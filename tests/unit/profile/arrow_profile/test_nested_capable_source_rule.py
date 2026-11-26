"""One rule decides which sources hand the profile an Arrow schema and fail with a closed label."""

from __future__ import annotations

import pyarrow as pa

from decoy_engine.profile._readers_resident import ResidentTableSource
from decoy_engine.profile._source import _holds_arrow_table, _nested_capable_schema


class _ForeignParquetReader:
    """A reader outside the three built-in Parquet classes that implements the protocol."""

    def __init__(self, schema: pa.Schema) -> None:
        self._schema = schema

    def schema(self) -> pa.Schema:
        return self._schema

    def sample_table(self, sample_rows: int) -> pa.Table:
        return self._schema.empty_table()


class _SchemaOnlyReader:
    """A CSV-like reader: it has a schema but no Arrow sample."""

    def schema(self) -> pa.Schema:
        return pa.schema([pa.field("a", pa.int64())])


def test_a_reader_with_the_protocol_gets_its_schema_and_the_boundary() -> None:
    schema = pa.schema([pa.field("a", pa.list_(pa.int64()))])
    reader = _ForeignParquetReader(schema)
    assert _holds_arrow_table(reader)  # type: ignore[arg-type]
    assert _nested_capable_schema(reader) == schema  # type: ignore[arg-type]


def test_a_resident_table_gets_its_schema_and_the_boundary() -> None:
    table = pa.table({"a": [1, 2]})
    reader = ResidentTableSource(table)
    assert _holds_arrow_table(reader)
    assert _nested_capable_schema(reader) == table.schema


def test_a_schema_only_reader_gets_neither() -> None:
    reader = _SchemaOnlyReader()
    assert not _holds_arrow_table(reader)  # type: ignore[arg-type]
    assert _nested_capable_schema(reader) is None  # type: ignore[arg-type]
