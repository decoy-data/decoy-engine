"""Cross-version pandas compatibility helpers.

CONTRACT (audit M5, 2026-06-12): dtype labels emitted into persisted
payloads (ColumnProfile, distribution snapshots) feed user-held snapshot
digests, so they must not drift when the pandas version changes. pandas
3 made ``str`` the default inferred string dtype where pandas 1.5-2.x
inferred ``object``; reporting the new label verbatim silently broke
every pre-existing baseline digest.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any, Final, NoReturn

import numpy as np
import pandas as pd
import pyarrow as pa

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


# A value pandas cannot hold raises ValueError (a date past year 9999; ArrowInvalid is a subclass,
# as is a sub-microsecond time64), OverflowError, or a bare ArrowException (a string with invalid
# UTF-8: "Wrapping <cell text> failed"). Every one quotes the cell.
_UNREPRESENTABLE: Final = (pa.ArrowException, ValueError, OverflowError)


def _is_resource_failure(exc: BaseException) -> bool:
    """Memory pressure and a full disk keep their own type: they say nothing about a value."""
    from decoy_engine.fileaccess import passes_by_type

    return isinstance(exc, Exception) and passes_by_type(exc)


_Mapper = Callable[[pa.DataType], pd.api.extensions.ExtensionDtype | None]

# The callback is told the failing column, or None when no single column reproduces the failure.
_OnUnrepresentable = Callable[[str | None], NoReturn]


def _fail(on_unrepresentable: Callable[[Any], NoReturn], column: str | None) -> NoReturn:
    on_unrepresentable(column)
    raise TypeError("on_unrepresentable must raise")


def _first_failing_column(table: pa.Table, types_mapper: _Mapper | None) -> str | None:
    """The first column that does not convert alone, or None when every one does.

    A recognized conversion failure counts as that column failing: its text may quote a cell and
    is dropped here, never chained. A resource failure, or any other exception, propagates as
    itself.
    """
    for position, name in enumerate(table.column_names):
        try:
            table.column(position).to_pandas(types_mapper=types_mapper)
        except _UNREPRESENTABLE as exc:
            if _is_resource_failure(exc):
                raise
            return name
    return None


def _no_widening(widen: bool) -> None:
    if widen:
        raise NotImplementedError("widening a column pandas cannot hold is not available yet")


def arrow_to_frame(
    table: pa.Table,
    *,
    on_unrepresentable: _OnUnrepresentable,
    widen: bool = False,
    types_mapper: _Mapper | None = None,
    ignore_metadata: bool = False,
) -> pd.DataFrame:
    """Experimental: the one Arrow-to-pandas conversion of a table (source-read boundary, S1b).

    A column pandas cannot hold calls `on_unrepresentable(column)` (None when no single column
    reproduces the failure) after the conversion's own
    handler has closed, so the coded error it raises carries no pandas or Arrow text (which
    quotes the value). `ignore_metadata` keeps every physical field a plain column under its own
    name, instead of restoring a stored pandas index. Code outside this module does not call `to_pandas` itself.
    """
    _no_widening(widen)
    try:
        return table.to_pandas(types_mapper=types_mapper, ignore_metadata=ignore_metadata)
    except _UNREPRESENTABLE as exc:
        if _is_resource_failure(exc):
            raise
    # Probed outside the handler above, so no exception raised from here carries a context
    # that quotes the value.
    _fail(on_unrepresentable, _first_failing_column(table, types_mapper))


def arrow_to_series(
    array: pa.Array | pa.ChunkedArray,
    *,
    on_unrepresentable: Callable[[str], NoReturn],
    widen: bool = False,
    types_mapper: _Mapper | None = None,
    name: str = "",
) -> pd.Series:
    """Experimental: `arrow_to_frame` for one column; `name` is what the callback is told."""
    _no_widening(widen)
    try:
        return array.to_pandas(types_mapper=types_mapper)
    except _UNREPRESENTABLE as exc:
        if _is_resource_failure(exc):
            raise
    _fail(on_unrepresentable, name)


def arrow_to_frame_pair(
    source: pa.Table,
    output: pa.Table,
    *,
    on_unrepresentable: _OnUnrepresentable,
    widen: bool = False,
    types_mapper: _Mapper | None = None,
    ignore_metadata: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Experimental: a source table and its output converted together, one rule for both sides."""
    kwargs: dict[str, Any] = {
        "on_unrepresentable": on_unrepresentable,
        "widen": widen,
        "types_mapper": types_mapper,
        "ignore_metadata": ignore_metadata,
    }
    return arrow_to_frame(source, **kwargs), arrow_to_frame(output, **kwargs)


def table_to_pandas_exact_ints(
    table: pa.Table,
    columns: Iterable[str],
    *,
    on_unrepresentable: _OnUnrepresentable,
    types_mapper: _Mapper = exact_int_types_mapper,
    on_unconvertible: Callable[[str], NoReturn] | None = None,
) -> pd.DataFrame:
    """`arrow_to_frame` with the named integer columns kept exact as nullable integer dtypes.

    Plain `to_pandas()` widens an integer column holding any null to float64, which rounds values
    beyond 2**53. Columns not named, or not integer-typed, keep pyarrow's default. A column that
    does not fit its own dtype calls `on_unconvertible(column)` (or `on_unrepresentable` when none
    is given), which must raise.
    """
    df = arrow_to_frame(table, on_unrepresentable=on_unrepresentable)
    for col in columns:
        if col not in table.column_names or not pa.types.is_integer(table.schema.field(col).type):
            continue
        series = arrow_to_series(
            table.column(col),
            on_unrepresentable=on_unconvertible or on_unrepresentable,
            types_mapper=types_mapper,
            name=col,
        )
        # `.array` carries no index, so the assignment is positional even when `df` has a
        # non-default index.
        df[col] = series.array
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
