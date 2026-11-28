"""Code outside `pipeline/post_scan` uses the package's exports, never its underscore modules."""

from __future__ import annotations

import ast

from decoy_engine.execution.pipeline import post_scan
from tests.sentry._platform_ast import engine_trees, import_map

PACKAGE = "decoy_engine.execution.pipeline.post_scan"
OWN_DIR = "decoy_engine/execution/pipeline/post_scan/"


def _private_imports(tree: ast.AST, rel: str) -> list[str]:
    """Every dotted name under the package with an underscore part, absolute or relative."""
    names = list(import_map(tree, rel).values())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
    prefix = PACKAGE.split(".")
    return [
        name
        for name in names
        if name.split(".")[: len(prefix)] == prefix
        and any(part.startswith("_") for part in name.split(".")[len(prefix) :])
    ]


def test_no_production_module_imports_a_private_post_scan_module() -> None:
    offenders = [
        rel
        for rel, tree in engine_trees().items()
        if not rel.startswith(OWN_DIR) and _private_imports(tree, rel)
    ]
    assert offenders == []


def test_the_guard_sees_every_spelling() -> None:
    rel = "decoy_engine/execution/_pipeline_route_dispatch.py"
    for line in (
        f"from {PACKAGE}._gate import settle",
        f"from {PACKAGE} import _suite",
        f"import {PACKAGE}._gate",
        "from .pipeline.post_scan._gate import settle",
        "from .pipeline.post_scan import _gate",
    ):
        assert _private_imports(ast.parse(line), rel) != [], line
    assert _private_imports(ast.parse(f"from {PACKAGE} import settle"), rel) == []
    assert _private_imports(ast.parse("from .pipeline.post_scan import settle"), rel) == []


def test_every_name_in_all_resolves() -> None:
    for name in post_scan.__all__:
        assert callable(getattr(post_scan, name))
