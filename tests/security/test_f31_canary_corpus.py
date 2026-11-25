"""F31 engine canary corpus (AE6): a planted marker must not reach any engine text surface.

Each cell plants `CANARY` in one place (a cell, an expression literal, a password), drives one
failure shape, asserts that the failure path ran (exception class and reason code) and then asserts
the marker is absent from every surface `observe` collects: the exception in all its forms and its
cause chain, DEBUG log records on a stream and a file handler, warnings, progress events, the
run-result quality fields and, once it exists, `render_failure(exc)`.

Cells marked `leak_xfail` were run on main first and observed to leak. The reason names the slice
that closes the leak; `strict=True` makes the slice's own merge flip the mark. A cell that leaks
for a reason no open slice covers is marked with "finding" in its reason and reported.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import run_pipeline
from decoy_engine.config import PipelineConfig
from decoy_engine.execution.capacity import estimate_job_capacity
from decoy_engine.execution.native._chunked_schema_rule import SchemaRule, normalize_chunk
from decoy_engine.expressions._lark_parser import compile_expr
from decoy_engine.unmask import unmask_pipeline
from tests.security._f31_canary import CANARY, Observed, observe

_TABLE = "records"
_VERSION = "f31-canary"
_KEY = b"\x00" * 32


def _provider() -> Any:
    from decoy_engine.keyprovider import SecretKeyProvider

    return SecretKeyProvider(secret=_KEY, key_version="v1")


def leak_xfail(reason: str) -> Any:
    return pytest.mark.xfail(strict=True, reason=reason)


def _config(columns: list[dict[str, Any]], tmp_path: Path, fmt: str = "csv") -> dict[str, Any]:
    cfg = {
        "version": 2,
        "global_settings": {"seed": 42},
        "sources": {
            _TABLE: {
                "type": "file",
                "format": fmt,
                "has_header": True,
                "path": str(tmp_path / f"in.{fmt}"),
            }
        },
        "tables": [{"name": _TABLE, "columns": columns}],
        "targets": {_TABLE: {"type": "file", "format": "csv", "path": str(tmp_path / "out.csv")}},
    }
    return PipelineConfig.model_validate(cfg).model_dump()


def _run_pipeline_cell(
    columns: list[dict[str, Any]], frame: pd.DataFrame, tmp_path: Path
) -> Observed:
    cfg = _config(columns, tmp_path)
    frame.to_csv(tmp_path / "in.csv", index=False)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return observe(
        run_pipeline,
        tmp_path,
        with_progress=True,
        config=cfg,
        sources={_TABLE: table},
        engine_version=_VERSION,
        key_provider=_provider(),
    )


def _assert_path_ran(seen: Observed, *, code: str | None, exc_name: str | None = None) -> None:
    assert seen.exc is not None, "the failure path did not run"
    if exc_name is not None:
        assert type(seen.exc).__name__ == exc_name, type(seen.exc).__name__
    if code is not None:
        assert seen.code == code, seen.code


def _assert_no_canary(seen: Observed) -> None:
    leaked = seen.surfaces_with_canary()
    assert not leaked, f"marker reached surfaces: {leaked}"


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _cell_chunked_cast(tmp_path: Path) -> Observed:
    rule = SchemaRule(string_columns=frozenset({"c"}), passthrough_types={}, passthrough_fields={})
    bad = pa.array([CANARY.encode() + b"\xff"], pa.binary())
    produced = pa.table({"c": bad})
    return observe(
        normalize_chunk, tmp_path, rule=rule, produced=produced, source=produced,
        table="t", chunk_index=1,
    )  # fmt: skip


def _cell_capacity(tmp_path: Path) -> Observed:
    (tmp_path / "in.csv").write_text(f"a,b\n1,2\n3,4,{CANARY}\n", encoding="utf-8")
    cols = [{"name": "a", "strategy": "passthrough"}, {"name": "b", "strategy": "passthrough"}]
    cfg = _config(cols, tmp_path)
    return observe(estimate_job_capacity, tmp_path, config_dump=cfg, base_dir=tmp_path)


def _cell_expression(tmp_path: Path) -> Observed:
    return observe(compile_expr, tmp_path, expr_string=f'"{CANARY}\\x"')


def _cell_numeric_cast(tmp_path: Path) -> Observed:
    cols = [
        {
            "name": "v",
            "strategy": "bucketize",
            "provider_config": {"width": 10},
            "logical_type": "integer",
            "parse_format": {"id": "integer/ascii/v1", "signed": True, "bit_width": 64},
        }
    ]
    frame = pd.DataFrame({"v": ["1", CANARY, "3"]})
    return _run_pipeline_cell(cols, frame, tmp_path)


def _cell_date_parse(tmp_path: Path) -> Observed:
    cols = [
        {
            "name": "d",
            "strategy": "date_shift",
            "namespace": "d_ns",
            "provider_config": {"min_days": -3, "max_days": 3, "date_format": "%Y-%m-%d"},
        }
    ]
    frame = pd.DataFrame({"d": ["2020-01-01", CANARY, "2020-01-03"]})
    return _run_pipeline_cell(cols, frame, tmp_path)


def _cell_fpe_domain(tmp_path: Path) -> Observed:
    cols = [
        {
            "name": "acct",
            "strategy": "fpe",
            "namespace": "acct_ns",
            "provider_config": {"charset": "digits", "preserve_separators": False},
        }
    ]
    frame = pd.DataFrame({"acct": ["12345678", CANARY, "87654321"]})
    return _run_pipeline_cell(cols, frame, tmp_path)


def _cell_unmask(tmp_path: Path) -> Observed:
    cfg = _config(
        [
            {
                "name": "acct",
                "strategy": "fpe",
                "namespace": "acct_ns",
                "provider_config": {"charset": "digits", "preserve_separators": False},
            }
        ],
        tmp_path,
    )
    masked = pa.table({"acct": pa.array(["12345678", CANARY], pa.string())})
    provider = _provider()
    return observe(
        unmask_pipeline,
        tmp_path,
        config=cfg,
        masked_sources={_TABLE: masked},
        key_provider=provider,
    )


@pytest.fixture
def closing_port() -> Any:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def close_all() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=close_all, daemon=True).start()
    try:
        yield srv.getsockname()[1]
    finally:
        srv.close()


@pytest.fixture(scope="module")
def pg_extension_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    duckdb = pytest.importorskip("duckdb")
    directory = tmp_path_factory.mktemp("duckdb_ext")
    conn = duckdb.connect(config={"extension_directory": str(directory)})
    try:
        conn.execute("INSTALL postgres")
    except Exception:
        pytest.skip("the DuckDB postgres extension cannot be installed on this host")
    finally:
        conn.close()
    return directory


def _cell_connector_auth(tmp_path: Path, ext: Path, port: int) -> Observed:
    from decoy_engine.connectors.postgres_snapshot import (
        PostgresSnapshotConfig,
        RelationSelection,
        snapshot_tables_to_parquet,
    )

    config = PostgresSnapshotConfig(
        dsn=f"host=127.0.0.1 port={port} user=u password={CANARY} dbname=d",
        extension_directory=ext,
        memory_limit="256MB",
        temp_directory=tmp_path / "spill",
        threads=1,
        row_group_size=1000,
        statement_timeout_s=5,
        deadline_s=20,
    )
    selection = RelationSelection(schema="public", table="t", columns=["a"], order_by=[])
    return observe(
        snapshot_tables_to_parquet,
        tmp_path,
        config=config,
        selections=[selection],
        dest_dir=tmp_path / "dest",
    )


# (id, builder, expected exception code, xfail mark or None)
_CELLS: list[Any] = [
    pytest.param(
        _cell_chunked_cast, "chunked_schema_mismatch", None, id="chunked_cast_out_of_range"
    ),
    pytest.param(
        _cell_capacity,
        "capacity_source_unprofilable",
        None,
        id="capacity_malformed_csv_row",
    ),
    pytest.param(
        _cell_expression,
        None,
        "ValidationError",
        id="expression_bad_string_escape",
        marks=leak_xfail("AE5 (#810) rewrites _lark_parser.py:241 to a value-free message"),
    ),
    pytest.param(_cell_numeric_cast, "declared_integer_invalid", None, id="numeric_cast_failure"),
    pytest.param(_cell_date_parse, None, "RowErrorsFailedError", id="date_parse_failure"),
    pytest.param(_cell_fpe_domain, "fpe_unencryptable_value", None, id="fpe_out_of_domain"),
    pytest.param(_cell_unmask, "fpe.unencryptable", None, id="unmask_mismatch"),
]


@pytest.mark.parametrize(("build", "code", "exc_name"), _CELLS)
def test_corpus_cell(
    build: Callable[[Path], Observed], code: str | None, exc_name: str | None, tmp_path: Path
) -> None:
    seen = build(tmp_path)
    _assert_path_ran(seen, code=code, exc_name=exc_name)
    _assert_no_canary(seen)


def test_connector_auth_failure(tmp_path: Path, pg_extension_dir: Path, closing_port: int) -> None:
    seen = _cell_connector_auth(tmp_path, pg_extension_dir, closing_port)
    _assert_path_ran(seen, code="source_unreachable")
    _assert_no_canary(seen)
