### Changed (large non-FK tables carry passthrough columns exactly, NONFK-OOM, 2026-11-20)

Under `auto`, a large non-FK table whose only non-chunk-stable columns are passthrough columns
that nothing reads now takes the chunked lane. Those columns come back as the source column,
type and values exact: integers with nulls above 2^53 stay `int64`, `decimal128(p, s)` keeps its
declared precision, dictionary columns keep their index width, and binary, list, struct and map
columns pass through unchanged. The full-frame route for tables below the size threshold is
unchanged, so the output type of these columns now depends on table size.

A source with a list, struct or map column no longer raises an uncoded `TypeError` at profile
time. The column's `distinct_count` is `None`.
