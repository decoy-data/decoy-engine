"""Owner question Q6, answer A: a whole-file Parquet read gates the projected schema on the open
file before any column decodes (DATE-RANGE-SENTINEL S5 remediation, V1-2).

`fixed_size_list<date32>` with a null parent makes Arrow raise a raw `ArrowInvalid` while it
decodes, so the refusal has to come first. If the owner picks answer B or C, this file changes."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.io import SourceDateTypeUnsupportedError
from decoy_engine.profile import LazySource
from decoy_engine.profile._cloud_readers import _checked_frame
from decoy_engine.profile._readers import ParquetFileSource


def _write(path: Path) -> Path:
    day = dt.date(2020, 1, 1)
    column = pa.array([[day, day], None], pa.list_(pa.date32(), 2))
    pq.write_table(pa.table({"id": [1, 2], "events": column}), str(path))
    return path


def _assert_refused(exc: BaseException) -> None:
    assert isinstance(exc, SourceDateTypeUnsupportedError), repr(exc)
    assert (exc.table, exc.column, exc.kind) == ("t", "events", "fixed_size_list")


def test_the_local_whole_file_read_refuses_before_it_decodes(tmp_path: Path) -> None:
    source = LazySource(_write(tmp_path / "f.parquet"), table="t")
    with pytest.raises(Exception) as caught:
        source.to_table()
    _assert_refused(caught.value)


def test_a_projection_that_leaves_the_column_out_still_reads(tmp_path: Path) -> None:
    source = LazySource(_write(tmp_path / "f.parquet"), table="t")
    assert source.to_table(["id"]).column("id").to_pylist() == [1, 2]


def test_the_local_frame_and_sample_refuse_the_same_way(tmp_path: Path) -> None:
    source = ParquetFileSource(_write(tmp_path / "f.parquet"), table="t")
    for read in (source.to_frame, lambda: source.sample_frame(10)):
        with pytest.raises(Exception) as caught:
            read()
        _assert_refused(caught.value)


def test_the_cloud_whole_object_read_refuses_before_it_decodes(tmp_path: Path) -> None:
    data = _write(tmp_path / "f.parquet").read_bytes()
    with pytest.raises(Exception) as caught:
        _checked_frame(data, "t")
    _assert_refused(caught.value)


def test_a_directory_source_is_gated_before_it_decodes(tmp_path: Path) -> None:
    """`read_table` opens a directory as a dataset, so the gate reads the schema that same way."""
    directory = tmp_path / "dataset"
    directory.mkdir()
    _write(directory / "part.parquet")
    with pytest.raises(Exception) as caught:
        LazySource(directory, table="t").to_table()
    _assert_refused(caught.value)


def test_a_dotted_projection_to_a_date_leaf_reads_as_the_whole_file_api_returns_it(
    tmp_path: Path,
) -> None:
    """`columns=["s.when"]` yields a top-level `when: date32` from `read_table`. The gate sees
    that projected schema, not a struct, so a plain date leaf under a struct still reads."""
    day = dt.date(2020, 1, 1)
    path = tmp_path / "s.parquet"
    pq.write_table(
        pa.table({"id": [1, 2], "s": pa.array([{"when": day}, {"when": day}])}), str(path)
    )
    table = LazySource(path, table="t").to_table(["s.when"])
    assert table.column_names == ["when"] and table.schema.field("when").type == pa.date32()
    assert table.column("when").to_pylist() == [day, day]


def test_a_dotted_projection_to_a_date_free_child_still_reads(tmp_path: Path) -> None:
    path = tmp_path / "s.parquet"
    pq.write_table(pa.table({"s": pa.array([{"when": dt.date(2020, 1, 1), "n": 5}])}), str(path))
    assert LazySource(path, table="t").to_table(["s.n"]).column("n").to_pylist() == [5]


def test_a_hive_partition_key_projects_as_the_whole_file_read_projects_it(tmp_path: Path) -> None:
    """`pq.read_table(directory, columns=["key"])` reads the partition key. The gate builds its
    dataset the same way, so it neither refuses the projection nor reads a different table."""
    part = tmp_path / "dataset" / "key=7"
    part.mkdir(parents=True)
    pq.write_table(pa.table({"v": [1, 2]}), str(part / "part.parquet"))
    source = LazySource(tmp_path / "dataset", table="t")
    expected = pq.read_table(str(tmp_path / "dataset"), columns=["key"])
    assert source.to_table(["key"]).to_pydict() == expected.to_pydict() == {"key": [7, 7]}
    assert source.to_table().column_names == ["v", "key"]


def test_a_hive_directory_with_a_refused_column_is_still_refused(tmp_path: Path) -> None:
    part = tmp_path / "dataset" / "key=7"
    part.mkdir(parents=True)
    _write(part / "part.parquet")
    with pytest.raises(Exception) as caught:
        LazySource(tmp_path / "dataset", table="t").to_table()
    _assert_refused(caught.value)
