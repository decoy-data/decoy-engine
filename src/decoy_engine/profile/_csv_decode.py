"""Decoder-failure translation for CSV reads: a damaged compressed or non-UTF-8 source is one
coded, value-free refusal, never the decoder's own text, which can quote the bytes it choked on.

`read_csv_source` applies it, so a direct read and the lazy backend refuse the same way.
"""

from __future__ import annotations

import lzma
import sys
import tarfile
import zipfile
import zlib
from typing import TYPE_CHECKING, TypeVar

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pandas as pd

_T = TypeVar("_T")

# What a decoder raises on bad bytes: invalid UTF-8, or a damaged or truncated gzip, bzip2, xz, zip
# or tar stream. Each one's text can quote the bytes. An `OSError` with no errno is a decoder's
# (`BadGzipFile`, bzip2's "Invalid data stream"); one with an errno is the disk (full, no memory,
# missing file) and keeps its own class.
_DECODER_ERRORS = (
    UnicodeDecodeError,
    EOFError,
    zlib.error,
    lzma.LZMAError,
    zipfile.BadZipFile,
    tarfile.TarError,
)


def _is_decoder_failure(exc: Exception) -> bool:
    if isinstance(exc, _DECODER_ERRORS) or (isinstance(exc, OSError) and exc.errno is None):
        return True
    # zstd is an optional backend: pandas can only have raised its error if it imported it.
    backend = sys.modules.get("zstandard")
    zstd_error = getattr(backend, "ZstdError", None)
    return isinstance(zstd_error, type) and isinstance(exc, zstd_error)


def _decode_refusal(table: str) -> ExecutionError:
    """The one value-free refusal for a source that cannot be decoded. Build and raise it after
    the `except` that caught the decoder error closes, so nothing is chained."""
    return ExecutionError(
        code=reasons.runtime.CHUNKED_PASSTHROUGH_VALUE_UNREPRESENTABLE,
        message=f"the source of table {table!r} could not be decoded.",
    )


def decoded(table: str, call: Callable[[], _T]) -> _T:
    """`call()`, with a decoder failure at the call replaced by the coded refusal."""
    try:
        return call()
    except Exception as exc:
        if not _is_decoder_failure(exc):
            raise
    raise _decode_refusal(table)


def translating(table: str, chunks: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
    """`chunks`, with a decoder failure on any step replaced by the coded refusal. Closes
    `chunks` on every exit."""
    failed = False
    try:
        yield from chunks
    except Exception as exc:
        if not _is_decoder_failure(exc):
            raise
        failed = True
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    if failed:
        raise _decode_refusal(table)
