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

Masking: a temporal value the pandas conversion target cannot hold is refused with the route's
existing coded error, also when the metadata names an extension dtype that would let the
conversion succeed silently. Values that convert and round-trip today keep doing so: the
masking check uses only the conversion-target part of the table, never the profile's display
rules (wall time, named zones).

No error, warning or statistic carries the value.

Non-goals: temporal values nested in lists or structs; exact per-zone bounds for zones with
transitions; any change for a masking column whose metadata names no extension dtype (its
conversion already fails by itself and is attributed today).

## Rule

1. **The physical Arrow type decides; metadata never does.** Before conversion, the `pandas`
   metadata entry of every temporal field (date, time, timestamp, duration; data or index
   column) is reconciled to the physical field: `pandas_type` from the physical type (`date`,
   `time`, `datetime`, `datetimetz` when the field has a zone, `timedelta`), `numpy_type`
   `"object"`, and `metadata` `{"timezone": field.type.tz}` for a zoned field, else `None`.
   All other entries and `index_columns` / `column_indexes` stay as they are. One function,
   `reconcile_temporal_metadata(table) -> pa.Table`, in `internal/pandas_compat.py`.
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
5. **Masking: the probe raises, the route codes.** `to_pandas_fk_safe` runs a probe only on
   temporal fields whose `pandas` metadata names an extension dtype (`...[pyarrow]` or
   `datetime64[<unit>, <zone>]`). That is the one case where the conversion does not fail by
   itself. The probe reads the conversion target from that metadata entry
   (`extension_temporal_targets(table) -> dict[str, pa.DataType]` in
   `internal/pandas_compat.py`) and checks each cell against the **conversion bound** of the
   table below. On a hit it raises `ValueError(f"column {name!r} holds a temporal value pandas
   cannot represent")` `from None`. The text names the column only and is the same on every
   call, so the existing per-route attribution reproduces it on its one-column retry and
   assigns the released code: `_raise_if_source_value_unrepresentable` gives
   `full_frame_value_unrepresentable` with the table name (full frame, sequential),
   `CarryPlan.diagnose_adapter` gives `chunked_passthrough_value_unrepresentable` with the
   chunk index (chunked, native `when:`), and unified admission declines as it does for any
   conversion failure. A sentinel cell is missing, so it never refuses. The masking frame keeps
   its metadata: the refused cell never reaches pandas, and the dtype choice is the existing
   route behaviour.

### Bounds table (inclusive, physical unit P, target unit T)

`PY_LOW` and `PY_HIGH` are 0001-01-01T00:00 and the last tick of 9999-12-31, from
`DATE32_MIN_DAY` and `DATE32_MAX_DAY`. `NS_LOW = INT64_MIN + 1`, `NS_HIGH = INT64_MAX`.
Unit conversion is exact integer arithmetic: a lower bound rounds up, an upper bound down.
Every bound is clamped to `[NS_LOW, NS_HIGH]` before it reaches a compute kernel, because
`pc.less_equal` on an int64 array raises `TypeError` for a scalar outside int64.

The table has two layers. `conversion_bounds(physical, target)` is what the pandas
conversion target can hold; masking uses only this layer. `temporal_bounds(kind, *,
coerce_ns)` is the profile bound: the conversion layer for the default target, intersected
with the display rules.

| Arrow type | Conversion bound | Profile adds | Why |
|---|---|---|---|
| `date32`, `date64` | `PY_LOW` to `PY_HIGH` (days, or ms for date64) | nothing | `datetime.date`; an Arrow-backed date fails later on `.as_py()` |
| `time32`, `time64` | 0 to one day less one tick; step 1000 for `ns` | nothing | `datetime.time` holds microseconds |
| `timestamp` naive or `UTC` | when T is `ns`: `[NS_LOW, NS_HIGH]` in ns, in P; else every value but the sentinel | the `PY` range | the target unit must hold it; a profile cell must also be a `datetime` |
| `timestamp` fixed offset (`+HH:MM`, `-HH:MM`) | as naive | `[max(storage_low, PY_LOW - off), min(storage_high, PY_HIGH - off)]`, `storage_*` being the conversion bound | the stored instant fits the unit unshifted; only the wall time is shifted |
| `timestamp` any other zone | as naive | `[NS_LOW + 1 day, NS_HIGH - 1 day]` in ns, in P, intersected with the `PY` range | pandas converts zones through ns tables; the day keeps the wall time inside int64 |
| `duration` | when T is `ns`: `[NS_LOW, NS_HIGH]` in ns, in P; else every value but the sentinel | nothing | pandas 1.x coerces to ns |

For masking, T is the unit of the extension dtype the metadata names (`timestamp[ns][pyarrow]`
gives `ns`; `datetime64[ns, <zone>]` gives `ns`). For a profile, T is `ns` when `coerce_ns`,
else P.

Zone classification is a string check on `field.type.tz`: `UTC` and `+HH:MM` / `-HH:MM` are
fixed; every other string is a zone with transitions. `Etc/GMT+5` therefore takes the narrower
bound, so its pre-1677 values read as null in a profile. That is safe and is recorded.

## Choke points

- Profile: `profile_frame` (`src/decoy_engine/profile/arrow/_frame.py:19`), already the one
  Arrow-to-pandas conversion for profile reads (round 4). It now calls
  `reconcile_temporal_metadata`, then the bounds, then one `to_pandas`.
- Masking: `to_pandas_fk_safe` (`src/decoy_engine/execution/_fk_keys.py:430`). The existing
  sentry `tests/sentry/defects/test_lossless_int_columns.py` already pins every ingestion
  caller (full-frame adapter, sequential, unified admission, chunked diagnosis, native `when:`
  and Faker masks), so every pandas conversion on a masking route reaches the probe by
  construction. Guard: P5 on each route. Mutation M8 (remove the probe from
  `to_pandas_fk_safe`) turns P5 red on every route at once.
- Codes stay where they are today: the probe raises a plain `ValueError`, and the existing
  after-failure attribution (`_raise_if_source_value_unrepresentable`,
  `CarryPlan.diagnose_adapter`) turns it into the route's released code. No new code path for
  this failure class.

## Acceptance tests (each fails on `b6c7785d5` unless marked new surface)

| Id | Case | File |
|---|---|---|
| P1 | Local Parquet, `timestamp[s]` cells `[0, 10**12, 1]` with stale `timestamp[ns][pyarrow]` metadata: `scan_sources(strategy="full")` and `profile_source` return; the middle cell is null; no output, warning or exception text holds `1000000000000` | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P1b | Same cells, stale `datetimetz` metadata naming `America/New_York` over the naive field: same result | same |
| P1c | A table from `pa.Table.from_pandas` with a named non-range index plus P1's stale entry: `profile_frame` keeps the index values and name; `__index_level_0__` is not a column | same |
| P2a | Full Parquet scan, `timestamp[s, America/New_York]` at year 1 day 2 and epoch, in a child process (`sys.executable`): exit code 0, the year-1 cell null, epoch kept | `tests/unit/profile/test_profile_frame_zones.py` (new) |
| P2b | Full scan, `timestamp[ns, America/New_York]` at `INT64_MAX - 3_600 * 10**9`: returns, that cell null | same |
| P2c | `profile_frame`, `timestamp[s, UTC]` at noon 0001-01-01 and noon 9999-12-31: both kept | same |
| P2d | `timestamp[s, +05:30]`: the instant whose wall time is 9999-12-31T23:59:59 is kept, one second later is null; the mirror at year 1 | same |
| P2e | `timestamp[s, Asia/Kolkata]` at year 1 day 10, in a child process: exit 0, null, no `KeyError` | same |
| P3 | `timestamp[s]` `[0, 2500-01-01, 1]` with `pandas_coerces_temporal_ns` patched to `True`: only the middle cell is null and the dtype is `datetime64[ns]`. The builder also runs `profile_frame` alone (the package does not import on pandas 1.5.3 for an unrelated reason) under pandas 1.5.3 in a throwaway venv and records the result (evidence, not CI) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P4 | Full Parquet scan of `timestamp[ns]` `[INT64_MIN, 0, INT64_MIN, 1]`: null count 2 with default metadata and 2 with `timestamp[ns][pyarrow]` metadata; the same for `duration[ns]` | same |
| P5 | Full-frame and sequential masking (pandas route forced), `date32` day counts `[0, 2932897, 1]` with `date32[day][pyarrow]` metadata: `ExecutionError` code `full_frame_value_unrepresentable`; the message names table and column; `str(exc)` and the rendered chain hold neither `2932897` nor `10000`. The same column without the metadata gives the same code (regression guard, green today) | `tests/unit/execution/test_temporal_unrepresentable_refusal.py` (new) |
| P5b | Chunked masking with that column read by a `when:`, with the Arrow-backed metadata: code `chunked_passthrough_value_unrepresentable`, `'chunk '` in the message, no value | same |
| P5c | Masking with a `timestamp[ns]` sentinel cell and Arrow-backed metadata: no refusal | same |
| P5d | `timestamp[s]` with stale `timestamp[ns][pyarrow]` metadata and a year-2500 cell: full frame gives `full_frame_value_unrepresentable`, chunked with a `when:` read gives `chunked_passthrough_value_unrepresentable`; neither text holds `16725225600` | same |
| P5e | The zoned rev9 shapes (`tests/native/_rev9_support.py:64`, `ts_*_far` and `ts_ns_*_edge` for `America/New_York`, `+05:30`, `Europe/London`) stay `"exact"` on every route; `tests/native/test_c8_i_when_mask.py` and `test_chunked_entry_rev9_shapes.py` stay green unchanged | existing files |
| P6 | No-regression, new surface: for tables from `pa.Table.from_pandas` with numpy dtypes (dates, naive and zoned in-range timestamps, timedelta, DatetimeIndex, zoned DatetimeIndex, a MultiIndex with a datetime level), `profile_frame(t)` equals `t.to_pandas()` (`assert_frame_equal`, dtypes included) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P6b | Disclosed change, new surface: correct Arrow-backed metadata (`timestamp[us][pyarrow]`, `date32[day][pyarrow]`) now profiles as the physical default (`datetime64[us]`, `object`), the same label the Arrow walk (`arrow_dtype_label`) gives. `reconcile_temporal_metadata` returns the table unchanged for unparseable `pandas` metadata, skips entries with no matching field (after `select`) and duplicate field names, and never raises | same |
| P7 | Bounds edges for every table row and unit, `coerce_ns` both ways, including `timestamp[ns, -05:00]`, `timestamp[ns, +05:30]` and `timestamp[s, +05:30]`: the expected edges are computed in the test from independent constants (`datetime(1, 1, 1)`, `datetime(9999, 12, 31, 23, 59, 59, 999999)`, the offset, `pd.Timestamp.min.value`, `pd.Timestamp.max.value`), never from `temporal_bounds`; low and high in, low - 1 and high + 1 out (skipped where high is `INT64_MAX`), `INT64_MIN` out; no bound lies outside int64 | `tests/unit/test_arrow_types.py` |
| P8 | Arithmetic sentry finds `from datetime import timedelta as td; td(days=1)` and `import datetime as dt; dt.timedelta(days=1)` | `tests/sentry/defects/test_date_shift_one_arithmetic.py` |
| R1-R6, A1-A7, D1-D3 | Round 3 and round 4 cases stay green; R5's zoned case uses `America/New_York` and its expectation still holds | existing files |

A segfault kills the test runner, so P2a and P2e run the scan in a child process and assert on
its exit code and its JSON output.

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
| M8 | remove the probe from `to_pandas_fk_safe` | P5, P5b, P5d |
| M11 | run the masking probe with the profile layer (wall time, named zones) | P5e |
| M12 | raise the probe's error as a coded `ExecutionError` | P5b (wrong code) |
| M13 | shift a fixed-offset bound without clamping | P7 (bound outside int64) |
| M9 | restore the whole-column fallback for bounded types | P3, R3, R4 |
| M10 | the arithmetic sentry matches the bare call name only | P8 |

## Defect classes (plan contract catalog)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | metadata reconciled and the cell nulled on Arrow before conversion; masking refuses with a column-only message `from None` | P1, P1b, P5 | M1, M8 |
| 2 | Cleanup missing on an exit path | N/A: no resource is opened; every new function is pure over an Arrow table | none needed | N/A |
| 3 | State machine and concurrency | N/A: no shared state; `coerce_ns` is read per call | none needed | N/A |
| 4 | Route parity and silent fallback | every profile route calls `profile_frame`; every pandas masking route ingests through `to_pandas_fk_safe` (sentry-pinned) | P4, P5, P5b | M8, probe removed |
| 5 | Referential integrity | N/A: no key path changes | none needed | N/A |
| 6 | Untrusted producer | pandas metadata from a source file is reconciled before a profile conversion and never used for a bound | P1, P1b, P4, P5 | M1, no reconcile |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is opened | none needed | N/A |
| 8 | Weak tests and overclaimed evidence | each P case records red on `b6c7785d5` except P6 (new surface); child-process isolation for the segfault cases | builder report | M1 to M13 |
| 9 | Behaviour-preserving refactor drift | P6 pins that correct metadata converts exactly as before | P6 equality test | M2, metadata dropped |
| 10 | Frozen contract drift | no released code changes route: the probe's error is attributed by each route's existing handler | P5b, P5e pins | M12 |

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
- masking, all through `to_pandas_fk_safe`: full frame (`_pandas_adapter.py:205`), sequential
  (`src/decoy_engine/execution/_sequential.py:415`), chunked (the adapter per chunk), unified
  admission, and on the native route the `when:` mask, Faker null mask, group-key kernel and
  transforms table. The probe fires only for extension-dtype metadata, so a native column
  with plain metadata is unchanged (P5e)

### Exit paths

- profile normal return: reconciled, bounded, converted once
- profile fallback: a nested column fails and is nulled whole
- profile raise: a bounded column fails; `ValueError` naming the column, `from None`
- masking refusal: the probe's `ValueError`, then the route's existing coded `ExecutionError`,
  no value
- masking pass: conversion as today

### FK shapes

N/A: no FK logic changes; a temporal FK key goes through the same probe as any column.

### Output surfaces

- `ColumnProfile.to_dict`, `scan_set_to_dict(detail=True)`, `profile_document` (P1, P4)
- top values (`src/decoy_engine/profiling/profiler.py:99`) (P2a)
- `ExecutionError` text and rendered chain (P5)

## Reuse inventory

`DATE32_MIN_DAY`, `DATE32_MAX_DAY`, `temporal_bounds`, `_bounded` (extended, not copied);
the `arrow_missing_mask` sentinel rule; `reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE`;
the `to_pandas_fk_safe` caller sentry; `import_bindings` and `canonical` from
`tests/sentry/_retry_scan.py:53` for P8; pyarrow `coerce_temporal_nanoseconds`.

## Design notes

No new module or abstraction. The bound stays one table in the bottom-tier
`_arrow_types.py`; the pandas-version fact and the metadata fact each live in one function in
`internal/pandas_compat.py`. The masking probe lives inside the existing conversion choke
point and raises into the existing attribution, so no caller and no code path changes.

## Placement

| New file | Directory | CODEMAP row | Beside |
|---|---|---|---|
| `test_profile_frame_zones.py` | `tests/unit/profile/` | profile readers, unit tests | `test_profile_frame_unrepresentable.py` |
| `test_temporal_unrepresentable_refusal.py` | `tests/unit/execution/` | execution, unit tests | existing execution route tests |

## Frozen contracts

None changed. `full_frame_value_unrepresentable` and `chunked_passthrough_value_unrepresentable`
keep their routes. The profile dtype label for a column with correct Arrow-backed temporal
metadata changes to the physical default (P6b); the PR adds a CHANGELOG line for it.

## Slices

One commit on #790, in this order: bounds table and `pandas_coerces_temporal_ns`;
`reconcile_temporal_metadata` and `profile_frame`; the probe in `to_pandas_fk_safe`; the
sentry resolver; tests.

| File | Now | Budget |
|---|---|---|
| `src/decoy_engine/_arrow_types.py` | 299 | about +80 (two bound layers, zone check) |
| `src/decoy_engine/internal/pandas_compat.py` | 218 | about +60 |
| `src/decoy_engine/profile/arrow/_frame.py` | 59 | about +20 |
| `src/decoy_engine/execution/_fk_keys.py` | 511 | about +20 |
| `tests/sentry/defects/test_date_shift_one_arithmetic.py` | small | about +15 |
| two new test files, two extended | | under 250 lines each |

New names: `pandas_coerces_temporal_ns`, `reconcile_temporal_metadata`,
`extension_temporal_targets`, `conversion_bounds`. Changed signature:
`temporal_bounds(kind, *, coerce_ns)`. Plus one CHANGELOG line (P6b).

Test depth: T0 the touched files' tests per edit; T1 impact selection at the slice head
(`tests/unit/profile`, `tests/unit/execution`, `tests/unit/test_arrow_types.py`,
`tests/native` date_shift files, `tests/sentry/defects`). No escalation trigger: no shared
fixture, schema, lock, auth, serialization or version pin changes. Builder evidence adds P3
under pandas 1.5.3.

## Pre-mortem

- pyarrow still builds an extension dtype for some temporal entry with `numpy_type`
  `"object"`: P1, P1b and P6 catch it.
- `coerce_temporal_nanoseconds` behaves differently under pandas 1.5.3: the P3 run there
  catches it.
- The probe fires on a value that converts today: it only runs for extension-dtype metadata,
  and only with the conversion layer; P5e pins the zoned rev9 shapes as exact.
- The one-column retry in the attribution does not reproduce the probe's error: `select`
  keeps the schema metadata, and the probe text depends only on the column name. P5 and P5b
  catch a mismatch.
- Child-process tests are slow: two small subprocesses, each under two seconds.

## Deferred (V2-LOG)

- Temporal values nested in lists or structs still null the whole column.
- Exact per-zone bounds (zoneinfo lookups) instead of the ns intersection for named zones.
- `__context__` on the coded pandas-route error, as in round 3.
- An Arrow-backed `timestamp[ns]` sentinel on a masking route keeps the existing ArrowDtype
  representation; only its refusal behaviour is pinned (P5c).
- `verification/canary/_canonical.py:42` holds a second copy of `DATE32_MIN_DAY` and
  `DATE32_MAX_DAY`; make it import them.
- A profile of a named-zone column reads a 9999 "open end" value as null (named zones take the
  ns bound).
