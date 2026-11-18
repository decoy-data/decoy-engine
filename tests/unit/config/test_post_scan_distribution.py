"""DI-T1 and DI-T13 (config half): `post_scan.distribution` and its frozen schema entry (row 31).

The block needs `integrity: true`, takes a strict tolerance in (0, 100] and `on_breach: warn` only
until the blocking slice, is dropped from the dump while absent and hashed when set. All values are
made up.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig, post_scan_distribution_tolerance
from decoy_engine.plan._compile import _hash_config
from decoy_engine.reasons import UNRELEASED

BASE: dict[str, Any] = {
    "version": 2,
    "global_settings": {"seed": 7},
    "sources": {"p": {"type": "file", "format": "csv", "has_header": True, "path": "/data/p.csv"}},
    "tables": [{"name": "p", "columns": [{"name": "id", "strategy": "hash", "namespace": "ids"}]}],
    "targets": {"p": {"type": "file", "format": "csv", "path": "/data/o.csv"}},
}
SNAPSHOT = (
    Path(__file__).parents[2] / "snapshots" / "frozen_schemas" / "pipeline-config.schema.json"
)


def _cfg(post_scan: dict[str, Any] | None) -> dict[str, Any]:
    raw = copy.deepcopy(BASE)
    if post_scan is not None:
        raw["post_scan"] = post_scan
    return raw


def _types(raw: dict[str, Any]) -> set[str]:
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(raw)
    return {e["type"] for e in caught.value.errors()}


def test_a_distribution_block_without_integrity_is_refused_as_inactive() -> None:
    types = _types(_cfg({"distribution": {"tolerance_pct": 5}}))
    assert str(reasons.config.POST_SCAN_INACTIVE) in types


def test_a_distribution_block_with_integrity_validates_and_dumps_back() -> None:
    cfg = PipelineConfig.model_validate(
        _cfg({"integrity": True, "distribution": {"tolerance_pct": 5}})
    )
    dumped = cfg.model_dump()
    assert dumped["post_scan"]["distribution"] == {"tolerance_pct": 5.0, "on_breach": "warn"}
    assert post_scan_distribution_tolerance(dumped) == 5.0


@pytest.mark.parametrize("value", [1, 5, 5.5, 100, 100.0, 0.0001])
def test_a_tolerance_inside_the_bounds_is_accepted(value: float) -> None:
    raw = _cfg({"integrity": True, "distribution": {"tolerance_pct": value}})
    assert (
        post_scan_distribution_tolerance(PipelineConfig.model_validate(raw).model_dump()) == value
    )


@pytest.mark.parametrize(
    "value", [0, 0.0, -1, 101, 100.0001, True, False, "5", None, float("nan"), float("inf"), [5]]
)
def test_a_tolerance_outside_the_bounds_or_of_the_wrong_type_is_refused(value: Any) -> None:
    _types(_cfg({"integrity": True, "distribution": {"tolerance_pct": value}}))


def test_a_tolerance_is_required() -> None:
    _types(_cfg({"integrity": True, "distribution": {}}))


@pytest.mark.parametrize("on_breach", ["fail", "block", "warning", "", None, True])
def test_only_warn_is_accepted_for_on_breach_until_the_blocking_slice(on_breach: Any) -> None:
    _types(_cfg({"integrity": True, "distribution": {"tolerance_pct": 5, "on_breach": on_breach}}))


def test_an_unknown_key_in_the_block_is_refused() -> None:
    _types(_cfg({"integrity": True, "distribution": {"tolerance_pct": 5, "extra": 1}}))


def test_an_omitted_block_keeps_the_old_dump_and_plan_hash() -> None:
    plain = PipelineConfig.model_validate(_cfg({"integrity": True})).model_dump()
    assert "distribution" not in plain["post_scan"]
    assert "distribution" not in PipelineConfig.model_validate(_cfg(None)).model_dump().get(
        "post_scan", {}
    )
    with_none = PipelineConfig.model_validate(
        _cfg({"integrity": True, "distribution": None})
    ).model_dump()
    assert with_none == plain
    assert _hash_config(with_none) == _hash_config(plain)


def test_a_set_block_moves_the_dump_and_the_plan_hash() -> None:
    plain = PipelineConfig.model_validate(_cfg({"integrity": True})).model_dump()
    five = PipelineConfig.model_validate(
        _cfg({"integrity": True, "distribution": {"tolerance_pct": 5}})
    ).model_dump()
    ten = PipelineConfig.model_validate(
        _cfg({"integrity": True, "distribution": {"tolerance_pct": 10}})
    ).model_dump()
    assert len({_hash_config(plain), _hash_config(five), _hash_config(ten)}) == 3


def test_the_tolerance_reader_trusts_only_an_enabled_suite() -> None:
    assert post_scan_distribution_tolerance({}) is None
    assert post_scan_distribution_tolerance({"post_scan": {"integrity": True}}) is None
    off = {"post_scan": {"integrity": False, "distribution": {"tolerance_pct": 5}}}
    assert post_scan_distribution_tolerance(off) is None


# ----- DI-T13: the frozen config schema ----------------------------------------------------


def test_the_frozen_schema_holds_distribution_with_its_bounds_and_enum() -> None:
    schema = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    assert "distribution" in defs["PostScanConfig"]["properties"]
    block = defs["DistributionCheck"]
    assert block["required"] == ["tolerance_pct"]
    tolerance = block["properties"]["tolerance_pct"]
    assert (tolerance["exclusiveMinimum"], tolerance["maximum"]) == (0, 100)
    assert block["properties"]["on_breach"]["const"] == "warn"
    assert block["additionalProperties"] is False


def test_the_deferred_refusal_is_registered_pending_with_fixed_value_free_text() -> None:
    spec = reasons.get("runtime", "post_scan_distribution_deferred")
    assert spec.since == UNRELEASED
    assert reasons.runtime.POST_SCAN_DISTRIBUTION_DEFERRED == "post_scan_distribution_deferred"
    assert not any(c in spec.summary for c in "{}%")
    assert {r.outcome.value for r in spec.rules} == {"configuration"}
    assert {r.retry.value for r in spec.rules} == {"configuration_repair"}
