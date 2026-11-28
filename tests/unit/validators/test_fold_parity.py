"""V1: the fold form of each validator gives the verdicts the whole-table functions gave.

The expected findings below were captured by running ``validate()`` at engine ``311ec1418``
(before the validators became folds) on the fixtures in ``_fold_cases.py``. This is a control:
it passes before and after the change, and it fails if a fold drifts from the old wording,
indices or order.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.validators import validate
from decoy_engine.validators._registry import _REGISTRY
from tests.unit.validators._fold_cases import build_cases, build_extra_cases

_FK_REL = "parent.['id'] -> child.['pid']"

# validator, table, column, failing_row_indices, detail -- captured at 311ec1418.
EXPECTED: dict[str, tuple[tuple[Any, ...], ...]] = {
    "luhn": (("luhn", "t", "cc", (1, 3), "2 row(s) in t.cc failed luhn check-digit validation"),),
    "npi": (("npi", "t", "cc", (1, 3), "2 row(s) in t.cc failed npi check-digit validation"),),
    "iban": (("iban", "t", "cc", (1,), "1 row(s) in t.cc failed iban check-digit validation"),),
    "vin": (("vin", "t", "cc", (1, 2), "2 row(s) in t.cc failed vin check-digit validation"),),
    "regex_match": (
        (
            "regex_match",
            "t",
            "cc",
            (1, 2),
            "2 row(s) in t.cc do not match the configured pattern",
        ),
    ),
    "column_in_set": (
        (
            "column_in_set",
            "t",
            "cc",
            (2, 3, 4),
            "3 row(s) in t.cc are not in the allowed set (2 value(s))",
        ),
    ),
    "fk_intact": (
        (
            "fk_intact",
            "child",
            None,
            (1, 4),
            f"2 row(s) in child have FK values not found in parent (relationship: {_FK_REL})",
        ),
    ),
    "no_orphan_children": (
        (
            "no_orphan_children",
            "child",
            None,
            (2,),
            f"1 row(s) in child have null FK values (orphaned children) for relationship {_FK_REL}",
        ),
    ),
    "leak_check": (
        (
            "leak_check",
            "t",
            "a",
            (0, 1, 2, 3, 4),
            "5 of 5 non-null cells identical to source (ratio 1.00); "
            "strategy 'hash' produced no change",
        ),
        (
            "leak_check",
            "t",
            "a",
            (0, 1, 2, 3, 4),
            "5 of 5 non-null cells identical to source (ratio 1.00 > max_identical_ratio "
            "0.02) under strategy 'hash'",
        ),
        (
            "leak_check",
            "t",
            "b",
            (0, 2),
            "2 of 5 non-null cells identical to source (ratio 0.40 > max_identical_ratio "
            "0.02) under strategy 'redact'",
        ),
        (
            "leak_check",
            "t",
            "c",
            (0, 1, 2, 3, 4),
            "5 of 5 non-null cells identical to source (ratio 1.00); "
            "strategy 'shuffle' produced no change",
        ),
    ),
    "parent_window_respected": (
        (
            "parent_window_respected",
            "child",
            "d",
            (1, 3, 4, 7),
            "4 row(s) in child.d fall outside the parent 'parent' window (start..end), fail "
            "to parse, or map to an unverifiable (null/unparseable) parent window",
        ),
    ),
    "reconciliation_holds": (
        (
            "reconciliation_holds",
            "parent",
            "total",
            (1, 2, 3),
            "3 row(s) in parent.total do not reconcile with child.amt (sum, tolerance=1e-06)",
        ),
    ),
}

CASES = build_cases()


def test_every_registered_validator_has_a_parity_case() -> None:
    assert set(CASES) == set(_REGISTRY) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_validate_matches_the_findings_captured_before_the_fold_change(name: str) -> None:
    case = CASES[name]
    report = validate(case.outputs, case.config, sources=case.sources)
    got = tuple(
        (f.validator, f.table, f.column, f.failing_row_indices, f.detail) for f in report.findings
    )
    assert got == EXPECTED[name]
    assert report.passed is False
    assert report.validators_run == (name,)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_whole_table_function_and_the_session_agree(name: str) -> None:
    case = CASES[name]
    entry = case.config["validators"][0]
    direct = _REGISTRY[name](case.outputs, entry, case.config, sources=case.sources)
    via_session = validate(case.outputs, case.config, sources=case.sources).findings
    assert direct == via_session


_WINDOW = "child.d fall outside the parent 'parent' window (start..end), fail to parse, or map"
_REPEAT_ONE = "3 of 3 non-null cells identical to source (ratio 1.00); strategy 'hash'"
_REPEAT_TWO = (
    "3 of 3 non-null cells identical to source (ratio 1.00 > max_identical_ratio 0.02) "
    "under strategy 'hash'"
)
# Also captured at 311ec1418.
EXTRA_EXPECTED: dict[str, tuple[tuple[Any, ...], ...]] = {
    "parent_window_leading_blank": (
        (
            "parent_window_respected",
            "child",
            "d",
            (0, 2),
            f"2 row(s) in {_WINDOW} to an unverifiable (null/unparseable) parent window",
        ),
    ),
    "leak_check_repeated_column": (
        ("leak_check", "t", "a", (0, 1, 2), f"{_REPEAT_ONE} produced no change"),
        ("leak_check", "t", "a", (0, 1, 2), _REPEAT_TWO),
        ("leak_check", "t", "a", (0, 1, 2), f"{_REPEAT_ONE} produced no change"),
        ("leak_check", "t", "a", (0, 1, 2), _REPEAT_TWO),
    ),
    "leak_check_skipped_columns_do_not_pair": (),
}


@pytest.mark.parametrize("name", sorted(EXTRA_EXPECTED))
def test_validate_matches_the_extra_findings_captured_before_the_fold_change(name: str) -> None:
    case = build_extra_cases()[name]
    report = validate(case.outputs, case.config, sources=case.sources)
    got = tuple(
        (f.validator, f.table, f.column, f.failing_row_indices, f.detail) for f in report.findings
    )
    assert got == EXTRA_EXPECTED[name]
