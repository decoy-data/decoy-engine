"""F31 audit census: outbound text sites by class and risk (heuristic AST walk)."""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = sys.argv[2]

EXC_NAMES = {"exc", "e", "err", "error", "ex", "exception", "cause", "inner", "boom"}
VALUE_NAMES = {
    "value",
    "v",
    "val",
    "values",
    "cell",
    "row",
    "expression",
    "expr",
    "formula",
    "text",
    "data",
    "sample",
    "raw",
    "record",
    "item",
    "line",
    "content",
    "z3",
    "z5",
    "zip3",
    "zip5",
    "zipcode",
    "prefix",
    "stderr",
    "stdout",
    "output",
    "payload",
    "body",
    "literal",
    "token",
    "secret",
    "password",
    "key",
    "default",
    "example",
    "examples",
    "match",
    "span",
    "snippet",
    "x",
    "obj",
    "rows",
    "series",
    "df",
    "frame",
}
LOC_PARTS = (
    "path",
    "uri",
    "url",
    "dsn",
    "conn",
    "locator",
    "bucket",
    "file",
    "dir",
    "target",
    "location",
    "endpoint",
    "host",
)
SAFE_EXC_ATTRS = {
    "__name__",
    "__class__",
    "code",
    "reason",
    "kind",
    "error_code",
    "exit_code",
    "errno",
    "status",
    "label",
    "category",
    "reason_code",
    "error_type",
    "lineno",
    "column",
    "location",
    "field",
    "loc",
}
LOG_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
LOGGER_RECV = {
    "log",
    "logger",
    "_log",
    "_logger",
    "LOG",
    "LOGGER",
    "_LOG",
    "_LOGGER",
    "logging",
    "self.logger",
    "self.log",
    "self._logger",
    "self._log",
    "cls.logger",
}


def recv_text(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def classify_expr(node: ast.AST, exc_bound: set[str]) -> set[str]:
    """Return the set of taint tags in an expression: EXC, VALUE, LOC, IDENT."""
    tags: set[str] = set()

    def walk(n: ast.AST) -> None:
        if isinstance(n, ast.Constant):
            return
        if isinstance(n, ast.Call):
            fn = recv_text(n.func)
            if fn in ("type",):
                return  # type(exc) -> safe when followed by __name__ (handled at attr)
            if fn in ("len", "int", "float", "bool", "id", "hex", "sorted_len"):
                return
            if fn.endswith(".format_exc") or fn.endswith("format_exception"):
                tags.add("EXC")
            for a in n.args:
                walk(a)
            for k in n.keywords:
                walk(k.value)
            if isinstance(n.func, ast.Attribute):
                if n.func.attr in ("count", "nunique", "sum", "size", "__len__", "qualname"):
                    return
                walk(n.func.value)
            return
        if isinstance(n, ast.Attribute):
            root = n
            chain = []
            while isinstance(root, ast.Attribute):
                chain.append(root.attr)
                root = root.value
            if isinstance(root, ast.Call) and recv_text(root.func) == "type":
                return
            if isinstance(root, ast.Name):
                if root.id in exc_bound or root.id in EXC_NAMES:
                    if (
                        (chain
                        and chain[-1] in SAFE_EXC_ATTRS)
                        or (chain and chain[0] in SAFE_EXC_ATTRS)
                    ):
                        return
                    tags.add("EXC")
                    return
                name = chain[0].lower()
                if name in VALUE_NAMES:
                    tags.add("VALUE")
                elif any(p in name for p in LOC_PARTS):
                    tags.add("LOC")
                else:
                    tags.add("IDENT")
                return
            walk(root)
            return
        if isinstance(n, ast.Name):
            low = n.id.lower()
            if n.id in exc_bound or n.id in EXC_NAMES:
                tags.add("EXC")
            elif low in VALUE_NAMES:
                tags.add("VALUE")
            elif any(p in low for p in LOC_PARTS):
                tags.add("LOC")
            elif n.id.isupper():
                return  # constant
            else:
                tags.add("IDENT")
            return
        for c in ast.iter_child_nodes(n):
            walk(c)

    walk(node)
    return tags


def message_args(call: ast.Call) -> list[ast.AST]:
    return list(call.args) + [
        k.value
        for k in call.keywords
        if k.arg not in ("exc_info", "stacklevel", "extra", "category")
    ]


def risk_of(tags: set[str], traceback: bool = False) -> str:
    if traceback or "EXC" in tags or "VALUE" in tags:
        return "leak"
    if "LOC" in tags:
        return "review_loc"
    if "IDENT" in tags:
        return "safe_ident"
    return "safe_const"


def scan_file(path: Path, rel: str, results: dict) -> None:
    try:
        tree = ast.parse(path.read_text("utf-8"))
    except Exception:
        return

    def visit(node: ast.AST, exc_bound: set[str], func: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            func = f"{func}.{node.name}" if func else node.name
        if isinstance(node, ast.ExceptHandler) and node.name:
            exc_bound = exc_bound | {node.name}
        if isinstance(node, ast.Raise) and node.exc is not None:
            ex = node.exc
            if isinstance(ex, ast.Call):
                args = message_args(ex)
                tags = set()
                for a in args:
                    tags |= classify_expr(a, exc_bound)
                cls = "raise_msg" if args else "raise_bare"
                results["sites"].append((rel, node.lineno, func, cls, risk_of(tags), sorted(tags)))
        if isinstance(node, ast.Call):
            fn = recv_text(node.func)
            if isinstance(node.func, ast.Attribute) and node.func.attr in LOG_LEVELS:
                recv = recv_text(node.func.value)
                if (
                    recv in LOGGER_RECV
                    or recv.endswith("logger")
                    or recv.endswith("_log")
                    or recv.startswith("logging.getLogger")
                ):
                    tb = node.func.attr == "exception" or any(
                        k.arg == "exc_info"
                        and not (
                            isinstance(k.value, ast.Constant) and k.value.value in (False, None)
                        )
                        for k in node.keywords
                    )
                    tags = set()
                    for a in message_args(node):
                        tags |= classify_expr(a, exc_bound)
                    results["sites"].append(
                        (
                            rel,
                            node.lineno,
                            func,
                            "log",
                            risk_of(tags, tb),
                            sorted(tags) + (["TB"] if tb else []),
                        )
                    )
            elif fn in ("warnings.warn", "warn"):
                tags = set()
                for a in message_args(node):
                    tags |= classify_expr(a, exc_bound)
                results["sites"].append(
                    (rel, node.lineno, func, "warn", risk_of(tags), sorted(tags))
                )
            elif (
                fn
                in (
                    "print",
                    "sys.stdout.write",
                    "sys.stderr.write",
                    "click.echo",
                    "typer.echo",
                    "click.secho",
                    "typer.secho",
                )
                or fn.endswith("console.print")
                or fn.endswith("err_console.print")
                or fn.endswith(".echo")
                or fn.endswith("emit_error")
                or fn.endswith("emit_json")
                or fn.endswith("print_error")
                or fn.endswith("print_warning")
                or fn.endswith("fail")
            ):
                tags = set()
                for a in message_args(node):
                    tags |= classify_expr(a, exc_bound)
                results["sites"].append(
                    (rel, node.lineno, func, "terminal", risk_of(tags), sorted(tags))
                )
            elif (
                fn in ("str", "repr")
                and node.args
                and isinstance(node.args[0], ast.Name)
                and (node.args[0].id in exc_bound or node.args[0].id in EXC_NAMES)
            ):
                results["sites"].append((rel, node.lineno, func, "exc_text", "leak", ["EXC"]))
            elif (
                fn.endswith("format_exc")
                or fn.endswith("format_exception")
                or fn.endswith("print_exc")
            ):
                results["sites"].append((rel, node.lineno, func, "exc_text", "leak", ["EXC", "TB"]))
        if (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id in exc_bound
        ):
            results["sites"].append((rel, node.lineno, func, "exc_fstring", "leak", ["EXC"]))
        if isinstance(node, (ast.FunctionDef,)) and node.name in ("__str__", "__repr__"):
            results["sites"].append((rel, node.lineno, func, "dunder_str", "review", []))
        for c in ast.iter_child_nodes(node):
            visit(c, exc_bound, func)

    visit(tree, set(), "")


results: dict = {"sites": []}
for p in sorted(ROOT.rglob("*.py")):
    if "__pycache__" in p.parts:
        continue
    scan_file(p, str(p.relative_to(ROOT)), results)

# de-dup exc_fstring that sit inside raise/log already counted: keep, but report separately
by = Counter((s[3], s[4]) for s in results["sites"])
files = defaultdict(Counter)
for s in results["sites"]:
    if s[4] == "leak":
        files[s[3]][s[0]] += 1
json.dump(results, open(OUT, "w"), indent=0)
for k in sorted(by):
    print(k, by[k])
print("--- top leak files by class")
for cls, c in files.items():
    print(cls, c.most_common(12))
