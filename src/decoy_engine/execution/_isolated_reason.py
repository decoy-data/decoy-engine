"""Reasons and the memory boundary of the isolated-run primitive (F29).

Kept apart from `_isolated_run` (the spawn/classify orchestrator) so that module stays near its
size budget. This module owns the attempt windows, the reserved memory results and
`memory_boundary`, the one handler that turns a `MemoryError` into a result on both routes; the
rest only *builds* a `ReasonRecord` or result and changes nothing about how a run is spawned,
committed or classified.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
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
    "Window",
    "cleanup_state_of",
    "commit_reason",
    "envelope_failure",
    "in_process_failure",
    "memory_boundary",
    "readback_memory_failure",
    "readback_refused",
    "reason_from_envelope",
]

# The one remedy of both readback results: the output, not the input, is what is too large.
_READBACK_REMEDY = "Run on a machine with more memory, or write fewer or smaller output tables."
# The memory result once publishing may have started: the target may or may not exist.
_UNKNOWN_REMEDY = "Rerun with the same operation id to confirm."
_OOM_CODE = _decoy.PROCESS_OUT_OF_MEMORY


class Window(Enum):
    """How far one attempt has got, which decides what a memory failure may claim."""

    BEFORE = "before"  # nothing a result could describe has started: a memory error stays raw
    PRE_CALL = "pre_call"  # the child's output is being read: nothing is published
    PUBLISHING = "publishing"  # the target may exist: a memory failure is UNKNOWN


@dataclass
class Attempt:
    """The memory contract of one attempt on either route, from setup through cleanup.

    Both reserved results are built in the constructor, before anything is staged, spawned or
    run, so a window never builds one: a memory failure inside a window only selects one.
    `extra` is shared with both reserves; the readback replaces its entry after each
    measurement, so they carry the last complete figures."""

    is_isolated: bool
    window: Window = Window.BEFORE
    extra: dict[str, Any] = field(default_factory=dict)
    _pre_call: IsolatedRunResult = field(init=False)
    _unknown: IsolatedRunResult = field(init=False)

    def __post_init__(self) -> None:
        code = _decoy.PROCESS_OUT_OF_MEMORY
        summary = reasons.get(code.namespace, code).summary
        unknown = CleanupState.UNKNOWN  # nothing is cleaned up yet when these are built
        self._pre_call = self._reserve(
            f"{summary} {_READBACK_REMEDY}", PublicationState.NOT_PUBLISHED, unknown
        )
        self._unknown = self._reserve(
            f"{summary} {_UNKNOWN_REMEDY}", PublicationState.UNKNOWN, unknown
        )

    @classmethod
    def isolated(cls) -> Attempt:
        return cls(True)

    @classmethod
    def resident(cls) -> Attempt:
        return cls(False)

    def _reserve(
        self, fixed_text: str, publication: PublicationState, cleanup: CleanupState
    ) -> IsolatedRunResult:
        return _reserved_result(
            _decoy.PROCESS_OUT_OF_MEMORY,
            fixed_text,
            (publication, cleanup),
            None,
            self.extra,
            None,
            None,
            isolated=self.is_isolated,
        )

    def enter_readback(self, pid: int | None, peak: float | None) -> None:
        """Open `PRE_CALL`, then add the child's pid and peak to both reserves. If the refresh
        fails, the reserves built at construction stand."""
        self.window = Window.PRE_CALL
        pre_call = replace(self._pre_call, pid=pid, peak_rss_mb=peak)
        unknown = replace(self._unknown, pid=pid, peak_rss_mb=peak)
        self._pre_call, self._unknown = pre_call, unknown

    def enter_publishing(self) -> None:
        """Called immediately before the publish call: from here the target may exist."""
        self.window = Window.PUBLISHING

    def failed_receipt_for(self, receipt: CommitReceipt) -> None:
        """Add the failed receipt of a requested destination to the pre-call reserve."""
        self._pre_call = replace(self._pre_call, publication_receipt=receipt)

    def memory_result(self) -> IsolatedRunResult | None:
        """The reserve for a memory failure now; None before any window opens."""
        if self.window is Window.PUBLISHING:
            return self._unknown
        return self._pre_call if self.window is Window.PRE_CALL else None

    def settle(self, result: IsolatedRunResult) -> IsolatedRunResult:
        """Normalize a memory-coded result by window. Once publishing began, any memory-coded
        failure is UNKNOWN. In the pre-call window a context-free one (the adapter's fallback
        while classifying a refusal) takes the pre-call reserve; one that already says what
        happened keeps its evidence. Before any window the result is returned as built."""
        reason = result.reason
        if result.outcome == "completed" or reason is None or reason.code != _OOM_CODE:
            return result
        if self.window is Window.PUBLISHING:
            return self._unknown
        if self.window is Window.PRE_CALL and reason.context.publication_state is None:
            return self._pre_call
        return result


def memory_boundary(attempt: Attempt, body: Callable[[], IsolatedRunResult]) -> IsolatedRunResult:
    """The one handler that turns a `MemoryError` into a result, for both routes. Inner handlers
    let it pass (tests/sentry/defects/memory_boundary); here the window picks the reserve. In
    `BEFORE` nothing a result could describe has started, so the error stays raw."""
    try:
        return attempt.settle(body())
    except MemoryError:
        reserved = attempt.memory_result()
        if reserved is None:
            raise
        return reserved


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
    return CleanupState.FAILED if staging.is_dir() else CleanupState.CONFIRMED


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
    return _reserved_result(code, fixed_text, _not_published(staging), receipt, extra, peak, pid)


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
    return _reserved_result(code, fixed_text, _not_published(staging), receipt, extra, peak, pid)


def _reserved_result(
    code: ReasonCode,
    fixed_text: str,
    states: tuple[PublicationState, CleanupState],
    receipt: CommitReceipt | None,
    extra: dict[str, Any],
    peak: float | None,
    pid: int | None,
    *,
    isolated: bool = True,
) -> IsolatedRunResult:
    """A crashed result with the given publication and cleanup states. The resident route
    (`isolated=False`) has no child: no returncode and the commit operation."""
    reason = ReasonRecord.for_reason(
        code,
        phase=Phase.FINALIZE,
        context=ReasonContext.build(
            operation=Operation.READ if isolated else Operation.COMMIT,
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
        returncode=0 if isolated else None,
        signal_number=None,
        error=fixed_text,
        isolated=isolated,
        pid=pid,
        extra=extra,
        reason=reason,
        publication_receipt=receipt,
    )
