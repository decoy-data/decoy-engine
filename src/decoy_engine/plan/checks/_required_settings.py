"""Required strategy settings, declared once and checked before any executor runs.

Each descriptor names one setting a strategy cannot run without. ``check_required_strategy_settings``
walks the config and refuses a column that leaves one out, so ``decoy validate`` and ``decoy run``
(``run_config_only_checks`` and ``compile_plan``) fail with the same code the executor's own guard
raises, instead of failing late. The executor guards stay as defense in depth.

The mapping lives in ``contracts.strategy_requirements`` so the strategy catalog and the starter
config builder read the same descriptors without importing ``plan``. Descriptors hold a registered code and a fixed
message only: no submitted value and no callable predicate, so a refusal cannot echo config data.
"""

from __future__ import annotations

from typing import Any

from decoy_engine.contracts.strategy_requirements import (
    REQUIREMENTS_BY_STRATEGY,
    StrategyRequirement,
    lookup_path,
    requirement_applies,
    requirements_for,
)
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.relationships import composite_bindings

__all__ = [
    "REQUIREMENTS_BY_STRATEGY",
    "StrategyRequirement",
    "check_required_strategy_settings",
    "requirements_for",
]


def _missing(value: Any) -> bool:
    """Every required setting is a name, so anything but a non-blank string is missing."""
    return not isinstance(value, str) or not value.strip()


def check_required_strategy_settings(config: dict[str, Any]) -> None:
    """Refuse the first column that leaves out a setting its strategy requires.

    Config-only, so it runs in both compile entry points. Tables and columns are walked in config
    order and each strategy's descriptors in declaration order.

    Raises:
        PlanCompileError: the code of the missing setting's descriptor.
    """
    tables = config.get("tables")
    # A coherent_with member's namespace comes from its group's binding, so the column need not
    # declare one. The registry owns that rule; ask it instead of restating it.
    _, derived = composite_bindings(config)
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            strategy = col.get("strategy") if isinstance(col, dict) else None
            if not isinstance(strategy, str):
                continue
            for req in requirements_for(strategy):
                if (
                    req.path == ("namespace",)
                    and (table.get("name", "?"), col.get("name", "?")) in derived
                ):
                    continue
                if requirement_applies(req, col) and _missing(lookup_path(col, req.path)):
                    raise PlanCompileError(
                        code=req.code,
                        path=(
                            f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}."
                            + ".".join(req.path)
                        ),
                        message=(
                            f"column {col.get('name', '?')!r} in table "
                            f"{table.get('name', '?')!r}: {req.message}"
                        ),
                    )
