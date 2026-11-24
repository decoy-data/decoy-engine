Breaking: columns no rule changes are written exactly as stored in the source on every route (decimal and nullable int columns, and all-null or zero-row columns, keep their type, and a float NaN stays NaN instead of becoming null). Carried text still leaves as `string` while it fits 32-bit offsets, as before.

### Changed (one output assembler, UF-DOMAIN S1, 2026-11-22)

The full-frame, sequential and unified-slice routes now build output through one function,
`table_from_pandas_keeping_source_types`. It takes the source table, writes each untouched column
from the source Arrow column, and converts only the masked columns from pandas. Before, a
`decimal(12,2)` column that no rule changed came back as `decimal(3,2)`, a nullable `int64`
as `float64` on those routes, while the chunked route kept the source type. All routes now agree. The function checks that the frame still has the source's row
count, index and column order, and raises an `ExecutionError` (`runtime/output_assembly_rows_changed` or `runtime/output_assembly_columns_mismatch`) before any output exists if it does not. A carried `Int64` or `string` column keeps its pandas dtype hint.
