"""The calendar ranges a date computation can hold, and the admission of a fitted datetime snapshot.

One definition of the whole days inside the pandas `datetime64[ns]` range (1677-09-22 to
2262-04-10, because the range itself starts at 00:12 on 09-21 and ends at 23:47 on 04-11). Date
strategies and the fitted distribution generator read these names, so the text-date domain is
stated in one place.

`admit_ns_datetime_snapshot` is the admission the distribution generator runs before any draw:
the snapshot's min, max and every live year bin must lie in that domain. It refuses with
`plan/generation_unbounded_column` and names the property, never a value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from pandas.errors import OutOfBoundsDatetime

from decoy_engine import reasons
from decoy_engine._arrow_types import CALENDAR_FIRST_DAY_NUMBER, CALENDAR_LAST_DAY_NUMBER
from decoy_engine.errors import DecoyError

NS_FIRST_DAY = date(1677, 9, 22)
NS_LAST_DAY = date(2262, 4, 10)
_EPOCH = date(1970, 1, 1)
# The day numbers live in `_arrow_types`; the dates derive from them.
CALENDAR_FIRST_DAY = _EPOCH + timedelta(days=CALENDAR_FIRST_DAY_NUMBER)
CALENDAR_LAST_DAY = _EPOCH + timedelta(days=CALENDAR_LAST_DAY_NUMBER)
NS_PER_DAY = 86_400 * 1_000_000_000
# Day numbers since 1970-01-01. `NS_END_DAY` is exclusive: the day after the last whole day.
NS_FIRST_DAY_NUMBER = (NS_FIRST_DAY - _EPOCH).days
NS_END_DAY_NUMBER = (NS_LAST_DAY - _EPOCH).days + 1

CODE_UNBOUNDED = reasons.plan.GENERATION_UNBOUNDED_COLUMN


class FittedRangeError(DecoyError):
    """A fitted datetime snapshot names a date the generator cannot hold.

    Names the property (`min`, `max` or `year_bins`) and the supported years, which are constants.
    It never carries a snapshot value.
    """

    code: str = CODE_UNBOUNDED

    def __init__(self, *, prop: str) -> None:
        self.prop = prop
        super().__init__(
            f"[{self.code}] {prop}: a fitted datetime must lie in "
            f"{NS_FIRST_DAY.isoformat()} to {NS_LAST_DAY.isoformat()}."
        )


@dataclass(frozen=True)
class NsDatetimeAdmission:
    """What the admission proved: both bounds as day-and-nanosecond-exact integers."""

    min_ns: int
    max_ns: int


_ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?)?"
)


def _ns_since_epoch(text: str) -> int:
    """Nanoseconds since the epoch, in UTC, of a datetime text.

    The usual ISO forms are read with integers on the Python calendar so the same text gives the
    same answer on every interpreter: all nine fractional digits count, and a zone offset at year
    1 or 9999 cannot overflow. A naive text is UTC. A date with a zone (no time) is not ISO and
    falls through, with every other form, to the pandas parser the sampler always used. Text no
    parser reads raises `ValueError`; a value pandas reads but cannot hold in nanoseconds raises
    `OverflowError`, which the caller reports as out of range.
    """
    match = _ISO.fullmatch(text.strip())
    if match is None:
        stamp = pd.Timestamp(text)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC")
        return int(stamp.value)
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    days = (date(int(year), int(month), int(day)) - _EPOCH).days
    if int(hour or 0) > 23 or int(minute or 0) > 59 or int(second or 0) > 59:
        raise ValueError("time of day out of range")
    seconds = int(hour or 0) * 3600 + int(minute or 0) * 60 + int(second or 0)
    nanos = int((fraction or "").ljust(9, "0"))
    offset = 0
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        if int(digits[:2]) > 23 or int(digits[2:]) > 59:
            raise ValueError("zone offset out of range")
        offset = sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return ((days * 86_400 + seconds - offset) * 1_000_000_000) + nanos


def admit_ns_datetime_snapshot(
    min_iso: str, max_iso: str, live_years: Iterable[int]
) -> NsDatetimeAdmission:
    """Check a fitted datetime's bounds and live years against the whole-day nanosecond domain.

    `min_iso` and `max_iso` are datetime text. Text that does not parse raises `ValueError` (the
    caller's own unparseable path); text that parses outside the domain raises `FittedRangeError`.
    """
    first, end = NS_FIRST_DAY_NUMBER * NS_PER_DAY, NS_END_DAY_NUMBER * NS_PER_DAY
    bounds: dict[str, int] = {}
    for prop, text in (("min", min_iso), ("max", max_iso)):
        too_far = False
        try:
            bounds[prop] = _ns_since_epoch(str(text))
        except (OutOfBoundsDatetime, OverflowError):
            too_far = True
        # Raised outside the handler: the bound is a data value, so nothing may chain it.
        if too_far or not first <= bounds[prop] < end:
            raise FittedRangeError(prop=prop)
    if any(not NS_FIRST_DAY.year <= year <= NS_LAST_DAY.year for year in live_years):
        raise FittedRangeError(prop="year_bins")
    return NsDatetimeAdmission(bounds["min"], bounds["max"])


__all__ = [
    "CALENDAR_FIRST_DAY",
    "CALENDAR_LAST_DAY",
    "NS_END_DAY_NUMBER",
    "NS_FIRST_DAY",
    "NS_FIRST_DAY_NUMBER",
    "NS_LAST_DAY",
    "NS_PER_DAY",
    "FittedRangeError",
    "NsDatetimeAdmission",
    "admit_ns_datetime_snapshot",
]
