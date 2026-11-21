"""Every pandas mask-handler call in the execution package goes through the row guard.

A handler's `run(df, ...)` result is stitched back into a frame, so a call site that skips
`require_same_rows` lets a dropped or relabelled row through silently. The scan flags each
handler-like `.run(` call under `execution/` and requires the same function to call the guard.
A call is handler-like when its receiver (name or attribute) contains "handler", or its first
argument is a frame-named variable (`df`, `sub_df`, `tmp`, ...), so an alias such as
`h = self._handlers[k]; h.run(df, ...)` is still caught. Adapter, kernel and driver `.run(plan,
...)` calls take other first arguments and are not handler calls.
"""

from __future__ import annotations

import ast
from pathlib import Path

_EXEC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "execution"
_FRAME_ARGS = {"df", "sub_df", "temp_df", "tmp", "frame", "out"}
# Exempt call sites: file -> why the result never reaches the table frame.
_ALLOWED = {
    "_strategies/_orphan.py": "orphan-REMAP lookup runs on a private scratch frame",
    "_strategies/nested/_handler.py": "child cell runs on a scratch frame the caller rebuilds",
}


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_handler_run(call: ast.Call) -> bool:
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr == "run"):
        return False
    first = _name(call.args[0]) if call.args else ""
    return "handler" in _name(f.value).lower() or first in _FRAME_ARGS


def _scan(source: str, rel: str) -> tuple[list[str], int]:
    """Return (functions with an unguarded handler call, number of handler calls seen)."""
    missing: list[str] = []
    seen = 0
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        runs = [c for c in _calls(fn) if _is_handler_run(c)]
        seen += len(runs)
        if runs and not any(_name(c.func) == "require_same_rows" for c in _calls(fn)):
            missing.append(f"{rel}::{fn.name}")
    return sorted(set(missing)), seen


def _scan_tree() -> tuple[list[str], int]:
    missing: list[str] = []
    seen = 0
    for path in sorted(_EXEC.rglob("*.py")):
        rel = path.relative_to(_EXEC).as_posix()
        if rel in _ALLOWED:
            continue
        bad, n = _scan(path.read_text(encoding="utf-8"), rel)
        missing += bad
        seen += n
    return missing, seen


def test_every_handler_call_site_calls_the_guard() -> None:
    missing, _ = _scan_tree()
    assert not missing, f"handler.run without require_same_rows in: {missing}"


def test_the_scan_finds_the_known_call_sites() -> None:
    # Three: the plain and gated calls in run_with_when_gate, and the composite dispatch.
    _, seen = _scan_tree()
    assert seen >= 3


def test_the_allowlist_entries_still_have_a_handler_call() -> None:
    for rel in _ALLOWED:
        _, seen = _scan((_EXEC / rel).read_text(encoding="utf-8"), rel)
        assert seen, f"{rel} no longer calls a handler; drop it from _ALLOWED"


def test_the_scan_catches_aliased_and_unguarded_calls() -> None:
    aliased = "def f(self, df):\n    h = self._h['x']\n    return h.run(df, 'c', None, None)\n"
    guarded = "def f(self, df):\n    h = 1\n    h.run(df, 'c', 1, 1)\n    require_same_rows(1, 2)\n"
    assert _scan(aliased, "x.py") == (["x.py::f"], 1)
    assert _scan(guarded, "x.py") == ([], 1)
