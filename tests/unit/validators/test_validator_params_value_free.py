"""Validator parameters never reach an error, a finding or a quarantine reason (EXPECT-OFF-ROUTE S2).

An operator can put a credential in a regex or a number field. Python's own conversion and
compile errors quote it, so every entry point has to refuse without echoing it.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.quarantine import compute_quarantine
from decoy_engine.validators import ValidationSession, validate, validator_function
from decoy_engine.validators._fold import KeyStateBudget
from decoy_engine.validators._registry import build_fold

SECRET = "hunter2-credential"
URL = f"https://user:{SECRET}@host.example/path"
_RELATIONSHIP = {
    "parent": {"table": "p", "columns": ["id"]},
    "children": [{"table": "c", "columns": ["pid"]}],
}


def _assert_value_free(exc: BaseException) -> None:
    assert SECRET not in str(exc)
    assert exc.__cause__ is None
    assert not exc.__suppress_context__ or exc.__context__ is None
    assert exc.__context__ is None


def test_invalid_regex_error_names_the_parameter_only() -> None:
    entry = {
        "name": "regex_match",
        "columns": {"t": ["c"]},
        "params": {"pattern": f"(?P<{URL}>x)"},
    }
    with pytest.raises(ValueError, match="params.pattern") as excinfo:
        validator_function("regex_match")({}, entry, {})
    _assert_value_free(excinfo.value)
    with pytest.raises(ValueError, match="params.pattern") as session_exc:
        ValidationSession({"validators": [entry]})
    _assert_value_free(session_exc.value)


def test_a_failing_regex_finding_does_not_echo_the_pattern() -> None:
    config: dict[str, Any] = {
        "validators": [
            {
                "name": "regex_match",
                "columns": {"t": ["c"]},
                "params": {"pattern": f"^{URL}$"},
            }
        ]
    }
    report = validate({"t": pa.table({"c": ["x", "y"]})}, config)
    assert report.passed is False
    assert all(SECRET not in finding.detail for finding in report.findings)


def test_a_quarantine_reason_does_not_echo_the_pattern() -> None:
    config: dict[str, Any] = {
        "validators": [
            {
                "name": "regex_match",
                "columns": {"t": ["c"]},
                "params": {"pattern": f"^{URL}$"},
            }
        ]
    }
    outputs = {"t": pa.table({"c": ["x", "y"]})}
    report = validate(outputs, config)
    _, entries, _, total = compute_quarantine(outputs, report, {"triggers": ["validation_fail"]})
    assert total == 2
    assert SECRET not in repr(entries)


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("leak_check", {"max_identical_ratio": URL}),
        ("leak_check", {"min_rows": URL}),
        (
            "reconciliation_holds",
            {
                "parent_table": "p",
                "parent_column": "v",
                "child_table": "c",
                "child_column": "v",
                "tolerance": URL,
            },
        ),
    ],
)
def test_numeric_parameter_errors_are_value_free_on_every_entry_point(
    name: str, params: dict[str, Any]
) -> None:
    entry = {"name": name, "params": params}
    config = {"relationships": [_RELATIONSHIP], "validators": [entry]}
    with pytest.raises(ValueError, match="params") as direct:
        validator_function(name)({}, entry, config)
    _assert_value_free(direct.value)
    with pytest.raises(ValueError, match="params") as opened:
        ValidationSession(config)
    _assert_value_free(opened.value)
    with pytest.raises(ValueError, match="params") as folded:
        build_fold(entry, config, cap=None, budget=KeyStateBudget(None), sources=None)
    _assert_value_free(folded.value)
