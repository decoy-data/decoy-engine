"""S3 file source + sink built on the public connector SDK.

This is the first-party reference implementation of `FileSource` /
`FileSink`. It targets real AWS S3 and any S3-compatible service that
accepts a custom `endpoint_url` (MinIO, Cloudflare R2, Wasabi, Backblaze
B2, etc.).

Streaming semantics:

* `S3FileSource.open()` yields ~1 MB chunks via `StreamingBody.iter_chunks`.
  Memory use is bounded regardless of object size.
* `S3FileSink.write()` accumulates input chunks into a 5 MB buffer (the
  S3 multipart minimum part size). Once the buffer reaches 5 MB the sink
  switches to a multipart upload and uploads parts as further chunks
  arrive. Files smaller than 5 MB are written via a single `put_object`
  call.

Error mapping:

* `botocore` `NoSuchBucket` / `NoSuchKey` / 404 / 403 are surfaced as
  `PermanentError` so the engine doesn't retry them.
* Networking errors (`EndpointConnectionError`, transient 5xx) raise
  `TransientError`. botocore retries a request once; a body read that fails mid-stream is
  resumed by `connectors/_retry.py` (see `_stream_object`).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

from pydantic import Field, SecretStr

from decoy_engine.connectors import _clients
from decoy_engine.connectors._digest import DigestingChunks
from decoy_engine.connectors._retry import run_retrying
from decoy_engine.sdk import (
    CAP_INTROSPECTION,
    CAP_MULTIPART,
    CAP_RESUMABLE,
    CAP_SIGNED_URL,
    CAP_STREAMING,
    CheckResult,
    ConnectorConfig,
    ConnectorError,
    FileMeta,
    FileSink,
    FileSource,
    WriteResult,
)

__all__ = ["S3Config", "S3FileSink", "S3FileSource"]


# Default streaming read chunk size for `open()`. ~1 MiB amortizes per-chunk
# overhead without blowing past the platform's smallest worker RSS budget.
_DEFAULT_READ_CHUNK_BYTES = 1 * 1024 * 1024


class S3Config(ConnectorConfig):
    """Config shared by `S3FileSource` and `S3FileSink`.

    The same config powers both directions because the AWS SDK uses one
    client per service regardless of read/write. Customers with separate
    read-only and write-only IAM roles instantiate two connectors with
    different configs.
    """

    bucket: str = Field(..., min_length=1, max_length=255)
    prefix: str = ""
    region: str | None = None
    # Credentials are optional so the SDK supports the AWS default-chain
    # auth modes that real shops use: EC2 instance profile, ECS task role,
    # EKS IRSA, IAM Identity Center, env vars (AWS_ACCESS_KEY_ID etc.),
    # `~/.aws/credentials`. When both are None, boto3 walks the chain.
    # When provided, they take precedence over the chain.
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    endpoint_url: str | None = Field(
        default=None,
        description=(
            "Override the AWS endpoint, e.g. https://<account>.r2.cloudflarestorage.com "
            "for Cloudflare R2 or http://localhost:9000 for a MinIO dev server. "
            "Leave None for real AWS S3."
        ),
    )


def _build_s3_client(config: S3Config, *, single_request: bool = False):
    """Build the client through the one factory (``_clients.s3_client``)."""
    return _clients.s3_client(
        region=config.region,
        endpoint_url=config.endpoint_url,
        access_key_id=config.access_key_id.get_secret_value() if config.access_key_id else None,
        secret_access_key=(
            config.secret_access_key.get_secret_value() if config.secret_access_key else None
        ),
        single_request=single_request,
    )


def _join_key(prefix: str, path: str) -> str:
    """Compose `prefix/path` cleanly without leading/trailing-slash mishaps.

    Treats prefix `""` and missing trailing slash as identity. Caller-supplied
    `path` may start with `/`; we strip it so a configured prefix isn't
    silently bypassed.
    """
    p = (prefix or "").rstrip("/")
    k = (path or "").lstrip("/")
    return f"{p}/{k}" if p else k


class S3FileSource(FileSource[S3Config]):
    """Read files from an S3 bucket (or S3-compatible service)."""

    name: ClassVar[str] = "s3"
    version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[dict[str, bool]] = {
        CAP_STREAMING: True,
        CAP_RESUMABLE: True,  # supported via Range header re-requests
        CAP_SIGNED_URL: True,  # via boto3 generate_presigned_url
        CAP_INTROSPECTION: True,  # list returns size + content_type
    }

    def __init__(self, config: S3Config) -> None:
        super().__init__(config)
        # Lazy: defer client construction until first call so that
        # constructing the source object is cheap and side-effect-free.
        self._client = None
        self._resume_client = None

    def _client_or_build(self):
        if self._client is None:
            self._client = _build_s3_client(self.config)
        return self._client

    def _resume_client_or_build(self):
        """The one-attempt client a mid-stream resume uses, so the executor is its only retry."""
        if self._resume_client is None:
            self._resume_client = _build_s3_client(self.config, single_request=True)
        return self._resume_client

    def check(self) -> CheckResult:
        """Verify the bucket exists and the configured credentials reach it."""
        try:
            client = self._client_or_build()
            client.head_bucket(Bucket=self.config.bucket)
        except Exception as exc:
            return CheckResult(ok=False, detail=str(_clients.s3_error(exc)))
        return CheckResult(ok=True)

    def list(self, prefix: str | None = None) -> Iterator[FileMeta]:
        """Yield FileMeta for every object under prefix.

        Combines the config-level prefix with the call-level prefix (the
        config prefix scopes the source; the call prefix narrows further
        within that scope).
        """
        client = self._client_or_build()
        effective_prefix = _join_key(self.config.prefix, prefix or "")
        paginator = _clients.s3_call(client.get_paginator, "list_objects_v2")
        # Pages are fetched lazily, so each `next` is a network call that needs translating.
        pages = iter(paginator.paginate(Bucket=self.config.bucket, Prefix=effective_prefix))
        done = object()
        while (page := _clients.s3_call(next, pages, done)) is not done:
            for item in page.get("Contents", []):
                # `LastModified` is a datetime; ISO format for FileMeta.
                modified = item.get("LastModified")
                yield FileMeta(
                    path=item["Key"],
                    size=item.get("Size"),
                    content_type=None,  # list_objects doesn't return content-type
                    modified=modified.isoformat() if modified else None,
                )

    def head(self, path: str) -> FileMeta:
        """Native S3 HEAD: one RPC, returns size and content-type.

        Overrides the default list-walking implementation. `path` is
        interpreted as an absolute S3 key (no prefix joining), matching
        the semantics of `open()`.
        """
        client = self._client_or_build()
        response = _clients.s3_call(client.head_object, Bucket=self.config.bucket, Key=path)
        modified = response.get("LastModified")
        return FileMeta(
            path=path,
            size=response.get("ContentLength"),
            content_type=response.get("ContentType"),
            modified=modified.isoformat() if modified else None,
        )

    def open(self, path: str) -> Iterator[bytes]:
        """Stream object bytes in ~1 MB chunks.

        `path` is interpreted as an absolute S3 key (no prefix joining).
        This matches what `list()` returned: callers iterate list, pick
        a key, pass it to open. Re-joining would double-prefix.
        """
        yield from _stream_object(
            self._client_or_build(), self._resume_client_or_build(), self.config.bucket, path
        )


class _Resumable:
    """One object read that can reopen its body at the byte it reached.

    The first request goes on the ordinary client. After a ``transient`` failure the next
    attempt reopens with ``Range`` from the bytes already yielded and ``IfMatch`` on the first
    ETag, on the one-attempt client, so the executor is the only retry layer. A 412 means the
    object changed: ``source_changed``, never retried.
    """

    def __init__(self, client: Any, resume_client: Any, bucket: str, key: str) -> None:
        self._client, self._resume_client = client, resume_client
        self._bucket, self._key = bucket, key
        self._chunks: Iterator[bytes] | None = None
        self._body: Any = None
        self._etag: str | None = None
        self.offset = 0

    def start(self) -> None:
        """The first request, on the ordinary client: botocore owns its retry, not the executor."""
        response = _clients.s3_call(self._client.get_object, Bucket=self._bucket, Key=self._key)
        self._etag = response.get("ETag") or None
        self._attach(response)

    def _resume(self) -> None:
        if self._etag is None:
            # Without a version to pin, a resume could splice two versions of the object.
            raise _clients.source_changed("S3")
        changed = False
        try:
            response = _clients.s3_call(
                self._resume_client.get_object,
                Bucket=self._bucket,
                Key=self._key,
                Range=f"bytes={self.offset}-",
                IfMatch=self._etag,
            )
        except ConnectorError as err:
            if err.kind != "precondition_failed":
                raise
            changed = True
        if changed:
            raise _clients.source_changed("S3")
        self._attach(response)

    def _attach(self, response: Any) -> None:
        self._body = response["Body"]
        self._chunks = self._body.iter_chunks(chunk_size=_DEFAULT_READ_CHUNK_BYTES)

    def next_chunk(self) -> bytes | None:
        """The next non-empty chunk, None at the end. A failure drops the body so a retry reopens."""
        if self._chunks is None:
            self._resume()
        assert self._chunks is not None  # noqa: S101 - set by start() or _resume()
        try:
            while True:
                chunk = _clients.s3_call(next, self._chunks, None)
                if chunk is None:
                    return None
                if chunk:
                    self.offset += len(chunk)
                    return chunk
        except ConnectorError:
            self.close()
            raise

    def close(self) -> None:
        body, self._body, self._chunks = self._body, None, None
        if body is not None:
            body.close()


def _stream_object(client, resume_client, bucket: str, key: str) -> Iterator[bytes]:
    """The one S3 object read loop, shared by the source and the object store.

    Each chunk read runs under ``run_retrying``; a failed one reopens the body at the offset
    already yielded (``_Resumable``), so no byte is yielded twice.
    """
    reader = _Resumable(client, resume_client, bucket, key)
    reader.start()
    try:
        while (chunk := run_retrying(reader.next_chunk)) is not None:
            yield chunk
    finally:
        reader.close()


class S3FileSink(FileSink[S3Config]):
    """Write files to an S3 bucket (or S3-compatible service).

    Sizes below 5 MB use a single `put_object`; larger writes transparently
    switch to a multipart upload. Failures during multipart trigger
    `abort_multipart_upload` so partial uploads don't accumulate.
    """

    name: ClassVar[str] = "s3"
    version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[dict[str, bool]] = {
        CAP_STREAMING: True,
        CAP_MULTIPART: True,
        CAP_SIGNED_URL: True,
    }

    def __init__(self, config: S3Config) -> None:
        super().__init__(config)
        self._client = None

    def _client_or_build(self):
        if self._client is None:
            self._client = _build_s3_client(self.config)
        return self._client

    def check(self) -> CheckResult:
        try:
            client = self._client_or_build()
            client.head_bucket(Bucket=self.config.bucket)
        except Exception as exc:
            return CheckResult(ok=False, detail=str(_clients.s3_error(exc)))
        return CheckResult(ok=True)

    def write(self, path: str, chunks: Iterator[bytes]) -> WriteResult:
        """Write `chunks` to `<config.prefix>/<path>` in the bucket.

        `_clients.s3_put` is the one put path. Strategy:

        1. Buffer incoming chunks up to the 5 MiB multipart minimum part size.
        2. If the iterator is exhausted before the buffer fills, do a
           single `put_object`. This is the cheap path for small files.
        3. Otherwise initiate a multipart upload, push the filled buffer
           as part 1, then keep filling and pushing parts.
        4. On the final part (after the iterator exhausts), upload
           whatever remains in the buffer (no 5-MiB minimum applies to
           the last part) and complete the multipart upload.
        5. Any error after step 3 triggers `abort_multipart_upload` to
           clean up the in-progress upload state on S3.
        """
        client = self._client_or_build()
        key = _join_key(self.config.prefix, path)
        digest = DigestingChunks(chunks)
        total = _clients.s3_put(client, self.config.bucket, key, iter(digest), {})
        return WriteResult(path=key, bytes_written=total, sha256=digest.hexdigest())
