"""`DeliveryStage.reserve` and `StagedMember` (DELIV E2b: AT-63, AT-64, AT-65, AT-67, AT-68).

Completion is an explicit call, a name collision is the file system's own `EEXIST`, and only a
file the stage claimed is ever removed from the unit.
"""

from __future__ import annotations

import errno
import mmap
import os
import re
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from decoy_engine.fileaccess._local import _LocalStageDir
from decoy_engine.publication import DeliveryReceipt, PublicationFailed, StageDecision
from decoy_engine.quarantine import guard_quarantine_not_aliasing_committed_table
from tests.unit.publication._publish_support import DESCRIPTOR, descriptor
from tests.unit.publication._stage_support import (
    FAILED,
    Run,
    deliver,
    put,
    unit_dir,
    volume_is_case_sensitive,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")

BOTH = StageDecision(True, frozenset({"a", "b"}))


def _bound(run: Run, run_id: str = "r1") -> dict[str, bytes]:
    folder = run.folder / run_id
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name not in (DESCRIPTOR, ".decoy-publication-stage")
    }


# -- AT-63: explicit completion ---------------------------------------------------------------


def test_nothing_exists_at_the_writer_path_until_the_writer_writes(run: Run) -> None:
    stage = run.open()
    member = stage.reserve("a", "d/a.csv")
    assert not member.path.exists() and member.path.parent.is_dir()
    assert member.path.name == "a.csv"
    reserved = stage.staged_path("a")
    assert reserved != member.path and reserved.parent.name == "d"
    member.path.write_bytes(b"")  # a zero-byte member is a valid member
    member.complete()
    assert stage.staged_path("a") == reserved
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {"d/a.csv": b""}
    assert run.litter() == []  # the slots stage is gone


def test_a_delivered_table_whose_member_was_never_completed_binds_nothing(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    stage.reserve("b", "b.csv").path.write_bytes(b"written but never completed\n")
    assert deliver(stage) == DeliveryReceipt("nothing", FAILED)
    assert not (run.folder / "r1" / DESCRIPTOR).exists() and not run.latest.exists()
    assert run.litter() == []


def test_a_non_delivered_member_that_was_never_completed_is_discarded(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    stage.reserve("b", "b.csv")
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {"a.csv": b"a\n"} and run.litter() == []


def test_completing_with_no_file_is_a_value_free_error(run: Run) -> None:
    stage = run.open()
    member = stage.reserve("a", "secret-name.csv")
    with pytest.raises(ValueError) as caught:
        member.complete()
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "secret" not in str(caught.value)
    stage.abort()
    assert run.litter() == []


def test_a_spill_file_under_stage_dir_is_never_a_member(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    (stage.stage_dir() / "spill.tmp").write_bytes(b"spill")
    assert stage.stage_dir() != unit_dir(stage)
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {"a.csv": b"a\n"} and run.litter() == []
    again = run.open("r2")
    (again.stage_dir() / "spill.tmp").write_bytes(b"spill")
    again.abort()
    assert run.litter() == []


def _sink_for(stage: Any) -> Any:
    return SimpleNamespace(committed_table_path=stage.staged_path)


def test_a_quarantine_destination_equal_to_a_table_destination_is_refused(run: Run) -> None:
    """The alias guard compares logical destinations in the unit stage; the writers' slots differ."""
    stage = run.open()
    table = stage.reserve("a", "x.csv")
    table.path.write_bytes(b"table bytes\n")
    table.complete()
    with pytest.raises(ValueError):  # a second reservation of one destination
        stage.reserve("q", "x.csv", "quarantine")
    logical = str(stage.staged_path("a"))
    with pytest.raises(ValueError):
        guard_quarantine_not_aliasing_committed_table(_sink_for(stage), ["a"], logical)
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {"x.csv": b"table bytes\n"}


def test_a_distinct_quarantine_destination_binds_with_rows_and_is_omitted_without(
    run: Run,
) -> None:
    stage = run.open()
    put(stage, "a", "x.csv", b"table\n")
    sidecar = stage.reserve("q", "quarantine/q.jsonl", "quarantine")
    guard_quarantine_not_aliasing_committed_table(
        _sink_for(stage), ["a"], str(stage.staged_path("q"))
    )
    sidecar.path.write_bytes(b'{"row": 1}\n')
    sidecar.complete()
    assert deliver(stage, StageDecision(True, frozenset({"a", "q"}))) == DeliveryReceipt(
        "delivered"
    )
    assert _bound(run) == {"x.csv": b"table\n", "quarantine/q.jsonl": b'{"row": 1}\n'}

    zero = run.open("r2")
    put(zero, "a", "x.csv", b"table\n")
    zero.reserve("q", "quarantine/q.jsonl", "quarantine").omit()  # the engine made no sidecar
    assert deliver(zero, StageDecision(True, frozenset({"a", "q"}))) == DeliveryReceipt("delivered")
    assert _bound(run, "r2") == {"x.csv": b"table\n"}
    paths = [m["path"] for m in descriptor(run.folder / "r2")["artifacts"]]
    assert paths == ["x.csv"] and not (run.folder / "r2" / "quarantine").exists()


def test_a_member_that_was_claimed_cannot_be_omitted(run: Run) -> None:
    stage = run.open()
    member = put(stage, "a", "a.csv", b"a\n")
    with pytest.raises(RuntimeError):
        member.omit()


def test_an_omitted_required_member_is_not_silent(run: Run) -> None:
    """Omission is the sink's explicit call; a reservation nobody completed still fails."""
    stage = run.open()
    stage.reserve("a", "a.csv")
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt(
        "nothing", FAILED
    )


# -- AT-64: writer shapes and full-length names -----------------------------------------------


def _append(path: Path) -> None:
    with open(path, "ab") as fh:
        fh.write(b"append\n")


def _exclusive(path: Path) -> None:
    with open(path, "xb") as fh:
        fh.write(b"exclusive\n")


def _replace(path: Path) -> None:
    tmp = path.parent / "writer.tmp"
    tmp.write_bytes(b"replaced\n")
    tmp.chmod(0o644)
    os.replace(tmp, path)


def _mapped(path: Path) -> None:
    with open(path, "w+b") as fh:
        fh.truncate(7)
        with mmap.mmap(fh.fileno(), 7) as view:
            view[:] = b"mapped\n"


@pytest.mark.parametrize(
    ("writer", "data"),
    [
        (_append, b"append\n"),
        (_exclusive, b"exclusive\n"),
        (_replace, b"replaced\n"),
        (_mapped, b"mapped\n"),
    ],
)
def test_every_writer_shape_is_bound_owner_only_with_one_link(
    run: Run, writer: Any, data: bytes
) -> None:
    stage = run.open()
    member = stage.reserve("a", "a.csv")
    writer(member.path)
    member.complete()
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    bound = run.folder / "r1" / "a.csv"
    st = bound.stat()
    assert bound.read_bytes() == data
    assert stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1
    assert [p.name for p in (run.folder / "r1").iterdir() if p.suffix == ".tmp"] == []


def test_a_failed_writer_is_never_bound(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    member = stage.reserve("b", "b.csv")
    with open(member.path, "wb") as fh:
        fh.write(b"half")
    member.fail()
    assert not member.path.exists()
    assert deliver(stage) == DeliveryReceipt("nothing", FAILED)
    assert not (run.folder / "r1" / DESCRIPTOR).exists() and run.litter() == []


def test_a_maximum_length_basename_is_delivered_unchanged(run: Run) -> None:
    name = "n" * 251 + ".csv"
    assert len(name.encode()) == 255
    stage = run.open()
    member = stage.reserve("a", f"d/{name}")
    assert member.path.name == name and re.fullmatch(r"s\d+", member.path.parent.name)
    member.path.write_bytes(b"long\n")
    member.complete()
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {f"d/{name}": b"long\n"}


# -- AT-65: names the target file system decides --------------------------------------------


@pytest.fixture
def sensitive(run: Run) -> bool:
    return volume_is_case_sensitive(run.folder)


def test_reserving_one_path_twice_or_a_file_and_its_folder_is_refused(run: Run) -> None:
    stage = run.open()
    stage.reserve("a", "a")
    for table, rel in (("a", "a"), ("b", "a/b"), ("b", "a")):
        with pytest.raises(ValueError) as caught:
            stage.reserve(table, rel)
        assert caught.value.__context__ is None
    stage.reserve("a", "d/x.csv")
    with pytest.raises(ValueError):
        stage.reserve("b", "d")


def test_a_recorded_folder_is_reused_by_its_exact_name(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[str] = []
    real = _LocalStageDir.create_dir

    def spy(self: _LocalStageDir, component: str) -> Any:
        made.append(component)
        return real(self, component)

    monkeypatch.setattr(_LocalStageDir, "create_dir", spy)
    stage = run.open()
    put(stage, "a", "d/x.csv", b"x\n")
    put(stage, "b", "d/y.csv", b"y\n")
    assert made.count("d") == 1
    assert deliver(stage) == DeliveryReceipt("delivered")
    assert _bound(run) == {"d/x.csv": b"x\n", "d/y.csv": b"y\n"}


def test_case_variants_follow_the_volume_and_the_winner_is_never_removed(
    run: Run, sensitive: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[str] = []
    real = _LocalStageDir.remove

    def spy(self: _LocalStageDir, component: str) -> None:
        removed.append(component)
        real(self, component)

    monkeypatch.setattr(_LocalStageDir, "remove", spy)
    stage = run.open()
    upper, lower = stage.reserve("a", "A.csv"), stage.reserve("b", "a.csv")
    upper.path.write_bytes(b"first\n")
    lower.path.write_bytes(b"second\n")
    upper.complete()
    if sensitive:
        lower.complete()
        want, decision = {"A.csv": b"first\n", "a.csv": b"second\n"}, BOTH
    else:
        with pytest.raises(PublicationFailed) as caught:
            lower.complete()
        assert caught.value.receipt.os_error == "EEXIST"
        assert caught.value.__context__ is None and "csv" not in str(caught.value)
        want, decision = {"A.csv": b"first\n"}, StageDecision(True, frozenset({"a"}))
    assert deliver(stage, decision) == DeliveryReceipt("delivered")
    assert _bound(run) == want
    assert "a.csv" not in removed  # a reservation that was never claimed authorizes no removal


def test_an_excluded_claimed_member_and_its_empty_folders_are_pruned(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    put(stage, "b", "x/y/b.csv", b"b\n")
    assert deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    assert _bound(run) == {"a.csv": b"a\n"} and not (run.folder / "r1" / "x").exists()


@pytest.mark.parametrize("folder_first", [True, False])
def test_a_folder_and_a_file_whose_names_differ_by_case(
    run: Run, sensitive: bool, folder_first: bool
) -> None:
    stage = run.open()

    def folder() -> Any:
        return put(stage, "a", "D/x.csv", b"inside\n")

    def file() -> Any:
        return put(stage, "b", "d", b"file\n")

    first, second = (folder, file) if folder_first else (file, folder)
    first()
    if sensitive:
        second()
        assert deliver(stage) == DeliveryReceipt("delivered")
        assert _bound(run) == {"D/x.csv": b"inside\n", "d": b"file\n"}
        return
    with pytest.raises(PublicationFailed) as caught:
        second()
    assert caught.value.receipt.os_error == "EEXIST" and caught.value.__context__ is None
    keep = "a" if folder_first else "b"
    assert deliver(stage, StageDecision(True, frozenset({keep}))) == DeliveryReceipt("delivered")
    assert len(_bound(run)) == 1


# -- AT-67: seals are re-checked under the lock ------------------------------------------------


def _swap_inode(path: Path) -> None:
    fresh = path.parent / "fresh"  # made while the old inode lives, so the numbers differ
    fresh.write_bytes(path.read_bytes())
    fresh.chmod(0o600)
    os.replace(fresh, path)


def _hard_link(path: Path) -> None:
    os.link(path, path.parent / "second-name")


def _loosen(path: Path) -> None:
    path.chmod(0o644)


def _remove(path: Path) -> None:
    path.unlink()


@pytest.mark.parametrize("tamper", [_swap_inode, _hard_link, _loosen, _remove])
def test_a_claimed_file_that_changes_before_the_bind_gives_nothing(run: Run, tamper: Any) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    put(stage, "b", "b.csv", b"b\n")
    tamper(unit_dir(stage) / "a.csv")
    assert deliver(stage) == DeliveryReceipt("nothing", FAILED)
    assert not (run.folder / "r1" / DESCRIPTOR).exists() and not run.latest.exists()
    assert list((run.folder / "r1").iterdir()) == [] and run.litter() == []


def test_two_members_that_share_one_inode_give_nothing(run: Run) -> None:
    stage = run.open()
    put(stage, "a", "a.csv", b"a\n")
    put(stage, "b", "b.csv", b"b\n")
    root = unit_dir(stage)
    (root / "b.csv").unlink()
    os.link(root / "a.csv", root / "b.csv")
    assert deliver(stage) == DeliveryReceipt("nothing", FAILED)
    assert not run.latest.exists()


def test_an_untouched_unit_delivers_after_the_seal_check(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    assert deliver(stage) == DeliveryReceipt("delivered")


# -- AT-68: reserve rolls back its own folders --------------------------------------------------


def _fail_nth_unit_folder(monkeypatch: pytest.MonkeyPatch, stage: Any, nth: int) -> None:
    real = _LocalStageDir.create_dir
    unit = str(unit_dir(stage))
    calls = {"n": 0}

    def create(self: _LocalStageDir, component: str) -> Any:
        if str(self._dir).startswith(unit):
            calls["n"] += 1
            if calls["n"] == nth:
                raise PermissionError(errno.EACCES, "/secret/path")
        return real(self, component)

    monkeypatch.setattr(_LocalStageDir, "create_dir", create)


def _tree(stage: Any) -> list[str]:
    root = unit_dir(stage)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.name[0] != ".")


@pytest.mark.parametrize("nth", [2, 3])
def test_a_failed_folder_removes_only_the_folders_this_call_made(
    run: Run, monkeypatch: pytest.MonkeyPatch, nth: int
) -> None:
    stage = run.open()
    _fail_nth_unit_folder(monkeypatch, stage, nth)
    with pytest.raises(PublicationFailed) as caught:
        stage.reserve("t", "a/b/c/x.csv")
    assert caught.value.receipt.os_error == "EACCES"
    assert caught.value.__context__ is None and "secret" not in str(caught.value)
    assert _tree(stage) == []
    monkeypatch.undo()
    put(stage, "t", "a/b/c/x.csv", b"x\n")  # the same path works afterwards
    assert deliver(stage, StageDecision(True, frozenset({"t"}))) == DeliveryReceipt("delivered")


def test_a_failed_slot_removes_the_folders_and_keeps_earlier_reservations(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = run.open()
    put(stage, "t", "a/y.csv", b"y\n")

    def refuse(component: str) -> Any:
        raise PermissionError(errno.EACCES, "/secret/path")

    monkeypatch.setattr(stage._slots, "create_dir", refuse)
    with pytest.raises(PublicationFailed) as caught:
        stage.reserve("u", "a/z/w.csv")
    assert caught.value.__context__ is None
    assert _tree(stage) == ["a", "a/y.csv"]  # `a` was made by the earlier call and stays
    monkeypatch.undo()
    put(stage, "u", "a/z/w.csv", b"w\n")
    assert deliver(stage, StageDecision(True, frozenset({"t", "u"}))) == DeliveryReceipt(
        "delivered"
    )
    assert _bound(run) == {"a/y.csv": b"y\n", "a/z/w.csv": b"w\n"}


def test_a_rollback_that_fails_does_not_replace_the_refusal(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = run.open()

    def refuse(component: str) -> Any:
        raise PermissionError(errno.EACCES, "/secret/path")

    def no_remove(self: Any, component: str) -> None:
        raise PermissionError(errno.EPERM, "/secret/rollback")

    monkeypatch.setattr(stage._slots, "create_dir", refuse)
    monkeypatch.setattr(_LocalStageDir, "remove", no_remove)
    with pytest.raises(PublicationFailed) as caught:
        stage.reserve("t", "a/b/x.csv")
    assert caught.value.receipt.os_error == "EACCES"
    assert "secret" not in str(caught.value) and caught.value.__context__ is None
