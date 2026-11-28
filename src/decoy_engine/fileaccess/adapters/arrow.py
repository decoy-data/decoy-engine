"""PyArrow adapter: Parquet and Arrow IPC reads and writes over policy capabilities."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO, TypeVar

import pyarrow as pa
import pyarrow.ipc
import pyarrow.parquet as pq

from decoy_engine.errors import ParquetFixedListNullError
from decoy_engine.fileaccess._errors import guarded, guarded_iter
from decoy_engine.fileaccess._types import FileHandle, StageDir
from decoy_engine.safe_output import output_schema, output_table


def _strict(handle: FileHandle) -> bool:
    return bool(getattr(handle, "strict", True))


# Custom metadata on the empty batch `ipc_write_exact` puts between chunks; no staged chunk has any.
_SEPARATOR = {b"decoy.isolated.separator": b"1"}


def ipc_write_exact(writer: _FileBacked, table: pa.Table) -> None:
    """Write `table` to an IPC stream so every chunk's dictionaries reach it bit for bit."""
    # The writer skips a dictionary equal to the last one sent, and Arrow equality takes -0.0
    # for +0.0; an empty-dictionary separator makes every chunk send its own.
    empty = [pa.nulls(0, field.type) for field in table.schema]
    separator = pa.RecordBatch.from_arrays(empty, schema=table.schema)
    for index, batch in enumerate(table.to_batches()):
        if index:
            writer.write_batch(separator, custom_metadata=_SEPARATOR)
        writer.write_batch(batch)


def _stream_chunks(reader: pa.ipc.RecordBatchStreamReader) -> list[pa.RecordBatch]:
    chunks: list[pa.RecordBatch] = []
    while True:
        try:
            item = reader.read_next_batch_with_custom_metadata()
        except StopIteration:
            return chunks
        meta = item.custom_metadata
        if meta is None or dict(meta) != _SEPARATOR:
            chunks.append(item.batch)


def ipc_read_path(handle: FileHandle) -> pa.Table:
    """Read a staged IPC stream; the returned Arrow buffers retain the mapped private file."""
    with guarded("isolated.sources", True, pa.memory_map, handle.library_path(), "r") as source:
        reader = guarded("isolated.sources", True, pa.ipc.open_stream, source)
        chunks = guarded("isolated.sources", True, _stream_chunks, reader)
        return pa.Table.from_batches(chunks, schema=reader.schema)


def read_table(handle: FileHandle, **kwargs: Any) -> pa.Table:
    return guarded(handle.display, _strict(handle), pq.read_table, handle.library_path(), **kwargs)


_T = TypeVar("_T")


def _read_single_file(handle: FileHandle, read: Callable[[BinaryIO], _T]) -> _T:
    """Close the input even when Arrow retains its scanner or rejects a corrupt footer."""
    with guarded(handle.display, _strict(handle), handle.open_binary) as source:
        return guarded(handle.display, _strict(handle), read, source)


def read_staged_table(handle: FileHandle) -> pa.Table:
    return _read_single_file(handle, pq.read_table)


def parquet_file(handle: FileHandle, **kwargs: Any) -> pq.ParquetFile:
    return guarded(handle.display, _strict(handle), pq.ParquetFile, handle.library_path(), **kwargs)


def iter_batches(
    handle: FileHandle, parquet_file: pq.ParquetFile, **kwargs: Any
) -> Iterator[pa.RecordBatch]:
    """`ParquetFile.iter_batches`, each step guarded under a strict handle."""
    source = guarded(handle.display, _strict(handle), parquet_file.iter_batches, **kwargs)
    return guarded_iter(handle.display, _strict(handle), source)


@contextmanager
def staged_parquet(fd: int) -> Iterator[pq.ParquetFile]:
    """A staged output file, opened from a descriptor the stage issued; closes it on exit."""
    fh = os.fdopen(fd, "rb")
    try:
        yield guarded("output", True, pq.ParquetFile, fh)
    finally:
        fh.close()


def iter_staged_batches(parquet_file: pq.ParquetFile, **kwargs: Any) -> Iterator[pa.RecordBatch]:
    """`ParquetFile.iter_batches` over a staged file: one row group at a time, each step guarded."""
    source = guarded("output", True, parquet_file.iter_batches, **kwargs)
    return guarded_iter("output", True, source)


def read_metadata(handle: FileHandle) -> pq.FileMetaData:
    return _read_single_file(handle, pq.read_metadata)


class _FileBacked:
    """A writer plus the file object it writes to; closing the writer closes both."""

    def __init__(self, writer: Any, fh: Any, display: str, strict: bool) -> None:
        self._writer = writer
        self._fh = fh
        self._display = display
        self._strict = strict

    def write_batch(self, batch: pa.RecordBatch, *args: Any, **kwargs: Any) -> None:
        guarded(self._display, self._strict, self._writer.write_batch, batch, *args, **kwargs)

    def write_table(self, table: pa.Table, *args: Any, **kwargs: Any) -> None:
        guarded(self._display, self._strict, self._writer.write_table, table, *args, **kwargs)

    def write(self, data: Any) -> None:
        guarded(self._display, self._strict, self._writer.write, data)

    def close(self) -> None:
        try:
            guarded(self._display, self._strict, self._writer.close)
        finally:
            self._fh.close()

    def __enter__(self) -> _FileBacked:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _writable(txn: StageDir, component: str) -> Any:
    return os.fdopen(txn.create_file(component), "wb")


def _readable(txn: StageDir, component: str) -> Any:
    return os.fdopen(txn.open_file(component), "rb")


def write_table(table: pa.Table, txn: StageDir, component: str, **kwargs: Any) -> None:
    """`pq.write_table` into a new file of the stage; bytes match a path write."""
    with _writable(txn, component) as fh:
        guarded(txn.display, txn.strict, pq.write_table, table, fh, **kwargs)


def parquet_writer(txn: StageDir, component: str, schema: pa.Schema, **kwargs: Any) -> _FileBacked:
    fh = _writable(txn, component)
    try:
        writer = guarded(txn.display, txn.strict, pq.ParquetWriter, fh, schema, **kwargs)
    except BaseException:
        fh.close()
        raise
    return _FileBacked(writer, fh, txn.display, txn.strict)


def _type_children(t: pa.DataType) -> list[pa.DataType]:
    """The types directly inside `t`: the one place the type checks learn Arrow's nesting rules."""
    if isinstance(t, pa.BaseExtensionType):
        return [t.storage_type]
    if pa.types.is_dictionary(t):
        return [t.value_type]
    if pa.types.is_map(t):
        return [t.field(0).type]  # the entries struct, whose fields are key and item
    if pa.types.is_struct(t) or pa.types.is_union(t):
        return [t.field(i).type for i in range(t.num_fields)]
    if hasattr(t, "value_type"):  # list, large list, fixed-size list and the list views
        return [t.value_type]
    return []


def _type_nodes(t: pa.DataType) -> Iterator[pa.DataType]:
    yield t
    for child in _type_children(t):
        yield from _type_nodes(child)


def _array_children(t: pa.DataType, array: pa.Array) -> list[pa.Array]:
    """The slice's children in `_type_children` order, struct validity pushed down; none where
    child positions do not follow the parent's (dictionary values, union members, list views)."""
    if isinstance(t, pa.BaseExtensionType):
        return [array.storage]
    if pa.types.is_struct(t):
        return list(array.flatten())
    if pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_fixed_size_list(t):
        return [array.flatten()]
    if pa.types.is_map(t):
        return [array.cast(pa.list_(t.field(0))).flatten()]
    return []


def _walk(t: pa.DataType, array: pa.Array) -> Iterator[tuple[pa.DataType, pa.Array]]:
    """Visit the slice's logical children with arrays that line up with its rows."""
    yield t, array
    for child_type, child in zip(_type_children(t), _array_children(t, array), strict=False):
        yield from _walk(child_type, child)


_EXACT_SCALARS = frozenset(
    (
        pa.null(),
        pa.bool_(),
        pa.float32(),
        pa.float64(),
        pa.string(),
        pa.large_string(),
        pa.binary(),
        pa.large_binary(),
        pa.date32(),
        pa.time32("ms"),
        pa.int8(),
        pa.int16(),
        pa.int32(),
        pa.int64(),
        pa.uint8(),
        pa.uint16(),
        pa.uint32(),
        pa.uint64(),
    )
)


def _parquet_exact(t: pa.DataType) -> bool:
    if isinstance(t, pa.BaseExtensionType):
        return False
    if pa.types.is_dictionary(t):
        # Parquet refuses a null dictionary entry, which no type check can see.
        return False
    if pa.types.is_timestamp(t):
        return t.unit in ("ms", "us", "ns")
    return (
        t in _EXACT_SCALARS
        or (isinstance(t, (pa.Decimal128Type, pa.Decimal256Type)) and 0 <= t.scale <= t.precision)
        or (pa.types.is_fixed_size_binary(t) and t.byte_width > 0)
        or pa.types.is_time64(t)
        or pa.types.is_duration(t)
        or (pa.types.is_struct(t) and t.num_fields > 0)
        or pa.types.is_list(t)
        or pa.types.is_large_list(t)
    )


def parquet_holds_type(t: pa.DataType) -> bool:
    return all(_parquet_exact(node) for node in _type_nodes(t))


def ipc_refusal(t: pa.DataType) -> str | None:
    """Why IPC cannot stage `t`, or None. A dictionary may hold a struct, list, map or union of
    anything, but not a dictionary (IPC reads the inner indices back as values) or an extension
    type (the reader rejects the extension over dictionary storage)."""
    for node in _type_nodes(t):
        if pa.types.is_dictionary(node):
            if pa.types.is_dictionary(node.value_type):
                return "dictionary_in_dictionary"
            if isinstance(node.value_type, pa.BaseExtensionType):
                return "dictionary_of_extension"
    return None


def _refuse_fixed_list_null(data: pa.Table | pa.RecordBatch) -> None:
    for field, column in zip(data.schema, data.columns, strict=True):
        if not any(pa.types.is_fixed_size_list(t) for t in _type_nodes(field.type)):
            continue
        chunks = column.chunks if isinstance(column, pa.ChunkedArray) else (column,)
        for chunk in chunks:
            if any(
                pa.types.is_fixed_size_list(t) and a.null_count for t, a in _walk(field.type, chunk)
            ):
                raise ParquetFixedListNullError(f"Null fixed-size list in column {field.name!r}.")


class _CheckedParquetWriter:
    def __init__(self, writer: _FileBacked) -> None:
        self._writer = writer

    def write_table(self, table: pa.Table, *args: Any, **kwargs: Any) -> None:
        _refuse_fixed_list_null(table)
        self._writer.write_table(table, *args, **kwargs)

    def write_batch(self, batch: pa.RecordBatch, *args: Any, **kwargs: Any) -> None:
        _refuse_fixed_list_null(batch)
        self._writer.write_batch(batch, *args, **kwargs)

    def close(self) -> None:
        self._writer.close()

    def __enter__(self) -> _CheckedParquetWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def write_output_table(table: pa.Table, txn: StageDir, component: str) -> None:
    """Write a published output table: `output_table` first, so the file carries no source
    key/value metadata (`safe_output`). The one engine entry for a whole published table."""
    _refuse_fixed_list_null(table)
    write_table(output_table(table), txn, component)


def output_parquet_writer(
    txn: StageDir, component: str, schema: pa.Schema
) -> _CheckedParquetWriter:
    """A published output writer built from `output_schema`, before the file is created. The
    footer holds the writer's schema, so batches that carry metadata cannot add to it."""
    return _CheckedParquetWriter(parquet_writer(txn, component, output_schema(schema)))


def ipc_new_file(txn: StageDir, component: str, schema: pa.Schema) -> _FileBacked:
    fh = _writable(txn, component)
    try:
        writer = guarded(txn.display, txn.strict, pa.ipc.new_file, fh, schema)
    except BaseException:
        fh.close()
        raise
    return _FileBacked(writer, fh, txn.display, txn.strict)


def ipc_new_stream(txn: StageDir, component: str, schema: pa.Schema) -> _FileBacked:
    fh = _writable(txn, component)
    try:
        writer = guarded(txn.display, txn.strict, pa.ipc.new_stream, fh, schema)
    except BaseException:
        fh.close()
        raise
    return _FileBacked(writer, fh, txn.display, txn.strict)


def ipc_read_file(txn: StageDir, component: str) -> pa.Table:
    """Read a whole IPC file written into this stage back as a table."""
    with _readable(txn, component) as fh:
        reader = guarded(txn.display, txn.strict, pa.ipc.open_file, fh)
        return guarded(txn.display, txn.strict, reader.read_all)


def ipc_read_stream_batches(txn: StageDir, component: str) -> list[pa.RecordBatch]:
    with _readable(txn, component) as fh:
        reader = guarded(txn.display, txn.strict, pa.ipc.open_stream, fh)
        return [b for b in reader]
