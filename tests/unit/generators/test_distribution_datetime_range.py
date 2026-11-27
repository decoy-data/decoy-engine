"""AT-V2 (DATE-RANGE-SENTINEL S5): the fitted datetime sampler refuses a snapshot it cannot hold
with `plan/generation_unbounded_column`, before any draw and without quoting a value, and it
samples the partial first and last years of the nanosecond domain."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from decoy_engine import reasons
from decoy_engine.contracts.calendar_range import FittedRangeError
from decoy_engine.generators.columns import ColumnGenerator

SEED = 20261127
CODE = reasons.plan.GENERATION_UNBOUNDED_COLUMN


def _snap(min_: str, max_: str, bins: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "kind": "datetime",
        "min": min_,
        "max": max_,
        "year_bins": [{"year": y, "count": c} for y, c in bins],
    }


REFUSED = {
    "max_far": _snap("2020-01-01T00:00:00", "9999-12-31T00:00:00", [(2020, 5)]),
    "min_far": _snap("0001-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5)]),
    "min_before_ns_domain": _snap("1677-09-21T10:00:00", "2020-12-31T00:00:00", [(2020, 5)]),
    "max_after_ns_domain": _snap("2020-01-01T00:00:00", "2262-04-11T00:00:00", [(2020, 5)]),
    "live_bin_far": _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5), (9999, 3)]),
    "live_bin_early": _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(1000, 3), (2020, 5)]),
}


@pytest.mark.parametrize("name", REFUSED)
def test_an_unsupported_snapshot_is_refused_before_any_draw(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_draw(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the sampler drew before admission")

    monkeypatch.setattr(np.random, "default_rng", no_draw)
    for call in (
        lambda cg: cg._generate_distribution_datetime(5, REFUSED[name], SEED),
        lambda cg: cg.generate_column(
            5, {"name": "d", "type": "distribution", "snapshot": REFUSED[name]}, "t", {}
        ),
    ):
        with pytest.raises(FittedRangeError) as caught:
            call(ColumnGenerator(seed=1))
        exc = caught.value
        assert exc.code == CODE
        text = str(exc) + repr(exc)
        for value in ("9999", "0001", "1000", "2020", "10:00"):
            assert value not in text
        assert exc.__cause__ is None and exc.__context__ is None


def test_a_zero_count_bin_outside_the_domain_is_not_live() -> None:
    snap = _snap("2020-01-01T00:00:00", "2020-12-31T00:00:00", [(2020, 5), (9999, 0)])
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


def test_a_fitted_bound_that_overflows_when_normalized_is_a_coded_refusal() -> None:
    snap = _snap("0001-01-01T00:00:00+01:00", "2020-12-31T00:00:00", [(2020, 5)])
    with pytest.raises(FittedRangeError):
        ColumnGenerator(seed=1)._generate_distribution_datetime(5, snap, SEED)


def test_nine_fractional_digits_are_kept_on_every_interpreter() -> None:
    stamp = "2020-06-01T12:00:00.123456789"
    snap = _snap(stamp, stamp, [(2020, 5)])
    out = ColumnGenerator(seed=1)._generate_distribution_datetime(3, snap, SEED)
    assert {int(v.value) for v in out} == {pd.Timestamp(stamp).value}
