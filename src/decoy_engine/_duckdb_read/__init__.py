"""The one way to read a single DuckDB row (choke point; sentry: test_duckdb_one_row_reads).

`cursor.fetchone()` leaves a SELECT result unfinished. DuckDB 2.x then refuses the next
`conn.register()` on that connection (ResourceInUseException); 1.x allowed it. Reading every
row finishes the result. This module imports nothing from the package so execution, profiling
and connectors can all use it from the bottom import tier.
"""

from __future__ import annotations

from typing import Any


def fetch_row(cursor: Any) -> Any:
    """The first row of `cursor`, or None when it holds none, with the result drained."""
    rows = cursor.fetchall()
    return rows[0] if rows else None


def fetch_scalar(cursor: Any) -> Any:
    """The first column of the first row of `cursor`, with the result drained."""
    return cursor.fetchall()[0][0]
