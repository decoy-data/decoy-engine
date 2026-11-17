"""AT-9 fidelity cells: both scorers accept a v2 range against a v1 snapshot."""

from __future__ import annotations

from typing import Any

from decoy_engine.quality.fidelity import compute_fidelity
from decoy_engine.quality.shape_fidelity import compute_shape_fidelity

V1, V2 = "distribution-snapshot/v1", "distribution-snapshot/v2"


def _snap(version: str, bins: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "schema_version": version,
        "row_count": 100,
        "columns": {
            "d": {
                "kind": "datetime",
                "dtype": "datetime64[ns]",
                "null_count": 0,
                "non_null_count": 100,
                "distinct_count": 100,
                "stats": {
                    "min": "2020-01-01T00:00:00",
                    "max": "2021-12-31T23:59:59",
                    "year_bins": bins,
                },
            }
        },
        "joints": [],
    }


V1_BINS = [{"year": 2020, "count": 50}, {"year": 2021, "count": 50}]
V2_BINS = [{"start_year": 2020, "end_year": 2021, "count": 100}]


def _col(fid: dict[str, Any]) -> dict[str, Any]:
    return fid["marginal"]["columns"][0]


def test_v1_against_v1_is_unchanged() -> None:
    col = _col(compute_fidelity(_snap(V1, V1_BINS), _snap(V1, V1_BINS)))
    assert col["comparable"] and col["similarity"] == 1.0
    assert col["method"] == "tvd"


def test_v2_range_against_v1_uses_uniform_in_time_year_counts() -> None:
    col = _col(compute_fidelity(_snap(V2, V2_BINS), _snap(V1, V1_BINS)))
    assert col["comparable"]
    # 2020 is a leap year, so the split is 366/731 against 50/100: a small TVD, not zero.
    assert 0.99 < col["similarity"] < 1.0
    assert col["extra_metrics"]["ks_complement"]["comparable"] is True


def test_a_malformed_or_mixed_bucket_is_non_comparable_without_exception_text() -> None:
    bad = _snap(V2, [{"year": 2020, "count": 100}])
    col = _col(compute_fidelity(bad, _snap(V1, V1_BINS)))
    assert col["comparable"] is False and col["similarity"] is None
    assert "2020" not in str(col)


def test_shape_fidelity_accepts_a_v2_range_against_v1() -> None:
    fid = compute_shape_fidelity(_snap(V2, V2_BINS), _snap(V1, V1_BINS))
    col = fid["marginal"]["columns"][0]
    assert col["comparable"] is True
    bad = compute_shape_fidelity(_snap(V2, [{"year": 1, "count": 1}]), _snap(V1, V1_BINS))
    assert bad["marginal"]["columns"][0]["comparable"] is False


def test_v1_fractional_counts_score_as_main_did_with_int_counts() -> None:
    src = _snap(V1, [{"year": 2020, "count": 2.5}, {"year": 2021, "count": 1.5}])
    out = _snap(V1, [{"year": 2020, "count": 1.5}, {"year": 2021, "count": 2.5}])
    # int() first: [2, 1] against [1, 2], the value origin/main produced.
    assert _col(compute_fidelity(src, out))["similarity"] == 0.666667


def test_v1_huge_finite_count_scores_in_both_scorers() -> None:
    big = _snap(V1, [{"year": 2020, "count": 1e308}, {"year": 2021, "count": 1e308}])
    small = _snap(V1, [{"year": 2020, "count": 1}, {"year": 2021, "count": 1}])
    assert _col(compute_fidelity(big, small))["similarity"] == 1.0
    shape = compute_shape_fidelity(big, small)["marginal"]["columns"][0]
    assert shape["comparable"] is True and shape["shape_similarity"] == 1.0
