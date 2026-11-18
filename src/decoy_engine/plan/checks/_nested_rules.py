"""Plan checks for the `rules` form of a nested column.

Config-only, so it runs in both compile entry points. A `rules` column is not refused by the
required-settings table for a missing top-level target or strategy (`unless_present`); each rule
gets the same two refusals here, at its own path. Messages are fixed text: no config value.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine._nested_json import nested_children
from decoy_engine.plan._errors import PlanCompileError

__all__ = ["check_nested_rules"]


_RULE_KEYS = frozenset({"target", "strategy", "strategy_config", "namespace"})


def _provider_named(strategy_config: Any, column_provider: Any) -> bool:
    own = strategy_config.get("provider") if isinstance(strategy_config, dict) else None
    return not _blank(own) or not _blank(column_provider)


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def check_nested_rules(config: dict[str, Any]) -> None:
    """Refuse the first nested `rules` column that is malformed.

    Raises:
        PlanCompileError: the code of the first failing rule, in config order.
    """
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict) or col.get("strategy") != "nested":
                continue
            pc = col.get("provider_config")
            if not isinstance(pc, dict) or "rules" not in pc:
                continue
            where = f"tables.{table.get('name', '?')}.columns.{col.get('name', '?')}"
            _check_column(where, pc, column_provider=col.get("provider"))


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
        if child.strategy == "faker" and not _provider_named(
            child.strategy_config, column_provider
        ):
            raise PlanCompileError(
                code=reasons.plan.NESTED_RULE_FAKER_PROVIDER_MISSING,
                path=f"{at}.strategy_config.provider",
                message="A nested faker rule needs a provider: set `strategy_config.provider` "
                "or the column's `provider`.",
            )
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
