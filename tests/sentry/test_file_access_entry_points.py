"""D9 engine entry sentry: a public callable that can reach the policy is a declared entry point.

`decoy_engine.fileaccess.ENTRY_POINTS` lists every public callable whose static call graph
reaches `fileaccess.current()`; each one accepts a keyword-only `file_access=` and is wrapped
by `entry_point`, which installs the policy for the call and keeps it on any iterator the call
returns. The platform's own sentry then requires `file_access=` at each call of these names.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import types
from pathlib import Path

import pytest

from decoy_engine.fileaccess import ENTRY_POINTS
from tests.sentry.fa.callgraph import build_graph

SRC = Path(__file__).parents[2] / "src"

# The policy package itself defines `current()`; it is not a caller of it.
INTERNAL_PREFIXES = ("decoy_engine.fileaccess",)

# Public re-exports of the native, out-of-core and physical seams that reach the policy but are
# not entry points. Each is called only from inside a declared entry point (the platform and CLI
# call `run_pipeline`, `run_fk_out_of_core` and the other listed entries, never these), so a
# policy is already installed when they run. A new public name in these packages that reaches
# the policy fails the sentry until it is made an entry point or added here with its reason.
INTERNAL_SEAMS: dict[str, str] = {
    "decoy_engine.execution.native._dispatch.plan_native_route": "routing helper of run_pipeline",
    "decoy_engine.execution.native._dispatch.run_native_or_oracle_chunked": "chunked route driver",
    "decoy_engine.execution.out_of_core._mask.mask_batch": "per-batch step of the FK route",
    "decoy_engine.execution.out_of_core._mask.mask_column": "per-column step of the FK route",
    "decoy_engine.execution.out_of_core._relation.build_parent_key_relation": "FK route step",
    "decoy_engine.execution.physical._snapshot.capture_physical_plan_inputs": "shadow-plan capture",
}


@pytest.fixture(scope="module")
def graph():  # type: ignore[no-untyped-def]
    return build_graph(SRC)


def _public_names(graph) -> set[str]:  # type: ignore[no-untyped-def]
    public: set[str] = set()
    for module, names in graph.all_exports.items():
        parts = module.split(".")
        if any(p.startswith("_") and p != "__init__" for p in parts):
            continue
        if module.startswith(INTERNAL_PREFIXES):
            continue
        for name in names:
            public.add(graph.index.normalize(f"{module}.{name}"))
    return public


def test_every_public_function_that_reaches_the_policy_is_an_entry_point(graph) -> None:  # type: ignore[no-untyped-def]
    reach = graph.reachers()
    missing = sorted(
        name
        for name in _public_names(graph)
        if name in reach
        and name in graph.funcs
        and not name.startswith(INTERNAL_PREFIXES)
        and name not in ENTRY_POINTS
        and name not in INTERNAL_SEAMS
    )
    assert not missing, (
        f"public callables reaching the file-access policy, not in ENTRY_POINTS: {missing}"
    )


def test_every_entry_point_exists_accepts_the_keyword_and_installs_the_policy() -> None:
    for dotted in ENTRY_POINTS:
        module, _, name = dotted.rpartition(".")
        fn = getattr(importlib.import_module(module), name)
        params = inspect.signature(fn).parameters
        assert "file_access" in params, dotted
        assert params["file_access"].kind is inspect.Parameter.KEYWORD_ONLY, dotted
        assert params["file_access"].default is None, dotted
        assert getattr(fn, "__decoy_entry_point__", False), (
            f"{dotted} is not wrapped by entry_point"
        )


def test_entry_points_are_sorted_and_unique() -> None:
    assert list(ENTRY_POINTS) == sorted(set(ENTRY_POINTS))


def test_an_entry_point_that_returns_an_iterator_goes_through_the_binding_wrapper() -> None:
    """`entry_point` binds any iterator result to the policy it ran under, so no listed
    function can hand back a lazy generator that reads under a different policy later."""
    source = (SRC / "decoy_engine" / "fileaccess" / "_entry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wrapper = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "entry_point"
    )
    calls = {
        c.func.id
        for c in ast.walk(wrapper)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    }
    assert "bind_iterator" in calls


def test_every_internal_seam_exemption_is_real_and_not_also_an_entry_point(graph) -> None:  # type: ignore[no-untyped-def]
    reach = graph.reachers()
    for name in INTERNAL_SEAMS:
        assert name in graph.funcs, f"stale exemption: {name}"
        assert name in reach, f"{name} no longer reaches the policy; drop the exemption"
        assert name not in ENTRY_POINTS, name


def test_the_out_of_core_driver_the_platform_calls_is_an_entry_point() -> None:
    assert "decoy_engine.execution.out_of_core._runner.run_fk_out_of_core" in ENTRY_POINTS


def _engine_modules() -> tuple[list[types.ModuleType], dict[str, str]]:
    """Every importable `decoy_engine` module, and the ones that could not be imported (name to
    its source file). The walk imports each module, so a function wrapped by
    `entry_point` under any alias, `functools` re-wrap or async form carries the runtime marker."""
    import decoy_engine

    modules: list[types.ModuleType] = []
    failed: dict[str, str] = {}
    for info in pkgutil.walk_packages(decoy_engine.__path__, "decoy_engine."):
        try:
            modules.append(importlib.import_module(info.name))
        except ImportError:
            spec = info.module_finder.find_spec(info.name)  # type: ignore[call-arg,union-attr]
            failed[info.name] = spec.origin or "" if spec else ""
    return modules, failed


def marked_functions(modules: list[types.ModuleType]) -> set[tuple[str, str]]:
    """(module, qualname) of every function that `entry_point` wrapped and the module defines
    itself (`__module__` check, so a re-export is not counted twice)."""
    found: set[tuple[str, str]] = set()
    for module in modules:
        for obj in vars(module).values():
            if (
                inspect.isfunction(obj)
                and getattr(obj, "__decoy_entry_point__", False)
                and obj.__module__ == module.__name__
            ):
                found.add((module.__name__, obj.__qualname__))
    return found


def _listed_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for dotted in ENTRY_POINTS:
        module, _, name = dotted.rpartition(".")
        fn = getattr(importlib.import_module(module), name)
        pairs.add((fn.__module__, fn.__qualname__))
    return pairs


def test_a_module_that_cannot_be_imported_defines_no_entry_point() -> None:
    """A module needing an optional extra (mimesis, lightgbm) cannot be imported in every venv,
    so the marker walk cannot see inside it. It is skipped only if its source never names
    `entry_point`; one that does fails here instead of hiding a function."""
    _, failed = _engine_modules()
    named = sorted(
        name for name, origin in failed.items() if "entry_point" in Path(origin).read_text()
    )
    assert named == []


def test_every_function_marked_by_entry_point_is_listed() -> None:
    """The call-graph walk cannot follow an indirect call (`entry.lazy(...)`), so a marked
    function that is not in ENTRY_POINTS is found here from the marker `entry_point` sets."""
    modules, _ = _engine_modules()
    assert sorted(marked_functions(modules) - _listed_pairs()) == []


def test_the_marker_walk_sees_every_listed_entry_point() -> None:
    """The walk is not vacuous: it finds each listed function, so a renamed marker fails here."""
    modules, _ = _engine_modules()
    assert _listed_pairs() <= marked_functions(modules)


def test_a_marked_function_that_is_not_listed_is_seen() -> None:
    def seeded() -> None: ...

    seeded.__decoy_entry_point__ = True  # type: ignore[attr-defined]
    seeded.__module__ = "seeded_module"
    module = types.ModuleType("seeded_module")
    module.seeded = seeded  # type: ignore[attr-defined]
    found = marked_functions([module])
    assert found == {("seeded_module", seeded.__qualname__)}
    assert found - _listed_pairs() == found
    reexport = types.ModuleType("other")
    reexport.seeded = seeded  # type: ignore[attr-defined]
    assert marked_functions([reexport]) == set()
