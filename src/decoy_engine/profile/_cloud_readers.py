"""Bounded S3 / GCS `ProfileSource` readers.

Pattern: HTTP ranged reads + Parquet footer metadata (Apache Arrow / AWS S3
GetObject Range / GCS objects.get Range; all vendor-standard). Every read is a
byte range pinned to the version seen with the size (S3 `IfMatch` on the HEAD
ETag, GCS `ifGenerationMatch`), so a Parquet footer + one Arrow batch, a CSV's
first `<= sample_rows` rows, or a whole frame streamed in pieces never asks for
the whole object in one response and never mixes two versions of it -- the
cloud analogue of the local footer/`nrows` readers in `_readers.py`.

Companion to `profile/_readers.py`. The engine never sees raw secrets:
`credentials_ref` is opaque and the SDKs walk their default credential chain.
Error bodies are wrapped so the raw SDK exception string (which can carry
endpoint URLs / request metadata) never reaches job logs, preserving the QA-7
F2 hygiene the eager loaders established.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine._lexeme import LEXEME_KEY, pandas_lexeme_kwargs
from decoy_engine.connectors import _clients
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.fileaccess.adapters import pandas as pandas_adapter
from decoy_engine.fileaccess.adapters.memory import StreamHandle
from decoy_engine.profile._readers import (
    PROOF_READ_ERRORS,
    ProfileSource,
    RowCount,
    estimate_csv_rows,
    head_frame_from_batches,
)
from decoy_engine.reasons import connector as _connector_reasons
from decoy_engine.sdk import PermanentError

# One ranged read big enough to cover a CSV header + a bounded sample on a
# typical object, while still being a tiny fraction of a large file. read_csv
# drops a truncated trailing line, so an over-read never corrupts the sample.
_CSV_SAMPLE_WINDOW_BYTES = 1 << 20  # 1 MiB
# Rows to parse from the window when only the schema (column set + dtypes) is
# needed; bounded so schema inference never depends on the full window.
_CSV_ESTIMATE_ROWS = 1_000
# A sample stops here: one huge quoted row must not pull a whole object into memory.
_CSV_SAMPLE_MAX_BYTES = 64 << 20
# The largest single ranged response; a Parquet column chunk over this is read in pieces.
_RANGE_PIECE_BYTES = 8 << 20
# CSV `to_frame` streams the object to pandas in pieces this size.
_CSV_STREAM_PIECE_BYTES = 1 << 20

Fetch = Callable[[int, int], bytes]


class SampleWindowExceeded(PermanentError):  # noqa: N818 - coded condition
    """The sample rows were not within `_CSV_SAMPLE_MAX_BYTES` of a larger object."""

    code = _connector_reasons.SAMPLE_WINDOW_EXCEEDED

    def __init__(self) -> None:
        super().__init__(
            "The CSV sample rows were not found within the 64 MiB sample read limit; "
            "profile a local copy of the object instead.",
            kind="rejected",
        )


def _exact(fetch: Fetch, start: int, end_inclusive: int, provider: str) -> bytes:
    """One ranged fetch; fewer bytes than asked means the object changed under the read."""
    data = fetch(start, end_inclusive)
    if len(data) != end_inclusive - start + 1:
        raise _clients.source_changed(provider)
    return data


def _fetch_span(fetch: Fetch, start: int, end_inclusive: int, provider: str) -> bytes:
    """`start..end_inclusive` as requests of at most `_RANGE_PIECE_BYTES` each."""
    out = bytearray()
    for lo in range(start, end_inclusive + 1, _RANGE_PIECE_BYTES):
        out += _exact(fetch, lo, min(lo + _RANGE_PIECE_BYTES, end_inclusive + 1) - 1, provider)
    return bytes(out)


# ---------------------------------------------------------------------
# Seekable ranged file: lets pyarrow read a Parquet footer + batches from a
# remote object via byte-range fetches instead of a whole-object download.
# ---------------------------------------------------------------------


class _RangeFileReader(io.RawIOBase):
    """A read-only seekable file backed by a `fetch(start, end_inclusive)`.

    pyarrow needs random access to read a Parquet footer (stored at the end of
    the file) and then decode selected row groups; this adapter serves those
    reads from byte-range requests so only the bytes pyarrow asks for cross the
    wire. `fetch` returns the inclusive `[start, end]` byte range; one buffer is
    filled with requests of at most `piece` bytes, each checked for a short read.
    """

    def __init__(
        self, size: int, fetch: Fetch, provider: str, piece: int = _RANGE_PIECE_BYTES
    ) -> None:
        super().__init__()
        self._size = size
        self._fetch = fetch
        self._provider = provider
        self._piece = piece
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self._size + offset
        else:  # pragma: no cover -- io module only defines the three above
            raise ValueError(f"invalid whence {whence!r}")
        return self._pos

    def readinto(self, buffer: Any) -> int:
        want = len(buffer)
        if want == 0 or self._pos >= self._size:
            return 0
        view = memoryview(buffer).cast("B")
        stop = min(self._pos + want, self._size)
        done = 0
        while self._pos < stop:
            end = min(self._pos + self._piece, stop)
            data = _exact(self._fetch, self._pos, end - 1, self._provider)
            view[done : done + len(data)] = data
            done += len(data)
            self._pos = end
        return done


def _parquet(size: int, fetch: Fetch, provider: str) -> tuple[StreamHandle, pq.ParquetFile]:
    stream = pa.PythonFile(_RangeFileReader(size, fetch, provider), mode="r")
    handle = StreamHandle(stream, provider)
    # pre_buffer=False: one request per column chunk, never a coalesced row-group read.
    return handle, arrow_adapter.parquet_file(handle, pre_buffer=False)


def _read_parquet_row_count(size: int, fetch: Fetch, provider: str) -> RowCount:
    return RowCount(_parquet(size, fetch, provider)[1].metadata.num_rows, exact=True)


def _read_parquet_schema(size: int, fetch: Fetch, provider: str) -> pa.Schema:
    return _parquet(size, fetch, provider)[1].schema_arrow


def _read_parquet_sample(size: int, fetch: Fetch, provider: str, sample_rows: int) -> pd.DataFrame:
    handle, pf = _parquet(size, fetch, provider)
    batches = arrow_adapter.iter_batches(handle, pf, batch_size=sample_rows)
    return head_frame_from_batches(batches, sample_rows, pf.schema_arrow)


def _read_parquet_frame(size: int, fetch: Fetch, provider: str) -> pd.DataFrame:
    """The whole object as `pd.read_parquet` would give it, read one column chunk at a time.

    The schema carries the pandas metadata (index, categoricals, timezones) and keeps a file
    with no row groups valid, where `iter_batches` yields nothing.
    """
    handle, pf = _parquet(size, fetch, provider)
    batches = arrow_adapter.iter_batches(handle, pf)
    return pa.Table.from_batches(batches, schema=pf.schema_arrow).to_pandas()


def _read_csv_frame(size: int, fetch: Fetch, provider: str, lexeme_columns: Any) -> pd.DataFrame:
    raw = _RangeFileReader(size, fetch, provider, piece=_CSV_STREAM_PIECE_BYTES)
    with StreamHandle(io.BufferedReader(raw, _CSV_STREAM_PIECE_BYTES), provider) as handle:
        return pandas_adapter.read_csv(handle, **pandas_lexeme_kwargs(lexeme_columns))


def _csv_row_count_from_window(size: int, window: bytes) -> RowCount:
    """Estimate CSV rows from the object size and a leading byte window.

    Splits the window into header + data lines to measure mean row width, then
    scales to the full object size. Mirrors the local CSV estimate so cloud and
    local CSV counts are flagged and computed the same way.
    """
    lines = window.split(b"\n")
    if not lines:
        return RowCount(0, exact=False)
    header_bytes = len(lines[0]) + 1  # + the split-stripped newline
    # Drop the header and a possibly-truncated final fragment; keep whole lines.
    data_lines = [len(line) + 1 for line in lines[1:-1] if line]
    return estimate_csv_rows(size, header_bytes, data_lines)


def _csv_sample_from_window(
    window: bytes, size: int, sample_rows: int, lexeme_columns: Any = None
) -> pd.DataFrame:
    """Parse up to `sample_rows` rows from a leading CSV byte window.

    If the window is a prefix of a larger object it may end mid-row; the last
    fragment is dropped before parsing so `read_csv` never sees a torn line.
    """
    if len(window) < size:
        window = window.rsplit(b"\n", 1)[0] + b"\n"
    return pd.read_csv(
        io.BytesIO(window), nrows=sample_rows, **pandas_lexeme_kwargs(lexeme_columns)
    )


def _csv_rows_from_ranges(
    size: int,
    fetch: Fetch,
    n: int,
    provider: str,
    lexeme_columns: Any = None,
) -> pd.DataFrame:
    """The first `n` data rows of a CSV object, fewer only when the object has fewer.

    Fetches the first window, then ranged windows of doubling size appended to the buffer
    (a byte is never fetched twice), until the buffer cut at its last newline parses to
    `n + 1` rows or the buffer is the whole object. One row past `n` proves the `n`-th row
    was complete. A `ParserError` on a prefix may be a quoted field cut open at the last
    newline, so it fetches again; on the whole object it is raised as `to_frame` would.
    A ranged response shorter than asked means the object shrank or the store misbehaved;
    it raises `source_changed` rather than looping or returning a short frame. The bytes
    fetched stop at `_CSV_SAMPLE_MAX_BYTES`; rows not found by then on a larger object raise
    `SampleWindowExceeded`.
    """
    buffer = b""
    window = _CSV_SAMPLE_WINDOW_BYTES
    while True:
        end = min(len(buffer) + window, size, _CSV_SAMPLE_MAX_BYTES)
        if end > len(buffer):
            buffer += _fetch_span(fetch, len(buffer), end - 1, provider)
        whole = len(buffer) >= size
        try:
            frame = _csv_sample_from_window(buffer, size, n + 1, lexeme_columns)
        except PROOF_READ_ERRORS:
            if whole:
                # Row `n + 1` is on the object and does not parse: a row exists past `n`,
                # which is all the proof asks. The `n` rows themselves must still parse,
                # and an error there is raised as `to_frame` would.
                return _csv_sample_from_window(buffer, size, n, lexeme_columns)
        else:
            if len(frame) <= n:
                if whole:
                    return frame
            else:
                # Row `n + 1` only proved row `n` complete; the sample is parsed again from
                # `n` rows so that row cannot change a column's inferred type.
                return _csv_sample_from_window(buffer, size, n, lexeme_columns)
        if not whole and len(buffer) >= _CSV_SAMPLE_MAX_BYTES:
            raise SampleWindowExceeded()
        window *= 2


# ---------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------


def _s3_for(descriptor: dict[str, Any]) -> Any:
    """A per-call S3 client from the shared factory (no shared global; QA Q1/Q10).

    Region and `endpoint_url` (MinIO/R2/moto) come from the descriptor; credentials come
    from the SDK default chain.
    """
    region = descriptor.get("region")
    endpoint_url = descriptor.get("endpoint_url")
    return _clients.s3_client(
        region=region if isinstance(region, str) and region else None,
        endpoint_url=endpoint_url if isinstance(endpoint_url, str) and endpoint_url else None,
        access_key_id=None,
        secret_access_key=None,
        single_request=False,
    )


def _s3_bind(descriptor: dict[str, Any]) -> tuple[int, Fetch]:
    """The object size and a `fetch` pinned to the ETag the same HEAD returned."""
    bucket = _require_str(descriptor, "bucket", "s3")
    key = _require_str(descriptor, "key", "s3")
    client = _s3_for(descriptor)
    head = _clients.s3_call(client.head_object, Bucket=bucket, Key=key)
    etag = head.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise _clients.source_changed("S3")

    def fetch(start: int, end_inclusive: int) -> bytes:
        return _s3_range(client, bucket, key, etag, start, end_inclusive)

    return int(head["ContentLength"]), fetch


def _s3_range(
    client: Any, bucket: str, key: str, etag: str, start: int, end_inclusive: int
) -> bytes:
    try:
        response = _clients.s3_call(
            client.get_object,
            Bucket=bucket,
            Key=key,
            Range=f"bytes={start}-{end_inclusive}",
            IfMatch=etag,
        )
        # Q17: draining .read() does not release the socket; close the body so the
        # connection returns to the pool (multi-range parquet reads reuse it).
        with response["Body"] as stream:
            return bytes(_clients.s3_call(stream.read, end_inclusive - start + 1))
    except PermanentError as exc:
        if exc.kind != "precondition_failed":
            raise
    # IfMatch failed: the object is a new version. Raised here so nothing chains.
    raise _clients.source_changed("S3")


class S3ParquetSource:
    """Bounded `ProfileSource` for an S3 Parquet object (footer + column chunk reads)."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor
        _require_str(descriptor, "bucket", "s3")
        _require_str(descriptor, "key", "s3")

    def row_count(self) -> RowCount:
        return _read_parquet_row_count(*_s3_bind(self._descriptor), "S3")

    def schema(self) -> pa.Schema:
        return _read_parquet_schema(*_s3_bind(self._descriptor), "S3")

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        return _read_parquet_sample(*_s3_bind(self._descriptor), "S3", sample_rows)

    def to_frame(self) -> pd.DataFrame:
        return _read_parquet_frame(*_s3_bind(self._descriptor), "S3")


class S3CsvSource:
    """`ProfileSource` for an S3 CSV object.

    The row estimate and schema read one leading window. `sample_frame` reads ranged windows
    until it holds the rows asked for or the object ends, and refuses past 64 MiB. `to_frame`
    streams the object to pandas in pinned 1 MiB ranges."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor
        _require_str(descriptor, "bucket", "s3")
        _require_str(descriptor, "key", "s3")

    def _size_and_window(self) -> tuple[int, bytes]:
        size, fetch = _s3_bind(self._descriptor)
        end = min(_CSV_SAMPLE_WINDOW_BYTES, size) - 1
        return size, _exact(fetch, 0, end, "S3") if size > 0 else b""

    def row_count(self) -> RowCount:
        size, window = self._size_and_window()
        return _csv_row_count_from_window(size, window)

    def schema(self) -> pa.Schema:
        size, window = self._size_and_window()
        # Reuse the sample parser so a window truncated mid-row is trimmed to
        # whole lines before pandas infers the schema.
        head = _csv_sample_from_window(
            window, size, _CSV_ESTIMATE_ROWS, self._descriptor.get(LEXEME_KEY)
        )
        return pa.Table.from_pandas(head, preserve_index=False).schema

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        size, fetch = _s3_bind(self._descriptor)
        lexemes = self._descriptor.get(LEXEME_KEY)
        return _csv_rows_from_ranges(size, fetch, sample_rows, "S3", lexemes)

    def to_frame(self) -> pd.DataFrame:
        size, fetch = _s3_bind(self._descriptor)
        return _read_csv_frame(size, fetch, "S3", self._descriptor.get(LEXEME_KEY))


def build_s3_profile_source(descriptor: dict[str, Any]) -> ProfileSource:
    fmt = descriptor.get("format")
    if fmt == "csv":
        return S3CsvSource(descriptor)
    if fmt == "parquet":
        return S3ParquetSource(descriptor)
    raise NotImplementedError(
        f"profile_source: unsupported s3 format {fmt!r}. V1 supports csv | parquet only."
    )


# ---------------------------------------------------------------------
# GCS
# ---------------------------------------------------------------------


def _gcs_blob(descriptor: dict[str, Any], client: Any) -> Any:
    bucket_name = _require_str(descriptor, "bucket", "gcs")
    object_name = _require_str(descriptor, "object", "gcs")
    return client.bucket(bucket_name).blob(object_name)


def _gcs_version(blob: Any) -> tuple[int, int]:
    """Size and generation from one metadata view; reloaded unless both are already known."""
    if blob.size is None or blob.generation is None:
        _clients.gcs_reload(blob)
    if blob.size is None or blob.generation is None:
        raise _clients.source_changed("GCS")
    return int(blob.size), int(blob.generation)


def _with_gcs_reads(descriptor: dict[str, Any], consume: Callable[[int, Fetch], Any]) -> Any:
    """Run `consume(size, fetch)` inside one GCS client block, every read on one generation.

    Q18: storage.Client owns an HTTP transport; the context manager closes it once every
    metadata and ranged read of this operation has completed.
    """
    with _clients.gcs_client() as client:
        blob = _gcs_blob(descriptor, client)
        size, generation = _gcs_version(blob)

        def fetch(start: int, end_inclusive: int) -> bytes:
            return _clients.gcs_download(
                blob, start=start, end=end_inclusive, size=size, generation=generation
            )

        return consume(size, fetch)


class GcsParquetSource:
    """Bounded `ProfileSource` for a GCS Parquet object (footer + column chunk reads)."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor

    def row_count(self) -> RowCount:
        return _with_gcs_reads(self._descriptor, lambda s, f: _read_parquet_row_count(s, f, "GCS"))

    def schema(self) -> pa.Schema:
        return _with_gcs_reads(self._descriptor, lambda s, f: _read_parquet_schema(s, f, "GCS"))

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        return _with_gcs_reads(
            self._descriptor, lambda s, f: _read_parquet_sample(s, f, "GCS", sample_rows)
        )

    def to_frame(self) -> pd.DataFrame:
        return _with_gcs_reads(self._descriptor, lambda s, f: _read_parquet_frame(s, f, "GCS"))


class GcsCsvSource:
    """`ProfileSource` for a GCS CSV object.

    The row estimate and schema read one leading window. `sample_frame` reads ranged windows
    until it holds the rows asked for or the object ends, and refuses past 64 MiB. `to_frame`
    streams the object to pandas in pinned 1 MiB ranges."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor

    def _size_and_window(self) -> tuple[int, bytes]:
        def window(size: int, fetch: Fetch) -> tuple[int, bytes]:
            end = min(_CSV_SAMPLE_WINDOW_BYTES, size) - 1
            return size, _exact(fetch, 0, end, "GCS") if size > 0 else b""

        result: tuple[int, bytes] = _with_gcs_reads(self._descriptor, window)
        return result

    def row_count(self) -> RowCount:
        size, window = self._size_and_window()
        return _csv_row_count_from_window(size, window)

    def schema(self) -> pa.Schema:
        size, window = self._size_and_window()
        # Reuse the sample parser so a window truncated mid-row is trimmed to
        # whole lines before pandas infers the schema.
        head = _csv_sample_from_window(
            window, size, _CSV_ESTIMATE_ROWS, self._descriptor.get(LEXEME_KEY)
        )
        return pa.Table.from_pandas(head, preserve_index=False).schema

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        return _with_gcs_reads(
            self._descriptor,
            lambda size, fetch: _csv_rows_from_ranges(
                size, fetch, sample_rows, "GCS", self._descriptor.get(LEXEME_KEY)
            ),
        )

    def to_frame(self) -> pd.DataFrame:
        lexemes = self._descriptor.get(LEXEME_KEY)
        return _with_gcs_reads(self._descriptor, lambda s, f: _read_csv_frame(s, f, "GCS", lexemes))


def build_gcs_profile_source(descriptor: dict[str, Any]) -> ProfileSource:
    fmt = descriptor.get("format")
    if fmt == "csv":
        return GcsCsvSource(descriptor)
    if fmt == "parquet":
        return GcsParquetSource(descriptor)
    raise NotImplementedError(
        f"profile_source: unsupported gcs format {fmt!r}. V1 supports csv | parquet only."
    )


def _require_str(descriptor: dict[str, Any], field: str, kind: str) -> str:
    value = descriptor.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"profile_source: {kind} source missing {field}")
    return value


__all__ = [
    "GcsCsvSource",
    "GcsParquetSource",
    "S3CsvSource",
    "S3ParquetSource",
    "SampleWindowExceeded",
    "build_gcs_profile_source",
    "build_s3_profile_source",
]
