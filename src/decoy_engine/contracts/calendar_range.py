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

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from decoy_engine import reasons
from decoy_engine.errors import DecoyError

NS_FIRST_DAY = date(1677, 9, 22)
NS_LAST_DAY = date(2262, 4, 10)
CALENDAR_FIRST_DAY = date.min
CALENDAR_LAST_DAY = date.max

_EPOCH = date(1970, 1, 1)
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


def _naive_utc(value: datetime) -> datetime:
    return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)


def _ns_since_epoch(value: datetime) -> int:
    days = (value.date() - _EPOCH).days
    micros = ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000_000 + value.microsecond
    return days * NS_PER_DAY + micros * 1_000


def admit_ns_datetime_snapshot(
    min_iso: str, max_iso: str, live_years: Iterable[int]
) -> NsDatetimeAdmission:
    """Check a fitted datetime's bounds and live years against the whole-day nanosecond domain.

    `min_iso` and `max_iso` are ISO text. Text that does not parse raises `ValueError` (the
    caller's own unparseable path); text that parses outside the domain raises `FittedRangeError`.
    The bounds are read on the Python calendar, so a far date is named and refused, never lost.
    """
    bounds: dict[str, datetime] = {}
    for prop, text in (("min", min_iso), ("max", max_iso)):
        bounds[prop] = _naive_utc(datetime.fromisoformat(str(text)))
    for prop, value in bounds.items():
        day = (value.date() - _EPOCH).days
        if not NS_FIRST_DAY_NUMBER <= day < NS_END_DAY_NUMBER:
            raise FittedRangeError(prop=prop)
    if any(not NS_FIRST_DAY.year <= year <= NS_LAST_DAY.year for year in live_years):
        raise FittedRangeError(prop="year_bins")
    return NsDatetimeAdmission(_ns_since_epoch(bounds["min"]), _ns_since_epoch(bounds["max"]))


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
