"""K6 sentry: one fpe checksum rule (FPE-CHECKSUM-NATIVE).

Whether a checksum scheme runs on the compiled kernel is decided in one function,
`fpe_checksum_rejection`. This guard pins, by `(path, function)`:

- who reads the registry field `checksum_schemes` (only the decision);
- who reads the configured scheme under `execution/` and how many times (carriers forward it,
  nothing else branches on it);
- who calls the decision and the mapping adapter, and with which route context.

Any other edge fails, even inside an already listed function: the pinned count per function
catches a second read there. Imports and local aliases are normalized, so renaming a call or
reading through `getattr`, a subscript, a `.get`, or a bound alias is still seen.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from tests.sentry.defects._defect_scan import ModuleIndex, attr_chain, module_name

ROOT = Path(__file__).resolve().parents[4] / "src" / "decoy_engine"
REJ = "execution/native/_operator_config_rejections.py"
ADM = "execution/native/_real_type_admission.py"
CHUNKED = "_fpe_checksum_decline"
DECISION = "fpe_checksum_rejection"
ADAPTER = "fpe_checksum_config_rejection"
FIELD = "checksum_schemes"
SCHEME = "checksum"

Edge = tuple[str, str]

FIELD_READERS: dict[Edge, str] = {
    (REJ, DECISION): "the one decision",
}

# Every read of the configured scheme, with the number of reads in that function. A carrier
# forwards the scheme to its destination; none of them decides a route.
SCHEME_READS: dict[Edge, tuple[int, str]] = {
    ("execution/_strategies/_fpe.py", "FpeStrategyHandler.run"): (1, "oracle carrier"),
    ("execution/out_of_core/_mask_group_b.py", "fpe_array"): (1, "oracle carrier"),
    ("execution/native/_crypto_ext.py", "FpeConfig.from_mapping"): (1, "config carrier"),
    ("execution/native/_crypto_ext.py", "FpeConfig._resolve"): (1, "config carrier"),
    ("execution/native/_crypto_reference.py", "_ReferenceFpe._run"): (1, "oracle carrier"),
    ("execution/native/_operator_params.py", "resolve_operator_params"): (1, "params carrier"),
    ("execution/native/_fpe_route.py", "fpe_config_from_params"): (1, "params to config"),
    (REJ, ADAPTER): (1, "adapter reads the scheme once and forwards it"),
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): (1, "wrapper backstop"),
    ("execution/native/_fpe_ext.py", "load_compiled_fpe_kernel"): (
        1,
        "ordinary-FF1 load probe asserts no scheme (replaced by the shared probe in S2b)",
    ),
}

DECISION_CALLERS: dict[Edge, str] = {
    (REJ, ADAPTER): "adapter forwards scheme and charset",
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): "wrapper backstop, payload",
}

# (path, function) -> route context literal passed to the adapter.
ADAPTER_CALLERS: dict[Edge, str] = {
    (ADM, CHUNKED): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_config_reason"): "<forwarded>",
    ("execution/out_of_core/_fpe_native.py", "decline_reason"): "payload",
    ("execution/physical/_shadow_bindings.py", "execution_binding_for_slice_node"): "payload",
}
# The chunked admission wraps the adapter in `_fpe_checksum_decline`; its one caller must let the
# result govern the table's route.
CHUNKED_CALLERS: dict[Edge, str] = {(ADM, "real_type_decline"): "chunked decision"}

# Where the scheme and context go. Kinds: `last` = the last positional argument of a call to one
# of the names; `kw` = the `checksum=` keyword of any call; `arg1` = the second positional
# argument of the decision; `ctx` = `arg1` plus `context=<the function's own context parameter>`;
# `ret4` = the fourth item of the returned tuple.
DELIVERIES: dict[Edge, tuple[str, frozenset[str]]] = {
    ("execution/_strategies/_fpe.py", "FpeStrategyHandler.run.encrypt_one"): (
        "last",
        frozenset({"fpe_encrypt_value"}),
    ),
    ("execution/out_of_core/_mask_group_b.py", "fpe_array"): (
        "last",
        frozenset({"fpe_encrypt_value"}),
    ),
    ("execution/native/_crypto_reference.py", "_ReferenceFpe._run"): (
        "last",
        frozenset({"transform"}),
    ),
    ("execution/native/_crypto_ext.py", "FpeConfig.from_mapping"): ("kw", frozenset()),
    ("execution/native/_crypto_ext.py", "FpeConfig._resolve"): ("ret4", frozenset()),
    ("execution/native/_fpe_route.py", "fpe_config_from_params"): ("kw", frozenset()),
    ("execution/native/_operator_params.py", "resolve_operator_params"): ("kw", frozenset()),
    (REJ, ADAPTER): ("ctx", frozenset({DECISION})),
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): ("arg1", frozenset({DECISION})),
}

# The two sequential admission callers pin the context the shared helper receives.
CONTEXT_FORWARDERS: dict[Edge, str] = {
    ("execution/_sequential_native_ops.py", "_fpe_admit"): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_key_admit"): "key",
}


class Resolver:
    """Resolves a call's callee through the shared `ModuleIndex` import tables, so an alias, a
    package re-export or a module attribute still lands on the defining function."""

    def __init__(self, index: ModuleIndex) -> None:
        self.index = index
        self.defs: dict[str, set[str]] = {}
        for path, tree in index.trees.items():
            self.defs[module_name(path, index.src)] = {
                n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

    def follow(self, mod: str, name: str, depth: int = 0) -> tuple[str, str]:
        if name in self.defs.get(mod, ()) or depth > 8:
            return (mod, name)
        if (mod, name) in self.index.imports:
            base, original = self.index.imports[(mod, name)]
            return self.follow(base, original, depth + 1)
        return (mod, name)

    def module_of(self, mod: str, chain: list[str]) -> str | None:
        head = chain[0]
        if (mod, head) in self.index.module_aliases:
            dotted = self.index.module_aliases[(mod, head)]
        elif (mod, head) in self.index.imports:
            base, original = self.index.imports[(mod, head)]
            dotted = f"{base}.{original}"
        else:
            return None
        dotted = ".".join([dotted, *chain[1:]])
        return dotted if dotted in self.index.module_paths else None

    def callee(self, mod: str, call: ast.Call) -> tuple[str, str] | None:
        chain = attr_chain(call.func)
        if chain is None:
            return None
        if len(chain) == 1:
            return self.follow(mod, chain[0])
        owner = self.module_of(mod, chain[:-1])
        return self.follow(owner, chain[-1]) if owner else ("?", chain[-1])


def _mod(rel: str, index: ModuleIndex) -> str:
    return module_name(index.src / rel, index.src)


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
    of a name bound to the scheme slot of `_resolve()` (the fourth item)."""
    tree = ast.parse(source)
    out: Counter[Edge] = Counter()
    bound: dict[str, set[str]] = {}
    scoped = _scoped(tree)
    for scope, node in scoped:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "_resolve"
            and isinstance(node.targets[0], ast.Tuple)
            and len(node.targets[0].elts) == 4
            and isinstance(node.targets[0].elts[3], ast.Name)
        ):
            bound.setdefault(scope, set()).add(node.targets[0].elts[3].id)
    for scope, node in scoped:
        if _key_read(node, SCHEME):
            out[(rel, scope)] += 1
        elif isinstance(node, ast.Attribute) and node.attr == SCHEME:
            if isinstance(node.ctx, ast.Load):
                out[(rel, scope)] += 1
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in bound.get(scope, ())
        ):
            out[(rel, scope)] += 1
    return out


def callers(
    index: ModuleIndex, rel: str, tree: ast.Module, target: tuple[str, str]
) -> list[tuple[Edge, str, bool]]:
    """Calls whose final name is `target`'s, as `(edge, context literal, resolves to target)`.
    A same-named function elsewhere is listed with `False`, so a private copy is never hidden.
    A non-literal context reads `<forwarded>` and a missing one `<none>`."""
    res = Resolver(index)
    mod = _mod(rel, index)
    out: list[tuple[Edge, str, bool]] = []
    for scope, node in _scoped(tree):
        if not isinstance(node, ast.Call):
            continue
        found = res.callee(mod, node)
        if found is None or found[1] != target[1]:
            continue
        ctx = "<none>"
        for kw in node.keywords:
            if kw.arg == "context":
                ctx = str(kw.value.value) if isinstance(kw.value, ast.Constant) else "<forwarded>"
        out.append(((rel, scope), ctx, found == target))
    return out


def context_forwarders(index: ModuleIndex, rel: str, tree: ast.Module) -> list[tuple[Edge, str]]:
    """Calls to `_fpe_config_reason` with the literal context they pass."""
    res = Resolver(index)
    mod = _mod(rel, index)
    out: list[tuple[Edge, str]] = []
    for scope, node in _scoped(tree):
        if isinstance(node, ast.Call) and res.callee(mod, node) == (mod, "_fpe_config_reason"):
            ctx = "<none>"
            for kw in node.keywords:
                if kw.arg == "context" and isinstance(kw.value, ast.Constant):
                    ctx = str(kw.value.value)
            out.append(((rel, scope), ctx))
    return out


def _tests_of(node: ast.AST) -> bool:
    """True when the branch taken on a test ends the function: it returns or raises."""
    return any(
        isinstance(n, (ast.Return, ast.Raise))
        for b in getattr(node, "body", ())
        for n in ast.walk(b)
    )


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _contains(root: ast.AST, node: ast.AST) -> bool:
    return any(n is node for n in ast.walk(root))


def _loads(expr: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id in names and isinstance(n.ctx, ast.Load)
        for n in ast.walk(expr)
    )


def _result_governs(tree: ast.Module, call: ast.Call) -> bool:
    """The call's result decides a route or refusal: it is returned, tested by an `if` whose
    branch returns or raises, or bound to a name that is. A bare call or an unused binding fails."""
    parents = _parents(tree)
    node: ast.AST = call
    while node in parents:
        parent = parents[node]
        if isinstance(parent, ast.Return):
            return True
        if isinstance(parent, ast.If) and _contains(parent.test, call):
            return _tests_of(parent)
        if isinstance(parent, (ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            fn: ast.AST = parent
            while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parents[fn]
            for sub in ast.walk(fn):
                if isinstance(sub, ast.If) and _loads(sub.test, names) and _tests_of(sub):
                    return True
                if (
                    isinstance(sub, ast.Return)
                    and sub.value is not None
                    and _loads(sub.value, names)
                ):
                    return True
            return False
        node = parent
    return False


def ungoverned_calls(
    index: ModuleIndex, target: tuple[str, str], under: str = "execution/"
) -> list[Edge]:
    """Every call of `target` whose result does not govern the outcome."""
    out: list[Edge] = []
    for rel, tree in _trees(index):
        if not rel.startswith(under):
            continue
        res = Resolver(index)
        mod = _mod(rel, index)
        scopes = {id(n): sc for sc, n in _scoped(tree)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (found := res.callee(mod, node)) is not None:
                if found[1] == target[1] and not _result_governs(tree, node):
                    out.append((rel, scopes.get(id(node), "")))
    return out


def _trees(index: ModuleIndex) -> list[tuple[str, ast.Module]]:
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


def _bound_scheme_names(tree: ast.Module, scope: str) -> set[str]:
    """Names only ever assigned the configured scheme (a key read or the fourth `_resolve()` item)
    in `scope`, its nested functions and the functions that enclose it. A class field of the same
    name is not an assignment in that function."""
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
            elif isinstance(target, ast.Tuple) and len(target.elts) == 4:
                last = target.elts[3]
                from_resolve = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "_resolve"
                )
                if isinstance(last, ast.Name):
                    (good if from_resolve else bad).add(last.id)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            bad.add(node.target.id)
    return good - bad


def delivery_violations(
    index: ModuleIndex, table: dict[Edge, tuple[str, frozenset[str]]]
) -> list[str]:
    """Each pinned carrier hands the configured scheme (and context) to its declared destination.
    `None`, a constant or any other expression in that position is a violation."""
    problems: list[str] = []
    trees = dict(_trees(index))
    for (rel, scope), (kind, names) in sorted(table.items()):
        tree = trees.get(rel)
        if tree is None:
            problems.append(f"{rel}: missing")
            continue
        bound = _bound_scheme_names(tree, scope)
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
                    kws = [k for k in node.keywords if k.arg == SCHEME]
                    sites += [_scheme_expr(k.value, bound) for k in kws]
                elif final in names and kind == "last":
                    sites.append(bool(node.args) and _scheme_expr(node.args[-1], bound))
                elif final in names:
                    ok = len(node.args) > 1 and _scheme_expr(node.args[1], bound)
                    if kind == "ctx":
                        ctx = {k.arg: k.value for k in node.keywords}.get("context")
                        ok = ok and isinstance(ctx, ast.Name) and ctx.id == "context"
                    sites.append(ok)
        if not sites or not all(sites):
            problems.append(f"{rel}::{scope}: scheme not delivered to its destination")
    return problems


def text_mask_restriction_pinned(source: str) -> bool:
    """`NATIVE_FPE_DETECTORS` keeps only digit detectors with no checksum scheme (until S3)."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id != "NATIVE_FPE_DETECTORS":
                continue
            for gen in ast.walk(node.value) if node.value else ():
                if isinstance(gen, ast.GeneratorExp):
                    conds = [c for g in gen.generators for i in g.ifs for c in ast.walk(i)]
                    no_scheme = any(
                        isinstance(c, ast.Compare)
                        and isinstance(c.left, ast.Name)
                        and c.left.id == "checksum"
                        and isinstance(c.ops[0], ast.Is)
                        and isinstance(c.comparators[0], ast.Constant)
                        and c.comparators[0].value is None
                        for c in conds
                    )
                    digits = any(
                        isinstance(c, ast.Compare)
                        and isinstance(c.left, ast.Name)
                        and c.left.id == "charset"
                        and isinstance(c.ops[0], ast.Eq)
                        and isinstance(c.comparators[0], ast.Constant)
                        and c.comparators[0].value == "digits"
                        for c in conds
                    )
                    return no_scheme and digits
    return False


def _sources() -> list[tuple[str, str]]:
    return [
        (p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted(ROOT.rglob("*.py"))
    ]


def _under_execution(rel: str) -> bool:
    return rel.startswith("execution/")


def test_only_the_decision_reads_the_registry_field() -> None:
    found: Counter[Edge] = Counter()
    for rel, src in _sources():
        found += field_readers(src, rel)
    assert set(found) == set(FIELD_READERS), sorted(found)
    assert found[(REJ, DECISION)] == 1, "one read, in the decision"


def test_scheme_reads_match_the_pinned_carriers() -> None:
    found: Counter[Edge] = Counter()
    for rel, src in _sources():
        if _under_execution(rel):
            found += scheme_reads(src, rel)
    pinned = Counter({edge: n for edge, (n, _why) in SCHEME_READS.items()})
    assert found == pinned, {
        "unexpected_or_changed": sorted((found - pinned).items()),
        "missing": sorted((pinned - found).items()),
    }


@pytest.fixture(scope="module")
def index() -> ModuleIndex:
    return ModuleIndex(ROOT)


def _call_sites(index: ModuleIndex, rel_target: str, name: str) -> list[tuple[Edge, str, bool]]:
    target = (_mod(rel_target, index), name)
    out: list[tuple[Edge, str, bool]] = []
    for rel, tree in _trees(index):
        if _under_execution(rel):
            out += callers(index, rel, tree, target)
    return out


def test_decision_callers_are_the_adapter_and_the_wrapper(index: ModuleIndex) -> None:
    sites = _call_sites(index, REJ, DECISION)
    assert sorted(e for e, _c, _x in sites) == sorted(DECISION_CALLERS), sites
    assert all(exact for _e, _c, exact in sites), "a private copy of the decision"


def test_adapter_callers_are_the_route_sites_with_their_context(index: ModuleIndex) -> None:
    sites = _call_sites(index, REJ, ADAPTER)
    found = {e: c for e, c, _x in sites}
    # the rejections module itself defines, never calls, the adapter
    assert found == ADAPTER_CALLERS and len(found) == len(sites), sites
    assert all(exact for _e, _c, exact in sites), "a private copy of the adapter"


def test_the_chunked_wrapper_has_one_caller(index: ModuleIndex) -> None:
    sites = _call_sites(index, ADM, CHUNKED)
    assert sorted(e for e, _c, _x in sites) == sorted(CHUNKED_CALLERS), sites
    assert all(exact for _e, _c, exact in sites)


def test_every_decision_result_governs_its_route_or_refusal(index: ModuleIndex) -> None:
    targets = [(REJ, DECISION), (REJ, ADAPTER), (ADM, CHUNKED)]
    found = {
        (rel, name): ungoverned_calls(index, (_mod(rel, index), name)) for rel, name in targets
    }
    assert found == {t: [] for t in targets}, found


def test_the_scheme_and_context_reach_each_destination(index: ModuleIndex) -> None:
    assert delivery_violations(index, DELIVERIES) == []


def test_text_mask_detector_restriction_is_pinned_until_s3() -> None:
    rel = "execution/native/_text_mask_native_fpe.py"
    assert text_mask_restriction_pinned((ROOT / rel).read_text(encoding="utf-8"))


def test_sequential_admission_callers_pin_payload_and_key_context(index: ModuleIndex) -> None:
    rel = "execution/_sequential_native_ops.py"
    tree = dict(_trees(index))[rel]
    assert dict(context_forwarders(index, rel, tree)) == CONTEXT_FORWARDERS


# Seeded spellings: each must be seen by the scanner it targets.


def test_scanner_sees_every_registry_field_spelling() -> None:
    spellings = [
        "def f(spec):\n    return spec.checksum_schemes\n",
        "def f(spec):\n    return getattr(spec, 'checksum_schemes')\n",
        "def f(spec):\n    return vars(spec)['checksum_schemes']\n",
        "def f(spec):\n    return spec.__dict__.get('checksum_schemes')\n",
        "def f():\n    s = OPERATORS['fpe']\n    return s.checksum_schemes\n",
    ]
    for src in spellings:
        assert field_readers(src, "x.py"), src
    declared = (
        "class A:\n    checksum_schemes: frozenset[str] = frozenset()\nA(checksum_schemes=1)\n"
    )
    assert not field_readers(declared, "x.py")


def test_scanner_sees_every_scheme_read_spelling() -> None:
    spellings = [
        "def f(cfg):\n    return cfg.get('checksum')\n",
        "def f(cfg):\n    return cfg['checksum']\n",
        "def f(p):\n    return p.checksum\n",
        "def f(cfg):\n    return getattr(cfg, 'checksum', None)\n",
        "def f(c):\n    a, b, d, e = c._resolve()\n    return e\n",
    ]
    for src in spellings:
        assert scheme_reads(src, "x.py"), src


def _seeded(tmp_path: Path, files: dict[str, str]) -> ModuleIndex:
    """A throwaway `decoy_engine` tree, so a bypass is scanned without touching real source."""
    root = tmp_path / "decoy_engine"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return ModuleIndex(root)


_GOOD_ORACLE = (
    "def f(cfg, v):\n"
    "    checksum = cfg.get('checksum') or None\n"
    "    return fpe_encrypt_value(v, 1, 2, 3, 4, 5, checksum)\n"
)
_ORACLE_EDGE: dict[Edge, tuple[str, frozenset[str]]] = {
    ("execution/o.py", "f"): ("last", frozenset({"fpe_encrypt_value"}))
}


def test_delivery_accepts_the_configured_scheme(tmp_path: Path) -> None:
    index = _seeded(tmp_path, {"execution/o.py": _GOOD_ORACLE})
    assert delivery_violations(index, _ORACLE_EDGE) == []


@pytest.mark.parametrize(
    "tail",
    [
        "    return fpe_encrypt_value(v, 1, 2, 3, 4, 5, None)\n",
        "    checksum = None\n    return fpe_encrypt_value(v, 1, 2, 3, 4, 5, checksum)\n",
        "    return fpe_encrypt_value(v, 1, 2, 3, 4, 5, 'luhn')\n",
    ],
    ids=["none-literal", "rebound-to-none", "constant"],
)
def test_delivery_rejects_a_scheme_replaced_before_the_oracle_transform(
    tmp_path: Path, tail: str
) -> None:
    src = "def f(cfg, v):\n    checksum = cfg.get('checksum') or None\n" + tail
    index = _seeded(tmp_path, {"execution/o.py": src})
    assert delivery_violations(index, _ORACLE_EDGE)


def test_delivery_rejects_a_dropped_context_and_a_missing_destination(tmp_path: Path) -> None:
    table = {("execution/r.py", "adapter"): ("ctx", frozenset({DECISION}))}
    ok = (
        "def adapter(column, cfg, *, context):\n"
        "    scheme = cfg.get('checksum') or None\n"
        "    return fpe_checksum_rejection(column, scheme, 'x', context=context)\n"
    )
    assert delivery_violations(_seeded(tmp_path, {"execution/r.py": ok}), table) == []
    for bad in (ok.replace("context=context", "context='payload'"), "def adapter():\n    pass\n"):
        idx = _seeded(tmp_path / "bad", {"execution/r.py": bad})
        assert delivery_violations(idx, table), bad


_DECISION_DEF = "def fpe_checksum_config_rejection(c, p, *, context):\n    return None\n"


def _governed_case(tmp_path: Path, body: str) -> list[Edge]:
    files = {
        "execution/native/_operator_config_rejections.py": _DECISION_DEF,
        "execution/native/__init__.py": (
            "from ._operator_config_rejections import fpe_checksum_config_rejection as adapter\n"
        ),
        "execution/route.py": (
            "from decoy_engine.execution.native import adapter as ask\ndef route(c, p):\n" + body
        ),
    }
    target = (
        "decoy_engine.execution.native._operator_config_rejections",
        "fpe_checksum_config_rejection",
    )
    return ungoverned_calls(_seeded(tmp_path, files), target)


@pytest.mark.parametrize(
    "body",
    [
        "    return ask(c, p, context='payload')\n",
        "    r = ask(c, p, context='payload')\n    if r is not None:\n        return r\n    return None\n",
        "    if ask(c, p, context='payload') is not None:\n        raise ValueError('x')\n",
    ],
    ids=["returned", "bound-then-tested", "tested-inline"],
)
def test_a_result_that_governs_the_outcome_is_accepted(tmp_path: Path, body: str) -> None:
    assert _governed_case(tmp_path, body) == []


@pytest.mark.parametrize(
    "body",
    [
        "    ask(c, p, context='payload')\n    return None\n",
        "    r = ask(c, p, context='payload')\n    return None\n",
        "    r = ask(c, p, context='payload')\n    if r is not None:\n        pass\n    return None\n",
    ],
    ids=["discarded", "bound-unused", "tested-no-exit"],
)
def test_a_discarded_decision_result_is_rejected(tmp_path: Path, body: str) -> None:
    assert _governed_case(tmp_path, body) == [("execution/route.py", "route")]


def test_an_import_alias_and_a_private_copy_are_told_apart(tmp_path: Path) -> None:
    files = {
        "execution/native/_operator_config_rejections.py": _DECISION_DEF,
        "execution/native/__init__.py": (
            "from ._operator_config_rejections import fpe_checksum_config_rejection\n"
        ),
        "execution/a.py": (
            "from decoy_engine.execution.native import fpe_checksum_config_rejection as r\n"
            "def f():\n    return r('c', {}, context='payload')\n"
        ),
        "execution/b.py": (
            "def fpe_checksum_config_rejection(c, p, *, context):\n    return None\n"
            "def g():\n    return fpe_checksum_config_rejection('c', {}, context='payload')\n"
        ),
    }
    index = _seeded(tmp_path, files)
    target = (
        "decoy_engine.execution.native._operator_config_rejections",
        "fpe_checksum_config_rejection",
    )
    seen = {
        e: exact
        for rel, tree in _trees(index)
        for e, _c, exact in callers(index, rel, tree, target)
    }
    assert seen == {("execution/a.py", "f"): True, ("execution/b.py", "g"): False}


def test_the_text_mask_restriction_check_sees_a_dropped_clause() -> None:
    kept = (
        "NATIVE_FPE_DETECTORS: frozenset[str] = frozenset(\n"
        "    d for d, (charset, checksum) in _FPE_CONFIG.items()\n"
        "    if checksum is None and charset == 'digits'\n)\n"
    )
    assert text_mask_restriction_pinned(kept)
    assert not text_mask_restriction_pinned(kept.replace("checksum is None and ", ""))
    assert not text_mask_restriction_pinned(kept.replace(" and charset == 'digits'", ""))


def test_a_second_read_inside_a_listed_function_changes_the_count() -> None:
    src = "def f(cfg):\n    a = cfg.get('checksum')\n    return cfg.get('checksum') or a\n"
    assert scheme_reads(src, "x.py")[("x.py", "f")] == 2
