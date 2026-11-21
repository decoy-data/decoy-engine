Breaking: `date_shift` on a number, boolean or decimal column (for example an `int64` holding `20240115` with a `date_format`) is now refused at compile; write the column as text first.

### Changed (date_shift on typed dates, COLUMN-SHAPE-RULE E1b, 2026-11-21)

`date_shift` now runs on a column that is already a date or a zoned timestamp (Parquet, DuckDB, a database or an Arrow table) with no `date_format`. The column's type comes from its source schema. The output keeps the type: a date stays a date, and a zoned timestamp keeps its unit, its zone and its time of day, moving by whole days. Before, a typed date was written back as text. A typed date and the same date as ISO text in one namespace get the same offset.

A `date_format` set on such a column is not used, and compile adds the warning `plan/column_shape_format_unused`. A timestamp with no time zone, a number, a boolean or a decimal is refused at compile with `plan/column_shape_mismatch`. Before, a naive timestamp failed on the first row (`timezone_naive_datetime`), and a number column with a `date_format` (an `int64` holding `20240115`) was parsed as a date; write such a column as text first. `preserve_values` needs no `date_format` on a typed column. A text column still needs its format (`date_shift_requires_date_format`). Both new reasons are pending.

`decoy validate` (the config-only check) no longer refuses a missing `date_format` on a Parquet, database or Arrow column, because it cannot tell a date from text without the schema. A CSV or fixed-width column is still refused there, and `validate compile` and `run` refuse a text column with no format.
