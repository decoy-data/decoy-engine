"""One file-identity protocol for every file-backed lazy source in `decoy_engine.profile`.

A `LazySource` subclass that reads a plain file (CSV, fixed-width) has no footer, so it must
check the file's identity around its facts pass and its batch read. That protocol lives in
`profile/_lazy_identity.py` (`LazyFileIdentity`). A subclass that took its own stat, kept its own
fact cache or raised `lazy_source_changed` itself would be a second copy that can drift, and the
check that a copy forgets is the one that routes on one file and reads another.

Offenders, per module under `profile/` other than the helper: a `LazySource` subclass without
`LazyFileIdentity` among its bases (the Parquet `LazySource` in `_readers.py` is the base, with a
footer, and is exempt), a method named `_identity`, or a call to `lazy_source_changed`.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "decoy_engine"
PROFILE = SRC / "profile"
HELPER = "_lazy_identity.py"
BASE_MODULE = "_readers.py"


def _base_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def violations(source: str, *, is_base_module: bool = False) -> list[str]:
    """What a module under `profile/` does that bypasses the shared identity helper."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            bases = _base_names(node)
            if "LazySource" in bases and "LazyFileIdentity" not in bases and not is_base_module:
                found.append(f"{node.lineno}: {node.name} subclasses LazySource without the helper")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_identity":
            found.append(f"{node.lineno}: own _identity")
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called == "lazy_source_changed":
                found.append(f"{node.lineno}: calls lazy_source_changed")
    return found


def test_every_file_backed_lazy_source_uses_the_shared_identity_helper() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(PROFILE.glob("*.py")):
        if path.name == HELPER:
            continue
        found = violations(
            path.read_text(encoding="utf-8"), is_base_module=path.name == BASE_MODULE
        )
        if found:
            offenders[path.name] = found
    assert not offenders, f"file identity handled outside profile/{HELPER}: {offenders}"


def test_the_sentry_sees_the_helper_and_both_backends() -> None:
    helper = (PROFILE / HELPER).read_text(encoding="utf-8")
    assert {"own _identity", "calls lazy_source_changed"} <= {
        line.split(": ", 1)[1] for line in violations(helper)
    }
    for name in ("_lazy_csv.py", "_lazy_fixed_width.py"):
        text = (PROFILE / name).read_text(encoding="utf-8")
        assert "LazyFileIdentity" in text and "LazySource" in text


def test_the_walk_sees_a_seeded_violation_per_spelling() -> None:
    own_class = "class Mine(LazySource):\n    pass\n"
    assert violations(own_class) == ["1: Mine subclasses LazySource without the helper"]
    dotted = "class Mine(_readers.LazySource):\n    pass\n"
    assert len(violations(dotted)) == 1
    assert violations("class Mine(LazyFileIdentity, LazySource):\n    pass\n") == []
    assert violations("class A:\n    def _identity(self):\n        return 1\n") == [
        "2: own _identity"
    ]
    assert violations("raise lazy_source_changed(t, 'x')\n") == ["1: calls lazy_source_changed"]
    assert violations("raise mod.lazy_source_changed(t, 'x')\n") == ["1: calls lazy_source_changed"]
    assert violations(own_class, is_base_module=True) == []
    assert violations("from x import lazy_source_changed as lazy_source_changed\n") == []
