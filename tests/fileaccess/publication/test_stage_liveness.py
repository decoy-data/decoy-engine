"""F26 E1: every `publication` stage holds its liveness lock and carries its interior proof.

Plan `docs/plans/2026-11-16-f26-v1-rescope.md` (revision 6.1) 3.1, G1(d), G2(a) and 6.1 rows
AT-E1 and AT-E1b. The owner holds `flock(LOCK_SH)` on the stage descriptor from creation until
the stage is bound, aborted or collected, as the systemd-tmpfiles aging rule expects; a cleaner's
`LOCK_EX|LOCK_NB` therefore fails while the run lives. The marker names and bytes are literals
here on purpose: they are a frozen contract (plan "Frozen contracts").
"""

from __future__ import annotations

import errno
import fcntl
import gc
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.fileaccess.publication._chain_support import (
    STAGE_GLOB,
    UNIT_BYTES,
    UNIT_FILE,
    output_dir,
    stage_unit,
)
from tests.fileaccess.publication._dirmode_support import POLICIES
from tests.fileaccess.support import fd_path
from tests.unit.publication._publish_support import close_root, tables

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX liveness lock")

MARKER = ".decoy-publication-stage"
MAGIC = b"decoy-publication-stage-v1:"
PENDING = "._decoy_publication_pending_"


@pytest.fixture
def out_factory(tmp_path: Path) -> Iterator[Callable[[str, str], Any]]:
    roots: list[int] = []

    def make(policy: str, rel: str = "out") -> Any:
        out, root_fd = output_dir(policy, tmp_path, rel)
        roots.append(root_fd)
        return out

    yield make
    for fd in roots:
        close_root(fd)


def _stage(parent: Path) -> Path:
    (stage,) = parent.glob(STAGE_GLOB)
    return stage


def _exclusive_free(path: Path) -> bool:
    """Whether another open file description can take `LOCK_EX|LOCK_NB` on `path` now."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


@pytest.mark.parametrize("end", ["publish", "abort", "collect"])
@pytest.mark.parametrize("policy", POLICIES)
def test_publication_stage_holds_shared_lock(
    tmp_path: Path, policy: str, end: str, out_factory: Callable[..., Any]
) -> None:
    txn = out_factory(policy).begin("dir", "exclusive", label="publication")
    stage_unit(txn)
    stage = _stage(tmp_path)
    held = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)  # outlives the stage name
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if end == "publish":
            txn.publish()
            assert os.fstat(held).st_ino == os.lstat(tmp_path / "out").st_ino  # the bound unit
        elif end == "abort":
            txn.abort()
        else:
            del txn
            gc.collect()
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the owner's lock is gone
    finally:
        os.close(held)
    if end != "collect":
        assert list(tmp_path.glob(STAGE_GLOB)) == []


def _assert_marker(directory: Path, token: str) -> None:
    marker = directory / MARKER
    st = os.lstat(marker)
    assert (oct(st.st_mode), st.st_uid) == (oct(0o100600), os.geteuid())
    assert marker.read_bytes() == MAGIC + token.encode("ascii") + b"\n"


@pytest.mark.parametrize("policy", POLICIES)
def test_publication_stage_marker(
    tmp_path: Path, policy: str, out_factory: Callable[..., Any]
) -> None:
    txn = out_factory(policy).begin("dir", "exclusive", label="publication")
    stage = _stage(tmp_path)
    token = stage.name.removeprefix(PENDING)
    _assert_marker(stage, token)  # present before the caller writes anything
    stage_unit(txn)
    txn.publish()
    _assert_marker(tmp_path / "out", token)  # reserved metadata: it stays in the bound unit
    assert (tmp_path / "out" / UNIT_FILE).read_bytes() == UNIT_BYTES


_HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
time.sleep(float(sys.argv[2]))
"""


@pytest.mark.parametrize("policy", POLICIES)
def test_lock_waits_for_cleaner(
    tmp_path: Path, policy: str, out_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cleaner that holds `LOCK_EX` on a just-made stage is waited for, then the run locks."""
    from decoy_engine.fileaccess import _fdtree

    real = _fdtree.hold_stage_lock
    waited: list[float] = []

    def contended(fd: int) -> bool:
        cleaner = subprocess.Popen(  # noqa: S603 -- static argv: sys.executable and a literal script
            [sys.executable, "-c", _HOLDER, fd_path(fd), "0.6"], stdout=subprocess.PIPE, text=True
        )
        assert cleaner.stdout is not None and cleaner.stdout.readline().strip() == "locked"
        start = time.monotonic()
        try:
            return real(fd)
        finally:
            waited.append(time.monotonic() - start)
            cleaner.wait(30)

    monkeypatch.setattr(_fdtree, "hold_stage_lock", contended)
    txn = out_factory(policy).begin("dir", "exclusive", label="publication")
    assert waited and waited[0] >= 0.3  # blocked behind the cleaner, not refused
    assert not _exclusive_free(_stage(tmp_path))  # and ends locked
    stage_unit(txn)
    txn.publish()
    assert (tmp_path / "out" / UNIT_FILE).read_bytes() == UNIT_BYTES


def _unit_bytes(leaf: Path) -> dict[str, bytes]:
    """A bound unit's files; the marker's token is random per stage, so only its shape counts."""
    found = {p.name: p.read_bytes() for p in sorted(leaf.iterdir()) if p.name != MARKER}
    marker = (leaf / MARKER).read_bytes()
    found[MARKER] = marker[: len(MAGIC)] + b"#" * (len(marker) - len(MAGIC))
    return found


def _force_flock(monkeypatch: pytest.MonkeyPatch, raises: list[OSError]) -> list[int]:
    """`flock` on a publication stage descriptor raises each of `raises` in turn, then works.
    Every other lock (the destination lock, arenas) is the real call. Returns the stage calls."""
    real = fcntl.flock
    calls: list[int] = []

    def flock(fd: int, operation: int) -> None:
        if os.path.basename(fd_path(fd)).startswith(PENDING):
            calls.append(operation)
            if raises:
                raise raises.pop(0)
        real(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    return calls


@pytest.mark.parametrize("code", ["ENOTSUP", "ENOLCK", "EINVAL", "EIO"])
@pytest.mark.parametrize("policy", POLICIES)
def test_lock_unsupported_publish_unchanged(
    tmp_path: Path,
    policy: str,
    code: str,
    out_factory: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any errno but `EINTR` leaves the run unlocked and its unit exactly what it would be."""
    from decoy_engine.publication import PublicationRequest, publish_tables

    control = publish_tables(out_factory(policy, "a"), tables("one"), PublicationRequest("op-1"))
    num = getattr(errno, code)
    calls = _force_flock(monkeypatch, [OSError(num, os.strerror(num))])
    txn = out_factory(policy, "b").begin("dir", "exclusive", label="publication")
    assert calls == [fcntl.LOCK_SH]  # non-vacuity: the stage lock was the call that failed
    assert _exclusive_free(_stage(tmp_path))  # unlocked, and the run goes on
    txn.abort()
    forced = publish_tables(out_factory(policy, "b"), tables("one"), PublicationRequest("op-1"))
    assert (
        (forced.outcome, forced.durable)
        == (control.outcome, control.durable)
        == (
            "published",
            True,
        )
    )
    assert _unit_bytes(tmp_path / "b") == _unit_bytes(tmp_path / "a")


@pytest.mark.parametrize("policy", POLICIES)
def test_lock_interrupted_once_ends_locked(
    tmp_path: Path, policy: str, out_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _force_flock(monkeypatch, [InterruptedError(errno.EINTR, os.strerror(errno.EINTR))])
    txn = out_factory(policy).begin("dir", "exclusive", label="publication")
    assert calls == [fcntl.LOCK_SH, fcntl.LOCK_SH]  # retried after EINTR
    assert not _exclusive_free(_stage(tmp_path))
    txn.abort()
