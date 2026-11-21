"""The one walk over every provider a config names, for the provider checks.

`check_unknown_provider` and `check_non_poolable_provider_with_pool_backend` both read the sites
from here, so a provider named in a place the walk reaches is held to both checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from decoy_engine._nested_json import UNSET, effective_provider, nested_children

__all__ = ["ProviderSite", "provider_sites"]


@dataclass(frozen=True)
class ProviderSite:
    """One place a config names a provider: where, which one, and whether a pool is built on it."""

    path: str
    provider: str
    pooled: bool
    label: str


def provider_sites(config: dict[str, Any]) -> Iterator[ProviderSite]:
    """Every provider the config names, in config order: the one walker both checks read.

    A column's own `provider` is a site, pooled when the column is a faker column. A `rules`
    column adds, for each faker rule, the provider the rule runs with (its own, else the
    column's), pooled, because a faker rule always builds a pool. A rule with no usable provider
    is not a site: `check_nested_rules` refuses it.
    """
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            col_name = col_entry.get("name", "?")
            where = f"tables.{table_name}.columns.{col_name}"
            label = f"{table_name}.{col_name}"
            provider = col_entry.get("provider")
            if provider is not None:
                yield ProviderSite(
                    f"{where}.provider", provider, col_entry.get("strategy") == "faker", label
                )
            pc = col_entry.get("provider_config")
            if (
                col_entry.get("strategy") != "nested"
                or not isinstance(pc, dict)
                or "rules" not in pc
            ):
                continue
            for child in nested_children(pc):
                if child.strategy != "faker":
                    continue
                effective = effective_provider(child, provider)
                if effective is None:
                    continue
                own = child.provider is not UNSET
                path = (
                    f"{where}.{child.config_path}.strategy_config.provider"
                    if own
                    else (f"{where}.provider")
                )
                yield ProviderSite(path, effective, True, f"{label} (rule {child.index})")
