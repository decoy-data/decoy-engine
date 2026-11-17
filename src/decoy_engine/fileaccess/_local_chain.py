"""The ambient policy's output-chain openers (F22 5.0 rule 1), split from `_local.py`.

The deepest existing ancestor of an output is opened by path, links followed as the ambient
policy always has, and each missing component is made beneath its held descriptor by
`make_parent_dir_at`; stage directories come from `make_stage_dir_at`. A publication stage is
locked and marked by `_mark_publication_stage` and its descriptor held until it binds or is
removed (F26 G2), as the strict arm holds its own. POSIX arm only: the
win32 arm in `_local.py` keeps the plain path calls. Like `_local.py`, every ambient open here
carries its own registry entry.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from decoy_engine.fileaccess import _durable
from decoy_engine.fileaccess._fdtree import _close
from decoy_engine.fileaccess._output import (
    STAGE_PREFIX,
    _call,
    make_parent_dir_at,
    make_stage_dir_at,
    _mark_publication_stage,
)


def _open_dir(directory: Path) -> int:
    """Open an existing directory by path, following links as the ambient policy always has.
    A failure keeps only its errno: the stock text names the path."""
    return _call(os.open, directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)


def _open_dir_creating(directory: Path, created: list[str] | None = None) -> int:
    """Open `directory`, making each missing component under the open descriptor of the one
    above it; the replacement for `mkdir(parents=True, exist_ok=True)` (F22 5.0 rule 1). Nothing
    is created unless the deepest existing ancestor opened. `created` receives the components
    that were missing, which the durable walk must sync strictly."""
    missing: list[str] = []
    current = directory
    while True:
        try:
            fd = _open_dir(current)
            break
        except FileNotFoundError:
            if current.parent == current:
                raise
            missing.append(current.name)
            current = current.parent
    try:
        for name in reversed(missing):
            child = make_parent_dir_at(fd, name)
            _close(fd)
            fd = child
    except BaseException:
        _close(fd)
        raise
    if created is not None:
        created.extend(missing)
    return fd


def _ensure_dirs(directory: Path) -> None:
    _close(_open_dir_creating(directory))


def _make_stage_dir(
    parent: Path, prefix: str, *, create_parents: bool, created: list[str] | None = None
) -> tuple[Path, int]:
    """A new private stage directory beside the target, made by `make_stage_dir_at`, and its open
    descriptor; a publication stage is locked and marked before it is returned."""
    parent_fd = _open_dir_creating(parent, created) if create_parents else _open_dir(parent)
    name = f"{prefix}{secrets.token_hex(6)}"
    try:
        fd = make_stage_dir_at(parent_fd, name)
        if prefix == STAGE_PREFIX["publication"]:
            try:
                _mark_publication_stage(parent_fd, name, fd)
            except BaseException:
                _close(fd)
                raise
    finally:
        _close(parent_fd)
    return parent / name, fd


class HeldStage:
    """The open descriptor of an ambient publication stage; its liveness lock lasts until close."""

    def __init__(self, fd: int = -1) -> None:
        self.fd = fd

    def close(self) -> None:
        fd, self.fd = self.fd, -1
        if fd >= 0:
            _close(fd)


def _publish_durable_dir(stage: Path, held: HeldStage, target: Path) -> None:
    """Fsync the stage tree through its held descriptor, rename it onto the leaf, then release the
    lock. Before the rename a failure keeps the stage, locked, for `abort()`."""
    _durable._sync_tree(held.fd)
    _call(os.replace, stage, target)
    held.close()
