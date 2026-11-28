"""The gate fails closed when a check cannot run (G8-S1 AT-7, AT-8 and AT-14).

A conversion the deferred gate cannot make, a column comparison that raises, and an invalid
relationship each reach a blocking `check_error` or a coded error, never a clean report or a
value-bearing message. All values are synthetic."""

from __future__ import annotations

import dataclasses
import functools
import importlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import reasons, run_pipeline
from decoy_engine._execution_error import ExecutionError
from decoy_engine.config import PipelineConfig, PipelineConfigError
from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
from decoy_engine.execution.pipeline.post_scan import PostScanGate
from decoy_engine.execution.pipeline.post_scan import _gate as _post_scan
from decoy_engine.verification.postmask import (
    SCHEMA_VERSION,
    PostScanBlockedError,
    _column_facts,
    post_scan_verdict,
    raise_if_ner_blocked,
)
from decoy_engine.verification.postmask.types import ResidualPIIFinding, Severity

MARK = "MARK-c41d"
ROWS = 6
EMAILS = [f"user{i}@realmail.com" for i in range(ROWS)]
HASHED = [f"h{i:08x}" for i in range(ROWS)]
CONTACT = [f"reach{i}@contactmail.com" for i in range(ROWS)]
KINDS = {"t": "mask"}
_FINDINGS = "decoy_engine.verification.postmask._model_findings"


def _cfg(post_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": 2,
        "tables": [{"name": "t", "columns": [{"name": "email", "strategy": "hash"}]}],
        "post_scan": {"integrity": True, **(post_scan or {})},
    }


def _ner(mode: str) -> dict[str, Any]:
    return {"detectors": ["regex", "ner"], "ner_findings": mode}


def _outcome(call: Callable[[], Any]) -> BaseException | None:
    """What `call` raised, so a wrong outcome fails an assertion rather than escaping."""
    try:
        call()
    except Exception as exc:  # the test inspects whatever the gate raised
        return exc
    return None


def _assert_bare_block(outcome: BaseException | None) -> PostScanBlockedError:
    assert isinstance(outcome, PostScanBlockedError)
    assert outcome.__cause__ is None and outcome.__context__ is None
    assert MARK not in str(outcome)
    return outcome


def _codes(report: dict[str, Any] | None, ner_findings: str = "warn") -> list[str]:
    assert report is not None
    return [c.code for c in post_scan_verdict(report, ner_findings=ner_findings).codes]


def _value_free(*surfaces: Any) -> None:
    for surface in surfaces:
        text = repr(surface)
        assert MARK not in text
        assert "realmail" not in text and "contactmail" not in text


@contextmanager
def _bound(gate: PostScanGate) -> Iterator[PostScanGate]:
    token = _post_scan._ACTIVE.set(gate)
    try:
        yield gate
    finally:
        _post_scan._ACTIVE.reset(token)


def _contact_fault(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the identity comparison raise for the `contact` batch only (found by its source
    fixture), with a value-bearing message, and delegate every other call."""
    fired: list[str] = []
    real = _column_facts.identity_facts

    def compare(src: Any, out: Any) -> Any:
        if CONTACT[0] in set(src.tolist()):
            fired.append("contact")
            raise RuntimeError(f"cannot compare {CONTACT[0]} {MARK}")
        return real(src, out)

    monkeypatch.setattr(_column_facts, "identity_facts", compare)
    return fired


def _fake_ner(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[int]]:
    """A deterministic NER pass that finds nothing; returns its detectors and its call log."""
    from decoy_engine.detection._ner_rate import NER_MIN_RATES, NerRate
    from decoy_engine.detection.types import ModelRef
    from decoy_engine.profiling.model_pack import DetectorSet

    mf = importlib.import_module(_FINDINGS)
    ref = ModelRef("en_core_web_sm", "3.8.0")
    monkeypatch.setattr(
        mf, "load_detectors", lambda sources, **_kw: DetectorSet(tuple(sources), None, ref)
    )
    monkeypatch.setattr(mf, "pipeline_version", lambda _model: ref.version)
    calls: list[int] = []

    def rates(values: Any, *, model: str) -> dict[str, NerRate]:
        calls.append(len(values))
        floor = NER_MIN_RATES["en_core_web_sm"]
        return {"person_name": NerRate("person_name", 0, len(values), floor)}

    monkeypatch.setattr(mf, "ner_rates", rates)
    return mf.load_detectors(("regex", "ner"), ner_model="en_core_web_sm"), calls


def _invalid_text(cells: list[bytes]) -> pa.Array:
    """A string array whose first cell is not UTF-8: Arrow refuses to convert it."""
    offsets = np.cumsum([0, *map(len, cells)]).astype(np.int32)
    buffers = [None, pa.py_buffer(offsets.tobytes()), pa.py_buffer(b"".join(cells))]
    return pa.Array.from_buffers(pa.string(), len(cells), buffers)


def _unconvertible() -> tuple[pa.Table, pa.Table]:
    notes = [b"ok\xff" + MARK.encode(), *(f"n{i}".encode() for i in range(1, ROWS))]
    source = pa.table({"email": EMAILS, "note": [f"n{i}" for i in range(ROWS)]})
    output = pa.table({"email": HASHED, "note": _invalid_text(notes)})
    return source, output


# ----- AT-14 (a): a conversion the deferred gate cannot make blocks -----------------------------
# Since #799 the suite's input conversion fails with its own code, which passes through the gate
# under either NER mode: the run stops on a coded, value-free error instead of a report.


def _assert_not_inspectable(gate: PostScanGate, outcome: BaseException | None) -> None:
    assert isinstance(outcome, ExecutionError)
    assert outcome.code == reasons.runtime.POST_SCAN_COLUMN_NOT_INSPECTABLE
    assert "'note'" in str(outcome)
    # Never a clean pass: the gate holds no verdict that lets the run publish.
    assert gate.verdict is None or gate.verdict.blocking


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_at14a_a_deferred_conversion_failure_is_a_coded_stop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    detectors, _ = _fake_ner(monkeypatch)
    source, output = _unconvertible()
    gate = PostScanGate(_cfg(_ner(mode)), detectors=detectors, deferred=True)
    with caplog.at_level(logging.DEBUG):
        outcome = _outcome(lambda: gate.run_resident({"t": output}, {"t": source}, KINDS))
    _assert_not_inspectable(gate, outcome)
    _value_free(gate.report, outcome, caplog.text)


def test_at14c_a_required_gate_stops_on_the_same_conversion_failure() -> None:
    source, output = _unconvertible()
    gate = PostScanGate(_cfg())
    outcome = _outcome(lambda: gate.run_resident({"t": output}, {"t": source}, KINDS))
    _assert_not_inspectable(gate, outcome)
    _value_free(gate.report, outcome)


# ----- AT-14 (b): a residual comparison error under a deferred gate -----------------------------


def _contact_tables() -> tuple[pa.Table, pa.Table]:
    return (
        pa.table({"email": EMAILS, "contact": CONTACT}),
        pa.table({"email": HASHED, "contact": CONTACT}),
    )


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_at14b_a_residual_comparison_error_holds_a_deferred_publication_under_fail(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    detectors, ner_calls = _fake_ner(monkeypatch)
    fired = _contact_fault(monkeypatch)
    source, output = _contact_tables()
    gate = PostScanGate(_cfg(_ner(mode)), detectors=detectors, deferred=True)
    published: list[str] = []
    ctx = SimpleNamespace(caller_sources={"t": source}, table_kinds=KINDS)
    result = SimpleNamespace(outputs={"t": output}, quality_metrics={}, warnings=())
    with _bound(gate):
        _post_scan.publish_after_gate(lambda: published.append("t"))
        held = len(gate._held)
        outcome = _outcome(lambda: _post_scan.settle(gate, ctx, result))  # type: ignore[arg-type]
    assert ner_calls and fired == ["contact"]
    report = gate.report
    assert report is not None and report.get("pass_failed_with") is None
    (error,) = [f for f in report["residual_pii"] if f["severity"] == "error"]
    assert error["column"] == "contact"
    assert _codes(report, mode) == ["check_error"]
    if mode == "fail":
        assert held == 1
        _assert_bare_block(outcome)
        assert published == []
    else:
        assert outcome is None
        assert published == ["t"]
        assert result.quality_metrics["post_scan_integrity"] is report
    _value_free(report, outcome)


def _residual(severity: Severity) -> dict[str, Any]:
    row = ResidualPIIFinding("t", "contact", "email", match_rate=1.0, severity=severity)
    return {"schema_version": SCHEMA_VERSION, "residual_pii": [dataclasses.asdict(row)]}


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_at14b_the_deferred_predicate_blocks_a_check_error_only_under_fail(mode: str) -> None:
    failed_pass = {"schema_version": SCHEMA_VERSION, "pass_failed_with": "RuntimeError"}
    for report in (_residual("error"), failed_pass):
        outcome = _outcome(functools.partial(raise_if_ner_blocked, report, ner_findings=mode))
        if mode == "fail":
            _assert_bare_block(outcome)
        else:
            assert outcome is None
    # A regex finding stays report-only on a deferred gate in either mode.
    blocked = _residual("fail")
    assert _codes(blocked) == ["finding_blocked"]
    assert _outcome(lambda: raise_if_ner_blocked(blocked, ner_findings=mode)) is None


# ----- AT-14 (d): nullable integers reach the suite exactly -------------------------------------

SSNS = [123456701 + i for i in range(75)]


def _ssn_tables() -> tuple[pa.Table, pa.Table]:
    ssn = pa.array([*SSNS, None], type=pa.int64())
    emails = [f"user{i}@realmail.com" for i in range(76)]
    hashed = [f"h{i:08x}" for i in range(76)]
    return pa.table({"email": emails, "ssn": ssn}), pa.table({"email": hashed, "ssn": ssn})


def _suite_dtypes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    real = _post_scan.run_post_mask

    def spy(sources: Any, outputs: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append((str(sources["t"]["ssn"].dtype), str(outputs["t"]["ssn"].dtype)))
        return real(sources, outputs, **kwargs)

    monkeypatch.setattr(_post_scan, "run_post_mask", spy)
    return seen


def _ssn_row(report: dict[str, Any] | None) -> dict[str, Any]:
    assert report is not None
    (row,) = [f for f in report["residual_pii"] if f["column"] == "ssn"]
    assert row["severity"] == "fail" and row["source_identity_rate"] == 1.0
    return row


def test_at14d_a_nullable_int_ssn_blocks_on_the_required_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _suite_dtypes(monkeypatch)
    source, output = _ssn_tables()
    gate = PostScanGate(_cfg())
    block = _assert_bare_block(
        _outcome(lambda: gate.run_resident({"t": output}, {"t": source}, KINDS))
    )
    _ssn_row(block.report)
    assert _codes(block.report) == ["finding_blocked"]
    assert seen == [("Int64", "Int64")]


def test_at14d_a_nullable_int_ssn_blocks_the_staged_commit(tmp_path: Path) -> None:
    source, output = _ssn_tables()
    out = tmp_path / "published"
    sink = ParquetTransactionalSink(out)
    sink.write("t", output)
    gate = PostScanGate(_cfg(), sources={"t": source})
    block = _assert_bare_block(_outcome(lambda: gate.before_commit(sink)))
    _ssn_row(block.report)
    assert _codes(block.report) == ["finding_blocked"]
    sink.abort()
    assert not out.exists()


def test_at14d_a_deferred_warn_gate_records_the_same_finding_and_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _suite_dtypes(monkeypatch)
    source, output = _ssn_tables()
    gate = PostScanGate(_cfg(), deferred=True)
    assert _outcome(lambda: gate.run_resident({"t": output}, {"t": source}, KINDS)) is None
    _ssn_row(gate.report)
    assert gate.report is not None and gate.verdict is not None
    assert gate.report["verdict"] == gate.verdict.as_dict()
    assert _codes(gate.report) == ["finding_blocked"]
    assert seen == [("Int64", "Int64")]


# ----- AT-8: an invalid relationship raises its own coded error ---------------------------------

BAD_REL = {
    "parent": {"table": "p", "columns": ["id"]},
    "children": [{"table": "c", "columns": ["pid"]}],
    "orphan_policy": f"keep-{MARK}",
}


def _parse_errors(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    raised: list[BaseException] = []
    real = _post_scan.parse_relationship_config

    def parse(raw: Any, *, prefix: str) -> Any:
        try:
            return real(raw, prefix=prefix)
        except Exception as exc:
            raised.append(exc)
            raise

    monkeypatch.setattr(_post_scan, "parse_relationship_config", parse)
    return raised


QUARANTINE_ROWS = pa.table({"id": ["a"]})
CALLS: dict[str, Callable[[PostScanGate], Any]] = {
    "tee_reader": lambda gate: gate.tee_reader(),
    "note_quarantined": lambda gate: gate.note_quarantined("p", QUARANTINE_ROWS, {0}),
    "run_resident": lambda gate: gate.run_resident(
        {"p": QUARANTINE_ROWS, "c": pa.table({"pid": ["a"]})},
        {"p": QUARANTINE_ROWS, "c": pa.table({"pid": ["a"]})},
        {"p": "mask", "c": "mask"},
    ),
}


@pytest.mark.parametrize("call", list(CALLS))
def test_at8_an_invalid_relationship_raises_the_same_value_free_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, call: str
) -> None:
    raised = _parse_errors(monkeypatch)
    gate = PostScanGate({"relationships": [BAD_REL]})
    with caplog.at_level(logging.DEBUG), pytest.raises(PipelineConfigError) as info:
        CALLS[call](gate)
    assert raised and info.value is raised[-1]
    for surface in (info.value, info.value.__context__, info.value.__cause__):
        assert MARK not in str(surface)
    assert MARK not in caplog.text
    assert gate.report is None  # nothing judged, so nothing was published


# ----- AT-7: a column comparison error withholds a real pipeline run ----------------------------


def _pipeline(tmp_path: Path) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    frame = pd.DataFrame({"email": EMAILS, "contact": CONTACT})
    src = tmp_path / "c.csv"
    frame.to_csv(src, index=False)
    raw = {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {"t": {"type": "file", "format": "csv", "has_header": True, "path": str(src)}},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "email", "strategy": "hash", "namespace": "e"},
                    # A real run declares every column, and an unwritten passthrough is exempt
                    # from the comparison, so `contact` gets a mask whose output still matches.
                    {
                        "name": "contact",
                        "strategy": "faker",
                        "provider": "person_email",
                        "deterministic": True,
                        "namespace": "ns_contact",
                    },
                ],
            }
        ],
        "targets": {"t": {"type": "file", "format": "csv", "path": str(tmp_path / "o.csv")}},
        "post_scan": {"integrity": True},
    }
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return PipelineConfig.model_validate(raw).model_dump(), {"t": table}


def test_at7_a_column_comparison_error_withholds_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fired = _contact_fault(monkeypatch)
    cfg, sources = _pipeline(tmp_path)
    out = tmp_path / "sink"
    with caplog.at_level(logging.DEBUG):
        outcome = _outcome(
            lambda: run_pipeline(
                cfg, sources=sources, engine_version="g8-at7", sink=ParquetTransactionalSink(out)
            )
        )
    assert fired == ["contact"]
    block = _assert_bare_block(outcome)
    report = block.report
    errors = [
        (section, f)
        for section in ("residual_pii", "policy_validation", "fk_preservation")
        for f in report.get(section) or []
        if f.get("severity") == "error"
    ]
    # `contact` has a policy entry (see `_pipeline`), so its policy check reports the same
    # comparison failure; no other column or section does.
    assert [(s, f["column"], f.get("detector_id")) for s, f in errors] == [
        ("residual_pii", "contact", "email"),
        ("policy_validation", "contact", None),
    ]
    assert report["error_count"] == 2
    assert _codes(report) == ["check_error"]
    assert not out.exists()
    assert not Path(cfg["targets"]["t"]["path"]).exists()
    _value_free(report, str(block), caplog.text)


def test_at7_a_residual_comparison_error_alone_withholds_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The policy check is silenced, so the residual error is the only one in the report and
    the block cannot come from the policy error."""
    from decoy_engine.verification.postmask import runner as runner_module

    monkeypatch.setattr(runner_module, "check_policy_validation", lambda *a, **k: [])
    fired = _contact_fault(monkeypatch)
    cfg, sources = _pipeline(tmp_path)
    out = tmp_path / "sink"
    outcome = _outcome(
        lambda: run_pipeline(
            cfg, sources=sources, engine_version="g8-at7b", sink=ParquetTransactionalSink(out)
        )
    )
    assert fired == ["contact"]
    report = _assert_bare_block(outcome).report
    errors = [
        (section, f["column"])
        for section in ("residual_pii", "policy_validation", "fk_preservation")
        for f in report.get(section) or []
        if f.get("severity") == "error"
    ]
    assert errors == [("residual_pii", "contact")]
    assert report["error_count"] == 1
    assert _codes(report) == ["check_error"]
    assert not out.exists()
