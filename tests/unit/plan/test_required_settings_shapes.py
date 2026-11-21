"""The `date_shift` shape rule: which shapes need a format, which run bare, which are refused."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.contracts import strategy_requirements as sr
from decoy_engine.contracts.column_shape import NO_SOURCES, ColumnShape
from decoy_engine.plan import PlanCompileError, run_config_only_checks
from decoy_engine.plan.checks import check_required_strategy_settings

S = ColumnShape
CODE = "date_shift_requires_date_format"


def _cfg(**col: Any) -> dict[str, Any]:
    entry = {"name": "d", "strategy": "date_shift", "namespace": "ns", **col}
    return {"tables": [{"name": "t", "columns": [entry]}]}


NEEDS = {S.TEXT, S.UNKNOWN}
RUNS_BARE = {S.DATE, S.TIMESTAMP_TZ}
MISMATCH = "column_shape_mismatch"


@pytest.mark.parametrize("shape", list(S))
def test_date_shift_rule_by_shape(shape: ColumnShape) -> None:
    """Text and `unknown` need the format; a date or a zoned timestamp runs bare; the rest are
    refused with the mismatch code, format or not."""
    if shape in NEEDS:
        with pytest.raises(PlanCompileError) as exc:
            check_required_strategy_settings(_cfg(), shapes={("t", "d"): shape}, sources=NO_SOURCES)
        assert exc.value.code == CODE
    elif shape in RUNS_BARE:
        check_required_strategy_settings(_cfg(), shapes={("t", "d"): shape}, sources=NO_SOURCES)
    else:
        with pytest.raises(PlanCompileError) as exc:
            check_required_strategy_settings(_cfg(), shapes={("t", "d"): shape}, sources=NO_SOURCES)
        assert exc.value.code == MISMATCH
    if shape not in NEEDS | RUNS_BARE:
        with pytest.raises(PlanCompileError) as exc2:
            check_required_strategy_settings(
                _cfg(provider_config={"date_format": "%Y-%m-%d"}),
                shapes={("t", "d"): shape},
                sources=NO_SOURCES,
            )
        assert exc2.value.code == MISMATCH
    else:
        check_required_strategy_settings(
            _cfg(provider_config={"date_format": "%Y-%m-%d"}),
            shapes={("t", "d"): shape},
            sources=NO_SOURCES,
        )


def test_declared_date_still_counts() -> None:
    cfg = _cfg(logical_type="date", parse_format={"id": "date/iso8601/v1"})
    check_required_strategy_settings(cfg, shapes={("t", "d"): S.DATE}, sources=NO_SOURCES)


def test_config_only_defers_unknown() -> None:
    """With no schema a column could be a typed date, so the config-only pass defers it and
    compile, which has the schema, refuses it like text."""
    run_config_only_checks(_cfg())
    check_required_strategy_settings(
        _cfg(), shapes={("t", "d"): S.DATE}, sources=NO_SOURCES
    )  # a typed date runs bare
    for refused in (S.UNKNOWN, S.TEXT):
        with pytest.raises(PlanCompileError) as exc:
            check_required_strategy_settings(
                _cfg(), shapes={("t", "d"): refused}, sources=NO_SOURCES
            )
        assert exc.value.code == CODE


def test_config_only_refuses_a_text_source() -> None:
    cfg = _cfg()
    cfg["sources"] = {"t": {"type": "file", "format": "csv", "path": "/dev/null"}}
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(cfg)
    assert exc.value.code == CODE


def test_nested_child_needs_the_format() -> None:
    entry = {
        "name": "doc",
        "strategy": "nested",
        "namespace": "ns",
        "provider_config": {"strategy": "date_shift", "target": "$.a"},
    }
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(
            {"tables": [{"name": "t", "columns": [entry]}]}, shapes={}, sources=NO_SOURCES
        )
    assert exc.value.code == CODE


def test_shape_requirement_is_the_registered_descriptor() -> None:
    """One place per fact: the shape rule wraps the same descriptor the registry holds."""
    shaped = sr.SHAPE_REQUIREMENTS_BY_STRATEGY["date_shift"]
    assert shaped.requirement in sr.REQUIREMENTS_BY_STRATEGY["date_shift"]
    assert sr.shape_requirement_for("date_shift", shaped.requirement) is shaped
    other = sr.REQUIREMENTS_BY_STRATEGY["date_shift"][0]
    assert sr.shape_requirement_for("date_shift", other) is None
    assert sr.shape_requirement_for("hash", other) is None
