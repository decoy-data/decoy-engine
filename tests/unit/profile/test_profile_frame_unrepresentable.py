"""DATE-SHIFT-TYPED S1 round 3: a source value pandas cannot hold never reaches a profile frame.

Profiling runs before any route, so every reader that builds a profile frame must neither raise
pandas' value-quoting error nor carry the value (as text) into a statistic or report.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.profile import _cloud_readers
from decoy_engine.profile.arrow import profile_frame
from decoy_engine.profiling import profile_document, scan_set_to_dict, scan_sources

PAST = 2932897  # day number of 10000-01-01, one past the last day pandas can hold
LITERALS = ("10000-01", str(PAST))


def _past_dates(n: int = 1) -> pa.Array:
    return pa.array([PAST] * n, pa.int32()).cast(pa.date32())


def _no_literal(text: str) -> None:
    for literal in LITERALS:
        assert literal not in text, text[:300]


def test_a_past_9999_date_converts_to_a_value_free_column() -> None:
    table = pa.table({"d": _past_dates(3), "n": pa.array([1, 2, 3])})
    frame = profile_frame(table)
    assert list(frame.columns) == ["d", "n"]
    assert frame["n"].tolist() == [1, 2, 3]
    _no_literal(repr(frame.to_dict("list")))
    assert frame["d"].isna().all()


def test_in_range_dates_around_a_past_date_keep_their_values() -> None:
    days = pa.array([0, PAST, 1], pa.int32()).cast(pa.date32())
    frame = profile_frame(pa.table({"d": days}))
    assert frame["d"].notna().tolist() == [True, False, True]


def test_schema_metadata_survives_the_fallback() -> None:
    """A stored pandas index is metadata: the fallback must not turn it into a data column."""
    stored = pd.DataFrame({"stored_id": [1, 2], "d": [None, None]}).set_index("stored_id")
    base = pa.Table.from_pandas(stored)
    index = base.schema.get_field_index("d")
    good = base.set_column(index, "d", pa.array([0, 1], pa.int32()).cast(pa.date32()))
    bad = base.set_column(index, "d", pa.array([0, PAST], pa.int32()).cast(pa.date32()))
    assert list(profile_frame(bad).columns) == list(profile_frame(good).columns) == ["d"]


def _parquet_bytes(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def test_the_s3_full_reader_does_not_raise_on_a_past_date(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _parquet_bytes(pa.table({"d": _past_dates()}))
    monkeypatch.setattr(_cloud_readers, "_s3_for", lambda _d: object())
    monkeypatch.setattr(_cloud_readers, "_s3_full", lambda *_a: data)
    source = _cloud_readers.S3ParquetSource({"bucket": "b", "key": "k"})
    frame = source.to_frame()
    _no_literal(repr(frame.to_dict("list")))


def test_the_gcs_full_reader_does_not_raise_on_a_past_date(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _parquet_bytes(pa.table({"d": _past_dates()}))

    @contextmanager
    def client() -> Any:
        yield object()

    monkeypatch.setattr(_cloud_readers._clients, "gcs_client", client)
    monkeypatch.setattr(_cloud_readers, "_gcs_blob", lambda *_a: object())
    monkeypatch.setattr(_cloud_readers._clients, "gcs_download", lambda *_a, **_k: data)
    frame = _cloud_readers.GcsParquetSource({"bucket": "b", "object": "o"}).to_frame()
    _no_literal(repr(frame.to_dict("list")))


@pytest.mark.parametrize("rows", [1, 20])
def test_a_scan_of_past_dates_carries_the_value_nowhere(tmp_path: Path, rows: int) -> None:
    """Singleton and repeated values: a repeated one used to reach mode, top values and bins."""
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"d": _past_dates(rows), "n": pa.array(range(rows))}), path)
    descriptor = {"type": "file", "format": "parquet", "path": str(path)}
    scan = scan_sources({"t": descriptor})
    _no_literal(json.dumps(scan_set_to_dict(scan, detail=True), default=str))
    for table in scan.tables:
        _no_literal(json.dumps(table.profile.to_dict(), default=str))
        _no_literal(json.dumps(profile_document(table.profile), default=str))
