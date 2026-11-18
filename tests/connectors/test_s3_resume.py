"""F02-E1: S3 body resume on the single-request client, the part split, `size` (AT-E1-3, -7, -11)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

botocore_exc = pytest.importorskip("botocore.exceptions")

from decoy_engine.connectors import _clients  # noqa: E402
from decoy_engine.connectors import object_store as object_store_mod  # noqa: E402
from decoy_engine.connectors.object_store import GCSObjectStore, S3ObjectStore  # noqa: E402
from decoy_engine.connectors.s3 import S3Config, _stream_object  # noqa: E402
from decoy_engine.sdk import ConnectorError, PermanentError  # noqa: E402

MIB = 1024 * 1024
PART = 5 * MIB
OBJECT = bytes(range(256)) * (7 * MIB // 256)
ETAG = '"etag-one"'


class Body:
    def __init__(self, data: bytes, *, die_after: int | None = None) -> None:
        self._data, self._die_after, self.closed = data, die_after, False

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self._data), chunk_size):
            if self._die_after is not None and start >= self._die_after:
                raise botocore_exc.ReadTimeoutError(endpoint_url="http://zz-host")
            yield self._data[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeClient:
    """A get_object stand-in over OBJECT that records its calls."""

    def __init__(self, *, die_after: int | None = None, etag: str = ETAG, fail: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._die_after, self._etag, self._fail = die_after, etag, fail

    def get_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(kw)
        if self._fail is not None and "Range" in kw:
            raise self._fail
        start = int(kw["Range"].split("=")[1].rstrip("-")) if "Range" in kw else 0
        die = self._die_after if "Range" not in kw else None
        return {"ETag": self._etag, "Body": Body(OBJECT[start:], die_after=die)}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_a_mid_stream_read_failure_resumes_at_the_offset_with_if_match() -> None:  # AT-E1-3
    first, resume = FakeClient(die_after=3 * MIB), FakeClient()
    data = b"".join(_stream_object(first, resume, "bkt", "k"))
    assert data == OBJECT
    assert len(first.calls) == 1 and "Range" not in first.calls[0]
    assert len(resume.calls) == 1
    assert resume.calls[0]["Range"] == "bytes=3145728-"
    assert resume.calls[0]["IfMatch"] == ETAG


def test_a_412_on_resume_is_source_changed_and_yields_nothing_more() -> None:  # AT-E1-3
    err = botocore_exc.ClientError(
        {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
        "GetObject",
    )
    first, resume = FakeClient(die_after=3 * MIB), FakeClient(fail=err)
    got: list[bytes] = []
    with pytest.raises(PermanentError) as info:
        for chunk in _stream_object(first, resume, "bkt", "k"):
            got.append(chunk)
    assert info.value.kind == "source_changed"
    assert b"".join(got) == OBJECT[: 3 * MIB]
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_a_permanent_failure_mid_stream_does_not_resume() -> None:
    class Dies(Body):
        def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
            yield b"a"
            raise ValueError("zz-private")

    class C(FakeClient):
        def get_object(self, **kw: Any) -> dict[str, Any]:
            self.calls.append(kw)
            return {"ETag": ETAG, "Body": Dies(b"")}

    first, resume = C(), FakeClient()
    with pytest.raises(ConnectorError):
        list(_stream_object(first, resume, "bkt", "k"))
    assert resume.calls == []


def test_store_and_source_send_the_resume_on_the_single_request_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # AT-E1-3 (identity)
    built: list[bool] = []
    first, resume = FakeClient(die_after=3 * MIB), FakeClient()

    def build(config: S3Config, *, single_request: bool = False) -> FakeClient:
        built.append(single_request)
        return resume if single_request else first

    monkeypatch.setattr(object_store_mod, "_build_s3_client", build)
    store = S3ObjectStore(S3Config(bucket="bkt"))
    assert b"".join(store.iter_object("k")) == OBJECT
    assert sorted(built) == [False, True]
    assert len(resume.calls) == 1 and len(first.calls) == 1


class PartRecorder:
    def __init__(self, label: str, log: list[tuple[str, str]]) -> None:
        self._label, self._log = label, log

    def _do(self, name: str, result: dict[str, Any]) -> dict[str, Any]:
        self._log.append((self._label, name))
        return result

    def put_object(self, **kw: Any) -> dict:
        return self._do("put_object", {"ETag": '"p"'})

    def create_multipart_upload(self, **kw: Any) -> dict:
        return self._do("create_multipart_upload", {"UploadId": "u"})

    def upload_part(self, **kw: Any) -> dict:
        return self._do("upload_part", {"ETag": '"x"'})

    def complete_multipart_upload(self, **kw: Any) -> dict:
        return self._do("complete_multipart_upload", {"ETag": '"c"'})

    def abort_multipart_upload(self, **kw: Any) -> dict:
        return self._do("abort_multipart_upload", {})


def test_put_new_sends_parts_on_the_ordinary_client_and_the_rest_on_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # AT-E1-7
    import io

    log: list[tuple[str, str]] = []

    def build(config: S3Config, *, single_request: bool = False) -> PartRecorder:
        return PartRecorder("single" if single_request else "ordinary", log)

    monkeypatch.setattr(object_store_mod, "_build_s3_client", build)
    S3ObjectStore(S3Config(bucket="bkt")).put_new("k", io.BytesIO(b"x" * (12 * MIB)))
    by_call = {name: label for label, name in log}
    assert by_call == {
        "create_multipart_upload": "single",
        "upload_part": "ordinary",
        "complete_multipart_upload": "single",
    }
    log.clear()
    S3ObjectStore(S3Config(bucket="bkt")).put_new("k", io.BytesIO(b"x"))
    assert log == [("single", "put_object")]


def test_s3_put_without_a_part_client_uses_its_one_client() -> None:
    log: list[tuple[str, str]] = []
    client = PartRecorder("only", log)
    _clients.s3_put(client, "b", "k", iter([b"x" * (6 * MIB)]), {})
    assert {label for label, _ in log} == {"only"}


def test_size_of_an_s3_object_and_a_missing_key() -> None:  # AT-E1-11
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        client = _clients.s3_client(
            region="us-east-1",
            endpoint_url=None,
            access_key_id="k",
            secret_access_key="s",
            single_request=False,
        )
        client.create_bucket(Bucket="zz-bkt")
        client.put_object(Bucket="zz-bkt", Key="o", Body=b"x" * (3 * MIB + 5))
        store = S3ObjectStore(
            S3Config(bucket="zz-bkt", region="us-east-1", access_key_id="k", secret_access_key="s")
        )
        # Longer than one read chunk, so a first-chunk length is not the object length.
        assert store.size("o") == 3 * MIB + 5
        with pytest.raises(ConnectorError) as info:
            store.size("missing")
        assert info.value.kind == "not_found"


def test_size_of_a_gcs_object_and_a_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # AT-E1-11
    from decoy_engine.connectors.gcs import GCSConfig

    class Blob:
        def __init__(self, name: str) -> None:
            self.name, self.size = name, None

        def reload(self, **kw: Any) -> None:
            if self.name == "missing":
                from google.api_core import exceptions as gax

                raise gax.NotFound("zz-private")
            self.size = 4321

    class Bucket:
        def blob(self, name: str) -> Blob:
            return Blob(name)

    class Client:
        def bucket(self, name: str) -> Bucket:
            return Bucket()

    pytest.importorskip("google.api_core")
    monkeypatch.setattr(object_store_mod, "_build_gcs_client", lambda config: Client())
    store = GCSObjectStore(GCSConfig(bucket="b"))
    assert store.size("o") == 4321
    with pytest.raises(ConnectorError) as info:
        store.size("missing")
    assert info.value.kind == "not_found"
