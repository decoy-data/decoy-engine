"""Arrow type predicates and the exact key cast, shared across layers (bottom leaf; imports
only pyarrow).

`string` and `large_string` are the same logical UTF-8 type with 32-bit or 64-bit offsets, and
a parquet read keeps whichever the file declared, so every check for "text" must accept both.

`exact_key_cast` is the cast the out-of-core FK join uses to unify one output column's chunk
types (`cast_fk_chunk`). It is not a matching rule: which key values are equal is decided by the
join tokens in `decoy_engine.internal.fk_tokens`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import pairwise

import numpy as np
import pyarrow as pa


def is_text(t: pa.DataType) -> bool:
    """True for `string` and `large_string`."""
    return pa.types.is_string(t) or pa.types.is_large_string(t)


def narrow_text(array: pa.Array) -> pa.Array:
    """Return `array` as a `string` array: `string` unchanged, `large_string` safely cast.

    The one owner of offset-width normalization for kernels that have a `string` fast path.
    The cast copies offsets and leaves the value bytes alone, so it does not check UTF-8: the
    caller still validates. It raises `pa.ArrowInvalid` when the text does not fit 32-bit
    offsets, and `TypeError` for any other type.
    """
    if pa.types.is_string(array.type):
        return array
    if pa.types.is_large_string(array.type):
        return array.cast(pa.string())
    raise TypeError(f"narrow_text needs a string or large_string array, got {array.type}")


# Largest total payload a 32-bit-offset `string` array can hold (a patch target for tests).
_OFFSET_LIMIT = 2**31 - 1


def _text_cuts(array: pa.Array) -> list[int] | None:
    """Row boundaries (first 0, last `len`) so that each span fits 32-bit offsets.

    Reads only the 64-bit offsets, never the payload: a span within the limit needs two
    reads, a larger one is cut greedily. None when a single value exceeds the limit.
    """
    if not len(array):
        return [0, 0]
    raw = np.frombuffer(array.buffers()[1], dtype=np.int64)
    offsets = raw[array.offset : array.offset + len(array) + 1]
    if offsets[-1] - offsets[0] <= _OFFSET_LIMIT:
        return [0, len(array)]
    cuts = [0]
    while cuts[-1] < len(array):
        start = cuts[-1]
        end = int(np.searchsorted(offsets, offsets[start] + _OFFSET_LIMIT, side="right")) - 1
        if end <= start:
            return None
        cuts.append(end)
    return cuts


def split_narrow_text(array: pa.Array) -> list[pa.Array] | None:
    """Split a `large_string` array into ordered `string` slices that each fit 32-bit offsets.

    None when a single value exceeds the limit, because no row split can narrow it.
    """
    cuts = _text_cuts(array)
    if cuts is None:
        return None
    return [array.slice(a, b - a).cast(pa.string()) for a, b in pairwise(cuts)]


def split_wide_batch(batch: pa.RecordBatch) -> list[pa.RecordBatch]:
    """Cut a record batch at the row boundaries its `large_string` columns need.

    A batch whose text fits is returned whole. Every column is sliced at the same rows, so
    order, nulls and the other columns are untouched. A column holding one unsplittable value
    adds no cut: its slice stays `large_string` for the width state to promote.
    """
    cuts = {0, batch.num_rows}
    for column in batch.columns:
        if pa.types.is_large_string(column.type):
            cuts |= set(_text_cuts(column) or ())
    bounds = sorted(cuts)
    if len(bounds) <= 2:
        return [batch]
    return [batch.slice(a, b - a) for a, b in pairwise(bounds)]


class TextWidthState:
    """The offset width of one pass-through text column across batches, in source order.

    Starts narrow. `observe` returns a batch as `string` slices while every value fits, and
    the first value that does not promotes the state to `large_string` for good. There is no
    source pre-scan: each batch is judged from its own offsets when it arrives.
    """

    def __init__(self) -> None:
        self.wide = False

    @property
    def arrow_type(self) -> pa.DataType:
        return pa.large_string() if self.wide else pa.string()

    def observe(self, array: pa.Array) -> list[pa.Array]:
        if not is_text(array.type):
            return [array]
        if not self.wide and pa.types.is_large_string(array.type):
            parts = split_narrow_text(array)
            if parts is not None:
                return parts
            self.wide = True
        if self.wide and pa.types.is_string(array.type):
            return [array.cast(pa.large_string())]
        return [array]


def promoted_text_type(fixed: pa.DataType, state: TextWidthState | None) -> pa.DataType:
    """`large_string` for a text type whose width state was promoted, else `fixed` unchanged."""
    return pa.large_string() if state is not None and state.wide and is_text(fixed) else fixed


def widen_text_columns(chunks: Iterable[pa.Table], columns: frozenset[str]) -> Iterator[pa.Table]:
    """Give pass-through text columns the source `large_string` field again.

    A Parquet writer fixes its schema before the first chunk, so a sink keeps the source field
    as on main and every failure stays main's. Widening copies offsets only.
    """
    for chunk in chunks:
        for name in columns:
            idx = chunk.schema.get_field_index(name)
            if idx >= 0 and pa.types.is_string(chunk.schema.field(idx).type):
                field = chunk.schema.field(idx).with_type(pa.large_string())
                chunk = chunk.set_column(idx, field, chunk.column(idx).cast(pa.large_string()))
        yield chunk


def unify_text_widths(types: set[pa.DataType]) -> set[pa.DataType]:
    """Collapse `string` and `large_string` chunk types to `large_string` (a promoted column)."""
    if pa.string() in types and pa.large_string() in types:
        return types - {pa.string()}
    return types


def is_text_or_null(t: pa.DataType) -> bool:
    """`is_text`, or the `null` type of an all-null batch the reader could not type."""
    return is_text(t) or pa.types.is_null(t)


def exact_key_cast(chunk: pa.Array, target: pa.DataType) -> pa.Array:
    """Cast one key chunk to `target` without silent drift, or raise an Arrow error.

    pyarrow's safe cast rejects every int -> float conversion outside [-2**53, 2**53], even a
    value that is exactly representable, because it guards the whole doubtful range. An integer
    chunk is therefore widened unsafely and kept only when it casts straight back to the same
    integers; a key that would round raises `ArrowInvalid`. The error carries the types only:
    pyarrow's own text quotes the value, and that text is dropped.
    """
    if chunk.type.equals(target):
        return chunk
    if pa.types.is_integer(chunk.type) and pa.types.is_floating(target):
        widened = chunk.cast(target, safe=False)
        if not widened.cast(chunk.type, safe=False).equals(chunk):
            raise pa.ArrowInvalid(f"cannot cast a key chunk {chunk.type} -> {target} exactly")
        return widened
    try:
        return chunk.cast(target)
    except MemoryError:
        raise
    except pa.ArrowException as exc:
        failed = type(exc)
    raise failed(f"cannot cast a key chunk {chunk.type} -> {target} exactly")


# One int32 offset per row of a variable-width Arrow column.
_OFFSET_BYTES = 4


def arrow_column_bytes(arrow_type: pa.DataType, rows: int, width: float) -> int:
    """Bytes of one Arrow column's data buffers (no validity bitmap).

    A fixed-width column is `bit_width` bits a value, rounded up to whole bytes so a 1-bit
    boolean stays an integer count. A variable-width column holds one int32 offset a value
    plus `width` payload bytes a value (`width` is the mean, 0 when the caller has none).
    """
    try:
        bit_width = arrow_type.bit_width
    except ValueError:  # variable-width types have no bit width
        return int(rows * (_OFFSET_BYTES + width))
    return (rows * bit_width + 7) // 8
