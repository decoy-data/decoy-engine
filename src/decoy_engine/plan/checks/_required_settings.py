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

from collections.abc import Iterator, Mapping
from typing import Any

from decoy_engine.contracts.declared_casting import date_shift_owns_declared_format
from decoy_engine.contracts.strategy_requirements import (
    REQUIREMENTS_BY_STRATEGY,
    StrategyRequirement,
    lookup_path,
    requirement_applies,
    requirement_missing,
    requirements_for,
)
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan.checks._strategy_sites import StrategySite, strategy_sites
from decoy_engine.relationships import composite_bindings

__all__ = [
    "REQUIREMENTS_BY_STRATEGY",
    "StrategyRequirement",
    "check_required_strategy_settings",
    "requirements_for",
]


def _declared_date_format(col: Mapping[str, Any]) -> bool:
    """Whether this top-level column's date format comes from its own declared parse format."""
    return date_shift_owns_declared_format(
        nested=False,
        logical_type=col.get("logical_type"),
        has_parse_format=col.get("parse_format") is not None,
    )


def _missing_in_child(site: StrategySite) -> Iterator[tuple[StrategyRequirement, str]]:
    """Each requirement a nested child leaves out, with its config path.

    Only descriptors rooted at `provider_config` apply: a child takes its parent's namespace
    (the nested handler copies it), so a root-level descriptor never binds the child. The child
    never inherits a declared-casting exemption from its parent.
    """
    if not isinstance(site.strategy, str):
        return
    config = site.config if isinstance(site.config, dict) else {}
    rooted = {"provider_config": config}
    for req in requirements_for(site.strategy):
        if req.path[0] != "provider_config":
            continue
        if requirement_applies(req, rooted) and requirement_missing(lookup_path(rooted, req.path)):
            yield req, ".".join((site.config_path, *req.path[1:]))


def _missing_requirements(
    site: StrategySite, derived: Any
) -> Iterator[tuple[StrategyRequirement, str]]:
    """Each requirement a strategy site leaves out with its path, in declaration order.

    A top-level column is held to every descriptor of its strategy. A nested child (a later
    site of the same column) is held to the descriptors rooted at `provider_config` only.
    """
    if site.nested:
        yield from _missing_in_child(site)
        return
    col = site.entry
    strategy = col.get("strategy")
    if not isinstance(strategy, str):
        return
    table_name, col_name = site.table, site.column
    where = f"tables.{table_name}.columns.{col_name}"
    for req in requirements_for(strategy):
        if req.path == ("namespace",) and (table_name, col_name) in derived:
            continue
        if req.path == ("provider_config", "date_format") and _declared_date_format(col):
            continue
        if requirement_applies(req, col) and requirement_missing(lookup_path(col, req.path)):
            yield req, f"{where}." + ".".join(req.path)


def check_required_strategy_settings(config: dict[str, Any]) -> None:
    """Refuse the first column that leaves out a setting its strategy requires.

    Config-only, so it runs in both compile entry points. Tables and columns are walked in config
    order and each strategy's descriptors in declaration order.

    Raises:
        PlanCompileError: the code of the missing setting's descriptor.
    """
    # A coherent_with member's namespace comes from its group's binding, so the column need not
    # declare one. The registry owns that rule; ask it instead of restating it.
    _, derived = composite_bindings(config)
    for site in strategy_sites(config):
        for req, path in _missing_requirements(site, derived):
            raise PlanCompileError(
                code=req.code,
                path=path,
                message=(f"column {site.column!r} in table {site.table!r}: {req.message}"),
            )
