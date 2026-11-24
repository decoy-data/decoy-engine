"""VALIDATE-SUBSET-EDGES E1: the one split refuses a bad edge direction before any source is read."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.subset import SubsetConfigError, split_subset_config
from tests.unit.execution import _subset_run_support as sup

EDGE = "customers.cid -> orders.cid"


def _cfg(tmp_path: Path, **block: Any) -> dict[str, Any]:
    cfg = sup.job(tmp_path)[0]
    cfg["subset"].update(block)
    return cfg


def test_at_e1_downward_needs_allow_dangling(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={EDGE: "downward"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_dangling_not_acknowledged"
    ok = _cfg(tmp_path, edge_directions={EDGE: "downward"}, allow_dangling=True)
    assert split_subset_config(ok).request is not None


def test_at_e1_none_direction_is_refused_too(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={EDGE: "none"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_dangling_not_acknowledged"


def test_at_e1_both_and_upward_pass(tmp_path: Path) -> None:
    for direction in ("both", "upward"):
        cfg = _cfg(tmp_path, edge_directions={EDGE: direction})
        assert split_subset_config(cfg).request is not None


def test_at_e2_unknown_edge_is_refused(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={"customers.cid -> nowhere.cid": "both"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert info.value.code == "subset_unknown_edge"


def test_at_e4_plan_validation_reports_the_dangling_code(tmp_path: Path) -> None:
    from decoy_engine.plan.validate import validate_plan
    from decoy_engine.profile import profile_source

    cfg = _cfg(tmp_path)
    assert validate_plan(cfg, profile_source(cfg), decoy_engine_version="t").ok
    bad = _cfg(tmp_path, edge_directions={EDGE: "downward"})
    result = validate_plan(bad, profile_source(bad), decoy_engine_version="t")
    assert not result.ok and result.error is not None
    assert result.error.code == "subset_dangling_not_acknowledged"
    assert result.error.path == "subset"


def test_at_e5_message_names_the_config_spellings_first(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={EDGE: "downward"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    text = str(info.value)
    assert "allow dangling" in text and "allow_dangling: true" in text
    assert text.index("allow dangling") < text.index("FanOutPolicy")
    assert EDGE in text


def test_message_holds_no_row_value(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={EDGE: "downward"})
    with pytest.raises(SubsetConfigError) as info:
        split_subset_config(cfg)
    assert sup.CANARY not in str(info.value) and str(tmp_path) not in str(info.value)


def test_split_does_not_edit_the_callers_dict(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, edge_directions={EDGE: "downward"}, allow_dangling=True)
    before = copy.deepcopy(cfg)
    split_subset_config(cfg)
    assert cfg == before
