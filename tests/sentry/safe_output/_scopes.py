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

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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
        risky = SINK_RISKY | EXC_NAMES | bound
        yield scope, own, risky | tainted_names(own, risky)
