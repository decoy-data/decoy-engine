"""The one ordering decision: every entry point compiles its work list here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.work_order.operations import (
    NodeKey,
    ResolvedOperation,
    resolve_operations,
)
from decoy_engine.execution.work_order.ranks import dependency_edges, fallback_edges

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.relationships import RelationshipGraph


@dataclass(frozen=True)
class WorkOrder:
    """Resolved operations and the dispatch order for one job.

    `fallback` is true only when the ordinary sort raised `cyclic_work_ordering` and the order
    comes from the value dependencies instead: then each column commits in rank order
    (`ranks.commit_rank`). A plan that orders today keeps its order and live-frame writes.
    """

    ordered: tuple[WorkNode, ...]
    ops: Mapping[NodeKey, ResolvedOperation]
    fallback: bool


def compile_work_order(work: list[WorkNode], graph: RelationshipGraph) -> WorkOrder:
    """Resolve every node once, then order. Only a `cyclic_work_ordering` result of the ordinary
    sort retries with the value graph; a real cycle of value inputs raises it again. Every other
    error propagates."""
    from decoy_engine.execution._runner import order_work

    ops = resolve_operations(work, graph)
    try:
        return WorkOrder(tuple(order_work(work, graph, dependency_edges(ops))), ops, False)
    except ExecutionError as exc:
        if exc.code != reasons.runtime.CYCLIC_WORK_ORDERING:
            raise
    return WorkOrder(tuple(order_work(work, graph, fallback_edges(ops))), ops, True)
