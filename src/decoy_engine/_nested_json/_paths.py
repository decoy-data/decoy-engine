"""The one reader of a nested path's key leaf: path shape and key extraction.

A rule that `references` a parent column names one leaf by a singular path of name segments
(`$.customer_id`, `$.ref.customer_id`). `path_key_batches` reads that leaf from a payload column
and yields an Arrow key column of the parent key column's type, so a pre-scan and a post-scan that
call it count the same keys. Nothing reads it yet; 82-E4b wires both scans.

An integer parent takes JSON integers and a string parent takes JSON strings. A missing path (also one that
runs through a scalar, as JSONPath reads it) and a JSON null are a null key. A cell that is not valid JSON, and a leaf of another kind (`"42"` for an
integer parent, an object, an array, a boolean, a float), is counted in `unreadable_rows` and not
loaded, so the key column has one type and `42` never matches `"42"`.

Messages are fixed text: no cell content.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final

import pyarrow as pa

from decoy_engine._canonical import (
    MASK_CELL_BYTES,
    MASK_MAX_DEPTH,
    StrictJsonError,
    strict_json_read,
)

__all__ = ["PathKeyBatch", "path_key_batches", "singular_path"]

_NAME_SEGMENT: Final = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class PathKeyBatch:
    """The keys read from one batch of payload cells, and how many cells were not readable."""

    keys: pa.Array
    unreadable_rows: int


def singular_path(path: Any) -> tuple[str, ...] | None:
    """The name segments of a singular path (`$.a.b`), or `None` for any other path text."""
    if not isinstance(path, str) or not path.startswith("$"):
        return None
    names: list[str] = []
    pos = 1
    while pos < len(path):
        match = _NAME_SEGMENT.match(path, pos)
        if match is None:
            return None
        names.append(match.group(1))
        pos = match.end()
    return tuple(names) or None


def _kind(parent_type: pa.DataType) -> str:
    if pa.types.is_integer(parent_type):
        return "integer"
    if pa.types.is_string(parent_type) or pa.types.is_large_string(parent_type):
        return "string"
    raise ValueError("a path key needs an integer or a string parent key column")


def _bounds(parent_type: pa.DataType) -> tuple[int, int] | None:
    if not pa.types.is_integer(parent_type):
        return None
    bits = parent_type.bit_width
    if pa.types.is_signed_integer(parent_type):
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def path_key_batches(
    batches: Iterable[pa.Array | pa.ChunkedArray],
    path: str,
    parent_type: pa.DataType,
    *,
    max_bytes: int = MASK_CELL_BYTES,
    max_depth: int = MASK_MAX_DEPTH,
) -> Iterator[PathKeyBatch]:
    """Yield the key column of each payload batch, read at `path` and typed as `parent_type`.

    Raises:
        ValueError: `path` is not a singular path of name segments, or `parent_type`
            is neither an integer nor a string type.
    """
    names = singular_path(path)
    if names is None:
        raise ValueError("a path key needs a singular path of name segments")
    kind = _kind(parent_type)
    bounds = _bounds(parent_type)
    for batch in batches:
        keys: list[Any] = []
        unreadable = 0
        for cell in batch.to_pylist():
            ok, key = _read_key(cell, names, kind, bounds, max_bytes, max_depth)
            if ok:
                keys.append(key)
            else:
                unreadable += 1
        yield PathKeyBatch(pa.array(keys, type=parent_type), unreadable)


def _read_key(
    cell: Any,
    names: tuple[str, ...],
    kind: str,
    bounds: tuple[int, int] | None,
    max_bytes: int,
    max_depth: int,
) -> tuple[bool, Any]:
    """`(readable, key)`: a missing path or null is `(True, None)`."""
    if cell is None:
        return True, None
    try:
        node = strict_json_read(cell, max_bytes=max_bytes, max_depth=max_depth)
    except StrictJsonError:
        return False, None
    for name in names:
        if not isinstance(node, dict) or name not in node:
            return True, None  # no match, as JSONPath reads it
        node = node[name]
    if node is None:
        return True, None
    if kind == "string":
        return isinstance(node, str), node
    if isinstance(node, bool) or not isinstance(node, int):
        return False, None
    if bounds is not None and not bounds[0] <= node <= bounds[1]:
        return False, None
    return True, node
