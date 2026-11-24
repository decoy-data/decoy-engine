"""V13: no cell value reaches a finding, a result, a skip record, a warning, a log line or an error.

Every validated cell below holds a marker. Every validator fails on it. The marker must not
appear in anything the validators produce. The refusals (a source that does not pair, a key
state over its budget, a missing source) also name tables and columns only.
"""

from __future__ import annotations

import logging
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators import ValidationSession, validate

MARK = "SECRET-MARK-7731"


def _rel(parent: str, child: str, pcol: str = "id", ccol: str = "pid") -> dict[str, Any]:
    return {
        "parent": {"table": parent, "columns": [pcol]},
        "children": [{"table": child, "columns": [ccol]}],
    }


def _all_failing() -> tuple[dict[str, pa.Table], dict[str, Any], dict[str, pa.Table]]:
    marked = [MARK, MARK + "-b"]
    outputs = {
        "t": pa.table({"cc": marked, "leak": marked}),
        "parent": pa.table({"id": [MARK + "-p"], "start": [MARK + "-s"], "end": [MARK + "-e"]}),
        "child": pa.table({"pid": [MARK + "-c", None], "d": [MARK + "-d", MARK + "-d2"]}),
        "ledger": pa.table({"id": [MARK + "-p"], "total": [MARK + "-t"]}),
        "lines": pa.table({"pid": [MARK + "-p"], "amt": [MARK + "-a"]}),
    }
    sources = {"t": pa.table({"cc": marked, "leak": marked})}
    column_checks = [
        {"name": name, "columns": {"t": ["cc"]}} for name in ("luhn", "npi", "iban", "vin")
    ]
    config = {
        "tables": [{"name": "t", "columns": [{"name": "leak", "strategy": "hash"}]}],
        "relationships": [_rel("parent", "child"), _rel("ledger", "lines")],
        "validators": [
            *column_checks,
            {"name": "regex_match", "columns": {"t": ["cc"]}, "params": {"pattern": "ok"}},
            {
                "name": "column_in_set",
                "columns": {"t": ["cc"]},
                "params": {"allowed_values": ["fine"]},
            },
            {"name": "fk_intact"},
            {"name": "no_orphan_children"},
            {"name": "leak_check", "columns": {"t": ["leak"]}},
            {
                "name": "parent_window_respected",
                "params": {
                    "child_table": "child",
                    "child_column": "d",
                    "parent_table": "parent",
                    "window_start_column": "start",
                    "window_end_column": "end",
                },
            },
            {
                "name": "reconciliation_holds",
                "params": {
                    "parent_table": "ledger",
                    "parent_column": "total",
                    "child_table": "lines",
                    "child_column": "amt",
                },
            },
        ],
    }
    return outputs, config, sources


@pytest.mark.filterwarnings("ignore")
def test_no_marker_in_any_report_field_or_log_line(caplog: pytest.LogCaptureFixture) -> None:
    outputs, config, sources = _all_failing()
    with caplog.at_level(logging.DEBUG):
        report = validate(outputs, config, sources=sources)
    assert {f.validator for f in report.findings} == {v["name"] for v in config["validators"]}
    assert MARK not in repr(report)
    assert MARK not in caplog.text
    assert all(MARK not in str(arg) for rec in caplog.records for arg in (rec.args or ()))


def test_no_marker_in_a_skip_record() -> None:
    outputs = sources = {"t": pa.table({"leak": [MARK]})}
    config = {
        "tables": [{"name": "t", "columns": [{"name": "leak", "strategy": "passthrough"}]}],
        "relationships": [],
        "validators": [{"name": "leak_check", "columns": {"t": ["leak"]}}],
    }
    report = validate(outputs, config, sources=sources)
    assert report.results[0].skipped
    assert MARK not in repr(report)


def test_a_missing_source_error_names_the_table_only() -> None:
    config = {
        "tables": [{"name": "t", "columns": [{"name": "leak", "strategy": "hash"}]}],
        "relationships": [],
        "validators": [{"name": "leak_check"}],
    }
    with pytest.raises(ValueError, match="leak_check") as err:
        validate({"t": pa.table({"leak": [MARK]})}, config)
    assert MARK not in str(err.value)


def test_a_pairing_mismatch_names_the_table_only() -> None:
    config = {
        "tables": [{"name": "t", "columns": [{"name": "leak", "strategy": "hash"}]}],
        "relationships": [],
        "validators": [{"name": "leak_check"}],
    }
    session = ValidationSession(config, sources={"t": pa.table({"leak": [MARK] * 3})})
    session.observe_published("t", pa.table({"leak": [MARK] * 2}))
    with pytest.raises(ValidatorStateError) as err:
        session.finish()
    assert MARK not in str(err.value)
    assert err.value.__cause__ is None and err.value.__context__ is None


def test_a_budget_refusal_names_the_table_and_column_only() -> None:
    outputs, config, _ = _all_failing()
    config = {**config, "validators": [config["validators"][-2]]}
    session = ValidationSession(config, key_state_budget_bytes=1)
    with pytest.raises(ValidatorStateError) as err:
        session.observe_published("child", outputs["child"])
    assert "child.d" in str(err.value)
    assert MARK not in str(err.value)
    assert err.value.__cause__ is None and err.value.__context__ is None
