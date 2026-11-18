"""Plan checks for the `rules` form of a nested column.

Config-only, so it runs in both compile entry points. A `rules` column is not refused by the
required-settings table for a missing top-level target or strategy (`unless_present`); each rule
gets the same two refusals here, at its own path. Messages are fixed text: no config value.

A rule may also `references` a parent column, so its leaf masks under the parent's identity. The
static checks here need the config only; `bind_reference_key_kinds` reads the parent's profiled
dtype, fixes the key kind the run checks each leaf against, and runs in `compile_plan` only.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from decoy_engine import reasons
from decoy_engine._nested_json import (
    UNSET,
    NestedChild,
    effective_provider,
    nested_children,
    reference_ends,
    singular_path,
)
from decoy_engine.plan._checks import _is_integer_dtype
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.profile._types import Profile
from decoy_engine.quality._freetext_advisory import is_string_dtype_label

__all__ = ["bind_reference_key_kinds", "check_nested_rules"]


_RULE_KEYS = frozenset({"target", "strategy", "strategy_config", "namespace", "references"})
# `fpe` is out: its tweak is column-scoped, so a leaf would not match the parent's value.
_JOIN_SAFE = frozenset({"hash", "tokenize"})


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def check_nested_rules(config: dict[str, Any]) -> None:
    """Refuse the first nested `rules` column that is malformed.

    Raises:
        PlanCompileError: the code of the first failing rule, in config order.
    """
    for where, col, pc in _rules_columns(config):
        _check_column(where, pc, column_provider=col.get("provider"))
    for where, col, pc in _rules_columns(config):
        _check_references(config, where, col, pc)


def _rules_columns(config: Mapping[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Each nested column that uses `rules`, with its config path, in config order."""
    found = []
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict) or col.get("strategy") != "nested":
                continue
            pc = col.get("provider_config")
            if isinstance(pc, dict) and "rules" in pc:
                where = f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}"
                found.append((where, col, pc))
    return found


def _check_column(where: str, pc: dict[str, Any], *, column_provider: Any) -> None:
    rules = pc["rules"]
    if "target" in pc or "strategy" in pc:
        raise PlanCompileError(
            code=reasons.plan.NESTED_RULES_AND_TARGET_BOTH_SET,
            path=f"{where}.provider_config.rules",
            message="A nested column sets `rules` and also a single `target` or `strategy`. "
            "Use one form.",
        )
    if not isinstance(rules, list) or not rules:
        raise PlanCompileError(
            code=reasons.plan.NESTED_RULES_EMPTY,
            path=f"{where}.provider_config.rules",
            message="A nested column's `rules` must be a non-empty list.",
        )
    seen_targets: set[str] = set()
    code_set_seen = False
    for child, rule in zip(nested_children(pc), rules, strict=True):
        at = f"{where}.{child.config_path}"
        for key in rule if isinstance(rule, dict) else ():
            if key not in _RULE_KEYS:
                raise PlanCompileError(
                    code=reasons.plan.NESTED_RULE_KEY_UNKNOWN,
                    path=f"{at}.{key}",
                    message="A nested rule may set only `target`, `strategy`, `strategy_config` "
                    "and `namespace`.",
                )
        if "namespace" in (rule if isinstance(rule, dict) else ()) and _blank(child.namespace):
            raise PlanCompileError(
                code=reasons.plan.NESTED_RULE_NAMESPACE_INVALID,
                path=f"{at}.namespace",
                message="A nested rule's `namespace` must be a non-blank string.",
            )
        if _blank(child.target):
            raise PlanCompileError(
                code=reasons.plan.NESTED_TARGET_UNSET,
                path=f"{at}.target",
                message="A nested rule needs a target path; set `target`.",
            )
        if _blank(child.strategy):
            raise PlanCompileError(
                code=reasons.plan.NESTED_STRATEGY_UNSET,
                path=f"{at}.strategy",
                message="A nested rule needs a child strategy; set `strategy`.",
            )
        if child.provider is not UNSET and _blank(child.provider):
            raise PlanCompileError(
                code=reasons.plan.NESTED_RULE_PROVIDER_INVALID,
                path=f"{at}.strategy_config.provider",
                message="A nested rule's `provider` must be a non-blank string.",
            )
        if child.strategy == "faker":
            _check_faker_provider(at, child, column_provider, where)
        if child.target in seen_targets:
            raise PlanCompileError(
                code=reasons.plan.NESTED_RULE_TARGET_DUPLICATE,
                path=f"{at}.target",
                message="Two rules of one nested column have the same target. "
                "Merge them into one rule.",
            )
        seen_targets.add(child.target)
        if child.strategy == "code_set":
            if code_set_seen:
                raise PlanCompileError(
                    code=reasons.plan.NESTED_RULES_CODE_SET_REPEATED,
                    path=f"{at}.strategy",
                    message="A nested column may have only one `code_set` rule: its corpus is "
                    "pinned once per column.",
                )
            code_set_seen = True


def _check_faker_provider(at: str, child: Any, column_provider: Any, where: str) -> None:
    """A faker rule needs a provider the registry knows and a pool can build.

    The column's own provider is already checked for being known by `check_unknown_provider`; a
    nested column is not a faker column, so its pool check is done here for the rule that uses it.
    """
    from decoy_engine.providers_v2 import get_default_registry

    provider = effective_provider(child, column_provider)
    own = child.provider is not UNSET
    path = f"{at}.strategy_config.provider" if own or provider is None else f"{where}.provider"
    if provider is None:
        raise PlanCompileError(
            code=reasons.plan.NESTED_RULE_FAKER_PROVIDER_MISSING,
            path=path,
            message="A nested faker rule needs a provider: set `strategy_config.provider` "
            "or the column's `provider`.",
        )
    registry = get_default_registry()
    if provider not in registry.known_providers():
        raise PlanCompileError(
            code=reasons.plan.UNKNOWN_PROVIDER,
            path=path,
            message="A nested faker rule names a provider that is not in the default registry.",
        )
    if not registry.get_capabilities(provider).poolable:
        raise PlanCompileError(
            code=reasons.plan.NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND,
            path=path,
            message="A nested faker rule names a provider that declares poolable=False, so its "
            "pool cannot be built. Use a poolable provider.",
        )


def _refuse(code: str, path: str, message: str) -> PlanCompileError:
    return PlanCompileError(code=code, path=path, message=message)


def _parent_column(config: Mapping[str, Any], child: NestedChild) -> dict[str, Any] | None:
    ends = reference_ends(child)
    for table in config.get("tables") or []:
        if isinstance(table, dict) and ends and table.get("name") == ends[0]:
            for col in table.get("columns") or []:
                if isinstance(col, dict) and col.get("name") == ends[1]:
                    return col
    return None


def _check_references(
    config: Mapping[str, Any], where: str, col: dict[str, Any], pc: dict[str, Any]
) -> None:
    """The static refusals for each rule that sets `references`, in the order the plan lists."""
    for child in nested_children(pc):
        if not child.references:
            continue
        at = f"{where}.{child.config_path}"
        refs = child.references[0]
        if isinstance(refs, Mapping) and "key_kind" in refs:
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_KEY_KIND_RESERVED,
                f"{at}.references.key_kind",
                "`references.key_kind` is set by the planner from the profile. Remove it.",
            )
        if singular_path(child.target) is None:
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_PATH_NOT_SINGULAR,
                f"{at}.target",
                "A rule with `references` needs a singular path of names, such as "
                "`$.customer_id` or `$.ref.customer_id`.",
            )
        parent = _parent_column(config, child)
        if parent is None:
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_PARENT_UNKNOWN,
                f"{at}.references",
                "`references` must name a table and a column that the config declares.",
            )
        if parent.get("when"):
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_PARENT_CONDITIONAL,
                f"{at}.references",
                "The referenced column has a `when` condition, so rows it skips keep their "
                "source key and would not match the path leaf. Reference a column that "
                "is masked on every row.",
            )
        if parent.get("strategy") not in _JOIN_SAFE:
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_STRATEGY_NOT_JOIN_SAFE,
                f"{at}.references",
                "The referenced column must be masked with `hash` or `tokenize`.",
            )
        if child.strategy != parent.get("strategy") or (child.strategy_config or {}) != (
            parent.get("provider_config") or {}
        ):
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_STRATEGY_MISMATCH,
                f"{at}.strategy",
                "The rule must use the same strategy and config as the referenced column.",
            )
        if (child.namespace or col.get("namespace")) != parent.get("namespace"):
            raise _refuse(
                reasons.plan.NESTED_REFERENCE_NAMESPACE_MISMATCH,
                f"{at}.namespace",
                "The rule must use the same namespace as the referenced column.",
            )


def _key_kind(dtype: str, strategy: Any) -> str | None:
    """The leaf kind a parent of this profiled dtype takes, `None` when it takes neither."""
    if _is_integer_dtype(dtype):
        return None if strategy == "tokenize" else "integer"
    return "string" if is_string_dtype_label(dtype) else None


def bind_reference_key_kinds(config: dict[str, Any], profile: Profile | None) -> dict[str, Any]:
    """A copy of `config` with `key_kind` written into each rule's `references`.

    The parent's profiled dtype fixes the kind: an integer parent takes JSON integers and a string
    parent takes JSON strings, so `42` and `"42"` can never hash to different tokens. The kind
    sits in `references`, outside the child's `strategy_config`, so the child's draws do not
    change. A config with no reference is returned as it is.

    Raises:
        PlanCompileError: no profile (`no_profile=True`, so no dtype to trust), the parent is
            not in the profile, or its dtype is not an integer or a string, or it is a
            `tokenize` column over integers, which `tokenize` refuses at run time.
    """
    if not any(
        child.references for _, _, pc in _rules_columns(config) for child in nested_children(pc)
    ):
        return config
    bound = copy.deepcopy(config)
    dtypes = {
        (t.name, c.name): c.dtype for t in (profile.tables if profile else ()) for c in t.columns
    }
    for where, _col, pc in _rules_columns(bound):
        for child in nested_children(pc):
            ends = reference_ends(child)
            if not child.references or ends is None:
                continue
            at = f"{where}.{child.config_path}"
            if profile is None:
                raise _refuse(
                    reasons.plan.NESTED_REFERENCE_REQUIRES_PROFILE,
                    f"{at}.references",
                    "`references` needs the parent column's profiled type. Compile with a profile.",
                )
            parent = _parent_column(bound, child)
            dtype = dtypes.get(ends)
            kind = (
                None
                if dtype is None or parent is None
                else _key_kind(dtype, parent.get("strategy"))
            )
            if kind is None:
                raise _refuse(
                    reasons.plan.NESTED_REFERENCE_PARENT_TYPE_UNSUPPORTED,
                    f"{at}.references",
                    "The referenced column must be an integer or a string key, "
                    "and `tokenize` takes string keys only.",
                )
            rule = pc["rules"][child.index]
            rule["references"] = {**rule["references"], "key_kind": kind}
    return bound
