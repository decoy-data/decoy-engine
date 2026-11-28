### Changed (internal, PER-COLUMN-ROUTING S0, 2026-11-28)

The oracle step of a chunked mask run moved into its own module, `_oracle_route`. Output, routes and errors do not change. This prepares per-column routing, where one table can send some columns to the native route and the rest to the oracle.
