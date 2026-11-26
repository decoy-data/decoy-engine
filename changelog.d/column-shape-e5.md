### Added (Strategy shapes in the catalog, COLUMN-SHAPE-RULE E5, 2026-11-26)

`StrategyInfo.shape` says which column shapes a strategy reads: its family, the column-entry field that declares how to read text (`provider_config.date_format` or `logical_type`), and the shapes it admits. It is read from the plan check's own shape table. `decoy_engine.profile.source_schema(reader)` is now public. The scan records each column's observed shape on `FieldStats.shape` for the starter; scan and profile documents do not carry it.

### Changed (Starter writes date_format only for text dates, COLUMN-SHAPE-RULE E5, 2026-11-26)

The starter config writes `date_format` for a date column that is text or of unknown shape, as before. For a typed date (a Parquet date or zoned timestamp) it writes a `date_shift` with no `date_format`.
