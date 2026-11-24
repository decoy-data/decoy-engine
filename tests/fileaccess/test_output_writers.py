"""OUTPUT-METADATA-LEAK E1: the output Parquet writers of the Arrow adapter.

`write_output_table` and `output_parquet_writer` are the only engine functions that write a
published Parquet file. Each builds its writer from the sanitized schema, so the footer is clean
whatever metadata the table or the batches carry.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import fileaccess
from decoy_engine.fileaccess import STAGE_MARKER, FileRequest, FileRole
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.safe_output import _file_metadata as fm
from tests.security import _metadata_canary as mc

CANARY = "DCY-CANARY"


def _dirty_table() -> pa.Table:
    return mc.canary_table(
        {"a": pa.array([1, 2, 3]), "b": pa.array(["x", "y", "z"])}, field_meta_on=("a", "b")
    )


@contextmanager
def _stage(tmp_path: Path) -> Iterator[tuple[object, Path]]:
    out = fileaccess.capture().output_dir(
        FileRequest(FileRole.TARGET_OUTPUT, "write", str(tmp_path / "out"), "targets.path")
    )
    txn = out.begin("dir", "exclusive", label="publication")
    try:
        yield txn, Path(txn.local_stage_path())
    finally:
        txn.abort()


def _footer_canaries(path: Path) -> set[str]:
    return mc.canaries_in(path)


def test_write_output_table_writes_a_clean_footer(tmp_path: Path) -> None:
    with _stage(tmp_path) as (txn, stage):
        arrow_adapter.write_output_table(_dirty_table(), txn, "t.parquet")
        assert _footer_canaries(stage / "t.parquet") == set()
        assert pq.read_table(stage / "t.parquet").num_rows == 3


def test_raw_write_table_still_carries_the_metadata(tmp_path: Path) -> None:
    """The control: the same table through the raw writer leaks, so the cell above can fail."""
    with _stage(tmp_path) as (txn, stage):
        arrow_adapter.write_table(_dirty_table(), txn, "t.parquet")
        assert _footer_canaries(stage / "t.parquet") != set()


def test_output_parquet_writer_cleans_dirty_schema_and_batches(tmp_path: Path) -> None:
    table = _dirty_table()
    with _stage(tmp_path) as (txn, stage):
        with arrow_adapter.output_parquet_writer(txn, "t.parquet", table.schema) as writer:
            for batch in table.to_batches():
                assert batch.schema.metadata  # the batches stay dirty; the writer schema governs
                writer.write_batch(batch)
        assert _footer_canaries(stage / "t.parquet") == set()
        footer = pq.ParquetFile(stage / "t.parquet").metadata.metadata
        schema = pa.ipc.read_schema(pa.py_buffer(base64.b64decode(footer[b"ARROW:schema"])))
        assert CANARY.encode() not in b"".join(mc.schema_texts(schema))


def test_output_parquet_writer_with_no_batches_writes_a_zero_row_clean_file(
    tmp_path: Path,
) -> None:
    table = _dirty_table()
    with _stage(tmp_path) as (txn, stage):
        arrow_adapter.output_parquet_writer(txn, "t.parquet", table.schema).close()
        assert pq.ParquetFile(stage / "t.parquet").metadata.num_rows == 0
        assert _footer_canaries(stage / "t.parquet") == set()


def test_a_clean_table_passes_through_without_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = pa.Table.from_pandas(pd.DataFrame({"a": [1, 2, 3]}), preserve_index=False)
    seen: list[pa.Table] = []
    real = arrow_adapter.write_table

    def spy(table: pa.Table, *args: object, **kwargs: object) -> None:
        seen.append(table)
        real(table, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(arrow_adapter, "write_table", spy)
    with _stage(tmp_path) as (txn, _stage_path):
        arrow_adapter.write_output_table(clean, txn, "t.parquet")
    assert len(seen) == 1
    assert seen[0] is clean


def test_the_schema_is_sanitized_before_the_file_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema that cannot be sanitized fails before a file exists in the stage."""
    bad = pa.schema([pa.field("x", pa.struct([pa.field("c", pa.int64())]))])
    monkeypatch.setattr(fm, "_REBUILDERS", ())
    with _stage(tmp_path) as (txn, stage):
        with pytest.raises(TypeError):
            arrow_adapter.output_parquet_writer(txn, "t.parquet", bad)
        assert [p.name for p in stage.iterdir()] == [STAGE_MARKER]  # no table file, only the proof


class _StructExtension(pa.ExtensionType):
    def __init__(self):
        super().__init__(pa.struct([("f", pa.list_(pa.int32(), 2))]), "test.fixed_list")

    def __arrow_ext_serialize__(self):
        return b""

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type, serialized):
        return cls()


def _fixed_list_column(shape, values):
    fixed = pa.list_(pa.int32(), 2)
    if shape == "fixed":
        return pa.array(values, fixed)
    if shape == "tensor":
        return pa.ExtensionArray.from_storage(
            pa.fixed_shape_tensor(pa.int32(), [2]), pa.array(values, fixed)
        )
    if shape == "null_parent":
        return pa.StructArray.from_arrays(
            [pa.array([[1, 2]] * len(values), fixed)],
            names=["f"],
            mask=pa.array([v is None for v in values]),
        )
    if shape in ("struct", "extension"):
        ext = _StructExtension()
        storage = pa.array([{"f": v} for v in values], ext.storage_type)
        return storage if shape == "struct" else pa.ExtensionArray.from_storage(ext, storage)
    if shape == "map":
        return pa.array([[("k", v)] for v in values], pa.map_(pa.string(), fixed))
    dtype = {
        "list": pa.list_(fixed),
        "large_list": pa.large_list(fixed),
        "fixed_fixed": pa.list_(fixed, 1),
    }[shape]
    return pa.array([[v] for v in values], dtype)


def _write_fixed(table, txn, method):
    if method == "whole":
        arrow_adapter.write_output_table(table, txn, "t.parquet")
    else:
        with arrow_adapter.output_parquet_writer(txn, "t.parquet", table.schema) as writer:
            if method == "batch":
                writer.write_batch(table.to_batches()[0])
            else:
                writer.write_table(table)


@pytest.mark.parametrize("method", ["whole", "batch", "table"])
@pytest.mark.parametrize(
    "shape",
    [
        "fixed",
        "struct",
        "list",
        "map",
        "null_parent",
        "tensor",
        "extension",
        "large_list",
        "fixed_fixed",
    ],
)
@pytest.mark.parametrize("nulls", [{0}, {1}, {2}, {0, 1, 2}])
def test_output_refuses_fixed_list_null(tmp_path, method, shape, nulls):
    from decoy_engine import errors

    values = [None if i in nulls else [i, i] for i in range(3)]
    table = pa.table({"x": _fixed_list_column(shape, values)})
    with _stage(tmp_path) as (txn, _), pytest.raises(errors.DecoyError) as caught:
        _write_fixed(table, txn, method)
    assert isinstance(caught.value, errors.ParquetFixedListNullError)


@pytest.mark.parametrize("method", ["whole", "batch", "table"])
@pytest.mark.parametrize("shape", ["fixed", "struct", "list", "map", "large_list", "fixed_fixed"])
@pytest.mark.parametrize("sliced", [False, True])
def test_valid_fixed_list_output(tmp_path, method, shape, sliced):
    values = [[1, 2], [3, 4]]
    arr = (
        _fixed_list_column(shape, [None, *values, None]).slice(1, 2)
        if sliced
        else _fixed_list_column(shape, values)
    )
    table = pa.table({"x": arr})
    with _stage(tmp_path) as (txn, stage):
        _write_fixed(table, txn, method)
        assert pq.read_table(stage / "t.parquet").equals(table)


def test_checked_writer_has_no_write(tmp_path):
    with (
        _stage(tmp_path) as (txn, _),
        arrow_adapter.output_parquet_writer(
            txn, "t.parquet", pa.schema([("x", pa.int32())])
        ) as writer,
    ):
        assert not hasattr(writer, "write")
