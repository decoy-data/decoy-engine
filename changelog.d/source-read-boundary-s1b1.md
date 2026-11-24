### Changed (every source read goes through one conversion, SOURCE-READ-BOUNDARY S1b-1, 2026-11-24)

A source column that pandas cannot hold, such as a `date32` past year 9999 or a `time64[ns]` with
non-zero nanoseconds, now fails with a coded error that names the table and column and carries no
value. The error text of pandas and Arrow quotes the cell, so it is never shown. The full-frame,
sequential and chunked routes keep `full_frame_value_unrepresentable`. Profile, scan and fidelity
reads raise the new `runtime/source_column_unrepresentable`. The post-scan check raises
`runtime/post_scan_column_not_inspectable`, and the post-mask check marks the column with
`runtime/postmask_column_not_inspectable` and reports it as an error finding, even for a column with no configured strategy, so neither check
passes a column it did not read. A resident table with such a column used to be profiled as text and
now fails the profile read the same way.

Experimental: `arrow_to_frame`, `arrow_to_series` and `arrow_to_frame_pair` are exported as experimental names.
Each takes a required `on_unrepresentable(column)` callback that must raise.
