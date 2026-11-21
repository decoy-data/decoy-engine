### Fixed (numeric profile chart on a subnormal edge, 2026-11-21)

A numeric column whose range reaches a subnormal float (for example a maximum near 2e-313) made the profiler's 10-bin chart raise a `ValueError` from pandas, so `distribution_snapshot_document` and `profile_columns` refused a legal column. The chart now falls back to bin codes and edges, with the same labels. Output for every other column is unchanged.
