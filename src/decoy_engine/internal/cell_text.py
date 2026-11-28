"""The one rule for reading cells as text, shared by the detectors and the post-scan runner.

Bytes of every kind (bytes, bytearray, memoryview, an Arrow binary column) are decoded as strict
UTF-8, as pandas `astype(str)` decodes a bytes cell, so a byte-encoded email reads as the email
and never as Python's `b'...'` or `<memory at ...>` form. Bytes that are not UTF-8 raise
`UnreadableCellError`, whose text is fixed: a decode error names the cell's bytes.

This module is the only place the detectors and the runner turn a cell or a column into text
(`tests/sentry/test_cell_text_choke_point.py`).
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine._error_base import DecoyError
from decoy_engine.internal.cell_atoms import (
    AS,
    Duration,
    Instant,
    Months,
    decimal_exact,
    int_digits,
    is_null,
    is_wide,
    reduced,
    temporal_form,
    unboxed,
)

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


def detector_text(series: pd.Series) -> list[str | None]:
    """One text per row of `series`, None for a null, for the detectors to read. A cell reads as
    written, except that an integral number reads as its exact plain digits, so a PAN or phone
    kept as an int, float or `Decimal("4111111111111111.00")` stays visible."""
    return [None if is_null(c) else _detector_cell(c) for c in _cells(series)]


def _cells(series: pd.Series) -> list[object]:
    return list(_bytes_as_objects(series).astype(object))


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


# Detector formatting. A long integral value reads in an exact bounded form, so its size is
# bounded; an absurd exponent reads as a band name. No `int()` sees the exponent's digits.
_PLAIN_ZEROS = 32
_BAND = 10**19
_DETECTOR_DIGITS = 64  # longer than any detector pattern
_INT64 = (-(2**63), 2**63 - 1)


def _number_text(negative: bool, digits: str, exponent: int) -> str:
    """The finite number (-1)**negative * int(digits) * 10**exponent as exact text: plain when it
    needs at most `_PLAIN_ZEROS` padding zeros, else `<coefficient>E<exponent>`."""
    negative, coefficient, exponent = reduced(negative, digits, exponent)
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


def _fits(ticks: int) -> bool:
    """True when NumPy can hold `ticks` as a value. The lowest int64 is its NaT."""
    return _INT64[0] < ticks <= _INT64[1]


def temporal_text(form: Instant | Duration | Months) -> str:
    """The text of a NumPy date or duration: the pandas value it equals, or an exact NumPy or
    attosecond text when pandas cannot hold it. Never raises."""
    if isinstance(form, Months):
        return (
            f"{form.months} months"
            if not _fits(form.months)
            else str(np.timedelta64(form.months, "M"))
        )
    return _exact_text(form.attoseconds, isinstance(form, Instant))


def _exact_text(attoseconds: int, instant: bool) -> str:
    make_np: Any = np.datetime64 if instant else np.timedelta64
    make_pd = pd.Timestamp if instant else pd.Timedelta
    nanos, remainder = divmod(attoseconds, AS["ns"])
    if remainder == 0 and _fits(nanos):
        return str(pd.Timestamp(nanos) if instant else pd.Timedelta(nanos, unit="ns"))
    for unit in ("s", "ms", "us"):
        if attoseconds % AS[unit] == 0 and _fits(attoseconds // AS[unit]):
            try:
                return str(make_pd(make_np(attoseconds // AS[unit], unit)))
            except (OverflowError, ValueError):
                break
    for unit in ("ns", "ps", "fs", "as"):
        if attoseconds % AS[unit] == 0 and _fits(attoseconds // AS[unit]):
            return str(make_np(attoseconds // AS[unit], unit))
    # No unit holds it. The kind stays in the text so an instant never reads as a duration.
    return f"{attoseconds} attoseconds" + (" from the epoch" if instant else "")


def _plain_digits(negative: bool, digits: str, exponent: int) -> str:
    """An integral value as plain digits when that is short, else its exact key form."""
    negative, coefficient, exponent = reduced(negative, digits, exponent)
    if not coefficient:
        return "0"
    if len(coefficient) + exponent > _DETECTOR_DIGITS:
        return _number_text(negative, coefficient, exponent)
    return ("-" if negative else "") + coefficient + "0" * exponent


def _detector_cell(value: object) -> str:
    value = unboxed(value)
    if isinstance(value, (np.datetime64, np.timedelta64)):
        # The exact conversion identity uses; a bare count comes back as the number it equals.
        form = temporal_form(value)
        if not isinstance(form, int):
            return temporal_text(form)  # type: ignore[arg-type]
        value = form
    if isinstance(value, (bool, np.bool_)):
        return cell_text(value)
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return cell_text(value)
        if np.floor(value) == value:
            return _plain_digits(bool(value < 0), int_digits(value.as_integer_ratio()[0]), 0)
        return repr(float(str(value)) if is_wide(value) else float(value))
    if isinstance(value, (int, np.integer)):
        return _plain_digits(int(value) < 0, int_digits(int(value)), 0)
    if isinstance(value, Decimal) and value.is_finite():
        exact = decimal_exact(value)
        return _plain_digits(*exact) if _is_integral(exact) else cell_text(value)
    return cell_text(value)


def _is_integral(exact: tuple[bool, str, int]) -> bool:
    _, coefficient, exponent = reduced(*exact)
    return not coefficient or exponent >= 0


# Export spellings: a cell as Python, NumPy or `json.dumps(default=str)` write it, rendered
# from digits so neither the int-to-str limit nor the decimal context changes the text.
def holds_decimal(value: object) -> bool:
    value = unboxed(value)
    if isinstance(value, Decimal):
        return True
    if isinstance(value, dict):
        return any(holds_decimal(k) or holds_decimal(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)) or (
        isinstance(value, np.ndarray) and value.dtype == object
    ):
        return any(holds_decimal(v) for v in value)
    return False


def native_value(value: object) -> object:
    value = unboxed(value)
    if isinstance(value, np.ndarray):
        return list(value)
    if isinstance(value, np.generic) and not isinstance(value, np.void):
        return value.item()
    return value


def export_text(value: object, native: bool, as_repr: bool, capitals: int) -> str:
    """`str(value)` or `repr(value)` as Python writes it, with ints and Decimals rendered from
    their digits, so neither the int-to-str limit nor the decimal context changes the text.
    `native` reads NumPy leaves and arrays as their Python values (`item`, `tolist`)."""
    value = native_value(value) if native else unboxed(value)

    def inner(v: object) -> str:
        return export_text(v, native, True, capitals)

    kind = type(value)
    if kind is list:
        return "[" + ", ".join(map(inner, value)) + "]"  # type: ignore[call-overload]
    if kind is tuple:
        items = list(map(inner, value))  # type: ignore[call-overload]
        return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        fields = ", ".join(f"{f}={inner(v)}" for f, v in zip(value._fields, value, strict=True))
        return f"{kind.__name__}({fields})"
    if kind is dict:
        pairs = (f"{inner(k)}: {inner(v)}" for k, v in value.items())  # type: ignore[attr-defined]
        return "{" + ", ".join(pairs) + "}"
    if kind in (set, frozenset):
        body = "{" + ", ".join(map(inner, value)) + "}" if value else "()"  # type: ignore[call-overload]
        if kind is set:
            return body if value else "set()"
        return f"frozenset({body})" if value else "frozenset()"
    if kind is bool:
        return repr(value)
    if kind is int:
        return ("-" if value < 0 else "") + int_digits(value)  # type: ignore[operator, arg-type]
    if kind is Decimal:
        text = decimal_text(value, capitals)  # type: ignore[arg-type]
        return f"Decimal('{text}')" if as_repr else text
    if kind is str:
        return repr(value) if as_repr else value  # type: ignore[return-value]
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        # A subclass (OrderedDict, Counter) keeps its own text; its ints are not re-rendered.
        return repr(value)
    return repr(value) if as_repr else str(value)


def decimal_text(value: Decimal, capitals: int) -> str:
    """`str(value)` under a context with this `capitals`, built from the digits (the
    to-sci-string rule of the General Decimal Arithmetic spec, as `_pydecimal` writes it)."""
    sign, digits, exponent = value.as_tuple()
    prefix = "-" if sign else ""
    coefficient = "".join(map(str, digits))
    if exponent == "F":
        return prefix + "Infinity"
    if exponent in ("n", "N"):
        payload = coefficient.lstrip("0")
        return prefix + ("NaN" if exponent == "n" else "sNaN") + payload
    exponent = int(exponent)  # finite: an int exponent
    left = exponent + len(coefficient)
    dot = left if exponent <= 0 and left > -6 else 1
    if dot <= 0:
        whole, part = "0", "." + "0" * -dot + coefficient
    elif dot >= len(coefficient):
        whole, part = coefficient + "0" * (dot - len(coefficient)), ""
    else:
        whole, part = coefficient[:dot], "." + coefficient[dot:]
    shown = "" if left == dot else "eE"[capitals] + f"{left - dot:+d}"
    return prefix + whole + part + shown


def export_json(value: object, sort: bool, capitals: int) -> str:
    """`json.dumps(native(value), default=str)` (or with `sort_keys`), rendered from digits."""
    value = native_value(value)
    if value is None or isinstance(value, bool):
        return {None: "null", True: "true", False: "false"}[value]
    if type(value) is int:
        return export_text(value, True, False, capitals)
    if type(value) is float:
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(export_json(v, sort, capitals) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0]) if sort else list(value.items())
        return (
            "{"
            + ", ".join(
                f"{_json_key(native_value(k))}: {export_json(v, sort, capitals)}" for k, v in items
            )
            + "}"
        )
    if isinstance(value, Decimal):
        return json.dumps(decimal_text(value, capitals))
    # `default=str`: the cell's own text as a JSON string.
    return json.dumps(export_text(value, True, False, capitals))


def _json_key(key: object) -> str:
    if isinstance(key, str):
        return json.dumps(key)
    if key is None or isinstance(key, (bool, int, float)):
        return json.dumps(export_json(key, False, 1))
    raise ValueError("a JSON key of this type has no spelling")


def safe_text(render: Callable[[], str]) -> Iterator[str]:
    try:
        text = render()
    except Exception:
        # A spelling that cannot be built is not a spelling of this cell; the next is tried.
        return
    yield text


def temporal_spellings(x: object, form: object) -> Iterator[str]:
    native = x.item() if isinstance(x, np.generic) else x
    renders: list[Callable[[], str]] = [lambda: native.isoformat()]  # type: ignore[union-attr]
    if isinstance(form, Instant):
        renders += [
            lambda: str(pd.Timestamp(x)),
            lambda: pd.Timestamp(x).isoformat(),
            lambda: str(np.datetime64(x)),  # type: ignore[call-overload]
        ]
    elif isinstance(form, Duration):
        renders += [
            lambda: str(pd.Timedelta(x)),
            lambda: pd.Timedelta(x).isoformat(),
            lambda: str(np.timedelta64(x)),  # type: ignore[call-overload]
        ]
    elif isinstance(form, Months):
        renders.append(lambda: str(np.timedelta64(x)))  # type: ignore[call-overload]
    for render in renders:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield from safe_text(render)
