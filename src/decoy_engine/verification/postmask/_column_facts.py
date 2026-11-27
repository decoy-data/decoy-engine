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
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine.detection.detectors import counting_scope, decide_detector, run_all_detectors
from decoy_engine.internal.pandas_compat import exact_int_types_mapper
from decoy_engine.plan.column_access import (
    TableWrites,
    config_child_keys,
    written_columns_by_table,
)
from decoy_engine.profiling import KEY_BATCH_ROWS, column_distinct, passes_through
from decoy_engine.providers_v2 import get_default_registry
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
        return self.constant(self.source_distinct)

    @staticmethod
    def constant(distinct: int) -> bool:
        """The one constant-source rule: with at most one distinct source value, an unchanged
        cell says nothing about whether the mask ran."""
        return distinct <= 1


@dataclass
class _Tally:
    comparable: int = 0
    identical: int = 0
    same_bytes: bool = True
    error: str | None = None
    # detector id -> [hits, non-null values, threshold, name hint]
    detectors: dict[str, list[float | bool]] | None = None
    values: _ValueTally | None = None


def _series(batch: pa.RecordBatch, column: str) -> pd.Series:
    # The dtype comes from the schema, so a null in one batch cannot retype an integer column.
    array = batch.column(batch.schema.get_field_index(column))
    return array.to_pandas(types_mapper=exact_int_types_mapper)


def _aligned(
    left: Iterator[pa.RecordBatch], right: Iterator[pa.RecordBatch]
) -> Iterator[tuple[pa.RecordBatch, pa.RecordBatch]]:
    """Pairs of batches of equal length covering both streams in order."""
    a = b = None
    while True:
        if a is None or a.num_rows == 0:
            a = next(left, None)
        if b is None or b.num_rows == 0:
            b = next(right, None)
        if a is None or b is None:
            # Exhaust both so the row-count check sees every row, not a prefix.
            for _ in left:
                pass
            for _ in right:
                pass
            return
        n = min(a.num_rows, b.num_rows)
        if n:
            yield a.slice(0, n), b.slice(0, n)
        a, b = a.slice(n), b.slice(n)


_MAPPING_TAG = object()


def _frozen(cell: Any) -> Any:
    if isinstance(cell, list | tuple | np.ndarray):
        return tuple(_frozen(v) for v in cell)
    if isinstance(cell, dict):
        # A frozenset of items: mapping equality ignores key order, as a JSON round trip may reorder.
        # Tagged, so a mapping never equals a set of key-value pairs.
        return (_MAPPING_TAG, frozenset((k, _frozen(v)) for k, v in cell.items()))
    if isinstance(cell, set | frozenset):
        return frozenset(_frozen(v) for v in cell)
    if isinstance(cell, bytearray | memoryview):
        # Equal to the same bytes under `==`, and hashable for a distinct count.
        return bytes(cell)
    return cell


def canonical_cells(series: pd.Series) -> pd.Series:
    """`series` as object cells in the one form both checks compare and count.

    A caller's frame holds a list cell as a Python list and a struct as a dict; the batch check
    reads them through Arrow as a NumPy array, and a map as a list of key-value tuples. Each
    container becomes a tuple (a set a frozenset), so a list equals the same list on either
    path, never its one element, and is hashable for a distinct count."""
    cells = series.astype(object)
    # Only an object column can hold a container; a typed one is passed as it is.
    if series.dtype != object:
        return cells
    # Not `Series.map`: it re-infers the result and rounds a wide float cell to a double.
    return pd.Series([_frozen(c) for c in cells], index=cells.index, dtype=object)


def source_distinct(series: pd.Series) -> int:
    """The non-null distinct cells of `series`, counted on the cells `identity_counts` compares."""
    return int(canonical_cells(series).nunique(dropna=True))


def identity_counts(src: pd.Series, out: pd.Series) -> tuple[int, int]:
    """Comparable and identical row counts of a positional source-to-output comparison.

    The one comparison the frame check and the batch check both run, so the two cannot grade
    the same cells differently. Both series must share a positional index. A cell comparison
    that fails raises; the caller records the class name as the column's `identity_error`."""
    src_o, out_o = canonical_cells(src), canonical_cells(out)
    present = src_o.notna() & out_o.notna()
    return int(present.sum()), int((src_o[present] == out_o[present]).sum())


def _add_identity(tally: _Tally, src: pd.Series, out: pd.Series) -> None:
    comparable, identical = identity_counts(src, out)
    tally.comparable += comparable
    tally.identical += identical
    src_o, out_o = src.astype(object), out.astype(object)
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


def _count_or_error(count: Callable[[], int]) -> tuple[int, str | None]:
    """`count()` and no error, or zero and the class name of an uncoded failure of that count."""
    try:
        return count(), None
    except Exception as exc:
        if passes_through(exc):
            raise
        return 0, type(exc).__name__


def cells_distinct_or_error(series: pd.Series) -> tuple[int, str | None]:
    """The distinct count of the cells of a frame column, or zero and the class name of the
    failure. The one count a frame column's facts and the table view read."""
    return _count_or_error(lambda: source_distinct(series))


def _distinct_or_error(
    table: TableBatches, column: str, scratch: Path, limit: str
) -> tuple[int, str | None]:
    """The count and no error, or zero and the class name of an uncoded failure counting this one
    column. A column with a cell view counts its cells, not its text keys. A short or long stream
    is not such a failure: `verify` refuses it for every column."""
    view = table.cell_views.get(column)
    if view is not None:
        return view.distinct, view.distinct_error
    counted, verify = _counted(table)
    count, error = _count_or_error(
        lambda: column_distinct(key_batches(counted, [column]), scratch=scratch, memory_limit=limit)
    )
    if error is None:
        verify()
    return count, error


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
        pairs = _aligned(src_read.read(compared, batch_rows), out_read.read(wanted, batch_rows))
    else:
        compared = []
        pairs = ((None, b) for b in out_read.read(wanted, batch_rows))
    offset = 0
    for src_batch, out_batch in pairs:
        for c in wanted:
            out_s = _series(out_batch, c)
            if src_batch is not None and c in compared and tallies[c].error is None:
                try:
                    _add_identity(tallies[c], _series(src_batch, c), out_s)
                except Exception as exc:
                    # One column that cannot be compared (a list or map cell, say) must not
                    # take the other columns down with it.
                    if passes_through(exc):
                        raise
                    tallies[c].error = type(exc).__name__
            view = output.cell_views.get(c)
            if view is None:
                _add_detectors(tallies[c], out_s, c)
            else:
                text = view.detector_text.slice(offset, out_batch.num_rows).to_pandas()
                _add_detectors(tallies[c], text, c)
            values = tallies[c].values
            if values is not None:
                values.add(out_batch.column(out_batch.schema.get_field_index(c)))
        offset += out_batch.num_rows
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
            distinct_error=distinct_failed,
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


def standalone_writes(
    config: Mapping[str, Any], schemas: Mapping[str, Sequence[str]]
) -> dict[str, TableWrites]:
    """The writer query for a caller with no compiled run: the tables' field names, the edges
    the config expands to and the default provider registry, the inputs a run with that config
    compiles. Relationships that do not expand give no answer, so no column is proven unwritten."""
    edges = config_child_keys(config)
    if edges is None:
        return {}
    return written_columns_by_table(
        config, schemas=schemas, edges=edges, registry=get_default_registry()
    )
