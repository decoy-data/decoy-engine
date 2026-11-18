### Added (microaggregation, V2-3.4, 2026-11-07)

V2 track, built ahead; opt-in by import only. New package `decoy_engine.anonymize.microaggregation`:
`microaggregate(table, quasi_identifiers, k=k)` groups rows into k to 2k-1 records with MDAV (Domingo-Ferrer and
Torra 2005, as sdcMicro runs it) on standardised numeric quasi-identifiers and replaces each by its group mean,
returning a new pandas or Arrow table and a value-free `MicroaggregationReport` (group sizes, SSE/SST information
loss). Refuses nulls, non-numeric columns, fewer than k rows and more than `MAX_ROWS` (50,000). No config,
strategy, planner or CLI change; `import decoy_engine` does not load it.
