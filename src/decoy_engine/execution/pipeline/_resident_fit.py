"""Strict lower bound on the bytes a full-frame run holds resident.

`lower_bound_bytes` is pure: it reads the facts a caller supplies (an in-memory table, or a row
count and a schema from a Parquet footer) and nothing else. It opens no file, reads no lazy source,
detects no host memory and runs no probe. Every width below is a floor, so the sum is a bound the
real peak cannot undercut; a width that turned out too high would make the bound wrong, so the
S1 baseline measures peak against it on every workload.

Method follows the Arrow columnar layout (fixed-width values, 4 or 8 offset bytes per
variable-width row) and the pandas block layout (numpy width per cell, one object pointer per
string-like cell).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

# list_view arrived in pyarrow 16; the floor for this repo is 14.
_LIST_PREDICATES = tuple(
    getattr(pa.types, name)
    for name in (
        "is_list",
        "is_large_list",
        "is_fixed_size_list",
        "is_list_view",
        "is_large_list_view",
    )
    if hasattr(pa.types, name)
)
_OBJECT_POINTER_BYTES = 8
_DICTIONARY_CODE_BYTES = 1  # pandas narrows categorical codes; one byte is the floor


@dataclass(frozen=True)
class TableBytesSpec:
    """One table's size facts.

    `resident_input_bytes` is set for a table already in memory and is `None` for a lazy table,
    which is priced from rows and schema alone. `charge_pandas` is false for a table the run holds
    but never converts to pandas (a generated table in a mixed job).
    """

    rows: int
    schema: pa.Schema
    resident_input_bytes: int | None = None
    charge_pandas: bool = True


def resident_spec(table: pa.Table, *, charge_pandas: bool = True) -> TableBytesSpec:
    return TableBytesSpec(
        rows=table.num_rows,
        schema=table.schema,
        resident_input_bytes=resident_table_bytes(table),
        charge_pandas=charge_pandas,
    )


def lazy_spec(rows: int, schema: pa.Schema, *, charge_pandas: bool = True) -> TableBytesSpec:
    return TableBytesSpec(rows=rows, schema=schema, charge_pandas=charge_pandas)


def resident_table_bytes(table: pa.Table) -> int:
    """`table.nbytes`, with every dictionary that several arrays share counted once.

    `nbytes` charges a dictionary once per array that points at it. The first owner keeps the
    charge; each later array holding the same dictionary buffers is charged zero for it, at any
    depth (a dictionary inside a struct, list or map included). A buffer that cannot be shown to
    be shared stays charged, so the figure never exceeds what is held.
    """
    seen: set[tuple[Any, ...]] = set()
    return sum(
        chunk.nbytes - _repeated_dictionary_bytes(chunk, seen)
        for column in table.columns
        for chunk in column.chunks
    )


def _repeated_dictionary_bytes(array: pa.Array, seen: set[tuple[Any, ...]]) -> int:
    """Bytes of `array` that belong to a dictionary an earlier array already owns."""
    t = array.type
    if pa.types.is_dictionary(t):
        dictionary = array.dictionary
        identity = (
            dictionary.offset,
            len(dictionary),
            *((b.address, b.size) for b in dictionary.buffers() if b is not None),
        )
        if identity in seen:
            return dictionary.nbytes
        seen.add(identity)
        return _repeated_dictionary_bytes(dictionary, seen)
    return sum(_repeated_dictionary_bytes(child, seen) for child in _children(array))


def _children(array: pa.Array) -> list[pa.Array]:
    t = array.type
    if pa.types.is_struct(t):
        return [array.field(i) for i in range(t.num_fields)]
    if pa.types.is_union(t):
        return [array.field(i) for i in range(t.num_fields)]
    if pa.types.is_map(t):
        return [array.keys, array.items]
    if any(is_list(t) for is_list in _LIST_PREDICATES):
        return [array.values]
    return []


def input_bytes(specs: Iterable[TableBytesSpec]) -> int:
    return sum(
        s.resident_input_bytes
        if s.resident_input_bytes is not None
        else _lazy_input_bytes(s.rows, s.schema)
        for s in specs
    )


def pandas_bytes(specs: Iterable[TableBytesSpec]) -> int:
    return sum(
        s.rows * sum(_pandas_cell_bytes(f.type) for f in s.schema) for s in specs if s.charge_pandas
    )


def lower_bound_bytes(specs: Iterable[TableBytesSpec]) -> int:
    """`input_bytes + pandas_bytes` over `specs`. The one formula; callers do not re-derive it."""
    materialized = tuple(specs)
    return input_bytes(materialized) + pandas_bytes(materialized)


def _lazy_input_bytes(rows: int, schema: pa.Schema) -> int:
    return sum(_lazy_column_bytes(rows, f.type) for f in schema)


def _lazy_column_bytes(rows: int, arrow_type: pa.DataType) -> int:
    """Fixed-width part only, plus the offsets of variable-width types; no validity bitmap."""
    t = arrow_type
    if pa.types.is_null(t):
        return 0
    if pa.types.is_boolean(t):
        return -(-rows // 8)
    if pa.types.is_dictionary(t):
        return rows * t.index_type.bit_width // 8
    if pa.types.is_struct(t):
        return sum(_lazy_column_bytes(rows, t.field(i).type) for i in range(t.num_fields))
    if pa.types.is_fixed_size_list(t):
        return 0  # the child length is not in the schema; zero keeps the bound a floor
    if pa.types.is_large_string(t) or pa.types.is_large_binary(t) or pa.types.is_large_list(t):
        return rows * 8
    if pa.types.is_string(t) or pa.types.is_binary(t) or pa.types.is_list(t) or pa.types.is_map(t):
        return rows * 4
    if pa.types.is_fixed_size_binary(t):
        return rows * t.byte_width
    return rows * t.bit_width // 8 if _has_bit_width(t) else 0


def _has_bit_width(t: pa.DataType) -> bool:
    try:
        return t.bit_width > 0
    except ValueError:
        return False


def _pandas_cell_bytes(arrow_type: pa.DataType) -> int:
    t = arrow_type
    if pa.types.is_dictionary(t):
        return _DICTIONARY_CODE_BYTES
    if pa.types.is_boolean(t):
        return 1
    if (
        pa.types.is_integer(t)
        or pa.types.is_floating(t)
        or pa.types.is_timestamp(t)
        or pa.types.is_duration(t)
    ):
        # An int with nulls widens to float64 (8); the int's own width is the floor.
        return t.bit_width // 8
    return _OBJECT_POINTER_BYTES
