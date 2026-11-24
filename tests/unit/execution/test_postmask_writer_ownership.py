"""PM-1a: the post-scan's writer query is asked once per run, over the run's own graph and
registry, and every gate call receives that one answer.

`build_run_context` asks it on the final routing facts. A second ask (at gate binding, or per
route) or an ask over other edges or another registry fails here. The standalone post-scan, which
has no compiled graph, must reach the same inputs from the config alone.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.config import PipelineConfig
from decoy_engine.execution import _pipeline_context as ctx_module
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._strategies._passthrough import PassthroughHandler
from decoy_engine.execution.pipeline import _post_scan as post_scan_module
from decoy_engine.execution.pipeline import _routing_facts as facts_module
from decoy_engine.generation.composite import CompositeAdapter, composite_capability
from decoy_engine.plan.column_access import (
    PASSTHROUGH_OUTPUT_IS_INPUT,
    KnownEmpty,
    KnownSet,
    Unknown,
    config_child_keys,
    may_write,
    written_columns_by_table,
)
from decoy_engine.providers_v2 import get_default_registry
from tests._declared_schema import declare_rest

_V = "pm1a-ownership"
N = 6


def _custom_composite_registry() -> Any:
    base = get_default_registry()
    caps = composite_capability("composite_custom").model_copy(update={"provider": "composite_x"})
    return base.override("composite_x", CompositeAdapter("composite_custom"), caps)


def _relationships(shape: str) -> list[dict[str, Any]]:
    one = {"table": "c1", "columns": ["pa", "pb"]}
    two = {"table": "c2", "columns": ["qa", "qb"]}
    parent = {"table": "p", "columns": ["a", "b"]}
    children = {"none": None, "one child": [one], "multi child": [one, two]}
    if children[shape] is None:
        return []
    rel = {"parent": parent, "children": children[shape], "orphan_policy": "preserve"}
    return [{**rel, "namespace": "ns"}]


def _config(tmp_path: Path, shape: str) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    keys = [f"k{i}" for i in range(N)]
    tables = {
        "p": pa.table({"a": keys, "b": keys, "note": keys}),
        "c1": pa.table({"pa": keys, "pb": keys, "note": keys}),
        "c2": pa.table({"qa": keys, "qb": keys, "note": keys}),
    }
    raw: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 7},
        "post_scan": {"integrity": True},
        "sources": {},
        "targets": {},
        "tables": [],
        "relationships": _relationships(shape),
    }
    for name, table in tables.items():
        path = tmp_path / f"{name}.parquet"
        pq.write_table(table, path)
        raw["sources"][name] = {"type": "file", "path": str(path), "format": "parquet"}
        out = str(tmp_path / f"{name}.out.parquet")
        raw["targets"][name] = {"type": "file", "path": out, "format": "parquet"}
        raw["tables"].append({"name": name, "columns": [{"name": "note", "strategy": "redact"}]})
    return PipelineConfig.model_validate(declare_rest(raw)).model_dump(), tables


class _Observed:
    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []
        self.results: list[Any] = []
        self.contexts: list[Any] = []
        self.gate_writes: list[Any] = []


def _observe(monkeypatch: pytest.MonkeyPatch) -> _Observed:
    seen = _Observed()

    def query(config, **kwargs):
        seen.queries.append(kwargs)
        seen.results.append(written_columns_by_table(config, **kwargs))
        return seen.results[-1]

    real_build = ctx_module.build_run_context

    def build(*args, **kwargs):
        seen.contexts.append(real_build(*args, **kwargs))
        return seen.contexts[-1]

    def gate_call(real):
        def call(*args, **kwargs):
            seen.gate_writes.append(kwargs.get("writes"))
            return real(*args, **kwargs)

        return call

    monkeypatch.setattr(facts_module, "written_columns_by_table", query, raising=False)
    monkeypatch.setattr(ctx_module, "build_run_context", build)
    for name in ("run_post_mask", "run_post_mask_tables"):
        monkeypatch.setattr(post_scan_module, name, gate_call(getattr(post_scan_module, name)))
    return seen


def _edge_tuples(edges) -> list[tuple]:
    return [(e.parent_table, e.parent_columns, e.child_table, e.child_columns) for e in edges]


_ROUTES = {
    "full frame": {"auto_chunk": False},
    "resident chunked": {"auto_chunk_threshold_rows": 1, "chunk_size_rows": 2},
}


@pytest.mark.parametrize("route", list(_ROUTES))
def test_one_query_per_run_and_every_gate_call_gets_its_answer(tmp_path, monkeypatch, route):
    config, sources = _config(tmp_path, "multi child")
    seen = _observe(monkeypatch)
    run_pipeline(config, sources=sources, engine_version=_V, **_ROUTES[route])
    assert len(seen.contexts) == 1
    assert len(seen.queries) == 1, "the writer query must be asked exactly once per run"
    ctx = seen.contexts[0]
    assert ctx.writes is seen.results[0]
    assert seen.gate_writes, "the post-scan gate did not run"
    assert all(writes is ctx.writes for writes in seen.gate_writes)


# A relationship with no children fails config validation, so the parent-only end is the
# table `p`, which every shape with an edge checks below.
@pytest.mark.parametrize("shape", ["none", "one child", "multi child"])
@pytest.mark.parametrize("custom", [False, True], ids=["default registry", "custom composite"])
def test_the_query_reads_the_edges_and_registry_the_run_executes(
    tmp_path, monkeypatch, shape, custom
):
    config, sources = _config(tmp_path, shape)
    registry = _custom_composite_registry() if custom else None
    seen = _observe(monkeypatch)
    run_pipeline(config, sources=sources, engine_version=_V, registry=registry, auto_chunk=False)
    assert len(seen.queries) == len(seen.contexts) == 1
    (query,), (ctx,) = seen.queries, seen.contexts
    assert query["registry"] is ctx.registry
    assert ctx.registry is (registry if custom else get_default_registry())
    assert _edge_tuples(query["edges"]) == _edge_tuples(ctx.graph.edges)
    # The standalone post-scan reaches the same child keys from the config alone.
    standalone = config_child_keys(config)
    assert standalone is not None
    assert _edge_tuples(standalone) == _edge_tuples(ctx.graph.edges)
    expected = {"none": 0, "one child": 1, "multi child": 2}[shape]
    assert len(ctx.graph.edges) == expected
    for edge in ctx.graph.edges:
        assert ctx.writes[edge.child_table] == KnownSet(frozenset({"note", *edge.child_columns}))
    assert ctx.writes["p"] == KnownSet(frozenset({"note"}))


def test_a_composite_provider_wins_over_passthrough_with_the_callers_registry():
    entry = {
        "name": "a",
        "strategy": "passthrough",
        "provider": "composite_x",
        "coherent_with": ["b"],
        "provider_config": {"bundle": {"a": "first_name", "b": "last_name"}},
    }
    config = {"version": 2, "tables": [{"name": "t", "columns": [entry]}]}
    args = {"schemas": {"t": ["a", "b"]}, "edges": ()}
    custom = written_columns_by_table(config, registry=_custom_composite_registry(), **args)
    # The rebound name has no declaration of its own, so the table fails closed to Unknown.
    assert custom.get("t") == Unknown()
    assert may_write(custom, "t", "a")
    # A known composite's own column is written although its strategy reads passthrough.
    fixed = {**entry, "provider": "composite_name_email", "provider_config": {}}
    fixed_config = {"version": 2, "tables": [{"name": "t", "columns": [fixed]}]}
    known = written_columns_by_table(fixed_config, registry=get_default_registry(), **args)
    assert isinstance(known["t"], KnownSet) and {"a", "b"} <= known["t"].columns
    plain = {**entry, "provider": None}
    plain_config = {"version": 2, "tables": [{"name": "t", "columns": [plain]}]}
    default = written_columns_by_table(plain_config, registry=get_default_registry(), **args)
    assert default["t"] == KnownEmpty()


def test_the_passthrough_handler_matches_the_plan_declaration():
    assert PassthroughHandler.output_is_input is PASSTHROUGH_OUTPUT_IS_INPUT is True


_QUERY = """
import decoy_engine.{first}
from decoy_engine.plan.column_access import KnownSet, Unknown
from decoy_engine.verification.postmask._column_facts import standalone_writes

config = {{"tables": [{{"name": "t", "columns": [{{"name": "a", "strategy": "redact"}}]}}]}}
assert standalone_writes(config, {{"t": ["a", "b"]}}) == {{"t": KnownSet(frozenset({{"a"}}))}}
bad = {{"tables": [{{"name": "t", "columns": [{{"name": "a", "strategy": "nope"}}]}}]}}
assert standalone_writes(bad, {{"t": ["a"]}}) == {{"t": Unknown()}}
"""


@pytest.mark.parametrize("first", ["execution", "verification.postmask", "plan.column_access"])
def test_the_query_resolves_whichever_package_is_imported_first(first):
    code = _QUERY.format(first=first)
    run = [sys.executable, "-c", code]
    done = subprocess.run(run, capture_output=True, text=True, check=False)  # noqa: S603
    assert done.returncode == 0, done.stderr[-2000:]
