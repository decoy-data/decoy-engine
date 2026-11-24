"""S2a ordering is main's ordering: `compile_work_order` sorts a plan if and only if the frozen
oracle (`_main_order_oracle`, `_runner.py` at `8ee461e0f`) does, in the same order, and raises the
same code when it does not.

Plan: `docs/plans/2026-11-22-when-reads-source.md`, revision 2.6, "Differential ordering test".
A plan that sorts on main and raises or reorders here is a defect in the S2a code, not in this test.
"""

from __future__ import annotations

import itertools
import random
from typing import Any

import pytest

from decoy_engine.execution._column_access import SURFACE_DECLARATIONS
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._runner import build_work_list
from decoy_engine.execution.work_order import compile_work_order
from decoy_engine.relationships._graph import OrphanPolicy, RelationshipEdge, RelationshipGraph
from tests.unit.execution.when import _write_support as ws
from tests.unit.execution.work_order import _main_order_oracle as oracle

_NO_GRAPH = RelationshipGraph(edges=(), ordering=())
_CREATING = {"derived", "derived_aggregate", "grouped_series", "windowed_date", "group_key"}
_SCALARS = sorted(k.split(":", 1)[1] for k in SURFACE_DECLARATIONS if k.startswith("scalar:"))
_COMPOSITES = sorted(k.split(":", 1)[1] for k in SURFACE_DECLARATIONS if k.startswith("composite:"))


def _seed(key: str, col: str, other: str, when: str | None) -> Any:
    """A seed for declaration `key` on `col`, reading `other` wherever its declaration reads."""
    if key in _COMPOSITES:
        provider = key
        cfg = (("bundle", [{"column": col, "provider": "first_name"}]),) if "custom" in key else ()
        return ws.seed(
            "faker",
            provider=provider,
            namespace="nm",
            backend_type="composite",
            coherent_with=(other,),
            provider_config=cfg,
        )
    cfg: tuple[tuple[str, Any], ...] = ()
    if key == "derived":
        cfg = (("expression", f'concat({other}, "!")'),)
    elif key == "derived_aggregate":
        cfg = (("column", other),)
    elif key in {"grouped_series", "windowed_date", "group_key", "date_shift"}:
        cfg = (("group_by", other),)
    elif key == "joint_mask":
        cfg = (("columns", [col, other]), ("reference", "customer:/none"), ("key_by", other))
    return ws.seed(key, provider_config=cfg, when=when)


def _plan(nodes: list[tuple[str, Any]], parent: bool = False) -> Any:
    out = ws.plan(nodes)
    if parent:
        out.seed_envelope = type(out.seed_envelope)(
            job_seed=out.seed_envelope.job_seed,
            per_table=(*out.seed_envelope.per_table, ("p", _p_table())),
        )
    return out


def _p_table() -> Any:
    from decoy_engine.plan._types import TableSeed

    return TableSeed(per_column=(("pk", ws.seed("redact")),), per_group=())


def _fk(parent: str, child: str, to_parent_table: bool = False) -> RelationshipGraph:
    edge = RelationshipEdge(
        "p" if to_parent_table else "t",
        ("pk",) if to_parent_table else (parent,),
        "t",
        (child,),
        "nm",
        OrphanPolicy.PRESERVE,
    )
    return RelationshipGraph(edges=(edge,), ordering=())


def _outcome_main(plan: Any, graph: Any) -> Any:
    work = build_work_list(plan, ws.REG)
    try:
        return [n.key for n in oracle.order_work(work, graph)]
    except ExecutionError as exc:
        return exc.code


def _outcome_s2a(plan: Any, graph: Any) -> Any:
    work = build_work_list(plan, ws.REG)
    try:
        return [n.key for n in compile_work_order(work, graph).ordered]
    except ExecutionError as exc:
        return exc.code


def _assert_same(plan: Any, graph: Any, label: str) -> None:
    assert _outcome_s2a(plan, graph) == _outcome_main(plan, graph), label


def _pair_corpus() -> list[tuple[str, Any, Any]]:
    rng = random.Random(20261124)
    keys = [*_SCALARS, *_COMPOSITES]
    cases: list[tuple[str, Any, Any]] = []
    for a, b in itertools.permutations(keys, 2):
        for _ in range(3):  # a fixed-seed sample of the (when, fk, overlap, unknown) cube
            when = "x == 1" if rng.random() < 0.5 else None
            fk = rng.random() < 0.5
            overlap = rng.random() < 0.5
            unknown = rng.random() < 0.5
            swap = rng.random() < 0.5
            ca, cb = ("zz_a", "aa_b") if swap else ("aa_a", "zz_b")
            nodes = [(ca, _seed(a, ca, cb, when)), (cb, _seed(b, cb, ca, when))]
            if overlap:  # a bundle and a scalar both write one column
                nodes.append((cb, _seed("redact", cb, ca, None)))
            if unknown:
                nodes.append(("mm_u", ws.seed("no_such_strategy")))
            graph = _fk(ca, cb) if fk else _NO_GRAPH
            cases.append(
                (f"{a}|{b}|when={when}|fk={fk}|ov={overlap}|unk={unknown}", _plan(nodes), graph)
            )
    return cases


_PAIRS = _pair_corpus()


@pytest.mark.parametrize("label", ["pairs"])
def test_every_pair_orders_as_main_does(label: str) -> None:
    """Every scalar and composite declaration key against every other, under a fixed-seed sample
    of with and without `when:`, FK edge, bundle overlap and unknown-output writer."""
    assert len(_PAIRS) > 2500
    for case, plan, graph in _PAIRS:
        _assert_same(plan, graph, case)


@pytest.mark.parametrize("with_fk", [False, True], ids=["no-fk", "fk"])
@pytest.mark.parametrize("names", [("a1", "b2", "c3"), ("c1", "b2", "a3"), ("b1", "c2", "a3")])
def test_three_node_chains_order_as_main_does(with_fk: bool, names: tuple[str, str, str]) -> None:
    """A creator, a reader that writes a second target, and a reader of that target, with names
    whose lexical order differs from the dependency order."""
    first, mid, last = names
    nodes = [
        (first, ws.derived('concat(src, "!")')),
        (mid, ws.derived(f'concat({first}, "?")')),
        (last, ws.derived(f'concat({mid}, "#")')),
    ]
    graph = _fk(first, last, to_parent_table=True) if with_fk else _NO_GRAPH
    _assert_same(_plan(nodes, parent=with_fk), graph, f"chain {names} fk={with_fk}")
    mid_fk = _fk(mid, last) if with_fk else _NO_GRAPH
    _assert_same(_plan(nodes), mid_fk, f"chain {names} fk-inside={with_fk}")


def _named_plans() -> dict[str, tuple[Any, Any]]:
    from tests.unit.execution.when import test_write_order as tw

    plans: dict[str, tuple[Any, Any]] = {
        "plan_a": (
            ws.plan(
                [("first_name", ws.bundle()), ("email", ws.derived('concat(first_name, "!")'))]
            ),
            _NO_GRAPH,
        ),
        "plan_b": (
            ws.plan([("first_name", ws.bundle()), ("last_name", ws.derived('concat(email, "?")'))]),
            _NO_GRAPH,
        ),
        "case_3": (
            ws.plan([("first_name", ws.bundle()), ("email", ws.derived('concat(other, "#")'))]),
            ws.fk_graph("first_name", "email"),
        ),
        "case_4": (tw._indirect_plan(), _NO_GRAPH),
        "case_4c": (tw._indirect_plan(with_view=True), _NO_GRAPH),
        "case_4d": (
            ws.plan([("a", ws.derived('concat(b, "!")')), ("b", ws.derived('concat(a, "?")'))]),
            _NO_GRAPH,
        ),
        "f2": (
            ws.plan(
                [
                    ("first_name", ws.bundle()),
                    ("email", ws.derived('concat(summary, "@x.test")', when="first_name == 'F0'")),
                    ("summary", ws.derived('concat(last_name, "!")')),
                ]
            ),
            _NO_GRAPH,
        ),
        "f3": (
            ws.plan(
                [
                    ("first_name", ws.bundle(coherent_with=("last_name",))),
                    ("last_name", ws.joint("customer:/none", ["last_name"])),
                    ("email", ws.derived('concat(summary, "@x.test")')),
                    ("summary", ws.derived('concat(last_name, "!")')),
                ]
            ),
            _NO_GRAPH,
        ),
    }
    return plans


@pytest.mark.parametrize("name", sorted(_named_plans()))
def test_named_plans_order_as_main_does(name: str) -> None:
    plan, graph = _named_plans()[name]
    _assert_same(plan, graph, name)


def test_the_cyclic_control_raises_on_both() -> None:
    plan, graph = _named_plans()["case_4d"]
    assert _outcome_main(plan, graph) == "cyclic_work_ordering"
    assert _outcome_s2a(plan, graph) == "cyclic_work_ordering"


def test_the_oracle_is_not_the_code_under_test() -> None:
    """The oracle is a separate copy: it shares no function object with `_runner`."""
    from decoy_engine.execution import _runner

    assert oracle.order_work is not _runner.order_work
    assert oracle.column_dependency_edges is not _runner.column_dependency_edges
