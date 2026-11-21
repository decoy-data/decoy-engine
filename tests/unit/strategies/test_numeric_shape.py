"""COLUMN-SHAPE E3: `bucketize`, `top_code` and `fpe` read a column's shape.

Text (CSV, fixed width, a string column) needs an F06 numeric declaration. A typed number runs
as it does today. A decimal runs under `bucketize` only when float64 buckets it exactly. A date,
a boolean or a wide decimal is refused at compile with a coded reason.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.contracts.bucketize_width import BUCKETIZE_PRESETS
from decoy_engine.contracts.column_shape import NO_SOURCES, ColumnShape, SourceFacts
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies._bucketize import BucketizeStrategyHandler
from decoy_engine.execution._strategies._top_code import TopCodeStrategyHandler
from decoy_engine.plan import PlanCompileError, run_config_only_checks
from decoy_engine.plan._compile import compile_plan
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.plan.checks import check_required_strategy_settings
from decoy_engine.plan.checks._column_shapes import build_column_shapes
from decoy_engine.profile._source import profile_source
from tests._declared_schema import declare_rest
from tests.acceptance._f06_support import (
    DEC_5_2,
    INT64,
    column,
    config,
    run,
    text_table,
    validate,
    write_csv,
)

S = ColumnShape
TOP = {"cap": 89, "over_label": "90+"}
DEC_12_2 = {"id": "decimal/plain/v1", "precision": 12, "scale": 2}
DEC_15_2 = {"id": "decimal/plain/v1", "precision": 15, "scale": 2}
DEC_16_2 = {"id": "decimal/plain/v1", "precision": 16, "scale": 2}
MARKER = "SECRET-MARKER-7431"
FULL = {"execution_mode": "full_frame", "auto_chunk": False}
CHUNKED = {"auto_chunk": True, "chunk_size_rows": 2, "auto_chunk_threshold_rows": 1}
ROUTES = {"full_frame": FULL, "chunked": CHUNKED}


def _declared(logical: str, parse_format: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"logical_type": logical, "parse_format": parse_format, **fields}


def _csv_cfg(tmp_path: Path, col: dict[str, Any], rows: list[list[str]] | None = None) -> dict:
    src = write_csv(tmp_path / "s.csv", [col["name"]], rows or [["1"]])
    return config([col], source_path=src)


def _parquet_cfg(tmp_path: Path, table: pa.Table, col: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / "s.parquet"
    pq.write_table(table, path)
    return {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {"people": {"type": "file", "format": "parquet", "path": str(path)}},
        "tables": [{"name": "people", "columns": [col]}],
        "targets": {"people": {"type": "file", "format": "csv", "path": str(path) + ".out"}},
        "relationships": [],
        "namespaces": {},
    }


def _compile(cfg: dict[str, Any], supplied: dict[str, Any] | None = None) -> Any:
    valid = validate(cfg)
    profile = profile_source(valid, seed=7, supplied_sources=supplied)
    return compile_plan(valid, profile, decoy_engine_version="t", sources=NO_SOURCES)


def _code(cfg: dict[str, Any], supplied: dict[str, Any] | None = None) -> str:
    with pytest.raises(PlanCompileError) as exc:
        _compile(cfg, supplied)
    return exc.value.code


def _out(result: Any, name: str) -> list[Any]:
    return result.outputs["people"].column(name).to_pylist()


def _num(strategy: str, pc: dict[str, Any], name: str = "n", **fields: Any) -> dict[str, Any]:
    return column(name, strategy, provider_config=pc, **fields)


# -- change (3): text needs an F06 numeric declaration -----------------------------------------


@pytest.mark.parametrize(("strategy", "pc"), [("top_code", TOP), ("bucketize", {"width": 10})])
def test_csv_without_declaration_refused(tmp_path: Path, strategy: str, pc: dict[str, Any]) -> None:
    cfg = _csv_cfg(tmp_path, _num(strategy, pc), [["42"]])
    assert _code(cfg) == "column_shape_required"
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(validate(cfg))
    assert exc.value.code == "column_shape_required"
    assert exc.value.path.endswith("columns.n.logical_type")


def test_csv_top_code_without_declaration_refused(tmp_path: Path) -> None:
    cfg = _csv_cfg(tmp_path, _num("top_code", TOP))
    assert _code(cfg) == "column_shape_required"


def test_csv_bucketize_without_declaration_refused(tmp_path: Path) -> None:
    cfg = _csv_cfg(tmp_path, _num("bucketize", {"width": 10}))
    assert _code(cfg) == "column_shape_required"


def test_string_declaration_is_not_a_numeric_declaration(tmp_path: Path) -> None:
    col = _num("top_code", TOP, **_declared("string", {"id": "string/utf8/v1"}))
    shapes = build_column_shapes(
        {"tables": [{"name": "people", "columns": [col]}]}, sources=NO_SOURCES
    )
    assert shapes == {("people", "n"): S.TEXT}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_csv_top_code_with_integer_declaration_runs_on_every_route(
    tmp_path: Path, route: str
) -> None:
    col = _num("top_code", TOP, **_declared("integer", INT64))
    cfg = _csv_cfg(tmp_path, col)
    ages = ["42", "95", "7", "90", "89", None]
    result = run(cfg, {"people": text_table(n=ages)}, **ROUTES[route])
    assert _out(result, "n") == ["42", "90+", "7", "90+", "89", None]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_csv_bucketize_with_integer_declaration_runs_on_every_route(
    tmp_path: Path, route: str
) -> None:
    col = _num("bucketize", {"width": 10, "format": "range"}, **_declared("integer", INT64))
    cfg = _csv_cfg(tmp_path, col)
    result = run(cfg, {"people": text_table(n=["42", "7", "100", "19", "20"])}, **ROUTES[route])
    assert _out(result, "n")[:3] == ["40-49", "0-9", "100-109"]


def _fk_cfg(tmp_path: Path, numeric: dict[str, Any]) -> dict[str, Any]:
    """Two tables under a relationship: the route the engine calls sequential."""
    par = write_csv(tmp_path / "par.csv", ["id"], [["1"]])
    chi = write_csv(tmp_path / "chi.csv", ["pid", "n"], [["1", "1"]])
    hashed = {"strategy": "hash", "namespace": "ns", "deterministic": True}
    cfg = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {
            "parent": {"type": "file", "format": "csv", "has_header": True, "path": par},
            "child": {"type": "file", "format": "csv", "has_header": True, "path": chi},
        },
        "tables": [
            {"name": "parent", "columns": [{"name": "id", **hashed}]},
            {"name": "child", "columns": [{"name": "pid", **hashed}, numeric]},
        ],
        "targets": {
            "parent": {"type": "file", "format": "csv", "path": par + ".o"},
            "child": {"type": "file", "format": "csv", "path": chi + ".o"},
        },
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["pid"]}],
                "orphan_policy": "remap",
                "namespace": "ns",
            }
        ],
        "namespaces": {},
    }
    return declare_rest(cfg)


@pytest.mark.parametrize(
    ("strategy", "pc", "want"),
    [
        ("top_code", TOP, ["42", "90+", "7"]),
        ("bucketize", {"width": 10, "format": "range"}, ["40-49", "90-99", "0-9"]),
    ],
)
def test_integer_declaration_runs_on_the_sequential_route(
    tmp_path: Path, strategy: str, pc: dict[str, Any], want: list[str]
) -> None:
    cfg = _fk_cfg(tmp_path, _num(strategy, pc, **_declared("integer", INT64)))
    sources = {
        "parent": text_table(id=["1", "2", "3"]),
        "child": text_table(pid=["1", "2", "3"], n=["42", "95", "7"]),
    }
    result = run(cfg, sources, execution_mode="sequential")
    assert result.outputs["child"].column("n").to_pylist() == want


def test_csv_top_code_decimal_declaration_refused(tmp_path: Path) -> None:
    col = _num("top_code", TOP, **_declared("decimal", DEC_5_2))
    assert _code(_csv_cfg(tmp_path, col)) == "column_shape_mismatch"


def test_parquet_decimal_under_top_code_refused(tmp_path: Path) -> None:
    table = pa.table({"n": pa.array([Decimal("1.50")], pa.decimal128(10, 2))})
    cfg = _parquet_cfg(tmp_path, table, _num("top_code", TOP))
    assert _code(cfg) == "column_shape_mismatch"


# -- the decimal cut of section 3.2 ------------------------------------------------------------


def test_csv_bucketize_decimal_declaration_range_format(tmp_path: Path) -> None:
    col = _num("bucketize", {"width": 10000, "format": "range"}, **_declared("decimal", DEC_12_2))
    cfg = _csv_cfg(tmp_path, col)
    rows = ["12345.67", "0.00", "29999.99", "30000.00"]
    got = _out(run(cfg, {"people": text_table(n=rows)}, **FULL), "n")
    assert got == ["10000-19999", "0-9999", "20000-29999", "30000-39999"]


BOUNDS = ["29999.99", "30000.00", "9999999999999.99", "0.01", "10000.00", "9999.99"]


def _expected_lower(values: list[str], width: int) -> list[str]:
    return [str(int(Decimal(v) // width) * width) for v in values]


def test_bucketize_decimal_boundary_exact_text(tmp_path: Path) -> None:
    col = _num("bucketize", {"width": 10000}, **_declared("decimal", DEC_15_2))
    cfg = _csv_cfg(tmp_path, col)
    got = _out(run(cfg, {"people": text_table(n=BOUNDS)}, **FULL), "n")
    assert got == _expected_lower(BOUNDS, 10000)


def test_bucketize_decimal_boundary_exact_typed(tmp_path: Path) -> None:
    table = pa.table({"n": pa.array([Decimal(v) for v in BOUNDS], pa.decimal128(15, 2))})
    cfg = _parquet_cfg(tmp_path, table, _num("bucketize", {"width": 10000}))
    got = _out(run(cfg, {"people": table}, **FULL), "n")
    assert got == _expected_lower(BOUNDS, 10000)


def test_bucketize_wide_decimal_refused(tmp_path: Path) -> None:
    col = _num("bucketize", {"width": 10}, **_declared("decimal", DEC_16_2))
    assert _code(_csv_cfg(tmp_path, col)) == "column_shape_mismatch"
    table = pa.table({"n": pa.array([Decimal("1.50")], pa.decimal128(20, 2))})
    assert _code(_parquet_cfg(tmp_path, table, _num("bucketize", {"width": 10}))) == (
        "column_shape_mismatch"
    )


def test_bucketize_decimal_non_integer_width_refused(tmp_path: Path) -> None:
    col = _num("bucketize", {"width": 0.1}, **_declared("decimal", DEC_12_2))
    assert _code(_csv_cfg(tmp_path, col)) == "column_shape_mismatch"
    table = pa.table({"n": pa.array([Decimal("1.50")], pa.decimal128(12, 2))})
    assert _code(_parquet_cfg(tmp_path, table, _num("bucketize", {"width": 2.5}))) == (
        "column_shape_mismatch"
    )


def _shape_cfg(strategy: str, pc: dict[str, Any], **fields: Any) -> dict[str, Any]:
    col = {"name": "n", "strategy": strategy, "provider_config": pc, **fields}
    return {"tables": [{"name": "people", "columns": [col]}]}


def test_bucketize_negative_scale_decimal_refused() -> None:
    schema = {"people": pa.schema([("n", pa.decimal128(15, -5))])}
    cfg = _shape_cfg("bucketize", {"width": 10})
    shapes = build_column_shapes(cfg, sources=SourceFacts(schemas=schema))
    assert shapes == {("people", "n"): S.DECIMAL_WIDE}
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(cfg, sources=NO_SOURCES, shapes=shapes)
    assert exc.value.code == "column_shape_mismatch"
    declared = _shape_cfg(
        "bucketize",
        {"width": 10},
        logical_type="decimal",
        parse_format={"id": "decimal/plain/v1", "precision": 15, "scale": -5},
    )
    with pytest.raises(PlanCompileError) as exc2:
        run_config_only_checks(declared)
    assert exc2.value.code == "column_shape_mismatch"


@pytest.mark.parametrize("width", [0, 10**15 + 1, 2**63])
def test_bucketize_decimal_width_out_of_range_refused(width: int) -> None:
    cfg = _shape_cfg("bucketize", {"width": width})
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(
            cfg, sources=NO_SOURCES, shapes={("people", "n"): S.DECIMAL}
        )
    assert exc.value.code == "column_shape_mismatch"


@pytest.mark.parametrize("width", [1, 10**15])
def test_bucketize_decimal_width_in_range_admitted(width: int) -> None:
    check_required_strategy_settings(
        _shape_cfg("bucketize", {"width": width}),
        sources=NO_SOURCES,
        shapes={("people", "n"): S.DECIMAL},
    )


@pytest.mark.parametrize("preset", sorted(BUCKETIZE_PRESETS))
def test_bucketize_decimal_preset_runs(tmp_path: Path, preset: str) -> None:
    values = ["0.00", "1.50", "99.99", "12345.67", "9999999999.99"]
    width = BUCKETIZE_PRESETS[preset]
    want = _out(
        run(
            _csv_cfg(
                tmp_path, _num("bucketize", {"width": width}, **_declared("decimal", DEC_12_2))
            ),
            {"people": text_table(n=values)},
            **FULL,
        ),
        "n",
    )
    declared = _csv_cfg(
        tmp_path, _num("bucketize", {"preset": preset}, **_declared("decimal", DEC_12_2))
    )
    assert _out(run(declared, {"people": text_table(n=values)}, **FULL), "n") == want
    table = pa.table({"n": pa.array([Decimal(v) for v in values], pa.decimal128(12, 2))})
    typed = _parquet_cfg(tmp_path, table, _num("bucketize", {"preset": preset}))
    assert _out(run(typed, {"people": table}, **FULL), "n") == want


# -- typed sources -----------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["top_code", "bucketize"])
@pytest.mark.parametrize("dtype", [pa.int64(), pa.int32(), pa.float64()])
def test_parquet_number_runs_without_declaration(
    tmp_path: Path, strategy: str, dtype: pa.DataType
) -> None:
    table = pa.table({"n": pa.array([42, 95, 7], dtype)})
    pc = TOP if strategy == "top_code" else {"width": 10, "format": "range"}
    cfg = _parquet_cfg(tmp_path, table, _num(strategy, pc))
    plan = _compile(cfg)
    assert [(c.column, c.shape) for c in plan.column_shapes] == [
        ("n", S.FLOAT if dtype == pa.float64() else S.INTEGER)
    ]
    got = _out(run(cfg, {"people": table}, **FULL), "n")
    assert got[0] in ("42", "40-49")


@pytest.mark.parametrize("strategy", ["top_code", "bucketize"])
def test_parquet_int_runs_without_declaration(tmp_path: Path, strategy: str) -> None:
    table = pa.table({"n": pa.array([42, 95, 7], pa.int64())})
    pc = TOP if strategy == "top_code" else {"width": 10, "format": "range"}
    cfg = _parquet_cfg(tmp_path, table, _num(strategy, pc))
    got = _out(run(cfg, {"people": table}, **FULL), "n")
    assert got == (["42", "90+", "7"] if strategy == "top_code" else ["40-49", "90-99", "0-9"])


@pytest.mark.parametrize("strategy", ["top_code", "bucketize"])
def test_parquet_date_under_numeric_strategy_refused(tmp_path: Path, strategy: str) -> None:
    table = pa.table({"n": pa.array([date(2024, 1, 15)], pa.date32())})
    pc = TOP if strategy == "top_code" else {"width": 10}
    assert _code(_parquet_cfg(tmp_path, table, _num(strategy, pc))) == "column_shape_mismatch"


def test_parquet_date_under_bucketize_refused(tmp_path: Path) -> None:
    table = pa.table({"n": pa.array([date(2024, 1, 15)], pa.date32())})
    cfg = _parquet_cfg(tmp_path, table, _num("bucketize", {"width": 10}))
    assert _code(cfg) == "column_shape_mismatch"


@pytest.mark.parametrize(
    "arrow",
    [pa.bool_(), pa.timestamp("us"), pa.timestamp("us", tz="UTC"), pa.binary()],
)
def test_other_types_under_numeric_strategy_refused(arrow: pa.DataType) -> None:
    cfg = _shape_cfg("top_code", TOP)
    shapes = build_column_shapes(
        cfg, sources=SourceFacts(schemas={"people": pa.schema([("n", arrow)])})
    )
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(cfg, sources=NO_SOURCES, shapes=shapes)
    assert exc.value.code == "column_shape_mismatch"


# -- fpe ---------------------------------------------------------------------------------------


def _fpe(name: str = "n") -> dict[str, Any]:
    return column(name, "fpe", namespace="ns", provider_config={"charset": "digits"})


def test_fpe_float_refused_integer_runs_text_runs(tmp_path: Path) -> None:
    floats = pa.table({"n": pa.array([1.5, 2.5], pa.float64())})
    assert _code(_parquet_cfg(tmp_path, floats, _fpe())) == "column_shape_mismatch"
    ints = pa.table({"n": pa.array([123456, 456789], pa.int64())})
    got = _out(run(_parquet_cfg(tmp_path, ints, _fpe()), {"people": ints}, **FULL), "n")
    assert len(got) == 2 and all(isinstance(v, str) and v.isdigit() for v in got)
    text = _csv_cfg(tmp_path, _fpe(), [["123456"]])
    got = _out(run(text, {"people": text_table(n=["123456", "456789"])}, **FULL), "n")
    assert len(got) == 2 and all(len(v) == 6 for v in got)


@pytest.mark.parametrize(
    "arrow",
    [
        pa.date32(),
        pa.timestamp("us"),
        pa.timestamp("us", tz="UTC"),
        pa.decimal128(10, 2),
        pa.bool_(),
    ],
)
def test_fpe_refuses_dates_decimals_and_booleans(arrow: pa.DataType) -> None:
    cfg = _shape_cfg("fpe", {"charset": "digits"}, namespace="ns")
    shapes = build_column_shapes(
        cfg, sources=SourceFacts(schemas={"people": pa.schema([("n", arrow)])})
    )
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(cfg, sources=NO_SOURCES, shapes=shapes)
    assert exc.value.code == "column_shape_mismatch"


def test_fpe_on_unknown_is_not_refused() -> None:
    cfg = _shape_cfg("fpe", {"charset": "digits"}, namespace="ns")
    run_config_only_checks(cfg)
    check_required_strategy_settings(cfg, sources=NO_SOURCES, shapes={("people", "n"): S.UNKNOWN})


# -- nested children read text -----------------------------------------------------------------


def test_nested_bucketize_child_needs_a_declaration() -> None:
    col = {
        "name": "doc",
        "strategy": "nested",
        "provider_config": {
            "strategy": "bucketize",
            "target": "$.a",
            "strategy_config": {"width": 5},
        },
    }
    cfg = {"tables": [{"name": "people", "columns": [col]}]}
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(
            cfg, sources=NO_SOURCES, shapes={("people", "doc"): S.TEXT}
        )
    assert exc.value.code == "column_shape_required"


# -- the handler backstop ----------------------------------------------------------------------


def _seed(strategy: str, **pc: Any) -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy=strategy,
        provider=strategy,
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(sorted(pc.items())),
        coherent_with=(),
    )


def _ctx(shapes: dict[tuple[str, str], ColumnShape] | None = None) -> StrategyContext:
    stub: Any = SimpleNamespace()
    return StrategyContext(
        registry=stub,
        pool_cache=stub,
        relationship_graph=stub,
        namespace_registry=stub,
        job_seed=b"\x00" * 8,
        current_table="t",
        column_shapes=shapes or {},
    )


@pytest.mark.parametrize(
    ("handler", "strategy", "pc"),
    [
        (BucketizeStrategyHandler, "bucketize", {"width": 10}),
        (TopCodeStrategyHandler, "top_code", TOP),
    ],
)
def test_handler_refuses_unlisted_column(handler: Any, strategy: str, pc: dict[str, Any]) -> None:
    frame = pd.DataFrame({"n": ["42", MARKER]})
    for shapes in (
        None,
        {("t", "n"): S.TEXT},
        {("t", "n"): S.UNKNOWN},
        {("t", "other"): S.INTEGER},
    ):
        with pytest.raises(StrategyError) as exc:
            handler().run(frame.copy(), "n", _seed(strategy, **pc), _ctx(shapes))
        assert exc.value.code == "column_shape_required"
        assert MARKER not in str(exc.value)
    out, _ = handler().run(
        pd.DataFrame({"n": [42, 95]}), "n", _seed(strategy, **pc), _ctx({("t", "n"): S.INTEGER})
    )
    assert len(out) == 2


# -- failure policy and messages ---------------------------------------------------------------


def test_bad_cell_follows_error_policy_fail(tmp_path: Path) -> None:
    col = _num("top_code", TOP, **_declared("integer", INT64, error_policy="fail"))
    cfg = _csv_cfg(tmp_path, col)
    with pytest.raises(Exception) as exc:
        run(cfg, {"people": text_table(n=["42", MARKER])}, **FULL)
    assert MARKER not in str(exc.value)


@pytest.mark.parametrize(
    ("strategy", "pc", "arrow"),
    [
        ("top_code", TOP, pa.date32()),
        ("bucketize", {"width": 10}, pa.decimal128(20, 2)),
        ("bucketize", {"width": 10}, pa.string()),
    ],
)
def test_messages_value_free(strategy: str, pc: dict[str, Any], arrow: pa.DataType) -> None:
    cfg = _shape_cfg(strategy, {**pc, "note": MARKER})
    shapes = build_column_shapes(
        cfg, sources=SourceFacts(schemas={"people": pa.schema([("n", arrow)])})
    )
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(cfg, sources=NO_SOURCES, shapes=shapes)
    assert MARKER not in exc.value.message and MARKER not in exc.value.path
    assert "people" in exc.value.message and "'n'" in exc.value.message


# -- the plan records the shape, and F06 proves the widened strategies -------------------------


def test_plan_records_the_shape_of_each_numeric_column(tmp_path: Path) -> None:
    table = pa.table({"a": pa.array([1], pa.int64()), "b": pa.array([1.5], pa.float64())})
    cfg = _parquet_cfg(tmp_path, table, _num("bucketize", {"width": 5}, name="a"))
    cfg["tables"][0]["columns"].append(_num("top_code", TOP, name="b"))
    plan = _compile(cfg)
    assert [(c.column, c.shape) for c in plan.column_shapes] == [
        ("a", S.INTEGER),
        ("b", S.FLOAT),
    ]


@pytest.mark.parametrize("fmt", ["lower", "range", "midpoint"])
def test_f06_proves_bucketize_on_decimal_for_every_format(fmt: str) -> None:
    from decoy_engine.plan._checks_declared_casting import strategy_output_logical

    pc = {"width": 10, "format": fmt}
    assert strategy_output_logical("bucketize", pc, "decimal") == "string"
    assert strategy_output_logical("bucketize", {"width": 2.5, "format": fmt}, "decimal") is None
    assert strategy_output_logical("bucketize", {"preset": "by_decade"}, "decimal") == "string"


def test_f06_proves_top_code_on_integer_only() -> None:
    from decoy_engine.plan._checks_declared_casting import strategy_output_logical

    assert strategy_output_logical("top_code", TOP, "integer") == "string"
    for logical in ("decimal", "currency", "date", "string"):
        assert strategy_output_logical("top_code", TOP, logical) is None
