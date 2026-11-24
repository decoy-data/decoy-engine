"""Lines where a function copies exception text into an expression (`str(exc)`, `f"{exc}"`).

An exception name is an `except ... as NAME` binding, or a parameter named like an exception or
annotated with an exception type. A copy is `str`/`repr`/`format` of it, an f-string slot, a
text attribute, `% NAME` or a traceback formatter. The registry rule uses the lines to refuse a
class whose raise sits in a function that already copies exception text. The copy ratchet (AE4)
reads the same forms.
"""

from __future__ import annotations

import ast

PARAM_NAMES = frozenset({"exc", "err", "e", "error", "ex", "exception", "cause", "inner"})
TEXT_ATTRS = frozenset(
    {
        "args",
        "message",
        "msg",
        "detail",
        "details",
        "raw_message",
        "stderr",
        "stdout",
        "problem_mark",
        "note",
        "text",
        "reason_text",
        "description",
        "strerror",
        "filename",
        "filename2",
        "doc",
        "pos",
        "context_mark",
    }
)
TRACEBACK = frozenset(
    {"format_exc", "format_exception", "print_exc", "format_exception_only", "print_exception"}
)


def _exc_annotation(node: ast.expr | None) -> bool:
    if node is None:
        return False
    parts = ast.unparse(node).replace("|", " ").replace("[", " ").replace("]", " ").split()
    return any(p.endswith(("Error", "Exception")) or p == "BaseException" for p in parts)


def _is_copy(node: ast.AST, bound: frozenset[str]) -> bool:
    if isinstance(node, ast.Call):
        func = ast.unparse(node.func)
        if (
            func in ("str", "repr", "format")
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in bound
        ):
            return True
        return func.split(".")[-1] in TRACEBACK
    if isinstance(node, ast.FormattedValue):
        return isinstance(node.value, ast.Name) and node.value.id in bound
    if isinstance(node, ast.Attribute):
        return (
            isinstance(node.value, ast.Name) and node.value.id in bound and node.attr in TEXT_ATTRS
        )
    if isinstance(node, ast.BinOp):
        return (
            isinstance(node.op, ast.Mod)
            and isinstance(node.right, ast.Name)
            and node.right.id in bound
        )
    return False


def copy_lines(tree: ast.AST) -> frozenset[int]:
    """The line of every exception-text copy in `tree`."""
    lines: set[int] = set()

    def visit(node: ast.AST, bound: frozenset[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            names = {
                a.arg
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
                if a.arg in PARAM_NAMES or _exc_annotation(a.annotation)
            }
            shadowed = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            bound = frozenset((bound - shadowed) | names)
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound = bound | {node.name}
        if _is_copy(node, bound):
            lines.add(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, bound)

    visit(tree, frozenset())
    return frozenset(lines)
