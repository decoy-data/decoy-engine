"""The runtime backstop for a strategy that needs an F06 cast to read text as numbers."""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.contracts.strategy_requirements import (
    SHAPE_REQUIREMENTS_BY_STRATEGY,
    shape_declaration_needed,
)
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError

__all__ = ["require_shape_declared"]


def require_shape_declared(
    strategy: str, column: str, cfg: dict[str, Any], ctx: StrategyContext
) -> None:
    """Refuse a column the plan does not list as typed or declared (a caller that skipped compile).

    Plan compile refuses a text column with no F06 cast before any read. This keys on the shape
    the plan recorded for the column, never on the pandas dtype, and reads the same table row.
    """
    shaped = SHAPE_REQUIREMENTS_BY_STRATEGY[strategy]
    shape = ctx.column_shapes.get(
        (ctx.current_table, ctx.nested_outer_column or column), ColumnShape.UNKNOWN
    )
    if shaped.requirement is not None and shape_declaration_needed(
        shaped, shape, config_only=False
    ):
        raise StrategyError(
            code=reasons.runtime.COLUMN_SHAPE_REQUIRED,
            strategy=strategy,
            message=f"column {column!r}: {shaped.requirement.message}",
        )
