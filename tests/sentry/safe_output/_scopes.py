"""Per-scope risky-name sets for the F31 sentries, built on the shared tagger.

Both the literal sentry and the value-free registry ask the same question of a scope: which
names in it hold an exception or a data value? Keeping the answer here means one edit changes it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from tests.sentry.safe_output._tagger import RISKY_NAMES, SINK_RISKY, own_nodes, tainted_names

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
# Only these calls drop a value's text: the type of it, and a count or truth value of it.
# `int(x)`, `float(x)` and `str(x)` keep it (`int(row["pin"])` prints the pin).
_TYPE_ONLY_CALLS = frozenset({"type", "len", "bool"})
# The audit tags `x.password` and `self.value` by the attribute name, whatever `x` is.
VALUE_ATTRS = frozenset(n.lower() for n in RISKY_NAMES | AUDIT_VALUE_NAMES)

_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


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
        if isinstance(node, ast.Attribute) and node.attr.lower() in VALUE_ATTRS:
            return True
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
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
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

    The risky set is the tagger's sink names, the exception and audit value names, the scope's own
    `except` bindings and every name bound from one of those (to a fixpoint). A nested function,
    class or lambda inherits the set of the scopes around it, because it can read their bindings.
    """

    def visit(
        scope: ast.AST, inherited: frozenset[str]
    ) -> Iterator[tuple[ast.AST, list[ast.AST], frozenset[str]]]:
        own = own_nodes(scope)
        bound = {n.name for n in own if isinstance(n, ast.ExceptHandler) and n.name}
        risky = SINK_RISKY | EXC_NAMES | AUDIT_VALUE_NAMES | bound | inherited
        full = risky | tainted_names(own, risky) | _wide_taint(own, risky)
        yield scope, own, full
        for child in own:
            if isinstance(child, _NESTED):
                yield from visit(child, full)

    yield from visit(tree, frozenset())
