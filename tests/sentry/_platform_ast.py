"""AST helpers shared by the Windows platform sentries (import aliases normalized).

`import os as o`, `from os import O_DIRECTORY as D` and `from sys import platform` all resolve
to the dotted name the engine reads (recurring-defects class 5), so a renamed import is read
the same as the plain spelling. Scope shadowing is not modelled: one map per module.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
OSFLAGS = "decoy_engine.fileaccess._osflags"
OSFLAGS_REL = "decoy_engine/fileaccess/_osflags.py"
WINDOWS_NAME = f"{OSFLAGS}.WINDOWS"


def engine_trees(src: Path = SRC) -> dict[str, ast.Module]:
    """Every engine module's parsed tree, keyed by its path under `src/`."""
    root = src / "decoy_engine"
    return {
        p.relative_to(src).as_posix(): ast.parse(p.read_text(encoding="utf-8"))
        for p in sorted(root.rglob("*.py"))
    }


def import_map(tree: ast.AST) -> dict[str, str]:
    """Local name to the dotted name it stands for, over module- and function-scope imports."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                out[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def resolve(node: ast.AST, imap: dict[str, str]) -> str | None:
    """The dotted name of a `Name` or `Attribute` chain, or None when it is not an import."""
    if isinstance(node, ast.Name):
        return imap.get(node.id)
    if isinstance(node, ast.Attribute):
        base = resolve(node.value, imap)
        return None if base is None else f"{base}.{node.attr}"
    return None


def not_windows_ids(tree: ast.AST, imap: dict[str, str]) -> set[int]:
    """Ids of every node inside the body of an `if not <_osflags.WINDOWS>:` branch."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and resolve(node.test.operand, imap) == WINDOWS_NAME
        ):
            ids.update(id(sub) for stmt in node.body for sub in ast.walk(stmt))
    return ids
