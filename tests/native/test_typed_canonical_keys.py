"""DATE-SHIFT-TYPED T2 (S1 part): the typed key bytes and the `date32` source preflight.

`canonicalize_typed_array` builds every row's key in Arrow. For each date Python can represent,
the key must be the bytes `_canonicalize_source` gives the same `datetime.date`, so a typed date
and the same date held as ISO text in another table shift alike in one namespace. A day outside
years 1 to 9999 has no Python date: it fails before formatting and gets no key.
"""

from __future__ import annotations

import datetime as dt

import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.generation.pool._canonicalize import (
    _canonicalize_source,
    canonicalize_typed_array,
)
from decoy_engine.transforms.date_shift import DATE32_MAX_DAY, DATE32_MIN_DAY

_DAY_IN_RANGE = st.integers(min_value=DATE32_MIN_DAY, max_value=DATE32_MAX_DAY)


def _keys(days: list[int | None]) -> tuple[list[bytes | None], list[bool]]:
    keys, failed = canonicalize_typed_array(pa.array(days, pa.int32()).cast(pa.date32()))
    assert keys.type == pa.string()
    return [None if k is None else k.encode("utf-8") for k in keys.to_pylist()], failed.tolist()


@settings(max_examples=300, deadline=None)
@given(st.lists(st.one_of(st.none(), _DAY_IN_RANGE), max_size=40))
def test_keys_equal_canonicalize_source_for_every_representable_date(
    days: list[int | None],
) -> None:
    keys, failed = _keys(days)
    epoch = dt.date(1970, 1, 1)
    expected = [None if d is None else _canonicalize_source(epoch + dt.timedelta(d)) for d in days]
    assert keys == expected
    assert not any(failed)


@pytest.mark.parametrize(
    ("day", "failed"),
    [
        (DATE32_MIN_DAY - 1, True),
        (DATE32_MIN_DAY, False),
        (DATE32_MIN_DAY + 1, False),
        (-1, False),
        (0, False),
        (DATE32_MAX_DAY - 1, False),
        (DATE32_MAX_DAY, False),
        (DATE32_MAX_DAY + 1, True),
        (-(2**31), True),
        (2**31 - 1, True),
    ],
)
def test_the_year_bounds_decide_which_days_get_a_key(day: int, failed: bool) -> None:
    keys, flags = _keys([day, None])
    assert flags == [failed, False]
    if failed:
        assert keys == [None, None]
    else:
        date = dt.date(1970, 1, 1) + dt.timedelta(day)
        assert keys == [_canonicalize_source(date), None]


def test_the_key_is_the_iso_text_not_the_day_number() -> None:
    """The raw int32 day would change every typed offset and split typed from text keys."""
    keys, _ = _keys([19737])
    assert keys == [b"2024-01-15"]


def test_only_date32_has_a_typed_key_in_s1() -> None:
    with pytest.raises(TypeError):
        canonicalize_typed_array(pa.array([dt.date(2024, 1, 15)], pa.date64()))
