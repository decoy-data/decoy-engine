"""The Postgres connector's one-row DuckDB reads leave the connection free to register again.

DuckDB 2.x raises ResourceInUseException on `conn.register()` while an earlier SELECT result is
unfinished, and `fetchone()` leaves one so. The real postgres_scanner is not available offline,
so `_StrictConn` models only that rule. No server is needed; the tests fail on `fetchone()`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from decoy_engine.connectors import _postgres_session as session
from decoy_engine.connectors import postgres_snapshot as snapshot


class _Cursor:
    def __init__(self, conn: _StrictConn, rows: list[tuple[Any, ...]]) -> None:
        self._conn = conn
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        self._conn.unfinished = True
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        self._conn.unfinished = False
        return self._rows


class _StrictConn:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.unfinished = False
        self._row = row

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        return _Cursor(self, [self._row])

    def register(self, name: str, obj: Any) -> None:
        if self.unfinished:
            raise RuntimeError("ResourceInUseException")


def test_load_postgres_extension_drains_its_read(tmp_path: Path) -> None:
    conn = _StrictConn((True, str(tmp_path / "pg.duckdb_extension")))
    session.load_postgres_extension(conn, tmp_path)
    conn.register("later", object())


def test_guard_values_drains_its_read() -> None:
    conn = _StrictConn((0,))
    sel = SimpleNamespace(schema_name="public", table="t", key="public.t")
    snapshot._guard_values(conn, sel, {"d": "date"})  # type: ignore[arg-type]
    conn.register("later", object())
