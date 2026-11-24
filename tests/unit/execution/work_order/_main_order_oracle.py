"""Frozen copy of main's work-order sort, the oracle for `test_order_matches_main.py`.

Verbatim from `src/decoy_engine/execution/_runner.py` at engine commit `8ee461e0f`
(`_writer_output_columns`, `_writer_node_map`, `_masked_driver_columns`,
`column_dependency_edges`, `order_work`, `_kahn_sorted`). It imports nothing from
`execution/work_order/`. Change it only when the owner approves an ordering change, and name the
change in the PR.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._runner import WorkNode
from decoy_engine.plan._types import ColumnSeed

if TYPE_CHECKING:
    from decoy_engine.relationships import RelationshipGraph

_NodeKey = tuple[str, tuple[str, ...]]


def _writer_output_columns(node: WorkNode) -> tuple[str, ...]:
    """Every column `node` WRITES, for the writer map (not its dispatch identity).

    A composite bundle and a composite-FK group already carry their full output
    set in `node.columns`. A scalar node writes its single column EXCEPT
    `joint_mask`: it is a multi-column transform (`apply_joint_mask` writes every
    column in its `columns` config in one pass), yet its work node keys on just
    the dispatch column (the first sorted output). Register all of its configured
    outputs so a dependent on a NON-dispatch output (e.g. a `derived` reading one
    of zip/city/state) still resolves to the joint_mask node and gets its edge.
    """
    if node.strategy == "joint_mask" and isinstance(node.plan_slice, ColumnSeed):
        from decoy_engine.execution._adapter import provider_config_to_dict

        cols = provider_config_to_dict(node.plan_slice.provider_config).get("columns")
        if cols:
            return tuple(cols)
    return node.columns


def _writer_node_map(work: list[WorkNode]) -> dict[tuple[str, str], set[_NodeKey]]:
    """Map each written (table, column) to the keys of ALL nodes that WRITE it.

    Not column=node (the cross-column ordering trap): a composite provider is a
    bundle node whose `columns` holds several outputs, so every one of them maps
    to that ONE bundle key; a scalar node (`derived`/`group_key`) maps its single
    output column to itself, and a `joint_mask` node maps EVERY column it writes
    (`_writer_output_columns`), not only its dispatch column.

    The value is a SET, not a single key: the production compiler emits a
    joint_mask group as one per-output-column node, each carrying the full
    `columns` config, so several nodes write the SAME output column. A plain
    last-write-wins map kept only the last node in CONFIG order, leaving a
    dependent ordered after one arbitrary writer while the OTHER writers (and so
    the column's final value) still ran later -- a stale read under a non-trivial
    execution order. Recording every writer makes a dependent wait on all of
    them, so it reads the column's final value whichever writer the topo sort
    places last. A dependent's driver ref resolves through this map to the nodes
    that must all run first.
    """
    writer: dict[tuple[str, str], set[_NodeKey]] = defaultdict(set)
    for node in work:
        for col in _writer_output_columns(node):
            writer[(node.table, col)].add(node.key)
    return writer


def _masked_driver_columns(node: WorkNode) -> frozenset[str]:
    """The same-table sibling columns `node` reads for their MASKED value, so it
    must be ordered AFTER them (the cross-column V1 ordering edge).

    Only a scalar node whose strategy creates its own target from other columns has
    such drivers. Their names come from `scalar_creating_reads`, the same declaration
    `created_columns` admits a created column by, so a column accepted as created is
    ordered after every column it reads, for every creating strategy. Every other node
    (including `joint_mask`, whose `key_by` is a SOURCE read via snapshot) imposes no
    ordering edge.
    """
    plan_slice = node.plan_slice
    if node.kind != "scalar" or not isinstance(plan_slice, ColumnSeed):
        return frozenset()
    from decoy_engine.execution._adapter import provider_config_to_dict
    from decoy_engine.execution._column_access import scalar_creating_reads

    entry = {
        "name": node.columns[0] if node.columns else None,
        "strategy": plan_slice.strategy,
        "provider_config": provider_config_to_dict(plan_slice.provider_config),
        "coherent_with": list(plan_slice.coherent_with),
    }
    return scalar_creating_reads(entry)


def column_dependency_edges(work: list[WorkNode]) -> dict[_NodeKey, set[_NodeKey]]:
    """The cross-column ordering channel for `order_work`: dependent-node key ->
    the keys of the nodes that write its MASKED driver columns.

    A driver column ref resolves to its writer node(s) through `_writer_node_map`
    (per-provider representation, not column=node). A ref whose column no node
    writes (an unmasked passthrough source) imposes no edge -- its live value is
    already its source value -- and a self-ref is skipped. A column written by a
    MULTI-ENTRY joint_mask group has several writers; the dependent waits on all
    of them so it reads the final value, not whichever writer a lexicographic
    accident ran before it. SOURCE-read drivers (`joint_mask` `key_by`) are
    deliberately absent: they read a pre-mask snapshot, so they need no ordering
    edge. Reusing `order_work`'s own topo sort + cycle backstop (no parallel
    scheduler); derived-derived cycles are still caught at plan time by
    `check_derived_column_refs`.
    """
    writer = _writer_node_map(work)
    deps: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)
    for node in work:
        for col in _masked_driver_columns(node):
            for writer_key in writer.get((node.table, col), ()):
                if writer_key != node.key:
                    deps[node.key].add(writer_key)
    return deps


def order_work(
    work: list[WorkNode],
    relationship_graph: RelationshipGraph,
    column_deps: Mapping[_NodeKey, set[_NodeKey]] | None = None,
) -> list[WorkNode]:
    """Order the work list (S9 spec §6.2).

    Dependency edges come from `relationship_graph.edges` (FK parent -> child),
    plus a composite-node -> FK-child edge whenever the composite's output
    columns are a superset of an FK's parent_columns (R17: the composite writes
    the whole bundle before any child reads a masked parent column). Topo-sorted
    with a sorted tie-break for byte-stable ordering.

    `column_deps` is the cross-column V1 channel: dependent-node key -> the keys
    of the nodes writing its MASKED driver columns (`derived` expression refs,
    `group_key` `group_by`, and the reads of every other creating strategy), so a dependent reads its drivers' masked values
    under an explicit edge instead of by lexicographic-sort accident. None means
    derive them from `work` via `column_dependency_edges` (so every route gets
    the fix); a caller/test may pass an explicit map. These edges only ADD
    constraints, so FK ordering stays dominant; a cross-column edge that
    contradicts an FK edge is a genuine cycle and raises `cyclic_work_ordering`.
    """
    by_key: dict[_NodeKey, WorkNode] = {w.key: w for w in work}
    deps: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)

    for edge in relationship_graph.edges:
        parent_k = (edge.parent_table, edge.parent_columns)
        child_k = (edge.child_table, edge.child_columns)
        if child_k not in by_key:
            continue
        if parent_k in by_key:
            deps[child_k].add(parent_k)
        else:
            # Composite-key FK: the parent tuple is not a single work node; its
            # columns mask as individual scalar nodes. The composite-FK child
            # node waits on each parent column node so the parent key mapping is
            # fully masked before the child resolves against it.
            for pcol in edge.parent_columns:
                pcol_k = (edge.parent_table, (pcol,))
                if pcol_k in by_key:
                    deps[child_k].add(pcol_k)

    # R17: a composite output column that is also a FK parent. The FK child waits
    # on the whole composite bundle node, not a per-column node.
    for node in work:
        if node.kind != "composite":
            continue
        node_cols = set(node.columns)
        for edge in relationship_graph.edges:
            if edge.parent_table == node.table and set(edge.parent_columns).issubset(node_cols):
                child_k = (edge.child_table, edge.child_columns)
                if child_k in by_key:
                    deps[child_k].add(node.key)

    # Cross-column V1: a dependent waits on the node(s) writing its MASKED
    # drivers, so the read is intentional (not lexicographic luck). FK edges
    # above stay dominant: these only add constraints.
    col_deps = column_dependency_edges(work) if column_deps is None else column_deps
    for dependent, drivers in col_deps.items():
        if dependent not in by_key:
            continue
        for driver in drivers:
            if driver in by_key:
                deps[dependent].add(driver)

    return _kahn_sorted(by_key, deps)


def _kahn_sorted(
    by_key: dict[_NodeKey, WorkNode], deps: dict[_NodeKey, set[_NodeKey]]
) -> list[WorkNode]:
    """Deterministic topological sort: at each step take the sorted-smallest node
    whose dependencies are all placed. Total order, byte-stable across runs.

    QA-10 F9 (2026-06-01): heapq-based Kahn replaces the prior O(n^2)
    "scan all keys + sort the ready set" loop. Pre-fix every
    topological step did a full `sorted(k for k in keys if ...)`,
    yielding O(n^2 log n) total work. Post-fix maintains a min-heap
    of ready nodes + an indegree counter; each node is pushed/popped
    once for O((n+e) log n) total. Output is byte-identical to the
    prior implementation (both yield the lexicographically smallest
    topological order). Same fix shape as QA-8 F1 closure on the
    relationship-graph builder.
    """
    keys = set(by_key)
    if not keys:
        return []
    # Build reverse adjacency + indegree counter so each placement
    # only revisits the children of the just-placed node, not the
    # full key set.
    rev: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)
    indegree: dict[_NodeKey, int] = {k: 0 for k in keys}
    for child, parents in deps.items():
        if child not in keys:
            continue
        for parent in parents:
            if parent not in keys:
                continue
            rev[parent].add(child)
            indegree[child] += 1
    ready_heap: list[_NodeKey] = [k for k in keys if indegree[k] == 0]
    heapq.heapify(ready_heap)
    placed: list[_NodeKey] = []
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
