"""DELIV E2f (AT-61): `StageDir.open_subdir` and `StageDir.entries` on every stage implementor.

The strict and ambient output stages and the scratch arena share one read-only view
(`_durable._ReadOnlyStageDir`) and one no-follow listing (`_durable.entries_at`).
"""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.publication._publish_support import POLICIES, close_root, make_out

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX stage traversal")


@pytest.fixture(params=[*POLICIES, "scratch"])
def stage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[Any, Path]]:
    """One stage with a folder `d`, a file `f` and a nested file `d/g`, plus its disk path."""
    if request.param == "scratch":
        from decoy_engine.fileaccess import ScratchArena

        with ScratchArena.fresh(under=tmp_path) as arena:
            root = Path(arena.local_path())
            yield _fill(arena), root
        return
    base = tmp_path / "root"
    base.mkdir()
    out, root_fd = make_out(request.param, base, "unit")
    txn = out.begin("dir", "exclusive", label="publication")
    try:
        (pending,) = sorted(base.glob("._decoy_publication_pending_*"))
        yield _fill(txn), pending
    finally:
        txn.abort()
        close_root(root_fd)


def _fill(txn: Any) -> Any:
    os.close(txn.create_file("f"))
    child = txn.create_dir("d")
    os.close(child.create_file("g"))
    return txn


def test_open_subdir_returns_read_only_view_over_a_real_folder(stage: tuple[Any, Path]) -> None:
    txn, _ = stage
    view = txn.open_subdir("d")
    assert [e.name for e in view.entries()] == ["g"]
    fd = view.open_file("g")
    os.close(fd)
    with pytest.raises(Exception) as caught:
        view.create_file("x")
    assert type(caught.value).__name__ == "FileAccessUnavailable"


def test_open_subdir_refuses_link_file_and_dotdot(stage: tuple[Any, Path]) -> None:
    txn, root = stage
    outside = root.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret").write_bytes(b"s")
    os.symlink(outside, root / "lnk")
    with pytest.raises(OSError) as caught:
        txn.open_subdir("lnk")
    assert caught.value.errno in (errno.ELOOP, errno.ENOTDIR)
    with pytest.raises(OSError) as caught:
        txn.open_subdir("f")
    assert caught.value.errno == errno.ENOTDIR
    with pytest.raises(Exception):
        txn.open_subdir("..")


def test_entries_report_kinds_without_following_links(stage: tuple[Any, Path]) -> None:
    txn, root = stage
    os.symlink(root.parent, root / "lnk")
    os.mkfifo(root / "fifo")
    kinds = {e.name: (e.is_file(), e.is_dir(), e.is_symlink()) for e in txn.entries()}
    assert kinds["f"] == (True, False, False)
    assert kinds["d"] == (False, True, False)
    assert kinds["lnk"] == (False, False, True)
    assert kinds["fifo"] == (False, False, False)
    entry = next(iter(txn.entries()))
    assert entry.is_file(follow_symlinks=True) == entry.is_file()


def test_every_mutation_through_a_view_refuses(stage: tuple[Any, Path]) -> None:
    txn, _ = stage
    view = txn.open_subdir("d")
    for call in (
        lambda: view.create_file("x"),
        lambda: view.create_dir("x"),
        lambda: view.remove("g"),
        lambda: view.rename("g", "h"),
    ):
        with pytest.raises(Exception) as caught:
            call()
        assert type(caught.value).__name__ == "FileAccessUnavailable"
    assert [e.name for e in view.entries()] == ["g"]


def test_use_after_the_stage_ends_refuses_and_closes_the_view(stage: tuple[Any, Path]) -> None:
    txn, _ = stage
    view = txn.open_subdir("d")
    nested = view.open_subdir if False else None  # noqa: F841
    fds_before = len(os.listdir("/proc/self/fd"))
    if hasattr(txn, "abort"):
        txn.abort()
    else:
        txn.reclaim()
    assert len(os.listdir("/proc/self/fd")) < fds_before  # the registered view fd was closed
    for call in (view.entries, lambda: view.open_file("g"), lambda: view.open_subdir("x")):
        with pytest.raises(Exception) as caught:
            call()
        assert type(caught.value).__name__ == "FileAccessUnavailable"
    with pytest.raises(Exception) as caught:
        txn.entries()
    assert type(caught.value).__name__ == "FileAccessUnavailable"
