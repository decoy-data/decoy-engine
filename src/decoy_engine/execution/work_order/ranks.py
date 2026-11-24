"""Ordering edges, the ordinary sort and the commit ranks, all read from resolved operations."""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.work_order.operations import NodeKey, ResolvedOperation

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode

Writers = dict[tuple[str, str | None], set[NodeKey]]

# Commit classes, lowest first: a column's final value comes from the highest rank that wrote it.
_WILDCARD, _HANDLER, _BUNDLE, _FK = 0, 1, 2, 3


def writer_index(ops: Mapping[NodeKey, ResolvedOperation]) -> Writers:
    """Each written (table, column) -> the keys of ALL nodes that write it, so a dependent waits
    on every writer and reads the final value. `(table, None)` holds the nodes whose writes cannot
    be named: they may write any column of their table, so `writers_of` returns them for every
    column of that table and no other."""
    writer: Writers = defaultdict(set)
    for op in ops.values():
        if op.wildcard:
            writer[(op.table, None)].add(op.key)
        for col in op.writes:
            writer[(op.table, col)].add(op.key)
    return writer


def writers_of(writer: Writers, table: str, column: str) -> set[NodeKey]:
    return writer.get((table, column), set()) | writer.get((table, None), set())


def _composite_overwrites(
    ops: Mapping[NodeKey, ResolvedOperation], writer: Writers
) -> dict[NodeKey, set[NodeKey]]:
    """Composite -> the creating nodes whose column it also writes. The handler writes every
    bundle output and refuses one not yet on the frame, so the composite runs after the creator
    and overwrites the created value with the coherent bundle's."""
    out: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for (_table, col), keys in writer.items():
        if col is None:
            continue
        composites = {k for k in keys if ops[k].kind == "composite"}
        for k in keys - composites:
            if ops[k].order_creates:
                for c in composites:
                    out[c].add(k)
    return out


def dependency_edges(ops: Mapping[NodeKey, ResolvedOperation]) -> dict[NodeKey, set[NodeKey]]:
    """The cross-column ordering channel: dependent key -> the keys of the nodes that write its
    MASKED driver columns. A creator a composite overwrites runs first and gets no edge onto that
    composite: what it read never reaches the output, and the edge could only form a cycle."""
    writer = writer_index(ops)
    overwrites = _composite_overwrites(ops, writer)
    deps: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for composite, creators in overwrites.items():
        deps[composite] |= creators
    for op in ops.values():
        for col in op.order_reads:
            for key in writers_of(writer, op.table, col):
                if key != op.key and op.key not in overwrites.get(key, ()):
                    deps[op.key].add(key)
    return deps


def fallback_edges(ops: Mapping[NodeKey, ResolvedOperation]) -> dict[NodeKey, set[NodeKey]]:
    """Value dependencies for a plan the ordinary edges reject as cyclic. A masked driver waits
    for every writer, as above. A creator a bundle overwrites no longer forces the bundle after
    it (commit ranks decide the final value). An FK child bypasses its configured handler: it
    waits for every other non-FK writer of its child columns, so its child tuple sees them."""
    writer = writer_index(ops)
    deps: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for op in ops.values():
        if op.kind == "fk":
            for col in op.node.columns:
                for key in writers_of(writer, op.table, col):
                    if key != op.key and ops[key].kind != "fk":
                        deps[op.key].add(key)
            continue
        for col in op.masked_reads:
            deps[op.key] |= writers_of(writer, op.table, col) - {op.key}
    return deps


def commit_rank(op: ResolvedOperation) -> tuple[int, NodeKey]:
    """`(class, node key)`: wildcard writers commit first, then known non-bundle handlers, then
    bundles, then FK resolutions; within a class the larger key writes last. Used for a plan whose
    ordinary sort is cyclic; every other plan commits in dispatch position."""
    if op.kind == "fk":
        return (_FK, op.key)
    if op.wildcard:
        return (_WILDCARD, op.key)
    return (_BUNDLE if op.kind == "composite" else _HANDLER, op.key)


def kahn_sorted(
    by_key: dict[NodeKey, WorkNode], deps: dict[NodeKey, set[NodeKey]]
) -> list[WorkNode]:
    """Deterministic topological sort: at each step take the sorted-smallest node whose
    dependencies are all placed (heap-based Kahn, O((n+e) log n)). Total order, byte-stable."""
    keys = set(by_key)
    if not keys:
        return []
    rev: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    indegree: dict[NodeKey, int] = dict.fromkeys(keys, 0)
    for child, parents in deps.items():
        if child not in keys:
            continue
        for parent in parents:
            if parent not in keys:
                continue
            rev[parent].add(child)
            indegree[child] += 1
    ready_heap: list[NodeKey] = [k for k in keys if indegree[k] == 0]
    heapq.heapify(ready_heap)
    placed: list[NodeKey] = []
    while ready_heap:
        nxt = heapq.heappop(ready_heap)
        placed.append(nxt)
        for child in sorted(rev[nxt]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready_heap, child)
    if len(placed) < len(keys):
        unplaced = sorted(k for k in keys if indegree[k] > 0)
        raise ExecutionError(
            code=reasons.runtime.CYCLIC_WORK_ORDERING,
            message=f"cycle in work-node dependencies; unresolved: {unplaced!r}",
        )
    return [by_key[k] for k in placed]
