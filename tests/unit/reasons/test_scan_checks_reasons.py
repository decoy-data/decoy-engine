"""SCAN-CHECKS B-1 and D-1: the three new reason codes, declared pending (``since=unreleased``)."""

from __future__ import annotations

import re

import pytest

from decoy_engine import reasons

NEW = (
    ("pre_scan", "drift_detected", "warning", "warning"),
    ("pre_scan", "drift_blocked", "finding", "error"),
    ("warning", "scan_baseline_missing", "warning", "warning"),
    ("pre_scan", "baseline_unbound", "warning", "warning"),
)


@pytest.mark.parametrize(("namespace", "code", "kind", "severity"), NEW)
def test_the_code_is_registered_pending_with_fixed_value_free_text(
    namespace: str, code: str, kind: str, severity: str
) -> None:
    spec = reasons.find(namespace, code)
    assert spec is not None
    assert spec.since == "1.30.0"
    assert spec.kind.value == kind
    assert all(rule.severity.value == severity for rule in spec.rules)
    assert not re.search(r"[{}%]", spec.summary)
    assert spec.context == ()


def test_the_symbols_resolve() -> None:
    assert reasons.pre_scan.DRIFT_DETECTED == "drift_detected"
    assert reasons.pre_scan.DRIFT_BLOCKED == "drift_blocked"
    assert reasons.warning.SCAN_BASELINE_MISSING == "scan_baseline_missing"


def test_a_blocked_drift_is_a_findings_outcome_a_user_can_repair() -> None:
    spec = reasons.get("pre_scan", "drift_blocked")
    assert {r.outcome.value for r in spec.rules} == {"findings"}
    assert {r.retry.value for r in spec.rules} == {"configuration_repair"}


# F15 E2: three more pending codes (F15-T9).
BOUND = (
    ("pre_scan", "baseline_digest_mismatch", "failure"),
    ("pre_scan", "baseline_unreadable", "failure"),
    ("config", "scan_baseline_unbound", "failure"),
)


@pytest.mark.parametrize(("namespace", "code", "kind"), BOUND)
def test_f15_t9_the_bound_baseline_codes_are_pending_with_fixed_text(
    namespace: str, code: str, kind: str
) -> None:
    spec = reasons.find(namespace, code)
    assert spec is not None
    assert spec.since == "1.30.0"
    assert spec.kind.value == kind
    assert not re.search(r"[{}%]", spec.summary)
    assert spec.context == ()


def test_f15_t9_the_registry_version_is_stamped_by_the_release() -> None:
    assert reasons.REGISTRY_VERSION == "1.31.0"
