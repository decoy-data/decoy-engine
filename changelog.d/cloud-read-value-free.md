### Fixed (cloud profile reads no longer carry data in their errors, F25 G7-1, 2026-11-25)

A Parquet conversion failure on an S3 or GCS object, and a CSV schema read over a window that
mixes numbers and text, could put a data cell in the error text. Both now leave with fixed text.
A CSV column that mixes numbers and text is text in the schema. An
invalid-UTF-8 CSV no longer keeps its input bytes in the error.
