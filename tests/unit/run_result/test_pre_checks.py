"""SCAN-CHECKS D-1: ``build_run_result(pre_checks=...)`` and the ``scan_drift`` check id."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.run_result import Check, CheckCounts, RunResultRead
from tests.unit.run_result.test_build import build
from tests.unit.run_result.test_outcome import EXIT_MAP

DETECTED = str(reasons.pre_scan.DRIFT_DETECTED)
BLOCKED = str(reasons.pre_scan.DRIFT_BLOCKED)


def drift(status: str, blocking: bool, code: str) -> Check:
    counts = CheckCounts(
        **{
            "pass": 0,
            "warning": int(status == "warned"),
            "fail": int(status == "failed"),
            "error": 0,
        }
    )
    return Check(id="scan_drift", status=status, blocking=blocking, counts=counts, codes=(code,))


def test_d_t2_a_blocking_pre_check_gives_findings_and_its_exit() -> None:
    result = build(pre_checks=(drift("failed", True, BLOCKED),))
    assert result.status == "findings"
    assert result.exit_code == EXIT_MAP[("findings", None)]
    assert [c.id for c in result.checks] == ["scan_drift"]
    assert result.checks[0].blocking is True and result.checks[0].codes == (BLOCKED,)


def test_d_t2_a_warned_pre_check_does_not_block() -> None:
    result = build(pre_checks=(drift("warned", False, DETECTED),))
    assert result.status == "succeeded"
    assert result.checks[0].status == "warned" and result.checks[0].blocking is False


def test_d_t2_no_pre_checks_changes_nothing() -> None:
    assert build().checks == build(pre_checks=()).checks == ()


def test_d_t2_the_read_model_accepts_scan_drift() -> None:
    payload = build(pre_checks=(drift("failed", True, BLOCKED),)).to_payload()
    read = RunResultRead.model_validate(payload)
    assert read.checks[0].id == "scan_drift"


def test_d_t2_an_unknown_check_id_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        Check(id="scan_other", status="passed", blocking=False,
              counts=CheckCounts(**{"pass": 1, "warning": 0, "fail": 0, "error": 0}), codes=())  # type: ignore[arg-type]  # fmt: skip


def test_d_t2_a_non_blocking_failed_pre_check_cannot_claim_blocking() -> None:
    result = build(pre_checks=(drift("passed", True, DETECTED),))
    assert result.checks[0].blocking is False and result.status == "succeeded"
