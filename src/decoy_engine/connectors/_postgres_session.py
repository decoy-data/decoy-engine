"""Shared DuckDB-to-Postgres session helpers for the Postgres connectors.

One place for the facts every Postgres read or write session needs: the coded error, the strict
identifier rule and its quoting, the offline extension load, the read-only attach and the
interrupt and deadline policy. ``postgres_snapshot`` and ``postgres_catalog`` build on it, and
the Postgres target adds ``open_write_session`` here rather than copying these helpers.

Leak rule: DuckDB echoes the full connection string in connect errors, so raw exception text is
never forwarded or chained. Every coded error is raised after its ``except`` block has closed,
so ``__cause__`` and ``__context__`` are both ``None``.
"""

from __future__ import annotations

import re
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from pydantic import SecretStr

from decoy_engine import fileaccess, reasons
from decoy_engine.fileaccess import open_protected_dir
from decoy_engine.sdk import PermanentError

__all__ = [
    "ATTACH_ALIAS",
    "INTERRUPT_CAUSE",
    "Deadline",
    "PostgresSnapshotError",
    "SessionSettings",
    "attach_read_only",
    "load_postgres_extension",
    "open_connection",
    "open_read_session",
    "quote_ident",
    "raise_for_interrupt",
    "raise_setup_failure",
    "read_session",
    "sql_literal",
    "validate_identifier",
]

# Strict on purpose: unquoted-safe Postgres identifiers. Names needing quoted
# oddities (spaces, quotes, unicode) are rejected rather than escaped, so the
# validation boundary and the quoting boundary cannot disagree.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}\Z")

# Alias for the attached database. Fixed, never caller-derived.
ATTACH_ALIAS = "decoy_pg_src"

# Class name DuckDB gives an interrupted statement (``conn.interrupt()`` or Ctrl-C).
INTERRUPT_CAUSE = "InterruptException"


class PostgresSnapshotError(PermanentError):
    """Coded, redacted snapshot failure.

    ``code`` is a stable machine-readable token. ``location`` is a relation
    (``schema.table``) or ``schema.table.column``, never a value or DSN. The
    message is built only from those parts plus an exception type name.
    """

    def __init__(self, code: str, *, location: str = "", cause_type: str = "") -> None:
        self.code = code
        self.location = location
        self.cause_type = cause_type
        parts = [f"postgres_snapshot[{code}]"]
        if location:
            parts.append(f"at {location}")
        if cause_type:
            parts.append(f"cause={cause_type}")
        super().__init__(" ".join(parts))


class SessionSettings(Protocol):
    """What a read session needs from a connection config (read-only attributes)."""

    @property
    def dsn(self) -> SecretStr: ...
    @property
    def extension_directory(self) -> Path: ...
    @property
    def memory_limit(self) -> str: ...
    @property
    def temp_directory(self) -> Path: ...
    @property
    def threads(self) -> int: ...
    @property
    def statement_timeout_s(self) -> int: ...
    @property
    def deadline_s(self) -> int: ...


def validate_identifier(value: str, what: str = "identifier") -> str:
    """Return ``value`` when it is a strict, unquoted-safe Postgres identifier."""
    if not isinstance(value, str) or not _IDENT_RE.fullmatch(value):
        # The offending text is not echoed: it may be attacker-shaped input.
        raise ValueError(f"invalid {what} identifier")
    return value


def quote_ident(ident: str) -> str:
    """Quote a validated identifier. Validation already excludes ``"``."""
    return '"' + ident.replace('"', '""') + '"'


def sql_literal(text: str) -> str:
    """SQL string literal. Used only for the DSN and generated paths."""
    return "'" + text.replace("'", "''") + "'"


class Deadline:
    """A whole-session deadline that interrupts the connection when it passes."""

    def __init__(self, seconds: int) -> None:
        self.expired = threading.Event()
        self._seconds = seconds
        self._timer: threading.Timer | None = None

    def arm(self, conn: Any) -> None:
        self._timer = threading.Timer(self._seconds, self._fire, args=(conn,))
        self._timer.daemon = True
        self._timer.start()

    def _fire(self, conn: Any) -> None:
        self.expired.set()
        try:
            conn.interrupt()
        except Exception:
            pass

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


def raise_for_interrupt(deadline: Deadline, cause_type: str) -> None:
    """Map a stopped session to its outcome. Call it after the ``except`` block has closed.

    A passed deadline is ``deadline_exceeded``. A DuckDB interrupt without it is the operator's
    Ctrl-C, re-raised as ``KeyboardInterrupt`` so the caller exits 130 and not as a failure.
    """
    if deadline.expired.is_set():
        raise PostgresSnapshotError(reasons.connector.DEADLINE_EXCEEDED)
    if cause_type == INTERRUPT_CAUSE:
        raise KeyboardInterrupt


def raise_setup_failure(deadline: Deadline | None, code: str, cause_type: str) -> None:
    """Map a failed setup step. Call it after the ``except`` block has closed.

    One path for connect, extension load, attach and catalog read: a DuckDB interrupt is routed
    through ``raise_for_interrupt`` first (deadline passed: ``deadline_exceeded``; otherwise the
    operator's ``KeyboardInterrupt``), and any other failure becomes ``code``. The coded error is
    raised outside the handler, so it carries no ``__cause__`` or ``__context__``.
    """
    raise_for_interrupt(deadline if deadline is not None else Deadline(0), cause_type)
    raise PostgresSnapshotError(code, cause_type=cause_type)


def _extension_directory_settings(directory: Path) -> dict[str, Any]:
    """DuckDB 1.x takes ``extension_directory``; 2.x prefers the list ``extension_directories``."""
    import duckdb

    try:
        major = int(str(duckdb.__version__).split(".", 1)[0])
    except ValueError:
        major = 0
    if major >= 2:
        return {"extension_directories": [str(directory)]}
    return {"extension_directory": str(directory)}


def open_connection(
    config: SessionSettings, spill_dir: Path, deadline: Deadline | None = None
) -> Any:
    open_protected_dir(spill_dir, create=True, parents=True)
    cause_type = ""
    conn: Any = None
    try:
        from decoy_engine.fileaccess.adapters import duckdb as duckdb_adapter

        conn = duckdb_adapter.connect_internal(
            {
                "temp_directory": str(spill_dir),
                "memory_limit": config.memory_limit,
                "threads": config.threads,
                **_extension_directory_settings(config.extension_directory),
                # Fail closed offline: nothing may be fetched or auto-loaded.
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
                "allow_unsigned_extensions": False,
                # Kept True so the ORDER BY result order survives the Parquet
                # write even when the export spills; dropping it would let DuckDB
                # reorder spilled chunks and break the byte-identical snapshot
                # (guarantee 2).
                "preserve_insertion_order": True,
            }
        )
    except Exception as exc:
        cause_type = type(exc).__name__
    if cause_type:
        raise_setup_failure(deadline, reasons.connector.DUCKDB_UNAVAILABLE, cause_type)
    return conn


def load_postgres_extension(
    conn: Any, extension_directory: Path, deadline: Deadline | None = None
) -> None:
    cause_type = ""
    row: Any = None
    try:
        conn.execute("LOAD postgres")
        row = conn.execute(
            "SELECT loaded, install_path FROM duckdb_extensions() WHERE extension_name = 'postgres_scanner'"
        ).fetchone()
    except Exception as exc:
        cause_type = type(exc).__name__
    if cause_type:
        raise_setup_failure(deadline, reasons.connector.EXTENSION_UNAVAILABLE, cause_type)
    if not row or not row[0]:
        raise PostgresSnapshotError(reasons.connector.EXTENSION_UNAVAILABLE)
    installed_under = str(row[1] or "")
    # An extension that loaded from anywhere but the bundled directory means the
    # offline pin was bypassed, so refuse it.
    if not installed_under.startswith(str(extension_directory)):
        raise PostgresSnapshotError(reasons.connector.EXTENSION_UNTRUSTED_LOCATION)


def attach_read_only(
    conn: Any, dsn: SecretStr, statement_timeout_s: int, deadline: Deadline | None = None
) -> None:
    cause_type = ""
    try:
        conn.execute("SET TimeZone = 'UTC'")
        conn.execute(f"SET pg_statement_timeout_millis = {int(statement_timeout_s) * 1000}")
        conn.execute(
            f"ATTACH {sql_literal(dsn.get_secret_value())} AS {quote_ident(ATTACH_ALIAS)} "
            "(TYPE postgres, READ_ONLY)"
        )
    except Exception as exc:
        cause_type = type(exc).__name__
    if cause_type:
        raise_setup_failure(deadline, reasons.connector.SOURCE_UNREACHABLE, cause_type)


def open_read_session(
    config: SessionSettings,
    spill_dir: Path,
    on_connect: Callable[[Any], None] | None = None,
    deadline: Deadline | None = None,
) -> Any:
    """Open a connection with the extension loaded and the database attached read-only.

    ``on_connect`` runs once the extension is loaded and before the attach, so a deadline timer
    also covers a connect that hangs. A failure closes the connection before it propagates.
    """
    conn = open_connection(config, spill_dir, deadline)
    try:
        load_postgres_extension(conn, config.extension_directory, deadline)
        if on_connect is not None:
            on_connect(conn)
        attach_read_only(conn, config.dsn, config.statement_timeout_s, deadline)
    except BaseException:
        _close(conn)
        raise
    return conn


def _close(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def read_session(config: SessionSettings, deadline: Deadline) -> Iterator[Any]:
    """A read-only session with its spill directory, closed and removed on every exit."""
    fileaccess.require_ambient("the Postgres read session")
    spill_dir = config.temp_directory / f"spill-{uuid.uuid4().hex}"
    conn: Any = None
    try:
        conn = open_read_session(config, spill_dir, on_connect=deadline.arm, deadline=deadline)
        yield conn
    finally:
        deadline.cancel()
        if conn is not None:
            _close(conn)
        shutil.rmtree(spill_dir, ignore_errors=True)
