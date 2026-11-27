"""The closed type gate and the dictionary repair of the checked source read (DATE-RANGE-SENTINEL
S5, section 4.4b: AT-V4, AT-V6 and the 17.1 rows).

A column that holds dates in a type the read does not know is refused by its type, whether the
dates are inside the calendar or not. The shapes Parquet can store (list, struct, map) are in
`test_source_date_nested_refusal_q6a.py`, because owner question Q6 decides them."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine._arrow_types import is_date_leaf, type_kind, type_nodes
from decoy_engine.io import check_source_dates

CODE = reasons.runtime.SOURCE_DATE_TYPE_UNSUPPORTED
FAR_DAY = 3_000_000  # a date32 in year 10183
DAY_US = 86_400 * 10**6


def refusal(data: Any, *, table: str = "t") -> BaseException | None:
    """What `check_source_dates` raises for `data`, or None."""
    try:
        check_source_dates(data, table=table)
    except Exception as exc:
        return exc
    return None


def assert_refused_by_type(data: Any, kind: str, column: str = "n") -> None:
    exc = refusal(data)
    assert exc is not None, "the column passed the gate"
    assert getattr(exc, "code", None) == CODE, f"refused by {type(exc).__name__}, not by type"
    assert (exc.table, exc.column, exc.kind) == ("t", column, kind)  # type: ignore[attr-defined]
    text = str(exc) + repr(exc)
    assert "10183" not in text and str(FAR_DAY) not in text
    assert "when" not in text  # no child field name
    assert exc.__cause__ is None and exc.__context__ is None


def one(column: Any, name: str = "n") -> pa.Table:
    return pa.table({"id": pa.array(range(len(column))), name: column})


_FAR_AND_OK = ([0, FAR_DAY], [0, 1])


class _DateExt(pa.ExtensionType):
    """A `pa.ExtensionType` subclass over `date32`."""

    def __init__(self) -> None:
        super().__init__(pa.date32(), "tests.date_ext")

    def __arrow_ext_serialize__(self) -> bytes:
        return b""

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes) -> Any:
        return cls()


def _list_view(days: list[int]) -> pa.Array:
    return pa.array([days], pa.list_view(pa.date32()))  # type: ignore[attr-defined]


def _ree(days: list[int]) -> pa.Array:
    # `from_buffers` builds it on every supported pyarrow; `from_arrays` fails on 14.
    run_ends = pa.array(range(1, len(days) + 1), pa.int32())
    arrow_type = pa.run_end_encoded(pa.int32(), pa.date32())
    return pa.Array.from_buffers(
        arrow_type, len(days), [None], children=[run_ends, pa.array(days, pa.date32())]
    )


def _extension(days: list[int]) -> pa.Array:
    return pa.ExtensionArray.from_storage(_DateExt(), pa.array(days, pa.date32()))


def _opaque(days: list[int]) -> pa.Array:
    typ = pa.opaque(pa.date32(), "type", "vendor")  # type: ignore[attr-defined]
    return pa.ExtensionArray.from_storage(typ, pa.array(days, pa.date32()))


def _tensor(days: list[int]) -> pa.Array:
    # `fixed_shape_tensor(timestamp[us], [2])`: one tensor of two timestamps per row.
    storage = pa.FixedSizeListArray.from_arrays(
        pa.array([d * DAY_US for d in days], pa.timestamp("us")), 2
    )
    return pa.ExtensionArray.from_storage(pa.fixed_shape_tensor(pa.timestamp("us"), [2]), storage)


def _dense_union(days: list[int]) -> pa.Array:
    types = pa.array([0] * len(days), pa.int8())
    offsets = pa.array(range(len(days)), pa.int32())
    return pa.UnionArray.from_dense(
        types, offsets, [pa.array(days, pa.date32()), pa.array(["x"])], ["when", "other"]
    )


_NEEDS = {"list_view": "list_view", "opaque": "opaque"}
_SHAPES = {
    "list_view": (_list_view, "list_view"),
    "run_end_encoded": (_ree, "run_end_encoded"),
    "extension": (_extension, "extension"),
    "opaque": (_opaque, "extension"),
    "fixed_shape_tensor": (_tensor, "extension"),
    "dense_union": (_dense_union, "union"),
}


def _build(shape: str, days: list[int]) -> pa.Array:
    needed = _NEEDS.get(shape)
    if needed is not None and not hasattr(pa, needed):
        pytest.skip(f"pyarrow {pa.__version__} has no pa.{needed}")
    return _SHAPES[shape][0](days)


@pytest.mark.parametrize("days", _FAR_AND_OK, ids=["far", "in_calendar"])
@pytest.mark.parametrize("shape", list(_SHAPES))
def test_a_date_in_a_container_or_encoded_type_is_refused_by_type(
    shape: str, days: list[int]
) -> None:
    """AT-V4: the gate reads the type, so a far date and an in-calendar date refuse alike."""
    assert_refused_by_type(one(_build(shape, days)), _SHAPES[shape][1])


def test_the_refusal_names_the_outermost_kind() -> None:
    inner = pa.array([[[0]]], pa.list_(pa.list_(pa.date32())))
    assert_refused_by_type(one(inner), "list")
    struct_of_list = pa.StructArray.from_arrays(
        [pa.array([[0]], pa.list_(pa.date32()))], names=["when"]
    )
    assert_refused_by_type(one(struct_of_list), "struct")


@pytest.mark.parametrize(
    "column",
    [
        pa.array([1, 2], pa.time64("us")),
        pa.array([1, 2], pa.duration("us")),
        pa.array([[1], [2]], pa.list_(pa.time64("us"))),
        pa.StructArray.from_arrays([pa.array([1, 2], pa.duration("s"))], names=["d"]),
        pa.array(["a", "b"]),
        pa.array([[1], [2]], pa.list_(pa.int64())),
    ],
    ids=["time64", "duration", "list_time64", "struct_duration", "text", "list_int"],
)
def test_a_type_with_no_date_leaf_passes_the_gate_unchanged(column: pa.Array) -> None:
    """AT-V4 pass cases: `pa.types.is_temporal` would count time64 and duration as dates."""
    table = one(column)
    assert refusal(table) is None
    assert check_source_dates(table, table="t") is table


def test_a_plain_date_leaf_and_a_top_level_dictionary_of_one_pass_the_gate() -> None:
    dictionary = pa.array([0, 5], pa.date32())
    column = pa.DictionaryArray.from_arrays(pa.array([0, 1], pa.int8()), dictionary)
    plain = pa.array([0, 1], pa.timestamp("us", "UTC"))
    assert refusal(pa.table({"a": column, "b": plain, "c": pa.array([0, 1], pa.date64())})) is None


def test_the_walker_finds_a_date_through_a_base_extension_type() -> None:
    """17.1 H1: the shared walker follows `pa.BaseExtensionType`, which `opaque`, `uuid`,
    `json` and `fixed_shape_tensor` share, not only `pa.ExtensionType` subclasses."""
    assert any(is_date_leaf(n) for n in type_nodes(_tensor([0, 1]).type))
    assert type_kind(_tensor([0, 1]).type) == "extension"


def test_the_date_leaf_is_date32_date64_or_timestamp_only() -> None:
    leaves = [pa.date32(), pa.date64(), pa.timestamp("s"), pa.timestamp("ns", "UTC")]
    others = [pa.time32("s"), pa.time64("us"), pa.duration("s"), pa.int32(), pa.string()]
    assert all(is_date_leaf(t) for t in leaves)
    assert not any(is_date_leaf(t) for t in others)


def test_a_record_batch_and_a_zero_row_table_are_gated_by_schema() -> None:
    nested = pa.array([[0]], pa.list_(pa.date32()))
    assert_refused_by_type(one(nested).to_batches()[0], "list")
    empty = pa.table({"n": pa.array([], pa.list_(pa.date32()))})
    assert empty.num_rows == 0
    assert_refused_by_type(empty, "list")


def test_check_source_schema_gates_a_schema_alone() -> None:
    from decoy_engine.io import SourceDateTypeUnsupportedError, check_source_schema

    check_source_schema(pa.schema([("id", pa.int64()), ("d", pa.date32())]), table="t")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        check_source_schema(pa.schema([("n", pa.list_(pa.date32()))]), table="t")
    assert (caught.value.table, caught.value.column, caught.value.kind) == ("t", "n", "list")
    assert caught.value.__cause__ is None and caught.value.__context__ is None


# --- AT-V6: the dictionary repair ---------------------------------------------------------------


def _dictionary(entries: list[int | None], indices: list[int | None], **kw: Any) -> pa.Array:
    return pa.DictionaryArray.from_arrays(
        pa.array(indices, kw.pop("index_type", pa.int8())),
        pa.array(entries, pa.date32()),
        ordered=kw.pop("ordered", False),
    )


def _chunk(column: Any, i: int = 0) -> Any:
    return column.chunk(i) if isinstance(column, pa.ChunkedArray) else column


def _entries(column: Any) -> list[Any]:
    return _chunk(column).dictionary.to_pylist()


def _indices(column: Any) -> list[Any]:
    return _chunk(column).indices.to_pylist()


def _days(day: int) -> Any:
    return pa.scalar(day, pa.date32()).as_py()


def test_the_repair_keeps_entry_order_and_the_ordered_flag() -> None:
    """AT-V6: entries `[D2, FAR, D1, D3]`, rows referencing D1 before D2. A re-encode gives
    `[D1, D2]` (row order) and drops the unused D3; the repair filters and remaps instead."""
    d1, d2, d3 = 1, 2, 3
    column = _dictionary([d2, FAR_DAY, d1, d3], [2, 0, None, 2], ordered=True)
    table = pa.table({"d": column})
    cleaned = check_source_dates(table, table="t").column("d")
    assert cleaned.type == column.type  # int8 index, ordered
    assert cleaned.type.ordered is True
    assert _entries(cleaned) == [_days(d2), _days(d1), _days(d3)]
    assert _indices(cleaned) == [1, 0, None, 1]
    assert cleaned.to_pylist() == table.column("d").to_pylist()


def test_a_null_entry_before_the_bad_one_is_kept_and_later_rows_remap() -> None:
    """Entries `[D, null, FAR, D2]` with uint8 indices `[0, 1, 3]`: `[D, null, D2]`, `[0, 1, 2]`;
    the middle row stays logically missing and the last stays D2. Omitting the null fill of the
    keep mask drops the null entry and shifts every later row (M-28)."""
    column = _dictionary([5, None, FAR_DAY, 7], [0, 1, 3], index_type=pa.uint8())
    cleaned = check_source_dates(pa.table({"d": column}), table="t").column("d")
    assert _entries(cleaned) == [_days(5), None, _days(7)]
    assert _indices(cleaned) == [0, 1, 2]
    assert cleaned.type.index_type == pa.uint8()
    assert cleaned.to_pylist() == [_days(5), None, _days(7)]


@pytest.mark.parametrize("index_type", [pa.uint8(), pa.int8(), pa.uint16()], ids=str)
def test_the_remap_vector_is_int64_before_it_narrows_to_the_index_type(
    monkeypatch: pytest.MonkeyPatch, index_type: pa.DataType
) -> None:
    """The running count of kept entries is summed in int64 whatever the index type (M-28): a
    narrow sum wraps past 127 or 255 kept entries. The spy watches the sum itself."""
    from decoy_engine.io import source_dates

    seen: list[tuple[pa.DataType, int]] = []
    real = source_dates._pc.cumulative_sum

    def spy(values: Any, *args: Any, **kwargs: Any) -> Any:
        out = real(values, *args, **kwargs)
        seen.append((values.type, out[-1].as_py()))
        return out

    monkeypatch.setattr(source_dates._pc, "cumulative_sum", spy)
    entries = [FAR_DAY, *range(300)]
    column = _dictionary(entries, [1, 2, 3], index_type=index_type)
    cleaned = check_source_dates(pa.table({"d": column}), table="t").column("d")
    assert seen == [(pa.int64(), 300)]
    assert _indices(cleaned) == [0, 1, 2] and cleaned.chunk(0).dictionary.type == pa.date32()
    assert cleaned.type == column.type


def test_two_chunks_with_different_dictionaries_are_repaired_chunk_by_chunk() -> None:
    first = _dictionary([5, FAR_DAY, 6], [2, 0])
    second = _dictionary([FAR_DAY, 9, 8], [1, 2, 1])
    table = pa.table({"d": pa.chunked_array([first, second])})
    cleaned = check_source_dates(table, table="t").column("d")
    assert [c.dictionary.to_pylist() for c in cleaned.chunks] == [
        [_days(5), _days(6)],
        [_days(9), _days(8)],
    ]
    assert [c.indices.to_pylist() for c in cleaned.chunks] == [[1, 0], [0, 1, 0]]
    assert cleaned.to_pylist() == table.column("d").to_pylist()


def test_a_record_batch_dictionary_is_repaired_with_the_same_order() -> None:
    column = _dictionary([2, FAR_DAY, 1, 3], [2, 0, None, 2], ordered=True)
    batch = pa.table({"d": column}).to_batches()[0]
    cleaned = check_source_dates(batch, table="t")
    assert isinstance(cleaned, pa.RecordBatch)
    assert _entries(cleaned.column(0)) == [_days(2), _days(1), _days(3)]
    assert _indices(cleaned.column(0)) == [1, 0, None, 1]
    assert cleaned.column(0).type.ordered is True


FIRST_US = -719_162 * DAY_US  # 0001-01-01T00:00:00 UTC
LAST_US = 2_932_897 * DAY_US - 1  # 9999-12-31T23:59:59.999999 UTC


def _zoned_dictionary(values: list[int], zone: str, indices: list[int]) -> pa.Array:
    return pa.DictionaryArray.from_arrays(
        pa.array(indices, pa.int8()), pa.array(values, pa.timestamp("us", zone))
    )


def test_kiritimati_crosses_both_calendar_ends_and_adak_stays_inside() -> None:
    """Kiritimati (UTC+14) leaves the calendar at the top, and its local date at the first UTC
    instant of year 1 is before year 1. An unused crossing entry drops and a referenced one
    counts once. Adak (UTC-10/-11) stays in range at both UTC endpoints, and survives."""
    kiri = "Pacific/Kiritimati"
    for crossing in (LAST_US, FIRST_US):
        unused = _zoned_dictionary([crossing, 0], kiri, [1, 1])
        cleaned = check_source_dates(pa.table({"d": unused}), table="t").column("d")
        assert _entries(cleaned) == pa.array([0], pa.timestamp("us", kiri)).to_pylist(), crossing
        used = _zoned_dictionary([crossing, 0], kiri, [0, 1])
        err = refusal(pa.table({"d": used}))
        assert err is not None and getattr(err, "count", None) == 1, crossing
        assert err.code == reasons.runtime.SOURCE_DATE_UNREPRESENTABLE  # type: ignore[attr-defined]
    adak = _zoned_dictionary([FIRST_US, LAST_US], "America/Adak", [0, 1])
    kept = check_source_dates(pa.table({"d": adak}), table="t").column("d")
    assert kept.to_pylist() == adak.to_pylist()
    assert len(_entries(kept)) == 2


def test_a_dictionary_with_no_bad_entry_comes_back_as_it_is() -> None:
    table = pa.table({"d": _dictionary([1, None, 2], [0, 1, 2])})
    assert check_source_dates(table, table="t") is table
