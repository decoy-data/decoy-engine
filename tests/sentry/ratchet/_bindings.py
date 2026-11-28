"""The one list of Python forms that bind a name, shared by every guard that counts rebinds.

``bound_names(node)`` names what ``node`` itself binds in the scope that holds it. Callers keep
their own scope walk (``_limit_constants`` for module constants, ``_reason_when_rows`` for one
function), so a form added here reaches both. Stdlib only.
"""

from __future__ import annotations

import ast


def bound_names(node: ast.AST) -> tuple[str, ...]:
    """Names bound by ``node`` itself: a stored or deleted name, a ``def``, ``class``, import
    alias, ``except ... as`` target, match capture or ``**rest``, ``global``/``nonlocal``
    declaration, or a parameter."""
    if isinstance(node, ast.Name):
        return (node.id,) if isinstance(node.ctx, (ast.Store, ast.Del)) else ()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.alias):
        return ((node.asname or node.name.split(".")[0]),)
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return (node.name,) if node.name else ()
    if isinstance(node, ast.MatchMapping):
        return (node.rest,) if node.rest else ()
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return tuple(node.names)
    if isinstance(node, ast.arg):
        return (node.arg,)
    return ()
