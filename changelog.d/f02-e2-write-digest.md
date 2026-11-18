### Added (content digest on writes, F02-E2, 2026-11-18)

`WriteResult` has a new optional `sha256` field: the lowercase SHA-256 hex of the bytes a sink wrote. `S3FileSink` and `GCSFileSink` set it; a sink that reports no digest leaves it `None`, so sinks written against SDK 1.0 keep working. `SDK_VERSION` is now `"1.1"` (minor on an additive change; the docstring now says so).

A provider checksum failure on a write now raises `PermanentError` with kind `digest_mismatch` and fixed text. On S3 the request is rejected and no object is created. On GCS the finalized object is live when the check fails, so the writer deletes that one generation (`if_generation_match`) and sets `cleanup_ok` on the error to say whether the delete worked. `ConnectorError` gains `cleanup_ok`, `None` by default.

GCS reads are pinned to the generation read first. An object replaced mid-read fails with kind `source_changed` (GCS answers a replaced generation with 412 or 404) instead of mixing two versions.
