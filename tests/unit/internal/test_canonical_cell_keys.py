"""Text keys read the canonical walk: plan C1 to C30, the K4 text rows and the properties P1 to P3.

Walk-only rows live in `test_canonical_cell.py`. "Runner ok" means no table error and as many
identical rows as comparable ones; "fails closed" means `ComparisonNotPreservedError`. A second
text row forces the text fallback, so the keys decide the comparison."""

from __future__ import annotations

import collections
import datetime as dt
import itertools
import random
import uuid
from typing import Any, NamedTuple
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.internal.canonical_cell import Null, canonical_cell, contains_record
from decoy_engine.internal.cell_text import RecordNotComparableError, detector_text, key_text
from decoy_engine.verification.postmask import post_scan_verdict, run_post_mask
from decoy_engine.verification.postmask import runner as runner_module
from decoy_engine.verification.postmask._column_facts import identity_counts
from decoy_engine.verification.postmask.runner import _frame_tables

MARKER = "x-marker"
BACKSTOP = "ComparisonNotPreservedError"


def _objects(*cells: object) -> pd.Series:
    return pd.Series(_object_array(*cells), dtype=object)


def key(cell: object) -> str | None:
    return key_text(_objects(cell))[0]


def _boxed(payload: object) -> np.ndarray:
    cell = np.empty((), dtype=object)
    cell[()] = payload
    return cell


def _object_array(*cells: object) -> np.ndarray:
    out = np.empty(len(cells), dtype=object)
    for i, cell in enumerate(cells):
        out[i] = cell
    return out


def _arr(values: list[int], dtype: str) -> np.ndarray:
    return np.array(values, dtype=dtype)


class Run(NamedTuple):
    failed: dict[str, str]
    cells: tuple[int, int]  # (comparable, identical) of the cells
    keys: tuple[int, int] | None  # the same, on the keys the runner emitted


def run(src_cell: object, out_cell: object) -> Run:
    """The runner's table errors and the identity counts of one cell pair, next to an unchanged
    marker row that keeps the column off the native Arrow path. The key counts read the arrays
    the runner emits, not keys rebuilt by the test."""
    src = pd.DataFrame({"v": _objects(src_cell, MARKER)})
    out = pd.DataFrame({"v": _objects(out_cell, MARKER)})
    emitted: list[pd.Series] = []
    real = runner_module._text

    def spy(series: pd.Series) -> Any:
        array = real(series)
        emitted.append(pd.Series(array.to_pylist(), dtype=object))
        return array

    with mock.patch.object(runner_module, "_text", spy):
        failed = _frame_tables({"t": src}, {"t": out})[2]
    # The output frame is converted first, then the source.
    keys = identity_counts(emitted[1], emitted[0]) if len(emitted) == 2 else None
    try:
        cells = identity_counts(src["v"], out["v"])
    except RecordNotComparableError:
        cells = (0, 0)
    return Run(failed, cells, keys)


class _P(NamedTuple):
    x: int
    y: int


def _utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _plus_one(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="Etc/GMT-1")


OK = [
    pytest.param(_arr([0], "m8[s]"), _arr([0], "m8[ns]"), id="C1"),
    pytest.param(np.array(7), np.array(7), id="C2"),
    pytest.param(_arr([1], "m8[s]"), _arr([1000], "m8[ms]"), id="C4"),
    pytest.param(np.array([1, 2]), _object_array(1, 2), id="C5"),
    pytest.param(_arr([1], "m8[M]"), _arr([1], "m8[M]"), id="C6"),
    pytest.param(_arr([1], "m8[Y]"), _arr([12], "m8[M]"), id="C7"),
    pytest.param(_arr([1], "M8[2s]"), _arr([2], "M8[s]"), id="C9"),
    pytest.param(_arr([1], "M8[M]"), np.array(["1970-02-01"], dtype="M8[D]"), id="C11"),
    pytest.param(np.array(True), True, id="C12"),
    pytest.param(_object_array({"b": 2, "a": 1}), _object_array({"a": 1, "b": 2}), id="C14"),
    pytest.param(_P(1, 2), (1, 2), id="C15"),
    pytest.param([float("nan")], [float("nan")], id="C19"),
    pytest.param(
        pd.Timestamp("3000-01-01").as_unit("s"), pd.Timestamp("3000-01-01").as_unit("s"), id="C21"
    ),
    pytest.param(
        pd.Timedelta(np.timedelta64(146000 * 86_400, "s")),
        pd.Timedelta(np.timedelta64(146000 * 86_400, "s")),
        id="C23",
    ),
    pytest.param(np.timedelta64(5), 5, id="C24"),
    pytest.param(
        dt.datetime(2020, 1, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        _plus_one("2020-01-01 01:00"),
        id="C25",
    ),
]

FAILS_CLOSED = [
    pytest.param(_utc("2020-01-01"), _plus_one("2020-01-01 01:00"), id="C17"),
    pytest.param([1], [1.0], id="C20"),
    pytest.param(
        dt.datetime(2020, 1, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        _utc("2020-01-01"),
        id="C26",
    ),
    pytest.param((1, 2), np.array([1, 2]), id="C30"),
]


@pytest.mark.parametrize(("a", "b"), OK)
def test_runner_ok_when_the_keys_keep_the_cells_equality(a: object, b: object) -> None:
    result = run(a, b)
    assert result.failed == {}
    assert result.cells == (2, 2)
    assert key(a) == key(b)


@pytest.mark.parametrize(("a", "b"), FAILS_CLOSED)
def test_runner_fails_closed_on_a_declared_spelling_split(a: object, b: object) -> None:
    assert run(a, b).failed == {"t": BACKSTOP}
    assert key(a) != key(b)
    assert canonical_cell(a) == canonical_cell(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        pytest.param(_boxed({"a": 1}), _boxed({"a": 2}), id="C3"),
        pytest.param(_arr([1], "m8[M]"), _arr([30], "m8[D]"), id="C8"),
        pytest.param(_arr([1], "M8[fs]"), _arr([2], "M8[fs]"), id="C10"),
        pytest.param({"id": 1}, {("id", 1)}, id="C16"),
        pytest.param(pd.Timestamp("2020-01-01"), _utc("2020-01-01"), id="C18"),
    ],
)
def test_different_cells_have_different_keys(a: object, b: object) -> None:
    assert key(a) != key(b)
    result = run(a, b)
    assert result.failed == {}
    assert result.cells == (2, 1)
    assert result.keys == (2, 1)


def test_c2_c13_c24_exact_keys() -> None:
    assert key(np.array(7)) == "7"
    assert key(np.timedelta64(5)) == "5"
    assert key(np.array(True)) == key(True) == "1"
    assert key(np.array(np.datetime64("NaT"))) is None
    assert isinstance(canonical_cell(np.array(np.datetime64("NaT"))), Null)


def test_c9_c15_c21_c23_c27_exact_text() -> None:
    expected = str([pd.Timestamp("1970-01-01 00:00:02")])
    assert key(_arr([1], "M8[2s]")) == key(_arr([2], "M8[s]")) == expected
    assert key(_P(1, 2)) == key((1, 2)) == "(1, 2)"
    assert key([1, 2]) == "[1, 2]"
    assert key((1,)) == "(1,)"
    assert key(pd.Timestamp("3000-01-01").as_unit("s")) == "3000-01-01 00:00:00"
    assert key(pd.Timedelta(np.timedelta64(146000 * 86_400, "s"))) == "146000 days 00:00:00"
    assert key(_arr([1], "M8[fs]")) == "[1970-01-01T00:00:00.000000000000001]"


def test_c19_a_nested_nan_keys_as_nan_and_identity_holds_for_distinct_objects() -> None:
    assert key([float("nan")]) == "[nan]"
    assert identity_counts(_objects([float("nan")]), _objects([float("nan")])) == (1, 1)


def test_c22_a_list_and_its_text_share_a_key() -> None:
    assert key([1]) == key("[1]")
    result = run([1], "[1]")
    assert result.failed == {}
    assert result.cells == (2, 1)
    assert result.keys == (2, 2)


def test_c30_a_tuple_and_an_array_split_by_keys_only() -> None:
    assert identity_counts(_objects((1, 2), MARKER), _objects(np.array([1, 2]), MARKER)) == (2, 2)
    pair = (_objects((1, 2), MARKER), _objects(np.array([1, 2]), MARKER))
    keys = tuple(pd.Series(key_text(s), dtype=object) for s in pair)
    assert identity_counts(*keys) == (2, 1)
    assert canonical_cell((1, 2)) == canonical_cell(np.array([1, 2]))
    assert hash(canonical_cell((1, 2))) == hash(canonical_cell(np.array([1, 2])))


def test_c28_top_level_keys_are_unchanged() -> None:
    cells = _objects(10001.0, 10001, None, memoryview(b"a@x.com"))
    assert key_text(cells) == ["10001", "10001", None, "a@x.com"]


# ----- K4: a typed cell and its str() read as one value (leak direction) ------------------------

K4 = [
    pytest.param(pd.Timestamp("2020-01-01"), "2020-01-01 00:00:00", id="T1"),
    pytest.param(_plus_one("2020-01-01 01:00"), "2020-01-01 01:00:00+01:00", id="T2"),
    pytest.param(pd.Timedelta(seconds=1), "0 days 00:00:01", id="T3"),
    pytest.param(uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001", id="T4"),
    pytest.param(dt.date(2020, 1, 1), "2020-01-01", id="T5"),
    pytest.param([1, "a"], "[1, 'a']", id="T6"),
    pytest.param({"a": 1}, "{'a': 1}", id="T7"),
    pytest.param((1, "a"), "(1, 'a')", id="T8"),
    pytest.param([float("nan"), "a"], "[nan, 'a']", id="T9"),
    pytest.param([pd.NaT, "a"], "[NaT, 'a']", id="T10"),
    pytest.param(
        [dt.datetime(2020, 1, 1), "a"], "[datetime.datetime(2020, 1, 1, 0, 0), 'a']", id="T11"
    ),
    pytest.param(dt.timedelta(seconds=1), "0:00:01", id="T12"),
    pytest.param(
        [_plus_one("2020-01-01 01:00"), "a"],
        "[Timestamp('2020-01-01 01:00:00+0100', tz='Etc/GMT-1'), 'a']",
        id="T13",
    ),
    pytest.param([dt.date(2020, 1, 1)], "[datetime.date(2020, 1, 1)]", id="date-in-list"),
    pytest.param([bytearray(b"a")], "[bytearray(b'a')]", id="bytearray-in-list"),
    pytest.param(frozenset({1}), "frozenset({1})", id="frozenset"),
    pytest.param({"a": [pd.NA, None]}, "{'a': [<NA>, None]}", id="nested-null-variants"),
]


@pytest.mark.parametrize(("source", "text"), K4)
def test_a_typed_cell_keys_like_its_text(source: object, text: str) -> None:
    assert text == str(source)
    assert key(source) == key(text)
    result = run(source, text)
    assert result.failed == {}
    assert result.keys == (2, 2)


def test_numpy_numbers_inside_a_dict_key_as_python_numbers() -> None:
    assert key({"b": np.int64(2), "a": np.float32(0.5)}) == "{'a': 0.5, 'b': 2}"


# ----- properties --------------------------------------------------------------------------------

LINEAR = ["W", "D", "h", "m", "s", "ms", "us", "ns", "ps", "fs", "as"]
FINER = dict(itertools.pairwise(LINEAR))
TICKS = st.integers(-1000, 1000)
COUNTS = st.sampled_from([1, 2])


def _stamp(unit: str, count: int, ticks: int, kind: type) -> Any:
    return kind(ticks, f"{count}{unit}" if count > 1 else unit)


NULLS = st.sampled_from(
    [None, float("nan"), pd.NaT, pd.NA, np.datetime64("NaT"), np.timedelta64("NaT", "s")]
)
NP_TEMPORAL = st.one_of(
    st.builds(_stamp, st.sampled_from([*LINEAR, "Y", "M"]), COUNTS, TICKS, st.just(np.datetime64)),
    st.builds(_stamp, st.sampled_from([*LINEAR, "Y", "M"]), COUNTS, TICKS, st.just(np.timedelta64)),
    st.builds(np.timedelta64, TICKS),
)
PD_TEMPORAL = st.one_of(
    st.builds(lambda n: pd.Timestamp(n), st.integers(-(10**15), 10**15)),
    st.builds(lambda n: pd.Timestamp(n, tz="UTC"), st.integers(-(10**15), 10**15)),
    st.builds(lambda n: pd.Timedelta(n, unit="ns"), st.integers(-(10**15), 10**15)),
)
NESTED_LEAF = st.one_of(
    st.none(),
    st.integers(-(2**70), 2**70),
    st.builds(np.int16, st.integers(-100, 100)),
    st.text(max_size=3),
    NP_TEMPORAL.filter(lambda v: not np.isnat(v)),
    PD_TEMPORAL.filter(lambda v: getattr(v, "tzinfo", None) is None),
)
TOP_LEAF = st.one_of(
    NULLS,
    NESTED_LEAF,
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.builds(np.float32, st.floats(-1e6, 1e6, width=32)),
    st.builds(np.bool_, st.booleans()),
    st.integers(-(2**70), 2**70).map(str),
    st.text(max_size=3).map(str.encode),
    PD_TEMPORAL,
    st.decimals(allow_nan=False, allow_infinity=False, places=3, min_value=-1000, max_value=1000),
)
SMALL_INTS = st.integers(0, 4)


def _tuple_of(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.lists(children, max_size=3).map(tuple)


def _containers(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.one_of(
        st.lists(children, max_size=3),
        _tuple_of(children),
        st.dictionaries(st.text(max_size=2), children, max_size=3),
        st.sets(SMALL_INTS, max_size=3),
        st.lists(st.integers(-5, 5), max_size=3).map(np.array),
        st.lists(children, max_size=3).map(lambda xs: _object_array(*xs)),
    )


P1_CELL = st.one_of(TOP_LEAF, st.recursive(NESTED_LEAF, _containers, max_leaves=6))


def _plain_containers(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(SMALL_INTS, children, max_size=3),
        st.sets(SMALL_INTS, max_size=3),
        st.lists(st.integers(-5, 5), max_size=3).map(np.array),
    )


P2_NESTED = st.one_of(
    st.none(),
    st.integers(-(2**53), 2**53),
    st.builds(np.int16, st.integers(-100, 100)),
    NP_TEMPORAL.filter(lambda v: not np.isnat(v)),
)
P2_CELL = st.one_of(
    NULLS,
    st.integers(-(2**53), 2**53),
    st.booleans(),
    st.floats(-(2.0**53), 2.0**53, allow_nan=False, allow_infinity=False),
    st.builds(np.int64, st.integers(-(2**53), 2**53)),
    NP_TEMPORAL,
    PD_TEMPORAL,
    st.recursive(P2_NESTED, _plain_containers, max_leaves=6),
)


def _shape(cell: Any) -> Any:
    """The sequence style of every level, read from the input and not from the walk (E3)."""
    if isinstance(cell, np.ndarray) and cell.ndim == 0:
        return _shape(cell[()])
    if isinstance(cell, tuple):
        return ("tuple", tuple(_shape(c) for c in cell))
    if isinstance(cell, list | np.ndarray):
        return ("list", tuple(_shape(c) for c in cell))
    if isinstance(cell, dict):
        return ("map", tuple(sorted((repr(k), _shape(v)) for k, v in cell.items())))
    return None


def _same_value(cell: Any, rng: random.Random, *, nested: bool) -> Any:
    """`cell` as another spelling-preserving form of the same value."""
    cell = _rewrite(cell, rng, nested=nested)
    if not nested and rng.random() < 0.3:
        return _boxed(cell)
    return cell


def _rewrite(cell: Any, rng: random.Random, *, nested: bool) -> Any:
    if isinstance(cell, np.datetime64 | np.timedelta64) and not np.isnat(cell):
        unit, count = np.datetime_data(cell.dtype)
        if unit in FINER and rng.random() < 0.5:
            prefix = "M8" if isinstance(cell, np.datetime64) else "m8"
            return cell.astype(f"{prefix}[{FINER[unit]}]")
        if unit == "Y" and isinstance(cell, np.timedelta64) and count == 1:
            return cell.astype("m8[M]")
        if count == 1 and unit in LINEAR and int(cell.astype(np.int64)) % 2 == 0:
            half = int(cell.astype(np.int64)) // 2
            return type(cell)(half, f"2{unit}")
        return cell
    if isinstance(cell, pd.Timestamp) and cell.tzinfo is None and rng.random() < 0.5:
        return cell.asm8
    if isinstance(cell, int) and not isinstance(cell, bool) and rng.random() < 0.5:
        return np.int64(cell) if -(2**63) <= cell < 2**63 else cell
    if isinstance(cell, list):
        items = [_rewrite(c, rng, nested=True) for c in cell]
        return _object_array(*items) if rng.random() < 0.5 else items
    if isinstance(cell, np.ndarray) and cell.ndim == 1:
        return [_rewrite(c, rng, nested=True) for c in cell]
    if isinstance(cell, tuple):
        items = [_rewrite(c, rng, nested=True) for c in cell]
        if rng.random() < 0.5 and items:
            return collections.namedtuple("Row", [f"f{i}" for i in range(len(items))])(*items)
        return tuple(items)
    if isinstance(cell, dict):
        pairs = [(k, _rewrite(v, rng, nested=True)) for k, v in cell.items()]
        rng.shuffle(pairs)
        return dict(pairs)
    return cell


def _floor(name: str) -> Any:
    """A module fixture counting generated cases, which fails the module unless a quarter of
    the pairs have equal canonical forms, so a property cannot pass on pairs that never meet."""

    @pytest.fixture(scope="module", name=name)
    def tally() -> Any:
        seen = {"cases": 0, "equal": 0}
        yield seen
        assert seen["equal"] * 4 >= seen["cases"], (name, seen)

    return tally


p1_tally = _floor("p1_tally")
p2_tally = _floor("p2_tally")
p3_tally = _floor("p3_tally")


def _pair(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.tuples(strategy, strategy, st.randoms(use_true_random=False), st.booleans())


def _count(seen: dict[str, int], a: Any, b: Any) -> bool:
    seen["cases"] += 1
    same = canonical_cell(a) == canonical_cell(b)
    seen["equal"] += int(same)
    return same


@settings(derandomize=True, max_examples=300, deadline=None)
@given(case=_pair(P1_CELL))
def test_p1_equal_cells_have_equal_keys(case: Any, p1_tally: dict[str, int]) -> None:
    a, fresh, rng, derived = case
    b = _same_value(a, rng, nested=False) if derived else fresh
    same = _count(p1_tally, a, b)
    assert (key(a) is None) == isinstance(canonical_cell(a), Null)
    if same and _shape(a) == _shape(b):
        assert key(a) == key(b)


@settings(derandomize=True, max_examples=300, deadline=None)
@given(case=_pair(P2_CELL))
def test_p2_keys_are_equal_exactly_when_the_cells_are(case: Any, p2_tally: dict[str, int]) -> None:
    a, fresh, rng, derived = case
    b = _same_value(a, rng, nested=False) if derived else fresh
    same = _count(p2_tally, a, b)
    if _shape(a) == _shape(b):
        assert same == (key(a) == key(b))


@settings(derandomize=True, max_examples=200, deadline=None)
@given(case=_pair(P1_CELL))
def test_p3_a_spelling_preserving_copy_passes_the_runner(
    case: Any, p3_tally: dict[str, int]
) -> None:
    a, _fresh, rng, _derived = case
    b = _same_value(a, rng, nested=False)
    _count(p3_tally, a, b)
    result = run(a, b)
    assert result.failed == {}
    assert result.cells[0] == result.cells[1]
    assert result.keys is None or result.keys[0] == result.keys[1]


def test_a_nested_complex_nan_keeps_its_python_spelling() -> None:
    assert key([np.complex64(complex("nan+0j"))]) == "[(nan+0j)]"
    assert run([np.complex64(complex("nan+0j"))], "[(nan+0j)]").keys == (2, 2)


def test_a_nested_numpy_void_keeps_its_python_spelling() -> None:
    assert key([np.void(b"ABC")]) == "[b'ABC']"


def test_a_masked_cell_is_a_null_and_does_not_hang() -> None:
    assert key(np.ma.masked) is None
    assert key_text(_objects(np.ma.masked, "x")) == [None, "x"]
    assert detector_text(_objects(np.ma.masked, "x")) == [None, "x"]


def test_a_zero_dimensional_nat_reads_as_null_in_every_reader() -> None:
    nat = np.array(np.datetime64("NaT"))
    assert detector_text(_objects(nat, "x")) == [None, "x"]
    assert key_text(_objects(nat, "x")) == [None, "x"]


def test_distinct_extreme_temporal_values_never_share_a_key() -> None:
    low = -(2**62)
    instant, duration = np.datetime64(low, "2ns"), np.timedelta64(low, "2ns")
    keys = {
        key(instant),
        key(duration),
        key(np.timedelta64(2**62, "2M")),
        key(np.datetime64(2**62, "M")),
    }
    assert len(keys) == 4
    assert "NaT" not in keys


def test_a_numpy_record_keys_from_its_fields_only() -> None:
    record = np.array([(np.array([1, 2], dtype=np.int32),)], dtype=[("samples", "i4", (2,))])[0]
    assert key(record) == "record([1, 2],)"
    assert key([record]) == "[record([1, 2],)]"
    assert key((1, 2)) != key(np.array([(1, 2)], dtype=[("a", "i4"), ("b", "i4")])[0])
    assert run(record, record).failed == {"t": NOT_COMPARABLE}


# ----- records: every field reads through the same unit-normalizing walk ------------------------

UNITS = ["s", "ms", "us", "ns"]
UNIT_PAIRS = list(itertools.combinations(UNITS, 2))


def _record(kind: str, shape: str, unit: str, index: int) -> Any:
    """A one-field record holding the same instant (or length) whatever `unit` is."""
    value = np.array([5, 7], f"{kind}8[s]").astype(f"{kind}8[{unit}]")[index]
    leaf = f"{kind}8[{unit}]"
    if shape == "flat":
        row = np.zeros(1, dtype=[("t", leaf)])
        row["t"][0] = value
    elif shape == "sub":
        row = np.zeros(1, dtype=[("t", leaf, (2,))])
        row["t"][0] = [value, value]
    else:
        row = np.zeros(1, dtype=[("inner", [("t", leaf)])])
        row["inner"]["t"][0] = value
    return row[0]


@pytest.mark.parametrize("shape", ["flat", "sub", "nested"])
@pytest.mark.parametrize("kind", ["M", "m"])
@pytest.mark.parametrize(("left", "right"), UNIT_PAIRS)
def test_records_with_the_same_instant_in_any_unit_are_one_value(
    kind: str, shape: str, left: str, right: str
) -> None:
    a, b = _record(kind, shape, left, 0), _record(kind, shape, right, 0)
    assert canonical_cell(a) == canonical_cell(b)
    assert hash(canonical_cell(a)) == hash(canonical_cell(b))
    assert key(a) == key(b)
    assert key(_record(kind, shape, left, 1)) != key(a)


@pytest.mark.parametrize(("left", "right"), UNIT_PAIRS)
def test_an_unchanged_record_column_in_another_unit_still_fails_the_hash_check(
    left: str, right: str
) -> None:
    emails = [f"user{i}@realmail.com" for i in range(64)]
    fake = [f"fake{i}@masked.example" for i in range(64)]
    column = [_record("M", "flat", left, i % 2) for i in range(64)]
    same = [_record("M", "flat", right, i % 2) for i in range(64)]
    config = {
        "version": 2,
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "email", "strategy": "faker"},
                    {"name": "n", "strategy": "hash"},
                ],
            }
        ],
    }
    src = pd.DataFrame({"email": emails, "n": _objects(*column)})
    out = pd.DataFrame({"email": fake, "n": _objects(*same)})
    report = run_post_mask({"t": src}, {"t": out}, config=config)
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "error"


# ----- a record against another kind is not comparable ------------------------------------------

NOT_COMPARABLE = "RecordNotComparableError"


def _flat(unit: str = "us") -> Any:
    return _record("M", "flat", unit, 0)


def test_r4_case_1_an_unchanged_record_exported_as_text_is_refused() -> None:
    record = _flat("us")
    assert run(record, str(record.item())).failed == {"t": NOT_COMPARABLE}
    emails = [f"user{i}@realmail.com" for i in range(64)]
    fake = [f"fake{i}@masked.example" for i in range(64)]
    config = {
        "version": 2,
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "email", "strategy": "faker"},
                    {"name": "n", "strategy": "hash"},
                ],
            }
        ],
    }
    cells = [_record("M", "flat", "us", i % 2) for i in range(64)]
    text = [str(c.item()) for c in cells]
    src = pd.DataFrame({"email": emails, "n": _objects(*cells)})
    out = pd.DataFrame({"email": fake, "n": _objects(*text)})
    report = run_post_mask({"t": src}, {"t": out}, config=config)
    errors = [f for f in report["residual_pii"] if f["severity"] == "error"]
    assert errors
    assert NOT_COMPARABLE in errors[0]["message"]
    assert not any(
        "differs from source" in f.get("message", "") for f in report["policy_validation"]
    )
    assert post_scan_verdict(report).blocking


@pytest.mark.parametrize("other", ["text", "tuple", "number", "list-of-text"])
def test_a_record_against_another_kind_is_refused_both_ways(other: str) -> None:
    record = _flat("ns")
    cell = {"text": "x", "tuple": (1,), "number": 5, "list-of-text": ["x"]}[other]
    assert run(record, cell).failed == {"t": NOT_COMPARABLE}
    assert run(cell, record).failed == {"t": NOT_COMPARABLE}
    assert run([record], [cell]).failed == {"t": NOT_COMPARABLE}
    with pytest.raises(RecordNotComparableError):
        identity_counts(_objects(record), _objects(cell))


def test_a_record_against_a_null_or_a_record_is_refused() -> None:
    assert run(_flat("ns"), None).failed == {"t": NOT_COMPARABLE}
    assert run(_flat("ns"), _flat("us")).failed == {"t": NOT_COMPARABLE}
    assert run([_flat("ns")], [_flat("us")]).failed == {"t": NOT_COMPARABLE}


def _subarray_of_nested(unit: str) -> Any:
    inner = [("u", f"M8[{unit}]")]
    row = np.zeros(1, dtype=[("t", inner, (2,))])
    row["t"]["u"][0] = np.array([5, 7], "M8[s]").astype(f"M8[{unit}]")
    return row[0]


def test_r4_case_2_a_subarray_of_nested_records_keys_alike_in_every_unit() -> None:
    a, b = _subarray_of_nested("us"), _subarray_of_nested("ns")
    assert canonical_cell(a) == canonical_cell(b)
    assert key(a) == key(b)
    assert run(a, b).failed == {"t": NOT_COMPARABLE}


def _deep3(unit: str) -> Any:
    leaf = [("t", f"M8[{unit}]")]
    row = np.zeros(1, dtype=[("a", [("b", [("c", leaf)])])])
    row["a"]["b"]["c"]["t"][0] = np.array([5], "M8[s]").astype(f"M8[{unit}]")[0]
    return row[0]


def _object_field(held: object) -> Any:
    row = np.zeros(1, dtype=[("o", object)])
    row["o"][0] = held
    return row[0]


PARTIAL_EXPORTS = [
    pytest.param(_subarray_of_nested("us"), lambda r: r.item(), id="item-of-subarray-of-nested"),
    pytest.param(_subarray_of_nested("us"), lambda r: r["t"].tolist(), id="tolist-of-subfield"),
    pytest.param(_subarray_of_nested("us"), lambda r: {"t": r["t"]}, id="dict-of-subarray"),
    pytest.param(_record("M", "nested", "us", 0), lambda r: tuple(r), id="tuple-of-nested"),
    pytest.param(_deep3("us"), lambda r: tuple(r), id="tuple-of-deep3"),
    pytest.param(_deep3("us"), lambda r: {"a": r["a"]}, id="dict-of-deep3-field"),
    pytest.param(
        _record("M", "nested", "us", 0), lambda r: {"inner": r["inner"]}, id="dict-of-nested"
    ),
    pytest.param(
        _record("M", "flat", "us", 0), lambda r: {"k": r}, id="dict-value-holding-the-record"
    ),
]


@pytest.mark.parametrize(("record", "export"), PARTIAL_EXPORTS)
def test_a_partial_export_that_keeps_an_inner_record_is_refused(record: Any, export: Any) -> None:
    other = export(record)
    assert run(record, other).failed == {"t": NOT_COMPARABLE}
    assert run(other, record).failed == {"t": NOT_COMPARABLE}
    held = contains_record(canonical_cell(export(record)))
    assert run(export(record), export(record)).failed == ({"t": NOT_COMPARABLE} if held else {})
    # The export keeps the inner record, and the wrapper itself carries the same record.
    assert run({"k": record}, {"k": str(record.item())}).failed == {"t": NOT_COMPARABLE}


def test_an_object_field_holding_a_record_against_its_text_is_refused() -> None:
    inner = _record("M", "flat", "us", 0)
    held, text = _object_field(inner), _object_field(str(inner.item()))
    assert run(held, text).failed == {"t": NOT_COMPARABLE}
    assert run(text, held).failed == {"t": NOT_COMPARABLE}
    assert run(held, _object_field(inner)).failed == {"t": NOT_COMPARABLE}


def test_a_changed_record_is_refused_not_graded() -> None:
    assert run(_record("M", "flat", "ns", 0), _record("M", "flat", "ns", 1)).failed == {
        "t": NOT_COMPARABLE
    }
    assert run([_record("M", "flat", "ns", 0)], [_record("M", "flat", "ns", 1)]).failed == {
        "t": NOT_COMPARABLE
    }
    assert run({"k": _flat("ns")}, {"k": _record("M", "flat", "ns", 1)}).failed == {
        "t": NOT_COMPARABLE
    }


def _readonly(unit: str = "us") -> Any:
    """A record scalar that NumPy lets a set or a dict key hold."""
    row = np.zeros(1, dtype=[("t", f"M8[{unit}]")])
    row["t"][0] = np.array([5], "M8[s]").astype(f"M8[{unit}]")[0]
    row.setflags(write=False)
    record = row[0]
    hash(record)
    return record


def test_a_readonly_record_in_a_set_a_frozenset_or_a_key_is_refused() -> None:
    record = _readonly()
    text = str(record.item())
    pairs = [
        ({record}, {text}),
        (frozenset([record]), frozenset([record.item()])),
        ({record: 1}, {text: 1}),
    ]
    for held, other in pairs:
        assert run(held, other).failed == {"t": NOT_COMPARABLE}
        assert run(other, held).failed == {"t": NOT_COMPARABLE}
    assert run({record}, {_readonly()}).failed == {"t": NOT_COMPARABLE}


# ----- one comparison authority at the public entry ---------------------------------------------

HASH_CONFIG = {
    "version": 2,
    "tables": [
        {
            "name": "t",
            "columns": [
                {"name": "email", "strategy": "faker"},
                {"name": "n", "strategy": "hash"},
            ],
        }
    ],
}


def _gate(src_cells: list[Any], out_cells: list[Any]) -> Any:
    """`run_post_mask` over a faker email column and a hash column holding the given cells."""
    count = len(src_cells)
    emails = [f"user{i}@realmail.com" for i in range(count)]
    fake = [f"fake{i}@masked.example" for i in range(count)]
    src = pd.DataFrame({"email": emails, "n": _objects(*src_cells)})
    out = pd.DataFrame({"email": fake, "n": _objects(*out_cells)})
    return run_post_mask({"t": src}, {"t": out}, config=HASH_CONFIG)


def _blocks(report: Any) -> bool:
    return bool(post_scan_verdict(report).blocking)


def test_codex_1_an_unchanged_nested_object_column_blocks() -> None:
    cells = [{"a": [1, 2]} if i % 2 else {"a": [3, 4]} for i in range(64)]
    assert _blocks(_gate(cells, [dict(c) for c in cells]))


def test_codex_2_equal_sets_in_another_iteration_order_block() -> None:
    forward = [{0, 8} if i % 2 else {1, 9} for i in range(64)]
    backward = [{8, 0} if i % 2 else {9, 1} for i in range(64)]
    assert list(forward[1]) != list(backward[1])
    assert forward[1] == backward[1]
    assert _blocks(_gate(forward, backward))


def test_codex_3_record_columns_block_whatever_the_dtype_equality_or_nulls() -> None:
    rows = np.zeros(2, dtype=[("t", "i8")])
    rows["t"] = [1, 2]
    rows.setflags(write=False)
    first, second = rows[0], rows[1]
    one = [_flat("us")]
    assert _blocks(_gate(one, [_flat("us")]))
    cells = [_flat("us") if i % 2 else _flat("ns") for i in range(64)]
    assert _blocks(_gate(cells, list(cells)))
    assert _blocks(_gate(cells, [None if i % 3 == 0 else c for i, c in enumerate(cells)]))
    codes = [i % 2 for i in range(64)]
    straight = pd.Categorical.from_codes(codes, categories=[first, second])
    swapped = pd.Categorical.from_codes([1 - c for c in codes], categories=[first, second])
    src = pd.DataFrame({"email": [f"user{i}@realmail.com" for i in range(64)], "n": straight})
    out = pd.DataFrame({"email": [f"fake{i}@masked.example" for i in range(64)], "n": swapped})
    assert _blocks(run_post_mask({"t": src}, {"t": out}, config=HASH_CONFIG))
