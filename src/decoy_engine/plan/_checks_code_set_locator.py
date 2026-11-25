"""Plan check: a code_set corpus locator must not carry credentials.

A `customer:` corpus_source that holds URL userinfo, or a query or fragment on a remote URL, would
be copied verbatim into the plan YAML and every file the CLI writes from it. The check refuses it
at validate and compile, before the plan exists, using the same detection the diagnostics use
(`fileaccess.without_url_credentials` changes a locator only when it carries one). The message
names the config position, never the locator.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from decoy_engine import fileaccess, reasons
from decoy_engine.plan._errors import PlanCompileError

_PREFIX = "customer:"


def _sources(node: Any) -> Iterator[str]:
    """Every `corpus_source` string under `node`, at any depth (nested children included)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "corpus_source" and isinstance(value, str):
                yield value
            else:
                yield from _sources(value)
    elif isinstance(node, list):
        for item in node:
            yield from _sources(item)


def check_code_set_corpus_locators(config: dict[str, Any]) -> None:
    """Refuse a credential-bearing `customer:` corpus_source before plan construction.

    Config-only; runs in both compile branches and in `run_config_only_checks`.

    Raises:
        PlanCompileError: `code_set_corpus_source_credentials`.
    """
    for source in _sources(config.get("tables")):
        if not source.startswith(_PREFIX):
            continue
        locator = source[len(_PREFIX) :]
        if fileaccess.without_url_credentials(locator) != locator:
            raise PlanCompileError(
                code=reasons.plan.CODE_SET_CORPUS_SOURCE_CREDENTIALS,
                path="provider_config.corpus_source",
                message=(
                    "a code_set corpus_source must not carry credentials (URL userinfo, or a "
                    "query or fragment on a remote URL). Keep the secret out of the locator "
                    "and give the file access through the environment or a credentials file."
                ),
            )
