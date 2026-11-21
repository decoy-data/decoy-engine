"""COLUMN-SHAPE E1b: `date_shift` reads a typed date with no declaration and writes the same type.

A Parquet, database or Arrow column that is already a date (or a zoned timestamp) has nothing to
parse, so the plan lets it run bare. The fixtures carry marker values so the value-free checks can
search every message for them.
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
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import ColumnShape, source_facts_of
from decoy_engine.declared_casting._boundary import declared_date_shift_columns, plan_column_shapes
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.profile._source import profile_source
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.native._chunked_entry_support import key_provider

NS = "ns_typed"
MARKERS = ("2031-07-19", "1987-03-11", "2024-02-03")
DATES = [
    dt.date(2031, 7, 19),
    None,
    dt.date(1987, 3, 11),
    dt.date(2024, 2, 3),
    dt.date(2024, 1, 15),
]
ROUTES = ("full_frame", "chunked", "native_chunked")
MISMATCH = reasons.plan.COLUMN_SHAPE_MISMATCH
FORMAT_UNUSED = str(reasons.plan.COLUMN_SHAPE_FORMAT_UNUSED)
NEEDS_FORMAT = reasons.plan.DATE_SHIFT_REQUIRES_DATE_FORMAT


def _file_source(directory: Path, table: pa.Table, name: str) -> dict[str, Any]:
    """A Parquet source descriptor over a real file, so the declaration gate reads its schema."""
    path = directory / f"{name}.parquet"
    pq.write_table(table, path)
    return {"type": "file", "format": "parquet", "path": str(path)}


def _cfg(
    directory: Path,
    table: pa.Table,
    *,
    name: str = "t",
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pc = {"min_days": -30, "max_days": 30, **(provider_config or {})}
    raw: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {name: _file_source(directory, table, name)},
        "targets": {name: {"type": "file", "format": "csv", "path": f"/dev/null.{name}"}},
        "tables": [
            {
                "name": name,
                "columns": [
                    {"name": "d", "strategy": "date_shift", "namespace": NS, "provider_config": pc},
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


def _run(cfg: dict[str, Any], table: pa.Table, route: str, name: str = "t") -> pa.Table:
    if route in ("chunked", "native_chunked"):
        chunks = [table.slice(i, 2) for i in range(0, table.num_rows, 2)]
        if route == "chunked":
            out = run_mask_pipeline_chunked(
                cfg,
                chunks,
                table=name,
                engine_version="e1b",
                source_schema=table.schema,
                key_provider=key_provider(),
            )
        else:
            out = run_mask_chunked(
                cfg, chunks, table=name, engine_version="e1b", key_provider=key_provider()
            )
        return pa.concat_tables(list(out))
    result = run_pipeline(
        cfg,
        {name: table},
        engine_version="e1b",
        execution_mode=route,  # type: ignore[arg-type]
        key_provider=key_provider(),
    )
    return result.outputs[name]


def _assert_shifted(src: list[dt.date | None], out: list[dt.date | None], window: int = 30) -> None:
    assert len(src) == len(out)
    for before, after in zip(src, out, strict=True):
        if before is None:
            assert after is None
        else:
            assert after is not None and abs((after - before).days) <= window
    assert any(a != b for a, b in zip(src, out, strict=True) if a is not None)


@pytest.mark.parametrize("route", ROUTES)
def test_parquet_date32_runs_without_format(tmp_path: Path, route: str) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table)
    out = _run(cfg, pq.read_table(tmp_path / "t.parquet"), route)
    assert out.schema.field("d").type == pa.date32()
    _assert_shifted(DATES, out.column("d").to_pylist())
    assert out.column("p").to_pylist() == list(range(len(DATES)))


def run_sequential_typed(tmp_path: Path, typ: pa.DataType) -> pa.Table:
    """Run a parent/child job on the sequential route; the child holds a typed date column."""
    refs = [f"r{i}" for i in range(len(DATES))]
    parent = pa.table({"id": pa.array(refs)})
    child = pa.table({"ref": pa.array(refs), "d": pa.array(DATES, typ)})
    raw = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {
            "parent": _file_source(tmp_path, parent, "parent"),
            "t": _file_source(tmp_path, child, "t"),
        },
        "targets": {
            n: {"type": "file", "format": "csv", "path": f"/dev/null.{n}"} for n in ("parent", "t")
        },
        "tables": [
            {
                "name": "parent",
                "columns": [{"name": "id", "strategy": "hash", "namespace": "ns_fk"}],
            },
            {
                "name": "t",
                "columns": [
                    {"name": "ref", "strategy": "hash", "namespace": "ns_fk"},
                    {
                        "name": "d",
                        "strategy": "date_shift",
                        "namespace": NS,
                        "provider_config": {"min_days": -30, "max_days": 30},
                    },
                ],
            },
        ],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "t", "columns": ["ref"]}],
                "orphan_policy": "preserve",
                "namespace": "ns_fk",
            }
        ],
    }
    result = run_pipeline(
        PipelineConfig.model_validate(raw).model_dump(),
        {"parent": parent, "t": child},
        engine_version="e1b",
        execution_mode="sequential",
        key_provider=key_provider(),
    )
    return result.outputs["t"]


def test_sequential_route_runs_typed_without_format(tmp_path: Path) -> None:
    """A parent/child job takes the sequential route; the typed child column needs no format."""
    out = run_sequential_typed(tmp_path, pa.date32())
    assert out.schema.field("d").type == pa.date32()
    _assert_shifted(DATES, out.column("d").to_pylist())


def test_loader_date32_runs_without_format(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    result = run_pipeline(
        _cfg(tmp_path, table),
        engine_version="e1b",
        source_loader=lambda name: table,
        source_loader_schemas={"t": table.schema},
        key_provider=key_provider(),
    )
    out = result.outputs["t"]
    assert out.schema.field("d").type == pa.date32()
    _assert_shifted(DATES, out.column("d").to_pylist())


@pytest.mark.parametrize("route", ROUTES)
def test_output_keeps_date32(tmp_path: Path, route: str) -> None:
    table = _table(DATES, pa.date32())
    out = _run(_cfg(tmp_path, table), table, route)
    assert out.schema.field("d").type == pa.date32()
    assert all(isinstance(v, dt.date) for v in out.column("d").to_pylist() if v is not None)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata"])
def test_timestamp_tz_keeps_unit_zone_and_time(tmp_path: Path, route: str, zone: str) -> None:
    utc = dt.timezone.utc
    values = [
        dt.datetime(2024, 1, 15, 13, 45, 30, 250000, tzinfo=utc),
        None,
        dt.datetime(2023, 11, 2, 0, 0, 1, tzinfo=utc),
        dt.datetime(2025, 6, 30, 23, 59, 59, 999999, tzinfo=utc),
    ]
    typ = pa.timestamp("us", tz=zone)
    table = _table(values, typ)
    out = _run(_cfg(tmp_path, table), table, route)
    assert out.schema.field("d").type == typ
    got = out.column("d").to_pylist()
    assert got[1] is None
    shifted = 0
    for before, after in zip(values, got, strict=True):
        if before is None:
            continue
        delta = after - before
        assert delta.microseconds == 0 and delta.seconds == 0  # a whole number of days
        assert abs(delta.days) <= 30
        shifted += delta.days != 0
    assert shifted


def test_typed_offset_equals_iso_text_offset(tmp_path: Path) -> None:
    """One namespace gives one offset: the digest input of a typed date is its ISO text."""
    days = [dt.date(2024, 1, 15), dt.date(2019, 9, 1), dt.date(2031, 7, 19)]
    typed = pa.table({"d": pa.array(days, pa.date32())})
    text = pa.table({"d": pa.array([d.isoformat() for d in days], pa.string())})
    window = {"min_days": -400, "max_days": 400}
    column = {"name": "d", "strategy": "date_shift", "namespace": NS}
    raw = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {
            "typed": _file_source(tmp_path, typed, "typed"),
            "text": _file_source(tmp_path, text, "text"),
        },
        "targets": {
            n: {"type": "file", "format": "csv", "path": f"/dev/null.{n}"}
            for n in ("typed", "text")
        },
        "tables": [
            {"name": "typed", "columns": [{**column, "provider_config": window}]},
            {
                "name": "text",
                "columns": [{**column, "provider_config": {**window, "date_format": "%Y-%m-%d"}}],
            },
        ],
        "relationships": [],
        "namespaces": {},
    }
    result = run_pipeline(
        PipelineConfig.model_validate(raw).model_dump(),
        {"typed": typed, "text": text},
        engine_version="e1b",
        key_provider=key_provider(),
    )
    typed_out = result.outputs["typed"].column("d").to_pylist()
    text_out = [dt.date.fromisoformat(s) for s in result.outputs["text"].column("d").to_pylist()]
    assert typed_out == text_out
    assert typed_out != days


@pytest.mark.parametrize("route", ROUTES)
def test_timestamp_naive_refused_at_compile(tmp_path: Path, route: str) -> None:
    naive = _table([dt.datetime(2024, 1, 15, 1, 2, 3)], pa.timestamp("us"))
    with pytest.raises(PlanCompileError) as exc:
        _run(_cfg(tmp_path, naive), naive, route)
    assert exc.value.code == MISMATCH
    assert "timestamp_naive" in str(exc.value) and "zoned timestamp" in str(exc.value)


@pytest.mark.parametrize(
    ("typ", "values", "shape"),
    [
        (pa.int64(), [20240115, 20240203], "integer"),
        (pa.float64(), [1.5, 2.5], "float"),
        (pa.bool_(), [True, False], "boolean"),
        (pa.decimal128(10, 2), [Decimal("1.50"), Decimal("2.50")], "decimal"),
    ],
)
def test_integer_column_refused(
    tmp_path: Path, typ: pa.DataType, values: list[Any], shape: str
) -> None:
    table = _table(values, typ)
    cfg = _cfg(tmp_path, table, provider_config={"date_format": "%Y%m%d"})
    with pytest.raises(PlanCompileError) as exc:
        _run(cfg, table, "full_frame")
    assert exc.value.code == MISMATCH
    assert f"is a {shape} column" in str(exc.value)


def _compile(cfg: dict[str, Any], table: pa.Table, name: str = "t") -> Any:
    profile = profile_source(cfg, seed=7, supplied_sources={name: table})
    return compile_plan(
        cfg, profile, decoy_engine_version="e1b", sources=source_facts_of({name: table})
    )


def test_date_format_on_typed_date_warns_and_is_unused(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"date_format": "%d/%m/%Y"})
    plan = _compile(cfg, table)
    warned = [w for w in plan.plan_compile.warnings if FORMAT_UNUSED in w]
    assert len(warned) == 1 and "'d'" in warned[0]
    assert not any(m in warned[0] for m in MARKERS)
    out = _run(cfg, table, "full_frame")
    assert out.schema.field("d").type == pa.date32()  # a date, never text under %d/%m/%Y
    _assert_shifted(DATES, out.column("d").to_pylist())


def test_no_format_no_warning(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    plan = _compile(_cfg(tmp_path, table), table)
    assert not [w for w in plan.plan_compile.warnings if FORMAT_UNUSED in w]


def test_loader_table_override_mismatch_refused(tmp_path: Path) -> None:
    """A `date_format` on a loader `int64` column is an override of the wrong kind."""
    table = _table([20240115, 20240203], pa.int64())
    with pytest.raises(PlanCompileError) as exc:
        run_pipeline(
            _cfg(tmp_path, table, provider_config={"date_format": "%Y%m%d"}),
            engine_version="e1b",
            source_loader=lambda name: table,
            source_loader_schemas={"t": table.schema},
            key_provider=key_provider(),
        )
    assert exc.value.code == MISMATCH


def test_csv_without_format_still_refused(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("d,p\n2024-01-15,1\n", encoding="utf-8")
    cfg = _cfg(tmp_path, _table(DATES, pa.date32()))
    cfg["sources"] = {"t": {"type": "file", "format": "csv", "has_header": True, "path": str(path)}}
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(cfg)
    assert exc.value.code == NEEDS_FORMAT
    with pytest.raises(PlanCompileError) as exc2:
        _compile(cfg, pa.table({"d": ["2024-01-15"], "p": ["1"]}))
    assert exc2.value.code == NEEDS_FORMAT


def test_config_only_defers_a_parquet_column(tmp_path: Path) -> None:
    """Without a schema the config-only pass cannot tell a date from text, so compile decides."""
    run_config_only_checks(_cfg(tmp_path, _table(DATES, pa.date32())))
    text = pa.table({"d": ["2024-01-15"], "p": pa.array([1], pa.int64())})
    cfg = _cfg(tmp_path, text)  # a Parquet column that holds text: the schema says so at compile
    run_config_only_checks(cfg)
    with pytest.raises(PlanCompileError) as exc:
        _compile(cfg, text)
    assert exc.value.code == NEEDS_FORMAT


@pytest.mark.parametrize("route", ROUTES)
def test_preserve_values_on_typed_date_without_format(tmp_path: Path, route: str) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"preserve_values": ["2024-02-03"]})
    out = _run(cfg, table, route)
    got = out.column("d").to_pylist()
    assert out.schema.field("d").type == pa.date32()
    assert got[DATES.index(dt.date(2024, 2, 3))] == dt.date(2024, 2, 3)  # the sentinel is kept
    rest = [(a, b) for a, b in zip(DATES, got, strict=True) if a not in (None, dt.date(2024, 2, 3))]
    assert any(a != b for a, b in rest)


def _seed() -> ColumnSeed:
    return ColumnSeed(
        namespace=NS,
        strategy="date_shift",
        provider="date_shift",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=(("min_days", -30), ("max_days", 30)),
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
        column_shapes=native,
    )
    object.__setattr__(ctx, "current_table", "t")
    return ctx


def test_handler_backstop_keys_on_plan() -> None:
    """Only a plan-listed typed column skips the format; the data never decides."""
    handler = DateShiftStrategyHandler()
    dates = pd.DataFrame({"d": pd.Series([dt.date(2024, 1, 15)], dtype=object)})
    out, _ = handler.run(dates.copy(), "d", _seed(), _ctx({("t", "d"): ColumnShape.DATE}))
    assert isinstance(out["d"].iloc[0], dt.date)
    with pytest.raises(StrategyError) as exc:  # the same column, its plan entry removed
        handler.run(dates.copy(), "d", _seed(), _ctx({}))
    assert exc.value.code == reasons.runtime.DATE_SHIFT_REQUIRES_DATE_FORMAT
    text = pd.DataFrame({"d": ["2024-01-15"]})
    with pytest.raises(StrategyError) as exc2:  # text with no format and no plan entry
        handler.run(text, "d", _seed(), _ctx({}))
    assert exc2.value.code == reasons.runtime.DATE_SHIFT_REQUIRES_DATE_FORMAT


def _native_view(plan: Any) -> dict[tuple[str, str], ColumnShape]:
    ctx = _ctx(plan_column_shapes(plan))
    object.__setattr__(ctx, "declared_date_columns", declared_date_shift_columns(plan))
    return ctx.native_date_columns


def test_native_date_columns_come_from_the_plan_shapes(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    plan = _compile(_cfg(tmp_path, table), table)
    assert _native_view(plan) == {("t", "d"): ColumnShape.DATE}
    text = _table([d.isoformat() if d else None for d in DATES], pa.string())
    text_plan = _compile(_cfg(tmp_path, text, provider_config={"date_format": "%Y-%m-%d"}), text)
    assert _native_view(text_plan) == {}
    stripped = dataclasses.replace(plan, column_shapes=())
    assert _native_view(stripped) == {}
    assert {s.shape for s in plan.column_shapes} == {ColumnShape.DATE}


def test_messages_value_free(tmp_path: Path) -> None:
    naive = _table([dt.datetime(2031, 7, 19, 1, 2, 3)], pa.timestamp("us"))
    with pytest.raises(PlanCompileError) as exc:
        _run(_cfg(tmp_path, naive), naive, "full_frame")
    ints = _table([19870311], pa.int64())
    with pytest.raises(PlanCompileError) as exc2:
        _run(_cfg(tmp_path, ints), ints, "full_frame")
    dates = _table(DATES, pa.date32())
    plan = _compile(_cfg(tmp_path, dates, provider_config={"date_format": "%Y"}), dates)
    texts = [str(exc.value), str(exc2.value), *plan.plan_compile.warnings]
    for text in texts:
        assert not any(m in text for m in (*MARKERS, "19870311", "2031"))
