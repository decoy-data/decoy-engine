"""The rooted output directory: one held root descriptor and one allowed leaf (F25, DELIV E2b).

Split from `_output.py` along its reason to change: that module holds the descriptor creators and
the stage transaction; this one resolves a request's relative locator beneath a held root and hands
out the transaction. It creates nothing itself except through those creators.
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Literal

from decoy_engine.fileaccess import _openat2, _osflags
from decoy_engine.fileaccess._component import validate_component, validate_publication_leaf
from decoy_engine.fileaccess._errors import deny
from decoy_engine.fileaccess._fdtree import _close
from decoy_engine.fileaccess._output import (
    _ISSUER,
    CREATES_PARENTS,
    DIRECTORY_PUBLISH_LABELS,
    RootedOutputTxn,
    make_parent_dir_at,
)
from decoy_engine.fileaccess._stage_claim import parent_identity_of
from decoy_engine.fileaccess._types import FileRequest, StageLabel

__all__ = ["RootedOutputDir"]


class RootedOutputDir:
    """An output root fd plus one allowed leaf. Parent directories are created one validated
    component at a time with `make_parent_dir_at` and opened with `openat2` when only read;
    no symlink is ever followed."""

    strict = True

    def __init__(self, root_fd: int, rel: str, req: FileRequest) -> None:
        parts = rel.split("/")
        if any(p in ("", ".") for p in parts[:-1]) or not parts:
            raise deny(req.field_key)
        for part in parts:
            validate_component(part, req.field_key)
        self._root_fd = root_fd
        self._parents = parts[:-1]
        self._leaf = self.leaf = parts[-1]
        self.display = req.field_key
        self.locator = req.locator
        self._field_key = req.field_key

    def parent_identity(self) -> tuple[int, int]:
        return parent_identity_of(lambda: self._open_parent(create=False))

    def _open_parent(self, *, create: bool, chain: list[int] | None = None) -> int:
        """The leaf's parent, opened from the root; `chain` keeps every directory above it."""
        fd = os.dup(self._root_fd)
        try:
            for part in self._parents:
                if create:
                    child = make_parent_dir_at(fd, part)
                else:
                    child = _openat2._confined_open(fd, part, _osflags.RDONLY | _osflags.DIRECTORY)
                if chain is None:
                    _close(fd)
                else:
                    chain.append(fd)
                fd = child
        except OSError:
            _close(fd)
            raise
        return fd

    def begin(
        self,
        kind: Literal["file", "dir"],
        mode: Literal["exclusive", "replace"],
        *,
        label: StageLabel,
    ) -> RootedOutputTxn:
        if label in DIRECTORY_PUBLISH_LABELS:
            validate_publication_leaf(self._leaf, self._field_key)
        failed = False
        parent = -1
        chain: list[int] = []
        try:
            parent = self._open_parent(create=label in CREATES_PARENTS, chain=chain)
        except OSError:
            failed = True
        try:
            if failed:
                raise deny(self._field_key) from None
            held = tuple(chain) if label in DIRECTORY_PUBLISH_LABELS else ()
            return RootedOutputTxn(
                _ISSUER, parent, self._leaf, kind, mode, label, self.display, held, self
            )
        finally:
            for fd in (parent, *chain):
                if fd >= 0:
                    _close(fd)

    def ensure_dir(self) -> None:
        failed = False
        parent = -1
        try:
            parent = self._open_parent(create=True)
            _close(make_parent_dir_at(parent, self._leaf))
        except OSError:
            failed = True
        finally:
            if parent >= 0:
                _close(parent)
        if failed:
            raise deny(self._field_key) from None

    def lock(self, timeout_s: float) -> AbstractContextManager[None]:
        from decoy_engine.fileaccess import _durable

        validate_publication_leaf(self._leaf, self._field_key)
        return _durable._held_lock(self._parent_reader, self._leaf, timeout_s)

    def read_member(self, component: str, *, limit: int) -> bytes | None:
        from decoy_engine.fileaccess import _durable

        validate_component(component, self._field_key)
        return _durable._read_member(self._parent_reader, self._leaf, component, limit)

    def _parent_reader(self) -> int:
        return self._open_parent(create=False)

    def sync_chain(self) -> None:
        from decoy_engine.fileaccess import _durable

        _durable._sync_rooted_chain(self._open_parent, self._leaf)

    def adopt_file(self, *, limit: int) -> bytes | None:
        from decoy_engine.fileaccess._durable import _adopt_rooted

        return _adopt_rooted(self._open_parent, self._leaf, limit)

    def is_empty_or_absent(self) -> bool:
        failed = False
        parent = child = -1
        try:
            parent = self._open_parent(create=False)
            child = _openat2._confined_open(
                parent, self._leaf, _osflags.RDONLY | _osflags.DIRECTORY
            )
        except FileNotFoundError:
            return True
        except OSError:
            failed = True
        finally:
            if parent >= 0:
                _close(parent)
        if failed:  # raised outside the handler: the OSError (which names the leaf) never rides
            raise deny(self._field_key)
        try:
            with os.scandir(child) as it:
                return next(it, None) is None
        finally:
            _close(child)
