"""The `nested` target has one grammar and one evaluator (NESTED-FREEZE choke point).

`_nested_json.parse_target` reads the target text and `TargetPath.find` evaluates it. A module that
handed a target to a JSONPath library would accept forms the frozen subset refuses and select
what the library decides, and the plan check and the run could disagree. jsonpath-ng is no longer
a dependency, so the scan fails on any import of it, in any form.
"""

from __future__ import annotations

import ast

import pytest

from tests.sentry.defects import _defect_scan as scan


def jsonpath_imports(source: str) -> list[str]:
    """Every import of `jsonpath_ng` (or anything below it) in one module, as `line: what`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                f"{node.lineno}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "jsonpath_ng"
            ]
        elif (
            isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "jsonpath_ng"
        ):
            found.append(f"{node.lineno}: from {node.module} import ...")
    return sorted(found)


def test_no_module_imports_jsonpath_ng() -> None:
    offenders = {}
    for path in scan.source_files():
        found = jsonpath_imports(path.read_text(encoding="utf-8"))
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
        "from jsonpath_ng import Child, Fields\n",
        "from jsonpath_ng.parser import JsonPathParser\n",
        "import jsonpath_ng.lexer\n",
    ],
)
def test_scan_catches_each_import_form(source: str) -> None:
    assert jsonpath_imports(source) != []


def test_scan_ignores_other_modules() -> None:
    assert jsonpath_imports("import json\nfrom jsonpath_like import x\n") == []
