"""The members of a publication unit: a writer's path and role, and how each one is measured.

Pattern: Git's tree entries, each a path under the unit root with a content hash, listed as a
closed set (a file in the stage that no member names is refused, as ``git write-tree`` refuses an
index entry it cannot hash). Parquet footer counts: https://parquet.apache.org/docs/file-format/metadata/.

A ``Member`` is a value: a relative path (one folder level per ``/``, at most
``UNIT_PATH_MAX_DEPTH`` deep) and a closed role. Every path passes the one rule in
``decoy_engine._canonical`` (``check_unit_path`` for one path, ``check_unit_paths`` for the whole
unit), the same rule the descriptor reader applies. ``measure_members`` is the only reader of
staged bytes: a ``table`` named ``*.parquet`` carries its footer row count, every other member
carries ``None``, and an empty file is hashed as the empty string without a mapping. The stage is
read only through ``StageDir.entries`` and ``StageDir.open_subdir``, which never follow a link.
"""

from __future__ import annotations

import errno
import hashlib
import mmap
import os
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import pyarrow.parquet as pq

from decoy_engine._canonical import UNIT_PATH_MAX_DEPTH, attempt, check_unit_path, check_unit_paths
from decoy_engine.fileaccess import (
    RESERVED_MEMBER_NAMES,
    STAGE_MARKER,
    StageDir,
    is_valid_component,
)
from decoy_engine.publication._descriptor import Artifact
from decoy_engine.publication._types import ROLES, Role, has_row_count

__all__ = ["Member", "check_member_paths", "measure_members", "stage_is_closed"]


def _one(path: object, max_depth: int = UNIT_PATH_MAX_DEPTH) -> None:
    check_unit_path(
        path,
        component_test=is_valid_component,
        reserved=RESERVED_MEMBER_NAMES,
        max_depth=max_depth,
    )


def check_member_paths(paths: Sequence[Any], message: str, *, flat: bool = False) -> None:
    """Refuse a unit's path list when any path or the whole set breaks the unit rules. ``flat``
    keeps every path to one component. The refusal is raised here, outside the spec handler,
    with the fixed ``message`` and no exception context."""

    def check(listed: Sequence[Any]) -> None:
        for path in listed:
            _one(path, 1 if flat else UNIT_PATH_MAX_DEPTH)
        check_unit_paths(listed)

    _, refused = attempt(check, paths)
    if refused is not None:
        raise ValueError(message)


@dataclass(frozen=True)
class Member:
    """One file of a unit: its path under the unit root and its role."""

    path: str
    role: Role

    def __post_init__(self) -> None:
        _, refused = attempt(_one, self.path)
        if refused is not None:
            raise ValueError("invalid path")
        if type(self.role) is not str or self.role not in ROLES:
            raise ValueError("invalid role")


def _open_dir(stage: StageDir, opened: dict[str, StageDir], parts: Sequence[str]) -> StageDir:
    """The read-only view of folder ``parts`` under ``stage``, opened once per folder."""
    directory, prefix = stage, ""
    for part in parts:
        prefix = f"{prefix}{part}/"
        if prefix not in opened:
            opened[prefix] = directory.open_subdir(part)
        directory = opened[prefix]
    return directory


def _digest(fd: int, size: int) -> str:
    if size == 0:  # mmap of zero bytes raises ValueError
        return hashlib.sha256(b"").hexdigest()
    with mmap.mmap(fd, 0, access=mmap.ACCESS_READ) as mapped:
        return hashlib.sha256(mapped).hexdigest()


def _measure_one(directory: StageDir, member: Member) -> Artifact:
    """Size, SHA-256 and, for a Parquet table, the footer row count of one staged file.

    The file is mapped read-only and hashed in one call, so a large table costs page cache, not
    a heap copy."""
    name = member.path.rsplit("/", 1)[-1]
    parquet = has_row_count(member.path, member.role)
    fd = directory.open_file(name)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (parquet and st.st_size == 0):  # no Parquet table
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        sha256 = _digest(fd, st.st_size)
        rows = None
        if parquet:
            with os.fdopen(os.dup(fd), "rb") as fh:
                rows = pq.ParquetFile(fh).metadata.num_rows
    finally:
        os.close(fd)
    return Artifact(path=member.path, role=member.role, rows=rows, sha256=sha256, size=st.st_size)


def measure_members(stage: StageDir, members: Iterable[Member]) -> list[Artifact]:
    """Measure every member through ``stage``, folders opened without following a link."""
    opened: dict[str, StageDir] = {}
    return [
        _measure_one(_open_dir(stage, opened, member.path.split("/")[:-1]), member)
        for member in members
    ]


def stage_is_closed(stage: StageDir, paths: Iterable[str]) -> bool:
    """Whether the stage holds exactly the declared members: every declared path a regular file
    (never a link), every folder a prefix of one, and nothing else. The stage's own marker at
    the root is the one entry no member names."""
    files = set(paths)
    folders = {"/".join(p.split("/")[:i]) for p in files for i in range(1, len(p.split("/")))}

    def walk(directory: StageDir, prefix: str) -> bool:
        for entry in directory.entries():
            path = f"{prefix}{entry.name}"
            kind = entry.kind
            if path in files or (not prefix and entry.name == STAGE_MARKER):
                if kind != "file":
                    return False
            elif path in folders:
                if kind != "dir":
                    return False
                if not walk(directory.open_subdir(entry.name), f"{path}/"):
                    return False
            else:
                return False
        return True

    return walk(stage, "")
