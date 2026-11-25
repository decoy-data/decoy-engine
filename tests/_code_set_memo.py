"""Shared setup and the pre-memo oracle for the code_set memo tests and benchmark.

``base_run`` is a copy of the handler loop as it was before the memo (one scalar call per
row); the memo tests compare the handler to it, and the perf test times against it.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._strategies import _code_set as csm
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

SEED = (0x77).to_bytes(8, "big")

AB_CODES = ["A01", "A02", "B01", "B02"]
AB_CHAPTERS = ["A", "A", "B", "B"]


def customer_corpus(
    tmp_path: pathlib.Path,
    codes: list[str] | None = None,
    chapters: list[str] | None = None,
    *,
    filename: str = "c.parquet",
) -> str:
    """Write a customer corpus Parquet (`code`, `chapter`) and return its `customer:` source."""
    path = tmp_path / filename
    pq.write_table(
        pa.table(
            {
                "code": pa.array(AB_CODES if codes is None else codes, type=pa.string()),
                "chapter": pa.array(
                    AB_CHAPTERS if chapters is None else chapters, type=pa.string()
                ),
            }
        ),
        str(path),
    )
    return f"customer:{path}"


def make_ctx() -> StrategyContext:
    return StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=SEED,
    )


def make_seed(cfg: dict[str, Any], namespace: str | None = "cs") -> ColumnSeed:
    return ColumnSeed(
        namespace=namespace,
        strategy="code_set",
        provider="code_set",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(cfg.items()),
        coherent_with=(),
    )


def base_run(df: pd.DataFrame, column: str, plan: ColumnSeed, ctx: StrategyContext) -> Any:
    """The handler loop as it was before the memo (one scalar call per row)."""
    cfg = csm.provider_config_to_dict(plan.provider_config)
    mode = str(cfg.get("mode", "mask"))
    code_cfg = csm.CodeSetConfig.from_dict(cfg)
    if mode == "gen" and plan.namespace is None:
        raise csm.StrategyError(
            code=csm.reasons.runtime.CODE_SET_GEN_REQUIRES_NAMESPACE,
            strategy="code_set",
            message=(
                f"column {column!r} uses code_set gen mode but has no namespace. "
                "Set namespace on the ColumnSeed so gen-mode columns are "
                "decorrelated across namespaces via derive_index."
            ),
        )
    record_key = (ctx.current_table, ctx.nested_outer_column or column)
    record = ctx.code_set_records.get(record_key)
    if record is None:
        record = csm.resolve_corpus_record(code_cfg)
        ctx.code_set_records[record_key] = record
    evidence = csm.describe_loaded_corpus(code_cfg, record=record)
    source = df[column]
    na_mask = source.isna().to_numpy()
    out: list[object] = []
    masked_any = False
    for i, value in enumerate(source):
        if na_mask[i]:
            out.append(None)
            continue
        try:
            result = csm.apply_code_set(
                str(value),
                code_cfg,
                mode=mode,
                job_seed=ctx.mask_key,
                row_index=i,
                namespace=plan.namespace,
                corpus_record=record,
            )
        except csm.PlanCompileError as exc:
            if exc.code not in csm._PER_VALUE_CODE_SET_ERRORS:
                raise
            ctx.row_errors.append(
                csm.RowError(
                    column=column,
                    row_index=i,
                    trigger="mask_error",
                    reason=f"code_set could not mask this value ({exc.code})",
                )
            )
            out.append(value)
            continue
        out.append(result)
        masked_any = True
    if masked_any:
        ec = ctx.nested_outer_column or column
        ctx.code_set_corpora[(ctx.current_table, ec)] = {
            **evidence,
            "table": ctx.current_table,
            "column": ec,
        }
    if out:
        df[column] = out
    else:
        df[column] = pd.array([], dtype="string")
    return df, []
