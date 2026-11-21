"""Sentry: the vault crypto and format live in one module (`vault/_format.py`).

`nacl` is imported only there, the vault key label appears once in `src/`, and the vault package does not import
`cryptography.fernet` (the v2 cipher; the secret-provider Fernet key requirement is a different use). The scan resolves `import x as y`, `from x import y` and
`importlib` strings, so the realistic ways of reaching the cipher from another module are caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
OWNER = "decoy_engine/vault/_format.py"
KEY_LABEL = b"vault-key/v2"


def _imports(tree: ast.AST) -> set[str]:
    """Every dotted module name the tree imports, by statement or by `importlib` string."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            callee = ast.unparse(node.func)
            if callee.endswith(("import_module", "__import__")) and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def _key_label_count(tree: ast.AST) -> int:
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == KEY_LABEL)


def scan(sources: dict[str, str]) -> list[str]:
    """Violations over `{relative path: source}`."""
    problems: list[str] = []
    label_count = 0
    for rel, text in sources.items():
        tree = ast.parse(text)
        modules = _imports(tree)
        if rel != OWNER and any(m == "nacl" or m.startswith("nacl.") for m in modules):
            problems.append(f"{rel}: imports nacl")
        if rel.startswith("decoy_engine/vault/") and any(
            m.startswith("cryptography.fernet") for m in modules
        ):
            problems.append(f"{rel}: imports cryptography.fernet")
        label_count += _key_label_count(tree)
    if label_count != 1:
        problems.append(f"the vault key label appears {label_count} times, not once")
    return problems


def _source() -> dict[str, str]:
    return {
        str(p.relative_to(SRC)): p.read_text(encoding="utf-8")
        for p in (SRC / "decoy_engine").rglob("*.py")
    }


def test_the_tree_holds() -> None:
    assert scan(_source()) == []


def test_the_owner_module_is_where_nacl_is_imported() -> None:
    assert any(m.startswith("nacl") for m in _imports(ast.parse(_source()[OWNER])))


def _seeded(extra_path: str, extra_text: str) -> list[str]:
    sources = dict(_source())
    sources[extra_path] = extra_text
    return scan(sources)


def test_seeded_nacl_import_elsewhere_fails() -> None:
    assert _seeded("decoy_engine/vault/_reader.py", "import nacl.bindings\n")
    assert _seeded("decoy_engine/x.py", "from nacl import bindings as b\n")
    assert _seeded(
        "decoy_engine/x.py", "import importlib\nimportlib.import_module('nacl.bindings')\n"
    )


def test_seeded_fernet_import_fails() -> None:
    assert _seeded("decoy_engine/vault/_x.py", "from cryptography.fernet import Fernet\n")


def test_seeded_second_key_label_fails() -> None:
    assert _seeded("decoy_engine/x.py", "LABEL = b'vault-key/v2'\n")
