"""`nested_children`: the one reader of a nested column's child strategy and config (F07 E3a)."""

from __future__ import annotations

import dataclasses

import pytest

from decoy_engine._nested_json import NestedChild, nested_children


def test_the_single_form_yields_one_child_with_the_single_form_path() -> None:
    cfg = {
        "target": "$.a",
        "strategy": "hash",
        "strategy_config": {"deterministic": True},
        "namespace": "ns",
    }
    (child,) = nested_children(cfg)
    assert child == NestedChild(
        index=None,
        target="$.a",
        strategy="hash",
        strategy_config={"deterministic": True},
        namespace="ns",
        references=(),
        config_path="provider_config",
    )


def test_an_empty_config_yields_one_child_of_unset_values() -> None:
    (child,) = nested_children({})
    assert child.index is None
    assert child.target is None
    assert child.strategy is None
    assert child.strategy_config is None
    assert child.namespace is None
    assert child.config_path == "provider_config"


def test_raw_values_pass_through_unchanged() -> None:
    cfg = {"strategy": 7, "strategy_config": "x", "target": ["$.a"]}
    (child,) = nested_children(cfg)
    assert (child.strategy, child.strategy_config, child.target) == (7, "x", ["$.a"])


def test_the_child_is_frozen() -> None:
    (child,) = nested_children({"strategy": "hash"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        child.strategy = "redact"  # type: ignore[misc]


def test_the_result_is_a_tuple() -> None:
    assert isinstance(nested_children({"strategy": "hash"}), tuple)
