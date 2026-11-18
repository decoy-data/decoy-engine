"""Walk the public engine surface and give every export one stability tier (contract 3.6).

The walk imports every public package (no `_` in its dotted path) that declares `__all__`, plus
the root, `sdk` and `providers` modules. Each export gets a tier from `contracts/stability.py`:
an explicit exception first, then identity (an experimental object, or an object a frozen
package already exports), then the package rule. Constants are matched by `(module, name)`.
"""

from __future__ import annotations

import ast
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


def static_all(module: str) -> list[str]:
    """`__all__` read from source, for a package that cannot be imported."""
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin, module
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return [ast.literal_eval(e) for e in node.value.elts]  # type: ignore[attr-defined]
    return []


def missing_extra(module: str, exc: ImportError) -> str | None:
    """The registered optional dependency this error is about, or None for any other error."""
    wanted = st.OPTIONAL_EXTRAS.get(module)
    cause = exc.__cause__ if isinstance(exc.__cause__, ImportError) else exc
    return wanted if wanted is not None and getattr(cause, "name", None) == wanted else None


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
            names = static_all(module)
            exports += [Export(module, n, None, True) for n in names]
            continue
        names = getattr(mod, "__all__", None)
        if names is None:
            continue
        if module not in extra:
            declared.append(module)
        exports += [Export(module, n, getattr(mod, n), False) for n in names]
    return exports, declared


def is_constant(obj: Any) -> bool:
    return not (isinstance(obj, type) or callable(obj))


def experimental_by_identity(export: Export) -> bool:
    obj = export.obj
    if obj is None:
        return False
    if is_constant(obj):
        module, names = st.EXPERIMENTAL_CONSTANTS
        return export.name in names and getattr(importlib.import_module(module), export.name) is obj
    return (obj.__module__, obj.__qualname__) in st.EXPERIMENTAL_OBJECTS


def classify(exports: list[Export]) -> dict[tuple[str, str], str]:
    """`(module, name) -> tier`; raises AssertionError when one object gets two tiers."""
    exceptions = {(m, n): tier for m, n, tier in st.TIER_EXCEPTIONS}
    frozen_ids = {
        id(e.obj)
        for e in exports
        if e.obj is not None
        and not is_constant(e.obj)
        and (e.module, e.name) not in exceptions
        and not experimental_by_identity(e)
        and st.package_tier(e.module) == st.FROZEN
    }
    tiers: dict[tuple[str, str], str] = {}
    groups: dict[int, dict[tuple[str, str], str]] = defaultdict(dict)
    for e in exports:
        key = (e.module, e.name)
        if key in exceptions:
            tier = exceptions[key]
        elif experimental_by_identity(e):
            tier = st.EXPERIMENTAL
        elif e.obj is not None and not is_constant(e.obj) and id(e.obj) in frozen_ids:
            tier = st.FROZEN
        else:
            tier = st.package_tier(e.module)
        assert key not in tiers, f"{key} exported twice"
        tiers[key] = tier
        if e.obj is not None and not is_constant(e.obj):
            groups[id(e.obj)][key] = tier
    clashes = [g for g in groups.values() if len(set(g.values())) > 1]
    assert not clashes, f"one object, two tiers: {clashes[:5]}"
    return tiers


def experimental_public_names(tiers: dict[tuple[str, str], str]) -> set[str]:
    """Public-name spelling of the experimental set: root names bare, `sdk.` names prefixed."""
    out = set()
    for (module, name), tier in tiers.items():
        if tier == st.EXPERIMENTAL and module == "decoy_engine":
            out.add(name)
        elif tier == st.EXPERIMENTAL and module == "decoy_engine.sdk":
            out.add(f"sdk.{name}")
    return out
