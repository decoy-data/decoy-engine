"""AT-V10 (DATE-RANGE-SENTINEL S5, section 4.4b item 5): the bytes of a returned date column.

A sliced or null-poisoned Arrow date column shares a backing buffer whose bytes include a day
the checked read excluded. Serialized as IPC (which pads each buffer to eight bytes), the
excluded day rides out in the alignment bytes or the null slot. Every public chunked return
passes its date columns through `own_date_columns`, so the reopened bytes hold only the
logical values."""

from __future__ import annotations

import io
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.safe_output import own_date_columns
from tests.unit.execution import _auto_chunk_support as support

FAR = 3_000_000  # year 10183, the excluded day
MARKER32 = FAR.to_bytes(4, "little")
MARKER64 = (FAR * 86_400_000).to_bytes(8, "little")
MARKER_TS = (FAR * 86_400 * 10**6).to_bytes(8, "little")


def _ipc(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def _reopen(table: pa.Table) -> pa.Table:
    return pa.ipc.open_stream(_ipc(table)).read_all()


def _poisoned_nulls() -> pa.Array:
    """Slot 1 is null but its payload word holds the excluded day; slot 2's validity bit is set."""
    data = pa.py_buffer(
        b"".join(v.to_bytes(4, "little", signed=True) for v in (5, FAR, 7, FAR)),
    )
    validity = pa.py_buffer(bytes([0b0000_1101]))  # bit 3 set past the logical length of 3
    return pa.Array.from_buffers(pa.date32(), 3, [validity, data], null_count=1)


def _dictionary(far_trailing: bool) -> pa.Array:
    """Entries `[7, null, 9, 11]` with a hidden fifth slot of the backing buffer that holds the
    excluded day; rows are a slice of the indices."""
    backing = pa.array([7, None, 9, 11, FAR if far_trailing else 13], pa.date32())
    column = pa.DictionaryArray.from_arrays(pa.array([3, 1, 0, 3], pa.uint8()), backing.slice(0, 4))
    return column.slice(1, 3)


CASES: dict[str, Any] = {
    "offset_zero_slice": lambda: pa.array([0, FAR], pa.date32()).slice(0, 1),
    "nonzero_offset_slice": lambda: pa.array([FAR, 0, 3, FAR], pa.date32()).slice(1, 2),
    "poisoned_null_payload": _poisoned_nulls,
    "date64": lambda: pa.array([0, FAR * 86_400_000], pa.date64()).slice(0, 1),
    "zoned_timestamp": lambda: pa.array([0, FAR * 86_400 * 10**6], pa.timestamp("us", "UTC")).slice(
        0, 1
    ),
    "dictionary_with_null_entry": lambda: _dictionary(far_trailing=False),
    "dictionary_poisoned_trailing_storage": lambda: _dictionary(far_trailing=True),
}


def _assert_clean(returned: pa.Table, expected: pa.Table) -> None:
    raw = _ipc(returned)
    assert not any(m in raw for m in (MARKER32, MARKER64, MARKER_TS)), "excluded day in IPC bytes"
    reopened = _reopen(returned)
    assert reopened.schema.equals(expected.schema)
    assert reopened.to_pylist() == expected.to_pylist()
    column = reopened.column("d").chunk(0)
    if pa.types.is_dictionary(column.type):
        assert column.type == expected.column("d").type  # index type and ordered flag
        assert column.dictionary.to_pylist() == expected.column("d").chunk(0).dictionary.to_pylist()
        assert column.indices.to_pylist() == expected.column("d").chunk(0).indices.to_pylist()
    else:
        validity, payload = column.buffers()[0], column.buffers()[1]
        width = column.type.bit_width // 8
        assert payload.size == width * len(column)  # exact length, no hidden tail
        if validity is not None and len(column) % 8:
            assert (
                validity.to_pybytes()[len(column) // 8] >> (len(column) % 8) == 0
            )  # zero tail bits
        for slot, valid in enumerate(column.is_valid().to_pylist()):
            if not valid:
                assert payload.to_pybytes()[slot * width : (slot + 1) * width] == bytes(width)


def _table(column: pa.Array) -> pa.Table:
    return pa.table({"id": pa.array(range(len(column))), "d": column})


@pytest.mark.parametrize("case", CASES)
def test_own_date_columns_removes_every_excluded_byte(case: str) -> None:
    table = _table(CASES[case]())
    _assert_clean(own_date_columns(table), table)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("route", ["CH", "NCH"])
def test_each_public_chunked_api_returns_clean_date_bytes(case: str, route: str) -> None:
    table = _table(CASES[case]())
    cfg = support.make_cfg([support.pass_col("id"), support.pass_col("d")])
    if route == "CH":
        stream = run_mask_pipeline_chunked(
            cfg,
            iter([table]),
            table=support.TABLE,
            engine_version=support.ENGINE_VERSION,
            source_schema=table.schema,
        )
    else:
        stream = run_native_chunked(
            cfg, iter([table]), table=support.TABLE, engine_version=support.ENGINE_VERSION
        )
    returned = pa.concat_tables(list(stream))
    _assert_clean(returned, table)


def test_a_table_with_no_date_column_comes_back_as_it_is() -> None:
    table = pa.table({"a": pa.array([1, 2])})
    assert own_date_columns(table) is table


def test_the_owned_column_keeps_unit_zone_and_entry_order() -> None:
    column = pa.DictionaryArray.from_arrays(
        pa.array([1, 0], pa.int8()),
        pa.array([5, 3], pa.timestamp("ms", "Asia/Karachi")),
        ordered=True,
    )
    owned = own_date_columns(pa.table({"d": column})).column("d").chunk(0)
    assert owned.type == column.type and owned.type.ordered is True
    assert owned.dictionary.to_pylist() == column.dictionary.to_pylist()
