"""Session helpers shared by the Postgres connectors (no database needed)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import duckdb
import pytest

from decoy_engine.connectors import _postgres_session as session
from decoy_engine.connectors.postgres_snapshot import PostgresSnapshotConfig


def _config(tmp_path):
    return PostgresSnapshotConfig(
        dsn="host=h",
        extension_directory=tmp_path / "ext",
        memory_limit="64MB",
        temp_directory=tmp_path / "spill",
        threads=1,
        row_group_size=1000,
        statement_timeout_s=1,
        deadline_s=1,
    )


def _settings_for(monkeypatch, tmp_path, version):
    seen = {}

    def fake_connect(cfg):
        seen.update(cfg)
        return object()

    monkeypatch.setattr(duckdb, "__version__", version)
    monkeypatch.setattr("decoy_engine.fileaccess.adapters.duckdb.connect_internal", fake_connect)
    session.open_connection(_config(tmp_path), tmp_path / "spill" / "x")
    return seen


def test_duckdb_1x_sets_extension_directory(monkeypatch, tmp_path):
    seen = _settings_for(monkeypatch, tmp_path, "1.5.4")
    assert seen["extension_directory"] == str(tmp_path / "ext")
    assert "extension_directories" not in seen


def test_duckdb_2x_sets_a_one_item_extension_directories_list(monkeypatch, tmp_path):
    seen = _settings_for(monkeypatch, tmp_path, "2.0.0")
    assert seen["extension_directories"] == [str(tmp_path / "ext")]
    assert "extension_directory" not in seen


@pytest.mark.parametrize("version", ["1.5.4", "2.0.0"])
def test_autoinstall_and_autoload_are_off_in_both(monkeypatch, tmp_path, version):
    seen = _settings_for(monkeypatch, tmp_path, version)
    assert seen["autoinstall_known_extensions"] is False
    assert seen["autoload_known_extensions"] is False
    assert seen["allow_unsigned_extensions"] is False


@pytest.mark.parametrize("bad", ["a.b", "x" * 64, "", "ok\n", 'a"b'])
def test_identifier_rule_refuses_without_echo(bad):
    with pytest.raises(ValueError) as ei:
        session.validate_identifier(bad, "table")
    assert bad.strip() not in str(ei.value) or not bad.strip()


def test_require_pg_turns_a_skip_into_a_failure(pg_policy):
    with pytest.raises(pytest.fail.Exception):
        pg_policy(True, "no postgres")
    with pytest.raises(pytest.skip.Exception):
        pg_policy(False, "no postgres")


# ----- S2: connect timeout on every ATTACH -----------------------------------------------------


@pytest.mark.parametrize(
    ("deadline_s", "want"), [(1, 2), (3, 2), (4, 2), (6, 4), (12, 10), (3600, 10)]
)
def test_connect_timeout_s_is_two_under_the_deadline_with_a_two_second_floor(deadline_s, want):
    assert session.connect_timeout_s(deadline_s) == want


@pytest.mark.parametrize(
    ("dsn", "want"),
    [
        ("host=h dbname=d", "host=h dbname=d connect_timeout=7"),
        ("", " connect_timeout=7"),
        ("postgresql://u@h/d", "postgresql://u@h/d?connect_timeout=7"),
        (
            "postgres://u@h/d?sslmode=require",
            "postgres://u@h/d?sslmode=require&connect_timeout=7",
        ),
        ("postgresql://u@h/d?", "postgresql://u@h/d?connect_timeout=7"),
        (
            "postgresql://u@h/d?sslmode=require&",
            "postgresql://u@h/d?sslmode=require&connect_timeout=7",
        ),
        ("host=h password='a\\\\'", "host=h password='a\\\\' connect_timeout=7"),
        ("host=h password=a\\\\", "host=h password=a\\\\ connect_timeout=7"),
        ("host=h password=a\\\\\\\\", "host=h password=a\\\\\\\\ connect_timeout=7"),
        ("host=h password='x?y' dbname=d", "host=h password='x?y' dbname=d connect_timeout=7"),
    ],
)
def test_with_connect_timeout_appends_and_keeps_every_byte(dsn, want):
    out = session.with_connect_timeout(dsn, 7)
    assert out == want
    assert out.startswith(dsn)


@pytest.mark.parametrize("dsn", ["host=h password=a\\", "host=h password=a\\\\\\"])
def test_with_connect_timeout_refuses_an_odd_trailing_backslash_run(dsn):
    with pytest.raises(session.PostgresSnapshotError) as ei:
        session.with_connect_timeout(dsn, 7)
    assert ei.value.code == "source_unreachable"
    assert ei.value.__cause__ is None and ei.value.__context__ is None
    assert "password" not in str(ei.value) and "host=h" not in repr(ei.value)


def test_type_postgres_attach_has_one_site():
    assert _attach_hits(_src_sources()) == [("connectors/_postgres_session.py", "type_postgres")]


@pytest.mark.parametrize(
    "seeded",
    [
        "ATTACH '...' AS x (type postgres)",
        "attach 'postgres:dbname=d' AS x",
        "CALL postgres_attach('dbname=d')",
        "SELECT * FROM postgres_scan('dbname=d', 'public', 't')",
        "SELECT * FROM postgres_scan_pushdown('dbname=d', 'public', 't')",
    ],
)
def test_attach_guard_catches_every_seeded_shape(seeded):
    hits = _attach_hits({"other/elsewhere.py": f"q = {seeded!r}\n"})
    assert hits and hits[0][0] == "other/elsewhere.py"


def test_attach_guard_ignores_the_extension_name_query():
    src = "q = \"SELECT 1 FROM duckdb_extensions() WHERE extension_name = 'postgres_scanner'\"\n"
    assert _attach_hits({"x.py": src}) == []


def _src_sources():
    root = Path(session.__file__).resolve().parents[1]
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in root.rglob("*.py")}


_ATTACH_SHAPES = {
    "type_postgres": re.compile(r"type\s+postgres\b", re.I),
    "prefixed_attach": re.compile(r"attach\s+'postgres(ql)?:", re.I),
    "postgres_attach": re.compile(r"postgres_attach\s*\(", re.I),
    "postgres_scan": re.compile(r"postgres_scan(_pushdown)?\s*\(", re.I),
}


def _attach_hits(sources):
    hits = []
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                hits.extend(
                    (path, name) for name, rx in _ATTACH_SHAPES.items() if rx.search(node.value)
                )
    return hits
