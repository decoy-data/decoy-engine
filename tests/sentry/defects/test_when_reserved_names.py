"""S5 sentry: the `when:` keyword set is reserved and pinned.

`RESERVED_NAMES` is frozen by contract 3.4. Three checks keep it that way:

- AT-S5a (a guard, green on the base): every quoted keyword in `when_grammar.lark` is a reserved
  name. It turns red when a keyword is added to the grammar and not to the set.
- AT-S5b: the nine words the grammar may grow into are refused as column names. Reserved names
  match exactly and case-sensitively, so `NULL` and `Between` stay columns.
- AT-S5c: an exact snapshot of the set. Adding or removing a name edits this file on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from decoy_engine.errors import ValidationError
from decoy_engine.expressions import _when_parser
from decoy_engine.expressions._when_parser import (
    RESERVED_NAMES,
    WHEN_OUTSIDE_GRAMMAR_CODE,
    Compare,
    parse_when,
)

GRAMMAR = Path(_when_parser.__file__).with_name("when_grammar.lark")

# The words S5 reserves ahead of any grammar growth (owner Q6).
S5_NAMES = (
    "null",
    "true",
    "false",
    "between",
    "like",
    "ilike",
    "matches",
    "startswith",
    "endswith",
)

# Snapshot of the whole set. A change here is a contract change (section 3.4, after GA a Breaking one).
EXPECTED_RESERVED_NAMES = frozenset(
    {
        # numexpr function names
        "abs", "arccos", "arccosh", "arcsin", "arcsinh", "arctan", "arctan2", "arctanh",
        "ceil", "complex", "conj", "contains", "copy", "copysign", "cos", "cosh", "exp",
        "expm1", "floor", "fmod", "hypot", "imag", "isfinite", "isinf", "isnan", "log",
        "log10", "log1p", "log2", "max", "maximum", "min", "minimum", "nextafter",
        "ones_like", "prod", "real", "round", "sign", "signbit", "sin", "sinh", "sqrt",
        "sum", "tan", "tanh", "trunc", "where",
        # pandas eval default globals and frame-level names
        "Timestamp", "datetime", "True", "False", "list", "tuple", "inf", "Inf",
        "nan", "NaN", "NaT", "index", "columns",
        # Python keywords and soft keywords
        "None", "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
        "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
        "return", "try", "while", "with", "yield", "match", "case", "_", "type",
        # S5: words the grammar may grow into (SQL-style literals and string operators)
        "null", "true", "false", "between", "like", "ilike", "matches", "startswith", "endswith",
    }
)  # fmt: skip


def unreserved_keywords(grammar_text: str) -> set[str]:
    """Quoted keyword literals in grammar rules that are not reserved names."""
    found: set[str] = set()
    for line in grammar_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or re.match(r"[A-Z_]+\s*:", stripped):
            continue  # a comment or a terminal definition (its quotes are regex text)
        found.update(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', stripped))
    return found - RESERVED_NAMES


def test_every_grammar_keyword_is_reserved() -> None:
    text = GRAMMAR.read_text(encoding="utf-8")
    # Not vacuous: the scan sees the real keywords.
    seen = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', text))
    assert {"and", "or", "not", "in", "True", "False"} <= seen
    assert unreserved_keywords(text) == set()


def test_the_guard_flags_a_keyword_added_to_the_grammar_only() -> None:
    mutated = GRAMMAR.read_text(encoding="utf-8").replace(
        '"True"    -> true_lit', '"True"    -> true_lit\n       | "xor"', 1
    )
    assert "xor" in mutated
    assert unreserved_keywords(mutated) == {"xor"}


@pytest.mark.parametrize("name", S5_NAMES)
def test_an_s5_name_is_refused_as_a_column(name: str) -> None:
    for expr in (f"{name} > 1", f"{name} == 1", f"{name} in [1, 2]", f"'a' == {name}"):
        with pytest.raises(ValidationError) as info:
            parse_when(expr)
        assert info.value.code == WHEN_OUTSIDE_GRAMMAR_CODE, expr


def test_null_and_like_comparisons_are_refused_with_the_grammar_code() -> None:
    for expr in ("null > 1", "like == 1"):
        with pytest.raises(ValidationError) as info:
            parse_when(expr)
        assert info.value.code == "when_outside_closed_grammar"


# `True` and `False` are reserved by an older rule, so they are not a case-variant column.
OTHER_CASES = sorted(
    {n.upper() for n in S5_NAMES} | {n.title() for n in S5_NAMES} - {"True", "False"}
)


@pytest.mark.parametrize("name", OTHER_CASES)
def test_other_cases_stay_columns(name: str) -> None:
    expr = parse_when(f"{name} > 1")
    assert isinstance(expr, Compare) and expr.ref == name


def test_null_upper_case_reads_a_column() -> None:
    expr = parse_when("NULL > 1")
    assert isinstance(expr, Compare) and expr.ref == "NULL"


def test_reserved_names_snapshot() -> None:
    assert RESERVED_NAMES == EXPECTED_RESERVED_NAMES
    assert set(S5_NAMES) <= RESERVED_NAMES
