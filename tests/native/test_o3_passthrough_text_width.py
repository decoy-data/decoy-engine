"""O3 acceptance (AT-O3a, b, d, e, f): pass-through text narrows or promotes by one width state.

A pass-through `large_string` column leaves every route as `string` while its values fit 32-bit
offsets. The decision is made per batch from the offsets (no source pre-scan). One value that
cannot fit promotes the column to `large_string` for the rest of the run and widens the earlier
chunks without rereading the source. Tests shrink the limit with `_OFFSET_LIMIT`; the byte
sizes below are small on purpose.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import _arrow_types, reasons, run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.execution import ParquetTransactionalSink, run_pipeline
from decoy_engine.execution import _chunked_output_sink as sink_mod
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._pipeline_auto_chunk import join_dispatcher_chunks
from decoy_engine.execution.native import _chunked_entry
from decoy_engine.execution.native.chunked import _oracle_route
from decoy_engine.execution.out_of_core import _mask
from decoy_engine.execution.out_of_core._batch_join import _resolve_output_types
from decoy_engine.execution.out_of_core._mask import masked_output_type
from decoy_engine.fileaccess._types import FileAccessReadError
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.profile._readers import LazySource
from decoy_engine.relationships._graph import OrphanPolicy
from tests._declared_schema import chunked_entry_kwargs, declare_rest
from tests.native._chunked_categorical_support import cat_col, make_config, passthrough
from tests.native._chunked_entry_support import (
    ENGINE_VERSION,
    TABLE,
    column_values,
    key_provider,
    split,
)
from tests.parity import _d2b_shapes as s
from tests.parity import _dcomp_ooc_shapes as o
from tests.unit.execution import _r3_scenarios as r3

# Every route in plan 5.3 has a cell below. There is no route registry, so a new route must add
# itself here (known limit, docs/frozen-surfaces.md route-list row).
ENTRIES = {
    "run_mask_chunked": run_mask_chunked,
    "run_mask_pipeline_chunked": run_mask_pipeline_chunked,
}
CFG = make_config([cat_col(mode=None), passthrough("keep")])
KEEP = ["A", "B", None, "D", "E", "F"]


def _source(values: list[str | None]) -> pa.Table:
    return pa.table(
        {
            "c": pa.array(["a", "b", "a", "c", "b", "a"][: len(values)], pa.string()),
            "keep": pa.array(values, pa.large_string()),
        }
    )


def _run(entry: str, chunks: Any) -> list[pa.Table]:
    run = ENTRIES[entry]
    return list(
        run(
            CFG,
            chunks,
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            **chunked_entry_kwargs(run, CFG, TABLE),
        )
    )


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> list[int]:
    """Count calls of `module.name`, a route-owned function the cell expects to run."""
    calls: list[int] = []
    real = getattr(module, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


@pytest.fixture
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 4)


# AT-O3a: one cell per route, each with a witness that the route's own code ran.


def test_o3a_run_mask_chunked_writes_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_mask_chunked normalizes on whichever route the table takes: the native leg in
    # _chunked_entry, or the oracle leg in _oracle_route (no companion installed).
    native_calls = _spy(monkeypatch, _chunked_entry, "normalize_chunk")
    oracle_calls = _spy(monkeypatch, _oracle_route, "normalize_chunk")
    got = _run("run_mask_chunked", split(_source(KEEP), 2))
    assert native_calls or oracle_calls
    assert {t.schema.field("keep").type for t in got} == {pa.string()}
    assert column_values(got, "keep") == KEEP


def test_o3a_run_mask_pipeline_chunked_writes_string() -> None:
    got = _run("run_mask_pipeline_chunked", split(_source(KEEP), 2))
    assert {t.schema.field("keep").type for t in got} == {pa.string()}
    assert column_values(got, "keep") == KEEP


def _pipeline(tmp_path: Path, source: pa.Table, **kwargs: Any) -> Any:
    path = str(tmp_path / "source.parquet")
    pq.write_table(source, path)
    config = copy.deepcopy(CFG)
    config["sources"][TABLE] = {"type": "file", "format": "parquet", "path": path}
    config["targets"][TABLE] = {"type": "file", "format": "parquet", "path": path + ".out"}
    declare_rest(config, {TABLE: source})
    return run_pipeline(
        config,
        {TABLE: source},
        engine_version=ENGINE_VERSION,
        auto_chunk=False,
        key_provider=key_provider(),
        use_byte_estimate_routing=False,
        use_probe_routing=False,
        **kwargs,
    )


def test_o3a_whole_frame_writes_string(tmp_path: Path) -> None:
    got = _pipeline(
        tmp_path, _source(KEEP), execution_mode="full_frame", unified_slice_enabled=False
    )
    out = got.outputs[TABLE]
    assert "unified_slice_activation" not in got.quality_metrics
    assert out.schema.field("keep").type == pa.string()
    assert out.column("keep").to_pylist() == KEEP


def _large_text(table: pa.Table) -> pa.Table:
    return pa.table(
        {
            n: table.column(n).cast(pa.large_string())
            if pa.types.is_string(table.schema.field(n).type)
            else table.column(n)
            for n in table.column_names
        }
    )


def _no_large_text(outputs: dict[str, pa.Table]) -> None:
    for name, table in outputs.items():
        assert all(not pa.types.is_large_string(f.type) for f in table.schema), name


def test_o3a_unified_slice_declines_large_string_and_writes_string(tmp_path: Path) -> None:
    """The slice admits `string` sources only, so a `large_string` source takes the pandas
    fallback; the control run shows the slice is otherwise live for this shape."""
    cfg, table = r3.single_table(tmp_path, hash_column=False)
    control = r3._go(cfg, {"t": table}, key_provider=r3.key_provider())
    assert "unified_slice_activation" in control.quality_metrics
    got = r3._go(cfg, {"t": _large_text(table)}, key_provider=r3.key_provider())
    assert "unified_slice_activation" not in got.quality_metrics
    assert got.outputs["t"].schema.field("p").type == pa.string()
    assert got.outputs["t"].column("p").to_pylist() == table.column("p").to_pylist()


def test_o3a_sequential_writes_string(tmp_path: Path) -> None:
    cfg, tables = r3.fk_job(tmp_path)
    want = r3._go(cfg, tables, execution_mode="sequential", **r3._ROW_ROUTING)
    got = r3._go(
        cfg,
        {n: _large_text(t) for n, t in tables.items()},
        execution_mode="sequential",
        **r3._ROW_ROUTING,
    )
    assert got.quality_metrics["execution"]["execution_mode"] == "sequential"
    _no_large_text(got.outputs)
    for name, table in want.outputs.items():
        assert got.outputs[name].to_pydict() == table.to_pydict()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("resident", pa.string()), ("sink-batch", pa.large_string())],
)
def test_o3a_out_of_core_writes_string_but_a_fixed_schema_sink_keeps_large_string(
    mode: str, expected: pa.DataType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Parquet sink fixes its schema before batch one, so it keeps main's field (plan 3.3)."""
    calls = _spy(monkeypatch, _mask, "narrow_passthrough")
    run = o.run_ooc(o.large_string_component_shape(OrphanPolicy.PRESERVE), mode, tmp_path=tmp_path)
    assert calls
    assert run.outputs["P"].schema.field("n").type == expected


def _fits_each_not_together() -> s.Shape:
    """Rows of 5 bytes each: one row fits a limit of 8, three rows (15 bytes) do not."""
    return o.component_shape(
        OrphanPolicy.PRESERVE,
        pa.large_string(),
        parent_n=["aaaaa", "bbbbb", "ccccc"],
        child_k=["a", "b", "c"],
        child_n=["aaaaa", "bbbbb", "bbbbb"],
    )


@pytest.mark.parametrize("mode", ["sink-batch", "sink-reorder"])
def test_o3a_fixed_schema_sink_file_is_byte_equal_when_aggregate_text_is_wide(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sink that fixes `large_string` keeps the source batches: one row group, same bytes."""
    shape = _fits_each_not_together()
    o.run_ooc(shape, mode, tmp_path=tmp_path / "base", batch_rows=10)
    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 8)
    o.run_ooc(shape, mode, tmp_path=tmp_path / "narrow", batch_rows=10)
    for table in ("P", "C"):
        base = o._published(tmp_path / "base" / "out", table)
        got = o._published(tmp_path / "narrow" / "out", table)
        assert pq.ParquetFile(got).metadata.num_row_groups == 1
        assert pq.ParquetFile(got).schema_arrow == pq.ParquetFile(base).schema_arrow
        assert got.read_bytes() == base.read_bytes()


def test_o3a_streamed_chunked_sink_keeps_the_large_string_field() -> None:
    chunks = [
        pa.table({"keep": pa.array(["ab", None], pa.string())}),
        pa.table({"keep": pa.array(["cd"], pa.string())}),
    ]
    seen: list[pa.Table] = []

    class _Sink:
        def write_batches(self, table: str, batches: Any, *, schema: pa.Schema) -> None:
            seen.append(pa.Table.from_batches(list(batches), schema=schema))

    widened = _arrow_types.widen_text_columns(chunks, frozenset({"keep"}))
    sink_mod.stream_table(_Sink(), "t", widened, fixed_columns=frozenset({"keep"}))  # type: ignore[arg-type]
    assert seen[0].schema.field("keep").type == pa.large_string()
    assert seen[0].column("keep").to_pylist() == ["ab", None, "cd"]


def test_o3a_streamed_chunked_parquet_sink_file_keeps_large_string(tmp_path: Path) -> None:
    cfg, table = r3.single_table(tmp_path, hash_column=False)
    out = tmp_path / "sink_out"
    got = r3._go(
        cfg,
        {"t": _large_text(table)},
        sink=ParquetTransactionalSink(out),
        key_provider=r3.key_provider(),
        auto_chunk=True,
        chunk_size_rows=7,
        auto_chunk_threshold_rows=1,
    )
    assert got.quality_metrics["auto_chunk"]["mode"] != "full_frame"
    written = pq.read_table(out / "t.parquet")
    assert written.schema.field("p").type == pa.large_string()
    assert written.column("p").to_pylist() == table.column("p").to_pylist()


# AT-O3b: an FK key passed through as large_string joins the same rows as the oracle.


@pytest.mark.parametrize("policy", [OrphanPolicy.PRESERVE, OrphanPolicy.REMAP])
def test_o3b_fk_key_large_string_joins_the_same_rows(policy: OrphanPolicy) -> None:
    shape = o.large_string_component_shape(policy)
    oracle, run = s.run_full(shape), o.run_ooc(shape)
    for table in ("P", "C"):
        for name in oracle.outputs[table].column_names:
            want = oracle.outputs[table].column(name).to_pylist()
            assert run.outputs[table].column(name).to_pylist() == want, (table, name)
        assert run.outputs[table].schema.field("n").type == pa.string()


# AT-O3d: the width decision reads offsets only and never combines chunks.

_TRIPWIRE = textwrap.dedent(
    """
    import ctypes, mmap, sys
    import numpy as np
    import pyarrow as pa
    from decoy_engine import _arrow_types

    page = mmap.PAGESIZE
    region = mmap.mmap(-1, page)
    addr = ctypes.addressof(ctypes.c_char.from_buffer(region))
    # PROT_NONE: any read of the payload kills the process with SIGSEGV.
    assert ctypes.CDLL(None).mprotect(ctypes.c_void_p(addr), page, 0) == 0
    values = pa.foreign_buffer(addr, page, base=region)
    offsets = np.array([0, 8, 16, 24, 32], dtype=np.int64)
    chunk = pa.Array.from_buffers(pa.large_string(), 4, [None, pa.py_buffer(offsets), values])
    _arrow_types._OFFSET_LIMIT = 16
    if sys.argv[1] == "control":
        chunk.to_pylist()  # must crash: proves the tripwire bites
    else:
        out = _arrow_types.TextWidthState().observe_column(pa.chunked_array([chunk, chunk]))
        assert out.type == pa.string() and out.num_chunks == 4 and len(out) == 8
    print("OK")
    """
)


def _tripwire(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _TRIPWIRE, mode], capture_output=True, text=True, timeout=120
    )


def test_o3d_payload_is_never_read_or_combined() -> None:
    done = _tripwire("narrow")
    assert done.returncode == 0 and done.stdout.strip() == "OK", done.stderr[-400:]


def test_o3d_tripwire_control_crashes_on_a_payload_read() -> None:
    assert _tripwire("control").returncode != 0


def test_o3d_out_of_core_passthrough_uses_the_state(small_limit: None) -> None:
    state = _arrow_types.TextWidthState()
    chunk = pa.array(["ab", "cd", "ef"], pa.large_string())
    out = state.observe_column(pa.chunked_array([chunk, chunk]))
    assert out.num_chunks == 4 and out.type == pa.string() and not state.wide
    assert out.to_pylist() == ["ab", "cd", "ef"] * 2


# AT-O3e: split-then-narrow over one-shot sources, on every route.


def _one_shot(chunks: list[pa.Table], consumed: list[int]) -> Iterator[pa.Table]:
    for chunk in chunks:
        consumed.append(chunk.num_rows)
        yield chunk


@pytest.mark.parametrize("entry", ["run_mask_chunked", "run_mask_pipeline_chunked"])
def test_o3e_oversized_chunk_with_fitting_rows_splits_and_succeeds(
    entry: str, small_limit: None
) -> None:
    values = ["abcd", "efgh", "ijkl", None, "mnop", "q"]  # 21 bytes against a 4-byte limit
    consumed: list[int] = []
    got = _run(entry, _one_shot(split(_source(values), 3), consumed))
    assert consumed == [3, 3]  # the one-shot iterator is read once, never replayed
    assert {t.schema.field("keep").type for t in got} == {pa.string()}
    assert column_values(got, "keep") == values


def test_o3e_the_source_is_not_pre_scanned(small_limit: None) -> None:
    """The first chunk is produced before the second is read: no pass over the source decides
    the width up front."""
    consumed: list[int] = []
    run = run_mask_chunked(
        CFG,
        _one_shot(split(_source(["abcd", "efgh", "ijkl", "mnop"]), 2), consumed),
        table=TABLE,
        engine_version=ENGINE_VERSION,
        key_provider=key_provider(),
    )
    next(iter(run))
    assert consumed == [2]


def test_o3e_ooc_batch_over_the_limit_is_split_by_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 1)
    shape = o.large_string_component_shape(OrphanPolicy.PRESERVE)
    oracle, run = s.run_full(shape), o.run_ooc(shape, batch_rows=10)
    assert run.outputs["P"].schema.field("n").type == pa.string()
    for table in ("P", "C"):
        want = oracle.outputs[table].column("n").to_pylist()
        assert run.outputs[table].column("n").to_pylist() == want


def test_o3e_split_is_ordered_and_offset_only(small_limit: None) -> None:
    arr = pa.array(["abcd", "efgh", None, "ij", "k"], pa.large_string())
    parts = _arrow_types.split_narrow_text(arr)
    assert parts is not None and len(parts) == 3
    assert {p.type for p in parts} == {pa.string()}
    assert [v for p in parts for v in p.to_pylist()] == arr.to_pylist()
    assert _arrow_types.split_narrow_text(pa.array(["abcdefgh"], pa.large_string())) is None
    batch = pa.record_batch({"a": arr, "b": pa.array(range(5))})
    assert [b.num_rows for b in _arrow_types.split_wide_batch(batch)] == [1, 2, 2]


# AT-O3f: a later unsplittable value promotes; CSV and resident output keep it.

WIDE = ["ab", None, "cd", "ef", "ghijklmnop"]  # the last value (10 bytes) cannot fit 4


def test_o3f_later_wide_value_promotes_without_replay(small_limit: None) -> None:
    consumed: list[int] = []
    table = _source(WIDE)
    got = _run("run_mask_chunked", _one_shot([table.slice(0, 3), table.slice(3)], consumed))
    assert consumed == [3, 2]
    assert [t.schema.field("keep").type for t in got] == [pa.string(), pa.large_string()]
    csv = "".join(t.select(["keep"]).to_pandas().to_csv(index=False) for t in got)
    assert csv.splitlines()[-1] == "ghijklmnop"  # CSV has no field width: the value is kept
    assert column_values(got, "keep") == WIDE


def test_o3f_resident_collector_widens_the_earlier_chunk(
    small_limit: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    table = _source(WIDE)
    got = _run("run_mask_chunked", [table.slice(0, 3), table.slice(3)])
    joined = join_dispatcher_chunks(got, table=TABLE, text_columns=frozenset({"keep"}))
    assert joined.schema.field("keep").type == pa.large_string()
    assert joined.column("keep").to_pylist() == WIDE
    # The same through the auto-chunk run: `x0`..`x9` fit two bytes, `x10` promotes the column.
    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 2)
    cfg, source = r3.single_table(tmp_path, hash_column=False)
    run = r3._go(
        cfg,
        {"t": _large_text(source)},
        key_provider=r3.key_provider(),
        auto_chunk=True,
        chunk_size_rows=5,
        auto_chunk_threshold_rows=1,
    )
    assert run.quality_metrics["auto_chunk"]["mode"] != "full_frame"
    assert run.outputs["t"].schema.field("p").type == pa.large_string()
    assert run.outputs["t"].column("p").to_pylist() == source.column("p").to_pylist()


def test_o3f_state_is_monotonic_and_aligns_analytic_and_fk_types(small_limit: None) -> None:
    state = _arrow_types.TextWidthState()
    first = state.observe(pa.array(["ab", "cd"], pa.large_string()))
    assert [p.type for p in first] == [pa.string()] and not state.wide
    (wide,) = state.observe(pa.array(["ghijklmnop"], pa.large_string()))
    assert wide.type == pa.large_string() and state.wide
    (after,) = state.observe(pa.array(["ab"], pa.large_string()))
    assert after.type == pa.large_string()  # never narrows again
    seed: Any = SimpleNamespace(strategy="passthrough", provider_config={}, namespace=None)
    # The analytic type fixes a Parquet sink's field before batch one: the source type, as on main.
    assert masked_output_type(seed, pa.large_string()) == pa.large_string()
    edge: Any = SimpleNamespace(orphan_policy=OrphanPolicy.PRESERVE, child_columns=("k",))
    kwargs: dict[str, Any] = {
        "edge": edge,
        "masked_types": (pa.large_string(),),
        "child_key_types": (pa.large_string(),),
        "remap_seeds": None,
    }
    assert _resolve_output_types(**kwargs, text_widths=(state,)) == (pa.large_string(),)
    assert _resolve_output_types(**kwargs, text_widths=(_arrow_types.TextWidthState(),)) == (
        pa.string(),
    )


@pytest.mark.parametrize("policy", [OrphanPolicy.PRESERVE, OrphanPolicy.REMAP])
def test_o3b_promoted_parent_state_reaches_the_out_of_core_joiner(
    policy: OrphanPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One-row batches: `x` narrows, `yyy` cannot, so the parent column promotes mid-run and the
    joiner resolves its key type from that same state."""
    from decoy_engine.execution.out_of_core import _batch_join

    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 2)
    seen: list[tuple[Any, ...]] = []
    real = _batch_join._resolve_output_types
    monkeypatch.setattr(
        _batch_join,
        "_resolve_output_types",
        lambda **kw: (seen.append(kw["text_widths"]), real(**kw))[1],
    )
    shape = o.component_shape(
        policy, pa.large_string(), parent_n=["x", "yyy"], child_k=["a", "q"], child_n=["x", "yyy"]
    )
    oracle, run = s.run_full(shape), o.run_ooc(shape, batch_rows=1)
    for table in ("P", "C"):
        got, want = run.outputs[table].column("n"), oracle.outputs[table].column("n")
        assert got.to_pylist() == want.to_pylist()
    assert run.outputs["P"].schema.field("n").type == pa.large_string()
    assert any(st is not None and st.wide for states in seen for st in states)


def _sparse_2gib_table(tmp_path: Path) -> pa.Table:
    size = 2**31
    path = tmp_path / "sparse.bin"
    with path.open("wb") as fh:
        fh.truncate(size)
    buf = pa.memory_map(str(path)).read_buffer(size)
    offsets = pa.py_buffer(b"".join(v.to_bytes(8, "little") for v in (0, size)))
    return pa.table({"keep": pa.Array.from_buffers(pa.large_string(), 1, [None, offsets, buf])})


class _Stage:
    """The two things `arrow_adapter.write_table` reads from a stage, for either policy."""

    display = "target"

    def __init__(self, root: Path, *, strict: bool) -> None:
        self.root, self.strict = root, strict

    def create_file(self, component: str) -> int:
        return os.open(self.root / component, os.O_WRONLY | os.O_CREAT | os.O_EXCL)


def test_o3f_parquet_local_writer_still_refuses_one_2gib_value(tmp_path: Path) -> None:
    """Same on origin/main and here: O3 adds no earlier refusal."""
    stage: Any = _Stage(tmp_path, strict=False)
    with pytest.raises(pa.ArrowInvalid, match="Parquet cannot store strings with size 2GB"):
        arrow_adapter.write_table(_sparse_2gib_table(tmp_path), stage, "out.parquet")


def test_o3f_parquet_strict_writer_still_raises_file_access_read_error(tmp_path: Path) -> None:
    stage: Any = _Stage(tmp_path, strict=True)
    with pytest.raises(FileAccessReadError, match="file could not be read: target"):
        arrow_adapter.write_table(_sparse_2gib_table(tmp_path), stage, "out.parquet")


def test_o3e_pandas_routes_succeed_under_a_small_limit(small_limit: None, tmp_path: Path) -> None:
    values = ["abcd", "efgh", "ijkl", None, "mnop", "q"]
    got = _pipeline(
        tmp_path, _source(values), execution_mode="full_frame", unified_slice_enabled=False
    )
    assert got.outputs[TABLE].schema.field("keep").type == pa.string()
    assert got.outputs[TABLE].column("keep").to_pylist() == values
    cfg, tables = r3.fk_job(tmp_path)
    seq = r3._go(
        cfg,
        {n: _large_text(t) for n, t in tables.items()},
        execution_mode="sequential",
        **r3._ROW_ROUTING,
    )
    _no_large_text(seq.outputs)


# AT-O3f: a promotion partway through one call, on every path that builds a column from parts.


def test_o3f_observe_column_recasts_earlier_parts_on_a_mid_call_promotion(
    small_limit: None,
) -> None:
    state = _arrow_types.TextWidthState()
    column = pa.chunked_array(
        [pa.array(["ab"], pa.large_string()), pa.array(["ghijklmnop"], pa.large_string())]
    )
    out = state.observe_column(column)
    assert state.wide
    assert out.type == pa.large_string()
    assert {c.type for c in out.chunks} == {pa.large_string()}
    assert out.to_pylist() == ["ab", "ghijklmnop"]
    narrow = _arrow_types.TextWidthState().observe_column(
        pa.chunked_array([pa.array(["ab", None], pa.large_string())])
    )
    assert narrow.type == pa.string() and narrow.to_pylist() == ["ab", None]
    ints = _arrow_types.TextWidthState().observe_column(pa.chunked_array([pa.array([1, 2])]))
    assert ints.type == pa.int64()


def test_o3f_run_mask_chunked_multi_chunk_column_promotes_mid_call(small_limit: None) -> None:
    keep = pa.chunked_array(
        [pa.array(["ab", "cd"], pa.large_string()), pa.array(["ghijklmnop"], pa.large_string())]
    )
    cats = pa.chunked_array([pa.array(["a", "b"]), pa.array(["a"])])
    got = _run("run_mask_chunked", [pa.table({"c": cats, "keep": keep})])
    assert [t.schema.field("keep").type for t in got] == [pa.large_string()]
    assert column_values(got, "keep") == ["ab", "cd", "ghijklmnop"]


def test_o3f_auto_chunk_lazy_source_without_a_sink_promotes_mid_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The no-sink collector receives widened chunks, so a late promotion cannot disagree."""
    monkeypatch.setattr(_arrow_types, "_OFFSET_LIMIT", 2)
    cfg, source = r3.single_table(tmp_path, hash_column=False)
    path = tmp_path / "large.parquet"
    pq.write_table(_large_text(source), path)
    cfg["sources"]["t"]["path"] = str(path)
    run = r3._go(
        cfg,
        {"t": LazySource(path)},
        key_provider=r3.key_provider(),
        auto_chunk=True,
        chunk_size_rows=5,
        auto_chunk_threshold_rows=1,
    )
    assert run.outputs["t"].schema.field("p").type == pa.large_string()
    assert run.outputs["t"].column("p").to_pylist() == source.column("p").to_pylist()


def test_o3f_auto_chunk_lazy_source_without_a_sink_narrows_when_nothing_promotes(
    tmp_path: Path,
) -> None:
    cfg, source = r3.single_table(tmp_path, hash_column=False)
    path = tmp_path / "large.parquet"
    pq.write_table(_large_text(source), path)
    cfg["sources"]["t"]["path"] = str(path)
    run = r3._go(
        cfg,
        {"t": LazySource(path)},
        key_provider=r3.key_provider(),
        auto_chunk=True,
        chunk_size_rows=5,
        auto_chunk_threshold_rows=1,
    )
    assert run.outputs["t"].schema.field("p").type == pa.string()
    assert run.outputs["t"].column("p").to_pylist() == source.column("p").to_pylist()


def test_o3f_join_widens_only_the_named_text_columns() -> None:
    a = pa.table({"keep": pa.array(["x"], pa.string()), "other": pa.array(["x"], pa.string())})
    b = pa.table(
        {"keep": pa.array(["y"], pa.large_string()), "other": pa.array(["y"], pa.large_string())}
    )
    with pytest.raises(ExecutionError) as err:
        join_dispatcher_chunks([a, b], table=TABLE, text_columns=frozenset({"keep"}))
    assert err.value.code == reasons.runtime.CHUNKED_SCHEMA_MISMATCH
    assert "other" in str(err.value)
    with pytest.raises(ExecutionError):
        join_dispatcher_chunks([a, b], table=TABLE)


# AT-O3a/O3f: the out-of-core mask narrows a `large_string` column no strategy touches.


def _unmasked_batch(values: list[str | None]) -> pa.RecordBatch:
    return pa.record_batch(
        {"k": pa.array(["a"] * len(values), pa.string()), "u": pa.array(values, pa.large_string())}
    )


@pytest.mark.parametrize("seeded", [True, False])
def test_o3a_out_of_core_narrows_an_unconfigured_large_string_column(seeded: bool) -> None:
    plan = s.make_plan({"U": s.table_seed({"k": s.hashed("ns")})} if seeded else {})
    widths: dict[str, _arrow_types.TextWidthState] = {}
    out = _mask.mask_batch(plan, "U", _unmasked_batch(["ab", None, "cd"]), text_widths=widths)
    assert out.schema.field("u").type == pa.string()
    assert out.column("u").to_pylist() == ["ab", None, "cd"]
    assert not widths["u"].wide


@pytest.mark.parametrize("seeded", [True, False])
def test_o3f_out_of_core_unconfigured_column_promotes_across_batches(
    seeded: bool, small_limit: None
) -> None:
    plan = s.make_plan({"U": s.table_seed({"k": s.hashed("ns")})} if seeded else {})
    widths: dict[str, _arrow_types.TextWidthState] = {}
    first = _mask.mask_batch(plan, "U", _unmasked_batch(["ab"]), text_widths=widths)
    later = _mask.mask_batch(plan, "U", _unmasked_batch(["ghijklmnop"]), text_widths=widths)
    assert first.schema.field("u").type == pa.string()
    assert later.schema.field("u").type == pa.large_string()
    assert later.column("u").to_pylist() == ["ghijklmnop"]
    assert widths["u"].wide
