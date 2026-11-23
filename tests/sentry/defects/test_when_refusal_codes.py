"""Sentry: a `when:` parser refusal maps to its boundary codes in one table.

`expressions/_when_parser.WHEN_REFUSALS` holds, per parser refusal code, the code the config
validator, the plan compile check, the runtime gate and the envelope check raise. Each
boundary reads it through `when_refusal_codes`; none compares `exc.code` itself. A refusal
code without a row would fall back to the outside-the-grammar code and hide the difference.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.expressions import _when_parser
from decoy_engine.expressions._when_parser import (
    WHEN_MASKED_REFERENCE_CODE,
    WHEN_OUTSIDE_GRAMMAR_CODE,
    WHEN_REFUSALS,
    parse_when,
)

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
BOUNDARIES = (
    "config/_tables.py",
    "plan/_checks_when.py",
    "execution/_when_gate.py",
    "expressions/_when_parser.py",
)


def _raised_codes() -> set[str]:
    """Every `code=` the parser's `ValidationError` constructions can carry, resolved by name."""
    tree = ast.parse((ROOT / "expressions/_when_parser.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ValidationError"
        ):
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Name):
                    names.add(kw.value.id)
    return {getattr(_when_parser, n) for n in names if n.startswith("WHEN_")}


def _missing_rows(table: dict[str, object]) -> set[str]:
    return _raised_codes() - set(table)


def test_every_parser_refusal_code_has_a_row() -> None:
    assert _raised_codes() == {WHEN_OUTSIDE_GRAMMAR_CODE, WHEN_MASKED_REFERENCE_CODE}
    assert _missing_rows(WHEN_REFUSALS) == set()


def test_a_missing_row_is_reported() -> None:
    """Mutation: dropping the masked row turns the row check red."""
    without = {k: v for k, v in WHEN_REFUSALS.items() if k != WHEN_MASKED_REFERENCE_CODE}
    assert _missing_rows(without) == {WHEN_MASKED_REFERENCE_CODE}


def test_rows_are_keyed_by_the_config_code_and_masked_matches_the_key() -> None:
    for key, row in WHEN_REFUSALS.items():
        assert row.config == key
        assert row.masked == (key == WHEN_MASKED_REFERENCE_CODE)


@pytest.mark.parametrize("path", BOUNDARIES)
def test_no_boundary_compares_the_refusal_code_itself(path: str) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            text = ast.unparse(node)
            assert "WHEN_MASKED_REFERENCE_CODE" not in text, (path, text)
            assert "exc.code ==" not in text, (path, text)


def test_parser_refusals_resolve_to_a_row() -> None:
    from decoy_engine.errors import ValidationError

    for expr, key in (
        ("x.y()", WHEN_OUTSIDE_GRAMMAR_CODE),
        ("masked.x > 1", WHEN_MASKED_REFERENCE_CODE),
    ):
        with pytest.raises(ValidationError) as info:
            parse_when(expr)
        assert info.value.code == key
        assert info.value.code in WHEN_REFUSALS


@pytest.mark.parametrize(
    ("expr", "key"),
    [
        ("x.y()", "when_outside_closed_grammar"),
        ("masked.x > 1", "when_masked_reference_unsupported"),
    ],
)
def test_the_runtime_gate_raises_the_row_runtime_code(expr: str, key: str) -> None:
    from decoy_engine.execution._errors import StrategyError
    from decoy_engine.execution._when_gate import _require_closed_grammar

    with pytest.raises(StrategyError) as info:
        _require_closed_grammar(expr, "redact", "c")
    assert info.value.code == key
