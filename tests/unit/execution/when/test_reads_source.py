"""WHEN-READS-SOURCE S2: a `when:` selects rows by the ORIGINAL value of every column it names.

Plan: `docs/plans/2026-11-22-when-reads-source.md` rev 2.2, section 9 (W2 to W6, W8). An earlier
node in work order masks `status` in place; the gated column's predicate must still see the
source `status` on every route, and the native lanes must admit the table.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies._redact import RedactHandler
from decoy_engine.execution._when_gate import run_with_when_gate
from decoy_engine.plan._types import ColumnSeed
from tests.native._c8_i_support import (
    chunk_by_sizes,
    run_native,
    run_native_below_gate,
    run_public_oracle,
    run_public_oracle_below_gate,
)
from tests.native._chunked_entry_support import (
    NEEDS_COMPANION,
    TABLE,
    hash_col,
    make_config,
    redact,
)
from tests.unit.execution.when._support import (
    NS,
    changed_rows,
    config_for,
    run_full_frame,
    status_source,
)

KINDS = [
    "redact",
    pytest.param("hash", marks=NEEDS_COMPANION),
    pytest.param("truncate", marks=NEEDS_COMPANION),
]


def _expected_rows(source: pa.Table) -> list[bool]:
    return [s == "active" for s in source.column("status").to_pylist()]


# ---------------------------------------------------------------------------
# W2: the oracle (full frame).
# ---------------------------------------------------------------------------


def test_w2_active_rows_are_masked_when_an_earlier_node_masks_the_read_column(
    tmp_path: Path,
) -> None:
    source = status_source()
    out = run_full_frame(config_for("redact"), source, tmp_path).outputs[TABLE]
    assert changed_rows(out, source, "zz_email") == _expected_rows(source)
    assert out.column("zz_email").to_pylist().count("REDACTED") == 600
    # `status` itself is hashed on every row: the earlier node did run first.
    assert all(changed_rows(out, source, "status"))


def test_w2_column_name_does_not_change_the_selected_rows(tmp_path: Path) -> None:
    """`aa_email` sorts before `status` (reads the live value before the fix too); `zz_email`
    sorts after. Both must select the same rows."""
    source = status_source()
    late = run_full_frame(config_for("redact"), source, tmp_path).outputs[TABLE]
    renamed = source.rename_columns(["status", "aa_email"])
    early_cfg = config_for("redact", gated="aa_email")
    (tmp_path / "e").mkdir()
    early = run_full_frame(early_cfg, renamed, tmp_path / "e").outputs[TABLE]
    assert changed_rows(early, renamed, "aa_email") == changed_rows(late, source, "zz_email")


# ---------------------------------------------------------------------------
# W3 and W4: the native lanes admit the table and equal the oracle.
# ---------------------------------------------------------------------------


def _values(chunks: list[pa.Table], name: str) -> list[Any]:
    return [v for c in chunks for v in c.column(name).to_pylist()]


@pytest.mark.parametrize("kind", KINDS)
def test_w3_chunked_native_admits_and_equals_the_oracle(kind: str, tmp_path: Path) -> None:
    source = status_source()
    config = config_for(kind, status_kind="redact")
    chunks = chunk_by_sizes(source, [700, 700, 600])
    out, evidence = run_native(config, chunks)
    assert evidence.native_admitted is True, evidence.reroute_reason
    want = run_public_oracle(config, chunks)
    assert _values(out, "zz_email") == _values(want, "zz_email")
    whole = run_full_frame(config, source, tmp_path).outputs[TABLE]
    assert _values(out, "zz_email") == whole.column("zz_email").to_pylist()
    assert changed_rows(pa.concat_tables(out), source, "zz_email") == _expected_rows(source)


@pytest.mark.parametrize("kind", KINDS)
def test_w3_unified_slice_admits_and_equals_the_oracle(kind: str, tmp_path: Path) -> None:
    source = status_source()
    config = config_for(kind, status_kind="redact")
    unified = run_full_frame(config, source, tmp_path, unified_slice_enabled=True)
    assert "unified_slice_activation" in unified.quality_metrics
    (tmp_path / "o").mkdir()
    oracle = run_full_frame(config, source, tmp_path / "o")
    got = unified.outputs[TABLE].column("zz_email").to_pylist()
    assert got == oracle.outputs[TABLE].column("zz_email").to_pylist()
    assert changed_rows(unified.outputs[TABLE], source, "zz_email") == _expected_rows(source)


@pytest.mark.parametrize("chunk", [700, 1300])
def test_w4_chunk_size_does_not_change_the_output(chunk: int) -> None:
    source = status_source()
    config = config_for("redact")
    sizes = [chunk] * (2000 // chunk) + ([2000 % chunk] if 2000 % chunk else [])
    chunks = chunk_by_sizes(source, sizes)
    native, _ = run_native_below_gate(config, chunks)
    oracle = run_public_oracle_below_gate(config, chunks)
    assert _values(native, "zz_email") == _values(oracle, "zz_email")
    assert changed_rows(pa.concat_tables(native), source, "zz_email") == _expected_rows(source)


# ---------------------------------------------------------------------------
# W5: the sequential FK route.
# ---------------------------------------------------------------------------


def test_w5_sequential_route_selects_by_the_original_value(tmp_path: Path) -> None:
    n = 40
    parent = pa.table({"pid": pa.array(range(1, n + 1), pa.int64())})
    child = pa.table(
        {
            "pid": pa.array(range(1, n + 1), pa.int64()),
            "kind": pa.array(["x" if i % 4 == 0 else "y" for i in range(n)], pa.string()),
            "zz_note": pa.array([f"note{i}" for i in range(n)], pa.string()),
        }
    )
    config = make_config(
        [
            {"name": "pid", "strategy": "passthrough"},
            hash_col("kind", NS),
            {**redact("zz_note"), "when": "kind == 'x'"},
        ],
        extra_tables=[{"name": "parent", "columns": [{"name": "pid", "strategy": "passthrough"}]}],
        relationships=[
            {
                "parent": {"table": "parent", "columns": ["pid"]},
                "children": [{"table": TABLE, "columns": ["pid"]}],
                "orphan_policy": "remap",
                "namespace": "ns_fk",
            }
        ],
    )
    out = _run_sequential(config, {TABLE: child, "parent": parent}, tmp_path).outputs[TABLE]
    assert changed_rows(out, child, "zz_note") == [k == "x" for k in child["kind"].to_pylist()]


def _run_sequential(config: dict[str, Any], tables: dict[str, pa.Table], tmp: Path) -> Any:
    import copy

    from decoy_engine.execution import run_pipeline
    from tests._declared_schema import declare_rest
    from tests.native._chunked_entry_support import ENGINE_VERSION, key_provider

    config = copy.deepcopy(config)
    for name, tbl in tables.items():
        path = tmp / f"{name}.csv"
        path.write_text(",".join(tbl.column_names) + "\n" + ",".join("x" for _ in tbl.column_names))
        config["sources"][name] = {
            "type": "file",
            "format": "csv",
            "has_header": True,
            "path": str(path),
        }
        config["targets"][name] = {"type": "file", "format": "csv", "path": str(tmp / f"{name}.o")}
    declare_rest(config, tables)
    result = run_pipeline(
        config,
        tables,
        engine_version=ENGINE_VERSION,
        key_provider=key_provider(),
        execution_mode="sequential",
        auto_chunk=False,
        unified_slice_enabled=False,
    )
    assert result.quality_metrics["execution"]["execution_mode"] == "sequential"
    return result


# ---------------------------------------------------------------------------
# W6 and W8: the gate fails closed and stays value-free.
# ---------------------------------------------------------------------------

_SENTINEL = "SENTINEL-ORIGINAL-VALUE"


class _Ctx:
    """Test double with the fields the gate reads from a real StrategyContext."""

    def __init__(
        self, columns: Any, snapshots: dict[tuple[str, str], pd.Series], table: str = "t"
    ) -> None:
        self.row_errors: list[Any] = []
        self.current_table = table
        self.source_snapshot_columns = columns
        self.group_anchor_snapshots = snapshots


def _seed(when: str) -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy="redact",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="bijective",
        deterministic=False,
        provider_config=(),
        when=when,
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"status": ["hashed1", "hashed2"], "email": ["a", "b"]})


@pytest.mark.parametrize(
    ("columns", "snapshots"),
    [
        (None, {}),
        ({"t": frozenset({"status"})}, {}),
    ],
    ids=["no_snapshot_set", "set_names_column_without_snapshot"],
)
def test_w6_w8_missing_snapshot_fails_closed_and_value_free(
    columns: Any, snapshots: dict[tuple[str, str], pd.Series]
) -> None:
    with pytest.raises(StrategyError) as info:
        run_with_when_gate(
            RedactHandler(),
            _frame(),
            "email",
            _seed(f"status == '{_SENTINEL}'"),
            _Ctx(columns, snapshots),  # type: ignore[arg-type]
        )
    assert info.value.code == "when_source_snapshot_missing"
    assert _SENTINEL not in str(info.value)
    assert "==" not in str(info.value)


def test_w2_gate_reads_the_snapshot_not_the_live_frame() -> None:
    df = _frame()
    snap = pd.Series(["active", "idle"], index=df.index, name="status")
    ctx = _Ctx({"t": frozenset({"status"})}, {("t", "status"): snap})
    out, _ = run_with_when_gate(
        RedactHandler(),
        df,
        "email",
        _seed("status == 'active'"),
        ctx,  # type: ignore[arg-type]
    )
    assert out["email"].tolist() == ["REDACTED", "b"]
    assert out["status"].tolist() == ["hashed1", "hashed2"]  # the live frame keeps its masked value


def test_a_column_no_node_writes_is_read_live() -> None:
    df = _frame()
    ctx = _Ctx({}, {})
    out, _ = run_with_when_gate(
        RedactHandler(),
        df,
        "email",
        _seed("status == 'hashed2'"),
        ctx,  # type: ignore[arg-type]
    )
    assert out["email"].tolist() == ["a", "REDACTED"]


def test_w3_the_snapshot_is_aligned_by_label_on_a_reindexed_frame() -> None:
    df = _frame()
    df.index = pd.Index([10, 20])
    # The snapshot holds the same labels in the reverse order: label 10 was "idle", 20 "active".
    snap = pd.Series(["active", "idle"], index=pd.Index([20, 10]), name="status")
    ctx = _Ctx({"t": frozenset({"status"})}, {("t", "status"): snap})
    out, _ = run_with_when_gate(
        RedactHandler(),
        df,
        "email",
        _seed("status == 'active'"),
        ctx,  # type: ignore[arg-type]
    )
    assert out["email"].tolist() == ["a", "REDACTED"]


@pytest.mark.parametrize("table", ["", "other"], ids=["empty_table", "unknown_table"])
def test_a_snapshot_set_without_the_running_table_never_reads_the_live_frame(table: str) -> None:
    """An empty table name cannot look the set up, so the gate fails closed. A table the set
    does not name has no written read column: its reads are original values, read live."""
    df = _frame()
    snap = pd.Series(["active", "idle"], index=df.index, name="status")
    ctx = _Ctx({"t": frozenset({"status"})}, {("t", "status"): snap}, table=table)
    run = lambda: run_with_when_gate(
        RedactHandler(),
        df,
        "email",
        _seed("status == 'hashed2'"),
        ctx,  # type: ignore[arg-type]
    )
    if table == "":
        with pytest.raises(StrategyError) as info:
            run()
        assert info.value.code == "when_source_snapshot_missing"
    else:
        assert run()[0]["email"].tolist() == ["a", "REDACTED"]


# ---------------------------------------------------------------------------
# Composite writers and duplicate row labels (Codex R2).
# ---------------------------------------------------------------------------


def _seed_plan(per_column: list[tuple[str, ColumnSeed]]) -> Any:
    from types import SimpleNamespace

    from decoy_engine.plan._types import SeedEnvelope, TableSeed

    return SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=b"\xca\xfe" * 16,
            per_table=(("t", TableSeed(per_column=tuple(per_column), per_group=())),),
        )
    )


def _seed_of(strategy: str, **kw: Any) -> ColumnSeed:
    base: dict[str, Any] = {
        "namespace": None,
        "strategy": strategy,
        "provider": None,
        "backend_type": "decoy_native",
        "backend_version": "1",
        "cardinality_mode": "preserve",
        "deterministic": False,
    }
    return ColumnSeed(**{**base, **kw})


def _composite_seed() -> ColumnSeed:
    return _seed_of(
        "faker",
        provider="composite_name_email",
        namespace="nm",
        deterministic=True,
        backend_type="composite",
        cardinality_mode="reuse",
    )


def test_a_composite_nodes_provider_output_is_snapshotted_for_a_when() -> None:
    """A lone `composite_name_email` keyed on `first_name` also writes `email`; a later
    `when: email == 'active'` still selects by the source email (Codex R2, V1)."""
    from decoy_engine.execution import PandasExecutionAdapter
    from decoy_engine.execution._runner import source_snapshot_columns
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships._graph import RelationshipGraph
    from decoy_engine.relationships._namespace import NamespaceBinding, NamespaceRegistry

    reg = get_default_registry()
    plan = _seed_plan(
        [
            ("first_name", _composite_seed()),
            ("zz_target", _seed_of("redact", when="email == 'active'")),
        ]
    )
    assert "email" in source_snapshot_columns(plan, reg).get("t", frozenset())
    n = 6
    emails = ["active" if i % 2 == 0 else f"u{i}@x.test" for i in range(n)]
    table = pa.table(
        {
            "first_name": pa.array([f"F{i}" for i in range(n)]),
            "last_name": pa.array([f"L{i}" for i in range(n)]),
            "email": pa.array(emails),
            "zz_target": pa.array([f"t{i}" for i in range(n)]),
        }
    )
    out = (
        PandasExecutionAdapter()
        .run_single(
            plan,
            table,
            registry=reg,
            relationship_graph=RelationshipGraph(edges=(), ordering=()),
            namespace_registry=NamespaceRegistry(
                bindings=(NamespaceBinding("nm", (("t", ("first_name",)),)),)
            ),
        )
        .output
    )
    assert changed_rows(out, table, "zz_target") == [e == "active" for e in emails]


@pytest.mark.parametrize(
    "provider",
    ["composite_name_email", "composite_city_state_zip", "composite_person", "composite_address"],
)
def test_every_column_a_handler_declares_written_is_snapshotted_when_read(provider: str) -> None:
    """Property over the declaration: each output column of a composite provider appears in the
    snapshot set once a `when:` reads it, whether or not the config names it."""
    from decoy_engine.execution._runner import source_snapshot_columns
    from decoy_engine.generation.composite._validate import _COMPOSITE_OUTPUT_COLUMNS
    from decoy_engine.providers_v2 import get_default_registry

    outputs = _COMPOSITE_OUTPUT_COLUMNS[provider]
    head = _seed_of("faker", provider=provider, namespace="nm", backend_type="composite")
    for read in outputs:
        plan = _seed_plan(
            [(outputs[0], head), ("zz_target", _seed_of("redact", when=f"{read} == 'x'"))]
        )
        assert read in source_snapshot_columns(plan, get_default_registry()).get(
            "t", frozenset()
        ), (
            provider,
            read,
        )


def test_an_unknown_writer_snapshots_every_column_the_table_reads() -> None:
    from decoy_engine.execution._runner import source_snapshot_columns
    from decoy_engine.providers_v2 import get_default_registry

    plan = _seed_plan(
        [
            ("a", _seed_of("no_such_strategy")),
            ("zz_target", _seed_of("redact", when="status == 'x'")),
        ]
    )
    assert source_snapshot_columns(plan, get_default_registry()).get("t") == {"status"}


def test_duplicate_row_labels_select_by_position_on_the_full_frame_and_chunked_oracle(
    tmp_path: Path,
) -> None:
    """Labels are positional here: the source index `[7, 7]` must not make the snapshot
    lookup select four rows (Codex R2, V1)."""
    df = pd.DataFrame({"status": ["h1", "h2"], "email": ["a", "b"]}, index=[7, 7])
    snap = pd.Series(["active", "idle"], index=df.index, name="status")
    ctx = _Ctx({"t": frozenset({"status"})}, {("t", "status"): snap})
    out, _ = run_with_when_gate(
        RedactHandler(),
        df,
        "email",
        _seed("status == 'active'"),
        ctx,  # type: ignore[arg-type]
    )
    assert out["email"].tolist() == ["REDACTED", "b"]
    # A snapshot that cannot be aligned fails closed with the coded error.
    short = pd.Series(["active"], index=[7], name="status")
    ctx = _Ctx({"t": frozenset({"status"})}, {("t", "status"): short})
    with pytest.raises(StrategyError) as info:
        run_with_when_gate(
            RedactHandler(),
            df,
            "email",
            _seed("status == 'active'"),
            ctx,  # type: ignore[arg-type]
        )
    assert info.value.code == "when_source_snapshot_missing"


def test_a_job_whose_source_has_one_row_label_repeated_runs_on_the_oracle_routes(
    tmp_path: Path,
) -> None:
    """Whole job through the public pandas adapter with a duplicated pandas index."""
    from decoy_engine.execution import PandasExecutionAdapter
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships._graph import RelationshipGraph
    from decoy_engine.relationships._namespace import NamespaceRegistry

    plan = _seed_plan(
        [
            ("status", _seed_of("redact")),
            ("zz_target", _seed_of("redact", when="status == 'active'")),
        ]
    )
    table = pa.table({"status": ["active", "idle"], "zz_target": ["t0", "t1"]})
    # `to_pandas_fk_safe` yields a RangeIndex; force the duplicate labels the dedupe-free
    # sources can produce.
    import decoy_engine.execution._pandas_adapter as adapter_mod

    orig = adapter_mod.to_pandas_fk_safe

    def dup(tbl: Any, cols: Any) -> pd.DataFrame:
        frame = orig(tbl, cols)
        frame.index = pd.Index([7] * len(frame))
        return frame

    adapter_mod.to_pandas_fk_safe = dup
    try:
        out = (
            PandasExecutionAdapter()
            .run_single(
                plan,
                table,
                registry=get_default_registry(),
                relationship_graph=RelationshipGraph(edges=(), ordering=()),
                namespace_registry=NamespaceRegistry(bindings=()),
            )
            .output
        )
    finally:
        adapter_mod.to_pandas_fk_safe = orig
    assert out.column("zz_target").to_pylist() == ["REDACTED", "t1"]


def test_a_derived_column_waits_for_the_composite_that_writes_its_driver() -> None:
    """`a_summary` sorts before the `first_name` composite, which writes `email` though no entry
    names it: the writer map must order the composite first and `a_summary` must read its value
    (Codex R3). One declaration answers "what does this node write" for ordering and snapshots."""
    from decoy_engine.execution import PandasExecutionAdapter
    from decoy_engine.execution._runner import build_work_list, order_work
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships._graph import RelationshipGraph
    from decoy_engine.relationships._namespace import NamespaceBinding, NamespaceRegistry

    reg = get_default_registry()
    graph = RelationshipGraph(edges=(), ordering=())
    plan = _seed_plan(
        [
            ("first_name", _composite_seed()),
            (
                "a_summary",
                _seed_of("derived", provider_config=(("expression", 'concat(email, "!")'),)),
            ),
        ]
    )
    order = [n.columns for n in order_work(build_work_list(plan, reg), graph)]
    assert order.index(("first_name",)) < order.index(("a_summary",))
    n = 4
    table = pa.table(
        {
            "first_name": pa.array([f"F{i}" for i in range(n)]),
            "last_name": pa.array([f"L{i}" for i in range(n)]),
            "email": pa.array([f"u{i}@x.test" for i in range(n)]),
            "a_summary": pa.array(["x"] * n),
        }
    )
    out = (
        PandasExecutionAdapter()
        .run_single(
            plan,
            table,
            registry=reg,
            relationship_graph=graph,
            namespace_registry=NamespaceRegistry(
                bindings=(NamespaceBinding("nm", (("t", ("first_name",)),)),)
            ),
        )
        .output
    )
    emails = out.column("email").to_pylist()
    assert emails != table.column("email").to_pylist()  # the composite did mask email
    assert out.column("a_summary").to_pylist() == [e + "!" for e in emails]
