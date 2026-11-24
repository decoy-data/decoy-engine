Breaking: Parquet output with a null fixed-size list cell now raises `ParquetFixedListNullError` and publishes nothing.

### Fixed (Exact in-memory source handoff, FIXED-LIST-NULL, 2026-11-23)

The engine hands in-memory sources to the isolated child with their Arrow types and values intact. A plain run can return a fixed-size list with null cells in memory. When the child must write such a result as Parquet, `run_pipeline_isolated` returns a crashed result where it previously could raise in the caller. Parquet output reports `runtime/parquet_fixed_list_null` where it previously raised a raw Arrow error or published an unreadable file.
