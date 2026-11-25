### Changed (stream-all pool take and pool memory charge, GEN-STREAM-ALL S1a, 2026-11-25)

Pooled Faker columns now hand Arrow arrays to the batch assembler instead of Python lists, through one pooled pick, `pool_take`. Output bytes do not change.

- Bounded generation charges a pooled Faker column for the pool's object form, its Arrow form and the conversion peak. Faker's locale provider tables are charged once per distinct locale of the run, before any locale opens. The charge covers every column that opens Faker (pooled, per-row and Faker-backed provider columns), the platform default locale, the default-locale check and every entry of a locale list. Each locale is charged its measured cold build: `it_IT` and `de_AT` cost more than the others. A job that needs more than the budget fails with `generation_budget_exceeded` before the first provider call.
- `PoolCache` counts the root buffers a pool's Arrow form keeps alive, including dictionaries nested in structs, lists and maps, so a small slice of a large array, or a column read from Arrow IPC, no longer passes a small cache limit.
- `generation.pool` exports `pool_take`, `faker_pool_resident_bytes`, `provider_init_bytes`, `provider_init_bound` and `run_faker_footprint`. The locale rule (`requested_locale`, `effective_locale`, `locale_entries`, `open_column_faker`, `DEFAULT_GENERATE_LOCALE`) is in `internal/faker_locale.py`, used by validation, budgeting, per-row and pooled generation and preflight. A locale alias such as `it` is charged as the locale Faker opens (`it_IT`). `table_batches` and `check_width` moved to `generation/stream/_batches.py` and load on first use.

Fixed: a validated locale list such as `["de_AT", "it_IT"]` no longer raises `NotImplementedError` when a Faker column generates.
