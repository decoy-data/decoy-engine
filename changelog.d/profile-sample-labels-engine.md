Breaking: `scan_sources` no longer lists `key_candidates` for a sampled scan, and `scan-set/v1` tables and `profile_document` gain `basis` (and `scanned_rows` on the table).

### Changed (profile basis labels, PROFILE-SAMPLE-LABELS E1, 2026-11-19)

A table in `scan-set/v1` now has `basis` (`whole` or `sample`) and `scanned_rows`, and a profile document has `basis`. `whole` means the read reached the end of the source; the head scan reads one row past the cap to prove it, and a head scan of a file with exactly the cap rows is `whole` with an exact `row_count`. `key_candidates` is empty on a `sample` basis, because a key needs counts over every row. A record written before this change reads as `sample` with no `scanned_rows` and still exports. A `basis` value a later minor adds reads as `sample`.

`ColumnProfile` gains a last field, `basis`, default `sample`. The scan-set read models are now derived by the one central deriver (`_value_free.derive_read`); the table row counts and basis are checked together on write and read.
