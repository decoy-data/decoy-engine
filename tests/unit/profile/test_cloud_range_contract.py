"""A ranged cloud answer is checked before its body is read (F25 G7-1, case 2b).

The fakes answer a range request as a misbehaving store would: a 200 with the whole object, a
206 naming other bytes, a 206 with another total, a 206 with another length, and a 200 whose
bytes and headers are exact (only the status breaks the 206 contract, RFC 9110 15.3.7). Each is
refused as kind `unexpected` with zero body bytes read, on S3 and GCS, for every read.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.errors import ConnectorError
from tests._cloud_fakes import RANGE_MODES
from tests.unit.profile.test_cloud_to_frame_bounded import (
    _SMALL_CSV,
    _serve,
    _small_parquet,
    _source,
    _value_free,
)

pytest.importorskip("botocore")

_READS = ["to_frame", "sample", "schema"]


def _read(source: Any, read: str) -> Any:
    if read == "schema":
        return source.schema()
    return source.to_frame() if read == "to_frame" else source.sample_frame(2)


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("fmt", ["csv", "parquet"])
@pytest.mark.parametrize("read", _READS)
@pytest.mark.parametrize("mode", RANGE_MODES)
def test_a_broken_range_answer_is_refused_before_its_body(
    monkeypatch: pytest.MonkeyPatch, provider: str, fmt: str, read: str, mode: str
) -> None:
    data = _small_parquet() if fmt == "parquet" else _SMALL_CSV
    ledger, _ = _serve(monkeypatch, provider, data, range_mode=mode)
    with pytest.raises(ConnectorError) as info:
        _read(_source(provider, fmt), read)
    assert info.value.kind == "unexpected"
    _value_free(info.value)
    assert ledger.data_requests, "the read must have asked for a range"
    assert ledger.body_bytes_read == 0
    assert ledger.unsized_reads == 0 and ledger.eager_reads == 0
    assert ledger.all_closed()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("fmt", ["csv", "parquet"])
@pytest.mark.parametrize("read", _READS)
def test_an_exact_206_answer_is_read(
    monkeypatch: pytest.MonkeyPatch, provider: str, fmt: str, read: str
) -> None:
    """The control: the same reads over an honest store complete, so the refusals above come
    from the answer and not from the reader."""
    data = _small_parquet() if fmt == "parquet" else _SMALL_CSV
    ledger, _ = _serve(monkeypatch, provider, data)
    _read(_source(provider, fmt), read)
    assert ledger.body_bytes_read > 0 and ledger.all_closed()
