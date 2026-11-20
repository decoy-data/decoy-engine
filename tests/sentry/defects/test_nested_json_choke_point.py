"""One strict JSON reader and writer for nested cells (F07 choke point).

Every nested-cell read and write goes through `strict_json_read` and `strict_json_write` in
`decoy_engine._canonical`. A plain `json.loads` or `json.dumps` in the nested handler package, the
nested-path helpers or the path-observation package would read a number as a float, accept a
repeated key or skip the size and depth bounds, so none may appear there. The scan resolves
`import json as j`, `from json import loads as l` and a re-binding of either. Deliberate evasion
(`getattr(json, "loads")`, `__import__`, `exec`) is not modelled.

The packages for later slices (`_nested_json/`, `profiling/paths/`) are listed now, so the rule
holds from the day each one exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._call_resolution import local_names
from tests.sentry.defects import _defect_scan as scan

SCOPE = ("execution/_strategies/nested", "_nested_json", "profiling/paths")
_CODEC = ("loads", "load", "dumps", "dump", "JSONDecoder", "JSONEncoder")


def json_codec_sites(tree: ast.AST) -> list[int]:
    """Line numbers of every call into the stdlib `json` codec in one module."""
    modules = {
        (a.asname or a.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for a in n.names
        if a.name == "json"
    }
    names: set[str] = set()
    for target in _CODEC:
        imported = any(
            isinstance(n, ast.ImportFrom)
            and n.module == "json"
            and any(a.name == target for a in n.names)
            for n in ast.walk(tree)
        )
        if imported:
            names |= local_names(tree, target)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in names) or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
            and func.attr in _CODEC
        ):
            lines.append(node.lineno)
    return lines


def _scoped_files() -> list[Path]:
    files: list[Path] = []
    for rel in SCOPE:
        root = scan.SRC / rel
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def test_the_nested_package_is_in_scope() -> None:
    names = {p.name for p in _scoped_files()}
    assert {"_handler.py", "_leaves.py"} <= names


def test_no_stdlib_json_call_in_the_nested_cell_code() -> None:
    found = {
        p.relative_to(scan.SRC).as_posix(): json_codec_sites(ast.parse(p.read_text()))
        for p in _scoped_files()
    }
    bad = {rel: lines for rel, lines in found.items() if lines}
    assert not bad, (
        "nested cells are read with strict_json_read and written with strict_json_write "
        f"(decoy_engine._canonical), not the json module: {bad}"
    )


@pytest.mark.parametrize(
    "source",
    [
        "import json\ndef f(t):\n    return json.loads(t)\n",
        "import json as j\ndef f(t):\n    return j.dumps(t)\n",
        "from json import loads\ndef f(t):\n    return loads(t)\n",
        "from json import dumps as d\ndef f(t):\n    return d(t)\n",
        "from json import loads as l\nread = l\ndef f(t):\n    return read(t)\n",
        "import json\ndef f(t, fh):\n    return json.load(fh)\n",
        "import json\ndef f(t):\n    return json.JSONDecoder().decode(t)\n",
        "def f(t):\n    import json\n    return json.dumps(t)\n",
    ],
)
def test_the_scanner_hits_each_seeded_spelling(source: str) -> None:
    assert json_codec_sites(ast.parse(source)), source


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine._canonical import strict_json_read\ndef f(t):\n    return strict_json_read(t)\n",
        "import yaml\ndef f(t):\n    return yaml.dumps(t)\n",
        "def loads(t):\n    return t\ndef f(t):\n    return loads(t)\n",
    ],
)
def test_the_scanner_ignores_the_owner_and_foreign_calls(source: str) -> None:
    assert json_codec_sites(ast.parse(source)) == []
