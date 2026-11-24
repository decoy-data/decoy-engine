"""The scalar bounds the sentries read, and the one reader that returns their live values.

``LIMITS`` maps ``(test file under tests/sentry, constant)`` to ``"max"`` (a cap) or ``"min"``
(a floor). The ``sentry-limits`` baseline mirrors it, so the ratchet sees a raised cap or a
lowered floor like any other loosened bound. Read by ``_baseline_sources.py``.
"""

from __future__ import annotations

import ast

# Each row names the line that compares against the constant (checked when it was added).
LIMITS: dict[tuple[str, str], str] = {
    ("test_module_size.py", "GOAL"): "max",  # an entry at or under GOAL needs no allowlist row
    ("test_module_size.py", "MAX"): "max",  # hard ceiling for new work
    ("test_module_size.py", "MARGIN"): "max",  # headroom added to a dense ceiling
    ("layout/test_package_fanout.py", "LIMIT"): "max",  # direct-module cap per package
    ("test_outbound_clients.py", "WALK_FLOOR"): "min",  # `>=` floor on files walked
    ("release/test_public_signatures.py", "HEAD_FLOOR"): "min",  # `>=` floor on public names
    (
        "dependencies/_faker_lock_lists.py",
        "EN_US_DIGEST_FLOOR",
    ): "min",  # `>=` floor on digest pairs
    ("defects/test_faker_native_allowlist_total.py", "MIN_COPY"): "max",  # `>=` flags a copy
    ("_ratchet.py", "MIN_REASON"): "min",  # a reason under it fails
}

# Module-level integer constants under tests/sentry that are not bounds, each with the reason.
# ``test_every_module_int_is_a_bound_or_named`` fails on any other one.
NOT_A_BOUND: dict[tuple[str, str], str] = {
    ("ci_scan/_identity.py", "TRIES"): "default retry count of a helper, not compared to a measure",
    (
        "parallel/_resources.py",
        "HOPS",
    ): "default search depth of a helper, not compared to a measure",
    ("safe_output/test_exception_text_copy.py", "AUDIT_PARITY"): (
        "exact-equality pin of the audit bucket; any change fails, so it cannot loosen quietly"
    ),
}


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _binds(node: ast.AST, name: str) -> bool:
    """True when ``node`` itself binds ``name`` in the scope that holds it."""
    if isinstance(node, ast.Name):
        return node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == name
    if isinstance(node, ast.alias):
        return (node.asname or node.name.split(".")[0]) == name
    if isinstance(node, ast.ExceptHandler):
        return node.name == name
    if isinstance(node, (ast.MatchAs, ast.MatchStar)):
        return node.name == name
    return isinstance(node, ast.MatchMapping) and node.rest == name


def _global_names(scope: ast.AST) -> set[str]:
    """Names a function or class body declares ``global``, not counting nested scopes."""
    out: set[str] = set()
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Global):
            out.update(node.names)
        elif not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    return out


def _count_bindings(node: ast.AST, name: str, live: bool) -> int:
    """Bindings of module-level ``name`` under ``node``: module scope, and any function or class
    scope that declares it ``global``. A local of the same name does not count. ``live`` is true
    when ``node`` sits in such a scope."""
    total = int(live and _binds(node, name))
    for field, value in ast.iter_fields(node):
        for kid in value if isinstance(value, list) else [value]:
            if not isinstance(kid, ast.AST):
                continue
            inner = live
            if field == "body" and isinstance(node, _SCOPES):
                inner = name in _global_names(node)
            elif field == "target" and isinstance(node, ast.comprehension):
                inner = False  # a comprehension target is local to it
            total += _count_bindings(kid, name, inner)
    return total


def read_int(source: str, constant: str) -> int:
    """The value of module-level ``NAME = <int>`` or ``NAME: int = <int>`` in ``source``, by ``ast``.

    Python uses the last binding, so the name must have exactly one: any other binding (a second
    assignment, ``+=``, unpacking, a loop or ``with`` target, ``:=``, ``del``, an import, a
    ``def``, or a rebind in a function that declares it ``global``) raises, as does a bool, a
    non-literal or a missing name. The module is never imported. The caller reads the file: this
    package holds checker code, whose reads all go through ``_integrity``.
    """
    tree = ast.parse(source)
    if _count_bindings(tree, constant, True) != 1:
        raise ValueError(f"{constant} must be bound exactly once at module level")
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == constant for t in targets):
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
            ):
                return value.value
            break
    raise ValueError(f"{constant} is not a plain integer literal at module level")


def key_of(file: str, constant: str) -> str:
    return f"{file}::{constant}"
