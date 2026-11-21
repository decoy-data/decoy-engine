"""E1a moves no behaviour: `date_shift` still needs its format on every shape.

The shape table is in place. Deferral of `unknown` in the config-only pass is a property of the
table's content, so it is shown here against a table that admits a typed date.
"""

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


@pytest.mark.parametrize("shape", list(S))
def test_date_shift_rule_unchanged_on_every_shape(shape: ColumnShape) -> None:
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(_cfg(), shapes={("t", "d"): shape}, sources=NO_SOURCES)
    assert exc.value.code == CODE
    check_required_strategy_settings(
        _cfg(provider_config={"date_format": "%Y-%m-%d"}),
        shapes={("t", "d"): shape},
        sources=NO_SOURCES,
    )


def test_declared_date_still_counts() -> None:
    cfg = _cfg(logical_type="date", parse_format={"id": "date/iso8601/v1"})
    check_required_strategy_settings(cfg, shapes={("t", "d"): S.DATE}, sources=NO_SOURCES)


def test_config_only_refuses_unknown_while_every_shape_needs_the_format() -> None:
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(_cfg())
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
            {"tables": [{"name": "t", "columns": [entry]}]}, {}, sources=NO_SOURCES
        )
    assert exc.value.code == CODE


def test_config_only_defers_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a table that lets a typed date run bare, the config-only pass defers `unknown`
    (it could be that date) and compile, which has the schema, refuses it like text."""
    base = sr.SHAPE_REQUIREMENTS_BY_STRATEGY["date_shift"]
    admitting = sr.ShapeRequirement(
        base.family, base.requirement, frozenset(S) - {S.DATE}, declared_counts=True
    )
    monkeypatch.setattr(sr, "SHAPE_REQUIREMENTS_BY_STRATEGY", {"date_shift": admitting})
    check_required_strategy_settings(_cfg(), sources=NO_SOURCES)  # config-only: unknown is deferred
    check_required_strategy_settings(
        _cfg(), {("t", "d"): S.DATE}, sources=NO_SOURCES
    )  # a typed date runs bare
    for refused in (S.UNKNOWN, S.TEXT, S.INTEGER):
        with pytest.raises(PlanCompileError) as exc:
            check_required_strategy_settings(_cfg(), {("t", "d"): refused}, sources=NO_SOURCES)
        assert exc.value.code == CODE


def test_shape_requirement_is_the_registered_descriptor() -> None:
    """One place per fact: the shape rule wraps the same descriptor the registry holds."""
    shaped = sr.SHAPE_REQUIREMENTS_BY_STRATEGY["date_shift"]
    assert shaped.requirement in sr.REQUIREMENTS_BY_STRATEGY["date_shift"]
    assert sr.shape_requirement_for("date_shift", shaped.requirement) is shaped
    other = sr.REQUIREMENTS_BY_STRATEGY["date_shift"][0]
    assert sr.shape_requirement_for("date_shift", other) is None
    assert sr.shape_requirement_for("hash", other) is None
