"""A plain fit snapshot keeps no rare or extreme cell of a column the profiler did not flag (row 24f, E1).

Every canary test first asserts the canary is in the raw snapshot, so a frame that never held a
rare cell cannot pass. Tests that need a column the profiler would flag (or would not) say so by
patching `value_sensitive_names`; the QA frame tests use the real profiler.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from itertools import pairwise
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from decoy_engine import reasons
from decoy_engine.contracts.distribution_snapshot import SCHEMA_VERSION_V1, SCHEMA_VERSION_V2
from decoy_engine.generation.statistical import StatisticalSpecError, load_spec, sample_column
from decoy_engine.profiling import (
    MIN_RELEASE_COUNT,
    REDACTED_POLICIES,
    distribution_snapshot_document,
    snapshot_joint_warnings,
)
from decoy_engine.profiling import _snapshot_values as sv
from decoy_engine.profiling._value_redaction import POLICY_REDACTED
from decoy_engine.quality.fidelity import compute_fidelity
from decoy_engine.quality.snapshot import compute_distribution_snapshot

K = MIN_RELEASE_COUNT
_STATES = ["CA", "NY", "TX", "WA", "OR", "FL", "IL", "OH"]
_DX = ["Hypertension", "Asthma", "Diabetes", "Migraine", "Arthritis", "Anemia", "Eczema", "Gout"]
_NOTES = [f"patient Surname{i} called" for i in range(30)]


@contextmanager
def _flagged(names: Sequence[str]) -> Iterator[None]:
    with mock.patch.object(sv, "value_sensitive_names", return_value=list(names)):
        yield


def _doc(df: pd.DataFrame, *, flagged: Sequence[str] | None = None, **kw: Any) -> dict[str, Any]:
    """The plain document as a reader sees it: round-tripped through JSON."""
    if flagged is None:
        return json.loads(json.dumps(distribution_snapshot_document(df, **kw)))
    with _flagged(flagged):
        return json.loads(json.dumps(distribution_snapshot_document(df, **kw)))


def _qa_frame() -> pd.DataFrame:
    """The DI models QA frame: 1,000 rows, seed 31, one rare cell in each of four columns."""
    rng = np.random.default_rng(31)
    n = 1000
    salary = rng.integers(40, 150, n) * 1000.0
    salary[0] = 987654.0
    diagnosis = rng.choice(_DX, n).astype(object)
    diagnosis[1] = "RARE-HIV-B20"
    is_active = np.ones(n, dtype=bool)
    is_active[2] = False
    days = rng.integers(0, 3650, n)
    visit = pd.Series(pd.Timestamp("2015-01-01") + pd.to_timedelta(days, unit="D"))
    visit[3] = pd.Timestamp("1921-06-15")
    return pd.DataFrame(
        {
            "salary": salary,
            "diagnosis": diagnosis,
            "state": rng.choice(_STATES, n),
            "is_active": is_active,
            "note": [_NOTES[i % 30] for i in range(n)],
            "visit_date": visit,
        }
    )


def _col(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return doc["columns"][name]


def _tops(doc: dict[str, Any], name: str) -> dict[str, int]:
    return {t["value"]: t["count"] for t in _col(doc, name)["stats"]["top_values"]}


def _ranges(doc: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return _col(doc, name)["stats"]["year_bins"]


# AT-1


def test_the_qa_frame_columns_are_unflagged_and_the_canaries_are_raw() -> None:
    df = _qa_frame()
    raw = compute_distribution_snapshot(df)
    doc = _doc(df)
    # The profiler flags every datetime column, so the date tests below force the flagged set.
    assert doc["redacted_columns"] == ["visit_date"]
    assert _col(raw, "salary")["stats"]["max"] == 987654.0
    assert "RARE-HIV-B20" in json.dumps(raw)
    assert _col(raw, "diagnosis")["stats"]["top_values"][-1]["count"] == 1


def test_an_unflagged_numeric_max_is_not_the_one_rare_cell() -> None:
    stats = _col(_doc(_qa_frame()), "salary")["stats"]
    assert stats["max"] != 987654.0
    assert 987654.0 not in stats["bin_edges"]
    assert stats["bin_counts"][-1] >= K


def _swap_tails(values: np.ndarray) -> np.ndarray:
    """Replace the K-1 smallest and K-1 largest cells with other values beyond the K-th ones."""
    order = np.argsort(values, kind="stable")
    out = values.copy()
    low, high = values[order[K - 1]], values[order[-K]]
    for rank, i in enumerate(order[: K - 1]):
        out[i] = low - 1e6 * (rank + 1)
    for rank, i in enumerate(order[-(K - 1) :]):
        out[i] = high + 1e6 * (rank + 1)
    return out


def _numeric_keys(doc: dict[str, Any], name: str) -> dict[str, Any]:
    stats = _col(doc, name)["stats"]
    return {k: stats[k] for k in ("min", "max", "bin_edges", "bin_counts", "quantiles")}


def test_replacing_the_k_minus_one_extremes_moves_no_numeric_bound() -> None:
    df = _qa_frame()
    swapped = df.assign(salary=_swap_tails(df["salary"].to_numpy()))
    assert _numeric_keys(_doc(df), "salary") == _numeric_keys(_doc(swapped), "salary")


_SPANS = {
    "ordinary": np.arange(100.0),
    "constant": np.full(50, 5.0),
    "nonzero constant": np.full(50, 123456.789),
    "narrow below the grid floor": 5.0 + np.arange(50) * 1e-13,
    "near float max": np.repeat([1.0e308, 1.79e308], 25),
}


@pytest.mark.parametrize("label", sorted(_SPANS))
def test_every_span_writes_finite_strict_edges_and_floored_counts(label: str) -> None:
    cells = _SPANS[label]
    doc = _doc(pd.DataFrame({"x": cells}), flagged=[], numeric_bins=17)
    assert "x" not in doc["redacted_columns"]
    stats = _col(doc, "x")["stats"]
    edges = stats["bin_edges"]
    assert all(math.isfinite(e) for e in edges)
    assert all(x < y for x, y in pairwise(edges))
    # 24f withdrew "at least numeric_bins bins": every non-empty bin now holds K rows.
    assert all(c == 0 or c >= K for c in stats["bin_counts"])
    assert len(edges) == len(stats["bin_counts"]) + 1
    assert sum(stats["bin_counts"]) == len(cells)


def test_near_float_max_uses_the_fixed_public_domain_as_one_bin() -> None:
    doc = _doc(pd.DataFrame({"x": _SPANS["near float max"]}), flagged=[], numeric_bins=17)
    stats = _col(doc, "x")["stats"]
    assert (stats["min"], stats["max"]) == (-1.5, 1.5)
    assert stats["bin_edges"] == [-1.5, 1.5]
    assert stats["bin_counts"] == [50]


def test_the_end_bins_each_hold_at_least_k_rows_when_the_span_is_not_constant() -> None:
    counts = _col(_doc(pd.DataFrame({"x": np.arange(100.0)}), flagged=[]), "x")["stats"][
        "bin_counts"
    ]
    assert counts[0] >= K and counts[-1] >= K


def test_a_quantile_is_kept_only_with_k_rows_on_each_side() -> None:
    small = _doc(pd.DataFrame({"x": np.arange(20.0)}), flagged=[])
    assert set(_col(small, "x")["stats"]["quantiles"]) == {"p50"}
    mid = _doc(pd.DataFrame({"x": np.arange(100.0)}), flagged=[])
    assert set(_col(mid, "x")["stats"]["quantiles"]) == {"p25", "p50", "p75"}
    big = _doc(pd.DataFrame({"x": np.arange(400.0)}), flagged=[])
    assert len(_col(big, "x")["stats"]["quantiles"]) == 5


# AT-2


def test_a_rare_label_is_folded_into_other_count() -> None:
    df = _qa_frame()
    raw = compute_distribution_snapshot(df)
    doc = _doc(df)
    assert "RARE-HIV-B20" in {t["value"] for t in _col(raw, "diagnosis")["stats"]["top_values"]}
    assert "RARE-HIV-B20" not in json.dumps(doc)
    assert (
        _col(doc, "diagnosis")["stats"]["other_count"]
        == _col(raw, "diagnosis")["stats"]["other_count"] + 1
    )
    assert min(_tops(doc, "diagnosis").values()) >= K


def test_a_label_held_by_exactly_k_rows_stays() -> None:
    df = pd.DataFrame({"c": ["a"] * 90 + ["b"] * K})
    assert _tops(_doc(df, flagged=[]), "c") == {"a": 90, "b": K}


# AT-3


def _joint_frame() -> pd.DataFrame:
    n = 800
    state = [_STATES[i % 8] for i in range(n)]
    tier = [("low", "mid", "high")[(i % 8) % 3] for i in range(n)]
    tier[0] = "high" if tier[0] != "high" else "low"  # one row off its state's usual tier
    return pd.DataFrame({"state": state, "tier": tier})


def test_a_joint_cell_under_k_is_folded_into_other_count() -> None:
    df = _joint_frame()
    raw = compute_distribution_snapshot(df, joint_columns=[("state", "tier")])
    doc = _doc(df, flagged=[], joint_columns=[("state", "tier")])
    assert min(c["count"] for c in raw["joints"][0]["cells"]) == 1
    joint = doc["joints"][0]
    assert joint["cells"]
    assert min(c["count"] for c in joint["cells"]) >= K
    assert joint["other_count"] == raw["joints"][0]["other_count"] + 1
    assert sum(c["count"] for c in joint["cells"]) + joint["other_count"] == len(df)


def test_a_joint_of_two_bool_columns_still_folds_a_cell_under_k() -> None:
    df = pd.DataFrame({"a": [True] * 99 + [False], "b": [True] * 98 + [False, False]})
    raw = compute_distribution_snapshot(df, joint_columns=[("a", "b")])
    joint = _doc(df, flagged=[], joint_columns=[("a", "b")])["joints"][0]
    assert min(c["count"] for c in raw["joints"][0]["cells"]) == 1
    assert all(c["count"] >= K for c in joint["cells"])
    assert sum(c["count"] for c in joint["cells"]) + joint["other_count"] == len(df)
    # the one-column bool vocabulary is still kept
    assert _tops(_doc(df, flagged=[]), "a")["False"] == 1


# AT-4


def test_a_short_sentence_column_is_free_text_with_a_blank_count() -> None:
    df = _qa_frame()
    raw = compute_distribution_snapshot(df)
    doc = _doc(df)
    assert _col(raw, "note")["kind"] == "categorical"
    assert _col(raw, "note")["stats"]["top_values"]
    note = _col(doc, "note")
    assert note["kind"] == "freetext"
    assert set(note["stats"]) == {"length", "length_bin_edges", "length_bin_counts"}
    assert note["cell_format"] == {"blank_count": 0}
    assert not any(text in json.dumps(doc) for text in _NOTES)


def test_a_joint_naming_a_free_text_column_is_withheld() -> None:
    df = _qa_frame()
    df["state"] = [_STATES[(i % 30) % 8] for i in range(len(df))]  # every note-state cell holds K
    raw = compute_distribution_snapshot(df, joint_columns=[("note", "state")])
    assert min(c["count"] for c in raw["joints"][0]["cells"]) >= K
    doc = _doc(df, joint_columns=[("note", "state")])
    assert doc["joints"][0]["cells"] == []


# AT-5


def _date_frame() -> pd.DataFrame:
    """Same years three times: K-row years, no year at K, and a column the profiler flags."""
    rng = np.random.default_rng(5)
    n = 600
    years = rng.integers(2012, 2022, n)
    days = 601 + rng.integers(0, 20, n)
    full = pd.Series(pd.to_datetime(years * 10000 + days, format="%Y%m%d"))
    for i, year in enumerate((1921, 1950, 1951)):
        full[i] = pd.Timestamp(f"{year}-03-03")
    sparse = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]")
    for i, year in enumerate(range(1990, 2010)):  # 20 years, 5 rows each: none holds K
        for j in range(5):
            sparse[10 + i * 5 + j] = pd.Timestamp(f"{year}-05-05")
    return pd.DataFrame({"visit": full, "sparse": sparse, "forced": full.copy()})


def _check_ranges(doc: dict[str, Any], name: str, df: pd.DataFrame) -> None:
    years = sorted(set(df[name].dropna().dt.year))
    ranges = _ranges(doc, name)
    assert all(
        set(r) == {"start_year", "end_year", "count"} and all(type(v) is int for v in r.values())
        for r in ranges
    )
    assert all(r["count"] >= K for r in ranges)
    assert sum(r["count"] for r in ranges) == int(df[name].notna().sum())
    assert all(r["start_year"] in years and r["end_year"] in years for r in ranges)
    # Bottom and top coded: the outer edges are the years of the K-th row from each end.
    rows = sorted(df[name].dropna().dt.year)
    assert ranges[0]["start_year"] == rows[K - 1] and ranges[-1]["end_year"] == rows[-K]
    coded = [y for y in years if rows[K - 1] <= y <= rows[-K]]
    for before, after in pairwise(ranges):
        assert after["start_year"] == coded[coded.index(before["end_year"]) + 1]


def test_datetime_years_fold_into_contiguous_ranges_of_at_least_k() -> None:
    df = _date_frame()
    assert Counter(df["sparse"].dropna().dt.year).most_common(1)[0][1] < K
    assert {"year": 1921, "count": 1} in _ranges(compute_distribution_snapshot(df), "visit")
    doc = _doc(df, flagged=["forced"])
    assert doc["schema_version"] == SCHEMA_VERSION_V2
    for name in ("visit", "sparse", "forced"):
        _check_ranges(doc, name, df)
    assert doc["redacted_columns"] == ["forced", "sparse"]
    first, last = _ranges(doc, "visit")[0], _ranges(doc, "visit")[-1]
    assert first["start_year"] == 2012 and first["end_year"] >= 2012  # not the 1921 outlier
    assert "1921" not in json.dumps(doc["columns"]["visit"]["stats"])
    visit = _col(doc, "visit")["stats"]
    assert visit["min"] == "2012-01-01T00:00:00"
    assert visit["max"] == f"{last['end_year']:04d}-12-31T23:59:59.999999"


def test_a_short_last_year_is_coded_into_the_one_before_it() -> None:
    years = [2000] * 12 + [2001] * 3
    df = pd.DataFrame({"d": pd.to_datetime([f"{y}-02-02" for y in years])})
    assert _ranges(_doc(df, flagged=[]), "d") == [
        {"start_year": 2000, "end_year": 2000, "count": 15}
    ]


def _wide_years(years: list[int]) -> pd.DataFrame:
    stamps = np.array([f"{y:04d}-02-02" for y in years], dtype="datetime64[s]")
    return pd.DataFrame({"d": pd.Series(stamps)})


def test_a_year_past_the_sampled_range_never_gets_a_bucket_of_its_own() -> None:
    df = _wide_years([2000] * 12 + [9998] * 10 + [9999])
    ranges = _ranges(_doc(df, flagged=[]), "d")
    assert ranges == [
        {"start_year": 2000, "end_year": 2000, "count": 12},
        {"start_year": 9998, "end_year": 9998, "count": 11},
    ]
    assert _draw(_doc(df, flagged=[]), "d", 50, 1)


def test_a_lone_row_in_year_9999_is_not_released_as_a_bucket() -> None:
    df = _wide_years([2000] * 30 + [9999])
    assert all(r["count"] >= K for r in _ranges(_doc(df, flagged=[]), "d"))
    assert 9999 not in {r["start_year"] for r in _ranges(_doc(df, flagged=[]), "d")}


def test_a_datetime_column_under_k_rows_releases_no_range() -> None:
    df = pd.DataFrame({"d": pd.to_datetime(["2001-01-01"] * 5)})
    doc = _doc(df, flagged=[])
    assert doc["redacted_columns"] == ["d"]
    assert _ranges(doc, "d") == []
    assert _col(doc, "d")["stats"]["min"] is None
    assert "2001" not in json.dumps(doc)


def test_the_flagged_and_g5_bounds_stay_outside_every_range() -> None:
    doc = _doc(_date_frame(), flagged=["forced"])
    for name in ("forced", "sparse"):
        stats = _col(doc, name)["stats"]
        ranges = _ranges(doc, name)
        assert stats["min"] == f"{ranges[0]['start_year'] - 1:04d}-01-01T00:00:00"
        assert stats["max"] == f"{ranges[-1]['end_year'] + 1:04d}-12-31T23:59:59"


def _draw(doc: dict[str, Any], name: str, size: int, seed: int) -> list[Any]:
    spec = load_spec({"name": name, "source_column": name}, snapshot=doc)
    return sample_column(spec, size, col_seed=seed)


def test_a_folded_range_is_drawn_at_its_weight_with_no_pile_up_at_the_bound() -> None:
    doc = _doc(_date_frame(), flagged=[])
    out = _draw(doc, "visit", 20_000, 7)
    ranges = _ranges(doc, "visit")
    total = sum(r["count"] for r in ranges)
    for r in ranges:
        share = sum(r["start_year"] <= v.year <= r["end_year"] for v in out) / len(out)
        assert share == pytest.approx(r["count"] / total, abs=0.02)
    lo = pd.Timestamp(_col(doc, "visit")["stats"]["min"]).to_pydatetime()
    hi = pd.Timestamp(_col(doc, "visit")["stats"]["max"]).to_pydatetime()
    assert sum(1 for v in out if v in (lo, hi)) < 5
    first = ranges[0]
    covered = {v.year for v in out if v.year <= first["end_year"]}
    assert len(covered) > 0.8 * (first["end_year"] - first["start_year"] + 1)


def _window_verdict(doc: dict[str, Any], names: list[str]) -> Any:
    from decoy_engine.generation._window_admission import classify_window_table

    cols = [{"name": n, "type": "statistical", "source_column": n} for n in names]
    specs = {("t", n): load_spec(c, snapshot=doc) for n, c in zip(names, cols, strict=True)}
    cfg = {"tables": [{"name": "t", "row_count": 10, "generate_columns": cols}]}
    return classify_window_table(cfg, "t", statistical_specs=specs)


def test_windowed_generation_admits_plain_fit_datetimes_with_short_outer_years() -> None:
    df = _qa_frame()
    df["sparse"] = _date_frame()["sparse"].reindex(range(len(df)))
    doc = _doc(df)  # the real profiler flags both datetime columns
    assert {"visit_date", "sparse"} <= set(doc["redacted_columns"])
    first = _ranges(doc, "visit_date")[0]
    kth = sorted(df["visit_date"].dropna().dt.year)[K - 1]
    assert first["start_year"] == kth > 1921 and first["end_year"] >= kth
    assert _window_verdict(doc, ["visit_date", "sparse"]).is_class_a
    unflagged = _doc(df, flagged=[])
    assert _window_verdict(unflagged, ["visit_date"]).is_class_a


# AT-6


def _tiny_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "state": ["CA"] * 5 + ["NY"] * 5 + ["TX"] * 5,
            "tier": ["a", "b", "c"] * 5,
            "amount": [1.0, 2.0, 3.0, 4.0, 5.0] * 3,
            "when": pd.to_datetime([f"{2010 + i % 5}-04-04" for i in range(15)]),
        }
    )


def test_a_column_too_small_to_floor_is_withheld_and_listed() -> None:
    doc = _doc(_tiny_frame(), flagged=[], joint_columns=[("state", "tier")])
    assert doc["redacted_columns"] == ["state", "tier", "amount", "when"]
    assert _col(doc, "state")["stats"]["top_values"] == []
    assert len(_col(doc, "amount")["stats"]["bin_counts"]) == 1
    assert all(r["count"] >= K for r in _ranges(doc, "when"))
    assert doc["joints"][0]["cells"] == []
    with pytest.raises(StatisticalSpecError) as err:
        load_spec(
            {"name": "s", "source_column": "state", "allow_real_categories": True}, snapshot=doc
        )
    assert err.value.code == reasons.plan.STATISTICAL_SNAPSHOT_VALUES_REDACTED
    assert "too few rows" in str(err.value)
    assert "CA" not in str(err.value)


def test_a_numeric_column_with_inf_cells_only_is_left_alone() -> None:
    doc = _doc(pd.DataFrame({"x": [np.inf] * 30}), flagged=[])
    assert "x" not in doc["redacted_columns"]


# AT-7


def test_the_plain_document_is_v2_and_the_other_writers_stay_v1() -> None:
    df = _qa_frame()
    doc = _doc(df)
    assert doc["value_policy"] == "flagged-redacted/v2" == POLICY_REDACTED
    assert doc["schema_version"] == SCHEMA_VERSION_V2
    assert compute_distribution_snapshot(df)["schema_version"] == SCHEMA_VERSION_V1
    included = distribution_snapshot_document(df, include_values=True)
    assert included["schema_version"] == SCHEMA_VERSION_V1
    assert included["value_policy"] == "raw"


@pytest.mark.parametrize("version", [SCHEMA_VERSION_V1, SCHEMA_VERSION_V2])
def test_load_spec_accepts_both_schema_versions(version: str) -> None:
    doc = {**_doc(_qa_frame()), "schema_version": version}
    if version == SCHEMA_VERSION_V1:
        for col in doc["columns"].values():
            if col["kind"] == "datetime":
                col["stats"]["year_bins"] = [{"year": 2020, "count": 3}]
    assert load_spec({"name": "salary", "source_column": "salary"}, snapshot=doc)


@pytest.mark.parametrize("bad", [None, "distribution-snapshot/v3"])
def test_load_spec_refuses_a_missing_or_future_schema_version(bad: str | None) -> None:
    doc = {**_doc(_qa_frame(), flagged=[]), "schema_version": bad}
    with pytest.raises(StatisticalSpecError):
        load_spec({"name": "visit_date", "source_column": "visit_date"}, snapshot=doc)


def test_both_policy_versions_are_accepted() -> None:
    assert {"flagged-redacted/v1", "flagged-redacted/v2"} == REDACTED_POLICIES


def test_a_withheld_joint_has_no_cap_warning_under_either_policy_version() -> None:
    base = _doc(_joint_frame(), flagged=["state"], joint_columns=[("state", "tier")])
    base["joints"][0]["cell_count"] = 99
    for policy in sorted(REDACTED_POLICIES):
        assert snapshot_joint_warnings({**base, "value_policy": policy}, contingency_top_k=25) == []
    forged = {**base, "value_policy": "flagged-redacted/v3"}
    assert len(snapshot_joint_warnings(forged, contingency_top_k=25)) == 1


# AT-8

_NUMBERS = st.lists(
    st.one_of(st.integers(-(10**6), 10**6), st.floats(-1e6, 1e6, allow_nan=False)),
    min_size=2 * K,
    max_size=120,
)
_LABELS = st.lists(st.sampled_from(["a", "b", "c", "d", "e", "f"]), min_size=1, max_size=120)
_YEARS = st.lists(st.integers(1900, 2100), min_size=1, max_size=120)
_SEEDED = settings(max_examples=40, deadline=None, suppress_health_check=list(HealthCheck))


@_SEEDED
@given(values=_NUMBERS)
def test_property_numeric_bounds_survive_a_tail_swap(values: list[float]) -> None:
    arr = np.asarray(values, dtype=float)
    ordered = np.sort(arr)
    # With a == b, or a span under the writable grid floor, the end bins are not the ones holding
    # the K-th cells, so the swap can move bin counts there (plan 4.2).
    assume(ordered[-K] - ordered[K - 1] >= 1e-10)
    a = _doc(pd.DataFrame({"x": arr}), flagged=[])
    b = _doc(pd.DataFrame({"x": _swap_tails(arr)}), flagged=[])
    assert "x" not in a["redacted_columns"]
    assert _numeric_keys(a, "x") == _numeric_keys(b, "x")
    assert sum(_col(a, "x")["stats"]["bin_counts"]) == len(arr)


@_SEEDED
@given(labels=_LABELS, other=_LABELS)
def test_property_labels_and_joint_cells_are_held_by_k_rows(
    labels: list[str], other: list[str]
) -> None:
    n = min(len(labels), len(other))
    df = pd.DataFrame({"s": labels[:n], "t": other[:n]})
    doc = _doc(df, flagged=[], joint_columns=[("s", "t")])
    for name in ("s", "t"):
        if name not in doc["redacted_columns"]:
            assert all(c >= K for c in _tops(doc, name).values())
    if not set(doc["redacted_columns"]) & {"s", "t"}:
        assert all(c["count"] >= K for c in doc["joints"][0]["cells"])


@_SEEDED
@given(years=_YEARS)
def test_property_every_year_range_holds_k_rows_and_the_count_is_kept(years: list[int]) -> None:
    df = pd.DataFrame({"d": pd.to_datetime([f"{y:04d}-07-07" for y in years])})
    ranges = _ranges(_doc(df, flagged=[]), "d")
    if len(years) >= 2 * K - 1:
        assert sum(r["count"] for r in ranges) == len(years)
    if ranges:  # fewer than 2K-1 rows may release none, when the K-th rows cross
        assert sum(r["count"] for r in ranges) == len(years)
        assert all(r["count"] >= K for r in ranges)
    else:
        assert len(years) < 2 * K - 1
    assert all(a["end_year"] < b["start_year"] for a, b in pairwise(ranges))


# AT-9


def _sampled(doc: dict[str, Any], name: str, seed: int) -> list[Any]:
    cfg = {"name": name, "source_column": name, "allow_real_categories": True}
    return sample_column(load_spec(cfg, snapshot=doc), 5000, col_seed=seed)


def test_the_round_trip_decodes_and_keeps_the_marginals() -> None:
    doc = _doc(_qa_frame(), flagged=[])
    generated = {
        name: _sampled(doc, name, seed)
        for seed, name in enumerate(("salary", "state", "visit_date", "diagnosis"))
    }
    assert "RARE-HIV-B20" not in set(generated["diagnosis"])
    out = pd.DataFrame(generated).assign(visit_date=lambda d: pd.to_datetime(d["visit_date"]))
    fidelity = compute_fidelity(doc, compute_distribution_snapshot(out))
    scores = {c["column"]: c for c in fidelity["marginal"]["columns"]}
    for name in ("salary", "state", "visit_date"):
        assert scores[name]["comparable"]
        assert scores[name]["similarity"] >= 0.95


# AT-10


def test_a_bool_column_keeps_its_one_false() -> None:
    assert _tops(_doc(_qa_frame()), "is_active")["False"] == 1


def test_a_bool_column_with_blanks_is_exempt_too() -> None:
    values: list[Any] = [True] * 50 + [False] + [None] * 5
    doc = _doc(pd.DataFrame({"b": pd.Series(values, dtype=object)}), flagged=[])
    assert "b" not in doc["redacted_columns"]
    assert _tops(doc, "b")["False"] == 1


def test_two_word_labels_stay_categorical() -> None:
    doc = _doc(pd.DataFrame({"city": ["New York", "San Diego"] * 50}), flagged=[])
    assert _col(doc, "city")["kind"] == "categorical"
    assert set(_tops(doc, "city")) == {"New York", "San Diego"}


def test_the_free_text_test_reads_the_median_label() -> None:
    assert not sv.labels_read_as_sentences(["one two three", "four five", "six seven", "eight"])
    assert sv.labels_read_as_sentences(["one two three", "four five six", "a"])
    assert not sv.labels_read_as_sentences([])


# AT-12


def test_a_flagged_sentence_column_stays_a_withheld_categorical() -> None:
    doc = _doc(_qa_frame(), flagged=["note"])
    note = _col(doc, "note")
    assert note["kind"] == "categorical"
    assert note["stats"]["top_values"] == []
    assert doc["redacted_columns"] == ["note"]


# the shared fold, which the scan document (row 24zm) calls too


def test_the_fold_merges_until_k_and_joins_a_short_tail() -> None:
    assert sv.fold_ranges_under_k([(1, 1, 4), (2, 2, 4), (3, 3, 4), (4, 4, 4)]) == [(1, 4, 16)]
    assert sv.fold_ranges_under_k([(1, 1, 12), (2, 2, 3)]) == [(1, 2, 15)]
    assert sv.fold_ranges_under_k([(1, 1, 12), (2, 2, 12)]) == [(1, 1, 12), (2, 2, 12)]
    assert sv.fold_ranges_under_k([(1, 1, 3)]) == [(1, 1, 3)]
    assert sv.fold_ranges_under_k([]) == []
    assert sv.fold_ranges_under_k([(10, 19, 4.0), (20, 29, 7.0)]) == [(10, 29, 11.0)]


def test_the_shape_block_names_match_the_numeric_shape_module() -> None:
    from decoy_engine.generation.statistical import _numeric_shape as shape

    assert set(sv._SHAPE_BLOCKS) == {shape.GRID_KEY, shape.EXACT_KEY}


# Row 24zp: datetime years are bottom and top coded at the K-th row from each end.


def _spread(n: int, start: int = 1950) -> list[int]:
    """One row in each of `n` consecutive years."""
    return list(range(start, start + n))


def _coded(years: list[int]) -> dict[str, Any]:
    return _doc(_wide_years(years), flagged=[])


def _span(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], Any, Any]:
    stats = _col(doc, "d")["stats"]
    return _ranges(doc, "d"), stats["min"], stats["max"]


def test_single_low_outlier_year_is_bottom_coded() -> None:
    ranges = _ranges(_coded([1850, *range(1990, 2020)]), "d")
    assert ranges[0]["start_year"] == 1998  # the 10th lowest row
    assert 1850 not in {r["start_year"] for r in ranges}


def test_single_high_outlier_year_is_top_coded() -> None:
    ranges = _ranges(_coded([*range(1990, 2020), 2090]), "d")
    assert ranges[-1]["end_year"] == 2011  # the 10th highest row
    assert 2090 not in {r["end_year"] for r in ranges}


@pytest.mark.parametrize("total", range(2 * K - 1, 2 * K + 12))
def test_moving_any_tail_row_outward_leaves_ranges_unchanged(total: int) -> None:
    years = _spread(total)
    base = _span(_coded(years))
    for i in range(K - 1):
        low = years.copy()
        low[i] = 1700 + i  # at or below the K-th lowest row's year
        assert _span(_coded(low)) == base, f"low row {i}"
        high = years.copy()
        high[-1 - i] = 2500 + i  # at or above the K-th highest row's year
        assert _span(_coded(high)) == base, f"high row {i}"


@pytest.mark.parametrize("total", range(K, 2 * K - 1))
def test_low_above_high_releases_no_range(total: int) -> None:
    """10 to 18 rows spread over distinct years: any one range would name a K-1 row's year."""
    doc = _coded(_spread(total, 1850))
    ranges, low, high = _span(doc)
    assert ranges == []
    assert low is None and high is None
    assert "1850" not in json.dumps(doc)


def test_k_rows_in_the_lowest_year_keep_that_year() -> None:
    """Kills an off-by-one K-th: the K-th lowest row sits in 1990, the (K+1)-th in 2000."""
    ranges = _ranges(_coded([*[1990] * K, *range(2000, 2020)]), "d")
    assert ranges[0]["start_year"] == 1990
    ranges = _ranges(_coded([*range(1990, 2010), *[2019] * K]), "d")
    assert ranges[-1]["end_year"] == 2019


def test_the_9999_sentinel_is_clamped_then_top_coded() -> None:
    ranges = _ranges(_coded([2000] * 12 + [9999] * 10), "d")
    assert ranges == [
        {"start_year": 2000, "end_year": 2000, "count": 12},
        {"start_year": 9998, "end_year": 9998, "count": 10},
    ]


def test_year_edge_reads_coded_bounds() -> None:
    df = _wide_years([1850, *range(1990, 2020)])
    stats = _col(_doc(df, flagged=["d"]), "d")["stats"]
    assert stats["min"] == "1997-01-01T00:00:00"  # one year below the coded first range
    assert stats["max"] == "2011-12-31T23:59:59"


def test_plain_min_max_read_coded_bounds() -> None:
    # A year holding K rows keeps the column out of the too-small-to-release path (G5), which
    # would bound it by the flagged edges instead of the plain ones.
    low_doc = _coded([1850, *[1990] * K, *range(1991, 2020)])
    assert "d" not in low_doc["redacted_columns"]  # the plain path, not the G5 flagged one
    assert _span(low_doc)[1] == "1990-01-01T00:00:00"
    assert "1850" not in json.dumps(low_doc)
    high_doc = _coded([2090, *[2019] * K, *range(1990, 2019)])
    assert "d" not in high_doc["redacted_columns"]
    assert _span(high_doc)[2] == "2019-12-31T23:59:59.999999"
    assert "2090" not in json.dumps(high_doc)
