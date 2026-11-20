"""Descriptor primitives shared by publication stages, scratch arenas and their reclaim.

A leaf module: standard library and `_osflags` only, so `_output.py`, `_local_chain.py`, `_scratch.py` and the
reclaimer can all import it without a cycle, and `fcntl` is optional, so the package still
imports where it is missing.

Patterns: the liveness lock `systemd-tmpfiles(8)` honours (an owner holds a shared BSD `flock` on
its directory for its whole life; a cleaner needs an exclusive one); CPython's `_rmtree_safe_fd`
and Rust's post-CVE-2022-21658 `remove_dir_all` (`openat(O_NOFOLLOW|O_DIRECTORY)` and `unlinkat`
relative to a held descriptor, so no planted link is followed); and an interior marker that proves
the creator, as the F25 arena does.
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import stat
from typing import Any

from decoy_engine.fileaccess import _osflags

try:
    import fcntl
except ImportError:  # win32 has no fcntl: the lock is skipped there
    fcntl = None  # type: ignore[assignment]

_DIR_FLAGS = _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC
STAGE_MARKER = ".decoy-publication-stage"  # F26 G1(d) proof, kept in a bound unit as metadata
STAGE_MAGIC = b"decoy-publication-stage-v1:"
STAGE_HEX = "[0-9a-f]{12}"  # the token_hex(6) a stage name carries
# Longer than any magic plus token plus newline: a read of this size that fills it is not a marker.
_MARKER_MAX = 128


def stage_entries(handle: Any) -> list[str]:
    """The sorted entry names of a publication stage, without its reserved marker.

    The one place that knows the marker is not content: a caller that checks what a stage holds
    lists through here, so the marker never reads as an extra file."""
    return sorted(entry.name for entry in handle.entries() if entry.name != STAGE_MARKER)


def _close(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.close(fd)


def _owned(found: os.stat_result) -> bool:
    """`found` is owned by the effective user: the one owner test of the descriptor leaf, its
    reclaimer and the protected-directory check. The test is the capability itself: a platform
    without `os.geteuid` (win32) has no owner uid, so nothing there is owned."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and found.st_uid == geteuid()


def _exact_stat(found: os.stat_result, kind: int, mode: int) -> bool:
    """`found` is of file type `kind`, owned by the effective user, with exactly `mode`."""
    same = stat.S_IFMT(found.st_mode) == kind and stat.S_IMODE(found.st_mode) == mode
    return same and _owned(found)


def hold_stage_lock(fd: int) -> bool:
    """Take the owner's shared liveness lock on a stage directory and keep it until `fd` closes.

    Blocking: a cleaner that holds the exclusive lock first is waited for. `EINTR` is retried.
    Any other `OSError` returns False and the caller carries on unlocked: the errno set differs
    by platform and filesystem, and a lock that cannot be taken must not fail a run."""
    if fcntl is None:
        return False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
        except InterruptedError:
            continue
        except OSError:
            return False
        return True


def _write_marker(fd: int, magic: bytes, token: str) -> None:
    """Write `magic`, the token and a newline at offset 0 of an open private marker file."""
    if os.pwrite(fd, data := magic + token.encode("ascii") + b"\n", 0) != len(data):
        raise OSError(errno.EIO, os.strerror(errno.EIO))


def prove_stage(stage_fd: int) -> str | None:
    """The token of a valid publication stage marker in `stage_fd`, or None."""
    return _prove_marker(stage_fd, STAGE_MARKER, STAGE_MAGIC, STAGE_HEX)


def _prove_marker(dir_fd: int, name: str, magic: bytes, token_pattern: str) -> str | None:
    """The token of a valid marker `name` under `dir_fd`, or None.

    Valid means: opened without following a link, a regular file owned by the effective user with
    mode exactly 0600, and content exactly `magic`, a token matching `token_pattern`, and one
    newline. Any `OSError` is None; nothing is raised and nothing is changed. Always None on
    win32, where no stage is marked."""
    if not _osflags.WINDOWS:
        try:
            fd = os.open(
                name,
                _osflags.RDONLY | _osflags.NOFOLLOW | _osflags.NONBLOCK | _osflags.CLOEXEC,
                dir_fd=dir_fd,
            )
        except OSError:
            return None
        try:
            if not _exact_stat(os.fstat(fd), stat.S_IFREG, 0o600):
                return None
            data = os.pread(fd, _MARKER_MAX, 0)
        except OSError:
            return None
        finally:
            _close(fd)
        pattern = re.escape(magic) + b"(" + token_pattern.encode("ascii") + b")\n"
        found = re.fullmatch(pattern, data)
        return found.group(1).decode("ascii") if found else None
    return None


def _rmtree_fd(dir_fd: int) -> None:
    """Remove everything beneath `dir_fd` without following any link (a no-op on win32)."""
    if not _osflags.WINDOWS:
        for entry in list(os.scandir(dir_fd)):
            if entry.is_dir(follow_symlinks=False):
                child = os.open(
                    entry.name,
                    _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC,
                    dir_fd=dir_fd,
                )
                try:
                    _rmtree_fd(child)
                finally:
                    _close(child)
                os.rmdir(entry.name, dir_fd=dir_fd)
            else:
                os.unlink(entry.name, dir_fd=dir_fd)


def _try_exclusive(fd: int) -> str | None:
    """Take a cleaner's `LOCK_EX|LOCK_NB` on `fd`: None when held (until `fd` closes), `live`
    when an owner holds its lock, `lock_unavailable` for any other `OSError`, whatever the errno."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return "live"
    except OSError:
        return "lock_unavailable"
    return None


def _same_entry(dir_fd: int, name: str, fd: int) -> bool:
    """`name` under `dir_fd`, not followed, is still the held directory `fd`: same inode, and an
    owned directory with mode exactly 0700 (the post-lock recheck of a name, systemd's
    `xopenat_lock_full_label` pattern)."""
    if not _osflags.WINDOWS:
        try:
            found = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            held = os.fstat(fd)
        except OSError:
            return False
        same = (found.st_dev, found.st_ino) == (held.st_dev, held.st_ino)
        return (
            same
            and _exact_stat(found, stat.S_IFDIR, 0o700)
            and _exact_stat(held, stat.S_IFDIR, 0o700)
        )
    return False


def _is_empty(fd: int) -> bool:
    """Whether the directory `fd` has no entry; the empty-only fallback's read-only test."""
    with os.scandir(fd) as entries:
        return next(entries, None) is None
