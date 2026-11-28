"""S1k P3 and P3b: float rendering and the float64 mirror of the oracle's arithmetic.

The oracle is pandas and NumPy at the locked versions: ``Series.astype(str)`` for labels and
``np.floor(nums / w) * w`` for the bucket. The kernel must match both bit for bit.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from decoy_engine.kernel import bucketize_array, floor_multiple, python_float_str

INF = math.inf


def _seeded_doubles(rng: np.random.Generator, count: int) -> np.ndarray:
    raw = rng.integers(0, 2**64, size=count // 4, dtype=np.uint64).view(np.float64)
    raw = raw[np.isfinite(raw)]
    uniform = rng.uniform(-1e6, 1e6, size=count // 4)
    normal = rng.normal(0.0, 1e3, size=count // 4)
    integral = np.floor(rng.uniform(-1e18, 1e18, size=count // 4))
    return np.concatenate([raw, uniform, normal, integral])


def test_float_strings_match_pandas_on_one_million_doubles() -> None:
    rng = np.random.default_rng(20261124)
    values = _seeded_doubles(rng, 1_000_000)
    edge = np.array(
        [
            0.0,
            -0.0,
            INF,
            -INF,
            5e-324,
            -5e-324,
            0.1 + 0.2,
            2.0**53,
            -(2.0**53),
            1e15,
            1e16,
            1e-4,
            1e-5,
        ]
    )
    values = np.concatenate([values, edge])
    got = python_float_str(pa.array(values)).to_pylist()
    want = pd.Series(values).astype(str).tolist()
    assert got == want


def test_float_string_notation_boundaries() -> None:
    array = pa.array([1e15, 1e16, 1e-4, 1e-5, 0.1 + 0.2, -0.0, INF, -INF, 5e-324])
    assert python_float_str(array).to_pylist() == [
        "1000000000000000.0",
        "1e+16",
        "0.0001",
        "1e-05",
        "0.30000000000000004",
        "-0.0",
        "inf",
        "-inf",
        "5e-324",
    ]


def test_float_string_keeps_null_and_prints_nan_as_a_present_float() -> None:
    out = python_float_str(pa.array([math.nan, None, 1.5]))
    assert out.type == pa.string()
    assert out.to_pylist() == ["nan", None, "1.5"]
    assert python_float_str(pa.chunked_array([[1.0], [2.5]])).to_pylist() == ["1.0", "2.5"]


def test_a_raw_arrow_cast_is_not_the_oracle_rendering() -> None:
    # Guard for the test itself: Arrow's own cast disagrees with pandas on notation, so
    # substituting it for python_float_str is detectable.
    array = pa.array([1e16, 1e-5])
    assert pc.cast(array, pa.string()).to_pylist() != python_float_str(array).to_pylist()


WIDTHS: list[int | float] = [1, 3, 7, 10, 1000, 2.5, 0.1]


def _bits(array: pa.Array) -> np.ndarray:
    return np.asarray(array.to_numpy(zero_copy_only=False), dtype=np.float64)


def _assert_bit_equal(got: np.ndarray, want: np.ndarray) -> None:
    both_nan = np.isnan(got) & np.isnan(want)
    assert np.array_equal(got.view(np.uint64)[~both_nan], want.view(np.uint64)[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(want))


@pytest.mark.parametrize("width", WIDTHS)
def test_floor_multiple_is_bit_equal_to_numpy_on_int64(width: int | float) -> None:
    rng = np.random.default_rng(7)
    ints = np.concatenate(
        [
            rng.integers(-(2**63), 2**63 - 1, size=200_000, dtype=np.int64),
            rng.integers(-(2**53), 2**53, size=200_000, dtype=np.int64),
        ]
    )
    as_float = pc.cast(pa.array(ints), pa.float64(), safe=False)
    want_source = ints.astype(np.float64)
    _assert_bit_equal(_bits(as_float), want_source)
    got = _bits(floor_multiple(as_float, width))
    _assert_bit_equal(got, np.floor(want_source / width) * width)


@pytest.mark.parametrize("width", WIDTHS)
def test_floor_multiple_is_bit_equal_to_numpy_on_doubles(width: int | float) -> None:
    rng = np.random.default_rng(11)
    values = _seeded_doubles(rng, 600_000)
    got = _bits(floor_multiple(pa.array(values), width))
    with np.errstate(over="ignore"):
        want = np.floor(values / width) * width
    _assert_bit_equal(got, want)


def test_floor_multiple_distinguishes_floor_from_truncation() -> None:
    got = _bits(floor_multiple(pa.array([-0.5, -15.0, 15.5]), 10))
    assert got.tolist() == [-10.0, -20.0, 10.0]


@pytest.mark.parametrize("fmt", ["lower", "range", "midpoint"])
@pytest.mark.parametrize("width", [10, 7, 2.5, 0.1])
def test_end_to_end_labels_match_the_handler_arithmetic(fmt: str, width: int | float) -> None:
    rng = np.random.default_rng(3)
    values = np.concatenate(
        [rng.uniform(-5e3, 5e3, size=2_000), np.arange(-30, 30, dtype=np.float64)]
    )
    result = bucketize_array(pa.array(values), width, fmt)
    lf = np.floor(values / width) * width
    if isinstance(width, int):
        lower = lf.astype(np.int64)
        if fmt == "lower":
            want = [str(v) for v in lower]
        elif fmt == "range":
            want = [f"{v}-{v + width - 1}" for v in lower]
        elif width % 2 == 0:
            want = [str(int(v)) for v in lf + width / 2]
        else:
            want = [str(float(v)) for v in lf + width / 2]
    elif fmt == "lower":
        want = [str(float(v)) for v in lf]
    elif fmt == "range":
        want = [f"{float(v)}-{float(v + width)}" for v in lf]
    else:
        want = [str(float(v)) for v in lf + width / 2]
    assert result.labels.to_pylist() == want
    assert result.exit_positions.to_pylist() == []
