"""Nested strategy sites are discovered in one place: `plan/checks/_strategy_sites.py`.

A check or stamp that needs "every strategy a config runs" (top-level and nested children) reads
`strategy_sites` / `column_sites`. A module under `plan/` or `execution/` that calls
`nested_children` or reads a `"rules"` key on its own grows a second copy of that walk, and the
copies drift: the NER, text_mask and provider checks each once skipped a form the others covered.

Modules that already read nested children for a single-purpose job are listed in `_ALLOWED`, and
the list only shrinks. A new reader fails here; route it through the walker instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
_SCOPE = ("plan", "execution")
_WALKER = "plan/checks/_strategy_sites.py"
# key: `<module under src/decoy_engine>::<nested_children|rules>` -> why the module reads it.
_ALLOWED = {
    "plan/checks/_nested_rules.py::nested_children": "validates the rules form itself, rule by rule",
    "plan/checks/_nested_rules.py::rules": "validates the rules form itself, rule by rule",
    "execution/_column_access.py::nested_children": "column read set of a nested child at run time",
    "execution/_pipeline_multi_table.py::nested_children": "run-time child lookup on a column seed",
    "execution/_strategies/nested/_handler.py::nested_children": "the nested handler runs its children",
}


def _reads(source: str) -> set[str]:
    """The kinds of nested read in one module: `nested_children` call, `"rules"` key read.

    An import alias (`import nested_children as walk`) is resolved, so renaming the call does
    not hide it.
    """
    found: set[str] = set()
    tree = ast.parse(source)
    names = {"nested_children"} | {
        a.asname
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.name == "nested_children" and a.asname
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            if name in names:
                found.add("nested_children")
            if name == "get" and node.args and _is_rules(node.args[0]):
                found.add("rules")
        elif isinstance(node, ast.Subscript) and _is_rules(node.slice):
            found.add("rules")
        elif isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
        ):
            if _is_rules(node.left):
                found.add("rules")
    return found


def _is_rules(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "rules"


def _scan_tree() -> set[str]:
    keys: set[str] = set()
    for scope in _SCOPE:
        for path in sorted((_SRC / scope).rglob("*.py")):
            rel = path.relative_to(_SRC).as_posix()
            if rel == _WALKER:
                continue
            keys |= {f"{rel}::{kind}" for kind in _reads(path.read_text(encoding="utf-8"))}
    return keys


def test_no_module_outside_the_walker_reads_nested_children_on_its_own() -> None:
    new = sorted(_scan_tree() - set(_ALLOWED))
    assert not new, f"read nested children without the strategy-site walker: {new}"


def test_the_allowlist_only_names_reads_that_still_exist() -> None:
    stale = sorted(set(_ALLOWED) - _scan_tree())
    assert not stale, f"drop these from _ALLOWED, the read is gone: {stale}"


def test_the_walker_itself_reads_nested_children() -> None:
    assert "nested_children" in _reads((_SRC / _WALKER).read_text(encoding="utf-8"))


def test_the_scan_catches_each_read_shape() -> None:
    assert _reads("from x import nested_children\nnested_children(pc)\n") == {"nested_children"}
    assert _reads("m.nested_children(pc)\n") == {"nested_children"}
    assert _reads("pc['rules']\n") == {"rules"}
    assert _reads("pc.get('rules')\n") == {"rules"}
    assert _reads("'rules' in pc\n") == {"rules"}
    assert _reads("pc.get('target')\n") == set()
    aliased = "from x import nested_children as walk\nwalk(pc)\n"
    assert _reads(aliased) == {"nested_children"}
