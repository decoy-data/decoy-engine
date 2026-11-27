"""Owner question Q6, answer A: a nested date column is refused by type on every run route
(DATE-RANGE-SENTINEL S5, section 4.4b, AT-V3). A far date and an in-calendar date refuse alike,
for a populated and an empty table, and no row is returned or published.

If the owner picks answer B or C, this file changes with the commits that add it."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import run_pipeline
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.io import SourceDateTypeUnsupportedError
from tests.unit.execution import _auto_chunk_support as support
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
