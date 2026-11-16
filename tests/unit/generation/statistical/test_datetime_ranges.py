"""AT-5 sampler cells and the admission cells for v2 datetime ranges."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import pytest

from decoy_engine.contracts.distribution_snapshot import SCHEMA_VERSION_V1, SCHEMA_VERSION_V2
from decoy_engine.generation._window_admission import (
    GenerationAdmissionError,
    classify_window_table,
)
from decoy_engine.generation.statistical import (
    load_spec,
    sample_column,
    spec_from_dict,
    spec_to_dict,
)

RANGES = [
    {"start_year": 2000, "end_year": 2004, "count": 600},
    {"start_year": 2005, "end_year": 2005, "count": 300},
    {"start_year": 2006, "end_year": 2007, "count": 100},
]
MIN, MAX = "2000-01-01T00:00:00", "2007-12-31T23:59:59.999999"


def _snapshot(version: str, bins: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "schema_version": version,
        "row_count": 1000,
        "columns": {
            "d": {
                "kind": "datetime",
                "dtype": "datetime64[ns]",
                "null_count": 0,
                "non_null_count": 1000,
                "distinct_count": 1000,
                "stats": {"min": MIN, "max": MAX, "year_bins": bins},
            }
        },
        "joints": [],
    }


def _spec(version: str = SCHEMA_VERSION_V2, bins: list[dict[str, int]] | None = None) -> Any:
    snap = _snapshot(version, RANGES if bins is None else bins)
    return load_spec({"name": "d", "source_column": "d"}, snapshot=snap)


def test_v2_ranges_are_drawn_at_their_recorded_weights() -> None:
    out = sample_column(_spec(), 20000, col_seed=11)
    years = Counter(v.year for v in out)
    first = sum(years[y] for y in range(2000, 2005)) / 20000
    assert first == pytest.approx(0.6, abs=0.02)
    assert years[2005] / 20000 == pytest.approx(0.3, abs=0.02)
    assert (years[2006] + years[2007]) / 20000 == pytest.approx(0.1, abs=0.02)


def test_a_multi_year_range_spreads_across_every_year() -> None:
    years = Counter(v.year for v in sample_column(_spec(), 20000, col_seed=3))
    for y in range(2000, 2005):
        assert years[y] > 0.6 * 20000 / 5 * 0.8  # roughly one fifth of the range each


def test_no_pile_up_at_either_outer_bound() -> None:
    out = sample_column(_spec(), 20000, col_seed=5)
    lo, hi = datetime.fromisoformat(MIN), datetime.fromisoformat(MAX)
    assert min(out) >= lo and max(out) <= hi
    assert sum(1 for v in out if v in (lo, hi)) < 5


def test_v1_one_year_buckets_draw_the_same_values_as_equal_v2_one_year_ranges() -> None:
    v1 = [{"year": 2000, "count": 5}, {"year": 2003, "count": 9}]
    v2 = [
        {"start_year": 2000, "end_year": 2000, "count": 5},
        {"start_year": 2003, "end_year": 2003, "count": 9},
    ]
    a = sample_column(_spec(SCHEMA_VERSION_V1, v1), 300, col_seed=9)
    b = sample_column(_spec(SCHEMA_VERSION_V2, v2), 300, col_seed=9)
    assert a == b


def test_spec_carries_normalized_ranges_and_round_trips_a_pin() -> None:
    spec = _spec()
    first = spec.datetime_buckets[0]
    assert (first.start_year, first.end_year, first.count) == (2000, 2004, 600)
    again = spec_from_dict(spec_to_dict(spec))
    assert again.datetime_buckets == spec.datetime_buckets


def test_an_old_pinned_spec_without_the_field_normalizes_to_one_year_ranges() -> None:
    data = spec_to_dict(_spec(SCHEMA_VERSION_V1, [{"year": 2001, "count": 4}]))
    data.pop("datetime_buckets")
    data["stats"] = {**data["stats"], "year_bins": [{"year": 2001, "count": 4}]}
    old = spec_from_dict(data)
    assert [(b.start_year, b.end_year, b.count) for b in old.datetime_buckets] == [(2001, 2001, 4)]


def test_load_spec_refuses_a_datetime_column_with_a_bad_version_or_bucket() -> None:
    from decoy_engine.generation.statistical import StatisticalSpecError

    for snap in (
        _snapshot("distribution-snapshot/v3", RANGES),
        _snapshot(SCHEMA_VERSION_V2, [{"year": 2000, "count": 1}]),
    ):
        with pytest.raises(StatisticalSpecError):
            load_spec({"name": "d", "source_column": "d"}, snapshot=snap)


def _verdict(spec: Any) -> Any:
    col = {"name": "c", "type": "statistical"}
    cfg = {"tables": [{"name": "t", "row_count": 10, "generate_columns": [col]}]}
    return classify_window_table(cfg, "t", statistical_specs={("t", "c"): spec})


def test_admission_accepts_v2_ranges_and_refuses_a_range_outside_the_supported_years() -> None:
    # A stored file with such a range is refused at load (see the load_spec test below), so the
    # admission refusal is reached through a pinned spec that carries the range.
    assert _verdict(_spec()).is_class_a
    spec = _spec()
    pinned = spec_to_dict(spec)
    out_of_range = [{"start_year": 2000, "end_year": 9999, "count": 5}]
    pinned["stats"] = {**pinned["stats"], "year_bins": out_of_range}
    pinned["datetime_buckets"] = out_of_range
    with pytest.raises(GenerationAdmissionError) as exc:
        _verdict(spec_from_dict(pinned))
    assert exc.value.code == "generation_unbounded_column"


def test_admission_requires_the_outer_range_edges_to_agree_with_min_and_max() -> None:
    spec = _spec()
    bad = spec_from_dict(
        {**spec_to_dict(spec), "stats": {**spec.stats, "max": "2001-06-01T00:00:00"}}
    )
    with pytest.raises(GenerationAdmissionError) as exc:
        _verdict(bad)
    assert exc.value.code == "statistical_stats_degenerate"


def test_load_spec_refuses_a_range_outside_the_supported_years_with_a_coded_error() -> None:
    from decoy_engine.generation.statistical import StatisticalSpecError

    snap = _snapshot(SCHEMA_VERSION_V2, [{"start_year": 2000, "end_year": 9999, "count": 5}])
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec({"name": "d", "source_column": "d"}, snapshot=snap)
    assert exc.value.code == "statistical_snapshot_schema_mismatch"
