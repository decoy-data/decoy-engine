Breaking: windowed_date produces different dates for the same seed (output-changing, pre-GA).

### Changed (windowed_date offsets, GEN-WINDOWED-BATCH, 2026-11-20)

`windowed_date` now draws each row's offset from the keyed index derivation that pooled sampling uses, in one batch per column, instead of a separate numpy generator per row. It is about BENCH_X times faster on 200,000-row columns (see `docs/records/2026-11-20-gen-windowed-offsets-bench.md`). Dates stay inside the configured window, null anchors stay null, and output stays the same across runs, batch sizes, routes and thread counts. Output from earlier releases does not match: regenerate stored `windowed_date` output.

Global row numbers must now be below 2^62 (before: below 2^64). A negative or larger row number raises the new reason `runtime/windowed_date_row_number_out_of_range`.

`SEED_PROTOCOL_VERSION` does not change. A bump would rekey every keyed column and vault before GA, and only this site moves.
