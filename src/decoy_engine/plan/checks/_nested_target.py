"""Plan-time check for `nested` columns: the target must be inside the one JSONPath subset.

The handler reads the target with the same `parse_target`, so a config that compiles here is a
config the run accepts. `decoy validate` (`run_config_only_checks`) and `decoy run`
(`compile_plan`) both call this. The message names the table, column, position and form, and shows
the target text (config, not data) up to a fixed length. It never holds a cell value.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine._nested_json import TargetRefusal, nested_children, parse_target
from decoy_engine.plan.checks._generate_columns import _located

__all__ = ["check_nested_targets"]

_SHOWN = 64


def check_nested_targets(config: dict[str, Any]) -> None:
    """Refuse a `nested` column whose `target` is outside the supported JSONPath subset."""
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict) or col.get("strategy") != "nested":
                continue
            pc = col.get("provider_config")
            if not isinstance(pc, dict):
                continue
            (child,) = nested_children(pc)
            # An unset or non-string target keeps its own refusal (nested_target_unset).
            if not isinstance(child.target, str) or not child.target:
                continue
            found = parse_target(child.target)
            if isinstance(found, TargetRefusal):
                table_name, col_name = table.get("name", "?"), col.get("name", "?")
                raise _located(
                    str(reasons.plan.NESTED_TARGET_UNSUPPORTED),
                    f"tables.{table_name}.columns.{col_name}.{child.config_path}.target",
                    where=(
                        f"table {table_name!r}, column {col_name!r}: {found.form} at position "
                        f"{found.position}, {_shown(child.target)}"
                    ),
                )


def _shown(target: str) -> str:
    if len(target) <= _SHOWN:
        return f"target {target!r}"
    return f"target (first {_SHOWN} of {len(target)} characters): {target[:_SHOWN]!r}"
