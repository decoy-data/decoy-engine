"""TB-1 (docs/plans/2026-07-12-track-b-completion-program.md): the governed
out-of-core path's input+output residency fixes.

Two defects this program's foundational sprint (TB-1) fixes, both in
`_isolated_worker.py`:

  1. `_load_sources` used to `pq.read_table` every manifest path eagerly,
     materializing a relationship-bearing job's whole input in the child
     BEFORE `run_pipeline` ever decided a route -- the root cause of the
     governed out-of-core path's measured ~2x memory overhead (docs plan's
     "two defects" section, #56).
  2. The worker never passed a sink, so a streaming route (out_of_core,
     sequential) still returned its output fully resident before the
     worker wrote it to disk via `pq.write_table` -- no different, memory-
     wise, than the full_frame route it was supposed to beat.

These tests exercise `_isolated_worker` directly (no subprocess spawn), so
they stay fast and deterministic; `test_isolated_run.py` already covers the
real-subprocess spawn/classify machinery this module does not touch.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution import _isolated_worker
from decoy_engine.execution._isolated_commit import stage_sources
from decoy_engine.execution._isolated_common import CAPPED_ENV
from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.io.bounded_reader import UnsupportedColumnType
from decoy_engine.profile._readers import LazySource
from tests.native._rev9_type_catalogue import CATALOGUE

_N = 30


def _hash_col(name: str, namespace: str) -> dict[str, Any]:
    return {"name": name, "strategy": "hash", "namespace": namespace}


def _write_source(tmp_path: Path, table: pa.Table, name: str) -> str:
    p = tmp_path / f"{name}.parquet"
    pq.write_table(table, p)
    return str(p)


def _fk_config(tmp_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """A small pure-mask FK job whose strategies the out-of-core compat gate
    admits -- mirrors `test_out_of_core_routing.py`'s `_fk_ooc_config`,
    duplicated locally per this test package's existing per-file convention
    (see `test_governor.py`'s module docstring)."""
    parent = pa.table({"id": pa.array([f"p{i}" for i in range(_N)], type=pa.string())})
    child = pa.table(
        {
            "cid": pa.array([f"c{i}" for i in range(_N)], type=pa.string()),
            "parent_id": pa.array([f"p{i}" for i in range(_N)], type=pa.string()),
        }
    )
    parent_path = _write_source(tmp_path, parent, "parent")
    child_path = _write_source(tmp_path, child, "child")
    config = {
        "version": 2,
        "global_settings": {"job_name": "tb1-worker-test", "seed": 7},
        "sources": {
            "parent": {"type": "file", "path": parent_path, "format": "parquet"},
            "child": {"type": "file", "path": child_path, "format": "parquet"},
        },
        "targets": {
            "parent": {
                "type": "file",
                "path": str(tmp_path / "parent.out.parquet"),
                "format": "parquet",
            },
            "child": {
                "type": "file",
                "path": str(tmp_path / "child.out.parquet"),
                "format": "parquet",
            },
        },
        "tables": [
            {"name": "parent", "columns": [_hash_col("id", "ns")]},
            {"name": "child", "columns": [_hash_col("cid", "cns"), _hash_col("parent_id", "ns")]},
        ],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["parent_id"]}],
                "orphan_policy": "preserve",
                "namespace": "ns",
            }
        ],
    }
    manifest = {
        name: {"path": path, "format": "parquet"}
        for name, path in (("parent", parent_path), ("child", child_path))
    }
    return config, manifest


class TestLoadSourcesLazyScope:
    """Fix #1's `lazy` scoping: relationship-bearing jobs get a `LazySource`;
    everything else keeps the pre-TB-1 eager load."""

    def test_lazy_true_wraps_lazy_source(self, tmp_path: Path) -> None:
        """FAILS pre-TB-1: `_load_sources` always called `pq.read_table`,
        returning a resident `pa.Table` regardless of any `lazy` intent."""
        path = tmp_path / "t.parquet"
        pq.write_table(pa.table({"a": [1, 2, 3]}), path)

        loaded = _isolated_worker._load_sources(
            {"t": {"path": str(path), "format": "parquet"}}, lazy=True
        )

        assert isinstance(loaded["t"], LazySource)
        # Cheap Parquet-footer metadata read only -- the whole point of
        # LazySource: no column data has been touched.
        assert loaded["t"].num_rows == 3

    def test_lazy_false_stays_eager(self, tmp_path: Path) -> None:
        """A non-relationship job keeps the pre-TB-1 eager load. Without this
        scoping, the S3 auto-chunk classifier (`_planner.
        _runtime_source_rejections`) would see a `LazySource` for a job that
        can never reach out-of-core anyway, and would conservatively decline
        the auto-chunk optimization it previously took -- reproduced during
        this sprint's own verification as a real memory-cap regression (a
        200k-row single-table mask job that used to auto-chunk into a
        bounded 50k-row pandas working set instead ran full-frame and
        crashed under a low rlimit cap)."""
        path = tmp_path / "t.parquet"
        pq.write_table(pa.table({"a": [1, 2, 3]}), path)

        loaded = _isolated_worker._load_sources(
            {"t": {"path": str(path), "format": "parquet"}}, lazy=False
        )

        assert isinstance(loaded["t"], pa.Table)
        assert loaded["t"].num_rows == 3


class TestIsolatedWorkerStreamsOutOfCore:
    def test_run_streams_input_and_output_for_out_of_core_route(self, tmp_path: Path) -> None:
        """End-to-end (no subprocess) proof of TB-1 fixes #1 + #2 together,
        exercising the real `_run` the isolated child process calls.

        FAILS pre-TB-1: the worker never passed a sink to `run_pipeline`, so
        `quality_metrics["execution"]["outputs_streamed"]` was always
        `False` for the out-of-core route -- the route reassembled its
        output fully resident in the child before `_stage_outputs` wrote it
        via `pq.write_table`, exactly the residency this sprint removes.
        """
        config, manifest = _fk_config(tmp_path)
        staging_output_dir = tmp_path / "staged"

        # Oracle: full_frame over the SAME resident sources, for byte parity.
        oracle_sources = {name: pq.read_table(entry["path"]) for name, entry in manifest.items()}
        oracle = run_pipeline(
            config, oracle_sources, engine_version="tb1-worker-test", execution_mode="full_frame"
        )

        payload = {
            "config": config,
            "sources": manifest,
            "kwargs": {"execution_mode": "out_of_core", "engine_version": "tb1-worker-test"},
            "mem_cap_bytes": None,
            "rlimit_kind": "data",
            "staging_output_dir": str(staging_output_dir),
        }

        envelope = _isolated_worker._run(payload)

        assert envelope["outcome"] == "completed"
        # The mechanism proof: outputs streamed straight to the sink's
        # target dir, never reassembled resident in this worker.
        assert envelope["quality_metrics"]["execution"]["outputs_streamed"] is True
        assert sorted(envelope["staged_tables"]) == ["child", "parent"]

        # Correctness: what actually landed on disk matches the full_frame
        # oracle byte-for-byte, in BOTH values and schema -- a value-only
        # comparison (`to_pydict()`) would miss a type divergence between
        # the streamed out_of_core sink's fixed schema and full_frame's
        # (e.g. a hash strategy emitting int64 on one route and string on
        # the other would still compare equal by `to_pydict()` if the
        # values happened to stringify the same).
        for table in ("parent", "child"):
            sunk = pq.read_table(staging_output_dir / f"{table}.parquet")
            oracle_table = oracle.outputs[table]
            assert sunk.schema == oracle_table.schema, (
                f"{table} sink schema diverges from the full_frame oracle: "
                f"{sunk.schema} vs {oracle_table.schema}"
            )
            assert sunk.to_pydict() == oracle_table.to_pydict(), f"{table} sink differs"

    def test_run_full_frame_route_unaffected_by_always_passed_sink(self, tmp_path: Path) -> None:
        """A non-relationship (full_frame-only) job must behave byte-for-byte
        as before: the sink `_run` now always constructs is never touched by
        that route (`_pipeline_route_exec`'s full_frame continuation never
        references `sink`), so outputs stay resident and are staged via the
        unchanged `_stage_outputs` path."""
        path = tmp_path / "t.parquet"
        pq.write_table(pa.table({"a": ["x", "y", "z"]}), path)
        config = {
            "version": 2,
            "global_settings": {"job_name": "tb1-full-frame", "seed": 1},
            "sources": {"t": {"type": "file", "path": str(path), "format": "parquet"}},
            "targets": {
                "t": {"type": "file", "path": str(tmp_path / "t.out.parquet"), "format": "parquet"}
            },
            "tables": [{"name": "t", "columns": [{"name": "a", "strategy": "redact"}]}],
        }
        staging_output_dir = tmp_path / "staged"
        payload = {
            "config": config,
            "sources": {"t": {"path": str(path), "format": "parquet"}},
            "kwargs": {"engine_version": "tb1-full-frame"},
            "mem_cap_bytes": None,
            "rlimit_kind": "data",
            "staging_output_dir": str(staging_output_dir),
        }

        envelope = _isolated_worker._run(payload)

        assert envelope["outcome"] == "completed"
        assert envelope["quality_metrics"]["execution"]["outputs_streamed"] is False
        assert envelope["staged_tables"] == ["t"]
        assert (staging_output_dir / "t.parquet").exists()


# Independent format expectations keep the all-Parquet and all-IPC mutations observable.
_IPC_TYPES = {
    "float16",
    "date64",
    "time32_s",
    "timestamp_s",
    "timestamp_s_tz",
    "string_view",
    "binary_view",
    "decimal32",
    "decimal64",
    "month_day_nano_interval",
    "fixed_size_list",
    "map",
    "list_view",
    "large_list_view",
    "sparse_union",
    "dense_union",
    "dictionary_string",
    "dictionary_binary",
    "dictionary_int",
    "dictionary_large_string",
    "dictionary_string_view",
    "dictionary_float16",
    "ree_string",
    "ree_int",
    "ree_float",
    "ree_string_view",
    "json",
    "uuid",
    "bool8",
    "fixed_shape_tensor",
    "opaque",
}
_FIXED = pa.list_(pa.int64(), 2)
_NESTED = {
    "struct_fixed": (pa.struct([("f", _FIXED)]), lambda v: {"f": v}),
    "list_fixed": (pa.list_(_FIXED), lambda v: [v]),
    "large_list_fixed": (pa.large_list(_FIXED), lambda v: [v]),
    "fixed_fixed": (pa.list_(_FIXED, 1), lambda v: [v]),
    "map_fixed": (pa.map_(pa.string(), _FIXED), lambda v: [("k", v)]),
}
_CASES = (
    [(name, null) for name in CATALOGUE for null in (False, True)]
    + [(name, pos) for name in _NESTED for pos in (0, 1)]
    + [("empty_struct", 0), ("nested_empty_struct", 0)]
)


@pytest.fixture(params=_CASES, ids=[f"{name}-{pos}" for name, pos in _CASES])
def staged_case(request, tmp_path):
    name, pos = request.param
    if name in CATALOGUE:
        array = CATALOGUE[name](pos)
    elif name in _NESTED:
        dtype, wrap = _NESTED[name]
        array = pa.array([wrap(None if i == pos else [i, i]) for i in range(3)], dtype)
    else:
        array = (
            pa.array([{}], pa.struct([]))
            if name == "empty_struct"
            else pa.array([{"g": {}}], pa.struct([("g", pa.struct([]))]))
        )
    table = pa.table({"x": array})
    manifest = stage_sources(tmp_path, {"t": table})
    return table, manifest, name in CATALOGUE and name not in _IPC_TYPES


def test_staged_source_round_trip(staged_case):
    table, manifest, _ = staged_case
    loaded = _isolated_worker._load_sources(manifest, lazy=True)["t"]
    actual = loaded.to_table() if isinstance(loaded, LazySource) else loaded
    assert str(actual.schema) == str(table.schema)
    assert actual.equals(table)


def test_staged_source_format(staged_case):
    table, manifest, parquet = staged_case
    assert isinstance(manifest["t"], dict)
    assert arrow_adapter.parquet_holds_type(table.schema.field(0).type) is parquet
    assert manifest["t"]["format"] == ("parquet" if parquet else "ipc")
    loaded = _isolated_worker._load_sources(manifest, lazy=True)["t"]
    assert isinstance(loaded, LazySource if parquet else pa.Table)


@pytest.mark.parametrize("lazy", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        {"path": "x", "format": "feather"},
        {"path": "x"},
        "x",
        {"path": 123, "format": "ipc"},
        {"path": None, "format": "parquet"},
    ],
)
def test_bad_manifest_precedes_reads(monkeypatch, bad, lazy):
    def unexpected(*args, **kwargs):
        pytest.fail("source opened before manifest validation")

    monkeypatch.setattr(_isolated_worker, "LazySource", unexpected)
    monkeypatch.setattr(_isolated_worker.pq, "read_table", unexpected)
    monkeypatch.setattr(_isolated_worker, "ipc_read_path", unexpected, raising=False)
    entries = {
        "a": {"format": "parquet", "path": "a"},
        "b": {"format": "ipc", "path": "b"},
        "c": bad,
    }
    with pytest.raises(ValueError, match="^Invalid isolated source manifest entry[.]$"):
        _isolated_worker._load_sources(entries, lazy=lazy)


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires procfs and Linux address-space accounting"
)
@pytest.mark.parametrize("kind", ["as", "data"])
# The `as` cell (VmSize, cap baseline + 3 x size) only pins that the read fits;
# it does not prove zero copy. The `data` cell (VmData, cap baseline + size // 2)
# plus the /proc/self/maps check below prove the column is mapped, not copied.
def test_mapped_ipc_under_cap(tmp_path, kind):
    table = pa.table({"x": pa.array([1] * 16_000_000, pa.date64())})
    manifest = stage_sources(tmp_path, {"t": table})
    assert manifest["t"]["format"] == "ipc"
    script = """
import json, os, sys
from pathlib import Path
from decoy_engine.execution._isolated_memwatch import read_vm_fields
from decoy_engine.execution._isolated_worker import _load_sources, apply_mem_cap

manifest = json.loads(sys.argv[1])
kind = sys.argv[2]
field = "VmSize" if kind == "as" else "VmData"
size = Path(manifest["t"]["path"]).stat().st_size
baseline = read_vm_fields(os.getpid(), (field,))[field]
apply_mem_cap(baseline + (3 * size if kind == "as" else size // 2), kind)
table = _load_sources(manifest, lazy=True)["t"]
assert table.num_rows == 16_000_000
buf = table["x"].chunk(0).buffers()[1]
assert buf.size >= 128_000_000
staged = os.path.realpath(manifest["t"]["path"])
mapped = False
for line in Path("/proc/self/maps").read_text().splitlines():
    parts = line.split(maxsplit=5)
    if len(parts) == 6 and os.path.realpath(parts[5].removesuffix(" (deleted)")) == staged:
        lo, hi = (int(v, 16) for v in parts[0].split("-"))
        mapped = mapped or lo <= buf.address < hi
assert mapped, "column buffer is not inside a mapping of the staged file"
"""
    subprocess.run(  # noqa: S603 -- fixed child script and test-owned source
        [sys.executable, "-c", script, json.dumps(manifest), kind],
        check=True,
        timeout=60,
        env={**os.environ, **CAPPED_ENV},  # the allocator pins every real child starts with
    )


def _round_trip(tmp_path, table):
    manifest = stage_sources(tmp_path, {"t": table})
    loaded = _isolated_worker._load_sources(manifest, lazy=True)["t"]
    actual = loaded.to_table() if isinstance(loaded, LazySource) else loaded
    return manifest, actual


def _assert_exact(table, actual):
    """Equal schema and values, and every chunk keeps its own dictionary, order and indices."""
    assert actual.schema.equals(table.schema)
    assert str(actual.schema) == str(table.schema)
    assert _canon(actual.to_pylist()) == _canon(table.to_pylist())
    for name in table.column_names:
        want, got = table.column(name), actual.column(name)
        assert [len(c) for c in got.chunks] == [len(c) for c in want.chunks]
        for w, g in zip(want.chunks, got.chunks, strict=True):
            assert g.type.equals(w.type)
            if pa.types.is_dictionary(w.type):
                # Arrow equality fails NaN against itself, so float dictionaries compare by bits.
                if not pa.types.is_floating(w.type.value_type):
                    assert g.dictionary.equals(w.dictionary)
                assert _bits(g.dictionary) == _bits(w.dictionary)
                assert g.indices.equals(w.indices)


def _canon(value):
    """Rows with each float as its bytes, so NaN matches itself and -0.0 differs from +0.0."""
    if isinstance(value, float):
        return struct.pack("<d", value)
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_canon(v) for v in value]
    return value


_FLOAT_BITS = {16: pa.int16(), 32: pa.int32(), 64: pa.int64()}


def _bits(array):
    """Values as compared bit for bit; Arrow equality takes -0.0 for +0.0."""
    if pa.types.is_floating(array.type):
        return array.view(_FLOAT_BITS[array.type.bit_width]).to_pylist()
    return array.to_pylist()


def _dict_chunks(dtype, *chunks):
    """A column whose chunks each carry their own (indices, dictionary)."""
    return pa.chunked_array(
        [
            pa.DictionaryArray.from_arrays(
                pa.array(indices, dtype.index_type),
                pa.array(values, dtype.value_type),
                ordered=dtype.ordered,
            )
            for indices, values in chunks
        ],
        dtype,
    )


_DICT_FIXED = pa.list_(pa.int64(), 2)


def _nan(payload):
    """A float64 NaN with its own payload bits."""
    return struct.unpack("<d", struct.pack("<Q", 0x7FF8_0000_0000_0000 | payload))[0]


def _nested_dicts():
    """A struct and a list over dictionaries, each chunk with its own dictionary."""
    floats = pa.dictionary(pa.int32(), pa.float64())
    strings = pa.dictionary(pa.int32(), pa.string())
    structs = [
        pa.StructArray.from_arrays([_dict_chunks(floats, chunk).chunk(0)], names=["d"])
        for chunk in (([0, 0], [0.0]), ([0, 0], [-0.0]))
    ]
    lists = [
        pa.ListArray.from_arrays(pa.array([0, 1, 2], pa.int32()), _dict_chunks(strings, c).chunk(0))
        for c in (([0, 1], ["a", "b"]), ([1, 0], ["c", "a"]))
    ]
    return pa.table({"s": pa.chunked_array(structs), "l": pa.chunked_array(lists)})


_DICTIONARY_CASES = {
    "fixed_list_beside_string_dicts": pa.table(
        {
            "d": _dict_chunks(
                pa.dictionary(pa.int32(), pa.string()),
                ([0, None, 1], ["a", "b"]),
                ([0, 1, None, 2], ["c", "a", "d"]),
            ),
            "e": _dict_chunks(
                pa.dictionary(pa.int32(), pa.string()),
                ([None, 0, 0], ["x"]),
                ([0, None, 1, 0], ["y", "z"]),
            ),
            "f": pa.chunked_array([[[1, 2], [3, 4], [5, 6]], [[7, 8]] * 4], _DICT_FIXED),
        }
    ),
    "list_values": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int32(), pa.list_(pa.int64())),
                ([0, 1, 0], [[1], [2, 3]]),
                ([1, None, 0], [[9], [2, 3]]),
            )
        }
    ),
    "int8_union_over_128": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int8(), pa.string()),
                (list(range(100)), [f"a{i}" for i in range(100)]),
                (list(range(100)), [f"b{i}" for i in range(100)]),
            )
        }
    ),
    "ordered_conflicting": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int32(), pa.string(), ordered=True),
                ([0, 1], ["b", "c"]),
                ([0, 1], ["c", "b"]),
            )
        }
    ),
    "float_signed_zero": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int32(), pa.float64()),
                ([0, 0], [0.0]),
                ([0, 0], [-0.0]),
            )
        }
    ),
    "float_nan_payloads": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int32(), pa.float64()),
                ([0, 0, None], [_nan(1), _nan(2)]),
                ([1, 0], [_nan(3), 2.5]),
            )
        }
    ),
    "dictionaries_in_struct_and_list": _nested_dicts(),
    "string_null_entry": pa.table(
        {
            "x": _dict_chunks(
                pa.dictionary(pa.int32(), pa.string()),
                ([0, 1, None], ["a", None]),
                ([1, 0], ["b", None]),
            )
        }
    ),
}


@pytest.mark.parametrize("name", list(_DICTIONARY_CASES))
def test_dictionaries_stage_byte_exact_through_ipc(tmp_path, name):
    table = _DICTIONARY_CASES[name]
    assert all(c.num_chunks == 2 for c in table.columns)
    assert not any(arrow_adapter.parquet_holds_type(f.type) for f in table.schema)
    manifest, actual = _round_trip(tmp_path, table)
    assert manifest["t"]["format"] == "ipc"
    _assert_exact(table, actual)


_PARQUET_REFUSED = {
    "decimal128_negative_scale": pa.array([Decimal("1.2E+3"), None], pa.decimal128(6, -2)),
    "decimal256_negative_scale": pa.array([Decimal("1.2E+3"), None], pa.decimal256(6, -2)),
    "decimal128_scale_above_precision": pa.array([None, None], pa.decimal128(2, 5)),
    "decimal256_scale_above_precision": pa.array([None, None], pa.decimal256(2, 5)),
    "fixed_size_binary_zero": pa.array([b"", None], pa.binary(0)),
}


@pytest.mark.parametrize("name", list(_PARQUET_REFUSED))
def test_parquet_refused_parameters_route_through_ipc(tmp_path, name):
    table = pa.table({"x": _PARQUET_REFUSED[name]})
    assert arrow_adapter.parquet_holds_type(table.schema.field(0).type) is False
    manifest, actual = _round_trip(tmp_path, table)
    assert manifest["t"]["format"] == "ipc"
    assert str(actual.schema) == str(table.schema)
    assert actual.equals(table)


def _dict_of_dict():
    """dictionary<dictionary<double>>, which Arrow IPC reads back as the inner indices."""
    inner = pa.DictionaryArray.from_arrays(pa.array([0, 1], pa.int8()), pa.array([2.0, 3.0]))
    return pa.DictionaryArray.from_arrays(pa.array([1, 0, 1], pa.int32()), inner)


_DICT_IN_DICT = {
    "top_level": lambda: _dict_of_dict(),
    "in_struct": lambda: pa.StructArray.from_arrays([_dict_of_dict()], names=["y"]),
    "under_struct_values": lambda: pa.DictionaryArray.from_arrays(
        pa.array([0, 0], pa.int32()),
        pa.StructArray.from_arrays([_dict_of_dict().dictionary], names=["y"]),
    ),
}


@pytest.mark.parametrize("name", list(_DICT_IN_DICT))
def test_dictionary_in_dictionary_is_refused_before_staging(tmp_path, name):
    table = pa.table({"x": _DICT_IN_DICT[name]()})
    with pytest.raises(UnsupportedColumnType) as caught:
        stage_sources(tmp_path, {"t": table})
    assert caught.value.detail == {"column": "x", "kind": "dictionary_in_dictionary"}
    assert "2.0" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []
