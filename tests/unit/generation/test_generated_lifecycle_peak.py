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
    # Summing both tables' objects, as the first version did, gave a higher figure.
    summed = _objects(rows_a) + _objects(rows_b) + _unique(rows_b)
    assert dict(est.phase_bytes)["execute"] < INTERCEPT + summed


def test_the_larger_table_first_sets_the_peak_the_same_way(tmp_path: Path) -> None:
    rows_a, rows_b = 2000, 1000
    est = estimate_job(_two_tables(tmp_path, rows_a, rows_b), tmp_path)
    during_a = _objects(rows_a) + _unique(rows_a)
    during_b = _arrow(rows_a) + _objects(rows_b) + _unique(rows_b)
    assert dict(est.phase_bytes)["execute"] == INTERCEPT + max(
        during_a, during_b, _arrow(rows_a) + _arrow(rows_b)
    )


# --- Codex round 2: the conversion moment and the mixed overlap ---------------------------
# Each moment is written out as its own figure, then the largest is taken by hand.

WIDE = "x" * 100
WIDE_CATEGORY = {"type": "categorical", "categories": [WIDE, "y" * 100]}


def _wide_table(name: str, rows: int) -> dict:
    return {
        "name": name,
        "row_count": rows,
        "generate_columns": [
            SEQUENCE,
            EMAIL,
            *({"name": f"w{i}", **WIDE_CATEGORY} for i in range(3)),
        ],
    }


def _wide_objects(rows: int) -> int:
    return (
        rows * (8 + INT_OBJ) + rows * (57 + 24) + 3 * rows * (57 + 100)  # id, em, w0..w2
    )


def _wide_arrow(rows: int) -> int:
    return rows * 8 + rows * (4 + 24) + 3 * rows * (4 + 100)


def _config(tmp_path: Path, tables: list[dict], mask: dict | None = None) -> dict:
    targets = {
        t["name"]: {
            "type": "file",
            "path": str(tmp_path / f"{t['name']}.o.parquet"),
            "format": "parquet",
        }
        for t in tables
    }
    raw: dict = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {},
        "targets": targets,
        "tables": list(tables),
    }
    if mask is not None:
        raw["sources"]["m"] = mask["source"]
        raw["targets"]["m"] = {
            "type": "file",
            "path": str(tmp_path / "m.o.parquet"),
            "format": "parquet",
        }
        raw["tables"].append(mask["table"])
    return PipelineConfig.model_validate(raw).model_dump()


def test_the_arrow_conversion_moment_can_dominate_a_legacy_table(tmp_path: Path) -> None:
    # synthesize.py builds `arrow_table(data)` while the table's Python lists are still live; the
    # unique seen set is function-local to its column draw (_unique.py), so it is gone by then.
    rows = 1000
    est = estimate_job(_config(tmp_path, [_wide_table("g", rows)]), tmp_path)
    assert est.lifecycle_peak_bytes is not None, est.notes
    draw = _wide_objects(rows) + _unique(rows)  # the unique column's draw moment
    convert = _wide_objects(rows) + _wide_arrow(rows)  # lists still live, Arrow being built
    assert _wide_arrow(rows) > _unique(rows)  # this fixture is the conversion-dominated case
    assert dict(est.phase_bytes)["execute"] == INTERCEPT + max(draw, convert, _wide_arrow(rows))


def test_a_mixed_job_peaks_in_generation_when_that_exceeds_the_mask_moment(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    # `_pipeline_generate_mask.py` runs `generate_tables` first (Step 1), then the mask step
    # (Step 2) with the generated Arrow outputs still held. The caller holds the mask input
    # throughout. Two moments, never summed.
    mask_rows, gen_rows = 200, 1000
    src = str(tmp_path / "m.parquet")
    pq.write_table(pa.table({"n": pa.array(range(mask_rows), type=pa.int64())}), src)
    mask = {
        "source": {"type": "file", "path": src, "format": "parquet"},
        "table": {"name": "m", "columns": [{"name": "n", "strategy": "passthrough"}]},
    }
    mask_only = estimate_job(_config(tmp_path, [], mask), tmp_path)
    mixed = estimate_job(_config(tmp_path, [_wide_table("g", gen_rows)], mask), tmp_path)
    assert mixed.lifecycle_peak_bytes is not None, mixed.notes
    mask_input = mask_rows * 8
    generation_moment = (
        INTERCEPT
        + mask_input
        + _wide_objects(gen_rows)
        + max(_unique(gen_rows), _wide_arrow(gen_rows))
    )
    mask_moment = dict(mask_only.phase_bytes)["execute"] + _wide_arrow(gen_rows)
    assert generation_moment > mask_moment  # the case the first formula missed
    assert dict(mixed.phase_bytes)["execute"] == max(generation_moment, mask_moment)
