"""Cross-version pandas compatibility helpers.

CONTRACT (audit M5, 2026-06-12): dtype labels emitted into persisted
payloads (ColumnProfile, distribution snapshots) feed user-held snapshot
digests, so they must not drift when the pandas version changes. pandas
3 made ``str`` the default inferred string dtype where pandas 1.5-2.x
inferred ``object``; reporting the new label verbatim silently broke
every pre-existing baseline digest.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterable
from typing import Any, Final, NoReturn

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine._arrow_types import is_date_dictionary

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")

# pandas-3 default datetime inference resolution is 'us' where 1.5-2.x
# always produced 'ns'. Resolution is uniform within one pandas version,
# so cross-frame drift comparison loses nothing by pinning the label.
_DATETIME_RES = re.compile(r"^datetime64\[(s|ms|us|ns)(, .+)?\]\Z")


def canonical_dtype_label(dtype: Any) -> str:
    """Stable dtype label across pandas major versions.

    Two pandas-3 inference changes are normalized to their historical
    labels so digests stay byte-stable across the 2.x -> 3.x boundary:
    the DEFAULT inferred string dtype (``str`` -> ``object``) and the
    default datetime resolution (``datetime64[us]`` ->
    ``datetime64[ns]``, timezone suffix preserved). Explicitly-requested
    extension dtypes (``string``, ``string[pyarrow]``, ...) pass through
    unchanged, as do all other dtypes.
    """
    label = str(dtype)
    if label == "str":
        return "object"
    m = _DATETIME_RES.match(label)
    if m:
        return f"datetime64[ns{m.group(2) or ''}]"
    return label


# Arrow integer value pandas reads as NaT in a timestamp or duration column.
_ARROW_INT64_MIN = -(2**63)


def arrow_missing_mask(arr: pa.Array) -> pa.Array:
    """Rows pandas reads as missing: Arrow nulls, NaN, and the int64 minimum in a timestamp."""
    mask = pc.is_null(arr)
    if pa.types.is_floating(arr.type):
        mask = pc.or_(mask, pc.is_nan(arr))
    if pa.types.is_timestamp(arr.type) or pa.types.is_duration(arr.type):
        mask = pc.or_kleene(mask, pc.equal(arr.cast(pa.int64()), _ARROW_INT64_MIN))
    return pc.fill_null(mask, True)


def arrow_dtype_label(t: pa.DataType, has_missing: bool, canonical: Any) -> str:
    """The dtype label pandas gives the column an Arrow column of type `t` converts to."""
    if pa.types.is_integer(t):
        return "float64" if has_missing else str(t)
    if pa.types.is_boolean(t):
        return "object" if has_missing else "bool"
    if pa.types.is_floating(t):
        return {16: "float16", 32: "float32", 64: "float64"}[t.bit_width]
    if pa.types.is_timestamp(t):
        # The pandas dtype names a zone through its tzinfo (`pytz.FixedOffset(330)` for
        # "+05:30"), so ask pyarrow for the dtype it converts to instead of formatting `tz`.
        return str(canonical(str(t.to_pandas_dtype())))
    if pa.types.is_duration(t):
        return f"timedelta64[{t.unit}]"
    if pa.types.is_dictionary(t):
        return "category"
    return "object"


def utc_naive_datetimes(series: pd.Series) -> pd.Series:
    """Coerce to datetimes, drop what does not parse, and express tz-aware values as naive UTC.

    Snapshot datetime stats and the fitted resolution must read values in the same time
    frame, and two machines in different zones must not diverge, so both call this one rule.
    """
    stamps = pd.to_datetime(series, errors="coerce").dropna()
    if getattr(stamps.dtype, "tz", None) is not None:
        stamps = stamps.dt.tz_convert("UTC").dt.tz_localize(None)
    return stamps


# Each Arrow integer type maps to its own same-width, same-signedness nullable pandas dtype, so a
# null-bearing integer column stays exact (no float64 round trip) and keeps its width.
_ARROW_INT_TO_NULLABLE_DTYPE: Final[dict[pa.DataType, type[pd.api.extensions.ExtensionDtype]]] = {
    pa.int8(): pd.Int8Dtype,
    pa.int16(): pd.Int16Dtype,
    pa.int32(): pd.Int32Dtype,
    pa.int64(): pd.Int64Dtype,
    pa.uint8(): pd.UInt8Dtype,
    pa.uint16(): pd.UInt16Dtype,
    pa.uint32(): pd.UInt32Dtype,
    pa.uint64(): pd.UInt64Dtype,
}


def exact_int_types_mapper(arrow_type: pa.DataType) -> pd.api.extensions.ExtensionDtype | None:
    """`to_pandas(types_mapper=...)` hook: the nullable dtype for an Arrow integer type, else None."""
    dtype_cls = _ARROW_INT_TO_NULLABLE_DTYPE.get(arrow_type)
    return dtype_cls() if dtype_cls is not None else None


def _refuse_unholdable(name: str, column: Any) -> NoReturn:
    """Refuse a date column whose referenced entry pandas cannot hold. The error is built from
    the column name and a row count only, so it quotes no value."""
    from decoy_engine.io.bounded_reader import SourceDateUnrepresentableError

    held = len(column) - column.null_count
    raise SourceDateUnrepresentableError(table="working frame", column=name, count=held)


def _referenced_entries(chunk: Any) -> pa.Array:
    """The non-null entries `chunk`'s rows point at, in dictionary order. An entry no row uses
    is not here, so what pandas must hold never depends on it."""
    used = pc.unique(chunk.indices.drop_null())
    used = pc.take(used, pc.sort_indices(used))
    return pc.take(chunk.dictionary, used).drop_null()


def _pandas_categories(categories: pa.Array) -> pd.Index | None:
    """`categories` as a pandas index, or None when pandas cannot hold one of them. INT64_MIN
    is pandas' NaT, and a zone shift near the nanosecond bounds raises; the error is dropped
    unread, because its text can quote the value."""
    if pa.types.is_timestamp(categories.type) and len(categories):
        if pc.any(pc.equal(categories.cast(pa.int64()), _ARROW_INT64_MIN)).as_py():
            return None
    try:
        return pd.Index(categories.to_pandas())
    except (ValueError, OverflowError, pa.ArrowInvalid):
        return None


def _working_categorical(name: str, column: Any) -> pd.Categorical:
    """A pandas categorical for a date dictionary column that passed the checked read.

    Arrow keeps the null entries the repair retains, and pandas refuses a null category, so the
    working copy is built apart from the Arrow source (which keeps its own dictionaries for the
    output). Categories are the non-null entries some row references, in first dictionary
    order: an unused entry never reaches pandas, so a row has one identity whether or not the
    dictionary carries one. A null index or a reference to a null entry is a missing row; codes
    are int64; several chunks unify their categories in first-seen order and share one code per
    value. A column with no chunk has no category and no row. A referenced entry pandas cannot
    hold is refused (`_refuse_unholdable`)."""
    chunks = column.chunks if isinstance(column, pa.ChunkedArray) else [column]
    parts = [_referenced_entries(chunk) for chunk in chunks]
    categories = pc.unique(
        pa.concat_arrays(parts) if parts else pa.array([], column.type.value_type)
    )
    codes = [
        pc.take(pc.index_in(chunk.dictionary, value_set=categories), chunk.indices).cast(pa.int64())
        for chunk in chunks
    ]
    flat = (
        pc.fill_null(pa.chunked_array(codes, pa.int64()), -1).to_numpy()
        if codes
        else np.empty(0, dtype=np.int64)
    )
    index = _pandas_categories(categories)
    if index is None:
        _refuse_unholdable(name, column)
    return pd.Categorical.from_codes(flat, categories=index, ordered=column.type.ordered)


def stored_index_names(table: pa.Table) -> list[str]:
    """The physical fields `table` holds that its pandas metadata stores as the frame index, in
    level order. A name the table lacks (stale metadata, or a projection that dropped the
    level) is not one, and a range index is metadata only. The one resolver for restoring the
    index and for checking row order."""
    listed = (table.schema.pandas_metadata or {}).get("index_columns", [])
    return [
        c for c in dict.fromkeys(x for x in listed if isinstance(x, str)) if c in table.schema.names
    ]


def table_to_pandas(table: pa.Table) -> pd.DataFrame:
    """`table.to_pandas()`, with each date dictionary column built as a working categorical.

    A date dictionary that passed the checked read can hold a null entry (kept for the output)
    that `to_pandas` refuses, so those columns convert through `_working_categorical`. Every
    other column converts as pyarrow does. A stored index level is restored from its physical
    field (`stored_index_names`) in level order, and keeps the display name pyarrow gave it. A
    data column is restored into its own position, so a label that is not a string (an integer,
    a tuple) is not mistaken for a new column."""
    dated = [i for i, t in enumerate(table.schema.types) if is_date_dictionary(t)]
    if not dated:
        return table.to_pandas()
    swapped = table
    for i in dated:
        swapped = swapped.set_column(i, table.schema.names[i], pa.nulls(table.num_rows))
    frame = swapped.to_pandas()
    physical = stored_index_names(table)
    levels = {
        table.schema.names[i]: _working_categorical(table.schema.names[i], table.column(i))
        for i in dated
    }
    if any(name in levels for name in physical):
        arrays = [
            levels[name] if name in levels else frame.index.get_level_values(position)
            for position, name in enumerate(physical)
        ]
        names = list(frame.index.names)
        frame.index = (
            pd.MultiIndex.from_arrays(arrays, names=names)
            if len(arrays) > 1
            else pd.Index(arrays[0], name=names[0])
        )
    position = 0  # among the data columns, which keep the table's order
    for i, name in enumerate(table.schema.names):
        if name in physical:
            continue
        if i in dated:
            frame.isetitem(position, levels[name])
        position += 1
    return frame


def table_to_pandas_exact_ints(
    table: pa.Table,
    columns: Iterable[str],
    *,
    types_mapper: Callable[[pa.DataType], pd.api.extensions.ExtensionDtype | None] = (
        exact_int_types_mapper
    ),
    on_unconvertible: Callable[[str], NoReturn] | None = None,
) -> pd.DataFrame:
    """`table.to_pandas()` with the named integer columns kept exact as nullable integer dtypes.

    Plain `to_pandas()` widens an integer column holding any null to float64, which rounds values
    beyond 2**53. Columns not named, or not integer-typed, keep pyarrow's default. A column that
    does not fit its own dtype calls `on_unconvertible(column)` (which must raise), or re-raises
    the pyarrow error when none is given.
    """
    df = table_to_pandas(table)
    failed = None
    for col in columns:
        if col not in table.column_names or not pa.types.is_integer(table.schema.field(col).type):
            continue
        try:
            series = table.column(col).to_pandas(types_mapper=types_mapper)
        except (pa.lib.ArrowInvalid, OverflowError):
            if on_unconvertible is None:
                raise
            failed = col
            break
        # `.array` carries no index, so the assignment is positional even when `df` has a
        # non-default index.
        df[col] = series.array
    if failed is not None and on_unconvertible is not None:
        on_unconvertible(failed)  # raised outside the except block, so no exception context
    return df


def numeric_cells(series: pd.Series) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(pd.to_numeric(series, errors="coerce").dropna(), dtype=float)


def finite_numeric_cells(series: pd.Series) -> np.ndarray[Any, np.dtype[np.float64]]:
    """The series' numeric cells as floats with nan and +-inf dropped."""
    arr = numeric_cells(series)
    return np.extract(np.isfinite(arr), arr)


# numpy refuses a bin count for a range that is too narrow (1e15 plus noise) or too wide (+-1e308).
_REFUSED = (ValueError, IndexError)


def _right_closed_histogram(
    values: np.ndarray[Any, np.dtype[np.float64]], bins: int, lo: float, hi: float
) -> tuple[Any, Any]:
    """`bins` equal-width bins over `[lo, hi]`, each `(left, right]` and `lo` in the first.

    This is the `pd.cut(include_lowest=True)` rule. When `hi - lo` is finite the edges are
    exactly `np.linspace(lo, hi, bins + 1)`, as in pandas, so a value on a boundary lands in
    the same bin. Only when `hi - lo` overflows (`[-max, max]`) is each edge `lo*(1-t) + hi*t`,
    which never passes float max, with the edges kept nondecreasing. Edges may repeat when the
    range sits at the float floor; the counts still add up.
    """
    if np.isfinite(hi - lo):
        edges = np.linspace(lo, hi, bins + 1)
    else:
        t = np.linspace(0.0, 1.0, bins + 1)
        edges = np.maximum.accumulate(lo * (1.0 - t) + hi * t)
        edges[0], edges[-1] = lo, hi
    codes = np.clip(np.searchsorted(edges, values, side="left") - 1, 0, bins - 1)
    return np.bincount(codes, minlength=bins), edges


def histogram_for_range(
    values: np.ndarray[Any, np.dtype[np.float64]],
    bins: int,
    lo: float,
    hi: float,
    *,
    right_closed: bool = False,
) -> tuple[Any, Any]:
    """Counts and edges over `[lo, hi]`; fewer bins than asked when numpy refuses `bins`.

    A snapshot must not crash on such a column. No error text is kept, so no cell can leak.
    `right_closed` counts as `pd.cut` does and always returns exactly `bins` bins.
    """
    with np.errstate(all="ignore"):
        if right_closed:
            return _right_closed_histogram(values, bins, lo, hi)
        try:
            return np.histogram(values, bins=bins, range=(lo, hi))
        except _REFUSED:
            pass
        good, bad = 1, bins  # `bad` is refused; bisect for the largest accepted count below it
        while bad - good > 1:
            mid = (good + bad) // 2
            try:
                np.histogram(values, bins=mid, range=(lo, hi))
                good = mid
            except _REFUSED:
                bad = mid
        try:
            return np.histogram(values, bins=good, range=(lo, hi))
        except _REFUSED:
            return np.array([values.size]), np.array([lo, hi])
