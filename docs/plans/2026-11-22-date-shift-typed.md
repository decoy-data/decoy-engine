Status: plan (revision 5, 2026-11-24; section 14 applies Dennis R1 to the source-read boundary of section 13)

# DATE-SHIFT-TYPED: `date_shift` on `date32` and zoned `timestamp` sources runs native, on the typed values

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: DATE-SHIFT-TYPED (group mask, 1.0), from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`) and the COLUMN-SHAPE-RULE row 19 follow-on (E1b merged in engine #751). Five slices over two repos after revision 5: S1b-1, S1b-2, S1-CLI, S1 (#790) and S2 (section 14.11). Depends on UF-DOMAIN S1 (`plan/uf-domain`, the one output assembler with its `arrow_columns` input).

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
2. The day offset of each usable row equals the oracle's offset for that row: the key bytes are `_canonicalize_source(value)` computed over the Arrow array (ISO date for `DATE`; `astimezone(UTC).isoformat()` for `TIMESTAMP_TZ`). A typed date and the same date stored as ISO text in another table get the same shift in the same namespace, as today. A row rejected by guarantee 5 derives no key or offset.
3. One arithmetic for both routes: `shift_typed_days(array, offsets) -> (shifted, failed)` in `transforms/date_shift.py`. The native route calls it on the resident array. The oracle calls it on an Arrow array built from the usable cells (section 4 "Exit paths"). Oracle and native output values agree by construction.
4. The output column keeps the source Arrow type (`date32`; `timestamp` with the source unit and zone) on every route. On the unified slice the native output column goes to the UF-DOMAIN assembler through `arrow_columns`, never through the pandas frame.
5. Before key construction, timezone conversion, formatting, or day addition, typed temporal values are read as their physical integer plus unit and checked with integer quotient/remainder and explicit bounds. A source timestamp whose UTC second is outside Python ISO years 1 to 9999, or whose local-time conversion cannot be represented, and any shifted value outside the source type's int64/unit range, is a `format_error` row error and keeps its source value on both routes. No Arrow floor, cast, timezone, formatting, or addition kernel receives a value that has not passed the applicable preflight.
6. Deterministic: same seed, namespace and input give the same bytes on every route and every run. One named exception: a `date32` source value outside years 1 to 9999 (B4). The unified slice and chunked routes keep it with a row error; the sequential and full-frame routes read the table through pandas, cannot convert the column, and fail the job with the coded `ExecutionError` `full_frame_value_unrepresentable` (table and column named, no value) (amended 2026-11-24 after Codex a1 round 3). The value-free guarantee covers every read before the route too, including profiling's sample conversion: profiling converts its sample without raising on an unrepresentable value, so the route's coded error fires whether the value sits inside or outside the profile sample, on both pandas routes (amended 2026-11-24 after Codex a2). Revision 4: this guarantee is now held by the one source-read boundary in section 13, not by `profile/_frame.py`.

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
- `date32` source value outside years 1 to 9999: the unified slice and chunked routes keep it with a `format_error`; the sequential and full-frame routes fail converting the column, with the coded error `full_frame_value_unrepresentable` and no value text, also when the value is inside the profile sample (B4, amended 2026-11-24 after Codex a1 round 3 and Codex a2).
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
- B4 Out of range: a `date32` source outside years 1 to 9999, a timestamp source outside the key/timezone preflight, and any shifted value outside the source type's range: row error, source kept. Byte change where the oracle raised or failed the job. Route difference (amended 2026-11-24 after Codex a1 round 3): sequential and full_frame read the whole table through pandas before any strategy runs, so an out-of-range `date32` source fails the job there with `ExecutionError` `full_frame_value_unrepresentable`, naming the table and column and no value, instead of quarantining the row. Recorded under ROUTE-OUTPUT-CONTRACT. Amended 2026-11-24 after Codex a2: profiling reads the source before either route, so its sample conversion goes through the same value-tolerant helper as resident profiling (`profile/_frame.py` `profile_frame`); no bare `to_pandas()` on a source table stays in `profile/`. Revision 4: superseded by section 13; `profile/_frame.py` is deleted and every source read goes through `internal/pandas_compat.py` `source_frame`.
- B5 Unified slice: the target column comes from the native Arrow output, so the pandas schema metadata does not list it (the UF-DOMAIN S1 rule).
- Values for `DATE` sources in range: unchanged (T1).
- Route evidence: `date_shift` native in place of `pandas_oracle`; two new decline codes.

## 5. Slices and size

**S1 DATE (`date32`).**

| File | Change | Lines (estimate) |
|---|---|---|
| `transforms/date_shift.py` (169) | `shift_typed_days(array, offsets)` for `date32`: cast to `int32`, add, range check against days -719162 and 2932896, return shifted array and failed mask | +35 |
| `generation/pool/_canonicalize.py` | `canonicalize_typed_array(array) -> (keys, failed)` (binary keys plus row mask): `date32` cast to `string`, then UTF-8 bytes; documented as equal to `_canonicalize_source` per usable value | +20 |
| `execution/native/_date_shift_ext.py` (255) | `native_date_shift` branches on `shape`: typed keys, `_derive_offsets`, `shift_typed_days`, row errors | +30 |
| `execution/native/_operator_config_rejections.py` (324) | skip the format check for a typed shape; `preserve_values` and resident-type declines for typed | +15 |
| `execution/native/_real_type_admission.py` (196) | typed `date_shift` passes the source-type check when the shape and resident type match | +8 |
| `execution/_operator_registry.py` (295) | replace the three parallel resident-type fields with one `resident_type_domain` descriptor and one admission operation; migrate every operator without changing its domain, then add `date32` to `date_shift` | about +35/-15 |
| `execution/_unified_slice_resident_types.py` | replace the three derived tables/functions with the descriptor's one admission operation | about -25 |
| `execution/_unified_slice_admission.py` | call that operation instead of selecting positional, deterministic, then default tables | about -8 |
| `execution/_unified_slice_evidence.py` (246) | a typed `date_shift` node's masked column is passed to the assembler in `arrow_columns`, not overlaid on the frame | +6 |
| `execution/native/_chunked_schema_rule.py` | typed `date_shift` output pinned to the source type | +6 |
| `execution/_strategies/_date_shift.py` (467) | `_shift_dates` keeps its cell pass, then calls `canonicalize_typed_array` and `shift_typed_days`; the per-row `timedelta` loop goes | -15, +12 |
| `execution/native/_route_decline_codes.py` and the reasons catalog | two codes | +4 |
| `changelog.d/date-shift-typed-date.md` | `### Changed` plus `Breaking:` (B4, B5) | new |
| Tests | T1-T3, T7, T8, T10, T11, sentry | about 280 |

**S2 TIMESTAMP_TZ.**

| File | Change | Lines (estimate) |
|---|---|---|
| `transforms/date_shift.py` | `shift_typed_days` for zoned `timestamp`: `local_timestamp`, add days in the unit with checked int64 arithmetic, `assume_timezone` with `earliest` and with `latest`, pick per row (section 7) | +40 |
| `generation/pool/_canonicalize.py` | timestamp keys (section 7) | +25 |
| `execution/_strategies/_date_shift.py` | `_shift_zoned` deleted; the typed and the text zoned paths call `shift_typed_days` on `pa.Array.from_pandas(parsed)`; the oracle output keeps the source dtype | -20, +10 |
| `execution/_operator_registry.py` | extend the S1 descriptor's central named-family vocabulary with `zoned_timestamp`; add that family to `date_shift` (no new field or dispatch path) | about +8 |
| native, config rejection, schema rule | same branches as S1 for the second shape | +15 |
| `docs/compatibility-contract.md` | date_shift typed entries (B1-B5) | about 15 |
| `changelog.d/date-shift-typed-timestamp.md` | `Breaking:` (B2, B4) | new |
| Tests | T4-T6, T9 | about 250 |

Two slices. `_strategies/_date_shift.py` shrinks. The registry consolidation lands in S1 before either typed domain is admitted; S2 only adds the zoned-timestamp family rule to the same descriptor.

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

One resident-domain mechanism: `_operator_registry.py` owns `ResidentTypeDomain`, the single `OperatorSpec.resident_type_domain` field, and its `admits(resident_type, params)` operation. The descriptor contains the existing default/positional/deterministic variants and each variant is one `ResidentTypeRule` made from an exact-type set plus an optional named family (`zoned_timestamp`); family evaluation is central, not an operator callback. This replaces, rather than supplements, `unified_resident_types`, `positional_resident_types`, and `deterministic_resident_types` at `_operator_registry.py:59-73`, the three derived mechanisms at `_unified_slice_resident_types.py:30-64`, and the selection chain at `_unified_slice_admission.py:513-521`. A registry guard asserts that every non-`group_key` operator has exactly one descriptor, the three old `OperatorSpec` fields no longer exist, all existing exact/positional/deterministic admissions are unchanged, and `date_shift` alone gains `date32` plus zoned timestamps. Mutations that must turn it red: restore any old field, bypass `admits` with a direct type check, or admit a naive timestamp.

One key definition: for every timestamp that Python can represent, `canonicalize_typed_array` must equal `[_canonicalize_source(v) for v in array.to_pylist()]`; non-representable source rows take the guarantee-5 `format_error` exit before conversion to Python or key derivation. For `TIMESTAMP_TZ`, key construction never calls `floor_temporal` and proceeds as follows:

1. View the UTC timestamp as its signed int64 count. For unit `s`, `ms`, `us`, or `ns`, compute `(whole_seconds, remainder) = divmod(count, units_per_second)` with checked integer quotient/remainder; Python/Euclidean division gives `0 <= remainder < units_per_second`, including negative fractional seconds, without subtracting a floored int64 value.
2. Preflight `whole_seconds` against the inclusive UTC-second bounds for years 1 through 9999. Rows outside are marked failed and removed from all subsequent Arrow formatting/timezone operations. Format only safe whole seconds as `timestamp("s", "UTC")` with `strftime("%Y-%m-%dT%H:%M:%S")`.
3. Append the fraction from `remainder`: 9 digits when a nanosecond remainder is not exactly microsecond precision, 6 digits for any other non-zero sub-second part (including millisecond values, as Python `datetime.isoformat()` emits), and nothing for zero. T2 pins the bytes against `_canonicalize_source` for every unit.
4. Append `+00:00`. Separately, `shift_typed_days` first checks that the count has 24-hour offset headroom before `local_timestamp`; it checks `count + offset_days * units_per_day` through `count <= INT64_MAX - delta` / `count >= INT64_MIN - delta` before addition; and it checks target local seconds against the supported ISO-year bounds before `assume_timezone`. A failed row never reaches a timezone kernel or unchecked Arrow arithmetic.

T2 checks representable values with a property test (Hypothesis): dates over years 1 to 9999; timestamps over each unit and several zones, pre- and post-1970, with zero and non-zero fractions. Its explicit boundary table also covers each unit's int64 minimum, minimum+1, maximum-1 and maximum; the negative fractional value `INT64_MIN + 1` for `ms`, `us`, and `ns`; and the nearest in-range values on both sides of the ISO-year preflight. Non-representable cells assert `format_error` plus source preservation and prove that the formatting/timezone kernels were not called for those cells.

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
- **T2 key bytes and source preflight.** For usable rows, a property test asserts `canonicalize_typed_array` equals per-value `_canonicalize_source` for `date32` (S1) and zoned `timestamp` in `s`, `ms`, `us`, `ns` across UTC, `America/New_York`, `Europe/London`, `Australia/Lord_Howe`, pre- and post-1970, with zero and non-zero fractions (S2). A per-unit table supplies `INT64_MIN`, `INT64_MIN+1`, `INT64_MAX-1`, `INT64_MAX`; `INT64_MIN+1` is the negative-fraction underflow witness for `ms`, `us`, and `ns`; and cells immediately inside/outside both ISO-year bounds. It asserts exact keys for representable cells and `format_error` plus unchanged source for rejected cells on native and oracle routes. Spies assert rejected cells never enter formatting or timezone kernels. Fail-before: the function does not exist, and Arrow floor wraps the negative witnesses.
- **T3 routes agree.** One config, `date32` column: 2,000 rows on the unified slice, 120,000 rows chunked, and a two-table FK job on the sequential route. Each output equals the oracle's on the same rows; route evidence names the native `date_shift`. A text column holding the same dates as ISO strings in the same namespace gets the same offsets. Fail-before: all three report `pandas_oracle`.
- **T4 zoned corpus.** Every DST gap and overlap from 1970 to 2037 in the four zones above, shifted by offsets that land in and out of each: gap cells equal today's oracle output (B3, no change); overlap cells follow the Java rule (B2). The test counts the overlap cells where the old DST-flag rule differs and prints them; the PR reports the count. Fail-before: native declines.
- **T5 unit and zone kept.** `timestamp[s, UTC]`, `timestamp[ms, Europe/London]`, `timestamp[us, America/New_York]`, `timestamp[ns, UTC]`: the output type equals the source type on the unified slice (2,000 rows; the cell that catches a frame overlay), chunked, sequential and oracle routes. Fail-before: the native routes decline.
- **T6 per-unit checked shift boundaries.** For each of `timestamp[s]`, `[ms]`, `[us]`, and `[ns]`, exercise positive and negative values at `INT64_MIN`, `INT64_MIN+1`, `INT64_MAX-1`, and `INT64_MAX` with zero, positive, and negative day windows. Include the negative fractional-second underflow witnesses for `ms`, `us`, and `ns`. Rows that cannot be keyed or shifted are `format_error` with the source kept on native and oracle; safe near-boundary rows equal the integer quotient/remainder oracle and retain the exact unit/zone. Spies assert no failed row reaches floor (which production does not use), formatting, timezone conversion, or addition. Fail-before: the oracle raises or cannot convert extremes, and Arrow floor wraps negative witnesses.
- **T7 errors carry no values.** Row errors and the two new decline codes contain no date text and no source value.
- **T8 date32 beyond Python range (B4).** A `date32` value at year 10000: native keeps it with a `format_error`; the sequential and full-frame routes fail with the coded error, and `str`, `repr`, the traceback and the log carry no year and no source value (recorded, marked; amended 2026-11-24 after Codex a1 round 3). Amended 2026-11-24 after Codex a2: Parquet FK source, parametrized on position (first of 120,000, a one-row table, last of 120,000) times route (sequential, full_frame); every case asserts the coded error and no `10000` or `2932897` in `str`, `repr`, the traceback or the log.
- **T9 declines.** `group_by`, `when:`, `preserve_values`, `date64` resident under a `DATE` shape: each declines with its code from section 3 and runs on the oracle with today's output (control for the oracle half).
- **T10 non-date cells on the oracle.** A `DATE`-shaped object column holding a `date`, a `datetime`, a string `"x"`, an int and a null: the `date` and the `datetime` (by its date) shift; `"x"` and the int are `format_error` row errors that keep the source; the null stays null. Equal to today's oracle output for the same column. Control: passes before and after.
- **T11 one resident-domain descriptor.** In existing `tests/native/test_operator_registry.py` and `tests/sentry/test_operator_registry_sentry.py`, enumerate every operator and the default, positional, and deterministic parameter modes. Assert the new descriptor admits exactly the pre-change resident types for every existing cell, with only `date_shift/date32` added in S1 and zoned timestamps added in S2; naive timestamps and all other temporal types decline. Assert `OperatorSpec` has none of the three old fields and `_unified_slice_admission.py` contains one descriptor admission call rather than route-specific type tables. Mutations restoring an old field, a direct `date_shift` predicate, or a naive-timestamp admission turn it red.
- **S sentry.** `test_date_shift_one_arithmetic.py` passes and fails on each seeded case.

Mutations (record the head they ran on): off-by-one on the upper date bound (T1 red); key on the raw int32 day number (T2, T3 red); replace Euclidean quotient/remainder with truncation toward zero (T2 negative-fraction cells red); delete the preflight before an Arrow floor/format/timezone/add operation (T2 or T6 red); overlap rule replaced by plain `earliest` (T4 red on overlap cells where the source was standard time).

Performance evidence (performance.md): 1,000,000-row `date32` and `timestamp[us, UTC]` columns, oracle before and native after, three runs each on the Dell node through `vm-run`; record wall time, peak RSS, and the split of key formatting against HMAC. Numbers go in the PR bodies.

## 10. Frozen contracts and compatibility

- **Byte changes, marked:** B2 (overlap rule, typed and text zoned sources), B4 (out-of-range as row error), B5 (unified output and metadata). B1 is a guarantee with no expected byte change; T5 proves it. Recorded in `docs/compatibility-contract.md` under ROUTE-OUTPUT-CONTRACT and the date_shift entry.
- S1 fragment first line: `Breaking: date_shift on a date column runs natively; a date outside years 1 to 9999 is a row error that keeps the source instead of failing the job.`
- S2 fragment first line: `Breaking: date_shift on a zoned timestamp runs natively, and an ambiguous local time after the shift keeps the source UTC offset when it can (text and typed sources).`
- The `_chunked_schema_rule.py` statement "date_shift output is always `string`" (line 18) becomes "text sources give `string`; typed sources keep their type".
- Offsets and key bytes: unchanged for every usable row (T1, T2); newly rejected extreme rows previously failed the job and now have no key. `SEED_PROTOCOL_VERSION` is not touched. Plan digest: the params gain `shape`, which is derived from the plan, not serialized config; the builder confirms the plan digest does not move.

## 11. Pre-mortem

- `strftime` zero-pads years below 1000 on Linux (probed). T2 runs on the Mac node too; if it fails there, the key builds the year with `pc.utf8_lpad` over the integer year.
- `pc.local_timestamp`, `assume_timezone`, and `strftime` can behave differently across pyarrow versions. The builder runs T2, T4, and T6 on the lowest pinned pyarrow in CI as well as the current one.
- The oracle change (B2) moves output for some rows already masked. Pre-V1, allowed by the owner direction; named in the Breaking line.
- The sequential route has its own date_shift seam (called only when shape is None today). The builder confirms the sequential native op reads the same config rejection, so a typed column is not admitted on one route and declined on another; T3 covers it.
- UF-DOMAIN S1 is not merged when S1 here starts. This plan does not start before it; the `arrow_columns` input is a hard dependency.

## 12. Open questions for the owner

- **Q1.** The B2 overlap rule changes oracle output where a zone's base offset changed between the source and target dates. Recommended: accept (one rule on both routes, vectorized). T4 reports the count of changed cells before merge.

## 13. Revision 4 (2026-11-24): one source-read boundary

Revision 5 (section 14) replaces 13.3, 13.4, 13.5, 13.6 placement and 13.9, removes WITHHOLD and its tokens, and corrects the base of the site inventory. Read section 14 first.

PR #790 (S1, head `a5c33ec0a`) reached the three-round review cap (development-loop REMEDIATE). Round 3 (Codex a3) found four more V1 sites of one rule: a source value pandas cannot hold (a date past year 9999, a time with non-zero nanoseconds) must never surface as text. Rounds 1 to 3 each closed the sites that review found. This section fixes the plan instead: one choke point for every Arrow-to-pandas conversion and every pandas file read, a guard that fails on any site outside it, and a report-boundary rule for the columns the choke point could not convert.

### 13.1 Defect class

- Primary: cross-cutting-concerns.md, missing policy enforcement point (shotgun surgery). `profile/_frame.py` `profile_frame` was the "helper every site is expected to call" that the rulebook calls the convention form: nothing failed when `_chunked_profile.py` or the cloud readers skipped it. Fix: choke point plus guard test with a ratchet allowlist.
- recurring-defects #5, normalized guard scanners: the S1 sentries matched only positional arguments and literal import spellings.
- recurring-defects #10, allowlisted helpers are still checked: the new guard names the choke point by exact `(path, function)`, so a second function in the same module is not exempt.
- recurring-defects #3, exception context: the V2-LOG item stays deferred (see Deferred). The new choke point raises after its `except` block closes because it is new code, but this is not a gate item for this revision.

### 13.2 Guarantee and non-goals of this revision

Guarantee: no Arrow-to-pandas conversion and no pandas file read of source data or of a table derived from it (masked output, sample, chunk, index columns) runs outside the choke point. At the choke point a column that pandas cannot convert either (a) is withheld: its cells become value-free tokens and the frame names it, or (b) raises the caller's coded error that names the column and no value. No pandas or Arrow error text from a conversion reaches a caller.

Non-goals, each recorded in Deferred:

- Python-object conversion (`to_pylist`, `as_py`, `to_pydict`, `to_numpy().tolist()`): 86, 26, 0 and 3 call sites in `src/` at `a5c33ec0a`, mostly on arrays already admitted as string or numeric. Not walked by the new guard. The public-entry matrix (R2) is the evidence that no reachable path converts an out-of-range temporal value this way.
- Deliberate scanner evasion (`getattr(t, "to_pandas")`, `eval`, `importlib`): catalog #5 scope.
- Arrow-native reads (`pq.read_table`, `pyarrow.csv.read_csv`, `pq.ParquetFile.iter_batches`): they do not convert to Python or pandas and do not fail on these values. They feed the choke point.

### 13.3 The choke point

`internal/pandas_compat.py` (181 lines today, an existing module that already owns `table_to_pandas_exact_ints`, the engine's Arrow-to-pandas conversion with exact integers). Public names:

- `source_frame(table, *, on_unrepresentable, int_columns=(), types_mapper=None) -> pd.DataFrame`
- `source_series(array, *, on_unrepresentable, types_mapper=None) -> pd.Series`
- `WITHHOLD`: the sentinel policy value.
- `unrepresentable_columns(frame) -> frozenset[str]`: the reader for the identity the choke point records.

`on_unrepresentable` is keyword-only and required: either `WITHHOLD` or a callable `(column_name) -> NoReturn` that raises the caller's coded error. There is no "propagate" option. `table_to_pandas_exact_ints` becomes a call to `source_frame` (its `on_unconvertible` integer callback is kept), so `to_pandas_fk_safe` and `generated_table_to_pandas` go through the choke point with no further change to their callers' conversion code.

Algorithm:

1. Try `table.to_pandas(...)` once. On success, set `frame.attrs[UNREPRESENTABLE_ATTR] = ()` and return. The success path costs one `try`.
2. On `ValueError` or `OverflowError` (`ArrowInvalid` is a `ValueError`), leave the handler, then probe each column alone. A column whose own conversion raises is a failing column.
3. With a callable policy: call it with the first failing column's name, after the handler has closed. The callable must raise. If it returns, the choke point raises a value-free `TypeError("on_unrepresentable must raise")`.
4. With `WITHHOLD`: replace each failing column on the original table with `table.set_column(i, table.schema.field(i).with_type(pa.string()), tokens)`. This keeps the schema metadata and the field metadata (probed at pyarrow 24.0.0: a table with a stored index `stored_id`, a `date32` column at year 10000 and a `timestamp[ns, Europe/London]` column, each replaced in turn, still converts with index `stored_id` and the same data columns). Never rebuild the table from arrays and names.
5. Tokens: for a temporal column, view the cells as their physical integer (`date32` to `int32`; `date64`, `timestamp`, `time64`, `duration` to `int64`) and map each distinct non-null integer to `"withheld:" + blake2b(value bytes, key=process key, digest_size=8).hexdigest()`. The key is 16 random bytes made once per process and never written. Nulls stay null. Equal values give equal tokens and distinct values give distinct tokens, so null counts, distinct counts and source-versus-output equality (fidelity and post-mask comparisons) stay correct within one run. No calendar text is formed. A non-temporal failing type (none known today) gets one constant token per non-null cell. The hashing loop runs only on a column that failed conversion.
6. Set `frame.attrs[UNREPRESENTABLE_ATTR]` to the sorted failing column names. pandas carries `attrs` through `iloc` slicing and column selection; R1 asserts this for every operation between a reader and its consumer.

Two layers hold the guarantee. The tokens make the frame value-free by construction, so a consumer that loses the `attrs` identity can show a meaningless token but not a value. The identity lets the report boundary say why a column's statistics are missing.

Placement. `profile/_frame.py` is deleted, so `profile/` goes back to 19 direct modules (Codex a3 DESIGN). Codex suggested the profile reader module. `internal/` is used instead because execution, verification and generation callers need the same function, and `internal/pandas_compat.py` already owns this conversion. No new module and no new public export from `decoy_engine` or `decoy_engine.profile`.

### 13.4 Site dispositions

Found by an AST walk of `src/decoy_engine/**/*.py` at `a5c33ec0a` (calls whose attribute is `to_pandas`, and calls or references that resolve to `pandas.read_*`), then checked by reading each site. The R4 guard repeats this walk on every run; the table is the starting state, not the guard's input.

| # | Site (at `a5c33ec0a`) | What it converts | Disposition |
|---|---|---|---|
| 1 | `execution/_chunked_profile.py:45` `walk_one_table` | first source chunk | `source_frame(WITHHOLD)` (Codex a3 V1-1) |
| 2 | `execution/_chunked_profile.py:171` `empty_input_profile` | empty table from the source schema | `source_frame(WITHHOLD)`; no values, routed so the allowlist stays empty |
| 3 | `execution/_pipeline_finalize.py:186` `compute_fidelity_reports` | source table | `source_frame(WITHHOLD)` |
| 4 | `execution/_pipeline_finalize.py:187` | masked output (keeps out-of-range source cells as row errors) | `source_frame(WITHHOLD)` |
| 5 | `execution/pipeline/_post_scan.py:285`, `:435` | source tables | `source_frame(WITHHOLD)` |
| 6 | `execution/pipeline/_post_scan.py:286`, `:436` | masked outputs | `source_frame(WITHHOLD)` |
| 7 | `verification/postmask/_column_facts.py:209` `_series` | source and output batches | `source_series(WITHHOLD, types_mapper=exact_int_types_mapper)` |
| 8 | `execution/pipeline/_source_types.py:64` `_expected_index` | stored index columns of a source | `source_frame` with the caller's coded callback |
| 9 | `execution/_unified_slice_evidence.py:228` | an empty masked column | `source_series` with a coded callback; no values |
| 10 | `execution/native/_date_shift_ext.py:270` | string column (admission) | `source_series` with a coded callback |
| 11 | `execution/native/_bucket_perturb_ext.py:100`, `:277` | string column (admission) | `source_series` with a coded callback |
| 12 | `execution/native/_operator_step.py:279` `_preserved_mask` | string column (`preserve_values` is string-only) | `source_series` with a coded callback |
| 13 | `execution/out_of_core/_bucket_native.py:263` | string column | `source_series` with a coded callback |
| 14 | `execution/out_of_core/_mask_group_c.py:537` `_to_series` | single string column | `source_series` with a coded callback |
| 15 | `internal/pandas_compat.py:95`, `:101` `table_to_pandas_exact_ints` | every execution ingest through `to_pandas_fk_safe` (10 call sites: `_transforms_table.py:72`, `_chunked_carry.py:143`, `_pipeline_full_frame.py:81`, `_unified_slice_admission.py:347`, `_sequential.py:415`, `_pandas_adapter.py:205`, `_mixed_fk_bridge.py:264`, `native/_group_key_kernel.py:173`, `native/_faker_null_mask.py:44`, `native/_when_mask.py:58`) and `generation/_numeric_typing.py:417` | becomes the choke point body. `to_pandas_fk_safe` gains a required keyword `table_name` and passes a callback that raises `ExecutionError` `full_frame_value_unrepresentable` naming table and column. `_raise_if_source_value_unrepresentable` (`_pipeline_full_frame.py:56`, called at `:234` and `_sequential.py:419`), which re-converted each column after the fact to find the offender, is deleted |
| 16 | `profile/_frame.py:19`, `:24`, `:28` | S1's helper | deleted; its callers (`profile/_readers.py:415`, `:496`, `:500`, `profile/_readers_resident.py:34`, `:37`) call `source_frame(WITHHOLD)` |
| 17 | `profile/_cloud_readers.py:270` S3 `to_frame`, `:391` GCS `to_frame` | whole Parquet object, `residency="full"` | `pq.read_table(io.BytesIO(data))` then `source_frame(WITHHOLD)` (Codex a3 V1-2). The sample path (`_read_parquet_sample`, `:109`) already goes through `head_frame_from_batches` |
| 18 | `profile/_cloud_readers.py:145`, `:318`, `:438` | CSV bytes, `pd.read_csv` with lexeme options | allowlisted with reason: a CSV text parse with no Arrow temporal conversion. Moving cloud CSV onto `_csv_reader._read_csv_rows` is a separate change |
| 19 | `fileaccess/adapters/pandas.py:23`, `:37`, `:44` (`pd.read_csv` references) | the file-access guard wrappers that the one CSV reader calls | allowlisted with reason; their callers are scanned (catalog #10): only `profile/_csv_reader.py` may call `read_csv*` adapters |
| 20 | `fileaccess/adapters/pandas.py:28` (`pd.read_parquet` reference) | guard wrapper with no `src/` caller (tests and `tests/sentry/file_access_registry.toml` use it) | allowlisted with reason; the guard fails on any `src/` caller of `fileaccess.adapters.pandas.read_parquet` |

Arrow-native reads seen by the walk and left alone (non-goal, 13.2): `execution/_isolated_worker.py:111`, `execution/_isolated_commit.py:218`, `profile/_readers.py:371`, `generation/kinds/_lookup.py:187`, `reference_tables/_loader.py:112`, `transforms/_codeset_loader.py:456`, `vault/_format.py:269` (`read_table`), and `io/bounded_reader.py:365` (`pyarrow.csv.read_csv`).

Starting allowlist: 7 entries (rows 18 to 20). It is a ratchet: it may shrink and never grows without a reviewed change (catalog #11).

### 13.5 Report boundary for withheld columns

- `FieldStats` (`profiling/types.py`) gains `source_value_unrepresentable: bool = False`, classified in `VALUE_FREE_FIELDS` (`profiling/_value_redaction.py`), so the existing type walk accepts it.
- `profile_columns` (`profiling/profiler.py:308`) reads `unrepresentable_columns(df)`, sets the flag, and does not compute value-bearing statistics for a flagged column. Null and distinct counts stay.
- `is_value_sensitive` (`_value_redaction.py:441`) returns True for a flagged field. `redact_profile_dict` and `profile_document` then remove `mode_value`, `top_values`, `distribution`, samples, `min` and `max` for it by the existing `VALUE_FIELDS` rules. A flagged field is redacted with `include_values=True` too: its cells are tokens, so there is nothing to show.
- Fidelity (`quality/report.py` `compute_quality_report`) and post-mask (`verification/postmask/runner.py` `run_post_mask`) need no new code: their frames hold tokens. R2 proves their outputs carry no literal.

### 13.6 Guard test

New `tests/sentry/test_source_read_boundary.py`, registered in `scripts/dev/sentry_registry.toml`. It reuses `walk_with_scope`, `dotted`, `package_of`, `import_bindings` and `canonical` from `tests/sentry/_retry_scan.py` (the existing resolver). It does not copy them.

Covered shapes (catalog #5, listed before building):

- any `X.to_pandas(...)` call, any receiver, positional or keyword arguments;
- the unbound form `pa.Table.to_pandas(t)` and `to_pandas` passed as a value (`map(pa.Table.to_pandas, ts)`, `fn=t.to_pandas`);
- `pandas.read_*` reached as `pd.read_x`, `pandas.read_x`, an aliased module import (`import pandas as p`), `from pandas import read_x [as y]`, `pandas.io.parquet.read_parquet`, or a relative import, each called or passed as a positional or keyword argument value;
- calls to `decoy_engine.fileaccess.adapters.pandas.read_parquet` or `read_csv*` from any module other than the allowlisted callers.

Exempt by exact `(path, function)`: `internal/pandas_compat.py` `source_frame`, `source_series` and their one private conversion helper. A call in any other function of that module is a violation.

The allowlist holds `(path, function, canonical target, reason)`. A stale entry fails the test.

### 13.7 DESIGN fixes on #790

- D1. `tests/sentry/test_typed_date_shapes_one_set.py` `_composed_views` (line 154): resolve the callee with `canonical(dotted(node.func), import_bindings(tree, package_of(rel)))` and check both `node.args` and `node.keywords` values for the view parts, resolved the same way.
- D2. `tests/sentry/test_public_import_boundary.py` `_private_canonicalize_imports` (line 164): resolve imports with `import_bindings(tree, package_of(rel))`, so `from decoy_engine.generation.pool import _canonicalize as c`, `import decoy_engine.generation.pool._canonicalize as c` and relative forms all resolve to the private module before the allowlist check.
- D3. `tests/native/test_date_shift_typed_declines.py:199`: replace the `inspect.getsource` substring check with a behavior probe. Monkeypatch `wa.when_target_rejection` to return a sentinel, call `when_native_rejection` with a `when:` entry and a schema where the target column is `pa.date32()` (a known type, so the missing-schema branch does not run), and assert the sentinel comes back. This is the same probe the test already uses for the sequential admit.

### 13.8 Acceptance tests (each fails before the change unless marked)

- **R1 choke point.** New `tests/unit/internal/test_source_frame.py`.
  - Control (passes before and after): for a corpus of every Arrow type the profile and execution readers produce, `source_frame(t, on_unrepresentable=WITHHOLD)` equals `t.to_pandas()` (frame, dtypes and index) and `unrepresentable_columns` is empty.
  - Withhold: one table each with `date32` at year 10000, `date64` past year 9999 and `time64[ns]` with a non-zero nanosecond (probed: pyarrow raises `ArrowInvalid: Value 1 has non-zero nanoseconds`). Each as one row and as 20 equal rows plus a null. No exception. Failing cells are `withheld:` tokens: equal values give one token, distinct values give distinct tokens, nulls stay null. Other columns equal their own bare conversion. `unrepresentable_columns` names exactly the failing columns. No cell, attr or column name contains `10000`, `2932897` or the nanosecond value.
  - Metadata: stored index `stored_id`, a `timestamp[ns, Europe/London]` column and a range index. Index and data columns after fallback equal those of the same table with the bad cell set to an in-range value.
  - Callback policy: the callback receives the column name. The coded error's `str`, `repr` and formatted traceback carry no value. A callback that returns gives the value-free `TypeError`. Calling without `on_unrepresentable` is a `TypeError`.
  - `attrs` survival: `iloc[:n]` and column selection keep the identity.
  - Mutations that must turn R1 red: rebuild the table with `pa.Table.from_arrays` (metadata cell); cast the column to `string` instead of tokens (no-literal cell); unkeyed token `str(int)` (no-day-number cell); catch only `ValueError` (no: `OverflowError` cell, from an out-of-range `date64`).
- **R2 public-entry matrix.** New `tests/integration/test_unrepresentable_source_values.py`, Parquet sources with a `date32` year-10000 cell, a `time64[ns]` cell and a passthrough column. Each cell asserts it completes or fails with a coded error, and that `str`, `repr`, the traceback, `caplog`, the returned documents and the written output carry no `10000-01-01`, `10000` or `2932897`.
  - `run_mask_chunked` with the bad cell in the first chunk and in a later chunk, with a `date_shift` target and as a passthrough column (Codex a3 V1-1). Before #790 lands the outcome is a coded error or a decline to the oracle. After #790, T8 pins the `format_error` row.
  - `run_mask` on sequential and full_frame: coded `full_frame_value_unrepresentable` with table and column named, now raised at the choke point.
  - Profile with `residency="full"` and with sampling: local Parquet, S3 and GCS readers with transport mocked and real Parquet bytes (Codex a3 V1-2).
  - Scan: default `profile_document`, `include_values=True`, and the raw `to_dict()` (Codex a3 V1-3).
  - `fidelity_report=True` and post-scan integrity requested.
  - Fail-before: chunked, both cloud readers and scan cells are red on `origin/main` and on `a5c33ec0a`.
- **R3 report boundary.** In the existing `tests/profiling/` value-redaction suite: column `d` with 20 equal out-of-range dates, and a singleton. `source_value_unrepresentable` is true. `mode_value`, `top_values`, `distribution`, samples, `min` and `max` are absent or empty in `profile_document` in both modes. Null and distinct counts are right. With a stored index, the profile's data columns before and after the fallback are both `['d']` (Codex a3 V1-4). Mutations: `is_value_sensitive` ignores the flag (default-mode cell red); `profile_columns` ignores `unrepresentable_columns` (flag cell red).
- **R4 guard.** `test_source_read_boundary.py` passes on the tree. Seeded cases in a scratch module, each red: aliased module import, `from pandas import read_parquet as rp`, `pd.read_parquet` passed as a keyword argument value, unbound `pa.Table.to_pandas(t)`, `t.to_pandas(types_mapper=m)`, a relative import of the choke point's private helper, and a new function in `internal/pandas_compat.py` that calls `to_pandas`. Real-caller mutations, each red: restore `table.to_pandas()` in `walk_one_table`; restore `pd.read_parquet(io.BytesIO(data))` in the GCS `to_frame`. Walk proof: the count of matched sites equals the 7 allowlisted entries, rises by one per seed, and a removed allowlisted site makes the stale-entry check red.
- **R5 DESIGN (#790).** D1 seeds against the real caller `execution/_chunked_bucket_perturb.py`: `native_date_shapes(shapes=plan_column_shapes(plan), declared=declared_date_shift_columns(plan))` and the same call through an aliased import; both red. D2 seeds against a real `execution/` caller: `from decoy_engine.generation.pool import _canonicalize as c`, `import decoy_engine.generation.pool._canonicalize as c` and a relative form; all red. D3 mutation: add a separate known-target check in `when_native_rejection` before the shared helper call; red.
- **R6 placement.** No test. `profile/_frame.py` deleted, no new module, `internal/` count unchanged. The reviewer checks the diff.

Mutations are rerun on the final head of each slice and that head is recorded (catalog #9).

### 13.9 Slice decision and size

The class exists on `origin/main` today. A `date32` year-10000 source already raises `year 10000 is out of range` through `walk_one_table`, the cloud full readers and fidelity, with no `date_shift` in the config. So the boundary is not part of DATE-SHIFT-TYPED and does not belong on #790.

New slice **S1b SOURCE-READ-BOUNDARY**, from `origin/main`, its own PR to `main` (not stacked on #790, so it cannot strand on a non-main base). Risk R2 (value-free guarantee on every source read). Plan gate: this section. Code gate: Codex and Dennis.

| Part | Lines (estimate) |
|---|---|
| `internal/pandas_compat.py` choke point | +110 / -20 |
| sites 1 to 17 and the 10 `to_pandas_fk_safe` callers | +70 / -40 |
| delete `_raise_if_source_value_unrepresentable` and its two calls | -40 |
| `profiling/types.py`, `_value_redaction.py`, `profiler.py` | +25 |
| changelog fragment, sentry registry row | +10 |
| tests R1 to R4 | +560 |
| **Total** | about 875 changed lines |

That is above the 600-line limit for adding to #790, which is already 2,188 / -299. S1b merges first. Then #790 rebases on `main`, deletes `profile/_frame.py` and points its readers at `source_frame`, and adds D1 to D3 (R5): about +100 / -60 on #790. #790's T8 cells then pass through the S1b choke point unchanged. Codex reviews S1b in full and the #790 delta as a delta.

If the S1b build passes 1,000 lines, the builder stops and reports (proportionality.md) instead of carrying it to review.

## 14. Revision 5 (2026-11-24): Dennis R1 fixes to the source-read boundary

Dennis R1 on revision 4 (`8428fc973`) was GO-WITH-FIXES: 0 BLOCKER, 4 HIGH, 6 MED, 3 LOW. Where this section and section 13 differ, this section wins. Section 13 stays as the record of revision 4.

Probes for this section ran once with the engine venv (`python -I`, pyarrow 24.0.0, pandas 2.3.3). Base for S1b: `origin/main` at `4bc582d0a`.

### 14.1 H4 decision: widen dates and times to a lossless pandas type, no tokens

Choice: Dennis option (b), extended to time columns. WITHHOLD and its tokens are removed from the plan.

Probe results:

- `to_pandas(date_as_object=False)` converts `date32` and `date64` to `datetime64[ms]` with no loss over the whole `date32` range: day -1000000 gives `-768-02-04`, day 2932897 gives `10000-01-01`, and day 2**31-1 gives `5881580-07-11`. The default conversion raises `ValueError: year 10000 is out of range` (and `year -768 is out of range`).
- `time64[ns]` with a non-zero nanosecond has no `to_pandas` option that works (`ArrowInvalid: Value 1 has non-zero nanoseconds`), and Arrow has no `time64` to `duration` cast. `array.view(pa.int64()).cast(pa.duration("ns")).to_pandas()` gives `timedelta64[ns]` (time since midnight) with no loss.
- `timestamp[s]` and `duration[s]` at 2**62 already convert (to `datetime64[s]` and `timedelta64[s]`); they need nothing.
- Risk check: `astype("datetime64[ns]")` on the widened column raises `OutOfBoundsDatetime: Out of bounds nanosecond timestamp: 10000-01-01 00:00:00` (value text). `pd.to_datetime(series, errors="coerce")` on a `datetime64[ms]` series keeps `ms` and does not raise. The three `to_datetime` sites in profiling at `4bc582d0a` (`profiling/_date_sniff.py:31`, `profiling/_distributions.py:105`, `profiling/sentinels.py:157`) all use `errors="coerce"`.

Why (b):

- The column keeps its meaning: real dates and times in a temporal dtype. A token column profiled as a 25-character string, ran detectors and models on hashes, could trip the free-text advisory, and made fidelity call it categorical (H4). With (b) none of that happens, so the per-consumer skip rules of option (a) are not needed.
- No new value-bearing path is opened. The widened values follow the existing report rules for any date column (`VALUE_FIELDS`, default redaction).
- M3 (token key scope, logical-type hashing, `top_values` stripping) no longer applies because there are no tokens. The paired-conversion part of M3 stays (14.4).
- The ns-cast risk is guarded by a rule and a sentry (14.5).

Rule: a column is "widened" only when its Arrow type is `date32`, `date64` or `time64[ns]` and its own default conversion fails. Columns that convert normally keep their normal dtype (`object` of `datetime.date` for dates), so profiles of in-range data do not change. Any other failing column goes to the caller's coded callback. No case falls back to text.

### 14.2 The choke point (replaces 13.3)

Module: `internal/pandas_compat.py` (unchanged). Names (L1: `source_frame` clashed with `candidate.source_frame`):

- `arrow_to_frame(table, *, on_unrepresentable, widen=False, int_columns=(), types_mapper=None) -> pd.DataFrame`
- `arrow_to_series(array, *, on_unrepresentable, widen=False, types_mapper=None) -> pd.Series`
- `arrow_to_frame_pair(source, output, *, on_unrepresentable, widen=True, ...) -> tuple[pd.DataFrame, pd.DataFrame]`
- `widened_columns(frame) -> Mapping[str, str]`: column name to original Arrow type string, read from `frame.attrs["decoy_engine.widened_columns"]`.

`on_unrepresentable` is keyword-only and required: a callable `(column_name) -> NoReturn`. Every callback raises a registered coded error `from None` and names the column, never a value. The choke point calls it after the `except` block has closed, so `__context__` is `None` as well as suppressed. A callback that returns gives a value-free `TypeError("on_unrepresentable must raise")`.

`widen=True` is allowed only for read-only consumers (profile, scan, fidelity, verification). Execution callers keep `widen=False`: they write frames back to Arrow, and `pa.Table.from_pandas` of a widened `date32` column gives `timestamp[ms]`, not `date32` (probed), which would change the output type. On those routes an unconvertible column stays a coded error, as guarantee 6 says.

Algorithm:

1. Try `table.to_pandas(...)` once. On success set `widened_columns = {}` and return.
2. On `ValueError` or `ArrowInvalid` (a `ValueError` subclass), leave the handler and probe each column alone. `OverflowError` is still caught for safety but is not claimed by any test (14.8, M2).
3. For each failing column: with `widen=True` and a widenable type, replace it on the original table by its widened conversion (dates through `date_as_object=False` on a one-column table; `time64[ns]` through the `int64` view and `duration[ns]`), keeping schema and field metadata, the stored index and column order (`set_column`, never `from_arrays`). Otherwise call `on_unrepresentable(column)`.
4. Record `{column: str(arrow_type)}` in `attrs`.

`table_to_pandas_exact_ints` becomes a call to `arrow_to_frame(widen=False)`. Its `on_unconvertible` integer callback is kept.

Public export (H2): `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` and `widened_columns` are exported from `decoy_engine` with an entry in `docs/compatibility-contract.md` marked pre-release, not frozen. "No new public export" in 13.3 is withdrawn. The engine re-pin for the CLI follows the engine repin checklist.

### 14.3 Site inventory at the S1b base (replaces 13.4, H1)

From `git grep` at `origin/main` `4bc582d0a` over `src/decoy_engine/**/*.py`, then read site by site. Comment and docstring hits are dropped (`config/_fixed_width.py:13`, `_chunked_fk_runtime.py:112`, `_fk_keys.py:434`, `_mask_group_c.py:530-531`, `_numeric_typing.py:412`, `pandas_compat.py:88`, `profile/_csv_reader.py:530`, `_fixed_width_reader.py:12-181`, `_readers.py:382`, `_readers_csv.py:40`).

| # | Site at `4bc582d0a` | Converts | S1b slice | Disposition |
|---|---|---|---|---|
| 1 | `profile/_readers.py:414` `to_frame` | whole local source | S1b-2 | `arrow_to_frame(widen=True)`, profile callback |
| 2 | `profile/_readers.py:495` | empty table from schema | S1b-2 | same |
| 3 | `profile/_readers.py:499` head frame | sample batches | S1b-2 | same |
| 4 | `profile/_readers_resident.py:20`, `:25`, `:29` `_frame_of` | resident sources; already has the string cast and `from_arrays` fallback (Codex V1-3 and V1-4 are on main) | S1b-2 | body deleted; calls `arrow_to_frame(widen=True)` |
| 5 | `profile/_cloud_readers.py:270` S3, `:391` GCS `to_frame` | whole Parquet object | S1b-2 | `pq.read_table(io.BytesIO(...))` then `arrow_to_frame(widen=True)` |
| 6 | `execution/_chunked_profile.py:45`, `:171` | first chunk, empty schema table | S1b-2 | `arrow_to_frame(widen=True)` |
| 7 | `execution/_pipeline_finalize.py:186`, `:187` fidelity | source, output | S1b-2 | `arrow_to_frame_pair(widen=True)` |
| 8 | `execution/pipeline/_post_scan.py:285-286`, `:435-436` | source, output | S1b-1 | `arrow_to_frame_pair`, fail-closed callback (14.4) |
| 9 | `verification/postmask/_column_facts.py:209` `_series` | source, output batches | S1b-1 | `arrow_to_series`, fail-closed callback (14.4) |
| 10 | `execution/pipeline/_source_types.py:60` | stored index columns | S1b-1 | `arrow_to_frame(widen=False)`, coded callback |
| 11 | `execution/_unified_slice_evidence.py:218` | empty masked column | S1b-1 | `arrow_to_series`, coded callback |
| 12 | `execution/native/_date_shift_ext.py:209`, `_bucket_perturb_ext.py:100`, `:277`, `_operator_step.py:279`, `out_of_core/_bucket_native.py:263`, `out_of_core/_mask_group_c.py:537` | string-typed kernel arrays | S1b-1 | `arrow_to_series`, coded callback |
| 13 | `internal/pandas_compat.py:95`, `:101` | `to_pandas_fk_safe` (10 callers) and `generated_table_to_pandas` | S1b-1 | choke point body. `to_pandas_fk_safe(table, cols, *, table_name)` |
| 14 | `profile/_cloud_readers.py:145`, `:318`, `:438` | CSV text | allowlist | reason: text parse, no Arrow temporal conversion |
| 15 | `fileaccess/adapters/pandas.py:23`, `:28`, `:37`, `:44` | file-access guard wrappers | allowlist | reason: wrappers; their `src/` callers are scanned |

Allowlist count: 7 at `4bc582d0a`. The ratchet baseline is the count the guard measures on the S1b-1 base, recorded in the guard file with that SHA. It may only go down. A change that raises it fails the guard unless the same diff lowers the recorded baseline's reviewer-signed entry list, which the guard does not allow to grow (M6). The count is never set to fit S1b's own sites: S1b-1 routes its sites, it does not allowlist them.

#790 delta (applied when #790 rebases on S1b-2):

| Site on #790 (`a5c33ec0a`) | Disposition |
|---|---|
| `profile/_frame.py:19`, `:24`, `:28` (new on #790) | file dropped in the rebase; its callers take the S1b-2 calls |
| `profile/_readers.py:415`, `:496`, `:500`, `_readers_resident.py:34`, `:37` (moved lines) | already routed by S1b-2; rebase keeps main's version |
| `execution/native/_date_shift_ext.py:270` (moved from `:209`) | keeps the S1b-1 call |
| `execution/_unified_slice_evidence.py:228` (moved from `:218`) | keeps the S1b-1 call |
| `_raise_if_source_value_unrepresentable` calls added on #790 | removed in the rebase (14.6) |

Allowlist count on #790 after rebase: 7, the same as main. The guard runs on #790 and fails on any new bare site.

### 14.4 Verification fails closed (H3)

Post-scan (site 8) and post-mask (site 9) never inspect a stand-in for a value.

- They call `arrow_to_frame_pair` / `arrow_to_series` with `widen=True`. A widened date or time is the real value, so identity and distinct checks still inspect it.
- `arrow_to_frame_pair` widens the union of the columns widened on either side, on both sides (M3). Without it, a source `date32` at year 10000 widens to `datetime64[ms]` while the in-range output stays `datetime.date` objects, and pandas `==` across the two is always False, which reads as "changed" and passes an identity check that should fail.
- Any column that cannot be converted goes to a fail-closed callback. Post-mask sets `identity_error` and `distinct_error` on that column's tally (`_column_facts.py:179-180`) to the new registered reason `postmask_column_not_inspectable`, and the gate result fails. Post-scan raises the new registered reason `post_scan_column_not_inspectable` naming table and column. Neither returns a pass for that column.

### 14.5 Rules and guard for widened columns

- Rule W1: no code in `profile/`, `profiling/`, `quality/`, `verification/` or `execution/pipeline/_post_scan.py` casts to nanosecond time (`datetime64[ns]`, `M8[ns]`, `timedelta64[ns]` on a widened column, `.as_unit("ns")`, `pd.to_datetime(..., unit=...)` without `errors="coerce"`). The guard (14.7) adds these spellings for those packages.
- Rule W2: `profile_columns` reads `widened_columns(df)` and sets the existing inferred type from the Arrow type (`date` for `date32`/`date64`, `time` for `time64`), not from the pandas dtype. `FieldStats` gains `source_arrow_type: str | None` in `VALUE_FREE_FIELDS` (an Arrow type string carries no value). It replaces the `source_value_unrepresentable` flag of 13.5; there is no special redaction rule, because the values are real and the normal date rules apply.
- Rule W3: `widened_columns` must survive every frame operation between a reader and its consumer. The R1 cells (14.8) list them. Where an operation drops `attrs` (pandas `concat` of frames with different `attrs`), the consumer re-reads it from the reader's frame before the operation.

### 14.6 Deletion and reason code (L3)

`execution/_pipeline_full_frame.py` `_raise_if_source_value_unrepresentable` (main `:56-95`, called at main `:234` and on #790 also at `_sequential.py:419`) is deleted in S1b-1. `to_pandas_fk_safe(..., table_name=...)` raises at the conversion instead. The reason code `FULL_FRAME_VALUE_UNREPRESENTABLE` (`reasons/runtime/_part1.py:203`) is kept and is now raised only from the `to_pandas_fk_safe` callback. Its text does not change.

### 14.7 Guard placement and shapes (replaces 13.6 placement, M5)

| Item | Path |
|---|---|
| choke point | `src/decoy_engine/internal/pandas_compat.py` (existing) |
| engine guard | `tests/sentry/source_read/test_boundary.py` (new sub-package; flat `tests/sentry/` has 100 modules) |
| guard allowlist | `tests/sentry/source_read/allowlist.toml` |
| R1 unit tests | `tests/unit/internal/test_arrow_to_frame.py` |
| R2 integration | `tests/integration/source_read/test_unrepresentable_values.py` (new sub-package) |
| R3 profile cells | existing `tests/profiling/` value-redaction suite |
| CLI guard | `tests/sentry/test_source_read_boundary.py` in the CLI repo, or its sentry sub-package if one exists at the slice base |

Shapes: as 13.6, plus the W1 ns-cast spellings for the listed packages, plus `S3` and `GCS` real-caller mutations (14.8 R4).

### 14.8 Acceptance test changes

- R1 (S1b-1 and S1b-2):
  - Callback cells (S1b-1): `date32` year 10000 with `widen=False` calls the callback with the column name; the coded error has `__cause__ is None`, `__context__ is None` and `__suppress_context__`; `str`, `repr` and the formatted traceback carry no `10000`, `2932897` or `-768`.
  - `time64[ns]` cell: `ArrowInvalid` path, same assertions (M2).
  - Widen cells (S1b-2): `date32` at days -1000000, 2932897 and 2**31-1, `date64` past 9999, and `time64[ns]` with nanoseconds, each single and repeated with a null: the result is `datetime64[ms]` or `timedelta64[ns]` with exact values, other columns equal their own conversion, `widened_columns` names the Arrow type. Stored index `stored_id`, a `timestamp[ns, Europe/London]` column and the range index are kept.
  - `attrs` cells (M4): `iloc[:n]`, column selection, `sample(n, random_state=0)` and `reset_index()` keep `widened_columns`; `concat` of two frames with the same `attrs` keeps it; `concat` with different `attrs` drops it (pandas 2.3.3 behavior, asserted so a pandas change is seen), which is why W3 re-reads.
  - Pair cell: source year-10000, output in range: both sides of `arrow_to_frame_pair` are `datetime64[ms]` and `==` is True on unchanged rows.
  - Mutations: `from_arrays` rebuild (index cell red); widen every date column instead of failing ones only (in-range dtype cell red); pair without the union (pair cell red); drop `from None` (context cell red).
  - The revision-4 `OverflowError` mutation is dropped. No `to_pandas` call on these types raises `OverflowError` at pandas 2.3.3 and pyarrow 24 (dates raise `ValueError`, `time64[ns]` raises `ArrowInvalid`). The only `OverflowError` seen is Python-object conversion (`to_pylist`, or `pd.ArrowDtype` then `astype(str)`: `date value out of range`), which is outside the choke point (14.9).
- R2 additions:
  - H3 (S1b-1): a year-10000 `date32` column in post-scan and in post-mask. With the output equal to the source on that column, the gate fails on identity, so a widened value is really inspected. With a monkeypatched converter that makes the column unconvertible, the gate fails closed with `post_scan_column_not_inspectable` / `postmask_column_not_inspectable`. Neither cell can return a pass. Mutation: a callback that returns a passing tally turns the second cell red.
  - H4 (S1b-2), one assertion per consumer for a year-10000 `date32` column: `profile_columns` gives inferred type `date` and `source_arrow_type == "date32[day]"`; `walk_dataframe` runs the date detectors, not the string ones, and raises no free-text advisory; the `scan_set` models receive a `datetime64[ms]` column; the fidelity snapshot classifies the column as datetime, not categorical. Mutation: drop W2 (inferred type taken from the pandas dtype) turns the profile cell red.
  - W1: a mutation adding `.astype("datetime64[ns]")` in `profiling/_distributions.py` turns the R2 profile cell red (`OutOfBoundsDatetime` with the date in its text) and the guard red.
- R3: replaced. The redaction cells assert that a widened column follows the normal date rules in both `include_values` modes, and that `source_arrow_type` passes the value-free type walk.
- R4 (M4): real-caller mutations for both S3 and GCS: restoring `pd.read_parquet(io.BytesIO(...))` in either `to_frame` turns the guard red. Plus a seeded bypass for each W1 spelling.

### 14.9 Exception text and the F31 split (M1)

Correction to the revision-4 V2-LOG note. At pyarrow 24 and pandas 2.3.3:

- `to_pylist`, `as_py` and `pd.ArrowDtype` then `astype(str)` raise `OverflowError: date value out of range`. The message does not quote the year.
- `to_numpy().tolist()` returns the day number (a value).
- `str(array)`, an Arrow cast to string and `strftime` print the date (a value).
- Arrow kernel errors quote values, for example `Casting from date32[day] to timestamp[ns] would result in out of bounds timestamp: 2932897`. This is its own value-bearing class: Arrow kernel error text.
- `astype("datetime64[ns]")` on a widened column raises `OutOfBoundsDatetime` with the date (W1).

Split of ownership (see F31-AUDIT, `docs/plans/2026-11-24-f31-audit.md`):

- F31 `render_failure`, the sink boundary, owns exception text that reaches a sink (log, CLI, report, job record), whatever its source, including Arrow kernel text.
- S1b owns two things only: a source read does not fail on a value pandas cannot hold, and statistics are computed on real, typed values. It does not try to scrub exception text in general.
- Coded callbacks raise `from None` and the choke point calls them after the handler closes, so `__context__` is cleared. The older V2-LOG item about keeping the original in `__context__` stays deferred.

### 14.10 CLI (H2)

CLI sites, as given by the orchestrator at `decoy` `95362d16`:

- `src/decoy/api.py:664` `table.to_pandas()` on mask outputs.
- `src/decoy/cli/_sources.py:395` `pd.read_parquet` in `read_file`, called from `init.py:224`, `report.py:950-951`, `unmask.py:205` and `tokenize.py:649`.
- `src/decoy/cli/io/_targets.py:540` `table.to_pandas()` for fixed width.

The local `decoy` checkout's `origin/main` shows the same sites at `api.py:665`, `_sources.py:469` and `_targets.py:541`, plus `cli/gen/_fit.py:48` `pd.read_csv` (CSV text, allowlist with reason). The slice re-measures at its base.

New slice S1-CLI: route the three sites through the exported `arrow_to_frame` (`read_file` becomes `pq.read_table` then `arrow_to_frame`), with callbacks that raise the CLI's coded errors (`widen=True` only for `report` and `init`, which are read-only). Add the CLI guard that mirrors the engine guard, with its own measured ratchet. Gate the CLI re-pin to the S1b-1 engine release on this slice. R2-CLI cells: `decoy init`, `report`, `unmask` and `tokenize` on a Parquet file with a year-10000 date: coded error or a correct result, and no `10000` in stdout, stderr or the job record.

### 14.11 Slices and size (replaces 13.9)

| Slice | Repo, base | Content | Lines (estimate) |
|---|---|---|---|
| S1b-1 | engine, `main` | choke point with required callback; every engine site routed (sites 8 to 13) with coded or fail-closed callbacks; `to_pandas_fk_safe(table_name)`; deletion (14.6); new reasons `postmask_column_not_inspectable`, `post_scan_column_not_inspectable`; public export and compatibility entry; guard and ratchet; R1 callback cells, R2 execution and H3 cells, R4 | about 450-500 |
| S1b-2 | engine, `main` after S1b-1 | `widen=True` and `arrow_to_frame_pair` widening; `widened_columns` attrs; profile, resident, chunked-profile, cloud and fidelity readers (sites 1 to 7); `FieldStats.source_arrow_type` and W2; W1 guard spellings; R1 widen and attrs cells, R2 profile, scan and H4 cells, R3 | about 400 |
| S1-CLI | CLI, `main` after the S1b-1 engine release | three CLI sites, CLI guard, R2-CLI cells, engine re-pin | about 250 |
| S1 (#790) | engine, rebased on `main` after S1b-2 | the typed date-shift work; drop `profile/_frame.py` and the diagnosis calls; D1 to D3 (R5) | delta about +100 / -60 |
| S2 | engine | as section 5 | as section 5 |

S1b-1 and S1b-2 each go to `main`, not stacked. S1-CLI runs in parallel with S1b-2 once S1b-1 is released. If S1b-1 or S1b-2 passes 650 lines, the builder stops and reports.

### 14.12 Not resolved here

- H3 asked that a year-10000 date column in post-scan and post-mask give a closed, coded failure. With option (b) that column converts losslessly, so the checks inspect it and the gate fails only when the data fails. The fail-closed path is kept for columns that cannot be converted, but no real Arrow type reaches it today, so its R2 cell uses a monkeypatched converter. If the owner wants any widened column to fail the gate too, that is one callback change in S1b-1.
- The CLI line numbers differ between the orchestrator's `95362d16` and the local `origin/main`; S1-CLI re-measures at its base.

## Deferred (V2-LOG)

- **V2-LOG: sequential keeps typed dates in Arrow (option B for B4).** Sequential would keep an admitted typed `date32` column as Arrow, and `date_shift_column` would return Arrow instead of `to_pylist()`, so an out-of-range date becomes a quarantined row as on the unified slice. Deferred because the sequential frame is pandas end to end: the table is converted before any strategy runs and `to_pylist()` cannot hold year 10000, so the change touches the sequential frame model, not one strategy. V1 takes option A (coded job failure) instead.
- **V2-LOG: the coded error keeps the original in `__context__`** (added 2026-11-24 after Codex a2). `raise ... from None` in `_pipeline_full_frame.py` hides the pandas exception from the printed traceback but leaves it on `__context__`, where a caller that walks the chain can still read the value text. V1 threat model (accidental leaks) is met because no V1 path prints or logs `__context__`; clearing it is hardening for V2, with option B.
- **V2-LOG — sentry completeness.** The one-arithmetic AST sentry scans `execution/**/*.py`, so it catches the realistic bypass of restoring arithmetic in `_strategies/_date_shift.py` (`origin/main` lines 358-405), but it does not scan `transforms/`, where the approved `shift_typed_days` choke point lives (`transforms/date_shift.py:1-10`). Extending the scanner to distinguish the one allowed transform function from a second transform implementation is completeness hardening for V2; it does not change the V1 guard or verdict.
- **V2-LOG: Python-object conversion of source values** (added 2026-11-24, revision 4; corrected in revision 5, see 14.9). `to_pylist` and `as_py` raise `OverflowError: date value out of range` (no year in the text); `to_numpy().tolist()` returns the day number; `str(array)`, Arrow casts to string and `strftime` print the date; Arrow kernel errors quote values. The guard covers Arrow-to-pandas conversion and pandas file reads only. Exception text at sinks belongs to F31 `render_failure`; extending the guard to Python-object conversion needs a type-aware rule and is V2 hardening.
- **V2-LOG: deliberate evasion of the source-read guard** (added 2026-11-24, revision 4). `getattr(t, "to_pandas")`, `eval` and `importlib` spellings are out of the guard's listed shapes (recurring-defects #5 scope).
- **V2-LOG: cloud CSV through the one CSV reader** (added 2026-11-24, revision 4). The three `pd.read_csv` calls in `profile/_cloud_readers.py` stay allowlisted in section 13. Routing them through `_csv_reader._read_csv_rows` removes three allowlist entries.
