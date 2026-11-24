"""Bounded state, pairing and lifecycle of the validation session."""

from __future__ import annotations

import dataclasses
import random

import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators import ValidationSession, validate
from decoy_engine.validators._fold import CappedIndices, KeyStateBudget
from tests.unit.validators._fold_cases import build_cases


@settings(derandomize=True, max_examples=80, deadline=None)
@given(
    indices=st.lists(st.integers(min_value=0, max_value=500), unique=True, max_size=120),
    cap=st.sampled_from([1, 5, 50, None]),
)
def test_capped_indices_keep_the_lowest_positions_in_any_arrival_order(
    indices: list[int], cap: int | None
) -> None:
    shuffled = list(indices)
    random.Random(7).shuffle(shuffled)
    tally = CappedIndices(cap)
    for i in shuffled:
        tally.add(i)
    ordered = sorted(indices)
    assert tally.count == len(indices)
    assert tally.indices() == tuple(ordered if cap is None else ordered[:cap])


def test_the_budget_refuses_with_its_registered_code_and_releases_what_it_gave_back() -> None:
    budget = KeyStateBudget(100)
    budget.reserve(60, table="t", column="c")
    with pytest.raises(ValidatorStateError) as err:
        budget.reserve(60, table="t", column="c")
    assert err.value.code == reasons.runtime.VALIDATOR_KEY_STATE_OVER_BUDGET
    budget.release(60)
    budget.reserve(100, table="t", column=None)
    assert budget.used == 100


def _window_session(budget: int | None) -> ValidationSession:
    case = build_cases()["parent_window_respected"]
    return ValidationSession(case.config, key_state_budget_bytes=budget)


def test_pending_children_are_reserved_one_by_one_and_refused_past_the_ceiling() -> None:
    case = build_cases()["parent_window_respected"]
    child = case.outputs["child"]
    refused_after = None
    session = _window_session(900)
    for i in range(child.num_rows):
        try:
            session.observe_published("child", child.slice(i, 1))
        except ValidatorStateError as err:
            assert err.code == reasons.runtime.VALIDATOR_KEY_STATE_OVER_BUDGET
            refused_after = i
            break
    assert refused_after is not None and refused_after > 0
    # With no ceiling the same rows are all held.
    unbounded = _window_session(None)
    for i in range(child.num_rows):
        unbounded.observe_published("child", child.slice(i, 1))


def test_the_pending_state_is_released_when_the_parent_table_completes() -> None:
    case = build_cases()["fk_intact"]
    budget_probe = ValidationSession(case.config, key_state_budget_bytes=10_000)
    budget_probe.observe_published("child", case.outputs["child"])
    budget_probe.observe_published("parent", case.outputs["parent"])
    first = budget_probe.finish()
    again = ValidationSession(case.config, key_state_budget_bytes=10_000)
    again.observe("parent", case.outputs["parent"])
    again.observe("child", case.outputs["child"])
    assert dataclasses.replace(first, elapsed_ms=0.0) == dataclasses.replace(
        again.finish(), elapsed_ms=0.0
    )


def test_a_self_referencing_key_resolves_when_its_table_completes() -> None:
    table = pa.table({"id": [1, 2, 3, 4], "boss": [None, 1, 9, 2]})
    config = {
        "validators": [{"name": "fk_intact"}],
        "relationships": [
            {
                "parent": {"table": "emp", "columns": ["id"]},
                "children": [{"table": "emp", "columns": ["boss"]}],
            }
        ],
    }
    whole = validate({"emp": table}, config)
    session = ValidationSession(config)
    for i in range(table.num_rows):
        session.observe_published("emp", table.slice(i, 1))
    got = session.finish()
    assert got.findings == whole.findings
    assert got.findings[0].failing_row_indices == (2,)


def test_a_source_that_does_not_pair_with_the_published_rows_is_refused() -> None:
    case = build_cases()["leak_check"]
    short = case.sources["t"].slice(0, 3)
    session = ValidationSession(case.config, sources={"t": short})
    with pytest.raises(ValidatorStateError) as err:
        session.observe_published("t", case.outputs["t"])
    assert err.value.code == reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH


def test_a_longer_source_is_refused_at_finish() -> None:
    case = build_cases()["leak_check"]
    session = ValidationSession(case.config, sources={"t": case.sources["t"]})
    session.observe_published("t", case.outputs["t"].slice(0, 3))
    with pytest.raises(ValidatorStateError) as err:
        session.finish()
    assert err.value.code == reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH


def test_observe_pair_feeds_the_raw_batch_with_the_published_one() -> None:
    case = build_cases()["leak_check"]
    whole = validate(case.outputs, case.config, sources=case.sources)
    session = ValidationSession(case.config)
    for i in range(0, 5, 2):
        session.observe_pair("t", case.sources["t"].slice(i, 2), case.outputs["t"].slice(i, 2))
    assert dataclasses.replace(session.finish(), elapsed_ms=0.0) == dataclasses.replace(
        whole, elapsed_ms=0.0
    )


def test_finish_is_idempotent_and_a_finished_session_takes_no_rows() -> None:
    case = build_cases()["luhn"]
    session = ValidationSession(case.config)
    session.observe("t", case.outputs["t"])
    assert session.finish() is session.finish()
    with pytest.raises(ValueError, match="finished"):
        session.observe_published("t", case.outputs["t"])


def test_a_missing_parent_table_is_refused_at_finish_as_before() -> None:
    case = build_cases()["fk_intact"]
    session = ValidationSession(case.config)
    session.observe("child", case.outputs["child"])
    with pytest.raises(ValueError, match="parent table 'parent'"):
        session.finish()


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"name": "no_such_validator"}, "unknown validator"),
        ("not a dict", "must be a dict"),
        ({"name": "regex_match", "columns": {"t": ["c"]}}, "requires params.pattern"),
        (
            {"name": "regex_match", "columns": {"t": ["c"]}, "params": {"pattern": "("}},
            "not a valid regex",
        ),
        ({"name": "column_in_set", "columns": {"t": ["c"]}}, "requires params.allowed_values"),
    ],
)
def test_bad_entries_and_parameters_are_refused_when_the_session_opens(
    entry: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ValidationSession({"validators": [entry]})
