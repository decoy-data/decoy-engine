### Added (generalization hierarchies, V2-3.1, 2026-11-07)

V2 track, built ahead, opt-in by import only. `decoy_engine.anonymize.hierarchies` builds per-column
generalization hierarchies for quasi-identifiers: `interval_hierarchy` (fixed widths), `band_hierarchy`
(cut points), `prefix_hierarchy` (fixed-length codes such as ZIPs), `date_hierarchy` (month, quarter,
year) and `category_hierarchy` (a user tree). Levels run from 0 (the value) to the top (`"*"` for
every row); coarser levels only merge classes, and a label depends only on the value.
`check_hierarchy` reports coverage, classes per level and monotonicity without values; `Lattice` gives
the level vectors a search walks and applies one to a pandas or Arrow table.
`decoy_engine.anonymize.type_family` is the shared value-identity rule (`1`, `1.0` and `True` are
three values). No config key, strategy, catalog row, planner check or reason code is added, and
`import decoy_engine` does not load the package.
