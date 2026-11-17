"""Tombstones of the ``platform`` namespace: workflow reasons that shipped and were retired.

The owner retired workflows, so the pipeline is the only unit. A reason that shipped in a tagged
release stays resolvable under its shipped name and text so persisted evidence can still be read:
it is deprecated, never deleted, and points at the live reason that replaces it.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED, Kind, Outcome, Severity

__all__ = [
    "WORKFLOW_RESTART_INTERRUPTED",
    "WORKFLOW_STEP_FAILED",
    "WORKFLOW_STEP_NOT_RUN",
]

_log = _catalog.platform("PlatformJobLog")
_response = _catalog.platform("PlatformResponse")

WORKFLOW_RESTART_INTERRUPTED = _log(
    "workflow_restart_interrupted",
    "The platform restarted while this workflow step ran. Progress was not kept; run it again when ready.",
    since="1.5.0",
    deprecated_in=UNRELEASED,
    replaced_by=("platform", "startup_failed"),
)
WORKFLOW_STEP_NOT_RUN = _log(
    "workflow_step_not_run",
    "Cancelled: the workflow run ended before this step ran.",
    kind=Kind.CONTROL,
    severity=Severity.INFO,
    outcome=Outcome.CANCELLED,
    since="1.5.0",
    deprecated_in=UNRELEASED,
    replaced_by=("platform", "job_cancelled"),
)
WORKFLOW_STEP_FAILED = _response(
    "workflow_step_failed",
    "The workflow step failed. The server log has the details.",
    since="1.5.0",
    deprecated_in=UNRELEASED,
    replaced_by=("platform", "job_failed"),
)
