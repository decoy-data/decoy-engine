Breaking: a pass-through `large_string` column is now written as `string` (32-bit offsets) when its values fit; a value that cannot fit keeps `large_string`

### Changed (pass-through text width, FREEZE-O3, 2026-11-19)

Pass-through text columns used to keep the source's `large_string` type on `run_mask_chunked` and the out-of-core route, so a Parquet schema or Arrow consumer saw `large_string` where the whole-frame route wrote `string`. One width state per column now decides per batch from the offsets, without a source pre-scan: values that fit leave as `string`, a batch over the 32-bit limit is split by rows, and one value that cannot fit promotes the column to `large_string` for the rest of the run. CSV text is unchanged. Parquet still cannot store a value of 2 GiB or more.
