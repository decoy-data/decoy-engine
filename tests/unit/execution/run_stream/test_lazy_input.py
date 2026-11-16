"""RUN-STREAM E5 (AT-E5) and E5a (AT-E5a, AT-E5s): the resident-fallback pre-pass and the no-sink
resident collector.

The pre-pass names the lazy tables a run reads whole and copies no routing rule: every
exclusion below is an existing engine owner answering. The collector lets a lazy source run the
auto-chunk lane with no publication sink, returning one resident output. E5a makes that collector
reachable through `run_pipeline` and gives it a private scratch arena to spill into.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import inspect
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution import _pipeline_auto_chunk as ac
from decoy_engine.execution import _transactional_sink
from decoy_engine.execution._pandas_adapter import PandasExecutionAdapter
from decoy_engine.execution.pipeline import _post_scan
from decoy_engine.execution.pipeline._post_scan import PostScanGate
from decoy_engine.profile._readers import LazySource
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.verification.postmask import PostScanBlockedError
from tests.acceptance._f06_support import ISO_DATE, column, config, validate
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _transform_testkit as tk
from tests.unit.execution.run_stream import _support as rs
from tests.unit.execution.test_lazy_path_route_admission import (
    _ooc_eligible_config,
    _parent_child_tables,
)

V = rs.ENGINE_VERSION


def _lazy(config_dict: Mapping[str, Any]) -> dict[str, LazySource]:
    return {name: LazySource(Path(spec["path"])) for name, spec in config_dict["sources"].items()}


def _names(
    cfg: dict[str, Any],
    candidates: Mapping[str, LazySource],
    base: Path,
    **over: Any,
) -> frozenset[str]:
    """The candidates the pre-pass keeps lazy."""
    from decoy_engine.execution.pipeline._lazy_input import resident_fallback_tables

    args: dict[str, Any] = {
        "engine_version": V,
        "base_dir": base,
        "instance_default_locale": None,
        "fidelity_report": False,
        "post_validation": False,
        "vault_writer": object() if over.pop("vault_active", False) else None,
    }
    args.update(over)
    return frozenset(candidates) - resident_fallback_tables(cfg, candidates, **args)


def _fk(tmp_path: Path) -> tuple[dict[str, Any], dict[str, LazySource]]:
    cfg = _ooc_eligible_config(tmp_path, "parquet")
    return cfg, _lazy(cfg)


def _two_flat_tables(tmp_path: Path) -> tuple[dict[str, Any], dict[str, LazySource]]:
    parent, child = _parent_child_tables()
    cfg = _ooc_eligible_config(tmp_path, "parquet", tables=(parent, child))
    cfg = copy.deepcopy(cfg)
    cfg["relationships"] = []
    return cfg, _lazy(cfg)


# ---------------------------------------------------------------- the predicate


def test_a_flat_mask_table_is_named(tmp_path: Path) -> None:
    cfg, source = rs.single_table_job(tmp_path, rs.two_column_table(50))
    assert _names(cfg, {"t": source}, tmp_path) == {"t"}


def test_only_candidate_names_come_back(tmp_path: Path) -> None:
    cfg, candidates = _two_flat_tables(tmp_path)
    assert _names(cfg, {"parent": candidates["parent"]}, tmp_path) == {"parent"}
    assert _names(cfg, {}, tmp_path) == frozenset()


def test_a_vault_names_no_table(tmp_path: Path) -> None:
    cfg, candidates = _two_flat_tables(tmp_path)
    assert _names(cfg, candidates, tmp_path, vault_active=True) == frozenset()


def test_a_declared_casting_table_is_never_named(tmp_path: Path) -> None:
    # M-E5e: the auto-chunk streamed arm refuses a declared table when any sink is present.
    path = tmp_path / "t.parquet"
    pq.write_table(
        pa.table({"start": pa.array(["2020-01-02"] * 5), "n": pa.array(["a"] * 5)}), path
    )
    cols = [column("start", logical_type="date", parse_format=ISO_DATE, error_policy="null")]
    cfg = validate(config(cols, source_path=str(path), table="t"))
    cfg["sources"]["t"]["format"] = "parquet"
    assert _names(cfg, {"t": LazySource(path)}, tmp_path) == frozenset()


def test_a_flat_job_reads_no_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the pre-pass must not materialize a source")

    # The bounded profiler may read its sample through `iter_batches`; a whole read may not happen.
    monkeypatch.setattr(LazySource, "to_table", boom)
    monkeypatch.setattr(LazySource, "open_batches", boom)
    cfg, source = rs.single_table_job(tmp_path, rs.two_column_table(50))
    assert _names(cfg, {"t": source}, tmp_path) == {"t"}
    fk_dir = tmp_path / "fk"
    fk_dir.mkdir()
    fk_cfg, candidates = _fk(fk_dir)
    assert _names(fk_cfg, candidates, fk_dir) == {"parent", "child"}


def test_an_eligible_relationship_job_names_every_candidate(tmp_path: Path) -> None:
    cfg, candidates = _fk(tmp_path)
    assert _names(cfg, candidates, tmp_path) == {"parent", "child"}


@pytest.mark.parametrize(
    "override",
    [
        {"fidelity_report": True},
        {"post_validation": True},
        {"vault_active": True},
    ],
    ids=["fidelity", "post_validation", "vault"],
)
def test_a_relationship_job_with_a_disqualifier_names_nothing(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    cfg, candidates = _fk(tmp_path)
    assert _names(cfg, candidates, tmp_path, **override) == frozenset()


def test_validators_disqualify_a_relationship_job(tmp_path: Path) -> None:
    cfg, candidates = _fk(tmp_path)
    cfg["validators"] = [{"type": "row_count", "table": "parent", "min": 1}]
    assert _names(cfg, candidates, tmp_path) == frozenset()


def test_a_model_post_scan_ask_disqualifies_a_relationship_job(tmp_path: Path) -> None:
    cfg, candidates = _fk(tmp_path)
    cfg["post_scan"] = {"integrity": True, "detectors": ["ner"]}
    assert _names(cfg, candidates, tmp_path) == frozenset()


def test_a_generate_table_disqualifies_a_relationship_job(tmp_path: Path) -> None:
    cfg, candidates = _fk(tmp_path)
    cfg["tables"].append(
        {
            "name": "extra",
            "generate_columns": [{"name": "g", "provider": "uuid4"}],
            "row_count": 5,
        }
    )
    assert _names(cfg, candidates, tmp_path) == frozenset()


@pytest.mark.parametrize(
    "owner",
    [
        "_has_cross_table_fk_cycle",
        "out_of_core_admission",
        "decline_out_of_core",
        "fk_out_of_core_dtype_hazard",
    ],
)
def test_each_routing_owner_can_exclude_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    from decoy_engine.execution import _pipeline_routing, _pipeline_routing_fk_dtype
    from decoy_engine.execution import _pipeline_routing_signals as signals

    cfg, candidates = _fk(tmp_path)
    assert _names(cfg, candidates, tmp_path) == {"parent", "child"}
    seen: list[str] = []
    if owner == "_has_cross_table_fk_cycle":
        monkeypatch.setattr(_pipeline_routing, owner, lambda graph: seen.append(owner) or True)
    elif owner == "out_of_core_admission":

        def refuse(*_a: Any, **_k: Any) -> tuple[bool, str]:
            seen.append(owner)
            return False, "unsupported_recipe"

        monkeypatch.setattr(signals, owner, refuse)
        monkeypatch.setattr(_pipeline_routing, owner, refuse)
    elif owner == "decline_out_of_core":

        def decline(_config: Any, _ok: bool, _code: Any) -> tuple[bool, str]:
            seen.append(owner)
            return False, "declined"

        monkeypatch.setattr(signals, owner, decline)
    else:

        def hazard(*_a: Any, **_k: Any) -> bool:
            seen.append(owner)
            return True

        monkeypatch.setattr(_pipeline_routing_fk_dtype, owner, hazard)
    assert _names(cfg, candidates, tmp_path) == frozenset()
    assert seen, f"{owner} was never consulted"


def _transforming_flat(tmp_path: Path) -> tuple[dict[str, Any], dict[str, LazySource]]:
    table = pa.table({"s": [f"v{i}" for i in range(10)]})
    cfg = tk.single_table_config(tmp_path, table, transforms=[{"op": "limit", "n": 5}])
    return cfg, _lazy(cfg)


def test_a_transform_bearing_table_is_dropped_when_the_gate_applies(tmp_path: Path) -> None:
    # M-E5: a lazy transform-bearing table would defer the post-scan gate to report-only.
    cfg, candidates = _transforming_flat(tmp_path)
    cfg["post_scan"] = {"integrity": True}
    assert _names(cfg, candidates, tmp_path) == frozenset()


def test_a_transform_bearing_table_stays_when_no_gate_applies(tmp_path: Path) -> None:
    cfg, candidates = _transforming_flat(tmp_path)
    assert _names(cfg, candidates, tmp_path) == {"t"}


def test_a_transforming_relationship_job_is_left_to_the_owners(tmp_path: Path) -> None:
    parent = pa.table({"id": [f"p{i}" for i in range(20)], "note": [f"n{i}" for i in range(20)]})
    child = pa.table(
        {"cid": [f"c{i}" for i in range(20)], "parent_id": [f"p{i}" for i in range(20)]}
    )
    cfg = tk.fk_config(
        tmp_path, parent, child, parent_transforms=[{"op": "dedupe", "columns": ["id"]}]
    )
    assert _names(cfg, _lazy(cfg), tmp_path) == frozenset()


def test_the_pre_pass_copies_no_eligibility_rule() -> None:
    from decoy_engine.execution.pipeline import _lazy_input, _routing_facts

    tree = ast.parse(inspect.getsource(_lazy_input) + inspect.getsource(_routing_facts))
    called = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    # The five routing rules are one composition in `_pipeline_routing`, not a copy here.
    assert "bounded_admission" in called
    owners = {
        "compile_declared_casting_contract",
        "post_scan_gate_applies",
        "transform_bearing_mask_tables",
        "profile_source",
        "compile_plan",
        "build_relationship_graph",
    }
    assert owners <= imported | called
    source = inspect.getsource(_lazy_input) + inspect.getsource(_routing_facts)
    for rule in (
        "_sequential_eligible",
        "_has_cross_table_fk_cycle",
        "out_of_core_admission",
        "decline_out_of_core",
        "fk_out_of_core_dtype_hazard",
    ):
        assert rule not in source, f"{rule} belongs to bounded_admission, not a copy here"
    for code in (
        "VALIDATORS_PRESENT",
        "FIDELITY_REPORT",
        "GENERATE_PLUS_MASK",
        "CROSS_TABLE_CYCLE",
    ):
        assert code not in source, f"{code} is a routing reason; ask the owner instead"


# ---------------------------------------------------------------- the run_pipeline wiring


def _spy_context(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record the sources the run context carries once the fallback has read what it rejects."""
    from decoy_engine.execution import _pipeline_context

    seen: dict[str, Any] = {}
    real = _pipeline_context.build_run_context
    real_fallback = _pipeline_context.read_resident_fallback

    def spy(config: Any, sources: Any, **kw: Any) -> Any:
        ctx = real(config, sources, **kw)
        seen["sources"] = ctx.caller_sources
        return ctx

    def spy_fallback(config: Any, facts: Any, **kw: Any) -> Any:
        # Recorded here too: a run the later steps refuse never returns a context.
        out = real_fallback(config, facts, **kw)
        seen["sources"] = out.caller_sources
        return out

    monkeypatch.setattr(_pipeline_context, "build_run_context", spy)
    monkeypatch.setattr(_pipeline_context, "read_resident_fallback", spy_fallback)
    return seen


def _run(cfg: dict[str, Any], sources: Mapping[str, Any], **kw: Any) -> Any:
    from decoy_engine.execution import run_pipeline

    return run_pipeline(cfg, sources=sources, engine_version=V, **kw)


def _declared_cast_job(tmp_path: Path) -> tuple[dict[str, Any], LazySource, Path]:
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"start": pa.array(["2020-01-02"] * 5)}), path)
    cols = [column("start", logical_type="date", parse_format=ISO_DATE, error_policy="null")]
    cfg = validate(config(cols, source_path=str(path), table="t"))
    cfg["sources"]["t"]["format"] = "parquet"
    return cfg, LazySource(path), path


def test_a_rejected_lazy_table_reaches_the_context_resident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-E5e: a declared-cast table is read whole through `materialize_source`.
    cfg, lazy, _path = _declared_cast_job(tmp_path)
    seen = _spy_context(monkeypatch)
    fallback = _run(cfg, {"t": lazy}, resident_fallback=True)
    assert isinstance(seen["sources"]["t"], pa.Table)
    resident = _run(cfg, {"t": lazy.to_table()})
    from decoy_engine.execution.pipeline import route_summary

    assert fallback.outputs["t"].equals(resident.outputs["t"])
    assert route_summary(fallback.quality_metrics).route == (
        route_summary(resident.quality_metrics).route
    )


def test_a_vault_run_reads_every_lazy_table_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-E5h: the vault rule.
    cfg, lazy = rs.single_table_job(tmp_path, rs.two_column_table(50))
    seen = _spy_context(monkeypatch)

    class _Vault:
        pass

    # The vault writer is only inspected by the pre-pass here; the run itself may refuse it later.
    with contextlib.suppress(Exception):
        _run(cfg, {"t": lazy}, resident_fallback=True, vault_writer=_Vault())
    assert isinstance(seen["sources"]["t"], pa.Table)


def test_a_safe_lazy_table_stays_lazy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M-E5j: reading a table the rules keep lazy turns this red.
    cfg, lazy = rs.single_table_job(tmp_path, rs.two_column_table(50))
    seen = _spy_context(monkeypatch)
    _run(cfg, {"t": lazy}, resident_fallback=True)
    assert seen["sources"]["t"] is lazy


def _forbid_pre_pass(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from decoy_engine.execution.pipeline import _lazy_input

    calls: list[str] = []

    def boom(*_a: Any, **_k: Any) -> Any:
        calls.append("pre-pass")
        raise AssertionError("the pre-pass must not run")

    monkeypatch.setattr(_lazy_input, "resident_fallback_tables", boom)
    return calls


def test_the_default_runs_no_pre_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M-E5g: the keyword defaults to False.
    import inspect

    from decoy_engine.execution import run_pipeline

    assert inspect.signature(run_pipeline).parameters["resident_fallback"].default is False
    cfg, lazy, _path = _declared_cast_job(tmp_path)
    calls = _forbid_pre_pass(monkeypatch)
    seen = _spy_context(monkeypatch)
    _run(cfg, {"t": lazy}, auto_chunk=False)
    assert calls == []
    assert seen["sources"]["t"] is lazy


def test_stream_skips_the_pre_pass_and_reads_no_whole_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-E5k: `stream` raises `streaming_unavailable` before any whole-table read.
    cfg, lazy, _path = _declared_cast_job(tmp_path)
    reads: list[str] = []

    def spy_read(self: LazySource, *a: Any, **k: Any) -> Any:
        reads.append("read")
        raise AssertionError("no whole-table read may happen")

    # The run context's bounded profile samples through `iter_batches`; only a whole read is the
    # pre-pass's `materialize_source`, and `stream` must refuse before that.
    monkeypatch.setattr(LazySource, "to_table", spy_read)
    calls = _forbid_pre_pass(monkeypatch)
    with pytest.raises(Exception) as excinfo:
        _run(cfg, {"t": lazy}, resident_fallback=True, execution_mode="stream")
    assert "streaming_unavailable" in str(excinfo.value)
    assert reads == []
    assert calls == []


def test_an_explicit_route_skips_the_pre_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, lazy, _path = _declared_cast_job(tmp_path)
    calls = _forbid_pre_pass(monkeypatch)
    _spy_context(monkeypatch)
    with contextlib.suppress(
        Exception
    ):  # the lazy table may be refused later; only the call matters
        _run(cfg, {"t": lazy}, resident_fallback=True, execution_mode="full_frame")
    assert calls == []


def _spy_declarations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[frozenset[str], Any]]:
    """Record the (declared table names, registry) of each declaration the engine prepares."""
    from decoy_engine.execution import _guards

    calls: list[tuple[frozenset[str], Any]] = []
    real = _guards.prepare_declared_execution_sources

    def spy(request: Any, **kw: Any) -> Any:
        names = frozenset(i.table for i in request._inputs if i.origin != "descriptor")
        calls.append((names, kw.get("registry")))
        return real(request, **kw)

    monkeypatch.setattr(_guards, "prepare_declared_execution_sources", spy)
    return calls


def test_a_mixed_job_is_routed_over_every_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pre-pass sees the resident parent too, so it picks the route the run takes.
    cfg, lazy = _fk(tmp_path)
    sources = {"parent": lazy["parent"].to_table(), "child": lazy["child"]}
    calls = _spy_declarations(monkeypatch)
    from decoy_engine.execution.pipeline._lazy_input import resident_fallback_tables

    rejected = resident_fallback_tables(
        cfg,
        sources,
        engine_version=V,
        base_dir=tmp_path,
        instance_default_locale=None,
        fidelity_report=False,
        post_validation=False,
        vault_writer=None,
    )
    assert calls == [(frozenset({"parent", "child"}), get_default_registry())]
    assert rejected == frozenset()
    seen = _spy_context(monkeypatch)
    _run(cfg, sources, resident_fallback=True)
    assert seen["sources"]["child"] is sources["child"]
    assert seen["sources"]["parent"] is sources["parent"]
    assert calls[-1][0] == calls[0][0]


def test_the_pre_pass_uses_the_registry_the_run_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution import _pipeline_routing_signals as signals
    from decoy_engine.execution.pipeline._lazy_input import resident_fallback_tables
    from decoy_engine.providers_v2 import ProviderRegistry

    cfg, candidates = _fk(tmp_path)
    custom = ProviderRegistry(dict(get_default_registry()._bindings))
    calls = _spy_declarations(monkeypatch)
    admitted: list[Any] = []
    real = signals.out_of_core_admission

    def spy(plan: Any, **kw: Any) -> Any:
        admitted.append(kw["registry"])
        return real(plan, **kw)

    monkeypatch.setattr(signals, "out_of_core_admission", spy)
    resident_fallback_tables(
        cfg,
        candidates,
        engine_version=V,
        base_dir=tmp_path,
        instance_default_locale=None,
        fidelity_report=False,
        post_validation=False,
        vault_writer=None,
        registry=custom,
    )
    assert [reg for _names, reg in calls] == [custom]
    assert admitted == [custom]


def test_the_run_context_and_the_pre_pass_share_one_routing_facts_function() -> None:
    from decoy_engine.execution import _pipeline_context
    from decoy_engine.execution.pipeline import _lazy_input

    for module in (_pipeline_context, _lazy_input):
        tree = ast.parse(inspect.getsource(module))
        called = {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert "build_routing_facts" in called, module.__name__
        assert not {"profile_source", "compile_plan", "build_relationship_graph"} & called


def test_the_pre_pass_is_private() -> None:
    from decoy_engine.execution import pipeline
    from decoy_engine.fileaccess import ENTRY_POINTS

    assert "lazy_input_tables" not in pipeline.__all__
    assert not hasattr(pipeline, "resident_fallback_tables")
    assert not [e for e in ENTRY_POINTS if "_lazy_input" in e]


# ---------------------------------------------------------------- the collector


def _lane_call(cfg: dict[str, Any], source: Any, **kw: Any) -> Any:
    params: dict[str, Any] = {
        "table": support.TABLE,
        "engine_version": V,
        "registry": get_default_registry(),
        "adapter": PandasExecutionAdapter(),
        "vault_writer": None,
        "chunk_size_rows": 700,
        "key_provider": None,
        "native_threads": 1,
        "dispatcher_enabled": True,
    }
    params.update(kw)
    return ac.run_auto_chunk(cfg, source, **params)


def _flat_job(tmp_path: Path, rows: int = 2_000) -> tuple[dict[str, Any], pa.Table, LazySource]:
    table = rs.two_column_table(rows)
    cfg, lazy = rs.single_table_job(tmp_path, table)
    return cfg, table, lazy


def test_a_lazy_source_with_no_sink_returns_one_resident_output(tmp_path: Path) -> None:
    # M-E5c: the old assertion refused this call.
    cfg, table, lazy = _flat_job(tmp_path)
    outputs, _t, _ms, _w, metrics = _lane_call(cfg, lazy)
    ref_outputs, *_rest, ref_metrics = _lane_call(cfg, table)
    assert list(outputs) == ["t"]
    assert outputs["t"].equals(ref_outputs["t"])
    assert metrics["chunked_route"] == ref_metrics["chunked_route"]
    lane = metrics["auto_chunk"]
    assert lane["input"]["mode"] == "lazy"
    assert lane["output"] == {"mode": "resident", "reason": reasons.route.NO_SINK}


def test_the_resident_lane_stamp_is_unchanged(tmp_path: Path) -> None:
    cfg, table, _lazy_source = _flat_job(tmp_path)
    *_head, metrics = _lane_call(cfg, table)
    assert "output" not in metrics["auto_chunk"] and "input" not in metrics["auto_chunk"]


def test_the_collector_is_local_and_leaves_no_publication_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Any] = []
    real = _transactional_sink._CallableSinkAdapter

    class Spy(real):  # type: ignore[misc, valid-type]
        def __init__(self, fn: object, **kw: Any) -> None:
            super().__init__(fn, **kw)
            made.append(self)

    monkeypatch.setattr(_transactional_sink, "_CallableSinkAdapter", Spy)
    cfg, _table, lazy = _flat_job(tmp_path)
    result = _lane_call(cfg, lazy)
    assert len(made) == 1
    flat = repr(result[1:])
    assert "publication" not in flat.lower() and "PublicationEvidence" not in flat
    assert all(getattr(part, "publication_evidence", None) is None for part in result)


def test_an_external_sink_never_gets_the_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Any] = []
    real = _transactional_sink._CallableSinkAdapter

    class Spy(real):  # type: ignore[misc, valid-type]
        def __init__(self, fn: object, **kw: Any) -> None:
            super().__init__(fn, **kw)
            made.append(self)

    monkeypatch.setattr(_transactional_sink, "_CallableSinkAdapter", Spy)
    cfg, _table, lazy = _flat_job(tmp_path)
    sink, _target = rs.real_sink(tmp_path)
    outputs, *_rest, metrics = _lane_call(cfg, lazy, sink=sink)
    assert outputs == {} and not made
    assert metrics["auto_chunk"]["output"]["mode"] == "streamed"


def test_a_declared_table_is_still_refused_with_the_collector(tmp_path: Path) -> None:
    from decoy_engine.execution._errors import DeclaredCastRouteError

    class _Cast:
        def tables(self) -> frozenset[str]:
            return frozenset({"t"})

    cfg, _table, lazy = _flat_job(tmp_path)
    with pytest.raises(DeclaredCastRouteError):
        _lane_call(cfg, lazy, cast_run=_Cast())


def _gate_over(
    cfg: dict[str, Any], sources: Mapping[str, Any], outputs: Mapping[str, pa.Table]
) -> tuple[PostScanGate, str]:
    kinds = {name: "mask" for name in sources}
    gate = PostScanGate(cfg, sources=sources)
    try:
        gate.run_resident(outputs, sources, kinds)
    except PostScanBlockedError as exc:
        return gate, f"blocked:{exc.__class__.__name__}"
    return gate, "passed"


def _gated_lane(
    cfg: dict[str, Any], sources: Mapping[str, Any]
) -> tuple[PostScanGate, str, dict[str, pa.Table]]:
    gate = PostScanGate(cfg, sources=sources)
    token = _post_scan._ACTIVE.set(gate)
    try:
        outputs: dict[str, pa.Table] = {}
        for name, source in sources.items():
            got, *_rest = _lane_call(cfg, source, table=name)
            outputs.update(got)
    finally:
        _post_scan._ACTIVE.reset(token)
    assert not gate.output_unreadable and not gate.ran  # M-E5f: the lane never handed it a sink
    verdict_gate, verdict = _gate_over(cfg, sources, outputs)
    return verdict_gate, verdict, outputs


def test_a_relationship_post_scan_verdict_equals_the_resident_call(tmp_path: Path) -> None:
    cfg, lazy, tables = rs.fk_job(tmp_path)
    lazy_gate, lazy_verdict, lazy_out = _gated_lane(cfg, lazy)
    resident_gate, resident_verdict, resident_out = _gated_lane(cfg, tables)
    assert lazy_verdict == resident_verdict == "passed"
    assert lazy_out.keys() == resident_out.keys() == {"customers", "orders"}
    for name, got in lazy_out.items():
        assert got.equals(resident_out[name])
    assert lazy_gate.output_unreadable is resident_gate.output_unreadable is False
    assert lazy_gate.report == resident_gate.report and lazy_gate.report is not None


# ---------------------------------------------------------------- E5a: through run_pipeline


def support_run(cfg: dict[str, Any], sources: Mapping[str, Any], **extra: Any) -> Any:
    from decoy_engine.execution import run_pipeline

    return run_pipeline(cfg, sources=sources, **support.run_kwargs(**extra))


def _reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Rows of every batch the Parquet reader yields."""
    yields: list[int] = []
    real = pq.ParquetFile.iter_batches

    def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
        for batch in real(self, *args, **kwargs):
            yields.append(batch.num_rows)
            yield batch

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", spy)
    return yields


def _never_materialized(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    from decoy_engine.execution import _pipeline_sources

    real = _pipeline_sources.materialize_source

    def spy(value: Any) -> Any:
        if isinstance(value, LazySource) and Path(value.path) == path:
            raise AssertionError("the admitted lazy source was materialized")
        return real(value)

    monkeypatch.setattr(_pipeline_sources, "materialize_source", spy)


def _context_sinks(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    from decoy_engine.execution import _pipeline_context

    seen: dict[str, list[Any]] = {"context": [], "commit": []}
    real_build = _pipeline_context.build_run_context

    def build(*args: Any, **kwargs: Any) -> Any:
        ctx = real_build(*args, **kwargs)
        seen["context"].append(ctx.sink)
        return ctx

    real_commit = PostScanGate.before_commit

    def before_commit(self: Any, sink: Any) -> None:
        seen["commit"].append(sink)
        real_commit(self, sink)

    monkeypatch.setattr(_pipeline_context, "build_run_context", build)
    monkeypatch.setattr(PostScanGate, "before_commit", before_commit)
    return seen


def _paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    taken: list[str] = []
    for name in ("_run_streamed", "_run_dispatcher", "_run_legacy"):
        real = getattr(ac, name)
        monkeypatch.setattr(
            ac, name, lambda *a, _n=name, _r=real, **k: (taken.append(_n), _r(*a, **k))[1]
        )
    return taken


_E5A_ROWS = 200  # 13 chunks of `support.CHUNK` rows


def test_a_lazy_table_with_no_sink_streams_its_input_through_run_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AT-E5a; M-E5a restores the streamed-output-only input mode and turns this red.
    cfg, table, lazy = _flat_job(tmp_path, rows=_E5A_ROWS)
    want = support_run(cfg, {"t": table})
    reads = _reads(monkeypatch)
    _never_materialized(monkeypatch, Path(lazy.path))
    sinks = _context_sinks(monkeypatch)
    taken = _paths(monkeypatch)
    got = support_run(cfg, {"t": lazy})
    assert _E5A_ROWS // support.CHUNK > 3 and len(reads) >= 3, reads
    assert taken == ["_run_streamed"]
    assert sinks["context"] == [None] and all(s is None for s in sinks["commit"])
    assert list(got.outputs) == ["t"] and got.outputs["t"].equals(want.outputs["t"])
    lane = got.quality_metrics["auto_chunk"]
    assert lane["input"]["mode"] == "lazy"
    assert lane["output"] == {"mode": "resident", "reason": reasons.route.NO_SINK}
    assert got.quality_metrics["execution"]["outputs_streamed"] is False


def test_the_dispatcher_kill_switch_does_not_leave_the_streamed_collector_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AT-E5a V2-LOG pin: `dispatcher_enabled=False` has no effect on a lazy no-sink lane.
    cfg, table, lazy = _flat_job(tmp_path, rows=_E5A_ROWS)
    enabled = support_run(cfg, {"t": lazy})
    taken = _paths(monkeypatch)
    got = support_run(cfg, {"t": lazy}, chunked_dispatcher_enabled=False)
    assert taken == ["_run_streamed"]
    assert got.outputs["t"].equals(enabled.outputs["t"])
    want = support_run(cfg, {"t": table})
    assert got.outputs["t"].equals(want.outputs["t"])
    for key in ("input", "output"):
        assert got.quality_metrics["auto_chunk"][key] == enabled.quality_metrics["auto_chunk"][key]
    lane, lane_reason = ac.select_lane(False)
    assert got.quality_metrics["auto_chunk"]["lane"] == lane
    assert got.quality_metrics["auto_chunk"]["lane_reason"] == lane_reason


def test_a_declared_table_with_no_sink_still_runs_resident(tmp_path: Path) -> None:
    # The collector refuses a declared table, so E5a keeps that table's input resident.
    path = tmp_path / "t.parquet"
    pq.write_table(
        pa.table(
            {
                "start": pa.array(["2020-01-02"] * _E5A_ROWS),
                "n": pa.array([f"a{i}" for i in range(_E5A_ROWS)]),
            }
        ),
        path,
    )
    cols = [
        column("start", logical_type="date", parse_format=ISO_DATE, error_policy="null"),
        column("n"),
    ]
    cfg = validate(config(cols, source_path=str(path), table="t"))
    cfg["sources"]["t"]["format"] = "parquet"
    want = support_run(cfg, {"t": pq.read_table(path)})
    got = support_run(cfg, {"t": LazySource(path)})
    assert list(got.outputs) == list(want.outputs)
    for name, table in want.outputs.items():
        assert got.outputs[name].equals(table), name


def _leaky_suite(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, int]]:
    """The real column suite plus one `fail` finding for a passthrough column the gate sees equal
    to its source on every row. It needs the whole source and the whole collected output, so a
    gate that never got the output cannot block. Returns the output rows each scan saw."""
    real = _post_scan.run_post_mask
    seen: list[dict[str, int]] = []

    def suite(sources: Any, outputs: Any, **kw: Any) -> dict[str, Any]:
        report = dict(real(sources, outputs, **kw))
        seen.append({name: len(frame) for name, frame in outputs.items()})
        leaked = [
            {"table": name, "column": "p", "detector_id": "made_up", "severity": "fail"}
            for name, frame in outputs.items()
            if len(frame) and (frame["p"] == sources[name]["p"]).all()
        ]
        report["residual_pii"] = [*report.get("residual_pii", []), *leaked]
        return report

    monkeypatch.setattr(_post_scan, "run_post_mask", suite)
    return seen


def _blocked_by(run: Any) -> PostScanBlockedError:
    with pytest.raises(PostScanBlockedError) as caught:
        run()
    return caught.value


def test_a_lazy_no_sink_run_is_blocked_by_post_scan_exactly_as_the_resident_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-E5f installs the collector as the run's sink: the gate then sees a sink it cannot read
    # and refuses or defers instead of blocking on the collected output.
    cfg, table, lazy = _flat_job(tmp_path, rows=_E5A_ROWS)
    cfg["post_scan"] = {"integrity": True}
    seen = _leaky_suite(monkeypatch)
    want = _blocked_by(lambda: support_run(cfg, {"t": table}))
    taken = _paths(monkeypatch)
    sinks = _context_sinks(monkeypatch)
    got = _blocked_by(lambda: support_run(cfg, {"t": lazy}))
    assert _E5A_ROWS // support.CHUNK > 1
    assert taken == ["_run_streamed"]
    assert sinks["context"] == [None]
    assert seen == [{"t": _E5A_ROWS}, {"t": _E5A_ROWS}]
    assert type(got) is type(want)
    assert got.reason == want.reason
    assert str(got) == str(want)


def test_a_zero_row_lazy_source_through_the_collector_keeps_the_source_schema(
    tmp_path: Path,
) -> None:
    # The `empty_schema` write, then `collected[table]`, with nothing to join. The resident lane
    # refuses a table with no chunks, and `run_pipeline` never routes a zero-row table to the
    # lane, so the collector's output is held to the empty table base `--chunked` writes.
    cfg, table, lazy = _flat_job(tmp_path, rows=0)
    outputs, *_rest, metrics = _lane_call(cfg, lazy)
    assert list(outputs) == ["t"]
    assert outputs["t"].equals(table.schema.empty_table())
    via_run = support_run(cfg, {"t": lazy})
    assert via_run.outputs["t"].equals(support_run(cfg, {"t": table}).outputs["t"])
    assert metrics["auto_chunk"]["input"]["mode"] == "lazy"
    assert metrics["auto_chunk"]["output"] == {"mode": "resident", "reason": reasons.route.NO_SINK}


# ---------------------------------------------------------------- E5a: collector spill (AT-E5s)

_SPILL_ROWS = 1_200_000
_SPILL_NULLS = 1_100_000
_SPILL_CHUNK = 100_000


@pytest.fixture(scope="module")
def spill_job(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    """The first column is null through row 1,100,000, so its output type resolves only after
    more than one 1,048,576-row group is held back (mirrors AT-C1i with no sink)."""
    base = tmp_path_factory.mktemp("e5s")
    dates = [f"2021-{1 + (i % 12):02d}-15" for i in range(_SPILL_ROWS - _SPILL_NULLS)]
    table = pa.table(
        {
            "val": pa.array([None] * _SPILL_NULLS + dates, pa.string()),
            "p": pa.array(range(_SPILL_ROWS), pa.int64()),
        }
    )
    path = Path(support.write_source(table, base / "late.parquet"))
    column = {
        "name": "val",
        "strategy": "bucket_perturb",
        "namespace": "tier_ns",
        "provider_config": {"date_format": "%Y-%m-%d", "bucket": "month"},
    }
    return support.make_cfg([column, support.pass_col("p")], path=str(path)), path


def _spill_run(cfg: dict[str, Any], source: Any) -> Any:
    return support_run(
        cfg, {"t": source}, chunk_size_rows=_SPILL_CHUNK, auto_chunk_threshold_rows=1_000
    )


class _ScratchSpy:
    """Records each collector scratch arena (and its root's mode), what the adapter's
    `open_spill_scratch` hands back and the hold stage directories present at each spill write."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, fail: BaseException | None = None) -> None:
        from decoy_engine.execution import _chunked_output_sink
        from decoy_engine.fileaccess import ScratchArena

        self.roots: list[tuple[Path, int]] = []
        self.arenas: list[Any] = []
        self.scratches: list[Any] = []
        self.fresh_calls = 0
        self.opener_calls = 0
        self.holds: list[tuple[Path, int]] = []
        self.writes = 0
        real_open = ScratchArena.fresh.__func__  # type: ignore[attr-defined]
        spy = self

        def opened(cls: Any, **kw: Any) -> Any:
            arena = real_open(cls, **kw)
            spy.fresh_calls += 1
            root = Path(arena.local_path())
            spy.arenas.append(arena)
            spy.roots.append((root, stat.S_IMODE(root.stat().st_mode)))
            return arena

        monkeypatch.setattr(ScratchArena, "fresh", classmethod(opened))
        real_adapter = _transactional_sink._CallableSinkAdapter

        class Adapter(real_adapter):  # type: ignore[misc, valid-type]
            def __init__(self, fn: object, **kw: Any) -> None:
                opener = kw.get("open_spill_scratch")
                if opener is not None:  # the output-mode probe's stand-in sink takes none

                    def recording() -> Any:
                        spy.opener_calls += 1
                        arena = opener()
                        spy.scratches.append(arena)
                        return arena

                    kw["open_spill_scratch"] = recording
                super().__init__(fn, **kw)

        monkeypatch.setattr(_transactional_sink, "_CallableSinkAdapter", Adapter)
        real_add = _chunked_output_sink._Spill.add

        def add(this: Any, chunk: pa.Table) -> None:
            real_add(this, chunk)
            self.writes += 1
            if self.writes == 1 and self.roots:
                for entry in self.roots[-1][0].iterdir():
                    if entry.name == "hold":
                        self.holds.append((entry, stat.S_IMODE(entry.stat().st_mode)))
            if fail is not None:
                raise fail

        monkeypatch.setattr(_chunked_output_sink._Spill, "add", add)


def test_the_no_sink_collector_spills_beneath_its_own_run_root(
    spill_job: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # AT-E5s; M-E5s drops the collector's spill parent (HOLD_BACK_SPILL_UNAVAILABLE).
    cfg, path = spill_job
    want = _spill_run(cfg, pq.read_table(path))
    spy = _ScratchSpy(monkeypatch)
    got = _spill_run(cfg, LazySource(path))
    assert got.quality_metrics["auto_chunk"]["input"]["mode"] == "lazy"
    assert got.outputs["t"].equals(want.outputs["t"])
    assert spy.writes > 0
    assert len(spy.roots) == 1 and spy.roots[0][1] == 0o700
    root = spy.roots[0][0]
    assert spy.scratches == spy.arenas and spy.fresh_calls == 1
    assert spy.holds and all(h.parent == root and mode == 0o700 for h, mode in spy.holds)
    assert not root.exists()


@pytest.mark.parametrize("fail", [RuntimeError("injected spill failure"), KeyboardInterrupt()])
def test_a_failure_after_the_first_spill_write_removes_the_hold_and_the_run_root(
    fail: BaseException, spill_job: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # AT-E5s; M-E5s2 closes the scratch scope only on success and leaves the root behind.
    cfg, path = spill_job
    spy = _ScratchSpy(monkeypatch, fail=fail)
    with pytest.raises(type(fail)):
        _spill_run(cfg, LazySource(path))
    assert spy.writes == 1 and len(spy.roots) == 1 and spy.holds
    assert not any(h.exists() for h, _mode in spy.holds)
    assert not spy.roots[0][0].exists()


def test_a_no_spill_lazy_no_sink_run_creates_no_scratch_arena(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E5b; M-E5b1 enters the arena eagerly again and turns this red.
    cfg, table, lazy = _flat_job(tmp_path, rows=_E5A_ROWS)
    want = support_run(cfg, {"t": table})
    spy = _ScratchSpy(monkeypatch)
    reads = _reads(monkeypatch)
    got = support_run(cfg, {"t": lazy})
    assert got.quality_metrics["auto_chunk"]["input"]["mode"] == "lazy" and len(reads) >= 3
    assert got.outputs["t"].equals(want.outputs["t"])
    assert spy.fresh_calls == 0 and spy.arenas == [] and spy.writes == 0


def test_the_spill_opener_is_memoized_and_enters_the_run_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # E5b; M-E5b2 makes a second call open a second arena, M-E5b4 opens it outside the scope.
    from contextlib import ExitStack

    spy = _ScratchSpy(monkeypatch)
    collected: dict[str, pa.Table] = {}
    with ExitStack() as scope:
        sink = ac._collector(collected, scope)
        assert spy.fresh_calls == 0
        first = sink.open_spill_scratch()
        assert sink.open_spill_scratch() is first
        assert spy.fresh_calls == 1
        root = spy.roots[0][0]
        assert root.exists()
    assert not root.exists()


class _Win32:
    """Stands in for `sys` inside the scratch module, so only `ScratchArena.fresh` sees win32."""

    platform = "win32"


def test_a_win32_host_does_not_refuse_a_no_spill_lazy_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E5b; the base resident read worked on win32, so a run that never spills must too.
    from decoy_engine.fileaccess import _scratch

    cfg, table, lazy = _flat_job(tmp_path, rows=_E5A_ROWS)
    want = support_run(cfg, {"t": table})
    monkeypatch.setattr(_scratch, "sys", _Win32)
    got = support_run(cfg, {"t": lazy})
    assert got.quality_metrics["auto_chunk"]["input"]["mode"] == "lazy"
    assert got.outputs["t"].equals(want.outputs["t"])


def test_a_win32_host_refuses_a_spilling_lazy_run_at_the_spill(
    spill_job: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # E5b: the refusal moves from before the first read to the first spill; no scratch is left.
    from decoy_engine.fileaccess import FileAccessUnavailable, _scratch

    cfg, path = spill_job
    spy = _ScratchSpy(monkeypatch)
    monkeypatch.setattr(_scratch, "sys", _Win32)
    with pytest.raises(FileAccessUnavailable):
        _spill_run(cfg, LazySource(path))
    # An eager open refuses inside `_collector`, before any sink exists to call the opener.
    assert spy.opener_calls == 1
    assert spy.writes == 0 and spy.arenas == []


# ------------------------------------------------ the collector spill under a strict policy


def _strict_policies(tmp_path: Path) -> list[Any]:
    """A policy that grants nothing the spill could name: a rooted one over an empty directory
    and a preopened one with no grants."""
    import os

    from decoy_engine.fileaccess import (
        FileRole,
        PreopenedFileAccess,
        Root,
        RootedFileAccess,
    )
    from decoy_engine.fileaccess._openat2 import openat2_usable

    policies: list[Any] = [PreopenedFileAccess()]
    if openat2_usable():
        root = tmp_path / "granted"
        root.mkdir()
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        policies.append(
            RootedFileAccess([Root("main", fd, frozenset({FileRole.SOURCE}), frozenset({"read"}))])
        )
    return policies


@pytest.mark.parametrize("which", [0, 1], ids=["preopened", "rooted"])
def test_the_collector_spills_under_a_strict_file_access_policy(
    which: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hold-back past one row group must not re-authorize a path through the policy; the old
    # collector handed `_Spill` a temporary path and a strict policy denied it.
    from contextlib import ExitStack

    from decoy_engine import fileaccess
    from decoy_engine.execution import _chunked_output_sink

    policies = _strict_policies(tmp_path)
    if which >= len(policies):
        pytest.skip("rooted file access needs Linux openat2")
    monkeypatch.setattr(_chunked_output_sink, "ROW_GROUP_ROWS", 100)
    nulls = pa.nulls(60)
    dates = pa.array(["2021-01-15"] * 60, pa.string())
    chunks = [
        pa.table({"val": nulls, "p": pa.array(range(60), pa.int64())}),
        pa.table({"val": nulls, "p": pa.array(range(60), pa.int64())}),
        pa.table({"val": nulls, "p": pa.array(range(60), pa.int64())}),
        pa.table({"val": dates, "p": pa.array(range(60), pa.int64())}),
    ]
    collected: dict[str, pa.Table] = {}
    with fileaccess.scope(policies[which]), ExitStack() as scope:
        sink = ac._collector(collected, scope)
        stats = _chunked_output_sink.stream_table(sink, "t", chunks, fixed_columns=frozenset())
    assert stats.spilled_chunks > 0
    assert collected["t"].num_rows == 240
    assert collected["t"].column("val").type == pa.string()


# ------------------------------------------------ the predicate and the router agree


def _parity_case(tmp_path: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """An FK job and the `run_pipeline` flags that shape its routing."""
    cfg, _candidates = _fk(tmp_path)
    flags: dict[str, Any] = {"fidelity_report": False, "post_validation": False}
    if name == "fidelity":
        flags["fidelity_report"] = True
    elif name == "post_validation":
        flags["post_validation"] = True
    elif name == "validators":
        cfg["validators"] = [{"type": "row_count", "table": "parent", "min": 1}]
    elif name == "generate":
        cfg["tables"].append(
            {
                "name": "extra",
                "generate_columns": [{"name": "g", "provider": "uuid4"}],
                "row_count": 5,
            }
        )
    elif name == "model_post_scan":
        cfg["post_scan"] = {"integrity": True, "detectors": ["ner"]}
    return cfg, flags


@pytest.mark.parametrize(
    "name",
    ["eligible", "fidelity", "post_validation", "validators", "generate", "model_post_scan"],
)
def test_the_predicate_and_the_router_agree_on_bounded_admission(tmp_path: Path, name: str) -> None:
    # The predicate and `resolve_execution_route` take one decision: a job the predicate admits
    # routes out-of-core when large, and a job it declines does not.
    from decoy_engine.config import classify_table_kinds
    from decoy_engine.execution import _pipeline_routing as routing
    from decoy_engine.execution import _pipeline_routing_signals as signals
    from decoy_engine.execution._errors import ExecutionError
    from decoy_engine.execution.pipeline._routing_facts import build_routing_facts
    from decoy_engine.providers_v2 import get_default_registry

    cfg, flags = _parity_case(tmp_path, name)
    candidates = _lazy(cfg)
    registry = get_default_registry()
    facts = build_routing_facts(
        cfg,
        candidates,
        registry=registry,
        source_loader_schemas=None,
        engine_version=V,
        base_dir=tmp_path,
        instance_default_locale=None,
    )
    profile, plan, graph = facts.profile, facts.plan, facts.graph
    kinds = classify_table_kinds(cfg)
    common: dict[str, Any] = {
        "plan": plan,
        "registry": registry,
        "graph": graph,
        "caller_sources": dict(candidates),
        "has_generate_table": "generate" in kinds.values(),
        "has_mask_table": True,
        "table_kinds": kinds,
        "validators": cfg.get("validators") or [],
        "fidelity_report": flags["fidelity_report"],
        "post_validation": flags["post_validation"],
        "vault_writer": None,
    }
    admission = routing.bounded_admission(profile, config=cfg, **common)
    try:
        route, _reason = signals.resolve_execution_route(
            profile,
            execution_mode="auto",
            resolved_substrate="pandas",
            out_of_core_threshold_rows=1,
            full_frame_reject_rows=10**9,
            out_of_core_budget_bytes=None,
            use_byte_estimate_routing=False,
            use_probe_routing=False,
            config=cfg,
            engine_version=V,
            **common,
        )
    except ExecutionError:
        route = "rejected"
    assert admission.admitted == (route == "out_of_core"), (name, admission, route)
    assert admission.admitted == (name == "eligible")


# ---------------------------------------------------- order against the config-only checks


def _no_whole_read(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reads: list[str] = []

    def spy(self: LazySource, *a: Any, **k: Any) -> Any:
        reads.append("to_table")
        raise AssertionError("a config-only refusal must come before any whole read")

    monkeypatch.setattr(LazySource, "to_table", spy)
    return reads


def _code_of(excinfo: pytest.ExceptionInfo[BaseException]) -> Any:
    return getattr(excinfo.value, "code", type(excinfo.value).__name__)


def test_a_bad_chunk_knob_is_refused_before_a_whole_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, lazy, _path = _declared_cast_job(tmp_path)
    with pytest.raises(Exception) as off:
        _run(cfg, {"t": lazy}, chunk_size_rows=0)
    reads = _no_whole_read(monkeypatch)
    with pytest.raises(Exception) as on:
        _run(cfg, {"t": lazy}, resident_fallback=True, chunk_size_rows=0)
    assert reads == []
    assert type(on.value) is type(off.value) and _code_of(on) == _code_of(off)
    assert _code_of(on) == reasons.runtime.INVALID_EXECUTION_KNOB


def test_a_missing_mask_secret_is_refused_before_a_whole_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.execution import _sample_run_support as sup

    monkeypatch.delenv(sup.VAR, raising=False)
    cfg, _data, lazy = sup.chain_job(tmp_path)
    with pytest.raises(Exception) as off:
        _run(cfg, lazy, fidelity_report=True)
    reads = _no_whole_read(monkeypatch)
    with pytest.raises(Exception) as on:
        _run(cfg, lazy, resident_fallback=True, fidelity_report=True)
    assert reads == []
    assert type(on.value) is type(off.value) and _code_of(on) == _code_of(off)


# ------------------------------------------------------ the pre-pass sees the run's own inputs


def test_a_subset_run_reads_whole_only_the_rows_it_keeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution.pipeline import _lazy_input
    from decoy_engine.execution.pipeline._subset_stage import SubsetStageScope
    from decoy_engine.subset import sample_request
    from tests.unit.execution import _sample_run_support as sup

    monkeypatch.setenv(sup.VAR, "ab" * 32)
    cfg, data, lazy = sup.chain_job(tmp_path)
    request = sample_request(cfg, rows=5)
    read_rows: list[int] = []
    real_read = _lazy_input.materialize_source

    def spy_read(source: Any) -> Any:
        table = real_read(source)
        read_rows.append(table.num_rows)
        return table

    applied: list[int] = []
    real_apply = SubsetStageScope.apply

    def spy_apply(self: SubsetStageScope, *a: Any, **k: Any) -> Any:
        applied.append(1)
        return real_apply(self, *a, **k)

    seen: dict[str, Any] = {}
    real_tables = _lazy_input.resident_fallback_tables

    def spy_tables(config: Any, sources: Any, **kw: Any) -> Any:
        seen["facts_sources"] = kw["facts"].caller_sources
        seen["sources"] = sources
        return real_tables(config, sources, **kw)

    monkeypatch.setattr(_lazy_input, "materialize_source", spy_read)
    monkeypatch.setattr(SubsetStageScope, "apply", spy_apply)
    monkeypatch.setattr(_lazy_input, "resident_fallback_tables", spy_tables)

    class _Vault:
        pass

    # The vault rule makes every lazy table read whole; the run may refuse the writer afterwards.
    with contextlib.suppress(Exception):
        _run(
            cfg,
            lazy,
            resident_fallback=True,
            vault_writer=_Vault(),
            subset_request=request,
        )
    full = max(t.num_rows for t in data.values())
    assert read_rows, "the vault rule must read the lazy tables"
    assert max(read_rows) <= 5 < full
    assert seen["sources"] is seen["facts_sources"]
    assert applied == [1]
