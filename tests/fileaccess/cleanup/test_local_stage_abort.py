"""`LocalOutputTxn.abort` keeps the stage until its removal is confirmed, and the local stage is
anchored to one physical operand at creation (plan 4d)."""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.fileaccess import FileRequest, FileRole, _fdtree, _local
from decoy_engine.fileaccess._local import LocalFileAccess

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX stage")


def _txn(target: Path, label: Any = "publication") -> _local.LocalOutputTxn:
    return _local.LocalOutputTxn(target, "dir", "exclusive", label)


def _fail_removal(monkeypatch: pytest.MonkeyPatch, times: int | None) -> list[str]:
    """Make `_fdtree.remove_tree` raise ENOSPC `times` times (None: every call)."""
    fired: list[str] = []
    real = _fdtree.remove_tree

    def remove(path: Any) -> None:
        if times is None or len(fired) < times:
            fired.append(str(path))
            raise OSError(errno.ENOSPC, "x")
        real(path)

    monkeypatch.setattr(_fdtree, "remove_tree", remove)
    return fired


def test_a_removal_that_fails_keeps_the_stage_and_the_next_abort_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _txn(tmp_path / "out")
    stage = Path(txn.local_stage_path())
    fired = _fail_removal(monkeypatch, 1)
    txn.abort()
    assert len(fired) == 1
    assert stage.is_dir() and txn.local_stage_path() == str(stage)  # still owned, still named
    assert txn._held.fd == -1  # the lock descriptor is released either way
    txn.abort()
    assert not stage.exists() and txn._stage is None


def test_a_removal_that_leaves_the_name_present_is_not_taken_as_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _txn(tmp_path / "out")
    stage = Path(txn.local_stage_path())
    monkeypatch.setattr(_fdtree, "remove_tree", lambda p: None)  # claims success, removes nothing
    txn.abort()
    assert stage.is_dir() and txn._stage == stage


def test_persistent_failure_keeps_ownership_across_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _txn(tmp_path / "out")
    stage = Path(txn.local_stage_path())
    fired = _fail_removal(monkeypatch, None)
    for _ in range(3):
        txn.abort()
    assert len(fired) == 3 and stage.is_dir()
    monkeypatch.undo()
    txn.abort()
    assert not stage.exists()


def test_a_finished_transaction_with_nothing_left_aborts_as_a_no_op(tmp_path: Path) -> None:
    txn = _txn(tmp_path / "out")
    txn.publish()
    assert txn._stage is None
    txn.abort()
    assert (tmp_path / "out").is_dir()  # the published directory is not the stage


# -- anchoring ---------------------------------------------------------------------------------


def _begin(locator: str) -> _local.LocalOutputTxn:
    req = FileRequest(FileRole.VAULT, "write", locator, "out")
    return LocalFileAccess().output_dir(req).begin("dir", "exclusive", label="publication")


def test_a_relative_target_is_anchored_before_the_stage_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here, elsewhere = tmp_path / "A", tmp_path / "B"
    here.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(here)
    out = LocalFileAccess().output_dir(FileRequest(FileRole.VAULT, "write", "out", "out"))
    assert out.display == out.locator == "out"  # the public spelling is kept
    monkeypatch.chdir(elsewhere)
    txn = out.begin("dir", "exclusive", label="publication")
    stage = Path(txn.local_stage_path())
    assert stage.is_absolute() and stage.parent == here.resolve()
    assert os.listdir(elsewhere) == []
    txn.abort()
    assert not stage.exists()


def test_the_stage_operand_is_the_physical_parent_not_the_spelling(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    txn = _begin(str(tmp_path / "link" / "out"))
    stage = Path(txn.local_stage_path())
    assert stage.parent == real.resolve() and stage.is_dir()
    txn.abort()


def test_a_parent_spelling_with_a_link_then_dotdot_follows_the_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep = tmp_path / "A" / "real" / "deep"
    deep.mkdir(parents=True)
    (tmp_path / "A" / "link").symlink_to(deep)
    monkeypatch.chdir(tmp_path / "A")
    txn = _begin("link/../out")  # the kernel reads this as A/real/out
    stage = Path(txn.local_stage_path())
    assert stage.parent == (tmp_path / "A" / "real").resolve()
    assert not any(p.name.startswith("._decoy") for p in (tmp_path / "A").iterdir())
    txn.abort()
