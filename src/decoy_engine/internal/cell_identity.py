"""The one place that decides whether a source cell and an output cell are the same value.

Every post-mask reader (the batch facts, the frame runner, the standalone residual and policy
checks) asks `identity_facts` and `distinct_values`; none compares or counts cells on its own
(`tests/sentry/post_scan/test_cell_identity_choke_point.py`). The comparison runs on the cells
as the caller holds them, before any Arrow conversion of a frame, so a set keeps set semantics,
a nested unit stays exact and an absent struct field stays absent.

Per row (`_verdict`): unbox; refuse a NumPy record, a cycle or an unhashable unknown object at
any depth, on every cell, before any shortcut; then both null, one null, text against non-text
(SAME only for a listed export spelling, `_spelled`), and otherwise the value forms (`_form`)
matched recursively. Numbers compare at their exact value, so no binary64 rounding, decimal
context or int-to-str limit enters a verdict. Pattern: the typed comparator plus scalar
fallback of datacompy's `columns_equal`, with an exact scalar path in place of its mixed-type
"not equal".
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Hashable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from functools import partial
from typing import Any, TypeAlias

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine.internal.cell_atoms import (
    INFINITY,
    NUMERAL,
    TEMPORAL,
    CellNotComparableError,
    Exact,
    Instant,
    decimal_exact,
    float_exact,
    int_digits,
    is_wide,
    numeral_exact,
    reduced,
    temporal_form,
    unboxed,
)
from decoy_engine.internal.cell_text import (
    cell_text,
    export_json,
    export_text,
    holds_decimal,
    safe_text,
    temporal_spellings,
)
from decoy_engine.internal.pandas_missing import is_null_cell

__all__ = [
    "CellNotComparableError",
    "DistinctCounter",
    "IdentityFacts",
    "IdentityFailure",
    "distinct_values",
    "duckdb_countable",
    "identity_facts",
]

pc: Any = importlib.import_module("pyarrow.compute")
Column: TypeAlias = pd.Series | pa.Array | pa.ChunkedArray
_TEXT = (str, bytes, bytearray, memoryview)
_BOTH_NULL, _ONE_NULL, _SAME, _DIFFERENT = range(4)


@dataclass(frozen=True)
class IdentityFacts:
    """`comparable`: rows where both cells hold a value. `identical`: those that are the same
    value. `all_same`: every row is the same value or null on both sides."""

    comparable: int
    identical: int
    all_same: bool

    def merge(self, other: IdentityFacts) -> IdentityFacts:
        return IdentityFacts(
            self.comparable + other.comparable,
            self.identical + other.identical,
            self.all_same and other.all_same,
        )


@dataclass(frozen=True)
class IdentityFailure:
    """A column whose identity could not be decided: the failure's class name, never its text."""

    error: str


# Value forms. Each is hashable and compares with `==`, so a distinct count is a set of forms.
class _Null:
    __slots__ = ()

    def __repr__(self) -> str:
        return "NULL"


NULL = _Null()


@dataclass(frozen=True)
class _Real:
    exact: Exact


@dataclass(frozen=True)
class _Infinite:
    negative: bool


@dataclass(frozen=True)
class _Complex:
    real: object
    imag: object


@dataclass(frozen=True)
class _Seq:
    items: tuple[object, ...]


@dataclass(frozen=True)
class _Map:
    pairs: frozenset[tuple[object, object]]


@dataclass(frozen=True)
class _Members:
    items: frozenset[object]


class _ArrowMap:
    """An Arrow map cell read by its type: Arrow gives a map as a list of pairs."""

    __slots__ = ("pairs",)

    def __init__(self, pairs: list[tuple[object, object]]) -> None:
        self.pairs = pairs


_ZERO = _Real((False, "", 0))


def _int(value: int) -> _Real:
    if -(10**18) < value < 10**18:
        return _Real(reduced(value < 0, str(abs(value)), 0))
    return _Real(reduced(value < 0, int_digits(value), 0))


def _float(value: float | np.floating) -> object:
    # In the value's own width: `math.isinf` would read a finite wide float past 1e308 as inf.
    if np.isinf(value):
        return _Infinite(bool(value < 0))
    if value == 0:
        return _ZERO
    if not is_wide(value) and float(value).is_integer() and abs(float(value)) < 1e18:
        return _int(int(value))
    return _Real(reduced(*float_exact(value)))


def _fraction(value: Fraction) -> object:
    # A denominator of 2s and 5s is a finite decimal, so it meets the int, float and Decimal forms.
    rest, twos, fives = value.denominator, 0, 0
    while rest % 2 == 0:
        rest, twos = rest // 2, twos + 1
    while rest % 5 == 0:
        rest, fives = rest // 5, fives + 1
    if rest != 1:
        return value
    scale = max(twos, fives)
    digits = int_digits(abs(value.numerator) * (10**scale // value.denominator))
    return _Real(reduced(value.numerator < 0, digits, -scale))


def _complex(value: complex | np.complexfloating) -> object:
    real = _float(value.real)
    return real if value.imag == 0 else _Complex(real, _float(value.imag))


def _is_record(value: object) -> bool:
    return isinstance(value, (np.void, np.ndarray)) and value.dtype.names is not None


def _form(value: object, path: set[int]) -> object:
    """The value form of one cell, walked with `path` holding the containers above it."""
    value = unboxed(value)
    kind = type(value)
    if kind is str:
        return value
    if kind is int:
        return _int(value)  # type: ignore[arg-type]
    if kind is float:
        return NULL if value != value else _float(value)  # type: ignore[arg-type]
    if value is None or value is np.ma.masked:
        return NULL
    if _is_record(value):
        raise CellNotComparableError
    if isinstance(value, (list, tuple, dict, set, frozenset, np.ndarray, _ArrowMap)):
        if id(value) in path:
            raise CellNotComparableError
        path.add(id(value))
        try:
            return _container(value, path)
        finally:
            path.discard(id(value))
    if is_null_cell(value):
        return NULL
    return _leaf(value)


def _container(value: object, path: set[int]) -> object:
    if isinstance(value, (set, frozenset)):
        return _Members(frozenset(_form(v, path) for v in value))
    if isinstance(value, dict):
        return _mapping([(k, v) for k, v in value.items()], path)
    if isinstance(value, _ArrowMap):
        return _mapping(value.pairs, path)
    return _Seq(tuple(_form(v, path) for v in value))  # type: ignore[attr-defined]


def _mapping(pairs: list[tuple[object, object]], path: set[int]) -> _Map:
    formed = [(_form(k, path), _form(v, path)) for k, v in pairs]
    if len({k for k, _ in formed}) != len(formed):
        # Two keys with one value form: no pairing of the entries is the right one.
        raise CellNotComparableError
    return _Map(frozenset(formed))


def _leaf(value: object) -> object:
    # First: `np.timedelta64` is an `np.signedinteger`, and its int would drop the unit.
    temporal = temporal_form(value)
    if temporal is not None:
        return _int(temporal) if isinstance(temporal, int) else temporal
    if isinstance(value, (bool, np.bool_)):
        return _int(int(value))
    if isinstance(value, (int, np.integer)):
        return _int(int(value))
    if isinstance(value, (float, np.floating)):
        return _float(value)
    if isinstance(value, (complex, np.complexfloating)):
        return _complex(value)
    if isinstance(value, Decimal):
        return (
            _Infinite(value.is_signed())
            if value.is_infinite()
            else _Real(reduced(*decimal_exact(value)))
        )
    if isinstance(value, Fraction):
        return _fraction(value)
    if isinstance(value, np.void):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        return str.__str__(value)
    if not isinstance(value, Hashable):
        raise CellNotComparableError
    return value


def _top(value: object) -> tuple[object, object, bool]:
    """A cell's form, its unboxed value, and whether it is text (a str or top-level bytes)."""
    raw = unboxed(value)
    return _form(raw, set()), raw, isinstance(raw, _TEXT)


def _verdict(x: object, y: object) -> int:
    # Both cells are formed first, so a record or cycle on either side always refuses the column.
    fx, rx, tx = _top(x)
    fy, ry, ty = _top(y)
    if fx is NULL or fy is NULL:
        return _BOTH_NULL if fx is fy else _ONE_NULL
    if tx and ty:
        if not isinstance(rx, str) and not isinstance(ry, str):
            return _SAME if fx == fy else _DIFFERENT
        return _SAME if cell_text(rx) == cell_text(ry) else _DIFFERENT
    if tx or ty:
        text, other, form = (rx, ry, fy) if tx else (ry, rx, fx)
        spelling = cell_text(text)
        if _spelled(other, form, spelling):
            return _SAME
        # A kind with no form of its own keeps its own equality, against text too.
        return _SAME if form is other and bool(other == spelling) else _DIFFERENT
    return _SAME if _match(fx, fy) else _DIFFERENT


def _match(a: object, b: object) -> bool:
    """Exact form equality, plus the aware-against-naive rule at any instant leaf. That rule is
    not transitive, so an unordered collection is paired one to one (Kuhn's matching)."""
    if a == b:
        return True
    if isinstance(a, Instant) and isinstance(b, Instant):
        if a.aware == b.aware:
            return False
        aware, naive = (a, b) if a.aware else (b, a)
        return naive.attoseconds in (aware.attoseconds, aware.local)
    if isinstance(a, _Seq) and isinstance(b, _Seq):
        return len(a.items) == len(b.items) and all(map(_match, a.items, b.items))
    if isinstance(a, _Members) and isinstance(b, _Members):
        return _paired(list(a.items), list(b.items), _match)
    if isinstance(a, _Map) and isinstance(b, _Map):
        return _paired(
            list(a.pairs),
            list(b.pairs),
            lambda p, q: _match(p[0], q[0]) and _match(p[1], q[1]),  # type: ignore[index]
        )
    return False


def _paired(
    left: list[object], right: list[object], match: Callable[[object, object], bool]
) -> bool:
    if len(left) != len(right) or not (_has_instant(left) and _has_instant(right)):
        return False
    partner: dict[int, int] = {}

    def place(i: int, tried: set[int]) -> bool:
        for j, candidate in enumerate(right):
            if j not in tried and match(left[i], candidate):
                tried.add(j)
                if j not in partner or place(partner[j], tried):
                    partner[j] = i
                    return True
        return False

    return all(place(i, set()) for i in range(len(left)))


def _has_instant(forms: object) -> bool:
    if isinstance(forms, Instant):
        return True
    if isinstance(forms, (list, tuple, frozenset)):
        return any(_has_instant(f) for f in forms)
    if isinstance(forms, (_Seq, _Members)):
        return _has_instant(forms.items)
    if isinstance(forms, _Map):
        return _has_instant(forms.pairs)
    return False


# Export spellings (K4): a non-text cell `x` against text `t`. Each candidate is built lazily
# and only for such a row, so other rows pay nothing. An extra spelling only adds SAME rows.
def _spelled(x: object, form: object, text: str) -> bool:
    if isinstance(form, (_Real, _Infinite)) and _numeral(x, form, text):
        return True
    return any(candidate == text for candidate in _candidates(x, form))


def _numeral(x: object, form: object, text: str) -> bool:
    infinity = INFINITY.fullmatch(text)
    if infinity is not None:
        return isinstance(form, _Infinite) and form.negative == bool(infinity["sign"])
    if NUMERAL.fullmatch(text) is None:
        return False
    exact = numeral_exact(text)
    if exact is None:
        return False  # an exponent too long to match any finite number
    if isinstance(form, _Real) and exact == form.exact:
        return True
    if isinstance(x, (float, np.floating)) and not isinstance(x, bool):
        # Any text that rounds to the float: `float()` reads a numeral of any length exactly.
        if is_wide(x):
            return float(text) == float(str(x))
        return type(x)(text) == x if isinstance(x, np.floating) else float(text) == x
    return False


def _candidates(x: object, form: object) -> Iterator[str]:
    if isinstance(form, TEMPORAL):
        yield from temporal_spellings(x, form)
    capitals = (1, 0) if holds_decimal(x) else (1,)
    for native in (False, True):
        for as_repr in (False, True):
            for caps in capitals:
                yield from safe_text(partial(export_text, x, native, as_repr, caps))
    if isinstance(form, (_Seq, _Map, _Members)):
        for sort in (False, True):
            for caps in capitals:
                yield from safe_text(partial(export_json, x, sort, caps))


# Columns.
def _cells(column: Column) -> list[object]:
    if isinstance(column, (pa.Array, pa.ChunkedArray)):
        return _arrow_cells(column)
    if isinstance(column.dtype, pd.ArrowDtype):
        # By its Arrow type, so a map stays a map.
        return _arrow_cells(pa.array(column))
    if column.dtype == object:
        # The stored objects themselves: pandas boxes NumPy temporal scalars when it iterates.
        return list(column.to_numpy(copy=False))
    # Iterating the backing array keeps each cell's own type: a wide float stays wide and a
    # categorical reads as its values.
    return list(column.array)


def _arrow_cells(array: pa.Array | pa.ChunkedArray) -> list[object]:
    values = array.to_pylist()
    if not pa.types.is_nested(array.type):
        return values
    return [_from_arrow(v, array.type) for v in values]


def _from_arrow(value: object, kind: pa.DataType) -> object:
    if value is None:
        return None
    if pa.types.is_map(kind):
        return _ArrowMap(
            [(_from_arrow(k, kind.key_type), _from_arrow(v, kind.item_type)) for k, v in value]  # type: ignore[attr-defined]
        )
    if pa.types.is_list(kind) or pa.types.is_large_list(kind) or pa.types.is_fixed_size_list(kind):
        return [_from_arrow(v, kind.value_type) for v in value]  # type: ignore[attr-defined]
    if pa.types.is_struct(kind):
        return {f.name: _from_arrow(value[f.name], f.type) for f in kind}  # type: ignore[index]
    return value


_FAST = (
    pa.types.is_integer,
    pa.types.is_floating,
    pa.types.is_boolean,
    pa.types.is_string,
    pa.types.is_large_string,
    pa.types.is_timestamp,
    pa.types.is_duration,
    pa.types.is_date32,
)


def _typed(column: Column) -> pa.Array | None:
    """`column` as one Arrow array when its type has an exact typed comparator, else None."""
    if isinstance(column, pd.Series):
        dtype = column.dtype
        if isinstance(dtype, pd.CategoricalDtype):
            return None
        if isinstance(dtype, np.dtype) and (
            dtype.kind not in "biufmM" or (dtype.kind == "f" and dtype.itemsize > 8)
        ):
            return None
        try:
            column = pa.array(column, from_pandas=True)
        except (pa.ArrowException, TypeError, ValueError):
            return None
    if isinstance(column, pa.ChunkedArray):
        column = column.combine_chunks()
    return column if any(fast(column.type) for fast in _FAST) else None


_FINER = ("s", "ms", "us", "ns")


def _common(a: pa.Array, b: pa.Array) -> tuple[pa.Array, pa.Array] | None:
    """Both arrays in one type that keeps every value exact, or None to take the scalar path."""
    ta, tb = a.type, b.type
    try:
        if ta == tb:
            return a, b
        if pa.types.is_integer(ta) and pa.types.is_integer(tb):
            return pc.cast(a, pa.int64()), pc.cast(b, pa.int64())
        if pa.types.is_floating(ta) and pa.types.is_floating(tb):
            return pc.cast(a, pa.float64()), pc.cast(b, pa.float64())
        text = (pa.types.is_string, pa.types.is_large_string)
        if any(t(ta) for t in text) and any(t(tb) for t in text):
            return pc.cast(a, pa.large_string()), pc.cast(b, pa.large_string())
        for same in (pa.types.is_timestamp, pa.types.is_duration):
            if same(ta) and same(tb):
                if pa.types.is_timestamp(ta) and (ta.tz is None) != (tb.tz is None):
                    return None  # aware against naive: the scalar rule decides
                unit = max(ta.unit, tb.unit, key=_FINER.index)
                target = (
                    pa.timestamp(unit, ta.tz)
                    if same is pa.types.is_timestamp
                    else pa.duration(unit)
                )
                # A safe cast refuses a value its target unit cannot hold.
                return pc.cast(a, target, safe=True), pc.cast(b, target, safe=True)
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
        return None
    return None


def _valid(array: pa.Array) -> pa.Array:
    valid = pc.is_valid(array)
    if pa.types.is_floating(array.type):
        # A valid NaN is a null too, as pandas reads it.
        valid = pc.and_(valid, pc.invert(pc.fill_null(pc.is_nan(array), False)))
    return valid


def _typed_facts(a: pa.Array, b: pa.Array) -> IdentityFacts:
    va, vb = _valid(a), _valid(b)
    both = pc.and_(va, vb)
    equal = pc.fill_null(pc.and_(pc.equal(a, b), both), False)
    comparable = pc.sum(both).as_py() or 0
    identical = pc.sum(equal).as_py() or 0
    nulls_agree = pc.all(pc.equal(va, vb)).as_py() is not False
    return IdentityFacts(comparable, identical, identical == comparable and nulls_agree)


def identity_facts(src: Column, out: Column) -> IdentityFacts:
    """The identity facts of two equal-length columns compared by position.

    Raises `CellNotComparableError` for a record, cycle or unhashable cell on either side,
    `UnreadableCellError` for text bytes that are not UTF-8; both have fixed text."""
    if len(src) != len(out):
        raise ValueError("identity_facts: the columns differ in length")
    typed_a, typed_b = _typed(src), _typed(out)
    if typed_a is not None and typed_b is not None:
        common = _common(typed_a, typed_b)
        if common is not None:
            return _typed_facts(*common)
    comparable = identical = 0
    all_same = True
    for x, y in zip(_cells(src), _cells(out), strict=True):
        verdict = _verdict(x, y)
        comparable += verdict >= _SAME
        identical += verdict == _SAME
        all_same = all_same and verdict in (_BOTH_NULL, _SAME)
    return IdentityFacts(comparable, identical, all_same)


def _forms(column: Column) -> Iterator[object]:
    for cell in _cells(column):
        form = _form(cell, set())
        if form is not NULL:
            yield form


def _typed_distinct(array: pa.Array) -> int:
    if pa.types.is_floating(array.type):
        # Without NaN, and with -0.0 as 0.0, as the forms count them.
        array = pc.add(array.filter(_valid(array)), pa.scalar(0.0, array.type))
    return int(pc.count_distinct(array, mode="only_valid").as_py())


def distinct_values(column: Column) -> int:
    """The non-null distinct count of `column` on the value forms. Raises as `identity_facts`."""
    typed = _typed(column)
    if typed is not None:
        return _typed_distinct(typed)
    return len(set(_forms(column)))


def duckdb_countable(kind: pa.DataType) -> bool:
    """True for a type whose DuckDB distinct count equals `distinct_values` (DN-R1-6)."""
    return bool(
        pa.types.is_boolean(kind)
        or pa.types.is_integer(kind)
        or kind in (pa.float32(), pa.float64(), pa.string(), pa.large_string())
    )


class DistinctCounter:
    """An exact distinct count over the batches of one column, refused before its memory budget.

    The budget is an estimate of `_ENTRY_BYTES` per distinct form; a refusal raises a fixed
    `MemoryError` and the partial count is discarded."""

    _ENTRY_BYTES = 256

    def __init__(self, budget_bytes: int) -> None:
        self._limit = max(1, budget_bytes // self._ENTRY_BYTES)
        self._seen: set[object] = set()

    def add(self, column: Column) -> None:
        if isinstance(column, (pa.Array, pa.ChunkedArray)) and _ticks(column.type):
            # Ticks in the declared unit: one schema, so one unit for the whole column.
            self._seen.update(pc.cast(column.drop_null(), pa.int64()).to_pylist())
        else:
            self._seen.update(_forms(column))
        if len(self._seen) > self._limit:
            self._seen = set()
            # A builtin class: the facts record an uncoded failure by its class name.
            raise MemoryError("a distinct count would pass its memory budget")

    def count(self) -> int:
        return len(self._seen)


def _ticks(kind: pa.DataType) -> bool:
    return bool(
        pa.types.is_timestamp(kind) or pa.types.is_duration(kind) or pa.types.is_date32(kind)
    )
