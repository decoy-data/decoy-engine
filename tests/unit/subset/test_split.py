"""AT-21: the split leaves a run config that dumps and hashes like one that never had a subset."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.subset import SubsetConfigError, drop_subset_block, split_subset_config
from tests.unit.execution import _subset_run_support as sup


def _cfg(tmp_path: Path) -> dict[str, Any]:
    return sup.job(tmp_path)[0]


def test_run_config_equals_a_config_with_no_subset(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    plain = copy.deepcopy(cfg)
    plain["subset"] = None
    split = split_subset_config(cfg)
    assert split.run_config == plain
    assert "subset" in split.run_config and split.run_config["subset"] is None
    assert cfg["subset"] is not None, "the caller's dict is not edited"


def test_config_hash_equals_that_of_the_same_config_without_a_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import decoy_engine.plan as plan_pkg
    from decoy_engine.profile import profile_source

    cfg = _cfg(tmp_path)
    plain = copy.deepcopy(cfg)
    plain["subset"] = None
    hashes = []
    for c in (split_subset_config(cfg).run_config, plain):
        plan = plan_pkg.compile_plan(
            c, profile_source(c), decoy_engine_version="t", sources=NO_SOURCES
        )
        hashes.append(plan.pipeline_config_hash)
    assert hashes[0] == hashes[1]


def test_no_block_means_no_request_and_the_same_object(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg["subset"] = None
    split = split_subset_config(cfg)
    assert split.request is None and split.fingerprint is None and split.run_config is cfg


def test_fingerprint_follows_the_request(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    other = copy.deepcopy(cfg)
    other["subset"]["seeds"][0]["count"] = 6
    a, b = split_subset_config(cfg), split_subset_config(other)
    assert a.fingerprint == split_subset_config(cfg).fingerprint
    assert a.fingerprint != b.fingerprint


def test_validate_plan_returns_findings_for_a_subset_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.plan.validate import validate_plan
    from decoy_engine.profile import profile_source

    cfg = _cfg(tmp_path)
    ok = validate_plan(cfg, profile_source(cfg), decoy_engine_version="t")
    assert ok.ok, ok.error

    def refuse(config: Any) -> Any:
        raise SubsetConfigError(code="subset_seed_unsupported", message="bad seed")

    monkeypatch.setattr("decoy_engine.subset.split_subset_config", refuse)
    bad = validate_plan(cfg, profile_source(cfg), decoy_engine_version="t")
    assert not bad.ok and bad.error is not None
    assert bad.error.code == "subset_seed_unsupported"


# VALIDATE-SUBSET-EDGES E1: the split refuses a bad edge direction before any read.
EDGE = "customers.cid -> orders.cid"


def _edge_cfg(tmp_path: Path, **block: Any) -> dict[str, Any]:
    cfg = sup.job(tmp_path)[0]
    cfg["subset"].update(block)
    return cfg


def test_at_e1_downward_needs_allow_dangling(tmp_path: Path) -> None:
    cfg = _edge_cfg(tmp_path, edge_directions={EDGE: "downward"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_dangling_not_acknowledged"
    ok = _edge_cfg(tmp_path, edge_directions={EDGE: "downward"}, allow_dangling=True)
    assert split_subset_config(ok).request is not None


def test_at_e1_none_direction_is_refused_too(tmp_path: Path) -> None:
    cfg = _edge_cfg(tmp_path, edge_directions={EDGE: "none"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_dangling_not_acknowledged"


def test_at_e1_both_and_upward_pass(tmp_path: Path) -> None:
    for direction in ("both", "upward"):
        cfg = _edge_cfg(tmp_path, edge_directions={EDGE: direction})
        assert split_subset_config(cfg).request is not None


def test_at_e2_unknown_edge_is_refused(tmp_path: Path) -> None:
    cfg = _edge_cfg(tmp_path, edge_directions={"customers.cid -> nowhere.cid": "both"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_unknown_edge"


def test_at_e4_plan_validation_reports_the_dangling_code(tmp_path: Path) -> None:
    from decoy_engine.plan.validate import validate_plan
    from decoy_engine.profile import profile_source

    cfg = _edge_cfg(tmp_path)
    assert validate_plan(cfg, profile_source(cfg), decoy_engine_version="t").ok
    bad = _edge_cfg(tmp_path, edge_directions={EDGE: "downward"})
    result = validate_plan(bad, profile_source(bad), decoy_engine_version="t")
    assert not result.ok and result.error is not None
    assert result.error.code == "subset_dangling_not_acknowledged"
    assert result.error.path == "subset"


def test_at_e5_message_names_the_config_spellings_first(tmp_path: Path) -> None:
    cfg = _edge_cfg(tmp_path, edge_directions={EDGE: "downward"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    text = str(info.value)
    assert "allow dangling" in text and "allow_dangling: true" in text
    assert text.index("allow dangling") < text.index("FanOutPolicy")
    assert EDGE in text


def test_message_holds_no_seeded_value(tmp_path: Path) -> None:
    seed = {"table": "customers", "mode": "keys", "key_columns": ["cid"], "keys": [[sup.CANARY]]}
    cfg = sup.job(tmp_path, seed=seed)[0]
    cfg["subset"]["edge_directions"] = {EDGE: "downward"}
    assert sup.CANARY in repr(cfg["subset"]), "the canary is in the config"
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert sup.CANARY not in str(info.value) and str(tmp_path) not in str(info.value)


def test_drop_subset_block_returns_a_blockless_config_itself(tmp_path: Path) -> None:
    plain = _cfg(tmp_path)
    plain["subset"] = None
    assert drop_subset_block(plain) is plain
    del plain["subset"]
    assert drop_subset_block(plain) is plain and "subset" not in plain


def test_drop_subset_block_leaves_the_caller_dict_alone(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    before = copy.deepcopy(cfg)
    dropped = drop_subset_block(cfg)
    assert dropped is not cfg and dropped["subset"] is None
    assert cfg == before


def test_split_does_not_edit_the_callers_dict(tmp_path: Path) -> None:
    cfg = _edge_cfg(tmp_path, edge_directions={EDGE: "downward"}, allow_dangling=True)
    before = copy.deepcopy(cfg)
    split_subset_config(cfg)
    assert cfg == before
