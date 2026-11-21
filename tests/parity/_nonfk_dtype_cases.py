"""One synthetic source per type class and null layout, for the non-FK dtype matrix.

Each case is a 200-row table with a masked string column `s` and one typed column `p`. The
support module runs it with `chunk_size_rows=16` and `auto_chunk_threshold_rows=10`, so it stands
in for a large table of 13 chunks. Layouts: `chunk0_all_null` (the first 50 rows null, so chunks 0
to 2 are all null, later rows mixed), `later_mixed` (chunk 0 null-free, later chunks mixed) and
`wide_value` (the widest values the type holds, nulls in later chunks).
"""

from __future__ import annotations

import decimal
from collections.abc import Callable
from typing import Any

import pyarrow as pa

ROWS = 200
NULL_PREFIX = 50
LAYOUTS = ("chunk0_all_null", "later_mixed", "wide_value")


def null_at(layout: str, i: int) -> bool:
    """Whether row `i` is null under `layout`."""
    if layout == "chunk0_all_null":
        return i < NULL_PREFIX or i % 5 == 0
    return i >= NULL_PREFIX and i % 7 == 0


def _wide(layout: str) -> bool:
    return layout == "wide_value"


def _ints(layout: str, *, unsigned: bool) -> list[Any]:
    base = (2**63 + 12345, 2**64 - 1) if unsigned else (2**53 + 1, -(2**63) + 7, 2**63 - 1)
    out: list[Any] = []
    for i in range(ROWS):
        if null_at(layout, i):
            out.append(None)
        elif _wide(layout):
            out.append(base[i % len(base)])
        else:
            out.append(i * 3 + 1)
    return out


def _decimals(layout: str) -> list[Any]:
    wide = decimal.Decimal("99999999.99")
    return [
        None
        if null_at(layout, i)
        else (wide if _wide(layout) and i % 2 else decimal.Decimal(i) / 100)
        for i in range(ROWS)
    ]


def _blobs(layout: str, *, width: int | None = None) -> list[Any]:
    out: list[Any] = []
    for i in range(ROWS):
        if null_at(layout, i):
            out.append(None)
        elif width is not None:
            out.append(bytes([i % 256]) * width)
        elif _wide(layout):
            out.append(b"\xff" * (4096 if i % 2 else 1))
        else:
            out.append(f"b{i}".encode())
    return out


def _lists(layout: str) -> list[Any]:
    return [
        None if null_at(layout, i) else list(range(100 if _wide(layout) and i % 2 else i % 4))
        for i in range(ROWS)
    ]


def _structs(layout: str) -> list[Any]:
    return [
        None if null_at(layout, i) else {"a": i, "b": None if i % 3 == 0 else f"v{i}"}
        for i in range(ROWS)
    ]


def _maps(layout: str) -> list[Any]:
    return [
        None if null_at(layout, i) else [(f"k{j}", j + i) for j in range(2 if i % 2 else 0)]
        for i in range(ROWS)
    ]


def _dictionary(layout: str) -> pa.Array:
    values = [None if null_at(layout, i) else f"c{i % 6}" for i in range(ROWS)]
    return pa.array(values, pa.string()).dictionary_encode()


# type class -> builder(layout) -> Arrow array of ROWS values
CARRIED_TYPES: dict[str, Callable[[str], pa.Array]] = {
    "int64_nulls": lambda lay: pa.array(_ints(lay, unsigned=False), pa.int64()),
    "uint64": lambda lay: pa.array(_ints(lay, unsigned=True), pa.uint64()),
    "decimal128": lambda lay: pa.array(_decimals(lay), pa.decimal128(10, 2)),
    "binary": lambda lay: pa.array(_blobs(lay), pa.binary()),
    "large_binary": lambda lay: pa.array(_blobs(lay), pa.large_binary()),
    "fixed_size_binary": lambda lay: pa.array(_blobs(lay, width=4), pa.binary(4)),
    "dictionary": _dictionary,
    "list": lambda lay: pa.array(_lists(lay), pa.list_(pa.int64())),
    "large_list": lambda lay: pa.array(_lists(lay), pa.large_list(pa.int64())),
    "struct": lambda lay: pa.array(
        _structs(lay), pa.struct([("a", pa.int64()), ("b", pa.string())])
    ),
    "map": lambda lay: pa.array(_maps(lay), pa.map_(pa.string(), pa.int64())),
}


def source_table(type_class: str, layout: str, column: str = "p") -> pa.Table:
    """The 200-row source: masked `s`, and `column` holding `type_class` under `layout`."""
    return pa.table(
        {
            "s": pa.array([f"name{i}" for i in range(ROWS)], pa.string()),
            column: CARRIED_TYPES[type_class](layout),
        }
    )
