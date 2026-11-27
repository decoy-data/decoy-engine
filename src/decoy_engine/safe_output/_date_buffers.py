"""Date columns that leave the engine in buffers of their own (DATE-RANGE-SENTINEL S5, 4.4b item 5).

A sliced Arrow array shares its parent's buffers, and a null slot keeps whatever integer was
stored there. An Arrow return that serializes such an array writes the whole backing buffer,
so a date the checked read excluded (a far day in a hidden slice, a poisoned null payload) can
ride out in the bytes. `own_date_columns` rebuilds every plain date or timestamp column, and
every retained date dictionary with its indices, over fresh buffers that hold exactly the
logical range: zeroed payload, validity packed from bit zero with zero tail bits, no offset.
It reads physical integers only, so no date is converted to a Python object.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import numpy as np
import pyarrow as pa

from decoy_engine._arrow_types import is_date_leaf


def _physical(arrow_type: pa.DataType) -> pa.DataType:
    """The integer type whose bytes a date, timestamp or integer array stores."""
    if pa.types.is_date32(arrow_type):
        return pa.int32()
    if pa.types.is_integer(arrow_type):
        return arrow_type
    return pa.int64()  # date64 and every timestamp unit


def _owned(array: pa.Array) -> pa.Array:
    """`array` over new buffers sized to its logical range. Only valid positions are copied."""
    length = len(array)
    if length == 0:
        return pa.array([], array.type)
    physical = _physical(array.type)
    valid = np.asarray(array.is_valid().to_numpy(zero_copy_only=False), dtype=bool)
    ints = array.view(physical).fill_null(0)
    payload = np.zeros(length, dtype=physical.to_pandas_dtype())
    payload[valid] = np.asarray(ints.to_numpy(zero_copy_only=False))[valid]
    validity = (
        None if valid.all() else pa.py_buffer(np.packbits(valid, bitorder="little").tobytes())
    )
    return pa.Array.from_buffers(
        array.type,
        length,
        [validity, pa.py_buffer(payload.tobytes())],
        null_count=int(length - valid.sum()),
    )


def _owned_dictionary(array: pa.DictionaryArray) -> pa.DictionaryArray:
    return pa.DictionaryArray.from_arrays(
        _owned(array.indices), _owned(array.dictionary), ordered=array.type.ordered
    )


def _owns(arrow_type: pa.DataType) -> bool:
    if pa.types.is_dictionary(arrow_type):
        return is_date_leaf(arrow_type.value_type)
    return is_date_leaf(arrow_type)


def _column(column: Any) -> Any:
    chunks = column.chunks if isinstance(column, pa.ChunkedArray) else [column]
    rebuilt = [
        _owned_dictionary(chunk) if pa.types.is_dictionary(chunk.type) else _owned(chunk)
        for chunk in chunks
    ]
    return (
        pa.chunked_array(rebuilt, column.type)
        if isinstance(column, pa.ChunkedArray)
        else rebuilt[0]
    )


def own_date_columns(data: Any) -> Any:
    """`data` (a Table or RecordBatch) with each date column over buffers it owns. A table with
    no such column comes back as it is; schema, units, zones, entry order, index types and the
    ordered flag are kept."""
    names = [i for i, t in enumerate(data.schema.types) if _owns(t)]
    if not names:
        return data
    columns = [data.column(i) for i in range(data.num_columns)]
    for i in names:
        columns[i] = _column(columns[i])
    if isinstance(data, pa.Table):
        return pa.Table.from_arrays(columns, schema=data.schema)
    return pa.RecordBatch.from_arrays(columns, schema=data.schema)


def own_date_chunks(chunks: Iterable[Any]) -> Iterator[Any]:
    """Each chunk of a lazy stream through `own_date_columns`, one at a time. Closing this
    iterator closes the stream it wraps."""
    try:
        for chunk in chunks:
            yield own_date_columns(chunk)
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()


__all__ = ["own_date_chunks", "own_date_columns"]
