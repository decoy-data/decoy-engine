"""Postgres snapshot primitive: no-database suites (gates 2 and 3, leak)."""

from __future__ import annotations

import shutil
import traceback
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from pydantic import ValidationError

from decoy_engine.connectors import _postgres_session as session
from decoy_engine.connectors.postgres_snapshot import (
    PostgresSnapshotConfig,
    PostgresSnapshotError,
    RelationSelection,
    snapshot_tables_to_parquet,
)

_INJECTIONS = [
    'x"; DROP TABLE users; --',
    "x'; select 1; --",
    "a b",
    "a.b",
    "",
    "1abc",
    "x" * 64,
    "x\x00y",
    "t) UNION SELECT 1 --",
]


def _sel(**over):
    base = {"schema": "public", "table": "t", "columns": ["a"], "order_by": []}
    base.update(over)
    return RelationSelection(**base)


# ----- GATE 2: structured-only / identifier safety -------------------------


@pytest.mark.parametrize("bad", _INJECTIONS)
def test_injection_rejected_in_schema(bad):
    with pytest.raises(ValidationError):
        _sel(schema=bad)


@pytest.mark.parametrize("bad", _INJECTIONS)
def test_injection_rejected_in_table(bad):
    with pytest.raises(ValidationError):
        _sel(table=bad)


@pytest.mark.parametrize("bad", _INJECTIONS)
def test_injection_rejected_in_column(bad):
    with pytest.raises(ValidationError):
        _sel(columns=["ok", bad])


@pytest.mark.parametrize("bad", _INJECTIONS)
def test_injection_rejected_in_order_by(bad):
    with pytest.raises(ValidationError):
        _sel(columns=["ok", bad], order_by=[bad])


def test_validation_error_does_not_echo_the_payload():
    payload = "zz_PAYLOAD_zz; drop"
    with pytest.raises(ValidationError) as ei:
        _sel(table=payload)
    assert "PAYLOAD" not in str(ei.value)


@pytest.mark.parametrize("field", ["where", "predicate", "sql", "query", "filter", "limit"])
def test_unknown_and_raw_sql_fields_rejected(field):
    with pytest.raises(ValidationError):
        _sel(**{field: "1=1"})


def test_no_raw_sql_or_predicate_field_exists():
    names = set(RelationSelection.model_fields) | set(PostgresSnapshotConfig.model_fields)
    assert not names & {"sql", "query", "where", "predicate", "filter", "raw"}


def test_columns_must_be_explicit_and_non_empty():
    with pytest.raises(ValidationError):
        _sel(columns=[])
    with pytest.raises(ValidationError):
        _sel(columns=["*"])


def test_order_by_must_be_projected_and_unique():
    with pytest.raises(ValidationError):
        _sel(columns=["a"], order_by=["b"])
    with pytest.raises(ValidationError):
        _sel(columns=["a", "a"])


def test_config_rejects_unknown_fields(tmp_path):
    with pytest.raises(ValidationError):
        PostgresSnapshotConfig(
            dsn="x",
            extension_directory=tmp_path,
            memory_limit="1GB",
            temp_directory=tmp_path,
            threads=1,
            row_group_size=1000,
            statement_timeout_s=1,
            deadline_s=1,
            sql="select 1",
        )


def test_quoting_doubles_embedded_quotes():
    # Validation already excludes quotes; the quoter must still be safe alone.
    assert session.quote_ident('a"b') == '"a""b"'


def test_empty_and_duplicate_selection_rejected(tmp_path):
    cfg = PostgresSnapshotConfig(
        dsn="x",
        extension_directory=tmp_path,
        memory_limit="1GB",
        temp_directory=tmp_path / "s",
        threads=1,
        row_group_size=1000,
        statement_timeout_s=1,
        deadline_s=1,
    )
    with pytest.raises(PostgresSnapshotError) as e1:
        snapshot_tables_to_parquet(cfg, [], tmp_path / "d")
    assert e1.value.code == "no_selections"
    with pytest.raises(PostgresSnapshotError) as e2:
        snapshot_tables_to_parquet(cfg, [_sel(), _sel()], tmp_path / "d")
    assert e2.value.code == "duplicate_relation"


# ----- GATE 3: offline extension ------------------------------------------


def _cfg(ext: Path, tmp_path: Path, dsn="host=127.0.0.1 port=1 user=u password=PW_SECRET dbname=d"):
    return PostgresSnapshotConfig(
        dsn=dsn,
        extension_directory=ext,
        memory_limit="256MB",
        temp_directory=tmp_path / "spill",
        threads=1,
        row_group_size=1000,
        statement_timeout_s=5,
        deadline_s=20,
    )


def test_extension_loads_from_local_dir_with_autoinstall_disabled(ext_dir, tmp_path):
    cfg = _cfg(ext_dir, tmp_path)
    conn = session.open_connection(cfg, tmp_path / "spill" / "x")
    try:
        assert (
            conn.execute("SELECT current_setting('autoinstall_known_extensions')").fetchone()[0]
            is False
        )
        assert (
            conn.execute("SELECT current_setting('autoload_known_extensions')").fetchone()[0]
            is False
        )
        session.load_postgres_extension(conn, cfg.extension_directory)
    finally:
        conn.close()


def test_missing_extension_fails_closed_and_never_fetches(tmp_path):
    empty = tmp_path / "empty_ext"
    empty.mkdir()
    cfg = _cfg(empty, tmp_path)
    with pytest.raises(PostgresSnapshotError) as ei:
        snapshot_tables_to_parquet(cfg, [_sel()], tmp_path / "dest")
    # A network INSTALL would have succeeded and moved on to a connect error.
    assert ei.value.code == "extension_unavailable"
    assert list(empty.rglob("*.duckdb_extension")) == []


def test_incompatible_extension_binary_fails_closed(ext_dir, tmp_path):
    bad = tmp_path / "bad_ext"
    shutil.copytree(ext_dir, bad)
    files = list(bad.rglob("postgres_scanner.duckdb_extension"))
    assert files, "fixture layout changed"
    for f in files:
        f.write_bytes(b"not an extension binary" * 64)
    cfg = _cfg(bad, tmp_path)
    with pytest.raises(PostgresSnapshotError) as ei:
        snapshot_tables_to_parquet(cfg, [_sel()], tmp_path / "dest")
    assert ei.value.code == "extension_unavailable"


def test_failed_extension_load_leaves_no_staged_files(tmp_path):
    empty = tmp_path / "empty_ext"
    empty.mkdir()
    dest = tmp_path / "dest"
    with pytest.raises(PostgresSnapshotError):
        snapshot_tables_to_parquet(_cfg(empty, tmp_path), [_sel()], dest)
    assert list(dest.iterdir()) == []
    assert not (tmp_path / "spill").exists() or list((tmp_path / "spill").iterdir()) == []


# ----- Leak rule ------------------------------------------------------------


def test_connect_failure_leaks_no_dsn(ext_dir, tmp_path, caplog):
    caplog.set_level("DEBUG")
    cfg = _cfg(ext_dir, tmp_path)
    with pytest.raises(PostgresSnapshotError) as ei:
        snapshot_tables_to_parquet(cfg, [_sel()], tmp_path / "dest")
    err = ei.value
    assert err.code == "source_unreachable"
    rendered = "".join(traceback.format_exception(err)) + str(err) + repr(err)
    rendered += "\n".join(r.getMessage() for r in caplog.records)
    for needle in ("PW_SECRET", "127.0.0.1", "port=1", "user=u", "dbname"):
        assert needle not in rendered
    assert err.__cause__ is None


def test_dsn_secretstr_repr_hides_value(tmp_path):
    cfg = _cfg(tmp_path, tmp_path)
    assert "PW_SECRET" not in repr(cfg) and "PW_SECRET" not in str(cfg)
    assert "PW_SECRET" not in cfg.model_dump_json()


# ----- AT-E3: no error keeps DuckDB's text as cause or context --------------------------------

_MARK = "PW_MARK_9f3"
_DATE_CATALOG = (("a", "date", "b"),)


def _rendered(err: BaseException, caplog) -> str:
    out = "".join(traceback.format_exception(err)) + str(err) + repr(err)
    return out + "\n".join(r.getMessage() for r in caplog.records)


def _assert_value_free(err: BaseException, caplog) -> None:
    assert err.__cause__ is None and err.__context__ is None
    assert _MARK not in _rendered(err, caplog)


def _run(tmp_path, ext, **cfg):
    config = _cfg(ext, tmp_path, dsn=f"host=h user=u password={_MARK} dbname=d")
    if cfg:
        config = config.model_copy(update=cfg)
    return snapshot_tables_to_parquet(config, [_sel()], tmp_path / "dest")


@pytest.mark.parametrize(
    ("fragment", "code", "catalog"),
    [
        ("LOAD postgres", "extension_unavailable", (("a", "text", "b"),)),
        ("ATTACH", "source_unreachable", (("a", "text", "b"),)),
        ("AS q(nspname", "catalog_read_failed", (("a", "text", "b"),)),
        ("count(*) FILTER", "value_guard_failed", _DATE_CATALOG),
        ("COPY", "export_failed", (("a", "text", "b"),)),
    ],
)
def test_every_coded_failure_is_value_free_and_unchained(
    fake_pg, tmp_path, caplog, fragment, code, catalog
):
    caplog.set_level("DEBUG")
    fake_pg(catalog=catalog, fail={fragment: "raise"})
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext")
    assert ei.value.code == code
    _assert_value_free(ei.value, caplog)


def test_connect_failure_is_value_free_and_unchained(monkeypatch, tmp_path, caplog):
    def boom(cfg):
        raise RuntimeError(f"cannot open {_MARK}")

    monkeypatch.setattr("decoy_engine.fileaccess.adapters.duckdb.connect_internal", boom)
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext")
    assert ei.value.code == "duckdb_unavailable"
    _assert_value_free(ei.value, caplog)


@pytest.mark.parametrize("fragment", ["AS q(nspname", "COPY"])
def test_deadline_failure_is_value_free_and_unchained(fake_pg, tmp_path, caplog, fragment):
    fake_pg(fail={fragment: "block"})
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext", deadline_s=1)
    assert ei.value.code == "deadline_exceeded"
    _assert_value_free(ei.value, caplog)


# ----- AT-E15: interrupt versus deadline ------------------------------------------------------


def _no_leftovers(tmp_path):
    dest = tmp_path / "dest"
    assert [p for p in dest.iterdir() if p.name.startswith((".stage-", "snapshot-"))] == []
    assert not (tmp_path / "spill").exists() or list((tmp_path / "spill").iterdir()) == []


def test_interrupt_without_deadline_is_keyboard_interrupt(fake_pg, tmp_path):
    conn = fake_pg(fail={"COPY": "interrupt"})
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, tmp_path / "ext")
    assert conn.closed
    _no_leftovers(tmp_path)


def test_interrupt_in_the_catalog_read_is_keyboard_interrupt(fake_pg, tmp_path):
    fake_pg(fail={"AS q(nspname": "interrupt"})
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, tmp_path / "ext")
    _no_leftovers(tmp_path)


def test_interrupt_with_the_deadline_set_is_deadline_exceeded(fake_pg, tmp_path):
    fake_pg(fail={"COPY": "block"})
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext", deadline_s=1)
    assert ei.value.code == "deadline_exceeded"
    _no_leftovers(tmp_path)


@pytest.mark.parametrize("fragment", ["ATTACH", "LOAD postgres", "SET TimeZone"])
def test_setup_interrupt_without_deadline_is_keyboard_interrupt(fake_pg, tmp_path, fragment):
    conn = fake_pg(fail={fragment: "interrupt"})
    with pytest.raises(KeyboardInterrupt) as ei:
        _run(tmp_path, tmp_path / "ext")
    assert ei.value.__cause__ is None
    assert conn.closed
    _no_leftovers(tmp_path)


def test_attach_interrupt_with_the_deadline_set_is_deadline_exceeded(fake_pg, tmp_path, caplog):
    conn = fake_pg(fail={"ATTACH": "block"})
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext", deadline_s=1)
    assert ei.value.code == "deadline_exceeded"
    assert conn.closed
    _assert_value_free(ei.value, caplog)
    _no_leftovers(tmp_path)


def test_attach_failure_still_maps_to_source_unreachable(fake_pg, tmp_path, caplog):
    fake_pg(fail={"ATTACH": "raise"})
    with pytest.raises(PostgresSnapshotError) as ei:
        _run(tmp_path, tmp_path / "ext")
    assert ei.value.code == "source_unreachable"
    _assert_value_free(ei.value, caplog)


# ----- AT-E6 (unit half): the shape guard -----------------------------------------------------

_TWO = (("a", "text", "b"), ("b", "text", "b"))


def _whole(columns):
    return RelationSelection(
        schema="public", table="t", columns=columns, order_by=[], whole_relation=True
    )


def test_whole_relation_refuses_a_column_the_caller_did_not_check(fake_pg, tmp_path):
    conn = fake_pg(catalog=_TWO)
    with pytest.raises(PostgresSnapshotError) as ei:
        snapshot_tables_to_parquet(
            _cfg(tmp_path / "ext", tmp_path), [_whole(["a"])], tmp_path / "d"
        )
    assert ei.value.code == "relation_shape_changed"
    assert ei.value.location == "public.t"
    assert not any("COPY" in q for q in conn.statements)


def test_whole_relation_refuses_a_checked_column_that_vanished(fake_pg, tmp_path):
    fake_pg(catalog=_TWO[:1])
    with pytest.raises(PostgresSnapshotError) as ei:
        snapshot_tables_to_parquet(
            _cfg(tmp_path / "ext", tmp_path), [_whole(["a", "b"])], tmp_path / "d"
        )
    assert ei.value.code == "relation_shape_changed"


def test_whole_relation_with_the_same_columns_passes(fake_pg, tmp_path):
    conn = fake_pg(catalog=_TWO)
    snapshot_tables_to_parquet(
        _cfg(tmp_path / "ext", tmp_path), [_whole(["a", "b"])], tmp_path / "d"
    )
    assert any("COPY" in q for q in conn.statements)


def test_a_partial_selection_is_not_shape_checked(fake_pg, tmp_path):
    conn = fake_pg(catalog=_TWO)
    snapshot_tables_to_parquet(_cfg(tmp_path / "ext", tmp_path), [_sel()], tmp_path / "d")
    assert any("COPY" in q for q in conn.statements)


def test_whole_relation_rejects_a_non_bool():
    with pytest.raises(ValidationError):
        _sel(whole_relation=1)


# ----- relation_columns: the catalog read before any row --------------------------------------

from decoy_engine.connectors.postgres_catalog import relation_columns  # noqa: E402


def test_relation_columns_returns_names_in_table_order(fake_pg, tmp_path):
    fake_pg(catalog=(("z", "text", "b"), ("a", "text", "b")))
    cols = relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "t")])
    assert cols == {"public.t": ["z", "a"]}


def test_a_catalog_column_name_that_fails_the_rule_is_refused_by_position(fake_pg, tmp_path):
    fake_pg(catalog=(("a", "text", "b"), ('a"b', "text", "b")))
    with pytest.raises(PostgresSnapshotError) as ei:
        relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "t")])
    assert ei.value.code == "column_name_unsupported"
    assert ei.value.location == "public.t#2"
    assert 'a"b' not in str(ei.value) + repr(ei.value)
    assert ei.value.__context__ is None and ei.value.__cause__ is None


def test_relation_columns_refuses_a_relation_named_twice(fake_pg, tmp_path):
    fake_pg()
    with pytest.raises(PostgresSnapshotError) as ei:
        relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "t"), ("public", "t")])
    assert ei.value.code == "duplicate_relation"


def test_relation_columns_reports_a_missing_relation(fake_pg, tmp_path):
    fake_pg()
    with pytest.raises(PostgresSnapshotError) as ei:
        relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "other")])
    assert ei.value.code == "relation_not_found"


def test_relation_columns_interrupt_is_keyboard_interrupt(fake_pg, tmp_path):
    fake_pg(fail={"AS q(nspname": "interrupt"})
    with pytest.raises(KeyboardInterrupt):
        relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "t")])


def test_relation_columns_attach_interrupt_is_keyboard_interrupt(fake_pg, tmp_path):
    fake_pg(fail={"ATTACH": "interrupt"})
    with pytest.raises(KeyboardInterrupt):
        relation_columns(_cfg(tmp_path / "ext", tmp_path), [("public", "t")])


def test_relation_columns_attach_interrupt_with_the_deadline_set_is_deadline_exceeded(
    fake_pg, tmp_path, caplog
):
    fake_pg(fail={"ATTACH": "block"})
    with pytest.raises(PostgresSnapshotError) as ei:
        relation_columns(
            _cfg(tmp_path / "ext", tmp_path).model_copy(update={"deadline_s": 1}), [("public", "t")]
        )
    assert ei.value.code == "deadline_exceeded"
    _assert_value_free(ei.value, caplog)


class _ElsewhereConn:
    """A connection whose postgres extension loaded from outside the bundled directory."""

    def execute(self, sql, params=None):
        class _Result:
            def fetchone(self):
                return (True, "/somewhere/else/postgres_scanner")

        return _Result()


def test_extension_loaded_from_outside_the_bundled_directory_is_refused(tmp_path):
    with pytest.raises(PostgresSnapshotError) as ei:
        session.load_postgres_extension(_ElsewhereConn(), tmp_path / "ext")
    assert ei.value.code == "extension_untrusted_location"
