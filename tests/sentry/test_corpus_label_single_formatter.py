"""Sentry: every corpus path or name that reaches a message goes through one formatter.

`_where(path)` renders a corpus file, `_corpus_label(name)` a corpus label; both apply the
file-access policy. An f-string in the code_set loader or its config checks that interpolates a
path-like or name-like local any other way (a bare `name`, `path`, `resolved`, `exc`, a
`.stem`, `handle.display`) is a leak waiting for the next secret in a file name. A new call
site must use the formatters, or this sentry fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "transforms"
FILES = ("_codeset_loader.py", "_codeset_config_checks.py", "code_set.py")
RISKY_NAMES = frozenset({"name", "path", "resolved", "raw", "exc", "stem", "handle", "source"})
RISKY_ATTRS = frozenset({"stem", "display", "message", "name"})
FORMATTERS = frozenset({"_corpus_label", "_where"})


def _risky(node: ast.expr) -> bool:
    """True when the interpolated expression exposes a risky local outside a formatter call."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORMATTERS:
            return False
        if isinstance(func, ast.Name) and func.id == "type":
            return False
    if isinstance(node, ast.Attribute) and node.attr == "__name__":
        return False
    # A `PlanCompileError`'s own code and message are already value-free by this sentry.
    if ast.unparse(node) in {"exc.code", "exc.message"}:
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in RISKY_NAMES:
            return True
        if isinstance(child, ast.Attribute) and child.attr in RISKY_ATTRS:
            return True
    return False


def interpolations(source: str) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FormattedValue) and _risky(node.value):
            bad.append(ast.unparse(node.value))
    return bad


@pytest.mark.parametrize("filename", FILES)
def test_no_corpus_path_or_name_is_formatted_outside_the_formatters(filename: str) -> None:
    bad = interpolations((SRC / filename).read_text(encoding="utf-8"))
    assert not bad, f"{filename}: format a corpus path/name via _where/_corpus_label: {bad}"


def test_the_sentry_catches_each_bypass() -> None:
    for seeded in (
        'f"corpus {name!r}"',
        'f"at {path}"',
        'f"at {handle.display}"',
        'f"{exc}"',
        'f"{path.stem}"',
        'f"{str(resolved)}"',
    ):
        assert interpolations(seeded), seeded
    assert not interpolations('f"{_corpus_label(name)} {_where(path)} {type(exc).__name__}"')
