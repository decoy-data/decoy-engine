"""Plain fit numeric histograms: no bin holds 1 to 9 rows, and `numeric_bins` has a ceiling (row 24f, E2).

Every canary test first asserts that the raw (`include_values=True`) document has the small
interior bin, so a frame that never held one cannot pass. Every released bin is recounted from the
source cells over the released edges.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from itertools import pairwise
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from decoy_engine import reasons
from decoy_engine.generation.statistical import load_spec, sample_column
from decoy_engine.profiling import MIN_RELEASE_COUNT, distribution_snapshot_document
from decoy_engine.profiling import _snapshot_values as sv
from decoy_engine.quality import MAX_NUMERIC_BINS, check_numeric_bins
from decoy_engine.quality import snapshot as snapshot_module
from decoy_engine.quality.snapshot import (
    DistributionSnapshotError,
    check_contingency_top_k,
    compute_distribution_snapshot,
)

K = MIN_RELEASE_COUNT
_SHAPES = ("quantile_grid", "exact_values")


@contextmanager
def _flagged(names: Sequence[str]) -> Iterator[None]:
    with mock.patch.object(sv, "value_sensitive_names", return_value=list(names)):
        yield


def _doc(df: pd.DataFrame, **kw: Any) -> dict[str, Any]:
    """The plain document with no column flagged, round-tripped through JSON."""
    with _flagged([]):
        doc = json.loads(json.dumps(distribution_snapshot_document(df, **kw)))
    assert not set(doc["redacted_columns"]) & set(df.columns)
    return doc


def _stats(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return doc["columns"][name]["stats"]  # type: ignore[no-any-return]


def _recount(cells: Sequence[float], stats: dict[str, Any]) -> list[int]:
    finite = np.asarray(cells, dtype=float)
    finite = finite[np.isfinite(finite)]
    edges = stats["bin_edges"]
    return np.histogram(np.clip(finite, edges[0], edges[-1]), bins=edges)[0].tolist()  # type: ignore[no-any-return]


def _swap_tails(values: np.ndarray) -> np.ndarray:
    """Replace the K-1 smallest and K-1 largest finite cells with other values beyond the K-th."""
    out = values.astype(float).copy()
    idx = np.flatnonzero(np.isfinite(out))
    order = idx[np.argsort(out[idx], kind="stable")]
    low, high = out[order[K - 1]], out[order[-K]]
    for rank, i in enumerate(order[: K - 1]):
        out[i] = low - 1e6 * (rank + 1)
    for rank, i in enumerate(order[-(K - 1) :]):
        out[i] = high + 1e6 * (rank + 1)
    return out


def _keys(doc: dict[str, Any], name: str) -> dict[str, Any]:
    stats = _stats(doc, name)
    return {k: stats[k] for k in ("min", "max", "bin_edges", "bin_counts")}


def _probe() -> pd.DataFrame:
    salary = [40000.0 + 400 * (i % 181) for i in range(500)] + [987654.0]
    return pd.DataFrame({"salary": salary})


def _has_small_bin(counts: Sequence[int]) -> bool:
    return any(0 < c < K for c in counts)


# AT-20


def test_a_quantile_grid_column_has_one_histogram_bin_at_every_n() -> None:
    df = _probe()
    raw = _stats(
        json.loads(
            json.dumps(distribution_snapshot_document(df, include_values=True, numeric_bins=1000))
        ),
        "salary",
    )
    assert _has_small_bin(raw["bin_counts"]) and "quantile_grid" in raw
    cells = df["salary"].to_numpy()
    ordered = np.sort(cells)
    a, b = ordered[K - 1], ordered[-K]
    for n in (1, 10, 17, 100, 999, 1000):
        doc = _doc(df, numeric_bins=n)
        stats = _stats(doc, "salary")
        assert len(stats["bin_edges"]) == 2 and stats["bin_counts"] == [501]
        assert _recount(cells, stats) == stats["bin_counts"]
        lo, hi = stats["bin_edges"]
        assert lo <= a and hi >= b
        assert lo <= min(stats["quantile_grid"]["values"])
        assert hi >= max(stats["quantile_grid"]["values"])
        swapped = _doc(df.assign(salary=_swap_tails(cells)), numeric_bins=n)
        assert _keys(doc, "salary") == _keys(swapped, "salary")


# AT-21


def _no_shape_frame(middle: Sequence[float]) -> pd.DataFrame:
    low = [round(0.1 * i, 1) for i in range(25)]
    high = [round(100 + 0.1 * i, 1) for i in range(25)]
    return pd.DataFrame({"x": low + list(middle) + high})


def _first_step(cells: Sequence[float], n: int) -> Decimal:
    """The largest 1, 2, 5 step at or below (b - a) / n, computed without the library."""
    ordered = sorted(cells)
    width = Decimal(repr(ordered[-K])) - Decimal(repr(ordered[K - 1]))
    width /= n
    best = Decimal(0)
    for exp in range(-6, 8):
        for m in (1, 2, 5):
            step = Decimal(m).scaleb(exp)
            if step <= width:
                best = max(best, step)
    return best


def test_a_three_row_interior_bin_is_not_released_at_the_default_n() -> None:
    df = _no_shape_frame([10.5, 20.5, 30.5, 45.0, 45.2, 45.4, 60.5, 70.5, 80.5, 90.5])
    raw = json.loads(json.dumps(distribution_snapshot_document(df, include_values=True)))
    raw_stats = _stats(raw, "x")
    assert _has_small_bin(raw_stats["bin_counts"])
    assert not any(s in raw_stats for s in _SHAPES)
    stats = _stats(_doc(df), "x")
    assert not any(s in stats for s in _SHAPES)
    assert not _has_small_bin(stats["bin_counts"])
    assert _recount(df["x"], stats) == stats["bin_counts"]
    assert sum(stats["bin_counts"]) == 60


def test_a_bin_of_exactly_k_rows_passes_at_the_first_ladder_step() -> None:
    mid = [round(50 + 0.1 * i, 1) for i in range(K)]
    df = _no_shape_frame(mid)
    raw = _stats(
        json.loads(json.dumps(distribution_snapshot_document(df, include_values=True))), "x"
    )
    assert not any(s in raw for s in _SHAPES)
    stats = _stats(_doc(df), "x")
    first = _first_step(df["x"].tolist(), 10)
    edges = [Decimal(repr(e)) for e in stats["bin_edges"]]
    assert {b - a for a, b in pairwise(edges)} == {first}
    assert K in stats["bin_counts"] and not _has_small_bin(stats["bin_counts"])
    assert _recount(df["x"], stats) == stats["bin_counts"]


def test_a_no_shape_column_near_float_max_falls_back_to_one_public_bin() -> None:
    cells = np.linspace(1e308, 1.79e308, 40)
    stats = _stats(_doc(pd.DataFrame({"x": cells}), numeric_bins=10), "x")
    assert not any(s in stats for s in _SHAPES)
    assert stats["bin_edges"] == [-1.5, 1.5] and stats["bin_counts"] == [40]


# AT-21b


def test_a_constant_core_releases_one_bin_and_a_tail_swap_moves_nothing() -> None:
    cells = np.array([10.0, 20, 30, 40, 45] + [50.0] * 30 + [55.0, 60, 70, 80, 90])
    df = pd.DataFrame({"x": cells})
    doc = _doc(df)
    stats = _stats(doc, "x")
    assert not any(s in stats for s in _SHAPES)
    assert stats["bin_counts"] == [40] and len(stats["bin_edges"]) == 2
    assert _keys(doc, "x") == _keys(_doc(df.assign(x=_swap_tails(cells))), "x")


# AT-22


def _spied(call: Any) -> tuple[Any, mock.Mock, mock.Mock]:
    with (
        mock.patch.object(snapshot_module, "numeric_stats") as stats_spy,
        mock.patch.object(sv, "profile_columns") as profile_spy,
    ):
        try:
            call()
        except DistributionSnapshotError as err:
            return err, stats_spy, profile_spy
    raise AssertionError("no refusal")


@pytest.mark.parametrize("bad", [0, -1, 1001, 100_000, 10**8, True, 10.0, "10", None])
def test_numeric_bins_outside_the_ceiling_is_refused_before_any_histogram(bad: Any) -> None:
    df = _probe()
    for call in (
        lambda: distribution_snapshot_document(df, numeric_bins=bad),
        lambda: compute_distribution_snapshot(df, numeric_bins=bad),
    ):
        err, stats_spy, profile_spy = _spied(call)
        assert err.code == reasons.quality.NUMERIC_BINS_INVALID
        assert str(MAX_NUMERIC_BINS) in str(err)
        assert "100000" not in str(err) and "987654" not in str(err)
        stats_spy.assert_not_called()
        profile_spy.assert_not_called()


@pytest.mark.parametrize("ok", [1, 1000, np.int64(17)])
def test_numeric_bins_inside_the_ceiling_is_accepted(ok: Any) -> None:
    check_numeric_bins(ok)
    assert compute_distribution_snapshot(_probe(), numeric_bins=ok)


def test_the_contingency_check_keeps_its_code_and_now_takes_numpy_ints() -> None:
    for bad in (0, 1001, True, 25.0, "25", None):
        with pytest.raises(DistributionSnapshotError) as err:
            check_contingency_top_k(bad)
        assert err.value.code == reasons.quality.CONTINGENCY_TOP_K_INVALID
    check_contingency_top_k(np.int64(25))


# AT-24

_FINITE = st.one_of(st.integers(-(10**6), 10**6), st.floats(-1e6, 1e6, allow_nan=False))
_SEEDED = settings(max_examples=60, deadline=None, suppress_health_check=list(HealthCheck))
_SPECIAL = st.sampled_from([np.nan, np.inf, -np.inf])


@st.composite
def _columns(draw: Any) -> list[float]:
    kind = draw(st.sampled_from(["no_shape", "shape", "constant", "special", "huge", "negative"]))
    if kind == "no_shape":
        n = draw(st.integers(20, 99))
        return sorted(draw(st.lists(st.floats(-1e4, 1e4), min_size=n, max_size=n, unique=True)))
    if kind == "constant":
        core = draw(st.floats(-1e3, 1e3))
        tails = draw(st.lists(st.floats(-1e5, 1e5), min_size=2 * K - 2, max_size=40))
        return [core] * draw(st.integers(2, 40)) + tails
    if kind == "special":
        cells = draw(st.lists(_FINITE, min_size=2 * K, max_size=60))
        return [float(c) for c in cells] + draw(st.lists(_SPECIAL, min_size=1, max_size=5))
    if kind == "huge":
        base = draw(st.lists(st.floats(-1e3, 1e3), min_size=K, max_size=30))
        sign = draw(st.sampled_from([1.0, -1.0]))
        # One side only: the raw snapshot cannot bin a range that spans both float extremes.
        return [sign * 1e308] * K + [sign * 1.5e308] * K + base
    if kind == "negative":
        return draw(st.lists(st.floats(-1e6, -1.0), min_size=2 * K, max_size=120))
    return [float(c) for c in draw(st.lists(_FINITE, min_size=2 * K, max_size=120))]


# A subnormal max made the profiler's own 10-bin chart raise (pd.cut rounds the edge to NaN), so the
# whole snapshot refused a legal column. Found by this property, 2026-11-21.
_SUBNORMAL_MAX = [2.2250738585e-313] * 2 + [0.0] * 17 + [-1.0]

_SUBNORMAL_ONLY = [-3.58244534e-316, -2e-316, -1e-316, 0.0, 1e-316, 2.43941943e-316] * 32


@_SEEDED
@example(cells=_SUBNORMAL_MAX, n=1)
@example(cells=_SUBNORMAL_ONLY, n=10)
@given(cells=_columns(), n=st.integers(1, 1000))
def test_property_every_plain_histogram_is_floored_recounted_and_tail_stable(
    cells: list[float], n: int
) -> None:
    arr = np.asarray(cells, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size < 2 * K:
        return
    doc = _doc(pd.DataFrame({"x": arr}), numeric_bins=n)
    stats = _stats(doc, "x")
    edges, counts = stats["bin_edges"], stats["bin_counts"]
    assert all(x < y for x, y in pairwise(edges))
    assert _recount(arr, stats) == counts
    assert sum(counts) == finite.size
    shapes = [stats[s] for s in _SHAPES if s in stats]
    if shapes:
        assert len(counts) == 1
        assert all(edges[0] <= v <= edges[-1] for s in shapes for v in s["values"])
    else:
        assert not _has_small_bin(counts)
    swapped = _doc(pd.DataFrame({"x": _swap_tails(arr)}), numeric_bins=n)
    # Whether a shape block is released depends on how often each value occurs, tails included,
    # so a swap that flips that choice is outside the histogram's guarantee.
    same_branch = any(s in _stats(swapped, "x") for s in _SHAPES) == bool(shapes)
    if edges != [-1.5, 1.5] and same_branch:
        assert _keys(doc, "x") == _keys(swapped, "x")


def test_a_subnormal_maximum_still_profiles_and_floors() -> None:
    arr = np.asarray(_SUBNORMAL_MAX)
    stats = _stats(_doc(pd.DataFrame({"x": arr}), numeric_bins=10), "x")
    assert sum(stats["bin_counts"]) == arr.size
    assert not _has_small_bin(stats["bin_counts"])
    assert _recount(arr, stats) == stats["bin_counts"]


@pytest.mark.parametrize("size", [20, 21])
def test_the_smallest_columns_that_floor_keep_the_guarantee(size: int) -> None:
    arr = np.arange(float(size)) * 3.7
    stats = _stats(_doc(pd.DataFrame({"x": arr}), numeric_bins=10), "x")
    assert not _has_small_bin(stats["bin_counts"])
    assert _recount(arr, stats) == stats["bin_counts"]


# AT-25


def test_raw_flagged_and_generation_paths_are_unchanged() -> None:
    df = _probe()
    for n in (10, 1000):
        raw = distribution_snapshot_document(df, include_values=True, numeric_bins=n)
        base = compute_distribution_snapshot(df, numeric_bins=n, cell_format=True)
        assert {
            k: v for k, v in raw.items() if k not in ("value_policy", "redacted_columns")
        } == base
    with _flagged(["salary"]):
        flagged = distribution_snapshot_document(df)
    assert len(_stats(flagged, "salary")["bin_counts"]) == 1
    doc = _doc(df)
    spec = load_spec({"name": "salary", "source_column": "salary"}, snapshot=doc)
    drawn = sample_column(spec, 2000, col_seed=11)
    raw_doc = json.loads(json.dumps(distribution_snapshot_document(df, include_values=True)))
    raw_spec = load_spec({"name": "salary", "source_column": "salary"}, snapshot=raw_doc)
    assert drawn == sample_column(raw_spec, 2000, col_seed=11)
    assert len(drawn) == 2000


# AT-26


def test_the_reason_is_registered_as_unreleased() -> None:
    spec = reasons.find("quality", "numeric_bins_invalid")
    assert spec is not None
    assert spec.owner == "DistributionSnapshotError"
    assert spec.since == reasons.UNRELEASED
    assert reasons.quality.NUMERIC_BINS_INVALID == "numeric_bins_invalid"
    from decoy_engine.reasons.quality import _part1

    assert "NUMERIC_BINS_INVALID" in _part1.__all__


# AT-27


def test_the_accepted_minimality_residual_is_pinned() -> None:
    cells = [0.0] * 10 + [100.0] * 10 + [45.0] * 6 + [55.0] * 6
    df = pd.DataFrame({"x": cells})
    raw = _stats(
        json.loads(json.dumps(distribution_snapshot_document(df, include_values=True))), "x"
    )
    assert not any(s in raw for s in _SHAPES)
    stats = _stats(_doc(df, numeric_bins=10), "x")
    assert not any(s in stats for s in _SHAPES)
    assert stats["bin_counts"] == [10, 0, 12, 0, 10]
    assert {y - x for x, y in pairwise(stats["bin_edges"])} == {20.0}


# AT-28


def test_exact_values_are_released_beside_one_bin_not_a_locating_histogram() -> None:
    cells = [float(v) for v in range(0, 100, 5) for _ in range(3 if v == 45 else 30)]
    df = pd.DataFrame({"x": cells})
    raw = _stats(
        json.loads(
            json.dumps(distribution_snapshot_document(df, include_values=True, numeric_bins=10))
        ),
        "x",
    )
    assert raw["exact_values"]["dropped_count"] == 3
    assert 33 in raw["bin_counts"]
    doc = _doc(df, numeric_bins=10)
    stats = _stats(doc, "x")
    assert stats["exact_values"] == raw["exact_values"]
    assert len(stats["bin_counts"]) == 1 and stats["bin_counts"] == [len(cells)]
    assert stats["bin_edges"][0] <= min(stats["exact_values"]["values"])
    assert stats["bin_edges"][-1] >= max(stats["exact_values"]["values"])
