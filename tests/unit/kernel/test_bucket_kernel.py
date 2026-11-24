"""S1a and S1k: the exit mask, the bucketize array operator and the top_code array operator.

Every expected label is an independent literal worked out by hand, not read from the code under test.
"""

from __future__ import annotations

import math

import pyarrow as pa
import pytest

from decoy_engine.kernel import (
    SparseLabels,
    bucketize_array,
    integer_width_exit_mask,
    top_code_array,
)

INF = math.inf
TWO53 = 2**53
# value, expected exit. B2: finite magnitude at or above 2**53. B3: either infinity.
# Arrow null and a valid NaN are never an exit.
CASES: list[tuple[float | None, bool]] = [
    (None, False),
    (math.nan, False),
    (0.0, False),
    (-0.0, False),
    (1.0, False),
    (9007199254740991.0, False),
    (-9007199254740991.0, False),
    (9007199254740992.0, True),
    (-9007199254740992.0, True),
    (9007199254740994.0, True),
    (1e19, True),
    (-1e300, True),
    (INF, True),
    (-INF, True),
]


def test_exit_mask_positions() -> None:
    mask = integer_width_exit_mask(pa.array([v for v, _ in CASES], type=pa.float64()))
    assert mask.type == pa.bool_()
    assert mask.null_count == 0
    assert mask.to_pylist() == [want for _, want in CASES]


def test_exit_mask_accepts_chunked_input() -> None:
    values = [v for v, _ in CASES]
    chunked = pa.chunked_array([values[:5], values[5:]], type=pa.float64())
    assert integer_width_exit_mask(chunked).to_pylist() == [want for _, want in CASES]


def test_exit_mask_empty() -> None:
    assert integer_width_exit_mask(pa.array([], type=pa.float64())).to_pylist() == []


@pytest.mark.parametrize("bad", [9007199254740992.0, INF, -INF])
def test_each_trigger_fires_alone(bad: float) -> None:
    mask = integer_width_exit_mask(pa.array([1.0, bad, 2.0], type=pa.float64()))
    assert mask.to_pylist() == [False, True, False]


def _labels(result_labels: pa.Array) -> list[str | None]:
    assert result_labels.type == pa.string()
    return result_labels.to_pylist()


# P1: (arrow type, values, width, {format: expected labels}). Hand-worked.
P1_CASES: list[
    tuple[pa.DataType, list[float | int | None], int | float, dict[str, list[str | None]]]
] = [
    (
        pa.int64(),
        [-15, 0, 5, 15, 25, 99, -1, -10, None],
        10,
        {
            "lower": ["-20", "0", "0", "10", "20", "90", "-10", "-10", None],
            "range": ["-20--11", "0-9", "0-9", "10-19", "20-29", "90-99", "-10--1", "-10--1", None],
            "midpoint": ["-15", "5", "5", "15", "25", "95", "-5", "-5", None],
        },
    ),
    (
        pa.int32(),
        [-15, 0, 5, 15, 25, 99],
        7,
        {
            "lower": ["-21", "0", "0", "14", "21", "98"],
            "range": ["-21--15", "0-6", "0-6", "14-20", "21-27", "98-104"],
            "midpoint": ["-17.5", "3.5", "3.5", "17.5", "24.5", "101.5"],
        },
    ),
    (
        pa.int8(),
        [-2, 0, 3],
        1,
        {
            "lower": ["-2", "0", "3"],
            "range": ["-2--2", "0-0", "3-3"],
            "midpoint": ["-1.5", "0.5", "3.5"],
        },
    ),
    (
        pa.uint32(),
        [0, 4294967295],
        10,
        {
            "lower": ["0", "4294967290"],
            "range": ["0-9", "4294967290-4294967299"],
            "midpoint": ["5", "4294967295"],
        },
    ),
    (
        pa.int64(),
        [0, 20, 7, -1, 6],
        2.5,
        {
            "lower": ["0.0", "20.0", "5.0", "-2.5", "5.0"],
            "range": ["0.0-2.5", "20.0-22.5", "5.0-7.5", "-2.5-0.0", "5.0-7.5"],
            "midpoint": ["1.25", "21.25", "6.25", "-1.25", "6.25"],
        },
    ),
    (
        pa.float64(),
        [15.5, -0.5, 99.9, -0.0, None],
        10,
        {
            "lower": ["10", "-10", "90", "0", None],
            "range": ["10-19", "-10--1", "90-99", "0-9", None],
            "midpoint": ["15", "-5", "95", "5", None],
        },
    ),
    (
        pa.float64(),
        [15.5, -0.5, 99.9],
        2.5,
        {
            "lower": ["15.0", "-2.5", "97.5"],
            "range": ["15.0-17.5", "-2.5-0.0", "97.5-100.0"],
            "midpoint": ["16.25", "-1.25", "98.75"],
        },
    ),
    (
        pa.float64(),
        [INF, -INF],
        2.5,
        {
            "lower": ["inf", "-inf"],
            "range": ["inf-inf", "-inf--inf"],
            "midpoint": ["inf", "-inf"],
        },
    ),
]


@pytest.mark.parametrize(("arrow_type", "values", "width", "expected"), P1_CASES)
def test_bucketize_labels_for_each_source_width_and_format(
    arrow_type: pa.DataType,
    values: list[float | int | None],
    width: int | float,
    expected: dict[str, list[str | None]],
) -> None:
    array = pa.array(values, type=arrow_type)
    for fmt, want in expected.items():
        result = bucketize_array(array, width, fmt)
        assert _labels(result.labels) == want, fmt
        assert result.exit_positions.to_pylist() == []


def test_bucketize_label_follows_the_width_type_not_the_source_type() -> None:
    # integer width over a float source prints integers; float width over an integer source
    # prints floats. Reading the source type instead would swap these.
    assert _labels(bucketize_array(pa.array([20.0]), 10, "lower").labels) == ["20"]
    assert _labels(bucketize_array(pa.array([20], pa.int64()), 2.5, "lower").labels) == ["20.0"]


def test_bucketize_nan_and_null_are_missing_by_default() -> None:
    array = pa.array([math.nan, None, 15.0], type=pa.float64())
    assert _labels(bucketize_array(array, 10, "lower").labels) == [None, None, "10"]
    assert _labels(bucketize_array(array, 2.5, "range").labels) == [None, None, "15.0-17.5"]


def test_bucketize_accepts_chunked_input_and_empty_input() -> None:
    chunked = pa.chunked_array([[1, 12], [25]], type=pa.int64())
    assert _labels(bucketize_array(chunked, 10, "lower").labels) == ["0", "10", "20"]
    assert _labels(bucketize_array(pa.array([], pa.int64()), 10, "lower").labels) == []


def test_bucketize_rejects_types_outside_the_numeric_domain() -> None:
    for bad in (pa.float32(), pa.uint64(), pa.string(), pa.bool_()):
        with pytest.raises(TypeError):
            bucketize_array(pa.nulls(1, bad), 10, "lower")


def test_bucketize_rejects_an_integer_width_at_or_past_the_exact_bound() -> None:
    with pytest.raises(ValueError, match="width"):
        bucketize_array(pa.array([1.0]), 2**53, "lower")


# P2: values immediately around the 2**53 limit and the int64 ends, independent literals.
def test_integer_width_exits_are_null_and_positioned() -> None:
    array = pa.array(
        [15.0, float(TWO53), 25.0, INF, math.nan, 1e19, -INF, -float(TWO53), 35.0, None],
        type=pa.float64(),
    )
    result = bucketize_array(array, 10, "range")
    assert result.exit_positions.type == pa.int64()
    assert result.exit_positions.to_pylist() == [1, 3, 5, 6, 7]
    assert _labels(result.labels) == [
        "10-19", None, "20-29", None, None, None, None, None, "30-39", None,
    ]  # fmt: skip


def test_values_just_inside_the_limit_get_labels() -> None:
    array = pa.array([9007199254740991, -9007199254740991], pa.int64())
    result = bucketize_array(array, 10, "range")
    assert result.exit_positions.to_pylist() == []
    assert _labels(result.labels) == [
        "9007199254740990-9007199254740999",
        "-9007199254741000--9007199254740991",
    ]


def test_int64_extremes_exit_under_an_integer_width_and_label_under_a_float_width() -> None:
    array = pa.array([-(2**63), 2**63 - 1, 2**62 + 7, TWO53 + 1], type=pa.int64())
    assert bucketize_array(array, 10, "lower").exit_positions.to_pylist() == [0, 1, 2, 3]
    assert bucketize_array(array, 7, "lower").exit_positions.to_pylist() == [0, 1, 2, 3]
    floats = bucketize_array(array, 2.5, "lower")
    assert floats.exit_positions.to_pylist() == []
    assert _labels(floats.labels)[3] == "9007199254740992.0"  # 2**53 + 1 rounds to 2**53


def test_float_width_never_exits() -> None:
    array = pa.array([1e19, INF, -INF, 1e300], type=pa.float64())
    result = bucketize_array(array, 2.5, "lower")
    assert result.exit_positions.to_pylist() == []
    assert _labels(result.labels)[1:3] == ["inf", "-inf"]


def test_computed_nan_is_a_present_float_not_a_null() -> None:
    # width inf: 0 * inf is NaN. The source is present, so the label is the string "nan".
    result = bucketize_array(pa.array([5.0, None]), math.inf, "lower")
    assert _labels(result.labels) == ["nan", None]


def test_exceptional_labels_replace_valid_nan_positions_only() -> None:
    array = pa.array([math.nan, 4.0, None, math.nan], type=pa.float64())
    sparse = SparseLabels(pa.array([0, 3], pa.int64()), pa.array(["nan", "x"], pa.string()))
    result = bucketize_array(array, 2.5, "lower", exceptional=sparse)
    assert _labels(result.labels) == ["nan", "2.5", None, "x"]
    assert result.exit_positions.to_pylist() == []


def test_exceptional_labels_must_sit_on_valid_nan_in_order() -> None:
    array = pa.array([math.nan, 4.0, None, math.nan], type=pa.float64())
    for positions in ([1], [2], [3, 0], [0, 0], [9]):
        sparse = SparseLabels(
            pa.array(positions, pa.int64()), pa.array(["z"] * len(positions), pa.string())
        )
        with pytest.raises(ValueError, match="exceptional"):
            bucketize_array(array, 2.5, "lower", exceptional=sparse)


# top_code: cap 89 with floor 40 and the two labels.
def test_top_code_integer_source_labels_and_counts() -> None:
    array = pa.array([10, 40, 41, 89, 90, 120, None, -5], type=pa.int64())
    result = top_code_array(array, 89, "90+", 40, "under 40")
    assert _labels(result.labels) == [
        "under 40", "40", "41", "89", "90+", "90+", None, "under 40",
    ]  # fmt: skip
    assert (result.over_count, result.under_count) == (2, 2)


def test_top_code_without_a_floor_keeps_negative_values_exact() -> None:
    array = pa.array([-9007199254740993, 89, 90], type=pa.int64())
    result = top_code_array(array, 89, "90+")
    assert _labels(result.labels) == ["-9007199254740993", "89", "90+"]
    assert (result.over_count, result.under_count) == (1, 0)


def test_top_code_equality_at_cap_and_floor_stays_in_range() -> None:
    result = top_code_array(pa.array([40, 89], pa.int32()), 89, "high", 40, "low")
    assert _labels(result.labels) == ["40", "89"]
    assert (result.over_count, result.under_count) == (0, 0)


def test_top_code_compares_exact_integers_when_both_sides_are_integers() -> None:
    # 2**53 + 1 is above a cap of 2**53 - 1; a float64 comparison would not see 2**53 + 1.
    array = pa.array([TWO53 - 1, TWO53, TWO53 + 1], type=pa.int64())
    result = top_code_array(array, TWO53 - 1, "big")
    assert _labels(result.labels) == [str(TWO53 - 1), "big", "big"]
    assert result.over_count == 2


def test_top_code_float_source_rendering() -> None:
    array = pa.array(
        [67.0, 67.5, -0.0, -INF, -1e300, -(2.0**63), 88.0, -(2.0**62), math.nan, None],
        type=pa.float64(),
    )
    result = top_code_array(array, 89, "90+")
    assert _labels(result.labels) == [
        "67",
        "67.5",
        "0",
        "-inf",
        str(int(-1e300)),
        "-9223372036854775808",
        "88",
        "-4611686018427387904",
        None,
        None,
    ]
    assert (result.over_count, result.under_count) == (0, 0)


def test_top_code_infinity_is_over_and_a_float_cap_compares_in_float() -> None:
    result = top_code_array(pa.array([INF, 89.4, 89.6]), 89.5, "over")
    assert _labels(result.labels) == ["over", "89.4", "over"]
    assert result.over_count == 2
    ints = top_code_array(pa.array([89, 90], pa.int64()), 89.5, "over")
    assert _labels(ints.labels) == ["89", "over"]


def test_top_code_exceptional_labels_and_empty_input() -> None:
    array = pa.array([math.nan, 50.0], type=pa.float64())
    sparse = SparseLabels(pa.array([0], pa.int64()), pa.array(["nan"], pa.string()))
    result = top_code_array(array, 89, "90+", exceptional=sparse)
    assert _labels(result.labels) == ["nan", "50"]
    assert (result.over_count, result.under_count) == (0, 0)
    empty = top_code_array(pa.array([], pa.int64()), 89, "90+")
    assert _labels(empty.labels) == [] and empty.over_count == 0


def test_top_code_rejects_types_outside_the_numeric_domain() -> None:
    for bad in (pa.float32(), pa.uint64(), pa.string(), pa.decimal128(5, 0)):
        with pytest.raises(TypeError):
            top_code_array(pa.nulls(1, bad), 89, "90+")
