"""`type: provider` columns are checked at validate and at compile, with fixed-text refusals.

Every refusal is asserted at both sites (`run_config_only_checks`, which `decoy validate` calls,
and `compile_plan`, which `decoy run` calls) with its code and path. Canary cells assert that no
submitted name reaches the error text, the log or the exception chain.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons, run_config_only_checks
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.generation import synthesize
from decoy_engine.generation._window_admission import classify_window_table
from decoy_engine.generation.pinned import PinnedModeError, compile_pinned_plan
from decoy_engine.plan import PlanCompileError, compile_plan
from decoy_engine.plan.checks import DEFERRED
from tests.unit._dps_helpers import empty_profile

CANARY = "CANARY-7731"


def cfg(cols: list[dict[str, Any]], n: int = 5) -> dict[str, Any]:
    return {
        "global_settings": {"seed": 1},
        "tables": [{"name": "t", "row_count": n, "generate_columns": cols}],
    }


def prov(provider: str, name: str = "x", **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": "provider", "provider": provider, **extra}


def p(column: str, key: str | None = None) -> str:
    base = f"tables.t.generate_columns.{column}"
    return base if key is None else f"{base}.{key}"


def _compile(config: dict[str, Any], **kwargs: Any) -> Any:
    kwargs.setdefault("instance_default_locale", None)
    return compile_plan(
        config, empty_profile(), decoy_engine_version="test", sources=NO_SOURCES, **kwargs
    )


def refusal(config: dict[str, Any], site: Any) -> PlanCompileError:
    with pytest.raises(PlanCompileError) as info:
        site(config)
    return info.value


def assert_refused(config: dict[str, Any], code: str, path: str) -> None:
    for site in (run_config_only_checks, _compile):
        exc = refusal(config, site)
        assert (exc.code, exc.path) == (code, path), site.__name__
        assert CANARY not in str(exc) and "7731" not in str(exc)
        assert exc.__cause__ is None and exc.__context__ is None


def assert_accepted(config: dict[str, Any]) -> None:
    run_config_only_checks(config)
    _compile(config)


def test_the_new_codes_are_plan_reasons_with_stable_text() -> None:
    for name in (
        "GENERATE_PROVIDER_UNKNOWN",
        "GENERATE_PROVIDER_UNSUPPORTED",
        "GENERATE_PROVIDER_FIELD_REQUIRED",
        "GENERATE_PROVIDER_FIELD_UNEXPECTED",
        "GENERATE_PROVIDER_LOCALE_UNSUPPORTED",
        "GENERATE_FAKER_TYPE_IS_DOMAIN_PROVIDER",
        "PINNED_PROVIDER_UNSUPPORTED",
    ):
        assert str(getattr(reasons.plan, name)) == name.lower()
    assert str(reasons.runtime.GENERATION_PROVIDER_FAILED) == "generation_provider_failed"


# ---- unknown, unsupported, field and locale refusals ---------------------------------------


def test_an_unknown_provider_is_refused_without_quoting_the_name() -> None:
    assert_refused(cfg([prov(CANARY)]), "generate_provider_unknown", p("x", "provider"))


def test_a_known_provider_of_each_backend_is_accepted() -> None:
    assert_accepted(cfg([prov("synthetic_npi"), prov("person_phone", "y"), prov("uuid", "z")]))


def test_composite_custom_is_unsupported() -> None:
    assert_refused(
        cfg([prov("composite_custom")]), "generate_provider_unsupported", p("x", "provider")
    )


@pytest.mark.parametrize(
    "name",
    ["composite_person", "composite_name_email", "composite_city_state_zip", "composite_address"],
)
def test_every_composite_needs_a_field(name: str) -> None:
    assert_refused(cfg([prov(name)]), "generate_provider_field_required", p("x", "field"))


@pytest.mark.parametrize("key", ["field", "group"])
def test_a_field_or_group_is_unexpected_on_a_scalar_provider(key: str) -> None:
    assert_refused(
        cfg([prov("synthetic_npi", **{key: "a"})]),
        "generate_provider_field_unexpected",
        p("x", key),
    )


# ---- composite fields and groups (GEN-PROVIDERS E2) ------------------------------------------


def comp(
    field: str, name: str | None = None, provider: str = "composite_person", **extra: Any
) -> dict[str, Any]:
    return prov(provider, name or field, field=field, **extra)


def test_a_composite_column_with_a_known_field_is_accepted() -> None:
    assert_accepted(
        cfg(
            [
                comp("first_name"),
                comp("email"),
                comp("zip", provider="composite_city_state_zip"),
                comp("npi", provider="composite_provider"),
            ]
        )
    )


@pytest.mark.parametrize("field", [CANARY, "", "FIRST_NAME", "first_name "])
def test_an_unknown_field_is_refused_without_quoting_it(field: str) -> None:
    assert_refused(cfg([comp(field, "x")]), "generate_provider_field_unknown", p("x", "field"))


def test_a_field_of_another_composite_is_unknown() -> None:
    assert_refused(cfg([comp("zip", "x")]), "generate_provider_field_unknown", p("x", "field"))


def test_a_field_taken_twice_in_one_group_is_refused() -> None:
    config = cfg([comp("email", "a"), comp("first_name", "b"), comp("email", "c")])
    assert_refused(config, "generate_provider_field_duplicate", p("c", "field"))


def test_two_groups_may_take_the_same_field_and_so_may_two_providers() -> None:
    assert_accepted(
        cfg(
            [
                comp("email", "a"),
                comp("email", "b", group="guardian"),
                comp("email", "c", provider="composite_name_email"),
                comp("email", "d", group="composite_person_two"),
            ]
        )
    )


def test_a_group_label_may_be_shared_by_two_providers_without_clashing_fields() -> None:
    assert_accepted(
        cfg(
            [
                comp("zip", "a", provider="composite_address", group="x"),
                comp("zip", "b", provider="composite_city_state_zip", group="x"),
            ]
        )
    )


def test_members_that_declare_different_locales_are_refused() -> None:
    config = cfg([comp("first_name", "a", locale="en_US"), comp("email", "b", locale="en_GB")])
    assert_refused(config, "generate_provider_locale_unsupported", p("b", "locale"))


def test_the_group_check_refuses_two_different_explicit_locales_on_its_own() -> None:
    """No composite declares a second locale yet, so the per-column check fires first at compile;
    the group check must hold for the day one does."""
    from decoy_engine.plan.checks._generate_providers import check_provider_groups

    with pytest.raises(PlanCompileError) as info:
        check_provider_groups(
            "t", [comp("first_name", "a", locale="en_US"), comp("email", "b", locale="en_GB")]
        )
    assert (info.value.code, info.value.path) == (
        "generate_provider_group_mismatch",
        p("b", "locale"),
    )


def test_members_that_mix_an_omitted_and_an_explicit_locale_are_refused() -> None:
    config = cfg([comp("first_name", "a"), comp("email", "b", locale="en_US")])
    assert_refused(config, "generate_provider_group_mismatch", p("b", "locale"))
    config = cfg([comp("first_name", "a", locale="en_US"), comp("email", "b")])
    assert_refused(config, "generate_provider_group_mismatch", p("b", "locale"))


def test_members_that_declare_the_same_locale_are_accepted() -> None:
    assert_accepted(
        cfg([comp("first_name", "a", locale="en_US"), comp("email", "b", locale="en_US")])
    )


def test_members_that_mix_stable_and_fresh_determinism_are_refused() -> None:
    config = cfg([comp("first_name", "a"), comp("email", "b", determinism="fresh")])
    assert_refused(config, "generate_provider_group_mismatch", p("b", "determinism"))
    config = cfg([comp("first_name", "a", determinism="stable"), comp("email", "b")])
    assert_accepted(config)


def test_a_group_of_all_fresh_members_is_accepted() -> None:
    assert_accepted(
        cfg(
            [
                comp("first_name", "a", determinism="fresh"),
                comp("email", "b", determinism="fresh"),
            ]
        )
    )


def test_groups_are_checked_per_table() -> None:
    config = {
        "global_settings": {"seed": 1},
        "tables": [
            {"name": "t", "row_count": 3, "generate_columns": [comp("email", "a")]},
            {"name": "u", "row_count": 3, "generate_columns": [comp("email", "a")]},
        ],
    }
    assert_accepted(config)


def test_a_composite_locale_the_provider_does_not_declare_is_refused() -> None:
    assert_refused(
        cfg([comp("email", "x", locale="fr_FR")]),
        "generate_provider_locale_unsupported",
        p("x", "locale"),
    )


def _config_errors(col: dict[str, Any]) -> list[str]:
    full = {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {},
        "tables": [{"name": "t", "row_count": 3, "generate_columns": [col]}],
        "targets": {"t": {"type": "file", "format": "csv", "path": "o.csv"}},
    }
    with pytest.raises(ValidationError) as info:
        PipelineConfig.model_validate(full)
    return [str(e["type"]) for e in info.value.errors()]


def test_unique_is_refused_on_a_provider_column() -> None:
    errors = _config_errors(prov("synthetic_npi", unique=True))
    assert str(reasons.config.GENERATE_UNIQUE_UNSUPPORTED) in errors


def test_a_locale_the_provider_does_not_declare_is_refused() -> None:
    assert_refused(
        cfg([prov("synthetic_npi", locale="fr_FR")]),
        "generate_provider_locale_unsupported",
        p("x", "locale"),
    )
    assert_refused(
        cfg([prov("person_phone", locale="fr_FR")]),
        "generate_provider_locale_unsupported",
        p("x", "locale"),
    )


def test_a_declared_locale_passes_and_a_locale_free_identifier_takes_any_engine_locale() -> None:
    assert_accepted(cfg([prov("synthetic_npi", locale="en_US")]))
    assert_accepted(cfg([prov("synthetic_iban", locale="fr_FR")]))
    assert_accepted(cfg([prov("synthetic_cusip", locale="en_CA")]))


def test_cusip_en_ca_passes_the_compile_path_and_fr_fr_does_not() -> None:
    assert_accepted(cfg([prov("synthetic_cusip", locale="en_CA")]))
    assert_accepted(cfg([prov("synthetic_cusip", locale="en_US")]))
    assert_refused(
        cfg([prov("synthetic_cusip", locale="fr_FR")]),
        "generate_provider_locale_unsupported",
        p("x", "locale"),
    )


@pytest.mark.parametrize("bad", [{"provider": 5}, {"locale": ["en_US"]}, {"field": 3}])
def test_a_non_string_option_is_a_config_error_not_a_coercion(bad: dict[str, Any]) -> None:
    errors = _config_errors({**prov("synthetic_npi"), **bad})
    assert str(reasons.config.GENERATE_OPTION_TYPE) in errors


def test_the_provider_key_is_required() -> None:
    assert "missing" in _config_errors({"name": "x", "type": "provider"})


# ---- faker hint ------------------------------------------------------------------------------


def test_a_registry_name_in_faker_type_points_at_the_provider_type() -> None:
    col = {"name": "x", "type": "faker", "faker_type": "synthetic_npi"}
    assert_refused(cfg([col]), "generate_faker_type_is_domain_provider", p("x", "faker_type"))


def test_an_unknown_faker_type_keeps_the_generic_refusal() -> None:
    col = {"name": "x", "type": "faker", "faker_type": "not_real"}
    assert_refused(cfg([col]), "generate_faker_type_unknown", p("x", "faker_type"))


# ---- the platform default locale -------------------------------------------------------------

LOCALE_CODE = "generate_provider_locale_unsupported"


def _plan(config: dict[str, Any]) -> Any:
    return compile_plan(config, empty_profile(), decoy_engine_version="test", sources=NO_SOURCES)


@pytest.mark.parametrize("default", ["fr_FR", "de_DE"])
def test_the_instance_default_locale_is_checked_at_every_choke_point(
    default: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = cfg([prov("synthetic_npi")])
    for site in (run_config_only_checks, _compile):
        with pytest.raises(PlanCompileError) as info:
            site(config, instance_default_locale=default)
        assert (info.value.code, info.value.path) == (LOCALE_CODE, p("x", "locale"))
    _compile(config, instance_default_locale=DEFERRED)  # a plan generated later
    plan = _plan(config)
    monkeypatch.setattr(
        "decoy_engine.generation._streamed.GenerationBudgetLedger",
        lambda *a, **k: pytest.fail("generation started"),
    )
    with pytest.raises(PlanCompileError) as info:
        synthesize.generate_tables(plan, instance_default_locale=default)
    assert info.value.code == LOCALE_CODE and info.value.__context__ is None
    with pytest.raises(PlanCompileError) as info:
        classify_window_table(config, "t", statistical_specs={}, instance_default_locale=default)
    assert info.value.code == LOCALE_CODE


def test_an_instance_default_of_en_ca_passes_for_cusip_and_refuses_npi() -> None:
    cusip = cfg([prov("synthetic_cusip")])
    run_config_only_checks(cusip, instance_default_locale="en_CA")
    _compile(cusip, instance_default_locale="en_CA")
    assert synthesize.generate_tables(_plan(cusip), instance_default_locale="en_CA")["t"].num_rows
    with pytest.raises(PlanCompileError) as info:
        run_config_only_checks(cfg([prov("synthetic_npi")]), instance_default_locale="en_CA")
    assert info.value.code == LOCALE_CODE


def test_a_column_locale_overrides_the_instance_default() -> None:
    config = cfg([prov("synthetic_npi", locale="en_US")])
    out = synthesize.generate_tables(_plan(config), instance_default_locale="fr_FR")
    assert out["t"].num_rows == 5


# ---- pinned ----------------------------------------------------------------------------------


def test_pinned_compile_refuses_a_provider_column() -> None:
    config = cfg([prov("synthetic_npi")])
    config["global_settings"]["reference_date"] = "2026-10-22T09:30:00Z"
    with pytest.raises(PinnedModeError) as info:
        compile_pinned_plan(config)
    assert info.value.code == "pinned_provider_unsupported"


def test_a_refusal_leaves_nothing_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        refusal(cfg([prov(CANARY)]), _compile)
    assert CANARY not in caplog.text
