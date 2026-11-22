"""NATIVE-MISSING-WARN E1: the one engine-side decision that a run used no compiled kernel.

`native_fallback_code` reads the compiled plan and the kernel availability. The tests inject
`KernelAvailability` so the answer never depends on whether the box that runs them has the
companion; AT-8 is the one test that reads the real probe, and CI runs it in both companion
states.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.execution import run_pipeline
from decoy_engine.execution.native._companion_status import (
    KernelAvailability,
    native_kernel_availability,
)
from decoy_engine.execution.pipeline import _native_notice, route_summary
from decoy_engine.plan import compile_plan
from decoy_engine.profile import profile_source
from tests._declared_schema import declare_rest
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _r3_scenarios as scenarios
from tests.unit.execution._r3_project import project

_CODE = "native_companion_missing"
_NONE_AVAILABLE = KernelAvailability(crypto=False, index=False, raw_hex=False, fpe=False)
_ALL_AVAILABLE = KernelAvailability(crypto=True, index=True, raw_hex=True, fpe=True)
_NO_RAW_HEX = KernelAvailability(crypto=True, index=True, raw_hex=False, fpe=True)


def _plan(tmp_path: Path, columns: list[dict[str, Any]], data: dict[str, pa.Array]) -> Any:
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table(data), path)
    cfg = support.make_cfg(columns, path=str(path))
    profile = profile_source(cfg, seed=0)
    return compile_plan(cfg, profile, decoy_engine_version="nmw-e1", sources=NO_SOURCES)


def _strings(n: int = 12) -> pa.Array:
    return pa.array([f"v{i}" for i in range(n)])


def _group_key(name: str) -> dict[str, Any]:
    return {"name": name, "strategy": "group_key", "provider_config": {"group_by": "g"}}


def _spy_probe(monkeypatch: pytest.MonkeyPatch, answer: KernelAvailability) -> list[int]:
    calls: list[int] = []

    def probe() -> KernelAvailability:
        calls.append(1)
        return answer

    monkeypatch.setattr(_native_notice, "native_kernel_availability", probe)
    return calls


# AT-1


def test_hash_plan_with_no_kernel_reports_the_code(tmp_path: Path) -> None:
    plan = _plan(tmp_path, [support.hash_col("h")], {"h": _strings()})
    assert _native_notice.native_fallback_code(plan, _NONE_AVAILABLE) == _CODE


def test_hash_plan_with_its_kernel_reports_nothing(tmp_path: Path) -> None:
    plan = _plan(tmp_path, [support.hash_col("h")], {"h": _strings()})
    only_crypto = KernelAvailability(crypto=True, index=False, raw_hex=False, fpe=False)
    assert _native_notice.native_fallback_code(plan, only_crypto) is None


def test_python_only_plan_reports_nothing_and_never_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(
        tmp_path,
        [support.redact_col("r"), support.truncate_col("t"), support.pass_col("p")],
        {"r": _strings(), "t": _strings(), "p": _strings()},
    )
    calls = _spy_probe(monkeypatch, _NONE_AVAILABLE)
    assert _native_notice.native_fallback_code(plan) is None
    assert calls == []


def test_without_an_injected_availability_the_plan_probes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path, [support.hash_col("h")], {"h": _strings()})
    calls = _spy_probe(monkeypatch, _NONE_AVAILABLE)
    assert _native_notice.native_fallback_code(plan) == _CODE
    assert calls == [1]


# AT-2


def _go(cfg: dict[str, Any], sources: Any, **kw: Any) -> Any:
    # One thread so the run does not depend on the host's core count.
    return run_pipeline(cfg, sources, engine_version="nmw-e1", native_threads=1, **kw)


def _run_unified(tmp: Path) -> Any:
    cfg, table = scenarios.single_table(tmp)
    return _go(cfg, {"t": table}, key_provider=scenarios.key_provider())


def _run_auto_chunk(tmp: Path) -> Any:
    cfg, table = scenarios.single_table(tmp)
    return _go(
        cfg,
        {"t": table},
        auto_chunk_threshold_rows=10,
        chunk_size_rows=8,
        use_byte_estimate_routing=False,
        key_provider=scenarios.key_provider(),
    )


def _run_fk(tmp: Path, mode: str) -> Any:
    cfg, tables = scenarios.fk_job(tmp)
    return _go(cfg, tables, execution_mode=mode, key_provider=scenarios.key_provider())


def _route_evidence(result: Any) -> dict[str, Any]:
    metrics = result.quality_metrics
    return {
        "mode": metrics.get("execution", {}).get("execution_mode"),
        "lane": metrics.get("auto_chunk", {}).get("lane"),
        "unified": "unified_slice_activation" in metrics,
    }


# What each fixture really ran, so a case cannot pass by taking another route. The unified slice
# declines a hash column when no kernel is available, which is exactly when the code is set, so
# that fixture lands on the full-frame route and the evidence says so.
_EXPECTED_EVIDENCE = {
    "unified_declined_full_frame": {"unified": False},
    "auto_chunk": {"mode": "full_frame", "lane": "dispatcher", "unified": False},
    "sequential": {"mode": "sequential", "lane": None, "unified": False},
    "out_of_core": {"mode": "out_of_core", "lane": None, "unified": False},
}

_ROUTES = {
    "unified_declined_full_frame": _run_unified,
    "auto_chunk": _run_auto_chunk,
    "sequential": lambda tmp: _run_fk(tmp, "sequential"),
    "out_of_core": lambda tmp: _run_fk(tmp, "out_of_core"),
}


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_every_route_sets_the_field(
    route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _spy_probe(monkeypatch, _NONE_AVAILABLE)
    result = _ROUTES[route](tmp_path)
    evidence = _route_evidence(result)
    expected = _EXPECTED_EVIDENCE[route]
    if route == "unified_declined_full_frame":
        # Real admission follows the host: a built companion admits the hash column.
        expected = {"unified": native_kernel_availability().crypto}
    assert {key: evidence[key] for key in expected} == expected
    assert result.native_fallback_code == _CODE


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_every_route_stays_silent_when_a_kernel_is_available(
    route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _spy_probe(monkeypatch, _ALL_AVAILABLE)
    assert _ROUTES[route](tmp_path).native_fallback_code is None


def test_a_failing_probe_cannot_fail_a_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> KernelAvailability:
        raise RuntimeError("simulated probe failure")

    monkeypatch.setattr(_native_notice, "native_kernel_availability", boom)
    result = _run_unified(tmp_path)
    assert result.native_fallback_code is None
    assert result.outputs


# AT-3


def test_the_field_is_the_registered_reason_and_its_text_is_fixed() -> None:
    assert reasons.warning.NATIVE_COMPANION_MISSING == _CODE
    spec = reasons.find("warning", _CODE)
    assert spec is not None
    assert spec.summary == (
        "No compiled kernel ran: a native kernel this run needs is not available, "
        "so masking ran in Python."
    )
    assert "NATIVE_COMPANION_MISSING" in reasons.warning._part1.__all__


# AT-5


def test_the_field_changes_no_output_metric_or_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = {}
    for label, answer in (("missing", _NONE_AVAILABLE), ("present", _ALL_AVAILABLE)):
        _spy_probe(monkeypatch, answer)
        (tmp_path / label).mkdir()
        runs[label] = _run_unified(tmp_path / label)
    missing, present = runs["missing"], runs["present"]
    assert missing.native_fallback_code == _CODE
    assert present.native_fallback_code is None
    assert project(missing) == project(present)
    # Not compared: setting the field alone leaves equality unchanged.
    assert dataclasses.replace(present, native_fallback_code=_CODE) == present
    document = json.dumps(project(missing), default=str)
    assert _CODE not in document
    assert _CODE not in repr(missing)
    assert _CODE not in json.dumps(missing.quality_metrics, default=str)
    assert all(w.code != _CODE for w in missing.warnings)


# AT-7


def test_a_partial_companion_counts_the_kernels_the_plan_needs(tmp_path: Path) -> None:
    both = _plan(
        tmp_path,
        [support.pass_col("g"), support.hash_col("h"), _group_key("k")],
        {"g": _strings(), "h": _strings(), "k": _strings()},
    )
    assert _native_notice.native_fallback_code(both, _NO_RAW_HEX) is None


def test_group_key_alone_reports_when_only_raw_hex_is_missing(tmp_path: Path) -> None:
    plan = _plan(
        tmp_path,
        [support.pass_col("g"), _group_key("k")],
        {"g": _strings(), "k": _strings()},
    )
    assert _native_notice.native_fallback_code(plan, _NO_RAW_HEX) == _CODE


# AT-8


def test_the_code_agrees_with_the_route_summary_on_the_real_probe(tmp_path: Path) -> None:
    cfg, table = scenarios.single_table(tmp_path)
    result = run_pipeline(
        cfg,
        {"t": table},
        engine_version="nmw-e1",
        key_provider=scenarios.key_provider(),
        auto_chunk_threshold_rows=10,
        chunk_size_rows=8,
        use_byte_estimate_routing=False,
        native_threads=1,
    )
    summary = route_summary(result.quality_metrics)
    assert (result.native_fallback_code is not None) == (summary.native == "not_installed")


# AT-9


def test_generate_columns_do_not_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = pa.table({"r": _strings()})
    path = tmp_path / "m.parquet"
    pq.write_table(table, path)
    raw = {
        "version": 2,
        "global_settings": {"seed": 3},
        "sources": {"m": {"type": "file", "format": "parquet", "path": str(path)}},
        "tables": [
            {"name": "m", "columns": [support.redact_col("r")]},
            {
                "name": "g",
                "row_count": 5,
                "generate_columns": [{"name": "email", "type": "faker", "faker_type": "email"}],
            },
        ],
        "targets": {
            "m": {"type": "file", "format": "parquet", "path": str(tmp_path / "m.out.parquet")},
            "g": {"type": "file", "format": "parquet", "path": str(tmp_path / "g.out.parquet")},
        },
    }
    declare_rest(raw)
    cfg = PipelineConfig.model_validate(raw).model_dump()
    plan = compile_plan(
        cfg, profile_source(cfg, seed=0), decoy_engine_version="nmw-e1", sources=NO_SOURCES
    )
    calls = _spy_probe(monkeypatch, _NONE_AVAILABLE)
    assert _native_notice.native_fallback_code(plan) is None
    assert calls == []
