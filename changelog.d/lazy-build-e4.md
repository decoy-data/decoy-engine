### Added (lazy source builder, RUN-STREAM-E4, 2026-11-15)

`decoy_engine.profile.build_lazy_source(table, descriptor)` returns the lazy backend for a local source: `LazySource` for Parquet, `CsvLazySource` for CSV, `FixedWidthLazySource` for fixed-width. It returns `None` for a compressed CSV, a cloud source and an unknown format, so a caller keeps its resident read. Building opens no data row and names `sources.<table>.path` in a refusal. The resident source builder now reads the same one format table, so a new format is added in one place.
