"""`DeliveryConfig` and the `delivery` field: the default leaves every legacy dump and hash alone."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import (
    DeliveryConfig,
    PipelineConfig,
    PipelineConfigError,
    parse_delivery_config,
    parse_pipeline_config,
)
from decoy_engine.delivery import plan_delivery
from decoy_engine.plan._compile import _hash_config
from decoy_engine.reasons.decoy import PUBLICATION_FAILED

CODE = "delivery_best_effort_unreleased"
_SUMMARY = reasons.get("config", reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED).summary
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BASELINE = json.loads((FIXTURES / "f06" / "legacy-compat-baseline.json").read_text())
# The frozen F06 config predates the required csv has_header; the old default keeps its read.
LEGACY_RAW: dict[str, Any] = {
    **BASELINE["raw_config"],
    "sources": {"p": {**BASELINE["raw_config"]["sources"]["p"], "has_header": True}},
}


def _hash(tmp_path: Path, **extra: Any) -> str:
    raw = copy.deepcopy(LEGACY_RAW)
    (tmp_path / "p.csv").write_text("id,age,note\n1,42,a\n2,7,b\n3,13,c\n")
    raw["sources"]["p"]["path"] = str(tmp_path / "p.csv")
    raw.update(extra)
    # The hash reads the config alone. E3 refuses this undeclared bucketize column at compile.
    return _hash_config(PipelineConfig.model_validate(raw).model_dump())


def test_at10_default_delivery_is_omitted_and_the_legacy_hash_is_unchanged(tmp_path: Path) -> None:
    cfg = PipelineConfig.model_validate(LEGACY_RAW)
    assert cfg.delivery == DeliveryConfig()
    legacy = cfg.model_dump()
    assert "delivery" not in legacy
    assert "delivery" not in json.loads(cfg.model_dump_json())
    del legacy["sources"]["p"]["has_header"]
    dump = json.dumps(legacy, sort_keys=True)
    assert hashlib.sha256(dump.encode()).hexdigest() == BASELINE["config_dump_sha256"]
    assert _hash(tmp_path) == BASELINE["pipeline_config_hash"]
    # Written out as the default is the same config, so the same hash.
    assert _hash(tmp_path, delivery={"mode": "strict"}) == _hash(tmp_path)


def test_at10_best_effort_is_refused_and_delivery_config_still_dumps_it() -> None:
    """BE0: the mode never had an effect, so validation refuses it; the block type still holds it."""
    with pytest.raises(ValidationError) as info:
        PipelineConfig.model_validate({**LEGACY_RAW, "delivery": {"mode": "best_effort"}})
    assert [e["type"] for e in info.value.errors()] == [CODE]
    assert DeliveryConfig(mode="best_effort").model_dump() == {"mode": "best_effort"}


def test_at1_parse_refuses_best_effort_with_one_coded_problem_at_delivery() -> None:
    with pytest.raises(PipelineConfigError) as info:
        parse_pipeline_config({**LEGACY_RAW, "delivery": {"mode": "best_effort"}})
    problems = info.value.problems
    assert [(p.code, p.location) for p in problems] == [(CODE, "delivery")]
    assert problems[0].text == _SUMMARY


@pytest.mark.parametrize("extra", [{}, {"delivery": {"mode": "strict"}}], ids=["omitted", "strict"])
def test_at2_strict_and_omitted_blocks_keep_the_legacy_dump_and_hash(
    tmp_path: Path, extra: dict[str, Any]
) -> None:
    cfg = parse_pipeline_config({**LEGACY_RAW, **extra})
    assert "delivery" not in cfg.model_dump()
    assert _hash(tmp_path, **extra) == BASELINE["pipeline_config_hash"]


def test_at3_the_delivery_block_and_plan_still_accept_best_effort() -> None:
    assert DeliveryConfig.model_validate({"mode": "best_effort"}).mode == "best_effort"
    assert parse_delivery_config({"mode": "best_effort"}).mode == "best_effort"
    config: dict[str, Any] = {
        "tables": [{"name": "p"}, {"name": "c"}],
        "targets": {n: {"type": "file", "path": f"./out/{n}.csv"} for n in ("p", "c")},
        "relationships": [
            {
                "parent": {"table": "p", "columns": ["id"]},
                "children": [{"table": "c", "columns": ["pid"]}],
                "orphan_policy": "fail",
            }
        ],
        "delivery": {"mode": "best_effort"},
    }
    decision = plan_delivery(config, {"p": PUBLICATION_FAILED, "c": None})
    assert {n: t.state for n, t in decision.tables.items()} == {"p": "failed", "c": "dropped"}


def test_at4_the_reason_is_registered_once_in_the_validation_group() -> None:
    assert str(reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED) == CODE
    found = reasons.lookup(CODE)
    assert [(s.namespace, s.owner) for s in found] == [("config", "PipelineValidationError")]


def test_at5_the_refusal_carries_no_submitted_text() -> None:
    sentinel = "SENTINEL-7f3a"
    raw = copy.deepcopy(LEGACY_RAW)
    raw["tables"][0]["columns"][0]["name"] = sentinel
    raw["targets"] = {"p": {"type": "file", "format": "csv", "path": f"./{sentinel}/p.csv"}}
    raw["delivery"] = {"mode": "best_effort"}
    with pytest.raises(PipelineConfigError) as parsed:
        parse_pipeline_config(raw)
    assert sentinel not in str(parsed.value)
    assert all(
        sentinel not in p.text and "input_value" not in p.text for p in parsed.value.problems
    )
    assert "input_value" not in str(parsed.value)
    with pytest.raises(ValidationError) as direct:
        PipelineConfig.model_validate(raw)
    errors = [e for e in direct.value.errors() if e["type"] == CODE]
    assert [e["msg"] for e in errors] == [_SUMMARY]
    assert sentinel not in str(direct.value)


@pytest.mark.parametrize("bad", [{"mode": "loose"}, {"mode": "strict", "extra": 1}])
def test_delivery_config_rejects_unknown_values(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DeliveryConfig.model_validate(bad)
