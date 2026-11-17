"""Postgres snapshot-to-Parquet materialization primitive.

Reads a fixed, structured selection of Postgres relations through DuckDB's
``postgres`` extension (the "postgres scanner",
https://duckdb.org/docs/stable/core_extensions/postgres/overview) and stages
each relation as one Parquet file. This is a materialization step, not a
streaming connector: DuckDB owns the wire protocol and type mapping, Decoy
owns only the narrow, read-only, structured selection-to-Parquet step.

Pinned guarantees (each has a test in ``tests/connectors/test_postgres_snapshot*``):

* One snapshot per call. All relations are exported inside one DuckDB
  transaction over one attached database, so a parent/child pair that is
  mutated between two exports is either wholly in or wholly out of the staged
  set. Postgres serves this from a single REPEATABLE READ snapshot that the
  scanner's parallel ctid workers import.
* Structured input only. Callers pass identifiers and column names, never SQL.
  Every identifier is validated against a strict pattern and then quoted; no
  value is concatenated into SQL unquoted.
* Deterministic output. Each export is ``ORDER BY`` the caller's key columns
  followed by every other projected column, ``NULLS LAST``, so equal source
  state yields identical Parquet even for keyless relations or non-unique
  keys. DuckDB's scan order is not relied on.
* Atomic publish. Files are written to a private staging directory and the
  directory is renamed into place only after every relation succeeded. Any
  failure, timeout, or interrupt removes staged and spill files and returns
  nothing.
* Type fidelity. A column whose Postgres type DuckDB cannot carry without
  loss is rejected with a coded error before any row is read. DuckDB's scanner
  otherwise degrades several types silently (unbounded or >38 digit numeric to
  DOUBLE, numeric NaN to NULL, far timestamps wrapping around int64,
  infinity to a sentinel), which a masking pipeline must never ingest.
* Offline extension. The extension is loaded from a caller-supplied directory
  with auto-install and auto-load disabled. The primitive never reaches the
  network to fetch it, and fails closed with a coded error if it is absent or
  incompatible.
* No leaks. DuckDB echoes the full connection string in connect errors, so
  raw exception text is never forwarded or chained. Errors and logs carry a
  code, a relation or column location, and the exception type only.

The library does not know its callers: it takes a resolved DSN as a
``SecretStr`` and knows nothing about accounts or credential references.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    field_validator,
    model_validator,
)

from decoy_engine import fileaccess, reasons
from decoy_engine.connectors._postgres_session import (
    ATTACH_ALIAS,
    Deadline,
    PostgresSnapshotError,
    quote_ident,
    raise_for_interrupt,
    read_session,
    sql_literal,
    validate_identifier,
)
from decoy_engine.connectors.postgres_catalog import check_relation_shape, read_relation_rows
from decoy_engine.reasons import Outcome

__all__ = [
    "POSTGRES_SOURCE_USAGE_CODES",
    "PostgresSnapshotConfig",
    "PostgresSnapshotError",
    "RelationSelection",
    "snapshot_tables_to_parquet",
    "validate_identifier",
]

_log = logging.getLogger(__name__)


def _usage_codes() -> frozenset[str]:
    return frozenset(
        spec.code
        for spec in reasons.specs()
        if spec.namespace == "connector"
        and any(r.outcome is Outcome.CONFIGURATION for r in spec.rules)
    )


# Codes a user can repair by changing the config or the database (exit 1 in the CLI). The
# registry outcome is the one source, so a new usage code needs no second list.
POSTGRES_SOURCE_USAGE_CODES: frozenset[str] = _usage_codes()

# DuckDB TIMESTAMP is int64 microseconds. Postgres allows years up to 294276
# AD, which wraps silently on the scanner's int64 conversion. The guard window
# keeps a wide safety margin inside DuckDB's range and still covers Postgres'
# whole BC range.
_TS_MIN = "4713-01-01 BC"
_TS_MAX = "290000-12-31 23:59:59"

_NUMERIC_MAX_PRECISION = 38  # DuckDB DECIMAL ceiling

# Scalar Postgres types the scanner carries without loss, keyed by the
# ``format_type`` text with any ``(n)`` length suffix removed. ``character(n)``
# is absent on purpose: the scanner trims its blank padding, which is a value
# change.
_PLAIN_TYPES = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "real",
        "double precision",
        "boolean",
        "text",
        "character varying",
        '"char"',
        "uuid",
        "json",
        "jsonb",
        "bytea",
        "time without time zone",
    }
)
_DATE = "date"
_TIMESTAMPS = frozenset({"timestamp without time zone", "timestamp with time zone"})
_NUMERIC_RE = re.compile(r"^numeric\((\d+),(\d+)\)\Z")
_LEN_SUFFIX_RE = re.compile(r"\(\d+\)\Z")


class PostgresSnapshotConfig(BaseModel):
    """Connection and resource policy for one snapshot call. No SQL field."""

    # hide_input_in_errors: a ValidationError would otherwise echo the rejected
    # input, which for these models can be a DSN or attacker-shaped text.
    model_config = ConfigDict(
        extra="forbid", frozen=True, arbitrary_types_allowed=True, hide_input_in_errors=True
    )

    dsn: SecretStr
    extension_directory: Path = Field(
        description="Directory holding the bundled DuckDB postgres extension. Never installed from the network."
    )
    memory_limit: str = Field(pattern=r"^\d+(\.\d+)?\s?(KB|MB|GB|TB|KiB|MiB|GiB|TiB|B)$")
    temp_directory: Path
    threads: int = Field(ge=1, le=256)
    row_group_size: int = Field(ge=1_000, le=10_000_000)
    statement_timeout_s: int = Field(ge=1)
    deadline_s: int = Field(ge=1)


class RelationSelection(BaseModel):
    """One relation to stage. Identifiers only; there is no predicate field."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_name: str = Field(alias="schema")
    table: str
    columns: list[str] = Field(min_length=1)
    order_by: list[str] = Field(default_factory=list)
    # True when ``columns`` is the whole relation as the caller checked it. The snapshot then
    # refuses if the live column set differs inside the transaction.
    whole_relation: StrictBool = False

    @field_validator("schema_name")
    @classmethod
    def _v_schema(cls, v: str) -> str:
        return validate_identifier(v, "schema")

    @field_validator("table")
    @classmethod
    def _v_table(cls, v: str) -> str:
        return validate_identifier(v, "table")

    @field_validator("columns", "order_by")
    @classmethod
    def _v_cols(cls, v: list[str]) -> list[str]:
        for c in v:
            validate_identifier(c, "column")
        if len(set(v)) != len(v):
            raise ValueError("duplicate column")
        return v

    @model_validator(mode="after")
    def _order_subset(self) -> RelationSelection:
        if not set(self.order_by) <= set(self.columns):
            raise ValueError("order_by must be a subset of columns")
        return self

    @property
    def key(self) -> str:
        return f"{self.schema_name}.{self.table}"


# ----- type fidelity ------------------------------------------------------


def _classify(type_text: str, typtype: str) -> str | None:
    """Return a guard class for a supported type, or None if unsupported.

    Classes: ``plain`` (no guard needed), ``array`` (lower-bound guard), ``date``, ``timestamp``,
    ``numeric`` (bounded <= 38 digits; NaN guard).
    """
    base = type_text
    is_array = False
    while base.endswith("[]"):
        base = base[:-2]
        is_array = True
    base_nolen = _LEN_SUFFIX_RE.sub("", base)
    if typtype == "e" or base_nolen in _PLAIN_TYPES:
        # Arrays need a lower-bound guard: the scanner drops a non-1 lower
        # bound, so '[0:2]={..}' would export with its indexing lost.
        return "array" if is_array else "plain"
    # Temporal and numeric element guards run on scalar columns only. An array
    # of them would need an unnest guard, so it is rejected instead.
    if is_array:
        return None
    if base == _DATE:
        return "date"
    if _LEN_SUFFIX_RE.sub("", base) in _TIMESTAMPS:
        return "timestamp"
    m = _NUMERIC_RE.fullmatch(base)
    if m and int(m.group(1)) <= _NUMERIC_MAX_PRECISION:
        return "numeric"
    return None


def _check_types(conn: Any, sel: RelationSelection) -> dict[str, str]:
    """Verify columns exist and are lossless. Returns {column: guard class}."""
    rows = read_relation_rows(conn, sel.schema_name, sel.table)
    if sel.whole_relation:
        check_relation_shape(rows, sel.columns, sel.key)
    declared = {r[2]: (r[3], r[4]) for r in rows}
    classes: dict[str, str] = {}
    for col in sel.columns:
        if col not in declared:
            raise PostgresSnapshotError(
                reasons.connector.COLUMN_NOT_FOUND, location=f"{sel.key}.{col}"
            )
        cls = _classify(*declared[col])
        if cls is None:
            raise PostgresSnapshotError(
                reasons.connector.UNSUPPORTED_COLUMN_TYPE, location=f"{sel.key}.{col}"
            )
        classes[col] = cls
    return classes


def _guard_values(conn: Any, sel: RelationSelection, classes: dict[str, str]) -> None:
    """Reject values DuckDB would alter silently, before any export.

    Runs through ``postgres_query`` on the same attached connection and inside
    the same transaction as the exports, so it is expected to read from that
    transaction's snapshot. That participation is not gate-tested (gate 1
    exercises the ATTACH scan path), and a spike showed it for a trivial query
    only. Until a mutation test covers it, treat a value changing between the
    guard and a later export as an unverified edge, tracked for Slice 2. The
    SQL is built only from validated, quoted identifiers and fixed literals.
    """
    checks: list[tuple[str, str]] = []
    for col, cls in classes.items():
        qc = quote_ident(col)
        if cls == "date":
            cond = f"NOT isfinite({qc})"
        elif cls == "timestamp":
            cond = (
                f"(NOT isfinite({qc}) OR {qc} < '{_TS_MIN}'::timestamp "
                f"OR {qc} > '{_TS_MAX}'::timestamp)"
            )
        elif cls == "array":
            # array_lower is NULL for empty arrays, which are fine. Postgres
            # allows at most 6 dimensions.
            cond = " OR ".join(f"array_lower({qc}, {d}) <> 1" for d in range(1, 7))
        elif cls == "numeric":
            # DuckDB's scanner maps numeric NaN to NULL by default.
            cond = f"{qc} = 'NaN'::numeric"
        else:
            continue
        checks.append((col, f"count(*) FILTER (WHERE {qc} IS NOT NULL AND {cond})"))
    if not checks:
        return
    sql = (
        "SELECT "
        + ", ".join(f"{expr} AS g{i}" for i, (_, expr) in enumerate(checks))
        + f" FROM {quote_ident(sel.schema_name)}.{quote_ident(sel.table)}"
    )
    counts: Any = None
    cause_type = ""
    try:
        counts = conn.execute(
            f"SELECT * FROM postgres_query({sql_literal(ATTACH_ALIAS)}, ?)", [sql]
        ).fetchone()
    except Exception as exc:
        cause_type = type(exc).__name__
    if cause_type:
        raise PostgresSnapshotError(
            reasons.connector.VALUE_GUARD_FAILED, location=sel.key, cause_type=cause_type
        )
    for (col, _), n in zip(checks, counts or (), strict=True):
        if n:
            raise PostgresSnapshotError(
                reasons.connector.VALUE_NOT_REPRESENTABLE, location=f"{sel.key}.{col}"
            )


# ----- export -------------------------------------------------------------


def _order_clause(sel: RelationSelection) -> str:
    # Key columns first, then every other projected column as tiebreaker, so
    # keyless relations and non-unique keys still export in one total order.
    ordered = list(sel.order_by) + [c for c in sel.columns if c not in sel.order_by]
    return ", ".join(f"{quote_ident(c)} ASC NULLS LAST" for c in ordered)


def _export_relation(conn: Any, sel: RelationSelection, target: Path, row_group_size: int) -> None:
    cols = ", ".join(quote_ident(c) for c in sel.columns)
    src = f"{quote_ident(ATTACH_ALIAS)}.{quote_ident(sel.schema_name)}.{quote_ident(sel.table)}"
    conn.execute(
        f"COPY (SELECT {cols} FROM {src} ORDER BY {_order_clause(sel)}) "
        f"TO {sql_literal(str(target))} (FORMAT parquet, ROW_GROUP_SIZE {int(row_group_size)})"
    )


def _export_all(
    conn: Any,
    config: PostgresSnapshotConfig,
    selections: list[RelationSelection],
    stage_dir: Path,
    deadline: Deadline,
) -> dict[str, Path]:
    """Check and export every selection in one transaction, with the failure policy applied."""
    staged: dict[str, Path] = {}
    failure: PostgresSnapshotError | None = None
    cause_type = ""
    try:
        conn.execute("BEGIN TRANSACTION")
        # Validate every relation first so a late type rejection never
        # follows a long export. All of this reads the same snapshot.
        plans = [(sel, _check_types(conn, sel)) for sel in selections]
        for sel, classes in plans:
            _guard_values(conn, sel, classes)
        for sel, _ in plans:
            target = stage_dir / f"{sel.schema_name}.{sel.table}.parquet"
            _export_relation(conn, sel, target, config.row_group_size)
            staged[sel.key] = target
        conn.execute("COMMIT")
    except PostgresSnapshotError as exc:
        failure = exc
    except Exception as exc:
        cause_type = type(exc).__name__
    if failure is not None:
        cause_type = failure.cause_type
    # Raised here, after the except blocks closed, so no error keeps DuckDB's text as context.
    raise_for_interrupt(deadline, cause_type)
    if failure is not None:
        raise failure
    if cause_type:
        raise PostgresSnapshotError(reasons.connector.EXPORT_FAILED, cause_type=cause_type)
    return staged


def snapshot_tables_to_parquet(
    config: PostgresSnapshotConfig,
    selections: list[RelationSelection],
    dest_dir: Path,
) -> dict[str, Path]:
    """Stage every selection from ONE snapshot; return ``{schema.table: parquet_path}``.

    One ATTACH, one transaction across all selections, one ordered COPY per
    relation. A single-relation snapshot is this same call with one selection.
    On any failure, timeout, or interrupt nothing is published and every
    staged and spill file is removed. A DuckDB interrupt that is not the deadline
    (Ctrl-C) is re-raised as ``KeyboardInterrupt``.
    """
    fileaccess.require_ambient("the Postgres snapshot")
    if not selections:
        raise PostgresSnapshotError(reasons.connector.NO_SELECTIONS)
    keys = [s.key for s in selections]
    if len(set(keys)) != len(keys):
        raise PostgresSnapshotError(reasons.connector.DUPLICATE_RELATION)

    run_id = uuid.uuid4().hex
    dest_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = dest_dir / f".stage-{run_id}"
    final_dir = dest_dir / f"snapshot-{run_id}"
    stage_dir.mkdir(mode=0o700)

    published = False
    deadline = Deadline(config.deadline_s)
    try:
        with read_session(config, deadline) as conn:
            staged = _export_all(conn, config, selections, stage_dir, deadline)
        os.replace(stage_dir, final_dir)
        published = True
        _log.info("postgres_snapshot published relations=%d", len(staged))
        return {k: final_dir / p.name for k, p in staged.items()}
    except PostgresSnapshotError as failure:
        code, location = failure.code, failure.location
        _log.warning("postgres_snapshot failed code=%s location=%s", code, location)
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
        if not published:
            shutil.rmtree(final_dir, ignore_errors=True)
