"""`Plan.column_shapes` and `PLAN_VERSION` 5: what a plan records, stores, and refuses at load."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import NO_SOURCES, ColumnShape
from decoy_engine.plan import PlanCompileError, compile_plan, plan_from_yaml, plan_to_yaml
from decoy_engine.plan._compile import PLAN_VERSION
from decoy_engine.profile._source import profile_source
from tests.acceptance._f06_support import INT64, ISO_DATE, column, config, validate, write_csv

S = ColumnShape


def _compile(tmp_path: Path, columns: list[dict[str, Any]]) -> Any:
    src = write_csv(tmp_path / "s.csv", ["d", "n"], [["2024-01-15", "42"], ["2024-02-03", "7"]])
    cfg = validate(config(columns, source_path=src))
    return compile_plan(
        cfg, profile_source(cfg, seed=7), decoy_engine_version="t", sources=NO_SOURCES
    )


def _shift(**pc: Any) -> dict[str, Any]:
    return column(
        "d", "date_shift", namespace="ns", provider_config={"date_format": "%Y-%m-%d", **pc}
    )


def test_plan_records_shapes_for_reading_strategies_only(tmp_path: Path) -> None:
    plan = _compile(tmp_path, [_shift(), column("n", "hash", namespace="h")])
    assert [(c.table, c.column, c.shape) for c in plan.column_shapes] == [("people", "d", S.TEXT)]


def test_plan_without_a_reading_strategy_has_no_shapes(tmp_path: Path) -> None:
    plan = _compile(tmp_path, [column("n", "hash", namespace="h")])
    assert plan.column_shapes == ()


def test_plan_is_deterministic(tmp_path: Path) -> None:
    a = _compile(tmp_path, [_shift()])
    b = _compile(tmp_path, [_shift()])
    assert plan_to_yaml(a) == plan_to_yaml(b)


def test_plan_round_trip_keeps_column_shapes(tmp_path: Path) -> None:
    plan = _compile(tmp_path, [_shift()])
    assert plan.column_shapes
    again = plan_from_yaml(plan_to_yaml(plan))
    assert again == plan
    assert again.column_shapes == plan.column_shapes


def test_plan_without_shapes_writes_no_key(tmp_path: Path) -> None:
    text = plan_to_yaml(_compile(tmp_path, [column("n", "hash", namespace="h")]))
    assert "column_shapes" not in text
    assert f"plan_version: {PLAN_VERSION}" in text


def test_the_shape_is_stored_as_its_token(tmp_path: Path) -> None:
    data = yaml.safe_load(plan_to_yaml(_compile(tmp_path, [_shift()])))
    assert data["column_shapes"] == [{"table": "people", "column": "d", "shape": "text"}]


# One version-4 plan per family that is valid today.
_FAMILIES: dict[str, list[dict[str, Any]]] = {
    "date_shift_format": [_shift()],
    "date_shift_f06_date": [
        column(
            "d",
            "date_shift",
            namespace="ns",
            logical_type="date",
            parse_format=ISO_DATE,
            provider_config={},
        )
    ],
    "bucket_perturb_format": [
        column(
            "d",
            "bucket_perturb",
            namespace="ns",
            provider_config={"bucket": "month", "date_format": "%Y-%m-%d"},
        )
    ],
    "bucket_perturb_no_format": [
        column("d", "bucket_perturb", namespace="ns", provider_config={"bucket": "month"})
    ],
    "bucketize": [
        column(
            "n",
            "bucketize",
            logical_type="integer",
            parse_format=INT64,
            provider_config={"width": 10},
        )
    ],
    "top_code": [
        column(
            "n",
            "top_code",
            logical_type="integer",
            parse_format=INT64,
            provider_config={"cap": 89, "over_label": "90+"},
        )
    ],
    "fpe": [column("n", "fpe", namespace="ns")],
}


def _drop_key(node: Any, key: str) -> None:
    if isinstance(node, dict):
        node.pop(key, None)
        for value in node.values():
            _drop_key(value, key)
    elif isinstance(node, list):
        for value in node:
            _drop_key(value, key)


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_v4_plans_need_recompile(tmp_path: Path, family: str) -> None:
    # A version-4 `bucket_perturb` plan with no format detected it at run time. The stored plan
    # is written from the formatted config with the format removed.
    stored = "bucket_perturb_format" if family == "bucket_perturb_no_format" else family
    plan = _compile(tmp_path, _FAMILIES[stored])
    v4 = plan_to_yaml(plan).replace(f"plan_version: {PLAN_VERSION}", "plan_version: 4", 1)
    v4_data = yaml.safe_load(v4)
    v4_data.pop("column_shapes", None)
    if family == "bucket_perturb_no_format":
        _drop_key(v4_data, "date_format")
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(v4_data, sort_keys=False))
    assert exc.value.code == reasons.plan.PLAN_RECOMPILE_REQUIRED
    assert "compile it again" in exc.value.message and "4" not in exc.value.message
    if family == "bucket_perturb_no_format":
        # Plan 2026-11-21-column-shape-rule section 8 (E1a) and 12: a stored plan's config compiled
        # again "gives a version-5 plan that runs, or is refused only by a freeze item of section
        # 12". `bucket_perturb on text with no date_format` is the E2 freeze item.
        with pytest.raises(PlanCompileError) as refused:
            _compile(tmp_path, _FAMILIES[family])
        assert refused.value.code == reasons.plan.COLUMN_SHAPE_REQUIRED
        return
    # Compiling the unchanged config again on this engine gives a plan that loads.
    again = _compile(tmp_path, _FAMILIES[family])
    assert again.plan_version == PLAN_VERSION
    assert plan_from_yaml(plan_to_yaml(again)) == again


def _stored(tmp_path: Path) -> dict[str, Any]:
    return yaml.safe_load(plan_to_yaml(_compile(tmp_path, [_shift()])))  # type: ignore[no-any-return]


def test_newer_plan_version_refused(tmp_path: Path) -> None:
    data = _stored(tmp_path)
    data["plan_version"] = PLAN_VERSION + 1
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(data, sort_keys=False))
    assert exc.value.code == reasons.plan.PLAN_VERSION_UNSUPPORTED
    assert "newer engine" in exc.value.message
    assert str(PLAN_VERSION + 1) not in exc.value.message


@pytest.mark.parametrize("bad", ["missing", True, "5", 5.0, [5], None])
def test_malformed_plan_version_refused(tmp_path: Path, bad: object) -> None:
    data = _stored(tmp_path)
    if bad == "missing":
        del data["plan_version"]
    else:
        data["plan_version"] = bad
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(data, sort_keys=False))
    assert exc.value.code == reasons.plan.PLAN_VERSION_UNSUPPORTED
    assert "no valid plan_version" in exc.value.message
    assert "5" not in exc.value.message.replace("plan_version", "")
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_the_version_is_checked_before_any_other_field(tmp_path: Path) -> None:
    data = _stored(tmp_path)
    data["plan_version"] = PLAN_VERSION + 1
    del data["seed_envelope"]
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(data, sort_keys=False))
    assert exc.value.code == reasons.plan.PLAN_VERSION_UNSUPPORTED


@pytest.mark.parametrize("token", ["bogus", "", 3, ["text"], None, "TEXT"])
def test_unknown_stored_shape_refused(tmp_path: Path, token: object) -> None:
    data = _stored(tmp_path)
    marker = copy.deepcopy(data)
    marker["column_shapes"][0]["shape"] = token
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(marker, sort_keys=False))
    assert exc.value.code == reasons.plan.STORED_SHAPE_UNKNOWN
    assert "'d'" not in exc.value.message and "column d in table people" in exc.value.message
    assert "bogus" not in exc.value.message and "TEXT" not in exc.value.message
    assert exc.value.__cause__ is None and exc.value.__context__ is None


@pytest.mark.parametrize(
    "bad",
    [
        "text",
        ["x"],
        [{"table": "people", "column": "d"}],
        [{"table": 5, "column": "d", "shape": "text"}],
        [{"table": "people", "column": ["d"], "shape": "text"}],
        [
            {"table": "people", "column": "d", "shape": "text"},
            {"table": "people", "column": "d", "shape": "date"},
        ],
    ],
    ids=[
        "not-a-list",
        "entry-not-a-mapping",
        "no-token",
        "non-str-table",
        "non-str-column",
        "duplicate",
    ],
)
def test_malformed_stored_shapes_are_plan_errors(tmp_path: Path, bad: object) -> None:
    data = _stored(tmp_path)
    data["column_shapes"] = bad
    with pytest.raises(PlanCompileError) as exc:
        plan_from_yaml(yaml.safe_dump(data, sort_keys=False))
    assert exc.value.code == reasons.plan.STORED_SHAPE_UNKNOWN
    assert exc.value.__cause__ is None and exc.value.__context__ is None
