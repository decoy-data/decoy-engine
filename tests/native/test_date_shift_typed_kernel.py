"""DATE-SHIFT-TYPED S1: the `date32` kernel against the recorded oracle corpus (T1), value-free
errors (T7) and dates beyond Python's range (T8).

The T1 fixture is today's oracle output, recorded at engine main 3426165fb before S1 moved the
oracle onto the shared arithmetic. Both the oracle and the native kernel must equal it, compared
as Arrow arrays with their type, so a type drift fails even when the values match.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler
from decoy_engine.execution.native._date_shift_ext import native_date_shift
from decoy_engine.execution.native._index_ext import load_compiled_index_kernel
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.transforms.date_shift import DATE32_MAX_DAY, DATE32_MIN_DAY, shift_typed_days
from tests.native._chunked_entry_support import NEEDS_COMPANION
from tests.unit.strategies.test_date_shift_typed import _ctx

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "vectors" / "date_shift_typed_t1_corpus.json").read_text()
)
NS = _FIXTURE["namespace"]
MIN_DAYS, MAX_DAYS = _FIXTURE["min_days"], _FIXTURE["max_days"]
KEY = bytes.fromhex(_FIXTURE["mask_key_hex"])
ERROR_ROWS = tuple(_FIXTURE["format_error_rows"])


def _dates(texts: list[str | None]) -> pa.Array:
    return pa.array(
        [None if t is None else dt.date.fromisoformat(t) for t in texts], type=pa.date32()
    )


SOURCE = _dates(_FIXTURE["source"])
EXPECTED = _dates(_FIXTURE["expected"])


def _seed() -> ColumnSeed:
    return ColumnSeed(
        namespace=NS,
        strategy="date_shift",
        provider="date_shift",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=(("min_days", MIN_DAYS), ("max_days", MAX_DAYS)),
        coherent_with=(),
        when=None,
    )


def oracle(values: list[Any]) -> tuple[list[Any], list[Any]]:
    """Today's oracle handler on an object column under the `DATE` plan shape."""
    ctx = _ctx({("t", "d"): ColumnShape.DATE})
    assert ctx.mask_key == KEY
    frame = pd.DataFrame({"d": pd.Series(values, dtype=object)})
    out, _ = DateShiftStrategyHandler().run(frame, "d", _seed(), ctx)
    return out["d"].tolist(), list(ctx.row_errors)


def native(array: pa.Array) -> tuple[pa.Array, tuple[int, ...]]:
    return native_date_shift(
        array,
        min_days=MIN_DAYS,
        max_days=MAX_DAYS,
        date_format=None,
        mask_key=KEY,
        namespace=NS,
        index_kernel=load_compiled_index_kernel(),
        shape=ColumnShape.DATE,
    )


def _diff(got: pa.Array, want: pa.Array) -> list[int]:
    return [
        i for i, (a, b) in enumerate(zip(got.to_pylist(), want.to_pylist(), strict=True)) if a != b
    ]


# ---------------------------------------------------------------------------
# T1: the corpus, oracle and native, against the pre-S1 recording.
# ---------------------------------------------------------------------------


def test_t1_oracle_equals_the_recorded_corpus() -> None:
    out, errors = oracle(SOURCE.to_pylist())
    got = pa.array(out, type=pa.date32())
    assert got.equals(EXPECTED), _diff(got, EXPECTED)
    assert tuple(sorted(e.row_index for e in errors)) == ERROR_ROWS


@NEEDS_COMPANION
def test_t1_native_equals_the_recorded_corpus() -> None:
    out, errors = native(SOURCE)
    assert out.type == pa.date32()
    assert out.equals(EXPECTED), _diff(out, EXPECTED)
    assert errors == ERROR_ROWS
    for i in errors:
        assert out[i].equals(SOURCE[i])


@NEEDS_COMPANION
def test_t1_slices_give_the_same_bytes_as_the_whole_column() -> None:
    whole, whole_errors = native(SOURCE)
    pieces = [native(SOURCE.slice(i, 7)) for i in range(0, len(SOURCE), 7)]
    assert pa.concat_arrays([p[0] for p in pieces]).equals(whole)
    assert tuple(i + 7 * k for k, p in enumerate(pieces) for i in p[1]) == whole_errors


# ---------------------------------------------------------------------------
# The shared arithmetic's bounds (the upper-bound mutation turns these red).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "offset", "failed"),
    [
        (DATE32_MAX_DAY, 0, False),
        (DATE32_MAX_DAY - 1, 1, False),
        (DATE32_MAX_DAY, 1, True),
        (DATE32_MAX_DAY + 1, 0, True),
        (DATE32_MIN_DAY, 0, False),
        (DATE32_MIN_DAY + 1, -1, False),
        (DATE32_MIN_DAY, -1, True),
        (DATE32_MIN_DAY - 1, 0, True),
    ],
)
def test_shift_typed_days_bounds_are_years_1_to_9999(day: int, offset: int, failed: bool) -> None:
    source = pa.array([day, None], pa.int32()).cast(pa.date32())
    out, flags = shift_typed_days(source, np.array([offset, 5], dtype=np.int64))
    assert out.type == pa.date32()
    assert flags.tolist() == [failed, False]
    assert out.cast(pa.int32()).to_pylist() == [day if failed else day + offset, None]


def test_the_bounds_are_python_date_min_and_max() -> None:
    epoch = dt.date(1970, 1, 1)
    assert dt.date.min == epoch + dt.timedelta(DATE32_MIN_DAY)
    assert dt.date.max == epoch + dt.timedelta(DATE32_MAX_DAY)


# ---------------------------------------------------------------------------
# T7: row errors carry positions and a reason, never a date.
# ---------------------------------------------------------------------------


def test_t7_oracle_row_errors_carry_no_date_text() -> None:
    _, errors = oracle(SOURCE.to_pylist())
    assert errors
    sources = {t for t in _FIXTURE["source"] if t is not None}
    for error in errors:
        text = repr(error)
        assert not any(s in text for s in sources), text


# ---------------------------------------------------------------------------
# T8: a date32 beyond years 1 to 9999 (B4).
# ---------------------------------------------------------------------------

_BEYOND = pa.array([DATE32_MAX_DAY + 1, 0, None, DATE32_MIN_DAY - 1], pa.int32()).cast(pa.date32())


@NEEDS_COMPANION
def test_t8_native_keeps_a_year_10000_date_with_a_format_error() -> None:
    out, errors = native(_BEYOND)
    assert errors == (0, 3)
    assert out.type == pa.date32()
    days = out.cast(pa.int32()).to_pylist()
    assert days[0] == DATE32_MAX_DAY + 1 and days[3] == DATE32_MIN_DAY - 1
    assert days[2] is None and days[1] is not None


def test_t8_the_pandas_route_cannot_convert_a_year_10000_date() -> None:
    """Recorded, not wanted: the full-frame route reads the column through pandas, which has no
    year 10000, so that job fails before any strategy runs (plan section 3, B4)."""
    with pytest.raises((ValueError, OverflowError)):
        pa.table({"d": _BEYOND}).to_pandas()


# ---------------------------------------------------------------------------
# T10: non-date cells in a DATE-shaped object column stay on the oracle's cell pass.
# ---------------------------------------------------------------------------


def test_t10_non_date_cells_are_row_errors_that_keep_the_source() -> None:
    day = dt.date(2024, 1, 15)
    stamp = dt.datetime(2019, 6, 30, 23, 59, 59)
    out, errors = oracle([day, stamp, "x", 7, None])
    [shifted_day], _ = oracle([day])
    [shifted_stamp], _ = oracle([stamp.date()])
    assert out == [shifted_day, shifted_stamp, "x", 7, None]
    assert shifted_day != day and shifted_stamp != stamp.date()
    assert sorted(e.row_index for e in errors) == [2, 3]
