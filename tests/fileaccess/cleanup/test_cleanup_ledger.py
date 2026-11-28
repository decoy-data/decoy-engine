"""CleanupLedger: record before create, release only after confirmed removal (plan L1-L20)."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from unittest import mock

import pytest

from decoy_engine.fileaccess import _fdtree
from decoy_engine.fileaccess._types import FileAccessUnavailable
from decoy_engine.fileaccess.cleanup import CleanupLedger
from decoy_engine.fileaccess.cleanup import _ledger as led


def _mk(operand: str) -> str:
    os.mkdir(operand)
    return operand


def _snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def test_l1_create_sees_its_own_entry_in_intent(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    seen: list[str] = []

    def create(operand: str) -> None:
        seen.extend(e.state for e in ledger._entries)
        os.mkdir(operand)

    ledger.acquire(tmp_path / "a", create)
    assert seen == [led.INTENT]
    assert ledger._entries[0].state == led.OWNED
    ledger.close()
    assert not (tmp_path / "a").exists()


def test_l2_create_losing_a_race_is_foreign_and_untouched(tmp_path: Path) -> None:
    ledger = CleanupLedger()

    def create(operand: str) -> None:
        os.mkdir(operand)  # a rival made it between the precheck and ours
        raise FileExistsError(errno.EEXIST, "x")

    with pytest.raises(FileExistsError):
        ledger.acquire(tmp_path / "a", create)
    assert ledger._entries[0].state == led.FOREIGN
    ledger.close()
    assert (tmp_path / "a").is_dir()


def test_l3_present_name_is_not_recorded_and_create_never_runs(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    calls: list[str] = []
    ledger = CleanupLedger()
    with pytest.raises(FileExistsError) as info:
        ledger.acquire(tmp_path / "a", calls.append)
    assert info.value.errno == errno.EEXIST
    assert calls == [] and ledger._entries == []


def test_l4_precheck_permission_error_propagates_without_create(tmp_path: Path) -> None:
    calls: list[str] = []
    ledger = CleanupLedger()
    with mock.patch.object(_fdtree, "_lstat", side_effect=PermissionError(errno.EACCES, "x")):
        with pytest.raises(PermissionError):
            ledger.acquire(tmp_path / "a", calls.append)
    assert calls == [] and ledger._entries == []


def test_l6_remove_returns_false_and_keeps_entry_while_present(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    ledger.acquire(tmp_path / "a", _mk)
    with mock.patch.object(_fdtree, "remove_confirmed", return_value=False):
        assert ledger.remove(tmp_path / "a") is False
    assert ledger._entries[0].state == led.OWNED
    ledger.close()
    assert not (tmp_path / "a").exists()


def test_l7_remove_raising_memory_error_keeps_entry_and_close_removes_it(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    ledger.acquire(tmp_path / "a", _mk)
    with mock.patch.object(_fdtree, "remove_confirmed", side_effect=MemoryError):
        with pytest.raises(MemoryError):
            ledger.remove(tmp_path / "a")
    assert ledger._entries[0].state == led.OWNED
    ledger.close()
    assert not (tmp_path / "a").exists()
    assert ledger._entries[0].state == led.RELEASED


def test_l8_close_visits_every_entry_in_both_passes_and_the_memory_error_escapes(
    tmp_path: Path,
) -> None:
    ledger = CleanupLedger()
    for name in ("a", "b", "c"):
        ledger.acquire(tmp_path / name, _mk)
    real = _fdtree.remove_confirmed
    attempts: list[str] = []

    def flaky(path: str, *, record: object = None) -> bool:
        name = os.path.basename(path)
        attempts.append(name)
        if name == "c" and attempts.count("c") == 1:
            raise MemoryError
        if name == "b" and attempts.count("b") == 1:
            return False  # E-as-False: present, retried
        return real(path, record=record)

    with mock.patch.object(_fdtree, "remove_confirmed", flaky):
        with pytest.raises(MemoryError) as info:
            ledger.close()
    assert info.value.__context__ is None
    assert attempts == ["c", "b", "a", "c", "b"]
    assert not any((tmp_path / n).exists() for n in "abc")
    ledger.close()  # a second close is safe


def test_l9_on_release_runs_once_and_a_failure_is_retried(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    seen: list[str] = []

    def release() -> None:
        seen.append(ledger._entries[0].state)
        if len(seen) == 1:
            raise MemoryError

    ledger.acquire(tmp_path / "a", _mk, on_release=release)
    with pytest.raises(MemoryError):
        ledger.close()  # M in pass one, success in pass two
    assert seen == [led.REMOVED, led.REMOVED]
    assert ledger._entries[0].state == led.RELEASED
    ledger.close()
    assert len(seen) == 2


def test_l10_remove_of_an_unrecorded_path_raises_and_touches_nothing(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    with pytest.raises(FileAccessUnavailable):
        CleanupLedger().remove(tmp_path / "x")
    assert (tmp_path / "x").is_dir()


def test_l11_intent_entry_with_absent_path_is_released_without_rmtree(tmp_path: Path) -> None:
    ledger = CleanupLedger()

    def boom(operand: str) -> None:
        raise OSError(errno.ENOSPC, "x")

    with pytest.raises(OSError):
        ledger.acquire(tmp_path / "a", boom)
    assert ledger._entries[0].state == led.INTENT
    with mock.patch.object(_fdtree, "remove_tree") as rmtree:
        ledger.close()
    rmtree.assert_not_called()
    assert ledger._entries[0].state == led.RELEASED


def test_l12_a_symlink_at_the_owned_path_is_not_followed(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep").write_text("k")
    ledger = CleanupLedger()
    ledger.acquire(tmp_path / "a", _mk)
    (tmp_path / "a").rmdir()
    (tmp_path / "a").symlink_to(other)
    ledger.close()
    assert (other / "keep").read_text() == "k"
    assert (tmp_path / "a").is_symlink()
    assert ledger._entries[0].state != led.RELEASED


def test_l14_deferred_slot(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    unbound = ledger.defer()
    bound = ledger.defer()
    answers = iter([False, True])
    bound.confirm = lambda: next(answers)
    ledger.close()
    assert unbound.state == led.RELEASED and bound.state == led.RELEASED


def test_l15_equivalent_spellings_find_the_entry(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    ledger = CleanupLedger()
    ledger.acquire(tmp_path / "x" / "b", _mk)
    assert ledger.remove(f"{tmp_path}/x/./b/") is True
    assert not (tmp_path / "x" / "b").exists()


def test_l17_first_remove_of_a_plain_path_is_true(tmp_path: Path) -> None:
    ledger = CleanupLedger()
    ledger.acquire(tmp_path / "a", _mk)
    assert ledger.remove(tmp_path / "a") is True
    assert ledger._entries[0].state == led.RELEASED and not (tmp_path / "a").exists()


def test_l19_dotdot_after_a_link_is_refused_before_any_callback(tmp_path: Path) -> None:
    base, other = tmp_path / "base", tmp_path / "other"
    (base).mkdir()
    (other / "deep").mkdir(parents=True)
    (base / "victim").write_text("caller data")
    (base / "link").symlink_to(other / "deep")
    before = _snapshot(tmp_path)
    calls: list[str] = []
    ledger = CleanupLedger()
    with pytest.raises(FileAccessUnavailable):
        ledger.acquire(f"{base}/link/../victim", calls.append)
    ledger.close()
    assert calls == [] and ledger._entries == []
    assert _snapshot(tmp_path) == before
    assert not (other / "victim").exists()


def test_l20_the_entry_pins_the_actual_parent_not_the_link(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    (one).mkdir()
    (two / "job").mkdir(parents=True)
    (two / "job" / "keep").write_text("k")
    link = tmp_path / "link"
    link.symlink_to(one)
    ledger = CleanupLedger()
    ledger.acquire(link / "job", _mk)
    st = os.stat(one)
    assert ledger._entries[0].key == (st.st_dev, st.st_ino, "job")
    link.unlink()
    link.symlink_to(two)
    with pytest.raises(FileAccessUnavailable):
        ledger.remove(link / "job")
    ledger.close()
    assert not (one / "job").exists()
    assert (two / "job" / "keep").read_text() == "k"
