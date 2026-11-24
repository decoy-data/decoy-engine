"""Per-column commits for a plan evaluated in `ranks.fallback_order`.

Each node runs in place, in evaluation order. The rows and values it changed in each column it
writes are saved; once every node has run, each column is rebuilt from its source version by
applying the saved writes in commit-rank order, so the last matching writer wins every row
whatever the evaluation order. An FK resolution reads a child tuple assembled the same way from
the writes committed so far, skipping a write whose node also supplies a parent key.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from decoy_engine.execution._runner import (
    WorkNode,
    dispatch_writes,
    node_creates_own_target,
)
from decoy_engine.execution.work_order.ranks import commit_rank
from decoy_engine.relationships._graph import RelationshipGraph

_Col = tuple[str, str]


def allocate_creator_targets(
    work: list[WorkNode], frames: dict[str, pd.DataFrame], graph: RelationshipGraph
) -> None:
    """Add each missing creator target as an index-aligned null column before dispatch, so a
    gate that matches nothing still leaves the column in place and a bundle can fill it. An FK
    child resolves its own columns and creates nothing."""
    for node in work:
        frame = frames.get(node.table)
        if frame is None or graph.parents_of(node.table, node.columns):
            continue
        if node_creates_own_target(node) and node.columns[0] not in frame.columns:
            frame[node.columns[0]] = pd.Series([None] * len(frame), index=frame.index, dtype=object)


def _same(a: Any, b: Any) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    try:
        return bool(a == b)
    except (TypeError, ValueError):
        return False


def _objects(series: pd.Series) -> np.ndarray:
    return series.to_numpy(dtype=object)


class FallbackCommits:
    """Saved writes of one fallback run; created before the first node dispatches."""

    def __init__(self, work: list[WorkNode], graph: RelationshipGraph, frames: dict[str, Any]):
        self._graph = graph
        self._frames = frames
        self._rank = {n.key: commit_rank(n, graph) for n in work}
        self._writes: dict[tuple[str, tuple[str, ...]], tuple[frozenset[str], bool]] = {
            n.key: dispatch_writes(n, graph) for n in work
        }
        written: dict[str, set[str]] = defaultdict(set)
        for node in work:
            names, unknown = self._writes[node.key]
            written[node.table] |= set(frames[node.table].columns) if unknown else set(names)
        self._source: dict[_Col, pd.Series] = {
            (t, c): frames[t][c].copy()
            for t, cols in written.items()
            if t in frames
            for c in cols
            if c in frames[t].columns
        }
        self._deltas: dict[_Col, list[tuple[Any, Any, np.ndarray, pd.Series]]] = defaultdict(list)
        self._before: dict[_Col, pd.Series] = {}

    def _columns(self, node: WorkNode) -> list[str]:
        names, unknown = self._writes[node.key]
        frame = self._frames[node.table]
        return list(frame.columns) if unknown else sorted(names)

    def before(self, node: WorkNode) -> None:
        """Snapshot the columns `node` writes; for an FK child, assemble its child tuple."""
        frame = self._frames[node.table]
        if self._graph.parents_of(node.table, node.columns):
            self._assemble_child_input(node)
        self._before = {
            (node.table, c): frame[c].copy() for c in self._columns(node) if c in frame.columns
        }

    def after(self, node: WorkNode) -> None:
        """Save the rows and values `node` changed (every row for an FK resolution)."""
        frame = self._frames[node.table]
        fk = bool(self._graph.parents_of(node.table, node.columns))
        for c in self._columns(node):
            if c not in frame.columns:
                continue
            after = frame[c]
            changed: np.ndarray[Any, Any]
            before = self._before.get((node.table, c))
            if fk or before is None:
                changed = np.ones(len(after), dtype=bool).reshape(-1)
            else:
                changed = np.fromiter(
                    (
                        not _same(x, y)
                        for x, y in zip(_objects(before), _objects(after), strict=True)
                    ),
                    dtype=bool,
                    count=len(after),
                )
            if changed.any():
                self._deltas[(node.table, c)].append(
                    (self._rank[node.key], node.key, changed, after.copy())
                )

    def _assemble_child_input(self, node: WorkNode) -> None:
        edges = self._graph.parents_of(node.table, node.columns)
        parent_keys = {c for e in edges if e.parent_table == node.table for c in e.parent_columns}
        frame = self._frames[node.table]
        for c in node.columns:
            source = self._source.get((node.table, c))
            if source is None:
                continue
            values = _objects(source)
            for _rank, key, mask, after in sorted(
                self._deltas[(node.table, c)], key=lambda d: d[0]
            ):
                if key != node.key and not (self._writes[key][0] & parent_keys):
                    values = np.where(mask, _objects(after), values)
            frame[c] = pd.Series(values, index=frame.index, dtype=object)

    def commit(self) -> None:
        """Rebuild every column more than one node wrote: the source version, then each saved
        write in commit-rank order."""
        for (table, c), deltas in self._deltas.items():
            if len(deltas) < 2:
                continue
            frame = self._frames[table]
            source = self._source.get((table, c))
            values = _objects(source) if source is not None else np.full(len(frame), None, object)
            for _rank, _key, mask, after in sorted(deltas, key=lambda d: d[0]):
                values = np.where(mask, _objects(after), values)
            result = pd.Series(values, index=frame.index, dtype=object)
            last = sorted(deltas, key=lambda d: d[0])[-1][3]
            try:
                result = result.astype(last.dtype)
            except (TypeError, ValueError):
                pass
            frame[c] = result
