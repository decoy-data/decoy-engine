"""Catalog of the ``plan`` namespace: the ``rules`` form of a nested column."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED, Phase

__all__ = [
    "NESTED_RULES_AND_TARGET_BOTH_SET",
    "NESTED_RULES_CODE_SET_REPEATED",
    "NESTED_RULES_EMPTY",
    "NESTED_RULE_FAKER_PROVIDER_MISSING",
    "NESTED_RULE_KEY_UNKNOWN",
    "NESTED_RULE_NAMESPACE_INVALID",
    "NESTED_RULE_TARGET_DUPLICATE",
]

_d = _catalog.plan("PlanCompileError")
# A pipeline config is checked at validation time and again when the plan compiles.
_BOTH = (Phase.CONFIGURATION, Phase.COMPILE)

NESTED_RULES_AND_TARGET_BOTH_SET = _d(
    "nested_rules_and_target_both_set",
    "A nested column sets both a rules list and a single target or strategy.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULES_EMPTY = _d(
    "nested_rules_empty",
    "A nested column sets rules that are not a non-empty list.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULE_TARGET_DUPLICATE = _d(
    "nested_rule_target_duplicate",
    "Two rules of one nested column have the same target.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULES_CODE_SET_REPEATED = _d(
    "nested_rules_code_set_repeated",
    "A nested column has more than one code_set rule.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULE_KEY_UNKNOWN = _d(
    "nested_rule_key_unknown",
    "A nested rule sets a key other than target, strategy, strategy_config or namespace.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULE_NAMESPACE_INVALID = _d(
    "nested_rule_namespace_invalid",
    "A nested rule's namespace is not a non-blank string.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_RULE_FAKER_PROVIDER_MISSING = _d(
    "nested_rule_faker_provider_missing",
    "A nested faker rule has no provider in its strategy_config or on the column.",
    phases=_BOTH,
    since=UNRELEASED,
)
