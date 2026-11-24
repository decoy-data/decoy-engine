"""The Arrow column walk: the `ColumnProfile` the pandas walk would produce, without pandas.

The chunked first-chunk profile uses it for carried passthrough columns, so their values never
reach pandas (rule R3). The bounded source profile uses it for every reader that holds Arrow
(`walk_arrow_table`), reading the pandas schema metadata for the facts `to_pandas` would have
taken from it. The pandas NaT and dtype-label rules it must match live in
`internal.pandas_compat`, because they decide from Arrow timestamp types and the column-shape
sentry keeps that kind of decision out of this package.
"""

from __future__ import annotations

import dataclasses
import importlib
from typing import Any

import pyarrow as pa

from decoy_engine._arrow_types import is_text
from decoy_engine._field_names import duplicate_names_message
from decoy_engine._pandas_meta import bounded_column_facts
from decoy_engine.internal.pandas_compat import (
    arrow_dtype_label,
    arrow_missing_mask,
    arrow_strings_restore_as_text,
    canonical_dtype_label,
)

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")

# Restored pandas dtypes whose columns pandas treats as text.
_TEXT_LABELS = frozenset({"string", "large_string[pyarrow]"})


def arrow_column_profile(
    name: str,
    column: pa.Array | pa.ChunkedArray,
    *,
    source_format: str | None = None,
    pandas_dtype: str | None = None,
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
    their defaults.

    `pandas_dtype` is the dtype label the schema metadata restores (`Int64`, `string`,
    `int64[pyarrow]`, `period[M]`): the column then follows pandas' masked and extension
    rules. Only an Arrow null is missing (no NaN or NaT rule), an integer keeps its width with
    a null in it, text lengths are measured over the valid values, and an interval's distinct
    count is over its (left, right) rows. `None` keeps the plain-column rules above."""
    from decoy_engine.profile._types import ColumnProfile
    from decoy_engine.profile._walk import observed_shape

    arr = _normalize(_one_array(column))
    t = arr.type
    missing = pc.fill_null(pc.is_null(arr), True) if pandas_dtype else arrow_missing_mask(arr)
    valid = arr.filter(pc.invert(missing))
    values = valid.dictionary_decode() if pa.types.is_dictionary(t) else valid
    if pa.types.is_float16(values.type):
        values = values.cast(pa.float32())  # no float16 compute kernels; the cast is exact
    null_count = int(pc.sum(missing.cast(pa.int64())).as_py() or 0)
    if pa.types.is_integer(t) and null_count > 0 and pandas_dtype is None:
        # pandas widens an integer column with a missing value to float64 first.
        values = values.cast(pa.float64(), safe=False)
    if pa.types.is_floating(values.type):
        values = pc.if_else(pc.equal(values, 0.0), pa.scalar(0.0, values.type), values)
        # NaNs with different IEEE payloads are one value to pandas; fold them to one NaN.
        values = pc.if_else(pc.is_nan(values), pa.scalar(float("nan"), values.type), values)
    distinct: int | None
    if pa.types.is_null(values.type):
        distinct = 0  # no kernel for the null type; pandas counts zero values
    elif pa.types.is_struct(values.type) and (pandas_dtype or "").startswith("interval"):
        distinct = _distinct_rows(values)
    else:
        try:
            distinct = int(pc.count_distinct(values, mode="only_valid").as_py())
        except pa.ArrowNotImplementedError:
            distinct = None
    avg_length = max_length = None
    text = (
        _is_pandas_string(arr, null_count)
        if pandas_dtype is None
        else _restored_text(arr, pandas_dtype)
    )
    if text and len(valid):
        lengths = pc.utf8_length(values).cast(pa.int64())
        avg_length = float(pc.sum(lengths).as_py()) / len(valid)
        max_length = int(pc.max(lengths).as_py())
    rows = len(arr)
    return ColumnProfile(
        name=name,
        dtype=(
            canonical_dtype_label(pandas_dtype)
            if pandas_dtype
            else arrow_dtype_label(t, null_count > 0, canonical_dtype_label)
        ),
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


def _one_array(column: pa.Array | pa.ChunkedArray) -> pa.Array:
    """The column as one array. Dictionary chunks keep their own dictionaries, so a narrow index
    type (`int8`) cannot hold the union of them: widen it first, as pandas' categorical does."""
    if not isinstance(column, pa.ChunkedArray):
        return column
    t = column.type
    if pa.types.is_dictionary(t) and t.index_type.bit_width < 32 and column.num_chunks > 1:
        column = column.cast(pa.dictionary(pa.int32(), t.value_type, t.ordered))
    return column.combine_chunks()


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
    if is_text(t) and arrow_strings_restore_as_text():
        return True  # `future.infer_string`: a plain Arrow string column is a string dtype
    return is_text(t) and null_count == 0


def _restored_text(arr: pa.Array, pandas_dtype: str) -> bool:
    """A restored `string` or `large_string[pyarrow]` column is text even with a missing value."""
    return pandas_dtype in _TEXT_LABELS and is_text(arr.type)


def _distinct_rows(values: pa.Array) -> int:
    """Distinct rows of a struct array (an interval's left and right), as pandas counts them."""
    table = pa.Table.from_struct_array(values)
    return int(table.group_by(table.column_names).aggregate([]).num_rows)


def walk_arrow_table(
    table: pa.Table,
    *,
    table_name: str,
    declared_pk_cols: frozenset[str],
    fk_specs: dict[str, tuple[str, str]],
    total_row_count: int | None,
    source_format: str | None,
) -> Any:
    """The `TableProfile` `walk_dataframe` gives a bounded sample, computed from Arrow.

    `table` is the sample; `total_row_count` is the source's true count (`None` when the table
    is the whole source). The pandas metadata is read once for the whole table. A stored index
    field is not a column. The walk draws nothing from an rng, so profiling several tables in
    one call leaves each the state it would have had alone.

    Raises:
        ValueError: if two fields share a name (the shared value-free text).
    """
    from decoy_engine.profile._types import TableProfile, column_key_fields

    message = duplicate_names_message(table_name, table.schema.names)
    if message is not None:
        raise ValueError(message)
    names, hints = bounded_column_facts(table.schema)
    total = total_row_count if total_row_count is not None else table.num_rows
    sampled = total > table.num_rows
    columns = []
    for name in names:
        column = arrow_column_profile(
            name,
            table.column(name),
            source_format=source_format,
            pandas_dtype=hints.get(name),
        )
        keys = column_key_fields(
            name,
            row_count=total,
            distinct_count=column.distinct_count,
            sampled=sampled,
            declared_pk_cols=declared_pk_cols,
            fk_specs=fk_specs,
        )
        columns.append(
            dataclasses.replace(column, row_count=total, sampled=sampled, **keys._asdict())
        )
    return TableProfile(name=table_name, row_count=total, columns=tuple(columns))
