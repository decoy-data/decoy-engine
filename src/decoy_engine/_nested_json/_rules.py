"""The one reader of a nested column's child strategy and child config.

A `nested` column keeps its child under `provider_config` (`target`, `strategy`,
`strategy_config`, `namespace`). Every site that needs the child calls `nested_children` instead
of reading those keys, so a second child form added later reaches every site at once.
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
    """The children of a nested column: one for the single form."""
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
