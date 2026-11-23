"""UF-DOMAIN S1 (one assembler): a column no rule changes is written from the source Arrow
column on every pandas-built route, so its type, values and nulls never depend on the route.

Plan: docs/plans/2026-11-22-uf-domain.md, acceptance tests U1, U2, U7, U8.
"""

from __future__ import annotations

import datetime as dt
import decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution import run_pipeline
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._unified_slice_evidence import reconstruct_source_shaped_output
from decoy_engine.execution.pipeline._source_types import table_from_pandas_keeping_source_types
from decoy_engine.relationships._graph import OrphanPolicy
from tests.native._chunked_entry_support import key_provider
from tests.parity import _d2b_shapes as s
from tests.unit.execution._auto_chunk_support import (
    TABLE,
    hash_col,
    make_cfg,
    pass_col,
    write_source,
)

_D = decimal.Decimal
_NAN = float("nan")


def _typed_columns(n: int) -> dict[str, pa.Array]:
    """One passthrough column per type family plan section 4 names. Each holds a null (or NaN
    for the floats) at row 1 so a lossy null path shows."""

    def cells(values: list[Any], t: pa.DataType) -> pa.Array:
        return pa.array([values[i % len(values)] for i in range(n)], t)

    return {
        "c_dec12": cells([_D("1.50"), None, _D("-3.25")], pa.decimal128(12, 2)),
        "c_dec256": cells([_D("1.5000"), None, _D("2.2500")], pa.decimal256(40, 4)),
        "c_i8": cells([1, None, -3], pa.int8()),
        "c_i64_null": cells([2**53 + 1, None, 5], pa.int64()),
        "c_u64": cells([2**64 - 1, None, 7], pa.uint64()),
        "c_f32": cells([1.5, _NAN, None], pa.float32()),
        "c_f64": cells([1.5, _NAN, None], pa.float64()),
        "c_date32": cells([dt.date(2020, 1, 2), None, dt.date(1999, 12, 31)], pa.date32()),
        "c_date64": cells([dt.date(2020, 1, 2), None, dt.date(1999, 12, 31)], pa.date64()),
        "c_ts_ms_utc": cells(
            [dt.datetime(2020, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc), None, None],
            pa.timestamp("ms", tz="UTC"),
        ),
        "c_ts_ns": cells(
            [pd.Timestamp("2020-01-02 03:04:05.123456789"), None, None], pa.timestamp("ns")
        ),
        "c_large_string": cells(["aa", None, "cc"], pa.large_string()),
        "c_binary": cells([b"\x00\x01", None, b"z"], pa.binary()),
        "c_list": cells([[1, 2], None, []], pa.list_(pa.int32())),
        "c_struct": cells([{"a": 1}, None, {"a": None}], pa.struct([("a", pa.int16())])),
    }


def _same_cells(a: pa.ChunkedArray, b: pa.ChunkedArray) -> bool:
    """Arrow `equals` treats NaN as unequal to itself, so a float column that equals its own
    source would fail; cells compare by `repr` (NaN, null and the exact decimal all show)."""
    return a.type == b.type and [repr(v) for v in a.to_pylist()] == [repr(v) for v in b.to_pylist()]


def _o3(table: pa.Table) -> pa.Table:
    """The source as every route writes it: carried text leaves as `string` (O3)."""
    for i, field in enumerate(table.schema):
        if pa.types.is_large_string(field.type):
            table = table.set_column(
                i, field.with_type(pa.string()), table.column(i).cast(pa.string())
            )
    return table


def _assert_columns_equal_source(out: pa.Table, source: pa.Table, names: list[str]) -> None:
    source = _o3(source)
    for name in names:
        assert out.schema.field(name).type == source.schema.field(name).type, name
        assert _same_cells(out.column(name), source.column(name)), name
    # Position: the name sits where the source put it.
    for name in names:
        assert out.schema.get_field_index(name) == source.schema.get_field_index(name), name


def _hash_shape(n: int) -> tuple[s.Shape, pa.Table]:
    typed = _typed_columns(n)
    child = pa.table({"k": s.strs([f"k{i}" for i in range(n)]), **typed})
    plan = s.make_plan(
        {
            "A": s.table_seed({"k": s.hashed("ns_k")}),
            "B": s.table_seed({"k": s.hashed("ns_k"), **{c: s.passthrough() for c in typed}}),
        }
    )
    graph = s.graph(s.edge("A", "k", "B", "k", "ns_k", OrphanPolicy.PRESERVE))
    parent = pa.table({"k": s.strs([f"k{i}" for i in range(n)])})
    return s.Shape(plan, graph, {"A": parent, "B": child}), child


def test_u1_untouched_types_keep_source_type_full_frame() -> None:
    shape, child = _hash_shape(3)
    out = s.run_full(shape).outputs["B"]
    _assert_columns_equal_source(out, child, list(_typed_columns(3)))
    assert out.column_names == child.column_names
    assert out.column("k").to_pylist() != child.column("k").to_pylist()  # the hash target ran


def test_u1_untouched_types_keep_source_type_sequential() -> None:
    shape, child = _hash_shape(3)
    out = s.run_seq(shape).outputs["B"]
    _assert_columns_equal_source(out, child, list(_typed_columns(3)))
    assert out.column_names == child.column_names


# U2: every column passthrough, at 3 rows and 0 rows.


@pytest.mark.parametrize("unified", [False, True], ids=["full_frame", "unified"])
def test_u2_all_untouched_three_rows(tmp_path: Path, unified: bool) -> None:
    source = pa.table(_typed_columns(3))
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg([pass_col(c) for c in source.column_names], path=path)
    out = run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        auto_chunk=False,
        unified_slice_enabled=unified,
    ).outputs[TABLE]
    assert out.num_rows == 3
    assert out.column_names == source.column_names
    _assert_columns_equal_source(out, source, source.column_names)


def test_u2_all_untouched_zero_rows_full_frame() -> None:
    # `run_pipeline` refuses a zero-row table in its memory probe, so the adapter runs it directly.
    source = pa.table(_typed_columns(0))
    plan = s.make_plan({"T": s.table_seed({c: s.passthrough() for c in source.column_names})})
    shape = s.Shape(plan, s.graph(), {"T": source})
    out = s.run_full(shape).outputs["T"]
    assert out.num_rows == 0
    assert out.column_names == source.column_names
    _assert_columns_equal_source(out, source, source.column_names)


def test_u2_all_untouched_zero_rows_unified_assembly() -> None:
    source = pa.table(_typed_columns(0))
    out = reconstruct_source_shaped_output(
        table="T",
        frame=source.to_pandas(),
        source=source,
        untouched=set(source.column_names),
        masked_table=pa.table({}),
        nodes=(),
    )["T"]
    assert out.num_rows == 0
    _assert_columns_equal_source(out, source, source.column_names)


# U7: one config, every route, one output type per column.

_U7_TYPES = ("c_dec12", "c_i64_null", "c_large_string", "c_ts_ms_utc")


def _u7_source(n: int) -> pa.Table:
    typed = _typed_columns(n)
    return pa.table({"h": s.strs([f"v{i}" for i in range(n)]), **{c: typed[c] for c in _U7_TYPES}})


def _u7_run(tmp_path: Path, source: pa.Table, **options: Any) -> pa.Table:
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg(
        [hash_col("h"), *[pass_col(c) for c in _U7_TYPES]],
        path=path,
    )
    return run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        **{"auto_chunk": False, **options},
    ).outputs[TABLE]


@pytest.mark.parametrize(
    "options",
    [
        {"unified_slice_enabled": True},
        {"unified_slice_enabled": False},
        {"post_validation": True},
        {"fidelity_report": True},
    ],
    ids=["unified", "full_frame", "post_validation", "fidelity_report"],
)
def test_u7_same_output_types_on_every_option(tmp_path: Path, options: dict[str, Any]) -> None:
    source = _u7_source(2_000)
    out = _u7_run(tmp_path, source, **options)
    assert out.num_rows == source.num_rows
    want = _o3(source)
    for name in _U7_TYPES:
        assert out.schema.field(name).type == want.schema.field(name).type, name
        assert _same_cells(out.column(name), want.column(name)), name


def test_u7_sequential_fk_child_matches_full_frame() -> None:
    shape, child = _hash_shape(50)
    full = s.run_full(shape).outputs["B"]
    seq = s.run_seq(shape).outputs["B"]
    assert full.schema.remove_metadata() == seq.schema.remove_metadata()
    # The masked FK key is not an untouched column: it is rebuilt from the frame, so it differs
    # from the source and matches the full-frame route.
    assert seq.column("k").to_pylist() != child.column("k").to_pylist()
    assert seq.column("k").to_pylist() == full.column("k").to_pylist()
    for name in _typed_columns(50):
        assert _same_cells(full.column(name), seq.column(name)), name


# U8: the assembler refuses a frame that is no longer the source's rows.


def _source3() -> pa.Table:
    return pa.table({"a": [1, 2, 3], "b": ["x", "y", "z"], "c": [1.5, 2.5, 3.5]})


def test_u8_frame_one_row_short_raises_with_counts_only() -> None:
    source = _source3()
    frame = pd.DataFrame({"a": [1, 2], "b": ["secret-1", "secret-2"], "c": [1.5, 2.5]})
    with pytest.raises(ExecutionError) as exc:
        table_from_pandas_keeping_source_types(frame, source, {"c"})
    assert exc.value.code == "output_assembly_rows_changed"
    assert "2 rows" in str(exc.value) and "has 3" in str(exc.value)
    assert "secret" not in str(exc.value)


def test_u8_reordered_index_raises() -> None:
    source = _source3()
    frame = source.to_pandas().iloc[[2, 1, 0]]
    with pytest.raises(ExecutionError) as exc:
        table_from_pandas_keeping_source_types(frame, source, {"c"})
    assert exc.value.code == "output_assembly_rows_changed"


def test_u8_columns_out_of_order_raise() -> None:
    source = _source3()
    frame = source.to_pandas()[["b", "a", "c"]]
    with pytest.raises(ExecutionError) as exc:
        table_from_pandas_keeping_source_types(frame, source, set())
    assert exc.value.code == "output_assembly_columns_mismatch"


def test_u8_zero_column_frame_takes_source_row_count() -> None:
    source = _source3()
    out = table_from_pandas_keeping_source_types(source.to_pandas()[[]], source, {"a", "b", "c"})
    assert out.num_rows == 3
    assert out.equals(source)


def test_u8_arrow_columns_are_written_as_given() -> None:
    source = _source3()
    given = pa.array([10, 20, 30], pa.int8())
    frame = source.to_pandas()[["b"]]
    out = table_from_pandas_keeping_source_types(frame, source, {"c"}, arrow_columns={"a": given})
    assert out.column_names == ["a", "b", "c"]
    assert out.schema.field("a").type == pa.int8()
    assert out.column("a").to_pylist() == [10, 20, 30]
    assert _same_cells(out.column("c"), source.column("c"))


@pytest.mark.parametrize("route", ["full_frame", "sequential"])
def test_passthrough_fk_child_key_still_follows_its_masked_parent(route: str) -> None:
    """A child key whose own strategy is passthrough is rewritten by the FK cascade, so it is
    not an untouched column and must come from the frame, not the source."""
    keys = [f"k{i}" for i in range(4)]
    plan = s.make_plan(
        {
            "A": s.table_seed({"k": s.hashed("ns_k")}),
            "B": s.table_seed({"k": s.passthrough(), "x": s.passthrough()}),
        }
    )
    graph = s.graph(s.edge("A", "k", "B", "k", "ns_k", OrphanPolicy.PRESERVE))
    child = pa.table({"k": s.strs(keys), "x": pa.array([1, 2, 3, 4], pa.int8())})
    shape = s.Shape(plan, graph, {"A": pa.table({"k": s.strs(keys)}), "B": child})
    result = s.run_full(shape) if route == "full_frame" else s.run_seq(shape)
    assert (
        result.outputs["B"].column("k").to_pylist() == result.outputs["A"].column("k").to_pylist()
    )
    assert result.outputs["B"].column("k").to_pylist() != keys
    assert result.outputs["B"].column("x").equals(child.column("x"))


# U1 completions: a composite FK child, a `subset:` run and the chunked and validator routes.


def test_u1_composite_child_untouched_column_keeps_source_type() -> None:
    base = s.composite_shape()
    child = pa.table(
        {
            "k": s.strs(["a", "b", "q", None]),
            "j": s.strs(["x", "y", "w", "x"]),
            "amt": pa.array([_D("1.10"), None, _D("3.30"), _D("4.40")], pa.decimal128(12, 2)),
        }
    )
    plan = s.make_plan(
        {
            "P": base.plan.seed_envelope.per_table[0][1],
            "C": s.table_seed({"amt": s.passthrough()}, {("k", "j"): "ns_cg"}),
        }
    )
    shape = s.Shape(plan, base.graph, {"P": base.sources["P"], "C": child})
    for out in (s.run_full(shape).outputs["C"], s.run_seq(shape).outputs["C"]):
        assert out.schema.field("amt").type == pa.decimal128(12, 2)
        assert _same_cells(out.column("amt"), child.column("amt"))
        assert out.column_names == child.column_names


def test_u1_subset_run_keeps_untouched_types_for_the_kept_rows(tmp_path: Path) -> None:
    n = 200
    typed = {c: v for c, v in _typed_columns(n).items() if c in _U7_TYPES}
    source = pa.table(
        {"id": pa.array(range(n), pa.int64()), "h": s.strs([f"v{i}" for i in range(n)]), **typed}
    )
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg([pass_col("id"), hash_col("h"), *[pass_col(c) for c in typed]], path=path)
    cfg["subset"] = {
        "seeds": [{"table": TABLE, "mode": "sample", "key_columns": ["id"], "count": 20}]
    }
    out = run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        auto_chunk=False,
    ).outputs[TABLE]
    assert out.num_rows == 20
    kept = _o3(source.take(pa.array(out.column("id").to_pylist(), pa.int64())))
    for name in typed:
        assert out.schema.field(name).type == kept.schema.field(name).type, name
        assert _same_cells(out.column(name), kept.column(name)), name


def test_u7_chunked_route_matches_the_other_routes(tmp_path: Path) -> None:
    source = _u7_source(120_000)
    out = _u7_run(tmp_path, source, auto_chunk=True)
    assert out.num_rows == source.num_rows
    want = _o3(source)
    for name in _U7_TYPES:
        assert out.schema.field(name).type == want.schema.field(name).type, name
        assert _same_cells(out.column(name), want.column(name)), name


def test_u7_validator_forces_full_frame_with_the_same_types(tmp_path: Path) -> None:
    source = _u7_source(2_000)
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg([hash_col("h"), *[pass_col(c) for c in _U7_TYPES]], path=path)
    cfg["validators"] = [
        {"name": "regex_match", "params": {"pattern": ".*"}, "columns": {TABLE: ["h"]}}
    ]
    out = run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        auto_chunk=False,
    ).outputs[TABLE]
    want = _o3(source)
    for name in _U7_TYPES:
        assert out.schema.field(name).type == want.schema.field(name).type, name
        assert _same_cells(out.column(name), want.column(name)), name


# B1: a pandas-written source whose metadata describes a non-unit range index.


def _ranged_source(step: int, n: int = 12, key: str = "h") -> pa.Table:
    frame = pd.DataFrame(
        {
            "id": range(n * abs(step)),
            key: [f"v{i}" for i in range(n * abs(step))],
            "amt": [_D(f"{i}.50") for i in range(n * abs(step))],
        }
    )
    return pa.Table.from_pandas(frame.iloc[::step])


@pytest.mark.parametrize("step", [2, -1], ids=["step2", "step-1"])
@pytest.mark.parametrize("unified", [False, True], ids=["full_frame", "unified"])
def test_b1_ranged_index_source_runs_on_full_frame_and_unified(
    tmp_path: Path, step: int, unified: bool
) -> None:
    source = _ranged_source(step)
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg([pass_col("id"), hash_col("h"), pass_col("amt")], path=path)
    out = run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        auto_chunk=False,
        unified_slice_enabled=unified,
    ).outputs[TABLE]
    assert out.num_rows == source.num_rows
    assert out.column("id").to_pylist() == source.column("id").to_pylist()
    assert out.schema.field("amt").type == source.schema.field("amt").type


@pytest.mark.parametrize("step", [2, -1], ids=["step2", "step-1"])
def test_b1_ranged_index_source_runs_on_the_sequential_route(step: int) -> None:
    child = _ranged_source(step, key="k")
    keys = child.column("k").to_pylist()
    plan = s.make_plan(
        {
            "A": s.table_seed({"k": s.hashed("ns_k")}),
            "B": s.table_seed({"k": s.hashed("ns_k"), "amt": s.passthrough()}),
        }
    )
    graph = s.graph(s.edge("A", "k", "B", "k", "ns_k", OrphanPolicy.PRESERVE))
    shape = s.Shape(
        plan,
        graph,
        {
            "A": pa.table({"k": s.strs(keys)}),
            "B": child.select(["k", "amt"]),
        },
    )
    out = s.run_seq(shape).outputs["B"]
    assert out.num_rows == child.num_rows
    assert out.schema.field("amt").type == child.schema.field("amt").type


def test_b1_a_reordered_frame_is_refused_with_a_registered_code() -> None:
    source = _ranged_source(2)
    frame = source.to_pandas().iloc[::-1]
    with pytest.raises(ExecutionError) as info:
        table_from_pandas_keeping_source_types(frame, source, {"id", "amt"})
    assert info.value.code == "output_assembly_rows_changed"
    with pytest.raises(ExecutionError) as info:
        table_from_pandas_keeping_source_types(source.to_pandas().iloc[:-1], source, {"id"})
    assert info.value.code == "output_assembly_rows_changed"
    with pytest.raises(ExecutionError) as info:
        table_from_pandas_keeping_source_types(
            source.to_pandas()[["h", "id", "amt"]], source, set()
        )
    assert info.value.code == "output_assembly_columns_mismatch"


# V1-2: carried columns keep the pandas dtype their source metadata names.


def _dtype_source(n: int = 6, key: str = "h") -> pa.Table:
    frame = pd.DataFrame(
        {
            key: [f"v{i}" for i in range(n)],
            "i": pd.array([1, None, 3, 4, None, 6][:n], dtype="Int64"),
            "t": pd.array(["a", None, "c", "d", "e", "f"][:n], dtype="string"),
        }
    )
    return pa.Table.from_pandas(frame, preserve_index=False)


def _assert_pandas_dtypes(out: pa.Table) -> None:
    dtypes = out.to_pandas().dtypes
    assert str(dtypes["i"]) == "Int64"
    assert str(dtypes["t"]) == "string"


@pytest.mark.parametrize("unified", [False, True], ids=["full_frame", "unified"])
def test_v12_carried_columns_keep_their_pandas_dtype(tmp_path: Path, unified: bool) -> None:
    source = _dtype_source()
    path = write_source(source, tmp_path / "t.parquet")
    cfg = make_cfg([hash_col("h"), pass_col("i"), pass_col("t")], path=path)
    out = run_pipeline(
        cfg,
        sources={TABLE: source},
        engine_version="uf-domain-s1",
        key_provider=key_provider(),
        auto_chunk=False,
        unified_slice_enabled=unified,
    ).outputs[TABLE]
    _assert_pandas_dtypes(out)


def test_v12_carried_columns_keep_their_pandas_dtype_sequential() -> None:
    child = _dtype_source(key="k")
    keys = child.column("k").to_pylist()
    plan = s.make_plan(
        {
            "A": s.table_seed({"k": s.hashed("ns_k")}),
            "B": s.table_seed({"k": s.hashed("ns_k"), "i": s.passthrough(), "t": s.passthrough()}),
        }
    )
    graph = s.graph(s.edge("A", "k", "B", "k", "ns_k", OrphanPolicy.PRESERVE))
    shape = s.Shape(
        plan,
        graph,
        {"A": pa.table({"k": s.strs(keys)}), "B": child},
    )
    _assert_pandas_dtypes(s.run_seq(shape).outputs["B"])


# D2: the passthrough rule is read in one place.


def test_d2_passthrough_and_untouched_agree_when_the_handler_changes_the_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.execution._chunked_carry import passthrough_columns, untouched_columns
    from decoy_engine.execution._runner import build_work_list
    from decoy_engine.execution._strategies import SCALAR_HANDLERS
    from decoy_engine.execution._strategies._passthrough import PassthroughHandler
    from tests.native.test_column_access_surfaces import REG, _compile

    class _Changes(PassthroughHandler):
        output_is_input = False

    columns = [{"name": "p", "strategy": "passthrough"}, {"name": "r", "strategy": "redact"}]
    data = {"p": pa.array(["a", "b"]), "r": pa.array(["x", "y"])}
    plan = _compile(columns, data)
    nodes = [n for n in build_work_list(plan, REG) if n.table == "t"]
    cfg = {"tables": [{"name": "t", "columns": columns}]}
    names = ["p", "r"]
    honest = (
        set(passthrough_columns(cfg, table="t", names=names, registry=REG)),
        set(untouched_columns(nodes, names, REG)),
    )
    assert honest == ({"p"}, {"p"})
    monkeypatch.setitem(SCALAR_HANDLERS, "passthrough", _Changes())
    changed = (
        set(passthrough_columns(cfg, table="t", names=names, registry=REG)),
        set(untouched_columns(nodes, names, REG)),
    )
    assert changed == (set(), set())
