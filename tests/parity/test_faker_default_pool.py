"""FAKER-DEFAULT-POOL: a faker column with no `pool_size` runs as if it declared 10,000.

Plan: docs/plans/2026-11-22-faker-default-pool.md. The oracle already builds the default pool
(`effective_pool_size`); the native, chunked, sequential and out-of-core routes used to refuse the
column instead. Every cell here compares the omitted-size column with the same column declaring
`pool_size: 10000`, or with the forced full-frame run, so a route that disagrees fails.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution import run_pipeline
from decoy_engine.execution._chunked import _conditional_admission_failures
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._sequential_native_ops import faker_op
from decoy_engine.execution.native._faker_positional_admission import positional_faker_failures
from decoy_engine.execution.native._provider_class import classify_provider
from decoy_engine.execution.native._requirements import (
    faker_pool_precondition_met,
    faker_pool_precondition_met_seed,
)
from decoy_engine.execution.out_of_core import _hash_run
from decoy_engine.execution.out_of_core._compat import _faker_conditional_rejection
from decoy_engine.execution.out_of_core._faker_native import decline_reason
from decoy_engine.execution.out_of_core._faker_pool import OocFakerPoolContext
from decoy_engine.execution.out_of_core._hash_run import OocHashRun, fk_child_skip_columns
from decoy_engine.generation.pool._runtime_pool_size import DEFAULT_POOL_SIZE
from decoy_engine.providers_v2 import get_default_registry
from tests.native._chunked_entry_support import NEEDS_COMPANION
from tests.parity._faker_seq_data import faker_seed, positional_seed

ENGINE_VERSION = "faker-default-pool"
FIRST = "person_first_name"
LAST = "person_last_name"
DEFAULT = DEFAULT_POOL_SIZE


def _column(
    provider: str = FIRST,
    *,
    name: str = "f",
    deterministic: bool | None = None,
    namespace: str | None = None,
    pool_size: int | None = None,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    col: dict[str, Any] = {"name": name, "strategy": "faker", "provider": provider}
    if deterministic is not None:
        col["deterministic"] = deterministic
    if namespace is not None:
        col["namespace"] = namespace
    if pool_size is not None:
        col["pool_size"] = pool_size
    if provider_config is not None:
        col["provider_config"] = provider_config
    return col


# The three shapes of the plan's F1: default first name, default last name, and the
# deterministic form with a namespace.
_SHAPES: dict[str, dict[str, Any]] = {
    "first": {"provider": FIRST},
    "last": {"provider": LAST},
    "deterministic": {"provider": FIRST, "deterministic": True, "namespace": "ns_fdp"},
}


def _source(rows: int, *, nulls: bool = True) -> pa.Table:
    values = [None if nulls and i % 11 == 0 else f"src{i % 977}" for i in range(rows)]
    return pa.table({"f": pa.array(values, pa.string()), "p": pa.array(range(rows), pa.int64())})


def _job(
    tmp_path: Path, columns: list[dict[str, Any]], table: pa.Table
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    from tests.unit.execution import _multi_table_support as mt

    tmp_path.mkdir(parents=True, exist_ok=True)
    keep = {"name": "p", "strategy": "passthrough"}
    return mt.build_job(tmp_path, {"t": ([*columns, keep], table)})


def _run(cfg: dict[str, Any], src: dict[str, pa.Table], **kw: Any) -> Any:
    return run_pipeline(cfg, sources=src, engine_version=ENGINE_VERSION, **kw)


def _forced_full_frame(cfg: dict[str, Any], src: dict[str, pa.Table]) -> Any:
    return _run(cfg, src, auto_chunk=False, unified_slice_enabled=False)


def _hash(table: pa.Table) -> str:
    # Schema metadata differs by route (pandas metadata) and is not part of the values.
    table = table.replace_schema_metadata(None)
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _backend(result: Any, column: str = "f") -> str:
    """The backend that executed `column`, from whichever route evidence the run carries."""
    metrics = result.quality_metrics
    route = metrics.get("chunked_route")
    if route is not None:
        return {c["column"]: c for c in route["columns"]}[column]["executed_backend"]
    leaf = metrics.get("unified_slice_activation")
    if leaf is not None:
        [node] = [n for n in leaf["nodes"].values() if column in n["columns"]]
        return node["executed_backend"]
    return "pandas_oracle"


def _assert_native(result: Any, rows: int) -> None:
    metrics = result.quality_metrics
    if rows >= 100_000:
        assert metrics["auto_chunk"]["mode"] == "chunked"
    else:
        assert "chunked_route" not in metrics  # the unified slice, not the chunked route
    assert _backend(result) in {"rust_pool_select", "rust_companion"}


# ---------------------------------------------------------------------------
# F1. Output equality, and the route the omitted size now takes.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_f1_the_omitted_size_equals_the_declared_default_and_the_full_frame_run(
    tmp_path: Path, shape: str, rows: int
) -> None:
    table = _source(rows)
    cfg_omitted, src = _job(tmp_path / "o", [_column(**_SHAPES[shape])], table)
    cfg_declared, _ = _job(tmp_path / "d", [_column(pool_size=DEFAULT, **_SHAPES[shape])], table)
    omitted = _run(cfg_omitted, src)
    declared = _run(cfg_declared, src)
    reference = _forced_full_frame(cfg_omitted, src)
    out = omitted.outputs["t"]
    assert out.equals(declared.outputs["t"])  # values and schema
    assert out.equals(reference.outputs["t"])
    assert _hash(out) == _hash(declared.outputs["t"]) == _hash(reference.outputs["t"])
    _assert_native(omitted, rows)
    assert _backend(reference) == "pandas_oracle"


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
def test_f1_a_declared_provider_config_size_still_wins(tmp_path: Path, rows: int) -> None:
    table = _source(rows)
    shape = {**_SHAPES["deterministic"], "provider_config": {"pool_size": 500}}
    cfg, src = _job(tmp_path, [_column(**shape)], table)
    got = _run(cfg, src)
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])
    _assert_native(got, rows)
    distinct = len(set(got.outputs["t"].column("f").to_pylist()) - {None})
    assert distinct <= 500 < len(set(table.column("f").to_pylist()) - {None})


# ---------------------------------------------------------------------------
# F2. Every admission entry point decides the same with and without the size.
# ---------------------------------------------------------------------------


def _both(make: Callable[[int | None], Any]) -> tuple[Any, Any]:
    return make(None), make(DEFAULT)


_SEED_SHAPES: dict[str, Callable[[int | None], Any]] = {
    "deterministic": lambda size: faker_seed(pool_size=size),
    "positional": lambda size: positional_seed(pool_size=size),
    "positional_no_namespace": lambda size: positional_seed(None, pool_size=size),
    "deterministic_no_namespace": lambda size: faker_seed(None, pool_size=size),
    "unique": lambda size: faker_seed(mode="unique", pool_size=size),
    "outside_allowlist": lambda size: faker_seed(provider="person_email", pool_size=size),
}


def _work_node(seed: Any) -> Any:
    return SimpleNamespace(provider=seed.provider, plan_slice=seed, table="t", columns=("c",))


@pytest.mark.parametrize("shape", sorted(_SEED_SHAPES))
def test_f2_the_seed_level_admission_points_ignore_the_pool_size(shape: str) -> None:
    omitted, declared = _both(_SEED_SHAPES[shape])
    assert faker_pool_precondition_met_seed(omitted) is faker_pool_precondition_met_seed(declared)
    assert faker_pool_precondition_met(SimpleNamespace(plan_slice=omitted)) is (
        faker_pool_precondition_met(SimpleNamespace(plan_slice=declared))
    )
    schema = pa.schema([pa.field("c", pa.string())])
    assert decline_reason("c", schema, omitted) == decline_reason("c", schema, declared)
    admit = faker_op(lambda _t: None).admit
    assert admit("c", pa.string(), omitted) == admit("c", pa.string(), declared)
    assert _faker_conditional_rejection(_work_node(omitted), None) == (
        _faker_conditional_rejection(_work_node(declared), None)
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"deterministic": False},
        {"deterministic": False, "namespace": "ns"},
        {"deterministic": True, "namespace": "ns"},
        {"deterministic": True},
        {"deterministic": True, "namespace": "ns", "cardinality_mode": "unique"},
        {"deterministic": False, "provider": "person_email"},
    ],
    ids=["nondet", "nondet_ns", "det_ns", "det_no_ns", "unique", "nondet_outside_allowlist"],
)
def test_f2_the_config_level_admission_points_ignore_the_pool_size(entry: dict[str, Any]) -> None:
    base = {"name": "c", "strategy": "faker", "provider": FIRST, **entry}
    variants = [
        base,
        {**base, "pool_size": DEFAULT},
        {**base, "provider_config": {"pool_size": DEFAULT}},
        {**base, "pool_size": None, "provider_config": {"pool_size": None}},
    ]
    assert len({str(_conditional_admission_failures(v)) for v in variants}) == 1
    assert len({str(positional_faker_failures(v)) for v in variants}) == 1


@NEEDS_COMPANION
@pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
def test_f2_the_unified_binding_ignores_the_pool_size(tmp_path: Path, deterministic: bool) -> None:
    from decoy_engine.execution._runner import build_work_list
    from decoy_engine.execution.physical import _shadow_bindings
    from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs

    results = []
    for name, size in (("o", None), ("d", DEFAULT)):
        shape = {"deterministic": deterministic, "namespace": "ns_fdp", "pool_size": size}
        cfg, src = _job(tmp_path / name, [_column(**shape)], _source(40))
        inputs = capture_physical_plan_inputs(cfg, src, engine_version=ENGINE_VERSION)
        [node] = [n for n in build_work_list(inputs.plan, inputs.registry) if n.columns == ("f",)]
        kwargs = {"plan_slice": node.plan_slice, "table": "t", "column": "f", "inputs": inputs}
        results.append(
            (
                _shadow_bindings._faker_pool_bindable(**kwargs),
                _shadow_bindings.positional_faker_bindable(**kwargs),
            )
        )
    assert results[0] == results[1]


# ---------------------------------------------------------------------------
# F3. Providers outside the allowlist, and the registry walk.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
def test_f3_a_non_allowlisted_deterministic_provider_runs_the_chunked_oracle_leg(
    tmp_path: Path,
) -> None:
    shape = {"provider": "person_email", "deterministic": True, "namespace": "ns_fdp"}
    cfg, src = _job(tmp_path, [_column(**shape)], _source(120_000))
    got = _run(cfg, src)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])


def test_f3_every_pool_native_provider_matches_full_frame_or_fails_before_the_first_chunk(
    tmp_path: Path,
) -> None:
    registry = get_default_registry()
    providers = sorted(
        p for p in registry.known_providers() if classify_provider(p, None) == "pool_native"
    )
    assert providers
    table = _source(60, nulls=False)
    mismatches: list[str] = []
    for index, provider in enumerate(providers):
        shape = {"provider": provider, "deterministic": True, "namespace": "ns_fdp"}
        try:
            cfg, src = _job(tmp_path / f"p{index}", [_column(**shape)], table)
            chunked = _run(cfg, src, auto_chunk_threshold_rows=10, chunk_size_rows=20)
            reference = _forced_full_frame(cfg, src)
        except Exception as exc:  # an existing coded refusal before the first chunk is allowed
            if getattr(exc, "code", None) is None:
                raise
            continue
        if not chunked.outputs["t"].equals(reference.outputs["t"]):
            mismatches.append(provider)
    assert mismatches == []


# ---------------------------------------------------------------------------
# F4. Empty and all-null output columns take the declared-default type.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize(
    "table",
    [
        pa.table({"f": pa.array([None] * 12, pa.string()), "p": pa.array(range(12))}),
        pa.table({"f": pa.array([], pa.string()), "p": pa.array([], pa.int64())}),
    ],
    ids=["all_null", "empty"],
)
def test_f4_the_degenerate_output_type_equals_the_declared_default(
    tmp_path: Path, table: pa.Table
) -> None:
    kw = {"auto_chunk_threshold_rows": 3, "chunk_size_rows": 4}
    shape = _SHAPES["first"]
    cfg_omitted, src = _job(tmp_path / "o", [_column(**shape)], table)
    cfg_declared, _ = _job(tmp_path / "d", [_column(pool_size=DEFAULT, **shape)], table)
    omitted = _run(cfg_omitted, src, **kw)
    declared = _run(cfg_declared, src, **kw)
    assert omitted.outputs["t"].schema.equals(declared.outputs["t"].schema)
    assert omitted.outputs["t"].equals(declared.outputs["t"])
    if table.num_rows:  # an empty table never reaches the chunked threshold
        assert omitted.outputs["t"].schema.field("f").type == pa.string()


# ---------------------------------------------------------------------------
# F5. A custom provider that returns non-strings keeps the explicit-size outcomes.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize("size", [None, DEFAULT], ids=["omitted", "declared"])
def test_f5_a_non_string_custom_provider_fails_the_chunked_route_before_any_chunk(
    size: int | None,
) -> None:
    from tests.native._b8_support import run_one
    from tests.native._chunked_faker_support import (
        make_config,
        nd_faker,
        passthrough,
        source,
        split,
    )
    from tests.native.test_chunked_nondet_faker_admission import _override

    written: list[Any] = []
    with pytest.raises(Exception) as info:
        written.append(
            run_one(
                make_config([nd_faker(pool_size=size), passthrough("p")]),
                split(source(["a", "b", None, "c", "d", "e"]), 2),
                registry=_override(FIRST),
                vault=True,
            )
        )
    assert getattr(info.value, "code", None) == "chunked_faker_nondeterministic_pool_not_string"
    assert written == []


@NEEDS_COMPANION
@pytest.mark.parametrize("size", [None, DEFAULT], ids=["omitted", "declared"])
def test_f5_a_non_string_custom_provider_reroutes_on_the_unified_slice_and_succeeds(
    tmp_path: Path, size: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.physical.test_unified_slice_faker import CountingAdapter, rebound_registry

    column = _column(deterministic=True, namespace="ns_fdp", pool_size=size)
    cfg, src = _job(tmp_path, [column], _source(40, nulls=False))
    with caplog.at_level("INFO", logger="decoy_engine.execution._unified_slice"):
        got = _run(cfg, src, registry=rebound_registry(CountingAdapter(lambda i: i)))
    off = _run(
        cfg,
        src,
        registry=rebound_registry(CountingAdapter(lambda i: i)),
        unified_slice_enabled=False,
    )
    assert any(
        r.getMessage().startswith("unified_slice_faker_non_string_pool_reroute")
        for r in caplog.records
    )
    assert got.outputs["t"].equals(off.outputs["t"], check_metadata=True)


# ---------------------------------------------------------------------------
# F6. Sequential and out-of-core routes.
# ---------------------------------------------------------------------------


def _fk_job(
    tmp_path: Path, faker_columns: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    parent = pa.table(
        {
            "k": [f"k{i}" for i in range(8)],
            **{c["name"]: [f"s{i}" for i in range(8)] for c in faker_columns},
        }
    )
    child = pa.table({"k": ["k1", "k2", "k3", "k9"]})
    for name, table in (("P", parent), ("C", child)):
        pq.write_table(table, tmp_path / f"{name}.parquet")
    config: dict[str, Any] = {
        "version": 2,
        "global_settings": {"job_name": "faker-default-pool", "seed": 7},
        "sources": {
            t: {"type": "file", "path": str(tmp_path / f"{t}.parquet"), "format": "parquet"}
            for t in ("P", "C")
        },
        "targets": {
            t: {"type": "file", "path": str(tmp_path / f"{t}.out.parquet"), "format": "parquet"}
            for t in ("P", "C")
        },
        "tables": [
            {
                "name": "P",
                "columns": [*faker_columns, {"name": "k", "strategy": "hash", "namespace": "ns_k"}],
            },
            {"name": "C", "columns": [{"name": "k", "strategy": "hash", "namespace": "ns_k"}]},
        ],
        "relationships": [
            {
                "parent": {"table": "P", "columns": ["k"]},
                "children": [{"table": "C", "columns": ["k"]}],
                "orphan_policy": "preserve",
                "namespace": "ns_k",
            }
        ],
    }
    return config, {"P": parent, "C": child}


@NEEDS_COMPANION
@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"execution_mode": "sequential"}, "sequential_faker"),
        ({"execution_mode": "out_of_core"}, "out_of_core_faker"),
    ],
    ids=["sequential", "out_of_core"],
)
def test_f6_a_default_faker_in_an_fk_job_runs_native_and_equals_full_frame(
    tmp_path: Path, kw: dict[str, Any], key: str
) -> None:
    columns = [_column(LAST, name="f", deterministic=True, namespace="ns_fdp")]
    cfg, src = _fk_job(tmp_path, columns)
    got = _run(cfg, src, out_of_core_budget_bytes=1 << 30, **kw)
    ref = _run(cfg, src, execution_mode="full_frame")
    [entry] = got.quality_metrics[key]
    assert entry["executed_backend"] in {"rust_companion", "rust_pool_select"}
    for table in ("P", "C"):
        assert got.outputs[table].equals(ref.outputs[table])


# ---------------------------------------------------------------------------
# F6b. Out-of-core pools are decided and reserved once, before any scratch exists.
# ---------------------------------------------------------------------------

_BUDGET = 100 * 1024 * 1024


def _three_pools() -> list[dict[str, Any]]:
    return [
        _column(FIRST, name="f1", deterministic=True, namespace="ns_a"),
        _column(LAST, name="f2", deterministic=True, namespace="ns_a"),
        _column(FIRST, name="f3", deterministic=True, namespace="ns_b"),
    ]


@NEEDS_COMPANION
def test_f6b_an_over_budget_job_fails_before_scratch_with_a_value_free_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution.out_of_core import _runner

    arenas: list[int] = []
    real_fresh = _runner.ScratchArena.fresh

    def spy(*a: Any, **k: Any) -> Any:
        arenas.append(1)
        return real_fresh(*a, **k)

    monkeypatch.setattr(_runner.ScratchArena, "fresh", spy)
    cfg, src = _fk_job(tmp_path, _three_pools())
    with pytest.raises(ExecutionError) as info:
        _run(cfg, src, execution_mode="out_of_core", out_of_core_budget_bytes=_BUDGET)
    assert info.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert arenas == []
    message = str(info.value)
    for fragment in (FIRST, LAST, str(DEFAULT), str(_BUDGET), str(DEFAULT * 4096), "ns_a"):
        assert fragment not in message
    assert not list(tmp_path.glob("*.out.parquet"))


@NEEDS_COMPANION
def test_f6b_two_identities_run_and_the_stored_plan_is_the_one_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decided: list[Any] = []
    real_decide = _hash_run.decide_faker_table

    def decide(*a: Any, **k: Any) -> Any:
        plan = real_decide(*a, **k)
        decided.append(plan)
        return plan

    attached: list[Any] = []
    real_prepare = OocHashRun.prepare_table

    def prepare(self: Any, *a: Any, **k: Any) -> Any:
        table_plan = real_prepare(self, *a, **k)
        attached.append(table_plan.faker)
        return table_plan

    monkeypatch.setattr(_hash_run, "decide_faker_table", decide)
    monkeypatch.setattr(OocHashRun, "prepare_table", prepare)
    cfg, src = _fk_job(tmp_path, _three_pools()[:2])
    result = _run(cfg, src, execution_mode="out_of_core", out_of_core_budget_bytes=_BUDGET)
    assert len(result.quality_metrics["out_of_core_faker"]) == 2
    assert len(decided) == 1  # one decision for the one faker table, made before scratch
    executed = [p for p in attached if p is not None]
    assert len(executed) == len(decided)
    assert all(a is b for a, b in zip(executed, decided, strict=True))


def _compiled(tmp_path: Path) -> Any:
    from decoy_engine.contracts.column_shape import NO_SOURCES
    from decoy_engine.plan import compile_plan
    from decoy_engine.profile import profile_source

    cfg, _ = _fk_job(tmp_path, _three_pools())
    return compile_plan(
        cfg, profile_source(cfg, seed=7), decoy_engine_version=ENGINE_VERSION, sources=NO_SOURCES
    )


def _context(plan: Any) -> OocFakerPoolContext:
    return OocFakerPoolContext(
        registry=get_default_registry(),
        job_seed=plan.seed_envelope.job_seed,
        max_pool_bytes=1 << 40,
    )


_FULL_SCHEMA = pa.schema([pa.field(c, pa.string()) for c in ("k", "f1", "f2", "f3")])


@NEEDS_COMPANION
@pytest.mark.parametrize("control", ["fk_child_skipped", "absent_column", "absent_table"])
def test_f6b_a_non_executable_faker_column_reserves_nothing(tmp_path: Path, control: str) -> None:
    plan = _compiled(tmp_path)
    tables: dict[str, tuple[pa.Schema, frozenset[str]]] = {}
    if control == "fk_child_skipped":
        tables = {"P": (_FULL_SCHEMA, frozenset({"f1", "f2", "f3"}))}
    elif control == "absent_column":
        tables = {"P": (pa.schema([pa.field("k", pa.string())]), frozenset())}
    pool = _context(plan)
    OocHashRun(faker_pool=pool).prepare_faker_tables(plan, tables)
    assert pool.reserved_bytes == 0 and pool.pool_count == 0


@NEEDS_COMPANION
def test_f6b_the_executable_table_reserves_one_pool_per_identity(tmp_path: Path) -> None:
    plan = _compiled(tmp_path)
    pool = _context(plan)
    OocHashRun(faker_pool=pool).prepare_faker_tables(plan, {"P": (_FULL_SCHEMA, frozenset())})
    assert pool.pool_count == 3
    assert pool.reserved_bytes == 3 * DEFAULT * 4096


def test_f6b_the_skip_set_is_the_union_of_the_incoming_child_columns() -> None:
    edges = [
        SimpleNamespace(child_columns=("a", "b")),
        SimpleNamespace(child_columns=("b", "c")),
    ]
    assert fk_child_skip_columns(edges) == frozenset({"a", "b", "c"})  # type: ignore[arg-type]
    assert fk_child_skip_columns([]) == frozenset()


# ---------------------------------------------------------------------------
# F7. An explicit null is the same as absent.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize(
    "nulled",
    [{"pool_size": None}, {"provider_config": {"pool_size": None}}],
    ids=["top_level", "provider_config"],
)
@pytest.mark.parametrize("rows", [2_000, 120_000])
def test_f7_an_explicit_null_pool_size_behaves_as_absent_on_every_route(
    tmp_path: Path, nulled: dict[str, Any], rows: int
) -> None:
    table = _source(rows)
    shape = _SHAPES["deterministic"]
    cfg_absent, src = _job(tmp_path / "a", [_column(**shape)], table)
    cfg_null, _ = _job(tmp_path / "n", [{**_column(**shape), **nulled}], table)
    absent = _run(cfg_absent, src)
    null = _run(cfg_null, src)
    assert null.outputs["t"].equals(absent.outputs["t"])
    _assert_native(null, rows)
