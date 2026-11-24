"""Cloud profile reads stay bounded and pinned to one object version (F25 G7-1).

`to_frame` on an S3 or GCS object streams it in ranged pieces of at most 8 MiB, each pinned
to the version read with the size (S3 ETag, GCS generation). A GCS answer that ignores the
range is closed before its body is read. A CSV sample reads at most 64 MiB in total.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.errors import ConnectorError
from decoy_engine.profile import _cloud_readers as cr
from tests._cloud_fakes import (
    FakeGcsSession,
    FakeS3,
    GcsObject,
    Ledger,
    MiB,
    install_gcs,
    install_s3,
)

pytest.importorskip("botocore")
MARKER = b"zz_marker"
PIECE = 8 * MiB


def _desc(provider: str, fmt: str) -> dict[str, Any]:
    if provider == "s3":
        return {"bucket": "b", "key": "zz_marker", "format": fmt}
    return {"bucket": "b", "object": "zz_marker", "format": fmt}


def _source(provider: str, fmt: str) -> Any:
    if provider == "s3":
        return cr.build_s3_profile_source(_desc(provider, fmt))
    return cr.build_gcs_profile_source(_desc(provider, fmt))


def _serve(
    monkeypatch: pytest.MonkeyPatch, provider: str, data: bytes, **kw: Any
) -> tuple[Ledger, Any]:
    if provider == "s3":
        fake = install_s3(monkeypatch, FakeS3(data, **kw))
        return fake.ledger, fake
    pytest.importorskip("google.cloud.storage")
    generation = kw.pop("generation", 7)
    session = install_gcs(monkeypatch, FakeGcsSession(GcsObject(data, generation), **kw))
    return session.ledger, session


def _csv_bytes(total: int) -> bytes:
    row = b"%08d," + MARKER + b"," + b"y" * 80 + b"\n"
    count = total // len(row % 0)
    return b"id,tag,payload\n" + b"".join(row % i for i in range(count))


def _parquet_bytes(total: int) -> bytes:
    rows = total // 1024
    rng = np.random.default_rng(0)
    blobs = [rng.bytes(1016) for _ in range(rows)]
    table = pa.table({"id": pa.array(range(rows), pa.int64()), "blob": pa.array(blobs)})
    sink = io.BytesIO()
    # About 4 MiB row groups with one column chunk each under the 8 MiB piece.
    pq.write_table(table, sink, row_group_size=4096, compression="none", use_dictionary=False)
    return sink.getvalue()


def _value_free(err: BaseException) -> None:
    assert MARKER.decode() not in str(err)
    assert err.__cause__ is None and err.__context__ is None


@pytest.fixture(scope="module")
def big_csv() -> bytes:
    return _csv_bytes(64 * MiB)


@pytest.fixture(scope="module")
def big_parquet() -> bytes:
    return _parquet_bytes(64 * MiB)


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("fmt", ["csv", "parquet"])
def test_to_frame_transport_bounded(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    fmt: str,
    big_csv: bytes,
    big_parquet: bytes,
) -> None:
    data = big_csv if fmt == "csv" else big_parquet
    ledger, _ = _serve(monkeypatch, provider, data)
    frame = _source(provider, fmt).to_frame()

    if fmt == "csv":
        expected_rows = data.count(b"\n") - 1
    else:
        expected_rows = pq.ParquetFile(io.BytesIO(data)).metadata.num_rows
    assert len(frame) == expected_rows
    assert ledger.responses and max(ledger.responses) <= PIECE
    assert ledger.max_held <= PIECE
    assert ledger.unsized_reads == 0 and ledger.eager_reads == 0
    assert ledger.all_closed()


def _small_parquet() -> bytes:
    sink = io.BytesIO()
    pq.write_table(pa.table({"a": [1, 2, 3], "t": ["zz_marker"] * 3}), sink)
    return sink.getvalue()


_SMALL_CSV = b"a,t\n1,zz_marker\n2,zz_marker\n3,zz_marker\n"


def _gcs_read(kind: str) -> Any:
    if kind == "connector_open":
        from decoy_engine.connectors.gcs import GCSConfig, GCSFileSource

        return b"".join(GCSFileSource(GCSConfig(bucket="b")).open("zz_marker"))
    fmt = "parquet" if kind == "parquet_to_frame" else "csv"
    source = cr.build_gcs_profile_source(_desc("gcs", fmt))
    return source.sample_frame(2) if kind == "csv_sample" else source.to_frame()


_GCS_READS = ["csv_to_frame", "parquet_to_frame", "csv_sample", "connector_open"]


@pytest.mark.parametrize("kind", _GCS_READS)
def test_gcs_ignored_range_closes_before_body(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    data = _small_parquet() if kind == "parquet_to_frame" else _SMALL_CSV
    ledger, _ = _serve(monkeypatch, "gcs", data, ignore_range=True)
    with pytest.raises(ConnectorError) as info:
        _gcs_read(kind)
    _value_free(info.value)
    assert ledger.data_requests, "no media GET was made"
    assert ledger.body_bytes_read == 0 and ledger.eager_reads == 0
    assert ledger.all_closed()


@pytest.mark.parametrize("kind", _GCS_READS)
def test_gcs_ranged_control_reads_exact_bytes(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    data = _small_parquet() if kind == "parquet_to_frame" else _SMALL_CSV
    ledger, _ = _serve(monkeypatch, "gcs", data)
    got = _gcs_read(kind)
    if kind == "connector_open":
        assert got == data
    elif kind == "parquet_to_frame":
        pd.testing.assert_frame_equal(got, pd.read_parquet(io.BytesIO(data)))
    else:
        expected = pd.read_csv(io.BytesIO(data))
        pd.testing.assert_frame_equal(got, expected.head(2) if kind == "csv_sample" else expected)
    assert ledger.body_bytes_read == ledger.fetched
    assert ledger.eager_reads == 0 and ledger.all_closed()
    assert all(r["stream"] is True for r in ledger.data_requests)


def _parity_frames() -> dict[str, pd.DataFrame]:
    tz = pd.date_range("2026-01-01", periods=3, freq="h", tz="America/Chicago")
    return {
        "empty": pd.DataFrame({"a": pd.Series([], dtype="int64"), "b": pd.Series([], dtype=str)}),
        "index": pd.DataFrame({"v": [1.5, 2.5, 3.5]}, index=pd.Index(["x", "y", "z"], name="k")),
        "categorical": pd.DataFrame({"c": pd.Categorical(["lo", "hi", "lo"])}),
        "tz": pd.DataFrame({"ts": tz, "n": [1, 2, 3]}),
    }


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("case", sorted(_parity_frames()))
def test_parquet_to_frame_parity(monkeypatch: pytest.MonkeyPatch, provider: str, case: str) -> None:
    sink = io.BytesIO()
    _parity_frames()[case].to_parquet(sink)
    data = sink.getvalue()
    _serve(monkeypatch, provider, data)
    got = _source(provider, "parquet").to_frame()
    pd.testing.assert_frame_equal(got, pd.read_parquet(io.BytesIO(data)))


@pytest.mark.parametrize("read", ["parquet_sample", "csv_to_frame"])
def test_range_reader_refuses_short_read(monkeypatch: pytest.MonkeyPatch, read: str) -> None:
    data = _small_parquet() if read == "parquet_sample" else _SMALL_CSV
    _serve(monkeypatch, "s3", data, short=True)
    source = _source("s3", "parquet" if read == "parquet_sample" else "csv")
    with pytest.raises(ConnectorError) as info:
        source.sample_frame(2) if read == "parquet_sample" else source.to_frame()
    assert info.value.kind == "source_changed"
    _value_free(info.value)


@pytest.mark.parametrize("piece", [3, 1 << 20])
def test_range_reader_short_fetch_is_source_changed(piece: int) -> None:
    reader = cr._RangeFileReader(10, lambda start, end: bytes(end - start), "S3", piece=piece)
    with pytest.raises(ConnectorError) as info:
        reader.read(10)
    assert info.value.kind == "source_changed"


_READS = ["row_count", "sample", "to_frame"]


def _run(source: Any, read: str) -> Any:
    if read == "row_count":
        return source.row_count()
    return source.sample_frame(2) if read == "sample" else source.to_frame()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("fmt", ["csv", "parquet"])
@pytest.mark.parametrize("read", _READS)
def test_ranges_pinned_to_version(
    monkeypatch: pytest.MonkeyPatch, provider: str, fmt: str, read: str
) -> None:
    data = _small_parquet() if fmt == "parquet" else _SMALL_CSV
    ledger, _ = _serve(monkeypatch, provider, data)
    _run(_source(provider, fmt), read)
    pin = '"v1"' if provider == "s3" else "7"
    assert ledger.data_requests
    assert [r["pin"] for r in ledger.data_requests] == [pin] * len(ledger.data_requests)


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("fmt", ["csv", "parquet"])
@pytest.mark.parametrize("read", _READS)
def test_missing_version_refuses_before_data(
    monkeypatch: pytest.MonkeyPatch, provider: str, fmt: str, read: str
) -> None:
    data = _small_parquet() if fmt == "parquet" else _SMALL_CSV
    kw = {"etag": None} if provider == "s3" else {"generation": None}
    ledger, _ = _serve(monkeypatch, provider, data, **kw)
    with pytest.raises(ConnectorError) as info:
        _run(_source(provider, fmt), read)
    assert info.value.kind == "source_changed"
    _value_free(info.value)
    assert ledger.data_requests == []


@pytest.mark.parametrize("generation", [7, None])
def test_gcs_cached_size_still_reloads_generation(
    monkeypatch: pytest.MonkeyPatch, generation: int | None
) -> None:
    ledger, _ = _serve(monkeypatch, "gcs", _SMALL_CSV, generation=generation)
    real_blob = cr._gcs_blob

    def cached(descriptor: dict[str, Any], client: Any) -> Any:
        blob = real_blob(descriptor, client)
        blob._properties["size"] = str(len(_SMALL_CSV))
        return blob

    monkeypatch.setattr(cr, "_gcs_blob", cached)
    source = _source("gcs", "csv")
    if generation is None:
        with pytest.raises(ConnectorError) as info:
            source.to_frame()
        assert info.value.kind == "source_changed"
        assert ledger.data_requests == []
    else:
        assert len(source.to_frame()) == 3
        assert {r["pin"] for r in ledger.data_requests} == {"7"}
    assert any(r["kind"] == "metadata" for r in ledger.requests)


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_changed_object_is_source_changed(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    ledger, _ = _serve(monkeypatch, provider, _parquet_bytes(4 * MiB), change_after=1)
    with pytest.raises(ConnectorError) as info:
        _source(provider, "parquet").to_frame()
    assert info.value.kind == "source_changed"
    _value_free(info.value)
    assert len(ledger.data_requests) >= 2 and ledger.all_closed()


def _stream_error(provider: str) -> BaseException:
    if provider == "s3":
        from botocore.exceptions import ReadTimeoutError

        return ReadTimeoutError(endpoint_url="https://zz_marker.invalid/")
    from urllib3.exceptions import ReadTimeoutError

    return ReadTimeoutError(None, "https://zz_marker.invalid/", "zz_marker")


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_to_frame_stream_error_translated(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    from decoy_engine.connectors import _clients

    monkeypatch.setattr(_clients, "GCS_RETRY_TOTAL_S", 0.01)
    data = _csv_bytes(3 * MiB)
    ledger, _ = _serve(
        monkeypatch, provider, data, fail_at=2 * MiB + 17, error=_stream_error(provider)
    )
    with pytest.raises(ConnectorError) as info:
        _source(provider, "csv").to_frame()
    assert info.value.kind == "transient"
    _value_free(info.value)
    assert ledger.fetched >= 2 * MiB and ledger.all_closed()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_sample_total_capped(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    data = b"a\n" + MARKER * (80 * MiB // len(MARKER)) + b"\n1\n2\n"
    ledger, _ = _serve(monkeypatch, provider, data)
    with pytest.raises(ConnectorError) as info:
        _source(provider, "csv").sample_frame(2)
    assert getattr(info.value, "code", None) == reasons.connector.SAMPLE_WINDOW_EXCEEDED
    _value_free(info.value)
    assert ledger.fetched <= 64 * MiB
    assert max(ledger.responses) <= PIECE and ledger.all_closed()
