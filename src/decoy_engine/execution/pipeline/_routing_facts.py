"""The routing facts of one run: declaration, bounded profile, plan and relationship graph.

`build_run_context` and the resident-fallback pre-pass both call `build_routing_facts` with the
complete caller source map and the registry the run resolves, so the pre-pass routes the job the
run executes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from decoy_engine.config import classify_table_kinds
from decoy_engine.execution import _guards
from decoy_engine.plan._seed import _normalize_job_seed_int
from decoy_engine.profile import DeclarationRequest
from decoy_engine.relationships import (
    RelationshipGraph,
    build_namespace_registry,
    build_relationship_graph,
    check_orphan_fk_policy_completeness,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pyarrow as pa

    from decoy_engine.execution._guards import PreparedDeclaredSources
    from decoy_engine.execution.pipeline._subset_stage import SubsetStageScope
    from decoy_engine.plan._types import Plan
    from decoy_engine.profile._readers import LazySource
    from decoy_engine.profile._types import Profile
    from decoy_engine.providers_v2 import ProviderRegistry


@dataclass(frozen=True)
class RoutingFacts:
    """What routing reads: the declaration, profile, plan, graph and namespace registry."""

    declared: PreparedDeclaredSources
    profile: Profile
    plan: Plan
    graph: RelationshipGraph
    namespace_registry: Any
    caller_sources: dict[str, pa.Table | LazySource]


def build_routing_facts(
    config: dict[str, Any],
    sources: Mapping[str, pa.Table | LazySource],
    *,
    registry: ProviderRegistry,
    source_loader_schemas: Mapping[str, Any] | None,
    engine_version: str,
    base_dir: str | Path | None,
    instance_default_locale: Any,
    subset_stage: SubsetStageScope | None = None,
) -> RoutingFacts:
    """Declare, refuse, profile, compile and graph one job over its complete source map.

    The profile reads the whole `sources` map as supplied, and a subset run then restricts it,
    so a subset run compiles from the full sources. `caller_sources` is the map after any
    subset selection.
    """
    from decoy_engine.plan import compile_plan
    from decoy_engine.profile import profile_source

    caller_sources = dict(sources)
    table_kinds = classify_table_kinds(config)
    # Every source column must be declared, checked from headers, footers and schemas first.
    schemas = {n: s.schema for n, s in caller_sources.items()}
    request = DeclarationRequest.for_run(config, schemas, source_loader_schemas)
    declared = _guards.prepare_declared_execution_sources(request, registry=registry)
    # Duplicate field names are refused after the config-only admission and before profiling,
    # routing and every pandas conversion: each looks columns up by name and would fail uncoded.
    _guards.refuse_duplicate_run_sources(config, caller_sources)
    _guards.refuse_undeclared_loader_tables(
        table_kinds, config, caller_sources, source_loader_schemas
    )
    supplied = caller_sources
    active_subset = subset_stage if subset_stage is not None and subset_stage.active else None
    selection = None
    if active_subset is not None:
        caller_sources, selection = active_subset.apply(caller_sources, config)
    # The profile-path seed goes through the canonical int normalizer so a bool or float seed
    # is rejected here, before profiling seeds its RNG.
    profile = profile_source(
        config,
        seed=_normalize_job_seed_int(config),
        declared=declared,
        supplied_sources=supplied,
    )
    if active_subset is not None and selection is not None:
        profile = active_subset.restrict_profile(profile, selection, active_subset.head_rows)
    plan = compile_plan(
        config,
        profile,
        decoy_engine_version=engine_version,
        base_dir=base_dir,
        instance_default_locale=instance_default_locale,
    )
    ns_registry = build_namespace_registry(config, profile)
    if profile.relationships:
        graph = build_relationship_graph(
            profile.relationships,
            namespace_registry=ns_registry,
            orphan_policy_lookup=check_orphan_fk_policy_completeness(config, profile.relationships),
        )
    else:
        graph = RelationshipGraph(edges=(), ordering=())
    return RoutingFacts(declared, profile, plan, graph, ns_registry, caller_sources)
