"""`CurrentPointer`, `HeldPointer.swap` and `read_value` (DELIV E2a: AT-11, AT-11b, AT-13, AT-54)."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.fileaccess import LockTimeout
from decoy_engine.publication import (
    CurrentPointer,
    LocalPointerStore,
    PointerResult,
    PointerState,
    read_value,
)
from tests.fileaccess.publication._chain_support import anchor_at
from tests.fileaccess.publication._dirmode_support import POLICIES, _output_dir

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")

R1, R3 = PointerState(b"r1\n", b"r1\n"), PointerState(b"r3\n", b"r3\n")


class FakeStore:
    """A scripted `PointerStore`: `answers` are replace_if results, `after` the stored bytes
    once replace_if has been called."""

    def __init__(self, held: bytes | None, answers: list[PointerResult], after: bytes | None):
        self.state = PointerState(held, held)
        self.answers = answers
        self.after = after
        self.reads = 0
        self.calls: list[tuple[PointerState, bytes]] = []

    def locator(self) -> object:
        return "fake"

    def read(self) -> PointerState:
        self.reads += 1
        return self.state

    def replace_if(self, expected: PointerState, new: bytes) -> PointerResult:
        self.calls.append((expected, new))
        self.state = PointerState(self.after, self.after)
        return self.answers.pop(0)


class FakeLock:
    locator = "fake"

    def lock(self, timeout_s: float) -> Any:
        import contextlib

        return contextlib.nullcontext()


def _pointer(store: FakeStore) -> CurrentPointer:
    return CurrentPointer(store, FakeLock())  # type: ignore[arg-type]


def _swap(store: FakeStore, expected: PointerState, new: str = "r2") -> PointerResult:
    with _pointer(store).locked(1.0) as held:
        return held.swap(expected, new)


def test_a_moved_pointer_is_stale_and_the_file_is_untouched() -> None:
    store = FakeStore(b"r3\n", ["stale"], b"r3\n")
    assert _swap(store, R1) == "stale"
    assert store.calls == [(R1, b"r2\n")]
    assert store.reads == 0  # no fresh read supplies a replacement expected state


def test_a_matching_state_calls_replace_if_once_with_the_captured_state() -> None:
    store = FakeStore(b"r1\n", ["replaced"], b"r2\n")
    assert _swap(store, R1) == "replaced"
    assert store.calls == [(R1, b"r2\n")]
    assert store.reads == 0


def test_unknown_then_the_new_value_is_replaced_after_one_outcome_read() -> None:
    store = FakeStore(b"r1\n", ["unknown"], b"r2\n")
    assert _swap(store, R1) == "replaced"
    assert store.reads == 1


def test_unknown_then_another_value_is_uncertain() -> None:
    store = FakeStore(b"r1\n", ["unknown"], b"r9\n")
    assert _swap(store, R1) == "uncertain"
    assert store.reads == 1


def test_conflict_is_returned_with_no_value_compare() -> None:
    store = FakeStore(b"r1\n", ["conflict"], b"r2\n")
    assert _swap(store, R1) == "conflict"
    assert store.reads == 0


def test_the_constructor_refuses_a_store_and_lock_on_different_leaves() -> None:
    other = FakeLock()
    other.locator = "elsewhere"
    with pytest.raises(ValueError, match="different leaves"):
        CurrentPointer(FakeStore(None, [], None), other)  # type: ignore[arg-type]


def test_a_non_ascii_value_is_refused_before_the_store() -> None:
    store = FakeStore(b"r1\n", ["replaced"], b"r2\n")
    with pytest.raises(UnicodeEncodeError):
        _swap(store, R1, "ré")
    assert store.calls == []


def _local(policy: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CurrentPointer, Path]:
    folder = base / "out" / "n"
    folder.mkdir(parents=True)
    if policy == "ambient":
        anchor_at(monkeypatch, base)
    out, _fd = _output_dir(policy, base, "out/n/LATEST")
    return CurrentPointer(LocalPointerStore(out), out), folder / "LATEST"


@pytest.mark.parametrize("policy", POLICIES)
def test_local_swap_with_a_moved_file_is_stale(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer, leaf = _local(policy, tmp_path, monkeypatch)
    leaf.write_bytes(b"r3\n")
    with pointer.locked(1.0) as held:
        assert held.swap(R1, "r2") == "stale"
    assert leaf.read_bytes() == b"r3\n"


@pytest.mark.parametrize("policy", POLICIES)
def test_local_swap_writes_value_and_newline(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer, leaf = _local(policy, tmp_path, monkeypatch)
    assert pointer.read() == PointerState(None, None)
    with pointer.locked(1.0) as held:
        assert held.swap(PointerState(None, None), "r1") == "replaced"
        assert held.swap(pointer.read(), "r2") == "replaced"
    assert leaf.read_bytes() == b"r2\n"


@pytest.mark.parametrize("policy", POLICIES)
def test_a_second_lock_times_out_with_no_store_call_and_a_stale_held_swap_raises(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer, leaf = _local(policy, tmp_path, monkeypatch)
    leaf.write_bytes(b"r1\n")
    second: list[BaseException] = []

    def contender() -> None:
        try:
            with pointer.locked(0.2):
                second.append(AssertionError("took the lock"))
        except BaseException as exc:
            second.append(exc)

    with pointer.locked(1.0) as held:
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join()
    assert len(second) == 1 and isinstance(second[0], LockTimeout)
    with pytest.raises(RuntimeError):
        held.swap(PointerState(b"r1\n", b"r1\n"), "r2")
    assert leaf.read_bytes() == b"r1\n"


@pytest.mark.parametrize(
    ("raw", "value"),
    [(b"r1\n", "r1"), (None, None), (b"../x\n", None), (b"r1\nr2\n", None), (b"r1\nr2", None)],
)
def test_read_value(raw: bytes | None, value: str | None, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine.publication"):
        assert read_value(raw, lambda v: v.isalnum()) == value
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == (0 if raw is None or value is not None else 1)
    assert all("r1" not in r.getMessage() and "x" not in r.getMessage() for r in warned)


def test_read_value_refuses_5_kib_and_missing_newline_and_non_ascii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine.publication"):
        assert read_value(b"a" * 5 * 1024 + b"\n", lambda v: True) is None
        assert read_value(b"r1", lambda v: True) is None
        assert read_value("ré\n".encode(), lambda v: True) is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3
