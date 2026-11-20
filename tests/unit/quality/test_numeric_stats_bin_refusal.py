"""numpy refusing a bin count for the range must not crash a snapshot (row 24f).

`np.histogram` raises "Too many bins for data range" for a narrow column at large magnitude and
for mixed-sign cells at +-1e308. `numeric_stats` writes the most bins numpy accepts instead.
"""

from __future__ import annotations

import json
import math
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from decoy_engine.internal.pandas_compat import histogram_for_range
from decoy_engine.profiling import distribution_snapshot_document
from decoy_engine.quality import snapshot as snapshot_module
from decoy_engine.quality.snapshot import compute_distribution_snapshot, numeric_stats

_NARROW = pd.Series(1e15 + np.random.default_rng(0).normal(0, 1, 2000))
_WIDE = pd.Series([1e308, -1e308] * 5)


def _refused(series: pd.Series, bins: int) -> bool:
    values = series.to_numpy(dtype=float)
    try:
        with np.errstate(all="ignore"):
            np.histogram(values, bins=bins, range=(values.min(), values.max()))
    except (ValueError, IndexError):
        return True
    return False


@pytest.mark.parametrize("series", [_NARROW, _WIDE], ids=["narrow-1e15", "wide-1e308"])
def test_the_repro_columns_are_refused_by_numpy_at_1000_bins(series: pd.Series) -> None:
    assert _refused(series, 1000)


@pytest.mark.parametrize("series", [_NARROW, _WIDE], ids=["narrow-1e15", "wide-1e308"])
def test_numeric_stats_falls_back_to_fewer_bins(series: pd.Series) -> None:
    stats = numeric_stats(series, bins=1000)
    counts, edges = stats["bin_counts"], stats["bin_edges"]
    assert 1 <= len(counts) < 1000 and len(edges) == len(counts) + 1
    assert sum(counts) == len(series)
    assert all(math.isfinite(e) for e in edges)
    # One more bin than written is refused, so the count written is the most numpy accepts.
    if len(counts) > 1:
        assert _refused(series, len(counts) + 1) or len(counts) + 1 >= 1000


@pytest.mark.parametrize("series", [_NARROW, _WIDE], ids=["narrow-1e15", "wide-1e308"])
def test_the_raw_snapshot_does_not_crash(series: pd.Series) -> None:
    df = pd.DataFrame({"x": series})
    raw = compute_distribution_snapshot(df, numeric_bins=1000)
    assert sum(raw["columns"]["x"]["stats"]["bin_counts"]) == len(df)


@pytest.mark.parametrize("include_values", [True, False])
def test_the_fit_document_does_not_crash_on_a_narrow_column(include_values: bool) -> None:
    df = pd.DataFrame({"x": _NARROW})
    with mock.patch(
        "decoy_engine.profiling._snapshot_values.value_sensitive_names", return_value=[]
    ):
        doc: dict[str, Any] = json.loads(
            json.dumps(
                distribution_snapshot_document(df, numeric_bins=1000, include_values=include_values)
            )
        )
    assert "x" in doc["columns"]


def test_an_accepted_bin_count_is_used_unchanged() -> None:
    values = np.arange(100, dtype=float)
    counts, edges = histogram_for_range(values, 10, 0.0, 99.0)
    assert len(counts) == 10 and len(edges) == 11


def test_the_helper_is_what_numeric_stats_calls() -> None:
    with mock.patch.object(
        snapshot_module, "histogram_for_range", wraps=histogram_for_range
    ) as spy:
        numeric_stats(pd.Series([1.0, 2.0, 3.0]), bins=2)
    spy.assert_called_once()
