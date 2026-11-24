"""Residual PII on name-hint-gated detector hits after a whole-cell destroying mask (row 24zu).

A gated detector (``mrn``, ``person_name`` ...) matches a loose shape and fires only because the
column name carries a hint, so the constant ``REDACTED`` or a hash matches it. The source
comparison, not the hit, says whether the mask fired.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from decoy_engine import reasons
from decoy_engine.verification.postmask._column_facts import ColumnFacts, DetectorRate
from decoy_engine.verification.postmask._model_findings import review
from decoy_engine.verification.postmask.residual_pii import (
    check_residual_pii,
    residual_pii_findings,
)


def _cfg(strategy: str, column: str = "customer_id") -> dict:
    return {
        "version": 2,
        "tables": [{"name": "t", "columns": [{"name": column, "strategy": strategy}]}],
    }


def _facts(
    *,
    identical: int,
    comparable: int,
    detectors: tuple[tuple[str, float], ...] = (("mrn", 1.0),),
    src_distinct: int = 50,
    column: str = "customer_id",
) -> dict:
    return {
        "t": {
            column: ColumnFacts(
                table="t",
                column=column,
                source_rows=comparable,
                output_rows=comparable,
                comparable_rows=comparable,
                identical_rows=identical,
                bytes_identical=False,
                source_distinct=src_distinct,
                output_distinct=1,
                detectors=tuple(DetectorRate(d, rate, "high") for d, rate in detectors),
            )
        }
    }


def _one(findings):
    assert len(findings) == 1, findings
    return findings[0]


def _grade(strategy: str = "redact", **kw):
    return _one(residual_pii_findings(_facts(**kw), _cfg(strategy)))


def test_redacted_hint_gated_hit_is_info_when_comparison_ran():
    finding = _grade(identical=0, comparable=100)
    assert finding.severity == "info"
    assert finding.source_compared is True


def test_redact_that_did_not_fire_still_fails():
    assert _grade(identical=100, comparable=100).severity == "fail"


def test_unchanged_constant_source_still_fails():
    finding = _grade(identical=100, comparable=100, src_distinct=1)
    assert finding.severity == "fail"


def test_two_row_unmasked_column_fails():
    assert _grade(identical=2, comparable=2, src_distinct=2).severity == "fail"


def test_gated_low_identity_warns():
    assert _grade(identical=2, comparable=100).severity == "warning"


def test_partial_redact_warns():
    finding = _grade(identical=10, comparable=100, src_distinct=50)
    assert finding.severity == "warning"
    assert not re.search(r"\d|%", finding.message)


def test_gated_majority_identity_fails():
    assert _grade(identical=60, comparable=100).severity == "fail"


@pytest.mark.parametrize(("identical", "comparable"), [(0, 100), (1, 100), (10, 100), (100, 100)])
def test_gated_message_has_no_rate_or_value(identical, comparable):
    finding = _grade(identical=identical, comparable=comparable)
    assert "only through its column name" in finding.message
    assert not re.search(r"\d|%", finding.message), finding.message
    assert "CUST-" not in finding.message and "REDACTED" not in finding.message


def test_text_redact_hint_gated_hit_still_fails():
    """Every cell changed (identity 0), but text_redact does not cover name-hint-only spans, so
    the name can survive: the finding is today's non-gated fail."""
    sources = [f"Alice Smith a{i}@x.com" for i in range(20)]
    outputs = ["Alice Smith REDACTED"] * 20
    findings = check_residual_pii(
        {"t": pd.DataFrame({"full_name": outputs})},
        _cfg("text_redact", "full_name"),
        source_frames={"t": pd.DataFrame({"full_name": sources})},
    )
    finding = _one(findings)
    assert finding.source_identity_rate == 0.0
    assert finding.detector_id == "person_name"
    assert finding.severity == "fail"
    assert "only through its column name" not in finding.message
    assert "should destroy the pattern" in finding.message


def test_mixed_gated_and_ungated_hits_still_fail():
    detectors = (("mrn", 1.0), ("ssn", 0.9))
    facts = _facts(identical=0, comparable=100, detectors=detectors)
    assert [d.detector_id for d in facts["t"]["customer_id"].detectors] == ["mrn", "ssn"]
    assert _one(residual_pii_findings(facts, _cfg("redact"))).severity == "fail"


def test_no_comparison_still_fails():
    assert _grade(identical=0, comparable=0).severity == "fail"


def test_hashed_hint_gated_hit_is_info():
    assert _grade("hash", identical=0, comparable=100).severity == "info"


def test_bucketized_hint_gated_hit_is_info():
    assert _grade("bucketize", identical=0, comparable=100).severity == "info"


def test_identity_error_is_still_an_error():
    facts = _facts(identical=0, comparable=0)
    bad = facts["t"]["customer_id"]
    facts["t"]["customer_id"] = ColumnFacts(**{**bad.__dict__, "identity_error": "ValueError"})
    assert _one(residual_pii_findings(facts, _cfg("redact"))).severity == "error"


def test_a_source_that_cannot_be_read_gives_one_error_finding_for_the_column():
    # `postmask_column_not_inspectable` on the source side: the first branch already reports the
    # column, so the identity-error branch must not add a second error finding.
    facts = _facts(identical=0, comparable=0)
    bad = facts["t"]["customer_id"]
    facts["t"]["customer_id"] = ColumnFacts(
        **{**bad.__dict__, "identity_error": reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE}
    )
    findings = residual_pii_findings(facts, _cfg("redact"))
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 1
    assert reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE in errors[0].message


def test_frame_route_on_demo_shaped_frame_is_info():
    n = 30
    source = pd.DataFrame({"customer_id": [f"CUST-{i:05d}" for i in range(n)]})
    output = pd.DataFrame({"customer_id": ["REDACTED"] * n})
    finding = _one(check_residual_pii({"t": output}, _cfg("redact"), source_frames={"t": source}))
    assert finding.detector_id == "mrn"
    assert finding.severity == "info"


def test_frame_route_redact_that_did_not_fire_fails():
    n = 30
    source = pd.DataFrame({"customer_id": [f"CUST-{i:05d}" for i in range(n)]})
    finding = _one(check_residual_pii({"t": source}, _cfg("redact"), source_frames={"t": source}))
    assert finding.severity == "fail"


def _dismissal(strategy: str = "redact") -> dict:
    return {
        "table": "t",
        "column": "customer_id",
        "detector_id": "mrn",
        "source": "regex",
        "strategy": strategy,
    }


@pytest.mark.parametrize(("identical", "comparable"), [(1, 100), (2, 100), (3, 100), (10, 100)])
def test_a_dismissal_never_lowers_a_gated_warning(identical, comparable):
    config = {**_cfg("redact"), "post_scan": {"dismissed": [_dismissal()]}}
    findings = residual_pii_findings(_facts(identical=identical, comparable=comparable), config)
    assert _one(findings).severity == "warning"
    (reviewed,), _stale = review(findings, config)
    assert reviewed.severity == "warning"
    assert reviewed.dismissed is False


def test_a_dismissal_still_lowers_nothing_on_a_gated_info():
    config = {**_cfg("redact"), "post_scan": {"dismissed": [_dismissal()]}}
    findings = residual_pii_findings(_facts(identical=0, comparable=100), config)
    (reviewed,), _stale = review(findings, config)
    assert reviewed.severity == "info"
