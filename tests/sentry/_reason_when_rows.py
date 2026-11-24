"""The one site-level exception to the reason-code guard: forwarding a `WHEN_REFUSALS` row.

`expressions/_when_parser.WHEN_REFUSALS` maps each `when:` parser refusal to the codes the
config, plan, runtime and envelope boundaries raise, and every row value is a `reasons.*`
symbol. In exactly the functions below, `code=<name>.config|plan|runtime` is accepted when the
name is bound once, as `<name> = when_refusal_codes(...)`, by a plain top-level statement of
that function that comes before the site. Any other binding of the name in the function
(rebinding, augmented, tuple-unpack, walrus, loop or with or except target, global, nonlocal,
import, nested def or class of that name, a parameter) makes the site a violation, and so does
a binding that exists only inside a nested function. Pinned by test_reason_registry_when_rows.py.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from tests.sentry.ratchet._bindings import bound_names

WHEN_ROW_FUNCTIONS = frozenset(
    {
        ("execution/_when_gate.py", "_closed_grammar_error"),
        ("expressions/_when_parser.py", "_envelope_refusal"),
        ("plan/_checks_when.py", "_when_refusal_error"),
    }
)
ROW_ATTRS = frozenset({"config", "plan", "runtime"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_nodes(fn: ast.FunctionDef) -> Iterator[ast.AST]:
    """Every node of the function's own body; nested def, lambda and class are yielded, not entered."""
    stack: list[ast.AST] = list(reversed(fn.body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _SCOPES):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _binding_count(fn: ast.FunctionDef, name: str) -> int:
    args = fn.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    nodes = [*(a for a in params if a is not None), *_own_nodes(fn)]
    return sum(name in bound_names(node) for node in nodes)


def _is_row_assignment(stmt: ast.stmt, name: str) -> bool:
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id == name
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "when_refusal_codes"
    )


def _reaching_row_binding(path: Path, function: str, name: str, line: int) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == function):
            continue
        if not fn.lineno <= line <= (fn.end_lineno or line):
            continue
        top = [s for s in fn.body if _is_row_assignment(s, name) and s.lineno < line]
        return len(top) == 1 and _binding_count(fn, name) == 1
    return False


def is_when_row_read(site: object, src: Path) -> bool:
    """True when `site` forwards a row of the when-refusal table by the rule above."""
    file, function = site.file, site.function  # type: ignore[attr-defined]
    if (file, function) not in WHEN_ROW_FUNCTIONS:
        return False
    name, _, attr = site.expr.partition(".")  # type: ignore[attr-defined]
    if attr not in ROW_ATTRS or not name.isidentifier():
        return False
    return _reaching_row_binding(src / file, function, name, site.line)  # type: ignore[attr-defined]
