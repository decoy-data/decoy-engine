"""AT-A8a (engine half): a `targets:` key that names no configured table is refused.

Fail-before: the key was accepted, the writers skipped it, and the run exited 0 with no file.
A source name alone is not a valid target key.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig, PipelineConfigError, parse_pipeline_config

CODE = "target_table_unknown"
CANARY = "CANARYVALUE"


def _file(path: str) -> dict[str, Any]:
    return {"type": "file", "format": "csv", "path": path}


def _config(targets: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {
            "customers": {"type": "file", "format": "csv", "has_header": True, "path": "in.csv"}
        },
        "tables": [
            {
                "name": "orders",
                "row_count": 3,
                "generate_columns": [{"name": "id", "type": "sequence", "start": 1, "step": 1}],
            }
        ],
        "targets": targets,
    }


def _locs(exc: ValidationError) -> list[tuple[Any, ...]]:
    return [e["loc"] for e in exc.errors() if e["type"] == CODE]


def test_a_target_key_naming_no_table_is_refused() -> None:
    with pytest.raises(ValidationError) as err:
        PipelineConfig.model_validate(_config({"custmers": _file("c.csv")}))
    assert _locs(err.value) == [("targets", "custmers")]
    assert reasons.find("config", CODE) is not None


def test_a_source_name_alone_is_not_a_valid_target_key() -> None:
    with pytest.raises(ValidationError) as err:
        PipelineConfig.model_validate(
            _config({"orders": _file("o.csv"), "customers": _file("c.csv")})
        )
    assert _locs(err.value) == [("targets", "customers")]


def test_every_unknown_key_is_reported_in_config_order() -> None:
    targets = {"zeta": _file("z.csv"), "orders": _file("o.csv"), "alpha": _file("a.csv")}
    with pytest.raises(ValidationError) as err:
        PipelineConfig.model_validate(_config(targets))
    assert _locs(err.value) == [("targets", "zeta"), ("targets", "alpha")]


def test_the_public_parser_reports_the_code_and_no_value() -> None:
    raw = _config({f"{CANARY}x": _file(f"/{CANARY}/p.csv")})
    with pytest.raises(PipelineConfigError) as err:
        parse_pipeline_config(raw)
    assert {p.code for p in err.value.problems} == {CODE}
    assert CANARY not in str(err.value).replace(f"{CANARY}x", "")
    assert f"/{CANARY}/p.csv" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__context__ is None


def test_a_matching_target_still_validates() -> None:
    PipelineConfig.model_validate(_config({"orders": _file("o.csv")}))


def test_unknown_and_shared_problems_are_both_reported() -> None:
    raw = _config({"orders": _file("x.csv"), "ghost": _file("y.csv")})
    raw["tables"].append(
        {
            "name": "items",
            "row_count": 1,
            "generate_columns": [{"name": "id", "type": "sequence", "start": 1, "step": 1}],
        }
    )
    raw["targets"]["items"] = _file("x.csv")
    with pytest.raises(ValidationError) as err:
        PipelineConfig.model_validate(raw)
    kinds = {e["type"] for e in err.value.errors()}
    assert kinds == {CODE, "target_shared_destination"}
