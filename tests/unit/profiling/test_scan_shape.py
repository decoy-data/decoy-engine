"""COLUMN-SHAPE-RULE E5: the scan records each column's observed shape for the starter.

The shape comes from the descriptor's format first, then the reader's Arrow schema, through the
one classifier. It is an input to the starter in the same process and is never written into the
scan-set or profile documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.profile import _readers_csv, profile_source
from decoy_engine.profiling import profile_columns, profile_document, scan_set_to_dict, scan_sources

DATES = ["1990-01-02", "1985-06-30", "2001-12-25", "1999-03-04", "1972-11-11"] * 4


def _sources(root: Path) -> dict[str, dict[str, Any]]:
    pd.DataFrame({"dob": DATES}).to_csv(root / "c.csv", index=False)
    pq.write_table(
        pa.table({"dob": pa.array(pd.to_datetime(DATES).date, pa.date32())}), root / "d.parquet"
    )
    pq.write_table(pa.table({"dob": pa.array(DATES, pa.string())}), root / "s.parquet")
    file = {"type": "file"}
    return {
        "csv": {**file, "format": "csv", "path": str(root / "c.csv"), "has_header": True},
        "typed": {**file, "format": "parquet", "path": str(root / "d.parquet")},
        "text": {**file, "format": "parquet", "path": str(root / "s.parquet")},
    }


def _shape(scan: Any, table: str) -> ColumnShape:
    t = next(t for t in scan.tables if t.name == table)
    return next(f for f in t.profile.fields if f.name == "dob").shape


def test_scan_records_shape_from_reader_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Any) -> pa.Schema:
        raise AssertionError("the CSV reader's schema must not be read")

    monkeypatch.setattr(_readers_csv.CsvFileSource, "schema", refuse)
    sources = _sources(tmp_path)
    scan = scan_sources(sources)
    assert _shape(scan, "typed") is ColumnShape.DATE
    assert _shape(scan, "csv") is ColumnShape.TEXT
    assert _shape(scan, "text") is ColumnShape.TEXT
    # The same rule through profile_source: the CSV schema is still not read.
    config = {
        "sources": sources,
        "tables": [
            {"name": n, "columns": [{"name": "dob", "strategy": "passthrough"}]} for n in sources
        ],
    }
    profile = profile_source(config, seed=1)
    shapes = {t.name: next(c for c in t.columns if c.name == "dob").shape for t in profile.tables}
    assert shapes == {
        "csv": ColumnShape.TEXT,
        "typed": ColumnShape.DATE,
        "text": ColumnShape.TEXT,
    }


def test_profile_documents_omit_shape(tmp_path: Path) -> None:
    scan = scan_sources(_sources(tmp_path))
    detail = json.dumps(scan_set_to_dict(scan, detail=True))
    assert '"shape"' not in detail
    for table in scan.tables:
        assert "shape" not in json.dumps(profile_document(table.profile))
        assert all("shape" not in f for f in table.profile.to_dict()["fields"])


def test_frame_without_shapes_reads_unknown() -> None:
    profile = profile_columns(pd.DataFrame({"dob": DATES}), "t")
    assert [f.shape for f in profile.fields] == [ColumnShape.UNKNOWN]
