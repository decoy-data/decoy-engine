"""A memory error is a coded result on both routes of `run_pipeline_isolated`, and no handler on
the way hides it (A16 to A18, A21).

`run_pipeline_isolated` runs under one boundary, `memory_boundary`, with a reserved result for
each window: before publishing the memory failure is NOT_PUBLISHED, from the publish call on it
is UNKNOWN with the same-id retry text. Inner handlers let a `MemoryError` through, and the
reason adapter reports it as `process_out_of_memory` instead of another code. The isolated route
runs a fake child (`Run` installs it); the resident route (`isolate=False`) runs `run_pipeline`
in process. Each case injects one fault and asserts that it fired.
"""

from __future__ import annotations

import errno
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import fileaccess, reason_adapter
from decoy_engine.execution import _isolated_reason, _isolated_run, run_pipeline_isolated
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.fileaccess import _errors, _local
from decoy_engine.publication import PublicationRequest
from decoy_engine.reasons import Operation, Phase, PublicationState, ReasonContext
from decoy_engine.reasons import decoy as _decoy
from decoy_engine.signed_evidence._errors import SignedEvidenceError
from tests.fileaccess.x_support import XWorld, xworld  # noqa: F401  (fixture)
from tests.unit.execution.publication._isolated_support import ENGINE_VERSION, job, sources
from tests.unit.execution.publication.test_isolated_commit_memory import (
    BEFORE_TEXT,
    CANARY,
    COMMIT,
    UNKNOWN_TEXT,
    memory,
    once,
)
from tests.unit.execution.publication.test_isolated_readback_cap import (
    HUGE,
    Run,
    ints,
    scratch,  # noqa: F401  (fixture)
)
from tests.unit.publication._publish_support import DESCRIPTOR, stages_left

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated route")

PUBLISH = "decoy_engine.publication._publish"
ADAPTER = "decoy_engine.reason_adapter"
OOM = "process_out_of_memory"
ROUTES = pytest.mark.parametrize("isolated", [True, False], ids=["isolated", "resident"])


def raises_memory(call: Callable[..., Any], *args: Any) -> MemoryError:
    """The `MemoryError` that `call` raises; anything else is an assertion failure."""
    try:
        call(*args)
    except MemoryError as exc:
        return exc
    except BaseException as other:
        raise AssertionError(f"expected MemoryError, got {type(other).__name__}") from None
    raise AssertionError("expected MemoryError, nothing was raised")


class Route:
    """One route over the same job, with or without an `output_dir`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated: bool) -> None:
        self.isolated, self.tmp = isolated, tmp_path
        # The isolated route runs the fake child that `Run` installs.
        self.run = Run(tmp_path, monkeypatch, [ints("t1", 10)], ceiling=HUGE) if isolated else None
        self.out = tmp_path / "pub" / "out"
        self.cfg = job(tmp_path, 3)
        self.table = "t1" if isolated else "t"

    def go(self, *, output: bool = True, on_spawn: Any = None, request: Any = None) -> Any:
        return run_pipeline_isolated(
            self.cfg,
            sources(self.cfg),
            engine_version=ENGINE_VERSION,
            isolate=self.isolated,
            output_dir=self.out if output else None,
            request=request or (PublicationRequest("op-readback") if output else None),
            on_spawn=on_spawn,
        )

    def go_checked(self, **kwargs: Any) -> Any:
        """`go`, where a raw memory error is an assertion failure and not a test error."""
        try:
            return self.go(**kwargs)
        except MemoryError as exc:
            raise AssertionError(f"{type(exc).__name__} escaped run_pipeline_isolated") from None

    def bind_other(self, operation: str = "op-first") -> bytes:
        """Bind a different result at the target; the descriptor bytes it holds."""
        cfg = job(self.tmp, 5)
        other = run_pipeline_isolated(
            cfg,
            sources(cfg),
            isolate=False,
            engine_version=ENGINE_VERSION,
            output_dir=self.out,
            request=PublicationRequest(operation),
        )
        assert other.outcome == "completed"
        return (self.out / DESCRIPTOR).read_bytes()

    def unknown(self, result: Any) -> None:
        memory(result, PublicationState.UNKNOWN, UNKNOWN_TEXT)
        assert result.isolated is self.isolated
        assert result.publication_receipt is None and result.committed_output_dir is None

    def not_published(self, result: Any) -> None:
        memory(result, PublicationState.NOT_PUBLISHED, BEFORE_TEXT)
        assert result.isolated is self.isolated

    def no_stage(self) -> None:
        assert stages_left(self.out.parent) == []


def after_publish_call(
    monkeypatch: pytest.MonkeyPatch, route: Route, target: str, fired: list[str]
) -> None:
    """Fault `target` once, only after the route's publish call was entered."""
    site = f"{COMMIT}.publish_unit" if route.isolated else f"{PUBLISH}.publish_unit"
    module, _, attr = site.rpartition(".")
    real_publish = getattr(sys.modules[module], attr)
    entered: list[int] = []

    def publish(*args: Any, **kwargs: Any) -> Any:
        entered.append(1)
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(site, publish)
    owner, _, name = target.rpartition(".")
    real = getattr(sys.modules[owner], name)

    def fault(*args: Any, **kwargs: Any) -> Any:
        if entered and not fired:
            fired.append(name)
            raise MemoryError(CANARY)
        return real(*args, **kwargs)

    monkeypatch.setattr(target, fault)


def classified(exc: BaseException, **kwargs: Any) -> Any:
    """`reason_from_exception`, where a raised error is an assertion failure."""
    try:
        return reason_adapter.reason_from_exception(exc, **kwargs)
    except MemoryError:
        raise AssertionError("reason_from_exception raised MemoryError") from None


# -- A16: memory error while classifying -------------------------------------------------------


@ROUTES
def test_a16_a_memory_error_classifying_a_refusal_after_the_flag_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    isolated: bool,
) -> None:
    route = Route(tmp_path, monkeypatch, isolated)
    bound = route.bind_other()
    fired: list[str] = []
    after_publish_call(monkeypatch, route, f"{ADAPTER}._classify", fired)
    result = route.go_checked()
    assert fired
    route.unknown(result)
    assert (route.out / DESCRIPTOR).read_bytes() == bound
    route.no_stage()


SEAM_ERRORS: dict[str, Callable[[], BaseException]] = {
    "_classify": lambda: ValueError("x"),
    "_lookup_captured": lambda: ValueError("x"),
    "_read_code": lambda: ExecutionError.__new__(ExecutionError),
    "_identified_reason": lambda: SignedEvidenceError.__new__(SignedEvidenceError),
}


@pytest.mark.parametrize("seam", sorted(SEAM_ERRORS))
def test_a16_the_adapter_reports_a_memory_error_from_each_seam(
    monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    fired: list[str] = []

    def raising(*args: Any, **kwargs: Any) -> Any:
        fired.append(seam)
        raise MemoryError(CANARY)

    monkeypatch.setattr(f"{ADAPTER}.{seam}", raising)
    assert classified(SEAM_ERRORS[seam]()).code == OOM
    assert fired


class _BadIdentityError(SignedEvidenceError):
    @property  # type: ignore[override]
    def identity(self) -> Any:
        raise MemoryError(CANARY)


class _BadCodeError(ExecutionError):
    @property  # type: ignore[override]
    def code(self) -> Any:
        raise MemoryError(CANARY)


@pytest.mark.parametrize("bad", [_BadIdentityError, _BadCodeError])
def test_a16_a_memory_error_in_the_real_inner_handlers_is_out_of_memory(bad: Any) -> None:
    assert classified(bad.__new__(bad)).code == OOM


def test_a16_a_memory_error_building_the_context_of_a_known_record_is_out_of_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = ValueError("x")
    reason_adapter.tag_exception(exc, _decoy.UNEXPECTED_ERROR, phase=Phase.UNKNOWN)
    context = ReasonContext.build(operation=Operation.COMMIT, storage_ref="output")

    def raising(*args: Any, **kwargs: Any) -> Any:
        raise MemoryError(CANARY)

    monkeypatch.setattr("decoy_engine.reasons.ReasonRecord.with_context", raising)
    assert classified(exc, context=context).code == OOM


def test_a16_an_ordinary_failure_in_classification_is_still_unexpected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raising(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(f"{ADAPTER}._classify", raising)
    assert classified(ValueError("x")).code == "unexpected_error"


@pytest.mark.parametrize("output", [True, False], ids=["output_dir", "no_output_dir"])
def test_a16_a_corrupt_footer_refusal_that_cannot_be_classified_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    output: bool,
) -> None:
    run = Run(tmp_path, monkeypatch, [ints("t1", 10)], ceiling=HUGE, plant="corrupt_first")
    ordinary = run.go(output=output)
    assert ordinary.reason is not None and ordinary.reason.code == "publication_failed"
    assert ordinary.publication_receipt is not None  # the refusal receipt, with or without a target
    fired: list[str] = []
    once(monkeypatch, f"{ADAPTER}._classify", fired)
    result = run.go(output=output)
    assert fired
    memory(result, PublicationState.NOT_PUBLISHED, BEFORE_TEXT)
    assert (result.publication_receipt is not None) is output
    if output:
        assert result.publication_receipt.outcome == "failed"
    assert list(scratch.iterdir()) == []
    run.nothing_left(output)


# -- A17: memory error in measurement and around the resident publisher ------------------------


def measure_fault(monkeypatch: pytest.MonkeyPatch, make: Callable[[], BaseException]) -> list[str]:
    fired: list[str] = []

    def measure(*args: Any, **kwargs: Any) -> Any:
        fired.append("measure")
        raise make()

    monkeypatch.setattr(f"{PUBLISH}._measure", measure)
    return fired


@ROUTES
@pytest.mark.parametrize("replay", [False, True], ids=["fresh", "matching_replay"])
def test_a17_an_arrow_memory_error_in_measurement_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    isolated: bool,
    replay: bool,
) -> None:
    route = Route(tmp_path, monkeypatch, isolated)
    real_measure = sys.modules[PUBLISH]._measure
    bound = b""
    if replay:
        assert route.go().outcome == "completed"
        bound = (route.out / DESCRIPTOR).read_bytes()
    fired = measure_fault(monkeypatch, lambda: pa.ArrowMemoryError(CANARY))
    result = route.go_checked()
    assert fired
    route.unknown(result)
    route.no_stage()
    if not replay:
        assert not route.out.exists()
        return
    assert (route.out / DESCRIPTOR).read_bytes() == bound
    monkeypatch.setattr(f"{PUBLISH}._measure", real_measure)
    again = route.go()  # the advice works: the same request confirms the commit
    assert again.publication_receipt is not None
    assert again.publication_receipt.outcome == "already_committed"


MEASURE_CONTROLS: dict[str, Callable[[], BaseException]] = {
    "invalid": lambda: pa.ArrowInvalid("x"),
    "eio": lambda: OSError(errno.EIO, "x"),
    "enomem": lambda: OSError(errno.ENOMEM, "x"),
}


@ROUTES
@pytest.mark.parametrize("kind", sorted(MEASURE_CONTROLS))
def test_a17_ordinary_measurement_failures_are_still_a_failed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    isolated: bool,
    kind: str,
) -> None:
    route = Route(tmp_path, monkeypatch, isolated)
    fired = measure_fault(monkeypatch, MEASURE_CONTROLS[kind])
    result = route.go_checked()
    assert fired
    assert result.outcome == "crashed" and result.reason is not None
    assert result.reason.code == "publication_failed"
    assert result.reason.context.publication_state == PublicationState.NOT_PUBLISHED
    assert result.publication_receipt is not None and result.publication_receipt.outcome == "failed"
    assert not route.out.exists()
    route.no_stage()


@pytest.mark.parametrize("seam", ["stage_path", "publish_entry"])
def test_a17_a_fault_around_the_resident_publisher_is_unknown_and_leaves_no_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    seam: str,
) -> None:
    route = Route(tmp_path, monkeypatch, False)
    fired: list[str] = []
    if seam == "publish_entry":
        once(monkeypatch, f"{PUBLISH}.publish_unit", fired)
    else:

        def fault(self: Any) -> Any:
            fired.append(seam)
            raise MemoryError(CANARY)

        monkeypatch.setattr(_local.LocalOutputTxn, "local_stage_path", fault)
    result = route.go_checked()
    assert fired
    route.unknown(result)
    assert not route.out.exists()
    route.no_stage()


def test_a17_a_fault_building_the_resident_result_without_a_target_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    route = Route(tmp_path, monkeypatch, False)
    fired: list[str] = []
    once(monkeypatch, f"{_isolated_run.__name__}.IsolatedRunResult", fired)
    result = route.go_checked(output=False)
    assert fired
    route.not_published(result)
    assert result.publication_receipt is None


# -- A18: the reserves exist before anything starts --------------------------------------------


@ROUTES
def test_a18_a_fault_building_the_reserves_raises_before_anything_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    isolated: bool,
) -> None:
    route = Route(tmp_path, monkeypatch, isolated)
    spawned: list[int] = []
    ran: list[int] = []
    fired: list[str] = []
    once(monkeypatch, f"{_isolated_reason.__name__}._reserved_result", fired)
    real_run = _isolated_run.run_pipeline

    def run_pipeline(*args: Any, **kwargs: Any) -> Any:
        ran.append(1)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(_isolated_run, "run_pipeline", run_pipeline)
    raises_memory(lambda: route.go(on_spawn=spawned.append))
    assert fired and spawned == [] and ran == []
    assert list(scratch.iterdir()) == []
    assert not route.out.exists()
    route.no_stage()


@pytest.mark.parametrize("which", [1, 2])
def test_a18_a_fault_refreshing_the_reserves_keeps_the_earlier_ones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    which: int,
) -> None:
    route = Route(tmp_path, monkeypatch, True)
    entered: list[int] = []
    calls: list[int] = []
    real_enter = _isolated_reason.Attempt.enter_readback
    real_replace = _isolated_reason.replace

    def enter(self: Any, *args: Any, **kwargs: Any) -> Any:
        entered.append(1)
        return real_enter(self, *args, **kwargs)

    def replace(*args: Any, **kwargs: Any) -> Any:
        if entered:
            calls.append(1)
            if len(calls) == which:
                raise MemoryError(CANARY)
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(_isolated_reason.Attempt, "enter_readback", enter)
    monkeypatch.setattr(f"{_isolated_reason.__name__}.replace", replace)
    result = route.go()
    assert len(calls) == which
    route.not_published(result)
    assert result.pid is None and result.peak_rss_mb is None
    assert result.publication_receipt is not None  # the failed receipt of the requested target
    route.no_stage()
    assert list(scratch.iterdir()) == []


# -- A21: behavior outside the window ----------------------------------------------------------


def faulting(fired: list[str], make: Callable[[], BaseException]) -> Callable[..., Any]:
    def build(*args: Any, **kwargs: Any) -> Any:
        fired.append("build")
        raise make()

    return build


def test_a21_a_memory_error_remembering_a_record_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    monkeypatch.setattr(f"{ADAPTER}._Captured", faulting(fired, lambda: MemoryError(CANARY)))

    def tag() -> Any:
        return reason_adapter.tag_exception(
            ValueError("x"), _decoy.UNEXPECTED_ERROR, phase=Phase.UNKNOWN
        )

    raises_memory(tag)
    raises_memory(reason_adapter.capture_failure, ValueError("y"))
    assert len(fired) == 2


def test_a21_an_ordinary_fault_remembering_a_record_keeps_the_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    monkeypatch.setattr(f"{ADAPTER}._Captured", faulting(fired, lambda: RuntimeError("x")))
    exc = ValueError("x")
    tagged = reason_adapter.tag_exception(exc, _decoy.UNEXPECTED_ERROR, phase=Phase.UNKNOWN)
    assert tagged is exc
    assert reason_adapter.capture_failure(ValueError("y")).code == "unexpected_error"
    assert len(fired) == 2


def test_a21_a_memory_error_validating_a_remembered_record_is_out_of_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = ValueError("x")
    reason_adapter.tag_exception(exc, _decoy.UNEXPECTED_ERROR, phase=Phase.UNKNOWN)
    real = reason_adapter.ReasonRecord.validate
    fired: list[str] = []

    def validate(self: Any) -> None:
        if not fired:
            fired.append("validate")
            raise MemoryError(CANARY)
        real(self)

    monkeypatch.setattr(reason_adapter.ReasonRecord, "validate", validate)
    assert classified(exc).code == OOM
    assert fired
    fired.clear()
    raises_memory(
        reason_adapter.amend_failure, exc, ReasonContext.build(operation=Operation.COMMIT)
    )
    assert fired


class RebuiltError(OSError):
    """Raises a fresh fixed-text `MemoryError` from its constructor, once armed."""

    armed: list[int] = []
    fired: list[int] = []

    def __init__(self, *args: Any) -> None:
        if RebuiltError.armed:
            RebuiltError.armed.clear()
            RebuiltError.fired.append(1)
            raise MemoryError("fixed text")
        super().__init__(*args)


# One original per rebuild helper: wording-recognised, then each memory or disk errno.
ORIGINALS: dict[str, Callable[[], OSError]] = {
    "marker": lambda: RebuiltError(f"Unknown error: Wrapping {CANARY} failed"),
    "enomem": lambda: RebuiltError(errno.ENOMEM, f"no memory {CANARY}", CANARY),
    "enospc": lambda: RebuiltError(errno.ENOSPC, f"no space {CANARY}", CANARY),
    "edquot": lambda: RebuiltError(errno.EDQUOT, f"quota {CANARY}", CANARY),
}


def rendered(exc: BaseException) -> str:
    return str(exc) + "".join(traceback.format_exception(exc))


def arm() -> None:
    RebuiltError.fired.clear()
    RebuiltError.armed.append(1)


@pytest.mark.parametrize("kind", ["marker", "enospc", "edquot"])
def test_a21_a_rebuild_fault_in_a_strict_guard_is_the_fault_with_no_chain(kind: str) -> None:
    original = ORIGINALS[kind]()

    def call() -> None:
        raise original

    def guard() -> None:
        _errors.guarded_with_parser_errors("field", True, (), call)

    arm()
    fault = raises_memory(guard)
    assert RebuiltError.fired and fault.__context__ is None and fault.__cause__ is None
    assert CANARY not in rendered(fault)
    # Control: an unarmed constructor rebuilds the value-free failure.
    with pytest.raises(OSError) as info:
        guard()
    assert CANARY not in rendered(info.value) and info.value.__context__ is None
    if kind != "marker":
        assert info.value.errno == original.errno


@pytest.mark.parametrize("kind", sorted(ORIGINALS))
def test_a21_the_strict_classifiers_raise_a_rebuild_fault(
    xworld: XWorld,  # noqa: F811
    kind: str,
) -> None:
    original = ORIGINALS[kind]()
    arm()
    raises_memory(fileaccess.classified_failure, original)
    assert RebuiltError.fired
    control = fileaccess.classified_failure(ORIGINALS[kind]())
    assert control is not None and control.fresh is not None
    assert CANARY not in rendered(control.fresh)
    if kind == "marker":
        with fileaccess.scope(xworld.policy):
            original = ORIGINALS[kind]()
            arm()
            raises_memory(fileaccess.keeps_class, original)
            assert RebuiltError.fired
            assert fileaccess.keeps_class(ORIGINALS[kind]())


def test_a21_a_typed_memory_error_and_a_parser_error_pass_a_strict_guard_unchanged() -> None:
    typed = pa.ArrowMemoryError("typed")
    parser = ValueError("parser")

    def memory_call() -> None:
        raise typed

    def parser_call() -> None:
        raise parser

    with pytest.raises(pa.ArrowMemoryError) as first:
        _errors.guarded_with_parser_errors("field", True, (), memory_call)
    assert first.value is typed
    with pytest.raises(ValueError) as second:
        _errors.guarded_with_parser_errors("field", True, (ValueError,), parser_call)
    assert second.value is parser
