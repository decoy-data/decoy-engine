"""Builders for the write-and-ordering acceptance tests: seed plans run through `run_single`
with explicit namespace bindings, one-row customer references for `joint_mask`, and a
fixed-seed composite oracle."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.plan import ColumnSeed, GroupSeed, SeedEnvelope, TableSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import (
    OrphanPolicy,
    RelationshipEdge,
    RelationshipGraph,
)
from decoy_engine.relationships._namespace import NamespaceBinding, NamespaceRegistry

REG = get_default_registry()
NO_GRAPH = RelationshipGraph(edges=(), ordering=())
SEED = b"\xca\xfe" * 16


def plan(
    per_column: list[tuple[str, ColumnSeed]],
    table: str = "t",
    groups: tuple[tuple[str, GroupSeed], ...] = (),
) -> Any:
    seeds = TableSeed(per_column=tuple(per_column), per_group=groups)
    return SimpleNamespace(seed_envelope=SeedEnvelope(job_seed=SEED, per_table=((table, seeds),)))


def seed(strategy: str, **kw: Any) -> ColumnSeed:
    base: dict[str, Any] = {
        "namespace": None,
        "strategy": strategy,
        "provider": None,
        "backend_type": "decoy_native",
        "backend_version": "1",
        "cardinality_mode": "preserve",
        "deterministic": False,
    }
    return ColumnSeed(**{**base, **kw})


def derived(expression: str, when: str | None = None) -> ColumnSeed:
    return seed("derived", provider_config=(("expression", expression),), when=when)


def bundle(coherent_with: tuple[str, ...] = ()) -> ColumnSeed:
    return seed(
        "faker",
        provider="composite_name_email",
        namespace="nm",
        deterministic=True,
        backend_type="composite",
        cardinality_mode="reuse",
        coherent_with=coherent_with,
    )


def reference(path: Path, **columns: list[Any]) -> str:
    """A customer reference table at `path` with the required stable `id`; returns the
    `reference:` value."""
    rows = len(next(iter(columns.values())))
    pq.write_table(pa.table({"id": list(range(rows)), **columns}), str(path))
    return f"customer:{path}"


def joint(ref: str, columns: list[str], key_by: str = "k", when: str | None = None) -> ColumnSeed:
    cfg = (("columns", columns), ("reference", ref), ("key_by", key_by))
    return seed("joint_mask", provider_config=cfg, when=when)


def fk_graph(parent: str, child: str, policy: OrphanPolicy = OrphanPolicy.PRESERVE) -> Any:
    edge = RelationshipEdge("t", (parent,), "t", (child,), "nm", policy)
    return RelationshipGraph(edges=(edge,), ordering=())


def run(
    seed_plan: Any,
    table: pa.Table,
    graph: Any = NO_GRAPH,
    bound: tuple[tuple[str, ...], ...] = (("first_name",),),
) -> pa.Table:
    """`run_single` with `nm` bound to each column tuple in `bound` of table `t`."""
    bindings = (NamespaceBinding("nm", tuple(("t", cols) for cols in bound)),)
    return (
        PandasExecutionAdapter()
        .run_single(
            seed_plan,
            table,
            registry=REG,
            relationship_graph=graph,
            namespace_registry=NamespaceRegistry(bindings=bindings),
        )
        .output
    )


def bundle_oracle(first_names: list[str]) -> dict[str, list[Any]]:
    """The composite's outputs for these source first names, run alone at the fixed seed."""
    n = len(first_names)
    table = pa.table(
        {
            "first_name": pa.array(first_names),
            "last_name": pa.array([f"src-last{i}" for i in range(n)]),
            "email": pa.array([f"src{i}@x.test" for i in range(n)]),
        }
    )
    out = run(plan([("first_name", bundle())]), table)
    return {c: out.column(c).to_pylist() for c in ("first_name", "last_name", "email")}


def run_sequential(
    seed_plan: Any,
    table: pa.Table,
    graph: Any = NO_GRAPH,
    bound: tuple[tuple[str, ...], ...] = (("first_name",),),
) -> pa.Table:
    """`run_sequential` over one table `t`, collected through a callable sink."""
    bindings = (NamespaceBinding("nm", tuple(("t", cols) for cols in bound)),)
    emitted: dict[str, pa.Table] = {}
    PandasExecutionAdapter().run_sequential(
        seed_plan,
        lambda name: table,
        config={},
        registry=REG,
        relationship_graph=graph,
        namespace_registry=NamespaceRegistry(bindings=bindings),
        sink=lambda name, out: emitted.__setitem__(name, out),
    )
    return emitted["t"]


def classify(seed_plan: Any, table: pa.Table, graph: Any = NO_GRAPH) -> Any:
    """`classify_job` over table `t` on the pandas substrate."""
    from decoy_engine.execution._planner import classify_job

    config = {"tables": [{"name": "t", "columns": [{"name": c} for c in table.column_names]}]}
    return classify_job(
        config,
        plan=seed_plan,
        registry=REG,
        relationship_graph=graph,
        substrate="pandas",
        source_tables={"t": table},
    )
