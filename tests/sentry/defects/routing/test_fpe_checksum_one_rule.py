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

ROOT = Path(__file__).resolve().parents[4] / "src" / "decoy_engine"
REJ = "execution/native/_operator_config_rejections.py"
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
    ("execution/native/_real_type_admission.py", "_fpe_checksum_decline"): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_config_reason"): "<forwarded>",
    ("execution/out_of_core/_fpe_native.py", "decline_reason"): "payload",
    ("execution/physical/_shadow_bindings.py", "execution_binding_for_slice_node"): "payload",
}
# The two sequential admission callers pin the context the shared helper receives.
CONTEXT_FORWARDERS: dict[Edge, str] = {
    ("execution/_sequential_native_ops.py", "_fpe_admit"): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_key_admit"): "key",
}


def _imports(tree: ast.Module) -> dict[str, str]:
    """Local name -> imported name, so an `as` alias still resolves to the real function."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out[alias.asname or alias.name] = alias.name
    return out


def _callee(call: ast.Call, names: dict[str, str]) -> str | None:
    if isinstance(call.func, ast.Name):
        return names.get(call.func.id, call.func.id)
    if isinstance(call.func, ast.Attribute):
        return names.get(call.func.attr, call.func.attr)
    return None


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


def callers(source: str, rel: str, function: str) -> list[tuple[Edge, str]]:
    """Calls to `function` as `(edge, context literal)`; a non-literal context reads
    `<forwarded>` and a missing one `<none>`."""
    tree = ast.parse(source)
    names = _imports(tree)
    out: list[tuple[Edge, str]] = []
    for scope, node in _scoped(tree):
        if isinstance(node, ast.Call) and _callee(node, names) == function:
            ctx = "<none>"
            for kw in node.keywords:
                if kw.arg == "context":
                    ctx = (
                        str(kw.value.value) if isinstance(kw.value, ast.Constant) else "<forwarded>"
                    )
            out.append(((rel, scope), ctx))
    return out


def context_forwarders(source: str, rel: str) -> list[tuple[Edge, str]]:
    """Calls to `_fpe_config_reason` with the literal context they pass."""
    tree = ast.parse(source)
    out: list[tuple[Edge, str]] = []
    for scope, node in _scoped(tree):
        if isinstance(node, ast.Call) and _callee(node, {}) == "_fpe_config_reason":
            ctx = "<none>"
            for kw in node.keywords:
                if kw.arg == "context" and isinstance(kw.value, ast.Constant):
                    ctx = str(kw.value.value)
            out.append(((rel, scope), ctx))
    return out


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


def test_decision_callers_are_the_adapter_and_the_wrapper() -> None:
    found: list[Edge] = []
    for rel, src in _sources():
        if _under_execution(rel):
            found += [edge for edge, _ctx in callers(src, rel, DECISION)]
    assert sorted(found) == sorted(DECISION_CALLERS), sorted(found)


def test_adapter_callers_are_the_route_sites_with_their_context() -> None:
    found: dict[Edge, str] = {}
    dupes: list[Edge] = []
    for rel, src in _sources():
        if not _under_execution(rel):
            continue
        for edge, ctx in callers(src, rel, ADAPTER):
            if edge in found:
                dupes.append(edge)
            found[edge] = ctx
    expected = {e: c for e, c in ADAPTER_CALLERS.items()}
    # the rejections module itself defines, never calls, the adapter
    assert found == expected and not dupes, (found, dupes)


def test_sequential_admission_callers_pin_payload_and_key_context() -> None:
    rel = "execution/_sequential_native_ops.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert dict(context_forwarders(src, rel)) == CONTEXT_FORWARDERS


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


def test_scanner_resolves_import_aliases_and_counts_a_second_call() -> None:
    src = (
        "from m import fpe_checksum_rejection as r\n"
        "def f():\n    r('c', 'luhn', '0', context='payload')\n"
        "    r('c', 'luhn', '0', context='payload')\n"
    )
    assert callers(src, "x.py", DECISION) == [
        (("x.py", "f"), "payload"),
        (("x.py", "f"), "payload"),
    ]


def test_a_second_read_inside_a_listed_function_changes_the_count() -> None:
    src = "def f(cfg):\n    a = cfg.get('checksum')\n    return cfg.get('checksum') or a\n"
    assert scheme_reads(src, "x.py")[("x.py", "f")] == 2
