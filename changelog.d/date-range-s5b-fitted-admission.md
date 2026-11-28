### Changed (fitted datetime range, DATE-RANGE-SENTINEL S5b, 2026-11-28)

The fitted datetime sampler refuses a snapshot it cannot hold, before it draws anything, with `plan/generation_unbounded_column`. The error names the property (`min`, `max` or `year_bins`) and never a value.

- A fitted bound outside 1677-09-22 to 2262-04-10 now refuses with `FittedRangeError`. Before, it failed with an uncoded `OverflowError`, `OutOfBoundsDatetime` or `ValueError` that could quote a date.
- Behavior change on `ColumnGenerator.generate_column` (QA F7 is reversed): a live year bin outside the snapshot's min and max years now refuses with `year_bins`. Before, a bin past the max was clamped into the max year, and a bin before the min put every row on the min instant. Snapshots written by profiling never trip this, because the min, max and bins come from the same values. A snapshot with max before min still gives null cells.
- The statistical generator now refuses a live year bin past 9998 on plan compile and on `sample_column` with `plan/generation_unbounded_column`. Before, it failed at draw time with an uncoded `ValueError`. A far fitted bound with in-range bins, and a zero-weight far bin, still generate.
- The first and last partial years of the nanosecond range (1677 and 2262) now sample inside the snapshot's min and max.
