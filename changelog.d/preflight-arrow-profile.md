### Fixed (bounded Parquet profile recovers unholdable dates and times, PREFLIGHT-ARROW-PROFILE, 2026-11-25)

A Parquet file can hold a `time64[ns]` value with a sub-microsecond part or a date outside
years 1 to 9999. Arrow reads it, but converting the first 10,000 rows to pandas failed, so
`estimate_job_capacity` returned `capacity_source_unprofilable` for a file the run publishes
exactly. The bounded profile now tries the whole sample through pandas first, as before. Only
when that conversion fails on a flat Parquet file (local, S3 or GCS) made of date32,
time64[ns], text and integer columns does it convert the sample column by column and profile
the failing date or time column from Arrow. A plain `run_pipeline` over such a file fails with
the coded `full_frame_value_unrepresentable`, and that error no longer chains the pyarrow error
that quoted the value.

A bounded profile of a Parquet file or a supplied table that still cannot be converted now
fails with `bounded source profile failed (<label>)`, with no value, name or pyarrow text. The
profile's duplicate-column `ValueError` now says "table 't' has N duplicated field name(s)"
without naming the columns.
