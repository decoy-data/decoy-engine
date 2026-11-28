"""Decoder-failure translation for CSV reads: a damaged compressed or non-UTF-8 source is one
coded, value-free refusal, never the decoder's own text, which can quote the bytes it choked on.

`_read_csv_rows` applies it at the one file-read boundary, so the resident reader, a direct read
and the lazy backend refuse the same way. `is_decoder_failure` is also handed to the file-access
adapter as its `passthrough`, so a strict policy cannot replace the decoder's type before it is seen.
The codec read from a declared file name lives here too.
"""

from __future__ import annotations

import lzma
import os
import sys
import tarfile
import zipfile
import zlib
from typing import TYPE_CHECKING, TypeVar

import pandas as pd
from pandas.io.common import infer_compression

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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


def is_decoder_failure(exc: Exception) -> bool:
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
        if not is_decoder_failure(exc):
            raise
    raise _decode_refusal(table)


def refusing(
    table: str, call: Callable[[], pd.DataFrame | Iterator[pd.DataFrame]]
) -> pd.DataFrame | Iterator[pd.DataFrame]:
    """`call()` (one frame or an iterator of chunks) with a decoder failure at the call or on any
    chunk step replaced by the coded refusal."""
    result = decoded(table, call)
    return result if isinstance(result, pd.DataFrame) else translating(table, result)


def translating(table: str, chunks: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
    """`chunks`, with a decoder failure on any step replaced by the coded refusal. Closes
    `chunks` on every exit."""
    failed = False
    try:
        yield from chunks
    except Exception as exc:
        if not is_decoder_failure(exc):
            raise
        failed = True
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    if failed:
        raise _decode_refusal(table)


def csv_compression(path: str | os.PathLike[str]) -> str | None:
    """The one place the codec is read from a declared file name (pandas' own rule)."""
    return infer_compression(os.fspath(path), "infer")


def csv_is_compressed(path: str | os.PathLike[str]) -> bool:
    """What pandas infers from the name of `path` (`compression="infer"`): True when its
    suffix names a compression format.

    Taken from pandas' own inference, so a pandas upgrade changes the answer with it. It looks at
    the name only and opens nothing. It does not decide how a read decompresses: `read_csv_source`
    takes the codec from the declared name and passes it on, so a rooted file policy (which hands
    pandas a descriptor path with no suffix) still reads a compressed file."""
    return csv_compression(path) is not None
