"""The bounded Arrow sample: the head of a reader's batches as a table, and the reader contract.

A reader that already holds Arrow hands the profile a `pa.Table`; the profile walks it with
`pyarrow.compute` and never converts it to pandas.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

import pyarrow as pa


def head_table_from_batches(
    batches: Iterable[pa.RecordBatch], sample_rows: int, schema: pa.Schema
) -> pa.Table:
    """Collect batches until `sample_rows` rows are gathered, as a table with `schema`.

    Stops reading as soon as the row target is met, so an arbitrarily large source yields
    only `<= sample_rows` decoded rows. An empty source returns an empty table that carries
    the schema, metadata included, so the walk still emits one profile per column."""
    collected: list[pa.RecordBatch] = []
    gathered = 0
    for batch in batches:
        collected.append(batch)
        gathered += batch.num_rows
        if gathered >= sample_rows:
            break
    if not collected:
        return schema.empty_table()
    table = pa.Table.from_batches(collected, schema=schema)
    return table.slice(0, sample_rows) if table.num_rows > sample_rows else table


@runtime_checkable
class ArrowSampleSource(Protocol):
    """A profile reader that holds Arrow (local, S3 or GCS Parquet, a resident table)."""

    def schema(self) -> pa.Schema: ...

    def sample_table(self, sample_rows: int) -> pa.Table:
        """Exactly `sample_rows` rows when the source holds that many; fewer only when the
        read reached the end of the source. Schema metadata is kept."""
        ...
