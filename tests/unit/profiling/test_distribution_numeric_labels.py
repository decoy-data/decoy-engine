"""The profiler's 10-bin numeric chart keeps its labels and survives edges near the float floor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from decoy_engine.profiling import profile_columns
from decoy_engine.profiling._distributions import _distribution_numeric


def test_wide_range_labels_are_whole_numbers_with_empty_bins_kept() -> None:
    dist = _distribution_numeric(pd.Series([0, 1, 2, 98, 99, 100]))
    assert dist is not None
    assert len(dist.labels) == 10 and dist.data[0] == 3.0 and dist.data[-1] == 3.0
    assert sum(dist.data) == 6.0 and dist.data[4] == 0.0
    assert all("." not in label for label in dist.labels)


def test_narrow_range_labels_use_two_decimals() -> None:
    dist = _distribution_numeric(pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert dist is not None and sum(dist.data) == 4.0
    assert all(label.count(".") == 2 for label in dist.labels)


def test_a_subnormal_maximum_is_charted() -> None:
    dist = _distribution_numeric(pd.Series([2.2250738585e-313] * 2 + [0.0] * 17 + [-1.0]))
    assert dist is not None and sum(dist.data) == 20.0 and len(dist.labels) == 10


def test_a_subnormal_only_range_is_charted_not_returned_empty() -> None:
    cells = [-3.58244534e-316, -2e-316, -1e-316, 0.0, 1e-316, 2.43941943e-316] * 32
    dist = _distribution_numeric(pd.Series(cells))
    assert dist is not None and len(dist.labels) == 10 and sum(dist.data) == 192.0
    assert len(profile_columns(pd.DataFrame({"x": cells}), "t").fields) == 1


_MAX = float(np.finfo(float).max)


@pytest.mark.parametrize(
    "cells",
    [[-_MAX, 0.0, _MAX], [1e308, 1.79e308], [-1.79e308, -1e308]],
)
def test_float_max_ranges_chart_ten_finite_bins(cells: list[float]) -> None:
    dist = _distribution_numeric(pd.Series(cells))
    assert dist is not None and len(dist.labels) == 10 and sum(dist.data) == len(cells)
    assert not any("nan" in label or "inf" in label for label in dist.labels)


def test_fallback_counts_match_pd_cut_right_closed() -> None:
    from decoy_engine.internal.pandas_compat import histogram_for_range

    values = np.arange(11.0)
    expected = pd.cut(pd.Series(values), bins=10, include_lowest=True).value_counts().sort_index()
    counts, _ = histogram_for_range(values, 10, 0.0, 10.0, right_closed=True)
    assert list(counts) == [int(c) for c in expected.values] == [2, 1, 1, 1, 1, 1, 1, 1, 1, 1]
