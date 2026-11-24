"""R2 (SOURCE-READ-BOUNDARY S1b-1): each routed read fails coded and value-free, never uncoded.

The source holds a `date32` in year 10000, which pandas cannot hold. Widening is off in S1b-1,
so every read ends in a coded error that names the column and carries no date.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._fk_keys import to_pandas_fk_safe
from decoy_engine.execution._pipeline_finalize import compute_fidelity_reports
from decoy_engine.execution.pipeline._post_scan import PostScanGate
from decoy_engine.profile._readers import ParquetFileSource
from decoy_engine.profile._readers_resident import ResidentTableSource
from decoy_engine.verification.postmask import run_post_mask_tables
from decoy_engine.verification.postmask._column_facts import column_facts
from decoy_engine.verification.postmask._stream_input import from_table

_TABLE = pa.table(
    {"id": [1, 2, 3], "d": pa.array([2932897, 19000, 19001], pa.int32()).cast(pa.date32())}
)
_CONFIG: dict[str, Any] = {
    "version": 2,
    "post_scan": {"integrity": True},
    "tables": [{"name": "t", "columns": [{"name": "d", "strategy": "faker"}]}],
}


def _value_free(exc: BaseException) -> None:
    text = f"{exc!s}{exc!r}"
    assert "10000" not in text and "2932897" not in text
    assert exc.__cause__ is None and exc.__context__ is None


def _coded(call: Any, code: str) -> ExecutionError:
    with pytest.raises(ExecutionError) as caught:
        call()
    assert caught.value.code == code
    assert "'d'" in str(caught.value)
    _value_free(caught.value)
    return caught.value


def test_profile_readers_reach_the_profile_callback(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    pq.write_table(_TABLE, path)
    code = reasons.runtime.SOURCE_COLUMN_UNREPRESENTABLE
    _coded(lambda: ResidentTableSource(_TABLE).to_frame(), code)
    _coded(lambda: ResidentTableSource(_TABLE).sample_frame(2), code)
    _coded(lambda: ParquetFileSource(path).to_frame(), code)
    _coded(lambda: ParquetFileSource(path).sample_frame(2), code)


def test_execution_conversion_names_the_table_and_column() -> None:
    err = _coded(
        lambda: to_pandas_fk_safe(_TABLE, set(), table_name="t"),
        reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE,
    )
    assert "table 't'" in str(err)


def test_fidelity_report_fails_coded() -> None:
    _coded(
        lambda: compute_fidelity_reports(
            {"t": _TABLE}, {"t": _TABLE}, table_kinds={"t": "mask"}, now_iso=None
        ),
        reasons.runtime.SOURCE_COLUMN_UNREPRESENTABLE,
    )


def test_post_scan_gate_fails_closed_on_a_scalar_date() -> None:
    """The gate never passes a column it did not read."""
    gate = PostScanGate(_CONFIG, sources={"t": _TABLE})
    _coded(
        lambda: gate.run_resident({"t": _TABLE}, {"t": _TABLE}, {"t": "mask"}),
        reasons.runtime.POST_SCAN_COLUMN_NOT_INSPECTABLE,
    )


def test_post_mask_facts_mark_the_column_not_inspectable(tmp_path: Path) -> None:
    code = reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE
    src, out = from_table("t", _TABLE), from_table("t", _TABLE)
    facts = column_facts(src, out, ["id", "d"], scratch=tmp_path, memory_limit="512MB")
    assert (facts["d"].identity_error, facts["d"].distinct_error) == (code, code)
    assert facts["id"].error is None  # the other columns are still checked
    report = run_post_mask_tables(
        {"t": src}, {"t": out}, config=_CONFIG, keys=(), scratch=tmp_path, memory_limit="512MB"
    )
    assert report["error_count"] >= 1
    assert "10000" not in str(report) and "2932897" not in str(report)


def test_unconfigured_not_inspectable_output_column_is_one_error_finding(tmp_path: Path) -> None:
    """No configured strategy, no detectors: the column still must not read as clean."""
    config: dict[str, Any] = {"version": 2, "tables": [{"name": "t", "columns": []}]}
    src = from_table("t", pa.table({"id": [1, 2, 3]}))
    out = from_table("t", _TABLE)
    report = run_post_mask_tables(
        {"t": src}, {"t": out}, config=config, keys=(), scratch=tmp_path, memory_limit="512MB"
    )
    errors = [f for f in report["residual_pii"] if f["severity"] == "error" and f["column"] == "d"]
    assert len(errors) == 1
    assert "postmask_column_not_inspectable" in errors[0]["message"]
    assert "10000" not in str(report)


def test_a_source_only_failure_still_runs_the_output_detectors(tmp_path: Path) -> None:
    emails = pa.array(["a@example.com", "b@example.com", "c@example.com"])
    out = from_table("t", pa.table({"e": emails}))
    src = from_table("t", pa.table({"e": _TABLE.column("d")}))
    fact = column_facts(src, out, ["e"], scratch=tmp_path, memory_limit="512MB")["e"]
    assert fact.identity_error == reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE
    assert fact.detectors  # the output column was still read and checked
