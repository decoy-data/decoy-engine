"""`CsvLazySource`: a CSV file read as bounded batches, behind the `LazySource` surface.

Routing, the planner, the chunked input and materialization all test `isinstance(src,
LazySource)`. A CSV backend that is a subclass is admitted by those existing checks with no
CSV-only branch, and every read goes through `read_csv_source(chunksize=)`, the engine's one
CSV reader, so dialect, headerless width checks and the all-text contract stay in one place.

CSV has no footer, so the routing facts come from one bounded counting pass (one chunk in
memory at a time). The pass runs only after `preflight`, which checks the dialect and reads the
header, never a data row. The file's identity (device, inode, size, mtime) is taken around the
facts pass and around the batch read: a file replaced or edited in between is refused with
`lazy_source_changed` instead of being routed on one file and read as another.

Row groups do not exist in CSV; the facts report none, and the layout is part of the facts
comparison like any other fact.

A compressed file (gzip, bzip2, xz, zip, tar, zstd) is read the same way: pandas decompresses it
as a stream, one chunk in memory. The format is inferred once from the declared name, because a
rooted file policy hands pandas a descriptor path with no suffix. A decoder failure is the coded
refusal below, never the decoder's own text, which can quote the bytes it choked on.
"""

from __future__ import annotations

import contextlib
import lzma
import tarfile
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError
from decoy_engine._execution_error import lazy_source_changed as lazy_source_changed
from decoy_engine.config._csv_dialect import CsvDialect
from decoy_engine.profile._csv_reader import csv_compression, read_csv_source, resolve_csv_dialect
from decoy_engine.profile._lazy_identity import LazyFileIdentity, check_batch_rows
from decoy_engine.profile._readers import FooterFacts, LazySource, OpenedLazyBatches

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from decoy_engine.fileaccess import FileAccess

# Rows per chunk in the counting pass; only the counts survive each chunk.
_FACTS_CHUNK_ROWS = 65_536

_T = TypeVar("_T")

# What a decoder raises on bad bytes: invalid UTF-8, a damaged or truncated gzip, bzip2, xz, zip
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
    return isinstance(exc, _DECODER_ERRORS) or (isinstance(exc, OSError) and exc.errno is None)


def _decode_refusal(table: str) -> ExecutionError:
    """The one value-free refusal for a source that cannot be decoded. Build and raise it after
    the `except` that caught the decoder error closes, so nothing is chained."""
    return ExecutionError(
        code=reasons.runtime.CHUNKED_PASSTHROUGH_VALUE_UNREPRESENTABLE,
        message=f"the source of table {table!r} could not be decoded.",
    )


def _decoded(table: str, call: Callable[[], _T]) -> _T:
    """`call()`, with a decoder failure at the call replaced by the coded refusal."""
    try:
        return call()
    except Exception as exc:
        if not _is_decoder_failure(exc):
            raise
    raise _decode_refusal(table)


def _translating(table: str, chunks: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
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


@contextlib.contextmanager
def _closing(chunks: Iterator[pd.DataFrame]) -> Iterator[Iterator[pd.DataFrame]]:
    """Yield `chunks` and close it on any exit, so an error or an abandoned read frees the fd."""
    try:
        yield chunks
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()


def _text_schema(names: list[str]) -> pa.Schema:
    return pa.schema([pa.field(name, pa.string()) for name in names])


def _batch(frame: pd.DataFrame, schema: pa.Schema) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [pa.array(frame[name], type=pa.string(), from_pandas=True) for name in schema.names],
        schema=schema,
    )


class OpenedCsvBatches(OpenedLazyBatches):
    """The CSV counterpart of `OpenedLazyBatches`: same attributes, no Parquet handle.

    Built from facts the caller already holds, so no second counting pass runs. `close()` is
    idempotent and drops the chunk iterator, which closes the underlying file."""

    # Does not call the Parquet constructor: there is no ParquetFile to hand it.
    def __init__(
        self,
        facts: FooterFacts,
        chunks: Iterator[pd.DataFrame],
        verify: Any,
        batch_schema: pa.Schema | None = None,
    ) -> None:
        self._closed = False
        self._chunks = chunks
        # A projection changes the batches' schema, never the facts.
        self._batch_schema = batch_schema or facts.schema
        self.facts = facts
        self.batches = self._read(verify)

    def _read(self, verify: Any) -> Iterator[pa.RecordBatch]:  # type: ignore[override]
        try:
            for frame in self._chunks:
                yield _batch(frame, self._batch_schema)
            verify()
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            close = getattr(self._chunks, "close", None)
            if close is not None:
                close()


@dataclass(frozen=True)
class CsvLazySource(LazyFileIdentity, LazySource):
    """A batch-readable handle onto one on-disk CSV file, declared by `dialect`."""

    dialect: CsvDialect = field(default_factory=CsvDialect)
    table: str = field(default="source", compare=False)
    # pandas' name for the codec (`gzip`, `bz2`, ...), None for plain text, or "infer" to read it
    # from the declared name (the reader's rule, so a rooted policy still sees the suffix).
    compression: str | None = field(default="infer", compare=False)
    # Facts and the identity they were taken under, from the last `footer_facts()` call.
    _seen: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_descriptor(
        cls,
        descriptor: Mapping[str, Any],
        *,
        table: str,
        file_access: FileAccess | None = None,
        field_key: str = "source.path",
    ) -> CsvLazySource:
        """Build from a validated `format: csv` source descriptor; the dialect is resolved
        once, here, by the engine's one resolver."""
        dialect = resolve_csv_dialect(descriptor, table=table, file_access=file_access)
        return cls(
            Path(descriptor["path"]),
            access=file_access,
            field_key=field_key,
            dialect=dialect,
            table=table,
            compression=csv_compression(descriptor["path"]),
        )

    def _chunks(self, batch_rows: int, columns: list[str] | None = None) -> Iterator[pd.DataFrame]:
        chunks = _decoded(
            self.table,
            lambda: read_csv_source(
                self.path,
                self.dialect,
                table=self.table,
                dtype=str,
                chunksize=batch_rows,
                file_access=self.access,
                field_key=self.field_key,
                columns=columns,
                compression=self.compression,
            ),
        )
        return _translating(self.table, chunks)

    def preflight(self) -> pa.Schema:
        """The all-text schema from the dialect and the header, before any data row is read."""
        header = _decoded(
            self.table,
            lambda: read_csv_source(
                self.path,
                self.dialect,
                table=self.table,
                dtype=str,
                nrows=0,
                file_access=self.access,
                field_key=self.field_key,
                compression=self.compression,
            ),
        )
        return _text_schema([str(name) for name in header.columns])

    @property
    def schema(self) -> pa.Schema:
        return self.preflight()

    def _measure(self) -> FooterFacts:
        """One bounded pass; the preflight sits inside the identity window, so a header change
        shows as a change."""
        schema = self.preflight()
        rows = 0
        nulls = dict.fromkeys(schema.names, 0)
        with _closing(self._chunks(_FACTS_CHUNK_ROWS)) as chunks:
            for frame in chunks:
                rows += len(frame)
                for name, count in frame.isna().sum().items():
                    nulls[str(name)] = nulls.get(str(name), 0) + int(count)
        return FooterFacts(
            num_rows=rows,
            schema=schema,
            null_counts=tuple(nulls.items()),
            row_groups=0,
            max_row_group_rows=0,
        )

    @property
    def num_rows(self) -> int:
        return self.footer_facts().num_rows

    def column_null_counts(self) -> dict[str, int | None]:
        return dict(self.footer_facts().null_counts)

    def iter_batches(
        self, batch_rows: int, *, columns: list[str] | None = None
    ) -> Iterator[pa.RecordBatch]:
        """Yield the file's rows (or just `columns`) as text batches of at most `batch_rows`."""
        return self._stream(check_batch_rows(batch_rows), columns)

    def _stream(self, batch_rows: int, columns: list[str] | None) -> Iterator[pa.RecordBatch]:
        names = self.preflight().names if columns is None else columns
        schema = _text_schema(list(names))
        with _closing(self._chunks(batch_rows, columns)) as chunks:
            for frame in chunks:
                yield _batch(frame, schema)

    def open_batches(
        self,
        batch_rows: int,
        *,
        pre_buffer: bool | None = None,
        buffer_size: int = 0,
        use_threads: bool = True,
        columns: Sequence[str] | None = None,
    ) -> OpenedLazyBatches:
        """Facts and a batch iterator for one read. The facts are the ones routing took when
        the file is unchanged since; the batch iterator checks the identity again when it is
        exhausted. The Parquet buffering arguments do not apply to CSV and are ignored."""
        del pre_buffer, buffer_size, use_threads
        batch_rows = check_batch_rows(batch_rows)
        facts, verify = self._open_facts()

        if columns is None:
            return OpenedCsvBatches(facts, self._chunks(batch_rows), verify)
        names = list(columns)
        return OpenedCsvBatches(facts, self._chunks(batch_rows, names), verify, _text_schema(names))

    def to_table(self, columns: list[str] | None = None) -> pa.Table:
        """Read the file (or just `columns`) into memory as text. Fallback for small jobs."""
        names = self.preflight().names if columns is None else columns
        schema = _text_schema(list(names))
        with _closing(self._chunks(_FACTS_CHUNK_ROWS, columns)) as chunks:
            batches = [_batch(frame, schema) for frame in chunks]
        return pa.Table.from_batches(batches, schema=schema)


__all__ = ["CsvLazySource", "OpenedCsvBatches"]
