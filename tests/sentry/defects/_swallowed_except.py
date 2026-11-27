"""The one predicate for the `swallowed-broad-except` sentry (standard library `ast` only).

A site is a broad handler that keeps going: a bare `except:`, `except Exception`, `except
BaseException` (a name or an attribute such as `builtins.Exception`) or a tuple holding one of
them, whose own body has no `raise`; or a `with suppress(...)` / `with contextlib.suppress(...)`
whose arguments include `Exception` or `BaseException`.

Not a site: a handler with any `raise` in its own body (a conditional raise is accepted), a narrow
handler, and a handler that saves the error and re-raises it after the whole `try`:

1. the handler binds `as exc`;
2. its own body assigns an expression that holds `exc` to a local name;
3. the same scope has a `raise` naming that local, starting after the `try`'s `end_lineno`.

A `raise` inside a nested `def`, `lambda` or `class` never counts, in the handler or in the scope.
Pattern: ruff `BLE001` (blind except) minus its `exc_info` exemption, because a logged and
continued failure is the class this sentry exists for. This file is vendored byte for byte into
the CLI repo, so it imports nothing from either project.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass

_BROAD = frozenset({"Exception", "BaseException"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
# `except*` exists from Python 3.11; on older interpreters `Try` is the only try node.
_TRY = (ast.Try, getattr(ast, "TryStar", ast.Try))


@dataclass(frozen=True)
class Site:
    lineno: int
    kind: str  # "except" or "suppress"


def _is_broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in _BROAD
    if isinstance(node, ast.Attribute):
        return node.attr in _BROAD
    if isinstance(node, ast.Tuple):
        return any(_is_broad(elt) for elt in node.elts)
    return False


def _walk_scope(nodes: list[ast.stmt] | list[ast.expr]) -> Iterator[ast.AST]:
    """Every node under `nodes` without entering a nested def, lambda or class."""
    stack: list[ast.AST] = list(reversed(nodes))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _SCOPES):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _names_in(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _saved_locals(handler: ast.ExceptHandler) -> set[str]:
    """Local names the handler's own body assigns an expression holding the bound exception to."""
    if handler.name is None:
        return set()
    saved: set[str] = set()
    for node in _walk_scope(handler.body):
        if isinstance(node, ast.Assign) and handler.name in _names_in(node.value):
            saved |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and handler.name in _names_in(node.value)
        ):
            saved.add(node.target.id)
    return saved


def _reraised_after(scope_body: list[ast.stmt], try_end: int, saved: set[str]) -> bool:
    for node in _walk_scope(scope_body):
        if isinstance(node, ast.Raise) and node.lineno > try_end:
            if saved & (_names_in(node.exc) | _names_in(node.cause)):
                return True
    return False


def _suppresses_broad(item: ast.withitem) -> bool:
    call = item.context_expr
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name == "suppress" and any(_is_broad(arg) for arg in call.args)


def _sites_in_scope(body: list[ast.stmt], found: list[Site]) -> None:
    for node in _walk_scope(body):
        if isinstance(node, _TRY):
            for handler in node.handlers:
                if not _is_broad(handler.type):
                    continue
                if any(isinstance(n, ast.Raise) for n in _walk_scope(handler.body)):
                    continue
                saved = _saved_locals(handler)
                end = node.end_lineno or node.lineno
                if saved and _reraised_after(body, end, saved):
                    continue
                found.append(Site(handler.lineno, "except"))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            found.extend(Site(node.lineno, "suppress") for i in node.items if _suppresses_broad(i))


def swallowed_sites(tree: ast.Module) -> list[Site]:
    """Every swallowing broad handler in `tree`, each scope judged on its own raises."""
    found: list[Site] = []
    _sites_in_scope(tree.body, found)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _sites_in_scope(node.body, found)
    return sorted(found, key=lambda s: (s.lineno, s.kind))
