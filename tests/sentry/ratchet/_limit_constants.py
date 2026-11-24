"""The scalar bounds the sentries read, and the one reader that returns their live values.

``LIMITS`` maps ``(test file under tests/sentry, constant)`` to ``"max"`` (a cap) or ``"min"``
(a floor). The ``sentry-limits`` baseline mirrors it, so the ratchet sees a raised cap or a
lowered floor like any other loosened bound. Read by ``_baseline_sources.py``.
"""

from __future__ import annotations

import ast

from tests.sentry.ratchet._bindings import bound_names

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
    ("release/test_public_census.py", "MIN_PACKAGES"): "min",  # `>=` floor on packages walked
    ("release/test_public_census.py", "MIN_NAMES"): "min",  # `>=` floor on public names walked
}

DIRECTIONS = ("max", "min")


def direction_problems(limits: dict[tuple[str, str], str]) -> list[str]:
    """Rows whose direction is neither ``max`` nor ``min``: such a row would drop out of both
    numeric maps and leave the baseline entry unchecked."""
    return [
        f"{file}::{name}: direction {kind!r} is not one of {', '.join(DIRECTIONS)}"
        for (file, name), kind in sorted(limits.items())
        if kind not in DIRECTIONS
    ]


# Module-level integer constants under tests/sentry that are not bounds, each with the reason.
# ``test_every_module_int_is_a_bound_or_named`` fails on any other one.
NOT_A_BOUND: dict[tuple[str, str], str] = {
    ("profiling/test_snapshot_value_registry.py", "_N"): (
        "row count of a seeded fixture frame, not compared to a measure"
    ),
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
    total = int(live and name in bound_names(node) and not isinstance(node, ast.arg))
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


def int_literal(value: ast.AST | None) -> int | None:
    """The value of a plain integer literal, signed or not (``5``, ``-5``, ``+5``); ``None`` for a
    bool, a float, an expression or anything else. The one parser for discovery and live reads."""
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.USub, ast.UAdd)):
        inner = int_literal(value.operand)
        if inner is None or isinstance(value.operand, ast.UnaryOp):
            return None
        return -inner if isinstance(value.op, ast.USub) else inner
    if isinstance(value, ast.Constant) and type(value.value) is int:
        return value.value
    return None


def _paired(target: ast.AST, value: ast.AST | None, out: dict[str, int | None]) -> None:
    """Match ``target`` to ``value``: a name takes the literal (or ``None`` when it is not one); a
    tuple or list target takes a tuple or list value of the same length element by element."""
    if isinstance(target, ast.Name):
        out[target.id] = int_literal(value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            for t, v in zip(target.elts, value.elts, strict=True):
                _paired(t, v, out)
        else:
            for node in ast.walk(target):
                if isinstance(node, ast.Name):
                    out[node.id] = None


def module_int_assignments(tree: ast.Module) -> dict[str, int | None]:
    """Each name a module-level ``=`` or annotated assignment binds, with its integer literal or
    ``None`` when the right side is not one. Chained targets (``A = B = 7``) and paired
    tuple targets (``A, B = 1, 2``) count. A name bound twice keeps the last binding."""
    out: dict[str, int | None] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _paired(target, node.value, out)
        elif isinstance(node, ast.AnnAssign):
            _paired(node.target, node.value, out)
    return out


def read_int(source: str, constant: str) -> int:
    """The value of module-level ``NAME = <int>`` or ``NAME: int = <int>`` in ``source``, by ``ast``.

    The literal may be signed and the name may sit in a chained or paired tuple assignment
    (``A, B = 1, 2``). Python uses the last binding, so the name must have exactly one: any other
    binding (a second assignment, ``+=``, unpacking of a non-literal, a loop or ``with`` target,
    ``:=``, ``del``, an import, a ``def``, or a rebind in a function that declares it ``global``)
    raises, as does a bool, a non-literal or a missing name. The module is never imported. The
    caller reads the file: this package holds checker code, whose reads all go through
    ``_integrity``.
    """
    tree = ast.parse(source)
    if _count_bindings(tree, constant, True) != 1:
        raise ValueError(f"{constant} must be bound exactly once at module level")
    value = module_int_assignments(tree).get(constant)
    if value is None:
        raise ValueError(f"{constant} is not a plain integer literal at module level")
    return value


def key_of(file: str, constant: str) -> str:
    return f"{file}::{constant}"


def consumer_problems(source: str, name: str, home: str) -> list[str]:
    """How a module that uses ``name`` from another file may go wrong. ``home`` is the stem of
    the declaring file.

    A consumer must import the constant by name from ``home``, never under an alias, rebind or
    shadow it, nor read it as an attribute, and may use it only as a direct operand of a
    comparison. Arithmetic on it (``NAME - 1``) or passing it on lowers the bound the registry
    records without touching the declaring file. A module that does not import ``name`` or
    read it as an attribute is not a consumer and gives no problems.
    """
    tree = ast.parse(source)
    imports = [
        (node, alias)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == name
    ]
    attrs = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == name]
    if not imports and not attrs:
        return []
    parents = {kid: node for node in ast.walk(tree) for kid in ast.iter_child_nodes(node)}
    out = [f"{name} is read as an attribute; import it by name from {home}" for _ in attrs]
    for node, alias in imports:
        if alias.asname or (node.module or "").split(".")[-1] != home:
            out.append(f"{name} must be imported by its own name from {home}")
    binds = sum(name in bound_names(n) for n in ast.walk(tree))
    if binds > len(imports):
        out.append(f"{name} is bound again in the importing module")
    for use in ast.walk(tree):
        if isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load):
            if not isinstance(parents.get(use), ast.Compare):
                out.append(f"{name} is used other than as a direct comparison operand")
    return out
