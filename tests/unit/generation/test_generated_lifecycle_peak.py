"""F24 84-E2: the legacy multi-table execute peak of the generate lifecycle.

`synthesize.generate_tables` converts each table to Arrow before it starts the next, so on the
legacy whole-table path only the earlier tables' Arrow output is retained while the current
table holds its Python objects. Expectations are written out in bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from decoy_engine import PipelineConfig, estimate_job
from decoy_engine.execution._mem_estimate import route_intercept_bytes

INTERCEPT = route_intercept_bytes("full_frame")
INT_OBJ = sys.getsizeof(1 << 20)
EMAIL = {"name": "em", "type": "faker", "faker_type": "email", "unique": True}
SEQUENCE = {"name": "id", "type": "sequence", "start": 1}


def _two_tables(tmp_path: Path, rows_a: int, rows_b: int) -> dict:
    tables = [
        {"name": "a", "row_count": rows_a, "generate_columns": [SEQUENCE, EMAIL]},
        {"name": "b", "row_count": rows_b, "generate_columns": [SEQUENCE, EMAIL]},
    ]
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {},
        "targets": {
            n: {"type": "file", "path": str(tmp_path / f"{n}.parquet"), "format": "parquet"}
            for n in ("a", "b")
        },
        "tables": tables,
    }
    return PipelineConfig.model_validate(raw).model_dump()


def _objects(rows: int) -> int:
    # A unique faker column declines the plan, so every cell is a Python object: id is a list
    # slot plus an int object, em is a str of the declared email width (24) plus its slot.
    return rows * (8 + INT_OBJ) + rows * (57 + 24)


def _arrow(rows: int) -> int:
    return rows * 8 + rows * (4 + 24)


def _unique(rows: int) -> int:
    return rows * (24 + 57 + 72) + rows * (32 + 72)


def test_a_legacy_run_holds_earlier_arrow_outputs_and_one_tables_objects(tmp_path: Path) -> None:
    rows_a, rows_b = 1000, 2000
    est = estimate_job(_two_tables(tmp_path, rows_a, rows_b), tmp_path)
    assert est.lifecycle_peak_bytes is not None, est.notes
    during_a = _objects(rows_a) + _unique(rows_a)
    during_b = _arrow(rows_a) + _objects(rows_b) + _unique(rows_b)
    done = _arrow(rows_a) + _arrow(rows_b)
    assert dict(est.phase_bytes)["execute"] == INTERCEPT + max(during_a, during_b, done)
    # The sum of both tables' objects was the old, too-high figure.
    assert dict(est.phase_bytes)["execute"] < INTERCEPT + _objects(rows_a) + _objects(rows_b)


def test_the_larger_table_first_sets_the_peak_the_same_way(tmp_path: Path) -> None:
    rows_a, rows_b = 2000, 1000
    est = estimate_job(_two_tables(tmp_path, rows_a, rows_b), tmp_path)
    during_a = _objects(rows_a) + _unique(rows_a)
    during_b = _arrow(rows_a) + _objects(rows_b) + _unique(rows_b)
    assert dict(est.phase_bytes)["execute"] == INTERCEPT + max(
        during_a, during_b, _arrow(rows_a) + _arrow(rows_b)
    )
