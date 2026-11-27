"""The checked source read: Arrow dates outside calendar years 1 to 9999 are refused by name and
count, before pandas or Python can see a value (DATE-RANGE-SENTINEL S5)."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.io import (
    SourceDateUnrepresentableError,
    check_source_dates,
    checked_batches,
    checked_loader,
)

DAY = 86_400
FIRST_DAY, LAST_DAY = -719_162, 2_932_896
# Year 10183, the value that reached `datetime.date` and raised with the year in its text.
FAR_DAY = 3_000_000
TPS = {"s": 1, "ms": 1_000, "us": 1_000_000}


def _table(column: pa.Array, name: str = "d") -> pa.Table:
    return pa.table({"id": pa.array(range(len(column))), name: column})


def _refused(table: pa.Table | pa.RecordBatch) -> SourceDateUnrepresentableError:
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        check_source_dates(table, table="orders")
    return caught.value


def test_date32_inside_the_calendar_passes_including_both_edges_and_nulls() -> None:
    check_source_dates(
        _table(pa.array([FIRST_DAY, 0, LAST_DAY, None], pa.date32())), table="orders"
    )


@pytest.mark.parametrize("day", [FIRST_DAY - 1, LAST_DAY + 1, FAR_DAY, -4_000_000])
def test_date32_one_day_outside_either_edge_is_refused(day: int) -> None:
    err = _refused(_table(pa.array([0, day, None], pa.date32())))
    assert (err.table, err.column, err.count) == ("orders", "d", 1)
    assert err.code == reasons.runtime.SOURCE_DATE_UNREPRESENTABLE


def test_the_refusal_carries_no_value_cause_or_context() -> None:
    err = _refused(_table(pa.array([FAR_DAY, FAR_DAY], pa.date32())))
    assert err.count == 2
    text = str(err) + repr(err)
    assert "10183" not in text and str(FAR_DAY) not in text
    assert err.__cause__ is None and err.__context__ is None


def test_date64_edges() -> None:
    ms = DAY * 1000
    ok = pa.array([FIRST_DAY * ms, (LAST_DAY + 1) * ms - 1], pa.date64())
    check_source_dates(_table(ok), table="orders")
    assert _refused(_table(pa.array([(LAST_DAY + 1) * ms], pa.date64()))).count == 1
    assert _refused(_table(pa.array([FIRST_DAY * ms - 1], pa.date64()))).count == 1


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
def test_naive_timestamp_edges_keep_the_last_instant_of_year_9999(unit: str) -> None:
    ticks = TPS[unit]
    low, high = FIRST_DAY * DAY * ticks, (LAST_DAY + 1) * DAY * ticks - 1
    check_source_dates(_table(pa.array([low, high], pa.timestamp(unit))), table="orders")
    assert _refused(_table(pa.array([high + 1], pa.timestamp(unit)))).count == 1
    assert _refused(_table(pa.array([low - 1, high + 1], pa.timestamp(unit)))).count == 2


def test_nanosecond_timestamps_cannot_leave_the_calendar() -> None:
    edge = pa.array([-(2**63), 2**63 - 1], pa.timestamp("ns"))
    check_source_dates(_table(edge), table="orders")


def test_zoned_timestamp_is_judged_by_its_local_calendar_date() -> None:
    top = (LAST_DAY + 1) * DAY * 10**6 - 1  # 9999-12-31T23:59:59.999999 UTC
    karachi = pa.timestamp("us", "Asia/Karachi")  # UTC+5: local date reaches year 10000
    new_york = pa.timestamp("us", "America/New_York")  # UTC-5: local date before year 1
    assert _refused(_table(pa.array([top], karachi))).count == 1
    check_source_dates(_table(pa.array([top], new_york)), table="orders")
    first = FIRST_DAY * DAY * 10**6  # 0001-01-01T00:00 UTC
    assert _refused(_table(pa.array([first], new_york))).count == 1
    check_source_dates(_table(pa.array([first], karachi)), table="orders")
    check_source_dates(_table(pa.array([first + 10 * 3600 * 10**6], new_york)), table="orders")


def test_dictionary_columns_count_referenced_rows() -> None:
    dictionary = pa.array([0, FAR_DAY], pa.date32())
    used = pa.DictionaryArray.from_arrays(pa.array([0, 1, 1], pa.int8()), dictionary)
    assert _refused(_table(used)).count == 2


def test_the_first_offending_column_is_named_and_other_types_are_ignored() -> None:
    table = pa.table(
        {
            "name": pa.array(["a", "b"]),
            "ok": pa.array([0, 1], pa.date32()),
            "bad": pa.array([FAR_DAY, 0], pa.date32()),
            "later": pa.array([FAR_DAY, FAR_DAY], pa.date32()),
        }
    )
    err = _refused(table)
    assert (err.column, err.count) == ("bad", 1)


def test_all_null_and_empty_columns_pass() -> None:
    check_source_dates(_table(pa.array([None, None], pa.date32())), table="orders")
    check_source_dates(_table(pa.array([], pa.date32())), table="orders")
    check_source_dates(pa.table({"x": pa.nulls(3)}), table="orders")


def test_a_record_batch_is_checked_like_a_table() -> None:
    batch = _table(pa.array([FAR_DAY], pa.date32())).to_batches()[0]
    assert _refused(batch).count == 1


def test_checked_batches_yields_clean_batches_and_stops_at_the_bad_one() -> None:
    good = _table(pa.array([0, 1], pa.date32())).to_batches()[0]
    bad = _table(pa.array([FAR_DAY], pa.date32())).to_batches()[0]
    seen = []
    with pytest.raises(SourceDateUnrepresentableError):
        for batch in checked_batches(iter([good, bad, good]), table="orders"):
            seen.append(batch)
    assert seen == [good]


def test_checked_loader_checks_what_the_loader_returns() -> None:
    bad = _table(pa.array([FAR_DAY], pa.date32()))
    load = checked_loader(lambda name: bad)
    assert load is not None
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        load("customers")
    assert caught.value.table == "customers"
    assert checked_loader(None) is None


def test_a_dictionary_of_something_else_is_left_alone() -> None:
    values = pa.array([{"a": 1}, {"a": 2}], pa.struct([("a", pa.int64())]))
    column = pa.DictionaryArray.from_arrays(pa.array([0, 1, 0], pa.int8()), values)
    check_source_dates(_table(column), table="orders")


def test_an_unused_bad_dictionary_entry_is_dropped_not_refused() -> None:
    """Section 4.4 counts referenced rows. The plan wins over the first S5 pin, which refused a
    job for an entry no row used; the returned table holds no entry pandas could choke on."""
    dictionary = pa.array([0, FAR_DAY, 5], pa.date32())
    column = pa.DictionaryArray.from_arrays(pa.array([0, None, 2, 0], pa.int8()), dictionary)
    table = _table(column)
    cleaned = check_source_dates(table, table="orders")
    assert cleaned.schema == table.schema
    assert cleaned.column("d").to_pylist() == table.column("d").to_pylist()
    used = pa.DictionaryArray.from_arrays(pa.array([1], pa.int8()), dictionary)
    assert _refused(_table(used)).count == 1
    cleaned.to_pandas()  # would raise `year 10183 is out of range` on the unused entry


def test_a_chunked_dictionary_column_is_cleaned_chunk_by_chunk() -> None:
    dictionary = pa.array([0, FAR_DAY], pa.date32())
    chunk = pa.DictionaryArray.from_arrays(pa.array([0, 0], pa.int8()), dictionary)
    table = pa.table({"d": pa.chunked_array([chunk, chunk])})
    cleaned = check_source_dates(table, table="orders")
    assert cleaned.schema == table.schema and cleaned.num_rows == 4
    cleaned.to_pandas()


def test_a_record_batch_is_cleaned_too() -> None:
    dictionary = pa.array([0, FAR_DAY], pa.date32())
    column = pa.DictionaryArray.from_arrays(pa.array([0, 0], pa.int8()), dictionary)
    batch = _table(column).to_batches()[0]
    cleaned = check_source_dates(batch, table="orders")
    assert isinstance(cleaned, pa.RecordBatch) and cleaned.schema == batch.schema
    cleaned.to_pandas()


def test_a_clean_table_comes_back_as_the_same_object() -> None:
    table = _table(pa.array([0, 1], pa.date32()))
    assert check_source_dates(table, table="orders") is table


def _nested_shapes(far: pa.Array) -> dict[str, pa.Array]:
    offsets = pa.array([0, 1, 3], pa.int32())
    return {
        "list": pa.ListArray.from_arrays(offsets, far),
        "large_list": pa.LargeListArray.from_arrays(pa.array([0, 1, 3], pa.int64()), far),
        "fixed_size_list": pa.FixedSizeListArray.from_arrays(far.slice(0, 2), 1),
        "struct": pa.StructArray.from_arrays([far.slice(0, 2)], names=["when"]),
        "list_of_struct": pa.ListArray.from_arrays(
            offsets, pa.StructArray.from_arrays([far], names=["when"])
        ),
        "map_item": pa.MapArray.from_arrays(offsets, pa.array(["a", "b", "c"]), far),
    }


@pytest.mark.parametrize(
    "shape", ["list", "large_list", "fixed_size_list", "struct", "list_of_struct", "map_item"]
)
def test_a_far_date_nested_in_a_container_is_refused_by_name_and_count(shape: str) -> None:
    far = pa.array([0, FAR_DAY, FAR_DAY], pa.date32())
    nested = _nested_shapes(far)[shape]
    err = _refused(pa.table({"n": nested}))
    assert err.column == "n" and err.count >= 1
    assert "10183" not in str(err) + repr(err)


def test_a_nested_date_inside_the_calendar_and_a_null_parent_pass() -> None:
    ok = pa.array([FIRST_DAY, LAST_DAY], pa.date32())
    check_source_dates(
        pa.table({"n": pa.ListArray.from_arrays(pa.array([0, 1, 2], pa.int32()), ok)}), table="o"
    )
    struct = pa.StructArray.from_arrays(
        [pa.array([FAR_DAY, 0], pa.date32())],
        names=["when"],
        mask=pa.array([True, False]),
    )
    check_source_dates(pa.table({"n": struct}), table="orders")


def test_a_zoned_instant_past_year_9999_is_refused_even_when_its_local_date_fits() -> None:
    year_10000_utc = (
        (LAST_DAY + 1) * DAY * 10**6
    )  # 10000-01-01T00:00 UTC, 9999-12-31 19:00 in New York
    new_york = pa.timestamp("us", "America/New_York")
    assert _refused(_table(pa.array([year_10000_utc], new_york))).count == 1


def test_a_resident_profile_source_refuses_the_far_date() -> None:
    from decoy_engine.profile._readers_resident import ResidentTableSource

    source = ResidentTableSource(_table(pa.array([FAR_DAY], pa.date32())), "orders")
    for read in (lambda: source.sample_frame(10), source.to_frame):
        with pytest.raises(SourceDateUnrepresentableError) as caught:
            read()
        assert caught.value.table == "orders"


def test_a_cloud_parquet_object_is_checked_before_pandas_reads_it() -> None:
    import io as bytes_io

    import pyarrow.parquet as pq

    from decoy_engine.profile._cloud_readers import _checked_frame

    buffer = bytes_io.BytesIO()
    pq.write_table(_table(pa.array([FAR_DAY], pa.date32())), buffer)
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        _checked_frame(buffer.getvalue(), "orders")
    assert caught.value.table == "orders"


def test_the_cloud_builders_carry_the_configured_table_name() -> None:
    from decoy_engine.profile._cloud_readers import (
        GcsParquetSource,
        S3ParquetSource,
        build_gcs_profile_source,
        build_s3_profile_source,
    )

    s3 = build_s3_profile_source({"format": "parquet", "bucket": "b", "key": "k"}, "orders")
    gcs = build_gcs_profile_source({"format": "parquet", "bucket": "b", "key": "k"}, "orders")
    assert isinstance(s3, S3ParquetSource) and s3._table == "orders"
    assert isinstance(gcs, GcsParquetSource) and gcs._table == "orders"
