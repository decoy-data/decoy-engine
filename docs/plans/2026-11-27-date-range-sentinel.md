Status: plan

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 3 (after review round 2, with Q1 to Q5 settled in section 15). Revision 4 adds section 4.4b after S5 code review round 2; Q6 is open. Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Anchors are in this repository (decoy-engine) at `origin/main` `f54ad388b` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one new reason code, three deprecations, a config key on one more strategy), `catalogs/recurring-defects.md` (11 classes), `cross-cutting-concerns.md` (one rule, many routes), `testing.md` (test depth T0 to T4). Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`, deprecation with `replaced_by`).

Risk: R2. It changes what a date strategy does with a far date on every route, adds a reason code and deprecates three, and turns a quarantinable row error into a refusal. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S1, S2, S3, S5, S6, S7 and S8; Codex only for S4. Full suite before merge: S1, S2, S3 and S5 for reasons, and S7 for snapshot serialization; the other slices by their own triggers (section 14).

Owner decision (2026-11-27): a date outside the range a strategy can compute is rejected, unless the column declares it as a sentinel to ignore. Sentinel rows skip the strategy and come out unchanged.

## 1. Frame

### 1.1 Symptom

Real data holds marker dates such as `9999-12-31` ("never expires", the open end of a type 2 slowly changing dimension) and `0001-01-01` ("unknown"). pandas `datetime64[ns]` holds 1677-09-21 to 2262-04-11 only. Today a far date does one of six different things, chosen by the route, the source shape and even the mask key (section 1.2). None of them is "refused with one code, unless declared".

### 1.2 What the probes showed

All probes ran on `f54ad388b` with the main checkout venv (pandas 2.3.3, pyarrow 24.0.0, companion present), through the public entries the tests use (`run_pipeline`, `run_mask_pipeline_chunked`, `run_mask_chunked`, `run_fk_out_of_core` via `tests/parity/_d1a_hash_data.run_chain`). Probe scripts: `p1.py` to `p9.py` in the Architect scratchpad; each is restated as an acceptance test in section 6, so nothing here depends on the scratch files.

Cells: text `"9999-12-31"`, `"0001-01-01"`, `"1600-01-01"` with `date_format="%Y-%m-%d"`; the same as `date32`; the same as `timestamp[us, UTC]`; near-bound text `"2262-04-10"`, `"1677-09-22"`; `date32` year 10183.

| ID | Strategy, shape | Route | Result today |
|---|---|---|---|
| A | date_shift or bucket_perturb, text far date | full_frame, auto, sequential, chunked, native chunked | `RowErrorsFailedError`, trigger `format_error` (quarantinable). Chunked routes stop at the first chunk, so the count differs by route |
| B | date_shift, `timestamp[us, tz]` far date | all in-memory routes | same as A: `format_error` |
| C | date_shift, `date32` far date | all routes | shifts it: `9999-12-31` became `9999-12-10`. A sentinel is silently destroyed |
| D | date_shift, `date32` `9999-12-31` with `min_days=1` | full_frame, native chunked | `format_error` row error (the `OverflowError` is caught at `_date_shift.py:394-397`) |
| E | date_shift, text or tz near-bound (`2262-04-10`, `1677-09-22`, window -30..30) | full_frame, native chunked | uncoded `OverflowError: Overflow in int64 addition`. On the sequential route the same cell shifted to `2262-03-21`: whether it crashes depends on the keyed offset, so on the mask key |
| F | bucket_perturb, `date32` far date | full_frame, chunked | perturbs it (`9999-12-31` became `9999-12-07`) |
| G | bucket_perturb, text far date | out_of_core, both backends | `bucket_perturb_unparseable_no_row_channel` (coded, but the wrong reason) |
| H | bucket_perturb, `date32` far date | `run_fk_out_of_core`, both backends | `bucket_perturb_unparseable_no_row_channel`, while full_frame perturbs the same cells (route divergence) |
| I | bucket_perturb, text near-bound | in-memory routes | computed on the Python path (`2262-04-10` became `2262-04-12`); the out-of-core native backend aborts with `out_of_core_bucket_perturb_date_out_of_native_range` instead (`_bucket_native.py:216-229`) |
| J | windowed_date, anchor `9999-12-31`, `1600-01-01` (text or date) | handler | `windowed_date_anchor_out_of_range` (coded, value-free, declared range 1700-01-01 to 2200-12-31) |
| K | text_mask date span `9999-12-31`, `0001-01-01`, `12/31/9999` at a shift that crosses year 1 or 9999 | transform | uncoded `OverflowError: date value out of range` from `text_mask.py:468` |
| L | distribution generator, fitted snapshot max `9999-12-31` (`timestamp[us]` source) | generation | uncoded `OutOfBoundsDatetime` whose text carries a derived date (`9999-01-01`); with min `0001-01-01` an uncoded `ValueError` quoting `"1-01-01"` |
| L2 | statistical generation, fitted snapshot whose datetime `year_bins`, `min` or `max` name year 9999 or 0 | plan compile (`generation/_window_admission.py:128-170`) and sampler (`generation/statistical/_sample.py:493`, `_degenerate.py:122`) | `plan/generation_unbounded_column` (coded, value-free). The snapshot range is `MIN_YEAR = 1` to `MAX_SAMPLED_YEAR = 9998` (`contracts/distribution_snapshot.py:31-32`), because the sampler builds `datetime(year + 1, 1, 1)`. There is no way to declare `9999-12-31` as a sentinel, so a column that holds one cannot be generated at all |
| L3 | statistical generation, `windowed_date` whose anchor is a statistical datetime column | plan compile (`generation/_window_admission.py:290-320`) | `plan/generation_unbounded_column` when the anchor's fitted `min`/`max` plus the offset leaves 1700 to 2200. A `9999-12-31` sentinel in the anchor column makes the whole pair refuse |
| M | quality snapshot `_datetime_stats` over object `datetime.date` values with `9999-12-31` | profiling | silently drops the far value from min, max and year bins (`utc_naive_datetimes`, `pandas_compat.py:84-93`, coerces it to NaT and drops it). `profiling/_distributions.py:105` `_distribution_date` drops it the same way (`pd.to_datetime(errors="coerce").dropna()`) |
| N | passthrough, hash, redact, shuffle over far `date32`, `timestamp[us]`, `timestamp[us, tz]` | all routes | correct (no date arithmetic; pandas 2 keeps the source unit). Not in scope |
| O | any strategy, `date32` year 10183 | every route but native chunked | uncoded `ValueError: year 10183 is out of range` from the profile sampler (`profile/_readers.py:499`) quoting the year. Not a strategy range, but a value-bearing error: fixed in S5 |
| P | date_shift or bucket_perturb with `preserve_values=["9999-12-31","0001-01-01"]` | every route above | the listed sentinels come out unchanged and are counted; undeclared far rows still behave as A to I |

Side finding, out of scope: shuffle over a `timestamp[ns]` column returns `timestamp[us]` on full_frame (follow-up G-3).

### 1.3 Impact under the V1 bar

C and F are silent wrong output for the most common sentinel (a `DATE` column from a database). E is a function break whose trigger depends on the secret. A and B make a run fail with a misleading reason and let a quarantine config hide sentinel rows from the main output. G, H and I give three different answers for one input across routes. All of these block V1 as function breaks.

## 2. Root cause with evidence

There is no single statement of "the dates this strategy can compute". Each primitive finds its limit in its own way:

- The text path parses with `pd.to_datetime(..., errors="coerce")` (`_date_shift.py:420`, `bucket_perturb.py:222`, `_date_shift_ext.py:219`), so a far date becomes NaT, and NaT is reported as a parse failure (`format_error`).
- The typed date path uses Python `datetime.date` arithmetic (`_date_shift.py:366-399`, `bucket_perturb.py:245`), so it computes years 1 to 9999 and treats a sentinel as a real date.
- The shift itself (`parsed + pd.to_timedelta(...)`, `_date_shift.py:432`, `_date_shift_ext.py:240`) overflows when an in-range date plus its keyed offset leaves the ns range. Nothing checks this before the add.
- The out-of-core route has no row error channel, so it refuses NaT under a reason that says "unparseable" (`_bucket_native.py:283-292`), and the native bucket kernel has its own range guard and reason (`_bucket_perturb_ext.py:91-110`, `_bucket_native.py:216-229`).
- `preserve_values` (D1c, `date_preserve.py:160-275`) already carves sentinels out before parsing, but nothing refuses the far dates that are not listed.

## 3. Established solutions considered

Search run: web search and page reads for ARX, Tonic Structural, Delphix, Gretel, Informatica, IBM Optim, Greenmask, Google Sensitive Data Protection and the pandas user guide; in-codebase search for `preserve_values`, `sentinel_to_null`, `OutOfBoundsDatetime`, `native_range_exceeded`, `SUPPORTED_MIN` and the pre-scan sentinel detector.

- ARX (https://arx.deidentifier.org/anonymization-tool/): values that do not conform to the column's data type are replaced with null values that every method then handles. No sentinel list.
- Tonic Structural, Timestamp Shift (https://docs.tonic.ai/app/generation/generators/generator-reference/timestamp-shift-generator): a value the generator cannot process goes to a fallback chosen per column; the default is "Fail on error", with Passthrough, Constant or Null as opt-ins. Date Truncation leaves dates more than 90 years old unchanged (search snippet only).
- Delphix date shift (https://masking.delphix.com/docs/latest/date-shift-fixed, snippet): the built-in algorithms change the day part only and clamp to the month end, so year overflow is mostly avoided by construction. No reserved-value list found.
- Greenmask `noise_date` (https://greenmaskio.github.io/docs/built_in_transformers/standard_transformers/noise_date, snippet): a result past the max threshold is set to the max (clamp).
- Google Sensitive Data Protection date shifting (https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-date-shifting): bounds only (`lower_bound_days`, `upper_bound_days`); no out-of-range rule stated.
- Informatica key date masking (snippet only, pages returned 403): supported range 1753 to 9999.
- Gretel, IBM Optim: nothing found.
- pandas "Timestamp limitations" (https://pandas.pydata.org/docs/user_guide/timeseries.html): the ns range is 1677-09-21 to 2262-04-11; `errors="coerce"` turns what it cannot parse into NaT.
- In-codebase: `preserve_values` (`date_preserve.py`), the windowed_date declared range (`windowed_date.py:66-72`, a range "declared, not inherited from pandas", narrower so arithmetic cannot wrap), the bucket reach table (`_bucket_perturb_ext.py:88`), and the pre-scan sentinel detector, which already names `0001-01-01` and `9999-12-31` (`profiling/sentinels.py:36-44`).

The design follows Tonic's default (fail on error, chosen per column) and the windowed_date pattern (a declared range per strategy, independent of the pandas version). It rejects clamping (Greenmask, Delphix month clamp) and nulling (ARX), because both write a value the source did not hold or erase the sentinel meaning. No surveyed tool has a per-column declared sentinel list; Decoy already ships one (`preserve_values`), so the remaining custom code is the range table and its one enforcement point.

## 4. Fix design

### 4.1 Guarantee

For `date_shift` and `bucket_perturb` (S1), and `windowed_date` anchors (S3), on every route (full_frame, auto, sequential, chunked, native chunked, out_of_core, `run_fk_out_of_core`, isolated):

1. Each (strategy, source shape) has one declared input range (section 4.2). It does not depend on the route, the backend, the batch size or the mask key.
2. A non-null cell whose calendar date matches the column's `preserve_values` skips the strategy and comes out byte for byte unchanged (text) or value for value unchanged (typed), and is counted in the existing `date_preserve` metric.
3. Any other non-null cell outside the range refuses the run with `runtime/date_outside_strategy_range` before the strategy computes any cell of that batch. The message names the table, the column, the strategy and the count of refusing cells in the batch. It holds no cell value, no position and no exception context.
4. A refusal is not a row error: quarantine does not absorb it (owner decision Q4). No target is published (the existing transactional publication aborts).
5. Null cells pass through as today. Rows a `when:` gate does not select are not computed and are not checked.
6. A declaration is a disclosure choice. A real date that is equal to a declared sentinel (a genuine `1900-01-01` birth date in a column that declares `1900-01-01`) passes unmasked, because the engine cannot tell the two apart. The user docs state this, and the post-mask report shows, per column, how many rows were left unmasked as declared sentinels (S6), so the exclusion is visible and never silent.

For statistical generation (S7) the same declaration applies to the fit: declared sentinels are taken out of the fitted range and emitted at their observed rate (Q3); an undeclared date outside the sampler range keeps its plan refusal (section 4.2).

Non-goals: widening the text path to the Python calendar (follow-up G-2); masking dates beyond year 9999 (S5 only refuses them, coded and value-free); any change to value-agnostic strategies (row N); a CLI hint that suggests `preserve_values` from pre-scan sentinel flags (G-4).

Size: S1 estimates 250 source lines over 13 files plus 400 test lines. S5 spans source ingestion, admission and reasons. S7 spans fit, value policy, the snapshot contract, both consumers and plan pins. S8 changes the CLI fit entry, reader, help and integration tests.

### 4.2 Design

The input range is the compute domain of the primitive, less the reach of the strategy's arithmetic. All values are whole calendar days, held as `datetime.date` (Python years 1 to 9999), so no bound needs `datetime64[ns]`.

| Strategy | Shape | Domain | Reach (days taken off each side) |
|---|---|---|---|
| date_shift | text, `timestamp_tz` | 1677-09-22 to 2262-04-10 (whole days inside the pandas ns range); `timestamp_tz` one more day on each side for the zone offset | low side `max(0, -low)`, high side `max(0, high)`, where `(low, high) = shift_window(cfg)` |
| date_shift | `date` | 0001-01-01 to 9999-12-31 | same as above |
| bucket_perturb | text | 1677-09-22 to 2262-04-10 | the existing `_BUCKET_REACH_DAYS` for the bucket, both sides |
| bucket_perturb | `date` | 0001-01-01 to 9999-12-31 | same |
| windowed_date (S3) | anchor, any supported shape | 1700-01-01 to 2200-12-31 (existing `SUPPORTED_MIN`/`SUPPORTED_MAX`) | none on the anchor; the existing offset check stays |
| statistical generation (S7) | fitted datetime snapshot | 0001-01-01 to 9998-12-31 (existing `MIN_YEAR`/`MAX_SAMPLED_YEAR`) | none |
| distribution generator (S5) | fitted `min`/`max` | the text domain (ns math at `generators/_distribution.py:410-416`) | none |

S5 owns the distribution ns bounds used in fitted admission. S1 and S5 reuse the whole-day ns endpoints from a single calendar-range definition in the lower-tier contracts module, landed by S5. S1 imports those names. The transforms table imports `MIN_YEAR` and `MAX_SAMPLED_YEAR` from `contracts/distribution_snapshot.py:31-32`. The decoder uses its own contract constants and never imports transforms. Both fitted generators refuse an unsupported snapshot with `plan/generation_unbounded_column`. Validate bounds and every live bin before a draw, including single-value and direct generator entry points. Use the same admission check at plan compile and for direct calls without a compiled plan. For the distribution generator, clip the first and last year on calendar bounds before constructing ns endpoints. Test 1677 and 2262 as well as out-of-domain bins with ordinary min/max. Explicitly convert to ns before integer arithmetic on every supported pandas version.

Resolve the shift once with `transforms/date_shift.py:98 shift_window(cfg)`. It handles jitter, default bounds and reversed bounds. Resolve the bucket once with the existing bucket resolver. Keep the config resolver in date_shift.py and the bucket reach table in date_preserve.py. Store the resolved window or bucket on the domain and carry it into the partition. Reach comes from that resolved choice, so the refusal set is the same for every key (fixes E). With the usual windows the edge sentinels are refused on the typed path too: `9999-12-31` under `max_days > 0` or any bucket, `0001-01-01` under `min_days < 0` or any bucket. Genuine historic typed dates (`1600-01-01`) keep computing, as COLUMN-SHAPE E1b intended (`test_date_shift_typed_edges.py:74`). This is owner decision Q1.

A text cell is "out of range" when pandas cannot hold it but `datetime.strptime` under the same `date_format` parses it, or when it parses inside pandas and falls outside the range. The strptime retry is the one `PreserveSet._strptime_date` already does (`date_preserve.py:198-204`). For pandas-only formats or precision directives that strptime cannot read, use a calendar-capable parse with the same format semantics before classifying NaT. Test a valid far ISO date with ISO8601 and mixed, fractional seconds with %f, and a genuinely malformed token. Only a token that fails calendar parsing stays a format_error.

One object carries both declarations. `preserve_set_from_config` (`date_preserve.py:226`) becomes `date_domain_from_config(cfg, *, strategy, shape)` and returns a `DateDomain` (the `PreserveSet` fields plus the range) for every column of these strategies, with or without `preserve_values`. `DateDomain.partition(values, *, table, column)` returns a `DatePartition` or raises `DateRangeError`. The partition carries the values it cleared: the source series it was built from, the parsed series (text path), the sentinel mask and the rows to compute. It is bound to that data, so a partition from another chunk or column cannot be used by mistake (section 4.4). Sentinels are matched first, then the range is checked on the rest, so a declared far sentinel is never counted.

Enforcement by construction: each compute primitive takes a required `partition: DatePartition` argument in place of today's series and optional `preserved` mask, reads its input values only from `partition.source` and `partition.parsed`, and computes only `partition.compute_rows`. Each primitive takes its window or bucket from the partition. Remove separate source, min/max, jitter and bucket arguments wherever they could override the checked choice, including calls into native kernels. Where a caller must also pass an aligned companion series (the `group_by` anchor in S2), the primitive checks `len(companion) == len(partition.source)` and `companion.index.equals(partition.source.index)` and raises an internal error if not. The primitives are `_shift_rows` and `_shift_dates` (`_date_shift.py:366`, `:402`), `native_date_shift` (`_date_shift_ext.py:147`), `native_bucket_perturb` (`_bucket_perturb_ext.py:213`), and `apply_bucket_perturb` / `apply_bucket_perturb_dates` (`bucket_perturb.py:183`, `:245`). `DatePartition` has no public constructor: only `DateDomain.partition` builds it (a module-private token checked in `__init__`). It is a frozen class with `__slots__`, not a dataclass, so `dataclasses.replace` does not apply, and `__replace__`, `__copy__`, `__deepcopy__` and `__reduce__` raise. Test shallow copy, deep copy, replacement and pickle on a real partition. A route that skips the check cannot call a primitive.

Call sites that build the domain today and must partition instead (all in S1): `_date_shift.py:159`, `:251`; `_bucket_perturb.py:70`, `:181`; `_sequential_native.py:395`, `:540`; `native/_operator_step.py:279`, `:459`, `:488`; `native/_operator_params.py:282`, `:299`; `out_of_core/_bucket_native.py:185`, `:263`; `out_of_core/_mask_group_c.py:452`; `date_preserve.py:256` (`apply_excluding_preserved`).

Removed as unreachable: the decline at `_sequential_native.py:398` and the abort at `_bucket_native.py:216-229`. A near-bound date is now refused by the partition before any kernel runs, on both backends. `native_range_exceeded` (`_bucket_perturb_ext.py:91`) stays as a cheap internal invariant: `native_bucket_perturb` and `native_date_shift` assert, on text and tz shapes only, that no row in `partition.compute_rows` is within reach of a pandas bound and raise an internal error if one is (pandas wraps silently there, `_bucket_perturb_ext.py:85-88`). It never declines and never fires on a correct partition; it is the second line behind the partition. The out-of-core typed path (H) calls `apply_bucket_perturb_dates`, the same primitive the handler uses.

`preserve_values` stays the one declaration (no rename). It already ships on two strategies, its literals are already held as `datetime.date` (`date_preserve.py:134-138`, `:240`), and `date.fromisoformat` already refuses years 0 and above 9999. S3 adds it to `windowed_date`. Config validation stays at plan compile (`plan/_checks_date_shift.py:376`) and in the handler preflights, one rule (`preserve_config_problem`, `date_preserve.py:84`).

Relation to `sentinel_to_null` (F06 declared casting, `config/_tables.py:146`, `contracts/declared_casting.py:55`). The two are kept apart on purpose, because they give different outputs:

- `sentinel_to_null` is a parse-time declaration on a declared-casting column: exact raw tokens, any logical type, matched before parsing, and the cell becomes null.
- `preserve_values` is a strategy-time declaration on a date strategy: calendar dates, and the cell comes out unchanged.

Casting runs first. A token that `sentinel_to_null` turns into null reaches the strategy as null and passes through as null; `preserve_values` never sees it. A column may declare both (for example `"0000-00-00"` to null, `9999-12-31` to keep). No overlap refusal is added: an entry in both is harmless (casting wins) and the docs say so. Merging them would either null a sentinel the user wants kept or keep a token the user wants nulled.

**Fit and generation (S7 and S8).** A generation config arrives after fit. Year bins cannot recover the count for an arbitrary declared day such as 1900-01-01, or the next minimum after removing it. A repeatable CLI option is simpler than persisting a histogram of every source date. S7 adds an optional keyword-only `preserve_values_by_column` mapping to the public `distribution_snapshot_document` and `compute_distribution_snapshot` functions. S8 passes it from `decoy fit --preserve-date COLUMN=YYYY-MM-DD` through `cli/gen/_fit.py:65 fit_exact_snapshot`. Split at the last equals sign and use the engine's existing declaration validation. Reject unknown columns or invalid dates with value-free errors. Refuse this exact-count option on DP fits. The default remains the ordinary fit.

Classify homogeneous Python calendar dates as datetime at the public writer entry. Today's `quality/snapshot.py:294` checks only datetime64 dtype. For declared CSV columns retain the selected source rows and parse calendar dates before pandas can return a text column or coerce a far date to NaT. Keep timestamp precision and timezone normalization for ordinary timestamp bounds. Match calendar dates before computing ordinary min, max and bins. Preserve total, null and non-null counts. Store every declared date with its exact count under `stats.sentinels`, including zero for an absent date. Omit the field when no date was declared. No full date histogram is needed. Derive ordinary ranges, including redaction and folding, from ordinary rows only. Keep sensitivity detection on the original column.

Treat the list as real values at both boundaries. For exact sentinel fits require the existing explicit raw-value release for the persisted document. Otherwise refuse before serialization with a value-free error. Never insert exact counts or dates into a redacted or DP artifact. At admission extend `_refuse_withheld_values` for date sentinels and require a valid raw marker for this new persisted field, including for a forged block with missing markers. Keep existing legacy no-block reads. Use a strict shared contract on write and read: unique canonical ISO days, nonnegative integer counts (no bool or string), total no greater than the non-null count and ordinary mass consistent with the residual. Refuse a recorded date without a matching column declaration, before reading ordinary bins or selecting a degenerate path. A generation request to preserve a date on a legacy snapshot without exact counts needs a refit. Admit a sentinel-bearing spec only after the policy, schema and declaration checks pass. Serialize that checked spec through the existing plan pin and revalidate its fields on restore. A zero-count entry proves the fit checked that declaration and contributes no draw weight. Refuse a generation declaration the fit did not cover.

The raw writer currently returns v1, and only the floored writer upgrades to v2 at `profiling/_snapshot_values.py:485`. For an opted-in raw fit, encode every datetime column's one-year bins through `encode_datetime_buckets` before stamping v2 on the document. Keep the no-option version selection. The ordinary redacted path currently clamps year 9999 to 9998 in `fold_year_bins` at line 254. Before folding or coarsening, record a value-free unsupported-range flag per affected sampler if an ordinary date lies outside its domain. Carry it through the stored and pinned spec and check it at admission. This preserves the refusal without writing the date. Exercise a default redacted fit with the outlier among enough ordinary dates to trigger folding.

At admission pass only ordinary stats to the existing range checks, including windowed anchor admission. Apply the existing null draw once, then draw a declared sentinel with its count divided by total non-null count. Use the ordinary sampler for the remaining mass. An all-sentinel non-null column needs no ordinary bounds or bins. An all-null column needs no draw. Carry this rule through statistical and distribution generation, including single-value shortcuts. The distribution entry currently accepts a bare column mapping (generators/_distribution.py:20-82). For sentinel-bearing input, require the policy-bearing document and source-column selection so both generators use the same validated spec. Keep the existing bare entry for ordinary distributions and reject a bare sentinel block value-free. Route versioned bins through the contract decoder before drawing. Use a date-capable output representation for declared days outside ns, and preserve ordinary timestamp precision. Older readers see only the ordinary bins and cannot emit the recorded far day. For in-range sentinel days, exclude declared days from the ordinary draw so their observed rate is not increased by a second path.

### 4.3 Group_by and other existing conflicts

- `preserve_values` with `group_by` is refused today (`_date_shift.py:167-178`, `plan/_checks_date_shift.py:403-412`). After S1 a group_by user with a `9999-12-31` row has no way to run, so S2 supports the pair: the handler passes the full `anchor_col` to the primitive. It checks length and index against the full partition source, then selects both the anchor and source by the same `compute_rows` positions before deriving group offsets. Native already declines `group_by`, so S2 touches the Python path only. The two `date_preserve_values_with_group_by_unsupported` reasons (plan and runtime) are deprecated with `replaced_by=None`: the refusal goes away, so there is nothing to replace it with. `CONTRIBUTING.md:58` says a deprecation comes "with `replaced_by`", but the registry allows `None` and only checks that a replacement, when given, names a declared identity on a deprecated entry (`reasons/_registry.py:202-209`). The S2 changelog fragment names both deprecations and says the pair is now supported.
- `preserve_values` on a child FK key stays refused (`date_preserve_values_unsupported_fk_shape`); a far date on a parent key is partitioned on the parent and the child remaps through it as today.
- `%f`, `%Z`, `ISO8601` and `mixed` formats stay refused with `preserve_values` (`date_preserve.py:113-130`). The range check uses the configured format even without a declaration, including the calendar fallback in section 4.2.
- A naive timestamp column stays a shape mismatch for both strategies (unchanged).
- Check order differs today between the chunked and full-frame compile paths (probe: chunked reports `preserve_values_invalid` before `column_shape_mismatch` on a naive timestamp). Not changed here; follow-up G-5.

### 4.4 Choke points

- Rule: no date compute primitive runs on a row the domain has not cleared. Enforced by the required `partition` argument and the private constructor.
- Guard: `tests/sentry/test_date_partition_choke_point.py` (new). It walks `src/decoy_engine` with `ast` and:
  - resolves every name in the primitive list to a function and fails if one no longer resolves, so a renamed or moved primitive cannot drop out of the check;
  - asserts each has a required, keyword-only `partition` parameter with no default, and no separate source or shift-window or bucket parameter;
  - asserts `DatePartition(`, `DatePartition.__new__`, `object.__new__(DatePartition` and `replace(`/`copy(`/`deepcopy(` on a `DatePartition` appear only inside `transforms/date_preserve.py`;
  - checks callers of allowlisted forwarding helpers by exact path and function. It also asserts that every function in the strategy-input packages (`execution/_strategies/`, `execution/native/`, `execution/out_of_core/`, `execution/_sequential_native.py`, `transforms/`) that calls `pd.to_datetime`, `pd.to_timedelta`, `timedelta(`, `pd.DateOffset` or adds to a `datetime.date` is either in the primitive list or on an allowlist entry that names module, function and reason (windowed_date, text_mask, the validators). This sees the typed path (`_date_shift.py:366-399`, `bucket_perturb.py:245`) as well as the text path.
- Mutations that must turn the guard red: give `native_bucket_perturb`'s `partition` a default of `None` (M-4); rename `_shift_dates` (M-15); add a `timedelta` add in a new unlisted helper (M-16).
- Second guard: `tests/unit/transforms/test_date_domain.py` passes a partition built for chunk N to the primitive together with chunk N+1's companion series and expects the internal error (M-13), and calls the native seams with a near-bound row inside `compute_rows` through a test-only hook and expects the invariant raise (M-14).

**S5 source reads.** Check Arrow data when it enters the reader, before it can reach pandas, Python scalar conversion or a native kernel. Use one checked table or batch operation in the io tier. Bind the table name when opening the source: it is the caller's `sources` mapping key, or the configured table on the single-source chunked entries (section 4.4b). In profile/_readers.py cover LazySource.iter_batches, open_batches and to_table, plus resident frames. At execution entry wrap supplied tables and loader results before transforms, preflight or dispatch, including direct chunked and native APIs. Apply it to resident inputs (including loader returns), lazy materialization and every yielded batch, including opened row-group reads and the direct OOC entry. The profile head uses the same checked read. Keep streaming bounded. A head scan proves nothing about unread rows. Later source conversions at `execution/_chunked_profile.py:41`, `pipeline/_source_types.py:60`, `out_of_core/_mask_group_c.py:537` and `internal/pandas_compat.py:132` must all receive checked data.

For date32, date64 and timestamps, compare non-null Arrow extrema as physical integers in their native units to the inclusive Python calendar bounds. Only plain date and timestamp columns and top-level dictionaries of them are read; every other column that holds a date at any depth is refused by type (section 4.4b). A top-level dictionary is checked by the rows that reference each entry, and its unused out-of-calendar entries are dropped in place, keeping order (section 4.4b). Intersect with the unit's storage range before making comparison scalars. Preserve valid sub-day timestamps through the end of year 9999. For zoned columns also check local calendar representability before conversion, including offset crossings. Only on failure count the offending rows with an Arrow mask. Raise `SourceDateUnrepresentableError` outside any exception handler with table, column and batch count only. The AT-V1 source-boundary guard traces resident returns, caller loaders and lazy yields to the checked read, with allowances per function, never per file, and it treats a function that forwards data to an allowlisted conversion helper as a sink (section 4.4b). Bypassing a later batch or a resident return must fail AT-V1. Run the import-layer and reason-adapter tests, including isolated classification.

### 4.4a Existing tests the S5 source check changes

Found by the S5 full suite on 2026-11-27 (236 new failures, all one class). The source check in 4.4 applies to every
source column on every route, including passthrough and carried columns. So a source date outside the Python
calendar (year 1 to 9999) is now refused at the reader with `source_date_unrepresentable`, before any strategy runs.
This follows the non-goal in section 4.1 ("masking dates beyond year 9999: S5 only refuses them"). Row N stays true for
far dates inside the calendar, such as `9999-12-31`, which passthrough still returns exactly.

Some tests fed out-of-calendar values through passthrough and asserted the old behavior. S5 changes them as follows,
and each change keeps the test's own claim:
- `tests/native/test_chunked_entry_rev9_shapes.py`: the shapes `timestamp_{s,ms}_min` (int64 minimum) and
  `date32_far`. Every test parametrized over them asserts something about carried passthrough: exact return on both
  routes, equal tables, oracle unchanged, min int64 kept, row-error sink, and no carried column reaching pandas. For
  each one, use the in-calendar extreme for the same unit instead (the first and last representable instant of years
  1 and 9999), so the claim is still checked at the edge. Add one test per route that the int64-minimum shapes are
  refused with `source_date_unrepresentable`, value-free, naming the table and column.
- `tests/native/test_unconfigured_passthrough_read.py::test_sibling_reading_strategy_keeps_its_listing_and_coded_error`:
  if the bad shape is an out-of-calendar date, swap it for a non-date bad shape of the same family, so the sibling
  listing and coded error are still checked. Add an assertion that the date shape is refused at the source.
- `tests/unit/execution/test_full_frame_value_unrepresentable.py::test_far_date_raises_coded_error_naming_the_column`:
  year 12921 is now refused at the source. Assert `source_date_unrepresentable`, naming the column and table.
  `full_frame_value_unrepresentable` stays tested by the time64 sub-microsecond case in the same file. If no date
  shape can reach `full_frame_value_unrepresentable` any more, write that down as a V2-LOG note. Do not remove the code.

Any other test that S5 turns red must fit this class (an out-of-calendar source date fed through a value-agnostic
column) to be changed this way. Anything else is a real regression: fix the code, not the test.

What section 4.4b changes here. The three entries above use plain date and timestamp columns, so 4.4b leaves them as
they are. 4.4b changes tests that the S5 branch added (they are not on main):
- `tests/unit/io/test_checked_source_dates.py::test_a_far_date_nested_in_a_container_is_refused_by_name_and_count`
  (six shapes): each shape is now refused with `source_date_type_unsupported` and its container kind, with no count.
  Rename it to `test_a_date_in_a_container_is_refused_by_type` and add an in-calendar case per shape.
- `test_a_nested_date_inside_the_calendar_and_a_null_parent_pass` in the same file: inverted. Both columns are now
  refused by type. This is the contract change behind Q6, not a weakened test.
- `test_an_unused_bad_dictionary_entry_is_dropped_not_refused`, `test_a_chunked_dictionary_column_is_cleaned_chunk_by_chunk`
  and `test_a_record_batch_is_cleaned_too`: keep them, and add the order and kept-entry assertions of AT-V6.
  `test_a_dictionary_of_something_else_is_left_alone` (no date inside) stays as it is.
- `tests/unit/execution/test_source_date_unrepresentable.py::test_a_far_date_nested_in_a_list_or_struct_is_refused_on_both_chunked_routes`:
  expects `source_date_type_unsupported`. Every `LazySource(path, table=TABLE)` fixture in that file (lines 84, 137,
  155, 163, 215, 239 at `2fab8cb9f`) drops `table=`, so the mapping key must supply the name (AT-V7). The static guard
  at lines 400 to 528 moves to `tests/sentry/test_source_date_read_guard.py` and is rewritten per section 4.4b.
- `docs/strategies.md:403-405` (the nested and dictionary paragraph) is rewritten per section 4.7.

Any other test that 4.4b turns red must hold a date inside a non-plain column. Anything else is a regression.

### 4.4b Date-bearing columns outside plain date and timestamp

Added after S5 code review round 2 (Codex, PR #839 at `2fab8cb9f`). Six of its seven V1 findings are one class, and
round 1 found the same class (V1-3 nested, V1-4 dictionary). `io/source_dates.py` walks Arrow's physical layouts by
hand: `.keys`, `.items` and `.flatten()` on a fixed list of container kinds, and a dictionary re-encode. Each layout it
misses or misreads is a new leak or a false refusal. A repeated class changes the plan, so this section replaces the
walk with a closed contract instead of a third patch round.

**Survey.** Run on this box with pyarrow 24.0.0, pandas 2.3.3 and Python 3.10 from the engine venv (probe scripts in
the planner scratchpad, not committed). The engine floor is `pyarrow>=14`, which has no `list_view` type.

| Operation | Probe result | Use here |
|---|---|---|
| dictionary cast or `dictionary_decode` | A cast of `dict<date32>` to `date32` counts referenced rows only. A cast of `dict<struct<date32>>` to its value type raises `ArrowNotImplementedError` (finding 6). `DictionaryArray.dictionary_decode()` and `take(dictionary, indices)` work for any value type. `ChunkedArray` has no `dictionary_decode`. | V1 keeps the cast for top-level dictionaries of plain dates. |
| `pc.run_end_decode` | Correct and slice-aware. A cast of REE to `date32` raises, REE has no `take` kernel, and REE `to_pylist` raises `OverflowError: date value out of range`. | V2 only. |
| cast `list_view` to `list` | Broken in 24.0.0: offsets `[0, 1]`, sizes `[1, 1]` gives an array that fails `validate(full=True)` and flattens to `[]`. An overlapping view keeps the unreferenced far value in `.values`. `pc.list_flatten` on a list view is correct. | Never cast a list view. |
| `pc.list_flatten` | Respects slices and null parents for list, large list and fixed-size list. No kernel for `map`; after a cast of the map to `list<struct<key, value>>` it respects the slice. `StructArray.flatten()` merges parent validity. `.field(i)`, `.values`, `.keys` and `.items` return raw backing storage (findings 2 and 4). | V2 logical view. |
| `pa.concat_arrays`, `take(arange)` | Neither removes all hidden storage. `take` removes it for a sliced map and a null-parent list, keeps it for a null-parent struct and an unused dictionary entry, and has no REE kernel. `concat_arrays` removes it for a sliced map, a list view and REE, and keeps it for null-parent lists and structs and for dictionaries. A Parquet round trip removes it all, but turns the dictionary column plain, renames list items, refuses list view and REE, and costs a full encode. | No single Arrow operation gives a canonical form. |
| error text of a far date | `to_pandas` raises `ValueError: year 10183 is out of range` for a far `date32`, for a list or struct with a far child under a null parent, for a dictionary with an unused far entry, and for an extension type over `date32`. `to_pylist` raises `OverflowError: date value out of range` (no year). A cast of `timestamp[us]` to `ns` raises `ArrowInvalid` quoting the raw integer. A null slot of a plain leaf is not read by `to_pylist`, `to_pandas` or the ns cast. | The check must run before any conversion. |
| order-preserving dictionary repair | `filter(dictionary, keep)` plus `take(cumulative_sum(keep) - 1, indices)` keeps the surviving entries in order, keeps unused valid entries and null entries, and the pandas categorical keeps `ordered=True` and its minimum. | V1 repair. |
| type-tree walk | `DataType.num_fields` and `field(i)` reach the children of list, large list, fixed-size list, list view, map, struct, union and run-end-encoded types. `DictionaryType.value_type` and `ExtensionType.storage_type` reach the rest. | V1 type gate. |

Which sources carry such columns. The CSV, fixed-width and database readers give flat columns only. Parquet can carry
`list`, `large_list`, `fixed_size_list`, `struct` and `map` columns with dates inside (common in event and analytics
exports from Spark or BigQuery, rare in the relational copies that are the main Decoy use) and dictionary-encoded date
columns. Parquet cannot store list view, run-end-encoded or union columns (probe: "Unhandled type for Arrow to Parquet
schema conversion"), and a Parquet dictionary sits on a leaf only. So those types, and a dictionary of structs, reach
the engine only as Arrow data a caller passes in: resident `sources`, a `source_loader` or the chunked APIs.

**Choice: option (b), a narrow V1 contract with a closed type gate.** Option (a) needs a canonical form built from
established Arrow operations, and the survey shows there is none. No single operation removes hidden storage on every
layout, the one cast that would remove list views is broken, and REE has no take kernel. A canonicalizer would be a
rebuild per layout (list offsets from lengths, structs from flattened children, maps from keys and items, fixed-size
list padding, dictionary remaps) written by hand, which is the class that failed twice. It would also have to either
change output types (a decoded dictionary is no longer a dictionary) or rebuild each type in place. No option (c) came
out of the survey: the logical-view operations count correctly, but they do not make the data handed on safe to convert
or to write. Option (b) checks two layouts with code that review has already passed, and refuses every other layout by
its type, so a layout the check does not know is refused, not missed.

The contract:

1. Read: a plain `date32`, `date64` or `timestamp` column (any unit, with or without a zone), checked as in section
   4.4; and a top-level dictionary whose value type is one of those, checked by casting the column to its value type,
   which counts referenced rows only. No other column that holds a date is read.
2. Type gate, first, on the schema. A date leaf is `date32`, `date64` or `timestamp` (the existing `_is_temporal`,
   `source_dates.py:52`), not `pa.types.is_temporal`, which also takes `time64`, `duration` and
   `month_day_nano_interval`. `_holds_dates(t)` is `any(is_date_leaf(n) for n in type_nodes(t))`. `type_nodes` and
   `type_children` are the existing type walker from `fileaccess/adapters/arrow.py:150-169` ("the one place the type
   checks learn Arrow's nesting rules"), moved to the bottom-tier `decoy_engine/_arrow_types.py` and used from both
   places, so there is one copy. It follows `pa.BaseExtensionType` to its storage type (so `opaque`, `uuid`, `json`
   and `fixed_shape_tensor` are seen, not only `pa.ExtensionType` subclasses), a dictionary to its value type, a map to
   its entries struct, structs and unions through `num_fields` and `field(i)`, and list kinds, list views and
   run-end-encoded types through `value_type`. There is no list of container kinds to keep in step with pyarrow.
   Probe on pyarrow 14.0.2 (the floor, scratch venv) and 24.0.0: the walker finds the date in list, large list,
   fixed-size list, map, struct, dense and sparse union, run-end-encoded, dictionary and `fixed_shape_tensor(timestamp)`
   on both, and in list view, large list view and `opaque(date32)` on 24; pyarrow 14 has no list view, `opaque`,
   `uuid` or `json` type, so there is nothing more to walk there. A column that holds dates and is not a shape in item 1
   is refused with the new reason `runtime/source_date_type_unsupported`, raised as `SourceDateTypeUnsupportedError`
   beside `SourceDateUnrepresentableError` in `io/bounded_reader.py`, with a `_CODED` row for that module. The message
   names the table, the column and the kind of the outermost type of the column, from a closed set (`list`,
   `large_list`, `fixed_size_list`, `list_view`, `large_list_view`, `map`, `struct`, `union`, `run_end_encoded`,
   `dictionary`, `extension`, `other`). It says to drop the column, select it out, or cast it to a plain date or text
   column before the run. It holds no value, no count, no child field name and no exception context. The gate reads the
   type only, so it refuses whether the dates are inside the calendar or not.
   Wiring: `check_source_schema(schema, *, table)` is the gate. `check_source_dates` calls it first on every table and
   batch (so a resident or loaded table refuses even when it has no rows), and `checked_batches` and `checked_chunks`
   call it eagerly on the source schema before the first batch: `LazySource.iter_batches`, `open_batches` and
   `to_table` pass the Parquet footer schema, and the `_FixedSchemaChunks` path passes its `source_schema`. So a lazy
   source refuses at open, before the profile head, and an empty Parquet file refuses (AT-V3 empty-file case). A plain
   chunk iterable with no known schema is gated at its first chunk; an empty one has nothing to check.
3. Closed vocabulary in the check. `source_dates.py` may call only an allowlist of `pc` functions (`min_max`, `less`,
   `greater`, `or_`, `and_`, `invert`, `fill_null`, `sum`, `local_timestamp`, `cumulative_sum`, `subtract`, `take`)
   and an allowlist of attributes and methods (the type and schema accessors, `.cast`, `.filter`, `.chunks`,
   `.dictionary`, `.indices`, `.column`, `.num_columns`, `.from_arrays`); the builder records the final list in the
   test. An `ast` test fails on any other `pc.` call or attribute, so `pc.list_flatten`, `struct_field`,
   `list_value_length`, `list_parent_indices`, `run_end_decode`, `dictionary_decode`, `.values`, `.keys`, `.items`,
   `.field`, `.storage`, `.sizes`, `.run_ends`, `.value_lengths`, `.value_parent_indices`, `.offsets`, `.buffers`,
   `.children` and `.flatten` all fail it (AT-V9). The test also fails when `source_dates.py` imports anything but `pyarrow`, `pyarrow.compute`,
   the standard library and these names: `SourceDateUnrepresentableError` and `SourceDateTypeUnsupportedError` from
   `decoy_engine.io.bounded_reader`, and `CALENDAR_FIRST_DAY_NUMBER`, `CALENDAR_LAST_DAY_NUMBER`, `type_nodes` and
   `is_date_leaf` from `decoy_engine._arrow_types`. Names are allowed, not whole modules, so a walk moved into a helper
   is caught. The type walk calls `field(i)` on types in
   `_arrow_types.py`, so `source_dates.py` needs no allowance. Runtime invariant: the counting function returns 0 for a type that
   holds no date, and raises an internal error for a type that holds a date but is not a plain date leaf or a top-level
   dictionary of one, so a gate that lets a container through fails loudly instead of counting (M-25). The date-leaf
   predicate `is_date_leaf` (date32, date64 or timestamp) lives in `_arrow_types.py` beside the walker, and both the
   gate and the counting function use it.
4. One outside-calendar mask, then the dictionary repair. `_outside_mask(values)` returns the per-cell boolean mask of
   cells outside years 1 to 9999, including the zoned local-time band (`source_dates.py:127-135`). For a zoned column the mask is
   the UTC mask OR the same test over `local_timestamp` of the same unfiltered cells, so both masks line up cell for
   cell and no `if_else` or `filter` is needed (today's code filters before `local_timestamp`, which the shared mask
   cannot use). `local_timestamp` wraps silently near the int64 extremes, but any cell there is already outside in
   the UTC mask, and the OR keeps it outside, so the wrap cannot clear a cell. The count uses it,
   and so does the repair: for a top-level dictionary, the mask over the dictionary entries. Once a dictionary column
   passes, any outside entry is unused. Build `keep = fill_null(invert(mask), True)` (a null entry is kept), compute
   `cumulative_sum` in `int64`, take the remap by the indices and cast back to the index type (signed or unsigned).
   Do this chunk by chunk with `filter` and `take`. The surviving entries keep their order, unused in-calendar entries
   and null entries stay, and the index type and the `ordered` flag stay. A column with no outside entry comes back as
   the same object. There is no re-encode. Probe: entries `[D, null, FAR, D2]` with `uint8` indices `[0, 1, 3]` give
   entries `[D, null, D2]` and indices `[0, 1, 2]`, so a row that points after a null entry keeps its value.
5. Not covered: bytes under a null slot of a plain leaf. Arrow leaves them undefined, no conversion reads them (probe),
   and the Parquet and CSV writers do not write them. Arrow IPC copies buffers as they are, so a caller that passes
   such bytes in gets its own bytes back in an Arrow return. Follow-up G-9, not a V1 item.

**Table name (finding 7).** The table name in a refusal is the name the caller gave the source: the key of the
`sources` mapping, or the configured table on the single-source chunked entries. `check_resident_sources` binds each
lazy source to its key with `dataclasses.replace(source, table=name)`, only when `dataclasses.is_dataclass(source)`
and `table` is one of `dataclasses.fields(source)`; anything else passes through as today. The run reads the bound
copy. A lazy source is a frozen dataclass and `replace` keeps the subclass, so the CSV and fixed-width lazy sources bind
too. A source built with another `table=` is rebound to the key. `io` must not import `profile`, so `io` types the
argument with a small `Protocol` that has a `table` field; `profile/_readers.py` gets no new method. The tests build
`LazySource(path)` with no `table=`, so a missing binding cannot hide behind the fixture.

Where the binding runs on each route, traced at `2fab8cb9f`:
- FF, AUTO, SEQ and OOC through `run_pipeline`: `check_resident_sources` runs at `execution/_pipeline.py:298`, before
  `build_run_context` and every route dispatch, so every route reads the bound sources. Only `resolve_subset` and the
  checked loader come earlier (`:291-292`), and they read through `source_loader`, not `sources`. SEQ gets its loader
  from `run_pipeline` after that line (`_pipeline_route_exec.py:152`), so a lazy source it materializes carries the
  bound name. A direct `run_sequential` call takes only a `source_loader`, which `checked_loader` names per table.
- `run_fk_out_of_core` and `PandasExecutionAdapter.run` call `check_resident_sources` at their own entry (the
  `_SELF_CHECKED` rows).
- ISO: `run_pipeline_isolated` takes resident tables only (`_isolated_run.py:147`), stages them to Parquet or IPC
  (`_isolated_commit.py:159`) without converting them, and the child rebuilds each lazy source as
  `LazySource(path, table=name)` from the manifest key (`_isolated_worker.py:97`) and calls `run_pipeline`, which
  binds again at `:298`. So the parent does not bind before dispatch: the name crosses the process boundary as the
  manifest key, and the child binds. With `isolate=False` the in-process path calls `run_pipeline` directly
  (`_isolated_run.py:322`). AT-V7 runs the ISO cell both ways.

**AT-V1 guard (DESIGN finding).** Move the static guard to `tests/sentry/test_source_date_read_guard.py` and make
every allowance per function:
- `_DOWNSTREAM_FUNCTIONS: dict[tuple[str, str], str]`, keyed by file and qualified function name and holding a reason,
  replaces `_DOWNSTREAM_FILES`. No file-level exemption remains.
- A function is a sink site when it calls `to_pandas`, `to_pandas_fk_safe` or a name in the closed set
  `_CONVERSION_HELPERS`: the conversion wrappers in `internal/pandas_compat.py` (today `table_to_pandas_exact_ints`).
  The rule is not transitive: being listed in `_DOWNSTREAM_FUNCTIONS` does not make a function's callers sinks. A
  transitive rule by simple name reaches about 3,477 functions (Dennis's simulation), which no one can review; the
  closed set gives about 28 entries. The guard asserts that `_CONVERSION_HELPERS` equals the set of sink sites in
  `internal/pandas_compat.py`, so the set cannot drift from the file. Accepted gap: raw data passed to a function
  already listed in `_DOWNSTREAM_FUNCTIONS` is caught only by the AT-V1 runtime route tests, not by this static guard.
  A new wrapper in `internal/pandas_compat.py` that calls `to_pandas` is itself a
  sink site, so it must be listed, and listing it as a conversion wrapper adds it to `_CONVERSION_HELPERS`.
- Every sink site is in `_SELF_CHECKED` (and still calls its checks) or in `_DOWNSTREAM_FUNCTIONS`. Every entry still
  exists and is still a sink site, so stale entries fail.
- A check result must be used. Anywhere in `src/decoy_engine`, a call to a name in `_ANY_CHECK` used as a bare
  expression statement fails the guard, because `check_source_dates` returns the repaired data and a caller that
  drops it converts the unrepaired table. Passing the result as an argument (`_chunked.py:459`) or assigning it is
  fine. `check_source_schema` returns `None` by design and is not in `_ANY_CHECK`. The rule misses an assigned
  result that is then ignored (V2-LOG G-11).
- The scan takes the module texts as an argument (default: the repository files), so a test can seed code in memory.
- Seeded bypasses: (1) `def _seeded_entry(source): return source.to_pandas()` appended to
  `execution/_pandas_adapter.py`, a file exempt as a whole today; (2) a new module with
  `def run_seeded(chunks): return [table_to_pandas_exact_ints(c) for c in chunks]`, which forwards raw chunks to the
  existing helper in `internal/pandas_compat.py`; (3) a `_SELF_CHECKED` function seeded with `check_source_dates(t,
  table=n)` as a bare statement followed by `t.to_pandas()`. The guard must name all three.
- If the first full `_DOWNSTREAM_FUNCTIONS` listing passes 40 entries, stop and report. How big an allowlist can be
  reviewed is a design question, not one to work around.

**Module size.** No cap, ceiling or ratchet is raised; a file that would need a higher pin is a stop.

| File | Lines at `2fab8cb9f` | After 4.4b | Rule |
|---|---|---|---|
| `io/source_dates.py` | 243 | about 240: loses the hand walk (`_children`, `_holds_dates` recursion, the re-encode), gains the schema gate, the shared mask and the repair | under GOAL 600, no entry |
| `_arrow_types.py` | 259 | about 285: gains `type_children` and `type_nodes` | under GOAL 600 |
| `fileaccess/adapters/arrow.py` | 333 | about 315: the walker moves out, its callers import it | under GOAL 600 |
| `io/bounded_reader.py` | 434 | about 455: the new error class | under GOAL 600 |
| `reasons/runtime/_part3.py` | 573 | about 588: the new reason | under GOAL 600; if it passes 600 it takes a census entry per `tests/sentry/test_module_size.py` (ceiling at most loc + 20, never above 700) |
| `execution/native/_chunked_entry.py` | 689 (ceiling 689, MAX 700) | 689: no lines; the chunked entries already pass their table name and schema to `checked_chunks` | unchanged pin |
| `execution/_chunked_input.py` | small | a few lines for the eager schema gate in `checked_chunks` | under GOAL 600 |
| `profile/_readers.py` | 598 | at most 600: the binding lives in `io`; passing the footer schema to `checked_batches` edits existing calls, and any added line is offset in the same file | must stay at or under GOAL 600 |

**Why the six cases are right by construction.**

| Finding | Under 4.4b |
|---|---|
| unused nested dictionary entry reaches output | the column holds dates inside a container: refused at the type gate, nothing is returned |
| far date under a null parent leaks a year later | same |
| list view and run-end-encoded dates not checked | the generic walk sees their date children: refused |
| sliced map counts values outside the slice | a map is refused by type; no nested cell is counted |
| re-encoding an ordered dictionary changes its order | the repair keeps order; there is no re-encode |
| dictionary of structs fails to cast | refused by type before any cast; no uncoded Arrow error |

Full support for these columns is follow-up G-8. The survey gives the check (a logical view from `dictionary_decode`,
`run_end_decode`, `list_flatten`, a map cast to a list of structs and `StructArray.flatten`). The open part is the
output: either decode to a canonical type (output types change) or rebuild each type in place.

### 4.5 Placement

| Item | Place | Why |
|---|---|---|
| `DateDomain`, `DatePartition`, `DateRangeError`, range table | `transforms/date_preserve.py` (275 lines today, about 400 after) | `transforms/` is at its fan-out limit (CODEMAP "Transforms" row); the matching code it extends is already here |
| New reason | `reasons/runtime/_part3.py`, new `_catalog.runtime("DateRangeError")` binding | runtime reason home; `_part3.py` is 553 lines |
| Coded family row | `reason_adapter.py:44-70` `_CODED`: `("decoy_engine.transforms.date_preserve", "DateRangeError", "runtime")`, the defining module | without it the adapter and isolated-child classification report the refusal uncoded; `tests/unit/test_reason_registry.py:198-218` already checks every row resolves and gains a case that `reason_from_exception(DateRangeError(...))` returns the new code |
| S5 source boundary | Existing `io/bounded_reader.py` (CODEMAP.md:129), public checked Arrow reader API exported by `decoy_engine.io`. Error `SourceDateUnrepresentableError` in `io/bounded_reader.py:106`, code in `reasons/runtime/_part3.py`, adapter row `("decoy_engine.io.bounded_reader", "SourceDateUnrepresentableError", "runtime")` at `reason_adapter.py:57` | Profile and run readers may both import io under `.importlinter:22-25` |
| S5 shared type walker (4.4b) | `type_children` and `type_nodes` move from `fileaccess/adapters/arrow.py:150-169` to the bottom-tier `decoy_engine/_arrow_types.py` (259 lines), which `io/source_dates.py` already imports; `fileaccess/adapters/arrow.py` imports them back | one copy of Arrow's nesting rules for the file-access type checks and the date gate; both consumers already import the bottom tier, and the date gate is not file access, so it does not belong in `fileaccess`. `_array_children` and `_walk` stay in `fileaccess/adapters/arrow.py:172-190` and zip with the moved `type_children` order: use `strict=True` at line 189 wherever `_array_children` is not empty, and add a `tests/unit/test_arrow_types.py` case that pins `type_children` for each kind (extension, dictionary, map, struct, union, list kinds, list views, run-end-encoded) |
| S5 type gate (4.4b) | `SourceDateTypeUnsupportedError` beside `SourceDateUnrepresentableError` in `io/bounded_reader.py`; reason in `reasons/runtime/_part3.py`; adapter row `("decoy_engine.io.bounded_reader", "SourceDateTypeUnsupportedError", "runtime")`; gate, repair and lazy binding in `io/source_dates.py` | the existing error and check live there; no new module |
| S5 read guard (4.4b) | `tests/sentry/test_source_date_read_guard.py` (moved from `tests/unit/execution/test_source_date_unrepresentable.py`) | beside the other choke-point sentries |
| S5 type tests (4.4b) | `tests/unit/io/test_checked_source_dates.py` for the unit cases; route cases in `tests/unit/execution/test_source_date_unrepresentable.py` | the existing S5 test homes |
| User docs | `docs/strategies.md` (date strategies, `preserve_values`), `docs/reasons.md` generated entries, `changelog.d/` fragments | section 4.7 |
| Sentry | `tests/sentry/test_date_partition_choke_point.py` | beside the other choke-point sentries |
| Route matrix | `tests/parity/test_date_range_sentinel.py` | beside the D1c suites, reusing `_d1c_data.py` |
| Domain unit tests | `tests/unit/transforms/test_date_domain.py` | per-module unit home |

### 4.6 Design notes

- One place per fact: the range table and reach rule are in `date_preserve.py` only; the native and out-of-core code read them from the `DatePartition`, never restate them.
- Typed proof object (parse, do not validate): the partition is the evidence the check ran, so the rule holds by construction instead of by a helper each site must remember.
- No flag arguments: the domain is resolved from `(strategy, shape, cfg)`; there is no "skip range" switch.
- Value-free errors: the `WindowedDateError` pattern (`windowed_date.py:84-100`), raised outside any `except` so `__cause__` and `__context__` stay empty.

### 4.7 User documentation

Each slice documents the behavior it ships, in the same PR:

- `docs/strategies.md`, date strategies and `preserve_values` (S1, then extended by S2, S3, S4, S7):
  - declared sentinel dates are never shifted, perturbed or bucketed; they pass through unchanged;
  - a real date equal to a declared sentinel also passes unchanged (section 4.1 item 6);
  - declared sentinel rows are left out of the post-mask identity count and the report shows the count per column (S6);
  - an undeclared date outside a strategy's range stops the run with `runtime/date_outside_strategy_range`, and the message names only table, column, strategy and count;
  - the range per column type: text and zoned timestamps 1677-09-22 to 2262-04-10, typed `date` 0001-01-01 to 9999-12-31, each less the strategy's reach (Q1), with a worked example for `min_days`/`max_days` and for each bucket;
  - quarantine does not divert these rows (Q4);
  - `sentinel_to_null` versus `preserve_values` and the order they run in;
  - `group_by` with `preserve_values` (S2); windowed_date sentinel anchors give the anchor's sentinel in the derived column (S3, Q2); text_mask edge spans become the token (S4, Q5); generation excludes declared sentinels from the fit and emits them at their observed rate (S7, Q3).
- S5 documents which source columns are read (plain date and timestamp columns and top-level dictionaries of them), that a column holding a date inside a list, map, struct or other container is refused with `runtime/source_date_type_unsupported` whatever its dates are, the remedy (drop, select out or cast the column), and that an unused out-of-calendar dictionary entry is dropped with the order kept. It replaces `docs/strategies.md:403-405`.
- S5 documents the calendar limit at source ingestion and the compile-time distribution limit. A date outside the Python calendar cannot be declared. S7 documents fit declaration coverage, exact-value release and legacy refits. S8 documents the repeatable fit option with an end-to-end example.
- Reason docs: the new code and every deprecation get their registry summary and remediation text specific to the remedy for that code; `docs/reasons.md` is regenerated from the registry, not hand-edited.
- `changelog.d/` fragment per slice naming each new and deprecated code as a code span, and the behavior change (far dates refuse instead of `format_error`; typed edge sentinels refuse instead of shifting).

## 5. Behavior and failure modes

| Input | Before | After |
|---|---|---|
| in-range cell | masked | masked, same bytes (no change) |
| declared sentinel, in or out of pandas range | unchanged, counted | unchanged, counted (no change) |
| undeclared far text cell | `format_error` row error, quarantinable | refusal `date_outside_strategy_range` |
| undeclared far `timestamp_tz` cell | `format_error` | refusal |
| undeclared typed `9999-12-31` (date_shift with `max_days > 0`, any bucket) | shifted silently | refusal |
| undeclared typed `1600-01-01` | shifted | shifted (no change; inside 0001 to 9999 less reach) |
| text or tz date within reach of a pandas bound | key-dependent `OverflowError`, or Python answer, or native abort | refusal on every route and key |
| unparseable text | `format_error` | `format_error` (no change) |
| null | null | null (no change) |
| row outside a `when:` gate | passthrough | passthrough (no change) |
| far date on the out-of-core route, text or typed | `bucket_perturb_unparseable_no_row_channel` | refusal `date_outside_strategy_range` |
| windowed_date far anchor (S3) | `windowed_date_anchor_out_of_range` | `date_outside_strategy_range`, or the declared sentinel output (Q2) |
| text_mask span at the calendar edge (S4) | uncoded `OverflowError` | the redaction token, as for an unparseable span (Q5) |
| real date equal to a declared sentinel | unchanged | unchanged, counted in the post-mask report (S6) |
| `date32` beyond year 9999 (S5) | uncoded `ValueError` quoting the year | coded refusal `runtime/source_date_unrepresentable` naming table, column and count |
| a date inside a list, map, struct, list view, run-end-encoded, union or extension column, or a dictionary of anything but plain dates (S5, 4.4b) | passes, or an uncoded Arrow error, or a hidden far value reaches output | refusal `runtime/source_date_type_unsupported` naming table, column and container kind, in or out of the calendar (Q6) |
| ordered dictionary date column with an unused far entry (S5, 4.4b) | on the S5 branch: re-encoded in row order, unused valid entries lost | far entry dropped, order and unused valid entries kept |
| `LazySource` without `table=` in `sources` (S5, 4.4b) | refusal names table `source` | refusal names the mapping key |
| distribution generator fitted on a far date (S5) | uncoded `OutOfBoundsDatetime` or `ValueError` quoting a date | `plan/generation_unbounded_column`, value-free |
| statistical generation with a declared sentinel (S7) | `plan/generation_unbounded_column` | admitted; sentinel emitted at its observed rate |

Failure modes the design must not introduce: a sentinel counted as out of range (M-3); a refusal whose count or set depends on the key (M-9); a native route that computes a far row because it skipped the partition (M-4, sentry); a refusal message that quotes the cell (M-5); a half-written target (AT-R7).

## 6. Acceptance tests (red-first)

Each test records red on `f54ad388b` with the failing output in the builder report; cells marked "green on base" are regression locks. Test rows run on every route in section 10.2 that admits the strategy and shape, through the public entry. Expected values are literals or the output of an unconfigured run on in-range rows only, never the output under test.

Route set: FF (`run_pipeline` full_frame), AUTO (`run_pipeline` auto, native shadow when the companion is present), SEQ (`run_pipeline` sequential, a parent/child job, Python and `seq_native`), CH (`run_mask_pipeline_chunked`, chunk size 2), NCH (`run_mask_chunked`), OOC (`run_pipeline` out_of_core and `run_fk_out_of_core`, Python backend forced with `force_companion_unavailable` and native backend), ISO (`run_pipeline_isolated`, one cell per strategy).

### 6.1 Core matrix (S1), date_shift and bucket_perturb

| AT | Shape | Rows | Expected on every route | Red on base |
|---|---|---|---|---|
| AT-R1 | text `%Y-%m-%d`, text `%d/%m/%Y`, `date32`, `timestamp[us, UTC]` (date_shift only) | in-range only, plus a null | masked; output digest equal across routes (parity) | green on base |
| AT-R2 | same | in-range, declared `9999-12-31` and `0001-01-01`, null | sentinels unchanged, `date_preserve` count 2 per pair, other rows equal to AT-R1 | green on base for text; red for typed on OOC (H) |
| AT-R3 | same | in-range, undeclared `9999-12-31` | `DateRangeError`, code `date_outside_strategy_range`, message names table, column, strategy and a count of 1 | red: A, B, C, F, G, H |
| AT-R4 | text, tz | undeclared `2262-04-10` with explicit -30..30, jitter_days=30, defaults only, and reversed bounds 30..-30. Run each under two mask keys | refusal under both keys | red: E |
| AT-R5 | `date32` | undeclared `1600-01-01` | masked (inside the typed domain) | green on base |
| AT-R6 | text | `"not-a-date"` and `""` | `format_error` row error, as today | green on base |
| AT-R7 | text | (a) `run_pipeline(config, sink=<reference file TransactionalSink>, auto_chunk=True, auto_chunk_threshold_rows=2, chunk_size_rows=2)` with the undeclared far date in the third chunk (assert that the chunk route ran); (b) a two-table SEQ job through `run_pipeline(..., sink=...)` where table `a` is fully staged and table `b` refuses | refusal; the sink's `abort` ran, no table is published (neither `a` nor `b`), and no staged file is left | red (format_error today) |
| AT-R8 | text | undeclared far date in a row a `when:` gate does not select | run succeeds, the row is the source value | green on base |
| AT-R9 | text | undeclared far date, quarantine enabled for `format_error` | refusal; nothing quarantined | red |
| AT-R10 | all | undeclared far date seeded with a marker value | no marker in `str(exc)`, `repr(exc)`, the run log and the evidence; `__cause__` and `__context__` are None | red (no such error) |
| AT-R11 | text | the reach edges: for date_shift with -5..7, reversed 7..-5, jitter_days=30, and defaults only, cells at hi, hi+1 day, lo, lo-1 day | hi and lo masked, the two outside refused | red at lo and hi edge (E) |
| AT-R12 | text, bucket month | cells one bucket inside each pandas bound and one day further | inside masked, further refused, on Python and native OOC alike | red (I) |

The CLI `--chunked` CSV staging (`decoy/src/decoy/cli/run/_execute.py:118-121`) is in the CLI repo and out of scope here; follow-up G-7 adds the same case as a CLI test.

Parity check (part of AT-R1, AT-R2): for every route pair the output table digest (`tests/parity/_d1c_data.table_digest`) is equal, and for AT-R3 and AT-R4 the error code, table and column are equal. The count is compared on FF, AUTO, SEQ and ISO, where the batch is the whole column; on CH, NCH and OOC it is the count of the refusing batch.

### 6.2 Config (S1)

- AT-C1: `preserve_values=["9999-12-31"]` resolves to `DateDomain.sentinels == frozenset({date(9999, 12, 31)})`, a `datetime.date`, never a `datetime64`. Green on base for the existing set.
- AT-C2: `"0000-01-01"`, `"10000-01-01"`, `"9999-13-01"` and `"2024-02-30"` are refused at plan compile with `date_shift_preserve_values_invalid` / `bucket_perturb_preserve_values_invalid`, path ending `.preserve_values`. Green on base.
- AT-C3: generate valid cfg mappings, including one-sided bounds, defaults, jitter, zero and reversed pairs. Check the partition window against `shift_window(cfg)` and its two edges against calendar bounds trimmed by that result. Check the resolved bucket and both edges for each bucket. Empty domains refuse at compile.

### 6.3 Group_by (S2)

- AT-G1: use interleaved groups, nonconsecutive indices and sentinels at the start and middle. Test date_shift with `group_by="patient_id"` and `preserve_values=["9999-12-31"]` on FF and SEQ: sentinel rows unchanged; every non-sentinel row of one patient shifts by the same offset as an unconfigured group_by run on the non-sentinel rows only. Red on base (compile refusal).
- AT-G2: the same with an undeclared far date: refusal. Red on base (compile refusal).
- AT-G3: a misaligned anchor snapshot still fails closed with `date_shift_group_anchor_snapshot_misaligned`. Green on base.

### 6.4 windowed_date (S3)

- AT-W1: an anchor `9999-12-31` declared in `preserve_values`: the derived cell holds `9999-12-31` (Q2); the row is counted. Red on base.
- AT-W2: an undeclared far anchor: `date_outside_strategy_range`. Red on base (old code).
- AT-W3: the offset check stays `windowed_date_offset_out_of_range`. Green on base.

### 6.5 text_mask (S4)

- AT-T1: spans `9999-12-31`, `12/31/9999` with a positive window and `0001-01-01` with a negative one come back as the token; the rest of the cell is masked as before. Red on base (OverflowError).

### 6.6 Post-mask check (S6, after PM-1)

- AT-P1: a date_shift column with declared `9999-12-31` rows that a date detector hits through its column name: the residual-PII grade counts the sentinel rows as neither comparable nor identical, so 100 percent sentinel rows do not grade `fail`. Red on base.
- AT-P2: the same column with one non-sentinel row left unchanged by a fault injection still grades `fail` (the exclusion does not hide a real leak).
- AT-P4: the post-mask report has, for that column, `declared_sentinel_rows` equal to the number of sentinel rows, and the column grade text says those rows were excluded. A column with no `preserve_values` has no such field.
- AT-P3: `timestamp[us]` and `date32` far dates in source and output are read without an exception (PM-1 owns the cell walk; this test only runs the runner end to end).

### 6.7 Value-free refusals (S5)

- AT-V1: place an unrepresentable date32 at row 10,001 in a later Parquet row group. Run FF, AUTO, SEQ, CH, NCH, OOC and ISO with an ordinary first 10,000 rows. Also exercise a first-batch profile failure, a resident table, a caller loader, opened batches and direct OOC. Assert runtime/source_date_unrepresentable, correct table, column and batch count, no year in the error, log or child result, empty cause and context, and no publication. Cover both ends for date32/date64 and each timestamp unit where such values exist, null-only batches, valid calendar endpoints and a timezone offset crossing a calendar endpoint.
- AT-V2: compile a distribution generator with max 9999-12-31, min 0001-01-01, and an unsupported live bin between otherwise ordinary inputs as separate fixtures. The compile entry and a direct generator call both refuse with plan/generation_unbounded_column, before any draw. Assert no cell or bound in the message and empty cause and context. Exercise valid partial years at each ns boundary.

Section 4.4b tests. Each is red at `2fab8cb9f` (the S5 branch head that Codex round 2 reviewed) and is written before the fix. Value-free means: no year, day number, count of nested cells or child field name in `str`, `repr`, the log or an isolated child result, and empty cause and context.

- AT-V3 (findings 1, 2 and 6). One column each: `list<date32>`, `large_list<timestamp[us]>`, `fixed_size_list<date32>`, `struct<date32>`, `map<string, date32>`, `list<dictionary<date32>>` with an unused far child entry, `dictionary<struct<date32>>`, and a struct and a list with a far date under a null parent. Referenced dates are all in the calendar. Run CH and NCH, and FF and AUTO with a resident source; repeat the Parquet-storable ones as a `LazySource` file. Add an empty Parquet file and an empty resident table with a `list<date32>` column: both refuse the same way, the lazy one before the profile head reads a batch. Each refuses `runtime/source_date_type_unsupported` naming table, column and the outermost kind, value-free, with nothing published and nothing returned. No `ArrowNotImplementedError` and no `ValueError` reaches the caller. Red: both chunked APIs succeed and return the far child entry (finding 1), the public oracle raises `ValueError: year 10183 is out of range` (finding 2), and the dictionary of structs raises `ArrowNotImplementedError` (finding 6).
- AT-V4 (finding 3). `list_view<date32>` and `run_end_encoded<int32, date32>`, each with a far date and with in-calendar dates only, plus a `pa.ExtensionType` subclass over `date32`, `opaque(date32)` with a far date, `fixed_shape_tensor(timestamp[us], [2])` with a far date, and a dense union with a `date32` member: each refused with its kind, value-free. The list view and `opaque` cases skip when `pa.list_view` or `pa.opaque` is missing (pyarrow 14 has neither); the others always run. A plain `time64`, a plain `duration`, `list<time64>` and `struct<duration>` pass the gate unchanged (no date leaf). Red: list view and REE pass the check and native returns the far value.
- AT-V5 (finding 4). A `map<string, date32>` sliced so that the row with a far date is outside the slice and an in-calendar row stays: refused with `source_date_type_unsupported`, kind `map`, and no count. Red: the S5 head reports `source_date_unrepresentable` with count 1. The refusal of this valid-looking job is the Q6 contract; if the owner picks Q6 (B), this test becomes "passes, and the output holds no far value".
- AT-V6 (finding 5). An ordered `dictionary<int8, date32>` with entries `[D2, FAR, D1, D3]` and indices `[2, 0, null, 2]` (rows reference D1 before D2, the reverse of entry order; D3 is valid and unused). After the check: entries `[D2, D1, D3]`, indices `[1, 0, null, 1]`, `ordered=True`, index type `int8`, logical values equal to the input's; the pandas categorical has categories `[D2, D1, D3]`, is ordered, and its minimum is D2. Repeat as a two-chunk column with different dictionaries and as a record batch. Add entries `[D, null, FAR, D2]` with `uint8` indices `[0, 1, 3]` (a referenced null entry before FAR and a row after it): entries `[D, null, D2]`, indices `[0, 1, 2]`, no row turned null. Add a negative-offset zone (`America/Adak`, UTC-10) whose unused entry is in year 1 in UTC but in year 0 in local time: it is dropped, and a referenced copy counts 1. Add a zoned `timestamp[us, tz=Pacific/Kiritimati]` dictionary whose unused entry is inside year 9999 in UTC but in year 10000 in local time: it is dropped like FAR, and the count of a referenced copy of it is 1. End to end through NCH and FF, the output column has the source type and entry order. Red: the S5 head re-encodes in row order (`[D1, D2]`) and drops D3.
- AT-V7 (finding 7). `sources={"t": LazySource(path)}`, no `table=`, with a far date after the profile sample: FF, AUTO, SEQ (parent and child), OOC and ISO refuse with table `t`. `LazySource(path, table="other")` under key `t` reports `t`. Repeat once with a CSV lazy source. Red: the S5 head reports `source`.
- AT-V8 (DESIGN finding). In `tests/sentry/test_source_date_read_guard.py`: the three seeded bypasses of section 4.4b (direct conversion, forwarding to `table_to_pandas_exact_ints`, a dropped check result) are each named by the guard; a seeded stale `_DOWNSTREAM_FUNCTIONS` entry fails; the repository as it is passes. Red: the file-level guard at the S5 head passes all three seeds.
- AT-V9 (rule 3 of 4.4b). An `ast` test over `io/source_dates.py` fails on any `pc.` call or attribute outside the allowlist and on any import outside the allowed modules; a seeded `pc.list_flatten(column)` and a seeded `.storage` each fail it. A unit test calls the counting function with a `list<date32>` column and expects the internal error. Red: the S5 head uses `.keys`, `.items`, `.flatten()` and `pc.list_flatten`, and counts the list instead of raising.
- Locks, green at the S5 head: in-calendar plain and top-level dictionary date columns come back as the same object; columns with no date inside (`struct<a: int64>`, `list<int64>`, `dictionary<struct<a: int64>>`, `map<string, int64>`) pass unchanged on every route.

### 6.8 Generation (S7)

- AT-F1: statistical generation whose snapshot is fitted from a column with undeclared `9999-12-31`: `plan/generation_unbounded_column`, value-free, as today. Green on base (lock).
- AT-F2: call distribution_snapshot_document(df, include_values=True, preserve_values_by_column={"end": ["9999-12-31"]}), load the persisted v2 document with the matching generation declaration, compile and generate. Assert exact count, sentinel-free ordinary bounds and bins, and sentinel frequency within a fixed-seed binomial 99.9 percent interval over 1,000 rows. Repeat with an in-range sentinel mixed with ordinary dates in its year, nulls, all-sentinel, all-null, zero observed, a declaration mismatch and a legacy refit. Exercise both date generators. Check that refused redacted/DP fits publish nothing and forged or ill-typed sentinel blocks fail value-free. S8 repeats the round trip on CSV with `decoy fit --parse-dates end --preserve-date end=9999-12-31 --include-values`, including the sampled-CSV path. Repeating the option covers multiple declarations. A malformed declaration or missing release option fails without printing its argument or writing a partial snapshot.
- AT-F3: `quality/snapshot.py` `_datetime_stats` and `profiling/_distributions.py` `_distribution_date` over object `datetime.date` values `[2020-01-01, 9999-12-31]`: through their public fit/profile dispatch both report a maximum on 9999-12-31 and count the far row once (snapshot year 9999, profile decade 9990s) (stats are computed on calendar dates, not ns). Then AT-F1 is the coded refusal a user sees, and nothing is dropped in silence. Red on base (M).
- AT-F4: a generation `windowed_date` whose statistical anchor column declares `9999-12-31`: admission uses the anchor's sentinel-free `min`/`max` and admits it; derived cells for sentinel anchors follow Q2. Red on base (L3).
- S7 known limits (found in S5 Codex round 3, both on main today): the whole-table statistical sampler (`generation/statistical/_sample.py:493-502`) reads `min` and `max` with `datetime.fromisoformat`. Equal bounds ending `.123456789`: Python 3.10 refuses at compile, 3.11 compiles and draws `.123456`, below the fitted minimum. Equal bounds ending `+01:00` compile on both, then draw raises an uncoded `TypeError` comparing an aware bound with a naive draw. S7 must fix both with one admission shared with `_window_admission._check_datetime`.

### 6.9 Existing tests whose expectation changes

These change because of the owner decision, and the builder's report lists each with the old and new expectation. Any other changed or deleted assertion is a stop (plan contract class 8):

- `tests/parity/_d1c_data.py` and `test_phase_d_d1c_oracle.py:79-100`: baseline runs that hold an undeclared `9999-12-31` move it into AT-R3; the "survives by accident" assertion is removed.
- `test_phase_d_d1c_ooc.py:35`: `_OOC` base lists keep the near-bound and far values declared only.
- `test_phase_d_d1b1_bucket_native.py:263-345`: the native range guard tests move to AT-R12 with the new code; "masks on the python path" for a near-bound date becomes a refusal.
- `test_date_shift_typed_edges.py:74-93`: `9999-12-31` under a positive window becomes a refusal; `9999-06-01` still shifts.

## 7. Mutations

Each runs on the final head (catalog class 9) and must turn the named test red.

| ID | Mutation | Turns red |
|---|---|---|
| M-1 | `partition` never raises (count forced to 0) | AT-R3, AT-R4, AT-R7, AT-R9 |
| M-2 | reach ignored (0 days) | AT-R4, AT-R11, AT-R12 |
| M-3 | range checked before sentinels | AT-R2 |
| M-4 | `native_bucket_perturb`'s `partition` gets a default `None` and the seam stops passing it | sentry, AT-R3 on NCH and OOC native |
| M-5 | the refusal message includes the first refusing cell | AT-R10 |
| M-6 | OOC Python path calls `apply_bucket_perturb` without partitioning | sentry, AT-R3 on OOC |
| M-7 | refusal recorded as a `format_error` row error instead of raised | AT-R9, AT-R3 |
| M-8 | typed `date` shape uses the pandas domain | AT-R5 |
| M-9 | reach taken from the keyed offset of each row | AT-R4 (two keys) |
| M-10 | the strptime retry dropped, so a far text cell is a `format_error` | AT-R3 text cells |
| M-11 | S2: after checking the full companion, skip its positional slice and send all anchor rows into the grouped computation | AT-G1 |
| M-12 | S6: exclusion applied to every identical row, not only sentinel rows | AT-P2 |
| M-13 | a stale partition: the chunk loop reuses chunk N's partition for chunk N+1 | AT-R3 on CH and NCH with the far date only in chunk 2; the length/index check unit test |
| M-14 | the internal native range invariant deleted | the text/tz seam invariant unit test (typed historic dates still pass AT-R5) |
| M-15 | a listed primitive renamed | sentry (name no longer resolves) |
| M-16 | a new helper adds `timedelta` to a typed date outside the primitive list | sentry |
| M-17 | `DateRangeError` row removed from `_CODED` | `tests/unit/test_reason_registry.py` new case; AT-R3 on ISO |
| M-18 | S5: the reader refusal message includes the year | AT-V1 |
| M-19 | S6: `declared_sentinel_rows` omitted from the report | AT-P4 |
| M-20 | S7: declared sentinels left in the fitted year bins | AT-F2 |
| M-21 | S5: `_holds_dates` walks a fixed list of container kinds without list view and run-end-encoded | AT-V4 |
| M-22 | S5: the dictionary repair re-encodes instead of filtering and remapping | AT-V6 |
| M-23 | S5: `check_resident_sources` skips the lazy-source binding | AT-V7 |
| M-24 | S5: the read guard exempts `execution/_pandas_adapter.py` as a whole file again | AT-V8 seed 1 |
| M-25 | S5: the type gate lets `struct` through to the counting function | AT-V3 (the internal error), AT-V9 runtime case |
| M-26 | S5: the type walker follows `pa.ExtensionType` instead of `pa.BaseExtensionType` | AT-V4 `opaque` and `fixed_shape_tensor` cases |
| M-27 | S5: the date leaf test is `pa.types.is_temporal`, so `time64` counts as a date | AT-V4 `time64` and `duration` pass cases |
| M-28 | S5: the repair builds `keep` without `fill_null`, or runs `cumulative_sum` in the index type | AT-V6 null-entry and `uint8` cases |
| M-29 | S5: the read guard stops flagging a bare check-call statement | AT-V8 seed 3 |

## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with `replaced_by=None` (allowed by `reasons/_registry.py:202-209`, section 4.3): `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
- New reason `runtime/source_date_unrepresentable` (`since=UNRELEASED`, S5).
- New reason `runtime/source_date_type_unsupported` (`since=UNRELEASED`, S5, section 4.4b) and public error class `SourceDateTypeUnsupportedError`. Behavior: a source column holding a date inside a container is refused (Q6).
- Post-mask report: new per-column field `declared_sentinel_rows` (S6, additive).
- Config and snapshot: S7 admits preserve_values on date generators. Store optional stats.sentinels beside year_bins within distribution-snapshot/v2. Only bucket entry models forbid extra fields (contracts/distribution_snapshot.py:47,58,68). Existing v2 readers ignore the new field and emit no sentinel from it. An all-sentinel fit has no ordinary distribution for an older reader to sample. Round-trip old and new snapshots, exercise the pre-S7 reader, and run the full engine suite for this writer change.
- Config: `preserve_values` becomes valid on `windowed_date` (S3, additive). No other config key changes.
- Behavior: far dates that were `format_error` row errors become refusals; typed edge sentinels that were shifted become refusals. Output bytes for in-range and declared rows are unchanged (AT-R1, AT-R2 digests against base).
- Evidence: the `date_preserve` metric keeps its shape; the `out_of_core_bucket_perturb` disposition loses its native range reason value (internal).
- Checks: `python scripts/release/reason_release_pin.py --check` and `python scripts/dev/registry_renumber.py --check --main origin/main` pass on every slice that touches reasons.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| Class | Applies | How |
|---|---|---|
| 1 Anchored validation | yes | the literal pattern stays `re.fullmatch` (`date_preserve.py:52`) |
| 2 Strict wire and stored types | yes | `preserve_values` must be a list of `str`; the domain holds `datetime.date` only (AT-C1, AT-C2) |
| 3 No exception context | yes | `DateRangeError` raised outside any `except`; AT-R10 checks `__cause__` and `__context__` |
| 4 Versioned read models | yes | Existing v1 and v2 reads, strict sentinel block, missing/unknown version refusal, old-reader and pin round trip (AT-F2) |
| 5 Normalized guard scanners | yes | the sentry resolves module aliases, imported aliases and unbound methods. Seed each supported spelling, including copy.deepcopy and an aliased deepcopy |
| 6 No reaching into private modules | yes | native and out-of-core import `DateDomain` from `transforms.date_preserve`, which is already imported there |
| 7 No hidden CI failures | no | no CI step changes |
| 8 One input, one trust class per entry point | no | no user-chosen name or path |
| 9 Mutations on the final head | yes | section 7 |
| 10 Allowlisted helpers are still checked | yes | the allowlist names module and function. Check callers of every allowlisted forwarding helper and seed a bypass through one |
| 10b Renamed helpers stay checked | yes | the sentry fails when a listed primitive no longer resolves (M-15) |
| 11 No raised caps | yes | module-size ceilings move only by the lines added; `transforms/` fan-out stays at its limit (no new module) |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the refusal message is built from table, column, strategy and a count only, raised with no context; S5 removes the two value-bearing errors (reader year, sampler date) | AT-R10, AT-V1, AT-V2 | M-5, M-18 |
| 2 | Cleanup missing on an exit path | the refusal raises inside the strategy call, so the existing transactional sink abort and isolated work-root cleanup run as for any coded refusal | AT-R7 (no target file, no outputs) | M-7 |
| 3 | State machine and concurrency | N/A: the partition is a pure function per batch; no shared state is added | AT-C3 property test | N/A: no state transition added |
| 4 | Route parity and silent fallback | one `DateDomain` per column and a required `DatePartition` on every compute primitive; the native range decline that sent near-bound text to Python is removed | AT-R1 to AT-R12 across section 10.2, the digest parity check, the sentry, the stale-partition check | M-1, M-4, M-6, M-8, M-13, M-15 |
| 5 | Referential integrity | a far parent key is partitioned on the parent; child keys remap through it; child-side `preserve_values` stays refused | section 10.3, existing `test_phase_d_d1c_fk.py` green | M-3 |
| 6 | Untrusted producer | Snapshot blocks and pins are validated before use | AT-C2, AT-F2 | restore a withheld sentinel block or coerce a string count |
| 7 | Check then use on a path (TOCTOU) | N/A: no file path is checked or opened by this change | none needed | N/A: no path handling |
| 8 | Weak tests and overclaimed evidence | every AT records red on `f54ad388b` or is marked green on base; section 6.9 lists every changed expectation; expected values never come from the output under test | builder report with base SHA and red output | each mutation names its test |
| 9 | Behavior-preserving refactor drift | the `preserved` mask becomes `partition.sentinels`; in-range and declared outputs keep their bytes | AT-R1, AT-R2 digests equal to base | M-3 |
| 10 | Frozen contract drift | section 8: both runtime codes, deprecations, generation config and the v2 writer contract | reason registry tests, `scripts/release/reason_release_pin.py --check` | M-7 |

## 10. Enumerations

### 10.1 Exit paths

- Handler raises `DateRangeError` (FF, AUTO, SEQ, CH, NCH): the pipeline error path; the transactional sink captures the failure and aborts; nothing published (AT-R7).
- Chunked generator APIs (`run_mask_chunked`, `run_mask_pipeline_chunked`) with no sink: the generator raises at the refusing chunk; chunks already yielded belong to the caller, as for every other mid-stream refusal. Documented, not changed.
- OOC (`run_fk_out_of_core`): raises inside the batch mask before the batch is written; the scratch directory and sink abort run as for `bucket_perturb_unparseable_no_row_channel` today (`out_of_core/_bucket_native.py:283`).
- Isolated child: the refusal is a child failure and is classified with its code, no publication.
- Plan compile (S2, S3): config refusals as today; no new compile exit.

### 10.2 Routes

| Route | Entry | date_shift | bucket_perturb | After |
|---|---|---|---|---|
| full_frame pandas | `_strategies/_date_shift.py:251`, `_strategies/_bucket_perturb.py:181` | A, B, C, D, E | A, F | partition in handler |
| full_frame native shadow (AUTO) | `native/_operator_step.py:459`, `:488` | A, E | A | partition in the step |
| sequential Python and `seq_native` | `_sequential_native.py:395`, `:540` | A, C | A, I (near-bound declines to Python) | partition in the seam; decline at `:398` removed |
| chunked oracle | handlers per chunk | A (count per chunk) | A | partition per chunk |
| native chunked | `native/_operator_step.py:279` | A, E | A | partition per chunk |
| out_of_core, Python backend | `out_of_core/_mask_group_c.py:452` | not admitted (`out_of_core/_compat.py:84`) | G, H | partition before `apply_bucket_perturb[_dates]` |
| out_of_core, native backend | `out_of_core/_bucket_native.py:263` | not admitted | G, H, I (native abort) | partition before the kernel; abort removed |
| isolated | child runs one of the above | as the child route | as the child route | same |
| windowed_date (S3) | `transforms/windowed_date.py:324` | n/a | n/a | J becomes the shared code |
| text_mask span (S4) | `transforms/text_mask.py:443` | n/a | n/a | K becomes the token |
| source read (S5) | checked resident and batch reads feeding profile and execution | O | O | coded value-free refusal |
| distribution generator (S5) | `generators/_distribution.py:276` | n/a | n/a | L coded value-free |
| statistical generation fit (S7) | `quality/snapshot.py:491`, `profiling/_distributions.py:105` | n/a | n/a | M counted, sentinels excluded when declared |
| statistical generation admission (S7) | `generation/_window_admission.py:128-170`, `:290-320` | n/a | n/a | L2, L3 sentinel path |
| statistical sampler (S7) | `generation/statistical/_sample.py:493`, `_degenerate.py:122` | n/a | n/a | emits declared sentinels at their rate |

### 10.3 FK shapes

- Single, composite and multi-hop parent keys masked with date_shift or bucket_perturb: the parent column is partitioned once; children remap through the parent mapping (`test_phase_d_d1c_fk.py:99`), so a far parent key refuses before any child is written.
- Child key carrying `preserve_values`: stays a compile refusal (`date_preserve_values_unsupported_fk_shape`, `plan/_checks_date_shift.py:334-374`).
- Orphan child rows under `orphan_policy: preserve`: an orphan's own value goes through the parent handler (`test_phase_d_d1c_fk.py:115`), so it is partitioned the same way.
- Self-referencing and cross-table cycles: N/A: no FK walk changes; the partition is per column.

### 10.4 Fields

- `DateDomain`: `sentinels` (`frozenset[datetime.date]`), `date_format` (`str | None`), `low` and `high` (`datetime.date`), `strategy`, `shape`.
- `DatePartition`: `sentinels` (bool mask), `compute_rows` (int positions), `sentinel_count`.
- `DatePartition` also carries `source` and `parsed` (the cleared values) and the resolved window or bucket, and is immutable.
- `DateRangeError`: `code`, `table`, `column`, `strategy`, `count`; message from these only.
- Post-mask column facts (S6): `declared_sentinel_rows` (int).
- Snapshot (S7): `sentinels`, a list of `{date, count}`.
- `date_preserve` metric: unchanged (`execution/_adapter.py:329-345`).

### 10.5 Output surfaces

- Returned tables and published files: unchanged bytes for in-range and declared rows; no table on refusal.
- Errors: the new coded refusal replaces `format_error` (far cells), `OverflowError` (near-bound shift), and two out-of-core codes.
- Row errors and quarantine: far cells no longer produce `format_error` rows.
- Logs: no new log line; the refusal is logged by the existing error path with the message above.
- Evidence and metrics: `date_preserve` counts unchanged; the out-of-core bucket disposition drops the native range reason.
- Post-mask report (S6): sentinel rows excluded from identity counts, and the excluded count shown per column (`declared_sentinel_rows`).
- CLI stdout, stderr, `--json`, exit code: the CLI maps engine codes generically; a hint for this code is follow-up G-4.

## 11. Reuse inventory

- `PreserveSet` matching, `_strptime_date` retry and `render` (`date_preserve.py:160-224`), extended in place into `DateDomain`.
- `preserve_config_problem` (`date_preserve.py:84`) and `check_date_preserve_values` (`plan/_checks_date_shift.py:376`) for config validation.
- `_BUCKET_REACH_DAYS` (`native/_bucket_perturb_ext.py:88`), moved into the range table.
- `SUPPORTED_MIN` / `SUPPORTED_MAX` (`windowed_date.py:71-72`) as the windowed domain.
- The `WindowedDateError` value-free error pattern (`windowed_date.py:84-100`).
- `record_date_preserved` (`execution/_adapter.py:329`) for counts.
- Test harnesses: `tests/parity/_d1c_data.py`, `tests/unit/strategies/test_date_shift_typed.py` (`_cfg`, `_run`, `run_sequential_typed`), `tests/parity/_d1a_hash_data.run_chain`, `force_companion_unavailable`, `tests/native/_chunked_entry_support.key_provider`.
- Pre-scan sentinel list (`profiling/sentinels.py:36-44`) for G-4.

## 12. Interface with PM-1 (post-mask check)

PM-1 (`fix/postmask-fail-closed`, `2026-11-27-pm1-canonical-cell-walk.md`) owns how a cell is read, keyed and compared, including far dates through `.asm8` and attosecond `Instant`s, so the post-mask runner does not crash on `9999-12-31`. This row does not touch that walk.

This row adds one input to the residual-PII identity count: for a column whose strategy has a `DateDomain`, `_add_identity` (`verification/postmask/_column_facts.py:235`) receives the source batch's sentinel mask from a matching-only call on the domain (no range check, since the run already refused far rows) and leaves those rows out of `comparable` and `identical`. The interface is that one mask: PM-1 decides whether two cells are equal; this row decides which rows were allowed to be equal. S6 merges after PM-1 and rebases on its `_column_facts.py` (on the inspected PM-1 checkout `_add_identity` is at line 294). Intersect the mask with the strategy-selected rows and use the anchor source for Q2. A bypassed row must not disappear from the identity count merely because its value matches a declaration. The runner also writes the excluded count to the column's report entry, so a user sees how many rows the declaration kept unmasked.

## 13. Pre-mortem

- A real date near a pandas bound in text is now refused (for example `2262-04-05` with `max_days=30`). Such dates are almost always placeholders; the message says to declare them. G-2 tracks widening the text path to the Python calendar if a customer needs it.
- A user relied on quarantine to divert sentinel rows. After S1 the run refuses instead (Q4, decided). The changelog entry states it and names `preserve_values`.
- The sentry misses a new primitive added later. The `pd.to_datetime` allowlist check fails for any new module that parses strategy input without being in the primitive list.
- A typed source whose shape the plan cannot prove (`ColumnShape.UNKNOWN`) takes the text domain. That is the narrower one, so it fails closed.
- The partition adds a pass over each batch. It reuses the parse the strategy already does (the partition returns the parsed series to the primitive on the text path), so the extra cost is one comparison per row.
- A user declares a sentinel that is also a common real date (`1900-01-01`, `1970-01-01`). Those real rows pass unmasked. The docs say so and the post-mask report shows the count per column (S6, AT-P4).
- S2 lands without S1. It cannot: S2's tests depend on the refusal. The After order in section 14 enforces it.

## 14. Slices and risk

| Slice | Repo | Content | After | Risk | Test depth |
|---|---|---|---|---|---|
| S5 | engine | Checked Arrow ingestion with the section 4.4b type gate, order-keeping dictionary repair, lazy-source binding to the mapping key and per-function read guard (AT-V3 to AT-V9), bottom-tier source errors and adapter rows, shared fitted distribution admission with the existing generation code, AT-V1 and AT-V2, user and reason docs, changelog | nothing | R2 | T1 plus full suite and layer checks |
| S1 | engine | `DateDomain`, bound `DatePartition`, `DateRangeError` and its `_CODED` row, range table, new reason, the required `partition` on six primitives and the 15 call sites, the internal native range invariant, OOC typed path through `apply_bucket_perturb_dates`, removal of the native decline and abort, deprecation of the native range reason, sentry, AT-R1 to AT-R12 and AT-C1 to AT-C3, section 6.9 test updates, user docs for the S1 behavior (section 4.7), changelog fragment | S5 (shared ns bounds) | R2 | T1 plus the full engine suite (reason registry, frozen behavior) |
| S2 | engine | `group_by` with `preserve_values` on the Python path, two deprecations (`replaced_by=None`), AT-G1 to AT-G3, docs paragraph, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S3 | engine | `preserve_values` on `windowed_date` anchors, derived cell holds the anchor's sentinel (Q2), the anchor range on the shared code, deprecation, AT-W1 to AT-W3, docs, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S4 | engine | text_mask edge overflow becomes the token (Q5), AT-T1, docs sentence, changelog fragment | nothing | R1 | T1 |
| S6 | engine | post-mask sentinel exclusion and `declared_sentinel_rows` per column, AT-P1 to AT-P4, docs, changelog fragment | S1, S3 (derived anchors) and PM-1 (#784) merged | R2 | T1 plus the T2 gate set |
| S7 | engine | date generation: per-column fit kwarg, policy-aware snapshot writer and sentinel counts, matching generation declaration, admission (`_window_admission.py:128-170`, `:290-320`) and sampler (`_sample.py:493`, `_degenerate.py:122`) emitting sentinels at their rate (Q3), calendar-date stats in `_datetime_stats` and `_distribution_date`, AT-F1 to AT-F4, docs, changelog fragment | S1, S3 and S5 | R2 | T1, T2 and full engine suite (snapshot writer) |
| S8 | CLI | Wire the per-column exact-fit option through fit_exact_snapshot, test CSV fit through generation, update command help, user guide and changelog | S7 engine API released and available to CLI | R2 | CLI suite and installed CLI/engine integration |

Each row is one PR. S4 and S5 can start independently. S1 follows S5 for the shared ns bounds. S2 and S3 follow S1. S6 follows S3 and PM-1. S7 follows S3 and S5 with S1 already merged. S8 follows the S7 engine release.

## 15. Owner decisions (product choices)

All five were answered by the owner on 2026-11-27: "recommended" for each. They are fixed for this plan.

- Q1, typed date columns. Decided: typed `date` columns (Parquet, database `DATE`) keep the 0001 to 9999 domain, less the strategy's reach. `9999-12-31` and `0001-01-01` are refused on the usual windows unless declared, and genuine historic dates such as `1600-01-01` still mask. Text and zoned timestamps use the pandas domain.
- Q2, windowed_date with a declared sentinel anchor. Decided: the derived cell holds the anchor's sentinel value, so "unknown admission" gives "unknown discharge". Never the source value of the derived column.
- Q3, generation. Decided: a declared sentinel is excluded from the fitted range and emitted at its observed rate, so downstream `= 9999-12-31` logic keeps working.
- Q4, quarantine. Decided: an undeclared far date refuses the run even when `format_error` quarantine is on. The remedy is to declare the sentinel.
- Q5, text_mask date spans at the calendar edge. This departs from the owner rule (a coded refusal), so it is a product call. Decided: the span becomes the redaction token, as an unparseable span already does. Free text holds dates the user never declared, one edge date in a note should not stop a run, and the token writes no source value (fail-closed). The other option was the coded refusal.

- Q6, date columns inside containers (section 4.4b). Open: the owner decides. Under 4.4b a column holding a date inside a list, large list, fixed-size list, map or struct is refused even when every date is inside the calendar. Parquet sources can carry such columns (event and analytics exports), and the internal nested handler masks struct-typed columns today (`docs/strategies.md:1376-1380`), so a job with, for example, a struct holding an email and a timestamp would stop after S5. Options: (A) accept for V1 and build full support later as G-8; (B) build G-8 inside S5 now, with a logical-view check and an output rule (a larger slice, and the output-type choice in 4.4b must be made too); (C) refuse only caller-supplied Arrow and read nested columns from the file readers, which needs a proof that batch reads never carry hidden storage and splits one rule by entry point. The planner recommends (A). List view, run-end-encoded, union, extension and dictionary-of-struct columns never come from a Decoy file reader, so refusing them is a technical choice and not part of Q6.

Technical choices taken (recommended option, no owner call needed): keep the name `preserve_values`; reach from config, not the key; refuse near-bound text dates on every route instead of computing them on some; keep `sentinel_to_null` separate with casting first; keep generation's plan-time refusal code; no rename of the out-of-core disposition fields.

## 16. Review round 1

Dennis R1 (`/home/cam/scratch/dennis-drs-plan-r1.md`, on `37cafb29e`): NO-GO, 2 blocker, 3 high, 4 medium, 2 low.

| # | Finding | Fix in this revision |
|---|---|---|
| 1 | Statistical generation missing: second date range 1..9998, `plan/generation_unbounded_column`, no sentinel path, windowed anchor admission | rows L2 and L3 in 1.2; generation rows in the range table with the reason for keeping its plan-time code (4.2); routes in 10.2; S7 rebuilt around `_window_admission.py:128-170`, `:290-320`, `_sample.py:493`, `_degenerate.py:122`; AT-F1, AT-F2, AT-F4; M-20 |
| 2 | Value-bearing errors deferred (reader year, sampler date) | new early slice S5 with `runtime/source_date_unrepresentable` and the distribution refusal, not gated on Q3; AT-V1, AT-V2; M-18; G-1 removed |
| 3 | Partition not bound to its data; `replace` bypass | partition carries `source` and `parsed`, primitives read values only from it, companion series checked for length and index; not a dataclass, `__replace__`/`__copy__` raise; sentry bans `replace(`/`__new__`; M-13 stale partition |
| 4 | Sentry blind to the typed path and to renames | sentry scans `timedelta(`, `to_timedelta`, `DateOffset` and date adds in strategy-input packages, with a named allowlist, and fails when a listed primitive no longer resolves; M-15, M-16; class 10b row |
| 5 | `DateRangeError` not in `_CODED` | `_CODED` row in 4.5 and S1, a `reason_from_exception` test; M-17 |
| 6 | Real date equal to a declared sentinel passes unmasked, unseen | guarantee item 6, user docs (4.7), pre-mortem entry; S6 adds `declared_sentinel_rows` per column; AT-P4, M-19 |
| 7 | text_mask token departs from the owner rule | owner question Q5, decided "recommended" by the owner 2026-11-27 |
| 8 | AT-R7 entry undefined, no multi-table case | AT-R7 names `run_pipeline(..., sink=..., auto_chunk=True)` and adds a two-table SEQ case with table `a` staged; CLI CSV case is G-7 |
| 9 | Native kernel left with no guard | `native_range_exceeded` kept as an internal invariant raise in both native seams (not a decline); M-14 |
| 10 | AT-F3 undecidable; `profiling/_distributions.py:105` | AT-F3 asserts both functions count the far value on calendar dates; `_distributions.py:105` added to row M and 10.2 |
| 11 | `replaced_by=None` without the registry citation | 4.3 and section 8 cite `reasons/_registry.py:202-209` and `CONTRIBUTING.md:58` |

## 17. Review round 2

| Finding | Class | Fix and verification |
|---|---|---|
| H1 | V1 | Section 4.2 binds the resolved shift window or bucket to the input partition. AT-R4, AT-R11 and AT-C3 cover defaults, jitter and reversed bounds. |
| H2 | V1 | Section 4.4 checks Arrow data at ingestion. AT-V1 puts the failing row past the sample on every run route. |
| H3 | V1 / DESIGN | Section 4.5 places the source error in errors and registers its defining module in the adapter. S5 is independent of S1. |
| H4 | V1 | The S7 exact-fit API receives a per-column declaration. S8 passes it through the public CLI after S7 ships. AT-F2 starts at the writer and checks the value policy. |
| M1 | V2-LOG | The primitive checks the full group anchor then slices it with its source. M-11 breaks that internal slice. |
| M2 | V2-LOG | Section 8 specifies v2 compatibility, the old-reader test and the full writer suite. |
| M3 | V2-LOG | AT-V2 uses plan/generation_unbounded_column for either fitted generator. |
| M4 | V2-LOG | The transforms table reads the contract constants. The decoder keeps its existing downward-only dependency. |
| L1 | V2-LOG | Section 4.2 refuses deep copy and pickle. The section 4.4 sentry covers deepcopy. |
| L2 | V2-LOG | The native ns invariant covers text and tz only. AT-R7 explicitly forces and verifies chunking. |

### 17.1 Review of section 4.4b, round 1

Dennis on `6e9e65664` (`~/scratch/dennis-s5-plan-4-4b-r1.md`): GO-WITH-FIXES, 2 high, 6 medium, 5 low.

| Finding | Fix in 4.4b |
|---|---|
| H1 gate follows `pa.ExtensionType` only | shared walker follows `pa.BaseExtensionType`; AT-V4 `opaque` and `fixed_shape_tensor` cases; M-26 |
| H2 transitive forwarding rule cannot be listed | sink set closed to `to_pandas`, `to_pandas_fk_safe` and `_CONVERSION_HELPERS`, not transitive; stop at 40 entries |
| M1 second copy of the type walker | walker moved to `_arrow_types.py` and shared; Placement and size rows |
| M2 date leaf too wide | date leaf is `date32`, `date64` or `timestamp`; AT-V4 pass cases; M-27 |
| M3 repair nulls rows after a null entry | one outside mask for count and repair, `fill_null` keep, `int64` cumsum; AT-V6 cases; M-28 |
| M4 denylist misses compute walks | allowlist of `pc` functions, attributes and imports; runtime invariant; AT-V9; M-25 |
| M5 "at open" and empty-table claims unwired | `check_source_schema` wired into `check_source_dates`, `checked_batches` and `checked_chunks`; AT-V3 empty cases |
| M6 dropped check result | guard fails on a bare check-call statement; AT-V8 seed 3; M-29 |
| L1 M-25 cites AT-V5 | cites AT-V3 and AT-V9 |
| L2 wrong error home in 4.5 | row points at `io/bounded_reader.py:106` and `reason_adapter.py:57` |
| L3 `_part3.py` missing from the size list | added with the census rule |
| L4 which kind is reported | the outermost kind |
| L5 binding precondition | `is_dataclass` and a `table` field |
| Not verified: pyarrow 14 walker | probed on 14.0.2 (4.4b item 2) |
| Not verified: ISO, SEQ and isolated-dispatch binding | traced in 4.4b "Where the binding runs" |

## 18. Follow-ups (not in this row)

- G-2: compute text dates on the Python calendar after the pandas parse, which would widen the text domain to the typed one.
- G-3: shuffle over `timestamp[ns]` returns `timestamp[us]` on full_frame.
- G-4: CLI hint for `date_outside_strategy_range`, and `decoy scan` suggesting `preserve_values` from the pre-scan sentinel flags.
- G-5: compile check order differs between the chunked and full-frame paths for a naive timestamp with `preserve_values`.
- G-7: CLI test for `--chunked` CSV staging with a refusing far date (CLI repo).
- G-8: full support for dates inside list, map, struct, list view, run-end-encoded and dictionary-of-struct columns (section 4.4b), if the owner picks Q6 (A). Needs the output-type decision first.
- G-11 (V2-LOG): the bare-statement guard rule misses a check result that is assigned and then ignored (section 4.4b).
- G-9: bytes under a null slot of a plain date leaf are returned as they are in an Arrow return (section 4.4b item 5).
- G-6: relationship validators read a far output date as unparsed (`validators/_dates.py:71-80`); confirm sentinel rows are skipped, not counted as violations.

VERDICT: GO
