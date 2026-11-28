"""The oracle route of the native chunked entry: the pandas loop with schema-rule evidence.

Moved out of `_chunked_entry` unchanged so the entry stays under its size ceiling.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.execution import _chunked, _chunked_oracle
from decoy_engine.execution.native._chunked_evidence import ColumnPlan, chunk_route_evidence
from decoy_engine.execution.native._chunked_oracle_rows import _oracle_preserved_rows
from decoy_engine.execution.native._chunked_schema_rule import SchemaRule, normalize_chunk

if TYPE_CHECKING:
    from decoy_engine.execution.native import NativeRouteEvidence


def oracle_route(
    state: Any,
    *,
    config: dict[str, Any],
    table: str,
    vault_writer: Any,
    chunk_result_sink: list[Any] | None,
    base_row_offset: int,
    rule: SchemaRule | None,
    columns: tuple[ColumnPlan, ...],
    decision: NativeRouteEvidence,
    read_passthrough: tuple[str, ...],
) -> Iterator[pa.Table]:
    # Eager, like the oracle's own preflight: a provider failure surfaces now.
    _chunked._warm_faker_pools(
        state.plan, table=table, registry=state.registry, pool_cache=state.pool_cache
    )
    if rule is None:
        return _chunked_oracle._oracle_masked(
            state,
            config=config,
            table=table,
            vault_writer=vault_writer,
            chunk_result_sink=chunk_result_sink,
            base_row_offset=base_row_offset,
        )
    produced = 0

    def on_chunk(result: Any, chunk: pa.Table) -> pa.Table:
        nonlocal produced
        out = normalize_chunk(rule, result.outputs[table], chunk, table=table, chunk_index=produced)
        produced += 1
        if chunk_result_sink is not None:
            elapsed: dict[str, float] = {}
            for rec in result.timings:
                elapsed[rec.column] = elapsed.get(rec.column, 0.0) + rec.elapsed_ms
            evidence = chunk_route_evidence(
                table=table,
                native_admitted=False,
                reroute_reason=decision.reroute_reason,
                decline_records=decision.decline_records,
                columns=columns,
                elapsed_ms=elapsed,
                pandas_read_passthrough=read_passthrough,
                preserved_rows=_oracle_preserved_rows(result.quality_metrics),
            )
            chunk_result_sink.append(
                dataclasses.replace(
                    result,
                    outputs={**result.outputs, table: out},
                    quality_metrics={**result.quality_metrics, "chunked_route": evidence},
                )
            )
        return out

    return _chunked_oracle._oracle_masked(
        state,
        config=config,
        table=table,
        vault_writer=vault_writer,
        chunk_result_sink=chunk_result_sink,
        base_row_offset=base_row_offset,
        on_chunk=on_chunk,
    )
