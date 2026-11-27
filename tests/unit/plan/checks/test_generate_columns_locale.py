"""GEN-STREAM-ALL S1a Codex fixes: validation and generation agree on the Faker a column gets.

Two cases the plan-time faker check got wrong:

* ``["it", "it_IT"]`` resolves to one locale name but Faker keeps both keys and builds a
  multi-locale proxy, which refuses single-factory helpers such as ``del_arguments``. Validation
  accepted the column and generation then emitted ``word`` values.
* A column without ``locale`` runs in the platform default. Only the column's own locale was
  checked, so an unknown default fell back to ``en_US`` inside ``make_faker`` unseen.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine import run_config_only_checks
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.internal.faker_locale import is_single_factory
from decoy_engine.internal.faker_setup import make_faker
from decoy_engine.plan import PlanCompileError, compile_plan
from decoy_engine.plan.checks import check_faker_default_locale
from tests.unit._dps_helpers import empty_profile


def _config(col: dict[str, Any]) -> dict[str, Any]:
    return {
        "global_settings": {"seed": 1},
        "tables": [{"name": "t", "row_count": 3, "generate_columns": [col]}],
    }


def _col(**extra: Any) -> dict[str, Any]:
    return {"name": "f", "type": "faker", "faker_type": "del_arguments", **extra}


def _compile(config: dict[str, Any], **kwargs: Any) -> Any:
    kwargs.setdefault("instance_default_locale", None)
    return compile_plan(
        config, empty_profile(), decoy_engine_version="test", sources=NO_SOURCES, **kwargs
    )


# Locale values whose resolved names collapse (`it` is `it_IT`, `en-US` is `en_US`) next to ones
# that do not. Faker, not the resolver, decides how many factories each one opens.
LOCALES: list[Any] = [
    "it",
    ["it"],
    ["it", "it_IT"],
    ["it_IT", "it"],
    ["it_IT", "it_IT"],
    ["en-US", "en_US"],
    ["en-US", "en_GB"],
    ["de_AT", "it_IT"],
    ["", "en_US"],
    ["en_US", ""],
    [""],
]


@pytest.mark.parametrize("locale", LOCALES, ids=repr)
def test_validation_accepts_a_single_factory_helper_exactly_when_faker_opens_one_factory(
    locale: Any,
) -> None:
    """`del_arguments` exists only on a real single-locale Faker; generation decides which."""
    single = len(make_faker(locale).factories) == 1
    config = _config(_col(locale=locale))
    if single:
        run_config_only_checks(config)
        _compile(config)
        return
    for site in (run_config_only_checks, _compile):
        with pytest.raises(PlanCompileError) as info:
            site(config)
        assert (info.value.code, info.value.path) == (
            "generate_faker_type_unknown",
            "tables.t.generate_columns.f.faker_type",
        )


@pytest.mark.parametrize("locale", LOCALES, ids=repr)
def test_the_shared_single_factory_rule_matches_what_faker_builds(locale: Any) -> None:
    assert is_single_factory(locale) == (len(make_faker(locale).factories) == 1)


# ---- the platform default locale ---------------------------------------------------------------


def _prefix(**extra: Any) -> dict[str, Any]:
    return {"name": "f", "type": "faker", "faker_type": "prefix", **extra}


def test_an_unknown_platform_default_locale_refuses_a_column_without_locale() -> None:
    config = _config(_prefix())
    expected = ("generate_locale_unknown", "tables.t.generate_columns.f.locale")
    for site in (
        lambda c: run_config_only_checks(c, instance_default_locale="xx_YY"),
        lambda c: _compile(c, instance_default_locale="xx_YY"),
        lambda c: check_faker_default_locale(c, "xx_YY"),
    ):
        with pytest.raises(PlanCompileError) as info:
            site(config)
        assert (info.value.code, info.value.path) == expected
        assert "xx_YY" not in str(info.value)


def test_a_column_locale_overrides_an_unknown_platform_default() -> None:
    config = _config(_prefix(locale="en_GB"))
    run_config_only_checks(config, instance_default_locale="xx_YY")
    _compile(config, instance_default_locale="xx_YY")
    check_faker_default_locale(config, "xx_YY")


@pytest.mark.parametrize("default", [None, "en_US", "en-GB"])
def test_a_known_platform_default_locale_is_accepted(default: str | None) -> None:
    config = _config(_prefix())
    run_config_only_checks(config, instance_default_locale=default)
    _compile(config, instance_default_locale=default)
    check_faker_default_locale(config, default)
