"""``type_family`` is defined once, in ``_value_family/``, and every reader uses that object."""

from __future__ import annotations

import ast
from pathlib import Path

import decoy_engine
import decoy_engine.anonymize as anonymize
from decoy_engine import _value_family
from decoy_engine.anonymize.hierarchies import _base, _category, _numeric, _prefix
from decoy_engine.quality.anonymity import _classes


def test_one_definition_in_the_engine() -> None:
    root = Path(decoy_engine.__file__).parent
    found = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "type_family"
            ):
                found.append(path.relative_to(root).as_posix())
    assert found == ["_value_family/__init__.py"]


def test_every_reader_uses_the_one_function() -> None:
    one = _value_family.type_family
    assert anonymize.type_family is one
    assert _classes.type_family is one
    for module in (_base, _category, _numeric, _prefix):
        assert module.type_family is one, module.__name__
