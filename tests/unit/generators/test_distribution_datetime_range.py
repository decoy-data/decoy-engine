"""AT-V2a (DATE-RANGE-SENTINEL S5b): the fitted datetime sampler refuses a snapshot it cannot hold
with `plan/generation_unbounded_column`, before any draw and without quoting a value, and it
samples the partial first and last years of the nanosecond domain.

Each refused fixture carries one fault, so a bounds-only check cannot pass the bin fixtures and a
bin-only check cannot pass the bound fixtures. No fixture has a 9999 bin."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from decoy_engine import reasons
from decoy_engine.contracts.calendar_range import FittedRangeError
from decoy_engine.contracts.distribution_snapshot import SCHEMA_VERSION_V1, decode_datetime_buckets
from decoy_engine.generators.columns import ColumnGenerator
from decoy_engine.reason_adapter import reason_from_exception

SEED = 20261127
CODE = reasons.plan.GENERATION_UNBOUNDED_COLUMN

BOUND_TEXT = (
    "[generation_unbounded_column] {prop}: a fitted datetime must lie in 1677-09-22 to 2262-04-10."
)
BIN_TEXT = (
    "[generation_unbounded_column] year_bins: a live year bin must lie between the fitted "
    "min and max years."
)


def _snap(min_: str, max_: str, bins: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "kind": "datetime",
        "min": min_,
        "max": max_,
        "year_bins": [{"year": y, "count": c} for y, c in bins],
    }


# name -> (snapshot, expected prop, expected message)
REFUSED = {
    "max_far": (
        _snap("2020-01-01T00:00:00", "9999-12-31T00:00:00", [(2020, 5)]),
        "max",
        BOUND_TEXT.format(prop="max"),
    ),
    "min_far": (
        _snap("0001-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5)]),
        "min",
        BOUND_TEXT.format(prop="min"),
    ),
    "live_bin_late": (
        _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5), (2021, 3)]),
        "year_bins",
        BIN_TEXT,
    ),
    "live_bin_early": (
        _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(1700, 3), (2020, 5)]),
        "year_bins",
        BIN_TEXT,
    ),
}
FIXTURE_YEARS = ("9999", "0001", "2020", "2021", "1700")


class _DrawSpy:
    """Stands in for `np.random.default_rng` and records every `choice` call."""

    def __init__(self) -> None:
        self.choice_calls = 0
        self._real = np.random.default_rng

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        rng = self._real(*args, **kwargs)
        spy = self

        class _Wrapped:
            def choice(self, *a: Any, **k: Any) -> Any:
                spy.choice_calls += 1
                return rng.choice(*a, **k)

            def __getattr__(self, name: str) -> Any:
                return getattr(rng, name)

        return _Wrapped()


@pytest.mark.parametrize("name", REFUSED)
def test_the_snapshot_validator_accepts_every_refused_fixture(name: str) -> None:
    # The refusal under test must come from the admission, not from an earlier validator.
    snap = REFUSED[name][0]
    decode_datetime_buckets(SCHEMA_VERSION_V1, snap)
    datetime.fromisoformat(snap["min"])
    datetime.fromisoformat(snap["max"])


@pytest.mark.parametrize("name", REFUSED)
def test_an_unsupported_snapshot_is_refused_before_any_draw(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap, prop, message = REFUSED[name]
    spy = _DrawSpy()
    monkeypatch.setattr(np.random, "default_rng", spy)
    for call in (
        lambda cg: cg._generate_distribution_datetime(5, snap, SEED),
        lambda cg: cg.generate_column(
            5, {"name": "d", "type": "distribution", "snapshot": snap}, "t", {}
        ),
    ):
        with pytest.raises(FittedRangeError) as caught:
            call(ColumnGenerator(seed=1))
        exc = caught.value
        assert exc.code == "generation_unbounded_column"
        assert exc.prop == prop
        assert str(exc) == message
        record = reason_from_exception(exc)
        assert record.code == CODE and record.namespace == CODE.namespace
        text = str(exc) + repr(exc)
        for year in FIXTURE_YEARS:
            assert year not in text
        assert exc.__cause__ is None and exc.__context__ is None
    assert spy.choice_calls == 0


def test_the_public_identity_of_the_refusal_is_plan_generation_unbounded_column() -> None:
    record = reason_from_exception(FittedRangeError(prop="max"))
    assert (record.namespace, record.code) == ("plan", "generation_unbounded_column")


def test_the_two_edge_years_of_the_domain_and_bins_equal_to_min_and_max_draw_inside() -> None:
    snap = _snap("1677-09-22T00:00:00", "2262-04-10T00:00:00", [(1677, 2), (2262, 2)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(200, snap, SEED)
    assert out.notna().all()
    assert out.min() >= pd.Timestamp("1677-09-22") and out.max() <= pd.Timestamp("2262-04-10")
    assert set(out.dt.year) == {1677, 2262}


def test_a_zero_weight_bin_outside_the_fitted_years_is_not_live() -> None:
    snap = _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5), (2021, 0)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(20, snap, SEED)
    assert out.notna().all() and (out.dt.year == 2020).all()


def test_the_first_partial_year_of_the_domain_samples_inside_min_and_max() -> None:
    snap = _snap("1677-09-22T00:00:00", "1677-12-31T23:59:59", [(1677, 10)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(200, snap, SEED)
    assert out.min() >= pd.Timestamp("1677-09-22") and out.max() <= pd.Timestamp(
        "1677-12-31 23:59:59"
    )
    assert (out.dt.year == 1677).all()


def test_the_last_partial_year_of_the_domain_samples_inside_min_and_max() -> None:
    snap = _snap("2262-01-01T00:00:00", "2262-04-10T23:59:59", [(2262, 10)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(200, snap, SEED)
    assert out.min() >= pd.Timestamp("2262-01-01") and out.max() <= pd.Timestamp(
        "2262-04-10 23:59:59"
    )


def test_a_range_across_both_domain_edges_samples_every_year_bin() -> None:
    snap = _snap("1677-09-22T00:00:00", "2262-04-10T23:59:59", [(1677, 1), (1970, 1), (2262, 1)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(300, snap, SEED)
    assert set(out.dt.year) <= {1677, 1970, 2262}
    assert len(set(out.dt.year)) == 3
    assert str(out.dtype) == "datetime64[ns]"


def test_the_same_seed_gives_the_same_draw() -> None:
    snap = _snap("2020-01-01T00:00:00", "2022-12-31T00:00:00", [(2020, 1), (2022, 3)])
    a = ColumnGenerator(seed=1)._generate_distribution_datetime(50, snap, SEED)
    b = ColumnGenerator(seed=1)._generate_distribution_datetime(50, snap, SEED)
    assert a.equals(b)


def test_inverted_bounds_still_emit_nulls_and_skip_the_live_bin_rule() -> None:
    # max < min keeps the sampler's warning and NaT path. Its bin lies outside the (inverted)
    # fitted years, so a live-bin rule run on inverted bounds would refuse it instead.
    snap = _snap("2024-01-01T00:00:00", "2020-01-01T00:00:00", [(2010, 3)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(5, snap, SEED)
    assert out.isna().all()


def test_a_fitted_bound_that_overflows_when_normalized_is_a_coded_refusal() -> None:
    snap = _snap("0001-01-01T00:00:00+01:00", "2020-12-31T00:00:00", [(2020, 5)])
    with pytest.raises(FittedRangeError):
        ColumnGenerator(seed=1)._generate_distribution_datetime(5, snap, SEED)


def test_nine_fractional_digits_are_kept_on_every_interpreter() -> None:
    stamp = "2020-06-01T12:00:00.123456789"
    snap = _snap(stamp, stamp, [(2020, 5)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert {int(v.value) for v in out} == {pd.Timestamp(stamp).value}


@pytest.mark.parametrize(
    "bound", ["2020-06-01T00:99:00", "2020-06-01T24:00:00", "2020-06-01T00:00:00+99:99"]
)
def test_a_malformed_clock_or_offset_stays_unparseable_not_shifted(bound: str) -> None:
    snap = _snap(bound, bound, [(2020, 5)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert out.isna().all()


def test_a_date_with_a_zone_and_no_time_stays_unparseable() -> None:
    snap = _snap("2020-01-01+02:00", "2020-01-01+02:00", [(2020, 5)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert out.isna().all()


def test_a_basic_format_date_is_still_read() -> None:
    snap = _snap("20200101", "20200101", [(2020, 5)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert not out.isna().any() and set(out) == {pd.Timestamp("2020-01-01")}


def test_a_bound_pandas_reads_beyond_the_domain_is_refused_not_nulled() -> None:
    snap = _snap("2020-01-01", "Dec 31 9999", [(2020, 5)])
    with pytest.raises(FittedRangeError):
        ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)


@pytest.mark.parametrize("bound", [1_577_836_800_000_000_000, 2020.5, ["2020-01-01"]])
def test_a_non_string_bound_is_unparseable_not_out_of_range(bound: Any) -> None:
    # Main's unparseable-bound path emits nulls. A non-string must not be stringified and then
    # refused as if it named a far date.
    snap = _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5)])
    snap["max"] = bound
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert out.isna().all()
