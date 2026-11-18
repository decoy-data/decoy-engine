"""Class 3 sentry: `NAME_HINT_GATED_DETECTORS` equals the detectors that gate on a name hint.

Residual-PII grading trusts the set: a detector missing from it is graded as if its regex alone
proved a leak, and a stale entry hides a real pattern detector behind a name hint. The scan reads
`detectors.py` with `ast`: every `detect_*` function whose first statement after the docstring is
`if not _hits_name_hint("<id>", ...): return None` is gated, and the id it passes must be the id
it passes to `_evaluate`, because that id is the one that appears in the column facts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.detection import NAME_HINT_GATED_DETECTORS

DETECTORS = (
    Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "detection" / "detectors.py"
)


def _str_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _first_statement(fn: ast.FunctionDef) -> ast.stmt | None:
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body[0] if body else None


def _gate_id(fn: ast.FunctionDef) -> str | None:
    """The id in `if not _hits_name_hint("<id>", ...): return None` as the first statement."""
    stmt = _first_statement(fn)
    if not (
        isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.UnaryOp)
        and isinstance(stmt.test.op, ast.Not)
        and isinstance(stmt.test.operand, ast.Call)
        and isinstance(stmt.test.operand.func, ast.Name)
        and stmt.test.operand.func.id == "_hits_name_hint"
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Return)
        and isinstance(stmt.body[0].value, ast.Constant)
        and stmt.body[0].value.value is None
    ):
        return None
    return _str_arg(stmt.test.operand)


def _evaluate_ids(fn: ast.FunctionDef) -> set[str]:
    return {
        arg
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_evaluate"
        and (arg := _str_arg(node)) is not None
    }


def gated_detectors(source: str) -> dict[str, tuple[str, set[str]]]:
    """`{function name: (gate id, ids passed to _evaluate)}` for every gated `detect_*`."""
    out: dict[str, tuple[str, set[str]]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("detect_"):
            gate = _gate_id(node)
            if gate is not None:
                out[node.name] = (gate, _evaluate_ids(node))
    return out


def registry_findings(source: str, registry: frozenset[str]) -> list[str]:
    gated = gated_detectors(source)
    found = {gate for gate, _ in gated.values()}
    problems = [f"gated but not in the set: {i}" for i in sorted(found - registry)]
    problems += [f"in the set but not gated: {i}" for i in sorted(registry - found)]
    return problems


def id_findings(source: str) -> list[str]:
    return [
        f"{name}: gate id {gate!r} but _evaluate ids {sorted(ids)}"
        for name, (gate, ids) in sorted(gated_detectors(source).items())
        if ids != {gate}
    ]


def test_registry_matches_gated_detectors() -> None:
    assert registry_findings(DETECTORS.read_text(), NAME_HINT_GATED_DETECTORS) == []


def test_gate_id_equals_evaluate_id() -> None:
    assert id_findings(DETECTORS.read_text()) == []


def test_the_scan_sees_the_gated_detectors() -> None:
    assert len(gated_detectors(DETECTORS.read_text())) >= 10


_GATED = '''
def detect_x(series, col_name):
    """Doc."""
    if not _hits_name_hint("x", col_name):
        return None
    return _evaluate("x", series, RE)
'''


def test_seeded_gated_detector_missing_from_set_is_found() -> None:
    assert registry_findings(_GATED, frozenset()) == ["gated but not in the set: x"]


def test_seeded_stale_set_entry_is_found() -> None:
    ungated = "def detect_x(series, col_name):\n    return _evaluate('x', series, RE)\n"
    assert registry_findings(ungated, frozenset({"x"})) == ["in the set but not gated: x"]


def test_seeded_mismatched_ids_are_found() -> None:
    bad = _GATED.replace('_evaluate("x"', '_evaluate("y"')
    assert id_findings(bad) == ["detect_x: gate id 'x' but _evaluate ids ['y']"]


def test_seeded_clean_detector_passes() -> None:
    assert registry_findings(_GATED, frozenset({"x"})) == []
    assert id_findings(_GATED) == []


@pytest.mark.parametrize("gate", ["not _hits_name_hint('x', c)", "_hits_name_hint('x', c)"])
def test_only_the_negated_gate_with_return_none_counts(gate: str) -> None:
    text = (
        f"def detect_x(s, c):\n    if {gate}:\n        return 1\n    return _evaluate('x', s, R)\n"
    )
    assert gated_detectors(text) == {}
