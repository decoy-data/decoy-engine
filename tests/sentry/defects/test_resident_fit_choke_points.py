"""NONFK-OOM choke points for the resident lower bound.

G-7: the strict lower bound has one formula, `lower_bound_bytes` in `pipeline/_resident_fit.py`.
Each consumer imports it through the `decoy_engine.execution.pipeline` facade, calls it, and does
not add `input_bytes` and `pandas_bytes` itself. The S1 bench is the only consumer today; the S4b
fact gatherer joins `CONSUMERS` when it lands.

The scan resolves import aliases and re-bindings through the shared call-resolution helper.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._call_resolution import resolved_calls

ROOT = Path(__file__).resolve().parents[3]
PRIMITIVE = "lower_bound_bytes"
OWNER_MODULES = ("_resident_fit", "_resident_bytes")
FACADE = "decoy_engine.execution.pipeline"
CONSUMERS = (ROOT / "scripts" / "bench-auto-chunk" / "bench_nonfk_fallthrough.py",)


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def _private_imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            private = any(m in (node.module or "").split(".") for m in OWNER_MODULES) or any(
                a.name in OWNER_MODULES for a in node.names
            )
        elif isinstance(node, ast.Import):
            private = any(m in a.name.split(".") for a in node.names for m in OWNER_MODULES)
        else:
            continue
        if private:
            found.append("imports the private module")
    return found


def _local_formulas(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        is_add = isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Add)
        if is_add and {"input_bytes", "pandas_bytes"} <= _names(node):
            found.append("adds input_bytes and pandas_bytes locally")
    return found


def consumer_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    problems = _private_imports(tree) + _local_formulas(tree)
    facade_import = any(
        isinstance(n, ast.ImportFrom)
        and n.module == FACADE
        and any(a.name == PRIMITIVE for a in n.names)
        for n in ast.walk(tree)
    )
    if not facade_import:
        problems.append(f"does not import {PRIMITIVE} from the facade")
    if not resolved_calls(tree, PRIMITIVE):
        problems.append(f"does not call {PRIMITIVE}")
    return problems


_GOOD = f"from {FACADE} import lower_bound_bytes\nx = lower_bound_bytes([spec])\n"
_ALIASED = f"from {FACADE} import lower_bound_bytes as lb\nx = lb([spec])\n"


@pytest.mark.parametrize("consumer", CONSUMERS, ids=lambda p: p.name)
def test_real_consumers_use_the_one_primitive(consumer: Path) -> None:
    assert consumer_violations(consumer.read_text(encoding="utf-8")) == []


def test_aliased_facade_call_is_accepted() -> None:
    assert consumer_violations(_ALIASED) == []


@pytest.mark.parametrize(
    "source",
    [
        # mutation 27: the inline formula in place of the call
        "from decoy_engine.execution.pipeline import lower_bound_bytes\n"
        "lb = input_bytes + pandas_bytes\n",
        "lb = ib + pb\ninput_bytes = 1\npandas_bytes = 2\nx = input_bytes + pandas_bytes\n",
        _GOOD + "total = input_bytes(specs) + pandas_bytes(specs)\n",
        _GOOD + "total = 0\ntotal += input_bytes + pandas_bytes\n",
        # a private-module import, in each spelling
        "from decoy_engine.execution.pipeline._resident_fit import lower_bound_bytes\n"
        "x = lower_bound_bytes([s])\n",
        "from decoy_engine.execution.pipeline import _resident_fit\nx = _resident_fit.lower_bound_bytes([s])\n",
        "import decoy_engine.execution.pipeline._resident_fit as rf\nx = rf.lower_bound_bytes([s])\n",
        "from decoy_engine.execution.pipeline._resident_bytes import lower_bound_bytes\n"
        "x = lower_bound_bytes([s])\n",
        "from decoy_engine.execution.pipeline import _resident_bytes\nx = _resident_bytes.lower_bound_bytes([s])\n",
        "import decoy_engine.execution.pipeline._resident_bytes as rb\nx = rb.lower_bound_bytes([s])\n",
        # imported but never called
        f"from {FACADE} import lower_bound_bytes\n",
        # no facade import
        "x = lower_bound_bytes([s])\n",
    ],
)
def test_seeded_bypasses_fail(source: str) -> None:
    assert consumer_violations(source) != []


def test_facade_re_exports_the_owner_function() -> None:
    from decoy_engine.execution import pipeline
    from decoy_engine.execution.pipeline import _resident_fit

    assert pipeline.lower_bound_bytes is _resident_fit.lower_bound_bytes
