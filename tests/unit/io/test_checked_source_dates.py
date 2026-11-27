"""The checked source read: Arrow dates outside calendar years 1 to 9999 are refused by name and
count, before pandas or Python can see a value (DATE-RANGE-SENTINEL S5)."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.errors import SourceDateUnrepresentableError
from decoy_engine.io import check_source_dates, checked_batches, checked_loader

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


def test_dictionary_columns_count_referenced_rows_only() -> None:
    dictionary = pa.array([0, FAR_DAY], pa.date32())
    unused = pa.DictionaryArray.from_arrays(pa.array([0, 0, None], pa.int8()), dictionary)
    check_source_dates(_table(unused), table="orders")
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
