"""Pipeline configs whose sources are real Parquet files, so the plan sees typed columns.

`make_config` points every source at a CSV `/dev/null`; a whole-frame run reads that descriptor
to build the plan's column shapes, so a `date32` column would compile as text. This swaps each
source for a Parquet file holding the table the run is handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine.config._pipeline import PipelineConfig


def with_parquet_sources(
    config: dict[str, Any], tables: dict[str, pa.Table], directory: Path
) -> dict[str, Any]:
    raw = dict(config)
    raw["sources"] = dict(config["sources"])
    for name, table in tables.items():
        path = directory / f"{name}.parquet"
        pq.write_table(table, path)
        raw["sources"][name] = {"type": "file", "format": "parquet", "path": str(path)}
    # `when` is read from the dumped dict but refused by validation (as in `make_config`).
    whens = {
        (t["name"], c["name"]): c["when"]
        for t in raw["tables"]
        for c in t["columns"]
        if c.get("when") is not None
    }
    raw["tables"] = [
        {**t, "columns": [{k: v for k, v in c.items() if k != "when"} for c in t["columns"]]}
        for t in raw["tables"]
    ]
    dumped = PipelineConfig.model_validate(raw).model_dump()
    for table in dumped["tables"]:
        for column in table["columns"]:
            if (table["name"], column["name"]) in whens:
                column["when"] = whens[(table["name"], column["name"])]
    return dumped
