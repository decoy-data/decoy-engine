"""A broad handler on the isolated commit, replay and vault-read path never swallows a memory error.

`MemoryError` (Arrow's `ArrowMemoryError` is one) caught by `except Exception`, `except
BaseException` or `except pyarrow.ArrowException` becomes a data verdict: a refused unit, a
malformed vault segment, a wrong publication state. The isolated driver's guard can only pick the
right result if the memory error reaches it. The rule, in `fileaccess.reraise_memory`: such a
handler calls it first. A handler is also fine when it names `MemoryError` itself or re-raises
with a bare `raise` (the cleanup handlers).

Scope: `publication/`, `vault/` and `execution/_isolated_commit.py`, the modules the commit and
the replay verification run through.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
SCOPE = [
    *sorted((SRC / "publication").glob("*.py")),
    *sorted((SRC / "vault").glob("*.py")),
    SRC / "execution" / "_isolated_commit.py",
]
BROAD = frozenset({"Exception", "BaseException", "ArrowException"})


def _names(node: ast.expr | None) -> set[str]:
    if node is None:
        return {"BaseException"}  # a bare `except:` catches everything
    if isinstance(node, ast.Tuple):
        return set().union(*(_names(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _calls_rule(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "reraise_memory":
                return True
    return False


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) and n.exc is None for n in handler.body)


def findings(source: str, label: str) -> list[str]:
    """The broad handlers in `source` that route a memory error nowhere."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        caught = _names(node.type)
        if not caught & BROAD or "MemoryError" in caught:
            continue
        if _calls_rule(node) or _reraises(node):
            continue
        out.append(f"{label}:{node.lineno} catches {sorted(caught & BROAD)} without the rule")
    return out


def test_the_scope_is_not_empty() -> None:
    assert len(SCOPE) > 10
    assert all(p.is_file() for p in SCOPE)


def test_every_broad_handler_on_the_commit_path_routes_memory_errors() -> None:
    bad: list[str] = []
    for path in SCOPE:
        bad += findings(path.read_text(encoding="utf-8"), str(path.relative_to(SRC)))
    assert not bad, "call fileaccess.reraise_memory(exc) first in:\n" + "\n".join(bad)


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    f()\nexcept Exception as exc:\n    return exc\n",
        "try:\n    f()\nexcept (OSError, pa.ArrowException):\n    pass\n",
        "try:\n    f()\nexcept BaseException:\n    cleanup()\n",
        "try:\n    f()\nexcept:\n    pass\n",
    ],
)
def test_the_scan_sees_a_handler_without_the_rule(source: str) -> None:
    assert findings(source, "x.py")


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    f()\nexcept Exception as exc:\n    reraise_memory(exc)\n    return exc\n",
        "try:\n    f()\nexcept BaseException:\n    cleanup()\n    raise\n",
        "try:\n    f()\nexcept (OSError, MemoryError, pa.ArrowException):\n    pass\n",
        "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n",
    ],
)
def test_the_scan_accepts_the_allowed_shapes(source: str) -> None:
    assert not findings(source, "x.py")
