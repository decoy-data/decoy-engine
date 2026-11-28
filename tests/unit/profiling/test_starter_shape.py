"""COLUMN-SHAPE-RULE E5: the starter writes `date_format` only where the engine would guess.

A text date needs the detected format. A typed date (Parquet date32) is read natively, so the
starter writes a `date_shift` with no format. An unknown shape fails closed and writes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import NO_SOURCES, ColumnShape
from decoy_engine.plan import compile_plan
from decoy_engine.profile import profile_source
from decoy_engine.profiling import profile_columns, scan_sources
from decoy_engine.profiling._starter_config import StarterConfig, detector_entry, starter_config
from decoy_engine.profiling._starter_inference import infer_starter_strategy

DATES = ["1990-01-02", "1985-06-30", "2001-12-25", "1999-03-04", "1972-11-11"] * 4


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, dict[str, Any]]:
    pd.DataFrame({"dob": DATES}).to_csv(tmp_path / "c.csv", index=False)
    pq.write_table(
        pa.table({"dob": pa.array(pd.to_datetime(DATES).date, pa.date32())}),
        tmp_path / "d.parquet",
    )
    file = {"type": "file"}
    return {
        "csv": {**file, "format": "csv", "path": str(tmp_path / "c.csv"), "has_header": True},
        "typed": {**file, "format": "parquet", "path": str(tmp_path / "d.parquet")},
    }


def _dob(result: StarterConfig, table: str) -> dict[str, Any]:
    entry = next(t for t in result.config["tables"] if t["name"] == table)
    return next(c for c in entry["columns"] if c["name"] == "dob")


def test_csv_date_gets_detected_format(sources: dict[str, dict[str, Any]]) -> None:
    col = _dob(starter_config(scan_sources(sources)), "csv")
    assert col["strategy"] == "date_shift"
    assert col["provider_config"]["date_format"] == "%Y-%m-%d"


def test_parquet_date_gets_no_format(sources: dict[str, dict[str, Any]]) -> None:
    col = _dob(starter_config(scan_sources(sources)), "typed")
    assert col["strategy"] == "date_shift"
    assert "date_format" not in col.get("provider_config", {})


def test_every_starter_config_compiles(sources: dict[str, dict[str, Any]]) -> None:
    result = starter_config(scan_sources(sources))
    dumped = PipelineConfig.model_validate(result.config).model_dump()
    profile = profile_source(dumped, seed=1)
    compile_plan(dumped, profile, decoy_engine_version="test", sources=NO_SOURCES)


def test_unknown_shape_writes_format() -> None:
    profile = profile_columns(pd.DataFrame({"dob": DATES}), "t")
    got = infer_starter_strategy(profile.fields[0])
    assert got.strategy == "date_shift"
    assert got.provider_config["date_format"] == "%Y-%m-%d"


@pytest.mark.parametrize("shape", [ColumnShape.INTEGER, ColumnShape.TIMESTAMP_NAIVE])
def test_shape_the_strategy_cannot_read_gets_no_date_shift(shape: ColumnShape) -> None:
    """A shape `date_shift` does not admit is never given a bare `date_shift` the compiler refuses."""
    profile = profile_columns(pd.DataFrame({"dob": DATES}), "t", shapes={"dob": shape})
    assert infer_starter_strategy(profile.fields[0]).strategy == "redact"


@pytest.mark.parametrize("shape", [ColumnShape.INTEGER, ColumnShape.TIMESTAMP_NAIVE])
def test_detector_entry_refuses_a_shape_the_strategy_cannot_read(shape: ColumnShape) -> None:
    assert detector_entry("iso_date", "dob", date_format="%Y-%m-%d", shape=shape) is None
    assert detector_entry("iso_date", "dob", shape=ColumnShape.DATE) is not None


def test_zoned_timestamp_with_a_date_match_gets_no_format() -> None:
    """When a date detector matches a zoned timestamp, the starter writes `date_shift` bare."""
    profile = profile_columns(
        pd.DataFrame({"dob": DATES}), "t", shapes={"dob": ColumnShape.TIMESTAMP_TZ}
    )
    got = infer_starter_strategy(profile.fields[0])
    assert got.strategy == "date_shift"
    assert "date_format" not in got.provider_config


def test_zoned_timestamp_parquet_without_a_detector_match_gets_redact(
    tmp_path: Path,
) -> None:
    """Pins today's behaviour: no date detector matches a zoned timestamp, so the starter redacts."""
    stamps = pd.to_datetime(DATES).tz_localize("UTC")
    pq.write_table(
        pa.table({"dob": pa.array(stamps, pa.timestamp("us", tz="UTC"))}), tmp_path / "z.parquet"
    )
    src = {"z": {"type": "file", "format": "parquet", "path": str(tmp_path / "z.parquet")}}
    col = _dob(starter_config(scan_sources(src)), "z")
    assert col["strategy"] == "redact"
