"""A one-row DuckDB read must finish its result before the connection registers more data.

DuckDB 2.x raises ResourceInUseException on `conn.register()` while an earlier SELECT result
is unfinished (`fetchone()` leaves it so); 1.x allowed it. The post-scan gate turned that
into `check_error` and blocked every run that declared a relationship. These tests pass on
1.x with or without the fix and fail on 2.x without it.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from decoy_engine._duckdb_read import fetch_scalar
from decoy_engine.execution.out_of_core._duckdb import connect_duckdb
from decoy_engine.profiling._scan_integrity import KeyBatches, key_facts


def _keys(values: list[int | None]) -> KeyBatches:
    table = pa.table({"k0": pa.array(values, type=pa.int64())})
    return KeyBatches(table.schema, lambda: iter(table.to_batches()), bounded=True)


def test_key_facts_loads_child_after_parent_counts(tmp_path: Path) -> None:
    facts = key_facts(
        _keys([1, 2, 2, None]),
        [_keys([1, 2, 3, None])],
        scratch=tmp_path,
        memory_limit="256MB",
    )
    assert facts.status == "checked"
    assert (facts.parent_rows, facts.parent_null_key_rows, facts.parent_duplicate_excess) == (
        4,
        1,
        1,
    )
    assert (facts.children[0].orphan_rows, facts.children[0].null_key_rows) == (1, 1)


def test_fetch_scalar_leaves_connection_free_to_register(tmp_path: Path) -> None:
    conn = connect_duckdb(temp_dir=tmp_path, memory_limit="256MB")
    try:
        assert fetch_scalar(conn.execute("SELECT 41 + 1")) == 42
        conn.register("later", pa.table({"a": [1]}))
        assert conn.execute("SELECT count(*) FROM later").fetchall() == [(1,)]
    finally:
        conn.close()
