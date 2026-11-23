Status: plan

# PREFLIGHT-ARROW-PROFILE: the bounded source profile reads Arrow, so preflight no longer refuses a valid Parquet file whose values pandas cannot hold

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 1, for Dennis R1. Roadmap row: PREFLIGHT-ARROW-PROFILE (CLI `docs/roadmap/groups/run.md`, 1.0, function break). Anchors are in this repository (decoy-engine) at `origin/main` `26091c834` unless marked `cli:` (decoy CLI `origin/main` `95362d16`) or `#399:` (CLI PR #399, branch `feat/chunked-run-mask-chunked-s2`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `reuse-first.md`, `proportionality.md`, `architecture.md` (design principles, layout), `cross-cutting-concerns.md`, `testing.md` (test depth), `api-and-compatibility.md`, `catalogs/recurring-defects.md` (11 classes). Engine `CODEMAP.md` "Where Things Go"; `changelog.d/README.md`.

Risk: R2. It changes how every bounded source profile is computed (the input to routing, plan compile and the capacity estimate) and moves one module. No serialization, public-signature or reason-code change. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes (shared profile input to every route; moved module imported by tests).

## 1. Frame

### 1.1 Symptom

`decoy run` calls `estimate_job_capacity` during preflight (`cli:src/decoy/cli/preflight.py:421`). That calls `profile_source` (`src/decoy_engine/execution/capacity.py:322-323`). For a Parquet source, the bounded profile reads the first rows with `iter_batches` and then converts them with `to_pandas()` (`src/decoy_engine/profile/_readers.py:477-499`, `head_frame_from_batches`, reached from `ParquetFileSource.sample_frame` at `:408-411`). A valid Parquet file whose sample holds a value pandas cannot hold raises in that conversion. `capacity.py:324-339` re-raises it as `capacity_source_unprofilable`, and the CLI reports `capacity.source_unreadable`, "source not parsed", exit 1 (`cli:src/decoy/cli/preflight.py:433-440`). This applies to plain and `--chunked` runs alike.

The pandas conversion is a default on the shipped path. The owner rule is that pandas is never a shipped default.

### 1.2 What the probes showed

Probes ran on the devbox, pyarrow 24.0.0, pandas 2.3.3, against `origin/main` `26091c834`. Scripts stay in the author's scratch.

Probe A, `pq.write_table` then `pq.read_table(...).to_pandas()`, one column:

| Column | Parquet type read back | `to_pandas()` |
|---|---|---|
| `time64[ns]`, a value with a sub-microsecond part | `time64[ns]` | `ArrowInvalid: Value 1 has non-zero nanoseconds` |
| `time64[ns]`, whole microseconds only | `time64[ns]` | ok, `object` |
| `date32`, year -768 or year 10183 | `date32` | `ValueError: year ... is out of range` |
| `date64`, year 10183 | `date32` | `ValueError` |
| `timestamp[s]`, `[ms]`, `[us]` far from 1970 | as written (s becomes ms) | ok (pandas 2 non-ns units) |
| `duration[ns]`, `time32[ms]`, `time64[us]` | as written | ok |

So the failing set on this stack is `time64[ns]` with a sub-microsecond part and dates outside years 1 to 9999. Timestamps are not in it.

Probe B, the engine on these files (config: one passthrough column `t`, one redacted `email`, no relationships):

| Call | `time64[ns]` sub-µs | `date32` year -768 | `int64` control |
|---|---|---|---|
| `profile_source` | raises `ArrowInvalid` | raises `ValueError` | ok |
| `estimate_job_capacity` | `capacity_source_unprofilable` | `capacity_source_unprofilable` | `NOT_APPLICABLE` |
| `run_pipeline`, source as `LazySource` (how the CLI plain run passes it, `cli:src/decoy/cli/run/_execute.py:296-330`) | raw `ArrowInvalid` from the profile | raw `ValueError` from the profile | ok |

Probe C, the sample size. An 80,001-row file with one bad value at row `k`: `k = 9,999` is refused; `k` in {10,000, 15,000, 19,999, 20,000, 30,000} is priced, with and without 20,000-row row groups. The capacity sample is 10,000 rows (`profile_source` default `sample_rows=10_000`, `src/decoy_engine/profile/_source.py:66`). The "20,000-row capacity sample" in `#399:CHANGELOG.md` and in the `#399:tests/e2e/test_run_chunked_parquet.py` comment is wrong; the 20,000 there is the chunked run's first chunk.

Probe D, a throwaway prototype (reverted): the bounded profile of Parquet and resident sources built from the Arrow sample with the existing `arrow_column_profile` (`src/decoy_engine/execution/_chunked_profile.py:196-264`), wrapped with the walk's table-level fields (row count, `sampled`, candidate key, PK, FK). Compared field by field with today's `walk_dataframe` over the same bounded sample:

| Source | Cells | Equal | Different |
|---|---|---|---|
| Parquet file | 205 (test-20 cases, every type-catalogue entry with and without a null, list, struct, map, the two bad types) | all 178 that Parquet can store and pandas can profile | none; the 2 bad types and `fixed_shape_tensor` now profile where base raised |
| Resident `pa.Table`, total = sample and total = 10 x sample | 410 | 380 | `time64[ns]` with no null: `avg_length` 18.0 and `max_length` 18 become None (see 6.1); the other 28 are cells where base raised and the prototype returns |

With the prototype, `estimate_job_capacity` returns `NOT_APPLICABLE` for both bad files, and the plain `run_pipeline` gets past the profile and stops at the existing coded refusal `full_frame_value_unrepresentable` (`src/decoy_engine/execution/_pipeline_full_frame.py:60-90`), which names the table and column and no value.

### 1.3 Impact under the V1 bar

- Function break: a valid Parquet source is refused at preflight on every run mode. On `--chunked`, the engine route behind the refusal publishes these values exactly (`#399:` `test_at_c12_default_runs_exact_and_no_native_fails`), so the refusal blocks a working run.
- The plain Python API run fails with a raw, uncoded pyarrow error from the profile.
- Not a leak: the CLI message names only the exception class.

## 2. Root cause

One cause: the bounded profile converts an Arrow sample to pandas before it computes any statistic, for readers that already hold Arrow. `ParquetFileSource`, `S3ParquetSource`, `GcsParquetSource` (`_cloud_readers.py:109-116`, `_read_parquet_sample`) and `ResidentTableSource` (`_readers_resident.py:16-29`) all build a `pa.Table` and then call `to_pandas()`. `_profile_one_source` (`_source.py:217-303`) only accepts a DataFrame (`walk_dataframe`).

`ResidentTableSource._frame_of` already works around the same fault by casting a failing column to text. That is a patch at one reader, and it changes the statistics (Probe D).

Not the cause: `capacity.py`'s narrow catch is correct for a corrupt file, and the CLI mapping is correct for that case. Neither changes.

## 3. Guarantee

This row promises:

1. The bounded profile (`residency="bounded"`, the default and the only production mode) of a source whose reader holds Arrow (local Parquet, S3 Parquet, GCS Parquet, a supplied `pa.Table`) computes every `ColumnProfile` field from the Arrow sample with `pyarrow.compute`, with no pandas conversion.
2. For every column pandas can convert today, every `ColumnProfile` and `TableProfile` field equals today's value. The one number that moves is named in 6.1 and frozen by AT-8.
3. `estimate_job_capacity`, `estimate_job`, `run_pipeline`'s routing facts and the physical snapshot (every `profile_source` caller, section 5) no longer fail on a `time64[ns]` sub-microsecond value or an out-of-range date in the sample.
4. A truncated, corrupt or wrong-format source still raises `capacity_source_unprofilable` from `estimate_job_capacity`, and the CLI still reports `capacity.source_unreadable`.
5. CLI: `decoy run` and `decoy validate preflight` no longer refuse these sources at preflight. The run then does what its route does today with the same value past the sample.

Non-goals (recorded follow-ups, not blockers):

- G-1. A plain `decoy run` of these sources still fails, now with the coded `full_frame_value_unrepresentable` (exit 3) in place of the preflight refusal (exit 1). Running them on a plain route without pandas is a separate row (decision D1).
- G-2. CSV and fixed-width profiles stay on pandas: their readers produce pandas frames, and their columns are text.
- G-3. `residency="full"` keeps `walk_dataframe` (no production caller; `git grep 'residency="full"' src` finds only docstrings).
- G-4. `decoy scan` (`src/decoy_engine/profiling/scan_set.py:339`, `reader.sample_frame`) and the chunked first-chunk profile (`_chunked_profile.walk_one_table`) still convert to pandas. Both feed pandas consumers (detectors, the oracle). Follow-up row (D5).
- G-5. Whether `full_frame_value_unrepresentable` keeps the raw pyarrow error (which quotes the value) in `__context__` (class 3) is not checked here. The builder records the observation; a positive result is a follow-up.

## 4. Established solutions

### 4.1 Search run

- External: Apache Arrow "Pandas Integration" (https://arrow.apache.org/docs/python/pandas.html): `date32` converts to `datetime.date` objects and `time64` to `datetime.time`, so values outside Python's ranges (years 1 to 9999, microsecond time) cannot convert. Arrow compute reference (https://arrow.apache.org/docs/python/compute.html, `CountOptions` at https://arrow.apache.org/docs/python/generated/pyarrow.compute.CountOptions.html): `count_distinct(mode="only_valid")` gives an exact distinct count of non-null values; `is_null`, `is_nan`, `utf8_length`, `sum` and `max` give the rest. ARROW-16808 (https://issues.apache.org/jira/browse/ARROW-16808) reported wrong `count_distinct` results over multi-chunk input; the existing code calls `combine_chunks()` first, and AT-3 has a multi-row-group cell. ARROW-3176 (https://issues.apache.org/jira/browse/ARROW-3176, date overflow through pandas) is the same class from the other side.
- Alternatives looked at: ydata-profiling (pandas-based, rejected for the same reason); Polars `describe` (a new dependency, and the owner turned Polars masking off); DuckDB `SUMMARIZE` (`approx_unique` is approximate, so numbers would move).
- In this repository: `arrow_column_profile` (`execution/_chunked_profile.py:196-264`, B1 rev9) already computes a `ColumnProfile` from Arrow with `pyarrow.compute`, matching `walk_dataframe` field by field; `tests/native/test_chunked_entry_rev9_profile.py` (acceptance test 20) pins that over 60-plus shapes. `ParquetFileSource` already reads the sample with `ParquetFile.iter_batches`. The `sample_frame` conformance matrix (`tests/unit/profile/test_sample_frame_contract.py`, sentry `tests/sentry/profiling/test_profile_source_contract_coverage.py`) is the house pattern for a reader contract.

### 4.2 What the design follows

Reuse `arrow_column_profile` as the one column walk for Arrow samples, moved into the profile package. Reuse `iter_batches` for the sample. The only new code is the table-level wrapper (the same fields `walk_dataframe` sets for row count, `sampled`, candidate key, PK and FK) and an Arrow sample method on four readers.

### 4.3 Rejected

- CLI-only fallback: skip the capacity estimate on the `--chunked` route. It hides the symptom on one CLI path. The plain run, `decoy validate preflight`, `estimate_job` and the Python API keep failing in the same profile, and the chunked run loses a real check. It does not fix the cause (decision D2).
- Catch the conversion error and cast the column to text, as `_frame_of` does. It changes `avg_length` and `max_length` (Probe D) and keeps pandas on the default path.
- `to_pandas(...)` options (`date_as_object`, `coerce_temporal_nanoseconds`): none makes a `datetime.time` hold nanoseconds or a `datetime.date` hold year 10183.

## 5. Callers checked

| Caller | Path | After this row |
|---|---|---|
| `estimate_job_capacity` | `execution/capacity.py:323` | fixed (bounded profile) |
| `estimate_job` | `execution/_job_estimate.py:150`; its lifecycle Parquet sample (`pipeline/_lifecycle_inputs.py:66-75`) is already Arrow | fixed |
| `run_pipeline` routing facts | `execution/pipeline/_routing_facts.py:90` | fixed; the route then decides (G-1) |
| Physical snapshot | `execution/physical/_snapshot.py:166` | fixed |
| CLI preflight | `cli:src/decoy/cli/preflight.py:421` (through `estimate_job_capacity`) | fixed, no CLI source change |
| CLI demo | `cli:src/decoy/cli/demo.py:243` (bundled demo data) | unaffected |
| `decoy scan` | `profiling/scan_set.py:339` (`sample_frame`) | unchanged (G-4) |
| Lifecycle fixed-width sample | `pipeline/_lifecycle_inputs.py:83` (`sample_frame` then `from_pandas`) | unchanged (G-2) |
| Chunked first-chunk profile | `execution/_chunked_profile.py:36-53` | unchanged (G-4); its import of `arrow_column_profile` moves |

## 6. Behaviour table

"Bad value" means a `time64[ns]` value with a sub-microsecond part, or a `date32`/`date64` value outside years 1 to 9999.

| Case | Today | After |
|---|---|---|
| `profile_source`, local Parquet, bad value in the first 10,000 rows | raises `ArrowInvalid` or `ValueError` | returns; the column has `dtype="object"`, exact `null_count` and `distinct_count`, `avg_length=None`, `max_length=None`, and the `shape` the same type gets without the bad value |
| Same, bad value after row 10,000 | returns | returns, unchanged |
| `profile_source`, S3 or GCS Parquet, bad value in the sample | raises | returns, as the local row |
| `profile_source`, supplied `pa.Table`, bad value, no missing value | returns via the text cast, `avg_length` = text length | returns, `avg_length=None`, `max_length=None` (6.1) |
| `profile_source`, any column pandas converts | returns | returns, every field equal |
| `estimate_job_capacity`, bad value in the sample | `capacity_source_unprofilable` | a verdict equal to the verdict for the same file with the bad value replaced |
| `estimate_job_capacity`, truncated or non-Parquet file | `capacity_source_unprofilable` | unchanged |
| `estimate_job_capacity`, duplicate column names | `capacity_source_unprofilable` (the walk's `ValueError`) | unchanged, same message |
| `run_pipeline`, plain, `LazySource`, bad value | raw `ArrowInvalid`/`ValueError` from the profile | `ExecutionError` `full_frame_value_unrepresentable` (existing code) |
| CLI `decoy run --chunked`, default native, bad value at row 0 | exit 1, `capacity.source_unreadable` | exit 0, the column published exactly |
| CLI `decoy run --chunked --no-native`, bad value at row 0 | exit 1 | exit 3, `chunked_passthrough_value_unrepresentable`, no value in the output |
| CLI `decoy run --chunked`, a `when:` reads the column | exit 1 | exit 3, `chunked_passthrough_value_unrepresentable` |
| CLI `decoy run` plain, bad value at row 0 | exit 1, `capacity.source_unreadable` | exit 3, `full_frame_value_unrepresentable`, no output file |
| CLI `decoy validate preflight`, bad value | FAIL `capacity.source_unreadable` | no such finding |
| CLI, corrupt Parquet | FAIL `capacity.source_unreadable`, exit 1 | unchanged |
| CLI, bad value at row 80,000 (`#399:` `TestLateRefusedValue`) | as pinned in `#399` | unchanged |

### 6.1 The number that moves

A supplied `pa.Table` (no descriptor) with a bad-value column and no missing value: today `_frame_of` casts it to text, so pandas sees strings and reports the text form's `avg_length` and `max_length` (18 for a `time64[ns]` value). After: None, which is what pandas reports for a `time64` or `date32` column it can convert. `dtype`, `null_count`, `distinct_count` and `shape` do not move (the cast is one-to-one). The capacity path never sees a supplied table. `avg_length` feeds only the HC-7 free-text advisory, which reads text columns. AT-8 freezes the new value.

## 7. Failure modes

| ID | Failure | Guard |
|---|---|---|
| F-1 | The Arrow walk drifts from `walk_dataframe` on a type pandas converts, so routes, plan hashes and advisories move | AT-3 over the test-20 cases, the type catalogue and nested types, through every Arrow reader; plan YAML equality cells |
| F-2 | A reader keeps a hidden `to_pandas` on the bounded path | AT-4 conversion spy (the choke-point guard) |
| F-3 | The sample is longer or shorter than `sample_rows` | AT-6 and the conformance matrix for `sample_table` (AT-10) |
| F-4 | Table-level fields (total row count, `sampled`, candidate key, PK, FK, `row_count_exact`) are lost in the wrapper | AT-3 cells with a total larger than the sample, AT-3 PK/FK cell, AT-1 FK cell |
| F-5 | A corrupt file is reported as priced, or a new exception type escapes the narrow catch | AT-5 |
| F-6 | `count_distinct` over a multi-chunk sample (ARROW-16808) | AT-3 multi-row-group cell |
| F-7 | A type with no compute kernel raises instead of giving `distinct_count=None` | AT-3 union, `fixed_shape_tensor`, list, struct and map cells |
| F-8 | A cloud reader keeps the pandas sample | AT-4, AT-9 |
| F-9 | The move of `arrow_column_profile` changes the chunked first-chunk profile | AT-11 |
| F-10 | The RNG state seen by later tables changes | The bounded walk never draws from `rng` (`walk_dataframe` samples internally only when the frame exceeds `sample_rows`, which a bounded sample cannot). AT-3 profiles a two-table config in one call |

## 8. Design

One mechanism: a reader that holds Arrow hands the profile an Arrow sample, and the profile walks it with `pyarrow.compute`.

1. `profile/_walk_arrow.py` (new) receives `arrow_column_profile` and its private helpers (`_normalize`, `_missing_mask`, `_is_pandas_string`, `_dtype_label`, `_INT64_MIN`), moved unchanged from `execution/_chunked_profile.py`. It adds `walk_arrow_table(table, *, table_name, declared_pk_cols, fk_specs, total_row_count, source_format) -> TableProfile`: the duplicate-name check with the same `ValueError` text as `walk_dataframe` (both through `_field_names.repeated_names`), one `arrow_column_profile` per column, then the table-level fields exactly as `walk_dataframe` sets them (`row_count = total`, `sampled = total > len(table)`, candidate key only when not sampled, `declared_pk`, `is_fk`, `fk_target`). It takes no `rng` and no PII flag: the bounded path uses neither.
2. `profile/_readers.py`: `head_table_from_batches(batches, sample_rows, schema) -> pa.Table` is today's `head_frame_from_batches` without the final `to_pandas()`. `head_frame_from_batches` then calls it and converts, for its remaining `sample_frame` callers. A private `@runtime_checkable` protocol `ArrowSampleSource` declares `schema()` and `sample_table(sample_rows) -> pa.Table`, with the same "exactly n rows, short only at the end" contract as `sample_frame`. The public `ProfileSource` protocol does not change, so third-party readers are unaffected.
3. `ParquetFileSource`, `ResidentTableSource`, `S3ParquetSource` and `GcsParquetSource` gain `sample_table`. The three Parquet readers' `sample_frame` becomes `sample_table(n).to_pandas()`; the resident one keeps `_frame_of` (G-3, G-4, D4). `_read_parquet_sample` returns the table.
4. `profile/_source.py`, `_profile_one_source`, bounded branch: `isinstance(reader, ArrowSampleSource)` picks `walk_arrow_table(reader.sample_table(n), ...)`; any other reader keeps `sample_frame` plus `walk_dataframe`. `_nested_capable_schema` uses the same protocol in place of its four-class `isinstance` list, so "this reader holds Arrow" is one fact.
5. `execution/_chunked_profile.py` imports `arrow_column_profile` from `decoy_engine.profile._walk_arrow` (the same package edge it already has to `profile._walk`) for `first_chunk_profile`, and drops it from its `__all__`. The two test files that import it from there (`tests/native/test_chunked_entry_rev9_profile.py:78`, `tests/native/test_chunked_entry_rev9_catalogue.py:17`) import it from the new module. No re-export is left behind.

`capacity.py`, the CLI preflight and every reason code are unchanged.

### 8.1 Choke point

Rule: the bounded profile of an Arrow-holding reader never converts to pandas. It is enforced by construction in `_profile_one_source`, the one bounded profile site (`profile_source` is its only caller). Guard: AT-4 spies `pa.Table.to_pandas`, `pa.ChunkedArray.to_pandas`, `pa.Array.to_pandas`, `pa.RecordBatch.to_pandas` and `pd.read_parquet` during `profile_source` over each Arrow reader and requires zero calls. The mutation that must turn it red: M-1. A new Arrow reader is caught by the extended conformance sentry (AT-10), which fails until the class is in the `sample_table` matrix.

### 8.2 Design notes

- Principles: single responsibility (the reader samples, the walk measures) and one place per fact (the set of Arrow-holding readers, today an `isinstance` list, becomes one protocol with four members). The protocol earns its place: four implementations exist today.
- Pattern: Arrow compute kernels per the Arrow compute reference; the house reader-contract matrix.
- House style: typed keywords, no flag argument (the reader's type picks the walk), comments say why.

### 8.3 Size

Files: 1 new source (`profile/_walk_arrow.py`, about 190 lines, about 150 of them moved), 5 changed source files (`_readers.py` +30, `_readers_resident.py` +5, `_cloud_readers.py` +12, `_source.py` +10 and -8, `_chunked_profile.py` -150), 1 new test file, 4 changed test or sentry files (the two import lines, the contract matrix, the coverage sentry), 1 changelog fragment, `CODEMAP.md` rows 107 and 126. Public names added: none (`sample_table` is a method on existing reader classes; `ArrowSampleSource` and `walk_arrow_table` are private). A build past about 300 added source lines net stops and explains.

## 9. Acceptance tests

Red on base: the cell fails on `origin/main`. Green on base on purpose: a regression pin. Engine tests live in `tests/unit/profile/test_arrow_bounded_profile.py` unless named.

Fixtures: `T_NS` = 4 rows, `t: time64[ns]` with `3_600_000_000_000 + 987_654_321` at row 3; `D_FAR` = `t: date32` with `-1_000_000` (year -768) at row 3, and a twin with `3_000_000` (year 10183); each with an `email` string column. Config: `t` passthrough, `email` redact, seed 7.

- AT-1 (red on base). `estimate_job_capacity` on `T_NS` and both `D_FAR` files returns `NOT_APPLICABLE` and does not raise. FK cell: the parent/child pair of `tests/unit/execution/test_capacity_estimate_job.py` (`_ooc_config` with its `low_threshold` fixture) with a `T_NS` column added to the parent returns the same verdict and `needed_bytes` as the same pair with that column's bad value replaced by `1000`.
- AT-2 (red on base). `profile_source` on each fixture as local Parquet: column `t` has `dtype="object"`, `null_count=0`, `distinct_count=4`, `avg_length=None`, `max_length=None`, `sampled=False`, and the `shape` the same column gets with the bad value replaced. Also a 5-row cell with a null at row 1 (`null_count=1`, `distinct_count=4`).
- AT-3 (green on base on purpose, except the marked cells). Parity: for every `tests/native/_rev9_profile_cases.py` case, every `tests/native/_rev9_type_catalogue.py` entry with and without a null, and list, struct and map columns, the bounded `profile_source` result through a local Parquet file (where Parquet stores the type) and through a supplied `pa.Table`, with total = sample and total = 10 x sample (a resident table sliced from a larger one), equals `walk_dataframe(reader.sample_frame(n), ...)` field by field. The reference is computed in the test with `walk_dataframe`, kept as the oracle. Extra cells: a 25,000-row file written with 4,000-row row groups (multi-chunk sample, F-6); a two-table config profiled in one call (F-10); a config with declared PK and FK columns. Plan cells: `plan_to_yaml(compile_plan(...))` equal for the redact, hash, truncate and faker configs of test 20 over the Parquet cases. Red on base: the Probe D cells where base raised, asserted to return; their field values are pinned by AT-2 and AT-8 only.
- AT-4 (red on base). Conversion spy (8.1): `profile_source` over a local Parquet, a fake-fetch S3 Parquet, a fake GCS Parquet and a supplied `pa.Table` makes zero pandas conversions. A CSV control cell still converts, which keeps the spy honest.
- AT-5 (green on base on purpose). `estimate_job_capacity` raises `ExecutionError` `capacity_source_unprofilable` for a truncated Parquet file, a CSV file declared `parquet`, and a Parquet file with two columns named `a` (the chained `ValueError` message equal to base).
- AT-6 (red on base for the row-0 and row-9,999 cells). An 80,001-row `time64[ns]` file with the bad value at row 0, 9,999, 10,000 and 80,000: every `estimate_job_capacity` call returns a verdict; `profile_source` gives `row_count=80_001`, `row_count_exact=True`, `sampled=True`, and `null_count` and `distinct_count` over exactly the first 10,000 rows (asserted against `pyarrow.compute` over `table.slice(0, 10_000)`).
- AT-7 (red on base). `run_pipeline` with the `T_NS` and `D_FAR` sources as `LazySource`, with and without `resident_fallback=True`, raises `ExecutionError` with code `full_frame_value_unrepresentable`; the message holds no digit of the bad value. File: beside the existing `full_frame_value_unrepresentable` tests (`git grep -l full_frame_value_unrepresentable tests`), else a new `tests/unit/execution/test_full_frame_value_unrepresentable_profile.py`.
- AT-8 (red on base). The frozen number (6.1): a supplied `pa.Table` with sub-µs `time64[ns]` values and no null, and one with year-10183 dates and no null, profile with `avg_length=None` and `max_length=None`; `dtype`, `null_count`, `distinct_count` and `shape` equal base.
- AT-9 (red on base). `S3ParquetSource` and `GcsParquetSource` over the `T_NS` bytes (the fakes of `tests/unit/profile/test_duplicate_header_readers.py`): `sample_table(n)` equals the local `ParquetFileSource.sample_table(n)`, and `profile_source` returns the AT-2 column.
- AT-10 (red on base). `tests/unit/profile/test_sample_frame_contract.py` gains a `SAMPLE_TABLE_MATRIX` proving "exactly n rows, short only at the end" for the four `sample_table` readers, and `tests/sentry/profiling/test_profile_source_contract_coverage.py` gains the same owned-class walk for `sample_table`, with a seeded class that must be caught.
- AT-11 (green on base on purpose). `tests/native/test_chunked_entry_rev9_profile.py` and `tests/native/test_chunked_entry_rev9_catalogue.py` pass after the move with only their import line changed.

## 10. Mutations

Each alone on the final head; each must turn the named test red. Record the head (class 9).

| ID | Mutation | Red |
|---|---|---|
| M-1 | `_profile_one_source` sends Arrow readers through `sample_frame` and `walk_dataframe` | AT-1, AT-2, AT-4 |
| M-2 | `walk_arrow_table` sets `row_count` to the sample length | AT-3 total = 10 x cells, AT-6 |
| M-3 | `sampled` always False | AT-3 total = 10 x cells, AT-6 |
| M-4 | the candidate-key rule drops `not sampled` | AT-3 total = 10 x cells |
| M-5 | `declared_pk`, `is_fk` or `fk_target` not set (one mutation each) | AT-3 PK/FK cell, AT-1 FK cell |
| M-6 | `head_table_from_batches` does not slice to `sample_rows` | AT-6, AT-10 |
| M-7 | `S3ParquetSource.sample_table` returns `pa.Table.from_pandas(self.sample_frame(n))` (same for GCS) | AT-4, AT-9 |
| M-8 | `ResidentTableSource` lacks `sample_table`, so it falls back to the pandas walk | AT-4 resident cell, AT-8 |
| M-9 | the duplicate-name check is removed from `walk_arrow_table` | AT-5 duplicate cell |
| M-10 | the `ArrowNotImplementedError` catch around `count_distinct` is removed | AT-3 union and tensor cells |
| M-11 | `combine_chunks()` removed before the column walk | AT-3 multi-row-group cell, or recorded as an equivalent mutant on pyarrow 24 with the run output |
| M-12 | the sentry walk for `sample_table` skips one module | AT-10 seeded cell |

## 11. Class tables

dev-rules `catalogs/recurring-defects.md`:

| Class | This row |
|---|---|
| 1 anchored validation | n/a, no pattern |
| 2 strict types | n/a, `ColumnProfile` serialization unchanged |
| 3 exception context | AT-7 checks the message; `__context__` recorded under G-5 |
| 4 versioned read models | n/a |
| 5 guard scanners | AT-10 walks classes by `__dict__` like its sibling; covered shape: a class whose own body defines `sample_table` |
| 6 private imports | `execution/_chunked_profile.py -> profile._walk_arrow` replaces nothing new: the same module already imports `profile._walk`; no new package pair |
| 7 hidden CI failures | n/a |
| 8 trust classes | n/a |
| 9 mutations on the final head | section 10 |
| 10 allowlisted helpers | n/a |
| 11 raised caps | `_readers.py` stays under 800 lines (591 + about 30); `profile/` goes from 20 to 21 modules, under the fan-out limit 25; no pin moves |

Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes):

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | no new message; the capacity and full-frame refusals keep their value-free text, and the profile never renders a cell | AT-7 (no digit of the bad value); CLI cells in 13.1 check the `_LATE` markers | M-1 (the raw pyarrow error returns) |
| 2 | Cleanup missing on an exit path | N/A: the profile opens no new handle; `iter_batches` reads stay inside the existing `LazySource` and cloud-reader lifetimes | none needed | N/A: no new resource |
| 3 | State machine and concurrency | N/A: no shared state; the walk is a pure function of the sample, and it never draws from the profile `rng` | AT-3 two-table cell | N/A: no transition added |
| 4 | Route parity and silent fallback | one dispatch in `_profile_one_source`; every caller of `profile_source` (section 5) gets the same walk; no fallback to pandas on error | AT-3, AT-4 | M-1, M-7, M-8 |
| 5 | Referential integrity | PK and FK flags set by the wrapper exactly as `walk_dataframe` sets them | AT-3 PK/FK cell, AT-1 FK cell | M-5 |
| 6 | Untrusted producer | N/A: the input is the caller's own source file, read as today; no new parse of untrusted structure | none needed | N/A |
| 7 | Check then use on a path (TOCTOU) | N/A: the same readers open the same paths once, as today | none needed | N/A: no new check-then-open |
| 8 | Weak tests and overclaimed evidence | each AT records red or green on `26091c834`; parity uses `walk_dataframe` as an unchanged oracle; the 20,000 claim in `#399` was re-measured (Probe C) | builder report with base SHA and red output | each mutation names the AT it turns red |
| 9 | Behavior-preserving refactor drift | `arrow_column_profile` moves unchanged; first-chunk profile unchanged | AT-11, AT-3 | M-10, M-11 |
| 10 | Frozen contract drift | no public name, signature, reason code or serialized field changes; the one moved value is named (6.1) and frozen | AT-8, signature sentry unchanged | M-8 |

### 11.1 Frozen contracts

- Public API: no name or signature changes. `ProfileSource` (public protocol) is unchanged; the Arrow sample is a separate private protocol.
- `Profile` and `ColumnProfile` serialization (`profile_to_json`, `profile_hash`): no field added; every value equal for columns pandas converts (AT-3), so plan bytes and profile hashes do not move. The one moved value (6.1) is on a supplied-table path that today only reached the profile through the text cast.
- Reason registry: no code added; `capacity_source_unprofilable` and `full_frame_value_unrepresentable` keep their meaning.
- Byte changes: none to any output file.

### 11.2 Enumerations

#### Exit paths

Of `estimate_job_capacity` (`capacity.py:236-555`):

- The profile catch (`capacity.py:324-339`): now fires only for unreadable, corrupt or duplicate-named files (AT-5).
- No relationships, `NOT_APPLICABLE` (`capacity.py:341-346`): unchanged, now reachable for these sources (AT-1).
- Routing reject, not out-of-core, priced verdict (`capacity.py:368-555`): unchanged, now reachable (AT-1 FK cell).

#### Routes

Every caller of the bounded profile (section 5) takes the one dispatch in `_profile_one_source`:

- Capacity estimate (`execution/capacity.py:323`).
- Job estimate (`execution/_job_estimate.py:150`).
- `run_pipeline` routing facts (`execution/pipeline/_routing_facts.py:90`), for every route it then picks (full frame, sequential, out-of-core, unified slice, auto-chunk).
- Physical snapshot (`execution/physical/_snapshot.py:166`).
- `run_mask_chunked` and `run_mask_pipeline_chunked`: N/A, they build their own first-chunk profile (`execution/_chunked_profile.py:68-123`) and are unchanged (G-4).

#### Readers

| Reader | Bounded walk after |
|---|---|
| `ParquetFileSource` (local) | Arrow |
| `S3ParquetSource`, `GcsParquetSource` | Arrow |
| `ResidentTableSource` (supplied `pa.Table`) | Arrow |
| `CsvFileSource`, `S3CsvSource`, `GcsCsvSource` | pandas (G-2) |
| `FixedWidthFileSource` | pandas (G-2) |

#### FK shapes

N/A: the profile records `is_fk` and `fk_target` from config as before (AT-3 PK/FK cell); no FK path changes.

#### Fields

- Every `ColumnProfile` field (`name`, `dtype`, `row_count`, `null_count`, `distinct_count`, `sampled`, `is_candidate_key_sampled`, `declared_pk`, `is_fk`, `fk_target`, `pii_class`, `avg_length`, `max_length`, `shape`), built today at `profile/_walk.py:226-241`: compared by AT-3.
- `TableProfile.row_count` and `row_count_exact`, set at `profile/_source.py:287-303`: AT-6.
- `pii_class`: always None on this path (`profile_source` never asks for PII detection); AT-3 compares it.

#### Output surfaces

- Errors: the raw pyarrow profile error goes away on these paths; no new message (AT-1, AT-7).
- CLI stdout, `--json` and exit codes: per section 6 (13.1 cells).
- Returned profiles and plans: equal for columns pandas converts (AT-3).
- Logs, audit, evidence, progress: N/A, unchanged; the profile writes none.

### 11.3 Reuse inventory

- `arrow_column_profile` and its helpers (`execution/_chunked_profile.py`), moved unchanged.
- `ParquetFileSource` / `LazySource.iter_batches` and `_read_parquet_sample` for the sample.
- `_field_names.repeated_names` for the duplicate-name check.
- `observed_shape` (`profile/_walk.py`) for `shape`, already called by `arrow_column_profile`.
- The `sample_frame` conformance matrix and its coverage sentry, extended to `sample_table`.
- Test corpora: `tests/native/_rev9_profile_cases.py`, `tests/native/_rev9_type_catalogue.py`, the S3 and GCS fakes in `tests/unit/profile/test_duplicate_header_readers.py`, `_ooc_config` in `tests/unit/execution/test_capacity_estimate_job.py`.

## 12. Placement

| File | Directory | CODEMAP "Where Things Go" row | Sits beside |
|---|---|---|---|
| `_walk_arrow.py` (new) | `src/decoy_engine/profile/` | "Source readers, profile types": `src/decoy_engine/profile/_<reader>.py` | `_walk.py`, its pandas twin |
| `test_arrow_bounded_profile.py` (new) | `tests/unit/profile/` | "Source readers, profile types", tests in `tests/unit/profile/` | `test_bounded_profiling.py` |
| `preflight-arrow-profile.md` (new) | `changelog.d/` | "Changelog fragments" | the other fragments |
| `CODEMAP.md` (edit) | root | n/a | row 107: the Arrow column profile lives in `profile/_walk_arrow.py`; row 126: add `_walk_arrow.py` (the Arrow bounded walk) |

Changelog fragment, `changelog.d/preflight-arrow-profile.md`:

```
### Fixed (bounded profile reads Arrow, PREFLIGHT-ARROW-PROFILE, 2026-11-23)

The bounded source profile of a Parquet file (local, S3, GCS) or a supplied `pa.Table` is
computed from the Arrow sample with `pyarrow.compute`, not through pandas. A `time64[ns]` value
with a sub-microsecond part or a date outside years 1 to 9999 in the first 10,000 rows no longer
makes `profile_source` raise, so `estimate_job_capacity` no longer returns
`capacity_source_unprofilable` for such a valid file, and a plain `run_pipeline` over it now
fails with the coded `full_frame_value_unrepresentable` instead of a raw pyarrow error. Every
profile field is unchanged for columns pandas converts. One value moves: a supplied table
column of these types with no missing value reports `avg_length` and `max_length` as None
(before: the length of its text form).
```

No `Breaking:` line: no public name or signature changes.

## 13. Slices

| Slice | Repo | Content | Size | Risk |
|---|---|---|---|---|
| S1 | engine | Section 8 in full, AT-1 to AT-11, M-1 to M-12, changelog fragment, CODEMAP rows | about 260 source lines changed (about 150 moved), about 350 test lines; 12 files | R2 |
| S2 | engine | Release: compile the fragment with `scripts/release/stamp_release.py`, bump to the next patch version (0.28.4 if nothing else lands first), tag | release files only | R2 (established release path) |
| S3 | CLI | Repin to the S2 release per the engine repin checklist (compat, fences, FROZEN, doc, `PIN_PREFIX`, Dockerfile ARG, catalog); test and doc changes in 13.1 | pin files plus about 120 test lines; no CLI source logic change | R1 |

S1 is one slice: the move, the walk and the reader methods share the same tests, and the move alone has no consumer. S3 needs `#399` merged first (D3).

### 13.1 S3, CLI test and doc changes

- `test_at_c12_the_cli_preflight_refuses_these_sources_first` becomes `test_at_c12_the_cli_runs_these_sources`: through `decoy run --chunked`, default intent exits 0 and the `t` column equals the source exactly; `--no-native` exits 3 with `chunked_passthrough_value_unrepresentable` and none of the `_LATE` markers in the output; neither output says `source not parsed`.
- `test_at_c12_default_runs_exact_and_no_native_fails` and `test_at_c14_a_read_refused_value_is_coded_and_value_free` stop calling `_direct` (its reason, the preflight refusal, is gone) and run through the CLI with `--no-native` and a `when:` config. `_direct` is deleted if nothing else uses it.
- `TestLateRefusedValue`: behaviour unchanged. Its comment drops "past the 20,000-row preflight sample" and says the cells pin a bad value deep in the file. `test_default_run_publishes_the_value_exactly` is parametrized over the bad row {0, 80,000}, so the early-row case is pinned through the whole `decoy run` path.
- New: plain `decoy run` (no `--chunked`) on the two `_REFUSED_SOURCES` exits 3 with `full_frame_value_unrepresentable`, no bad-value marker, no output file (G-1).
- New: `decoy validate preflight` on the two sources reports no `capacity.source_unreadable`; a truncated Parquet still does (exit 1).
- Docs: remove the PREFLIGHT-ARROW-PROFILE carve-out from the `CHANGELOG.md` entry and say the preflight now accepts these sources; check the `decoy explain chunked`, `docs/cli-reference.md` and `run --help` text that `#399` names for the same sentence.

## 14. Pre-mortem

- A parity cell differs on a type the probe did not cover (for example a pyarrow 25 type). The catalogue skips missing factories; any new difference fails AT-3, and the type is fixed in `_walk_arrow.py` or listed in 6.1 with an owner call.
- Mac or Windows pandas differs. CI pins `pandas<3`; AT-3 computes its reference on the same host, so a host difference shows as a parity failure, not a silent change.
- A builder makes a parity cell pass by editing the oracle. The oracle is `walk_dataframe`, unchanged; a diff to `profile/_walk.py` in S1 is out of scope and the gate refuses it.

## 15. Open decisions

- D1. A plain `decoy run` of these sources still exits 3 (`full_frame_value_unrepresentable`) after this row. Accept for V1 and open a follow-up row to run plain-route passthrough columns without pandas? Recommended: yes. The refusal is coded and value-free, `--chunked` works, and the plain-route fix is a routing change, not a profile change.
- D2. Also ship the CLI-only fallback (skip capacity pricing on the `--chunked` route)? Recommended: no. After S1 the refusal is gone at its source on every path; skipping the check would only remove a working estimate.
- D3. Land the CLI test flip in a separate PR after `#399` and the S2 release, or fold it into `#399`? Recommended: a separate PR. `#399` works on the current pin and should not wait on an engine release. The wrong "20,000-row" sentence in `#399`'s CHANGELOG and test comment is corrected to 10,000 in `#399` before it merges, since it is a factual error, not a behaviour change.
- D4. Remove `ResidentTableSource._frame_of`'s text-cast fallback now that the bounded profile no longer reaches it? Recommended: no, not in this row. It still serves `to_frame` and `sample_frame` (G-3, G-4); the D5 row decides it.
- D5. Open one follow-up row for `decoy scan` and the chunked first-chunk profile (G-4)? Recommended: yes, one row, after the rows that block 1.0, since both feed pandas consumers today.
