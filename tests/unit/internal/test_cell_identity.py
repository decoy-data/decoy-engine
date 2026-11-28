"""PM-1 S1a: pair table for the cell identity authority (value forms, nulls, records).

Written before the module exists (plan: docs/plans/2026-11-27-pm1-comparison-redesign.md,
slice S1a). The authority is imported inside each test, so collection works today. Rows that
need the missing module are strict xfail and name the slice that turns them green. Synthetic
values only, and no assertion message carries a cell value (value-free).
"""

from __future__ import annotations

import collections
import datetime as dt
import signal
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import pytest

from decoy_engine.internal.pandas_missing import is_null_cell

MODULE = "decoy_engine.internal.cell_identity"


class _AuthorityMissingError(Exception):
    """The authority module is not built yet (only this module's absence is expected)."""


def _authority() -> Any:
    try:
        import importlib

        return importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise
        raise _AuthorityMissingError from exc


# S3 builds identity_facts, distinct_values, IdentityFacts and CellNotComparableError.
needs_authority = pytest.mark.xfail(
    raises=_AuthorityMissingError,
    strict=True,
    reason="S3: internal.cell_identity does not exist yet",
)
# S2 extends the shared missing-cell predicate (masked constant, Decimal sNaN).
needs_predicate = pytest.mark.xfail(
    strict=True, reason="S2: is_null_cell does not yet treat masked or sNaN as missing"
)


def _col(*cells: object) -> pd.Series:
    arr = np.empty(len(cells), dtype=object)
    for i, cell in enumerate(cells):
        arr[i] = cell
    return pd.Series(arr)


def _facts(a: object, b: object) -> Any:
    return _authority().identity_facts(_col(a), _col(b))


def _same(a: object, b: object) -> bool:
    facts = _facts(a, b)
    return facts.comparable == 1 and facts.identical == 1


def _differs(a: object, b: object) -> bool:
    facts = _facts(a, b)
    return facts.comparable == 1 and facts.identical == 0


@contextmanager
def _within(seconds: int) -> Iterator[None]:
    """Fail a hang loudly (PC1-1). A no-op where SIGALRM does not exist."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _fire(*_: object) -> None:
        raise AssertionError("comparison did not finish in time")

    old = signal.signal(signal.SIGALRM, _fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _record() -> np.void:
    arr = np.zeros(2, dtype=[("a", "i4"), ("b", "f8")])
    arr.flags.writeable = False
    return arr[0]


_NT = collections.namedtuple("_NT", "x y")
_T2 = dt.datetime(2020, 1, 1, 5, 0, tzinfo=dt.timezone.utc)
_NY = pd.Timestamp("2020-01-01 05:00", tz="America/New_York")
_US_2500 = np.datetime64("2500-01-01", "us")
_WRAPPED_NS = np.datetime64(((int(_US_2500.astype("int64")) * 1000 + 2**63) % 2**64) - 2**63, "ns")

# ---------------------------------------------------------------- value forms: SAME

SAME_ROWS = [
    ("bool-int", True, 1),
    ("bool-npbool", True, np.bool_(True)),
    ("npbool-int", np.bool_(True), 1),
    ("E-7 zero signs", 0.0, -0.0),
    ("int-float", 1, 1.0),
    ("npint-int", np.int8(3), 3),
    ("npfloat32-float", np.float32(0.5), 0.5),
    ("E-12 int-decimal", 10**30, Decimal(10**30)),
    ("decimal-int", Decimal("2.0"), 2),
    ("DN-R1-2c longdouble inf", np.longdouble("inf"), float("inf")),
    ("DN-R1-2c longdouble -inf", np.longdouble("-inf"), float("-inf")),
    ("R2-V6c complex width", complex(1.5, 2), np.clongdouble(complex(1.5, 2))),
    ("R2-V6c complex inf", np.clongdouble(complex(float("inf"), 2)), complex(float("inf"), 2)),
    ("R2-V6c complex -inf", complex(1, float("-inf")), np.clongdouble(complex(1, float("-inf")))),
    ("R2-V6c real as complex", complex(1.5, 0), 1.5),
    ("DN-P1-5 generic timedelta", np.timedelta64(5), 5),
    ("O3-1 timedelta units", np.timedelta64(1, "s"), np.timedelta64(1000, "ms")),
    ("O5-2 multiple unit", np.array([1], "datetime64[2s]")[0], np.array([2], "datetime64[s]")[0]),
    (
        "DN-P1-5 aware vs utc",
        dt.datetime(2020, 1, 1, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        pd.Timestamp("2020-01-01 05:00", tz="UTC"),
    ),
    (
        "DN-R1-8d aware vs naive utc",
        dt.datetime(2020, 1, 1, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        np.datetime64("2020-01-01T05:00:00", "ns"),
    ),
    ("DN-R1-8a utc wall clock", _NY, pd.Timestamp("2020-01-01 10:00")),
    ("DN-R1-8b zone wall clock", _NY, pd.Timestamp("2020-01-01 05:00")),
    (
        "R2-V6a month instant",
        np.datetime64("2020-01", "M"),
        np.datetime64("2020-01-01T00:00:00", "ns"),
    ),
    ("R2-V6a year instant", np.datetime64("2020", "Y"), np.datetime64("2020-01-01", "D")),
    ("DN-R1-1a date vs D", dt.date(2020, 1, 1), np.datetime64("2020-01-01", "D")),
    ("DN-R1-1b date vs ns", dt.date(2020, 1, 1), np.datetime64("2020-01-01T00:00", "ns")),
    ("DN-R1-1c date vs Timestamp", dt.date(2020, 1, 1), pd.Timestamp("2020-01-01")),
    ("DN-R1-1e date vs utc", dt.date(2020, 1, 1), pd.Timestamp("2020-01-01", tz="UTC")),
    (
        "R2-V6b coarser equivalent",
        np.datetime64("2020-01-01", "s"),
        np.datetime64("2020-01-01", "us"),
    ),
    ("DN-P2-1 tuple vs array", (1, 2), np.array([1, 2])),
    ("O4-2 int vs object array", np.array([1, 2]), np.array([1, 2], dtype=object)),
    ("PC1-2 list vs array", [3], np.array([3])),
    ("OD-2 namedtuple", _NT(1, 2), (1, 2)),
    (
        "OD-3 dict array order",
        np.array([{"a": 1, "b": 2}], dtype=object),
        np.array([{"b": 2, "a": 1}], dtype=object),
    ),
    ("dict order", {"b": 2, "a": 1}, {"a": 1, "b": 2}),
    ("DN-F-LOW-2 map key", {np.int64(1): "a"}, {1: "a"}),
    ("CX-2 set order", {1, 2, 3}, {3, 2, 1}),
    ("set vs frozenset", {1, 2}, frozenset({2, 1})),
    ("E-10 list vs tuple", [], ()),
    ("O3-2 0-dim", np.array(7), 7),
    ("O5-3 0-dim bool", np.array(True), True),
    ("DN-R1-2f nan in list", [float("nan")], [None]),
    ("nested temporal", [dt.date(2020, 1, 1), 1], [np.datetime64("2020-01-01", "D"), 1.0]),
    ("uuid", uuid.UUID(int=1), uuid.UUID(int=1)),
]


@needs_authority
@pytest.mark.parametrize(("a", "b"), [r[1:] for r in SAME_ROWS], ids=[r[0] for r in SAME_ROWS])
def test_value_forms_same(a: object, b: object) -> None:
    assert _same(a, b)
    assert _same(b, a)


# ---------------------------------------------------------------- value forms: DIFFERENT

DIFFERENT_ROWS = [
    ("N-1 int beyond float", 2**53 + 1, float(2**53)),
    ("N-1 decimal vs float", Decimal("0.1"), 0.1),
    ("DN-R1-2c inf vs -inf", np.longdouble("inf"), np.longdouble("-inf")),
    ("R2-V6c complex imag", complex(1.5, 2), np.clongdouble(complex(1.5, 3))),
    ("R2-V6c complex real", complex(1.5, 2), np.clongdouble(complex(1.0, 2))),
    ("R2-V6c complex inf sign", complex(float("inf"), 2), complex(float("-inf"), 2)),
    ("R2-V6a month vs 31 days", np.timedelta64(1, "M"), np.timedelta64(31, "D")),
    ("O5-2 fs ticks", np.timedelta64(1, "fs"), np.timedelta64(2, "fs")),
    (
        "O5-2 multiple unit ticks",
        np.array([1], "datetime64[2s]")[0],
        np.array([1], "datetime64[s]")[0],
    ),
    ("R2-V6b wrapped ns cast", _US_2500, _WRAPPED_NS),
    ("DN-R1-1d date vs +1s", dt.date(2020, 1, 1), pd.Timestamp("2020-01-01 00:00:01")),
    ("DN-R1-8c wrong wall clock", _NY, pd.Timestamp("2020-01-01 07:00")),
    ("list order", [1, 2], [2, 1]),
    ("list vs set", [1, 2], {1, 2}),
    ("E-10 list vs set", [], set()),
    ("E-10 set vs dict", set(), {}),
    ("E-10 list vs dict", [], {}),
    ("set member", {1, 2}, {1, 3}),
    ("O4-3 0-dim object dict", np.array({"a": 1}, dtype=object), np.array({"a": 2}, dtype=object)),
    ("dict value", {"a": [1, 2]}, {"a": [3, 4]}),
    ("dict key", {"a": 1}, {"b": 1}),
    ("tuple length", (1, 2), (1, 2, 3)),
    ("namedtuple vs other values", _NT(1, 2), (1, 3)),
    ("uuid", uuid.UUID(int=1), uuid.UUID(int=2)),
]


@needs_authority
@pytest.mark.parametrize(
    ("a", "b"), [r[1:] for r in DIFFERENT_ROWS], ids=[r[0] for r in DIFFERENT_ROWS]
)
def test_value_forms_different(a: object, b: object) -> None:
    assert _differs(a, b)
    assert _differs(b, a)


@needs_authority
@pytest.mark.parametrize(
    "cell",
    [np.timedelta64(-(2**62), "ns"), np.timedelta64(-(2**62), "M"), np.datetime64(2**62, "M")],
    ids=["PC1-4 ns", "PC1-4 months", "PC1-5 huge months"],
)
def test_temporal_extremes_are_values_not_null(cell: object) -> None:
    facts = _facts(cell, cell)
    assert (facts.comparable, facts.identical, facts.all_same) == (1, 1, True)


# ---------------------------------------------------------------- nulls

NULL_CELLS = [
    ("None", None),
    ("float nan", float("nan")),
    ("np float32 nan", np.float32("nan")),
    ("longdouble nan", np.longdouble("nan")),
    ("decimal nan", Decimal("NaN")),
    ("decimal sNaN", Decimal("sNaN")),
    ("complex nan", complex("nan+0j")),
    ("pd.NA", pd.NA),
    ("pd.NaT", pd.NaT),
    ("np NaT", np.datetime64("NaT")),
    ("masked constant", np.ma.masked),
    ("boxed NaT", np.array(np.datetime64("NaT"))),
]


@needs_authority
@pytest.mark.parametrize(("name", "cell"), NULL_CELLS, ids=[n for n, _ in NULL_CELLS])
def test_null_forms(name: str, cell: object) -> None:
    both = _facts(cell, cell)
    assert (both.comparable, both.identical, both.all_same) == (0, 0, True)
    assert _facts(cell, 1).all_same is False
    assert _facts(1, cell).comparable == 0


@needs_authority
def test_one_null_pairs_with_every_other_null_form() -> None:
    for _, x in NULL_CELLS:
        for _, y in NULL_CELLS:
            facts = _facts(x, y)
            assert (facts.comparable, facts.all_same) == (0, True)


@needs_authority
def test_null_rows_do_not_hide_a_changed_row() -> None:
    facts = _authority().identity_facts(_col(1, None, 3), _col(1, None, 4))
    assert (facts.comparable, facts.identical, facts.all_same) == (2, 1, False)


@needs_authority
def test_empty_columns() -> None:  # E-1
    facts = _authority().identity_facts(_col(), _col())
    assert (facts.comparable, facts.identical, facts.all_same) == (0, 0, True)


@needs_authority
def test_all_null_columns() -> None:  # E-2, E-3
    auth = _authority()
    both = auth.identity_facts(_col(None, np.nan), _col(pd.NA, None))
    assert (both.comparable, both.all_same) == (0, True)
    one = auth.identity_facts(_col(None, None), _col(1, 2))
    assert (one.comparable, one.all_same) == (0, False)


@needs_authority
def test_positions_not_labels() -> None:  # E-5
    src = pd.Series([1, 2], index=[10, 11], dtype=object)
    out = pd.Series([1, 2], index=["a", "b"], dtype=object)
    assert _authority().identity_facts(src, out).identical == 2


@needs_authority
def test_string_na_vs_object_none() -> None:  # E-14
    facts = _authority().identity_facts(
        pd.Series([pd.NA, "a"], dtype="string"), pd.Series([None, "a"], dtype=object)
    )
    assert (facts.comparable, facts.identical, facts.all_same) == (1, 1, True)


@needs_authority
def test_merge_folds_batches() -> None:
    auth = _authority()
    one = auth.identity_facts(_col(1, 2), _col(1, 2))
    two = auth.identity_facts(_col(3, None), _col(4, None))
    merged = one.merge(two)
    assert (merged.comparable, merged.identical, merged.all_same) == (3, 2, False)
    assert one.merge(one).all_same is True


@needs_authority
def test_distinct_values_counts_value_forms() -> None:
    auth = _authority()
    assert auth.distinct_values(_col({"id": 1}, {("id", 1)})) == 2  # OD-1
    assert auth.distinct_values(_col(1, 1.0, True, None, np.nan)) == 1
    assert auth.distinct_values(_col({1, 2}, {2, 1}, [1, 2])) == 2


# ---------------------------------------------------------------- records and cycles

RECORD_CELLS = [
    ("bare", lambda r: r),
    ("CX-3b in list", lambda r: [r]),
    ("in tuple", lambda r: (1, r)),
    ("DN-RD-1b tuple of record", lambda r: tuple([r])),
    ("DN-D2-1 frozenset member", lambda r: frozenset([r])),
    ("DN-D2-1 dict key", lambda r: {r: 1}),
    ("DN-RD-1c dict value", lambda r: {"k": r}),
    ("deep", lambda r: [[{"k": (r,)}]]),
    ("structured ndarray", lambda r: np.zeros(1, dtype=[("a", "i4")])),
]


@needs_authority
@pytest.mark.parametrize(("name", "build"), RECORD_CELLS, ids=[n for n, _ in RECORD_CELLS])
@pytest.mark.parametrize("side", ["source", "output"])
@pytest.mark.parametrize("other", ["null", "equal", "text", "number"])
def test_record_is_refused_not_compared(
    name: str, build: Callable[[np.void], object], side: str, other: str
) -> None:
    error = _authority().CellNotComparableError
    cell = build(_record())
    partner = {"null": None, "equal": build(_record()), "text": "x", "number": 1}[other]
    src, out = (cell, partner) if side == "source" else (partner, cell)
    with pytest.raises(error) as info:
        _facts(src, out)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert not info.value.args or all(not isinstance(a, np.void) for a in info.value.args)


@needs_authority
def test_record_distinct_count_is_refused() -> None:
    auth = _authority()
    with pytest.raises(auth.CellNotComparableError):
        auth.distinct_values(_col(1, _record()))


@needs_authority
def test_record_row_aborts_the_whole_column_call() -> None:  # CX-3b, a row-level refusal
    auth = _authority()
    with pytest.raises(auth.CellNotComparableError):
        auth.identity_facts(_col(1, 2, None), _col(1, 2, _record()))


def _cycle_list() -> list[object]:
    box: list[object] = []
    box.append(box)
    return box


def _cycle_dict() -> dict[str, object]:
    box: dict[str, object] = {}
    box["me"] = box
    return box


@needs_authority
@pytest.mark.parametrize("build", [_cycle_list, _cycle_dict], ids=["list", "dict"])
def test_cycle_raises_within_five_seconds(build: Callable[[], object]) -> None:  # PC1-1
    error = _authority().CellNotComparableError
    with _within(5), pytest.raises(error):
        _facts(build(), build())


@needs_authority
def test_shared_child_is_not_a_cycle() -> None:  # R2-V7b
    child = [1, 2]
    with _within(5):
        assert _same([child, child], [[1, 2], [1, 2]])


@needs_authority
def test_masked_constant_inside_a_list_is_null_at_depth() -> None:  # PC1-1
    with _within(5):
        assert _same([np.ma.masked, "marker"], [None, "marker"])


# ---------------------------------------------------------------- null predicate (DN-R1-5, R2-V3b)

LIVE_NULLS = [
    None,
    float("nan"),
    np.float32("nan"),
    Decimal("NaN"),
    pd.NA,
    pd.NaT,
    np.datetime64("NaT"),
]


@pytest.mark.parametrize("cell", LIVE_NULLS, ids=[type(c).__name__ for c in LIVE_NULLS])
def test_masker_predicate_treats_ordinary_nulls_as_missing(cell: object) -> None:
    assert is_null_cell(cell) is True


@pytest.mark.parametrize("cell", [0, "", 0.0, [], [float("nan")], b""], ids=repr)
def test_masker_predicate_keeps_real_values(cell: object) -> None:
    assert is_null_cell(cell) is False


@needs_predicate
@pytest.mark.parametrize("cell", [np.ma.masked, Decimal("sNaN")], ids=["masked", "sNaN"])
def test_masker_predicate_treats_masked_and_snan_as_missing(cell: object) -> None:
    assert is_null_cell(cell) is True
