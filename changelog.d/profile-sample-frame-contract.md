### Changed (sample_frame end-of-source contract, PROFILE-SAMPLE-LABELS E0, 2026-11-19)

`ProfileSource.sample_frame(n)` now returns exactly `n` rows when the source holds that many, and fewer only at the end of the source. S3 and GCS CSV readers fetch more ranged windows until they hold `n` rows or the object ends, instead of parsing only the first 1 MiB.

Cloud CSV `profile_source` now profiles the requested 10,000 rows when available. Null counts, distinct counts and profile hashes can change from first-window results.
