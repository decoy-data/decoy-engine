"""AT-V6 (DATE-RANGE-SENTINEL S5, section 4.4b item 6): the pandas working table of a date
dictionary column, and the public routes that carry one.

The checked read keeps a null dictionary entry for the output. Pandas refuses a null category, so
`table_to_pandas` builds each date dictionary column as a separate working categorical: the
non-null entries some row references, in surviving entry order (an unused entry never reaches
pandas), a missing row for a null index or a reference to a null entry, signed int64 codes,
`ordered` kept, several chunks unified in first dictionary order. The Arrow source the output is built from keeps its own dictionaries."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine._arrow_types import is_date_dictionary
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.internal.pandas_compat import table_to_pandas
from decoy_engine.io import check_source_dates
from tests.unit.execution import _auto_chunk_support as support

FAR = 3_000_000


def day(n: int) -> dt.date:
    return dt.date(1970, 1, 1) + dt.timedelta(days=n)


def _dictionary(
    entries: list[Any], indices: list[Any], *, itype: Any = None, ordered: bool = False
) -> pa.Array:
    return pa.DictionaryArray.from_arrays(
        pa.array(indices, itype or pa.int8()), pa.array(entries, pa.date32()), ordered=ordered
    )


def test_a_null_entry_and_a_null_index_become_missing_rows_and_the_rest_keep_order() -> None:
    for itype in (pa.int8(), pa.uint8()):
        column = _dictionary([5, None, 7, 9], [2, 1, None, 0, 2], itype=itype)
        frame = table_to_pandas(pa.table({"d": column}))
        series = frame["d"]
        assert list(series.cat.categories) == [day(5), day(7)]  # 9 is unused
        assert series.isna().tolist() == [False, True, True, False, False]
        assert series.iloc[0] == day(7) and series.iloc[3] == day(5)
        assert series.cat.codes.dtype.kind == "i"  # signed codes whatever the index type


def test_unused_entries_are_dropped_and_the_ordered_flag_and_minimum_follow_entry_order() -> None:
    """Entries `[D2, D1, D3]` after the repair, rows reference D1 then D2: the categorical keeps
    those two in entry order, `ordered=True`, and its minimum is D2 (the first entry)."""
    d1, d2, d3 = 1, 2, 3
    checked = check_source_dates(
        pa.table({"d": _dictionary([d2, FAR, d1, d3], [2, 0, None, 2], ordered=True)}), table="t"
    )
    series = table_to_pandas(checked)["d"]
    assert list(series.cat.categories) == [day(d2), day(d1)]
    assert series.cat.ordered is True
    assert series.min() == day(d2)


def test_several_chunks_unify_their_categories_in_first_dictionary_order() -> None:
    first = _dictionary([5, 6], [1, 0])
    second = _dictionary([6, 8, 5], [2, 0, 1])
    table = pa.table({"d": pa.chunked_array([first, second])})
    series = table_to_pandas(table)["d"]
    assert list(series.cat.categories) == [day(5), day(6), day(8)]
    assert list(series) == [day(6), day(5), day(5), day(6), day(8)]


def test_a_table_without_a_date_dictionary_converts_as_pyarrow_does() -> None:
    table = pa.table({"a": pa.array([1, 2]), "d": pa.array([0, 1], pa.date32())})
    assert table_to_pandas(table).equals(table.to_pandas())


CASES = {
    "null_entry_int8": ([5, None, 7], [0, 1, 2, 2], pa.int8()),
    "null_entry_uint8": ([5, None, 7], [2, 1, 0], pa.uint8()),
    "no_null_uint8": ([5, 7], [1, 0, 1], pa.uint8()),
    "far_unused": ([5, FAR, 7], [2, 0, 2], pa.int8()),
}


def _cfg(tmp_path: Path) -> dict[str, Any]:
    """A config that profiles a clean declared copy, so the run reaches the dictionary column."""
    path = tmp_path / "declared.parquet"
    pq.write_table(pa.table({"id": [0, 1], "d": pa.array([0, 1], pa.date32())}), str(path))
    return support.make_cfg([support.pass_col("id"), support.pass_col("d")], path=str(path))


def _source(case: str) -> pa.Table:
    entries, indices, itype = CASES[case]
    column = _dictionary(entries, indices, itype=itype)
    return pa.table({"id": pa.array(range(len(column))), "d": column})


@pytest.mark.parametrize("case", CASES)
def test_ff_and_the_public_chunked_oracle_run_a_date_dictionary_to_the_same_output(
    case: str, tmp_path: Path
) -> None:
    table = _source(case)
    ff = run_pipeline(
        _cfg(tmp_path),
        sources={support.TABLE: table},
        **support.run_kwargs(execution_mode="full_frame", auto_chunk=False),
    )
    chunked = pa.concat_tables(
        list(
            run_mask_pipeline_chunked(
                _cfg(tmp_path),
                iter([table]),
                table=support.TABLE,
                engine_version=support.ENGINE_VERSION,
                source_schema=table.schema,
            )
        )
    )
    expected = check_source_dates(table, table=support.TABLE).column("d").to_pylist()
    for out in (ff.outputs[support.TABLE], chunked):
        assert out.column("d").to_pylist() == expected
        assert pa.types.is_dictionary(out.schema.field("d").type)


def test_the_far_unused_entry_is_not_in_the_output_dictionary(tmp_path: Path) -> None:
    table = _source("far_unused")
    out = pa.concat_tables(
        list(
            run_mask_pipeline_chunked(
                _cfg(tmp_path),
                iter([table]),
                table=support.TABLE,
                engine_version=support.ENGINE_VERSION,
                source_schema=table.schema,
            )
        )
    )
    assert len(out.column("d").chunk(0).dictionary) == 2


# ---- remediation round 1 (V1-3, V1-4) ------------------------------------------------------

_INT64_MIN = -(2**63)


def _indexed(names: list[str], levels: list[Any]) -> pa.Table:
    """A table as pandas would store it, with the date dictionary level(s) as the index."""
    import pandas as pd

    day = dt.date
    arrays = [
        pd.CategoricalIndex([day(2020, 1, 1), day(2020, 1, 2)], name=names[0]),
        *[pd.Index(level, name=n) for n, level in zip(names[1:], levels, strict=False)],
    ]
    index = arrays[0] if len(arrays) == 1 else pd.MultiIndex.from_arrays(arrays, names=names)
    table = pa.Table.from_pandas(pd.DataFrame({"v": [1, 2]}, index=index))
    assert pa.types.is_dictionary(table.schema.field(names[0]).type)
    return table


def test_a_stored_date_categorical_index_keeps_its_name_and_position() -> None:
    frame = table_to_pandas(_indexed(["d"], []))
    assert list(frame.columns) == ["v"]
    assert frame.index.name == "d" and str(frame.index.dtype) == "category"
    assert [x.isoformat() for x in frame.index] == ["2020-01-01", "2020-01-02"]


def test_a_date_categorical_level_of_a_multi_index_keeps_its_name_and_position() -> None:
    frame = table_to_pandas(_indexed(["d", "k"], [[10, 20]]))
    assert list(frame.columns) == ["v"]
    assert list(frame.index.names) == ["d", "k"]
    assert list(frame.index.get_level_values("k")) == [10, 20]
    assert str(frame.index.get_level_values("d").dtype) == "category"


def test_a_date_dictionary_with_no_chunk_converts_to_an_empty_categorical() -> None:
    schema = pa.schema([("d", pa.dictionary(pa.int8(), pa.date32()))])
    frame = table_to_pandas(pa.Table.from_batches([], schema=schema))
    assert len(frame) == 0 and str(frame["d"].dtype) == "category"


_ZONES = [None, "UTC", "America/New_York", "Asia/Kolkata"]


def _ns_column(entries: list[Any], indices: list[Any], tz: str | None) -> pa.Table:
    column = pa.DictionaryArray.from_arrays(
        pa.array(indices, pa.int8()), pa.array(entries, pa.timestamp("ns", tz))
    )
    return pa.table({"d": column})


@pytest.mark.parametrize("tz", _ZONES)
def test_an_unused_boundary_entry_does_not_change_the_row_it_sits_beside(tz: str | None) -> None:
    """The same ordinary row, with and without an entry no row uses at pandas' NaT sentinel or
    at the far end, has one identity: the same categories, the same cell, the same repr."""
    plain = table_to_pandas(_ns_column([5], [0, None], tz))["d"]
    for unused in (_INT64_MIN, _INT64_MIN + 42, 2**63 - 1):
        beside = table_to_pandas(_ns_column([_INT64_MIN, 5, unused], [1, None], tz))["d"]
        assert list(beside.cat.categories) == list(plain.cat.categories)
        assert beside.iloc[0] == plain.iloc[0] and repr(beside.iloc[0]) == repr(plain.iloc[0])
        assert beside.isna().tolist() == plain.isna().tolist()


@pytest.mark.parametrize("tz", _ZONES)
def test_the_same_row_across_chunks_has_one_identity_with_or_without_an_unused_entry(
    tz: str | None,
) -> None:
    """Chunk one carries an unused boundary entry and chunk two does not; the row both hold is
    one category, equal to the row of a table that never had the entry."""
    first = _ns_column([_INT64_MIN, 5], [1, 1], tz).column("d").chunk(0)
    second = _ns_column([5], [0, None], tz).column("d").chunk(0)
    split = table_to_pandas(pa.table({"d": pa.chunked_array([first, second])}))["d"]
    whole = table_to_pandas(_ns_column([5], [0, 0, 0, None], tz))["d"]
    assert list(split.cat.categories) == list(whole.cat.categories)
    assert split.tolist()[:3] == whole.tolist()[:3]
    assert split.isna().tolist() == whole.isna().tolist()


@pytest.mark.parametrize("tz", _ZONES)
def test_a_referenced_nat_sentinel_is_one_coded_refusal_that_quotes_no_value(
    tz: str | None,
) -> None:
    from decoy_engine.io import SourceDateUnrepresentableError

    with pytest.raises(SourceDateUnrepresentableError) as caught:
        table_to_pandas(_ns_column([_INT64_MIN, 5], [0, 1], tz))
    text = str(caught.value)
    assert caught.value.code == reasons.runtime.SOURCE_DATE_UNREPRESENTABLE
    assert str(_INT64_MIN) not in text and str(_INT64_MIN)[1:] not in text
    assert "WorkingInstant" not in text and caught.value.column == "d"


@pytest.mark.parametrize("near", [_INT64_MIN + 42, 2**63 - 1 - 42], ids=["low", "high"])
@pytest.mark.parametrize("tz", [None, "UTC"])
def test_an_entry_near_the_bound_that_pandas_holds_keeps_its_exact_value(
    near: int, tz: str | None
) -> None:
    frame = table_to_pandas(_ns_column([near, 5], [0, 1], tz))
    assert [c.value for c in frame["d"].cat.categories] == [near, 5]


def test_a_null_dictionary_entry_beside_a_sentinel_entry_no_row_uses_is_a_missing_row() -> None:
    frame = table_to_pandas(_ns_column([_INT64_MIN, None, 7], [1, 2, 2], "America/New_York"))
    assert frame["d"].isna().tolist() == [True, False, False]
    assert [c.value for c in frame["d"].cat.categories] == [7]


def test_an_unnamed_stored_date_index_is_restored_from_its_physical_field() -> None:
    import datetime as dt

    import pandas as pd

    index = pd.CategoricalIndex([dt.date(2020, 1, 1), dt.date(2020, 1, 2)])  # no name
    table = pa.Table.from_pandas(pd.DataFrame({"v": [1, 2]}, index=index))
    assert table.schema.names[-1] == "__index_level_0__"
    frame = table_to_pandas(table)
    assert list(frame.columns) == ["v"] and frame.index.name is None
    assert [x.isoformat() for x in frame.index] == ["2020-01-01", "2020-01-02"]


def test_a_named_stored_date_index_that_shares_a_data_column_name_keeps_both() -> None:
    import datetime as dt

    import pandas as pd

    index = pd.CategoricalIndex([dt.date(2020, 1, 1), dt.date(2020, 1, 2)], name="d")
    table = pa.Table.from_pandas(pd.DataFrame({"d": [10, 20]}, index=index))
    assert "__index_level_0__" in table.schema.names  # the physical field is not the display name
    frame = table_to_pandas(table)
    assert list(frame.columns) == ["d"] and frame["d"].tolist() == [10, 20]
    assert frame.index.name == "d"
    assert [x.isoformat() for x in frame.index] == ["2020-01-01", "2020-01-02"]


# ---- remediation round 3 ---------------------------------------------------------------------


def _frame_pair(tz: str) -> tuple[Any, Any, pa.Table]:
    """The same ordinary row converted without and with an unused sentinel entry."""
    plain = table_to_pandas(_ns_column([5], [0], tz))
    source = check_source_dates(_ns_column([_INT64_MIN, 5], [1], tz), table="t")
    return plain, table_to_pandas(source), source


@pytest.mark.parametrize("tz", ["UTC", "America/New_York"])
def test_mask_input_and_snapshot_do_not_depend_on_an_unused_entry(tz: str) -> None:
    from decoy_engine.generation.pool._canonicalize import _canonicalize_source
    from decoy_engine.quality.snapshot import compute_distribution_snapshot

    plain, beside, _ = _frame_pair(tz)
    assert _canonicalize_source(beside["d"].iloc[0]) == _canonicalize_source(plain["d"].iloc[0])
    snapshot = compute_distribution_snapshot(beside)
    assert snapshot == compute_distribution_snapshot(plain)
    assert "WorkingInstant" not in repr(snapshot)


@pytest.mark.parametrize("tz", ["UTC", "America/New_York"])
def test_passthrough_output_with_an_unused_sentinel_entry_is_the_source_column(tz: str) -> None:
    """The output assembler converts a zero-row frame for the carried column's dtype; it used
    to fail, quoting the value, when the dictionary held an entry pandas cannot."""
    from decoy_engine.execution.pipeline._source_types import (
        table_from_pandas_keeping_source_types,
    )

    _, beside, source = _frame_pair(tz)
    out = table_from_pandas_keeping_source_types(beside, source, untouched=["d"])
    assert out.column("d").to_pylist() == source.column("d").to_pylist()
    assert out.schema.field("d").type == source.schema.field("d").type


def _multi_index_table() -> pa.Table:
    import pandas as pd

    index = pd.MultiIndex.from_arrays(
        [
            pd.CategoricalIndex([dt.date(2020, 1, 1), dt.date(2020, 1, 2)]),
            pd.Index([10, 20]),
        ],
        names=["d", "k"],
    )
    return pa.Table.from_pandas(pd.DataFrame({"v": [1, 2]}, index=index))


def test_a_projection_keeping_one_level_of_a_stored_multi_index_converts() -> None:
    table = _multi_index_table()
    date_only = table_to_pandas(table.select(["v", "d"]))
    assert date_only.index.name == "d" and str(date_only.index.dtype) == "category"
    assert [x.isoformat() for x in date_only.index] == ["2020-01-01", "2020-01-02"]
    key_only = table_to_pandas(table.select(["v", "k"]))
    assert key_only.index.name == "k" and list(key_only.index) == [10, 20]


def test_a_projection_dropping_every_level_converts_to_a_range_index() -> None:
    frame = table_to_pandas(_multi_index_table().select(["v"]))
    assert list(frame.columns) == ["v"] and len(frame) == 2


@pytest.mark.parametrize("labels", [(3, 4), ((1, "a"), (2, "b"))], ids=["int", "tuple"])
def test_a_date_categorical_is_restored_under_its_pandas_label(labels: Any) -> None:
    import pandas as pd

    dates = pd.Categorical([dt.date(2020, 1, 1), dt.date(2020, 1, 2)])
    frame = pd.DataFrame({labels[0]: dates, labels[1]: [1, 2]})
    table = pa.Table.from_pandas(frame)
    assert is_date_dictionary(table.schema.field(0).type)
    back = table_to_pandas(table)
    assert list(back.columns) == list(frame.columns)
    assert [x.isoformat() for x in back[labels[0]]] == ["2020-01-01", "2020-01-02"]
    assert back[labels[1]].tolist() == [1, 2]
