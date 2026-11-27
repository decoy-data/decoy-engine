"""Sentry: `import decoy_engine` works in a fresh interpreter, and the work-order package stays a
one-way dependency (work_order -> `_column_access`).

import-linter sees `execution` as one layer, so an import cycle inside it passes the layer
contract. A cycle only shows when a module loads first, which is how a second slice merged against
this one broke `import decoy_engine`: `_column_access` -> `generation.composite` -> `plan` ->
`_strategies._date_shift` -> `work_order` (eager) -> `operations` -> `_column_access` (half
loaded). The package `__init__` is lazy and `rows` is a leaf, so no module that a strategy or
`_column_access` imports can reach the compiler. `decoy_engine/__init__` loads the whole engine in
one fixed order, so every `import decoy_engine.x` runs that same order first; the fresh-interpreter
cells below are the modules a cycle would have to enter through, not a walk of every module.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"
EXECUTION = SRC / "decoy_engine" / "execution"
WORK_ORDER = "decoy_engine.execution.work_order"


def _fresh(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300, check=False
    )


def _eager_imports(path: Path) -> list[str]:
    """Absolute names a module imports at module level, outside `TYPE_CHECKING` blocks.

    `import decoy_engine` loads the whole engine, so a runtime probe cannot tell what one module
    pulls in; the module-level import statements can."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.append(node.module)
                names.extend(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.If):
                test = ast.unparse(node.test)
                if test not in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
                    walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                walk(node.body)
                for handler in node.handlers:
                    walk(handler.body)

    walk(tree.body)
    return names


def test_the_package_init_imports_no_submodule_eagerly() -> None:
    """The lazy `__init__` is what lets a strategy import `rows` without loading the compiler."""
    eager = _eager_imports(EXECUTION / "work_order" / "__init__.py")
    assert [n for n in eager if n.startswith(WORK_ORDER)] == []


def test_rows_is_a_leaf_of_the_work_order_package() -> None:
    """Strategies import `rows`; it takes only `reasons` and the error types at module level, so
    it cannot pull the compiler (or `_column_access`) in behind them."""
    eager = _eager_imports(EXECUTION / "work_order" / "rows.py")
    internal = {n for n in eager if n.startswith("decoy_engine")}
    assert internal <= {
        "decoy_engine",
        "decoy_engine.reasons",
        "decoy_engine.execution._errors",
        "decoy_engine.execution._errors.StrategyError",
        "decoy_engine.reasons.runtime",
    }, sorted(internal)


def test_the_probe_sees_an_eager_import(tmp_path: Path) -> None:
    """Seeded positive: the scanner reports a module-level import and skips a guarded one."""
    probe = tmp_path / "m.py"
    probe.write_text(
        "from typing import TYPE_CHECKING\nfrom a.b import c\n"
        "if TYPE_CHECKING:\n    from x.y import z\n"
        "def f():\n    import late\n",
        encoding="utf-8",
    )
    assert "a.b" in _eager_imports(probe)
    assert not {"x.y", "late"} & set(_eager_imports(probe))


def test_column_access_never_imports_the_work_order_package() -> None:
    """The dependency runs work_order -> `_column_access`, never back."""
    tree = ast.parse((EXECUTION / "_column_access.py").read_text(encoding="utf-8"))
    imported = [
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.level == 0)
    ] + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert [m for m in imported if m.startswith(WORK_ORDER)] == []


@pytest.mark.parametrize(
    "module",
    [
        "decoy_engine",
        f"{WORK_ORDER}.rows",
        f"{WORK_ORDER}.operations",
        "decoy_engine.execution._column_access",
        "decoy_engine.execution._strategies._date_shift",
        "decoy_engine.execution._strategies._joint_mask",
    ],
)
def test_a_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    res = _fresh(f"import {module}")
    assert res.returncode == 0, f"importing {module} first failed (rc {res.returncode})"
