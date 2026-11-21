"""Plan-time check for `text_mask` columns: detector ids and strategy pairs the engine can run.

`text_mask` used to dispatch each span on its strategy without asking whether the strategy fits the
detector: `date_shift` on an SSN wrote the SSN through, and an unknown detector id was skipped. The
refusals here name the table, column, detector id and strategy, never a cell value. `decoy validate`
(`run_config_only_checks`) and `decoy run` (`compile_plan`) both call this, so they refuse the same
configs.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan.checks._generate_columns import _located
from decoy_engine.transforms.text_mask import (
    SELECTABLE_TEXT_MASK_DETECTORS,
    TEXT_MASK_STRATEGY_DETECTORS,
    strategy_supported,
)

__all__ = ["check_text_mask_strategies"]


def _refuse(code: Any, path: str, where: str) -> PlanCompileError:
    return _located(str(code), path, where=where)


def _shown(item: Any) -> str:
    return repr(item[:64]) if isinstance(item, str) else f"a value of type {type(item).__name__}"


def check_text_mask_strategies(config: dict[str, Any]) -> None:
    """Refuse a `text_mask` column whose `detectors` or `per_detector_strategy` cannot run."""
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict) or col.get("strategy") != "text_mask":
                continue
            pc = col.get("provider_config")
            if isinstance(pc, dict):
                where = f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}"
                _check_column(pc, where, f"table {table.get('name')!r}, column {col.get('name')!r}")


def _check_column(pc: dict[str, Any], where: str, label: str) -> None:
    code_unknown = reasons.config.MASK_TEXT_MASK_DETECTOR_UNKNOWN
    code_unsupported = reasons.config.MASK_TEXT_MASK_STRATEGY_UNSUPPORTED
    selectors = pc.get("detectors")
    if selectors is not None and not isinstance(selectors, (list, tuple)):
        raise _refuse(
            code_unknown, f"{where}.provider_config.detectors", f"{label}: {_shown(selectors)}"
        )
    for det in selectors or ():
        if not isinstance(det, str) or det not in SELECTABLE_TEXT_MASK_DETECTORS:
            raise _refuse(
                code_unknown, f"{where}.provider_config.detectors", f"{label}: {_shown(det)}"
            )
    overrides = pc.get("per_detector_strategy")
    if overrides is not None and not isinstance(overrides, dict):
        raise _refuse(
            code_unsupported,
            f"{where}.provider_config.per_detector_strategy",
            f"{label}: {_shown(overrides)}",
        )
    for det, strategy in (overrides or {}).items():
        path = (
            f"{where}.provider_config.per_detector_strategy.{det if isinstance(det, str) else '?'}"
        )
        if not isinstance(det, str) or det not in TEXT_MASK_STRATEGY_DETECTORS:
            raise _refuse(code_unknown, path, f"{label}: {_shown(det)}")
        if not isinstance(strategy, str) or not strategy_supported(det, strategy):
            raise _refuse(
                code_unsupported,
                path,
                f"{label}: detector {det!r}, strategy {_shown(strategy)}",
            )
