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
| V1 F1 | `timestamp[s]` with stale `timestamp[ns][pyarrow]` metadata: the final `to_pandas` raises `ArrowInvalid` that quotes the source integer | the bound is on the physical type, but the conversion target comes from the metadata |
| V1 F2 | `America/New_York` near year 1 segfaults on iteration; zoned ns near int64 max fails; UTC edge values are nulled | the one-day zone margin is the wrong model: pandas does zone work in int64 nanoseconds |
| V1 F3 | pandas 1.5.3: one year-2500 `timestamp[s]` cell nulls the whole column | pandas 1.x converts every timestamp to ns; the bound assumes the physical unit |
| V1 F4 | `timestamp[ns]` `INT64_MIN` counts as null or not, depending on metadata | the bound admits the NaT sentinel; only the numpy conversion reads it as NaT |
| V1 F5 | full-frame and sequential masking with Arrow-backed `date32` year 10000 raise uncoded `OverflowError` | the refusal runs only after a conversion fails, and Arrow-backed conversion does not fail |

The DESIGN finding (the arithmetic sentry misses `from datetime import timedelta as td`) is
fixed here too, as P8.

Review history. Dennis R1 returned GO-WITH-FIXES. Codex plan reviews R1, R2 and R3 returned NO-GO.
codex-fix then added the native predicate projection and value-free retries (rules 5 and 6).
The owner dropped its exact time membership rule. That edge is now a refusal (P5t).
R1 (V1) added the shifted storage bound, protected exact native work and removed masking bounds.
R2 (V1) required reconciliation of valid hints and stale zones, plus value-free conversion errors.
R3 (V1) found that native predicates still exposed the null row's sibling and lost carry attribution.
P5w now compares emitted rows. P5r compares the public error with both route causes.
R3 (V2-LOG) corrected the profile label, sentinel mutation, last aligned time and wall-time evidence.

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

Read-only route probes on `08ee112c2` confirmed both reproductions. On the timestamp
fixture, native and forced oracle each left the null sibling visible with the hint.
Both redacted it without the hint. On `t in [0]`, both hinted legs selected only the
last row and returned the original time column exactly. Without the hint, both refused
the unaligned input. On the C8-i comparison, both legs emitted chunk 0. Both then
reported chunk 1 with a tick-bearing `ArrowInvalid` cause. The public oracle raised
that same class with the tick in its own text.

Custom code left: the bound table (pyarrow has no per-cell "would this cast succeed" kernel)
and the metadata reconciliation (pyarrow has no option to drop only the dtype hints).

## Guarantee

Profile: every temporal column that enters a profile frame is judged on its physical integer
by one table, whatever the pandas metadata says and on every supported pandas major. An
out-of-bound cell reads as null and its neighbours keep their values.

Full frame, sequential, chunked oracle and unified admission use physical temporal types.
Native `when:` uses the same representation for its referenced fields. Source dtype hints cannot
select a row, change a conversion refusal or put a rejected value in error or log text.
Native output still takes a passthrough column from Arrow. The predicate supplies only a mask.

Non-goals include nested temporal bounds and exact transition-zone limits.
Known issue (owner decision, rule 6): a `when:` that reads an Arrow-backed `time64[ns]` column
holding a sub-microsecond tick now gets the coded refusal on both legs. Today the hint lets
`t in [0]` succeed. The unhinted source is already refused, so the hint no longer changes the
outcome. Exact time membership is deferred to a later release.
The native Faker null mask, group-key kernel, transforms and mixed FK bridge retain their
existing conversions.

## Rule

1. **The physical Arrow type decides; metadata never does.** Before conversion, the `pandas`
   metadata entry of every temporal field (date, time, timestamp, duration; data or index
   column) is reconciled to the physical field. The `pandas_type` and `metadata` members come
   from the existing registry, `_pandas_meta` (`pairs_for(field.type)[0]` and
   `column_metadata(field.type)`, `src/decoy_engine/_pandas_meta/_descriptors.py:89,107`), so
   no temporal fact is decided twice. The function adds one override, `numpy_type`
   `"object"`, which makes pyarrow use the physical default. All other entries and
   `index_columns` / `column_indexes` stay as they are. One function,
   `reconcile_temporal_metadata(table) -> pa.Table`, in `internal/pandas_compat.py`, used by
   the profile and by pandas masking alike. It rewrites every temporal entry, including the
   `metadata.timezone` member, so neither a stale nor a correct Arrow-backed hint survives. It
   never raises: unparseable metadata returns the table unchanged; an entry with no matching
   field, or a duplicated field name, is skipped.
2. **One bounds table.** `temporal_bounds(kind, *, coerce_ns)` in `decoy_engine/_arrow_types.py`
   returns `(low, high, step)` on the physical integer. The target unit is `ns` when
   `coerce_ns`, else the physical unit. `coerce_ns` comes from one helper,
   `pandas_coerces_temporal_ns()` in `internal/pandas_compat.py` (`True` when the pandas major
   is below 2). Every profile conversion that relies on the bound passes the same value to
   `to_pandas(coerce_temporal_nanoseconds=...)`, so the bound and the conversion agree.
3. **The NaT sentinel is missing everywhere.** For timestamp and duration, `INT64_MIN` is never
   inside the bound, on any unit, with or without metadata. This matches `arrow_missing_mask`
   (`src/decoy_engine/internal/pandas_compat.py:55`).
4. **Per cell, never whole column.** The profile read nulls each out-of-bound cell on Arrow.
   The whole-column fallback in `profile_frame` stays only for a type with no bound (a nested
   column). If a bounded column still fails `to_pandas`, that is a bound bug: `profile_frame`
   raises `ValueError` naming the column only, after leaving the conversion handler.
5. **Use one masking conversion.** Put `to_pandas_masking_frame` beside `to_pandas_fk_safe`
   in `execution/_fk_keys.py`. Reconcile every temporal entry with rule 1. Preserve index
   metadata, row positions and the existing protected-integer set. Do not bound masking input.
   Use the helper at adapter ingestion (line 205), sequential ingestion (415), unified
   admission (347), full-frame attribution (81) and carry attribution (143).
   Use it also in `native/_when_mask.py:58` on `raw_chunk.select(present)`.
   Keep `_eval_predicate` and its handling of nullable boolean masks. At its existing
   fallback warning (`_when_gate.py:404`), log only the fixed event, strategy and column.
   Omit the library warning payload.
6. **No exact time path (owner decision, 2026-11-25).** Integer-list time membership gets no
   special column access. Rev9's `t != 1` and `t in [0]` both take ordinary ingestion.
   A hinted Arrow-backed `time64[ns]` column with an unaligned tick that a `when:` reads is
   refused on both legs, as the unhinted source is refused today. See Non-goals and P5t.

6. **Preserve the public failure class and replace its text once.** At the shared conversion
   boundary, diagnose a failed conversion with single-column conversions in source order.
   Use the same prepared input and protected set. A single-column failure needs no retry.
   Match the original class and text internally before attributing a multi-column failure.
   Never log either exception. Make a fresh exception of the matching conversion class with
   just the column name in a fixed message. For the unaligned time this is `pa.ArrowInvalid`.
   For an unlocated conversion failure, use a fixed value-free conversion message of the same
   class. Leave already-coded engine errors alone. Raise the new exception outside both
   handlers. Construct the known Arrow and pandas conversion types with fixed text. Use a
   plain value-free ValueError for an unknown subtype that needs special constructor args.
   Never pass through a temporal conversion message. Do not attach the raw exception or
   copy its args, notes or traceback. Keep this handling inside frame conversion so handler
   and custom adapter exceptions still retain their identity.

   Use this representation on first conversion, public oracle and attribution retry.
   Keep `_same_failure` and the equivalent full-frame check exact. The carry code still
   chains the safe exception via `_raise_if_read`. A masked column outside the read set
   yields the safe public error directly. Unified admission declines on conversion failure.
   The full-frame and sequential error messages still name the table and column.

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
fixed; every other string is a zone with transitions. Match signed offsets with a full match. `Etc/GMT+5` therefore takes the narrower
bound, so its pre-1677 values read as null in a profile. That is safe and is recorded.

## Choke points

- Profile: `profile_frame` (`src/decoy_engine/profile/arrow/_frame.py:19`), already the one
  Arrow-to-pandas conversion for profile reads (round 4). It now calls
  `reconcile_temporal_metadata`, then the bounds, then one `to_pandas`.
- The five pandas sites and native predicate projection enter the same conversion boundary.
  The caller sentry pins the six qualified callers and the forwarding helper. The four
  exact-vector consumers in P5e retain their existing calls. M8 and M16 exercise this split.
- The existing predicate evaluator decides membership on the converted frame. P5t checks
  the unaligned time refusal. P5r checks the ordinary comparison. Neither the predicate nor
  a retry adds a reason code.
- `native/_chunked_entry.py:330` passes the masks and the original Arrow chunk separately
  into the kernel. `_chunked_carry.py:139-164` matches errors and owns the chunk refusal.

## Acceptance tests

| Id | Case | File |
|---|---|---|
| P1 | Use physical `timestamp[s]` values at epoch, year 2500 and one second after epoch. Set a stale `timestamp[ns][pyarrow]` hint. On pandas 2, the resident frame keeps all three and has dtype `datetime64[s]`. The Parquet reader frame keeps all three at `datetime64[ms]`. Run `scan_sources(strategy="full")` and `profile_source(residency="full", sample_rows=None)`. Assert zero nulls and three distinct values. The latter reports the canonical `datetime64[ns]` label (`profile/_walk.py:226`). Check errors, warnings and logs for the rejected-cast tick strings. | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P1b | Same cells, stale `datetimetz` metadata naming `America/New_York` over the naive field: same result, and the profiled column is naive (the physical type, not the metadata zone) | same |
| P1c | A table from `pa.Table.from_pandas` with a named non-range index plus P1's stale entry: `profile_frame` keeps the index values and name; `__index_level_0__` is not a column | same |
| P2a | Full Parquet scan, `timestamp[s, America/New_York]` at year 1 day 2 and epoch, in a child process (`sys.executable`): exit code 0, the year-1 cell null, epoch kept | same |
| P2b | Full scan, `timestamp[ns, America/New_York]` at `INT64_MAX - 3_600 * 10**9`: returns, that cell null | same |
| P2c | `profile_frame`, `timestamp[s, UTC]` at noon 0001-01-01 and noon 9999-12-31: both kept | same |
| P2d | `timestamp[s, +05:30]`: the instant whose wall time is 9999-12-31T23:59:59 is kept, one second later is null; the mirror at year 1 | same |
| P2e | `timestamp[s, Asia/Kolkata]` at year 1 day 10, in a child process: exit 0, null, no `KeyError` | same |
| P2f | Rendered profile (top values, `profiler.py:99`) of `timestamp[ns, +05:30]` at `INT64_MAX` and `INT64_MAX - 5.5 h`: the first is null, the second is kept and renders as year 2262. Mirror for `timestamp[ns, -05:00]` at `NS_LOW` (null) and `NS_LOW + 5 h` (kept, year 1677). No `OutOfBoundsDatetime`, and the rejected cells' integers and their rendered timestamps appear in no output | same |
| P3 | `timestamp[s]` `[0, 2500-01-01, 1]` with `pandas_coerces_temporal_ns` patched to `True`: only the middle cell is null and the dtype is `datetime64[ns]`. The builder also runs `profile_frame` alone (the package does not import on pandas 1.5.3 for an unrelated reason) under pandas 1.5.3 in a throwaway venv and records the result (evidence, not CI) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P4 | Full Parquet scan of `timestamp[ns]` `[INT64_MIN, 0, INT64_MIN, 1]`: null count 2 with default metadata and 2 with `timestamp[ns][pyarrow]` metadata; the same for `duration[ns]` | same |
| P5 | Differential, pandas masking forced, on full frame, sequential and the chunked oracle (passthrough column plus the masked `name` sibling, as in `test_full_frame_value_unrepresentable.py`). For each fixture, run once with the given metadata and once with the `pandas` metadata removed; assert the same outcome: both succeed with equal output values, or both raise with the same code (full frame, sequential: `full_frame_value_unrepresentable`, table and column named). Fixtures: `date32` `[0, 2932897, 1]` with `date32[day][pyarrow]` (F5: red today, the metadata run raises an uncoded `OverflowError`); `time64[ns]` `[1, 2]` with `time64[ns][pyarrow]`; `timestamp[s]` year 2500 with stale `timestamp[ns][pyarrow]`; `timestamp[s]` `10**16` with stale `timestamp[ms][pyarrow]`; `timestamp[ms]` `12345` with stale `timestamp[s][pyarrow]`; physical `timestamp[us, UTC]` at midnight with a stale `timezone: America/New_York` member; in-range `duration[us]`, `timestamp[us, UTC]` and `date32` with their pyarrow-written Arrow-backed entries (both succeed). Check fixed error text and captured logs using distinctive rejected ticks | `tests/unit/execution/test_full_frame_value_unrepresentable.py` |
| P5z | Use UTC midnight and noon with stale New York metadata. Observe the actual frame passed to the gate. In this test only, project `t.dt.hour` from that frame into a temporary predicate operand and delegate to the real evaluator with `wall_hour == 0`. Keep the configured read on `t` so carry conversion runs. Assert that only the midnight sibling is redacted, with and without the stale member. An unreconciled frame gives hours 19 and 7 in winter. This tests wall time without extending the public grammar. The carried timestamp alone cannot detect the fault (`pipeline/_source_types.py:160`). | same |
| P5w | Use nullable `timestamp[us]` values at null, 2050 and 2200. Redact `name` with `not (t < '2100-01-01')`. Run full frame and sequential. Run the same chunks through `run_native` and `run_oracle_leg` in native test support. Assert native admission on the first and forced reroute on the second. Repeat with only the temporal hint removed. Compare emitted values, field types and validity across the four chunked runs. On every route the null and 2200 rows contain the redaction, and the 2050 row retains its original name. | same |
| P5x | Chunked oracle, a masked (not passthrough) `time64[ns]` column with tick `123456789` and `time64[ns][pyarrow]`: the run raises; no `str(exc)` and no rendered chain holds `123456789`; the same with the metadata removed | same |
| P5b | Chunked oracle, the far `date32` column read by a `when:` with `date32[day][pyarrow]`: the same `chunked_passthrough_value_unrepresentable` code, `'chunk '` in the message, `__cause__` set, as the same run without metadata | same |
| P5r | Use the C8-i good chunk then its bad chunk, `t != 1`, with and without the `time64[ns][pyarrow]` hint. The public oracle raises exactly `pa.ArrowInvalid` with the fixed column-only text. Its cause and context are empty. Native and forced oracle each emit the same first chunk only. Both then raise `chunked_passthrough_value_unrepresentable` naming the table, `'t'` and `chunk 1`. Both causes equal the public error in exact class and text. Assert that the safe cause has no raw cause or context. Check outer text, cause, formatted chain and captured logs for the rejected tick. Seed the fallback warning with a distinctive literal and check the captured log too. Run unchanged rev9 and C8-i pins too. | same |
| P5c | Unified admission flag on and off, P5's `date32` fixture with Arrow-backed metadata: both give `full_frame_value_unrepresentable` (admission declines) | same |
| P5d | Native compatibility guard: the chunked positional Faker job on Arrow-backed `date32` year 10000 succeeds; the zoned rev9 shapes (`tests/native/_rev9_support.py:64`) stay `"exact"`; `tests/native/test_c8_i_when_mask.py` and `test_chunked_entry_rev9_shapes.py` retain their assertions. Update the shapes spy binding as described in Slices. | same, and existing files |
| P5t | Known-issue refusal (owner decision, rule 6): `t in [0]` on Arrow-backed `time64[ns]` ticks `[1, null, 0]` with `time64[ns][pyarrow]` metadata. Native and forced oracle both raise `chunked_passthrough_value_unrepresentable` naming the table, `'t'` and `'chunk '`, with `__cause__` set; full frame raises `full_frame_value_unrepresentable`. The same run without metadata gives the same codes. No `str(exc)`, rendered chain or captured log holds the tick text `00:00:00.000000001`. Aligned ticks (`[1000, null, 0]`) on both legs succeed and redact only the last sibling. | `tests/unit/execution/test_full_frame_value_unrepresentable.py` |
| P5e | Pin the five pandas sites and `native.when_mask` to the masking helper. Pin its FK-safe delegate and the four direct users (Faker null mask, group-key, transforms, mixed FK). Extend the exact caller-set and alias tests for the helper. | `tests/sentry/defects/test_lossless_int_columns.py` |
| P6 | No-regression, new surface (guard): for tables from `pa.Table.from_pandas` with numpy dtypes (dates, naive and zoned in-range timestamps, timedelta, DatetimeIndex, zoned DatetimeIndex, a MultiIndex with a datetime level), `profile_frame(t)` equals `t.to_pandas()` (`assert_frame_equal`, dtypes included) | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| P6b | Disclosed change, new surface: correct Arrow-backed metadata (`timestamp[us][pyarrow]`, `date32[day][pyarrow]`) now profiles as the physical default (`datetime64[us]`, `object`), before profile label canonicalization. `reconcile_temporal_metadata` returns the table unchanged for unparseable `pandas` metadata, skips entries with no matching field (after `select`) and duplicate field names, and never raises | same |
| P7 | Bounds edges for every table row and unit, `coerce_ns` both ways, including `timestamp[ns, -05:00]`, `timestamp[ns, +05:30]` and `timestamp[s, +05:30]` (the fixed-offset edges use the three-term formula): the expected edges are computed in the test from independent constants (`datetime(1, 1, 1)`, `datetime(9999, 12, 31, 23, 59, 59, 999999)`, the offset, `pd.Timestamp.min.value`, `pd.Timestamp.max.value`), never from `temporal_bounds`; assert the returned low bound itself excludes `INT64_MIN` for every timestamp and duration unit. Check both inclusive edges and their representable neighbours. For `time64[ns]`, accept 86,399,999,999,000 (the last aligned tick), reject its adjacent ticks and the next midnight; no bound lies outside int64 | `tests/unit/test_arrow_types.py` |
| P8 | Arithmetic sentry finds `from datetime import timedelta as td; td(days=1)` (red today); `import datetime as dt; dt.timedelta(days=1)` is a guard (green today) | `tests/sentry/defects/test_date_shift_one_arithmetic.py` |
| R1-R6, A1-A7, D1-D3 | Round 3 and round 4 cases stay green; R5's zoned case uses `America/New_York` and its expectation still holds | existing files |

A segfault kills the test runner, so P2a and P2e run the scan in a child process and assert on
its exit code and JSON output. Record fail-before evidence per assertion on the implementation
base. Distinguish a newly failing reproduction from a passing compatibility guard. P5d is a guard. P5t is
a reproduction. P4 verifies observed nulls after NumPy conversion. Only P7 inspects the sentinel bound directly.

## Mutations

| Id | Mutation | Red |
|---|---|---|
| M1 | skip `reconcile_temporal_metadata` in `profile_frame` | P1, P1b |
| M2 | reconcile by dropping the whole `pandas` metadata | P1c, P6 |
| M3 | classify UTC as a zone with transitions | P2c |
| M4 | classify every zone as fixed (no ns intersection) | P2a, P2e |
| M5 | drop the one-day margin in the ns intersection | P2b |
| M6 | ignore `coerce_ns` in the bound | P3 |
| M7 | admit `INT64_MIN` | P7 |
| M8 | one masking site back to `to_pandas_fk_safe` | P5e (exact caller set) |
| M9 | restore the whole-column fallback for bounded types; red is shown with a patched bound that admits one bad cell, so the conversion fails after bounding | P3 variant: expects the column-only `ValueError` of rule 4, gets a nulled column |
| M10 | the arithmetic sentry matches the bare call name only | P8 |
| M11 | the masking helper skips reconciliation | P5 (date32), P5z, P5w, P5b, P5c |
| M12 | the masking helper reconciles only entries absent from `pairs_for` | P5w, P5z |
| M13 | the fixed-offset bound drops the `S - off` term | P2f, P7 |
| M14 | apply scalar temporal limits in the raw FK-safe converter | P5d (native Faker guard) |
| M15 | re-raise raw Arrow conversion text | P5x, P5r |
| M16 | native predicate projection bypasses the masking helper | P5w, P5e, P5r |
| M17 | normalize only the retry, or collapse the first failure to plain ValueError | P5r, existing rev9 class and C8-i parity pins |
| M18 | give hinted `time64[ns]` columns `pd.ArrowDtype` in the masking helper | P5t, P5r |

Rerun M1 through M18 on the final implementation head. Record the head and failing assertion.

## Defect classes (plan contract catalog)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | metadata reconciled and the cell nulled on Arrow before conversion; both initial conversions and retries raise fresh value-free errors after leaving the handler | P1, P1b, P2f, P5x, P5r | M1, M15, M17 |
| 2 | Cleanup missing on an exit path | N/A: no resource is opened; every new function is pure over an Arrow table | none needed | N/A |
| 3 | State machine and concurrency | N/A: no shared state; `coerce_ns` is read per call | none needed | N/A |
| 4 | Route parity and silent fallback | every profile route calls `profile_frame`; every pandas masking site calls `to_pandas_masking_frame` (sentry-pinned); native predicate input and unified admission use it too | P5c, P5d, P5e, P5t, P5w | M8, M16, M18 |
| 5 | Referential integrity | N/A: no key path changes | none needed | N/A |
| 6 | Untrusted producer | pandas metadata from a source file never decides a profile bound or a masking outcome | P1, P1b, P4, P5 | M1, no reconcile |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is opened | none needed | N/A |
| 8 | Weak tests and overclaimed evidence | record baseline results separately for regressions and guards. Compare emitted siblings, public errors and direct bounds | builder report | M1 to M18 |
| 9 | Behaviour-preserving refactor drift | P6 pins that correct metadata converts exactly as before | P6 equality test | M2, metadata dropped |
| 10 | Frozen contract drift | public class and coded causes match on both legs. Exact native outputs and Faker remain covered | P5d, P5r, P5t, P5w | M14 to M18 |

The recurring-defect checks apply to the final implementation. Use a full match for offset
tokens and test a trailing newline. Treat malformed metadata members as untrusted input.
Keep raw exceptions outside both chains. Sentries resolve aliases and check forwarding
callers. Run the import contracts and keep CI failures visible. There is no new wire model,
version, trust boundary or cap. Record the unchanged pins and final-head mutations.

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
- native predicate projection uses the masking helper (`native/_when_mask.py:58`).
- direct users of `to_pandas_fk_safe` include the Faker null mask, group-key
  kernel, transforms table, mixed FK bridge (P5d)

### Exit paths

- profile normal return: reconciled, bounded, converted once
- profile fallback: a nested column fails and is nulled whole
- profile raise: a bounded column fails; `ValueError` naming the column, `from None`
- masking refusal: a safe public conversion exception, used directly, chained by
  carry, attributed by the full-frame or sequential route, or declined by admission
- masking pass: every temporal entry reconciled, then conversion as for a source with no
  temporal metadata

### FK shapes

N/A: no FK logic changes; a temporal FK key goes through the same helper as any column.

### Output surfaces

- `ColumnProfile.to_dict`, `scan_set_to_dict(detail=True)`, `profile_document` (P1, P4)
- top values (`src/decoy_engine/profiling/profiler.py:99`) (P2a)
- Public exception text, coded error, cause, rendered chain and captured logs (P5x, P5r)

## Reuse inventory

Extend `temporal_bounds` and `_bounded`. Reuse `DATE32_MIN_DAY`, `DATE32_MAX_DAY`,
the sentinel rule in `arrow_missing_mask`, and pyarrow's `coerce_temporal_nanoseconds`.
Read descriptors through `_pandas_meta.pairs_for` and `column_metadata`.

Share the conversion-error tuple now duplicated at `execution/_chunked_carry.py:46`
and `execution/_pipeline_full_frame.py:49` in the execution helper. Keep the extra
profile-only TypeError at its caller. Extend the FK-safe caller sentry. For P8, use
`import_bindings` and `canonical` from `tests/sentry/_retry_scan.py:53`.

## Design notes

Keep the bounds in `_arrow_types.py` and dtype reconciliation in `internal/pandas_compat.py`.
Reuse `_pandas_meta` through its package exports. Extend the access declarations rather than
adding a second parser or consumer list. Keep one frame conversion and one safe error builder.
Both attributions already compare exact class and text (`_pipeline_full_frame.py:83`,
`_chunked_carry.py:164`). Preserve that contract. Native kernels still receive Arrow arrays.

## Placement

| New file | Directory | CODEMAP row | Beside |
|---|---|---|---|
| none | | | |

All new tests extend existing files: `tests/unit/profile/test_profile_frame_unrepresentable.py`
(profile cases, about +200), `tests/unit/execution/test_full_frame_value_unrepresentable.py`
(masking cases, about +180), `tests/unit/test_arrow_types.py`, and the two sentries.
Existing instrumentation also follows the ingestion rename (see Slices).

## Frozen contracts

Keep both released reason codes and every exception-class and cause pin. No pin change.
The public oracle still raises `ArrowInvalid` on rev9's unaligned time comparison.
Both coded causes carry the same safe text. A hinted unaligned time read by any `when:` now gives the same refusal as the unhinted
source. This keeps the released C8-i refusal and adds the P5t known issue.

Document normalized temporal frame dtypes, metadata-independent predicate selection,
value-free failures and the P5t known issue in one CHANGELOG entry. The profile report
continues to use its canonical dtype labels. Untouched output fields come from the source.

## Slices

One commit on #790, in this order: bounds table and `pandas_coerces_temporal_ns`;
`reconcile_temporal_metadata` and `profile_frame`; `to_pandas_masking_frame` and the five
pandas sites plus the native predicate projection. Finish with sentries and acceptance tests.

| File | Now | Budget |
|---|---|---|
| `src/decoy_engine/_arrow_types.py` | 299 | about +70 (bounds, zone check) |
| `src/decoy_engine/internal/pandas_compat.py` | 218 | about +60 |
| `src/decoy_engine/profile/arrow/_frame.py` | 59 | about +20 |
| `src/decoy_engine/execution/_fk_keys.py` | 511 | about +65 (conversion and safe failure) |
| `_pandas_adapter.py`, `_sequential.py` | 674, 680 | adapter at most +6. Sequential 0 net under its 680-line sentry pin. Keep conversion logic in the helper |
| `_when_gate.py` | 565 | remove the warning payload |
| `native/_when_mask.py` | 101 | about +8 for projection inputs |
| `_unified_slice_admission.py`, `_pipeline_full_frame.py`, `_chunked_carry.py` | 551, 337, 311 | about +8 each |
| `tests/sentry/defects/test_date_shift_one_arithmetic.py`, `test_lossless_int_columns.py` | | about +15, +25 |
| extended test files | 165, 98, 94 | each stays under 450 |

Retarget the adapter conversion spies in `test_chunked_entry_rev9_shapes.py:178`,
`test_chunked_entry_rev9_read.py:399` and `test_gated_hash_on_integer.py:73`. Forward the
conversion inputs and retain their assertions. Replace the renamed call in
`test_column_access_surfaces.py:277`. Update the checked caller identities in
`tests/sentry/baselines/lossless-int-columns.json` with the sentry. Record these inventory
edits separately from behavior pins. Keep the same coverage and module size ceilings.

New names: `pandas_coerces_temporal_ns`, `reconcile_temporal_metadata`,
`to_pandas_masking_frame`. Changed signature:
`temporal_bounds(kind, *, coerce_ns)`. Plus one CHANGELOG line (P6b).

Test depth: T0 the touched files' tests per edit; T1 impact selection at the slice head
(`tests/unit/profile`, `tests/unit/execution`, `tests/unit/test_arrow_types.py`,
`tests/native` date_shift, rev9, c8_i and unified-admission parity files, `tests/sentry`). No escalation trigger: no shared
fixture, schema, lock, auth, serialization or version pin changes. Builder evidence adds P3
under pandas 1.5.3. Include the touched spies, caller-inventory tests, import contracts and
`tests/security/test_fk_key_value_free_errors.py` in T1.

## Pre-mortem

- pyarrow still builds an extension dtype for some temporal entry with `numpy_type`
  `"object"`: P1, P1b and P6b catch it.
- `coerce_temporal_nanoseconds` behaves differently under pandas 1.5.3: the P3 run there
  catches it.
- The predicate sees an Arrow timestamp on one leg. P5w checks admission and the actual
  siblings, including the null row. P5z observes the physical wall hour before output assembly.
- A user relied on hinted sub-microsecond time membership. P5t pins the coded, value-free
  refusal on both legs; the CHANGELOG names it. P5r checks that an ordinary comparison still
  fails after one yielded chunk.
- One route changes the exception class or quotes a tick. P5r compares both causes with the
  public exception. P5x checks a masked column with no carry attribution.
- Multi-column diagnosis costs one conversion per candidate on a failed ingest. The success
  path performs no diagnostic retries.

- Unified admission and the oracle diverge: both call the helper; P5c and the existing parity
  gate catch it.
- Child-process tests are slow: two small subprocesses, each under two seconds.

## Deferred (V2-LOG)

- Temporal values nested in lists or structs still null the whole column.
- Exact per-zone bounds (zoneinfo lookups) instead of the ns intersection for named zones.
- A masked temporal column outside carry attribution has a public, value-free conversion error.
  A new reason code for that case belongs in a separate change.

- `verification/canary/_canonical.py:42` holds a second copy of `DATE32_MIN_DAY` and
  `DATE32_MAX_DAY`; make it import them.
- A profile of a named-zone column reads a 9999 "open end" value as null (named zones take the
  ns bound).
