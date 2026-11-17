"""The strict YAML models of the policy block."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from decoy_engine.config.policy import ColumnDecision, PolicyConfig


def _rule(**extra):
    return {"id": "r1", "select": {"table": "t"}, "strategy": "hash", **extra}


def _refused(data):
    with pytest.raises(ValidationError) as caught:
        PolicyConfig.model_validate(data)
    return caught.value


def test_a_full_block_validates():
    cfg = PolicyConfig.model_validate(
        {
            "disguise": {"id": "hipaa", "version": "2026-11-20"},
            "rules": [_rule(provider_config={"min_days": -30}, why="dates")],
            "prohibit": [
                {"id": "no-ssn", "select": {"classification": "ssn"}, "forbid": ["passthrough"]}
            ],
            "default": {"strategy": "redact"},
        }
    )
    assert cfg.rules[0].decision() == ColumnDecision(
        strategy="hash", provider_config={"min_days": -30}
    )
    assert cfg.default == ColumnDecision(strategy="redact")


@pytest.mark.parametrize(
    "data",
    [
        {"unknown": 1},
        {"disguise": {"id": "hipaa"}},
        {"disguise": {"id": "Hipaa", "version": "2026-11-20"}},
        {"disguise": {"id": "hipaa", "version": "2026-11-20\n"}},
        {"disguise": {"id": "hipaa", "version": "20261120"}},
        {"disguise": {"id": "hipaa\n", "version": "2026-11-20"}},
        {"rules": [_rule(id="has space")]},
        {"rules": [_rule(id="x\n")]},
        {"rules": [_rule(deterministic="yes")]},
        {"rules": [_rule(deterministic=1)]},
        {"rules": [_rule(allow_collisions="true")]},
        {"rules": [_rule(strategy=True)]},
        {"rules": [_rule(namespace=5)]},
        {"rules": [_rule(provider_config=[1])]},
        {"rules": [_rule(extra_key=1)]},
        {"rules": [{"id": "r", "strategy": "hash"}]},
        {"rules": [{"id": "r", "select": {"table": "t"}}]},
        {"rules": [_rule(id=f"r{i}") for i in range(201)]},
        {"default": {"strategy": "hash", "id": "x"}},
        {"default": {}},
        {"prohibit": [{"id": "p", "select": {"table": "t"}}]},
        {"prohibit": [{"id": "p", "select": {"table": "t"}, "forbid": ["a"], "require": ["b"]}]},
        {"prohibit": [{"id": "p", "select": {"table": "t"}, "forbid": []}]},
        {"prohibit": [{"id": "p", "select": {"table": "t"}, "forbid": ["a"] * 51}]},
    ],
)
def test_bad_blocks_are_refused(data):
    _refused(data)


def test_200_rules_are_allowed():
    PolicyConfig.model_validate({"rules": [_rule(id=f"r{i}") for i in range(200)]})


def test_ids_are_unique_across_rules_and_prohibitions():
    exc = _refused(
        {
            "rules": [_rule(id="same")],
            "prohibit": [{"id": "same", "select": {"table": "t"}, "forbid": ["passthrough"]}],
        }
    )
    assert exc.errors()[0]["type"] == "policy_rule_conflict"
    assert "same" in exc.errors()[0]["msg"]


def test_a_bad_selector_inside_a_rule_keeps_its_code_and_location():
    exc = _refused({"rules": [_rule(select={})]})
    (err,) = exc.errors()
    assert err["type"] == "policy_selector_invalid"
    assert err["loc"] == ("rules", 0, "select")


def test_models_are_frozen():
    cfg = PolicyConfig.model_validate({"default": {"strategy": "hash"}})
    with pytest.raises(ValidationError):
        cfg.default = None  # type: ignore[misc]
