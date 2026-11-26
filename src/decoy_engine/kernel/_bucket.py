"""Arrow kernels for `bucketize` and `top_code`.

An integer-width bucket label is built from a float64 quotient, so a source value is only
representable when its magnitude stays below ``EXACT_INT_BOUND`` (2**53) and is finite.
``integer_width_exit_mask`` is the one rule for that; the handler and the array operator both
ask it, and neither keeps a copy.

``bucketize_array`` and ``top_code_array`` are the vector forms of the two pandas handlers. They
take resolved settings (a width, a cap, two labels), never derive a bound from the data, and
return string labels plus the facts the caller needs (positions that cannot be labelled, the two
warning counts). The float arithmetic mirrors NumPy's ``floor(x / w) * w`` bit for bit, and float
labels use Python's ``str(float)``, which is what ``Series.astype(str)`` prints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError
from decoy_engine.contracts.bucketize_width import (
    BUCKETIZE_FORMATS,
    EXACT_INT_BOUND,
    is_oversized_integer,
)
from decoy_engine.contracts.label_text import is_utf8_text
from decoy_engine.kernel._scalar import passthrough_array

_BOUND = float(EXACT_INT_BOUND)  # 2**53 is exact in float64


def integer_width_exit_mask(values: pa.Array | pa.ChunkedArray) -> pa.Array:
    """Positions that cannot take an integer-width label, as a boolean array without nulls.

    B2: a finite value whose magnitude is at least ``EXACT_INT_BOUND``. B3: positive or negative
    infinity. An Arrow null and a valid NaN are never an exit: their predicates are false, so
    callers keep their own missingness rules.
    """
    # pyarrow ships no stubs for the compute functions it builds at import time.
    is_finite = pc.is_finite(values)  # type: ignore[attr-defined, unused-ignore]
    magnitude = pc.abs(values)  # type: ignore[attr-defined, unused-ignore]
    at_bound = pc.greater_equal(magnitude, _BOUND)  # type: ignore[attr-defined, unused-ignore]
    out_of_range = pc.and_(is_finite, at_bound)  # type: ignore[attr-defined, unused-ignore]
    infinite = pc.is_inf(values)  # type: ignore[attr-defined, unused-ignore]
    either = pc.or_(out_of_range, infinite)  # type: ignore[attr-defined, unused-ignore]
    mask = pc.fill_null(either, False)
    if isinstance(mask, pa.ChunkedArray):
        return mask.combine_chunks()
    return mask


_INT64_LOW = -(2.0**63)  # exact in float64
_INT64_HIGH = 2.0**63  # exclusive upper limit of the signed 64-bit cast range


@dataclass(frozen=True)
class SparseLabels:
    """Labels for positions that hold a valid NaN in a float source.

    By default a valid NaN is missing, like an Arrow null. A pandas extension dtype can treat it
    as a present value, and the oracle then prints it; the caller renders those few positions
    with the handler's own code and hands the strings here. ``positions`` are strictly ascending
    row numbers, each of which must be a valid NaN in the source.
    """

    positions: pa.Array
    labels: pa.Array


@dataclass(frozen=True)
class BucketizeResult:
    """String labels (null where missing or exited) and the exited row numbers, ascending."""

    labels: pa.Array
    exit_positions: pa.Array


@dataclass(frozen=True)
class TopCodeResult:
    """String labels (null where missing) and how many rows went over the cap or under the floor."""

    labels: pa.Array
    over_count: int
    under_count: int


def _numeric_domain(values: pa.Array) -> bool:
    """The array types the operators admit: int8..int64, uint8..uint32 and float64."""
    t = values.type
    if pa.types.is_floating(t):
        return t == pa.float64()
    return bool(pa.types.is_integer(t)) and t != pa.uint64()


def _require_numeric(values: pa.Array, operator: str) -> None:
    if not _numeric_domain(values):
        raise TypeError(f"{operator} does not take this array type")


def _as_float64(values: pa.Array) -> pa.Array:
    """Float64 view of the source; integers round to nearest, as pandas and NumPy do."""
    if values.type == pa.float64():
        return values
    return pc.cast(values, pa.float64(), safe=False)


def _present(f: pa.Array) -> pa.Array:
    """Valid and not NaN: the rows a label is built for by default."""
    not_nan = pc.invert(pc.fill_null(pc.is_nan(f), False))  # type: ignore[attr-defined, unused-ignore]
    return pc.and_(pc.is_valid(f), not_nan)  # type: ignore[attr-defined, unused-ignore]


def _scatter(n: int, mask: pa.Array, labels: pa.Array) -> pa.Array:
    """A length-``n`` string array: ``labels`` in order at the true positions, null elsewhere."""
    return pc.replace_with_mask(pa.nulls(n, pa.string()), mask, labels)  # type: ignore[attr-defined, unused-ignore, no-any-return]


def _positions(mask: pa.Array) -> pa.Array:
    return pc.indices_nonzero(mask)  # type: ignore[attr-defined, unused-ignore, no-any-return]


def _apply_exceptional(
    values: pa.Array, labels: pa.Array, exceptional: SparseLabels | None
) -> pa.Array:
    if exceptional is None:
        return labels
    n = len(values)
    pos = np.asarray(exceptional.positions.to_numpy(zero_copy_only=False), dtype=np.int64)
    if len(pos) != len(exceptional.labels):
        raise ValueError("exceptional positions and labels differ in length")
    if len(pos) == 0:
        return labels
    ordered = bool(np.all(pos[1:] > pos[:-1])) and pos[0] >= 0 and pos[-1] < n
    if not ordered:
        raise ValueError("exceptional positions must be ascending, unique and in range")
    nan_valid = pc.and_(pc.is_valid(values), pc.fill_null(pc.is_nan(values), False))  # type: ignore[attr-defined, unused-ignore]
    if not bool(np.all(nan_valid.take(exceptional.positions).to_numpy(zero_copy_only=False))):
        raise ValueError("exceptional positions must be valid NaN values")
    mask = np.zeros(n, dtype=bool)
    mask[pos] = True
    return pc.replace_with_mask(labels, pa.array(mask), exceptional.labels)  # type: ignore[attr-defined, unused-ignore, no-any-return]


def python_float_str(values: pa.Array | pa.ChunkedArray) -> pa.Array:
    """Python ``str(float)`` for every present float; Arrow null stays null.

    This is the notation ``Series.astype(str)`` prints (``1e+16``, ``1e-05``, ``-0.0``, ``inf``,
    ``nan``). Arrow's own float-to-string cast prints differently, so it is not used.
    """
    array = passthrough_array(values)
    valid = array.is_valid().to_numpy(zero_copy_only=False)
    floats = np.asarray(array.fill_null(0.0).to_numpy(zero_copy_only=False), dtype=np.float64)
    strings = [
        str(v) if ok else None for v, ok in zip(floats.tolist(), valid.tolist(), strict=True)
    ]
    return pa.array(strings, pa.string())


def floor_multiple(values: pa.Array | pa.ChunkedArray, width: int | float) -> pa.Array:
    """``floor(x / width) * width`` in float64: the bucket start, bit-equal to NumPy's."""
    w = pa.scalar(float(width), pa.float64())
    quotient = pc.divide(_as_float64(passthrough_array(values)), w)  # type: ignore[attr-defined, unused-ignore]
    return pc.multiply(pc.floor(quotient), w)  # type: ignore[attr-defined, unused-ignore, no-any-return]


def _decimal(floats: pa.Array) -> pa.Array:
    """Decimal text of integral floats below 2**54 in magnitude (the safe cast cannot fail)."""
    return pc.cast(pc.cast(floats, pa.int64(), safe=True), pa.string())


def _range_upper(lower: pa.Array, width: int) -> pa.Array:
    """Last integer of each bucket. A checked add: the one integer sum that could silently wrap."""
    return pc.add_checked(lower, pa.scalar(width - 1, pa.int64()))  # type: ignore[attr-defined, unused-ignore, no-any-return]


def _integer_width_labels(lf: pa.Array, width: int, fmt: str) -> pa.Array:
    lower = pc.cast(lf, pa.int64(), safe=True)
    if fmt == "lower":
        return pc.cast(lower, pa.string())
    if fmt == "range":
        upper = _range_upper(lower, width)
        return pc.binary_join_element_wise(  # type: ignore[attr-defined, unused-ignore, no-any-return]
            pc.cast(lower, pa.string()), pc.cast(upper, pa.string()), "-"
        )
    mid = pc.add(lf, pa.scalar(width / 2, pa.float64()))  # type: ignore[attr-defined, unused-ignore]
    return _decimal(mid) if width % 2 == 0 else python_float_str(mid)


def _float_width_labels(lf: pa.Array, width: float, fmt: str) -> pa.Array:
    if fmt == "lower":
        return python_float_str(lf)
    if fmt == "range":
        upper = pc.add(lf, pa.scalar(width, pa.float64()))  # type: ignore[attr-defined, unused-ignore]
        return pc.binary_join_element_wise(python_float_str(lf), python_float_str(upper), "-")  # type: ignore[attr-defined, unused-ignore, no-any-return]
    return python_float_str(pc.add(lf, pa.scalar(width / 2, pa.float64())))  # type: ignore[attr-defined, unused-ignore]


def bucketize_array(
    values: pa.Array | pa.ChunkedArray,
    width: int | float,
    fmt: str,
    *,
    exceptional: SparseLabels | None = None,
) -> BucketizeResult:
    """Bucket labels for a numeric array, equal to the pandas handler's output.

    ``width`` is the resolved width: a Python int gives integer labels, a float gives float
    labels, whatever the source type. Under an integer width a value that is infinite or at least
    2**53 in magnitude cannot take a label; its label is null and its row is in ``exit_positions``.
    A float width never exits. Null and NaN rows are null unless ``exceptional`` supplies a label.
    """
    array = passthrough_array(values)
    _require_numeric(array, "bucketize")
    if fmt not in BUCKETIZE_FORMATS:
        raise ValueError("bucketize format is not one of lower, range, midpoint")
    is_int_width = isinstance(width, int) and not isinstance(width, bool)
    if is_oversized_integer(width):
        raise ValueError("an integer bucketize width must be below the exact integer bound")
    f = _as_float64(array)
    present = _present(f)
    if is_int_width:
        exit_mask = pc.and_(present, integer_width_exit_mask(f))  # type: ignore[attr-defined, unused-ignore]
        usable = pc.and_(present, pc.invert(exit_mask))  # type: ignore[attr-defined, unused-ignore]
    else:
        exit_mask = pa.array(np.zeros(len(f), dtype=bool))
        usable = present
    lf = floor_multiple(f.filter(usable), width)  # excluded rows never reach a cast
    labels = (
        _integer_width_labels(lf, int(width), fmt)
        if is_int_width
        else _float_width_labels(lf, float(width), fmt)
    )
    out = _apply_exceptional(f, _scatter(len(f), usable, labels), exceptional)
    return BucketizeResult(out, _positions(exit_mask).cast(pa.int64()))


def _compare_view(values: pa.Array, cap: int | float, floor: int | float | None) -> pa.Array:
    """Exact int64 when the source and both bounds are integers, else float64."""
    integer_bounds = isinstance(cap, int) and (floor is None or isinstance(floor, int))
    if pa.types.is_integer(values.type) and integer_bounds:
        return pc.cast(values, pa.int64(), safe=True)
    return _as_float64(values)


def _bound(view: pa.Array, bound: int | float) -> pa.Scalar[Any]:
    return pa.scalar(bound, view.type) if view.type == pa.int64() else pa.scalar(float(bound))


def _in_range_labels(rows: pa.Array) -> pa.Array:
    """Text of the in-range rows, as the oracle renders them (no ``.0`` on an integral value)."""
    if pa.types.is_integer(rows.type):
        return pc.cast(rows, pa.string())
    n = len(rows)
    finite = pc.is_finite(rows)  # type: ignore[attr-defined, unused-ignore]
    integral = pc.and_(finite, pc.equal(pc.floor(rows), rows))  # type: ignore[attr-defined, unused-ignore]
    fits = pc.and_(  # type: ignore[attr-defined, unused-ignore]
        integral,
        pc.and_(pc.greater_equal(rows, _INT64_LOW), pc.less(rows, _INT64_HIGH)),  # type: ignore[attr-defined, unused-ignore]
    )
    wide = pc.and_(integral, pc.invert(fits))  # type: ignore[attr-defined, unused-ignore]
    other = pc.invert(integral)  # type: ignore[attr-defined, unused-ignore]
    out = _scatter(n, fits, _decimal(rows.filter(fits)))
    if wide.true_count:
        exact = [str(int(v)) for v in rows.filter(wide).to_pylist()]
        out = pc.replace_with_mask(out, wide, pa.array(exact, pa.string()))  # type: ignore[attr-defined, unused-ignore]
    if other.true_count:
        out = pc.replace_with_mask(out, other, python_float_str(rows.filter(other)))  # type: ignore[attr-defined, unused-ignore]
    return out


def top_code_array(
    values: pa.Array | pa.ChunkedArray,
    cap: int | float,
    over_label: str,
    floor: int | float | None = None,
    under_label: str | None = None,
    *,
    exceptional: SparseLabels | None = None,
) -> TopCodeResult:
    """Top-coded labels for a numeric array, equal to the pandas handler's output.

    A value above ``cap`` becomes ``over_label``. With both ``floor`` and ``under_label`` set, a
    value below ``floor`` becomes ``under_label``. Every other value prints as the oracle prints
    it: an integral value without ``.0``. Null and NaN rows are null unless ``exceptional``
    supplies a label. The counts are the over and under rows, for the warning.
    """
    if not is_utf8_text(over_label) or (under_label is not None and not is_utf8_text(under_label)):
        raise ExecutionError(
            code=reasons.runtime.TOP_CODE_BOUNDS_UNRESOLVABLE,
            message="top_code labels must be text that encodes as UTF-8.",
        )
    array = passthrough_array(values)
    _require_numeric(array, "top_code")
    do_under = floor is not None and under_label is not None
    view = _compare_view(array, cap, floor if do_under else None)
    present = _present(_as_float64(array))
    over = pc.and_(present, pc.fill_null(pc.greater(view, _bound(view, cap)), False))  # type: ignore[attr-defined, unused-ignore]
    if do_under and floor is not None and under_label is not None:
        below = pc.fill_null(pc.less(view, _bound(view, floor)), False)  # type: ignore[attr-defined, unused-ignore]
        under = pc.and_(present, below)  # type: ignore[attr-defined, unused-ignore]
    else:
        under = pa.array(np.zeros(len(view), dtype=bool))
    in_range = pc.and_(present, pc.invert(pc.or_(over, under)))  # type: ignore[attr-defined, unused-ignore]
    # Compare on the view, but print from the source: a float64 view rounds an integer past 2**53.
    text_source = array if pa.types.is_integer(array.type) else view
    out = _scatter(len(view), in_range, _in_range_labels(text_source.filter(in_range)))
    out = pc.if_else(over, pa.scalar(over_label), out)  # type: ignore[attr-defined, unused-ignore]
    if do_under and under_label is not None:
        out = pc.if_else(under, pa.scalar(under_label), out)  # type: ignore[attr-defined, unused-ignore]
    out = _apply_exceptional(_as_float64(array), out, exceptional)
    return TopCodeResult(out, over.true_count, under.true_count)
