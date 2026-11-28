"""Profile reader for a table the caller holds in memory (a supplied `pa.Table`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa

from decoy_engine.internal.pandas_compat import table_to_pandas
from decoy_engine.io import check_source_dates
from decoy_engine.profile._readers import RowCount

if TYPE_CHECKING:
    import pandas as pd


def _frame_of(table: pa.Table) -> pd.DataFrame:
    """`table` as a DataFrame; a column pandas cannot hold (a date past year 9999, a
    sub-microsecond time) is profiled as text, so the route that never converts still runs. Only
    such a column is replaced, on the table itself, so its pandas metadata (the stored index)
    stays."""
    try:
        return table_to_pandas(table)
    except (ValueError, OverflowError):
        for position, name in enumerate(table.column_names):
            column = table.column(position)
            try:  # the shared conversion, so an admitted date dictionary is not mistaken for one
                table_to_pandas(pa.Table.from_arrays([column], names=[name]))
            except (ValueError, OverflowError):
                table = table.set_column(position, name, column.cast(pa.string()))
        return table_to_pandas(table)


@dataclass(frozen=True)
class ResidentTableSource:
    """`ProfileSource` over a table the caller holds in memory and no descriptor describes.

    The count and schema come from the table; the bounded sample is sliced before any pandas
    conversion, so a large resident table is never copied whole to profile it.
    """

    table: pa.Table
    name: str = "source"

    def row_count(self) -> RowCount:
        return RowCount(self.table.num_rows, exact=True)

    def schema(self) -> pa.Schema:
        return self.table.schema

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        head = self.table.slice(0, sample_rows)
        return _frame_of(check_source_dates(head, table=self.name))

    def to_frame(self) -> pd.DataFrame:
        return _frame_of(check_source_dates(self.table, table=self.name))
