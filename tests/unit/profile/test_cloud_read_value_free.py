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
    cols = 1050
    head = ",".join(f"c{i}" for i in range(cols))
    rows = [",".join(["1"] * cols) for _ in range(512)]
    rows.append(",".join(["1"] * (cols - 1) + [CANARY]))
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


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_schema_conversion_failure_is_read_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
) -> None:
    mixed = pd.DataFrame({"a": pd.Series([1, CANARY], dtype=object)})
    monkeypatch.setattr(cr, "_csv_sample_from_window", lambda *a, **k: mixed)
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
