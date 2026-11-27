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


def test_session_construction_reports_a_bad_parameter_as_a_config_error() -> None:
    from decoy_engine.errors import ConfigRuleError
    from decoy_engine.reason_adapter import reason_from_exception

    config = {
        "validators": [{"name": "regex_match", "columns": {"t": ["c"]}, "params": {"pattern": "("}}]
    }
    with pytest.raises(ConfigRuleError) as caught:
        ValidationSession(config)
    assert reason_from_exception(caught.value).code != "unexpected_error"


@pytest.mark.parametrize(
    ("params", "expected"),
    [({"min_rows": "50"}, 50), ({"min_rows": " 7 "}, 7)],
)
def test_a_numeric_string_parameter_still_converts(params: dict[str, Any], expected: int) -> None:
    from decoy_engine.validators._params import numeric_param

    assert (
        numeric_param(params, "min_rows", kind=int, default=1, validator="leak_check") == expected
    )
    assert (
        numeric_param({"x": "0.25"}, "x", kind=float, default=0.0, validator="leak_check") == 0.25
    )


def test_a_numeric_string_min_rows_still_runs_through_validate() -> None:
    outputs = {"t": pa.table({"col": [f"new{i}" for i in range(10)]})}
    sources = {"t": pa.table({"col": [f"old{i}" for i in range(10)]})}
    config: dict[str, Any] = {
        "validators": [{"name": "leak_check", "params": {"min_rows": "50"}}],
        "tables": [{"name": "t", "columns": [{"name": "col", "strategy": "hash"}]}],
        "relationships": [],
    }
    (result,) = validate(outputs, config, sources=sources).results
    assert result.skipped == (("t", "col", "leak_check_skip_below_min_rows"),)


def test_a_non_numeric_string_parameter_is_refused_without_its_text() -> None:
    from decoy_engine.validators._params import ParamError, numeric_param

    with pytest.raises(ParamError) as caught:
        numeric_param({"min_rows": URL}, "min_rows", kind=int, default=1, validator="leak_check")
    _assert_value_free(caught.value)
