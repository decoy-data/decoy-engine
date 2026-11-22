"""NONFK-OOM S4b: the resident-fit decision for a job with no foreign keys.

AT-C1 to AT-C12, AT-C14, AT-C15, AT-C17 and AT-C18 of docs/plans/2026-11-19-nonfk-oom.md. The
host ceiling `H`, the static estimate and the probe are stubbed so each boundary of the ladder is
hit exactly; the lower bound is computed from the same table with the production function. Do not
delete a cell, skip one or loosen an equality to pass.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import errors, reasons
from decoy_engine.execution import _probe, run_pipeline
from decoy_engine.execution import out_of_core as ooc
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._mem_estimate import K_CALIBRATION_ERROR_BAND as BAND
from decoy_engine.execution.pipeline import _resident_fit as rf
from decoy_engine.execution.pipeline import lower_bound_bytes, resident_spec
from decoy_engine.profile._readers import LazySource
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _multi_table_support as mt

pytestmark = pytest.mark.filterwarnings("ignore")

ROWS = 400
CODE_FITS = reasons.route.NONFK_FULL_FRAME_FITS
CODE_PROBE = reasons.route.NONFK_FULL_FRAME_PROBE_FITS
CODE_UNVERIFIED = reasons.route.NONFK_FULL_FRAME_UNVERIFIED
CODE_REFUSED = reasons.runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED
SENTINELS = ("SENTINEL_TABLE", "SENTINEL_COLUMN", "SENTINEL_VALUE")


class _Probe:
    """Stands in for `probe_peak_bytes`: a canned result, and every call recorded."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = _probe.ProbeResult(conclusive=False, reason="stub")

    def __call__(self, config: Any, sources: Any, **kwargs: Any) -> _probe.ProbeResult:
        self.calls.append(kwargs)
        return self.result

    def measures(self, estimated: int, *, risk: bool = False) -> None:
        self.result = _probe.ProbeResult(
            conclusive=True,
            reason="measured",
            estimated_peak_bytes=estimated,
            uniqueness_risk=risk,
        )


@pytest.fixture(autouse=True)
def probe(monkeypatch: pytest.MonkeyPatch) -> _Probe:
    stub = _Probe()
    monkeypatch.setattr(_probe, "probe_peak_bytes", stub)
    return stub


def _ceiling(monkeypatch: pytest.MonkeyPatch, kill: int) -> None:
    monkeypatch.setattr(ooc, "detect_effective_memory_bytes", lambda: kill)


def _static(monkeypatch: pytest.MonkeyPatch, value: int | None) -> None:
    monkeypatch.setattr(rf, "_static_estimate", lambda ctx, names: value)


def _table(rows: int = ROWS) -> pa.Table:
    # Low cardinality: a near-unique column is a risk column, and a risk column never proves a fit.
    return pa.table(
        {"s": [f"v{i % 5}" for i in range(rows)], "n": pa.array([i % 7 for i in range(rows)])}
    )


_DIR: list[Path] = []


@pytest.fixture(autouse=True)
def _workdir(tmp_path: Path) -> None:
    _DIR[:] = [tmp_path]


def _cfg(table: pa.Table | None = None) -> dict[str, Any]:
    """The profile reads a real Parquet file; the run reads the table passed as the source."""
    path = support.write_source(table or _table(), _DIR[0] / "src.parquet")
    return support.make_cfg([support.redact_col("s"), support.pass_col("n")], path=path)


def _lb(table: pa.Table) -> int:
    return lower_bound_bytes([resident_spec(table)])


def _kill_for_admission(admission: int) -> int:
    """The smallest ceiling whose admission ceiling is `admission`."""
    kill = int(admission / rf.RESIDENT_ADMISSION_FRACTION) - 3
    while rf.admission_ceiling_bytes(kill) < admission:
        kill += 1
    assert rf.admission_ceiling_bytes(kill) == admission
    return kill


def _run(table: pa.Table, **extra: Any) -> Any:
    return support.run_full_frame(_cfg(table), table, **extra)


def _fit(result: Any) -> dict[str, Any]:
    """The verdict the latest run stored on its `RouteDecision`, as plain tokens and numbers."""
    stored = _DECISIONS[-1].resident_fit
    assert stored is not None
    return rf.resident_fit_metrics(stored)


_DECISIONS: list[Any] = []


@pytest.fixture(autouse=True)
def _decisions(monkeypatch: pytest.MonkeyPatch) -> None:
    from decoy_engine.execution import _pipeline_full_frame as full_frame

    _DECISIONS.clear()
    real = full_frame.run_full_frame_route

    def spy(ctx: Any, decision: Any, **kwargs: Any) -> Any:
        _DECISIONS.append(decision)
        return real(ctx, decision, **kwargs)

    monkeypatch.setattr(full_frame, "run_full_frame_route", spy)


def _refusal(table: pa.Table, **extra: Any) -> ExecutionError:
    with pytest.raises(ExecutionError) as caught:
        _run(table, **extra)
    return caught.value


def test_at_c1_a_small_job_fits_and_its_output_is_unchanged(probe: _Probe) -> None:
    table = _table()
    got = _run(table)
    block = _fit(got)
    assert block["verdict"] == "FIT"
    assert block["code"] == CODE_FITS
    assert set(block) == {
        "verdict",
        "code",
        "table_count",
        "estimated_bytes",
        "lower_bound_bytes",
        "admission_ceiling_bytes",
        "kill_ceiling_bytes",
    }
    assert all(type(v) is int for k, v in block.items() if k not in {"verdict", "code"})
    assert block["table_count"] == 1
    assert block["lower_bound_bytes"] == _lb(table)
    assert probe.calls == []
    forced = _run(table, execution_mode="full_frame")
    assert got.outputs[support.TABLE].equals(forced.outputs[support.TABLE])
    assert _DECISIONS[-1].resident_fit is None


@pytest.mark.parametrize(
    ("delta", "verdict", "code"),
    [
        (+1, "FIT", CODE_FITS),
        (0, "UNKNOWN", CODE_UNVERIFIED),
        (-1, "UNKNOWN", CODE_UNVERIFIED),
    ],
    ids=["lb-just-below-A", "lb-equals-A", "lb-just-above-A"],
)
def test_at_c2_admission_boundary(
    monkeypatch: pytest.MonkeyPatch, delta: int, verdict: str, code: str
) -> None:
    table = _table()
    lb = _lb(table)
    kill = _kill_for_admission(lb + delta)
    _ceiling(monkeypatch, kill)
    _static(monkeypatch, 1)
    block = _fit(_run(table))
    assert (block["verdict"], block["code"]) == (verdict, code)
    assert block["admission_ceiling_bytes"] == lb + delta
    assert block["kill_ceiling_bytes"] == kill


def test_at_c2_lb_equal_to_the_kill_ceiling_runs_and_one_byte_more_refuses(
    monkeypatch: pytest.MonkeyPatch, probe: _Probe
) -> None:
    table = _table()
    lb = _lb(table)
    _static(monkeypatch, 1)
    _ceiling(monkeypatch, lb)
    assert _fit(_run(table))["verdict"] == "UNKNOWN"
    probe.calls.clear()
    _ceiling(monkeypatch, lb - 1)
    err = _refusal(table)
    assert err.code == CODE_REFUSED
    assert err.__cause__ is None
    assert err.__context__ is None
    assert probe.calls == []


def test_at_c3_a_probe_below_the_admission_ceiling_recovers_the_job(
    monkeypatch: pytest.MonkeyPatch, probe: _Probe
) -> None:
    table = _table()
    kill = _lb(table) * 20
    admit = rf.admission_ceiling_bytes(kill)
    _ceiling(monkeypatch, kill)
    _static(monkeypatch, admit)  # over A with the band, so step 1 does not admit
    probe.measures(int(admit / (1 + BAND)) - 1)
    block = _fit(_run(table))
    assert (block["verdict"], block["code"]) == ("FIT", CODE_PROBE)
    assert len(probe.calls) == 1
    assert probe.calls[0]["risk_policy"] == "measure"
    assert probe.calls[0]["mem_cap_bytes"] == kill


def test_at_c4_probe_thresholds(monkeypatch: pytest.MonkeyPatch, probe: _Probe) -> None:
    table = _table()
    kill = _lb(table) * 20
    admit = rf.admission_ceiling_bytes(kill)
    _ceiling(monkeypatch, kill)
    _static(monkeypatch, admit)
    upper_edge = int(admit / (1 + BAND))
    refuse_above = int(kill * (1 + BAND))
    for measured, verdict in [
        (upper_edge - 1, "FIT"),
        (upper_edge + 2, "UNKNOWN"),
        (refuse_above, "UNKNOWN"),
    ]:
        probe.measures(measured)
        assert _fit(_run(table))["verdict"] == verdict, measured
    probe.measures(refuse_above + 1)
    assert _refusal(table).code == CODE_REFUSED


def test_at_c5_only_the_full_frame_table_is_priced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    columns = mt.std_columns("ns_split")
    cfg, sources = mt.build_job(
        tmp_path,
        {
            "a": (columns, mt.string_table(mt.BIG, "a")),
            "b": (columns, mt.string_table(mt.BIG, "b")),
            "c": ([support.redact_col("r")], pa.table({"r": pa.array(["x", "y", "z"])})),
        },
    )
    small = _lb(sources["c"])
    _static(monkeypatch, 1)
    _ceiling(monkeypatch, small)
    got = run_pipeline(cfg, sources=sources, **mt.kw())
    block = _fit(got)
    assert block["table_count"] == 1
    assert block["lower_bound_bytes"] == small
    assert mt.dispatched_tables(got) == ["a", "b"]
    _ceiling(monkeypatch, small - 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, sources=sources, **mt.kw())
    assert caught.value.code == CODE_REFUSED


def test_at_c6_a_refusal_opens_no_output_and_no_cast_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.declared_casting import _boundary
    from decoy_engine.execution import _chunked_output_sink as sink
    from decoy_engine.execution import _pipeline_full_frame as full_frame

    opened: list[str] = []
    for owner, name in [
        (sink.OutputPublish, "open"),
        (_boundary, "open_cast_run"),
        (full_frame, "run_full_frame_route"),
    ]:
        monkeypatch.setattr(owner, name, lambda *a, _n=name, **k: opened.append(_n))
    table = _table()
    _ceiling(monkeypatch, _lb(table) - 1)
    _static(monkeypatch, 1)
    assert _refusal(table).code == CODE_REFUSED
    assert opened == []


def test_at_c6b_a_refused_subset_job_leaves_no_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from decoy_engine.execution.pipeline import _subset_stage
    from decoy_engine.subset import sample_request

    roots: list[Path] = []
    real = _subset_stage.engine_scratch_root

    def spy(base: Any) -> Any:
        scope = real(base)

        class _Spy:
            def __enter__(self) -> Any:
                root = scope.__enter__()
                roots.append(Path(root))
                return root

            def __exit__(self, *exc: Any) -> Any:
                return scope.__exit__(*exc)

        return _Spy()

    monkeypatch.setattr(_subset_stage, "engine_scratch_root", spy)
    monkeypatch.setenv("SUB_STOP_TEST_SECRET", "ab" * 32)
    table = _table()
    cfg = _cfg(table)
    lazy = {support.TABLE: LazySource(Path(cfg["sources"][support.TABLE]["path"]))}
    _ceiling(monkeypatch, 1000)
    _static(monkeypatch, 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(
            cfg,
            lazy,
            engine_version="t",
            auto_chunk=False,
            subset_request=sample_request(cfg, rows=50),
        )
    assert caught.value.code == CODE_REFUSED
    assert roots, "the subset stage never opened its scratch root"
    assert not any(root.exists() for root in roots)


def test_at_c7_the_refusal_and_the_block_name_no_table_column_or_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {"SENTINEL_COLUMN": [f"SENTINEL_VALUE{i}" for i in range(ROWS)], "n": list(range(ROWS))}
    )
    path = support.write_source(table, _DIR[0] / "sent.parquet")
    cfg = support.make_cfg(
        [support.redact_col("SENTINEL_COLUMN"), support.pass_col("n")], path=path
    )
    cfg["tables"][0]["name"] = "SENTINEL_TABLE"
    cfg["sources"]["SENTINEL_TABLE"] = cfg["sources"].pop(support.TABLE)
    cfg["targets"]["SENTINEL_TABLE"] = cfg["targets"].pop(support.TABLE)
    kwargs = support.run_kwargs(auto_chunk=False)
    _static(monkeypatch, 1)
    _ceiling(monkeypatch, _lb(table) * 20)
    ok = run_pipeline(cfg, sources={"SENTINEL_TABLE": table}, **kwargs)
    _ceiling(monkeypatch, _lb(table) - 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, sources={"SENTINEL_TABLE": table}, **kwargs)
    rendered = f"{caught.value} {_fit(ok)}"
    assert not any(s in rendered for s in SENTINELS)


def test_at_c8_auto_chunk_off_on_a_too_large_table_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = _table()
    _static(monkeypatch, 1)
    _ceiling(monkeypatch, _lb(table) - 1)
    assert _refusal(table).code == CODE_REFUSED


def test_at_c9_the_compiler_reads_the_stored_verdict_and_never_gathers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored refusal makes the compiler raise the shared builder's code; it touches neither
    the host ceiling nor the probe."""
    from decoy_engine.execution.physical import _compiler
    from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs

    table = _table()
    inputs = capture_physical_plan_inputs(
        _cfg(table), {support.TABLE: table}, engine_version=support.ENGINE_VERSION
    )
    refused = rf.ResidentFit("INSUFFICIENT", CODE_REFUSED, 1, 10, 10, 5, 8)
    monkeypatch.setattr(ooc, "detect_effective_memory_bytes", lambda: pytest.fail("host read"))
    monkeypatch.setattr(_probe, "probe_peak_bytes", lambda *a, **k: pytest.fail("probe"))
    with pytest.raises(ExecutionError) as caught:
        _compiler.compile_physical_plan(dataclasses.replace(inputs, resident_fit=refused))
    assert caught.value.code == CODE_REFUSED
    fits = dataclasses.replace(refused, verdict="FIT", code=CODE_FITS)
    stored = _compiler.compile_physical_plan(dataclasses.replace(inputs, resident_fit=fits))
    assert stored.plan_hash != _compiler.compile_physical_plan(inputs).plan_hash


def test_at_c10_the_code_is_a_capacity_code() -> None:
    assert CODE_REFUSED in errors.CAPACITY_REASON_CODES
    assert CODE_REFUSED not in errors.CAPACITY_EXCLUSIONS


def test_at_c11_a_job_with_a_foreign_key_is_not_priced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.unit.execution import _subset_run_support as sub

    monkeypatch.setenv("SUB_STOP_TEST_SECRET", "ab" * 32)
    calls: list[str] = []
    monkeypatch.setattr(rf, "gather_resident_fit", lambda *a, **k: calls.append("gather"))
    cfg, data, _lazy = sub.job(tmp_path)
    cfg.pop("subset", None)
    _ceiling(monkeypatch, 1)
    run_pipeline(cfg, sources=data, **support.run_kwargs())
    assert calls == []
    assert all(d.resident_fit is None for d in _DECISIONS)


def test_at_c12_a_forced_full_frame_run_is_never_priced(
    monkeypatch: pytest.MonkeyPatch, probe: _Probe
) -> None:
    _ceiling(monkeypatch, 1)
    _run(_table(), execution_mode="full_frame")
    assert _DECISIONS[-1].resident_fit is None
    assert probe.calls == []


def test_at_c14_strict_file_access_skips_the_probe(
    monkeypatch: pytest.MonkeyPatch, probe: _Probe
) -> None:
    from decoy_engine import fileaccess

    table = _table()
    kill = _lb(table) * 20
    _ceiling(monkeypatch, kill)
    _static(monkeypatch, rf.admission_ceiling_bytes(kill))
    monkeypatch.setattr(fileaccess, "is_ambient", lambda policy=None: False)
    block = _fit(_run(table))
    assert (block["verdict"], block["code"]) == ("UNKNOWN", CODE_UNVERIFIED)
    assert probe.calls == []


def test_at_c15_through_the_isolated_entry_the_refusal_comes_back_crashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.execution import run_pipeline_isolated

    table = _table()
    _static(monkeypatch, 1)
    _ceiling(monkeypatch, _lb(table) - 1)
    result = run_pipeline_isolated(
        _cfg(table),
        {support.TABLE: table},
        isolate=False,
        **support.run_kwargs(auto_chunk=False),
    )
    assert result.outcome == "crashed"
    assert not result.outputs


def test_at_c17_risk_columns_never_fit_and_refuse_only_beyond_the_band(
    monkeypatch: pytest.MonkeyPatch, probe: _Probe
) -> None:
    table = pa.table({"id": [f"id{i}" for i in range(30_000)]})
    path = support.write_source(table, _DIR[0] / "ids.parquet")
    cfg = support.make_cfg([support.hash_col("id")], path=path)
    kill = _lb(table) * 20
    admit = rf.admission_ceiling_bytes(kill)
    _ceiling(monkeypatch, kill)
    _static(monkeypatch, 1)
    kwargs = support.run_kwargs(auto_chunk=False)
    for measured in (admit // 4, kill, int(kill * (1 + BAND))):
        probe.measures(measured)
        block = _fit(run_pipeline(cfg, sources={support.TABLE: table}, **kwargs))
        assert (block["verdict"], block["code"]) == ("UNKNOWN", CODE_UNVERIFIED), measured
    assert probe.calls[-1]["risk_policy"] == "measure"
    assert probe.calls[-1]["uniqueness_risk_columns"] == ((support.TABLE, "id"),)
    probe.measures(int(kill * (1 + BAND)) + 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, sources={support.TABLE: table}, **kwargs)
    assert caught.value.code == CODE_REFUSED


def test_at_c17_an_all_null_column_is_not_a_risk() -> None:
    risky = _probe.sampled_uniqueness_risk(
        {"t": 30_000}, {("t", "c"): 0, ("t", "u"): 10_000}, {("t", "c"): 0, ("t", "u"): 10_000}
    )
    assert risky == (("t", "u"),)


def test_at_c18_the_fk_caller_still_skips_risk_columns() -> None:
    from decoy_engine.execution import _pipeline_routing_signals as signals

    assert "risk_policy" not in inspect.getsource(signals.resolve_probe_recovery)
    assert 'risk_policy: Literal["skip", "measure"] = "skip"' in inspect.getsource(_probe)
    assert _probe.ProbeResult(conclusive=False, reason="x").uniqueness_risk is False
