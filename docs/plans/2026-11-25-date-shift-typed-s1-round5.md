# DATE-SHIFT-TYPED S1: round 5 rule, physical temporal bounds

Status: plan

Rules consulted: 00-universal, development-loop, bugfix, cross-cutting-concerns, testing,
architecture, recurring-defects catalog.

This note replaces the "Rule" and "Acceptance tests" sections of
`2026-11-25-date-shift-typed-s1-round4.md` for PR #790. The rest of round 4 stays (non-goals,
deferred items). Codex round 4 on `b6c7785d5` returned NO-GO with five V1 findings and one
DESIGN finding. The five V1 findings are one class: a range decision that depends on pandas
metadata or on per-version conversion, not on the physical Arrow value.

| # | Finding | Root cause |
|---|---|---|
| F1 | `timestamp[s]` with stale `timestamp[ns][pyarrow]` metadata: the final `to_pandas` raises `ArrowInvalid` that quotes the source integer | the bound is on the physical type, but the conversion target comes from the metadata |
| F2 | `America/New_York` near year 1 segfaults on iteration; zoned ns near int64 max fails; UTC edge values are nulled | the one-day zone margin is the wrong model: pandas does zone work in int64 nanoseconds |
| F3 | pandas 1.5.3: one year-2500 `timestamp[s]` cell nulls the whole column | pandas 1.x converts every timestamp to ns; the bound assumes the physical unit |
| F4 | `timestamp[ns]` `INT64_MIN` counts as null or not, depending on metadata | the bound admits the NaT sentinel; only the numpy conversion reads it as NaT |
| F5 | full-frame and sequential masking with Arrow-backed `date32` year 10000 raise uncoded `OverflowError` | the refusal runs only after a conversion fails, and Arrow-backed conversion does not fail |

The DESIGN finding (the arithmetic sentry misses `from datetime import timedelta as td`) is
fixed here too, as P8.

Review history of this plan: Dennis R1 GO-WITH-FIXES (folded). Codex plan R1 NO-GO with three
V1 findings, folded in this revision: (a) the fixed-offset profile bound ignored the shifted
storage range; (b) a masking probe inside the shared `to_pandas_fk_safe` refused exact native
work (`when:` on `time64[ns]`, the Faker null mask on a far `date32`); (c) a bound table for
masking cannot cover every physical/target unit pair. The masking half is now a different
rule: metadata never decides, checked by a differential test, at the pandas masking sites only.

## Established solutions

Search run: the pyarrow `Table.to_pandas` reference (`coerce_temporal_nanoseconds`,
`ignore_metadata`, `safe`, `types_mapper`), the pyarrow `pandas_compat` reconstruction of
extension dtypes from schema metadata, the pandas timestamp limitations page
(`Timestamp.min`, `Timestamp.max`, non-nanosecond units from pandas 2.0), and in-codebase
`arrow_missing_mask`, `table_to_pandas_exact_ints` and `to_pandas_fk_safe`. Each claim below
was also measured on pandas 2.3.3, pyarrow 24.0.0 (the dev venv).

- pyarrow builds an extension dtype for a column from the `pandas` schema metadata when
  `numpy_type` names one (`timestamp[ns][pyarrow]`, `datetime64[ns, America/New_York]`) and
  casts to it with `safe=True`; the cast error quotes the value. Measured: both stale entries
  raise `ArrowInvalid ... out of bounds timestamp: 1000000000000`. An entry with `numpy_type`
  `"object"` makes pyarrow use the physical default (`datetime64[s]`, `object` dates), and the
  stored index still rebuilds (`index_columns` kept, values `[5, 6]` restored).
- `ignore_metadata=True` also fixes F1 but turns a stored index into a data column, so the
  profile would gain a `__index_level_0__` column. Not used.
- `coerce_temporal_nanoseconds` (pyarrow 13+, the floor here is 14) chooses ns or the
  physical unit for timestamps and durations. Under pandas below 2.0 pyarrow always coerces.
- pandas holds datetime64[ns] in `[INT64_MIN + 1, INT64_MAX]` (`pd.Timestamp.min.value`,
  `pd.Timestamp.max.value`); `INT64_MIN` is `NaT`.
- A zone with transitions goes through ns transition tables. Measured on cell `str()`:
  `timestamp[s, America/New_York]` at `-9_300_000_000` (year 1675) segfaults, at
  `-9_223_372_036` it does not; `Europe/London` the same; `Asia/Kolkata` below the ns range
  raises `KeyError: '+0630'`. UTC and `+05:30` print at years 1 and 9999.

Custom code left: the bound table (pyarrow has no per-cell "would this cast succeed" kernel)
and the metadata reconciliation (pyarrow has no option to drop only the dtype hints).

## Guarantee

Profile: every temporal column that enters a profile frame is judged on its physical integer
by one table, whatever the pandas metadata says and on every supported pandas major. An
out-of-bound cell reads as null and its neighbours keep their values.

Pandas masking routes (full frame, sequential, chunked oracle, unified admission): a run's
outcome does not depend on the `pandas` metadata of its temporal columns. A source with
Arrow-backed or stale temporal metadata succeeds or is refused exactly as the same source with
that metadata removed, with the same released code. Native callers of `to_pandas_fk_safe`
(`when:` mask, Faker null mask, group-key kernel, transforms table, mixed FK bridge) do not
change.

No error, warning or statistic carries the value.

Non-goals: temporal values nested in lists or structs; exact per-zone bounds for zones with
transitions; the native route; value-bearing errors on a pandas masking route for a source
with no temporal metadata (listed under Deferred, not this class).

## Rule

1. **The physical Arrow type decides; metadata never does.** Before conversion, the `pandas`
   metadata entry of every temporal field (date, time, timestamp, duration; data or index
   column) is reconciled to the physical field. The `pandas_type` and `metadata` members come
   from the existing registry, `_pandas_meta` (`pairs_for(field.type)[0]` and
   `column_metadata(field.type)`, `src/decoy_engine/_pandas_meta/_descriptors.py:89,107`), so
   no temporal fact is decided twice. The profile keeps one local override, `numpy_type`
   `"object"`, which makes pyarrow use the physical default. All other entries and
   `index_columns` / `column_indexes` stay as they are. One function,
   `reconcile_temporal_metadata(table, *, only_stale: bool) -> pa.Table`, in
   `internal/pandas_compat.py`. With `only_stale=True` (masking) it rewrites only an entry
   whose `(pandas_type, numpy_type)` pair is not in `pairs_for(field.type)`, and writes the
   registry's plain pair. It never raises: unparseable metadata returns the table unchanged;
   an entry with no matching field, or a duplicated field name, is skipped.
2. **One bounds table.** `temporal_bounds(kind, *, coerce_ns)` in `decoy_engine/_arrow_types.py`
   returns `(low, high, step)` on the physical integer. The target unit is `ns` when
   `coerce_ns`, else the physical unit. `coerce_ns` comes from one helper,
   `pandas_coerces_temporal_ns()` in `internal/pandas_compat.py` (`True` when the pandas major
   is below 2). Every conversion that relies on the bound passes the same value to
   `to_pandas(coerce_temporal_nanoseconds=...)`, so the bound and the conversion agree.
3. **The NaT sentinel is missing everywhere.** For timestamp and duration, `INT64_MIN` is never
   inside the bound, on any unit, with or without metadata. This matches `arrow_missing_mask`
   (`src/decoy_engine/internal/pandas_compat.py:55`).
4. **Per cell, never whole column.** The profile read nulls each out-of-bound cell on Arrow.
   The whole-column fallback in `profile_frame` stays only for a type with no bound (a nested
   column). If a bounded column still fails `to_pandas`, that is a bound bug: `profile_frame`
   raises `ValueError` naming the column only, `from None`.
5. **Masking: metadata never decides.** One helper, `to_pandas_masking_frame(table,
   lossless)` in `src/decoy_engine/execution/_fk_keys.py`, replaces `to_pandas_fk_safe` at the
   five pandas masking sites: the adapter ingestion (`_pandas_adapter.py:205`), sequential
   (`_sequential.py:415`), unified admission (`_unified_slice_admission.py:347`), and the two
   attribution retries (`_pipeline_full_frame.py:81`, `_chunked_carry.py:143`). It does two
   things, then calls `to_pandas_fk_safe` unchanged:
   - `reconcile_temporal_metadata(table, only_stale=True)`: a stale entry (F1, and the
     `s`/`ms` unit pairs of Codex plan R1) is replaced by the registry's plain pair, so pyarrow
     never casts to a unit or kind the physical field does not have.
   - For each temporal field whose remaining entry names an Arrow-backed dtype (`numpy_type`
     ending in `[pyarrow]`), a trial conversion of that one column with the entry set to the
     plain pair. If the trial fails, the helper raises `ValueError(f"column {name!r} holds a
     temporal value pandas cannot represent")` `from None`. The trial is what the same column
     with no metadata would do, so the outcome matches the no-metadata run. The successful
     trial frame is dropped; the real conversion keeps the Arrow-backed dtype, so in-range
     output is unchanged.
   The error text depends on the column name only, so each attribution retry (which calls the
   same helper) reproduces it and assigns the released code: `full_frame_value_unrepresentable`
   with table and column on full frame and sequential, `chunked_passthrough_value_unrepresentable`
   for a read passthrough on the chunked oracle, and a decline in unified admission (which then
   reaches the legacy route's coded refusal, so flag-on and flag-off stay equal). The sentinel
   is not special here: `INT64_MIN` converts to `NaT` in the trial as it does with no metadata.

### Bounds table (inclusive, physical unit P, target unit T)

`PY_LOW` and `PY_HIGH` are 0001-01-01T00:00 and the last tick of 9999-12-31, from
`DATE32_MIN_DAY` and `DATE32_MAX_DAY`. `NS_LOW = INT64_MIN + 1`, `NS_HIGH = INT64_MAX`.
Unit conversion is exact integer arithmetic: a lower bound rounds up, an upper bound down.
Every bound is clamped to `[NS_LOW, NS_HIGH]` before it reaches a compute kernel, because
`pc.less_equal` on an int64 array raises `TypeError` for a scalar outside int64. The table is
the profile's only; masking does not use it (rule 5).

`S_LOW`, `S_HIGH` below are the storage limits of the target unit in P ticks: `[NS_LOW,
NS_HIGH]` read in ns when T is `ns`, else `[INT64_MIN + 1, INT64_MAX]`.

| Arrow type | Bound | Why |
|---|---|---|
| `date32`, `date64` | `PY_LOW` to `PY_HIGH` (days, or ms for date64) | `datetime.date` |
| `time32`, `time64` | 0 to one day less one tick; step 1000 for `ns` | `datetime.time` holds microseconds |
| `timestamp` naive or `UTC` | `[max(S_LOW, PY_LOW), min(S_HIGH, PY_HIGH)]` | the cell must fit the target unit and `datetime` |
| `timestamp` fixed offset `off` (`+HH:MM`, `-HH:MM`) | `[max(S_LOW, S_LOW - off, PY_LOW - off), min(S_HIGH, S_HIGH - off, PY_HIGH - off)]` | both the stored instant and the wall time (instant plus offset) must fit the unit, and the wall time must be a `datetime` |
| `timestamp` any other zone | the naive bound intersected with `[NS_LOW + 1 day, NS_HIGH - 1 day]` in ns, in P | pandas converts zones through ns tables; the day keeps the wall time inside int64 |
| `duration` | `[S_LOW, S_HIGH]` | pandas 1.x coerces to ns |

For the profile, T is `ns` when `coerce_ns`, else P. The profile always reconciles every
temporal entry (rule 1), so no other unit pair reaches a profile conversion.

Zone classification is a string check on `field.type.tz`: `UTC` and `+HH:MM` / `-HH:MM` are
fixed; every other string is a zone with transitions. `Etc/GMT+5` therefore takes the narrower
bound, so its pre-1677 values read as null in a profile. That is safe and is recorded.

## Choke points

- Profile: `profile_frame` (`src/decoy_engine/profile/arrow/_frame.py:19`), already the one
  Arrow-to-pandas conversion for profile reads (round 4). It now calls
  `reconcile_temporal_metadata`, then the bounds, then one `to_pandas`.
- Masking: `to_pandas_masking_frame` at the five pandas masking sites named in rule 5. The
  existing caller sentry `tests/sentry/defects/test_lossless_int_columns.py` is extended: those
  five sites must call `to_pandas_masking_frame`, and the native callers (`native/_when_mask.py`,
  `native/_faker_null_mask.py`, `native/_group_key_kernel.py`, `_transforms_table.py`,
  `_mixed_fk_bridge.py`) keep `to_pandas_fk_safe`. Guard: P5 (differential) on each route and
  the sentry. Mutation M8 (one site back to `to_pandas_fk_safe`) turns the sentry and P5 red.
- Codes stay where they are today: the helper raises a plain `ValueError`, and the existing
  after-failure attribution turns it into the route's released code.

## Acceptance tests (each fails on `b6c7785d5` unless marked new surface)

| Id | Case | File |
|---|---|---|
| P1 | Local Parquet, `timestamp[s]` cells `[0, 16725225600, 1]` (year 2500) with stale `timestamp[ns][pyarrow]` metadata: `scan_sources(strategy="full")` and `profile_source` return; on pandas 2 the middle cell is kept as 2500-01-01 and the dtype is `datetime64[s]`; no output, warning or exception text holds `16725225600` | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P1b | Same cells, stale `datetimetz` metadata naming `America/New_York` over the naive field: same result, and the profiled column is naive (the physical type, not the metadata zone) | same |
| P1c | A table from `pa.Table.from_pandas` with a named non-range index plus P1's stale entry: `profile_frame` keeps the index values and name; `__index_level_0__` is not a column | same |
| P2a | Full Parquet scan, `timestamp[s, America/New_York]` at year 1 day 2 and epoch, in a child process (`sys.executable`): exit code 0, the year-1 cell null, epoch kept | same |
| P2b | Full scan, `timestamp[ns, America/New_York]` at `INT64_MAX - 3_600 * 10**9`: returns, that cell null | same |
| P2c | `profile_frame`, `timestamp[s, UTC]` at noon 0001-01-01 and noon 9999-12-31: both kept | same |
| P2d | `timestamp[s, +05:30]`: the instant whose wall time is 9999-12-31T23:59:59 is kept, one second later is null; the mirror at year 1 | same |
| P2e | `timestamp[s, Asia/Kolkata]` at year 1 day 10, in a child process: exit 0, null, no `KeyError` | same |
| P2f | Rendered profile (top values, `profiler.py:99`) of `timestamp[ns, +05:30]` at `INT64_MAX` and `INT64_MAX - 5.5 h`: the first is null, the second is kept and renders as year 2262. Mirror for `timestamp[ns, -05:00]` at `NS_LOW` (null) and `NS_LOW + 5 h` (kept, year 1677). No `OutOfBoundsDatetime` and no timestamp text in any output | same |
| P3 | `timestamp[s]` `[0, 2500-01-01, 1]` with `pandas_coerces_temporal_ns` patched to `True`: only the middle cell is null and the dtype is `datetime64[ns]`. The builder also runs `profile_frame` alone (the package does not import on pandas 1.5.3 for an unrelated reason) under pandas 1.5.3 in a throwaway venv and records the result (evidence, not CI) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P4 | Full Parquet scan of `timestamp[ns]` `[INT64_MIN, 0, INT64_MIN, 1]`: null count 2 with default metadata and 2 with `timestamp[ns][pyarrow]` metadata; the same for `duration[ns]` | same |
| P5 | Differential, pandas masking forced, on full frame, sequential and the chunked oracle (passthrough column plus the masked `name` sibling, as in `test_full_frame_value_unrepresentable.py`). For each fixture, run once with the given metadata and once with the `pandas` metadata removed; assert the same outcome: both succeed with equal output values, or both raise `ExecutionError` with the same code (full frame, sequential: `full_frame_value_unrepresentable`, table and column named). Fixtures: `date32` `[0, 2932897, 1]` with `date32[day][pyarrow]` (F5: red today, the metadata run raises an uncoded `OverflowError`); `time64[ns]` `[1, 2]` with `time64[ns][pyarrow]`; `timestamp[s]` year 2500 with stale `timestamp[ns][pyarrow]`; `timestamp[s]` `10**16` with stale `timestamp[ms][pyarrow]`; `timestamp[ms]` `12345` with stale `timestamp[s][pyarrow]`; in-range `timestamp[us]` with `timestamp[us][pyarrow]` (both succeed). No `str(exc)` or rendered chain holds a fixture integer or its year | `tests/unit/execution/test_full_frame_value_unrepresentable.py` |
| P5b | Chunked oracle, the far `date32` column read by a `when:` with `date32[day][pyarrow]`: the same `chunked_passthrough_value_unrepresentable` code, `'chunk '` in the message, `__cause__` set, as the same run without metadata | same |
| P5c | Unified admission flag on and off, P5's `date32` fixture with Arrow-backed metadata: both give `full_frame_value_unrepresentable` (admission declines) | same |
| P5d | Regression guards, green today and kept: native `when:` on Arrow-backed `time64[ns]` ticks `[1, null, 0]` selects the expected rows and returns the column exactly; the chunked positional Faker job on Arrow-backed `date32` year 10000 succeeds; the zoned rev9 shapes (`tests/native/_rev9_support.py:64`) stay `"exact"`; `tests/native/test_c8_i_when_mask.py` and `test_chunked_entry_rev9_shapes.py` stay green unchanged | same, and existing files |
| P5e | Sentry: the five pandas masking sites call `to_pandas_masking_frame`; the native callers call `to_pandas_fk_safe` | `tests/sentry/defects/test_lossless_int_columns.py` |
| P6 | No-regression, new surface (guard): for tables from `pa.Table.from_pandas` with numpy dtypes (dates, naive and zoned in-range timestamps, timedelta, DatetimeIndex, zoned DatetimeIndex, a MultiIndex with a datetime level), `profile_frame(t)` equals `t.to_pandas()` (`assert_frame_equal`, dtypes included) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P6b | Disclosed change, new surface: correct Arrow-backed metadata (`timestamp[us][pyarrow]`, `date32[day][pyarrow]`) now profiles as the physical default (`datetime64[us]`, `object`), the same label the Arrow walk (`arrow_dtype_label`) gives. `reconcile_temporal_metadata` returns the table unchanged for unparseable `pandas` metadata, skips entries with no matching field (after `select`) and duplicate field names, and never raises | same |
| P7 | Bounds edges for every table row and unit, `coerce_ns` both ways, including `timestamp[ns, -05:00]`, `timestamp[ns, +05:30]` and `timestamp[s, +05:30]` (the fixed-offset edges use the three-term formula): the expected edges are computed in the test from independent constants (`datetime(1, 1, 1)`, `datetime(9999, 12, 31, 23, 59, 59, 999999)`, the offset, `pd.Timestamp.min.value`, `pd.Timestamp.max.value`), never from `temporal_bounds`; low and high in, low - 1 and high + 1 out (skipped where high is `INT64_MAX`), `INT64_MIN` out; no bound lies outside int64 | `tests/unit/test_arrow_types.py` |
| P8 | Arithmetic sentry finds `from datetime import timedelta as td; td(days=1)` (red today); `import datetime as dt; dt.timedelta(days=1)` is a guard (green today) | `tests/sentry/defects/test_date_shift_one_arithmetic.py` |
| R1-R6, A1-A7, D1-D3 | Round 3 and round 4 cases stay green; R5's zoned case uses `America/New_York` and its expectation still holds | existing files |

A segfault kills the test runner, so P2a and P2e run the scan in a child process and assert on
its exit code and its JSON output. P5d, P6 and P8's second case are guards that are green
today; every other P case records red on `b6c7785d5`.

## Mutations

| Id | Mutation | Red |
|---|---|---|
| M1 | skip `reconcile_temporal_metadata` in `profile_frame` | P1, P1b |
| M2 | reconcile by dropping the whole `pandas` metadata | P1c, P6 |
| M3 | classify UTC as a zone with transitions | P2c |
| M4 | classify every zone as fixed (no ns intersection) | P2a, P2e |
| M5 | drop the one-day margin in the ns intersection | P2b |
| M6 | ignore `coerce_ns` in the bound | P3 |
| M7 | admit `INT64_MIN` | P4, P7 |
| M8 | one masking site back to `to_pandas_fk_safe` | P5e, and P5 on that route |
| M9 | restore the whole-column fallback for bounded types, with a patched bound that admits one bad cell so the conversion fails after bounding | P3 variant with the patched bound (only that cell null, not the column) |
| M10 | the arithmetic sentry matches the bare call name only | P8 |
| M11 | the masking helper skips the trial conversion | P5 (`date32`, `time64` fixtures), P5b, P5c |
| M12 | the masking helper reconciles every entry, not only stale ones | P5 in-range fixture (output dtype changes), P5d |
| M13 | the fixed-offset bound drops the `S - off` term | P2f, P7 |
| M14 | the probe moved back into `to_pandas_fk_safe` | P5d (native `when:` and Faker guards), P5e |

## Defect classes (plan contract catalog)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | metadata reconciled and the cell nulled on Arrow before conversion; the masking helper raises a column-only message `from None` | P1, P1b, P2f, P5 | M1, M11 |
| 2 | Cleanup missing on an exit path | N/A: no resource is opened; every new function is pure over an Arrow table | none needed | N/A |
| 3 | State machine and concurrency | N/A: no shared state; `coerce_ns` is read per call | none needed | N/A |
| 4 | Route parity and silent fallback | every profile route calls `profile_frame`; every pandas masking site calls `to_pandas_masking_frame` (sentry-pinned); unified admission uses it too, so flag on and off agree | P4, P5, P5c, P5e | M8, one site reverted |
| 5 | Referential integrity | N/A: no key path changes | none needed | N/A |
| 6 | Untrusted producer | pandas metadata from a source file never decides a profile bound or a masking outcome | P1, P1b, P4, P5 | M1, no reconcile |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is opened | none needed | N/A |
| 8 | Weak tests and overclaimed evidence | each P case records red on `b6c7785d5` except P6 (new surface); child-process isolation for the segfault cases | builder report | M1 to M14 |
| 9 | Behaviour-preserving refactor drift | P6 pins that correct metadata converts exactly as before | P6 equality test | M2, metadata dropped |
| 10 | Frozen contract drift | no released code changes route; native callers unchanged; in-range Arrow-backed masking output unchanged | P5b, P5d pins | M12, M14 |

## Enumerations

### Fields

- date32, date64
- time32 (s, ms), time64 (us, ns)
- timestamp (s, ms, us, ns): naive, UTC, fixed offset, zone with transitions
- duration (s, ms, us, ns)

### Routes

- profile, all through `profile_frame`: local Parquet full, sample and empty schema
  (`src/decoy_engine/profile/_readers.py:415`), S3 and GCS
  (`src/decoy_engine/profile/_cloud_readers.py:271`), resident
  (`src/decoy_engine/profile/_readers_resident.py:34`), chunked first chunk
  (`src/decoy_engine/execution/_chunked_profile.py:42`)
- pandas masking, all through `to_pandas_masking_frame`: full frame (`_pandas_adapter.py:205`),
  sequential (`src/decoy_engine/execution/_sequential.py:415`), the chunked oracle (the same
  adapter per chunk), unified admission (`_unified_slice_admission.py:347`), and the
  attribution retries (`_pipeline_full_frame.py:81`, `_chunked_carry.py:143`)
- native callers, unchanged on `to_pandas_fk_safe`: `when:` mask, Faker null mask, group-key
  kernel, transforms table, mixed FK bridge (P5d)

### Exit paths

- profile normal return: reconciled, bounded, converted once
- profile fallback: a nested column fails and is nulled whole
- profile raise: a bounded column fails; `ValueError` naming the column, `from None`
- masking refusal: the helper's `ValueError`, then the route's existing coded `ExecutionError`,
  or an admission decline, no value
- masking pass: stale entries reconciled, otherwise conversion as today

### FK shapes

N/A: no FK logic changes; a temporal FK key goes through the same helper as any column.

### Output surfaces

- `ColumnProfile.to_dict`, `scan_set_to_dict(detail=True)`, `profile_document` (P1, P4)
- top values (`src/decoy_engine/profiling/profiler.py:99`) (P2a)
- `ExecutionError` text and rendered chain (P5)

## Reuse inventory

`DATE32_MIN_DAY`, `DATE32_MAX_DAY`, `temporal_bounds`, `_bounded` (extended, not copied);
the `arrow_missing_mask` sentinel rule; `_pandas_meta.pairs_for` and `column_metadata` for
reconciliation; the existing attributions and their codes; the `to_pandas_fk_safe` caller
sentry (extended); `import_bindings` and `canonical` from
`tests/sentry/_retry_scan.py:53` for P8; pyarrow `coerce_temporal_nanoseconds`.

## Design notes

No new module or abstraction. The bound stays one table in the bottom-tier
`_arrow_types.py`; the pandas-version fact and the metadata fact each live in one function in
`internal/pandas_compat.py`. The masking helper is a drop-in for `to_pandas_fk_safe` at the
pandas masking sites only and raises into the existing attribution, so no new error path. A
probe inside the shared `to_pandas_fk_safe` was rejected: native callers use it for exact
vector work that a Python-scalar rule would refuse (Codex plan R1).

## Placement

| New file | Directory | CODEMAP row | Beside |
|---|---|---|---|
| none | | | |

All new tests extend existing files: `tests/unit/profile/test_profile_frame_unrepresentable.py`
(profile cases, about +200), `tests/unit/execution/test_full_frame_value_unrepresentable.py`
(masking cases, about +180), `tests/unit/test_arrow_types.py`, and the two sentries.

## Frozen contracts

None changed. `full_frame_value_unrepresentable` and `chunked_passthrough_value_unrepresentable`
keep their routes. The profile dtype label for a column with correct Arrow-backed temporal
metadata changes to the physical default (P6b); a pandas masking run on a source with stale
temporal metadata writes the physical default dtype in its output metadata. The PR adds one
CHANGELOG line covering both.

## Slices

One commit on #790, in this order: bounds table and `pandas_coerces_temporal_ns`;
`reconcile_temporal_metadata` and `profile_frame`; `to_pandas_masking_frame` and the five
call sites; the two sentries; tests.

| File | Now | Budget |
|---|---|---|
| `src/decoy_engine/_arrow_types.py` | 299 | about +70 (bounds, zone check) |
| `src/decoy_engine/internal/pandas_compat.py` | 218 | about +60 |
| `src/decoy_engine/profile/arrow/_frame.py` | 59 | about +20 |
| `src/decoy_engine/execution/_fk_keys.py` | 511 | about +40 |
| `_pandas_adapter.py`, `_sequential.py` | 674, 680 | 0 net (call renamed; both are near the 700 cap) |
| `_unified_slice_admission.py`, `_pipeline_full_frame.py`, `_chunked_carry.py` | 551, 337, 311 | about +1 each |
| `tests/sentry/defects/test_date_shift_one_arithmetic.py`, `test_lossless_int_columns.py` | | about +15, +25 |
| extended test files | 165, 98, 94 | each stays under 450 |

New names: `pandas_coerces_temporal_ns`, `reconcile_temporal_metadata`,
`to_pandas_masking_frame`. Changed signature:
`temporal_bounds(kind, *, coerce_ns)`. Plus one CHANGELOG line (P6b).

Test depth: T0 the touched files' tests per edit; T1 impact selection at the slice head
(`tests/unit/profile`, `tests/unit/execution`, `tests/unit/test_arrow_types.py`,
`tests/native` date_shift, rev9, c8_i and unified-admission parity files, `tests/sentry`). No escalation trigger: no shared
fixture, schema, lock, auth, serialization or version pin changes. Builder evidence adds P3
under pandas 1.5.3.

## Pre-mortem

- pyarrow still builds an extension dtype for some temporal entry with `numpy_type`
  `"object"`: P1, P1b and P6 catch it.
- `coerce_temporal_nanoseconds` behaves differently under pandas 1.5.3: the P3 run there
  catches it.
- A pandas masking run that succeeds today with Arrow-backed metadata is now refused: only
  when the same source without metadata is refused today (P5 differential); native callers
  are untouched (P5d).
- The trial conversion doubles conversion cost: it runs only for temporal columns with an
  Arrow-backed entry, one column at a time.
- The attribution retry does not reproduce the helper's error: it calls the same helper on
  `select([name])`, which keeps the schema metadata, and the text depends on the name only.
  P5 and P5b catch a mismatch.
- Unified admission and the oracle diverge: both call the helper; P5c and the existing parity
  gate catch it.
- Child-process tests are slow: two small subprocesses, each under two seconds.

## Deferred (V2-LOG)

- Temporal values nested in lists or structs still null the whole column.
- Exact per-zone bounds (zoneinfo lookups) instead of the ns intersection for named zones.
- `__context__` on the coded pandas-route error, as in round 3.
- An Arrow-backed `timestamp[ns]` sentinel on a masking route keeps the existing ArrowDtype
  representation; only its refusal behaviour is pinned (P5c).
- A pandas masking route on a source with no temporal metadata can surface a raw Arrow error
  that quotes the integer, for a column the chunked attribution does not cover (Codex plan R1
  finding 3). It predates this PR and is not the metadata class; it needs its own row.
- `verification/canary/_canonical.py:42` holds a second copy of `DATE32_MIN_DAY` and
  `DATE32_MAX_DAY`; make it import them.
- A profile of a named-zone column reads a 9999 "open end" value as null (named zones take the
  ns bound).
