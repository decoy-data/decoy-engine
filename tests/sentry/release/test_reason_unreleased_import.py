"""Every reason module binds UNRELEASED, so a branch that adds a new unreleased code loads.

The release stamp rewrites `since=UNRELEASED` to the version. It used to delete the import too,
once nothing used it. An open branch that added a new `since=UNRELEASED` code to that file then
merged clean and raised NameError when `decoy_engine.reasons` loaded. The binding is the re-export
form `UNRELEASED as UNRELEASED`, so ruff keeps F401 on for every other import in these files.
Modules are found by place (every module inside a reason subpackage), not by how they import, so a
multi-line, aliased or builder-free module cannot drop out. Limit: this proves the name is bound
and survives the stamp; it does not check the codes themselves.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

from decoy_engine import reasons

ROOT = Path(__file__).resolve().parents[3]
REASONS = Path(reasons.__file__).parent
TYPES_MODULE = "decoy_engine.reasons._types"


def _reason_modules(root: Path = REASONS) -> list[Path]:
    """Every module inside a reason subpackage: where specs are declared, now or later."""
    return sorted(p for p in root.rglob("*.py") if p.parent != root and p.name != "__init__.py")


def _binds_unreleased(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom)
        and n.module == TYPES_MODULE
        and any(a.name == "UNRELEASED" and a.asname == "UNRELEASED" for a in n.names)
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


# The reasons package root holds only the catalog machinery; specs live in subpackages, which
# _reason_modules covers. A new module here must be added on purpose, after deciding which it is.
TOP_LEVEL_INTERNALS = frozenset(
    {"__init__.py", "_catalog.py", "_identity.py", "_record.py", "_registry.py", "_types.py"}
)


def test_the_reasons_root_holds_only_the_known_internals() -> None:
    assert {p.name for p in REASONS.glob("*.py")} == TOP_LEVEL_INTERNALS


@pytest.mark.parametrize("path", _reason_modules(), ids=_rel)
def test_reason_module_binds_unreleased(path: Path) -> None:
    tree = ast.parse(path.read_text("utf-8"))
    assert _binds_unreleased(tree), (
        f"{_rel(path)} must `from decoy_engine.reasons._types import UNRELEASED as UNRELEASED`, "
        "even when no code in it is unreleased"
    )


@pytest.mark.parametrize("path", _reason_modules(), ids=_rel)
def test_stamp_keeps_the_binding_a_new_unreleased_code_needs(path: Path) -> None:
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
    assert _binds_unreleased(ast.parse(merged))


_TYPES = "from decoy_engine.reasons._types import"


@pytest.mark.parametrize(
    ("source", "binds"),
    [
        (f"{_TYPES} UNRELEASED as UNRELEASED\n", True),
        (f"{_TYPES} (\n    Kind,\n    UNRELEASED as UNRELEASED,\n)\n", True),
        (f"{_TYPES} UNRELEASED\n", False),
        (f"{_TYPES} UNRELEASED as U\n", False),
        (f"{_TYPES} (\n    Kind,\n    Outcome,\n)\n", False),
        ("from decoy_engine.reasons import _types\n", False),
        (f"def f():\n    {_TYPES} UNRELEASED as UNRELEASED\n", False),
    ],
    ids=["alias", "multiline", "bare", "renamed", "absent", "module-only", "not-top-level"],
)
def test_the_binding_check_reads_each_import_form(source: str, binds: bool) -> None:
    assert _binds_unreleased(ast.parse(source)) is binds


def test_discovery_finds_nested_and_builder_free_modules(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "_top.py").write_text("")
    nested = tmp_path / "plan" / "deep"
    nested.mkdir(parents=True)
    (tmp_path / "plan" / "__init__.py").write_text("")
    (tmp_path / "plan" / "_tables.py").write_text("X = 1\n")
    (nested / "__init__.py").write_text("")
    (nested / "_multi.py").write_text(f"{_TYPES} (\n    Kind,\n)\n")
    found = {p.relative_to(tmp_path).as_posix() for p in _reason_modules(tmp_path)}
    assert found == {"plan/_tables.py", "plan/deep/_multi.py"}
