"""Final review on the fold change: leak_check without a source, key memory by value size,
a child that lacks its declared FK column, a status that never reads passed on nothing checked,
and the one report builder both routes use.
"""

from __future__ import annotations

import tracemalloc
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.validators import (
    FoldResult,
    ValidationSession,
    ValidatorFinding,
    assemble_report,
    validate,
)
from decoy_engine.validators._fk_validators import key_bytes
from decoy_engine.validators._types import result_status
from tests.unit.validators._fold_cases import build_cases, build_extra_cases

_MISSING_COLUMN = "validator_skip_missing_column"

# --- V1-a: no source is fine when no column is compared ----------------------------------------


def test_leak_check_without_a_source_passes_when_every_column_is_skipped() -> None:
    case = build_extra_cases()["leak_check_skipped_columns_do_not_pair"]
    report = validate(case.outputs, case.config)
    (result,) = report.results
    assert report.passed is True
    assert result.status == "skipped" and result.checked == ()
    assert result.skipped == (("t", "e", reasons.warning.LEAK_CHECK_SKIP_PASSTHROUGH),)


def test_the_session_without_a_source_records_the_same_skips() -> None:
    case = build_extra_cases()["leak_check_skipped_columns_do_not_pair"]
    session = ValidationSession(case.config)
    session.observe_published("t", case.outputs["t"])
    assert session.finish().results[0].skipped == (
        ("t", "e", reasons.warning.LEAK_CHECK_SKIP_PASSTHROUGH),
    )


def test_leak_check_without_a_source_still_refuses_when_a_column_would_be_compared() -> None:
    case = build_cases()["leak_check"]
    with pytest.raises(ValueError, match="no source table"):
        validate(case.outputs, case.config)


# --- V1-b: the key estimate counts the value, not only the key width ----------------------------

_KEYS = 10_000


def _real_and_reserved(case: Any, child: pa.Table) -> tuple[float, float]:
    session = ValidationSession(case.config, key_state_budget_bytes=10**10)
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        session.observe_published("child", child)
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    reserved = session._folds[0]._budget.used  # type: ignore[attr-defined]
    return float(after - before), float(reserved)


def _string_fk_case() -> Any:
    case = build_cases()["fk_intact"]
    config = {
        **case.config,
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["pid"]}],
            }
        ],
    }
    return case._replace(config=config)


@pytest.mark.serial
def test_unique_long_string_keys_are_charged_at_their_length() -> None:
    child = pa.table({"pid": [f"{i:06d}" + "x" * 994 for i in range(_KEYS)]})
    real, reserved = _real_and_reserved(_string_fk_case(), child)
    assert reserved >= real, (reserved, real)


@pytest.mark.serial
def test_unique_composite_keys_are_charged_for_every_part() -> None:
    case = build_cases()["fk_intact"]
    config = {
        **case.config,
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["a", "b"]},
                "children": [{"table": "child", "columns": ["a", "b"]}],
            }
        ],
    }
    child = pa.table(
        {
            "a": [f"{i:06d}" + "y" * 400 for i in range(_KEYS)],
            "b": [f"{i:06d}" + "z" * 400 for i in range(_KEYS)],
        }
    )
    real, reserved = _real_and_reserved(case._replace(config=config), child)
    assert reserved >= real, (reserved, real)


def test_a_longer_key_costs_more() -> None:
    assert key_bytes(("x" * 1000,)) > key_bytes(("x",)) + 900
    assert key_bytes(("a", "b")) > key_bytes(("a",))


# --- V1-c: a missing FK column is a skip, and nothing checked is never passed -------------------


@pytest.mark.parametrize("name", ["fk_intact", "no_orphan_children"])
def test_a_child_without_its_fk_column_is_skipped_not_passed(name: str) -> None:
    case = build_cases()[name]
    outputs = {**case.outputs, "child": pa.table({"other": [1, 2, 3]})}
    report = validate(outputs, case.config)
    (result,) = report.results
    assert result.status == "skipped"
    assert result.checked == ()
    assert result.skipped == (("child", "pid", _MISSING_COLUMN),)


@pytest.mark.parametrize("name", ["fk_intact", "no_orphan_children"])
def test_a_child_missing_the_fk_column_in_one_batch_is_still_skipped(name: str) -> None:
    case = build_cases()[name]
    session = ValidationSession(case.config)
    session.observe_published("parent", case.outputs["parent"])
    session.observe_published("child", pa.table({"other": [1]}))
    (result,) = session.finish().results
    assert result.status == "skipped" and result.skipped == (("child", "pid", _MISSING_COLUMN),)


def test_parent_window_and_reconciliation_skip_a_child_missing_its_fk_column() -> None:
    for name in ("parent_window_respected", "reconciliation_holds"):
        case = build_cases()[name]
        child = case.outputs["child"]
        fk = next(c for c in child.schema.names if c in ("pid", "parent_id", "fk"))
        report = validate({**case.outputs, "child": child.drop_columns([fk])}, case.config)
        (result,) = report.results
        assert result.status == "skipped", name
        assert result.skipped[0][1] == fk, name


def test_status_is_skipped_when_nothing_was_checked_and_nothing_was_recorded() -> None:
    assert result_status((), (), ()) == "skipped"
    assert result_status((), (), (("t", None, "x"),)) == "skipped"
    assert result_status((), (("t", "c"),), ()) == "passed"


# --- DESIGN: one report builder -----------------------------------------------------------------


def test_assemble_report_builds_status_skips_and_totals_from_outcomes() -> None:
    finding = ValidatorFinding("luhn", "t", "c", (0, 3), "2 row(s) bad", failing_row_count=2)
    outcomes = [
        FoldResult((finding,), (("t", "c"),), ()),
        FoldResult((), (), (("g", None, "validator_skip_missing_table"),)),
        FoldResult((), (("t", "c"),), ()),
    ]
    report = assemble_report(["luhn", "iban", "luhn"], outcomes, 5.0)
    assert report.passed is False
    assert report.validators_run == ("luhn", "iban")
    assert report.findings == (finding,)
    assert [r.status for r in report.results] == ["failed", "skipped", "passed"]
    assert [r.entry_index for r in report.results] == [0, 1, 2]
    assert report.results[0].failing_row_count == 2
    assert report.elapsed_ms == 5.0


def test_the_out_of_core_collector_uses_the_public_builder() -> None:
    import inspect

    from decoy_engine.execution.out_of_core import _validate_batch

    source = inspect.getsource(_validate_batch)
    assert "validators._types" not in source
    assert "validators._registry" not in source
    assert "assemble_report" in source
