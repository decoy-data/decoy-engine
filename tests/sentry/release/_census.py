"""Walk the public engine surface and give every export one stability tier (contract 3.6).

The walk imports every public package (no `_` in its dotted path) that declares `__all__`, plus
the root, `sdk` and `providers` modules. Each export gets a tier from `contracts/stability.py`:
an explicit exception first, then identity (what `sdk` defines, a listed experimental object, or
an object a frozen path already exports), then the package rule. A tier belongs to the object and
applies to every path that exports it. A constant is matched by `(name, object identity)`.
"""

from __future__ import annotations

import ast
import functools
import importlib
import importlib.util
import pkgutil
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

import decoy_engine
from decoy_engine.contracts import stability as st

EXTRA_MODULES = ("decoy_engine", "decoy_engine.sdk", "decoy_engine.providers")


class Export(NamedTuple):
    module: str
    name: str
    obj: Any  # None when the package could not be imported (optional extra, static names)
    static: bool


def public_packages() -> list[str]:
    found = []
    for info in pkgutil.walk_packages(decoy_engine.__path__, "decoy_engine."):
        if info.ispkg and not any(p.startswith("_") for p in info.name.split(".")[1:]):
            found.append(info.name)
    return sorted(found)


def module_source(module: str) -> str:
    """The source text of `module`; the census reads it so `contracts` does not have to."""
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin, module
    return Path(spec.origin).read_text(encoding="utf-8")


# The seam asks for the same module once per export; fixtures rewrite modules, so only this is cached.
seam_source = functools.cache(module_source)


def _source_tree(module: str) -> ast.Module:
    return ast.parse(module_source(module))


def _literal_names(node: ast.expr, module: str) -> list[str]:
    assert isinstance(node, (ast.List, ast.Tuple)), f"{module}: `__all__` is not a literal list"
    return [ast.literal_eval(e) for e in node.elts]


def static_all(module: str) -> list[str]:
    """`__all__` read from source: plain, annotated and `+=` forms; anything else fails."""
    names: list[str] = []
    found = False
    for node in _source_tree(module).body:
        if (isinstance(node, ast.Assign) and any(_is_all(t) for t in node.targets)) or (
            isinstance(node, ast.AnnAssign) and _is_all(node.target) and node.value
        ):
            names, found = _literal_names(node.value, module), True  # type: ignore[arg-type]
        elif isinstance(node, ast.AugAssign) and _is_all(node.target):
            names += _literal_names(node.value, module)
            found = True
    assert found, f"{module}: no static `__all__` to classify"
    return names


def _is_all(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == "__all__"


def missing_extra(module: str, exc: ImportError) -> str | None:
    """The registered optional dependency this error is about, or None for any other error.

    Tolerated only when the dependency is really absent and the error is the
    `ModuleNotFoundError` that names it.
    """
    wanted = st.OPTIONAL_EXTRAS.get(module.removeprefix("decoy_engine."))
    cause = exc.__cause__ if isinstance(exc.__cause__, ImportError) else exc
    if wanted is None or not isinstance(cause, ModuleNotFoundError) or cause.name != wanted:
        return None
    return wanted if importlib.util.find_spec(wanted) is None else None


def load(
    modules: list[str] | None = None, extra: tuple[str, ...] = EXTRA_MODULES
) -> tuple[list[Export], list[str]]:
    """Every export of the walked modules, and the importable packages that declared `__all__`."""
    exports: list[Export] = []
    declared: list[str] = []
    for module in [*extra, *(modules if modules is not None else public_packages())]:
        try:
            mod = importlib.import_module(module)
        except ImportError as exc:
            assert missing_extra(module, exc), f"{module}: unregistered import failure: {exc!r}"
            exports += [Export(module, n, None, True) for n in static_all(module)]
            continue
        names = getattr(mod, "__all__", None)
        if names is None:
            continue
        if module not in extra:
            declared.append(module)
        exports += [Export(module, n, getattr(mod, n), False) for n in names]
    return exports, declared


def packages_without_all() -> list[str]:
    """Importable public packages that declare no `__all__`, as paths under `decoy_engine`."""
    out = []
    for module in public_packages():
        try:
            mod = importlib.import_module(module)
        except ImportError:
            continue
        if getattr(mod, "__all__", None) is None:
            out.append(module.removeprefix("decoy_engine."))
    return sorted(out)


def classify(exports: list[Export]) -> dict[tuple[str, str], str]:
    """`(module, name) -> tier`; raises AssertionError when one object gets two tiers."""
    exceptions = {(m, n): tier for m, n, tier in st.TIER_EXCEPTIONS}
    frozen_groups = {
        st.tier_key(e.name, e.obj)
        for e in exports
        if e.obj is not None
        and not st.is_experimental_export(e.name, e.obj, seam_source)
        and (
            exceptions.get((e.module, e.name)) == st.FROZEN
            or ((e.module, e.name) not in exceptions and st.package_tier(e.module) == st.FROZEN)
        )
    }
    tiers: dict[tuple[str, str], str] = {}
    groups: dict[Any, dict[tuple[str, str], str]] = defaultdict(dict)
    for e in exports:
        key = (e.module, e.name)
        if key in exceptions:
            tier = exceptions[key]
        elif e.obj is not None and st.is_experimental_export(e.name, e.obj, seam_source):
            tier = st.EXPERIMENTAL
        elif e.obj is not None and st.tier_key(e.name, e.obj) in frozen_groups:
            tier = st.FROZEN
        else:
            tier = st.package_tier(e.module)
        assert key not in tiers, f"{key} exported twice"
        tiers[key] = tier
        if e.obj is not None:
            groups[st.tier_key(e.name, e.obj)][key] = tier
    clashes = [g for g in groups.values() if len(set(g.values())) > 1]
    assert not clashes, f"one object, two tiers: {clashes[:5]}"
    return tiers


def experimental_names(tiers: dict[tuple[str, str], str]) -> set[str]:
    """Bare names of every experimental export."""
    return {n for (_, n), tier in tiers.items() if tier == st.EXPERIMENTAL}


def experimental_public_names(tiers: dict[tuple[str, str], str]) -> set[str]:
    """Public-name spelling of the experimental set: root names bare, `sdk.` names prefixed."""
    return _spelled(tiers, st.EXPERIMENTAL)


def frozen_public_names(tiers: dict[tuple[str, str], str]) -> set[str]:
    """The frozen names the map holds: root bare, `sdk.` prefixed, and each frozen exception row
    as `<package path under decoy_engine>.<name>`."""
    out = _spelled(tiers, st.FROZEN)
    out |= {
        f"{m.removeprefix('decoy_engine.')}.{n}"
        for m, n, tier in st.TIER_EXCEPTIONS
        if tier == st.FROZEN
    }
    return out


def _spelled(tiers: dict[tuple[str, str], str], wanted: str) -> set[str]:
    out = set()
    for (module, name), tier in tiers.items():
        if tier != wanted:
            continue
        if module == "decoy_engine":
            out.add(name)
        elif module == "decoy_engine.sdk":
            out.add(f"sdk.{name}")
    return out


def marker_problems(rows: list[tuple[Export, str]]) -> list[str]:
    """Callables whose docstring marker disagrees with their tier, both ways."""
    problems = []
    for e, tier in rows:
        if e.obj is None or not callable(e.obj):
            continue
        marked = (getattr(e.obj, "__doc__", None) or "").lstrip().startswith(st.EXPERIMENTAL_MARKER)
        if tier == st.EXPERIMENTAL and not marked:
            problems.append(f"{e.module}.{e.name}: experimental without the marker")
        elif tier != st.EXPERIMENTAL and marked:
            problems.append(f"{e.module}.{e.name}: marker on a {tier} name")
    return problems
