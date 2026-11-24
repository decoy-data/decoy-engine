"""VALIDATE-SUBSET-EDGES E1: a run refuses a bad subset edge before any read; an override is free."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import run_pipeline
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.execution.pipeline._subset_stage import resolve_subset
from decoy_engine.subset import (
    SubsetConfigError,
    SubsetRequest,
    split_subset_config,
    subset_request_from_config,
)
from tests.unit.execution import _subset_run_support as sup

EDGE = "customers.cid -> orders.cid"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sup.VAR, "ab" * 32)


def _dangling(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg, data, _ = sup.job(tmp_path)
    cfg["subset"]["edge_directions"] = {EDGE: "downward"}
    return cfg, data


def _valid_request(tmp_path: Path) -> SubsetRequest:
    """A clean request from a separate job dir, so no test config carries it."""
    side = tmp_path / "request"
    side.mkdir()
    request = subset_request_from_config(sup.job(side)[0])
    assert request is not None
    return request


def _hash(config: dict[str, Any]) -> str:
    import decoy_engine.plan as plan_pkg
    from decoy_engine.profile import profile_source

    plan = plan_pkg.compile_plan(
        config, profile_source(config), decoy_engine_version="t", sources=NO_SOURCES
    )
    return str(plan.pipeline_config_hash)


def test_at_e3_dangling_refused_before_a_missing_source_is_read(tmp_path: Path) -> None:
    cfg, _ = _dangling(tmp_path)
    for desc in cfg["sources"].values():
        Path(desc["path"]).unlink()
    with pytest.raises(SubsetConfigError) as info:
        run_pipeline(cfg, None, engine_version="t")
    assert info.value.code == "subset_dangling_not_acknowledged"


def test_at_e6_override_runs_when_the_discarded_block_is_dangling(tmp_path: Path) -> None:
    """Pin: green before E1. Red if the override is routed through the split."""
    cfg, data = _dangling(tmp_path)
    request = _valid_request(tmp_path)
    result = run_pipeline(cfg, data, engine_version="t", subset_request=request)
    assert result.outputs["customers"].num_rows == 5


def test_at_e6b_override_keeps_a_blockless_config_unchanged(tmp_path: Path) -> None:
    """Pin: green before E1."""
    cfg = sup.job(tmp_path)[0]
    cfg["subset"] = None
    request = _valid_request(tmp_path)
    run_config, scope = resolve_subset(cfg, request, None)
    assert run_config == cfg and "subset" in cfg
    plain = tmp_path / "plain"
    plain.mkdir()
    cfg2 = sup.job(plain)[0]
    del cfg2["subset"]
    run_config2, scope2 = resolve_subset(cfg2, request, None)
    assert run_config2 == cfg2 and "subset" not in run_config2
    assert _hash(run_config2) == _hash(cfg2)
    assert scope2.declared is False and scope.declared is False


def test_at_e6b_override_hash_equals_the_config_path_with_a_block(tmp_path: Path) -> None:
    """Pin: green before E1."""
    cfg = sup.job(tmp_path)[0]
    request = _valid_request(tmp_path)
    overridden, scope = resolve_subset(copy.deepcopy(cfg), request, None)
    via_config = split_subset_config(cfg).run_config
    assert overridden == via_config
    assert _hash(overridden) == _hash(via_config)
    assert scope.declared is True


def test_at_e7_skip_still_refuses_a_dangling_block(tmp_path: Path) -> None:
    """Red before E1 (Q1 option A, the open default)."""
    cfg, data = _dangling(tmp_path)
    with pytest.raises(SubsetConfigError) as info:
        run_pipeline(cfg, data, engine_version="t", subset_request="skip")
    assert info.value.code == "subset_dangling_not_acknowledged"
