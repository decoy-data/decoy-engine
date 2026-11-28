"""Profile reader for a table the caller holds in memory (a supplied `pa.Table`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa

from decoy_engine._execution_error import source_column_unrepresentable
from decoy_engine.internal.pandas_compat import arrow_to_frame
from decoy_engine.profile._readers import RowCount

if TYPE_CHECKING:
    import pandas as pd


def _frame_of(table: pa.Table) -> pd.DataFrame:
    """`table` as a DataFrame; a column pandas cannot hold is a coded error naming the column."""
    return arrow_to_frame(table, on_unrepresentable=source_column_unrepresentable())


@dataclass(frozen=True)
class ResidentTableSource:
    """`ProfileSource` over a table the caller holds in memory and no descriptor describes.

    The count and schema come from the table; the bounded sample is sliced before any pandas
    conversion, so a large resident table is never copied whole to profile it.
    """

    table: pa.Table

    def row_count(self) -> RowCount:
        return RowCount(self.table.num_rows, exact=True)

    def schema(self) -> pa.Schema:
        return self.table.schema

    def sample_frame(self, sample_rows: int) -> pd.DataFrame:
        return _frame_of(self.table.slice(0, sample_rows))

    def to_frame(self) -> pd.DataFrame:
        return _frame_of(self.table)
