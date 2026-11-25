"""S1a: the one vector exit mask for an integer-width bucketize column."""

from __future__ import annotations

import math

import pyarrow as pa
import pytest

from decoy_engine.kernel import integer_width_exit_mask

INF = math.inf
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
