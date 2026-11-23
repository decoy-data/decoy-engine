"""One grammar for a `nested` target (NESTED-FREEZE choke point).

`_nested_json.parse_target` is the only reader of the target text. A module that hands a target to
a jsonpath-ng parser would accept forms the frozen subset refuses, so the plan check and the run
could disagree. The scan fails on:

- an import of `jsonpath_ng.parser`, `jsonpath_ng.lexer` or `jsonpath_ng.ext` (or below);
- an import of `parse`, `JsonPathParser` or `JsonPathLexer` from `jsonpath_ng` (aliased or not);
- an attribute `.parse`, `.JsonPathParser` or `.JsonPathLexer` on a name bound to `jsonpath_ng`.
"""

from __future__ import annotations

import ast

import pytest

from tests.sentry.defects import _defect_scan as scan

_BARRED_MODULES = ("jsonpath_ng.parser", "jsonpath_ng.lexer", "jsonpath_ng.ext")
_BARRED_NAMES = frozenset({"parse", "JsonPathParser", "JsonPathLexer"})


def parser_uses(source: str) -> list[str]:
    """Every parser use in one module's source, as `line: what`."""
    tree = ast.parse(source)
    bound: set[str] = set()
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "jsonpath_ng":
                    bound.add(alias.asname or "jsonpath_ng")
                if alias.name.startswith(_BARRED_MODULES):
                    found.append(f"{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(_BARRED_MODULES):
                found.append(f"{node.lineno}: from {node.module}")
            elif node.module == "jsonpath_ng":
                for alias in node.names:
                    if alias.name in _BARRED_NAMES:
                        found.append(f"{node.lineno}: from jsonpath_ng import {alias.name}")
                    if alias.name in {"parser", "lexer", "ext"}:
                        found.append(f"{node.lineno}: from jsonpath_ng import {alias.name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _BARRED_NAMES:
            chain = scan.attr_chain(node)
            if chain and chain[0] in bound:
                found.append(f"{node.lineno}: {'.'.join(chain)}")
    return sorted(found)


def test_no_module_parses_a_target_with_jsonpath_ng() -> None:
    offenders = {}
    for path in scan.source_files():
        found = parser_uses(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.relative_to(scan.SRC).as_posix()] = found
    assert offenders == {}


@pytest.mark.parametrize(
    "source",
    [
        "import jsonpath_ng\nexpr = jsonpath_ng.parse(target_path)\n",
        "import jsonpath_ng as jp\nexpr = jp.parse(target_path)\n",
        "from jsonpath_ng.ext import parse as p\n",
        "from jsonpath_ng import parse\n",
        "from jsonpath_ng import parse as p\n",
        "from jsonpath_ng.parser import JsonPathParser\n",
        "import jsonpath_ng.lexer\n",
        "import jsonpath_ng as jp\nx = jp.JsonPathParser()\n",
    ],
)
def test_scan_catches_each_bypass(source: str) -> None:
    assert parser_uses(source) != []


def test_scan_allows_ast_classes_and_isinstance_checks() -> None:
    source = "import jsonpath_ng\nfrom jsonpath_ng import Child, Fields\nok = isinstance(x, jsonpath_ng.Index)\n"
    assert parser_uses(source) == []
