"""COLUMN-SHAPE E2: `bucket_perturb` never detects a format and reads typed dates as they are.

A text column needs `provider_config.date_format`; a missing one is refused at plan compile with
`plan/column_shape_required`. A Parquet, database or Arrow date column needs nothing and keeps its
type. The fixtures carry marker values so the value-free checks can search every message.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons, run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine._execution_error import ExecutionError
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import ColumnShape, source_facts_of
from decoy_engine.declared_casting._boundary import native_date_columns
from decoy_engine.errors import RowErrorsFailedError
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.execution._strategies._bucket_perturb import BucketPerturbStrategyHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.profile._source import profile_source
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from decoy_engine.transforms.bucket_perturb import (
    apply_bucket_perturb,
    apply_bucket_perturb_dates,
)
from tests.native._chunked_entry_support import key_provider

NS = "ns_bucket_typed"
SEED = b"\xb0\x0c\xfe\x00\x12\x34\x56\x78"
MARKERS = ("2031-07-19", "1987-03-11", "2024-02-03")
DATES = [
    dt.date(2031, 7, 19),
    None,
    dt.date(1987, 3, 11),
    dt.date(2024, 2, 3),
    dt.date(2024, 1, 15),
]
ROUTES = ("full_frame", "chunked", "native_chunked")
REQUIRED = reasons.plan.COLUMN_SHAPE_REQUIRED
MISMATCH = reasons.plan.COLUMN_SHAPE_MISMATCH
FORMAT_UNUSED = str(reasons.plan.COLUMN_SHAPE_FORMAT_UNUSED)
BUCKET_OF = {"week": 7, "month": 31, "quarter": 92}


def _cfg(
    directory: Path,
    table: pa.Table,
    *,
    provider_config: dict[str, Any] | None = None,
    bucket: str = "month",
) -> dict[str, Any]:
    pc = {"bucket": bucket, **(provider_config or {})}
    path = directory / "t.parquet"
    pq.write_table(table, path)
    raw: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {"t": {"type": "file", "format": "parquet", "path": str(path)}},
        "targets": {"t": {"type": "file", "format": "csv", "path": "/dev/null.t"}},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {
                        "name": "d",
                        "strategy": "bucket_perturb",
                        "namespace": NS,
                        "provider_config": pc,
                    },
                    {"name": "p", "strategy": "passthrough"},
                ],
            }
        ],
        "relationships": [],
        "namespaces": {},
    }
    return PipelineConfig.model_validate(raw).model_dump()


def _table(values: list[Any], typ: pa.DataType) -> pa.Table:
    return pa.table({"d": pa.array(values, typ), "p": pa.array(range(len(values)), pa.int64())})


def _run(cfg: dict[str, Any], table: pa.Table, route: str) -> pa.Table:
    if route in ("chunked", "native_chunked"):
        chunks = [table.slice(i, 2) for i in range(0, table.num_rows, 2)]
        if route == "chunked":
            out = run_mask_pipeline_chunked(
                cfg,
                chunks,
                table="t",
                engine_version="e2",
                source_schema=table.schema,
                key_provider=key_provider(),
            )
        else:
            out = run_mask_chunked(
                cfg, chunks, table="t", engine_version="e2", key_provider=key_provider()
            )
        return pa.concat_tables(list(out))
    result = run_pipeline(
        cfg,
        {"t": table},
        engine_version="e2",
        execution_mode=route,  # type: ignore[arg-type]
        key_provider=key_provider(),
    )
    return result.outputs["t"]


def _compile(cfg: dict[str, Any], table: pa.Table) -> Any:
    profile = profile_source(cfg, seed=7, supplied_sources={"t": table})
    return compile_plan(
        cfg, profile, decoy_engine_version="e2", sources=source_facts_of({"t": table})
    )


def _same_month(src: list[dt.date | None], out: list[dt.date | None]) -> None:
    assert len(src) == len(out)
    for before, after in zip(src, out, strict=True):
        if before is None:
            assert after is None
        else:
            assert isinstance(after, dt.date)
            assert (after.year, after.month) == (before.year, before.month)
    assert any(a != b for a, b in zip(src, out, strict=True) if a is not None)


# -- text columns need their format -----------------------------------------------------


def test_text_without_format_refused(tmp_path: Path) -> None:
    """Config-only on a CSV source, and compile on a Parquet string column."""
    path = tmp_path / "t.csv"
    path.write_text("d,p\n2024-01-15,1\n", encoding="utf-8")
    cfg = _cfg(tmp_path, _table(DATES, pa.date32()))
    cfg["sources"] = {"t": {"type": "file", "format": "csv", "has_header": True, "path": str(path)}}
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(cfg)  # before any data row is read
    assert exc.value.code == REQUIRED
    assert "provider_config.date_format" in str(exc.value)

    text = pa.table({"d": ["2024-01-15"], "p": pa.array([1], pa.int64())})
    pcfg = _cfg(tmp_path, text)
    run_config_only_checks(pcfg)  # a Parquet column may be a date, so the config alone defers
    with pytest.raises(PlanCompileError) as exc2:
        _compile(pcfg, text)
    assert exc2.value.code == REQUIRED


def test_blank_format_is_refused_like_a_missing_one(tmp_path: Path) -> None:
    text = pa.table({"d": ["2024-01-15"], "p": pa.array([1], pa.int64())})
    with pytest.raises(PlanCompileError) as exc:
        _compile(_cfg(tmp_path, text, provider_config={"date_format": ""}), text)
    assert exc.value.code == REQUIRED


def test_transform_does_not_detect() -> None:
    """Clean ISO values that detection would read still need the format, at the transform."""
    series = pd.Series(["2024-06-15", "2024-08-20"])
    with pytest.raises(TypeError):
        apply_bucket_perturb(series, "month", SEED, "d")  # type: ignore[call-arg]
    for missing in (None, "", "  "):
        with pytest.raises(ExecutionError) as exc:
            apply_bucket_perturb(series, "month", SEED, "d", missing)  # type: ignore[arg-type]
        assert exc.value.code == reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT
        assert "2024" not in str(exc.value)


def test_explicit_format_output_is_pinned() -> None:
    """Valid text input gives the bytes it gave before detection was removed (taken from main)."""
    series = pd.Series(["2024-06-15", None, "2024-08-20", "2024-11-30"])
    out = apply_bucket_perturb(series, "month", SEED, "d", "%Y-%m-%d")
    assert out.tolist() == ["2024-06-23", None, "2024-08-09", "2024-11-27"]


# -- typed dates run bare and keep their type --------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_typed_date_runs_without_format_and_keeps_type(tmp_path: Path, route: str) -> None:
    table = _table(DATES, pa.date32())
    out = _run(_cfg(tmp_path, table), pq.read_table(tmp_path / "t.parquet"), route)
    assert out.schema.field("d").type == pa.date32()
    _same_month(DATES, out.column("d").to_pylist())
    assert out.column("p").to_pylist() == list(range(len(DATES)))


def _run_sequential(tmp_path: Path, typ: pa.DataType) -> pa.Table:
    """A parent/child job takes the sequential route; the child holds a typed date column."""
    refs = [f"r{i}" for i in range(len(DATES))]
    parent = pa.table({"id": pa.array(refs)})
    child = pa.table({"ref": pa.array(refs), "d": pa.array(DATES, typ)})
    for name, table in (("parent", parent), ("t", child)):
        pq.write_table(table, tmp_path / f"{name}.parquet")
    raw = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {
            n: {"type": "file", "format": "parquet", "path": str(tmp_path / f"{n}.parquet")}
            for n in ("parent", "t")
        },
        "targets": {
            n: {"type": "file", "format": "csv", "path": f"/dev/null.{n}"} for n in ("parent", "t")
        },
        "tables": [
            {"name": "parent", "columns": [{"name": "id", "strategy": "hash", "namespace": "fk"}]},
            {
                "name": "t",
                "columns": [
                    {"name": "ref", "strategy": "hash", "namespace": "fk"},
                    {
                        "name": "d",
                        "strategy": "bucket_perturb",
                        "namespace": NS,
                        "provider_config": {"bucket": "month"},
                    },
                ],
            },
        ],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "t", "columns": ["ref"]}],
                "orphan_policy": "preserve",
                "namespace": "fk",
            }
        ],
    }
    result = run_pipeline(
        PipelineConfig.model_validate(raw).model_dump(),
        {"parent": parent, "t": child},
        engine_version="e2",
        execution_mode="sequential",
        key_provider=key_provider(),
    )
    return result.outputs["t"]


def test_sequential_route_runs_a_date_column_without_format(tmp_path: Path) -> None:
    out = _run_sequential(tmp_path, pa.date32())
    assert out.schema.field("d").type == pa.date32()
    _same_month(DATES, out.column("d").to_pylist())


def test_every_route_gives_the_same_dates(tmp_path: Path) -> None:
    """One plan field, one rule: the routes agree on every cell."""
    table = _table(DATES, pa.date32())
    outputs = [
        _run(_cfg(tmp_path, table), table, route).column("d").to_pylist() for route in ROUTES
    ]
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0] == _run_sequential(tmp_path, pa.date32()).column("d").to_pylist()


@pytest.mark.parametrize("bucket", ["week", "month", "quarter"])
def test_typed_date_stays_in_its_bucket(tmp_path: Path, bucket: str) -> None:
    table = _table(DATES, pa.date32())
    out = _run(_cfg(tmp_path, table, bucket=bucket), table, "full_frame").column("d").to_pylist()
    for before, after in zip(DATES, out, strict=True):
        if before is not None:
            assert abs((after - before).days) < BUCKET_OF[bucket]


def test_typed_date_matches_the_same_date_as_iso_text() -> None:
    """One namespace gives one offset for a Parquet date and its ISO text."""
    present = [d for d in DATES if d is not None]
    typed = apply_bucket_perturb_dates(pd.Series(present), "month", SEED, NS)
    text = pd.Series([d.isoformat() for d in present])
    from_text = apply_bucket_perturb(text, "month", SEED, NS, "%Y-%m-%d")
    assert [d.isoformat() for d in typed] == from_text.tolist()


def test_date_format_on_a_date_column_warns_and_is_unused(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"date_format": "%d/%m/%Y"})
    warned = [w for w in _compile(cfg, table).plan_compile.warnings if FORMAT_UNUSED in w]
    assert len(warned) == 1 and "'d'" in warned[0]
    out = _run(cfg, table, "full_frame")
    assert out.schema.field("d").type == pa.date32()  # a date, never text under %d/%m/%Y
    _same_month(DATES, out.column("d").to_pylist())


def test_preserve_values_on_a_date_column_needs_no_format(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"preserve_values": ["2024-02-03"]})
    out = _run(cfg, table, "full_frame")
    got = out.column("d").to_pylist()
    assert out.schema.field("d").type == pa.date32()
    assert got[DATES.index(dt.date(2024, 2, 3))] == dt.date(2024, 2, 3)


def test_a_bucket_past_year_9999_is_a_row_error_not_a_value() -> None:
    last = dt.date(9999, 12, 30)  # a week position can land after 9999-12-31
    hits = 0
    for i in range(12):
        errors: list[int] = []
        out = apply_bucket_perturb_dates(pd.Series([last]), "week", SEED, f"ns{i}", errors)
        if errors:
            hits += 1
            assert errors == [0] and out.iloc[0] == last  # reported, source value untouched
        else:
            assert out.iloc[0] <= dt.date(9999, 12, 31)
    assert hits > 0


def test_a_cell_that_is_not_a_date_needs_a_row_channel() -> None:
    errors: list[int] = []
    apply_bucket_perturb_dates(pd.Series(["not a date"]), "week", SEED, NS, errors)
    assert errors == [0]
    with pytest.raises(ExecutionError) as exc:  # no channel: refuse, never lose the cell
        apply_bucket_perturb_dates(pd.Series(["not a date"]), "week", SEED, NS)
    assert exc.value.code == reasons.runtime.BUCKET_PERTURB_UNPARSEABLE_NO_ROW_CHANNEL


# -- other shapes are refused -----------------------------------------------------------


@pytest.mark.parametrize(
    ("typ", "values", "shape"),
    [
        (pa.timestamp("us"), [dt.datetime(2024, 1, 15, 1, 2, 3)], "timestamp_naive"),
        (
            pa.timestamp("us", tz="UTC"),
            [dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc)],
            "timestamp_tz",
        ),
        (pa.int64(), [20240115, 20240203], "integer"),
        (pa.float64(), [1.5, 2.5], "float"),
        (pa.bool_(), [True, False], "boolean"),
        (pa.decimal128(10, 2), [Decimal("1.50"), Decimal("2.50")], "decimal"),
    ],
)
def test_other_shapes_are_refused(
    tmp_path: Path, typ: pa.DataType, values: list[Any], shape: str
) -> None:
    table = _table(values, typ)
    cfg = _cfg(tmp_path, table, provider_config={"date_format": "%Y%m%d"})
    with pytest.raises(PlanCompileError) as exc:
        _run(cfg, table, "full_frame")
    assert exc.value.code == MISMATCH
    assert f"is a {shape} column" in str(exc.value)


# -- the handler backstop keys on the plan ----------------------------------------------


def _seed(provider_config: tuple[tuple[str, Any], ...] = (("bucket", "month"),)) -> ColumnSeed:
    return ColumnSeed(
        namespace=NS,
        strategy="bucket_perturb",
        provider="bucket_perturb",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=provider_config,
        coherent_with=(),
        when=None,
    )


def _ctx(native: dict[tuple[str, str], ColumnShape]) -> StrategyContext:
    ctx = StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=(0x42).to_bytes(8, "big"),
        native_date_columns=native,
    )
    object.__setattr__(ctx, "current_table", "t")
    return ctx


def test_handler_refuses_unlisted_column() -> None:
    """Only a plan-listed date skips the format; the data never decides."""
    handler = BucketPerturbStrategyHandler()
    dates = pd.DataFrame({"d": pd.Series([dt.date(2024, 1, 15)], dtype=object)})
    out, _ = handler.run(dates.copy(), "d", _seed(), _ctx({("t", "d"): ColumnShape.DATE}))
    assert isinstance(out["d"].iloc[0], dt.date)
    with pytest.raises(ExecutionError) as exc:  # the same column, its plan entry removed
        handler.run(dates.copy(), "d", _seed(), _ctx({}))
    assert exc.value.code == reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT
    text = pd.DataFrame({"d": ["2024-01-15"]})
    with pytest.raises(ExecutionError) as exc2:  # text with no format and no plan entry
        handler.run(text, "d", _seed(), _ctx({}))
    assert exc2.value.code == reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT


def test_native_date_columns_come_from_the_plan_shapes(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    plan = _compile(_cfg(tmp_path, table), table)
    assert native_date_columns(plan) == {("t", "d"): ColumnShape.DATE}
    text = _table([d.isoformat() if d else None for d in DATES], pa.string())
    text_plan = _compile(_cfg(tmp_path, text, provider_config={"date_format": "%Y-%m-%d"}), text)
    assert native_date_columns(text_plan) == {}
    assert native_date_columns(dataclasses.replace(plan, column_shapes=())) == {}


def test_a_nested_child_needs_its_format(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _table(DATES, pa.date32()))
    column = cfg["tables"][0]["columns"][0]
    column["strategy"] = "nested"
    column["provider_config"] = {
        "target": "when",
        "strategy": "bucket_perturb",
        "strategy_config": {"bucket": "month"},
    }
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(cfg)
    assert exc.value.code == REQUIRED


# -- value-free messages ----------------------------------------------------------------


def test_messages_value_free(tmp_path: Path) -> None:
    ints = _table([19870311], pa.int64())
    with pytest.raises(PlanCompileError) as mismatch:
        _run(_cfg(tmp_path, ints, provider_config={"date_format": "%Y%m%d"}), ints, "full_frame")
    text = pa.table({"d": ["2031-07-19"], "p": pa.array([1], pa.int64())})
    with pytest.raises(PlanCompileError) as required:
        _compile(_cfg(tmp_path, text), text)
    dates = _table(DATES, pa.date32())
    warnings = _compile(
        _cfg(tmp_path, dates, provider_config={"date_format": "%Y"}), dates
    ).plan_compile.warnings
    bad = pa.table({"d": ["2031-07-19", "2024-02-03"], "p": pa.array([1, 2], pa.int64())})
    with pytest.raises(RowErrorsFailedError) as rows:
        _run(_cfg(tmp_path, bad, provider_config={"date_format": "%d/%m/%Y"}), bad, "full_frame")
    for message in (str(mismatch.value), str(required.value), *warnings, str(rows.value)):
        assert not any(m in message for m in (*MARKERS, "19870311", "2031"))
