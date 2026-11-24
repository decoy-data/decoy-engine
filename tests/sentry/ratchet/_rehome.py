"""Re-homing of a census key whose old site is proven gone (AST proof), split out of ``_ratchet.py``.

``tests/sentry/_ratchet.py`` loads this file by path (``_helper("_rehome")``), the same way it
loads ``_integrity.py``.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _find_defs(node: ast.AST, part: str) -> list[ast.AST]:
    """Every def or class named ``part`` under ``node``, looking inside if/try/with/for blocks."""
    found: list[ast.AST] = []
    todo = list(ast.iter_child_nodes(node))
    while todo:
        child = todo.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if child.name == part:
                found.append(child)
            continue
        todo.extend(ast.iter_child_nodes(child))
    return found


def _qualname_nodes(tree: ast.AST, qualname: str) -> list[ast.AST]:
    nodes: list[ast.AST] = [tree]
    for part in qualname.split("."):
        nodes = [d for n in nodes for d in _find_defs(n, part)]
    return nodes


def _mentions(n: ast.AST, name: str) -> bool:
    """True when ``n`` binds or reads ``name``: a closure that only reads it still holds the site."""
    if isinstance(n, ast.arg):
        return n.arg == name
    if isinstance(n, ast.Name):
        return n.id == name
    if isinstance(n, ast.Attribute):
        return n.attr == name
    if isinstance(n, ast.alias):
        return (n.asname or n.name.partition(".")[0]) == name
    if isinstance(n, ast.MatchMapping):
        return n.rest == name
    # def, class, except-as, match capture, type-param and any later form that names itself.
    return getattr(n, "name", None) == name


def _site_parts(key: str) -> tuple[str, str, str] | None:
    """Split ``<file>::<qualname>::<name>`` with an optional all-digit ``::<ordinal>`` suffix."""
    parts = key.split("::")
    if len(parts) == 4 and parts[3].isdigit():
        parts = parts[:3]
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def site_gone(root: Path, key: str, tree: Any) -> bool:
    """True when ``<file>.py::<qualname>::<name>`` is proven absent from the source tree.

    ``<file>`` is relative to ``src/``. Proof by AST: the qualified def or class is missing, or it
    is present but neither binds nor reads ``name`` (``_mentions``) in any same-named def. A
    qualname part that is not an identifier (``<lambda>``) is never proven. A missing file proves it only
    when the file existed at the base. A key of another shape, an unresolvable path, or a
    file that never existed is "not proven" and returns false.
    """
    parts = _site_parts(key)
    if parts is None or not parts[0].endswith(".py") or not parts[2].isidentifier():
        return False
    file, qualname, name = parts
    if not all(q.isidentifier() for q in qualname.split(".")):
        return False
    path = root / "src" / file
    if not path.is_file():
        return tree.has_file(f"src/{file}")
    nodes = _qualname_nodes(ast.parse(path.read_text(encoding="utf-8")), qualname)
    return not any(_mentions(n, name) for node in nodes for n in ast.walk(node))


def rehomes(
    root: Path,
    tree: Any,
    grown: frozenset[str],
    head_entries: dict[str, object],
    lost: dict[str, object],
    max_of: Callable[[object], int | None],
) -> tuple[frozenset[str], list[str]]:
    """Split ``grown`` into declared 1:1 moves of ``lost`` keys, and the rest.

    A grown key is a move only when its entry names the old key in ``moved_from`` and that old
    key was lost from this baseline, is proven gone (``site_gone``), carries no numeric ``max``,
    ends in the same bound name, and is named by no other entry. Anything else stays growth.
    """
    claims: dict[str, list[str]] = {}
    for key in grown:
        entry = head_entries.get(key)
        old = entry.get("moved_from") if isinstance(entry, dict) else None
        if isinstance(old, str):
            claims.setdefault(old, []).append(key)
    remaining = set(grown)
    report: list[str] = []
    for old, keys in sorted(claims.items()):
        old_parts, new_parts = _site_parts(old), _site_parts(keys[0])
        same_name = old_parts is not None and new_parts is not None and old_parts[2] == new_parts[2]
        if len(keys) != 1 or not same_name or old not in lost or max_of(lost[old]) is not None:
            continue
        if site_gone(root, old, tree):
            remaining.discard(keys[0])
            report.append(f"re-homed {old} -> {keys[0]} (declared in moved_from; old site gone)")
    return frozenset(remaining), report
