"""A faker column's pool size is answered in one place: `effective_pool_size`.

Admission answers "is this column a shape the route can reproduce". Pool size is not part of that
answer, because every size, the default included, reproduces. An admission module that tests
`pool_size` (a comparison, a membership test or a branch on it) turns an absent size back into a
refusal on one route while the others admit it. Passing the value on to
`resolve_faker_pool_identity` is allowed.

Covered shapes: an attribute or a `"pool_size"` key (`.get`, subscript) used as an operand of a
comparison, `in`/`not in`, `and`/`or`/`not`, or the test of an `if`, `while` or ternary.
Aliasing the value through another name first is out of scope (V2-LOG).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
KEY = "pool_size"
MODULES = (
    "execution/native/_requirements.py",
    "execution/native/_faker_positional_admission.py",
    "execution/_chunked.py",
    "execution/physical/_shadow_bindings.py",
    "execution/out_of_core/_compat.py",
    "execution/out_of_core/_faker_native.py",
    "execution/_sequential_native_ops.py",
)

# (module, function) -> reason. Starts empty: a new entry needs a reason here.
ALLOWED: dict[tuple[str, str], str] = {}


def _is_pool_size(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == KEY
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == KEY
    if isinstance(node, ast.Constant):
        return node.value == KEY
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "pop")
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == KEY
    )


def _mentions(node: ast.AST) -> bool:
    return any(_is_pool_size(n) for n in ast.walk(node))


def _tested_operands(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Compare):
        return [node.left, *node.comparators]
    if isinstance(node, ast.BoolOp):
        return list(node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return [node.operand]
    if isinstance(node, (ast.If, ast.While, ast.IfExp)):
        return [node.test]
    return []


def scan(source: str, rel: str = "m.py") -> set[tuple[str, str]]:
    """The `(module, function)` pairs that test `pool_size` instead of passing it on."""
    found: set[tuple[str, str]] = set()

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = (*scope, child.name)
            if any(_mentions(op) for op in _tested_operands(child)):
                found.add((rel, ".".join(scope)))
            walk(child, inner)

    walk(ast.parse(source), ())
    return found


@pytest.mark.parametrize("module", MODULES)
def test_admission_modules_do_not_test_pool_size(module: str) -> None:
    path = ROOT / module
    assert path.exists(), module
    unexpected = scan(path.read_text(), module) - set(ALLOWED)
    assert unexpected == set(), (
        "admission must not read pool_size; resolve it via effective_pool_size"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "def f(seed):\n    return seed.pool_size is not None\n",
        "def f(cfg):\n    if cfg.get('pool_size'):\n        return 1\n",
        "def f(cfg):\n    return 'pool_size' in cfg\n",
        "def f(e):\n    return e.get('pool_size') is None and e.get('x') is None\n",
        "def f(e):\n    return e['pool_size'] == 3\n",
        "def f(s):\n    return 1 if s.pool_size else 2\n",
        "def f(s):\n    return not s.pool_size\n",
    ],
)
def test_the_scan_catches_the_realistic_spellings(bad: str) -> None:
    assert scan(bad)


def test_the_scan_allows_passing_the_value_on() -> None:
    ok = "def f(s):\n    return PoolBinding(provider=p, plan_pool_size=s.pool_size)\n"
    assert scan(ok) == set()
