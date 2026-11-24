"""The native route's view of typed date_shift columns: their plan shapes and the one policy
decline that must run before the generic fallback-policy check.

A `date32` date_shift column runs the typed kernel under the plan's `DATE` shape
(`plan_native_date_shape`). Both chunked entry points read that shape from the compiled plan
through this module, so admission and parameter resolution see the same answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution.native._route_decline_codes import (
    CodedDecline,
    RouteDeclineCode,
    coded,
)

__all__ = ["policy_decline", "table_date_shapes", "typed_preserve"]


def table_date_shapes(plan: Any, table: str, columns: Iterable[str]) -> dict[str, ColumnShape]:
    """Each of `columns` the compiled `plan` lists as a native typed date column, with its shape."""
    from decoy_engine.declared_casting._boundary import plan_native_date_shape

    shapes = {name: plan_native_date_shape(plan, table, name) for name in columns}
    return {name: shape for name, shape in shapes.items() if shape is not None}


def typed_preserve(
    config: dict[str, Any], shapes: Mapping[tuple[str, str], ColumnShape], table: str, column: str
) -> bool:
    """Whether `table.column` is a typed date_shift column (in the plan's `shapes`) whose config
    lists `preserve_values`, the same predicate the config gate applies (`has_preserve_values`)."""
    from decoy_engine.transforms.date_preserve import has_preserve_values

    if (table, column) not in shapes:
        return False
    for table_cfg in config.get("tables") or ():
        if not isinstance(table_cfg, dict) or table_cfg.get("name") != table:
            continue
        for col in table_cfg.get("columns") or ():
            if isinstance(col, dict) and col.get("name") == column:
                cfg = col.get("provider_config")
                return has_preserve_values(cfg if isinstance(cfg, dict) else {})
    return False


def policy_decline(
    config: dict[str, Any],
    shapes: Mapping[tuple[str, str], ColumnShape],
    node: Any,
    table: str,
    column: str,
    positional: bool,
) -> CodedDecline | None:
    """The static admission's policy decline for one scalar `node`, or None.

    A typed column with `preserve_values` resolves a non-native policy too, so its own code is
    checked first: otherwise it would report the generic `fallback_policy_not_native`. A
    `positional` column (the seeded non-deterministic categorical and the non-deterministic
    REUSE faker) resolves a non-native policy because the full-frame operators are
    source-keyed; the chunked route admits it, config only.
    """
    if typed_preserve(config, shapes, table, column):
        return coded(
            f"date_shift_typed_preserve_not_native:{column}",
            RouteDeclineCode.DATE_SHIFT_TYPED_PRESERVE_NOT_NATIVE,
            table,
            column,
        )
    if node.fallback_policy != "native" and not positional:
        return coded(
            f"fallback_policy_not_native:{column}:{node.fallback_policy}",
            RouteDeclineCode.FALLBACK_POLICY_NOT_NATIVE,
            table,
            column,
        )
    return None
