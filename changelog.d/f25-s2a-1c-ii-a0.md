### Added (Recursive scratch child removal, F25-S2A-1C-II-A0, 2026-11-25)

`ScratchArena.remove_tree(component)` removes a child directory and everything under it without following links, and returns a `CleanupReport`. It never raises `OSError`: a failure leaves the rest in place and reports `RETAINED`. The existing `remove` is unchanged.

Tree removal stops at a mount. On Linux it reads `/proc/self/mountinfo` and keeps the tree when the table cannot be read, parsed or matched to the directory. Every removal compares its root with the held parent's device, and the proof marker of a stage or arena is removed last, so a removal that stops part way can still be reclaimed.
