"""`LocalFileAccess`: today's ambient semantics, the no-policy CLI default.

Paths are plain paths relative to the CWD, symlinks are followed, `display` is the path, and
every open is lazy so a missing file fails inside the library call with the same text it always
had. Output transactions use ordinary path calls (a stage directory in the target's parent, one
`os.replace`), as the sinks did before the policy existed. This module (with `_local_chain.py`)
is the one place ambient opens of caller or config paths are allowed. A durable directory
publish fsyncs the stage tree, renames, then fsyncs each directory above it up to the mount.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import logging.handlers
import os
import secrets
import shutil
import stat
import sys
import tempfile
import weakref
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Literal, TextIO

from decoy_engine.fileaccess import _durable, _osflags
from decoy_engine.fileaccess._component import validate_component, validate_publication_leaf
from decoy_engine.fileaccess._errors import deny
from decoy_engine.fileaccess._local_chain import (
    HeldStage,
    _ensure_dirs,
    _make_stage_dir,
    _open_dir,
    _publish_durable_dir,
)
from decoy_engine.fileaccess._output import (
    CREATES_PARENTS,
    DIRECTORY_PUBLISH_LABELS,
    PRIVATE_LABELS,
    STAGE_PREFIX,
    STAGE_SUFFIX,
    _call,
    _close,
    create_private_at,
    create_private_child_at,
    make_stage_dir_at,
)
from decoy_engine.fileaccess._stage_claim import StageClaim, parent_identity_of
from decoy_engine.fileaccess._stage_walk import PathStageWalk, StageLife
from decoy_engine.fileaccess._types import (
    FileAccessUnavailable,
    FileRequest,
    LockUnavailable,
    StageDir,
    StageLabel,
)

_logger = logging.getLogger("decoy_engine.quarantine")

_CREATE = _osflags.WRONLY | _osflags.CREAT | _osflags.EXCL | _osflags.CLOEXEC


class LocalHandle:
    """A path standing in for an open file; nothing is opened until a library asks."""

    strict = False

    def __init__(self, path: str) -> None:
        self._path = path
        self.display = path
        self._fd: int | None = None

    def fileno(self) -> int:
        if self._fd is None:
            self._fd = os.open(self._path, _osflags.RDONLY | _osflags.CLOEXEC)
        return self._fd

    def library_path(self) -> str:
        return self._path

    def stat(self) -> os.stat_result:
        return Path(self._path).stat()

    def identity(self) -> str:
        """A key for "the same file" across calls: the resolved path, as the CLI always keyed."""
        return str(Path(self._path).resolve())

    def read_all(self, limit: int | None = None) -> bytes:
        with open(self._path, "rb") as fh:
            return fh.read() if limit is None else fh.read(limit)

    def open_binary(self, opener: Callable[..., BinaryIO] | None = None) -> BinaryIO:
        """`opener` lets a caller that already routes `open` through a seam keep doing so."""
        return (opener or open)(self._path, "rb")

    def open_text(self, encoding: str = "utf-8") -> TextIO:
        return open(self._path, encoding=encoding)

    def close(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

    def __enter__(self) -> LocalHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def engine_handle(path: str | os.PathLike[str]) -> LocalHandle:
    """A handle over a file the engine itself owns: shipped package data, or a scratch file
    it created in its own temp space.

    Never for a path that came from a config or a caller. Every call site is listed in the
    sentry registry with the rule that built its path."""
    return LocalHandle(os.fspath(path))


def engine_dir_handle(path: str | os.PathLike[str]) -> LocalDirHandle:
    """A directory handle over package data the engine ships (a model pack, a hint library).

    Never for a path that came from a config or a caller; every call site is listed in the
    sentry registry with the rule that built its path."""
    return LocalDirHandle(os.fspath(path))


class LocalDirHandle:
    def __init__(self, path: str) -> None:
        self._path = path
        self.display = path

    def entries(self) -> Iterator[os.DirEntry[str]]:
        yield from os.scandir(self._path)

    def open_file(self, rel: str) -> LocalHandle:
        return LocalHandle(os.path.join(self._path, rel))

    def open_dir(self, rel: str) -> LocalDirHandle:
        return LocalDirHandle(os.path.join(self._path, rel))

    def close(self) -> None:
        return None

    def __enter__(self) -> LocalDirHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _LocalStageDir(PathStageWalk, StageClaim):
    """Name-taking operations over one stage directory, by path."""

    strict = False

    def __init__(
        self, path: Path, display: str, *, private: bool = False, life: StageLife | None = None
    ) -> None:
        self._dir = path
        self.display = display
        self._display = display
        self._life = life or StageLife()
        self._private = private  # files 0600 with the owner bits restored (F22 Q8)

    def _check(self, *components: str) -> None:
        """Refuse a name that would leave the stage. Length and NUL are left to the operating
        system so the ambient policy raises the same errors a plain path write always did."""
        if self._life.finished:
            raise FileAccessUnavailable("output transaction is finished")
        for component in components:
            if not component or component in (".", "..") or "/" in component:
                raise deny(self._display)

    def create_file(self, component: str) -> int:
        self._check(component)
        if self._private and sys.platform != "win32":
            parent = _open_dir(self._dir)
            try:
                return create_private_child_at(parent, component)
            finally:
                _close(parent)
        return os.open(self._dir / component, _CREATE, 0o666)

    def open_file(self, component: str) -> int:
        self._check(component)
        return os.open(self._dir / component, _osflags.RDONLY | _osflags.CLOEXEC)

    def create_dir(self, component: str) -> _LocalStageDir:
        self._check(component)
        if sys.platform == "win32":
            (self._dir / component).mkdir()
        else:
            parent = _open_dir(self._dir)
            try:
                _close(make_stage_dir_at(parent, component))
            finally:
                _close(parent)
        return _LocalStageDir(
            self._dir / component, self._display, private=self._private, life=self._life
        )

    def remove(self, component: str) -> None:
        self._check(component)
        target = self._dir / component
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            os.unlink(target)

    def rename(self, src: str, dst: str) -> None:
        self._check(src, dst)
        os.rename(self._dir / src, self._dir / dst)

    def local_stage_path(self) -> str:
        return str(self._dir)


def _sync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so a rename into it survives a crash. A directory that
    cannot be opened, synced or closed is skipped: the rename has already published."""
    try:
        fd = os.open(directory, _osflags.RDONLY | _osflags.CLOEXEC)
    except OSError:
        return
    with contextlib.suppress(OSError):
        os.fsync(fd)
    with contextlib.suppress(OSError):
        os.close(fd)


def _probe_dir(path: str) -> os.stat_result:
    """`lstat` of a directory on a durable chain, for its device (the mount boundary) and its
    owner; it needs search permission on the directory above, not read permission on this one.
    A failure keeps only its errno, like every other call on the chain."""
    return _call(os.stat, path, follow_symlinks=False)


def _sync_up(directory: Path, strict_levels: int) -> None:
    """The ambient durable walk (`_durable._walk_up`) over the physical chain: links in the caller
    path are resolved first, and each directory is probed and opened by path here."""
    _durable._walk_up(
        os.path.realpath(directory), strict_levels, _probe_dir, lambda path: _open_dir(Path(path))
    )


def handed_stage_dir(path: Path, display: str) -> StageDir:
    """A private stage over a directory this process was handed by the one that made it: the
    isolated child adds files to the parent's stage and the parent writes its work root. Owner-only
    files, replace on rewrite, names refused if they would leave the stage. It issues no publish
    or abort: whoever made the directory decides its fate. Ambient policy only: the path is the
    caller's word, so any other policy raises `FileAccessUnavailable`."""
    from decoy_engine.fileaccess._entry import require_ambient  # _entry imports this module

    require_ambient("a handed stage directory")
    return _LocalStageDir(path, display, private=True)


def own_entry(path: Path, mode: int, *, directory: bool = False) -> None:
    """Set `mode` on an existing file (or directory) through its own descriptor, opened read-only
    without following a link: the repair a narrowing umask makes necessary for what a child
    wrote. Anything but the expected kind, or an entry its owner cannot read, raises with the
    errno only. Ambient policy only: any other policy raises `FileAccessUnavailable`."""
    from decoy_engine.fileaccess._entry import require_ambient  # _entry imports this module

    require_ambient("repairing a handed entry")
    fd = _call(
        os.open, path, _osflags.RDONLY | _osflags.NOFOLLOW | _osflags.NONBLOCK | _osflags.CLOEXEC
    )
    try:
        kind = os.fstat(fd).st_mode
        if not (stat.S_ISDIR(kind) if directory else stat.S_ISREG(kind)):
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        os.fchmod(fd, mode)
    finally:
        _close(fd)


class LocalOutputTxn(_LocalStageDir):
    """The legacy stage: a private stage directory (or one `mkstemp` file) in the target's
    parent."""

    def __init__(
        self,
        target: Path,
        kind: Literal["file", "dir"],
        mode: Literal["exclusive", "replace"],
        label: StageLabel,
        owner: object = None,
    ) -> None:
        self._target = target
        self.owner = owner
        self._kind = kind
        self._walkable = kind == "dir"
        self._mode = mode
        self._label = self.label = label
        self._staged_file: Path | None = None
        self._direct = False
        if (label == "publication" and kind != "dir") or (
            label in _durable.DURABLE_REPLACE_LABELS and mode != "replace"
        ):
            raise FileAccessUnavailable("the label does not fit this stage kind or mode")
        self._durable_dir = label in DIRECTORY_PUBLISH_LABELS and sys.platform != "win32"
        self._created: list[str] = []
        # A durable stage publishes through a parent descriptor opened before the stage exists.
        self._parent_fd = -1
        self._held = HeldStage()  # a publication stage's descriptor, holding its lock
        stage: Path | None = None
        if kind == "dir":
            if sys.platform == "win32":
                if label in CREATES_PARENTS:
                    target.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX[label], dir=target.parent))
            else:
                stage, self._held.fd = _make_stage_dir(
                    target.parent,
                    STAGE_PREFIX[label],
                    create_parents=label in CREATES_PARENTS,
                    created=self._created,
                )
                if label != "publication":
                    self._held.close()
                weakref.finalize(self, self._held.close)
        # Other private labels keep main's 0666 here; only a durable unit is owner-only (Q8).
        super().__init__(
            stage if stage is not None else target.parent, str(target), private=self._durable_dir
        )
        self._stage = stage

    def create_file(self, component: str) -> int:
        if self._kind == "file":
            self._check(component)
            if self._staged_file is not None:
                raise FileAccessUnavailable("a file stage holds exactly one file")
            if self._label in CREATES_PARENTS:
                if sys.platform == "win32":
                    self._target.parent.mkdir(parents=True, exist_ok=True)
                else:
                    _ensure_dirs(self._target.parent)
            if self._label in _durable.FD_STAGED_LABELS:
                return self._create_durable_stage()
            private = self._label in PRIVATE_LABELS
            # A private stage never writes through: publish replaces a symlink, not its target.
            if self._mode == "replace" and not private and self._writes_through():
                self._direct = True
                self._staged_file = self._target
                return os.open(self._target, _osflags.WRONLY | _osflags.TRUNC | _osflags.CLOEXEC)
            prefix = STAGE_PREFIX[self._label]
            suffix = STAGE_SUFFIX.get(self._label, "")
            if private:
                fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=self._target.parent)
                self._staged_file = Path(name)
                try:  # mkstemp's 0600 is narrowed by the umask; under 0777 it is born 000
                    os.fchmod(fd, 0o600)
                except OSError:
                    os.close(fd)
                    self.abort()
                    raise
                return fd
            stage = self._target.parent / f"{prefix}{secrets.token_hex(6)}{suffix}"
            self._staged_file = stage
            return os.open(stage, _CREATE, 0o666)
        return super().create_file(component)

    def _create_durable_stage(self) -> int:
        """Create the 0600 stage beside the leaf through the private-file choke point; a failure
        leaves nothing and keeps the ambient error shape (the class and the target's path)."""
        # Validate first: the shared publish checks the leaf only after the stage exists.
        validate_component(self._target.name, "fileaccess.stage")
        name = f"{STAGE_PREFIX[self._label]}{secrets.token_hex(6)}"
        failed: OSError | None = None
        try:
            self._parent_fd = _open_dir(self._target.parent)
            fd = create_private_at(self._parent_fd, name)
        except OSError as exc:
            failed = exc
        if failed is not None:
            code, cls = failed.errno, type(failed)
            del failed
            self._close_parent()
            raise cls(code, os.strerror(code or errno.EIO), str(self._target))
        self._staged_file = self._target.parent / name
        return fd

    def _close_parent(self) -> None:
        if self._parent_fd >= 0:
            fd, self._parent_fd = self._parent_fd, -1
            with contextlib.suppress(OSError):
                os.close(fd)

    def _unlink_stage(self) -> None:
        if self._staged_file is not None and self._parent_fd >= 0:
            _durable.discard_stage_at(self._parent_fd, self._staged_file.name)

    def _publish_durable(self) -> None:
        """Publish through the shared durable helper; only the path-shaped step 1 is ambient."""
        staged = self._staged_file
        if staged is None:  # pragma: no cover - checked by publish
            raise FileAccessUnavailable("nothing was staged")
        self._life.end()
        try:

            def rename() -> None:
                os.replace(staged, self._target)

            fd, name = self._parent_fd, staged.name
            _durable._publish_labelled(self._label, fd, name, self._target.name, rename)
        finally:
            self._close_parent()

    def _writes_through(self) -> bool:
        """A special file (`/dev/null`) or symlink is written in place, as the un-staged writer
        always did: a stage beside it cannot be renamed over it."""
        return self._target.is_symlink() or (self._target.exists() and not self._target.is_file())

    def local_stage_path(self) -> str:
        if self._stage is None:
            raise FileAccessUnavailable("a file stage has no directory path")
        return str(self._stage)

    def publish(self) -> None:
        if self._life.finished:
            raise FileAccessUnavailable("output transaction is finished")
        if self._kind == "dir":
            if self._stage is None:  # pragma: no cover - a dir stage always has one
                raise FileAccessUnavailable("output transaction is finished")
            if self._durable_dir:
                _publish_durable_dir(self._stage, self._held, self._target)
                self._stage = None
                self._life.end()
                strict = len(self._created) + 1
                _durable._sync_bound(lambda: _sync_up(self._target.parent, strict))
                return
            if sys.platform == "win32":
                self._target.parent.mkdir(parents=True, exist_ok=True)
            else:
                _ensure_dirs(self._target.parent)
            os.replace(self._stage, self._target)
            self._stage = None
            self._life.end()
            return
        staged = self._staged_file
        if staged is None:
            raise FileAccessUnavailable("nothing was staged")
        if self._label in _durable.FD_STAGED_LABELS:
            self._publish_durable()
            return
        if self._direct:
            self._life.end()
            return
        if self._mode == "replace":
            os.replace(staged, self._target)
            self._life.end()
            _sync_dir(self._target.parent)
            return
        occupied = False
        try:
            _durable.link_noclobber_at(None, staged, None, self._target)
        except FileExistsError:
            occupied = True
        if occupied:  # raised outside the handler: the link error (both paths) never rides
            with contextlib.suppress(OSError):
                staged.unlink(missing_ok=True)
            self._life.end()
            raise FileExistsError(errno.EEXIST, "output exists")
        self._life.end()
        try:
            os.unlink(staged)
        except OSError as exc:
            _logger.warning(
                "quarantine sidecar published but failed to remove the staging link (%s); "
                "the sidecar is intact and the leftover staging file is harmless",
                type(exc).__name__,
            )

    def abort(self) -> None:
        if self._life.finished:
            return
        self._life.end()
        if self._stage is not None:
            shutil.rmtree(self._stage, ignore_errors=True)
            self._stage = None
        self._held.close()  # after the stage is gone: the lock outlives the name
        if self._label in _durable.FD_STAGED_LABELS:
            self._unlink_stage()
            self._close_parent()
            return
        if self._staged_file is not None and not self._direct:
            with contextlib.suppress(OSError):
                self._staged_file.unlink(missing_ok=True)

    def __enter__(self) -> LocalOutputTxn:
        return self

    def __exit__(self, *exc: object) -> None:
        self.abort()


class LocalOutputDir:
    strict = False

    def __init__(self, req: FileRequest) -> None:
        self._target = Path(req.locator)
        self.display = self.locator = req.locator
        self.leaf = self._target.name
        self._field_key = req.field_key

    def parent_identity(self) -> tuple[int, int]:
        return parent_identity_of(self._parent_fd)

    def begin(
        self,
        kind: Literal["file", "dir"],
        mode: Literal["exclusive", "replace"],
        *,
        label: StageLabel,
    ) -> LocalOutputTxn:
        if label in DIRECTORY_PUBLISH_LABELS:
            validate_publication_leaf(self._target.name, self._field_key)
        return LocalOutputTxn(self._target, kind, mode, label, self)

    def ensure_dir(self) -> None:
        if sys.platform == "win32":
            self._target.parent.mkdir(parents=True, exist_ok=True)
            self._target.mkdir(exist_ok=True)
        else:
            _ensure_dirs(self._target)

    def is_empty_or_absent(self) -> bool:
        return not self._target.exists() or not any(self._target.iterdir())

    def _parent_fd(self) -> int:
        return _open_dir(self._target.parent)

    def lock(self, timeout_s: float) -> AbstractContextManager[None]:
        validate_publication_leaf(self._target.name, self._field_key)
        if sys.platform == "win32":  # the msvcrt lock is the Windows arm (F22 5.8); no fallback
            raise LockUnavailable(errno.ENOSYS)
        return _durable._held_lock(self._parent_fd, self._target.name, timeout_s)

    def read_member(self, component: str, *, limit: int) -> bytes | None:
        if not component or component in (".", "..") or "/" in component:
            raise deny(self._field_key)
        if sys.platform == "win32":
            raise FileAccessUnavailable("member reads come with the Windows arm")
        return _durable._read_member(self._parent_fd, self._target.name, component, limit)

    def sync_chain(self) -> None:
        if sys.platform == "win32":
            raise FileAccessUnavailable("the durable chain comes with the Windows arm")
        parent_fd = self._parent_fd()
        try:
            _durable._sync_leaf_at(parent_fd, self._target.name)
        finally:
            _close(parent_fd)
        _sync_up(self._target.parent, 1)

    def adopt_file(self, *, limit: int) -> bytes | None:
        if sys.platform == "win32":
            raise FileAccessUnavailable("adopting a file comes with the Windows arm")
        parent = self._target.parent
        return _durable._adopt_ambient(
            self._parent_fd, self._target.name, limit, lambda: _sync_up(parent, 1)
        )


class LocalFileAccess:
    """Constructed only inside `fileaccess/_entry.py`; never installed after `forbid_ambient()`."""

    def open_read(self, req: FileRequest) -> LocalHandle:
        return LocalHandle(req.locator)

    def open_dir(self, req: FileRequest) -> LocalDirHandle:
        return LocalDirHandle(req.locator)

    def stat(self, req: FileRequest) -> os.stat_result:
        return os.stat(req.locator)

    def output_dir(self, req: FileRequest) -> LocalOutputDir:
        return LocalOutputDir(req)

    def allows_subprocess(self) -> bool:
        return True

    def log_handler(self, locator: str, max_bytes: int, backup_count: int) -> logging.Handler:
        """The rotating file handler for the CLI's log file; ambient policy only, because a
        log is appended to for the life of the process and is not an output transaction."""
        parent = os.path.dirname(locator)
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        return logging.handlers.RotatingFileHandler(
            locator, maxBytes=max_bytes, backupCount=backup_count
        )


__all__ = ["LocalFileAccess", "engine_dir_handle", "engine_handle"]
