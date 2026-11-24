"""Interrupts while `deliver` runs (DELIV E2b: AT-70).

After the pointer lock is held, an interrupt is judged by the 4.7 rule 2 re-read, reconciled
exactly once, and only then does the lock go and the interrupt re-raise. Before the lock nothing
is read.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from decoy_engine.fileaccess import LockTimeout
from decoy_engine.publication import DeliveryReceipt
from decoy_engine.publication import _stage as stage_module
from decoy_engine.publication._current import HeldPointer
from tests.unit.publication._stage_support import UNCERTAIN, Run, deliver

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")


class Trace:
    """What happened around one `deliver`: pointer reads and reconciles, in order."""

    def __init__(self, run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
        self.run = run
        self.events: list[str] = []
        self.receipts: list[DeliveryReceipt] = []
        self.contender: list[str] = []
        real = run.pointer.read

        def read() -> Any:
            self.events.append("read")
            return real()

        monkeypatch.setattr(run.pointer, "read", read)

    def contend(self) -> str:
        try:
            with self.run.pointer.locked(0):
                return "free"
        except LockTimeout:
            return "held"

    def reconcile(self, receipt: DeliveryReceipt) -> None:
        self.events.append("reconcile")
        self.receipts.append(receipt)
        self.contender.append(self.contend())


def _interrupt(*args: Any, **kwargs: Any) -> Any:
    raise KeyboardInterrupt


@pytest.fixture
def trace(run: Run, monkeypatch: pytest.MonkeyPatch) -> Trace:
    return Trace(run, monkeypatch)


def _staged(run: Run, trace: Trace) -> Any:
    stage = run.open()
    run.stage_files(stage)
    trace.events.clear()  # `open` read the pointer; the cases count what `deliver` does
    return stage


def _crash_after_real_publish(*args: Any, **kwargs: Any) -> Any:
    stage_module_publish(*args, **kwargs)
    raise KeyboardInterrupt


stage_module_publish = stage_module.publish_unit


@pytest.mark.parametrize(
    ("where", "reads", "want"),
    [
        ("before_visible", 1, DeliveryReceipt("nothing")),
        ("publish_unit", 2, DeliveryReceipt("nothing")),
        ("after_bind", 2, DeliveryReceipt("nothing")),
        ("after_swap", 2, DeliveryReceipt("uncertain", UNCERTAIN)),
    ],
)
def test_an_interrupt_under_the_lock_is_judged_and_reconciled_before_the_lock_goes(
    run: Run,
    trace: Trace,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    reads: int,
    want: DeliveryReceipt,
) -> None:
    stage = _staged(run, trace)
    before: Any = lambda: None
    if where == "before_visible":
        before = _interrupt
    elif where == "publish_unit":
        monkeypatch.setattr(stage_module, "publish_unit", _interrupt)
    elif where == "after_bind":
        monkeypatch.setattr(stage_module, "publish_unit", _crash_after_real_publish)
    else:
        real = HeldPointer.swap

        def swapped(self: HeldPointer, expected: Any, new: str) -> Any:
            real(self, expected, new)
            raise KeyboardInterrupt

        monkeypatch.setattr(HeldPointer, "swap", swapped)
    with pytest.raises(KeyboardInterrupt):
        deliver(stage, before=before, reconcile=trace.reconcile)
    assert trace.receipts == [want]  # reconciled exactly once
    assert trace.contender == ["held"]  # inside the lock
    assert trace.events == ["read"] * reads + ["reconcile"]
    assert trace.contend() == "free"  # and the lock goes after
    assert stage.state == ("delivered" if want.state == "uncertain" else "aborted")
    assert run.litter() == []


def test_an_interrupt_before_the_lock_reads_nothing(
    run: Run, trace: Trace, monkeypatch: Any
) -> None:
    stage = _staged(run, trace)
    monkeypatch.setattr(run.pointer, "locked", _interrupt)
    with pytest.raises(KeyboardInterrupt):
        deliver(stage, reconcile=trace.reconcile)
    assert trace.receipts == [DeliveryReceipt("nothing")]
    assert trace.events == ["reconcile"]  # no read at all
    assert stage.state == "aborted" and run.litter() == []


def test_an_interrupt_before_the_lock_on_a_replay_is_uncertain_with_no_read(
    run: Run, trace: Trace, monkeypatch: Any
) -> None:
    run.latest.write_bytes(b"r1\n")  # the pointer already names this run
    stage = _staged(run, trace)
    monkeypatch.setattr(run.pointer, "locked", _interrupt)
    with pytest.raises(KeyboardInterrupt):
        deliver(stage, reconcile=trace.reconcile)
    assert trace.receipts == [DeliveryReceipt("uncertain", UNCERTAIN)]
    assert trace.events == ["reconcile"]


def test_a_second_interrupt_while_settling_still_releases_the_lock_and_reconciles_once(
    run: Run, trace: Trace
) -> None:
    stage = _staged(run, trace)
    calls: list[int] = []

    def reconcile(receipt: DeliveryReceipt) -> None:
        calls.append(1)
        raise KeyboardInterrupt  # a second interrupt, inside the settle

    with pytest.raises(KeyboardInterrupt):
        deliver(stage, before=_interrupt, reconcile=reconcile)
    assert calls == [1]
    assert trace.contend() == "free"
    assert run.litter() == []
