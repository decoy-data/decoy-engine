"""One reader of a nested column's child strategy and config (F07 choke point).

A `nested` column keeps its child under `provider_config.strategy` and `.strategy_config`. A module
that tests a strategy against `"nested"` and then reads those keys itself would miss the `rules`
form 82-E3b adds, and skip a plan refusal for it. Every such module must call `nested_children`
from `decoy_engine._nested_json`, which is the only reader.

The scan is per module. A module is a reader when it has a `"nested"` literal in a comparison
(`==`, `!=`, `in`, `not in`) or as a dict key, and a child read: `.get("strategy")`,
`["strategy"]`, `.get("strategy_config")` or `["strategy_config"]`. A reader must import and call
`nested_children`. Registries that name `"nested"` in a set or table without reading the child
(for example `validators/_leak_check.py`) have no comparison or key, so the shape does not match
them. Deliberate evasion (`getattr`, a key built at run time) is not modelled.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._call_resolution import resolved_calls
from tests.sentry.defects import _defect_scan as scan

OWNER = "_nested_json/_rules.py"
CHILD_KEYS = ("strategy", "strategy_config")
# The seven modules the plan names; each must be found as a reader and be migrated.
READERS = (
    "execution/_column_access.py",
    "execution/_pipeline_multi_table.py",
    "execution/_strategies/nested/_handler.py",
    "plan/_checks_bucket_perturb.py",
    "plan/_checks_date_shift.py",
    "plan/_checks_top_code.py",
    "secret_providers/_requirements.py",
)


def _is_nested(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "nested"


def _names_nested(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                if _is_nested(side):
                    return True
                if isinstance(side, (ast.Tuple, ast.List, ast.Set)) and any(
                    _is_nested(e) for e in side.elts
                ):
                    return True
        if isinstance(node, ast.Dict) and any(k is not None and _is_nested(k) for k in node.keys):
            return True
    return False


def _reads_child(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in CHILD_KEYS
        ):
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in CHILD_KEYS
        ):
            return True
    return False


def is_reader(tree: ast.AST) -> bool:
    return _names_nested(tree) and _reads_child(tree)


def uses_choke_point(tree: ast.AST) -> bool:
    imported = any(
        isinstance(n, ast.ImportFrom) and any(a.name == "nested_children" for a in n.names)
        for n in ast.walk(tree)
    )
    return imported and bool(resolved_calls(tree, "nested_children"))


def unmigrated(tree: ast.AST) -> bool:
    return is_reader(tree) and not uses_choke_point(tree)


def _files() -> list[Path]:
    return [p for p in scan.source_files() if p.relative_to(scan.SRC).as_posix() != OWNER]


def test_every_reader_of_a_nested_child_uses_the_choke_point() -> None:
    bad = [
        p.relative_to(scan.SRC).as_posix() for p in _files() if unmigrated(ast.parse(p.read_text()))
    ]
    assert not bad, (
        "read a nested column's child through decoy_engine._nested_json.nested_children, "
        f"not provider_config strategy keys: {bad}"
    )


def test_the_known_readers_are_found_by_the_scan() -> None:
    found = {
        p.relative_to(scan.SRC).as_posix() for p in _files() if is_reader(ast.parse(p.read_text()))
    }
    assert set(READERS) <= found


def test_the_registry_that_only_names_nested_is_not_a_reader() -> None:
    tree = ast.parse((scan.SRC / "validators/_leak_check.py").read_text())
    assert not is_reader(tree)


@pytest.mark.parametrize(
    "source",
    [
        'def f(c, pc):\n    return c["strategy"] == "nested" and pc.get("strategy")\n',
        'def f(c, pc):\n    return c["strategy"] == "nested" and pc["strategy"]\n',
        'def f(c, pc):\n    return c["strategy"] != "nested" or pc.get("strategy_config")\n',
        'def f(c, pc):\n    if c["strategy"] in ("nested", "x"):\n        return pc["strategy_config"]\n',
        'def f(c, pc):\n    if c["strategy"] in {"x", "nested"}:\n        return pc.get("strategy")\n',
        'T = {"nested": 1}\ndef f(pc):\n    return pc.get("strategy_config")\n',
        'def f(c, pc):\n    return "nested" == c["strategy"] and pc.get("strategy")\n',
        'from decoy_engine._nested_json import other\n'
        'def f(c, pc):\n    return c["strategy"] == "nested" and pc.get("strategy")\n',
    ],
)
def test_the_scan_is_red_on_each_seeded_shape(source: str) -> None:
    assert unmigrated(ast.parse(source)), source


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine._nested_json import nested_children\n"
        'def f(c, pc):\n    return c["strategy"] == "nested" and nested_children(pc)\n',
        "from decoy_engine._nested_json import nested_children as kids\n"
        'def f(c, pc):\n    return c["strategy"] == "nested" and kids(pc)\n',
        'def f(c):\n    return c["strategy"] == "nested"\n',
        'def f(pc):\n    return pc.get("strategy")\n',
        'KNOWN = frozenset({"nested"})\ndef f(pc):\n    return pc.get("strategy")\n',
    ],
)
def test_the_scan_is_green_on_a_migrated_or_unrelated_module(source: str) -> None:
    assert not unmigrated(ast.parse(source)), source
