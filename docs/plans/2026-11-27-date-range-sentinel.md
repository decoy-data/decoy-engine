Status: plan

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 3 (after review round 2, with Q1 to Q5 settled in section 15). Revision 4 adds section 4.4b after S5 code review round 2. Revision 5 (2026-11-28) redesigns S5 in section 4.4b after the S5 build failed six code-review rounds, splits it into S5a and S5b, and records Q6 as decided A. Revision 6 (2026-11-28) fixes Dennis plan review round 1 (section 17.3): S5 anchors move to `origin/main` `d1d7453ac`, after #799. Revision 7 (2026-11-28) addresses Dennis round 2 against main at `395c1c662`, including #830. Revision 8 (2026-11-28) addresses the outside Codex review of plan head `f82252693`. Revision 9 (2026-11-28) addresses the review of `fb84f0204` against `395c1c662`. Revision 10 (2026-11-28) puts the S5a scope to the owner as Q9 (section 0), writes S5a for Option A with the owner's Q7 = A and Q8 = A, states S5b as a standalone slice with the two r3 S5b fixes (section 4.4c), and moves superseded detail to Appendix B. Revision 11 (2026-11-28) records the owner's Q9 = A (section 15), moves Q9 = B to Appendix B.5, and fixes Dennis plan review round 1 of revision 10 (`~/scratch/dennis-s5-plan-r10.md`, Appendix B.3.6). Revision 12 (2026-11-28) incorporates the Codex review of revision 11 into the S5 rules, port inventory, tests and mutations. Revision 13 replaces the S5a spelling list with a schema restore and corrects date64 and ISO admission. Revision 14 guards the populated route restore and reuses its result. Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Anchors are in this repository (decoy-engine) at `origin/main` `f54ad388b` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one new reason code, three deprecations, a config key on one more strategy), `catalogs/recurring-defects.md` (11 classes), `cross-cutting-concerns.md` (one rule, many routes), `testing.md` (test depth T0 to T4). Revision 5 also consulted the bound registry (`tests/sentry/ratchet/_limit_constants.py`, `tests/sentry/baselines/sentry-limits.json`) and, as established solutions, Arrow's dictionary semantics (a slice keeps its dictionary; some dictionaries cannot be unified, as covered in AT-V14; `to_pandas` converts the whole dictionary), pyarrow's tz resolver (`pyarrow.lib.string_to_tzinfo`, the tzinfo `to_pandas` and `as_py` receive) for offsets, and Hypothesis property tests against an independent oracle. Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`, deprecation with `replaced_by`).

Risk: R2. It changes what a date strategy does with a far date on every route, adds a reason code and deprecates three, and turns a quarantinable row error into a refusal. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S1, S2, S3, S5, S6, S7 and S8; Codex only for S4. Full suite before merge: S1, S2, S3 and S5 for reasons, and S7 for snapshot serialization; the other slices by their own triggers (section 14).

Owner decision (2026-11-27): a date outside the range a strategy can compute is rejected, unless the column declares it as a sentinel to ignore. Sentinel rows skip the strategy and come out unchanged.

## 0. S5 redesign: Q9 decided A (revisions 10 and 11)

Three Codex plan rounds on revisions 7 to 9 (`~/scratch/codex-s5-plan-r1.out`, `-r2.out`, `-r3.out`) each closed the cases they named and then found the same class one layer deeper. Every new finding came from an Arrow or pandas encoding that the conversion treats specially:

- pandas metadata restores a time zone that the physical Arrow type does not carry (round 2), and an `ArrowDtype` spelling in the metadata restores another unit or zone the same way (round 3);
- two valid `int8` date dictionaries whose union needs a wider index fail in the carried profile (round 2), then the same union fails in AUTO's `concat_tables(...).combine_chunks()` and in the legacy collector (round 3);
- the round 2 fix for the profile union adds a row-sized index allocation (round 3).

Exact route parity on these encodings kept adding machinery, so revision 10 put the S5a scope to the owner as Q9. On 2026-11-28 the owner chose Q9 = A, with Q7 = A (pandas floor 2.x) and Q8 = A (one rule on every route) (section 15). The option not chosen, Q9 = B, is in Appendix B.5. Plain `date32`, `date64` and `timestamp` cells keep the one Q8 = A rule on every route, including passthrough. Rules 3 and 4 apply at actual reads. Exact carry preserves raw milliseconds. S1 to S4, S5b and S6 to S8 do not depend on Q9.

In this section, an *exotic encoding* is one of:

- a dictionary whose value type holds a date (`dictionary<date32>`, `dictionary<timestamp[us, UTC]>` and so on);
- a field with malformed pandas metadata or a restore that changes its date meaning (section 4.4b rule 3);
- a `date64` column with a non-null value that is not a whole number of days.

A column is *date-strategy-read* when a column entry from the run config or compiled work nodes gives it `date_shift` or `bucket_perturb` (the strategies that build the range and sentinel rule of S1), or names it as the `anchor` of a `windowed_date` entry. The set comes from `date_strategy_columns` in `execution/_column_access.py`, the module that already declares which columns each config entry reads (section 4.4b). A `when:` gate does not change the answer: a gated `date_shift` still reads its column. A `date_shift` inside a `nested` entry runs on extracted JSON text, so it does not make the parent column date-strategy-read. A composite entry is decided by its provider, as in `build_work_list`, and no composite is a date strategy. A column that is passed through, kept, hashed, redacted, tokenized or profiled is not date-strategy-read. Stored pandas index fields are never date-strategy-read.

### 0.1 Strategy restrictions and guarded route reads

At `check_source_dates`, the one source-date boundary:

1. A date-strategy-read column in an exotic encoding is refused with the existing type refusal `runtime/source_date_type_unsupported` and one new kind token: `dictionary`, `pandas_metadata` or `date64_time_of_day`. The refusal names table, column and kind, carries no count and no value, and names the fix: cast the column to a plain date or timestamp column (section 4.4b, rule 6, gives the literal texts).
2. A field that is neither a date-strategy input nor materialized by the route receives no restore, no metadata or calendar-day refusal under rules 3 and 4, and no change to its physical buffers. The physical Q6/Q8 checks retain their separate scope.
3. A frame conversion also reads its passthrough and stored index fields. Guard that actual restore before exposing the frame. Use the same test of meaning on any restored date, including a sibling of the masked column.

The dictionary strategy restriction applies at schema admission. Restore failures and changes of meaning depend on the actual input and route options. A genuinely empty input is checked as empty.

Inputs that stay admitted for date strategies (controls in AT-V19 and AT-V21): pandas metadata that preserves the physical date meaning under rule 3, as `pa.Table.from_pandas` writes it for naive, zoned, `date` and `ArrowDtype` columns, and a pandas-written zoned Parquet file read back at `us` whose `numpy_type` still says `datetime64[ns]`. In that writer control the restored unit is the physical unit. On pyarrow 24.0.0 and pandas 2.3.3 that file converts to `datetime64[us, America/New_York]` (probe, 2026-11-28).

**What A refuses that main reads today.** The table describes date-strategy inputs. Revision 14 also guards actual restores of sibling fields. The last column shows which rows the decided Q8 = A already refuses under revision 9 (only the code changes) and which rows are new because of Q9. Comparison rows refer to Appendix B.1.

| # | Date-strategy-read input | Main at `395c1c662` | Under A | Already refused by Q8 = A (revision 9)? |
|---|---|---|---|---|
| E1 | a date dictionary whose entries are all in years 1 to 9999, unique, with a signed index (comparison rows 1 and 4; fixture F3) | the strategy receives a pandas categorical of dates | refused, kind `dictionary` | no: **new with Q9** |
| E2 | a date dictionary with an entry outside years 1 to 9999 in a non-ns unit, or an unused zoned ns edge entry (rows 5 and 7; fixture F2) | the strategy receives the converted rows | refused, kind `dictionary` | yes, with `source_date_unrepresentable` |
| E3 | a date dictionary main cannot convert: far, `INT64_MIN` or null entries, and the one-chunk literals with duplicate entries or a `uint64` index (rows 2, 6, 12, 15; fixture F9; the literal keys of AT-V16) | refused with #799's code on converting routes | refused, kind `dictionary` | yes |
| E3b | a date dictionary main converts only by joining chunks, or reads as another type: duplicate entries spread over chunks, which some multi-chunk conversions unify and then convert; an epoch entry in `dictionary<timestamp[ns, Factory]>`, which pandas reads as a naive timestamp (Appendix B.1, below row 15) | the strategy receives the converted rows | refused, kind `dictionary` | no: **new with Q9** |
| E4 | a field with ordinary values and a metadata mismatch: a string with zoned `M8` metadata (AT-V21), a timestamp with another zone, a restored timestamp that actually loses fractional ticks or another zone, or a `datetimetz` entry over a `date32`, `date64` or naive timestamp field (fixture F11) | restoring reads give the strategy the metadata type, for a `date32` a zoned timestamp on another calendar day; metadata-ignoring reads give it the physical type | refused, kind `pandas_metadata` | no: **new with Q9** |
| E5 | the same with an edge value (physical UTC ns `INT64_MIN + 42` restored to New York; a `us` tick of 1 restored to `timestamp[s][pyarrow]`) | zone restoration succeeds but scalar access can raise with timestamp text and year extraction can wrap; #799 already codes the precision error; metadata-ignoring reads succeed | refused, kind `pandas_metadata` | yes, with `source_date_unrepresentable` |
| E6 | a `date64` with a time of day (for example 1 ms; fixture F12) | the strategy receives the date with the time of day dropped | refused, kind `date64_time_of_day` | yes, with `source_date_unrepresentable` |

Revision 11 adds E3b: the converting successes that Appendix B.1 lists below row 15, which revision 10 folded into E3 as "fails". E4 now also covers the non-timestamp physical fields that rule 3 refuses.

Per route. "Q9" marks a row A refuses where main reads the input today. "Q8" marks a row the decided Q8 = A already refuses (only the code changes). "fails" means main already fails. "none" means no input of that kind can reach the route.

| Route (date strategy configured on the column) | E1 | E2 | E3 | E3b | E4 | E5 | E6 |
|---|---|---|---|---|---|---|---|
| FF and AUTO, resident Arrow or loader | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| SEQ, loader (Arrow) | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| OOC Python and native, resident `sources` | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| CH and NCH, Arrow batches (the configured column is converted or computed natively, never carried) | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| PAN `run` and `run_single` | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| ISO on and off, resident Arrow | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| FF, AUTO, SEQ and OOC on Parquet, CLOUD and HIVE | none | none | none | none | Q9 | Q8 | none |
| PROF and non-strategy siblings | No strategy dictionary restriction | Same | Guard any actual restore | Same | Refuse actual change of meaning | Refuse failed or altered restore | Rule 4 for conversion, original ticks on carry |

**Re-pin both ways.** The cells above are derived from probes, not from runs of every route on main. The S5a wiring slices run every E1 to E6 and E3b cell on `origin/main` red-first in AT-V16 and records the observed outcome per cell. A "Q9" or "Q8" cell where main fails moves to "fails". A "fails" or "none" cell where main succeeds moves to "Q9", is added to the E list here, to the changelog and to the compatibility contract (section 4.7), and is named in the builder report. If the re-pin adds an E row, the builder stops and reports before merge, because the owner decided Q9 on this list.

Parquet stores no date dictionary and no sub-day `date64`, so E1 to E3b and E6 reach a date strategy only as caller-built Arrow (resident `sources`, a `source_loader` result, chunked API input). A pandas frame with a categorical of dates becomes a date dictionary under `pa.Table.from_pandas`, so an SDK caller that shifts such a column must decode it first. E4 and E5 can arrive through Parquet, because Parquet keeps the pandas metadata of the table it was written from. An ordinary Parquet write of an ArrowDtype timestamp can preserve the original unit in pandas metadata while changing the physical unit: `df.to_parquet` writes `timestamp[s][pyarrow]` at ms, and `coerce_timestamps="us"` writes an ns column at us. The changelog, `docs/strategies.md` and the compatibility contract list E1 to E6 and E3b.

What A removes from the revision 9 S5a design: the dictionary structure rule and its count, the bounded index windows, the ISO parent projection of original dictionaries and its RSS bound, the carried-profile index widening, the two metadata interpretations, the disjoint-dictionary and AUTO-join cases, and mutations M-43, M-44, M-50, M-54, M-55 and M-57.

### 0.2 Why A, and how Q9 combines with Q7 and Q8

Section 4.4b distinguishes the config read set from the fields materialized by each route. It binds both to physical columns before any strategy consumes them.

- **Q8 = A (decided).** The plain-cell rule runs on every route, passthrough included. Plain physical dates remain subject to the Q8 domain check. Exact carry preserves an unread date dictionary without visiting its entries. If a route materializes that dictionary or a sibling with stale metadata, it checks the real restore. Removing the asymmetry means judging unread exotic encodings, which is the Q9 = B design (Appendix B.5). The asymmetry goes into `docs/strategies.md` with the E list (section 4.7), not only into this plan.
- **Q7 = A (decided).** pandas 2.x is the floor, so the plain rule keeps the source timestamp unit and needs no pandas 1.x bounds. Q9 does not depend on the pandas version. DEP-FLOOR raises the declared floor (section 14).
- G-16 remains a separate dictionary-union issue. Rules 3 and 4 now cover G-17 whenever the route restores the column.

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

Row O update (2026-11-28, after #799): the profile sampler now refuses with the value-free `source_column_unrepresentable`. NCH passthrough returns the column. S5a gives both the date refusal (comparison rows 3 and 13, Q8 = A).

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

S5 owns the distribution ns bounds used in fitted admission. S1 and S5 reuse the whole-day ns endpoints from a single calendar-range definition in the lower-tier contracts module, landed by S5. S1 imports those names. The transforms table imports `MIN_YEAR` and `MAX_SAMPLED_YEAR` from `contracts/distribution_snapshot.py:31-32`. The decoder uses its own contract constants and never imports transforms. Both fitted generators refuse an unsupported snapshot with `plan/generation_unbounded_column`. Validate bounds and every live bin before a draw, including single-value and direct generator entry points. The fitted distribution sampler has no plan compile path, so it checks at its direct entry; the statistical generator checks its live year bins at plan compile and window admission (section 4.4c). For the distribution generator, clip the first and last year on calendar bounds before constructing ns endpoints. Test 1677 and 2262 as well as out-of-domain bins with ordinary min/max. Explicitly convert to ns before integer arithmetic on every supported pandas version.

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
- Guard: `tests/sentry/dates/test_date_partition_choke_point.py` (new). It walks `src/decoy_engine` with `ast` and:
  - resolves every name in the primitive list to a function and fails if one no longer resolves, so a renamed or moved primitive cannot drop out of the check;
  - asserts each has a required, keyword-only `partition` parameter with no default, and no separate source or shift-window or bucket parameter;
  - asserts `DatePartition(`, `DatePartition.__new__`, `object.__new__(DatePartition` and `replace(`/`copy(`/`deepcopy(` on a `DatePartition` appear only inside `transforms/date_preserve.py`;
  - checks callers of allowlisted forwarding helpers by exact path and function. It also asserts that every function in the strategy-input packages (`execution/_strategies/`, `execution/native/`, `execution/out_of_core/`, `execution/_sequential_native.py`, `transforms/`) that calls `pd.to_datetime`, `pd.to_timedelta`, `timedelta(`, `pd.DateOffset` or adds to a `datetime.date` is either in the primitive list or on an allowlist entry that names module, function and reason (windowed_date, text_mask, the validators). This sees the typed path (`_date_shift.py:366-399`, `bucket_perturb.py:245`) as well as the text path.
- Mutations that must turn the guard red: give `native_bucket_perturb`'s `partition` a default of `None` (M-4); rename `_shift_dates` (M-15); add a `timedelta` add in a new unlisted helper (M-16).
- Second guard: `tests/unit/transforms/date_domain/test_date_domain.py` passes a partition built for chunk N to the primitive together with chunk N+1's companion series and expects the internal error (M-13), and calls the native seams with a near-bound row inside `compute_rows` through a test-only hook and expects the invariant raise (M-14).

**S5 source reads.** Check Arrow data when it enters the reader, before it can reach pandas, Python scalar conversion or a native kernel. Use one checked table or batch operation in the io tier. Bind the table name when opening the source: it is the caller's `sources` mapping key, or the configured table on the single-source chunked entries (section 4.4b). In profile/_readers.py cover LazySource.iter_batches, open_batches and to_table, plus resident frames. At execution entry wrap supplied tables and loader results before transforms, preflight or dispatch, including direct chunked and native APIs. Apply it to resident inputs (including loader returns), lazy materialization and every yielded batch, including opened row-group reads and the direct OOC entry. The profile head uses the same checked read. Keep streaming bounded. A head scan proves nothing about unread rows. Later source conversions, all through main's `arrow_to_frame` / `arrow_to_series` since #799 (for example `execution/_chunked_profile.py:43`, `execution/pipeline/_source_types.py:64`, `execution/out_of_core/_mask_group_c.py:531`), must all receive checked data.

The physical Q6/Q8 checks in section 4.4b return the original Arrow input or raise. The conversion boundary applies rules 3 and 4 to the working result. AT-V1 covers resident returns, caller loaders and lazy yields. The source-date refusal builders remain in io/source_dates.py. Run the import-layer and reason-adapter tests, including isolated classification.

### 4.4a Existing tests the S5 source check changes

This section specifies the test edits for the decided Q8 = A and for Q9 = A.

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
that its replacement preserves. For each additional red, run the original input on the original route and assert the new refusal. On the admitted companion retain the original positions, null bitmap, route and assertions. Show both expectations in the review. Investigate any other failure as a regression. Section 4.4b changes both the plain
timestamp tests above and the following tests added on the S5 branch:

- At port head `a5da43ef9`, retain the Q6 type assertions in `tests/unit/io/test_source_date_nested_refusal_q6a.py` (including in-calendar dates, null parents and sliced maps). Retain the resident, lazy and isolated route assertions in `tests/unit/execution/test_source_date_nested_routes_q6a.py` when moving it into `source_dates/`.
- In `tests/unit/io/test_checked_source_dates.py:89`, replace `test_dictionary_columns_count_referenced_rows` with Q9 expectations on the same referenced rows. A read dictionary refuses by kind without a count. An unread dictionary returns the identical object, including its original indices and entries.
- `test_an_unused_bad_dictionary_entry_is_dropped_not_refused`, `test_a_chunked_dictionary_column_is_cleaned_chunk_by_chunk`
  and `test_a_record_batch_is_cleaned_too`: under Q9 = A the check never judges dictionary entries. Rewrite each as two
  cases: with the column in `date_read`, the column is refused by type with kind `dictionary` in every chunk layout;
  with an empty `date_read`, `result is data`. Rename them to `test_a_read_date_dictionary_is_refused_by_kind`,
  `test_an_unread_date_dictionary_is_left_to_main` and `test_a_record_batch_is_checked_too`.
  `test_a_dictionary_of_something_else_is_left_alone` (no date inside) stays as it is.
- In the remaining `test_source_date_unrepresentable.py` port, preserve the table-name and guard coverage. Use `LazySource(path)` to exercise mapping-key binding (AT-V7). Port the existing read guard to `tests/sentry/dates/test_source_date_read_guard.py` per section 4.4b.
- `docs/strategies.md:403-405` (the nested and dictionary paragraph) is rewritten per section 4.7.

For branch tests, record the specific 4.4b type, cell or dictionary rule that changes the expected result.

### 4.4b S5a design (Q9 = A, Q8 = A, Q7 = A)

Revision 14 implements the owner’s populated-restore decision. The config read set comes from execution/_column_access.py. Section 4.4c specifies the independent S5b slice.

**Main after #799.** `7822182c5` (#799, "route source reads through one conversion that fails coded") merged after the S5 branch was cut from `9812da814`. `a5da43ef9` does not contain it. On `395c1c662`:
- every source conversion goes through `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` or `table_to_pandas_exact_ints` in `internal/pandas_compat.py`. The public module `decoy_engine.arrow_frames` exports the three `arrow_to_*` names. The exact-integer helper is internal. Only the implementation module calls `to_pandas`;
- a column pandas cannot hold raises the coded, value-free `runtime/source_column_unrepresentable` (or `full_frame_value_unrepresentable` on the pandas execution routes), built in `_execution_error.py:52-75`.

Use #799’s conversion implementation and its route arguments as the restore boundary.

S5 preserves original Arrow buffers on admission. The physical checker returns its input. A converting caller receives the checked pandas result directly.

#### The rule

`check_source_dates(data, *, table, date_read)` in `io/source_dates.py` is the one place where the source date domain is judged. It judges one table or record batch, with its schema and pandas metadata. `date_read` is the set of physical field names that a date strategy reads in this table (section 0). Execution identifies the configured reads once per table with `date_strategy_columns(entries, registry) -> frozenset[str]`, added to the existing `execution/_column_access.py` beside `touched_columns`. No new execution module is added: `FANOUT_ALLOWLIST` pins `src/decoy_engine/execution` at exactly 102 modules (`tests/sentry/layout/test_package_fanout.py:33`), and `_column_access.py` is already the one declaration of which columns each config entry reads ("never a scan of config strings"). Source checks precede `build_run_context`; `build_work_list` takes a compiled Plan. Bind entries from raw run config through the same `_table_columns(config, table)` view as `passthrough_columns` (_chunked_carry.py:187,256). For `PandasExecutionAdapter.run` (_pandas_adapter.py:167), build the work nodes once with `build_work_list(plan, registry)` before resident source admission. Group by `node.table` and feed the same classifier entries from the existing `ColumnSeed` mapping in `untouched_columns` (_chunked_carry.py:230–244). Extract that mapping once for both callers, preserving name, strategy, provider, decoded provider_config, coherent_with and when. Non-ColumnSeed FK bundles still count as masked in carry and contribute no scalar date entry. Reuse the work list for dispatch. `run_single` (:132) delegates with the same plan, table key and registry. Require an explicit read set at the checker and wrapper boundaries. Resolve the caller registry before admission (use `get_default_registry()` when it is None) and pass the same registry to dispatch. The ISO parent uses the default registry because its entry refuses a caller registry. The common classifier uses the column-access module’s parsing:
- `_is_composite(provider, registry)` decides composite entries first, as `column_access` does. No composite is a date read.
- A scalar entry whose `strategy` is in `DATE_STRATEGIES = frozenset({"date_shift", "bucket_perturb"})` reads its own column. A `when:` gate (`has_when`) does not change that.
- A `windowed_date` entry reads `_provider_config(entry)["anchor"]`, the key `SIBLING_REFERENCE_KEYS` already names.
- A `nested` entry is not a date read of its column, even when a JSON child (`nested_children`) is `date_shift`: the child runs on extracted text.
- Bind targets and anchors by exact string equality against the available schema labels, excluding stored index fields. Apply this when each resident table, loader result or streamed schema becomes available. Strategy lookup indexes the exact label (_strategies/_date_shift.py:177). The conservative NFKC match in carry planning (_chunked_carry.py:81) serves a different purpose.

The constant and the helper are about 35 lines; the module goes from 544 to about 580. The `io` tier never reads config. Standalone profile reads pass an explicit empty set. Execution callers supply the set computed for each table, including an empty result when there are no date reads. S1 adds a sentry assertion that the strategies which build a `DateDomain` equal `DATE_STRATEGIES`.

Separate the early physical and structural checks from the value comparison at materialization. Native-only date-strategy reads also need the guarded restore described below.

1. **Type gate (Q6 = A, unchanged).** A column that holds a date inside a list, large list, fixed-size list, map, struct, list view, run-end-encoded, union, extension or dictionary-of-container type is refused by type with `runtime/source_date_type_unsupported` and its outermost kind, whatever its dates are and whether or not a strategy reads it. The walker, the shape classifier and the unclassified-layout refusal from the S5 branch stay (`_arrow_types.py`). A top-level dictionary of a plain date type is not a container. Rule 2 decides it.
2. **Strategy input restrictions (Q9 = A).** Bind date targets and anchors before dispatch. Apply these priorities within a field:
   - a field in `date_read` that is a dictionary of a plain date type is refused, kind `dictionary`;
   - a field in `date_read` with a metadata mismatch (rule 3) is refused, kind `pandas_metadata`;
   - a `date64` field in `date_read` with a time of day (rule 4) is refused, kind `date64_time_of_day`;
   - A dictionary that is only carried keeps its Arrow representation. A non-strategy dictionary that the route converts retains its categorical behavior if its logical values and restore are valid.

   Apply Q6 and the dictionary restriction first. Preserve the physical rule-5 domain refusal and count for intrinsically unholdable plain dates (including Factory). A restore failure for an otherwise admissible input takes precedence over a sub-day refusal. Check fields in projection order. Keep unassigned table-level failures value-free.
3. **Guard the real restore.** For a source table, use the route’s actual projection, pandas metadata, index descriptors, mapper, metadata flag and exact-integer handling. The exact-int helper already reassigns named integer columns as nullable series. Validate the final assigned values and preserve that existing contract without adding a preflight conversion. For ordinary FF the options are types_mapper=None and ignore_metadata=False. Keep ignore_metadata=True on paths that request it. Wrap the existing conversion in `internal/pandas_compat.py` (frame :199, series and frame-pair in the same module). Invoke the shared source-date decision via a callback supplied by the source reader so the lower tier never imports IO. Keep error construction in `io/source_dates.py`. For a frame, validate the frame that will be returned, including reconstructed indexes by physical position. For a series, use its actual array conversion. Do not substitute a series conversion for a metadata-restoring table. For a native date target or anchor with no pandas consumer, guard one populated projection with the engine’s ordinary metadata-restoring frame helper before the kernel. Pass the original Arrow data to the native kernel after admission. On streamed routes guard the current batch before yielding or masking it. Keep the work and its result local to that read.

   Keep the structural parser with `stored_index_fields` in `_pandas_meta/_columns.py` and export through its package API. Check the projected footer’s mapping, column/index structure, field identity and required descriptor types. A categorical descriptor requires signed code dtype, nonnegative integer count (exclude bool) and boolean ordered. Scope checks to participating fields. Omitted projected entries use the library default. A malformed shared descriptor affecting a read gives a typed refusal. Always bind configured reads by exact physical name, including when a malformed index descriptor prevents ordinary label binding. The parser supplies structure only.

   Inside the guard run the existing restore on the real rows, including genuinely empty inputs. Catch conversion and deferred scalar/index access exceptions here, including backend exceptions outside #799’s ordinary tuple. Retain existing resource classification for resource failures. On a restore failure discard exception text, args and traceback. Raise one `SourceDateTypeUnsupportedError` (kind `pandas_metadata`) after leaving the handler, before #799 diagnostics retry individual fields or a downstream consumer reads the frame. Use the known field, or table alone for an unattributed frame failure. Reuse the optional-column location wording of #799. Never derive a field name by parsing backend text. Preserve #799's existing handling for unrelated non-date jobs and conversions outside the guarded source path.

   Compare physical and restored rows by position, including length and null mask. Use actual scalars or exact typed array operations with scalar-access equivalence. For a timestamp require a timestamp, the same resolved named zone (or fixed offset, including naive), identical instant at the physical precision, and in-range UTC and local calendar values. Compare ticks with overflow-safe exact scaling, including the sub-microsecond remainder. Reject non-null to NaT, changed day, wrapping, truncation, or loss of scalar access. For calendar dates require an accessible calendar date with the expected day under rule 4. For a text target or anchor require the same text in every non-null row, including categorical text. Reject date/non-date and calendar-date/timestamp substitutions. Read the actual restored type and zone even for an empty or all-null input. For object results without scalar evidence, enforce structural constraints and validate subsequent populated batches independently. A change in unit with exact values and range on this input can pass. Writer metadata alone never determines the result.

4. **Calendar day and unread fields.** On a date-strategy read, apply the populated restore first. A failed cast is the rule-3 refusal. After success require day alignment of physical date64 milliseconds and equality of restored and physical days. Misalignment on a strategy input has kind `date64_time_of_day`. For a restored passthrough date use its actual accessible day in years 1–9999 and verify the calendar-day semantics of the route: bare Python dates truncate sub-day milliseconds toward zero, Arrow date64 scalar access floors them. Compare to the physical day under that convention with exact integer arithmetic. A failed restore or changed meaning refuses. Scan at most 65,536 logical rows per comparison window.

   A field outside both the strategy reads and the route’s real conversion projection is unread for this guard. Do not restore it, inspect its pandas descriptor, or refuse it under rules 3–4. Projection away and exact carry both exercise this path. A field selected by a whole-frame restore is read even when the config only masks its sibling. Guard that field at the same boundary. Physical rule 1 and plain-cell rule 5 still apply on Arrow-only routes. On exact carry judge a sub-day date64 by its bare calendar day (integer division toward zero, preserving the existing bare carry domain), without consulting pandas metadata, and preserve every admitted raw tick.

5. **Holdable cells (Q8 = A, every route).** Apply the plain physical domain to non-null logical cells. For a restored calendar date use rule 4. A holdable cell meets these conditions:
   - its instant is a day in calendar years 1 to 9999 (the 4.4a domain, Q1);
   - for `ns`, its instant is not `INT64_MIN`, which pandas reads as `NaT`;
   - for a zoned timestamp, pandas can read the cell and Python can turn it into a `datetime` in its zone.

   | Type | A non-null cell with physical integer `v` is holdable when |
   |---|---|
   | `date32` | `CALENDAR_FIRST_DAY_NUMBER <= v <= CALENDAR_LAST_DAY_NUMBER` |
   | `date64` | its day lies in that range (rule 4). For sub-day passthrough converted to pandas, decide the calendar bound on the actual restored scalar |
   | `timestamp(unit)`, no zone | `lo <= v <= hi` |
   | `timestamp(unit, zone)` | `lo <= v <= hi`, the zone resolves, and `lo <= v + offset(zone, v) <= hi` with the local time inside years 1 to 9999 |

   `[lo, hi]` is the span from the first tick of year 1 to the last tick of year 9999 in the unit's ticks, intersected with `[INT64_MIN + 1, INT64_MAX]`. For `s`, `ms` and `us` the calendar lies inside the storage range, so `[lo, hi]` is the calendar. For `ns` the storage range is the narrower one, so `[lo, hi]` is 1677-09-21 00:12:43.145224193 to 2262-04-11 23:47:16.854775807 UTC. `offset(zone, v)` is the UTC offset at instant `v` of the tzinfo that pyarrow gives pandas and Python for that zone ("How the zone test is computed" below). Rule 3 compares actual source and restored values. Rule 4 checks the resulting day. Q7 = A: pandas 2.x keeps the source unit, so no pandas 1.x bounds exist.
6. **Refusal, count and text.** A failed cell test or an unresolved zone raises `SourceDateUnrepresentableError` (`runtime/source_date_unrepresentable`). The count is the number of logical rows of this column in this checked input with a non-null value that fails, or with a non-null value in an unresolved zone. Missing rows add zero. An empty or all-null column in an unresolved zone refuses with `count == 0`. The count is kept on the typed error only. A type, metadata, restore or alignment refusal raises `SourceDateTypeUnsupportedError` with table, column and kind, and no count. Raise outside any handler. The variable part of every text is the mapping key and column only. The fix sentences are fixed strings:

   | Kind | Fix sentence in the message |
   |---|---|
   | `dictionary` | "A date strategy reads this column, and it is dictionary-encoded. Cast it to a plain date or timestamp column." |
   | `pandas_metadata` | "The source could not be restored with its original meaning. Check the source type and rewrite its pandas metadata." |
   | `date64_time_of_day` | "A date strategy reads this column, and it holds a time of day. Cast it to a plain date32 or timestamp column." |
   | container kinds (Q6) | the revision 4 text, unchanged |

7. **Cost and reuse.** Charge one restore per materialized table projection or batch, over only its read columns. Hand the checked frame or series directly to masking, profiling or dispatch. Preserve its index, category order and dtype. If a route already owns the frame, compare in place. Carry the verified result across helper calls for that same source read. Do not convert the original again for the consumer. ISO checks structure in the parent and restores in the consuming process. Native-only date reads incur one extra restore of just the target/anchor projection. Exact carry incurs none. The incremental work on an already converting route is one linear comparison over the guarded logical cells, with bounded scratch plus the result main already needs.

   AT-V15 measures baseline and guarded elapsed time on the same test node with identical 10M-row inputs, projection, route and batch size. Report median elapsed time for both, delta and ratio, separately for full-frame, batches, native-only reads and exact carry. Charge the native projection and all scalar checks to the guarded run. Retain the 1 MiB physical-check scratch ceiling and 65,536-row window. Time the full route including restore and consumption. Revision 13 gives no numeric elapsed-time ceiling for the 10M-row date workload. Report its delta separately. On the existing scalar no-FK and chunked single-table benchmark fixtures, both limits are elapsed time < 2.6 s (origin/main, tests/perf/test_job_performance_gates.py:246,637). For each, report baseline, incremental seconds and remaining headroom; the guarded total must still meet its own limit with output parity. Run timings on the test nodes.

**Reason decision.** S5a keeps its own code, `runtime/source_date_unrepresentable`, beside #799's `runtime/source_column_unrepresentable`:
- the set of values is different: S5 refuses dates that pandas can hold, under the decided calendar domain (for example a `timestamp[us]` cell in year 10000, or fixture F4), and on routes that never convert (NCH carry);
- the remedy is different: fix or null the date, or cast the column to text. A date outside this domain cannot be declared as a sentinel;
- it carries a row count.

Move the table and column phrase of `_unrepresentable_text` (`_execution_error.py:41-46`) into `source_location_text(table, column)` in the same leaf module. Both error families build their message from it. `io` sits above the `_execution_error` tier (`tests/sentry/layout/test_import_layers.py` `LAYERS`), so the import is allowed. Registry summaries: `source_date_unrepresentable` "The source date column holds a date outside years 1 to 9999, outside the nanosecond range, or in an unknown time zone"; `source_date_type_unsupported` "The source column holds dates in a type or encoding the engine does not read". The remediation names each kind's fix from rule 6. Both codes are `since=UNRELEASED`, so the text can still change without a deprecation.

**How the zone test is computed (revision 6, H1).** pandas 2 does not use `zoneinfo`. `to_pandas` gets its tzinfo from pyarrow's resolver, `pyarrow.lib.string_to_tzinfo(zone)`, which returns a `pytz` zone when `pytz` is installed. pandas 2 requires `pytz`, so in every supported environment the zone is a `pytz` zone. `as_py` uses the same resolver. `pytz` differs from `zoneinfo` in three ways that matter at the bounds:
- It keeps the last rule after its 2037 transition table. Australia/Sydney is +11:00 and Pacific/Auckland is +13:00 at 2262-04-11 (zoneinfo: +10:00 and +12:00). Europe/Berlin goes the other way: +1:00 (zoneinfo: +2:00).
- It rounds local mean time offsets to whole minutes: New York is -4:56, not -4:56:02.
- It does not know some zones that `zoneinfo` knows, for example `Factory`.

So the zone test uses the resolver that the converter uses:

- Resolve the zone once per judged zoned column with `pyarrow.lib.string_to_tzinfo`, whether or not the column has band cells, including empty and all-null columns. Resolution is a type-level requirement. A missing zone definition sets the refusal even when the row count is zero. On a reader that yields no batches, check the projected typed empty table before returning an empty result. Catch only `KeyError` and `pa.ArrowInvalid` from the resolver. `KeyError` covers both pytz's unknown-zone error and zoneinfo's missing-key error. Keep pytz imports out of `io`. AT-V12 pins the refusal.
- Let `M` be two days in the unit's ticks. The largest named-zone offset measured was 15:56:08 (Asia/Manila). The resolver also accepts fixed offsets through plus or minus 23:59. Both fit within the margin. A cell with `lo + M <= v <= hi - M` is holdable in every resolved zone, and a cell outside `[lo, hi]` is not. Integer comparisons on the whole array decide both.
- For *band* cells (within `M` of `lo` or `hi` in a zoned column), take the distinct band values (`pc.unique`). Build each one's UTC `datetime` from whole seconds, since offsets change on whole seconds. Convert it with `astimezone(tzinfo)` and add the offset back to `v` in integers. An `OverflowError` means the local wall time leaves years 1 to 9999: not holdable.
- The helper returns a boolean and catches only the listed errors. The refusal is raised later, outside it.
- `pc.local_timestamp` and `_fixed_offset_seconds` are not used. The resolver handles fixed offsets (`+05:30`, `-08:00`) as well, so one path covers every zone and the pyarrow 14 fixed-offset failure (R3) cannot recur.

This resolver serves the physical rule-5 range check, including exact carry. Rules 3 and 4 validate the result at the conversion boundary. A library probe on main's venv (pyarrow 24.0.0, pandas 2.3.3, pytz 2026.2, 2026-11-28) compared the resolver test with real conversion plus scalar access on 14,448 band values over 599 zones and three fixed offsets, in units `s`, `us` and `ns`, at both bounds: 0 disagreements. AT-V13's oracle is the real conversion, so a pandas or pyarrow change that breaks this agreement turns the test red. Any pandas or pyarrow pin bump, and the DEP-FLOOR legs, run AT-V13 and AT-V20. `string_to_tzinfo` is a private pyarrow API. It is present on 24.0.0 (checked by Dennis) but not verified on the declared floor 14, so the DEP-FLOOR pyarrow 14 leg runs the AT-V21 writer controls as well as a one-line import check of `pyarrow.lib.string_to_tzinfo` and fails if it is missing. The review verified the six original AT-V21 writer rows and int32 → date32 on PyArrow 14.0.2. Run the full fixture set at the dependency floor on the final implementation head.

#### Where the check runs (choke point and guards)

Physical admission and populated comparison share the IO decision site. The conversion implementation owns the restore. Ingestion reaches it through the entry wrappers that the S5 branch already built and review already passed. Rounds 3 to 6 confirmed that SEQ, direct OOC, both chunked entries, `PandasExecutionAdapter.run` and `run_single`, cloud and ISO reach it. The wrappers are:
- `check_resident_sources` at pipeline, direct OOC and pandas adapter entry, and `checked_loader` at pipeline and direct sequential entry (port sites in M-73);
- `checked_chunks` in `execution/_chunked_input.py` for both `run_mask_pipeline_chunked` and `run_mask_chunked`;
- `checked_batches` for lazy Parquet batches;
- the profile readers, always with an empty `date_read`.

Give `check_resident_sources`, `checked_loader`, both `checked_chunks` entries and `checked_batches` the required keyword `date_read_by_table=`, with an explicit entry for every source table on the call. A missing entry must never silently become an empty set. Execution supplies the table-specific schema binding above, including on lazy results and batches; the IO check receives only physical names as `date_read`. Use the same binding for the ISO parent. M-73 exercises each wrapper site separately.

**Isolation.** Put the parent schema admission in `execution/_isolated_reason.py` and call it on original resident schemas by mapping key immediately before `DeclarationRequest.for_run` in `run_pipeline_isolated` (_isolated_run.py:236). Keep the prior argument, request and ambient-access checks. Both ISO modes reach this point before declaration, dispatch, staging or spawn. The helper binds configured reads through the shared guarded index fact and invokes the common schema checker (rule 1, the dictionary gate and rule 3 structural validation only). Thus malformed JSON cannot escape from the earlier `for_run → arrow_columns → stored_index_fields` path. Keep the normal declaration and file-access checks on success. Preserve unrelated declaration errors. ISO off and worker re-entry use the in-process failure mapper. Catch only typed source refusals in this helper. For an intended spawn return `replace(in_process_failure(exc), isolated=True, peak_rss_mb=None, pid=None)` on typed refusal. Return None on success. Two call-site lines (conditional helper call with effective spawn mode `isolate and not already_isolated`, then return) and one import would take the 597-line module to 600. Measure the diff and keep its ceiling. The helper module starts at 112 lines. The child checks staged cells after applying its memory limit. IPC preserves the admitted physical buffers.

The builder re-derives each line anchor on main while porting (section "What the S5 branch keeps").

Four guards hold it:

- **The read sentry** (`tests/sentry/dates/test_source_date_read_guard.py`, kept from the S5 branch, sink set rebuilt in revision 6). Every function that hands Arrow source data to a conversion must be a checked entry or have a per-function allowance with a reason.
  - On main the conversion helpers (the sinks) are `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` and `table_to_pandas_exact_ints`. Resolve all four at their definition and follow aliases. For the three `arrow_to_*` functions, also follow the public re-exports in `decoy_engine.arrow_frames` and the root package.
  - The census assertion: every function in `internal/pandas_compat.py` that calls the exact attribute `to_pandas` is a sink, or a private helper that only a sink calls. On main that is `arrow_to_frame`, `arrow_to_series` and `_first_failing_column`, and only `arrow_to_frame` calls `_first_failing_column`. Exclude `arrow_dtype_label`, whose call is to `to_pandas_dtype`.
  - Keep the resolved direct-caller check (M-36) and the alias resolution from round 4.
  - Remove the bare-statement rule (old M-29): the check returns its input, so a call whose result is dropped is correct.
  - Name the bound as the module constant `_STOP_AT` and use it in the size assertion. Register it in `tests/sentry/ratchet/_limit_constants.py` `LIMITS` as `("dates/test_source_date_read_guard.py", "_STOP_AT"): "max"`, and mirror it as `dates/test_source_date_read_guard.py::_STOP_AT` in `tests/sentry/baselines/sentry-limits.json` with a reason. Pin the measured caller inventory when the wiring is complete in S5a-1c. The builder report states the measured count. If it is above 40 (the branch's stop), the builder stops and reports instead of pinning.
- **One decision site.** Outside `io/source_dates.py`, no module under `src/decoy_engine` constructs `SourceDateUnrepresentableError` or `SourceDateTypeUnsupportedError` (their definitions live in `io/bounded_reader.py`), and no module imports the holdable helpers. `date_strategy_columns` in `_column_access.py` decides the use set only and never a refusal. The walk parses the tree and resolves import aliases, as the existing sentry does.
- **Guarded conversion and reuse.** Extend the read sentry at the existing #799 sinks. Seed a direct unguarded source restore, an ignored checked frame followed by a second conversion, and an unguarded later batch. Each must fail. Instrument successful restore calls and their row counts, field projections and options. Assert the consumer receives the very result returned by the guard. Exact carry records zero calls for the carried field. Keep #799’s ordinary converters available to non-source callers.
- **Admission soundness** (AT-V20). Compare the admitted result against the populated route conversion on an independent input. Exercise scalar and index access, and check exact equality of the applicable physical and restored values.

**Reads stay main's reads.** S5 does not change how a source is read.
- Whole-file reads: `LazySource.to_table` (feeding `profile/_readers.py:417`) and the S3/GCS whole-object reads (`profile/_cloud_readers.py:272` and `:394`, main's `pq.read_table` then `arrow_to_frame`). Insert `check_source_dates` on the returned table before main's conversion, and guard the route conversion itself. Do not port `read_table_gated` or the `pyarrow.dataset` import.
- Batch reads keep the S5 branch's open-time gate on the projected schema (`projected_schema`, `_gate_open`). The gate applies the schema and structural checks at open. Guard the actual first and every later batch at materialization. For a genuinely empty result, guard the route’s actual empty conversion once.
- A file that Arrow itself cannot decode (a null parent in a `fixed_size_list<date32>`) fails with Arrow's error, as on main (follow-up G-14).

**Table name.** Unchanged from revision 4 and kept from the branch: `check_resident_sources` rebinds a lazy source to its `sources` mapping key, the single-source chunked entries use the configured table, and ISO carries the key through the manifest.

#### Behavior matrix

The rule is tested exhaustively at the function, and each route is tested to reach the same function with the right `date_read` and report its answer unchanged.

Axes:
- Routes: FF and AUTO; SEQ (`run_pipeline` sequential and direct `run_sequential`); OOC (`run_pipeline` out_of_core and `run_fk_out_of_core`, Python and native backend); CH; NCH; PAN (`run` and `run_single`); ISO (on and off); CLOUD (S3/GCS whole-object and range readers); HIVE (whole directory, and a batch reader on the partition file); PROF (head sample, resident and lazy).
- Use: the column is date-strategy-read (`date_shift`), or only passed through.
- Layouts: plain, one chunk; plain, many chunks; plain, sliced, with a bad value in hidden storage outside the slice; record batch and table; dictionary, any layout.
- Zones (timestamps only): naive; `UTC`; negative (`America/New_York`, `-08:00`); positive (`Asia/Kolkata`, `+05:30`, `Pacific/Kiritimati`); zones where `pytz` and `zoneinfo` differ (`Australia/Sydney`, `Pacific/Auckland`, `Europe/Berlin`); an unknown zone (`Factory`).
- Units: `date32`, `date64`, `timestamp` `s`, `ms`, `us`, `ns`.
- Positions: ordinary; hidden storage outside a slice; at each bound (`lo` and `hi`, one tick outside each, a band cell whose local time stays inside, and one whose local time leaves).

| Cell group | Cells | Expected | Acceptance test | Mutation that must turn it red |
|---|---|---|---|---|
| R. Rule | every unit x zone x position, plain, at the function | holdable per rule 5; hidden storage ignored | AT-V12, AT-V13 | M-38, M-39, M-40, M-41, M-42, M-53 |
| Z. Zone library | Sydney and Auckland at the `ns` top, Berlin near the `ns` top, New York local mean time at the `ns` bottom, `Factory` | Sydney and Auckland refused; Berlin read where pandas reads it; New York at `INT64_MIN + 42` refused and at `INT64_MIN + 5h` read; `Factory` refused | AT-V12, AT-V13 | M-53 |
| E. Exotic encodings | each kind, read and unread, at the function and on the routes in AT-V16; each rule 3 outcome; each use-set row | read: type refusal with the kind and its fix sentence; unread: `result is data` and main's outcome; pandas-written controls admitted | AT-V21 | M-65 to M-73, M-76 to M-80, M-82 to M-84 |
| A. Admission soundness | generated judged date columns, every unit and zone | `arrow_to_frame` on main's code converts; every `iloc` and each applicable AT-V20 Arrow scalar read succeeds and none is `NaT` for a non-null source cell | AT-V20 | M-39, M-53 |
| L. Layout | each R cell in every plain layout | same decision and count for equivalent forms of one checked input | AT-V14 | M-38 and M-40 also run through AT-V14 |
| P. Purity and cost | every admitted cell; a 10M-row `date32` and a 10M-row `date64` column | `check_source_dates(x) is x`; Arrow pool growth below 1 MiB on the pass path | AT-V15 | M-45, M-72 |
| T. Type gate (Q6 = A) | containers, list views, run-end-encoded, union, extension, dictionary of containers, at the function and on FF, CH, NCH and a lazy route | `source_date_type_unsupported` with table, column and kind | AT-V3, AT-V4, AT-V5 | M-21, M-25, M-26, M-27 |
| X. Route reach | the route-by-fixture table below | the literal expected outcome per executed cell; the executed-cell count is exact | AT-V16, AT-V1 | M-46, M-47, M-24, M-36 |
| N. Name binding | lazy sources under a mapping key, stale `table=`, ISO manifest | refusal names the mapping key | AT-V7 | M-23, M-37 |
| H. Reads unchanged | HIVE, CLOUD whole-object, a directory, a dotted projection, `columns=["key"]` | the Arrow input to conversion equals main's `pq.read_table` with the same arguments (`key` stays `dictionary<int32>`) | AT-V17 | M-49 |
| C. Conversion unchanged | admitted plain date columns, pandas-written zoned and `ArrowDtype` frames, unread date dictionaries and a date `CategoricalIndex` through FF, CH, fidelity report and post-scan | the pandas frame and the output equal those of `origin/main` | AT-V19 | M-66 (an unread dictionary judged) |
| S. Sentries | the read sentry with main's sinks, the decision-site rule, `_STOP_AT` | seeded bypasses fail | AT-V8, AT-V18 | M-48, M-51, M-52, M-56 |

**Fixture set F for AT-V16.** Record two expectations per key. Assert the fixture decision at its physical or populated boundary. For metadata fixtures the refusal applies when the route actually changes meaning or fails. A route that ignores metadata and preserves the physical values admits. Record projection, mapper and metadata option for each key. Through the public route record the stage reached and the observed main result, including compile and strategy errors. Main rejects naive timestamps at date_shift compilation with a column shape mismatch. For admitted naive writer controls assert source admission and preserve the observed public compile outcome. For F5 distinguish that baseline from the source refusal when admission runs first. For admitted controls require the same downstream success or failure as main. Each fixture is one table `t` with a date column `c` and an ordinary `id` column. The config gives `c` a `date_shift` strategy unless the fixture says "unread", where `c` is passed through. Each runs as one chunk and as chunks of two rows, with the same logical rows. Pad short fixtures with ordinary rows to four rows. Put the single bad cell of F4, F5 or F8 in the first pair.

| Fixture | Column | Expected |
|---|---|---|
| F1 | plain `date32`, 10,004 rows with one year 10183 at row 10,001 (beyond the profile head, and in the split layout in a later chunk, batch or row group) | when the reader reaches it, `source_date_unrepresentable`, `t`, `c`, `count == 1` |
| F2 | `dictionary<timestamp[ns, America/New_York]>`, entries `[0, INT64_MIN + 42]`, rows reference entry 0 | refused, kind `dictionary` |
| F3 | `dictionary<date32>`, entries `[2020-01-01, 9999-12-31, 0001-01-01]`, rows reference the first two | refused, kind `dictionary` (E1) |
| F3u | F3, unread | read; output equals `origin/main` |
| F4 | plain `timestamp[us, Asia/Kolkata]`, `9999-12-31T23:00Z` | refused, `count == 1` |
| F5 | plain `timestamp[ns]`, `INT64_MIN` | refused, `count == 1` |
| F5u | F5, unread | refused, `count == 1` (Q8 = A) |
| F6 | plain `timestamp[us, America/Chicago]`, `9999-12-31T06:00Z` | source admits. Public FF date_shift on main fails downstream with `RowErrorsFailedError` and `format_error`. Preserve that outcome. |
| F7 | `list<date32>`, dates in range | refused, kind `list` |
| F8 | plain `timestamp[ns, Australia/Sydney]`, `INT64_MAX - 10h` | refused, `count == 1` |
| F9 | `dictionary<date32>`, entries `[2020-01-01, null]`, rows reference entry 0 | refused, kind `dictionary` |
| F11 | plain `timestamp[ns, UTC]`, an epoch tick, pandas metadata `datetimetz` with zone `America/New_York` | refused, kind `pandas_metadata` (E4) |
| F11u | F11, passthrough | exact carry succeeds unchanged. If actually restored with a changed zone, refuse with kind `pandas_metadata`. Metadata-ignoring restores preserving UTC admit. |
| F12 | plain `date64`, first value 1 ms | refused, kind `date64_time_of_day` |
| F12u | F12, unread | read; output equals `origin/main` |

"Arrow" means a resident `pa.Table`, a `source_loader` result or chunked API batches. "Parquet" means a `LazySource` or a cloud object. Parquet stores no date dictionary and no sub-day `date64`, so F2, F3, F3u, F9, F12 and F12u are Arrow-only. Never feed them through Parquet as stand-ins. Parquet keeps pandas metadata, so F11 and F11u run on every row. PROF has no strategy, so on PROF every fixture runs as its unread form (F3u, F11u and F12u follow the actual route conversion, and F2 and F9 are guarded if materialized).

Route rows are those of revision 9 (Appendix B.4): 10 Arrow rows (FF/AUTO, SEQ loader, OOC Python, OOC native, CH, NCH, PAN, ISO off, ISO on, PROF) and 9 Parquet rows (FF/AUTO, SEQ lazy, OOC Python, OOC native, CLOUD range head, CLOUD whole object, HIVE batches, HIVE whole directory, PROF). With 15 fixtures on Arrow rows and 9 (F1, F4, F5, F5u, F6, F7, F8, F11, F11u) on Parquet rows, the grid is 150 + 81 = 231 keys per layout, 462 for both layouts.

- On PROF resident, PROF Parquet and CLOUD range, request exactly 10,000 rows of F1. Assert the returned frame equals the first 10,000 good rows. Also run F10, which moves the far date to row 2, in both layouts, and require the coded refusal with count 1 (six keys). Count batch pulls on the bounded path.
- On CH and NCH consume the public iterator with the fixture config. In split F1 compare each of the first 5,000 yields, in order, to its two masked rows from a successful main run on the good prefix with the same config, seed and chunking. The next pull refuses at rows 10,001 and 10,002 with count 1, and a later pull ends the iterator. Separately feed late F1 from a lazy file through the transactional auto-chunk route with a reference sink, threshold two and two-row chunks. Require abort, zero committed files or tables, and no staged output.
- Literal keys (eight): duplicate date32 categories `[epoch, epoch]` with indices `[0, 1]`, and date32 `[epoch]` with a `uint64` index `[0]`, each read (kind `dictionary`) on PAN and NCH; `timestamp[ns, Factory]` with zero rows, and with two null rows, each read on PAN and NCH (date refusal, count zero).
- Isolation keys (four): on forced ISO on and off, a resident table whose read column `c` is a `dictionary<date32>` with one ordinary chunk and a trailing zero-row chunk, and a wholly empty column with one zero-row dictionary chunk. All four refuse with kind `dictionary` in the parent before the writer runs. Spies on the writer and spawn record no calls. For ISO on assert `isolated is True`, `peak_rss_mb is None` and `pid is None` on each refusal. A successful control runs inside the capped child. For each fixture compare ISO on and off for exact equality of outcome, reason and error.
- Metadata and index keys (eight): F11's edge form (physical UTC `INT64_MIN + 42`, metadata New York), read, on FF Arrow and NCH (kind `pandas_metadata`); a pandas-written zoned frame stored with `coerce_timestamps="us"`, read, on FF Parquet and PROF Parquet (admitted, equals main); a frame with `timestamp[us][pyarrow]`, zoned `ArrowDtype` and `date64[ms][pyarrow]` columns, all read, on FF Arrow and NCH (source admits all three. Pin the public outcome separately, including the FF compile rejection for naive timestamp date_shift); a frame with a date `CategoricalIndex` stored as a dictionary index field, with a read plain date column, on FF Arrow and NCH (admitted: an index field is never read, equals main).
- AT-V16 asserts exact key sets: 462 grid keys, 6 F10 keys, 8 literal keys, 4 isolation keys and 8 metadata and index keys, total **488**. For each refusal check the registered code, names-only variable text with the fix sentence, empty cause and context on the typed exception, and no source value in errors, logs or public results. Only the typed date exception carries the count.

**Factory on a passthrough stream (outside the 488 keys).** Plain `timestamp[ns, Factory]` in NCH's first table, unread, populated (one epoch), typed empty or two nulls: the first table refuses with counts 1, 0 and 0 (Q8 = A). Separately feed a good UTC first table and a Factory second table with identical column names: yield the first table, then refuse the populated second at the source boundary, count 1, with no further yield.

#### Tests in detail

- **AT-V12** (`tests/unit/io/test_source_date_hold_rule.py`, new). An enumerated table of every unit x zone x position cell, plain, each with its literal expected decision. It includes the Z rows: Sydney and Auckland at `INT64_MAX - 10h` and `INT64_MAX - 12h` (refused); Berlin at `INT64_MAX - 3601 s` (read); New York at `INT64_MIN + 42` (refused) and `INT64_MIN + 5h` (read); fixed offsets at both bounds; `Factory` populated, typed empty and all-null (refused, the last two count zero); an unread `date64` with a time of day at the last day of year 9999 (read) and at the first tick of year 10000 (refused). Add `-62135596800001` ms: read refuses by kind, bare FF passthrough admits day −719162, Arrow-backed FF scalar access fails and exact carry preserves the original milliseconds. Expectations are literal only, written from the rule table and checked once against real conversion, never taken from the function under test.
- **AT-V13** (same file). Hypothesis property over random `v`, drawn uniformly and from the bands (within `2 * M` of each `lo` and `hi`), for every unit and every listed zone, on plain columns. Include bare and Arrow-backed date64 at −1 and −62135596800001 ms, as targets, restored siblings and exact carry. Use a separate real route conversion plus scalar access as the oracle. Check physical nulls, exact ticks, local and UTC calendar bounds. A read unaligned target that restores successfully gets the sub-day refusal. Keep the fixed seed and database, and pin any counterexample in AT-V12.
- **AT-V14** (same file). Layout invariance on plain columns: random internal splits, `combine_chunks`, a record batch and a sliced array give the same decision and count for one checked input. A streaming entry checks each batch independently and stops at its first refusal. Its count can differ from a whole-table count, and the test pins that separately.
- **AT-V15** (same file). For every admitted case of AT-V12 and AT-V14, `check_source_dates(x, table="t", date_read=reads) is x`. Build a 10M-row `date32` and a 10M-row `date64` column (aligned) before measuring. Use one chunk for the aligned date64 field `c`, pass `date_read={"c"}`, and observe lengths at the operation that computes remainders. Require at least one call, total coverage of all 10M rows, and at most 65,536 rows per call, including NumPy operands. Use a fresh Arrow proxy memory pool for the call and assert peak allocation below 1 MiB, including buffers freed before return. Restore the original pool after the measurement. M-72 (a full-length modulo array for the `date64` scan) must fail the operand-length assertion even when NumPy allocates outside the Arrow pool.
- **AT-V16** (`tests/unit/execution/source_dates/test_source_date_route_fingerprint.py`, new). The route-by-fixture table above, through the public entries, with the executed-key count asserted. The 488 keys and final-head mutation kills are implementation gates.
- **AT-V17** (`tests/unit/profile/source_dates/test_whole_file_read_unchanged.py`, replaces the branch's `test_whole_file_gate_q6a.py`). Cases: Hive directory `key=7/part.parquet`, no projection, `columns=["key"]`, `columns=["s.when"]`, a plain directory, and the in-memory S3/GCS whole object. For Arrow-returning reads compare the public rows and full schema, including metadata, with `pq.read_table(path, **same_args)`. For S3/GCS whole-object `to_frame()`, observe the table at the existing #799 conversion call and compare its rows, types and schema metadata with the reference read. These comparisons are green on base. M-49 breaks the Hive key type. A far `date32` in the partition file refuses with the mapping key (red on base).
- **AT-V18** (in `tests/sentry/dates/test_source_date_read_guard.py`). The decision-site rule, with a seeded `raise SourceDateUnrepresentableError(...)` in an in-memory copy of `internal/pandas_compat.py` and an aliased import of the error. `_STOP_AT` is a module constant, it is in `LIMITS`, and its live value equals the `sentry-limits` baseline. The sink census matches post-#799 `pandas_compat.py`.
- **AT-V19** (`tests/unit/execution/source_dates/test_source_date_conversion_unchanged.py`, new). A differential lock, green on base. Build the frames and outputs for the C cells on `origin/main`, record them as literal fixtures in the test, and assert that the head gives the same values, dtypes, index and columns. Include an unread ordered date32 categorical with entries `[2020-01-01, 9999-12-31, 0001-01-01]` and indices `[0, 1]` through the FF frame conversion, with all three ordered categories and codes pinned from base. For each base failure record the exact SHA, input, route and observed outcome.
- **AT-V20** (`tests/unit/io/test_source_date_hold_rule.py`). Generate every unit and listed zone, single and multiple chunks, empty, all-null, populated, near each bound, both bare and writer metadata. Compare the guarded result to an independent populated conversion with the same route options. Exercise scalar access on every non-null and check days, precision and nulls. Test bare and Arrow-backed date64 at −1 ms (FF sibling days 1970-01-01 and 1969-12-31, exact carry −1) and −62135596800001 ms (bare FF 0001-01-01, Arrow-backed scalar access refuses, exact carry preserves the original milliseconds for either footer). A successfully restored unaligned strategy target refuses by kind. Add the three-way date32-cast test in AT-V21. Test actual empty input separately from populated data.
- **AT-V21** (`tests/unit/io/test_source_date_encodings.py`, new). Exercise the structural checker and populated conversion together. For each kind test a strategy input, a materialized sibling and an exact-carry field:
  - `dictionary`: every plain date value type, in-range and far entries, signed and unsigned index widths including `uint64`, one chunk and differing chunk dictionaries, empty and all-null columns. Read: refused with kind and fix sentence, decided before any cell (an empty column refuses too). Unread: `result is data`, and no cell rule runs on it (a far entry is not counted).
  - `pandas_metadata`: each rule 3 comparison on the actual input, with admitted and refused controls. Refused when read, from the Dennis probe: `datetimetz` with zone `America/New_York` over `date32`, over `date64`, over naive `timestamp[us]`, over `int64` and over `string`, and the same with `Asia/Tokyo`; each Parquet-capable case also after a Parquet round trip (`date64` comes back as `date32` and still refuses). Keep each earlier refusal fixture. Use the zoned extension dtype in the Dennis fixtures above and pin the effective type. Cover ArrowDtype unit/zone changes, temporal restores over int64, a datetime entry over a zoned field, and a datetimetz entry changing its zone. Use an explicit naive Arrow timestamp restore to exercise zone removal. Also write an Arrow-backed int64 source to date64 and to timestamp[us] using an explicit schema: restoration to int64[pyarrow] is the date-to-non-date refusal. Keep the datetime-tag/ordinary NumPy control over zoned us when the restore retains UTC. A dtype declaration ignored by the library is a positive control when the structural record is valid and the restored meaning agrees. A stored index field outside a projection is skipped. When restored as an index, guard its actual values. Controls that must admit: `pa.Table.from_pandas` output for naive, zoned and `date` columns and for `timestamp[us][pyarrow]`, `timestamp[ns, tz=America/New_York][pyarrow]` and `date64[ms][pyarrow]` columns, the pandas-written `us` Parquet file, a `string` column of text dates with its writer entry, and a projection that leaves the mismatched field out. Each control records the observed entry in the test as a literal, to identify the fixture. The expected admission comes from the restored meaning.
    Pin the following writer controls with literal expectations for the physical type, metadata triple and restored dtype. Use one unordered category for the categorical fixture.

    | AT-V21 writer input | Physical field | Literal (`pandas_type`, `numpy_type`, `metadata`) | Restored |
    |---|---|---|---|
    | Object column of naive datetimes | `timestamp[us]` | `("datetime", "object", None)` | `datetime64[us]` |
    | Object column of UTC datetimes | `timestamp[us, tz=UTC]` | `("datetimetz", "object", None)` | `datetime64[us, UTC]` |
    | Naive ns datetimes, explicit date32 schema | `date32[day]` | `("date", "datetime64[ns]", None)` | object dates |
    | Naive ns datetimes, explicit UTC us schema | `timestamp[us, tz=UTC]` | `("datetimetz", "datetime64[ns]", None)` | `datetime64[us, UTC]` |
    | NumPy int32 `17000`, explicit date32 schema | `date32[day]` | `("date", "int32", None)` | object dates |
    | NumPy int64 `1704067200000000`, explicit UTC us schema | `timestamp[us, tz=UTC]` | `("datetimetz", "int64", None)` | `datetime64[us, UTC]` |
    | Categorical of pandas timestamps after Parquet | `timestamp[ns]` | `("categorical", "int8", {"num_categories": 1, "ordered": False})` | `datetime64[ns]` |
    | ArrowDtype date64 after Parquet | `date32[day]` | `("date", "date64[ms][pyarrow]", None)` | `date64[ms][pyarrow]` |

    Run both explicit integer controls through public full-frame `date_shift` with a fixed one-day shift. Assert rendered dates `2016-07-19` and `2024-01-02 00:00:00.000000Z`, respectively.

    Add public fixed-one-day FF `date_shift` controls from genuine writers. With NumPy int64 and explicit Arrow schemas, write 2020-01-01 midnight as date64[ms], and noon UTC as timestamp[ms, UTC] and timestamp[us, America/New_York]. Require source admission and the same one-day-shifted output as main. The expected date is January 2 and the two expected instants are noon UTC (07:00 in New York). Record the public rendering on main for each schema. With pandas 2.3.3 `future.infer_string=True`, write ordinary text as large_string. Also read a Fastparquet categorical-text writer fixture (physical string with signed codes and category metadata). Both shift `2020-01-01` to `2020-01-02`. Keep writer controls for ordinary numeric, nullable, boolean, binary, time, duration, decimal, null, date-free nested and categorical non-date fields. Pair the genuine timestamp categorical control with a forged `("categorical", "uint64", None)` and independently corrupt the code signedness and each required category metadata field. Expect kind `pandas_metadata` on read.

    Pair a physical timestamp[us, UTC] at `2024-01-01 00:00:00.123456` with the ordinary zone-free NumPy writer token (restores us, shifts with .123456 intact) and `datetime64[ms, UTC]` (restores ms). The latter must return the source `pandas_metadata` refusal on the public job before strategy use. Pair it with an exactly representable full-second tick: admit when the actual restored instant and zone agree.

    On a physical string field containing `2020-01-01`, the writer control `("unicode", "object", None)` shifts to `2020-01-02`. Change only the triple to `("unicode", "M8[ns, America/New_York]", None)`. Main produced `2020-01-01`; require the public full-frame route to refuse with kind `pandas_metadata` before masking (M-84). Keep the bare, unit-qualified and zoned M8 and datetime64 fixtures. On pandas 2.3.3 / Arrow 24, unzoned NumPy tokens that leave text as object admit and shift to January 2. Both zoned extension forms that restore timestamps refuse. Pin the actual dtypes alongside the literal decisions.

    Two challenging writer/metadata fixtures use (1) `df.to_parquet` of ArrowDtype seconds, physical `timestamp[ms]`, entry `("datetime", "timestamp[s][pyarrow]", None)`, and (2) naive `timestamp[ns]` with `("datetime", "datetime64[ns, America/New_York]", None)`. The changed-zone case refuses. For the seconds writer keep its genuine exact-second values as a positive control. Add a physical millisecond remainder to the same metadata to exercise the refused lossy cast. A parameterized malformed-metadata row supplies invalid JSON and a matching entry missing `numpy_type`; both give the same typed refusal, with empty cause and context. Drive both malformed fixtures through public run_pipeline_isolated with isolate=False and isolate=True as four AT-V21 cases outside the 488 keys. Assert the registered source reason, kind, value-free error and no writer/spawn call. On ISO on assert both peak_rss_mb and pid are None.

  - Calendar day: test time of day at the first row, an interior row between aligned extrema, and hidden storage outside a slice. Exercise FF with a masked sibling and exact carry. Assert the actual day, raw ticks or refusal as specified in AT-V20.
  - Round 3 timestamp: physical timestamp[us, UTC], datetimetz America/New_York, numpy_type="datetime64[us, UTC]". With identical descriptors compare actual empty input, ordinary 2020-01-01 and 2300-01-01. Admit the first two when the returned UTC values agree. The year-2300 intermediate cast fails inside the guard. Assert the typed refusal on FF and on a metadata-restoring batch route with the bad row in batch two.
  - Round 3 date64: attach date32[day][pyarrow] metadata to physical −1 ms. A read target and FF passthrough with a masked sibling both refuse the failed cast as `pandas_metadata`. Pair with an aligned genuine writer (pandas Arrow-backed date32, explicit physical date64 schema), admitted with its original day. Exact-carry the −1 ms field with the same bad metadata and assert identical raw tick, zero restore calls for that field and no restore refusal. Project it out with a valid masked sibling and assert the same zero calls. Compare bare and Arrow-backed controls in AT-V20.
  - Round 3 text: physical string `2020-01-01` with int64[pyarrow] metadata. Test as a date_shift target and windowed_date anchor. Both refuse the populated parse as `pandas_metadata`. Keep the genuine object, inferred-string and categorical writer controls. On FF require the one-day controls to produce `2020-01-02`. On all three failed restores assert the registered typed reason, fixed text, empty cause/context, no quoted input or backend error, and no processing or publication of the failing batch. Run the cases at both supported Arrow test legs.
  - Use (`tests/unit/execution/source_dates/test_date_strategy_columns.py`, part of AT-V21): `date_strategy_columns` returns exactly the `date_shift`, `bucket_perturb` and `windowed_date` anchor columns for a mixed config, and never a `group_by` companion or a hashed, kept, redacted or tokenized column. Rows: a `when:`-gated `date_shift` (in the set); a `nested` entry whose JSON child is `date_shift` (its column not in the set); a provider made composite by the caller registry on an entry with `strategy: date_shift` (excluded, M-83); a `windowed_date` anchor (in the set); a `bucket_perturb` column (in the set); a public FF job with date_shift on `K` and a passthrough date dictionary on `K` (U+212A). Assert the bound set is exactly `{"K"}`, `K` shifts, and `K` matches main. Exercise the same exact-label binding on a windowed_date anchor. Call each of `PandasExecutionAdapter.run` and `run_single` directly with a compiled single-table date_shift plan, its registry and a read date dictionary. Assert the first source check sees the exact target and raises kind `dictionary` before conversion. Bypass the outer pipeline in both tests. No runtime policy expansion exists today. E3 must expand `policy:` before source admission and feed the same config to dispatch. Guard the ordering in `run_pipeline` and seed an expansion after the source check to prove the guard fails. Exercise the M-73 sites independently.
  - Every restore failure also checks the known-name or table-only location. Every message: the literal text of rule 6, no value, empty cause and context.
- **Kept from the branch, unchanged in purpose:** AT-V1 with F-style literal expectations; AT-V3 without the repair and IPC parts; AT-V4, AT-V5 and AT-V7; AT-V8 seeds 1, 2 and 4, plus seed 5 (`from decoy_engine.arrow_frames import arrow_to_frame as conv` on unchecked data) and seed 6 (`arrow_to_series` aliased, on an unchecked column); AT-V9 with the vocabulary `min_max`, `less`, `greater`, `or_`, `and_`, `invert`, `fill_null`, `sum`, `unique`, `is_null`, `divide` and `multiply` on integer views, allowing `cast` only to `pa.int32()` and `pa.int64()`, and excluding `take`, `local_timestamp`, `cumulative_sum` and `dictionary_decode`.
- **Removed:** AT-V6 (repair), AT-V10 (owned date buffers, follow-up G-12), AT-V11 (moved to row DEP-FLOOR). AT-V2 moves to S5b (section 4.4c).

Red-first expectations by route:
- *Main defect on converting routes:* F5 becomes `NaT` at conversion when reached and the F8 scalar read fails. The `Factory` case raises an uncoded resolver error.
- *Contract change, red on main by design:* F5u on NCH and CH passthrough where main returns it (Q8 = A); F2, F3, F9 and F12 on date-strategy reads, plus F11 on reads that actually change the zone (Q9 = A); F4 on every route.
- *Different code on main:* F1 on whole reads that reach the far cell, F10 on bounded profiles, the E3 literal keys on PAN.
- *Locks, green on base:* F3u, F6 (source admission and downstream baseline), F11u when carried or restored with unchanged zone, F12u, the pandas-written metadata and index controls, AT-V17 read and schema comparisons and the AT-V19 differential.
- *E-cell re-pin, both ways:* every E1 to E6 and E3b cell of section 0.1 on its route, with the observed main outcome recorded. A cell moves in either direction as section 0.1 says.

Each mutation runs on the final head (catalog class 9).

#### What the S5 branch keeps and what it discards

**Port method.**
1. Port S5b first (section 4.4c). Build S5a-1a on a fresh branch from main containing #799, #830 and the merged S5b (baseline `395c1c662` or later). Build 1b, 1c and 2 in sequence after 1a.
2. For a file that main and the branch both changed since `9812da814`, re-apply only the S5 hunks by hand. `git diff 9812da814 a5da43ef9 -- <path>` lists them. Never run `git checkout a5da43ef9 -- <path>` on these files, because it would revert #799. The files are: `CODEMAP.md`; `execution/_chunked_profile.py`, `_pandas_adapter.py`, `_pipeline_finalize.py`, `_sequential.py`; `execution/pipeline/_source_types.py`; `internal/pandas_compat.py`; `profile/_cloud_readers.py`, `_readers.py`, `_readers_resident.py`; `tests/native/test_chunked_entry_rev9_shapes.py`, `tests/native/test_chunked_entry_values_schema.py`; `tests/sentry/file_access_registry.toml`; `tests/unit/execution/run_stream/test_lazy_input.py`; `tests/unit/profile/test_supplied_table_profiling.py`.
3. A file that main has not changed since `9812da814` may be taken whole from `a5da43ef9` and then edited as noted. Check with `git diff --quiet 9812da814 origin/main -- <path>`.
4. Do not cherry-pick: the branch's 44 commits mix kept work, discarded work and S5b content.

Kept hunks in the shared files:

| File (both #799 and S5 changed it) | S5a takes | Stays main's |
|---|---|---|
| `execution/_chunked_profile.py` | the check call (empty `date_read`) and the table-name plumbing | the `arrow_to_frame(..., source_column_unrepresentable(table_name))` calls (`:43`, `:170`) |
| `execution/_pandas_adapter.py`, `execution/_sequential.py` | `check_resident_sources` / `checked_loader` wiring, with `date_read` | everything else |
| `profile/_readers.py` | the batch open gate, the one-open sample, the check on `to_table`'s result, the `table` field | every `arrow_to_frame` call (`:417`, `:500`, `:505`) |
| `profile/_cloud_readers.py` | the range-reader schema gate; `check_source_dates` between `pq.read_table` and `arrow_to_frame` at `:272` and `:394` | the reads and conversions |
| `profile/_readers_resident.py` | the `name` field and the check call | the fallback and `arrow_to_frame` at `:20` |
| `internal/pandas_compat.py` and source callers, including `execution/pipeline/_source_types.py` and `execution/_pipeline_finalize.py` | wire the populated guard and reuse at the existing source conversion | options, non-source behavior and unrelated #799 logic |
| `CODEMAP.md` | rows for the new S5a files | the rest |
| `tests/sentry/file_access_registry.toml` | nothing expected; recompute only if the registry test says so | the rest |
| the four shared test files | table name on the lazy copy and date expectations from 4.4a | #799's coded expectations for other types |

Kept and discarded, by area:

| Keep (port, then edit as noted) | Discard |
|---|---|
| `_arrow_types.py` (S5a-1a: date leaf, shape classifier, unclassified layouts and type walker on top of S5b) | `internal/pandas_compat.py` changes: working categorical, `WorkingInstant`, `stored_index_names`, `table_to_pandas`, `_refuse_unholdable` |
| `io/source_dates.py`: schema gate, `_holds_dates`, `checked_batches`, lazy binding, `check_resident_sources`, `checked_loader`. Edit: drop `_repaired_dictionary`, `_without_unused_bad_entries`, `_fixed_offset_seconds`, every dictionary entry test and the row-decoding count; add `date_read`, rules 2 to 4 and the resolver band test; return the input | `safe_output/_date_buffers.py` and its `own_date_*` exports, the `output_table` change and the `execution/chunked/_progress.py` hook |
| `io/bounded_reader.py` errors (message built with `source_location_text`, kind fix sentences), `io/__init__.py` exports, the two reasons in `reasons/runtime/_part3.py` (summary and remediation as above), only the two source-error `reason_adapter._CODED` rows | `fileaccess/adapters/arrow.py` `read_table_gated` and the `pyarrow.dataset` import |
| Entry wiring (S5a-1b and 1c): the parent schema-admission helper in `_isolated_reason.py` with its call site in `_isolated_run.py` on main, plus `_chunked.py`, `_chunked_input.py`, `_isolated_commit.py`, `_isolated_worker.py`, `native/_chunked_entry.py`, `out_of_core/_runner.py`, `execution/_pipeline.py`, and the shared files per the table above | `execution/pipeline/_source_types.py`, `execution/_pipeline_finalize.py`, the branch's `execution/pipeline/_post_scan.py` change: retain #799 logic and add only guarded source wiring where needed |
| Profile: `_lazy_build.py`, `_source.py` (table name), and the shared profile files per the table above | `profile/_readers_resident.py` fallback rewrite |
| `fileaccess/adapters/arrow.py` walker move and `projected_schema` | `safe_output/_file_metadata.py` optional list-view rows and their tests (move to row DEP-FLOOR) |
| `tests/native/_rev9_support.py`, `tests/native/_rev9_profile_cases.py`, `tests/native/test_unconfigured_passthrough_types.py`: keep the admitted-edge coverage and apply 4.4a to every refused carrier. Keep `tests/native/test_unconfigured_passthrough_read.py` and `tests/unit/execution/test_full_frame_value_unrepresentable.py` for the claims in 4.4a | the branch's dictionary repair and dictionary entry tests that rule 2 makes moot |
| `tests/native/test_column_access_surfaces.py`: include the new `check_resident_sources` call in the adapter guard. `tests/unit/profiling/test_scan_set.py`: forward `**kwargs` through the spy | |
| Tests in `tests/unit/io/`: `test_source_date_type_gate.py`, `test_source_date_shape_classifier.py`, `test_source_date_nested_refusal_q6a.py`, `test_source_dates_vocabulary.py`, `test_checked_source_dates.py` (dictionary cases rewritten per 4.4a; in `test_date64_edges` retain the upper and aligned bounds and replace the unconditional lower-edge refusal with the read/unread and bare/Arrow-backed outcomes from rule 4; in `test_nanosecond_timestamps_cannot_leave_the_calendar` split the ticks: non-null INT64_MIN refuses, count 1, including unread, while INT64_MIN + 1 and INT64_MAX admit), `test_source_dates_fixed_offset.py` (port cases to AT-V12). In the new sub-package `tests/unit/execution/source_dates/` (moved from `tests/unit/execution/` on the branch): `test_source_date_nested_routes_q6a.py`, `test_source_date_type_routes.py`, `test_source_date_unrepresentable.py`. Keep `test_source_type_gate_projection_q6a.py`, moved to the new `tests/unit/profile/source_dates/` | `tests/unit/internal/test_working_categorical.py`, `test_no_import_time_timestamps.py`, `tests/unit/safe_output/test_date_buffers_ipc.py`, `tests/unit/profile/test_resident_fallback_dates.py`, `test_whole_file_gate_q6a.py` (replaced by AT-V17), `tests/unit/execution/test_source_date_reports_r1.py` (replaced by AT-V19), and `tests/sentry/test_signed_evidence_file_access.py` (main's file stays) |
| `test_source_date_read_guard.py`, moved from `tests/sentry/` on the branch to the new `tests/sentry/dates/`, with main's sinks, `_STOP_AT` measured and registered, and the decision-site rule | the bare-statement rule in the read sentry (old M-29) |
| `_execution_error.py`: extract `source_location_text` (about 10 lines) | |
| Docs: `docs/strategies.md` S5 paragraph (section 4.7), CODEMAP rows, `changelog.d/date-range-s5-source-dates.md` listing E1 to E6 with E3b, the Q8 x Q9 asymmetry, and the Q8 = A passthrough narrowings | |

New code on main, listed separately in the builder report: the structural footer reader in `_pandas_meta/_columns.py` and populated guard in the #799 conversion boundary, `date_strategy_columns` and `DATE_STRATEGIES` in `execution/_column_access.py`, the pre-declaration helper in `_isolated_reason.py`, AT-V21 and the hunks re-applied onto the #799-shared files. In the builder report, compare the path list from `git diff --name-only 9812da814 a5da43ef9` (75 files) with the paths assigned above and in section 4.4c. Give each path a disposition (keep, discard or S5b) and identify the hunks for mixed files. Resolve any missing disposition before porting.

#### Size and slices

Each PR permits at most 799 new-for-review lines. Split wiring by route. Keep the tests of each route with its first production caller. The following are planning estimates. Measure each actual diff by the accounting rule below.

Revision 10 counted only new lines against that cap and gave S5a-1 about 600, but the S5a-1 diff was about 2,600 changed lines. Review rounds 3 to 6 passed the ported code on a pre-#799 base. Files taken whole from `a5da43ef9` are reviewed as a port diff against that commit and are listed separately below. The hunks re-applied by hand onto the 15 files that #799 also changed are different: `git diff 9812da814 a5da43ef9` on those paths is 384 insertions and 176 deletions, and they sit in #799's new code. The estimate counts the retained hunks as new for review, so S5a-1 splits in two.

| Slice | Content | Taken whole from `a5da43ef9` | New for review (new code plus re-applied hunks) | Estimate |
|---|---|---|---|---|
| S5a-1a | Physical type and structural gate, both reasons, changelog, adapter rows, classifier, shared populated guard and direct AT-V3/V9/V21 writer/refusal controls | about 900 | 680 including comparison and guarded converter tests | one day |
| S5a-1b | Resident, loader, FF/PAN and ISO wiring, shared seed extraction, re-use, pre-declaration check, paired AT-V21 public jobs, associated AT-V3/V16 keys and adapter/ordering sentries | part of the 1,100 wiring port | 560 including re-applied shared hunks | one day |
| S5a-1c | Streaming, native, profile, cloud and Hive wiring, late failure and exact-carry controls, remaining wiring hunks, AT-V4/V5/V7/V8/V17/V18, remaining type/encoding keys of AT-V16, isolation/metadata controls and E-cell re-pin | balance of wiring port | 610 including route guards | one day |
| S5a-2 | Rule 5 domain, resolver and count, AT-V1/V12–V15/V19/V20, 4.4a edits and remaining AT-V16 keys, including all four PAN/NCH Factory empty/all-null keys | about 700 | 710 | one day |

S5a-1a has only test callers. Its new IO exports default to INTERNAL and main has no unused-export gate. Its two pending reasons do trigger `test_every_live_pending_identity_is_named_by_a_fragment`: ship `changelog.d/date-range-s5-source-dates.md` in S5a-1a with the exact code spans `runtime/source_date_unrepresentable` and `runtime/source_date_type_unsupported` and the statement “not raised by any route yet”. S5a-1b extends that fragment for the resident routes, and 1c documents the remaining routes. S5a-2 extends it again for the cell rules.

Measure the touched modules on each head. The ISO staging helper goes in `_isolated_reason.py`, and `_isolated_run.py` stays at or under 600 lines (see "Isolation"). `_column_access.py` stays under 600. Keep the current ceilings and pins. One bound row is added, `_STOP_AT`, at its measured value. For each implementation PR measure inserted plus deleted lines on its actual base-to-head diff. Exclude only unchanged whole-file port content and charge subsequent edits against the port head. Count shared-file hunks reapplied on main in full. At 800 or more new-for-review lines, the builder stops and reports before splitting further. The builder report gives the real diff size of each PR, taken whole and new for review separately.

#### What is not S5

| Item | Where it goes | Why not S5 |
|---|---|---|
| The output assembler mixes pandas display labels with Arrow field names. Integer or tuple column labels raise `IndexError` or `TypeError` during passthrough assembly (`execution/pipeline/_source_types.py`, round 6) | Row ASSEMBLER-LABELS (engine, V1 function break, R2, about half a day): map source-backed display labels to physical fields by position; tests with integer, tuple and duplicate-looking labels on FF passthrough | Reproduces on main with ordinary integer data; S5 no longer touches the assembler |
| Two resolvers read the stored index from pandas metadata (`execution/pipeline/_source_types.py` and `_pandas_meta/_columns.py` `stored_index_fields`) | The structure review list, or folded into ASSEMBLER-LABELS | Pre-existing duplication |
| The engine does not import at the declared floors: pyarrow 14 (unconditional list-view predicate, `safe_output/_file_metadata.py`) and pandas 1.5.3 (`validators/_dates.py:13`) | Row DEP-FLOOR (engine, R2): raise the declared pandas floor to 2.x (Q7 = A), optional list-view rows and `test_import_floor.py`, exact-version CI legs that also run AT-V13 and AT-V20 | Pre-existing on main; independent of dates |
| Disjoint dictionary union in carried profile and AUTO join | G-16 (log) | Separate from conversion. G-17 moves into the S5a populated guard. |
| Hidden storage outside a slice is serialized when a caller writes a returned passthrough table to IPC (all types) | G-12, V2-LOG | The caller's own data returned to the caller |
| A Parquet file Arrow cannot decode fails with Arrow's error before the type refusal | G-14, log | Pre-existing; the read is main's read |
| The resident profile fallback rebuild drops a stored index (round 5) | G-15, log | Pre-existing |

### 4.4c S5b slice: fitted distribution admission (independent, buildable now)

**Goal.** A fitted datetime snapshot that a fitted generator cannot compute, or whose live year bins lie outside its own fitted years, is refused before any draw with `plan/generation_unbounded_column`, value-free. Working statistical and parametric jobs keep working.

**Two generators, two rules.**
- The *fitted sampler* `_generate_distribution_datetime` (`generators/_distribution.py`) is reached only through the legacy `ColumnGenerator.generate_column(n, {"type": "distribution", "snapshot": ...})`. It has no plan compile path. A V2 config with `type: distribution` goes to the parametric family through `generation/synthesize._generate_column` and never reaches it. Its bounds must lie in the ns range, 1677-09-22 to 2262-04-10, and since revision 11 every live year bin must lie inside the fitted years, from the min bound's year to the max bound's year (`contracts/calendar_range.py`, `admit_ns_datetime_snapshot`, Fix 3). It refuses with `FittedRangeError(prop=...)`, where `prop` is `"min"`, `"max"` or `"year_bins"`.
- The *statistical generator* samples from live year bins (`count > 0`). Its rule is `SAMPLED_YEARS_RULE` (years 1 to 9998, `contracts/distribution_snapshot.py`). Fitted bounds outside the ns range are fine for it, because draws come from the bins. `check_degenerate` and `_window_admission._check_datetime` both apply the live-bin rule.

**Fix 1 (r3 V1: AT-V2 pinned on the wrong generator).** The branch fixture `FAR` (max 9999-12-31 and a live 9999 bin) could pass on either check alone. Rewrite AT-V2 as two groups (below), with three independent fitted-sampler refusals that each carry one fault, and no 9999 bin in any fitted-sampler fixture.

**Fix 2 (r3 DESIGN: two renderings of the sampled-year rule).** `_degenerate.py:176` on the branch raises `StatisticalSpecError(message="sampled years must lie in 1..9998")`, a second literal beside `SAMPLED_YEARS_RULE`. Replace it with the sentry-approved builder:

```python
refusal = config_refusal(
    config_position("statistical", Name(spec.column)),
    Problem.NOT_ALLOWED,
    hint=SAMPLED_YEARS_RULE,
)
raise StatisticalSpecError(code=reasons.plan.GENERATION_UNBOUNDED_COLUMN, message=refusal.text)
```

This is the pattern `withheld_values_refusal` uses. It passes the config-refusal sentry (`tests/sentry/defects/_config_refusal_scan.py`): S1 accepts a message from a `Refusal` builder field, and S2 accepts `hint` as an UPPER constant imported from another module. No new baseline entry. Plan compile already rebuilds the error through `statistical_refusal(code, ...)` (`plan/_generation.py:145`, `:520`) with the registry summary, so the builder text appears only on direct `check_degenerate` calls. `_window_admission` keeps its own message, `f"{table}.{column}: {SAMPLED_YEARS_RULE}"`. Both messages take the rule from the one constant.

**Fix 3 (Dennis r1 of revision 10, S5b-M1: what the live-bin rule is for).** The branch refuses a live bin outside the ns years 1677 to 2262. The ported sampler can compute such a bin: it caps years to the max year and clips day numbers to the ns domain (`np.minimum(years_arr, max_year)`, `np.clip(...)`), which is the clamp QA F7 (2026-06-01) made on purpose. The branch rule is also not a consistency rule: a live 1000 bin under 2020 bounds is refused, but a live 1700 bin under the same bounds is admitted and puts every row on the min instant (`bad = hi_ns <= lo_ns`). Revision 11 takes Dennis's option (b): for ordered bounds a live bin must lie inside [min year, max year]. That is the integrity rule of a fitted snapshot. Real fits never trip it, because profiling writes min, max and year bins from the same values. Only hand-built or inconsistent snapshots reach it, and for those the clamp gave a wrong distribution with no notice. Because the bounds are checked first, a bin inside the fitted years is also inside the ns years, so the ns-year bin check goes away.
- In `admit_ns_datetime_snapshot`, after both bounds pass and only when `min_ns <= max_ns`, take the min and max years from the admitted ns bounds with integer day arithmetic (`date.fromordinal`, no pandas), and raise `FittedRangeError(prop="year_bins")` when a live year lies outside them. About 10 lines on top of the file taken whole. For inverted bounds leave the sampler’s existing warning and NaT path intact.
- The `year_bins` message names its own rule: `"[generation_unbounded_column] year_bins: a live year bin must lie between the fitted min and max years."` The `min` and `max` messages stay `"[generation_unbounded_column] <prop>: a fitted datetime must lie in 1677-09-22 to 2262-04-10."`. AT-V2a asserts exact str(exc) separately from reason_from_exception(exc), whose namespace and code are plan/generation_unbounded_column.
- QA F7 is reversed: main clamps a live 9999 bin under 2026 bounds, and S5b refuses it with `year_bins`. This is a behavior change on `ColumnGenerator.generate_column`, which the SDK can reach, and the changelog names it (Files table).

**Files.**

| File | Change |
|---|---|
| `src/decoy_engine/contracts/calendar_range.py` | new, 139 lines, taken whole from `a5da43ef9`, then Fix 3 (about 10 lines) |
| `src/decoy_engine/contracts/distribution_snapshot.py` | `SAMPLED_YEARS_RULE` (one hunk) |
| `src/decoy_engine/generators/_distribution.py` | admission before any draw. Remove the dead `np.minimum(years_arr, max_year)` clamp and its stale past-max comment; keep the day-number clip |
| `src/decoy_engine/generation/_window_admission.py` | uses `SAMPLED_YEARS_RULE` and `names_far_year`, taken whole |
| `src/decoy_engine/generation/statistical/__init__.py` | export, taken whole |
| `src/decoy_engine/generation/statistical/_degenerate.py` | taken from the branch, then Fix 2 (about 10 lines) |
| `src/decoy_engine/reason_adapter.py` | only the row `("decoy_engine.contracts.calendar_range", "FittedRangeError", "plan")` |
| `src/decoy_engine/_arrow_types.py` | only the two calendar day-number definitions at `a5da43ef9:src/decoy_engine/_arrow_types.py:23-24` |
| `src/decoy_engine/verification/canary/_canonical.py` | import those definitions in place of the literal pair at `:42` |
| `tests/unit/generators/test_distribution_datetime_range.py` | rewritten fixtures (AT-V2a) |
| `tests/unit/generation/statistical/test_date_range_compile_routes.py` | moved from `tests/unit/generation/` on the branch (40 flat modules there; the named sub-package has 13); rewritten fixtures (AT-V2b) and the parametric control, which is at `test_date_range_compile_routes.py:67` on the branch |
| `tests/unit/generators/test_columns_qa1.py` | QA F7: a live 9999 bin with 2026 bounds now refuses (`year_bins`, Fix 3) before any draw. Update the F7 class and test docstrings to describe this refusal |
| `tests/unit/generators/test_distribution_samplers.py` | F7-class reversals: `test_year_beyond_max_is_capped_into_bounds` and `test_year_below_min_clamps_to_min` now expect `FittedRangeError`, `prop == "year_bins"` and no draw. Keep `test_max_before_min_emits_nat` unchanged |
| `tests/sentry/generation/test_sampled_years_rule_single_rendering.py` | new guard, in the named sub-package for generation choke points (5 modules) and not in the flat `tests/sentry/` (101 modules) |
| `CODEMAP.md` | the `contracts/` row lists `calendar_range.py`; the `tests/sentry/generation/` row (CODEMAP.md:177) names the new guard. Hunks only, because #799 changed this file |
| `changelog.d/date-range-s5b-fitted-admission.md` | names `plan/generation_unbounded_column` for the fitted sampler (main: uncoded `OverflowError`, `OutOfBoundsDatetime` or `ValueError`); the QA F7 reversal as a behavior change on `ColumnGenerator.generate_column`: a live year bin outside the fitted min and max years now refuses, where main clamped it or put every row on the min instant; and the statistical change: plan compile and `sample_column` (through `check_degenerate`, `_sample.py:436`) now refuse a live bin past 9998 with `plan/generation_unbounded_column`, where main failed at draw time with an uncoded `ValueError` (`_sample.py:501`) |
| `docs/strategies.md` | one sentence on the fitted sampler's range (section 4.7) |

#799 changed none of these files except `CODEMAP.md`, where S5b adds its two row edits by hand. Check each other file with `git diff --quiet 9812da814 origin/main -- <path>` before taking it whole. For the registry row and the two constant hunks, take only the named hunks. Verify one definition of each calendar endpoint on the S5b head.

**Size.** About 600 ported lines (about 300 source, 300 tests) plus about 20 new source lines (Fix 2 and Fix 3) and about 160 new or changed test lines. Half a day with review. R2. Test depth: T1 plus the T2 gate set, and the config-refusal sentry and `tests/unit/test_reason_registry.py` in T1.

**Tests (red-first).**
- **AT-V2a, fitted sampler** (`test_distribution_datetime_range.py`). Each fixture has one fault. Before the sampler runs, the test checks that the snapshot validator accepts the fixture, so the refusal comes from the admission under test: `decode_datetime_buckets(SCHEMA_VERSION_V1, stats)` returns, and `datetime.fromisoformat` reads both bounds. If the validator refuses a fixture, the builder records it and changes the fixture, not the expectation:
  - max far: min 2020-01-01, max 9999-12-31, bins `[2020: 5]`. Expect `FittedRangeError`, `prop == "max"`.
  - min far: min 0001-01-01, max 2020-12-31, bins `[2020: 5]`. Expect `prop == "min"`.
  - live bin late: min 2020-01-01, max 2020-12-31, bins `[2020: 5, 2021: 3]`. Expect `prop == "year_bins"`.
  - live bin early: the same 2020 bounds with sorted bins `[1700: 3, 2020: 5]`. Expect `prop == "year_bins"`. Both bins lie inside the ns years, so only the Fix 3 rule refuses them (M-75).

  For each: `exc.code == "generation_unbounded_column"`; `reason_from_exception(exc)` gives namespace `plan` and that code (public identity `plan/generation_unbounded_column`), so removing the `_CODED` row fails even though the exception keeps its code; the message equals the literal for its `prop` (Fix 3); no fixture year (`9999`, `0001`, `2020`, `2021`, `1700`) appears in `str` or `repr`; empty cause and context; a spy on the draw, the `np.random.default_rng(...).choice` call in `_generate_distribution_datetime`, records no call. No fixture has a 9999 bin, so a bin-only check cannot pass the two bound fixtures, and a bounds-only check cannot pass the two bin fixtures.
  - Controls: min 1677-09-22, max 2262-04-10, bins `[1677: 2, 2262: 2]` draws inside the bounds (valid partial years at each ns edge, and bins equal to the min and max years). A zero-weight 2021 bin under 2020 bounds is not live and does not refuse.
  - Parametric control (kept): a V2 config `type: distribution` column generates, and a spy shows `_generate_distribution_datetime` is never reached.
- **AT-V2b, statistical rule** (`test_date_range_compile_routes.py`):
  - refusal: min 2020-01-01, max 2020-12-31, bins `[2020: 5, 9999: 3]`. `check_degenerate` raises `StatisticalSpecError` whose message equals the literal `"statistical.c: not allowed. sampled years must lie in 1..9998"`. The builder renders it once with `config_refusal`, pins the literal, and records it in the report. `classify_window_table` raises `GenerationAdmissionError` with message `"t.c: sampled years must lie in 1..9998"`. Plan compile reports `plan/generation_unbounded_column`. Both messages contain `SAMPLED_YEARS_RULE`, and neither has a value from the snapshot outside the rule.
  - controls that must pass `check_degenerate` and `classify_window_table`, then draw 20 rows with a fixed seed, all in 2020: max 9999-12-31 with bins `[2020: 5]`; min 0001-01-01 with bins `[2020: 5]`; a zero-weight 9999 bin (kept). These lock that working statistical jobs are not narrowed. Green on base expected; record the base outcome.
- **Single-rendering guard** (`tests/sentry/generation/test_sampled_years_rule_single_rendering.py`). An AST scan of `src/decoy_engine`: a string constant containing `sampled years must lie` or `a sampled year is outside`, an integer or string literal `9998`, and an f-string (`JoinedStr`) that formats both `MIN_YEAR` and `MAX_SAMPLED_YEAR` appear only in `contracts/distribution_snapshot.py`. The guard's own test seeds each shape in an in-memory module, including main's second rendering `f"a sampled year is outside {MIN_YEAR}..{MAX_SAMPLED_YEAR}"` (`_window_admission.py:156`), which has neither the first phrase nor a literal `9998`. Red on `a5da43ef9` (the literal at `_degenerate.py:176`). The config-refusal sentry stays green with no baseline change.
- Red on main: record the observed main outcome for each AT-V2a fixture and for the AT-V2b refusal. Expected on pandas 2.3.3: for the far bounds, an uncoded `OverflowError` ("Cannot convert Timestamp to nanoseconds without overflow"), because pandas parses `9999-12-31` and `0001-01-01` at unit `s` and `.value` overflows, or an `OutOfBoundsDatetime` or `ValueError` quoting a date; for the bin fixtures, a draw (the clamp or the min instant). For AT-V2b, an uncoded `ValueError` at draw time. A different failure is recorded as such, never relabelled as the expected red.

**Mutations.** M-58 to M-64, M-75 and M-81 in section 7.

### 4.5 Placement

| Item | Place | Why |
|---|---|---|
| `DateDomain`, `DatePartition`, `DateRangeError`, range table | `transforms/date_preserve.py` (275 lines today, about 400 after) | `transforms/` is at its fan-out limit (CODEMAP "Transforms" row); the matching code it extends is already here |
| New reason | `reasons/runtime/_part3.py`, new `_catalog.runtime("DateRangeError")` binding | runtime reason home; `_part3.py` is 553 lines |
| Coded family row | `reason_adapter.py:44-70` `_CODED`: `("decoy_engine.transforms.date_preserve", "DateRangeError", "runtime")`, the defining module | without it the adapter and isolated-child classification report the refusal uncoded; `tests/unit/test_reason_registry.py:198-218` already checks every row resolves and gains a case that `reason_from_exception(DateRangeError(...))` returns the new code |
| S5 source boundary | Existing `io/bounded_reader.py` (CODEMAP.md:129), public checked Arrow reader API exported by `decoy_engine.io`. Error `SourceDateUnrepresentableError` in `io/bounded_reader.py:106`, code in `reasons/runtime/_part3.py`, adapter row `("decoy_engine.io.bounded_reader", "SourceDateUnrepresentableError", "runtime")` at `reason_adapter.py:57` | Profile and run readers may both import io under `.importlinter:22-25` |
| S5 shared type walker (4.4b) | `type_children` and `type_nodes` move from `fileaccess/adapters/arrow.py:150-169` to the bottom-tier `decoy_engine/_arrow_types.py` (254 lines on main), which `io/source_dates.py` already imports; `fileaccess/adapters/arrow.py` imports them back | one copy of Arrow's nesting rules for the file-access type checks and the date gate; both consumers already import the bottom tier, and the date gate is not file access, so it does not belong in `fileaccess`. `_array_children` and `_walk` stay in `fileaccess/adapters/arrow.py:172-190` and zip with the moved `type_children` order: use `strict=True` at line 189 wherever `_array_children` is not empty, and add a `tests/unit/test_arrow_types.py` case that pins `type_children` for each kind (extension, dictionary, map, struct, union, list kinds, list views, run-end-encoded) |
| S5 type gate and holdable rule (4.4b) | `SourceDateTypeUnsupportedError` beside `SourceDateUnrepresentableError` in `io/bounded_reader.py`; reason in `reasons/runtime/_part3.py`; adapter row `("decoy_engine.io.bounded_reader", "SourceDateTypeUnsupportedError", "runtime")`; gate, holdable rule and lazy binding in `io/source_dates.py` (about 290 lines) | the existing error and check live there; no new module |
| S5 rule tests (4.4b, revision 5) | `tests/unit/io/test_source_date_hold_rule.py` (AT-V12 to AT-V15, AT-V20), `tests/unit/io/test_source_date_encodings.py` (AT-V21), `tests/unit/execution/source_dates/test_date_strategy_columns.py` (AT-V21 use rows), `tests/unit/execution/source_dates/test_source_date_route_fingerprint.py` (AT-V16), `tests/unit/profile/source_dates/test_whole_file_read_unchanged.py` (AT-V17), `tests/unit/execution/source_dates/test_source_date_conversion_unchanged.py` (AT-V19) | `tests/unit/io/` has 3 modules, so the io tests stay flat. `tests/unit/execution/` (266 modules) and `tests/unit/profile/` (37) are over the 25-module rule (owner 2026-11-06), so the route tests go in new named sub-packages (next row) |
| New test sub-packages (revision 11, Dennis S5a-H3 and S5b-H1) | `tests/sentry/dates/` (the read guard and the S1 date partition sentry), `tests/unit/execution/source_dates/`, `tests/unit/profile/source_dates/`, `tests/parity/date_range/` (S1, 162 flat modules in `tests/parity/`), `tests/unit/transforms/date_domain/` (S1, 26 flat modules). S5b uses the existing `tests/sentry/generation/` and `tests/unit/generation/statistical/` | each new sub-package gets an `__init__.py` and a CODEMAP row in the slice that creates it, as `tests/sentry/generation/` has (CODEMAP.md:177). No new module goes in a flat folder over 25 modules |
| Use set | `date_strategy_columns` and `DATE_STRATEGIES` in `execution/_column_access.py` (544 lines, about 580 after) | the one declaration of which columns each entry reads; `execution/` is frozen at 102 modules |
| S5b fitted range | `contracts/calendar_range.py` (new, about 150 lines), CODEMAP `contracts/` row | the contracts tier holds the snapshot rules; imports `errors`, `reasons` and `_arrow_types`, all lower tiers |
| S5 read guard (4.4b) | `tests/sentry/dates/test_source_date_read_guard.py` (on the branch at `tests/sentry/`, first split out of `test_source_date_unrepresentable.py`) | a named sentry sub-package for date choke points, with its CODEMAP row |
| S5 type tests (4.4b) | `tests/unit/io/test_checked_source_dates.py` for the unit cases; route cases in `tests/unit/execution/source_dates/test_source_date_unrepresentable.py` | the existing S5 test homes |
| User docs | `docs/strategies.md` (date strategies, `preserve_values`), `docs/reasons.md` generated entries, `changelog.d/` fragments | section 4.7 |
| Sentry | `tests/sentry/dates/test_date_partition_choke_point.py` | the date choke-point sentry sub-package, with the S5 read guard |
| Route matrix | `tests/parity/date_range/test_date_range_sentinel.py` | a sub-package of the D1c suites' folder, importing `tests.parity._d1c_data` |
| Domain unit tests | `tests/unit/transforms/date_domain/test_date_domain.py` | per-module unit home in a named sub-package |

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
- S5 documents which source columns are read: plain date and timestamp columns on every route, judged by one rule (Q8 = A). A column holding a date inside a list, map, struct or other container is refused with `runtime/source_date_type_unsupported` whatever its dates are, with the remedy (drop, select out or cast the column). A date strategy can still read text dates with ordinary writer metadata. For a date-strategy target or window anchor, a date dictionary, malformed or date-changing pandas metadata (rule 3), or a `date64` with a time of day is refused with its kind and the fix "cast it to a plain date or timestamp column". Document which fields the route materializes: a restored sibling is guarded, and an exact-carry sibling bypasses rules 3–4. It states the Q8 x Q9 asymmetry in plain words: a far plain date is refused on every column, but the same far date in a dictionary on an exact-carry column is carried as before (section 0.2). It names the `ns` and zoned limits in plain words, and it lists E1 to E6 and E3b from section 0 and the Q8 = A passthrough narrowings (comparison rows 8, 9, 13 and 14 for plain cells, Appendix B.1). Under Q8 = A a zone must resolve even on an empty or all-null column. It replaces `docs/strategies.md:403-405`. S5b adds one sentence: the legacy fitted distribution sampler refuses a fitted bound outside 1677-09-22 to 2262-04-10, or a live year bin outside its fitted min and max years, with `plan/generation_unbounded_column`. Both the S5a changelog and `docs/strategies.md` give the two ordinary Parquet writer examples in E4 (seconds stored at ms and ns coerced to us).
- In S5a update #799's paragraph on `run_mask_chunked` and `run_mask_pipeline_chunked` in `docs/compatibility-contract.md`.
  The date check can raise `SourceDateUnrepresentableError` (`runtime/source_date_unrepresentable`) or
  `SourceDateTypeUnsupportedError` (`runtime/source_date_type_unsupported`) at the source or guarded conversion boundary, including on NCH
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
| a date inside a list, map, struct, list view, run-end-encoded, union or extension column, or a dictionary of a container (S5, 4.4b) | passes, or an uncoded Arrow error, or a hidden far value reaches output | refusal `runtime/source_date_type_unsupported` naming table, column and container kind, in or out of the calendar (Q6) |
| a date dictionary, malformed or date-changing pandas metadata (rule 3), or a `date64` with a time of day on a column a date strategy reads (S5, Q9 = A) | the strategy receives a converted column, or a coded or value-bearing conversion error (E1 to E6, E3b) | refusal `runtime/source_date_type_unsupported` with kind `dictionary`, `pandas_metadata` or `date64_time_of_day` and the fix sentence |
| the same encodings on a column no date strategy reads (S5, Q9 = A) | main's behavior | exact carry preserves admitted Arrow values. Actual sibling restores follow rules 3–4 |
| plain far date on NCH passthrough (S5, Q8 = A) | returned exactly | refusal `runtime/source_date_unrepresentable` |
| `LazySource` without `table=` in `sources` (S5, 4.4b) | refusal names table `source` | refusal names the mapping key |
| legacy fitted distribution sampler with a far bound, or a live year bin outside the fitted min and max years (S5b) | far bound: uncoded `OverflowError`, or `OutOfBoundsDatetime` or `ValueError` quoting a date; outside bin: a clamp (QA F7) or every row on the min instant | `plan/generation_unbounded_column`, value-free, `prop` on the typed error |
| statistical generation with a live year bin past 9998 (S5b) | uncoded `ValueError` at draw time (`_sample.py:501`); the builder records the observed outcome | `plan/generation_unbounded_column` at plan compile and in `sample_column`, before any draw; far fitted bounds with only ordinary live bins still generate |
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

- AT-V1: place an unrepresentable date32 at row 10,001 in a later Parquet row group. Run FF, AUTO, SEQ, CH, NCH, OOC and ISO with an ordinary first 10,000 rows. Also exercise a first-batch profile failure, a resident table, a caller loader, opened batches and direct OOC. Assert runtime/source_date_unrepresentable, correct table and column, the batch count on the typed exception, exact names-only rendered text, no year in the error, log or child result, empty cause and context. Use the bounded-head, raw iterator prefix and transactional abort assertions in AT-V16. Compare counts inside one checked table or at the first refusing batch on a stream. Cover both ends for date32/date64 and each timestamp unit where such values exist, null-only batches, valid calendar endpoints and a timezone offset crossing a calendar endpoint.
- AT-V2: moved to S5b and rewritten in revision 10. See AT-V2a (fitted sampler, three independent faults, `prop` asserted, no 9999 bin) and AT-V2b (statistical live-bin rule with positive controls) in section 4.4c.

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
- AT-V8 (DESIGN). Run each of the five active seeds (1, 2, 4, 5 and 6) in section 4.4b separately through the scanner, asserting the exact offending caller. For seed 6 remove only the series sink and verify that the bypass goes undetected before restoring the sink. Check aliased imports and a stale allowance. The clean source inventory passes. Red first: the old file exemption misses seed 1, the old guard misses seed 2, and the round-one finite sink set misses seed 4, whose call to `walk_one_table` reaches a year-bearing pandas conversion on the reference. Kill M-36 even after the original three seeds pass.
- AT-V9 (rule 3 of 4.4b). An `ast` test over `io/source_dates.py` fails on any `pc.` call or attribute outside the allowlist and on any import outside the allowed modules. Reject `take` everywhere (seed direct and aliased calls) and enforce the integer-view `cast` rules in section 4.4b, including aliased calls. A seeded `pc.list_flatten(column)` and a seeded `.storage` each fail it. A unit test calls the counting function with a `list<date32>` column and expects the internal error. Red: the S5 head uses `.keys`, `.items`, `.flatten()` and `pc.list_flatten`, and counts the list instead of raising.
- AT-V10: removed in revision 5 (S5 no longer owns returned date buffers; follow-up G-12).
- AT-V11: moved to row DEP-FLOOR (section 14). The import floor is pre-existing and independent of dates.
- AT-V12 to AT-V21: specified in section 4.4b (rule, layout, purity, route fingerprint, reads unchanged, decision site and `_STOP_AT`, conversion unchanged).

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
- S5b QA F7 in `test_columns_qa1.py` and its two F7-class reversals in `tests/unit/generators/test_distribution_samplers.py`: `test_year_beyond_max_is_capped_into_bounds` and `test_year_below_min_clamps_to_min`. The F7 cap, the 2200 bin capped to 2024 and the 2010 bin clamped to the minimum all become `FittedRangeError` with `prop == "year_bins"` before any draw.

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
| M-43 | Retired in revision 10 (Q9 = A: no dictionary entry rule). Appendix B.5 lists it under B | |
| M-44 | Retired in revision 10 (Q9 = A). Appendix B.5 lists it under B | |
| M-45 | S5: the check returns a rebuilt table | AT-V15 |
| M-46 | S5: remove the check from one chunked entry (`run_mask_chunked`, then separately `run_mask_pipeline_chunked`) | AT-V16 NCH or CH, AT-V8 |
| M-47 | S5: skip `check_resident_sources` in `PandasExecutionAdapter.run` | AT-V16 PAN |
| M-48 | S5: add a second check that raises `SourceDateUnrepresentableError` in `internal/pandas_compat.py` | AT-V18 decision-site rule |
| M-49 | S5: reintroduce a dataset scanner for whole-file reads | AT-V17 Hive key type |
| M-50 | Retired in revision 10 (Q9 = A: unread dictionaries are main's conversion, covered by M-66) | |
| M-51 | S5: raise `_STOP_AT` by one above the measured count | the `sentry-limits` ratchet test |
| M-52 | S5: inline the measured literal again in place of `_STOP_AT` | AT-V18 and the bound census |
| M-53 | S5: compute the band offset with `zoneinfo.ZoneInfo(zone)` instead of pyarrow's resolver | AT-V12 Sydney and Auckland rows, AT-V13, AT-V20, F8 |
| M-54 | Retired in revision 10 (Q9 = A: a read date dictionary refuses by kind, covered by M-65) | |
| M-55 | Retired in revision 10 (Q9 = A: the check never sees dictionary rows). Appendix B.5 lists it under B | |
| M-57 | Retired in revision 10 (Q9 = A: no parent dictionary scan). Appendix B.5 lists it under B | |
| M-56 | S5: drop `arrow_to_series` from the read sentry's sink set | AT-V8 seed 6 and the sink census in AT-V18 |
| M-58 | S5b: re-inline the literal `"sampled years must lie in 1..9998"` in `_degenerate.py` | single-rendering guard |
| M-59 | S5b: the fitted admission drops its `min` and `max` checks and keeps the bin check | AT-V2a max-far and min-far |
| M-60 | S5b: the fitted admission drops its live-bin check | AT-V2a live bin late and early (the draw spy records a call) |
| M-61 | S5b: `FittedRangeError` always reports `prop="max"` | AT-V2a `prop` assertions |
| M-62 | S5b: remove the `FittedRangeError` row from `_CODED` | AT-V2a `reason_from_exception` assertion |
| M-63 | S5b: the statistical rule checks fitted bounds instead of live bins | AT-V2b refusal and both bound controls |
| M-64 | S5b: the statistical rule counts zero-weight bins | AT-V2b zero-weight control |
| M-75 | S5b: the live-bin check uses the ns years 1677 to 2262 in place of the fitted min and max years (the branch rule) | AT-V2a live bin late (2021) and early (1700) |
| M-65 | S5a: refuse a read date dictionary only when an entry fails the cell rule | AT-V21 in-range dictionary, AT-V16 F3 |
| M-66 | S5a: judge the cells of an unread exotic field instead of skipping it | AT-V21 unread rows, AT-V16 F3u, F11u, F12u, AT-V19 |
| M-67 | S5a: decide the `dictionary` and `pandas_metadata` kinds from values, so empty and all-null columns pass | AT-V21 empty rows, AT-V16 isolation keys |
| M-68 | Skip the populated restore guard and deliver the raw converter result | AT-V21 requires the typed source refusal before consumption for the year-2300 FF and late-batch inputs. Checking only the returned dtype also misses this failure. |
| M-69 | Skip only the resolved zone comparison | AT-V21 F11 epoch keeps its instant and precision but restores UTC as New York. |
| M-70 | Swallow the populated restore failure and continue with physical data | AT-V21 text-to-int and date64-to-date32 require the typed refusal and no consumer call. |
| M-71 | S5a: the `date64` time-of-day test reads only the extrema | AT-V21 interior row |
| M-72 | S5a: the `date64` scan builds one full-length modulo array | AT-V15 date64 operand-length bound |
| M-73 | S5a: pass an empty `date_read_by_table` at one site at a time: each resident call (port head `_pipeline.py:298`, `out_of_core/_runner.py:195`, `_pandas_adapter.py:190`), each loader call (`_pipeline.py:291`, `_sequential.py:294`), each `checked_chunks` call (`_chunked.py:459`, `native/_chunked_entry.py:438`), `OpenedLazyBatches.__init__ → checked_batches` (profile/_readers.py:196), `LazySource.iter_batches → checked_batches` (:269), and the ISO parent | For each non-Parquet site AT-V21 drives that wrapper with a read F3 or F11 and checks the physical read set at the first check and its typed refusal. For the two Parquet calls mutate each independently. Use a schema-admitted plain read column, spy on the arguments of each actual checked_batches invocation, consume a batch and assert its physical read set at batch admission. An open-time F11 refusal cannot prove either forwarding site. Use the AT-V16 pre-writer spy on ISO |
| M-74 | S5a: the ISO parent leaves the schema rules to the child | AT-V16 isolation keys (the writer spy records a call) |
| M-76 | Skip only precision comparison after successful restore | AT-V21 .123456 us-to-ms differs at the same zone. If the backend itself rejects a cast, inject a successful truncated result at the comparison seam to kill this mutant independently. |
| M-77 | S5a: `date_strategy_columns` drops the `windowed_date` anchor | AT-V21 anchor row |
| M-78 | S5a: `date_strategy_columns` drops `bucket_perturb` from `DATE_STRATEGIES` | AT-V21 `bucket_perturb` row |
| M-79 | S5a: `date_strategy_columns` counts a `nested` entry's JSON child `date_shift` as a read of the parent column | AT-V21 nested row |
| M-80 | S5a: `date_strategy_columns` skips entries with a `when:` gate | AT-V21 `when:` row |
| M-81 | S5b: run the live-year rule on inverted bounds | `test_max_before_min_emits_nat` fails on a `year_bins` refusal |
| M-82 | S5a: compare the writer dtype token to the physical timestamp unit instead of the restored dtype | AT-V21 genuine ns-token/us writer and object datetime controls |
| M-83 | S5a: read `strategy` before `_is_composite` | AT-V21 composite provider with `strategy: date_shift` |
| M-84 | S5a: classify every physical text field as non-date on both sides | AT-V21 public zoned M8 refusal |


## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with `replaced_by=None` (allowed by `reasons/_registry.py:202-209`, section 4.3): `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
- New reason `runtime/source_date_unrepresentable` (`since=UNRELEASED`, S5a), kept beside #799's `runtime/source_column_unrepresentable` for the reasons in section 4.4b. Its summary and remediation name the calendar years, the `ns` limit, the zoned local-time test, and the type reason's remediation names each kind's fix. Both messages build their table and column phrase from one helper, `source_location_text` in `_execution_error.py`.
- The S5a changelog records the Q8 = A narrowings for plain cells: zoned ns edges (row 8), plain or UTC `INT64_MIN` ns (row 9), out-of-calendar local times that pandas can read (row 11), and the passthrough returns of rows 13 and 14 (Appendix B.1), on NCH and on CH passthrough where main preserves them. It records E1 to E6 and E3b from section 0 for date-strategy-read columns, including both Parquet unit-coercion writer controls and the actual lossy companion. It distinguishes exact carry from a populated sibling restore and lists the round 3 examples.
- Amend #799's `run_mask_chunked` and `run_mask_pipeline_chunked` paragraph in `docs/compatibility-contract.md` with
  the two date codes, their exception classes and the NCH narrowing specified in 4.7. Update the dispatcher's
  matching date examples and keep #830's detector paragraph.
- New reason `runtime/source_date_type_unsupported` (`since=UNRELEASED`, S5a-1a, section 4.4b) and public error class `SourceDateTypeUnsupportedError`. Behavior: a source column holding a date inside a selected container is refused under Q6 = A. A date-strategy-read column that is a date dictionary, has malformed or date-changing pandas metadata (rule 3), or holds a `date64` time of day is refused under Q9 = A with kind `dictionary`, `pandas_metadata` or `date64_time_of_day`. The kind tokens are part of the frozen text contract.
- S5b: `FittedRangeError` (code `generation_unbounded_column`, public namespace `plan`, attribute `prop`) is a new coded error with one `_CODED` row. The QA F7 behavior of `ColumnGenerator.generate_column` changes from a clamp to a refusal for a live year bin outside the fitted years (changelog, section 4.4c Fix 3). Statistical plan compile and `sample_column` refuse a live bin past 9998 with `plan/generation_unbounded_column` where main failed at draw time uncoded (changelog).
- Post-mask report: new per-column field `declared_sentinel_rows` (S6, additive).
- Config and snapshot: S7 admits preserve_values on date generators. Store optional stats.sentinels beside year_bins within distribution-snapshot/v2. Only bucket entry models forbid extra fields (contracts/distribution_snapshot.py:47,58,68). Existing v2 readers ignore the new field and emit no sentinel from it. An all-sentinel fit has no ordinary distribution for an older reader to sample. Round-trip old and new snapshots, exercise the pre-S7 reader, and run the full engine suite for this writer change.
- Config: `preserve_values` becomes valid on `windowed_date` (S3, additive). No other config key changes.
- Behavior: far dates that were `format_error` row errors become refusals; typed edge sentinels that were shifted become refusals. Logical output for in-range and declared rows is unchanged (AT-R1, AT-R2 digests against base). S5 leaves every admitted input and its pandas conversion byte-for-byte as main has them (AT-V15, AT-V19). For refused inputs, the comparison table distinguishes earlier coded refusals, conversion or scalar-read failures, silent `NaT` and inputs main returned successfully. The last group is the narrowing under Q8 = A and Q9 = A (section 0).
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

- Returned tables and published files: unchanged logical values for in-range and declared rows, with the same Arrow input object on a successful S5 check. Buffer ownership belongs to G-12. A failed transactional run commits no output. Raw chunk iterators can already have yielded the good prefix.
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
| S5b | engine | Fitted distribution admission (section 4.4c): the fitted sampler refuses far bounds and live bins outside the fitted min and max years with `FittedRangeError(prop=...)`; the statistical rule refuses live bins past 9998 through `config_refusal` with `SAMPLED_YEARS_RULE`; the `_CODED` row, the two endpoint definitions and the canary hunk; AT-V2a, AT-V2b, the single-rendering guard in `tests/sentry/generation/`; M-58 to M-64, M-75 and M-81; docs sentence and changelog naming the QA F7 reversal and the statistical change. Ported from `a5da43ef9` plus the r3 fixes and Fix 3 | nothing | R2 | T1 plus the T2 gate set |
| S5a-1a | engine | Checked Arrow ingestion, the check unwired: the Q6 = A type gate, the Q9 = A kinds with `date_read`, the populated restore guard, `date_strategy_columns` in `_column_access.py`, both reasons, adapter rows and error classes (section 4.4b "Size and slices"). Fresh branch from main after S5b | S5b | R2 | T1 plus full suite and layer checks (reason registry, new reasons) |
| S5a-1b | engine | Checked Arrow ingestion, wiring: resident, loader, PAN and ISO wiring with the S5 hunks re-applied onto #799's files, name binding, the ISO pre-declaration helper in `_isolated_reason.py`, the resident conversion and reuse tests. S5a-1c completes the sentry and E-cell re-pin | S5a-1a | R2 | T1 plus full suite (frozen behavior, shared fixtures) |
| S5a-1c | engine | Streaming, native and profile wiring and remaining encoding route controls, including late failures and restore reuse | S5a-1b | R2 | T1 plus full suite |
| S5a-2 | engine | Checked Arrow ingestion, plain cells: the holdable rule on every route (Q8 = A), the resolver band test, count, purity, the 4.4a test edits, user docs and changelog naming the narrowed set and the Q8 x Q9 asymmetry | S5a-1c | R2 | T1 plus full suite (frozen behavior on passthrough) |
| S1 | engine | `DateDomain`, bound `DatePartition`, `DateRangeError` and its `_CODED` row, range table, new reason, the required `partition` on six primitives and the 15 call sites, the internal native range invariant, OOC typed path through `apply_bucket_perturb_dates`, removal of the native decline and abort, deprecation of the native range reason, sentry, AT-R1 to AT-R12 and AT-C1 to AT-C3, section 6.9 test updates, user docs for the S1 behavior (section 4.7), changelog fragment | S5b (shared ns bounds) | R2 | T1 plus the full engine suite (reason registry, frozen behavior) |
| S2 | engine | `group_by` with `preserve_values` on the Python path, two deprecations (`replaced_by=None`), AT-G1 to AT-G3, docs paragraph, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S3 | engine | `preserve_values` on `windowed_date` anchors, derived cell holds the anchor's sentinel (Q2), the anchor range on the shared code, deprecation, AT-W1 to AT-W3, docs, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S4 | engine | text_mask edge overflow becomes the token (Q5), AT-T1, docs sentence, changelog fragment | nothing | R1 | T1 |
| S6 | engine | post-mask sentinel exclusion and `declared_sentinel_rows` per column, AT-P1 to AT-P4, docs, changelog fragment | S1, S3 (derived anchors) and PM-1 (#784) merged | R2 | T1 plus the T2 gate set |
| S7 | engine | date generation: per-column fit kwarg, policy-aware snapshot writer and sentinel counts, matching generation declaration, admission (`_window_admission.py:128-170`, `:290-320`) and sampler (`_sample.py:493`, `_degenerate.py:122`) emitting sentinels at their rate (Q3), calendar-date stats in `_datetime_stats` and `_distribution_date`, AT-F1 to AT-F4, docs, changelog fragment | S1, S3 and S5 | R2 | T1, T2 and full engine suite (snapshot writer) |
| S8 | CLI | Wire the per-column exact-fit option through fit_exact_snapshot, test CSV fit through generation, update command help, user guide and changelog | S7 engine API released and available to CLI | R2 | CLI suite and installed CLI/engine integration |
| ASSEMBLER-LABELS | engine | Map source-backed pandas display labels to physical Arrow fields by position in the passthrough assembler (`execution/pipeline/_source_types.py:129,156`); tests with integer, tuple and duplicate-looking labels on FF. Pre-existing, found in S5 round 6 | nothing | R2 | T1 |
| DEP-FLOOR | engine | Raise the declared pandas floor to 2.x (Q7 = A) and make the engine import at its declared pyarrow floor: optional list-view predicates (`safe_output/_file_metadata.py:60-61`); AT-V11 and M-35 move here; exact-version CI legs that also run AT-V13 and AT-V20, and on the pyarrow 14 leg the AT-V21 writer controls and a one-line import check of the private `pyarrow.lib.string_to_tzinfo`. Pre-existing | nothing | R2 | T1 plus the floor legs and a full suite (version pin) |
| SOURCE-RESTORE-CODED | engine | G-17 folded into S5a rules 3–4. Preserve FF, PAN and PROF restored-zone edge and safe controls at the real conversion, including scalar access. | S5a wiring slices | R2 | AT-V20/V21 |

Each row is one PR. S4, S5b, ASSEMBLER-LABELS and DEP-FLOOR can start independently. S5a follows S5b in order 1a, 1b, 1c, 2. SOURCE-RESTORE-CODED is covered in these PRs. S1 follows S5b for the shared ns bounds. S2 and S3 follow S1. S6 follows S3 and PM-1. S7 follows S3, S5a-2 and S5b with S1 already merged. S8 follows the S7 engine release.

## 15. Owner decisions (product choices)

The owner accepted the recommendations for Q1 to Q5 on 2026-11-27, chose A for Q6 on 2026-11-28, and chose A for Q7, Q8 and Q9 on 2026-11-28. No owner question is open.

- Q1, typed date columns. Decided: typed `date` columns (Parquet, database `DATE`) keep the 0001 to 9999 domain, less the strategy's reach. `9999-12-31` and `0001-01-01` are refused on the usual windows unless declared, and genuine historic dates such as `1600-01-01` still mask. Text and zoned timestamps use the pandas domain.
- Q2, windowed_date with a declared sentinel anchor. Decided: the derived cell holds the anchor's sentinel value, so "unknown admission" gives "unknown discharge". Never the source value of the derived column.
- Q3, generation. Decided: a declared sentinel is excluded from the fitted range and emitted at its observed rate, so downstream `= 9999-12-31` logic keeps working.
- Q4, quarantine. Decided: an undeclared far date refuses the run even when `format_error` quarantine is on. The remedy is to declare the sentinel.
- Q5, text_mask date spans at the calendar edge. This departs from the owner rule (a coded refusal), so it is a product call. Decided: the span becomes the redaction token, as an unparseable span already does. Free text holds dates the user never declared, one edge date in a note should not stop a run, and the token writes no source value (fail-closed). The other option was the coded refusal.

- Q6, date columns inside containers (section 4.4b). Decided: (A), as given in the S5 redesign brief on 2026-11-28. A column holding a date inside a list, large list, fixed-size list, map or struct is refused by type even when every date is inside the calendar; full support is follow-up G-8. The options considered were (A) refuse for V1, (B) build G-8 inside S5, and (C) refuse only caller-supplied Arrow. List view, run-end-encoded, union, extension and dictionary-of-struct columns never come from a Decoy file reader, so refusing them is a technical choice and not part of Q6.

- Q7, pandas floor (row DEP-FLOOR, not S5). Decided 2026-11-28: (A), raise the declared pandas floor to 2.x. The engine does not import on pandas 1.5.3 today (`validators/_dates.py:13`), so no working user is lost, and the S5a holdable rule keeps the source timestamp unit. The (B) branch is in Appendix B.2.

- Q8, inputs main accepted that S5a refuses on routes that never convert. Decided 2026-11-28: (A), one holdable rule on every route, passthrough included, for plain date cells. Main can return zoned ns edges (row 8), `INT64_MIN` ns (row 9), readable year-10000 local times (row 11) and far plain dates (rows 13 and 14) on NCH and CH passthrough; S5a refuses them. Every plain `date64` is judged by its day. The (B) branch is in Appendix B.2. Under Q9 = A, Q8 = A does not reach exotic encodings on columns no date strategy reads (section 0.2).

- Q9, S5a scope for exotic date encodings (section 0). Decided 2026-11-28: (A). A column that `date_shift`, `bucket_perturb` or a `windowed_date` anchor reads must be a plain `date32`, `date64` or `timestamp` column. A date dictionary, malformed or date-changing pandas metadata (rule 3), or a `date64` with a time of day is refused there with `runtime/source_date_type_unsupported`, kind `dictionary`, `pandas_metadata` or `date64_time_of_day`, and the fix "cast it to a plain date or timestamp column", with no value in the message. The same encodings on a column that is only passed through, kept, hashed, redacted, tokenized or profiled follow the unread rules in section 4.4b. E1, E3b and E4 in section 0.1 document the original Q9 compatibility decision. Revision 14 additionally covers changes of meaning on actual sibling restores. The builder re-pins every E-cell on main both ways and stops before merge if the re-pin adds an E row. The (B) branch and the question as put are in Appendix B.5.

Technical choices taken (recommended option, no owner call needed): keep the name `preserve_values`; reach from config, not the key; refuse near-bound text dates on every route instead of computing them on some; keep `sentinel_to_null` separate with casting first; keep generation's plan-time refusal code; no rename of the out-of-core disposition fields.

## 16. Follow-ups (not in this row)

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
- G-16: two disjoint date dictionaries whose union needs a wider index fail in the carried profile (`profile/arrow/_walk_arrow.py:44`) and in the AUTO join (`execution/_pipeline_auto_chunk.py:144`). Pre-existing on main, also for non-date dictionaries. Under Q9 = A it stays main's behavior on unread columns. Log; fix with the shared union of Appendix B.5.1 item 2 if a customer needs it.
- G-17: covered in S5a by the guarded restore, including scalar access to the restored-zone edge on FF, PAN and PROF. Exact carry bypasses restoration.
- G-18: `config_position("statistical", Name(col))` in S5b's `check_degenerate` refusal names a config key that does not exist (`statistical.c`). Only direct `check_degenerate` and `sample_column` callers see it, since plan compile rebuilds the error; its sibling `refuse_degenerate` says "statistical column 'c'". Acceptable for V1. Log.
- G-19: `contracts/calendar_range.py` imports pandas for its fallback parse of non-ISO text, a framework import inside a contract module (Dennis r1 of revision 10, LOW). Log for the structure review.

## Appendix B. Superseded detail

Historical appendix retained at plan head `4d90a2951`, path `docs/plans/2026-11-27-date-range-sentinel.md`, sections B.1–B.5 (including comparison rows, prior reviews and the rejected option B). All Appendix B references point to those sections. Retrieve with `git show 4d90a2951:docs/plans/2026-11-27-date-range-sentinel.md`.

## Revision 14 finding-to-fix map

| Class | Round 3 finding | Plan-level closure |
|---|---|---|
| V1 | Year 2300 overflows during the intermediate New York cast | Rule 3 guards the populated restore. AT-V21 pairs the failing instant with ordinary and empty UTC controls. M-68 exercises the bypass. |
| V1 | Sub-day date64 fails the date32 restore on an unmasked sibling | Rule 4 distinguishes actual FF restore, projection and exact carry. AT-V20/V21 cover −1 ms, the aligned writer and zero restore calls on carry. |
| V1 | Integer metadata breaks a populated text date | AT-V21 checks both target and anchor, with typed failure and successful writer controls. M-70 exercises swallowed failure. M-69 and M-76 isolate zone and precision loss after successful restore. |
| V2-LOG | PR size and sequencing | Section 4.4b splits the wiring into 1b and 1c. S5a-2 owns the Factory keys with their count implementation. Measure actual base-to-head diffs against 799. |
| V2-LOG | Conflicting take instructions and test inventory | AT-V9 forbids take, including aliases. AT-V16 keeps 488 keys. Additional round 3 cases belong to AT-V20/V21. Count executed keys and record mutation kills on the final implementation head. |
| V2-LOG | S5b message prefix | Fix 3 and AT-V2a pin the port's unqualified display code and separately assert the registered plan namespace. |
| DESIGN | Existing plan size | Appendix B now points to the exact historical revision. The remaining over-cap document is a pre-existing follow-up. |
