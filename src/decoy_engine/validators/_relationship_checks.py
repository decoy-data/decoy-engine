"""Relationship-aware validators: parent_window_respected, reconciliation_holds
(Sprint 2 honesty pack, S4 / p5-j-validators-extended).

Both validators mirror `_fk_validators.py`'s parent-first edge-lookup pattern
(SDV HMA1 method, Patki et al., IEEE DSAA 2016; method only, no SDV code: SDV is
BUSL-1.1): find the declared `relationships:` edge linking
the two named tables, resolve child rows to their parent via the edge's FK
columns, then apply the validator's own check. No second join mechanism is
invented (trap T8); `_edge_for` below is the one lookup helper both share.

parent_window_respected pairs with the `windowed_date` generate strategy:
every child date must fall within its parent's declared window (dbt
relationship-test style, inclusive bounds).

reconciliation_holds pairs with the `derived_aggregate` strategy: a parent
aggregate cell must reconcile with its child rows under an absolute
tolerance (dbt-style relationship/aggregation test; money data legitimately
reconciles to a cent, hence the tolerance knob).

Both are folds that take the parent and child tables in either order. Child rows that arrive
before their parent table has completed wait in a pending map (parent_window_respected) or in
per-key sums (reconciliation_holds, which compares only when both sides are done). Every
retained key, pending observation and parent row is reserved against the key-state budget.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.validators._dates import OneFormatDates, require_columns
from decoy_engine.validators._fk_validators import (
    _child_fk_values,
    _extract_relationships,
    key_bytes,
)
from decoy_engine.validators._fold import (
    CappedIndices,
    FoldResult,
    KeyStateBudget,
    finding_index_cap,
    run_whole,
)
from decoy_engine.validators._params import numeric_param
from decoy_engine.validators._types import RowSpan, SkippedColumn, ValidatorFinding


def _edge_for(
    config: dict[str, Any], *, parent_table: str, child_table: str, validator_name: str
) -> dict[str, Any]:
    """Return the unique relationship edge linking parent_table -> child_table.

    Raises ValueError (fail loud, D2's no-silent-skip rule) when zero or more
    than one edge matches: an ambiguous or missing edge must not silently
    produce zero findings.
    """
    matches = []
    for rel in _extract_relationships(config):
        parent_info = rel.get("parent") or {}
        if parent_info.get("table") != parent_table:
            continue
        children = rel.get("children") or []
        if not isinstance(children, list):
            continue
        if any(isinstance(c, dict) and c.get("table") == child_table for c in children):
            matches.append(rel)
    if len(matches) != 1:
        raise ValueError(
            f"{validator_name}: found {len(matches)} relationship edge(s) linking "
            f"parent {parent_table!r} -> child {child_table!r} (expected exactly 1). "
            "Declare exactly one relationships: entry for this pair."
        )
    return matches[0]


def _require_params(params: dict[str, Any], keys: list[str], validator_name: str) -> None:
    missing = [k for k in keys if not params.get(k)]
    if missing:
        raise ValueError(
            f"{validator_name} validator requires params {missing!r} (all are required strings)."
        )


# ---------------------------------------------------------------------------
# parent_window_respected
# ---------------------------------------------------------------------------

_OBSERVATION_BYTES = 200


def _first_missing(out: Any, columns: list[str]) -> str | None:
    """The first of ``columns`` the table lacks, or None when it holds them all."""
    return next((c for c in columns if c not in out.schema.names), None)


class ParentWindowFold:
    """parent_window_respected: every child date falls within its parent's window.

    Bounds are inclusive on both ends. A non-null child date that fails to parse IS a finding
    (a generated date that does not parse is itself a defect); null child dates are skipped. A
    null or unparseable parent window bound makes every child row mapped to that parent a
    finding (the window cannot be verified: fail loud, D2's no-silent-skip rule), not a skip.

    A child row waits as ``(row_index, parsed_date, raw_is_null)`` until its parent table has
    completed. The raw-null flag is kept beside the parsed date because a null cell and a
    malformed value both parse to NaT, and the verdict differs (skip against fail). Every
    observation is kept, so two children of one parent cannot overwrite each other.

    Raises:
        ValueError: Missing params, or zero/multiple matching relationship edges (at
            construction); the parent table never observed (at finish).
    """

    def __init__(
        self,
        entry: dict[str, Any],
        config: dict[str, Any],
        *,
        cap: int | None,
        budget: KeyStateBudget,
    ) -> None:
        params: dict[str, Any] = entry.get("params") or {}
        _require_params(
            params,
            [
                "child_table",
                "child_column",
                "parent_table",
                "window_start_column",
                "window_end_column",
            ],
            "parent_window_respected",
        )
        self._child_table: str = params["child_table"]
        self._child_column: str = params["child_column"]
        self._parent_table: str = params["parent_table"]
        self._start_col: str = params["window_start_column"]
        self._end_col: str = params["window_end_column"]
        edge = _edge_for(
            config,
            parent_table=self._parent_table,
            child_table=self._child_table,
            validator_name="parent_window_respected",
        )
        self._parent_cols: list[str] = (edge.get("parent") or {}).get("columns") or []
        child_info = next(
            c
            for c in edge.get("children") or []
            if isinstance(c, dict) and c.get("table") == self._child_table
        )
        self._child_fk_cols: list[str] = child_info.get("columns") or []
        self._budget = budget
        self._failing = CappedIndices(cap)
        self._starts = OneFormatDates()
        self._ends = OneFormatDates()
        self._children = OneFormatDates()
        self._windows: dict[tuple[Any, ...], tuple[int | None, int | None]] = {}
        # key -> (row_index, parsed microseconds or None, raw cell was null), in arrival order.
        self._pending: dict[tuple[Any, ...], list[tuple[int, int | None, bool]]] = {}
        self._parent_seen = False
        self._parent_complete = False
        self._child_seen = False
        self._child_checked = False
        self._child_gap: str | None = None

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def add(self, table: str, span: RowSpan) -> None:
        if table == self._parent_table:
            self._add_parent(span)
        if table == self._child_table:
            self._add_child(span)

    def _add_parent(self, span: RowSpan) -> None:
        self._parent_seen = True
        out = span.output
        require_columns(
            span, self._parent_table, [*self._parent_cols, self._start_col, self._end_col]
        )
        pk_lists = [out.column(c).to_pylist() for c in self._parent_cols]
        starts = self._starts.parse(out.column(self._start_col).to_pylist())
        ends = self._ends.parse(out.column(self._end_col).to_pylist())
        for i in range(out.num_rows):
            key = tuple(col[i] for col in pk_lists)
            if any(v is None for v in key):
                continue
            if key not in self._windows:
                self._budget.reserve(
                    key_bytes(key) + _OBSERVATION_BYTES,
                    table=self._parent_table,
                    column=None,
                )
            self._windows[key] = (starts[i], ends[i])

    def _add_child(self, span: RowSpan) -> None:
        out = span.output
        self._child_seen = True
        gap = _first_missing(out, [self._child_column, *self._child_fk_cols])
        if gap is not None:
            self._child_gap = self._child_gap or gap
            return
        self._child_checked = True
        raw = out.column(self._child_column).to_pylist()
        dates = self._children.parse(raw)
        for i, fk in enumerate(_child_fk_values(out, self._child_fk_cols)):
            if fk is None:
                continue  # null FK: not this validator's concern (see no_orphan_children)
            observation = (span.offset + i, dates[i], raw[i] is None)
            if self._parent_complete:
                self._judge(observation, self._windows.get(fk))
                continue
            waiting = self._pending.get(fk)
            if waiting is None:
                self._budget.reserve(
                    key_bytes(fk),
                    table=self._child_table,
                    column=self._child_column,
                )
                waiting = self._pending[fk] = []
            self._budget.reserve(
                _OBSERVATION_BYTES, table=self._child_table, column=self._child_column
            )
            waiting.append(observation)

    def _judge(
        self,
        observation: tuple[int, int | None, bool],
        window: tuple[int | None, int | None] | None,
    ) -> None:
        index, date, raw_is_null = observation
        if raw_is_null:
            return  # null child date: skipped, not a violation
        if date is None:
            self._failing.add(index)  # non-null child date that fails to parse: a defect
            return
        if window is None:
            return  # FK does not resolve to a parent row: fk_intact's concern, not this one
        start, end = window
        if start is None or end is None:
            self._failing.add(index)  # window cannot be verified: fail loud, not skip
            return
        if not (start <= date <= end):
            self._failing.add(index)

    def table_complete(self, table: str) -> None:
        if table != self._parent_table or self._parent_complete:
            return
        self._parent_complete = True
        for fk, waiting in self._pending.items():
            window = self._windows.get(fk)
            for observation in waiting:
                self._judge(observation, window)
            self._budget.release(key_bytes(fk) + _OBSERVATION_BYTES * len(waiting))
        self._pending.clear()

    def finish(self) -> FoldResult:
        if not self._parent_seen:
            raise ValueError(
                f"parent_window_respected: parent table {self._parent_table!r} not found in "
                "outputs."
            )
        self.table_complete(self._parent_table)
        if not self._child_checked:
            code = (
                reasons.warning.VALIDATOR_SKIP_MISSING_COLUMN
                if self._child_seen
                else reasons.warning.VALIDATOR_SKIP_MISSING_TABLE
            )
            column = (self._child_gap or self._child_column) if self._child_seen else None
            return FoldResult((), (), (SkippedColumn(self._child_table, column, code),))
        checked = ((self._child_table, self._child_column),)
        count = self._failing.count
        if not count:
            return FoldResult((), checked)
        return FoldResult(
            (
                ValidatorFinding(
                    validator="parent_window_respected",
                    table=self._child_table,
                    column=self._child_column,
                    failing_row_indices=self._failing.indices(),
                    detail=(
                        f"{count} row(s) in {self._child_table}.{self._child_column} fall "
                        f"outside the parent {self._parent_table!r} window "
                        f"({self._start_col}..{self._end_col}), fail to parse, or map to an "
                        "unverifiable (null/unparseable) parent window"
                    ),
                    failing_row_count=count,
                ),
            ),
            checked,
        )


def validate_parent_window_respected(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """parent_window_respected over whole tables (see `ParentWindowFold`).

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block; requires `params.child_table`, `child_column`,
            `parent_table`, `window_start_column`, `window_end_column`.
        config: Full pipeline config dict; the relationship edge is read
            from `config["relationships"]`.
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding (at most one, for the child table).

    Raises:
        ValueError: Missing params, zero/multiple matching relationship edges for
            (parent_table, child_table), or the parent table absent from the outputs.
    """
    fold = ParentWindowFold(
        entry, config, cap=finding_index_cap(config), budget=KeyStateBudget(None)
    )
    return run_whole(fold, outputs).findings


# ---------------------------------------------------------------------------
# reconciliation_holds
# ---------------------------------------------------------------------------

_OPS = frozenset({"sum", "count"})
_PARENT_ROW_BYTES = 160


class ReconciliationFold:
    """reconciliation_holds: a parent aggregate reconciles with its child rows.

    Groups child rows by the FK edge, applies `op` ("sum" default, or "count"), and compares
    the result to the parent cell with an absolute tolerance (`math.isclose`-style, default
    1e-6). Non-numeric parent or child cells are findings, not skips (a reconciliation that
    cannot be computed is itself a defect).

    The child sums and the parent rows are kept until both tables are done, then compared, so
    the verdict does not depend on which table came first. One finding per parent table;
    `failing_row_indices` are the PARENT rows whose reconciliation failed. `detail` carries the
    worst absolute delta observed.

    Raises:
        ValueError: Missing params, unknown `op`, or zero/multiple matching relationship edges
            (at construction); the parent table never observed (at finish).
    """

    def __init__(
        self,
        entry: dict[str, Any],
        config: dict[str, Any],
        *,
        cap: int | None,
        budget: KeyStateBudget,
    ) -> None:
        params: dict[str, Any] = entry.get("params") or {}
        _require_params(
            params,
            ["parent_table", "parent_column", "child_table", "child_column"],
            "reconciliation_holds",
        )
        self._parent_table: str = params["parent_table"]
        self._parent_column: str = params["parent_column"]
        self._child_table: str = params["child_table"]
        self._child_column: str = params["child_column"]
        self._op: str = str(params.get("op", "sum"))
        self._tolerance: float = float(
            numeric_param(
                params, "tolerance", kind=float, default=1e-6, validator="reconciliation_holds"
            )
        )
        if self._op not in _OPS:
            raise ValueError(
                f"reconciliation_holds: params.op is not a known op. Known ops: {sorted(_OPS)}."
            )
        edge = _edge_for(
            config,
            parent_table=self._parent_table,
            child_table=self._child_table,
            validator_name="reconciliation_holds",
        )
        self._parent_pk_cols: list[str] = (edge.get("parent") or {}).get("columns") or []
        child_info = next(
            c
            for c in edge.get("children") or []
            if isinstance(c, dict) and c.get("table") == self._child_table
        )
        self._child_fk_cols: list[str] = child_info.get("columns") or []
        self._budget = budget
        self._cap = cap
        # Group "count": row count. "sum": numeric sum; a non-numeric non-null cell makes the
        # whole group unreconcilable (`_bad`), which the parent-side compare turns into a finding.
        self._agg: dict[tuple[Any, ...], float] = {}
        self._bad: set[tuple[Any, ...]] = set()
        self._parent_rows: list[tuple[int, tuple[Any, ...], Any]] = []
        self._parent_seen = False
        self._parent_has_column = False
        self._child_seen = False
        self._child_has_column = False
        self._child_gap: str | None = None

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def table_complete(self, table: str) -> None:
        return None

    def add(self, table: str, span: RowSpan) -> None:
        if table == self._parent_table:
            self._add_parent(span)
        if table == self._child_table:
            self._add_child(span)

    def _add_parent(self, span: RowSpan) -> None:
        out = span.output
        self._parent_seen = True
        require_columns(span, self._parent_table, self._parent_pk_cols)
        if self._parent_column not in out.schema.names:
            return
        self._parent_has_column = True
        pk_lists = [out.column(c).to_pylist() for c in self._parent_pk_cols]
        values = out.column(self._parent_column).to_pylist()
        self._budget.reserve(
            _PARENT_ROW_BYTES * out.num_rows,
            table=self._parent_table,
            column=self._parent_column,
        )
        for i in range(out.num_rows):
            self._parent_rows.append(
                (span.offset + i, tuple(col[i] for col in pk_lists), values[i])
            )

    def _add_child(self, span: RowSpan) -> None:
        out = span.output
        self._child_seen = True
        gap = _first_missing(out, [self._child_column, *self._child_fk_cols])
        if gap is not None:
            self._child_gap = self._child_gap or gap
            return
        self._child_has_column = True
        raw = out.column(self._child_column).to_pylist()
        for i, fk in enumerate(_child_fk_values(out, self._child_fk_cols)):
            if fk is None:
                continue
            if self._op == "count":
                self._reserve_key(fk)
                self._agg[fk] = self._agg.get(fk, 0.0) + 1.0
                continue
            val = raw[i]
            if val is None:
                continue
            try:
                numeric = float(val)
            except (TypeError, ValueError):
                self._reserve_key(fk)
                self._bad.add(fk)
                continue
            self._reserve_key(fk)
            self._agg[fk] = self._agg.get(fk, 0.0) + numeric

    def _reserve_key(self, fk: tuple[Any, ...]) -> None:
        if fk not in self._agg and fk not in self._bad:
            self._budget.reserve(
                key_bytes(fk),
                table=self._child_table,
                column=self._child_column,
            )

    def _skips(self) -> tuple[SkippedColumn, ...]:
        missing_column = reasons.warning.VALIDATOR_SKIP_MISSING_COLUMN
        skips: list[SkippedColumn] = []
        if not self._child_seen:
            skips.append(
                SkippedColumn(self._child_table, None, reasons.warning.VALIDATOR_SKIP_MISSING_TABLE)
            )
        elif not self._child_has_column:
            skips.append(
                SkippedColumn(
                    self._child_table, self._child_gap or self._child_column, missing_column
                )
            )
        if not self._parent_has_column:
            skips.append(SkippedColumn(self._parent_table, self._parent_column, missing_column))
        return tuple(skips)

    def finish(self) -> FoldResult:
        if not self._parent_seen:
            raise ValueError(
                f"reconciliation_holds: parent table {self._parent_table!r} not found in outputs."
            )
        if not (self._child_seen and self._parent_has_column and self._child_has_column):
            return FoldResult((), (), self._skips())
        failing = CappedIndices(self._cap)
        worst_delta = 0.0
        for index, key, parent_val in self._parent_rows:
            if key in self._bad:
                failing.add(index)
                continue
            try:
                parent_numeric = float(parent_val) if parent_val is not None else None
            except (TypeError, ValueError):
                parent_numeric = None
            if parent_numeric is None:
                failing.add(index)
                continue
            delta = abs(parent_numeric - self._agg.get(key, 0.0))
            if delta > self._tolerance:
                failing.add(index)
                worst_delta = max(worst_delta, delta)
        checked = ((self._parent_table, self._parent_column),)
        if not failing.count:
            return FoldResult((), checked)
        return FoldResult(
            (
                ValidatorFinding(
                    validator="reconciliation_holds",
                    table=self._parent_table,
                    column=self._parent_column,
                    failing_row_indices=failing.indices(),
                    detail=(
                        f"{failing.count} row(s) in {self._parent_table}.{self._parent_column} "
                        f"do not reconcile with {self._child_table}.{self._child_column} "
                        f"({self._op}, tolerance={self._tolerance}); "
                        f"worst absolute delta observed: {worst_delta}"
                    ),
                    failing_row_count=failing.count,
                ),
            ),
            checked,
        )


def validate_reconciliation_holds(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """reconciliation_holds over whole tables (see `ReconciliationFold`).

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block; requires `params.parent_table`, `parent_column`,
            `child_table`, `child_column`; optional `op` (default "sum") and
            `tolerance` (default 1e-6).
        config: Full pipeline config dict; the relationship edge is read
            from `config["relationships"]`.
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding (at most one, for the parent table).

    Raises:
        ValueError: Missing params, unknown `op`, zero/multiple matching relationship edges
            for (parent_table, child_table), or the parent table absent from the outputs.
    """
    fold = ReconciliationFold(
        entry, config, cap=finding_index_cap(config), budget=KeyStateBudget(None)
    )
    return run_whole(fold, outputs).findings
