"""Catalog of the ``pre_scan`` namespace, part 1 (phase-envelope failures and the drift check)."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED as UNRELEASED
from decoy_engine.reasons._types import (
    Kind,
    Outcome,
    Phase,
    ReasonCode,
    RetryClass,
    Severity,
)

__all__ = [
    "BASELINE_DIGEST_MISMATCH",
    "BASELINE_UNBOUND",
    "BASELINE_UNREADABLE",
    "DRIFT_BLOCKED",
    "DRIFT_DETECTED",
    "PROFILE_FAILED",
    "REVIEW_DUPLICATE",
    "REVIEW_EMPTY_TABLE",
    "REVIEW_STALE",
    "REVIEW_UNKNOWN_COLUMN",
]

_d = _catalog.pre_scan("decoy_engine.phase")

PROFILE_FAILED = _d("profile_failed", "The Pre-scan profile did not complete.")
# SCAN-CHECKS: `scan_baseline.on_drift` rescans the sources at run start and compares them with
# the baseline. `warn` reports and the run continues; `fail` stops the run before any masking read.
DRIFT_DETECTED = _d(
    "drift_detected",
    "The sources drifted from the scan baseline; the run continues under on_drift: warn.",
    kind=Kind.WARNING,
    severity=Severity.WARNING,
    outcome=Outcome.FINDINGS,
    retry=RetryClass.NEVER,
    since="1.30.0",
)
DRIFT_BLOCKED = _d(
    "drift_blocked",
    "The sources drifted from the scan baseline, so the run stopped under on_drift: fail.",
    kind=Kind.FINDING,
    severity=Severity.ERROR,
    outcome=Outcome.FINDINGS,
    retry=RetryClass.CONFIGURATION_REPAIR,
    since="1.30.0",
)
# F15: a bound baseline (`scan_baseline.sha256`) is checked before it is read as a scan.
BASELINE_DIGEST_MISMATCH = _d(
    "baseline_digest_mismatch",
    "The scan baseline file does not match scan_baseline.sha256, so the run stopped.",
    retry=RetryClass.CONFIGURATION_REPAIR,
    since="1.30.0",
)
BASELINE_UNREADABLE = _d(
    "baseline_unreadable",
    "The scan baseline file is not a readable scan-set/v1 scan.",
    retry=RetryClass.CONFIGURATION_REPAIR,
    since="1.30.0",
)
# An `on_drift: warn` baseline with no `scan_baseline.sha256`: nothing proves the file is the one
# the operator meant, so a run that passes the drift check still says so.
BASELINE_UNBOUND = _d(
    "baseline_unbound",
    "The scan baseline has no scan_baseline.sha256, so nothing proves it is the intended file.",
    kind=Kind.WARNING,
    severity=Severity.WARNING,
    outcome=Outcome.FINDINGS,
    retry=RetryClass.NEVER,
    since="1.30.0",
)

# INIT-WIZARD E1: a review decision the starter config cannot take. The caller repairs its input,
# so these are configuration failures, not scan failures. Each names a table or column, never a
# value.
_review_declare = _catalog.pre_scan("ReviewInputError")


def _review(code: str, summary: str) -> ReasonCode:
    return _review_declare(
        code,
        summary,
        phases=(Phase.CONFIGURATION,),
        outcome=Outcome.CONFIGURATION,
        retry=RetryClass.CONFIGURATION_REPAIR,
        since="1.31.0",
    )


REVIEW_UNKNOWN_COLUMN = _review(
    "review_unknown_column",
    "A review decision names a column that is not in the starter config.",
)
REVIEW_DUPLICATE = _review(
    "review_duplicate",
    "Two review decisions name the same column.",
)
REVIEW_STALE = _review(
    "review_stale",
    "A confirmed suggestion no longer matches the starter config's suggestion for that column.",
)
REVIEW_EMPTY_TABLE = _review(
    "review_empty_table",
    "The review drops every column of a table, and a mask table needs at least one column.",
)
