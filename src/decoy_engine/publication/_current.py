"""The managed pointer: one small file (`out/<name>/LATEST`) read and swapped under its F22 lock.

Pattern: Git ref compare-and-swap under a lockfile (`git update-ref <ref> <new> <old>`,
`refs/files-backend.c`: take the lock, compare the old value, write, fsync, rename). Here the lock
is F22's `.<leaf>.decoy-lock` and the compare is on raw bytes. A failed parent fsync after the
rename is `uncertain` (PostgreSQL's rule: the state is visible, not known durable). Contract:
`docs/publication.md`.

A pointer file is replaced only through `HeldPointer.swap`; the `pointer` file-access label
appears nowhere else (`tests/sentry/test_pointer_label_caller.py`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from decoy_engine._error_base import DecoyError
from decoy_engine.fileaccess import (
    CommitUncertain,
    FileAccessDenied,
    FileAccessUnavailable,
    LeafTooLarge,
    OutputDir,
)

_logger = logging.getLogger("decoy_engine.publication")
POINTER_LIMIT = 4096

PointerResult = Literal["replaced", "stale", "uncertain", "unknown", "failed", "conflict"]


@dataclass(frozen=True)
class PointerState:
    """The pointer as read: its raw bytes (`None` when absent) and a store-defined version."""

    raw: bytes | None
    version: bytes | str | None


class PointerUnreadable(DecoyError):  # noqa: N818 - the plan's name
    """The pointer cannot be read. Fixed text: no path, no byte, no OS message."""

    def __init__(self) -> None:
        super().__init__("pointer unreadable")

    def __reduce__(self) -> tuple[object, tuple[()]]:
        return (type(self), ())


class PointerStore(Protocol):
    """Where the pointer lives. `replace_if` compares `expected.raw` with the stored bytes and
    replaces them with `new` only on a match."""

    def read(self) -> PointerState: ...

    def replace_if(self, expected: PointerState, new: bytes) -> PointerResult: ...

    def locator(self) -> object:
        """What the store writes; `CurrentPointer` checks it against its lock."""
        ...


class LocalPointerStore:
    """A pointer in a local file: `leaf` is the `OutputDir` whose leaf is the pointer file."""

    def __init__(self, leaf: OutputDir) -> None:
        self._leaf = leaf

    def locator(self) -> object:
        return self._leaf.locator

    def _adopt(self) -> tuple[bytes | None, bool]:
        """The leaf bytes and whether the read failed (decided outside the handler, so no
        exception context survives)."""
        failed = False
        data: bytes | None = None
        try:
            data = self._leaf.adopt_file(limit=POINTER_LIMIT)
        except (OSError, FileAccessDenied, LeafTooLarge):
            failed = True
        return data, failed

    def read(self) -> PointerState:
        raw, failed = self._adopt()
        if failed:
            raise PointerUnreadable
        return PointerState(raw, raw)

    def replace_if(self, expected: PointerState, new: bytes) -> PointerResult:
        raw, failed = self._adopt()
        if failed:
            return "failed"
        if raw != expected.raw:
            return "stale"
        return self._publish(new)

    def _publish(self, new: bytes) -> PointerResult:
        uncertain = failed = False
        try:
            with self._leaf.begin("file", "replace", label="pointer") as txn:
                with os.fdopen(txn.create_file("value"), "wb") as fh:
                    fh.write(new)
                txn.publish()
        except CommitUncertain:
            uncertain = True
        except (OSError, FileAccessDenied, FileAccessUnavailable):
            failed = True
        if uncertain:
            return "uncertain"
        return "failed" if failed else "replaced"


class HeldPointer:
    """The pointer while its lock is held. It exists only inside `CurrentPointer.locked`."""

    def __init__(self, store: PointerStore) -> None:
        self._store: PointerStore | None = store

    def _close(self) -> None:
        self._store = None

    def swap(self, expected: PointerState, new: str) -> PointerResult:
        """Replace the pointer with `new` if it still matches `expected` (the state read before
        the run; never re-read here). A store answer of `unknown` gets one outcome-check read."""
        store = self._store
        if store is None:
            raise RuntimeError("the pointer lock is no longer held")
        payload = f"{new}\n".encode("ascii")
        result = store.replace_if(expected, payload)
        if result != "unknown":
            return result
        confirmed = False
        try:
            confirmed = store.read().raw == payload
        except PointerUnreadable:
            pass
        return "replaced" if confirmed else "uncertain"


class CurrentPointer:
    """A pointer in `store`, locked through `lock`, the same leaf `OutputDir`."""

    def __init__(self, store: PointerStore, lock: OutputDir) -> None:
        if store.locator() != lock.locator:
            raise ValueError("the pointer store and its lock name different leaves")
        self._store = store
        self._lock = lock

    def read(self) -> PointerState:
        return self._store.read()

    @contextmanager
    def locked(self, timeout_s: float) -> Iterator[HeldPointer]:
        with self._lock.lock(timeout_s):
            held = HeldPointer(self._store)
            try:
                yield held
            finally:
                held._close()


def read_value(raw: bytes | None, accept: Callable[[str], bool]) -> str | None:
    """The pointer's value, or `None` for an absent or malformed pointer (the malformed cases
    log one value-free warning). A valid value has exactly one trailing newline stripped."""
    if raw is None:
        return None
    value = _decode(raw)
    if value is None or not accept(value):
        _logger.warning("the pointer file holds no valid value; it is ignored")
        return None
    return value


def _decode(raw: bytes) -> str | None:
    if len(raw) > POINTER_LIMIT or not raw.endswith(b"\n") or not raw.isascii():
        return None
    value = raw[:-1].decode("ascii")
    return None if "\n" in value else value


__all__ = [
    "CurrentPointer",
    "HeldPointer",
    "LocalPointerStore",
    "PointerResult",
    "PointerState",
    "PointerStore",
    "PointerUnreadable",
    "read_value",
]
