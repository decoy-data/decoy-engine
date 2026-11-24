"""Creator-target preparation and ranked per-column commits for one run.

Each node runs in place and in order. For a plan whose ordinary sort is cyclic, the run also saves
what each node wrote: the rows it selected (every row for an unconditional write, the gate's rows
otherwise) and the values at those rows. A column written more than once is rebuilt from its source
version by applying the saved writes in commit-rank order, so the last matching writer wins each
row. The rebuild is published before a reader dispatches and again when the table is done. An FK
child reads a child tuple assembled the same way, skipping a write whose node also supplies one of
the lookup's parent keys. Saved versions live on the run object and end with it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from decoy_engine.execution.work_order.compile import WorkOrder
from decoy_engine.execution.work_order.operations import ResolvedOperation
from decoy_engine.execution.work_order.ranks import commit_rank

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.generation.pool._events import QualityWarning

_Col = tuple[str, str]


def _restore_dtype(series: pd.Series, dtype: Any) -> pd.Series:
    """`series` as `dtype` when its values fit it, else unchanged (object)."""
    if series.dtype == dtype:
        return series
    try:
        return series.astype(dtype)
    except (TypeError, ValueError, OverflowError):
        return series


class Selection:
    """The positions a gated handler replaced, set by `run_with_when_gate`; None = every row."""

    positions: np.ndarray[Any, Any] | None = None


def _objects(series: pd.Series) -> np.ndarray[Any, Any]:
    return series.to_numpy(dtype=object)


class WorkOrderRun:
    """Per-run state for one `WorkOrder`; created before the first dispatch."""

    def __init__(self, order: WorkOrder, graph: Any) -> None:
        self.order = order
        self._graph = graph
        self._rank = {k: commit_rank(op) for k, op in order.ops.items()}
        self._source: dict[_Col, pd.Series] = {}
        self._saves: dict[_Col, list[tuple[Any, Any, np.ndarray[Any, Any] | None, Any]]] = (
            defaultdict(list)
        )
        self.selection = Selection()

    def begin_table(self, table: str, frame: pd.DataFrame) -> None:
        """Add each missing creator target as an index-aligned null column, so a gate that
        matches nothing leaves it in place and a bundle can fill it. An FK child resolves its own
        columns and creates nothing. For a cyclic plan, also keep the table's source versions."""
        for op in self.order.ops.values():
            if op.table != table or op.kind == "fk":
                continue
            col = op.node.columns[0]
            if op.creates and col not in frame.columns:
                frame[col] = pd.Series([None] * len(frame), index=frame.index, dtype=object)
        fallback = [op for k, op in self.order.ops.items() if k in self.order.fallback_keys]
        written = {c for op in fallback if op.table == table for c in op.writes}
        if any(op.wildcard for op in fallback if op.table == table):
            written = set(frame.columns)
        for col in written & set(frame.columns):
            self._source[(table, col)] = frame[col].copy()

    def dispatch(
        self,
        call: Callable[..., list[QualityWarning]],
        node: WorkNode,
        frames: dict[str, pd.DataFrame],
        *args: Any,
        **kwargs: Any,
    ) -> list[QualityWarning]:
        """Run `call(node, frames, ...)` (the adapter's node dispatch) between `before` and
        `after`, so the versions the node reads are published first and what it wrote is saved."""
        self.before(node, frames)
        warnings = call(node, frames, *args, **kwargs)
        self.after(node, frames[node.table])
        return warnings

    def before(self, node: WorkNode, frames: dict[str, pd.DataFrame]) -> None:
        self.selection = Selection()
        if node.key not in self.order.fallback_keys:
            return
        op = self.order.ops[node.key]
        for col in op.masked_reads:
            self._publish(frames[node.table], node.table, col)
        if op.kind == "fk":
            # The parent map reads the winning (rank-assembled) value of every parent column.
            for edge in op.fk_edges:
                for col in edge.parent_columns:
                    if edge.parent_table in frames:
                        self._publish(frames[edge.parent_table], edge.parent_table, col)
            self._assemble_child_input(op, frames[node.table])

    def after(self, node: WorkNode, frame: pd.DataFrame) -> None:
        """Save the rows `node` selected and the values it wrote there."""
        if node.key not in self.order.fallback_keys:
            return
        op = self.order.ops[node.key]
        positions = self.selection.positions
        cols = frame.columns if op.wildcard else [c for c in op.outputs if c in frame.columns]
        for col in cols:
            series = frame[col]
            values = _objects(series if positions is None else series.iloc[positions])
            self._saves[(node.table, col)].append(
                (self._rank[node.key], node.key, positions, (values.copy(), series.dtype))
            )

    def _rebuild(
        self,
        frame: pd.DataFrame,
        table: str,
        col: str,
        *,
        skip_parent_keys: frozenset[str] = frozenset(),
        child: Any = None,
    ) -> np.ndarray[Any, Any] | None:
        source = self._source.get((table, col))
        if source is None:
            return None
        values = _objects(source)
        for _rank, key, positions, (saved, _dtype) in sorted(
            self._saves[(table, col)], key=lambda d: d[0]
        ):
            if child is not None and key != child and self._supplies(key, skip_parent_keys):
                continue
            if positions is None:
                values = saved.copy()
            else:
                values[positions] = saved
        return values

    def _supplies(self, key: Any, parent_keys: frozenset[str]) -> bool:
        op = self.order.ops[key]
        return bool(parent_keys) and (op.wildcard or bool(op.writes & parent_keys))

    def _publish(self, frame: pd.DataFrame, table: str, col: str) -> None:
        saves = self._saves.get((table, col))
        if not saves or col not in frame.columns:
            return
        values = self._rebuild(frame, table, col)
        if values is None:
            return
        result = pd.Series(values, index=frame.index, dtype=object)
        last = max(saves, key=lambda d: d[0])[3][1]
        # Restore the dtype the last writer produced. A column that cannot hold the assembled
        # values in that dtype (an int column given a null by another writer) stays object, and
        # the Arrow conversion at the table boundary types it from the values.
        frame[col] = _restore_dtype(result, last)

    def _assemble_child_input(self, op: ResolvedOperation, frame: pd.DataFrame) -> None:
        edges = op.fk_edges
        parents = frozenset(
            c for e in edges if e.parent_table == op.table for c in e.parent_columns
        )
        for col in op.node.columns:
            values = self._rebuild(frame, op.table, col, skip_parent_keys=parents, child=op.key)
            if values is not None:
                frame[col] = pd.Series(values, index=frame.index, dtype=object)

    def finish(self, frames: dict[str, pd.DataFrame], table: str | None = None) -> None:
        """Rebuild every column some other node also wrote, in commit-rank order."""
        for (t, col), saves in list(self._saves.items()):
            if (table is None or t == table) and len(saves) > 1 and t in frames:
                self._publish(frames[t], t, col)
