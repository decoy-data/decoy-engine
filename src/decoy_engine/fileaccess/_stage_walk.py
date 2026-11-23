"""Read-only traversal of a stage, shared by every `StageDir` implementor.

A stage lists itself (`entries`) and opens one folder at a time (`open_subdir`) without following a
link. The helpers that touch descriptors live in `_durable` (`entries_at`, `open_subdir_at`); this
module holds what the three implementors share around them: the stage's end-of-life state, which
closes every view when the stage publishes, aborts or is reclaimed, and the two methods. A
implementor supplies `_life`, `display`, `strict` and `_held_fd`, so none carries its own listing or
view bookkeeping.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from decoy_engine.fileaccess._types import FileAccessUnavailable, StageDir, StageEntry

__all__ = ["PathStageWalk", "StageLife", "StageWalk"]


class StageLife:
    """Whether a stage tree ended, and the closes of the read-only views opened on it."""

    def __init__(self) -> None:
        self.finished = False
        self.views: list[Callable[[], None]] = []

    def end(self) -> None:
        self.finished = True
        while self.views:
            self.views.pop()()


class StageWalk:
    """`open_subdir` and `entries` for a stage that holds a descriptor (`_held_fd`)."""

    _life: StageLife
    display: str
    strict: bool
    _fd: Any

    def _held_fd(self) -> int:
        """The stage directory's descriptor, or -1 when the stage has no directory."""
        return self._fd

    def _release_fd(self, fd: int) -> None:
        """Called with the descriptor `_held_fd` returned, once a call is done with it."""

    def _alive(self) -> bool:
        return not self._life.finished

    def _walk_fd(self) -> int:
        if self._life.finished:
            raise FileAccessUnavailable("output transaction is finished")
        fd = self._held_fd()
        if fd < 0:
            raise FileAccessUnavailable("a file stage has no entries")
        return fd

    def open_subdir(self, component: str) -> StageDir:
        from decoy_engine.fileaccess import _durable

        fd = self._walk_fd()
        try:
            return _durable.open_subdir_at(
                fd, component, self._alive, self._life.views.append, self.display, self.strict
            )
        finally:
            self._release_fd(fd)

    def entries(self) -> Iterator[StageEntry]:
        from decoy_engine.fileaccess import _durable

        fd = self._walk_fd()
        try:
            return iter(list(_durable.entries_at(fd)))
        finally:
            self._release_fd(fd)


class PathStageWalk(StageWalk):
    """A stage known by its path (the ambient policy): each call opens it and closes it again."""

    _dir: Path
    _walkable = True  # a file stage has no directory to list

    def _held_fd(self) -> int:
        from decoy_engine.fileaccess._local_chain import _open_dir

        return _open_dir(self._dir) if self._walkable else -1

    def _release_fd(self, fd: int) -> None:
        from decoy_engine.fileaccess._fdtree import _close

        _close(fd)
