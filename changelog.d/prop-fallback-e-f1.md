Breaking: the import path `decoy_engine.quality.dp_budget.OpenDpReleaseSession` is removed; import it from `decoy_engine.quality.dp_session`.

### Fixed (Quiet fallbacks that weaken output, PROP-FALLBACK-E-F1, 2026-11-25)

A8a: a `targets:` key that names no configured table is now refused with `config/target_table_unknown`. Before, the writers skipped it and the run exited 0 with no file. A source name alone is not a valid target key.

A2: `geo_generalize` with `state` in its cascade raises `ExecutionError` with `runtime/reference_table_unavailable` when the shipped `us_zip5_city_state` table cannot load. Before, it logged a warning and blanked every state value. A cascade without `state` never loads the table.

D9: the lazy `dp_budget.OpenDpReleaseSession` re-export is deleted. A3 and A6 remove two catch-alls that could not trigger on a correct build. A new `swallowed-broad-except` sentry fails any new broad handler under `src/` that keeps going after the exception, with a shrink-only baseline.
