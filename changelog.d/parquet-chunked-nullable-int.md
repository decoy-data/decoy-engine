### Changed (Chunked entry contract and value-free schema error, PARQUET-CHUNKED-NULLABLE-INT S1, 2026-11-26)

The compatibility contract for `run_mask_chunked` now states a narrower exception. The oracle writes untouched columns from the source, so nullable integers above 2^53 and a `timestamp[ns]` of `-2**63` agree on both entries. The remaining differences are values pandas refuses, an adapter that is not exactly `PandasExecutionAdapter` (it runs the oracle leg and carries nothing), and the oracle typing each chunk alone.

The `chunked_schema_mismatch` message from the chunk schema rule no longer includes pyarrow's text, which can quote a source value, and the error carries no exception context. Callers that match on the code are not affected.
