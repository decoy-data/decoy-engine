"""A fixed-offset timestamp zone is checked by integer comparison, not by `local_timestamp`
(DATE-RANGE-SENTINEL S5 remediation, V1-1): pyarrow 14 raises on `local_timestamp` near the
calendar edge for an instant that is valid."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine._arrow_types import CALENDAR_FIRST_DAY_NUMBER, CALENDAR_LAST_DAY_NUMBER
from decoy_engine.io import check_source_dates

DAY_US = 86_400 * 10**6
FIRST_US = CALENDAR_FIRST_DAY_NUMBER * DAY_US
LAST_US = (CALENDAR_LAST_DAY_NUMBER + 1) * DAY_US - 1
HOUR_US = 3_600 * 10**6


def _column(value: int, tz: str) -> pa.Table:
    return pa.table({"d": pa.array([value], pa.timestamp("us", tz=tz))})


@pytest.mark.parametrize(
    ("value", "tz"),
    [
        (FIRST_US, "+05:30"),  # local 05:30 of year 1: valid
        (FIRST_US + 6 * HOUR_US, "-05:30"),  # local 00:30 of year 1
        (LAST_US - 6 * HOUR_US, "+05:30"),  # local is still 9999-12-31
        (LAST_US, "-05:30"),
    ],
)
def test_a_valid_instant_in_a_fixed_offset_zone_is_read(value: int, tz: str) -> None:
    table = _column(value, tz)
    assert (
        check_source_dates(table, table="t").column("d").to_pylist()
        == table.column("d").to_pylist()
    )


@pytest.mark.parametrize(
    ("value", "tz"),
    [
        (FIRST_US, "-05:30"),  # the local date is before year 1
        (LAST_US, "+05:30"),  # the local date is after year 9999
        (FIRST_US - 1, "+05:30"),  # the instant itself is before year 1
        (LAST_US + 1, "-05:30"),
    ],
)
def test_a_crossing_in_a_fixed_offset_zone_is_refused_once(value: int, tz: str) -> None:
    with pytest.raises(Exception) as caught:
        check_source_dates(_column(value, tz), table="t")
    exc = caught.value
    assert getattr(exc, "code", None) == reasons.runtime.SOURCE_DATE_UNREPRESENTABLE, repr(exc)
    assert (exc.table, exc.column, exc.count) == ("t", "d", 1)  # type: ignore[attr-defined]
