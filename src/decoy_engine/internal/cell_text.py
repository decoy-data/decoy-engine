"""The one rule for reading cells as text, shared by the detectors and the post-scan runner.

Bytes of every kind (bytes, bytearray, memoryview, an Arrow binary column) are decoded as strict
UTF-8, as pandas `astype(str)` decodes a bytes cell, so a byte-encoded email reads as the email
and never as Python's `b'...'` or `<memory at ...>` form. Bytes that are not UTF-8 raise
`UnreadableCellError`, whose text is fixed: a decode error names the cell's bytes.

This module is the only place the detectors and the runner turn a cell or a column into text
(`tests/sentry/test_cell_text_choke_point.py`).
"""

from __future__ import annotations

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
    """One text key per row of `series`, None for a null. A number reads as a key that is equal
    for equal numbers whatever their type, as pandas `==` treats them: a float 10001.0 and an int
    10001 must not read as two values, or a leaked source value looks changed."""
    series = _bytes_as_objects(series)
    present = series.notna().to_numpy(dtype=bool)
    keys = np.full(len(series), None, dtype=object)
    keys[present] = series[present].astype(object).map(_number_key).to_numpy(dtype=object)
    return list(keys)


def _text(values: pd.Series) -> pd.Series:
    if isinstance(values.dtype, pd.CategoricalDtype):
        # The categories hold the cells; each is read once and taken back by its code.
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


def _wide_float_key(value: np.floating) -> str:
    """The key of a finite float that a double cannot hold (longdouble). It comes from the exact
    integer ratio, so two distinct values never share a key. It reads no process setting: not the
    decimal context precision, and not the int-to-str digit limit, which `Decimal(int)` and hex
    formatting both skip. A whole value gets its decimal digits, so it matches an int cell."""
    numerator, denominator = value.as_integer_ratio()
    if denominator == 1:
        return str(Decimal(numerator))
    return f"{numerator:x}/{denominator:x}"


def _number_key(value: object) -> str:
    if isinstance(value, np.floating) and np.isfinite(value) and value != float(value):
        return _wide_float_key(value)
    value = _python_scalar(value)
    if isinstance(value, bool):
        # pandas `==` holds True equal to 1 and 1.0, so a bool keys as the number it equals.
        return "1" if value else "0"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return str(value)
        if value == value.to_integral_value():
            return str(int(value))
        return format(value.normalize(), "f")
    return cell_text(value)


def _python_scalar(value: object) -> object:
    """A NumPy scalar as the Python or pandas value it equals, so both share one key. Checked
    before the Python types: `np.float64` is a `float`, but its `repr` names NumPy."""
    if isinstance(value, np.timedelta64):
        return pd.Timedelta(value)
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value
