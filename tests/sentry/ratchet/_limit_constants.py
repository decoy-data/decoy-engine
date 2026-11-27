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


REFUSED = "must be one module-level NAME = <int> statement"

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_TARGET_OWNERS = (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor, ast.NamedExpr)


def _global_names(scope: ast.AST) -> frozenset[str]:
    """Names a function or class body declares ``global``, not counting nested scopes."""
    out: set[str] = set()
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Global):
            out.update(node.names)
        elif not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    return frozenset(out)


def _bindings(tree: ast.Module) -> list[tuple[str, ast.AST | None]]:
    """Every binding of every name in the counted scopes, as ``(name, owner)``. The counted scopes
    are the module and any function or class body, for the names it declares ``global``; a
    comprehension target is local and does not count. ``owner`` is the construct whose target or
    pattern holds the name (an assignment, loop, ``with`` item, walrus or ``match``), ``None`` for
    a ``def``, import, ``except``, ``global`` or ``del``. A subscript or attribute target binds no
    name: its base and key are Loads, and a walrus inside it is its own owner."""
    out: list[tuple[str, ast.AST | None]] = []

    def visit(node: ast.AST, live: frozenset[str] | None, owner: ast.AST | None) -> None:
        if not isinstance(node, ast.arg):
            out.extend((name, owner) for name in bound_names(node) if live is None or name in live)
        keeps_owner = isinstance(node, (ast.expr, ast.pattern))
        for field, value in ast.iter_fields(node):
            for kid in value if isinstance(value, list) else [value]:
                if not isinstance(kid, ast.AST):
                    continue
                inner = live
                if field == "body" and isinstance(node, _SCOPES):
                    inner = _global_names(node)
                elif field == "target" and isinstance(node, ast.comprehension):
                    inner = frozenset()
                kid_owner = owner if keeps_owner else None
                if (
                    (field == "targets" and isinstance(node, ast.Assign))
                    or (field == "target" and isinstance(node, _TARGET_OWNERS))
                    or (field == "optional_vars" and isinstance(node, ast.withitem))
                    or (field == "cases" and isinstance(node, ast.Match))
                ):
                    kid_owner = node
                elif field == "pattern" and isinstance(node, ast.match_case):
                    kid_owner = owner
                visit(kid, inner, kid_owner)

    visit(tree, None, None)
    return out


def _has_int(node: ast.AST | None) -> bool:
    return node is not None and any(
        isinstance(n, ast.Constant) and type(n.value) is int for n in ast.walk(node)
    )


def _stripped_int(value: ast.AST | None) -> bool:
    while isinstance(value, ast.UnaryOp):
        value = value.operand
    return isinstance(value, ast.Constant) and type(value.value) is int


def _makes_candidate(owner: ast.AST | None) -> bool:
    """Whether a binding owned by ``owner`` makes its name a bound candidate. A single-name
    assignment qualifies only when its value, with unary signs removed, is an exact int; that is
    the one exception to "any int literal in the statement", so ``MIN = 59 - 1`` is not found.
    Every other binding form qualifies when its value expression holds an exact int anywhere."""
    if isinstance(owner, ast.Assign):
        one_name = len(owner.targets) == 1 and isinstance(owner.targets[0], ast.Name)
        return _stripped_int(owner.value) if one_name else _has_int(owner.value)
    if isinstance(owner, ast.AnnAssign):
        return _stripped_int(owner.value)
    if isinstance(owner, (ast.AugAssign, ast.NamedExpr)):
        return _has_int(owner.value)
    if isinstance(owner, (ast.For, ast.AsyncFor)):
        return _has_int(owner.iter)
    if isinstance(owner, ast.withitem):
        return _has_int(owner.context_expr)
    if isinstance(owner, ast.Match):
        return _has_int(owner.subject)
    return False


def _plain_literal(value: ast.AST) -> int | None:
    """The int of ``<int>`` or ``-<int>``; ``None`` for a bool, ``+5``, ``--5``, ``~5`` or any
    other expression."""
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub):
        value, sign = value.operand, -1
    else:
        sign = 1
    if isinstance(value, ast.Constant) and type(value.value) is int:
        return sign * value.value
    return None


def _plain_value(owner: ast.AST | None, name: str) -> int | None:
    """The literal when ``owner`` is ``NAME = <lit>`` or ``NAME: int = <lit>`` for ``name``."""
    if isinstance(owner, ast.Assign):
        if len(owner.targets) == 1 and _is_name(owner.targets[0], name):
            return _plain_literal(owner.value)
    elif isinstance(owner, ast.AnnAssign):
        ann = owner.annotation
        if (
            owner.value is not None
            and _is_name(owner.target, name)
            and isinstance(ann, ast.Name)
            and ann.id == "int"
        ):
            return _plain_literal(owner.value)
    return None


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def int_constants(tree: ast.Module) -> dict[str, int | None]:
    """Each name that might be a module-level integer bound, with its value or ``None`` (refused).

    A name is a candidate when any counted binding qualifies (``_makes_candidate``). It reads as an
    int only when it has exactly one binding, that binding is a direct statement of the module
    body in the form ``NAME = <int>`` or ``NAME: int = <int>``, and the module has no wildcard
    import. Every other candidate is ``None``: the source is never evaluated, so a form this parser
    does not model fails closed instead of reading a wrong value. A bound whose literal sits in
    another statement (``MIN = OTHER``) is not a candidate. Discovery and live reads both call this.
    """
    bindings = _bindings(tree)
    wildcard = any(name == "*" for name, _ in bindings)
    direct = {id(stmt) for stmt in tree.body}
    candidates = {name for name, owner in bindings if _makes_candidate(owner)}
    out: dict[str, int | None] = {}
    for name in sorted(candidates):
        owners = [owner for n, owner in bindings if n == name]
        value = _plain_value(owners[0], name) if len(owners) == 1 else None
        plain = not wildcard and owners[0] is not None and id(owners[0]) in direct
        out[name] = value if plain else None
    return out


def read_int(source: str, constant: str) -> int:
    """The value of module-level ``NAME = <int>`` or ``NAME: int = <int>`` in ``source``, by ``ast``.

    Any other form raises ``ValueError`` with a fixed, value-free message: a second binding, a
    tuple or chained target, ``+=``, a loop, ``with`` or ``:=`` target, ``del``, an import, a
    ``def``, a rebind through ``global``, a ``match`` capture, a wildcard import, a bool, a
    non-literal or a missing name. The module is never imported. The caller reads the file: this
    package holds checker code, whose reads all go through ``_integrity``.
    """
    value = int_constants(ast.parse(source)).get(constant)
    if value is None:
        raise ValueError(f"{constant} {REFUSED}")
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
    imported = {id(alias) for _, alias in imports}
    rebound = [n for n in ast.walk(tree) if name in bound_names(n) and id(n) not in imported]
    if rebound:
        out.append(f"{name} is bound again in the importing module")
    for use in ast.walk(tree):
        if isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load):
            if not isinstance(parents.get(use), ast.Compare):
                out.append(f"{name} is used other than as a direct comparison operand")
    return out
