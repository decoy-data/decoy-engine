"""F31 AE1a1: ``SafeText.const`` and ``SafeText.literal_template`` take a string literal only.

Python cannot prove at run time that an argument was written as a literal, so this AST walk over
``src/`` is the proof. It reads the same on every interpreter. Covered shapes, the spellings a
person writes by habit: a first argument that is not a string constant (a name, a call such as
``str(exc)``, a conditional, ``x or "lit"``, an f-string), a format passed by keyword only, a star
argument, an alias of the class, and a builder referenced without being called. Deliberate evasion
(``getattr``, ``partial``, ``eval``) is V2-LOG.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
BUILDERS = frozenset({"const", "literal_template"})
CLASS = "SafeText"


def _class_names(tree: ast.AST) -> set[str]:
    """``SafeText`` plus every alias it is imported under."""
    names = {CLASS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == CLASS and a.asname}
    return names


def _is_builder(node: ast.AST, classes: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in BUILDERS
        and (
            (isinstance(node.value, ast.Name) and node.value.id in classes)
            or (isinstance(node.value, ast.Attribute) and node.value.attr == CLASS)
        )
    )


def violations(source: str, name: str = "<scratch>") -> list[str]:
    """One ``name:line: reason`` per call that does not take a string literal first."""
    tree = ast.parse(source)
    classes = _class_names(tree)
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    found: list[str] = []
    for node in ast.walk(tree):
        if _is_builder(node, classes) and id(node) not in called:
            found.append(f"{name}:{node.lineno}: builder referenced without a call")
        if not (isinstance(node, ast.Call) and _is_builder(node.func, classes)):
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Starred) or any(k.arg is None for k in node.keywords):
            found.append(f"{name}:{node.lineno}: star argument")
        elif first is None:
            found.append(f"{name}:{node.lineno}: text passed by keyword or missing")
        elif not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            found.append(f"{name}:{node.lineno}: first argument is not a string literal")
    return found


def test_every_call_under_src_takes_a_string_literal() -> None:
    bad: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        bad += violations(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
    assert bad == []


@pytest.mark.parametrize(
    "call",
    [
        "SafeText.const(str(exc))",
        "SafeText.const(name)",
        'SafeText.const(name if flag else "lit")',
        'SafeText.const(name or "lit")',
        'SafeText.const(f"value {name}")',
        'SafeText.const(text="lit")',
        'SafeText.literal_template(fmt="lit {x}")',
        "SafeText.literal_template(name, names={})",
        'SafeText.const(*["lit"])',
        'SafeText.const(**{"text": "lit"})',
        "decoy_engine._safe_text.SafeText.const(str(exc))",
        "Safe.const(name)",
        "make = SafeText.const",
    ],
)
def test_a_non_literal_spelling_is_red_in_a_scratch_module(call: str) -> None:
    source = "from decoy_engine._safe_text import SafeText as Safe, SafeText\n" + call + "\n"
    assert violations(source)


@pytest.mark.parametrize(
    "call",
    [
        'SafeText.const("plain text")',
        'SafeText.const("one " "two")',
        'SafeText.literal_template("at {name} done", names={"name": value})',
        'SafeText.literal_template("plain", names=None, paths=None)',
    ],
)
def test_a_plain_literal_is_green_in_a_scratch_module(call: str) -> None:
    assert violations("from decoy_engine._safe_text import SafeText\n" + call + "\n") == []
