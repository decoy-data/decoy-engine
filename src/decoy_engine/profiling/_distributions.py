"""Per-column distribution builders for the column profiler (F11c split).

Build the small Distribution summaries (numeric bins, decade bins, top-k
categorical, detector match-rate, freetext length buckets) shown per column.
Self-contained; imported back into profiler.py via _build_distribution.
"""

from __future__ import annotations

import math
from decimal import Decimal
from itertools import pairwise
from typing import Final

import numpy as np
import pandas as pd

from decoy_engine.detection.types import DetectorMatch
from decoy_engine.profiling.types import Distribution

# Cardinality threshold for "categorical" object columns. Below this we group
# by value and show top-10 + other; above it we treat the column as freetext
# or pattern-shaped depending on whether a detector fired. Deliberately
# independent of quality/snapshot.py's fit-time CATEGORICAL_DISTINCT_CAP
# (HC-5 D4): this is a profiler-chart display concern, not the fit source of
# truth, so it is not imported from there even though the value matches.
_PROFILE_CATEGORICAL_DISTINCT_CAP = 30
# A categorical share is rounded to 0.1 percent, so the true share is within this many percent
# of it. A plain profile document reads it as the margin when it bounds a label's row count.
SHARE_ROUNDING_MARGIN: Final = Decimal("0.05")
# The categorical chart keeps this many labels and sums the rest under `OTHER_LABEL`.
CATEGORICAL_TOP_LABELS: Final = 10
OTHER_LABEL: Final = "other"
# The four length buckets a free-text distribution is labelled with, in order.
FREETEXT_BUCKET_LABELS: Final = ("<20", "20-50", "50-100", ">100")


def _edge_label(left: float, right: float) -> str:
    """Label one bin: whole numbers when it spans more than 1 unit, else two decimals."""
    if not (math.isfinite(left) and math.isfinite(right)):
        # pd.cut widens the range, so an edge can pass float max and has no int form.
        return f"{left:.6g}-{right:.6g}"
    if (right - left) >= 1:
        return f"{int(left)}-{int(right)}"
    return f"{left:.2f}-{right:.2f}"


def _bin_counts_and_labels(series: pd.Series) -> tuple[list[int], list[str]]:
    """The same 10 equal-width bins as `pd.cut`, labelled without its edge rounding."""
    codes, edges = pd.cut(series, bins=10, include_lowest=True, labels=False, retbins=True)
    counts = np.bincount(codes.to_numpy(dtype=int), minlength=len(edges) - 1).tolist()
    # A tiny edge rounds to zero here instead of overflowing.
    rounded = [float(np.round(e, 3)) for e in edges]
    return counts, [_edge_label(lo, hi) for lo, hi in pairwise(rounded)]


def _distribution_numeric(non_null: pd.Series) -> Distribution | None:
    """10 equal-width bins between min and max, with counts + min/max/mean."""
    series = pd.to_numeric(non_null, errors="coerce").dropna()
    series = series[np.isfinite(series.to_numpy(dtype=float))]  # pd.cut rejects inf
    if len(series) == 0:
        return None
    # When all values are identical pd.cut errors on zero range - fall back to
    # a single-bin histogram so the renderer still has something to show.
    if series.min() == series.max():
        return Distribution(
            kind="numeric",
            data=[float(len(series))],
            labels=[str(series.iloc[0])],
            min=str(series.min()),
            max=str(series.max()),
            mean=round(float(series.mean()), 4),
        )
    try:
        binned = pd.cut(series, bins=10, include_lowest=True)
    except ValueError:
        # pd.cut's label builder rounds an edge near the float floor (a subnormal max) to a
        # non-finite value and refuses a legal column. Chart it from codes and edges instead.
        data, labels = _bin_counts_and_labels(series)
    else:
        bin_counts = binned.value_counts().sort_index()
        data = [int(c) for c in bin_counts.values]
        labels = [_edge_label(iv.left, iv.right) for iv in bin_counts.index]
    return Distribution(
        kind="numeric",
        data=[float(d) for d in data],
        labels=labels,
        min=str(series.min()),
        max=str(series.max()),
        mean=round(float(series.mean()), 4),
    )


def _distribution_date(non_null: pd.Series) -> Distribution | None:
    """Decade bins on parsed date values."""
    coerced = pd.to_datetime(non_null, errors="coerce").dropna()
    if len(coerced) == 0:
        return None
    decades = (coerced.dt.year // 10) * 10
    by_decade = decades.value_counts().sort_index()
    return Distribution(
        kind="date",
        data=[float(c) for c in by_decade.values],
        labels=[f"{int(d)}s" for d in by_decade.index],
        min=coerced.min().date().isoformat(),
        max=coerced.max().date().isoformat(),
    )


def _distribution_categorical(non_null: pd.Series, total_rows: int) -> Distribution | None:
    """Top-10 + 'other' as percent of column."""
    if total_rows == 0 or len(non_null) == 0:
        return None
    vc = non_null.value_counts()
    top = vc.head(CATEGORICAL_TOP_LABELS)
    other = int(vc.iloc[CATEGORICAL_TOP_LABELS:].sum()) if len(vc) > CATEGORICAL_TOP_LABELS else 0
    data = [round(float(c) / total_rows * 100, 1) for c in top.values]
    labels = [str(v) for v in top.index]
    if other > 0:
        data.append(round(other / total_rows * 100, 1))
        labels.append(OTHER_LABEL)
    return Distribution(kind="categorical", data=data, labels=labels)


def _distribution_pattern(non_null: pd.Series, winning: DetectorMatch) -> Distribution:
    """3 buckets for detector-fired columns: matches / no-match / null is 0
    here because we operate on non_null. Reported as pct of non-null."""
    n = len(non_null)
    matches = round(winning.match_rate * 100, 1)
    miss = round(100.0 - matches, 1) if matches < 100.0 else 0.0
    return Distribution(
        kind="pattern",
        data=[matches, miss],
        labels=[f"matches {winning.detector_id}", "doesn't match"],
        min=None,
        max=str(n),
    )


def _distribution_freetext(non_null: pd.Series) -> Distribution | None:
    """Length buckets <20 / 20-50 / 50-100 / >100 chars."""
    if len(non_null) == 0:
        return None
    lens = non_null.astype(str).str.len()
    counts = [
        int((lens < 20).sum()),
        int(((lens >= 20) & (lens < 50)).sum()),
        int(((lens >= 50) & (lens < 100)).sum()),
        int((lens >= 100).sum()),
    ]
    return Distribution(
        kind="freetext",
        data=[float(c) for c in counts],
        labels=list(FREETEXT_BUCKET_LABELS),
        min=str(int(lens.min())),
        max=str(int(lens.max())),
        mean=round(float(lens.mean()), 1),
    )


def _build_distribution(
    series: pd.Series,
    inferred_type: str,
    detector_matches: list[DetectorMatch],
    distinct_count: int,
    total_rows: int,
) -> Distribution | None:
    """Pick a distribution shape based on dtype + cardinality + detector hits."""
    non_null = series.dropna()
    if len(non_null) == 0:
        return None

    if inferred_type in ("integer", "float"):
        return _distribution_numeric(non_null)

    # Native datetime columns map directly to date bins.
    if inferred_type == "date":
        return _distribution_date(non_null)

    if inferred_type == "string":
        # Categorical when low cardinality regardless of detector - value-set is
        # the most useful summary at that scale.
        if distinct_count > 0 and distinct_count <= _PROFILE_CATEGORICAL_DISTINCT_CAP:
            return _distribution_categorical(non_null, total_rows)
        # If a detector fired, surface match-rate buckets; the user wants to
        # see "97.8% of values look like SSN" at a glance.
        if detector_matches:
            return _distribution_pattern(non_null, detector_matches[0])
        # Otherwise the column is high-cardinality free-form text.
        return _distribution_freetext(non_null)

    return None
