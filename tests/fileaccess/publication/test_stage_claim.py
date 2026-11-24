"""`StageDir.claim_from` and `seal_of` on every stage implementor, and the link primitive (AT-66).

The strict and ambient output stages and the scratch arena share one claim (`_stage_claim`) and
one no-clobber link (`_durable.link_noclobber_at`); the ambient exclusive publish and the durable
vault publish call that same link.
"""

from __future__ import annotations

import ast
import errno
import logging
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import decoy_engine.fileaccess as fileaccess_pkg
from decoy_engine.fileaccess import (
    FileAccessUnavailable,
    FileSeal,
    LinkUnsupported,
    ScratchArena,
    _durable,
    probe_claim,
)
from tests.fileaccess.publication._dirmode_support import POLICIES
from tests.unit.publication._publish_support import close_root, make_out

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX stage claims")

UNSUPPORTED = [errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS, errno.EXDEV]
SECRET = "/secret/place"


class Pair:
    """A source stage, a destination stage, and their disk folders."""

    def __init__(self, src: Any, dst: Any, src_dir: Path, dst_dir: Path) -> None:
        self.src, self.dst, self.src_dir, self.dst_dir = src, dst, src_dir, dst_dir

    def write(self, name: str, data: bytes = b"bytes\n", mode: int = 0o644) -> Path:
        fd = self.src.create_file(name)
        os.write(fd, data)
        os.fchmod(fd, mode)
        os.close(fd)
        return self.src_dir / name


@pytest.fixture(params=[*POLICIES, "scratch"])
def pair(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Pair]:
    if request.param == "scratch":
        with ScratchArena.fresh(under=tmp_path) as arena:
            src, dst = arena.create_dir("src"), arena.create_dir("dst")
            yield Pair(src, dst, Path(arena.local_path("src")), Path(arena.local_path("dst")))
        return
    base = tmp_path / "root"
    base.mkdir()
    out, root_fd = make_out(request.param, base, "unit")
    unit = out.begin("dir", "exclusive", label="publication")
    slots = out.begin("dir", "exclusive", label="delivery_slots")
    (slot_dir,) = base.glob("._decoy_delivery_slots_*")
    (unit_dir,) = base.glob("._decoy_publication_pending_*")
    try:
        yield Pair(slots, unit, slot_dir, unit_dir)
    finally:
        unit.abort()
        slots.abort()
        close_root(root_fd)


def _fail_only_when(real: Any, hit: Any, error: BaseException) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if hit(*args, **kwargs):
            raise error
        return real(*args, **kwargs)

    return wrapper


def test_a_claim_moves_the_file_and_seals_the_final_inode(pair: Pair) -> None:
    pair.write("f", b"payload\n", 0o644)
    seal = pair.dst.claim_from(pair.src, "f", "g")
    final = pair.dst_dir / "g"
    st = os.lstat(final)
    assert not (pair.src_dir / "f").exists() and final.read_bytes() == b"payload\n"
    assert stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1
    assert seal == FileSeal(st.st_dev, st.st_ino, 1, stat.S_IFREG | 0o600)
    assert pair.dst.seal_of("g") == seal


def test_a_claim_onto_a_taken_name_keeps_both_files(pair: Pair) -> None:
    pair.write("f", b"new\n")
    fd = pair.dst.create_file("g")
    os.write(fd, b"incumbent\n")
    os.close(fd)
    before = os.lstat(pair.dst_dir / "g")
    with pytest.raises(FileExistsError) as caught:
        pair.dst.claim_from(pair.src, "f", "g")
    assert caught.value.__context__ is None
    assert (pair.src_dir / "f").read_bytes() == b"new\n"
    assert (pair.dst_dir / "g").read_bytes() == b"incumbent\n"
    assert os.lstat(pair.dst_dir / "g").st_ino == before.st_ino


@pytest.mark.parametrize("kind", ["symlink", "fifo", "folder"])
def test_a_source_that_is_not_a_regular_file_is_refused_before_the_link(
    pair: Pair, kind: str
) -> None:
    target = pair.src_dir / "f"
    if kind == "symlink":
        (pair.src_dir / "real").write_bytes(b"real")
        os.symlink(pair.src_dir / "real", target)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    with pytest.raises(FileAccessUnavailable):
        pair.dst.claim_from(pair.src, "f", "g")
    assert os.path.lexists(target) and not os.path.lexists(pair.dst_dir / "g")


@pytest.mark.parametrize("step", ["unlink", "open", "fchmod"])
def test_a_fault_after_the_link_leaves_no_final_name(
    pair: Pair, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    pair.write("f")
    error = OSError(errno.EIO, SECRET)
    if step == "unlink":
        monkeypatch.setattr(
            os, "unlink", _fail_only_when(os.unlink, lambda name, **kw: name == "f", error)
        )
    elif step == "open":
        monkeypatch.setattr(
            os, "open", _fail_only_when(os.open, lambda name, *a, **kw: name == "g", error)
        )
    else:
        monkeypatch.setattr(os, "fchmod", _fail_only_when(os.fchmod, lambda fd, mode: True, error))
    with pytest.raises(FileAccessUnavailable) as caught:
        pair.dst.claim_from(pair.src, "f", "g")
    assert SECRET not in str(caught.value) and caught.value.__context__ is None
    assert not os.path.lexists(pair.dst_dir / "g")


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_every_unsupported_link_errno_is_the_one_named_limit(
    pair: Pair, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    pair.write("f")
    monkeypatch.setattr(
        os, "link", _fail_only_when(os.link, lambda *a, **k: True, OSError(code, SECRET))
    )
    with pytest.raises(LinkUnsupported) as caught:
        pair.dst.claim_from(pair.src, "f", "g")
    assert caught.value.errno == code and SECRET not in str(caught.value)
    assert caught.value.__context__ is None
    assert (pair.src_dir / "f").exists() and not os.path.lexists(pair.dst_dir / "g")


def test_a_file_system_that_ignores_chmod_is_the_named_limit(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    pair.write("f")
    monkeypatch.setattr(os, "fchmod", lambda fd, mode: None)
    with pytest.raises(LinkUnsupported):
        pair.dst.claim_from(pair.src, "f", "g")
    assert not os.path.lexists(pair.dst_dir / "g")


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_publish_exclusive_durable_maps_the_same_errnos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    (tmp_path / "stage").write_bytes(b"vault")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(
        os, "link", _fail_only_when(os.link, lambda *a, **k: True, OSError(code, SECRET))
    )
    try:
        with pytest.raises(LinkUnsupported) as caught:
            _durable.publish_exclusive_durable(fd, "stage", "leaf")
    finally:
        os.close(fd)
    assert caught.value.errno == code and not (tmp_path / "leaf").exists()
    assert not (tmp_path / "stage").exists()  # the stage name is still discarded


def test_seal_of_reads_without_following_and_works_on_a_read_only_view(pair: Pair) -> None:
    pair.write("f")
    os.symlink(pair.src_dir / "f", pair.src_dir / "ln")
    seal = pair.src.seal_of("f")
    assert seal is not None and stat.S_ISREG(seal.mode) and seal.nlink == 1
    link = pair.src.seal_of("ln")
    assert link is not None and stat.S_ISLNK(link.mode) and link.ino != seal.ino
    assert pair.src.seal_of("missing") is None
    child = pair.src.create_dir("sub")
    os.close(child.create_file("h"))
    view = pair.src.open_subdir("sub")
    assert view.seal_of("h") is not None and view.seal_of("nope") is None


def _view(pair: Pair, name: str = "h") -> Any:
    child = pair.src.create_dir("sub")
    fd = child.create_file(name)
    os.write(fd, b"read-only source\n")
    os.fchmod(fd, 0o640)
    os.close(fd)
    return pair.src.open_subdir("sub")


def test_a_read_only_source_cannot_be_claimed_into_a_writable_stage(pair: Pair) -> None:
    view = _view(pair)
    with pytest.raises(FileAccessUnavailable):
        pair.dst.claim_from(view, "h", "g")
    held = pair.src_dir / "sub" / "h"
    assert held.read_bytes() == b"read-only source\n" and stat.S_IMODE(held.stat().st_mode) == 0o640
    assert not os.path.lexists(pair.dst_dir / "g")


def test_a_read_only_destination_refuses_a_claim(pair: Pair) -> None:
    pair.write("f", b"keep\n")
    child = pair.dst.create_dir("sub")
    view = pair.dst.open_subdir("sub")
    with pytest.raises(FileAccessUnavailable):
        view.claim_from(pair.src, "f", "g")
    assert (pair.src_dir / "f").read_bytes() == b"keep\n"
    assert not os.path.lexists(pair.dst_dir / "sub" / "g")
    del child


def test_a_source_with_another_hard_link_is_refused_before_any_change(pair: Pair) -> None:
    path = pair.write("f", b"shared\n", 0o644)
    other = pair.src_dir / "other-name"
    os.link(path, other)
    before = os.lstat(path)
    with pytest.raises(FileAccessUnavailable):
        pair.dst.claim_from(pair.src, "f", "g")
    for name in (path, other):
        now = os.lstat(name)
        assert (now.st_ino, stat.S_IMODE(now.st_mode), now.st_nlink) == (before.st_ino, 0o644, 2)
        assert name.read_bytes() == b"shared\n"
    assert not os.path.lexists(pair.dst_dir / "g")


# -- the probe: a mode that really moves from 0644 to 0600 -------------------------------------


def test_the_probe_starts_at_0644_and_must_see_0600(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real = os.fchmod

    def spy(fd: int, mode: int) -> None:
        real(fd, mode)
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))

    monkeypatch.setattr(os, "fchmod", spy)
    probe_claim(pair.src, pair.dst)
    assert modes[-2:] == [0o644, 0o600]
    assert not os.path.lexists(pair.dst_dir / ".decoy-claim-probe")
    assert not os.path.lexists(pair.src_dir / "probe")


def test_a_probe_whose_tightening_chmod_does_nothing_is_refused(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.fchmod
    monkeypatch.setattr(os, "fchmod", lambda fd, mode: None if mode == 0o600 else real(fd, mode))
    with pytest.raises(LinkUnsupported):
        probe_claim(pair.src, pair.dst)
    assert not os.path.lexists(pair.dst_dir / ".decoy-claim-probe")


# -- the ambient exclusive publish shares the link ---------------------------------------------


def _ambient_txn(tmp_path: Path) -> tuple[Any, Path, Any]:
    from decoy_engine.fileaccess import FileRequest, FileRole
    from decoy_engine.fileaccess._local import LocalFileAccess

    target = tmp_path / "side.jsonl"
    req = FileRequest(FileRole.QUARANTINE_OUTPUT, "write", str(target), "quarantine.output_path")
    txn = LocalFileAccess().output_dir(req).begin("file", "exclusive", label="quarantine")
    fd = txn.create_file("side")
    os.write(fd, b"sidecar\n")
    os.close(fd)
    return txn, target, req


def _litter(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if p.name != "side.jsonl")


def test_ambient_exclusive_publish_removes_its_stage_on_success(tmp_path: Path) -> None:
    txn, target, _ = _ambient_txn(tmp_path)
    txn.publish()
    assert target.read_bytes() == b"sidecar\n" and _litter(tmp_path) == []


def test_ambient_exclusive_publish_keeps_the_incumbent_and_raises_a_clean_exists(
    tmp_path: Path,
) -> None:
    txn, target, _ = _ambient_txn(tmp_path)
    target.write_bytes(b"incumbent\n")
    with pytest.raises(FileExistsError) as caught:
        txn.publish()
    assert caught.value.__context__ is None and str(tmp_path) not in str(caught.value)
    assert target.read_bytes() == b"incumbent\n" and _litter(tmp_path) == []
    with pytest.raises(FileAccessUnavailable):
        txn.publish()  # the transaction is finished


def test_ambient_exclusive_publish_after_another_link_error_can_still_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn, target, _ = _ambient_txn(tmp_path)
    monkeypatch.setattr(
        os, "link", _fail_only_when(os.link, lambda *a, **k: True, OSError(errno.EACCES, SECRET))
    )
    with pytest.raises(PermissionError):
        txn.publish()
    monkeypatch.undo()
    assert not target.exists() and _litter(tmp_path) != []
    txn.abort()
    assert _litter(tmp_path) == []


def test_ambient_cleanup_failure_after_the_link_warns_and_keeps_the_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    txn, target, _ = _ambient_txn(tmp_path)
    keep = target.name
    monkeypatch.setattr(
        os,
        "unlink",
        _fail_only_when(
            os.unlink, lambda path, **kw: Path(path).name != keep, OSError(errno.EIO, SECRET)
        ),
    )
    with caplog.at_level(logging.WARNING, logger="decoy_engine.quarantine"):
        txn.publish()
    monkeypatch.undo()
    assert target.read_bytes() == b"sidecar\n" and SECRET not in caplog.text
    assert "failed to remove the staging link" in caplog.text
    with pytest.raises(FileAccessUnavailable):
        txn.publish()


def test_an_ambient_publish_on_a_backend_without_a_descriptor_link_still_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows has no `dir_fd` for `os.link`: the plain two-path call must carry the publish."""
    real = os.link
    seen: list[set[str]] = []

    def path_only(src: Any, dst: Any, **kwargs: Any) -> None:
        seen.append(set(kwargs))
        if kwargs:
            raise NotImplementedError("no descriptor form on this backend")
        real(src, dst)

    monkeypatch.setattr(os, "link", path_only)
    monkeypatch.setattr(os, "supports_dir_fd", frozenset(os.supports_dir_fd - {real}))
    txn, target, _ = _ambient_txn(tmp_path)
    txn.publish()
    # the descriptor form is tried first and answers ENOSYS; the plain two-path call carries it
    assert seen[-1] == set() and set() not in seen[:-1]
    assert target.read_bytes() == b"sidecar\n"
    assert _litter(tmp_path) == []


@pytest.mark.parametrize("code", [errno.EEXIST, *UNSUPPORTED])
def test_the_path_form_maps_errnos_like_the_descriptor_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    def refuse(src: Any, dst: Any, **kwargs: Any) -> None:
        raise OSError(code, SECRET)

    monkeypatch.setattr(os, "link", refuse)
    monkeypatch.setattr(os, "supports_dir_fd", frozenset())
    txn, target, _ = _ambient_txn(tmp_path)
    want = FileExistsError if code == errno.EEXIST else LinkUnsupported
    with pytest.raises(want) as caught:
        txn.publish()
    assert SECRET not in str(caught.value) and caught.value.__context__ is None
    monkeypatch.undo()
    if code != errno.EEXIST:
        txn.abort()
    assert not target.exists() and _litter(tmp_path) == []


def test_only_the_two_registered_sites_call_os_link_in_fileaccess() -> None:
    """Two link sites: the descriptor primitive and the ambient two-path arm. A third is a finding."""
    root = Path(fileaccess_pkg.__file__).parent
    sites: list[tuple[str, str]] = []
    for source in sorted(root.rglob("*.py")):
        tree = ast.parse(source.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                is_link = isinstance(node, ast.Attribute) and node.attr == "link"
                if is_link and isinstance(node.value, ast.Name) and node.value.id == "os":
                    sites.append((source.name, fn.name))
    assert sites == [
        ("_link.py", "link_noclobber_at"),
        ("_local_chain.py", "link_noclobber_beside"),
    ]
