"""The fixed argument grid of the Faker output lock, and the descriptors its arguments use.

Split from `output_lock.py` to keep that tool under the module-size goal. No engine import here:
the worker in `output_lock.py` runs the grid; this module only names the cases and decodes them.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


class OutputLockError(RuntimeError):
    """A refusal with a fixed message: no value, no exception text."""


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# The fixed argument grid: every Faker method the engine exposes with caller-supplied arguments
# (the formula helper table, `generators/_formula.py`, which a sentry derives and compares), each
# with a few explicit argument shapes. Rows are (methods, case id, args, kwargs). A descriptor is a
# JSON scalar or `{"date": "YYYY-MM-DD"}`; the lock stores the descriptor, so an edit here shows as
# a changed `arguments` field. `date_of_birth` runs through the anchored helper, the others through
# the bound Faker method.
_DATE_THIS = ("date_this_decade", "date_this_year", "date_this_month")
ARGUMENT_GRID: tuple[tuple[tuple[str, ...], str, list[Any], dict[str, Any]], ...] = (
    (("date_between",), "relative", [], {"start_date": "-30y", "end_date": "today"}),
    (
        ("date_between",),
        "absolute_strings",
        [],
        {"start_date": "2000-01-01", "end_date": "2000-12-31"},
    ),
    (
        ("date_between",),
        "date_objects",
        [],
        {"start_date": {"date": "2000-01-01"}, "end_date": {"date": "2000-12-31"}},
    ),
    (
        ("date_between",),
        "equal_boundary",
        [],
        {"start_date": {"date": "2000-01-01"}, "end_date": {"date": "2000-01-01"}},
    ),
    (_DATE_THIS, "before_only", [], {"before_today": True, "after_today": False}),
    (_DATE_THIS, "after_only", [], {"before_today": False, "after_today": True}),
    (_DATE_THIS, "both_sides", [], {"before_today": True, "after_today": True}),
    (_DATE_THIS, "neither_side", [], {"before_today": False, "after_today": False}),
    (("future_date",), "relative", [], {"end_date": "+30d"}),
    (("future_date",), "absolute_string", [], {"end_date": "2030-01-01"}),
    (("future_date",), "date_object", [], {"end_date": {"date": "2030-01-01"}}),
    (("past_date",), "relative", [], {"start_date": "-30d"}),
    (("past_date",), "absolute_string", [], {"start_date": "2000-01-01"}),
    (("past_date",), "date_object", [], {"start_date": {"date": "2000-01-01"}}),
    (("date_of_birth",), "full_bounds", [], {"minimum_age": 0, "maximum_age": 115}),
    (("date_of_birth",), "adult_range", [], {"minimum_age": 18, "maximum_age": 65}),
    (("date_of_birth",), "equal_age_boundary", [], {"minimum_age": 18, "maximum_age": 18}),
    (("date_of_birth",), "adult_positional", [None, 18, 65], {}),
)


def descriptor_ok(d: object) -> bool:
    """A JSON scalar (no float) or the closed date descriptor; nothing else is accepted."""
    if d is None or type(d) in (bool, int, str):
        return True
    if isinstance(d, dict) and set(d) == {"date"}:
        text = d["date"]
        if type(text) is not str or _DATE_RE.fullmatch(text) is None:
            return False
        try:
            date.fromisoformat(text)
        except ValueError:
            return False
        return True
    return False


def decode_descriptor(d: Any) -> Any:
    if not descriptor_ok(d):
        raise OutputLockError("an argument descriptor is not accepted")
    return date.fromisoformat(d["date"]) if isinstance(d, dict) else d


def encode_descriptor(value: Any) -> Any:
    if isinstance(value, date) and not isinstance(value, datetime):
        return {"date": value.isoformat()}
    if value is None or type(value) in (bool, int, str):
        return value
    raise OutputLockError("an argument value has no descriptor")


def grid_cells() -> dict[tuple[str, str], tuple[list[Any], dict[str, Any]]]:
    """`(method, case id) -> (args, kwargs)` descriptors, the grid expanded per method."""
    return {
        (method, case): (args, kwargs)
        for methods, case, args, kwargs in ARGUMENT_GRID
        for method in methods
    }
