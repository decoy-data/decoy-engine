"""Every executed source gives its schema to the shape assembler: files, resident tables,
source-loader tables and both public chunked entries, including a chunked input with no chunks."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import decoy_engine.plan as plan_module
from decoy_engine import run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution._chunked_input import fixed_schema_chunks_from_resident
from decoy_engine.execution._chunked_profile import empty_input_profile, first_chunk_profile
from decoy_engine.profile import Profile
from decoy_engine.profile._source import profile_source
from tests.acceptance._f06_support import column
from tests.native._chunked_entry_support import key_provider

S = ColumnShape
SCHEMA = pa.schema([("d", pa.date32())])


def _config(**source: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
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
    }
    if source:
        cfg["sources"] = {"t": {"type": "file", **source}}
    return cfg


@pytest.fixture
def compiled_profiles(monkeypatch: pytest.MonkeyPatch) -> list[Profile]:
    seen: list[Profile] = []
    original = plan_module.compile_plan

    def spy(config: dict[str, Any], profile: Profile, **kw: Any) -> Any:
        seen.append(profile)
        return original(config, profile, **kw)

    monkeypatch.setattr(plan_module, "compile_plan", spy)
    return seen


def _shapes(profile: Profile) -> dict[str, ColumnShape]:
    return {c.name: c.shape for c in profile.tables[0].columns}


def test_zero_chunk_input_takes_source_schema_shape_pipeline_entry(
    compiled_profiles: list[Profile],
) -> None:
    out = list(
        run_mask_pipeline_chunked(
            _config(),
            [],
            table="t",
            source_schema=SCHEMA,
            engine_version="t",
            key_provider=key_provider(),
        )
    )
    assert out == []
    assert _shapes(compiled_profiles[-1]) == {"d": S.DATE}


def test_zero_chunk_input_takes_source_schema_shape_native_entry(
    compiled_profiles: list[Profile],
) -> None:
    empty = fixed_schema_chunks_from_resident(SCHEMA.empty_table(), 10)
    out = list(
        run_mask_chunked(
            _config(), empty, table="t", engine_version="t", key_provider=key_provider()
        )
    )
    assert out == []
    assert _shapes(compiled_profiles[-1]) == {"d": S.DATE}


def test_zero_chunk_arbitrary_iterable_is_unknown(compiled_profiles: list[Profile]) -> None:
    out = list(
        run_mask_chunked(_config(), [], table="t", engine_version="t", key_provider=key_provider())
    )
    assert out == []
    assert _shapes(compiled_profiles[-1]) == {"d": S.UNKNOWN}


def test_empty_profile_keeps_a_config_column_the_schema_lacks() -> None:
    profile = empty_input_profile(
        _config(), table="t", engine_version="t", source_schema=pa.schema([("x", pa.int64())])
    )
    assert _shapes(profile) == {"x": S.INTEGER, "d": S.UNKNOWN}


def test_chunked_first_chunk_shape_matches_full_frame_parquet(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    table = pa.table({"d": pa.array([date(2024, 1, 15), date(2024, 2, 3)], pa.date32())})
    pq.write_table(table, path)
    cfg = _config(format="parquet", path=str(path))
    full = profile_source(cfg, seed=7)
    chunk = first_chunk_profile(table, table="t", engine_version="t", source_format="parquet")
    assert _shapes(full) == _shapes(chunk) == {"d": S.DATE}


def test_chunked_first_chunk_shape_matches_full_frame_csv(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("d\n20240115\n20240203\n", encoding="utf-8")
    cfg = _config(format="csv", has_header=True, path=str(path))
    full = profile_source(cfg, seed=7)
    # The chunked reader infers int64 for this column; the format keeps it text.
    chunk = first_chunk_profile(
        pa.table({"d": pa.array([20240115, 20240203], pa.int64())}),
        table="t",
        engine_version="t",
        source_format="csv",
    )
    assert _shapes(full) == _shapes(chunk) == {"d": S.TEXT}


def test_resident_caller_table_shape_is_its_schema() -> None:
    table = pa.table({"d": pa.array([date(2024, 1, 15)], pa.date32())})
    profile = profile_source(_config(), seed=7, supplied_sources={"t": table})
    assert _shapes(profile) == {"d": S.DATE}


def test_cloud_csv_reader_inference_does_not_make_a_csv_column_typed() -> None:
    """A cloud CSV reader reports `int64` for digits. The descriptor's format wins."""
    from decoy_engine.plan.checks._column_shapes import build_column_shapes

    schemas = {"t": pa.schema([("d", pa.int64())])}
    got = build_column_shapes(_config(format="csv", path="s3://b/k.csv"), source_schemas=schemas)
    assert got == {("t", "d"): S.TEXT}


def test_loader_table_shape_from_loader_schema(
    tmp_path: Path, compiled_profiles: list[Profile], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The routing facts hand the loader schemas to the compile. A loader table has no profile
    entry of its own when its descriptor cannot give a schema, so that map is the only source of
    its column shapes."""
    from decoy_engine.execution.pipeline._routing_facts import build_routing_facts
    from decoy_engine.providers_v2 import get_default_registry

    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"d": pa.array([date(2024, 1, 15)], pa.date32())}), path)
    received: list[Any] = []
    original = plan_module.compile_plan

    def spy(config: dict[str, Any], profile: Profile, **kw: Any) -> Any:
        received.append(kw.get("source_schemas"))
        return original(config, profile, **kw)

    monkeypatch.setattr(plan_module, "compile_plan", spy)
    facts = build_routing_facts(
        _config(format="parquet", path=str(path)),
        {},
        registry=get_default_registry(),
        source_loader_schemas={"t": SCHEMA},
        engine_version="t",
        base_dir=None,
        instance_default_locale=None,
    )
    assert received == [{"t": SCHEMA}]
    assert [(c.table, c.column, c.shape) for c in facts.plan.column_shapes] == [("t", "d", S.DATE)]
