Status: plan

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 3 (after review round 2, with Q1 to Q5 settled in section 15). Revision 4 adds section 4.4b after S5 code review round 2. Revision 5 (2026-11-28) redesigns S5 in section 4.4b after the S5 build failed six code-review rounds, splits it into S5a and S5b, and records Q6 as decided A. Revision 6 (2026-11-28) fixes Dennis plan review round 1 (section 17.3): S5 anchors move to `origin/main` `d1d7453ac`, after #799. Revision 7 (2026-11-28) addresses Dennis round 2 against main at `395c1c662`, including #830. Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Anchors are in this repository (decoy-engine) at `origin/main` `f54ad388b` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one new reason code, three deprecations, a config key on one more strategy), `catalogs/recurring-defects.md` (11 classes), `cross-cutting-concerns.md` (one rule, many routes), `testing.md` (test depth T0 to T4). Revision 5 also consulted the bound registry (`tests/sentry/ratchet/_limit_constants.py`, `tests/sentry/baselines/sentry-limits.json`) and, as established solutions, Arrow's dictionary semantics (a slice keeps its dictionary; `concat_arrays`, `combine_chunks` and `unify_dictionaries` keep the union of entries; `to_pandas` converts the whole dictionary), pyarrow's tz resolver (`pyarrow.lib.string_to_tzinfo`, the tzinfo `to_pandas` and `as_py` receive) for offsets, and Hypothesis property tests against an independent oracle. Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`, deprecation with `replaced_by`).

Risk: R2. It changes what a date strategy does with a far date on every route, adds a reason code and deprecates three, and turns a quarantinable row error into a refusal. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S1, S2, S3, S5, S6, S7 and S8; Codex only for S4. Full suite before merge: S1, S2, S3 and S5 for reasons, and S7 for snapshot serialization; the other slices by their own triggers (section 14).

Owner decision (2026-11-27): a date outside the range a strategy can compute is rejected, unless the column declares it as a sentinel to ignore. Sentinel rows skip the strategy and come out unchanged.

## 1. Frame

### 1.1 Symptom

Real data holds marker dates such as `9999-12-31` ("never expires", the open end of a type 2 slowly changing dimension) and `0001-01-01` ("unknown"). pandas `datetime64[ns]` holds 1677-09-21 to 2262-04-11 only. Today a far date does one of six different things, chosen by the route, the source shape and even the mask key (section 1.2). None of them is "refused with one code, unless declared".

### 1.2 What the probes showed

All probes ran on `f54ad388b` with the main checkout venv (pandas 2.3.3, pyarrow 24.0.0, companion present), through the public entries the tests use (`run_pipeline`, `run_mask_pipeline_chunked`, `run_mask_chunked`, `run_fk_out_of_core` via `tests/parity/_d1a_hash_data.run_chain`). Probe scripts: `p1.py` to `p9.py` in the Architect scratchpad; each is restated as an acceptance test in section 6, so nothing here depends on the scratch files.

Cells: text `"9999-12-31"`, `"0001-01-01"`, `"1600-01-01"` with `date_format="%Y-%m-%d"`; the same as `date32`; the same as `timestamp[us, UTC]`; near-bound text `"2262-04-10"`, `"1677-09-22"`; `date32` year 10183.

| ID | Strategy, shape | Route | Result at the probe head |
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
| O | any strategy, `date32` year 10183 | every route but native chunked | uncoded `ValueError: year 10183 is out of range` from the profile sampler (`profile/_readers.py:499`) quoting the year at `f54ad388b` |
| P | date_shift or bucket_perturb with `preserve_values=["9999-12-31","0001-01-01"]` | every route above | the listed sentinels come out unchanged and are counted; undeclared far rows still behave as A to I |

Row O update (2026-11-28, after #799): the profile sampler now refuses with the value-free `source_column_unrepresentable`. NCH passthrough returns the column. S5a gives both the date refusal (comparison rows 3 and 13, subject to Q8).

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

**S5 source reads.** Check Arrow data when it enters the reader, before it can reach pandas, Python scalar conversion or a native kernel. Use one checked table or batch operation in the io tier. Bind the table name when opening the source: it is the caller's `sources` mapping key, or the configured table on the single-source chunked entries (section 4.4b). In profile/_readers.py cover LazySource.iter_batches, open_batches and to_table, plus resident frames. At execution entry wrap supplied tables and loader results before transforms, preflight or dispatch, including direct chunked and native APIs. Apply it to resident inputs (including loader returns), lazy materialization and every yielded batch, including opened row-group reads and the direct OOC entry. The profile head uses the same checked read. Keep streaming bounded. A head scan proves nothing about unread rows. Later source conversions, all through main's `arrow_to_frame` / `arrow_to_series` since #799 (for example `execution/_chunked_profile.py:43`, `execution/pipeline/_source_types.py:64`, `execution/out_of_core/_mask_group_c.py:531`), must all receive checked data.

For date32, date64 and timestamps, apply the holdable rule of section 4.4b in one pure check, `check_source_dates`, which returns its input unchanged or raises. Only plain date and timestamp columns and top-level dictionaries of them are read; every other column that holds a date at any depth is refused by type (Q6 = A). A plain column is read when every non-null cell is holdable; a date dictionary is read when every entry of every chunk is non-null and holdable, used or not. The rule covers the `ns` unit (the storage range less `INT64_MIN`) and the local wall time of zoned columns, computed in Python integers with the tzinfo pyarrow hands pandas (`pyarrow.lib.string_to_tzinfo`) for the few cells near a bound. Raise `SourceDateUnrepresentableError` outside any exception handler with table and column names in text and the logical row count on the exception object. S5 changes no data, no pandas conversion and no read: whole-file reads stay main's `read_table` and are checked after the read. The AT-V1 source-boundary guard traces resident returns, caller loaders and lazy yields to the checked read, with allowances per function, never per file, and it treats a function that forwards data to an allowlisted conversion helper as a sink. A second rule allows the source-date errors to be raised only in `io/source_dates.py`. Bypassing a later batch or a resident return must fail AT-V1. Run the import-layer and reason-adapter tests, including isolated classification.

### 4.4a Existing tests the S5 source check changes

Found by the S5 full suite on 2026-11-27 (236 new failures, all one class). The source check in 4.4 applies to every
source column on every route, including passthrough and carried columns. So a source date outside the Python
calendar (year 1 to 9999) is now refused at the reader with `source_date_unrepresentable`, before any strategy runs.
This follows the non-goal in section 4.1 ("masking dates beyond year 9999: S5 only refuses them"). Row N stays true for
far dates inside the calendar, such as `9999-12-31`, which passthrough still returns exactly.

The allowed value-based test change is a source date cell that the 4.4b rule refuses. This includes dates outside years
1 to 9999, `INT64_MIN` ns and zoned timestamps whose local time leaves the allowed range. For each original refused
value, add a refusal case on each affected route. Assert the date code, table and column, and value-free text. Keep
the positive test at an admitted extreme of the same unit and zone. Pin the replacement independently of the predicate.

- `tests/native/test_chunked_entry_rev9_shapes.py`: the shapes `timestamp_{s,ms,us}_min`, `ts_{s,ms,us}_*_far`,
  `date32_far` and `date64_far`. Every test parametrized over them asserts something about carried passthrough: exact return on both
  routes, equal tables, oracle unchanged, min int64 kept, row-error sink, and no carried column reaching pandas. For
  each one, use the first and last admitted instants for its unit, keeping both UTC and local time inside years 1
  to 9999 for a zoned shape. Add one test per route that the int64-minimum shapes are
  refused with `source_date_unrepresentable`, value-free, naming the table and column.
- `tests/native/test_unconfigured_passthrough_read.py::test_sibling_reading_strategy_keeps_its_listing_and_coded_error`:
  if the bad shape is an out-of-calendar date, swap it for a non-date bad shape of the same family, so the sibling
  listing and coded error are still checked. Add an assertion that the date shape is refused at the source.
- `tests/unit/execution/test_full_frame_value_unrepresentable.py::test_far_date_raises_coded_error_naming_the_column`:
  year 12921 is now refused at the source. Assert `source_date_unrepresentable`, naming the column and table.
  `full_frame_value_unrepresentable` stays tested by the time64 sub-microsecond case in the same file. If no date
  shape can reach `full_frame_value_unrepresentable` any more, write that down as a V2-LOG note. Do not remove the code.

- `tests/native/_rev9_support.py`: for `ts_ns_America/New_York_edge`, `ts_ns_+05:30_edge` and
  `ts_ns_Europe/London_edge`, keep the exact-return claim at the nearest ns tick where UTC and local time both fit.
  With `lo = INT64_MIN + 1` and `hi = INT64_MAX`, the admitted ticks are `lo + 17_760 * 10**9` for New York,
  `hi - 19_800 * 10**9` for +05:30 and `lo + 60 * 10**9` for London on the pinned stack.
  For `timestamp_ns_min`, use `INT64_MIN + 1` and assert exact return, including the null bitmap. Update the shape
  labels, the docstring and the literal minimum assertion in `test_chunked_entry_rev9_shapes.py` accordingly.
  Durations still exercise the raw int64 minimum. Test the original lower edges for New York and London, the upper
  edge for +05:30 and the naive minimum as refusals through CH and NCH.
- `tests/native/_rev9_profile_cases.py:72`: use `INT64_MIN + 1` at the same positions in `ts_ns_min`. Keep field-for-field native/pandas profile equality
  and equal compiled plans and routes for that input and the admitted rev9 carriers. On checked profile routes, assert a refusal for the
  original values separately.
- `tests/native/test_chunked_entry_values_schema.py::test_e4_timestamp_ns_minimum_agrees_with_the_oracle`:
  compare the repeated lowest admitted tick on both chunked APIs. Assert exact stored values, table equality and the
  original null positions. Run the old `INT64_MIN` input through each API and assert the source refusal. In the
  companion `test_e4_value_pandas_refuses_raises_on_the_oracle_and_is_exact_on_the_entry`, move the far date32
  to a refusal on both APIs. Keep #799's existing code and exact-return checks for the time64 case.
- `tests/native/test_unconfigured_passthrough_types.py:178-184`: for `ts_ns_naive`, `ts_ns_America/New_York` and
  `ts_ns_+05:30`, use the admitted low and high ticks for that zone. Preserve exact unconfigured passthrough,
  including type, values and nulls. Keep every already-admitted extreme. Test each original refused extreme on each
  affected route.

Apply the same rule to any other test that turns red. Record the old input, the clause that refuses it and the claim
that its replacement preserves. Investigate any other failure as a regression. Section 4.4b changes both the plain
timestamp tests above and the following tests added on the S5 branch:

- `tests/unit/io/test_checked_source_dates.py::test_a_far_date_nested_in_a_container_is_refused_by_name_and_count`
  (six shapes): each shape is now refused with `source_date_type_unsupported` and its container kind, with no count.
  Rename it to `test_a_date_in_a_container_is_refused_by_type` and add an in-calendar case per shape.
- `test_a_nested_date_inside_the_calendar_and_a_null_parent_pass` in the same file: inverted. Both columns are now
  refused by type. This is the contract change behind Q6, not a weakened test.
- `test_an_unused_bad_dictionary_entry_is_dropped_not_refused`, `test_a_chunked_dictionary_column_is_cleaned_chunk_by_chunk`
  and `test_a_record_batch_is_cleaned_too`: inverted in revision 5. An unused non-holdable entry now refuses the
  column with `count == 0`, in every chunk layout. Rename them to `test_an_unused_bad_dictionary_entry_is_refused`,
  `test_a_bad_entry_in_any_chunk_dictionary_is_refused` and `test_a_record_batch_is_checked_too`.
  `test_a_dictionary_of_something_else_is_left_alone` (no date inside) stays as it is.
- `tests/unit/execution/test_source_date_unrepresentable.py::test_a_far_date_nested_in_a_list_or_struct_is_refused_on_both_chunked_routes`:
  expects `source_date_type_unsupported`. Every `LazySource(path, table=TABLE)` fixture in that file (lines 84, 137,
  155, 163, 215, 239 at `2fab8cb9f`) drops `table=`, so the mapping key must supply the name (AT-V7). The static guard
  at lines 400 to 528 moves to `tests/sentry/test_source_date_read_guard.py` and is rewritten per section 4.4b.
- `docs/strategies.md:403-405` (the nested and dictionary paragraph) is rewritten per section 4.7.

For branch tests, record the specific 4.4b type, cell or dictionary rule that changes the expected result.

### 4.4b S5 redesign: one pure checked read (revisions 5 to 7)

Revision 5 replaced the revision 4 text of this section (plan commit `780b3f26d`, kept in git history). It followed the
S5 build (PR #839, branch `feat/date-range-s5`, head `a5da43ef9`), which failed six code-review rounds. Revision 6
fixes Dennis plan review round 1 (section 17.3). Its main changes:
- the zone test now uses the tzinfo that pandas and Python actually get;
- the plan is re-anchored to `origin/main` `d1d7453ac`, which includes #799;
- the comparison with main is corrected;
- the null dictionary entry is now decided.

**Main after #799.** `7822182c5` (#799, "route source reads through one conversion that fails coded") merged after the
S5 branch was cut from `9812da814`. `a5da43ef9` does not contain it. On `d1d7453ac`:
- every source conversion goes through `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` or
  `table_to_pandas_exact_ints` in `internal/pandas_compat.py`. The public module `decoy_engine.arrow_frames` exports
  the three `arrow_to_*` names. The exact-integer helper is internal. Only the implementation module calls `to_pandas`;
- a column pandas cannot hold raises the coded, value-free `runtime/source_column_unrepresentable` (or
  `full_frame_value_unrepresentable` on the pandas execution routes), built in `_execution_error.py:52-75`.

S5a builds on that boundary. It does not replace it, and it adds no conversion of its own. Source anchors and the original conversion probes in this section use `d1d7453ac`. Revision 7 uses
`395c1c662` for the port and the public compatibility contract.

**What went wrong.** Codex rounds 3 to 6 (`~/scratch/codex-s5-r3.out` to `r6.out`) found 22 V1 findings. Each round
closed the named cases and the next round found the same class on another layout, zone or route. The findings come from
three things S5 added on top of the date check, plus two gaps in the check itself:

| Source of the finding | Findings | What it was |
|---|---|---|
| Dictionary repair and a pandas working copy of date dictionaries (`io/source_dates.py` repair, `internal/pandas_compat.py` working categorical, `WorkingInstant`, index and label restoration) | R3: stored index lost, zero-chunk and `INT64_MIN` dictionaries, reports bypass the copy. R4: pandas 1.5.3 import, `INT64_MIN` instant changed, physical and display index names. R5: passthrough assembly fails and quotes a value, mask identity depends on an unused entry, projected MultiIndex, non-string labels, resident fallback index. R6: per-chunk compaction reorders categories, route disagreement (a second check site in the conversion). 14 in all | S5 rewrote data and the pandas conversion that main already did. Every layout the rewrite handled differently from `to_pandas` was a new finding |
| A rewritten whole-file Parquet read (`fileaccess/adapters/arrow.py` dataset scanner, to gate before decode) | R3: decode before the gate. R4: directory fallback, dotted projection. R5: Hive partition key missing. R6: Hive key type. 5 in all | S5 replaced main's `pq.read_table` with a scanner whose semantics differ |
| The check itself | R3: `local_timestamp` refuses fixed offsets on pyarrow 14. R6: zoned values near the nanosecond bounds pass the check and fail on scalar access | the rule had no statement for the nanosecond unit, and it used an Arrow kernel whose behavior varies by version |
| Pre-existing, surfaced by S5 | R6: the output assembler mixes display labels with physical field names | reproduces on main with ordinary integer data |

The repeated class is "S5 rewrites something main already does, and the rewrite differs on a layout no test named".
The redesign ends it by construction: **S5 refuses; it never rewrites.** The checked read is a pure predicate over Arrow
data. It returns its input object unchanged or raises. S5 adds no data repair, no pandas conversion code and no new
read. What main converts and reads, S5 leaves as it is.

#### The rule: one checked read, one predicate

`check_source_dates(data, *, table)` in `io/source_dates.py` is the one place where the source date domain is judged.
It runs once per table or batch at ingestion (section 4.4), before the routes split. Main's `arrow_to_frame` still
refuses, coded, any column pandas cannot hold when a route converts. That is main's guard and it stays. AT-V20 proves
that the two never disagree on a date column: every date column S5 admits converts and reads.

1. **Type gate (Q6 = A, unchanged from revision 4).** A column is read only in one of these cases:
   - it holds no date at any depth;
   - it is a plain `date32`, `date64` or `timestamp` column;
   - it is a top-level dictionary of one of those types.

   Any other column that holds a date is refused by its type with `runtime/source_date_type_unsupported`, whether or not
   its dates are in range. The walker, the shape classifier and the unclassified-layout refusal from the S5 branch stay
   (`_arrow_types.py`).
2. **Holdable cells.** Every non-null date cell of an admitted column must be *holdable*. Holdable means all of these:
   - its instant is a day in calendar years 1 to 9999 (the 4.4a domain, Q1);
   - for `ns`, its instant is not `INT64_MIN`, which pandas reads as `NaT`;
   - for a zoned timestamp, pandas can read the cell and Python can turn it into a `datetime` in its zone.

   The test uses only the type and the physical integer:

   | Type | A non-null cell with physical integer `v` is holdable when |
   |---|---|
   | `date32` | `CALENDAR_FIRST_DAY_NUMBER <= v <= CALENDAR_LAST_DAY_NUMBER` |
   | `date64` | `v` falls on a day in that range (unchanged from the S5 branch) |
   | `timestamp(unit)`, no zone | `lo <= v <= hi` |
   | `timestamp(unit, zone)` | `lo <= v <= hi`, the zone resolves, and `lo <= v + offset(zone, v) <= hi` with the local time inside years 1 to 9999 |

   `[lo, hi]` is the span from the first tick of year 1 to the last tick of year 9999 in the unit's ticks, intersected
   with `[INT64_MIN + 1, INT64_MAX]`. For `s`, `ms` and `us` the calendar lies inside the storage range, so `[lo, hi]`
   is the calendar. For `ns` the storage range is the narrower one, so `[lo, hi]` is 1677-09-21 00:12:43.145224193 to
   2262-04-11 23:47:16.854775807 UTC. `offset(zone, v)` is the UTC offset at instant `v` of the tzinfo that pyarrow
   gives pandas and Python for that zone. The section "How the zone test is computed" explains how it is found.
3. **Dictionaries.** A date dictionary column is read only when every entry of every chunk's dictionary is holdable,
   whether or not a row references it. A null entry also refuses the column (G-13, decided in revision 6 as a technical
   call). On main a null entry already fails every converting route with `source_column_unrepresentable`, because
   pandas categories cannot be null. Refusing it at the read gives one answer on every route, NCH included. The remedy is
   the same as for a far entry: decode the column or re-encode its dictionary.
4. **Refusal.** A column that fails 2 or 3 is refused with `runtime/source_date_unrepresentable` (the reason decision
   is below). The message names the table (the `sources` mapping key, section "Table name" below) and the column, and
   nothing else. The exception carries `count`, the number of logical rows whose value is not holdable or is a null
   entry. A dictionary refused only for an unused entry has `count == 0`. The raise is outside any exception handler.
5. **Purity and cost.** When the data passes, `check_source_dates` returns the same object it was given
   (`result is data`). On the pass path it reads plain cells through zero-copy integer views and `min_max`. For a
   dictionary it checks entries without decoding rows or building a row mask. Once a dictionary entry fails, the refusal counter
   gathers the bad-entry mask with `pc.take(bad_entries, chunk.indices)` and sums the true rows. A null index adds
   zero. A row pointing to a null entry adds one. The whole-file in-memory read (`LazySource.to_table`, "small jobs only",
   `profile/_readers.py:417`) is main's existing read. The out-of-core routes use the batch path. AT-V15 checks the
   allocation.

**Reason decision (revision 6, M2).** S5a keeps its own code, `runtime/source_date_unrepresentable`, beside #799's
`runtime/source_column_unrepresentable`. It does not reuse #799's code, for three reasons:
- The set of values is different. S5 refuses dates that pandas can hold, under the decided calendar domain (for example
  a `timestamp[us]` entry in year 10000, or fixture F4). It also refuses on routes that never convert (NCH).
  `source_column_unrepresentable` says "a value pandas cannot represent", which would be false for those inputs.
- The remedy is different. The remedy is to fix or null the date, cast the column to text, or decode or re-encode a
  dictionary. A date outside this domain cannot be declared as a sentinel.
- It carries a row count.

The location wording is shared, not copied: move the table and column phrase of `_unrepresentable_text`
(`_execution_error.py:41-46`) into a helper `source_location_text(table, column)` in the same leaf module. Both error
families build their message from it. `io` sits above the `_execution_error` tier (`tests/sentry/layout/test_import_layers.py`
`LAYERS`), so the import is allowed. Registry summary: "A source date column holds a value outside the supported date
range: calendar years 1 to 9999, narrowed for nanosecond timestamps to what pandas can hold, with zoned timestamps
judged in both UTC and local time." The remediation text adds the dictionary remedy above. Both codes are
`since=UNRELEASED`, so the text can still change without a deprecation.

**How the zone test is computed (revision 6, H1).** pandas 2 does not use `zoneinfo`. `to_pandas` gets its tzinfo
from pyarrow's resolver, `pyarrow.lib.string_to_tzinfo(zone)`, which returns a `pytz` zone when `pytz` is installed.
pandas 2 requires `pytz`, so in every supported environment the zone is a `pytz` zone. `as_py` uses the same
resolver. `pytz` differs from `zoneinfo` in three ways that matter at the bounds:
- It keeps the last rule after its 2037 transition table. Australia/Sydney is +11:00 and Pacific/Auckland is +13:00 at
  2262-04-11 (zoneinfo: +10:00 and +12:00). Europe/Berlin goes the other way: +1:00 (zoneinfo: +2:00).
- It rounds local mean time offsets to whole minutes: New York is -4:56, not -4:56:02.
- It does not know some zones that `zoneinfo` knows, for example `Factory`.

Revision 5 modelled offsets with `zoneinfo`. For Sydney at `INT64_MAX - 10h` its model admits a cell that main's
own `arrow_to_frame` converts and then fails to read (`OutOfBoundsDatetime` quoting a timestamp). So the zone test
uses the resolver that the converter uses:

- Resolve the zone once per zoned column with `pyarrow.lib.string_to_tzinfo`, whether or not the column has band
  cells. If the zone does not resolve, refuse each non-null value. Catch only `KeyError` and `pa.ArrowInvalid`
  from the resolver. `KeyError` covers both
  pytz's unknown-zone error and zoneinfo's missing-key error. Keep pytz imports out of `io`. AT-V12 pins the refusal.
  When testing pandas 3 without pytz, check malformed zone keys for `ValueError` before extending this catch.
- Let `M` be two days in the unit's ticks. The largest named-zone offset measured was 15:56:08 (Asia/Manila).
  The resolver also accepts fixed offsets through ±23:59. Both fit within the margin.
  A cell with `lo + M <= v <= hi - M` is holdable in every resolved zone, and a
  cell outside `[lo, hi]` is not. Integer comparisons on the whole array decide both (the existing extrema
  prefilter).
- For *band* cells (within `M` of `lo` or `hi` in a zoned column), take the distinct band values (`pc.unique`). Build
  each one's UTC `datetime` from whole seconds, since offsets change on whole seconds. Convert it with
  `astimezone(tzinfo)` and add the offset back to `v` in integers. An `OverflowError` means the local wall time leaves
  years 1 to 9999: not holdable.
- The helper returns a boolean and catches only the listed errors. The refusal is raised later, outside it.
- `pc.local_timestamp` and `_fixed_offset_seconds` are not used. The resolver handles fixed offsets (`+05:30`,
  `-08:00`) as well, so one path covers every zone and the pyarrow 14 fixed-offset failure (R3) cannot recur.

This uses pyarrow's resolver and not a trial conversion, because the check sits in `io`, a tier below `internal`. It
cannot import the conversion module, and main's rule keeps `to_pandas` inside `internal/pandas_compat.py`. A trial
conversion would either break the layering or add a second conversion site, which is the class that failed review.
The resolver is the same object the converter receives, so it is not a separate model.

A library probe on main's venv (pyarrow 24.0.0, pandas 2.3.3, pytz 2026.2, 2026-11-28) compared the resolver test with
real conversion plus scalar access (`to_pandas`, `iloc[0]`, `as_py`):
- sample: 14,448 band values over 599 zones and three fixed offsets, in units `s`, `us` and `ns`, at both bounds;
- result: 0 disagreements;
- the four reviewed cases also match: Sydney and Auckland at the `ns` top are refused, Berlin `INT64_MAX - 3601 s` is
  read, and New York `INT64_MIN + 42` is refused.

AT-V13's oracle is the real conversion, not the resolver (see the tests below). So a pandas or pyarrow change that
breaks this agreement turns the test red.

pandas 3 drops `pytz` and resolves zone strings with `zoneinfo`. If pyarrow then hands pandas a `zoneinfo` object, the
resolver follows, because the check asks pyarrow and not a fixed library. AT-V13 and AT-V20 are the guard. Any
pandas or pyarrow pin bump, and the DEP-FLOOR legs, run them.

**Why this rule (options considered).** The brief asked for the simplest rule that satisfies Q6 = A and that can be
tested exhaustively.

| Option | What it does | Verdict |
|---|---|---|
| A. Refuse a date dictionary when any entry, used or not, is not holdable or is null (chosen) | One predicate for plain cells and dictionary entries; the read never changes data | Chosen. See below |
| B. Decode every date dictionary to a plain column at the read, then test cells | One cell rule, but the read returns new data | Rejected: changes the output type of every valid date dictionary from `dictionary<date32>` to `date32`, loses ordered-categorical sorting, and still needs the holdable test for the decoded cells. The check would again return data callers must use |
| C. Test only referenced entries, then repair the dictionary (the S5 branch) | Drops unused bad entries, remaps codes, builds a pandas working copy | Rejected: this is the design that failed rounds 3 to 6 |
| D. Refuse every date dictionary | No dictionary rule at all | Rejected: refuses in-range dictionaries that main converts correctly, and narrows the shapes Q6 = A admits, which is an owner call |

**What rule A changes against main (corrected in revision 6, M1).** Revision 5 said that rule A refuses only inputs
that already fail on main. That was measured against raw `to_pandas`, not against main's `arrow_to_frame`, and it is
false as written. The probe below ran main's own `arrow_to_frame` from a `git archive` of `d1d7453ac`, with the same
library versions, 2026-11-28:

| # | Input | Main `d1d7453ac` (convert, then read the rows) | S5a | Kind |
|---|---|---|---|---|
| 1 | `dictionary<date32>`, entries in years 1 to 9999 including `0001-01-01` and `9999-12-31`, used or unused | converts, rows read | read | same |
| 2 | `dictionary<date32>`, unused entry in year 10183 | refused, `source_column_unrepresentable` | refused, `count == 0` | other code, earlier |
| 3 | plain `date32`, year 10183 | refused, `source_column_unrepresentable` | refused, `count == 1` | other code, earlier |
| 4 | `dictionary<timestamp[us]>`, `9999-12-31` used | converts, rows read | read | same |
| 5 | `dictionary<timestamp[s\|ms\|us]>`, an entry before year 1 or after year 9999 | converts, rows read | refused | **narrowing** (calendar domain) |
| 6 | `dictionary<timestamp[ns]>`, entry `INT64_MIN` | refused, `source_column_unrepresentable` | refused | other code, earlier |
| 7 | `dictionary<timestamp[ns, America/New_York]>`, unused entry `INT64_MIN + 42` | converts, rows read (the entry is never read) | refused, `count == 0` | **narrowing** |
| 8 | plain `timestamp[ns, America/New_York]` `INT64_MIN + 42`; `timestamp[ns, Asia/Kolkata]` `INT64_MAX`; `timestamp[ns, Australia/Sydney]` `INT64_MAX - 10h` | converts; reading the cell raises `OutOfBoundsDatetime` quoting a timestamp | refused | main defect on conversion (value in the message) |
| 9 | plain `timestamp[ns]` or `timestamp[ns, UTC]`, `INT64_MIN` | converts to `NaT` without notice | refused | main defect on conversion (a value is lost) |
| 10 | plain `timestamp[ns]`, `INT64_MAX` | converts, rows read | read | same |
| 11 | plain `timestamp[us, Asia/Kolkata]`, `9999-12-31T23:00Z` (F4) | converts; pandas reads the cell (`10000-01-01 04:30+05:30`); only Python `as_py` fails | refused | **narrowing** (calendar domain) |
| 12 | `dictionary<date32>` with a null entry | refused, `source_column_unrepresentable` | refused (G-13) | other code, earlier |
| 13 | rows 2, 3, 5, 6, 7, 8, 9, 11 and 12 on NCH passthrough, also rows 8 and 9 on CH where it returns the original column | returned exactly | refused | **narrowing** |
| 14 | non-null timestamp in unknown zone `Factory` | conversion raises uncoded `UnknownTimeZoneError('Factory')`. NCH passthrough returns the column | coded date refusal | coded error on conversion, **narrowing** on NCH |

On routes that convert these columns, S5a gives an earlier date code for rows 2, 3, 6 and 12. It prevents the scalar read failure
in row 8, silent loss in row 9 and the uncoded resolver error in row 14. Main can read rows 5, 7 and 11.
On passthrough, rows 13 and 14 show which accepted inputs would now fail. Only the dictionary forms require
caller-supplied Arrow. Include each narrowing in the changelog and section 4.7. Q8 remains open. The build assumes
option A pending the owner's decision.

Why A is otherwise sound:

- *Chunk layout cannot change the answer.* Slicing a dictionary array keeps its dictionary, and `concat_arrays`,
  `combine_chunks` and `unify_dictionaries` keep the union of entries. So the set of entries tested is the same for one
  chunk, many chunks, a table or a record batch. Only a caller that re-encodes the column changes it, which is a new
  input. The count is over logical rows, so it does not depend on layout either. AT-V14 proves both as properties.
- *The refusal reaches only caller-supplied Arrow* for dictionaries. A date dictionary reaches the engine only as
  resident `sources`, a `source_loader` result or chunked API input, where the caller can decode or re-encode the
  column. The refusal text says so.
- *Q6 = A holds.* The type gate and the admitted shapes are those of revision 4. Only the value rule for an admitted
  dictionary changes (all entries instead of referenced entries plus repair), and that is a technical choice.

#### Where the check runs (choke point and guards)

The rule is one function. Ingestion reaches it through the entry wrappers that the S5 branch already built and review
already passed. Rounds 3 to 6 confirmed that SEQ, direct OOC, both chunked entries, `PandasExecutionAdapter.run` and
`run_single`, cloud and ISO reach it. The wrappers are:
- `check_resident_sources` and `checked_loader` at `run_pipeline`, `run_sequential`, `run_fk_out_of_core` and
  `PandasExecutionAdapter.run`;
- `checked_chunks` in `execution/_chunked_input.py` for both `run_mask_pipeline_chunked` and `run_mask_chunked`;
- `checked_batches` for lazy Parquet batches;
- the schema gate before IPC staging in ISO;
- the profile readers.

The builder re-derives each line anchor on main while porting (section "What the S5 branch keeps").

Four guards hold it:

- **The read sentry** (`tests/sentry/test_source_date_read_guard.py`, kept from the S5 branch, sink set rebuilt in
  revision 6). Every function that hands Arrow source data to a conversion must be a checked entry or have a
  per-function allowance with a reason.
  - On main the conversion helpers (the sinks) are `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` and
    `table_to_pandas_exact_ints`. Resolve all four at their definition and follow aliases. For the three
    `arrow_to_*` functions, also follow the public re-exports in `decoy_engine.arrow_frames` and the root package. This replaces the branch's
    `{table_to_pandas, table_to_pandas_exact_ints, _pandas_categories}`.
  - The census assertion becomes: every function in `internal/pandas_compat.py` that calls the exact attribute `to_pandas` is a sink, or a
    private helper that only a sink calls. On main that is `arrow_to_frame`, `arrow_to_series` and
    `_first_failing_column`, and only `arrow_to_frame` calls `_first_failing_column`. Exclude `arrow_dtype_label`, whose call is to `to_pandas_dtype`.
  - Keep the resolved direct-caller check (M-36) and the alias resolution from round 4.
  - Remove the bare-statement rule (old M-29): the check returns its input, so a call whose result is dropped is
    correct.
  - **Round 6 DESIGN fix, kept and measured (revision 6, L1).** Name the bound as the module constant `_STOP_AT` and
    use it in the size assertion. Register it in `tests/sentry/ratchet/_limit_constants.py` `LIMITS` as
    `("test_source_date_read_guard.py", "_STOP_AT"): "max"`, and mirror it in
    `tests/sentry/baselines/sentry-limits.json` with a reason.
  - Its value is the measured length of `_DOWNSTREAM_FUNCTIONS` on the S5a head, after the sink set is rebuilt. It is
    not 40: the 31 entries counted on the branch were never measured against post-#799 main. The builder report states
    the measured count. If it is above 40 (the branch's stop), the builder stops and reports instead of pinning.
- **One decision site** (new rule in the same sentry). Outside `io/source_dates.py`, no module under `src/decoy_engine`
  constructs `SourceDateUnrepresentableError` or `SourceDateTypeUnsupportedError` (their definitions in
  `io/bounded_reader.py` are the only other mention), and no module imports the holdable helpers. A second check in a
  conversion helper (the R6 route disagreement) fails this rule. The walk parses the tree and resolves import aliases,
  as the existing sentry does.
- **No S5 conversion code** (revision 6, H2). The builder report checks added lines with this command:
  ```
  git diff origin/main -U0 -- src | grep '^+' | grep -E 'to_pandas|arrow_to_(frame|series)|table_to_pandas'
  ```
  Explain every hit line by line. For a comment or docstring, identify the text. For an existing call moved or
  re-indented, show the matching base call and its unchanged arguments and behavior. A new conversion fails the check.
  - `internal/pandas_compat.py`, `execution/pipeline/_source_types.py`, `execution/_pipeline_finalize.py`,
    `execution/pipeline/post_scan/`, `execution/chunked/_progress.py` and `safe_output/` stay byte-identical to
    `origin/main`. The report shows `git diff origin/main --stat` for these paths, and it must be empty.
  - In the files S5a does touch, every existing conversion call stays main's
    `arrow_to_frame(..., on_unrepresentable=...)` call with its original arguments and behavior.
- **Admission soundness** (AT-V20). Every date column the check admits converts through main's `arrow_to_frame`, and
  every one of its cells, dictionary entries included, reads through `iloc` and `as_py`.

**Reads stay main's reads.** S5 does not change how a source is read.
- Whole-file reads: `LazySource.to_table` (feeding `profile/_readers.py:417`) and the S3/GCS whole-object reads
  (`profile/_cloud_readers.py:272` and `:394`, main's `pq.read_table` then `arrow_to_frame`). For these, insert
  `check_source_dates` on the returned table before main's conversion, and change nothing else. The check gates the
  table's schema and cells. Do not port `read_table_gated` or the `pyarrow.dataset` import.
- A whole-file read decodes a refused column once before the refusal. That costs time only, on the in-memory route.
- Batch reads keep the S5 branch's open-time gate on the projected schema (`projected_schema`, `_gate_open`; round 5
  confirmed it), because a batch iterator uses `ParquetFile` semantics on both sides.
- A file that Arrow itself cannot decode (a null parent in a `fixed_size_list<date32>`) fails with Arrow's error, as on
  main (follow-up G-14).

**Table name.** Unchanged from revision 4 and kept from the branch:
- `check_resident_sources` rebinds a lazy source to its `sources` mapping key;
- the single-source chunked entries use the configured table;
- ISO carries the key through the manifest.

#### Behavior matrix

The decision is a pure function of the column type and its cell values (all entries, for a dictionary). Routes only
have to reach it. So the matrix is tested in two layers: the rule is tested exhaustively at the function, and each route
is tested to reach the same function and report its answer unchanged.

Axes:

- Routes:
  - FF and AUTO (`run_pipeline`);
  - SEQ (`run_pipeline` sequential and direct `run_sequential`);
  - OOC (`run_pipeline` out_of_core and `run_fk_out_of_core`, Python and native backend);
  - CH (`run_mask_pipeline_chunked`);
  - NCH (`run_mask_chunked`);
  - PAN (`PandasExecutionAdapter.run` and `run_single`);
  - ISO (isolation on and off);
  - CLOUD (S3/GCS whole-object and range readers, in-memory fetch);
  - HIVE (a `LazySource` over a Hive-partitioned directory, whole-file and batch reads);
  - PROF (profile head sample, resident and lazy).
- Layouts:
  - plain, one chunk;
  - plain, many chunks (slices of one array, chunk size 2 on chunked routes);
  - plain, sliced, with a bad value in hidden storage outside the slice;
  - dictionary, one chunk;
  - dictionary, many chunks sharing one dictionary;
  - dictionary, many chunks with different dictionaries;
  - record batch and table.
- Zones (timestamps only): naive; `UTC`; negative (`America/New_York`, `-08:00`); positive (`Asia/Kolkata`, `+05:30`,
  `Pacific/Kiritimati`); zones where `pytz` and `zoneinfo` differ (`Australia/Sydney`, `Pacific/Auckland`,
  `Europe/Berlin`); an unknown zone (`Factory`).
- Units: `date32`, `date64`, `timestamp` `s`, `ms`, `us`, `ns`.
- Positions:
  - ordinary;
  - unused (a dictionary entry no row references; for plain, hidden storage outside a slice);
  - referenced;
  - null dictionary entry;
  - at each bound: `lo` and `hi` themselves, one tick outside each, a band cell whose local time stays inside, and a
    band cell whose local time leaves.

| Cell group | Cells | Expected | Acceptance test | Mutation that must turn it red |
|---|---|---|---|---|
| R. Rule | every unit x zone x position, plain and dictionary, at the function | holdable per the table above; dictionary read only when all entries are holdable and none is null; plain hidden storage ignored | AT-V12 (enumerated table), AT-V13 (property against the real conversion) | M-38 `<=` turned into `<` at `lo`; M-39 `ns` bounds left untested; M-40 local test skipped; M-41 offset sign flipped; M-42 band margin set to 0; M-43 only referenced dictionary entries tested; M-53 band offset from `zoneinfo`; M-54 null entry admitted |
| Z. Zone library | Sydney and Auckland at the `ns` top, Berlin near the `ns` top, New York local mean time at the `ns` bottom, `Factory` | Sydney and Auckland refused; Berlin read where pandas reads it; New York at `INT64_MIN + 42` refused and at `INT64_MIN + 5h` read; `Factory` refused | AT-V12 rows, AT-V13 | M-53 |
| A. Admission soundness | generated admitted date columns, every unit, zone and layout | `arrow_to_frame` on main's code converts; every `iloc`, every dictionary category and every `as_py` read succeeds and none is `NaT` for a non-null source cell | AT-V20 | M-39, M-53, M-54 |
| L. Layout | each R cell in every layout | same decision and same `count` as the one-chunk plain or one-chunk dictionary form | AT-V14 (layout invariance property) | M-43; M-44 only the first chunk's dictionary tested |
| P. Purity and cost | every admitted R cell in every layout; a 10M-row `int8`-coded `dictionary<date32>` | `check_source_dates(x) is x`; on the dictionary, the Arrow pool grows by less than 1 MiB on the pass path (decoding the rows would allocate 40 MB) | AT-V15 | M-45 the check returns a rebuilt table; M-55 the pass path decodes dictionary rows |
| T. Type gate (Q6 = A) | containers, list views, run-end-encoded, union, extension, dictionary of non-date, at the function and on FF, CH, NCH and a lazy route | `source_date_type_unsupported` with table, column and kind | AT-V3, AT-V4, AT-V5 (kept) | M-21, M-25, M-26, M-27 (kept) |
| X. Route reach | the route-by-fixture table below | the literal expected outcome per executed cell; nothing published on a refusal; the executed-cell count is exact | AT-V16 (route fingerprint), AT-V1 (kept: far date after the first 10,000 rows) | M-46 drop the check from one chunked entry; M-47 skip `check_resident_sources` in `PandasExecutionAdapter.run`; M-48 a second check in `internal/pandas_compat.py` (decision-site rule and AT-V16 NCH); M-24, M-36 (kept read-sentry mutants) |
| N. Name binding | lazy sources under a mapping key, stale `table=`, ISO manifest | refusal names the mapping key | AT-V7 (kept) | M-23, M-37 (kept) |
| H. Reads unchanged | HIVE, CLOUD whole-object, a directory, a dotted projection, `columns=["key"]` | the returned table equals main's `pq.read_table` with the same arguments, schema and types included (`key` stays `dictionary<int32>`); a bad date in a partition file refuses with the mapping key | AT-V17 | M-49 reintroduce a dataset scanner without dictionary inference |
| C. Conversion unchanged | admitted date dictionaries through FF, CH, fidelity report and post-scan; a named and an unnamed date `CategoricalIndex`; a MultiIndex with a date level; a sub-microsecond `time64` sibling on the resident profile | the pandas frame and the output equal those of `origin/main` on the same input | AT-V19 (differential against main) | M-50 route admitted dictionaries through any custom conversion |
| S. Sentries | the read sentry with main's sinks, the decision-site rule, `_STOP_AT` | seeded bypasses fail; a seeded `arrow_to_series` call on unchecked data fails; `_STOP_AT` equals the measured count and is in the bound registry | AT-V8 (kept seeds 1, 2, 4, plus seed 5 for `arrow_frames.arrow_to_frame` by alias), AT-V18 | M-48; M-51 raise `_STOP_AT` by one; M-52 inline the literal again; M-56 drop `arrow_to_series` from the sink set |

**Fixture set F for AT-V16.** Each fixture is one table `t` with a column `c` and an ordinary `id` column. Each runs as
one chunk and as chunks of two rows.

| Fixture | Column | Expected |
|---|---|---|
| F1 | plain `date32`, year 10183 at row 10,001 (beyond the profile head and, in the split layout, in a later chunk, batch or row group) | refused, `source_date_unrepresentable`, `t`, `c`, `count == 1` |
| F2 | `dictionary<timestamp[ns, America/New_York]>`, entries `[0, INT64_MIN + 42]`, rows reference only entry 0 | refused, `count == 0` |
| F3 | `dictionary<date32>`, entries `[2020-01-01, 9999-12-31, 0001-01-01]`, rows reference the first two | read; output values equal the input; output type equals what `origin/main` gives for the same input |
| F4 | plain `timestamp[us, Asia/Kolkata]`, `9999-12-31T23:00Z` | refused, `count == 1` |
| F5 | plain `timestamp[ns]`, `INT64_MIN` | refused, `count == 1` |
| F6 | plain `timestamp[us, America/Chicago]`, `9999-12-31T06:00Z` (a database "never" value) | read; output equals what `origin/main` gives |
| F7 | `list<date32>`, dates in range | refused, `source_date_type_unsupported`, kind `list` |
| F8 | plain `timestamp[ns, Australia/Sydney]`, `INT64_MAX - 10h` | refused, `count == 1` |
| F9 | `dictionary<date32>`, entries `[2020-01-01, null]`, rows reference entry 0 | refused, `count == 0` |

**Route by fixture (revisions 6 and 7).** Each cell is `run` or `n/a`. "Arrow" means a resident `pa.Table`, a
`source_loader` result or chunked API batches. "Parquet" means a `LazySource` or a cloud object. A dictionary fixture
must never be fed through Parquet to stand in for its Arrow form: Parquet stores no date dictionary, and the fixture
would arrive as a plain column and test something else.

| Route and input | F1 | F2 | F3 | F4 | F5 | F6 | F7 | F8 | F9 |
|---|---|---|---|---|---|---|---|---|---|
| FF/AUTO, Arrow | run | run | run | run | run | run | run | run | run |
| FF/AUTO, Parquet | run | n/a | n/a | run | run | run | run | run | n/a |
| SEQ, loader (Arrow) | run | run | run | run | run | run | run | run | run |
| SEQ, lazy Parquet | run | n/a | n/a | run | run | run | run | run | n/a |
| OOC, Python (`run_fk_out_of_core`, `sources` as `pa.Table`) | run | run | run | run | run | run | run | run | run |
| OOC, Python, Parquet | run | n/a | n/a | run | run | run | run | run | n/a |
| OOC, native, Arrow | run | run | run | run | run | run | run | run | run |
| OOC, native, Parquet | run | n/a | n/a | run | run | run | run | run | n/a |
| CH, Arrow batches | run | run | run | run | run | run | run | run | run |
| NCH, Arrow batches | run | run | run | run | run | run | run | run | run |
| PAN `run` and `run_single`, Arrow | run | run | run | run | run | run | run | run | run |
| ISO on, Arrow | run | run | run | run | run | run | run | run | run |
| CLOUD, Parquet object | run | n/a | n/a | run | run | run | run | run | n/a |
| HIVE, Parquet | run | n/a | n/a | run | run | run | run | run | n/a |
| PROF, Arrow | run | run | run | run | run | run | run | run | run |
| PROF, Parquet | run | n/a | n/a | run | run | run | run | run | n/a |

Parquet stores no date dictionary, which accounts for every `n/a`. The table has 9 Arrow rows × 9 fixtures and
7 Parquet rows × 6 fixtures, or 123 route/fixture cells. Run each cell in both layouts (for files, one row group or
row groups of two). Assert that the completed (route row, fixture, layout) keys equal the expected set, with 123
cells per layout and 246 completed cases in total. For grouped routes, exercise every named entry within the case
before counting it. For each refusal:

- the message is exactly the name-only text;
- no year, day, timestamp or count appears in `str`, `repr`, captured logs or an isolated child result;
- `__cause__` and `__context__` are empty;
- nothing is published.

#### Tests in detail

- **AT-V12** (`tests/unit/io/test_source_date_hold_rule.py`, new). An enumerated table of every unit x zone x position
  cell above, plain and as a dictionary entry (used and unused), each with its literal expected decision. It includes
  the Z group rows:
  - Sydney and Auckland at `INT64_MAX - 10h` and `INT64_MAX - 12h`: refused;
  - Berlin at `INT64_MAX - 3601 s`: read;
  - New York at `INT64_MIN + 42` (refused) and `INT64_MIN + 5h` (read);
  - fixed offsets at both bounds;
  - `Factory`: refused;
  - a null dictionary entry, used and unused: refused.

  Expectations are literal only. They are written from the rule table and checked once against real conversion,
  never taken from the function under test.
- **AT-V13** (same file). Hypothesis property over random `v`, drawn uniformly and from the bands (within `2 * M` of
  each `lo` and `hi`), for every unit and every listed zone. The vectorized decision must equal an oracle that uses only
  the real path: build a one-element Arrow array; holdable means `to_pandas()`, `iloc[0]` and `as_py()` all succeed,
  the pandas value is not `NaT`, and the instant lies in years 1 to 9999. The oracle does not compute an offset and has
  no band shortcut, so it shares no model with the implementation. Use a fixed seed and database, and pin any failing
  example as an AT-V12 row.
- **AT-V14** (same file). Hypothesis property over generated columns: the decision and `count` are equal for the column
  in each of these forms:
  - as one chunk;
  - as random slices re-chunked;
  - after `combine_chunks`;
  - after `unify_dictionaries`;
  - as a record batch and as a table.

  For dictionaries with no unused or null entry, the decision also equals the decision on the decoded plain column.
- **AT-V15** (same file). For every admitted case of AT-V12 and AT-V14, `check_source_dates(x, table="t") is x`. Also,
  build the 10M-row `int8`-coded `dictionary<date32>` with three entries before measuring. Use a fresh Arrow
  proxy memory pool for the call and assert peak allocation below 1 MiB, including buffers freed before return.
  Restore the original pool after the measurement.
- **AT-V16** (`tests/unit/execution/test_source_date_route_fingerprint.py`, new). The route-by-fixture table above,
  through the public entries, with the executed-cell count asserted.
- **AT-V17** (`tests/unit/profile/test_whole_file_read_unchanged.py`, replaces the branch's
  `test_whole_file_gate_q6a.py`). Cases: Hive directory `key=7/part.parquet`, no projection, `columns=["key"]`,
  `columns=["s.when"]`, a plain directory, and the in-memory S3/GCS whole object. For each, the returned Arrow table
  equals `pq.read_table(path, **same_args)`, schema included. A far `date32` in the partition file refuses with the
  mapping key.
- **AT-V18** (in `tests/sentry/test_source_date_read_guard.py`).
  - The decision-site rule, with a seeded `raise SourceDateUnrepresentableError(...)` in an in-memory copy of
    `internal/pandas_compat.py`, and an aliased import of the error.
  - `_STOP_AT` is a module constant, it is in `LIMITS`, and its live value equals the `sentry-limits` baseline.
  - The sink census matches post-#799 `pandas_compat.py` as stated above.
- **AT-V19** (`tests/unit/execution/test_source_date_conversion_unchanged.py`, new). A differential lock, green on
  base. Build the frames and outputs for the conversion cells on `origin/main`, record them as literal fixtures in the
  test (generated once from base and committed), and assert that the head gives the same values, dtypes, index and
  columns. If a cell fails on main itself, record it as a follow-up and drop it from the lock; do not fix it in S5.
- **AT-V20** (`tests/unit/io/test_source_date_hold_rule.py`, new in revision 6, M3). Hypothesis property over
  generated date columns: every unit, the listed zones, plain and dictionary, one chunk and many, values drawn near
  both bounds. For every column the check admits:
  - `arrow_to_frame(pa.table({"c": col}), on_unrepresentable=<raising callback>)` succeeds;
  - every row's `iloc` succeeds and is not `NaT` for a non-null source cell;
  - for a dictionary, every entry in `series.cat.categories` reads as a scalar;
  - `as_py()` succeeds on every non-null value and every dictionary entry.

  Keep both dictionary checks. In pandas 2.3.3 the categories of `dictionary<timestamp[ns, zone]>` come back as
  naive `datetime64[ns]`. Reading the original Arrow entries with `as_py()` checks their zone.

  This ties S5's predicate to main's real conversion. A value the check admits and the conversion refuses fails here
  before it can become a route split.
- **Kept from the branch, unchanged in purpose:**
  - AT-V1, with F-style literal expectations;
  - AT-V2, which moves to S5b;
  - AT-V3, without the repair and IPC parts;
  - AT-V4, AT-V5 and AT-V7;
  - AT-V8 seeds 1, 2 and 4, plus seed 5 (`from decoy_engine.arrow_frames import arrow_to_frame as conv` on unchecked
    data);
  - AT-V9 with the new vocabulary: `min_max`, `less`, `greater`, `or_`, `and_`, `invert`, `fill_null`, `sum`,
    `unique` and `is_null`. Allow `pc.take` only inside the dictionary refusal counter, gathering the bad-entry
    mask by indices after a failed entry check. Seed a pass-path `take` and require AT-V9 to reject it. Check the
    AST argument of each array `cast`: allow only `pa.int32()` and `pa.int64()` for the physical integer views.
    Seed `column.cast(arrow_type.value_type)` and require it to fail. Exclude `local_timestamp`, `cumulative_sum`
    and `subtract`. Allow stdlib `datetime` and `pyarrow.lib.string_to_tzinfo` imports.
- **Removed:** AT-V6 (repair), AT-V10 (owned date buffers, follow-up G-12), AT-V11 (moves to row DEP-FLOOR).

Red-first expectations by route

- *Main defect on converting routes:* F5 becomes `NaT` and the F8 scalar read fails (rows 9 and 8).
  The `Factory` case raises an uncoded resolver error (row 14).
- *Contract change, red on main by design:* F5 and F8 on NCH and CH passthrough where main returns them exactly.
  Include F2 and F4 on every route, F1 and F9 on passthrough where main returns them, and the `Factory` NCH case.
  Record the old success and the new refusal for rows 5, 7, 11, 13 and 14.
- *Different code on main:* F1 and F9 on converting routes, and converting cases in rows 2, 3, 6 and 12.
  The main profile conversion already refuses with `source_column_unrepresentable`.
- *Red on the S5 branch head `a5da43ef9`:* F2 on `run_mask_chunked`, F8, and the round 6 layout and zone cases.
- *Locks, green on base:* F3, F6, AT-V17 and AT-V19.

Each mutation runs on the final head (catalog class 9).

#### What the S5 branch keeps and what it discards

**Port method.**
1. Build S5a on a fresh branch from `origin/main` at `395c1c662` or later.
2. For a file that main and the branch both changed since `9812da814`, re-apply only the S5 hunks by hand.
   `git diff 9812da814 a5da43ef9 -- <path>` lists them; take the hunks named in the table below onto main's version.
   Never run `git checkout a5da43ef9 -- <path>` on these files, because it would revert #799. The files are:
   - `CODEMAP.md`;
   - `execution/_chunked_profile.py`, `_pandas_adapter.py`, `_pipeline_finalize.py`, `_sequential.py`;
   - `execution/pipeline/_source_types.py`;
   - `internal/pandas_compat.py`;
   - `profile/_cloud_readers.py`, `_readers.py`, `_readers_resident.py`;
   - `tests/native/test_chunked_entry_rev9_shapes.py`, `tests/native/test_chunked_entry_values_schema.py`;
   - `tests/sentry/file_access_registry.toml`;
   - `tests/unit/execution/run_stream/test_lazy_input.py`;
   - `tests/unit/profile/test_supplied_table_profiling.py`.
3. A file that main has not changed since `9812da814` may be taken whole from `a5da43ef9` and then edited as noted.
   Check this with `git diff --quiet 9812da814 origin/main -- <path>`.
4. Do not cherry-pick: the branch's 44 commits mix kept work, discarded work and S5b content.

Kept hunks in the shared files:

| File (both #799 and S5 changed it) | S5a takes | Stays main's |
|---|---|---|
| `execution/_chunked_profile.py` | the check call and the table-name plumbing | the `arrow_to_frame(..., source_column_unrepresentable(table_name))` calls (`:43`, `:170`) |
| `execution/_pandas_adapter.py`, `execution/_sequential.py` | `check_resident_sources` / `checked_loader` wiring | everything else |
| `profile/_readers.py` | the batch open gate, the one-open sample, the check on `to_table`'s result, the `table` field | every `arrow_to_frame` call (`:417`, `:500`, `:505`) |
| `profile/_cloud_readers.py` | the range-reader schema gate; `check_source_dates` between `pq.read_table` and `arrow_to_frame` at `:272` and `:394` | the reads and conversions; no footer pre-gate |
| `profile/_readers_resident.py` | the `name` field and the check call | the fallback and `arrow_to_frame` at `:20` |
| `execution/_pipeline_finalize.py`, `execution/pipeline/_source_types.py`, `internal/pandas_compat.py` | nothing | the whole file |
| `CODEMAP.md` | rows for the new S5a files | the rest |
| `tests/sentry/file_access_registry.toml` | nothing expected (S5a adds no file access); recompute only if the registry test says so | the rest |
| the four shared test files | table name on the lazy copy and date expectations from 4.4a | #799's coded expectations for other types |

Kept and discarded, by area:

| Keep (port, then edit as noted) | Discard |
|---|---|
| `_arrow_types.py` (date leaf, shape classifier, unclassified layouts, type walker, calendar day numbers) | `internal/pandas_compat.py` changes: working categorical, `WorkingInstant`, `stored_index_names`, `table_to_pandas`, `_refuse_unholdable` |
| `io/source_dates.py`: schema gate, `_holds_dates`, `checked_batches`, lazy binding, `check_resident_sources`, `checked_loader`. Edit: drop `_repaired_dictionary`, `_without_unused_bad_entries`, `_fixed_offset_seconds` and the row-decoding count on the pass path; test every dictionary entry and refuse null entries; add the `ns` bounds and the resolver band test; return the input | `safe_output/_date_buffers.py` and its `own_date_*` exports in `safe_output/__init__.py` (no buffer rewrite), the `output_table` change and the `execution/chunked/_progress.py` hook |
| `io/bounded_reader.py` errors (message built with `source_location_text`), `io/__init__.py` exports, the two reasons in `reasons/runtime/_part3.py` (summary and remediation rewritten as above), `reason_adapter.py` rows | `fileaccess/adapters/arrow.py` `read_table_gated` and the `pyarrow.dataset` import |
| Entry wiring: `_chunked.py`, `_chunked_input.py`, `_isolated_commit.py`, `_isolated_worker.py`, `native/_chunked_entry.py`, `out_of_core/_runner.py`, and the shared files per the table above. Keep `execution/_pipeline.py` to wire `checked_loader` and `check_resident_sources` into `run_pipeline` | `execution/pipeline/_source_types.py`, `execution/_pipeline_finalize.py`, the branch's `execution/pipeline/_post_scan.py` change (main moved the file to `post_scan/_gate.py`): main's versions stay |
| Profile: `_lazy_build.py`, `_source.py` (table name), and the shared profile files per the table above | `profile/_readers_resident.py` fallback rewrite |
| `fileaccess/adapters/arrow.py` walker move and `projected_schema`; `verification/canary/_canonical.py` constants | `safe_output/_file_metadata.py` optional list-view rows and their tests in `tests/unit/safe_output/test_file_metadata.py` and `tests/unit/test_import_floor.py` (move to row DEP-FLOOR) |
| `tests/native/_rev9_support.py`, `tests/native/_rev9_profile_cases.py` and `tests/native/test_unconfigured_passthrough_types.py`: keep the admitted-edge coverage and apply 4.4a to every refused carrier. Use the admitted carriers in the checked profile cases when porting the branch fixture loop. Keep `tests/native/test_unconfigured_passthrough_read.py` and `tests/unit/execution/test_full_frame_value_unrepresentable.py` for the sibling and coded-error claims in 4.4a | |
| `tests/native/test_column_access_surfaces.py`: include the new `check_resident_sources` call in the adapter guard. `tests/unit/profiling/test_scan_set.py`: forward `**kwargs` through the spy so it still checks that the bounded head consumes one batch | |
| Tests in `tests/unit/io/`: `test_source_date_type_gate.py`, `test_source_date_shape_classifier.py`, `test_source_date_nested_refusal_q6a.py`, `test_source_dates_vocabulary.py`, `test_checked_source_dates.py` (dictionary refusals and AT-V15 identity) and `test_source_dates_fixed_offset.py` (port cases to AT-V12). In `tests/unit/execution/`: `test_source_date_nested_routes_q6a.py`, `test_source_date_type_routes.py` and `test_source_date_unrepresentable.py`. Keep `tests/unit/profile/test_source_type_gate_projection_q6a.py`; the shared test files per the table above | Tests: `tests/unit/internal/test_working_categorical.py`, `test_no_import_time_timestamps.py`, `tests/unit/safe_output/test_date_buffers_ipc.py`, `tests/unit/profile/test_resident_fallback_dates.py`, `test_whole_file_gate_q6a.py` (replaced by AT-V17), `tests/unit/execution/test_source_date_reports_r1.py` (replaced by AT-V19), and `tests/sentry/test_signed_evidence_file_access.py` (its count change, 203 to 202, followed `read_table_gated`; main's file stays) |
| `tests/sentry/test_source_date_read_guard.py` with main's sinks, `_STOP_AT` measured and registered, and the decision-site rule | The bare-statement rule in the read sentry (old M-29) |
| `_execution_error.py`: extract `source_location_text` (new, about 10 lines) | |
| Docs: `docs/strategies.md` S5 paragraph (edit per section 4.7, naming the narrowings in the comparison table), CODEMAP rows for new files, `changelog.d/date-range-s5-source-dates.md` listing the narrowed set | |

S5b (fitted distribution admission, row L, AT-V2) ports these files:
- `contracts/calendar_range.py`, `contracts/distribution_snapshot.py`;
- `generators/_distribution.py`;
- `generation/_window_admission.py`, `generation/statistical/__init__.py`, `generation/statistical/_degenerate.py`;
- the two calendar day-number constants in `_arrow_types.py`;
- `tests/unit/generation/test_date_range_compile_routes.py`,
  `tests/unit/generators/test_distribution_datetime_range.py`, `tests/unit/generators/test_columns_qa1.py`.

#799 changed none of these files, so they can be taken whole and then rebased; the builder checks with
`git diff --quiet 9812da814 origin/main -- <path>`. Round 6 found nothing open in this code. Its last DESIGN finding
(the `1..9998` literal) closed in round 6.

In the builder report, compare the path list from `git diff --name-only 9812da814 a5da43ef9` (75 files) with the
paths assigned above. Give each path a disposition (keep, discard or S5b) and identify the hunks for mixed files.
Expand grouped test entries to full paths. The two path sets must match exactly. Resolve any missing disposition
before porting.

#### Size

| Slice | Ported from `a5da43ef9` | New or changed | Estimate |
|---|---|---|---|
| S5a | about 2,700 lines (about 900 source, 1,800 tests) already reviewed in rounds 3 to 6, with the shared-file hunks re-applied onto main by hand | about 750: `source_dates.py` rule edits (about 70 source lines net; the file goes from 319 to about 280), `source_location_text`, two read edits, the sentry sink set and rules (about 80), AT-V12 to AT-V20 (about 550 test lines) | about one day |
| S5b | about 600 lines (about 300 source, 300 tests) | rebase only | half a day with review |

No module crosses 600 lines and no ceiling or pin is raised. One bound row is added, `_STOP_AT`, at its measured
value. If the S5a build's new or changed lines pass 1,000, the builder stops and splits it:
- S5a-1: the type gate, wiring, name binding and read sentry (all ported);
- S5a-2: the holdable rule, the dictionary rule and AT-V12 to AT-V16 and AT-V20.

#### What is not S5

| Item | Where it goes | Why not S5 |
|---|---|---|
| The output assembler mixes pandas display labels with Arrow field names. Integer or tuple column labels raise `IndexError` or `TypeError` during passthrough assembly (`execution/pipeline/_source_types.py`, round 6) | New row ASSEMBLER-LABELS (engine, V1 function break, R2, about half a day): map source-backed display labels to physical fields by position; tests with integer, tuple and duplicate-looking labels on FF passthrough. The builder re-anchors on main after #799 | Reproduces on main with ordinary integer data; S5 no longer touches the assembler |
| Two resolvers read the stored index from pandas metadata (`execution/pipeline/_source_types.py` and `_pandas_meta/_columns.py` `stored_index_fields`) | The structure review list (owner 11-18: one structure review after V1), or folded into ASSEMBLER-LABELS if its fix needs one resolver | Pre-existing duplication; the third copy was S5's and is discarded |
| The engine does not import at the declared floors: pyarrow 14 (unconditional list-view predicate, `safe_output/_file_metadata.py`) and pandas 1.5.3 (`validators/_dates.py:13`) | New row DEP-FLOOR (engine, R2): the branch's optional list-view rows and `test_import_floor.py`, exact-version CI legs that also run AT-V13 and AT-V20, and the pandas floor answer (Q7) | Pre-existing on main; independent of dates |
| Hidden storage outside a slice is serialized when a caller writes a returned passthrough table to IPC (all types) | G-12, V2-LOG | The caller's own data returned to the caller; no trust boundary is crossed (V1 threat model: accidental leaks) |
| A Parquet file Arrow cannot decode fails with Arrow's error before the type refusal | G-14, log | Pre-existing; the read is main's read |
| The resident profile fallback rebuild drops a stored index (round 5) | G-15, log | Pre-existing (round 5 says the rebuild predates S5) |
| The holdable rule assumes pandas 2 keeps the source unit; pandas 1.x holds every timestamp in `ns` | DEP-FLOOR decides (Q7) | The engine does not import on pandas 1.5.3 today |

### 4.5 Placement

| Item | Place | Why |
|---|---|---|
| `DateDomain`, `DatePartition`, `DateRangeError`, range table | `transforms/date_preserve.py` (275 lines today, about 400 after) | `transforms/` is at its fan-out limit (CODEMAP "Transforms" row); the matching code it extends is already here |
| New reason | `reasons/runtime/_part3.py`, new `_catalog.runtime("DateRangeError")` binding | runtime reason home; `_part3.py` is 553 lines |
| Coded family row | `reason_adapter.py:44-70` `_CODED`: `("decoy_engine.transforms.date_preserve", "DateRangeError", "runtime")`, the defining module | without it the adapter and isolated-child classification report the refusal uncoded; `tests/unit/test_reason_registry.py:198-218` already checks every row resolves and gains a case that `reason_from_exception(DateRangeError(...))` returns the new code |
| S5 source boundary | Existing `io/bounded_reader.py` (CODEMAP.md:129), public checked Arrow reader API exported by `decoy_engine.io`. Error `SourceDateUnrepresentableError` in `io/bounded_reader.py:106`, code in `reasons/runtime/_part3.py`, adapter row `("decoy_engine.io.bounded_reader", "SourceDateUnrepresentableError", "runtime")` at `reason_adapter.py:57` | Profile and run readers may both import io under `.importlinter:22-25` |
| S5 shared type walker (4.4b) | `type_children` and `type_nodes` move from `fileaccess/adapters/arrow.py:150-169` to the bottom-tier `decoy_engine/_arrow_types.py` (259 lines), which `io/source_dates.py` already imports; `fileaccess/adapters/arrow.py` imports them back | one copy of Arrow's nesting rules for the file-access type checks and the date gate; both consumers already import the bottom tier, and the date gate is not file access, so it does not belong in `fileaccess`. `_array_children` and `_walk` stay in `fileaccess/adapters/arrow.py:172-190` and zip with the moved `type_children` order: use `strict=True` at line 189 wherever `_array_children` is not empty, and add a `tests/unit/test_arrow_types.py` case that pins `type_children` for each kind (extension, dictionary, map, struct, union, list kinds, list views, run-end-encoded) |
| S5 type gate and holdable rule (4.4b) | `SourceDateTypeUnsupportedError` beside `SourceDateUnrepresentableError` in `io/bounded_reader.py`; reason in `reasons/runtime/_part3.py`; adapter row `("decoy_engine.io.bounded_reader", "SourceDateTypeUnsupportedError", "runtime")`; gate, holdable rule and lazy binding in `io/source_dates.py` (about 290 lines) | the existing error and check live there; no new module |
| S5 rule tests (4.4b, revision 5) | `tests/unit/io/test_source_date_hold_rule.py` (AT-V12 to AT-V15), `tests/unit/execution/test_source_date_route_fingerprint.py` (AT-V16), `tests/unit/profile/test_whole_file_read_unchanged.py` (AT-V17), `tests/unit/execution/test_source_date_conversion_unchanged.py` (AT-V19) | per-module unit homes; the route fingerprint sits with the other route tests |
| S5 read guard (4.4b) | `tests/sentry/test_source_date_read_guard.py` (moved from `tests/unit/execution/test_source_date_unrepresentable.py`) | CODEMAP.md:165, beside the other choke-point sentries |
| S5 type tests (4.4b) | `tests/unit/io/test_checked_source_dates.py` for the unit cases; route cases in `tests/unit/execution/test_source_date_unrepresentable.py` | the existing S5 test homes |
| User docs | `docs/strategies.md` (date strategies, `preserve_values`), `docs/reasons.md` generated entries, `changelog.d/` fragments | section 4.7 |
| Sentry | `tests/sentry/test_date_partition_choke_point.py` | CODEMAP.md:165, beside the other choke-point sentries |
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
- S5 documents which source columns are read (plain date and timestamp columns and top-level dictionaries of them), that a column holding a date inside a list, map, struct or other container is refused with `runtime/source_date_type_unsupported` whatever its dates are, the remedy (drop, select out or cast the column), and that a date dictionary is refused when any entry, used or not, is outside the range a row can hold or when it has a null entry (remedy: decode the column or re-encode its dictionary). It names the `ns` and zoned limits in plain words, and it lists the inputs main accepted that S5 now refuses (section 4.4b, rows 5, 7, 11, 13 and 14, including the row 8 and 9 passthrough cases), subject to Q8. It replaces `docs/strategies.md:403-405`.
- In S5a update #799's paragraph on `run_mask_chunked` and `run_mask_pipeline_chunked` in `docs/compatibility-contract.md`.
  The date check can raise `SourceDateUnrepresentableError` (`runtime/source_date_unrepresentable`) or
  `SourceDateTypeUnsupportedError` (`runtime/source_date_type_unsupported`) before conversion, including on NCH
  passthrough that previously succeeded. In the same file, update the dispatcher's pinned guarantees at
  `:975-980`: both entries now refuse `INT64_MIN` ns and a date32 outside the calendar. Keep the exact integer and
  time64 examples, #799's codes for other conversion failures and #830's detector text.
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
| `date32` beyond year 9999 (S5) | profile conversion refuses with `source_column_unrepresentable` after #799. NCH passthrough returns the date | coded refusal `runtime/source_date_unrepresentable` naming table and column; batch count on the typed exception |
| a date inside a list, map, struct, list view, run-end-encoded, union or extension column, or a dictionary of anything but plain dates (S5, 4.4b) | passes, or an uncoded Arrow error, or a hidden far value reaches output | refusal `runtime/source_date_type_unsupported` naming table, column and container kind, in or out of the calendar (Q6) |
| ordered date32 dictionary with an unused year-10183 entry (S5, 4.4b) | main profile conversion refuses with `source_column_unrepresentable`. NCH passthrough returns it | refuse the whole column with `source_date_unrepresentable` and count zero when no row uses a bad entry |
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

- AT-V1: place an unrepresentable date32 at row 10,001 in a later Parquet row group. Run FF, AUTO, SEQ, CH, NCH, OOC and ISO with an ordinary first 10,000 rows. Also exercise a first-batch profile failure, a resident table, a caller loader, opened batches and direct OOC. Assert runtime/source_date_unrepresentable, correct table and column, the batch count on the typed exception, exact names-only rendered text, no year in the error, log or child result, empty cause and context, and no publication. Cover both ends for date32/date64 and each timestamp unit where such values exist, null-only batches, valid calendar endpoints and a timezone offset crossing a calendar endpoint.
- AT-V2: compile a distribution generator with max 9999-12-31, min 0001-01-01, and an unsupported live bin between otherwise ordinary inputs as separate fixtures. The compile entry and a direct generator call both refuse with plan/generation_unbounded_column, before any draw. Assert no cell or bound in the message and empty cause and context. Exercise valid partial years at each ns boundary.

Section 4.4b tests. Write and run each regression before its fix. Record the failing assertion and head, then rerun
the same test on the fix. For a control already green on the reference, obtain red on its named single-fault mutation
before restoring the correct wiring. Value-free means: no year, day number, count of nested cells or child field name in `str`, `repr`, the log or an isolated child result, and empty cause and context.

- AT-V3 (findings 1, 2 and 6). One column each: `list<date32>`, `large_list<timestamp[us]>`, `fixed_size_list<date32>`, `struct<date32>`, `map<string, date32>`, `list<dictionary<date32>>` with an unused far child entry, `dictionary<struct<date32>>`, and a struct and a list with a far date under a null parent. Referenced dates are all in the calendar. Run CH and NCH, and FF and AUTO with a resident source; repeat the Parquet-storable ones as a `LazySource` file. Add an empty Parquet file and an empty resident table with a `list<date32>` column: both refuse the same way, the lazy one before the profile head reads a batch. Each refuses `runtime/source_date_type_unsupported` naming table, column and the outermost kind, value-free, with nothing published and nothing returned. No `ArrowNotImplementedError` and no `ValueError` reaches the caller. Red: both chunked APIs succeed and return the far child entry (finding 1), the public oracle raises `ValueError: year 10183 is out of range` (finding 2), and the dictionary of structs raises `ArrowNotImplementedError` (finding 6).
  - **Projection.** For both populated and zero-row Parquet with `id` and `events: list<date32>`, test
    `open_batches`, `iter_batches` and `to_table`. For opened batches assert the gate result at open, before calling `next`. Selecting only `id` succeeds with the expected rows/schema;
    selecting `events` or omitting the projection refuses before a batch reaches the caller. Opened footer facts
    still describe both columns. Also select a date-free child of a struct with a date sibling. Red on the
    unchecked head for the refusal, and on M-34 for the valid projection. For local and range-backed empty files,
    require the identical name-only reason/table/column/kind. Drive the S3/GCS helper with an in-memory range fetch;
    red on the head (returns an empty frame) and M-33.
  - **ISO precedence.** Supply the same resident nested dictionary of dates and dictionary of a date-bearing
    extension under key `t` with column `events` to both isolate settings. Assert exact
    `runtime/source_date_type_unsupported`, `t`, `events`, `dictionary`, no value in the message or logs,
    and no output; spy on staging admission/writers to prove the rejected inputs never reach them. Red first:
    the reference isolated parent reports the IPC-specific reason. Keep a non-date IPC-refusal control.
- AT-V4 (finding 3). `list_view<date32>` and `run_end_encoded<int32, date32>`, each with a far date and with in-calendar dates only, plus a `pa.ExtensionType` subclass over `date32`, `opaque(date32)` with a far date, `fixed_shape_tensor(timestamp[us], [2])` with a far date, and a dense union with a `date32` member: each refused with its kind, value-free. The list view and `opaque` cases skip when `pa.list_view` or `pa.opaque` is missing (pyarrow 14 has neither); the others always run. A plain `time64`, a plain `duration`, `list<time64>` and `struct<duration>` pass the gate unchanged (no date leaf). Red: list view and REE pass the check and native returns the far value.
- AT-V5 (finding 4). A `map<string, date32>` sliced so that the row with a far date is outside the slice and an in-calendar row stays: refused with `source_date_type_unsupported`, kind `map`, and no count. Red: the S5 head reports `source_date_unrepresentable` with count 1. The refusal of this valid-looking job is the Q6 contract; if the owner picks Q6 (B), this test becomes "passes, and the output holds no far value".
- AT-V6: removed in revision 5. S5 no longer repairs dictionaries; AT-V12 to AT-V15 in section 4.4b test the dictionary rule.
- AT-V7 (finding 7). FF, AUTO, SEQ (parent/child) and OOC read `sources={"t": LazySource(path)}` with the first bad date after the sample. Repeat with an explicit stale `table="other"`; require `t` on each failing route. Red on the unbound head. For CSV inspect the bound copy and its subclass/path and confirm the original retains its name. For ISO pass a resident, stageable plain date with a referenced FAR, using a nondefault mapping key; assert the spawned and in-process public reasons and value-free summaries. Also pass the actual staged manifest through `_isolated_worker.py:77–100` with lazy loading, then read using its bound source and assert its exception names the key. This observes transport before the child pipeline rebinds a lazy source.
- AT-V8 (DESIGN). Run each of the four executable seeds in section 4.4b separately through the scanner, asserting the exact offending caller. Check aliased imports and a stale allowance. The clean source inventory passes. Red first: the old file exemption misses seed 1, the old guard misses seeds 2–3, and the round-one finite sink set misses seed 4, whose call to `walk_one_table` reaches a year-bearing pandas conversion on the reference. Kill M-36 even after the original three seeds pass.
- AT-V9 (rule 3 of 4.4b). An `ast` test over `io/source_dates.py` fails on any `pc.` call or attribute outside the allowlist and on any import outside the allowed modules. Enforce the refusal-only `take` and integer-view `cast` rules in section 4.4b, including aliased calls. A seeded `pc.list_flatten(column)` and a seeded `.storage` each fail it. A unit test calls the counting function with a `list<date32>` column and expects the internal error. Red: the S5 head uses `.keys`, `.items`, `.flatten()` and `pc.list_flatten`, and counts the list instead of raising.
- AT-V10: removed in revision 5 (S5 no longer owns returned date buffers; follow-up G-12).
- AT-V11: moved to row DEP-FLOOR (section 14). The import floor is pre-existing and independent of dates.
- AT-V12 to AT-V19: specified in section 4.4b (rule, layout, purity, route fingerprint, reads unchanged, decision site and `_STOP_AT`, conversion unchanged).

### 6.8 Generation (S7)

- AT-F1: statistical generation whose snapshot is fitted from a column with undeclared `9999-12-31`: `plan/generation_unbounded_column`, value-free, as today. Green on base (lock).
- AT-F2: call distribution_snapshot_document(df, include_values=True, preserve_values_by_column={"end": ["9999-12-31"]}), load the persisted v2 document with the matching generation declaration, compile and generate. Assert exact count, sentinel-free ordinary bounds and bins, and sentinel frequency within a fixed-seed binomial 99.9 percent interval over 1,000 rows. Repeat with an in-range sentinel mixed with ordinary dates in its year, nulls, all-sentinel, all-null, zero observed, a declaration mismatch and a legacy refit. Exercise both date generators. Check that refused redacted/DP fits publish nothing and forged or ill-typed sentinel blocks fail value-free. S8 repeats the round trip on CSV with `decoy fit --parse-dates end --preserve-date end=9999-12-31 --include-values`, including the sampled-CSV path. Repeating the option covers multiple declarations. A malformed declaration or missing release option fails without printing its argument or writing a partial snapshot.
- AT-F3: `quality/snapshot.py` `_datetime_stats` and `profiling/_distributions.py` `_distribution_date` over object `datetime.date` values `[2020-01-01, 9999-12-31]`: through their public fit/profile dispatch both report a maximum on 9999-12-31 and count the far row once (snapshot year 9999, profile decade 9990s) (stats are computed on calendar dates, not ns). Then AT-F1 is the coded refusal a user sees, and nothing is dropped in silence. Red on base (M).
- AT-F4: a generation `windowed_date` whose statistical anchor column declares `9999-12-31`: admission uses the anchor's sentinel-free `min`/`max` and admits it; derived cells for sentinel anchors follow Q2. Red on base (L3).
- S7 known limits (found in S5 Codex round 3, both on main today): the whole-table statistical sampler (`generation/statistical/_sample.py:493-502`) reads `min` and `max` with `datetime.fromisoformat`. Equal bounds ending `.123456789`: Python 3.10 refuses at compile, 3.11 compiles and draws `.123456`, below the fitted minimum. Equal bounds ending `+01:00` compile on both, then draw raises an uncoded `TypeError` comparing an aware bound with a naive draw. S7 must fix both with one admission shared with `_window_admission._check_datetime`.

### 6.9 Existing tests whose expectation changes

These change because of the owner decision, and the builder's report lists each with the old and new expectation. Include the S5 changes in section 4.4a in that report. Any changed or deleted assertion outside these rules is a stop (plan contract class 8):

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
| M-18 | S5: render the offending year, or append the batch count to the name-only range message | AT-V1 exact message and captured logs; keep the count assertion on the typed exception |
| M-19 | S6: `declared_sentinel_rows` omitted from the report | AT-P4 |
| M-20 | S7: declared sentinels left in the fitted year bins | AT-F2 |
| M-21 | S5: `_holds_dates` walks a fixed list of container kinds without list view and run-end-encoded | AT-V4 |
| M-22 | Retired in revision 5 (no repair) | |
| M-23 | S5: skip lazy-source rebinding | AT-V7 FF/AUTO/SEQ/OOC and CSV bound copy |
| M-24 | S5: the read guard exempts `execution/_pandas_adapter.py` as a whole file again | AT-V8 seed 1 |
| M-25 | S5: the type gate lets `struct` through to the counting function | AT-V3 struct cell (wrong internal error instead of the public refusal) |
| M-26 | S5: the type walker follows `pa.ExtensionType` instead of `pa.BaseExtensionType` | AT-V4 `opaque` and `fixed_shape_tensor` cases |
| M-27 | S5: the date leaf test is `pa.types.is_temporal`, so `time64` counts as a date | AT-V4 `time64` and `duration` pass cases |
| M-28 | Retired in revision 5 (no repair) | |
| M-29 | Retired in revision 5 (the bare-statement rule is removed; a dropped result is correct for a pure check) | |
| M-30 | Retired in revision 5 (no buffer ownership) | |
| M-31 | Retired in revision 5 (no S5 pandas conversion) | |
| M-32 | Move the resident ISO schema gate below IPC admission | AT-V3 nested dictionary and dictionary-of-extension precedence |
| M-33 | Remove the schema gate at profile-helper entry | AT-V3 empty cloud/local parity (cloud returns a frame) |
| M-34 | Gate the full footer for projected reads; separately skip projection gating when there are zero row groups/rows | AT-V3 id-only and nested-child success; empty events refusal at open (before requesting its iterator’s first batch) |
| M-35 | Moved to row DEP-FLOOR | |
| M-36 | Drop the resolved direct-caller check for unchecked raw-Arrow helpers while retaining the finite sink set | AT-V8 seed 4, including its import alias |
| M-37 | Replace the child manifest table name with the default on load | AT-V7 manifest round-trip read before pipeline rebinding |
| M-38 | S5: `<=` becomes `<` at a bound (each of `lo` and `hi`, per unit) | AT-V12 bound rows, AT-V13 |
| M-39 | S5: the `ns` bounds are left untested (`None`), as on the branch | AT-V12 `INT64_MIN` and zoned `ns` rows, F2, F5 |
| M-40 | S5: the local wall-time test is skipped | AT-V12 zoned band rows, F4 |
| M-41 | S5: the zone offset sign is flipped | AT-V12 New York and Kolkata rows, AT-V13 |
| M-42 | S5: the band margin `M` is 0 | AT-V13 band draws, AT-V12 Kiritimati rows |
| M-43 | S5: only referenced dictionary entries are tested | AT-V12 unused-entry rows, AT-V14, F2 |
| M-44 | S5: only the first chunk's dictionary is tested | AT-V14 different-dictionary chunks |
| M-45 | S5: the check returns a rebuilt table | AT-V15 |
| M-46 | S5: remove the check from one chunked entry (`run_mask_chunked`, then separately `run_mask_pipeline_chunked`) | AT-V16 NCH or CH, AT-V8 |
| M-47 | S5: skip `check_resident_sources` in `PandasExecutionAdapter.run` | AT-V16 PAN |
| M-48 | S5: add a second check that raises `SourceDateUnrepresentableError` in `internal/pandas_compat.py` | AT-V18 decision-site rule |
| M-49 | S5: reintroduce a dataset scanner for whole-file reads | AT-V17 Hive key type |
| M-50 | S5: route admitted date dictionaries through a custom pandas conversion | AT-V19 |
| M-51 | S5: raise `_STOP_AT` by one above the measured count | the `sentry-limits` ratchet test |
| M-52 | S5: inline the measured literal again in place of `_STOP_AT` | AT-V18 and the bound census |
| M-53 | S5: compute the band offset with `zoneinfo.ZoneInfo(zone)` instead of pyarrow's resolver | AT-V12 Sydney and Auckland rows, AT-V13, AT-V20, F8 |
| M-54 | S5: admit a dictionary with a null entry | AT-V12 null-entry rows, AT-V20, F9 |
| M-55 | S5: decode dictionary rows (`cast` to the value type) on the pass path | AT-V15 allocation assertion, AT-V9 |
| M-56 | S5: drop `arrow_to_series` from the read sentry's sink set | AT-V8 seed 5 and the sink census in AT-V18 |


## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with `replaced_by=None` (allowed by `reasons/_registry.py:202-209`, section 4.3): `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
- New reason `runtime/source_date_unrepresentable` (`since=UNRELEASED`, S5a), kept beside #799's `runtime/source_column_unrepresentable` for the reasons in section 4.4b. Its summary and remediation name the calendar years, the `ns` limit, the zoned local-time test and the dictionary remedy. Both messages build their table and column phrase from one helper, `source_location_text` in `_execution_error.py`.
- Subject to Q8, the S5a changelog lists the accepted inputs that would now fail. On converting routes these include
  out-of-calendar non-ns timestamp dictionary entries (row 5), unused zoned ns edge entries (row 7) and local times
  outside the Python calendar that pandas can read (row 11). On NCH passthrough, list far dates, bad dictionary
  entries including unused and null entries, and unknown zones such as `Factory` (rows 13 and 14). Include zoned ns
  edges (row 8) and plain or UTC `INT64_MIN` ns (row 9) on NCH and on CH passthrough where main preserves them.
- Amend #799's `run_mask_chunked` and `run_mask_pipeline_chunked` paragraph in `docs/compatibility-contract.md` with
  the two date codes, their exception classes and the NCH narrowing specified in 4.7. Update the dispatcher's
  matching date examples and keep #830's detector paragraph.
- New reason `runtime/source_date_type_unsupported` (`since=UNRELEASED`, S5, section 4.4b) and public error class `SourceDateTypeUnsupportedError`. Behavior: a source column holding a date inside a selected container is refused under owner decision Q6 = A. A date dictionary with a non-holdable entry, used or not, is refused with `runtime/source_date_unrepresentable` (revision 5).
- Post-mask report: new per-column field `declared_sentinel_rows` (S6, additive).
- Config and snapshot: S7 admits preserve_values on date generators. Store optional stats.sentinels beside year_bins within distribution-snapshot/v2. Only bucket entry models forbid extra fields (contracts/distribution_snapshot.py:47,58,68). Existing v2 readers ignore the new field and emit no sentinel from it. An all-sentinel fit has no ordinary distribution for an older reader to sample. Round-trip old and new snapshots, exercise the pre-S7 reader, and run the full engine suite for this writer change.
- Config: `preserve_values` becomes valid on `windowed_date` (S3, additive). No other config key changes.
- Behavior: far dates that were `format_error` row errors become refusals; typed edge sentinels that were shifted become refusals. Logical output for in-range and declared rows is unchanged (AT-R1, AT-R2 digests against base). S5 leaves every admitted input and its pandas conversion byte-for-byte as main has them (AT-V15, AT-V19). For refused inputs, the comparison table distinguishes earlier coded refusals, conversion or scalar-read failures, silent `NaT` and inputs main returned successfully. The last group is the narrowing under Q8.
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
| 11 No raised caps | yes | no module-size ceiling is raised; S5a adds one bound row, `_STOP_AT`, pinned at its measured count (section 4.4b), not with headroom; `transforms/` fan-out stays at its limit (no new module) |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the refusal message is built from table, column, strategy and a count only, raised with no context; S5a prevents the zoned ns scalar-read leak and keeps #799's coded profile refusal value-free. S5b prevents the sampler date leak | AT-R10, AT-V1, AT-V2 | M-5, M-18 |
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

- Returned tables and published files: unchanged logical values for in-range and declared rows, with owned date buffers on Arrow return; no table on refusal.
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
| S5b | engine | Shared fitted distribution admission with the existing generation code (row L, AT-V2), the calendar day-number constants, `contracts/calendar_range.py`, docs line, changelog fragment; ported from `a5da43ef9` (section 4.4b) | nothing | R2 | T1 plus the T2 gate set |
| S5a | engine | Checked Arrow ingestion: the Q6 = A type gate, the holdable rule over plain cells and every dictionary entry, a pure check that returns its input, lazy-source binding to the mapping key, entry wiring, the read sentry with main's conversion sinks, `_STOP_AT` measured and registered, and the decision-site rule, bottom-tier source errors and adapter rows (AT-V1, AT-V3 to AT-V5, AT-V7 to AT-V9, AT-V12 to AT-V20), user and reason docs, changelog naming the narrowed set. Fresh branch from `origin/main` `395c1c662` or later; S5 hunks re-applied onto main's files, never whole-file checkout of a file #799 changed (section 4.4b) | S5b; merge after the owner answers Q8 | R2 | T1 plus full suite and layer checks (reason registry, new reasons) |
| S1 | engine | `DateDomain`, bound `DatePartition`, `DateRangeError` and its `_CODED` row, range table, new reason, the required `partition` on six primitives and the 15 call sites, the internal native range invariant, OOC typed path through `apply_bucket_perturb_dates`, removal of the native decline and abort, deprecation of the native range reason, sentry, AT-R1 to AT-R12 and AT-C1 to AT-C3, section 6.9 test updates, user docs for the S1 behavior (section 4.7), changelog fragment | S5b (shared ns bounds) | R2 | T1 plus the full engine suite (reason registry, frozen behavior) |
| S2 | engine | `group_by` with `preserve_values` on the Python path, two deprecations (`replaced_by=None`), AT-G1 to AT-G3, docs paragraph, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S3 | engine | `preserve_values` on `windowed_date` anchors, derived cell holds the anchor's sentinel (Q2), the anchor range on the shared code, deprecation, AT-W1 to AT-W3, docs, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S4 | engine | text_mask edge overflow becomes the token (Q5), AT-T1, docs sentence, changelog fragment | nothing | R1 | T1 |
| S6 | engine | post-mask sentinel exclusion and `declared_sentinel_rows` per column, AT-P1 to AT-P4, docs, changelog fragment | S1, S3 (derived anchors) and PM-1 (#784) merged | R2 | T1 plus the T2 gate set |
| S7 | engine | date generation: per-column fit kwarg, policy-aware snapshot writer and sentinel counts, matching generation declaration, admission (`_window_admission.py:128-170`, `:290-320`) and sampler (`_sample.py:493`, `_degenerate.py:122`) emitting sentinels at their rate (Q3), calendar-date stats in `_datetime_stats` and `_distribution_date`, AT-F1 to AT-F4, docs, changelog fragment | S1, S3 and S5 | R2 | T1, T2 and full engine suite (snapshot writer) |
| S8 | CLI | Wire the per-column exact-fit option through fit_exact_snapshot, test CSV fit through generation, update command help, user guide and changelog | S7 engine API released and available to CLI | R2 | CLI suite and installed CLI/engine integration |
| ASSEMBLER-LABELS | engine | Map source-backed pandas display labels to physical Arrow fields by position in the passthrough assembler (`execution/pipeline/_source_types.py:129,156`); tests with integer, tuple and duplicate-looking labels on FF. Pre-existing, found in S5 round 6 | nothing | R2 | T1 |
| DEP-FLOOR | engine | Make the engine import at its declared floors: optional list-view predicates (`safe_output/_file_metadata.py:60-61`) and the pandas 1.5.3 failure at `validators/_dates.py:13`; AT-V11 and M-35 move here; exact-version CI legs. Pre-existing | owner answer on the pandas floor (section 15) | R2 | T1 plus the floor legs |

Each row is one PR. S4, S5b, ASSEMBLER-LABELS and DEP-FLOOR can start independently. S5a follows S5b (shared calendar constants). S1 follows S5b for the shared ns bounds. S2 and S3 follow S1. S6 follows S3 and PM-1. S7 follows S3, S5a and S5b with S1 already merged. S8 follows the S7 engine release.

## 15. Owner decisions (product choices)

The owner accepted the recommendations for Q1 to Q5 on 2026-11-27 and chose A for Q6 on 2026-11-28. Q7 and Q8 remain open.

- Q1, typed date columns. Decided: typed `date` columns (Parquet, database `DATE`) keep the 0001 to 9999 domain, less the strategy's reach. `9999-12-31` and `0001-01-01` are refused on the usual windows unless declared, and genuine historic dates such as `1600-01-01` still mask. Text and zoned timestamps use the pandas domain.
- Q2, windowed_date with a declared sentinel anchor. Decided: the derived cell holds the anchor's sentinel value, so "unknown admission" gives "unknown discharge". Never the source value of the derived column.
- Q3, generation. Decided: a declared sentinel is excluded from the fitted range and emitted at its observed rate, so downstream `= 9999-12-31` logic keeps working.
- Q4, quarantine. Decided: an undeclared far date refuses the run even when `format_error` quarantine is on. The remedy is to declare the sentinel.
- Q5, text_mask date spans at the calendar edge. This departs from the owner rule (a coded refusal), so it is a product call. Decided: the span becomes the redaction token, as an unparseable span already does. Free text holds dates the user never declared, one edge date in a note should not stop a run, and the token writes no source value (fail-closed). The other option was the coded refusal.

- Q6, date columns inside containers (section 4.4b). Decided: (A), as given in the S5 redesign brief on 2026-11-28. A column holding a date inside a list, large list, fixed-size list, map or struct is refused by type even when every date is inside the calendar; full support is follow-up G-8. The options considered were (A) refuse for V1, (B) build G-8 inside S5, and (C) refuse only caller-supplied Arrow. List view, run-end-encoded, union, extension and dictionary-of-struct columns never come from a Decoy file reader, so refusing them is a technical choice and not part of Q6.

- Q7, pandas floor (row DEP-FLOOR, not S5). Open. The engine does not import on pandas 1.5.3 today (`validators/_dates.py:13`), and the S5a holdable rule assumes pandas 2 keeps the source timestamp unit. Options: (A) raise the declared pandas floor to 2.x; (B) keep 1.5.3, fix the import and make the rule use the `ns` range on pandas 1.x. The planner recommends (A): main already fails on 1.5.3, so no working user is lost, and one rule stays one rule. S5a does not wait on this answer.

- Q8, inputs main accepted that S5a would refuse. Open for the owner. On converting routes, these include an
  out-of-calendar non-ns timestamp dictionary entry, an unused bad zoned ns entry, and a zoned local time in year
  10000 that pandas reads (comparison rows 5, 7 and 11). On NCH passthrough they include the dates and dictionary
  entries in row 13 and the unknown zone in row 14. In particular, main can return zoned ns edges (row 8) and
  `INT64_MIN` ns (row 9) exactly on NCH and on CH passthrough. Should S5a refuse these inputs?
  - (A) Apply the same holdable rule to every route. All routes refuse these inputs before a later scalar read can fail.
  - (B) Preserve main's successful reads and passthroughs. Refuse cells on converting routes that fail pandas conversion or
    pandas scalar access or silently become `NaT`. The same input can then succeed on one route and fail on another.
    A year-10000 local time that pandas reads can still fail a later Python `as_py` call.
  - The planner recommends A. S5a can start on that assumption. Merge waits for the owner's answer.

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

### 17.1 Review of section 4.4b

This review covers the revision 4 text of section 4.4b (items 1 to 7, repair and buffer ownership). Revision 5 replaces that text; the rows below are history. Section 17.2 records the redesign.

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
| L1 M-25 cites AT-V5 | round 1 cited AT-V3 and AT-V9; the later Codex entry below corrects the kill attribution |
| L2 wrong error home in 4.5 | row points at `io/bounded_reader.py:106` and `reason_adapter.py:57` |
| L3 `_part3.py` missing from the size list | listed at 573 lines with a 600-line limit; no new census row |
| L4 which kind is reported | the outermost kind |
| L5 binding precondition | `is_dataclass` and a `table` field |
| Not verified: pyarrow 14 walker | probed on 14.0.2 (4.4b item 2) |
| Not verified: ISO, SEQ and isolated-dispatch binding | traced in 4.4b "Where the binding runs" |

#### Codex review of `5e65076c6` against `2fab8cb9f`

Dennis’s two GO reviews and the decisions above stand. Q6 remains open with A as the written default.
Round-two cases 1–4 and 6 close at type admission. Case 5 also needs the pandas working representation. Case 7 uses the bound mapping key. The following entries cover the remaining contract, wiring and fixture changes.

| Class | Finding | Fix and distinguishing evidence |
|---|---|---|
| V1 | Excluded date bytes survive an Arrow return | §4.4b item 5 owns the final logical buffers including nulls, padding and dictionary storage. AT-V10 reopens IPC from both public APIs; M-30. |
| V1 | Arrow dictionary repair still fails pandas jobs | Item 6 derives a signed, null-safe working categorical from each checked dictionary, including no-FAR input. AT-V6 exercises FF and CH; M-31. |
| V1 | ISO IPC admission wins before the source gate | Gate resident schemas by key in the parent before staging. AT-V3 compares exact refusals in both isolation modes; M-32. |
| V1 | Empty cloud sample bypasses admission | Gate the supplied schema before profile iteration. AT-V3 drives the range reader with zero rows; M-33. |
| V1 | Whole-footer gating rejects valid projected reads | Gate the selected schema from the open file; return complete footer facts. AT-V3 includes populated and empty projections; M-34. |
| V1 | Engine import fails on supported Arrow 14 | Item 7 conditions optional rebuilders. AT-V11 starts the installed engine on 14 before checked reads; M-35. |
| DESIGN | A new caller can forward raw input to an unchecked conversion helper | Pin qualified direct callers of the listed raw-Arrow helpers. AT-V8 seed 4 exercises the existing profile forwarder; M-36. |
| V2-LOG | Plan document falls in the 800–900-line cleanup band | Log for V2. Production sizes and unchanged ceilings are in §4.4b. |
| V2-LOG | Wrong lower-end zone | AT-V6 uses Kiritimati for both outward crossings and Adak for both inward controls. |
| V2-LOG | ISO and CSV used as lazy Parquet fixtures | AT-V7 checks manifest transport (M-37) and the CSV bound copy; M-23 exercises lazy run routes. |
| V2-LOG | Width-only M-28 survives the row assertions | AT-V6 inspects the intermediate int64 remap; test the null-fill mutant separately. |
| V2-LOG | M-25 misattributes the kill to AT-V9 | AT-V3 kills the gate-only struct mutant. AT-V9 independently calls the counter with a list. |
| V2-LOG | Forwarding seed lacks required arguments | AT-V8 seed 2 supplies `columns=()`; seed 4 supplies `table_name="t"`. |

Own plan review: **GO under Q6(A)**. The tests and mutations specify the builder’s required evidence. During this plan revision, direct probes on 14.0.2 and 24.0.0 confirmed the excluded word in reopened IPC and the zero-row-group projection for populated and empty files, including a selected struct child. The reference engine import reproduced the missing predicate on 14.0.2. Run each mutation independently on the final implementation head, record its failing assertion, revert and verify green. The plan review does not certify an implementation.

## 17.2 S5 build review rounds 3 to 6 (revision 5)

The S5 build (PR #839, `feat/date-range-s5`, head `a5da43ef9`) went through Codex rounds 3 to 6 without a GO. Section
4.4b records the finding classes. The plan response is the redesign in section 4.4b: S5 refuses and never rewrites,
one pure check judges every source date, reads stay main's reads, and the pre-existing findings move to rows
ASSEMBLER-LABELS and DEP-FLOOR. The round 6 DESIGN finding (the inline `<= 40` stop in the read sentry) is kept as
`_STOP_AT = 40`, registered in the bound registry at its current value. The fitted distribution admission (S5b) had no
open finding after round 6 and is ported as it is.

## 17.3 Dennis plan review round 1 of revision 5 (revision 6)

Dennis reviewed `15ff9e33f` (`~/scratch/dennis-s5-plan-r1.md`): GO-WITH-FIXES, 0 BLOCKER, 2 HIGH, 4 MEDIUM, 3 LOW. Fixes in revision 6:

| Finding | Fix |
|---|---|
| H1 zone test modelled `zoneinfo`; pandas 2 converts with `pytz` | band offsets from pyarrow's own resolver (`string_to_tzinfo`), the tzinfo pandas and `as_py` receive; probe found 0 disagreements with real conversion in 14,448 band values; AT-V13 oracle is the real conversion; Sydney, Auckland, Berlin, New York and `Factory` rows in AT-V12; M-53; pandas 3 note |
| H2 plan predated #799 | re-anchored to `d1d7453ac`; port by re-applying S5 hunks onto main, never whole-file checkout of the 15 files #799 also changed; read sentry sinks rebuilt from main's `arrow_to_*` helpers; builder-report grep for added conversions; `_STOP_AT` measured, not assumed |
| M1 regression claim measured against raw `to_pandas` | comparison table rebuilt against main's `arrow_to_frame`; narrowed set named for the changelog; red-first labels corrected; the narrowing put to the owner as Q8 |
| M2 second reason beside `source_column_unrepresentable` | kept with stated reasons (different value set, remedy and count); shared location wording helper; summary covers `ns` and zone limits |
| M3 no admitted-implies-converts test; G-13 undecided | AT-V20 property through main's `arrow_to_frame`, `iloc`, categories and `as_py`; G-13 decided: a null entry refuses the column |
| M4 no route-by-fixture table | route-by-fixture table and asserted count, with dictionary fixtures n/a on Parquet routes. Revision 7 adds lazy SEQ and native OOC and counts both layouts explicitly |
| L1 `_STOP_AT` headroom; class 11 text | pinned at the measured count; class 11 text corrected |
| L2 memory | pass path tests dictionary entries only and never decodes rows; AT-V15 allocation bound; M-55 |
| L3 stale anchors; `test_signed_evidence_file_access.py` unplaced | cloud anchors `:272`, `:394`; the file is discarded (its count change followed `read_table_gated`) |

## 18. Follow-ups (not in this row)

- G-2: compute text dates on the Python calendar after the pandas parse, which would widen the text domain to the typed one.
- G-3: shuffle over `timestamp[ns]` returns `timestamp[us]` on full_frame.
- G-4: CLI hint for `date_outside_strategy_range`, and `decoy scan` suggesting `preserve_values` from the pre-scan sentinel flags.
- G-5: compile check order differs between the chunked and full-frame paths for a naive timestamp with `preserve_values`.
- G-7: CLI test for `--chunked` CSV staging with a refusing far date (CLI repo).
- G-8: full support for dates inside list, map, struct, list view, run-end-encoded and dictionary-of-struct columns (section 4.4b); the owner picked Q6 (A). Needs the output-type decision first.
- G-11: dropped in revision 5 (the bare-statement rule is removed because the check is pure).
- G-12 (V2-LOG): hidden storage outside a slice is serialized when a caller writes a returned passthrough table to IPC (all types; the caller's own data).
- G-13: decided in revision 6 (S5a refuses a date dictionary with a null entry on every route); no follow-up.
- G-14: a Parquet file Arrow cannot decode (null parent in `fixed_size_list<date32>`) fails with Arrow's error before the type refusal (pre-existing).
- G-15: the resident profile fallback rebuild drops a stored index (pre-existing, S5 round 5).
- Structure review list: one resolver for the stored index (`execution/pipeline/_source_types.py:45` and `_pandas_meta/_columns.py:26`).
- G-6: relationship validators read a far output date as unparsed (`validators/_dates.py:71-80`); confirm sentinel rows are skipped, not counted as violations.

VERDICT: GO
