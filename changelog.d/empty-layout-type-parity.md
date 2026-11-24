Breaking: `read_fixed_width` on a file with no record (or with `max_records=0`) now types each column by the layout, a text field as a pandas `string` column, so an untouched column of an empty fixed-width source is written with its declared type (`int64`, `float64` or `string`) on every route, not `null` on the resident routes.

### Fixed (empty fixed-width type parity, EMPTY-LAYOUT-PARITY, 2026-11-24)

An empty fixed-width file written to a Parquet target gave different column types on the lazy
and resident runs. The lazy source takes its schema from the layout. The resident read built its
frame from the records, so with none every column was `object` and converted to Arrow `null`.
Since 0.28.4 writes an untouched column from the source table, the resident run wrote that `null`.
`read_fixed_width` now builds the zero-record frame from the layout, and the lazy and resident
readers share one layout-to-Arrow type map (`layout_arrow_schema`).
