"""F07 E3b: plan checks for the nested `rules` form, through both compile entry points."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.contracts.strategy_requirements import requirement_applies, requirements_for
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan.checks import check_required_strategy_settings
from decoy_engine.profile import Profile
from decoy_engine.secret_providers._requirements import column_is_keyed

COL = "tables.customers.columns.name"


def _config(provider_config: dict[str, Any], **column: Any) -> dict[str, Any]:
    entry = {
        "name": "name",
        "strategy": "nested",
        "namespace": "ns",
        "provider_config": provider_config,
        **column,
    }
    return {"tables": [{"name": "customers", "columns": [entry]}]}


def _rule(target: str = "$.a", strategy: str = "redact", **extra: Any) -> dict[str, Any]:
    return {"target": target, "strategy": strategy, **extra}


def _refused(config: dict[str, Any], profile: Profile) -> list[PlanCompileError]:
    errors = []
    for call in (
        lambda: run_config_only_checks(config),
        lambda: compile_plan(config, profile, decoy_engine_version="0.1.0"),
    ):
        with pytest.raises(PlanCompileError) as exc:
            call()
        errors.append(exc.value)
    return errors


@pytest.mark.parametrize(
    ("provider_config", "code"),
    [
        ({"rules": [_rule()], "target": "$.a"}, "nested_rules_and_target_both_set"),
        ({"rules": [_rule()], "strategy": "redact"}, "nested_rules_and_target_both_set"),
        ({"rules": []}, "nested_rules_empty"),
        ({"rules": "oops"}, "nested_rules_empty"),
        ({"rules": [_rule("$.a"), _rule("$.a", "hash")]}, "nested_rule_target_duplicate"),
        (
            {"rules": [_rule("$.a", "code_set"), _rule("$.b", "code_set")]},
            "nested_rules_code_set_repeated",
        ),
    ],
)
def test_malformed_rules_are_refused_at_both_entry_points(
    provider_config: dict[str, Any], code: str, simple_profile: Profile
) -> None:
    for error in _refused(_config(provider_config), simple_profile):
        assert error.code == code
        assert error.path.startswith(f"{COL}.provider_config")


def test_the_duplicate_target_names_the_second_rule(simple_profile: Profile) -> None:
    config = _config({"rules": [_rule("$.a"), _rule("$.b"), _rule("$.a", "hash")]})
    for error in _refused(config, simple_profile):
        assert error.path == f"{COL}.provider_config.rules[2].target"


class TestChildRefusalsReachRulesAfterTheFirst:
    def test_top_code_in_the_second_rule(self, simple_profile: Profile) -> None:
        config = _config({"rules": [_rule("$.a"), _rule("$.b", "top_code")]})
        for error in _refused(config, simple_profile):
            assert error.code == "top_code_unsupported_in_nested"
            assert error.path == f"{COL}.provider_config.rules[1].strategy"

    def test_date_shift_group_by_in_the_second_rule(self, simple_profile: Profile) -> None:
        config = _config(
            {
                "rules": [
                    _rule("$.a", "date_shift"),
                    _rule("$.b", "date_shift", strategy_config={"group_by": "id"}),
                ]
            }
        )
        for error in _refused(config, simple_profile):
            assert error.code == "date_shift_group_by_unsupported_in_nested"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.group_by"

    def test_bucket_perturb_date_format_in_the_second_rule(self, simple_profile: Profile) -> None:
        config = _config(
            {
                "rules": [
                    _rule("$.a"),
                    _rule("$.b", "bucket_perturb", strategy_config={"date_format": 5}),
                ]
            }
        )
        for error in _refused(config, simple_profile):
            assert error.code == "bucket_perturb_date_format_unsupported"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.date_format"

    def test_date_shift_preserve_values_in_the_second_rule(self, simple_profile: Profile) -> None:
        config = _config(
            {
                "rules": [
                    _rule("$.a"),
                    _rule("$.b", "date_shift", strategy_config={"preserve_values": "bad"}),
                ]
            }
        )
        for error in _refused(config, simple_profile):
            assert error.code == "date_shift_preserve_values_invalid"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.preserve_values"

    def test_a_keyed_second_rule_makes_the_column_keyed(self) -> None:
        rules = {"rules": [_rule("$.a"), _rule("$.b", "hash")]}
        keyed = column_is_keyed("nested", deterministic=False, vault=False, provider_config=rules)
        assert keyed
        unkeyed = {"rules": [_rule("$.a"), _rule("$.b", "redact")]}
        assert not column_is_keyed(
            "nested", deterministic=False, vault=False, provider_config=unkeyed
        )


class TestRequiredSettingsForRules:
    def test_a_rules_column_needs_no_top_level_target_or_strategy(self) -> None:
        check_required_strategy_settings(_config({"rules": [_rule()]}))

    def test_the_single_form_without_target_is_refused_as_before(self) -> None:
        with pytest.raises(PlanCompileError) as exc:
            check_required_strategy_settings(_config({"strategy": "redact"}))
        assert exc.value.code == "nested_target_unset"
        assert exc.value.path == f"{COL}.provider_config.target"

    @pytest.mark.parametrize(
        ("rule", "code", "leaf"),
        [
            ({"strategy": "redact"}, "nested_target_unset", "target"),
            ({"target": "$.b"}, "nested_strategy_unset", "strategy"),
            ({"target": "", "strategy": "redact"}, "nested_target_unset", "target"),
        ],
    )
    def test_a_rule_missing_a_setting_is_refused_at_its_own_path(
        self, rule: dict[str, Any], code: str, leaf: str, simple_profile: Profile
    ) -> None:
        config = _config({"rules": [_rule("$.a"), rule]})
        for error in _refused(config, simple_profile):
            assert error.code == code
            assert error.path == f"{COL}.provider_config.rules[1].{leaf}"

    def test_unless_present_skips_the_row_only_when_the_value_exists(self) -> None:
        rows = requirements_for("nested")
        assert all(r.unless_present == ("provider_config", "rules") for r in rows)
        with_rules = {"provider_config": {"rules": [_rule()]}}
        without = {"provider_config": {"strategy": "redact"}}
        assert not any(requirement_applies(r, with_rules) for r in rows)
        assert all(requirement_applies(r, without) for r in rows)


def test_a_valid_rules_column_passes_config_only_checks() -> None:
    run_config_only_checks(_config({"rules": [_rule("$.a"), _rule("$.b", "hash")]}))


class TestRuleKeysAreAClosedSet:
    @pytest.mark.parametrize("key", ["when", "namspace", "group_by"])
    def test_an_unknown_rule_key_is_refused_at_its_own_path(
        self, key: str, simple_profile: Profile
    ) -> None:
        config = _config({"rules": [_rule("$.a"), _rule("$.b", **{key: "x"})]})
        for error in _refused(config, simple_profile):
            assert error.code == "nested_rule_key_unknown"
            assert error.path == f"{COL}.provider_config.rules[1].{key}"

    @pytest.mark.parametrize("value", [5, "", "  ", ["ns"], {}])
    def test_a_namespace_that_is_not_a_non_blank_string_is_refused(
        self, value: Any, simple_profile: Profile
    ) -> None:
        config = _config({"rules": [_rule("$.a"), _rule("$.b", "hash", namespace=value)]})
        for error in _refused(config, simple_profile):
            assert error.code == "nested_rule_namespace_invalid"
            assert error.path == f"{COL}.provider_config.rules[1].namespace"

    def test_a_string_namespace_passes(self) -> None:
        run_config_only_checks(_config({"rules": [_rule("$.b", "hash", namespace="customer")]}))


class TestFakerRuleProvider:
    def test_a_faker_rule_without_a_provider_anywhere_is_refused(
        self, simple_profile: Profile
    ) -> None:
        config = _config({"rules": [_rule("$.a"), _rule("$.b", "faker")]})
        for error in _refused(config, simple_profile):
            assert error.code == "nested_rule_faker_provider_missing"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.provider"

    @pytest.mark.parametrize("value", [5, "", " ", None, ["person_email"]])
    @pytest.mark.parametrize("strategy", ["faker", "hash"])
    def test_a_provider_key_that_is_not_a_non_blank_string_is_refused_even_with_a_column_provider(
        self, value: Any, strategy: str, simple_profile: Profile
    ) -> None:
        rule = _rule("$.b", strategy, strategy_config={"provider": value})
        config = _config({"rules": [_rule("$.a"), rule]}, provider="person_email")
        for error in _refused(config, simple_profile):
            assert error.code == "nested_rule_provider_invalid"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.provider"

    def test_an_unknown_rule_provider_is_refused_at_the_rule(self, simple_profile: Profile) -> None:
        rule = _rule("$.b", "faker", strategy_config={"provider": "no_such_provider"})
        for error in _refused(_config({"rules": [_rule("$.a"), rule]}), simple_profile):
            assert error.code == "unknown_provider"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.provider"

    def test_a_non_poolable_rule_provider_is_refused_at_the_rule(
        self, simple_profile: Profile
    ) -> None:
        rule = _rule("$.b", "faker", strategy_config={"provider": "address_full"})
        for error in _refused(_config({"rules": [_rule("$.a"), rule]}), simple_profile):
            assert error.code == "non_poolable_provider_with_pool_backend"
            assert error.path == f"{COL}.provider_config.rules[1].strategy_config.provider"

    def test_a_non_poolable_column_provider_reaches_a_faker_rule(
        self, simple_profile: Profile
    ) -> None:
        config = _config({"rules": [_rule("$.b", "faker")]}, provider="address_full")
        for error in _refused(config, simple_profile):
            assert error.code == "non_poolable_provider_with_pool_backend"

    def test_the_rule_provider_or_the_column_provider_satisfies_it(self) -> None:
        own = _rule("$.b", "faker", strategy_config={"provider": "person_email"})
        run_config_only_checks(_config({"rules": [own]}))
        run_config_only_checks(_config({"rules": [_rule("$.b", "faker")]}, provider="person_email"))


class TestNestedTextMaskRunsTheTopLevelStrategyCheck:
    """A nested `text_mask` child is held to the same detector and strategy check."""

    @pytest.mark.parametrize(
        "strategy_config",
        [
            {"detectors": ["emial"], "unmatched_span_policy": "passthrough"},
            {"per_detector_strategy": {"ssn": "date_shift"}},
        ],
    )
    @pytest.mark.parametrize("form", ["rules", "single"])
    def test_a_bad_nested_text_mask_is_refused_by_both_entry_points(
        self, strategy_config: dict[str, Any], form: str, simple_profile: Profile
    ) -> None:
        child = {"target": "$.note", "strategy": "text_mask", "strategy_config": strategy_config}
        config = _config({"rules": [child]} if form == "rules" else child)
        for error in _refused(config, simple_profile):
            assert error.code in {
                "mask.text_mask_detector_unknown",
                "mask.text_mask_strategy_unsupported",
            }
            at = f"{COL}.provider_config" + (".rules[0]" if form == "rules" else "")
            assert error.path is not None and error.path.startswith(f"{at}.strategy_config.")

    def test_a_valid_nested_text_mask_passes(self) -> None:
        child = {
            "target": "$.note",
            "strategy": "text_mask",
            "strategy_config": {"detectors": ["email"]},
        }
        run_config_only_checks(_config({"rules": [child]}))


class TestCompileResultNamesTheNestedRulesCheck:
    def test_both_entry_points_report_it(
        self, simple_config: dict, simple_profile: Profile
    ) -> None:
        plan = compile_plan(simple_config, simple_profile, decoy_engine_version="0.1.0")
        assert plan.plan_compile.checks_passed[-1] == "nested_rules"
        assert run_config_only_checks(simple_config)[-1] == "nested_rules"
        no_profile = compile_plan(
            simple_config, simple_profile, decoy_engine_version="0.1.0", no_profile=True
        )
        assert "nested_rules" in no_profile.plan_compile.checks_passed
