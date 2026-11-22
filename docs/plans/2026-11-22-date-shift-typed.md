Status: plan (revision 2, 2026-11-22; Dennis R1 items closed)

# DATE-SHIFT-TYPED: `date_shift` on `date32` and zoned `timestamp` sources runs native, on the typed values

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: DATE-SHIFT-TYPED (group mask, 1.0), from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`) and the COLUMN-SHAPE-RULE row 19 follow-on (E1b merged in engine #751). Two slices, engine only. Depends on UF-DOMAIN S1 (`plan/uf-domain`, the one output assembler with its `arrow_columns` input).

Anchors: a path with no prefix is under `src/decoy_engine/` in this repository (decoy-engine). Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head. Arrow behavior was probed with the engine venv (pyarrow 24.0.0).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `risk-and-exceptions.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (determinism of a masking strategy; some output values change on a recorded contract). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

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

Search run: calendar-day arithmetic on zoned timestamps (PostgreSQL `timestamptz + interval '1 day'`, Java `ZonedDateTime.plusDays`, Arrow `assume_timezone` and `local_timestamp` docs); date-shift de-identification in established tools (the MIMIC per-patient shift, Philter); Arrow temporal casts and `strftime` (`pyarrow.compute` docs).

- Calendar-day arithmetic (Java `ZonedDateTime.plusDays`, PostgreSQL `interval 'N days'`): add days to the local date-time, then resolve against the zone. In an overlap Java keeps the previous offset if it is valid at the target. This plan takes that overlap rule (B2). For a gap Java moves the local time forward by the gap length; this plan does not take that rule. It keeps today's pandas `nonexistent="shift_forward"` (the first valid instant after the gap), so gap cells do not change (B3).
- Arrow: `pc.local_timestamp` gives the wall clock; `pc.assume_timezone(ambiguous=..., nonexistent=...)` re-attaches the zone, with `earliest`, `latest` or `raise` for each case. Arrow `nonexistent="latest"` was measured equal to pandas `shift_forward` in plan review. Arrow has no "keep the source offset" option, so B2 is computed from the two candidates (section 7).
- De-identification practice (MIMIC, Philter): shift every date of one entity by one keyed offset, keep the type, keep the time of day. That is the engine's keyed-offset rule. None of these tools formats a date to text to shift it.
- Arrow casts `date32` to `string` as ISO `YYYY-MM-DD` with a zero-padded 4-digit year (probed: year 5 gives `0005-01-01`), the same bytes as Python `date.isoformat()` for years 1 to 9999. Arrow `strftime("%S")` adds the unit's fraction for a sub-second unit (probed: `timestamp[us]` gives `00:00:00.000000`), while Python `isoformat()` drops a zero fraction; section 7 handles this.

### Reuse inventory

- `derive_index_batch` through `_derive_offsets` (`execution/native/_date_shift_ext.py:97`): the compiled keyed offsets, reused as they are.
- `_canonicalize_source` (`generation/pool/_canonicalize.py:63`): the definition of the key bytes. The new vector form sits beside it and is tested against it.
- `shift_window`, `order_window` (`transforms/date_shift.py:100`, `:64`): the day bounds.
- `format_error_row_errors`, `FORMAT_ERROR_REASON` (`execution/native/_date_shift_ext.py:75`): the row-error form.
- `RouteDeclineCode` and `coded(...)` (`execution/native/_route_decline_codes.py`): two new members.
- UF-DOMAIN S1 `table_from_pandas_keeping_source_types(..., arrow_columns=...)` (`execution/_fk_keys.py:521`): the one output assembler. A typed masked column is handed to it as an Arrow array. This plan adds no second splice.

## 3. Guarantee and non-goals

After S1 (DATE) and S2 (TIMESTAMP_TZ):

1. A `date_shift` column whose plan shape is `DATE` over a resident `date32`, or `TIMESTAMP_TZ` over a resident `timestamp` with a zone (any unit), with a namespace, no `group_by`, no `when:`, and no `preserve_values`, runs native on the unified slice, the chunked route and the sequential route.
2. The day offset of each row equals the oracle's offset for that row: the key bytes are `_canonicalize_source(value)` computed over the Arrow array (ISO date for `DATE`; `astimezone(UTC).isoformat()` for `TIMESTAMP_TZ`). A typed date and the same date stored as ISO text in another table get the same shift in the same namespace, as today.
3. One arithmetic for both routes: `shift_typed_days(array, offsets) -> (shifted, failed)` in `transforms/date_shift.py`. The native route calls it on the resident array. The oracle calls it on an Arrow array built from the usable cells (section 4 "Exit paths"). Oracle and native output values agree by construction.
4. The output column keeps the source Arrow type (`date32`; `timestamp` with the source unit and zone) on every route. On the unified slice the native output column goes to the UF-DOMAIN assembler through `arrow_columns`, never through the pandas frame.
5. A shifted value outside the type's range (years 1 to 9999 for `date32`; the int64 range of the unit for `timestamp`) is a `format_error` row error and keeps its source value, on both routes.
6. Deterministic: same seed, namespace and input give the same bytes on every route and every run. One named exception: a `date32` source value outside years 1 to 9999 (B4). The native routes keep it with a row error; the pandas route cannot convert the column and fails the job.

Non-goals, each kept on its existing path with a coded reason:

| Case | Reason code | Path |
|---|---|---|
| `group_by` set | `date_shift_group_by_not_native` (existing) | oracle |
| `when:` on the column | existing `when:` decline | oracle |
| `preserve_values` on a typed source | `date_shift_typed_preserve_not_native` (new) | oracle |
| plan shape `DATE` over `date64`, or any other resident type for a typed shape | `date_shift_typed_type_not_native` (new) | oracle |
| naive timestamp, integer source | `column_shape_mismatch` at compile (existing) | refused |
| out-of-core route | out-of-core does not take `date_shift` today | unchanged |

Text-source `date_shift` keeps its native text kernel. The oracle's text zoned path (a string column parsed with a `%z` format) moves onto `shift_typed_days` in S2 with the rest of the oracle, so B2 applies to it too.

## 4. Enumerations

### Exit paths

- Admitted typed column: shifted natively; rows out of range get `format_error` and keep the source (`execution/native/_date_shift_ext.py:75`).
- Null source cell: stays null, no error, no offset derived (as `_shift_dates` at `execution/_strategies/_date_shift.py:393`).
- Oracle, a non-date cell in a `DATE`-shaped object column (a string or number that reached a column the plan types as date): today a `format_error` row error that keeps the source (`_shift_dates`, line 401). `pa.Array.from_pandas(col)` would raise `ArrowTypeError` on it (probed). So the oracle keeps its cell pass: it classifies each cell (null, `date`, `datetime` reduced to its date, other), builds the `date32` array from the usable cells with null in every other slot, calls `shift_typed_days`, and marks the "other" cells as row errors. Behavior unchanged; T10.
- Declined typed column: one of the coded reasons in section 3, oracle path.
- `date32` source value outside years 1 to 9999: native keeps it with a `format_error`; the pandas route fails converting the column (B4).
- Missing namespace: existing config rejection, unchanged.

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | declined (`date_shift` domain is `string`) | admitted for `date32` (S1) and zoned `timestamp` (S2); the masked column reaches output through `arrow_columns` |
| Chunked native | `date_shift_requires_date_format` | admitted; `date_shift_pinned_columns` (`execution/native/_chunked_schema_rule.py:169`) pins a typed column's output to the source type, not `string` |
| Sequential native | requires a `date_format` | admitted through the same config rejection |
| Out-of-core | does not take `date_shift` | unchanged |
| Oracle (pandas) | Python loop and pandas tz arithmetic | calls `shift_typed_days`; same values as native |

### FK shapes

- A typed date column is never an FK key on the native routes (`date_shift` is not a key strategy). Unchanged.
- A typed `date_shift` column in a child or parent table runs on the sequential route under the same rule as a single table.

### Fields

- `strategy: date_shift`, `namespace` (required for native), `min_days` / `max_days` (resolved by `shift_window`).
- `date_format`: the oracle ignores it for a typed shape (`_required_format` at `execution/_strategies/_date_shift.py:108`). The config rejection skips the format check when the plan shape is typed.
- `group_by`, `preserve_values`, `when`: decline (section 3).
- Plan shape: `ColumnShape.DATE` or `ColumnShape.TIMESTAMP_TZ` from `native_date_columns`; the native params get a `shape` field.

### Output surfaces

Each item marked "byte change" is in section 10 and a `Breaking:` line.

- B1 Column type, `TIMESTAMP_TZ`: keeps the source unit and zone on every route (guarantee 4). Not a byte change on the pandas route at pandas 2 (probed: `timestamp[us, UTC]` round-trips through pandas with its unit). T5 proves it on every route, unified included.
- B2 Overlap resolution, `TIMESTAMP_TZ` and text zoned sources: an ambiguous local time keeps the source row's UTC offset if that offset is valid, else the earlier instant (Java rule), on both routes. Byte change where the oracle's DST-flag rule picked differently.
- B3 Gap resolution: first valid instant after the gap, as today. No change; T4.
- B4 Out of range: a `date32` source outside years 1 to 9999, and any shifted value outside the type range: row error, source kept. Byte change where the oracle raised or failed the job.
- B5 Unified slice: the target column comes from the native Arrow output, so the pandas schema metadata does not list it (the UF-DOMAIN S1 rule).
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
| `execution/_unified_slice_evidence.py` (246) | a typed `date_shift` node's masked column is passed to the assembler in `arrow_columns`, not overlaid on the frame | +6 |
| `execution/native/_chunked_schema_rule.py` | typed `date_shift` output pinned to the source type | +6 |
| `execution/_strategies/_date_shift.py` (467) | `_shift_dates` keeps its cell pass, then calls `canonicalize_typed_array` and `shift_typed_days`; the per-row `timedelta` loop goes | -15, +12 |
| `execution/native/_route_decline_codes.py` and the reasons catalog | two codes | +4 |
| `changelog.d/date-shift-typed-date.md` | `### Changed` plus `Breaking:` (B4, B5) | new |
| Tests | T1-T3, T7, T8, T10, sentry | about 260 |

**S2 TIMESTAMP_TZ.**

| File | Change | Lines (estimate) |
|---|---|---|
| `transforms/date_shift.py` | `shift_typed_days` for zoned `timestamp`: `local_timestamp`, add days in the unit with checked int64 arithmetic, `assume_timezone` with `earliest` and with `latest`, pick per row (section 7) | +40 |
| `generation/pool/_canonicalize.py` | timestamp keys (section 7) | +25 |
| `execution/_strategies/_date_shift.py` | `_shift_zoned` deleted; the typed and the text zoned paths call `shift_typed_days` on `pa.Array.from_pandas(parsed)`; the oracle output keeps the source dtype | -20, +10 |
| `execution/_operator_registry.py` | `date_shift` unified domain admits zoned `timestamp` of any unit: a `unified_resident_type_predicate` field on `OperatorSpec`, used only by `date_shift` | +10 |
| `execution/_unified_slice_resident_types.py` | the domain check calls the predicate when it is set | +6 |
| native, config rejection, schema rule | same branches as S1 for the second shape | +15 |
| `docs/compatibility-contract.md` | date_shift typed entries (B1-B5) | about 15 |
| `changelog.d/date-shift-typed-timestamp.md` | `Breaking:` (B2, B4) | new |
| Tests | T4-T6, T9 | about 250 |

Two slices. `_strategies/_date_shift.py` shrinks.

QA log item: `OperatorSpec` gets a fourth type-domain field (`unified_resident_types`, `positional_resident_types`, `deterministic_resident_types`, and now `unified_resident_type_predicate`). Logged as a QA follow-up to fold the four into one domain descriptor per operator; not in this row.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_date_shift_typed_parity.py` | `tests/parity/` | cross-route equality tests | `test_phase_d_faker_seq.py` |
| `test_date_shift_typed_kernel.py` | `tests/native/` | native operator tests | `test_chunked_date_shift_parity.py` |
| `test_typed_canonical_keys.py` | `tests/native/` | native operator tests (key bytes are tested there today) | `test_determinism_protocol.py` |
| `test_date_shift_one_arithmetic.py` | `tests/sentry/defects/` | "Sentry test" | other defect sentries |
| two fragments | `changelog.d/` | "Changelog fragments" | other fragments |

No new source module. `execution/` (cap 103) and `execution/native/` (cap 55) get no new file; the helpers go into `transforms/date_shift.py` and `generation/pool/_canonicalize.py`, which already own the window and the key bytes. The sentry gets a row in `scripts/dev/sentry_registry.toml`.

## 7. Design notes

One arithmetic: `shift_typed_days` is the only code that adds calendar days to a typed date or re-attaches a zone. Sentry `test_date_shift_one_arithmetic.py`, an AST rule over `execution/**/*.py`:

- Forbidden calls: `datetime.timedelta(days=...)` or `timedelta(days=...)`; `.tz_localize(`; `pc.assume_timezone(` / `pyarrow.compute.assume_timezone(`; `pc.local_timestamp(`.
- Not covered on purpose: `pd.to_timedelta`, which the text path uses legitimately (`execution/_strategies/_date_shift.py:448`, `execution/native/_date_shift_ext.py:233`) and `bucket_perturb` uses for numeric-date buckets (`execution/native/_bucket_perturb_ext.py:124`, `:128`, `:303`). Those are text or bucket arithmetic, not typed-shape arithmetic.
- Named allowlist (module, function, reason): starts empty. At `70881ad79` the forbidden calls appear only in `_shift_zoned` and `_shift_dates`, which S1 and S2 remove.
- Seeded cases in the sentry's own test: one of each forbidden call in a scratch module; each must fail.
- The mutation that must turn it red: put the `date + timedelta` loop back in `_shift_dates`.

One key definition: `canonicalize_typed_array` must equal `[_canonicalize_source(v) for v in array.to_pylist()]`. For `TIMESTAMP_TZ` the key is built in four vector steps:

1. Convert to UTC and floor to whole seconds with `pc.floor_temporal(unit="second")`. Floor, not a truncating cast, so a pre-1970 value with a fraction gets the right second.
2. Cast the floored value to `timestamp("s", "UTC")` and format it with `strftime("%Y-%m-%dT%H:%M:%S")`. At second unit `strftime` adds no fraction (probed).
3. Compute the sub-second part as an integer in the source unit (value minus floored value). Append `.` plus 9 digits if the nanosecond part is non-zero, `.` plus 6 digits if only the microsecond part is non-zero, else nothing. This is Python `isoformat()` on a pandas `Timestamp`.
4. Append `+00:00`.

T2 checks it with a property test (Hypothesis): dates over years 1 to 9999; timestamps over each unit and several zones, pre- and post-1970, with zero and non-zero micro and nano parts.

Overlap rule (S2), computed in Arrow: `e = assume_timezone(local, ambiguous="earliest")`, `l = assume_timezone(local, ambiguous="latest")`, both with `nonexistent="latest"`. Where `e == l` the time is not ambiguous. Where they differ, take the candidate whose UTC offset (`local - utc`) equals the source row's UTC offset; if neither does, take `e`. Each step is a vector operation; there is no per-row Python.

Keys stay ISO text, not the integer day or epoch number. Integer keys would change every typed offset and break the rule that a typed date and the same date stored as text shift alike across tables in one namespace. The Arrow formatting is a C++ vector step. The PR records the split of key formatting against HMAC time for the owner's information; changing the key form is an owner decision, not a trigger in this plan.

Unified-slice output: a typed `date_shift` target is a frame column under UF-DOMAIN (it is a non-passthrough target), so the round-trip guard applies to it at admission (probed: `date32` and `timestamp[us, UTC]` round-trip cleanly). Its masked output does not go back through the frame. `reconstruct_source_shaped_output` passes it to the UF-DOMAIN assembler in `arrow_columns`, so the native array is written as it is, with its unit and zone. The old `frame[col] = masked.to_pylist()` overlay would give `timestamp[ns, tz]`. This uses the UF-DOMAIN mechanism; nothing is copied.

Smallest alternative considered: let native format typed values to text, call today's text kernel, and parse back. Rejected by the owner direction: it is slower, it loses the unit, and it keeps pandas in the kernel. Declining `TIMESTAMP_TZ` on the unified slice was also considered and rejected: the `arrow_columns` input makes the typed output path cost one dictionary entry.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | row errors and decline messages | `format_error_row_errors` carries positions and the reason only; codes carry table and column | T7 | put the source value in the row error (T7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: the kernel opens no file or temp state; a decline returns before output | n/a | n/a |
| 3 | State and concurrency | chunked shifting across chunks | the offset depends only on the row's key bytes, never on chunk position | T3 | key on the row index (T3 red) |
| 4 | Route parity and silent fallback | oracle vs native, unified output | one arithmetic, one key function, one assembler; sentry | T1, T3, T5, sentry | overlay the unified output through `to_pylist()` again (T5 unified cell red) |
| 5 | Referential integrity | none | N/A: `date_shift` is never an FK key strategy | n/a | n/a |
| 6 | Untrusted producer | dates outside years 1 to 9999, extreme timestamps, non-date cells in a date-shaped object column | range check returns a failed mask; the oracle cell pass marks other cells | T6, T8, T10 | skip the range check (T6 raises) |
| 7 | Check then use | plan shape checked at admission, used at run | the shape is carried on the bound params, not read again from the config | T9 | read the shape from the config at run time with a mismatched resident type (T9 red) |
| 8 | Weak tests | `to_pylist()` equality misses the unit | T1, T5 compare Arrow arrays with type | T1, T5 | compare `to_pylist()` (reviewer checks) |
| 9 | Refactor drift | the oracle moved onto the shared helper | the T1 corpus runs against today's oracle output, recorded before S1 starts | T1, T10 | n/a |
| 10 | Frozen contract drift | ROUTE-OUTPUT-CONTRACT and the date_shift contract text | B2, B4, B5 entries and Breaking lines | docs review, T4 | leave the "date_shift output is always `string`" pin at `_chunked_schema_rule.py:18` (T3 red) |

## 9. Acceptance tests (each fails before the change unless marked)

- **T1 DATE identity.** A corpus of `date32` values covering years 1, 5, 99, 999, 1000, 1582, 1970, 2000, 9999, leap days, nulls, and offsets that cross 0001-01-01 and 9999-12-31. Before S1, the builder records today's oracle output for this corpus as a fixture. After S1, the oracle and the native kernel both equal the fixture for every in-range row (Arrow `equals` with type), and out-of-range rows are `format_error` with the source kept. Fail-before: the native half declines.
- **T2 key bytes.** Property test: `canonicalize_typed_array` equals per-value `_canonicalize_source` for `date32` (S1) and zoned `timestamp` in `s`, `ms`, `us`, `ns` across UTC, `America/New_York`, `Europe/London`, `Australia/Lord_Howe`, pre- and post-1970, with zero and non-zero fractions (S2). Fail-before: the function does not exist.
- **T3 routes agree.** One config, `date32` column: 2,000 rows on the unified slice, 120,000 rows chunked, and a two-table FK job on the sequential route. Each output equals the oracle's on the same rows; route evidence names the native `date_shift`. A text column holding the same dates as ISO strings in the same namespace gets the same offsets. Fail-before: all three report `pandas_oracle`.
- **T4 zoned corpus.** Every DST gap and overlap from 1970 to 2037 in the four zones above, shifted by offsets that land in and out of each: gap cells equal today's oracle output (B3, no change); overlap cells follow the Java rule (B2). The test counts the overlap cells where the old DST-flag rule differs and prints them; the PR reports the count. Fail-before: native declines.
- **T5 unit and zone kept.** `timestamp[s, UTC]`, `timestamp[ms, Europe/London]`, `timestamp[us, America/New_York]`, `timestamp[ns, UTC]`: the output type equals the source type on the unified slice (2,000 rows; the cell that catches a frame overlay), chunked, sequential and oracle routes. Fail-before: the native routes decline.
- **T6 int64 overflow.** `timestamp[ns, UTC]` values near 2262-04-11 with a positive window: shifted values past the range are `format_error` with the source kept, on native and oracle. Fail-before: the oracle raises.
- **T7 errors carry no values.** Row errors and the two new decline codes contain no date text and no source value.
- **T8 date32 beyond Python range (B4).** A `date32` value at year 10000: native keeps it with a `format_error`; the pandas route fails converting it (recorded, marked).
- **T9 declines.** `group_by`, `when:`, `preserve_values`, `date64` resident under a `DATE` shape: each declines with its code from section 3 and runs on the oracle with today's output (control for the oracle half).
- **T10 non-date cells on the oracle.** A `DATE`-shaped object column holding a `date`, a `datetime`, a string `"x"`, an int and a null: the `date` and the `datetime` (by its date) shift; `"x"` and the int are `format_error` row errors that keep the source; the null stays null. Equal to today's oracle output for the same column. Control: passes before and after.
- **S sentry.** `test_date_shift_one_arithmetic.py` passes and fails on each seeded case.

Mutations (record the head they ran on): off-by-one on the upper date bound (T1 red); key on the raw int32 day number (T2, T3 red); truncating cast in place of `floor_temporal` (T2 pre-1970 cells red); overlap rule replaced by plain `earliest` (T4 red on overlap cells where the source was standard time).

Performance evidence (performance.md): 1,000,000-row `date32` and `timestamp[us, UTC]` columns, oracle before and native after, three runs each on the Dell node through `vm-run`; record wall time, peak RSS, and the split of key formatting against HMAC. Numbers go in the PR bodies.

## 10. Frozen contracts and compatibility

- **Byte changes, marked:** B2 (overlap rule, typed and text zoned sources), B4 (out-of-range as row error), B5 (unified output and metadata). B1 is a guarantee with no expected byte change; T5 proves it. Recorded in `docs/compatibility-contract.md` under ROUTE-OUTPUT-CONTRACT and the date_shift entry.
- S1 fragment first line: `Breaking: date_shift on a date column runs natively; a date outside years 1 to 9999 is a row error that keeps the source instead of failing the job.`
- S2 fragment first line: `Breaking: date_shift on a zoned timestamp runs natively, and an ambiguous local time after the shift keeps the source UTC offset when it can (text and typed sources).`
- The `_chunked_schema_rule.py` statement "date_shift output is always `string`" (line 18) becomes "text sources give `string`; typed sources keep their type".
- Offsets and key bytes: unchanged for every row (T1, T2). `SEED_PROTOCOL_VERSION` is not touched. Plan digest: the params gain `shape`, which is derived from the plan, not serialized config; the builder confirms the plan digest does not move.

## 11. Pre-mortem

- `strftime` zero-pads years below 1000 on Linux (probed). T2 runs on the Mac node too; if it fails there, the key builds the year with `pc.utf8_lpad` over the integer year.
- `pc.local_timestamp` and `assume_timezone` behave differently across pyarrow versions (the floor is `pyarrow>=14`). The builder runs T2 and T4 on the lowest pinned pyarrow in CI as well as the current one.
- The oracle change (B2) moves output for some rows already masked. Pre-V1, allowed by the owner direction; named in the Breaking line.
- The sequential route has its own date_shift seam (called only when shape is None today). The builder confirms the sequential native op reads the same config rejection, so a typed column is not admitted on one route and declined on another; T3 covers it.
- UF-DOMAIN S1 is not merged when S1 here starts. This plan does not start before it; the `arrow_columns` input is a hard dependency.

## 12. Open questions for the owner

- **Q1.** The B2 overlap rule changes oracle output where a zone's base offset changed between the source and target dates. Recommended: accept (one rule on both routes, vectorized). T4 reports the count of changed cells before merge.
