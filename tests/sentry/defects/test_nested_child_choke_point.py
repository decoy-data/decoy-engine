"""One reader of a nested column's child strategy and config (F07 choke point).

A `nested` column keeps its child under `provider_config.strategy` and `.strategy_config`. A module
that tests a strategy against `"nested"` and then reads those keys itself would miss the `rules`
form 82-E3b adds, and skip a plan refusal for it. Every such module must call `nested_children`
from `decoy_engine._nested_json`, which is the only reader.

A module is in scope when it has a `"nested"` literal in a comparison
(`==`, `!=`, `in`, `not in`) or as a dict key (`"nested"` or a prefixed key such as
`"scalar:nested"`). In scope, a child read is `.get("strategy")` or `["strategy"]` off a provider
config, or `.get("strategy_config")` or `["strategy_config"]`. Enforcement is per read: every direct read is flagged, also in a module that calls
`nested_children` elsewhere. A module that reads the child must go through `nested_children`
for all of it. Registries that name `"nested"` in a set or table without reading the child
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
PROVIDER_CONFIG_NAMES = frozenset({"pc", "cfg", "config", "provider_cfg", "pcfg", "pconf"})
# The seven modules that read a nested child at the slice base; each must call the choke point.
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


def _is_nested_key(node: ast.AST | None) -> bool:
    """A dict key for the strategy: `"nested"`, or a prefixed registry key like `"scalar:nested"`."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == "nested" or node.value.endswith(":nested"))
    )


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
        if isinstance(node, ast.Dict) and any(_is_nested_key(k) for k in node.keys):
            return True
    return False


def _receiver(node: ast.AST) -> str:
    """The last name of the object a key is read from: `pc` for `pc.get(..)`, else ''."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_provider_config(receiver: str) -> bool:
    return receiver in PROVIDER_CONFIG_NAMES or "provider_config" in receiver


def direct_child_reads(tree: ast.AST) -> list[int]:
    """Lines that read a nested child key straight off a provider config.

    `strategy_config` is a child key whatever it is read from. `strategy` is also the column's
    own key (`col_entry.get("strategy")`), so it counts only when read from a provider-config
    looking name (`pc`, `cfg`, `provider_config`, ...). Per read, not per module: a module that
    also calls `nested_children` is still flagged for each direct read it keeps.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        key: object = None
        receiver = ""
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            key, receiver = node.args[0].value, _receiver(node.func.value)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            key, receiver = node.slice.value, _receiver(node.value)
        if key == "strategy_config" or (key == "strategy" and _is_provider_config(receiver)):
            lines.append(node.lineno)
    return lines


def is_reader(tree: ast.AST) -> bool:
    return _names_nested(tree) and bool(direct_child_reads(tree))


def uses_choke_point(tree: ast.AST) -> bool:
    imported = any(
        isinstance(n, ast.ImportFrom) and any(a.name == "nested_children" for a in n.names)
        for n in ast.walk(tree)
    )
    return imported and bool(resolved_calls(tree, "nested_children"))


def unmigrated(tree: ast.AST) -> bool:
    """A module that names `nested` and still reads a child key itself."""
    return is_reader(tree)


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


def test_each_known_reader_calls_the_choke_point() -> None:
    missing = [
        rel for rel in READERS if not uses_choke_point(ast.parse((scan.SRC / rel).read_text()))
    ]
    assert not missing, (
        f"these modules read a nested child and must call nested_children: {missing}"
    )


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
        # A module that calls nested_children and still reads a child key directly.
        "from decoy_engine._nested_json import nested_children\n"
        "def f(c, pc):\n    kids = nested_children(pc)\n"
        '    return c["strategy"] == "nested" and pc.get("strategy_config")\n',
        "from decoy_engine._nested_json import nested_children\n"
        "def f(c, pc):\n    kids = nested_children(pc)\n"
        '    return c["strategy"] == "nested" and pc["strategy"]\n',
        'T = {"scalar:nested": 1}\ndef f(pc):\n    return pc.get("strategy_config")\n',
        'T = {"nested": 1}\ndef f(pc):\n    return pc.get("strategy_config")\n',
        'def f(c, pc):\n    return "nested" == c["strategy"] and pc.get("strategy")\n',
        "from decoy_engine._nested_json import other\n"
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
        'def f(c):\n    return c["kind"] == "nested"\n',
        'def f(pc):\n    return pc.get("strategy")\n',
        'KNOWN = frozenset({"nested"})\ndef f(pc):\n    return pc.get("strategy")\n',
    ],
)
def test_the_scan_is_green_on_a_migrated_or_unrelated_module(source: str) -> None:
    assert not unmigrated(ast.parse(source)), source
