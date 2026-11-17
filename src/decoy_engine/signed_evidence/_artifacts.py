"""Artifact binding: open every delivered file safely and hash the bytes actually read.

Pattern: rooted no-follow reads under a held directory descriptor (``decoy_engine.fileaccess``:
``openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS)`` or its descriptor walk, as in ``cap-std`` and
CERT FIO45-C), so a path inside the tree cannot be redirected by a symlink or a swapped directory.
The size and the hash both come from the one open descriptor, never from a separate ``stat`` on the
pathname. A FIFO or device is refused on ``fstat`` before any read. Reads stream in bounded chunks.

A file that changes while it is hashed is caught two ways (pattern: git's racy-index check): its
size, ``mtime`` and ``ctime`` must be equal before and after the read, and the same relative path
opened again must be the same inode. Either difference is ``ARTIFACT_CHANGED_DURING_READ``. A
filesystem with a coarse ``ctime`` can miss a same-size write inside one tick (named limit).

Enumeration fails closed: any error while listing a directory is ``ARTIFACT_ENUMERATION_FAILED``
and the artifact status is never ``MATCH``. Extra files under the tree are reported as unbound; they
cannot be part of a verified release.

Where the tree comes from is the caller's choice. ``open_path_tree`` opens a caller-named directory
(the path form); a ``SignedBundle`` hands over its ``artifacts`` child. Both give this module a
zero-argument opener, so one binding routine serves both.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass

from decoy_engine import fileaccess
from decoy_engine.fileaccess import DirHandle, FileAccessDenied, FileHandle
from decoy_engine.reasons import evidence as ev

from ._context import ExpectedArtifact
from ._errors import SignedEvidenceError
from ._result import ArtifactResult, ArtifactStatus
from ._statement import EvidenceStatementV1

_CHUNK = 1024 * 1024
MAX_TREE_ENTRIES = 200_000
MAX_TREE_DEPTH = 32
MAX_REPORTED_UNBOUND = 100

_POSIX = os.name == "posix" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")

#: Opens the artifact tree. Raises ``FileAccessDenied`` (with its ``kind``) when it cannot.
TreeOpener = Callable[[], DirHandle]


@dataclass(frozen=True, slots=True)
class ArtifactEvaluation:
    status: ArtifactStatus
    results: tuple[ArtifactResult, ...]
    unbound: tuple[str, ...]
    reasons: tuple[str, ...]


_PRECEDENCE = (
    ArtifactStatus.MISMATCH,
    ArtifactStatus.MISSING,
    ArtifactStatus.UNAVAILABLE,
    ArtifactStatus.UNEXPECTED,
)


def require_supported_platform() -> None:
    """The one temporary V1 rule: the signed filesystem routes are POSIX only.

    Raised before any opener runs, with no path and no platform value. The Windows chain replaces
    this refusal later.
    """
    if not _POSIX:
        raise SignedEvidenceError(ev.ARTIFACT_PLATFORM_UNSUPPORTED)


def _artifact_refusal(kind: str | None) -> tuple[ArtifactStatus, str]:
    """The one table from a no-follow denial kind to an artifact status and reason token."""
    if kind == "absent":
        return ArtifactStatus.MISSING, ev.WIRE_TOKEN[ev.ARTIFACT_MISSING]
    if kind == "link":
        return ArtifactStatus.UNAVAILABLE, ev.WIRE_TOKEN[ev.ARTIFACT_PATH_UNSAFE]
    if kind == "not_regular":
        return ArtifactStatus.UNAVAILABLE, ev.WIRE_TOKEN[ev.ARTIFACT_NOT_REGULAR_FILE]
    return ArtifactStatus.UNAVAILABLE, ev.WIRE_TOKEN[ev.ARTIFACT_UNREADABLE]


def open_path_tree(root: str | os.PathLike[str]) -> DirHandle:
    """Open the caller-named artifact root once (the path form). Ambient policy only."""
    return fileaccess.open_ambient_tree(root)


def _open_tree(opener: TreeOpener) -> tuple[DirHandle | None, str | None]:
    """The held tree, or the denial kind. The kind is read in the handler and used outside it."""
    kind: str | None = None
    try:
        return opener(), None
    except FileAccessDenied as denial:
        kind = denial.kind or "unreadable"
    except OSError:
        kind = "unreadable"
    return None, kind


def _open_file(tree: DirHandle, rel: str) -> tuple[FileHandle | None, str | None]:
    kind: str | None = None
    try:
        return tree.open_file(rel), None
    except FileAccessDenied as denial:
        kind = denial.kind or "unreadable"
    return None, kind


def _read_chunk(fd: int) -> bytes:
    """One bounded read. A named function so a test can write to the file between chunks."""
    return os.read(fd, _CHUNK)


def _before_reopen() -> None:
    """Runs after the second ``fstat`` and before the re-open. A test seam; does nothing."""


def _hash_artifact(
    tree: DirHandle, rel_path: str, size: int, digest: str
) -> tuple[ArtifactStatus, str | None]:
    handle, kind = _open_file(tree, rel_path)
    if handle is None:
        return _artifact_refusal(kind)
    changed = False
    unreadable = False
    with handle as held:
        fd = held.fileno()
        before = os.fstat(fd)
        if before.st_size != size:
            return ArtifactStatus.MISMATCH, "ARTIFACT_LENGTH_MISMATCH"
        h = hashlib.sha256()
        read = 0
        try:
            while chunk := _read_chunk(fd):
                read += len(chunk)
                if read > size:
                    return ArtifactStatus.MISMATCH, "ARTIFACT_LENGTH_MISMATCH"
                h.update(chunk)
            after = os.fstat(fd)
        except OSError:
            unreadable = True
        if not unreadable:
            changed = (
                read != size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            )
            if not changed:
                _before_reopen()
                again, _ = _open_file(tree, rel_path)
                if again is None:
                    changed = True
                else:
                    with again as second:
                        changed = second.identity() != held.identity()
    if unreadable:
        return ArtifactStatus.UNAVAILABLE, ev.WIRE_TOKEN[ev.ARTIFACT_UNREADABLE]
    if changed:
        return ArtifactStatus.MISMATCH, ev.WIRE_TOKEN[ev.ARTIFACT_CHANGED_DURING_READ]
    if "sha256:" + h.hexdigest() != digest:
        return ArtifactStatus.MISMATCH, "ARTIFACT_DIGEST_MISMATCH"
    return ArtifactStatus.MATCH, None


@dataclass(slots=True)
class _Walk:
    found: list[str]
    seen: int = 0
    truncated: bool = False
    failed: bool = False


def _scan(tree: DirHandle, prefix: str, depth: int, bound: set[str], walk: _Walk) -> None:
    """Every non-directory entry (symlinks, FIFOs and devices included) not named by the statement.

    Directories are entered through ``open_dir`` on the held handle, so no link is followed. A
    listing or open error sets ``failed``; a limit sets ``truncated``.
    """
    names: list[tuple[str, bool]] = []
    try:
        for entry in tree.entries():
            walk.seen += 1
            if walk.seen > MAX_TREE_ENTRIES:
                walk.truncated = True
                return
            names.append((entry.name, entry.is_dir(follow_symlinks=False)))
    except OSError:
        walk.failed = True
        return
    for name, is_dir in names:
        rel = prefix + name
        if not is_dir:
            if rel not in bound:
                walk.found.append(rel)
            continue
        if depth >= MAX_TREE_DEPTH:
            walk.truncated = True
            continue
        child, _ = _open_tree(lambda n=name: tree.open_dir(n))  # type: ignore[misc]
        if child is None:
            walk.failed = True
            continue
        with child:
            _scan(child, rel + "/", depth + 1, bound, walk)
        if walk.truncated:
            return


def _unbound_entries(tree: DirHandle, bound: set[str]) -> tuple[list[str], bool, bool]:
    walk = _Walk(found=[])
    _scan(tree, "", 0, bound, walk)
    return sorted(walk.found), walk.truncated, walk.failed


def bind_artifacts(
    *,
    statement: EvidenceStatementV1,
    expected: tuple[ExpectedArtifact, ...],
    empty_output_allowed: bool,
    open_tree: TreeOpener | None,
) -> ArtifactEvaluation:
    reasons: set[str] = set()
    results: list[ArtifactResult] = []
    by_stmt = {a.id: a for a in statement.artifacts}
    by_exp = {a.id: a for a in expected}
    status_seen: set[ArtifactStatus] = set()

    def note(aid: str, status: ArtifactStatus, reason: str | None) -> None:
        results.append(ArtifactResult(aid, status, reason))
        status_seen.add(status)
        if reason:
            reasons.add(reason)

    for aid in sorted(by_exp.keys() - by_stmt.keys()):
        note(aid, ArtifactStatus.MISSING, "ARTIFACT_NOT_IN_STATEMENT")
    for aid in sorted(by_stmt.keys() - by_exp.keys()):
        note(aid, ArtifactStatus.UNEXPECTED, "ARTIFACT_NOT_EXPECTED")
    if not by_exp and not by_stmt and not empty_output_allowed:
        reasons.add("EMPTY_OUTPUT_NOT_ALLOWED")
        status_seen.add(ArtifactStatus.MISSING)

    common = sorted(by_stmt.keys() & by_exp.keys())
    comparable: list[str] = []
    for aid in common:
        s, e = by_stmt[aid], by_exp[aid]
        if s.media_type != e.media_type:
            note(aid, ArtifactStatus.MISMATCH, "ARTIFACT_MEDIA_TYPE_MISMATCH")
        elif s.sha256 != e.sha256:
            note(aid, ArtifactStatus.MISMATCH, "EXPECTED_DIGEST_MISMATCH")
        else:
            comparable.append(aid)

    unbound: list[str] = []
    rejected = statement.publication.state == "REJECTED"
    if rejected:
        for aid in comparable:
            note(aid, ArtifactStatus.WITHHELD, None)
        held = _open_tree(open_tree)[0] if open_tree is not None else None
        if held is not None:
            with held:
                extras, _, _ = _unbound_entries(held, set())
            if extras:
                unbound = extras
                reasons.add("ARTIFACT_PRESENT_FOR_REJECTED")
                status_seen.add(ArtifactStatus.UNEXPECTED)
    elif open_tree is None:
        for aid in comparable:
            note(aid, ArtifactStatus.NOT_EVALUATED, "ARTIFACTS_NOT_EVALUATED")
        # Even an empty inventory was not checked against anything on disk.
        status_seen.add(ArtifactStatus.NOT_EVALUATED)
        reasons.add("ARTIFACTS_NOT_EVALUATED")
    else:
        tree, kind = _open_tree(open_tree)
        if tree is None:
            status, why = _artifact_refusal(kind)
            for aid in comparable:
                note(aid, status, why)
        else:
            with tree:
                bound_paths: set[str] = set()
                for aid in comparable:
                    entry = by_stmt[aid]
                    bound_paths.add(entry.path)
                    if entry.sha256 is None or entry.bytes is None:
                        # The schema forbids this for a published artifact; refuse rather than skip.
                        note(aid, ArtifactStatus.UNAVAILABLE, "ARTIFACT_INVENTORY_INVALID")
                        continue
                    st, why_hash = _hash_artifact(tree, entry.path, entry.bytes, entry.sha256)
                    note(aid, st, why_hash)
                extras, truncated, failed = _unbound_entries(tree, bound_paths)
            if failed:
                reasons.add(ev.WIRE_TOKEN[ev.ARTIFACT_ENUMERATION_FAILED])
                status_seen.add(ArtifactStatus.UNAVAILABLE)
            if extras or truncated:
                unbound = extras[:MAX_REPORTED_UNBOUND]
                reasons.add("ARTIFACT_UNBOUND_FILE" if extras else "ARTIFACT_TREE_TOO_LARGE")
                status_seen.add(ArtifactStatus.UNEXPECTED)

    for candidate in _PRECEDENCE:
        if candidate in status_seen:
            overall = candidate
            break
    else:
        if status_seen == {ArtifactStatus.NOT_EVALUATED}:
            overall = ArtifactStatus.NOT_EVALUATED
        elif rejected:
            overall = ArtifactStatus.WITHHELD
        else:
            overall = ArtifactStatus.MATCH
    return ArtifactEvaluation(overall, tuple(results), tuple(unbound), tuple(sorted(reasons)))
