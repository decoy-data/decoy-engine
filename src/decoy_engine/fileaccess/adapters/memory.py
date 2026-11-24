"""`FileHandle`s over bytes the engine holds or streams itself, for the pandas and Arrow adapters.

A pinned artifact (a lookup file) is read once through the policy and kept in the plan. Parsing
it later must not open the path again, so the adapters get a `MemoryHandle` instead: it stands
for those bytes and names only a config position. A cloud object is read through a
`StreamHandle` over the engine's own ranged stream. Both handles are strict whatever policy is
in force, so a library failure becomes the one value-free `FileAccessReadError`; a connector
error raised by the stream itself passes through with its kind (see `guarded`).
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from typing import Any, BinaryIO, TextIO


class MemoryHandle:
    """In-memory stand-in for an open, authorized file. Nothing here touches a file system."""

    strict = True

    def __init__(self, data: bytes, display: str) -> None:
        self._data = data
        self.display = display

    def fileno(self) -> int:
        raise io.UnsupportedOperation("a memory handle has no descriptor")

    def library_path(self) -> Any:
        """A fresh buffer per call: pandas and pyarrow accept one where they accept a path."""
        return io.BytesIO(self._data)

    def stat(self) -> os.stat_result:
        return os.stat_result((0o100444, 0, 0, 1, 0, 0, len(self._data), 0, 0, 0))

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

    def __enter__(self) -> MemoryHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class StreamHandle:
    """A `FileHandle` over a readable byte stream the engine opened itself (a cloud object).

    Strict, so a parser failure on the object's bytes leaves without its text. The stream is
    handed to the library once; nothing here touches a file system.
    """

    strict = True

    def __init__(self, stream: BinaryIO, display: str) -> None:
        self._stream = stream
        self.display = display

    def fileno(self) -> int:
        raise io.UnsupportedOperation("a stream handle has no descriptor")

    def library_path(self) -> Any:
        return self._stream

    def stat(self) -> os.stat_result:
        raise io.UnsupportedOperation("a stream handle has no size")

    def identity(self) -> str:
        return self.display

    def read_all(self, limit: int | None = None) -> bytes:
        return self._stream.read() if limit is None else self._stream.read(limit)

    def open_binary(self, opener: Callable[..., BinaryIO] | None = None) -> BinaryIO:
        return self._stream

    def open_text(self, encoding: str = "utf-8") -> TextIO:
        return io.TextIOWrapper(self._stream, encoding=encoding)

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> StreamHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
