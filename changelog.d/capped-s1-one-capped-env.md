### Fixed (memory-capped bench and probe runs use the one capped child env, CAPPED-S1, 2026-11-18)

The memory probe and the capped bench driver now start their child with the shared capped env, so they get the same BLAS thread limits as the capped worker. Before, they built their own env without those limits and could fail on a many-core host the same way the worker did. The build-floor probe now uses the shared memory-cap setter. Engine output does not change.
