### Changed (internal, PER-COLUMN-ROUTING S0, 2026-11-28)

The oracle route wrapper of a chunked mask run moved into its own module, `_oracle_route`. The per-chunk oracle step itself is in `_oracle_step.py`. Output, routes and errors do not change. This prepares per-column routing, where one table can send some columns to the native route and the rest to the oracle.
