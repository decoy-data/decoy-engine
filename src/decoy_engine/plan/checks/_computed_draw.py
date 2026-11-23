"""Plan-time checks for `strategy: faker` columns on a computed provider (uuid, random_int_range,
random_choice): the draw arguments, the cardinality mode and the namespace.

A computed draw is a keyed function of the source value or the row number, so it has no pool and
no source-cardinality modes. The arguments are read by the same parser the run uses
(`generation.pool.parse_computed_draw`), so a config that compiles is a config that runs.
Messages name the table, column and field and never the supplied bounds or elements.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.generation.pool import (
    COMPUTED_NAMESPACE_MARKER,
    DrawRefusal,
    draw_kwargs,
    parse_computed_draw,
)
from decoy_engine.plan.checks._generate_columns import _located

__all__ = ["check_computed_draws"]


def _faker_columns(config: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    found: list[tuple[str, str, dict[str, Any]]] = []
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            if isinstance(col, dict) and col.get("strategy") == "faker":
                found.append((str(table.get("name", "?")), str(col.get("name", "?")), col))
    return found


def _is_computed(provider: Any) -> bool:
    from decoy_engine.providers_v2 import get_default_registry

    registry = get_default_registry()
    return (
        isinstance(provider, str)
        and registry.has(provider)
        and registry.get_capabilities(provider).draw == "computed"
    )


def check_computed_draws(config: dict[str, Any]) -> None:
    """Refuse a faker column whose computed draw cannot run: a reserved namespace (any faker
    column), a cardinality mode other than reuse, or arguments outside the contract."""
    for table, column, col in _faker_columns(config):
        base = f"tables.{table}.columns.{column}"
        where = f"table {table!r}, column {column!r}"
        namespace = col.get("namespace")
        if isinstance(namespace, str) and COMPUTED_NAMESPACE_MARKER in namespace:
            raise _located(
                str(reasons.plan.COMPUTED_DRAW_NAMESPACE_RESERVED), f"{base}.namespace", where
            )
        provider = col.get("provider")
        if not _is_computed(provider):
            continue
        if col.get("cardinality_mode") not in (None, "reuse"):
            raise _located(
                str(reasons.plan.COMPUTED_DRAW_MODE_UNSUPPORTED), f"{base}.cardinality_mode", where
            )
        provider_config = col.get("provider_config")
        if provider_config is not None and not isinstance(provider_config, dict):
            raise _located(
                str(reasons.plan.COMPUTED_DRAW_ELEMENTS_INVALID), f"{base}.provider_config", where
            )
        found = parse_computed_draw("mask", str(provider), draw_kwargs(provider_config))
        if isinstance(found, DrawRefusal):
            code = (
                reasons.plan.COMPUTED_DRAW_RANGE_INVALID
                if found.kind == "range"
                else reasons.plan.COMPUTED_DRAW_ELEMENTS_INVALID
            )
            raise _located(str(code), f"{base}.provider_config", where)
