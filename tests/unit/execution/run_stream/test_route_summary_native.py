"""RUN-STREAM E5 (AT-E5, route summary half): `RouteSummary.native_executed`.

True only when a column ran its planned backend and that backend is a compiled one the operator
registry owns. A planned `arrow_python` column that ran `arrow_python` is equality without a
kernel, and an admitted column whose kernel stayed idle reports `arrow_python`: neither counts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.execution._operator_registry import ARROW_PYTHON, PANDAS_ORACLE, RUST_COMPANION
from decoy_engine.execution.pipeline import route_summary
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution.run_stream import _support as rs


def _col(planned: str, executed: str) -> dict[str, Any]:
    return {
        "column": "c",
        "strategy": "s",
        "planned_backend": planned,
        "executed_backend": executed,
        "calls": 1,
    }


def _lane(admitted: bool, *cols: dict[str, Any]) -> dict[str, Any]:
    return {
        "auto_chunk": {"lane": "dispatcher", "lane_reason": None, "native_threads": 1},
        "chunked_route": {
            "native_admitted": admitted,
            "reroute_reason": None,
            "columns": list(cols),
        },
    }


def _executed(metrics: Any) -> bool | None:
    return route_summary(metrics).native_executed


def test_a_compiled_column_that_ran_its_kernel_is_executed() -> None:
    assert _executed(_lane(True, _col(RUST_COMPANION, RUST_COMPANION))) is True


def test_an_idle_compiled_kernel_is_not_executed() -> None:
    # M-E5b: the preflight says admitted, but the kernel made no call.
    metrics = _lane(True, _col(RUST_COMPANION, ARROW_PYTHON))
    assert route_summary(metrics).native == "admitted"
    assert _executed(metrics) is False


def test_planned_python_equality_is_not_a_compiled_run() -> None:
    # M-E5d: planned and executed agree, but arrow_python is not a registry compiled backend.
    assert _executed(_lane(True, _col(ARROW_PYTHON, ARROW_PYTHON))) is False
    assert _executed(_lane(True, _col("unregistered_backend", "unregistered_backend"))) is False


def test_a_declined_route_is_not_executed() -> None:
    assert _executed(_lane(False, _col(RUST_COMPANION, PANDAS_ORACLE))) is False


def test_one_compiled_column_among_python_columns_is_enough() -> None:
    cols = (_col(ARROW_PYTHON, ARROW_PYTHON), _col(RUST_COMPANION, RUST_COMPANION))
    assert _executed(_lane(True, *cols)) is True


def test_any_compiled_table_of_a_split_counts() -> None:
    metrics = {
        "auto_chunk": {
            "lane": "dispatcher",
            "tables": [
                {"table": "a", "dispatched": True},
                {"table": "b", "dispatched": True},
            ],
        },
        "chunked_route_by_table": {
            "a": {"native_admitted": True, "columns": [_col(RUST_COMPANION, ARROW_PYTHON)]},
            "b": {"native_admitted": True, "columns": [_col(RUST_COMPANION, RUST_COMPANION)]},
        },
    }
    assert _executed(metrics) is True


@pytest.mark.parametrize(
    "metrics",
    [None, {}, {"unrelated": 1}, {"execution": {"execution_mode": "full_frame"}}],
)
def test_off_the_lane_there_is_no_answer(metrics: Any) -> None:
    assert _executed(metrics) is None


@support.NEEDS_COMPANION
def test_a_real_lane_run_reports_the_kernel_it_ran(tmp_path: Path) -> None:
    table = rs.two_column_table(200)
    hashed = [support.hash_col("r"), support.pass_col("p")]
    cfg, source = rs.single_table_job(tmp_path, table, hashed)
    sink, _ = rs.real_sink(tmp_path)
    # Stream mode drops the 100,000-row threshold, so 200 rows really take the lane. Default
    # routing runs a table this small full-frame, which has no per-column backend evidence.
    result: Any = rs.run_stream(cfg, {"t": source}, sink)
    got = route_summary(result.quality_metrics)
    assert got.route == "auto_chunk"
    assert got.native_executed is True

    cfg2, source2 = rs.single_table_job(tmp_path, table)
    sink2, _ = rs.real_sink(tmp_path, "out2")
    python_only: Any = rs.run_stream(cfg2, {"t": source2}, sink2)
    assert route_summary(python_only.quality_metrics).route == "auto_chunk"
    assert route_summary(python_only.quality_metrics).native_executed is False
