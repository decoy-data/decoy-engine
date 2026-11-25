"""PREFLIGHT-ARROW-PROFILE S1b, AT-1, AT-5 and the capacity half of AT-6.

A valid Parquet source with a value pandas cannot hold (a `time64[ns]` with a sub-microsecond
part, a date outside years 1 to 9999) used to fail the bounded profile, so
`estimate_job_capacity` raised `capacity_source_unprofilable` for a file the run publishes
exactly. A corrupt or wrong-format source must still raise it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.capacity import estimate_job_capacity
from decoy_engine.execution.out_of_core._capacity_eval import CapacityVerdict
from tests.unit.execution.test_capacity_estimate_job import (  # noqa: F401  (low_threshold is a fixture, used by name)
    _ooc_config,
    _parent_child_tables,
    low_threshold,
)

T_NS_BAD = 3_600_000_000_000 + 987_654_321
EMAILS = ["a@x.test", "b@x.test", "c@x.test", "d@x.test"]


def _single_config(tmp_path: Path, table: pa.Table, name: str = "t.parquet") -> dict[str, Any]:
    path = tmp_path / name
    pq.write_table(table, path)
    return {
        "version": 2,
        "global_settings": {"job_name": "arrow-profile", "seed": 7},
        "sources": {"t": {"type": "file", "path": str(path), "format": "parquet"}},
        "targets": {
            "t": {"type": "file", "path": str(tmp_path / "o.parquet"), "format": "parquet"}
        },
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "t", "strategy": "passthrough"},
                    {"name": "email", "strategy": "redact"},
                ],
            }
        ],
    }


BAD_TABLES = {
    "time64_ns": pa.table(
        {"t": pa.array([0, 1000, 2000, T_NS_BAD], pa.time64("ns")), "email": EMAILS}
    ),
    "date_year_minus_768": pa.table(
        {"t": pa.array([0, 1, 2, -1_000_000], pa.date32()), "email": EMAILS}
    ),
    "date_year_10183": pa.table(
        {"t": pa.array([0, 1, 2, 3_000_000], pa.date32()), "email": EMAILS}
    ),
}


@pytest.mark.parametrize("fixture", sorted(BAD_TABLES))
def test_at1_a_valid_source_with_an_unholdable_value_is_priced(
    fixture: str, tmp_path: Path
) -> None:
    estimate = estimate_job_capacity(_single_config(tmp_path, BAD_TABLES[fixture]), tmp_path)
    assert estimate.verdict is CapacityVerdict.NOT_APPLICABLE


@pytest.mark.usefixtures("low_threshold")
def test_at1_fk_pair_prices_the_same_as_with_the_bad_value_replaced(tmp_path: Path) -> None:
    parent, child = _parent_child_tables()

    def with_time(table: pa.Table, bad: bool) -> pa.Table:
        values = [i * 1000 for i in range(table.num_rows)]
        if bad:
            values[3] = T_NS_BAD
        return table.append_column("t", pa.array(values, pa.time64("ns")))

    results = []
    for label, bad in (("bad", True), ("good", False)):
        base = tmp_path / label
        base.mkdir()
        config = _ooc_config(base, tables=(with_time(parent, bad), child))
        config["tables"][0]["columns"].append({"name": "t", "strategy": "passthrough"})
        results.append(estimate_job_capacity(config, base))
    bad_estimate, good_estimate = results
    assert bad_estimate.verdict is good_estimate.verdict
    assert bad_estimate.needed_bytes == good_estimate.needed_bytes
    assert bad_estimate.verdict is not CapacityVerdict.NOT_APPLICABLE


@pytest.mark.parametrize("bad_row", [0, 9_999, 10_000, 80_000])
def test_at6_estimate_returns_a_verdict_wherever_the_bad_value_sits(
    bad_row: int, tmp_path: Path
) -> None:
    n = 80_001
    values = [(i % 6000) * 1000 for i in range(n)]
    values[bad_row] = T_NS_BAD
    table = pa.table({"t": pa.array(values, pa.time64("ns")), "email": ["e"] * n})
    estimate = estimate_job_capacity(_single_config(tmp_path, table), tmp_path)
    assert estimate.verdict is CapacityVerdict.NOT_APPLICABLE


# ------------------------------------------------------------------ AT-5


def test_at5_a_truncated_parquet_file_is_still_unprofilable(tmp_path: Path) -> None:
    config = _single_config(tmp_path, BAD_TABLES["time64_ns"])
    path = Path(config["sources"]["t"]["path"])
    path.write_bytes(path.read_bytes()[:-9])
    with pytest.raises(ExecutionError) as caught:
        estimate_job_capacity(config, tmp_path)
    assert caught.value.code == "capacity_source_unprofilable"


def test_at5_a_csv_declared_parquet_is_still_unprofilable(tmp_path: Path) -> None:
    config = _single_config(tmp_path, BAD_TABLES["time64_ns"])
    Path(config["sources"]["t"]["path"]).write_text("t,email\n1,a\n")
    with pytest.raises(ExecutionError) as caught:
        estimate_job_capacity(config, tmp_path)
    assert caught.value.code == "capacity_source_unprofilable"


def test_at5_duplicate_columns_keep_the_code_and_chain_the_shared_text(tmp_path: Path) -> None:
    table = pa.Table.from_arrays([pa.array([1]), pa.array([2])], names=["a", "a"])
    config = _single_config(tmp_path, table)
    config["tables"][0]["columns"] = [{"name": "a", "strategy": "passthrough"}]
    with pytest.raises(ExecutionError) as caught:
        estimate_job_capacity(config, tmp_path)
    assert caught.value.code == "capacity_source_unprofilable"
    assert isinstance(caught.value.__cause__, ValueError)
    assert str(caught.value.__cause__) == "table 't' has 1 duplicated field name(s)"
