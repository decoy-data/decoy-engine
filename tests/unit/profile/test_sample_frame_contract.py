"""E0 (PROFILE-SAMPLE-LABELS): `ProfileSource.sample_frame(n)` returns exactly `n` rows when the
source holds that many, and fewer only when the read reached the end of the source.

AT-0a (every reader), AT-0c (giant row, request bound, malformed object), AT-0d (planner
`profile_source` on a wide cloud CSV). `READER_MATRIX` is the set the coverage sentry in
`tests/sentry/profiling/test_profile_source_contract_coverage.py` compares against the reader
classes defined under `decoy_engine.profile` and `decoy_engine.profiling`.
Do not skip a case or loosen a bound to make one pass.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.profile._readers import ProfileSource, build_profile_source
from tests.unit.profile.test_duplicate_header_readers import _FakeBlob, _FakeGcsClient

PAD = "x" * 290
MIB = 1 << 20
BUCKET = "bkt-test"


def _csv_bytes(rows: int) -> bytes:
    """`rows` wide rows (about 300 bytes each); `id` is unique in the first 10,000, then repeats."""
    lines = ["id,pad"] + [f"{i % 10_000},{PAD}" for i in range(rows)]
    return ("\n".join(lines) + "\n").encode()


@dataclass
class Env:
    tmp_path: Path
    monkeypatch: pytest.MonkeyPatch
    s3: Any = None
    gcs_log: list[str] = field(default_factory=list)


class _CountingGcs(_FakeGcsClient):
    """Logs one `open` and one `close` per client block, so a client opened per window shows."""

    def __init__(self, data: bytes, log: list[str]) -> None:
        super().__init__(data)
        self._log = log

    def __enter__(self) -> _CountingGcs:
        self._log.append("open")
        return self

    def __exit__(self, *exc: Any) -> None:
        self._log.append("close")


def _gcs(env: Env, data: bytes) -> None:
    storage = pytest.importorskip("google.cloud.storage")
    env.monkeypatch.setattr(storage, "Client", lambda *a, **k: _CountingGcs(data, env.gcs_log))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    boto3 = pytest.importorskip("boto3")
    from moto import mock_aws

    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield Env(tmp_path, monkeypatch, client)


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({"id": [i % 10_000 for i in range(rows)], "pad": [PAD] * rows})


def _parquet_bytes(rows: int) -> bytes:
    buf = io.BytesIO()
    table = pa.Table.from_pandas(_frame(rows), preserve_index=False)
    pq.write_table(table, buf, row_group_size=2_000)
    return buf.getvalue()


def _local_csv(env: Env, rows: int) -> ProfileSource:
    path = env.tmp_path / "t.csv"
    path.write_bytes(_csv_bytes(rows))
    return build_profile_source(
        {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    )


def _local_parquet(env: Env, rows: int) -> ProfileSource:
    path = env.tmp_path / "t.parquet"
    path.write_bytes(_parquet_bytes(rows))
    return build_profile_source({"type": "file", "format": "parquet", "path": str(path)})


def _fixed_width(env: Env, rows: int) -> ProfileSource:
    from decoy_engine.config._fixed_width import FixedWidthLayout
    from decoy_engine.profile._readers import FixedWidthFileSource

    path = env.tmp_path / "t.txt"
    path.write_text("".join(f"{i % 10_000:<6}{PAD}\n" for i in range(rows)))
    layout = FixedWidthLayout.model_validate(
        {
            "columns": [
                {"name": "id", "start": 0, "width": 6},
                {"name": "pad", "start": 6, "width": len(PAD)},
            ]
        }
    )
    return FixedWidthFileSource(path, layout)


def _resident(env: Env, rows: int) -> ProfileSource:
    from decoy_engine.profile._readers_resident import ResidentTableSource

    return ResidentTableSource(pa.Table.from_pandas(_frame(rows), preserve_index=False))


def _s3(env: Env, data: bytes, fmt: str) -> ProfileSource:
    env.s3.put_object(Bucket=BUCKET, Key=f"k.{fmt}", Body=data)
    descriptor = {"type": "s3", "format": fmt, "bucket": BUCKET, "key": f"k.{fmt}"}
    return build_profile_source({**descriptor, "region": "us-east-1"})


def _gcs_source(env: Env, data: bytes, fmt: str) -> ProfileSource:
    _gcs(env, data)
    return build_profile_source({"type": "gcs", "format": fmt, "bucket": BUCKET, "object": "o"})


_CLOUD = "decoy_engine.profile._cloud_readers"
READER_MATRIX: dict[str, Callable[[Env, int], ProfileSource]] = {
    "decoy_engine.profile._readers_csv.CsvFileSource": _local_csv,
    "decoy_engine.profile._readers.ParquetFileSource": _local_parquet,
    "decoy_engine.profile._readers.FixedWidthFileSource": _fixed_width,
    "decoy_engine.profile._readers_resident.ResidentTableSource": _resident,
    f"{_CLOUD}.S3CsvSource": lambda e, n: _s3(e, _csv_bytes(n), "csv"),
    f"{_CLOUD}.S3ParquetSource": lambda e, n: _s3(e, _parquet_bytes(n), "parquet"),
    f"{_CLOUD}.GcsCsvSource": lambda e, n: _gcs_source(e, _csv_bytes(n), "csv"),
    f"{_CLOUD}.GcsParquetSource": lambda e, n: _gcs_source(e, _parquet_bytes(n), "parquet"),
}
READERS = sorted(READER_MATRIX)


@pytest.mark.parametrize("reader", READERS)
def test_at0a_short_source_returns_every_row(env: Env, reader: str) -> None:
    assert len(READER_MATRIX[reader](env, 3).sample_frame(5)) == 3


@pytest.mark.parametrize("reader", READERS)
def test_at0a_wide_source_returns_exactly_the_rows_asked_for(env: Env, reader: str) -> None:
    source = READER_MATRIX[reader](env, 25_000)
    assert len(source.sample_frame(10_000)) == 10_000
    assert len(source.sample_frame(10_001)) == 10_001


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at0a_quoted_field_open_across_two_window_edges(env: Env, kind: str) -> None:
    head = "id,note\n"
    rows: list[str] = []
    while len(head) + sum(len(r) for r in rows) < MIB - 60:
        rows.append(f"{len(rows)},{PAD}\n")
    big = '"' + ("a" * 99 + "\n") * 26_000 + '"'  # starts before 1 MiB, ends after 3 MiB
    tail = [f"{len(rows) + 1 + i},{PAD}\n" for i in range(5)]
    data = (head + "".join(rows) + f"{len(rows)},{big}\n" + "".join(tail)).encode()
    assert len(data) > 3 * MIB
    asked = len(rows) + 3
    source = _s3(env, data, "csv") if kind == "s3" else _gcs_source(env, data, "csv")
    frame = source.sample_frame(asked)
    assert len(frame) == asked
    assert len(frame["note"].iloc[len(rows)]) == len(big) - 2
    assert frame["id"].tolist() == list(range(asked))
    if kind == "gcs":
        assert env.gcs_log == ["open", "close"]


# ---------------------------------------------------------------- AT-0c


Tamper = Callable[[int, bytes], bytes]


class _CountingS3:
    """A fake S3 client that counts every request and the bytes returned."""

    def __init__(self, data: bytes, tamper: Tamper | None = None) -> None:
        self._data = data
        self._tamper = tamper
        self.requests = 0
        self.bytes_read = 0

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.requests += 1
        return {"ContentLength": len(self._data)}

    def get_object(self, Bucket: str, Key: str, Range: str | None = None) -> dict[str, Any]:
        self.requests += 1
        if Range is None:
            return {"Body": io.BytesIO(self._data)}
        match = re.match(r"bytes=(\d+)-(\d+)", Range)
        assert match
        chunk = self._data[int(match[1]) : int(match[2]) + 1]
        if self._tamper:
            chunk = self._tamper(self.requests - 1, chunk)
        self.bytes_read += len(chunk)
        return {"Body": io.BytesIO(chunk)}


class _Counts:
    """What a stubbed cloud CSV reader asked its backend for: requests and bytes fetched."""

    def __init__(self) -> None:
        self.requests = 0
        self.bytes_read = 0


def _stub(
    env: Env, kind: str, data: bytes, tamper: Tamper | None = None
) -> tuple[ProfileSource, _Counts]:
    from decoy_engine.profile import _cloud_readers

    counts = _Counts()
    if kind == "s3":
        client = _CountingS3(data, tamper)
        env.monkeypatch.setattr(_cloud_readers._clients, "s3_client", lambda **_kw: client)
        source = build_profile_source({"type": "s3", "format": "csv", "bucket": BUCKET, "key": "k"})
        counts = client  # type: ignore[assignment]
        return source, counts

    storage = pytest.importorskip("google.cloud.storage")

    class _Blob(_FakeBlob):
        def download_as_bytes(
            self, start: int | None = None, end: int | None = None, **kw: Any
        ) -> bytes:
            counts.requests += 1
            chunk = super().download_as_bytes(start, end)
            if tamper:
                chunk = tamper(counts.requests, chunk)
            counts.bytes_read += len(chunk)
            return chunk

    class _Client(_CountingGcs):
        def __init__(self) -> None:
            super().__init__(data, env.gcs_log)
            self._blob = _Blob(data)

    env.monkeypatch.setattr(storage, "Client", lambda *a, **k: _Client())
    source = build_profile_source({"type": "gcs", "format": "csv", "bucket": BUCKET, "object": "o"})
    return source, counts


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at0c_giant_row_stays_within_the_request_and_byte_bound(env: Env, kind: str) -> None:
    data = b"a,b\n1," + b"x" * (3 * MIB) + b"\n" + b"".join(b"%d,y\n" % i for i in range(2, 7))
    source, counts = _stub(env, kind, data)
    assert len(source.sample_frame(4)) == 4
    assert counts.requests <= math.ceil(math.log2(len(data) / MIB)) + 2
    assert counts.bytes_read <= len(data)


# Ranged responses that break the byte count. The index counts ranged reads from 1; the S3 fake
# counts its size lookup as request 1, so it passes `requests - 1`.
TAMPERS: dict[str, Tamper] = {
    "short_first_window": lambda i, b: b[:-1] if i <= 1 else b,
    "empty_first_window": lambda i, b: b"" if i <= 1 else b,
    "short_later_window": lambda i, b: b[:-1] if i > 1 else b,
    "empty_after_valid_prefix": lambda i, b: b"" if i > 1 else b,
}


@pytest.mark.timeout(60)
@pytest.mark.parametrize("tamper", sorted(TAMPERS))
@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at0c_a_short_ranged_response_is_source_changed(env: Env, kind: str, tamper: str) -> None:
    from decoy_engine.sdk import PermanentError

    data = b"a,b\n1," + b"x" * (3 * MIB) + b"\n" + b"".join(b"%d,y\n" % i for i in range(2, 7))
    source, _ = _stub(env, kind, data, TAMPERS[tamper])
    with pytest.raises(PermanentError) as info:
        source.sample_frame(4)
    assert info.value.kind == "source_changed"
    assert "x" * 20 not in str(info.value)


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at0c_malformed_whole_object_raises_parser_error(env: Env, kind: str) -> None:
    source, _ = _stub(env, kind, b"a,b\n1,2\n3,4,5,6\n")
    with pytest.raises(pd.errors.ParserError):
        source.sample_frame(10)


# ---------------------------------------------------------------- AT-0d


def _profile_config(kind: str) -> dict[str, Any]:
    source: dict[str, Any] = {"type": kind, "format": "csv", "bucket": BUCKET}
    source["key" if kind == "s3" else "object"] = "wide.csv"
    if kind == "s3":
        source["region"] = "us-east-1"
    return {
        "version": 2,
        "global_settings": {"seed": 0},
        "sources": {"t": source},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "id", "strategy": "redact"},
                    {"name": "pad", "strategy": "redact"},
                ],
            }
        ],
        "targets": {"t": {"type": "file", "format": "csv", "path": "/tmp/out.csv"}},
        "relationships": [],
        "namespaces": {},
    }


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at0d_profile_source_sees_the_requested_rows(env: Env, kind: str) -> None:
    from decoy_engine.profile import profile_source

    data = _csv_bytes(25_000)
    if kind == "s3":
        env.s3.put_object(Bucket=BUCKET, Key="wide.csv", Body=data)
    else:
        _gcs(env, data)
    table = profile_source(_profile_config(kind)).tables[0]
    assert all(c.sampled and not c.is_candidate_key_sampled for c in table.columns)
    assert {c.name: c.distinct_count for c in table.columns}["id"] == 10_000
