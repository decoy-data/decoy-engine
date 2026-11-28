"""A cell the authority cannot read, and a distinct count over its budget, are coded per column.

A source `date32` in year 10000 has no Python date, so the authority cannot read it. On every
route the column fails with `postmask_column_not_inspectable`, even a passthrough column nothing
else writes, and no uncoded exception leaves the authority. A distinct count over its memory
budget is `high_cardinality_distinct_limit_exceeded` on that one column, never the
out-of-memory reason a real `MemoryError` gets. All values are synthetic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine._execution_error import ExecutionError
from decoy_engine.execution.pipeline.post_scan import PostScanGate
from decoy_engine.internal.cell_identity import identity_facts
from decoy_engine.internal.cell_text import UnreadableCellError
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.verification.postmask._column_facts import column_facts, standalone_writes
from decoy_engine.verification.postmask._stream_input import from_staged, from_table
from decoy_engine.verification.postmask.residual_pii import residual_pii_findings
from decoy_engine.verification.postmask.runner import run_post_mask_tables

NOT_INSPECTABLE = reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE
DISTINCT_LIMIT = reasons.quality.HIGH_CARDINALITY_DISTINCT_LIMIT_EXCEEDED
LIMIT = "512MB"
# Day 2932897 is 10000-01-01, one day past Python's last date.
FAR = pa.array([2932897, 19000, 19001], pa.int32()).cast(pa.date32())
EMAILS = pa.array(["a@example.com", "b@example.com", "c@example.com"])


def _cfg(strategy: str = "passthrough") -> dict[str, Any]:
    return {
        "version": 2,
        "tables": [{"name": "t", "columns": [{"name": "e", "strategy": strategy}]}],
    }


def _errors(findings: list[Any]) -> list[Any]:
    return [
        f for f in findings if (f["severity"] if isinstance(f, dict) else f.severity) == "error"
    ]


def _message(finding: Any) -> str:
    return str(finding["message"] if isinstance(finding, dict) else finding.message)


def test_the_authority_codes_a_cell_it_cannot_read_on_both_column_kinds() -> None:
    for out in (EMAILS, pd.Series(EMAILS.to_pylist(), dtype=object)):
        with pytest.raises(UnreadableCellError) as caught:
            identity_facts(FAR, out)
        assert "10000" not in str(caught.value)


@pytest.mark.parametrize("strategy", ["passthrough", "hash"])
def test_standalone_route_gives_one_coded_error_row(tmp_path: Path, strategy: str) -> None:
    src, out = from_table("t", pa.table({"e": FAR})), from_table("t", pa.table({"e": EMAILS}))
    fact = column_facts(src, out, ["e"], scratch=tmp_path, memory_limit=LIMIT)["e"]
    assert fact.identity_error == NOT_INSPECTABLE
    config = _cfg(strategy)
    findings = residual_pii_findings(
        {"t": {"e": fact}}, config, writes=standalone_writes(config, {"t": ["e"]})
    )
    (error,) = _errors(findings)
    assert NOT_INSPECTABLE in _message(error) and "10000" not in _message(error)


def _staged(path: Path, column: pa.Array) -> Any:
    pq.write_table(pa.table({"e": column}), path)
    return from_staged("t", lambda: os.open(path, os.O_RDONLY))


def test_staged_route_gives_one_coded_error_row(tmp_path: Path) -> None:
    src, out = _staged(tmp_path / "src.parquet", FAR), _staged(tmp_path / "out.parquet", EMAILS)
    report = run_post_mask_tables(
        {"t": src}, {"t": out}, config=_cfg(), keys=(), scratch=tmp_path, memory_limit=LIMIT
    )
    assert report.get("pass_failed_with") is None
    (error,) = _errors(report["residual_pii"])
    assert error["column"] == "e" and NOT_INSPECTABLE in _message(error)
    assert "10000" not in repr(report)


def test_frame_route_stops_on_the_coded_conversion_error() -> None:
    source, output = pa.table({"e": FAR}), pa.table({"e": EMAILS})
    config = {**_cfg("faker"), "post_scan": {"integrity": True}}
    gate = PostScanGate(config, sources={"t": source})
    with pytest.raises(ExecutionError) as caught:
        gate.run_resident({"t": output}, {"t": source}, {"t": "mask"})
    assert caught.value.code == reasons.runtime.POST_SCAN_COLUMN_NOT_INSPECTABLE
    assert "10000" not in str(caught.value)


def _times(n: int) -> pa.Array:
    return pa.array(np.datetime64("2020-01-01", "s") + np.arange(n).astype("m8[s]"))


def test_a_budget_overrun_is_one_coded_column_and_the_others_keep_their_counts(
    tmp_path: Path,
) -> None:
    # 1 MB holds 4096 forms at the counter's 256-byte estimate; `wide` has more, `narrow` three.
    table = from_table(
        "t",
        pa.table(
            {"wide": _times(10_000), "narrow": _times(3).take([i % 3 for i in range(10_000)])}
        ),
    )
    facts = column_facts(table, table, ["wide", "narrow"], scratch=tmp_path, memory_limit="1MB")
    assert facts["wide"].distinct_error == DISTINCT_LIMIT
    assert facts["narrow"].distinct_error is None and facts["narrow"].output_distinct == 3
    config = {
        "version": 2,
        "tables": [
            {"name": "t", "columns": [{"name": c, "strategy": "hash"} for c in ("wide", "narrow")]}
        ],
    }
    writes = standalone_writes(config, {"t": ["wide", "narrow"]})
    (error,) = _errors(residual_pii_findings({"t": facts}, config, writes=writes))
    assert error.column == "wide" and DISTINCT_LIMIT in _message(error)


def test_a_budget_overrun_and_a_real_memory_error_give_different_reasons(tmp_path: Path) -> None:
    table = from_table("t", pa.table({"wide": _times(10_000)}))
    fact = column_facts(table, table, ["wide"], scratch=tmp_path, memory_limit="1MB")["wide"]
    real = reason_from_exception(MemoryError())
    assert real.code == reasons.decoy.PROCESS_OUT_OF_MEMORY
    assert fact.distinct_error == DISTINCT_LIMIT != real.code
