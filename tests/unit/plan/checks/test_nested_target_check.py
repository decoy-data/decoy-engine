"""NESTED-FREEZE A1, A7: a `nested` target outside the subset does not compile or validate."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.plan import PlanCompileError, compile_plan
from decoy_engine.plan._compile import run_config_only_checks
from decoy_engine.profile import Profile

_ACCEPTED = [
    "$",
    "$.a",
    "$.a.b.c",
    "$.*",
    "$[*]",
    "$['a']",
    '$["a b"]',
    "$['a\\'b']",
    "$['\\u00e9']",
    "$.a['b']",
    "$[0]",
    "$[-1]",
    "$[0:1]",
    "$[1:]",
    "$[:2]",
    "$[:]",
    "$[::2]",
    "$[0:4:2]",
    "$[1:2:]",
    "$.dates[*]",
    "$.users[*].email",
    "$.items[*].k",
    "$.wrapper[:]",
    "$.user.email",
    "$._x1",
]
_REFUSED = [
    "$..a",
    "$..*",
    "$..['a']",
    "a.b",
    "$.'b c'",
    "$.a | $.b",
    "$.a.`this`",
    "`this`",
    "$[0,1]",
    "$['a','b']",
    "$[?(@.b)]",
    "$['*']",
    '$["*"]',
    "$[::-1]",
    "$[::0]",
    "$[01]",
    "$[-0]",
    "$ .a",
    "$.x[",
    "$.a\n",
    " $.a",
    "$.a ",
    "$.a\t",
    "$.a where b",
    "$.a & $.b",
    "$[length(@)]",
]


def _config(target: Any) -> dict[str, Any]:
    return {
        "global_settings": {"seed": 1},
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {
                        "name": "name",
                        "strategy": "nested",
                        "provider_config": {"target": target, "strategy": "redact"},
                    }
                ],
            }
        ],
    }


def _compilable(base: dict, target: Any) -> dict:
    """The conftest config that compiles against `simple_profile`, with its column made nested."""
    column = {
        "name": "name",
        "strategy": "nested",
        "provider_config": {"target": target, "strategy": "redact"},
    }
    base["tables"][0]["columns"] = [column]
    return base


@pytest.mark.parametrize("target", _ACCEPTED)
def test_a1_accepted_target_passes_validate(target: str) -> None:
    run_config_only_checks(_config(target))


@pytest.mark.parametrize("target", _REFUSED)
def test_a1_refused_target_fails_validate_with_the_code(target: str) -> None:
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(_config(target))
    assert exc.value.code == "nested_target_unsupported"
    assert exc.value.path == "tables.customers.columns.name.provider_config.target"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


@pytest.mark.parametrize("target", _REFUSED)
def test_a1_refused_target_fails_compile_plan_with_the_code(
    target: str, simple_config: dict, simple_profile: Profile
) -> None:
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(
            _compilable(simple_config, target),
            simple_profile,
            decoy_engine_version="0.1.0",
            sources=NO_SOURCES,
        )
    assert exc.value.code == "nested_target_unsupported"


@pytest.mark.parametrize("target", _ACCEPTED)
def test_a1_accepted_target_passes_compile_plan(
    target: str, simple_config: dict, simple_profile: Profile
) -> None:
    compile_plan(
        _compilable(simple_config, target),
        simple_profile,
        decoy_engine_version="0.1.0",
        sources=NO_SOURCES,
    )


def test_message_names_position_form_and_target() -> None:
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(_config("$.a..b"))
    message = exc.value.message
    assert "table 'customers', column 'name'" in message
    assert "descendant segment at position 3" in message
    assert "'$.a..b'" in message


def test_a7_long_target_is_cut_at_64_characters() -> None:
    target = "$.a.." + "b" * 195
    assert len(target) == 200
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(_config(target))
    message = exc.value.message
    assert "first 64 of 200 characters" in message
    assert target[:64] in message and target[:65] not in message


def test_unset_or_non_text_target_keeps_its_own_refusal_path() -> None:
    for target in (None, "", 5):
        with pytest.raises(PlanCompileError) as exc:
            run_config_only_checks(_config(target))
        assert exc.value.code == "nested_target_unset"


def test_other_strategies_are_not_read() -> None:
    config = _config("$..a")
    config["tables"][0]["columns"][0]["strategy"] = "redact"
    run_config_only_checks(config)
