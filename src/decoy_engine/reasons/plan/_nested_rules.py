"""Catalog of the ``plan`` namespace: the ``rules`` form of a nested column and its references."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED, Phase

__all__ = [
    "NESTED_REFERENCE_KEY_KIND_RESERVED",
    "NESTED_REFERENCE_NAMESPACE_MISMATCH",
    "NESTED_REFERENCE_PARENT_CONDITIONAL",
    "NESTED_REFERENCE_PARENT_TYPE_UNSUPPORTED",
    "NESTED_REFERENCE_PARENT_UNKNOWN",
    "NESTED_REFERENCE_PATH_NOT_SINGULAR",
    "NESTED_REFERENCE_REQUIRES_PROFILE",
    "NESTED_REFERENCE_STRATEGY_MISMATCH",
    "NESTED_REFERENCE_STRATEGY_NOT_JOIN_SAFE",
    "NESTED_RULES_AND_TARGET_BOTH_SET",
    "NESTED_RULES_CODE_SET_REPEATED",
    "NESTED_RULES_EMPTY",
    "NESTED_RULE_FAKER_PROVIDER_MISSING",
    "NESTED_RULE_KEY_UNKNOWN",
    "NESTED_RULE_NAMESPACE_INVALID",
    "NESTED_RULE_PROVIDER_INVALID",
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
NESTED_RULE_PROVIDER_INVALID = _d(
    "nested_rule_provider_invalid",
    "A nested rule sets a provider that is not a non-blank string.",
    phases=_BOTH,
    since=UNRELEASED,
)


NESTED_REFERENCE_PATH_NOT_SINGULAR = _d(
    "nested_reference_path_not_singular",
    "A nested rule with references targets a path that is not a singular path of names.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_PARENT_UNKNOWN = _d(
    "nested_reference_parent_unknown",
    "A nested rule references a parent table or column that the config does not declare.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_STRATEGY_NOT_JOIN_SAFE = _d(
    "nested_reference_strategy_not_join_safe",
    "A nested rule references a parent column masked by a strategy other than hash or tokenize.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_STRATEGY_MISMATCH = _d(
    "nested_reference_strategy_mismatch",
    "A nested rule masks with a different strategy or config than the parent column it references.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_NAMESPACE_MISMATCH = _d(
    "nested_reference_namespace_mismatch",
    "A nested rule uses a different namespace than the parent column it references.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_PARENT_CONDITIONAL = _d(
    "nested_reference_parent_conditional",
    "A nested rule references a parent column that is masked only when a condition holds.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_KEY_KIND_RESERVED = _d(
    "nested_reference_key_kind_reserved",
    "A nested rule sets key_kind in references, which the planner fills from the profile.",
    phases=_BOTH,
    since=UNRELEASED,
)
NESTED_REFERENCE_PARENT_TYPE_UNSUPPORTED = _d(
    "nested_reference_parent_type_unsupported",
    "A nested rule references a parent column that is neither an integer nor a string key.",
    phases=(Phase.COMPILE,),
    since=UNRELEASED,
)
NESTED_REFERENCE_REQUIRES_PROFILE = _d(
    "nested_reference_requires_profile",
    "A nested rule with references has no profiled key kind: compile it with a profile.",
    phases=(Phase.COMPILE,),
    since=UNRELEASED,
)
