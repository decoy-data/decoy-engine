"""The ambient policy's output-chain openers (F22 5.0 rule 1), split from `_local.py`.

The deepest existing ancestor of an output is opened by path, links followed as the ambient
policy always has, and each missing component is made beneath its held descriptor by
`make_parent_dir_at`; stage directories come from `make_stage_dir_at`. POSIX arm only: the
win32 arm in `_local.py` keeps the plain path calls. Like `_local.py`, every ambient open here
carries its own registry entry.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from decoy_engine.fileaccess import _osflags
from decoy_engine.fileaccess._output import _call, _close, make_parent_dir_at, make_stage_dir_at


def _open_dir(directory: Path) -> int:
    """Open an existing directory by path, following links as the ambient policy always has.
    A failure keeps only its errno: the stock text names the path."""
    return _call(os.open, directory, _osflags.RDONLY | _osflags.DIRECTORY | _osflags.CLOEXEC)


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
) -> Path:
    """A new private stage directory beside the target, made by `make_stage_dir_at`."""
    parent_fd = _open_dir_creating(parent, created) if create_parents else _open_dir(parent)
    name = f"{prefix}{secrets.token_hex(6)}"
    try:
        _close(make_stage_dir_at(parent_fd, name))
    finally:
        _close(parent_fd)
    return parent / name
