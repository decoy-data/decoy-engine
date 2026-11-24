"""The copy rules: where engine code copies exception text into another value.

An exception name is an `except ... as NAME` binding, or a function parameter that is named
like an exception or annotated with an exception type. A copy is `str()`, `repr()` or
`format()` of that name, an f-string `{NAME}`, a text attribute (`NAME.args`, `NAME.message`),
`% NAME`, or a traceback formatter. The rules come from the F31 audit census
(docs/plans/2026-11-24-f31-audit.md, Method step 2); this module is the test-tree home so the
ratchet does not read from docs/.

The tagger in `_tagger.py` answers a different question (which names in an expression carry
data), so the exception-name classifier stays here. The `str`/`repr`/`format` predicate and the
scope walk (`own_nodes`) come from the tagger, so there is one source for each.

Two buckets, counted apart so extending coverage never rewrites the audit figure:
  audit  the shapes the F31 audit census counted (binding is `except` or `param`);
  extra  shapes found later: an alias of an exception binding (`last_exc = exc`, used after the
         handler) and a literal `getattr(exc, "<text attr>", ...)`.
`log.warning("%s", exc)` is not a copy here: test_log_interpolation.py owns that shape.

Output is a location (file, function, line) and rule labels, never message text.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from tests.sentry.safe_output._tagger import (
    assign_target_names,
    format_builtin,
    ordered_assignments,
    own_nodes,
)

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


class Copy(NamedTuple):
    file: str
    line: int
    form: str
    binding: str
    sink: str
    func: str = "<module>"

    @property
    def bucket(self) -> str:
        return "extra" if self.binding == "alias" or self.form.startswith("getattr") else "audit"

    @property
    def key(self) -> str:
        """Stable, value-free site key: no line number, no source text."""
        return f"{self.bucket}::{self.file}::{self.func}::{self.form}::{self.sink}"


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
        builtin = format_builtin(node)
        if builtin and node.args and _is_bound(node.args[0], bound):
            return f"{builtin}(exc)", bound[node.args[0].id]  # type: ignore[attr-defined]
        if (
            func == "getattr"
            and len(node.args) >= 2
            and _is_bound(node.args[0], bound)
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in TEXT_ATTRS
        ):
            return f"getattr(exc.{node.args[1].value})", bound[node.args[0].id]  # type: ignore[attr-defined]
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


def _aliases(scope: ast.AST, bound: dict[str, str]) -> dict[str, str]:
    """Names assigned straight from an exception binding of this scope: `last_exc = exc`.

    Bounded on purpose: one scope, plain or annotated `name = bound_name` assignments in source order (so a
    chain of aliases resolves), no flow through calls or containers. Seeded only by this
    module's own bindings (handler names and exception-like parameters).
    """
    own = own_nodes(scope)
    known = set(bound) | {n.name for n in own if isinstance(n, ast.ExceptHandler) and n.name}
    found: dict[str, str] = {}
    for node in ordered_assignments(own):
        # AE4 is narrower than the tagger: only a direct name (`last = exc`, `last: E = exc`).
        if isinstance(node.value, ast.Name) and node.value.id in known | set(found):
            for name in assign_target_names(node):
                if name not in bound:
                    found[name] = "alias"
    return found


def _visit(
    node: ast.AST, bound: dict[str, str], stack: list[ast.AST], rel: str, func: str = "<module>"
) -> Iterator[Copy]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        bound = dict(bound)
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if arg.arg in PARAM_NAMES or _exc_annotation(arg.annotation):
                bound[arg.arg] = "param"
            else:
                bound.pop(arg.arg, None)
        if not isinstance(node, ast.Lambda):
            bound = {**_aliases(node, bound), **bound}
        name = getattr(node, "name", "<lambda>")
        func = name if func == "<module>" else f"{func}.{name}"
    elif isinstance(node, ast.ClassDef):
        func = node.name if func == "<module>" else f"{func}.{node.name}"
    if isinstance(node, ast.ExceptHandler) and node.name:
        bound = {**bound, node.name: "except"}
    hit = _form(node, bound)
    if hit:
        yield Copy(rel, getattr(node, "lineno", 0), hit[0], hit[1], _sink(stack), func)
    for child in ast.iter_child_nodes(node):
        yield from _visit(child, bound, [*stack, node], rel, func)


def scan_source(source: str, rel: str = "<memory>") -> list[Copy]:
    """Every exception-text copy in one module's source."""
    tree = ast.parse(source)
    return list(
        _visit(
            tree,
            {
                **_aliases(tree, {}),
            },
            [],
            rel,
        )
    )


def scan_tree(root: Path) -> list[Copy]:
    """Every copy under `root`, files in sorted order, paths relative to `root`."""
    copies: list[Copy] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        copies.extend(scan_source(path.read_text("utf-8"), str(path.relative_to(root))))
    return copies


def census(copies: list[Copy]) -> dict[str, int]:
    """Site key to how many copies share it. This is what the baseline records, as `max`."""
    counts: dict[str, int] = {}
    for copy in copies:
        counts[copy.key] = counts.get(copy.key, 0) + 1
    return dict(sorted(counts.items()))
