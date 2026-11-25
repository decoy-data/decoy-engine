"""The one Arrow-to-pandas conversion the profile readers use for a source sample or table."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine._arrow_types import temporal_bounds

if TYPE_CHECKING:
    import pandas as pd

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")


def profile_frame(table: pa.Table) -> pd.DataFrame:
    """`table` as a DataFrame; a value pandas cannot hold (a date past year 9999, a
    sub-microsecond time) is read as null. Profiling runs before any route, so it must not fail
    first with pandas' error, which quotes the value, and no statistic may carry the value
    either; the route then raises its own coded error, or the native route runs.

    Temporal cells are checked on their physical integer before any conversion, because pandas
    metadata naming an Arrow-backed dtype makes `to_pandas` keep a bad value instead of failing.
    Only the bad cell is nulled. A column is replaced on the original table, so a stored pandas
    index and the schema metadata stay as they were."""
    for position, column in enumerate(table.columns):
        bounds = temporal_bounds(column.type)
        if bounds is not None:
            table = table.set_column(
                position, table.schema.field(position), _bounded(column, *bounds)
            )
    try:
        return table.to_pandas()
    except (ValueError, OverflowError):
        pass
    # Only a type with no per-cell bound (a nested column) gets here: null it whole.
    for position, column in enumerate(table.columns):
        try:
            column.to_pandas()
        except (ValueError, OverflowError):
            empty = pa.chunked_array([pa.nulls(len(column), column.type)])
            table = table.set_column(position, table.schema.field(position), empty)
    return table.to_pandas()


def _bounded(column: pa.ChunkedArray, low: int, high: int, step: int) -> pa.ChunkedArray:
    """`column` with each cell whose physical integer is outside `[low, high]` or off `step`
    nulled. The integer is read without converting a value, so nothing wraps or overflows."""
    kind = column.type
    physical = column.cast(pa.int32() if kind.bit_width == 32 else pa.int64())
    ok = pc.and_(pc.greater_equal(physical, low), pc.less_equal(physical, high))
    if step > 1:
        ok = pc.and_(ok, pc.equal(pc.multiply(pc.divide(physical, step), step), physical))
    if pc.all(ok).as_py() is not False:
        return column
    return pc.if_else(ok, column, pa.scalar(None, kind))
