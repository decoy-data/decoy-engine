### Changed (ScratchArena.open is now ScratchArena.fresh, F25, 2026-11-15)

`ScratchArena.open(under=...)` is renamed `ScratchArena.fresh(under=...)`. The name `open` collided with the GCS `Blob.open` name the outbound client sentry matches, and an arena is not a GCS client. Behavior is unchanged; there is no alias for the old name (pre-GA hard rename).
