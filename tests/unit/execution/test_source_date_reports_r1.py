"""The optional reports convert a date dictionary through the shared working conversion
(DATE-RANGE-SENTINEL S5 remediation, V1-5).

The checked read keeps a null dictionary entry, which `to_pandas` refuses, so the fidelity report
and the post-scan column suite must not call it directly. Both are reached through the public
run options."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution import run_pipeline
from tests.unit.execution import _auto_chunk_support as support

DAY = dt.date(2020, 1, 1)


def _source() -> pa.Table:
    entries = pa.array([DAY, None, dt.date(2020, 1, 2)], pa.date32())
    events = pa.DictionaryArray.from_arrays(pa.array([0, 2, 0, None, 2], pa.int8()), entries)
    return pa.table({"id": pa.array(range(5)), "events": events})


def _cfg(tmp_path: Path, *, post_scan: bool) -> dict[str, Any]:
    """A real clean source file the parent profiles, so the run reaches the checked read."""
    declared = tmp_path / "declared.parquet"
    pq.write_table(pa.table({"id": [0, 1], "events": ["a", "b"]}), str(declared))
    cfg = support.make_cfg([support.hash_col("id"), support.pass_col("events")], path=str(declared))
    if post_scan:
        cfg["post_scan"] = {"integrity": True}
    return cfg


def test_the_fidelity_report_runs_over_a_date_dictionary_with_a_null_entry(tmp_path: Path) -> None:
    result = run_pipeline(
        _cfg(tmp_path, post_scan=False),
        sources={support.TABLE: _source()},
        **support.run_kwargs(fidelity_report=True, execution_mode="full_frame", auto_chunk=False),
    )
    assert result.outputs[support.TABLE].num_rows == 5


@pytest.mark.parametrize("route", [{"execution_mode": "full_frame", "auto_chunk": False}, {}])
def test_the_post_scan_column_suite_runs_over_a_date_dictionary_with_a_null_entry(
    route: dict[str, Any], tmp_path: Path
) -> None:
    result = run_pipeline(
        _cfg(tmp_path, post_scan=True),
        sources={support.TABLE: _source()},
        **support.run_kwargs(**route),
    )
    assert result.outputs[support.TABLE].num_rows == 5
    assert "post_scan_integrity" in result.quality_metrics


def test_the_deferred_post_scan_check_runs_over_a_date_dictionary_with_a_null_entry(
    tmp_path: Path,
) -> None:
    """A loader run defers the gate; its report-only check is the second conversion site."""
    table = _source()
    result = run_pipeline(
        _cfg(tmp_path, post_scan=True),
        sources=None,
        **support.run_kwargs(
            source_loader=lambda name: table, source_loader_schemas={support.TABLE: table.schema}
        ),
    )
    assert result.outputs[support.TABLE].num_rows == 5
    assert "post_scan_integrity" in result.quality_metrics
