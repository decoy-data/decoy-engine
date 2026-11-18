"""F02-E2: a content digest on writes (AT-E2-1 to AT-E2-4, AT-E2-7, AT-E2-9).

S3 and GCS use local stand-ins. The GCS cleanup cells raise the library's own
``DataCorruption`` under the real ``_clients._TranslatingFile`` wrapper, so the cleanup
cannot sit in the sink.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Any

import pytest

botocore_exc = pytest.importorskip("botocore.exceptions")
gax_exc = pytest.importorskip("google.api_core.exceptions")
gcs_exc = pytest.importorskip("google.cloud.storage.exceptions")

from decoy_engine.connectors import _clients  # noqa: E402
from decoy_engine.connectors._digest import DigestingChunks  # noqa: E402
from decoy_engine.connectors.gcs import GCSConfig, GCSFileSink, GCSFileSource  # noqa: E402
from decoy_engine.connectors.s3 import S3Config, S3FileSink  # noqa: E402
from decoy_engine.errors import ConnectorError  # noqa: E402
from decoy_engine.sdk import PermanentError, WriteResult  # noqa: E402

CHUNKS = [b"alpha", b"", b"beta" * 3]
EXPECTED = hashlib.sha256(b"".join(CHUNKS)).hexdigest()
MARKER = "zz_marker_bkt zz_marker_key"


# ----- AT-E2-1: both first-party sinks report the digest ------------------------------


class _S3Recorder:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    def put_object(self, **kw: Any) -> dict:
        self.bodies.append(kw["Body"])
        return {}


def test_s3_sink_reports_digest_and_length(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = S3FileSink(S3Config(bucket="b"))
    monkeypatch.setattr(sink, "_client_or_build", lambda: _S3Recorder())
    result = sink.write("k", iter(CHUNKS))
    assert result.sha256 == EXPECTED
    assert result.bytes_written == len(b"".join(CHUNKS))


class _GcsStore:
    """A bucket stand-in: objects by name, each with a generation."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, int]] = {}
        self.deletes: list[dict[str, Any]] = []
        self.delete_fails = False
        self.open_calls: list[tuple[str, dict[str, Any]]] = []
        self.stale_error: Any = gax_exc.PreconditionFailed  # answer for a replaced generation
        self.read_fault: Any = None  # raised when a reader closes


class _Writer:
    def __init__(self, blob: _Blob, fault: Any) -> None:
        self.blob, self.fault, self.parts = blob, fault, []

    def write(self, data: bytes) -> int:
        self.parts.append(data)
        return len(data)

    def close(self) -> None:
        store = self.blob.store
        store.objects[self.blob.name] = (b"".join(self.parts), 7)
        if self.fault is not None:
            raise self.fault()

    def __enter__(self) -> _Writer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Response:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def json(self) -> Any:
        return self.payload


class _Reader:
    """Reads the bytes in two chunks; each read re-checks the pinned generation."""

    def __init__(self, blob: _Blob, kw: dict[str, Any]) -> None:
        self.blob, self.kw, self.reads = blob, kw, 0

    def read(self, size: int = -1) -> bytes:
        body, generation = self.blob.store.objects[self.blob.name]
        if "if_generation_match" in self.kw and self.kw["if_generation_match"] != generation:
            raise self.blob.store.stale_error(MARKER)
        self.reads += 1
        return body[(self.reads - 1) * 4 : self.reads * 4]

    def __enter__(self) -> _Reader:
        return self

    def __exit__(self, *exc: object) -> None:
        if self.blob.store.read_fault is not None:
            raise self.blob.store.read_fault()


class _Blob:
    def __init__(self, store: _GcsStore, name: str, fault: Any = None) -> None:
        self.store, self.name, self.fault = store, name, fault
        self.generation: int | None = None
        self.size = None
        self.content_type = None
        self.updated = None

    def reload(self, timeout: Any = None, retry: Any = None) -> None:
        if self.name not in self.store.objects:
            raise gax_exc.NotFound(MARKER)
        self.generation = self.store.objects[self.name][1]

    def open(self, mode: str, **kw: Any) -> Any:
        self.store.open_calls.append((mode, kw))
        if "w" in mode:
            return _Writer(self, self.fault)
        return _Reader(self, kw)

    def delete(self, **kw: Any) -> None:
        self.store.deletes.append(kw)
        if self.store.delete_fails:
            raise gax_exc.ServiceUnavailable(MARKER)
        if self.store.objects.get(self.name, (b"", None))[1] == kw["if_generation_match"]:
            del self.store.objects[self.name]


class _Bucket:
    def __init__(self, store: _GcsStore, fault: Any = None) -> None:
        self.store, self.fault = store, fault

    def blob(self, name: str) -> _Blob:
        return _Blob(self.store, name, self.fault)


def _gcs_sink(store: _GcsStore, fault: Any = None) -> GCSFileSink:
    sink = GCSFileSink(GCSConfig(bucket="b"))
    sink._bucket = _Bucket(store, fault)  # type: ignore[assignment]
    return sink


def test_gcs_sink_reports_digest_and_length() -> None:
    store = _GcsStore()
    result = _gcs_sink(store).write("k", iter(CHUNKS))
    assert result.sha256 == EXPECTED
    assert result.bytes_written == len(b"".join(CHUNKS))


# ----- AT-E2-2: the field is validated strictly ---------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["A" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", True, b"a" * 64, 5, ""],
    ids=["upper", "short", "long", "newline", "bool", "bytes", "int", "empty"],
)
def test_write_result_refuses_a_bad_digest(bad: Any) -> None:
    with pytest.raises(TypeError):
        WriteResult("p", 1, sha256=bad)


def test_write_result_accepts_a_digest_and_stays_compatible() -> None:
    assert WriteResult("p", 1, sha256="a" * 64).sha256 == "a" * 64
    old = WriteResult("p", 1)
    assert old.sha256 is None and old.bytes_written == 1


# ----- AT-E2-3: provider digest failures --------------------------------------------


def _client_error(code: str) -> Any:
    return botocore_exc.ClientError(
        {"Error": {"Code": code, "Message": MARKER}, "ResponseMetadata": {"HTTPStatusCode": 400}},
        "PutObject",
    )


@pytest.mark.parametrize(
    "make",
    [
        lambda: _client_error("BadDigest"),
        lambda: _client_error("InvalidDigest"),
        lambda: _client_error("XAmzContentSHA256Mismatch"),
        lambda: botocore_exc.FlexibleChecksumError(error_msg="zz_marker"),
    ],
    ids=["BadDigest", "InvalidDigest", "XAmzContentSHA256Mismatch", "FlexibleChecksumError"],
)
def test_s3_digest_failures_are_digest_mismatch(make: Any) -> None:
    def boom() -> None:
        raise make()

    with pytest.raises(PermanentError) as info:
        _clients.s3_call(boom)
    assert info.value.kind == "digest_mismatch"
    assert str(info.value) == "S3 content check failed"
    assert info.value.__cause__ is None and info.value.__context__ is None


# ----- AT-E2-4: GCS cleanup under the real wrapper ----------------------------------


def _corruption(payload: Any) -> Any:
    return lambda: gcs_exc.DataCorruption(_Response(payload))


def _write_fails(store: _GcsStore, payload: Any) -> PermanentError:
    sink = _gcs_sink(store, _corruption(payload))
    with pytest.raises(PermanentError) as info:
        sink.write("k", iter([b"abc"]))
    return info.value


def test_gcs_digest_failure_deletes_the_finalized_object_by_generation() -> None:
    store = _GcsStore()
    err = _write_fails(store, {"generation": "7", "name": "zz_marker"})
    assert err.kind == "digest_mismatch" and err.cleanup_ok is True
    assert str(err) == "GCS content check failed"
    assert err.__cause__ is None and err.__context__ is None
    assert store.objects == {}
    assert len(store.deletes) == 1
    assert store.deletes[0]["if_generation_match"] == 7
    assert type(store.deletes[0]["if_generation_match"]) is int


def test_gcs_cleanup_failure_is_reported() -> None:
    store = _GcsStore()
    store.delete_fails = True
    err = _write_fails(store, {"generation": "7"})
    assert err.kind == "digest_mismatch" and err.cleanup_ok is False
    assert err.__cause__ is None and err.__context__ is None
    assert "zz_marker" not in str(err) + repr(err)


@pytest.mark.parametrize(
    "payload",
    [{}, {"generation": "x"}, {"generation": True}, {"generation": 7}, {"generation": 7.9}]
    + [{"generation": v} for v in (" 7", "+7", "07", "7\n", "", "0")]
    + [None, [1]],
)
def test_gcs_unreadable_generation_means_no_delete(payload: Any) -> None:
    store = _GcsStore()
    err = _write_fails(store, payload)
    assert err.kind == "digest_mismatch" and err.cleanup_ok is False
    assert store.deletes == []


def test_gcs_corruption_without_a_response_means_no_delete() -> None:
    store = _GcsStore()
    sink = _gcs_sink(store, lambda: gcs_exc.DataCorruption(None))
    with pytest.raises(PermanentError) as info:
        sink.write("k", iter([b"abc"]))
    assert info.value.cleanup_ok is False and store.deletes == []


@pytest.mark.parametrize("how", ["close", "exit"])
def test_gcs_close_and_exit_behave_the_same(how: str) -> None:
    store = _GcsStore()
    blob = _Blob(store, "k", _corruption({"generation": "7"}))
    wrapper = _clients.gcs_open(blob, "wb")
    wrapper.write(b"abc")
    with pytest.raises(PermanentError) as info:
        wrapper.close() if how == "close" else wrapper.__exit__(None, None, None)
    assert info.value.cleanup_ok is True and len(store.deletes) == 1


def test_a_read_wrapper_has_no_cleanup() -> None:
    store = _GcsStore()
    store.objects["k"] = (b"abcdefgh", 3)
    store.read_fault = _corruption({"generation": "3"})
    blob = _Blob(store, "k")
    with pytest.raises(PermanentError) as info:
        with _clients.gcs_open(blob, "rb") as remote:
            assert remote.read(4) == b"abcd"
    assert info.value.kind == "digest_mismatch" and info.value.cleanup_ok is None
    assert store.deletes == [] and "k" in store.objects


def test_digest_read_before_exhaustion_raises() -> None:
    digest = DigestingChunks(iter([b"a", b"b"]))
    with pytest.raises(ValueError):
        digest.hexdigest()
    it = iter(digest)
    next(it)
    with pytest.raises(ValueError):
        digest.hexdigest()
    list(it)
    assert digest.hexdigest() == hashlib.sha256(b"ab").hexdigest() and digest.count == 2


# ----- AT-E2-7: the error attribute and the size ceiling ------------------------------


def test_connector_error_cleanup_ok_defaults_to_none_and_survives_pickle() -> None:
    assert ConnectorError("x", kind="digest_mismatch").cleanup_ok is None
    err = PermanentError("x", kind="digest_mismatch", cleanup_ok=True)
    back = pickle.loads(pickle.dumps(err))  # noqa: S301 - round trip of our own value
    assert back.cleanup_ok is True and back.kind == "digest_mismatch"
    assert PermanentError("x", cleanup_ok=False).cleanup_ok is False


def test_errors_module_stays_within_the_goal_with_no_census_line() -> None:
    root = Path(__file__).resolve().parents[2]
    lines = (root / "src/decoy_engine/errors.py").read_text(encoding="utf-8").count("\n")
    assert lines <= 600
    size_test = (root / "tests/sentry/test_module_size.py").read_text(encoding="utf-8")
    assert "decoy_engine/errors.py" not in size_test


# ----- AT-E2-9: the GCS read is pinned to one generation ----------------------------


def _source(store: _GcsStore) -> GCSFileSource:
    source = GCSFileSource(GCSConfig(bucket="b"))
    source._bucket = _Bucket(store)  # type: ignore[assignment]
    return source


def test_gcs_read_pins_the_reloaded_generation_on_every_chunk() -> None:
    store = _GcsStore()
    store.objects["k"] = (b"abcdefgh", 3)
    assert b"".join(_source(store).open("k")) == b"abcdefgh"
    (mode, kw), *rest = store.open_calls
    assert mode == "rb" and kw["if_generation_match"] == 3 and not rest


def test_gcs_object_replaced_mid_read_is_source_changed() -> None:
    store = _GcsStore()
    store.objects["k"] = (b"abcdefgh", 3)
    reader = _source(store).open("k")
    assert next(reader) == b"abcd"
    store.objects["k"] = (b"WXYZ" * 2, 4)
    with pytest.raises(PermanentError) as info:
        next(reader)
    assert info.value.kind == "source_changed"
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_gcs_replaced_object_answering_not_found_mid_read_is_source_changed() -> None:
    """A real replaced generation can answer 404 (the media link carries the generation)."""
    store = _GcsStore()
    store.objects["k"] = (b"abcdefgh", 3)
    store.stale_error = gax_exc.NotFound
    reader = _source(store).open("k")
    assert next(reader) == b"abcd"
    store.objects["k"] = (b"WXYZ" * 2, 4)
    with pytest.raises(PermanentError) as info:
        next(reader)
    assert info.value.kind == "source_changed"
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_gcs_missing_object_at_reload_stays_not_found() -> None:
    with pytest.raises(PermanentError) as info:
        next(_source(_GcsStore()).open("missing"))
    assert info.value.kind == "not_found"
