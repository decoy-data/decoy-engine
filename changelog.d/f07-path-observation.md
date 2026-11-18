### Added (scan observes the paths of JSON columns, 82-E2b, 2026-11-18)

`scan_sources` now lists the paths inside each JSON column (`$.user.email`, `$.items[*].sku`) with how many cells hold each path, how many hold a JSON null, the value kinds and the detector ids that hit the leaf values. Each column's record gains an optional `nested` member (`scan-set/v1`, additive; `null` for a column that is not JSON). A key is written as a name only when it looks like an identifier with no run of four digits, no detector hits it, and it appears in at least 2 cells and in a tenth of its parent's cells; every other key is `*`. The scan walks at most 20,480 cells per column, 16 levels deep, 16 array items, 256 paths, and collapses a level with more than 64 keys. Pass `nested_paths=False` to skip it.

New warning codes: `warning/nested_paths_truncated`, `warning/nested_path_key_suspect` and `warning/nested_cells_unreadable`.
