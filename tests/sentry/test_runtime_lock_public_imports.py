"""AT-E2-14: the F10 modules import other engine packages only through public names.

`support/_probe.py` and `support/_runtime_lock.py` may import a `_`-prefixed module of
`decoy_engine.support` and the engine-root `decoy_engine._canonical`. Any other import whose dotted
path has a `_` segment below another engine package (for example
`decoy_engine.providers_v2._faker_adapter`) fails here. Scope is these two modules: the
`support/__init__.py` import of `execution.native._route_decline_codes` (F32) is a recorded V2-LOG.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "src" / "decoy_engine" / "support"
MODULES = (SUPPORT / "_probe.py", SUPPORT / "_runtime_lock.py")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "runtime_lock_public_imports"
_ROOT_SHARED = ("decoy_engine._canonical",)
_PACKAGE = ("decoy_engine", "support")


def _resolved(node: ast.ImportFrom) -> str:
    """The absolute dotted module of a `from` import, resolving a relative one in `support`."""
    if node.level == 0:
        return node.module or ""
    base = _PACKAGE[: len(_PACKAGE) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def private_imports(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = _resolved(node)
            names = [module] + [f"{module}.{a.name}" for a in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] != "decoy_engine" or len(parts) < 3:
                continue
            if name.startswith("decoy_engine.support.") or any(
                name == shared or name.startswith(shared + ".") for shared in _ROOT_SHARED
            ):
                continue
            if any(part.startswith("_") for part in parts[2:]):
                hits.append((node.lineno, name))
    return sorted(set(hits))


def test_the_f10_modules_import_only_public_names_of_other_packages() -> None:
    found = {path.name: private_imports(path) for path in MODULES}
    assert not any(found.values()), found


@pytest.mark.parametrize(
    "fixture",
    ["private_import", "plain_import", "from_package", "relative"],
)
def test_a_planted_private_import_is_flagged(fixture: str) -> None:
    names = {n for _, n in private_imports(FIXTURES / f"{fixture}.py.txt")}
    assert "decoy_engine.providers_v2._faker_adapter" in names


def test_private_siblings_in_support_and_the_shared_root_module_are_allowed() -> None:
    assert private_imports(FIXTURES / "allowed.py.txt") == []
