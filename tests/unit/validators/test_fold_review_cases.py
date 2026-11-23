"""Review round 1 on the fold change: each case here failed before it was fixed.

H1 the date format comes from the first value pandas would use, M1 a column listed twice,
M2 a source that need not pair, M3 a missing parent column, M4 the key-state estimate against
real memory, M5 a whole-table validator fed batches, M6 a validator that checked nothing.
"""

from __future__ import annotations

import dataclasses
import tracemalloc
from typing import Any

import numpy as np
import pyarrow as pa
import pytest
from pandas._libs import tslib

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators import ValidationSession, validate
from decoy_engine.validators._fk_validators import key_bytes
from decoy_engine.validators._registry import _REGISTRY
from decoy_engine.validators._relationship_checks import _is_blank
from tests.unit.validators._fold_cases import build_cases, build_extra_cases
from tests.unit.validators.test_session_invariance import feed

# --- H1 ---------------------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore")
@pytest.mark.parametrize(
    "value",
    ["", "NaT", "nat", "NAT", "nan", "NaN", "NAN", "None", " ", "null", "N/A", "2024-01-05", None],
)
def test_the_blank_rule_is_the_one_pandas_uses_to_pick_the_format_value(value: Any) -> None:
    probe = np.array([value, "2024-01-05"], dtype=object)
    pandas_skips_it = tslib.first_non_null(probe) == 1
    assert _is_blank(value) == pandas_skips_it


@pytest.mark.parametrize("chunk", [1, 2, None])
def test_a_leading_blank_does_not_fix_the_format_of_the_column(chunk: int | None) -> None:
    case = build_extra_cases()["parent_window_leading_blank"]
    whole = validate(case.outputs, case.config)
    chunked = feed(case, chunk, ["parent", "child"], interleave=False)
    assert whole.findings[0].failing_row_indices == (0, 2)
    assert dataclasses.replace(chunked, elapsed_ms=0.0) == dataclasses.replace(
        whole, elapsed_ms=0.0
    )


def test_a_first_span_of_only_blanks_leaves_the_format_unset() -> None:
    case = build_extra_cases()["parent_window_leading_blank"]
    # The blank row alone is span one; the format must come from "2024-01-05" in span two.
    got = feed(case, 1, ["parent", "child"], interleave=False)
    assert got.findings[0].failing_row_indices == (0, 2)


# --- M1 ---------------------------------------------------------------------------------------


def test_a_column_listed_twice_is_two_independent_checks() -> None:
    case = build_extra_cases()["leak_check_repeated_column"]
    report = validate(case.outputs, case.config, sources=case.sources)
    assert [f.failing_row_count for f in report.findings] == [3, 3, 3, 3]
    assert all(f.failing_row_indices == (0, 1, 2) for f in report.findings)
    chunked = feed(case, 1, ["t"], interleave=False)
    assert chunked.findings == report.findings


# --- M2 ---------------------------------------------------------------------------------------


def test_a_table_whose_columns_are_all_skipped_needs_no_pairing() -> None:
    case = build_extra_cases()["leak_check_skipped_columns_do_not_pair"]
    assert validate(case.outputs, case.config, sources=case.sources).passed is True
    session = ValidationSession(case.config, sources=case.sources)
    session.observe_published("t", case.outputs["t"])
    assert session.finish().passed is True


def test_a_table_with_a_checked_column_still_must_pair() -> None:
    case = build_cases()["leak_check"]
    session = ValidationSession(case.config, sources={"t": case.sources["t"].slice(0, 4)})
    with pytest.raises(ValidatorStateError) as err:
        session.observe_published("t", case.outputs["t"])
    assert err.value.code == reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH


# --- M3 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["start", "end", "id"])
def test_a_parent_without_a_window_or_key_column_is_a_coded_refusal(missing: str) -> None:
    case = build_cases()["parent_window_respected"]
    parent = case.outputs["parent"].drop_columns([missing])
    session = ValidationSession(case.config)
    with pytest.raises(ValidatorStateError) as err:
        session.observe_published("parent", parent)
    assert err.value.code == reasons.runtime.VALIDATOR_COLUMN_MISSING
    assert missing in str(err.value) and "parent" in str(err.value)
    assert err.value.__cause__ is None and err.value.__context__ is None


def test_a_reconciliation_parent_without_its_key_column_is_a_coded_refusal() -> None:
    case = build_cases()["reconciliation_holds"]
    session = ValidationSession(case.config)
    with pytest.raises(ValidatorStateError) as err:
        session.observe_published("parent", case.outputs["parent"].drop_columns(["id"]))
    assert err.value.code == reasons.runtime.VALIDATOR_COLUMN_MISSING


# --- M4 ---------------------------------------------------------------------------------------

_ROWS = 20_000


def _retained_bytes_per_item(run: Any) -> float:
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        keep = run()
        after = tracemalloc.get_traced_memory()[0]
        del keep
    finally:
        tracemalloc.stop()
    return (after - before) / _ROWS


def test_the_estimate_for_a_pending_date_observation_is_at_least_its_real_cost() -> None:
    case = build_cases()["parent_window_respected"]
    child = pa.table(
        {"pid": [1] * _ROWS, "d": pa.array([f"2020-03-{i % 28 + 1:02d}" for i in range(_ROWS)])}
    )
    session = ValidationSession(case.config, key_state_budget_bytes=10**9)

    def run() -> ValidationSession:
        session.observe_published("child", child)
        return session

    real = _retained_bytes_per_item(run)
    reserved = session._folds[0]._budget.used / _ROWS  # type: ignore[attr-defined]
    assert reserved >= real, (reserved, real)


def test_the_estimate_for_a_pending_foreign_key_is_at_least_its_real_cost() -> None:
    case = build_cases()["fk_intact"]
    child = pa.table({"pid": list(range(1, _ROWS + 1))})
    session = ValidationSession(case.config, key_state_budget_bytes=10**9)

    def run() -> ValidationSession:
        session.observe_published("child", child)
        return session

    real = _retained_bytes_per_item(run)
    reserved = session._folds[0]._budget.used / _ROWS  # type: ignore[attr-defined]
    assert reserved >= real, (reserved, real)
    assert key_bytes(1) > 0


# --- M5 ---------------------------------------------------------------------------------------


def test_a_whole_table_validator_refuses_a_second_batch_of_one_table() -> None:
    seen: list[int] = []

    def whole_only(
        outputs: dict[str, pa.Table], entry: dict[str, Any], config: dict[str, Any], **_: Any
    ) -> tuple[Any, ...]:
        seen.extend(t.num_rows for t in outputs.values())
        return ()

    _REGISTRY["_whole_only_probe"] = whole_only
    try:
        session = ValidationSession({"validators": [{"name": "_whole_only_probe"}]})
        session.observe_published("t", pa.table({"x": [1, 2]}))
        with pytest.raises(ValidatorStateError) as err:
            session.observe_published("t", pa.table({"x": [3]}))
        assert err.value.code == reasons.runtime.VALIDATOR_SPAN_REPEATED
        assert err.value.__cause__ is None and err.value.__context__ is None
        # Different tables are fine, and one span per table still works.
        ok = ValidationSession({"validators": [{"name": "_whole_only_probe"}]})
        ok.observe_published("a", pa.table({"x": [1]}))
        ok.observe_published("b", pa.table({"x": [1, 2]}))
        ok.finish()
        assert sorted(seen) == [1, 2]
    finally:
        del _REGISTRY["_whole_only_probe"]


# --- M6 ---------------------------------------------------------------------------------------

_MISSING_TABLE = "validator_skip_missing_table"
_MISSING_COLUMN = "validator_skip_missing_column"


def _single(report: Any) -> Any:
    (result,) = report.results
    return result


def test_a_cell_validator_with_a_missing_table_or_column_reports_skipped() -> None:
    entry = {"name": "luhn", "columns": {"ghost": ["x"], "t": ["nope"]}}
    config = {"validators": [entry]}
    result = _single(validate({"t": pa.table({"x": ["4532015112830366"]})}, config))
    assert result.status == "skipped" and result.checked == ()
    assert result.skipped == (("ghost", None, _MISSING_TABLE), ("t", "nope", _MISSING_COLUMN))


def test_a_partly_checked_entry_stays_passed_and_lists_what_it_skipped() -> None:
    entry = {"name": "luhn", "columns": {"t": ["cc", "nope"]}}
    result = _single(
        validate({"t": pa.table({"cc": ["4532015112830366"]})}, {"validators": [entry]})
    )
    assert result.status == "passed"
    assert result.checked == (("t", "cc"),)
    assert result.skipped == (("t", "nope", _MISSING_COLUMN),)


def test_relationship_validators_with_nothing_to_look_at_report_skipped() -> None:
    cases = build_cases()
    fk = cases["fk_intact"]
    only_parent = {"parent": fk.outputs["parent"]}
    assert _single(validate(only_parent, fk.config)).skipped == (("child", None, _MISSING_TABLE),)
    assert _single(validate(only_parent, fk.config)).status == "skipped"

    win = cases["parent_window_respected"]
    no_column = {"parent": win.outputs["parent"], "child": win.outputs["child"].drop_columns(["d"])}
    result = _single(validate(no_column, win.config))
    assert (result.status, result.skipped) == ("skipped", (("child", "d", _MISSING_COLUMN),))

    rec = cases["reconciliation_holds"]
    only = {"parent": rec.outputs["parent"]}
    result = _single(validate(only, rec.config))
    assert (result.status, result.skipped) == ("skipped", (("child", None, _MISSING_TABLE),))
