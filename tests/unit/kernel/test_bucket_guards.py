"""S1k P10: structural guards for the bucketize and top_code kernel.

Three rules, each tested on planted source (one violation per test, plus a legal control) and then
on the production code:

1. A bucket width or top_code bound comes from the resolved settings only. No function that feeds
   a width or bound reduces over the data (min, max, quantile, percentile, mean, describe, sum).
   Counting a warning mask (``true_count``, ``count_nonzero``) is not a reduction over values.
2. The integer range endpoint uses checked addition.
3. The kernel package imports nothing from ``decoy_engine.execution``, however the import is
   written (absolute, relative, aliased, or through the package).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
KERNEL = SRC / "kernel"
STRATEGIES = SRC / "execution" / "_strategies"

REDUCTIONS = frozenset(
    {
        "min", "max", "nanmin", "nanmax", "min_max", "quantile", "nanquantile", "percentile",
        "nanpercentile", "mean", "nanmean", "median", "nanmedian", "describe", "sum", "nansum",
        "std", "var", "mode", "approximate_median",
    }
)  # fmt: skip


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> original name, for every ``from x import name as alias``."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                out[a.asname or a.name] = a.name
    return out


def data_reductions(source: str, functions: frozenset[str] | None = None) -> list[str]:
    """Calls to a value reduction inside ``functions`` (all functions when None).

    Catches a plain name, an imported alias, a method call, a module attribute and a literal
    ``getattr(obj, "max")``.
    """
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or (
            functions is not None and fn.name not in functions
        ):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Name):
                name = aliases.get(func.id, func.id)
                if func.id == "getattr" and len(node.args) >= 2:
                    arg = node.args[1]
                    name = (
                        arg.value
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        else None
                    )
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in REDUCTIONS:
                found.append(f"{fn.name}:{name}")
    return found


PLANTED_REDUCTIONS = {
    "min": "def f(v):\n    return v.min()\n",
    "max": "def f(v):\n    return max(v)\n",
    "quantile": "import numpy as np\ndef f(v):\n    return np.quantile(v, 0.9)\n",
    "percentile": "import numpy as np\ndef f(v):\n    return np.nanpercentile(v, 90)\n",
    "mean": "def f(v):\n    return v.mean()\n",
    "describe": "def f(v):\n    return v.describe()\n",
    "sum": "import pyarrow.compute as pc\ndef f(v):\n    return pc.sum(v)\n",
    "alias": "from numpy import max as biggest\ndef f(v):\n    return biggest(v)\n",
    "getattr": 'def f(v):\n    return getattr(v, "max")()\n',
}


@pytest.mark.parametrize("name", sorted(PLANTED_REDUCTIONS))
def test_planted_reduction_is_found(name: str) -> None:
    assert data_reductions(PLANTED_REDUCTIONS[name]) != []


def test_counting_a_warning_mask_is_legal() -> None:
    legal = (
        "import numpy as np\n"
        "def f(over, under):\n"
        "    return over.true_count, int(np.count_nonzero(under)), len(over)\n"
    )
    assert data_reductions(legal) == []


def test_a_reduction_outside_the_scoped_functions_is_ignored() -> None:
    src = "def other(v):\n    return v.max()\ndef resolve(v):\n    return 1\n"
    assert data_reductions(src, frozenset({"resolve"})) == []
    assert data_reductions(src, frozenset({"other"})) == ["other:max"]


def test_kernel_never_reduces_over_values() -> None:
    for path in sorted(KERNEL.glob("_bucket.py")):
        assert data_reductions(path.read_text(encoding="utf-8")) == [], path.name


def test_settings_resolvers_never_reduce_over_values() -> None:
    scope = {
        "_bucketize.py": frozenset({"resolve_bucketize_settings"}),
        "_top_code.py": frozenset(
            {
                "resolve_top_code_settings",
                "_resolve_top_bound",
                "_resolve_bottom_bound",
                "_is_usable_bound",
            }
        ),
    }
    for name, functions in scope.items():
        source = (STRATEGIES / name).read_text(encoding="utf-8")
        present = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
        assert functions <= present, f"{name} lost a guarded resolver"
        assert data_reductions(source, functions) == [], name


def checked_endpoint(source: str, function: str) -> bool:
    """True when ``function`` adds with ``add_checked`` and never with a plain ``add``."""
    tree = ast.parse(source)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == function:
            calls = [
                n.func.attr
                for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            ]
            return "add_checked" in calls and "add" not in calls
    return False


def test_planted_unchecked_endpoint_is_found() -> None:
    bad = "import pyarrow.compute as pc\ndef end(a, w):\n    return pc.add(a, w)\n"
    good = "import pyarrow.compute as pc\ndef end(a, w):\n    return pc.add_checked(a, w)\n"
    assert not checked_endpoint(bad, "end")
    assert checked_endpoint(good, "end")
    assert not checked_endpoint(good, "missing")


def test_kernel_range_endpoint_is_checked() -> None:
    source = (KERNEL / "_bucket.py").read_text(encoding="utf-8")
    assert checked_endpoint(source, "_range_upper")


def execution_imports(source: str, module: str) -> list[str]:
    """Imports of ``decoy_engine.execution`` from ``module`` (dotted name), in any spelling."""
    package = module.rsplit(".", 1)[0].split(".")
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_execution(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                resolved = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                resolved = node.module or ""
            if _is_execution(resolved):
                found.append(resolved)
            else:
                found += [
                    f"{resolved}.{a.name}"
                    for a in node.names
                    if _is_execution(f"{resolved}.{a.name}")
                ]
    return found


def _is_execution(dotted: str) -> bool:
    return dotted == "decoy_engine.execution" or dotted.startswith("decoy_engine.execution.")


PLANTED_IMPORTS = {
    "absolute": "from decoy_engine.execution import _row_errors\n",
    "absolute module": "import decoy_engine.execution._adapter\n",
    "aliased module": "import decoy_engine.execution as ex\n",
    "from-import alias": "from decoy_engine.execution._adapter import StrategyContext as C\n",
    "package alias": "from decoy_engine import execution as ex\n",
    "relative": "from ..execution import _adapter\n",
    "relative package": "from .. import execution\n",
}


@pytest.mark.parametrize("name", sorted(PLANTED_IMPORTS))
def test_planted_execution_import_is_found(name: str) -> None:
    assert execution_imports(PLANTED_IMPORTS[name], "decoy_engine.kernel._bucket") != []


def test_legal_kernel_imports_pass() -> None:
    legal = (
        "from decoy_engine.contracts.bucketize_width import EXACT_INT_BOUND\n"
        "from decoy_engine import kernel\n"
        "from . import _scalar\n"
        "import pyarrow as pa\n"
    )
    assert execution_imports(legal, "decoy_engine.kernel._bucket") == []


def test_kernel_package_imports_nothing_from_execution() -> None:
    for path in sorted(KERNEL.glob("*.py")):
        module = f"decoy_engine.kernel.{path.stem}"
        assert execution_imports(path.read_text(encoding="utf-8"), module) == [], path.name
