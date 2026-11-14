"""Required strategy settings, declared once.

Each descriptor names one setting a strategy cannot run without. The plan check
(``plan.checks.check_required_strategy_settings``), the strategy catalog and the starter config
builder all read this one table, so no layer keeps its own list of which strategies need a
namespace. Descriptors hold a registered code and a fixed message only: no submitted value and no
callable predicate, so a refusal cannot echo config data. This module imports ``reasons`` only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from decoy_engine import reasons

__all__ = [
    "REQUIREMENTS_BY_STRATEGY",
    "StrategyRequirement",
    "lookup_path",
    "requirement_applies",
    "requirements_for",
]


@dataclass(frozen=True)
class StrategyRequirement:
    """One setting a strategy needs, as a path from a column entry.

    ``when_path`` and ``when_equals`` make the requirement conditional: it applies only when the
    value at ``when_path`` has exactly the type and value of ``when_equals``, so ``1`` never
    activates a boolean condition.
    """

    path: tuple[str, ...]
    code: str
    message: str
    when_path: tuple[str, ...] | None = None
    when_equals: bool | str | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.message:
            raise ValueError("a strategy requirement needs a path and a message")
        if (self.when_path is None) != (self.when_equals is None):
            raise ValueError("when_path and when_equals are set together")


def _namespace(strategy: str, what: str | None = None, **when: Any) -> StrategyRequirement:
    code = getattr(reasons.plan, f"{strategy.upper()}_REQUIRES_NAMESPACE")
    return StrategyRequirement(
        ("namespace",), code, f"{what or strategy} needs a namespace; set `namespace`.", **when
    )


_PROVIDER = ("provider_config",)

REQUIREMENTS_BY_STRATEGY: Mapping[str, tuple[StrategyRequirement, ...]] = MappingProxyType(
    {
        "hash": (_namespace("hash"),),
        "fpe": (_namespace("fpe"),),
        "date_shift": (_namespace("date_shift"),),
        "bucket_perturb": (_namespace("bucket_perturb"),),
        "categorical": (_namespace("categorical"),),
        "tokenize": (_namespace("tokenize"),),
        "shuffle": (_namespace("shuffle", when_path=("deterministic",), when_equals=True),),
        "code_set": (
            _namespace(
                "code_set_gen",
                "code_set in gen mode",
                when_path=(*_PROVIDER, "mode"),
                when_equals="gen",
            ),
        ),
        "nested": (
            StrategyRequirement(
                (*_PROVIDER, "strategy"),
                reasons.plan.NESTED_STRATEGY_UNSET,
                "nested needs a child strategy; set `provider_config.strategy`.",
            ),
            StrategyRequirement(
                (*_PROVIDER, "target"),
                reasons.plan.NESTED_TARGET_UNSET,
                "nested needs a target path; set `provider_config.target`.",
            ),
        ),
    }
)


def requirements_for(strategy: str) -> tuple[StrategyRequirement, ...]:
    """The requirements of ``strategy``; empty when it declares none."""
    return REQUIREMENTS_BY_STRATEGY.get(strategy, ())


def lookup_path(entry: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = entry
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def requirement_applies(req: StrategyRequirement, entry: Mapping[str, Any]) -> bool:
    """Whether ``req`` binds the column ``entry``: always, or when its condition holds exactly."""
    if req.when_path is None:
        return True
    actual = lookup_path(entry, req.when_path)
    return type(actual) is type(req.when_equals) and actual == req.when_equals
