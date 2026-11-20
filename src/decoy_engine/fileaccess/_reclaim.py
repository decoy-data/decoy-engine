"""Reclaim of what a killed run leaves: dead `publication` stages beside a caller's output.

Pattern: `systemd-tmpfiles(8)` aging (an entry whose lock is taken is live and skipped; the
cleaner takes an exclusive BSD lock itself), the age floor of Maildir's `tmp/` and git's
`gc.pruneExpire` (a crash-left temporary is touched only past an age, here over its whole tree),
and systemd's `xopenat_lock_full_label` (after the lock, the name must still be the locked inode).

An entry is judged only if its name is an exact litter name (`re.fullmatch`), then in order:
classify by `fstatat` without following (another uid is `foreign` and never opened), open
`O_NOFOLLOW` and match the inode, prove the interior marker, check the age of a `pending` stage,
take `LOCK_EX|LOCK_NB`, and repeat every check after the lock. A `reclaim` name is never proof by
itself: without a valid marker only an empty directory may go. The report holds counts only.
"""

from __future__ import annotations

import os
import re
import stat
import time
from collections import Counter

from decoy_engine.fileaccess import _fdtree, _osflags
from decoy_engine.fileaccess._entry import require_ambient
from decoy_engine.fileaccess._fdtree import (
    _close,
    _exact_stat,
    _is_empty,
    _prove_marker,
    _same_entry,
    _try_exclusive,
)
from decoy_engine.fileaccess._output import STAGE_HEX, STAGE_MAGIC, STAGE_MARKER, STAGE_PREFIX
from decoy_engine.fileaccess._scratch_reports import ReclaimOutcome, ReclaimReport

PENDING_PREFIX = STAGE_PREFIX["publication"]
RECLAIM_PREFIX = PENDING_PREFIX.replace("_pending_", "_reclaim_")
_PENDING = re.compile(re.escape(PENDING_PREFIX) + f"({STAGE_HEX})")
_RECLAIM = re.compile(re.escape(RECLAIM_PREFIX) + STAGE_HEX)
DEFAULT_GRACE_S = 3600

_PROVED, _FALLBACK = "proved", "fallback"


def reclaim_stages(
    directory: str | os.PathLike[str], *, apply: bool, min_age_s: float = DEFAULT_GRACE_S
) -> ReclaimReport:
    """Judge every dead `publication` stage directly in `directory`; with `apply=False` change
    nothing and count what `apply=True` would remove now as `eligible`.

    `directory` is opened without following its last component. If it cannot be opened or
    listed the report is `scope_unavailable=1` with every entry count zero; no `OSError` is
    raised. Ambient policy only. On win32 the report is empty."""
    if type(min_age_s) not in (int, float) or not min_age_s >= 0:
        raise ValueError("min_age_s must be a non-negative number of seconds")
    if apply:
        raise NotImplementedError("reclaim_stages(apply=True) is not built yet")
    if _fdtree.fcntl is None:  # no flock here (win32): nothing can be proved dead
        return ReclaimReport()
    require_ambient("reclaiming publication stages")
    scope = _open_scope(os.fspath(directory))
    if scope < 0:
        return ReclaimReport(scope_unavailable=1)
    try:
        names = _list(scope)
        if names is None:
            return ReclaimReport(scope_unavailable=1)
        counts = Counter(
            _judge(scope, name, min_age_s)
            for name in names
            if _PENDING.fullmatch(name) or _RECLAIM.fullmatch(name)
        )
    finally:
        _close(scope)
    return ReclaimReport(**{outcome.value: n for outcome, n in counts.items()})


def _open_scope(path: str) -> int:
    failed = False
    try:
        fd = os.open(
            path, _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC
        )
    except OSError:  # the exception is dropped here: no path or OS text survives the call
        failed = True
    return -1 if failed else fd


def _list(scope: int) -> list[str] | None:
    names: list[str] | None = None
    try:
        with os.scandir(scope) as entries:
            names = [entry.name for entry in entries]
    except OSError:
        pass
    return names


def _judge(scope: int, name: str, min_age_s: float) -> ReclaimOutcome:
    """G1 (a) to (g) for one exact-named entry, read-only: the lock is released on return."""
    try:
        found = os.stat(name, dir_fd=scope, follow_symlinks=False)
    except OSError:
        return ReclaimOutcome.UNPROVEN
    if found.st_uid != os.geteuid():
        return ReclaimOutcome.FOREIGN
    if not _exact_stat(found, stat.S_IFDIR, 0o700):
        return ReclaimOutcome.UNPROVEN
    try:
        fd = os.open(
            name,
            _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC,
            dir_fd=scope,
        )
    except OSError:
        return ReclaimOutcome.UNPROVEN
    try:
        return _judge_held(scope, name, fd, min_age_s)
    except OSError:
        return ReclaimOutcome.UNPROVEN
    finally:
        _close(fd)


def _judge_held(scope: int, name: str, fd: int, min_age_s: float) -> ReclaimOutcome:
    if not _same_entry(scope, name, fd):
        return ReclaimOutcome.UNPROVEN
    first = _proof(fd, name, min_age_s)
    if isinstance(first, ReclaimOutcome):
        return first
    held = _try_exclusive(fd)
    if held is not None:
        return ReclaimOutcome(held)
    if not _same_entry(scope, name, fd) or _proof(fd, name, min_age_s) != first:
        return ReclaimOutcome.UNPROVEN
    if first == _FALLBACK:  # a reclaim name without proof: only an empty directory may go
        return ReclaimOutcome.ELIGIBLE if _is_empty(fd) else ReclaimOutcome.KEPT
    return ReclaimOutcome.ELIGIBLE


def _proof(fd: int, name: str, min_age_s: float) -> str | ReclaimOutcome:
    """`proved`, `fallback` (a reclaim name without a valid marker), or a retained outcome.

    A pending stage inside the grace is `young` whatever its marker says: it may be a writer
    that has not locked yet, or one from an engine that writes no marker."""
    token = _prove_marker(fd, STAGE_MARKER, STAGE_MAGIC, STAGE_HEX)
    pending = _PENDING.fullmatch(name)
    if pending is None:
        return _FALLBACK if token is None else _PROVED
    if time.time() - _newest(fd) < min_age_s:
        return ReclaimOutcome.YOUNG
    return _PROVED if token == pending.group(1) else ReclaimOutcome.KEPT


def _newest(fd: int) -> float:
    """The newest `max(st_mtime, st_ctime)` of the directory `fd` and everything below it, by
    descriptor, no link followed. A subdirectory that cannot be opened (`EACCES`) counts with its
    own times only: no writer without permission on it can change what is inside."""
    held = os.fstat(fd)
    newest = max(held.st_mtime, held.st_ctime)
    with os.scandir(fd) as entries:
        children = [(entry.name, entry.stat(follow_symlinks=False)) for entry in entries]
    for child_name, found in children:
        newest = max(newest, found.st_mtime, found.st_ctime)
        if not stat.S_ISDIR(found.st_mode):
            continue
        try:
            child = os.open(
                child_name,
                _osflags.RDONLY | _osflags.DIRECTORY | _osflags.NOFOLLOW | _osflags.CLOEXEC,
                dir_fd=fd,
            )
        except PermissionError:
            continue
        try:
            newest = max(newest, _newest(child))
        finally:
            _close(child)
    return newest
