"""Every reason spec module binds UNRELEASED, so a branch that adds a new unreleased code loads.

The release stamp rewrites `since=UNRELEASED` to the version. It used to delete the import too,
once nothing used it. An open branch that added a new `since=UNRELEASED` code to that file then
merged clean and raised NameError when `decoy_engine.reasons` loaded. Limit: this proves the name
is bound in each spec module and survives the stamp; it does not check the codes themselves.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

from decoy_engine import reasons

ROOT = Path(__file__).resolve().parents[2]
REASONS = Path(reasons.__file__).parent
TYPES_MODULE = "decoy_engine.reasons._types"


def _spec_files() -> list[Path]:
    """Modules that declare specs: they import the `_catalog` builders."""
    return sorted(
        p
        for p in REASONS.rglob("*.py")
        if "from decoy_engine.reasons import _catalog" in p.read_text("utf-8")
    )


def _imports_unreleased(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom)
        and n.module == TYPES_MODULE
        and any(a.name == "UNRELEASED" and a.asname is None for a in n.names)
        for n in tree.body
    )


def _rel(p: Path) -> str:
    return p.relative_to(REASONS).as_posix()


def test_every_module_under_reasons_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(reasons.__path__, "decoy_engine.reasons.")]
    assert names, "no reason modules found"
    for name in names:
        importlib.import_module(name)
        assert name in sys.modules


def test_spec_modules_were_found() -> None:
    assert len(_spec_files()) >= 30


@pytest.mark.parametrize("path", _spec_files(), ids=_rel)
def test_spec_module_binds_unreleased(path: Path) -> None:
    tree = ast.parse(path.read_text("utf-8"))
    assert _imports_unreleased(tree), (
        f"{_rel(path)} must `from decoy_engine.reasons._types import UNRELEASED`, "
        "even when no code in it is unreleased"
    )


@pytest.mark.parametrize("path", _spec_files(), ids=_rel)
def test_stamp_keeps_the_import_a_new_unreleased_code_needs(path: Path) -> None:
    """Stamp the module as a release would, then append what a merged branch brings."""
    sys.path.insert(0, str(ROOT / "scripts" / "dev"))
    sys.path.insert(0, str(ROOT))
    try:
        import registry_renumber as rr
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
    stamped = rr.stamp_source(path.read_text("utf-8"), "9.9.0")
    merged = stamped + '\n_x = _d("x_probe", "A probe.", since=UNRELEASED)\n'
    assert _imports_unreleased(ast.parse(merged))
