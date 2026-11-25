"""A standalone `ShadowCoordinator.run` never returns generation or mixed output its configured
validators reject (EXPECT-OFF-ROUTE S2, round 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from decoy_engine.errors import ValidatorFailedError
from decoy_engine.execution.physical._compiler import compile_physical_plan
from decoy_engine.execution.physical._shadow_context import ShadowContext
from decoy_engine.execution.physical._shadow_coordinator import ShadowCoordinator
from decoy_engine.execution.physical._shadow_snapshot import capture_shadow_snapshot
from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs
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
