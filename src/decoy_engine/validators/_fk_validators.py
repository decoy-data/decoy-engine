"""FK-integrity validators: fk_intact and no_orphan_children (SP-05 / P5.INFRA.4).

Pattern: SDV HMA1 method (Patki, Wedge and Veeramachaneni, "The Synthetic Data Vault", IEEE DSAA 2016). Method only: no SDV code is used
or imported (SDV is BUSL-1.1). Parent-first DAG; materialise parent PK set;
resolve child FK values against it.

The two validators implement the parent-first DAG pattern from SDV's
HierarchicalMetaData (HMA1) model, adapted for integrity checking rather
than generation:

  fk_intact
    For every declared FK relationship, every non-null child FK value must
    resolve to an entry in the parent PK set. A null FK is not a broken
    reference (nullable FK columns are a legitimate pattern); only non-null
    values that do not appear in the parent PK set are violations.
    Mirrors the ``FAIL`` branch of the engine's existing orphan-policy
    machinery in ``relationships/_graph.py``.

  no_orphan_children
    For every declared FK relationship, every child row must have a non-null
    FK value. A null FK makes the child an orphan with no resolvable parent.
    This is stricter than fk_intact: fk_intact ignores nulls; this validator
    flags them.

Relationships are read from the ``relationships:`` block in the pipeline
config dict. Each entry is expected to have the shape::

    parent:
      table: <str>
      columns: [<str>, ...]
    children:
      - table: <str>
        columns: [<str>, ...]
    orphan_policy: fail | preserve | warn | remap

Both validators run over every relationship entry in the config regardless
of the ``orphan_policy`` field; the validator config's intent is separate
from the masking-phase orphan policy.

Both are folds. ``no_orphan_children`` reads each child row alone. ``fk_intact`` pairs a parent
key set with child rows that may arrive before their parent (a self-reference, or a parent table
written after its child): a child row whose parent table is not complete waits in a pending map
and is probed when the parent table completes. The key set and the pending map are reserved
against the key-state budget.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.validators._fold import (
    CappedIndices,
    FoldResult,
    KeyStateBudget,
    finding_index_cap,
    run_whole,
)
from decoy_engine.validators._types import RowSpan, SkippedColumn, ValidatorFinding

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_relationships(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of relationship entries from the pipeline config.

    Each entry has ``parent`` (with ``table`` and ``columns``) and
    ``children`` (a list of dicts with ``table`` and ``columns``).
    Returns an empty list when the config has no ``relationships:`` block.

    Args:
        config: Pipeline config dict (validated dump from PipelineConfig).

    Returns:
        List of relationship entry dicts (possibly empty).
    """
    rels = config.get("relationships") or []
    if not isinstance(rels, list):
        return []
    return [r for r in rels if isinstance(r, dict)]


def _parent_keys(
    table: pa.Table | pa.RecordBatch,
    columns: list[str],
    parent_table_name: str = "",
) -> Iterator[tuple[Any, ...]]:
    """Yield the non-null parent PK tuples of one span, in row order.

    Composite PKs are tuples in the order of ``columns``; a single-column PK is a 1-tuple.

    Raises:
        ValueError: If any column in ``columns`` is not present in ``table``. An absent column
            silently produces an empty PK set, which would make every child FK appear broken
            (mass false-positive quarantine).
    """
    table_cols = set(table.schema.names)
    missing = [c for c in columns if c not in table_cols]
    if missing:
        raise ValueError(
            f"misconfigured FK validator: column(s) {missing!r} not found in parent "
            f"table {parent_table_name!r}. Available columns: {sorted(table_cols)}"
        )
    if not columns:
        return
    col_arrays = [table.column(c).to_pylist() for c in columns]
    for row in zip(*col_arrays, strict=True):
        if any(v is None for v in row):
            continue  # skip null PK rows (defensive; PKs should be non-null)
        yield row


def _child_fk_values(
    table: pa.Table | pa.RecordBatch,
    columns: list[str],
) -> list[tuple[Any, ...] | None]:
    """Return per-row FK values for a child table.

    Each entry is either a tuple of FK column values (one per FK column),
    or None when all FK columns for that row are null (indicating a nullable
    FK relationship).

    Args:
        table: Child table (read-only; not mutated). The caller has checked it holds every
            column; a missing one is a skip, not a silent drop.
        columns: List of column names forming the child FK.

    Returns:
        List of tuples (or None) with one entry per row.
    """
    col_arrays = [table.column(c).to_pylist() for c in columns]
    if not col_arrays:
        return []
    # If ALL columns in the FK tuple are null, treat the whole FK as null.
    return [None if all(v is None for v in row) else row for row in zip(*col_arrays, strict=True)]


# ---------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------

# Fixed overhead of one retained key (tuple, set or dict entry) and the pointer cost of each
# value in it; the values themselves are charged by `sys.getsizeof`. The budget is a ceiling on
# retained state, so the estimate leans high.
_KEY_BASE_BYTES = 150
_KEY_COLUMN_BYTES = 16
_INDEX_BYTES = 60


def _skip_table(skipped: list[SkippedColumn], table: str) -> None:
    """Record a table the run did not produce, once."""
    record = SkippedColumn(table, None, reasons.warning.VALIDATOR_SKIP_MISSING_TABLE)
    if record not in skipped:
        skipped.append(record)


def key_bytes(key: tuple[Any, ...]) -> int:
    """Estimated bytes one retained key tuple costs: the tuple, its entry and every value in it.

    A string key costs its length, so a key of 1,000 characters is charged as such.
    """
    return _KEY_BASE_BYTES + sum(sys.getsizeof(v) + _KEY_COLUMN_BYTES for v in key)


class _ChildEdge:
    """One (relationship, child table) pair and what has been seen of it."""

    __slots__ = (
        "child_cols",
        "child_table",
        "missing",
        "parent",
        "pending",
        "ref",
        "seen",
        "tally",
    )

    def __init__(
        self,
        parent: _ParentSide,
        child_table: str,
        child_cols: list[str],
        cap: int | None,
    ) -> None:
        self.parent = parent
        self.child_table = child_table
        self.child_cols = child_cols
        self.tally = CappedIndices(cap)
        # key -> [exact count, first positions]; children whose parent table is not complete.
        self.pending: dict[tuple[Any, ...], tuple[int, list[int]]] = {}
        self.seen = False
        self.missing: list[str] = []
        self.ref = f"{parent.table}.{parent.columns} -> {child_table}.{child_cols}"

    def readable(self, output: pa.Table | pa.RecordBatch) -> bool:
        """Mark the table seen; True when it holds every FK column, else note the gaps."""
        self.seen = True
        gaps = [c for c in self.child_cols if c not in output.schema.names]
        for c in gaps:
            if c not in self.missing:
                self.missing.append(c)
        return not gaps

    def skip_unread(self, skipped: list[SkippedColumn]) -> bool:
        """Record why the edge was not checked. True when it was not."""
        if not self.seen:
            _skip_table(skipped, self.child_table)
            return True
        if self.missing:
            code = reasons.warning.VALIDATOR_SKIP_MISSING_COLUMN
            skipped.extend(SkippedColumn(self.child_table, c, code) for c in self.missing)
            return True
        return False


class _ParentSide:
    """The parent table of one relationship: its key set and whether it has completed."""

    __slots__ = ("columns", "complete", "keys", "seen", "table")

    def __init__(self, table: str, columns: list[str]) -> None:
        self.table = table
        self.columns = columns
        self.keys: set[tuple[Any, ...]] = set()
        self.complete = False
        self.seen = False


class FkIntactFold:
    """fk_intact: every non-null child FK value resolves to a parent PK, in any table order.

    Pattern: SDV HMA1 method (Patki et al., IEEE DSAA 2016; method only, no SDV code), joined
    like a symmetric hash join (Wilschut and Apers 1991): keys of a parent that has not
    completed go in a key set, child rows probe it once the parent table completes, and a child
    row that arrives earlier waits in a pending map. Null FK values are NOT flagged (use
    no_orphan_children for that).
    """

    def __init__(self, config: dict[str, Any], *, cap: int | None, budget: KeyStateBudget) -> None:
        self._cap = cap
        self._budget = budget
        self._parents: list[_ParentSide] = []
        self._edges: list[_ChildEdge] = []
        for rel in _extract_relationships(config):
            parent_info = rel.get("parent") or {}
            children = rel.get("children") or []
            if not isinstance(children, list):
                continue
            parent = _ParentSide(parent_info.get("table") or "", parent_info.get("columns") or [])
            self._parents.append(parent)
            for child_info in children:
                if isinstance(child_info, dict):
                    self._edges.append(
                        _ChildEdge(
                            parent,
                            child_info.get("table") or "",
                            child_info.get("columns") or [],
                            cap,
                        )
                    )
        self._tables: set[str] = set()

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def add(self, table: str, span: RowSpan) -> None:
        self._tables.add(table)
        for parent in self._parents:
            if parent.table == table:
                self._add_parent(parent, span)
        for edge in self._edges:
            if edge.child_table == table:
                self._add_child(edge, span)

    def _add_parent(self, parent: _ParentSide, span: RowSpan) -> None:
        parent.seen = True
        found = set(_parent_keys(span.output, parent.columns, parent.table))
        new = found - parent.keys
        self._budget.reserve(sum(key_bytes(k) for k in new), table=parent.table, column=None)
        parent.keys |= new

    def _add_child(self, edge: _ChildEdge, span: RowSpan) -> None:
        if not edge.readable(span.output):
            return
        parent = edge.parent
        for i, fk in enumerate(_child_fk_values(span.output, edge.child_cols)):
            if fk is None:
                continue  # null FK -> not a broken reference; skip
            position = span.offset + i
            if parent.complete:
                if fk not in parent.keys:
                    edge.tally.add(position)
                continue
            held = edge.pending.get(fk)
            if held is None:
                self._budget.reserve(
                    key_bytes(fk) + _INDEX_BYTES, table=edge.child_table, column=None
                )
                edge.pending[fk] = (1, [position])
                continue
            count, positions = held
            if self._cap is None or len(positions) < self._cap:
                self._budget.reserve(_INDEX_BYTES, table=edge.child_table, column=None)
                positions.append(position)
            edge.pending[fk] = (count + 1, positions)

    def table_complete(self, table: str) -> None:
        for parent in self._parents:
            if parent.table != table or parent.complete:
                continue
            parent.complete = True
            for edge in self._edges:
                if edge.parent is parent:
                    self._resolve(edge)

    def _resolve(self, edge: _ChildEdge) -> None:
        for fk, (count, positions) in edge.pending.items():
            if fk not in edge.parent.keys:
                edge.tally.add_group(count, positions)
            self._budget.release(key_bytes(fk) + _INDEX_BYTES * len(positions))
        edge.pending.clear()

    def finish(self) -> FoldResult:
        for parent in self._parents:
            if not parent.seen:
                raise ValueError(
                    f"misconfigured fk_intact validator: parent table {parent.table!r} "
                    f"not found in outputs. Available tables: {sorted(self._tables)}"
                )
            self.table_complete(parent.table)
        findings: list[ValidatorFinding] = []
        checked: list[tuple[str, str | None]] = []
        skipped: list[SkippedColumn] = []
        for edge in self._edges:
            if edge.skip_unread(skipped):
                continue
            checked.append((edge.child_table, None))
            count = edge.tally.count
            if count:
                findings.append(
                    ValidatorFinding(
                        validator="fk_intact",
                        table=edge.child_table,
                        column=None,
                        failing_row_indices=edge.tally.indices(),
                        detail=(
                            f"{count} row(s) in {edge.child_table} "
                            f"have FK values not found in {edge.parent.table} "
                            f"(relationship: {edge.ref})"
                        ),
                        failing_row_count=count,
                    )
                )
        return FoldResult(tuple(findings), tuple(checked), tuple(skipped))


class NoOrphanChildrenFold:
    """no_orphan_children: every child row must have a non-null FK value.

    Stricter than fk_intact: it flags child rows whose FK columns are all null. It reads each
    row alone and never looks at a parent.
    """

    def __init__(self, config: dict[str, Any], *, cap: int | None) -> None:
        self._edges: list[_ChildEdge] = []
        for rel in _extract_relationships(config):
            children = rel.get("children") or []
            if not isinstance(children, list):
                continue
            parent_info = rel.get("parent") or {}
            parent = _ParentSide(parent_info.get("table") or "", parent_info.get("columns") or [])
            for child_info in children:
                if isinstance(child_info, dict):
                    edge = _ChildEdge(
                        parent, child_info.get("table") or "", child_info.get("columns") or [], cap
                    )
                    self._edges.append(edge)

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def table_complete(self, table: str) -> None:
        return None

    def add(self, table: str, span: RowSpan) -> None:
        for edge in self._edges:
            if edge.child_table != table:
                continue
            if not edge.readable(span.output):
                continue
            for i, fk in enumerate(_child_fk_values(span.output, edge.child_cols)):
                if fk is None:
                    edge.tally.add(span.offset + i)

    def finish(self) -> FoldResult:
        findings: list[ValidatorFinding] = []
        checked: list[tuple[str, str | None]] = []
        skipped: list[SkippedColumn] = []
        for edge in self._edges:
            if edge.skip_unread(skipped):
                continue
            checked.append((edge.child_table, None))
            count = edge.tally.count
            if count:
                findings.append(
                    ValidatorFinding(
                        validator="no_orphan_children",
                        table=edge.child_table,
                        column=None,
                        failing_row_indices=edge.tally.indices(),
                        detail=(
                            f"{count} row(s) in {edge.child_table} "
                            f"have null FK values (orphaned children) "
                            f"for relationship {edge.ref}"
                        ),
                        failing_row_count=count,
                    )
                )
        return FoldResult(tuple(findings), tuple(checked), tuple(skipped))


def validate_fk_intact(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """fk_intact over whole tables (see `FkIntactFold`).

    Reads every relationship declared in ``config["relationships"]``; one finding per child-side
    violation group. Null FK values are NOT flagged by this validator.

    Args:
        outputs: Read-only pipeline outputs keyed by table name.
        entry: Per-validator config block (no extra keys expected here).
        config: Full pipeline config dict; relationships are read from it.
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each FK pair that has broken references.

    Raises:
        ValueError: A parent table is absent from the outputs, or a parent PK column is absent.
    """
    fold = FkIntactFold(config, cap=finding_index_cap(config), budget=KeyStateBudget(None))
    return run_whole(fold, outputs).findings


def validate_no_orphan_children(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """no_orphan_children over whole tables (see `NoOrphanChildrenFold`).

    Args:
        outputs: Read-only pipeline outputs keyed by table name.
        entry: Per-validator config block (no extra keys expected here).
        config: Full pipeline config dict; relationships are read from it.
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each FK pair that has orphaned children.
    """
    fold = NoOrphanChildrenFold(config, cap=finding_index_cap(config))
    return run_whole(fold, outputs).findings
