### Added (Recursive scratch child removal, F25-S2A-1C-II-A0, 2026-11-25)

`ScratchArena.remove_tree(component)` removes a child directory and everything under it without following links, and returns a `CleanupReport`. It never raises `OSError`: a failure leaves the rest in place and reports `RETAINED`. The existing `remove` is unchanged.
