"""A standalone `ShadowCoordinator.run` never returns generation or mixed output its configured
validators reject (EXPECT-OFF-ROUTE S2, round 1)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.errors import ValidatorFailedError, ValidatorStateError
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


def test_run_has_no_way_to_skip_judgement() -> None:
    """One way to defer judgement: the owner token. `run` takes no flag that skips it."""
    import inspect

    assert "validate_result" not in inspect.signature(ShadowCoordinator.run).parameters


def test_the_stitched_mixed_result_is_judged_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution.physical import _shadow_generation as generation

    judged: list[frozenset[str]] = []
    real = generation.enforce_validators

    def spy(ctx: Any, outputs: Any, sources: Any, **kwargs: Any) -> Any:
        judged.append(frozenset(outputs))
        return real(ctx, outputs, sources, **kwargs)

    monkeypatch.setattr(generation, "enforce_validators", spy)
    _, inputs, plan, ctx, snapshot = _mixed_reject_all(tmp_path)
    with pytest.raises(ValidatorFailedError):
        ShadowCoordinator(ctx=ctx, registry=inputs.registry).run(plan, snapshot)
    assert len(judged) == 1, "the mask half and the stitched whole were each judged"
    assert len(judged[0]) > 1, "the judged result was the mask half alone, not the stitched whole"


def test_bound_session_is_fed_by_a_generation_result_and_fails(tmp_path: Path) -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    with pytest.raises(ValidatorFailedError):
        with bind_validation_session(config, key_state_budget=lambda: None) as session:
            assert session is not None
            result = ShadowCoordinator(ctx=ctx).run(plan, snapshot)
            assert "people" in result.outputs
            assert session.unobserved_tables(("people",)) == []
            assert session.finish().passed is False


def test_bound_session_is_fed_by_a_mixed_result_and_fails(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _mixed_reject_all(tmp_path)
    with pytest.raises(ValidatorFailedError):
        with bind_validation_session(config, key_state_budget=lambda: None) as session:
            assert session is not None
            ShadowCoordinator(ctx=ctx, registry=inputs.registry).run(plan, snapshot)
            assert session.finish().passed is False


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


# --- Plan section 3a: under a bound session, `close` judges what the coordinator fed -------------


def _full_frame_reject_all(tmp_path: Path) -> tuple[Any, Any, Any, Any, Any]:
    config, source = _admitted_table_config(tmp_path)
    config["validators"] = [
        {"name": "regex_match", "columns": {_TABLE: ["shuffled"]}, "params": _REJECT_ALL}
    ]
    sources = {_TABLE: source}
    inputs, plan = _capture(config, sources)
    return config, inputs, plan, _build_ctx(inputs, config), capture_shadow_snapshot(sources)


def test_v15b_default_context_full_frame_is_judged_at_close(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _full_frame_reject_all(tmp_path)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        _coordinator(inputs, ctx).run(plan, snapshot)
        with pytest.raises(ValidatorFailedError):
            session.close()
        assert session.unjudged_tables() == []


def test_v15d_generation_fed_under_a_session_is_judged_at_close() -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        ShadowCoordinator(ctx=ctx).run(plan, snapshot)
        with pytest.raises(ValidatorFailedError):
            session.close()
        assert session.unjudged_tables() == []


def test_v15e_mixed_driver_under_a_session_is_judged_at_close(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _mixed_reject_all(tmp_path)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        ShadowCoordinator(ctx=ctx, registry=inputs.registry).run(plan, snapshot)
        with pytest.raises(ValidatorFailedError):
            session.close()


def test_v15g_an_owned_context_defers_and_close_refuses_when_the_owner_never_feeds(
    tmp_path: Path,
) -> None:
    config, inputs, plan, ctx, snapshot = _full_frame_reject_all(tmp_path)
    owned = dataclasses.replace(ctx, validation_owner="unified_slice")
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        _coordinator(inputs, owned).run(plan, snapshot)
        assert session.unobserved_tables([_TABLE]) == [_TABLE]
        with pytest.raises(ValidatorStateError) as caught:
            session.close()
    assert caught.value.code == reasons.runtime.VALIDATOR_TABLE_NOT_OBSERVED


# --- Codex round 2: standalone and ambient-session holes -------------------------------------------


def test_r2_standalone_full_frame_with_a_default_context_refuses_rejected_rows(
    tmp_path: Path,
) -> None:
    """No session and no `validation_config`: the plan's own validators still judge the result."""
    _, inputs, plan, ctx, snapshot = _full_frame_reject_all(tmp_path)
    assert ctx.validation_config is None
    with pytest.raises(ValidatorFailedError):
        _coordinator(inputs, ctx).run(plan, snapshot)


def test_r2_a_bound_generation_run_cannot_leave_its_scope_with_rejected_rows() -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    returned: list[Any] = []
    with pytest.raises(ValidatorFailedError):
        with bind_validation_session(config, key_state_budget=lambda: None):
            returned.append(ShadowCoordinator(ctx=ctx).run(plan, snapshot))
    assert returned, "the run itself returned; the scope exit is what refuses"


def test_r2_close_raises_the_same_verdict_every_time() -> None:
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        ShadowCoordinator(ctx=ctx).run(plan, snapshot)
        for _ in range(3):
            with pytest.raises(ValidatorFailedError):
                session.close()


def test_r2_an_ambient_session_holding_other_validators_is_refused() -> None:
    """An accept-all session must not judge a run configured with reject-all."""
    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    ambient = {
        "validators": [
            {"name": "regex_match", "columns": {"people": ["tier"]}, "params": {"pattern": "."}}
        ]
    }
    with bind_validation_session(ambient, key_state_budget=lambda: None) as session:
        assert session is not None
        with pytest.raises(ValidatorStateError) as caught:
            ShadowCoordinator(ctx=ctx).run(plan, snapshot)
        assert caught.value.code == reasons.runtime.VALIDATOR_CONFIG_NOT_OWNED
        session.close()  # the refused run fed it nothing, so the scope still closes cleanly


# --- Codex round 3: what the plan carries, what a session owns, who may defer ------------------


def _leak_check_config(tmp_path: Path) -> tuple[Any, Any, Any, Any, Any]:
    config, source = _admitted_table_config(tmp_path)
    config["validators"] = [{"name": "leak_check"}]
    sources = {_TABLE: source}
    inputs, plan = _capture(config, sources)
    return config, inputs, plan, _build_ctx(inputs, config), capture_shadow_snapshot(sources)


def test_r3_a_plan_carries_the_tables_a_leak_check_scope_reads(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _leak_check_config(tmp_path)
    full = dataclasses.replace(ctx, validation_config=config)
    with pytest.raises(ValidatorFailedError):
        _coordinator(inputs, full).run(plan, snapshot)
    assert ctx.validation_config is None
    with pytest.raises(ValidatorFailedError):
        _coordinator(inputs, ctx).run(plan, snapshot)


def test_r3_a_session_missing_the_tables_does_not_own_the_run(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _leak_check_config(tmp_path)
    ambient = {"validators": config["validators"]}
    with pytest.raises(ValidatorStateError) as caught:
        with bind_validation_session(ambient, key_state_budget=lambda: None):
            _coordinator(inputs, ctx).run(plan, snapshot)
    assert caught.value.code == reasons.runtime.VALIDATOR_CONFIG_NOT_OWNED


def test_r3_a_caller_edit_after_compile_cannot_change_the_verdict(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _full_frame_reject_all(tmp_path)
    config["validators"][0]["params"]["pattern"] = "."
    with pytest.raises(ValidatorFailedError):
        _coordinator(inputs, ctx).run(plan, snapshot)


def test_r3_deferral_needs_an_open_session(tmp_path: Path) -> None:
    config, inputs, plan, ctx, snapshot = _full_frame_reject_all(tmp_path)
    owned = dataclasses.replace(ctx, validation_owner="unified_slice")
    with pytest.raises(ValidatorStateError) as no_session:
        _coordinator(inputs, owned).run(plan, snapshot)
    assert no_session.value.code == reasons.runtime.VALIDATOR_SESSION_UNAVAILABLE
    with bind_validation_session(config, key_state_budget=lambda: None) as session:
        assert session is not None
        session.close()
        with pytest.raises(ValidatorStateError) as closed:
            _coordinator(inputs, owned).run(plan, snapshot)
    assert closed.value.code == reasons.runtime.VALIDATOR_SESSION_UNAVAILABLE


def test_no_public_coordinator_method_runs_a_plan_unjudged() -> None:
    """Every public method that takes a plan and a snapshot refuses output a validator rejects.

    The unchecked dispatch the mixed route needs is private, so a caller of the exported
    `ShadowCoordinator` cannot reach a result without judgement."""
    import inspect

    config = _generate_config()
    config["validators"] = [
        {"name": "regex_match", "columns": {"people": ["tier"]}, "params": _REJECT_ALL}
    ]
    plan, ctx, snapshot = _admitted_dispatch(config)
    coordinator = ShadowCoordinator(ctx=ctx)
    runners = [
        name
        for name, member in inspect.getmembers(ShadowCoordinator, inspect.isfunction)
        if not name.startswith("_")
        and {"plan", "snapshot"} <= set(inspect.signature(member).parameters)
    ]
    assert "run" in runners
    for name in runners:
        kwargs = {
            key: ()
            for key, param in inspect.signature(getattr(coordinator, name)).parameters.items()
            if param.default is inspect.Parameter.empty and key not in {"plan", "snapshot"}
        }
        with pytest.raises(ValidatorFailedError):
            getattr(coordinator, name)(plan, snapshot, **kwargs)
