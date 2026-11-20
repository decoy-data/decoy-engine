"""ENGINE-THREADS-DEFAULT: a memory-capped isolated run keeps one thread when none is requested.

The Rust shared pool is sized to the host's cores and its thread stacks count against RLIMIT_DATA.
Kept apart from `test_native_threads_default.py`, which spawns an uncapped child.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.serial

ENGINE = "s3-threads-capped"


def test_a_memory_capped_isolated_run_keeps_one_thread(tmp_path: Path) -> None:
    """The Rust pool is sized to the host and its stacks count against RLIMIT_DATA, so a capped
    run with no thread request resolves to one thread (recorded as explicit)."""
    from decoy_engine.execution import run_pipeline_isolated
    from tests.unit.execution.test_isolated_run import _mask_config, _mask_sources

    cfg = _mask_config(tmp_path, n_cols=2)
    sources = _mask_sources(tmp_path, n_rows=50, n_cols=2)
    result = run_pipeline_isolated(
        cfg, sources, engine_version=ENGINE, mem_cap_bytes=8 * 1024**3, rlimit_kind="data"
    )
    assert result.outcome == "completed", result.error
    assert (
        result.quality_metrics["execution"]["native_threads"]["count"],
        result.quality_metrics["execution"]["native_threads"]["source"],
    ) == (1, "explicit")
    omitted = run_pipeline_isolated(cfg, sources, engine_version=ENGINE)
    assert omitted.quality_metrics["execution"]["native_threads"]["source"] == "auto"
