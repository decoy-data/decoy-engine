"""AST helpers for the retry sentries (F02-E1): enclosing function identity and call targets."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PKG = SRC / "decoy_engine"
RETRY_MODULE = "decoy_engine.connectors._retry"


def rel(path: Path) -> str:
    return path.relative_to(PKG).as_posix()


def walk_with_scope(tree: ast.AST) -> Iterator[tuple[ast.AST, str, tuple[ast.AST, ...]]]:
    """Yield ``(node, function qualname, ancestors)``; the qualname is ``<module>`` at top level."""

    def visit(
        node: ast.AST, scope: tuple[str, ...], parents: tuple[ast.AST, ...]
    ) -> Iterator[tuple[ast.AST, str, tuple[ast.AST, ...]]]:
        yield node, ".".join(scope) or "<module>", parents
        inner = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = (*scope, node.name)
        for child in ast.iter_child_nodes(node):
            yield from visit(child, inner, (*parents, node))

    yield from visit(tree, (), ())


def dotted(node: ast.AST) -> str | None:
    """``a.b.c`` for a Name or an Attribute chain on Names, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def import_bindings(tree: ast.AST) -> dict[str, str]:
    """Local name to canonical dotted target for every import in the module."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bound[head] = head
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def canonical(call_target: str, bindings: dict[str, str]) -> str:
    head, _, tail = call_target.partition(".")
    base = bindings.get(head, head)
    return f"{base}.{tail}" if tail else base
