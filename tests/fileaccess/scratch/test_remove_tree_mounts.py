"""Tree removal fails closed when the mounts under it cannot be known, compares every root with
its held parent, and removes the proof marker of a stage or arena last."""

from __future__ import annotations

import errno
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess
from decoy_engine.fileaccess import FileRequest, FileRole, ScratchArena
from decoy_engine.fileaccess._fdtree import STAGE_MARKER, prove_stage
from decoy_engine.fileaccess._local import LocalFileAccess
from decoy_engine.fileaccess._scratch import _MARKER as ARENA_MARKER
from decoy_engine.fileaccess._scratch_reports import Disposition
from tests.fileaccess.publication._reclaim_support import make_stage

pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the mount table is Linux"),
    pytest.mark.serial,
]
_fdtree = fileaccess._fdtree


@pytest.fixture(autouse=True)
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_env_clean: None) -> Path:
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def arena() -> Iterator[ScratchArena]:
    with ScratchArena.fresh() as made:
        child = made.create_dir("t")
        os.close(child.create_file("top"))
        sub = child.create_dir("sub")
        os.close(sub.create_file("leaf"))
        yield made


def _leaf(arena: ScratchArena) -> Path:
    return Path(arena.local_path()) / "t" / "sub" / "leaf"


def _escape(path: str) -> str:
    for raw, code in (("\\", "\\134"), (" ", "\\040"), ("\t", "\\011"), ("\n", "\\012")):
        path = path.replace(raw, code)
    return path


def _table(*points: str) -> str:
    lines = [f"{20 + i} 1 0:{i} / {_escape(p)} rw - tmpfs none rw" for i, p in enumerate(points)]
    return "".join(f"{line}\n" for line in lines)


def _with_table(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(_fdtree, "_read_mount_table", lambda: text)


def test_the_real_table_names_a_real_mount() -> None:
    """Kills `_mount_roots` returning nothing: `/proc` is a mount root under `/proc` itself."""
    fd = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY)
    try:
        found = os.stat("/proc")
        assert (found.st_dev, found.st_ino) in _fdtree._mount_roots(fd)
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "name", ["plain", "a b", "tab\there", "new\nline", "back\\slash", "u\u2028sep"]
)
def test_a_listed_same_device_mount_is_kept(
    arena: ScratchArena, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A bind mount keeps its device, so only the table finds it; every escaped name matches."""
    target = Path(arena.local_path()) / "t" / "sub" / name
    target.mkdir()
    (target / "kept").write_bytes(b"x")
    _with_table(monkeypatch, _table("/", "/proc", str(target)))
    assert arena.remove_tree("t").disposition is Disposition.RETAINED
    assert (target / "kept").is_file()


def test_a_table_with_no_mount_under_the_tree_removes_it(
    arena: ScratchArena, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_table(monkeypatch, _table("/", "/proc", f"{arena.local_path()}-sibling"))
    assert arena.remove_tree("t").disposition is Disposition.REMOVED


def _raise(error: int) -> Callable[..., Any]:
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError(error, os.strerror(error))

    return fail


_UNDISCOVERABLE: dict[str, Callable[[pytest.MonkeyPatch, ScratchArena], None]] = {
    "table_emfile": lambda mp, a: mp.setattr(_fdtree, "_read_mount_table", _raise(errno.EMFILE)),
    "no_proc": lambda mp, a: mp.setattr(_fdtree, "_MOUNTINFO", "/nonexistent/mountinfo"),
    "oversized": lambda mp, a: mp.setattr(_fdtree, "_MOUNTINFO_MAX", 16),
    "unreadable_fd_link": lambda mp, a: mp.setattr(_fdtree, "_PROC_FD", "/nonexistent/fd/"),
    "deleted_base": lambda mp, a: mp.setattr(
        os, "readlink", lambda path: f"{a.local_path()}/t (deleted)"
    ),
    "relative_base": lambda mp, a: mp.setattr(os, "readlink", lambda path: "t"),
    "stat_fails": lambda mp, a: _with_table(mp, _table("/", f"{a.local_path()}/t/gone")),
    "malformed": lambda mp, a: _with_table(mp, _table("/") + "garbage\n"),
    "unknown_host": lambda mp, a: mp.setattr(_fdtree, "_LINUX", False),
}


@pytest.mark.parametrize("cell", sorted(_UNDISCOVERABLE))
def test_undiscoverable_mounts_keep_the_tree(
    arena: ScratchArena, monkeypatch: pytest.MonkeyPatch, cell: str
) -> None:
    _UNDISCOVERABLE[cell](monkeypatch, arena)
    assert arena.remove_tree("t").disposition is Disposition.RETAINED
    assert _leaf(arena).is_file()
    assert (Path(arena.local_path()) / "t" / "top").is_file()


def test_macos_uses_the_device_test_alone(
    arena: ScratchArena, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_fdtree, "_DEVICE_ONLY", True)
    monkeypatch.setattr(_fdtree, "_read_mount_table", _raise(errno.EIO))
    assert arena.remove_tree("t").disposition is Disposition.REMOVED


def _other_device(monkeypatch: pytest.MonkeyPatch, path: str | Path) -> None:
    """`fstat` of the directory at `path` reports a device one higher than the real one."""
    ino = os.stat(path).st_ino
    real = os.fstat

    def moved(fd: int) -> os.stat_result:
        found = real(fd)
        if found.st_ino != ino:
            return found
        fields = list(found)
        fields[2] += 1  # st_dev
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", moved)


def test_arena_reclaim_compares_the_root_with_its_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    made = ScratchArena.fresh()
    os.close(made.create_file("f"))
    path = made.local_path()
    _other_device(monkeypatch, path)
    assert made.reclaim().disposition is Disposition.RETAINED
    assert os.path.isfile(os.path.join(path, "f"))
    monkeypatch.undo()


def test_stage_discard_compares_the_root_with_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    req = FileRequest(FileRole.TARGET_OUTPUT, "write", str(out), "targets.t.path")
    txn = LocalFileAccess().output_dir(req).begin("dir", "exclusive", label="publication")
    os.close(txn.create_file("t.parquet"))
    stage = txn.local_stage_path()
    _other_device(monkeypatch, stage)
    txn.abort()
    assert os.path.isfile(os.path.join(stage, "t.parquet"))
    monkeypatch.undo()


class _Listing:
    """A scandir result in a fixed order: the proof marker last, where a naive walk pops it first."""

    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self.entries = sorted(entries, key=lambda e: e.name in (STAGE_MARKER, ARENA_MARKER))

    def __enter__(self) -> list[os.DirEntry[str]]:
        return self.entries

    def __exit__(self, *_exc: object) -> None:
        return None


def _marker_popped_first(monkeypatch: pytest.MonkeyPatch, busy: str) -> None:
    real_scandir, real_unlink = os.scandir, os.unlink

    def scandir(fd: Any) -> _Listing:
        with real_scandir(fd) as found:
            return _Listing(list(found))

    def unlink(name: Any, *, dir_fd: int | None = None) -> None:
        if name == busy:
            raise OSError(errno.EBUSY, os.strerror(errno.EBUSY))
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "unlink", unlink)


def test_a_stopped_stage_removal_keeps_its_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = make_stage(tmp_path, token="0123456789ab", files=("a.parquet", "b.parquet"))
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _marker_popped_first(monkeypatch, busy="a.parquet")
        with pytest.raises(OSError, match="busy"):
            _fdtree._rmtree_fd(stage_fd, parent_fd, STAGE_MARKER)
        monkeypatch.undo()
        assert prove_stage(stage_fd) == "0123456789ab"  # a later reclaim still proves the stage
    finally:
        os.close(stage_fd)
        os.close(parent_fd)


def test_a_stopped_arena_reclaim_keeps_its_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    made = ScratchArena.fresh()
    for name in ("a", "b"):
        os.close(made.create_file(name))
    path = made.local_path()
    _marker_popped_first(monkeypatch, busy="a")
    assert made.reclaim().disposition is Disposition.RETAINED
    monkeypatch.undo()
    assert os.path.isfile(os.path.join(path, ARENA_MARKER))
