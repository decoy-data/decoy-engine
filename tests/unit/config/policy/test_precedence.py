"""F16-T2: the precedence registry."""

from __future__ import annotations

import itertools

import pytest

from decoy_engine.config.policy import ColumnDecision, PrecedenceLevel, Selector
from decoy_engine.config.policy._precedence import selector_level
from tests.unit.config.policy._helpers import col, expand, raw_config, table

L1, L2, L3 = (
    PrecedenceLevel.EXACT_FIELD,
    PrecedenceLevel.EXACT_OBJECT_OR_CLASSIFICATION,
    PrecedenceLevel.SCOPED_PATTERN,
)

WORKED = [
    ({"table": "t", "column": "c"}, L1),
    ({"table": "t", "column": "c*"}, L3),
    ({"table": "t*", "column": "c"}, L3),
    ({"column": "c"}, L3),
    ({"column": "c*"}, L3),
    ({"table": "t", "tag": "x"}, L3),
    ({"table": "t", "role": "child_key"}, L3),
    ({"classification": "email", "column": "c*"}, L3),
    ({"table": "t", "column": "c", "tag": "x"}, L3),
    ({"classification": ["email", "ssn"]}, L2),
    ({"classification": "email"}, L2),
    ({"table": "t"}, L2),
    ({"table": "t", "classification": "email"}, L2),
    ({"table": "t*"}, L3),
    ({"table": "t*", "classification": "email"}, L3),
    ({"tag": "x"}, L3),
    ({"logical_type": "date"}, L3),
    ({"role": "parent_key"}, L3),
]


@pytest.mark.parametrize(("selector", "level"), WORKED)
def test_worked_cells(selector, level):
    assert selector_level(Selector.model_validate(selector)) is level


def _oracle(spec):
    keys = set(spec)
    globby = any(k in spec and any(ch in spec[k] for ch in "*?[") for k in ("table", "column"))
    if keys == {"table", "column"} and not globby:
        return L1
    if keys in ({"table"}, {"classification"}, {"table", "classification"}) and not globby:
        return L2
    return L3


def test_every_key_combination_has_its_pinned_level():
    options = {
        "table": ("t", "t*"),
        "column": ("c", "c*"),
        "classification": ("email",),
        "tag": ("x",),
        "logical_type": ("date",),
        "role": ("child_key",),
    }
    count = 0
    for subset in itertools.chain.from_iterable(
        itertools.combinations(options, n) for n in range(1, len(options) + 1)
    ):
        for values in itertools.product(*(options[k] for k in subset)):
            spec = dict(zip(subset, values, strict=True))
            assert selector_level(Selector.model_validate(spec)) is _oracle(spec), spec
            count += 1
    assert count > 100


def test_level_numbers_and_labels():
    assert [int(level) for level in PrecedenceLevel] == [1, 2, 3, 4, 5]
    assert [level.label for level in PrecedenceLevel] == [
        "exact_field",
        "exact_object_or_classification",
        "scoped_pattern",
        "classification_default",
        "global_default",
    ]


def _decide(levels):
    """Config where the field `t.c` has one differing decision per requested level."""
    own = {"strategy": "hash"} if 1 in levels else {}
    column = col("c", classification="email", **own)
    policy: dict = {"rules": []}
    if 2 in levels:
        policy["rules"].append(
            {"id": "r2", "select": {"classification": "email"}, "strategy": "redact"}
        )
    if 3 in levels:
        policy["rules"].append({"id": "r3", "select": {"table": "t*"}, "strategy": "truncate"})
    if 5 in levels:
        policy["default"] = {"strategy": "passthrough"}
    level4 = {"email": ColumnDecision(strategy="fpe")} if 4 in levels else None
    return expand(raw_config([table("t", column)]), policy, level4)[1].fields[0]


WINNER = {1: "hash", 2: "redact", 3: "truncate", 4: "fpe", 5: "passthrough"}


@pytest.mark.parametrize(("low", "high"), list(itertools.combinations(range(1, 6), 2)))
def test_field_matched_at_two_levels_takes_the_lower_number(low, high):
    field = _decide({low, high})
    assert int(field.level) == low
    assert field.decision.strategy == WINNER[low]


@pytest.mark.parametrize("only", range(1, 6))
def test_a_single_level_decides(only):
    field = _decide({only})
    assert int(field.level) == only and field.decision.strategy == WINNER[only]


def test_losing_rules_are_listed_as_overridden():
    field = _decide({2, 3, 5})
    assert field.decision.strategy == "redact"
    assert field.overridden == ("r3",)
