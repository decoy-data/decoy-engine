"""Structured reasons for the isolated-run primitive (F29).

Kept apart from `_isolated_run` (the spawn/classify orchestrator) so that module stays near its
size budget. Both helpers only *build* a `ReasonRecord`; nothing here changes how a run is
spawned, committed or classified.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from decoy_engine import reasons
from decoy_engine.execution._errors import capacity_message
from decoy_engine.execution._isolated_common import (
    IsolatedRunOutcome,
    IsolatedRunResult,
    exception_error_text,
    is_memory_failure,
    peak_rss_mb,
)
from decoy_engine.execution.pipeline import ResidentFit
from decoy_engine.publication import CommitReceipt
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.reasons import (
    CleanupState,
    Operation,
    Phase,
    PublicationState,
    ReasonCode,
    ReasonContext,
    ReasonRecord,
)
from decoy_engine.reasons import decoy as _decoy
from decoy_engine.verification.postmask import PostScanBlockedError

__all__ = [
    "Attempt",
    "cleanup_state_of",
    "commit_reason",
    "envelope_failure",
    "in_process_failure",
    "readback_memory_failure",
    "readback_refused",
    "reason_from_envelope",
]

# The one remedy of both readback results: the output, not the input, is what is too large.
_READBACK_REMEDY = "Run on a machine with more memory, or write fewer or smaller output tables."
# The memory result once publishing may have started: the target may or may not exist.
_UNKNOWN_REMEDY = "Rerun with the same operation id to confirm."


@dataclass
class Attempt:
    """The memory contract of one isolated attempt, from the child's report through cleanup.

    `reserve` builds both memory results before the readback allocates anything, so a memory
    failure later only selects one of them. `publishing` is set just before `publish_unit`:
    from then on the target may exist, so the reserve says UNKNOWN, never NOT_PUBLISHED.
    `extra` is shared with both reserves; the readback replaces its entry after each
    measurement, so they carry the last complete figures."""

    publishing: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    _pre_call: IsolatedRunResult | None = None
    _unknown: IsolatedRunResult | None = None

    def reserve(self, *, receipt: CommitReceipt | None, peak: float | None, pid: int) -> None:
        """Build both results; `receipt` is the failed receipt of a requested destination."""
        code = _decoy.PROCESS_OUT_OF_MEMORY
        summary = reasons.get(code.namespace, code).summary
        unknown = CleanupState.UNKNOWN  # nothing is cleaned up yet when these are built
        self._pre_call = _readback_result(
            code,
            f"{summary} {_READBACK_REMEDY}",
            (PublicationState.NOT_PUBLISHED, unknown),
            receipt,
            self.extra,
            peak,
            pid,
        )
        self._unknown = _readback_result(
            code,
            f"{summary} {_UNKNOWN_REMEDY}",
            (PublicationState.UNKNOWN, unknown),
            None,
            self.extra,
            peak,
            pid,
        )

    def failed_receipt_for(self, receipt: CommitReceipt) -> None:
        """Add the failed receipt of a requested destination to the pre-call reserve. If this
        allocation fails the receipt-less reserve already stands."""
        if self._pre_call is not None:
            self._pre_call = replace(self._pre_call, publication_receipt=receipt)

    def memory_result(self) -> IsolatedRunResult | None:
        """The reserve for a memory failure now, or None when none was built yet."""
        return self._unknown if self.publishing else self._pre_call


def _blocked_metrics(metrics: Any) -> dict[str, Any]:
    """The only result a blocked run keeps: its post-scan report, and only when it is a mapping.
    The envelope is untrusted input, so a wrong-typed field is dropped, never repaired."""
    report = metrics.get("post_scan_integrity") if isinstance(metrics, dict) else None
    return {"post_scan_integrity": dict(report)} if isinstance(report, dict) else {}


def in_process_failure(exc: BaseException) -> IsolatedRunResult:
    """A run that raised in this process. A post-scan block is its own outcome and keeps the
    report; every other failure is a memory kill or a crash with the safe text and reason."""
    outcome: IsolatedRunOutcome = "oom_killed" if is_memory_failure(exc) else "crashed"
    metrics: dict[str, Any] = {}
    if isinstance(exc, PostScanBlockedError):
        outcome, metrics = "blocked", _blocked_metrics({"post_scan_integrity": exc.report})
    return IsolatedRunResult(
        outcome=outcome,
        peak_rss_mb=round(peak_rss_mb(), 1),
        outputs=None,
        quality_metrics=metrics,
        table_kinds={},
        returncode=None,
        signal_number=None,
        error=exception_error_text(exc),
        isolated=False,
        reason=reason_from_exception(exc),
    )


def envelope_failure(envelope: dict[str, Any], *, pid: int) -> IsolatedRunResult:
    """The result of a child that reported a failure. A `blocked` child also hands back its
    report."""
    blocked = envelope["outcome"] == "blocked"
    return IsolatedRunResult(
        outcome=envelope["outcome"],
        peak_rss_mb=envelope.get("peak_rss_mb"),
        outputs=None,
        quality_metrics=_blocked_metrics(envelope.get("quality_metrics")) if blocked else {},
        table_kinds={},
        returncode=0,
        signal_number=None,
        error=envelope.get("error"),
        isolated=True,
        pid=pid,
        reason=reason_from_envelope(envelope),
    )


def reason_from_envelope(envelope: dict[str, Any]) -> ReasonRecord:
    """The worker's reason, validated here: identity, phase and context are read from the
    envelope, while severity, outcome and retry class are recomputed from this process's
    registry. An old worker (no `reason` key) or a corrupt or newer payload degrades to a fixed
    diagnostic and never to success or to retry advice the registry did not give."""
    if "reason" not in envelope:
        return ReasonRecord.for_reason(
            _decoy.ISOLATED_WORKER_OUT_OF_MEMORY
            if envelope.get("outcome") == "oom_killed"
            else _decoy.UNEXPECTED_ERROR
        )
    return ReasonRecord.from_payload(envelope["reason"])


def cleanup_state_of(staging: Path) -> CleanupState:
    """How cleanup of a refused stage ended, confirmed by looking."""
    return CleanupState.FAILED if staging.exists() else CleanupState.CONFIRMED


def commit_reason(exc: BaseException, staging: Path) -> ReasonRecord:
    """A failed atomic commit: nothing was published, and cleanup is confirmed by looking."""
    return reason_from_exception(
        exc,
        phase=Phase.PUBLISH,
        context=ReasonContext.build(
            operation=Operation.COMMIT,
            storage_ref="output",
            publication_state=PublicationState.NOT_PUBLISHED,
            cleanup_state=cleanup_state_of(staging),
        ),
    )


def _not_published(staging: Path) -> tuple[PublicationState, CleanupState]:
    """Nothing was published; cleanup is confirmed by looking, as for a failed commit."""
    return PublicationState.NOT_PUBLISHED, cleanup_state_of(staging)


def readback_refused(
    fit: ResidentFit,
    *,
    staging: Path,
    receipt: CommitReceipt | None,
    extra: dict[str, Any],
    peak: float | None,
    pid: int,
) -> IsolatedRunResult:
    """A completed child whose output the driver would not hold: refused before the next decode.

    The fixed_text is the registered summary and two integers; no table, column or value reaches it.
    Output size is the same on every route, so the governor has nothing to reroute to: `crashed`.
    """
    code = _decoy.ISOLATED_READBACK_CAPACITY_EXCEEDED
    fixed_text = capacity_message(
        code,
        needed_bytes=fit.estimated_bytes,
        kill_ceiling_bytes=fit.kill_ceiling_bytes,
        remedy=_READBACK_REMEDY,
    )
    return _readback_result(code, fixed_text, _not_published(staging), receipt, extra, peak, pid)


def readback_memory_failure(
    *,
    staging: Path,
    receipt: CommitReceipt | None,
    extra: dict[str, Any],
    peak: float | None,
    pid: int,
) -> IsolatedRunResult:
    """A memory failure while the driver read the child's output back, with fixed fixed_text.

    Built from the registry, never from the exception: its message can carry sizes and names."""
    code = _decoy.PROCESS_OUT_OF_MEMORY
    fixed_text = f"{reasons.get(code.namespace, code).summary} {_READBACK_REMEDY}"
    return _readback_result(code, fixed_text, _not_published(staging), receipt, extra, peak, pid)


def _readback_result(
    code: ReasonCode,
    fixed_text: str,
    states: tuple[PublicationState, CleanupState],
    receipt: CommitReceipt | None,
    extra: dict[str, Any],
    peak: float | None,
    pid: int,
) -> IsolatedRunResult:
    """A crashed readback result with the given publication and cleanup states."""
    reason = ReasonRecord.for_reason(
        code,
        phase=Phase.FINALIZE,
        context=ReasonContext.build(
            operation=Operation.READ,
            storage_ref="output",
            publication_state=states[0],
            cleanup_state=states[1],
        ),
    )
    return IsolatedRunResult(
        outcome="crashed",
        peak_rss_mb=peak,
        outputs=None,
        quality_metrics={},
        table_kinds={},
        returncode=0,
        signal_number=None,
        error=fixed_text,
        isolated=True,
        pid=pid,
        extra=extra,
        reason=reason,
        publication_receipt=receipt,
    )
