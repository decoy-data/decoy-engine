"""Postgres catalog reads: relation columns, name checks and the shape guard.

``read_relation_rows`` is the one catalog query. The snapshot primitive calls it inside its
transaction (type fidelity and the shape guard). ``relation_columns`` calls it in its own
read-only session, before any row is read, so a caller can check declared columns against the
real relation first. The snapshot refuses with ``relation_shape_changed`` when the relation's
column set differs from the one the caller checked (a column added or dropped in between).

Errors carry a code and a ``schema.table`` or ``schema.table#<position>`` location, never a
name taken from the catalog.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from decoy_engine import reasons
from decoy_engine.connectors._postgres_session import (
    ATTACH_ALIAS,
    Deadline,
    PostgresSnapshotError,
    SessionSettings,
    raise_for_interrupt,
    read_session,
    sql_literal,
    validate_identifier,
)

__all__ = ["CATALOG_SQL", "check_relation_shape", "read_relation_rows", "relation_columns"]

# Constant catalog query: no caller text is interpolated. format_type gives
# the declared type (with precision), and the element typtype lets enum
# arrays be told apart from other arrays. attnum orders the columns.
CATALOG_SQL = (
    "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
    "COALESCE(e.typtype, t.typtype)::text, a.attnum::int "
    "FROM pg_attribute a "
    "JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_type t ON t.oid = a.atttypid "
    "LEFT JOIN pg_type e ON e.oid = t.typelem AND t.typcategory = 'A' "
    "WHERE a.attnum > 0 AND NOT a.attisdropped "
    "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
    "AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
)


def read_relation_rows(conn: Any, schema: str, table: str) -> list[tuple[Any, ...]]:
    """Catalog rows ``(schema, table, column, type, typtype, attnum)`` of one exact relation."""
    key = f"{schema}.{table}"
    rows: list[Any] = []
    cause_type = ""
    try:
        rows = conn.execute(
            f"SELECT nspname, relname, attname, fmt, typtype, attnum "
            f"FROM postgres_query({sql_literal(ATTACH_ALIAS)}, ?) "
            "AS q(nspname, relname, attname, fmt, typtype, attnum) "
            "WHERE lower(nspname) = lower(?) AND lower(relname) = lower(?)",
            [CATALOG_SQL, schema, table],
        ).fetchall()
    except Exception as exc:
        cause_type = type(exc).__name__
    if cause_type:
        raise PostgresSnapshotError(
            reasons.connector.CATALOG_READ_FAILED, location=key, cause_type=cause_type
        )
    # DuckDB resolves schema, table and column names case-insensitively, so a
    # source with names differing only by case would export the wrong object
    # without any error. Fetch case-insensitive matches and reject ambiguity,
    # then require an exact-case match so a near miss is never resolved.
    if len({r[0] for r in rows}) > 1 or len({(r[0], r[1]) for r in rows}) > 1:
        raise PostgresSnapshotError(reasons.connector.AMBIGUOUS_NAME, location=key)
    exact = [r for r in rows if r[0] == schema and r[1] == table]
    if not exact:
        raise PostgresSnapshotError(reasons.connector.RELATION_NOT_FOUND, location=key)
    folded: dict[str, int] = {}
    for r in exact:
        folded[r[2].lower()] = folded.get(r[2].lower(), 0) + 1
    # Reject the relation if ANY two of its columns collide case-insensitively,
    # even ones outside this projection. DuckDB folds a case-colliding pair to
    # one name and renames the duplicate with a generated suffix (a + "A" ->
    # a, A_1), which can then shadow a real column like a_1 and export the
    # wrong column with no error. The whole relation is unsafe, so refuse it.
    if any(count > 1 for count in folded.values()):
        raise PostgresSnapshotError(reasons.connector.AMBIGUOUS_NAME, location=key)
    return sorted(exact, key=lambda r: r[5])


def check_relation_shape(rows: Sequence[tuple[Any, ...]], columns: Sequence[str], key: str) -> None:
    """Refuse when the relation's live columns are not exactly ``columns``."""
    if {r[2] for r in rows} != set(columns):
        raise PostgresSnapshotError(reasons.connector.RELATION_SHAPE_CHANGED, location=key)


def relation_columns(
    config: SessionSettings, relations: Sequence[tuple[str, str]]
) -> dict[str, list[str]]:
    """Column names of each ``(schema, table)`` in table order, read before any data row.

    Keyed by ``schema.table``. A column name that is not a strict identifier is refused by its
    1-based position, so the name is never echoed.
    """
    for schema, table in relations:
        validate_identifier(schema, "schema")
        validate_identifier(table, "table")
    keys = [f"{s}.{t}" for s, t in relations]
    if len(set(keys)) != len(keys):
        raise PostgresSnapshotError(reasons.connector.DUPLICATE_RELATION)
    out: dict[str, list[str]] = {}
    failure: PostgresSnapshotError | None = None
    cause_type = ""
    deadline = Deadline(config.deadline_s)
    with read_session(config, deadline) as conn:
        try:
            for (schema, table), key in zip(relations, keys, strict=True):
                names = [r[2] for r in read_relation_rows(conn, schema, table)]
                for pos, name in enumerate(names, start=1):
                    try:
                        validate_identifier(name, "column")
                    except ValueError:
                        failure = PostgresSnapshotError(
                            reasons.connector.COLUMN_NAME_UNSUPPORTED, location=f"{key}#{pos}"
                        )
                    if failure is not None:
                        break
                if failure is not None:
                    break
                out[key] = names
        except PostgresSnapshotError as exc:
            failure = exc
        except Exception as exc:
            cause_type = type(exc).__name__
        if failure is not None:
            cause_type = failure.cause_type
    raise_for_interrupt(deadline, cause_type)
    if failure is not None:
        raise failure
    if cause_type:
        raise PostgresSnapshotError(reasons.connector.CATALOG_READ_FAILED, cause_type=cause_type)
    return out
