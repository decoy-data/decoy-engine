"""The one rule for reading cells as text, shared by the detectors and the post-scan runner.

Bytes of every kind (bytes, bytearray, memoryview, an Arrow binary column) are decoded as strict
UTF-8, as pandas `astype(str)` decodes a bytes cell, so a byte-encoded email reads as the email
and never as Python's `b'...'` or `<memory at ...>` form. Bytes that are not UTF-8 raise
`UnreadableCellError`, whose text is fixed: a decode error names the cell's bytes.

This module is the only place the detectors and the runner turn a cell or a column into text
(`tests/sentry/test_cell_text_choke_point.py`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from decimal import Decimal

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine._error_base import DecoyError

_BYTES = (bytes, bytearray, memoryview)


class UnreadableCellError(DecoyError, ValueError):
    """A cell that cannot be read as text. The text is fixed, so no cell bytes reach a finding,
    a report or a log."""

    def __init__(self) -> None:
        super().__init__("a cell could not be read as text")


class ComparisonNotPreservedError(DecoyError):
    """A column's text keys lost the equality its cells have. The text is fixed, so no cell
    reaches the report; the table fails with this class name."""

    def __init__(self) -> None:
        super().__init__("a column's text keys do not keep its cells' equality")


def cell_text(value: object) -> str:
    """`value` as text: bytes of any kind decoded as UTF-8, anything else as `str`."""
    if not isinstance(value, _BYTES):
        return str(value)
    try:
        text: str | None = bytes(value).decode("utf-8")
    except UnicodeError:
        text = None
    if text is None:
        # Raised outside the handler, so the decode error is not chained as its context.
        raise UnreadableCellError
    return text


def column_text(series: pd.Series) -> pd.Series:
    """The non-null cells of `series` as text, whatever its dtype, index kept."""
    series = _bytes_as_objects(series)
    return _text(series[series.notna().to_numpy(dtype=bool)])


def key_text(series: pd.Series) -> list[str | None]:
    """One text key per row of `series`, None for a null. Cells of one value share a key
    whatever their type, as pandas `==` treats them: a float 10001.0 and an int 10001 must not
    read as two values, or a leaked source value looks changed. See `_number_key`."""
    return _per_cell(series, _number_key)


def detector_text(series: pd.Series) -> list[str | None]:
    """One text per row of `series`, None for a null, for the detectors to read. A cell reads as
    written, except that an integral number reads as its exact plain digits, so a PAN or phone
    kept as an int, float or `Decimal("4111111111111111.00")` stays visible. Never the key: the
    key rounds a number to its binary64 and drops the digits a detector reads."""
    return _per_cell(series, _detector_cell)


def _per_cell(series: pd.Series, render: Callable[[object], str]) -> list[str | None]:
    series = _bytes_as_objects(series)
    present = series.notna().to_numpy(dtype=bool)
    out = np.full(len(series), None, dtype=object)
    out[present] = series[present].astype(object).map(render).to_numpy(dtype=object)
    return list(out)


def _text(values: pd.Series) -> pd.Series:
    if isinstance(values.dtype, pd.CategoricalDtype):
        # The categories hold the cells; each is read once and taken back by its code.
        # Only the used ones: a filtered-out category may hold bytes no row has.
        values = values.cat.remove_unused_categories()
        categories = column_text(pd.Series(values.cat.categories))
        taken = categories.to_numpy(dtype=object)[values.cat.codes.to_numpy()]
        return pd.Series(taken, index=values.index, dtype=object)
    if values.dtype == object:
        return values.map(cell_text)
    # A bytes dtype arrives as objects (`_bytes_as_objects`), so this one holds no bytes: numbers,
    # dates and strings keep the vectorised text pandas gives them.
    return values.astype(str)


def numpy_bytes_as_objects(series: pd.Series) -> pd.Series:
    """A numpy bytes column as Python bytes cells, every byte kept; any other column unchanged.
    Arrow reads a numpy bytes cell as a C string and stops at its first NUL, so a numpy bytes
    column must not reach Arrow as it is."""
    if isinstance(series.dtype, np.dtype) and series.dtype.kind == "S":
        return pd.Series(series.to_numpy().astype(object), index=series.index, dtype=object)
    return series


def _bytes_as_objects(series: pd.Series) -> pd.Series:
    """A bytes column as Python bytes cells, every byte kept, embedded NULs included."""
    series = numpy_bytes_as_objects(series)
    if _is_arrow_binary(series.dtype):
        # Through Arrow: pandas has no filter or cast kernel for every Arrow binary type
        # (binary_view has neither).
        return pd.Series(pa.array(series).to_pylist(), index=series.index, dtype=object)
    return series


def _is_arrow_binary(dtype: object) -> bool:
    """True for Arrow binary of any width, or a pandas BinaryDtype where pandas has one."""
    if isinstance(dtype, pd.ArrowDtype):
        arrow = dtype.pyarrow_dtype
        view = getattr(pa.types, "is_binary_view", None)
        return bool(
            pa.types.is_binary(arrow)
            or pa.types.is_large_binary(arrow)
            or pa.types.is_fixed_size_binary(arrow)
            or (view is not None and view(arrow))
        )
    binary_dtype = getattr(pd, "BinaryDtype", None)
    return binary_dtype is not None and isinstance(dtype, binary_dtype)


# A number keys as the shortest text of its nearest binary64, the way NumPy and pandas compare
# int, float and Decimal (they promote to float64). Each cell first becomes its exact value, the
# General Decimal Arithmetic "reduce" form built from `Decimal.as_tuple` and
# `float.as_integer_ratio` with no context, so no precision rounds it and no int-to-str digit
# limit applies. Within binary64 range the value then goes through `float(text)` (correctly
# rounded, Clinger 1990) and `repr` (shortest round trip, Steele and White 1990), which gives
# one text for every spelling that rounds to the same double. Outside the range the exact value
# is the key. Text that is a plain decimal numeral reads as that number; a leading zero or `+`
# keeps the text, since a ZIP or phone code must reach the detectors as written.
_PLAIN_ZEROS = 32  # beyond this many padding zeros a key uses the E form, so its size is bounded
_BAND = 10**19  # an adjusted exponent beyond this is only a bucket: no real number gets there
_EXP_DIGITS = 20  # an exponent of more digits is a band, so no int() sees more than 25 digits
_ADJUSTED_RANGE = (-325, 308)  # adjusted exponents whose value can round to a finite binary64
_DETECTOR_DIGITS = 64  # longer than any detector pattern
_NUMERAL = re.compile(
    r"(?P<sign>-?)(?:(?P<whole>0|[1-9][0-9]*)(?:\.(?P<part>[0-9]*))?|\.(?P<bare>[0-9]+))"
    r"(?:[eE](?P<exp>[+-]?[0-9]+))?",
    re.ASCII,
)
_INFINITY = re.compile(r"(?P<sign>-?)inf(?:inity)?", re.ASCII | re.IGNORECASE)


def _reduced(negative: bool, digits: str, exponent: int) -> tuple[bool, str, int]:
    """(sign, coefficient, exponent) with no leading or trailing coefficient zeros; zero is an
    empty coefficient."""
    coefficient = digits.lstrip("0")
    if not coefficient:
        return False, "", 0
    trimmed = coefficient.rstrip("0")
    return negative, trimmed, exponent + len(coefficient) - len(trimmed)


def _number_text(negative: bool, digits: str, exponent: int) -> str:
    """The key of the finite number (-1)**negative * int(digits) * 10**exponent in its exact
    form: plain decimal text when it needs at most `_PLAIN_ZEROS` padding zeros, else
    `<coefficient>E<exponent>`; a band name for an absurd exponent. The form depends only on the
    value, so equal values share one key and a key read back as text is the same key."""
    negative, coefficient, exponent = _reduced(negative, digits, exponent)
    if not coefficient:
        return "0"
    point = len(coefficient) + exponent
    sign = "-" if negative else ""
    if point - 1 > _BAND:
        return f"{sign}Overflow"
    if point - 1 < -_BAND:
        return f"{sign}Underflow"
    if 0 <= exponent <= _PLAIN_ZEROS:
        text = coefficient + "0" * exponent
    elif exponent < 0 < point:
        text = f"{coefficient[:point]}.{coefficient[point:]}"
    elif exponent < 0 and -point <= _PLAIN_ZEROS:
        text = f"0.{'0' * -point}{coefficient}"
    else:
        text = f"{coefficient}E{exponent}"
    return sign + text


def _binary64_key(negative: bool, digits: str, exponent: int, nearest: float | None = None) -> str:
    """`_number_text` of the value's nearest binary64 when it has a finite non-zero one, else of
    the exact value. `nearest` is that double when the caller already has it."""
    negative, coefficient, exponent = _reduced(negative, digits, exponent)
    adjusted = exponent + len(coefficient) - 1
    if coefficient and _ADJUSTED_RANGE[0] <= adjusted <= _ADJUSTED_RANGE[1]:
        if nearest is None:
            # Never a Decimal-float operation, so no decimal context trap can fire.
            nearest = float(f"{'-' if negative else ''}{coefficient}e{exponent}")
        if math.isfinite(nearest):
            return _short_key(nearest)
    return _number_text(negative, coefficient, exponent)


def _short_key(value: float) -> str:
    """The key of a finite double: the value of its shortest round-trip text."""
    if value == 0:
        return "0"
    # `Decimal(str)` is exact and reads no context.
    return _number_text(*_decimal_exact(Decimal(repr(value))))


def _int_digits(value: int) -> str:
    # Through Decimal: `str(int)` raises past the int-to-str digit limit.
    return "".join(map(str, Decimal(abs(value)).as_tuple().digits))


def _special(negative: bool, nan: bool) -> str:
    if nan:
        return "NaN"
    return "-Infinity" if negative else "Infinity"


def _is_wide(value: float | np.floating) -> bool:
    return isinstance(value, np.floating) and np.finfo(type(value)).nmant > 52


def _float_exact(value: float | np.floating) -> tuple[bool, str, int]:
    """A finite binary float of any width at its exact value: n / 2**k is n * 5**k / 10**k."""
    numerator, denominator = value.as_integer_ratio()
    scale = denominator.bit_length() - 1
    return numerator < 0, _int_digits(abs(numerator) * 5**scale), -scale


def _float_key(value: float | np.floating) -> str:
    if not np.isfinite(value):
        return _special(bool(value < 0), bool(np.isnan(value)))
    if not _is_wide(value):
        return _short_key(float(value))
    # A wide float keys as its own `str` export, which a normal exporter writes, not as the
    # double its value happens to round to.
    return _binary64_key(*_float_exact(value), nearest=float(str(value)))


def _decimal_exact(value: Decimal) -> tuple[bool, str, int]:
    sign, digits, exponent = value.as_tuple()
    return bool(sign), "".join(map(str, digits)), int(exponent)


def _decimal_key(value: Decimal) -> str:
    if not value.is_finite():
        return _special(value.is_signed(), value.is_nan())
    return _binary64_key(*_decimal_exact(value))


def _text_key(text: str) -> str:
    """`text` read as a number when it is a plain decimal numeral or an infinity, else itself."""
    numeral = _NUMERAL.fullmatch(text)
    if numeral is None:
        infinity = _INFINITY.fullmatch(text)
        return text if infinity is None else _special(bool(infinity["sign"]), nan=False)
    fraction = numeral["part"] or numeral["bare"] or ""
    digits = (numeral["whole"] or "") + fraction
    negative = bool(numeral["sign"])
    if not digits.strip("0"):
        return "0"
    exponent = numeral["exp"] or "0"
    magnitude = exponent.lstrip("+-").lstrip("0")
    if len(magnitude) > _EXP_DIGITS:
        # The sign of the exponent picks the band; no int() sees the digits.
        band = "Underflow" if exponent.startswith("-") else "Overflow"
        return f"-{band}" if negative else band
    shift = int(magnitude or "0") * (-1 if exponent.startswith("-") else 1)
    return _binary64_key(negative, digits, shift - len(fraction))


def _number_key(value: object) -> str:
    # First: `np.timedelta64` subclasses `np.integer` and must key as the duration it equals.
    value = _python_scalar(value)
    if isinstance(value, (bool, np.bool_)):
        # pandas `==` holds True equal to 1 and 1.0, so a bool keys as the number it equals.
        return "1" if value else "0"
    if isinstance(value, (float, np.floating)):
        return _float_key(value)
    if isinstance(value, (int, np.integer)):
        return _binary64_key(int(value) < 0, _int_digits(int(value)), 0)
    if isinstance(value, Decimal):
        return _decimal_key(value)
    return _text_key(cell_text(_key_ordered(value)))


def _key_ordered(value: object) -> object:
    """`value` with every mapping in key order, so equal mappings share one text."""
    if isinstance(value, dict):
        items = sorted(((k, _key_ordered(v)) for k, v in value.items()), key=lambda kv: repr(kv[0]))
        return dict(items)
    if isinstance(value, list | tuple):
        return type(value)(_key_ordered(v) for v in value)
    return value


def _plain_digits(negative: bool, digits: str, exponent: int) -> str:
    """An integral value as plain digits when that is short, else its exact key form."""
    negative, coefficient, exponent = _reduced(negative, digits, exponent)
    if not coefficient:
        return "0"
    if len(coefficient) + exponent > _DETECTOR_DIGITS:
        return _number_text(negative, coefficient, exponent)
    return ("-" if negative else "") + coefficient + "0" * exponent


def _detector_cell(value: object) -> str:
    value = _python_scalar(value)
    if isinstance(value, (bool, np.bool_)):
        return cell_text(value)
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return cell_text(value)
        if np.floor(value) == value:
            return _plain_digits(bool(value < 0), _int_digits(value.as_integer_ratio()[0]), 0)
        return repr(float(str(value)) if _is_wide(value) else float(value))
    if isinstance(value, (int, np.integer)):
        return _plain_digits(int(value) < 0, _int_digits(int(value)), 0)
    if isinstance(value, Decimal) and value.is_finite():
        exact = _decimal_exact(value)
        return _plain_digits(*exact) if _is_integral(exact) else cell_text(value)
    return cell_text(value)


def _is_integral(exact: tuple[bool, str, int]) -> bool:
    _, coefficient, exponent = _reduced(*exact)
    return not coefficient or exponent >= 0


def _python_scalar(value: object) -> object:
    """A NumPy date or duration as the pandas value it equals, so both share one key."""
    if isinstance(value, np.timedelta64):
        return pd.Timedelta(value)
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value)
    return value
