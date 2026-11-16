Status: plan

# FIT-UNFLAGGED-VALUES: a plain fit snapshot keeps no rare or extreme cell of any column (roadmap row 24f, open part)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `proportionality.md`; engine `docs/frozen-surfaces.md`,
`docs/strategies.md`; CLI `docs/ROADMAP.md` row 24f (and PR #291, which reopens it), CLI
`docs/records/2026-11-10-cli-qa-generation-distribution-models.md` findings H6 and H7.

Bases (2026-11-16): engine `origin/main` `ddd014a5` (release 0.27.0), CLI `origin/main`
`307a189a`. Line numbers are read at these bases.

Owner decisions used: V1 bar (a leak of a non-admin value blocks V1); row 24f is a leak class
that blocks V1; "names may show in messages, data values never"; pre-release, so snapshot output
may change with a `Breaking:` line.

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
unflagged datetime column keeps its exact earliest and latest timestamp (`_datetime_stats`,
`:491-501`), and a joint cell with a count of one names a combination held by one row
(`_joint_snapshot`).

### 1.2 Root cause

The plain-snapshot policy has one switch per column: flagged (withhold all) or not flagged (keep
all). Detection is a heuristic, so a column it misses keeps every cell. The fix is a second,
weaker rule for every column the first rule does not cover: no released number, label or string
may be a fact about fewer than K source rows. K is the existing `MIN_RELEASE_COUNT` (10,
`_value_redaction.py:58`), which the numeric shape blocks already use
(`generation/statistical/_numeric_shape.py`). One constant sets one floor.

## 2. Guarantee

For a snapshot written by `distribution_snapshot_document(..., include_values=False)`:

- G1. Every label in a categorical `top_values` and every joint cell key is held by at least K
  source rows. Bool columns are exempt: their vocabulary (`True`, `False`) is public, and a
  count is not a value.
- G2. A numeric column's `min`, `max` and `bin_edges` sit on a grid chosen from the K-th smallest
  and K-th largest cells, never from the extremes. Each `quantiles` entry kept has at least K
  rows on each side. `mean` and `std` are kept only when the column has at least K finite cells.
  `quantile_grid` and `exact_values` keep their existing K floor and do not change.
- G3. A datetime column's `min` and `max` are month edges around the K-th earliest and K-th latest
  values.
- G4. A short string column whose labels read as sentences is written as `freetext` (length
  statistics only), never as categorical.
- G5. A column with fewer than 2K usable cells, or a categorical column whose every label falls
  under K, gets the flagged treatment: it is withheld and listed in `redacted_columns`.
- G6. `include_values=True` output is byte-identical to today.
- G7. Flagged columns are treated exactly as today.

Non-goals (V1): interior histogram bins with a small count (a count on a public grid, not a
value); fan-out degree counts; freetext length statistics; scan and profile documents (owner
question Q3); reconstruction across several snapshots of the same source (the V1 threat model
covers accidental leaks only).

## 3. Established solutions

Search run: SDC handbook and sdcMicro (already cited in the code), synthpop `sdc()`, SDV
synthesizer docs, ARX, CMS cell-size policy; in the codebase, the redaction registry, the
numeric shape release floor and the coarse-range helpers.

| Source | What it does | Used here |
|---|---|---|
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), 3.4 and 4.2; cited at `_value_redaction.py:55-58` | Global recoding, top and bottom coding, and a minimum frequency rule (thresholds of 3 to 11) for released cells | K floor on labels and joint cells; top and bottom coding of numeric and date bounds |
| CMS cell-size suppression policy | Suppresses any published cell under 11 | Supports K = 10 |
| R synthpop `sdc()` ([docs](https://rdrr.io/cran/synthpop/man/sdc.html)) | `bottom.top.coding` limits per variable and `rm.replicated.uniques` before synthetic data is released | The same steps, applied to the fitted model instead of the output |
| R sdcMicro `topBotCoding` ([docs](https://www.rdocumentation.org/packages/sdcMicro/versions/4.6.0/topics/topBotCoding)) and `globalRecode` | Replace values beyond a limit with the limit; recode to intervals | The numeric bound rule; `_coarse_domain` already cites `globalRecode` |
| ARX (Prasser and Kohlmayer; k-anonymity with a suppression limit) | Records in groups smaller than k are suppressed, not published | The fold of rare labels and cells into `other_count` |
| SDV synthesizers, `enforce_min_max_values=True` by default ([docs](https://docs.sdv.dev/sdv/single-table-data/modeling/synthesizers/ctgansynthesizer)) | Learns and stores the exact real min and max | The counter-example: the H6a leak is SDV's default. We do not follow it |
| Heckbert, "Nice numbers for graph labels" (Graphics Gems 1990); cited at `_snapshot_values.py:16` | Steps of 1, 2 or 5 times a power of ten | Grid step for numeric bounds |

Free text in a low-cardinality column: no surveyed tool tests for it. SDV and synthpop pick a
type from the dtype and the distinct count only, as Decoy does today. The word-count test in 4.3
is our own rule; its threshold is owner question Q2.

Codebase reuse: `_grid_edges` and `_coarse_range` (fallback for tiny columns),
`numeric_stats(domain=...)` (already clamps outliers into the end bins), `_collapse_counted_items`
(the one `other_count` writer, pinned by a sentry), `_freetext_stats`, `MIN_RELEASE_COUNT`, the
`Rule` enum and the snapshot registry in `_value_redaction.py`, and the existing refusal
`plan.statistical_snapshot_values_redacted` for withheld columns.

## 4. Design

Design notes: no new module and no new abstraction. One more table in the existing registry,
applied by the existing applier in the file the sentries already scan. Choke point:
`distribution_snapshot_document` is the only writer of a plain snapshot (CLI sentry
`tests/sentry/io_policy/test_fit_value_redaction.py` already refuses the raw writer in the CLI),
and inside it every value key is driven by the registry. Guard: the registry sentry (AT-11)
fails on a raw key that neither table classifies. Mutation that must turn it red: remove one row
of `SNAPSHOT_FLOOR_STATS`.

### 4.1 Registry

`_value_redaction.py` gains a second table beside `SNAPSHOT_VALUE_STATS`:
`SNAPSHOT_FLOOR_STATS`, the rules for an unflagged column in a plain snapshot. New `Rule`
members join the one enum: `TOP_CODED_RANGE`, `K_TAIL_QUANTILES`, `NULL_UNDER_K`,
`MONTH_FLOOR_START`, `MONTH_FLOOR_END`, `FOLD_UNDER_K`. All are data rules (`DATA_RULES`).

| Scope, key | Rule |
|---|---|
| numeric `min`, `max`, `bin_edges`, `bin_counts` | `TOP_CODED_RANGE` |
| numeric `quantiles` | `K_TAIL_QUANTILES` |
| numeric `mean`, `std` | `NULL_UNDER_K` |
| datetime `min` / `max` | `MONTH_FLOOR_START` / `MONTH_FLOOR_END` |
| categorical `top_values`, joint `cells` | `FOLD_UNDER_K` |

Keys not listed (`quantile_grid`, `exact_values`, `year_bins`, freetext length statistics,
counts) are already value-free or already K-floored.

### 4.2 Rules (all in `_snapshot_values.py`, applied by one `_floor_column`)

- `TOP_CODED_RANGE`: with n finite cells and n at least 2K, take `a` = K-th smallest and
  `b` = K-th largest. Step = the Heckbert nice number (1, 2 or 5 times a power of ten) at or
  above `(b - a) / numeric_bins`, or the `_grid_edges` step when `a == b`. Domain
  `lo = floor(a / step) * step`, `hi = lo + step * ceil((b - lo) / step)`, with `hi > lo`,
  computed in `Decimal` as `_grid_edges` does. Then `numeric_stats(non_null, bins=numeric_bins,
  domain=(lo, hi))` and copy the four keys. Cells outside the domain are clamped into the end
  bins, so each end bin holds at least K rows. With n under 2K: the existing `_coarse_range`.
- `K_TAIL_QUANTILES`: keep `pXX` only when `p * n >= K` and `(1 - p) * n >= K`; drop the rest.
- `NULL_UNDER_K`: null when n < K.
- `MONTH_FLOOR_START` / `MONTH_FLOOR_END`: first instant of the month of the K-th earliest value,
  last instant of the month of the K-th latest. With fewer than 2K values: the existing year
  edges. `year_bins` do not change.
- `FOLD_UNDER_K`: `_collapse_counted_items` gains a `keep` predicate. Items with `count < K` move
  into `other_count`; the rest stay in order. Bool dtype columns skip it. A joint is folded the
  same way. If every label of a categorical column folds, the column is withheld (G5).

### 4.3 Free-text test

Before the raw snapshot is computed, `distribution_snapshot_document` (plain mode only) picks the
string columns with at most `CATEGORICAL_DISTINCT_CAP` distinct values where the median distinct
label has 3 or more whitespace-separated words. It passes them as a new keyword
`freetext_columns` to `compute_distribution_snapshot`, which writes them with `_freetext_stats`
and `kind: freetext`. The kind is decided once, so `cell_format` (the blank count is
freetext-only) and `add_numeric_shape` stay consistent. A joint that names such a column is
withheld, as for a flagged column. `high_cardinality_columns` wins over the test (the caller
asked for categories), and those columns still fold under K in plain mode.

### 4.4 Marker

`POLICY_REDACTED` becomes `"flagged-redacted/v2"`: the string now also means "every other column
is floored at K". `generation/statistical/_spec.py:273` accepts `v1` and `v2`, so old files keep
working. Columns withheld by G5 are listed in `redacted_columns`, and the existing refusal text
"(a sensitive column)" becomes "(a sensitive column, or one whose values are each held by fewer
than 10 rows)". The snapshot `schema_version` stays `distribution-snapshot/v1`: no key or kind is
added, and today's reader reads the new files.

## 5. Behaviour (DI models QA fixture, 1,000 rows)

| Column | Today | After |
|---|---|---|
| `salary`, one row 987,654 | `max: 987654` | `max` on a grid at or above the 10th largest cell, for example `900000`; the one row is clamped into the top bin |
| `diagnosis` with `RARE-HIV-B20` x1 | label stored, generated 9 times | folded into `other_count`, never generated |
| `note`, 30 three-word strings | categorical, all 30 stored | `freetext`, length statistics only |
| `state` (CA, NY, ...), each label over 10 rows | stored | stored, unchanged |
| `is_active` bool with one `False` | stored | stored (bool exempt) |
| `visit_date` | exact first and last timestamp | month edges around the 10th earliest and latest |
| 15-row file, `state` with 3 to 6 rows per label | stored | every label folds; column withheld and listed; generate refuses with the existing code and hint |
| any column with `--include-values` | raw | raw, byte-identical |

### 5.1 Fidelity cost

- Numeric, histogram path: bounds widen by at most one grid step (one tenth of the K-trimmed
  range, rounded up to a nice number) on each side. The outer K rows on each side are clamped
  into the end bins, so generated values never pass the grid bound. Columns with 100 or more
  finite cells use `quantile_grid`, which is unchanged, so their draws do not move. Generation
  output changes for numeric columns under 100 rows.
- Numeric `quantiles`: `p05` and `p95` need 200 rows, `p25` and `p75` need 40. Only reports read
  them; the sampler does not.
- Categorical: labels held by fewer than 10 rows vanish, and their mass goes to the kept labels
  (or to `OTHER` with `other_mode: emit`). On 1,000 rows that is each label under 1%; on 100 rows,
  each label under 10%. A column with fewer than 10 rows per label is withheld.
- Free text: short sentence columns become length-matched filler. A phrase vocabulary of 3 or
  more words (for example `Type 2 diabetes`) is caught too; `--include-values` restores it.
- Datetime: draws clamp to whole months around the K-th extremes instead of the exact ends.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| Numeric column with under 2K finite cells | one coarse interval (`_coarse_range`), `mean`/`std` null under K, as for a flagged column |
| Only inf cells | left alone, as today (`_coarse_range` returns early) |
| `a == b` (K-th smallest equals K-th largest) | step from `_grid_edges`; domain strictly around the value |
| Grid not writable near float max | `_FALLBACK_DOMAIN`, as today |
| Every categorical label under K | column withheld, listed in `redacted_columns`; generate refuses with `plan.statistical_snapshot_values_redacted` and the fix hint |
| `condition_on` with a folded parent label | the child draws from its marginal (existing fallback, counted) |
| Joint at a raised `contingency_top_k` | cells under K fold; `snapshot_joint_warnings` reports them as `policy_dropped` (existing field) |
| `quantile_grid` decoder bound check | grid points lie at or inside the K-th extremes, so inside the new edges; AT-9 proves it |
| Old v1 snapshot | read as today |
| A forged `flagged-redacted/v3` | refused as an unknown policy (existing test, new spelling) |
| Object column with mixed types | the free-text test reads `str(value)`, as the snapshot does |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged column and joint of a plain snapshot; the G5 refusal text | `SNAPSHOT_FLOOR_STATS` in the one registry, applied in `distribution_snapshot_document`; the refusal names columns only | AT-1 to AT-5, AT-8 canary and property tests | drop `FOLD_UNDER_K` from the table |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory frame; nothing opened, staged or leased | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state or cache is added | n/a | n/a |
| 4 | Route parity and silent fallback | `decoy fit`, the engine API, `ui/summary.py` (counts only) | all three call `distribution_snapshot_document`; the CLI sentry refuses the raw writer | AT-C1 and the existing `test_fit_value_redaction.py` | call `compute_distribution_snapshot` from `cli/gen/_fit.py` |
| 5 | Referential integrity | `condition_on` with a folded parent label | existing marginal fallback | AT-9 round trip with a conditional column | drop the fallback for a missing parent |
| 6 | Untrusted producer | a hand-edited snapshot marker | the reader accepts exactly v1 and v2 and refuses any other value | AT-7 | accept any `flagged-redacted/*` prefix |
| 7 | Check then use (TOCTOU) | none | N/A: no new file read; the frame is read once by the caller | n/a | n/a |
| 8 | Weak tests | a floor test that passes on a frame with no rare cell | each canary test asserts the canary is in the raw snapshot first | AT-1 to AT-5 non-vacuity line | build the AT-2 frame without the rare row |
| 9 | Refactor drift | `include_values=True`, flagged columns | those paths do not change | AT-10, existing flagged tests | apply the floor when `include_values=True` |
| 10 | Frozen contract drift | `distribution_snapshot_document` output, `value_policy`, generated output 3.3 | `Breaking:` line, compat note, v1 still read | AT-7, section 9 | drop v1 from the accepted set |

### 6.2 Enumerations

- Exit paths: none added. The G5 refusal reuses `plan.statistical_snapshot_values_redacted`
  (CLI exit 1).
- Routes that write a plain snapshot: `decoy fit` (`cli/gen/_fit.py:164`), the engine API
  `distribution_snapshot_document`, CLI `ui/summary.py:370-371` (reads null counts only, so the
  floor does not change its result). `fit_dp_snapshot` is a separate DP route and is untouched.
- FK shapes: none. `fanout` degree counts are out of scope (section 2).
- Fields: snapshot kinds `numeric`, `categorical`, `datetime`, `freetext`, `empty` and the joint;
  the keys each rule touches are in 4.1. No key is added.
- Output surfaces: the snapshot file, `fit --json` (`value_policy`, `redacted_columns`), the
  `fit` stderr list of withheld names, generated rows.

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Floor constant | `MIN_RELEASE_COUNT` | no |
| Tiny-column fallback | `_coarse_range`, `_coarse_domain`, `_grid_edges` | no |
| Clamped histogram | `numeric_stats(domain=...)` | no |
| Fold into `other_count` | `_collapse_counted_items` | gains a `keep` predicate |
| Free-text statistics | `_freetext_stats` | no; reached through the new keyword |
| Year edges for small date columns | `_year_edge` | no |
| Rule enum, registry, applier | `Rule`, `snapshot_rules`, `_apply` | one new table, six new members |
| Refusal | `plan.statistical_snapshot_values_redacted`, `redacted_fix_hint` | message wording |

## 7. Acceptance tests, red first

Engine (E1), in `tests/unit/profiling/test_snapshot_floor.py` (new) unless named. The fixture is
the QA frame rebuilt in the test (1,000 rows, seed 31), plus small frames.

| # | Test | Fail before |
|---|---|---|
| AT-1 | unflagged salary with one 987,654 row: no value in `min`, `max`, `bin_edges`, `quantiles` equals any of the K-1 largest or K-1 smallest cells; each end bin holds at least K | `max == 987654` |
| AT-2 | the document's JSON text does not contain `RARE-HIV-B20`; `other_count` grew by 1; every kept label count is at least K | label stored with count 1 |
| AT-3 | joint of two unflagged columns: every kept cell count is at least K; folded mass is in `other_count` | count-1 cell stored |
| AT-4 | the 30-string note column is `kind: freetext`; no note string is in the JSON | categorical, all 30 stored |
| AT-5 | datetime: `min` and `max` are month edges; neither equals a source timestamp | exact first and last timestamp |
| AT-6 | 15-row frame: a categorical column with every label under K is listed in `redacted_columns`, and `load_spec` refuses it with `plan.statistical_snapshot_values_redacted` | labels stored, spec loads |
| AT-7 | `value_policy == "flagged-redacted/v2"`; `load_spec` accepts v1 and v2 and refuses v3 (`tests/unit/generation/test_statistical_redacted.py`) | marker is v1; v2 refused |
| AT-8 | property (hypothesis, as `test_snapshot_values.py` already uses): for random numeric, string and bool frames, G1 to G3 hold for every unflagged column | fails on the first count-1 label or exact extreme |
| AT-9 | round trip: fit the QA frame, generate 5,000 rows; the numeric shape decodes, no generated label is a folded label, and the per-column marginal similarity from `quality.fidelity` is at least 0.95 for `salary`, `state` and `visit_date` | not fail-before: the fidelity budget |
| AT-10 | guards that stay green: a bool column keeps a count-1 `False`; 2-word labels (`New York`) stay categorical; `include_values=True` equals the raw snapshot plus the two keys (existing `test_include_values_is_the_raw_snapshot_plus_the_two_keys`) | not fail-before: they pin what must not change |
| AT-11 | sentry (`tests/sentry/profiling/test_snapshot_value_registry.py`): every raw key is classified across both tables; `other_count` still has one writer; no direct `stats[...] =` in `_snapshot_values.py` | new rule keys unclassified |

Mutations that must turn a test red: drop `FOLD_UNDER_K` from the table (AT-2, AT-3, AT-8,
AT-11); take `a` and `b` as the min and max (AT-1, AT-8); skip the free-text pass (AT-4); keep
v1 (AT-7); fold bool columns (AT-10).

CLI (C1), after the engine release that carries E1:

| # | Test | Fail before |
|---|---|---|
| AT-C1 | `decoy fit` on the QA frame: no canary (`RARE-HIV-B20`, `987654`, any note string) in the file; `fit --json` shows `value_policy: flagged-redacted/v2` (`tests/e2e/first_user/test_items_privacy.py`) | canaries present on the old pin |
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
change wherever they build through the document. Small fixture frames whose labels are under K
grow their rows to keep the old intent. No assertion is weakened to pass.

CLI: `tests/e2e/first_user/test_items_privacy.py`, `test_items_fit_joint_cap.py`
(`test_at9_raised_cap_keeps_every_cell_and_warns_nothing` keeps every cell only if each cell is
held by K rows), `test_items_generate.py`, `test_items_generate_init.py` and
`tests/e2e/test_fit_command.py`. Tiny CSV fixtures that sample categories grow, as above.

## 8. Placement

No new production file. One new test file beside the owning package.

| Change | File | Note |
|---|---|---|
| new `Rule` members, `SNAPSHOT_FLOOR_STATS`, `DATA_RULES`, `POLICY_REDACTED` v2, the accepted-policy set | `src/decoy_engine/profiling/_value_redaction.py` (475 lines, about +40) | the one registry |
| `_floor_column`, the four data rules, the free-text test, the `keep` predicate on `_collapse_counted_items` | `src/decoy_engine/profiling/_snapshot_values.py` (274 lines, about +130) | stays in the file the sentries scan; a new module would escape them |
| `freetext_columns` keyword in `compute_distribution_snapshot` and `_stats_for` | `src/decoy_engine/quality/snapshot.py` (600 lines, about +15) | present consumer: `distribution_snapshot_document` |
| accept v1 and v2; refusal wording | `src/decoy_engine/generation/statistical/_spec.py` (about +5) | |
| docs | `docs/strategies.md` (what a plain snapshot keeps), `docs/compatibility-contract.md` dated note | |
| fragment | `changelog.d/fit-unflagged-values.md` with a `Breaking:` line | |
| tests | AT-1 to AT-11 in `tests/unit/profiling/test_snapshot_floor.py` (new, beside `test_snapshot_values.py`), plus 7b | |
| CLI code text | `src/decoy/cli/fit.py` docstring, lines 12 to 18 ("Unflagged categorical `top_values` still carry real source values") | C1 rides the CLI repin PR |
| CLI docs | `docs/guides/shape-and-privacy/03-fit-and-generate.md` lines 82 to 110 (an unflagged column "still holds its real values", "including a rare category and its exact largest and smallest number") and the kinds table at lines 70 to 76; `06-troubleshooting.md` entry for the G5 refusal; `decoy explain security` text if it repeats the old rule; `docs/ROADMAP.md` row 24f, `docs/RECENTLY-SHIPPED.md`, `CHANGELOG.md` | |

Expected size: E1 about 200 source lines in 4 production files plus 2 docs and a fragment, about
400 test lines; one new public name (the `freetext_columns` keyword). C1 about 60 lines of text
in 4 files, plus tests.

## 9. Frozen contracts touched

- `distribution_snapshot_document` (frozen surface, `docs/frozen-surfaces.md:77`): the signature
  does not change; plain snapshot output does. Pre-GA break with a `Breaking:` line: "A plain
  `decoy fit` snapshot now keeps no label or joint cell held by fewer than 10 rows and no exact
  numeric or date extreme, and it writes short sentence columns as free text. Use
  `--include-values` for the old content. `value_policy` is now `flagged-redacted/v2`."
- `compute_distribution_snapshot`: a new keyword whose default keeps output byte-identical.
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
  `test_the_profile_redactor_uses_the_same_selection_stamp_and_applier` stays green.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E1 | 4.1 to 4.4, docs, compat note, fragment | R2 | 4 production files, about 200 source and 400 test lines | none | AT-1 to AT-11, the 7b engine list, `tests/unit/profiling/`, `tests/unit/generation/statistical/`, `tests/unit/quality/`, `tests/sentry/profiling/` |
| C1 | CLI docstring, guide, troubleshooting, explain text, e2e fixtures, AT-C1, AT-C2, roadmap row | R1 | 4 production and doc files, about 60 lines plus tests | E1 released and pinned (repin checklist) | AT-C1, AT-C2, the 7b CLI list |

E1 changes pinned tests and a serialized contract (an escalation trigger), so its merge head gets
the full engine suite against the saved main baseline. Tests run on the Mac first, then
`~/bin/vm-run`, never on the devbox.

## 11. Stop lines for builders

1. No second `Rule` enum, applier or `other_count` writer; extend the existing ones.
2. Do not change flagged-column handling, `VALUE_FIELDS`, or the `include_values=True` bytes.
3. Do not change `MIN_RELEASE_COUNT` or add a second floor constant without the owner (Q1).
4. A red test outside 7b is a stop. Growing a fixture is allowed; weakening an assertion is not.
5. No new reason code. If the G5 refusal cannot reuse the existing one, stop and report.

## 12. Owner questions

- Q1. Label floor K. Recommended: reuse `MIN_RELEASE_COUNT = 10` for labels, cells and bounds
  (one floor, SDC and CMS precedent). Alternative: 3 for labels only. That keeps more categories
  on small files but still releases labels held by 3 to 9 rows.
- Q2. Free-text test. Recommended: the median distinct label has 3 or more words. It catches the
  QA note column, and it also turns phrase vocabularies like `Type 2 diabetes` into filler text.
- Q3. Scan and profile documents keep unflagged `top_values`, `min_value` and `max_value`
  (`profile_document`, used by `decoy demo` and the `decoy.scan()` API). `decoy scan --output`
  writes the value-free core, so the CLI scan file is safe. Recommended: a separate follow-up
  row, outside 24f.

## 13. Pre-mortem

- Small CSVs in tests and examples lose their categories (G5). Mitigation: the refusal names the
  fix; fixtures grow; the guide states the floor.
- Users read a missing rare label as a bug. Mitigation: guide text and the existing
  `other_count`.
- A future raw key escapes the floor. Mitigation: the registry sentry fails on an unclassified
  key.
