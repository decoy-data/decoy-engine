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
from decoy_engine.contracts.column_shape import ColumnShape, source_format_for
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
    got = build_column_shapes(_config(), source_schemas=schemas, resident_tables={"t"})
    assert got == {("t", "d"): shape}


def test_csv_descriptor_read_from_a_file_is_text() -> None:
    schemas = {"t": pa.schema([("d", pa.int64())])}
    assert build_column_shapes(_config(), source_schemas=schemas) == {("t", "d"): S.TEXT}


def test_csv_file_profile_is_text_and_a_supplied_table_is_not(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("d\n20240115\n20240203\n", encoding="utf-8")
    cfg = _config(str(path))
    assert _shape(profile_source(cfg, seed=7)) is S.TEXT
    ints = pa.table({"d": pa.array([20240115, 20240203], pa.int64())})
    assert _shape(profile_source(cfg, seed=7, supplied_sources={"t": ints})) is not S.TEXT


def test_pandas_arrow_and_chunked_routes_agree(
    tmp_path: Path, compiled_profiles: list[Profile]
) -> None:
    path = tmp_path / "t.csv"
    path.write_text("d\n2024-01-15\n2024-02-03\n", encoding="utf-8")
    cfg = _config(str(path))
    facts = build_routing_facts(
        cfg,
        {"t": DATES},
        registry=get_default_registry(),
        source_loader_schemas=None,
        engine_version="t",
        base_dir=None,
        instance_default_locale=None,
    )
    plan_shape = [c.shape for c in facts.plan.column_shapes]
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
    oracle = _shape(compiled_profiles[-1])
    list(
        run_mask_chunked(
            cfg,
            fixed_schema_chunks_from_resident(DATES, 10),
            table="t",
            engine_version="t",
            key_provider=key_provider(),
        )
    )
    native = _shape(compiled_profiles[-1])
    assert plan_shape == [S.DATE]
    assert oracle is native is S.DATE
