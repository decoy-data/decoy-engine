"""The bounded Arrow sample: the head of a Parquet reader's batches as a table, and the reader
contract.

A Parquet reader hands the bounded profile the `pa.Table` it converts to pandas. The profile
converts it with `arrow_to_frame`, as the reader's `sample_frame` does; only when that fails on a flat
temporal schema does it read the table column by column (`profile.arrow._recovery`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

import pandas as pd
import pyarrow as pa

from decoy_engine._execution_error import source_column_unrepresentable
from decoy_engine.internal.pandas_compat import arrow_to_frame


def head_table_from_batches(
    batches: Iterable[pa.RecordBatch], sample_rows: int, schema: pa.Schema
) -> pa.Table:
    """Collect batches until `sample_rows` rows are gathered, as a table with `schema`.

    Stops reading as soon as the row target is met, so an arbitrarily large source yields
    only `<= sample_rows` decoded rows. The table's schema is inferred from the batches, so a
    batch's own metadata decides the conversion; only an empty source returns an empty table
    that carries `schema`, so the walk still emits one profile per column."""
    collected: list[pa.RecordBatch] = []
    gathered = 0
    for batch in batches:
        collected.append(batch)
        gathered += batch.num_rows
        if gathered >= sample_rows:
            break
    if not collected:
        return schema.empty_table()
    table = pa.Table.from_batches(collected)
    return table.slice(0, sample_rows) if table.num_rows > sample_rows else table


def sample_table_frame(table: pa.Table) -> pd.DataFrame:
    """A bounded sample as a DataFrame through the one source-read conversion; a column pandas
    cannot hold is a coded error naming it."""
    return arrow_to_frame(table, on_unrepresentable=source_column_unrepresentable())


@runtime_checkable
class ArrowSampleSource(Protocol):
    """A profile reader over Parquet (local, S3 or GCS): its `sample_frame` is `sample_table`
    converted to pandas."""

    def schema(self) -> pa.Schema: ...

    def sample_table(self, sample_rows: int) -> pa.Table:
        """Exactly `sample_rows` rows when the source holds that many; fewer only when the
        read reached the end of the source. Schema metadata is kept."""
        ...
