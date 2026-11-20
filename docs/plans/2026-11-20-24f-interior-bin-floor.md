Status: plan

# 24f interior bin floor: no plain-fit numeric bin holds 1 to 9 rows, and `numeric_bins` has a ceiling (roadmap row 24f, amendment)

Owner: Cam. Author: Opus plan agent. Date of decision: 2026-11-20. Revision 1.

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established
solutions), `reuse-first.md`, `proportionality.md`, `cross-cutting-concerns.md`,
`api-and-compatibility.md`, `testing.md` (test depth and full-suite triggers); commit rule from
`workspace-and-vcs.md` as restated in the global instructions. Engine: `CODEMAP.md` "Where
Things Go", `tests/sentry/test_module_size.py`, `tests/sentry/layout/test_package_fanout.py`,
`docs/compatibility-contract.md` (the `distribution-snapshot/v2` paragraph),
`changelog.d/README.md`. The parent plan `docs/plans/2026-11-16-fit-unflagged-values.md` on
`plan/fit-unflagged-values` (revision 4), sections 2, 4.2, 7 and 11.

Bases (2026-11-20): engine `origin/main` `017b168be` (release 0.28.1 plus later merges), CLI
`origin/main` `c87ab295`. Line numbers are read at these bases.

Risk: E2 is R2 (value-leak class; changes the bytes of plain snapshots; adds a refusal to a frozen
surface). C2 is R1 (CLI option text, forwarding, tests, docs). Plan review: Dennis, then Codex.
Code gate: E2 Dennis and Codex; C2 Codex.

## 1. Frame

### 1.1 Evidence

Dennis HIGH-1 on CLI PR #340 (2026-11-20). PR #340 let a plain (non-DP) `decoy fit
--numeric-bins N` forward N to `distribution_snapshot_document` with no upper bound. Probe on
engine 0.28.1: 501 rows, with an unflagged `salary` column of 181 distinct values plus one outlier.

- `--numeric-bins 100000` wrote 173,000 bins of width 1.0. 23 bins held exactly one row. For
  example, bin `[112000, 112001)` holds one row, and that row's value is 112000.0. The document
  was still labelled `value_policy: flagged-redacted/v2`.
- `--numeric-bins` near 1e8 allocates a histogram of that size before anything is written (out of
  memory).

The CLI half is being reverted on PR #340: plain mode refuses `--numeric-bins` again (exit 2)
until this engine fix ships.

### 1.2 Root cause

The parent plan (revision 4, section 4.2, rule `TOP_CODED_RANGE`) floors only the two end bins.
Top and bottom coding at the K-th smallest and K-th largest cell puts at least K rows in each end
bin (`_top_coded_stats`, `src/decoy_engine/profiling/_snapshot_values.py:323-355`). Interior bins
are plain counts on the grid. The parent plan listed "interior histogram bins with a small count"
as a non-goal, because it read them as "a count on a public grid, not a value". That reading
holds only while bins are wide. The grid step is the largest nice step at or below
`(b - a) / numeric_bins`, and `m = max(numeric_bins, ceil((b - lo) / step))` (`:340-345`). The
user picks `numeric_bins`, so the user picks the bin width. At width 1.0 on integer data, a
count-1 bin names one row's exact value. The flaw exists at the default of 10 bins too: a narrow
or skewed column can have an interior bin of 1 to 9 rows, which breaks the threshold rule that the
rest of the floor follows. A large N makes it worse.

The memory fault has a separate cause: nothing bounds `numeric_bins` from above.
`compute_distribution_snapshot` (`src/decoy_engine/quality/snapshot.py:137`) passes it to
`numeric_stats` (`:287`) and `freetext_stats` (`:296`) for every column before the floor runs.
`fit_dp_snapshot` checks only `numeric_bins >= 2` (`src/decoy_engine/quality/dp.py:181`).

## 2. Guarantee

For a document written by `distribution_snapshot_document(..., include_values=False)`:

- G9. A numeric column released with two or more bins has every `bin_counts` entry at least
  `MIN_RELEASE_COUNT` (K = 10). This covers end and interior bins for any accepted
  `numeric_bins`. No bin holds 1 to K-1 rows, and no bin is empty. A column released as one bin
  (flagged, G5, or a merge that leaves one bin) holds all its finite cells. That count is the
  column's finite-cell count, which the document already publishes.
- G10. Every released `bin_edges` entry is an edge of the pre-merge grid (the Heckbert grid of
  `_top_coded_stats`, or the public `_FALLBACK_DOMAIN` grid). The merge does not change the first
  and last edges. So `quantile_grid` and `exact_values` stay inside `[bin_edges[0],
  bin_edges[-1]]`, and parent G2 (bounds unchanged under a tail swap) still holds.
- G11. `numeric_bins` must be an `int`, not `bool`, from 1 to `MAX_NUMERIC_BINS` (1000). Any other
  value is refused before any histogram is computed, with the new registered reason
  `quality.numeric_bins_invalid` (`DistributionSnapshotError`). The message names the parameter,
  the allowed range and the type it received. It never holds a cell value or the rejected number.
  The check sits in `compute_distribution_snapshot`, so `include_values=True` and in-memory
  callers are bounded too. `fit_dp_snapshot` refuses `numeric_bins > MAX_NUMERIC_BINS` with its
  existing `dp_numeric_bins_invalid`.
- G12. With G9 and G11 in force, plain `decoy fit --numeric-bins N` is safe for every accepted N.
  The CLI forwards N in plain mode and checks it before it reads the source.

Unchanged: `include_values=True` output for any N up to the ceiling (parent G6); DP histograms
(noised, and the carrier check needs exactly `numeric_bins` bins); datetime ranges (already
folded, parent G3); `quantile_grid` and `exact_values` (already K-floored); `mean` and `std`.

Non-goals (recorded follow-ups, not blockers):

- Freetext `length_bin_counts`. A length is not a cell value, and the parent plan excludes length
  statistics. G11 bounds their memory. V2-LOG item: "freetext length bins under K".
- Choosing the merge partner to lose the least information (the OptimalBinningWoE approach). The
  greedy left-to-right fold is the one the year ranges already use (section 3).
- A user-visible note when bins merge. The help text and the guide state the rule.
- Scan and profile documents (row 24zm).

## 3. Established solutions

Search run (2026-11-20): the SDC handbook (Hundepool et al., 2012, and the 2025 second edition)
on frequency tables; the tau-ARGUS manual "Producing safe tables"; sdcMicro `globalRecode`; ARX
interval generalization hierarchies; Mondrian (LeFevre, DeWitt, Ramakrishnan, ICDE 2006);
OptBinning (Navas-Palencia, arXiv 2001.08025) and R OptimalBinningWoE minimum-bin-size merging;
the CBS SDC FAQ on threshold semantics. In the codebase: `fold_ranges_under_k` and
`release_ranges_at_k` (`_snapshot_values.py:178-251`), `check_contingency_top_k`
(`quality/snapshot.py:127`) and `_FALLBACK_DOMAIN`.

| Source | What it does | Used here |
|---|---|---|
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), chapter 5 (frequency tables): threshold rule and table redesign | A cell under the threshold is unsafe. Table redesign collapses adjacent categories until no cell is unsafe | The rule (G9) and the method: merge adjacent bins |
| tau-ARGUS manual, "Producing safe tables" | The user combines categories (global recoding) until the unsafe cells are gone, then suppresses what is left | Recode first. A one-way histogram has no secondary suppression problem: no margin can recompute a part of a merged bin |
| sdcMicro `globalRecode`; ARX interval hierarchies | Recode a numeric variable into intervals on fixed breaks; coarsen by merging neighbours | Breaks stay on the public nice grid and are only removed, never moved (G10) |
| CBS SDC FAQ | A cell at the threshold minus one is unsafe; the comparison is stated exactly | `count >= K` is safe, the same comparison as `_held_by_k` and the year fold. K = 10 is the owner-set floor |
| OptBinning; OptimalBinningWoE | Minimum records per bin, met by merging a small bin with a neighbour | Confirms adjacent merge as the standard repair. We do not use their information-value partner choice (non-goal) |
| Mondrian in one dimension (median splits while each part keeps k) | k-anonymous partition with cut points taken from the data | Rejected: a median cut can equal a real cell. Our edges must stay on the public grid |

Reuse: the merge is the existing `fold_ranges_under_k`, applied to `(i, i, count)` index ranges.
It merges adjacent ranges in order until each holds K, and joins a short last range to the one
before it. Year ranges and numeric bins then follow one rule, with no new merge code.

Ceiling: the codebase pattern is `MAX_CONTINGENCY_TOP_K = 1000` with `check_contingency_top_k`, a
fixed cap checked first in `compute_distribution_snapshot`. A cap derived from rows/K was
considered. It cannot bound memory before the data is read, and on a large file it still allows
millions of bins. After the merge a plain document has at most `floor(n / K)` bins anyway, so a
rows/K refusal adds nothing (Q1).

## 4. Design

Design notes: no new structure and no new module. One step joins the numeric branch of
`_floor_column`, and one bounds check joins the existing parameter checks. One fact in one place:
`MAX_NUMERIC_BINS` lives in `quality/snapshot.py` and `dp.py` and the CLI import it; K stays
`MIN_RELEASE_COUNT`.

Choke points. The ceiling: every non-DP writer goes through `compute_distribution_snapshot`
(`distribution_snapshot_document` calls it before it profiles or floors), so its first line is
the one check. Guard: AT-22 spies on `numeric_stats` and `profile_columns` and fails if either
runs for a refused value. Mutation that must turn it red: move the check below the column loop.
The DP route is the one other site and reads the same constant (AT-23). The floor: the merge
runs in `_floor_column`, the only place an unflagged numeric histogram is written into a plain
document. Guard: the AT-24 property test over every plain `bin_counts`. Mutation: delete the call.

### 4.1 Interior floor (E2, `profiling/_snapshot_values.py`)

New private `_merge_bins_under_k(stats)`:

1. Read `bin_edges` (`m + 1` entries) and `bin_counts` (`m` entries).
2. `folded = fold_ranges_under_k([(i, i, c) for i, c in enumerate(counts)])`.
3. Write `bin_edges = [edges[first] for first, _, _ in folded] + [edges[-1]]` and
   `bin_counts = [count for _, _, count in folded]`.

`_floor_column` calls it right after it copies the `TOP_CODED_RANGE` keys from
`_top_coded_stats` (`:416-418`). This covers both the grid path and the `_FALLBACK_DOMAIN` path.
Parent G5 means the column has at least 2K finite cells here, so the fold always gives at least
one range of K or more. A zero-count bin joins the group after it, or the last group, so no empty
bin is released.

Why G2 still holds: for `a < b`, the pre-merge counts do not change under the parent's tail swap.
The K-1 smallest cells stay in bin 0, the K-1 largest stay in the last bin, and interior counts
depend only on cells in `[a, b]`. The fold reads only those counts. For `a == b`, or a span below
the grid floor, the parent's documented exception stands: interior counts can move under a swap.
The merge does not widen that exception, and G9 still holds.

`_top_coded_stats` and its `_writable` check do not change. The check proves the pre-merge grid
has at least `numeric_bins` strict, finite edges. The merge only removes interior edges, so the
released edges stay strictly increasing and finite.

The parent plan's promise "at least `numeric_bins` bins" (parent 4.2, AT-1, AT-C1;
`docs/strategies.md:1705`) is withdrawn. `numeric_bins` becomes the requested grid resolution. The
released count is at most the pre-merge grid size and at most `floor(n / K)`.

### 4.2 Ceiling (E2: `quality/snapshot.py`, `quality/dp.py`, reasons)

- `quality/snapshot.py`: `MAX_NUMERIC_BINS = 1000` beside `MAX_CONTINGENCY_TOP_K`, and
  `check_numeric_bins(value)` beside `check_contingency_top_k`, in the same form: accept when
  `type(value) is int and 1 <= value <= MAX_NUMERIC_BINS`, else raise
  `DistributionSnapshotError(code=reasons.quality.NUMERIC_BINS_INVALID, message="numeric_bins must
  be an int from 1 to 1000 (got type <name>).")`. `compute_distribution_snapshot` calls it on its
  first line, before `check_contingency_top_k`. Export `MAX_NUMERIC_BINS` and `check_numeric_bins`
  through `decoy_engine.quality` (the lazy map in `quality/__init__.py`, as for
  `MAX_CONTINGENCY_TOP_K`), so the CLI can check before it reads a file.
- `reasons/quality/_part1.py`: `NUMERIC_BINS_INVALID = _d("numeric_bins_invalid", "Numeric bins
  invalid.", since=UNRELEASED)` in the `DistributionSnapshotError` group.
- `quality/dp.py` `_validate_fit_params`: the existing condition gains `or numeric_bins >
  MAX_NUMERIC_BINS`. The message becomes "numeric_bins must be an int from 2 to 1000". The code
  stays `dp_numeric_bins_invalid`.

Lower bound: 0 and negative values raise a bare numpy `ValueError` today. They now get the
registered refusal. `numeric_bins=1` stays valid in plain mode, as today.

### 4.3 CLI (C2, `src/decoy/cli/fit.py`)

- Remove `--numeric-bins` from the DP-only list (`:465-466`). `--delta`, the carrier flags and
  `--dp-allow-omit` stay there.
- When the option is given, call the engine's `check_numeric_bins` before the source is read. A
  `DistributionSnapshotError` exits 2 (`EXIT_USAGE`) through `_emit_error` with the engine code, as
  the existing handler at `:559-564` does. In DP mode, `fit_dp_snapshot` also keeps its own check.
- Plain mode passes `numeric_bins` to `distribution_snapshot_document`. DP mode keeps passing it
  to `fit_dp_snapshot`.
- Help text: "Requested histogram bins per numeric column, 1 to 1000 (engine default 10). In a
  plain fit, adjacent bins merge until each holds at least 10 rows." The fit guide and the
  troubleshooting page say the same.

## 5. Behaviour

| Case | Today (0.28.1 with the PR #340 CLI) | After E2 and C2 |
|---|---|---|
| Probe, `--numeric-bins 100000` | 173,000 bins, 23 with one row; `[112000, 112001)` names a value | exit 2, `quality.numeric_bins_invalid`, before the CSV is read |
| Probe, `--numeric-bins 1000` | about 2,500 narrow bins, many with 1 to 3 rows | every released bin holds 10 or more rows; at most 50 bins (501 / 10) |
| Probe, default 10 | ten bins; an interior bin can hold fewer than 10 | an interior bin under 10 merges into the next |
| `--numeric-bins 100000000` | histogram allocation, out of memory | exit 2 before any allocation |
| `--numeric-bins 0` or `-3` | passed through; numpy `ValueError` | exit 2, registered code |
| `include_values=True`, N up to 1000 | raw | raw, byte-identical |
| `include_values=True`, N over 1000 | allocates | refused, registered code |
| DP fit, N over 1000 | allocates N-1 edges per column | refused, `dp_numeric_bins_invalid` |
| Flagged or G5 numeric | one coarse bin | unchanged |
| 100 or more finite cells | sampler draws from `quantile_grid` | draws unchanged; only the released histogram is coarser |

### 5.1 Fidelity cost

- Generation: the sampler reads the histogram only when a column has no `quantile_grid` or
  `exact_values`, which means under 100 finite cells (`MIN_GRID_ROWS`,
  `generation/statistical/_numeric_shape.py:52`). Those columns now draw from bins of at least 10
  rows: 2 to 9 bins for 20 to 99 cells. Draws stay inside the same outer edges.
- Scorers: `ks_complement_binned` (`quality/_distribution_gof.py:108`) evaluates the union of both
  edge lists, so uneven bins compare correctly. The `shape_fidelity` numeric method (sorted
  `bin_counts` TVD) gets a coarser source vector when a caller scores against a plain document.
  The E2 builder lists every caller that passes a plain `distribution_snapshot_document` into a
  scorer. If there is one, the parent's AT-9 must stay green on it. If there is none, the PR says
  "no scorer reads a plain document's histogram".
- Docs: `docs/distribution-integrity/snapshot-and-fidelity.md:65` says "equal-width over min to
  max". Plain v2 bins become "grid edges, with adjacent bins merged to hold 10 rows". Raw and DP
  stay equal-width.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| All interior bins empty, mass only in the end bins | the fold gives two bins or one; every count is K or more |
| `a == b` (constant core) | all mass may sit in one interior bin; the empties around it fold in, usually to one bin |
| Float-max fallback (`_FALLBACK_DOMAIN`) | all cells clamp to one end bin; the fold gives one bin `[-1.5, 1.5]` holding n |
| Short last group (under K) | joins the group before it (`fold_ranges_under_k` tail rule) |
| A bin of exactly K rows | stays its own bin (`>=`, as `_held_by_k`) |
| `numeric_bins` is `True`, `10.0`, `"10"`, `None`, 0, negative or 1001 | `quality.numeric_bins_invalid` before any histogram; no value in the message |
| `numeric_bins == 1000` | accepted |
| Narrow span widens the pre-merge grid past N | at most about 2.5 N + 1 = 2,501 bins in memory, then folded |
| Hand-written v2 snapshot with uneven edges | already accepted by every reader (`_window_admission.py:108-125`, `_degenerate.py:52-64`, `_sample.py:420-428`) |
| An old 0.28.x plain v2 file with small interior bins | still reads and generates; it lacks the floor (Q2) |
| DP carrier check | unchanged: DP histograms are never merged, and `plan/_checks_dp_carrier.py:198` still sees exactly `numeric_bins` bins |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged numeric histogram of a plain document | the one merge in `_floor_column`, after the one top-coding step | AT-20, AT-21, AT-24 | delete the `_merge_bins_under_k` call |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory frame; the refusal raises before anything is opened or allocated | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state or cache is added | n/a | n/a |
| 4 | Route parity | CLI plain and DP routes; the engine API | the CLI calls the engine check and keeps no copy of the limit | AT-C4, AT-C5 | hard-code 1000 in the CLI |
| 5 | Referential integrity | none | N/A: the merge reads one column's counts; no key relationship or joint is touched | n/a | n/a |
| 6 | Untrusted producer (user-chosen N; unbounded resource) | `numeric_bins` on the raw, plain, include-values and DP writers | `check_numeric_bins` as the first line of `compute_distribution_snapshot`; the DP condition reads the same constant; registered refusal with no value in the message | AT-22, AT-23 | move the check below the column loop; put the value in the message |
| 7 | Check then use (TOCTOU) | none | N/A: no new file read; the CLI check reads only the option value | n/a | n/a |
| 8 | Weak tests | a floor test on a frame with no small interior bin | each canary test first asserts that the raw (`include_values=True`) document has a bin of 1 to 9 rows | AT-20, AT-21 non-vacuity lines | build the probe without the spread values |
| 9 | Refactor drift | `include_values=True`, DP | those paths are not merged; AT-25 pins their bytes | AT-25 | call the merge from `numeric_stats` |
| 10 | Frozen contract drift | plain snapshot bytes; the new refusal on `compute_distribution_snapshot` | `Breaking:` line and compat note (section 9) | AT-25, the compat corpus | none beyond AT-25 |

### 6.2 Enumerations

#### Exit paths

- New: `quality.numeric_bins_invalid` (`DistributionSnapshotError`), raised first in
  `compute_distribution_snapshot` (`src/decoy_engine/quality/snapshot.py:137`). The CLI maps it
  to exit 2 through the existing handler (CLI `src/decoy/cli/fit.py:559-564`).
- Changed: `dp_numeric_bins_invalid` (`src/decoy_engine/quality/dp.py:181-185`) also covers
  values over 1000.
- No other exit path changes. G5 keeps its existing refusal.

#### Routes

- `decoy fit` plain mode (CLI `src/decoy/cli/fit.py`), calling `distribution_snapshot_document`
  (`src/decoy_engine/profiling/_snapshot_values.py:543`).
- `decoy fit --epsilon` (DP), calling `fit_dp_snapshot` (CLI `src/decoy/cli/fit.py:640-641`).
- The engine API `distribution_snapshot_document` and `compute_distribution_snapshot`.

#### FK shapes

- N/A: the merge reads one numeric column and never a key relationship.
- `fanout` degree counts are counts, not values, and are out of scope (parent plan section 2).

#### Fields

- Numeric `bin_edges` of a plain document: fewer, uneven grid edges
  (`src/decoy_engine/profiling/_snapshot_values.py:416-418` writes them).
- Numeric `bin_counts` of a plain document: each at least K. No key is added or removed.

#### Output surfaces

- The snapshot file and `fit --json` (keys unchanged).
- The stderr error line and exit 2 for a refused N.
- Generated rows of numeric columns under 100 finite cells fitted from a new plain snapshot.

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Floor constant | `MIN_RELEASE_COUNT` | no |
| Adjacent merge until K | `fold_ranges_under_k` | no |
| Pre-merge grid and top coding | `_top_coded_stats`, `_writable`, `_FALLBACK_DOMAIN` | no |
| Parameter check pattern | `check_contingency_top_k`, `MAX_CONTINGENCY_TOP_K` | no; the new check copies its form |
| Refusal type | `DistributionSnapshotError`, `DpError` | one new code |
| CLI error exit | the `DistributionSnapshotError` handler in `fit.py` | no |

## 7. Acceptance tests, red first

Engine (E2): a new file, `tests/unit/profiling/test_snapshot_bin_floor.py` (the parent's
`test_snapshot_floor.py` is already 709 lines). The test rebuilds the probe frame: `salary` cycles
over the 181 values `40000 + 400 * j`, `j` in 0..180 (so 112000 is one of them, at `j = 180`), for
500 rows, plus one row of 987654. The test asserts that `salary` is not in `redacted_columns`, so
the column is unflagged.

| # | Test | Fail before |
|---|---|---|
| AT-20 | Probe frame. Non-vacuity: with `include_values=True` and `numeric_bins=1000`, some bin holds 1 to 9 rows. Then, for each N in (1, 10, 17, 100, 999, 1000), the plain document's `salary` `bin_counts` are all `>= 10`; the sum is 501; the edges are finite and strictly increasing; `bin_edges[0]` and `bin_edges[-1]` equal the ends of the pre-merge grid (read through `_top_coded_stats`); every edge is a pre-merge grid edge; no bin of width 1.0 holds one row | at N = 1000 many bins hold one row |
| AT-21 | Interior canary at the default N: 60 cells, 25 near 0, 25 near 100 and 10 spread so that one interior bin holds 3 rows. The raw document has the 3-row interior bin; the plain document has no bin under 10. A bin of exactly 10 rows in a second fixture stays its own bin | the 3-row interior bin is released |
| AT-22 | For `numeric_bins` in (0, -1, 1001, 100_000, 10**8, True, 10.0, "10", None): `distribution_snapshot_document` and `compute_distribution_snapshot` raise `DistributionSnapshotError` with code `quality.numeric_bins_invalid`. Spies on `quality.snapshot.numeric_stats` and on `profile_columns` record no call. The message contains neither `100000` nor `987654`. `numeric_bins=1` and `numeric_bins=1000` are accepted | no refusal; 10**8 allocates |
| AT-23 | `fit_dp_snapshot(numeric_bins=1001)` raises `DpError` with `dp_numeric_bins_invalid`; 1000 passes the validator (validator level, no OpenDP run needed) | 1001 accepted |
| AT-24 | Property (hypothesis, as the parent's AT-8): random finite float and int arrays of 20 to 400 cells and random N from 1 to 1000. In every plain document, each `bin_counts` entry is `>= K` or the column has one bin; counts sum to the finite count; and when `a < b`, the parent's tail swap leaves `min`, `max`, `bin_edges` and `bin_counts` unchanged | first count under K |
| AT-25 | Guards that stay green: `include_values=True` equals the raw snapshot plus two keys for N 10 and 1000; DP output for N 10 is byte-identical to the base; a flagged numeric still has one coarse bin; `quantile_grid` values lie inside the merged outer edges; the probe round trip (fit, then generate 2,000 rows) decodes and generates | not fail-before: they pin what must not change |
| AT-26 | `quality.numeric_bins_invalid` is registered with `since` unreleased, and the existing reason registry sentries pass | code not registered |

Mutations that must turn a test red:

- Delete the merge call (AT-20, AT-21, AT-24).
- Use `>` for `>=` in the fold threshold (AT-21, the exact-10 bin).
- Drop the short-tail join (AT-21, AT-24).
- Run the merge before the `_writable` check (AT-20 edge check).
- Run the merge on the `include_values=True` path (AT-25).
- Move `check_numeric_bins` below the column loop (AT-22 spy).
- Use `<` for `<=` against the maximum (AT-22, 1000 accepted).
- Accept bool (AT-22).
- Drop the DP maximum (AT-23).
- Put the value in the message (AT-22).

### 7b. Existing tests that change (engine)

In `tests/unit/profiling/test_snapshot_floor.py`:

- `test_every_span_writes_at_least_the_requested_bins_on_strict_edges` (`:150`): keep the finite
  and strict edge checks and the sum. Replace `len(bin_counts) >= 17` with "each count >= K, or
  one bin".
- `test_near_float_max_uses_the_fixed_public_domain_with_every_requested_bin` (`:163`): keep the
  `(-1.5, 1.5)` bounds. The counts become `[50]`, because all cells clamp to one end.
- `test_the_end_bins_each_hold_at_least_k_rows_when_the_span_is_not_constant` (`:170`) stays as
  it is. G9 implies it.

Any other test that builds a plain document and asserts `len(bin_counts) == numeric_bins` follows
the same rule, and the builder lists each one in the PR. No assertion is weakened beyond replacing
the withdrawn "at least N bins" promise with G9.

CLI (C2), after the engine release with E2 is pinned on CLI main:

| # | Test | Fail before |
|---|---|---|
| AT-C3 | Probe CSV, plain `decoy fit --numeric-bins 1000`, exits 0. The snapshot's `salary` `bin_counts` are all `>= 10`; no bin of width 1.0 is present; `987654` is not in the file; `value_policy` is `flagged-redacted/v2` (`tests/e2e/first_user/test_items_privacy.py`) | on the reverted CLI: exit 2 (option refused in plain mode) |
| AT-C4 | `decoy fit --numeric-bins 100000` and `--numeric-bins 0` exit 2 with `quality.numeric_bins_invalid`, and a spy shows that the source reader is not called. With `--epsilon` and 100000, the result is the same exit 2 from the same engine check | plain mode exits 2 with `dp_mode_not_selected` instead |
| AT-C5 | Rewritten forwarding tests in `tests/e2e/test_fit_command.py`: plain mode passes 17 to `distribution_snapshot_document`; DP mode passes 17 to `fit_dp_snapshot` | the plain option is refused |

C2 mutations: hard-code the limit in the CLI (AT-C4 patches the engine constant to 5 and expects
`--numeric-bins 6` to be refused); check after the read (AT-C4 spy); forward to DP only (AT-C5).

## 8. Placement

No new production module. `profiling/` and `quality/` each hold 25 direct modules, which is the
fan-out limit (`tests/sentry/layout/test_package_fanout.py:25`), so neither can take a new one.

| Change | File | CODEMAP placement | Neighbour or reason |
|---|---|---|---|
| `_merge_bins_under_k` and its call | `src/decoy_engine/profiling/_snapshot_values.py` | "Detectors, profiling" row | beside `fold_ranges_under_k` and `_top_coded_stats` |
| `MAX_NUMERIC_BINS`, `check_numeric_bins` and the call | `src/decoy_engine/quality/snapshot.py` | the existing quality snapshot owner | beside `MAX_CONTINGENCY_TOP_K` and `check_contingency_top_k` |
| lazy exports | `src/decoy_engine/quality/__init__.py` | existing re-export map | same map as `MAX_CONTINGENCY_TOP_K` |
| DP maximum | `src/decoy_engine/quality/dp.py` | existing DP fit owner | `_validate_fit_params` |
| reason code | `src/decoy_engine/reasons/quality/_part1.py` | existing reason catalog | the `DistributionSnapshotError` group |
| acceptance tests | `tests/unit/profiling/test_snapshot_bin_floor.py` | "Unit tests" row | beside `test_snapshot_floor.py` |
| DP bound test | the existing DP validator test file under `tests/unit/quality/` | "Unit tests" row | beside the existing `dp_numeric_bins_invalid` cases |
| docs and fragment | `docs/strategies.md` (the plain-snapshot section, `:1696-1715`), `docs/distribution-integrity/snapshot-and-fidelity.md:65`, `docs/compatibility-contract.md` (the v2 paragraph), `docs/reasons.md` if the registry generates it, `changelog.d/24f-interior-bin-floor.md` | "Feature and contract docs" and "Changelog fragments" rows | existing owners |
| CLI | `src/decoy/cli/fit.py`, the C2 tests, the fit guide and troubleshooting pages, roadmap row 24f, the shipped log | CLI CODEMAP command and "First-user QA item tests" rows | no new CLI module |

Module size. `_snapshot_values.py` has 589 lines and `quality/snapshot.py` has 595. The goal is
600 (`tests/sentry/test_module_size.py:71`). E2 adds about 14 and 12 lines. The builder keeps each
file at or under 600 by trimming duplicated prose in the same file's module docstring
(`_snapshot_values.py:1-24` gives the SDC citations twice; `quality/snapshot.py:1-60` carries a
long D1a history). If a trim would lose meaning, the builder adds a census entry at the measured
count (at most 620) and says so in the PR. That is V2-LOG, not a stop.

Expected size: E2 is about 30 production lines across 5 files, about 220 test lines and about 40
doc lines. New public names: `MAX_NUMERIC_BINS`, `check_numeric_bins` and
`reasons.quality.NUMERIC_BINS_INVALID`. C2 is 1 production file, about 15 production lines and
about 80 test and doc lines.

## 9. Frozen contracts touched (compatibility contract impact)

- Plain snapshot bytes change (`distribution_snapshot_document`, a frozen surface listed in
  `docs/frozen-surfaces.md:101`). A plain document that had an unflagged numeric bin of 1 to 9
  rows now has fewer, merged bins of uneven width. This includes default-N fits of small or skewed
  columns. Pre-GA, so the fragment carries a `Breaking:` line:
  "Breaking: a plain `decoy fit` snapshot merges adjacent numeric histogram bins until each holds
  10 rows, so `bin_edges` can be uneven and fewer than `numeric_bins`; `numeric_bins` outside 1 to
  1000 is refused with `quality.numeric_bins_invalid` by every snapshot writer, and above 1000 by
  the DP fit."
- `compute_distribution_snapshot`: the signature does not change. It gains a refusal for values
  that crashed before (0 or less) or could exhaust memory (over 1000). Bytes are unchanged for
  valid N.
- Schema and marker stay `distribution-snapshot/v2` and `flagged-redacted/v2` (Q2). Every reader
  already accepts uneven, strictly increasing edges, so no reader changes. The compat-contract v2
  paragraph gains one sentence: "A plain v2 numeric histogram has every bin held by at least 10
  rows; its edges are grid points and need not be evenly spaced."
- Reason codes: one new code, `quality.numeric_bins_invalid`, with `since` unreleased. Release
  prep stamps the version.
- Generated output (contract 3.3): changes only for statistical numeric columns with under 100
  finite cells that are fitted from a new plain snapshot. Old snapshots generate as before.
- DP: bytes are unchanged for N up to 1000.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E2 | 4.1 and 4.2, docs, compat note, fragment | R2 | 5 production files; about 30 source, 220 test and 40 doc lines | none (E1 is merged) | AT-20 to AT-26, the 7b edits, `tests/unit/profiling/`, `tests/unit/quality/`, `tests/unit/generation/statistical/`, `tests/sentry/profiling/`, the reason registry sentries, `tests/sentry/test_module_size.py`, `tests/sentry/layout/` |
| release | engine release with E2, then the CLI repin (engine repin checklist) | R1 | standard | E2 merged | release checks |
| C2 | 4.3, help, guide, troubleshooting, AT-C3 to AT-C5, roadmap row 24f, shipped log | R1 | 1 production file; about 95 lines in all | CLI #340 merged with the revert; the repin above on CLI main | AT-C3 to AT-C5, `tests/e2e/test_fit_command.py`, `tests/e2e/first_user/test_items_privacy.py` |

E2 changes the output of a frozen surface and adds a reason code. Both are full-suite triggers in
`testing.md`, so the E2 merge head gets the full engine suite against the saved main baseline.
Tests run on the Mac first, then through `~/bin/vm-run`, never on the devbox. C2 runs T1 only.

Row 24f stays PARTLY MERGED until C2 merges. Roadmap text for the row (CLI repo): "E2 (interior
bin floor and `numeric_bins` ceiling, plan `E:docs/plans/2026-11-20-24f-interior-bin-floor.md`),
then C2 (plain `--numeric-bins`)."

## 11. Stop lines for builders

1. Reuse `fold_ranges_under_k`. No second fold, no new threshold constant, no change to
   `MIN_RELEASE_COUNT`.
2. Do not merge DP, raw or `include_values=True` histograms.
3. Do not move or add a grid edge. The merge only removes interior edges.
4. No new module in `profiling/` or `quality/`; both are at the fan-out limit.
5. One limit constant, `MAX_NUMERIC_BINS`. The CLI and `dp.py` import it and do not copy it.
6. No message, log or exception text carries a cell value or the rejected `numeric_bins` value.
   Use the type name only, as `check_contingency_top_k` does.
7. A red test outside 7b is a stop. Weakening an assertion beyond the withdrawn "at least N bins"
   promise is a stop.
8. More than 8 production files or 400 changed lines in E2 is a stop.

## 12. Owner questions (recommended option first)

- Q1. Ceiling. (a) Recommended: a fixed `MAX_NUMERIC_BINS = 1000`, the same figure as
  `MAX_CONTINGENCY_TOP_K`, together with the merge. Memory is bounded before any data is read,
  and the released bin count is at most `floor(n / 10)`. (b) Refuse N above rows/10. This needs
  the data first, does not bound memory on large files, and makes the same command pass or fail by
  file size. (c) A higher fixed cap such as 10,000. Generation already gets fine detail from the
  `quantile_grid`, so there is no present consumer for it.
- Q2. Version bump. (a) Recommended: keep `distribution-snapshot/v2` and `flagged-redacted/v2`.
  The shape does not change, every reader already accepts uneven edges, v2 is in no released CLI
  build, and the project is pre-release (no product decision is locked). (b) Move the marker to
  `flagged-redacted/v3` so a reader can tell whether a file has the interior floor. That costs one
  more accepted-policy entry and test changes, for little value before GA.
- Q3. DP ceiling. (a) Recommended: apply the same 1000 maximum to `fit_dp_snapshot` with its
  existing code. It is the same out-of-memory fault on the other route, and the change is one
  condition. (b) Leave DP unbounded and record a follow-up.

## 13. Pre-mortem

- A user asks for 50 bins on a 200-row column and gets about 10. The help text and the guide say
  that bins merge to hold 10 rows. `--include-values` gives the raw histogram.
- A later change adds another histogram key to the plain numeric entry and skips the merge. The
  AT-24 property test reads every `bin_counts`, and the parent's registry sentry fails on an
  unclassified key.
- Someone raises the cap later for a large-data use. That changes one constant, and the refusal
  test reads the constant, so the bounds stay pinned.

## 14. Sources

- [KS Handbook on Statistical Disclosure Control, 2nd ed. (2025)](https://ue.poznan.pl/wp-content/uploads/2025/12/KS-Handbook-on-Statistical-Disclosure-Control.pdf): threshold rule and table redesign for frequency tables.
- [tau-ARGUS manual, Producing safe tables](https://julienjamme.github.io/manual_tau_argus_to_quarto/02_Producing_Safe_tables.html): combine categories (global recoding) before suppression.
- [CBS CASC SDC FAQ](https://research.cbs.nl/casc/FAQ.htm): threshold semantics.
- [Navas-Palencia, Optimal binning: mathematical programming formulation](https://arxiv.org/pdf/2001.08025): minimum records per bin as a binning constraint.
- [OptimalBinningWoE `ob_numerical_mob`](https://www.rdocumentation.org/packages/OptimalBinningWoE/versions/1.0.8/topics/ob_numerical_mob): small bins merged with an adjacent bin.
- Hundepool et al., Statistical Disclosure Control (Wiley 2012), sections 3.4 and chapter 5; R sdcMicro `globalRecode`; ARX interval hierarchies; LeFevre, DeWitt and Ramakrishnan, "Mondrian Multidimensional K-Anonymity" (ICDE 2006).
