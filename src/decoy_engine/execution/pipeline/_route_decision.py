"""Route-decision pieces split out of `_pipeline_context` to hold its 600-line cap."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from decoy_engine.execution import _pipeline_multi_table as _multi_table

if TYPE_CHECKING:
    from decoy_engine.execution._pipeline_context import PipelineRunContext
    from decoy_engine.execution._pipeline_multi_table import MultiTableSplit

__all__ = ["decide_split"]


def decide_split(
    ctx: PipelineRunContext, route: str, route_chunked: bool, keep_lazy: Mapping[str, Any]
) -> MultiTableSplit | None:
    """B7: an independent multi-table job runs each table on the route it would take alone.

    Only the full-frame executor reads the result. The classification reads `ctx.caller_sources`
    as the route layers do, so a lazy source is judged from its footer, not from a resolved table.
    """
    if route != "full_frame" or route_chunked or not ctx.has_mask_table:
        return None
    return _multi_table.decide_multi_table_split(
        ctx.config,
        plan=ctx.plan,
        registry=ctx.registry,
        graph=ctx.graph,
        substrate=ctx.resolved_substrate,
        caller_sources=ctx.caller_sources,
        table_kinds=ctx.table_kinds,
        auto_chunk=ctx.auto_chunk,
        source_facts=keep_lazy,
        auto_chunk_threshold_rows=ctx.auto_chunk_threshold_rows,
        dispatcher_enabled=ctx.chunked_dispatcher_enabled,
        # F06: a declared job keeps one route for the whole job, so every table's companion rows
        # stay aligned with its rendered output.
        split_enabled=ctx.multi_table_dispatch_enabled and ctx.plan.declared_casting is None,
        vault_writer_present=ctx.vault_writer is not None,
    )
