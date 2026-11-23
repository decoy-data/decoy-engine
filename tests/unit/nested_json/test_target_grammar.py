"""NESTED-FREEZE A2, A3, A4: the `nested` target grammar against RFC 9535 and its test suite.

`cts_subset.json` holds the JSONPath Compliance Test Suite cases for the selectors the subset
covers, every case it calls an invalid selector, and the valid cases it leaves out on purpose
(`subset: false`). The CTS `name` is the pytest id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from decoy_engine._nested_json import TargetRefusal, parse_target, to_jsonpath
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies.nested._handler import NestedStrategyHandler
from decoy_engine.execution._strategies.nested._leaves import find_matches
from tests.unit.execution._nested_strategy_support import _FakeCtx, _seed

_FIXTURE = json.loads((Path(__file__).parent / "cts_subset.json").read_text(encoding="utf-8"))
_CASES: list[dict[str, Any]] = _FIXTURE["cases"]
_INVALID = [c for c in _CASES if c.get("invalid")]
_REFUSED_VALID = [c for c in _CASES if not c.get("invalid") and not c["subset"]]
_ACCEPTED = [c for c in _CASES if not c.get("invalid") and c["subset"]]
_SELECTS = [
    c for c in _ACCEPTED if not c.get("fails_closed") and not c.get("jsonpath_ng_selects_nothing")
]
_FAILS_CLOSED = [c for c in _ACCEPTED if c.get("fails_closed")]
_NOTHING = [c for c in _ACCEPTED if c.get("jsonpath_ng_selects_nothing")]


def _ids(cases: list[dict[str, Any]]) -> list[str]:
    return [c["name"] for c in cases]


def test_fixture_covers_each_pinned_group() -> None:
    prefixes = (
        "basic, root",
        "basic, name shorthand",
        "basic, wildcard shorthand",
        "basic, multiple selectors",
        "basic, descendant segment",
        "name selector, double quotes",
        "name selector, single quotes",
        "index selector",
        "slice selector",
        "filter,",
    )
    for prefix in prefixes:
        assert any(c["name"].startswith(prefix) for c in _CASES), prefix
    assert len(_INVALID) >= 200 and len(_ACCEPTED) >= 80


@pytest.mark.parametrize("case", _INVALID, ids=_ids(_INVALID))
def test_every_cts_invalid_selector_is_refused(case: dict[str, Any]) -> None:
    assert isinstance(parse_target(case["selector"]), TargetRefusal)


@pytest.mark.parametrize("case", _REFUSED_VALID, ids=_ids(_REFUSED_VALID))
def test_valid_rfc_selectors_outside_the_subset_are_refused(case: dict[str, Any]) -> None:
    assert isinstance(parse_target(case["selector"]), TargetRefusal)


@pytest.mark.parametrize("case", _SELECTS, ids=_ids(_SELECTS))
def test_subset_selector_selects_what_the_cts_says(case: dict[str, Any]) -> None:
    expr = to_jsonpath(parse_target(case["selector"]))
    got = [m.value for m in find_matches(expr, case["document"], "data")]
    wanted = [case["result"]] if "result" in case else case["results"]
    assert got in wanted


@pytest.mark.parametrize("case", _FAILS_CLOSED, ids=_ids(_FAILS_CLOSED))
def test_subset_selector_that_jsonpath_ng_misapplies_fails_closed(case: dict[str, Any]) -> None:
    handler = NestedStrategyHandler()
    df = pd.DataFrame({"data": [json.dumps(case["document"])]})
    with pytest.raises(StrategyError) as exc:
        handler.run(
            df, "data", _seed({"target": case["selector"], "strategy": "redact"}), _FakeCtx()
        )
    assert exc.value.code == "nested_target_unwritable_container"


@pytest.mark.parametrize("case", _NOTHING, ids=_ids(_NOTHING))
def test_dot_wildcard_on_an_array_selects_nothing_in_jsonpath_ng(case: dict[str, Any]) -> None:
    """Known gap to RFC 9535: `$.*` on an array selects its items there, nothing here. The cell
    stays as it is and a column with no match at all raises `nested_target_matched_nothing`."""
    assert to_jsonpath(parse_target(case["selector"])).find(case["document"]) == []


def test_a3_quoted_star_is_not_a_member_name() -> None:
    """jsonpath-ng reads `$['*']` as a wildcard and selects every member."""
    refusal = parse_target("$['*']")
    assert isinstance(refusal, TargetRefusal) and "wildcard" in refusal.form


def test_a4_index_on_an_object_fails_closed_without_the_cell_text() -> None:
    handler = NestedStrategyHandler()
    df = pd.DataFrame({"data": ['{"a": "SSN-1"}']})
    with pytest.raises(StrategyError) as exc:
        handler.run(df, "data", _seed({"target": "$[0]", "strategy": "redact"}), _FakeCtx())
    assert exc.value.code == "nested_target_unwritable_container"
    assert "SSN-1" not in str(exc.value)


def test_index_past_the_end_selects_nothing_and_never_raises() -> None:
    handler = NestedStrategyHandler()
    df = pd.DataFrame({"data": ["[1, 2]", "[1, 2, 3]"]})
    out, _ = handler.run(df, "data", _seed({"target": "$[2]", "strategy": "redact"}), _FakeCtx())
    assert out["data"].tolist() == ["[1, 2]", '[1, 2, "REDACTED"]']


@pytest.mark.parametrize(
    "target",
    ["$", "$.a", "$.a.b", "$.*", "$[*]", "$[0]", "$[-1]", "$[1:]", "$[0:4:2]", "$.users[*].email"],
)
def test_built_ast_equals_the_jsonpath_ng_parse(target: str) -> None:
    from jsonpath_ng import parse

    built = repr(to_jsonpath(parse_target(target))).replace("_InRangeIndex", "Index")
    assert built == repr(parse(target))


@pytest.mark.parametrize(
    ("target", "form"),
    [
        ("$.a\n", "blank space"),
        ("$['a'\n]", "blank space"),
        ("$[::0]", "slice step"),
        ("$[::-1]", "slice step"),
        ("$[-0]", "invalid integer"),
        ("$[01]", "leading zero"),
        ("$[9007199254740992]", "range"),
        ("$['a\\ud800']", "surrogate"),
        ("$.", "member name missing"),
    ],
)
def test_refusal_names_the_form(target: str, form: str) -> None:
    refusal = parse_target(target)
    assert isinstance(refusal, TargetRefusal) and form in refusal.form


def test_quoted_names_decode_rfc_escapes() -> None:
    assert parse_target("$['a\\'b']").segments[0].value == "a'b"
    assert parse_target('$["a\\"b"]').segments[0].value == 'a"b'
    assert parse_target("$['\\u00e9\\ud83d\\ude00']").segments[0].value == "é\U0001f600"
    assert parse_target("$[0:4:2]").segments[0].value == (0, 4, 2)
    assert parse_target("$[9007199254740991]").segments[0].value == 2**53 - 1


_SHORT_ARRAY_ROW = json.dumps(
    {"items": [{"tags": ["a", "b", "SECRET"]}, {"tags": ["a", "b"]}, {"tags": []}]}
)


def test_short_array_in_one_branch_does_not_unmask_the_others() -> None:
    """An index past the end selects nothing for that branch only, never for the whole find."""
    handler = NestedStrategyHandler()
    df = pd.DataFrame({"data": [_SHORT_ARRAY_ROW]})
    target = "$.items[*].tags[2]"
    out, _ = handler.run(df, "data", _seed({"target": target, "strategy": "redact"}), _FakeCtx())
    items = json.loads(out["data"].iloc[0])["items"]
    assert items[0]["tags"] == ["a", "b", "REDACTED"]
    assert items[1]["tags"] == ["a", "b"] and items[2]["tags"] == []


def test_negative_index_past_the_start_selects_nothing_for_that_branch() -> None:
    handler = NestedStrategyHandler()
    row = json.dumps({"items": [{"tags": ["SECRET", "b"]}, {"tags": ["x"]}]})
    df = pd.DataFrame({"data": [row]})
    target = "$.items[*].tags[-2]"
    out, _ = handler.run(df, "data", _seed({"target": target, "strategy": "redact"}), _FakeCtx())
    items = json.loads(out["data"].iloc[0])["items"]
    assert items[0]["tags"] == ["REDACTED", "b"] and items[1]["tags"] == ["x"]
