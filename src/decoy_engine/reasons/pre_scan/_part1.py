"""Catalog of the ``pre_scan`` namespace, part 1 (phase-envelope failures and the drift check)."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import Kind, Outcome, RetryClass, Severity

__all__ = [
    "BASELINE_DIGEST_MISMATCH",
    "BASELINE_UNBOUND",
    "BASELINE_UNREADABLE",
    "DRIFT_BLOCKED",
    "DRIFT_DETECTED",
    "PROFILE_FAILED",
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
