"""AT-V2b (DATE-RANGE-SENTINEL S5b): the statistical generator draws from live year bins, so its
rule is about those bins and not about the fitted bounds. A live bin past year 9998 is refused on
plan compile, on window admission and on a direct `sample_column`, with
`plan/generation_unbounded_column`. A far fitted bound with in-range bins keeps working."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.contracts.distribution_snapshot import SAMPLED_YEARS_RULE
from decoy_engine.generation._window_admission import (
    GenerationAdmissionError,
    classify_window_table,
)
from decoy_engine.generation.statistical import (
    StatisticalSpecError,
    check_degenerate,
    sample_column,
    spec_from_dict,
)
from decoy_engine.generation.synthesize import _generate_column
from decoy_engine.generators.columns import ColumnGenerator

CODE = reasons.plan.GENERATION_UNBOUNDED_COLUMN
COMPILE_TEXT = "statistical.c: not allowed. sampled years must lie in 1..9998"
WINDOW_TEXT = "t.c: sampled years must lie in 1..9998"
FAR_BIN = {
    "min": "2020-01-01T00:00:00",
    "max": "2020-12-31T00:00:00",
    "year_bins": [{"year": 2020, "count": 5}, {"year": 9999, "count": 3}],
}
CFG = {
    "tables": [
        {"name": "t", "row_count": 10, "generate_columns": [{"name": "c", "type": "statistical"}]}
    ]
}


def _spec(stats: dict[str, Any]) -> Any:
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


def test_the_shared_rule_text_is_one_constant() -> None:
    assert SAMPLED_YEARS_RULE == "sampled years must lie in 1..9998"


def test_check_degenerate_refuses_a_live_bin_past_9998_with_the_pinned_text() -> None:
    with pytest.raises(StatisticalSpecError) as caught:
        check_degenerate(_spec(FAR_BIN))
    assert caught.value.code == CODE
    assert caught.value.message == COMPILE_TEXT
    assert SAMPLED_YEARS_RULE in caught.value.message
    assert "9999" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_window_admission_refuses_the_same_snapshot_with_its_own_text() -> None:
    with pytest.raises(GenerationAdmissionError) as caught:
        classify_window_table(CFG, "t", statistical_specs={("t", "c"): _spec(FAR_BIN)})
    assert caught.value.code == CODE
    assert caught.value.message == WINDOW_TEXT
    assert SAMPLED_YEARS_RULE in caught.value.message
    assert "9999" not in str(caught.value)


def test_sample_column_refuses_before_any_draw() -> None:
    with pytest.raises(StatisticalSpecError) as caught:
        sample_column(_spec(FAR_BIN), 5, col_seed=7)
    assert caught.value.code == CODE
    assert "9999" not in str(caught.value)


def test_plan_compile_reports_the_public_code() -> None:
    from decoy_engine.reason_adapter import reason_from_exception

    with pytest.raises(StatisticalSpecError) as caught:
        check_degenerate(_spec(FAR_BIN))
    record = reason_from_exception(caught.value)
    assert (record.namespace, record.code) == ("plan", "generation_unbounded_column")


CONTROLS = {
    "far_max_bound": {
        "min": "2020-01-01T00:00:00",
        "max": "9999-12-31T00:00:00",
        "year_bins": [{"year": 2020, "count": 5}],
    },
    "far_min_bound": {
        "min": "0001-01-01T00:00:00",
        "max": "2020-12-31T00:00:00",
        "year_bins": [{"year": 2020, "count": 5}],
    },
    "zero_weight_far_bin": {
        "min": "2020-01-01T00:00:00",
        "max": "2020-12-31T00:00:00",
        "year_bins": [{"year": 2020, "count": 5}, {"year": 9999, "count": 0}],
    },
}


@pytest.mark.parametrize("name", CONTROLS)
def test_working_statistical_jobs_are_not_narrowed(name: str) -> None:
    spec = _spec(CONTROLS[name])
    check_degenerate(spec)
    classify_window_table(CFG, "t", statistical_specs={("t", "c"): spec})
    out = sample_column(spec, 20, col_seed=7)
    assert len(out) == 20
    assert {v.year for v in out} == {2020}


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
        "snapshot": {"kind": "datetime", **FAR_BIN},
    }
    values = _generate_column(col, 4, 7)
    assert all(isinstance(v, float) for v in values)
