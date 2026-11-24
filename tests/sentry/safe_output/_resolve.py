"""One name resolver for the F31 sentries: import aliases, plain rebindings, qualified names.

Both the literal sentry and the registry rule ask "does this expression name class X, however it
was imported or rebound?". They share this answer so they cannot disagree on an alias. A name is
resolved file-wide, ignoring scope, which errs toward finding more.
"""

from __future__ import annotations

import ast

_MAX_PASSES = 6


def aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted target, from imports and plain `X = Y` rebinding (to a fixpoint)."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found[a.asname or a.name.split(".")[0]] = (
                    a.name if a.asname else a.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            for a in node.names:
                found[a.asname or a.name] = f"{prefix}.{a.name}"
    # A rebinding like `x = x.attr` grows its target each pass, so the passes are bounded.
    for _ in range(_MAX_PASSES):
        before = dict(found)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, (ast.Name, ast.Attribute))
            ):
                target = qualified(node.value, found)
                if target:
                    found[node.targets[0].id] = target
        if found == before:
            break
    return found


def qualified(node: ast.expr, known: dict[str, str]) -> str:
    """The dotted target a Name or Attribute chain refers to, through the module's aliases."""
    if isinstance(node, ast.Name):
        return known.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        head = qualified(node.value, known)
        return f"{head}.{node.attr}" if head else ""
    return ""


def last(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1]


def names_class(node: ast.expr, known: dict[str, str], name: str) -> bool:
    """Whether `node` is the class `name` by any alias, rebinding or module qualification."""
    return last(qualified(node, known)) == name
