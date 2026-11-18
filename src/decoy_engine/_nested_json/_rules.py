"""The one reader of a nested column's child strategy and child config.

A `nested` column keeps its child under `provider_config` (`target`, `strategy`,
`strategy_config`, `namespace`), or a list of them under `rules`. Every site that needs the child
calls `nested_children` instead of reading those keys, so a new child form reaches every site at
once. `path_relations` lists the rules that `references` a parent column.
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
UNSET: Final = object()


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
    # Empty when the rule has no `references`; else the one raw value, so a check still sees a
    # value that is not a mapping.
    references: tuple[Any, ...]
    config_path: str
    # A rule's own `strategy_config.provider`, `UNSET` when the key is absent.
    provider: Any = UNSET


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
    rule = rule if isinstance(rule, Mapping) else {}
    cfg = get("strategy_config")
    return NestedChild(
        index=index,
        target=get("target"),
        strategy=get("strategy"),
        strategy_config=get("strategy_config"),
        namespace=get("namespace"),
        references=(get("references"),) if "references" in rule else (),
        config_path=f"{SINGLE_FORM_PATH}.rules[{index}]",
        provider=cfg.get("provider", UNSET) if isinstance(cfg, Mapping) else UNSET,
    )


def effective_provider(child: NestedChild, column_provider: str | None) -> str | None:
    """The provider a child runs with: the one precedence rule for plan checks and the handler.

    A rule's own `strategy_config.provider` wins. When that key is present but is not a non-blank
    string the answer is `None`, never the column's provider, so a bad value is not hidden. An
    absent key, and the single form, use the column's provider.
    """
    if child.index is None:
        return column_provider
    if child.provider is UNSET:
        return column_provider if isinstance(column_provider, str) else None
    own = child.provider
    return own if isinstance(own, str) and own.strip() else None


@dataclass(frozen=True)
class PathRelation:
    """A nested rule's reference: the parent key column and the child payload column and path."""

    parent_table: str
    parent_column: str
    child_table: str
    child_column: str
    path: str


def reference_ends(child: NestedChild) -> tuple[str, str] | None:
    """The `(table, column)` a rule references, or `None` for no reference or a malformed one."""
    if not child.references or not isinstance(child.references[0], Mapping):
        return None
    table, column = child.references[0].get("table"), child.references[0].get("column")
    if isinstance(table, str) and isinstance(column, str) and table and column:
        return table, column
    return None


def path_relations(config: Mapping[str, Any]) -> tuple[PathRelation, ...]:
    """One relation per rule with a well-formed `references`, in config order.

    The one place the relations are listed. A malformed `references` is skipped here and refused
    by the plan check. Nothing reads the result before 82-E4b: path relations never enter the
    config's `relationships`, so no FK route, subset or orphan remap sees them.
    """
    found: list[PathRelation] = []
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, Mapping):
            continue
        for col in table.get("columns") or []:
            pc = col.get("provider_config") if isinstance(col, Mapping) else None
            if not isinstance(col, Mapping) or col.get("strategy") != "nested":
                continue
            if not isinstance(pc, Mapping):
                continue
            for child in nested_children(pc):
                ends = reference_ends(child)
                if ends is not None and isinstance(child.target, str):
                    found.append(
                        PathRelation(
                            ends[0],
                            ends[1],
                            str(table.get("name")),
                            str(col.get("name")),
                            child.target,
                        )
                    )
    return tuple(found)
