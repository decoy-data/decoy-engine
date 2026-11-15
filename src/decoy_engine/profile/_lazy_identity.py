"""The one place a file-backed lazy source checks that its file is still the one it described.

A lazy source reads a file twice: once for the routing facts and once for the batches. A file
replaced or edited in between would be routed on one file and read as another. The identity
(device, inode, size, mtime) is taken around the counting pass and again when the batch read
ends; any change is refused with `runtime.lazy_source_changed`. `LazyFileIdentity` holds that
protocol and the fact cache, so a backend supplies only `_measure()` (its facts for one file)
and cannot skip or reword a check. The sentry `test_lazy_identity_single_path` keeps backends
from carrying their own copy.

`check_batch_rows` is the one validator of the batch size every lazy backend accepts.
"""

from __future__ import annotations

import numbers
from typing import TYPE_CHECKING, Any

from decoy_engine._execution_error import lazy_source_changed

if TYPE_CHECKING:
    from collections.abc import Callable

    from decoy_engine.fileaccess import FileHandle
    from decoy_engine.profile._readers import FooterFacts

_Identity = tuple[int, int, int, int]


def check_batch_rows(batch_rows: object) -> int:
    """`batch_rows` as an `int`, or `ValueError`. A bool, a float (NaN and inf included), a
    string, `None` and anything below 1 are refused, so a bad size fails at the call and never
    reads as a whole-file batch or as no rows."""
    if (
        isinstance(batch_rows, bool)
        or not isinstance(batch_rows, numbers.Integral)
        or batch_rows < 1
    ):
        raise ValueError(f"batch_rows must be an int >= 1, got {batch_rows!r}")
    return int(batch_rows)


class LazyFileIdentity:
    """Mixin for a `LazySource` backed by one local file with no footer to read facts from.

    The subclass defines `_measure()`; `footer_facts()`, `_count_pass()` and `_open_facts()`
    are the shared protocol. Put it before `LazySource` in the bases."""

    table: str
    _seen: dict[str, Any]

    if TYPE_CHECKING:

        def _handle(self) -> FileHandle: ...

    def _measure(self) -> FooterFacts:
        """The facts for the file as it is now. Implemented by the backend."""
        raise NotImplementedError

    def _identity(self) -> _Identity:
        with self._handle() as handle:
            st = handle.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def footer_facts(self) -> FooterFacts:
        """Routing calls this several times, so the snapshot is reused while a single stat says
        the file is the one it describes; otherwise one pass refreshes it. Nothing else
        refreshes the snapshot."""
        if "facts" in self._seen and self._identity() == self._seen["identity"]:
            facts: FooterFacts = self._seen["facts"]
            return facts
        return self._count_pass()

    def _count_pass(self) -> FooterFacts:
        """`_measure()` between two identity reads."""
        before = self._identity()
        facts = self._measure()
        if self._identity() != before:
            raise lazy_source_changed(self.table, "the file changed while its facts were read")
        self._seen["facts"] = facts
        self._seen["identity"] = before
        return facts

    def _open_facts(self) -> tuple[FooterFacts, Callable[[], None]]:
        """The facts for one batch read and the check to run when it ends. The facts are the
        ones routing took when the file is unchanged since, else a file that moved is refused."""
        if "facts" in self._seen and self._identity() != self._seen["identity"]:
            raise lazy_source_changed(self.table, "the file changed since its facts were read")
        facts: FooterFacts = self._seen["facts"] if "facts" in self._seen else self.footer_facts()
        identity: _Identity = self._seen["identity"]

        def verify() -> None:
            if self._identity() != identity:
                raise lazy_source_changed(self.table, "the file changed while it was read")

        return facts, verify
