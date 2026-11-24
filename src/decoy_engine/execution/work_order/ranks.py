"""Evaluation order and commit ranks for a plan the ordinary sort rejects as cyclic."""

from __future__ import annotations

from collections import defaultdict

from decoy_engine.execution._runner import (
    WorkNode,
    dispatch_writes,
    masked_driver_columns,
    order_work,
    writer_node_map,
    writers_of,
)
from decoy_engine.relationships._graph import RelationshipGraph

# Commit classes, lowest first: a column's final value comes from the highest rank that wrote it.
_WILDCARD, _HANDLER, _BUNDLE, _FK = 0, 1, 2, 3


def commit_rank(
    node: WorkNode, graph: RelationshipGraph
) -> tuple[int, tuple[str, tuple[str, ...]]]:
    """`(class, node key)`: wildcard writers commit first, then known non-bundle handlers, then
    bundles, then FK resolutions; within a class the larger key writes last."""
    if graph.parents_of(node.table, node.columns):
        return (_FK, node.key)
    if dispatch_writes(node, graph)[1]:
        return (_WILDCARD, node.key)
    return (_BUNDLE if node.kind == "composite" else _HANDLER, node.key)


def fallback_order(work: list[WorkNode], graph: RelationshipGraph) -> list[WorkNode]:
    """An evaluation order that satisfies every VALUE dependency, for a plan whose ordinary
    constraints form a cycle.

    A masked driver waits for its writers, as in `order_work`. A creator a bundle overwrites no
    longer forces the bundle after it (commit ranks decide the final value), and an FK child
    bypasses its creator's reads: it waits for the parent and for every other writer of its child
    columns, so its child tuple sees them. A real cycle of value inputs still raises
    `cyclic_work_ordering`.
    """
    writer = writer_node_map(work, graph)
    is_fk = {n.key: bool(graph.parents_of(n.table, n.columns)) for n in work}
    deps: dict[tuple[str, tuple[str, ...]], set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
    for node in work:
        if is_fk[node.key]:
            for col in node.columns:
                for key in writers_of(writer, node.table, col):
                    if key != node.key and not is_fk.get(key, False):
                        deps[node.key].add(key)
            continue
        for col in masked_driver_columns(node):
            deps[node.key] |= writers_of(writer, node.table, col) - {node.key}
    return order_work(work, graph, column_deps=deps)
