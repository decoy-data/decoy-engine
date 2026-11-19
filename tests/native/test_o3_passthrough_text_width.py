"""O3 acceptance (AT-O3a, b, d, e, f): pass-through text narrows or promotes by one width state.

A pass-through `large_string` column leaves every route as `string` while its values fit 32-bit
offsets. The decision is made per batch from the offsets (no source pre-scan). One value that
cannot fit promotes the column to `large_string` for the rest of the run and widens the earlier
chunks without rereading the source. Tests shrink the limit with `_OFFSET_LIMIT`; the byte
sizes below are small on purpose.
"""

from __future__ import annotations

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

from decoy_engine import _arrow_types, run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.execution import _chunked
from decoy_engine.execution._pipeline_auto_chunk import join_dispatcher_chunks
from decoy_engine.execution.native import _chunked_entry
from decoy_engine.execution.out_of_core import _mask
from decoy_engine.execution.out_of_core._batch_join import _resolve_output_types
from decoy_engine.execution.out_of_core._mask import masked_output_type
from decoy_engine.kernel import passthrough_array
from decoy_engine.relationships._graph import OrphanPolicy
from tests._declared_schema import chunked_entry_kwargs
from tests.native._chunked_categorical_support import cat_col, make_config, passthrough
from tests.native._chunked_entry_support import (
    ENGINE_VERSION,
    TABLE,
    column_values,
    key_provider,
    split,
)
from tests.native.test_chunked_entry_values_schema import _full_frame
from tests.parity import _d2b_shapes as s
from tests.parity import _dcomp_ooc_shapes as o

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
    calls = _spy(monkeypatch, _chunked_entry, "normalize_chunk")
    got = _run("run_mask_chunked", split(_source(KEEP), 2))
    assert calls
    assert {t.schema.field("keep").type for t in got} == {pa.string()}
    assert column_values(got, "keep") == KEEP


def test_o3a_run_mask_pipeline_chunked_writes_string() -> None:
    got = _run("run_mask_pipeline_chunked", split(_source(KEEP), 2))
    assert {t.schema.field("keep").type for t in got} == {pa.string()}
    assert column_values(got, "keep") == KEEP


def test_o3a_whole_frame_writes_string(tmp_path: Path) -> None:
    out = _full_frame(CFG, _source(KEEP), tmp_path)
    assert out.schema.field("keep").type == pa.string()
    assert out.column("keep").to_pylist() == KEEP


@pytest.mark.parametrize("mode", ["resident", "sink-batch"])
def test_o3a_out_of_core_writes_string(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch, _mask, "passthrough_array")
    run = o.run_ooc(o.large_string_component_shape(OrphanPolicy.PRESERVE), mode, tmp_path=tmp_path)
    assert calls
    assert run.outputs["P"].schema.field("n").type == pa.string()


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
    from decoy_engine.kernel import passthrough_array

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
        out = passthrough_array(pa.chunked_array([chunk, chunk]), _arrow_types.TextWidthState())
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
    out = passthrough_array(pa.chunked_array([chunk, chunk]), state)
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


def test_o3f_resident_collectors_widen_the_earlier_chunk(small_limit: None) -> None:
    table = _source(WIDE)
    got = _run("run_mask_chunked", [table.slice(0, 3), table.slice(3)])
    for joined in (
        _chunked.concat_masked_chunks(got, table=TABLE),
        join_dispatcher_chunks(got, table=TABLE),
    ):
        assert joined.schema.field("keep").type == pa.large_string()
        assert joined.column("keep").to_pylist() == WIDE


def test_o3f_state_is_monotonic_and_aligns_analytic_and_fk_types(small_limit: None) -> None:
    state = _arrow_types.TextWidthState()
    first = state.observe(pa.array(["ab", "cd"], pa.large_string()))
    assert [p.type for p in first] == [pa.string()] and not state.wide
    (wide,) = state.observe(pa.array(["ghijklmnop"], pa.large_string()))
    assert wide.type == pa.large_string() and state.wide
    (after,) = state.observe(pa.array(["ab"], pa.large_string()))
    assert after.type == pa.large_string()  # never narrows again
    seed: Any = SimpleNamespace(strategy="passthrough", provider_config={}, namespace=None)
    assert masked_output_type(seed, pa.large_string(), state) == pa.large_string()
    assert masked_output_type(seed, pa.large_string(), _arrow_types.TextWidthState()) == pa.string()
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


def test_o3f_parquet_still_refuses_one_2gib_value(tmp_path: Path) -> None:
    """Parquet cannot store the value on origin/main or here; O3 adds no earlier refusal."""
    size = 2**31
    path = tmp_path / "sparse.bin"
    with path.open("wb") as fh:
        fh.truncate(size)
    buf = pa.memory_map(str(path)).read_buffer(size)
    offsets = pa.py_buffer(b"".join(v.to_bytes(8, "little") for v in (0, size)))
    big = pa.Array.from_buffers(pa.large_string(), 1, [None, offsets, buf])
    with pytest.raises(pa.ArrowInvalid, match="Parquet cannot store strings with size 2GB"):
        pq.write_table(pa.table({"keep": big}), str(tmp_path / "out.parquet"))
