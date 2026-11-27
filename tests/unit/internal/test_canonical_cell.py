"""The canonical cell walk: when two object cells are the same value (plan C1 to C27)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import NamedTuple

import numpy as np
import pandas as pd
import pytest

from decoy_engine.internal.canonical_cell import (
    NULL,
    Duration,
    Instant,
    Map,
    Members,
    Months,
    Null,
    Seq,
    canonical_cell,
    temporal_text,
)

SECOND = 10**18


def _arr(values: list[int], dtype: str) -> np.ndarray:
    return np.array(values, dtype=dtype)


def _boxed(payload: object) -> np.ndarray:
    cell = np.empty((), dtype=object)
    cell[()] = payload
    return cell


def _object_array(*cells: object) -> np.ndarray:
    out = np.empty(len(cells), dtype=object)
    out[:] = list(cells)
    return out


class _P(NamedTuple):
    x: int
    y: int


SAME = [
    pytest.param(_arr([0], "m8[s]"), _arr([0], "m8[ns]"), id="C1-zero-duration-units"),
    pytest.param(_arr([1], "m8[s]"), _arr([1000], "m8[ms]"), id="C4-one-second-two-units"),
    pytest.param(np.array([1, 2]), _object_array(1, 2), id="C5-int-array-vs-object-array"),
    pytest.param(_arr([1], "m8[Y]"), _arr([12], "m8[M]"), id="C7-year-is-twelve-months"),
    pytest.param(_arr([1], "M8[2s]"), _arr([2], "M8[s]"), id="C9-count-multiplier"),
    pytest.param(_arr([1], "M8[M]"), np.array(["1970-02-01"], dtype="M8[D]"), id="C11-month-date"),
    pytest.param(np.array(True), True, id="C12-boxed-bool"),
    pytest.param(
        _object_array({"b": 2, "a": 1}), _object_array({"a": 1, "b": 2}), id="C14-dict-order"
    ),
    pytest.param(_P(1, 2), (1, 2), id="C15-namedtuple-vs-tuple"),
    pytest.param(_P(1, 2), [1, 2], id="C15-list-shares-sequence-identity"),
    pytest.param([float("nan")], [float("nan")], id="C19-nested-nan"),
    pytest.param([1], [1.0], id="C20-nested-int-vs-float"),
    pytest.param(
        pd.Timestamp("2020-01-01", tz="UTC"),
        pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1"),
        id="C17-same-instant-two-zones",
    ),
    pytest.param(
        dt.datetime(2020, 1, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1"),
        id="C25-python-and-pandas-aware",
    ),
    pytest.param(
        dt.datetime(2020, 1, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        pd.Timestamp("2020-01-01", tz="UTC"),
        id="C26-offset-applied",
    ),
    pytest.param(np.timedelta64(5), 5, id="C24-generic-timedelta-is-its-count"),
    pytest.param(np.array(7), 7, id="C2-zero-dim-array"),
    pytest.param(dt.timedelta(seconds=1), pd.Timedelta(seconds=1), id="python-and-pandas-second"),
    pytest.param(dt.datetime(2020, 1, 1), pd.Timestamp("2020-01-01"), id="python-and-pandas-naive"),
    pytest.param(
        np.datetime64("2020-01-01T00:00:01.5"), pd.Timestamp("2020-01-01 00:00:01.5"), id="np-ms"
    ),
    pytest.param(bytearray(b"ab"), b"ab", id="bytearray-is-bytes"),
    pytest.param(memoryview(b"ab"), b"ab", id="memoryview-is-bytes"),
    pytest.param(np.int8(3), 3, id="numpy-int"),
    pytest.param(np.float32(0.5), 0.5, id="numpy-float"),
    pytest.param({1, 2}, frozenset({2, 1}), id="set-and-frozenset"),
    pytest.param([np.str_("a")], ["a"], id="numpy-str"),
]

DIFFERENT = [
    pytest.param(_boxed({"a": 1}), _boxed({"a": 2}), id="C3-boxed-dict-values"),
    pytest.param(_arr([1], "m8[M]"), _arr([30], "m8[D]"), id="C8-month-is-not-thirty-days"),
    pytest.param(_arr([1], "M8[fs]"), _arr([2], "M8[fs]"), id="C10-femtoseconds"),
    pytest.param({"id": 1}, {("id", 1)}, id="C16-dict-vs-set-of-pairs"),
    pytest.param(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01", tz="UTC"), id="C18-naive-vs-aware"
    ),
    pytest.param(1, "1", id="number-vs-text"),
    pytest.param(Decimal("1"), "1", id="decimal-vs-text"),
    pytest.param(pd.Timestamp("2020-01-01"), "2020-01-01 00:00:00", id="timestamp-vs-its-text"),
    pytest.param(pd.Timedelta(seconds=1), 1, id="duration-vs-number"),
    pytest.param(np.datetime64("2020-01-01"), np.timedelta64(18262, "D"), id="instant-vs-duration"),
    pytest.param([1], 1, id="list-vs-element"),
    pytest.param([1], {1}, id="list-vs-set"),
    pytest.param(b"a", "a", id="bytes-vs-str"),
    pytest.param(_arr([1], "M8[fs]"), _arr([1], "M8[as]"), id="fs-vs-as"),
]


@pytest.mark.parametrize(("a", "b"), SAME)
def test_equal_cells_share_one_form_and_hash(a: object, b: object) -> None:
    assert canonical_cell(a) == canonical_cell(b)
    assert hash(canonical_cell(a)) == hash(canonical_cell(b))


@pytest.mark.parametrize(("a", "b"), DIFFERENT)
def test_different_cells_have_different_forms(a: object, b: object) -> None:
    assert canonical_cell(a) != canonical_cell(b)


def test_c2_a_zero_dimensional_array_is_its_payload() -> None:
    form = canonical_cell(np.array(7))
    assert form == 7
    assert type(form) is int


def test_c4_a_duration_array_is_exact_attoseconds() -> None:
    form = canonical_cell(_arr([1], "m8[s]"))
    assert isinstance(form, Seq)
    assert form.items == (Duration(SECOND),)


def test_c6_a_calendar_array_has_a_months_form_and_does_not_raise() -> None:
    form = canonical_cell(_arr([1], "m8[M]"))
    assert isinstance(form, Seq)
    assert form.items == (Months(1),)


def test_c12_a_boxed_bool_is_the_python_bool() -> None:
    assert type(canonical_cell(np.array(True))) is bool


@pytest.mark.parametrize(
    "cell",
    [
        pytest.param(np.array(np.datetime64("NaT")), id="C13-zero-dim-nat"),
        pytest.param(np.timedelta64("NaT", "s"), id="timedelta-nat"),
        pytest.param(np.datetime64("NaT", "ns"), id="datetime-nat"),
        pytest.param(None, id="none"),
        pytest.param(pd.NA, id="pd-na"),
        pytest.param(pd.NaT, id="pd-nat"),
        pytest.param(float("nan"), id="float-nan"),
        pytest.param(np.float32("nan"), id="numpy-nan"),
        pytest.param(Decimal("NaN"), id="decimal-nan"),
        pytest.param(np.array(float("nan")), id="boxed-nan"),
    ],
)
def test_every_null_is_the_null_form(cell: object) -> None:
    form = canonical_cell(cell)
    assert isinstance(form, Null)
    assert form == NULL
    assert hash(form) == hash(NULL)


def test_a_nested_null_equals_the_null_form_at_any_depth() -> None:
    assert canonical_cell([None, [pd.NaT]]) == canonical_cell(
        [float("nan"), [np.datetime64("NaT")]]
    )
    assert canonical_cell({"a": pd.NA}) == canonical_cell({"a": None})


def test_c17_the_zone_does_not_enter_equality() -> None:
    utc = canonical_cell(pd.Timestamp("2020-01-01", tz="UTC"))
    plus_one = canonical_cell(pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1"))
    assert isinstance(utc, Instant)
    assert isinstance(plus_one, Instant)
    assert utc == plus_one
    assert utc.zone != plus_one.zone
    assert utc.aware
    assert not canonical_cell(pd.Timestamp("2020-01-01")).aware  # type: ignore[attr-defined]


def test_c21_c23_a_far_date_and_duration_do_not_overflow() -> None:
    far = pd.Timestamp("3000-01-01").as_unit("s")
    form = canonical_cell(far)
    assert isinstance(form, Instant)
    assert temporal_text(form) == "3000-01-01 00:00:00"
    long = pd.Timedelta(np.timedelta64(146000 * 86_400, "s"))
    duration = canonical_cell(long)
    assert isinstance(duration, Duration)
    assert temporal_text(duration) == "146000 days 00:00:00"
    from_numpy = canonical_cell(np.datetime64("3000-01-01", "s"))
    assert isinstance(from_numpy, Instant)
    assert temporal_text(from_numpy) == "3000-01-01 00:00:00"
    assert temporal_text(from_numpy, nested=True) == "Timestamp('3000-01-01 00:00:00')"
    assert from_numpy == form


def test_c27_a_sub_nanosecond_instant_has_an_exact_text() -> None:
    form = canonical_cell(np.datetime64(1, "fs"))
    assert isinstance(form, Instant)
    assert temporal_text(form) == "1970-01-01T00:00:00.000000000000001"
    assert temporal_text(form, nested=True) == "1970-01-01T00:00:00.000000000000001"
    duration = canonical_cell(np.timedelta64(1, "fs"))
    assert isinstance(duration, Duration)
    assert temporal_text(duration) == "1 femtoseconds"


@pytest.mark.parametrize(
    ("cell", "top", "nested"),
    [
        (np.timedelta64(1, "s"), "0 days 00:00:01", "Timedelta('0 days 00:00:01')"),
        (np.datetime64("2020-01-01"), "2020-01-01 00:00:00", "Timestamp('2020-01-01 00:00:00')"),
        (
            pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1"),
            "2020-01-01 01:00:00+01:00",
            "Timestamp('2020-01-01 01:00:00+0100', tz='Etc/GMT-1')",
        ),
        (dt.timedelta(seconds=1), "0:00:01", "datetime.timedelta(seconds=1)"),
        (dt.datetime(2020, 1, 1), "2020-01-01 00:00:00", "datetime.datetime(2020, 1, 1, 0, 0)"),
        (np.timedelta64(3, "M"), "3 months", "3 months"),
    ],
)
def test_temporal_text_matches_str_and_repr(cell: object, top: str, nested: str) -> None:
    form = canonical_cell(cell)
    assert isinstance(form, (Instant, Duration, Months))
    assert temporal_text(form) == top
    assert temporal_text(form, nested=True) == nested


def test_temporal_text_never_raises_when_no_unit_holds_the_value() -> None:
    week = canonical_cell(np.timedelta64(2**62, "W"))
    assert isinstance(week, Duration)
    assert temporal_text(week) == f"{week.attoseconds} attoseconds"


def test_the_week_unit_is_linear() -> None:
    assert canonical_cell(np.timedelta64(1, "W")) == canonical_cell(np.timedelta64(7, "D"))


def test_the_form_never_reads_pandas_nanoseconds() -> None:
    assert canonical_cell(np.datetime64(1, "fs")) != canonical_cell(np.datetime64(2, "fs"))
    assert canonical_cell(np.datetime64(1, "ns")) == canonical_cell(pd.Timestamp(1))


def test_dict_forms_hold_values_not_only_keys() -> None:
    assert isinstance(canonical_cell({"a": 1}), Map)
    assert canonical_cell({"a": 1}) != canonical_cell({"a": 2})
    assert isinstance(canonical_cell({1}), Members)


def test_numbers_stay_equal_across_python_and_numpy_kinds() -> None:
    assert (
        canonical_cell(True)
        == canonical_cell(1)
        == canonical_cell(1.0)
        == canonical_cell(Decimal(1))
    )
    assert canonical_cell(np.longdouble(2)) == canonical_cell(2)
    assert type(canonical_cell(np.str_("a"))) is str
    assert type(canonical_cell(np.bytes_(b"a"))) is bytes


def test_a_self_holding_cell_fails_with_recursion_error() -> None:
    loop: list[object] = []
    loop.append(loop)
    with pytest.raises(RecursionError):
        canonical_cell(loop)
