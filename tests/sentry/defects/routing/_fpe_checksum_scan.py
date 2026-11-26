"""Scanner for the K6 fpe checksum sentry: AST readers, call resolution and delivery checks.

The pins and the guard tests live in `test_fpe_checksum_one_rule.py`.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from tests.sentry._call_resolution import local_names
from tests.sentry.defects._defect_scan import ModuleIndex, attr_chain

ROOT = Path(__file__).resolve().parents[4] / "src" / "decoy_engine"
REJ = "execution/native/_operator_config_rejections.py"
ADM = "execution/native/_real_type_admission.py"
CHUNKED = "_fpe_checksum_decline"
DECISION = "fpe_checksum_rejection"
ADAPTER = "fpe_checksum_config_rejection"
FIELD = "checksum_schemes"
SCHEME = "checksum"
FPE_CONFIG = "_FPE_CONFIG"

Edge = tuple[str, str]

# `transform` is the oracle's local `encrypt if forward else decrypt`.
DEST_ALIAS: dict[str, str] = {"transform": "fpe_encrypt_value"}


def _is_str(node: ast.AST | None, value: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _scoped(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Every node with its qualified enclosing function (empty string at module scope)."""
    out: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = (*scope, child.name)
            out.append((".".join(scope), child))
            visit(child, inner)

    visit(tree, ())
    return out


def _key_read(node: ast.AST, key: str) -> bool:
    """`x[key]`, `x.get(key)`, `x.pop(key)`, `x.setdefault(key)`, `getattr(x, key)`."""
    if isinstance(node, ast.Subscript):
        return _is_str(node.slice, key)
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("get", "pop", "setdefault"):
            return bool(node.args) and _is_str(node.args[0], key)
        if isinstance(f, ast.Name) and f.id == "getattr":
            return len(node.args) >= 2 and _is_str(node.args[1], key)
    return False


def field_readers(source: str, rel: str) -> Counter[Edge]:
    """Reads of the registry field. Class fields and constructor keywords are not reads."""
    out: Counter[Edge] = Counter()
    for scope, node in _scoped(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == FIELD:
            if isinstance(node.ctx, ast.Load):
                out[(rel, scope)] += 1
        elif _key_read(node, FIELD):
            out[(rel, scope)] += 1
    return out


def scheme_reads(source: str, rel: str) -> Counter[Edge]:
    """Reads of the configured scheme: a mapping key read, a `.checksum` attribute, and any use
    of a name `bound_scheme_names` says carries it, including a nested function that captures
    the name from its enclosing function."""
    tree = ast.parse(source)
    out: Counter[Edge] = Counter()
    bound: dict[str, set[str]] = {}
    for scope, node in _scoped(tree):
        if _key_read(node, SCHEME):
            out[(rel, scope)] += 1
        elif isinstance(node, ast.Attribute) and node.attr == SCHEME:
            if isinstance(node.ctx, ast.Load):
                out[(rel, scope)] += 1
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if scope not in bound:
                bound[scope] = bound_scheme_names(tree, scope)
            if node.id in bound[scope]:
                out[(rel, scope)] += 1
    return out


def callers(rel: str, tree: ast.Module, target: str) -> list[tuple[Edge, str]]:
    """Calls of `target` under any local spelling (import alias, assignment alias, attribute),
    as `(edge, context literal)`. A non-literal context reads `<forwarded>`, a missing one
    `<none>`."""
    names = local_names(tree, target)
    out: list[tuple[Edge, str]] = []
    for scope, node in _scoped(tree):
        if isinstance(node, ast.Call) and _is_call_of(node, names, target):
            ctx = "<none>"
            for kw in node.keywords:
                if kw.arg == "context":
                    ctx = (
                        str(kw.value.value) if isinstance(kw.value, ast.Constant) else "<forwarded>"
                    )
            out.append(((rel, scope), ctx))
    return out


def _is_call_of(call: ast.Call, names: set[str], target: str) -> bool:
    f = call.func
    return (isinstance(f, ast.Name) and f.id in names) or (
        isinstance(f, ast.Attribute) and f.attr == target
    )


def context_forwarders(rel: str, tree: ast.Module) -> list[tuple[Edge, str]]:
    """Calls to `_fpe_config_reason` with the literal context they pass."""
    names = local_names(tree, "_fpe_config_reason")
    out: list[tuple[Edge, str]] = []
    for scope, node in _scoped(tree):
        if isinstance(node, ast.Call) and _is_call_of(node, names, "_fpe_config_reason"):
            literal = {k.arg: k.value for k in node.keywords}.get("context")
            out.append(
                (
                    (rel, scope),
                    str(literal.value) if isinstance(literal, ast.Constant) else "<none>",
                )
            )
    return out


def defining_modules(index: ModuleIndex, name: str) -> list[str]:
    """Every module under `execution/` that defines a function called `name`, so a private
    copy of the decision, the adapter or the chunked wrapper is a failure of its own."""
    return sorted(
        rel
        for rel, tree in trees(index)
        if rel.startswith("execution/")
        and any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
            for n in ast.walk(tree)
        )
    )


def _admits(value: ast.AST | None) -> bool:
    """A returned value that means "no refusal": nothing, `None`, or a tuple of only `None`."""
    if value is None or (isinstance(value, ast.Constant) and value.value is None):
        return True
    return isinstance(value, ast.Tuple) and all(_admits(e) for e in value.elts)


def _branch_outcome_ok(branch: ast.If, outcome: str) -> bool:
    """What the refusal branch does: `raise`, return a reason (`value`), or return `None`."""
    exits = [n for b in branch.body for n in ast.walk(b) if isinstance(n, (ast.Return, ast.Raise))]
    returns = [n for n in exits if isinstance(n, ast.Return)]
    if outcome == "raise":
        return any(isinstance(n, ast.Raise) for n in exits)
    if not returns:
        return False
    if outcome == "none":
        return all(_admits(r.value) for r in returns)
    return all(not _admits(r.value) for r in returns)


def _mentions(expr: ast.AST, call: ast.Call, names: set[str]) -> bool:
    return any(
        n is call or (isinstance(n, ast.Name) and n.id in names and isinstance(n.ctx, ast.Load))
        for n in ast.walk(expr)
    )


def _polarity_ok(test: ast.AST, call: ast.Call, names: set[str]) -> bool:
    """The branch runs when a refusal exists: no `is None` / `== None` / `not` on the result."""
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and _mentions(n.left, call, names):
            if any(isinstance(op, (ast.Is, ast.Eq)) for op in n.ops):
                return False
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and _mentions(n, call, names):
            return False
    return True


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _contains(root: ast.AST, node: ast.AST) -> bool:
    return any(n is node for n in ast.walk(root))


def _inside_if(parents: dict[ast.AST, ast.AST], node: ast.AST, stop: ast.AST) -> bool:
    """A conditional return is judged by its `if`, not as a return of the bound result."""
    while node in parents and node is not stop:
        node = parents[node]
        if isinstance(node, ast.If):
            return True
    return False


def _result_governs(tree: ast.Module, call: ast.Call, outcome: str) -> bool:
    """The call's result decides the outcome: it is returned, or an `if` on it (directly or
    through the name it is bound to) refuses on a reason and takes the pinned `outcome`.
    A bare call, an unused binding, a reversed test or a branch that admits fails."""
    parents = _parents(tree)
    node: ast.AST = call
    while node in parents:
        parent = parents[node]
        if isinstance(parent, ast.Return):
            return True
        if isinstance(parent, ast.If) and _contains(parent.test, call):
            return _polarity_ok(parent.test, call, set()) and _branch_outcome_ok(parent, outcome)
        if isinstance(parent, (ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            fn: ast.AST = parent
            while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parents[fn]
            for sub in ast.walk(fn):
                if isinstance(sub, ast.If) and _mentions(sub.test, call, names):
                    if _polarity_ok(sub.test, call, names) and _branch_outcome_ok(sub, outcome):
                        return True
                if isinstance(sub, ast.Return) and sub.value is not None:
                    if _mentions(sub.value, call, names) and not _inside_if(parents, sub, fn):
                        return True
            return False
        node = parent
    return False


def ungoverned_calls(
    index: ModuleIndex,
    target: str,
    outcomes: dict[Edge, str] | None = None,
    under: str = "execution/",
) -> list[Edge]:
    """Every call of `target` whose result does not govern the pinned outcome."""
    out: list[Edge] = []
    for rel, tree in trees(index):
        if not rel.startswith(under):
            continue
        names = local_names(tree, target)
        scopes = {id(n): sc for sc, n in _scoped(tree)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_call_of(node, names, target):
                edge = (rel, scopes.get(id(node), ""))
                if not _result_governs(tree, node, (outcomes or {}).get(edge, "value")):
                    out.append(edge)
    return out


def trees(index: ModuleIndex) -> list[tuple[str, ast.Module]]:
    return [(p.relative_to(index.src).as_posix(), t) for p, t in index.trees.items()]


def _scheme_expr(node: ast.AST | None, bound: set[str]) -> bool:
    """The configured scheme itself: a bound name, `.checksum`, a key read, or `<scheme> or None`."""
    if isinstance(node, ast.Name):
        return node.id in bound
    if isinstance(node, ast.Attribute):
        return node.attr == SCHEME and isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _scheme_expr(node.values[0], bound) and all(
            _scheme_expr(v, bound) or (isinstance(v, ast.Constant) and v.value is None)
            for v in node.values[1:]
        )
    return node is not None and _key_read(node, SCHEME)


def _function_scopes(tree: ast.Module) -> set[str]:
    return {
        f"{sc}.{n.name}".lstrip(".")
        for sc, n in _scoped(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _is_resolve_call(value: ast.AST | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "_resolve"
    )


def _is_fpe_config_row(value: ast.AST | None) -> bool:
    """`_FPE_CONFIG[detector_id]`: the text-mask registry row `(charset, checksum)`."""
    return (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and value.value.id == FPE_CONFIG
    )


def bound_scheme_names(tree: ast.Module, scope: str) -> set[str]:
    """The one answer to "which names carry the configured scheme" in `scope`: the function
    itself, its nested functions and the functions that enclose it (a closure captures the name).
    A name counts when every assignment to it is the scheme (a key read, `.checksum`,
    `<scheme> or None`), the fourth item of `_resolve()`, or the second item of an
    `_FPE_CONFIG[...]` row. A class field of the same name is not an assignment in a function."""
    funcs = _function_scopes(tree)
    good: set[str] = set()
    bad: set[str] = set()
    for sc, node in _scoped(tree):
        if not (
            sc == scope
            or sc.startswith(scope + ".")
            or (scope.startswith(sc + ".") and sc in funcs)
        ):
            continue
        pairs: list[tuple[ast.AST, ast.AST | None]] = []
        if isinstance(node, ast.Assign):
            pairs = [(t, node.value) for t in node.targets]
        elif isinstance(node, ast.AnnAssign):
            pairs = [(node.target, node.value)]
        for target, value in pairs:
            if isinstance(target, ast.Name):
                (good if _scheme_expr(value, set()) else bad).add(target.id)
            elif isinstance(target, ast.Tuple):
                n = len(target.elts)
                last = target.elts[-1] if n else None
                carries = (n == 4 and _is_resolve_call(value)) or (
                    n == 2 and _is_fpe_config_row(value)
                )
                for elt in target.elts[:-1]:
                    if isinstance(elt, ast.Name):
                        bad.add(elt.id)
                if isinstance(last, ast.Name):
                    (good if carries else bad).add(last.id)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            bad.add(node.target.id)
    return good - bad


def _positional_params(index: ModuleIndex, fname: str) -> tuple[list[str], list[str]] | None:
    """`(positional parameter names, every parameter name)` of the function `fname`."""
    for _rel, tree in trees(index):
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
                a = node.args
                pos = [x.arg for x in (*a.posonlyargs, *a.args)]
                return pos, [*pos, *(x.arg for x in a.kwonlyargs)]
    return None


def _bound_arg(index: ModuleIndex, call: ast.Call, fname: str, param: str) -> ast.AST | None:
    """The expression a call binds to `param` of `fname`: by keyword, or by that parameter's
    position in the `def`. Absent, or not resolvable (a starred argument), reads `None`."""
    for kw in call.keywords:
        if kw.arg == param:
            return kw.value
    params = _positional_params(index, fname)
    if (
        params is None
        or param not in params[0]
        or any(isinstance(a, ast.Starred) for a in call.args)
    ):
        return None
    i = params[0].index(param)
    return call.args[i] if i < len(call.args) else None


def delivery_violations(
    index: ModuleIndex, table: dict[Edge, tuple[str, frozenset[str]]]
) -> list[str]:
    """Each pinned carrier hands the configured scheme (and context) to the destination
    parameter it is meant for. `None`, a constant, another expression, or the scheme landing in
    a neighbouring parameter is a violation."""
    problems: list[str] = []
    parsed = dict(trees(index))
    for (rel, scope), (kind, names) in sorted(table.items()):
        tree = parsed.get(rel)
        if tree is None:
            problems.append(f"{rel}: missing")
            continue
        bound = bound_scheme_names(tree, scope)
        sites: list[bool] = []
        for sc, node in _scoped(tree):
            if sc != scope:
                continue
            if kind == "ret4":
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                    sites.append(
                        len(node.value.elts) == 4 and _scheme_expr(node.value.elts[3], bound)
                    )
            elif isinstance(node, ast.Call):
                chain = attr_chain(node.func)
                final = chain[-1] if chain else None
                if kind == "kw":
                    sites += [
                        _scheme_expr(k.value, bound) for k in node.keywords if k.arg == SCHEME
                    ]
                elif final in names and kind == "bind":
                    dest = DEST_ALIAS.get(final, final)
                    sites.append(_scheme_expr(_bound_arg(index, node, dest, SCHEME), bound))
                elif final in names:
                    ok = _scheme_expr(_bound_arg(index, node, final, "scheme"), bound)
                    if kind == "ctx":
                        ctx = _bound_arg(index, node, final, "context")
                        ok = ok and isinstance(ctx, ast.Name) and ctx.id == "context"
                    sites.append(ok)
        if not sites or not all(sites):
            problems.append(f"{rel}::{scope}: scheme not delivered to its destination")
    return problems


def _conjuncts(expr: ast.AST) -> list[ast.AST]:
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.And):
        return [c for v in expr.values for c in _conjuncts(v)]
    return [expr]


def _compares(c: ast.AST, name: str, op: type, value: object) -> bool:
    return (
        isinstance(c, ast.Compare)
        and isinstance(c.left, ast.Name)
        and c.left.id == name
        and len(c.ops) == 1
        and isinstance(c.ops[0], op)
        and isinstance(c.comparators[0], ast.Constant)
        and c.comparators[0].value == value
    )


def text_mask_restriction_pinned(source: str) -> bool:
    """`NATIVE_FPE_DETECTORS` keeps a detector only when BOTH hold, as separate AND conditions:
    its scheme is `None` and its charset is `digits` (until S3). An `or`, a `not`, or either
    test missing admits PAN or NPI to the plain kernel."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id != "NATIVE_FPE_DETECTORS" or node.value is None:
                continue
            for gen in ast.walk(node.value):
                if isinstance(gen, ast.GeneratorExp):
                    conds = [c for g in gen.generators for i in g.ifs for c in _conjuncts(i)]
                    return any(_compares(c, "checksum", ast.Is, None) for c in conds) and any(
                        _compares(c, "charset", ast.Eq, "digits") for c in conds
                    )
    return False


def sources() -> list[tuple[str, str]]:
    return [
        (p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted(ROOT.rglob("*.py"))
    ]


def under_execution(rel: str) -> bool:
    return rel.startswith("execution/")
