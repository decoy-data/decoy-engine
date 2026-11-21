"""The one walk over every strategy a config runs, top-level or inside a nested column.

A `nested` column runs child strategies (the single form, or one per rule). Every plan check and
stamp that has to look at "each place a strategy and its config appear" reads them here, so a
child is held to the same checks as a top-level column and the copies cannot drift:

- `strategy_sites`: one `StrategySite` per top-level column, then one per nested child.
- `provider_sites`: the provider-naming view of the same walk, for the two provider checks.

`tests/sentry/defects/test_nested_site_walker.py` fails on a plan or execution module that reads
nested children or `rules` on its own.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from decoy_engine._nested_json import UNSET, effective_provider, nested_children

__all__ = ["ProviderSite", "StrategySite", "column_sites", "provider_sites", "strategy_sites"]


@dataclass(frozen=True)
class StrategySite:
    """One strategy a column runs: where it is, its config, and the provider it runs with.

    For a top-level column `config` is its `provider_config` and `strategy` its own strategy. For
    a nested child it is the child's `strategy_config` and strategy. `rule` is the rule index, or
    `None` for a top-level column and the single nested form.
    """

    table: Any
    column: Any
    nested: bool
    rule: int | None
    strategy: Any
    config: Any
    config_path: str
    provider: Any
    provider_path: str
    entry: Mapping[str, Any]
    table_entry: Mapping[str, Any]

    @property
    def strategy_path(self) -> str:
        """The config path of the strategy name this site runs."""
        suffix = ".strategy_config" if self.nested else ".provider_config"
        return self.config_path.removesuffix(suffix) + ".strategy"

    @property
    def label(self) -> str:
        suffix = (
            ""
            if not self.nested
            else " (nested child)"
            if self.rule is None
            else (f" (rule {self.rule})")
        )
        return f"{self.table}.{self.column}{suffix}"


def column_sites(
    table_name: Any, col_entry: Mapping[str, Any], table_entry: Mapping[str, Any] | None = None
) -> Iterator[StrategySite]:
    """The sites of one column entry: the column itself, then each child of a nested column."""
    col_name = col_entry.get("name", "?")
    where = f"tables.{table_name}.columns.{col_name}"
    provider = col_entry.get("provider")
    pc = col_entry.get("provider_config")
    yield StrategySite(
        table_name,
        col_name,
        False,
        None,
        col_entry.get("strategy"),
        pc,
        f"{where}.provider_config",
        provider,
        f"{where}.provider",
        col_entry,
        table_entry or {},
    )
    if col_entry.get("strategy") != "nested" or not isinstance(pc, Mapping):
        return
    for child in nested_children(pc):
        at = f"{where}.{child.config_path}"
        own = child.provider is not UNSET
        yield StrategySite(
            table_name,
            col_name,
            True,
            child.index,
            child.strategy,
            child.strategy_config,
            f"{at}.strategy_config",
            effective_provider(child, provider),
            f"{at}.strategy_config.provider" if own else f"{where}.provider",
            col_entry,
            table_entry or {},
        )


def strategy_sites(config: Mapping[str, Any]) -> Iterator[StrategySite]:
    """Every strategy site of a config, in config order."""
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else ():
        if not isinstance(table, Mapping):
            continue
        for col in table.get("columns") or ():
            if isinstance(col, Mapping):
                yield from column_sites(table.get("name", "?"), col, table)


@dataclass(frozen=True)
class ProviderSite:
    """One place a config names a provider: where, which one, and whether a pool is built on it."""

    path: str
    provider: str
    pooled: bool
    label: str


def provider_sites(config: Mapping[str, Any]) -> Iterator[ProviderSite]:
    """Every provider the config names, in config order.

    A top-level column's `provider` is a site, pooled when the column is a faker column. A nested
    faker child (single form or rule) adds the provider it runs with (its own, else the column's),
    pooled, because a faker child always builds a pool. A child with no usable provider is not a
    site: `check_nested_rules` refuses it.
    """
    for site in strategy_sites(config):
        if site.provider is None or (site.nested and site.strategy != "faker"):
            continue
        yield ProviderSite(site.provider_path, site.provider, site.strategy == "faker", site.label)
