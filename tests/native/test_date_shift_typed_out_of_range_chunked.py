"""DATE-SHIFT-TYPED S1 round 3: the public chunked entry survives a date past year 9999.

The first chunk is profiled through pandas before any route runs, so a `date_shift` target
holding such a date must not fail that profile with pandas' value-quoting error, in the first
chunk or a later one.
"""

from __future__ import annotations

import datetime as dt
import traceback

import pyarrow as pa
import pytest

from decoy_engine.errors import RowErrorsFailedError
from tests.native._b8_support import run_one
from tests.native._chunked_entry_support import NEEDS_COMPANION, make_config

pytestmark = NEEDS_COMPANION

PAST = 2932897  # day number of 10000-01-01


def _chunk(days: list[int]) -> pa.Table:
    return pa.table({"d": pa.array(days, pa.int32()).cast(pa.date32())})


_COLUMN = {
    "name": "d",
    "strategy": "date_shift",
    "namespace": "ns_oor",
    "provider_config": {"min_days": -5, "max_days": 5},
}
_GOOD = [(dt.date(2001, 1, 1) - dt.date(1970, 1, 1)).days + i for i in range(10)]


@pytest.mark.parametrize("bad_chunk", [0, 1])
def test_a_past_9999_date_never_crashes_the_chunked_run(bad_chunk: int) -> None:
    chunks = [_chunk(_GOOD), _chunk(_GOOD)]
    chunks[bad_chunk] = _chunk([PAST, *_GOOD[1:]])
    # The kernel keeps the row and records a format error; with no quarantine trigger the run
    # refuses with the row-error summary. It must be that refusal, never pandas' own error.
    with pytest.raises(RowErrorsFailedError) as caught:
        run_one(make_config([_COLUMN]), chunks)
    text = "".join(traceback.format_exception(caught.value))
    assert "10000-01" not in text and str(PAST) not in text, text[-1500:]
