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
    """The carried-set function the planner and the lane both call: unconfigured columns are
    passthrough under the policy, a duplicated name carries nothing."""
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


@pytest.mark.parametrize("policy", ["warn", "error", None])
def test_at_a2_unconfigured_columns_cannot_reach_run_pipeline(
    tmp_path: Path, policy: str | None
) -> None:
    """The unconfigured shape has no end-to-end run: `run_pipeline` refuses a source column the
    config leaves out (`source_file.undeclared_column`) before it routes, whatever the
    unconfigured-column policy, and a mask table needs a declared file source, so a resident
    `pa.Table` cannot dodge the gate. The carried-set function above is therefore the only
    place the shape is reachable, and the planner and the lane both call it."""
    from decoy_engine.errors import PipelineValidationError

    table = source_table("int64_nulls", "later_mixed")
    cfg = _cfg(tmp_path, table, None)  # `p` is in the source file but not in the table entry
    if policy is not None:
        cfg["global_settings"]["unconfigured_column_policy"] = policy
    with pytest.raises(PipelineValidationError, match="undeclared_column"):
        _run(table, cfg)


@pytest.mark.parametrize(("type_class", "layout"), CELLS, ids=IDS)
def test_at_a3_masked_column_equals_the_full_frame_oracle(
    tmp_path: Path, type_class: str, layout: str
) -> None:
    """The masked column `s` carries a keyed hash, so its values depend on the whole
    pipeline: a carried sibling must not change what the masking writes. Type and values
    are compared with the full-frame run over every type class and null layout."""
    table = source_table(type_class, layout)
    cfg = _cfg(tmp_path, table, support.pass_col("p"), s_entry=support.hash_col("s", "ns_a3"))
    got = _run(table, cfg)
    base = _oracle(table, cfg)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    a, b = got.outputs[support.TABLE], base.outputs[support.TABLE]
    assert a.schema.field("s").type == b.schema.field("s").type
    assert a.column("s").to_pylist() == b.column("s").to_pylist()
    assert a.column("s").to_pylist() != table.column("s").to_pylist()


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


def test_at_a4_a_column_read_as_a_sibling_reference_stays_full_frame(tmp_path: Path) -> None:
    """`group_by` names `p`, so the read set keeps `p` out of the carried set and the dtype gate
    judges it. Without the read-set subtraction this job would route chunked."""
    table = source_table("int64_nulls", "later_mixed")
    entry = {**support.redact_col("s"), "provider_config": {"group_by": "p"}}
    cfg = _cfg(tmp_path, table, support.pass_col("p"), s_entry=entry)
    block = _run(table, cfg).quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame"
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


def _scan(source: str, filename: str, target: str) -> list[str]:
    """`file:function` of every call to `target` in `source`, by AST. A call counts whether it
    names the function directly, through a `from ... import ... as` alias or a rebinding, or as
    an attribute of a module, and whether it sits in a function or at module level."""
    tree = ast.parse(source)
    names = {target}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == target and a.asname}
    for node in ast.walk(tree):  # `rs = read_set` rebinds the function under a new name
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute)):
            bound = node.value.id if isinstance(node.value, ast.Name) else node.value.attr
            if bound in names:
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    found: list[str] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                f = child.func
                if (f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")) in names:
                    found.append(f"{filename}:{scope}")
            is_def = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            visit(child, child.name if is_def else scope)

    visit(tree, "<module>")
    return found


def _production_callers(target: str) -> list[str]:
    root = Path(carry.__file__).resolve().parents[1]
    return [
        hit
        for path in sorted(root.rglob("*.py"))
        for hit in _scan(path.read_text(), path.name, target)
    ]


def test_g3_read_set_has_one_production_caller() -> None:
    assert _production_callers("read_set") == ["_chunked_carry.py:carried_columns"]


def test_g3_carried_columns_has_exactly_two_production_callers() -> None:
    """The planner's dtype gate and `plan_carry`: a third caller is a second place that can
    disagree on which columns are carried."""
    assert _production_callers("carried_columns") == [
        "_chunked_carry.py:plan_carry",
        "_planner.py:_runtime_source_rejections",
    ]


def test_g3_the_scanner_resolves_aliases_and_module_level_calls() -> None:
    src = (
        "from m import read_set as rs\n"
        "import m\n"
        "alias = rs\n"
        "rs([], [], None)\n"
        "def f():\n    return alias([], [], None)\n"
        "class C:\n    def g(self):\n        return m.read_set([], [], None)\n"
        "def h():\n    return other()\n"
    )
    assert _scan(src, "x.py", "read_set") == ["x.py:<module>", "x.py:f", "x.py:g"]


# -- kill switch, physical plan, stream and lazy legs (Dennis r1 on #725) -----------------------

LEGACY_TYPES = list(CARRIED_TYPES)


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


def test_at_a9_small_map_table_on_full_frame_is_exact(tmp_path: Path) -> None:
    """The full-frame adapter rebuilds a map column with the source's map type."""
    table = source_table("map", "later_mixed").slice(0, 8)
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    got = support.run_default(cfg, table, auto_chunk_threshold_rows=10_000)
    assert got.quality_metrics["auto_chunk"]["mode"] == "full_frame"
    out = got.outputs[support.TABLE]
    assert out.schema.field("p").type == table.schema.field("p").type
    assert out.column("p").to_pylist() == table.column("p").to_pylist()


@pytest.mark.parametrize(
    ("route", "knobs"),
    [
        ("sequential", {"execution_mode": "sequential"}),
        ("full_frame", {"execution_mode": "full_frame"}),
        ("out_of_core", {}),
    ],
)
def test_a_map_column_on_an_fk_job_is_exact(
    tmp_path: Path, route: str, knobs: dict[str, Any]
) -> None:
    """An FK job keeps a map column on every route it can take: the sequential and full-frame
    conversions rebuild it from the source type, out-of-core never leaves Arrow."""
    import pyarrow.parquet as pq

    from decoy_engine.config import PipelineConfig
    from decoy_engine.execution import run_pipeline
    from tests.unit.execution.run_stream import _support as rs

    cfg, _lazy, tables = rs.fk_job(tmp_path)
    orders = tables["orders"].append_column(
        "m", source_table("map", "later_mixed").column("p").slice(0, 31).combine_chunks()
    )
    pq.write_table(orders, cfg["sources"]["orders"]["path"])
    next(t for t in cfg["tables"] if t["name"] == "orders")["columns"].append(support.pass_col("m"))
    cfg = PipelineConfig.model_validate(cfg).model_dump()
    result = run_pipeline(
        cfg,
        sources={"customers": tables["customers"], "orders": orders},
        engine_version=rs.ENGINE_VERSION,
        auto_chunk_threshold_rows=1,
        **knobs,
    )
    assert result.quality_metrics["execution"]["execution_mode"] == route
    out = result.outputs["orders"]
    assert out.schema.field("m").type == orders.schema.field("m").type
    assert out.column("m").to_pylist() == orders.column("m").to_pylist()


LEG_TYPES = ["int64_nulls", "uint64", "decimal128", "binary", "dictionary", "list", "map"]


def _written(sink_dir: Path) -> pa.Table:
    import pyarrow.parquet as pq

    return pq.read_table(sink_dir / f"{support.TABLE}.parquet")


def _run_lazy(tmp_path: Path, table: pa.Table, mode: str, **write_options: Any) -> Any:
    """Run `table` as a lazy Parquet source (written with `write_options`) into the engine sink."""
    import pyarrow.parquet as pq

    from decoy_engine.execution import run_pipeline
    from decoy_engine.profile._readers import LazySource
    from tests.unit.execution.run_stream import _support as rs

    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    if write_options:
        pq.write_table(table, str(tmp_path / "src.parquet"), **write_options)
    sink, target = rs.engine_sink(tmp_path)
    result = run_pipeline(
        cfg,
        sources={support.TABLE: LazySource(tmp_path / "src.parquet")},
        sink=sink,
        engine_version=support.ENGINE_VERSION,
        execution_mode=mode,
        auto_chunk_threshold_rows=support.THRESHOLD,
        chunk_size_rows=support.CHUNK,
    )
    return result, _written(target)


@pytest.mark.parametrize("mode", ["auto", "stream"])
@pytest.mark.parametrize("type_class", LEG_TYPES)
def test_a_lazy_parquet_source_streams_a_carried_column_exactly(
    tmp_path: Path, mode: str, type_class: str
) -> None:
    table = source_table(type_class, "later_mixed")
    result, got = _run_lazy(tmp_path, table, mode)
    block = result.quality_metrics["auto_chunk"]
    if mode == "auto":
        assert block["mode"] == "chunked", block.get("reason")
    assert block["input"]["mode"] == "lazy", block["input"]
    assert got.schema.field("p").type == table.schema.field("p").type
    assert got.column("p").to_pylist() == table.column("p").to_pylist()


@pytest.mark.parametrize("type_class", ["int64_nulls", "uint64"])
def test_a_carried_integer_column_needs_no_footer_null_count(
    tmp_path: Path, type_class: str
) -> None:
    """Parquet written without statistics has no footer null count for `p`. Nothing reads that
    count for a carried column, so the table still routes chunked; the same file with `p` read
    by a `when:` predicate declines on the missing count."""
    table = source_table(type_class, "later_mixed")
    result, got = _run_lazy(tmp_path, table, "auto", write_statistics=False)
    block = result.quality_metrics["auto_chunk"]
    assert block["mode"] == "chunked", block.get("reason")
    assert block["input"]["mode"] == "lazy", block["input"]
    assert got.column("p").to_pylist() == table.column("p").to_pylist()


def test_a_read_integer_column_without_footer_statistics_still_declines(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from decoy_engine.execution import run_pipeline
    from decoy_engine.profile._readers import LazySource
    from tests.unit.execution.run_stream import _support as rs

    table = source_table("int64_nulls", "later_mixed")
    cfg = _cfg(
        tmp_path,
        table,
        support.pass_col("p"),
        s_entry={**support.redact_col("s"), "when": "p > 3"},
    )
    pq.write_table(table, str(tmp_path / "src.parquet"), write_statistics=False)
    sink, _target = rs.engine_sink(tmp_path)
    result = run_pipeline(
        cfg,
        sources={support.TABLE: LazySource(tmp_path / "src.parquet")},
        sink=sink,
        engine_version=support.ENGINE_VERSION,
        execution_mode="auto",
        auto_chunk_threshold_rows=support.THRESHOLD,
        chunk_size_rows=support.CHUNK,
    )
    block = result.quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame"
    assert "lazy_source_null_count_unavailable" in block["reason"]


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


# -- a masked map column converts as any masked column does (Codex final on #725) ---------------

MASKED_MAP = {
    "redact": support.redact_col,
    "truncate": support.truncate_col,
    "hash": support.hash_col,
    "faker": support.faker_col,
}


def _fk_job_with_map(
    tmp_path: Path, entry: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    """customers -> orders, with a map column `m` on orders in the middle of the columns."""
    import pyarrow.parquet as pq

    from decoy_engine.config import PipelineConfig
    from tests.unit.execution.run_stream import _support as rs

    cfg, _lazy, tables = rs.fk_job(tmp_path)
    maps = source_table("map", "later_mixed").column("p").slice(0, 31).combine_chunks()
    orders = tables["orders"].add_column(0, "a", pa.array(range(31), pa.int64()))
    orders = orders.add_column(2, "m", maps).append_column("z", pa.array(range(31), pa.int64()))
    pq.write_table(orders, cfg["sources"]["orders"]["path"])
    cols = next(t for t in cfg["tables"] if t["name"] == "orders")["columns"]
    cols[:] = [support.pass_col("a"), cols[0], entry, support.pass_col("z")]
    cfg = PipelineConfig.model_validate(cfg).model_dump()
    return cfg, {"customers": tables["customers"], "orders": orders}


def _assert_masked_map(
    out: pa.Column | pa.ChunkedArray, source: pa.ChunkedArray, strategy: str
) -> None:
    assert not pa.types.is_map(out.type), out.type
    got, want = out.to_pylist(), source.to_pylist()
    assert [v is None for v in got] == [v is None for v in want]
    if strategy == "redact":
        assert {v for v in got if v is not None} == {"REDACTED"}


@pytest.mark.parametrize("strategy", list(MASKED_MAP))
def test_a_masked_map_column_on_full_frame_is_not_forced_back_to_a_map(
    tmp_path: Path, strategy: str
) -> None:
    table = source_table("map", "later_mixed").slice(0, 40)
    cfg = _cfg(tmp_path, table, MASKED_MAP[strategy]("p"))
    got = support.run_default(cfg, table, auto_chunk_threshold_rows=10_000)
    assert got.quality_metrics["auto_chunk"]["mode"] == "full_frame"
    _assert_masked_map(got.outputs[support.TABLE].column("p"), table.column("p"), strategy)


@pytest.mark.parametrize("route", ["sequential", "full_frame"])
@pytest.mark.parametrize("strategy", list(MASKED_MAP))
def test_a_masked_map_column_on_an_fk_job_is_not_forced_back_to_a_map(
    tmp_path: Path, strategy: str, route: str
) -> None:
    from decoy_engine.execution import run_pipeline
    from tests.unit.execution.run_stream import _support as rs

    cfg, tables = _fk_job_with_map(tmp_path, MASKED_MAP[strategy]("m"))
    result = run_pipeline(
        cfg, sources=tables, engine_version=rs.ENGINE_VERSION, execution_mode=route
    )
    assert result.quality_metrics["execution"]["execution_mode"] == route
    out = result.outputs["orders"]
    _assert_masked_map(out.column("m"), tables["orders"].column("m"), strategy)


@pytest.mark.parametrize("route", ["sequential", "full_frame"])
def test_a_passthrough_map_keeps_its_place_between_other_columns(
    tmp_path: Path, route: str
) -> None:
    from decoy_engine.execution import run_pipeline
    from tests.unit.execution.run_stream import _support as rs

    cfg, tables = _fk_job_with_map(tmp_path, support.pass_col("m"))
    result = run_pipeline(
        cfg, sources=tables, engine_version=rs.ENGINE_VERSION, execution_mode=route
    )
    out = result.outputs["orders"]
    assert out.column_names == tables["orders"].column_names
    assert out.schema.field("m").type == tables["orders"].schema.field("m").type
    assert out.column("m").to_pylist() == tables["orders"].column("m").to_pylist()


# AT-A8: `run_mask_chunked` called directly (`--chunked`) is unchanged by this slice. The cells
# below pass on the base head too; they pin what the direct entry returns for a carried column.
@pytest.mark.parametrize(
    "type_class", ["int64_nulls", "uint64", "decimal128", "dictionary", "list"]
)
def test_at_a8_run_mask_chunked_direct_output_is_unchanged(tmp_path: Path, type_class: str) -> None:
    from decoy_engine import run_mask_chunked
    from tests.native._chunked_entry_support import ENGINE_VERSION, TABLE, key_provider, split

    table = source_table(type_class, "later_mixed")
    cfg = _cfg(tmp_path, table, support.pass_col("p"))
    chunks = list(
        run_mask_chunked(
            cfg,
            split(table, support.CHUNK),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
        )
    )
    out = pa.concat_tables(chunks)
    assert out.schema.field("p").type == table.schema.field("p").type
    assert out.column("p").to_pylist() == table.column("p").to_pylist()
