### Added (cloud table reads are bounded and pinned to one object version, F25 G7-1, 2026-11-24)

`to_frame` on the S3 and GCS profile readers no longer downloads the whole object. Parquet is
read through the footer and one row group at a time over ranged requests. CSV is streamed to
pandas in 1 MiB ranges. Every ranged read is pinned to the object version seen at open: the S3
ETag through `IfMatch`, the GCS generation through `ifGenerationMatch`. An object that changes
mid-read, or a range that comes back short, stops the read with the existing source-changed
error. A GCS media response that ignores the range or arrives transcoded is refused before its
body is read. The CSV sample window now stops at 64 MiB with `connector/sample_window_exceeded`
instead of growing to the whole object. The GCS connector's `open` uses the same pinned ranged
read. SFTP reads stay at 1 MiB.
A GCS object stored with a content encoding (for example uploaded with `gsutil cp -Z`) is
refused with `connector/stored_content_encoding`, not a generic GCS error.
