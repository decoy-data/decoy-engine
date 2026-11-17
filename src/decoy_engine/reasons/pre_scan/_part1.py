"""Catalog of the ``pre_scan`` namespace, part 1 (phase-envelope failures and the drift check)."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED, Kind, Outcome, Phase, RetryClass, Severity

__all__ = [
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
    since=UNRELEASED,
)
DRIFT_BLOCKED = _d(
    "drift_blocked",
    "The sources drifted from the scan baseline, so the run stopped under on_drift: fail.",
    kind=Kind.FINDING,
    severity=Severity.ERROR,
    outcome=Outcome.FINDINGS,
    retry=RetryClass.CONFIGURATION_REPAIR,
    since=UNRELEASED,
)

# INIT-WIZARD E1: a review decision the starter config cannot take. The caller repairs its input,
# so these are configuration failures, not scan failures. Each names a table or column, never a
# value.
_review = _catalog.pre_scan("ReviewInputError")
_REVIEW_RULES = {
    "phases": (Phase.CONFIGURATION,),
    "outcome": Outcome.CONFIGURATION,
    "retry": RetryClass.CONFIGURATION_REPAIR,
    "since": UNRELEASED,
}
REVIEW_UNKNOWN_COLUMN = _review(
    "review_unknown_column",
    "A review decision names a column that is not in the starter config.",
    **_REVIEW_RULES,
)
REVIEW_DUPLICATE = _review(
    "review_duplicate",
    "Two review decisions name the same column.",
    **_REVIEW_RULES,
)
REVIEW_STALE = _review(
    "review_stale",
    "A confirmed suggestion no longer matches the starter config's suggestion for that column.",
    **_REVIEW_RULES,
)
REVIEW_EMPTY_TABLE = _review(
    "review_empty_table",
    "The review drops every column of a table, and a mask table needs at least one column.",
    **_REVIEW_RULES,
)
