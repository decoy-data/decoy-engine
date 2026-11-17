"""Whether a package `__init__.py` only re-exports, for the physical-seam byte-identity sentry.

A pure re-export `__init__.py` holds a module docstring, `import` and `from ... import`
statements, and `__all__` assigned a literal list or tuple of string constants. It cannot do
physical work itself; a re-export of `execution.physical` is caught by the physical-import sweep.
Anything else (a def, a class, a call, a `try`, another assignment) needs a reviewed hand entry.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _is_all_literal(node: ast.stmt) -> bool:
    if not (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__all__"
    ):
        return False
    value = node.value
    return isinstance(value, (ast.List, ast.Tuple)) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
    )


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def is_pure_reexport_init(path: Path) -> bool:
    """True for an existing `__init__.py` whose body only re-exports. False on any doubt."""
    if path.name != "__init__.py":
        return False
    try:
        body = ast.parse(path.read_text(encoding="utf-8")).body
    except (OSError, SyntaxError, ValueError):
        return False
    for i, node in enumerate(body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_all_literal(node):
            continue
        if i == 0 and _is_docstring(node):
            continue
        return False
    return True
