"""A chunked table compiles beside the job's other tables, shaped by their schemas.

The dispatched table's chunked compile reads the whole config, so a resident sibling with a
numeric strategy and a `csv` descriptor is shaped by its Arrow schema (integer, no declaration
needed), not by its descriptor (text, declaration required). The job's facts reach that compile
through `run_multi_table_split`, so this runs the real `run_pipeline` route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

from decoy_engine.execution import run_pipeline
from tests.unit.execution import _multi_table_support as mt


def _job(tmp_path: Path) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    big = (mt.std_columns("big_ns"), mt.string_table(mt.BIG, "b"))
    small_table = pa.table({"n": pa.array(list(range(mt.SMALL)), pa.int64())})
    small = (
        [{"name": "n", "strategy": "bucketize", "provider_config": {"width": 10}}],
        small_table,
    )
    cfg, sources = mt.build_job(tmp_path, {"big": big, "small": small})
    csv = tmp_path / "small.csv"
    csv.write_text("n\n" + "\n".join(str(i) for i in range(mt.SMALL)) + "\n", encoding="utf-8")
    cfg["sources"]["small"] = {
        "type": "file",
        "format": "csv",
        "has_header": True,
        "path": str(csv),
    }
    return cfg, sources


def test_a_dispatched_table_compiles_beside_a_typed_sibling_with_a_csv_descriptor(
    tmp_path: Path,
) -> None:
    cfg, sources = _job(tmp_path)
    result = run_pipeline(cfg, sources=sources, **mt.kw())
    assert mt.dispatched_tables(result) == ["big"]
    assert [str(v) for v in result.outputs["small"].column("n").to_pylist()] == ["0"] * mt.SMALL
    assert result.outputs["big"].num_rows == mt.BIG
