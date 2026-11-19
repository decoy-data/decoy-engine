"""AT-C0: the pure strict lower bound (NONFK-OOM S1).

Every expected figure is worked out by hand from the layout rules in the module docstring. The spy
test fails the moment the function opens a file, reads a lazy source, detects host memory or runs
a probe.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution.pipeline import lazy_spec, lower_bound_bytes, resident_spec
from decoy_engine.execution.pipeline._resident_fit import (
    TableBytesSpec,
    input_bytes,
    pandas_bytes,
    resident_table_bytes,
)

ROWS = 1000


def _lazy(schema: pa.Schema, rows: int = ROWS) -> TableBytesSpec:
    return lazy_spec(rows, schema)


@pytest.mark.parametrize(
    ("fields", "want_input", "want_pandas"),
    [
        # int64 8, float64 8, int32 4, bool 1/8 byte rounded up to 125.
        (
            [("a", pa.int64()), ("b", pa.float64()), ("c", pa.int32()), ("d", pa.bool_())],
            8000 + 8000 + 4000 + 125,
            ROWS * (8 + 8 + 4 + 1),
        ),
        # string and binary: 4 offset bytes per row; pandas holds one object pointer per cell.
        ([("s", pa.string()), ("b", pa.binary())], 4000 + 4000, ROWS * (8 + 8)),
        # large variants: 8 offset bytes per row.
        ([("s", pa.large_string()), ("b", pa.large_binary())], 8000 + 8000, ROWS * (8 + 8)),
        ([("f", pa.binary(5))], 5000, ROWS * 8),
        # decimal128 is 16 bytes in Arrow and one pointer in pandas.
        ([("d", pa.decimal128(10, 2))], 16000, ROWS * 8),
        # temporal widths.
        ([("t", pa.timestamp("us")), ("d", pa.date32())], 8000 + 4000, ROWS * (8 + 8)),
        # small ints keep their own width as the floor (an int with nulls widens to float64).
        ([("a", pa.int8()), ("b", pa.float32())], 1000 + 4000, ROWS * (1 + 4)),
        # dictionary: Arrow index width in the file, one byte per row of pandas codes.
        ([("d", pa.dictionary(pa.int32(), pa.string()))], 4000, ROWS * 1),
        # nested: list offsets, struct children summed, one pointer per row in pandas.
        ([("l", pa.list_(pa.int64()))], 4000, ROWS * 8),
        (
            [("s", pa.struct([("a", pa.int64()), ("b", pa.string())]))],
            8000 + 4000,
            ROWS * 8,
        ),
    ],
)
def test_lazy_lower_bound_is_hand_computed(
    fields: list[tuple[str, pa.DataType]], want_input: int, want_pandas: int
) -> None:
    spec = _lazy(pa.schema(fields))
    assert input_bytes([spec]) == want_input
    assert pandas_bytes([spec]) == want_pandas
    assert lower_bound_bytes([spec]) == want_input + want_pandas


def _shared_dictionary_table() -> pa.Table:
    dictionary = pa.array(["a", "bb", "ccc"])
    chunks = [
        pa.DictionaryArray.from_arrays(pa.array([0, 1, 2, 0], pa.int32()), dictionary),
        pa.DictionaryArray.from_arrays(pa.array([2, 1, 0, 1], pa.int32()), dictionary),
    ]
    return pa.table({"d": pa.chunked_array(chunks)})


def test_shared_dictionary_is_counted_once() -> None:
    table = _shared_dictionary_table()
    # indices 2 chunks x 4 rows x 4 bytes = 32; dictionary: 3 offsets x 4 + 6 data bytes = 18.
    assert resident_table_bytes(table) == 32 + 18
    assert table.nbytes == 32 + 18 + 18  # nbytes charges the dictionary per chunk
    assert lower_bound_bytes([resident_spec(table)]) == (32 + 18) + 8 * 1


def test_distinct_dictionaries_are_counted_per_dictionary() -> None:
    chunks = [
        pa.DictionaryArray.from_arrays(pa.array([0, 1], pa.int32()), pa.array(["a", "bb", "ccc"])),
        pa.DictionaryArray.from_arrays(pa.array([2, 1], pa.int32()), pa.array(["a", "bb", "ccc"])),
    ]
    table = pa.table({"d": pa.chunked_array(chunks)})
    assert resident_table_bytes(table) == 2 * 2 * 4 + 2 * 18


def test_resident_input_is_the_table_nbytes() -> None:
    table = pa.table({"i": pa.array([1, None, 3], pa.int64()), "s": ["x", "yy", None]})
    spec = resident_spec(table)
    assert input_bytes([spec]) == table.nbytes
    assert pandas_bytes([spec]) == 3 * (8 + 8)


def test_a_table_the_run_never_converts_costs_input_only() -> None:
    table = pa.table({"s": ["x", "yy"]})
    spec = resident_spec(table, charge_pandas=False)
    assert pandas_bytes([spec]) == 0
    assert lower_bound_bytes([spec]) == table.nbytes


def test_bound_sums_over_tables() -> None:
    one = _lazy(pa.schema([("a", pa.int64())]), 10)
    two = _lazy(pa.schema([("s", pa.string())]), 20)
    assert lower_bound_bytes([one, two]) == (80 + 80) + (80 + 160)
    assert lower_bound_bytes([]) == 0


def test_bound_does_not_touch_io_host_memory_or_a_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from decoy_engine.execution import _probe
    from decoy_engine.execution.out_of_core import _budget

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("lower_bound_bytes must stay pure")

    table = pa.table({"s": ["x"]})
    specs = [resident_spec(table), _lazy(pa.schema([("a", pa.int64())]))]
    with monkeypatch.context() as m:
        m.setattr(builtins, "open", boom)
        m.setattr(pq, "read_table", boom)
        m.setattr(pq, "ParquetFile", boom)
        m.setattr(pq, "read_metadata", boom)
        m.setattr(_budget, "detect_effective_memory_bytes", boom)
        m.setattr(_budget, "detect_host_memory_bytes", boom)
        m.setattr(_probe, "probe_peak_bytes", boom)
        assert lower_bound_bytes(specs) > 0


def _held_bytes(build: Callable[[], pa.Table]) -> tuple[pa.Table, int]:
    before = pa.total_allocated_bytes()
    table = build()
    return table, pa.total_allocated_bytes() - before


def _nested_shared_dictionary_table() -> pa.Table:
    dictionary = pa.array([f"value-{i:04d}-" + "x" * 20 for i in range(500)])
    chunks = []
    for start in range(5):
        indices = pa.array([(start + i) % 500 for i in range(50)], pa.int32())
        child = pa.DictionaryArray.from_arrays(indices, dictionary)
        chunks.append(pa.StructArray.from_arrays([child], names=["d"]))
    return pa.table({"s": pa.chunked_array(chunks)})


def test_nested_shared_dictionary_never_exceeds_what_is_held() -> None:
    table, held = _held_bytes(_nested_shared_dictionary_table)
    figure = resident_table_bytes(table)
    # nbytes charges the dictionary five times; one copy is held.
    assert table.nbytes > held
    assert figure <= held
    # Only the repeats are removed: the first owner keeps the dictionary.
    dictionary_bytes = table.column("s").chunk(0).field(0).dictionary.nbytes
    assert figure == table.nbytes - 4 * dictionary_bytes


def test_nested_dictionary_in_a_list_is_counted_once() -> None:
    dictionary = pa.array(["a", "bb", "ccc"])
    chunks = []
    for _ in range(3):
        child = pa.DictionaryArray.from_arrays(pa.array([0, 1, 2, 1], pa.int32()), dictionary)
        chunks.append(pa.ListArray.from_arrays(pa.array([0, 2, 4], pa.int32()), child))
    table = pa.table({"l": pa.chunked_array(chunks)})
    assert resident_table_bytes(table) == table.nbytes - 2 * dictionary.nbytes
