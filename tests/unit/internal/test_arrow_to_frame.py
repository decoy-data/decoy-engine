"""R1 (SOURCE-READ-BOUNDARY S1b-1): the conversion choke point and its required callback."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import NoReturn

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.internal.pandas_compat import (
    arrow_to_frame,
    arrow_to_frame_pair,
    arrow_to_series,
)

# Day numbers and nanoseconds the failure text must never carry.
_LEAKS = ("10000", "2932897", "-768", "non-zero nanoseconds")


class _RefusedError(Exception):
    def __init__(self, column: str) -> None:
        super().__init__(f"column {column}")
        self.column = column


def _refuse(column: str) -> NoReturn:
    raise _RefusedError(column) from None


def _date32(days: int) -> pa.Array:
    return pa.array([days, 19000, None], pa.int32()).cast(pa.date32())


def _bad_table(kind: str) -> pa.Table:
    if kind == "date32":
        bad = _date32(2932897)
    elif kind == "date64":
        bad = pa.array([253402300800000, 0, None], pa.int64()).cast(pa.date64())
    else:
        bad = pa.array([1, 2, None], pa.time64("ns"))
    return pa.table({"ok": [1, 2, 3], "bad": bad})


@pytest.mark.parametrize("kind", ["date32", "date64", "time64"])
def test_unrepresentable_column_calls_the_callback_with_its_name(kind: str) -> None:
    with pytest.raises(_RefusedError) as caught:
        arrow_to_frame(_bad_table(kind), on_unrepresentable=_refuse)
    exc = caught.value
    assert exc.column == "bad"
    assert exc.__cause__ is None and exc.__context__ is None and exc.__suppress_context__
    text = "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)
    assert not [leak for leak in _LEAKS if leak in text]


def test_in_range_table_equals_its_plain_conversion() -> None:
    table = pa.table({"i": [1, None, 3], "d": _date32(19000), "s": ["a", None, "c"]})
    pd.testing.assert_frame_equal(
        arrow_to_frame(table, on_unrepresentable=_refuse), table.to_pandas()
    )


def test_a_callback_that_returns_is_a_value_free_type_error() -> None:
    def returns(_column: str) -> NoReturn:
        return None  # type: ignore[return-value]

    with pytest.raises(TypeError, match="on_unrepresentable must raise") as caught:
        arrow_to_frame(_bad_table("date32"), on_unrepresentable=returns)
    assert not [leak for leak in _LEAKS if leak in str(caught.value)]


def test_the_callback_is_required() -> None:
    with pytest.raises(TypeError):
        arrow_to_frame(_bad_table("date32"))  # type: ignore[call-arg]


@pytest.mark.parametrize("entry", [arrow_to_frame, arrow_to_series, arrow_to_frame_pair])
def test_widening_is_not_available_yet(entry: Callable[..., object]) -> None:
    table = pa.table({"a": [1]})
    args: tuple[object, ...] = (table, table) if entry is arrow_to_frame_pair else (table,)
    if entry is arrow_to_series:
        args = (table.column("a"),)
    with pytest.raises(NotImplementedError):
        entry(*args, on_unrepresentable=_refuse, widen=True)


def test_series_and_pair_use_the_same_callback() -> None:
    bad = _bad_table("date32")
    with pytest.raises(_RefusedError) as one:
        arrow_to_series(bad.column("bad"), on_unrepresentable=_refuse, name="bad")
    assert one.value.column == "bad"
    good = pa.table({"ok": [1, 2, 3]})
    with pytest.raises(_RefusedError):
        arrow_to_frame_pair(good, bad, on_unrepresentable=_refuse)
    left, right = arrow_to_frame_pair(good, good, on_unrepresentable=_refuse)
    assert left.equals(right)
