"""The caller `LazySource` inputs a run reads whole before routing (`resident_fallback`).

`run_pipeline(resident_fallback=True)` turns this pre-pass on for a plain `auto` run.
`build_run_context` calls it after every config-only check and key admission, on the run's own
post-subset routing facts, so a bad config fails before any whole read. Every rule is an existing owner
answering, never a copy: the bounded profiler, the exact plan compiler, the relationship graph,
the router's own `bounded_admission` (sequential eligibility, cycle test, out-of-core admission
and its dtype hazard check), the declared-casting contract and `post_scan_gate_applies`. The
pre-pass is a step inside the run: it is not exported and not an entry point.

Why a relationship job needs the whole bounded-eligible answer: a lazy table gives the size
estimator no sample, so a relationship job with no bounded route would be rejected before read
where the resident run fits and runs full frame.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.execution._pipeline_sources import materialize_source
from decoy_engine.execution.pipeline._resident_fit import check_pre_read
from decoy_engine.execution.pipeline._routing_facts import RoutingFacts, build_routing_facts
from decoy_engine.profile._readers import LazySource

if TYPE_CHECKING:
    from decoy_engine.execution.pipeline._subset_stage import SubsetStageScope
    from decoy_engine.providers_v2 import ProviderRegistry


def read_resident_fallback(
    config: dict[str, Any],
    facts: RoutingFacts,
    *,
    rebuild: Callable[[Mapping[str, pa.Table | LazySource], SubsetStageScope | None], RoutingFacts]
    | None,
    **run_values: Any,
) -> RoutingFacts:
    """`facts` with each lazy table the run cannot keep lazy read whole.

    `facts.caller_sources` is the map the run executes, after any subset selection, so a whole
    read covers only the rows the run keeps. A subset run keeps its facts and swaps the tables in,
    because the selection already staged them. Without a subset, `rebuild` makes the facts again
    over the resident tables, as a run handed those tables would.
    """
    sources = facts.caller_sources
    rejected = resident_fallback_tables(config, sources, facts=facts, **run_values)
    if not rejected:
        return facts
    # Before the whole read: a footer lower bound beyond the kill ceiling refuses with nothing read.
    check_pre_read(config, sources, rejected, graph=facts.graph)
    resident = {n: materialize_source(v) if n in rejected else v for n, v in sources.items()}
    if rebuild is None:
        return replace(facts, caller_sources=resident)
    return rebuild(resident, None)


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
    registry: ProviderRegistry | None = None,
    source_loader_schemas: Mapping[str, Any] | None = None,
    facts: RoutingFacts | None = None,
) -> frozenset[str]:
    """The caller `LazySource` names the run cannot keep lazy; a subset of the lazy `sources`.

    Reads no data row beyond the bounded profile. The arguments are the run's own values and the
    routing facts come from the one function the run context calls, over every caller source, so
    the job profiled and compiled here is the job the run executes.
    """
    from decoy_engine.config import classify_table_kinds, post_scan_gate_applies
    from decoy_engine.execution._transforms_gate import transform_bearing_mask_tables
    from decoy_engine.plan._checks_declared_casting import compile_declared_casting_contract

    candidates = {name: src for name, src in sources.items() if isinstance(src, LazySource)}
    if not candidates:
        return frozenset()
    if vault_writer is not None:
        # A vault run reads every lazy candidate whole: a lazy table gives routing no fit
        # estimate, so the fallback charges input bytes only. The full-frame executor may still
        # choose auto-chunk afterwards.
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
        from decoy_engine.providers_v2 import get_default_registry

        resolved_registry = registry if registry is not None else get_default_registry()
        facts = facts or build_routing_facts(
            config,
            sources,
            registry=resolved_registry,
            source_loader_schemas=source_loader_schemas,
            engine_version=engine_version,
            base_dir=base_dir,
            instance_default_locale=instance_default_locale,
        )
        eligible = _relationship_job_is_bounded(
            config,
            facts,
            sources,
            registry=resolved_registry,
            fidelity_report=fidelity_report,
            post_validation=post_validation,
            table_kinds=kinds,
        )
        if not eligible:
            return frozenset(candidates)
    return frozenset(candidates) - keep


def _relationship_job_is_bounded(
    config: dict[str, Any],
    facts: RoutingFacts,
    sources: Mapping[str, pa.Table | LazySource],
    *,
    registry: ProviderRegistry,
    fidelity_report: bool,
    post_validation: bool,
    table_kinds: dict[str, str],
) -> bool:
    """Whether routing would take a bounded route for this job, from the router's own answer."""
    from decoy_engine.execution import _pipeline_routing as routing

    if not facts.profile.relationships:
        return True
    return routing.bounded_admission(
        facts.profile,
        plan=facts.plan,
        registry=registry,
        graph=facts.graph,
        caller_sources=dict(sources),
        config=config,
        table_kinds=table_kinds,
        has_generate_table="generate" in table_kinds.values(),
        has_mask_table=True,
        validators=config.get("validators") or [],
        fidelity_report=fidelity_report,
        post_validation=post_validation,
        vault_writer=None,
    ).admitted
