"""SCAN-ML M4 in `run_pipeline`: AT-M4e (route parity of the report) and AT-M4g (the block).

AT-M4e: the full-frame route and `run_pipeline`'s resident auto-chunk lane give the same report,
model findings included (M-M4e: skip the model passes on the chunked route).
AT-M4g: under `ner_findings: fail` an NER `fail` finding, or an NER pass that raises, makes
`run_pipeline` raise `PostScanBlockedError` carrying the report; `warn` returns. The error's text
is the registry summary and its chain is empty (M-M4g, M-M4g2, M-M4g3).

Model proofs use the real spaCy model and the real classifier pack. The last two tests are routing
unit tests with a fake NER detector, so the block predicate is also exercised where spaCy is absent.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig
from tests._ner import needs_ner
from tests.unit.detection_verification import _scanml_m4_support as s

_V = "scanml-m4"
_FINDINGS = "decoy_engine.verification.postmask._model_findings"
ROWS = 400


def _summary() -> str:
    spec = reasons.find("post_scan", "ner_blocked")
    assert spec is not None, "post_scan.ner_blocked is not registered"
    return spec.summary


def _source(every: int = 2) -> pa.Table:
    # An email in every fifth note gives `text_redact` something to change, so the policy check
    # passes and an NER row is the only blocking finding.
    notes = [
        f"{cell} Reply to user{i}@example.com." if i % 5 == 0 else cell
        for i, cell in enumerate(s.notes_column(every, n=ROWS))
    ]
    frame = pd.DataFrame(
        {
            "notes": notes,
            "email": [f"user{i}@example.com" for i in range(ROWS)],
            "code": [f"c{i}" for i in range(ROWS)],
        }
    )
    return pa.Table.from_pandas(frame, preserve_index=False)


def _cfg(
    tmp_path: Path,
    table: pa.Table,
    post_scan: dict[str, Any],
    *,
    extra_columns: tuple[dict[str, Any], ...] = (),
    quarantine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = tmp_path / "t.csv"
    table.to_pandas().to_csv(path, index=False)
    raw = {
        "version": 2,
        "global_settings": {"seed": 11},
        "post_scan": {"integrity": True, **post_scan},
        "sources": {"t": {"type": "file", "format": "csv", "has_header": True, "path": str(path)}},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "notes", "strategy": "text_redact"},
                    {"name": "email", "strategy": "passthrough"},
                    {"name": "code", "strategy": "redact"},
                    *extra_columns,
                ],
            }
        ],
        "targets": {"t": {"type": "file", "format": "csv", "path": str(tmp_path / "o.csv")}},
    }
    if quarantine is not None:
        raw["quarantine"] = quarantine
    return PipelineConfig.model_validate(raw).model_dump()


def _run(cfg: dict[str, Any], table: pa.Table, **kwargs: Any) -> Any:
    from decoy_engine.execution import run_pipeline

    return run_pipeline(cfg, sources={"t": table}, engine_version=_V, **kwargs)


def _routes(cfg: dict[str, Any], table: pa.Table) -> tuple[dict[str, Any], dict[str, Any]]:
    full = _run(cfg, table, auto_chunk=False)
    chunked = _run(cfg, table, auto_chunk_threshold_rows=1, chunk_size_rows=64)
    assert "auto_chunk" in chunked.quality_metrics, "the auto-chunk lane did not run"
    assert chunked.quality_metrics["auto_chunk"]["output"]["mode"] == "resident"
    assert full.quality_metrics["auto_chunk"]["mode"] == "full_frame"
    assert chunked.quality_metrics["auto_chunk"]["mode"] != "full_frame"
    assert chunked.outputs["t"].equals(full.outputs["t"])
    reports = []
    for result in (full, chunked):
        report = dict(result.quality_metrics["post_scan_integrity"])
        report.pop("generated_at")
        reports.append(report)
    return reports[0], reports[1]


def test_classifier_report_is_the_same_on_full_frame_and_chunked_routes(tmp_path: Path) -> None:
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "classifier"]})
    full, chunked = _routes(cfg, table)
    assert s.rows(full, "classifier"), full["residual_pii"]
    assert full == chunked


def test_classifier_finding_reports_v3_with_a_null_match_rate(tmp_path: Path) -> None:
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "classifier"]})
    full, _ = _routes(cfg, table)
    assert full["schema_version"] == "post-scan-integrity/v3"
    rows = s.rows(full, "classifier")
    assert rows and all(r["match_rate"] is None and r["band"] for r in rows)


@needs_ner
def test_ner_report_is_the_same_on_full_frame_and_chunked_routes(tmp_path: Path) -> None:
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "classifier", "ner"]})
    full, chunked = _routes(cfg, table)
    assert s.rows(full, "ner", column="notes", severity="warning"), full["residual_pii"]
    assert full == chunked


def _assert_safe(err: BaseException) -> None:
    assert str(err) == _summary()
    assert getattr(err, "message", None) == _summary()
    assert err.__cause__ is None and err.__context__ is None
    assert getattr(err, "reason", None) == "post_scan.ner_blocked"
    assert [c.code for c in err.verdict.codes] == ["ner_blocked"]
    clone = pickle.loads(pickle.dumps(err))  # noqa: S301 - our own bytes
    assert type(clone) is type(err) and str(clone) == str(err)
    assert clone.report == err.report


@needs_ner
def test_an_ner_fail_finding_blocks_the_run(tmp_path: Path) -> None:
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "ner"], "ner_findings": "fail"})
    with pytest.raises(s.blocked_error()) as caught:
        _run(cfg, table)
    err = caught.value
    (finding,) = s.rows(err.report, "ner", column="notes", detector_id="person_name")
    assert (finding["severity"], finding["promoted"]) == ("fail", True)
    assert err.report["schema_version"] == "post-scan-integrity/v3"
    _assert_safe(err)


@needs_ner
def test_warn_mode_returns_with_the_finding_in_the_report(tmp_path: Path) -> None:
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "ner"]})
    result = _run(cfg, table)
    report = result.quality_metrics["post_scan_integrity"]
    (finding,) = s.rows(report, "ner", column="notes", detector_id="person_name")
    assert finding["severity"] == "warning"


@needs_ner
def test_fail_mode_with_no_ner_finding_over_the_rate_returns(tmp_path: Path) -> None:
    table = _source(every=10)
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "ner"], "ner_findings": "fail"})
    report = _run(cfg, table).quality_metrics["post_scan_integrity"]
    (finding,) = s.rows(report, "ner", column="notes", detector_id="person_name")
    assert finding["severity"] == "info"


@needs_ner
def test_a_raising_ner_pass_blocks_and_keeps_the_regex_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    table = _source()
    warn = _cfg(tmp_path, table, {"detectors": ["regex", "ner"]})
    regex = s.rows(
        _run(warn, table, auto_chunk=False).quality_metrics["post_scan_integrity"], "regex"
    )
    assert regex, "the fixture must give a regex finding"
    mf = importlib.import_module(_FINDINGS)

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Ask Debra Archer to confirm")

    monkeypatch.setattr(mf, "ner_rates", boom)
    warn_report = _run(warn, table, auto_chunk=False).quality_metrics["post_scan_integrity"]
    assert len(s.rows(warn_report, "ner", severity="error")) == 1  # warn mode: report, no block
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "ner"], "ner_findings": "fail"})
    with pytest.raises(s.blocked_error()) as caught:
        _run(cfg, table, auto_chunk=False)
    err = caught.value
    assert s.rows(err.report, "regex") == regex
    (error,) = s.rows(err.report, "ner", severity="error")
    assert error["model"]["id"] == "en_core_web_sm"
    assert "Debra" not in repr(err.report)
    _assert_safe(err)


# -- routing unit tests (a fake NER detector; the proofs above use the real model) -------------


def _fake_ner(monkeypatch: pytest.MonkeyPatch, hit_cells: int | None) -> None:
    import importlib

    from decoy_engine.detection._ner_rate import NER_MIN_RATE, NerRate
    from decoy_engine.detection.types import ModelRef
    from decoy_engine.profiling.model_pack import DetectorSet

    mf = importlib.import_module(_FINDINGS)
    ref = ModelRef("en_core_web_sm", "3.8.0")
    monkeypatch.setattr(
        mf, "load_detectors", lambda sources, **_kw: DetectorSet(tuple(sources), None, ref)
    )
    monkeypatch.setattr(mf, "pipeline_version", lambda _model: ref.version)

    def rates(values: Any, *, model: str) -> dict[str, NerRate]:
        if hit_cells is None:
            raise RuntimeError("fake pass failure")
        return {
            "location": NerRate("location", 0, ROWS, NER_MIN_RATE),
            "person_name": NerRate("person_name", hit_cells, ROWS, NER_MIN_RATE),
        }

    monkeypatch.setattr(mf, "ner_rates", rates)


@pytest.mark.parametrize("hit_cells", [300, None], ids=["fail_finding", "pass_error"])
def test_block_predicate_routing_with_a_fake_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hit_cells: int | None
) -> None:
    import importlib.util

    assert importlib.util.find_spec(_FINDINGS) is not None, "the model findings pass is missing"
    _fake_ner(monkeypatch, hit_cells)
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "ner"], "ner_findings": "fail"})
    with pytest.raises(s.blocked_error()) as caught:
        _run(cfg, table, auto_chunk=False)
    _assert_safe(caught.value)
    warn = _cfg(tmp_path, table, {"detectors": ["regex", "ner"]})
    assert "post_scan_integrity" in _run(warn, table, auto_chunk=False).quality_metrics


@pytest.mark.parametrize("hit_cells", [300, None], ids=["fail_finding", "pass_error"])
def test_a_deferred_gate_still_blocks_under_ner_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hit_cells: int | None
) -> None:
    """A loader run defers the gate, whose column suite is then report-only. An NER block under
    `ner_findings: fail` is never report-only, so it still withholds the outputs."""
    from decoy_engine.execution import run_pipeline

    _fake_ner(monkeypatch, hit_cells)
    table = _source()

    def run(post_scan: dict[str, Any]) -> Any:
        return run_pipeline(
            _cfg(tmp_path, table, post_scan),
            sources=None,
            source_loader=lambda _name: table,
            source_loader_schemas={"t": table.schema},
            engine_version=_V,
            auto_chunk=False,
        )

    with pytest.raises(s.blocked_error()) as caught:
        run({"detectors": ["regex", "ner"], "ner_findings": "fail"})
    _assert_safe(caught.value)
    result = run({"detectors": ["regex", "ner"]})
    assert "post_scan_gate_deferred" in result.quality_metrics
    assert s.rows(result.quality_metrics["post_scan_integrity"], "ner")


def _quarantine_loader_run(tmp_path: Path, post_scan: dict[str, Any]) -> tuple[Any, Path]:
    """A loader run (deferred gate) whose `age` column quarantines one row."""
    from decoy_engine.execution import run_pipeline

    ages = ["badX" if i == 3 else str(10 + i % 70) for i in range(ROWS)]
    table = _source().append_column("age", pa.array(ages, type=pa.string()))
    qpath = tmp_path / "q.jsonl"
    quarantine = {"enabled": True, "output_path": str(qpath), "triggers": ["format_error"]}
    age = {"name": "age", "strategy": "bucketize", "provider_config": {"width": 10}}
    cfg = _cfg(tmp_path, table, post_scan, extra_columns=(age,), quarantine=quarantine)

    def run() -> Any:
        return run_pipeline(
            cfg,
            sources=None,
            source_loader=lambda _name: table,
            source_loader_schemas={"t": table.schema},
            engine_version=_V,
            auto_chunk=False,
        )

    return run, qpath


@pytest.mark.parametrize("hit_cells", [300, None], ids=["fail_finding", "pass_error"])
def test_a_deferred_ner_block_leaves_no_quarantine_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hit_cells: int | None
) -> None:
    """The quarantine file carries source row values. A deferred gate under `ner_findings: fail`
    can still block, so the write waits for its check: a blocked run leaves no file, and a run the
    same check passes publishes it."""
    run, qpath = _quarantine_loader_run(
        tmp_path, {"detectors": ["regex", "ner"], "ner_findings": "fail"}
    )
    _fake_ner(monkeypatch, hit_cells)
    with pytest.raises(s.blocked_error()) as caught:
        run()
    _assert_safe(caught.value)
    assert not qpath.exists()
    _fake_ner(monkeypatch, 0)
    result = run()
    assert "post_scan_gate_deferred" in result.quality_metrics
    assert result.quality_metrics["quarantine"]["total_quarantined"] == 1
    assert qpath.exists()


@pytest.mark.parametrize("ner_findings", ["fail", "warn"])
def test_only_a_deferred_ner_fail_holds_the_quarantine_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ner_findings: str
) -> None:
    """The hold is for the NER block alone: under `warn` a deferred check never blocks, so the
    file is written before the check runs, as on any other deferred run."""
    from decoy_engine.execution.pipeline import _post_scan

    run, qpath = _quarantine_loader_run(
        tmp_path, {"detectors": ["regex", "ner"], "ner_findings": ner_findings}
    )
    _fake_ner(monkeypatch, 0)
    seen: list[bool] = []
    real = _post_scan.run_post_mask

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(qpath.exists())
        return real(*args, **kwargs)

    monkeypatch.setattr(_post_scan, "run_post_mask", spy)
    run()
    assert seen == [ner_findings == "warn"], "the write precedes a check that cannot block"
    assert qpath.exists()


def test_a_regex_fail_alone_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The NER enforcement adds nothing for a regex `fail`: the report-only check of a deferred
    gate (where M4's raise is the only enforcement) returns, and a gate that judges the run blocks
    with the regex code alone, never `ner_blocked`."""
    import inspect

    from decoy_engine.execution.pipeline._post_scan import PostScanGate

    assert "detectors" in inspect.signature(PostScanGate).parameters, "no detectors are passed in"
    _fake_ner(monkeypatch, 0)
    import importlib

    mf = importlib.import_module(_FINDINGS)
    table = pa.table({"email": [f"user{i}@example.com" for i in range(ROWS)]})
    cfg = s.config(
        [s.table_config("t", [])], post_scan={"detectors": ["regex", "ner"], "ner_findings": "fail"}
    )
    detectors = mf.load_detectors(("regex", "ner"), ner_model="en_core_web_sm")
    deferred = PostScanGate(cfg, detectors=detectors, deferred=True)
    deferred.run_resident({"t": table}, {"t": table}, {"t": "mask"})
    report = deferred.report
    assert report is not None
    assert s.rows(report, "regex", column="email", severity="fail"), report["residual_pii"]
    assert not s.rows(report, "ner")
    with pytest.raises(s.blocked_error()) as caught:
        PostScanGate(cfg, detectors=detectors).run_resident(
            {"t": table}, {"t": table}, {"t": "mask"}
        )
    assert [c.code for c in caught.value.verdict.codes] == ["finding_blocked"]


def test_the_run_context_never_shows_its_detector_set(tmp_path: Path) -> None:
    """The loaded set rides on the run context only: out of its repr and equality, out of the
    result, and its own repr carries ids and versions, never the loaded pack."""
    import dataclasses
    import json

    from decoy_engine.execution._pipeline_context import PipelineRunContext

    (spec,) = [f for f in dataclasses.fields(PipelineRunContext) if f.name == "post_scan_detectors"]
    assert (spec.repr, spec.compare) == (False, False)
    detectors = s.detector_set("classifier")
    assert "manifest" not in repr(detectors) and "clf" not in repr(detectors)
    table = _source()
    cfg = _cfg(tmp_path, table, {"detectors": ["regex", "classifier"]})
    result = _run(cfg, table, auto_chunk=False)
    dumped = json.dumps(result.quality_metrics, default=repr)
    assert "DetectorSet" not in dumped and "classifier_pack" not in dumped
    assert "DetectorSet" not in repr(result)
