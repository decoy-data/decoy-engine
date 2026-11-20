"""SCAN-MULTI S3-engine.1: `scan_baseline` and the reserved namespace placeholder.

T3-config-field: the field accepts only the `scan-set/v1` tag and a config without it is
unchanged. T3-placeholder (validator half): a namespace holding the placeholder prefix is
refused with `config.namespace_placeholder_unset` at the field path, any other value passes.
T3-placeholder-error-value-free: the error carries the path and the code, never the value.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig, RelationshipConfig
from decoy_engine.config._namespaces import NAMESPACE_PLACEHOLDER_PREFIX
from decoy_engine.profiling.scan_set import SCAN_SET_SCHEMA

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BASELINE = json.loads((FIXTURES / "f06" / "legacy-compat-baseline.json").read_text())
RAW: dict[str, Any] = {
    **BASELINE["raw_config"],
    "sources": {"p": {**BASELINE["raw_config"]["sources"]["p"], "has_header": True}},
}
CANARY = "CANARY-9c3e41"


def _raw(**extra: Any) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    raw.update(extra)
    return raw


def _with_column_namespace(value: object) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    raw["tables"][0]["columns"][0]["namespace"] = value
    return raw


def _relationship(namespace: object) -> dict[str, Any]:
    return {
        "parent": {"table": "a", "columns": ["id"]},
        "children": [{"table": "b", "columns": ["a_id"]}],
        "orphan_policy": "fail",
        "namespace": namespace,
    }


def test_the_tag_matches_the_scan_set_schema() -> None:
    assert SCAN_SET_SCHEMA == "scan-set/v1"


def test_scan_baseline_round_trips() -> None:
    cfg = PipelineConfig.model_validate(
        _raw(scan_baseline={"path": ".decoy/library/x.json", "schema": SCAN_SET_SCHEMA})
    )
    assert cfg.model_dump()["scan_baseline"] == {
        "path": ".decoy/library/x.json",
        "schema": "scan-set/v1",
    }
    again = PipelineConfig.model_validate(cfg.model_dump())
    assert again.model_dump() == cfg.model_dump()


def test_scan_baseline_dumps_write_schema_in_every_form() -> None:
    cfg = PipelineConfig.model_validate(
        _raw(scan_baseline={"path": "x.json", "schema": SCAN_SET_SCHEMA})
    )
    want = {"path": "x.json", "schema": "scan-set/v1"}
    assert cfg.model_dump()["scan_baseline"] == want
    assert cfg.model_dump(by_alias=True)["scan_baseline"] == want
    assert cfg.model_dump(mode="json", by_alias=True)["scan_baseline"] == want
    assert json.loads(cfg.model_dump_json(by_alias=True))["scan_baseline"] == want
    assert json.loads(cfg.model_dump_json())["scan_baseline"] == want


def test_scan_baseline_absent_leaves_the_dump_unchanged() -> None:
    cfg = PipelineConfig.model_validate(_raw())
    assert cfg.scan_baseline is None
    assert "scan_baseline" not in cfg.model_dump()
    assert "scan_baseline" not in cfg.model_dump(mode="json")


@pytest.mark.parametrize("tag", ["scan-set/v2", "", "scan-set/v1 ", None, 1])
def test_scan_baseline_refuses_another_schema_tag(tag: object) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(_raw(scan_baseline={"path": "x.json", "schema": tag}))


@pytest.mark.parametrize(
    "bad",
    [
        {"path": "x.json"},
        {"schema": "scan-set/v1"},
        {"path": "x.json", "schema": "scan-set/v1", "record_id": "r"},
        {"path": 3, "schema": "scan-set/v1"},
        "x.json",
    ],
)
def test_scan_baseline_refuses_other_shapes(bad: object) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(_raw(scan_baseline=bad))


def test_the_placeholder_identity_is_registered() -> None:
    spec = reasons.REASONS[("config", "namespace_placeholder_unset")]
    assert str(reasons.config.NAMESPACE_PLACEHOLDER_UNSET) == "namespace_placeholder_unset"
    assert spec.since == "1.27.0"


@pytest.mark.parametrize("n", [1, 2, 17])
def test_a_column_placeholder_is_refused_at_its_path(n: int) -> None:
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(_with_column_namespace(f"decoy-set-namespace-{n}"))
    errors = caught.value.errors()
    assert [e["type"] for e in errors] == ["namespace_placeholder_unset"]
    assert errors[0]["loc"] == ("tables", 0, "columns", 0, "namespace")


def test_the_bare_prefix_is_refused() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(_with_column_namespace(NAMESPACE_PLACEHOLDER_PREFIX))


@pytest.mark.parametrize(
    "value", ["cust", "decoy-set-namespace", "Decoy-set-namespace-1", " x", None]
)
def test_other_namespaces_pass(value: object) -> None:
    PipelineConfig.model_validate(_with_column_namespace(value))


def test_a_relationship_placeholder_is_refused_at_its_path() -> None:
    with pytest.raises(ValidationError) as caught:
        RelationshipConfig.model_validate(_relationship("decoy-set-namespace-1"))
    errors = caught.value.errors()
    assert [e["type"] for e in errors] == ["namespace_placeholder_unset"]
    assert errors[0]["loc"] == ("namespace",)
    RelationshipConfig.model_validate(_relationship("cust"))


def test_the_pipeline_path_names_a_relationship_placeholder() -> None:
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(_raw(relationships=[_relationship("decoy-set-namespace-2")]))
    locs = [e["loc"] for e in caught.value.errors() if e["type"] == "namespace_placeholder_unset"]
    assert locs == [("relationships", 0, "namespace")]


def test_the_error_is_value_free() -> None:
    """M3-echo: the text names the code and the path, never the submitted value."""
    value = f"decoy-set-namespace-{CANARY}"
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(_with_column_namespace(value))
    # errors() keeps pydantic's own `input` key for every field; type, msg and loc are value-free.
    assert CANARY not in str(caught.value)
    assert all(CANARY not in f"{e['type']}{e['msg']}{e['loc']}" for e in caught.value.errors())
    assert "namespace_placeholder_unset" in str(caught.value)
    with pytest.raises(ValidationError) as rel:
        RelationshipConfig.model_validate(_relationship(value))
    assert CANARY not in str(rel.value)
    assert all(CANARY not in f"{e['type']}{e['msg']}{e['loc']}" for e in rel.value.errors())


# SCAN-CHECKS D-1: `on_drift` is the opt-in drift check of a run.
BASELINE_PTR = {"path": ".decoy/library/x.json", "schema": SCAN_SET_SCHEMA}


DIGEST = "3f1c" + "0" * 56 + "e9ab"


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_d_t1_on_drift_accepts_warn_and_fail(mode: str) -> None:
    cfg = PipelineConfig.model_validate(
        _raw(scan_baseline={**BASELINE_PTR, "on_drift": mode, "sha256": DIGEST})
    )
    assert cfg.model_dump()["scan_baseline"]["on_drift"] == mode
    again = PipelineConfig.model_validate(cfg.model_dump())
    assert again.model_dump() == cfg.model_dump()


@pytest.mark.parametrize("bad", ["block", "WARN", "", True, False, 1])
def test_d_t1_on_drift_refuses_other_values(bad: object) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(_raw(scan_baseline={**BASELINE_PTR, "on_drift": bad}))


def test_d_t1_absent_on_drift_keeps_the_old_dump() -> None:
    cfg = PipelineConfig.model_validate(_raw(scan_baseline=BASELINE_PTR))
    assert cfg.model_dump()["scan_baseline"] == BASELINE_PTR
    assert "on_drift" not in cfg.model_dump(by_alias=True)["scan_baseline"]
    assert "on_drift" not in json.loads(cfg.model_dump_json())["scan_baseline"]


def test_d_t1_an_explicit_null_on_drift_means_no_check_and_is_not_dumped() -> None:
    cfg = PipelineConfig.model_validate(_raw(scan_baseline={**BASELINE_PTR, "on_drift": None}))
    assert cfg.model_dump()["scan_baseline"] == BASELINE_PTR


# F15 E2: `sha256` binds the baseline bytes; `on_drift: fail` needs it (F15-T6).
def _block(**extra: Any) -> dict[str, Any]:
    return _raw(scan_baseline={**BASELINE_PTR, **extra})


def test_f15_t6_a_lowercase_digest_is_accepted_and_round_trips() -> None:
    cfg = PipelineConfig.model_validate(_block(sha256=DIGEST))
    assert cfg.model_dump()["scan_baseline"] == {**BASELINE_PTR, "sha256": DIGEST}
    assert PipelineConfig.model_validate(cfg.model_dump()).model_dump() == cfg.model_dump()
    assert json.loads(cfg.model_dump_json(by_alias=True))["scan_baseline"]["sha256"] == DIGEST


@pytest.mark.parametrize(
    "bad",
    [
        DIGEST.upper(),
        DIGEST[:-1],
        DIGEST + "0",
        DIGEST + "\n",
        "g" * 64,
        "",
        True,
        7,
        int("1" * 64),
    ],
)
def test_f15_t6_a_malformed_digest_is_refused(bad: object) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(_block(sha256=bad))


def test_f15_t6_fail_without_a_digest_is_refused_naming_the_field_and_no_value() -> None:
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(_block(on_drift="fail"))
    errors = caught.value.errors()
    assert [e["type"] for e in errors] == ["scan_baseline_unbound"]
    assert errors[0]["loc"] == ("scan_baseline",)
    assert "scan_baseline.sha256" in errors[0]["msg"]
    assert ".decoy/library/x.json" not in str(caught.value)


def test_f15_t6_the_unbound_code_is_registered_pending() -> None:
    spec = reasons.REASONS[("config", "scan_baseline_unbound")]
    assert str(reasons.config.SCAN_BASELINE_UNBOUND) == "scan_baseline_unbound"
    assert spec.since == "1.30.0"


def test_f15_t6_warn_without_a_digest_is_accepted() -> None:
    cfg = PipelineConfig.model_validate(_block(on_drift="warn"))
    assert "sha256" not in cfg.model_dump()["scan_baseline"]


def test_f15_t6_a_digest_without_on_drift_is_accepted_and_kept() -> None:
    cfg = PipelineConfig.model_validate(_block(sha256=DIGEST))
    assert cfg.model_dump()["scan_baseline"]["sha256"] == DIGEST
    assert "on_drift" not in cfg.model_dump()["scan_baseline"]


def test_f15_t6_an_explicit_null_digest_is_not_dumped() -> None:
    cfg = PipelineConfig.model_validate(_block(on_drift="warn", sha256=None))
    assert "sha256" not in cfg.model_dump()["scan_baseline"]


def test_f15_t6_the_schema_snapshot_holds_the_key() -> None:
    snapshot = json.loads(
        (
            FIXTURES.parent / "snapshots" / "frozen_schemas" / "pipeline-config.schema.json"
        ).read_text()
    )
    assert "sha256" in snapshot["$defs"]["ScanBaselineConfig"]["properties"]
