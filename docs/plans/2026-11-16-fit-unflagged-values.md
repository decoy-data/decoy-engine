Status: plan

# FIT-UNFLAGGED-VALUES: a plain fit snapshot keeps no rare or extreme cell of any column (roadmap row 24f, open part)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `proportionality.md`; engine `docs/frozen-surfaces.md`,
`docs/strategies.md`, `tests/sentry/test_module_size.py`; CLI `docs/ROADMAP.md` row 24f (and
PR #291, which reopens it), CLI `docs/records/2026-11-10-cli-qa-generation-distribution-models.md`
findings H6 and H7.

Revision 2, after Dennis r1 (GO-WITH-FIXES: 1 HIGH, 3 MEDIUM, 4 LOW). Every finding is taken;
the change map is in section 14.

Bases (2026-11-16): engine `origin/main` `ddd014a5` (release 0.27.0), CLI `origin/main`
`307a189a`. Line numbers are read at these bases.

Owner decisions used: V1 bar (a leak of a non-admin value blocks V1); row 24f is a leak class
that blocks V1; "names may show in messages, data values never"; pre-release, so snapshot output
may change with a `Breaking:` line. Owner calls on this plan (2026-11-16): K = 10, the 3-word
free-text rule, and a new row 24zm for `profile_document` (outside this plan).

Risk: E1 is R2 (value-leak class, changes the bytes of every plain snapshot and one marker
string). C1 is R1 (CLI text, tests, docs). Full plan; plan review Dennis then Codex; E1 code
gate Dennis and Codex, C1 Codex only.

## 1. Frame

### 1.1 Evidence

`distribution_snapshot_document` (`profiling/_snapshot_values.py:222-274`) withholds values
only for the columns `value_sensitive_names` returns (`:264-273`). Every other column is the raw
`compute_distribution_snapshot` entry. The DI models QA (2026-11-10, 1,000 rows, seed 31)
showed three leaks in a plain snapshot. All three are still present on `ddd014a5`:

| Finding | What the snapshot holds | Source of the value |
|---|---|---|
| H6a | salary `max: 987654`, the one row's exact salary; `bin_edges[-1]` and `p95` can also equal real cells | `quality/snapshot.py:411-465` `numeric_stats` |
| H6b | `{"value": "RARE-HIV-B20", "count": 1}` in `top_values`; it appeared in 9 of 5,000 generated rows | `quality/snapshot.py:468-488` `_categorical_stats` |
| H7 | a `note` column of 30 strings like `patient Surname24 called` is classed categorical, so every string is stored and 100% of generated notes are real | `quality/snapshot.py:286-291` (`CATEGORICAL_DISTINCT_CAP = 30`) |

The same class has two more members the QA did not test. This plan closes them too: an
unflagged datetime column keeps its exact earliest and latest timestamp and a `year_bins` entry
for every year, so a single 1921 date publishes `{"year": 1921, "count": 1}`
(`_datetime_stats`, `:491-501`); and a joint cell with a count of one names a combination held by
one row (`_joint_snapshot`).

### 1.2 Root cause

The plain-snapshot policy has one switch per column: flagged (withhold all) or not flagged (keep
all). Detection is a heuristic, so a column it misses keeps every cell. The fix is a second,
weaker rule for every column the first rule does not cover: no released label, year or bound may
be a fact about fewer than K source rows. K is the existing `MIN_RELEASE_COUNT` (10,
`_value_redaction.py:58`), which the numeric shape blocks already use
(`generation/statistical/_numeric_shape.py`). One constant sets one floor.

## 2. Guarantee

For a snapshot written by `distribution_snapshot_document(..., include_values=False)`, every
column the profiler does not flag ("unflagged") gets the floor:

- G1. Every label in a categorical `top_values` and every joint cell key is held by at least K
  source rows. Bool columns are exempt: their vocabulary (`True`, `False`) is public, and a
  count is not a value.
- G2. A numeric column's `min`, `max`, `bin_edges` and `bin_counts` do not change when any of the
  K-1 smallest or K-1 largest cells is replaced by another value beyond the K-th smallest or
  K-th largest cell (top and bottom coding). The same holds for each `quantiles` entry kept. The
  bounds and edges are points on a 1, 2 or 5 times 10^k grid; a grid point, a kept `p50` or an
  interior `quantile_grid` point can still equal a real cell by coincidence, as today
  (`_numeric_shape.py:18-22`). `mean` and `std` are aggregates and are kept.
- G3. Every `year_bins` count of a datetime column is at least K, and `min` and `max` are the
  first and last instant of the first and last kept year.
- G4. A short string column whose labels read as sentences is written as `freetext` (length
  statistics only), never as categorical.
- G5. When the floor would leave a column nothing to release, the column gets the flagged
  treatment (`_redact_column`, unchanged) and is listed in `redacted_columns`. "Nothing to
  release" is, per kind: numeric with fewer than 2K finite cells; categorical (not bool) with
  every label under K; datetime with no year held by K rows. The flagged numeric rule
  (`_coarse_range`) derives its power-of-ten bounds from the true extremes, so a G5 numeric column
  releases the order of magnitude of its range, exactly as a flagged one does today.
- G6. `include_values=True` output is byte-identical to today.
- G7. Flagged columns are treated exactly as today: the free-text pass skips them, and their
  joints are withheld as today.

Non-goals (V1): interior histogram bins with a small count (a count on a public grid, not a
value); fan-out degree counts; freetext length statistics; reconstruction across several
snapshots of the same source (the V1 threat model covers accidental leaks only); scan and
profile documents (`profile_document`), which are roadmap row 24zm.

## 3. Established solutions

Search run: SDC handbook and sdcMicro (already cited in the code), synthpop `sdc()`, SDV
synthesizer docs, ARX, CMS cell-size policy; in the codebase, the redaction registry, the
numeric shape release floor and the coarse-range helpers.

| Source | What it does | Used here |
|---|---|---|
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), 3.4 and 4.2; cited at `_value_redaction.py:55-58` | Global recoding, top and bottom coding, and a minimum frequency rule (thresholds of 3 to 11) for released cells | K floor on labels, joint cells and year bins; top and bottom coding of numeric bounds |
| CMS cell-size suppression policy | Suppresses any published cell under 11 | Supports K = 10 |
| R synthpop `sdc()` ([docs](https://rdrr.io/cran/synthpop/man/sdc.html)) | `bottom.top.coding` limits per variable and `rm.replicated.uniques` before synthetic data is released | The same steps, applied to the fitted model instead of the output |
| R sdcMicro `topBotCoding` ([docs](https://www.rdocumentation.org/packages/sdcMicro/versions/4.6.0/topics/topBotCoding)) and `globalRecode` | Replace values beyond a limit with the limit; recode to intervals | The numeric bound rule and the year fold; `_coarse_domain` already cites `globalRecode` |
| ARX (Prasser and Kohlmayer; k-anonymity with a suppression limit) | Records in groups smaller than k are suppressed, not published | The fold of rare labels and cells into `other_count` |
| SDV synthesizers, `enforce_min_max_values=True` by default ([docs](https://docs.sdv.dev/sdv/single-table-data/modeling/synthesizers/ctgansynthesizer)) | Learns and stores the exact real min and max | The counter-example: the H6a leak is SDV's default. We do not follow it |
| Heckbert, "Nice numbers for graph labels" (Graphics Gems 1990); cited at `_snapshot_values.py:16` | Steps of 1, 2 or 5 times a power of ten | Grid step for numeric bounds |

Free text in a low-cardinality column: no surveyed tool tests for it. SDV and synthpop pick a
type from the dtype and the distinct count only, as Decoy does today. The word-count test in 4.3
is our own rule, approved by the owner.

Codebase reuse: see 7a.

## 4. Design

Design notes: no new module and no new abstraction. One more table in the existing registry,
applied in the file the sentries already scan. Choke point: `distribution_snapshot_document` is
the only writer of a plain snapshot (CLI sentry `tests/sentry/io_policy/test_fit_value_redaction.py`
already refuses the raw writer in the CLI), and inside it every value key is driven by the
registry. Guard: the registry sentry (AT-11) fails on a raw key that neither table classifies.
Mutation that must turn it red: remove one row of `SNAPSHOT_FLOOR_STATS`.

### 4.1 Registry

`_value_redaction.py` gains a second table beside `SNAPSHOT_VALUE_STATS`:
`SNAPSHOT_FLOOR_STATS`, the rules for an unflagged column in a plain snapshot. New `Rule`
members join the one enum: `TOP_CODED_RANGE`, `K_TAIL_QUANTILES`, `FOLD_YEARS_UNDER_K`,
`KEPT_YEAR_START`, `KEPT_YEAR_END`, `FOLD_UNDER_K`. All are data rules (`DATA_RULES`).

| Scope, key | Rule |
|---|---|
| numeric `min`, `max`, `bin_edges`, `bin_counts` | `TOP_CODED_RANGE` |
| numeric `quantiles` | `K_TAIL_QUANTILES` |
| datetime `year_bins` | `FOLD_YEARS_UNDER_K` |
| datetime `min` / `max` | `KEPT_YEAR_START` / `KEPT_YEAR_END` |
| categorical `top_values`, joint `cells` | `FOLD_UNDER_K` |

Keys not listed: numeric `mean` and `std` (aggregates of at least 2K cells, since G5 takes
smaller columns), `quantile_grid` and `exact_values` (already K-floored by
`_numeric_shape.py`), freetext length statistics and the counts (value-free).

The same file gains `REDACTED_POLICIES = frozenset({"flagged-redacted/v1", POLICY_REDACTED})`.
Every reader that asks "is this a redacted document" uses the set: `snapshot_joint_warnings`
(`_snapshot_values.py:188`) and `_spec.py:273`.

### 4.2 Rules (all in `_snapshot_values.py`, applied by one `_floor_column`)

- `TOP_CODED_RANGE`: n finite cells, n at least 2K (G5 takes the rest). `a` = K-th smallest,
  `b` = K-th largest. Step = the Heckbert nice number (1, 2 or 5 times a power of ten) at or
  above `(b - a) / numeric_bins`, or the `_grid_edges` step when `a == b`. Domain
  `lo = floor(a / step) * step` and `hi = lo + step * m`, where `m` is the smallest whole number
  with `lo + step * m >= b`, at least 1; computed in `Decimal` as `_grid_edges` does. Then
  `numeric_stats(non_null, bins=m, domain=(lo, hi))`, so every edge is a grid point. `lo <= a`
  puts `a` in the first bin and `b <= hi` puts `b` in the last, and clamping moves every cell
  beyond them into those bins, so each end bin holds at least K rows. `m` is between
  `numeric_bins` and `numeric_bins + 2`; the sampler and the shape decoder read the edge list,
  not its length. Everything depends only on `a`, `b`, n and the clamped counts, which gives G2.
- `K_TAIL_QUANTILES`: keep `pXX` only when `p * n >= K` and `(1 - p) * n >= K`; drop the rest.
  Type-7 interpolation at such a `p` reads order statistics K and above from each end, so a kept
  entry is unchanged by the tail swap in G2.
- `FOLD_YEARS_UNDER_K`: the kept years are the years with a count of at least K. Each other
  year's count moves to the nearest kept year (the earlier one on a tie). Years before the first
  kept year therefore land in it, and years after the last kept year land in that one. The total
  count does not change.
- `KEPT_YEAR_START` / `KEPT_YEAR_END`: `min` is `YYYY-01-01T00:00:00` of the first kept year,
  `max` is `YYYY-12-31T23:59:59` of the last kept year. The sampler draws a year from `year_bins`
  and a uniform instant in it, then clamps to `[min, max]` (`_sample.py:480-510`). With whole-year
  bounds the clamp never moves a draw, so no draw piles up at a bound.
- `FOLD_UNDER_K`: `_collapse_counted_items` gains a `keep` predicate. Items with `count < K` move
  into `other_count`; the rest stay in order. Bool dtype columns skip it. A joint is folded the
  same way.

Order inside `distribution_snapshot_document` (plain mode):

1. Profile the frame and get the flagged names (moved up from `:262-264`).
2. Pick the free-text columns (4.3) among the unflagged string columns.
3. Compute the raw snapshot, then convert the free-text columns (4.3).
4. For each unflagged column, test G5. A G5 column joins the flagged set.
5. Apply `_redact_column` to the flagged set, `_floor_column` to every other column.
6. Withhold every joint that names a flagged or free-text column; fold every other joint.
7. Stamp the policy with the flagged set (flagged by the profiler plus G5) as
   `redacted_columns`.

Step 6 runs after step 4, so a G5 column's joints are withheld (AT-6).

### 4.3 Free-text test

A string column that the profiler did not flag, that has at most `CATEGORICAL_DISTINCT_CAP`
distinct values and is not in `high_cardinality_columns`, is free text when the median distinct
label has 3 or more whitespace-separated words. After the raw snapshot is computed, its entry
gets `kind: freetext`, `stats` from the snapshot's own freetext builder, and its `cell_format`
relearned by `add_cell_format` on that one column, so the blank count (freetext only) is
present. To reach the builder without growing `quality/snapshot.py` (exactly 600 lines, and the
module-size census may not grow), `_freetext_stats` is renamed to `freetext_stats`, the same
public style as `numeric_stats`: two changed lines, no added line. A joint that names a free-text
column is withheld.

### 4.4 Marker

`POLICY_REDACTED` becomes `"flagged-redacted/v2"`: the string now also means "every other column
is floored at K". Readers accept `REDACTED_POLICIES`, so v1 files keep working, including their
joint-warning exemption. G5 columns are listed in `redacted_columns`. The existing refusal at
`_spec.py:292-298` covers a listed categorical column, a listed `condition_on` parent, and a
listed numeric column that holds `exact_values` or a grid. A listed numeric column without those
blocks samples its one coarse bin, which is today's flagged behaviour (`_spec.py:262-269`). A
listed datetime column samples its years, also as today. The refusal text "(a sensitive column)"
becomes "(a sensitive column, or one with too few rows to release values)". The snapshot
`schema_version` stays `distribution-snapshot/v1`: no key or kind is added.

## 5. Behaviour (DI models QA fixture, 1,000 rows)

| Column | Today | After |
|---|---|---|
| `salary`, one row 987,654 | `max: 987654` | `max` on a grid at or above the 10th largest cell; the one row is clamped into the top bin |
| `diagnosis` with `RARE-HIV-B20` x1 | label stored, generated 9 times | folded into `other_count`, never generated |
| `note`, 30 three-word strings | categorical, all 30 stored | `freetext`, length statistics only |
| `state` (CA, NY, ...), each label over 10 rows | stored | stored, unchanged |
| `is_active` bool with one `False` | stored | stored (bool exempt) |
| `visit_date` with one 1921 row, the rest 2015 to 2024 | exact first and last timestamp; `{"year": 1921, "count": 1}` | 1921 folded into 2015; `min` 2015-01-01, `max` 2024-12-31T23:59:59 |
| 15-row file, `state` with 3 to 6 rows per label | stored | G5: withheld and listed; generate refuses with the existing code and hint |
| 15-row file, `amount` numeric | exact bounds | G5: one coarse interval, listed |
| any column with `--include-values` | raw | raw, byte-identical |

### 5.1 Fidelity cost

- Numeric, histogram path: bounds widen by at most one grid step (about one tenth of the
  K-trimmed range) on each side, and the outer K rows on each side are clamped into the end bins.
  Columns with 100 or more finite cells use `quantile_grid`, which is unchanged, so their draws do
  not move. Generation output changes for numeric columns under 100 rows.
- Numeric `quantiles`: `p05` and `p95` need 200 rows, `p25` and `p75` need 40. Only reports read
  them; the sampler does not.
- Categorical: labels held by fewer than 10 rows vanish, and their mass goes to the kept labels
  (or to `OTHER` with `other_mode: emit`). On 1,000 rows that is each label under 1%; on 100 rows,
  each label under 10%. A column with fewer than 10 rows per label is withheld.
- Free text: short sentence columns become length-matched filler. A phrase vocabulary of 3 or
  more words (for example `Type 2 diabetes`) is caught too; `--include-values` restores it.
- Datetime: years with under 10 rows vanish and their mass moves to the nearest kept year; draws
  spread over whole first and last years instead of stopping at the exact ends.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| Numeric column with under 2K finite cells | G5: `_redact_column` (one coarse interval), listed |
| Only inf cells | left alone, as today (`_coarse_range` returns early) |
| `a == b` (K-th smallest equals K-th largest) | step from `_grid_edges`, `m = 1`, domain around the value |
| Grid not writable near float max | `_FALLBACK_DOMAIN`, as today |
| Every categorical label under K | G5: withheld and listed; generate refuses with `plan.statistical_snapshot_values_redacted` and the fix hint |
| Datetime with no year held by K rows | G5: today's flagged year rule, listed |
| A G5 or free-text column in a joint | the joint is withheld (step 6 after step 4) |
| `condition_on` with a folded parent label | the child draws from its marginal (existing fallback, counted) |
| Joint at a raised `contingency_top_k` | cells under K fold; `snapshot_joint_warnings` reports them as `policy_dropped` (existing field) |
| `quantile_grid` decoder bound check | grid points lie at or inside the K-th extremes, so inside `[lo, hi]`; AT-9 proves it |
| Old v1 snapshot | read as today, with its joint-warning exemption (`REDACTED_POLICIES`) |
| A forged `flagged-redacted/v3` | refused as an unknown policy (existing test, new spelling) |
| A flagged short-sentence column | stays flagged and categorical-withheld; the free-text pass never sees it (G7) |
| Object column with mixed types | the free-text test reads `str(value)`, as the snapshot does |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged column and joint of a plain snapshot; the G5 refusal text | `SNAPSHOT_FLOOR_STATS` in the one registry, applied in `distribution_snapshot_document`; the refusal names columns only | AT-1 to AT-6, AT-8 | drop `FOLD_UNDER_K` from the table |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory frame; nothing opened, staged or leased | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state or cache is added | n/a | n/a |
| 4 | Route parity and silent fallback | `decoy fit`, the engine API, `ui/summary.py` (counts only) | all three call `distribution_snapshot_document`; the CLI sentry refuses the raw writer | AT-C1 and the existing `test_fit_value_redaction.py` | call `compute_distribution_snapshot` from `cli/gen/_fit.py` |
| 5 | Referential integrity | `condition_on` with a folded parent label; a joint with a G5 column | existing marginal fallback; step order in 4.2 | AT-9 conditional column; AT-6 joint | run the joint loop before the G5 test |
| 6 | Untrusted producer | a hand-edited snapshot marker | readers accept exactly `REDACTED_POLICIES` and `raw` | AT-7 | accept any `flagged-redacted/*` prefix |
| 7 | Check then use (TOCTOU) | none | N/A: no new file read; the frame is read once by the caller | n/a | n/a |
| 8 | Weak tests | a floor test that passes on a frame with no rare cell | each canary test first asserts the canary is in the raw snapshot | AT-1 to AT-5 non-vacuity line | build the AT-2 frame without the rare row |
| 9 | Refactor drift | `include_values=True`, flagged columns | those paths do not change; the free-text pass excludes flagged names | AT-10, AT-12, existing flagged tests | run the free-text pass on every string column |
| 10 | Frozen contract drift | `distribution_snapshot_document` output, `value_policy`, generated output 3.3 | `Breaking:` line, compat note, v1 still read | AT-7, section 9 | drop v1 from `REDACTED_POLICIES` |

### 6.2 Enumerations

#### Exit paths

- No new exit path: the G5 refusal reuses `plan.statistical_snapshot_values_redacted`, raised at
  `generation/statistical/_spec.py:292-298` (CLI exit 1).
- The existing `DistributionSnapshotError` refusals of `compute_distribution_snapshot` are
  unchanged and still raise before the floor runs.

#### Routes

- `decoy fit`, CLI `cli/gen/_fit.py:164`: writes the plain snapshot.
- The engine API `distribution_snapshot_document`, `profiling/_snapshot_values.py:222`.
- CLI `ui/summary.py:370-371`: reads null counts only, so the floor does not change its result.
- `fit_dp_snapshot`: a separate DP route, not touched.

#### FK shapes

- N/A: the floor reads one column at a time and never a key relationship.
- `fanout` degree counts are counts, not values, and are out of scope (section 2).

#### Fields

- Snapshot kinds `numeric`, `categorical`, `datetime`, `freetext`, `empty` and the joint
  (`profiling/_value_redaction.py:115-156`); the keys each rule touches are in 4.1.
- No key is added; `value_policy` and `redacted_columns` keep their types.

#### Output surfaces

- The snapshot file and `fit --json` (`value_policy`, `redacted_columns`).
- The `fit` stderr list of withheld names.
- Generated rows of statistical columns fitted from a new snapshot.

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Floor constant | `MIN_RELEASE_COUNT` | no |
| G5 treatment | `_redact_column` (with `_coarse_range`, `_year_edge`) | no |
| Grid arithmetic | `_grid_edges` (step when `a == b`, `Decimal` context) | no |
| Clamped histogram | `numeric_stats(bins=..., domain=...)` | no |
| Fold into `other_count` | `_collapse_counted_items` | gains a `keep` predicate |
| Free-text statistics | `_freetext_stats` | renamed `freetext_stats`, no added line |
| Free-text cell format | `add_cell_format` | no |
| Rule enum, registry, applier | `Rule`, `snapshot_rules`, `_apply` | one new table, six new members |
| Refusal | `plan.statistical_snapshot_values_redacted`, `redacted_fix_hint` | message wording |

## 7. Acceptance tests, red first

Engine (E1), in `tests/unit/profiling/test_snapshot_floor.py` (new) unless named. The fixture is
the QA frame rebuilt in the test (1,000 rows, seed 31), plus small frames.

| # | Test | Fail before |
|---|---|---|
| AT-1 | unflagged salary (canary 987,654 present in the raw snapshot): `max` is not 987,654. Invariance: replace the 9 largest cells with other values above the 10th largest and the 9 smallest with other values below the 10th smallest; `min`, `max`, `bin_edges`, `bin_counts` and every kept `quantiles` entry are equal before and after the swap. Each end bin holds at least K | `max == 987654`; the swap moves `max` |
| AT-2 | the document's JSON text does not contain `RARE-HIV-B20`; `other_count` grew by 1; every kept label count is at least K | label stored with count 1 |
| AT-3 | joint of two unflagged columns: every kept cell count is at least K; folded mass is in `other_count` | count-1 cell stored |
| AT-4 | the 30-string note column is `kind: freetext` with a `cell_format` blank count; no note string is in the JSON | categorical, all 30 stored |
| AT-5 | datetime with one 1921 row and the rest 2015 to 2024: every `year_bins` count is at least K, no 1921 bin, the total count is unchanged, `min` is `2015-01-01T00:00:00`, `max` is `2024-12-31T23:59:59`; a 5,000-row draw has no value at a clamped bound more often than any other instant | `{"year": 1921, "count": 1}` and exact bounds stored |
| AT-6 | 15-row frame with a categorical `state` (3 to 6 rows per label), a numeric `amount` and a joint `(state, tier)`: both columns are in `redacted_columns`; `state` has empty `top_values`; `amount` has one coarse bin; the joint has no cells; `load_spec` refuses `state` with `plan.statistical_snapshot_values_redacted` | labels and joint cells stored, spec loads |
| AT-7 | `value_policy == "flagged-redacted/v2"`; `load_spec` accepts v1 and v2 and refuses v3 (`tests/unit/generation/test_statistical_redacted.py`); `snapshot_joint_warnings` exempts a withheld joint for a v1 and a v2 document | marker is v1; v2 refused |
| AT-8 | property (hypothesis, as `test_snapshot_values.py` already uses): for random numeric, string, datetime and bool frames, the G1 to G3 floors hold for every unflagged column, and the AT-1 swap leaves numeric bounds unchanged | fails on the first count-1 label, rare year or moved bound |
| AT-9 | round trip: fit the QA frame, generate 5,000 rows; the numeric shape decodes, no generated label is a folded label, and the per-column marginal similarity from `quality.fidelity` is at least 0.95 for `salary`, `state` and `visit_date` | not fail-before: the fidelity budget |
| AT-10 | guards that stay green: a bool column keeps a count-1 `False`; 2-word labels (`New York`) stay categorical; `include_values=True` equals the raw snapshot plus the two keys (existing `test_include_values_is_the_raw_snapshot_plus_the_two_keys`) | not fail-before: they pin what must not change |
| AT-11 | sentry (`tests/sentry/profiling/test_snapshot_value_registry.py`): every raw key is classified across both tables; `other_count` still has one writer; the existing forbidden-shape guard stays green | new rule keys unclassified |
| AT-12 | a forced-flagged column of 3-word strings is withheld as a flagged categorical (`kind: categorical`, empty `top_values`), not converted to freetext | the pass ran before the profile and converted it |

Mutations that must turn a test red: drop `FOLD_UNDER_K` from the table (AT-2, AT-3, AT-8,
AT-11); take `a` and `b` as the min and max (AT-1, AT-8); bin with `numeric_bins` instead of `m`
(AT-1 end-bin check); leave `year_bins` unfolded (AT-5, AT-8); set `min` to the month of the K-th
earliest value (AT-5 pile-up check); run the joint loop before the G5 test (AT-6); skip the
free-text pass (AT-4); run it on flagged names (AT-12); keep v1 (AT-7); compare
`== POLICY_REDACTED` in `snapshot_joint_warnings` (AT-7); fold bool columns (AT-10).

CLI (C1), after the engine release that carries E1:

| # | Test | Fail before |
|---|---|---|
| AT-C1 | `decoy fit` on the QA frame: no canary (`RARE-HIV-B20`, `987654`, any note string, `1921`) in the file; `fit --json` shows `value_policy: flagged-redacted/v2` (`tests/e2e/first_user/test_items_privacy.py`) | canaries present on the old pin |
| AT-C2 | a 15-row fit, then `decoy validate` on a statistical categorical column: exit 1 with the redacted code and the `--include-values` hint | validate passes |

### 7b. Existing tests that change

Engine: `tests/unit/profiling/test_snapshot_values.py::test_plain_columns_equal_the_raw_snapshot`
and `::test_a_joint_of_two_plain_columns_is_unchanged` pin "unflagged equals raw" and are
rewritten to the floor. `tests/unit/generation/test_statistical_redacted.py::test_an_unknown_or_ill_typed_policy_refuses`
lists `flagged-redacted/v2` as unknown; it moves to v3.
`tests/sentry/profiling/test_snapshot_value_registry.py::test_the_four_snapshot_rules_join_the_one_rule_enum`
and `::test_every_visited_key_is_classified_and_every_entry_is_visited` learn the second table.
`tests/unit/quality/test_snapshot_joint_cap.py`,
`tests/unit/generation/statistical/test_numeric_grid.py`, `test_numeric_exact.py`,
`tests/unit/profiling/test_snapshot_cell_format.py` and `test_snapshot_values_numeric_shape.py`
change wherever they build through the document. Any test that imports `_freetext_stats` follows
the rename. Small fixture frames whose labels are under K grow their rows to keep the old intent.
No assertion is weakened to pass.

CLI: `tests/e2e/first_user/test_items_privacy.py`, `test_items_fit_joint_cap.py`
(`test_at9_raised_cap_keeps_every_cell_and_warns_nothing` keeps every cell only if each cell is
held by K rows), `test_items_generate.py`, `test_items_generate_init.py` and
`tests/e2e/test_fit_command.py`. Tiny CSV fixtures that sample categories grow, as above.

## 8. Placement

No new production file. One new test file beside the owning package.

| Change | File | Note |
|---|---|---|
| new `Rule` members, `SNAPSHOT_FLOOR_STATS`, `DATA_RULES`, `POLICY_REDACTED` v2, `REDACTED_POLICIES` | `src/decoy_engine/profiling/_value_redaction.py` (475 lines, about +40) | the one registry |
| `_floor_column`, the data rules, the G5 test, the free-text pass, the new step order, the `keep` predicate, the policy-set read at `:188` | `src/decoy_engine/profiling/_snapshot_values.py` (274 lines, about +150, ends near 425) | stays in the file the sentries scan; a new module would escape them |
| rename `_freetext_stats` to `freetext_stats` | `src/decoy_engine/quality/snapshot.py` (600 lines, net 0) | no census entry needed |
| accept `REDACTED_POLICIES`; refusal wording | `src/decoy_engine/generation/statistical/_spec.py` (about +3) | |
| docs | `docs/strategies.md` (what a plain snapshot keeps), `docs/compatibility-contract.md` dated note | |
| fragment | `changelog.d/fit-unflagged-values.md` with a `Breaking:` line | |
| tests | AT-1 to AT-12 in `tests/unit/profiling/test_snapshot_floor.py` (new, beside `test_snapshot_values.py`), plus 7b | |
| CLI code text | `src/decoy/cli/fit.py` docstring, lines 12 to 18 ("Unflagged categorical `top_values` still carry real source values") | C1 rides the CLI repin PR |
| CLI docs | `docs/guides/shape-and-privacy/03-fit-and-generate.md` lines 82 to 110 (an unflagged column "still holds its real values", "including a rare category and its exact largest and smallest number") and the kinds table at lines 70 to 76; `06-troubleshooting.md` entry for the G5 refusal; `decoy explain security` text if it repeats the old rule; `docs/ROADMAP.md` row 24f, `docs/RECENTLY-SHIPPED.md`, `CHANGELOG.md` | |

Expected size: E1 about 200 source lines in 4 production files plus 2 docs and a fragment, about
450 test lines. New public names: `freetext_stats` (renamed, module-public in `quality.snapshot`
like `numeric_stats`) and `REDACTED_POLICIES`. C1 about 60 lines of text in 4 files, plus tests.

## 9. Frozen contracts touched

- `distribution_snapshot_document` (frozen surface, `docs/frozen-surfaces.md:77`): the signature
  does not change; plain snapshot output does. Pre-GA break with a `Breaking:` line: "A plain
  `decoy fit` snapshot now keeps no label, joint cell or year held by fewer than 10 rows and no
  exact numeric or date extreme, and it writes short sentence columns as free text. A column too
  small to floor is withheld and listed. Use `--include-values` for the old content.
  `value_policy` is now `flagged-redacted/v2`."
- `compute_distribution_snapshot`: unchanged.
- `value_policy` string: v1 to v2; readers accept both. The CLI `json-shapes.json` freeze pins
  the type (`string`) only, so it does not change.
- `schema_version`: unchanged, `distribution-snapshot/v1`.
- Reason codes: none added; the existing refusal covers G5.
- `allow_real_categories`: unchanged. It still gates every non-DP categorical draw. The floor
  reduces what the opt-in releases; it does not replace the opt-in.
- Generated output (compatibility contract 3.3): changes for statistical columns fitted from a
  new plain snapshot. Old snapshot files generate as before.
- Scan documents: `_value_redaction.py` is shared with `profile_document` and
  `redact_profile_dict`, but `VALUE_FIELDS` and that code path do not change. The existing sentry
  `test_the_profile_redactor_uses_the_same_selection_stamp_and_applier` stays green. The same
  leak in profile documents is roadmap row 24zm.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E1 | 4.1 to 4.4, docs, compat note, fragment | R2 | 4 production files, about 200 source and 450 test lines | none | AT-1 to AT-12, the 7b engine list, `tests/unit/profiling/`, `tests/unit/generation/statistical/`, `tests/unit/quality/`, `tests/sentry/profiling/`, `tests/sentry/test_module_size.py` |
| C1 | CLI docstring, guide, troubleshooting, explain text, e2e fixtures, AT-C1, AT-C2, roadmap row | R1 | 4 production and doc files, about 60 lines plus tests | E1 released and pinned (repin checklist) | AT-C1, AT-C2, the 7b CLI list |

Row 24zm (`profile_document`) is a follow-up with its own plan; it is not a slice here.

E1 changes pinned tests and a serialized contract (an escalation trigger), so its merge head gets
the full engine suite against the saved main baseline. Tests run on the Mac first, then
`~/bin/vm-run`, never on the devbox.

## 11. Stop lines for builders

1. No second `Rule` enum, applier or `other_count` writer; extend the existing ones.
2. Do not change flagged-column handling, `VALUE_FIELDS`, or the `include_values=True` bytes.
3. Do not change `MIN_RELEASE_COUNT` or add a second floor constant.
4. `quality/snapshot.py` does not grow, and no module-size census entry, ceiling, sentry baseline
   or allowlist is added or raised.
5. `_snapshot_values.py` keeps passing the forbidden-shape guard: no float literal from 0 to 1
   (take the median with `statistics.median`), no inline null or `{}` assignment to a stats key,
   no `redacted_columns` string (the list goes through `stamp_value_policy`).
6. A red test outside 7b is a stop. Growing a fixture is allowed; weakening an assertion is not.
7. No new reason code. If the G5 refusal cannot reuse the existing one, stop and report.

## 12. Owner questions

None open. Taken 2026-11-16: K = 10 for labels, cells, years and bounds; the 3-word free-text
rule; `profile_document` moves to row 24zm.

## 13. Pre-mortem

- Small CSVs in tests and examples lose their categories (G5). Mitigation: the refusal names the
  fix; fixtures grow; the guide states the floor.
- Users read a missing rare label or year as a bug. Mitigation: guide text and the existing
  `other_count`.
- A future raw key escapes the floor. Mitigation: the registry sentry fails on an unclassified
  key.

## 14. Revision map

### Revision 2 (Dennis r1)

| # | Finding | Change |
|---|---|---|
| 1 | HIGH: `year_bins` not K-floored; month `min` makes the sampler pile draws at the bound | `FOLD_YEARS_UNDER_K` folds each year under K into the nearest kept year; `min`/`max` become whole kept-year edges, so the clamp never moves a draw (1.1, G3, 4.1, 4.2, 5, AT-5, mutations) |
| 2 | MEDIUM: G5 contradicted 4.2 and 6 | one rule per kind in G5, all through `_redact_column` and listed; how a listed numeric and datetime column then generate is in 4.4; AT-6 pins numeric and categorical |
| 3 | MEDIUM: free-text pass ran before the flagged names were known | step order in 4.2 profiles first; the pass skips flagged names; AT-12; class 9 |
| 4 | MEDIUM: "no bound equals a tail cell" fails on ties; end-bin claim did not follow | G2 and AT-1/AT-8 assert invariance under a tail swap; bins are now `m` grid steps, which makes the end-bin claim true (4.2) |
| 5 | LOW: `quality/snapshot.py` at 600 lines | no `freetext_columns` keyword; the conversion runs in `_snapshot_values.py` through the renamed `freetext_stats` (net 0 lines); stop line 4 |
| 6 | LOW: `snapshot_joint_warnings` compares `== POLICY_REDACTED` | `REDACTED_POLICIES` used there and in `_spec.py`; AT-7 |
| 7 | LOW: G2 overclaimed | G2 states grid, `p50` and grid-point coincidence and the `_coarse_range` magnitude release |
| 8 | LOW: G5 columns must join the flagged set before the joint loop | step order in 4.2; AT-6 joint assertion; class 5 |
