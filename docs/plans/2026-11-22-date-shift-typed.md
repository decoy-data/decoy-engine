Status: plan (revision 1, 2026-11-22)

# DATE-SHIFT-TYPED: `date_shift` on `date32` and zoned `timestamp` sources runs native, on the typed values

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: DATE-SHIFT-TYPED (group mask, 1.0), from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`) and the COLUMN-SHAPE-RULE row 19 follow-on (E1b merged in engine #751). Two slices, engine only. Depends on UF-DOMAIN S1 (`plan/uf-domain`) for the unified-slice output splice.

Anchors: a path with no prefix is under `src/decoy_engine/` in this repository (decoy-engine). Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `risk-and-exceptions.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (determinism of a masking strategy; output types and some output values change on a recorded contract). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): every masking strategy runs its fastest path by default; V1 must be fast and reproducible; output stays deterministic for a seed and namespace; a byte change that buys speed or robustness is allowed before V1 if it is marked in section 10 and in the changelog `Breaking:` line. This plan shifts the typed values in Arrow, with no format-and-parse step, and moves the oracle onto the same arithmetic so both routes agree by construction. Section 4 "Output surfaces" lists every byte change.

## 1. Frame

Since E1b the oracle shifts typed dates without text: `ColumnShape.DATE` adds a `timedelta` to each `datetime.date` in a Python loop (`execution/_strategies/_date_shift.py:379` `_shift_dates`), and `ColumnShape.TIMESTAMP_TZ` adds days to the local wall clock and re-attaches the zone (`_shift_zoned`, line 358). The shape comes from the compiled plan (`declared_casting/_boundary.py:185` `native_date_columns`). Naive timestamps and integer sources are refused at compile with `column_shape_mismatch`.

No native route takes a typed source:

- `date_shift_config_rejection` (`execution/native/_operator_config_rejections.py:146`) requires a `date_format` (line 170), which a typed column does not have.
- `string_source_type_rejection` (`execution/native/_real_type_admission.py:93`, through line 111) requires exact `string`.
- The registry domain for `date_shift` is `_STRING_ONLY` (`execution/_operator_registry.py:93`).
- The native kernel (`execution/native/_date_shift_ext.py:147` `native_date_shift`) parses and formats text through pandas.

So every typed `date_shift` column runs on pandas, in a per-row Python loop, at every size.

## 2. Established solutions

Search run: calendar-day arithmetic on zoned timestamps (PostgreSQL `timestamptz + interval '1 day'`, Java `ZonedDateTime.plusDays`, Arrow `assume_timezone` and `local_timestamp` docs); date-shift de-identification in established tools (the HIPAA Safe Harbor date-shift practice as used by Philter, Microsoft Presidio's date handling, and the MIMIC per-patient shift); Arrow temporal casts (`pyarrow.compute.cast`, `strftime`).

- Java `ZonedDateTime.plusDays` (Oracle and Android docs): add days to the local date-time, then resolve against the zone. In an overlap it keeps the previous offset if that offset is valid at the target. In a gap it moves the local time forward by the gap length. PostgreSQL does the same for `interval 'N days'`.
- Arrow: `pc.local_timestamp` gives the wall clock; `pc.assume_timezone(ambiguous=..., nonexistent=...)` re-attaches the zone, with `earliest`, `latest` or `raise` for each case. For a gap, `latest` returns the first valid instant after it, which is what pandas `nonexistent="shift_forward"` does today. Arrow has no "keep the source offset" option, so that rule is computed from the two candidates (section 7).
- De-identification practice (MIMIC, Philter): shift every date of one entity by one keyed offset, keep the type, keep the time of day. That is the engine's existing keyed-offset rule. None of these tools format a date to text to shift it.
- Arrow casts `date32` to `string` as ISO `YYYY-MM-DD` with a zero-padded 4-digit year, in C++, which is the same bytes as Python `date.isoformat()` for years 1 to 9999.

### Reuse inventory

- `derive_index_batch` through `_derive_offsets` (`execution/native/_date_shift_ext.py:97`): the compiled keyed offsets, reused as they are.
- `_canonicalize_source` (`generation/pool/_canonicalize.py:63`): the definition of the key bytes. The new vector form sits beside it and is tested against it.
- `shift_window`, `order_window` (`transforms/date_shift.py:100`, `:64`): the day bounds.
- `format_error_row_errors`, `FORMAT_ERROR_REASON` (`execution/native/_date_shift_ext.py:75`): the row-error form for a shifted value out of range.
- `RouteDeclineCode` and `coded(...)` (`execution/native/_route_decline_codes.py`): two new members.
- UF-DOMAIN S1 `read_columns` and the splice in `reconstruct_source_shaped_output`: the unified-slice output path for a typed target.

## 3. Guarantee and non-goals

After S1 (DATE) and S2 (TIMESTAMP_TZ):

1. A `date_shift` column whose plan shape is `DATE` over a resident `date32`, or `TIMESTAMP_TZ` over a resident `timestamp` with a zone (any unit), with a namespace, no `group_by`, no `when:`, and no `preserve_values`, runs native on the unified slice, the chunked route and the sequential route.
2. The day offset of each row equals the oracle's offset for that row: the key bytes are `_canonicalize_source(value)` computed over the Arrow array (ISO date for `DATE`; `astimezone(UTC).isoformat()` for `TIMESTAMP_TZ`). A typed date and the same date stored as ISO text in another table get the same shift in the same namespace, as today.
3. One arithmetic for both routes: `shift_typed_days(array, offsets) -> (shifted, failed)` in `transforms/date_shift.py`. The native route calls it on the resident array; the oracle calls it on `pa.Array.from_pandas(col)`. Oracle and native output values agree by construction.
4. The output column keeps the source Arrow type (`date32`; `timestamp` with the source unit and zone) on the native routes.
5. A shifted value outside the type's range (years 1 to 9999 for `date32`; the int64 range of the unit for `timestamp`) is a `format_error` row error and keeps its source value, on both routes.
6. Deterministic: same seed, namespace and input give the same bytes on every route and every run.

Non-goals, each kept on its existing path with a coded reason:

| Case | Reason code | Path |
|---|---|---|
| `group_by` set | `date_shift_group_by_not_native` (existing) | oracle |
| `when:` on the column | existing `when:` decline | oracle |
| `preserve_values` on a typed source | `date_shift_typed_preserve_not_native` (new) | oracle |
| plan shape `DATE` over `date64`, or any other resident type for a typed shape | `date_shift_typed_type_not_native` (new) | oracle |
| naive timestamp, integer source | `column_shape_mismatch` at compile (existing) | refused |
| out-of-core route | out-of-core does not take `date_shift` today | unchanged |

Text-source `date_shift` is unchanged.

## 4. Enumerations

### Exit paths

- Admitted typed column: shifted natively; rows out of range get `format_error` and keep the source (`execution/native/_date_shift_ext.py:75`).
- Null source cell: stays null, no error, no offset derived (as `_shift_dates` at `execution/_strategies/_date_shift.py:393`).
- Declined typed column: one of the coded reasons in section 3, oracle path.
- `date32` source value outside years 1 to 9999: native keeps it with a `format_error` row error; the pandas route fails converting the column (marked case B4).
- Key derivation error (missing namespace): existing config rejection, unchanged.

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | declined (`date_shift` domain is `string`) | admitted for `date32` (S1) and zoned `timestamp` (S2); output spliced from Arrow |
| Chunked native | `date_shift_requires_date_format` | admitted; `date_shift_pinned_columns` (`execution/native/_chunked_schema_rule.py:169`) pins the output to the source type, not `string`, for a typed column |
| Sequential native | requires a `date_format` | admitted through the same config rejection |
| Out-of-core | does not take `date_shift` | unchanged |
| Oracle (pandas) | Python loop and pandas tz arithmetic | calls `shift_typed_days`; same values as native |

### FK shapes

- A typed date column is never an FK key on the native routes (`date_shift` is not a key strategy). Unchanged.
- A typed `date_shift` column in a child or parent table runs on the sequential route under the same rule as a single table.

### Fields

- `strategy: date_shift`, `namespace` (required for native), `min_days` / `max_days` (resolved by `shift_window`).
- `date_format`: must be absent for a typed shape; if present, the existing compile rule decides (the oracle ignores it for a typed shape, `_required_format` at `execution/_strategies/_date_shift.py:108`). The config rejection skips the format check when the plan shape is typed.
- `group_by`, `preserve_values`, `when`: decline (section 3).
- Plan shape: `ColumnShape.DATE` or `ColumnShape.TIMESTAMP_TZ` from `native_date_columns`; the native params get a `shape` field.

### Output surfaces

Each item marked "byte change" is in section 10 and the `Breaking:` line.

- B1 Column type, `TIMESTAMP_TZ`: keeps the source unit and zone on every route. Byte change where the pandas route wrote `timestamp[ns, tz]` for a `us` or `ms` source.
- B2 Overlap resolution, `TIMESTAMP_TZ`: an ambiguous local time keeps the source row's UTC offset if that offset is valid, else the earlier instant (Java rule), on both routes. Byte change where the oracle's DST-flag rule picked differently (only where a zone's base offset changed between the source and target dates).
- B3 Gap resolution: first valid instant after the gap, as today (`shift_forward` equals Arrow `latest`). No change, proven by T4.
- B4 Out of range: `date32` source outside years 1 to 9999, and any shifted value outside the type range: row error, source kept, on both routes. Byte change where the oracle raised or failed the job.
- B5 Unified slice: the target column is spliced from Arrow; the pandas schema metadata no longer lists it (the UF-DOMAIN S1 rule).
- Values for `DATE` sources in range: unchanged (T1).
- Route evidence: `date_shift` native in place of `pandas_oracle`; two new decline codes.

## 5. Slices and size

**S1 DATE (`date32`).**

| File | Change | Lines (estimate) |
|---|---|---|
| `transforms/date_shift.py` (169) | `shift_typed_days(array, offsets)` for `date32`: cast to `int32`, add, range check against days -719162 and 2932896, return shifted array and failed mask | +35 |
| `generation/pool/_canonicalize.py` | `canonicalize_typed_array(array) -> pa.Array` (binary keys): `date32` cast to `string`, then UTF-8 bytes; documented as equal to `_canonicalize_source` per value | +20 |
| `execution/native/_date_shift_ext.py` (255) | `native_date_shift` branches on `shape`: typed keys, `_derive_offsets`, `shift_typed_days`, row errors | +30 |
| `execution/native/_operator_config_rejections.py` (324) | skip the format check for a typed shape; `preserve_values` and resident-type declines for typed | +15 |
| `execution/native/_real_type_admission.py` (196) | typed `date_shift` passes the source-type check when the shape and resident type match | +8 |
| `execution/_operator_registry.py` (295) | `date_shift` unified domain gains `date32` | +2 |
| `execution/native/_chunked_schema_rule.py` | typed `date_shift` output pinned to the source type | +6 |
| `execution/_strategies/_date_shift.py` (467) | `_shift_dates` calls `canonicalize_typed_array` and `shift_typed_days`; the Python loop goes | -25, +12 |
| `execution/native/_route_decline_codes.py` and the reasons catalog | two codes | +4 |
| `changelog.d/date-shift-typed-date.md` | `### Changed` plus `Breaking:` (B4, B5) | new |
| Tests | T1-T3, T7, T8 | about 250 |

**S2 TIMESTAMP_TZ.**

| File | Change | Lines (estimate) |
|---|---|---|
| `transforms/date_shift.py` | `shift_typed_days` for zoned `timestamp`: `local_timestamp`, add days in the unit with checked int64 arithmetic, `assume_timezone` with `earliest` and with `latest`, pick per row (section 7) | +40 |
| `generation/pool/_canonicalize.py` | timestamp keys: convert to UTC, `strftime("%Y-%m-%dT%H:%M:%S")`, fraction (9 digits if the nanosecond part is non-zero, 6 if the microsecond part is, else none), `+00:00` | +25 |
| `execution/_strategies/_date_shift.py` | `_shift_zoned` replaced by `shift_typed_days`; the oracle output keeps the source dtype | -20, +10 |
| `execution/_operator_registry.py` | `date_shift` unified domain admits zoned `timestamp` of any unit: a `unified_resident_type_predicate` field on `OperatorSpec`, used only by `date_shift` | +10 |
| `execution/_unified_slice_resident_types.py` | the domain check calls the predicate when it is set | +6 |
| native, config rejection, schema rule | same branches as S1 for the second shape | +15 |
| `docs/compatibility-contract.md` | date_shift typed entries (B1-B5) | about 15 |
| `changelog.d/date-shift-typed-timestamp.md` | `Breaking:` (B1, B2, B4) | new |
| Tests | T4-T6, T9 | about 250 |

Two slices. `_strategies/_date_shift.py` shrinks. `_unified_slice_admission.py` is not touched by this plan.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_date_shift_typed_parity.py` | `tests/parity/` | cross-route equality tests | `test_phase_d_faker_seq.py` |
| `test_date_shift_typed_kernel.py` | `tests/native/` | native operator tests | `test_dispatch_faker.py` |
| `test_typed_canonical_keys.py` | `tests/native/` | native operator tests (key bytes are tested there today) | `test_determinism_protocol.py` |
| `test_date_shift_one_arithmetic.py` | `tests/sentry/defects/` | "Sentry test" | other defect sentries |
| two fragments | `changelog.d/` | "Changelog fragments" | other fragments |

No new source module. `execution/` (cap 103) and `execution/native/` (cap 55) get no new file; the helpers go into `transforms/date_shift.py` and `generation/pool/_canonicalize.py`, which already own the window and the key bytes. The sentry gets a row in `scripts/dev/sentry_registry.toml`.

## 7. Design notes

One arithmetic: `shift_typed_days` is the only code that adds days to a typed date. The sentry `test_date_shift_one_arithmetic.py` walks the AST of `execution/` and fails on `timedelta(days=`, `to_timedelta(` with `unit="D"`, `tz_localize(` and `assume_timezone(` outside `transforms/date_shift.py`. Seeded cases in the sentry's own test: one of each. The mutation that must turn it red: put the `date + timedelta` loop back in `_shift_dates`.

One key definition: `canonicalize_typed_array` must equal `[_canonicalize_source(v) for v in array.to_pylist()]`. T2 checks it over a corpus with a property test (Hypothesis, dates over years 1 to 9999, timestamps over each unit and several zones, fractions with zero and non-zero micro and nano parts).

Overlap rule (S2), computed in Arrow: `e = assume_timezone(local, "earliest")`, `l = assume_timezone(local, "latest")`. Where `e == l` the time is not ambiguous. Where they differ, take the candidate whose UTC offset (`local - utc`) equals the source row's UTC offset; if neither does, take `e`. For a gap `assume_timezone(nonexistent="latest")` gives the first instant after it. Each step is a vector operation; there is no per-row Python.

Why the keys stay ISO text and not the integer day number: an integer key would be a little faster, but it changes every offset and breaks the rule that a typed date and the same date stored as text shift alike in one namespace. The Arrow cast to `string` is a C++ vector step; HMAC dominates the cost. The PR records the split of key formatting against HMAC time. If formatting is over 20% of native `date_shift` time, Q2 asks the owner.

Smallest alternative considered: let native format typed values to text, call today's text kernel, and parse back. Rejected by the owner direction: it is slower, it loses the unit, and it keeps pandas in the kernel.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | row errors and decline messages | `format_error_row_errors` carries positions and the reason only; codes carry table and column | T7 asserts no date text in errors | put the source value in the row error (T7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: the kernel opens no file or temp state; a decline returns before output | n/a | n/a |
| 3 | State and concurrency | chunked shifting across chunks | the offset depends only on the row's key bytes, never on chunk position | T3 (chunked equals unified equals oracle) | key on the row index (T3 red) |
| 4 | Route parity and silent fallback | oracle vs native | one arithmetic and one key function, shared; sentry | T1, T3, T5, sentry | change the native range check bound by one day (T1 edge cell red) |
| 5 | Referential integrity | none | N/A: `date_shift` is never an FK key strategy | n/a | n/a |
| 6 | Untrusted producer | a file with dates outside years 1 to 9999 or extreme timestamps | range check returns a failed mask; row error, source kept | T6, T8 | skip the range check (T6 raises) |
| 7 | Check then use | plan shape checked at admission, used at run | the shape is carried on the bound params, not read again from the config | T9 | read the shape from the config at run time with a mismatched resident type (T9 red) |
| 8 | Weak tests | equality of `to_pylist()` misses the unit | T1, T5 compare Arrow arrays with type | T1, T5 | compare `to_pylist()` (reviewer checks) |
| 9 | Refactor drift | the oracle moved onto the shared helper | the T1 corpus runs against today's oracle output, recorded before S1 starts | T1 | n/a |
| 10 | Frozen contract drift | ROUTE-OUTPUT-CONTRACT and date_shift contract text | B1-B5 entries and Breaking lines | docs review, T4 | leave the old "date_shift output is always string" pin in `_chunked_schema_rule.py:18` (T3 red) |

## 9. Acceptance tests (each fails before the change unless marked)

- **T1 DATE identity.** A corpus of `date32` values covering years 1, 99, 999, 1000, 1582, 1970, 2000, 9999, leap days, nulls, and offsets that cross 0001-01-01 and 9999-12-31. Before S1, the builder records today's oracle output for this corpus as a fixture. After S1, the oracle and the native kernel both equal the fixture for every in-range row (Arrow `equals` with type), and out-of-range rows are `format_error` with the source kept. Fail-before: the native half declines.
- **T2 key bytes.** Property test: `canonicalize_typed_array` equals per-value `_canonicalize_source` for `date32` (S1) and zoned `timestamp` in `s`, `ms`, `us`, `ns` across UTC, `America/New_York`, `Europe/London`, `Australia/Lord_Howe` (S2). Fail-before: the function does not exist.
- **T3 routes agree.** One config, `date32` column: 2,000 rows on the unified slice, 120,000 rows chunked, and a two-table FK job on the sequential route. Each output equals the oracle's on the same rows; route evidence names the native `date_shift`. A text column holding the same dates as ISO strings in the same namespace gets the same offsets. Fail-before: all three report `pandas_oracle`.
- **T4 zoned corpus.** Every DST gap and overlap from 1970 to 2037 in the four zones above, shifted by offsets that land in and out of each: gap cells equal today's oracle output (B3, no change); overlap cells follow the Java rule (B2). The test counts the overlap cells where the old DST-flag rule differs and lists them in the output; the PR reports the count. Fail-before: native declines.
- **T5 unit and zone kept.** `timestamp[s, UTC]`, `timestamp[ms, Europe/London]`, `timestamp[us, America/New_York]`, `timestamp[ns, UTC]`: the output type equals the source type on unified, chunked, sequential and oracle routes (B1). Fail-before: native declines and the pandas route writes `ns`.
- **T6 int64 overflow.** `timestamp[ns, UTC]` values near 2262-04-11 with a positive window: shifted values past the range are `format_error` with the source kept, on native and oracle. Fail-before: the oracle raises.
- **T7 errors carry no values.** Row errors and the two new decline codes contain no date text and no source value.
- **T8 date32 beyond Python range (B4).** A `date32` value at year 10000: native keeps it with a `format_error`; the pandas route fails converting it (recorded, marked).
- **T9 declines.** `group_by`, `when:`, `preserve_values`, `date64` resident under a `DATE` shape: each declines with its code from section 3 and runs on the oracle with today's output (control for the oracle half).
- **S sentry.** `test_date_shift_one_arithmetic.py` passes and fails on each seeded case.

Mutations (record the head they ran on): off-by-one on the upper date bound (T1 red); key on the raw int32 day number (T2, T3 red); overlap rule replaced by plain `earliest` (T4 red on overlap cells where the source was standard time).

Performance evidence (performance.md): 1,000,000-row `date32` and `timestamp[us, UTC]` columns, oracle before and native after, three runs each on the Dell node through `vm-run`; record wall time, peak RSS, and the split of key formatting against HMAC. Numbers go in the PR bodies.

## 10. Frozen contracts and compatibility

- **Byte changes, marked:** B1 (unit and zone kept), B2 (overlap rule), B4 (out-of-range as row error), B5 (unified splice and metadata). Recorded in `docs/compatibility-contract.md` under ROUTE-OUTPUT-CONTRACT and the date_shift entry.
- S1 fragment first line: `Breaking: date_shift on a date column runs natively; a date outside years 1 to 9999 is a row error that keeps the source instead of failing the job.`
- S2 fragment first line: `Breaking: date_shift on a zoned timestamp keeps the source unit and time zone, and an ambiguous local time after the shift keeps the source UTC offset when it can.`
- The `_chunked_schema_rule.py` statement "date_shift output is always `string`" (line 18) becomes "text sources give `string`; typed sources keep their type".
- Offsets and key bytes: unchanged for every row (T1, T2). `SEED_PROTOCOL_VERSION` is not touched. Plan digest: the params gain `shape`, which is derived from the plan, not serialized config; the builder confirms the plan digest does not move.

## 11. Pre-mortem

- Arrow `strftime` for year below 1000 does not zero-pad on some platforms. T2 runs on Linux and the Mac node; if it fails, the key builds the year with `pc.utf8_lpad` over the integer year.
- `pc.local_timestamp` behaves differently across pyarrow versions (the floor is `pyarrow>=14`). The builder runs T4 on the lowest pinned pyarrow in CI as well as the current one.
- The oracle change (B2) moves output for some rows that customers have already masked. Pre-V1, allowed by the owner direction; named in the Breaking line.
- The sequential route has its own date_shift seam (`execution/_strategies/_date_shift.py`, called only when shape is None today). The builder confirms the sequential native op reads the same config rejection, so a typed column is not admitted on one route and declined on another; T3 covers it.

## 12. Open questions for the owner

- **Q1.** The B2 overlap rule changes oracle output where a zone's base offset changed between the source and target dates. Recommended: accept (one rule on both routes, vectorized). T4 reports the count of changed cells before merge.
- **Q2.** If key formatting is over 20% of native `date_shift` time, switch typed keys to the integer day or epoch value (faster, changes every typed offset, breaks text and typed agreement)? Recommended: keep ISO keys unless the number says otherwise.
