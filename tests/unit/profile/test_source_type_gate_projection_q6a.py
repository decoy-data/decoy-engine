"""Owner question Q6, answer A: the type gate on the projected Parquet read (DATE-RANGE-SENTINEL
S5, section 4.4b, AT-V3 projection and empty-file cases).

A file with `id` and `events: list<date32>` refuses when the read keeps `events` and reads when it
selects it out, populated or empty, local or range-backed. Footer facts still name both columns."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.io import SourceDateTypeUnsupportedError
from decoy_engine.profile._cloud_readers import _read_parquet_sample
from decoy_engine.profile._readers import LazySource, ParquetFileSource

CODE = reasons.runtime.SOURCE_DATE_TYPE_UNSUPPORTED


def _file(tmp_path: Path, rows: int) -> Path:
    when = pa.StructArray.from_arrays(
        [pa.array([0, 1], pa.date32()), pa.array(["a", "b"])], ["when", "label"]
    )
    table = pa.table(
        {
            "id": pa.array([1, 2]),
            "events": pa.array([[0], [1]], pa.list_(pa.date32())),
            "s": when,
        }
    ).slice(0, rows)
    path = tmp_path / f"t{rows}.parquet"
    pq.write_table(table, str(path))
    return path


def _assert_events_refusal(exc: BaseException, column: str = "events") -> None:
    assert isinstance(exc, SourceDateTypeUnsupportedError)
    assert (exc.table, exc.column, exc.kind, exc.code) == ("t", column, "list", CODE)
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("rows", [2, 0])
def test_open_batches_gates_the_projection_at_open(tmp_path: Path, rows: int) -> None:
    source = LazySource(_file(tmp_path, rows), table="t")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        source.open_batches(10, columns=["events"])  # before any `next`
    _assert_events_refusal(caught.value)
    with pytest.raises(SourceDateTypeUnsupportedError):
        source.open_batches(10)  # no projection means the whole footer schema
    opened = source.open_batches(10, columns=["id"])
    try:
        assert opened.schema.names == ["id", "events", "s"]  # footer facts stay whole-file
        assert [b.schema.names for b in opened.batches] == ([["id"]] if rows else [])
    finally:
        opened.close()


@pytest.mark.parametrize("rows", [2, 0])
def test_iter_batches_and_to_table_refuse_before_a_batch_reaches_the_caller(
    tmp_path: Path, rows: int
) -> None:
    source = LazySource(_file(tmp_path, rows), table="t")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        next(iter(source.iter_batches(10, columns=["events"])), None)
    _assert_events_refusal(caught.value)
    with pytest.raises(SourceDateTypeUnsupportedError):
        list(source.iter_batches(10))
    with pytest.raises(SourceDateTypeUnsupportedError):
        source.to_table()
    assert source.to_table(columns=["id"]).num_rows == rows
    assert sum(b.num_rows for b in source.iter_batches(10, columns=["id"])) == rows


def test_a_date_free_child_of_a_struct_with_a_date_sibling_is_readable(tmp_path: Path) -> None:
    source = LazySource(_file(tmp_path, 2), table="t")
    assert source.to_table(columns=["s.label"]).num_rows == 2
    assert sum(b.num_rows for b in source.iter_batches(10, columns=["s.label"])) == 2
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        source.to_table(columns=["s"])
    assert caught.value.column == "s" and caught.value.kind == "struct"


@pytest.mark.parametrize("rows", [2, 0])
def test_the_local_sample_refuses_the_same_way(tmp_path: Path, rows: int) -> None:
    sample = ParquetFileSource(_file(tmp_path, rows), table="t")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        sample.sample_frame(10)
    _assert_events_refusal(caught.value)


@pytest.mark.parametrize("rows", [2, 0])
def test_the_range_reader_refuses_an_empty_file_like_a_populated_one(
    tmp_path: Path, rows: int
) -> None:
    data = _file(tmp_path, rows).read_bytes()

    def fetch(start: int, end_inclusive: int) -> Any:
        return data[start : end_inclusive + 1]

    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        _read_parquet_sample(len(data), fetch, 10, "t")
    _assert_events_refusal(caught.value)


def test_a_cloud_object_read_whole_is_gated_too() -> None:
    from decoy_engine.profile._cloud_readers import _checked_frame

    buffer = io.BytesIO()
    pq.write_table(pa.table({"events": pa.array([[0]], pa.list_(pa.date32()))}), buffer)
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        _checked_frame(buffer.getvalue(), "t")
    assert caught.value.table == "t"
