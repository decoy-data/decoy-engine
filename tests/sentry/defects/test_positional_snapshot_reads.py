"""Pre-mask snapshots are read by position, in one place (plan revision 2.6, L1).

`ctx.group_anchor_snapshots` is loaded (read, `.get`, iterated) only inside `snapshot_rows`; the
snapshot builders of the two routes may store into it. The modules that read snapshots or write
gated results back never use label alignment (`.loc`, `.reindex`, `.align`), so a repeated or
unsorted index cannot reach them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
EXEC = SRC / "execution"
FIELD = "group_anchor_snapshots"
# The one reader, and the one load that touches keys only (evicting a finished table).
READERS = {("work_order/rows.py", "snapshot_rows"), ("_sequential.py", "run_sequential")}
GUARDED = (
    "_when_gate.py",
    "_strategies/_joint_mask.py",
    "_strategies/_date_shift.py",
    "work_order/rows.py",
)
LABEL_ACCESS = {"loc", "reindex", "align"}


def snapshot_loads(source: str, relpath: str) -> set[tuple[str, str]]:
    """(path, enclosing function) of every load of the snapshot field; stores and deletes through
    a subscript are not loads of its values."""
    tree = ast.parse(source)
    out: set[tuple[str, str]] = set()

    def visit(node: ast.AST, function: str, writes: bool) -> None:
        for child in ast.iter_child_nodes(node):
            here = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else function
            )
            store_target = isinstance(child, ast.Subscript) and isinstance(
                child.ctx, ast.Store | ast.Del
            )
            if isinstance(child, ast.Attribute) and child.attr == FIELD and not writes:
                if not isinstance(child.ctx, ast.Store):
                    out.add((relpath, here))
            visit(child, here, store_target)

    visit(tree, "<module>", False)
    return out


def label_access(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in LABEL_ACCESS
    }


def test_only_snapshot_rows_loads_the_snapshots() -> None:
    loads: set[tuple[str, str]] = set()
    for path in EXEC.rglob("*.py"):
        loads |= snapshot_loads(path.read_text(), path.relative_to(EXEC).as_posix())
    assert loads <= READERS, sorted(loads - READERS)
    assert ("work_order/rows.py", "snapshot_rows") in loads


@pytest.mark.parametrize("relpath", GUARDED)
def test_no_label_alignment_in_the_snapshot_modules(relpath: str) -> None:
    assert not label_access((EXEC / relpath).read_text()), relpath


@pytest.mark.parametrize("relpath", GUARDED)
@pytest.mark.parametrize("seed", [".loc[df.index]", ".reindex(df.index)", ".align(other)"])
def test_a_seeded_label_lookup_is_found(relpath: str, seed: str) -> None:
    source = f"def f(df, other):\n    return df{seed}\n"
    assert label_access(source), (relpath, seed)


def test_a_seeded_snapshot_load_is_found_and_a_store_is_not() -> None:
    reader = "def g(ctx):\n    return ctx.group_anchor_snapshots.get(('t', 'c'))\n"
    loop = "def g(ctx):\n    return [k for k in ctx.group_anchor_snapshots]\n"
    store = "def g(ctx, s):\n    ctx.group_anchor_snapshots[('t', 'c')] = s\n"
    delete = "def g(ctx):\n    del ctx.group_anchor_snapshots[('t', 'c')]\n"
    assert snapshot_loads(reader, "_when_gate.py") == {("_when_gate.py", "g")}
    assert snapshot_loads(loop, "_when_gate.py") == {("_when_gate.py", "g")}
    assert not snapshot_loads(store, "_pandas_adapter.py")
    assert not snapshot_loads(delete, "_sequential.py")
