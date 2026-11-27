"""AT-V2 evidence (DATE-RANGE-SENTINEL S5): every route that could draw a datetime from a fitted
bound refuses a year past the supported range with `plan/generation_unbounded_column` before any
draw, or never reaches the legacy sampler at all."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.contracts.calendar_range import FittedRangeError
from decoy_engine.generation._window_admission import (
    GenerationAdmissionError,
    classify_window_table,
)
from decoy_engine.generation.statistical import spec_from_dict
from decoy_engine.generation.synthesize import _generate_column
from decoy_engine.generators.columns import ColumnGenerator

CODE = reasons.plan.GENERATION_UNBOUNDED_COLUMN
FAR = {
    "kind": "datetime",
    "min": "2020-01-01T00:00:00",
    "max": "9999-12-31T00:00:00",
    "year_bins": [{"year": 2020, "count": 5}, {"year": 9999, "count": 3}],
}


def _statistical_spec(stats: dict[str, Any]) -> Any:
    return spec_from_dict(
        {
            "column": "c",
            "source_column": "c",
            "kind": "datetime",
            "dtype": "datetime64[ns]",
            "stats": stats,
            "other_mode": "redistribute",
            "condition_on": None,
            "joint": None,
            "parent_first": True,
        }
    )


def test_statistical_compile_refuses_a_year_past_the_range_before_any_draw() -> None:
    spec = _statistical_spec({"year_bins": FAR["year_bins"], "min": FAR["min"], "max": FAR["max"]})
    cfg = {
        "tables": [
            {
                "name": "t",
                "row_count": 10,
                "generate_columns": [{"name": "c", "type": "statistical"}],
            }
        ]
    }
    with pytest.raises(GenerationAdmissionError) as caught:
        classify_window_table(cfg, "t", statistical_specs={("t", "c"): spec})
    assert caught.value.code == CODE
    assert "9999" not in str(caught.value)


def test_a_config_distribution_column_never_reaches_the_fitted_datetime_sampler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `type: distribution` in a V2 config is the parametric family: it takes low/high, not a
    # snapshot, so the legacy sampler is not on its path.
    def reached(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the fitted datetime sampler was reached from a config column")

    monkeypatch.setattr(ColumnGenerator, "_generate_distribution_datetime", reached)
    col = {
        "name": "d",
        "type": "distribution",
        "family": "uniform",
        "low": 0,
        "high": 1,
        "snapshot": FAR,
    }
    values = _generate_column(col, 4, 7)
    assert all(isinstance(v, float) for v in values)


def test_the_legacy_sampler_refuses_a_year_past_the_range_before_any_draw() -> None:
    with pytest.raises(FittedRangeError) as caught:
        ColumnGenerator(seed=1).generate_column(
            3, {"name": "d", "type": "distribution", "snapshot": FAR}, "t", {}
        )
    assert caught.value.code == CODE


def test_the_plan_compile_check_refuses_a_statistical_year_past_the_range() -> None:
    from decoy_engine.generation.statistical import StatisticalSpecError, check_degenerate

    spec = _statistical_spec({"year_bins": FAR["year_bins"], "min": FAR["min"], "max": FAR["max"]})
    with pytest.raises(StatisticalSpecError) as caught:
        check_degenerate(spec)
    assert caught.value.code == CODE
    assert "9999" not in str(caught.value)


@pytest.mark.parametrize("bound", ["min", "max"])
def test_the_plan_compile_check_refuses_an_unparseable_statistical_bound(bound: str) -> None:
    from decoy_engine.generation.statistical import StatisticalSpecError, check_degenerate

    stats = {"year_bins": [{"year": 2020, "count": 5}], "min": "2020-01-01", "max": "2020-12-31"}
    stats[bound] = "not a datetime"
    with pytest.raises(StatisticalSpecError) as caught:
        check_degenerate(_statistical_spec(stats))
    assert caught.value.code == CODE
    assert "not a datetime" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
