"""Mutation controls for the inherited_columns invariant (`inherit` generate columns).

Each control applies one known-bad change to an otherwise faithful parent/child output and
asserts check_inherited_columns raises; the faithful output passes, so the check does not
over-assert.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from testflight._evaluate import evaluate_invariants
from testflight._inherited import check_inherited_columns
from testflight._spec import FlightManifest, InheritedColumnSpec, InvariantSpec, TableSpec

pytestmark = pytest.mark.testflight

PARENT: dict[str, list[Any]] = {"clinic_id": [1, 2, 3], "clinic_tier": ["Gold", "Silver", "Bronze"]}
CHILD: dict[str, list[Any]] = {
    "stay_id": [1, 2, 3, 4, 5],
    "clinic_id": [2, None, 1, 3, 2],
    "clinic_tier": ["Silver", None, "Gold", "Bronze", "Silver"],
}
SPEC = InheritedColumnSpec(
    table="clinic_stays",
    column="clinic_tier",
    via="clinic_id",
    parent_table="clinics",
    parent_key="clinic_id",
    parent_column="clinic_tier",
    min_null_keys=1,
    min_distinct_values=3,
)


def _result(child: dict[str, list[Any]] | None = None, parent: dict[str, list[Any]] | None = None):
    return SimpleNamespace(
        outputs={
            "clinics": pa.table(parent or PARENT),
            "clinic_stays": pa.table(child or CHILD),
        },
        quality_metrics={},
    )


def _child(**changes: list[Any]) -> dict[str, list[Any]]:
    return {**CHILD, **changes}


def test_a_faithful_copy_passes() -> None:
    evidence = check_inherited_columns("inherit_ctl", [SPEC], _result())
    assert "clinic_stays.clinic_tier(rows=5, null_keys=1, distinct=3)" in evidence


def test_a_copy_from_the_wrong_parent_row_raises() -> None:
    wrong = _child(clinic_tier=["Gold", None, "Gold", "Bronze", "Silver"])
    with pytest.raises(AssertionError, match="parent holds 'Silver'"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(wrong))


def test_a_value_beside_a_null_key_raises() -> None:
    kept = _child(clinic_tier=["Silver", "Gold", "Gold", "Bronze", "Silver"])
    with pytest.raises(AssertionError, match="null key but value"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(kept))


def test_a_key_with_no_parent_row_raises() -> None:
    orphan = _child(clinic_id=[2, None, 1, 9, 2])
    with pytest.raises(AssertionError, match="has no parent row"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(orphan))


def test_a_copy_with_another_type_raises() -> None:
    parent: dict[str, list[Any]] = {"clinic_id": [1, 2, 3], "clinic_tier": [10, 20, 30]}
    text = _child(clinic_tier=["20", None, "10", "30", "20"])
    with pytest.raises(AssertionError, match="parent holds 20"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(text, parent))


def test_a_parent_key_that_repeats_raises() -> None:
    parent: dict[str, list[Any]] = {
        "clinic_id": [1, 2, 2],
        "clinic_tier": ["Gold", "Silver", "Bronze"],
    }
    with pytest.raises(AssertionError, match="is not unique"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(parent=parent))


def test_a_fixture_without_null_keys_is_vacuous() -> None:
    full = _child(
        clinic_id=[2, 3, 1, 3, 2], clinic_tier=["Silver", "Bronze", "Gold", "Bronze", "Silver"]
    )
    with pytest.raises(AssertionError, match="null-key row"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(full))


def test_a_fixture_with_one_copied_value_is_vacuous() -> None:
    one = _child(
        clinic_id=[2, None, 2, 2, 2], clinic_tier=["Silver", None, "Silver", "Silver", "Silver"]
    )
    with pytest.raises(AssertionError, match="distinct inherited value"):
        check_inherited_columns("inherit_ctl", [SPEC], _result(one))


def test_evaluate_invariants_fails_a_wrong_copy_end_to_end() -> None:
    manifest = FlightManifest(
        job_name="inherit_wiring",
        topology="mixed",
        seed=1,
        master_key_label="inherit",
        tables=[
            TableSpec(name="clinics", kind="generate", row_count=3),
            TableSpec(name="clinic_stays", kind="generate", row_count=5),
        ],
        invariants=InvariantSpec(determinism=False, inherited_columns=[SPEC]),
    )
    wrong = _result(_child(clinic_tier=["Gold", None, "Gold", "Bronze", "Silver"]))
    found = [
        r
        for r in evaluate_invariants(manifest, wrong, wrong, {})
        if r.family == "inherited_columns"
    ]
    assert len(found) == 1 and found[0].passed is False, found
    good = _result()
    found = [
        r for r in evaluate_invariants(manifest, good, good, {}) if r.family == "inherited_columns"
    ]
    assert len(found) == 1 and found[0].passed is True, found
