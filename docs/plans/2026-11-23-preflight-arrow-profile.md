Status: plan

# PREFLIGHT-ARROW-PROFILE: the bounded source profile reads Arrow, so preflight no longer refuses a valid Parquet file whose values pandas cannot hold

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 5 (2026-11-25), after Dennis on Revision 4 (`8b1e32022`); section 0b lists the changes. Revision 4 followed two Codex NO-GO rounds on PR #805; section 0a replaces the S1b admission rule. Roadmap row: PREFLIGHT-ARROW-PROFILE (CLI `docs/roadmap/groups/run.md`, 1.0, function break). Anchors are in this repository (decoy-engine) at `origin/main` `26091c834` unless marked `cli:` (decoy CLI `origin/main` `95362d16`) or `#399:` (CLI PR #399, branch `feat/chunked-run-mask-chunked-s2`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `bugfix.md`, `reuse-first.md`, `proportionality.md`, `architecture.md`, `cross-cutting-concerns.md`, `testing.md` (test depth), `api-and-compatibility.md`, `catalogs/recurring-defects.md` (11 classes). Engine `CODEMAP.md` "Where Things Go"; `changelog.d/README.md`; engine `CLAUDE.md` (module size goal 600, max 700).

Risk: R2. It changes how every bounded source profile is computed (the input to routing, plan compile and the capacity estimate), moves one module and three schema helpers, and changes where one coded error is raised. No serialization, public-signature or reason-code change. Revision 3 caller and sentry census checked on engine origin/main `4bc582d0a`. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes (shared profile input to every route; moved helpers imported by shared test fixtures).

## 0. Dennis R2 resolutions

| Class | Finding | Revision 3 |
|---|---|---|
| V1 | Producer metadata can stop profiling or assign a dtype or index to the wrong column. | Section 8 defines the name lookup and fallback. AT-3c tests malformed input, rename, drop and reorder through the bounded reader. |
| V1 | A stale import in the chunk schema guard breaks native and forced chunked execution. | Section 5.1 lists the source and test imports, including both schema reads in `check_stored_index`. AT-11 runs the guard. |
| V2-LOG | Sentries and inventories still name the old sites. | Section 8.4 assigns each entry to the function that owns the call after the move. |
| V2-LOG | S1 mixed relocation with new behavior. | Section 13 gives the move and the behavior change separate acceptance and mutation gates. |

## 0a. Revision 4: admit a proven set, fall back for the rest

Codex R1 (`ec85b7a21`) and R2 (`04459013f`) on PR #805 each found about seven V1 blockers of one class: the Arrow walk differs from the pandas oracle on a family the walk tried to imitate (pandas extension types, ArrowDtype tokens, masked floats, string inference, producer footers). Imitating more pandas rules does not close this class. Revision 4 changes the rule:

- The bounded Arrow walk runs only for a table whose every data field is in the admitted set (8.5), and whose footer passes a strict, CPython-independent decode and a strict layout check. Parity for each admitted family is proven by AT-3 and AT-3b with no exception exemption.
- Every other table takes the base path unchanged: `reader.sample_frame(n)` and `walk_dataframe(..., arrow_schema=_nested_capable_schema(reader))`. Its result is the oracle by construction. `arrow_walk_admission` returns a coded fallback reason (8.5). The reason is internal. It is not a reason code, and it is never serialized, logged or put in a message.
- One case does not fall back: a field whose pandas dtype cannot be built (an invalid `pandas.period` frequency, an unknown timezone). Base raised the pandas error with the producer text. Revision 4 raises a value-free `ValueError` that carries only the `safe_error_type` label (8.5, item 4).
- The walk drops the code that imitated the now-excluded families: the ArrowDtype token branch, `_extension_label`, the interval `_distinct_rows` count and the NaN-payload fold. `pandas_dtype` takes only the admitted nullable labels.

| Round, finding | Revision 4 handling | Acceptance cell (AT-12) |
|---|---|---|
| R1, two `int8` dictionary chunks with 200 categories fail `combine_chunks()` | Admitted (dictionary of text). Keep the index widening from `04459013f`. | `r1-dict-chunks`: parity, `distinct_count=200` |
| R1, legacy entry with `name` and no `field_name` loses the `Int8` hint | `metadata_layout` fallback | `r1-legacy-name`: reason, parity, truncate compile raises `PlanCompileError` as on base |
| R1, footerless `period[M]` and interval extension types | `extension_type` fallback | `r1-footerless-ext`: reason, parity |
| R1, masked `Float64` with two NaN payloads | `metadata_dtype` fallback (masked floats not admitted) | `r1-float64-nan`: reason, parity, no candidate key |
| R1, `future.infer_string=True` on pandas 2.3.3 | `string_inference` fallback | `r1-infer-string`: reason, parity, lengths 3 |
| R1, `1e999` in the footer with `index_columns=["x"]` | `metadata_unreadable` fallback | `r1-nonfinite`: reason, parity |
| R1, `("wrong", "int8[pyarrow]")` on a null-bearing `int8` | `metadata_dtype` fallback | `r1-wrong-pair`: reason, parity |
| R2, invalid `pandas.period` frequency, invalid timezone: `str(ValueError)` leaks | Value-free `ValueError`, label only, no chain | `r2-bad-freq`, `r2-bad-tz`: text, chain, traceback marker-free, capacity code |
| R2, `double[pyarrow]` NaN payloads and `[-0.0, +0.0]` | `metadata_dtype` fallback (ArrowDtype not admitted) | `r2-arrowdtype-float`: reason, parity, 3 distinct |
| R2, period ordinal `-2**63` read as NaT | `extension_type` fallback | `r2-period-min`: reason, parity, `null_count=1` |
| R2, interval `(-0.0, 1.0]` and `(+0.0, 1.0]` | `extension_type` fallback | `r2-interval-zero`: reason, parity |
| R2, `large_binary[pyarrow]`, dictionary ArrowDtype token | `metadata_dtype` fallback | `r2-large-binary`, `r2-dict-token`: reason, parity, `category`, length 3 |
| R2, missing `future.infer_string` read as True on pandas 2.0.3 | Detection fixed (8.5 item 5); a missing option means on only for pandas 3 or later | `r2-infer-floor`: detection cells and the absent-option profile cell |
| R2, a 1,000-digit int makes output depend on `sys.set_int_max_str_digits` | The admission decode uses `max_int_digits=20`, checked on the literal text before any `int()`, so the admission result never depends on the limit. Over the limit: `metadata_unreadable` fallback. The fallback is base, and base `to_pandas` decodes the footer with pyarrow's `json.loads`, so the fallback keeps base's dependence on the limit (8.6) | `r2-big-int`: same reason at limits 640, 4300 and 0; `profile_source` equals the base outcome at each limit |
| R2 DESIGN, the parity harness exempts any exception for a whole family | Harness rule in AT-3: no exemption for admitted families; a non-admitted family must show its reason and match the base outcome | `test_admitted_families_are_frozen`, AT-3 harness |
| R2 DESIGN, the footer-entry walk is duplicated | Admission uses the shared `column_entries` iterator; `_physical_entries` is deleted; the estimator keeps its own legacy adapter | AT-3c `legacy-name`; M-31 |

The bounded walk never depends on the CPython integer-digit limit. A table that falls back keeps whatever dependence base has (8.6).

Moved out of this row (8.6): admitting more families, value-free text for base pandas errors on the fallback path, and a pandas floor CI leg.

## 0b. Revision 5: Dennis on Revision 4

Dennis kept the table-level admit-or-fallback design and returned NO-GO on two blockers and eight should-fix items.

| ID | Finding | Revision 5 change |
|---|---|---|
| B1 | `date64` values with a sub-day part (resident `[0, 3_600_000, 86_400_000]`): base gives 2 distinct, the walk 3 and a candidate key | `date64` removed from `ADMITTED_FAMILIES`; reason `type_family`; AT-13 row; M-36 |
| B2 | AT-12 `r2-big-int` cannot pass: the fallback is base, and base raises at limit 640 and profiles at 4300 and 0 | Cell rewritten: same reason at all three limits, base equality at each. 0a and 8.6 state that the fallback keeps base's dependence |
| S1 | In an admitted family, some values base cannot convert now profile | Declared as 6.1 (d). Dictionary values that are null count as missing (decode before `is_null`). AT-14 pins the three cases |
| S2 | The dictionary `metadata` rule was not written down | 8.5 item 3: None, or a dict with exactly `num_categories` (int, not bool) and `ordered` (bool equal to `t.ordered`) |
| S3 | `column_entries` skips non-dict and keyless entries | 8.5 item 2: the yielded count must equal `len(columns)`, else `metadata_layout`; `column_entries` unchanged |
| S4 | A strict decode in the shared helpers splits profile from execution on a footer like `1e999` plus `index_columns` | `stored_index_fields`, `arrow_columns` and `source_columns` keep main's lenient parse; the strict decode is private to `arrow_walk_admission` |
| S5 | String detection must follow pyarrow's order | 8.5 item 5 follows `uses_string_dtype` (pyarrow `pandas-shim.pxi:189`): pandas 3 or later True; 2.3 up to 3 the option; else False |
| S6 | AT-13 too loose; missing mutations; integer column labels untested | AT-13 asserts a literal reason per catalogue type from AT-3's table; M-37 to M-42; AT-3c `int-labels` |
| S7 | Cloud readers fetch `schema()` and `sample_table()` separately | 8 item 7: `sample.schema.equals(admitted_schema, check_metadata=True)`, base path on mismatch; class 7 row fixed; AT-9 cell; M-43 |
| S8 | On pandas 1.5, `duration[s]` restores as ns, so an admitted family breaks parity | S2 raises the floor to `pandas>=2.0.3` before release, owner-gated (Q-PAP-D7, default raise). The CI leg stays a follow-up row |
| V2 | Store the exception class in `unreadable`; the duplicate footer walk in `pandas_nullable_columns`; decimal first to widen | All three in 8.6. Storing the class is not cheap: `safe_error_type` takes an instance and reads `type(exc)`, so it needs a new class entry point in `safe_output` |
| D9 | Capacity message and cause | Not in S1b. Follow-up row G-5 (engine and CLI) |

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
- V2-LOG, exception-chain exposure on the plain run: Dennis showed `full_frame_value_unrepresentable` keeps the pyarrow error, which quotes the value, as `__context__`. S1b closes it (8 item 6).

## 2. Root cause

One cause: the bounded profile converts an Arrow sample to pandas before it computes any statistic, for readers that already hold Arrow. `ParquetFileSource`, `S3ParquetSource`, `GcsParquetSource` (`_cloud_readers.py:109-116`, `_read_parquet_sample`) and `ResidentTableSource` (`_readers_resident.py:16-29`) all build a `pa.Table` and then call `to_pandas()`. `_profile_one_source` (`_source.py:217-303`) only accepts a DataFrame.

`ResidentTableSource._frame_of` works around the same fault by casting a failing column to text. That is a patch at one reader, and it changes the statistics (Probe D).

Not the cause: `capacity.py`'s narrow catch is correct for a corrupt file, and the CLI mapping is correct for that case. Neither changes.

## 3. Guarantee

This row promises:

1. The bounded profile (`residency="bounded"`, the default and the only production mode) of a source whose reader holds Arrow (local Parquet, S3 Parquet, GCS Parquet, a supplied `pa.Table`) is computed from the Arrow sample with `pyarrow.compute`, with no pandas conversion, when `arrow_walk_admission` admits the table (8.5). Every other table of these readers takes the base path (`sample_frame` and `walk_dataframe`) unchanged, so its profile, or its error, is the base one.
2. For an admitted table, every `ColumnProfile` and `TableProfile` field equals the value `walk_dataframe` gives on the same sample, and the column list is the same (stored index fields are not columns). This covers pandas-written Parquet and `pa.Table.from_pandas` tables whose fields are all in the admitted set, with any valid index. For a table that is not admitted, equality holds by construction. The values that move are named in 6.1 and frozen by AT-8, AT-5 and AT-12.
2a. A field whose pandas dtype cannot be built (`to_pandas_dtype()` raises on an extension or timezone type) raises a `ValueError` whose text holds only the table name, the field position and the `safe_error_type` label, with `__context__` and `__cause__` None. No producer text from the schema is in the message.
3. `estimate_job_capacity`, `estimate_job`, `run_pipeline`'s routing facts and the physical snapshot (every `profile_source` caller, section 5) no longer fail on a `time64[ns]` sub-microsecond value or an out-of-range date in the sample.
4. A truncated, corrupt or wrong-format source still raises `capacity_source_unprofilable` from `estimate_job_capacity`, and the CLI still reports `capacity.source_unreadable`.
5. `full_frame_value_unrepresentable` is raised with `__context__` and `__cause__` both None, so no rendering of the error chain carries the value.
6. CLI: `decoy run` and `decoy validate preflight` no longer refuse these sources at preflight. The run then does what its route does today with the same value past the sample.

Non-goals (recorded follow-ups):

- G-1. A plain `decoy run` of these sources still fails, now with the coded, value-free `full_frame_value_unrepresentable` (exit 3) in place of the preflight refusal (exit 1). Follow-up row, tagged 1.0-blocking: run plain-route passthrough columns without pandas (D1).
- G-2. CSV and fixed-width profiles stay on pandas: their readers produce pandas frames of text.
- G-3. `residency="full"` keeps `walk_dataframe` (no production caller; `git grep 'residency="full"' src` finds only docstrings).
- G-4. `decoy scan` and `init` (`src/decoy_engine/profiling/scan_set.py:339`, `reader.sample_frame`) raise a raw `ValueError` that contains the year on a valid Parquet file, and the chunked first-chunk profile (`_chunked_profile.walk_one_table`) still converts to pandas. Follow-up row, tagged 1.0-blocking (D5).
- G-5. `capacity.py:332` builds `capacity_source_unprofilable` with `({type(exc).__name__}: {exc})` and chains `from exc`, and the CLI reads `type(exc.__cause__).__name__` to report the cause. Follow-up row, engine and CLI together: the engine gives a label-only message plus a cause label (the `safe_error_type` value) the CLI can read without the chained exception; the CLI switches to that label; then the engine drops the chain. Not in S1b (D9).

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

### 5.1 S1a import census

Paths without a `tests/` prefix start at `src/decoy_engine/`. Each row gives the replacement import. Keep unrelated imports in place. The three functions and the nullable dtype set have one definition each in `_pandas_meta/_columns.py`.

| Caller file | Function or call lines on the base | Replacement import |
|---|---|---|
| `execution/_transforms.py` | `check_transform_source_schema` (169), `reject_config_references_stored_index` (202) | `from decoy_engine._pandas_meta import stored_index_fields` |
| `execution/_transforms_table.py` | `null_bearing_int_columns` (59). Replace the qualified call. | `from decoy_engine._pandas_meta import stored_index_fields` |
| `execution/native/_chunk_schema.py` | `check_stored_index` (62, 64). Replace the local import and check both the expected and incoming schemas. | `from decoy_engine._pandas_meta import stored_index_fields` |
| `execution/native/_chunked_entry.py` | `_route_chunked` (523, 594) | `from decoy_engine._pandas_meta import stored_index_fields` |
| `execution/native/_dispatch.py` | `plan_native_route` (471, 475) | `from decoy_engine._pandas_meta import stored_index_fields` |
| `tests/native/test_unconfigured_passthrough.py` | `test_stored_pandas_index_field_is_dropped_on_the_native_route` (728, 731) | `from decoy_engine._pandas_meta import stored_index_fields` |
| `profile/_declared_columns.py` | `source_columns`, `_supplied`, `for_chunks`, `checked_stream`, `_checked_chunk`, `checked_loader.load` (105, 234, 414, 485, 488, 508) | `from decoy_engine._pandas_meta import arrow_columns` |
| `tests/_declared_schema.py` | `declare_rest` (14, 52) | `from decoy_engine._pandas_meta import arrow_columns` |
| `tests/native/_b8_support.py` | `_declare_columns` (37, 57) | `from decoy_engine._pandas_meta import arrow_columns` |
| `tests/unit/profile/test_declared_columns.py` | `test_source_columns_reads_header_only` (30, 337) | `from decoy_engine._pandas_meta import arrow_columns` |
| `execution/_mem_estimate_arrow.py` | `source_nullable_columns` (248, 250), `column_arrow_types` (269, 281) | `from decoy_engine._pandas_meta import pandas_nullable_columns` |
| `execution/_mem_estimate_schema.py` | `table_size_spec_from_table` (38, 168) | `from decoy_engine._pandas_meta import pandas_nullable_columns` |
| `tests/unit/execution/test_mem_estimate_nullable_metadata.py` | malformed, deeply nested, missing metadata and field-name fallback tests (17, 233, 239, 243, 254). Keep `classify_column` at its existing import. | `from decoy_engine._pandas_meta import pandas_nullable_columns` |

The moved `arrow_columns` calls its sibling `stored_index_fields` directly. Delete its old local import at `profile/_declared_columns.py:77`. The `arrow_columns=` parameter in `execution/pipeline/_source_types.py:95` and its parity test pass arrays. They do not call the schema helper. The callers of `check_stored_index` and `stored_index_guard` keep their imports from `execution.native._chunk_schema`.

## 6. Behaviour table

"Bad value" means a `time64[ns]` value with a sub-microsecond part, or a `date32`/`date64` value outside years 1 to 9999. `date64` is not admitted (8.5), so a `date64` bad value keeps the base result; the rows below that change apply to `time64[ns]` and `date32`.

| Case | Today | After |
|---|---|---|
| `profile_source`, local Parquet, bad value in the first 10,000 rows | raises `ArrowInvalid` or `ValueError` | returns; the column has `dtype="object"`, exact `null_count` and `distinct_count`, lengths None, and the `shape` the same type gets without the bad value |
| Same, bad value after row 10,000 | returns | returns, unchanged |
| `profile_source`, S3 or GCS Parquet, bad value in the sample | raises | returns, as the local row |
| `profile_source`, supplied `pa.Table`, bad value, no missing value | returns via the text cast | returns, lengths None (6.1 a) |
| `profile_source`, pandas-written Parquet or `from_pandas` table, every field admitted (8.5), any valid index | returns | returns, every field and the column list equal |
| `profile_source`, any table that is not admitted (8.5): an excluded family, a masked float or ArrowDtype hint, string inference on, a footer that fails the strict decode or layout check | returns or raises | the base path runs; the same profile, or the same exception type |
| `profile_source`, a field whose `to_pandas_dtype()` raises (invalid `pandas.period` frequency, unknown timezone) | raises the pandas error, producer text in the message | raises `ValueError`, label-only text, no chain (6.1 c) |
| `estimate_job_capacity`, that same field | `capacity_source_unprofilable`, chained message with producer text | `capacity_source_unprofilable`, chained message value-free |
| `profile_source`, zero-row Parquet file or zero-row table | returns | returns, equal |
| `profile_source`, any other column pandas converts with current metadata | returns | returns, every field equal |
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

(c) A field whose pandas dtype cannot be built. Base raised the pandas error, whose text quotes the frequency or timezone string from the schema. After: `ValueError(f"table {table!r} column {position} has a type pandas cannot restore ({label})")`, where `label` is `safe_error_type(exc).value`, raised after the `except` block so no chain holds the pandas error. For an unknown timezone base may have raised a `KeyError` subclass; the builder records the base type in the report. `estimate_job_capacity` maps both to `capacity_source_unprofilable` (AT-12 `r2-bad-freq`, `r2-bad-tz`). The first-chunk profile and execution keep their own paths (G-4).

(d) In an admitted family, a value base cannot convert now profiles. This is the same class as the row's purpose, applied to three more cases. Base `to_pandas` raises; after, `profile_source` returns:

- a dictionary whose dictionary holds a null: decode the indices to values before `is_null`, so a row pointing at a null dictionary value is missing, as pandas would count it;
- a dictionary with a repeated dictionary value: distinct values are counted on the decoded values, not the indices;
- a `time32` or `time64` value of 24 hours or more, or negative: profiled like the `time64[ns]` bad value (AT-2 rules: `dtype="object"`, exact counts, lengths None).

AT-14 pins all three. Revision 5 moves no other value: an admitted table equals the oracle wherever base returns, and every other table runs the oracle.

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
| F-14 | A family the walk cannot match is admitted, so the walk differs from the oracle (the R1 and R2 class) | the admitted set is a frozen table (8.5); AT-13 fails when it changes without a test cell; AT-3 has no exception exemption; M-24, M-25, M-33, M-35 |
| F-15 | The footer decode depends on `sys.set_int_max_str_digits` or accepts a non-finite number | `max_int_digits=20` checked on the literal text; AT-12 `r2-big-int`, `r1-nonfinite`; M-26 |
| F-16 | String inference detection is wrong on a pandas version without the option | AT-12 `r2-infer-floor`; M-27, M-28 |
| F-17 | A fallback table runs a path that differs from base (for example `arrow_schema=None`) | AT-3 and AT-3c compare non-admitted cells to the base outcome; M-30 |
| F-18 | The value-free `ValueError` for an unreadable type quotes the producer text or chains the pandas error | AT-12 `r2-bad-freq`, `r2-bad-tz`; M-29 |

## 8. Design

One mechanism: a reader that holds Arrow hands the profile an Arrow sample, and the profile walks it with `pyarrow.compute`, reading the pandas metadata for the facts `to_pandas` would have taken from it.

1. In S1a, move the three functions and their constant unchanged. In S1b, add the admission in `_pandas_meta/_columns.py`: `arrow_walk_admission(schema, *, strings_restore_as_text: bool) -> ArrowWalkAdmission`, exported from `_pandas_meta/__init__.py`. 8.5 gives the admitted set, the order of the checks and the reason codes. Read `(schema.metadata or {}).get(b"pandas")` once per table. Avoid `schema.pandas_metadata`, which decodes producer bytes before the caller can check their shape.
   - `ArrowWalkAdmission` is a frozen dataclass: `reason: str | None` (None means admitted), `data_fields: tuple[str, ...]` (ordered physical names, stored index fields removed; empty unless admitted), `hints: Mapping[str, str]` (the admitted nullable labels by physical name), and `unreadable: tuple[int, Exception] | None` (the position and the caught error of the first field whose `to_pandas_dtype()` raised). `_pandas_meta` is in the foundation tier and cannot import `safe_output`, so it returns the error object and the profile builds the message (8.5 item 4).
   - Decode: a private `_strict_pandas_blob` in `_columns.py`, used only by `arrow_walk_admission`, calls `strict_json_loads(raw, max_int_digits=20)`. `strict_json_loads` checks the length of each integer literal before it calls `int()` (`_canonical/_json.py:296`), so the result does not depend on `sys.set_int_max_str_digits`. It also refuses `NaN`, `Infinity` and an overflowing float such as `1e999`. Catch `StrictJsonError` and `RecursionError`, return None, and require a dict root. The output sanitizer keeps its own call and its own bound: it is not changed in this row. The admission never feeds its decode back into the shared helpers.
   - Layout: use the shared `column_entries` iterator for the `columns` list, unchanged (the sanitizer shares it), and require that it yields `len(columns)` entries (8.5 item 2). Delete `_physical_entries` and its name-only fallback from the bounded path. The estimator keeps its legacy name fallback in its own adapter, and its existing tests pin it. The layout rules are in 8.5 item 2. A layout that fails any rule gives `metadata_layout` and the base path. The admission never repairs a footer, never matches by position, and never uses a display name to find a field.
   - Hints: a field takes a hint only from its own entry, and only when the pair `(pandas_type, numpy_type)` is in `pairs_for(field.type)` and `numpy_type` is in the admitted nullable labels (8.5 item 3). The hint passed to the walk is the canonical label from the registry, never text from the blob.
   - Keep `stored_index_fields`, `arrow_columns`, `pandas_nullable_columns` and `profile/_declared_columns.py:source_columns` on main's lenient parse (`schema.pandas_metadata` and `json.loads`), with their current contracts. The strict decode is not shared with them, so execution and the declared-columns check read a footer such as `1e999` with `index_columns` exactly as main does, and the profile falls back to base for that footer, which also reads it as main does. Run `tests/unit/execution/test_mem_estimate_nullable_metadata.py` and the output sanitizer tests `tests/unit/safe_output/test_file_metadata.py::test_clean_blob_identical`, `test_forged_blob_not_copied` and `test_blob_entries_follow_output_schema` unchanged.
2. `profile/arrow/_walk_arrow.py` (new) receives `arrow_column_profile`, `_normalize` and `_is_pandas_string` from `execution/_chunked_profile.py`. Move `_missing_mask` (291), `_dtype_label` (310) and `_INT64_MIN` (259) to `internal/pandas_compat.py`, beside `canonical_dtype_label`. In the Arrow walk, use `from decoy_engine.internal.pandas_compat import arrow_missing_mask, arrow_dtype_label`. Keep their signatures and bodies in S1a. These functions implement pandas NaT and dtype rules. The timestamp predicates at 295 and 317 would fail `tests/sentry/test_column_shape_classifier.py::test_no_other_module_decides_a_shape_from_an_arrow_predicate` inside `profile/`. Keep that guard and its scope. S1b adds the following behavior:
   - `arrow_column_profile` gains a keyword `pandas_dtype: str | None = None`, which takes only the admitted nullable labels (`Int8` to `Int64`, `UInt8` to `UInt64`, `boolean`, `string`). When set: `dtype` is `canonical_dtype_label(pandas_dtype)`; only an Arrow null is missing, as in pandas masked arrays; string lengths are computed over the valid values when `pandas_dtype == "string"`. When None, the function is unchanged, so the first-chunk profile is unchanged. Remove from the PR head the code for families that are no longer admitted: the ArrowDtype token branch, `_extension_label`, the interval `_distinct_rows` group-by and the NaN-payload fold. Keep the plain-float `-0.0`/`+0.0` fold and the index widening for multi-chunk dictionaries (AT-12 `r1-dict-chunks`). For a dictionary column, decode to values before the missing mask and the distinct count, so a null dictionary value is missing and repeated dictionary values count once (6.1 d).
   - `walk_arrow_table(table, *, table_name, admission, declared_pk_cols, fk_specs, total_row_count, source_format) -> TableProfile` (new): the duplicate-name check (item 5); for each name in `admission.data_fields` call `arrow_column_profile(..., pandas_dtype=admission.hints.get(name))`; then the table-level fields exactly as `walk_dataframe` sets them (`row_count = total`, `sampled = total > len(table)`, candidate key only when not sampled, `declared_pk`, `is_fk`, `fk_target`). It takes the admission from its caller and does not decode the blob again (`test_bounded_walk_decodes_metadata_once`, M-23). Reuse the candidate-key and PK/FK field rules from `profile/_walk.py:_walk_column` (208-240) for both walks. Extract those rules into `profile/_types.py:column_key_fields`. Supply the Arrow statistics and true total before constructing the column. Keep the pandas statistics independent. M-2 through M-5 must fail the explicit AT-3 expectations as well as the parity checks.
3. Readers: `ParquetFileSource`, `ResidentTableSource`, `S3ParquetSource` and `GcsParquetSource` gain `sample_table(sample_rows) -> pa.Table`, schema metadata kept. The three Parquet readers' `sample_frame` becomes `sample_table(n).to_pandas()`; the resident one keeps `_frame_of` (D4). `_read_parquet_sample` returns the table.
4. `profile/arrow/_arrow_sample.py` (new, about 45 lines): `head_table_from_batches(batches, sample_rows, schema) -> pa.Table` (today's `head_frame_from_batches` without the `to_pandas()`, keeping the schema metadata), and the private `@runtime_checkable` protocol `ArrowSampleSource` (`schema()`, `sample_table(sample_rows)`, contract "exactly n rows, short only at the end"). Keep the existing `head_frame_from_batches` signature as a compatibility wrapper around the table helper and `to_pandas()`. Import the table helper into `_readers.py` for the local reader and the scan probe in section 8.4. The public `ProfileSource` protocol does not change.
5. `_field_names.py` gains `duplicate_names_message(table, names) -> str | None`, using the existing `repeated_names` function and the text (`table {table!r} has {n} duplicated field name(s)`). `walk_dataframe` and `walk_arrow_table` raise `ValueError(message)`; `_guards.refuse_duplicate_field_names` raises its `TransformError(message=...)`. Its module docstring changes from "each boundary keeps its own wording" to "the wording is shared; each boundary keeps its own exception".
6. `execution/_pipeline_full_frame.py`: `_raise_if_source_value_unrepresentable` becomes `_unrepresentable_source_column(resident_sources, graph, exc) -> tuple[str, str] | None`, still called inside the handler, returning the offending table and column instead of raising. The caller at `:229-231` keeps the bare `raise` when it is None, and otherwise raises the same `ExecutionError` (same code, same message text) after the `except` block ends. Initialize the optional offending column before the try. On success continue the route with its original step. Raise only when the diagnostic returned a column. `from None` alone is not enough: it sets `__suppress_context__` but keeps `__context__`.
7. `profile/_source.py`, `_profile_one_source`, bounded branch, for a reader that is an `ArrowSampleSource`:
   - Call `arrow_walk_admission(reader.schema(), strings_restore_as_text=arrow_strings_restore_as_text())` once. The reader schema carries the same metadata bytes as its sample (AT-10 asserts this for the four readers).
   - If `admission.unreadable` is set, raise the 8.5 item 4 `ValueError`. The caught error is held as a value, so the raise is outside any `except` block.
   - If `admission.reason is None`, read `sample = reader.sample_table(n)`. If `sample.schema.equals(schema, check_metadata=True)` is False (the cloud readers fetch the schema and the sample in two calls, and the object may change between them), run the base branch below. Otherwise profile `walk_arrow_table(sample, admission=admission, ...)`.
   - Otherwise run the base branch with no change: `walk_dataframe(reader.sample_frame(n), ..., arrow_schema=_nested_capable_schema(reader))`. The reason is not logged, not stored and not put in a message. Tests read it from `arrow_walk_admission` directly.
   - Any other reader keeps `sample_frame` plus `walk_dataframe`. Preserve the existing effective sample size, the CSV extra-row probe and the final `row_count_exact` from `reader.row_count()`. `_nested_capable_schema` uses the same protocol in place of its four-class `isinstance` list. Section 8.4 covers the import and sentry changes.

`capacity.py`, the CLI preflight and every reason code are unchanged.

### 8.1 Choke point

Rule: the bounded profile of an Arrow-holding reader never converts an admitted table to pandas, and decides admission once per table before reading the sample. It is enforced by construction in `_profile_one_source`, the one bounded profile site, which is the only caller of `arrow_walk_admission` on the profile path. Guard: AT-4. `pa.Table.to_pandas` and the other Arrow `to_pandas` methods cannot be monkeypatched (immutable extension types), so the spy wraps the functions they reach. Probed: `pyarrow.pandas_compat.table_to_dataframe` catches `Table.to_pandas` and `RecordBatch.to_pandas`; `pd.Series.__init__` catches `ChunkedArray.to_pandas` and `Array.to_pandas`. The spy also wraps `pd.DataFrame.__init__` and `pd.read_parquet`, and requires zero calls. A CSV control cell must record at least one call. The mutation that must turn it red: M-1. AT-10 checks each reader that defines `sample_table`.

### 8.2 Design notes

- Principles: single responsibility (the reader samples, the walk measures, `_pandas_meta` states the metadata facts) and one place per fact (the Arrow-holding readers become one protocol; the metadata parse lives once, in the foundation tier both profile and execution may import; the duplicate-name text lives once).
- Dependency direction: profile and execution both import `_pandas_meta`; no new profile-to-execution edge, and one lazy profile-to-execution import goes away.
- House style: typed keywords, no flag argument (the reader's type picks the walk; the metadata picks the dtype rule), comments say why.

### 8.3 Size and imports

Use `profile/arrow/` for the Arrow walk and sample contract. The base has 20 direct Python files in `profile/`. Expose `arrow_column_profile` through `decoy_engine.profile.arrow` for execution and its tests. Keep the top-level engine API and the existing `ProfileSource` protocol stable. Inside the profile package expose the sampling and table-walk helpers through that same subpackage. Keep the Arrow walk independent of reader modules to avoid an import cycle.

Budget about 230 lines for `profile/arrow/_walk_arrow.py`, 45 for `profile/arrow/_arrow_sample.py` and about 170 for `_pandas_meta/_columns.py` (the admission and its frozen family table). Net additions exclude the existing column profiler and schema helpers. Check the actual counts in each slice. Keep every cap and allowlist at or below its base size.

### 8.4 Sentry and census edits

| Slice and file | Exact edit and check |
|---|---|
| S1a, `execution/_chunked_profile.py:109,329`, `tests/native/test_chunked_entry_rev9_profile.py:78`, `tests/native/test_chunked_entry_rev9_catalogue.py:17` | Import `arrow_column_profile` from `decoy_engine.profile.arrow`. Drop it from the old module's `__all__`. Keep `walk_one_table` in execution. Run `test_arrow_column_profile_equals_the_pandas_profile_field_for_field` and `test_type_catalogue_profile_matches_or_pandas_refuses`. |
| S1a, `tests/sentry/test_column_shape_classifier.py:34,113,120` | Replace the `observed_shape` caller path with `profile/arrow/_walk_arrow.py`. In `test_the_sentry_catches_a_planted_caller`, plant that path, create its parents and expect that same path. Run it and `test_only_the_named_files_call_the_classifier`. |
| S1a, `tests/sentry/baselines/column-shape-classifier.json:17` | Rename `observed_shape::execution/_chunked_profile.py` to `observed_shape::profile/arrow/_walk_arrow.py`. |
| S1a, `.importlinter:49` and `tests/sentry/baselines/import-layers.json:71` | Delete the retired `decoy_engine.profile._declared_columns -> decoy_engine.execution._transforms` ignore and its `layers::` key. Run `tests/sentry/layout/test_import_layers.py::test_the_layer_contract_is_kept`. |
| S1a, `tests/native/test_draw_site_inventory_coverage.py:241` | Keep the existing path. The functions that use the random seed stay in `execution/_chunked_profile.py`. Run `test_static_scan_finds_no_uncatalogued_draw_site`. |
| S1b, `tests/sentry/defects/test_lossless_int_columns.py:30,61` | In both the `to_pandas_fk_safe` and `fk_columns_for_table` caller tuples replace `_raise_if_source_value_unrepresentable` with `_unrepresentable_source_column`. Preserve the file, reasons and both caller counts. Run `test_only_allowlisted_functions_call_the_helper`. |
| S1b, `tests/sentry/baselines/lossless-int-columns.json:17,41` | Make that same function-name substitution in both keys. The calls remain inside the diagnostic helper. |
| S1b, `tests/fixtures/f29/producer-inventory.json:156`, `tests/sentry/baselines/f29-producer-inventory.json:401` | Move the single producer row to `run_full_frame_route` and its actual raise line. Record the existing registry expression `reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE` and its `registry` classification. Replace the baseline key with `execution/_pipeline_full_frame.py::run_full_frame_route::kw::reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE`. Keep the row count and code coverage. Keep the registered identity and its frozen reason baseline. Run `tests/unit/test_reason_registry.py::test_every_producer_resolves` and AT-7 to check the actual emitting function and code. |
| S1b, `tests/unit/profiling/test_scan_set.py:99,109` | In `test_bounded_head_reads_one_batch`, patch `_readers.head_table_from_batches` where `ParquetFileSource.sample_table` looks it up. Annotate the spy result as `pa.Table`. Keep the consumed-row counter and both bounds. |
| S1b, `tests/sentry/file_access_registry.toml:1114` | Keep the existing entry. The ParquetFile open stays in `profile/_cloud_readers.py::_read_parquet_sample`. Run `tests/sentry/test_file_access_boundary.py::test_registry_has_no_stale_entries`. |

For each changed baseline run `tests/sentry/test_baseline_registry.py::test_source_matches_its_registered_baseline` on the corresponding ID. Replace live and recorded keys together. Never increase a ceiling or add an exception. The F31 `docs/plans/evidence/2026-11-24-f31-audit/engine-sites.json` is a dated audit of another head. Keep that evidence intact.

### 8.5 Admission: the admitted set and the fallback reasons

`arrow_walk_admission` runs these checks in this order and returns the first reason it finds. Within a check, fields are visited in schema order. Tests assert the exact reason, so the order is part of the contract.

1. Type probe (all fields, stored index fields included). For each field whose type is an Arrow extension type registered by pandas (`pandas.period`, `pandas.interval`) or a timestamp with a timezone, call `field.type.to_pandas_dtype()` inside `try`. On any `Exception`, return `unreadable=(position, exc)` and stop. Base `to_pandas` fails on the same fields, so no table that base profiles is refused here.
2. Footer. No `b"pandas"` key: no hints, no stored index, go to item 3 with every field a data field. Otherwise the blob must pass the strict decode (8 item 1) with a dict root, else `metadata_unreadable`. Then the layout rules, else `metadata_layout`:
   - `columns` is a list, and every entry is a dict with a string `field_name`. A legacy entry with only `name` fails. Check it by count: `column_entries` yields only valid entries, so the yielded count must equal `len(columns)`.
   - The sequence of `field_name` values equals `schema.names` exactly: same order, same length, no duplicates. A renamed, dropped, added or reordered field fails.
   - The `name` member of each data entry equals its `field_name` when `name` is a string; a non-string `name` (None) is allowed for an index entry only.
   - `index_columns` is absent or a list, and each item is either a current field name or a range descriptor: a dict with `kind == "range"` and `start`, `stop`, `step` that are `int` and not `bool`, with `step != 0`.
   - `column_indexes` is absent, an empty list, or a list of one dict whose `pandas_type` is `"unicode"`.
3. Per data field, in order (stored index fields are dropped and not checked):
   - An Arrow extension type of any kind: `extension_type`.
   - A type outside the admitted families below: `type_family`.
   - A `string`, `large_string`, or dictionary-of-text field while string inference is on: `string_inference`.
   - A footer entry whose pair, or whose `metadata` member, is not admitted for the physical type: `metadata_dtype`. The entry is admitted when it is absent from a footerless table, or when its pair equals `pairs_for(t)[0]` (the plain pair) and its `metadata` is None or equals `column_metadata(t)`, or when its pair is in `pairs_for(t)` with `numpy_type` in the admitted nullable labels and its `metadata` is None. For a dictionary field the `metadata` member is None, or a dict with exactly the keys `num_categories` (an `int`, not a `bool`) and `ordered` (a `bool` equal to `t.ordered`); pandas writes both keys. Any other dictionary metadata gives `metadata_dtype`.

Admitted families (the frozen table `ADMITTED_FAMILIES` in `_columns.py`, one predicate per row, guarded by AT-13):

| Family | Physical types |
|---|---|
| boolean | `bool` |
| integers | `int8`, `int16`, `int32`, `int64`, `uint8`, `uint16`, `uint32`, `uint64` |
| floats | `float32`, `float64` |
| text | `string`, `large_string` (only while string inference is off) |
| binary | `binary`, `large_binary`, `fixed_size_binary` |
| dates and times | `date32`, `time32[s]`, `time32[ms]`, `time64[us]`, `time64[ns]` |
| timestamps | `timestamp` in `s`, `ms`, `us`, `ns`, naive or with a timezone that passed item 1 |
| durations | `duration` in `s`, `ms`, `us`, `ns` |
| null | `null` |
| dictionary of text | dictionary with a signed integer index over `string` or `large_string` (string inference off); with a footer entry, the plain categorical pair and the dictionary `metadata` rule in item 3 |

Admitted nullable labels (hints): `Int8`, `Int16`, `Int32`, `Int64`, `UInt8`, `UInt16`, `UInt32`, `UInt64`, `boolean`, `string`.

Not admitted, with the reason the table gets: `Float32` and `Float64` masked hints, every ArrowDtype `[pyarrow]` token, and the categorical pair on a non-dictionary field (`metadata_dtype`); every extension type, including `pandas.period`, `pandas.interval`, `arrow.uuid`, the fixed-shape tensor and opaque types (`extension_type`); `date64` (sub-day values: 0b B1), `float16`, every decimal, the view types, run-end encoded, union, `list`, `large_list`, `list_view`, `fixed_size_list`, `struct`, `map`, `month_day_nano_interval`, and a dictionary over any other value type or with an unsigned index (`type_family`).

Fallback reasons (internal strings; not reason codes, never serialized, logged or in a message):

| Reason | When |
|---|---|
| `metadata_unreadable` | the blob fails the strict decode, or its root is not a dict |
| `metadata_layout` | the footer fails a layout rule in item 2 |
| `metadata_dtype` | a data field's footer entry is not admitted for its physical type |
| `extension_type` | a data field has an Arrow extension type |
| `type_family` | a data field's type is outside the admitted families |
| `string_inference` | a text field while string inference is on |

4. Value-free refusal. When `unreadable` is set, `_profile_one_source` raises `ValueError(f"table {table!r} column {position} has a type pandas cannot restore ({safe_error_type(exc).value})")`, from no `except` block. The table name is config text, not producer text. `capacity.py` catches the `ValueError` as it does today and maps it to `capacity_source_unprofilable`; its own `{exc}` text then carries only this message.
5. String inference detection, in `internal/pandas_compat.py:arrow_strings_restore_as_text()`, follows pyarrow's own `uses_string_dtype` (pyarrow `pandas-shim.pxi:189`), which is what `to_pandas` consults: pandas major version 3 or later gives True; pandas 2.3 up to 3 gives `bool(pd.get_option("future.infer_string"))`; any earlier version gives False, even where the option exists. On the declared floor (2.0.3 after S2) the answer is False, which matches how those versions restore text (object dtype).

Why a table-level rule: one non-admitted field sends the whole table to the base path, so the column list, the index handling and every field come from one source. A per-field mix would need the oracle's index and column rules restated in the walk, which is the code that failed two rounds.

### 8.6 Moved out of this row

To S2 or S3: nothing new. S2 releases what S1b ships; S3 is unchanged (13.1).

To the V2 log (recorded in the plan's follow-up list, not built here):

- Widen the admitted set one family at a time, each with its own parity cells: decimals, nested types, masked floats, ArrowDtype tokens, `pandas.period` and `pandas.interval`.
- The fallback path keeps base pandas errors, and some of them quote producer text (for example a malformed footer that pyarrow's own pandas conversion rejects). Same as base; no new leak.
- `capacity.py:332` builds its message as `({type(exc).__name__}: {exc})` and chains with `from exc`. Pre-existing; this row only makes the profile's own new error value-free.
- A table with a bad value (6) and a non-admitted field still fails at preflight, as on base (D8).
- A CI leg on the declared pandas floor (D7). The floor raise itself is in S2.
- The fallback keeps base's dependence on `sys.set_int_max_str_digits`: base `to_pandas` decodes the footer with pyarrow's `json.loads`, so a footer integer longer than the limit raises `ValueError` at a low limit and profiles at a higher one. Same as base.
- `ArrowWalkAdmission.unreadable` holds the caught instance. Storing only the class needs a class entry point in `safe_output` beside `safe_error_type(exc)`; small, but outside this row.
- `pandas_nullable_columns` keeps its own footer-entry walk beside `column_entries`. Merge them when the estimator's legacy name fallback can go.
- D8: decimal is the first family to widen.
- G-5: the engine and CLI row for a label-only capacity message and cause label.
- The `_arrow_sample` direct import, carried from Codex R1.

## 9. Acceptance tests

Red on base: the cell fails on `origin/main`. Green on base on purpose: a regression pin. Engine tests live in `tests/unit/profile/test_arrow_bounded_profile.py` unless named.

Fixtures: `T_NS` = 4 rows, `t: time64[ns]` with `3_600_000_000_000 + 987_654_321` at row 3; `D_FAR` = `t: date32` with `-1_000_000` (year -768) at row 3, and a twin with `3_000_000` (year 10183); each with an `email` string column. Config: `t` passthrough, `email` redact, seed 7.

- AT-1 (red on base). `estimate_job_capacity` on `T_NS` and both `D_FAR` files returns `NOT_APPLICABLE` and does not raise. FK cell: the parent/child pair of `tests/unit/execution/test_capacity_estimate_job.py` (`_ooc_config`, `low_threshold`) with a `T_NS` column on the parent gives the same verdict and `needed_bytes` as the pair with that bad value replaced by `1000`.
- AT-2 (red on base). `profile_source` on each fixture as local Parquet: column `t` has `dtype="object"`, `null_count=0`, `distinct_count=4`, lengths None, `sampled=False`, and the `shape` of the same column with the bad value replaced. A 5-row cell with a null at row 1 gives `null_count=1`, `distinct_count=4`.
- AT-3 (green on base on purpose, except the marked cells). Parity: for every `tests/native/_rev9_profile_cases.py` case, every `tests/native/_rev9_type_catalogue.py` entry with and without a null, and list, struct and map columns, the bounded `profile_source` result through a local Parquet file (where Parquet stores the type) and through a supplied `pa.Table`, with total = sample and total = 10 x sample, equals `walk_dataframe(reader.sample_frame(n), ...)` field by field, with the same column list. The oracle is `walk_dataframe`, unchanged. Extra cells: a zero-row Parquet file and a zero-row `pa.Table` of the catalogue schema; a 25,000-row file with 4,000-row row groups (F-7); a two-table config profiled in one call (F-11); declared PK and FK columns. Besides comparing both walks, assert the known total, sampled flag, candidate-key flag, PK flag and FK target for empty, complete and capped samples. Plan cells: `plan_to_yaml(compile_plan(...))` equal for the redact, hash, truncate and faker configs of test 20. Red on base: the Probe D cells where base raised, asserted to return. Harness rule (Revision 4): there is no per-family exception exemption. For each cell, call `arrow_walk_admission` first. If it admits the table, the oracle must return and the bounded result must equal it. If it does not, assert the expected reason for that cell (a table in the test module, one row per catalogue entry) and that `profile_source` equals the base outcome: the same profile, or the same exception type. List, struct, map, union, tensor, decimal, `float16` and view-type cells are expected fallbacks (`type_family` or `extension_type`).
- AT-3b (red on base for the reader cells: base already matches itself, so the red is a test-first run of `walk_arrow_table` without the metadata rules, recorded in the builder report; green on base on purpose for the oracle side). Parity over the Probe E corpus, field by field and column list, against `walk_dataframe(reader.sample_frame(n), ...)`. Admitted (assert reason None): dtypes `Int8`/`16`/`32`/`64`, `UInt8`/`16`/`32`/`64`, `boolean`, `string`, categorical unordered and ordered, tz-aware timestamps. Expected fallbacks (assert the reason, then base equality): `string[pyarrow]` and every other ArrowDtype token (`metadata_dtype`), `Float32` and `Float64` (`metadata_dtype`), `period[M]` and `interval` (`extension_type`). Each with and without a null; RangeIndex, named index, filtered index; full and zero rows; written with `df.to_parquet` and read through `ParquetFileSource`, the S3 and GCS fakes, and built with `pa.Table.from_pandas` through `ResidentTableSource`. Plus: a `Float64`-metadata column holding a NaN (fallback, base equality); plan cells for a `when:` numeric check and `check_null_bearing_int_unsupported` over the `Int64` with-null table, equal to base.
- AT-3b also adds `test_arrowdtype_metadata_falls_back` in `tests/unit/profile/test_arrow_bounded_profile.py` (replaces `test_arrowdtype_metadata_matches_pandas`). Construct columns with `pd.ArrowDtype` for int64, double, bool, string, large string, binary, large binary, date32, timestamp and a dictionary. Include a null, a repeated value and a distinct value. For local Parquet and resident tables, assert reason `metadata_dtype` and that `profile_source` equals the base path, including dtype, counts and string lengths. Run M-25 against these cells.
- AT-3c. Add `test_damaged_footer_takes_the_base_path` in `tests/unit/profile/test_arrow_bounded_profile.py` (replaces `test_bounded_profile_uses_current_field_names`). Parameterize each cell over resident, local Parquet and the S3 and GCS fakes. Keep the original blob with `replace_schema_metadata` after each schema operation, and check the bytes on the reader sample. For each cell assert the reason from `arrow_walk_admission`, then that `profile_source` equals the base outcome (`walk_dataframe(reader.sample_frame(n), ..., arrow_schema=_nested_capable_schema(reader))`): the same profile, or the same exception type. Assert that no canary string from the blob is in the profile or in any message.

  | Cell ID | Input | Expected reason |
  |---|---|---|
  | `missing-blob` | no `b"pandas"` key | None (admitted), no hints |
  | `malformed-blob` | invalid UTF-8, truncated JSON, deeply nested JSON, scalar and list roots, `NaN`, `1e999`, a 21-digit integer; one variant also has a `decimal128` field | `metadata_unreadable` |
  | `malformed-section` | `columns` null or an object; `index_columns` a scalar string; a range descriptor with `step` 0 or a `bool` start; `column_indexes` with two levels | `metadata_layout` |
  | `malformed-entry` | a non-object entry, a non-string `field_name`, a duplicate `field_name` | `metadata_layout` |
  | `legacy-name` | an entry with `name` and no `field_name` | `metadata_layout` |
  | `bad-hint` | an unknown dtype holding a canary, an unhashable dtype, a forged `("unicode", "string")` hint on an `int8` field, a plain pair with wrong `metadata` | `metadata_dtype` |
  | `renamed` | nullable `a` renamed to `new_a`, stored index `k` renamed to `new_k`, stale display name `new_a` | `metadata_layout` |
  | `dropped` | first nullable field and a stored index dropped, entries kept | `metadata_layout` |
  | `reordered` | two `int8` fields swapped, a stored index moved between them, metadata order kept | `metadata_layout` |
  | `int-labels` | `pa.Table.from_pandas(pd.DataFrame({0: [1, 2], 1: [3, 4]}))` and its Parquet file: integer column labels give a `column_indexes` level that is not `"unicode"` | `metadata_layout`, base equality |
  | `count-check` | a `columns` list with one extra non-dict entry and otherwise valid | `metadata_layout` |
  | `dict-metadata` | a dictionary field with `metadata` `{"num_categories": true, "ordered": false}`, with an extra key, and with `ordered` not equal to `t.ordered` | `metadata_dtype` |
  | `clean-control` | the same table before damage | None (admitted), parity with the oracle |

- In `tests/unit/profile/test_arrow_bounded_profile.py::test_bounded_walk_decodes_metadata_once`, count calls to `_pandas_meta._columns._strict_pandas_blob` during one `walk_arrow_table` call on a wide table with a stored index and several nullable fields. Expect one call. In S1b, repeat the lookup inside the per-column loop and require this test to fail (M-23).
- AT-4 (red on base). Conversion spy (8.1): `profile_source` over an admitted table as a local Parquet, a fake S3 Parquet, a fake GCS Parquet and a supplied `pa.Table` (each also with valid pandas metadata) records zero calls to `pyarrow.pandas_compat.table_to_dataframe`, `pd.Series.__init__`, `pd.DataFrame.__init__` and `pd.read_parquet`. A CSV control cell and a non-admitted Parquet control cell (a `decimal128` column) each record at least one.
- AT-5 (green on base on purpose, except the message cell). `estimate_job_capacity` raises `ExecutionError` `capacity_source_unprofilable` for a truncated Parquet file, a CSV file declared `parquet`, and a Parquet file with two columns named `a`. Message cell (red on base): the chained `ValueError` text equals `table 't' has 1 duplicated field name(s)`, and `walk_dataframe`, `walk_arrow_table` and `refuse_duplicate_field_names` give that same text for the same names.
- AT-6 (red on base for the row-0 and row-9,999 cells). An 80,001-row `time64[ns]` file with the bad value at row 0, 9,999, 10,000 and 80,000: every `estimate_job_capacity` call returns a verdict; `profile_source` gives `row_count=80_001`, `row_count_exact=True`, `sampled=True`, and `null_count` and `distinct_count` over exactly the first 10,000 rows (asserted against `pyarrow.compute` over `table.slice(0, 10_000)`).
- AT-7 (red on base). `run_pipeline` with the `T_NS` and `D_FAR` sources as `LazySource`, with and without `resident_fallback=True`, and as resident `pa.Table`s, raises `ExecutionError` `full_frame_value_unrepresentable`; `exc.__context__ is None`, `exc.__cause__ is None`; `"".join(traceback.format_exception(exc))` holds no digit string of the bad value. Add `test_full_frame_error_has_no_exception_chain` in `tests/unit/execution/test_full_frame_value_unrepresentable.py`.
- AT-8 (red on base). The frozen value 6.1 (a): a supplied `pa.Table` with sub-µs `time64[ns]` values and no null, and one with year-10183 dates and no null, profile with lengths None; `dtype`, `null_count`, `distinct_count` and `shape` equal base.
- AT-9 (red on base). `S3ParquetSource` and `GcsParquetSource` over the `T_NS` bytes (fakes of `tests/unit/profile/test_duplicate_header_readers.py`): `sample_table(n)` equals the local `ParquetFileSource.sample_table(n)`, schema metadata included, and `profile_source` returns the AT-2 column. Mismatch cell: a fake whose `schema()` metadata differs from its `sample_table(n)` metadata (the object replaced between the two calls) takes the base path, proven with the 8.1 conversion spy recording at least one call and base equality.
- AT-10 (red on base). `tests/unit/profile/test_sample_frame_contract.py` gains a `SAMPLE_TABLE_MATRIX` ("exactly n rows, short only at the end", metadata kept) for the four `sample_table` readers, and asserts that `reader.schema().metadata` equals `reader.sample_table(n).schema.metadata` for a pandas-written source, so admission on the reader schema decides for the sample; `tests/sentry/profiling/test_profile_source_contract_coverage.py` gains a method-name argument on the existing `owned_readers` scanner. Parameterize `test_every_reader_is_in_the_conformance_matrix` and `test_a_reader_missing_from_the_matrix_is_caught` for both methods.
- AT-11 (green on base on purpose). Include `tests/native/test_composite_admission.py::test_unrelated_schema_metadata_changes_are_not_stored_index_drift`. `tests/native/test_chunked_entry_rev9_profile.py`, `tests/native/test_chunked_entry_rev9_catalogue.py` and `tests/sentry/test_column_shape_classifier.py` pass after the move with only the named path edits; the F-13 tests pass with only their import line changed.
- AT-12 (each cell red on the head where Codex found it: `ec85b7a21` for R1, `04459013f` for R2). `test_codex_805_findings` in `tests/unit/profile/test_arrow_bounded_profile.py`, one parameter per finding in section 0a. Each cell builds the reviewer's reproduction, asserts the reason from `arrow_walk_admission` (or None), and asserts that `profile_source` through local Parquet and the resident reader equals the base outcome. Extra asserts per cell:
  - `r1-dict-chunks`: two `int8`-index dictionary chunks with different dictionaries, 200 categories in all: admitted, `distinct_count == 200`.
  - `r1-legacy-name`: `metadata_layout`; `compile_plan` with a truncate config raises `PlanCompileError` as on base.
  - `r1-footerless-ext`: `period[M]` and an interval with no footer: `extension_type`.
  - `r1-float64-nan`: a masked `Float64` with two NaN payloads: `metadata_dtype`; `is_candidate_key_sampled` equal to base.
  - `r1-infer-string`: `future.infer_string=True` set with `pd.option_context` where the option exists (skip with a recorded reason where it does not): `string_inference`; `avg_length` and `max_length` 3 as on base.
  - `r1-nonfinite`: `1e999` in the footer, `index_columns=["x"]`: `metadata_unreadable`; `x` is profiled as base profiles it.
  - `r1-wrong-pair`: `("wrong", "int8[pyarrow]")` on a null-bearing `int8`: `metadata_dtype`.
  - `r2-bad-freq` and `r2-bad-tz`: a `pandas.period` type with an invalid frequency canary, and a timestamp with an unknown timezone canary (one variant on a data field, one on a stored index field). `profile_source` raises `ValueError`; the text equals the 8.5 item 4 text with the label; `__context__` and `__cause__` are None; `"".join(traceback.format_exception(exc))` holds no canary. `estimate_job_capacity` raises `capacity_source_unprofilable` and its rendered chain holds no canary.
  - `r2-arrowdtype-float`: `double[pyarrow]` with two NaN payloads and `[-0.0, +0.0]`: `metadata_dtype`; three distinct as on base.
  - `r2-period-min`: period ordinal `-2**63`: `extension_type`; `null_count == 1` as on base.
  - `r2-interval-zero`: intervals `(-0.0, 1.0]` and `(+0.0, 1.0]`: `extension_type`.
  - `r2-large-binary` and `r2-dict-token`: `large_binary[pyarrow]` and a dictionary ArrowDtype token: `metadata_dtype`; dtype `category` and lengths 3 where base gives them.
  - `r2-infer-floor`: monkeypatch `pd.__version__` and `pd.get_option`. `"3.0.0"` gives True whatever the option says; `"2.3.3"` gives the option value (True, then False); `"2.2.3"` and `"2.0.3"` give False even when `get_option` returns True; `"2.0.3"` with the option absent (`OptionError`) gives False, and a text table is then admitted.
  - `r2-big-int`: a 1,000-digit integer in the footer. Under `sys.set_int_max_str_digits` 640, 4300 and 0 (restored after), the reason is `metadata_unreadable` each time, and at each limit `profile_source` equals the base outcome at that limit (on the probe host: `ValueError` at 640, a profile at 4300 and 0). The cell does not require the three outcomes to be equal.
- AT-13 (new guard). `test_admitted_families_are_frozen` in `tests/unit/pandas_meta/test_columns_admission.py`: the names in `ADMITTED_FAMILIES` and the admitted nullable labels equal a literal set in the test. For every Arrow type in `tests/native/_rev9_type_catalogue.py`, `arrow_walk_admission` on a one-field footerless table gives the literal expected reason from AT-3's per-entry table (one shared table, imported by both tests): None for an admitted type with an AT-3 parity cell, otherwise the named `type_family` or `extension_type`. A catalogue type missing from the table fails the test. Explicit rows include `date64` (`type_family`), `float16` (`type_family`), a dictionary with an unsigned index (`type_family`), a dictionary over `int32` values (`type_family`), `time32[s]` and `time64[ns]` (None). Adding a family needs a test edit and a parity cell.
- AT-14 (red on base: base raises). `test_admitted_values_base_cannot_convert` in `tests/unit/profile/test_arrow_bounded_profile.py`, resident and local Parquet, each cell admitted (reason None):
  - `dict-null-value`: indices `[0, 1, 0]` (`int8`) over `["a", None]`: `null_count == 1`, `distinct_count == 1`, `dtype == "category"`.
  - `dict-dup-value`: indices `[0, 1, 0]` over `["a", "a"]`: `null_count == 0`, `distinct_count == 1`, no candidate key.
  - `time-over-day`: `time32[s]` `[90_000, 1, 2]` and `time64[us]` `[-5, 1, 2]`: `dtype == "object"`, `null_count == 0`, `distinct_count == 3`, lengths None.
  Base raises on each (asserted), so these are 6.1 (d) values, not parity cells.

## 10. Mutations

Run each mutation alone on the final S1b head. Record the failing test and SHA. Section 13 gives the separate S1a mutations.

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
| M-13 | metadata ignored: `walk_arrow_table` passes `pandas_dtype=None` for every column | AT-3b admitted nullable and string cells |
| M-14 | stored index fields not dropped (`table.column_names` in place of `arrow_columns`) | AT-3b named and filtered index cells |
| M-15 | the string-length rule ignores `pandas_dtype == "string"` | AT-3b string with-null cells |
| M-16 | the index widening for multi-chunk dictionaries removed | AT-12 `r1-dict-chunks` |
| M-17 | the full-frame error is raised inside the handler again | AT-7 `__context__` asserts |
| M-18 | `walk_dataframe` keeps its own duplicate-name text | AT-5 message cell |
| M-19 | the layout check compares `field_name` values as a set, not a sequence | AT-3c `reordered` |
| M-20 | Let a JSON decode error escape | AT-3c malformed-blob |
| M-21 | a legacy entry with `name` and no `field_name` is accepted, `name` used as the physical key | AT-3c `legacy-name`, AT-12 `r1-legacy-name` |
| M-22 | a hint is accepted without checking it against `pairs_for(field.type)` | AT-3c `bad-hint` |
| M-23 | Decode the blob again for each column in `walk_arrow_table` | `test_bounded_walk_decodes_metadata_once` |
| M-24 | extension types pass admission (the `extension_type` check removed) | AT-12 `r1-footerless-ext`, `r2-period-min`, `r2-interval-zero`; AT-13 |
| M-25 | any pair in `pairs_for(t)` admitted (ArrowDtype tokens and masked floats included) | AT-12 `r1-float64-nan`, `r1-wrong-pair`, `r2-arrowdtype-float`, `r2-large-binary`, `r2-dict-token`; AT-3b `test_arrowdtype_metadata_falls_back` |
| M-26 | `_strict_pandas_blob` passes `max_int_digits=None` | AT-12 `r2-big-int` (reason differs at limit 0); AT-3c `malformed-blob` 21-digit cell |
| M-27 | `arrow_strings_restore_as_text` returns True when the option is absent | AT-12 `r2-infer-floor` |
| M-28 | the `string_inference` check removed from admission | AT-12 `r1-infer-string` |
| M-29 | (a) the type probe removed; (b) the refusal message interpolates `str(exc)`; (c) the refusal is raised inside the `except` block. One at a time | AT-12 `r2-bad-freq`, `r2-bad-tz` |
| M-30 | the fallback passes `arrow_schema=None` to `walk_dataframe` | AT-3 list, struct and map fallback cells |
| M-31 | admission skips non-dict or keyless entries instead of failing the layout | AT-3c `malformed-entry` |
| M-32 | a range descriptor with `step` 0 or a `bool` member accepted | AT-3c `malformed-section` |
| M-33 | `float16` or union admitted (one at a time) | AT-3 harness cells for those types; AT-13 |
| M-34 | the `metadata` member of a footer entry not compared with `column_metadata(t)` | AT-3c `bad-hint` wrong-metadata cell; AT-3b ordered categorical cell |
| M-35 | a family added to `ADMITTED_FAMILIES` with no test change | AT-13 |
| M-36 | `date64` admitted again | AT-13 `date64` row; AT-3 `date64` sub-day cell |
| M-37 | the dictionary predicate widened (any index type, or any value type) | AT-13 unsigned-index and `int32`-value rows |
| M-38 | the temporal predicate widened (any `time` or `date` unit) | AT-13 `date64` row; M-36 cells |
| M-39 | the `column_indexes` rule removed | AT-3c `int-labels`, `malformed-section` two-level cell |
| M-40 | the `name == field_name` rule removed | AT-3c `renamed` stale-display-name cell |
| M-41 | the type probe skips stored index fields | AT-12 `r2-bad-tz` variant with the bad timezone on a stored index field |
| M-42 | items 2 and 3 of 8.5 run in swapped order | AT-3c `malformed-blob` cell with a non-admitted field (expects `metadata_unreadable`, mutant gives `type_family`) |
| M-43 | the sample schema equality check in 8 item 7 removed | AT-9 mismatch cell |
| M-44 | the dictionary is not decoded before the missing mask | AT-14 `dict-null-value`, `dict-dup-value` |
| M-45 | `arrow_strings_restore_as_text` reads the option on pandas before 2.3 | AT-12 `r2-infer-floor` `2.2.3` cell |

## 11. Class tables

dev-rules `catalogs/recurring-defects.md`:

| Class | This row |
|---|---|
| 1 anchored validation | admission matches each footer pair by exact equality with a registered pair for the physical type, and the layout by exact sequence equality with `schema.names` |
| 2 strict types | 8.5 item 2 checks producer JSON types (`int` not `bool`, `str` keys, dict entries) before use; the decode bounds integer literals by length. AT-3c and AT-12 cover them |
| 3 exception context | 8 item 6 removes the value-bearing `__context__`; AT-7 asserts both links None; M-17 |
| 4 versioned read models | n/a |
| 5 guard scanners | AT-10 walks classes by `__dict__` like its sibling; covered shape: a class whose own body defines `sample_table` |
| 6 private imports | schema imports go into the foundation tier (`profile -> _pandas_meta`, `execution -> _pandas_meta`), which `tests/sentry/layout/test_import_layers.py:55` already lists; execution imports the column profiler through `decoy_engine.profile.arrow`; one lazy `profile -> execution._transforms` import is removed |
| 7 hidden CI failures | n/a |
| 8 trust classes | n/a |
| 9 mutations on the final head | section 10 |
| 10 allowlisted helpers | n/a |
| 11 raised caps | module size goal 600, max 700 (`tests/sentry/test_module_size.py`): `_readers.py` goes from 591 to about 571; every new module is under 250; no census grows. The new `profile/arrow/` subpackage keeps the direct Python file count in `profile/` at 20, under the 25-module fan-out cap (`tests/sentry/baselines/package-fanout.json`); `_pandas_meta/` from 2 to 3. No pin moves |

Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes):

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the full-frame error leaves its handler before it is raised, so no chain holds the pyarrow text; the duplicate-name text drops header names; the unreadable-type refusal carries only the `safe_error_type` label and has no chain; no new message carries a cell | AT-7, AT-5 message cell, AT-12 `r2-bad-freq`/`r2-bad-tz`, CLI cells in 13.1 | M-17, M-18, M-1, M-29 |
| 2 | Cleanup missing on an exit path | N/A: no new handle; `iter_batches` reads stay inside the existing `LazySource` and cloud-reader lifetimes | none needed | N/A: no new resource |
| 3 | State machine and concurrency | N/A: no shared state; the walk is a pure function of the sample and never draws from `rng` | AT-3 two-table cell | N/A: no transition added |
| 4 | Route parity and silent fallback | one dispatch in `_profile_one_source`, decided once per table by `arrow_walk_admission` before any read; the fallback is the base path, chosen by type and footer, never by catching an error from the walk | AT-3, AT-3b, AT-3c, AT-4, AT-12 | M-1, M-7, M-8, M-30 |
| 5 | Referential integrity | PK and FK flags set by the wrapper exactly as `walk_dataframe` sets them | AT-3 PK/FK cell, AT-1 FK cell | M-5 |
| 6 | Untrusted producer | the `b"pandas"` blob is producer-written: one bounded parse in `_pandas_meta`; any footer the admission does not fully accept sends the table to the base path; no blob text reaches a profile or message | AT-3c, AT-12; the existing malformed tests in `test_mem_estimate_nullable_metadata.py` | M-19, M-21, M-22, M-26, M-31, M-32, M-34 |
| 7 | Check then use on a path (TOCTOU) | admission reads `reader.schema()` and the walk reads `reader.sample_table(n)`; a cloud reader fetches them in two calls. The walk runs only when `sample.schema.equals(schema, check_metadata=True)`; otherwise the base path | AT-9 mismatch cell | M-43 |
| 8 | Weak tests and overclaimed evidence | each AT records red or green on `26091c834`; parity uses `walk_dataframe` as an unchanged oracle; AT-3b corpus carries real pandas metadata (the test-20 corpus has none); the 20,000 claim in `#399` was re-measured | builder report with base SHA and red output | each mutation names its AT |
| 9 | Behavior-preserving refactor drift | `arrow_column_profile` with `pandas_dtype=None` is the moved body; helpers moved with their tests | AT-11, AT-3 | M-10, M-11 |
| 10 | Frozen contract drift | no public name, signature, reason code or serialized field changes; the two moved values are named (6.1) and frozen | AT-8, AT-5, signature sentry unchanged | M-8, M-18 |

### 11.1 Frozen contracts

- Public API: no name or signature changes. `ProfileSource` is unchanged; the Arrow sample is a separate private protocol.
- `Profile` and `ColumnProfile` serialization (`profile_to_json`, `profile_hash`): no field added; every value equal for the valid-input parity matrices, pandas-written input included (AT-3, AT-3b), so plan bytes and profile hashes do not move.
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

- Errors: the raw pyarrow profile error goes away on these paths for admitted tables; an unreadable extension or timezone type gives the value-free `ValueError` (6.1 c); the full-frame error loses its chained context; the duplicate-name `ValueError` text changes (6.1 b).
- CLI stdout, `--json` and exit codes: per section 6 (13.1 cells).
- Returned profiles and plans: equal for admitted tables (AT-3, AT-3b); equal by construction for the rest, which run the base path (AT-3, AT-3c, AT-12).
- Logs, audit, evidence, progress: N/A, unchanged; the profile writes none.

### 11.3 Reuse inventory

- `arrow_column_profile` and its helpers, moved, with one keyword added.
- `stored_index_fields`, `arrow_columns`, `pandas_nullable_columns`, moved into `_pandas_meta`; `arrow_walk_admission` reads the index, layout and dtype facts from one bounded decode; `pairs_for` and `column_metadata` from `_pandas_meta/_descriptors.py` are the only source of admitted pairs; `strict_json_loads` bounds the decode; `safe_error_type` gives the refusal label.
- `ParquetFile.iter_batches` and `_read_parquet_sample` for the sample.
- `_field_names.repeated_names` for the duplicate-name scan; the guard's existing text.
- `canonical_dtype_label` (`internal/pandas_compat`) for the dtype label; `observed_shape` for `shape`.
- The `sample_frame` conformance matrix and its coverage sentry, extended to `sample_table`.
- Test corpora: `tests/native/_rev9_profile_cases.py`, `tests/native/_rev9_type_catalogue.py`, the S3 and GCS fakes in `tests/unit/profile/test_duplicate_header_readers.py`, `_ooc_config` in `tests/unit/execution/test_capacity_estimate_job.py`.

## 12. Placement

| File | Directory | CODEMAP "Where Things Go" row | Sits beside |
|---|---|---|---|
| `_columns.py` (new) | `src/decoy_engine/_pandas_meta/` | foundation packages (`src/decoy_engine/_<name>/`) | `_descriptors.py`, the per-type facts |
| `__init__.py` (new) | `src/decoy_engine/profile/arrow/` | "Source readers, profile types" | imports the subpackage functions and protocol |
| `_walk_arrow.py` (new) | `src/decoy_engine/profile/arrow/` | "Source readers, profile types" | `_walk.py`, its pandas twin |
| `_arrow_sample.py` (new) | `src/decoy_engine/profile/arrow/` | "Source readers, profile types" | `_readers.py` |
| `test_arrow_bounded_profile.py` (new) | `tests/unit/profile/` | tests in `tests/unit/profile/` | `test_bounded_profiling.py` |
| `test_columns_admission.py` (new) | `tests/unit/pandas_meta/` | tests mirror the source package | `test_descriptors.py` |
| `preflight-arrow-profile.md` (new) | `changelog.d/` | "Changelog fragments" | the other fragments |
| `CODEMAP.md` (edit) | root | n/a | row 107: the Arrow column profile is in `profile/arrow/_walk_arrow.py`; row 126: add `_walk_arrow.py` and `_arrow_sample.py`; the `_pandas_meta` row adds per-column facts |

Changelog fragment, `changelog.d/preflight-arrow-profile.md`:

```
### Fixed (bounded profile reads Arrow, PREFLIGHT-ARROW-PROFILE, 2026-11-23)

The bounded source profile of a Parquet file (local, S3, GCS) or a supplied `pa.Table` is
computed from the Arrow sample with `pyarrow.compute`, not through pandas. It is used when every
column has a plain Arrow type, or a pandas nullable integer, boolean or string dtype, and
the pandas schema metadata is well formed. Any other table is profiled through pandas as
before, so its result does not change. A column type pandas cannot restore (an invalid
period frequency or unknown timezone) now raises a `ValueError` that does not quote the
schema text. A `time64[ns]` value with a sub-microsecond part or a date
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
| S1a | engine | Move the existing Arrow column profiler, its private helpers and the three schema functions. Update imports, the column-shape sentry, import-layer entries and CODEMAP. Keep callable signatures, helper behavior and reader dispatch unchanged. | About 200 source lines relocated, 15 caller files, mostly import edits. | R1 |
| S1b | engine | Add the table admission (8.5), the bounded Arrow walk for admitted tables, the base-path fallback, the value-free unreadable-type refusal, the string inference detection fix, reader methods, shared duplicate-name message and full-frame error handling. Update the remaining sentries, CODEMAP and changelog. Revision 4 reworks the open PR #805 in place: it removes the walk code for excluded families and adds the admission; no force-push. | About 170 new source lines in `_columns.py`, a net reduction in `_walk_arrow.py` from the `04459013f` head, reader edits, and about 700 test lines. | R2 |
| S2 | engine | Owner-gated first step (Q-PAP-D7, default: raise): set `pandas>=2.0.3,<3` in `pyproject.toml` and the lock, because on pandas 1.5 `duration[s]` restores as ns and breaks parity for an admitted family. Then release: compile the fragment with `scripts/release/stamp_release.py`, bump to the next patch version, tag. The floor CI leg stays a follow-up row | `pyproject.toml`, lock, release files | R2 (established release path; a dependency floor change is a full-suite trigger) |
| S3 | CLI | Repin to the S2 release per the engine repin checklist (compat, fences, FROZEN, doc, `PIN_PREFIX`, Dockerfile ARG, catalog); test and doc changes in 13.1 | pin files plus about 120 test lines; no CLI source logic change | R1 |

Merge S1a first. Run AT-11, including the named schema, chunk guard and parity tests in sections 5.1 and 8.4. On the final S1a head, seed each move regression separately. Return an empty set from `stored_index_fields` and require `test_source_columns_reads_header_only` to fail. In `_chunk_schema.check_stored_index`, replace the lookup on the incoming schema with an empty set and require `tests/native/test_composite_admission.py::test_unrelated_schema_metadata_changes_are_not_stored_index_drift` to fail. Its two schemas have the same stored index and different metadata bytes, so it reaches both lookups. Change the non-null integer label in `internal/pandas_compat.py:arrow_dtype_label` and require `test_arrow_column_profile_equals_the_pandas_profile_field_for_field` to fail. Restore each mutation and record the SHA.

On the final S1b head run AT-1 through AT-14, including AT-3b, AT-3c and the full suite. Run M-1 through M-45 separately and record the test failure and SHA for each. S2 follows S1b. S3 needs S2 and CLI #399.

### 13.1 S3, CLI test and doc changes

- `test_at_c12_the_cli_preflight_refuses_these_sources_first` becomes `test_at_c12_the_cli_runs_these_sources`: through `decoy run --chunked`, default intent exits 0 and the `t` column equals the source exactly; `--no-native` exits 3 with `chunked_passthrough_value_unrepresentable` and none of the `_LATE` markers in the output; neither output says `source not parsed`.
- `test_at_c12_default_runs_exact_and_no_native_fails` and `test_at_c14_a_read_refused_value_is_coded_and_value_free` stop calling `_direct` (its reason, the preflight refusal, is gone) and run through the CLI. `_direct` is deleted if nothing else uses it.
- `TestLateRefusedValue`: behaviour unchanged. Its comment drops "past the 20,000-row preflight sample". `test_default_run_publishes_the_value_exactly` is parametrized over the bad row {0, 80,000}.
- New: plain `decoy run` on the two `_REFUSED_SOURCES` exits 3 with `full_frame_value_unrepresentable`, no bad-value marker in stdout, stderr or `--json`, no output file (G-1).
- New: `decoy validate preflight` on the two sources reports no `capacity.source_unreadable`; a truncated Parquet still does (exit 1).
- Docs: remove the PREFLIGHT-ARROW-PROFILE carve-out from the `CHANGELOG.md` entry; check the `decoy explain chunked`, `docs/cli-reference.md` and `run --help` text that `#399` names for the same sentence.

## 14. Pre-mortem

- A parity cell differs on an admitted type. Revision 4 answer: remove that family from `ADMITTED_FAMILIES` (it then takes the base path) rather than add walk rules in this row; record the widening in the V2 log. A new pyarrow type is not admitted until it is added to the table with a parity cell (AT-13).
- A third review round finds a new family difference. It can only be in an admitted family, which AT-3 tests without exemptions; the fix is the same removal, which does not change the plan.
- Most real files fall back, so the row fixes little. The bad-value types (`time64[ns]`, `date32`; `date64` falls back, 0b B1) and the common companions (integers, floats, text, timestamps, nullable integers) are admitted; `df.to_parquet` with default dtypes writes only admitted pairs. A file that mixes a bad value with a decimal or nested column still fails as on base (D8).
- The S2 floor raise is declined. Then pandas 1.5 users get a `duration` parity difference; the fallback would need `duration` removed from the admitted set before release (owner call on Q-PAP-D7).
- Mac or Windows pandas differs. CI pins `pandas<3`; the oracle runs on the same host, so a host difference shows as a parity failure.
- pandas 3 changes the default string dtype. String inference is then on, so every text table falls back (`string_inference`) and keeps the pandas 3 result. Nothing silent changes.
- A builder makes a parity cell pass by editing the oracle. Keep the existing pandas statistics as the independent oracle. Check any shared profile assembly against the base output in AT-3 before either walk uses it.

## 15. Open decisions

- D1. A plain `decoy run` of these sources still exits 3 after this row. Recommended (accepted by Dennis R1): accept for this row, and open the follow-up row "run plain-route passthrough columns without pandas" tagged 1.0-blocking, since the plain run is the default path.
- D2. Also ship the CLI-only fallback (skip capacity pricing on `--chunked`)? Recommended: no. After S1b the refusal is gone at its source on every path.
- D3. Land the CLI test flip in a separate PR after `#399` and the S2 release, or fold it into `#399`? Recommended: a separate PR. The wrong "20,000-row" sentence in `#399` is corrected to 10,000 in `#399` before it merges.
- D4. Remove `ResidentTableSource._frame_of`'s text-cast fallback? Recommended: no, not in this row. It still serves `to_frame` and `sample_frame`; the D5 row decides it.
- D5. One follow-up row for `decoy scan` / `init` and the chunked first-chunk profile (G-4)? Recommended (accepted by Dennis R1): yes, tagged 1.0-blocking, because scan and init raise a raw `ValueError` containing the year on a valid Parquet file (`profiling/scan_set.py:339`).
- D6. The duplicate-name `ValueError` text from the profile walk changes to the shared value-free text (6.1 b). Recommended: accept. The alternative, keeping two texts, leaves the column names (producer text) in an engine message.
- D7 (owner, Q-PAP-D7 open, default raise). `pyproject.toml` declares `pandas>=1.5.0,<3`; the supported floor is stated as 2.0.3; no CI leg runs either. On pandas 1.5 `duration[s]` restores as ns, so an admitted family breaks parity there. Recommended: S2 raises the declared floor to `pandas>=2.0.3` before the release ships; the floor CI leg is a follow-up row.
- D8 (owner). A table that has a bad value (6) and also a non-admitted field (for example a decimal) still fails at preflight, as on base. Recommended: accept for V1; widen one family per row with its own parity cells, decimal first.
- D9 (owner). `capacity.py:332` puts `{exc}` in its message and chains `from exc`, and the CLI reads `type(exc.__cause__).__name__`. Not in S1b: it is a two-repo change. Follow-up row G-5 (engine and CLI): a label-only message plus a cause label the CLI can read.
