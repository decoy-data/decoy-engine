"""The copy rules: where engine code copies exception text into another value.

An exception name is an `except ... as NAME` binding, or a function parameter that is named
like an exception or annotated with an exception type. A copy is `str()`, `repr()` or
`format()` of that name, an f-string `{NAME}`, a text attribute (`NAME.args`, `NAME.message`),
`% NAME`, or a traceback formatter. The rules come from the F31 audit census
(docs/plans/2026-11-24-f31-audit.md, Method step 2); this module is the test-tree home so the
ratchet does not read from docs/.

The tagger in `_tagger.py` answers a different question (which names in an expression carry
data), so the copy rules stay here and only share its one-edit idea: a rule change is one edit.
Output is a location (file, line) and rule labels, never message text.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

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
TERMINAL = frozenset(
    {
        "emit_error",
        "_emit_error",
        "emit_json",
        "echo",
        "secho",
        "print",
        "write",
        "fail",
        "add_fail",
        "print_error",
        "print_warning",
    }
)
LOG = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})
TRACEBACK = frozenset(
    {"format_exc", "format_exception", "print_exc", "format_exception_only", "print_exception"}
)
STR_CALLS = frozenset({"str", "repr", "format"})


class Copy(NamedTuple):
    file: str
    line: int
    form: str
    binding: str
    sink: str


def _exc_annotation(node: ast.expr | None) -> bool:
    if node is None:
        return False
    text = ast.unparse(node)
    return any(
        part.endswith(("Error", "Exception")) or part == "BaseException"
        for part in text.replace("|", " ").replace("[", " ").replace("]", " ").split()
    )


def _sink(stack: list[ast.AST]) -> str:
    for node in reversed(stack):
        if isinstance(node, ast.Raise):
            return "raise"
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            last = func.split(".")[-1]
            if isinstance(node.func, ast.Attribute) and last in LOG and "log" in func.lower():
                return "log"
            if last in TERMINAL or func.endswith("console.print"):
                return "terminal"
        if isinstance(node, ast.Return):
            return "return"
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            return "assign"
        if isinstance(node, ast.Dict):
            return "dict"
    return "other"


def _is_bound(node: ast.AST, bound: dict[str, str]) -> bool:
    return isinstance(node, ast.Name) and node.id in bound


def _form(node: ast.AST, bound: dict[str, str]) -> tuple[str, str] | None:
    if isinstance(node, ast.Call):
        func = ast.unparse(node.func)
        if func in STR_CALLS and node.args and _is_bound(node.args[0], bound):
            return f"{func}(exc)", bound[node.args[0].id]  # type: ignore[attr-defined]
        if func.split(".")[-1] in TRACEBACK:
            return "traceback", "except"
    if isinstance(node, ast.FormattedValue) and _is_bound(node.value, bound):
        return "f{exc}", bound[node.value.id]  # type: ignore[attr-defined]
    if isinstance(node, ast.Attribute) and _is_bound(node.value, bound) and node.attr in TEXT_ATTRS:
        return f"exc.{node.attr}", bound[node.value.id]  # type: ignore[attr-defined]
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mod)
        and _is_bound(node.right, bound)
    ):
        return "%exc", bound[node.right.id]  # type: ignore[attr-defined]
    return None


def _visit(node: ast.AST, bound: dict[str, str], stack: list[ast.AST], rel: str) -> Iterator[Copy]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        bound = dict(bound)
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if arg.arg in PARAM_NAMES or _exc_annotation(arg.annotation):
                bound[arg.arg] = "param"
            else:
                bound.pop(arg.arg, None)
    if isinstance(node, ast.ExceptHandler) and node.name:
        bound = {**bound, node.name: "except"}
    hit = _form(node, bound)
    if hit:
        yield Copy(rel, getattr(node, "lineno", 0), hit[0], hit[1], _sink(stack))
    for child in ast.iter_child_nodes(node):
        yield from _visit(child, bound, [*stack, node], rel)


def scan_source(source: str, rel: str = "<memory>") -> list[Copy]:
    """Every exception-text copy in one module's source."""
    return list(_visit(ast.parse(source), {}, [], rel))


def scan_tree(root: Path) -> list[Copy]:
    """Every copy under `root`, files in sorted order, paths relative to `root`."""
    copies: list[Copy] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        copies.extend(scan_source(path.read_text("utf-8"), str(path.relative_to(root))))
    return copies
