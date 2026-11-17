"""Descriptor primitives shared by publication stages, scratch arenas and their reclaim.

A leaf module: standard library only, so `_output.py`, `_local_chain.py`, `_scratch.py` and the
reclaimer can all import it without a cycle, and `fcntl` only off win32, so the package still
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
import sys

if sys.platform != "win32":
    import fcntl

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_MARKER_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
# Longer than any magic plus token plus newline: a read of this size that fills it is not a marker.
_MARKER_MAX = 128


def _close(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.close(fd)


def _exact_stat(found: os.stat_result, kind: int, mode: int) -> bool:
    """`found` is of file type `kind`, owned by the effective user, with exactly `mode`."""
    same = stat.S_IFMT(found.st_mode) == kind and stat.S_IMODE(found.st_mode) == mode
    return same and found.st_uid == os.geteuid()


def hold_stage_lock(fd: int) -> bool:
    """Take the owner's shared liveness lock on a stage directory and keep it until `fd` closes.

    Blocking: a cleaner that holds the exclusive lock first is waited for. `EINTR` is retried.
    Any other `OSError` returns False and the caller carries on unlocked: the errno set differs
    by platform and filesystem, and a lock that cannot be taken must not fail a run."""
    if sys.platform == "win32":
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


def _prove_marker(dir_fd: int, name: str, magic: bytes, token_pattern: str) -> str | None:
    """The token of a valid marker `name` under `dir_fd`, or None.

    Valid means: opened without following a link, a regular file owned by the effective user with
    mode exactly 0600, and content exactly `magic`, a token matching `token_pattern`, and one
    newline. Any `OSError` is None; nothing is raised and nothing is changed."""
    try:
        fd = os.open(name, _MARKER_FLAGS, dir_fd=dir_fd)
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
    found = re.fullmatch(re.escape(magic) + b"(" + token_pattern.encode("ascii") + b")\n", data)
    return found.group(1).decode("ascii") if found else None


def _rmtree_fd(dir_fd: int) -> None:
    """Remove everything beneath `dir_fd` without following any link."""
    for entry in list(os.scandir(dir_fd)):
        if entry.is_dir(follow_symlinks=False):
            child = os.open(entry.name, _DIR_FLAGS, dir_fd=dir_fd)
            try:
                _rmtree_fd(child)
            finally:
                _close(child)
            os.rmdir(entry.name, dir_fd=dir_fd)
        else:
            os.unlink(entry.name, dir_fd=dir_fd)
