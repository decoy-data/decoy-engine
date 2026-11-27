Status: plan

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 3 (after review round 2, with Q1 to Q5 settled in section 15). Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Anchors are in this repository (decoy-engine) at `origin/main` `f54ad388b` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

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

**S5 source reads.** Check Arrow data when it enters the reader, before it can reach pandas, Python scalar conversion or a native kernel. Use one checked table or batch operation in the io tier. Bind the table name when opening the source. In profile/_readers.py cover LazySource.iter_batches, open_batches and to_table, plus resident frames. At execution entry wrap supplied tables and loader results before transforms, preflight or dispatch, including direct chunked and native APIs. Apply it to resident inputs (including loader returns), lazy materialization and every yielded batch, including opened row-group reads and the direct OOC entry. The profile head uses the same checked read. Keep streaming bounded. A head scan proves nothing about unread rows. Later source conversions at `execution/_chunked_profile.py:41`, `pipeline/_source_types.py:60`, `out_of_core/_mask_group_c.py:537` and `internal/pandas_compat.py:132` must all receive checked data.

For date32, date64 and timestamps, compare non-null Arrow extrema as physical integers in their native units to the inclusive Python calendar bounds. Decode dictionary-encoded date columns on the Arrow side for this check, counting referenced rows, not unused dictionary entries. Intersect with the unit's storage range before making comparison scalars. Preserve valid sub-day timestamps through the end of year 9999. For zoned columns also check local calendar representability before conversion, including offset crossings. Only on failure count the offending rows with an Arrow mask. Raise `SourceDateUnrepresentableError` outside any exception handler with table, column and batch count only. The AT-V1 source-boundary guard traces resident returns, caller loaders and lazy yields to the checked read. Bypassing a later batch or a resident return must fail AT-V1. Run the import-layer and reason-adapter tests, including isolated classification.

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

### 4.5 Placement

| Item | Place | Why |
|---|---|---|
| `DateDomain`, `DatePartition`, `DateRangeError`, range table | `transforms/date_preserve.py` (275 lines today, about 400 after) | `transforms/` is at its fan-out limit (CODEMAP "Transforms" row); the matching code it extends is already here |
| New reason | `reasons/runtime/_part3.py`, new `_catalog.runtime("DateRangeError")` binding | runtime reason home; `_part3.py` is 553 lines |
| Coded family row | `reason_adapter.py:44-70` `_CODED`: `("decoy_engine.transforms.date_preserve", "DateRangeError", "runtime")`, the defining module | without it the adapter and isolated-child classification report the refusal uncoded; `tests/unit/test_reason_registry.py:198-218` already checks every row resolves and gains a case that `reason_from_exception(DateRangeError(...))` returns the new code |
| S5 source boundary | Existing `io/bounded_reader.py` (CODEMAP.md:129), public checked Arrow reader API exported by `decoy_engine.io`. Error in `errors.py`, code in `reasons/runtime/_part3.py`, adapter row `("decoy_engine.errors", "SourceDateUnrepresentableError", "runtime")` | Profile and run readers may both import io and errors under `.importlinter:22-25` |
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

## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with `replaced_by=None` (allowed by `reasons/_registry.py:202-209`, section 4.3): `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
- New reason `runtime/source_date_unrepresentable` (`since=UNRELEASED`, S5).
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
| S5 | engine | Checked Arrow ingestion, bottom-tier source error and adapter row, shared fitted distribution admission with the existing generation code, AT-V1 and AT-V2, user and reason docs, changelog | nothing | R2 | T1 plus full suite and layer checks |
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

## 18. Follow-ups (not in this row)

- G-2: compute text dates on the Python calendar after the pandas parse, which would widen the text domain to the typed one.
- G-3: shuffle over `timestamp[ns]` returns `timestamp[us]` on full_frame.
- G-4: CLI hint for `date_outside_strategy_range`, and `decoy scan` suggesting `preserve_values` from the pre-scan sentinel flags.
- G-5: compile check order differs between the chunked and full-frame paths for a naive timestamp with `preserve_values`.
- G-7: CLI test for `--chunked` CSV staging with a refusing far date (CLI repo).
- G-6: relationship validators read a far output date as unparsed (`validators/_dates.py:71-80`); confirm sentinel rows are skipped, not counted as violations.

VERDICT: GO
