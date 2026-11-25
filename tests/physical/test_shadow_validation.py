"""A standalone `ShadowCoordinator.run` never returns generation or mixed output its configured
validators reject (EXPECT-OFF-ROUTE S2, round 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.errors import ValidatorFailedError
from decoy_engine.execution.physical._compiler import compile_physical_plan
from decoy_engine.execution.physical._shadow_context import ShadowContext
from decoy_engine.execution.physical._shadow_coordinator import ShadowCoordinator
from decoy_engine.execution.physical._shadow_snapshot import capture_shadow_snapshot
from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs
from decoy_engine.validators import bind_validation_session
from tests.physical.test_shadow_full_frame import (
    _TABLE,
    _admitted_table_config,
    _build_ctx,
    _capture,
    _coordinator,
)
from tests.physical.test_shadow_generation import _admitted_dispatch, _generate_config
from tests.physical.test_shadow_mixed import ENGINE_VERSION, _accounts_source, _mixed_config

_REJECT_ALL = {"pattern": "^$"}


def test_generation_branch_refuses_output_a_validator_rejects() -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    with pytest.raises(ValidatorFailedError):
        ShadowCoordinator(ctx=ctx).run(plan, snapshot)


def test_mixed_branch_refuses_output_a_validator_rejects(tmp_path: Path) -> None:
    accounts = _accounts_source()
    config = _mixed_config(
        tmp_path,
        mask_sources={"accounts": accounts},
        mask_table_columns={"accounts": [{"name": "acct_id", "strategy": "passthrough"}]},
    )
    config["validators"] = [
        {"name": "regex_match", "columns": {"accounts": ["acct_id"]}, "params": _REJECT_ALL}
    ]
    inputs = capture_physical_plan_inputs(
        config, {"accounts": accounts}, engine_version=ENGINE_VERSION, execution_mode="full_frame"
    )
    plan = compile_physical_plan(inputs)
    ctx = ShadowContext.from_key_provider(
        plan=inputs.plan, key_provider=None, relationship_graph=inputs.graph
    )
    with pytest.raises(ValidatorFailedError):
        ShadowCoordinator(ctx=ctx, registry=inputs.registry).run(
            plan, capture_shadow_snapshot({"accounts": accounts})
        )


def _mixed_reject_all(tmp_path: Path) -> tuple[Any, Any, Any, Any, Any]:
    accounts = _accounts_source()
    config = _mixed_config(
        tmp_path,
        mask_sources={"accounts": accounts},
        mask_table_columns={"accounts": [{"name": "acct_id", "strategy": "passthrough"}]},
    )
    config["validators"] = [
        {"name": "regex_match", "columns": {"accounts": ["acct_id"]}, "params": _REJECT_ALL}
    ]
    inputs = capture_physical_plan_inputs(
        config, {"accounts": accounts}, engine_version=ENGINE_VERSION, execution_mode="full_frame"
    )
    plan = compile_physical_plan(inputs)
    ctx = ShadowContext.from_key_provider(
        plan=inputs.plan, key_provider=None, relationship_graph=inputs.graph
    )
    return config, inputs, plan, ctx, capture_shadow_snapshot({"accounts": accounts})


def test_bound_session_is_fed_by_a_generation_result_and_fails(tmp_path: Path) -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        result = ShadowCoordinator(ctx=ctx).run(plan, snapshot)
        assert "people" in result.outputs
        assert session.unobserved_tables(("people",)) == []
        report = session.finish()
    assert report.passed is False


def test_bound_session_is_fed_by_a_mixed_result_and_fails(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _mixed_reject_all(tmp_path)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        ShadowCoordinator(ctx=ctx, registry=inputs.registry).run(plan, snapshot)
        report = session.finish()
    assert report.passed is False


def test_full_frame_branch_refuses_output_a_validator_rejects(tmp_path: Path) -> None:
    config, source = _admitted_table_config(tmp_path)
    config["validators"] = [
        {"name": "regex_match", "columns": {_TABLE: ["shuffled"]}, "params": _REJECT_ALL}
    ]
    sources = {_TABLE: source}
    inputs, plan = _capture(config, sources)
    ctx = _build_ctx(inputs, config, validation_config=config)
    with pytest.raises(ValidatorFailedError):
        _coordinator(inputs, ctx).run(plan, capture_shadow_snapshot(sources))


def test_full_frame_branch_returns_output_a_validator_accepts(tmp_path: Path) -> None:
    config, source = _admitted_table_config(tmp_path)
    config["validators"] = [
        {"name": "regex_match", "columns": {_TABLE: ["shuffled"]}, "params": {"pattern": "."}}
    ]
    sources = {_TABLE: source}
    inputs, plan = _capture(config, sources)
    ctx = _build_ctx(inputs, config, validation_config=config)
    result = _coordinator(inputs, ctx).run(plan, capture_shadow_snapshot(sources))
    assert _TABLE in result.outputs
