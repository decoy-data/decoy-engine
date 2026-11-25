"""V10: leak_check records every column and table it does not check, with a registered code.

A column that the entry names in ``columns:`` and then skips also raises a ``QualityWarning``
(``leak_check_column_not_checked``) on a run, which still passes. A column that only came from
the default scope is recorded and raises no warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine import reasons
from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.validators import (
    ValidationSession,
    plan_scope,
    unchecked_named_columns,
    validate,
)


def _table(name: str, strategy: str, **col: Any) -> dict[str, Any]:
    return {"name": name, "columns": [{"name": "email", "strategy": strategy, **col}]}


def _config(tables: list[dict[str, Any]], **entry: Any) -> dict[str, Any]:
    return {
        "validators": [{"name": "leak_check", **entry}],
        "tables": tables,
        "relationships": [],
    }


def _same(rows: int = 3) -> dict[str, pa.Table]:
    return {"customers": pa.table({"email": [f"a{i}@x.test" for i in range(rows)]})}


def test_a_named_passthrough_column_is_a_recorded_skip() -> None:
    outputs = sources = _same()
    config = _config([_table("customers", "passthrough")], columns={"customers": ["email"]})
    report = validate(outputs, config, sources=sources)
    (result,) = report.results
    assert report.passed is True
    assert result.status == "skipped"
    assert result.checked == ()
    assert result.skipped == (("customers", "email", "leak_check_skip_passthrough"),)
    assert unchecked_named_columns(config, report) == result.skipped


def test_the_default_scope_records_the_skip_and_names_nothing() -> None:
    outputs = sources = _same()
    config = _config([_table("customers", "passthrough")])
    report = validate(outputs, config, sources=sources)
    assert report.results[0].skipped == (("customers", "email", "leak_check_skip_passthrough"),)
    assert unchecked_named_columns(config, report) == ()


def test_fewer_cells_than_min_rows_is_a_recorded_skip() -> None:
    outputs = {"customers": pa.table({"email": [f"new{i}" for i in range(10)]})}
    sources = {"customers": pa.table({"email": [f"old{i}" for i in range(10)]})}
    config = _config([_table("customers", "hash")], params={"min_rows": 50})
    (result,) = validate(outputs, config, sources=sources).results
    assert result.status == "skipped"
    assert result.skipped == (("customers", "email", "leak_check_skip_below_min_rows"),)


def test_a_scoped_table_the_run_did_not_produce_is_a_whole_table_skip() -> None:
    outputs = {"other": pa.table({"x": [1]})}
    config = _config([_table("customers", "hash")], columns={"customers": ["email"]})
    (result,) = validate(outputs, config, sources={"customers": _same()["customers"]}).results
    assert result.skipped == (("customers", None, "leak_check_skip_table_not_produced"),)
    assert result.status == "skipped"


def test_each_remaining_exclusion_has_its_own_code() -> None:
    outputs = sources = {
        "t": pa.table({"exempt": ["a"], "child": ["b"], "when": ["c"], "kept": ["d"]})
    }
    tables = [
        {
            "name": "t",
            "columns": [
                {"name": "exempt", "strategy": "hash"},
                {"name": "child", "strategy": "hash"},
                {"name": "when", "strategy": "hash", "when": "exempt == 'a'"},
                {"name": "kept", "strategy": "hash"},
            ],
        }
    ]
    config = _config(
        tables,
        columns={"t": ["exempt", "child", "when", "absent"]},
        params={"exempt": {"t": ["exempt"]}},
    )
    config["relationships"] = [
        {
            "parent": {"table": "p", "columns": ["id"]},
            "children": [{"table": "t", "columns": ["child"]}],
        }
    ]
    (result,) = validate(outputs, config, sources=sources).results
    assert {s.column: s.code for s in result.skipped} == {
        "exempt": "leak_check_skip_exempt",
        "child": "leak_check_skip_fk_child",
        "when": "leak_check_skip_when",
        "absent": "leak_check_skip_missing_column",
    }


def test_plan_scope_reports_the_config_level_skips_without_any_data() -> None:
    config = _config([_table("customers", "passthrough")], columns={"customers": ["email"]})
    plan = plan_scope(config, config["validators"][0])
    assert plan.config_skips() == (("customers", "email", "leak_check_skip_passthrough"),)


def test_every_skip_code_is_registered_as_a_warning() -> None:
    codes = {
        reasons.warning.LEAK_CHECK_COLUMN_NOT_CHECKED,
        reasons.warning.LEAK_CHECK_SKIP_BELOW_MIN_ROWS,
        reasons.warning.LEAK_CHECK_SKIP_EXEMPT,
        reasons.warning.LEAK_CHECK_SKIP_FK_CHILD,
        reasons.warning.LEAK_CHECK_SKIP_MISSING_COLUMN,
        reasons.warning.LEAK_CHECK_SKIP_PASSTHROUGH,
        reasons.warning.LEAK_CHECK_SKIP_TABLE_NOT_PRODUCED,
        reasons.warning.LEAK_CHECK_SKIP_WHEN,
    }
    assert len(codes) == 8
    assert all(c.namespace == "warning" for c in codes)


def test_a_session_builds_the_same_result_as_validate() -> None:
    outputs = sources = _same()
    config = _config([_table("customers", "passthrough")], columns={"customers": ["email"]})
    session = ValidationSession(config, sources=sources)
    session.observe_published("customers", outputs["customers"])
    assert session.finish().results == validate(outputs, config, sources=sources).results


# ---------------------------------------------------------------------------
# A run: the warning and the pass
# ---------------------------------------------------------------------------


def _run(tmp_path: Path, **entry: Any) -> dict[str, Any]:
    src = pa.table({"email": ["a@x.test", "b@x.test", "c@x.test"], "id": [1, 2, 3]})
    path = tmp_path / "customers.parquet"
    pq.write_table(src, path)
    config = {
        "version": 2,
        "global_settings": {"job_name": "v10", "seed": 42},
        "sources": {"customers": {"type": "file", "path": str(path), "format": "parquet"}},
        "targets": {"customers": {"type": "file", "path": str(path) + ".out", "format": "parquet"}},
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "email", "strategy": "passthrough"},
                    {"name": "id", "strategy": "passthrough"},
                ],
            }
        ],
        "relationships": [],
        "validators": [{"name": "leak_check", **entry}],
    }
    result = run_pipeline(config, {"customers": src}, engine_version="0.1.0")
    return dict(result.quality_metrics["validation"])


def test_a_run_that_names_a_kept_column_passes_and_warns_once(tmp_path: Path) -> None:
    block = _run(tmp_path, columns={"customers": ["email"]})
    assert block["validators"]["passed"] is True
    (warning,) = block["warnings"]
    assert warning["code"] == "leak_check_column_not_checked"
    assert warning["column"] == "email"
    assert warning["detail"] == {"table": "customers", "reason": "leak_check_skip_passthrough"}
    (result,) = block["validators"]["results"]
    assert result["status"] == "skipped"


def test_a_run_with_the_default_scope_records_the_skip_and_does_not_warn(tmp_path: Path) -> None:
    block = _run(tmp_path)
    assert "warnings" not in block
    skipped = [tuple(s) for s in block["validators"]["results"][0]["skipped"]]
    assert ("customers", "email", "leak_check_skip_passthrough") in skipped
