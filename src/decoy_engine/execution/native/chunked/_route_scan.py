"""The per-node pass of the native chunked route decision.

Moved out of `_dispatch._static_route_decision` unchanged. It looks at every scalar node of
one table and records why a node cannot run natively; the caller turns the result into the
table's single route. The strategy allowlists come in as arguments so the caller's own module
globals stay the one place a test or a future registry swap changes them.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from decoy_engine.execution.native._chunked_group_key_gate import (
    group_by_columns,
    order_dependence_rejection,
)
from decoy_engine.execution.native._faker_positional_admission import chunked_positional_column
from decoy_engine.execution.native._route_decline_codes import (
    RouteDeclineCode as Decline,
)
from decoy_engine.execution.native._route_decline_codes import (
    RouteDeclineRecord,
    column_decline,
    table_decline,
)


@dataclass(frozen=True)
class NodeScan:
    """What the node pass found: reason strings, decline records and the scalar columns."""

    reasons: list[str] = field(default_factory=list)
    declines: list[RouteDeclineRecord] = field(default_factory=list)
    scalar_columns: list[tuple[str, str]] = field(default_factory=list)


def scan_table_nodes(
    table_nodes: Sequence[Any],
    *,
    config: dict[str, Any],
    table: str,
    vetoed_strategies: Collection[str],
    kernel_strategies: Collection[str],
    pool_strategies: Collection[str],
) -> NodeScan:
    reasons: list[str] = []
    declines: list[RouteDeclineRecord] = []
    scalar_columns: list[tuple[str, str]] = []
    for node in table_nodes:
        label = ",".join(node.columns) if node.columns else "?"
        if node.kind != "scalar":
            reasons.append(f"non_scalar_node:{node.kind}:{label}")
            declines.append(table_decline(Decline.NON_SCALAR_NODE, table))
            continue
        column = node.columns[0]
        scalar_columns.append((column, node.strategy))
        if node.strategy in vetoed_strategies:
            # A strategy native on the full-frame route but vetoed on this chunked route
            # would otherwise resolve fallback_policy == "native" and reach a missing chunk
            # handler, so veto the whole table to the oracle here. The set is empty today;
            # the reason carries the strategy so a future veto stays distinguishable.
            reasons.append(f"{node.strategy}_not_native_chunked_route:{column}")
            declines.append(column_decline(Decline.STRATEGY_VETOED_CHUNKED, table, column))
            continue
        if node.strategy == "group_key" and node.fallback_policy == "native":
            # The sibling must reach group_key unmasked, or the native leg (which masks from
            # the source chunk) would read a different value than the oracle.
            group_by = group_by_columns(config, table).get(column)
            order_reason = (
                order_dependence_rejection(column, group_by, table_nodes) if group_by else None
            )
            if order_reason is not None:
                reasons.append(order_reason)
                self_anchor = group_by == column
                declines.append(
                    column_decline(
                        Decline.GROUP_KEY_SELF_ANCHOR
                        if self_anchor
                        else Decline.GROUP_KEY_MASKED_SIBLING,
                        table,
                        column,
                    )
                )
                continue
        no_kernel = node.strategy not in kernel_strategies
        no_pool_path = node.strategy not in pool_strategies
        # The seeded non-deterministic categorical and the non-deterministic REUSE faker resolve
        # a non-native policy (the full-frame operators are source-keyed); this chunked-only
        # route admits them, config only.
        positional = chunked_positional_column(config, table, node.strategy, column)
        if node.fallback_policy != "native" and not positional:
            reasons.append(f"fallback_policy_not_native:{column}:{node.fallback_policy}")
            declines.append(column_decline(Decline.FALLBACK_POLICY_NOT_NATIVE, table, column))
        elif no_kernel and no_pool_path:
            # Defense in depth (see module docstring): `fallback_policy` already
            # encodes this via `_requirements.py`'s combined kernel-or-pool
            # check, so this branch should be unreachable for an admitted
            # node. Kept as a second, independent guard against the two
            # allowlists drifting apart; a faker node satisfying JC-5 is in
            # pool_strategies, so it passes here alongside the
            # compiled-kernel strategies.
            reasons.append(f"no_native_kernel_or_pool:{column}:{node.strategy}")
            declines.append(column_decline(Decline.NO_NATIVE_KERNEL_OR_POOL, table, column))
    return NodeScan(reasons, declines, scalar_columns)
