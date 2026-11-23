"""PRE-SCAN-RUN E1: the presence switch, `on_findings`, and what the plan hash keeps."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import decoy_engine.config as config_pkg
from decoy_engine import reasons
from decoy_engine.config import PipelineConfig, pre_scan_requested
from decoy_engine.plan._compile import _hash_config

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BASELINE = json.loads((FIXTURES / "f06" / "legacy-compat-baseline.json").read_text())
LEGACY_RAW: dict[str, Any] = {
    **BASELINE["raw_config"],
    "sources": {"p": {**BASELINE["raw_config"]["sources"]["p"], "has_header": True}},
}


def _raw(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    raw = copy.deepcopy(LEGACY_RAW)
    (tmp_path / "p.csv").write_text("id,age,note\n1,42,a\n2,7,b\n3,13,c\n")
    raw["sources"]["p"]["path"] = str(tmp_path / "p.csv")
    raw.update(extra)
    return raw


def _hash(tmp_path: Path, **extra: Any) -> str:
    # The hash reads the config alone. E3 refuses this undeclared bucketize column at compile.
    return _hash_config(PipelineConfig.model_validate(_raw(tmp_path, **extra)).model_dump())


def test_e1_t1_a_written_default_block_survives_dump_and_revalidation() -> None:
    raw = copy.deepcopy(LEGACY_RAW)
    written = PipelineConfig.model_validate({**raw, "pre_scan": {}}).model_dump()
    assert written["pre_scan"] == {"detectors": ("regex",)}
    again = PipelineConfig.model_validate(written)
    assert "pre_scan" in again.model_fields_set
    assert again.model_dump() == written
    assert pre_scan_requested(written)


def test_e1_t1_an_unwritten_block_is_dropped_and_the_dump_is_unchanged() -> None:
    dump = PipelineConfig.model_validate(copy.deepcopy(LEGACY_RAW)).model_dump()
    assert "pre_scan" not in dump
    assert not pre_scan_requested(dump)
    # Same dump as before this change: no new key reaches a config that never wrote the block.
    cfg = copy.deepcopy(dump)
    del cfg["sources"]["p"]["has_header"]  # the frozen baseline predates the csv has_header key
    legacy_dump = json.dumps(cfg, sort_keys=True)
    assert hashlib.sha256(legacy_dump.encode()).hexdigest() == BASELINE["config_dump_sha256"]


def test_e1_t2_pre_scan_requested_is_presence_not_truthiness() -> None:
    assert pre_scan_requested({"pre_scan": {}})
    assert pre_scan_requested({"pre_scan": {"detectors": ["regex"]}})
    assert not pre_scan_requested({})
    assert not pre_scan_requested({"pre_scan": None})
    assert not pre_scan_requested({"post_scan": {"integrity": True}})


def test_e1_t3_under_fail_the_hash_moves_with_the_blocking_inputs(tmp_path: Path) -> None:
    fail = _hash(tmp_path, pre_scan={"on_findings": "fail"})
    assert fail != _hash(tmp_path)
    assert fail != _hash(
        tmp_path, pre_scan={"detectors": ["regex", "classifier"], "on_findings": "fail"}
    )
    ner = _hash(tmp_path, pre_scan={"detectors": ["regex", "ner"], "on_findings": "fail"})
    assert fail != ner


def test_e1_t3_effective_values_hash_the_same(tmp_path: Path) -> None:
    short = _hash(tmp_path, pre_scan={"on_findings": "fail"})
    long = _hash(tmp_path, pre_scan={"detectors": ["regex"], "on_findings": "fail"})
    assert short == long


def test_e1_t3_the_ner_model_moves_the_hash_only_when_ner_runs(tmp_path: Path) -> None:
    from decoy_engine.detection.ner import DEFAULT_NER_MODEL

    other = "en_core_web_sm" if DEFAULT_NER_MODEL != "en_core_web_sm" else "en_core_web_md"
    ner = {"detectors": ["regex", "ner"], "on_findings": "fail"}
    assert _hash(tmp_path, pre_scan=ner) != _hash(tmp_path, pre_scan={**ner, "ner_model": other})
    assert _hash(tmp_path, pre_scan=ner) == _hash(
        tmp_path, pre_scan={**ner, "ner_model": DEFAULT_NER_MODEL}
    )


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"on_findings": "warn"},
        {"detectors": ["regex", "classifier"]},
        {"detectors": ["regex", "ner"], "ner_model": "en_core_web_sm", "on_findings": "warn"},
    ],
)
def test_e1_t3_under_warn_nothing_from_the_block_moves_the_hash(
    tmp_path: Path, block: dict[str, Any]
) -> None:
    assert _hash(tmp_path, pre_scan=block) == _hash(tmp_path)


def test_e1_t4_a_bad_on_findings_is_refused_at_its_field_without_the_value() -> None:
    secret = "maybe-canary-text"
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate({**LEGACY_RAW, "pre_scan": {"on_findings": secret}})
    error = next(e for e in caught.value.errors() if e["loc"][-2:] == ("pre_scan", "on_findings"))
    assert error["type"] == "literal_error"
    assert secret not in str(caught.value)
    assert secret not in json.dumps(caught.value.errors(include_input=False), default=str)


def test_e1_on_findings_warn_is_dropped_and_fail_is_kept() -> None:
    warn = PipelineConfig.model_validate({**LEGACY_RAW, "pre_scan": {"on_findings": "warn"}})
    assert "on_findings" not in warn.model_dump()["pre_scan"]
    fail = PipelineConfig.model_validate({**LEGACY_RAW, "pre_scan": {"on_findings": "fail"}})
    assert fail.model_dump()["pre_scan"]["on_findings"] == "fail"
    assert PipelineConfig.model_validate(fail.model_dump()).model_dump() == fail.model_dump()


def test_e1_t10_the_facade_exports_pre_scan_requested() -> None:
    from decoy_engine.config import pre_scan_requested as imported

    assert imported is config_pkg.pre_scan_requested
    assert "pre_scan_requested" in config_pkg.__all__


def test_e1_t7_the_two_codes_are_registered_with_fixed_text() -> None:
    for code, kind, severity in (
        ("uncovered_pii", "warning", "warning"),
        ("uncovered_pii_blocked", "finding", "error"),
    ):
        spec = reasons.get("pre_scan", code)
        assert spec.since == "1.33.0"
        assert spec.kind.value == kind
        assert all(rule.severity.value == severity for rule in spec.rules)
        assert {r.outcome.value for r in spec.rules} == {"findings"}
        assert "{" not in spec.summary and "%" not in spec.summary
        assert spec.context == ()
    assert reasons.pre_scan.UNCOVERED_PII == "uncovered_pii"
    assert reasons.pre_scan.UNCOVERED_PII_BLOCKED == "uncovered_pii_blocked"


def test_e1_t8_the_drift_not_checked_warning_is_registered() -> None:
    spec = reasons.get("warning", "drift_not_checked")
    assert spec.since == "1.33.0"
    assert spec.kind.value == "warning"
    assert reasons.warning.DRIFT_NOT_CHECKED == "drift_not_checked"


def test_e1_t8_no_text_still_claims_the_run_rescans_at_run_start() -> None:
    root = Path(__file__).resolve().parents[3]
    for rel in (
        "src/decoy_engine/reasons/pre_scan/_part1.py",
        "docs/compatibility-contract.md",
    ):
        assert "rescans the sources at run start" not in (root / rel).read_text(), rel
    contract = (root / "docs/compatibility-contract.md").read_text()
    assert "warning.drift_not_checked" in contract


def test_e1_t3_the_hash_fills_defaults_in_a_raw_block() -> None:
    from decoy_engine.plan._compile import _hash_config

    base = {"version": 2, "tables": []}
    short = _hash_config({**base, "pre_scan": {"on_findings": "fail"}})
    assert short == _hash_config(
        {**base, "pre_scan": {"detectors": ["regex"], "on_findings": "fail"}}
    )
    assert short == _hash_config(
        {**base, "pre_scan": {"detectors": ("regex",), "on_findings": "fail"}}
    )
    assert short != _hash_config(
        {**base, "pre_scan": {"detectors": ["classifier", "regex"], "on_findings": "fail"}}
    )
    assert _hash_config({**base, "pre_scan": {"on_findings": "warn"}}) == _hash_config(base)


def test_e1_the_fail_hash_input_follows_the_pre_scan_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.config import PreScanConfig, pre_scan_hash_input

    assert pre_scan_hash_input(None) is None
    assert pre_scan_hash_input({"on_findings": "warn"}) is None
    assert pre_scan_hash_input({"on_findings": "fail"}) == {
        "on_findings": "fail",
        "detectors": ["regex"],
    }
    assert pre_scan_hash_input(PreScanConfig(on_findings="fail")) == pre_scan_hash_input(
        {"on_findings": "fail"}
    )

    class Wider(PreScanConfig):
        detectors: tuple[str, ...] = ("regex", "classifier")  # type: ignore[assignment]
        ner_model: str = "en_core_web_sm"

    monkeypatch.setattr("decoy_engine.config._parse.PreScanConfig", Wider)
    assert pre_scan_hash_input({"on_findings": "fail"}) == {
        "on_findings": "fail",
        "detectors": ["regex", "classifier"],
    }
