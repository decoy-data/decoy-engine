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
# Every function the type table calls, so the `isinstance`, `==` and membership rules cover it all.
_CHECKED = (
    "_safe_value",
    "_other_value",
    "_safe_pairs",
    "_named_args",
    "_is_container",
    "_is_exact",
    "_is_record_class",
    "_default_for",
)
_BANNED_CALLS = {
    "collections.OrderedDict",
    "collections.Counter",
    "collections.defaultdict",
    "collections.UserDict",
    "copy",
    "copy.copy",
    "copy.deepcopy",
}
_BASES = {"list", "tuple", "set", "frozenset", "deque", "_KEYS_VIEW", "_VALUES_VIEW", "_ITEMS_VIEW"}
_BANNED_ATTRS = {"default_factory", "get", "keys", "values"}
_FUNCS = {
    "_safe_value": "def _safe_value(value: object, depth: int) -> object:\n",
    "_other_value": "def _other_value(value: object) -> object:\n",
    "_is_container": "def _is_container(kind: type) -> bool:\n",
}
_ITEMS_RULE = "items read outside the single dict.items(store) call in _safe_pairs"


def _is_the_pair_read(call: ast.Call) -> bool:
    """Exactly `dict.items(store)`: the unbound call, one argument, no keywords."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "items"
        and isinstance(func.value, ast.Name)
        and func.value.id == "dict"
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "store"
        and not call.keywords
    )


def _visit(
    node: ast.AST, scope: str, imap: dict[str, str], found: list[str], reads: list[int]
) -> None:
    for child in ast.iter_child_nodes(node):
        inner = child.name if isinstance(child, ast.FunctionDef | ast.ClassDef) else scope
        where = f"{inner}:{getattr(child, 'lineno', 0)}"
        if inner == "<module>":
            # The constants at module scope name types (`type({}.keys())`); only functions run.
            pass
        elif isinstance(child, ast.Call):
            target = resolve(child.func, imap)
            if target in _BANNED_CALLS:
                found.append(f"{where} builds {target}")
            if isinstance(child.func, ast.Call) and getattr(child.func.func, "id", "") == "type":
                found.append(f"{where} type(...)(...)")
            if inner in _CHECKED and getattr(child.func, "id", "") == "isinstance":
                found.append(f"{where} isinstance")
            if inner == "_safe_pairs" and _is_the_pair_read(child):
                reads.append(id(child.func))
        elif isinstance(child, ast.Attribute):
            if child.attr in _BANNED_ATTRS:
                found.append(f"{where} reads .{child.attr}")
            if child.attr == "__iter__" and not (
                isinstance(child.value, ast.Name) and child.value.id in _BASES
            ):
                found.append(f"{where} __iter__ outside the eight base names")
        elif inner in _CHECKED and isinstance(child, ast.Compare):
            for op, right in zip(child.ops, child.comparators, strict=True):
                if isinstance(op, ast.In | ast.NotIn):
                    found.append(f"{where} membership test")
                if isinstance(op, ast.Eq | ast.NotEq) and not any(
                    isinstance(s, ast.Constant) and isinstance(s.value, int)
                    for s in (child.left, right)
                ):
                    found.append(f"{where} == on a caller value")
        _visit(child, inner, imap, found, reads)


def _flaws(source: str) -> list[str]:
    tree = ast.parse(source)
    found: list[str] = []
    reads: list[int] = []
    _visit(tree, "<module>", import_map(tree), found, reads)
    # Every `.items` attribute must be the func of the one allowed call.
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "items" and id(node) not in reads:
            scope = _scope_of(tree, node)
            if scope != "<module>":
                found.append(f"{scope}:{node.lineno} {_ITEMS_RULE}")
    if len(reads) != 1:
        found.append(f"_safe_pairs has {len(reads)} pair reads, expected exactly 1")
    return found


def _scope_of(tree: ast.Module, target: ast.AST) -> str:
    """The innermost function or class that holds `target`."""
    best = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and any(
            n is target for n in ast.walk(node)
        ):
            best = node.name
    return best


def test_filter_builds_only_closed_types() -> None:
    assert _flaws(_SOURCE) == []


_HEADER = "import collections\nimport collections as c\nfrom collections import OrderedDict as OD\n"


@pytest.mark.parametrize(
    ("func", "seed", "needle"),
    [
        ("_safe_value", "    x = defaultdict(int)\n", "builds"),
        ("_safe_value", "    x = collections.OrderedDict()\n", "builds"),
        ("_safe_value", "    x = OD()\n", "builds"),
        ("_safe_value", "    x = c.defaultdict(int)\n", "builds"),
        ("_safe_value", "    x = store.get('a')\n", "reads .get"),
        ("_safe_value", "    x = value == depth\n", "== on a caller value"),
        ("_safe_value", "    x = dict.items(value)\n", _ITEMS_RULE),
        ("_other_value", "    x = isinstance(value, enum.Enum)\n", "isinstance"),
        ("_is_container", "    x = kind == dict\n", "== on a caller value"),
    ],
)
def test_filter_sentry_flags_each_seed(func: str, seed: str, needle: str) -> None:
    head = _FUNCS[func]
    assert head in _SOURCE
    flagged = _flaws(_HEADER + _SOURCE.replace(head, head + seed, 1))
    assert any(needle in f and f.startswith(f"{func}:") for f in flagged), flagged


def test_a_second_items_read_inside_safe_pairs_is_flagged() -> None:
    # Replacing the unbound call in place must fail, wherever it sits in `_safe_pairs`.
    call = "in dict.items(store):"
    assert call in _SOURCE
    flagged = _flaws(_SOURCE.replace(call, "in store.items():", 1))
    assert any(f.startswith("_safe_pairs:") and _ITEMS_RULE in f for f in flagged), flagged
