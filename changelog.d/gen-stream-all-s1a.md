### Changed (stream-all pool take and pool memory charge, GEN-STREAM-ALL S1a, 2026-11-25)

Pooled Faker columns now hand Arrow arrays to the batch assembler instead of Python lists, through one pooled pick, `pool_take`. Output bytes do not change.

- Bounded generation charges a pooled Faker column for the pool's object form, its Arrow form and the conversion peak. Faker's locale provider tables are charged once per distinct locale of the run, before any locale opens, including the platform default locale and every entry of a locale list. A job that needs more than the budget fails with `generation_budget_exceeded` before the first provider call.
- `PoolCache` counts the buffers a pool's Arrow form keeps alive, so a small slice of a large array no longer passes a small cache limit.
- `generation.pool` exports `pool_take`, `faker_pool_resident_bytes`, `provider_init_bytes` and `pool_locales`. `table_batches` and `check_width` moved to `generation/stream/_batches.py` and load on first use.
