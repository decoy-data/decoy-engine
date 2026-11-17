"""YAML models of the pipeline `policy` block.

Strict throughout: no coercion of a bool or a number into a string, unknown keys refused, ids and
dates matched whole (`\\z`, never `$`). A `ColumnDecision` is the one canonical decision form:
rules, `policy.default` and the disguise rule for a classification all become one, so conflicts
are compared after normalizing to the `ColumnConfig` defaults once.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from decoy_engine import reasons
from decoy_engine._canonical import CanonicalJsonError, canonical_json_bytes
from decoy_engine.config.policy._selectors import Selector

__all__ = [
    "MAX_PROHIBITIONS",
    "MAX_RULES",
    "ColumnDecision",
    "DisguisePin",
    "PolicyConfig",
    "PolicyRule",
    "Prohibition",
    "json_carryable",
]

MAX_RULES = 200
MAX_PROHIBITIONS = 200
_MAX_STRATEGY_LIST = 50

# Rust regex: `\A` and `\z` anchor the whole value; `$` is not used.
Slug = Annotated[StrictStr, StringConstraints(pattern=r"\A[a-z0-9][a-z0-9_-]{0,63}\z")]
IsoDate = Annotated[StrictStr, StringConstraints(pattern=r"\A\d{4}-\d{2}-\d{2}\z")]
Why = Annotated[StrictStr, StringConstraints(max_length=500)]
StrategyName = Annotated[StrictStr, StringConstraints(min_length=1, max_length=64)]

_STRICT = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


def json_carryable(value: Any) -> bool:
    """True when `value` has a canonical JSON form (no NaN, infinity or foreign type)."""
    try:
        canonical_json_bytes(dict(value) if isinstance(value, Mapping) else value)
    except CanonicalJsonError:
        return False
    return True


class ColumnDecision(BaseModel):
    """What one mask column is told to do. The defaults equal the `ColumnConfig` defaults."""

    model_config = _STRICT

    strategy: StrategyName
    provider: StrictStr | None = None
    provider_config: dict[str, Any] = Field(default_factory=dict)
    namespace: StrictStr | None = None
    deterministic: bool = False
    allow_collisions: bool = False

    @field_validator("provider_config")
    @classmethod
    def _json_carryable(cls, value: dict[str, Any]) -> dict[str, Any]:
        """A NaN or other non-JSON value cannot be compared or digested; refuse it by code."""
        if not json_carryable(value):
            raise PydanticCustomError(
                str(reasons.config.POLICY_BLOCK_INVALID),
                "provider_config holds a value JSON cannot carry.",
            )
        return value


class DisguisePin(BaseModel):
    """A built-in disguise and the exact bundle version the pipeline was written against."""

    model_config = _STRICT

    id: Slug
    version: IsoDate


class PolicyRule(ColumnDecision):
    """A decision for every field the selector matches."""

    id: Slug
    select: Selector
    why: Why | None = None

    def decision(self) -> ColumnDecision:
        """The decision part alone, so a rule and `policy.default` compare as one type."""
        return ColumnDecision.model_validate(
            {name: getattr(self, name) for name in ColumnDecision.model_fields}
        )


class Prohibition(BaseModel):
    """Forbid or require a strategy set on the selected fields. Checked after expansion."""

    model_config = _STRICT

    id: Slug
    select: Selector
    forbid: list[StrategyName] | None = Field(
        default=None, min_length=1, max_length=_MAX_STRATEGY_LIST
    )
    require: list[StrategyName] | None = Field(
        default=None, min_length=1, max_length=_MAX_STRATEGY_LIST
    )
    why: Why | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> Prohibition:
        if (self.forbid is None) == (self.require is None):
            raise PydanticCustomError(
                str(reasons.config.POLICY_BLOCK_INVALID),
                "A prohibition sets exactly one of forbid and require.",
            )
        return self


class PolicyConfig(BaseModel):
    """The pipeline `policy:` block."""

    model_config = _STRICT

    disguise: DisguisePin | None = None
    rules: list[PolicyRule] = Field(default_factory=list, max_length=MAX_RULES)
    prohibit: list[Prohibition] = Field(default_factory=list, max_length=MAX_PROHIBITIONS)
    default: ColumnDecision | None = None

    @model_validator(mode="after")
    def _ids_unique(self) -> PolicyConfig:
        seen: set[str] = set()
        ids: list[str] = [*(r.id for r in self.rules), *(p.id for p in self.prohibit)]
        for item_id in ids:
            if item_id in seen:
                raise PydanticCustomError(
                    str(reasons.config.POLICY_BLOCK_INVALID),
                    "Rule and prohibition ids must be unique; {id} is used twice.",
                    {"id": item_id},
                )
            seen.add(item_id)
        return self
