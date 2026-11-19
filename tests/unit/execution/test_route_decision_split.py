"""AT-S1: the multi-table split is decided once, in `decide_route`, and stored on `RouteDecision`.

The executor used to call `decide_multi_table_split` itself, after the route was published. The
resident-fit stage (NONFK-OOM) needs the split before execution to know which tables stay
resident, so the decision moved up and the executor reads it. Outputs must not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import run_pipeline
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _multi_table_support as mt

pytestmark = pytest.mark.filterwarnings("ignore")


def _three_tables(tmp_path: Path) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    columns = mt.std_columns("ns_split")
    return mt.build_job(
        tmp_path,
        {
            "a": (columns, mt.string_table(mt.BIG, "a")),
            "b": (columns, mt.string_table(mt.BIG, "b")),
            "c": ([support.redact_col("r")], pa.table({"r": pa.array(["x", "y", "z"])})),
        },
    )


def _spy_decisions(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The `RouteDecision` each full-frame run executes."""
    from decoy_engine.execution import _pipeline_full_frame as full_frame

    seen: list[Any] = []
    real = full_frame.run_full_frame_route

    def spy(ctx: Any, decision: Any, **kwargs: Any) -> Any:
        seen.append(decision)
        return real(ctx, decision, **kwargs)

    monkeypatch.setattr(full_frame, "run_full_frame_route", spy)
    return seen


def test_decision_split_is_what_the_executor_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, sources = _three_tables(tmp_path)
    decisions = _spy_decisions(monkeypatch)
    ran = mt.spy_split(monkeypatch)
    result = run_pipeline(cfg, sources=sources, **mt.kw())
    (decision,) = decisions
    (call,) = ran
    assert decision.split is not None
    assert decision.split is call[0][0]
    assert decision.split.dispatched == ("a", "b")
    assert decision.split.full_frame == ("c",)
    assert mt.dispatched_tables(result) == ["a", "b"]


def test_outputs_match_the_job_that_never_splits(tmp_path: Path) -> None:
    cfg, sources = _three_tables(tmp_path)
    split = run_pipeline(cfg, sources=sources, **mt.kw())
    whole = run_pipeline(cfg, sources=sources, **mt.kw(**mt.off_kw()))
    assert split.outputs.keys() == whole.outputs.keys()
    for name in whole.outputs:
        assert split.outputs[name].equals(whole.outputs[name]), name


def test_a_job_that_stays_whole_stores_no_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, sources = _three_tables(tmp_path)
    decisions = _spy_decisions(monkeypatch)
    run_pipeline(cfg, sources=sources, **mt.kw(**mt.off_kw()))
    (decision,) = decisions
    assert decision.split is None


def test_a_declared_job_keeps_one_route_and_stores_no_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F06: a declared job keeps one route for the whole job, as it did when the executor decided."""
    from tests.acceptance import test_f06_fallback_reasons as f06
    from tests.acceptance import test_f06_route_parity as parity
    from tests.acceptance._f06_support import run

    cfg, sources = f06._two_tables(tmp_path)
    decisions = _spy_decisions(monkeypatch)
    run(
        cfg,
        sources,
        auto_chunk=True,
        chunk_size_rows=2,
        auto_chunk_threshold_rows=1,
        quarantine_runtime=parity._runtime(tmp_path / "q-multi"),
    )
    (decision,) = decisions
    assert decision.split is None


def test_a_single_chunked_table_stores_no_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, sources = mt.build_job(tmp_path, {"a": (mt.std_columns("ns_one"), mt.string_table())})
    decisions = _spy_decisions(monkeypatch)
    run_pipeline(cfg, sources=sources, **mt.kw())
    (decision,) = decisions
    assert decision.route_chunked
    assert decision.split is None
