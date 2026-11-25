"""A credential-bearing code_set corpus locator is refused before any plan exists.

The locator would otherwise be copied verbatim into the plan YAML and every file the CLI writes
from it. A clean URL and a local path still pass.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.plan import PlanCompileError, compile_plan, plan_to_yaml
from decoy_engine.plan._checks_code_set_locator import check_code_set_corpus_locators
from decoy_engine.plan._compile import run_config_only_checks
from decoy_engine.profile import Profile

_PW = "ZQX-PASSWORD-7731"
_TOK = "ZQX-TOKEN-5519"
_BAD = [
    f"customer:s3://svc:{_PW}@bucket/key.parquet",
    f"customer:https://host.example/c.parquet?token={_TOK}",
    f"customer:https://host.example/c.parquet#{_TOK}",
    f"customer:https://svc:pa/{_PW}@host/c.parquet",
    f"customer:https:\\\\svc:{_PW}@host\\c.parquet",
]
_CLEAN = [
    "customer:https://host.example/corpora/c.parquet",
    "customer:s3://bucket/corpora/c.parquet",
    "customer:/data/corpora/c.parquet",
    "customer:/tmp/archive:/alice@local/file.parquet",
    "customer:C:\\data\\c.parquet",
    "shipped",
]


def _config(source: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(base) if base else {"tables": [{"name": "t", "columns": []}]}
    cfg["tables"][0]["columns"].append(
        {
            "name": "dx",
            "strategy": "code_set",
            "namespace": "dx_ns",
            "provider_config": {"code_set": "icd10", "corpus_source": source},
        }
    )
    return cfg


@pytest.mark.parametrize("source", _BAD)
def test_a_credential_bearing_locator_is_refused_value_free(source: str) -> None:
    with pytest.raises(PlanCompileError) as info:
        check_code_set_corpus_locators(_config(source))
    assert info.value.code == "code_set_corpus_source_credentials"
    text = str(info.value)
    assert _PW not in text and _TOK not in text


@pytest.mark.parametrize("source", _CLEAN)
def test_a_clean_url_or_local_path_passes(source: str) -> None:
    check_code_set_corpus_locators(_config(source))


@pytest.mark.parametrize("source", _BAD[:2])
def test_validate_refuses_before_a_plan_exists(source: str) -> None:
    with pytest.raises(PlanCompileError) as info:
        run_config_only_checks(_config(source))
    assert info.value.code == "code_set_corpus_source_credentials"


def test_a_nested_column_locator_is_refused_too() -> None:
    cfg = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {
                        "name": "j",
                        "strategy": "nested",
                        "provider_config": {
                            "children": [
                                {"provider_config": {"corpus_source": _BAD[0]}},
                            ]
                        },
                    }
                ],
            }
        ]
    }
    with pytest.raises(PlanCompileError):
        check_code_set_corpus_locators(cfg)


def test_compile_never_yields_a_plan_holding_the_secret(
    simple_config: dict, simple_profile: Profile
) -> None:
    with pytest.raises(PlanCompileError) as info:
        compile_plan(
            _config(_BAD[0], simple_config),
            simple_profile,
            decoy_engine_version="0.1.0",
            sources=NO_SOURCES,
        )
    assert info.value.code == "code_set_corpus_source_credentials"
    # The clean control compiles and its locator round-trips into the plan YAML.
    plan = compile_plan(
        _config("customer:/data/corpora/c.parquet", simple_config),
        simple_profile,
        decoy_engine_version="0.1.0",
        sources=NO_SOURCES,
    )
    assert _PW not in plan_to_yaml(plan)
