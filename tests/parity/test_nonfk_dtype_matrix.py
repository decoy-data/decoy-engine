"""NONFK-OOM part (a): a carried passthrough column keeps a non-FK table on the chunked lane.

AT-A1, AT-A2, AT-A3, AT-A4, AT-A5, AT-A6, AT-A7, AT-A8, AT-A9 and the guards G-1 (passthrough
rows) and G-3 of docs/plans/2026-11-19-nonfk-oom.md. Do not delete a cell, skip one or loosen
an equality to pass.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import _chunked_carry as carry
from decoy_engine.execution._chunked_carry import is_stock_adapter
from tests.parity._nonfk_dtype_cases import CARRIED_TYPES, LAYOUTS, source_table
from tests.unit.execution import _auto_chunk_support as support

CELLS = [(t, lay) for t in CARRIED_TYPES for lay in LAYOUTS]
IDS = [f"{t}-{lay}" for t, lay in CELLS]


def _cfg(
    tmp_path: Path,
    table: pa.Table,
    p_entry: dict[str, Any] | None,
    extra: list[dict[str, Any]] | None = None,
    *,
    s_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The config for `table`; the Parquet file `profile_source` reads is written after the
    config is built, so the source stays undeclared (no declared casting)."""
    cols = [s_entry or support.redact_col("s"), *(extra or [])]
    if p_entry is not None:
        cols.append(p_entry)
    path = tmp_path / "src.parquet"
    cfg = support.make_cfg(cols, path=str(path))
    support.write_source(table, path)
    return cfg


def _run(table: pa.Table, cfg: dict[str, Any], **kwargs: Any) -> Any:
    return support.run_default(cfg, table, **kwargs)


def _oracle(table: pa.Table, cfg: dict[str, Any]) -> Any:
    return support.run_full_frame(cfg, table, execution_mode="full_frame")


@pytest.mark.parametrize(("type_class", "layout"), CELLS, ids=IDS)
def test_at_a1_configured_passthrough_is_carried_exactly(
    tmp_path: Path, type_class: str, layout: str
) -> None:
    table = source_table(type_class, layout)
    got = _run(table, _cfg(tmp_path, table, support.pass_col("p")))
    block = got.quality_metrics["auto_chunk"]
    assert block["mode"] == "chunked", block["reason"]
    out = got.outputs[support.TABLE]
    assert out.schema.field("p").type == table.schema.field("p").type
    assert out.column("p").to_pylist() == table.column("p").to_pylist()


def test_at_a2_unconfigured_columns_are_carried() -> None:
    """A file source must declare every column, so the unconfigured shape is reachable only
    through the shared carried-set function the planner and the lane both call."""
    from decoy_engine.providers_v2 import get_default_registry

    cfg = {"tables": [{"name": "t", "columns": [support.redact_col("s")]}]}
    got = carry.carried_columns(
        cfg, table="t", names=["s", "p", "q"], registry=get_default_registry()
    )
    assert got == {"p", "q"}
    assert (
        carry.carried_columns(
            cfg, table="t", names=["s", "p", "p"], registry=get_default_registry()
        )
        == frozenset()
    )


@pytest.mark.parametrize("type_class", ["int64_nulls", "decimal128", "list"])
def test_at_a3_non_carried_columns_equal_the_full_frame_oracle(
    tmp_path: Path, type_class: str
) -> None:
    table = source_table(type_class, "later_mixed")
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    got = _run(table, cfg)
    base = _oracle(table, cfg)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    a, b = got.outputs[support.TABLE], base.outputs[support.TABLE]
    assert a.schema.field("s").type == b.schema.field("s").type
    assert a.column("s").to_pylist() == b.column("s").to_pylist()


def _when_read_run(tmp_path: Path) -> dict[str, Any]:
    table = pa.table(
        {
            "s": pa.array([f"n{i}" for i in range(200)]),
            "p": pa.array([None if i % 5 == 0 else i for i in range(200)], pa.int64()),
        }
    )
    cfg = _cfg(
        tmp_path,
        table,
        support.pass_col("p"),
        s_entry={**support.redact_col("s"), "when": "p > 3"},
    )
    return _run(table, cfg).quality_metrics["auto_chunk"]


def test_at_a4_a_column_read_by_when_stays_full_frame(tmp_path: Path) -> None:
    block = _when_read_run(tmp_path)
    assert block["mode"] == "full_frame"
    assert "non-chunk-stable pandas round-trip dtypes" in block["reason"]
    assert "p (integer with nulls)" in block["reason"]


def test_at_a5_the_auto_lane_hands_the_stock_adapter() -> None:
    from decoy_engine.execution._pandas_adapter import PandasExecutionAdapter

    assert is_stock_adapter(None)
    assert is_stock_adapter(PandasExecutionAdapter())

    class Custom(PandasExecutionAdapter):
        pass

    assert not is_stock_adapter(Custom())


def test_at_a6_nested_columns_profile_without_error_and_carry(tmp_path: Path) -> None:
    import random

    from decoy_engine.profile._readers_resident import ResidentTableSource
    from decoy_engine.profile._source import _profile_one_source

    table = source_table("list", "later_mixed").append_column(
        "q", source_table("struct", "later_mixed").column("p")
    )
    profile = _profile_one_source(
        ResidentTableSource(table),
        table_name="t",
        declared_pk_cols=frozenset(),
        fk_specs={},
        sample_rows=None,
        residency="full",
        rng=random.Random(0),
    )
    by_name = {c.name: c for c in profile.columns}
    assert by_name["p"].distinct_count is None
    assert by_name["q"].distinct_count is None
    cfg = _cfg(tmp_path, table, support.pass_col("p"), extra=[support.pass_col("q")])
    got = _run(table, cfg)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    out = got.outputs[support.TABLE]
    assert out.column("p").to_pylist() == table.column("p").to_pylist()
    assert out.column("q").to_pylist() == table.column("q").to_pylist()


def test_at_a7_the_decline_carries_a_registered_code(tmp_path: Path) -> None:
    from decoy_engine.execution.physical._reasons import (
        CODE_CHUNKED_SOURCE_DTYPE_UNSTABLE,
        translate_chunked_rejection,
    )

    codes = translate_chunked_rejection(_when_read_run(tmp_path)["reason"])
    assert CODE_CHUNKED_SOURCE_DTYPE_UNSTABLE in codes
    assert not any(c.startswith("unclassified") for c in codes)


def test_at_a9_small_nested_table_on_full_frame_is_exact(tmp_path: Path) -> None:
    table = source_table("list", "later_mixed").slice(0, 8)
    table = table.append_column("q", source_table("struct", "later_mixed").column("p").slice(0, 8))
    cfg = _cfg(tmp_path, table, support.pass_col("p"), extra=[support.pass_col("q")])
    got = support.run_default(cfg, table, auto_chunk_threshold_rows=10_000)
    assert got.quality_metrics["auto_chunk"]["mode"] == "full_frame"
    out = got.outputs[support.TABLE]
    assert out.column("p").to_pylist() == table.column("p").to_pylist()
    assert out.column("q").to_pylist() == table.column("q").to_pylist()


def test_g3_read_set_has_one_production_caller() -> None:
    root = Path(carry.__file__).resolve().parents[1]
    callers: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                    if name == "read_set":
                        callers.append(f"{path.name}:{fn.name}")
    assert callers == ["_chunked_carry.py:carried_columns"]


# -- part (b1): masked columns of admitted types (AT-B1 to AT-B3, G-1 masked rows) --------------

_CLASS_TYPES = {
    "int_with_nulls": ["int64_nulls", "uint64"],
    "decimal": ["decimal128"],
    "binary": ["binary", "large_binary", "fixed_size_binary"],
}


def _masked_entry(strategy: str, name: str = "p") -> dict[str, Any]:
    if strategy == "hash":
        return support.hash_col(name)
    if strategy == "redact":
        return support.redact_col(name)
    return support.faker_col(name)


def _masked_cells() -> list[tuple[str, str, str]]:
    from decoy_engine.execution.chunked._source_dtype_gate import CHUNK_STABLE_MASKED_SOURCE_TYPES

    return [
        (strategy, t, lay)
        for strategy, classes in CHUNK_STABLE_MASKED_SOURCE_TYPES.items()
        for cls in sorted(classes)
        for t in _CLASS_TYPES[cls]
        for lay in LAYOUTS
    ]


MASKED = _masked_cells()


@pytest.mark.parametrize(("strategy", "type_class", "layout"), MASKED)
def test_at_b1_admitted_masked_pair_is_chunked_and_equals_the_oracle(
    tmp_path: Path, strategy: str, type_class: str, layout: str
) -> None:
    table = source_table(type_class, layout)
    cfg = _cfg(tmp_path, table, _masked_entry(strategy))
    got = _run(table, cfg)
    block = got.quality_metrics["auto_chunk"]
    assert block["mode"] == "chunked", block["reason"]
    base = _oracle(table, cfg).outputs[support.TABLE]
    out = got.outputs[support.TABLE]
    assert out.schema.field("p").type == base.schema.field("p").type
    assert out.column("p").to_pylist() == base.column("p").to_pylist()


def test_g1_every_table_pair_has_a_cell() -> None:
    from decoy_engine.execution.chunked._source_dtype_gate import CHUNK_STABLE_MASKED_SOURCE_TYPES

    cells = {(s, t) for s, t, _ in MASKED}
    for strategy, classes in CHUNK_STABLE_MASKED_SOURCE_TYPES.items():
        for cls in classes:
            assert all((strategy, t) in cells for t in _CLASS_TYPES[cls])


def test_at_b2_a_pair_outside_the_table_stays_full_frame(tmp_path: Path) -> None:
    table = source_table("int64_nulls", "later_mixed")
    non_deterministic = {**support.faker_col("p"), "deterministic": False}
    got = _run(table, _cfg(tmp_path, table, non_deterministic))
    block = got.quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame"
    assert "p (integer with nulls)" in block["reason"]


def test_at_b2_the_table_does_not_name_numeric_strategies() -> None:
    from decoy_engine.execution.chunked._source_dtype_gate import CHUNK_STABLE_MASKED_SOURCE_TYPES

    assert set(CHUNK_STABLE_MASKED_SOURCE_TYPES) == {"hash", "redact", "faker"}


def test_at_b3_a_masked_column_read_by_another_entry_stays_full_frame(tmp_path: Path) -> None:
    table = source_table("int64_nulls", "later_mixed")
    cfg = _cfg(
        tmp_path,
        table,
        support.hash_col("p"),
        s_entry={**support.redact_col("s"), "when": "p == p"},
    )
    block = _run(table, cfg).quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame"
    assert "p (integer with nulls)" in block["reason"]


def test_at_b3_a_hash_with_its_own_when_is_not_admitted() -> None:
    from decoy_engine.execution import _chunked_input as ci
    from decoy_engine.execution.chunked._source_dtype_gate import admitted_masked_columns
    from decoy_engine.providers_v2 import get_default_registry

    table = source_table("int64_nulls", "later_mixed")
    facts = ci.facts_for(None, table, "t")
    registry = get_default_registry()
    plain = [support.redact_col("s"), support.hash_col("p")]
    gated = [support.redact_col("s"), {**support.hash_col("p"), "when": "p > 3"}]
    assert admitted_masked_columns(facts, plain, registry) == {"p"}
    assert admitted_masked_columns(facts, gated, registry) == frozenset()


# -- kill switch, physical plan, stream and lazy legs (Dennis r1 on #725) -----------------------

LEGACY_TYPES = [t for t in CARRIED_TYPES if t != "map"]


@pytest.mark.parametrize("type_class", LEGACY_TYPES)
def test_at_a1_kill_switch_lane_keeps_the_registered_decline(
    tmp_path: Path, type_class: str
) -> None:
    """`chunked_dispatcher_enabled=False` runs the legacy oracle, which converts every column to
    pandas: no column is exempt, so the table runs full-frame as it did before."""
    from decoy_engine.execution.physical._reasons import (
        CODE_CHUNKED_SOURCE_DTYPE_UNSTABLE,
        translate_chunked_rejection,
    )

    table = source_table(type_class, "later_mixed")
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    got = support.run_legacy(cfg, table)
    block = got.quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame", block
    assert CODE_CHUNKED_SOURCE_DTYPE_UNSTABLE in translate_chunked_rejection(block["reason"])


@pytest.mark.parametrize("dispatcher", [True, False])
def test_the_physical_compiler_reads_the_kill_switch(tmp_path: Path, dispatcher: bool) -> None:
    from decoy_engine.execution.physical._compiler import layer2_chunk_decision
    from decoy_engine.execution.physical._snapshot import capture_physical_plan_inputs

    table = source_table("int64_nulls", "later_mixed")
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    inputs = capture_physical_plan_inputs(
        cfg,
        {support.TABLE: table},
        engine_version=support.ENGINE_VERSION,
        auto_chunk_threshold_rows=support.THRESHOLD,
        chunked_dispatcher_enabled=dispatcher,
    )
    _, route_chunked = layer2_chunk_decision(inputs)
    assert route_chunked is dispatcher


def test_at_a5_the_auto_lane_hands_run_mask_chunked_the_stock_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution.native.chunked import _core

    seen: list[Any] = []
    real = _core.mask_chunked

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["adapter"])
        return real(*args, **kwargs)

    monkeypatch.setattr(_core, "mask_chunked", spy)
    table = source_table("int64_nulls", "later_mixed")
    got = _run(table, _cfg(tmp_path, table, support.pass_col("p")))
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert seen
    assert all(is_stock_adapter(a) for a in seen)


@pytest.mark.xfail(
    strict=True,
    raises=pa.ArrowTypeError,
    reason="follow-up: the full-frame adapter cannot rebuild a map column from pandas",
)
def test_at_a9_small_map_table_on_full_frame(tmp_path: Path) -> None:
    table = source_table("map", "later_mixed").slice(0, 8)
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    got = support.run_default(cfg, table, auto_chunk_threshold_rows=10_000)
    assert got.outputs[support.TABLE].column("p").to_pylist() == table.column("p").to_pylist()


LEG_TYPES = ["int64_nulls", "uint64", "decimal128", "binary", "dictionary", "list", "map"]


def _written(sink_dir: Path) -> pa.Table:
    import pyarrow.parquet as pq

    return pq.read_table(sink_dir / f"{support.TABLE}.parquet")


@pytest.mark.parametrize("mode", ["auto", "stream"])
@pytest.mark.parametrize("type_class", LEG_TYPES)
def test_a_lazy_parquet_source_streams_a_carried_column_exactly(
    tmp_path: Path, mode: str, type_class: str
) -> None:
    from decoy_engine.execution import run_pipeline
    from decoy_engine.profile._readers import LazySource
    from tests.unit.execution.run_stream import _support as rs

    table = source_table(type_class, "later_mixed")
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    sink, target = rs.engine_sink(tmp_path)
    run_pipeline(
        cfg,
        sources={support.TABLE: LazySource(tmp_path / "src.parquet")},
        sink=sink,
        engine_version=support.ENGINE_VERSION,
        execution_mode=mode,
        auto_chunk_threshold_rows=support.THRESHOLD,
        chunk_size_rows=support.CHUNK,
    )
    got = _written(target)
    assert got.schema.field("p").type == table.schema.field("p").type
    assert got.column("p").to_pylist() == table.column("p").to_pylist()


def test_a_stream_fk_job_carries_a_passthrough_column_exactly(tmp_path: Path) -> None:
    """Stream drops the FK graph for its lane view, so an FK job takes the carried exemption in
    stream mode. The extra column must come back as the source holds it."""
    import pyarrow.parquet as pq

    from decoy_engine.config import PipelineConfig
    from decoy_engine.profile._readers import LazySource
    from tests.unit.execution.run_stream import _support as rs

    cfg, _lazy, tables = rs.fk_job(tmp_path)
    orders = tables["orders"].append_column(
        "x", pa.array([None if i % 4 == 0 else 2**53 + i for i in range(31)], pa.int64())
    )
    path = cfg["sources"]["orders"]["path"]
    pq.write_table(orders, path)
    order_cols = next(t for t in cfg["tables"] if t["name"] == "orders")["columns"]
    order_cols.append(support.pass_col("x"))
    cfg = PipelineConfig.model_validate(cfg).model_dump()
    sink, target = rs.engine_sink(tmp_path)
    result = rs.run_stream(
        cfg,
        {
            "customers": LazySource(Path(cfg["sources"]["customers"]["path"])),
            "orders": LazySource(Path(path)),
        },
        sink,
        chunk_size_rows=7,
    )
    entries = result.quality_metrics["auto_chunk"]["tables"]
    assert all(t["dispatched"] for t in entries)
    got = pq.read_table(target / "orders.parquet")
    assert got.schema.field("x").type == pa.int64()
    assert got.column("x").to_pylist() == orders.column("x").to_pylist()
