"""AT-E15: the signed filesystem routes refuse an unsupported platform before any opener.

An AST guard derives the signed filesystem entries from the facade (a public function that reaches
the one ambient opener) and requires each to call ``require_supported_platform``. A seeded bypass
turns it red.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import decoy_engine.signed_evidence as se

PKG = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "signed_evidence"
OPENERS = {"open_ambient_tree", "open_path_tree"}
GUARD = "require_supported_platform"


def _functions(sources: dict[str, str]) -> dict[str, ast.FunctionDef]:
    out: dict[str, ast.FunctionDef] = {}
    for source in sources.values():
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef):
                out[node.name] = node
    return out


def _called(fn: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return names


def filesystem_entries(sources: dict[str, str], public: set[str]) -> set[str]:
    """Public functions that reach an opener, directly or through another package function."""
    fns = _functions(sources)
    reach = {n for n, fn in fns.items() if _called(fn) & OPENERS}
    changed = True
    while changed:
        changed = False
        for name, fn in fns.items():
            if name not in reach and _called(fn) & reach:
                reach.add(name)
                changed = True
    return {n for n in reach if n in public}


def unguarded(sources: dict[str, str], public: set[str]) -> list[str]:
    fns = _functions(sources)
    return sorted(n for n in filesystem_entries(sources, public) if GUARD not in _called(fns[n]))


def _real() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py"))}


def test_the_derived_entries_are_the_two_signed_filesystem_routes() -> None:
    assert filesystem_entries(_real(), set(se.__all__)) == {
        "open_signed_bundle",
        "verify_signed_evidence",
    }


def test_each_entry_calls_the_platform_guard() -> None:
    assert unguarded(_real(), set(se.__all__)) == []


@pytest.mark.parametrize("target", ["open_signed_bundle", "verify_signed_evidence"])
def test_a_seeded_bypass_turns_the_guard_red(target: str) -> None:
    sources = _real()
    for name, text in sources.items():
        if f"def {target}" in text:
            sources[name] = text.replace(f"{GUARD}()", "pass", 1)
    assert target in unguarded(sources, set(se.__all__))


def test_the_guard_runs_before_the_opener_in_each_entry() -> None:
    fns = _functions(_real())
    for name in ("open_signed_bundle", "verify_signed_evidence"):
        order = [
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(fns[name])
            if isinstance(n, ast.Call)
        ]
        assert GUARD in order
