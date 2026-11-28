"""The scope model of the config refusal scanner: plain assignments, parameters and loop
indexes of one function at a time. Split from `_config_refusal_scan.py` to keep it under 800 lines."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field


def _name_of(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


@dataclass
class Scope:
    qualname: str
    parent: Scope | None
    assigns: dict[str, list[ast.expr]] = field(default_factory=dict)
    refusal_params: set[str] = field(default_factory=set)
    position_params: set[str] = field(default_factory=set)
    index_names: set[str] = field(default_factory=set)

    def chain(self) -> Iterable[Scope]:
        scope: Scope | None = self
        while scope is not None:
            yield scope
            scope = scope.parent

    def lookup(self, name: str) -> tuple[Scope, list[ast.expr]] | None:
        for scope in self.chain():
            if name in scope.assigns:
                return scope, scope.assigns[name]
        return None

    def is_refusal_param(self, name: str) -> bool:
        for scope in self.chain():
            if name in scope.refusal_params:
                return True
            if name in scope.assigns:
                return False
        return False

    def is_index(self, name: str) -> bool:
        return any(name in scope.index_names for scope in self.chain())


def _own_walk(scope_node: ast.AST) -> Iterable[ast.AST]:
    """Nodes of one scope: nested functions, lambdas and classes appear but are not entered."""
    pending = list(ast.iter_child_nodes(scope_node))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            pending.extend(ast.iter_child_nodes(node))


def _build_scope(node: ast.AST, qualname: str, parent: Scope | None) -> Scope:
    scope = Scope(qualname, parent)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            scope.assigns.setdefault(arg.arg, [])
            if _name_of(arg.annotation) == "Refusal":
                scope.refusal_params.add(arg.arg)
            if _name_of(arg.annotation) == "ConfigPosition":
                scope.position_params.add(arg.arg)
    for sub in _own_walk(node):
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Name):
                    scope.assigns.setdefault(target.id, []).append(sub.value)
        elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            if sub.value is not None:
                scope.assigns.setdefault(sub.target.id, []).append(sub.value)
        elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
            # An augmented assignment rebuilds the value: record it as formatted.
            scope.assigns.setdefault(sub.target.id, []).append(
                ast.BinOp(left=sub.target, op=ast.Mod(), right=sub.value)
            )
        elif isinstance(sub, ast.For):
            it = sub.iter
            target = sub.target
            if isinstance(it, ast.Call) and _name_of(it.func) in {"enumerate", "range"}:
                first = target.elts[0] if isinstance(target, ast.Tuple) else target
                if isinstance(first, ast.Name):
                    scope.index_names.add(first.id)
            for t in ast.walk(target):
                if isinstance(t, ast.Name):
                    scope.assigns.setdefault(t.id, []).append(ast.Constant(value=None))
    return scope
