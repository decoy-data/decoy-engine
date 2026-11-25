"""F31 engine canary corpus (AE6): a planted marker must not reach any engine text surface.

Each cell plants `CANARY` in one place (a cell, an expression literal, a password), drives one
failure shape, asserts that the failure path ran (exception class and reason code) and then asserts
the marker is absent from every surface `observe` collects: the exception in all its forms and its
cause chain, DEBUG log records on a stream and a file handler, warnings, progress events, the
run-result quality fields and, once it exists, `render_failure(exc)`.

Cells marked `leak_xfail` were run on main first and observed to leak. The reason names the slice
that closes the leak or the V2-LOG entry that records it; the mark is strict, so the fixing slice's
own merge flips it. A cell that never reached its site fails (`assert_path_ran` uses `pytest.fail`),
because the mark absorbs only an AssertionError.

A cell that stops at a boundary before the site is listed in the PR body, not given a cell here.
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

from decoy_engine import run_config_only_checks, run_mask_chunked, run_pipeline, validate_config
from decoy_engine.config import PipelineConfig
from decoy_engine.execution.capacity import estimate_job_capacity
from decoy_engine.execution.native._chunked_schema_rule import SchemaRule, normalize_chunk
from decoy_engine.expressions._lark_parser import compile_expr
from decoy_engine.profile._source import profile_source
from decoy_engine.profiling.scan_set import scan_sources
from decoy_engine.unmask import unmask_pipeline
from tests._f31_canary import (
    CANARY,
    Observed,
    assert_no_canary,
    assert_path_ran,
    leak_xfail,
    observe,
)
from tests.connectors.conftest import (
    ext_dir,  # noqa: F401 - the shared fixture and its DECOY_REQUIRE_PG policy
)

_TABLE = "records"
_VERSION = "f31-canary"
_KEY = b"\x00" * 32


def _provider() -> Any:
    from decoy_engine.keyprovider import SecretKeyProvider

    return SecretKeyProvider(secret=_KEY, key_version="v1")


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


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _chunked_rule() -> SchemaRule:
    return SchemaRule(string_columns=frozenset({"c"}), passthrough_types={}, passthrough_fields={})


def _normalize(produced: pa.Table, source: pa.Table, tmp_path: Path) -> Observed:
    return observe(
        normalize_chunk, tmp_path, rule=_chunked_rule(), produced=produced, source=source,
        table="t", chunk_index=1,
    )  # fmt: skip


def _cell_chunked_cast(tmp_path: Path) -> Observed:
    bad = pa.array([CANARY.encode() + b"\xff"], pa.binary())
    produced = pa.table({"c": bad})
    return _normalize(produced, produced, tmp_path)


def _cell_chunked_cast_string_source(tmp_path: Path) -> Observed:
    """The marker is a string in the source and inside a nested produced column. A list column
    cannot cast to string, and its repr shows the text (a binary column's repr is hex)."""
    produced = pa.table({"c": pa.array([[CANARY]], pa.list_(pa.string()))})
    source = pa.table({"c": pa.array([CANARY], pa.string())})
    return _normalize(produced, source, tmp_path)


def _drain(*args: Any, **kwargs: Any) -> list[pa.Table]:
    return list(run_mask_chunked(*args, **kwargs))


def _cell_chunked_route(tmp_path: Path) -> Observed:
    """`run_mask_chunked`: a passthrough column changes type between chunks, value in chunk 2."""
    cfg = _config(
        [{"name": "s", "strategy": "redact"}, {"name": "p", "strategy": "passthrough"}], tmp_path
    )
    first = pa.table({"s": pa.array(["a", "b"]), "p": pa.array([1, 2], pa.int64())})
    second = pa.table({"s": pa.array(["c", "d"]), "p": pa.array(["3", CANARY])})
    return observe(
        _drain, tmp_path, config=cfg, chunks=[first, second], table=_TABLE,
        engine_version=_VERSION, key_provider=_provider(),
    )  # fmt: skip


def _cell_capacity(tmp_path: Path) -> Observed:
    (tmp_path / "in.csv").write_text(f"a,b\n1,2\n3,4,{CANARY}\n", encoding="utf-8")
    cols = [{"name": "a", "strategy": "passthrough"}, {"name": "b", "strategy": "passthrough"}]
    cfg = _config(cols, tmp_path)
    return observe(estimate_job_capacity, tmp_path, config_dump=cfg, base_dir=tmp_path)


_EXPRESSION = f'"{CANARY}\\x"'


def _cell_expression(tmp_path: Path) -> Observed:
    return observe(compile_expr, tmp_path, expr_string=_EXPRESSION)


def _derived_columns() -> list[dict[str, Any]]:
    return [
        {"name": "a", "strategy": "passthrough"},
        {"name": "b", "strategy": "derived", "provider_config": {"expression": _EXPRESSION}},
    ]


def _cell_expression_run(tmp_path: Path) -> Observed:
    return _run_pipeline_cell(_derived_columns(), pd.DataFrame({"a": ["1"], "b": ["2"]}), tmp_path)


def _cell_expression_validate(tmp_path: Path) -> Observed:
    """`decoy validate`'s engine entry. It swallows the compile error (`_checks.py:636`, the run
    reports it), so the cell proves the check ran and wrote nothing, not that it raised."""
    pd.DataFrame({"a": ["1"], "b": ["2"]}).to_csv(tmp_path / "in.csv", index=False)
    cfg = _config(_derived_columns(), tmp_path)
    return observe(run_config_only_checks, tmp_path, config=cfg, base_dir=tmp_path)


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


_DATE_COLUMNS = [
    {
        "name": "d",
        "strategy": "date_shift",
        "namespace": "d_ns",
        "provider_config": {"min_days": -3, "max_days": 3, "date_format": "%Y-%m-%d"},
    }
]


def _cell_date_parse(tmp_path: Path) -> Observed:
    frame = pd.DataFrame({"d": ["2020-01-01", CANARY, "2020-01-03"]})
    return _run_pipeline_cell(_DATE_COLUMNS, frame, tmp_path)


_DATE_PARSE_REASON = "value is not a parseable date under date_shift"


def _check_row_error_reasons(seen: Observed) -> None:
    """The failure is a row error, and each record names its reason by registered code."""
    records = getattr(seen.exc, "records", ())
    if not records:
        pytest.fail("the failure carried no row-error records")
    reasons = {(r.trigger, r.reason) for r in records}
    if reasons != {("format_error", _DATE_PARSE_REASON)}:
        pytest.fail(f"unexpected row-error reasons: {sorted(reasons)}")


_FPE_COLUMNS = [
    {
        "name": "acct",
        "strategy": "fpe",
        "namespace": "acct_ns",
        "provider_config": {"charset": "digits", "preserve_separators": False},
    }
]


def _cell_fpe_domain(tmp_path: Path) -> Observed:
    frame = pd.DataFrame({"acct": ["12345678", CANARY, "87654321"]})
    return _run_pipeline_cell(_FPE_COLUMNS, frame, tmp_path)


def _cell_tokenize_without_vault(tmp_path: Path) -> Observed:
    cols = [{"name": "t", "strategy": "tokenize", "namespace": "t_ns"}]
    return _run_pipeline_cell(cols, pd.DataFrame({"t": ["a", CANARY]}), tmp_path)


def _cell_unmask(tmp_path: Path) -> Observed:
    cfg = _config(_FPE_COLUMNS, tmp_path)
    masked = pa.table({"acct": pa.array(["12345678", CANARY], pa.string())})
    return observe(
        unmask_pipeline,
        tmp_path,
        config=cfg,
        masked_sources={_TABLE: masked},
        key_provider=_provider(),
    )


# The config fields below carry a declared default (`,` for a delimiter, `fail` for
# on_pool_exhaustion). A caller who overrides the default with a bad value must get a refusal
# that names the field, never the value.
def _default_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    (tmp_path / "in.csv").write_text("a\n1\n", encoding="utf-8")
    cfg = _config([{"name": "a", "strategy": "passthrough"}], tmp_path)
    for dotted, value in overrides.items():
        *path, leaf = dotted.split("__")
        node = cfg
        for key in path:
            node = node[key]
        node[leaf] = value
    return cfg


def _cell_default_validate_delimiter(tmp_path: Path) -> Observed:
    cfg = _default_config(tmp_path, sources__records__delimiter=CANARY)
    return observe(validate_config, tmp_path, config=cfg)


def _cell_default_validate_pool(tmp_path: Path) -> Observed:
    cfg = _default_config(tmp_path, global_settings__on_pool_exhaustion=CANARY)
    return observe(validate_config, tmp_path, config=cfg)


def _cell_default_scan(tmp_path: Path) -> Observed:
    cfg = _default_config(tmp_path, sources__records__delimiter=CANARY)
    return observe(scan_sources, tmp_path, sources=cfg["sources"])


def _cell_default_profile(tmp_path: Path) -> Observed:
    cfg = _default_config(tmp_path, sources__records__delimiter=CANARY)
    return observe(profile_source, tmp_path, config=cfg)


@pytest.fixture
def closed_port() -> Any:
    """A local port with nothing listening: a connect is refused at once."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    return port


def _cell_connector_scan(tmp_path: Path, port: int, monkeypatch: pytest.MonkeyPatch) -> Observed:
    """`scan_sources` over an S3 source. The marker is in the key and the credentials reference;
    the engine takes no raw secret, so the closest it gets to a password is that reference."""
    for name, value in (
        ("AWS_ACCESS_KEY_ID", "f31"),
        ("AWS_SECRET_ACCESS_KEY", "f31"),
        ("AWS_MAX_ATTEMPTS", "1"),
        ("AWS_EC2_METADATA_DISABLED", "true"),
    ):
        monkeypatch.setenv(name, value)
    source = {
        "type": "s3",
        "format": "csv",
        "bucket": "bkt",
        "key": f"{CANARY}/in.csv",
        "endpoint_url": f"http://127.0.0.1:{port}",
        "region": "us-east-1",
        "credentials_ref": CANARY,
    }
    return observe(scan_sources, tmp_path, sources={_TABLE: source})


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


_LARK_LEAK = "AE5 (#810) rewrites _lark_parser.py:241 to a value-free message"

# (id, builder, expected exception code, expected exception class name, extra path check, marks)
_CELLS: list[Any] = [
    ("chunked_cast_out_of_range", _cell_chunked_cast, "chunked_schema_mismatch", None, None, []),
    (
        "chunked_cast_string_source",
        _cell_chunked_cast_string_source,
        "chunked_schema_mismatch",
        None,
        None,
        [],
    ),
    (
        "chunked_route_type_drift",
        _cell_chunked_route,
        "native_chunk_schema_drift",
        "NativeChunkSchemaDriftError",
        None,
        [],
    ),
    (
        "capacity_malformed_csv_row",
        _cell_capacity,
        "capacity_source_unprofilable",
        None,
        None,
        [],
    ),
    (
        "expression_bad_string_escape",
        _cell_expression,
        None,
        "ValidationError",
        None,
        [leak_xfail(_LARK_LEAK)],
    ),
    (
        "expression_bad_string_escape_run",
        _cell_expression_run,
        None,
        "ValidationError",
        None,
        [leak_xfail(_LARK_LEAK)],
    ),
    ("numeric_cast_failure", _cell_numeric_cast, "declared_integer_invalid", None, None, []),
    (
        "date_parse_failure",
        _cell_date_parse,
        None,
        "RowErrorsFailedError",
        _check_row_error_reasons,
        [],
    ),
    ("fpe_out_of_domain", _cell_fpe_domain, "fpe_unencryptable_value", None, None, []),
    (
        "tokenize_without_vault",
        _cell_tokenize_without_vault,
        "tokenize_requires_vault",
        None,
        None,
        [],
    ),
    ("unmask_mismatch", _cell_unmask, "fpe.unencryptable", None, None, []),
    (
        "config_default_validate_delimiter",
        _cell_default_validate_delimiter,
        None,
        "PipelineValidationError",
        None,
        [],
    ),
    (
        "config_default_validate_pool_policy",
        _cell_default_validate_pool,
        None,
        "PipelineValidationError",
        None,
        [],
    ),
    ("config_default_scan", _cell_default_scan, None, "PipelineConfigError", None, []),
    ("config_default_profile", _cell_default_profile, None, "ConfigError", None, []),
]

_CELL_PARAMS = [
    pytest.param(build, code, exc_name, check, id=cell_id, marks=marks)
    for cell_id, build, code, exc_name, check, marks in _CELLS
]


@pytest.mark.parametrize(("build", "code", "exc_name", "check"), _CELL_PARAMS)
def test_corpus_cell(
    build: Callable[[Path], Observed],
    code: str | None,
    exc_name: str | None,
    check: Callable[[Observed], None] | None,
    tmp_path: Path,
) -> None:
    seen = build(tmp_path)
    assert_path_ran(seen, code=code, exc_name=exc_name)
    if check is not None:
        check(seen)
    assert_no_canary(seen.surfaces)


def test_expression_validate_ran_and_wrote_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import decoy_engine.expressions as expressions

    real_compile = expressions.compile_expr
    compiled: list[str] = []

    def spy(text: str, *args: Any, **kwargs: Any) -> Any:
        compiled.append(text)
        return real_compile(text, *args, **kwargs)

    monkeypatch.setattr(expressions, "compile_expr", spy)
    seen = _cell_expression_validate(tmp_path)
    if compiled != [_EXPRESSION]:
        pytest.fail("the real expression compiler did not receive the planted expression")
    if seen.exc is not None or "derived_column_refs" not in (seen.result or ()):
        pytest.fail("the derived-column check did not run to completion")
    assert_no_canary(seen.surfaces)


def test_connector_scan_failure(
    tmp_path: Path, closed_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _cell_connector_scan(tmp_path, closed_port, monkeypatch)
    assert_path_ran(seen, code=None, exc_name="TransientError")
    assert_no_canary(seen.surfaces)


def test_connector_auth_failure(tmp_path: Path, ext_dir: Path, closing_port: int) -> None:  # noqa: F811
    seen = _cell_connector_auth(tmp_path, ext_dir, closing_port)
    assert_path_ran(seen, code="source_unreachable")
    assert_no_canary(seen.surfaces)
