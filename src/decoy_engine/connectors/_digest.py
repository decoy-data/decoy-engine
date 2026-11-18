"""The one place a connector computes a content digest.

``DigestingChunks`` hashes a chunk stream as a sink consumes it; ``sha256_hex`` covers small
payloads. Nothing else under ``connectors/`` calls ``hashlib`` (a sentry holds that). The hasher
is a local name bound once in ``__iter__``, so the outbound sentry can tell the ``update`` call
from a GCS ``Blob.update`` by construction, not by a baseline row.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator


class DigestingChunks:
    """Wrap a chunk iterable; once it is exhausted, ``hexdigest()`` and ``count`` are set."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = chunks
        self._hex: str | None = None
        self.count = 0

    def __iter__(self) -> Iterator[bytes]:
        h = hashlib.sha256()
        count = 0
        for chunk in self._chunks:
            h.update(chunk)
            count += len(chunk)
            yield chunk
        self._hex = h.hexdigest()
        self.count = count

    def hexdigest(self) -> str:
        """The lowercase SHA-256 hex of every chunk yielded; only valid after exhaustion."""
        if self._hex is None:
            raise ValueError("digest read before the chunks were exhausted")
        return self._hex


def sha256_hex(data: bytes) -> str:
    """Lowercase SHA-256 hex of a small payload."""
    return hashlib.sha256(data).hexdigest()
