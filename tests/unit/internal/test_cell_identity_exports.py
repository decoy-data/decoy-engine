"""PM-1 S1b: export spellings (K4 answer A), exact numbers and property rows for the authority.

Text matches a non-text cell only when it is a listed export spelling of that cell: `str` or
`repr` of the original or native value, a plain numeral of the same value, temporal text, or
default and sorted JSON. Text against text and bytes against bytes compare as written. Plan:
docs/plans/2026-11-27-pm1-comparison-redesign.md (K4, number keys, R2-V4, R2-V5, P1 to P3).
Synthetic values only; no assertion message carries a cell value.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Iterator
from decimal import Decimal, FloatOperation, Inexact, Rounded, localcontext
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.internal.cell_identity import (
    CellNotComparableError,
    distinct_values,
    identity_facts,
)
from decoy_engine.internal.cell_text import UnreadableCellError


def _col(*cells: object) -> pd.Series:
    arr = np.empty(len(cells), dtype=object)
    for i, cell in enumerate(cells):
        arr[i] = cell
    # dtype=object: pandas would otherwise infer a temporal dtype and convert the cells.
    return pd.Series(arr, dtype=object)


def _verdict(a: object, b: object) -> str:
    facts = identity_facts(_col(a), _col(b))
    if facts.comparable == 0:
        return "both null" if facts.all_same else "one null"
    return "same" if facts.identical == 1 else "different"


def _both(a: object, b: object) -> str:
    forward, back = _verdict(a, b), _verdict(b, a)
    assert forward == back
    return forward


@contextlib.contextmanager
def _int_limit(digits: int) -> Iterator[None]:
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(digits)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(old)


@contextlib.contextmanager
def _trapping() -> Iterator[None]:
    with localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin = 1, 9, -9
        ctx.traps[FloatOperation] = ctx.traps[Inexact] = ctx.traps[Rounded] = True
        yield


@contextlib.contextmanager
def _capitals(flag: int) -> Iterator[None]:
    with localcontext() as ctx:
        ctx.capitals = flag
        yield


SETTINGS = {
    "default": contextlib.nullcontext,
    "int limit 640": lambda: _int_limit(640),
    "int limit 4300": lambda: _int_limit(4300),
    "int limit off": lambda: _int_limit(0),
    "capitals 0": lambda: _capitals(0),
    "trapping": _trapping,
}

# ---------------------------------------------------------------- number spellings

SAME_EXPORTS = [
    ("F2 short", 0.1, "0.1"),
    ("F2 dot17e", 0.1, "1.00000000000000006e-01"),
    ("F2 exact expansion", 0.1, str(Decimal(0.1))),  # noqa: RUF032
    ("F2 exponent", 1e23, "1e+23"),
    ("F2 wide str", np.longdouble("35.001417"), str(np.longdouble("35.001417"))),
    ("N-2 true as one", True, "1"),
    ("N-2 true as name", True, "True"),
    ("decimal exact text", Decimal("7351.25"), "7351.25"),
    ("decimal trailing zero", Decimal("2.5"), "2.50"),
    ("decimal scientific", Decimal("2.5"), "25e-1"),
    ("big int digits", 10**30, "1" + "0" * 30),
    ("infinity", float("inf"), "inf"),
    ("negative infinity", Decimal("-Infinity"), "-Infinity"),
]


@pytest.mark.parametrize(
    ("a", "b"), [r[1:] for r in SAME_EXPORTS], ids=[r[0] for r in SAME_EXPORTS]
)
def test_a_listed_export_spelling_is_the_same_value(a: object, b: object) -> None:
    assert _both(a, b) == "same"


DIFFERENT_EXPORTS = [
    ("N-1 decimal vs float", Decimal("0.1"), 0.1),
    ("N-1 past 2**53", 2**53 + 1, float(2**53)),
    ("leading zero", 2134, "02134"),
    ("plus sign", 1, "+1"),
    ("one digit off", Decimal("7351.25"), "7351.26"),
    ("R2-V4c compact json", [1, 2], "[1,2]"),
    ("text vs text as written", "1.0", "1.00"),
    ("bytes vs bytes as written", b"1.0", b"1.00"),
]


@pytest.mark.parametrize(
    ("a", "b"), [r[1:] for r in DIFFERENT_EXPORTS], ids=[r[0] for r in DIFFERENT_EXPORTS]
)
def test_an_unlisted_spelling_is_a_different_value(a: object, b: object) -> None:
    assert _both(a, b) == "different"


@pytest.mark.parametrize("setting", list(SETTINGS))
def test_f3_a_padded_exponent_has_one_verdict_under_every_setting(setting: str) -> None:
    with SETTINGS[setting]():
        assert _both(10, "1e" + "0" * 640 + "1") == "different"
        assert _both(10, "1e1") == "same"


def test_f3b_an_absurd_exponent_differs_and_raises_nothing() -> None:
    with _int_limit(640):
        assert _both(10**700, "10e" + "9" * 640) == "different"
        assert _both(10**700, "1e" + "9" * 100_000) == "different"


def test_r4_verdicts_do_not_depend_on_the_decimal_context() -> None:
    pairs = [(Decimal("1.5"), "1.5"), (0.1, "0.1"), (1e-07, "1e-07"), (Decimal("1E4500"), 10**4500)]
    plain = [_both(a, b) for a, b in pairs]
    with _trapping():
        assert [_both(a, b) for a, b in pairs] == plain == ["same"] * 4


@pytest.mark.parametrize("setting", list(SETTINGS))
def test_r2_v5a_a_huge_int_and_its_digits_under_every_setting(setting: str) -> None:
    big, text = 10**700, "1" + "0" * 700
    with SETTINGS[setting]():
        assert _both(big, text) == "same"
        assert _both(-big, "-" + text) == "same"
        assert _both(big, "1" + "0" * 699 + "1") == "different"
        assert _both([big], f"[{text}]") == "same"
        assert _both({"k": big}, json.dumps({"k": 0}).replace("0", text)) == "same"


@pytest.mark.parametrize("setting", list(SETTINGS))
def test_r2_v5b_decimal_repr_in_a_list_under_every_setting(setting: str) -> None:
    with SETTINGS[setting]():
        assert _both([Decimal("1E+8")], "[Decimal('1E+8')]") == "same"
        assert _both([Decimal("1E+8")], "[Decimal('1e+8')]") == "same"
        assert _both(Decimal("1E+8"), "Decimal('1E+8')") == "same"


@pytest.mark.parametrize("setting", list(SETTINGS))
def test_r2_v5c_a_dict_with_huge_numbers_and_its_json(setting: str) -> None:
    cell = {"n": 10**400, "d": Decimal("1.25")}
    with SETTINGS[setting]():
        # `json.dumps(cell, default=str)`: the Decimal is written as a JSON string.
        assert _both(cell, '{"n": ' + "1" + "0" * 400 + ', "d": "1.25"}') == "same"


# ---------------------------------------------------------------- container and temporal exports


def test_r2_v4a_str_repr_and_json_exports_of_containers() -> None:
    cell = {"b": 1, "a": [1, 2]}
    assert _both(cell, str(cell)) == "same"
    assert _both(cell, json.dumps(cell)) == "same"
    assert _both(cell, json.dumps(cell, sort_keys=True)) == "same"
    assert _both((1, "x"), repr((1, "x"))) == "same"
    assert _both([np.float64(0.1)], "[0.1]") == "same"
    assert _both([np.complex64(complex("nan+0j"))], "[(nan+0j)]") == "same"  # PC1-3


def test_r2_v4b_bytes_and_temporal_exports() -> None:
    assert _both(Decimal("1.5"), b"Decimal('1.5')") == "same"
    stamp = pd.Timestamp("2020-01-01 05:00")
    assert _both(stamp, str(stamp)) == "same"
    assert _both(stamp, stamp.isoformat()) == "same"
    assert _both(np.datetime64("2020-01-01T05:00"), "2020-01-01T05:00") == "same"
    with pytest.raises(UnreadableCellError):
        _verdict(Decimal("1.5"), b"\xff1.5")


def test_r2_v4c_null_name_and_record_text() -> None:
    assert _both(None, "None") == "one null"
    record = np.zeros(1, dtype=[("a", "i4")])[0]
    with pytest.raises(CellNotComparableError):
        _verdict(record, str(record))


def test_r6_an_aware_instant_and_its_text_are_the_same() -> None:
    a = pd.Timestamp("2020-01-01", tz="UTC")
    b = a.tz_convert("America/New_York")
    facts = identity_facts(_col(a, b, a, b), _col(str(a), b, str(a), b))
    assert (facts.comparable, facts.identical, facts.all_same) == (4, 4, True)


def test_r5_a_bytearray_cell_is_counted() -> None:
    assert distinct_values(_col(bytearray(b"ab"), 2)) == 2


def test_d1_text_spellings_count_as_written() -> None:
    assert distinct_values(_col("1.0", "1.00", "x")) == 3


# ---------------------------------------------------------------- A-K1: every NumPy typecode


def _kinds() -> list[tuple[str, object]]:
    cells: list[tuple[str, object]] = []
    for code in np.typecodes["All"]:
        if code in "VO":
            continue
        try:
            dtype = np.dtype(code)
            value = (
                np.ones(1, dtype=dtype)[0]
                if dtype.kind not in "Mm"
                else np.zeros(1, f"{code}8[s]")[0]
            )
        except (TypeError, ValueError):
            continue
        cells.append((code, value))
    return cells


@pytest.mark.parametrize(("code", "cell"), _kinds(), ids=[c for c, _ in _kinds()])
@pytest.mark.parametrize("shape", ["top", "list", "tuple", "dict", "box", "array"])
def test_a_k1_every_typecode_is_itself_in_every_shape(code: str, cell: object, shape: str) -> None:
    box = np.empty((), dtype=object)
    box[()] = cell
    wrapped = {
        "top": cell,
        "list": [cell],
        "tuple": (cell,),
        "dict": {"k": cell},
        "box": box,
        "array": np.array([cell]),
    }[shape]
    assert _verdict(wrapped, wrapped) == "same"
    assert distinct_values(_col(wrapped, wrapped)) == 1


# ---------------------------------------------------------------- property rows (fixed seed)

LEAVES = st.one_of(
    st.integers(-(2**70), 2**70),
    st.floats(allow_nan=False),
    st.text(max_size=5),
    st.booleans(),
    st.decimals(allow_nan=False, allow_infinity=False, places=3),
    st.none(),
)
CELLS = st.recursive(
    LEAVES,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.tuples(inner, inner),
        st.dictionaries(st.text(max_size=3), inner, max_size=3),
    ),
    max_leaves=6,
)


def _transform(cell: Any, how: int) -> Any:
    """A form change that keeps the value: a box, a list as tuple, reversed dict order."""
    if how == 0:
        box = np.empty((), dtype=object)
        box[()] = cell
        return box
    if how == 1 and isinstance(cell, list):
        return tuple(_transform(c, how) for c in cell)
    if how == 2 and isinstance(cell, dict):
        return dict(reversed([(k, _transform(v, how)) for k, v in cell.items()]))
    return cell


def test_p1_identity_is_reflexive_and_symmetric_with_a_floor_of_same_pairs() -> None:
    seen = [0, 0]

    @settings(derandomize=True, max_examples=300, deadline=None)
    @given(a=CELLS, other=CELLS, derived=st.booleans(), how=st.integers(0, 2))
    def check(a: Any, other: Any, derived: bool, how: int) -> None:
        b = _transform(a, how) if derived else other
        assert _verdict(a, a) in ("same", "both null")
        forward = _verdict(a, b)
        assert forward == _verdict(b, a)
        if derived:
            assert forward in ("same", "both null")
        seen[0] += forward == "same"
        seen[1] += 1

    check()
    assert seen[1] >= 300
    assert seen[0] >= seen[1] // 4


@settings(derandomize=True, max_examples=300, deadline=None)
@given(f=st.floats(allow_nan=False, allow_infinity=False))
def test_p2_every_export_of_a_binary64_is_the_float(f: float) -> None:
    for text in (repr(f), str(f), f"{f:.17e}", str(Decimal(f))):
        assert _both(f, text) == "same"


FAST = {
    "int64": (st.integers(-(2**63), 2**63 - 1), pa.int64()),
    "float64": (st.floats(allow_nan=True), pa.float64()),
    "bool": (st.booleans(), pa.bool_()),
    "string": (st.text(max_size=4), pa.string()),
    "timestamp us": (st.integers(-(2**50), 2**50), pa.timestamp("us")),
    "duration ns": (st.integers(-(2**60), 2**60), pa.duration("ns")),
    # Days from 1970 within Python's `date` range (years 1 to 9999).
    "date32": (st.integers(-719162, 2932896), pa.date32()),
}


def _scalars(kind: str, array: pa.Array) -> pd.Series:
    # Through pandas where Python's own types would drop sub-microsecond ticks or keep NaN apart.
    pandas_kinds = {"float64", "timestamp us", "duration ns"}
    cells = array.to_pandas().tolist() if kind in pandas_kinds else array.to_pylist()
    return _col(*cells)


@pytest.mark.parametrize("kind", list(FAST))
def test_p3_the_fast_path_agrees_with_the_per_row_rule(kind: str) -> None:
    values, arrow = FAST[kind]
    cells = st.lists(st.one_of(st.none(), values), min_size=1, max_size=12)

    @settings(derandomize=True, max_examples=100, deadline=None)
    @given(src=cells, out=cells)
    def check(src: list[Any], out: list[Any]) -> None:
        size = min(len(src), len(out))
        typed_src = pa.array(src[:size], arrow)
        typed_out = pa.array(out[:size], arrow)
        fast = identity_facts(typed_src, typed_out)
        rows = identity_facts(_scalars(kind, typed_src), _scalars(kind, typed_out))
        assert fast == rows
        assert distinct_values(typed_src) == distinct_values(_scalars(kind, typed_src))

    check()
