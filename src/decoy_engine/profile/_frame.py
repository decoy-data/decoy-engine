"""The one Arrow-to-pandas conversion the profile readers use for a source sample or table."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    import pandas as pd


def profile_frame(table: pa.Table) -> pd.DataFrame:
    """`table` as a DataFrame; a column pandas cannot hold (a date past year 9999, a
    sub-microsecond time) is profiled as text. Profiling runs before any route, so it must not
    fail first with pandas' error, which quotes the value; the route then raises its own coded
    error, or the native route runs."""
    try:
        return table.to_pandas()
    except (ValueError, OverflowError):
        columns = []
        for column in table.columns:
            try:
                column.to_pandas()
            except (ValueError, OverflowError):
                column = column.cast(pa.string())
            columns.append(column)
        return pa.Table.from_arrays(columns, names=table.column_names).to_pandas()
