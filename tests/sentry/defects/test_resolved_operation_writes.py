"""One write authority: every consumer of "what does this node write" reads the resolved operation.

A stub strategy `z_aux` declares a secondary output `aux` that no config entry, node column or
ordinary handler declaration names. The declaration is injected where the resolver reads it, and
each consumer must act on `aux`: the predicate snapshot set, both carry callers and the gated
stitch. A consumer that kept its own write list would miss it. (Ordering is main's `order_work`
and its writer map, unchanged in S2a, so it is covered by the differential test instead.) An AST guard keeps raw declaration lookups inside the resolver and its registry helpers.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution import _column_access as ca
from decoy_engine.execution._chunked_carry import passthrough_columns, untouched_columns
from decoy_engine.execution._runner import build_work_list, source_snapshot_columns
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution.work_order import compile_work_order
from tests.unit.execution.when import _write_support as ws

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "execution"


class _AuxHandler:
    """Writes its own column and the secondary output `aux`, row by row."""

    name = "z_aux"
    namespace_required = False
    join_safe = False

    def run(self, df: pd.DataFrame, column: str, plan: Any, ctx: Any) -> tuple[pd.DataFrame, list]:
        df[column] = ["OWN"] * len(df)
        df["aux"] = ["AUX"] * len(df)
        return df, []


@pytest.fixture
def aux_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    def declare(entry: Any) -> ca.ColumnAccess:
        return ca.ColumnAccess(writes=frozenset({entry["name"], "aux"}))

    monkeypatch.setitem(ca.SURFACE_DECLARATIONS, "scalar:z_aux", declare)
    monkeypatch.setitem(SCALAR_HANDLERS, "z_aux", _AuxHandler())


def _plan(when: str | None = None, reader: bool = True) -> Any:
    cols = [("owner", ws.seed("z_aux", when=when))]
    if reader:
        cols.append(("z_reader", ws.derived('concat(aux, "!")')))
    return ws.plan(cols)


def _table() -> pa.Table:
    return pa.table(
        {
            "owner": pa.array(["o0", "o1", "o2", "o3"]),
            "aux": pa.array(["a0", "a1", "a2", "a3"]),
            "flag": pa.array(["y", "n", "y", "n"]),
            "z_reader": pa.array(["r"] * 4),
        }
    )


def test_predicate_snapshot_set_includes_the_secondary_output(aux_declared: None) -> None:
    plan = ws.plan(
        [("owner", ws.seed("z_aux")), ("z_gated", ws.seed("redact", when="aux == 'a0'"))]
    )
    order = compile_work_order(build_work_list(plan, ws.REG), ws.NO_GRAPH)
    assert "aux" in source_snapshot_columns(order)["t"]


def test_both_carry_callers_treat_the_secondary_output_as_touched(aux_declared: None) -> None:
    nodes = build_work_list(_plan(reader=False), ws.REG)
    assert "aux" not in untouched_columns(nodes, ["owner", "aux", "flag"])
    config = {"tables": [{"name": "t", "columns": [{"name": "owner", "strategy": "z_aux"}]}]}
    carried = passthrough_columns(
        config, table="t", names=["owner", "aux", "flag"], registry=ws.REG
    )
    assert "aux" not in carried


def test_gated_stitch_and_exact_selection_cover_the_secondary_output(aux_declared: None) -> None:
    out = ws.run(_plan(when="flag == 'y'", reader=False), _table())
    assert out.column("owner").to_pylist() == ["OWN", "o1", "OWN", "o3"]
    assert out.column("aux").to_pylist() == ["AUX", "a1", "AUX", "a3"]


def test_the_compiled_record_carries_the_secondary_output(aux_declared: None) -> None:
    order = compile_work_order(build_work_list(_plan(), ws.REG), ws.NO_GRAPH)
    assert "aux" in order.ops[("t", ("owner",))].writes
    out = ws.run(_plan(), _table())
    assert out.column("z_reader").to_pylist() == ["AUX!"] * 4


# ---------------------------------------------------------------------------
# Raw declaration lookups stay inside the resolver and its checked registry helpers.
# ---------------------------------------------------------------------------

# (path, enclosing function) allowed to call each raw reader.
_PINNED_CALLERS: dict[str, set[tuple[str, str]]] = {
    "declared_access": {
        ("_column_access.py", "column_access"),
        ("work_order/operations.py", "resolve_operation"),
    },
    "column_access": {
        ("work_order/operations.py", "entries_written"),
        ("_column_access.py", "touched_columns"),
        ("_column_access.py", "created_columns"),
        ("_mixed_static.py", "_mask_table_config"),
        ("_transforms.py", "reject_config_references_stored_index"),
    },
    # One ordering decision: nothing else sorts the work list.
    "order_work": {("work_order/compile.py", "compile_work_order")},
}


def _aliases(tree: ast.AST, name: str) -> set[str]:
    """Every local spelling of `name` in a module: its own name plus each `import x as y` alias."""
    spellings = {name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == name and alias.asname:
                    spellings.add(alias.asname)
    return spellings


def _callers(name: str) -> set[tuple[str, str]]:
    """(path, enclosing function) of every call to `name`: a bare call, an aliased import, or a
    module-qualified call (`mod.name(...)`)."""
    found: set[tuple[str, str]] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        spellings = _aliases(tree, name)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                called = func.id if isinstance(func, ast.Name) else None
                if isinstance(func, ast.Attribute) and func.attr in spellings:
                    called = func.attr
                if called in spellings:
                    found.add((str(path.relative_to(SRC)), fn.name))
    return found


@pytest.mark.parametrize("name", sorted(_PINNED_CALLERS))
def test_raw_write_declaration_lookups_are_pinned(name: str) -> None:
    """A new caller of a raw declaration reader fails here until it is pinned with its reason."""
    assert _callers(name) <= _PINNED_CALLERS[name]
