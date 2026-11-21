"""A table the caller supplied in memory is shaped by its own schema, whatever format the config
descriptor names; the same descriptor read from a file stays text. One helper decides this for
the plan check, the profile walk and both chunked entries."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

import decoy_engine.plan as plan_module
from decoy_engine import run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.contracts.column_shape import (
    ColumnShape,
    SourceFacts,
    build_source_facts,
    source_format_for,
)
from decoy_engine.execution._chunked_input import fixed_schema_chunks_from_resident
from decoy_engine.execution.pipeline._routing_facts import build_routing_facts
from decoy_engine.plan.checks._column_shapes import build_column_shapes
from decoy_engine.profile import Profile
from decoy_engine.profile._source import profile_source
from decoy_engine.providers_v2 import get_default_registry
from tests.acceptance._f06_support import column
from tests.native._chunked_entry_support import key_provider

S = ColumnShape
DATES = pa.table({"d": pa.array([date(2024, 1, 15), date(2024, 2, 3)], pa.date32())})


def _config(path: str = "t.csv", fmt: str = "csv") -> dict[str, Any]:
    return {
        "version": 2,
        "global_settings": {"seed": 7},
        "tables": [
            {
                "name": "t",
                "columns": [
                    column(
                        "d",
                        "date_shift",
                        namespace="ns",
                        provider_config={"date_format": "%Y-%m-%d"},
                    )
                ],
            }
        ],
        "relationships": [],
        "namespaces": {},
        "sources": {"t": {"type": "file", "format": fmt, "has_header": True, "path": path}},
    }


@pytest.fixture
def compiled_profiles(monkeypatch: pytest.MonkeyPatch) -> list[Profile]:
    seen: list[Profile] = []
    original = plan_module.compile_plan

    def spy(config: dict[str, Any], profile: Profile, **kw: Any) -> Any:
        seen.append(profile)
        return original(config, profile, **kw)

    monkeypatch.setattr(plan_module, "compile_plan", spy)
    return seen


def _shape(profile: Profile) -> ColumnShape:
    return profile.tables[0].columns[0].shape


def test_helper_prefers_resident_over_descriptor() -> None:
    sources = {"t": {"format": "csv"}}
    assert source_format_for(sources, "t") == "csv"
    assert source_format_for(sources, "t", resident=["t"]) == "table"
    assert source_format_for(sources, "other", resident=["t"]) is None
    assert source_format_for(None, "t") is None


@pytest.mark.parametrize(("arrow_type", "shape"), [(pa.int64(), S.INTEGER), (pa.date32(), S.DATE)])
def test_csv_descriptor_with_resident_table_classifies_by_schema(
    arrow_type: pa.DataType, shape: ColumnShape
) -> None:
    schemas = {"t": pa.schema([("d", arrow_type)])}
    got = build_column_shapes(_config(), sources=build_source_facts(caller=schemas))
    assert got == {("t", "d"): shape}


def test_csv_descriptor_read_from_a_file_is_text() -> None:
    schemas = {"t": pa.schema([("d", pa.int64())])}
    assert build_column_shapes(_config(), sources=SourceFacts(schemas=schemas)) == {
        ("t", "d"): S.TEXT
    }


def test_csv_file_profile_is_text_and_a_supplied_table_is_not(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("d\n20240115\n20240203\n", encoding="utf-8")
    cfg = _config(str(path))
    assert _shape(profile_source(cfg, seed=7)) is S.TEXT
    ints = pa.table({"d": pa.array([20240115, 20240203], pa.int64())})
    assert _shape(profile_source(cfg, seed=7, supplied_sources={"t": ints})) is not S.TEXT


@pytest.fixture
def compiled_plans(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Every plan each route compiles, keyed by the module that called `compile_plan`."""
    import decoy_engine.execution.native._plan as native_plan

    seen: dict[str, list[Any]] = {"plan": [], "native": []}

    def spy(key: str, original: Any) -> Any:
        def call(config: dict[str, Any], profile: Profile, **kw: Any) -> Any:
            plan = original(config, profile, **kw)
            seen[key].append(plan)
            return plan

        return call

    monkeypatch.setattr(plan_module, "compile_plan", spy("plan", plan_module.compile_plan))
    monkeypatch.setattr(native_plan, "compile_plan", spy("native", native_plan.compile_plan))
    return seen


def _plan_shapes(plan: Any) -> list[tuple[str, str, ColumnShape]]:
    return [(c.table, c.column, c.shape) for c in plan.column_shapes]


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "t.csv"
    path.write_text("d\n2024-01-15\n2024-02-03\n", encoding="utf-8")
    return path


def _facts(cfg: dict[str, Any], tables: dict[str, Any], **kw: Any) -> Any:
    return build_routing_facts(
        cfg,
        tables,
        registry=get_default_registry(),
        source_loader_schemas=kw.get("loader"),
        engine_version="t",
        base_dir=None,
        instance_default_locale=None,
    )


# One entry per route. Each returns the plans that route compiled for the same input.
def _full_frame(cfg: dict[str, Any], plans: dict[str, list[Any]]) -> list[Any]:
    return [_facts(cfg, {"t": DATES}).plan]


def _snapshot(cfg: dict[str, Any], plans: dict[str, list[Any]]) -> list[Any]:
    from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs

    return [capture_physical_plan_inputs(cfg, {"t": DATES}, engine_version="t").plan]


def _chunked(cfg: dict[str, Any], plans: dict[str, list[Any]]) -> list[Any]:
    list(
        run_mask_pipeline_chunked(
            cfg,
            [DATES],
            table="t",
            source_schema=DATES.schema,
            engine_version="t",
            key_provider=key_provider(),
        )
    )
    return plans["plan"]


def _native_chunked(cfg: dict[str, Any], plans: dict[str, list[Any]]) -> list[Any]:
    list(
        run_mask_chunked(
            cfg,
            fixed_schema_chunks_from_resident(DATES, 10),
            table="t",
            engine_version="t",
            key_provider=key_provider(),
        )
    )
    return [*plans["plan"], *plans["native"]]


ROUTES = {
    "full_frame": _full_frame,
    "snapshot": _snapshot,
    "chunked": _chunked,
    "native_chunked": _native_chunked,
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_every_route_shapes_a_resident_typed_table_by_its_schema(
    route: str, tmp_path: Path, compiled_plans: dict[str, list[Any]]
) -> None:
    """A csv descriptor plus a resident date table: the same `column_shapes` on every route,
    never `text` from the descriptor."""
    cfg = _config(str(_csv(tmp_path)))
    got = ROUTES[route](cfg, compiled_plans)
    assert got, route
    for plan in got:
        assert _plan_shapes(plan) == [("t", "d", S.DATE)], route


def test_routes_agree_on_the_serialized_shapes(
    tmp_path: Path, compiled_plans: dict[str, list[Any]]
) -> None:
    from decoy_engine.plan import plan_to_yaml

    cfg = _config(str(_csv(tmp_path)))
    shapes = set()
    for route in ROUTES.values():
        compiled_plans["plan"].clear()
        compiled_plans["native"].clear()
        for plan in route(cfg, compiled_plans):
            shapes.add(plan_to_yaml(plan).split("column_shapes:")[1].split("\n\n")[0])
    assert len(shapes) == 1, sorted(ROUTES)


def test_loader_table_is_resident_when_a_csv_descriptor_exists(tmp_path: Path) -> None:
    """A typed table a loader supplies is resident, so a csv descriptor does not make it text."""
    cfg = _config(str(_csv(tmp_path)))
    plan = _facts(cfg, {}, loader={"t": DATES.schema}).plan
    assert _plan_shapes(plan) == [("t", "d", S.DATE)]
