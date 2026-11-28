"""Shared cell atoms: unboxing, the null test, exact temporal forms and number primitives.

Both cell readers sit above this module: `cell_identity` (is a source cell the same value as an
output cell) and `cell_text` (what text the detectors read). Neither owns the other's rules, so
a date reads as one exact instant for both, and a number's digits come from one routine.

A date or duration is an exact count of attoseconds in a Python `int`: the dtype's own unit
would make `datetime64[2s]` and `[s]` differ, and nanoseconds would merge 1 fs with 2 fs. A
calendar interval is its own kind, as Arrow's `month_day_nano_interval` is: a month is no fixed
number of days. Values are read through `asm8` and NumPy ticks, never `.value`, so no unit is
converted to nanoseconds on the way, and calendar months convert with Python integers.

Imports only NumPy, pandas, the standard library and `pandas_missing`.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd

from decoy_engine._error_base import DecoyError
from decoy_engine.internal.pandas_missing import is_null_cell

# Attoseconds per linear NumPy datetime unit. Y and M are calendar units and are not here.
AS = {
    "W": 7 * 86_400 * 10**18,
    "D": 86_400 * 10**18,
    "h": 3_600 * 10**18,
    "m": 60 * 10**18,
    "s": 10**18,
    "ms": 10**15,
    "us": 10**12,
    "ns": 10**9,
    "ps": 10**6,
    "fs": 10**3,
    "as": 1,
}
_EPOCH = dt.datetime(1970, 1, 1)  # naive on purpose: offsets are applied by hand


class CellNotComparableError(DecoyError):
    """A cell the comparison authority refuses: a NumPy record at any depth, a container that
    holds itself, or an unhashable object of no known kind. The text is fixed, so no cell reaches
    a finding, a report or a log; the column fails with this class name."""

    def __init__(self) -> None:
        super().__init__("a column holds a cell that cannot be compared")


@dataclass(frozen=True)
class Instant:
    """A point in time. `attoseconds` is UTC for an aware instant and the wall clock for a naive
    one. Equality and hashing read the count and the awareness tag; `local` (an aware value's
    own wall clock) is read only when an aware instant meets a naive one."""

    attoseconds: int
    aware: bool
    local: int = field(default=0, compare=False)


@dataclass(frozen=True)
class Duration:
    """A linear length of time."""

    attoseconds: int


@dataclass(frozen=True)
class Months:
    """A calendar interval in months. It equals no duration."""

    months: int


Temporal = Instant | Duration | Months
TEMPORAL = (Instant, Duration, Months)


def unboxed(value: object) -> object:
    """A 0-dim array as the payload it holds, repeatedly. The masked constant is a 0-dim array
    that holds itself, so it stays as it is. A box that holds itself is refused."""
    seen: set[int] = set()
    cycle = False
    while isinstance(value, np.ndarray) and value.ndim == 0 and value is not np.ma.masked:
        if id(value) in seen:
            cycle = True
            break
        seen.add(id(value))
        value = value[()]
    if cycle:
        raise CellNotComparableError
    return value


def is_null(value: object) -> bool:
    """True when `value`, unboxed, is a null: the masker's own predicate, so both agree."""
    return is_null_cell(unboxed(value))


def temporal_form(value: object) -> Temporal | int | None:
    """The exact form of a date, instant or duration; a generic NumPy count as its int; else
    None. The caller has ruled out nulls."""
    if isinstance(value, np.datetime64):
        return _datetime64(value)
    if isinstance(value, np.timedelta64):
        return _timedelta64(value)
    if isinstance(value, pd.Timestamp):
        # `asm8` keeps the value's own unit and is UTC when aware, so no step converts to ns.
        base = _datetime64(value.asm8).attoseconds
        offset = value.utcoffset()
        if offset is None:
            return Instant(base, False, base)
        return Instant(base, True, base + timedelta_attoseconds(offset))
    if isinstance(value, pd.Timedelta):
        return _timedelta64(value.asm8)
    if isinstance(value, dt.datetime):
        return _python_datetime(value)
    if isinstance(value, dt.date):
        # A date is the naive midnight that starts it, so it meets the same day as a datetime64.
        at = (value.toordinal() - _EPOCH.toordinal()) * AS["D"]
        return Instant(at, False, at)
    if isinstance(value, dt.timedelta):
        return Duration(timedelta_attoseconds(value))
    return None


def _datetime64(value: np.datetime64) -> Instant:
    unit, count = np.datetime_data(value.dtype)
    ticks = int(value.astype(np.int64)) * count
    if unit in ("Y", "M"):
        # A calendar date converts to days exactly; a calendar length would not. Python integers,
        # because NumPy would wrap the day count of a far year.
        at = first_of_month(ticks * (12 if unit == "Y" else 1)) * AS["D"]
    else:
        at = ticks * AS.get(unit, 1)
    return Instant(at, False, at)


def first_of_month(months: int) -> int:
    """Days from 1970-01-01 to the first day of the month `months` after January 1970
    (Hinnant, `days_from_civil`)."""
    year, month = 1970 + months // 12, months % 12 + 1
    year -= month <= 2
    era, year_of_era = divmod(year, 400)
    day_of_year = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146_097 + day_of_era - 719_468


def _timedelta64(value: np.timedelta64) -> Temporal | int:
    unit, count = np.datetime_data(value.dtype)
    ticks = int(value.astype(np.int64))
    if unit == "generic":
        # A bare count: `np.timedelta64(5) == 5`, so it is the number.
        return ticks
    if unit in ("Y", "M"):
        return Months(ticks * count * (12 if unit == "Y" else 1))
    return Duration(ticks * count * AS[unit])


def timedelta_attoseconds(value: dt.timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 10**18 + value.microseconds * 10**12


def _python_datetime(value: dt.datetime) -> Instant:
    offset = value.utcoffset()
    wall = timedelta_attoseconds(value.replace(tzinfo=None) - _EPOCH)
    if offset is None:
        return Instant(wall, False, wall)
    return Instant(wall - timedelta_attoseconds(offset), True, wall)


# Number primitives. A number is read at its exact value, (sign, coefficient digits, exponent),
# the General Decimal Arithmetic "reduce" form built from `Decimal.as_tuple` and
# `float.as_integer_ratio` with no context, so no precision rounds it and no int-to-str digit
# limit applies. Numeral text is read by `NUMERAL` with `fullmatch`; an exponent of more than
# `EXP_DIGITS` digits is never converted, so no `int()` sees more than 25 digits.
EXP_DIGITS = 20
NUMERAL = re.compile(
    r"(?P<sign>-?)(?:(?P<whole>0|[1-9][0-9]*)(?:\.(?P<part>[0-9]*))?|\.(?P<bare>[0-9]+))"
    r"(?:[eE](?P<exp>[+-]?[0-9]+))?",
    re.ASCII,
)
INFINITY = re.compile(r"(?P<sign>-?)inf(?:inity)?", re.ASCII | re.IGNORECASE)

Exact = tuple[bool, str, int]


def reduced(negative: bool, digits: str, exponent: int) -> Exact:
    """(sign, coefficient, exponent) with no leading or trailing coefficient zeros; zero is an
    empty coefficient with no sign."""
    coefficient = digits.lstrip("0")
    if not coefficient:
        return False, "", 0
    trimmed = coefficient.rstrip("0")
    return negative, trimmed, exponent + len(coefficient) - len(trimmed)


def int_digits(value: int) -> str:
    """The decimal digits of `abs(value)`. Through Decimal: `str(int)` raises past the
    int-to-str digit limit."""
    return "".join(map(str, Decimal(abs(value)).as_tuple().digits))


def decimal_exact(value: Decimal) -> Exact:
    sign, digits, exponent = value.as_tuple()
    return bool(sign), "".join(map(str, digits)), int(exponent)


def float_exact(value: float | np.floating) -> Exact:
    """A finite binary float of any width at its exact value: n / 2**k is n * 5**k / 10**k."""
    numerator, denominator = value.as_integer_ratio()
    scale = denominator.bit_length() - 1
    return numerator < 0, int_digits(abs(numerator) * 5**scale), -scale


def is_wide(value: object) -> bool:
    """True for a NumPy float wider than binary64 (`np.longdouble` where it is wider)."""
    return isinstance(value, np.floating) and np.finfo(type(value)).nmant > 52


def numeral_exact(text: str) -> Exact | None:
    """The exact value of a plain decimal numeral, reduced, or None when `text` is not one or
    its exponent is too long for any finite number."""
    numeral = NUMERAL.fullmatch(text)
    if numeral is None:
        return None
    fraction = numeral["part"] or numeral["bare"] or ""
    digits = (numeral["whole"] or "") + fraction
    exponent = numeral["exp"] or "0"
    written = exponent.lstrip("+-")
    # The written digits, zeros included: a padded exponent is not an export spelling.
    if len(written) > EXP_DIGITS:
        return None
    shift = int(written) * (-1 if exponent.startswith("-") else 1)
    return reduced(bool(numeral["sign"]), digits, shift - len(fraction))
