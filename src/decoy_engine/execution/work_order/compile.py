"""The one ordering decision: every entry point compiles its work list here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from decoy_engine.execution.work_order.operations import (
    NodeKey,
    ResolvedOperation,
    resolve_operations,
)

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.relationships import RelationshipGraph


@dataclass(frozen=True)
class WorkOrder:
    """Resolved operations and the dispatch order for one job."""

    ordered: tuple[WorkNode, ...]
    ops: Mapping[NodeKey, ResolvedOperation]


def compile_work_order(work: list[WorkNode], graph: RelationshipGraph) -> WorkOrder:
    """Resolve every node once, then order with `_runner.order_work`, main's ordering unchanged.
    A plan sorts here if and only if it sorts on main; `cyclic_work_ordering` and every other
    ordering error propagate."""
    from decoy_engine.execution._runner import order_work

    return WorkOrder(tuple(order_work(work, graph)), resolve_operations(work, graph))


def compile_plan_order(plan: Any, registry: Any, graph: RelationshipGraph) -> WorkOrder:
    """`compile_work_order` over the plan's own work list: the entry point for a caller that
    holds a plan rather than a work list."""
    from decoy_engine.execution._runner import build_work_list

    return compile_work_order(build_work_list(plan, registry), graph)
