"""`delivery`: how a run's outputs become visible.

`strict` makes every output visible together or none of them. `best_effort` makes visible the
tables that passed and drops each failed table with the tables that depend on it. The default
is dropped from the dump (by value, `_global_settings.py` precedent), so a config that predates
the block keeps its exact dump and plan hash. `best_effort` is not built yet: `PipelineConfig`
and `compile_plan` refuse it, while this block type keeps accepting it for row 61b.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from decoy_engine import reasons
from decoy_engine._config_text import Problem, config_refusal, config_root_position
from decoy_engine.errors import PipelineValidationError

DeliveryMode = Literal["strict", "best_effort"]

__all__ = [
    "DeliveryConfig",
    "DeliveryMode",
    "is_unreleased_delivery_mode",
    "refuse_unreleased_delivery",
]


def is_unreleased_delivery_mode(mode: object) -> bool:
    """True for the one mode no run implements yet. Row 61b deletes this with its refusals."""
    return mode == "best_effort"


def best_effort_text() -> str:
    """The registry summary the validator prints; the raw guard builds its text from the same code."""
    return reasons.get("config", reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED).summary


def refuse_unreleased_delivery(config: Mapping[str, Any]) -> None:
    """Raise `PipelineValidationError` when a raw config asks for best-effort delivery.

    For entries that take a mapping and never build a `PipelineConfig`, such as `compile_plan`.
    """
    block = config.get("delivery")
    if isinstance(block, Mapping) and is_unreleased_delivery_mode(block.get("mode")):
        refusal = config_refusal(
            config_root_position("delivery"),
            Problem.NOT_ALLOWED,
            code=reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED,
        )
        raise PipelineValidationError(
            refusal.text,
            path=refusal.key,
            code=reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED,
        )


class DeliveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)

    mode: DeliveryMode = "strict"
