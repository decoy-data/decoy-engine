Status: plan

Q10: decided A by the owner on 2026-11-28 (section 15).

# DATE-RANGE-SENTINEL: a date a strategy cannot compute is refused unless the column declares it as a sentinel

Owner: Cam. Author: Opus (Architect). Date: 2026-11-27. Revision 3 (after review round 2, with Q1 to Q5 settled in section 15). Revision 4 adds section 4.4b after S5 code review round 2. Revision 5 (2026-11-28) redesigns S5 in section 4.4b after the S5 build failed six code-review rounds, splits it into S5a and S5b, and records Q6 as decided A. Revision 6 (2026-11-28) fixes Dennis plan review round 1 (section 17.3): S5 anchors move to `origin/main` `d1d7453ac`, after #799. Revision 7 (2026-11-28) addresses Dennis round 2 against main at `395c1c662`, including #830. Revision 8 (2026-11-28) addresses the outside Codex review of plan head `f82252693`. Revision 9 (2026-11-28) addresses the review of `fb84f0204` against `395c1c662`. Revision 10 (2026-11-28) puts the S5a scope to the owner as Q9 (section 0), writes S5a for Option A with the owner's Q7 = A and Q8 = A, states S5b as a standalone slice with the two r3 S5b fixes (section 4.4c), and moves superseded detail to Appendix B. Revision 11 (2026-11-28) records the owner's Q9 = A (section 15), moves Q9 = B to Appendix B.5, and fixes Dennis plan review round 1 of revision 10 (`~/scratch/dennis-s5-plan-r10.md`, Appendix B.3.6). Revision 12 (2026-11-28) incorporates the Codex review of revision 11 into the S5 rules, port inventory, tests and mutations. Revision 13 replaces the S5a spelling list with a schema restore and corrects date64 and ISO admission. Revision 14 guards the populated route restore and reuses its result. Revision 15 (2026-11-28) re-scopes S5a to one schema-level pandas metadata check (section 4.4b) and opens Q10 (section 15). Revision 16 (2026-11-28) records the owner's Q10 = A, applies Dennis plan review round 1 of revision 15 (12 edits, Appendix C), and re-anchors S5a to `origin/main` `8414da35c` with S5b at `feat/date-range-sentinel-s5b` `52c3070e8` (not merged at that head). Roadmap row: DATE-RANGE-SENTINEL (engine 1.0). Section 1 probe anchors are at `f54ad388b`. S5a anchors in sections 0 and 4.4b are at `origin/main` `8414da35c` unless marked `PM-1:` (branch `fix/postmask-fail-closed`, `docs/plans/2026-11-27-pm1-canonical-cell-walk.md`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one new reason code, three deprecations, a config key on one more strategy), `catalogs/recurring-defects.md` (11 classes), `cross-cutting-concerns.md` (one rule, many routes), `testing.md` (test depth T0 to T4). Revision 5 also consulted the bound registry (`tests/sentry/ratchet/_limit_constants.py`, `tests/sentry/baselines/sentry-limits.json`) and, as established solutions, Arrow's dictionary semantics (a slice keeps its dictionary; some dictionaries cannot be unified, as covered in AT-V14; `to_pandas` converts the whole dictionary), pyarrow's tz resolver (`pyarrow.lib.string_to_tzinfo`, the tzinfo `to_pandas` and `as_py` receive) for offsets, and Hypothesis property tests against an independent oracle. Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`, deprecation with `replaced_by`).

Risk: R2. It changes what a date strategy does with a far date on every route, adds a reason code and deprecates three, and turns a quarantinable row error into a refusal. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis for S1, S2, S3, S5, S6, S7 and S8; Codex only for S4. Full suite before merge: S1, S2, S3 and S5 for reasons, and S7 for snapshot serialization; the other slices by their own triggers (section 14).

Owner decision (2026-11-27): a date outside the range a strategy can compute is rejected, unless the column declares it as a sentinel to ignore. Sentinel rows skip the strategy and come out unchanged.

## 0. S5 redesign: Q9 decided A (revisions 10 and 11)

Three Codex plan rounds on revisions 7 to 9 (`~/scratch/codex-s5-plan-r1.out`, `-r2.out`, `-r3.out`) each closed the cases they named and then found the same class one layer deeper. Every new finding came from an Arrow or pandas encoding that the conversion treats specially:

- pandas metadata restores a time zone that the physical Arrow type does not carry (round 2), and an `ArrowDtype` spelling in the metadata restores another unit or zone the same way (round 3);
- two valid `int8` date dictionaries whose union needs a wider index fail in the carried profile (round 2), then the same union fails in AUTO's `concat_tables(...).combine_chunks()` and in the legacy collector (round 3);
- the round 2 fix for the profile union adds a row-sized index allocation (round 3).

Exact route parity on these encodings kept adding machinery, so revision 10 put the S5a scope to the owner as Q9. On 2026-11-28 the owner chose Q9 = A, with Q7 = A (pandas floor 2.x) and Q8 = A (one rule on every route) (section 15). The option not chosen, Q9 = B, is in Appendix B.5. Plain `date32`, `date64` and `timestamp` cells keep the one Q8 = A rule on every route, including passthrough. Rule 3 judges the schema of date-read fields only. Exact carry preserves raw milliseconds. S1 to S4, S5b and S6 to S8 do not depend on Q9.

In this section, an *exotic encoding* is one of:

- a dictionary whose value type holds a date (`dictionary<date32>`, `dictionary<timestamp[us, UTC]>` and so on);
- a field whose pandas metadata is malformed or would change the field's meaning at conversion (section 4.4b rule 3, judged from the schema);
- a `date64` column with a non-null value that is not a whole number of days.

A column is *date-strategy-read* when a column entry from the run config or compiled work nodes gives it `date_shift` or `bucket_perturb` (the strategies that build the range and sentinel rule of S1), or names it as the `anchor` of a `windowed_date` entry. The set comes from `date_strategy_columns` in `execution/_column_access.py`, the module that already declares which columns each config entry reads (section 4.4b). A `when:` gate does not change the answer: a gated `date_shift` still reads its column. A `date_shift` inside a `nested` entry runs on extracted JSON text, so it does not make the parent column date-strategy-read. A composite entry is decided by its provider, as in `build_work_list`, and no composite is a date strategy. A column that is passed through, kept, hashed, redacted, tokenized or profiled is not date-strategy-read. Stored pandas index fields are never date-strategy-read.

### 0.1 Strategy restrictions and guarded route reads

At `check_source_dates`, the one source-date boundary:

1. A date-strategy-read column in an exotic encoding is refused with the existing type refusal `runtime/source_date_type_unsupported` and one new kind token: `dictionary`, `pandas_metadata` or `date64_time_of_day`. The refusal names table, column and kind, carries no count and no value, and names the fix: cast the column to a plain date or timestamp column (section 4.4b, rule 6, gives the literal texts).
2. A field that is not a date-strategy input gets no metadata or time-of-day refusal and no change to its physical buffers. The physical Q6/Q8 checks keep their separate scope.
3. Every engine frame conversion receives a pandas metadata blob reduced to the fields it converts (section 4.4b rule 3c), so a descriptor of a field outside the projection cannot break or change the read.

The dictionary restriction and the metadata check apply at schema admission and need no rows, so an empty input gets the same verdict as a populated one.

Inputs that stay admitted for date strategies (controls in AT-V19 and AT-M2): every descriptor whose channels are identity under rule 3b, as `pa.Table.from_pandas` writes it for naive, zoned, `date`, text and `ArrowDtype` columns, the pandas-written zoned Parquet file read back at `us` (its `numpy_type` `datetime64[ns]` is a plain token and its zone equals the field zone), and the `ArrowDtype` `date64` writer stored as `date32` (probe, 2026-11-28).

**What A refuses that main reads today.** The table describes date-strategy inputs. Revision 15 does not judge sibling fields (G-21). The last column shows which rows the decided Q8 = A already refuses under revision 9 (only the code changes) and which rows are new because of Q9. Comparison rows refer to Appendix B.1.

| # | Date-strategy-read input | Main at `395c1c662` | Under A | Already refused by Q8 = A (revision 9)? |
|---|---|---|---|---|
| E1 | a date dictionary whose entries are all in years 1 to 9999, unique, with a signed index (comparison rows 1 and 4; fixture F3) | the strategy receives a pandas categorical of dates | refused, kind `dictionary` | no: **new with Q9** |
| E2 | a date dictionary with an entry outside years 1 to 9999 in a non-ns unit, or an unused zoned ns edge entry (rows 5 and 7; fixture F2) | the strategy receives the converted rows | refused, kind `dictionary` | yes, with `source_date_unrepresentable` |
| E3 | a date dictionary main cannot convert: far, `INT64_MIN` or null entries, and the one-chunk literals with duplicate entries or a `uint64` index (rows 2, 6, 12, 15; fixture F9; the literal keys of AT-V16) | refused with #799's code on converting routes | refused, kind `dictionary` | yes |
| E3b | a date dictionary main converts only by joining chunks, or reads as another type: duplicate entries spread over chunks, which some multi-chunk conversions unify and then convert; an epoch entry in `dictionary<timestamp[ns, Factory]>`, which pandas reads as a naive timestamp (Appendix B.1, below row 15) | the strategy receives the converted rows | refused, kind `dictionary` | no: **new with Q9** |
| E4 | a date-read field whose descriptor fires the zone channel (fixture F11, a timestamp with another zone), fires a non-identity extension channel that changes the zone or unit (`datetime64[ms, UTC]` on `timestamp[us, UTC]`, a zoned `M8` token on a string or `date32`), or gives the field another frame label | restoring reads give the strategy the metadata type or another column; metadata-ignoring reads give it the physical type | refused, kind `pandas_metadata` | no: **new with Q9** |
| E5 | the same with an edge value (physical UTC ns `INT64_MIN + 42` restored to New York; a `us` tick of 1 restored to `timestamp[s][pyarrow]`) | zone restoration succeeds but scalar access can raise with timestamp text and year extraction can wrap; #799 already codes the precision error; metadata-ignoring reads succeed | refused, kind `pandas_metadata` | yes, with `source_date_unrepresentable` |
| E6 | a `date64` with a time of day (for example 1 ms; fixture F12) | the strategy receives the date with the time of day dropped | refused, kind `date64_time_of_day` | yes, with `source_date_unrepresentable` |
| E4b | (revision 15) a naive `timestamp[ns]` written by Parquet `use_deprecated_int96_timestamps=True` or `flavor="spark"` from a zoned column, with the writer's `datetimetz` descriptor | the zone channel restores the original zone and instants correctly | refused, kind `pandas_metadata` (the zone channel fires), Q10 = A | no: **new with revision 15**, decided by the owner (Q10 = A, section 15) |
| E7 | (Q10) a date-read field whose descriptor asks for an extension dtype that is not identity for its Arrow type and keeps the zone (for example `Int64` or `period[D]` on `string`) | main converts to that dtype or fails | refused, kind `pandas_metadata` (the extension channel fires), Q10 = A | no: **decided by the owner (Q10 = A, section 15)** |

Revision 11 adds E3b: the converting successes that Appendix B.1 lists below row 15, which revision 10 folded into E3 as "fails". E4 now also covers the non-timestamp physical fields that rule 3 refuses. Revision 15 adds E4b and E7 and states E4 by pyarrow's channels. E4b and E7 follow the E4 column of the route table on every route. Revision 16 records the owner's Q10 = A for both: E4b through the zone channel and E7 through the extension channel. The principle is the same for both: Decoy never ignores the pandas metadata of a date-read column. When the metadata conflicts with the data, the column is refused with a coded refusal that names it. Both rows apply only to date-strategy-read columns (section 15, Q10 scope). An int96 or Spark-flavor column that no date strategy reads keeps main's correct restore.

Per route. "Q9" marks a row A refuses where main reads the input today. "Q8" marks a row the decided Q8 = A already refuses (only the code changes). "fails" means main already fails. "none" means no input of that kind can reach the route.

| Route (date strategy configured on the column) | E1 | E2 | E3 | E3b | E4 | E5 | E6 |
|---|---|---|---|---|---|---|---|
| FF and AUTO, resident Arrow or loader | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| SEQ, loader (Arrow) | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| OOC Python and native, resident `sources` | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| CH and NCH, Arrow batches (the configured column is converted or computed natively, never carried) | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| PAN `run` and `run_single` | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| ISO on and off, resident Arrow | Q9 | Q8 | fails | Q9 | Q9 | Q8 | Q8 |
| FF, AUTO, SEQ and OOC on Parquet (whole file and lazy batches), CLOUD and HIVE | none | none | none | none | Q9 (E4b and E7 too, refused at batch open before any batch is yielded) | Q8 | none |
| PROF and non-strategy siblings | No strategy dictionary restriction | Same | main's conversion | Same | Not judged (G-21) | Not judged | Rule 5 on the rule 4 day, original ticks on carry |

**Re-pin both ways.** The cells above are derived from probes, not from runs of every route on main. The S5a wiring slices run every E1 to E6 and E3b cell on `origin/main` red-first in AT-V16 and records the observed outcome per cell. A "Q9" or "Q8" cell where main fails moves to "fails". A "fails" or "none" cell where main succeeds moves to "Q9", is added to the E list here, to the changelog and to the compatibility contract (section 4.7), and is named in the builder report. If the re-pin adds an E row, the builder stops and reports before merge, because the owner decided Q9 on this list.

Parquet stores no date dictionary and no sub-day `date64`, so E1 to E3b and E6 reach a date strategy only as caller-built Arrow (resident `sources`, a `source_loader` result, chunked API input). A pandas frame with a categorical of dates becomes a date dictionary under `pa.Table.from_pandas`, so an SDK caller that shifts such a column must decode it first. E4 and E5 can arrive through Parquet, because Parquet keeps the pandas metadata of the table it was written from. An ordinary Parquet write of an ArrowDtype timestamp can preserve the original unit in pandas metadata while changing the physical unit: `df.to_parquet` writes `timestamp[s][pyarrow]` at ms, and `coerce_timestamps="us"` writes an ns column at us. The changelog, `docs/strategies.md` and the compatibility contract list E1 to E6 and E3b.

What A removes from the revision 9 S5a design: the dictionary structure rule and its count, the bounded index windows, the ISO parent projection of original dictionaries and its RSS bound, the carried-profile index widening, the two metadata interpretations, the disjoint-dictionary and AUTO-join cases, and mutations M-43, M-44, M-50, M-54, M-55 and M-57.

### 0.2 Why A, and how Q9 combines with Q7 and Q8

Section 4.4b distinguishes the config read set from the fields materialized by each route. It binds both to physical columns before any strategy consumes them.

- **Q8 = A (decided).** The plain-cell rule runs on every route, passthrough included. Plain physical dates remain subject to the Q8 domain check. Exact carry preserves an unread date dictionary without visiting its entries. A sibling's descriptor is not judged (G-21). Removing the asymmetry means judging unread exotic encodings, which is the Q9 = B design (Appendix B.5). The asymmetry goes into `docs/strategies.md` with the E list (section 4.7), not only into this plan.
- **Q7 = A (decided).** pandas 2.x is the floor, so the plain rule keeps the source timestamp unit and needs no pandas 1.x bounds. Q9 does not depend on the pandas version. DEP-FLOOR raises the declared floor (section 14).
- G-16 remains a separate dictionary-union issue. G-17 is closed by rule 3 for date reads, and its passthrough part is G-21.

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

The checks in section 4.4b return the original Arrow input or raise (Q10 = A, decided 2026-11-28). `arrow_to_frame` reduces the pandas metadata blob to the converted fields. AT-V1 covers resident returns, caller loaders and lazy yields. The source-date refusal builders remain in io/source_dates.py. Run the import-layer and reason-adapter tests, including isolated classification.

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
- The S5 branch's nested and dictionary paragraph (`a5da43ef9:docs/strategies.md:403-405`, not on main) is rewritten per section 4.7 and lands on main as a new subsection before `### bucketize` (`docs/strategies.md:399` on `8414da35c`).

For branch tests, record the specific 4.4b type, cell or dictionary rule that changes the expected result.

### 4.4b S5a design (Q10 = A, Q9 = A, Q8 = A, Q7 = A, all decided)

Revision 15 replaces rules 3 and 4 of revision 14 with one schema-level metadata check (design C, `~/scratch/s5a-rescope.md`). Revision 14 guarded the populated restore and compared its result cell by cell. Rounds 1 to 4 of the Codex review each found a new case one layer deeper, because the engine passes the whole `b"pandas"` blob to pyarrow, including descriptors of fields the job never reads. Design C stops predicting the restore. It reads the conditions under which pyarrow changes a value and refuses a date read when one of them is met. The revision 14 text is at plan head `115f760e3`. Section 4.4c (S5b) does not change.

**Main after #799.** `7822182c5` (#799) merged after the S5 branch was cut from `9812da814`. `a5da43ef9` does not contain it. Checked again on `8414da35c` (revision 16), after #827, #828, #829 and #837:
- every source conversion goes through `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair` or `table_to_pandas_exact_ints` in `internal/pandas_compat.py`. The public module `decoy_engine.arrow_frames` exports the three `arrow_to_*` names. Only the implementation module calls `to_pandas`. `arrow_to_series` (`:213`) never uses the blob. `arrow_to_frame_pair` (`:243`) and `table_to_pandas_exact_ints` (`:262`) call `arrow_to_frame`;
- a column pandas cannot hold raises the coded, value-free `runtime/source_column_unrepresentable` (or `full_frame_value_unrepresentable` on the pandas execution routes). On failure `_first_failing_column` (`internal/pandas_compat.py:156-173`) converts column by column with `Column.to_pandas`, which reads no schema blob, and names the failing column. S5a keeps this unchanged.
- the only caller that passes `ignore_metadata=True` is `execution/pipeline/post_scan/_suite.py:51`.

S5 keeps original Arrow buffers on admission. Under Q10 = A (decided) the checker returns its input object on every admitted input.

**Re-anchor at `8414da35c` (revision 16).** What moved since `395c1c662`:
- #829 moved the chunked oracle step. `DeclarationRequest.for_chunks(config, table, source_schema)` is now at `execution/_chunked_oracle.py:455` (was `:534`).
- `stored_index_fields` in `execution/native/_chunked_entry.py` is called at `:456` and `:527`. The file is 621 lines on main (census ceiling 641), not 688.
- #827 changed `profile/_lazy_build.py` and `profile/_source.py`. Both move from "taken whole" to the "re-apply hunks only" list (port method step 2).
- `docs/strategies.md:403-405` is an anchor on the S5 branch (`a5da43ef9`), not on main. On main the S5a docs text is a new `#### Dates outside the calendar` subsection at the end of `#### Sentinel dates (preserve_values)`, before `### bucketize` (`docs/strategies.md:399` on `8414da35c`).
- S5b is not merged at `8414da35c`. It is on `feat/date-range-sentinel-s5b` at `52c3070e8`. S5b defines `CALENDAR_FIRST_DAY_NUMBER` and `CALENDAR_LAST_DAY_NUMBER` in `_arrow_types.py` (`52c3070e8:src/decoy_engine/_arrow_types.py:22-23`), and `MAX_BIN_YEAR = 9999` and `names_year_beyond` in `contracts/distribution_snapshot.py` (`:35`, `:50`). S5a takes the calendar constants from S5b and drops the port's duplicate definitions at `a5da43ef9:src/decoy_engine/_arrow_types.py:22-23`. Any year bound S5a needs comes from `MIN_YEAR` and `MAX_BIN_YEAR` in `contracts/distribution_snapshot.py`, and S5a adds no second literal for years 1 or 9999.
- S5b and the port both change `_arrow_types.py`, `reason_adapter.py` (`_CODED`), `CODEMAP.md` and `docs/strategies.md`. S5a re-applies its own hunks onto S5b's versions of these four files (port method step 2).

#### Failure modes S5a must not have

Each failure mode is pinned by the named tests. A builder who changes one of these tests reports it as a change of expectation (section 6.9).

| Failure mode | What it looks like | Pinned by |
|---|---|---|
| Refusing real writer output | a descriptor that pyarrow, pandas, fastparquet or Spark writes, and that converts to the Arrow type, is refused | AT-M2 (writer forms, Spark orphan descriptor), AT-M1 `pairs_for` identity guard, AT-V19 |
| A projected-away descriptor breaks a read | a malformed or mismatched descriptor of a field the route does not convert raises or changes the frame | AT-M3, AT-V17 |
| A refusal after declaration or loader calls | the refusal comes after `DeclarationRequest.for_run`, `for_chunks`, a loader call, a writer call, a spawn or a yielded batch | AT-M4, AT-M2 lazy batch rows (zero batches yielded), the order sentry in AT-V18 |
| A value in a refusal | a cell value, the metadata zone, a `numpy_type` token or descriptor JSON in `str`, `repr`, cause, context, logs or the isolated child result | AT-M2 and AT-M6 exact `str(exc)` rows (E4b, E7), AT-M1 refusal rows, AT-V16 refusal checks |
| A verdict that differs from what pyarrow applies | `identity` where pyarrow changes the column, or `meaning_change` where pyarrow reads the Arrow type, because the verdict resolves the descriptor differently from the channel | AT-M1 property and per-channel lookup rows (rule 3b), AT-M1 wrong-type rows (rule 3a) |

#### The rule

`check_source_dates(data, *, table, date_read)` in `io/source_dates.py` is the one place where the source date domain is judged. It judges one table or record batch, with its schema and pandas metadata. `date_read` is the set of physical field names that a date strategy reads in this table (section 0). Execution identifies the configured reads once per table with `date_strategy_columns(entries, registry) -> frozenset[str]`, added to the existing `execution/_column_access.py` beside `touched_columns`. No new execution module is added: `FANOUT_ALLOWLIST` pins `src/decoy_engine/execution` at exactly 102 modules (`tests/sentry/layout/test_package_fanout.py:33`). Bind entries from raw run config through the same `_table_columns(config, table)` view as `passthrough_columns` (`_chunked_carry.py:187,256`). For `PandasExecutionAdapter.run` (`_pandas_adapter.py:167`), build the work nodes once with `build_work_list(plan, registry)` before resident source admission. Group by `node.table` and feed the same classifier entries from the existing `ColumnSeed` mapping in `untouched_columns` (`_chunked_carry.py:230-244`). Extract that mapping once for both callers. Reuse the work list for dispatch. The work-list build, the grouping and the binding are one function in `_column_access.py`, so `_pandas_adapter.py` gains one call and stays at or below 676 lines (net zero, per-file line budget below). `run_single` (`:132`) delegates with the same plan, table key and registry. Resolve the caller registry before admission (`get_default_registry()` when it is None). The ISO parent uses the default registry. The classifier:
- `_is_composite(provider, registry)` decides composite entries first, as `column_access` does. No composite is a date read.
- A scalar entry whose `strategy` is in `DATE_STRATEGIES = frozenset({"date_shift", "bucket_perturb"})` reads its own column. A `when:` gate does not change that.
- A `windowed_date` entry reads `_provider_config(entry)["anchor"]`.
- A `nested` entry is not a date read of its column.
- Bind targets and anchors by exact string equality against the schema field names, excluding stored index fields.

The constant and the helper are about 35 lines. The `io` tier never reads config. Standalone profile reads pass an explicit empty set. Execution callers pass the set for each table, empty when there are no date reads. S1 adds a sentry assertion that the strategies which build a `DateDomain` equal `DATE_STRATEGIES`.

Rules 1, 2, 3 and the first half of rule 4 use the schema only. Rules 4 (cells) and 5 read the physical buffers. No rule converts to pandas.

1. **Type gate (Q6 = A, unchanged).** A column that holds a date inside a list, large list, fixed-size list, map, struct, list view, run-end-encoded, union, extension or dictionary-of-container type is refused by type with `runtime/source_date_type_unsupported` and its outermost kind, whether or not a strategy reads it. The walker, the shape classifier and the unclassified-layout refusal from the S5 branch stay (`_arrow_types.py`). A top-level dictionary of a plain date type is not a container. Rule 2 decides it.
2. **Strategy input restrictions (Q9 = A).** Within a field in `date_read`, apply these in order:
   - a dictionary of a plain date type is refused, kind `dictionary`;
   - a descriptor verdict other than `identity` (rule 3) is refused, kind `pandas_metadata`;
   - a `date64` with a time of day (rule 4) is refused, kind `date64_time_of_day`.

   A dictionary of text (`dictionary<int8, string>`) is not a date type, so rule 2's first item does not apply to it. Rule 1 runs before rule 2. Check fields in schema order. A table-level malformed blob (rule 3) refuses before any field rule.
3. **Pandas metadata check (schema only).** Three parts: one parser, one channel verdict, one projection filter.

   **3a. The parser.** `parse_source_meta(schema) -> SourceMeta | MalformedMeta` in the new bottom-tier module `_pandas_meta/_source_meta.py`. It imports only pyarrow and `_canonical.strict_json_loads`, as `_pandas_meta`'s package docstring requires. It parses the `b"pandas"` value once. No blob gives an empty `SourceMeta`. `MalformedMeta` carries only a field name (or none) and no backend text. The blob is malformed when any of these is false, matching the keys pyarrow 24.0.0 reads without a default:
   - the value is strict JSON and an object;
   - `columns` and `index_columns` are lists;
   - every `columns` entry is an object with the keys `name` and `numpy_type`;
   - the entry of every field present in the schema has `pandas_type`;
   - the entry of a present `timestamp` field with `pandas_type == "datetimetz"` has the key `metadata`;
   - in that entry, a truthy `metadata` is an object, and a truthy `metadata["timezone"]` is a string. pyarrow calls `metadata.get("timezone")` and passes the zone to `pa.timestamp("ns", tz=...)` inside `_add_any_metadata`, so a non-object truthy `metadata` (a list, a string, a number) raises `AttributeError` and a non-string truthy `timezone` raises `TypeError` (revision 16, Dennis r1 edit 6);
   - every string in `index_columns` has a `columns` entry, and every object in it has `kind == "range"` and the keys `name`, `start`, `stop` and `step`.

   A missing `field_name` is not malformed. fastparquet and old pyarrow files omit it, and pyarrow then resolves by `name` and by position. pyarrow does not resolve an entry to a field the same way in each channel, so `SourceMeta` has one lookup per channel and no shared `descriptor(field)` (rule 3b gives the three lookups). `stored_index_fields` and `arrow_columns` (`_pandas_meta/_columns.py:26,32`) read from `SourceMeta`. `pandas_nullable_columns` (`_pandas_meta/_columns.py:38`, its own `json.loads` at `:49`) reads the lenient view of `parse_source_meta`: the `columns` list when the blob parses to an object with a `columns` list, else empty. It keeps main's per-entry rule (`field_name or name`, the `numpy_type` test) and main's result on every blob, malformed ones included, so the engine parses the blob in one place (revision 16, Dennis r1 edit 10). On `MalformedMeta` they keep main's behavior (they read `schema.pandas_metadata` and raise as main does), so a job with no date reads keeps main's error (follow-up G-20).

   **3b. The channel verdict.** `descriptor_verdict(field, meta) -> Verdict` in the new module `io/_descriptor_channels.py`. It needs `pandas.api.types.pandas_dtype`, so it cannot sit in `_pandas_meta`. Only `io/source_dates.py` calls it. The verdict is `identity`, `meaning_change` or `malformed`. It follows pyarrow 24.0.0 `pandas_compat.py`, not a list of spellings:
   - *Zone channel* (`_add_any_metadata`, `:1223-1281`). Lookup: for the entry at position `i` in `columns`, the key is `field_name` when it is truthy; else `name`, replaced by the string `index_columns[i - n_columns]` when `i >= n_columns` (`n_columns` is the number of `columns` entries less the number of string `index_columns`); a None key becomes `"None"`. The entry belongs to the field `schema.get_field_index(key)` names, and to no field when that is -1 (absent or duplicate name). Every entry that belongs to a date-read field is judged. The channel fires when the field is a `timestamp`, `pandas_type == "datetimetz"`, `metadata` is truthy, and `metadata["timezone"]` is truthy and not equal to `field.type.tz` (string comparison, as pyarrow does). A fired zone channel is `meaning_change`. pyarrow casts through `timestamp("ns", tz=meta_zone)`, which changes the zone and the unit and overflows outside the ns range (round 3, year 2300).
   - *Extension channel* (`_get_extension_dtypes`, `:866-945`). Lookup: the key is `col_meta["field_name"]` when the key `field_name` is present, even when its value is None or `""`, else `name`. The loop runs over every `columns` entry, index entries included, so an index entry whose key equals a data field's name sets that field's dtype. The first entry for a key that sets an extension dtype wins; a later entry for the same key is skipped. An entry skipped by the `StringDtype` rule below sets nothing, so a later entry can still win. The verdict judges the winning entry for `field.name`, and no channel when there is none. No channel when `numpy_type` is in pyarrow's `_pandas_supported_numpy_types` (`int8` to `int64`, `uint8` to `uint64`, `float16`, `float32`, `float64`, `object`, `bool`). Otherwise call `pandas_dtype(numpy_type)`. Any exception gives `malformed`. A result that is not an `ExtensionDtype` with `__from_arrow__` gives no channel. A `StringDtype` on a dictionary field gives no channel (pyarrow skips it). Else the channel fires, and the verdict is `identity` only for:
     - `ArrowDtype` whose `pyarrow_dtype == field.type` (exact type equality, unit and zone included);
     - `StringDtype` on `string`, `large_string` or `string_view`;
     - `ArrowDtype(date64[ms])` on `date32`. The pandas Arrow-backed `date64` writer stores `date32` in Parquet and reads back as `date64[ms][pyarrow]` with the same day (Dennis r11 writer table). The reverse, `date32[day][pyarrow]` on `date64`, is `meaning_change` (round 3).

     Every other fired extension channel is `meaning_change` (Q10, below).
   - *Label channel* (`_deserialize_column_index`, `:960-968`). Lookup: the key is `field_name` when present (even when None), else `_column_name_to_strings(name)`. The last entry for a key wins. The frame label of a field is that entry's `name`, and the field name when no entry has its key. The verdict is `identity` only when `name == field.name`. A `name` that is None, an integer, or another string is `meaning_change`, because the strategy then reads another label or none. A label collision is also `meaning_change`: the descriptor of any other field has `name == field.name` (probe: `df["c"]` then returns a DataFrame). `column_indexes` conversions of labels stay with row ASSEMBLER-LABELS.
   - *Index channel* (`_reconstruct_index`). A field listed in `index_columns` is never in `date_read` (binding excludes stored index fields). The index descriptor structure is part of 3a.

   pyarrow lets `types_mapper` and Arrow extension types take precedence over the descriptor. The verdict ignores that precedence, so it is the same on every route and can only be stricter than a route with a mapper. The verdict judges only fields in `date_read`. A field outside `date_read` is not judged, even when its descriptor changes meaning (main's behavior, follow-up G-21).

   **3c. The projection filter.** A private helper `_projected_meta(table)` in `internal/pandas_compat.py` runs inside `arrow_to_frame` before `to_pandas` when `ignore_metadata` is false. `arrow_to_frame` stays experimental (`contracts/stability.py:67-69`, `docs/compatibility-contract.md:905-906`) and its signature does not change. The helper:
   - returns the table unchanged when there is no blob, when the parser returns `MalformedMeta`, or when any `columns` entry lacks `field_name`;
   - otherwise keeps the `columns` entries whose `field_name` is a field of the table, the string `index_columns` that name a field of the table, and every range object. Present entries stay verbatim, and every other top-level key stays verbatim;
   - returns the table unchanged (same object, no re-serialization) when nothing is dropped, so the blob bytes equal main's;
   - else returns `table.replace_schema_metadata(...)` with the reduced blob. This is zero-copy.

   The filter closes round 4 #3: `select` keeps the original blob, and pyarrow loops over every entry, so a malformed or mismatched descriptor of a projected-away field broke the read. A reduced blob of a well-formed blob is well-formed, because entries keep their keys and an index descriptor leaves with its field. So the admission verdict on the full schema holds for every projection that a route converts. `arrow_to_frame_pair`, `table_to_pandas_exact_ints` and the head readers reach the filter through `arrow_to_frame`.

   **Q10 = A (decided by the owner, 2026-11-28).** A date-read field whose zone channel or extension channel fires with a verdict of `meaning_change` is refused with `runtime/source_date_type_unsupported`, kind `pandas_metadata`, naming the column. This covers E4b through the zone channel (int96 or Spark-flavor Parquet from a zoned column, for example a New York `datetimetz` descriptor on naive `timestamp[ns]`) and E7 through the extension channel (for example `datetime64[ns, UTC]` on `timestamp[us, UTC]`, `Int64` or `period[D]` on `string`). The principle: Decoy never ignores the metadata. It does not drop or rewrite a descriptor to make a column readable. `check_source_dates(x) is x` on every admitted input. The label channel and a malformed blob refuse as before (Q9 = A). Scope: the refusal applies only to date-strategy-read columns (Q9 = A, G-21). An int96 or Spark-flavor column that no date strategy reads keeps main's correct restore (orchestrator reading, owner may overrule; section 15). The option not chosen, B, is in Appendix B.6.
4. **Calendar day (physical).** On a `date64` field in `date_read`, a non-null value `v` with `v mod 86_400_000 != 0` is refused, kind `date64_time_of_day`. On a `date64` field outside `date_read`, rule 5 judges the day that the route's pandas value would carry, decided from the schema and not by a restore:
   - by default the day is `v / 86_400_000` truncated toward zero, which is what a bare Python `date` gets on main's frame conversion and what exact carry keeps (Codex r1, `-62135596800001` ms renders `0001-01-01` on main and stays admitted);
   - when the field's descriptor asks for `ArrowDtype(date64[ms])` (an identity verdict), scalar access floors, so the day is also `floor(v / 86_400_000)` and both days must lie in years 1 to 9999 (Codex r2 #3).

   No other part of the pandas metadata takes part. Exact carry keeps every raw tick. Scan at most 65,536 logical rows per window.
5. **Holdable cells (Q8 = A, every route).** Apply the plain physical domain to non-null logical cells:
   - its instant is a day in calendar years 1 to 9999 (the 4.4a domain, Q1);
   - for `ns`, its instant is not `INT64_MIN`, which pandas reads as `NaT`;
   - for a zoned timestamp, the zone resolves and the local time stays in years 1 to 9999.

   | Type | A non-null cell with physical integer `v` is holdable when |
   |---|---|
   | `date32` | `CALENDAR_FIRST_DAY_NUMBER <= v <= CALENDAR_LAST_DAY_NUMBER` |
   | `date64` | its day (rule 4) lies in that range |
   | `timestamp(unit)`, no zone | `lo <= v <= hi` |
   | `timestamp(unit, zone)` | `lo <= v <= hi`, the zone resolves, and `lo <= v + offset(zone, v) <= hi` with the local time inside years 1 to 9999 |

   `[lo, hi]` is the span from the first tick of year 1 to the last tick of year 9999 in the unit's ticks, intersected with `[INT64_MIN + 1, INT64_MAX]`. For `ns` that is 1677-09-21 00:12:43.145224193 to 2262-04-11 23:47:16.854775807 UTC. `offset(zone, v)` uses the tzinfo that pyarrow gives pandas ("How the zone test is computed" below). Q7 = A: pandas 2.x keeps the source unit, so no pandas 1.x bounds exist.
6. **Refusal, count and text.** A failed cell test or an unresolved zone raises `SourceDateUnrepresentableError` (`runtime/source_date_unrepresentable`). The count is the number of logical rows of this column in this checked input with a non-null value that fails, or with a non-null value in an unresolved zone. An empty or all-null column in an unresolved zone refuses with `count == 0`. The count is kept on the typed error only. A type, dictionary, metadata or time-of-day refusal raises `SourceDateTypeUnsupportedError` with table, column (none for a table-level malformed blob) and kind, and no count. Raise outside any handler. The variable part of every text is the mapping key and column only. Against the rule "the message names only the column", the mapping key (the table) is the only addition. A `pandas_metadata` refusal (E4, E4b, E7) carries no metadata zone (for example `America/New_York`), no `numpy_type` token and no descriptor JSON, in `str`, `repr`, `__cause__`, `__context__`, logs or the isolated child result. Its message is exactly the location text from `source_location_text(table, column)` followed by the fixed sentence, and AT-M2 and AT-M6 assert it by `str(exc) ==` a literal. The fix sentences are fixed strings:

   | Kind | Fix sentence in the message |
   |---|---|
   | `dictionary` | "A date strategy reads this column, and it is dictionary-encoded. Cast it to a plain date or timestamp column." |
   | `pandas_metadata` | "The pandas metadata stored with this table would change this column or cannot be read. Remove or rewrite the pandas metadata, or cast the column to the zoned timestamp type the metadata names." |
   | `date64_time_of_day` | "A date strategy reads this column, and it holds a time of day. Cast it to a plain date32 or timestamp column." |
   | container kinds (Q6) | the revision 4 text, unchanged |

7. **Cost.** Rules 1 to 3 cost one JSON parse per schema and one verdict per date-read field, with no rows read. Empty and populated inputs get the same verdict. Rules 4 and 5 keep the 1 MiB scratch ceiling and the 65,536-row window. No route restores a column twice. The filter is linear in the number of descriptors. AT-V15 keeps the purity and scratch bounds. The elapsed-time check on the scalar no-FK and chunked single-table benchmarks (limit 2.6 s, `tests/perf/test_job_performance_gates.py:246,637`) stays: report baseline, head and headroom.

**Reason decision.** S5a keeps its own code, `runtime/source_date_unrepresentable`, beside #799's `runtime/source_column_unrepresentable`. The set of values is different (S5 refuses dates that pandas can hold, and on routes that never convert), the remedy is different, and it carries a row count. Move the table and column phrase of `_unrepresentable_text` (`_execution_error.py:41-46`) into `source_location_text(table, column)` in the same leaf module. Both error families build their message from it. Registry summaries: `source_date_unrepresentable` "The source date column holds a date outside years 1 to 9999, outside the nanosecond range, or in an unknown time zone"; `source_date_type_unsupported` "The source column holds dates in a type, encoding or pandas metadata the engine does not read". Both codes are `since=UNRELEASED`.

**How the zone test is computed (revision 6, H1, unchanged).** pandas 2 gets its tzinfo from pyarrow's resolver, `pyarrow.lib.string_to_tzinfo(zone)`, which returns a `pytz` zone. `pytz` keeps the last rule after its 2037 table (Sydney +11:00 and Auckland +13:00 at 2262-04-11, Berlin +1:00), rounds local mean time to whole minutes (New York -4:56), and does not know some zones (`Factory`). So:
- Resolve the zone once per judged zoned column, including empty and all-null columns. Catch only `KeyError` and `pa.ArrowInvalid`. Keep pytz imports out of `io`.
- Let `M` be two days in the unit's ticks (largest measured offset 15:56:08, fixed offsets up to 23:59). A cell with `lo + M <= v <= hi - M` is holdable in every resolved zone, and a cell outside `[lo, hi]` is not.
- For band cells take the distinct values (`pc.unique`), build each UTC `datetime` from whole seconds, convert with `astimezone(tzinfo)`, and add the offset back to `v` in integers. An `OverflowError` means not holdable.
- `pc.local_timestamp` and `_fixed_offset_seconds` are not used.

The probe of 14,448 band values over 599 zones and three fixed offsets found 0 disagreements with real conversion (pyarrow 24.0.0, pandas 2.3.3, pytz 2026.2). AT-V13's oracle is the real conversion. The DEP-FLOOR pyarrow 14 leg runs AT-V13, AT-M1 and a one-line import check of `pyarrow.lib.string_to_tzinfo`.

#### Where the check runs (choke point and guards)

Two entry points, one decision site:
- `check_source_dates(data, *, table, date_read)` judges one table or batch (rules 1 to 5). The port wrappers call it: `check_resident_sources` (pipeline, direct OOC, pandas adapter), `checked_loader` (pipeline and direct sequential), `checked_chunks` (`run_mask_pipeline_chunked` and `run_mask_chunked`), `checked_batches` (lazy Parquet) and the profile readers (empty `date_read`). On the port head `a5da43ef9` every wrapper carries on with the returned value.
- `check_source_schemas(schemas, *, date_read_by_table)` judges schemas only (rules 1, 2 and 3), before any read of `pandas_metadata` that a malformed blob can break. It calls the same per-field code as `check_source_dates`.

Give every wrapper and `check_source_schemas` the required keyword `date_read_by_table=`, with an explicit entry for every source table. A missing entry never becomes an empty set.

`check_source_schemas` runs before declaration on every run route:

| Site | Schemas judged | Before |
|---|---|---|
| `execution/_pipeline.py` | resident `sources` schemas and declared `source_loader_schemas` | `_routing_facts` (`DeclarationRequest.for_run` at `_routing_facts.py:75`, which calls `_declared_columns.py` `_supplied` at `:227` through `_run_schemas` at `:393-398`) and the resident fit |
| `execution/_isolated_reason.py` (ISO parent) | the same, by mapping key | `DeclarationRequest.for_run` at `_isolated_run.py:236-237`, writer and spawn |
| `execution/_chunked_input.py` | the first streamed schema | `for_chunks(config, table, source_schema)` at `_chunked_oracle.py:534` (CH) and the NCH entry |

A loader result whose schema differs from its declared schema is judged again by `checked_loader` when it returns. A declared schema that fails refuses with zero loader calls (round 4 #2). The planning snapshot (`physical/_snapshot.py:163`, `for_run`) is not a run route. It keeps main's behavior (follow-up G-20).

**Isolation.** The ISO parent helper in `execution/_isolated_reason.py` runs `check_source_schemas` on original resident and declared schemas immediately before `DeclarationRequest.for_run`. Both ISO modes reach it before declaration, staging or spawn. For an intended spawn it returns `replace(in_process_failure(exc), isolated=True, peak_rss_mb=None, pid=None)` on a typed refusal and None on success. ISO off and worker re-entry use the in-process failure mapper. The call site is one import and one call line in `_isolated_run.py` (597 on main). The effective spawn mode `isolate and not already_isolated` and the failure mapping are computed inside the helper, so the file ends at 599 or below (revision 16 cap, Dennis r1 edit 7). The builder measures it, and moves existing code into the helper if the call needs a second line. The child runs `check_source_dates` on staged cells after its memory limit applies.

**Reads stay main's reads.** Whole-file reads (`LazySource.to_table`, `profile/_readers.py:416`; S3/GCS whole objects, `profile/_cloud_readers.py:273` and `:395`) get `check_source_dates` on the returned table before main's conversion. Batch reads keep the branch's open-time gate on the projected schema (`projected_schema`, `_gate_open`), which runs rules 1 to 3, and check every batch before it is yielded. A schema refusal (E4b, E7 and every other rule 1 to 3 refusal) is raised by the gate when `checked_batches` opens the reader, so no batch is yielded (AT-M2 lazy rows). Do not port `read_table_gated` or the `pyarrow.dataset` import. A file that Arrow cannot decode fails with Arrow's error (G-14).

**Table name.** Unchanged from revision 4: `check_resident_sources` rebinds a lazy source to its `sources` mapping key, the single-source chunked entries use the configured table, and ISO carries the key through the manifest.

**Sentries.**
- **The read sentry** (`tests/sentry/dates/test_source_date_read_guard.py`, kept from the branch). Every function that hands Arrow source data to a conversion is a checked entry or has a per-function allowance with a reason. The sinks are `arrow_to_frame`, `arrow_to_series`, `arrow_to_frame_pair`, `table_to_pandas_exact_ints` and `to_pandas_fk_safe` (`execution/_fk_keys.py`), resolved at their definition, with aliases and the public re-exports in `decoy_engine.arrow_frames` followed. The census is an exact named set with no numeric bound (revision 16 drops `_STOP_AT`, its `LIMITS` entry and its `sentry-limits.json` row):
  - in `internal/pandas_compat.py`, the functions that call the attribute `to_pandas` are exactly `arrow_to_frame`, `arrow_to_series` and the private helper `_first_failing_column`, which only `arrow_to_frame` calls; `arrow_to_frame_pair` and `table_to_pandas_exact_ints` reach `to_pandas` only through `arrow_to_frame` and `arrow_to_series`;
  - outside that module, the set of functions that call a sink equals the checked entries plus the allowances below, both ways. A new caller, a removed caller and a stale allowance each fail.

  Checked entries (S5a wires the check into them or into the reader that feeds them): `profile/_readers.py` `ParquetFileSource.to_frame` and `head_frame_from_batches`; `profile/_cloud_readers.py` `S3ParquetSource.to_frame` and `GcsParquetSource.to_frame`; `profile/_readers_resident.py` `_frame_of`.

  Allowances, by path, function and reason (measured on `8414da35c` by a direct-call scan; the builder repeats the scan with alias resolution and stops and reports if the set differs):

  | Path | Function | Reason |
  |---|---|---|
  | `execution/_chunked_profile.py` | `empty_input_profile` | an empty frame from a gated schema |
  | `execution/_chunked_profile.py` | `walk_one_table` | raw-Arrow helper; its callers are pinned by (module, function) in `_RAW_HELPER_CALLERS` |
  | `execution/_fk_keys.py` | `to_pandas_fk_safe` | the FK conversion wrapper; it is also a sink, so its callers are in the census |
  | `execution/_pipeline_finalize.py` | `compute_fidelity_reports` | fidelity reports over checked inputs and the output |
  | `execution/_unified_slice_evidence.py` | `reconstruct_source_shaped_output` | output shaped from a checked source |
  | `execution/native/_bucket_perturb_ext.py` | `native_bucket_perturb`, `native_range_exceeded` | kernel helpers over a checked chunk |
  | `execution/native/_date_shift_ext.py` | `native_date_shift` | kernel helper over a checked chunk |
  | `execution/native/_operator_step.py` | `_preserved_mask` | kernel helper over a checked chunk |
  | `execution/out_of_core/_bucket_native.py` | `native_bucket_perturb_array` | out-of-core helper over a checked partition |
  | `execution/out_of_core/_mask_group_c.py` | `_to_series` | out-of-core helper over a checked partition |
  | `execution/pipeline/_source_types.py` | `_expected_index` | the stored index of a checked resident source |
  | `execution/pipeline/post_scan/_suite.py` | `suite_frames` | post-scan frames with `ignore_metadata=True` over checked inputs |
  | `generation/_numeric_typing.py` | `generated_table_to_pandas` | generated output, not source data |
  | `verification/postmask/_column_facts.py` | `_read` | post-mask facts over masked output |
- **One decision site.** Outside `io/source_dates.py`, no module constructs `SourceDateUnrepresentableError` or `SourceDateTypeUnsupportedError`, imports the holdable helpers, or calls `descriptor_verdict`. Outside `io/_descriptor_channels.py`, no module under `io/` or `_pandas_meta/` imports `pandas_dtype`. The walk resolves import aliases.
- **One filter.** In `internal/pandas_compat.py`, the only `to_pandas` call that can honor metadata is in `arrow_to_frame`, and its table argument is the result of `_projected_meta`. Seed a direct `to_pandas(table)` in a copy of the module: the sentry fails.
- **Admission before declaration.** An AST order check in `execution/_pipeline.py`, `execution/_isolated_run.py` and `execution/_chunked_input.py`: the `check_source_schemas` call comes before the first `DeclarationRequest.for_run`, `for_chunks` or resident fit call on every path. AT-M4 adds the runtime spy.

#### Behavior matrix

The rule is tested in full at the function, and each route is tested to reach the same function with the right `date_read` and report its answer unchanged. Axes: routes FF and AUTO, SEQ, OOC (Python and native), CH, NCH, PAN (`run`, `run_single`), ISO (on, off), CLOUD, HIVE, PROF; use (date-strategy-read or passthrough); layouts (one chunk, many chunks, sliced with hidden storage, record batch and table, dictionary); zones and units as in revision 14.

| Cell group | Cells | Expected | Acceptance test | Mutation |
|---|---|---|---|---|
| R. Rule | every unit x zone x position, plain, at the function | holdable per rule 5; hidden storage ignored | AT-V12, AT-V13 | M-38 to M-42, M-53 |
| Z. Zone library | Sydney, Auckland, Berlin, New York local mean time, `Factory` | as revision 14 | AT-V12, AT-V13 | M-53 |
| D. Descriptor channels | every date-read Arrow type x writer and mutated descriptors | identity admits; meaning change and malformed refuse, kind `pandas_metadata` | AT-M1, AT-M6 | M-68 to M-70, M-76, M-82, M-84, M-90, M-91, M-93, M-95, M-97 to M-99 |
| W. Writer parity | the genuine writer forms, under `date_shift` and `bucket_perturb`, on every route; int96 and Spark-flavor files on every Parquet route and the batch-open gate; the Spark orphan descriptor | output equals main; int96 read refused at open, unread equals main | AT-M2 | M-66, M-71, M-82, M-86, M-94, M-100, M-102 |
| J. Projection | malformed or mismatched descriptor of a projected-away field | job runs, equals main where main ran | AT-M3 | M-85 to M-87 |
| O. Order | malformed blob or mismatch on a declared loader schema, ISO parent, first streamed schema | typed refusal before declaration, zero loader and writer calls | AT-M4 | M-73, M-74, M-88, M-89, M-96 |
| F. Failure attribution | a date read beside a column pandas cannot hold | #799's code names the other column | AT-M5 | M-92 |
| E. Exotic encodings and kinds | each kind, read and unread | read: refusal with kind and fix sentence; unread: `result is data`, main's outcome | AT-M6, AT-V16, AT-M2 | M-65, M-67, M-71, M-101 |
| L. Layout | each R cell in every plain layout | same decision and count for one checked input | AT-V14 | M-38, M-40 |
| P. Purity and cost | every admitted cell; 10M-row `date32` and `date64` | `check_source_dates(x) is x`; scratch below 1 MiB | AT-V15 | M-45, M-72 |
| T. Type gate (Q6 = A) | containers and the other refused layouts | `source_date_type_unsupported` with kind | AT-V3, AT-V4, AT-V5 | M-21, M-25 to M-27 |
| X. Route reach | the fixture table below | literal outcome per key; exact key count | AT-V16, AT-V1 | M-24, M-36, M-46, M-47 |
| N. Name binding | lazy sources, stale `table=`, ISO manifest | refusal names the mapping key | AT-V7 | M-23, M-37 |
| H. Reads unchanged | HIVE, CLOUD whole object, directory, dotted projection, `columns=["key"]` | Arrow input to conversion equals main's | AT-V17 | M-49 |
| C. Conversion unchanged | admitted plain columns, writer forms, unread date dictionaries, date `CategoricalIndex` | frame and output equal main | AT-V19 | M-66 |
| S. Sentries | read sentry (exact named census and allowances), decision site, filter, order | seeded bypasses fail; a new caller or a stale allowance fails | AT-V8, AT-V18 | M-48, M-51, M-52, M-56 |
| U. Use set | `date_strategy_columns` rows | exact sets | AT-V22 | M-77 to M-80, M-83 |

**Fixture set F for AT-V16.** Unchanged from revision 14 except F11 and F11u. Each fixture is one table `t` with a date column `c` and an `id` column. The config gives `c` a `date_shift` strategy unless the fixture says "unread". Each runs as one chunk and as chunks of two rows.

| Fixture | Column | Expected |
|---|---|---|
| F1 | plain `date32`, 10,004 rows with one year 10183 at row 10,001 | when the reader reaches it, `source_date_unrepresentable`, `t`, `c`, `count == 1` |
| F2 | `dictionary<timestamp[ns, America/New_York]>`, entries `[0, INT64_MIN + 42]` | refused, kind `dictionary` |
| F3 | `dictionary<date32>`, entries `[2020-01-01, 9999-12-31, 0001-01-01]` | refused, kind `dictionary` (E1) |
| F3u | F3, unread | read; output equals `origin/main` |
| F4 | plain `timestamp[us, Asia/Kolkata]`, `9999-12-31T23:00Z` | refused, `count == 1` |
| F5 | plain `timestamp[ns]`, `INT64_MIN` | refused, `count == 1` |
| F5u | F5, unread | refused, `count == 1` (Q8 = A) |
| F6 | plain `timestamp[us, America/Chicago]`, `9999-12-31T06:00Z` | source admits; main's downstream `RowErrorsFailedError` with `format_error` kept |
| F7 | `list<date32>`, dates in range | refused, kind `list` |
| F8 | plain `timestamp[ns, Australia/Sydney]`, `INT64_MAX - 10h` | refused, `count == 1` |
| F9 | `dictionary<date32>`, entries `[2020-01-01, null]` | refused, kind `dictionary` |
| F11 | plain `timestamp[ns, UTC]`, an epoch tick, descriptor `datetimetz` with zone `America/New_York` | refused at the schema on every route, kind `pandas_metadata` (E4, zone channel) |
| F11u | F11, passthrough | not judged; main's outcome on every route (G-21) |
| F12 | plain `date64`, first value 1 ms | refused, kind `date64_time_of_day` |
| F12u | F12, unread | read; output equals `origin/main` |

The route rows, the 462 grid keys, the 6 F10 keys, the 8 literal keys and the 4 isolation keys are those of revision 14 (`115f760e3`). The 8 metadata and index keys keep their inputs. Their expected outcomes: F11's edge form on FF Arrow and NCH refused at the schema; the pandas-written `us` Parquet file on FF and PROF admitted; the `timestamp[us][pyarrow]`, zoned `ArrowDtype` and `date64[ms][pyarrow]` frame on FF Arrow and NCH admitted (every channel identity); the date `CategoricalIndex` on FF Arrow and NCH admitted. Total **488**. For each refusal check the registered code, names-only text with the fix sentence, empty cause and context, and no source value in errors, logs or public results.

#### Tests in detail

Expectations are literal, written from the rules, and never taken from the function under test. Each test records red or green on `origin/main` at the S5a base (`8414da35c` or later, with S5b merged).

- **AT-M1** (`tests/unit/io/test_descriptor_channels.py`, new). The channel oracle, a Hypothesis property with a fixed seed and database, plus pinned rows. For each date-read Arrow type (`date32`, `date64`, `timestamp` `s`, `ms`, `us`, `ns` naive, `UTC`, `Asia/Tokyo`, `+05:30`, `string`, `large_string`, `dictionary<int8, string>`), combine the writer descriptor with mutated descriptors: another zone, `Int64`, `datetime64[ns, UTC]`, `int64`, `period[D]`, `interval`, a garbage `numpy_type`, each missing required key, each key of the wrong JSON type, `name` None, an integer `name`, `name != field_name`, and a second field whose `name` equals the read field. Assertions:
  - verdict `identity`: a populated conversion of the table with the blob at ordinary and near-bound values equals the conversion with `ignore_metadata=True` cell for cell, by exact scalar equality and equal dtype, or equal values for `ArrowDtype` and `StringDtype`; the frame label of the field is `field.name` and `df[field.name]` is a Series;
  - verdict `meaning_change`: `check_source_dates` raises `SourceDateTypeUnsupportedError` with table `t`, column `c`, kind `pandas_metadata`, the fixed sentence, no count, empty `__cause__` and `__context__`; and the oracle confirms that the populated conversion differs, raises, or gives a label other than `c` or a DataFrame for `df["c"]`;
  - verdict `malformed`: the same refusal, and the oracle confirms that `to_pandas` raises;
  - pinned rows: zone channel on naive `timestamp[us]` with `Asia/Tokyo` refused; `ArrowDtype(timestamp[ms])` on `timestamp[us]` refused; `ArrowDtype(date32)` on `date64` refused; `ArrowDtype(date64[ms])` on `date32` identity; `StringDtype` on `dictionary<int8, string>` no channel; `("categorical", "uint64")` on `timestamp[ns]` no channel; `str` no channel; `interval` malformed (`AttributeError` inside pyarrow); `Int64` on `timestamp[ns]` malformed;
  - wrong-type rows (rule 3a, revision 16): on a `timestamp` field with `pandas_type == "datetimetz"`, a truthy non-object `metadata` (`["America/New_York"]`, `"America/New_York"`, `1`) and an object `metadata` whose `timezone` is a truthy non-string (`5`, `["UTC"]`). Each is `malformed`, refused with kind `pandas_metadata`, and the oracle confirms that `to_pandas` raises `AttributeError` or `TypeError` inside `_add_any_metadata`;
  - per-channel lookup rows (rule 3b, revision 16): `field_name` null, `field_name` `""` and `field_name` missing, each with `name == "c"`, a New York `datetimetz` descriptor on `timestamp[ns, UTC]` and, separately, an `Int64` `numpy_type` on `string`. Expected: the zone channel resolves a null or `""` `field_name` by `name` (fires, refused); the extension channel resolves the null or `""` key to no field (no channel); a missing `field_name` resolves by `name` in both channels (fires, refused). Also an index entry with no `field_name`, `name == "c"` and `numpy_type` `Int64`, beside a data field `c` of type `string`: the extension channel gives `c` the `Int64` dtype (refused), and the zone channel resolves that entry to its `index_columns` position, not to `c`. Also two extension entries for a `string` field `c`, the first `string` (`StringDtype`, identity), the second `Int64`: the first wins, so `c` is admitted (a last-wins lookup would refuse). The oracle confirms each against the populated conversion;
  - `pairs_for` guard (revision 16): for every date-read Arrow type in this test's list, each pair in `_pandas_meta/_descriptors.py` `pairs_for(t)`, written as that field's descriptor, gets verdict `identity`. A library bump that adds a pair turns this row red together with `tests/unit/pandas_meta/test_descriptors.py`;
  - lenient view row (revision 16): `pandas_nullable_columns` on every blob of this test, malformed ones included, equals main's function, recorded as literals;
  - runs on pyarrow 24.0.0 here and on 14.0.2 in the DEP-FLOOR leg. If the leg disagrees, the leg fails.
- **AT-M2** (`tests/unit/execution/source_dates/test_writer_parity.py`, new). Writer parity, red-first. Inputs: the eight writer forms of revision 14 (object naive and UTC datetimes, ns datetimes to `date32` and to UTC `us`, NumPy int32 to `date32`, int64 to UTC `us`, categorical of timestamps after Parquet, `ArrowDtype` `date64` after Parquet), both round 4 #1 dictionary forms (`("categorical", "object")` and `("categorical", "string")` on `dictionary<int8, string>` text dates), the `infer_string` large_string writer, a fastparquet categorical-text file and a fastparquet-style blob with no `field_name`. Under `date_shift` and `bucket_perturb` with fixed config and seed, on FF, SEQ batches, NCH native, ISO on and exact carry: source admitted, and the output equals main's output recorded as literals in the test. Add the passthrough sibling F11u (equals main) and the int96 rows. Inputs: Parquet written with `use_deprecated_int96_timestamps=True` and, separately, with `flavor="spark"` from a zoned New York column. Each gives naive `timestamp[ns]` with a `datetimetz` New York descriptor. Routes: the routes above, plus lazy Parquet (`sources={"t": LazySource(path)}`) on FF, AUTO, SEQ and OOC, a CLOUD whole object (S3 and GCS fakes) and a HIVE directory, and the batch-open gate through `checked_batches`. Expected:
  - read by `date_shift` (E4b, Q10 = A): refused, kind `pandas_metadata`, on every route. Main restores the zone correctly. On a batch route the refusal is raised when `checked_batches` opens the reader, and a spy on the batch iterator records zero yielded batches;
  - the refusal text: `str(exc)` equals the literal location text for table `t` and column `c` followed by the `pandas_metadata` fix sentence. `America/New_York`, the descriptor's `numpy_type` token and any substring of the descriptor JSON are absent from `str(exc)`, `repr(exc)`, `__cause__`, `__context__`, the captured logs and, on ISO on, the isolated child result;
  - unread (Q10 scope): the column is admitted and the output equals main on every route above, with main's restored zone.

  Also the Spark orphan-descriptor row (revision 16): a pandas-written file with a column `my col` and a New York `datetimetz` descriptor, rewritten by Spark, which renames the field to `my_col` and keeps the blob, so the descriptor's `field_name` stays `"my col"`. No field resolves to that descriptor in any channel, so no channel fires, and main reads `my_col` as naive UTC. Read by `date_shift` on `my_col`: admitted, and the output equals main. `_projected_meta` drops the orphan entry, and the frame equals main's frame.
- **AT-M3** (`tests/unit/profile/source_dates/test_projected_meta.py`, new). Projection. A Parquet file with a valid date column `c` and a field `x` whose descriptor is malformed (missing `numpy_type`) or mismatched (zone channel):
  - `head_frame_from_batches`, the resident and lazy profile readers and the FF route with `x` projected away succeed (red on main: `KeyError` or wrong conversion), and the frame equals the conversion of the same projection with only the present descriptors;
  - with `x` as a date read the job refuses, kind `pandas_metadata`;
  - parity: on 15 cases (Index, RangeIndex and MultiIndex sources, five projections each), `_projected_meta` output converts to the same frame as main;
  - when nothing is dropped, `_projected_meta(t) is t`.
- **AT-M4** (`tests/unit/execution/source_dates/test_admission_order.py`, new). Order. Malformed JSON, and separately a zone mismatch on `c`, in a declared `source_loader_schemas` entry of a date job: typed refusal, zero loader calls, and a spy on `DeclarationRequest.for_run` records no call. A valid declared schema with a loader result whose blob is malformed: refused at the loader result. A job with no date reads and malformed JSON keeps main's `JSONDecodeError` (recorded on main). Run the four malformed ISO cases on `run_pipeline_isolated` with `isolate=False` and `isolate=True`: registered reason, kind, value-free text, no writer or spawn call, and on ISO on `peak_rss_mb is None` and `pid is None`. On CH and NCH the first streamed schema with a mismatch refuses before `for_chunks` (spy).
- **AT-M5** (`tests/unit/execution/source_dates/test_failure_attribution.py`, new). A `date32` date read beside a bare `time64[ns]` column at tick 1 on FF: `full_frame_value_unrepresentable` naming the time column, as main. No `pandas_metadata` refusal (round 4 #4).
- **AT-M6** (`tests/unit/io/test_source_date_encodings.py`, rewritten). Earlier rounds and the kinds:
  - year 2300 on `timestamp[us, UTC]` with a New York `datetimetz` descriptor: refused at the schema, on FF and on a batch route with the bad row in batch two (refused at open, no batch yielded);
  - `date64` −1 ms as a read target: kind `date64_time_of_day`; unread: admitted, FF gives main's day and exact carry keeps the raw tick; `-62135596800001` ms unread with no descriptor: admitted, FF renders `0001-01-01` as main; the same with an `ArrowDtype(date64[ms])` descriptor: `source_date_unrepresentable`, count 1;
  - `date32[day][pyarrow]` descriptor on physical `date64`: refused, kind `pandas_metadata`;
  - string `2020-01-01` with `Int64` and with `int64[pyarrow]` (E7, Q10 = A): refused as target and as `windowed_date` anchor. `str(exc)` equals the literal location text and fix sentence, and the `numpy_type` token and descriptor JSON are absent from `str`, `repr`, cause, context and the captured logs. The same on ISO on for the isolated child result;
  - each kind (`dictionary`, `pandas_metadata`, `date64_time_of_day`) on an empty column, an all-null column and a populated column: the same verdict;
  - each refusal: rule 6 text, no value, empty cause and context.
- **AT-V22** (`tests/unit/execution/source_dates/test_date_strategy_columns.py`, the use rows of revision 14's AT-V21, unchanged): mixed config, `when:` gate, `nested` child, composite provider, `windowed_date` anchor, `bucket_perturb`, the `K` and U+212A binding, and direct `PandasExecutionAdapter.run` and `run_single` calls.
- **Kept from revision 14:** AT-V1, AT-V3 to AT-V5, AT-V7 to AT-V9, AT-V12 to AT-V14, AT-V16 (fixture set above), AT-V17, AT-V18 (adds the filter rule and the order rule) and AT-V19. AT-V15 keeps purity and the scratch bound and drops the restore timings.
- **Removed:** AT-V20 (restore soundness) and AT-V21 (replaced by AT-M1 to AT-M6 and AT-V22). Also removed: the populated restore wrapper, its comparison and attribution, the extra restore before native kernels, the sibling-restore guard and the checked-frame reuse instrumentation.

Red-first expectations: F5 becomes `NaT` on main where converted and F8 scalar access fails; F2, F3, F9, F11 and F12 are red by design (Q9 = A); AT-M3 is red on main (projected-away failure); AT-M4 is red on main (`JSONDecodeError` before declaration); AT-M2 and AT-M5 are green on main except the int96 and Spark-flavor read rows on every route (E4b, Q10 = A). Re-pin every E-cell of section 0.1 on main both ways.

#### What the S5 branch keeps and what it discards

**Port method.**
1. Port S5b first (section 4.4c). Build S5a-1a on a fresh branch from main containing #799, #830 and the merged S5b. Build 1b, 1c and 2 in order.
2. For a file that main and the branch both changed since `9812da814`, re-apply only the S5 hunks by hand (`git diff 9812da814 a5da43ef9 -- <path>`). Never run `git checkout a5da43ef9 -- <path>` on these files. They are (recomputed on `8414da35c` as the intersection of `git diff --name-only 9812da814 origin/main` and `git diff --name-only 9812da814 a5da43ef9`): `CODEMAP.md`; `docs/strategies.md`; `execution/_chunked_profile.py`, `_pandas_adapter.py`, `_pipeline_finalize.py`, `_sequential.py`; `execution/native/_chunked_entry.py`; `execution/pipeline/_source_types.py`; `internal/pandas_compat.py`; `profile/_cloud_readers.py`, `_lazy_build.py` (#827), `_readers.py`, `_readers_resident.py`, `_source.py` (#827); `tests/native/test_chunked_entry_rev9_shapes.py`, `tests/native/test_chunked_entry_values_schema.py`; `tests/sentry/file_access_registry.toml`; `tests/unit/execution/run_stream/test_lazy_input.py`; `tests/unit/profile/test_supplied_table_profiling.py`. The S5b overlaps are on this list too, re-applied onto S5b's version after S5b merges: `_arrow_types.py` (S5b owns `CALENDAR_FIRST_DAY_NUMBER` and `CALENDAR_LAST_DAY_NUMBER`; S5a drops the port's duplicate), `reason_adapter.py` (`_CODED`: S5b adds the `FittedRangeError` row, S5a adds its two rows), `CODEMAP.md` and `docs/strategies.md`. Recompute the list on the S5a base head before porting, and add any new intersection.
3. A file main has not changed since `9812da814` may be taken whole from `a5da43ef9`, then edited. Check with `git diff --quiet 9812da814 origin/main -- <path>`.
4. Do not cherry-pick.

| Keep (port, then edit) | Discard |
|---|---|
| `_arrow_types.py` (date leaf, shape classifier, unclassified layouts, type walker), hunks only onto S5b's file; the calendar constants come from S5b | `internal/pandas_compat.py` branch changes (working categorical, `WorkingInstant`, `stored_index_names`, `table_to_pandas`, `_refuse_unholdable`). Main's file gets only `_projected_meta` |
| `io/source_dates.py`: schema gate, `_holds_dates`, `checked_batches`, lazy binding, `check_resident_sources`, `checked_loader`. Edit: drop `_repaired_dictionary`, `_without_unused_bad_entries`, `_fixed_offset_seconds`, the dictionary entry tests and the row-decoding count; add `date_read`, rules 2 to 4, `check_source_schemas` and the resolver band test | `safe_output/_date_buffers.py`, the `output_table` change, the `execution/chunked/_progress.py` hook |
| `io/bounded_reader.py` errors, `io/__init__.py` exports, the two reasons in `reasons/runtime/_part3.py`, the two `reason_adapter._CODED` rows | `fileaccess/adapters/arrow.py` `read_table_gated` and the `pyarrow.dataset` import |
| Entry wiring: `_isolated_reason.py` helper and its call in `_isolated_run.py`, `_chunked.py`, `_chunked_input.py`, `_isolated_commit.py`, `_isolated_worker.py`, `native/_chunked_entry.py`, `out_of_core/_runner.py`, `execution/_pipeline.py` | `execution/pipeline/_source_types.py`, `execution/_pipeline_finalize.py` and `_post_scan.py` branch changes: they keep main's code, and the filter inside `arrow_to_frame` covers them |
| Profile: `_lazy_build.py`, `_source.py` (table name) and the shared profile hunks (check call only) | `profile/_readers_resident.py` fallback rewrite |
| `fileaccess/adapters/arrow.py` walker move and `projected_schema` | `safe_output/_file_metadata.py` list-view rows (to DEP-FLOOR) |
| Branch tests per revision 14 (`tests/native/_rev9_*`, `tests/unit/io/` type gate, classifier, nested, vocabulary, `test_checked_source_dates.py` with the rule 4 edits above, the `tests/unit/execution/source_dates/` route tests) | the branch's dictionary repair tests, `test_working_categorical.py`, `test_no_import_time_timestamps.py`, `test_date_buffers_ipc.py`, `test_resident_fallback_dates.py`, `test_whole_file_gate_q6a.py`, `test_source_date_reports_r1.py`, `tests/sentry/test_signed_evidence_file_access.py` |
| `test_source_date_read_guard.py` moved to `tests/sentry/dates/`, with main's sinks, the exact named census and allowance table (no numeric bound), the decision-site, filter and order rules | the bare-statement rule (old M-29) |
| `_execution_error.py`: extract `source_location_text` (about 10 lines) | |

New code on main, listed separately in the builder report: `_pandas_meta/_source_meta.py`, `io/_descriptor_channels.py`, `_projected_meta`, `check_source_schemas` and its three call sites, `date_strategy_columns`, the ISO helper, AT-M1 to AT-M6. Give every path of `git diff --name-only 9812da814 a5da43ef9` (75 files) a disposition (keep, discard or S5b) before porting.

#### Size and slices

Each PR permits at most 799 new-for-review lines. Count re-applied shared-file hunks in full. Files taken whole from `a5da43ef9` are reviewed as a port diff against that commit and counted apart. At 800 new-for-review lines the builder stops and reports.

| Slice | Content | Taken whole | New for review | Estimate |
|---|---|---|---|---|
| S5a-1a | Parser (`_source_meta.py`), channel verdict (`_descriptor_channels.py`), filter (`_projected_meta`), type gate, rules 2 to 4 at the function, both reasons, adapter rows, changelog ("not raised by any route yet"), AT-M1, AT-M3 (unit part), AT-M6 (function part), AT-V3, AT-V9 | about 900 | about 550 | one day |
| S5a-1b | `check_source_schemas`; resident, loader, declared loader schema, FF/PAN and ISO wiring; seed extraction; `date_strategy_columns`; AT-M4, AT-M5, AT-V22, the resident AT-V16 keys, the order sentry | part of the wiring port | about 450 | one day |
| S5a-1c | Streaming, native, profile, cloud and Hive wiring; AT-M2, AT-M3 (route part), AT-V4, AT-V5, AT-V7, AT-V8, AT-V17, AT-V18, the remaining AT-V16 type and encoding keys, the E-cell re-pin | balance of the wiring port | about 450 | one day |
| S5a-2 | Rule 5 domain, resolver and count, AT-V1, AT-V12 to AT-V15, AT-V19, 4.4a edits, remaining AT-V16 keys | about 700 | about 650 (AT-V20 removed) | one day |

S5a-1a has only test callers. Its two pending reasons trigger `test_every_live_pending_identity_is_named_by_a_fragment`, so ship `changelog.d/date-range-s5-source-dates.md` in S5a-1a with both code spans. S5a-1a also ships an "Experimental:" fragment for the `arrow_to_frame` blob filter. 1b, 1c and 2 extend the S5a fragment.

**Per-file line budget.** Repo rule: modules aim for 600 lines; above 600 needs a census entry with a ceiling (`tests/sentry/test_module_size.py`), and a file above the ceiling may only shrink. "Main" is `8414da35c` (with S5b's change where S5b touches the file). "Port" is `a5da43ef9`. "After" is the S5a-2 head.

Revision 16 rule (Dennis r1 edit 7): every touched file over 600 lines on main has net zero growth, and S5a adds or raises no census entry. Where S5a must add a line to such a file, the builder moves at least as many existing lines out of it in the same slice (into `_column_access.py`, the ISO helper in `_isolated_reason.py`, `_chunked_input.py` or `io/source_dates.py`), so the file ends at or below its main length. The binding of `date_read` (work list, grouping, seed extraction) lives in `_column_access.py`, and the ISO admission lives in the `_isolated_reason.py` helper, never in the large callers.

| File | Main | Port | After (estimate) | Note |
|---|---|---|---|---|
| `_pandas_meta/_source_meta.py` | new | n/a | about 140 | pyarrow and `_canonical` only |
| `_pandas_meta/_columns.py` | 56 | 56 | about 65 | reads from `SourceMeta` |
| `_pandas_meta/__init__.py` | 33 | 33 | about 38 | exports |
| `io/_descriptor_channels.py` | new | n/a | about 120 | `io` holds 4 modules on the port; cap 25 |
| `io/source_dates.py` | new | 319 | about 430 | |
| `io/bounded_reader.py` | 413 | 455 | about 460 | fix sentence |
| `io/__init__.py` | 39 | 55 | about 57 | |
| `internal/pandas_compat.py` | 359 | 334 (discarded) | about 385 | main's file plus `_projected_meta` |
| `_arrow_types.py` | 254 (259 with S5b) | 349 | about 349 | S5b's constants kept; the port's duplicate dropped |
| `execution/_column_access.py` | 544 | 544 | about 580 | |
| `execution/_isolated_reason.py` | 112 | 112 | about 150 | |
| `execution/_isolated_run.py` | 597 | 597 | at most 599 | one import and one call line; the spawn mode and the failure mapping are computed in the helper. If the call needs more lines, move existing code into `_isolated_reason.py` |
| `execution/_pipeline.py` | 361 | 365 | about 375 | |
| `execution/_chunked_input.py` | 513 | 532 | about 545 | |
| `execution/_pandas_adapter.py` | 676 (ceiling 700) | 678 | at most 676 | net zero: the work-list build and `date_read` binding are one call into `_column_access.py`; offset every added line by moving code out |
| `execution/_sequential.py` | 680 (ceiling 680) | 680 | at most 680 | net zero, same rule |
| `execution/native/_chunked_entry.py` | 621 (ceiling 641) | 689 | at most 621 | net zero, same rule; the check call goes through `_chunked_input.py` |
| `out_of_core/_runner.py` | 393 | 395 | about 400 | |
| `profile/_readers.py` | 597 | 599 | at most 599 | call lines only; move any helper into `io/source_dates.py` |
| `profile/_cloud_readers.py` | 472 | 484 | about 486 | |
| `profile/_readers_resident.py` | 43 | 57 | 57 | |
| `profile/_lazy_build.py`, `profile/_source.py` | 142, 409 | hunks re-applied (#827) | about main plus the table-name hunks | |
| `profile/_declared_columns.py`, `execution/pipeline/_routing_facts.py` | 551, 117 | same | unchanged | reached through `stored_index_fields` |

New test modules stay under 600 lines each. Keep the current ceilings and pins. S5a adds no bound row: no `LIMITS` entry and no `sentry-limits.json` row.

#### What is not S5

| Item | Where it goes | Why not S5 |
|---|---|---|
| The output assembler mixes pandas display labels with Arrow field names (`execution/pipeline/_source_types.py`, round 6), and `column_indexes` can turn labels into integers | Row ASSEMBLER-LABELS | Reproduces on main with ordinary data |
| Two resolvers read the stored index (`execution/pipeline/_source_types.py` and `_pandas_meta/_columns.py`) | Structure review list, or ASSEMBLER-LABELS | Pre-existing duplication |
| The engine does not import at the declared floors, and the channel functions of `pyarrow/pandas_compat.py` must be diffed between 14.0.2 and 24.0.0 | Row DEP-FLOOR | Pre-existing; independent of dates |
| Malformed blob on a job with no date reads; the planning snapshot read | G-20 (V2-LOG) | Main's behavior kept |
| A descriptor that changes the meaning of a passthrough sibling | G-21 (V2-LOG) | Main's behavior kept |
| Disjoint dictionary union in carried profile and AUTO join | G-16 (log) | Separate from conversion |
| Hidden storage outside a slice serialized to IPC | G-12, V2-LOG | The caller's own data |
| A Parquet file Arrow cannot decode | G-14, log | Pre-existing |
| The resident profile fallback drops a stored index | G-15, log | Pre-existing |

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
| S5 rule tests (4.4b, revision 15) | `tests/unit/io/test_source_date_hold_rule.py` (AT-V12 to AT-V15), `tests/unit/io/test_descriptor_channels.py` (AT-M1), `tests/unit/io/test_source_date_encodings.py` (AT-M6), `tests/unit/execution/source_dates/` (AT-M2, AT-M4, AT-M5, AT-V16, AT-V19, AT-V22), `tests/unit/profile/source_dates/` (AT-M3, AT-V17) | `tests/unit/io/` has 3 modules, so the io tests stay flat. `tests/unit/execution/` (266 modules) and `tests/unit/profile/` (37) are over the 25-module rule (owner 2026-11-06), so the route tests go in named sub-packages (next row) |
| New test sub-packages (revision 11, Dennis S5a-H3 and S5b-H1) | `tests/sentry/dates/` (the read guard and the S1 date partition sentry), `tests/unit/execution/source_dates/`, `tests/unit/profile/source_dates/`, `tests/parity/date_range/` (S1, 162 flat modules in `tests/parity/`), `tests/unit/transforms/date_domain/` (S1, 26 flat modules). S5b uses the existing `tests/sentry/generation/` and `tests/unit/generation/statistical/` | each new sub-package gets an `__init__.py` and a CODEMAP row in the slice that creates it, as `tests/sentry/generation/` has (CODEMAP.md:177). No new module goes in a flat folder over 25 modules |
| Use set | `date_strategy_columns` and `DATE_STRATEGIES` in `execution/_column_access.py` (544 lines, about 580 after) | the one declaration of which columns each entry reads; `execution/` is frozen at 102 modules |
| S5a metadata parser (4.4b rule 3a) | `_pandas_meta/_source_meta.py` (new, about 140 lines), exported from `_pandas_meta/__init__.py` | bottom tier beside `stored_index_fields`; imports only pyarrow and `_canonical` (package docstring) |
| S5a channel verdict (4.4b rule 3b) | `io/_descriptor_channels.py` (new, about 120 lines), called only from `io/source_dates.py` | needs `pandas.api.types.pandas_dtype`, which `_pandas_meta` may not import; `io` holds 4 modules on the port (cap 25) |
| S5a projection filter (4.4b rule 3c) | `_projected_meta` in `internal/pandas_compat.py` (about 25 lines) | the one conversion module; `internal` (tier 4) may import the bottom tier |
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
- S5 documents which source columns are read: plain date and timestamp columns on every route, judged by one rule (Q8 = A). A column holding a date inside a list, map, struct or other container is refused with `runtime/source_date_type_unsupported` whatever its dates are, with the remedy (drop, select out or cast the column). A date strategy can still read text dates with ordinary writer metadata. For a date-strategy target or window anchor, a date dictionary, pandas metadata that is malformed or would change the column (rule 3), or a `date64` with a time of day is refused with its kind and fix sentence. Pandas metadata of columns no date strategy reads is not judged, and descriptors of fields a read does not select are dropped before conversion. It states the Q8 x Q9 asymmetry in plain words: a far plain date is refused on every column, but the same far date in a dictionary on an exact-carry column is carried as before (section 0.2). It names the `ns` and zoned limits in plain words, and it lists E1 to E6 and E3b from section 0 and the Q8 = A passthrough narrowings (comparison rows 8, 9, 13 and 14 for plain cells, Appendix B.1). Under Q8 = A a zone must resolve even on an empty or all-null column. It replaces the S5 branch paragraph at `a5da43ef9:docs/strategies.md:403-405` and lands on main as a new `#### Dates outside the calendar` subsection before `### bucketize` (`docs/strategies.md:399` on `8414da35c`), re-applied onto S5b's version of the file. S5b adds one sentence: the legacy fitted distribution sampler refuses a fitted bound outside 1677-09-22 to 2262-04-10, or a live year bin outside its fitted min and max years, with `plan/generation_unbounded_column`. Both the S5a changelog and `docs/strategies.md` give the E4b example (int96 or Spark-flavor Parquet from a zoned column) and its fix in the words of the rule 6 sentence (remove or rewrite the pandas metadata, or cast the column to the zoned timestamp type the metadata names), and the Q10 = A answer: Decoy never ignores the metadata of a date-read column, and an unread int96 column keeps main's restore.
- In S5a update #799's paragraph on `run_mask_chunked` and `run_mask_pipeline_chunked` in `docs/compatibility-contract.md`.
  The date check can raise `SourceDateUnrepresentableError` (`runtime/source_date_unrepresentable`) or
  `SourceDateTypeUnsupportedError` (`runtime/source_date_type_unsupported`) at the source boundary, including on NCH
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
| a date dictionary, pandas metadata that is malformed or would change the column (rule 3, schema only), or a `date64` with a time of day on a column a date strategy reads (S5, Q9 = A) | the strategy receives a converted column, or a coded or value-bearing conversion error (E1 to E7, E3b) | refusal `runtime/source_date_type_unsupported` with kind `dictionary`, `pandas_metadata` or `date64_time_of_day` and the fix sentence |
| the same encodings on a column no date strategy reads (S5, Q9 = A) | main's behavior | not judged; descriptors of fields outside a conversion's projection are dropped before conversion (rule 3c) |
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
- AT-V12 to AT-V19, AT-V22 and AT-M1 to AT-M6: specified in section 4.4b (rule, layout, purity, route fingerprint, reads unchanged, decision site and the exact read census, conversion unchanged, use set, metadata check).

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
| M-51 | S5: add a function outside `internal/pandas_compat.py` that calls `arrow_to_series` and is in neither the checked entries nor the allowance table | AT-V18 census equality (new caller) |
| M-52 | S5: keep the `_read` allowance of `verification/postmask/_column_facts.py` after its sink call is removed | AT-V18 census equality (stale allowance) |
| M-53 | S5: compute the band offset with `zoneinfo.ZoneInfo(zone)` instead of pyarrow's resolver | AT-V12 Sydney and Auckland rows, AT-V13, F8 |
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
| M-65 | S5a: refuse a read date dictionary only when an entry fails the cell rule | AT-V16 F3 (in-range dictionary refused), AT-M6 dictionary rows |
| M-66 | S5a: judge the descriptor of every date-typed field, not only `date_read` | AT-M2 F11u and int96 unread rows (equal main), AT-V16 F11u, AT-V19 |
| M-67 | S5a: decide the `dictionary` and `pandas_metadata` kinds from values, so empty and all-null columns pass | AT-M6 empty and all-null rows, AT-V16 isolation keys |
| M-68 | S5a: drop the zone channel test | AT-M1 naive `timestamp[us]` with `Asia/Tokyo` row (oracle shows the zone change), AT-M6 year-2300 refusal |
| M-69 | S5a: fire the zone channel only when the zone strings differ by unit or case, not by exact string inequality (any changed rule that admits `America/New_York` over UTC) | AT-V16 F11, AT-M2 int96 read row |
| M-70 | S5a: count every fired extension channel as identity | AT-M1 `datetime64[ns, UTC]` on `timestamp[us, UTC]` row, AT-M6 `Int64` on string |
| M-71 | S5a: the `date64` time-of-day test reads only the extrema | AT-M6 interior row |
| M-72 | S5a: the `date64` scan builds one full-length modulo array | AT-V15 date64 operand-length bound |
| M-73 | S5a: pass an empty `date_read_by_table` at one site at a time: each resident call (port head `_pipeline.py:298`, `out_of_core/_runner.py:195`, `_pandas_adapter.py:190`), each loader call (`_pipeline.py:291`, `_sequential.py:294`), each `checked_chunks` call (`_chunked.py:459`, `native/_chunked_entry.py:438`), `OpenedLazyBatches.__init__ → checked_batches` (profile/_readers.py:196), `LazySource.iter_batches → checked_batches` (:269), and the ISO parent | For each non-Parquet site AT-M4 drives that wrapper with a read F3 or F11 and checks the physical read set at the first check and its typed refusal. For the two Parquet calls mutate each independently. Use a schema-admitted plain read column, spy on the arguments of each actual checked_batches invocation, consume a batch and assert its physical read set at batch admission. An open-time F11 refusal cannot prove either forwarding site. Use the AT-V16 pre-writer spy on ISO; also each `check_source_schemas` site (`_pipeline.py`, `_isolated_reason.py`, `_chunked_input.py`) one at a time, killed by AT-M4 |
| M-74 | S5a: the ISO parent leaves the schema rules to the child | AT-V16 isolation keys (the writer spy records a call) |
| M-76 | S5a: identity by dtype kind (any `ArrowDtype` timestamp or date) instead of exact `pyarrow_dtype == field.type` | AT-M1 `ArrowDtype(timestamp[ms])` on `timestamp[us]` and `ArrowDtype(date32)` on `date64` rows |
| M-77 | S5a: `date_strategy_columns` drops the `windowed_date` anchor | AT-V22 anchor row |
| M-78 | S5a: `date_strategy_columns` drops `bucket_perturb` from `DATE_STRATEGIES` | AT-V22 `bucket_perturb` row |
| M-79 | S5a: `date_strategy_columns` counts a `nested` entry's JSON child `date_shift` as a read of the parent column | AT-V22 nested row |
| M-80 | S5a: `date_strategy_columns` skips entries with a `when:` gate | AT-V22 `when:` row |
| M-81 | S5b: run the live-year rule on inverted bounds | `test_max_before_min_emits_nat` fails on a `year_bins` refusal |
| M-82 | S5a: drop the `ArrowDtype(date64[ms])` on `date32` identity | AT-M2 `ArrowDtype` date64 after Parquet writer row (admitted, equals main), AT-M1 pinned row |
| M-83 | S5a: read `strategy` before `_is_composite` | AT-V22 composite provider with `strategy: date_shift` |
| M-84 | S5a: make the date identity symmetric, so `ArrowDtype(date32)` on `date64` is identity | AT-M6 `date32[day][pyarrow]` on `date64` refusal |
| M-85 | S5a: `_projected_meta` keeps descriptors of absent fields | AT-M3 projected-away malformed `x` on `head_frame_from_batches` (raises `KeyError` again) |
| M-86 | S5a: `_projected_meta` drops a present descriptor, or re-serializes the blob when nothing is dropped | AT-M2 writer parity (dtype differs from main), AT-M3 15-case parity and the `is t` assertion |
| M-87 | S5a: `_projected_meta` drops range objects from `index_columns` | AT-M3 RangeIndex cases (index differs from main) |
| M-88 | S5a: `check_source_schemas` skips declared `source_loader_schemas` | AT-M4 zero loader calls (the loader spy records a call) |
| M-89 | S5a: move `check_source_schemas` after `DeclarationRequest.for_run` | AT-M4 (`JSONDecodeError` escapes, the `for_run` spy records a call), order sentry |
| M-90 | S5a: drop the label channel test (`name != field.name` admitted) | AT-M1 `name` None, integer `name` and renamed rows |
| M-91 | S5a: drop the label collision test | AT-M1 collision row (`df["c"]` is a DataFrame) |
| M-92 | S5a: turn a conversion failure on a table with date reads into `pandas_metadata` | AT-M5 (`full_frame_value_unrepresentable` naming the time column) |
| M-93 | S5a: treat a missing `field_name` as malformed | AT-M2 fastparquet-style blob row (admitted, equals main) |
| M-94 | S5a: count `StringDtype` on a dictionary field as a fired channel | AT-M2 round 4 #1 dictionary rows (admitted, equal main) |
| M-95 | S5a: judge the extension channel from `pandas_type` spellings instead of `pandas_dtype(numpy_type)` | AT-M1 property (garbage `numpy_type` and `interval` rows must be malformed) |
| M-96 | S5a: let a malformed blob on a table with date reads fall through to main's parse | AT-M4 malformed JSON (typed refusal expected, `JSONDecodeError` seen) |
| M-97 | S5a: treat a truthy non-object `metadata` or a non-string `timezone` as no zone channel instead of malformed | AT-M1 wrong-type rows |
| M-98 | S5a: resolve the extension channel with the zone channel's truthy `field_name` lookup | AT-M1 `field_name` null and `""` rows |
| M-99 | S5a: resolve extension descriptors over data entries only, or let the last entry win | AT-M1 index-entry `Int64` row and the first-wins row |
| M-100 | S5a: check the schema of a lazy Parquet source on the first batch instead of at open | AT-M2 lazy int96 rows (a batch is yielded) |
| M-101 | S5a: put the metadata zone in the `pandas_metadata` refusal text | AT-M2 int96 exact `str(exc)` row, AT-M6 E7 row |
| M-102 | S5a: refuse an int96 column that no date strategy reads | AT-M2 int96 unread rows (equal main) |


## 8. Frozen contracts and byte changes

- New reason `runtime/date_outside_strategy_range` (`since=UNRELEASED`), error class `DateRangeError` (public, beside `WindowedDateError`), named in the S1 changelog fragment.
- Deprecated with `replaced_by=("runtime", "date_outside_strategy_range")`: `runtime/out_of_core_bucket_perturb_date_out_of_native_range` (S1), `runtime/windowed_date_anchor_out_of_range` (S3). Deprecated with `replaced_by=None` (allowed by `reasons/_registry.py:202-209`, section 4.3): `plan/date_preserve_values_with_group_by_unsupported` and `runtime/date_preserve_values_with_group_by_unsupported` (S2).
- New reason `runtime/source_date_unrepresentable` (`since=UNRELEASED`, S5a), kept beside #799's `runtime/source_column_unrepresentable` for the reasons in section 4.4b. Its summary and remediation name the calendar years, the `ns` limit, the zoned local-time test, and the type reason's remediation names each kind's fix. Both messages build their table and column phrase from one helper, `source_location_text` in `_execution_error.py`.
- The S5a changelog records the Q8 = A narrowings for plain cells: zoned ns edges (row 8), plain or UTC `INT64_MIN` ns (row 9), out-of-calendar local times that pandas can read (row 11), and the passthrough returns of rows 13 and 14 (Appendix B.1), on NCH and on CH passthrough where main preserves them. It records E1 to E6 and E3b from section 0 for date-strategy-read columns, including both Parquet unit-coercion writer controls and the actual lossy companion. It distinguishes exact carry from a populated sibling restore and lists the round 3 examples.
- Amend #799's `run_mask_chunked` and `run_mask_pipeline_chunked` paragraph in `docs/compatibility-contract.md` with
  the two date codes, their exception classes and the NCH narrowing specified in 4.7. Update the dispatcher's
  matching date examples and keep #830's detector paragraph.
- New reason `runtime/source_date_type_unsupported` (`since=UNRELEASED`, S5a-1a, section 4.4b) and public error class `SourceDateTypeUnsupportedError`. Behavior: a source column holding a date inside a selected container is refused under Q6 = A. A date-strategy-read column that is a date dictionary, has pandas metadata that is malformed or would change it (rule 3, schema only), or holds a `date64` time of day is refused under Q9 = A with kind `dictionary`, `pandas_metadata` or `date64_time_of_day`. The kind tokens are part of the frozen text contract.
- S5b: `FittedRangeError` (code `generation_unbounded_column`, public namespace `plan`, attribute `prop`) is a new coded error with one `_CODED` row. The QA F7 behavior of `ColumnGenerator.generate_column` changes from a clamp to a refusal for a live year bin outside the fitted years (changelog, section 4.4c Fix 3). Statistical plan compile and `sample_column` refuse a live bin past 9998 with `plan/generation_unbounded_column` where main failed at draw time uncoded (changelog).
- Post-mask report: new per-column field `declared_sentinel_rows` (S6, additive).
- Config and snapshot: S7 admits preserve_values on date generators. Store optional stats.sentinels beside year_bins within distribution-snapshot/v2. Only bucket entry models forbid extra fields (contracts/distribution_snapshot.py:47,58,68). Existing v2 readers ignore the new field and emit no sentinel from it. An all-sentinel fit has no ordinary distribution for an older reader to sample. Round-trip old and new snapshots, exercise the pre-S7 reader, and run the full engine suite for this writer change.
- Config: `preserve_values` becomes valid on `windowed_date` (S3, additive). No other config key changes.
- Behavior: far dates that were `format_error` row errors become refusals; typed edge sentinels that were shifted become refusals. Logical output for in-range and declared rows is unchanged (AT-R1, AT-R2 digests against base). S5 leaves every admitted input and its pandas conversion byte-for-byte as main has them (AT-V15, AT-V19, AT-M2). For refused inputs, the comparison table distinguishes earlier coded refusals, conversion or scalar-read failures, silent `NaT` and inputs main returned successfully. The last group is the narrowing under Q8 = A and Q9 = A (section 0).
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
| 11 No raised caps | yes | no module-size ceiling is raised; S5a adds no bound row (revision 16 replaces `_STOP_AT` with an exact named census, section 4.4b); `transforms/` fan-out stays at its limit (no new module) |

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
| S5a-1a | engine | Checked Arrow ingestion, the check unwired: the Q6 = A type gate, the Q9 = A kinds with `date_read`, the metadata parser, channel verdict and projection filter (rule 3), both reasons, adapter rows, error classes, AT-M1, AT-M3 unit part, AT-M6 (section 4.4b "Size and slices", about 550 new lines). Fresh branch from main after S5b | S5b | R2 | T1 plus full suite and layer checks (reason registry, new reasons, conversion module) |
| S5a-1b | engine | Wiring: `check_source_schemas` before declaration (resident, declared loader schemas, ISO parent), resident, loader, PAN and ISO wiring with the S5 hunks re-applied onto #799's files, name binding, `date_strategy_columns`, AT-M4, AT-M5, AT-V22, order sentry (about 450) | S5a-1a | R2 | T1 plus full suite (frozen behavior, shared fixtures) |
| S5a-1c | engine | Streaming, native, profile, cloud and Hive wiring, AT-M2, AT-M3 route part, remaining AT-V16 encoding keys, the read sentry with its exact census, the E-cell re-pin (about 450) | S5a-1b | R2 | T1 plus full suite |
| S5a-2 | engine | Checked Arrow ingestion, plain cells: the holdable rule on every route (Q8 = A), the resolver band test, count, purity, the 4.4a test edits, user docs and changelog naming the narrowed set and the Q8 x Q9 asymmetry | S5a-1c | R2 | T1 plus full suite (frozen behavior on passthrough) |
| S1 | engine | `DateDomain`, bound `DatePartition`, `DateRangeError` and its `_CODED` row, range table, new reason, the required `partition` on six primitives and the 15 call sites, the internal native range invariant, OOC typed path through `apply_bucket_perturb_dates`, removal of the native decline and abort, deprecation of the native range reason, sentry, AT-R1 to AT-R12 and AT-C1 to AT-C3, section 6.9 test updates, user docs for the S1 behavior (section 4.7), changelog fragment | S5b (shared ns bounds) | R2 | T1 plus the full engine suite (reason registry, frozen behavior) |
| S2 | engine | `group_by` with `preserve_values` on the Python path, two deprecations (`replaced_by=None`), AT-G1 to AT-G3, docs paragraph, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S3 | engine | `preserve_values` on `windowed_date` anchors, derived cell holds the anchor's sentinel (Q2), the anchor range on the shared code, deprecation, AT-W1 to AT-W3, docs, changelog fragment | S1 | R2 | T1 plus full suite (reason registry) |
| S4 | engine | text_mask edge overflow becomes the token (Q5), AT-T1, docs sentence, changelog fragment | nothing | R1 | T1 |
| S6 | engine | post-mask sentinel exclusion and `declared_sentinel_rows` per column, AT-P1 to AT-P4, docs, changelog fragment | S1, S3 (derived anchors) and PM-1 (#784) merged | R2 | T1 plus the T2 gate set |
| S7 | engine | date generation: per-column fit kwarg, policy-aware snapshot writer and sentinel counts, matching generation declaration, admission (`_window_admission.py:128-170`, `:290-320`) and sampler (`_sample.py:493`, `_degenerate.py:122`) emitting sentinels at their rate (Q3), calendar-date stats in `_datetime_stats` and `_distribution_date`, AT-F1 to AT-F4, docs, changelog fragment | S1, S3 and S5 | R2 | T1, T2 and full engine suite (snapshot writer) |
| S8 | CLI | Wire the per-column exact-fit option through fit_exact_snapshot, test CSV fit through generation, update command help, user guide and changelog | S7 engine API released and available to CLI | R2 | CLI suite and installed CLI/engine integration |
| ASSEMBLER-LABELS | engine | Map source-backed pandas display labels to physical Arrow fields by position in the passthrough assembler (`execution/pipeline/_source_types.py:129,156`); tests with integer, tuple and duplicate-looking labels on FF. Pre-existing, found in S5 round 6 | nothing | R2 | T1 |
| DEP-FLOOR | engine | Raise the declared pandas floor to 2.x (Q7 = A) and make the engine import at its declared pyarrow floor: optional list-view predicates (`safe_output/_file_metadata.py:60-61`); AT-V11 and M-35 move here; exact-version CI legs that also run AT-V13 and AT-M1, a diff of the channel functions of `pyarrow/pandas_compat.py` between 14.0.2 and 24.0.0, and on the pyarrow 14 leg the AT-M2 writer rows and a one-line import check of the private `pyarrow.lib.string_to_tzinfo`. Pre-existing | nothing | R2 | T1 plus the floor legs and a full suite (version pin) |
| SOURCE-RESTORE-CODED | engine | Closed in revision 15: G-17 for date reads is rule 3 in S5a-1a to 1c; the passthrough part is G-21 | n/a | n/a | n/a |

Each row is one PR. S4, S5b, ASSEMBLER-LABELS and DEP-FLOOR can start independently. S5a follows S5b in order 1a, 1b, 1c, 2. SOURCE-RESTORE-CODED has no PR of its own. S1 follows S5b for the shared ns bounds. S2 and S3 follow S1. S6 follows S3 and PM-1. S7 follows S3, S5a-2 and S5b with S1 already merged. S8 follows the S7 engine release.

## 15. Owner decisions (product choices)

The owner accepted the recommendations for Q1 to Q5 on 2026-11-27, chose A for Q6 on 2026-11-28, chose A for Q7, Q8 and Q9 on 2026-11-28, and chose A for Q10 on 2026-11-28.

- Q1, typed date columns. Decided: typed `date` columns (Parquet, database `DATE`) keep the 0001 to 9999 domain, less the strategy's reach. `9999-12-31` and `0001-01-01` are refused on the usual windows unless declared, and genuine historic dates such as `1600-01-01` still mask. Text and zoned timestamps use the pandas domain.
- Q2, windowed_date with a declared sentinel anchor. Decided: the derived cell holds the anchor's sentinel value, so "unknown admission" gives "unknown discharge". Never the source value of the derived column.
- Q3, generation. Decided: a declared sentinel is excluded from the fitted range and emitted at its observed rate, so downstream `= 9999-12-31` logic keeps working.
- Q4, quarantine. Decided: an undeclared far date refuses the run even when `format_error` quarantine is on. The remedy is to declare the sentinel.
- Q5, text_mask date spans at the calendar edge. This departs from the owner rule (a coded refusal), so it is a product call. Decided: the span becomes the redaction token, as an unparseable span already does. Free text holds dates the user never declared, one edge date in a note should not stop a run, and the token writes no source value (fail-closed). The other option was the coded refusal.

- Q6, date columns inside containers (section 4.4b). Decided: (A), as given in the S5 redesign brief on 2026-11-28. A column holding a date inside a list, large list, fixed-size list, map or struct is refused by type even when every date is inside the calendar; full support is follow-up G-8. The options considered were (A) refuse for V1, (B) build G-8 inside S5, and (C) refuse only caller-supplied Arrow. List view, run-end-encoded, union, extension and dictionary-of-struct columns never come from a Decoy file reader, so refusing them is a technical choice and not part of Q6.

- Q7, pandas floor (row DEP-FLOOR, not S5). Decided 2026-11-28: (A), raise the declared pandas floor to 2.x. The engine does not import on pandas 1.5.3 today (`validators/_dates.py:13`), so no working user is lost, and the S5a holdable rule keeps the source timestamp unit. The (B) branch is in Appendix B.2.

- Q8, inputs main accepted that S5a refuses on routes that never convert. Decided 2026-11-28: (A), one holdable rule on every route, passthrough included, for plain date cells. Main can return zoned ns edges (row 8), `INT64_MIN` ns (row 9), readable year-10000 local times (row 11) and far plain dates (rows 13 and 14) on NCH and CH passthrough; S5a refuses them. Every plain `date64` is judged by its day. The (B) branch is in Appendix B.2. Under Q9 = A, Q8 = A does not reach exotic encodings on columns no date strategy reads (section 0.2).

- Q9, S5a scope for exotic date encodings (section 0). Decided 2026-11-28: (A). A column that `date_shift`, `bucket_perturb` or a `windowed_date` anchor reads must be a plain `date32`, `date64` or `timestamp` column. A date dictionary, malformed or date-changing pandas metadata (rule 3), or a `date64` with a time of day is refused there with `runtime/source_date_type_unsupported`, kind `dictionary`, `pandas_metadata` or `date64_time_of_day`, and the fix "cast it to a plain date or timestamp column", with no value in the message. The same encodings on a column that is only passed through, kept, hashed, redacted, tokenized or profiled follow the unread rules in section 4.4b. E1, E3b and E4 in section 0.1 document the original Q9 compatibility decision. Revision 15 judges the schema of date-read fields only. The builder re-pins every E-cell on main both ways and stops before merge if the re-pin adds an E row. The (B) branch and the question as put are in Appendix B.5.

- Q10, pandas metadata that conflicts with the data of a date-read column (section 4.4b rule 3b, rows E4b and E7). **Decided 2026-11-28: (A).** The owner was asked: "when a Parquet column carries Spark/int96 timestamp metadata that conflicts with the data, what should Decoy do?" The owner chose "A: refuse the column. Fail closed with a clear coded refusal naming the column. No silent wrong dates."
  - E4b, through the zone channel: a naive `timestamp[ns]` from int96 or Spark-flavor Parquet whose `datetimetz` descriptor names a zone is refused with `runtime/source_date_type_unsupported`, kind `pandas_metadata`.
  - E7, through the extension channel: a descriptor that asks for an extension dtype that is not identity for the Arrow type (`datetime64[ns, UTC]` on `timestamp[us, UTC]`, `Int64` or `period[D]` on `string`) is refused the same way.
  - The principle behind both: Decoy never ignores the metadata. It does not drop or rewrite a descriptor to make a date-read column readable, and the checker returns its input object on every admitted input.
  - Scope (orchestrator reading, owner may overrule): the refusal applies only to columns that a date strategy reads (Q9 = A, G-21). An int96 or Spark-flavor column that no date strategy reads is not judged and keeps main's correct restore. This is the technical default and does not block the build. If the owner overrules it, the unread case moves from G-21 into S5a.
  - The option not chosen, B, is in Appendix B.6.

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
- G-17: closed for date reads by rule 3 of section 4.4b (revision 15). The passthrough part is G-21.
- G-18: `config_position("statistical", Name(col))` in S5b's `check_degenerate` refusal names a config key that does not exist (`statistical.c`). Only direct `check_degenerate` and `sample_column` callers see it, since plan compile rebuilds the error; its sibling `refuse_degenerate` says "statistical column 'c'". Acceptable for V1. Log.
- G-19: `contracts/calendar_range.py` imports pandas for its fallback parse of non-ISO text, a framework import inside a contract module (Dennis r1 of revision 10, LOW). Log for the structure review.
- G-20 (V2-LOG): a malformed pandas metadata blob on a job with no date reads keeps main's uncoded error (`_pandas_meta/_columns.py:28`, `execution/pipeline/_resident_bytes.py:111`, `execution/pipeline/_source_types.py:49,67`, declaration), and so does the planning snapshot (`physical/_snapshot.py:163`). Fix: one typed refusal from `parse_source_meta` at those sites.
- G-21 (V2-LOG): a descriptor that changes the meaning of a passthrough sibling (zone channel or extension channel) is not judged. Main's conversion is kept. This includes an unread int96 or Spark-flavor column, which keeps main's correct restore (Q10 scope, orchestrator reading, owner may overrule). Fix: judge every converted date field with the same verdict, once a customer shows the case.
- G-23 (log, revision 16): other readers of the `b"pandas"` blob parse it on their own instead of through `parse_source_meta`: the faker admission (`execution/native/_faker_deterministic_admission.py`), `safe_output/_file_metadata.py:282`, `execution/pipeline/_resident_bytes.py:111` and `execution/pipeline/_source_types.py:49,67`. Move them to the parser in a later slice. S5a moves only `pandas_nullable_columns`, `stored_index_fields` and `arrow_columns`.
- G-22 (later): the label channel refuses a date read whose descriptor `name` is not its field name. Integer and tuple labels from `column_indexes` stay with ASSEMBLER-LABELS. Re-check after that row merges.

## Appendix B. Superseded detail

Historical appendix retained at plan head `4d90a2951`, path `docs/plans/2026-11-27-date-range-sentinel.md`, sections B.1 to B.5 (including comparison rows, prior reviews and the rejected option B). All Appendix B references to B.1 to B.5 point to those sections. Retrieve with `git show 4d90a2951:docs/plans/2026-11-27-date-range-sentinel.md`.

### B.6 Q10 option B (not chosen, revision 16)

The owner chose Q10 = A on 2026-11-28 (section 15). Revision 15 offered this B branch, kept here as written:

- **(B)** Ignore that one descriptor and read the Arrow type. The job runs, and the pandas unit or dtype can differ from main. If the owner picks B, these lines change and nothing else:
  - Rule 3b: a fired extension channel with verdict `meaning_change` on a date-read field gives verdict `ignored`, not a refusal. Rule 6 and the fix sentences do not change.
  - `check_source_dates` returns `x.replace_schema_metadata(blob)` where `blob` equals the parsed blob with that entry's `numpy_type` set to `"object"`. `"object"` is in pyarrow's plain set, so the extension channel does not fire and pyarrow reads the Arrow type. The copy is zero-copy. `check_source_dates(x) is x` still holds for every other input.
  - `check_source_schemas` cannot rewrite a schema, so the rewrite happens where data first exists: `check_resident_sources`, `checked_loader` (on the result), `checked_chunks` and `checked_batches` (on every batch) and the whole-file reads. The port wrappers already carry on with the returned value.
  - Every in-run read gets the table's `date_read`, the in-run profile read included. Only standalone profiling passes the empty set. Otherwise the in-run profile dtype differs from the masking dtype.
  - `io/source_dates.py` grows by about 25 lines (about 455). S5a-1a grows by about 60 new-for-review lines (about 610).
  - Tests: AT-M1 `meaning_change` extension rows expect admission, the returned blob changed in that entry only, the column buffers identical (same buffer addresses), and the field converted as with `ignore_metadata=True`. AT-V15 purity keeps `is x` except for these rows. AT-M6 `Int64` and `int64[pyarrow]` on string rows are admitted and shift `2020-01-01` to `2020-01-02`. New AT-M2-B: on FF, SEQ, NCH, ISO on and the in-run profile, the field's dtype is the Arrow-type dtype and the same on every route, the in-run profile dtype equals the masking dtype, and a sibling's descriptor is unchanged.
  - Mutations: M-70 is killed by the AT-M1 B row (the returned blob must change). New M-97B: apply the rewrite only on FF (AT-M2-B route equality). New M-98B: give the in-run profile the empty set (AT-M2-B profile dtype equals masking dtype). New M-99B: rewrite every entry, not only the date-read one (AT-M2-B sibling descriptor unchanged). M-45 (rebuilt table) stays killed by AT-V15 on the other rows.
  - E7 under B: read as the Arrow type. The changelog names the dtype change.

The B mutation names M-97B to M-99B are not the S5a mutations M-97 to M-99 in section 7.

## Appendix C. Review findings mapped to the revision 15 design

Revision 14's finding-to-fix map is at `115f760e3`. This table maps every S5a finding of the Codex plan rounds r1 to r4 (`~/scratch/codex-s5-plan-r{1,2,3,4}.out`) and Dennis rounds r1, r2, r10 and r11 (`~/scratch/dennis-s5-plan-r*.md`) to design C. S5b findings are closed in section 4.4c and are not listed.

| Review | Finding | How design C closes it |
|---|---|---|
| Codex r1 V1 | Rule 3 rejected genuine writer tokens (`(date, int32)`, `(datetimetz, int64)`) | plain `numpy_type` tokens fire no channel (rule 3b); AT-M2 writer rows |
| Codex r1 V1 | Zoned `M8` on a string passed a "names no date" test | the extension channel fires (`DatetimeTZDtype`), verdict `meaning_change`; AT-M1 |
| Codex r1 V1 | NFKC bound an unread `K` (Kelvin sign) column | exact-name binding kept; AT-V22 |
| Codex r1 V1 | Floor day refused a working unread `-62135596800001` ms | rule 4 uses the truncated day unless the descriptor is `ArrowDtype`; AT-M6 |
| Codex r1 DESIGN | The pandas adapter lacked the config input | work list built once from the plan (rule text); AT-V22 direct calls |
| Codex r1 V2-LOG | M-72, M-73, M-76 precision; AT-V16 admission versus strategy result; size | M-72 and M-73 kept per site; M-76 now targets exact dtype equality; F6 keeps main's downstream result; per-file budget in 4.4b |
| Codex r2 #1 V1 | Rule 3 refused int64 writers to `date64` and zoned `timestamp` | plain tokens fire no channel; AT-M2 |
| Codex r2 #2 V1 | A same-zone dtype lost precision on restore (`.123456` us to ms) | `datetime64[ms, UTC]` on `timestamp[us, UTC]` is a fired extension channel, `meaning_change`, refused (Q10 A); AT-M1 |
| Codex r2 #3 V1 | Wrong day for an unread Arrow-backed `date64` | rule 4 floors when the descriptor is `ArrowDtype(date64)`; AT-M6 |
| Codex r2 #4 V1 | Malformed JSON failed before the ISO check | `check_source_schemas` runs before `for_run` in the ISO parent; AT-M4 |
| Codex r2 #5 V1 | Pre-spawn refusal reported the parent's memory peak | `peak_rss_mb=None, pid=None` on the ISO refusal; AT-M4 |
| Codex r2 V2-LOG | `infer_string`, fastparquet, test inventory | `StringDtype` on large_string is identity, missing `field_name` is not malformed; AT-M2 rows |
| Codex r3 #1 V1 | Year 2300 overflowed in the intermediate ns cast | the zone channel fires, refused at the schema before conversion; AT-M6 |
| Codex r3 #2 V1 | `date32[day][pyarrow]` on `date64` failed before a scalar existed | `ArrowDtype(date32)` on `date64` is `meaning_change`; AT-M6; M-84 |
| Codex r3 #3 V1 | `int64[pyarrow]` on a text date destroyed it | fired extension channel on `string`, refused; AT-M6 |
| Codex r3 V2-LOG | PR size, test inventory, plan length | slices 1a to 1c at about 550, 450 and 450 new lines; AT-M list replaces AT-V20 and AT-V21; the plan is shorter |
| Codex r4 #1 V1 | `("categorical", "object")` and `("categorical", "string")` on `dictionary<int8, string>` were refused | `object` is a plain token and `StringDtype` on a dictionary is skipped by pyarrow, so no channel fires; AT-M2; M-94 |
| Codex r4 #2 V1 | A declared loader schema failed before the guarded loader | `check_source_schemas` judges declared `source_loader_schemas` before `for_run`, zero loader calls; AT-M4; M-88, M-89 |
| Codex r4 #3 V1 | A projected-away malformed descriptor stayed active | `_projected_meta` drops descriptors of absent fields inside `arrow_to_frame`; AT-M3; M-85 to M-87 |
| Codex r4 #4 V1 | A mixed frame got the wrong reason | nothing wraps the conversion, so #799's column attribution stays; AT-M5; M-92 |
| Dennis r1 H1 | zoneinfo versus pytz | resolver test kept (rule 5) |
| Dennis r1 H2 | The port would revert #799 | hunk-only port method kept |
| Dennis r1 M1 to M4, L1 to L3 | false "already fails" claim, second reason, admitted-column conversion, fixture-route map, `_STOP_AT` headroom, memory, anchors | E table re-pinned both ways; reason decision kept; AT-V19 and AT-M2; fixture table; `_STOP_AT` measured, then replaced in revision 16 by the exact named read census; rule 7; anchors re-derived on main |
| Dennis r2 H1 | ns and zone rule turned main tests red | 4.4a edits kept |
| Dennis r2 M1 to M4, L1 to L4 | stale claims, AT-V9 vocabulary, missing branch files, compat-contract text | kept as revision 14 fixed them; section 4.7 contract paragraph |
| Dennis r10 S5a-H1 | Rule 3 blocked known triggers instead of allowing known writers | the verdict reads pyarrow's trigger conditions, so any token that fires no channel admits and any that fires a non-identity channel refuses; AT-M1 property |
| Dennis r10 S5a-H2, H3 | fan-out freeze; flat test folders | `date_strategy_columns` in `_column_access.py`; new test files in the named sub-packages |
| Dennis r10 S5a-M1 to M3, L1 to L4 | one-way re-pin, G-17, size, stray text, private resolver API, strategy-set mutation, asymmetry | both-way re-pin; G-17 closed by rule 3 plus G-21; per-file budget; DEP-FLOOR import check; M-78; section 0.2 |
| Dennis r11 S5a-H1 | Writer spellings outside the allow list were refused | no allow list; the writer table is AT-M2 |
| Dennis r11 S5a-M1 to M6 | `date_read` binding, `_STOP_AT` key path, unwired 1a, `_isolated_run.py` at 601, second failure mapper, SOURCE-RESTORE-CODED | binding text kept; `tests/sentry/dates/` path (the `_STOP_AT` key is gone in revision 16); changelog fragment in 1a; mode computed in the helper (599 or below after revision 16); `in_process_failure` reused; row closed |
| Dennis r11 S5a-L1 to L4 | size, use-set mutations, malformed metadata, unprobed writers | slice sizes; M-77 to M-80, M-83; malformed rules in 3a; int96 and Spark writers probed (E4b) |
| Dennis r1 of revision 15, edit 1 | `_STOP_AT` numeric bound on the read census | `_STOP_AT`, its `LIMITS` entry and its `sentry-limits.json` row are dropped; the census is an exact named set of sinks and private helpers, and the allowances are listed by path, function and reason (section 4.4b, Sentries); M-51 and M-52 retargeted |
| Dennis r1 of revision 15, edit 2 | Q10 still open | Q10 = A recorded with the owner's wording in the header, section 0.1 (E4b, E7), rule 3b, section 15 and the 4.4b heading; B moved to Appendix B.6 |
| Dennis r1 of revision 15, edit 3 | refusal scope | date-strategy-read columns only; unread int96 keeps main's restore; marked "orchestrator reading, owner may overrule" (section 15, G-21) |
| Dennis r1 of revision 15, edit 4 | int96 rows ran on too few routes | AT-M2 int96 and Spark-flavor rows on lazy Parquet FF, AUTO, SEQ and OOC, CLOUD, HIVE and the `checked_batches` open gate, zero batches yielded; M-100, M-102 |
| Dennis r1 of revision 15, edit 5 | refusal text could carry the zone | rule 6: exact `str(exc)` equality, no zone, `numpy_type` or descriptor JSON in any surface; the mapping key is the only addition; AT-M2, AT-M6; M-101 |
| Dennis r1 of revision 15, edit 6 | wrong-type `metadata` and `timezone` | two rule 3a items; AT-M1 wrong-type rows; M-97 |
| Dennis r1 of revision 15, edit 7 | large files grew | net zero growth on files over 600 lines; `_isolated_run.py` and `profile/_readers.py` capped at 599; binding in `_column_access.py` and the ISO helper; line table updated |
| Dennis r1 of revision 15, edit 8 | stale anchors | re-anchored to `8414da35c` (#829, #827, `_chunked_entry.py` 621 lines); docs anchor moved to main; S5b overlaps on the hunk list; calendar constants from S5b |
| Dennis r1 of revision 15, edit 9 | one descriptor lookup for all channels | one lookup per channel in rule 3b; AT-M1 `field_name` null, `""`, missing, index-entry and first-wins rows; M-98, M-99 |
| Dennis r1 of revision 15, edit 10 | second blob parser | `pandas_nullable_columns` reads the lenient view; AT-M1 `pairs_for` identity guard and lenient-view row; G-23 lists the other readers |
| Dennis r1 of revision 15, edit 11 | failure modes not stated | "Failure modes S5a must not have" table before the rules, each mode with its AT IDs |
| Dennis r1 of revision 15, edit 12 | fix sentence and Spark orphan descriptor | fix sentence names the cast to the zoned timestamp type, matching section 4.7; AT-M2 Spark orphan row (admitted, equals main) |
