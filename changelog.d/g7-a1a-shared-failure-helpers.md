### Added (shared memory failure classifier and refreshed connector error, F25-G7-A1A, 2026-11-24)

`decoy_engine.fileaccess` exports `classified_failure`, `is_memory_failure` and the one chain walker `typed_memory_member`, and `decoy_engine.connectors` exports `refreshed_error`, which rebuilds a caught `TransientError` or `PermanentError` with fixed text and the same class and kind.
