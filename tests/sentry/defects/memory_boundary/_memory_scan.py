"""The scanner behind the memory-boundary guard: which handlers can hold a `MemoryError`, and
whether each one lets it pass.

A handler can catch `MemoryError` when its type is bare, or names (as a `Name` or the last
`Attribute` part, alone or in a tuple) `Exception`, `BaseException`, `ArrowException`,
`MemoryError` or `ArrowMemoryError`. Import aliases resolve through `ModuleIndex`. A handler
passes in one of three shapes (see `handler_problem`). A `contextlib.suppress` naming such a type
and a `return`, `break` or `continue` in a `finally` are findings too, since each discards an
in-flight memory error. `A19` imports `SCOPE` and `risky_functions` from here, so the guard and
the trace test share one definition.

Known limit, not chased: an exception class bound to another name (`Broad = Exception`).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tests.sentry.defects import _defect_scan as scan

# Globs under `src/decoy_engine`: the modules the isolated and resident commit windows run
# through (the A19 trace), each of which must match a file.
SCOPE = (
    "publication/*.py",
    "vault/*.py",
    "reason_adapter.py",
    "execution/_isolated_commit.py",
    "execution/_isolated_reason.py",
    "execution/_isolated_run.py",
    "execution/_isolated_common.py",
    "fileaccess/_errors.py",
    "fileaccess/_local_chain.py",
    "fileaccess/_output.py",
    "determinism/_derive.py",
    "determinism/_hkdf.py",
    "internal/crypto.py",
)

# The only handlers that may turn a `MemoryError` into something else: (path, function, kind).
# "arm": one `except MemoryError` that converts (a result or a record), and any broad handler of
# the same try must come after it. "run": the resident run's own failure handler, whose
# protected body is the `run_pipeline` call alone.
CLASSIFIERS = {
    ("execution/_isolated_reason.py", "memory_boundary"): "arm",
    ("reason_adapter.py", "reason_from_exception"): "arm",
    ("execution/_isolated_run.py", "_run_in_process"): "run",
}

_MEMORY_NAMES = frozenset(
    {"Exception", "BaseException", "ArrowException", "MemoryError", "ArrowMemoryError"}
)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Names:
    """The import aliases of one module: local name to original, and local module to dotted."""

    names: dict[str, str]
    modules: dict[str, str]


def names_of(index: scan.ModuleIndex, mod: str) -> Names:
    return Names(
        {local: name for (m, local), (_b, name) in index.imports.items() if m == mod},
        {local: dotted for (m, local), dotted in index.module_aliases.items() if m == mod},
    )


def scope_paths(index: scan.ModuleIndex, scope: tuple[str, ...] = SCOPE) -> dict[Path, str]:
    """The scanned files for each `scope` glob; a glob that matches nothing is an error."""
    found: dict[Path, str] = {}
    for pattern in scope:
        matched = sorted(index.src.glob(pattern))
        assert matched, f"SCOPE entry {pattern} matches no file"
        for path in matched:
            found[path] = path.relative_to(index.src).as_posix()
    return found


def _named(node: ast.expr, names: Names) -> Iterator[str]:
    if isinstance(node, ast.Tuple):
        for element in node.elts:
            yield from _named(element, names)
    elif isinstance(node, ast.Name):
        yield names.names.get(node.id, node.id)
    elif isinstance(node, ast.Attribute):
        yield node.attr


def catches_memory(handler: ast.ExceptHandler, names: Names) -> bool:
    """True when `handler` can hold a `MemoryError`."""
    if handler.type is None:
        return True
    return bool(set(_named(handler.type, names)) & _MEMORY_NAMES)


def is_clause(handler: ast.ExceptHandler) -> bool:
    """Exactly `except MemoryError:` with the body `raise`."""
    kind = handler.type
    only_raise = (
        len(handler.body) == 1
        and isinstance(handler.body[0], ast.Raise)
        and handler.body[0].exc is None
        and handler.body[0].cause is None
    )
    return isinstance(kind, ast.Name) and kind.id == "MemoryError" and only_raise


def _own_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Every node of `body` outside nested `def` and `lambda` bodies."""
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (*_FUNCTIONS, ast.Lambda)):
                pending.append(child)


def _passes_through(handler: ast.ExceptHandler) -> bool:
    """Shape 2: the last statement is a bare `raise`, every `raise` is bare and nothing returns,
    breaks or continues."""
    body = handler.body
    if not (isinstance(body[-1], ast.Raise) and body[-1].exc is None):
        return False
    for node in _own_nodes(body):
        if isinstance(node, ast.Raise) and (node.exc is not None or node.cause is not None):
            return False
        if isinstance(node, (ast.Return, ast.Break, ast.Continue)):
            return False
    return True


def handler_problem(
    try_node: ast.Try, handler: ast.ExceptHandler, names: Names, classifier: str | None
) -> str | None:
    """Why `handler` can hide a `MemoryError`, or None when it cannot."""
    if not catches_memory(handler, names) or is_clause(handler):
        return None
    index = try_node.handlers.index(handler)
    if any(is_clause(earlier) for earlier in try_node.handlers[:index]):
        return None
    if _passes_through(handler):
        return None
    if classifier is not None:
        return None  # judged by `classifier_problems`
    return "catches MemoryError without the clause, a final bare raise or a registered role"


def finally_exit(try_node: ast.Try) -> bool:
    """A `return`, `break` or `continue` in `finally` discards the in-flight exception."""
    for node in _own_nodes(try_node.finalbody):
        if isinstance(node, ast.Return):
            return True
        if isinstance(node, (ast.Break, ast.Continue)):
            return True
    return False


def suppresses_memory(node: ast.With, names: Names) -> bool:
    """`with contextlib.suppress(<a memory-catching type>)`, under any import spelling."""
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Name):
            spelled = names.names.get(func.id, func.id) == "suppress"
        else:
            spelled = isinstance(func, ast.Attribute) and func.attr == "suppress"
        if spelled and any(set(_named(arg, names)) & _MEMORY_NAMES for arg in call.args):
            return True
    return False


def _walk_functions(
    tree: ast.AST, prefix: str = ""
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, _FUNCTIONS):
            qualified = f"{prefix}{node.name}"
            yield qualified, node
            yield from _walk_functions(node, f"{qualified}.")
        elif isinstance(node, ast.ClassDef):
            yield from _walk_functions(node, f"{prefix}{node.name}.")
        else:
            yield from _walk_functions(node, prefix)


def _tries(function: ast.AST) -> Iterator[ast.Try]:
    for node in _own_nodes(function.body):  # type: ignore[attr-defined]
        if isinstance(node, ast.Try):
            yield node


def classifier_problems(function: ast.FunctionDef, kind: str, names: Names) -> list[str]:
    """The registered classifier's own rule: one converting arm, in order, over the right body."""
    problems: list[str] = []
    arms = [
        (try_node, handler)
        for try_node in _tries(function)
        for handler in try_node.handlers
        if catches_memory(handler, names) and not is_clause(handler)
    ]
    if kind == "arm":
        converting = [
            (t, h) for t, h in arms if isinstance(h.type, ast.Name) and h.type.id == "MemoryError"
        ]
        if len(converting) != 1:
            problems.append(f"needs exactly one `except MemoryError` arm, found {len(converting)}")
        for try_node, handler in arms:
            if (try_node, handler) in converting:
                continue
            earlier = try_node.handlers[: try_node.handlers.index(handler)]
            if not any(h in [c[1] for c in converting] for h in earlier):
                problems.append("a broad handler precedes the MemoryError arm")
    else:
        if len(arms) != 1:
            problems.append(f"needs exactly one run handler, found {len(arms)}")
        for try_node, _handler in arms:
            body = try_node.body
            call = body[0].value if len(body) == 1 and isinstance(body[0], ast.Assign) else None
            name = getattr(getattr(call, "func", None), "id", None)
            if name != "run_pipeline":
                problems.append("the protected body is more than the run_pipeline call")
    return problems


def risky_functions(tree: ast.Module, names: Names) -> set[str]:
    """Qualified names of the functions that hold a memory-catching handler, a memory-naming
    `suppress` or a `finally` exit (the discovery A19 checks against its trace)."""
    found: set[str] = set()
    for qualified, function in _walk_functions(tree):
        for node in _own_nodes(function.body):
            if (
                isinstance(node, ast.Try)
                and (finally_exit(node) or any(catches_memory(h, names) for h in node.handlers))
            ) or (isinstance(node, ast.With) and suppresses_memory(node, names)):
                found.add(qualified)
    return found


def file_findings(
    tree: ast.Module, rel: str, names: Names, registry: dict[tuple[str, str], str]
) -> list[str]:
    """Every way a function in `tree` can hide a `MemoryError`."""
    out: list[str] = []
    for qualified, function in _walk_functions(tree):
        if function.name == "__del__":
            continue  # a finalizer's exceptions are discarded: a clause there changes nothing
        kind = registry.get((rel, qualified))
        for node in _own_nodes(function.body):
            where = f"{rel}:{getattr(node, 'lineno', function.lineno)} {qualified}"
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    problem = handler_problem(node, handler, names, kind)
                    if problem:
                        out.append(
                            f"{where.rsplit(' ', 1)[0]}:{handler.lineno} {qualified}: {problem}"
                        )
                if finally_exit(node):
                    out.append(f"{where}: a return, break or continue in finally")
            elif isinstance(node, ast.With) and suppresses_memory(node, names):
                out.append(f"{where}: contextlib.suppress names a memory-catching type")
        if kind is not None and isinstance(function, ast.FunctionDef):
            out += [f"{rel} {qualified}: {p}" for p in classifier_problems(function, kind, names)]
    return out


def scan_scope(
    index: scan.ModuleIndex,
    scope: tuple[str, ...] = SCOPE,
    classifiers: dict[tuple[str, str], str] | None = None,
) -> list[str]:
    """The findings over every file of `scope`, plus a registered classifier that is gone."""
    registry = CLASSIFIERS if classifiers is None else classifiers
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path, rel in scope_paths(index, scope).items():
        tree = index.trees[path]
        mod = scan.module_name(path, index.src)
        out += file_findings(tree, rel, names_of(index, mod), registry)
        seen |= {(rel, q) for q, _f in _walk_functions(tree)}
    out += [
        f"{p}: registered classifier {q} no longer exists"
        for p, q in registry
        if (p, q) not in seen
    ]
    return out


def function_spans(tree: ast.Module) -> list[tuple[str, int, int]]:
    """(qualified name, first line including decorators, last line) of every function."""
    spans = []
    for qualified, function in _walk_functions(tree):
        first = min([function.lineno, *(d.lineno for d in function.decorator_list)])
        spans.append((qualified, first, function.end_lineno or function.lineno))
    return spans
