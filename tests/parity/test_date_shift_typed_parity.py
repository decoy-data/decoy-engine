"""DATE-SHIFT-TYPED T3: one `date_shift` config on a `date32` column, every route that takes it.

The reference is the full-frame pandas oracle on the same rows. The unified slice (2,000 rows),
the chunked route (120,000 rows) and the sequential route (a two-table FK job) must each equal
it, as Arrow `date32`, and their evidence must name the native `date_shift`, so a silent fall
back to the oracle fails the cell. A text column with the same dates as ISO strings in the same
namespace gets the same offsets: the typed key is the ISO text.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa

from decoy_engine import run_pipeline
from decoy_engine.execution._sequential_native_ops import SEQ_DATE_SHIFT_DISPOSITION_KEY
from tests.native._b8_support import assert_same_as_oracle, run_one, run_pair
from tests.native._chunked_entry_support import (
    NEEDS_COMPANION,
    TABLE,
    key_provider,
    make_config,
    split,
)
from tests.native._date_shift_typed_support import with_parquet_sources

NS = "ns_typed"
NATIVE = "rust_companion"
BASE = dt.date(1987, 3, 1)
pytestmark = NEEDS_COMPANION


def _dates(n: int) -> list[dt.date | None]:
    return [None if i % 11 == 5 else BASE + dt.timedelta(days=(i * 37) % 15000) for i in range(n)]


def _ds(name: str, **cfg: Any) -> dict[str, Any]:
    config = {"min_days": -90, "max_days": 90, **cfg}
    return {"name": name, "strategy": "date_shift", "namespace": NS, "provider_config": config}


def _table(n: int) -> pa.Table:
    dates = _dates(n)
    return pa.table(
        {
            "d": pa.array(dates, pa.date32()),
            "t": pa.array([None if d is None else d.isoformat() for d in dates], pa.string()),
        }
    )


CONFIG = make_config([_ds("d"), _ds("t", date_format="%Y-%m-%d")])


def _run(config: dict[str, Any], tables: dict[str, pa.Table], tmp: Path, **kw: Any) -> Any:
    config = with_parquet_sources(config, tables, tmp)
    return run_pipeline(config, tables, engine_version="t3", key_provider=key_provider(), **kw)


def _oracle(table: pa.Table, tmp: Path) -> pa.Table:
    result = _run(
        CONFIG,
        {TABLE: table},
        tmp,
        execution_mode="full_frame",
        auto_chunk=False,
        unified_slice_enabled=False,
    )
    assert "unified_slice_activation" not in result.quality_metrics
    return result.outputs[TABLE]


def _assert_text_matches_typed(out: pa.Table) -> None:
    typed = [None if d is None else d.isoformat() for d in out.column("d").to_pylist()]
    assert typed == out.column("t").to_pylist()


def test_the_oracle_moves_typed_dates_and_keeps_the_type(tmp_path: Path) -> None:
    table = _table(300)
    out = _oracle(table, tmp_path)
    assert out.schema.field("d").type == pa.date32()
    assert out.column("d") != table.column("d")
    _assert_text_matches_typed(out)


def test_t3_unified_slice_runs_native_and_equals_the_oracle(tmp_path: Path) -> None:
    table = _table(2000)
    result = _run(
        CONFIG,
        {TABLE: table},
        tmp_path,
        execution_mode="full_frame",
        auto_chunk=False,
        unified_slice_enabled=True,
    )
    nodes = result.quality_metrics["unified_slice_activation"]["nodes"].values()
    [node] = [n for n in nodes if n["columns"] == ["d"]]
    assert (node["strategy"], node["executed_backend"]) == ("date_shift", NATIVE), node
    out = result.outputs[TABLE]
    assert out.column("d").type == pa.date32()
    assert out.column("d").equals(_oracle(table, tmp_path).column("d"))
    _assert_text_matches_typed(out)


def test_t3_chunked_route_runs_native_and_equals_the_oracle(tmp_path: Path) -> None:
    table = _table(120_000)
    native, forced = run_pair([_ds("d"), _ds("t", date_format="%Y-%m-%d")], split(table, 25_000))
    assert_same_as_oracle(native, forced)
    assert native.ev[0].kernel_calls.get("date_shift"), native.ev[0].kernel_calls
    whole = pa.concat_tables(native.out)
    assert whole.schema.field("d").type == pa.date32()
    assert (
        whole.column("d")
        .combine_chunks()
        .equals(_oracle(table, tmp_path).column("d").combine_chunks())
    )
    _assert_text_matches_typed(whole)


def _fk_config() -> dict[str, Any]:
    parent = {"name": "id", "strategy": "hash", "namespace": "fk_ns"}
    child = [{"name": "pid", "strategy": "hash", "namespace": "fk_ns"}, _ds("d")]
    return make_config(
        [parent],
        extra_tables=[{"name": "child", "columns": child}],
        relationships=[
            {
                "parent": {"table": TABLE, "columns": ["id"]},
                "children": [{"table": "child", "columns": ["pid"]}],
                "orphan_policy": "preserve",
                "namespace": "fk_ns",
            }
        ],
    )


def test_t3_sequential_fk_job_runs_native_and_equals_the_oracle(tmp_path: Path) -> None:
    n = 400
    tables = {
        TABLE: pa.table({"id": pa.array([f"p{i}" for i in range(n)])}),
        "child": pa.table(
            {
                "pid": pa.array([f"p{i % n}" for i in range(n)]),
                "d": pa.array(_dates(n), pa.date32()),
            }
        ),
    }
    config = _fk_config()
    seq = _run(config, tables, tmp_path, execution_mode="sequential", auto_chunk=False)
    entries = [
        e for e in seq.quality_metrics.get(SEQ_DATE_SHIFT_DISPOSITION_KEY, []) if e["column"] == "d"
    ]
    assert [e["executed_backend"] for e in entries] == [NATIVE], entries
    full = _run(
        config,
        tables,
        tmp_path,
        execution_mode="full_frame",
        auto_chunk=False,
        unified_slice_enabled=False,
    )
    got, want = seq.outputs["child"].column("d"), full.outputs["child"].column("d")
    assert got.type == pa.date32()
    assert got.combine_chunks().equals(want.combine_chunks())


def test_an_empty_date32_column_keeps_its_type_on_every_route(tmp_path: Path) -> None:
    """A zero-row table has no value to type the pandas column by, so the full-frame frame holds
    `float64`; the output assembler restores the source type, as the unified slice and the
    chunked API already do. Two all-null rows are the control that already passed."""
    for rows in (0, 2):
        table = pa.table({"d": pa.array([None] * rows, pa.date32())})
        config = make_config([_ds("d")])
        for unified in (False, True):
            result = _run(
                config,
                {TABLE: table},
                tmp_path,
                execution_mode="full_frame",
                auto_chunk=False,
                unified_slice_enabled=unified,
            )
            got = result.outputs[TABLE].schema.field("d").type
            assert got == pa.date32(), (rows, unified, got)
        chunked = run_one(config, [table])
        assert all(c.schema.field("d").type == pa.date32() for c in chunked.out), rows
