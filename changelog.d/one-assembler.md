Breaking: columns no rule changes are written exactly as stored in the source on every route (decimal, nullable int, large_string and all-null or zero-row columns keep their type, and a float NaN stays NaN instead of becoming null), and the pandas schema metadata lists only the masked and read columns.

### Changed (one output assembler, UF-DOMAIN S1, 2026-11-22)

The full-frame, sequential and unified-slice routes now build output through one function,
`table_from_pandas_keeping_source_types`. It takes the source table, writes each untouched column
from the source Arrow column, and converts only the masked columns from pandas. Before, a
`decimal(12,2)` column that no rule changed came back as `decimal(3,2)`, a nullable `int64`
as `float64` and a `large_string` as `string` on those routes, while the chunked route kept the
source type. All routes now agree. The function checks that the frame still has the source's row
count, index and column order, and raises before any output exists if it does not.
