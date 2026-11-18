"""The bound baseline: digest before parse, strict read, and the drift verdict (F15-T7, T8, T9)."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.config import PipelineConfigError, ScanBaselineConfig
from decoy_engine.profiling import (
    BaselineBindingError,
    BoundBaseline,
    DriftFinding,
    bind_baseline,
    evaluate_drift,
)
from decoy_engine.reason_adapter import reason_from_exception

CANARY = "CANARY-31f0a9"
PATH = "baselines/CANARY-path.scan.json"


def _field(name: str, score: float | None) -> dict[str, Any]:
    return {
        "name": name,
        "dtype": "object",
        "null_count": 0,
        "null_rate": 0.0,
        "distinct_count": 3,
        "pii_score": score,
        "pii_candidate": bool(score and score >= 0.6),
        "detector_hits": [],
        "leading_zero_count": None,
    }


def _table(name: str, fields: dict[str, float | None], *, qi: list[list[str]] | None = None) -> Any:
    return {
        "name": name,
        "descriptor": {},
        "row_count": 3,
        "row_count_exact": True,
        "sample_strategy": "head",
        "sample_row_cap": None,
        "fields": [_field(n, s) for n, s in fields.items()],
        "key_candidates": [],
        "warnings": [],
        "reid_risk_score": None,
        "quasi_identifier_groups": qi or [],
    }


def _scan(*tables: Any, tag: object = "scan-set/v1") -> dict[str, Any]:
    return {
        "scan_schema": tag,
        "engine_version": "0.27.0",
        "scanned_at": "2026-11-17T00:00:00Z",
        "tables": list(tables),
        "relationships": [],
    }


BASE = _scan(_table("customers", {"id": 0.0, "email": 0.9}))


def _raw(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True).encode()


def _block(
    sha256: str | None = None, on_drift: str | None = None, **extra: Any
) -> ScanBaselineConfig:
    data: dict[str, Any] = {"path": PATH, "schema": "scan-set/v1", **extra}
    if sha256 is not None:
        data["sha256"] = sha256
    if on_drift is not None:
        data["on_drift"] = on_drift
    return ScanBaselineConfig.model_validate(data)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bound(doc: dict[str, Any], on_drift: str | None = "fail") -> BoundBaseline:
    raw = _raw(doc)
    return bind_baseline(raw, _block(_digest(raw), on_drift))


def _refusal(raw: bytes, block: ScanBaselineConfig) -> BaselineBindingError:
    with pytest.raises(BaselineBindingError) as caught:
        bind_baseline(raw, block)
    return caught.value


def _clean(error: BaselineBindingError, *secrets: str) -> None:
    assert error.__cause__ is None and error.__context__ is None
    text = f"{error}{error.args}"
    for secret in (PATH, _digest(b"x"), CANARY, *secrets):
        assert secret not in text


def test_matching_bytes_bind() -> None:
    raw = _raw(BASE)
    bound = bind_baseline(raw, _block(_digest(raw), "fail"))
    assert bound.bound is True
    assert bound.sha256 == _digest(raw)
    assert bound.on_drift == "fail"
    assert bound.scan["tables"][0]["name"] == "customers"


def test_an_unpinned_warn_baseline_binds_but_reports_unbound() -> None:
    raw = _raw(BASE)
    bound = bind_baseline(raw, _block(None, "warn"))
    assert bound.bound is False
    assert bound.sha256 == _digest(raw)


@pytest.mark.parametrize("on_drift", [None, "warn", "fail"])
def test_one_changed_byte_is_a_digest_mismatch(on_drift: str | None) -> None:
    raw = _raw(BASE)
    block = _block(_digest(raw), on_drift)
    error = _refusal(raw.replace(b"customers", b"customerz"), block)
    assert error.code == str(reasons.pre_scan.BASELINE_DIGEST_MISMATCH)
    assert error.kind == "digest_mismatch"
    _clean(error, _digest(raw))


@pytest.mark.parametrize("on_drift", [None, "warn", "fail"])
def test_a_reformatted_file_with_the_same_content_is_a_mismatch(on_drift: str | None) -> None:
    raw = _raw(BASE)
    block = _block(_digest(raw), on_drift)
    pretty = json.dumps(json.loads(raw), indent=2).encode()
    assert _refusal(pretty, block).code == str(reasons.pre_scan.BASELINE_DIGEST_MISMATCH)


def test_the_digest_is_checked_before_any_parse() -> None:
    """A non-JSON body with the wrong digest is a mismatch, not unreadable."""
    block = _block(_digest(b"something else"), "fail")
    error = _refusal(b"{not json " + CANARY.encode(), block)
    assert error.code == str(reasons.pre_scan.BASELINE_DIGEST_MISMATCH)
    _clean(error, _digest(b"something else"))


def _dup_scan_schema() -> bytes:
    return b'{"scan_schema": "scan-set/v1", ' + _raw(BASE)[1:]


def _dup_tables_hiding_a_drifted_table() -> bytes:
    return b'{"tables": [], ' + _raw(BASE)[1:]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"{not json " + CANARY.encode(), id="not-json"),
        pytest.param(b"\xff\xfe", id="not-utf8"),
        pytest.param(_dup_scan_schema(), id="duplicate-scan-schema"),
        pytest.param(_dup_tables_hiding_a_drifted_table(), id="duplicate-tables"),
        pytest.param(_raw(BASE).replace(b'"pii_score": 0.9', b'"pii_score": NaN'), id="nan"),
        pytest.param(
            _raw(BASE).replace(b'"pii_score": 0.9', b'"pii_score": Infinity'), id="infinity"
        ),
        pytest.param(_raw(BASE).replace(b'"pii_score": 0.9', b'"pii_score": 1e999'), id="overflow"),
        pytest.param(_raw({"tables": [{"name": "customers", "fields": []}]}), id="legacy-profile"),
        pytest.param(_raw(_scan(tag="scan-set/v2")), id="scan-set-v2"),
        pytest.param(b"[]", id="not-an-object"),
    ],
)
def test_an_unreadable_baseline_is_refused_when_no_digest_is_set(raw: bytes) -> None:
    error = _refusal(raw, _block(None, "warn"))
    assert error.code == str(reasons.pre_scan.BASELINE_UNREADABLE)
    assert error.kind == "unreadable"
    _clean(error)


def test_an_unreadable_baseline_with_a_matching_digest_is_still_refused() -> None:
    raw = _dup_tables_hiding_a_drifted_table()
    error = _refusal(raw, _block(_digest(raw), "fail"))
    assert error.code == str(reasons.pre_scan.BASELINE_UNREADABLE)
    _clean(error)


def test_fail_without_a_digest_is_refused_before_hashing() -> None:
    block = ScanBaselineConfig.model_construct(
        path=PATH, schema_tag="scan-set/v1", on_drift="fail", sha256=None
    )
    with pytest.raises(PipelineConfigError) as caught:
        bind_baseline(_raw(BASE), block)
    assert [p.code for p in caught.value.problems] == [str(reasons.config.SCAN_BASELINE_UNBOUND)]
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert PATH not in str(caught.value)


@pytest.mark.parametrize("kind", ["digest_mismatch", "unreadable"])
def test_the_error_pickles_and_maps_to_its_pre_scan_code(kind: str) -> None:
    error = BaselineBindingError(kind)  # type: ignore[arg-type]
    again = pickle.loads(pickle.dumps(error))  # noqa: S301 - bytes this test just produced
    assert (type(again), again.kind, again.code, str(again)) == (
        BaselineBindingError,
        kind,
        error.code,
        str(error),
    )
    record = reason_from_exception(error)
    want = (
        reasons.pre_scan.BASELINE_DIGEST_MISMATCH
        if kind == "digest_mismatch"
        else reasons.pre_scan.BASELINE_UNREADABLE
    )
    assert (record.namespace, str(record.code)) == ("pre_scan", str(want))


def test_the_error_text_names_a_config_key_and_no_value() -> None:
    mismatch = _refusal(b"x", _block(_digest(b"y"), "fail"))
    unreadable = _refusal(b"x", _block(None, "warn"))
    assert "scan_baseline.sha256" in str(mismatch)
    assert "scan_baseline.path" in str(unreadable)
    assert isinstance(mismatch, ValueError)


def test_a_bound_baseline_cannot_be_built_directly() -> None:
    with pytest.raises(TypeError):
        BoundBaseline("0" * 64, True, "fail", {}, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BoundBaseline(sha256="0" * 64, bound=True, on_drift="fail", scan={})  # type: ignore[call-arg]


# --- evaluate_drift (F15-T8) -------------------------------------------------------------


def _verdict(current: dict[str, Any], on_drift: str | None = "fail") -> Any:
    return evaluate_drift(_bound(BASE, on_drift), current)


def test_no_drift_passes_with_no_code() -> None:
    verdict = _verdict(copy.deepcopy(BASE))
    assert (verdict.status, verdict.code) == ("passed", None)
    assert verdict.findings == () and dict(verdict.drifted_tables) == {}
    assert verdict.bound is True and verdict.baseline_sha256 == _digest(_raw(BASE))


DRIFTED = _scan(
    _table(
        "customers",
        {"id": 0.0, "email": 0.9, "alt_email": 0.91, "zzz": 0.8},
        qi=[["email", "id"]],
    ),
    _table("orders", {"id": 0.0}),
)


def test_drift_under_warn_is_warned_with_drift_detected() -> None:
    verdict = _verdict(DRIFTED, "warn")
    assert (verdict.status, verdict.code) == ("warned", str(reasons.pre_scan.DRIFT_DETECTED))


def test_drift_under_fail_is_failed_with_drift_blocked() -> None:
    verdict = _verdict(DRIFTED, "fail")
    assert (verdict.status, verdict.code) == ("failed", str(reasons.pre_scan.DRIFT_BLOCKED))


def test_a_baseline_with_no_on_drift_only_warns() -> None:
    assert _verdict(DRIFTED, None).status == "warned"


def test_findings_are_sorted_names_only_and_grouped_by_table() -> None:
    verdict = _verdict(DRIFTED)
    assert verdict.findings == (
        DriftFinding("customers", None, "new_quasi_identifier_group"),
        DriftFinding("customers", "alt_email", "new_high_pii_field"),
        DriftFinding("customers", "zzz", "new_high_pii_field"),
        DriftFinding("orders", None, "table_added"),
    )
    assert list(verdict.drifted_tables) == ["customers", "orders"]
    assert verdict.drifted_tables["orders"] == (DriftFinding("orders", None, "table_added"),)
    assert verdict.drifted_tables["customers"] == verdict.findings[:3]


def test_a_bucket_increase_is_a_finding_for_that_column() -> None:
    low = _scan(_table("customers", {"id": 0.0, "email": 0.1}))
    verdict = evaluate_drift(_bound(low), BASE)
    assert verdict.findings == (DriftFinding("customers", "email", "pii_bucket_increased"),)
    assert verdict.status == "failed"


def test_no_common_table_is_one_finding_with_no_table() -> None:
    other = _scan(_table("elsewhere", {"id": 0.0}), _table("more", {"id": 0.0}))
    verdict = _verdict(other)
    assert verdict.findings == (DriftFinding(None, None, "no_common_table"),)
    assert dict(verdict.drifted_tables) == {}
    assert verdict.status == "failed"


def test_a_removed_table_is_not_drift() -> None:
    both = _scan(_table("customers", {"id": 0.0, "email": 0.9}), _table("orders", {"id": 0.0}))
    verdict = evaluate_drift(_bound(both), BASE)
    assert verdict.status == "passed"
    assert verdict.diff.tables_removed == ("orders",)


@pytest.mark.parametrize("on_drift", ["warn", None])
def test_an_unbound_baseline_replaced_by_the_current_scan_still_warns(on_drift: str | None) -> None:
    """Without a digest nothing proves the file is the intended one, so no drift is not a pass."""
    current = copy.deepcopy(BASE)
    unbound = bind_baseline(_raw(current), _block(None, on_drift))
    verdict = evaluate_drift(unbound, current)
    assert verdict.diff.drift is False
    assert (verdict.status, verdict.bound) == ("warned", False)
    assert verdict.code == str(reasons.pre_scan.BASELINE_UNBOUND)
    assert verdict.findings == ()


def test_an_unbound_baseline_with_drift_keeps_the_drift_code() -> None:
    verdict = evaluate_drift(bind_baseline(_raw(BASE), _block(None, "warn")), DRIFTED)
    assert verdict.code == str(reasons.pre_scan.DRIFT_DETECTED)


def test_a_bound_baseline_with_no_drift_has_no_warning() -> None:
    verdict = evaluate_drift(_bound(BASE, "warn"), copy.deepcopy(BASE))
    assert (verdict.status, verdict.code) == ("passed", None)


def test_an_unbound_warn_baseline_reports_bound_false() -> None:
    raw = _raw(BASE)
    verdict = evaluate_drift(bind_baseline(raw, _block(None, "warn")), DRIFTED)
    assert verdict.bound is False and verdict.status == "warned"
