"""Truth table for the shared Arrow text-type predicates (DUP-DEFECTS A15, AT-E3-4)."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine._arrow_types import is_text, is_text_or_null, narrow_text

_TABLE = [
    (pa.string(), True, True),
    (pa.large_string(), True, True),
    (pa.null(), False, True),
    (pa.binary(), False, False),
    (pa.large_binary(), False, False),
    (pa.int64(), False, False),
    (pa.dictionary(pa.int32(), pa.string()), False, False),
]


@pytest.mark.parametrize(("typ", "text", "text_or_null"), _TABLE, ids=lambda v: str(v))
def test_text_predicates_truth_table(typ: pa.DataType, text: bool, text_or_null: bool) -> None:
    assert is_text(typ) is text
    assert is_text_or_null(typ) is text_or_null


# --- LARGE-STRING-FAST: narrow_text ----------------------------------------------------------


def test_narrow_text_returns_a_string_array_unchanged() -> None:
    arr = pa.array(["a", None])
    assert narrow_text(arr) is arr


def test_narrow_text_casts_large_string_keeping_values_nulls_and_slices() -> None:
    arr = pa.array(["abc", None, "", "é😀", "z"], type=pa.large_string())
    for src in (arr, arr.slice(1, 3)):
        out = narrow_text(src)
        assert out.type == pa.string()
        assert out.to_pylist() == src.to_pylist()


@pytest.mark.parametrize(
    "typ",
    [pa.binary(), pa.int64(), pa.null(), pa.dictionary(pa.int32(), pa.string())],
    ids=str,
)
def test_narrow_text_rejects_non_text(typ: pa.DataType) -> None:
    with pytest.raises(TypeError):
        narrow_text(pa.nulls(1, typ))


# --- F24 84-E1: the shared Arrow column byte helper ----------------------------------------


def _base_head_floor(arrow_type: pa.DataType, rows: int) -> int:
    # The rule `generation/_bounds.py` held before it became this helper.
    try:
        bit_width = arrow_type.bit_width
    except ValueError:
        return 4 * rows
    return (rows * bit_width + 7) // 8


@pytest.mark.parametrize(
    "arrow_type",
    [
        pa.bool_(),
        pa.int8(),
        pa.int16(),
        pa.int32(),
        pa.int64(),
        pa.float32(),
        pa.float64(),
        pa.string(),
        pa.large_string(),
        pa.timestamp("us"),
        pa.date32(),
    ],
)
@pytest.mark.parametrize("rows", [0, 1, 7, 8, 9, 1000])
def test_arrow_column_bytes_with_no_payload_matches_the_generation_floor_rule(
    arrow_type: pa.DataType, rows: int
) -> None:
    from decoy_engine._arrow_types import arrow_column_bytes

    assert arrow_column_bytes(arrow_type, rows, 0) == _base_head_floor(arrow_type, rows)


def test_arrow_column_bytes_adds_the_string_payload() -> None:
    from decoy_engine._arrow_types import arrow_column_bytes

    assert arrow_column_bytes(pa.string(), 1000, 10.0) == 14_000
    assert arrow_column_bytes(pa.bool_(), 9, 10.0) == 2
