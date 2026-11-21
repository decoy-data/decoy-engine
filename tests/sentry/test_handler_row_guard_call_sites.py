"""Every pandas mask-handler call in the execution package goes through the row guard.

A handler's `run(df, ...)` result is stitched back into a frame, so a call site that skips
`require_same_rows` lets a dropped or relabelled row through silently. The scan finds each
`<handler>.run(` call under `execution/` and requires the same function to call the guard.
The two listed files run a handler on a private scratch frame (an orphan-REMAP lookup, a nested
child cell) whose rows are rebuilt by the caller, so the result never reaches the table frame.
"""

from __future__ import annotations

import ast
from pathlib import Path

_EXEC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "execution"
_RECEIVERS = {"handler", "child_handler", "_composite_handler"}
_SCRATCH_FRAME = {"_strategies/_orphan.py", "_strategies/nested/_handler.py"}


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _is_handler_run(call: ast.Call) -> bool:
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr == "run"):
        return False
    recv = f.value
    return (isinstance(recv, ast.Name) and recv.id in _RECEIVERS) or (
        isinstance(recv, ast.Attribute) and recv.attr in _RECEIVERS
    )


def _scan() -> tuple[list[str], int]:
    missing: list[str] = []
    seen = 0
    for path in sorted(_EXEC.rglob("*.py")):
        rel = path.relative_to(_EXEC).as_posix()
        if rel in _SCRATCH_FRAME or rel == "_gated_string_guard.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            runs = [c for c in _calls(fn) if _is_handler_run(c)]
            if not runs:
                continue
            seen += len(runs)
            guarded = any(
                isinstance(c.func, ast.Name) and c.func.id == "require_same_rows"
                for c in _calls(fn)
            )
            if not guarded:
                missing.append(f"{rel}::{fn.name}")
    return sorted(set(missing)), seen


def test_every_handler_call_site_calls_the_guard() -> None:
    missing, _ = _scan()
    assert not missing, f"handler.run without require_same_rows in: {missing}"


def test_the_scan_finds_the_known_call_sites() -> None:
    # Three: the plain and gated calls in run_with_when_gate, and the composite dispatch.
    _, seen = _scan()
    assert seen >= 3
