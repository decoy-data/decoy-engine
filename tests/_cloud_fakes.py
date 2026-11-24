"""Fake S3 and GCS object stores that record every byte they serve (F25 G7-1).

``FakeS3`` stands in for a boto3 client. ``FakeGcsSession`` stands in for the HTTP session
under a real ``google.cloud.storage.Client``: it answers the JSON metadata GET that
``Blob.reload`` makes and the media GET that ``connectors._clients.gcs_download`` makes, so
the SDK runs unchanged above it. Both write to one ``Ledger``: each response's size, the
bytes held by open responses not yet read, unsized reads, eager body reads, closes and the
version pin on each data request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

MiB = 1 << 20
_RANGE = re.compile(r"bytes=(\d+)-(\d+)")


@dataclass
class Ledger:
    responses: list[int] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    open_bodies: list[Body] = field(default_factory=list)
    max_held: int = 0
    unsized_reads: int = 0
    eager_reads: int = 0
    body_bytes_read: int = 0

    def opened(self, body: Body) -> None:
        self.open_bodies.append(body)
        self.max_held = max(self.max_held, self.held())

    def held(self) -> int:
        return sum(b.remaining for b in self.open_bodies if not b.closed)

    @property
    def data_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["kind"] == "data"]

    @property
    def fetched(self) -> int:
        return sum(self.responses)

    def all_closed(self) -> bool:
        return all(b.closed for b in self.open_bodies)


class Body:
    """A response body over ``data``, or ``length`` lazy zero bytes; ``fail_at`` raises mid-read."""

    def __init__(
        self,
        ledger: Ledger,
        data: bytes | None = None,
        *,
        length: int | None = None,
        fail_at: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._ledger, self._data = ledger, data
        self._length = len(data) if data is not None else int(length or 0)
        self._pos = 0
        self._fail_at, self._error = fail_at, error
        self.closed = False
        ledger.opened(self)

    @property
    def remaining(self) -> int:
        return self._length - self._pos

    def read(self, amt: int | None = None, decode_content: Any = None) -> bytes:
        if amt is None or amt < 0:
            self._ledger.unsized_reads += 1
            amt = self.remaining
        end = min(self._pos + amt, self._length)
        if self._fail_at is not None and end > self._fail_at:
            assert self._error is not None
            raise self._error
        piece = self._data[self._pos : end] if self._data is not None else bytes(end - self._pos)
        self._ledger.body_bytes_read += len(piece)
        self._pos = end
        return piece

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _span(header: str | None, size: int) -> tuple[int, int] | None:
    if header is None:
        return None
    match = _RANGE.fullmatch(header)
    assert match, header
    return int(match[1]), min(int(match[2]), size - 1)


def _fail_offset(fail_at: int | None, start: int, end: int) -> int | None:
    if fail_at is not None and start <= fail_at <= end:
        return fail_at - start
    return None


# ----- S3 ----------------------------------------------------------------------------------


class FakeS3:
    """A boto3 S3 client over one object. ``etag=None`` leaves ETag out of HEAD.

    ``change_after=n`` gives the object a new version after ``n`` data requests, so a later
    pinned read answers 412. ``fail_at`` raises ``error`` once a body passes that offset.
    ``short=True`` serves each range one byte short, as a store that lost bytes would.
    """

    def __init__(
        self,
        data: bytes,
        ledger: Ledger | None = None,
        *,
        etag: str | None = '"v1"',
        change_after: int | None = None,
        fail_at: int | None = None,
        error: BaseException | None = None,
        short: bool = False,
    ) -> None:
        self.data, self.ledger, self.etag = data, ledger or Ledger(), etag
        self._short = short
        self._change_after, self._fail_at, self._error = change_after, fail_at, error

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.ledger.requests.append({"kind": "head"})
        head: dict[str, Any] = {"ContentLength": len(self.data)}
        if self.etag is not None:
            head["ETag"] = self.etag
        return head

    def get_object(self, Bucket: str, Key: str, **kw: Any) -> dict[str, Any]:
        rng, pin = kw.get("Range"), kw.get("IfMatch")
        self.ledger.requests.append({"kind": "data", "range": rng, "pin": pin})
        n = len(self.ledger.data_requests)
        changed = self._change_after is not None and n > self._change_after
        current = '"v2"' if changed else self.etag
        if pin is not None and pin != current:
            from botocore.exceptions import ClientError

            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed", "Message": "zz_marker etag"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "GetObject",
            )
        span = _span(rng, len(self.data))
        start, end = span if span is not None else (0, len(self.data) - 1)
        part = self.data[start : end + 1]
        if self._short and len(part) > 1:
            part = part[:-1]
        self.ledger.responses.append(len(part))
        fail_at = _fail_offset(self._fail_at, start, end)
        return {"Body": Body(self.ledger, part, fail_at=fail_at, error=self._error)}


def install_s3(monkeypatch: pytest.MonkeyPatch, fake: FakeS3) -> FakeS3:
    from decoy_engine.profile import _cloud_readers

    monkeypatch.setattr(_cloud_readers._clients, "s3_client", lambda **_kw: fake)
    return fake


# ----- GCS ---------------------------------------------------------------------------------


@dataclass
class GcsObject:
    data: bytes
    generation: int | None = 7


class Response:
    """A ``requests.Response`` stand-in: a raw body and its headers, nothing read yet."""

    def __init__(self, ledger: Ledger, status: int, headers: dict[str, str], raw: Body) -> None:
        from requests.structures import CaseInsensitiveDict

        self.status_code, self.raw = status, raw
        self.headers: CaseInsensitiveDict[str] = CaseInsensitiveDict(headers)
        self._ledger = ledger
        self._content: bytes | None = None
        self.request = type("Req", (), {"method": "GET", "url": "https://fake.invalid/"})()

    @property
    def content(self) -> bytes:
        if self._content is None:
            self._ledger.eager_reads += 1
            self._content = self.raw.read()
        return self._content

    @property
    def text(self) -> str:
        return self.content.decode()

    def json(self) -> Any:
        return json.loads(self.content)

    def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False) -> Iterator[bytes]:
        self._ledger.eager_reads += 1
        while piece := self.raw.read(chunk_size):
            yield piece

    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeGcsSession:
    """The transport under a real ``storage.Client``: metadata JSON and ranged media GETs.

    ``ignore_range=True`` answers a media GET with 200 and a lazy 64 MiB body, no
    Content-Range and no Content-Length. ``stored_gzip=True`` answers as GCS does for an
    object uploaded with ``gsutil cp -Z``: 200, ``X-Goog-Stored-Content-Encoding: gzip`` and
    the whole compressed object. ``reply(start, end, size)`` returns headers laid over a 206
    answer, to serve a wrong Content-Range or a Content-Encoding. A ``generation`` query
    parameter that names a generation other than the current one answers 404, as GCS does.
    ``statuses`` is a queue of statuses served to media GETs before the normal answer.
    ``on_request`` sees each call first and may raise. ``tamper(n, part)`` rewrites the body
    of the n-th media GET (from 1) after its headers are set, as a store that lost bytes
    would. ``log`` gets one ``open`` per client built by ``install_gcs`` and one ``close``
    per close.
    """

    def __init__(
        self,
        obj: GcsObject,
        ledger: Ledger | None = None,
        *,
        ignore_range: bool = False,
        stored_gzip: bool = False,
        reply: Callable[[int, int, int], dict[str, str]] | None = None,
        statuses: list[int] | None = None,
        change_after: int | None = None,
        on_request: Callable[[str, dict[str, Any]], None] | None = None,
        fail_at: int | None = None,
        error: BaseException | None = None,
        tamper: Callable[[int, bytes], bytes] | None = None,
    ) -> None:
        self.obj, self.ledger, self.ignore_range = obj, ledger or Ledger(), ignore_range
        self._tamper, self._stored_gzip, self._reply = tamper, stored_gzip, reply
        self.log: list[str] = []
        self.statuses = list(statuses or [])
        self._change_after, self._on_request = change_after, on_request
        self._fail_at, self._error = fail_at, error
        self.timeouts: list[Any] = []
        self.closed = False
        self.is_mtls = False

    def request(self, method: str, url: str, **kw: Any) -> Response:
        parts = urlsplit(url)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        media = query.get("alt") == "media"
        if self._on_request is not None:
            self._on_request("media_get" if media else "metadata", kw)
        self.timeouts.append(kw.get("timeout"))
        if not media:
            return self._metadata(parts.path)
        return self._media(query, kw.get("headers") or {}, kw)

    def _metadata(self, path: str) -> Response:
        self.ledger.requests.append({"kind": "metadata"})
        name = unquote(path.rsplit("/o/", 1)[-1])
        meta: dict[str, Any] = {"name": name, "bucket": "b", "size": str(len(self.obj.data))}
        if self.obj.generation is not None:
            meta["generation"] = str(self.obj.generation)
        side = Ledger()
        return Response(side, 200, {}, Body(side, json.dumps(meta).encode()))

    def _media(
        self, query: dict[str, str], headers: dict[str, str], kw: dict[str, Any]
    ) -> Response:
        pin = query.get("ifGenerationMatch")
        self.ledger.requests.append(
            {
                "kind": "data",
                "range": headers.get("Range"),
                "pin": pin,
                "stream": kw.get("stream"),
                "accept_encoding": headers.get("Accept-Encoding"),
            }
        )
        if self.statuses:
            return Response(self.ledger, self.statuses.pop(0), {}, Body(self.ledger, b""))
        n = len(self.ledger.data_requests)
        if self._change_after is not None and n > self._change_after:
            self.obj.generation = (self.obj.generation or 0) + 1
        named = query.get("generation")
        if named is not None and int(named) != self.obj.generation:
            return Response(self.ledger, 404, {}, Body(self.ledger, b""))
        if pin is None or int(pin) != self.obj.generation:
            return Response(self.ledger, 412, {}, Body(self.ledger, b""))
        size = len(self.obj.data)
        span = _span(headers.get("Range"), size)
        if self._stored_gzip:
            stored = {"X-Goog-Stored-Content-Encoding": "gzip", "Content-Encoding": "gzip"}
            return Response(self.ledger, 200, stored, Body(self.ledger, length=64 * MiB))
        if self.ignore_range or span is None:
            return Response(self.ledger, 200, {}, Body(self.ledger, length=64 * MiB))
        start, end = span
        part = self.obj.data[start : end + 1]
        hdrs = {"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(len(part))}
        if self._reply is not None:
            hdrs.update(self._reply(start, end, size))
        if self._tamper is not None:
            part = self._tamper(n, part)
        self.ledger.responses.append(len(part))
        fail_at = _fail_offset(self._fail_at, start, end)
        return Response(
            self.ledger, 206, hdrs, Body(self.ledger, part, fail_at=fail_at, error=self._error)
        )

    def close(self) -> None:
        self.closed = True
        self.log.append("close")


def gcs_client_over(session: FakeGcsSession) -> Any:
    """A real ``storage.Client`` whose HTTP transport is ``session``."""
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage

    return storage.Client(project="p", credentials=AnonymousCredentials(), _http=session)


def install_gcs(monkeypatch: pytest.MonkeyPatch, session: FakeGcsSession) -> FakeGcsSession:
    """Make every ``storage.Client(...)`` the engine builds run over ``session``."""
    from google.cloud import storage

    real = storage.Client
    from google.auth.credentials import AnonymousCredentials

    def build(*_a: Any, **_k: Any) -> Any:
        session.log.append("open")
        return real(project="p", credentials=AnonymousCredentials(), _http=session)

    monkeypatch.setattr(storage, "Client", build)
    return session
