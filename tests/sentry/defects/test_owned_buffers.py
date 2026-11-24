"""Execution writes only into arrays it owns (plan revision 2.6, I3 and D3).

A NumPy array that comes from `Series.to_numpy()` without `copy=True`, `.values`, `.array` or
`np.asarray(...)` may be a view of pandas memory: under copy-on-write it is read-only, and
otherwise a store changes the caller's frame. In one function, a subscript store into such a name
fails this sentry. Read-only uses of the same producers are fine.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXEC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "execution"
SCANNED = ("work_order", "_when_gate.py", "_strategies", "_fk_keys.py")


def _borrowed(value: ast.expr) -> bool:
    """Whether `value` may hand back memory the frame still owns."""
    if isinstance(value, ast.Attribute) and value.attr in {"values", "array"}:
        return True
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == "to_numpy":
        return not any(
            k.arg == "copy" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in value.keywords
        )
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "asarray"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"np", "numpy"}
    )


def borrowed_stores(source: str) -> list[tuple[str, int]]:
    """(function, line) of each subscript store into a name bound from a borrowing producer."""
    tree = ast.parse(source)
    found: list[tuple[str, int]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        borrowed: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and _borrowed(node.value):
                borrowed |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.Assign):  # a rebind to an owned value ends the borrow
                borrowed -= {
                    t.id
                    for t in node.targets
                    if isinstance(t, ast.Name) and isinstance(node.value, ast.Call)
                }
        for node in ast.walk(fn):
            targets = node.targets if isinstance(node, ast.Assign) else []
            if isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in borrowed
                ):
                    found.append((fn.name, node.lineno))
    return found


def _files() -> list[Path]:
    out: list[Path] = []
    for name in SCANNED:
        path = EXEC / name
        out += sorted(path.rglob("*.py")) if path.is_dir() else [path]
    return out


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.relative_to(EXEC).as_posix())
def test_no_store_into_a_borrowed_array(path: Path) -> None:
    assert not borrowed_stores(path.read_text()), path.name


@pytest.mark.parametrize(
    "seed",
    [
        "def f(s, p, x):\n    values = s.to_numpy(dtype=object)\n    values[p] = x\n",
        "def f(s, p, x):\n    values = s.values\n    values[p] = x\n",
        "def f(s, p, x):\n    values = s.array\n    values[p] = x\n",
        "def f(s, p, x):\n    values = np.asarray(s)\n    values[p] = x\n",
    ],
    ids=["to_numpy", "values", "array", "asarray"],
)
def test_a_seeded_borrowed_store_is_found(seed: str) -> None:
    assert borrowed_stores(seed)


@pytest.mark.parametrize(
    "owned",
    [
        "def f(s, p, x):\n    values = s.to_numpy(dtype=object, copy=True)\n    values[p] = x\n",
        "def f(s, p, x):\n    values = s.to_numpy().copy()\n    values[p] = x\n",
        "def f(s, p):\n    values = s.values\n    return values[p]\n",
    ],
    ids=["copy_true", "copied", "read_only"],
)
def test_owned_and_read_only_uses_pass(owned: str) -> None:
    assert not borrowed_stores(owned)
