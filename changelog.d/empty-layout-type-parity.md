Breaking: `read_fixed_width` on a file with no record (or with `max_records=0`) now types each column by the layout, a text field as a pandas `string` column, so an untouched column of an empty fixed-width source is written with its declared type (`int64`, `float64` or `string`) on every route, not `null` on the resident routes. For an empty fixed-width source this also moves: full and bounded `profile` dtypes change from `object` to `string`, `int64` and `float64`, so `profile_hash` and the physical `plan_hash` change; head, random and full scans report `integer` and `float` for numeric fields; and a `when` that gives string output on a numeric field (for example `redact` with `when: c > 2` on an int field) is now refused with `when_string_output_on_numeric_unsupported`, as it already was on a non-empty file, where it used to return 0 rows.

### Fixed (empty fixed-width type parity, EMPTY-LAYOUT-PARITY, 2026-11-24)

An empty fixed-width file written to a Parquet target gave different column types on the lazy
and resident runs. The lazy source takes its schema from the layout. The resident read built its
frame from the records, so with none every column was `object` and converted to Arrow `null`.
Since 0.28.4 writes an untouched column from the source table, the resident run wrote that `null`.
`read_fixed_width` now builds the zero-record frame from the layout, and the lazy and resident
readers share one layout-to-Arrow type map (`layout_arrow_schema`).
