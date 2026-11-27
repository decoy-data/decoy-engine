"""`when:` on a column the input lacks: one check, in the snapshot step (plan revision 2.7, AT-27a
to AT-27f).

The check sits in `work_order.rows.take_source_snapshots`, on the converted masking frame, before
the table's first handler. It covers only gates that dispatch evaluates (scalar and passthrough).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution import PandasExecutionAdapter, _when_gate
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._runner import build_work_list, source_snapshot_columns
from decoy_engine.execution.physical.drivers._sequential import SequentialAdapter
from decoy_engine.execution.work_order import compile_work_order
from decoy_engine.execution.work_order import rows as rows_module
from decoy_engine.plan import GroupSeed
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.unit.execution.when import _write_support as ws

CODE = "when_expression_error"
NO_NAMESPACES = NamespaceRegistry(bindings=())


class Spies:
    """Counts node dispatches, predicate evaluations and refusals of the snapshot step."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dispatches = 0
        self.evaluations = 0
        self.refusals = 0
        real_dispatch = PandasExecutionAdapter._dispatch_mask_node
        real_eval = _when_gate._eval_predicate
        real_take = rows_module.take_source_snapshots

        def dispatch(adapter: Any, *args: Any, **kwargs: Any) -> Any:
            self.dispatches += 1
            return real_dispatch(adapter, *args, **kwargs)

        def evaluate(*args: Any, **kwargs: Any) -> Any:
            self.evaluations += 1
            return real_eval(*args, **kwargs)

        def take(*args: Any, **kwargs: Any) -> Any:
            try:
                return real_take(*args, **kwargs)
            except ExecutionError:
                self.refusals += 1
                raise

        monkeypatch.setattr(PandasExecutionAdapter, "_dispatch_mask_node", dispatch)
        monkeypatch.setattr(_when_gate, "_eval_predicate", evaluate)
        for module in ("_pandas_adapter", "_sequential"):
            monkeypatch.setattr(f"decoy_engine.execution.{module}.take_source_snapshots", take)


def order_of(seed_plan: Any, graph: Any = ws.NO_GRAPH) -> Any:
    return compile_work_order(build_work_list(seed_plan, ws.REG), graph)


def run_driver(seed_plan: Any, table: pa.Table) -> pa.Table:
    emitted: dict[str, pa.Table] = {}
    SequentialAdapter().run(
        PandasExecutionAdapter(),
        seed_plan,
        lambda name: table,
        config={},
        registry=ws.REG,
        relationship_graph=ws.NO_GRAPH,
        namespace_registry=NO_NAMESPACES,
        sink=lambda name, out: emitted.__setitem__(name, out),
    )
    return emitted["t"]


def run_adapter(seed_plan: Any, table: pa.Table) -> pa.Table:
    result = PandasExecutionAdapter().run(
        seed_plan,
        {"t": table},
        registry=ws.REG,
        relationship_graph=ws.NO_GRAPH,
        namespace_registry=NO_NAMESPACES,
    )
    return result.output


def run_seq(seed_plan: Any, table: pa.Table) -> pa.Table:
    return ws.run_sequential(seed_plan, table, bound=())


ROUTES: dict[str, Callable[[Any, pa.Table], pa.Table]] = {
    "full-frame": run_adapter,
    "sequential": run_seq,
    "driver": run_driver,
}


def refused(route: str, seed_plan: Any, table: pa.Table) -> ExecutionError:
    with pytest.raises(ExecutionError) as err:
        ROUTES[route](seed_plan, table)
    return err.value


# ---------------------------------------------------------------------------
# AT-27a: the compiled `gated` flag is what dispatch evaluates.
# ---------------------------------------------------------------------------

PEOPLE = pa.table(
    {
        "first_name": ["a", "b", "c"],
        "last_name": ["la", "lb", "lc"],
        "email": ["ea", "eb", "ec"],
        "n": pa.array([1, 0, 2]),
    }
)


def _case(kind: str) -> tuple[Any, Any, str]:
    when = "n > 0"
    if kind == "scalar":
        return ws.plan([("email", ws.seed("redact", when=when))]), ws.NO_GRAPH, "email"
    if kind == "passthrough":
        return ws.plan([("email", ws.seed("passthrough", when=when))]), ws.NO_GRAPH, "email"
    if kind == "fk-child":
        seed_plan = ws.plan(
            [("first_name", ws.bundle()), ("email", ws.seed("passthrough", when=when))]
        )
        return seed_plan, ws.fk_graph("first_name", "email"), "email"
    seed_plan = ws.plan([("first_name", replace(ws.bundle(), when=when))])
    return seed_plan, ws.NO_GRAPH, "first_name"


@pytest.mark.parametrize("kind", ["scalar", "passthrough", "fk-child", "composite"])
def test_gate_evaluated_matches_dispatch(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_plan, graph, column = _case(kind)
    order = order_of(seed_plan, graph)
    op = next(o for o in order.ops.values() if column in o.node.columns)
    spies = Spies(monkeypatch)
    ws.run(seed_plan, PEOPLE, graph)
    assert op.gated is (kind in {"scalar", "passthrough"})
    assert (spies.evaluations > 0) is op.gated


def test_a_composite_fk_group_is_never_gated() -> None:
    group = GroupSeed(namespace="nm", coherent_columns=("a", "b"))
    seed_plan = ws.plan([("x", ws.seed("redact"))], groups=(("a__b", group),))
    ops = order_of(seed_plan).ops.values()
    assert [(o.kind, o.gated) for o in ops if o.node.columns == ("a", "b")] == [
        ("composite", False)
    ]


# ---------------------------------------------------------------------------
# AT-27b: a gate dispatch never evaluates is not checked.
# ---------------------------------------------------------------------------


def _fk_child_plan(when: str | None) -> tuple[Any, Any]:
    child = ws.seed("passthrough", when=when)
    seed_plan = ws.plan([("first_name", ws.bundle()), ("c", ws.derived("n + 1")), ("email", child)])
    return seed_plan, ws.fk_graph("first_name", "email")


def _composite_plan(when: str | None) -> tuple[Any, Any]:
    bundle = replace(ws.bundle(), when=when)
    return ws.plan([("c", ws.derived("n + 1")), ("first_name", bundle)]), ws.NO_GRAPH


@pytest.mark.parametrize("build", [_fk_child_plan, _composite_plan])
@pytest.mark.parametrize("route", ["single", "sequential"])
def test_gate_not_evaluated_on_fk_and_composite_runs_as_main(
    build: Callable[[str | None], tuple[Any, Any]], route: str
) -> None:
    run = ws.run if route == "single" else ws.run_sequential
    with_gate, graph = build("c > 0")
    without_gate, _ = build(None)
    assert run(with_gate, PEOPLE, graph).equals(run(without_gate, PEOPLE, graph))


# ---------------------------------------------------------------------------
# AT-27c: the check runs before the table's first handler.
# ---------------------------------------------------------------------------

SOURCE = pa.table(
    {"a_first": ["x", "y", "z"], "n": pa.array([1, 0, 2]), "z": ["p", "q", "r"], "k": [5, 6, 7]}
)


def _absent_plan() -> Any:
    return ws.plan(
        [
            ("a_first", ws.seed("redact")),
            ("c", ws.derived("n + 1")),
            ("z", ws.seed("redact", when="c > 0")),
        ]
    )


@pytest.mark.parametrize("route", list(ROUTES))
def test_absent_gate_column_refused_before_table_handlers(
    route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spies = Spies(monkeypatch)
    err = refused(route, _absent_plan(), SOURCE)
    assert err.code == CODE
    assert spies.dispatches == 0
    assert spies.refusals == 1
    assert "'c'" not in str(err)  # the table is named, the column is not


@pytest.mark.parametrize("route", list(ROUTES))
def test_gate_column_in_the_source_is_not_refused(route: str) -> None:
    source = SOURCE.append_column("c", pa.array([3, -1, 4]))
    out = ROUTES[route](_absent_plan(), source)
    assert out.column("z").to_pylist() == ["REDACTED", "q", "REDACTED"]


@pytest.mark.parametrize("route", list(ROUTES))
def test_gate_on_an_unwritten_column_has_an_empty_snapshot_and_runs(route: str) -> None:
    seed_plan = ws.plan([("z", ws.seed("redact", when="n > 0"))])
    assert source_snapshot_columns(order_of(seed_plan)) == {}
    out = ROUTES[route](seed_plan, SOURCE)
    assert out.column("z").to_pylist() == ["REDACTED", "q", "REDACTED"]


# ---------------------------------------------------------------------------
# AT-27d: the names are the converted frame's labels, as on main.
# ---------------------------------------------------------------------------


def _indexed(index: pd.Index, **columns: list[Any]) -> pa.Table:
    return pa.Table.from_pandas(pd.DataFrame(columns, index=index), preserve_index=True)


def _relabelled(columns: dict[str, Any], field: str, label: str) -> pa.Table:
    """A table whose Parquet field `field` carries the pandas label `label`, as a pandas frame
    with a column `label` written under another physical name does."""
    renamed = {(label if name == field else name): values for name, values in columns.items()}
    table = pa.Table.from_pandas(pd.DataFrame(renamed), preserve_index=False)
    meta = json.loads((table.schema.metadata or {})[b"pandas"])
    for entry in meta["columns"]:
        if entry["field_name"] == label:
            entry["field_name"] = field
    names = [field if name == label else name for name in table.column_names]
    return table.rename_columns(names).replace_schema_metadata(
        {b"pandas": json.dumps(meta).encode()}
    )


def _gated_plan(when: str) -> Any:
    return ws.plan([("a_first", ws.seed("redact")), ("z", ws.seed("redact", when=when))])


@pytest.mark.parametrize("route", ["full-frame", "sequential"])
def test_gate_names_match_main_conversion(route: str, monkeypatch: pytest.MonkeyPatch) -> None:
    spies = Spies(monkeypatch)
    strings = ["p", "q", "r"]
    ints = pd.Index(pd.array([1, 2, 0], dtype="Int64"), name="idx")
    # (1) a stored index is not a column the gate can read
    stored = _indexed(ints, a_first=["x", "y", "z"], z=strings)
    assert refused(route, _gated_plan("idx > 0"), stored).code == CODE
    assert spies.dispatches == 0
    # (2) a real input column named idx is read
    real = pa.table({"a_first": ["x", "y", "z"], "z": strings, "idx": pa.array([1, 2, 0])})
    out = ROUTES[route](_gated_plan("idx > 0"), real)
    assert out.column("z").to_pylist() == ["REDACTED", "REDACTED", "r"]
    # (6) disclosed change: an index named like the internal alias is not readable either
    spies.dispatches = 0
    alias = _indexed(pd.Index([1, 2, 0], name="_w0"), a_first=["x", "y", "z"], z=strings)
    assert refused(route, _gated_plan("_w0 > 0"), alias).code == CODE
    assert spies.dispatches == 0


def test_gate_reads_the_pandas_label_of_a_field() -> None:
    """(3) The Parquet field `foo` carries the pandas label `logical`; main evaluates
    `logical > 0` on it. (4) A nullable field read by its physical name still selects rows."""
    plain = {"a_first": ["x", "y"], "z": ["p", "q"], "foo": [1, 0]}
    out = run_seq(_gated_plan("logical > 0"), _relabelled(plain, "foo", "logical"))
    assert out.column("z").to_pylist() == ["REDACTED", "q"]
    nullable = {
        "z": ["p", "q", "r"],
        "a_first": ["x", "y", "w"],
        "foo": pd.array([1, None, 0], "Int64"),
    }
    out = run_seq(_gated_plan("foo > 0"), _relabelled(nullable, "foo", "logical"))
    assert out.column("z").to_pylist() == ["REDACTED", "q", "r"]


@pytest.mark.parametrize("route", ["single", "sequential"])
def test_ungated_date_shift_grouped_by_a_stored_integer_index_runs(route: str) -> None:
    cfg = (("max_shift_days", 30), ("group_by", "g"), ("date_format", "%Y-%m-%d"))
    seed = ws.seed("date_shift", provider_config=cfg, namespace="nm", deterministic=True)
    dates = ["2020-01-01", "2020-02-01", "2020-03-01"]
    table = _indexed(pd.Index([1, 1, 2], name="g"), d=dates, a_first=list("xyz"))
    run = ws.run if route == "single" else ws.run_sequential
    out = run(ws.plan([("d", seed), ("a_first", ws.seed("redact"))]), table, bound=(("d",),))
    assert out.num_rows == 3


# ---------------------------------------------------------------------------
# AT-27e: transform targets and overwritten inputs.
# ---------------------------------------------------------------------------


def _transform_run(tmp_path: Path, ops: list[dict[str, Any]], when: str) -> pa.Table:
    from decoy_engine import run_pipeline
    from tests.unit.execution._transform_testkit import ENGINE_VERSION, single_table_config

    table = pa.table(
        {"id": pa.array([-2, 1, 3, 0]), "s": ["a", "b", "c", "d"], "extra": [1, 2, 3, 4]}
    )
    cfg = single_table_config(tmp_path, table, transforms=ops)
    cfg["tables"][0]["columns"][0]["when"] = when  # `when` is read from the dumped dict
    result = run_pipeline(cfg, {"t": table}, engine_version=ENGINE_VERSION)
    return result.outputs["t"]


def test_a_derive_target_is_readable(tmp_path: Path) -> None:
    derive = [{"op": "derive", "column": "d", "expression": "abs(id)"}]
    out = _transform_run(tmp_path, derive, "d > 1")
    assert out.column("s").to_pylist() == ["REDACTED", "b", "REDACTED", "d"]


@pytest.mark.parametrize("route", ["full-frame", "sequential"])
@pytest.mark.parametrize("dropped", ["d", "extra"])
def test_a_dropped_or_derived_then_dropped_column_is_refused_before_dispatch(
    route: str, dropped: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frame the executors receive after `derive d` then `drop d`, or `drop extra`, lacks the
    column. `run_pipeline` refuses a config that names it earlier, under its own code, so this
    drives the executors on that frame; the spy shows the snapshot step is what refused."""
    spies = Spies(monkeypatch)
    frame = pa.table({"id": pa.array([-2, 1, 3, 0]), "s": ["a", "b", "c", "d"]})
    seed_plan = ws.plan(
        [("a_first", ws.seed("redact")), ("s", ws.seed("redact", when=f"{dropped} > 1"))]
    )
    frame = frame.append_column("a_first", pa.array(list("wxyz")))
    assert refused(route, seed_plan, frame).code == CODE
    assert spies.refusals == 1
    assert spies.dispatches == 0


@pytest.mark.parametrize("route", ["full-frame", "sequential"])
def test_gate_reads_the_source_value_of_an_overwritten_column(route: str) -> None:
    source = pa.table(
        {"x": pa.array([4, -1, 3, -2]), "a_first": list("wxyz"), "z": ["p", "q", "r", "s"]}
    )
    seed_plan = ws.plan(
        [
            ("x", ws.derived("0 - x")),  # crosses zero, and overwrites the column
            ("z", ws.seed("redact", when="x > 0")),
        ]
    )
    out = ROUTES[route](seed_plan, source)
    assert out.column("z").to_pylist() == ["REDACTED", "q", "REDACTED", "s"]


# ---------------------------------------------------------------------------
# AT-27f: the refusal follows each route's sink contract.
# ---------------------------------------------------------------------------


class Sink:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.commits = 0
        self.aborts = 0

    def write(self, table: str, data: pa.Table) -> None:
        self.written.append(table)

    def commit(self) -> Any:
        self.commits += 1

    def abort(self) -> None:
        self.aborts += 1


def _two_tables() -> tuple[Any, dict[str, pa.Table]]:
    """Table `a` is valid; table `b` gates `z` on `c`, which only a node creates."""
    seed_plan = ws.plan([("s", ws.seed("redact"))], table="a")
    b_plan = _absent_plan()
    envelope = seed_plan.seed_envelope
    b_tables = tuple(("b", seeds) for _name, seeds in b_plan.seed_envelope.per_table)
    seed_plan.seed_envelope = replace(envelope, per_table=envelope.per_table + b_tables)
    return seed_plan, {"a": pa.table({"s": ["p", "q"]}), "b": SOURCE}


def _sequential(seed_plan: Any, tables: dict[str, pa.Table], sink: Any) -> None:
    PandasExecutionAdapter().run_sequential(
        seed_plan,
        lambda name: tables[name],
        config={},
        registry=ws.REG,
        relationship_graph=ws.NO_GRAPH,
        namespace_registry=NO_NAMESPACES,
        sink=sink,
    )


def test_a_transactional_sink_commits_nothing() -> None:
    seed_plan, tables = _two_tables()
    sink = Sink()
    with pytest.raises(ExecutionError) as err:
        _sequential(seed_plan, tables, sink)
    assert err.value.code == CODE
    assert sink.aborts == 1 and sink.commits == 0
    assert "b" not in sink.written


def test_a_plain_callable_sink_keeps_the_earlier_table() -> None:
    seed_plan, tables = _two_tables()
    delivered: list[str] = []
    with pytest.raises(ExecutionError) as err:
        _sequential(seed_plan, tables, lambda name, out: delivered.append(name))
    assert err.value.code == CODE
    assert delivered == ["a"]


def test_full_frame_run_returns_no_output() -> None:
    seed_plan, tables = _two_tables()
    with pytest.raises(ExecutionError) as err:
        PandasExecutionAdapter().run(
            seed_plan,
            tables,
            registry=ws.REG,
            relationship_graph=ws.NO_GRAPH,
            namespace_registry=NO_NAMESPACES,
        )
    assert err.value.code == CODE


def test_a_chunk_stream_yields_the_earlier_chunk_then_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine import run_mask_pipeline_chunked
    from tests._declared_schema import declared_schema
    from tests.native._chunked_entry_support import (
        ENGINE_VERSION,
        TABLE,
        key_provider,
        make_config,
    )

    spies = Spies(monkeypatch)
    # `derived` is not chunk-safe at the public entry; the subject here is the oracle's loop.
    monkeypatch.setattr(
        "decoy_engine.execution._chunked.check_chunked_compatibility", lambda *a, **k: None
    )
    columns = [
        {"name": "a_first", "strategy": "redact"},
        {"name": "n", "strategy": "passthrough"},
        {"name": "k", "strategy": "derived", "provider_config": {"expression": "n + 1"}},
        {"name": "z", "strategy": "redact", "when": "k > 0"},
    ]
    config = make_config(columns)
    first = pa.table({"a_first": ["x"], "n": pa.array([1]), "z": ["p"], "k": pa.array([3])})
    second = pa.table({"a_first": ["y"], "n": pa.array([1]), "z": ["q"]})
    stream = run_mask_pipeline_chunked(
        config,
        [first, second],
        table=TABLE,
        source_schema=declared_schema(config, TABLE),
        engine_version=ENGINE_VERSION,
        key_provider=key_provider(),
    )
    assert next(stream).num_rows == 1
    dispatched = spies.dispatches
    with pytest.raises(ExecutionError) as err:
        next(stream)
    assert err.value.code == CODE
    assert spies.dispatches == dispatched  # the refused chunk dispatched nothing
