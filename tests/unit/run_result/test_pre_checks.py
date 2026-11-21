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


@pytest.mark.parametrize("status", ["passed", "warned", "not_run"])
def test_d_t2_only_a_failed_or_error_pre_check_can_block(status: str) -> None:
    result = build(pre_checks=(drift(status, True, DETECTED),))
    assert result.checks[0].blocking is False and result.status == "succeeded"


def test_d_t2_an_error_pre_check_that_blocks_gives_findings() -> None:
    result = build(pre_checks=(drift("error", True, BLOCKED),))
    assert result.checks[0].blocking is True and result.status == "findings"


def test_d_t2_a_pre_check_block_does_not_make_engine_checks_blocking() -> None:
    from types import SimpleNamespace

    facts = SimpleNamespace(
        outputs={},
        row_errors=(),
        warnings=(),
        quality_metrics={"quality_summary": {}, "failed_checks": [{"code": None}]},
    )
    result = build(result=facts, blocking=False, pre_checks=(drift("failed", True, BLOCKED),))
    by_id = {c.id: c for c in result.checks}
    assert by_id["post_validation"].status == "failed"
    assert by_id["post_validation"].blocking is False
    assert by_id["scan_drift"].blocking is True and result.status == "findings"


def test_d_t2_pre_checks_hold_only_scan_drift() -> None:
    other = Check(
        id="fidelity",
        status="failed",
        blocking=True,
        counts=CheckCounts(**{"pass": 0, "warning": 0, "fail": 1, "error": 0}),
        codes=(),
    )
    with pytest.raises(ValueError):
        build(pre_checks=(other,))


# PRE-SCAN-RUN E1: the `pre_scan` check id, and the order of pre-checks.
def pre_scan(status: str, blocking: bool, code: str) -> Check:
    counts = CheckCounts(
        **{
            "pass": 0,
            "warning": int(status == "warned"),
            "fail": int(status == "failed"),
            "error": 0,
        }
    )
    return Check(id="pre_scan", status=status, blocking=blocking, counts=counts, codes=(code,))


UNCOVERED_BLOCKED = str(reasons.pre_scan.UNCOVERED_PII_BLOCKED)


def test_e1_t5_a_blocking_pre_scan_check_gives_findings_and_exit_4() -> None:
    result = build(pre_checks=(pre_scan("failed", True, UNCOVERED_BLOCKED),))
    assert result.status == "findings"
    assert result.exit_code == EXIT_MAP[("findings", None)]
    assert [c.id for c in result.checks] == ["pre_scan"]


def test_e1_t5_pre_scan_comes_before_scan_drift_and_each_appears_once() -> None:
    both = (pre_scan("warned", False, UNCOVERED_BLOCKED), drift("warned", False, DETECTED))
    assert [c.id for c in build(pre_checks=both).checks] == ["pre_scan", "scan_drift"]
    with pytest.raises(ValueError):
        build(pre_checks=tuple(reversed(both)))
    with pytest.raises(ValueError):
        build(pre_checks=(both[0], both[0]))


def test_e1_t6_the_read_model_keeps_the_pre_scan_check() -> None:
    payload = build(pre_checks=(pre_scan("failed", True, UNCOVERED_BLOCKED),)).to_payload()
    assert RunResultRead.model_validate(payload).checks[0].id == "pre_scan"
    # An older reader that did not know the id keeps it as a plain token.
    tolerant = RunResultRead.model_validate(
        {**payload, "checks": [{**payload["checks"][0], "id": "pre_scan_next"}]}
    )
    assert tolerant.checks[0].id == "pre_scan_next"
