"""Owner question Q6, answer A: a nested date column is refused by type on every run route
(DATE-RANGE-SENTINEL S5, section 4.4b, AT-V3). A far date and an in-calendar date refuse alike,
for a populated and an empty table, and no row is returned or published.

If the owner picks answer B or C, this file changes with the commits that add it."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution import run_pipeline, run_pipeline_isolated
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.io import SourceDateTypeUnsupportedError
from decoy_engine.profile import LazySource
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _b6a_support as b6a
from tests.unit.execution.test_source_date_type_routes import ROUTES, TABLE, _assert_refusal

FAR_DAY = 3_000_000
SHAPES = {
    "list": (pa.list_(pa.date32()), "list"),
    "struct": (pa.struct([("when", pa.date32())]), "struct"),
    "map": (pa.map_(pa.string(), pa.date32()), "map"),
}


def _table(shape: str, far: bool, rows: int) -> pa.Table:
    day = FAR_DAY if far else 5
    values = {
        "list": [[day], [0]],
        "struct": [{"when": day}, {"when": 0}],
        "map": [[("k", day)], [("k", 0)]],
    }[shape][:rows]
    events = pa.array(values, SHAPES[shape][0])
    return pa.table({"id": pa.array(range(len(events))), "events": events})


@pytest.mark.parametrize("rows", [2, 0])
@pytest.mark.parametrize("far", [True, False], ids=["far", "in_calendar"])
@pytest.mark.parametrize("shape", list(SHAPES))
def test_resident_nested_dates_are_refused_on_every_route(shape: str, far: bool, rows: int) -> None:
    table = _table(shape, far, rows)
    kind = SHAPES[shape][1]
    cfg = support.make_cfg([support.pass_col("id"), support.pass_col("events")])
    for route in ROUTES.values():
        with pytest.raises(SourceDateTypeUnsupportedError) as caught:
            run_pipeline(cfg, sources={TABLE: table}, **support.run_kwargs(**route))
        _assert_refusal(caught.value, kind)
    runs: list[Any] = [
        lambda: run_mask_pipeline_chunked(
            cfg,
            iter([table] if rows else []),
            table=TABLE,
            engine_version=support.ENGINE_VERSION,
            source_schema=table.schema,
        ),
        lambda: run_native_chunked(
            cfg,
            iter([table] if rows else []),
            table=TABLE,
            engine_version=support.ENGINE_VERSION,
        ),
    ]
    for run in runs:
        if rows == 0 and run is runs[1]:
            continue  # the native entry has no schema argument; an empty stream has no schema
        with pytest.raises(SourceDateTypeUnsupportedError) as caught:
            list(run())
        _assert_refusal(caught.value, kind)


# ---- the Parquet-storable shapes through the lazy routes (AT-V3) ----------------------------

_DAY = dt.date(2020, 1, 1)
LAZY_SHAPES: dict[str, tuple[pa.Array, str]] = {
    "list": (pa.array([[_DAY], [_DAY]], pa.list_(pa.date32())), "list"),
    "large_list": (pa.array([[_DAY], [_DAY]], pa.large_list(pa.date32())), "large_list"),
    "struct": (
        pa.array([{"when": _DAY}, {"when": _DAY}], pa.struct([("when", pa.date32())])),
        "struct",
    ),
    "map": (pa.array([[("k", _DAY)], [("k", _DAY)]], pa.map_(pa.string(), pa.date32())), "map"),
    "fixed_size_list": (
        pa.array([[_DAY, _DAY], None], pa.list_(pa.date32(), 2)),
        "fixed_size_list",
    ),
}


def _lazy_job(tmp_path: Path, events: pa.Array) -> tuple[dict[str, Any], Path]:
    declared = tmp_path / "declared.parquet"
    pq.write_table(pa.table({"id": [0, 1], "events": ["a", "b"]}), str(declared))
    path = tmp_path / "nested.parquet"
    pq.write_table(pa.table({"id": [0, 1], "events": events}), str(path))
    cfg = support.make_cfg([support.pass_col("id"), support.pass_col("events")], path=str(declared))
    return cfg, path


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("shape", list(LAZY_SHAPES))
def test_a_lazy_nested_source_is_refused_by_type_and_publishes_nothing(
    shape: str, route: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events, kind = LAZY_SHAPES[shape]
    cfg, path = _lazy_job(tmp_path, events)
    sink, target = b6a.real_sink(tmp_path, "out")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        run_pipeline(
            cfg,
            sources={TABLE: LazySource(path, table="stale")},
            sink=sink,
            **support.run_kwargs(**ROUTES[route]),
        )
    _assert_refusal(caught.value, kind)
    assert not Path(target).exists()
    assert "2020" not in caplog.text and "when" not in caplog.text


@pytest.mark.parametrize("isolate", [True, False])
def test_the_isolated_run_reports_the_classified_refusal_in_both_modes(
    isolate: bool, tmp_path: Path
) -> None:
    events, kind = LAZY_SHAPES["fixed_size_list"]
    table = pa.table({"id": [0, 1], "events": events})
    cfg, _ = _lazy_job(tmp_path, events)
    if isolate:
        with pytest.raises(SourceDateTypeUnsupportedError) as caught:
            run_pipeline_isolated(
                cfg, {TABLE: table}, engine_version=support.ENGINE_VERSION, isolate=True
            )
        _assert_refusal(caught.value, kind)
        return
    result = run_pipeline_isolated(
        cfg, {TABLE: table}, engine_version=support.ENGINE_VERSION, isolate=False
    )
    assert result.outcome == "crashed" and result.outputs is None
    assert (result.error or "").startswith("SourceDateTypeUnsupportedError")
    assert "events" not in (result.error or "") and "2020" not in (result.error or "")
