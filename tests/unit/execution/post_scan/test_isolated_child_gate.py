"""The post-scan gate in a real isolated child (`isolate=True`): it reads the child's staging
sink back, so `post_scan.integrity` neither refuses nor defers there. All values are made up."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.config._post_scan import post_scan_output_readable, post_scan_sink_kind
from decoy_engine.execution import run_pipeline_isolated
from tests.unit.execution import _subset_run_support as subset_sup
from tests.unit.execution.post_scan.test_wiring import (
    DUPLICATES,
    _blocked,
    _config,
    _run,
)
from tests.unit.execution.test_lazy_path_route_admission import _parent_child_tables

V = "ps12-isolated-child"


@pytest.fixture(autouse=True)
def _subset_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subset_sup.VAR, "ab" * 32)


def _isolated(tmp: Path, mode: str, *, broken: bool = False) -> Any:
    parent, child = _parent_child_tables()
    config = _config(tmp, broken=broken, integrity=True)
    config["global_settings"]["mask_secret_ref"] = f"env:{subset_sup.VAR}"
    return run_pipeline_isolated(
        config,
        {"parent": parent, "child": child},
        isolate=True,
        output_dir=tmp / "committed",
        engine_version=V,
        execution_mode=mode,
    )


@pytest.mark.parametrize("mode", ["full_frame", "sequential"])
def test_integrity_in_an_isolated_child_passes_the_gate(tmp_path: Path, mode: str) -> None:
    result = _isolated(tmp_path, mode)
    assert result.isolated is True
    assert result.outcome == "completed", (result.error, result.reason)
    metrics = result.quality_metrics
    assert "post_scan_gate_deferred" not in metrics
    assert metrics["post_scan_integrity"]["verdict"]["blocking"] is False
    assert (tmp_path / "committed").is_dir()


@pytest.mark.parametrize("mode", ["sequential", "out_of_core"])
def test_a_blocking_finding_on_a_streamed_child_blocks_like_the_in_process_route(
    tmp_path: Path, mode: str
) -> None:
    in_process = tmp_path / "in_process"
    in_process.mkdir()
    expected = _blocked(lambda: _run(_config(in_process, broken=True, integrity=True), mode))
    result = _isolated(tmp_path, mode, broken=True)
    assert result.isolated is True
    assert result.outcome == "blocked", (result.error, result.reason)
    assert result.reason is not None
    assert f"{result.reason.namespace}.{result.reason.code}" == expected.reason == DUPLICATES
    assert result.outputs is None
    assert not (tmp_path / "committed").exists()
    assert result.quality_metrics["post_scan_integrity"]["verdict"]["blocking"] is True


def test_the_staging_sink_is_a_readable_kind() -> None:
    from decoy_engine.execution._isolated_common import StagingSink

    kind = post_scan_sink_kind(StagingSink.__new__(StagingSink))
    assert post_scan_output_readable(kind)
