### Added (deterministic faker collision report, Z-E1)

A `--post-validate` run now reports, for each deterministic `faker` column that is not `unique` and has no `when:`, how many distinct source values merged into shared masked values. The warning code is `cardinality_collisions` (`warning/cardinality_collisions`). Its detail holds `table`, `source_distinct`, `output_distinct`, `distinct_lost` and `pool_size`: names and counts only. `decoy_engine.generation.pool.effective_pool_size` is a new public name.

### Changed (faker and hash collision docs, Z-E1)

`docs/strategies.md` and `docs/security/token-vault.md` no longer say deterministic identifier and pool strategies map distinct source values to distinct masked values. Deterministic `faker` is a keyed many-to-one pick. Only `fpe` is one-to-one, and an untruncated `hash` or `tokenize` is collision-resistant, not collision-free.
