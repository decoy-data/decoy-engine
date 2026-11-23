"""Plan and context stand-ins that list a column as typed, for direct handler tests.

`bucketize` and `top_code` skip their F06 declaration only for a column the plan lists as typed.
A test that calls a handler or the adapter with a hand-built plan says so here, instead of going
through compile.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.plan._types import PlanColumnShape


class AnyInteger(Mapping[tuple[str, str], ColumnShape]):
    """Every (table, column) is an integer column."""

    def __getitem__(self, key: tuple[str, str]) -> ColumnShape:
        return ColumnShape.INTEGER

    def get(self, key: Any, default: Any = None) -> ColumnShape:  # type: ignore[override]
        return ColumnShape.INTEGER

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(())

    def __len__(self) -> int:
        return 0


# Attributes a hand-built context needs next to `job_seed` for the numeric handlers.
CTX_SHAPE_ATTRS: dict[str, Any] = {
    "column_shapes": AnyInteger(),
    "current_table": "t",
    "nested_outer_column": "",
}


def integer_shapes(table: str, *columns: str) -> tuple[PlanColumnShape, ...]:
    """`Plan.column_shapes` listing each column as an integer."""
    return tuple(PlanColumnShape(table, c, ColumnShape.INTEGER) for c in columns)


# The F06 declaration of a text column that holds base-10 integers, for `bucketize`/`top_code`.
INT_DECL: dict[str, Any] = {
    "logical_type": "integer",
    "parse_format": {"id": "integer/ascii/v1", "signed": True, "bit_width": 64},
}


def numeric_shapes(per_table: Any) -> tuple[PlanColumnShape, ...]:
    """`Plan.column_shapes` for a hand-built seed envelope: each `bucketize` or `top_code` column
    is listed as an integer. `per_table` is the envelope's `(table, TableSeed)` pairs."""
    return tuple(
        PlanColumnShape(table, name, ColumnShape.INTEGER)
        for table, seed in per_table
        for name, col in seed.per_column
        if col.strategy in ("bucketize", "top_code")
    )
