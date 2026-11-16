"""AT-13: the datetime bucket contract matrix. One decoder reads v1 and v2."""

from __future__ import annotations

import pytest

from decoy_engine.contracts.distribution_snapshot import (
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    DatetimeBucket,
    decode_datetime_buckets,
    encode_datetime_buckets,
    year_weights,
)

V1, V2 = SCHEMA_VERSION_V1, SCHEMA_VERSION_V2


def _stats(*bins: object) -> dict[str, object]:
    return {"year_bins": list(bins)}


def test_v1_normalizes_to_one_year_ranges() -> None:
    got = decode_datetime_buckets(
        V1, _stats({"year": 2020, "count": 4}, {"year": 2022, "count": 6})
    )
    assert got == (DatetimeBucket(2020, 2020, 4), DatetimeBucket(2022, 2022, 6))


def test_v2_range_decodes_unchanged() -> None:
    got = decode_datetime_buckets(V2, _stats({"start_year": 2000, "end_year": 2003, "count": 12}))
    assert got == (DatetimeBucket(2000, 2003, 12),)


def test_encoder_round_trips_through_the_v2_decoder() -> None:
    buckets = (DatetimeBucket(1921, 2015, 10), DatetimeBucket(2016, 2024, 990))
    stored = encode_datetime_buckets(buckets)
    assert stored[0] == {"start_year": 1921, "end_year": 2015, "count": 10}
    assert decode_datetime_buckets(V2, {"year_bins": stored}) == buckets


@pytest.mark.parametrize("version", [None, "", "distribution-snapshot/v3", "distribution-snapshot"])
def test_missing_or_unknown_version_is_refused(version: object) -> None:
    with pytest.raises(ValueError):
        decode_datetime_buckets(version, _stats({"year": 2020, "count": 1}))


@pytest.mark.parametrize(
    ("version", "entry"),
    [
        (V2, {"year": 2020, "count": 1}),  # v1 entry under v2
        (V1, {"start_year": 2020, "end_year": 2020, "count": 1}),  # v2 entry under v1
        (V2, {"start_year": True, "end_year": 2020, "count": 1}),
        (V2, {"start_year": "2020", "end_year": 2020, "count": 1}),
        (V2, {"start_year": 2020.0, "end_year": 2020, "count": 1}),
        (V2, {"start_year": 2020, "end_year": 2020, "count": "1"}),
        (V2, {"start_year": 2020, "end_year": 2020, "count": True}),
        (V2, {"start_year": 2020, "end_year": 2020, "count": 1.5}),
        (V2, {"start_year": 2020, "end_year": 2020, "count": -1}),
        (V2, {"start_year": 2020, "end_year": 2020, "count": 1, "extra": 1}),
        (V2, {"start_year": 2020, "count": 1}),
        (V1, {"year": "2020", "count": 1}),
        (V1, {"year": True, "count": 1}),
        (V1, {"year": 2020.0, "count": 1}),
        (V1, {"year": 2020, "count": "1"}),
        (V1, {"year": 2020, "count": True}),
        (V1, {"year": 2020, "count": float("nan")}),
        (V1, {"year": 2020, "count": 1, "extra": 1}),
        (V2, "2020"),
    ],
)
def test_wrong_fields_or_types_are_refused(version: str, entry: object) -> None:
    with pytest.raises(ValueError):
        decode_datetime_buckets(version, _stats(entry))


def test_mixed_v1_and_v2_entries_are_refused() -> None:
    mixed = _stats({"year": 2020, "count": 1}, {"start_year": 2021, "end_year": 2022, "count": 5})
    for version in (V1, V2):
        with pytest.raises(ValueError):
            decode_datetime_buckets(version, mixed)


@pytest.mark.parametrize(
    "bins",
    [
        [{"start_year": 2005, "end_year": 2001, "count": 5}],  # inverted
        [
            {"start_year": 2000, "end_year": 2002, "count": 5},
            {"start_year": 2002, "end_year": 2004, "count": 5},
        ],  # overlap
        [
            {"start_year": 2003, "end_year": 2004, "count": 5},
            {"start_year": 2000, "end_year": 2001, "count": 5},
        ],  # out of order
    ],
)
def test_inverted_overlapping_and_unordered_ranges_are_refused(bins: list[object]) -> None:
    with pytest.raises(ValueError):
        decode_datetime_buckets(V2, {"year_bins": bins})
    with pytest.raises(ValueError):
        encode_datetime_buckets(
            [DatetimeBucket(b["start_year"], b["end_year"], b["count"]) for b in bins]
        )  # type: ignore[index]


def test_refusal_text_names_no_stored_value() -> None:
    with pytest.raises(ValueError) as exc:
        decode_datetime_buckets(
            V2, _stats({"start_year": "SECRET-1921", "end_year": 1, "count": 1})
        )
    assert "SECRET" not in str(exc.value)


def test_year_weights_split_by_seconds_and_keep_a_single_year_exact() -> None:
    assert year_weights((DatetimeBucket(2020, 2020, 7),)) == {2020: 7.0}
    w = year_weights((DatetimeBucket(2019, 2020, 100),))
    assert sum(w.values()) == pytest.approx(100.0)
    assert w[2020] > w[2019]  # leap year holds more seconds


@pytest.mark.parametrize(
    "entry",
    [
        {"start_year": 2001, "end_year": 9999, "count": 0},  # strictly past the sampled bound
        {"start_year": 0, "end_year": 5, "count": 3},
        {"start_year": -(10**9), "end_year": 10**9, "count": 1},
        {"start_year": 2000, "end_year": 10**9, "count": 0},
    ],
)
def test_v2_range_outside_supported_years_is_refused_whatever_its_count(
    entry: dict[str, int],
) -> None:
    with pytest.raises(ValueError) as exc:
        decode_datetime_buckets(
            V2, _stats({"start_year": 2000, "end_year": 2000, "count": 5}, entry)
        )
    assert "9999" not in str(exc.value)
    with pytest.raises(ValueError):
        encode_datetime_buckets([DatetimeBucket(entry["start_year"], entry["end_year"], 0)])


def test_v2_range_at_the_supported_bounds_decodes() -> None:
    got = decode_datetime_buckets(V2, _stats({"start_year": 1, "end_year": 9998, "count": 1}))
    assert got == (DatetimeBucket(1, 9998, 1),)


def test_pinned_v2_list_outside_supported_years_is_refused() -> None:
    from decoy_engine.contracts.distribution_snapshot import pinned_buckets

    bad = [{"start_year": -(10**9), "end_year": 10**9, "count": 1}]
    assert pinned_buckets("datetime", {}, bad) is None


@pytest.mark.parametrize("count", [2.5, 3.0, True])
def test_encoder_refuses_a_non_integer_count_instead_of_truncating(count: object) -> None:
    with pytest.raises(ValueError) as exc:
        encode_datetime_buckets([DatetimeBucket(2000, 2001, count)])  # type: ignore[arg-type]
    assert "2.5" not in str(exc.value)
