"""`nested_children` for the `rules` form (F07 E3b): one child per rule, with its config path."""

from __future__ import annotations

from decoy_engine._nested_json import nested_children


def test_rules_form_returns_one_child_per_rule_in_order() -> None:
    cfg = {
        "rules": [
            {"target": "$.a", "strategy": "redact"},
            {
                "target": "$.b",
                "strategy": "hash",
                "strategy_config": {"truncate": 8},
                "namespace": "customer",
            },
        ]
    }
    first, second = nested_children(cfg)
    assert (first.index, first.target, first.strategy) == (0, "$.a", "redact")
    assert first.config_path == "provider_config.rules[0]"
    assert first.namespace is None
    assert (second.index, second.target, second.strategy) == (1, "$.b", "hash")
    assert second.strategy_config == {"truncate": 8}
    assert second.namespace == "customer"
    assert second.config_path == "provider_config.rules[1]"


def test_single_form_keeps_its_path_and_index() -> None:
    (child,) = nested_children({"target": "$.a", "strategy": "redact"})
    assert child.index is None
    assert child.config_path == "provider_config"


def test_an_empty_or_non_list_rules_value_gives_no_children() -> None:
    assert nested_children({"rules": []}) == ()
    assert nested_children({"rules": "oops"}) == ()


def test_a_rule_that_is_not_a_mapping_still_yields_a_child_with_unset_fields() -> None:
    (child,) = nested_children({"rules": ["oops"]})
    assert (child.index, child.target, child.strategy) == (0, None, None)
    assert child.config_path == "provider_config.rules[0]"
