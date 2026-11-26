### Added (Stability seam for the CLI census, EXPERIMENTAL-TIER S0, 2026-11-26)

`decoy_engine.contracts.stability` now holds `is_experimental_export` and `tier_key`, the engine census's identity rule moved out of the test tree so the CLI census can call it. No tier changes and no runtime behavior changes. Contract 3.6 names these functions as the consumer seam.
