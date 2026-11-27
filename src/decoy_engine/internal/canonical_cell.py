"""The one definition of when two object cells are the same value.

`canonical_cell` turns a cell into a hashable form that compares with `==`: two cells are the
same value exactly when their forms are equal. The post-mask identity counts, the text keys
(`internal/cell_text.py`) and the null decision all read it, so no reader walks a cell on its own
and a new kind of cell is one row here, not a fix per reader.

Pattern: pandas `hash_array` gives each kind one integer form and then runs one comparison. Here
a date or duration is an exact count of attoseconds in a Python `int` (the dtype's own unit would
make `datetime64[2s]` and `[s]` differ, and nanoseconds would merge 1 fs with 2 fs), and a
calendar interval is its own kind, as Arrow's `month_day_nano_interval` is: a month is no fixed
number of days. A field declared `compare=False` carries the spelling a cell had (a zone, `repr`
text, a tuple's parentheses) so a key can still read as `str()` does. It never enters `==` or
the hash.

Imports only NumPy, pandas and the standard library, so `cell_text` can import it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# Attoseconds per linear NumPy datetime unit. Y and M are calendar units and are not here.
_AS = {
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
_INT64 = (-(2**63), 2**63 - 1)


@dataclass(frozen=True)
class Null:
    """Every null at every depth. It has no comparing field, so all spellings are equal."""

    spelling: str = field(default="None", compare=False)


NULL = Null()


@dataclass(frozen=True)
class Instant:
    """A point in time. A naive and an aware instant never compare equal, as in pandas."""

    attoseconds: int
    aware: bool
    zone: object = field(default=None, compare=False)
    source: object = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Duration:
    """A linear length of time."""

    attoseconds: int
    source: object = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Months:
    """A calendar interval in months. It equals no duration."""

    months: int


@dataclass(frozen=True)
class Seq:
    """A list, tuple, namedtuple or array. `style` is how `str()` writes it."""

    items: tuple[object, ...]
    style: str = field(default="list", compare=False)


@dataclass(frozen=True)
class Map:
    """A mapping, equal to another with the same pairs in any order. `entries` is the display:
    each key's `repr` in sorted order beside its canonical value."""

    pairs: frozenset[object]
    entries: tuple[tuple[str, object], ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class Members:
    """A set or frozenset. `spelling` is the container's own `repr`."""

    items: frozenset[object]
    spelling: str = field(default="", compare=False)


@dataclass(frozen=True)
class Record:
    """A NumPy record scalar. It compares as the canonical form of the Python tuple it holds, so it
    is hashable; `spelling` is that tuple's `repr`, as an exporter writes it."""

    fields: object
    spelling: str = field(default="", compare=False)


class Blob(bytes):
    """Bytes read from a bytearray or memoryview: equal to the same bytes, spelled as the source."""

    spelling: str

    def __new__(cls, data: bytes, spelling: str) -> Blob:
        blob = super().__new__(cls, data)
        blob.spelling = spelling
        return blob


Temporal = Instant | Duration | Months
TEMPORAL = (Instant, Duration, Months)


def canonical_cell(value: object) -> object:
    """`value` as its canonical form: `NULL` for a null, a temporal form, a number or text leaf,
    a container form, or the value itself when it is none of those (an "other" leaf)."""
    value = unboxed(value)
    if _is_null(value):
        spelling = _null_spelling(value)
        return NULL if spelling == NULL.spelling else Null(spelling)
    temporal = _temporal(value)
    if temporal is not None:
        return temporal
    leaf = _leaf(value)
    return leaf if leaf is not value else _container(value)


def unboxed(value: object) -> object:
    """A 0-dim array as the payload it holds, repeatedly. The masked constant is a 0-dim array
    that holds itself, so it stays as it is, and a cycle raises as a nested cell does."""
    seen: set[int] = set()
    while isinstance(value, np.ndarray) and value.ndim == 0 and value is not np.ma.masked:
        if id(value) in seen:
            raise RecursionError
        seen.add(id(value))
        value = value[()]
    return value


def is_null(value: object) -> bool:
    """True when `canonical_cell(value)` is a null, without walking a container."""
    return _is_null(unboxed(value))


def _is_null(value: object) -> bool:
    if value is np.ma.masked:
        return True
    if isinstance(value, (list, tuple, dict, set, frozenset, np.ndarray, str, bytes)):
        return False
    result = pd.isna(value)
    return isinstance(result, (bool, np.bool_)) and bool(result)


def _null_spelling(value: object) -> str:
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return "NaT"
    if isinstance(value, np.generic):
        # The Python value it holds, as a container shows it.
        return repr(value.item())
    return repr(value)


def _temporal(value: object) -> Temporal | int | None:
    """The temporal form of a date or duration, a generic NumPy count as its int, else None."""
    if isinstance(value, np.datetime64):
        return _datetime64(value, value)
    if isinstance(value, np.timedelta64):
        return _timedelta64(value, value)
    if isinstance(value, pd.Timestamp):
        # `asm8` keeps the value's own unit and is UTC when aware, so no step converts to ns.
        base = _datetime64(value.asm8, value)
        return Instant(base.attoseconds, value.tzinfo is not None, value.tz, value)
    if isinstance(value, pd.Timedelta):
        return _timedelta64(value.asm8, value)
    if isinstance(value, dt.datetime):
        return _python_datetime(value)
    if isinstance(value, dt.timedelta):
        return Duration(_timedelta_attoseconds(value), value)
    return None


def _datetime64(value: np.datetime64, source: object) -> Instant:
    unit, count = np.datetime_data(value.dtype)
    ticks = int(value.astype(np.int64)) * count
    if unit in ("Y", "M"):
        # A calendar date converts to days exactly; a calendar length would not. Python integers,
        # because NumPy would wrap the day count of a far year.
        months = ticks * (12 if unit == "Y" else 1)
        return Instant(_first_of_month(months) * _AS["D"], False, None, source)
    return Instant(ticks * _AS[unit], False, None, source)


def _first_of_month(months: int) -> int:
    """Days from 1970-01-01 to the first day of the month `months` after January 1970
    (Hinnant, `days_from_civil`)."""
    year, month = 1970 + months // 12, months % 12 + 1
    year -= month <= 2
    era, year_of_era = divmod(year, 400)
    day_of_year = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146_097 + day_of_era - 719_468


def _timedelta64(value: np.timedelta64, source: object) -> Temporal | int:
    unit, count = np.datetime_data(value.dtype)
    ticks = int(value.astype(np.int64))
    if unit == "generic":
        # A bare count: `np.timedelta64(5) == 5`, so it is the number.
        return ticks
    if unit in ("Y", "M"):
        return Months(ticks * count * (12 if unit == "Y" else 1))
    return Duration(ticks * count * _AS[unit], source)


def _timedelta_attoseconds(value: dt.timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 10**18 + value.microseconds * 10**12


def _python_datetime(value: dt.datetime) -> Instant:
    offset = value.utcoffset()
    naive = _timedelta_attoseconds(value.replace(tzinfo=None) - _EPOCH)
    if offset is None:
        return Instant(naive, False, None, value)
    return Instant(naive - _timedelta_attoseconds(offset), True, value.tzinfo, value)


def _leaf(value: object) -> object:
    """A number or text leaf in one Python form; anything else comes back as it is."""
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.float16, np.float32, np.float64)):
        return float(value)
    if isinstance(value, (np.complex64, np.complex128)):
        return complex(value)
    if isinstance(value, (bytearray, memoryview)):
        return Blob(bytes(value), repr(value))
    if isinstance(value, bytes):
        return value if type(value) is bytes else bytes(value)
    if isinstance(value, str):
        return value if type(value) is str else str(value)
    if isinstance(value, np.generic):
        # Any other NumPy scalar (a void, a record) as the Python value it holds.
        item = value.item()
        if isinstance(value, np.void) and value.dtype.names:
            return Record(canonical_cell(item), repr(item))
        if type(item) is not type(value):
            return canonical_cell(item)
    return value


def _container(value: object) -> object:
    if isinstance(value, (np.ndarray, list)):
        return Seq(tuple(canonical_cell(v) for v in value), "list")
    if isinstance(value, tuple):
        return Seq(tuple(canonical_cell(v) for v in value), "tuple")
    if isinstance(value, dict):
        rows = [(repr(k), canonical_cell(k), canonical_cell(v)) for k, v in value.items()]
        entries = tuple(sorted(((r, v) for r, _, v in rows), key=lambda e: e[0]))
        return Map(frozenset((k, v) for _, k, v in rows), entries)
    if isinstance(value, (set, frozenset)):
        return Members(frozenset(canonical_cell(v) for v in value), repr(value))
    return value


def temporal_text(form: Temporal, *, nested: bool = False) -> str:
    """The text of a temporal form: `str()` of the value it came from at the top level, its
    `repr` inside a container. A NumPy value has no spelling of its own, so it reads as the
    pandas value it equals, or as an exact NumPy or attosecond text when pandas cannot hold it.
    Never raises."""
    if isinstance(form, Months):
        return _months_text(form.months)
    source = form.source
    if source is not None and not isinstance(source, (np.datetime64, np.timedelta64)):
        return repr(source) if nested else str(source)
    return _exact_text(form.attoseconds, isinstance(form, Instant), nested)


def _fits(ticks: int) -> bool:
    """True when NumPy can hold `ticks` as a value. The lowest int64 is its NaT."""
    return _INT64[0] < ticks <= _INT64[1]


def _months_text(months: int) -> str:
    if not _fits(months):
        return f"{months} months"
    return str(np.timedelta64(months, "M"))


def _exact_text(attoseconds: int, instant: bool, nested: bool) -> str:
    make_np: Any = np.datetime64 if instant else np.timedelta64
    make_pd = pd.Timestamp if instant else pd.Timedelta
    nanos, remainder = divmod(attoseconds, _AS["ns"])
    if remainder == 0 and _fits(nanos):
        shown = pd.Timestamp(nanos) if instant else pd.Timedelta(nanos, unit="ns")
        return repr(shown) if nested else str(shown)
    for unit in ("s", "ms", "us"):
        if attoseconds % _AS[unit] == 0 and _fits(attoseconds // _AS[unit]):
            try:
                shown = make_pd(make_np(attoseconds // _AS[unit], unit))
            except (OverflowError, ValueError):
                break
            return repr(shown) if nested else str(shown)
    for unit in ("ns", "ps", "fs", "as"):
        if attoseconds % _AS[unit] == 0 and _fits(attoseconds // _AS[unit]):
            return str(make_np(attoseconds // _AS[unit], unit))
    # No unit holds it. The kind stays in the text so an instant never keys as a duration.
    return f"{attoseconds} attoseconds" + (" from the epoch" if instant else "")
