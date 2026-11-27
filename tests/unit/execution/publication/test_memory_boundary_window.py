"""The memory guard covers every module the commit windows run through (A19), and the callers of
`publish_unit` that now raise a measurement memory error (A20).

A19 runs the scenario matrix on both routes under `sys.setprofile`, from the first window
transition of the outer attempt to the return of its `memory_boundary`, and checks that every
traced function holding a memory-catching handler, a memory-naming `suppress` or a `finally`
exit is in a file of the guard's `SCOPE`. The sentry and this test share one definition of
`SCOPE` and of the handler predicate (`_memory_scan`). The vault cases need PyNaCl.
"""

from __future__ import annotations

import ast
import errno
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reason_adapter
from decoy_engine.execution import _isolated_run
from decoy_engine.execution._isolated_reason import Attempt
from decoy_engine.publication import PublicationRequest
from tests.sentry.defects import _defect_scan as scan
from tests.sentry.defects.memory_boundary import _memory_scan as ms
from tests.unit.execution.publication.test_isolated_commit_memory import CANARY, COMMIT, once
from tests.unit.execution.publication.test_isolated_readback_cap import scratch  # noqa: F401
from tests.unit.execution.publication.test_memory_boundary_routes import PUBLISH, Route
from tests.unit.publication._publish_support import DESCRIPTOR
from tests.unit.publication._stage_support import Run as DeliveryRun
from tests.unit.publication._stage_support import deliver
from tests.unit.publication._vault_publish_support import binding, prepare

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated route")

SRC = scan.SRC


@dataclass
class Trace:
    functions: set[tuple[str, int]] = field(default_factory=set)
    outer: Any = None
    active: bool = False
    starts: int = 0
    stops: int = 0
    threads: int = 0

    def add(self, code: Any) -> None:
        name = code.co_filename
        if name.startswith(str(SRC)) and code.co_name != "<module>":
            self.functions.add((name, code.co_firstlineno))


@contextmanager
def tracing(mp: pytest.MonkeyPatch) -> Iterator[Trace]:
    """Profile the outer attempt from its first window transition to its boundary's return."""
    trace = Trace()
    previous = sys.getprofile()
    real_boundary, real_enter = _isolated_run.memory_boundary, Attempt.enter_readback
    real_start = threading.Thread.start

    def profiler(frame: Any, event: str, arg: Any) -> None:
        if event == "call":
            trace.add(frame.f_code)

    def boundary(attempt: Attempt, body: Callable[[], Any]) -> Any:
        if trace.outer is None:
            trace.outer = attempt
        try:
            return real_boundary(attempt, body)
        finally:
            if attempt is trace.outer and trace.active:
                sys.setprofile(previous)
                trace.active = False
                trace.stops += 1

    def enter(self: Attempt, pid: int | None, peak: float | None) -> None:
        if self is trace.outer and not trace.starts:
            trace.starts, trace.active = 1, True
            frame: Any = sys._getframe(1)
            while frame is not None:  # the frames already on the stack are in the window too
                trace.add(frame.f_code)
                frame = frame.f_back
            sys.setprofile(profiler)
        real_enter(self, pid, peak)

    def start(self: threading.Thread) -> None:
        trace.threads += trace.active
        real_start(self)

    mp.setattr(_isolated_run, "memory_boundary", boundary)
    mp.setattr(Attempt, "enter_readback", enter)
    mp.setattr(threading.Thread, "start", start)
    try:
        yield trace
    finally:
        sys.setprofile(previous)


# One entry per scenario: the routes it runs on and the sentinel functions it must reach.
SCENARIOS: dict[str, tuple[tuple[bool, ...], set[str]]] = {
    "scratch_only": ((True, False), set()),
    "publish": ((True, False), {"_judge_and_bind"}),
    "publish_vault": ((True, False), {"_judge_and_bind"}),
    "replay_vault": ((True, False), {"_judge_and_bind", "_check_vault", "_decode_rows"}),
    "occupied": ((True, False), {"reason_from_exception"}),
    "conflict": ((True, False), {"reason_from_exception"}),
    "publish_entry_fault": ((True, False), set()),
    "measure_eio": ((True, False), {"_judge_and_bind"}),
    "measure_enomem": ((True, False), {"_judge_and_bind"}),
    "refusal_target": ((True,), set()),
    "refusal_scratch": ((True,), set()),
    "readback_enomem": ((True,), set()),
    "readback_marker": ((True,), set()),
}


def expect(kind: str, result: Any) -> None:
    code = result.reason.code if result.reason is not None else None
    receipt = result.publication_receipt
    if kind in ("scratch_only", "publish", "publish_vault"):
        assert result.outcome == "completed"
    elif kind == "replay_vault":
        assert result.outcome == "completed" and receipt.outcome == "already_committed"
    elif kind in ("occupied", "conflict"):
        assert result.outcome == "crashed" and receipt.outcome in ("refused", "operation_conflict")
    elif kind in ("publish_entry_fault", "readback_enomem", "readback_marker"):
        assert code == "process_out_of_memory"
    elif kind.startswith("measure"):
        assert code == "publication_failed"
    else:
        assert code == "isolated_readback_capacity_exceeded"


def play(kind: str, isolated: bool, base: Path, mp: pytest.MonkeyPatch, traced: bool) -> Any:
    """One scenario; the setup runs untraced and the final call is the traced window."""
    base.mkdir(parents=True)
    route = Route(base, mp, isolated)
    fired: list[str] = []
    request, output = None, kind not in ("scratch_only", "refusal_scratch")
    if "vault" in kind:
        prepare(base)

        def vaulted() -> PublicationRequest:
            return PublicationRequest(
                "op-readback", vault=binding("ambient", base)[0], lock_timeout_s=60
            )

        request = vaulted()
        if kind == "replay_vault":
            assert route.go(request=request).outcome == "completed"
            request = vaulted()
    elif kind in ("occupied", "conflict"):
        route.bind_other("op-first" if kind == "occupied" else "op-readback")
    elif kind == "publish_entry_fault":
        once(mp, f"{COMMIT}.publish_unit" if isolated else f"{PUBLISH}.publish_unit", fired)
    elif kind.startswith("measure"):
        failure = OSError(errno.EIO if kind == "measure_eio" else errno.ENOMEM, "x")

        def measure(*args: Any, **kwargs: Any) -> Any:
            fired.append(kind)
            raise failure

        mp.setattr(f"{PUBLISH}._measure", measure)
    elif kind.startswith("refusal"):
        mp.setattr(f"{COMMIT}.kill_ceiling", lambda: 1)
    elif kind.startswith("readback"):
        assert route.run is not None
        route.run.decodes.fail_on = 1
        route.run.decodes.error = (
            OSError(errno.ENOMEM, "x")
            if kind == "readback_enomem"
            else pa.ArrowInvalid("Unknown error: Wrapping x failed")
        )
    if not traced:
        return route.go(output=output, request=request)
    with tracing(mp) as trace:
        result = route.go(output=output, request=request)
    expect(kind, result)
    if kind.startswith(("publish_entry", "measure")):
        assert fired
    return result, trace


def names_in(trace: Trace) -> set[str]:
    """The innermost enclosing `def` of each traced code object, and the files holding risk."""
    names: set[str] = set()
    index = scan.ModuleIndex()
    scope = set(ms.scope_paths(index).values())
    outside: list[str] = []
    cache: dict[str, Any] = {}
    for filename, line in sorted(trace.functions):
        path = Path(filename)
        rel = path.relative_to(SRC).as_posix()
        if rel not in cache:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mod = scan.module_name(path, SRC)
            cache[rel] = (
                ms.function_spans(tree),
                ms.risky_functions(tree, ms.names_of(index, mod)),
            )
        spans, risky = cache[rel]
        holding = [s for s in spans if s[1] <= line <= s[2]]
        if not holding:
            continue
        qualified = min(holding, key=lambda s: s[2] - s[1])[0]
        names.add(qualified.rsplit(".", 1)[-1])
        if qualified in risky and rel not in scope:
            outside.append(f"{rel}: {qualified}")
    assert not outside, (
        "a handler the window runs through is outside the guard's SCOPE:\n" + "\n".join(outside)
    )
    return names


@pytest.mark.parametrize(
    ("kind", "isolated"), [(k, r) for k, (routes, _) in SCENARIOS.items() for r in routes]
)
def test_a19_the_guard_scope_covers_the_traced_window(
    tmp_path: Path,
    scratch: Path,  # noqa: F811
    kind: str,
    isolated: bool,
) -> None:
    import nacl.bindings  # noqa: F401  (the vault scenarios and the replay sentinel need it)

    with pytest.MonkeyPatch.context() as warm:
        play(kind, isolated, tmp_path / "warm", warm, traced=False)
    with pytest.MonkeyPatch.context() as live:
        result, trace = play(kind, isolated, tmp_path / "traced", live, traced=True)
    assert result is not None
    assert (trace.starts, trace.stops, trace.threads) == (1, 1, 0)
    found = names_in(trace)
    assert SCENARIOS[kind][1] <= found, sorted(SCENARIOS[kind][1] - found)


def test_a19_a_scope_entry_the_trace_needs_cannot_be_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = Trace({(str(SRC / "reason_adapter.py"), _first_line("reason_from_exception"))})
    monkeypatch.setattr(ms, "scope_paths", lambda index, scope=ms.SCOPE: {SRC / "x.py": "x.py"})
    with pytest.raises(AssertionError, match="reason_from_exception"):
        names_in(trace)


def _first_line(name: str) -> int:
    tree = ast.parse((SRC / "reason_adapter.py").read_text(encoding="utf-8"))
    return next(first for qualified, first, _ in ms.function_spans(tree) if qualified == name)


# -- A20: the other callers of publish_unit ----------------------------------------------------


def measurement_memory_fault(mp: pytest.MonkeyPatch) -> list[str]:
    fired: list[str] = []

    def measure(*args: Any, **kwargs: Any) -> Any:
        fired.append("measure")
        raise pa.ArrowMemoryError(CANARY)

    mp.setattr(f"{PUBLISH}._measure", measure)
    return fired


def test_a20_the_transactional_sink_raises_a_measurement_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.execution.publication._sink_support import sink_factory, stages, table

    fired = measurement_memory_fault(monkeypatch)
    with sink_factory("ambient", tmp_path) as make, reason_adapter.failure_scope() as scope:
        sink = make()
        sink.write("customers", table("A"))
        with pytest.raises(MemoryError):
            sink.commit()
    assert fired and not (tmp_path / "out").exists() and stages(tmp_path) == []
    assert scope.first is not None and scope.first.code == "process_out_of_memory"


def test_a20_the_delivery_stage_raises_a_measurement_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = DeliveryRun(tmp_path)
    stage = run.open()
    run.stage_files(stage)
    fired = measurement_memory_fault(monkeypatch)
    with pytest.raises(MemoryError):
        deliver(stage)
    assert fired and not (run.folder / "r1" / DESCRIPTOR).exists() and run.litter() == []
