Breaking: a faker column with no pool_size now runs on the native and chunked routes; an empty or all-null chunked output column is typed string, a non-string custom person_first_name or person_last_name provider now fails on the chunked route but still reroutes on the unified slice, and an out-of-core job whose faker pools exceed the pool budget now fails before the run starts.

### Changed (faker without pool_size runs native, FAKER-DEFAULT-POOL, 2026-11-22)

A faker column that leaves out `pool_size` now takes the default of 10,000 on every route, the same
as the full-frame run. Output values do not change. Default `person_first_name` and
`person_last_name` columns run on the native route, and tables of 100,000 rows or more run chunked
instead of full frame. `chunked_strategy_conditions_unmet` no longer names `pool_size`. The
out-of-core pool budget error no longer lists the provider, pool size or byte counts.
