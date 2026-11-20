"""One reader of a nested column's child strategy and config (F07 choke point).

A `nested` column keeps its child under `provider_config.strategy` and `.strategy_config`. A module
that tests a strategy against `"nested"` and then reads those keys itself would miss the `rules`
form 82-E3b adds, and skip a plan refusal for it. Every such module must call `nested_children`
from `decoy_engine._nested_json`, which is the only reader.

A module is in scope when it has a `"nested"` literal in a comparison
(`==`, `!=`, `in`, `not in`) or as a dict key (`"nested"` or a prefixed key such as
`"scalar:nested"`). In scope, a child read is `.get("strategy")` or `["strategy"]` off a provider-config
derived value (see `direct_child_reads`), or `.get("strategy_config")` or `["strategy_config"]`. Enforcement is per read: every direct read is flagged, also in a module that calls
`nested_children` elsewhere. A module that reads the child must go through `nested_children`
for all of it. Registries that name `"nested"` in a set or table without reading the child
(for example `validators/_leak_check.py`) have no comparison or key, so the shape does not match
them. Deliberate evasion (`getattr`, a key built at run time) is not modelled.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._call_resolution import resolved_calls
from tests.sentry.defects import _defect_scan as scan

OWNER = "_nested_json/_rules.py"
# The seven modules that read a nested child at the slice base; each must call the choke point.
READERS = (
    "execution/_column_access.py",
    "execution/_pipeline_multi_table.py",
    "execution/_strategies/nested/_handler.py",
    "plan/_checks_bucket_perturb.py",
    "plan/_checks_date_shift.py",
    "plan/_checks_top_code.py",
    "secret_providers/_requirements.py",
)


def _is_nested(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "nested"


def _is_nested_key(node: ast.AST | None) -> bool:
    """A dict key for the strategy: `"nested"`, or a prefixed registry key like `"scalar:nested"`."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == "nested" or node.value.endswith(":nested"))
    )


def _names_nested(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                if _is_nested(side):
                    return True
                if isinstance(side, (ast.Tuple, ast.List, ast.Set)) and any(
                    _is_nested(e) for e in side.elts
                ):
                    return True
        if isinstance(node, ast.Dict) and any(_is_nested_key(k) for k in node.keys):
            return True
    return False


def _const_key(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _own_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node of one scope: a function body without the bodies of functions nested in it."""
    found: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        found.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))
    return found


def _derived(node: ast.AST, names: set[str]) -> bool:
    """Whether an expression is a provider config, or a part of one, by where it comes from."""
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Subscript):
        return _const_key(node.slice) == "provider_config" or _derived(node.value, names)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get" and node.args and _const_key(node.args[0]) == "provider_config":
            return True
        if node.func.attr in ("get", "values", "items", "keys", "copy", "pop"):
            return _derived(node.func.value, names)
    if isinstance(node, ast.BoolOp):
        return any(_derived(v, names) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _derived(node.body, names) or _derived(node.orelse, names)
    return False


def _target_names(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _scope_names(scope: ast.AST, seeded: set[str]) -> set[str]:
    """Names in one scope bound to a derived value: assigned from one, or iterated over one."""
    names = set(seeded)
    nodes = _own_nodes(scope)
    grew = True
    while grew:
        grew = False
        for node in nodes:
            bound: set[str] = set()
            if isinstance(node, ast.Assign) and _derived(node.value, names):
                for target in node.targets:
                    bound |= _target_names(target)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and _derived(
                node.iter, names
            ):
                bound = _target_names(node.target)
            if not bound <= names:
                names |= bound
                grew = True
    return names


def _params(func: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> list[str]:
    args = [*func.args.posonlyargs, *func.args.args]
    if is_method and args:
        args = args[1:]
    return [a.arg for a in args]


def direct_child_reads(tree: ast.AST) -> list[int]:
    """Lines that read a nested child key straight off a provider config.

    A read is `.get("strategy")`, `["strategy"]` or the same for `strategy_config`. It counts
    when its receiver is provider-config derived: a `["provider_config"]` subscript or
    `.get("provider_config")` call (inline counts), a name assigned from or iterated over such
    a value (aliases, `.values()`, `.items()`, comprehension targets), or a parameter of a
    function in the same module that a call site passes a derived value to. Column-level reads
    (`col_entry.get("strategy")`) come from a column entry, not from a provider config, so they
    are not flagged, with no list of names. A `strategy_config` read is flagged from any
    receiver. Per read, not per module: a module that also calls `nested_children` is still
    flagged for each direct read it keeps.

    Known remainder, not tracked: a derived value that crosses a module boundary, or a call
    chain deeper than a same-module call that passes the value on by name or attribute. V2.
    """
    scopes: list[ast.AST] = [tree] + [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    methods = {
        id(f)
        for c in ast.walk(tree)
        if isinstance(c, ast.ClassDef)
        for f in c.body
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    funcs: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for sc in scopes[1:]:
        assert isinstance(sc, (ast.FunctionDef, ast.AsyncFunctionDef))
        funcs.setdefault(sc.name, []).append(sc)
    names: dict[int, set[str]] = {id(sc): set() for sc in scopes}
    grew = True
    while grew:
        grew = False
        for sc in scopes:
            names[id(sc)] = _scope_names(sc, names[id(sc)])
        for sc in scopes:
            for node in _own_nodes(sc):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                callee = (
                    fn.id
                    if isinstance(fn, ast.Name)
                    else fn.attr
                    if isinstance(fn, ast.Attribute)
                    else ""
                )
                for target in funcs.get(callee, []):
                    params = _params(target, id(target) in methods)
                    passed = {
                        params[i]
                        for i, a in enumerate(node.args)
                        if i < len(params) and _derived(a, names[id(sc)])
                    } | {
                        k.arg
                        for k in node.keywords
                        if k.arg in params and _derived(k.value, names[id(sc)])
                    }
                    if not passed <= names[id(target)]:
                        names[id(target)] |= passed
                        grew = True
    lines: list[int] = []
    for sc in scopes:
        for node in _own_nodes(sc):
            key: object = None
            receiver: ast.AST | None = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
            ):
                key, receiver = _const_key(node.args[0]), node.func.value
            elif isinstance(node, ast.Subscript):
                key, receiver = _const_key(node.slice), node.value
            if receiver is None:
                continue
            if key == "strategy_config" or (
                key == "strategy" and _derived(receiver, names[id(sc)])
            ):
                lines.append(node.lineno)
    return lines


def is_reader(tree: ast.AST) -> bool:
    return _names_nested(tree) and bool(direct_child_reads(tree))


def uses_choke_point(tree: ast.AST) -> bool:
    imported = any(
        isinstance(n, ast.ImportFrom) and any(a.name == "nested_children" for a in n.names)
        for n in ast.walk(tree)
    )
    return imported and bool(resolved_calls(tree, "nested_children"))


def unmigrated(tree: ast.AST) -> bool:
    """A module that names `nested` and still reads a child key itself."""
    return is_reader(tree)


def _files() -> list[Path]:
    return [p for p in scan.source_files() if p.relative_to(scan.SRC).as_posix() != OWNER]


def test_every_reader_of_a_nested_child_uses_the_choke_point() -> None:
    bad = [
        p.relative_to(scan.SRC).as_posix() for p in _files() if unmigrated(ast.parse(p.read_text()))
    ]
    assert not bad, (
        "read a nested column's child through decoy_engine._nested_json.nested_children, "
        f"not provider_config strategy keys: {bad}"
    )


def test_each_known_reader_calls_the_choke_point() -> None:
    missing = [
        rel for rel in READERS if not uses_choke_point(ast.parse((scan.SRC / rel).read_text()))
    ]
    assert not missing, (
        f"these modules read a nested child and must call nested_children: {missing}"
    )


def test_the_registry_that_only_names_nested_is_not_a_reader() -> None:
    tree = ast.parse((scan.SRC / "validators/_leak_check.py").read_text())
    assert not is_reader(tree)


@pytest.mark.parametrize(
    "source",
    [
        'def f(c):\n    pc = c["provider_config"]\n    return c["strategy"] == "nested" and pc.get("strategy")\n',
        'def f(c):\n    pc = c["provider_config"]\n    return c["strategy"] == "nested" and pc["strategy"]\n',
        'def f(c):\n    pc = c["provider_config"]\n    return c["strategy"] != "nested" or pc.get("strategy_config")\n',
        'def f(c):\n    pc = c["provider_config"]\n    if c["strategy"] in ("nested", "x"):\n        return pc["strategy_config"]\n',
        'def f(c):\n    pc = c["provider_config"]\n    if c["strategy"] in {"x", "nested"}:\n        return pc.get("strategy")\n',
        # A module that calls nested_children and still reads a child key directly.
        "from decoy_engine._nested_json import nested_children\n"
        'def f(c):\n    pc = c["provider_config"]\n    kids = nested_children(pc)\n'
        '    return c["strategy"] == "nested" and pc.get("strategy_config")\n',
        "from decoy_engine._nested_json import nested_children\n"
        'def f(c):\n    pc = c["provider_config"]\n    kids = nested_children(pc)\n'
        '    return c["strategy"] == "nested" and pc["strategy"]\n',
        'T = {"scalar:nested": 1}\ndef f(pc):\n    return pc.get("strategy_config")\n',
        'T = {"nested": 1}\ndef f(pc):\n    return pc.get("strategy_config")\n',
        'def f(c):\n    pc = c["provider_config"]\n    return "nested" == c["strategy"] and pc.get("strategy")\n',
        "from decoy_engine._nested_json import other\n"
        'def f(c):\n    pc = c["provider_config"]\n    return c["strategy"] == "nested" and pc.get("strategy")\n',
        # A renamed receiver, an alias, an inline expression, a comprehension, a helper parameter.
        'def f(c):\n    p = c["provider_config"]\n    return c["strategy"] == "nested" and p.get("strategy")\n',
        'def f(c):\n    pc = c.get("provider_config") or {}\n    q = pc\n'
        '    return c["strategy"] == "nested" and q["strategy"]\n',
        'def f(c):\n    return c["strategy"] == "nested" and c["provider_config"].get("strategy")\n',
        'def f(c):\n    kids = c["provider_config"].get("rules", [])\n'
        '    return c["strategy"] == "nested" and [k.get("strategy") for k in kids]\n',
        'def f(c):\n    return c["strategy"] == "nested" and [k["strategy"] for k in c["provider_config"]["rules"]]\n',
        'def h(x):\n    return x.get("strategy")\n'
        'def f(c):\n    return c["strategy"] == "nested" and h(c["provider_config"])\n',
    ],
)
def test_the_scan_is_red_on_each_seeded_shape(source: str) -> None:
    assert unmigrated(ast.parse(source)), source


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine._nested_json import nested_children\n"
        'def f(c, pc):\n    return c["strategy"] == "nested" and nested_children(pc)\n',
        "from decoy_engine._nested_json import nested_children as kids\n"
        'def f(c, pc):\n    return c["strategy"] == "nested" and kids(pc)\n',
        'def f(c):\n    return c["kind"] == "nested"\n',
        'def f(pc):\n    return pc.get("strategy")\n',
        'KNOWN = frozenset({"nested"})\ndef f(pc):\n    return pc.get("strategy")\n',
        # Column-level reads are not provider-config derived.
        'def f(t):\n    for col in t["columns"]:\n        s = col.get("strategy")\n'
        '        if col["strategy"] == "nested":\n            return s\n',
        'def f(c):\n    return c["strategy"] == "nested" and c.get("provider_config")\n',
    ],
)
def test_the_scan_is_green_on_a_migrated_or_unrelated_module(source: str) -> None:
    assert not unmigrated(ast.parse(source)), source
