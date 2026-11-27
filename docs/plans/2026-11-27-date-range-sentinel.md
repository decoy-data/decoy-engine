Status: plan

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 1. Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Anchors are in this repository (decoy-engine) at `origin/main` `f54ad388b` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one new reason code, three deprecations, a config key on one more strategy), `catalogs/recurring-defects.md` (11 classes), `cross-cutting-concerns.md` (one rule, many routes), `testing.md` (test depth T0 to T4). Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`, deprecation with `replaced_by`).

Risk: R2. It changes what a date strategy does with a far date on every route, adds a reason code and deprecates three, and turns a quarantinable row error into a refusal. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S1, S2, S3, S6 and S7; Codex only for S4. Full suite before merge: S1 and S3 yes (reason registry trigger); the other slices by their own triggers (section 14).

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
| M | quality snapshot `_datetime_stats` over object `datetime.date` values with `9999-12-31` | profiling | silently drops the far value from min, max and year bins (`utc_naive_datetimes`, `pandas_compat.py:84-93`, coerces it to NaT and drops it) |
| N | passthrough, hash, redact, shuffle over far `date32`, `timestamp[us]`, `timestamp[us, tz]` | all routes | correct (no date arithmetic; pandas 2 keeps the source unit). Not in scope |
| O | any strategy, `date32` year 10183 | every route but native chunked | uncoded `ValueError: year 10183 is out of range` from the profile sampler (`profile/_readers.py:499`) quoting the year. Not a strategy range; follow-up G-1 |
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
4. A refusal is not a row error: quarantine does not absorb it (owner question Q4). No target is published (the existing transactional publication aborts).
5. Null cells pass through as today. Rows a `when:` gate does not select are not computed and are not checked.

Non-goals: widening the text path to the Python calendar (follow-up G-2); dates beyond year 9999 in Arrow (G-1); any change to value-agnostic strategies (row N); a CLI hint that suggests `preserve_values` from pre-scan sentinel flags (G-4).

Size: S1 is about 250 source lines over 13 source files plus about 400 test lines; the other slices are 40 to 150 source lines each.

### 4.2 Design

The input range is the compute domain of the primitive, less the reach of the strategy's arithmetic. All values are whole calendar days, held as `datetime.date` (Python years 1 to 9999), so no bound needs `datetime64[ns]`.

| Strategy | Shape | Domain | Reach (days taken off each side) |
|---|---|---|---|
| date_shift | text, `timestamp_tz` | 1677-09-22 to 2262-04-10 (whole days inside the pandas ns range); `timestamp_tz` one more day on each side for the zone offset | low side `max(0, -min_days)`, high side `max(0, max_days)` |
| date_shift | `date` | 0001-01-01 to 9999-12-31 | same as above |
| bucket_perturb | text | 1677-09-22 to 2262-04-10 | the existing `_BUCKET_REACH_DAYS` for the bucket, both sides |
| bucket_perturb | `date` | 0001-01-01 to 9999-12-31 | same |
| windowed_date (S3) | anchor, any shape | 1700-01-01 to 2200-12-31 (existing `SUPPORTED_MIN`/`SUPPORTED_MAX`) | none on the anchor; the existing offset check stays |

Reach comes from the config, never from the keyed offset, so the refusal set is the same for every key (fixes E). With the usual windows the edge sentinels are refused on the typed path too: `9999-12-31` under `max_days > 0` or any bucket, `0001-01-01` under `min_days < 0` or any bucket. Genuine historic typed dates (`1600-01-01`) keep computing, as COLUMN-SHAPE E1b intended (`test_date_shift_typed_edges.py:74`). This reading of the owner decision is Q1.

A text cell is "out of range" when pandas cannot hold it but `datetime.strptime` under the same `date_format` parses it, or when it parses inside pandas and falls outside the range. The strptime retry is the one `PreserveSet._strptime_date` already does (`date_preserve.py:198-204`). A cell neither parser accepts stays a `format_error`, as today.

One object carries both declarations. `preserve_set_from_config` (`date_preserve.py:226`) becomes `date_domain_from_config(cfg, *, strategy, shape)` and returns a `DateDomain` (the `PreserveSet` fields plus the range) for every column of these strategies, with or without `preserve_values`. `DateDomain.partition(values, *, table, column)` returns a `DatePartition` (the sentinel mask and the rows to compute) or raises `DateRangeError`. Sentinels are matched first, then the range is checked on the rest, so a declared far sentinel is never counted.

Enforcement by construction: each compute primitive takes a required `partition: DatePartition` argument in place of today's optional `preserved` mask, and computes only `partition.compute_rows`. The primitives are `_shift_rows` and `_shift_dates` (`_date_shift.py:366`, `:402`), `native_date_shift` (`_date_shift_ext.py:147`), `native_bucket_perturb` (`_bucket_perturb_ext.py:213`), and `apply_bucket_perturb` / `apply_bucket_perturb_dates` (`bucket_perturb.py:183`, `:245`). `DatePartition` has no public constructor: only `DateDomain.partition` builds it (a module-private token in its `__init__`). A route that skips the check cannot call a primitive.

Call sites that build the domain today and must partition instead (all in S1): `_date_shift.py:159`, `:251`; `_bucket_perturb.py:70`, `:181`; `_sequential_native.py:395`, `:540`; `native/_operator_step.py:279`, `:459`, `:488`; `native/_operator_params.py:282`, `:299`; `out_of_core/_bucket_native.py:185`, `:263`; `out_of_core/_mask_group_c.py:452`; `date_preserve.py:256` (`apply_excluding_preserved`).

Removed as unreachable: `native_range_exceeded` (`_bucket_perturb_ext.py:91`), its decline at `_sequential_native.py:398` and the abort at `_bucket_native.py:216-229`. A near-bound date is now refused by the partition before any kernel runs, on both backends. The out-of-core typed path (H) calls `apply_bucket_perturb_dates`, the same primitive the handler uses.

`preserve_values` stays the one declaration (no rename). It already ships on two strategies, its literals are already held as `datetime.date` (`date_preserve.py:134-138`, `:240`), and `date.fromisoformat` already refuses years 0 and above 9999. S3 adds it to `windowed_date`. Config validation stays at plan compile (`plan/_checks_date_shift.py:376`) and in the handler preflights, one rule (`preserve_config_problem`, `date_preserve.py:84`).

Relation to `sentinel_to_null` (F06 declared casting, `config/_tables.py:146`, `contracts/declared_casting.py:55`). The two are kept apart on purpose, because they give different outputs:

- `sentinel_to_null` is a parse-time declaration on a declared-casting column: exact raw tokens, any logical type, matched before parsing, and the cell becomes null.
- `preserve_values` is a strategy-time declaration on a date strategy: calendar dates, and the cell comes out unchanged.

Casting runs first. A token that `sentinel_to_null` turns into null reaches the strategy as null and passes through as null; `preserve_values` never sees it. A column may declare both (for example `"0000-00-00"` to null, `9999-12-31` to keep). No overlap refusal is added: an entry in both is harmless (casting wins) and the docs say so. Merging them would either null a sentinel the user wants kept or keep a token the user wants nulled.

### 4.3 Group_by and other existing conflicts

- `preserve_values` with `group_by` is refused today (`_date_shift.py:167-178`, `plan/_checks_date_shift.py:403-412`). After S1 a group_by user with a `9999-12-31` row has no way to run, so S2 supports the pair: the handler passes `anchor_col.iloc[partition.compute_rows]` to `_shift_rows` (positional, the same index-identity check stays on the full frame first). Native already declines `group_by`, so S2 touches the Python path only. The two `date_preserve_values_with_group_by_unsupported` reasons (plan and runtime) are deprecated with no replacement code.
- `preserve_values` on a child FK key stays refused (`date_preserve_values_unsupported_fk_shape`); a far date on a parent key is partitioned on the parent and the child remaps through it as today.
- `%f`, `%Z`, `ISO8601` and `mixed` formats stay refused with `preserve_values` (`date_preserve.py:113-130`). The range check itself works for any explicit format; a cell strptime cannot read stays a `format_error`.
- A naive timestamp column stays a shape mismatch for both strategies (unchanged).
- Check order differs today between the chunked and full-frame compile paths (probe: chunked reports `preserve_values_invalid` before `column_shape_mismatch` on a naive timestamp). Not changed here; follow-up G-5.

### 4.4 Choke points

- Rule: no date compute primitive runs on a row the domain has not cleared. Enforced by the required `partition` argument and the private constructor.
- Guard: `tests/sentry/test_date_partition_choke_point.py` (new). It walks `src/decoy_engine` with `ast`, finds every function in the primitive list above, asserts each has a required, keyword-only `partition` parameter with no default, and asserts `DatePartition(` is constructed only inside `transforms/date_preserve.py`. It also asserts that every module that calls `pd.to_datetime` on a strategy input is either in the primitive list or on an explicit allowlist with a reason (the validators, profiling, generation, windowed_date).
- Mutation that must turn the guard red: give `native_bucket_perturb`'s `partition` a default of `None` (M-4).

### 4.5 Placement

| Item | Place | Why |
|---|---|---|
| `DateDomain`, `DatePartition`, `DateRangeError`, range table | `transforms/date_preserve.py` (275 lines today, about 400 after) | `transforms/` is at its fan-out limit (CODEMAP "Transforms" row); the matching code it extends is already here |
| New reason | `reasons/runtime/_part3.py`, new `_catalog.runtime("DateRangeError")` binding | runtime reason home; `_part3.py` is 553 lines |
| Sentry | `tests/sentry/test_date_partition_choke_point.py` | beside the other choke-point sentries |
| Route matrix | `tests/parity/test_date_range_sentinel.py` | beside the D1c suites, reusing `_d1c_data.py` |
| Domain unit tests | `tests/unit/transforms/test_date_domain.py` | per-module unit home |

### 4.6 Design notes

- One place per fact: the range table and reach rule are in `date_preserve.py` only; the native and out-of-core code read them from the `DatePartition`, never restate them.
- Typed proof object (parse, do not validate): the partition is the evidence the check ran, so the rule holds by construction instead of by a helper each site must remember.
- No flag arguments: the domain is resolved from `(strategy, shape, cfg)`; there is no "skip range" switch.
- Value-free errors: the `WindowedDateError` pattern (`windowed_date.py:84-100`), raised outside any `except` so `__cause__` and `__context__` stay empty.

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
| text_mask span at the calendar edge (S4) | uncoded `OverflowError` | the redaction token, as for an unparseable span |

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
| AT-R4 | text, tz | undeclared `2262-04-10` with window -30..30; run under two different mask keys | refusal under both keys | red: E |
| AT-R5 | `date32` | undeclared `1600-01-01` | masked (inside the typed domain) | green on base |
| AT-R6 | text | `"not-a-date"` and `""` | `format_error` row error, as today | green on base |
| AT-R7 | text with a CSV file target | undeclared far date in the third chunk | refusal; the target file does not exist after the run; the run result has no outputs | red (format_error today) |
| AT-R8 | text | undeclared far date in a row a `when:` gate does not select | run succeeds, the row is the source value | green on base |
| AT-R9 | text | undeclared far date, quarantine enabled for `format_error` | refusal; nothing quarantined | red |
| AT-R10 | all | undeclared far date seeded with a marker value | no marker in `str(exc)`, `repr(exc)`, the run log and the evidence; `__cause__` and `__context__` are None | red (no such error) |
| AT-R11 | text | the reach edges: for date_shift `min_days=-5, max_days=7`, cells at hi, hi+1 day, lo, lo-1 day | hi and lo masked, the two outside refused | red at lo and hi edge (E) |
| AT-R12 | text, bucket month | cells one bucket inside each pandas bound and one day further | inside masked, further refused, on Python and native OOC alike | red (I) |

Parity check (part of AT-R1, AT-R2): for every route pair the output table digest (`tests/parity/_d1c_data.table_digest`) is equal, and for AT-R3 and AT-R4 the error code, table and column are equal. The count is compared on FF, AUTO, SEQ and ISO, where the batch is the whole column; on CH, NCH and OOC it is the count of the refusing batch.

### 6.2 Config (S1)

- AT-C1: `preserve_values=["9999-12-31"]` resolves to `DateDomain.sentinels == frozenset({date(9999, 12, 31)})`, a `datetime.date`, never a `datetime64`. Green on base for the existing set.
- AT-C2: `"0000-01-01"`, `"10000-01-01"`, `"9999-13-01"` and `"2024-02-30"` are refused at plan compile with `date_shift_preserve_values_invalid` / `bucket_perturb_preserve_values_invalid`, path ending `.preserve_values`. Green on base.
- AT-C3: the range table is a pure function of `(strategy, shape, min_days, max_days, bucket)`: a property test over random windows checks `lo <= hi` or a compile refusal when the window leaves no computable day.

### 6.3 Group_by (S2)

- AT-G1: date_shift with `group_by="patient_id"` and `preserve_values=["9999-12-31"]` on FF and SEQ: sentinel rows unchanged; every non-sentinel row of one patient shifts by the same offset as an unconfigured group_by run on the non-sentinel rows only. Red on base (compile refusal).
- AT-G2: the same with an undeclared far date: refusal. Red on base (compile refusal).
- AT-G3: a misaligned anchor snapshot still fails closed with `date_shift_group_anchor_snapshot_misaligned`. Green on base.

### 6.4 windowed_date (S3, after Q2)

- AT-W1: an anchor `9999-12-31` declared in `preserve_values`: the output cell is the Q2 answer; the row is counted. Red on base.
- AT-W2: an undeclared far anchor: `date_outside_strategy_range`. Red on base (old code).
- AT-W3: the offset check stays `windowed_date_offset_out_of_range`. Green on base.

### 6.5 text_mask (S4)

- AT-T1: spans `9999-12-31`, `12/31/9999` with a positive window and `0001-01-01` with a negative one come back as the token; the rest of the cell is masked as before. Red on base (OverflowError).

### 6.6 Post-mask check (S6, after PM-1)

- AT-P1: a date_shift column with declared `9999-12-31` rows that a date detector hits through its column name: the residual-PII grade counts the sentinel rows as neither comparable nor identical, so 100 percent sentinel rows do not grade `fail`. Red on base.
- AT-P2: the same column with one non-sentinel row left unchanged by a fault injection still grades `fail` (the exclusion does not hide a real leak).
- AT-P3: `timestamp[us]` and `date32` far dates in source and output are read without an exception (PM-1 owns the cell walk; this test only runs the runner end to end).

### 6.7 Generation (S7, after Q3)

- AT-F1: a distribution-fitted date column whose source holds undeclared `9999-12-31`: `date_outside_strategy_range` at fit, value-free. Red on base (L).
- AT-F2: the same with the sentinel declared: the fit excludes it and the output follows Q3. Red on base.
- AT-F3: `_datetime_stats` over object dates no longer drops a far value silently: either it counts it or the declared sentinel path removes it explicitly (M). Red on base.

### 6.8 Existing tests whose expectation changes

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
| M-11 | S2: anchor passed unsliced to the sub-run | AT-G1 |
| M-12 | S6: exclusion applied to every identical row, not only sentinel rows | AT-P2 |

## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with no replacement: `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
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
| 4 Versioned read models | no | no persisted format added |
| 5 Normalized guard scanners | yes | the new sentry walks the AST, not text, and resolves aliased imports |
| 6 No reaching into private modules | yes | native and out-of-core import `DateDomain` from `transforms.date_preserve`, which is already imported there |
| 7 No hidden CI failures | no | no CI step changes |
| 8 One input, one trust class per entry point | no | no user-chosen name or path |
| 9 Mutations on the final head | yes | section 7 |
| 10 Allowlisted helpers are still checked | yes | the sentry's `pd.to_datetime` allowlist names module and function with a reason each |
| 11 No raised caps | yes | module-size ceilings move only by the lines added; `transforms/` fan-out stays at its limit (no new module) |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the refusal message is built from table, column, strategy and a count only, raised with no context | AT-R10 seeded-marker check on message, log and evidence | M-5 |
| 2 | Cleanup missing on an exit path | the refusal raises inside the strategy call, so the existing transactional sink abort and isolated work-root cleanup run as for any coded refusal | AT-R7 (no target file, no outputs) | M-7 |
| 3 | State machine and concurrency | N/A: the partition is a pure function per batch; no shared state is added | AT-C3 property test | N/A: no state transition added |
| 4 | Route parity and silent fallback | one `DateDomain` per column and a required `DatePartition` on every compute primitive; the native range decline that sent near-bound text to Python is removed | AT-R1 to AT-R12 across section 10.2, the digest parity check, the sentry | M-1, M-4, M-6, M-8 |
| 5 | Referential integrity | a far parent key is partitioned on the parent; child keys remap through it; child-side `preserve_values` stays refused | section 10.3, existing `test_phase_d_d1c_fk.py` green | M-3 |
| 6 | Untrusted producer | N/A: config is validated at compile as today; no new producer is read | AT-C2 | N/A: no new input channel |
| 7 | Check then use on a path (TOCTOU) | N/A: no file path is checked or opened by this change | none needed | N/A: no path handling |
| 8 | Weak tests and overclaimed evidence | every AT records red on `f54ad388b` or is marked green on base; section 6.8 lists every changed expectation; expected values never come from the output under test | builder report with base SHA and red output | each mutation names its test |
| 9 | Behavior-preserving refactor drift | the `preserved` mask becomes `partition.sentinels`; in-range and declared outputs keep their bytes | AT-R1, AT-R2 digests equal to base | M-3 |
| 10 | Frozen contract drift | section 8: one new code, deprecations with `replaced_by`, one additive config key | reason registry tests, `scripts/release/reason_release_pin.py --check` | M-7 |

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
| generation (S7) | `generators/_distribution.py:276`, `quality/snapshot.py:491` | n/a | n/a | L, M coded |

### 10.3 FK shapes

- Single, composite and multi-hop parent keys masked with date_shift or bucket_perturb: the parent column is partitioned once; children remap through the parent mapping (`test_phase_d_d1c_fk.py:99`), so a far parent key refuses before any child is written.
- Child key carrying `preserve_values`: stays a compile refusal (`date_preserve_values_unsupported_fk_shape`, `plan/_checks_date_shift.py:334-374`).
- Orphan child rows under `orphan_policy: preserve`: an orphan's own value goes through the parent handler (`test_phase_d_d1c_fk.py:115`), so it is partitioned the same way.
- Self-referencing and cross-table cycles: N/A: no FK walk changes; the partition is per column.

### 10.4 Fields

- `DateDomain`: `sentinels` (`frozenset[datetime.date]`), `date_format` (`str | None`), `low` and `high` (`datetime.date`), `strategy`, `shape`.
- `DatePartition`: `sentinels` (bool mask), `compute_rows` (int positions), `sentinel_count`.
- `DateRangeError`: `code`, `table`, `column`, `strategy`, `count`; message from these only.
- `date_preserve` metric: unchanged (`execution/_adapter.py:329-345`).

### 10.5 Output surfaces

- Returned tables and published files: unchanged bytes for in-range and declared rows; no table on refusal.
- Errors: the new coded refusal replaces `format_error` (far cells), `OverflowError` (near-bound shift), and two out-of-core codes.
- Row errors and quarantine: far cells no longer produce `format_error` rows.
- Logs: no new log line; the refusal is logged by the existing error path with the message above.
- Evidence and metrics: `date_preserve` counts unchanged; the out-of-core bucket disposition drops the native range reason.
- Post-mask report (S6): sentinel rows excluded from identity counts.
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

This row adds one input to the residual-PII identity count: for a column whose strategy has a `DateDomain`, `_add_identity` (`verification/postmask/_column_facts.py:235`) receives the source batch's sentinel mask from a matching-only call on the domain (no range check, since the run already refused far rows) and leaves those rows out of `comparable` and `identical`. The interface is that one mask: PM-1 decides whether two cells are equal; this row decides which rows were allowed to be equal. S6 merges after PM-1 and rebases on its `_column_facts.py`.

## 13. Pre-mortem

- A real date near a pandas bound in text is now refused (for example `2262-04-05` with `max_days=30`). Such dates are almost always placeholders; the message says to declare them. G-2 tracks widening the text path to the Python calendar if a customer needs it.
- A user relied on quarantine to divert sentinel rows. After S1 the run refuses instead (Q4). The changelog entry states it and names `preserve_values`.
- The sentry misses a new primitive added later. The `pd.to_datetime` allowlist check fails for any new module that parses strategy input without being in the primitive list.
- A typed source whose shape the plan cannot prove (`ColumnShape.UNKNOWN`) takes the text domain. That is the narrower one, so it fails closed.
- The partition adds a pass over each batch. It reuses the parse the strategy already does (the partition returns the parsed series to the primitive on the text path), so the extra cost is one comparison per row.
- S2 lands without S1. It cannot: S2's tests depend on the refusal. The After order in section 14 enforces it.

## 14. Slices and risk

| Slice | Repo | Content | After | Risk | Test depth |
|---|---|---|---|---|---|
| S1 | engine | `DateDomain`, `DatePartition`, `DateRangeError`, range table, new reason, the required `partition` on six primitives and the 15 call sites, OOC typed path through `apply_bucket_perturb_dates`, removal of `native_range_exceeded` and its decline and abort, deprecation of the native range reason, sentry, AT-R1 to AT-R12 and AT-C1 to AT-C3, section 6.8 test updates, changelog fragment, `docs/strategies.md` paragraph | nothing | R2 | T1 plus the full engine suite (reason registry, frozen behavior) |
| S2 | engine | `group_by` with `preserve_values` on the Python path, two deprecations, AT-G1 to AT-G3 | S1 | R2 | T1 plus full suite (reason registry) |
| S3 | engine | `preserve_values` on `windowed_date` anchors with the Q2 output, the anchor range on the shared code, deprecation, AT-W1 to AT-W3 | S1, and Q2 answered | R2 | T1 plus full suite (reason registry) |
| S4 | engine | text_mask edge overflow becomes the token, AT-T1 | nothing | R1 | T1 |
| S6 | engine | post-mask sentinel exclusion, AT-P1 to AT-P3 | S1 and PM-1 (#784) merged | R2 | T1 plus the T2 gate set |
| S7 | engine | generation fit: coded refusal for undeclared far dates, declared exclusion per Q3, AT-F1 to AT-F3 | S1, and Q3 answered | R2 | T1 plus the T2 gate set |

S1 is one PR because the guarantee is route parity: shipping the partition on some routes first would create the divergence this row removes. There is no S5: the year-beyond-9999 reader crash is G-1, a separate row.

## 15. Owner questions (product choices)

- Q1. Typed date columns (Parquet, database `DATE`) compute years 1 to 9999 today. Recommended: keep that domain (less the strategy's reach), so `9999-12-31` and `0001-01-01` are refused on the usual windows and genuine historic dates such as `1600-01-01` still mask. Alternative: one pandas range for every shape, which also refuses `1600-01-01` typed.
- Q2. windowed_date with a declared sentinel anchor: what does the derived cell hold? Recommended: the anchor's sentinel value, so "unknown admission" gives "unknown discharge". Alternative: null. Never the source value of the derived column, which would leak it.
- Q3. Generation: a declared sentinel in a fitted date column. Recommended: exclude it from the fitted range and emit it at its observed rate, so downstream `= 9999-12-31` logic keeps working. Alternative: exclude only (the output never holds the sentinel).
- Q4. Quarantine: recommended that an undeclared far date refuses the run even when `format_error` quarantine is on (the fix is to declare the sentinel). Alternative: a new quarantine trigger `date_out_of_range` that diverts those rows.

Technical choices taken (recommended option, no owner call needed): keep the name `preserve_values`; reach from config, not the key; refuse near-bound text dates on every route instead of computing them on some; keep `sentinel_to_null` separate with casting first; text_mask edge spans become the token (S4); no rename of the out-of-core disposition fields.

## 16. Follow-ups (not in this row)

- G-1: an Arrow `date32` beyond year 9999 crashes the profile sampler with an uncoded `ValueError` that quotes the year (`profile/_readers.py:499`, every route but native chunked). Needs a coded, value-free refusal at the reader.
- G-2: compute text dates on the Python calendar after the pandas parse, which would widen the text domain to the typed one.
- G-3: shuffle over `timestamp[ns]` returns `timestamp[us]` on full_frame.
- G-4: CLI hint for `date_outside_strategy_range`, and `decoy scan` suggesting `preserve_values` from the pre-scan sentinel flags.
- G-5: compile check order differs between the chunked and full-frame paths for a naive timestamp with `preserve_values`.
- G-6: relationship validators read a far output date as unparsed (`validators/_dates.py:71-80`); confirm sentinel rows are skipped, not counted as violations.
