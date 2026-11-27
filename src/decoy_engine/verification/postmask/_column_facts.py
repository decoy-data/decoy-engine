"""Exact per-column facts for the post-scan column suite, computed over batches.

Every number is a count (or a ratio of two counts), so it does not depend on where a batch
starts or ends. Detector rates sum hits and non-null values over the batches before the
threshold test; averaging per-batch rates would not equal the whole-column rate.

Source and output are read in lockstep and re-cut to equal lengths, because the two readers
need not share batch boundaries. When the row counts differ the positional comparison is
skipped, as `residual_pii` and `policy_validation` do. Holds counts, names and detector ids only.

The distribution check (`post_scan.distribution`) adds null counts and streamed moments (count,
mean, sum of squared deviations). They merge per batch by the pairwise formula of Chan, Golub and
LeVeque, "Updating formulae and a pairwise algorithm for computing sample variances" (1979), so
batch cuts do not change the result and no raw sum of squares is kept. The output side comes from
the pass that already runs (`ColumnFacts.output_values`); the source side is a source-only pass,
`value_facts`, because the lockstep pass pairs the sides only when their row counts match, which
quarantine breaks. Aggregates only: no value reaches a field here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError, postmask_not_inspectable
from decoy_engine.detection.detectors import counting_scope, decide_detector, run_all_detectors
from decoy_engine.internal.pandas_compat import (
    arrow_to_series,
    exact_int_types_mapper,
)
from decoy_engine.profiling import KEY_BATCH_ROWS, column_distinct, passes_through
from decoy_engine.verification.postmask._stream_input import TableBatches, key_batches


@dataclass(frozen=True)
class Moments:
    """Count, mean and sum of squared deviations (M2) of a set of numbers, mergeable in any
    grouping."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    @classmethod
    def of(cls, values: np.ndarray) -> Moments:
        n = int(values.size)
        if n == 0:
            return cls()
        # A spread past the float range overflows to infinity; the caller withholds such moments.
        with np.errstate(over="ignore"):
            mean = float(values.mean())
            return cls(n, mean, float(np.square(values - mean).sum()))

    def merge(self, other: Moments) -> Moments:
        if other.count == 0:
            return self
        if self.count == 0:
            return other
        n = self.count + other.count
        delta = other.mean - self.mean
        return Moments(
            n,
            self.mean + delta * other.count / n,
            self.m2 + other.m2 + delta * delta * self.count * other.count / n,
        )

    @property
    def std(self) -> float | None:
        """The sample standard deviation, or `None` below two values."""
        return math.sqrt(self.m2 / (self.count - 1)) if self.count > 1 else None


@dataclass(frozen=True)
class ValueFacts:
    """Null count and moments of one column. `moments` is `None` for a column that is not an
    integer or float, one that holds a non-finite value, and one whose read failed (`error`
    then holds the class name of the failure, never its message)."""

    rows: int
    nulls: int
    moments: Moments | None
    error: str | None = None
    # True when the column held a non-finite value (infinity, NaN, or a spread past the float
    # range), so the moments are withheld. Distinct from a non-numeric column.
    non_finite: bool = False

    @property
    def non_null(self) -> int:
        return self.rows - self.nulls


@dataclass
class _ValueTally:
    numeric: bool
    rows: int = 0
    nulls: int = 0
    moments: Moments = field(default_factory=Moments)
    # Exact extremes of the finite values, internal only. A constant column has min == max, and
    # its moments are then exact (`done`): the pairwise merge of a constant leaves a mean and an M2
    # a few ulps off, which would read as a spread.
    low: float = math.inf
    high: float = -math.inf
    finite: bool = True
    error: str | None = None

    def add(self, array: pa.Array) -> None:
        if self.error is not None:
            return
        try:
            self.rows += len(array)
            self.nulls += array.null_count
            if self.numeric and self.finite:
                values = array.drop_null().to_numpy(zero_copy_only=False).astype("float64")
                merged = (
                    self.moments.merge(Moments.of(values)) if np.isfinite(values).all() else None
                )
                # A sum of squared deviations can overflow on finite values; withhold it too.
                if merged is not None and math.isfinite(merged.mean) and math.isfinite(merged.m2):
                    self.moments = merged
                    if values.size:
                        self.low = min(self.low, float(values.min()))
                        self.high = max(self.high, float(values.max()))
                else:
                    self.finite = False
        except Exception as exc:
            if passes_through(exc):
                raise
            self.error = type(exc).__name__

    def done(self) -> ValueFacts:
        keeps = self.numeric and self.finite and self.error is None
        moments = self.moments
        if moments.count and self.low == self.high:
            moments = Moments(moments.count, self.low, 0.0)
        return ValueFacts(
            self.rows,
            self.nulls,
            moments if keeps else None,
            self.error,
            non_finite=self.numeric and not self.finite and self.error is None,
        )


def _is_numeric(schema: pa.Schema, column: str) -> bool:
    # By position, not `schema.field(name)`, which raises on a duplicated column name.
    data_type = schema.types[schema.names.index(column)]
    return pa.types.is_integer(data_type) or pa.types.is_floating(data_type)


@dataclass(frozen=True)
class DetectorRate:
    """A detector that fires on the whole output column, as `run_all_detectors` reports it."""

    detector_id: str
    match_rate: float
    confidence: str


@dataclass(frozen=True)
class ColumnFacts:
    """Counts for one configured column. `comparable_rows` and `identical_rows` are 0 and
    `bytes_identical` is False when there is no source column or the row counts differ."""

    table: str
    column: str
    source_rows: int
    output_rows: int
    comparable_rows: int
    identical_rows: int
    bytes_identical: bool
    source_distinct: int
    output_distinct: int
    detectors: tuple[DetectorRate, ...]
    # Class names of uncoded failures on this one column: comparing source with output (identity
    # and bytes_identical are then unavailable), and counting distinct values (that count is then
    # 0). The detector rates are exact either way.
    identity_error: str | None = None
    distinct_error: str | None = None
    # True when the failed count was the source's, so a zero source_distinct means unknown.
    source_distinct_failed: bool = False
    # Null count and moments of the output column, from the same pass as the detector rates.
    output_values: ValueFacts | None = None

    @property
    def error(self) -> str | None:
        return self.identity_error or self.distinct_error

    @property
    def source_constant(self) -> bool:
        return self.source_distinct <= 1


@dataclass
class _Tally:
    comparable: int = 0
    identical: int = 0
    same_bytes: bool = True
    error: str | None = None
    # True when the output column itself could not be read (no detectors, no values).
    unreadable: bool = False
    # Set when the output or source column could not be read. Separate from `error`, which a later
    # length mismatch takes over, so the inspection failure is never lost.
    not_inspectable: bool = False
    # detector id -> [hits, non-null values, threshold, name hint]
    detectors: dict[str, list[float | bool]] | None = None
    values: _ValueTally | None = None


_NOT_INSPECTABLE_CODE = reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE
_LENGTH_MISMATCH_CODE = reasons.runtime.POSTMASK_SOURCE_LENGTH_MISMATCH


def _output_series(
    src_batch: pa.RecordBatch | None, out_batch: pa.RecordBatch, column: str, tally: _Tally
) -> pd.Series:
    """The output column as a series, with the identity tally run against the source when the
    column is compared. The dtype comes from the schema, so a null in one batch cannot retype an
    integer column. An output column pandas cannot hold raises the
    `postmask_column_not_inspectable` error. A source column it cannot hold only marks the tally,
    so the output is still read and its detectors still run."""
    out_s = _read(out_batch, column)
    if src_batch is None or tally.error is not None:
        return out_s
    try:
        src_s = _read(src_batch, column)
    except ExecutionError as exc:
        if exc.code != _NOT_INSPECTABLE_CODE:
            raise
        tally.error = exc.code
        tally.not_inspectable = True
        return out_s
    try:
        _add_identity(tally, src_s, out_s)
    except Exception as exc:
        # One column that cannot be compared (a list or map cell, say) must not take the other
        # columns down with it.
        if passes_through(exc):
            raise
        tally.error = type(exc).__name__
    return out_s


def _read(batch: pa.RecordBatch, column: str) -> pd.Series:
    return arrow_to_series(
        batch.column(batch.schema.get_field_index(column)),
        on_unrepresentable=postmask_not_inspectable,
        types_mapper=exact_int_types_mapper,
        name=column,
    )


def _aligned(
    left: Iterator[pa.RecordBatch],
    right: Iterator[pa.RecordBatch],
    on_length_mismatch: Callable[[], None],
) -> Iterator[tuple[pa.RecordBatch | None, pa.RecordBatch]]:
    """Pairs of batches of equal length covering both streams in order.

    The right stream is the output: every one of its rows is yielded, with `None` for the source
    batch once the source has ended, so no output row goes uninspected. When the two streams turn
    out to differ in length, positional identity is meaningless and `on_length_mismatch` runs."""
    a = b = None
    while True:
        while a is None or a.num_rows == 0:
            a = next(left, None)
            if a is None:
                break
        while b is None or b.num_rows == 0:
            b = next(right, None)
            if b is None:
                break
        if b is None:
            if a is not None:
                on_length_mismatch()
            for _ in left:  # drain so the row-count check sees every source row
                pass
            return
        if a is None:
            on_length_mismatch()
            yield None, b
            yield from ((None, rest) for rest in right)
            return
        n = min(a.num_rows, b.num_rows)
        if n:
            yield a.slice(0, n), b.slice(0, n)
        a, b = a.slice(n), b.slice(n)


def _add_identity(tally: _Tally, src: pd.Series, out: pd.Series) -> None:
    src_o, out_o = src.astype(object), out.astype(object)
    present = src_o.notna() & out_o.notna()
    tally.comparable += int(present.sum())
    tally.identical += int((src_o[present] == out_o[present]).sum())
    # A null is NaN in a float column and pd.NA in an Arrow-typed integer one; `equals` treats
    # NaN and None as one null but not NaN and pd.NA, so a float source against an int output of
    # the same numbers would read as different.
    tally.same_bytes = tally.same_bytes and bool(
        src_o.where(src_o.notna(), None).equals(out_o.where(out_o.notna(), None))
    )


def _add_detectors(tally: _Tally, out: pd.Series, column: str) -> None:
    with counting_scope() as counts:
        run_all_detectors(out, column)
    seen = tally.detectors if tally.detectors is not None else {}
    for c in counts:
        row = seen.setdefault(c.detector_id, [0, 0, c.threshold, c.name_hint])
        row[0] = int(row[0]) + c.hits
        row[1] = int(row[1]) + c.n
    tally.detectors = seen


def _fired(tally: _Tally) -> tuple[DetectorRate, ...]:
    rates = []
    for detector_id, (hits, n, threshold, name_hint) in (tally.detectors or {}).items():
        decided = decide_detector(int(hits), int(n), float(threshold), bool(name_hint))
        if decided is not None:
            rates.append(DetectorRate(detector_id, round(decided[0], 4), decided[1]))
    return tuple(sorted(rates, key=lambda r: r.match_rate, reverse=True))


def _counted(table: TableBatches) -> tuple[TableBatches, Callable[[], None]]:
    """`table` with a row tally over its reads, and a check that the tally equals its declared
    row count. A stream that ends early or runs long would otherwise leave facts over a prefix."""
    seen = [0]

    def read(columns: Sequence[str], batch_rows: int) -> Iterator[pa.RecordBatch]:
        for batch in table.read(columns, batch_rows):
            seen[0] += batch.num_rows
            yield batch

    def verify() -> None:
        # A table that drops rows on read (a declared cast) may give fewer rows, never more.
        if seen[0] > table.num_rows or (seen[0] != table.num_rows and not table.drops_rows):
            raise ValueError(
                f"column facts: a table read gave {seen[0]} rows but the table declares "
                f"{table.num_rows}"
            )

    return replace(table, read=read), verify


def _distinct_or_error(
    table: TableBatches, column: str, scratch: Path, limit: str
) -> tuple[int, str | None]:
    """The count and no error, or zero and the class name of an uncoded failure counting this one
    column. A short or long stream is not such a failure: `verify` refuses it for every column."""
    counted, verify = _counted(table)
    try:
        count = column_distinct(key_batches(counted, [column]), scratch=scratch, memory_limit=limit)
    except Exception as exc:
        if passes_through(exc):
            raise
        return 0, type(exc).__name__
    verify()
    return count, None


def column_facts(
    source: TableBatches | None,
    output: TableBatches,
    columns: Sequence[str],
    *,
    batch_rows: int = KEY_BATCH_ROWS,
    scratch: Path,
    memory_limit: str,
    value_columns: Collection[str] | None = None,
) -> dict[str, ColumnFacts]:
    """Facts for each of `columns` that the output has, keyed by column name.

    `value_columns` names the columns whose output null counts and moments are tallied
    (`ColumnFacts.output_values`); `None` tallies every column. The run passes only the columns
    a distribution check reads, so an unconfigured run pays nothing for them."""
    wanted = [c for c in columns if c in output.schema.names]
    if not wanted:
        return {}
    compared = [c for c in wanted if source is not None and c in source.schema.names]
    aligned = source is not None and source.num_rows == output.num_rows
    tallied = set(wanted if value_columns is None else value_columns)
    tallies = {
        c: _Tally(values=_ValueTally(_is_numeric(output.schema, c)) if c in tallied else None)
        for c in wanted
    }
    out_read, out_verify = _counted(output)
    checks = [out_verify]
    if aligned and source is not None and compared:
        src_read, src_verify = _counted(source)
        checks.append(src_verify)

        def lengths_differ() -> None:
            # Positional identity is void: fail closed on every compared column.
            for c in compared:
                tallies[c].error = _LENGTH_MISMATCH_CODE

        pairs = _aligned(
            src_read.read(compared, batch_rows),
            out_read.read(wanted, batch_rows),
            lengths_differ,
        )
    else:
        compared = []
        pairs = ((None, b) for b in out_read.read(wanted, batch_rows))
    for src_batch, out_batch in pairs:
        for c in wanted:
            if tallies[c].unreadable:
                continue  # a batch already showed this column cannot be read
            try:
                out_s = _output_series(
                    src_batch if c in compared else None, out_batch, c, tallies[c]
                )
            except ExecutionError as exc:
                if exc.code != _NOT_INSPECTABLE_CODE:
                    raise
                # An earlier length mismatch keeps `error`; the failure is recorded either way.
                tallies[c].error = tallies[c].error or exc.code
                tallies[c].not_inspectable = True
                tallies[c].unreadable = True
                continue
            _add_detectors(tallies[c], out_s, c)
            values = tallies[c].values
            if values is not None:
                values.add(out_batch.column(out_batch.schema.get_field_index(c)))
    for check in checks:
        check()
    facts = {}
    for c in wanted:
        t = tallies[c]
        has_source = source is not None and c in source.schema.names
        distinct_failed = None
        source_failed = False
        distinct = [0, 0]
        for n, (table, present) in enumerate(((source, has_source), (output, True))):
            if present and table is not None:
                distinct[n], err = _distinct_or_error(table, c, scratch, memory_limit)
                distinct_failed = distinct_failed or err
                source_failed = source_failed or (n == 0 and err is not None)
        facts[c] = ColumnFacts(
            table=output.name,
            column=c,
            source_rows=source.num_rows if source is not None else 0,
            output_rows=output.num_rows,
            comparable_rows=0 if t.error else t.comparable,
            identical_rows=0 if t.error else t.identical,
            bytes_identical=aligned and c in compared and t.same_bytes and not t.error,
            source_distinct=distinct[0],
            output_distinct=distinct[1],
            detectors=_fired(t),
            identity_error=t.error,
            # The inspection code wins over a failed distinct count: the gate keys its
            # unconditional residual-PII finding on it.
            distinct_error=(_NOT_INSPECTABLE_CODE if t.not_inspectable else None)
            or distinct_failed,
            source_distinct_failed=source_failed,
            output_values=t.values.done() if t.values is not None else None,
        )
    return facts


def distinct_counts(
    table: TableBatches, columns: Sequence[str], *, scratch: Path, memory_limit: str
) -> dict[str, int | None]:
    """The distinct count of each of `columns` that `table` has, or `None` for one whose count
    failed with an uncoded error."""
    counts: dict[str, int | None] = {}
    for column in dict.fromkeys(columns):
        if column in table.schema.names:
            count, error = _distinct_or_error(table, column, scratch, memory_limit)
            counts[column] = None if error is not None else count
    return counts


def value_facts(
    table: TableBatches, columns: Sequence[str], *, batch_rows: int = KEY_BATCH_ROWS
) -> dict[str, ValueFacts]:
    """Null count and moments of each of `columns` that `table` has, in one read of the table.

    A short or long stream is refused (`ValueError`) rather than answered over a prefix."""
    wanted = [c for c in dict.fromkeys(columns) if c in table.schema.names]
    if not wanted:
        return {}
    tallies = {c: _ValueTally(_is_numeric(table.schema, c)) for c in wanted}
    counted, verify = _counted(table)
    for batch in counted.read(wanted, batch_rows):
        for c in wanted:
            tallies[c].add(batch.column(batch.schema.get_field_index(c)))
    verify()
    return {c: t.done() for c, t in tallies.items()}
