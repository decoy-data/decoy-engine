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
from decoy_engine._nested_json import nested_children
from decoy_engine.contracts.declared_casting import date_shift_owns_declared_format
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


def _refuse(req: StrategyRequirement, table: Any, col: Any, path: str) -> PlanCompileError:
    return PlanCompileError(
        code=req.code,
        path=path,
        message=f"column {col!r} in table {table!r}: {req.message}",
    )


def _declared_date_format(col: dict[str, Any]) -> bool:
    """Whether this top-level column's date format comes from its own declared parse format."""
    return date_shift_owns_declared_format(
        nested=False,
        logical_type=col.get("logical_type"),
        has_parse_format=col.get("parse_format") is not None,
    )


def _check_nested_children(table: Any, col: dict[str, Any]) -> None:
    """Refuse a nested child that leaves out a setting under its own `strategy_config`.

    Only descriptors rooted at `provider_config` apply: a child takes its parent's namespace
    (the nested handler copies it), so a root-level descriptor never binds the child. The child
    never inherits a declared-casting exemption from its parent.
    """
    provider_config = col.get("provider_config")
    if not isinstance(provider_config, dict):
        return
    for child in nested_children(provider_config):
        if not isinstance(child.strategy, str):
            continue
        config = child.strategy_config if isinstance(child.strategy_config, dict) else {}
        rooted = {"provider_config": config}
        for req in requirements_for(child.strategy):
            if req.path[0] != "provider_config":
                continue
            if requirement_applies(req, rooted) and _missing(lookup_path(rooted, req.path)):
                path = ".".join(
                    (
                        f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}",
                        child.config_path,
                        "strategy_config",
                        *req.path[1:],
                    )
                )
                raise _refuse(req, table.get("name", "?"), col.get("name", "?"), path)


def check_required_strategy_settings(config: dict[str, Any]) -> None:
    """Refuse the first column that leaves out a setting its strategy requires.

    Config-only, so it runs in both compile entry points. Tables and columns are walked in config
    order and each strategy's descriptors in declaration order. A `nested` column's child is
    walked after the column itself, for descriptors rooted at `provider_config` only.

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
                if req.path == ("provider_config", "date_format") and _declared_date_format(col):
                    continue
                if requirement_applies(req, col) and _missing(lookup_path(col, req.path)):
                    path = (
                        f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}."
                        + ".".join(req.path)
                    )
                    raise _refuse(req, table.get("name", "?"), col.get("name", "?"), path)
            if strategy == "nested":
                _check_nested_children(table, col)
