### Changed (the no-sink collector opens its scratch arena on the first spill, RUN-STREAM E5b, 2026-11-16)

A lazy source with no sink now creates the private scratch directory only when a held-back chunk first spills. A run that never spills makes no directory, and no longer fails on a Windows host, where the scratch arena is unavailable. A run that must spill on Windows still fails, at the first spill.
