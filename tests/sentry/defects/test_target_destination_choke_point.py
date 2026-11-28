"""DUP-DEST choke point: one grouping function decides "same destination".

`PipelineConfig` and the starter builder both call public `duplicate_target_groups`. The private
identity primitive is named only inside `config/_targets.py`, so a caller cannot bypass the one
grouping loop with its own comparison. Aliased imports, module-attribute calls and plain
re-bindings are resolved; deliberate evasion (`getattr`, `exec`) is not modelled.
"""

from __future__ import annotations

import ast

import pytest

from tests.sentry._call_resolution import local_names, resolved_calls
from tests.sentry.defects import _defect_scan as scan

PRIVATE = "_target_identity"
PUBLIC = "duplicate_target_groups"
OWNER = "config/_targets.py"
CALLERS = ("config/_pipeline.py", "profiling/_starter_targets.py")


def private_uses(tree: ast.AST) -> list[int]:
    """Line numbers where the private identity is imported, named, aliased or called."""
    names = local_names(tree, PRIVATE)
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            (isinstance(node, ast.ImportFrom) and any(a.name == PRIVATE for a in node.names))
            or (isinstance(node, ast.Name) and node.id in names)
            or (isinstance(node, ast.Attribute) and node.attr == PRIVATE)
        ):
            lines.append(node.lineno)
    return lines


def calls_public(tree: ast.AST) -> bool:
    return bool(resolved_calls(tree, PUBLIC))


def _trees() -> dict[str, ast.Module]:
    return {p.relative_to(scan.SRC).as_posix(): t for p, t in scan.ModuleIndex().trees.items()}


def test_the_private_identity_is_named_only_inside_its_owner() -> None:
    leaks = {rel: private_uses(t) for rel, t in _trees().items() if rel != OWNER}
    assert not {k: v for k, v in leaks.items() if v}, (
        f"{PRIVATE} is private to {OWNER}; call {PUBLIC} instead"
    )


def test_the_owner_still_defines_both_functions() -> None:
    tree = _trees()[OWNER]
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {PRIVATE, PUBLIC} <= defined


@pytest.mark.parametrize("rel", CALLERS)
def test_each_caller_goes_through_the_public_grouping_function(rel: str) -> None:
    assert calls_public(_trees()[rel]), f"{rel} must call {PUBLIC}"


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine.config._targets import _target_identity\n",
        "from decoy_engine.config._targets import _target_identity as t\ndef f(x):\n    return t(x)\n",
        "from decoy_engine.config import _targets\ndef f(x):\n    return _targets._target_identity(x)\n",
        "import decoy_engine.config._targets as m\ndef f(x):\n    return m._target_identity(x)\n",
        "import decoy_engine.config._targets\n"
        "def f(x):\n    return decoy_engine.config._targets._target_identity(x)\n",
        "from decoy_engine.config._targets import _target_identity\nf = _target_identity\n",
    ],
)
def test_the_scanner_hits_each_seeded_bypass(source: str) -> None:
    assert private_uses(ast.parse(source)), source


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine.config import duplicate_target_groups as g\ndef f(x):\n    return g(x, [])\n",
        "from decoy_engine import config\ndef f(x):\n    return config.duplicate_target_groups(x, [])\n",
        "from decoy_engine.config import duplicate_target_groups\nduplicate_target_groups({}, [])\n",
    ],
)
def test_the_scanner_sees_each_public_call_spelling(source: str) -> None:
    tree = ast.parse(source)
    assert calls_public(tree)
    assert not private_uses(tree)


def test_a_module_with_no_grouping_call_is_flagged() -> None:
    assert not calls_public(ast.parse("def f(x):\n    return x\n"))
