"""The profiler's 10-bin numeric chart keeps its labels and survives edges near the float floor."""

from __future__ import annotations

import pandas as pd

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
