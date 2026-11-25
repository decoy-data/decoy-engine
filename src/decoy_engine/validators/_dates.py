"""Date parsing and column checks shared by the relationship validators.

``OneFormatDates`` parses a date column with one format for every batch, so a column that is
split into chunks gets the verdict it gets whole. ``require_columns`` refuses a parent table that
lacks a key or window column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from pandas.tseries.api import guess_datetime_format

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError

if TYPE_CHECKING:
    from decoy_engine.validators._types import RowSpan

_UNSET: Any = object()

# The strings pandas passes over when it looks for the first value of a column to guess a format
# from (`pandas._libs.tslib.first_non_null` skips these and every null object). A guard test
# compares this set with pandas itself.
PANDAS_BLANK_STRINGS = frozenset({"", "NAT", "NaT", "nat", "NAN", "NaN", "nan"})


def is_blank(value: Any) -> bool:
    if isinstance(value, str):
        return value in PANDAS_BLANK_STRINGS
    return value is None or bool(pd.isna(value))


def require_columns(span: RowSpan, table: str, columns: list[str]) -> None:
    """Refuse a parent table that lacks a key or window column, naming the columns only."""
    names = set(span.output.schema.names)
    missing = [c for c in columns if c not in names]
    if missing:
        raise ValidatorStateError(
            code=reasons.runtime.VALIDATOR_COLUMN_MISSING,
            message=f"table {table!r} has no column(s) {missing!r} that the validator needs.",
        )


class OneFormatDates:
    """Parses one date column with one format for every span, to integer microseconds.

    pandas 2 infers the format from the first value of whatever it is given that is not null or
    a null string, so the same rows parse differently when split into chunks. This takes the
    first such value of the column (by pandas' own rule, `is_blank`), guesses its format once
    (`guess_datetime_format`, the guess `to_datetime` makes), and passes it as ``format`` to every
    span, with ``format="mixed"`` when the guess is None, which is what `to_datetime` does for a
    whole column then. Non-string values (dates, timestamps) need no format. The format stays
    unset while every value seen so far is blank. A cell that does not parse comes back as None.
    """

    def __init__(self) -> None:
        self._format: Any = _UNSET

    def parse(self, values: list[Any]) -> list[int | None]:
        series = pd.Series(values, dtype=object) if not values else pd.Series(values)
        if self._format is _UNSET:
            first = next((v for v in values if not is_blank(v)), _UNSET)
            if first is not _UNSET:
                if isinstance(first, str):
                    self._format = guess_datetime_format(first) or "mixed"
                else:
                    self._format = None
        if self._format is _UNSET or self._format is None:
            parsed = pd.to_datetime(series, errors="coerce")
        else:
            parsed = pd.to_datetime(series, format=self._format, errors="coerce")
        if parsed.dtype == object:
            parsed = pd.to_datetime(parsed, errors="coerce", utc=True)
        index = pd.DatetimeIndex(parsed).as_unit("us")
        return [
            None if missing else int(value)
            for value, missing in zip(index.asi8.tolist(), index.isna().tolist(), strict=True)
        ]
