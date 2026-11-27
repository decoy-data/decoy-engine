### Added (lazy compressed CSV and route sink fact, RUN-STREAM-E6, 2026-11-25)

A compressed CSV source (gzip, bzip2, xz, zip, tar or zstd, by the declared file name) now gets the lazy CSV backend, so a streamed run reads it one chunk at a time instead of loading it whole. `read_csv_source` takes an optional `compression`; the default still infers from the name. A decoder failure (gzip, bzip2, xz, zip, tar, zstd or invalid UTF-8), including one found by the headerless width scan of a direct `read_csv_source` call, is the value-free refusal `chunked_passthrough_value_unrepresentable`, with the decoder's text never carried.

`decoy-run-result/v1` gains the optional `route.sink`, and `build_run_result` takes `sink=` (default `None`). The value is `"used"` or one reason code and is a safe reference, so free text is refused. A document without it reads as `null`.

The compatibility contract now lists `spill_parent`, `committed_table_path` and `bounded_write_batches` as optional members of a caller's sink.
