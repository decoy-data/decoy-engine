"""The Arrow column walk: the `ColumnProfile` the pandas walk would produce, without pandas.

The chunked first-chunk profile uses it for carried passthrough columns, so their values never
reach pandas (rule R3). The pandas NaT and dtype-label rules it must match live in
`internal.pandas_compat`, because they decide from Arrow timestamp types and the column-shape
sentry keeps that kind of decision out of this package.
"""

from __future__ import annotations

import importlib
from typing import Any

import pyarrow as pa

from decoy_engine._arrow_types import is_text
from decoy_engine.internal.pandas_compat import (
    arrow_dtype_label,
    arrow_missing_mask,
    canonical_dtype_label,
)

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")


def holds_date32(t: pa.DataType) -> bool:
    """A 32-bit date. The date decision goes through the shared classifier (the column-shape
    sentry forbids a second one); the width tells date32 from date64."""
    from decoy_engine.contracts.column_shape import ColumnShape
    from decoy_engine.profile._walk import observed_shape

    return observed_shape(t, None) is ColumnShape.DATE and t.bit_width == 32


def arrow_column_profile(
    name: str, column: pa.Array | pa.ChunkedArray, *, source_format: str | None = None
) -> Any:
    """The `ColumnProfile` `walk_dataframe` would produce for `column`, computed
    from Arrow without pandas (rule R3, pinned field by field by test 20).

    Missing values are Arrow nulls, NaN in floating columns and the int64 minimum
    in timestamp and duration columns (pandas reads it as NaT). `dtype` follows the
    pandas dtype the column converts to; `distinct_count` counts the non-missing
    values after decoding dictionaries, widening an integer column that holds a
    missing value to float64 as pandas does, and folding `-0.0` into `0.0`; the
    string lengths are set only where pandas would call the column a string
    column. The chunked walk passes no PK, FK or PII inputs, so those fields are
    their defaults."""
    from decoy_engine.profile._walk import observed_shape
    from decoy_engine.profile.arrow._parent import ColumnProfile

    arr = _normalize(column.combine_chunks() if isinstance(column, pa.ChunkedArray) else column)
    t = arr.type
    missing = arrow_missing_mask(arr)
    valid = arr.filter(pc.invert(missing))
    values = valid.dictionary_decode() if pa.types.is_dictionary(t) else valid
    if pa.types.is_float16(values.type):
        values = values.cast(pa.float32())  # no float16 compute kernels; the cast is exact
    null_count = int(pc.sum(missing.cast(pa.int64())).as_py() or 0)
    if pa.types.is_integer(t) and null_count > 0:
        # pandas widens an integer column with a missing value to float64 first.
        values = values.cast(pa.float64(), safe=False)
    if pa.types.is_floating(values.type):
        values = pc.if_else(pc.equal(values, 0.0), pa.scalar(0.0, values.type), values)
    distinct: int | None
    if pa.types.is_null(values.type):
        distinct = 0  # no kernel for the null type; pandas counts zero values
    else:
        try:
            distinct = int(pc.count_distinct(values, mode="only_valid").as_py())
        except pa.ArrowNotImplementedError:
            distinct = None
    avg_length = max_length = None
    if _is_pandas_string(arr, null_count) and len(valid):
        lengths = pc.utf8_length(values).cast(pa.int64())
        avg_length = float(pc.sum(lengths).as_py()) / len(valid)
        max_length = int(pc.max(lengths).as_py())
    rows = len(arr)
    return ColumnProfile(
        name=name,
        dtype=arrow_dtype_label(t, null_count > 0, canonical_dtype_label),
        row_count=rows,
        null_count=null_count,
        distinct_count=distinct,
        sampled=False,
        is_candidate_key_sampled=rows > 0 and distinct == rows,
        declared_pk=False,
        is_fk=False,
        fk_target=None,
        pii_class=None,
        avg_length=avg_length,
        max_length=max_length,
        shape=observed_shape(column.type, source_format),
    )


def _normalize(arr: pa.Array) -> pa.Array:
    """The representation pandas sees, using only types the compute kernels handle:
    an extension type is its storage (as `to_pandas` converts it), a run-end-encoded
    array is decoded, a view type becomes the large type of the same kind, and a
    dictionary keeps its indices over normalized values (float16 widened, as no kernel
    reads it). The float16 type itself is kept for the `dtype` label of a plain column."""
    t = arr.type
    if isinstance(t, pa.BaseExtensionType):
        return _normalize(arr.storage)
    if pa.types.is_run_end_encoded(t):
        try:
            return _normalize(pc.run_end_decode(arr))
        except pa.ArrowNotImplementedError:
            # No decode kernel for view values: normalize the values, then decode.
            values = _normalize(arr.values)
            rebuilt = pa.RunEndEncodedArray.from_arrays(arr.run_ends, values)
            return pc.run_end_decode(rebuilt.slice(arr.offset, len(arr)))
    if pa.types.is_string_view(t):
        return arr.cast(pa.large_string())
    if pa.types.is_binary_view(t):
        return arr.cast(pa.large_binary())
    if pa.types.is_dictionary(t):
        dictionary = _normalize(arr.dictionary)
        if pa.types.is_float16(dictionary.type):
            dictionary = dictionary.cast(pa.float32())
        return pa.DictionaryArray.from_arrays(arr.indices, dictionary)
    return arr


def _is_pandas_string(arr: pa.Array, null_count: int) -> bool:
    """pandas' `is_string_dtype` for the converted column: text with no missing value
    (a missing value makes a plain column object-typed with None), or a dictionary
    of text with a non-empty dictionary."""
    t = arr.type
    if pa.types.is_dictionary(t):
        return is_text(t.value_type) and len(arr.dictionary) > 0
    return is_text(t) and null_count == 0
