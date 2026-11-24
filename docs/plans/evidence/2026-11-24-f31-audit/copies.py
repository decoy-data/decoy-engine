"""F31 audit: every copy of exception text and the sink it flows to.

Usage: python3 copies.py <src root> <out.tsv>

An exception name is an `except ... as NAME` binding, or a function parameter that is named
like an exception (exc, err, e, error, ex, exception, cause, inner) or annotated with
BaseException, Exception or a name ending in Error or Exception. A copy is `str(NAME)`,
`repr(NAME)`, `format(NAME)`, an f-string `{NAME}`, `NAME.<text attribute>`, `% NAME`, or a
traceback formatter. The sink is the nearest enclosing raise, log call, terminal call, return,
assignment or dict. Output columns: file, line, form, binding (except or param), sink.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

PARAM_NAMES = {"exc", "err", "e", "error", "ex", "exception", "cause", "inner"}
TEXT_ATTRS = {
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
TERMINAL = {
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
LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
TRACEBACK = {
    "format_exc",
    "format_exception",
    "print_exc",
    "format_exception_only",
    "print_exception",
}


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


def _form(node: ast.AST, bound: dict[str, str]) -> tuple[str, str] | None:
    if isinstance(node, ast.Call):
        func = ast.unparse(node.func)
        if (
            func in ("str", "repr", "format")
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in bound
        ):
            return f"{func}(exc)", bound[node.args[0].id]
        if func.split(".")[-1] in TRACEBACK:
            return "traceback", "except"
    if (
        isinstance(node, ast.FormattedValue)
        and isinstance(node.value, ast.Name)
        and node.value.id in bound
    ):
        return "f{exc}", bound[node.value.id]
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in bound
        and node.attr in TEXT_ATTRS
    ):
        return f"exc.{node.attr}", bound[node.value.id]
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mod)
        and isinstance(node.right, ast.Name)
        and node.right.id in bound
    ):
        return "%exc", bound[node.right.id]
    return None


def scan(root: Path) -> list[tuple[str, int, str, str, str]]:
    rows = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(root))

        def visit(node: ast.AST, bound: dict[str, str], stack: list[ast.AST]) -> None:
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
                rows.append((rel, node.lineno, hit[0], hit[1], _sink(stack)))
            for child in ast.iter_child_nodes(node):
                visit(child, bound, [*stack, node])

        visit(ast.parse(path.read_text("utf-8")), {}, [])
    return rows


def main() -> None:
    rows = scan(Path(sys.argv[1]))
    with open(sys.argv[2], "w") as out:
        out.write("file\tline\tform\tbinding\tsink\n")
        for row in rows:
            out.write("\t".join(map(str, row)) + "\n")
    print("total", len(rows))
    print("by binding", dict(Counter(r[3] for r in rows)))
    print("by sink", dict(Counter(r[4] for r in rows)))
    print("binding x sink", dict(Counter((r[3], r[4]) for r in rows)))


if __name__ == "__main__":
    main()
