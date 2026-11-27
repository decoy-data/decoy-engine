"""AT-V6 (DATE-RANGE-SENTINEL S5, section 4.4b item 6): the pandas working table of a date
dictionary column, and the public routes that carry one.

The checked read keeps a null dictionary entry for the output. Pandas refuses a null category, so
`table_to_pandas` builds each date dictionary column as a separate working categorical: non-null
categories in surviving entry order (unused valid ones kept), a missing row for a null index or a
reference to a null entry, signed int64 codes, `ordered` kept, several chunks unified in first
dictionary order. The Arrow source the output is built from keeps its own dictionaries."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

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
        assert list(series.cat.categories) == [day(5), day(7), day(9)]
        assert series.isna().tolist() == [False, True, True, False, False]
        assert series.iloc[0] == day(7) and series.iloc[3] == day(5)
        assert series.cat.codes.dtype.kind == "i"  # signed codes whatever the index type


def test_unused_valid_entries_stay_and_the_ordered_flag_and_minimum_follow_entry_order() -> None:
    """Entries `[D2, D1, D3]` after the repair, rows reference D1 then D2: the categorical keeps
    that entry order, `ordered=True`, and its minimum is D2 (the first entry), not D1."""
    d1, d2, d3 = 1, 2, 3
    checked = check_source_dates(
        pa.table({"d": _dictionary([d2, FAR, d1, d3], [2, 0, None, 2], ordered=True)}), table="t"
    )
    series = table_to_pandas(checked)["d"]
    assert list(series.cat.categories) == [day(d2), day(d1), day(d3)]
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


def test_a_nanosecond_entry_at_int64_min_is_a_category_not_a_missing_value() -> None:
    entries = pa.array([_INT64_MIN, 1_000], pa.timestamp("ns"))
    column = pa.DictionaryArray.from_arrays(pa.array([0, 1, 0], pa.int8()), entries)
    frame = table_to_pandas(pa.table({"d": column}))
    assert not frame["d"].isna().any()
    assert len(frame["d"].cat.categories) == 2
    assert frame["d"].iloc[0] == frame["d"].iloc[2] != frame["d"].iloc[1]
