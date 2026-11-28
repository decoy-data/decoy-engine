"""One cleanup owner per run: a path is recorded before the call that creates it and released
only after its removal is confirmed.

Invariant: a path enters the ledger immediately before the exclusive create that makes it, and
only after the name was proven absent; it leaves only when a no-follow lookup after removal shows
it gone, and the ledger never removes a path it does not hold.

Patterns taken: write-ahead undo logging (ARIES, Mohan et al. 1992): the undo record exists before
the change, undo is idempotent, a record is retired only after the undo is confirmed, and
`close()` re-runs undo for every record not retired. CPython `tempfile.mkstemp` supplies the
exclusive, random-name create. Patterns not taken: `tempfile.TemporaryDirectory` registers its
finalizer one statement after `mkdtemp`, and `weakref.finalize` and `ExitStack` pop an entry
before running it, so a cleanup that raises is never retried.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable
from typing import TypeVar

from decoy_engine.fileaccess import _fdtree
from decoy_engine.fileaccess._types import FileAccessUnavailable

T = TypeVar("T")

INTENT, OWNED, REMOVED, RELEASED, FOREIGN = "INTENT", "OWNED", "REMOVED", "RELEASED", "FOREIGN"
_HELD = (INTENT, OWNED, REMOVED)
_Key = tuple[int, int, str]


class _Entry:
    """One owned path. `state` moves by single attribute stores of the constants above."""

    __slots__ = ("confirm", "key", "observation", "on_release", "operand", "parent", "state")

    def __init__(self) -> None:
        self.key: _Key | None = None
        self.operand: str | None = None
        self.parent: str | None = None
        self.state = INTENT
        self.on_release: Callable[[], None] | None = None
        self.confirm: Callable[[], bool] | None = None
        self.observation = _fdtree.OBSERVED_UNKNOWN


class Deferred(_Entry):
    """A slot for a cleanup whose confirmation belongs to another owner (a publication stage).

    Reserved before the thing exists; bind it once with `slot.confirm = discard`. An unbound slot
    is released at close with nothing to do."""

    __slots__ = ("_ledger",)

    def __init__(self, ledger: CleanupLedger) -> None:
        super().__init__()
        self._ledger = ledger

    def attempt(self) -> str:
        """One attempt, the same transition `close()` makes; returns what it observed."""
        self._ledger._attempt(self)
        return self.observation


def _unheld() -> FileAccessUnavailable:
    return FileAccessUnavailable("the cleanup ledger does not hold this path.")


class CleanupLedger:
    """Directories the run created, each removed and proven gone before it is let go."""

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def __enter__(self) -> CleanupLedger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- recording ---------------------------------------------------------------------------

    def acquire(
        self,
        path: str | os.PathLike[str],
        create: Callable[[str], T],
        *,
        on_release: Callable[[], None] | None = None,
    ) -> T:
        """Record `path` as `INTENT`, then call `create(operand)` once with the exact absolute
        operand. A name already present is refused with `FileExistsError` before any callback."""
        operand, parent, key = self._resolve(path)
        if _fdtree._lstat(operand) is not None:
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST))
        entry = _Entry()
        entry.key, entry.operand, entry.parent, entry.on_release = key, operand, parent, on_release
        self._entries.append(entry)
        try:
            result = create(operand)
        except FileExistsError:
            entry.state = FOREIGN  # a same-user race took the name; it is not ours to remove
            raise
        entry.state = OWNED
        return result

    def defer(self) -> Deferred:
        slot = Deferred(self)
        self._entries.append(slot)
        return slot

    @staticmethod
    def _resolve(path: str | os.PathLike[str]) -> tuple[str, str, _Key]:
        raw = os.fspath(path)
        if _fdtree.has_parent_component(raw):
            raise _unheld()
        parent, leaf = os.path.split(os.path.abspath(raw))
        physical, ident = _fdtree._physical_parent(parent)
        return os.path.join(physical, leaf), physical, (ident[0], ident[1], leaf)

    # -- removal -----------------------------------------------------------------------------

    def remove(self, path: str | os.PathLike[str]) -> bool:
        """Remove a held path now. True when the entry ends released; False keeps it for
        `close()`. A path the ledger does not hold raises and nothing is touched."""
        entry = self._attempt_path(path)
        return entry is not None and entry.state == RELEASED

    def remove_attempt(self, path: str | os.PathLike[str]) -> str:
        """`remove`, returning what this attempt observed: removed, pending or unknown."""
        entry = self._attempt_path(path)
        return _fdtree.OBSERVED_UNKNOWN if entry is None else entry.observation

    def _attempt_path(self, path: str | os.PathLike[str]) -> _Entry | None:
        """The entry after one attempt; None when the parent cannot be resolved (retry at close)."""
        raw = os.fspath(path)
        if _fdtree.has_parent_component(raw):
            raise _unheld()
        parent, leaf = os.path.split(os.path.abspath(raw))
        try:
            _, ident = _fdtree._physical_parent(parent)
        except OSError:
            return None
        key = (ident[0], ident[1], leaf)
        entry = next((e for e in self._entries if e.key == key and e.state in _HELD), None)
        if entry is None:
            raise _unheld()
        self._attempt(entry)
        return entry

    def _attempt(self, entry: _Entry) -> None:
        if entry.state in (RELEASED, FOREIGN):
            return
        if entry.state in (INTENT, OWNED):
            if not self._removal_confirmed(entry):
                return
            entry.state = REMOVED
        if entry.on_release is not None:
            entry.on_release()
        entry.state = RELEASED

    def _removal_confirmed(self, entry: _Entry) -> bool:
        if entry.confirm is not None:  # a deferred slot: its owner proves the removal
            return entry.confirm()
        operand = entry.operand
        if operand is None:  # an unbound slot has nothing to remove
            return True
        try:
            _, ident = _fdtree._physical_parent(entry.parent or "")
        except FileNotFoundError:
            entry.observation = _fdtree.observe(operand)
            return entry.observation == _fdtree.OBSERVED_REMOVED
        except OSError:
            entry.observation = _fdtree.OBSERVED_UNKNOWN
            return False
        if entry.key is None or ident != entry.key[:2]:
            entry.observation = _fdtree.OBSERVED_UNKNOWN
            return False
        entry.observation = _fdtree.observe(operand)
        if entry.observation == _fdtree.OBSERVED_REMOVED:
            return True
        if entry.observation == _fdtree.OBSERVED_UNKNOWN:
            return False
        return _fdtree.remove_confirmed(operand, record=entry)

    # -- close -------------------------------------------------------------------------------

    def _pass(self, entries: list[_Entry], i: int) -> None:
        if i < len(entries):
            try:
                self._attempt(entries[i])
            finally:
                self._pass(entries, i + 1)

    def close(self) -> None:
        """Two passes, children before parents. Every entry is tried in both passes even when an
        earlier attempt raised; the last non-`OSError` escapes with the earlier ones chained."""
        entries = [e for e in reversed(self._entries) if e.state not in (RELEASED, FOREIGN)]
        try:
            self._pass(entries, 0)
        finally:
            self._pass(entries, 0)
