"""F01 E0 spike: what the DuckDB postgres extension does under a read-write ATTACH.

Raw DuckDB calls only, no product code. The Postgres target publish (roadmap row 86) holds
every step in one PostgreSQL transaction opened by DuckDB. Each cell below proves one behaviour
that design needs, before any product code depends on it. A second DuckDB connection (its own
libpq session) plays the "other application session". Cells c, d and h also record their
outcome (``record_property`` and a ``SPIKE`` line on stdout). Results are in
docs/records/2026-11-18-f01-e0-spike.md.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
import warnings

import pytest

duckdb = pytest.importorskip("duckdb")

pytestmark = pytest.mark.pg_integration

# Cell (a) mutation seam: the plan's named mutation runs it with ``use_transaction := false``.
CELL_A_USE_TRANSACTION = "true"


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _open(ext_dir, dsn: str, alias: str, *, read_only: bool = False):
    conn = duckdb.connect(config={"extension_directory": str(ext_dir)})
    conn.execute("LOAD postgres")
    opts = "TYPE postgres, READ_ONLY" if read_only else "TYPE postgres"
    conn.execute(f"ATTACH {_lit(dsn)} AS {alias} ({opts})")
    return conn


def _pgx(conn, sql: str, flag: str = "true") -> None:
    conn.execute(f"CALL postgres_execute('w', ?, use_transaction := {flag})", [sql])


class Peer:
    """A second libpq session, standing in for the application reading the target."""

    def __init__(self, ext_dir, dsn):
        self._c = _open(ext_dir, dsn, "peer", read_only=True)

    def q(self, sql: str) -> list[tuple]:
        return self._c.execute("SELECT * FROM postgres_query('peer', ?)", [sql]).fetchall()

    def one(self, sql: str):
        rows = self.q(sql)
        return rows[0][0] if rows else None

    def close(self) -> None:
        self._c.close()


@pytest.fixture
def peer(pg_dsn, ext_dir):
    p = Peer(ext_dir, pg_dsn)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def rw(pg_dsn, ext_dir):
    conns = []

    def _make():
        c = _open(ext_dir, pg_dsn, "w")
        conns.append(c)
        return c

    try:
        yield _make
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass


def _parquet(conn, tmp_path, select_sql: str):
    path = tmp_path / f"{uuid.uuid4().hex}.parquet"
    conn.execute(f"COPY ({select_sql}) TO {_lit(str(path))} (FORMAT parquet)")
    return path


def _wait(predicate, seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


def _note(record_property, key: str, value) -> None:
    record_property(key, str(value))
    warnings.warn(f"SPIKE {key}={value}", stacklevel=2)


def _seed_table(pg, name="t", rows=3):
    s = pg.schema
    pg.run(
        f"CREATE TABLE {s}.{name}(id int PRIMARY KEY, v text);"
        f"INSERT INTO {s}.{name} SELECT g, 'old' || g FROM generate_series(1, {rows}) g;"
    )


def _relfilenode(peer, schema, name):
    return peer.one(f"SELECT relfilenode FROM pg_class WHERE oid = '{schema}.{name}'::regclass")


# ----- (a) DDL, TRUNCATE and INSERT share one transaction, invisible until COMMIT ---------------


def _run_cell_a(pg, peer, rw, tmp_path, *, finish: str):
    s = pg.schema
    _seed_table(pg)
    before_fn = _relfilenode(peer, s, "t")
    conn = rw()
    src = _parquet(conn, tmp_path, "SELECT 100 + range AS id, 'new' AS v FROM range(5)")
    conn.execute("BEGIN")
    _pgx(conn, f"CREATE TABLE {s}.made(i int)", CELL_A_USE_TRANSACTION)
    _pgx(conn, f"TRUNCATE {s}.t", CELL_A_USE_TRANSACTION)
    count = conn.execute(
        f"INSERT INTO w.{s}.t (id, v) SELECT id, v FROM read_parquet({_lit(str(src))})"
    ).fetchone()
    assert count == (5,)
    # TRUNCATE holds ACCESS EXCLUSIVE, so the peer reads catalogs only (a count(*) would queue
    # behind the lock). Neither the new table nor the new relfilenode shows before the end.
    assert peer.one(f"SELECT to_regclass('{s}.made') IS NULL") is True
    assert _relfilenode(peer, s, "t") == before_fn
    conn.execute(finish)
    return before_fn


def test_cell_a_rollback_undoes_ddl_truncate_and_insert(pg, peer, rw, tmp_path):
    s = pg.schema
    before_fn = _run_cell_a(pg, peer, rw, tmp_path, finish="ROLLBACK")
    assert peer.one(f"SELECT to_regclass('{s}.made') IS NULL") is True
    assert _relfilenode(peer, s, "t") == before_fn
    assert peer.one(f"SELECT count(*) FROM {s}.t") == 3
    assert peer.one(f"SELECT min(v) FROM {s}.t") == "old1"


def test_cell_a_commit_publishes_every_statement_together(pg, peer, rw, tmp_path):
    s = pg.schema
    before_fn = _run_cell_a(pg, peer, rw, tmp_path, finish="COMMIT")
    assert peer.one(f"SELECT to_regclass('{s}.made') IS NOT NULL") is True
    assert _relfilenode(peer, s, "t") != before_fn
    assert peer.one(f"SELECT count(*) FROM {s}.t") == 5
    assert peer.one(f"SELECT min(v) FROM {s}.t") == "new"


# ----- (b) closing the connection mid-transaction aborts it and releases its locks --------------


@pytest.mark.serial
def test_cell_b_close_mid_transaction_aborts_and_releases_locks(pg, peer, rw):
    s = pg.schema
    _seed_table(pg)
    conn = rw()
    conn.execute("BEGIN")
    pid = conn.execute("SELECT * FROM postgres_query('w', 'SELECT pg_backend_pid()')").fetchone()[0]
    _pgx(conn, f"TRUNCATE {s}.t")
    held = f"SELECT count(*) FROM pg_locks WHERE pid = {pid} AND mode = 'AccessExclusiveLock'"
    assert peer.one(held) > 0
    conn.close()
    assert _wait(
        lambda: peer.one(f"SELECT count(*) FROM pg_stat_activity WHERE pid = {pid}") == 0, 10
    ), "the backend is still alive after the DuckDB connection closed"
    assert peer.one(held) == 0
    # The truncate never committed and no lock is left, so the read returns the old rows at once.
    assert peer.one(f"SELECT count(*) FROM {s}.t") == 3


# ----- (c) a DuckDB-side read of a locked, truncated table inside the transaction ---------------


def test_cell_c_duckdb_side_read_of_truncated_table_is_recorded(pg, rw, record_property):
    s = pg.schema
    _seed_table(pg)
    conn = rw()
    conn.execute("BEGIN")
    _pgx(conn, f"TRUNCATE {s}.t")
    box: dict = {}

    def read():
        try:
            box["rows"] = conn.execute(f"SELECT count(*) FROM w.{s}.t").fetchone()[0]
        except Exception as exc:
            box["error"] = type(exc).__name__

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(10)
    if t.is_alive():
        conn.interrupt()
        t.join(10)
        outcome = "hang_until_interrupt"
    elif "error" in box:
        outcome = f"error_{box['error']}"
    elif box["rows"] == 0:
        outcome = "in_transaction_state"
    else:
        outcome = f"stale_read_{box['rows']}"
    _note(record_property, "cell_c", outcome)
    assert not t.is_alive()
    conn.execute("ROLLBACK")


# ----- (d) pg_clear_cache() shows a changed catalog ---------------------------------------------


def test_cell_d_pg_clear_cache_shows_changed_catalog(pg, rw, record_property):
    s = pg.schema
    _seed_table(pg)
    conn = rw()

    def cols():
        return [r[0] for r in conn.execute(f"DESCRIBE w.{s}.t").fetchall()]

    assert cols() == ["id", "v"]
    pg.run(f"ALTER TABLE {s}.t ADD COLUMN extra int")
    _note(record_property, "cell_d_stale_before_clear", cols() == ["id", "v"])
    conn.execute("CALL pg_clear_cache()")
    assert cols() == ["id", "v", "extra"]


# ----- (e) interrupt() cancels the server query -------------------------------------------------


@pytest.mark.serial
@pytest.mark.parametrize("path", ["query", "execute", "execute_in_transaction", "lock_wait"])
def test_cell_e_interrupt_cancels_the_server_query(pg, peer, rw, path, record_property):
    s = pg.schema
    conn = rw()
    marker = "m" + uuid.uuid4().hex
    running = (
        "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' "
        f"AND pid <> pg_backend_pid() AND query LIKE '%{marker}%'"
    )
    holder = None
    if path == "lock_wait":
        _seed_table(pg)
        holder = rw()
        holder.execute("BEGIN")
        _pgx(holder, f"TRUNCATE {s}.t")
        statement = f"TRUNCATE {s}.t /* {marker} */"
    else:
        statement = f"SELECT 1 FROM pg_sleep(30) /* {marker} */"
    if path in ("execute_in_transaction", "lock_wait"):
        conn.execute("BEGIN")

    def run():
        try:
            if path == "query":
                conn.execute("SELECT * FROM postgres_query('w', ?)", [statement]).fetchall()
            else:
                _pgx(conn, statement)
            box["done"] = True
        except Exception as exc:
            box["error"] = type(exc).__name__

    box: dict = {}
    t = threading.Thread(target=run, daemon=True)
    t.start()
    try:
        assert _wait(lambda: peer.one(running) == 1, 10), "the statement never reached the server"
        conn.interrupt()
        t.join(10)
        returned = not t.is_alive()
        gone = _wait(lambda: peer.one(running) == 0, 5)
        _note(record_property, f"cell_e_{path}", f"client_returned={returned} server_gone={gone}")
        assert returned, "interrupt() did not return control to the client"
        assert gone, "the server query outlived interrupt()"
    finally:
        # Leave no sleeper behind if interrupt() failed.
        peer.q(
            "SELECT pg_cancel_backend(pid) FROM pg_stat_activity "
            f"WHERE query LIKE '%{marker}%' AND pid <> pg_backend_pid()"
        )
        if holder is not None:
            holder.close()


@pytest.mark.serial
def test_cell_e2_cancelling_the_backend_from_a_second_session_stops_the_statement(
    pg, peer, rw, record_property
):
    # Fallback for cell e: the publisher already records pg_backend_pid() at step 1, so a
    # watchdog can cancel the running statement from another session when interrupt() cannot.
    conn = rw()
    marker = "m" + uuid.uuid4().hex
    conn.execute("BEGIN")
    pid = conn.execute("SELECT * FROM postgres_query('w', 'SELECT pg_backend_pid()')").fetchone()[0]
    running = f"SELECT count(*) FROM pg_stat_activity WHERE pid = {pid} AND state = 'active'"
    box: dict = {}

    def run():
        try:
            _pgx(conn, f"SELECT pg_sleep(30) /* {marker} */")
            box["done"] = True
        except Exception as exc:
            box["error"] = type(exc).__name__

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert _wait(lambda: peer.one(running) == 1, 10), "the statement never reached the server"
    assert peer.one(f"SELECT pg_cancel_backend({pid})") is True
    t.join(10)
    returned = not t.is_alive()
    _note(record_property, "cell_e2", f"client_returned={returned} outcome={box}")
    assert returned and "error" in box
    assert (
        peer.one(f"SELECT count(*) FROM pg_stat_activity WHERE pid = {pid} AND state = 'active'")
        == 0
    )
    conn.execute("ROLLBACK")


# ----- (f) INSERT with a column list over generated, identity and exotic types -------------------


def test_cell_f_insert_column_list_handles_generated_identity_and_exotic_types(
    pg, peer, rw, tmp_path
):
    s = pg.schema
    pg.run(
        f"CREATE TYPE {s}.mood AS ENUM ('happy', 'sad');"
        f"CREATE TABLE {s}.g ("
        "id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, a int, "
        "twice int GENERATED ALWAYS AS (a * 2) STORED, "
        f"m {s}.mood, j jsonb, u uuid, arr int[], tags text[])"
    )
    conn = rw()
    src = _parquet(
        conn,
        tmp_path,
        "SELECT 40 + range AS id, range + 1 AS a, 'happy' AS m, '{\"k\": 1}' AS j, "
        "'123e4567-e89b-12d3-a456-426614174000' AS u, [1, 2, 3] AS arr, ['x', 'y'] AS tags "
        "FROM range(3)",
    )
    conn.execute("BEGIN")
    _pgx(conn, f"ALTER TABLE {s}.g ALTER COLUMN id SET GENERATED BY DEFAULT")
    n = conn.execute(
        f"INSERT INTO w.{s}.g (id, a, m, j, u, arr, tags) "
        f"SELECT id, a, m, j, u, arr, tags FROM read_parquet({_lit(str(src))})"
    ).fetchone()
    assert n == (3,)
    conn.execute("COMMIT")
    rows = peer.q(
        f"SELECT id, a, twice, m::text, j::text, u::text, arr::text, tags::text "
        f"FROM {s}.g ORDER BY id"
    )
    assert rows[0] == (
        40,
        1,
        2,
        "happy",
        '{"k": 1}',
        "123e4567-e89b-12d3-a456-426614174000",
        "{1,2,3}",
        "{x,y}",
    )
    assert [r[0] for r in rows] == [40, 41, 42]
    assert [r[2] for r in rows] == [2, 4, 6]


# ----- (g) the INSERT affected-row count is returned ---------------------------------------------


def test_cell_g_insert_returns_the_affected_row_count(pg, rw, tmp_path):
    s = pg.schema
    pg.run(f"CREATE TABLE {s}.c(id int, v text)")
    conn = rw()
    src = _parquet(conn, tmp_path, "SELECT range AS id, 'x' AS v FROM range(1234)")
    conn.execute("BEGIN")
    got = conn.execute(
        f"INSERT INTO w.{s}.c (id, v) SELECT id, v FROM read_parquet({_lit(str(src))})"
    ).fetchone()
    conn.execute("ROLLBACK")
    assert got == (1234,)


# ----- (h) a connect-timeout mechanism bounds a connection to a blackhole address ----------------

BLACKHOLE = "192.0.2.1"  # TEST-NET-1, never routed


def _attach_blackhole(ext_dir, dsn_text: str, box: dict):
    conn = duckdb.connect(config={"extension_directory": str(ext_dir)})
    conn.execute("LOAD postgres")
    start = time.monotonic()
    try:
        conn.execute(f"ATTACH {_lit(dsn_text)} AS bh (TYPE postgres, READ_ONLY)")
        box["error"] = "attached"
    except Exception as exc:
        box["error"] = type(exc).__name__
    finally:
        box["elapsed"] = time.monotonic() - start
        conn.close()


_INTERRUPT_CHILD = """
import sys, threading, duckdb
c = duckdb.connect(config={"extension_directory": sys.argv[1]})
c.execute("LOAD postgres")
threading.Timer(2.0, c.interrupt).start()
try:
    c.execute("ATTACH '" + sys.argv[2] + "' AS bh (TYPE postgres, READ_ONLY)")
except Exception as exc:
    print(type(exc).__name__)
"""


def _interrupt_attach_blackhole(ext_dir, dsn_text: str) -> dict:
    # A blocked connect cannot be stopped from inside the process, so a child is killed instead.
    start = time.monotonic()
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-I", "-c", _INTERRUPT_CHILD, str(ext_dir), dsn_text],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        return {"error": done.stdout.strip() or "attached", "elapsed": time.monotonic() - start}
    except subprocess.TimeoutExpired:
        return {"error": "no_return_in_12s", "elapsed": 12.0}


@pytest.mark.serial
def test_cell_h_a_connect_timeout_mechanism_bounds_a_blackhole_connection(
    ext_dir, monkeypatch, record_property
):
    base = f"host={BLACKHOLE} port=5432 user=postgres password=pw dbname=postgres"
    results: dict[str, dict] = {}

    def attempt(name, dsn_text, *, env=None):
        monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)
        for k, v in (env or {}).items():
            monkeypatch.setenv(k, v)
        box: dict = {}
        t = threading.Thread(target=_attach_blackhole, args=(ext_dir, dsn_text, box), daemon=True)
        t.start()
        t.join(20)
        results[name] = box or {"error": "no_return_in_20s", "elapsed": 20.0}
        monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)

    attempt("dsn_connect_timeout", base + " connect_timeout=2")
    attempt("env_pgconnect_timeout", base, env={"PGCONNECT_TIMEOUT": "2"})
    results["wall_clock_interrupt"] = _interrupt_attach_blackhole(ext_dir, base)
    bounded = {}
    for name, box in results.items():
        bounded[name] = (
            not box["error"].startswith(("attached", "no_return")) and box["elapsed"] < 8
        )
        _note(record_property, f"cell_h_{name}", f"{box['error']} {box['elapsed']:.1f}s")
    assert bounded["dsn_connect_timeout"], results
    assert any(bounded.values()), results


# ----- (i) a server-side DO block restarting a sequence is undone by ROLLBACK -------------------


def test_cell_i_do_block_alter_sequence_restart_is_undone_by_rollback(pg, peer, rw):
    s = pg.schema
    pg.run(f"CREATE SEQUENCE {s}.sq START 1")
    do = f"DO $$ BEGIN ALTER SEQUENCE {s}.sq RESTART WITH 500; END $$"
    state = f"SELECT last_value::text || ',' || is_called::text FROM {s}.sq"
    assert peer.one(state) == "1,false"
    conn = rw()
    conn.execute("BEGIN")
    _pgx(conn, do)
    conn.execute("ROLLBACK")
    assert peer.one(state) == "1,false"
    # The same block commits when asked to, so the rollback result above is not a no-op.
    conn.execute("BEGIN")
    _pgx(conn, do)
    conn.execute("COMMIT")
    assert peer.one(state) == "500,false"


# ----- (j) the transaction id and backend pid read inside match a second session -----------------


def test_cell_j_xact_id_and_backend_pid_match_a_second_session(pg, peer, rw):
    s = pg.schema
    _seed_table(pg)
    conn = rw()
    conn.execute("BEGIN")
    _pgx(conn, f"TRUNCATE {s}.t")
    xid, pid = conn.execute(
        "SELECT * FROM postgres_query('w', "
        "'SELECT pg_current_xact_id()::xid::text, pg_backend_pid()')"
    ).fetchone()
    seen = peer.q(f"SELECT backend_xid::text, state FROM pg_stat_activity WHERE pid = {pid}")
    conn.execute("ROLLBACK")
    assert seen == [(xid, "idle in transaction")]
