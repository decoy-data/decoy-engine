"""Descriptor primitives shared by publication stages, scratch arenas and their reclaim.

A leaf module: standard library, `_osflags` and the `_mountinfo` foundation only, so
`_output.py`, `_local_chain.py`, `_scratch.py` and the reclaimer can all import it without a cycle, and `fcntl` is optional, so the package still
imports where it is missing.

Patterns: the liveness lock `systemd-tmpfiles(8)` honours (an owner holds a shared BSD `flock` on
its directory for its whole life; a cleaner needs an exclusive one); CPython's `_rmtree_safe_fd`
and Rust's post-CVE-2022-21658 `remove_dir_all` (`openat(O_NOFOLLOW|O_DIRECTORY)` and `unlinkat`
relative to a held descriptor, so no planted link is followed); and an interior marker that proves
the creator, as the F25 arena does. Tree removal also stops at a mount (see "Mount detection" below).
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import stat
import sys
from typing import Any

from decoy_engine._mountinfo import parse_record, records
from decoy_engine.fileaccess import _osflags

try:
    import fcntl
except ImportError:  # win32 has no fcntl: the lock is skipped there
    fcntl = None  # type: ignore[assignment]

_DIR_FLAGS = _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC
STAGE_MARKER = ".decoy-publication-stage"  # F26 G1(d) proof, kept in a bound unit as metadata
DESCRIPTOR_NAME = "_decoy_publication.json"  # the publication descriptor, a member of every unit
# Names a table may not take inside a publication directory. The one source for every check.
RESERVED_MEMBER_NAMES = frozenset({DESCRIPTOR_NAME, STAGE_MARKER})
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
            fd = _open_leaf(name, dir_fd)
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


# Mount detection. Patterns: coreutils `rm --one-file-system` and gnulib `fts` (`FTS_XDEV`) skip any
# entry whose `st_dev` differs from its parent's; CPython's `shutil.rmtree` does no mount test and
# relies on `rmdir` failing `EBUSY` on the mount point, which comes only after the contents are
# gone. A bind mount from the same filesystem keeps `st_dev`, so the device test alone misses it.
# On Linux `/proc/self/mountinfo` is read once per removal and the `(st_dev, st_ino)` of every
# mount point under the held directory is kept; a directory whose identity is in that set is a
# mount root whatever its device. The table is required there: when it cannot be read, parsed,
# or matched to the held directory, or a listed mount point cannot be stat'ed, the removal fails
# with `EBUSY` before anything is touched (fail closed). macOS has no same-device bind mount
# (a firmlink or FUSE mount reports its own device), so the device test is the whole check
# there. Any other POSIX host has no known table and fails closed. A mount made after the table
# is read is not seen; that needs privilege and is outside the V1 threat model of accidental
# leaks.
_LINUX = sys.platform.startswith("linux")
_DEVICE_ONLY = sys.platform == "darwin"
_MOUNTINFO = "/proc/self/mountinfo"
_PROC_FD = "/proc/self/fd/"
_MOUNTINFO_MAX = 4 * 1024 * 1024  # a mount table is a few KiB; this bounds a hostile one


def _undiscoverable() -> OSError:
    return OSError(errno.EBUSY, os.strerror(errno.EBUSY))


def _open_leaf(name: str, dir_fd: int | None = None) -> int:
    """Open a regular file read-only without following a final link: a marker under a held
    directory, or the fixed kernel path of the mount table. The one such opener of this leaf."""
    return os.open(
        name,
        _osflags.RDONLY | _osflags.NOFOLLOW | _osflags.NONBLOCK | _osflags.CLOEXEC,
        dir_fd=dir_fd,
    )


def _read_mount_table() -> str:
    """The whole mount table; `EBUSY` when it is larger than `_MOUNTINFO_MAX`."""
    fd = _open_leaf(_MOUNTINFO)
    try:
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
            size += len(chunk)
            if size > _MOUNTINFO_MAX:
                raise _undiscoverable()
    finally:
        _close(fd)
    return os.fsdecode(b"".join(chunks))


def _path_identity(path: str) -> tuple[int, int]:
    """`(st_dev, st_ino)` of a kernel-reported absolute path."""
    found = os.stat(path)
    return found.st_dev, found.st_ino


def _mount_roots(dir_fd: int) -> frozenset[tuple[int, int]]:
    """`(st_dev, st_ino)` of each mount root at or under the directory held by `dir_fd`.

    Empty on macOS, where the device test is enough. Elsewhere any failure to discover the
    mounts raises `OSError` (`EBUSY` for a malformed or oversized table, a path that is not the
    held directory, or a host without a table), so the caller keeps the tree."""
    if _DEVICE_ONLY:
        return frozenset()
    if not _LINUX:
        raise _undiscoverable()
    held = os.fstat(dir_fd)
    base = os.readlink(f"{_PROC_FD}{dir_fd}")
    # The link text must name the held directory itself: a deleted or unreachable directory
    # (" (deleted)", a path outside this root) gives no prefix to match mounts against.
    if not base.startswith("/") or _path_identity(base) != (held.st_dev, held.st_ino):
        raise _undiscoverable()
    prefix = base.rstrip("/") + "/"
    found: set[tuple[int, int]] = set()
    for line in records(_read_mount_table()):
        record = parse_record(line)
        if record is None:
            raise _undiscoverable()
        if record.mountpoint == base or record.mountpoint.startswith(prefix):
            found.add(_path_identity(record.mountpoint))
    return frozenset(found)


_MAX_TREE_DEPTH = 128  # open descriptors one removal may hold at once: a deeper tree is retained
# The interior markers that prove who made a stage or an arena. At the root of a removal they go
# last, so a removal stopped part way leaves the proof a later reclaim needs.
ARENA_MARKER = ".decoy-arena"
_ROOT_PROOFS = frozenset({STAGE_MARKER, ARENA_MARKER})


def _mount_guard(fd: int, parent_dev: int, mounts: frozenset[tuple[int, int]]) -> os.stat_result:
    """`fstat` of a directory about to be cleared; `EBUSY` when it is a mount boundary.

    A mount boundary is a device other than its parent's (`rm --one-file-system`) or an identity
    in the mount table (a same-device bind mount). Nothing under it has been touched yet."""
    found = os.fstat(fd)
    if found.st_dev != parent_dev or (found.st_dev, found.st_ino) in mounts:
        raise OSError(errno.EBUSY, os.strerror(errno.EBUSY))
    return found


def _listing(fd: int, *, root: bool) -> list[tuple[str, bool]]:
    """`(name, is a real directory)` of each entry, in the order the walk pops them (from the
    end). At the root a proof marker is put first, so it is removed after everything else."""
    with os.scandir(fd) as listing:
        found = [(e.name, e.is_dir(follow_symlinks=False)) for e in listing]
    if root:
        found.sort(key=lambda entry: entry[0] not in _ROOT_PROOFS)
    return found


def _rmtree_fd(dir_fd: int, parent_fd: int) -> None:
    """Remove everything beneath `dir_fd` without following any link or crossing a mount.

    One iterative walk holds an explicit stack of descriptors, at most `_MAX_TREE_DEPTH`, so no
    tree depth reaches the interpreter's recursion limit. Every directory, `dir_fd` itself
    included, is tested by `_mount_guard` after it is opened and before anything under it is
    listed, so no entry beneath a mount is removed. `parent_fd` is the held parent of `dir_fd`,
    whose device the root is compared with. A limit, a mount or mounts that cannot be
    discovered raise `OSError` (`EMFILE`, `EBUSY`) for the caller to report as retained. A
    no-op on win32."""
    if not _osflags.WINDOWS:
        mounts = _mount_roots(dir_fd)
        root_dev = _mount_guard(dir_fd, os.fstat(parent_fd).st_dev, mounts).st_dev
        # One frame per held directory: its descriptor, the name to remove from the parent, its
        # device and its still-unremoved entries (None until listed).
        frames: list[list[Any]] = [[dir_fd, "", root_dev, None]]
        try:
            while frames:
                top = frames[-1]
                if top[3] is None:
                    top[3] = _listing(top[0], root=len(frames) == 1)
                if not top[3]:
                    frames.pop()
                    if frames:  # a descended directory: its contents are gone, so remove it
                        _close(top[0])
                        os.rmdir(top[1], dir_fd=frames[-1][0])
                    continue
                name, is_dir = top[3].pop()
                if not is_dir:
                    os.unlink(name, dir_fd=top[0])
                    continue
                if len(frames) >= _MAX_TREE_DEPTH:
                    raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
                child = os.open(
                    name,
                    _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC,
                    dir_fd=top[0],
                )
                try:
                    child_dev = _mount_guard(child, top[2], mounts).st_dev
                except BaseException:
                    _close(child)
                    raise
                frames.append([child, name, child_dev, None])
        finally:
            for held in frames[1:]:  # the root descriptor is the caller's
                _close(held[0])


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
