"""F33 E1a (AT-E10): the signed-evidence filesystem entries sit behind the file-access sentry.

The bundle and artifact roots are caller-named directories. They are opened by one ambient guard
(`fileaccess/_ambient_tree.py`), each caller of it has its own registry entry, and no signed-evidence
module opens or walks a path on its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.sentry.fa.classify import Roles, classify, registry_index
from tests.sentry.fa.rules import load_modules_config, load_registry
from tests.sentry.fa.scan import scan_tree

HERE = Path(__file__).parent
SRC = HERE.parents[1] / "src"
PKG = SRC / "decoy_engine" / "signed_evidence"
MODULES = load_modules_config(HERE / "file_access_modules.toml")
REGISTRY = load_registry(HERE / "file_access_registry.toml")
AMBIENT = "decoy_engine/fileaccess/_ambient_tree.py"
ROLES = Roles(
    adapters=frozenset(MODULES["adapter_modules"]),
    capabilities=frozenset(MODULES["capability_modules"]),
    local_constructors=frozenset(MODULES["local_constructors"]),
    creators=frozenset(MODULES["capability_creators"]),
)


def _call_names(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                names.append(f"{func.value.id}.{func.attr}")
    return names


def test_the_registry_holds_the_planned_number_of_entries() -> None:
    assert len(REGISTRY) == 205


def test_the_ambient_guard_is_named_in_both_module_lists() -> None:
    assert AMBIENT in MODULES["ambient_only_modules"]
    assert AMBIENT in MODULES["ambient_guards"]
    flagged = [e for e in REGISTRY if e["module"] == AMBIENT]
    assert len(flagged) == 1 and flagged[0].get("ambient_only") is True


def test_the_rooted_capability_module_gains_no_open() -> None:
    # `_rooted.py` is a pure capability module: it opens only through `_openat2`.
    assert "os.open" not in _call_names(SRC / "decoy_engine" / "fileaccess" / "_rooted.py")


def test_no_signed_evidence_module_opens_or_walks_a_path_itself() -> None:
    for path in sorted(PKG.glob("*.py")):
        calls = set(_call_names(path))
        assert not calls & {"os.open", "os.walk", "os.scandir", "os.listdir", "os.stat"}, path.name


def test_each_caller_of_the_ambient_open_has_its_own_entry() -> None:
    callers = {(e["module"], e["function"]) for e in REGISTRY if e["sink"] == "open_ambient_tree"}
    assert callers == {
        ("decoy_engine/signed_evidence/_artifacts.py", "open_path_tree"),
        ("decoy_engine/signed_evidence/_bundle.py", "open_signed_bundle"),
    }


def _scan(tmp_path: Path, files: dict[str, str]):  # type: ignore[no-untyped-def]
    root = tmp_path / "decoy_engine"
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    sites, _ = scan_tree(tmp_path)
    violations, _used = classify(sites, ROLES, registry_index([]))
    return violations


def test_a_scratch_open_in_a_signed_evidence_module_turns_the_sentry_red(tmp_path) -> None:  # type: ignore[no-untyped-def]
    violations = _scan(
        tmp_path,
        {
            "__init__.py": "",
            "signed_evidence/__init__.py": "",
            "signed_evidence/_artifacts.py": (
                "import os\n\ndef scratch(path):\n    return os.open(path, os.O_RDONLY)\n"
            ),
        },
    )
    assert any(v.site.sink == "os.open" for v in violations)


def test_an_unregistered_ambient_open_call_turns_the_sentry_red(tmp_path) -> None:  # type: ignore[no-untyped-def]
    violations = _scan(
        tmp_path,
        {
            "__init__.py": "",
            "fileaccess/__init__.py": "",
            "signed_evidence/__init__.py": "",
            "signed_evidence/_other.py": (
                "from decoy_engine import fileaccess\n\n"
                "def scratch(path):\n    return fileaccess.open_ambient_tree(path)\n"
            ),
        },
    )
    assert any(v.site.sink == "open_ambient_tree" for v in violations)
