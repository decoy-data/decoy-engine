"""The one reader of a nested column's child strategy and child config.

A `nested` column keeps its child under `provider_config` (`target`, `strategy`,
`strategy_config`, `namespace`), or a list of them under `rules`. Every site that needs the child
calls `nested_children` instead of reading those keys, so a new child form reaches every site at
once.
`tests/sentry/defects/test_nested_child_choke_point.py` fails on a module that reads the keys
itself.

The reader takes the provider-config mapping, not a column entry: the multi-table runner reads
the child from a seed's provider config, which has no column around it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

SINGLE_FORM_PATH: Final = "provider_config"


@dataclass(frozen=True)
class NestedChild:
    """One child strategy of a nested column.

    Values are the raw config values: a site that validates them keeps doing so, so a refusal
    keeps its code and text. `index` is `None` for the single form. `config_path` is the prefix
    a refusal path uses below the column, so the single form keeps its path text exactly.
    """

    index: int | None
    target: Any
    strategy: Any
    strategy_config: Any
    namespace: Any
    references: tuple[Any, ...]
    config_path: str


def nested_children(provider_config: Mapping[str, Any]) -> tuple[NestedChild, ...]:
    """The children of a nested column: one per rule for the `rules` form, else the single child.

    A `rules` value that is empty or not a list gives no children; the plan check refuses it
    before a run, and the handler fails closed if one still arrives.
    """
    if "rules" in provider_config:
        rules = provider_config["rules"]
        return (
            tuple(_rule_child(i, r) for i, r in enumerate(rules)) if isinstance(rules, list) else ()
        )
    return (
        NestedChild(
            index=None,
            target=provider_config.get("target"),
            strategy=provider_config.get("strategy"),
            strategy_config=provider_config.get("strategy_config"),
            namespace=provider_config.get("namespace"),
            references=(),
            config_path=SINGLE_FORM_PATH,
        ),
    )


def _rule_child(index: int, rule: Any) -> NestedChild:
    get = rule.get if isinstance(rule, Mapping) else (lambda _key: None)
    return NestedChild(
        index=index,
        target=get("target"),
        strategy=get("strategy"),
        strategy_config=get("strategy_config"),
        namespace=get("namespace"),
        references=(),
        config_path=f"{SINGLE_FORM_PATH}.rules[{index}]",
    )
