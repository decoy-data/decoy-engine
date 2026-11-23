"""leak_check: post-mask residual-value verification (Sprint 2 honesty pack,
S2 / p5-j-validators-extended, the load-bearing slice).

Established methodology (CLAUDE.md core rule): commercial masking tools
verify masking by comparing pre/post values per column and reporting the
percentage unchanged against a threshold (Delphix and Informatica "masking
verification" reports; Microsoft Presidio's evaluator counts residual
original values). The column-pair comparison itself is the Great
Expectations `expect_column_pair_values_A_to_not_equal_B` pattern. No tool
asserts "every cell must differ": legitimate masking produces occasional
coincidences (Faker can emit the source value; FPE is a permutation and
permutations have fixed points, non-trivially likely on small domains;
bucketize's lower/range/midpoint format returns the source value for cells
already on a bucket boundary; date_shift with `min_days <= 0 <= max_days` can
legitimately shift by zero). A naive per-cell equality assert WILL
false-positive on legitimately-masked data (trap T1); this module uses a
threshold-per-column design instead.

Two tiers (D3):

1. Column tier (all non-excluded columns): `identical_ratio == 1.0` over
   non-null compared cells (with `min_rows` non-null cells present) means the
   declared strategy had NO effect on the column at all -- the
   forgot-to-mask safety net.
2. Cell tier (TRANSFORMATIVE columns only): `identical_ratio >
   max_identical_ratio` flags residual per-row leaks; `failing_row_indices`
   make the finding quarantinable row-by-row under the existing
   `validation_fail` trigger.

Strategy classification (the false-positive control, trap T1) and the scope of an entry live in
`_scope.py`; the names stay importable from here. The validator is a fold: it takes the output
rows and their source rows span by span and keeps, per column, the compared count, an exact
identical count and the first `FINDING_INDEX_CAP` identical positions. Every column or table it
does not check is recorded with a registered `leak_check_skip_*` code.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators._fold import CappedIndices, FoldResult, finding_index_cap, run_whole
from decoy_engine.validators._scope import (
    _COMPOSITE_PROVIDERS,
    EXCLUDED,
    SHAPE_PRESERVING,
    TRANSFORMATIVE,
    ScopedColumn,
    plan_scope,
)
from decoy_engine.validators._types import RowSpan, SkippedColumn, ValidatorFinding

__all__ = [
    "EXCLUDED",
    "SHAPE_PRESERVING",
    "TRANSFORMATIVE",
    "_COMPOSITE_PROVIDERS",
    "LeakCheckFold",
    "validate_leak_check",
]


def _is_identical(src: Any, out: Any) -> bool:
    """Canonical cell-identity compare (D3). Caller guarantees `src is not None`."""
    if out is None:
        return False  # value -> null is redaction, not a leak
    if str(src) == str(out):
        return True
    try:
        return float(src) == float(out)
    except (TypeError, ValueError):
        return False


class _ColumnState:
    """Counters for one scoped column: compared cells and the identical ones."""

    __slots__ = ("compared", "identical", "present")

    def __init__(self, cap: int | None) -> None:
        self.compared = 0
        self.identical = CappedIndices(cap)
        self.present = False


class LeakCheckFold:
    """leak_check over output rows paired with their source rows.

    Missing-source rule (D2, fail-loud): a table in scope that reaches the fold without source
    rows raises, because a leak check that silently did not run is worse than none.

    Raises:
        ValueError: An explicit `columns:` entry names a generate-kind table (at construction),
            a table in scope has no source, or a column's strategy is not classified.
    """

    def __init__(self, entry: dict[str, Any], config: dict[str, Any], *, cap: int | None) -> None:
        params: dict[str, Any] = entry.get("params") or {}
        self._max_ratio = float(params.get("max_identical_ratio", 0.02))
        self._min_rows = int(params.get("min_rows", 1))
        self._plan = plan_scope(config, entry)
        # One state per occurrence in scope order: a column listed twice is two checks.
        self._by_table: dict[str, list[int]] = {}
        for position, col in enumerate(self._plan.columns):
            self._by_table.setdefault(col.table, []).append(position)
        self._state = [_ColumnState(cap) for _ in self._plan.columns]
        self._observed: set[str] = set()
        self._compared_tables: set[str] = set()

    def paired_tables(self) -> frozenset[str]:
        """Tables with at least one column that was read against its source."""
        return frozenset(self._compared_tables)

    def table_complete(self, table: str) -> None:
        return None

    def add(self, table: str, span: RowSpan) -> None:
        columns = self._by_table.get(table)
        if columns is None:
            return
        self._observed.add(table)
        if span.source is None:
            raise ValueError(
                f"leak_check configured for table {table!r} but no source table was "
                "provided; leak verification cannot run. Pass the source table via "
                "run_pipeline(sources=...) or exclude this table from leak_check's scope."
            )
        out_names = set(span.output.schema.names)
        src_names = set(span.source.schema.names)
        present = [
            position
            for position in columns
            if self._plan.columns[position].column in out_names
            and self._plan.columns[position].column in src_names
        ]
        for position in present:
            self._state[position].present = True
        reading = [p for p in present if self._plan.columns[p].skip is None]
        if reading and span.source.num_rows != span.output.num_rows:
            raise ValidatorStateError(
                code=reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH,
                message=f"the source rows for table {table!r} do not line up with its output rows.",
            )
        if reading:
            self._compared_tables.add(table)
        for position in reading:
            col = self._plan.columns[position]
            state = self._state[position]
            if col.kind == "unclassified":
                # Fail CLOSED (dennis review 2026-07-04): an unclassified strategy reaching here
                # means the drift sentry was bypassed, and silently skipping the column would
                # manufacture false confidence in a privacy product.
                raise ValueError(
                    f"leak_check: strategy {col.strategy!r} on {table}.{col.column} is not "
                    "classified as TRANSFORMATIVE, SHAPE_PRESERVING, or EXCLUDED. leak_check "
                    "cannot verify a strategy it does not know how to interpret; classify it "
                    "in decoy_engine.validators._scope (and its drift sentry) before use."
                )
            src_vals = span.source.column(col.column).to_pylist()
            out_vals = span.output.column(col.column).to_pylist()
            for i, (src_val, out_val) in enumerate(zip(src_vals, out_vals, strict=True)):
                if src_val is None:
                    continue  # null source: not a leak either way
                state.compared += 1
                if _is_identical(src_val, out_val):
                    state.identical.add(span.offset + i)

    def finish(self) -> FoldResult:
        findings: list[ValidatorFinding] = []
        checked: list[tuple[str, str | None]] = []
        skipped: list[SkippedColumn] = []
        for table in self._plan.tables:
            if table not in self._observed:
                skipped.append(
                    SkippedColumn(table, None, reasons.warning.LEAK_CHECK_SKIP_TABLE_NOT_PRODUCED)
                )
                continue
            for position in self._by_table[table]:
                col = self._plan.columns[position]
                state = self._state[position]
                if not state.present:
                    skipped.append(
                        SkippedColumn(
                            table, col.column, reasons.warning.LEAK_CHECK_SKIP_MISSING_COLUMN
                        )
                    )
                elif col.skip is not None:
                    skipped.append(SkippedColumn(table, col.column, col.skip))
                elif state.compared < self._min_rows or state.compared == 0:
                    skipped.append(
                        SkippedColumn(
                            table, col.column, reasons.warning.LEAK_CHECK_SKIP_BELOW_MIN_ROWS
                        )
                    )
                else:
                    checked.append((table, col.column))
                    findings.extend(self._verdict(col, state))
        return FoldResult(tuple(findings), tuple(checked), tuple(skipped))

    def _verdict(self, col: ScopedColumn, state: _ColumnState) -> list[ValidatorFinding]:
        identical = state.identical.count
        compared = state.compared
        ratio = identical / compared
        indices = state.identical.indices()
        found: list[ValidatorFinding] = []
        if ratio == 1.0:
            found.append(
                ValidatorFinding(
                    validator="leak_check",
                    table=col.table,
                    column=col.column,
                    failing_row_indices=indices,
                    detail=(
                        f"{identical} of {compared} non-null cells identical to "
                        f"source (ratio {ratio:.2f}); strategy {col.strategy!r} produced no "
                        "change"
                    ),
                    failing_row_count=identical,
                )
            )
        if col.kind == "transformative" and ratio > self._max_ratio:
            found.append(
                ValidatorFinding(
                    validator="leak_check",
                    table=col.table,
                    column=col.column,
                    failing_row_indices=indices,
                    detail=(
                        f"{identical} of {compared} non-null cells identical to "
                        f"source (ratio {ratio:.2f} > max_identical_ratio "
                        f"{self._max_ratio:.2f}) under strategy {col.strategy!r}"
                    ),
                    failing_row_count=identical,
                )
            )
        return found


def validate_leak_check(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """leak_check over whole tables: one span per table (see `LeakCheckFold`).

    Default scope (no `columns:` on the entry): every non-excluded column of every mask-kind
    table. Exclusions (D3): `passthrough` strategy, FK-child columns, and any column carrying a
    `when:` predicate; `params.exempt` is the documented operator escape hatch on top of these.
    Every exclusion is recorded with a registered code on the session's result.

    Args:
        outputs: Read-only pipeline outputs (post-mask).
        entry: Config block; optional `columns` (explicit scope) and `params` (`exempt`,
            `max_identical_ratio` default 0.02, `min_rows` default 1).
        config: Full pipeline config dict (`tables`, `relationships`).
        sources: Read-only pre-mask source tables (D2). Required for every table in scope that
            the run produced.

    Returns:
        Tuple of ValidatorFinding (column-tier and/or cell-tier per column).

    Raises:
        ValueError: A table in scope has no source table, or an explicit `columns:` entry names
            a generate-kind table.
    """
    fold = LeakCheckFold(entry, config, cap=finding_index_cap(config))
    return run_whole(fold, outputs, sources).findings
