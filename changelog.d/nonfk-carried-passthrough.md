### Changed (large non-FK tables carry passthrough columns exactly, NONFK-OOM, 2026-11-20)

Under `auto`, a large non-FK table whose only non-chunk-stable columns are passthrough columns
that nothing reads now takes the chunked lane. Those columns come back as the source column,
type and values exact: integers with nulls above 2^53 stay `int64`, `decimal128(p, s)` keeps its
declared precision, dictionary columns keep their index width, and binary, list and struct
columns pass through unchanged. A map column keeps its map type: the chunked lane carries it, and the full-frame
and sequential adapters rebuild it from the source's declared type instead of failing on it. The
full-frame route is otherwise unchanged, so the output type of the other columns now depends on
table size. With
`chunked_dispatcher_enabled=False` the legacy lane converts every column to pandas, so no column
is exempt and the table runs full-frame as before.

A source with a list, struct or map column no longer raises an uncoded `TypeError` at profile
time. The column's `distinct_count` is `None`.
