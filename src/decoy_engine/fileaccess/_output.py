"""Policy-issued output transactions over directory descriptors (strict policies).

Pattern: `cap-std`'s `Dir` (create, rename and remove only through a held directory handle),
Spark's `FileOutputCommitter` (stage privately, publish with one rename, delete the stage on
abort) and POSIX `renameat`/`linkat` between directory fds. The caller never supplies or sees a
stage pathname: the stage has a random name beside the final leaf, so publication is a rename on
one filesystem. Every child name passes `validate_component` inside the transaction, and every
operation is one `dir_fd`-relative call with `O_NOFOLLOW`, so a symlink planted in the stage is
never followed.

Publication keeps each sink's existing semantics: a directory stage publishes with plain
`rename(2)` (`ENOTEMPTY` on a non-empty destination, stage intact for `abort()`), a file stage with
`link(2)` (`exclusive`) or `rename(2)` (`replace`; `pointer` then fsyncs its parent). A
`DIRECTORY_PUBLISH_LABELS` stage is fsynced before the rename and its parent chain after.

Directories are made by one core, `_make_dir_core`, with two entry points: `make_stage_dir_at`
(private stage directories, exact 0700) and `make_parent_dir_at` (user-named output parents at
their real name, born mode with the owner bits forced). The core creates with the requested mode,
observes the mode the filesystem gave (the umask or a default ACL decides it) and repairs only the
owner bits, so Decoy can always open what it made; it never reads or sets the process umask. A
parent keeps an inherited set-group-ID bit through that repair, as Git's `adjust_shared_perm` does.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
import sys
import weakref
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from decoy_engine.fileaccess import _fdtree, _osflags
from decoy_engine.fileaccess._component import validate_component
from decoy_engine.fileaccess._errors import deny
from decoy_engine.fileaccess._fdtree import _DIR_FLAGS, _close, _rmtree_fd
from decoy_engine.fileaccess._link import CREATOR_KEY as _CREATOR_KEY
from decoy_engine.fileaccess._link import raise_link_error
from decoy_engine.fileaccess._stage_claim import StageClaim
from decoy_engine.fileaccess._stage_walk import StageLife, StageWalk
from decoy_engine.fileaccess._types import FileAccessUnavailable, StageLabel

# The only names a caller can influence: a closed label picks a prefix, never a path.
STAGE_PREFIX: dict[str, str] = {
    "table_sink": "_decoy_stage_",
    "quarantine": "_decoy_quarantine_stage_",
    "quarantine_direct": "_decoy_quarantine_stage_",
    "isolated": "_decoy_isolated_stage_",
    "hold": "_decoy_hold_",
    "subset": "_decoy_subset_stage_",
    "vault": "_decoy_vault_stage_",
    "pack": "_decoy_pack_stage_",
    "publication": "._decoy_publication_pending_",
    "delivery_slots": "._decoy_delivery_slots_",
    "pointer": "._decoy_pointer_stage_",
}
STAGE_SUFFIX: dict[str, str] = {"quarantine": ".jsonl", "quarantine_direct": ".jsonl"}
DURABLE_REPLACE_LABELS: frozenset[str] = frozenset({"pointer"})  # stage fsync, rename, parent fsync
# Labels whose stage holds secrets or real data (0600 at creation), durable-replace ones included.
PRIVATE_LABELS = DURABLE_REPLACE_LABELS | {
    *("quarantine", "isolated", "vault", "publication", "delivery_slots")
}
# `DURABLE_LABELS` publish exclusively: the writer fsyncs the stage, it is linked, then the parent is
# fsynced (the commit point; its failure is raised). A failure removes only the stage.
DURABLE_LABELS: frozenset[str] = frozenset({"vault"})
# Labels whose directory publish is durable (F22 5.1): the walk, the rename, then the chain.
DIRECTORY_PUBLISH_LABELS: frozenset[str] = frozenset({"publication"})
# Every output but a vault leaf may create missing parent directories; a vault leaf sits
# directly in a directory the caller already provided.
CREATES_PARENTS: frozenset[str] = frozenset(STAGE_PREFIX) - {"vault"}

T = TypeVar("T")


_NOFOLLOW_CLOEXEC = _osflags.NOFOLLOW | _osflags.CLOEXEC
_FILE_CREATE = _osflags.WRONLY | _osflags.CREAT | _osflags.EXCL | _NOFOLLOW_CLOEXEC


def _call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run one syscall wrapper. A failure keeps only its errno: the stock `OSError` text
    names the stage and leaf, and a basename must not reach an error message."""
    code = 0
    try:
        return fn(*args, **kwargs)
    except OSError as exc:
        code = exc.errno or errno.EIO
    raise OSError(code, os.strerror(code)) from None


def _born_mode(parent_fd: int, name: str) -> int:
    """The mode of a directory this call just made but cannot open for reading. An `O_PATH`
    descriptor needs no permission on the directory itself, so its `fstat` sees what the
    umask left. Elsewhere the group and other bits are not observable without a read, so the
    repair falls back to owner-only (narrower, never wider)."""
    if sys.platform != "linux":
        return stat.S_IFDIR | 0o700
    fd = _call(os.open, name, _osflags.PATH | _NOFOLLOW_CLOEXEC, dir_fd=parent_fd)
    try:
        born = os.fstat(fd).st_mode
    finally:
        _close(fd)
    if not stat.S_ISDIR(born):  # a link swapped in after mkdir: never chmod through it
        raise OSError(errno.ENOTDIR, os.strerror(errno.ENOTDIR))
    return born


def _make_dir_core(parent_fd: int, name: str, mode: int, *, keep_special: bool) -> tuple[int, int]:
    """Create directory ``name`` under ``parent_fd`` with ``mode``, open it, and return the
    descriptor and the born mode. The umask (or a default ACL) only narrows the mode, so the
    owner bits it stripped are restored to ``(born & 0o777) | 0o700``; with ``keep_special``
    an inherited set-group-ID bit is kept, without it any special bit is cleared. Failures keep
    only their errno; the directory this call made is removed if a later step fails, and an
    existing entry is never touched (``mkdir`` raises ``EEXIST`` first)."""
    _call(os.mkdir, name, mode, dir_fd=parent_fd)
    fd = -1
    try:
        try:
            fd = _call(os.open, name, _DIR_FLAGS, dir_fd=parent_fd)
            born = os.fstat(fd).st_mode
        except PermissionError:
            born = _born_mode(parent_fd, name)
            # Named limit L6: this chmod goes by name, so a different user who can write in the
            # caller's output directory could swap a symlink in between mkdir and here. The effect
            # stays bounded: owner bits on a path the engine user owns, and no read. An fd-only
            # repair is impossible: an unreadable directory cannot be opened for it, and fchmod
            # on an O_PATH descriptor gives EBADF.
            _call(os.chmod, name, _repaired(born, keep_special), dir_fd=parent_fd)
            fd = _call(os.open, name, _DIR_FLAGS, dir_fd=parent_fd)
        now = os.fstat(fd).st_mode
        if (now & 0o700) != 0o700 or (not keep_special and now & 0o7000):
            _call(os.fchmod, fd, _repaired(born, keep_special))
    except OSError:
        _close(fd)
        with contextlib.suppress(OSError):
            os.rmdir(name, dir_fd=parent_fd)
        raise
    return fd, born


def _repaired(born: int, keep_special: bool) -> int:
    return (born & (0o7777 if keep_special else 0o777)) | 0o700


def make_stage_dir_at(parent_fd: int, name: str) -> int:
    """Create private stage directory ``name`` under ``parent_fd``, exactly 0700 whatever the
    umask or an inherited set-group-ID bit, and return it opened. ``EEXIST`` is raised and the
    existing entry left untouched."""
    validate_component(name, _CREATOR_KEY)
    return _make_dir_core(parent_fd, name, 0o700, keep_special=False)[0]


def make_parent_dir_at(parent_fd: int, name: str) -> int:
    """Create output parent ``name`` under ``parent_fd`` at its real name and return it opened;
    the only creator of user-named directories on an output chain (F22 5.0 rule 1).

    Its permission bits are the born ones with the owner bits forced (0755 under umask 022,
    0700 under 0477) and an inherited set-group-ID bit is kept, so a group-shared parent keeps
    its group. ``EEXIST`` (another attempt or process made it first) continues with the existing
    directory, opened without following a link and never repaired: one Decoy cannot open is
    refused with its errno (named limit L1u). ``name`` is one component the caller already
    holds: the strict policy validated it, and the ambient policy passes the user's path
    components unchanged, as its path semantics always have."""
    try:
        return _make_dir_core(parent_fd, name, 0o777, keep_special=True)[0]
    except FileExistsError:
        pass
    return _open_existing_dir(parent_fd, name)


def _open_existing_dir(parent_fd: int, name: str) -> int:
    return _call(os.open, name, _DIR_FLAGS, dir_fd=parent_fd)


def set_mode_fd(fd: int, mode: int) -> None:
    """The one `fchmod` on a held file descriptor, errno only on failure."""
    _call(os.fchmod, fd, mode)


def _restore_always(fd: int) -> None:
    set_mode_fd(fd, 0o600)


def link_noclobber_at(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """Link `src_name` to `dst_name` without replacing it, both validated components beneath held
    directories, never following a symlink. Raises `FileExistsError` for a taken name,
    `LinkUnsupported` for the errnos in `LINK_UNSUPPORTED` (or a backend whose `os.link` has no
    descriptor form, answered as ENOSYS) and an errno-only `OSError` for anything else."""
    validate_component(src_name, _CREATOR_KEY)
    validate_component(dst_name, _CREATOR_KEY)
    code = 0
    try:
        os.link(
            src_name, dst_name, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=False
        )
    except OSError as exc:
        code = exc.errno or errno.EIO
    except (NotImplementedError, TypeError):  # no descriptor or no-follow form on this backend
        code = errno.ENOSYS
    raise_link_error(code)


def _restore_missing_owner_bits(fd: int) -> None:
    """Repair only what the umask stripped, so a filesystem that already reports owner read and
    write is not asked for a chmod it may refuse."""
    if (_call(os.fstat, fd).st_mode & 0o600) != 0o600:
        _call(os.fchmod, fd, 0o600)


def _create_private_core(dir_fd: int, name: str, restore: Callable[[int], None]) -> int:
    """The one private-file creation: ``O_EXCL`` so only this call's file is ever touched, then
    the caller's restorer. If the restorer fails, close and unlink the name this call created."""
    fd = _call(os.open, name, _FILE_CREATE, 0o600, dir_fd=dir_fd)
    try:
        restore(fd)
    except OSError:
        _close(fd)
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=dir_fd)
        raise
    return fd


def create_private_at(dir_fd: int, name: str) -> int:
    """A new 0600 file whose mode is set unconditionally (top-level private stages, arena files)."""
    validate_component(name, _CREATOR_KEY)
    return _create_private_core(dir_fd, name, _restore_always)


def create_private_child_at(dir_fd: int, name: str) -> int:
    """A new private file inside a stage directory: owner bits restored only when missing."""
    validate_component(name, _CREATOR_KEY)
    return _create_private_core(dir_fd, name, _restore_missing_owner_bits)


def create_output_file_at(dir_fd: int, name: str, mode: int) -> int:
    """A new output-mode file; the umask governs ``mode``."""
    validate_component(name, _CREATOR_KEY)
    return _call(os.open, name, _FILE_CREATE, mode, dir_fd=dir_fd)


def _dup(held_fd: int) -> int:
    return os.dup(held_fd)


def _mark_publication_stage(parent_fd: int, name: str, stage_fd: int) -> None:
    """Lock stage `name` until `stage_fd` closes, write and prove its marker; on failure remove it."""
    try:
        _fdtree.hold_stage_lock(stage_fd)
        token, marker = name.removeprefix(STAGE_PREFIX["publication"]), -1
        try:
            marker = create_private_at(stage_fd, _fdtree.STAGE_MARKER)
            _fdtree._write_marker(marker, _fdtree.STAGE_MAGIC, token)
        finally:
            _close(marker)
        if _fdtree.prove_stage(stage_fd) != token:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
    except BaseException:
        with contextlib.suppress(OSError):
            _rmtree_fd(stage_fd, parent_fd)
            os.rmdir(name, dir_fd=parent_fd)
        raise


class _State(StageLife):
    """What a transaction owns, held apart from the object so collection can clean up."""

    def __init__(self, parent_fd: int, stage_name: str, kind: str) -> None:
        self.parent_fd = parent_fd
        self.stage_name = stage_name
        self.kind = kind
        self.stage_fd = -1
        super().__init__()
        self.file_created = False
        self.child_fds: list[int] = []
        self.chain_fds: list[int] = []  # root down to the parent's parent, for a durable publish


def _close_all(fds: list[int]) -> None:
    while fds:
        _close(fds.pop())


def _discard(state: _State) -> None:
    if state.finished:
        return
    state.end()
    try:
        if state.kind == "dir":
            if state.stage_fd >= 0:
                with contextlib.suppress(OSError):
                    _rmtree_fd(state.stage_fd, state.parent_fd)
            with contextlib.suppress(OSError):
                os.rmdir(state.stage_name, dir_fd=state.parent_fd)
            _close(state.stage_fd)  # after the rmdir: the liveness lock outlives the name
        else:
            with contextlib.suppress(OSError):
                os.unlink(state.stage_name, dir_fd=state.parent_fd)
    finally:
        state.stage_fd = -1
        _close_all(state.child_fds)
        _close_all(state.chain_fds)
        _close(state.parent_fd)


class _StageDir(StageWalk, StageClaim):
    """Name-taking operations over one stage directory descriptor."""

    strict = True

    def __init__(self, dir_fd: int, display: str, live: _State, mode_bits: int) -> None:
        self._fd = dir_fd
        self.display = display
        self._display = display
        self._live = self._life = live
        self._mode = mode_bits

    def _check(self, *components: str) -> None:
        if self._live.finished:
            raise FileAccessUnavailable("output transaction is finished")
        for component in components:
            validate_component(component, self._display)

    def create_file(self, component: str) -> int:
        self._check(component)
        if self._mode == 0o600:
            return create_private_child_at(self._fd, component)
        return create_output_file_at(self._fd, component, self._mode)

    def open_file(self, component: str) -> int:
        self._check(component)
        return _call(os.open, component, _osflags.RDONLY | _NOFOLLOW_CLOEXEC, dir_fd=self._fd)

    def create_dir(self, component: str) -> _StageDir:
        self._check(component)
        child = make_stage_dir_at(self._fd, component)
        self._live.child_fds.append(child)
        return _StageDir(child, self._display, self._live, self._mode)

    def remove(self, component: str) -> None:
        self._check(component)
        try:
            _call(os.unlink, component, dir_fd=self._fd)
        except IsADirectoryError:
            _call(os.rmdir, component, dir_fd=self._fd)

    def rename(self, src: str, dst: str) -> None:
        self._check(src, dst)
        _call(os.rename, src, dst, src_dir_fd=self._fd, dst_dir_fd=self._fd)

    def local_stage_path(self) -> str:
        raise FileAccessUnavailable("a strict policy has no stage path to hand to a subprocess")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError(
            "an output transaction cannot be serialized; it crosses a process as its fd"
        )


_ISSUER = object()


class RootedOutputTxn(_StageDir):
    """The top-level stage: publishes once or aborts, never both. Only `RootedOutputDir.begin`
    can make one: the issuer token is private to this module, so a transaction built any other
    way is refused before it touches a descriptor."""

    def __init__(
        self,
        issuer: object,
        parent_fd: int,
        leaf: str,
        kind: Literal["file", "dir"],
        mode: Literal["exclusive", "replace"],
        label: StageLabel,
        display: str,
        chain: tuple[int, ...] = (),
        owner: object = None,
    ) -> None:
        if issuer is not _ISSUER:
            raise FileAccessUnavailable("an output transaction is issued by an OutputDir")
        validate_component(leaf, display)
        if label not in STAGE_PREFIX or (label in DURABLE_REPLACE_LABELS and mode != "replace"):
            raise deny(display)  # an in-place label exists only for the ambient policy
        if label == "publication" and kind != "dir":
            raise FileAccessUnavailable("a publication stage is a directory")
        self._durable = label in DURABLE_LABELS
        self._durable_replace = label in DURABLE_REPLACE_LABELS
        self._durable_dir = label in DIRECTORY_PUBLISH_LABELS
        self.label, self.owner = label, owner  # read by `publish_unit`
        self._leaf = leaf
        self._publish_mode = mode
        name = f"{STAGE_PREFIX[label]}{secrets.token_hex(6)}{STAGE_SUFFIX.get(label, '')}"
        self._state = state = _State(os.dup(parent_fd), name, kind)
        try:  # no finalizer yet: a failure closes every descriptor this call opened
            for fd in chain:
                state.chain_fds.append(_dup(fd))
            if kind == "dir":
                state.stage_fd = make_stage_dir_at(state.parent_fd, name)
            if label == "publication":
                _mark_publication_stage(state.parent_fd, name, state.stage_fd)
        except BaseException:
            _close_all([*state.chain_fds, state.stage_fd, state.parent_fd])
            raise
        self._private = label in PRIVATE_LABELS
        super().__init__(state.stage_fd, display, state, 0o600 if self._private else 0o666)
        self._finalizer = weakref.finalize(self, _discard, state)

    def create_file(self, component: str) -> int:
        if self._state.kind == "file":
            self._check(component)
            if self._state.file_created:
                raise FileAccessUnavailable("a file stage holds exactly one file")
            self._state.file_created = True
            if self._private:
                return create_private_at(self._state.parent_fd, self._state.stage_name)
            return create_output_file_at(self._state.parent_fd, self._state.stage_name, self._mode)
        return super().create_file(component)

    def _rename_stage(self) -> None:
        parent = self._state.parent_fd
        _call(os.replace, self._state.stage_name, self._leaf, src_dir_fd=parent, dst_dir_fd=parent)

    def publish(self) -> None:
        from decoy_engine.fileaccess import _durable

        state = self._state
        if state.finished:
            raise FileAccessUnavailable("output transaction is finished")
        if state.kind == "file" and not state.file_created:
            raise FileAccessUnavailable("nothing was staged")
        parent = state.parent_fd
        if state.kind == "file" and (self._publish_mode == "exclusive" or self._durable_replace):
            if self._durable or self._durable_replace:
                try:
                    _durable._publish_labelled(
                        self.label, parent, state.stage_name, self._leaf, self._rename_stage
                    )
                except OSError:
                    _discard(state)  # the stage only; a bound leaf is never removed
                    raise
            else:
                try:
                    link_noclobber_at(parent, state.stage_name, parent, self._leaf)
                except FileExistsError:
                    _discard(state)
                    raise
                _durable.discard_stage_at(parent, state.stage_name)
        else:
            if self._durable_dir:  # a failure here leaves the stage for abort()
                _durable._sync_tree(state.stage_fd)
            self._rename_stage()
            if state.kind == "file":
                _durable._sync(parent)
        state.end()
        if state.stage_fd >= 0:
            _close(state.stage_fd)
            state.stage_fd = -1
        _close_all(state.child_fds)
        self._finalizer.detach()
        try:
            if self._durable_dir:  # the parent is the commit point, then up to the root
                chain = [parent, *reversed(state.chain_fds)]
                _durable._sync_bound(lambda: _durable._sync_fds(chain))
        finally:
            _close_all(state.chain_fds)
            _close(parent)

    def abort(self) -> None:
        _discard(self._state)
        self._finalizer.detach()

    def __enter__(self) -> RootedOutputTxn:
        return self

    def __exit__(self, *exc: object) -> None:
        self.abort()


__all__ = [
    "DIRECTORY_PUBLISH_LABELS",
    "DURABLE_LABELS",
    "PRIVATE_LABELS",
    "STAGE_PREFIX",
    "STAGE_SUFFIX",
    "RootedOutputTxn",
]
