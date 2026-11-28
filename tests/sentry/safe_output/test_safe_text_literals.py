"""F31 AE1a1: ``SafeText.const`` and ``SafeText.literal_template`` take a string literal only.

Python cannot prove at run time that an argument was written as a literal, so this AST walk over
``src/`` is the proof. It reads the same on every interpreter. Covered shapes, the spellings a
person writes by habit: a first argument that is not a string constant (a name, a call such as
``str(exc)``, a conditional, ``x or "lit"``, an f-string), a format passed by keyword only, a star
argument, and a builder referenced without being called. Every ``.const`` or ``.literal_template``
attribute in every ``src`` module counts, whatever the receiver: that covers an alias of the class
(``Text.const``), an instance (``label.const``) and ``functools.partial(SafeText.const, x)``, which
is an uncalled reference. Calling ``getattr(SafeText, "const")`` by string and ``eval`` are V2-LOG.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
BUILDERS = frozenset({"const", "literal_template"})


def _is_builder(node: ast.AST) -> bool:
    """A ``.const`` or ``.literal_template`` access on any receiver. The receiver is not matched
    by name: an alias, a re-export or an instance would slip past a name match."""
    return isinstance(node, ast.Attribute) and node.attr in BUILDERS


def violations(source: str, name: str = "<scratch>") -> list[str]:
    """One ``name:line: reason`` per call that does not take a string literal first."""
    tree = ast.parse(source)
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    found: list[str] = []
    for node in ast.walk(tree):
        if _is_builder(node) and id(node) not in called:
            found.append(f"{name}:{node.lineno}: builder referenced without a call")
        if not (isinstance(node, ast.Call) and _is_builder(node.func)):
            continue
        first = node.args[0] if node.args else None
        if any(isinstance(a, ast.Starred) for a in node.args) or any(
            k.arg is None for k in node.keywords
        ):
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
        "Text = SafeText\nText.const(name)",
        "pair = (1, 2)\nSafeText.const(pair[0])",
        "import functools\nfunctools.partial(SafeText.const, name)()",
        "from decoy_engine import Renamed\nRenamed.const(name)",
        'label = SafeText.const("ready")\nlabel.const(name)',
        'SafeText.const("fixed", *extra)',
    ],
)
def test_a_non_literal_spelling_is_red_in_a_scratch_module(call: str) -> None:
    source = "from decoy_engine._safe_text import SafeText as Safe, SafeText\n" + call + "\n"
    assert violations(source)


def test_a_module_without_the_class_name_is_still_scanned() -> None:
    """A re-export under another name carries no ``SafeText`` text; the walk must not skip it."""
    source = "from decoy_engine.x import Text\nText.const(row)\n"
    assert "SafeText" not in source
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
