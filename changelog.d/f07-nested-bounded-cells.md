### Fixed (nested cells are read under bounds and numbers are kept as read, 82-E1, 2026-11-17)

The `nested` strategy no longer rewrites a number it does not mask: `1.10`, `1e400` and a long decimal come back as written. A cell that repeats an object key, is over 16 MiB or 64 levels deep, or holds a lone surrogate fails its row with a coded warning instead of passing through. A leaf list of integers with a null reaches the child as integers and a null (it was `float64` with `NaN`, which `hash` refused), and a child output of `NaN` is written as JSON `null`. Pre-GA behavior change; see the compatibility contract.

New warning codes: `warning/nested_cell_oversized`, `warning/nested_cell_too_deep`, `warning/nested_cell_duplicate_key`, `warning/nested_cell_number_out_of_range` and `warning/nested_child_non_finite`.
