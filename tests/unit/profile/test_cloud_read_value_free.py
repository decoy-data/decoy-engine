"""Cloud profile reads leave value-free whatever the library says (F25 G7-1, round 3).

Each failure carries a canary data value; it must be absent from the message, `args`, `repr`,
notes, the cause chain and the log, on S3 and GCS.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._isolated_common import is_memory_failure
from decoy_engine.fileaccess import FileAccessReadError
from decoy_engine.fileaccess._errors import resurface_scrubbed
from decoy_engine.profile import _cloud_readers as cr
from decoy_engine.profile._readers import has_row_beyond
from tests.unit.profile.test_cloud_to_frame_bounded import MARKER, _run, _serve, _source

pytest.importorskip("botocore")
CANARY = MARKER.decode()


def _everything(err: BaseException) -> str:
    seen: list[str] = []
    stack: list[BaseException | None] = [err]
    done: set[int] = set()
    while stack:
        e = stack.pop()
        if e is None or id(e) in done:
            continue
        done.add(id(e))
        seen += [str(e), repr(e), repr(e.args), *getattr(e, "__notes__", [])]
        stack += [e.__cause__, e.__context__]
    return "\n".join(seen)


def _assert_free(err: BaseException, caplog: pytest.LogCaptureFixture) -> None:
    assert CANARY not in _everything(err)
    assert CANARY not in caplog.text
    assert err.__cause__ is None and err.__context__ is None


def _int_metadata_parquet() -> bytes:
    """pandas metadata asks for `int64[pyarrow]`; the column holds text with a canary and an
    OpenSSL marker, so the conversion fails with the cell in an Arrow error."""
    meta = pa.Table.from_pandas(pd.DataFrame({"t": pd.array([1], dtype="int64[pyarrow]")}))
    text = pa.array([f"digital envelope routines {CANARY}"])
    table = pa.table({"t": text}).replace_schema_metadata(meta.schema.metadata)
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("read", ["sample", "to_frame"])
def test_parquet_int_conversion_failure_is_value_free(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str, read: str
) -> None:
    _serve(monkeypatch, provider, _int_metadata_parquet())
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as info:
        _run(_source(provider, "parquet"), read)
    _assert_free(info.value, caplog)
    assert is_memory_failure(info.value)


@pytest.mark.parametrize(
    "text",
    [
        f"digital envelope routines {CANARY}",
        f"{CANARY} not able to copy ctx {CANARY}",
        f"Unknown error: Wrapping {CANARY} failed",
        f"x Wrapping {CANARY} failed digital envelope routines {CANARY}",
    ],
)
def test_resurface_text_is_fixed(text: str) -> None:
    rebuilt = resurface_scrubbed(pa.ArrowInvalid(text))
    assert rebuilt is not None and is_memory_failure(rebuilt)
    assert CANARY not in _everything(rebuilt)


def _wide_mixed_csv() -> bytes:
    """Numbers down column 0 for 512 rows, then text: past one parser chunk, so an unpinned
    inference leaves a column of mixed int and str, which Arrow refuses and names the cell."""
    cols = 1050
    head = ",".join(f"c{i}" for i in range(cols))
    rows = [",".join([str(i), str(i)] + [""] * (cols - 2)) for i in range(512)]
    rows.append(f"{CANARY},7" + "," * (cols - 2))
    return ("\n".join([head, *rows]) + "\n").encode()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_schema_mixed_types_is_text_not_a_leak(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
) -> None:
    _serve(monkeypatch, provider, _wide_mixed_csv())
    with caplog.at_level(logging.DEBUG):
        try:
            schema = _source(provider, "csv").schema()
        except Exception as exc:
            _assert_free(exc, caplog)
            raise
    assert len(schema) == 1050
    # Types are asserted, not only the column count: the mixed column is text, the integer
    # column stays an integer.
    assert schema.field("c0").type == pa.string()
    assert schema.field("c1").type == pa.int64()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_schema_conversion_failure_is_read_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
) -> None:
    # Column names that repeat make Arrow refuse the frame and name them (read_csv itself
    # mangles repeats, so this stands in for any conversion failure the library words with data).
    broken = pd.DataFrame([[1, 2]], columns=[CANARY, CANARY])
    with pytest.raises(ValueError) as raw:
        pa.Table.from_pandas(broken, preserve_index=False)
    assert CANARY in str(raw.value)  # non-vacuity: the library text does carry the value
    monkeypatch.setattr(cr, "_csv_sample_from_window", lambda *a, **k: broken)
    _serve(monkeypatch, provider, b"a\n1\n")
    with caplog.at_level(logging.DEBUG), pytest.raises(FileAccessReadError) as info:
        _source(provider, "csv").schema()
    _assert_free(info.value, caplog)


_BAD_UTF8 = b"a,t\n1," + MARKER + b"\xff\n2,x\n"


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("read", ["sample", "schema"])
def test_csv_decode_error_holds_no_input_bytes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str, read: str
) -> None:
    _serve(monkeypatch, provider, _BAD_UTF8)
    source: Any = _source(provider, "csv")
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as info:
        source.sample_frame(1) if read == "sample" else source.schema()
    assert isinstance(info.value, UnicodeDecodeError)
    _assert_free(info.value, caplog)


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_proof_read_sees_a_row_that_does_not_decode(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """Row 3 holds the bad bytes and rows 1 and 2 decode: the proof read answers True."""
    _serve(monkeypatch, provider, b"a,t\n1,x\n2,y\n3,z\xff\n")
    source: Any = _source(provider, "csv")
    with pytest.raises(UnicodeDecodeError):  # non-vacuity: reading row 3 does fail to decode
        source.sample_frame(3)
    assert has_row_beyond(source.sample_frame, 2) is True


_TORN = "TORNCANARY"
_ROW_BYTES = 100_000


def _torn_csv() -> bytes:
    """Ten whole 100 kB rows, then an eleventh that starts before the 1 MiB mark and ends
    after it, so the first window cuts it. Its first cell is text in an integer column."""
    filler = "y" * (_ROW_BYTES - 8)
    rows = [f"{i},{filler}" for i in range(10)]
    rows.append(f"{_TORN},{filler}")
    rows.append(f"11,{filler}")
    data = ("a,b\n" + "\n".join(rows) + "\n").encode()
    assert len(data) > cr._CSV_SAMPLE_WINDOW_BYTES > data.index(_TORN.encode()) + 10
    return data


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_a_window_cut_mid_row_never_holds_the_partial_row(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
) -> None:
    ledger, _ = _serve(monkeypatch, provider, _torn_csv())
    source: Any = _source(provider, "csv")
    with caplog.at_level(logging.DEBUG):
        schema = source.schema()
        sample = source.sample_frame(5)
    assert next(r["range"] for r in ledger.data_requests).startswith("bytes=0-")
    assert schema.names == ["a", "b"]
    assert schema.field("a").type == pa.int64()  # the cut fragment is not a row of the sample
    assert sample.columns.tolist() == ["a", "b"] and len(sample) == 5
    assert _TORN not in "".join(map(str, sample["a"])) and _TORN not in caplog.text
