"""The one ordering decision: every entry point compiles its work list here."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.work_order.operations import (
    NodeKey,
    ResolvedOperation,
    resolve_operations,
)
from decoy_engine.execution.work_order.ranks import (
    dependency_edges,
    fallback_edges,
    writer_index,
)

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.relationships import RelationshipGraph


@dataclass(frozen=True)
class WorkOrder:
    """Resolved operations and the dispatch order for one job.

    `fallback_keys` names the nodes of every connected component whose ordinary sort raised
    `cyclic_work_ordering`: those run in the value-dependency order and commit each column in
    rank order (`ranks.commit_rank`). Every other node, in this table or another, keeps today's
    order and live-frame writes.
    """

    ordered: tuple[WorkNode, ...]
    ops: Mapping[NodeKey, ResolvedOperation]
    fallback_keys: frozenset[NodeKey] = frozenset()

    @property
    def fallback(self) -> bool:
        return bool(self.fallback_keys)


def _components(
    work: list[WorkNode], ops: Mapping[NodeKey, ResolvedOperation], graph: RelationshipGraph
) -> list[list[WorkNode]]:
    """Connected components of the nodes under every ordering edge and every shared writer of one
    column (a table-wide writer joins every node of its table)."""
    from decoy_engine.execution._runner import ordering_deps

    parent = {n.key: n.key for n in work}

    def find(k: NodeKey) -> NodeKey:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: NodeKey, b: NodeKey) -> None:
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    for child, drivers in ordering_deps(work, graph, dependency_edges(ops)).items():
        for d in drivers:
            union(child, d)
    for child, drivers in fallback_edges(ops).items():
        for d in drivers:
            union(child, d)
    for keys in writer_index(ops).values():
        first, *rest = sorted(keys)
        for k in rest:
            union(first, k)
    for op in ops.values():
        if op.wildcard:
            for other in ops.values():
                if other.table == op.table:
                    union(op.key, other.key)
    groups: dict[NodeKey, list[WorkNode]] = defaultdict(list)
    for n in work:
        groups[find(n.key)].append(n)
    return list(groups.values())


def compile_work_order(work: list[WorkNode], graph: RelationshipGraph) -> WorkOrder:
    """Resolve every node once, then order. A plan the ordinary sort accepts keeps its order.
    Otherwise only the connected components whose own sort raises `cyclic_work_ordering` use the
    value graph (a real cycle of value inputs raises it again); the rest keep today's order, so a
    cycle in one table never changes another table's output. Other errors propagate."""
    from decoy_engine.execution._runner import order_work

    ops = resolve_operations(work, graph)
    try:
        return WorkOrder(tuple(order_work(work, graph, dependency_edges(ops))), ops)
    except ExecutionError as exc:
        if exc.code != reasons.runtime.CYCLIC_WORK_ORDERING:
            raise
    ordinary: list[WorkNode] = []
    cyclic: list[list[WorkNode]] = []
    for nodes in _components(work, ops, graph):
        try:
            order_work(nodes, graph, dependency_edges(ops))
            ordinary.extend(nodes)
        except ExecutionError as exc:
            if exc.code != reasons.runtime.CYCLIC_WORK_ORDERING:
                raise
            cyclic.append(nodes)
    ordered = list(order_work(ordinary, graph, dependency_edges(ops)))
    keys: set[NodeKey] = set()
    for nodes in cyclic:
        ordered += order_work(nodes, graph, fallback_edges(ops))
        keys.update(n.key for n in nodes)
    return WorkOrder(tuple(ordered), ops, frozenset(keys))


def compile_plan_order(plan: Any, registry: Any, graph: RelationshipGraph) -> WorkOrder:
    """`compile_work_order` over the plan's own work list: the entry point for a caller that
    holds a plan rather than a work list."""
    from decoy_engine.execution._runner import build_work_list

    return compile_work_order(build_work_list(plan, registry), graph)
