"""`jitter_days: N` on the chunked native lane: the route taken, the window and the bytes.

The same config written as `min_days: -7, max_days: 7` is the control. The forced-oracle leg of
`run_pair` is the pandas handler, so the native leg is also compared with the handler's route.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pyarrow as pa

from tests.native._chunked_date_shift_support import (
    assert_same_as_oracle,
    ds_col,
    run_one,
    run_pair,
    source,
)
from tests.native._chunked_entry_support import NEEDS_COMPANION, make_config, passthrough, split

JITTER = 7
BASE = dt.date(2019, 1, 1)
CELLS = [None if i % 9 == 4 else (BASE + dt.timedelta(days=37 * i)).isoformat() for i in range(60)]


def _jitter_col() -> dict[str, Any]:
    col = ds_col()
    col["provider_config"] = {"date_format": "%Y-%m-%d", "jitter_days": JITTER}
    return col


def _out(run: Any) -> list[Any]:
    return pa.concat_tables(run.out).column("d").to_pylist()


@NEEDS_COMPANION
def test_chunked_native_lane_honours_jitter_days() -> None:
    chunks = split(source(CELLS), 3)
    native, forced = run_pair([_jitter_col(), passthrough("p")], chunks)
    assert_same_as_oracle(native, forced)  # native_admitted is True and bytes equal the handler
    control = run_one(
        make_config([ds_col(min_days=-JITTER, max_days=JITTER), passthrough("p")]), chunks
    )
    assert control.ev[0].native_admitted is True
    assert _out(native) == _out(control)
    moved = 0
    for before, after in zip(CELLS, _out(native), strict=True):
        if before is None:
            assert after is None
            continue
        delta = (dt.date.fromisoformat(after) - dt.date.fromisoformat(before)).days
        assert -JITTER <= delta <= JITTER
        moved += delta != 0
    assert moved > 0
