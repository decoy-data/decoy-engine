"""F31 AE3 structural guard: the log filter builds only closed types and runs no caller code.

`_log_filter.py` decides every value by exact type and reads a mapping through one call,
`dict.items(store)` inside `_safe_pairs`. This guard fails on a second reader, a rebuild of a
caller mapping type, a lookup on a caller store, or an `==` on a caller value. Import aliases
resolve through the shared `import_map` and `resolve`, so `from collections import OrderedDict
as OD` counts as `collections.OrderedDict`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.safe_output import _log_filter
from tests.sentry._platform_ast import import_map, resolve

_SOURCE = Path(_log_filter.__file__).read_text(encoding="utf-8")
_CHECKED = ("_safe_value", "_safe_pairs", "_named_args")
_BANNED_CALLS = {
    "collections.OrderedDict",
    "collections.Counter",
    "collections.defaultdict",
    "collections.UserDict",
    "copy",
    "copy.copy",
    "copy.deepcopy",
}
_BASES = {"list", "tuple", "set", "frozenset"}
_BANNED_ATTRS = {"default_factory", "get", "keys", "values"}
_HEAD = "def _safe_value(value: object, depth: int) -> object:\n"


def _flaws(source: str) -> list[str]:
    tree = ast.parse(source)
    imap = import_map(tree)
    found: list[str] = []
    items_sites: list[tuple[str, int]] = []
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.ClassDef)):
        for node in ast.walk(func):
            where = f"{func.name}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call):
                target = resolve(node.func, imap)
                if target in _BANNED_CALLS:
                    found.append(f"{where} builds {target}")
                if isinstance(node.func, ast.Call) and getattr(node.func.func, "id", "") == "type":
                    found.append(f"{where} type(...)(...)")
                if func.name == "_safe_value" and getattr(node.func, "id", "") == "isinstance":
                    found.append(f"{where} isinstance")
            elif isinstance(node, ast.Attribute):
                if node.attr in _BANNED_ATTRS:
                    found.append(f"{where} reads .{node.attr}")
                if node.attr == "items":
                    items_sites.append((func.name, node.lineno))
                if node.attr == "__iter__" and not (
                    isinstance(node.value, ast.Name) and node.value.id in _BASES
                ):
                    found.append(f"{where} __iter__ outside the four base types")
            elif func.name in _CHECKED and isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators, strict=True):
                    if isinstance(op, ast.In | ast.NotIn):
                        found.append(f"{where} membership test")
                    if isinstance(op, ast.Eq | ast.NotEq) and not any(
                        isinstance(s, ast.Constant) and isinstance(s.value, int)
                        for s in (node.left, right)
                    ):
                        found.append(f"{where} == on a caller value")
    found.extend(
        f"{name}:{line} dict.items outside _safe_pairs"
        for name, line in items_sites
        if name != "_safe_pairs"
    )
    reads = sum(1 for name, _ in items_sites if name == "_safe_pairs")
    if reads != 1:
        found.append(f"_safe_pairs has {reads} items reads, expected exactly 1")
    return found


def test_filter_builds_only_closed_types() -> None:
    assert _flaws(_SOURCE) == []


@pytest.mark.parametrize(
    ("seed", "needle"),
    [
        ("    x = defaultdict(int)\n", "builds"),
        ("    x = collections.OrderedDict()\n", "builds"),
        ("    x = OD()\n", "builds"),
        ("    x = c.defaultdict(int)\n", "builds"),
        ("    x = store.get('a')\n", "reads .get"),
        ("    x = value == depth\n", "== on a caller value"),
        ("    x = dict.items(value)\n", "dict.items outside _safe_pairs"),
    ],
)
def test_filter_sentry_flags_each_seed(seed: str, needle: str) -> None:
    header = (
        "import collections\nimport collections as c\nfrom collections import OrderedDict as OD\n"
    )
    assert _HEAD in _SOURCE
    flagged = _flaws(header + _SOURCE.replace(_HEAD, _HEAD + seed, 1))
    assert any(needle in f and f.startswith("_safe_value:") for f in flagged), flagged
