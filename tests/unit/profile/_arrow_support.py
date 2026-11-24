"""Shared builders for the bounded Arrow profile tests (PREFLIGHT-ARROW-PROFILE S1b).

One table is offered to the four readers that hold Arrow (local Parquet, S3, GCS, a supplied
`pa.Table`), profiled through the one bounded choke point `_profile_one_source`, and compared
with `walk_dataframe` over the same reader's `sample_frame`, the pandas oracle, unchanged.
"""

from __future__ import annotations

import io
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.profile._readers import ProfileSource, build_profile_source
from decoy_engine.profile._readers_resident import ResidentTableSource
from decoy_engine.profile._source import _profile_one_source
from decoy_engine.profile._types import TableProfile
from decoy_engine.profile._walk import walk_dataframe
from tests.unit.profile.test_duplicate_header_readers import _stub_cloud

READER_KINDS = ("local", "s3", "gcs", "resident")
FILE_FORMAT = {"local": "parquet", "s3": "parquet", "gcs": "parquet", "resident": "table"}


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


def oracle_profile(
    reader: ProfileSource,
    kind: str,
    *,
    sample_rows: int = 10_000,
    declared_pk: frozenset[str] = frozenset(),
    fk_specs: dict[str, tuple[str, str]] | None = None,
) -> TableProfile:
    """What the bounded profile was before this row: `walk_dataframe` over `sample_frame`."""
    frame = reader.sample_frame(sample_rows)
    total = max(reader.row_count().value, len(frame))
    table = walk_dataframe(
        frame,
        table_name="t",
        declared_pk_cols=declared_pk,
        fk_specs=fk_specs or {},
        sample_rows=sample_rows,
        rng=random.Random(0),
        total_row_count=total,
        arrow_schema=reader.schema(),
        source_format=FILE_FORMAT[kind],
    )
    return replace(table, row_count_exact=reader.row_count().exact)


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
