"""Session helpers shared by the Postgres connectors (no database needed)."""

from __future__ import annotations

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
