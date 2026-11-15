"""RUN-STREAM E5 (AT-E5): `lazy_input_tables` and the no-sink resident collector.

The predicate names the candidate tables that may arrive lazy and copies no routing rule: every
exclusion below is an existing engine owner answering. The collector lets a lazy source run the
auto-chunk lane with no publication sink, returning one resident output.
"""

from __future__ import annotations

import ast
import copy
import inspect
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
    from decoy_engine.execution.pipeline import lazy_input_tables

    args: dict[str, Any] = {
        "engine_version": V,
        "base_dir": base,
        "instance_default_locale": None,
        "fidelity_report": False,
        "post_validation": False,
        "vault_active": False,
    }
    args.update(over)
    return lazy_input_tables(cfg, candidates, **args)


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
        raise AssertionError("the predicate must not materialize a source")

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
    from decoy_engine.execution import _transforms_admission as admission

    cfg, candidates = _fk(tmp_path)
    assert _names(cfg, candidates, tmp_path) == {"parent", "child"}
    seen: list[str] = []
    if owner == "_has_cross_table_fk_cycle":
        monkeypatch.setattr(_pipeline_routing, owner, lambda graph: seen.append(owner) or True)
    elif owner == "out_of_core_admission":
        from decoy_engine.execution import _pipeline_routing_signals as signals

        def refuse(*_a: Any, **_k: Any) -> tuple[bool, str]:
            seen.append(owner)
            return False, "unsupported_recipe"

        monkeypatch.setattr(signals, owner, refuse)
        monkeypatch.setattr(_pipeline_routing, owner, refuse)
    elif owner == "decline_out_of_core":

        def decline(_config: Any, _ok: bool, _code: Any) -> tuple[bool, str]:
            seen.append(owner)
            return False, "declined"

        monkeypatch.setattr(admission, owner, decline)
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


def test_the_predicate_copies_no_eligibility_rule() -> None:
    from decoy_engine.execution.pipeline import _lazy_input

    tree = ast.parse(inspect.getsource(_lazy_input))
    called = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    owners = {
        "_sequential_eligible",
        "_has_cross_table_fk_cycle",
        "out_of_core_admission",
        "decline_out_of_core",
        "fk_out_of_core_dtype_hazard",
        "compile_declared_casting_contract",
        "post_scan_gate_applies",
        "transform_bearing_mask_tables",
        "profile_source",
        "compile_plan",
        "build_relationship_graph",
    }
    assert owners <= imported | called
    source = inspect.getsource(_lazy_input)
    for code in (
        "VALIDATORS_PRESENT",
        "FIDELITY_REPORT",
        "GENERATE_PLUS_MASK",
        "CROSS_TABLE_CYCLE",
    ):
        assert code not in source, f"{code} is a routing reason; ask the owner instead"


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
        def __init__(self, fn: object) -> None:
            super().__init__(fn)
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
        def __init__(self, fn: object) -> None:
            super().__init__(fn)
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
