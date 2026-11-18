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


def package_of(relpath: str) -> str:
    """The dotted package a module (given as a path under ``decoy_engine/``) lives in."""
    parts = relpath.removesuffix(".py").split("/")
    parts = parts[:-1]  # an ``__init__`` is its own package, any other module its parent's
    return ".".join(["decoy_engine", *parts])


def import_bindings(tree: ast.AST, package: str | None = None) -> dict[str, str]:
    """Local name to canonical dotted target for every import in the module.

    ``package`` is the module's own package; with it, relative imports (``from ..x import y``,
    ``from . import y``) resolve to absolute names. Without it they are skipped.
    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bound[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module
            elif package is None:
                continue
            else:
                up = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*up, *([node.module] if node.module else [])])
            if not base:
                continue
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{base}.{alias.name}"
    return bound


def canonical(call_target: str, bindings: dict[str, str]) -> str:
    head, _, tail = call_target.partition(".")
    base = bindings.get(head, head)
    return f"{base}.{tail}" if tail else base
