"""Sentry: one rule decides a bucketize column's effective width.

``contracts/bucketize_width.py`` resolves ``preset`` and ``width``. The handler, the compile check,
the shape rule and the F06 proof call it; none of them reads either key itself, and none keeps a
preset table of its own. A second reader is a second width rule, so it fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
HOME = "contracts/bucketize_width.py"
MODULE = "decoy_engine.contracts.bucketize_width"
RESOLVERS = ("resolve_bucketize_width", "unresolvable_width_field")
KEYS = frozenset({"preset", "width"})

# file under src/decoy_engine -> why it may call the resolver
ALLOWED_CALLERS: dict[str, str] = {
    "execution/_strategies/_bucketize.py": "the handler resolves the width it buckets by",
    "plan/_checks_bucketize.py": "the compile check refuses an unresolvable width",
    "contracts/strategy_requirements.py": "the shape rule tests a decimal column's width",
    "plan/_checks_declared_casting.py": "the F06 proof tests whether the width is an integer",
}

# The files whose width logic the contract replaced: they must not read the keys themselves. The
# F06 module also reads a fixed-width layout's `width`, so only its proof function is guarded.
GUARDED: dict[str, str | None] = {
    "execution/_strategies/_bucketize.py": None,
    "plan/_checks_bucketize.py": None,
    "contracts/strategy_requirements.py": None,
    "plan/_checks_declared_casting.py": "strategy_output_logical",
}


def _call_sites(root: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == HOME:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            a.asname or a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module == MODULE
            for a in n.names
            if a.name in RESOLVERS
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in imported:
                    found.add(rel)
    return found


def _key_reads(path: Path, function: str | None = None) -> list[int]:
    """Lines that read ``preset`` or ``width`` from a mapping, by ``.get`` or subscript.

    With ``function``, only that function's body is read.
    """
    lines: list[int] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if function is not None:
        tree = ast.Module(
            body=[
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function
            ],
            type_ignores=[],
        )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in KEYS
        ) or (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in KEYS
        ):
            lines.append(node.lineno)
    return lines


def test_only_the_named_files_call_the_resolver() -> None:
    assert _call_sites(SRC) == set(ALLOWED_CALLERS)


def test_every_allowance_has_a_reason() -> None:
    assert all(r.strip() for r in ALLOWED_CALLERS.values())


@pytest.mark.parametrize("rel", sorted(GUARDED))
def test_a_guarded_file_does_not_read_the_keys_itself(rel: str) -> None:
    assert _key_reads(SRC / rel, GUARDED[rel]) == []


def test_no_module_keeps_a_preset_table_of_its_own() -> None:
    """A preset name as a string literal outside the contract is a second table."""
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == HOME:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in {"by_decade", "by_century"}:
                raise AssertionError(f"{rel}:{node.lineno} names a bucketize preset")


def test_the_sentry_catches_a_planted_caller(tmp_path: Path) -> None:
    probe = tmp_path / "execution" / "_p.py"
    probe.parent.mkdir()
    probe.write_text(
        "from decoy_engine.contracts.bucketize_width import resolve_bucketize_width\n"
        "x = resolve_bucketize_width({})\n",
        encoding="utf-8",
    )
    assert _call_sites(tmp_path) == {"execution/_p.py"}


def test_the_sentry_catches_a_planted_key_read(tmp_path: Path) -> None:
    probe = tmp_path / "p.py"
    probe.write_text("cfg = {}\na = cfg.get('width')\nb = cfg['preset']\n", encoding="utf-8")
    assert _key_reads(probe) == [2, 3]


def test_a_function_scope_ignores_reads_elsewhere(tmp_path: Path) -> None:
    probe = tmp_path / "p.py"
    probe.write_text(
        "def other(c):\n    return c.get('width')\n\ndef proof(c):\n    return c['width']\n",
        encoding="utf-8",
    )
    assert _key_reads(probe, "proof") == [5]
    assert _key_reads(probe, "missing") == []
