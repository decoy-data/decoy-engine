"""A cyclic plan commits by rank only where it is cyclic, and an FK child maps to the winner.

The test-4 plan (`email` derived from `summary`, `summary` from the bundle's `last_name`) has no
ordinary order. Two properties must hold on the full-frame and sequential routes: an FK child
resolves against the rank-winning parent column (never the lower-ranked writer left live), and a
table with no cycle is unchanged by a cyclic table beside it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.plan._types import SeedEnvelope, TableSeed
from decoy_engine.relationships._graph import OrphanPolicy, RelationshipEdge, RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceBinding, NamespaceRegistry
from tests.unit.execution.when import _write_support as ws

N = 4
FIRST = [f"F{i}" for i in range(N)]
SRC_EMAIL = [f"u{i}@x.test" for i in range(N)]
CYCLE_COLUMNS = (
    ("first_name", ws.bundle()),
    ("email", ws.derived('concat(summary, "@x.test")')),
    ("summary", ws.derived('concat(last_name, "!")')),
)


def _cyclic_table() -> pa.Table:
    return pa.table(
        {
            "first_name": pa.array(FIRST),
            "last_name": pa.array([f"L{i}" for i in range(N)]),
            "email": pa.array(SRC_EMAIL),
            "summary": pa.array(["x"] * N),
        }
    )


def _run_job(
    tables: dict[str, tuple[pa.Table, tuple[tuple[str, Any], ...]]],
    graph: Any,
    bindings: tuple[NamespaceBinding, ...],
    sequential: bool,
) -> dict[str, pa.Table]:
    per_table = tuple(
        (name, TableSeed(per_column=cols, per_group=())) for name, (_, cols) in tables.items()
    )
    plan = SimpleNamespace(seed_envelope=SeedEnvelope(job_seed=ws.SEED, per_table=per_table))
    sources = {name: tbl for name, (tbl, _) in tables.items()}
    kwargs: dict[str, Any] = {
        "registry": ws.REG,
        "relationship_graph": graph,
        "namespace_registry": NamespaceRegistry(bindings=bindings),
    }
    adapter = PandasExecutionAdapter()
    if not sequential:
        return dict(adapter.run(plan, sources, **kwargs).outputs)
    emitted: dict[str, pa.Table] = {}
    adapter.run_sequential(
        plan,
        lambda name: sources[name],
        config={},
        sink=lambda name, out: emitted.__setitem__(name, out),
        **kwargs,
    )
    return emitted


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_fk_child_maps_to_the_winning_parent_writer(sequential: bool) -> None:
    """B1. `o.email_ref` references `t.email`, which two nodes write (the derived creator and the
    higher-ranked bundle). Every child value must be a value of the parent column."""
    child = pa.table(
        {
            "id": pa.array(["1", "2", "3", "4"]),
            "email_ref": pa.array([SRC_EMAIL[i] for i in (2, 0, 3, 1)]),
        }
    )
    edge = RelationshipEdge("t", ("email",), "o", ("email_ref",), "nm2", OrphanPolicy.PRESERVE)
    bindings = (
        NamespaceBinding("nm", (("t", ("first_name",)),)),
        NamespaceBinding("nm2", (("t", ("email",)), ("o", ("email_ref",)))),
    )
    out = _run_job(
        {
            "o": (child, (("email_ref", ws.seed("passthrough")),)),
            "t": (_cyclic_table(), CYCLE_COLUMNS),
        },
        RelationshipGraph(edges=(edge,), ordering=()),
        bindings,
        sequential,
    )
    parent = out["t"].column("email").to_pylist()
    assert parent == ws.bundle_oracle(FIRST)["email"]
    assert out["o"].column("email_ref").to_pylist() == [parent[i] for i in (2, 0, 3, 1)]


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_self_fk_maps_to_the_winning_parent_writer(sequential: bool) -> None:
    """B1, self-referencing: `mgr_email` references the cyclic table's own `email`."""
    table = _cyclic_table().append_column(
        "mgr_email", pa.array([SRC_EMAIL[i] for i in (2, 0, 3, 1)])
    )
    edge = RelationshipEdge("t", ("email",), "t", ("mgr_email",), "nm2", OrphanPolicy.PRESERVE)
    bindings = (
        NamespaceBinding("nm", (("t", ("first_name",)),)),
        NamespaceBinding("nm2", (("t", ("email",)), ("t", ("mgr_email",)))),
    )
    out = _run_job(
        {"t": (table, (*CYCLE_COLUMNS, ("mgr_email", ws.seed("passthrough"))))},
        RelationshipGraph(edges=(edge,), ordering=()),
        bindings,
        sequential,
    )["t"]
    emails = out.column("email").to_pylist()
    assert out.column("mgr_email").to_pylist() == [emails[i] for i in (2, 0, 3, 1)]


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_an_acyclic_table_is_unchanged_by_a_cyclic_table_beside_it(sequential: bool) -> None:
    """B2. Table `a` (bundle, then a head truncate of last_name) runs the same alone and with an
    unrelated cyclic table `b` in the job."""
    a = pa.table(
        {
            "first_name": pa.array(FIRST),
            "last_name": pa.array([f"ZZZ{i}" for i in range(N)]),
            "email": pa.array(SRC_EMAIL),
        }
    )
    trunc = ws.seed("truncate", provider_config=(("length", 3), ("keep", "head")))
    a_cols = (("first_name", ws.bundle()), ("last_name", trunc))
    bindings = (NamespaceBinding("nm", (("a", ("first_name",)), ("b", ("first_name",)))),)
    alone = _run_job({"a": (a, a_cols)}, ws.NO_GRAPH, bindings, sequential)["a"]
    both = _run_job(
        {"a": (a, a_cols), "b": (_cyclic_table(), CYCLE_COLUMNS)}, ws.NO_GRAPH, bindings, sequential
    )
    assert both["a"].equals(alone)
    assert all(len(v) == 3 for v in both["a"].column("last_name").to_pylist())


class _WildcardStub:
    """A handler whose writes cannot be named: it joins every node of its table into one
    component, and writes nothing."""

    name = "z_stub"
    namespace_required = False
    join_safe = False

    def run(self, df: Any, column: str, plan: Any, ctx: Any) -> tuple[Any, list]:
        return df, []


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_integer_fk_keys_keep_their_dtype_through_the_fallback_assembly(
    sequential: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor 4. A self-FK on integer keys inside a cyclic component: the child tuple is assembled
    from the source version, and the parent and child columns keep their integer type and
    values (no silent object column)."""
    from decoy_engine.execution._strategies import SCALAR_HANDLERS

    monkeypatch.setitem(SCALAR_HANDLERS, "z_stub", _WildcardStub())
    table = (
        _cyclic_table()
        .append_column("pid", pa.array([10, 20, 30, 40], type=pa.int64()))
        .append_column("mgr_id", pa.array([30, 10, 40, None], type=pa.int64()))
        .append_column("z_stub", pa.array(["s"] * N))
    )
    edge = RelationshipEdge("t", ("pid",), "t", ("mgr_id",), "nm2", OrphanPolicy.PRESERVE)
    bindings = (
        NamespaceBinding("nm", (("t", ("first_name",)),)),
        NamespaceBinding("nm2", (("t", ("pid",)), ("t", ("mgr_id",)))),
    )
    cols = (
        *CYCLE_COLUMNS,
        ("pid", ws.seed("passthrough")),
        ("mgr_id", ws.seed("passthrough")),
        ("z_stub", ws.seed("z_stub")),
    )
    out = _run_job(
        {"t": (table, cols)}, RelationshipGraph(edges=(edge,), ordering=()), bindings, sequential
    )["t"]
    assert out.schema.field("pid").type == pa.int64()
    assert out.schema.field("mgr_id").type == pa.int64()
    assert out.column("pid").to_pylist() == [10, 20, 30, 40]
    assert out.column("mgr_id").to_pylist() == [30, 10, 40, None]


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_fk_child_waits_for_a_late_sorting_parent_writer(sequential: bool) -> None:
    """B1. The bundle is keyed on `zz_first`, so its node sorts after the derived `email`. The FK
    child of `t.email` must still wait for it and map to the bundle's email."""
    parent = _cyclic_table().append_column("zz_first", pa.array(FIRST))
    cols = (
        ("zz_first", ws.bundle()),
        ("email", ws.derived('concat(summary, "@x.test")')),
        ("summary", ws.derived('concat(last_name, "!")')),
    )
    child = pa.table(
        {
            "id": pa.array(["1", "2", "3", "4"]),
            "email_ref": pa.array([SRC_EMAIL[i] for i in (2, 0, 3, 1)]),
        }
    )
    edge = RelationshipEdge("t", ("email",), "o", ("email_ref",), "nm2", OrphanPolicy.PRESERVE)
    bindings = (
        NamespaceBinding("nm", (("t", ("zz_first",)),)),
        NamespaceBinding("nm2", (("t", ("email",)), ("o", ("email_ref",)))),
    )
    out = _run_job(
        {"o": (child, (("email_ref", ws.seed("passthrough")),)), "t": (parent, cols)},
        RelationshipGraph(edges=(edge,), ordering=()),
        bindings,
        sequential,
    )
    emails = out["t"].column("email").to_pylist()
    assert out["o"].column("email_ref").to_pylist() == [emails[i] for i in (2, 0, 3, 1)]


def test_fk_child_depends_on_every_writer_of_its_parent_columns(tmp_path: Any) -> None:
    """B1. In the fallback graph the FK child of `t.email` waits for each node that writes
    `email`, including a joint mask that no other node depends on."""
    from decoy_engine.execution._runner import build_work_list
    from decoy_engine.execution.work_order import resolve_operations
    from decoy_engine.execution.work_order.ranks import fallback_edges

    ref = ws.reference(tmp_path / "r.parquet", zz_k=["J"], email=["JE"])
    seed_plan = SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=ws.SEED,
            per_table=(
                ("o", TableSeed(per_column=(("email_ref", ws.seed("passthrough")),), per_group=())),
                (
                    "t",
                    TableSeed(
                        per_column=(*CYCLE_COLUMNS, ("zz_k", ws.joint(ref, ["zz_k", "email"]))),
                        per_group=(),
                    ),
                ),
            ),
        )
    )
    edge = RelationshipEdge("t", ("email",), "o", ("email_ref",), "nm2", OrphanPolicy.PRESERVE)
    graph = RelationshipGraph(edges=(edge,), ordering=())
    edges = fallback_edges(resolve_operations(build_work_list(seed_plan, ws.REG), graph))
    assert ("t", ("zz_k",)) in edges[("o", ("email_ref",))]
