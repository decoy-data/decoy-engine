"""Shared builders for the bounded Parquet profile tests (PREFLIGHT-ARROW-PROFILE S1b).

One table is offered to the readers the bounded profile meets (local Parquet, S3, GCS, a supplied
`pa.Table`) through the one choke point `_profile_one_source`. The reference is rebuilt here from
pyarrow and pandas alone: the base reader's collect, slice, convert, and the pandas walk. It
calls no reader of the engine, so it cannot share a defect with the code under test.
"""

from __future__ import annotations

import io
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.profile._readers import ProfileSource, build_profile_source
from decoy_engine.profile._readers_resident import ResidentTableSource
from decoy_engine.profile._source import _profile_one_source
from decoy_engine.profile._types import TableProfile
from decoy_engine.profile._walk import walk_dataframe
from decoy_engine.profile.arrow import _recovery
from tests.unit.profile.test_duplicate_header_readers import _stub_cloud

READER_KINDS = ("local", "s3", "gcs", "resident")
PARQUET_KINDS = ("local", "s3", "gcs")
FILE_FORMAT = {"local": "parquet", "s3": "parquet", "gcs": "parquet", "resident": "table"}
SAFE_FAILURE = r"^bounded source profile failed \(\w+\)$"


def parquet_bytes(table: pa.Table, *, row_group_size: int | None = None) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf, row_group_size=row_group_size)
    return buf.getvalue()


def make_reader(
    kind: str,
    table: pa.Table,
    data: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ProfileSource:
    """`kind` reader over `data` (a Parquet file) or, for `resident`, over `table`."""
    if kind == "resident":
        return ResidentTableSource(table)
    if kind == "local":
        path = tmp_path / "t.parquet"
        path.write_bytes(data)
        return build_profile_source({"type": "file", "format": "parquet", "path": str(path)})
    _stub_cloud(monkeypatch, data, kind)
    descriptor: dict[str, Any] = {"type": kind, "format": "parquet", "bucket": "b"}
    descriptor["key" if kind == "s3" else "object"] = "t.parquet"
    return build_profile_source(descriptor)


def bounded_profile(
    reader: ProfileSource,
    kind: str,
    *,
    sample_rows: int = 10_000,
    declared_pk: frozenset[str] = frozenset(),
    fk_specs: dict[str, tuple[str, str]] | None = None,
    rng: random.Random | None = None,
) -> TableProfile:
    return _profile_one_source(
        reader,
        table_name="t",
        declared_pk_cols=declared_pk,
        fk_specs=fk_specs or {},
        sample_rows=sample_rows,
        residency="bounded",
        rng=rng or random.Random(0),
        source_format=FILE_FORMAT[kind],
    )


def _base_resident_frame(table: pa.Table) -> pd.DataFrame:
    """The resident reader's conversion: the whole slice, else text for the failing columns."""
    try:
        return table.to_pandas()
    except (ValueError, OverflowError):
        columns = []
        for column in table.columns:
            try:
                column.to_pandas()
            except (ValueError, OverflowError):
                column = column.cast(pa.string())
            columns.append(column)
        return pa.Table.from_arrays(columns, names=table.column_names).to_pandas()


def base_sample(kind: str, table: pa.Table, data: bytes, sample_rows: int) -> tuple[Any, ...]:
    """(frame, shape schema, total rows) as the base reader gave them."""
    if kind == "resident":
        return _base_resident_frame(table.slice(0, sample_rows)), table.schema, table.num_rows
    parquet = pq.ParquetFile(io.BytesIO(data))
    batches: list[pa.RecordBatch] = []
    gathered = 0
    for batch in parquet.iter_batches(sample_rows):
        batches.append(batch)
        gathered += batch.num_rows
        if gathered >= sample_rows:
            break
    head = pa.Table.from_batches(batches) if batches else parquet.schema_arrow.empty_table()
    return head.slice(0, sample_rows).to_pandas(), parquet.schema_arrow, parquet.metadata.num_rows


def base_profile(
    kind: str,
    table: pa.Table,
    data: bytes,
    *,
    sample_rows: int = 10_000,
    declared_pk: frozenset[str] = frozenset(),
    fk_specs: dict[str, tuple[str, str]] | None = None,
) -> TableProfile:
    """What the bounded profile gave before this row; raises where base raised."""
    frame, schema, total = base_sample(kind, table, data, sample_rows)
    profile = walk_dataframe(
        frame,
        table_name="t",
        declared_pk_cols=declared_pk,
        fk_specs=fk_specs or {},
        sample_rows=sample_rows,
        rng=random.Random(0),
        total_row_count=max(total, len(frame)),
        arrow_schema=schema,
        source_format=FILE_FORMAT[kind],
    )
    return replace(profile, row_count_exact=True)


def assert_same_profile(ours: TableProfile, oracle: TableProfile, label: str) -> None:
    """Field by field, so a failure names the column and the field."""
    assert [c.name for c in ours.columns] == [c.name for c in oracle.columns], label
    for a, b in zip(ours.columns, oracle.columns, strict=True):
        assert a == b, (
            label,
            a.name,
            [f for f in a.__dataclass_fields__ if getattr(a, f) != getattr(b, f)],
        )
    assert ours == oracle, label


def assert_matches_base(
    table: pa.Table,
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **kw: Any,
) -> bool:
    """The bounded profile equals base where base succeeds; where base raises, the bounded
    profile raises the value-free error. Returns whether base succeeded."""
    try:
        data = parquet_bytes(table) if kind != "resident" else b""
    except (pa.ArrowNotImplementedError, pa.ArrowInvalid, pa.ArrowTypeError):
        pytest.skip("parquet does not store this type")
    reader = make_reader(kind, table, data, tmp_path, monkeypatch)
    try:
        oracle = base_profile(kind, table, data, **kw)
    except Exception:
        read_back = pq.ParquetFile(io.BytesIO(data)).schema_arrow if data else table.schema
        if data and _recovery._eligible(read_back):
            # The one place a base failure may become a success: a flat date/time schema.
            assert any(c.dtype == "object" for c in bounded_profile(reader, kind, **kw).columns)
        else:
            with pytest.raises(ValueError, match=SAFE_FAILURE):
                bounded_profile(reader, kind, **kw)
        return False
    assert_same_profile(bounded_profile(reader, kind, **kw), oracle, kind)
    return True
