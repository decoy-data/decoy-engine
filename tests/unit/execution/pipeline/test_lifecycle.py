"""F24 84-E1: the I/O-free phase arithmetic of the lifecycle estimate.

Every expectation is written out in bytes here, from the plan's section 4.2 terms, so a change to
a term in `_lifecycle.py` cannot move its own test with it.
"""

from __future__ import annotations

import sys

import pyarrow as pa
import pytest

from decoy_engine.execution._mem_estimate import (
    ColumnSizeSpec,
    TableSizeSpec,
    estimate_peak_bytes,
    route_intercept_bytes,
)
from decoy_engine.execution.pipeline import _lifecycle as lc

INT_OBJ = sys.getsizeof(1 << 20)
INTERCEPT = route_intercept_bytes("full_frame")


def _dict_bytes(columns: int) -> int:
    return sys.getsizeof(dict.fromkeys(range(columns)))


def _str(name: str, width: float, *, nulls: bool = False) -> lc.ColumnInputs:
    spec = ColumnSizeSpec(name, "object", string_width_bytes=width)
    return lc.ColumnInputs(name, pa.string(), nulls, spec)


def _int(name: str) -> lc.ColumnInputs:
    return lc.ColumnInputs(name, pa.int64(), False, ColumnSizeSpec(name, "int64"))


def _table(
    name: str,
    rows: int,
    columns: tuple[lc.ColumnInputs, ...],
    *,
    source: str = "csv",
    target: lc.TargetInputs | None = None,
    row_group_bytes: int = 0,
    has_transforms: bool = False,
) -> lc.TableInputs:
    return lc.TableInputs(
        name=name,
        rows=rows,
        columns=columns,
        source_format=source,
        target=target or lc.TargetInputs("parquet"),
        row_group_bytes=row_group_bytes,
        has_transforms=has_transforms,
    )


def _phase(result: lc.Lifecycle, name: str) -> int:
    return dict(result.phase_bytes)[name]


def _peak(tables: tuple[lc.TableInputs, ...], path: str = "full_frame") -> lc.Lifecycle:
    return lc.lifecycle_peak(lc.PhaseInputs(path=path, tables=tables))  # type: ignore[arg-type]


# One string column of mean width 10: Arrow holds 4 offset bytes plus 10 payload bytes a row; the
# pandas frame holds a pointer, a 49-byte header and the payload, 67 bytes a row.
def _s_table(
    name: str,
    rows: int,
    *,
    source: str = "csv",
    target: lc.TargetInputs | None = None,
    row_group_bytes: int = 0,
    has_transforms: bool = False,
) -> lc.TableInputs:
    return _table(
        name,
        rows,
        (_str("s", 10.0),),
        source=source,
        target=target,
        row_group_bytes=row_group_bytes,
        has_transforms=has_transforms,
    )


# --- AT-E1-1 -----------------------------------------------------------------------------


def test_ingest_holds_earlier_tables_as_arrow_while_the_next_is_read() -> None:
    # B larger: the peak is at B, with A already resident as Arrow.
    b_larger = _peak((_s_table("a", 1000), _s_table("b", 2000)))
    assert _phase(b_larger, "ingest") == INTERCEPT + 14_000 + 134_000 + 28_000
    # A larger: the peak is at A itself, nothing earlier is resident.
    a_larger = _peak((_s_table("a", 2000), _s_table("b", 1000)))
    assert _phase(a_larger, "ingest") == INTERCEPT + 134_000 + 28_000


# --- AT-E1-2 -----------------------------------------------------------------------------


def test_parquet_ingest_transient_is_arrow_plus_the_largest_row_group() -> None:
    parquet = _s_table("t", 1000, source="parquet", row_group_bytes=5_000)
    assert _phase(_peak((parquet,)), "ingest") == INTERCEPT + 14_000 + 5_000
    csv = _s_table("t", 1000, source="csv")
    assert _phase(_peak((csv,)), "ingest") == INTERCEPT + 67_000 + 14_000


def test_fixed_width_ingest_is_the_larger_of_records_and_frame_plus_arrow() -> None:
    # Narrow strings: the reader's row dicts dominate (records + refs).
    narrow = _s_table("t", 1000, source="fixed_width")
    records = 1000 * (_dict_bytes(1) + 8 + 67) + 8_000
    assert records > 67_000 + 14_000
    assert _phase(_peak((narrow,)), "ingest") == INTERCEPT + records
    # Very wide strings: the frame and its Arrow copy dominate.
    wide = _table("t", 1000, (_str("s", 1000.0),), source="fixed_width")
    wide_records = 1000 * (_dict_bytes(1) + 8 + 1057) + 8_000
    wide_frame_arrow = 1000 * 1057 + 1000 * 1004
    assert wide_frame_arrow > wide_records
    assert _phase(_peak((wide,)), "ingest") == INTERCEPT + wide_frame_arrow


# --- AT-E1-3, AT-E1-16 -------------------------------------------------------------------


def _two_inputs(path: str) -> tuple[lc.Lifecycle, int, int]:
    spec = (ColumnSizeSpec("s", "object", string_width_bytes=10.0),)
    specs = (TableSizeSpec("small", 1000, spec), TableSizeSpec("large", 3000, spec))
    base = estimate_peak_bytes(specs, path).estimated_bytes  # type: ignore[arg-type]
    assert base is not None
    return _peak((_s_table("small", 1000), _s_table("large", 3000)), path), base, 14_000 + 42_000


def test_execute_full_frame_adds_nothing_to_the_measured_model() -> None:
    result, base, _ = _two_inputs("full_frame")
    assert _phase(result, "execute") == base


def test_execute_sequential_adds_all_inputs_but_the_largest() -> None:
    result, base, total = _two_inputs("sequential")
    assert _phase(result, "execute") == base + (total - 42_000)


def test_execute_out_of_core_adds_every_input() -> None:
    result, base, total = _two_inputs("out_of_core")
    assert _phase(result, "execute") == base + total


def test_a_declared_transform_adds_one_arrow_copy_of_that_table() -> None:
    plain = _peak((_s_table("t", 1000),))
    with_transform = _peak((_s_table("t", 1000, has_transforms=True),))
    assert _phase(with_transform, "execute") == _phase(plain, "execute") + 14_000


# --- AT-E1-4 -----------------------------------------------------------------------------


def test_csv_target_adds_the_frame_of_the_largest_output() -> None:
    csv = lc.TargetInputs("csv")
    small = _s_table("small", 1000, target=csv)
    large = _s_table("large", 3000, target=csv)
    arrows = 14_000 + 42_000
    assert _phase(_peak((small, large)), "write") == INTERCEPT + 2 * arrows + 3000 * 67


def test_parquet_target_adds_no_transient() -> None:
    assert _phase(_peak((_s_table("t", 1000),)), "write") == INTERCEPT + 14_000 + 14_000


# --- AT-E1-5 -----------------------------------------------------------------------------


def test_the_peak_is_the_largest_phase_and_ties_go_to_the_earlier_phase() -> None:
    result = _peak((_s_table("t", 1000),))
    assert [name for name, _ in result.phase_bytes] == ["ingest", "execute", "write"]
    assert result.peak_bytes == max(b for _, b in result.phase_bytes)
    assert result.limiting_phase == max(result.phase_bytes, key=lambda p: p[1])[0]
    assert lc.limiting_phase((("ingest", 5), ("execute", 5), ("write", 3))) == "ingest"
    assert lc.limiting_phase((("ingest", 3), ("execute", 5), ("write", 5))) == "execute"
    assert lc.limiting_phase((("ingest", 3), ("execute", 4), ("write", 5))) == "write"


def test_the_arithmetic_is_stateless() -> None:
    tables = (_s_table("a", 1000), _s_table("b", 2000, target=lc.TargetInputs("csv")))
    assert _peak(tables) == _peak(tables) == _peak(tables)


# --- AT-E1-15 (arithmetic side) ----------------------------------------------------------


def test_arrow_bytes_use_the_arrow_width_and_a_validity_bitmap_for_nulls() -> None:
    spec = ColumnSizeSpec("n", "float64")
    nullable = lc.ColumnInputs("n", pa.int32(), True, spec)
    clean = lc.ColumnInputs("n", pa.int32(), False, spec)
    assert lc.arrow_bytes(_table("t", 1000, (nullable,))) == 4 * 1000 + 125
    assert lc.arrow_bytes(_table("t", 1000, (clean,))) == 4 * 1000
    assert lc.arrow_bytes(_table("t", 1000, (_str("s", 10.0, nulls=True),))) == 14_000 + 125


# --- AT-E1-26 ----------------------------------------------------------------------------


def _fw(*cols: lc.ColumnInputs, ints: tuple[str, ...] = (), rows: int = 1000) -> lc.TableInputs:
    return _table("t", rows, cols, target=lc.TargetInputs("fixed_width", frozenset(ints)))


def test_fixed_width_write_takes_the_larger_of_the_two_moments() -> None:
    table = _fw(_str("s", 10.0), _int("n"), ints=("n",))  # n is already an integer column
    frame = 1000 * 67 + 8_000
    refs = 8_000 + 8_000
    lists = 8_000 + 1000 * (8 + INT_OBJ)  # string: slot only; int: slot plus an int object
    assert lc.refs_bytes(table) == refs
    assert lc.lists_bytes(table) == lists
    assert lc.int_columns(table) == ()
    assert lc.coerce_moment(table) == frame + refs
    assert lc.list_moment(table) == frame + lists
    arrow = 14_000 + 8_000
    expected = INTERCEPT + arrow + arrow + max(frame + refs, frame + lists)
    assert _phase(_peak((table,)), "write") == expected
    # Not the summed form and not the frame alone.
    assert expected != INTERCEPT + 2 * arrow + frame + refs + lists
    assert expected != INTERCEPT + 2 * arrow + frame


def test_a_csv_target_of_the_same_table_adds_the_frame_only() -> None:
    table = _table("t", 1000, (_str("s", 10.0), _int("n")), target=lc.TargetInputs("csv"))
    arrow = 14_000 + 8_000
    assert _phase(_peak((table,)), "write") == INTERCEPT + 2 * arrow + (1000 * 67 + 8_000)


# --- AT-E1-28 ----------------------------------------------------------------------------


def test_an_int_declared_string_column_adds_the_coerce_terms() -> None:
    # A CSV-sourced string column the target layout types `int`.
    table = _fw(_str("id", 6.0), _str("name", 10.0), ints=("id",))
    frame = 1000 * 63 + 1000 * 67
    refs = 16_000
    coerce = 1000 * (8 + INT_OBJ + 9)
    converted = 1000 * (9 - 8)
    assert [c.name for c in lc.int_columns(table)] == ["id"]
    assert lc.converted_bytes(table) == converted
    assert lc.coerce_moment(table) == frame + refs + converted + coerce
    # `lists` prices the column as an int object per cell, not as its string spec.
    assert lc.lists_bytes(table) == 1000 * (8 + INT_OBJ) + 8_000
    assert lc.list_moment(table) == frame + 1000 * (8 + INT_OBJ) + 8_000


def test_an_integer_typed_column_adds_no_coerce_term() -> None:
    table = _fw(_int("n"), ints=("n",))
    assert lc.int_columns(table) == ()
    assert lc.converted_bytes(table) == 0
    assert lc.coerce_moment(table) == 8_000 + 8_000


def test_two_int_declared_columns_add_converted_for_both_and_coerce_for_one() -> None:
    table = _fw(_str("a", 6.0), _str("b", 6.0), ints=("a", "b"))
    frame = 2 * 1000 * 63
    refs = 16_000
    coerce_largest = 1000 * (8 + INT_OBJ + 9)
    converted_both = 2 * 1000 * (9 - 8)
    assert lc.coerce_moment(table) == frame + refs + converted_both + coerce_largest


def test_a_float_column_declared_int_is_coerced_too() -> None:
    column = lc.ColumnInputs("f", pa.float64(), False, ColumnSizeSpec("f", "float64"))
    table = _fw(column, ints=("f",))
    assert [c.name for c in lc.int_columns(table)] == ["f"]
    assert lc.converted_bytes(table) == 1000 * (9 - 8)


# --- AT-E1-21 (the notes block) ----------------------------------------------------------


def test_the_note_constants_are_pinned() -> None:
    assert {
        "row counts estimated from file size",
        "lifecycle not priced: sample of table {table} not readable ({error})",
        "lifecycle not priced: source {table} is not a local file",
        "lifecycle not priced: source {table} has a format with no rule",
        "lifecycle not priced: target {table} has a format with no rule",
        "lifecycle not priced: layout of target {table} not readable",
        "lifecycle not priced ({error})",
    } == lc.NOTE_SHAPES


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("row counts estimated from file size", True),
        ("lifecycle not priced: source t has a format with no rule", True),
        ("lifecycle not priced (RuntimeError)", True),
        ("lifecycle not priced: because", False),
        ("anything else", False),
    ],
)
def test_note_shape_matcher(note: str, expected: bool) -> None:
    assert lc.note_matches_shape(note) is expected
