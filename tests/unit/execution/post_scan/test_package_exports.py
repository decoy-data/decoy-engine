"""Code outside `pipeline/post_scan` uses the package's exports, never its underscore modules."""

from __future__ import annotations

import ast
from pathlib import Path

from decoy_engine.execution.pipeline import post_scan

SRC = Path(post_scan.__file__).resolve().parents[3]
PACKAGE = "decoy_engine.execution.pipeline.post_scan"
OWN_DIR = Path(post_scan.__file__).resolve().parent


def _private_imports(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(PACKAGE + "._") or (
                node.module == PACKAGE and any(a.name.startswith("_") for a in node.names)
            ):
                lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(a.name.startswith(PACKAGE + "._") for a in node.names):
                lines.append(node.lineno)
    return lines


def test_no_production_module_imports_a_private_post_scan_module() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if OWN_DIR in path.parents:
            continue
        for line in _private_imports(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(SRC)}:{line}")
    assert offenders == []


def test_the_guard_flags_a_private_import() -> None:
    bad = ast.parse(f"from {PACKAGE}._gate import settle\nfrom {PACKAGE} import _suite\n")
    assert _private_imports(bad) == [1, 2]
    assert _private_imports(ast.parse(f"from {PACKAGE} import settle\n")) == []


def test_every_name_in_all_resolves() -> None:
    for name in post_scan.__all__:
        assert callable(getattr(post_scan, name))
