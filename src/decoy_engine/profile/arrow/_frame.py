"""The one Arrow-to-pandas conversion the profile readers use for a source sample or table."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pyarrow as pa

if TYPE_CHECKING:
    import pandas as pd

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")


def profile_frame(table: pa.Table) -> pd.DataFrame:
    """`table` as a DataFrame; a value pandas cannot hold (a date past year 9999, a
    sub-microsecond time) is read as null. Profiling runs before any route, so it must not fail
    first with pandas' error, which quotes the value, and no statistic may carry the value
    either; the route then raises its own coded error, or the native route runs. A failing
    column is replaced on the original table, so a stored pandas index and the schema metadata
    stay as they were."""
    try:
        return table.to_pandas()
    except (ValueError, OverflowError):
        pass
    for position, column in enumerate(table.columns):
        try:
            column.to_pandas()
        except (ValueError, OverflowError):
            table = table.set_column(position, table.schema.field(position), _holdable(column))
    return table.to_pandas()


def _holdable(column: pa.ChunkedArray) -> pa.ChunkedArray:
    """`column` with every value pandas cannot hold nulled; all of it when that is not enough."""
    kind = column.type
    if pa.types.is_date(kind) or pa.types.is_timestamp(kind):
        year = pc.year(column)
        past = pc.or_(pc.greater(year, 9999), pc.less(year, 1))
        kept = pc.if_else(past, pa.scalar(None, kind), column)
        try:
            kept.to_pandas()
            return kept
        except (ValueError, OverflowError):
            pass
    return pa.chunked_array([pa.nulls(len(column), kind)])
