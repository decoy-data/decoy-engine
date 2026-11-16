"""The caller `LazySource` inputs a run reads whole before routing (`resident_fallback`).

`run_pipeline(resident_fallback=True)` calls this pre-pass on a plain `auto` run, after the subset
and token-vault steps and before the run context is built. Every rule is an existing owner
answering, never a copy: the bounded profiler, the exact plan compiler, the relationship graph,
`_sequential_eligible`, the cross-table cycle test, out-of-core admission and its dtype hazard
check, the declared-casting contract and `post_scan_gate_applies`. The pre-pass is a step inside
`run_pipeline`: it is not exported and not an entry point.

Why a relationship job needs the whole bounded-eligible answer: a lazy table gives the size
estimator no sample, so a relationship job with no bounded route would be rejected before read
where the resident run fits and runs full frame.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.execution._pipeline_sources import materialize_source
from decoy_engine.profile._readers import LazySource

if TYPE_CHECKING:
    from decoy_engine.fileaccess import FileAccess


def read_resident_fallback(
    config: dict[str, Any],
    sources: Mapping[str, pa.Table | LazySource] | None,
    **run_values: Any,
) -> Mapping[str, pa.Table | LazySource] | None:
    """`sources` with each lazy table the run cannot keep lazy read whole."""
    if not sources:
        return sources
    rejected = resident_fallback_tables(config, sources, **run_values)
    return {n: materialize_source(v) if n in rejected else v for n, v in sources.items()}


def resident_fallback_tables(
    config: dict[str, Any],
    sources: Mapping[str, pa.Table | LazySource],
    *,
    engine_version: str,
    base_dir: str | Path | None,
    instance_default_locale: Any,
    fidelity_report: bool,
    post_validation: bool,
    vault_writer: Any,
    file_access: FileAccess | None,
) -> frozenset[str]:
    """The caller `LazySource` names the run cannot keep lazy; a subset of the lazy `sources`.

    Reads no data row beyond the bounded profile. The arguments are the run's own values, so the
    plan compiled here is the plan the run compiles.
    """
    from decoy_engine.config import classify_table_kinds, post_scan_gate_applies
    from decoy_engine.execution._transforms_gate import transform_bearing_mask_tables
    from decoy_engine.plan._checks_declared_casting import compile_declared_casting_contract

    candidates = {name: src for name, src in sources.items() if isinstance(src, LazySource)}
    if not candidates:
        return frozenset()
    if vault_writer is not None:
        # The chunked lane refuses a vault, and a lazy table gives routing no fit estimate to
        # lift it onto out-of-core.
        return frozenset(candidates)
    kinds = classify_table_kinds(config)
    keep = {name for name in candidates if kinds.get(name) == "mask"}
    declared = compile_declared_casting_contract(config)
    if declared is not None:
        keep -= {column.table for column in declared.columns}
    if post_scan_gate_applies(config):
        # A lazy transform-bearing table defers the gate to report-only.
        keep -= transform_bearing_mask_tables(config)
    if keep and config.get("relationships"):
        eligible = _relationship_job_is_bounded(
            config,
            candidates,
            engine_version=engine_version,
            base_dir=base_dir,
            instance_default_locale=instance_default_locale,
            fidelity_report=fidelity_report,
            post_validation=post_validation,
            has_generate_table="generate" in kinds.values(),
            file_access=file_access,
        )
        if not eligible:
            return frozenset(candidates)
    return frozenset(candidates) - keep


def _relationship_job_is_bounded(
    config: dict[str, Any],
    candidates: Mapping[str, LazySource],
    *,
    engine_version: str,
    base_dir: str | Path | None,
    instance_default_locale: Any,
    fidelity_report: bool,
    post_validation: bool,
    has_generate_table: bool,
    file_access: FileAccess | None,
) -> bool:
    """Whether routing would take a bounded route for this job, from the engine's own owners."""
    from decoy_engine.execution import _pipeline_routing, _transforms_admission
    from decoy_engine.execution import _pipeline_routing_signals as signals
    from decoy_engine.execution._guards import prepare_declared_execution_sources
    from decoy_engine.execution._pipeline_routing_fk_dtype import fk_out_of_core_dtype_hazard
    from decoy_engine.execution._transforms_gate import post_scan_resident_for
    from decoy_engine.plan import compile_plan
    from decoy_engine.plan._seed import _normalize_job_seed_int
    from decoy_engine.profile import DeclarationRequest, profile_source
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships import (
        build_namespace_registry,
        build_relationship_graph,
        check_orphan_fk_policy_completeness,
    )

    registry = get_default_registry()
    schemas = {name: source.schema for name, source in candidates.items()}
    declared = prepare_declared_execution_sources(
        DeclarationRequest.for_run(config, schemas, None), registry=registry
    )
    profile = profile_source(
        config,
        seed=_normalize_job_seed_int(config),
        declared=declared,
        supplied_sources=candidates,
        file_access=file_access,
    )
    plan = compile_plan(
        config,
        profile,
        decoy_engine_version=engine_version,
        base_dir=base_dir,
        instance_default_locale=instance_default_locale,
    )
    if not profile.relationships:
        return True
    graph = build_relationship_graph(
        profile.relationships,
        namespace_registry=build_namespace_registry(config, profile),
        orphan_policy_lookup=check_orphan_fk_policy_completeness(config, profile.relationships),
    )
    eligible, _reason = _pipeline_routing._sequential_eligible(
        profile,
        has_generate_table=has_generate_table,
        validators=config.get("validators") or [],
        fidelity_report=fidelity_report,
        vault_writer=None,
        post_validation=post_validation,
        post_scan_resident=post_scan_resident_for(config),
    )
    if not eligible or _pipeline_routing._has_cross_table_fk_cycle(graph):
        return False
    compatible, code = signals.out_of_core_admission(
        plan, registry=registry, graph=graph, source_types=signals._source_arrow_types(candidates)
    )
    compatible, _code = _transforms_admission.decline_out_of_core(config, compatible, code)
    return compatible and not fk_out_of_core_dtype_hazard(
        plan, graph, caller_sources=dict(candidates)
    )
