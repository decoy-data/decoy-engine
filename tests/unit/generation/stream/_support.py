"""Shared helpers for the GEN-STREAM-ALL stream tests (test-side only)."""

from __future__ import annotations

import hashlib
from typing import Any

import pyarrow as pa

from tests.parity import _f0_fixtures as fx

LEGACY_TEN = (
    "first_name",
    "last_name",
    "name",
    "prefix",
    "suffix",
    "city",
    "state",
    "country",
    "job",
    "company",
)


def faker_config(faker_type: str, rows: int, *, null_probability: float = 0.0) -> dict[str, Any]:
    col: dict[str, Any] = {"name": "v", "type": "faker", "faker_type": faker_type}
    if null_probability:
        col["null_probability"] = null_probability
    return fx.config([fx.table("t", rows, [col])])


def table_digest(table: pa.Table) -> str:
    """sha256 over column names and cell text; a null has its own marker."""
    h = hashlib.sha256()
    for name in table.column_names:
        h.update(name.encode())
        h.update(b"\x00")
        for value in table.column(name).to_pylist():
            h.update(b"\xff" if value is None else str(value).encode())
            h.update(b"\x1f")
    return h.hexdigest()


def ipc_bytes(table: pa.Table) -> bytes:
    """The Arrow IPC stream of `table` as one chunk: every buffer, bytes under null slots too."""
    combined = table.replace_schema_metadata(None).combine_chunks()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, combined.schema) as writer:
        writer.write_table(combined)
    return bytes(sink.getvalue().to_pybytes())
