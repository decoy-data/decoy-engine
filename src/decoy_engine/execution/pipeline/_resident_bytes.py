"""Byte pricing for the resident-fit decision: `TableBytesSpec` facts and the strict lower bound.

`lower_bound_bytes` is the one formula: `input_bytes + pandas_bytes` over the table facts a caller
supplies (an in-memory table, or a row count and a schema from a Parquet footer). It is pure: no
file is opened, no lazy source read, no host memory detected and no probe run. Every width is a
floor, so the sum is a bound the real peak cannot undercut.

Method follows the Arrow columnar layout (fixed-width values, 4 or 8 offset bytes per
variable-width row) and the pandas block layout (numpy width per cell, one object pointer per
string-like cell).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

import pyarrow as pa

_OBJECT_POINTER_BYTES = 8
_DICTIONARY_CODE_BYTES = 1  # pandas narrows categorical codes; one byte is the floor


@dataclass(frozen=True)
class TableBytesSpec:
    """One table's size facts.

    `resident_input_bytes` is set for a table already in memory and is `None` for a lazy table,
    which is priced from rows and schema alone. `buffer_ranges` holds the `(address, size)` of
    every physical buffer of a resident table, so `input_bytes` counts the union of the byte
    ranges: a buffer shared by several tables, or two slices of one allocation that overlap, is
    counted once. `charge_pandas` is false for a table the run holds but never converts to pandas
    (a generated table in a mixed job). `pandas_shared` names the columns whose pandas form is
    the Arrow column itself (an Arrow-backed dtype), which add no bytes to the input union.
    `pandas_widened` are the shared 32-bit-offset string columns, whose frame still allocates 64-bit offsets; `widened_chunks` is their total chunk
    count, one terminal offset each. Binary is not widened: the frame reuses its offsets.
    """

    rows: int
    schema: pa.Schema
    resident_input_bytes: int | None = None
    charge_pandas: bool = True
    buffer_ranges: tuple[tuple[int, int], ...] = dataclasses.field(default=(), compare=False)
    pandas_shared: frozenset[str] = frozenset()
    pandas_widened: frozenset[str] = frozenset()
    widened_chunks: int = 0


def resident_spec(table: pa.Table, *, charge_pandas: bool = True) -> TableBytesSpec:
    ranges = _buffer_ranges(table)
    shared = _arrow_backed_columns(table)
    widened = frozenset(n for n in shared if _widens_offsets(table.schema.field(n).type))
    return TableBytesSpec(
        rows=table.num_rows,
        schema=table.schema,
        resident_input_bytes=union_bytes(ranges),
        charge_pandas=charge_pandas,
        buffer_ranges=ranges,
        pandas_shared=shared,
        pandas_widened=widened,
        widened_chunks=sum(table.column(n).num_chunks for n in widened),
    )


def union_bytes(ranges: Iterable[tuple[int, int]]) -> int:
    """Bytes covered by the union of `(address, size)` ranges; overlapping or touching merge."""
    total = 0
    end = -1
    for start, size in sorted(ranges):
        stop = start + size
        if start > end:
            total += size
            end = stop
        elif stop > end:
            total += stop - end
            end = stop
    return total


def _buffer_ranges(table: pa.Table) -> tuple[tuple[int, int], ...]:
    """The `(address, size)` of each physical buffer under `table`, at any depth."""
    ranges: list[tuple[int, int]] = []
    for column in table.columns:
        for chunk in column.chunks:
            _collect_buffers(chunk, ranges)
    return tuple(ranges)


def _collect_buffers(array: pa.Array, ranges: list[tuple[int, int]]) -> None:
    ranges.extend((b.address, b.size) for b in array.buffers() if b is not None and b.size)
    t = array.type
    if pa.types.is_dictionary(t):
        _collect_buffers(array.dictionary, ranges)
    elif pa.types.is_struct(t):
        for i in range(t.num_fields):
            _collect_buffers(array.field(i), ranges)
    elif pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_map(t):
        _collect_buffers(array.values, ranges)


def _arrow_backed_columns(table: pa.Table) -> frozenset[str]:
    """Columns `to_transform_frame` hands to pandas as the Arrow column itself.

    A column whose pandas metadata names an Arrow-backed dtype (`int64[pyarrow]`) comes back as
    `ArrowDtype` over the same chunks, so it adds no bytes. An integer column with nulls is the
    exception: the transform frame maps it to a nullable numpy-backed dtype, which copies.
    """
    from decoy_engine.execution._transforms_table import null_bearing_int_columns

    meta = table.schema.pandas_metadata
    if not meta:
        return frozenset()
    null_copied = set(null_bearing_int_columns(table))
    names: set[str] = set()
    for entry in meta.get("columns", ()):
        name = entry.get("field_name")
        if not str(entry.get("numpy_type", "")).endswith("[pyarrow]"):
            continue
        if name not in table.column_names:
            continue
        if name in null_copied:
            continue
        names.add(name)
    return frozenset(names)


def _widens_offsets(arrow_type: pa.DataType) -> bool:
    """A 32-bit-offset string column: the frame shares the payload, not the offsets."""
    return pa.types.is_string(arrow_type)


def lazy_spec(rows: int, schema: pa.Schema, *, charge_pandas: bool = True) -> TableBytesSpec:
    return TableBytesSpec(rows=rows, schema=schema, charge_pandas=charge_pandas)


def input_bytes(specs: Iterable[TableBytesSpec]) -> int:
    """Lazy tables from rows and schema; resident tables by the union of their buffer ranges.

    Tables read from one source or sliced from one allocation share bytes, so summing each table
    alone would count them twice and break the lower bound.
    """
    total = 0
    ranges: list[tuple[int, int]] = []
    for s in specs:
        if s.resident_input_bytes is None:
            total += _lazy_input_bytes(s.rows, s.schema)
        elif s.buffer_ranges:
            ranges.extend(s.buffer_ranges)
        else:
            total += s.resident_input_bytes
    return total + union_bytes(ranges)


_WIDENED_OFFSET_BYTES = 8  # the frame's 64-bit offsets: one per row plus one terminal per chunk


def pandas_bytes(specs: Iterable[TableBytesSpec]) -> int:
    """Each charged table's pandas copy, less the columns that share the Arrow buffers."""
    return sum(
        s.widened_chunks * _WIDENED_OFFSET_BYTES
        + s.rows
        * sum(
            _WIDENED_OFFSET_BYTES if f.name in s.pandas_widened else _pandas_cell_bytes(f.type)
            for f in s.schema
            if f.name in s.pandas_widened or f.name not in s.pandas_shared
        )
        for s in specs
        if s.charge_pandas
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
