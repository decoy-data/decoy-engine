"""Per-scope risky-name sets for the F31 sentries, built on the shared tagger.

Both the literal sentry and the value-free registry ask the same question of a scope: which
names in it hold an exception or a data value? Keeping the answer here means one edit changes it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from tests.sentry.safe_output._tagger import SINK_RISKY, own_nodes, tainted_names

# Exception names the tagger's list leaves out; `except ... as NAME` bindings are added per scope.
EXC_NAMES = frozenset({"exception", "cause", "inner", "boom"})
# Data-value names the F31 audit's `classify_expr` tagged beyond the shared tagger's list. The
# registry rule must never admit a class the audit rule would reject, so it reads the wider set.
AUDIT_VALUE_NAMES = frozenset(
    {
        "output", "payload", "body", "literal", "token", "secret", "password", "key", "default",
        "example", "examples", "match", "span", "snippet", "x", "obj", "rows", "series", "df",
        "frame", "stderr", "stdout",
    }
)  # fmt: skip
_TYPE_ONLY_CALLS = frozenset({"type", "len", "int", "float", "bool", "id", "hex"})

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def exposes(value: ast.AST, names: frozenset[str]) -> bool:
    """Whether any name in `names` is read anywhere inside `value`.

    Wider than the tagger's `risky_in`: it follows calls such as `render(err)` and
    `getattr(exc, "args")`, which a name-and-formatting walk cannot see. Only the type of a name
    (`type(exc)`, `exc.__class__`) and a count (`len(row)`) are exempt.
    """
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _TYPE_ONLY_CALLS:
                continue
        if isinstance(node, ast.Attribute) and node.attr == "__class__":
            continue
        if isinstance(node, ast.Name) and node.id in names:
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


def _wide_taint(own: list[ast.AST], risky: frozenset[str]) -> frozenset[str]:
    """Names bound from any expression that reads a risky name, to a fixpoint."""
    tainted: set[str] = set()
    while True:
        before = len(tainted)
        for node in own:
            value: ast.AST | None = None
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                value, targets = node.value, list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                value, targets = node.value, [node.target]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                value, targets = node.iter, [node.target]
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                value, targets = node.context_expr, [node.optional_vars]
            if value is not None and exposes(value, risky | tainted):
                for target in targets:
                    tainted |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        if len(tainted) == before:
            return frozenset(tainted)


def iter_scopes(tree: ast.AST) -> Iterator[tuple[ast.AST, list[ast.AST], frozenset[str]]]:
    """Each scope with its own nodes and the names that count as risky inside it.

    The risky set is the tagger's sink names, the exception names, the scope's own `except`
    bindings and every name assigned from one of those (one pass, same bound as the tagger).
    """
    for scope in ast.walk(tree):
        if not isinstance(scope, _SCOPES):
            continue
        own = own_nodes(scope)
        bound = {n.name for n in own if isinstance(n, ast.ExceptHandler) and n.name}
        risky = SINK_RISKY | EXC_NAMES | AUDIT_VALUE_NAMES | bound
        yield scope, own, risky | tainted_names(own, risky) | _wide_taint(own, risky)
