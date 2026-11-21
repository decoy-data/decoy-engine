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
from decoy_engine.plan.checks._strategy_sites import strategy_sites
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
    """Refuse a `text_mask` column or nested child whose `detectors` or strategies cannot run."""
    for site in strategy_sites(config):
        if site.strategy == "text_mask" and isinstance(site.config, dict):
            label = f"table {site.table!r}, column {site.column!r}"
            if site.rule is not None:
                label += f", rule {site.rule}"
            _check_column(site.config, site.config_path, label)


def _check_column(pc: dict[str, Any], at: str, label: str) -> None:
    code_unknown = reasons.config.MASK_TEXT_MASK_DETECTOR_UNKNOWN
    code_unsupported = reasons.config.MASK_TEXT_MASK_STRATEGY_UNSUPPORTED
    selectors = pc.get("detectors")
    if selectors is not None and not isinstance(selectors, (list, tuple)):
        raise _refuse(code_unknown, f"{at}.detectors", f"{label}: {_shown(selectors)}")
    for det in selectors or ():
        if not isinstance(det, str) or det not in SELECTABLE_TEXT_MASK_DETECTORS:
            raise _refuse(code_unknown, f"{at}.detectors", f"{label}: {_shown(det)}")
    overrides = pc.get("per_detector_strategy")
    if overrides is not None and not isinstance(overrides, dict):
        raise _refuse(
            code_unsupported,
            f"{at}.per_detector_strategy",
            f"{label}: {_shown(overrides)}",
        )
    for det, strategy in (overrides or {}).items():
        path = f"{at}.per_detector_strategy.{det if isinstance(det, str) else '?'}"
        if not isinstance(det, str) or det not in TEXT_MASK_STRATEGY_DETECTORS:
            raise _refuse(code_unknown, path, f"{label}: {_shown(det)}")
        if not isinstance(strategy, str) or not strategy_supported(det, strategy):
            raise _refuse(
                code_unsupported,
                path,
                f"{label}: detector {det!r}, strategy {_shown(strategy)}",
            )
