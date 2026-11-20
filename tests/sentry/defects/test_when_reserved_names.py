"""S5 sentry: the `when:` keyword set is reserved and pinned.

`RESERVED_NAMES` is frozen by contract 3.4. Three checks keep it that way:

- AT-S5a (a guard, green on the base): every keyword terminal of the compiled grammar is a reserved
  name, none is case-insensitive, and the set of regex terminals is pinned. It turns red when a
  keyword is added to the grammar in any spelling and not to the set.
- AT-S5b: the nine words the grammar may grow into are refused as column names. Reserved names
  match exactly and case-sensitively, so `NULL` and `Between` stay columns.
- AT-S5c: an exact snapshot of the set. Adding or removing a name edits this file on purpose.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import lark
import pytest
from lark.lexer import PatternRE, PatternStr

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


# The regex terminals the grammar may have. A new one can hide a keyword, so it fails the guard
# until a person looks at it and adds the name here.
EXPECTED_REGEX_TERMINALS = frozenset(
    {"CMP", "IDENT", "NUMBER", "SQ_STRING", "DQ_STRING", "__IGNORE_0"}
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _compile(grammar_text: str) -> lark.Lark:
    return lark.Lark(grammar_text, parser="lalr", lexer="basic", maybe_placeholders=False)


def grammar_violations(grammar_text: str) -> set[str]:
    """Ways the compiled grammar can carry a keyword that RESERVED_NAMES does not cover.

    Works on the compiled terminals, so a quoted literal, a named terminal (`XOR: "xor"`) and a
    case-insensitive literal (`"xor"i`) are all seen, whichever line they sit on.
    """
    found: set[str] = set()
    for term in _compile(grammar_text).terminals:
        pattern = term.pattern
        if isinstance(pattern, PatternStr):
            if pattern.flags:
                found.add(f"{term.name}: case-insensitive literal")
            if _IDENTIFIER.fullmatch(pattern.value) and pattern.value not in RESERVED_NAMES:
                found.add(f"{term.name}: unreserved keyword {pattern.value!r}")
        elif isinstance(pattern, PatternRE):
            if term.name not in EXPECTED_REGEX_TERMINALS:
                found.add(f"{term.name}: new regex terminal")
            if pattern.flags:
                found.add(f"{term.name}: regex flags")
            if term.name == "CMP" and re.search(r"[A-Za-z]", pattern.value):
                found.add(f"{term.name}: a word inside the comparison operators")
        else:  # pragma: no cover - lark has only these two
            found.add(f"{term.name}: unknown pattern type")
    return found


def test_every_grammar_keyword_is_reserved() -> None:
    text = GRAMMAR.read_text(encoding="utf-8")
    # Not vacuous: the compiled grammar holds the real keywords and every expected regex terminal.
    terms = {t.name: t.pattern for t in _compile(text).terminals}
    keywords = {p.value for p in terms.values() if isinstance(p, PatternStr)}
    assert {"and", "or", "not", "in", "True", "False"} <= keywords
    assert set(terms) >= EXPECTED_REGEX_TERMINALS
    assert grammar_violations(text) == set()


def test_the_compiled_grammar_is_the_one_the_parser_uses() -> None:
    assert {t.name for t in _when_parser._PARSER.terminals} == {
        t.name for t in _compile(GRAMMAR.read_text(encoding="utf-8")).terminals
    }


_ANCHOR = '"True"    -> true_lit'


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        # a quoted literal in a rule
        (lambda t: t.replace(_ANCHOR, _ANCHOR + '\n       | "xor"', 1), "unreserved keyword 'xor'"),
        # a named terminal, which sits on a line the old text scan skipped
        (
            lambda t: t.replace(_ANCHOR, _ANCHOR + "\n       | XOR", 1) + '\nXOR: "xor"\n',
            "unreserved keyword 'xor'",
        ),
        # a case-insensitive literal
        (lambda t: t.replace('"not" not_expr', '"not"i not_expr', 1), "case-insensitive literal"),
        # a keyword hidden in a regex terminal
        (
            lambda t: t.replace('CMP: "==" |', 'CMP: "like" | "==" |', 1),
            "word inside the comparison",
        ),
        # a new regex terminal
        (
            lambda t: t.replace(_ANCHOR, _ANCHOR + "\n       | KW", 1) + "\nKW: /xor/\n",
            "new regex terminal",
        ),
    ],
    ids=["quoted", "named-terminal", "case-insensitive", "keyword-in-cmp", "new-regex"],
)
def test_the_guard_flags_each_spelling(edit: Callable[[str], str], expected: str) -> None:
    mutated = edit(GRAMMAR.read_text(encoding="utf-8"))
    assert mutated != GRAMMAR.read_text(encoding="utf-8")
    violations = grammar_violations(mutated)
    assert violations, "the guard missed the seeded keyword"
    if expected is not None:
        assert any(expected in v for v in violations), violations


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


@pytest.mark.parametrize("name", S5_NAMES)
def test_a_held_back_name_has_a_neutral_reason(name: str) -> None:
    with pytest.raises(ValidationError) as info:
        parse_when(f"{name} > 1")
    assert "reserved word of the when grammar" in str(info.value)
    assert "pandas eval would not" not in str(info.value)


def test_a_pandas_name_keeps_the_pandas_reason() -> None:
    with pytest.raises(ValidationError) as info:
        parse_when("sin > 1")
    assert "pandas eval would not read it as a column" in str(info.value)
