Status: plan

# PREFLIGHT-ARROW-PROFILE: the bounded source profile reads Arrow, so preflight no longer refuses a valid Parquet file whose values pandas cannot hold

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 2, after Dennis R1 (NO-GO). Roadmap row: PREFLIGHT-ARROW-PROFILE (CLI `docs/roadmap/groups/run.md`, 1.0, function break). Anchors are in this repository (decoy-engine) at `origin/main` `26091c834` unless marked `cli:` (decoy CLI `origin/main` `95362d16`) or `#399:` (CLI PR #399, branch `feat/chunked-run-mask-chunked-s2`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `bugfix.md`, `reuse-first.md`, `proportionality.md`, `architecture.md`, `cross-cutting-concerns.md`, `testing.md` (test depth), `api-and-compatibility.md`, `catalogs/recurring-defects.md` (11 classes). Engine `CODEMAP.md` "Where Things Go"; `changelog.d/README.md`; engine `CLAUDE.md` (module size goal 600, max 700).

Risk: R2. It changes how every bounded source profile is computed (the input to routing, plan compile and the capacity estimate), moves one module and three schema helpers, and changes where one coded error is raised. No serialization, public-signature or reason-code change. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes (shared profile input to every route; moved helpers imported by shared test fixtures).

## 0. Rev 2 changes

| Dennis R1 finding | Fix in rev 2 | Where |
|---|---|---|
| BLOCKER: pandas `b"pandas"` metadata ignored (index fields become columns; nullable and extension dtypes drift) | The walk drops stored index fields and takes the dtype, the missing rule and the string-length rule from the metadata. The metadata helpers move into `_pandas_meta`, one parse, no copy, no profile-to-execution import. Re-probed: 432 of 432 cells equal | 1.2 Probe E, 3, 6, 8 items 1-2, AT-3b, M-13 to M-16 |
| BLOCKER, sub-question: does `iter_batches` keep the metadata | Yes, probed: each batch schema, the `from_batches` table and `ParquetFile.schema_arrow` carry the same `b"pandas"` blob as `read_table` | 1.2 Probe E |
| HIGH: AT-4 spy cannot patch `to_pandas` | Spy `pyarrow.pandas_compat.table_to_dataframe`, `pd.Series.__init__`, `pd.DataFrame.__init__`, `pd.read_parquet`; probed that these catch Table, RecordBatch, ChunkedArray and Array conversion; CSV control kept | 8.1, AT-4 |
| MEDIUM 1: module size is goal 600 / max 700; `_readers.py` is 591 | `head_table_from_batches` and `ArrowSampleSource` go in a new `profile/_arrow_sample.py`; `_readers.py` shrinks | 8 item 4, 8.3, 11 class 11, 12 |
| MEDIUM 2: the move breaks the column-shape sentry | `tests/sentry/test_column_shape_classifier.py:34` and `:113-120` and `tests/sentry/baselines/column-shape-classifier.json:17` edited to the new path; `tests/native/test_draw_site_inventory_coverage.py:241` unchanged | 8 item 7, 13 |
| MEDIUM 3: G-5 confirmed, `full_frame_value_unrepresentable` keeps a value-bearing `__context__` | Folded into S1: the coded error is raised after the handler exits; AT-7 asserts `__context__ is None` and `__cause__ is None` | 3, 6, 8 item 6, AT-7, M-17 |
| MEDIUM 4: D1 and D5 | Accepted; both follow-up rows tagged 1.0-blocking | 3 G-1, G-4, 15 |
| LOW: duplicate-name text has three copies | One message helper in `_field_names.py` for `walk_dataframe`, `walk_arrow_table` and `_guards.refuse_duplicate_field_names` | 6.1 (b), 8 item 5, AT-5 |
| LOW: CLI indirect callers not listed | `cli:src/decoy/cli/tokenize.py:353` and `cli:src/decoy/api.py:621` added | 5 |
| LOW: zero-row cells missing | Zero-row Parquet and zero-row resident cells in AT-3 and AT-3b | AT-3, AT-3b |

## 1. Frame

### 1.1 Symptom

`decoy run` calls `estimate_job_capacity` during preflight (`cli:src/decoy/cli/preflight.py:421`). That calls `profile_source` (`src/decoy_engine/execution/capacity.py:322-323`). For a Parquet source, the bounded profile reads the first rows with `iter_batches` and converts them with `to_pandas()` (`src/decoy_engine/profile/_readers.py:477-499`, `head_frame_from_batches`, reached from `ParquetFileSource.sample_frame` at `:408-411`). A valid Parquet file whose sample holds a value pandas cannot hold raises in that conversion. `capacity.py:324-339` re-raises it as `capacity_source_unprofilable`, and the CLI reports `capacity.source_unreadable`, "source not parsed", exit 1 (`cli:src/decoy/cli/preflight.py:433-440`). This applies to plain and `--chunked` runs alike.

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

So the failing set on this stack is `time64[ns]` with a sub-microsecond part and dates outside years 1 to 9999.

Probe B, the engine on these files (one passthrough column `t`, one redacted `email`, no relationships): `profile_source` raises `ArrowInvalid` or `ValueError`; `estimate_job_capacity` raises `capacity_source_unprofilable` (an `int64` control gives `NOT_APPLICABLE`); `run_pipeline` with the source as `LazySource` (how the CLI plain run passes it, `cli:src/decoy/cli/run/_execute.py:296-330`) raises the raw pyarrow error from the profile.

Probe C, the sample size. An 80,001-row file with one bad value at row `k`: `k = 9,999` is refused; `k` in {10,000, 15,000, 19,999, 20,000, 30,000} is priced. The capacity sample is 10,000 rows (`profile_source` default `sample_rows=10_000`, `src/decoy_engine/profile/_source.py:66`). The "20,000-row capacity sample" in `#399:CHANGELOG.md` and in the `#399:tests/e2e/test_run_chunked_parquet.py` comment is wrong; 20,000 is the chunked run's first chunk.

Probe D, a throwaway prototype: the bounded profile of Parquet and resident sources built from the Arrow sample with `arrow_column_profile` (`src/decoy_engine/execution/_chunked_profile.py:196-264`), wrapped with the walk's table-level fields, compared field by field with `walk_dataframe` over the same sample, over the test-20 cases, every type-catalogue entry with and without a null, list, struct and map. Parquet: all 178 cells Parquet stores and pandas profiles are equal. Resident (total = sample and total = 10 x sample): 380 of 410 equal; 28 are cells where base raised and the prototype returns; 2 are the 6.1 (a) move. With the prototype, `estimate_job_capacity` returns `NOT_APPLICABLE` for both bad files and a plain `run_pipeline` stops at `full_frame_value_unrepresentable` (`src/decoy_engine/execution/_pipeline_full_frame.py:56-90`).

Probe E (rev 2), the pandas-written corpus. Frames built in pandas with one column `x` of each of: `Int8`/`16`/`32`/`64`, `UInt8`/`16`/`32`/`64`, `boolean`, `string`, `string[pyarrow]`, `Float32`, `Float64`, categorical unordered and ordered, tz-aware `datetime64[ns, US/Central]`, `period[M]`, `interval`; each with and without a null; each with a RangeIndex, a named index (`set_index("k")`) and a filtered index (`df[df.index != 1]`); each at full and zero rows; each through `df.to_parquet` plus `ParquetFileSource` and through `pa.Table.from_pandas` plus `ResidentTableSource`. 432 cells.

- The rev 1 walk (no metadata): 12 of 216 cells equal (full-row only). Index fields `k` and `__index_level_0__` appear as columns; `Int*`/`UInt*` with a null report `float64` (pandas: `Int8` and so on), without a null `int8`; `boolean` reports `bool`/`object`; `string` reports `object` and `avg_length` None with a null; `Float32`/`64` report `float32`/`float64`; `period[M]` and `interval` report `object`. This confirms the BLOCKER.
- The rev 2 walk (8 items 1-3): 432 of 432 equal, including zero rows.
- The metadata lists each column's pandas dtype in `numpy_type`: the nullable dtype names, `string` for both string dtypes, `period[M]`, `interval[int64, right]`. Categorical (`numpy_type` is the code width) and tz-aware columns already match through the Arrow type and need no metadata.
- `interval` storage is a struct, and `count_distinct` has no struct kernel. The rev 2 walk counts distinct `(left, right)` pairs with `Table.group_by(...).aggregate([])`; that is what makes the interval cells equal.
- A `Float64` column whose Arrow data holds a NaN (not a null) under `Float64` metadata: pandas reads the NaN as not missing; the rev 2 rule (only an Arrow null is missing for a metadata-typed column) matches.
- `iter_batches` keeps the metadata: each `RecordBatch.schema`, the `pa.Table.from_batches` result and `ParquetFile.schema_arrow` carry a `b"pandas"` blob equal to the one `pq.read_table` gives. So the Arrow sample sees the same metadata as the pandas path did.

### 1.3 Impact under the V1 bar

- Function break: a valid Parquet source is refused at preflight on every run mode. On `--chunked`, the route behind the refusal publishes these values exactly (`#399:` `test_at_c12_default_runs_exact_and_no_native_fails`).
- The plain Python API run fails with a raw, uncoded pyarrow error from the profile.
- A leak on the plain run after the fix: Dennis showed `full_frame_value_unrepresentable` keeps the pyarrow error, which quotes the value, as `__context__`. S1 closes it (8 item 6).

## 2. Root cause

One cause: the bounded profile converts an Arrow sample to pandas before it computes any statistic, for readers that already hold Arrow. `ParquetFileSource`, `S3ParquetSource`, `GcsParquetSource` (`_cloud_readers.py:109-116`, `_read_parquet_sample`) and `ResidentTableSource` (`_readers_resident.py:16-29`) all build a `pa.Table` and then call `to_pandas()`. `_profile_one_source` (`_source.py:217-303`) only accepts a DataFrame.

`ResidentTableSource._frame_of` works around the same fault by casting a failing column to text. That is a patch at one reader, and it changes the statistics (Probe D).

Not the cause: `capacity.py`'s narrow catch is correct for a corrupt file, and the CLI mapping is correct for that case. Neither changes.

## 3. Guarantee

This row promises:

1. The bounded profile (`residency="bounded"`, the default and the only production mode) of a source whose reader holds Arrow (local Parquet, S3 Parquet, GCS Parquet, a supplied `pa.Table`) computes every `ColumnProfile` field from the Arrow sample with `pyarrow.compute`, with no pandas conversion.
2. For every column pandas can convert today, including pandas-written Parquet and `pa.Table.from_pandas` tables with any index and any nullable or extension dtype in the Probe E corpus, every `ColumnProfile` and `TableProfile` field equals today's value, and the column list is the same (stored index fields are not columns). The values that move are named in 6.1 and frozen by AT-8 and AT-5.
3. `estimate_job_capacity`, `estimate_job`, `run_pipeline`'s routing facts and the physical snapshot (every `profile_source` caller, section 5) no longer fail on a `time64[ns]` sub-microsecond value or an out-of-range date in the sample.
4. A truncated, corrupt or wrong-format source still raises `capacity_source_unprofilable` from `estimate_job_capacity`, and the CLI still reports `capacity.source_unreadable`.
5. `full_frame_value_unrepresentable` is raised with `__context__` and `__cause__` both None, so no rendering of the error chain carries the value.
6. CLI: `decoy run` and `decoy validate preflight` no longer refuse these sources at preflight. The run then does what its route does today with the same value past the sample.

Non-goals (recorded follow-ups):

- G-1. A plain `decoy run` of these sources still fails, now with the coded, value-free `full_frame_value_unrepresentable` (exit 3) in place of the preflight refusal (exit 1). Follow-up row, tagged 1.0-blocking: run plain-route passthrough columns without pandas (D1).
- G-2. CSV and fixed-width profiles stay on pandas: their readers produce pandas frames of text.
- G-3. `residency="full"` keeps `walk_dataframe` (no production caller; `git grep 'residency="full"' src` finds only docstrings).
- G-4. `decoy scan` and `init` (`src/decoy_engine/profiling/scan_set.py:339`, `reader.sample_frame`) raise a raw `ValueError` that contains the year on a valid Parquet file, and the chunked first-chunk profile (`_chunked_profile.walk_one_table`) still converts to pandas. Follow-up row, tagged 1.0-blocking (D5).

## 4. Established solutions

### 4.1 Search run

- Apache Arrow "Pandas Integration" (https://arrow.apache.org/docs/python/pandas.html): `date32` converts to `datetime.date` and `time64` to `datetime.time`, so values outside Python's ranges cannot convert. The same page documents the `b"pandas"` schema metadata that `from_pandas` and `to_parquet` write (index columns, per-column `pandas_type` and `numpy_type`) and that `to_pandas` reads to restore the index and extension dtypes; the walk reads the same fields.
- Arrow compute (https://arrow.apache.org/docs/python/compute.html; `CountOptions`): `count_distinct(mode="only_valid")` is exact; `is_null`, `is_nan`, `utf8_length`, `sum`, `max`, and `Table.group_by` for a struct's distinct rows. ARROW-16808 (wrong `count_distinct` over multi-chunk input): the code calls `combine_chunks()` first; AT-3 has a multi-row-group cell.
- Alternatives: ydata-profiling (pandas-based); Polars `describe` (new dependency, owner turned Polars masking off); DuckDB `SUMMARIZE` (`approx_unique` is approximate). Rejected.
- In this repository: `arrow_column_profile` (`execution/_chunked_profile.py:196-264`) computes a `ColumnProfile` from Arrow, pinned field by field by `tests/native/test_chunked_entry_rev9_profile.py` (test 20). `stored_index_fields` (`execution/_transforms.py:108`), `arrow_columns` (`profile/_declared_columns.py:75`) and `pandas_nullable_columns` (`execution/_mem_estimate_arrow.py:224`) already read the metadata. `_pandas_meta` (`src/decoy_engine/_pandas_meta/`) is the foundation package for pandas-metadata facts. The `sample_frame` conformance matrix (`tests/unit/profile/test_sample_frame_contract.py`, sentry `tests/sentry/profiling/test_profile_source_contract_coverage.py`) is the house pattern for a reader contract.

### 4.2 What the design follows

Reuse `arrow_column_profile` as the one column walk, moved into the profile package. Reuse the existing metadata readers, moved inward into `_pandas_meta` and sharing one parse. Reuse `iter_batches` for the sample.

### 4.3 Rejected

- CLI-only fallback (skip the capacity estimate on `--chunked`): hides the symptom on one CLI path; the plain run, `decoy validate preflight`, `estimate_job` and the API keep failing (D2).
- Catch the conversion error and cast to text, as `_frame_of` does: changes `avg_length` and `max_length` and keeps pandas on the default path.
- `to_pandas(...)` options (`date_as_object`, `coerce_temporal_nanoseconds`): none makes a `datetime.time` hold nanoseconds or a `datetime.date` hold year 10183.
- Take dtype labels from `schema.empty_table().to_pandas()`: zero rows cannot fail on a value, but it is a pandas conversion on the default path, and AT-4 could no longer require zero conversions.

## 5. Callers checked

| Caller | Path | After this row |
|---|---|---|
| `estimate_job_capacity` | `execution/capacity.py:323` | fixed |
| `estimate_job` | `execution/_job_estimate.py:150` | fixed |
| `run_pipeline` routing facts | `execution/pipeline/_routing_facts.py:90` | fixed; the route then decides (G-1) |
| Physical snapshot | `execution/physical/_snapshot.py:166` | fixed |
| CLI preflight | `cli:src/decoy/cli/preflight.py:421` (through `estimate_job_capacity`) | fixed, no CLI source change |
| CLI `decoy tokenize` | `cli:src/decoy/cli/tokenize.py:353` (`run_pipeline`, so the routing facts) | profile fixed; a plain route then raises the value-free `full_frame_value_unrepresentable` (G-1) |
| CLI Python API | `cli:src/decoy/api.py:621` (`run_pipeline`) | same as `tokenize` |
| CLI demo | `cli:src/decoy/cli/demo.py:243` (bundled demo data) | unaffected |
| `decoy scan` / `init` | `profiling/scan_set.py:339` (`sample_frame`) | unchanged (G-4) |
| Lifecycle fixed-width sample | `pipeline/_lifecycle_inputs.py:83` | unchanged (G-2) |
| Chunked first-chunk profile | `execution/_chunked_profile.py:36-53` | unchanged (G-4); its import of `arrow_column_profile` moves |

## 6. Behaviour table

"Bad value" means a `time64[ns]` value with a sub-microsecond part, or a `date32`/`date64` value outside years 1 to 9999.

| Case | Today | After |
|---|---|---|
| `profile_source`, local Parquet, bad value in the first 10,000 rows | raises `ArrowInvalid` or `ValueError` | returns; the column has `dtype="object"`, exact `null_count` and `distinct_count`, lengths None, and the `shape` the same type gets without the bad value |
| Same, bad value after row 10,000 | returns | returns, unchanged |
| `profile_source`, S3 or GCS Parquet, bad value in the sample | raises | returns, as the local row |
| `profile_source`, supplied `pa.Table`, bad value, no missing value | returns via the text cast | returns, lengths None (6.1 a) |
| `profile_source`, pandas-written Parquet or `from_pandas` table, any Probe E dtype and index | returns | returns, every field and the column list equal |
| `profile_source`, zero-row Parquet file or zero-row table | returns | returns, equal |
| `profile_source`, any other column pandas converts | returns | returns, every field equal |
| `estimate_job_capacity`, bad value in the sample | `capacity_source_unprofilable` | the verdict for the same file with the bad value replaced |
| `estimate_job_capacity`, truncated or non-Parquet file | `capacity_source_unprofilable` | unchanged |
| `estimate_job_capacity`, duplicate column names | `capacity_source_unprofilable`, chained `ValueError` naming the columns | same code; the chained message is the shared value-free text (6.1 b) |
| `run_pipeline`, plain, `LazySource`, bad value | raw `ArrowInvalid`/`ValueError` from the profile | `ExecutionError` `full_frame_value_unrepresentable`, `__context__` and `__cause__` None |
| `run_pipeline`, plain, resident `pa.Table`, bad value | `full_frame_value_unrepresentable` with the pyarrow error (value quoted) as `__context__` | same code, `__context__` None |
| CLI `decoy run --chunked`, default native, bad value at row 0 | exit 1, `capacity.source_unreadable` | exit 0, the column published exactly |
| CLI `decoy run --chunked --no-native`, bad value at row 0 | exit 1 | exit 3, `chunked_passthrough_value_unrepresentable`, no value in the output |
| CLI `decoy run --chunked`, a `when:` reads the column | exit 1 | exit 3, `chunked_passthrough_value_unrepresentable` |
| CLI `decoy run` plain, bad value at row 0 | exit 1, `capacity.source_unreadable` | exit 3, `full_frame_value_unrepresentable`, no output file |
| CLI `decoy validate preflight`, bad value | FAIL `capacity.source_unreadable` | no such finding |
| CLI, corrupt Parquet | FAIL `capacity.source_unreadable`, exit 1 | unchanged |
| CLI, bad value at row 80,000 (`#399:` `TestLateRefusedValue`) | as pinned in `#399` | unchanged |

### 6.1 The values that move

(a) A supplied `pa.Table` (no descriptor) with a bad-value column and no missing value: today `_frame_of` casts it to text, so pandas reports the text form's `avg_length` and `max_length` (18 for a `time64[ns]` value). After: None, which is what pandas reports for a `time64` or `date32` column it can convert. `dtype`, `null_count`, `distinct_count` and `shape` do not move. The capacity path never sees a supplied table; `avg_length` feeds only the HC-7 free-text advisory, which reads text columns. AT-8 freezes it.

(b) The duplicate-name `ValueError` from `walk_dataframe` (`profile/_walk.py:105-110`) names the repeated columns. After: it uses the shared text `table 't' has 1 duplicated field name(s)`, the text `_guards.refuse_duplicate_field_names` already uses. A header is producer-controlled text, so dropping it from the message is the value-free direction. Exception types are unchanged (`ValueError` from the walks, `TransformError` from the guard). `tests/unit/profile/test_invariants.py:107` and `tests/unit/profile/test_walk_edge_cases.py:31` change their `match=`. AT-5 freezes it.

No pandas-metadata type needed a move: Probe E is 432 of 432 equal.

## 7. Failure modes

| ID | Failure | Guard |
|---|---|---|
| F-1 | The Arrow walk drifts from `walk_dataframe` on a type pandas converts | AT-3 over the test-20 cases, the type catalogue and nested types, through every Arrow reader |
| F-2 | pandas metadata ignored: index fields profiled as columns, nullable or extension dtypes mislabelled, string lengths dropped, so `check_null_bearing_int_unsupported` (`plan/_checks.py:198-217`), the `when:` numeric check (`plan/_checks_correctness.py:110-113`), HC-7, profile hashes and the declared-columns exclusion (`profile/_declared_columns.py:75-80`) move | AT-3b over the Probe E corpus through local, S3, GCS and resident readers; M-13 to M-16 |
| F-3 | A reader keeps a hidden pandas conversion on the bounded path | AT-4 conversion spy |
| F-4 | The sample is longer or shorter than `sample_rows` | AT-6, AT-10 |
| F-5 | Table-level fields (total, `sampled`, candidate key, PK, FK, `row_count_exact`) lost | AT-3 total = 10 x cells, PK/FK cell, AT-1 FK cell, AT-6 |
| F-6 | A corrupt file is reported as priced, or a new exception type escapes the narrow catch | AT-5 |
| F-7 | `count_distinct` over a multi-chunk sample (ARROW-16808) | AT-3 multi-row-group cell |
| F-8 | A type with no compute kernel raises instead of `distinct_count=None` | AT-3 union, tensor, list, struct, map cells |
| F-9 | A cloud reader keeps the pandas sample or drops the metadata | AT-4, AT-3b S3/GCS cells, AT-9 |
| F-10 | The move changes the chunked first-chunk profile, or a sentry still names the old path | AT-11, the column-shape sentry run |
| F-11 | The profile draws from `rng` and later tables see a different state | the bounded walk takes no `rng`; AT-3 two-table cell |
| F-12 | The coded full-frame error still carries the value in its chain | AT-7 `__context__`/`__cause__` asserts; M-17 |
| F-13 | Moving the metadata helpers changes their answer for execution callers | their existing tests (`tests/unit/execution/test_mem_estimate_nullable_metadata.py`, `tests/native/test_unconfigured_passthrough.py:728`, `tests/unit/profile/test_declared_columns.py:337`) pass with only the import line changed |

## 8. Design

One mechanism: a reader that holds Arrow hands the profile an Arrow sample, and the profile walks it with `pyarrow.compute`, reading the pandas metadata for the facts `to_pandas` would have taken from it.

1. `_pandas_meta/_columns.py` (new, foundation tier, imports only `pyarrow` and `json`). One parse of the `b"pandas"` blob, malformed metadata giving empty results with the catch `pandas_nullable_columns` uses today:
   - `stored_index_fields(schema) -> set[str]`, moved from `execution/_transforms.py:108`.
   - `arrow_columns(schema) -> tuple[str, ...]`, moved from `profile/_declared_columns.py:75` (it loses its lazy import of `execution._transforms`).
   - `pandas_column_dtypes(schema) -> Mapping[str, str]` (new): field name to `numpy_type` for the columns whose pandas dtype is an extension dtype, which is the nullable set (`Int8` to `UInt64`, `Float32`, `Float64`, `boolean`, `string`) plus `period[...]` and `interval[...]`.
   - `pandas_nullable_columns(schema)`, moved from `execution/_mem_estimate_arrow.py:224` and redefined as the keys of `pandas_column_dtypes` whose value is in the nullable set, so both answers come from one parse.
   - `_pandas_meta/__init__.py` exports the four; its docstring says it now also holds the per-column facts.
   Callers change their import in place, with no re-export left behind: `execution/_transforms.py` (169, 202), `_transforms_table.py:58`, `native/_chunked_entry.py:49`, `native/_dispatch.py:471`, `_mem_estimate_arrow.py` (its own uses at 248-281), `_mem_estimate_schema.py:38`, `profile/_declared_columns.py` (105-508); tests `tests/_declared_schema.py:14`, `tests/native/_b8_support.py:37`, `tests/unit/profile/test_declared_columns.py:30`, `tests/unit/execution/test_mem_estimate_nullable_metadata.py:17`, `tests/native/test_unconfigured_passthrough.py:728`.
2. `profile/_walk_arrow.py` (new) receives `arrow_column_profile` and its helpers (`_normalize`, `_missing_mask`, `_is_pandas_string`, `_dtype_label`, `_INT64_MIN`), moved from `execution/_chunked_profile.py`. Changes on the move:
   - `arrow_column_profile` gains a keyword `pandas_dtype: str | None = None`. When set: `dtype` is `canonical_dtype_label(pandas_dtype)`; only an Arrow null is missing (no NaN or NaT rule, no float64 widening), as pandas' masked arrays do; string lengths are computed over the valid values when `pandas_dtype == "string"`; a struct storage (interval) counts distinct rows with `Table.group_by(...).aggregate([])`. When None, the function is unchanged, so the first-chunk profile is unchanged.
   - `walk_arrow_table(table, *, table_name, declared_pk_cols, fk_specs, total_row_count, source_format) -> TableProfile` (new): the duplicate-name check (item 5); the columns are `arrow_columns(table.schema)`; each gets `arrow_column_profile(..., pandas_dtype=pandas_column_dtypes(schema).get(name))`; then the table-level fields exactly as `walk_dataframe` sets them (`row_count = total`, `sampled = total > len(table)`, candidate key only when not sampled, `declared_pk`, `is_fk`, `fk_target`). No `rng`, no PII flag.
3. Readers: `ParquetFileSource`, `ResidentTableSource`, `S3ParquetSource` and `GcsParquetSource` gain `sample_table(sample_rows) -> pa.Table`, schema metadata kept. The three Parquet readers' `sample_frame` becomes `sample_table(n).to_pandas()`; the resident one keeps `_frame_of` (D4). `_read_parquet_sample` returns the table.
4. `profile/_arrow_sample.py` (new, about 45 lines): `head_table_from_batches(batches, sample_rows, schema) -> pa.Table` (today's `head_frame_from_batches` without the `to_pandas()`, keeping the schema metadata), and the private `@runtime_checkable` protocol `ArrowSampleSource` (`schema()`, `sample_table(sample_rows)`, contract "exactly n rows, short only at the end"). `_readers.py` keeps `head_frame_from_batches` as a two-line call into it for its `sample_frame` callers, so it shrinks. The public `ProfileSource` protocol does not change.
5. `_field_names.py` gains `duplicate_names_message(table, names) -> str | None`, the one text (`table {table!r} has {n} duplicated field name(s)`). `walk_dataframe` and `walk_arrow_table` raise `ValueError(message)`; `_guards.refuse_duplicate_field_names` raises its `TransformError(message=...)`. Its module docstring changes from "each boundary keeps its own wording" to "the wording is shared; each boundary keeps its own exception".
6. `execution/_pipeline_full_frame.py`: `_raise_if_source_value_unrepresentable` becomes `_unrepresentable_source_column(resident_sources, graph, exc) -> tuple[str, str] | None`, still called inside the handler, returning the offending table and column instead of raising. The caller at `:229-231` keeps the bare `raise` when it is None, and otherwise raises the same `ExecutionError` (same code, same message text) after the `except` block ends, so Python sets no `__context__`. `from None` alone is not enough: it sets `__suppress_context__` but keeps `__context__`.
7. `profile/_source.py`, `_profile_one_source`, bounded branch: `isinstance(reader, ArrowSampleSource)` picks `walk_arrow_table(reader.sample_table(n), ...)`; any other reader keeps `sample_frame` plus `walk_dataframe`. `_nested_capable_schema` uses the same protocol in place of its four-class `isinstance` list. `execution/_chunked_profile.py` imports `arrow_column_profile` from `decoy_engine.profile._walk_arrow` and drops it from `__all__`. Renamed-path edits: `tests/native/test_chunked_entry_rev9_profile.py:78` and `tests/native/test_chunked_entry_rev9_catalogue.py:17` (import line); `tests/sentry/test_column_shape_classifier.py:34` (the `observed_shape` caller row becomes `profile/_walk_arrow.py`); `:113-120` (the planted-caller probe path becomes `profile/_walk_arrow.py`); `tests/sentry/baselines/column-shape-classifier.json:17` (key `observed_shape::profile/_walk_arrow.py`). `tests/native/test_draw_site_inventory_coverage.py:241` stays as it is: `execution/_chunked_profile.py` still exists and is still in its inventory.

`capacity.py`, the CLI preflight and every reason code are unchanged.

### 8.1 Choke point

Rule: the bounded profile of an Arrow-holding reader never converts to pandas. It is enforced by construction in `_profile_one_source`, the one bounded profile site. Guard: AT-4. `pa.Table.to_pandas` and the other Arrow `to_pandas` methods cannot be monkeypatched (immutable extension types), so the spy wraps the functions they reach. Probed: `pyarrow.pandas_compat.table_to_dataframe` catches `Table.to_pandas` and `RecordBatch.to_pandas`; `pd.Series.__init__` catches `ChunkedArray.to_pandas` and `Array.to_pandas`. The spy also wraps `pd.DataFrame.__init__` and `pd.read_parquet`, and requires zero calls. A CSV control cell must record at least one call. The mutation that must turn it red: M-1. A new Arrow reader is caught by the extended conformance sentry (AT-10).

### 8.2 Design notes

- Principles: single responsibility (the reader samples, the walk measures, `_pandas_meta` states the metadata facts) and one place per fact (the Arrow-holding readers become one protocol; the metadata parse lives once, in the foundation tier both profile and execution may import; the duplicate-name text lives once).
- Dependency direction: profile and execution both import `_pandas_meta`; no new profile-to-execution edge, and one lazy profile-to-execution import goes away.
- House style: typed keywords, no flag argument (the reader's type picks the walk; the metadata picks the dtype rule), comments say why.

### 8.3 Size

New source files: `_pandas_meta/_columns.py` (about 80 lines, about 45 moved), `profile/_walk_arrow.py` (about 230, about 150 moved), `profile/_arrow_sample.py` (about 45, about 20 moved). Changed: `_readers.py` (about -20, ends near 571), `_readers_resident.py` +5, `_cloud_readers.py` +12, `_source.py` +10 -8, `_chunked_profile.py` -150, `_transforms.py` -4, `_mem_estimate_arrow.py` -30, `_declared_columns.py` -6, `_field_names.py` +10, `_guards.py` +2 -3, `_walk.py` +1 -4, `_pipeline_full_frame.py` +6 -3, four import-only source edits. Every file ends under 600. Tests: 1 new file, about 12 changed (imports, two `match=` strings, the sentry rows, the contract matrix, the coverage sentry). Public names added: none. A build past about 350 added source lines net stops and explains.

## 9. Acceptance tests

Red on base: the cell fails on `origin/main`. Green on base on purpose: a regression pin. Engine tests live in `tests/unit/profile/test_arrow_bounded_profile.py` unless named.

Fixtures: `T_NS` = 4 rows, `t: time64[ns]` with `3_600_000_000_000 + 987_654_321` at row 3; `D_FAR` = `t: date32` with `-1_000_000` (year -768) at row 3, and a twin with `3_000_000` (year 10183); each with an `email` string column. Config: `t` passthrough, `email` redact, seed 7.

- AT-1 (red on base). `estimate_job_capacity` on `T_NS` and both `D_FAR` files returns `NOT_APPLICABLE` and does not raise. FK cell: the parent/child pair of `tests/unit/execution/test_capacity_estimate_job.py` (`_ooc_config`, `low_threshold`) with a `T_NS` column on the parent gives the same verdict and `needed_bytes` as the pair with that bad value replaced by `1000`.
- AT-2 (red on base). `profile_source` on each fixture as local Parquet: column `t` has `dtype="object"`, `null_count=0`, `distinct_count=4`, lengths None, `sampled=False`, and the `shape` of the same column with the bad value replaced. A 5-row cell with a null at row 1 gives `null_count=1`, `distinct_count=4`.
- AT-3 (green on base on purpose, except the marked cells). Parity: for every `tests/native/_rev9_profile_cases.py` case, every `tests/native/_rev9_type_catalogue.py` entry with and without a null, and list, struct and map columns, the bounded `profile_source` result through a local Parquet file (where Parquet stores the type) and through a supplied `pa.Table`, with total = sample and total = 10 x sample, equals `walk_dataframe(reader.sample_frame(n), ...)` field by field, with the same column list. The oracle is `walk_dataframe`, unchanged. Extra cells: a zero-row Parquet file and a zero-row `pa.Table` of the catalogue schema; a 25,000-row file with 4,000-row row groups (F-7); a two-table config profiled in one call (F-11); declared PK and FK columns. Plan cells: `plan_to_yaml(compile_plan(...))` equal for the redact, hash, truncate and faker configs of test 20. Red on base: the Probe D cells where base raised, asserted to return.
- AT-3b (red on base for the reader cells: base already matches itself, so the red is a test-first run of `walk_arrow_table` without the metadata rules, recorded in the builder report; green on base on purpose for the oracle side). Parity over the Probe E corpus, field by field and column list, against `walk_dataframe(reader.sample_frame(n), ...)`: dtypes `Int8`/`16`/`32`/`64`, `UInt8`/`16`/`32`/`64`, `boolean`, `string`, `string[pyarrow]`, `Float32`, `Float64`, categorical unordered and ordered, tz-aware timestamps, `period[M]`, `interval`; each with and without a null; RangeIndex, named index, filtered index; full and zero rows; written with `df.to_parquet` and read through `ParquetFileSource`, the S3 and GCS fakes, and built with `pa.Table.from_pandas` through `ResidentTableSource`. Plus: a `Float64`-metadata column holding a NaN; a table whose metadata names a column that is absent (malformed metadata, the walk falls back to the Arrow rule); plan cells for a `when:` numeric check and `check_null_bearing_int_unsupported` over the `Int64` with-null table, equal to base.
- AT-4 (red on base). Conversion spy (8.1): `profile_source` over a local Parquet, a fake S3 Parquet, a fake GCS Parquet and a supplied `pa.Table` (each also with pandas metadata) records zero calls to `pyarrow.pandas_compat.table_to_dataframe`, `pd.Series.__init__`, `pd.DataFrame.__init__` and `pd.read_parquet`. A CSV control cell records at least one.
- AT-5 (green on base on purpose, except the message cell). `estimate_job_capacity` raises `ExecutionError` `capacity_source_unprofilable` for a truncated Parquet file, a CSV file declared `parquet`, and a Parquet file with two columns named `a`. Message cell (red on base): the chained `ValueError` text equals `table 't' has 1 duplicated field name(s)`, and `walk_dataframe`, `walk_arrow_table` and `refuse_duplicate_field_names` give that same text for the same names.
- AT-6 (red on base for the row-0 and row-9,999 cells). An 80,001-row `time64[ns]` file with the bad value at row 0, 9,999, 10,000 and 80,000: every `estimate_job_capacity` call returns a verdict; `profile_source` gives `row_count=80_001`, `row_count_exact=True`, `sampled=True`, and `null_count` and `distinct_count` over exactly the first 10,000 rows (asserted against `pyarrow.compute` over `table.slice(0, 10_000)`).
- AT-7 (red on base). `run_pipeline` with the `T_NS` and `D_FAR` sources as `LazySource`, with and without `resident_fallback=True`, and as resident `pa.Table`s, raises `ExecutionError` `full_frame_value_unrepresentable`; `exc.__context__ is None`, `exc.__cause__ is None`; `"".join(traceback.format_exception(exc))` holds no digit string of the bad value. File: beside the existing `full_frame_value_unrepresentable` tests (`git grep -l full_frame_value_unrepresentable tests`).
- AT-8 (red on base). The frozen value 6.1 (a): a supplied `pa.Table` with sub-µs `time64[ns]` values and no null, and one with year-10183 dates and no null, profile with lengths None; `dtype`, `null_count`, `distinct_count` and `shape` equal base.
- AT-9 (red on base). `S3ParquetSource` and `GcsParquetSource` over the `T_NS` bytes (fakes of `tests/unit/profile/test_duplicate_header_readers.py`): `sample_table(n)` equals the local `ParquetFileSource.sample_table(n)`, schema metadata included, and `profile_source` returns the AT-2 column.
- AT-10 (red on base). `tests/unit/profile/test_sample_frame_contract.py` gains a `SAMPLE_TABLE_MATRIX` ("exactly n rows, short only at the end", metadata kept) for the four `sample_table` readers; `tests/sentry/profiling/test_profile_source_contract_coverage.py` gains the same owned-class walk for `sample_table`, with a seeded class that must be caught.
- AT-11 (green on base on purpose). `tests/native/test_chunked_entry_rev9_profile.py`, `tests/native/test_chunked_entry_rev9_catalogue.py` and `tests/sentry/test_column_shape_classifier.py` pass after the move with only the named path edits; the F-13 tests pass with only their import line changed.

## 10. Mutations

Each alone on the final head; each must turn the named test red. Record the head (class 9).

| ID | Mutation | Red |
|---|---|---|
| M-1 | `_profile_one_source` sends Arrow readers through `sample_frame` and `walk_dataframe` | AT-1, AT-2, AT-4 |
| M-2 | `walk_arrow_table` sets `row_count` to the sample length | AT-3 total = 10 x cells, AT-6 |
| M-3 | `sampled` always False | AT-3 total = 10 x cells, AT-6 |
| M-4 | the candidate-key rule drops `not sampled` | AT-3 total = 10 x cells |
| M-5 | `declared_pk`, `is_fk` or `fk_target` not set (one each) | AT-3 PK/FK cell, AT-1 FK cell |
| M-6 | `head_table_from_batches` does not slice to `sample_rows` | AT-6, AT-10 |
| M-7 | `S3ParquetSource.sample_table` returns `pa.Table.from_pandas(self.sample_frame(n))` (same for GCS) | AT-4, AT-9 |
| M-8 | `ResidentTableSource` lacks `sample_table` | AT-4 resident cell, AT-8 |
| M-9 | the duplicate-name check is removed from `walk_arrow_table` | AT-5 duplicate cell |
| M-10 | the `ArrowNotImplementedError` catch around `count_distinct` is removed | AT-3 union and tensor cells |
| M-11 | `combine_chunks()` removed before the column walk | AT-3 multi-row-group cell, or an equivalent mutant on pyarrow 24 with the run output |
| M-12 | the sentry walk for `sample_table` skips one module | AT-10 seeded cell |
| M-13 | metadata ignored: `walk_arrow_table` passes `pandas_dtype=None` for every column | AT-3b nullable, string, period, interval cells |
| M-14 | stored index fields not dropped (`table.column_names` in place of `arrow_columns`) | AT-3b named and filtered index cells |
| M-15 | the string-length rule ignores `pandas_dtype == "string"` | AT-3b string with-null cells |
| M-16 | the struct distinct count for interval removed | AT-3b interval cells |
| M-17 | the full-frame error is raised inside the handler again | AT-7 `__context__` asserts |
| M-18 | `walk_dataframe` keeps its own duplicate-name text | AT-5 message cell |

## 11. Class tables

dev-rules `catalogs/recurring-defects.md`:

| Class | This row |
|---|---|
| 1 anchored validation | n/a, no pattern |
| 2 strict types | n/a, `ColumnProfile` serialization unchanged |
| 3 exception context | 8 item 6 removes the value-bearing `__context__`; AT-7 asserts both links None; M-17 |
| 4 versioned read models | n/a |
| 5 guard scanners | AT-10 walks classes by `__dict__` like its sibling; covered shape: a class whose own body defines `sample_table` |
| 6 private imports | new edges only into the foundation tier (`profile -> _pandas_meta`, `execution -> _pandas_meta`), which `tests/sentry/layout/test_import_layers.py:55` already lists; `_chunked_profile -> profile._walk_arrow` replaces its existing `profile._walk` edge pattern; one lazy `profile -> execution._transforms` import is removed |
| 7 hidden CI failures | n/a |
| 8 trust classes | n/a |
| 9 mutations on the final head | section 10 |
| 10 allowlisted helpers | n/a |
| 11 raised caps | module size goal 600, max 700 (`tests/sentry/test_module_size.py`): `_readers.py` goes from 591 to about 571; every new module is under 250; no census entry added. `profile/` goes from 20 to 22 modules, under the 25-module fan-out cap (`tests/sentry/baselines/package-fanout.json`); `_pandas_meta/` from 2 to 3. No pin moves |

Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes):

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the full-frame error leaves its handler before it is raised, so no chain holds the pyarrow text; the duplicate-name text drops header names; no new message carries a cell | AT-7, AT-5 message cell, CLI cells in 13.1 | M-17, M-18, M-1 |
| 2 | Cleanup missing on an exit path | N/A: no new handle; `iter_batches` reads stay inside the existing `LazySource` and cloud-reader lifetimes | none needed | N/A: no new resource |
| 3 | State machine and concurrency | N/A: no shared state; the walk is a pure function of the sample and never draws from `rng` | AT-3 two-table cell | N/A: no transition added |
| 4 | Route parity and silent fallback | one dispatch in `_profile_one_source`; every `profile_source` caller gets the same walk; no fallback to pandas on error | AT-3, AT-3b, AT-4 | M-1, M-7, M-8 |
| 5 | Referential integrity | PK and FK flags set by the wrapper exactly as `walk_dataframe` sets them | AT-3 PK/FK cell, AT-1 FK cell | M-5 |
| 6 | Untrusted producer | the `b"pandas"` blob is producer-written: one parse in `_pandas_meta`, malformed input gives empty results, never an exception | AT-3b malformed-metadata cell; the moved malformed tests in `test_mem_estimate_nullable_metadata.py` | M-13 |
| 7 | Check then use on a path (TOCTOU) | N/A: the same readers open the same paths once, as today | none needed | N/A: no new check-then-open |
| 8 | Weak tests and overclaimed evidence | each AT records red or green on `26091c834`; parity uses `walk_dataframe` as an unchanged oracle; AT-3b corpus carries real pandas metadata (the test-20 corpus has none); the 20,000 claim in `#399` was re-measured | builder report with base SHA and red output | each mutation names its AT |
| 9 | Behavior-preserving refactor drift | `arrow_column_profile` with `pandas_dtype=None` is the moved body; helpers moved with their tests | AT-11, AT-3 | M-10, M-11 |
| 10 | Frozen contract drift | no public name, signature, reason code or serialized field changes; the two moved values are named (6.1) and frozen | AT-8, AT-5, signature sentry unchanged | M-8, M-18 |

### 11.1 Frozen contracts

- Public API: no name or signature changes. `ProfileSource` is unchanged; the Arrow sample is a separate private protocol.
- `Profile` and `ColumnProfile` serialization (`profile_to_json`, `profile_hash`): no field added; every value equal for columns pandas converts, pandas-written input included (AT-3, AT-3b), so plan bytes and profile hashes do not move.
- Reason registry: no code added; `capacity_source_unprofilable`, `full_frame_value_unrepresentable` and `duplicate_source_field_names` keep their meaning and message text.
- Byte changes: none to any output file.

### 11.2 Enumerations

#### Exit paths

Of `estimate_job_capacity` (`capacity.py:236-555`):

- The profile catch (`capacity.py:324-339`): now fires only for unreadable, corrupt or duplicate-named files (AT-5).
- No relationships, `NOT_APPLICABLE` (`capacity.py:341-346`): unchanged, now reachable for these sources (AT-1).
- Routing reject, not out-of-core, priced verdict (`capacity.py:368-555`): unchanged, now reachable (AT-1 FK cell).

Of the full-frame ingest (`_pipeline_full_frame.py:229-231`):

- No single source column reproduces the error: the bare `raise` of the original, unchanged.
- A column reproduces it: the coded error, now raised outside the handler (AT-7).

#### Routes

Every caller of the bounded profile (section 5) takes the one dispatch in `_profile_one_source`:

- Capacity estimate (`execution/capacity.py:323`).
- Job estimate (`execution/_job_estimate.py:150`).
- `run_pipeline` routing facts (`execution/pipeline/_routing_facts.py:90`), for every route it then picks, reached from the CLI by `run`, `tokenize` and the API.
- Physical snapshot (`execution/physical/_snapshot.py:166`).
- `run_mask_chunked` and `run_mask_pipeline_chunked`: N/A, they build their own first-chunk profile (`execution/_chunked_profile.py:68-123`), unchanged (G-4).

#### Readers

| Reader | Bounded walk after |
|---|---|
| `ParquetFileSource` (local) | Arrow, metadata kept |
| `S3ParquetSource`, `GcsParquetSource` | Arrow, metadata kept |
| `ResidentTableSource` (supplied `pa.Table`) | Arrow, metadata kept |
| `CsvFileSource`, `S3CsvSource`, `GcsCsvSource` | pandas (G-2) |
| `FixedWidthFileSource` | pandas (G-2) |

#### FK shapes

N/A: the profile records `is_fk` and `fk_target` from config as before (AT-3 PK/FK cell); no FK path changes.

#### Fields

- Every `ColumnProfile` field (`name`, `dtype`, `row_count`, `null_count`, `distinct_count`, `sampled`, `is_candidate_key_sampled`, `declared_pk`, `is_fk`, `fk_target`, `pii_class`, `avg_length`, `max_length`, `shape`), built today at `profile/_walk.py:226-241`: compared by AT-3 and AT-3b.
- The column list itself (stored index fields excluded): AT-3b.
- `TableProfile.row_count` and `row_count_exact`, set at `profile/_source.py:287-303`: AT-6.
- `pii_class`: always None on this path; AT-3 compares it.

#### Output surfaces

- Errors: the raw pyarrow profile error goes away on these paths; the full-frame error loses its chained context; the duplicate-name `ValueError` text changes (6.1 b).
- CLI stdout, `--json` and exit codes: per section 6 (13.1 cells).
- Returned profiles and plans: equal for columns pandas converts (AT-3, AT-3b).
- Logs, audit, evidence, progress: N/A, unchanged; the profile writes none.

### 11.3 Reuse inventory

- `arrow_column_profile` and its helpers, moved, with one keyword added.
- `stored_index_fields`, `arrow_columns`, `pandas_nullable_columns`, moved into `_pandas_meta`; the new `pandas_column_dtypes` shares their parse.
- `ParquetFile.iter_batches` and `_read_parquet_sample` for the sample.
- `_field_names.repeated_names` for the duplicate-name scan; the guard's existing text.
- `canonical_dtype_label` (`internal/pandas_compat`) for the dtype label; `observed_shape` for `shape`.
- The `sample_frame` conformance matrix and its coverage sentry, extended to `sample_table`.
- Test corpora: `tests/native/_rev9_profile_cases.py`, `tests/native/_rev9_type_catalogue.py`, the S3 and GCS fakes in `tests/unit/profile/test_duplicate_header_readers.py`, `_ooc_config` in `tests/unit/execution/test_capacity_estimate_job.py`.

## 12. Placement

| File | Directory | CODEMAP "Where Things Go" row | Sits beside |
|---|---|---|---|
| `_columns.py` (new) | `src/decoy_engine/_pandas_meta/` | foundation packages (`src/decoy_engine/_<name>/`) | `_descriptors.py`, the per-type facts |
| `_walk_arrow.py` (new) | `src/decoy_engine/profile/` | "Source readers, profile types" | `_walk.py`, its pandas twin |
| `_arrow_sample.py` (new) | `src/decoy_engine/profile/` | "Source readers, profile types" | `_readers.py` |
| `test_arrow_bounded_profile.py` (new) | `tests/unit/profile/` | tests in `tests/unit/profile/` | `test_bounded_profiling.py` |
| `preflight-arrow-profile.md` (new) | `changelog.d/` | "Changelog fragments" | the other fragments |
| `CODEMAP.md` (edit) | root | n/a | row 107: the Arrow column profile is in `profile/_walk_arrow.py`; row 126: add `_walk_arrow.py` and `_arrow_sample.py`; the `_pandas_meta` row adds per-column facts |

Changelog fragment, `changelog.d/preflight-arrow-profile.md`:

```
### Fixed (bounded profile reads Arrow, PREFLIGHT-ARROW-PROFILE, 2026-11-23)

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
```

No `Breaking:` line: no public name or signature changes.

## 13. Slices

| Slice | Repo | Content | Size | Risk |
|---|---|---|---|---|
| S1 | engine | Section 8 in full (items 1-7), AT-1 to AT-11 with AT-3b, M-1 to M-18, the renamed-path sentry edits, changelog fragment, CODEMAP rows | about 330 source lines changed (about 215 moved), about 500 test lines; about 30 files, most of them one import line | R2 |
| S2 | engine | Release: compile the fragment with `scripts/release/stamp_release.py`, bump to the next patch version, tag | release files only | R2 (established release path) |
| S3 | CLI | Repin to the S2 release per the engine repin checklist (compat, fences, FROZEN, doc, `PIN_PREFIX`, Dockerfile ARG, catalog); test and doc changes in 13.1 | pin files plus about 120 test lines; no CLI source logic change | R1 |

S1 is one slice: the helper move, the walk, the reader methods and the error-chain fix share the same tests (AT-7 needs the profile fix to reach the full-frame error on a `LazySource`). If the gate wants it smaller, the only clean cut is S1a = item 1 alone (the `_pandas_meta` move, pure refactor, AT-11 F-13 cells), merged first. S3 needs `#399` merged first (D3).

### 13.1 S3, CLI test and doc changes

- `test_at_c12_the_cli_preflight_refuses_these_sources_first` becomes `test_at_c12_the_cli_runs_these_sources`: through `decoy run --chunked`, default intent exits 0 and the `t` column equals the source exactly; `--no-native` exits 3 with `chunked_passthrough_value_unrepresentable` and none of the `_LATE` markers in the output; neither output says `source not parsed`.
- `test_at_c12_default_runs_exact_and_no_native_fails` and `test_at_c14_a_read_refused_value_is_coded_and_value_free` stop calling `_direct` (its reason, the preflight refusal, is gone) and run through the CLI. `_direct` is deleted if nothing else uses it.
- `TestLateRefusedValue`: behaviour unchanged. Its comment drops "past the 20,000-row preflight sample". `test_default_run_publishes_the_value_exactly` is parametrized over the bad row {0, 80,000}.
- New: plain `decoy run` on the two `_REFUSED_SOURCES` exits 3 with `full_frame_value_unrepresentable`, no bad-value marker in stdout, stderr or `--json`, no output file (G-1).
- New: `decoy validate preflight` on the two sources reports no `capacity.source_unreadable`; a truncated Parquet still does (exit 1).
- Docs: remove the PREFLIGHT-ARROW-PROFILE carve-out from the `CHANGELOG.md` entry; check the `decoy explain chunked`, `docs/cli-reference.md` and `run --help` text that `#399` names for the same sentence.

## 14. Pre-mortem

- A parity cell differs on a type the probes did not cover (a pyarrow 25 type, or a pandas extension dtype outside Probe E). Any new difference fails AT-3 or AT-3b; the type is fixed in `_walk_arrow.py` or listed in 6.1 with an owner call.
- Mac or Windows pandas differs. CI pins `pandas<3`; the oracle runs on the same host, so a host difference shows as a parity failure.
- pandas 3 changes the default string dtype. The metadata rule follows `numpy_type`, and AT-3b computes its oracle on the installed pandas, so the upgrade shows as a parity failure, not a silent change.
- A builder makes a parity cell pass by editing the oracle. A diff to `walk_dataframe` beyond the item 5 message call is out of scope and the gate refuses it.

## 15. Open decisions

- D1. A plain `decoy run` of these sources still exits 3 after this row. Recommended (accepted by Dennis R1): accept for this row, and open the follow-up row "run plain-route passthrough columns without pandas" tagged 1.0-blocking, since the plain run is the default path.
- D2. Also ship the CLI-only fallback (skip capacity pricing on `--chunked`)? Recommended: no. After S1 the refusal is gone at its source on every path.
- D3. Land the CLI test flip in a separate PR after `#399` and the S2 release, or fold it into `#399`? Recommended: a separate PR. The wrong "20,000-row" sentence in `#399` is corrected to 10,000 in `#399` before it merges.
- D4. Remove `ResidentTableSource._frame_of`'s text-cast fallback? Recommended: no, not in this row. It still serves `to_frame` and `sample_frame`; the D5 row decides it.
- D5. One follow-up row for `decoy scan` / `init` and the chunked first-chunk profile (G-4)? Recommended (accepted by Dennis R1): yes, tagged 1.0-blocking, because scan and init raise a raw `ValueError` containing the year on a valid Parquet file (`profiling/scan_set.py:339`).
- D6 (new). The duplicate-name `ValueError` text from the profile walk changes to the shared value-free text (6.1 b). Recommended: accept. The alternative, keeping two texts, leaves the column names (producer text) in an engine message.
