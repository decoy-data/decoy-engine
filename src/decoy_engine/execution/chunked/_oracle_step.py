"""One chunk through the pandas oracle: the guards, the adapter call, the row-error fail-closed.

`_chunked_oracle._oracle_masked` calls this once per chunk. The body lives here so that every
caller that runs a chunk on the oracle shares one copy of the schema guards, the DGRN offset
check, the carry handling and the row-error raise, and the adapter is called from one place.

Two tables, on purpose: `source_chunk` is the full chunk and feeds every guard and `on_chunk`;
`adapter_chunk` is what the adapter, `carry` and the row-error summary see. The oracle loop
passes the same chunk for both.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.execution import _chunked_bucket_perturb as bucket_perturb_gate
from decoy_engine.execution import _chunked_code_set as code_set_gate
from decoy_engine.execution import _chunked_dgrn as dgrn
from decoy_engine.execution import _chunked_text_mask as text_mask_gate
from decoy_engine.execution._chunked_carry import adapter_fk_safe_columns
from decoy_engine.execution._chunked_fk import reject_lossy_chunked_fk_passthrough
from decoy_engine.execution._chunked_fk_dtype import reject_mismatched_chunked_fk_declared_dtype
from decoy_engine.execution._row_error_summary import chunk_row_error_summary

if TYPE_CHECKING:
    from decoy_engine.execution._chunked_oracle import OraclePreflightState


@dataclass(frozen=True)
class OracleChunkStep:
    """What one oracle step runs and where its result goes.

    `plan` is the plan handed to the adapter (the preflight's plan today). `on_chunk(result,
    source_chunk)` returns the table to yield and owns any enriched result for the sink.
    """

    plan: Any
    table: str
    on_chunk: Callable[[Any, pa.Table], pa.Table] | None = None
    chunk_result_sink: list[Any] | None = None


def oracle_chunk_step(
    state: OraclePreflightState,
    step: OracleChunkStep,
    *,
    source_chunk: pa.Table,
    adapter_chunk: pa.Table,
    chunk_index: int,
    row_offset: int,
) -> pa.Table:
    """Mask one chunk on the oracle and return the table to yield.

    In this order: schema guards on `source_chunk`; DGRN offset domain check; adapter run; the
    raw result goes to `step.chunk_result_sink` (always when `on_chunk` is None, and for a
    failing chunk even when it is set, so a row-error chunk is reported unnormalized); fail
    closed on row errors; `on_chunk(result, source_chunk)`. The caller advances the row offset
    and adds vault entries.
    """
    from decoy_engine.errors import RowErrorsFailedError

    carry = state.carry
    table = step.table
    if state.guard_passthrough_fk_columns:
        reject_lossy_chunked_fk_passthrough(
            source_chunk, table=table, passthrough_fk_columns=state.guard_passthrough_fk_columns
        )
    # `hash_fk_key_columns` triggers the guard independently of
    # `declared_fk_dtypes`: `dtype` is optional in config, so a hash FK key
    # with no declared dtype leaves `declared_fk_dtypes` empty yet still
    # needs predicate 12's real-type check (else an unsafe real
    # date64/decimal256 reaches the kernel unchecked).
    if state.declared_fk_dtypes or state.hash_fk_key_columns:
        reject_mismatched_chunked_fk_declared_dtype(
            source_chunk,
            table=table,
            declared_fk_dtypes=state.declared_fk_dtypes,
            hash_fk_key_columns=state.hash_fk_key_columns,
        )
    # These source columns must stay a chunk-stable string on every chunk,
    # not just the first (the iterable's dtype can drift).
    if state.text_mask_cols:
        text_mask_gate.reject_unsafe_text_mask_chunk_schema(
            source_chunk.schema, state.text_mask_cols, table=table
        )
    if state.code_set_cols:
        code_set_gate.reject_unsafe_code_set_chunk_schema(
            source_chunk.schema, state.code_set_cols, table=table
        )
    if state.bucket_perturb_cols:
        bucket_perturb_gate.reject_unsafe_bucket_perturb_chunk_schema(
            source_chunk.schema, state.bucket_perturb_cols, table=table
        )
    # Per-chunk DGRN domain guard (no whole-stream row count); see `_chunked_dgrn.py`.
    dgrn.validate_chunk_row_offset_range(row_offset, source_chunk.num_rows)
    try:
        result = state.adapter.run(
            step.plan,
            {table: adapter_chunk if carry is None else carry.adapter_input(adapter_chunk)},
            registry=state.registry,
            pool_cache=state.pool_cache,
            relationship_graph=state.graph,
            namespace_registry=state.ns_registry,
            unconfigured_column_policy=state.projection_policy,
            key_provider=state.key_provider,
            row_offset=row_offset,
            code_set_records=state.code_set_records,
        )
    except Exception as exc:
        if carry is not None:
            carry.diagnose_adapter(
                exc,
                adapter_chunk,
                table=table,
                chunk_index=chunk_index,
                fk_safe=lambda: adapter_fk_safe_columns(
                    step.plan, state.registry, state.graph, table
                ),
            )
        raise
    if carry is not None and carry.carried and result.row_errors:
        # The failing chunk is reported with the real carried columns, never the
        # placeholders the adapter saw.
        result = dataclasses.replace(
            result,
            outputs={**result.outputs, table: carry.reattach(result.outputs[table], adapter_chunk)},
        )
    if step.chunk_result_sink is not None and (step.on_chunk is None or result.row_errors):
        step.chunk_result_sink.append(result)
    # The chunked path has no quarantine machinery, so a per-row strategy
    # error (bucketize/date_shift format_error, code_set mask_error)
    # cannot be routed anywhere. Discarding it would silently keep the raw
    # source value in the streamed output, the leak the full-frame path
    # closes. Fail closed the moment any chunk reports a row error; this
    # applies to every caller, including a routed job in run_pipeline.
    if result.row_errors:
        raise RowErrorsFailedError(
            result.row_errors,
            summary=chunk_row_error_summary(
                result.row_errors,
                table=table,
                columns=adapter_chunk.schema.names,
                chunk_index=chunk_index,
                chunk_row_offset=row_offset,
            ),
        )
    if step.on_chunk is None:
        return result.outputs[table]
    return step.on_chunk(result, source_chunk)
