"""Bounded S3 / GCS `ProfileSource` readers.

Pattern: HTTP ranged reads + Parquet footer metadata (Apache Arrow / AWS S3
GetObject Range / GCS objects.get Range; all vendor-standard). See: the S3
`Range` request header and GCS `download_as_bytes(start, end)` fetch only the
requested byte window, so a Parquet footer + one Arrow batch, or a CSV's first
`<= sample_rows` rows, can be read without transferring the whole object -- the
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
from decoy_engine.internal.pandas_compat import table_to_pandas
from decoy_engine.io import check_source_dates, check_source_schema
from decoy_engine.profile._readers import (
    PROOF_READ_ERRORS,
    ProfileSource,
    RowCount,
    estimate_csv_rows,
    head_frame_from_batches,
)

# One ranged read big enough to cover a CSV header + a bounded sample on a
# typical object, while still being a tiny fraction of a large file. read_csv
# drops a truncated trailing line, so an over-read never corrupts the sample.
_CSV_SAMPLE_WINDOW_BYTES = 1 << 20  # 1 MiB
# Rows to parse from the window when only the schema (column set + dtypes) is
# needed; bounded so schema inference never depends on the full window.
_CSV_ESTIMATE_ROWS = 1_000


# ---------------------------------------------------------------------
# Seekable ranged file: lets pyarrow read a Parquet footer + batches from a
# remote object via byte-range fetches instead of a whole-object download.
# ---------------------------------------------------------------------


class _RangeFileReader(io.RawIOBase):
    """A read-only seekable file backed by a `fetch(start, end_inclusive)`.

    pyarrow needs random access to read a Parquet footer (stored at the end of
    the file) and then decode selected row groups; this adapter serves those
    reads from byte-range requests so only the bytes pyarrow asks for cross the
    wire. `fetch` returns the inclusive `[start, end]` byte range.
    """

    def __init__(self, size: int, fetch: Callable[[int, int], bytes]) -> None:
        super().__init__()
        self._size = size
        self._fetch = fetch
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
        end_inclusive = min(self._pos + want, self._size) - 1
        data = self._fetch(self._pos, end_inclusive)
        n = len(data)
        buffer[:n] = data
        self._pos += n
        return n


def _read_parquet_row_count(size: int, fetch: Callable[[int, int], bytes]) -> RowCount:
    reader = _RangeFileReader(size, fetch)
    return RowCount(pq.ParquetFile(pa.PythonFile(reader, mode="r")).metadata.num_rows, exact=True)


def _read_parquet_schema(size: int, fetch: Callable[[int, int], bytes]) -> pa.Schema:
    reader = _RangeFileReader(size, fetch)
    return pq.ParquetFile(pa.PythonFile(reader, mode="r")).schema_arrow


def _read_parquet_sample(
    size: int, fetch: Callable[[int, int], bytes], sample_rows: int, table: str
) -> pd.DataFrame:
    reader = _RangeFileReader(size, fetch)
    parquet_file = pq.ParquetFile(pa.PythonFile(reader, mode="r"))
    return head_frame_from_batches(
        parquet_file.iter_batches(batch_size=sample_rows),
        sample_rows,
        parquet_file.schema_arrow,
        table=table,
    )


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
    fetch: Callable[[int, int], bytes],
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
    it raises `source_changed` rather than looping or returning a short frame.
    """
    buffer = b""
    window = _CSV_SAMPLE_WINDOW_BYTES
    while True:
        end = min(len(buffer) + window, size)
        if end > len(buffer):
            chunk = fetch(len(buffer), end - 1)
            if len(chunk) != end - len(buffer):
                raise _clients.source_changed(provider)
            buffer += chunk
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


def _s3_size(client: Any, bucket: str, key: str) -> int:
    head = _clients.s3_call(client.head_object, Bucket=bucket, Key=key)
    return int(head["ContentLength"])


def _s3_range(client: Any, bucket: str, key: str, start: int, end_inclusive: int) -> bytes:
    response = _clients.s3_call(
        client.get_object, Bucket=bucket, Key=key, Range=f"bytes={start}-{end_inclusive}"
    )
    # Q17: draining .read() does not release the socket; close the body so the
    # connection returns to the pool (multi-range parquet reads reuse it).
    with response["Body"] as stream:
        return bytes(_clients.s3_call(stream.read))


def _s3_full(client: Any, bucket: str, key: str) -> bytes:
    response = _clients.s3_call(client.get_object, Bucket=bucket, Key=key)
    with response["Body"] as stream:
        return bytes(_clients.s3_call(stream.read))


class S3ParquetSource:
    """Bounded `ProfileSource` for an S3 Parquet object (footer + batch reads)."""

    def __init__(self, descriptor: dict[str, Any], table: str = "source") -> None:
        self._descriptor = descriptor
        self._table = table
        self._bucket = _require_str(descriptor, "bucket", "s3")
        self._key = _require_str(descriptor, "key", "s3")

    def _bind(self) -> tuple[Any, int, Callable[[int, int], bytes]]:
        client = _s3_for(self._descriptor)
        size = _s3_size(client, self._bucket, self._key)

        def fetch(start: int, end_inclusive: int) -> bytes:
            return _s3_range(client, self._bucket, self._key, start, end_inclusive)

        return client, size, fetch

    def row_count(self) -> RowCount:
        _, size, fetch = self._bind()
        return _read_parquet_row_count(size, fetch)

    def schema(self) -> pa.Schema:
        _, size, fetch = self._bind()
        return _read_parquet_schema(size, fetch)

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        _, size, fetch = self._bind()
        return _read_parquet_sample(size, fetch, sample_rows, self._table)

    def to_frame(self) -> pd.DataFrame:
        client = _s3_for(self._descriptor)
        return _checked_frame(_s3_full(client, self._bucket, self._key), self._table)


def _checked_frame(data: bytes, table: str) -> pd.DataFrame:
    """A whole Parquet object as a frame, after its dates passed the calendar check."""
    check_source_schema(  # the footer only: no column decodes before the type gate
        _read_parquet_schema(len(data), lambda start, end: data[start : end + 1]), table=table
    )
    return table_to_pandas(check_source_dates(pq.read_table(io.BytesIO(data)), table=table))


class S3CsvSource:
    """`ProfileSource` for an S3 CSV object.

    The row estimate and schema read one leading window. `sample_frame` reads ranged windows
    until it holds the rows asked for or the object ends, so an ordinary sample is bounded but a
    no-newline object or one giant quoted row can need the whole object."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor
        self._bucket = _require_str(descriptor, "bucket", "s3")
        self._key = _require_str(descriptor, "key", "s3")

    def _size_and_window(self) -> tuple[int, bytes]:
        client = _s3_for(self._descriptor)
        size = _s3_size(client, self._bucket, self._key)
        end = min(_CSV_SAMPLE_WINDOW_BYTES, size) - 1
        window = _s3_range(client, self._bucket, self._key, 0, end) if size > 0 else b""
        return size, window

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
        client = _s3_for(self._descriptor)
        size = _s3_size(client, self._bucket, self._key)
        return _csv_rows_from_ranges(
            size,
            lambda start, end: _s3_range(client, self._bucket, self._key, start, end),
            sample_rows,
            "S3",
            self._descriptor.get(LEXEME_KEY),
        )

    def to_frame(self) -> pd.DataFrame:
        client = _s3_for(self._descriptor)
        return pd.read_csv(
            io.BytesIO(_s3_full(client, self._bucket, self._key)),
            **pandas_lexeme_kwargs(self._descriptor.get(LEXEME_KEY)),
        )


def build_s3_profile_source(descriptor: dict[str, Any], table: str = "source") -> ProfileSource:
    fmt = descriptor.get("format")
    if fmt == "csv":
        return S3CsvSource(descriptor)
    if fmt == "parquet":
        return S3ParquetSource(descriptor, table)
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


def _gcs_size(blob: Any) -> int:
    if blob.size is None:
        # size is populated by a metadata fetch, not an object download.
        _clients.gcs_reload(blob)
    return int(blob.size)


def _with_gcs_reads(
    descriptor: dict[str, Any], consume: Callable[[int, Callable[[int, int], bytes]], Any]
) -> Any:
    """Run `consume(size, fetch)` inside one GCS client block.

    Q18: storage.Client owns an HTTP transport; the context manager closes it once every
    metadata and ranged read of this operation has completed.
    """
    with _clients.gcs_client() as client:
        blob = _gcs_blob(descriptor, client)
        size = _gcs_size(blob)

        def fetch(start: int, end_inclusive: int) -> bytes:
            return bytes(_clients.gcs_download(blob, start=start, end=end_inclusive))

        return consume(size, fetch)


class GcsParquetSource:
    """Bounded `ProfileSource` for a GCS Parquet object (footer + batch reads)."""

    def __init__(self, descriptor: dict[str, Any], table: str = "source") -> None:
        self._descriptor = descriptor
        self._table = table

    def row_count(self) -> RowCount:
        return _with_gcs_reads(self._descriptor, _read_parquet_row_count)

    def schema(self) -> pa.Schema:
        return _with_gcs_reads(self._descriptor, _read_parquet_schema)

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        return _with_gcs_reads(
            self._descriptor,
            lambda size, fetch: _read_parquet_sample(size, fetch, sample_rows, self._table),
        )

    def to_frame(self) -> pd.DataFrame:
        with _clients.gcs_client() as client:
            data = _clients.gcs_download(_gcs_blob(self._descriptor, client))
        return _checked_frame(data, self._table)


class GcsCsvSource:
    """`ProfileSource` for a GCS CSV object.

    The row estimate and schema read one leading window. `sample_frame` reads ranged windows
    until it holds the rows asked for or the object ends, so an ordinary sample is bounded but a
    no-newline object or one giant quoted row can need the whole object."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor

    def _size_and_window(self) -> tuple[int, bytes]:
        with _clients.gcs_client() as client:
            blob = _gcs_blob(self._descriptor, client)
            size = _gcs_size(blob)
            if size == 0:
                return 0, b""
            end = min(_CSV_SAMPLE_WINDOW_BYTES, size) - 1
            window = bytes(_clients.gcs_download(blob, start=0, end=end))
        return size, window

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
        with _clients.gcs_client() as client:
            data = _clients.gcs_download(_gcs_blob(self._descriptor, client))
        return pd.read_csv(
            io.BytesIO(data), **pandas_lexeme_kwargs(self._descriptor.get(LEXEME_KEY))
        )


def build_gcs_profile_source(descriptor: dict[str, Any], table: str = "source") -> ProfileSource:
    fmt = descriptor.get("format")
    if fmt == "csv":
        return GcsCsvSource(descriptor)
    if fmt == "parquet":
        return GcsParquetSource(descriptor, table)
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
    "build_gcs_profile_source",
    "build_s3_profile_source",
]
