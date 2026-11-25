"""Plan check: a code_set corpus locator or name must not carry credentials.

A corpus_source or code_set name that holds URL userinfo, or a query or fragment on a URL, would
be copied verbatim into the plan YAML and every file the CLI writes from it. The check refuses it
at validate and compile, before the plan exists, with the detector the diagnostics use
(`locator_carries_credentials`). It reads every `corpus_source` and `code_set` string under the
tables, with or without the `customer:` prefix. The message names the config position, never the
value.
"""

from collections.abc import Iterator
from typing import Any

from decoy_engine import reasons
from decoy_engine._locator import locator_carries_credentials
from decoy_engine.plan._errors import PlanCompileError

_FIELDS = ("corpus_source", "code_set")
_PREFIX = "customer:"
_NAME_MARKS = ("@", "?", "#")


def _values(node: Any) -> Iterator[tuple[str, str]]:
    """Every `(field, text)` pair of a corpus field under `node`, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _FIELDS and isinstance(value, str):
                yield key, value
            else:
                yield from _values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _values(item)


def check_code_set_corpus_locators(config: dict[str, Any]) -> None:
    """Refuse a credential-bearing corpus_source or code_set before plan construction.

    Config-only; runs in both compile branches and in `run_config_only_checks`.

    Raises:
        PlanCompileError: `code_set_corpus_source_credentials`.
    """
    for field, text in _values(config.get("tables")):
        text = text.removeprefix(_PREFIX)
        # A corpus name is a label, not a locator: one holding a URL mark is never a valid name.
        if locator_carries_credentials(text) or (
            field == "code_set" and any(mark in text for mark in _NAME_MARKS)
        ):
            raise PlanCompileError(
                code=reasons.plan.CODE_SET_CORPUS_SOURCE_CREDENTIALS,
                path=f"provider_config.{field}",
                message=(
                    f"a code_set {field} must not carry credentials (URL userinfo, or a "
                    "query or fragment on a URL). Keep the secret out of the locator "
                    "and give the file access through the environment or a credentials file."
                ),
            )
