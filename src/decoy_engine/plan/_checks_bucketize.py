"""Plan-compile check for bucketize columns (Sprint 13 / coercion-13, S3).

Added as its own module to avoid growing plan/_checks.py past its size
ceiling (see the SP-10 comment in tests/sentry/test_module_size.py).

Sprint 13 GATE-1 Q4 (PO-approved, 2026-07-03): close the sibling silent-
unmask leaks in the same pass as truncate, not only truncate itself.
``resolve_bucketize_width`` (`execution/_strategies/
_bucketize.py`) returns ``None`` -- and the handler then passes the source
column through UNMASKED -- when ``preset`` names something not in the
known preset table (e.g. the Studio picker's ``"(custom)"`` sentinel
reaching the engine unresolved) or when ``width`` is missing, non-numeric,
or not positive. This module rejects both shapes at compile time, before
any row is masked. The handler's ``run`` additionally raises
``StrategyError`` on the same shapes as a defense-in-depth backstop.

Reads the width through ``contracts.bucketize_width``, the one rule the handler and the
column-shape check share (no duplicated table to drift out of sync).

This module exports exactly one function: ``check_bucketize_config``.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.contracts.bucketize_width import (
    BUCKETIZE_PRESETS,
    is_oversized_integer_width,
    unresolvable_width_field,
)
from decoy_engine.contracts.column_shape import ColumnShape, ColumnShapes
from decoy_engine.plan._errors import PlanCompileError


def check_bucketize_config(config: dict[str, Any], shapes: ColumnShapes | None = None) -> None:
    """Reject bucketize columns whose bucket width cannot be resolved.

    Compile-check ownership table row #23 (Sprint 13 / coercion-13 S3,
    GATE-1 Q4, 2026-07-03). Mirrors ``resolve_bucketize_width``
    exactly: a column is valid when either

    1. ``preset`` is set and is a known preset name (``BUCKETIZE_PRESETS``); or
    2. ``preset`` is unset and ``width`` is a positive ``int``/``float``
       (not a ``bool``, not a numeric string).

    Any other shape -- an unknown/unresolved preset (including the Studio
    picker's ``"(custom)"`` sentinel reaching the engine without a
    resolved numeric width), a missing width, a non-numeric width string,
    or a non-positive width -- is guaranteed to leave the column unmasked
    at run today; reject it here instead. A masking strategy must never
    silently pass the source value through on a bad config.

    Config-only (no profile, no source data): safe to run in both compile
    branches and in ``run_config_only_checks``. Validation never mutates
    (per engine rule).

    Args:
        config: Raw pipeline config dict.

    Raises:
        PlanCompileError: neither a known preset nor a resolvable numeric
            width is configured.
    """
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") != "bucketize":
                continue
            col_name = col_entry.get("name", "?")
            pc = col_entry.get("provider_config")
            if not isinstance(pc, dict):
                pc = {}

            field = unresolvable_width_field(pc)
            if field == "preset":
                raise PlanCompileError(
                    code=reasons.plan.BUCKETIZE_WIDTH_UNRESOLVABLE,
                    path=f"tables.{table_name}.columns.{col_name}.provider_config.preset",
                    message=(
                        f"bucketize column {col_name!r} in table {table_name!r} "
                        "has a preset that is not a known preset "
                        f"(known: {sorted(BUCKETIZE_PRESETS)!r}). An unresolved preset "
                        "(e.g. a UI sentinel like '(custom)' that was never "
                        "replaced with a numeric width) leaves the column "
                        "unmasked at run; set a known preset or drop 'preset' "
                        "and set a numeric 'width' instead."
                    ),
                )
            if field == "width":
                if (
                    shapes is not None
                    and shapes.get((table_name, col_name)) is ColumnShape.DECIMAL
                    and is_oversized_integer_width(pc)
                ):
                    continue  # the decimal shape rule refuses it as column_shape_mismatch
                raise PlanCompileError(
                    code=reasons.plan.BUCKETIZE_WIDTH_UNRESOLVABLE,
                    path=f"tables.{table_name}.columns.{col_name}.provider_config.width",
                    message=(
                        f"bucketize column {col_name!r} in table {table_name!r} has "
                        "no usable width. Set "
                        "either a known 'preset' or a positive numeric 'width' "
                        "(an integer width must be below 2**53) "
                        "(a numeric-looking string does not count; the emitter "
                        "must coerce it to a real number before it reaches the "
                        "engine)."
                    ),
                )
