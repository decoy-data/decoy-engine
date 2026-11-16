"""Vault entry collection: the config walk and the positional source-to-masked pairing.

Split from `decoy_engine.vault` (a pure move, no behavior change) to keep that module under its
size goal; `vault` re-exports both names, which stay the public spelling.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyarrow as pa

__all__ = ["collect_vault_entries", "iter_vault_columns"]


def iter_vault_columns(config: dict[str, Any]) -> list[tuple[str, str, str]]:
    """List `(table, column, namespace)` for every `vault: true` mask column.

    Pure config walk; the compile check `check_vault_columns` has
    already guaranteed each vaulted column carries a namespace and a
    one-way strategy.
    """
    out: list[tuple[str, str, str]] = []
    for table_cfg in config.get("tables") or []:
        if not isinstance(table_cfg, dict):
            continue
        table = table_cfg.get("name")
        if not table:
            continue
        for col_cfg in table_cfg.get("columns") or []:
            if not isinstance(col_cfg, dict) or not col_cfg.get("vault"):
                continue
            name = col_cfg.get("name")
            namespace = col_cfg.get("namespace")
            if name and namespace:
                out.append((str(table), str(name), str(namespace)))
    return out


def collect_vault_entries(
    config: dict[str, Any],
    sources: Mapping[str, pa.Table],
    outputs: Mapping[str, pa.Table],
) -> list[tuple[str, str, str]]:
    """Pair source and masked values for every vaulted column.

    Returns `(namespace, masked, source)` string triples. Masking
    preserves row count and order, so pairing is positional: source row
    i maps to output row i. Rows where either side is null are skipped
    (null is preserved by every strategy; there is nothing to recover).
    """
    entries: list[tuple[str, str, str]] = []
    for table, column, namespace in iter_vault_columns(config):
        src_tbl = sources.get(table)
        out_tbl = outputs.get(table)
        if src_tbl is None or out_tbl is None:
            continue
        if column not in src_tbl.schema.names or column not in out_tbl.schema.names:
            continue
        src_values = src_tbl.column(column).to_pylist()
        out_values = out_tbl.column(column).to_pylist()
        for src, masked in zip(src_values, out_values, strict=True):
            if src is None or masked is None:
                continue
            entries.append((namespace, str(masked), str(src)))
    return entries
