### Added (anonymity metrics, V2-3.2, 2026-11-07)

V2 track, library-only, not wired into config, validators or the CLI.
`decoy_engine.quality.anonymity` measures syntactic privacy models over named quasi-identifiers of a
pandas DataFrame or pyarrow Table: `measure_k_anonymity` (class sizes, size distribution, ARX prosecutor
risk; Sweeney 2002), `measure_l_diversity` (distinct, entropy, recursive (c, l); Machanavajjhala et al.
2007) and `measure_t_closeness_equal` / `measure_t_closeness_ordered` (Earth Mover's Distance with equal
or ordered ground distance; Li, Li and Venkatasubramanian 2007). Reports are frozen and value-free.
Null quasi-identifiers are their own value; null sensitive values are excluded, and t-closeness reports
an undetermined target while a class has no non-null sensitive value. Arrow columns convert
losslessly (dictionary entries that are null or NaN become null cells); float NaN counts as null.
Object-column values are keyed by type family (`1`, `1.0`, `True` differ) for quasi-identifiers and
for t-closeness, and by plain equality for l-diversity. Plan: `docs/plans/2026-11-07-v2-3.2-anonymity-metrics.md`.
