Status: plan

# FIT-UNFLAGGED-VALUES: a plain fit snapshot keeps no rare or extreme cell of any column (roadmap row 24f, open part)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `profiles/local-operations.md`, `workspace-and-vcs.md`,
`reuse-first.md`, `exploration.md`, `scope-discipline.md`, `proportionality.md`,
`verification.md`, `code-review.md`, `testing.md`, `architecture.md`,
`cross-cutting-concerns.md`, `api-and-compatibility.md`, `data-and-migrations.md`,
`documentation.md`, `catalogs/recurring-defects.md`; engine `docs/frozen-surfaces.md`,
`docs/strategies.md`, `tests/sentry/test_module_size.py`; CLI `docs/ROADMAP.md` row 24f (and
PR #291, which reopens it), CLI `docs/records/2026-11-10-cli-qa-generation-distribution-models.md`
findings H6 and H7.

Revision 4, after Codex review of revision 3. Every finding is taken; the change map is in
section 14.

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
all). Detection is a heuristic, so a column it misses keeps every cell. The flagged rule also
classifies datetime `year_bins` as value-free (`_value_redaction.py:150`), so it keeps raw years
with counts below K. The fix applies one floor to every released label, year bucket or bound,
including datetime columns flagged by the profiler or by G5. K is the existing
`MIN_RELEASE_COUNT` (10, `_value_redaction.py:58`), which the numeric shape blocks already use
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
- G3. Every released datetime bucket is a contiguous closed year range held by at least K rows,
  for unflagged, G5 and profiler-flagged columns. A v2 bucket is
  `{start_year, end_year, count}`. `min` and `max` are the first and last instant of the first
  and last range. A reader never treats the count of a range as the count of one year.
- G4. A short string column whose labels read as sentences is written as `freetext` (length
  statistics only), never as categorical.
- G5. When the floor would leave a column nothing to release, the column gets the flagged
  treatment (`_redact_column`) and is listed in `redacted_columns`. "Nothing to
  release" is, per kind: numeric with fewer than 2K finite cells; categorical (not bool) with
  every label under K; datetime with no single year held by K rows. The flagged numeric rule
  (`_coarse_range`) derives its power-of-ten bounds from the true extremes, so a G5 numeric column
  releases the order of magnitude of its range, exactly as a flagged one does today. A G5
  datetime column still releases folded multi-year buckets, never its raw `year_bins`.
- G6. `include_values=True` output is byte-identical to today.
- G7. The free-text pass skips flagged columns and their joints are withheld as today. Their
  datetime `year_bins` get the G3 fold before release.
- G8. A plain floored snapshot is `distribution-snapshot/v2`. The raw writer, DP writer and
  `include_values=True` keep writing `distribution-snapshot/v1`. Generation, admission and both
  fidelity scorers read valid v1 and v2 snapshots. A v1 `{year, count}` entry is normalized to a
  one-year range. A missing or unknown version and a bucket with the wrong fields or primitive
  types is refused.

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

Design notes: the floor adds no new abstraction. One more table joins the existing value-rule
registry and the writer applies it in the file the sentries already scan. The new stored bucket
shape does need one contract module because the writer, generation, admission and two
fidelity scorers must agree. `contracts/distribution_snapshot.py` owns the accepted schema
versions, the v2 writer model, a read adapter derived from that same model, the legacy v1 read
model and the one normalization function. It follows the CODEMAP row for versioned contracts and
sits beside `declared_casting.py`. No consumer imports a private module.

Writer choke point: `distribution_snapshot_document` is the only writer of a plain snapshot.
The CLI sentry `tests/sentry/io_policy/test_fit_value_redaction.py` refuses the raw writer in the
CLI. Inside the writer every value key is driven by the registry. Guard: the registry sentry
(AT-11) fails on a raw key that neither table classifies. Mutation that must turn it red: remove
one row of `SNAPSHOT_FLOOR_STATS`.

Reader choke point: `decode_datetime_buckets(schema_version, stats)` in the new contract module
is the only parser of stored datetime bucket entries. Generation spec loading and both fidelity
scorers call it. Admission and the statistical sampler use the normalized ranges carried by
`StatisticalSpec`, not the stored dicts. A sentry walks the
AST for reads of `year_bins`, `start_year` and `end_year` outside the contract writer, contract
decoder and named raw-snapshot tests. Mutation that must turn it red: read `b["year"]` again in
`_sample.py`.

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

### 4.2 Rules (all in `_snapshot_values.py`; the datetime fold is shared by both treatments)

- `TOP_CODED_RANGE`: n finite cells, n at least 2K (G5 takes the rest). `a` = K-th smallest and
  `b` = K-th largest. For `a < b`, start with the largest Heckbert nice step at or below
  `(b - a) / numeric_bins`. For `a == b`, start with the existing `_grid_edges` step. A step is
  never below the `1e-12` writable floor. Set `lo = floor(a / step) * step` and
  `m = max(numeric_bins, ceil((b - lo) / step), 1)`, then set `hi = lo + step * m`. This widens
  a narrow or constant domain instead of writing duplicate edges. Build all edges in `Decimal`,
  serialize them through the real 12-place writer, and require `m + 1` finite, strictly
  increasing stored numbers. If that check fails, advance through the nice-step sequence and
  rebuild. If Decimal-to-float conversion or endpoint arithmetic overflows near float max, use
  the public `_FALLBACK_DOMAIN` with exactly `numeric_bins` bins, not the existing one-bin G5
  path. The fallback contains no data-derived bound and clamps every finite cell into an end bin.
  `numeric_stats(non_null, bins=m, domain=(lo, hi))` then writes at least `numeric_bins` valid
  bins in every retained case. When `a < b`, clamping puts at least K rows in each end bin. When
  `a == b`, all rows may occupy one interior bin, which is the correct constant distribution.
  The sampler and shape decoder read the edge list, not its requested length. Everything depends
  only on `a`, `b`, n and the clamped counts, which gives G2.
- `K_TAIL_QUANTILES`: keep `pXX` only when `p * n >= K` and `(1 - p) * n >= K`; drop the rest.
  Type-7 interpolation at such a `p` reads order statistics K and above from each end, so a kept
  entry is unchanged by the tail swap in G2.
- `FOLD_YEARS_UNDER_K`: walk years from earliest to latest and merge adjacent years until the
  running count reaches K. Pass `(start_year, end_year, count)` to the contract encoder, which
  emits `{start_year, end_year, count}`, and start the next range. If the final range has fewer
  than K rows, merge it into the preceding range. This one fold is used by
  `_floor_column` and `_redact_column`, so unflagged, G5 and profiler-flagged datetime columns
  cannot release raw short years. The total count does not change.
- `KEPT_YEAR_START` / `KEPT_YEAR_END`: `min` is `YYYY-01-01T00:00:00` at the first bucket's
  lower edge, and `max` is `YYYY-12-31T23:59:59.999999` at the last bucket's upper edge. The
  sampler selects a range by `count`, then draws uniformly in seconds from January 1 of
  `start_year` to January 1 after `end_year`. It clamps only to the outer `min` and `max`.
  Whole-year range edges mean the clamp never moves a valid draw, so no draw piles up at a bound.
- `FOLD_UNDER_K`: `_collapse_counted_items` gains a `keep` predicate. Items with `count < K` move
  into `other_count`; the rest stay in order. Bool dtype columns skip it. A joint is folded the
  same way.

Order inside `distribution_snapshot_document` (plain mode):

1. Profile the frame and get the flagged names (moved up from `:262-264`).
2. Pick the free-text columns (4.3) among the unflagged string columns.
3. Compute the raw snapshot, then convert the free-text columns (4.3).
4. For each unflagged column, test G5. A G5 column joins the flagged set.
5. Fold datetime year bins into contiguous buckets for every column, then apply
   `_redact_column` to the flagged set and `_floor_column` to every other column. Both paths use
   the same fold.
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
`schema_version` change is in 4.5.

### 4.5 Versioned datetime buckets and readers

`contracts/distribution_snapshot.py` owns two exact versions. The v2 writer is one frozen strict
Pydantic model and a `TypeAdapter` over that same model is its stored reader, so field names and
types are not copied into a second validator. `encode_datetime_buckets` is the only v2 bucket
writer. V1 has a legacy read model for the existing
`{year, count}` bucket and normalizes it to `(year, year, count)`. V2 accepts only
`{start_year, end_year, count}`. Years and counts are strict integers, bool is refused, counts
are non-negative, and a range must have `start_year <= end_year`. The list must be ordered,
non-overlapping and non-empty when its total count is positive. The decoder refuses a missing
version, an unknown major version, mixed v1 and v2 entries, extra bucket fields and wrong stored
primitive types. The contract module exports the version constants, the frozen normalized
bucket type and `decode_datetime_buckets` through `decoy_engine.contracts`.

`distribution_snapshot_document` changes the schema version to `distribution-snapshot/v2` only
after it has made a plain document and replaced every datetime `year_bins` list with v2 ranges.
`compute_distribution_snapshot`, `fit_dp_snapshot` and the `include_values=True` return stay v1
and keep their bytes. `_spec.load_spec` accepts exactly v1 and v2, calls the contract decoder for
a datetime column and carries the normalized tuple on `StatisticalSpec`. `spec_from_dict`
normalizes the old v1 `stats` form when it reads a pinned plan that predates the new field, so old
pinned plans remain readable. `_window_admission.py` validates normalized range bounds against
the supported datetime years and requires the outer range edges to agree with `min` and `max`.
`statistical/_sample.py` selects a normalized range by count and samples uniformly over that
whole range. Neither module reads stored bucket dicts.

`quality/fidelity.py` and `quality/shape_fidelity.py` pass each document version to the same
decoder. For a v2 range they split its expected count across its calendar years in proportion to
the number of seconds in each year, then compare the aligned year vectors with the existing TVD
and KS formulas. This matches the sampler's uniform-in-time rule. When both documents are v1,
the existing one-year vectors and results are byte-identical. A malformed or mixed-version
bucket makes the column non-comparable through the scorer's existing malformed-input path; raw
exception text is not surfaced.

## 5. Behaviour (DI models QA fixture, 1,000 rows)

| Column | Today | After |
|---|---|---|
| `salary`, one row 987,654 | `max: 987654` | `max` on a grid at or above the 10th largest cell; the one row is clamped into the top bin |
| `diagnosis` with `RARE-HIV-B20` x1 | label stored, generated 9 times | folded into `other_count`, never generated |
| `note`, 30 three-word strings | categorical, all 30 stored | `freetext`, length statistics only |
| `state` (CA, NY, ...), each label over 10 rows | stored | stored, unchanged |
| `is_active` bool with one `False` | stored | stored (bool exempt) |
| `visit_date` with one 1921 row, the rest 2015 to 2024 | exact first and last timestamp; `{"year": 1921, "count": 1}` | first v2 range starts at 1921 and ends at the first later year that brings its count to K; `min` is 1921-01-01 and `max` is 2024-12-31T23:59:59.999999 |
| 15-row file, `state` with 3 to 6 rows per label | stored | G5: withheld and listed; generate refuses with the existing code and hint |
| 15-row file, `amount` numeric | exact bounds | G5: one coarse interval, listed |
| any column with `--include-values` | raw | raw, byte-identical |

### 5.1 Fidelity cost

- Numeric, histogram path: an ordinary span widens by at most one grid step (about one tenth of
  the K-trimmed range) on each side, and the outer K rows on each side are clamped into the end
  bins. A span below the writable grid widens enough to hold the requested bins. The float-max
  fallback uses the public fixed domain. Columns with 100 or more finite cells use
  `quantile_grid`, which is unchanged, so their draws do not move. Generation output changes for
  numeric columns under 100 rows.
- Numeric `quantiles`: `p05` and `p95` need 200 rows, `p25` and `p75` need 40. Only reports read
  them; the sampler does not.
- Categorical: labels held by fewer than 10 rows vanish, and their mass goes to the kept labels
  (or to `OTHER` with `other_mode: emit`). On 1,000 rows that is each label under 1%; on 100 rows,
  each label under 10%. A column with fewer than 10 rows per label is withheld.
- Free text: short sentence columns become length-matched filler. A phrase vocabulary of 3 or
  more words (for example `Type 2 diabetes`) is caught too; `--include-values` restores it.
- Datetime: adjacent years become contiguous buckets of at least 10 rows. A final short bucket
  joins the preceding bucket. This also applies to G5 and profiler-flagged columns. Draws spread
  across the selected bucket instead of preserving each year's weight, and the outer buckets use
  whole-year edges instead of the exact ends.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| Numeric column with under 2K finite cells | G5: `_redact_column` (one coarse interval), listed |
| Only inf cells | left alone, as today (`_coarse_range` returns early) |
| `a == b` (K-th smallest equals K-th largest) | step from `_grid_edges`; widen to at least `numeric_bins`; all mass may occupy one bin |
| `0 < b - a < numeric_bins * 1e-12` | use the `1e-12` floor and widen the domain until at least `numeric_bins` distinct edges serialize |
| Grid arithmetic or conversion overflows near float max | use `_FALLBACK_DOMAIN` with exactly `numeric_bins` valid bins |
| Every categorical label under K | G5: withheld and listed; generate refuses with `plan.statistical_snapshot_values_redacted` and the fix hint |
| Datetime with no single year held by K rows | G5: listed, but its v2 ranges still each hold at least K rows |
| A G5 or free-text column in a joint | the joint is withheld (step 6 after step 4) |
| `condition_on` with a folded parent label | the child draws from its marginal (existing fallback, counted) |
| Joint at a raised `contingency_top_k` | cells under K fold; `snapshot_joint_warnings` reports them as `policy_dropped` (existing field) |
| `quantile_grid` decoder bound check | grid points lie at or inside the K-th extremes, so inside `[lo, hi]`; AT-9 proves it |
| Old v1 snapshot | each `{year, count}` is read as a one-year range; generation and fidelity results stay unchanged |
| Missing schema version, unknown version or wrong bucket shape/type | generation refuses with the existing schema or degenerate-stat code; fidelity marks the column non-comparable without raw exception text |
| A forged `flagged-redacted/v3` | refused as an unknown policy (existing test, new spelling) |
| A flagged short-sentence column | stays flagged and categorical-withheld; the free-text pass never sees it (G7) |
| Object column with mixed types | the free-text test reads `str(value)`, as the snapshot does |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged column and joint of a plain snapshot; the G5 refusal text | `SNAPSHOT_FLOOR_STATS` in the one registry, applied in `distribution_snapshot_document`; the refusal names columns only | AT-1 to AT-6, AT-8 | drop `FOLD_UNDER_K` from the table |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory frame; nothing opened, staged or leased | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state or cache is added | n/a | n/a |
| 4 | Route parity and silent fallback | `decoy fit`, the engine API, `ui/summary.py` (counts only) | the CLI and engine API call `distribution_snapshot_document`; the CLI sentry refuses the raw writer; summary reads counts only | AT-C1 and the existing `test_fit_value_redaction.py` | call `compute_distribution_snapshot` from `cli/fit.py` |
| 5 | Referential integrity | `condition_on` with a folded parent label; a joint with a G5 column | existing marginal fallback; step order in 4.2 | AT-9 conditional column; AT-6 joint | run the joint loop before the G5 test |
| 6 | Untrusted producer | a hand-edited snapshot marker or datetime bucket | readers accept exact policy and schema versions; the contract decoder strictly validates bucket fields and types | AT-5, AT-7, AT-13 | accept any `flagged-redacted/*` prefix or coerce a bucket string to int |
| 7 | Check then use (TOCTOU) | none | N/A: no new file read; the frame is read once by the caller | n/a | n/a |
| 8 | Weak tests | a floor test that passes on a frame with no rare cell | each canary test first asserts the canary is in the raw snapshot | AT-1 to AT-5 non-vacuity line | build the AT-2 frame without the rare row |
| 9 | Refactor drift | `include_values=True`, flagged columns | those paths do not change; the free-text pass excludes flagged names | AT-10, AT-12, existing flagged tests | run the free-text pass on every string column |
| 10 | Frozen contract drift | `distribution_snapshot_document` output, schema version, `value_policy`, generated output 3.3 | `Breaking:` line, compat note, v1 read model and reader-first slice | AT-7, AT-13, section 9 | drop v1 from the accepted schema versions |

### 6.2 Enumerations

#### Exit paths

- No new exit path: the G5 refusal reuses `plan.statistical_snapshot_values_redacted`, raised at
  `generation/statistical/_spec.py:292-298` (CLI exit 1).
- The existing `DistributionSnapshotError` refusals of `compute_distribution_snapshot` are
  unchanged and still raise before the floor runs.

#### Routes

- `decoy fit`, CLI `src/decoy/cli/fit.py`: writes the plain snapshot and passes `numeric_bins`.
- The engine API `distribution_snapshot_document`, `profiling/_snapshot_values.py:222`.
- CLI `ui/summary.py:370-371`: reads null counts only, so the floor does not change its result.
- `fit_dp_snapshot`: a separate DP route, not touched.

#### FK shapes

- N/A: the floor reads one column at a time and never a key relationship.
- `fanout` degree counts are counts, not values, and are out of scope (section 2).

#### Fields

- Snapshot kinds `numeric`, `categorical`, `datetime`, `freetext`, `empty` and the joint
  (`profiling/_value_redaction.py:115-156`); the keys each rule touches are in 4.1.
- V2 replaces each datetime bucket's `year` key with `start_year` and `end_year`.
  `value_policy` and `redacted_columns` keep their types.

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
| AT-1 | unflagged salary (canary 987,654 present in the raw snapshot): `max` is not 987,654. Invariance: replace the 9 largest cells with other values above the 10th largest and the 9 smallest with other values below the 10th smallest; `min`, `max`, `bin_edges`, `bin_counts` and every kept `quantiles` entry are equal before and after the swap. For `a < b`, each end bin holds at least K. For ordinary, constant, nonzero spans below `numeric_bins * 1e-12`, and finite cells near float max, the stored edges are finite and strictly increasing, `len(bin_counts) >= numeric_bins`, and counts sum to n. The narrow and overflow cells each request 17 bins | `max == 987654`; the swap moves `max`; narrow edges duplicate after rounding; the overflow fallback has one bin |
| AT-2 | the document's JSON text does not contain `RARE-HIV-B20`; `other_count` grew by 1; every kept label count is at least K | label stored with count 1 |
| AT-3 | joint of two unflagged columns: every kept cell count is at least K; folded mass is in `other_count` | count-1 cell stored |
| AT-4 | the 30-string note column is `kind: freetext` with a `cell_format` blank count; no note string is in the JSON | categorical, all 30 stored |
| AT-5 | three datetime columns with the same years: one unflagged, one forced into G5 because no single year has K rows, and one profiler-flagged. Each v2 entry has exact strict fields `{start_year, end_year, count}`; ranges are ordered, contiguous across observed years and non-overlapping; every count is at least K; a short tail joins the last range; and total count is unchanged. `min` and `max` are the outer range edges. A seeded draw selects ranges at their recorded weights, spreads draws across every year in a multi-year range, and has no pile-up at either outer bound | raw short `{year, count}` entries and exact bounds stored; the old sampler assigns all range mass to one year |
| AT-6 | 15-row frame with a categorical `state` (3 to 6 rows per label), a numeric `amount`, a G5 datetime spread across years, and a joint `(state, tier)`: all three columns are in `redacted_columns`; `state` has empty `top_values`; `amount` has one coarse bin; every datetime year bucket count is at least K; the joint has no cells; `load_spec` refuses `state` with `plan.statistical_snapshot_values_redacted` | labels, raw short year bins and joint cells stored; spec loads |
| AT-7 | `value_policy == "flagged-redacted/v2"`; plain output has `schema_version == "distribution-snapshot/v2"`; raw, DP and `include_values=True` output stay v1; `load_spec` accepts schema v1 and v2 and refuses a missing version and v3; `snapshot_joint_warnings` exempts a withheld joint for both policy versions | marker is v1; schema v2 is refused |
| AT-8 | property (hypothesis, as `test_snapshot_values.py` already uses): for random numeric, string, datetime and bool frames, the G1 to G3 floors hold for every unflagged column, and the AT-1 swap leaves numeric bounds unchanged | fails on the first count-1 label, rare year or moved bound |
| AT-9 | round trip: fit the QA frame, generate 5,000 rows; the numeric shape decodes, no generated label is a folded label, and the per-column marginal similarity from `quality.fidelity` is at least 0.95 for `salary`, `state` and `visit_date`. Both fidelity scorers accept a v2 range against a v1 generated snapshot and use the range's uniform-in-time expected year counts | the v2 bucket crashes or is assigned to one year |
| AT-10 | guards that stay green: a bool column keeps a count-1 `False`; 2-word labels (`New York`) stay categorical; `include_values=True` equals the raw snapshot plus the two keys (existing `test_include_values_is_the_raw_snapshot_plus_the_two_keys`) | not fail-before: they pin what must not change |
| AT-11 | sentry (`tests/sentry/profiling/test_snapshot_value_registry.py`): every raw key is classified across both tables; `other_count` still has one writer; the existing forbidden-shape guard stays green | new rule keys unclassified |
| AT-12 | a forced-flagged column of 3-word strings is withheld as a flagged categorical (`kind: categorical`, empty `top_values`), not converted to freetext | the pass ran before the profile and converted it |
| AT-13 | contract matrix: a valid v1 datetime document produces one-year normalized ranges and the same seeded generated bytes and fidelity scores as before; a valid v2 multi-year range normalizes unchanged. Missing and v3 schema versions, mixed v1/v2 fields, bool/string/float years or counts, extra fields, inverted ranges, overlap and out-of-order ranges are refused. The AST sentry finds a seeded direct `year_bins` parse outside the contract | no v2 read model; current coercion accepts strings and bools; direct readers bypass one contract |

Mutations that must turn a test red: drop `FOLD_UNDER_K` from the table (AT-2, AT-3, AT-8,
AT-11); take `a` and `b` as the min and max (AT-1, AT-8); remove the `max(numeric_bins, ...)`
term or use the one-bin float-max fallback (AT-1); leave unflagged `year_bins` unfolded (AT-5,
AT-8); leave flagged `year_bins` unfolded (AT-5, AT-6); parse a v2 range as its start year or
coerce a string count (AT-5, AT-9, AT-13); set `min` to the month of the K-th earliest value
(AT-5 pile-up check); run the joint loop before the G5 test (AT-6); skip the
free-text pass (AT-4); run it on flagged names (AT-12); keep v1 (AT-7); compare
`== POLICY_REDACTED` in `snapshot_joint_warnings` (AT-7); fold bool columns (AT-10); read a stored
bucket directly in `_sample.py` (AT-13 sentry).

CLI (C1), after the engine release that carries E1:

| # | Test | Fail before |
|---|---|---|
| AT-C1 | plain `decoy fit --numeric-bins 17` on the QA frame exits 0: no canary (`RARE-HIV-B20`, `987654`, any note string) appears as a stored cell; the datetime uses v2 ranges rather than a representative `1921` year entry; salary has at least 17 valid `bin_counts`; `fit --json` shows `value_policy: flagged-redacted/v2` (`tests/e2e/first_user/test_items_privacy.py`). The former `test_numeric_bins_without_epsilon_exits_usage` is rewritten to prove plain mode reaches `distribution_snapshot_document` with 17, while DP mode still passes 17 to `fit_dp_snapshot` | current CLI exits 2 before reading the CSV and passes the option only to DP fit |
| AT-C2 | a 15-row fit, then `decoy validate` on a statistical categorical column: exit 1 with the redacted code and the `--include-values` hint | validate passes |

### 7b. Existing tests that change

Engine: `tests/unit/profiling/test_snapshot_values.py::test_plain_columns_equal_the_raw_snapshot`
and `::test_a_joint_of_two_plain_columns_is_unchanged` pin "unflagged equals raw" and are
rewritten to the floor. `tests/unit/generation/test_statistical_redacted.py::test_an_unknown_or_ill_typed_policy_refuses`
lists `flagged-redacted/v2` as unknown; it moves to v3.
`tests/sentry/profiling/test_snapshot_value_registry.py::test_the_four_snapshot_rules_join_the_one_rule_enum`
and `::test_every_visited_key_is_classified_and_every_entry_is_visited` learn the second table.
The same file's `test_a_sixth_kind_literal_is_seen_by_the_source_read` at lines 152 to 154 changes
because its source-text witness matches `return "freetext", _freetext_stats`, and that helper is
renamed to `freetext_stats`.
`tests/unit/quality/test_snapshot_joint_cap.py`,
`tests/unit/generation/statistical/test_numeric_grid.py`, `test_numeric_exact.py`,
`tests/unit/profiling/test_snapshot_cell_format.py` and `test_snapshot_values_numeric_shape.py`
change wherever they build through the document. Any test that imports `_freetext_stats` follows
the rename. `tests/unit/generation/test_statistical.py`,
`tests/unit/generation/test_window_admission.py`, `tests/unit/quality/test_fidelity.py` and
`test_shape_fidelity.py` add v1 and v2 datetime cells. Small fixture frames whose labels are under
K grow their rows to keep the old intent. No assertion is weakened to pass.

CLI: `tests/e2e/first_user/test_items_privacy.py`, `test_items_fit_joint_cap.py`
(`test_at9_raised_cap_keeps_every_cell_and_warns_nothing` keeps every cell only if each cell is
held by K rows), `test_items_generate.py`, `test_items_generate_init.py` and
`tests/e2e/test_fit_command.py`. The last file replaces
`test_numeric_bins_without_epsilon_exits_usage` with the plain-fit forwarding test and retains a
separate DP forwarding test. Tiny CSV fixtures that sample categories grow, as above.

## 8. Placement

One new production contract file and two new test files. The existing files remain in the
CODEMAP owners that already contain their concern.

| Change | File and directory | CODEMAP placement | Existing neighbour or reason |
|---|---|---|---|
| v2 datetime bucket writer, derived read adapter, v1 read model, encoder and decoder | `src/decoy_engine/contracts/distribution_snapshot.py` | "Versioned contracts" row: `src/decoy_engine/contracts/<contract>.py` | beside `declared_casting.py`; shared by profiling, quality and generation without a private import |
| contract matrix | `tests/unit/contracts/test_distribution_snapshot.py` | "Unit tests" row: mirror `src/` under `tests/unit/<package>/` | first contract-specific unit folder; beside the owning package by map |
| new `Rule` members, `SNAPSHOT_FLOOR_STATS`, `DATA_RULES`, policy v2 and accepted policies | `src/decoy_engine/profiling/_value_redaction.py` | "Detectors, profiling" row | existing value-rule registry |
| floor rules, writable numeric grid, year fold, G5, free-text pass and writer schema stamp | `src/decoy_engine/profiling/_snapshot_values.py` | "Detectors, profiling" row | existing plain snapshot writer and sentry target |
| rename `_freetext_stats` to `freetext_stats` | `src/decoy_engine/quality/snapshot.py` | existing quality snapshot owner named in the map | net zero lines; no census entry needed |
| accept schema versions, decode ranges and carry normalized buckets | `src/decoy_engine/generation/statistical/_spec.py` | "Generation" row and the existing statistical sub-package | existing persisted snapshot loader |
| admit normalized datetime ranges | `src/decoy_engine/generation/_window_admission.py` | "Generation" row | existing statistical admission owner |
| sample normalized datetime ranges | `src/decoy_engine/generation/statistical/_sample.py` | "Generation" row | existing one statistical sampler |
| score v2 ranges against v1 output | `src/decoy_engine/quality/fidelity.py`, `src/decoy_engine/quality/shape_fidelity.py` | existing quality scorer owners named in the map | no second fidelity mechanism |
| floor acceptance tests | `tests/unit/profiling/test_snapshot_floor.py` | "Unit tests" row | beside `test_snapshot_values.py` |
| decoder bypass sentry | `tests/sentry/profiling/test_snapshot_datetime_contract.py` | "Sentry test" row: existing rules under `tests/sentry/` | beside the snapshot registry sentry |
| engine docs and fragment | `docs/strategies.md`, `docs/compatibility-contract.md`, `changelog.d/fit-unflagged-values.md` | "Feature and contract docs" and "Changelog fragments" rows | existing durable owners |
| CLI option validation, help and plain writer call | `src/decoy/cli/fit.py` | existing CLI command file; no new module in the frozen flat package | remove `--numeric-bins` from the DP-only list; pass it to `distribution_snapshot_document` in plain mode and to `fit_dp_snapshot` in DP mode |
| CLI tests and docs | `tests/e2e/first_user/test_items_privacy.py`, `tests/e2e/test_fit_command.py`, the 7b files, shape-and-privacy guides, roadmap, shipped log and changelog | CLI CODEMAP "First-user QA item tests" and "Task-oriented user guides" rows; existing command tests stay in place | C1 rides the engine repin PR |

Expected size: E0 about 250 production and 300 test lines across 6 production files. E1 about
240 production and 450 test lines across 3 production files, plus 2 docs and a fragment. Each
is below 800 changed lines. New public names: `DatetimeBucket`, `DatetimeBucketV2`,
`encode_datetime_buckets`, `decode_datetime_buckets`, the
schema-version constants, `freetext_stats` and `REDACTED_POLICIES`. C1 changes 1 production file
and about 90 source, test and doc lines.

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
- `schema_version`: plain floored documents become `distribution-snapshot/v2` because datetime
  bucket entries change shape. Raw, DP and `include_values=True` documents stay v1. Readers ship
  before the writer and accept exact v1 and v2 shapes. The compatibility corpus keeps one v1
  datetime artifact and adds one v2 multi-year artifact.
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
| E0 | 4.5 reader support and contract guard, no writer change | R2 | 6 production files; about 250 source and 300 test lines; below 800 total | none | AT-5 sampler cells, AT-9 fidelity cells, AT-13, existing statistical generation, admission and quality fidelity suites, contract bypass sentry, import layers, module size |
| E1 | 4.1 to 4.4 writer and floor, docs, compat note, fragment | R2 | 3 production files; about 240 source and 450 test lines; below 800 total | E0 merged | AT-1 to AT-12 writer cells, the 7b engine list, `tests/unit/profiling/`, `tests/unit/generation/statistical/`, `tests/unit/quality/`, `tests/sentry/profiling/`, `tests/sentry/test_module_size.py` |
| C1 | CLI option validation and forwarding, command text, guide, troubleshooting, explain text, e2e fixtures, AT-C1, AT-C2, roadmap row | R1 | 1 production file; about 90 source, test and doc lines | E1 released and pinned (repin checklist) | AT-C1, AT-C2, rewritten plain and DP numeric-bin forwarding tests, the 7b CLI list |

Row 24zm (`profile_document`) is a follow-up with its own plan; it is not a slice here.

E0 changes a serialized contract and E1 changes pinned tests, both escalation triggers. Each
merge head gets the full engine suite against the saved main baseline. Tests run on the Mac
first, then `~/bin/vm-run`, never on the devbox.

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
8. No reader parses `year_bins`, `start_year` or `end_year` outside the contract decoder, and no
   writer builds a v2 bucket outside the contract encoder. The statistical spec carries
   normalized buckets to admission and sampling.
9. Do not change raw, DP or `include_values=True` schema versions or bytes while adding v2 plain
   output. Do not remove the v1 read model.
10. A slice stops if it exceeds 10 production files or 800 changed lines. Split tests or docs by
    the E0/E1 boundary instead of raising the limit.

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
- A future consumer assumes one year per bucket. Mitigation: one strict decoder owns both stored
  versions and the AST sentry fails on a direct parse.
- A narrow or near-overflow numeric domain writes duplicate edges. Mitigation: AT-1 checks the
  stored JSON edges, not the pre-serialization Decimal list.

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

### Revision 3 (Dennis r2)

| # | Finding | Change |
|---|---|---|
| 1 | V1: G5 and profiler-flagged datetime columns kept raw short `year_bins` | one shared contiguous bucket fold now covers unflagged, G5 and profiler-flagged datetime columns; G3, G5, 1.2, 4.2 steps, 5.1, AT-5, AT-6 and mutations pin it |
| 2 | V1: the claimed upper bound on numeric bin count was false | the largest nice step at or below the requested width makes `numeric_bins` a minimum; 4.2 proves `m <= ceil(5 * numeric_bins / 2) + 1`, and AT-1 and AT-C1 pin engine and CLI behavior |
| 3 | V2-LOG: the freetext helper rename would break a source-text sentry | 7b names `test_a_sixth_kind_literal_is_seen_by_the_source_read` and its old `_freetext_stats` witness |

### Revision 4 (Codex review of revision 3)

| # | Finding | Change |
|---|---|---|
| 1 | V1: multi-year datetime buckets had no stored range representation and generation, admission and fidelity still assumed one year per entry | G3 and G8 define strict v2 `{start_year, end_year, count}` buckets; 4.5 adds one versioned contract decoder, v1 normalization, reader-first slice E0, range sampling, admission and both fidelity readers; AT-5, AT-7, AT-9 and AT-13 prove v1 compatibility and v2 behavior |
| 2 | V1: plain `decoy fit --numeric-bins 17` was rejected as DP-only and the option reached only `fit_dp_snapshot` | C1 removes only `--numeric-bins` from the DP-only rejection, updates help, calls `distribution_snapshot_document` for plain fit and forwards 17 on both plain and DP routes; AT-C1 and the rewritten command test pin both calls |
| 3 | V1: spans below the 12-place writable grid and the float-max fallback could not meet the promised minimum bin count | 4.2 widens narrow and constant domains, validates the serialized edges and makes the public fallback use exactly the requested bins; failure modes and AT-1 add narrow-span and near-float-max red-before cells |
| 4 | V2-LOG: the Rules consulted list omitted selected rulebooks | the header now lists code review, testing, architecture, cross-cutting concerns, API compatibility and the other rulebooks read for this revision |
