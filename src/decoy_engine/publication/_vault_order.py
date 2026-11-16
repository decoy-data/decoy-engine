"""Vault before output: adopt a vault that already exists, durably, or refuse (F22 5.5, D1).

Pattern: write-ahead ordering, as PostgreSQL's WAL makes the log record durable before the page
it describes. A vault found at the leaf (`vault_exists`) may have a directory fsync that failed
or never ran, so it is never trusted as found: `OutputDir.adopt_file` fsyncs the leaf and then
its whole chain, and only then are its rows compared with this writer's. Equal rows give an
adopted `VaultCommit`; anything else is refused with a fixed code and no text of the vault.
Contract: ``docs/publication.md``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, TextIO

from decoy_engine import reasons, vault
from decoy_engine.fileaccess import FileAccessUnavailable, LeafTooLarge
from decoy_engine.vault import VaultCommit, VaultError, VaultWriter

if TYPE_CHECKING:
    import os
    from collections.abc import Callable

    from decoy_engine.fileaccess import OutputDir

__all__ = ["BytesHandle", "VaultConflict", "adopt_vault", "same_rows"]

_SLACK_BYTES = 64 * 1024  # a leaf this much over twice our own size cannot hold the same rows


@dataclass(frozen=True)
class VaultConflict:
    """`adopt_vault`'s refusal: the vault found is not this writer's. A value of its own, so it
    is never mistaken for `adopt_file`'s `None` (an absent leaf)."""


class BytesHandle:
    """A read-only in-memory `FileHandle` over a vault's bytes. Its `display` is constant because
    `load_vault` puts it in messages and a path or name must never ride along."""

    strict = True
    display = "<vault>"

    def __init__(self, data: bytes) -> None:
        self._data = data

    def _no_descriptor(self) -> FileAccessUnavailable:
        return FileAccessUnavailable("an in-memory vault has no descriptor")

    def fileno(self) -> int:
        raise self._no_descriptor()

    def library_path(self) -> str:
        raise self._no_descriptor()

    def stat(self) -> os.stat_result:
        raise self._no_descriptor()

    def identity(self) -> str:
        return self.display

    def read_all(self, limit: int | None = None) -> bytes:
        return self._data if limit is None else self._data[:limit]

    def open_binary(self, opener: Callable[..., BinaryIO] | None = None) -> BinaryIO:
        return io.BytesIO(self._data)

    def open_text(self, encoding: str = "utf-8") -> TextIO:
        return io.TextIOWrapper(io.BytesIO(self._data), encoding=encoding)

    def close(self) -> None:
        return None

    def __enter__(self) -> BytesHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def same_rows(blob: bytes, writer: VaultWriter) -> bool:
    """Whether `blob` opens under the writer's key to exactly the writer's rows and dropped count.
    A wrong key, a bad frame or an unreadable file is a difference, never an error."""
    return writer.reads_as_own(BytesHandle(blob))


def adopt_vault(out: OutputDir, writer: VaultWriter) -> VaultCommit | VaultConflict:
    """Adopt the vault at `out` for `writer`, durably.

    The leaf and its chain are fsynced by `adopt_file` before the rows are compared, so the
    `VaultCommit` covers a leaf whose own directory fsync failed or was killed, and the leaf is
    never rewritten. Returns a `VaultConflict` (never `None`, which `adopt_file` uses for an absent
    leaf) for a conflict: other rows, another key's data, or more than this vault could hold. The
    caller refuses with `publication_vault_conflict`, a `decoy` code that cannot ride a `VaultError`. Raises `VaultError` with
    ``vault_commit_failed`` when the leaf cannot be read or made durable."""
    own, entries = writer.serialize()
    blob = None
    failed = too_big = False
    try:
        blob = out.adopt_file(limit=2 * len(own) + _SLACK_BYTES)
    except LeafTooLarge:
        too_big = True
    except OSError:
        failed = True
    if failed or (blob is None and not too_big):  # absent after `vault_exists`: deleted out of band
        raise VaultError(
            code=reasons.runtime.VAULT_COMMIT_FAILED,
            message=reasons.get("runtime", reasons.runtime.VAULT_COMMIT_FAILED).summary,
        )
    if blob is None or not same_rows(blob, writer):
        return VaultConflict()
    return vault.issue_commit(blob, entries, adopted=True)
