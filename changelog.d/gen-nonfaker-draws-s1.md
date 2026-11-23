Breaking: the physical `plan_hash` and `activation_hash` of every unified-slice job change once, because the provider capability matrix gains a `draw` field and the registry fingerprint hashes it. `pipeline_config_hash` does not change, and no output value changes.

### Added (computed Faker draws on masking, GEN-NONFAKER-DRAWS, 2026-11-23)

A `faker` column with `provider: uuid`, `random_int_range` or `random_choice` now compiles and runs. Before, `compile_plan` refused it with `plan.non_poolable_provider_with_pool_backend`, even though `decoy scan` and `decoy init` write `provider: uuid` for a UUID column. These providers build no pool. The value is drawn from the key: for the source value and namespace in deterministic mode, for the row number under the job seed otherwise. A null source stays null.

- `uuid` writes an RFC 9562 version 4 string. `random_int_range` writes an int64 from `min`, `max` and `step`. `random_choice` writes one of `elements`, typed as the one Arrow type of the list.
- The new plan reasons `plan/computed_draw_range_invalid`, `plan/computed_draw_elements_invalid`, `plan/computed_draw_mode_unsupported` and `plan/computed_draw_namespace_reserved` refuse arguments, cardinality modes and namespaces a computed draw cannot honor. The new runtime reason `runtime/computed_draw_position_out_of_domain` covers a row number outside the unsigned 64-bit domain. None carries an argument value.
- `address_full` and `lorem_text` are still refused at compile.
- Computed providers run the whole frame. The chunked, unified, sequential and out-of-core native routes do not admit them yet; auto routing falls through, and a forced out-of-core run refuses before any write.
- The argument and default facts for the three providers live in one table, `providers_v2.FAKER_DRAW_CONTRACTS`, which the Faker adapter and the numeric-typing integer table now read. `generation.pool.derive_pool_indices` is the public name of the former private index helper. `classify_provider` gains the class `computed_native`.
