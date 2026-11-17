"""F16-T1: the closed selector grammar."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

from decoy_engine.config import _declared_casting
from decoy_engine.config.policy import Selector
from decoy_engine.config.policy._selectors import FieldFacts, matches

INVALID = "policy_selector_invalid"


def _refused(value, code=INVALID):
    with pytest.raises(ValidationError) as caught:
        Selector.model_validate(value)
    assert [e["type"] for e in caught.value.errors()] == [code]
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize(
    "selector",
    [
        {"table": "visits"},
        {"column": "*_date"},
        {"classification": "email"},
        {"classification": ["email", "ssn"]},
        {"tag": "direct_id"},
        {"tag": ["direct_id", "quasi"]},
        {"logical_type": "date"},
        {"role": "child_key"},
        {"role": ["parent_key", "child_key"]},
        {"table": "v*", "column": "?_date", "classification": "email", "tag": "a1"},
    ],
)
def test_each_key_is_accepted(selector):
    assert Selector.model_validate(selector).present_keys() == frozenset(selector)


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"bogus": "x"},
        {"table": "a", "bogus": "x"},
        {"table": True},
        {"table": 1},
        {"column": None},
        {"table": ""},
        {"table": "x" * 129},
        {"column": ["a"]},
        {"table": "a\tb"},
        {"table": "a\x00b"},
        {"column": "x\n"},
        {"classification": []},
        {"classification": ["email", 3]},
        {"classification": ["email"] * 51},
        {"tag": "Bad Tag"},
        {"tag": "x\n"},
        {"tag": ["ok", "ok\n"]},
        {"logical_type": "float"},
        {"logical_type": "date\n"},
        {"role": "sibling"},
        {"role": "child_key\n"},
        "table",
        ["table"],
        None,
    ],
)
def test_bad_selectors_are_refused_value_free(selector):
    _refused(selector)


def test_129_char_boundary():
    assert Selector.model_validate({"table": "x" * 128}).table == "x" * 128


def test_unknown_classification_has_its_own_code():
    _refused({"classification": "not_a_detector"}, "policy_unknown_classification")
    _refused({"classification": ["email", "nope"]}, "policy_unknown_classification")


def test_refusal_text_does_not_echo_the_value():
    with pytest.raises(ValidationError) as caught:
        Selector.model_validate({"table": "CANARY_VALUE\n"})
    assert "CANARY_VALUE" not in str(caught.value)
    for err in caught.value.errors():
        assert "CANARY_VALUE" not in err["msg"] + repr(err.get("ctx"))


def test_logical_type_values_are_exactly_the_declared_vocabulary():
    for value in _declared_casting.LOGICAL_TYPES:
        assert Selector.model_validate({"logical_type": value}).logical_type == value
    _refused({"logical_type": "float"})


def _facts(**kw):
    base = {"table": "visits", "column": "visit_date"}
    return FieldFacts(**{**base, **kw})


def test_globs_use_fnmatchcase_anchored_and_case_sensitive():
    star = Selector.model_validate({"column": "*_date"})
    assert matches(star, _facts(column="visit_date"))
    assert not matches(star, _facts(column="a_date\n"))
    assert not matches(star, _facts(column="visit_DATE"))
    assert not matches(Selector.model_validate({"column": "visit_*"}), _facts(column="Visit_date"))
    assert not matches(Selector.model_validate({"table": "visits"}), _facts(table="VISITS"))
    assert matches(Selector.model_validate({"column": "v?sit_[a-z]ate"}), _facts())


def test_keys_and_and_lists_or():
    sel = Selector.model_validate({"table": "visits", "classification": ["email", "ssn"]})
    assert matches(sel, _facts(classification="ssn"))
    assert matches(sel, _facts(classification="email"))
    assert not matches(sel, _facts(classification="phone"))
    assert not matches(sel, _facts(table="other", classification="ssn"))
    assert not matches(sel, _facts())  # no classification on the field

    tags = Selector.model_validate({"tag": ["a", "b"]})
    assert matches(tags, _facts(tags=("b", "z")))
    assert not matches(tags, _facts(tags=("z",)))
    assert not matches(tags, _facts())

    both = Selector.model_validate({"tag": "a", "logical_type": ["date", "integer"]})
    assert matches(both, _facts(tags=("a",), logical_type="integer"))
    assert not matches(both, _facts(tags=("a",), logical_type="string"))
    assert not matches(both, _facts(tags=("a",)))


def test_roles_match_any_listed_role():
    sel = Selector.model_validate({"role": ["parent_key", "child_key"]})
    assert matches(sel, _facts(roles=frozenset({"child_key"})))
    assert not matches(sel, _facts())
    assert not matches(
        Selector.model_validate({"role": "parent_key"}), _facts(roles=frozenset({"child_key"}))
    )


def test_policy_package_imports_in_a_fresh_interpreter():
    done = subprocess.run(
        [sys.executable, "-I", "-c", "import decoy_engine.config.policy"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
