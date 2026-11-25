"""WHEN-READS-SOURCE S1: the `when:` reference prefixes and backtick quoting.

Plan: docs/plans/2026-11-22-when-reads-source.md, section 9 (T-S1 to T-S6). A reference is a bare
name, `source.<name>` (the same thing), `masked.<name>` (refused in V1) or a backtick-quoted name.
"""

from __future__ import annotations

import re
import warnings
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest
from pydantic import ValidationError as PydanticValidationError

from decoy_engine.config import PipelineConfig
from decoy_engine.errors import ValidationError
from decoy_engine.execution._unified_slice_when import compute_when_masks
from decoy_engine.execution._when_gate import _eval_predicate
from decoy_engine.execution.native._when_mask import WhenSpec, when_mask
from decoy_engine.expressions._when_parser import (
    WHEN_MASKED_REFERENCE_CODE,
    WHEN_OUTSIDE_GRAMMAR_CODE,
    Compare,
    WhenRead,
    parse_when,
    validate_envelope_when,
    when_column_refs,
    when_literals_by_ref,
)
from decoy_engine.plan import PlanCompileError
from decoy_engine.plan._checks_when import check_when_grammar
from tests.unit.test_c8_i_when_grammar import ACCEPTED

SHAPES = [
    "status == 'a'",
    "'a' == status",
    "status != 'a' and n > 3",
    "not (status in ['a', 'b'] or n <= 2)",
    "status not in ['a']",
    "n == 4 or n == 5",
]


def _source_form(expr: str) -> str:
    return re.sub(r"\b(status|n)\b(?!')", r"source.\1", expr)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"status": ["a", "b", "c", None, "a"], "n": [1, 4, 5, None, 3]},
    )


@pytest.mark.parametrize("expr", SHAPES)
def test_ts1_a_bare_name_equals_the_source_prefix(expr: str) -> None:
    prefixed = _source_form(expr)
    assert prefixed != expr
    assert parse_when(expr) == parse_when(prefixed)
    assert when_column_refs(parse_when(prefixed)) == when_column_refs(parse_when(expr))
    assert all(r.phase == "source" for r in when_column_refs(parse_when(prefixed)))
    frame = _frame()
    assert _eval_predicate(frame, prefixed, "redact").tolist() == (
        _eval_predicate(frame, expr, "redact").tolist()
    )


def test_ts1_reads_are_typed_sorted_and_unique() -> None:
    reads = when_column_refs(parse_when("b == 1 or source.a == 2 or `a` != 3"))
    assert reads == (WhenRead("a", "source"), WhenRead("b", "source"))


@pytest.mark.parametrize(
    "expr",
    ["masked.status == 'a'", "masked.`a.b` == 'x'", "1 == masked.n", "masked.n in [1]"],
)
def test_ts2_a_masked_reference_is_refused_with_its_own_code(expr: str) -> None:
    with pytest.raises(ValidationError) as info:
        parse_when(expr)
    assert info.value.code == WHEN_MASKED_REFERENCE_CODE == "when_masked_reference_unsupported"
    assert "planned for 1.x" in info.value.raw_message


def test_ts2_the_masked_refusal_reaches_config_plan_and_envelope() -> None:
    raw = {
        "tables": [
            {
                "name": "t",
                "source": {"type": "csv", "path": "x.csv"},
                "columns": [{"name": "c", "strategy": "redact", "when": "masked.s == 'a'"}],
            }
        ]
    }
    with pytest.raises(PydanticValidationError) as info:
        PipelineConfig.model_validate({"tables": raw["tables"]})
    errors = [e for e in info.value.errors() if e["loc"][-1] == "when"]
    assert [e["type"] for e in errors] == ["when_masked_reference_unsupported"]
    assert errors[0]["loc"] == ("tables", 0, "columns", 0, "when")

    with pytest.raises(PlanCompileError) as plan_info:
        check_when_grammar(raw)
    assert plan_info.value.code == "when_masked_reference_unsupported"
    assert plan_info.value.path == "tables.t.columns.c.when"

    envelope = SimpleNamespace(
        per_table=[
            ("t", SimpleNamespace(per_column=[("c", SimpleNamespace(when="masked.s == 1"))]))
        ]
    )
    with pytest.raises(ValidationError) as env_info:
        validate_envelope_when(envelope)
    assert env_info.value.code == WHEN_MASKED_REFERENCE_CODE
    assert env_info.value.path == "tables.t.columns.c.when"


def _dotted_frame() -> pd.DataFrame:
    return pd.DataFrame({"a.b": ["x", "y", "x", None], "k": [1, 2, 3, 4]})


@pytest.mark.parametrize("expr", ["`a.b` == 'x'", "source.`a.b` == 'x'", "'x' == `a.b`"])
def test_ts3_a_quoted_dotted_name_selects_on_the_oracle(expr: str) -> None:
    assert _eval_predicate(_dotted_frame(), expr, "redact").tolist() == [True, False, True, False]


@pytest.mark.parametrize("expr", ["`a.b` == 'x'", "source.`a.b` == 'x'"])
def test_ts3_a_quoted_dotted_name_selects_on_the_chunked_native_mask(expr: str) -> None:
    chunk = pa.table({"a.b": ["x", "y", "x", None], "k": [1, 2, 3, 4]})
    spec = WhenSpec("target", "redact", expr, when_column_refs(parse_when(expr)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mask = when_mask(spec, chunk, set())
    assert mask.to_pylist() == [True, False, True, False]


@pytest.mark.parametrize("expr", ["`a.b` == 'x'", "source.`a.b` == 'x'"])
def test_ts3_a_quoted_dotted_name_selects_on_the_unified_slice(expr: str) -> None:
    node = SimpleNamespace(
        node_id="n0",
        strategy="redact",
        columns=("target",),
        execution=SimpleNamespace(when_expression=expr),
    )
    masks = compute_when_masks(_dotted_frame(), [node])
    assert masks.selected["n0"].tolist() == [True, False, True, False]


@pytest.mark.parametrize(
    "expr",
    ["a.b == 'x'", "a.`b` == 'x'", "x.y.z == 1", "other.s == 1"],
)
def test_ts3_an_unquoted_dotted_name_is_refused_with_the_grammar_code(expr: str) -> None:
    with pytest.raises(ValidationError) as info:
        parse_when(expr)
    assert info.value.code == WHEN_OUTSIDE_GRAMMAR_CODE


@pytest.mark.parametrize(
    "expr",
    ["`a`b` == 1", "`` == 1", "`a\\b` == 1", "`a\tb` == 1", "`a\x00b` == 1", "`a\u2028b` == 1"],
    ids=["backtick", "empty", "backslash", "tab", "nul", "line-sep"],
)
def test_ts3_a_quoted_name_holds_no_backtick_backslash_or_control_character(expr: str) -> None:
    with pytest.raises(ValidationError) as info:
        parse_when(expr)
    assert info.value.code == WHEN_OUTSIDE_GRAMMAR_CODE


def test_ts3_a_quoted_name_may_hold_other_characters() -> None:
    ast = parse_when("`first name (x)` == 'a'")
    assert isinstance(ast, Compare) and ast.ref == "first name (x)"
    frame = pd.DataFrame({"first name (x)": ["a", "b"]})
    assert _eval_predicate(frame, "`first name (x)` == 'a'", "redact").tolist() == [True, False]


def test_ts4_source_is_still_a_column_name_when_bare() -> None:
    ast = parse_when("source == 'web'")
    assert isinstance(ast, Compare) and (ast.ref, ast.phase) == ("source", "source")
    frame = pd.DataFrame({"source": ["web", "app"]})
    assert _eval_predicate(frame, "source == 'web'", "redact").tolist() == [True, False]
    assert _eval_predicate(frame, "source.source == 'web'", "redact").tolist() == [True, False]


def test_ts5_the_refusals_hold_no_literal_from_the_predicate() -> None:
    secret = "VERY-SECRET-123-45-6789"
    for expr in (
        f"masked.s == '{secret}'",
        f"a.b == '{secret}'",
        f"`a`b` == '{secret}'",
        f"x.y.z == '{secret}'",
    ):
        with pytest.raises(ValidationError) as info:
            parse_when(expr)
        assert secret not in str(info.value), expr
        assert info.value.__context__ is None and info.value.__cause__ is None


@pytest.mark.parametrize("expr", ACCEPTED)
def test_ts6_the_aliased_rendering_equals_the_raw_text_evaluation(expr: str) -> None:
    """Every predicate the existing grammar tests accept gives the mask pandas gives the raw text."""
    ast = parse_when(expr)
    reads = [r.column for r in when_column_refs(ast)]
    literals = when_literals_by_ref(ast)
    data: dict[str, Any] = {}
    for name in reads:
        numeric = any(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in literals[name]
        )
        data[name] = (
            pd.Series([1, 5, None, 10, 0], dtype="float64")
            if numeric
            else pd.Series(["a", "b", None, "s1", ""], dtype=object)
        )
    frame = pd.DataFrame(data)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = frame.eval(expr, engine="python", local_dict={}, global_dict={})
    except Exception:  # a type mix pandas itself refuses is not the comparison
        pytest.skip("pandas refuses the raw text on this frame")
    mask = _eval_predicate(frame, expr, "redact")
    assert mask.tolist() == pd.Series(raw).fillna(False).astype(bool).tolist()
