### Changed (pure re-export __init__ files need no hand entry, fix24-e3, 2026-11-17)

Tests only. The physical-seam byte-identity sentry permits a new or changed `__init__.py` under
`execution/` that only re-exports, so the hand entry for `_strategies/nested/__init__.py` is gone.
