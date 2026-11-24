"""Claiming a finished file into a stage, and reading its seal (DELIV E2b).

Pattern: Maildir delivery (write under `tmp/`, then `link()` into `new/`) and git's
`finalize_object_file` (link, then unlink the temporary name): the file system's own exclusive
`link` decides whether a name is taken, so the stage guesses nothing from sizes, times or
spellings. POSIX `linkat`/`openat` over held directory descriptors is the file-access model
(cap-std `Dir`).

`claim_file_at` moves one regular, singly linked file from a slot name to its final name, then
re-opens the final name with `O_NOFOLLOW`, requires the same inode with one link, sets mode
`0o600` on that descriptor and reads the mode back. A file system that ignores `chmod` or cannot
link is `LinkUnsupported`. Any failure after the link removes the name this call made. The
mixin `StageClaim` gives every stage implementor `claim_from` and `seal_of`; each needs live,
writable authority over both operands before anything is linked, unlinked or chmodded.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Callable
from typing import TYPE_CHECKING

from decoy_engine.fileaccess import _osflags
from decoy_engine.fileaccess._component import validate_component
from decoy_engine.fileaccess._fdtree import _close
from decoy_engine.fileaccess._link import CREATOR_KEY, LINK_UNSUPPORTED, link_noclobber_at
from decoy_engine.fileaccess._types import (
    FileAccessUnavailable,
    FileSeal,
    LinkUnsupported,
    StageDir,
)

__all__ = ["PROBE_NAME", "StageClaim", "claim_file_at", "probe_claim", "seal_at"]

PROBE_NAME = ".decoy-claim-probe"  # a claim probe's name in the unit stage; removed at once
_SLOT_PROBE = "probe"
_CREATOR_KEY = CREATOR_KEY
_FINAL_MODE = 0o600
_PROBE_START_MODE = 0o644
_OPEN_FINAL = _osflags.RDONLY | _osflags.NOFOLLOW | _osflags.CLOEXEC | _osflags.NONBLOCK


def _seal_of_stat(st: os.stat_result) -> FileSeal:
    return FileSeal(st.st_dev, st.st_ino, st.st_nlink, st.st_mode)


def _lstat_at(dir_fd: int, name: str) -> os.stat_result | None:
    """`lstat` of `name` beneath the held `dir_fd` from its directory entry (never through a
    link); `None` when the name is absent. Any other failure keeps only its errno."""
    validate_component(name, _CREATOR_KEY)
    code = 0
    try:
        with os.scandir(dir_fd) as entries:
            for entry in entries:
                if entry.name == name:
                    return entry.stat(follow_symlinks=False)
    except OSError as exc:
        code = exc.errno or errno.EIO
    if code:
        raise OSError(code, os.strerror(code))
    return None


def seal_at(dir_fd: int, name: str) -> FileSeal | None:
    """The seal of `name` beneath the held `dir_fd`, read without following a link; `None` when
    the name is absent."""
    found = _lstat_at(dir_fd, name)
    return None if found is None else _seal_of_stat(found)


def _tighten(dst_fd: int, dst_name: str, before: os.stat_result) -> tuple[FileSeal | None, int]:
    """Open the final name, require the claimed inode with one link, set `0o600` on that
    descriptor and read it back. Returns the seal, or `None` and the errno that stopped it
    (`EINVAL` for a refusal that is not an OS failure, `ENOTSUP` for a mode that did not hold)."""
    fd = -1
    if not _osflags.WINDOWS:  # the descriptor arm; Windows claims through the ambient arm
        try:
            fd = os.open(dst_name, _OPEN_FINAL, dir_fd=dst_fd)
            now = os.fstat(fd)
            same = (now.st_dev, now.st_ino) == (before.st_dev, before.st_ino)
            if not (stat.S_ISREG(now.st_mode) and same and now.st_nlink == 1):
                return None, errno.EINVAL
            os.fchmod(fd, _FINAL_MODE)
            held = os.fstat(fd)
            if stat.S_IMODE(held.st_mode) != _FINAL_MODE:
                return None, errno.ENOTSUP
            return _seal_of_stat(held), 0
        except OSError as exc:
            return None, exc.errno or errno.EIO
        finally:
            if fd >= 0:
                _close(fd)
    return None, errno.ENOSYS


def _unlink_at(dir_fd: int, name: str) -> int:
    """Remove `name` beneath the held `dir_fd`. Returns 0 or the errno that stopped it."""
    if not _osflags.WINDOWS:
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError as exc:
            return exc.errno or errno.EIO
        return 0
    return errno.ENOSYS


def claim_file_at(src_fd: int, src_name: str, dst_fd: int, dst_name: str) -> FileSeal:
    """Move regular file `src_name` (beneath `src_fd`) to `dst_name` (beneath `dst_fd`).

    Refused before any link, unlink or chmod: a symlink, FIFO, folder, or a file that already
    has another hard link (`FileAccessUnavailable`). A taken `dst_name` is `FileExistsError` with
    both files untouched. After the link the source name is removed and the final name is
    checked and tightened (`_tighten`); on any failure the final name this call made is removed.
    Errors keep no path, name or OS text and carry no context."""

    validate_component(src_name, _CREATOR_KEY)
    validate_component(dst_name, _CREATOR_KEY)
    before = _lstat_at(src_fd, src_name)
    if before is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT))
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise FileAccessUnavailable("only a plain, singly linked file can be claimed")
    link_noclobber_at(src_fd, src_name, dst_fd, dst_name)
    seal: FileSeal | None = None
    code = _unlink_at(src_fd, src_name)
    if not code:
        seal, code = _tighten(dst_fd, dst_name, before)
    if seal is not None:
        return seal
    _unlink_at(dst_fd, dst_name)
    if code in LINK_UNSUPPORTED or code == errno.ENOTSUP:
        raise LinkUnsupported(code)
    raise FileAccessUnavailable("the file could not be claimed")


class StageClaim:
    """`claim_from` and `seal_of` for a stage that holds a descriptor. An implementor supplies
    `_walk_fd` and `_release_fd` (the `StageWalk` pair) and `_check`, which refuses a finished
    stage and a bad name; the claim asks it about both operands before touching either."""

    if TYPE_CHECKING:

        def _walk_fd(self) -> int: ...

        def _release_fd(self, fd: int) -> None: ...

        def _check(self, *components: str) -> None: ...

    def _check_write(self, *components: str) -> None:
        self._check(*components)

    def claim_from(self, source: StageDir, src_component: str, dst_component: str) -> FileSeal:
        if not isinstance(source, StageClaim):
            raise FileAccessUnavailable("a read-only stage cannot give a file")
        self._check_write(dst_component)
        source._check_write(src_component)
        dst_fd = self._walk_fd()
        try:
            src_fd = source._walk_fd()
            try:
                return claim_file_at(src_fd, src_component, dst_fd, dst_component)
            finally:
                source._release_fd(src_fd)
        finally:
            self._release_fd(dst_fd)

    def seal_of(self, component: str) -> FileSeal | None:
        fd = self._walk_fd()
        try:
            return seal_at(fd, component)
        finally:
            self._release_fd(fd)


def _start_probe(fd: int) -> int:
    """Set the probe file to 0644 on its descriptor and read it back; close it. Returns 0 or the
    errno that says this file system does not hold a chmod."""
    code = errno.ENOSYS
    try:
        if not _osflags.WINDOWS:
            code = 0
            os.fchmod(fd, _PROBE_START_MODE)
            if stat.S_IMODE(os.fstat(fd).st_mode) != _PROBE_START_MODE:
                code = errno.ENOTSUP
    except OSError as exc:
        code = exc.errno or errno.EIO
    finally:
        _close(fd)
    return code


def probe_claim(slots: StageDir, unit: StageDir) -> None:
    """Prove that `unit` can take a claimed file before any writer runs.

    A disposable file is made in `slots` (born `0o600`), set to `0o644` and read back as `0o644`
    on its descriptor, so the claim has a real mode to tighten; a file system that ignores
    `chmod` is `LinkUnsupported` here. The claim then links it into `unit` and must observe
    `0o600` on the final descriptor. The probe name is removed from `unit` at once. Raises
    `LinkUnsupported` (unsupported link or ignored chmod) or the claim's own error."""
    code = _start_probe(slots.create_file(_SLOT_PROBE))
    if code:
        raise LinkUnsupported(code)
    unit.claim_from(slots, _SLOT_PROBE, PROBE_NAME)
    unit.remove(PROBE_NAME)


def parent_identity_of(open_parent: Callable[[], int]) -> tuple[int, int]:
    """`(st_dev, st_ino)` of the folder `open_parent` opens, read from that descriptor."""
    return _identity(open_parent())


def _identity(fd: int) -> tuple[int, int]:
    try:
        st = os.fstat(fd)
    finally:
        _close(fd)
    return st.st_dev, st.st_ino
