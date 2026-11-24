### Fixed (bounded profile reads Arrow, PREFLIGHT-ARROW-PROFILE, 2026-11-24)

The bounded source profile of a Parquet file (local, S3, GCS) or a supplied `pa.Table` is
computed from the Arrow sample with `pyarrow.compute`, not through pandas. It reads the
pandas schema metadata as `to_pandas` did, so a pandas-written file profiles the same
columns and dtypes as before. A `time64[ns]` value with a sub-microsecond part or a date
outside years 1 to 9999 in the first 10,000 rows no longer makes `profile_source` raise, so
`estimate_job_capacity` no longer returns `capacity_source_unprofilable` for such a valid
file, and a plain `run_pipeline` over it fails with the coded
`full_frame_value_unrepresentable` instead of a raw pyarrow error. That coded error no
longer chains the pyarrow error, which quoted the value. Two values move: a supplied table
column of these types with no missing value reports `avg_length` and `max_length` as None
(before: the length of its text form), and the profile's duplicate-column `ValueError` now
says "table 't' has N duplicated field name(s)" without naming the columns.
