Status: plan

# 24f interior bin floor: no plain-fit numeric bin holds 1 to 9 rows, and `numeric_bins` has a ceiling (roadmap row 24f, amendment)

Owner: Cam. Author: Opus plan agent. Date of decision: 2026-11-20. Revision 3, after reviewer
round 2 (NO-GO). The change map is in section 15.

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established
solutions), `reuse-first.md`, `proportionality.md`, `cross-cutting-concerns.md`,
`api-and-compatibility.md`, `testing.md` (test depth and full-suite triggers), `architecture.md`,
`security.md`, `performance.md`, `documentation.md`, `exploration.md`, `scope-discipline.md`,
`verification.md`, `code-review.md`, `feature-dev.md`, `bugfix.md`, and
`catalogs/recurring-defects.md`; commit rule from `workspace-and-vcs.md` as restated in the global
instructions. Engine: `CODEMAP.md` "Where
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
Top and bottom coding at the K-th smallest cell `a` and the K-th largest cell `b` puts at least K
rows in each end bin (`_top_coded_stats`, `src/decoy_engine/profiling/_snapshot_values.py:323-355`).
Interior bins are plain counts on the grid. The grid step is the largest nice step at or below
`(b - a) / numeric_bins` (`:340`), so the user picks the bin width. At width 1.0 on integer data, a
count-1 bin names one row's exact value. The same flaw exists at the default of 10 bins: a narrow
or skewed column can have an interior bin of 1 to 9 rows.

A per-bin repair does not close it. Revision 1 merged adjacent bins greedily until each held K.
Dennis showed that a greedy fold closes a group at the first sub-bin where the running total
reaches K, so every released interior edge says the sub-bin just below it holds at least one row.
With ages 18 to 90, `--numeric-bins 100` and a step of 0.5, an edge at 47.5 proves that someone is
exactly 47. Any edge chosen bin by bin from the counts has this fault. The edges must not depend
on how rows sit inside a released bin.

The memory fault has a separate cause: nothing bounds `numeric_bins` from above.
`compute_distribution_snapshot` (`src/decoy_engine/quality/snapshot.py:137`) passes it to
`numeric_stats` (`:287`) and `freetext_stats` (`:296`) for every column before the floor runs.
`fit_dp_snapshot` checks only `numeric_bins >= 2` (`src/decoy_engine/quality/dp.py:181`).

## 2. Guarantee

For a document written by `distribution_snapshot_document(..., include_values=False)`, every
unflagged numeric column that the floor keeps (at least 2K finite cells, parent G5):

- G9. If `add_numeric_shape` attached an `exact_values` or `quantile_grid` block and that block can
  be released, the accompanying histogram is one bin `[lo, hi]` holding the finite count. Its
  bounds are the one-bin top-coded grid bounds derived only from `a` and `b`. The sampler reads the
  shape block first (`generation/statistical/_sample.py:416-421`), so it does not use that coarse
  histogram for generation. For `exact_values`, `dropped_count` already publishes the total rare
  mass; one bin prevents the histogram from locating that mass in a numeric interval. For
  `quantile_grid`, one bin prevents ranks and cumulative histogram edges from deriving a sub-K
  interval count. If no shape block is released, the histogram uses one width `s` from the
  Heckbert 1, 2, 5 times 10^k ladder. Its edges are `lo + i * s` for `i = 0..m`, with `lo =
  floor(a / s) * s` and `m = max(1, ceil((b - lo) / s))`. Every non-empty bin then holds at least
  `MIN_RELEASE_COUNT` (K = 10) rows. `s` is the finest ladder step, starting from the step
  `numeric_bins` asks for, at which that rule passes and the edges can be written. The float-max
  fallback releases one bin `[-1.5, 1.5]` holding every finite cell and pops a shape block that
  would lie outside those public bounds.
- G2 (parent, now without exceptions). Replacing any of the K-1 smallest cells by another value
  below `a`, or any of the K-1 largest by another value above `b`, changes no `min`, `max`,
  `bin_edges` or `bin_counts`. In the one-bin shape branch, the edges depend only on `a` and `b`
  and the count is the finite count. In the no-shape branch, the widened grid is gone. This holds
  for `a == b` and for spans below the grid floor too (4.1).
- G10. When a shape block is released, `bin_edges[0] <= a` and `bin_edges[-1] >= b`, and its sole
  bin contains every `quantile_grid` point and every `exact_values` value. Each exact value is held
  by K rows, so it lies inside `[a, b]`. The same outer-edge rule holds for a no-shape histogram.
- G11. `numeric_bins` must be an integral number (`numbers.Integral`, so `int` and `np.int64`),
  not `bool`, from 1 to `MAX_NUMERIC_BINS` (1000). Any other value is refused before any histogram
  is computed, with the new registered reason `quality.numeric_bins_invalid`
  (`DistributionSnapshotError`). The message names the parameter, the range (read from
  `MAX_NUMERIC_BINS`) and the type it received. It never holds a cell value or the rejected
  number. The check is the first line of `compute_distribution_snapshot`, so `include_values=True`
  and in-memory callers are bounded too. `fit_dp_snapshot` refuses `numeric_bins >
  MAX_NUMERIC_BINS` with its existing `dp_numeric_bins_invalid`.
- G12. With G9 and G11 in force, plain `decoy fit --numeric-bins N` is safe for every accepted N.
  The CLI forwards N in plain mode and checks it before it reads the source.

Residual disclosure, accepted: in the no-shape branch, the chosen level `s` says that the next
finer ladder step failed. In the worst case the released counts identify the only coarse bin that
could have failed. Minimality inference can then show that each of its finer sub-bins is non-empty
and below a bound derived from the coarse count. For example, 10 rows at 0, 10 at 100, 6 at 45 and
6 at 55 with N = 10 release step 20 and counts `[10, 0, 12, 0, 10]`. The document proves that
`[40, 50)` and `[50, 60)` each hold from 1 to 11 rows. This is the minimality attack described by
Wong, Fu, Wang and Pei, "Minimality Attack in Privacy Preserving Data Publishing" (VLDB 2007).
Owner-recorded decision: "24f residual accepted under V1 threat model, orchestrator 2026-11-20, owner may override." The V1 threat model covers accidental leaks only, and primary threshold
suppression reveals the same class of fact.

Unchanged: `include_values=True` output for any N up to the ceiling (parent G6); DP histograms
(noised, and the carrier check needs exactly `numeric_bins` bins); datetime ranges (parent G3);
the contents and release criteria of `quantile_grid` and `exact_values`; `mean` and `std`; flagged
and G5 numeric columns (one coarse bin). The plain histogram accompanying a released shape block
does change to one bin.

Non-goals (recorded follow-ups, not blockers):

- Freetext `length_bin_counts`. A length is not a cell value, and the parent plan excludes length
  statistics. G11 bounds their memory. V2-LOG item: "freetext length bins under K".
- Folding empty bins into a neighbour. Empty bins stay as zero bins, because a fold would make an
  edge depend on the data again. A count of 0 names no value.
- A user-visible note when the histogram coarsens. The help text and the guide state the rule.
- Reconstruction across several snapshots of the same source with different N (parent non-goal).
- Scan and profile documents (row 24zm).
- V2-LOG: minimality inference from the finest passing level. Mitigation options are a release
  level independent of the data, for example a fixed level from N and `(b - a)` only followed by
  suppression of sub-K bins, or noise.
- Datetime year ranges: greedy fold edges reveal observed years. Remedy: one uniform year step on
  a ladder. This is not in this slice.

## 3. Established solutions

Search run (2026-11-20): the SDC handbook (Hundepool et al., 2012, and the 2025 second edition)
on frequency tables; the tau-ARGUS manual "Producing safe tables"; sdcMicro `globalRecode`; ARX
interval generalization hierarchies and its lattice search; Samarati (2001) minimal
generalization; Mondrian (LeFevre, DeWitt, Ramakrishnan, ICDE 2006); OptBinning (Navas-Palencia,
arXiv 2001.08025) and R OptimalBinningWoE minimum-bin-size merging; the CBS SDC FAQ on threshold
semantics. In the codebase: `_top_coded_stats`, `_nice_steps` and `_writable`
(`_snapshot_values.py:299-355`), `check_contingency_top_k` (`quality/snapshot.py:127`) and
`_FALLBACK_DOMAIN`. The datetime `fold_ranges_under_k` / `release_ranges_at_k` path was inspected
but is not a safe precedent: its greedy, data-chosen edges have the same disclosure fault as the
rejected numeric fold and are recorded as a follow-up.

| Source | What it does | Used here |
|---|---|---|
| sdcMicro `globalRecode` (breaks or a fixed interval width for the whole variable) | Recodes every value of a variable into intervals on one set of breaks | The release is one uniform interval width for the whole column |
| ARX generalization hierarchies; Samarati 2001; Kohlmayer et al., "Flash" (2012) | A variable is generalized to one level of a fixed hierarchy; the search picks the lowest level at which every group holds k | The ladder is the hierarchy; we pick the finest level at which every non-empty bin holds K |
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), chapter 5: threshold rule and table redesign | A cell under the threshold is unsafe; table redesign collapses categories until no cell is unsafe | The rule (G9) |
| tau-ARGUS manual, "Producing safe tables" | Global recoding of the spanning variable first, then suppression | Recoding only; a one-way histogram with uniform bins has no margin that recomputes a part |
| CBS SDC FAQ | The threshold comparison is stated exactly | `count >= K` is the owner-set primary threshold rule. K = 10 |
| Wong, Fu, Wang and Pei, VLDB 2007 | A minimality attack infers unsafe facts from the knowledge that a data-dependent release is minimally generalized | Documents the accepted residual from choosing the finest passing ladder level; mitigation is a V2-LOG follow-up |
| OptBinning; OptimalBinningWoE; greedy adjacent fold (revision 1) | Merge a small bin with a neighbour, bin by bin | Rejected: edges chosen bin by bin show where the rows are (1.2) |
| Mondrian in one dimension | Median cut points while each part keeps k | Rejected: a median cut can equal a real cell |

Reuse: the ladder `_nice_steps`, the anchor `floor(a / step) * step`, the one-bin grid helper
`_grid_edges`, the writability check `_writable` and the clamped `numeric_stats(bins, domain)` all
exist. The change adds the shape-aware one-bin branch and replaces the widening rule and stop
condition of the existing loop in `_top_coded_stats`. Candidate counts use NumPy `searchsorted`
over the already sorted finite array. No new merge code.

Ceiling: the codebase pattern is `MAX_CONTINGENCY_TOP_K = 1000` with `check_contingency_top_k`, a
fixed cap checked first in `compute_distribution_snapshot`. A cap derived from rows/K was
considered. It cannot bound memory before the data is read, and on a large file it still allows
millions of bins (Q1).

## 4. Design

Design notes: no new structure and no new module. The existing ladder loop gets a different stop
condition, and one private parameter check is shared by two public checks. One fact in one
place: `MAX_NUMERIC_BINS` lives in `quality/snapshot.py`, and `dp.py` and the CLI import it; K
stays `MIN_RELEASE_COUNT`.

Choke points. The ceiling: every non-DP writer goes through `compute_distribution_snapshot`
(`distribution_snapshot_document` calls it before it profiles or floors), so its first line is
the one check. Guard: AT-22 spies on `numeric_stats` and `profile_columns` and fails if either
runs for a refused value. Mutation: move the check below the column loop. The DP route is the one
other site and reads the same constant (AT-23). The floor: `_top_coded_stats` is the only writer of
an unflagged numeric histogram in a plain document (called from `_floor_column`, `:416`). Guard:
the AT-24 property test over every plain `bin_counts`, plus AT-28 for the shape/histogram
interaction. Mutations: route a released shape through the multi-bin search; stop a no-shape
search on writability alone.

### 4.1 Shape branch and level search (E2, `profiling/_snapshot_values.py`, `_top_coded_stats`)

Inputs as today: `a` = K-th smallest finite cell, `b` = K-th largest, and the start width
`(b - a) / numeric_bins` when `a < b`, else `_grid_step(a, b)`.

```
ordered = sort(finite)                                 # once per column
a, b = ordered[K - 1], ordered[-K]

if exact_values or quantile_grid is present:
    domain = the finite one-bin grid bounds from _grid_edges(a, b)
    if the domain is writable and contains the shape values:
        return numeric_stats(non_null, bins=1, domain=domain), False
    return numeric_stats(non_null, bins=1, domain=_FALLBACK_DOMAIN), True

for step in islice(_nice_steps(width), _MAX_STEP_TRIES):
    start = floor(a / step) * step                     # Decimal, as today
    bins = max(1, ceil((b - start) / step))            # no max(numeric_bins, ...) widening
    domain = (float(start), float(start + step * bins))
    stop to the fallback if a domain end is not finite
    counts = bin counts from searchsorted(ordered, candidate edges), with tails in the end bins
    if every count is 0 or >= MIN_RELEASE_COUNT:
        stats = numeric_stats(non_null, bins=bins, domain=domain)
        if _writable(stats, bins) and stats["bin_counts"] == counts:
            return stats, False
return numeric_stats(non_null, bins=1, domain=_FALLBACK_DOMAIN), True
```

Changes from 0.28.1, and why:

- A released `exact_values` or `quantile_grid` block forces one histogram bin. The sampler reads
  that shape first, so more histogram detail has no generation benefit. The rule also prevents
  subtracting public exact-value counts or quantile ranks from cumulative edge counts to locate a
  1 to 9 row residual. A shape block that the fixed fallback cannot contain is popped as today.
- The level search runs only when no shape block is released. Its stop test adds "every count is 0
  or at least K". The loop climbs the ladder from the requested resolution until the whole column
  passes. The result is the finest passing level, with the accepted minimality residual in G9.
- The `max(numeric_bins, ...)` widening is removed. It existed to keep the promise "at least
  `numeric_bins` bins", which is withdrawn. Without it, `a` is always in bin 0 and `b` in the last
  bin, at every level and for every span. That makes G2 hold everywhere, including `a == b`.
- The fallback releases one bin over `_FALLBACK_DOMAIN`, not `numeric_bins` bins. Cells in the
  interior of `(-1.5, 1.5)` could otherwise sit in small interior bins next to cells near float
  max. One bin holds all finite cells (at least 2K), so G9 and G2 hold there too. The shape blocks
  are popped as today.

Termination: every count is at least K once the grid has only end bins, because top coding puts
at least K rows in bin 0 and in the last bin. The ladder reaches that level after at most about
`3 * log10(2.5 * numeric_bins) + 3` steps (about 14 for N = 1000). `_MAX_STEP_TRIES` (64) covers
that plus the writability steps at large magnitudes.

Why G2 holds: the K-1 smallest cells lie below `a`, so they fall in `[lo, a)` or clamp to `lo`;
either way they count in bin 0 at every level. The same holds for the K-1 largest and the last
bin. So every level's counts, and with them the chosen level, do not change under the swap. In the
shape branch, `[lo, hi]` depends only on `a` and `b`, and its sole count is the finite count, so the
same tail swap changes nothing.

Memory and time: the first level has at most `(b - a) / s0 + 1` bins with `s0 > width / 2.5`, so
at most about `2.5 * numeric_bins + 1` (2,501 for N = 1000). Later levels have fewer. Each level is
counted with `searchsorted` over the one sorted finite array. `numeric_stats` runs only to
materialize a count-floor candidate and verify the written counts and edges. A column therefore
pays for one sort plus at most about 14 searches over at most 2,501 candidate edges, rather than
about 14 full passes. The builder measures two 1M-row columns at N = 1000: one representative
spread and one centered at `1e15` with a small finite spread. The measurement records warmup,
repeated runs and the slowest observed per-column time. A result over 2 seconds per column is a
stop and a report, not a silent optimization.

The parent plan's promise "at least `numeric_bins` bins" (parent 4.2, AT-1, AT-C1;
`docs/strategies.md:1705`) is withdrawn. `numeric_bins` sets the finest step the search may use.

### 4.2 Ceiling (E2: `quality/snapshot.py`, `quality/dp.py`, reasons)

- `quality/snapshot.py`: `MAX_NUMERIC_BINS = 1000` beside `MAX_CONTINGENCY_TOP_K`. One private
  `_check_int_param(name, value, maximum, code)`: accept when `isinstance(value,
  numbers.Integral) and not isinstance(value, bool) and 1 <= value <= maximum`, else raise
  `DistributionSnapshotError(code=code, message=f"{name} must be an int from 1 to {maximum} (got
  type {type(value).__name__}).")`. `check_contingency_top_k(value)` and the new
  `check_numeric_bins(value)` each become one call to it. `compute_distribution_snapshot` calls
  `check_numeric_bins` on its first line, before `check_contingency_top_k`. Export
  `MAX_NUMERIC_BINS` and `check_numeric_bins` through `decoy_engine.quality` (the lazy map in
  `quality/__init__.py`, as for `MAX_CONTINGENCY_TOP_K`), so the CLI can check before it reads a
  file.
- `check_contingency_top_k` now also accepts `np.int64` and other integral types. Its message text
  is unchanged for every value it refused before, except that a non-bool integral numpy value is
  now accepted. This is a loosening, recorded in the fragment.
- `reasons/quality/_part1.py`: `NUMERIC_BINS_INVALID = _d("numeric_bins_invalid", "Numeric bins
  invalid.", since=UNRELEASED)` in the `DistributionSnapshotError` group, and
  `"NUMERIC_BINS_INVALID"` in `__all__` (sorted position).
- `quality/dp.py` `_validate_fit_params`: the condition gains `or numeric_bins >
  MAX_NUMERIC_BINS`. The message changes from `numeric_bins must be an int >= 2; got {value!r}.`
  to `numeric_bins must be an int from 2 to {MAX_NUMERIC_BINS}; got {value!r}.` The DP message
  keeps its existing `got <repr>` suffix: the value is a request parameter, not a cell. The code
  stays `dp_numeric_bins_invalid`. DP keeps its `int`-only type rule.

Lower bound: 0 and negative values raise a bare numpy `ValueError` today. They now get the
registered refusal. `numeric_bins=1` stays valid in plain mode.

### 4.3 CLI (C2, `src/decoy/cli/fit.py`)

- Remove `--numeric-bins` from the DP-only list (`:465-466`). `--delta`, the carrier flags and
  `--dp-allow-omit` stay there.
- When the option is given, call the engine's `check_numeric_bins` before the source is read, in
  both modes. A `DistributionSnapshotError` exits 2 (`EXIT_USAGE`) through `_emit_error` with the
  engine code, as the existing handler at `:559-564` does.
- Code parity, stated: any N outside 1 to 1000 exits 2 with `quality.numeric_bins_invalid` in
  both modes, before the read. With `--epsilon`, N = 1 passes the shared check and is then refused
  by `fit_dp_snapshot` with `dp_numeric_bins_invalid` (exit 2 through the existing `DpError`
  handler, `:654-656`). That refusal comes after the source is read, as every DP parameter
  refusal does today.
- Plain mode passes `numeric_bins` to `distribution_snapshot_document`. DP mode keeps passing it
  to `fit_dp_snapshot`.
- Help text: "Requested histogram bins per numeric column, 1 to 1000 (engine default 10). A plain
  fit writes one histogram bin when it releases a numeric shape block; otherwise it widens the
  bins until every non-empty bin holds at least 10 rows." The fit guide and troubleshooting page
  say the same.

## 5. Behaviour

| Case | Today (0.28.1 with the PR #340 CLI) | After E2 and C2 |
|---|---|---|
| Probe, `--numeric-bins 100000` | 173,000 bins, 23 with one row; `[112000, 112001)` names a value | exit 2, `quality.numeric_bins_invalid`, before the CSV is read |
| Probe, `--numeric-bins 1000` | about 2,500 narrow bins, many with 1 to 3 rows | one bin if a shape block is released; otherwise one uniform width coarse enough that every non-empty bin holds 10 or more rows |
| Ages 18 to 90, `--numeric-bins 100`, age 47 held by 3 rows | step 0.5; the 47 bin holds 3 | `quantile_grid` is released, so the accompanying histogram has one bin and cannot locate the 3 rows |
| 10 rows at 0 and 100, 6 at 45 and 55, N = 10 | step 10 has two 6-row bins | no shape block; step 20 has `[10, 0, 12, 0, 10]`, with the accepted G9 minimality residual |
| Default 10 bins, one interior bin of 3 rows | released | one bin when a shape block is released; otherwise the whole histogram moves to the next ladder step until it passes |
| `--numeric-bins 100000000` | histogram allocation, out of memory | exit 2 before any allocation |
| `--numeric-bins 0` or `-3` | passed through; numpy `ValueError` | exit 2, registered code |
| `--epsilon 1 --numeric-bins 1` | DP refusal | DP refusal, `dp_numeric_bins_invalid`, exit 2 |
| `include_values=True`, N up to 1000 | raw | raw, byte-identical |
| `include_values=True`, N over 1000 | allocates | refused, registered code |
| DP fit, N over 1000 | allocates N-1 edges per column | refused, `dp_numeric_bins_invalid` |
| Flagged or G5 numeric | one coarse bin | unchanged |
| 100 or more finite cells | sampler draws from `quantile_grid` | draws unchanged; the accompanying released histogram is one bin |

### 5.1 Fidelity cost

- Generation: the sampler calls `decode_numeric_shape` before reading `bin_edges` and `bin_counts`
  (`generation/statistical/_sample.py:416-421`). A column with a released `quantile_grid` or
  `exact_values` therefore keeps the same draws while its accompanying histogram becomes one bin.
  A column with no shape block uses the level-searched histogram. With 20 to 99 finite cells, at
  most 9 non-empty bins can pass. One sparse region can coarsen the whole column, and draws stay
  inside `[lo, hi]`.
- Uniform coarsening is coarser than a per-bin merge. That is the price of edges that show
  nothing about where rows sit (1.2).
- Scorers: `ks_complement_binned` (`quality/_distribution_gof.py:108`) reads only histogram edges
  and counts. Against a shape-bearing plain document it now compares the other histogram with one
  wide source bin, so the score is valid but less discriminating. The `shape_fidelity` numeric
  method (`quality/shape_fidelity.py:163-168`) compares sorted `bin_counts`; a one-element source
  vector can lower that score even though generation uses the unchanged shape block. The E2
  builder lists every caller that passes a plain `distribution_snapshot_document` into either
  scorer and adds or updates a caller-level expectation for the one-bin case. If there is no such
  caller, the PR records that result. The parent AT-9 stays green for every affected caller.
- Docs: `docs/distribution-integrity/snapshot-and-fidelity.md:65` says "equal-width over min to
  max". Plain v2 becomes "one histogram bin when a numeric shape block is released; otherwise
  equal width on a 1, 2, 5 grid, widened until every non-empty bin holds 10 rows". Raw and DP keep
  their current text.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| Released `exact_values` or `quantile_grid` | one histogram bin over the top-coded `[lo, hi]`, holding the finite count; the sampler uses the shape block first |
| `exact_values` with rare dropped mass | subtracting all public exact counts from the sole bin yields only the already public `dropped_count`; it does not locate that mass in an interval |
| `quantile_grid` plus histogram counts | one histogram bin provides no interior cumulative edge count from which a sub-K rank interval can be derived |
| No released numeric shape block | global ladder search; every non-empty bin holds at least K, with the accepted minimality residual in G9 |
| No-shape mass only in the end bins | passes at the first writable level (interior bins are 0) |
| `a == b` (constant core, spread tails) | one bin holding every finite cell, whether selected by the shape branch or the first valid no-shape level; tails clamp into it; G2 holds |
| `0 < b - a` below the grid floor | first writable step at or above the floor; `a` in bin 0, `b` in the last bin; climbs until it passes |
| Grid arithmetic overflows near float max | fallback: one bin `[-1.5, 1.5]` holding every finite cell; a shape block outside those bounds is popped |
| A bin of exactly K rows | passes (`>=`, as `_held_by_k`) |
| Large gap between two clusters | zero bins between them stay as zero bins; they name no value |
| `_MAX_STEP_TRIES` exhausted | fallback (one bin); the bound in 4.1 makes this unreachable for N up to 1000 except at extreme magnitudes |
| `numeric_bins` is `True`, `10.0`, `"10"`, `None`, 0, negative or 1001 | `quality.numeric_bins_invalid` before any histogram; message has the type, not the value |
| `numeric_bins` is `np.int64(17)` | accepted on the plain API |
| `numeric_bins == 1000` | accepted |
| Hand-written v2 snapshot with any strictly increasing edges | already accepted by every reader (`_window_admission.py:108-125`, `_degenerate.py:52-64`, `_sample.py:420-428`) |
| An old 0.28.x plain v2 file with small interior bins | still reads and generates; it lacks the floor (Q2) |
| DP carrier check | unchanged: DP histograms are never coarsened, and `plan/_checks_dp_carrier.py:198` still sees exactly `numeric_bins` bins |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged numeric histogram of a plain document | the shape-aware one-bin branch or the level search in `_top_coded_stats`, the one writer | AT-20, AT-21, AT-24, AT-27, AT-28 | route a released shape through the multi-bin search; stop the no-shape search on writability alone |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory frame; the refusal raises before anything is opened or allocated | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state or cache is added | n/a | n/a |
| 4 | Route parity | CLI plain and DP routes; the engine API | the CLI calls the engine check and keeps no copy of the limit; the DP N = 1 case is stated in 4.3 | AT-C4, AT-C5 | hard-code 1000 in the CLI |
| 5 | Referential integrity | none | N/A: the search reads one column's counts; no key relationship or joint is touched | n/a | n/a |
| 6 | Untrusted producer (user-chosen N; unbounded resource) | `numeric_bins` on the raw, plain, include-values and DP writers | `check_numeric_bins` as the first line of `compute_distribution_snapshot`, through the one `_check_int_param`; the DP condition reads the same constant | AT-22, AT-23 | move the check below the column loop; put the value in the plain message |
| 7 | Check then use (TOCTOU) | none | N/A: no new file read; the CLI check reads only the option value | n/a | n/a |
| 8 | Weak tests | a floor test on a frame with no small interior bin; a count test that trusts the document | each canary test first asserts that the raw (`include_values=True`) document has a bin of 1 to 9 rows; every bin is recounted from the source | AT-20, AT-21, AT-24 | build the probe without the spread values; write counts from a different level than the edges |
| 9 | Refactor drift | `include_values=True`, DP | those paths do not use `_top_coded_stats`; AT-25 pins their bytes | AT-25 | call the search from `numeric_stats` |
| 10 | Frozen contract drift | plain snapshot bytes; the new refusal on `compute_distribution_snapshot` | `Breaking:` line and compat note (section 9) | AT-25, the compat corpus | none beyond AT-25 |

### 6.2 Enumerations

#### Exit paths

- New: `quality.numeric_bins_invalid` (`DistributionSnapshotError`), raised first in
  `compute_distribution_snapshot` (`src/decoy_engine/quality/snapshot.py:137`). The CLI maps it
  to exit 2 through the existing handler (CLI `src/decoy/cli/fit.py:559-564`).
- Changed: `dp_numeric_bins_invalid` (`src/decoy_engine/quality/dp.py:181-185`) also covers
  values over 1000, with the new message suffix.
- No other exit path changes. G5 keeps its existing refusal.

#### Routes

- `decoy fit` plain mode (CLI `src/decoy/cli/fit.py`), calling `distribution_snapshot_document`
  (`src/decoy_engine/profiling/_snapshot_values.py:543`).
- `decoy fit --epsilon` (DP), calling `fit_dp_snapshot` (CLI `src/decoy/cli/fit.py:640-641`).
- The engine API `distribution_snapshot_document` and `compute_distribution_snapshot`.

#### FK shapes

- N/A: the search reads one numeric column and never a key relationship.
- `fanout` degree counts are counts, not values, and are out of scope (parent plan section 2).

#### Fields

- Numeric `bin_edges` of a plain document: uniform width `s` on the ladder
  (`src/decoy_engine/profiling/_snapshot_values.py:416-418` copies them into the document).
- Numeric `bin_counts` of a plain document: each 0 or at least K. No key is added or removed.

#### Output surfaces

- The snapshot file and `fit --json` (keys unchanged).
- The stderr error line and exit 2 for a refused N.
- Generated rows of numeric columns under 100 finite cells fitted from a new plain snapshot.

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Floor constant | `MIN_RELEASE_COUNT` | no |
| One-bin and level grids | `_grid_edges`, `_nice_steps`, the `floor(a / step) * step` anchor in `_top_coded_stats` | shape branch, stop condition and widening |
| Candidate counting | the already sorted finite array in `_top_coded_stats`; NumPy `searchsorted` | count each level without another full-column histogram pass |
| Writable edges | `_writable` | no |
| Clamped histogram | `numeric_stats(bins=..., domain=...)` | no |
| Fixed public fallback | `_FALLBACK_DOMAIN` | released as one bin |
| Parameter check | `check_contingency_top_k`, `MAX_CONTINGENCY_TOP_K` | both checks go through one `_check_int_param` |
| Refusal type | `DistributionSnapshotError`, `DpError` | one new code |
| CLI error exit | the `DistributionSnapshotError` and `DpError` handlers in `fit.py` | no |

## 7. Acceptance tests, red first

Engine (E2): a new file, `tests/unit/profiling/test_snapshot_bin_floor.py` (the parent's
`test_snapshot_floor.py` is already 709 lines). One helper, `recount(cells, stats)`, returns
`np.histogram(np.clip(finite, edges[0], edges[-1]), bins=edges)[0]` for the released edges. The
probe frame: `salary` cycles over the 181 values `40000 + 400 * j`, `j` in 0..180 (so 112000 is
one of them, at `j = 180`), for 500 rows, plus one row of 987654. The test asserts that `salary` is
not in `redacted_columns`, so the column is unflagged.

| # | Test | Fail before |
|---|---|---|
| AT-20 | Quantile-grid probe frame. Non-vacuity: with `include_values=True` and `numeric_bins=1000`, some bin holds 1 to 9 rows and `quantile_grid` is present. Then, for each N in (1, 10, 17, 100, 999, 1000), the plain `salary` histogram has exactly one bin, its count is 501, `recount == bin_counts`, its bounds contain `a`, `b` and every released grid value, and the parent tail swap leaves `min`, `max`, `bin_edges` and `bin_counts` unchanged | before the fix the shape-bearing plain document has many bins, including bins under K |
| AT-21 | No-shape interior canary at the default N: 60 cells, more than 30 distinct values, 25 near 0, 25 near 100 and 10 spread so that one interior bin holds 3 rows. Assert neither shape block is present. The raw document has the 3-row bin; the plain document has none from 1 to 9 and `recount == bin_counts`. A second no-shape fixture has a bin of exactly 10 rows and no bin from 1 to 9 at its first ladder level. The test computes that first step independently from `(b - a) / N` and the 1, 2, 5 ladder, without reading the `include_values=True` histogram, and asserts the released width equals it | the 3-row bin is released |
| AT-21b | `a == b`: 30 cells equal to 50.0 with 5 spread cells on each side. One bin; it holds 40; the parent tail swap leaves every key unchanged | under 0.28.1 the widened grid spreads the tails |
| AT-22 | For `numeric_bins` in (0, -1, 1001, 100_000, 10**8, True, 10.0, "10", None): `distribution_snapshot_document` and `compute_distribution_snapshot` raise `DistributionSnapshotError` with code `quality.numeric_bins_invalid`. Spies on `quality.snapshot.numeric_stats` and on `profile_columns` record no call. The message contains `str(MAX_NUMERIC_BINS)` and neither `100000` nor `987654`. `1`, `1000` and `np.int64(17)` are accepted. `check_contingency_top_k` still refuses its existing bad values with its existing code | no refusal; 10**8 allocates |
| AT-23 | `fit_dp_snapshot(numeric_bins=1001)` raises `DpError` with `dp_numeric_bins_invalid` and the message ends `from 2 to 1000; got 1001.`; 1000 passes the validator; 1 is still refused (validator level, no OpenDP run needed) | 1001 accepted |
| AT-24 | Property (Hypothesis, as the parent's AT-8), N from 1 to 1000. Strategies explicitly cover both branches: no-shape frames with 20 to 99 finite cells and more than 30 distinct values; shape-bearing ordinary floats and repeated ints; a constant core (`a == b`) with spread tails; NaN and +-inf mixed into finite cells; at least K cells at +-1e308 (fallback domain); all-negative values; finite counts of exactly 20 and 21. If a shape block is released, assert exactly one bin containing every shape value. Otherwise assert each count is 0 or `>= K`. Every case: `recount == bin_counts`; counts sum to the finite count; and the parent tail swap leaves `min`, `max`, `bin_edges` and `bin_counts` unchanged, except that fallback cases assert G9 and recount only | a shape-bearing column takes the multi-bin path, or a no-shape first-level count under K is released |
| AT-25 | Guards that stay green: `include_values=True` equals the raw snapshot plus two keys for N 10 and 1000; DP output for N 10 is byte-identical to the base; a flagged numeric still has one coarse bin; every released `quantile_grid` and `exact_values` lies inside a sole histogram bin; the probe round trip (fit, then generate 2,000 rows) decodes and produces the same seeded rows as the pre-floor shape sampler | not fail-before: they pin what must not change |
| AT-26 | `quality.numeric_bins_invalid` is registered with `since` unreleased and listed in `__all__`; the existing reason registry sentries pass | code not registered |
| AT-27 | Accepted minimality residual, no shape: 10 rows at 0, 10 at 100, 6 at 45 and 6 at 55, N = 10. Assert neither shape block is released. Step 10 fails and the plain release has step 20 and counts `[10, 0, 12, 0, 10]`. The test pins the documented fact that each of `[40, 50)` and `[50, 60)` holds 1 to 11 rows rather than claiming the residual is closed | before the floor, step 10 releases two 6-row bins |
| AT-28 | Exact-values subtraction probe: values 0, 5, ..., 95 occur 30 times each except 45 occurs 3 times. Assert the raw shape keeps `exact_values`, reports `dropped_count == 3`, and its step-10 histogram has `[40, 50) == 33`. The plain release keeps the same exact block but has exactly one histogram bin holding the full finite count. Subtracting all public exact counts from that sole bin yields only the already public `dropped_count`; there is no interior edge or cumulative bin count that locates a residual of 1 to 9 rows | before the fix the plain step-10 bin minus the public count for 40 derives 3 rows in `[40, 50)` |

Mutations that must turn a test red:

- Route a released shape block through the multi-bin search (AT-20, AT-24, AT-25, AT-28).
- Stop the no-shape search on writability alone (AT-21, AT-24, AT-27).
- Restore the `max(numeric_bins, ...)` widening (AT-21b, AT-24 tail swap).
- Edge off-by-one: `bins = ceil(...) - 1` or `start = floor(a / step) * step + step` (AT-21,
  AT-24 and AT-27 edge placement and recount).
- Shift the one-bin shape domain so it excludes `a`, `b` or a shape value (AT-20, AT-24, AT-25).
- Write counts from a different level than the edges (AT-21, AT-24 and AT-27 recount).
- Use `>` for `>=` against K (AT-21 exact-10 fixture).
- Treat 0 as failing (AT-27: the empty bins force a needless coarser level).
- Fallback with `numeric_bins` bins (AT-24 fallback strategy).
- Run the search on the `include_values=True` path (AT-25).
- Move `check_numeric_bins` below the column loop (AT-22 spy).
- Use `<` for `<=` against the maximum (AT-22, 1000 accepted).
- Accept bool, or refuse `np.int64` (AT-22).
- Drop the DP maximum (AT-23).
- Put the value in the plain message (AT-22).

### 7b. Existing tests that change (engine)

In `tests/unit/profiling/test_snapshot_floor.py`:

- `test_every_span_writes_at_least_the_requested_bins_on_strict_edges` (`:150`): keep the finite
  and strict edge checks and the sum. Replace `len(bin_counts) >= 17` with "each count is 0 or at
  least K, and the recount matches". The "near float max" span takes the fallback, so it releases
  one bin.
- `test_near_float_max_uses_the_fixed_public_domain_with_every_requested_bin` (`:163`): rename to
  say one bin. Keep `(min, max) == (-1.5, 1.5)`; assert `bin_edges == [-1.5, 1.5]` and
  `bin_counts == [50]`.
- `test_the_end_bins_each_hold_at_least_k_rows_when_the_span_is_not_constant` (`:170`) stays as
  it is. G9 implies it.

Any other test that builds a plain document and asserts `len(bin_counts) == numeric_bins`, or a
widened grid for a narrow or constant span, follows the same rule. The builder lists each one in
the PR. No assertion is weakened beyond replacing the withdrawn "at least N bins" promise with G9.

CLI (C2), after the engine release with E2 is pinned on CLI main:

| # | Test | Fail before |
|---|---|---|
| AT-C3 | Probe CSV, plain `decoy fit --numeric-bins 1000`, exits 0. The snapshot's `salary` counts are each 0 or `>= 10`; widths are equal; `987654` is not in the file; `value_policy` is `flagged-redacted/v2` (`tests/e2e/first_user/test_items_privacy.py`) | on the reverted CLI: exit 2 (option refused in plain mode) |
| AT-C4 | `decoy fit --numeric-bins 100000` and `--numeric-bins 0` exit 2 with `quality.numeric_bins_invalid`, and a spy shows the source reader is not called. The same holds with `--epsilon` and 100000. `--epsilon 1 --numeric-bins 1` exits 2 with `dp_numeric_bins_invalid` | plain mode exits 2 with `dp_mode_not_selected` instead |
| AT-C5 | Rewritten forwarding tests in `tests/e2e/test_fit_command.py`: plain mode passes 17 to `distribution_snapshot_document`; DP mode passes 17 to `fit_dp_snapshot` | the plain option is refused |

C2 mutations: hard-code the limit in the CLI (AT-C4 patches the engine constant to 5 and expects
`--numeric-bins 6` to be refused); check after the read (AT-C4 spy); forward to DP only (AT-C5).

## 8. Placement

No new production module. `profiling/` and `quality/` each hold 25 direct modules, which is the
fan-out limit (`tests/sentry/layout/test_package_fanout.py:25`), so neither can take a new one.

| Change | File | CODEMAP placement | Neighbour or reason |
|---|---|---|---|
| shape-aware one-bin branch and level search (searchsorted counts, stop test, no widening, one-bin fallback) | `src/decoy_engine/profiling/_snapshot_values.py` | "Detectors, profiling" row | inside `_top_coded_stats` |
| `MAX_NUMERIC_BINS`, `_check_int_param`, `check_numeric_bins` and the call | `src/decoy_engine/quality/snapshot.py` | the existing quality snapshot owner | beside `MAX_CONTINGENCY_TOP_K` and `check_contingency_top_k` |
| lazy exports | `src/decoy_engine/quality/__init__.py` | existing re-export map | same map as `MAX_CONTINGENCY_TOP_K` |
| DP maximum and message | `src/decoy_engine/quality/dp.py` | existing DP fit owner | `_validate_fit_params` |
| reason code and `__all__` entry | `src/decoy_engine/reasons/quality/_part1.py` | existing reason catalog | the `DistributionSnapshotError` group |
| acceptance tests | `tests/unit/profiling/test_snapshot_bin_floor.py` | "Unit tests" row | beside `test_snapshot_floor.py` |
| DP bound test | the existing DP validator test file under `tests/unit/quality/` | "Unit tests" row | beside the existing `dp_numeric_bins_invalid` cases |
| docs and fragment | `docs/strategies.md` (the plain-snapshot section, `:1696-1715`), `docs/distribution-integrity/snapshot-and-fidelity.md:65`, `docs/compatibility-contract.md` (the v2 paragraph), `docs/reasons.md` if the registry generates it, `changelog.d/24f-interior-bin-floor.md` | "Feature and contract docs" and "Changelog fragments" rows | existing owners |
| CLI | `src/decoy/cli/fit.py`, the C2 tests, the fit guide and troubleshooting pages, roadmap row 24f, the shipped log | CLI CODEMAP command and "First-user QA item tests" rows | no new CLI module |

Module size. `_snapshot_values.py` has 589 lines and `quality/snapshot.py` has 595. The goal is
600 (`tests/sentry/test_module_size.py:71`). E2 adds the shape branch and searchsorted candidate
counts to the first and about 10 lines to the second. The builder first keeps each file at or under
600 by trimming duplicated prose in the same file's module docstring (`_snapshot_values.py:1-24`
gives the SDC citations twice; `quality/snapshot.py:1-60` carries a long D1a history). A census
entry at the measured count, at most 620, is the last resort only if a trim would lose meaning;
the PR records it. That is V2-LOG, not a stop.

Expected size: E2 is about 45 production lines across 5 files, about 320 test lines and about 45
doc lines. New public names: `MAX_NUMERIC_BINS`, `check_numeric_bins` and
`reasons.quality.NUMERIC_BINS_INVALID`. C2 is 1 production file, about 15 production lines and
about 90 test and doc lines.

## 9. Frozen contracts touched (compatibility contract impact)

- Plain snapshot bytes change (`distribution_snapshot_document`, a frozen surface listed in
  `docs/frozen-surfaces.md:101`). A shape-bearing numeric column now has one accompanying histogram
  bin. A no-shape grid with a bin of 1 to 9 rows now has a coarser uniform grid. This includes
  default-N fits of small or skewed columns, narrow or constant spans (no widening) and the
  float-max fallback (one bin). Pre-GA, so the fragment
  carries a `Breaking:` line:
  "Breaking: a plain `decoy fit` snapshot writes one numeric histogram bin when it releases an
  `exact_values` or `quantile_grid` block; otherwise it widens to the finest 1, 2, 5 step at which
  every non-empty bin holds 10 rows. It can therefore have fewer bins than `numeric_bins`.
  `numeric_bins` outside 1 to 1000 is refused with `quality.numeric_bins_invalid` by every snapshot
  writer, and above 1000 by the DP fit."
- `compute_distribution_snapshot`: the signature does not change. It gains a refusal for values
  that crashed before (0 or less) or could exhaust memory (over 1000). Bytes are unchanged for
  valid N. `contingency_top_k` and `numeric_bins` accept `np.int64` (a loosening).
- Schema and marker stay `distribution-snapshot/v2` and `flagged-redacted/v2` (Q2). Every reader
  already accepts any strictly increasing finite edges, so no reader changes. The compat-contract
  v2 paragraph gains one sentence: "A plain v2 numeric histogram accompanying `exact_values` or
  `quantile_grid` has one bin; without either block, it has equal-width bins on a 1, 2, 5 grid and
  every non-empty bin is held by at least 10 rows."
- Reason codes: one new code, `quality.numeric_bins_invalid`, with `since` unreleased. Release
  prep stamps the version. The DP message text changes; the DP code does not.
- Generated output (contract 3.3): columns with a released numeric shape block generate the same
  seeded rows because the sampler reads that block first. Output can change only for a no-shape
  numeric column whose histogram coarsens. Old snapshots generate as before.
- DP: bytes are unchanged for N up to 1000.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E2 | 4.1 and 4.2, docs, compat note, fragment | R2 | 5 production files; about 45 source, 320 test and 45 doc lines | none (E1 is merged) | AT-20 to AT-28, the 7b edits, `tests/unit/profiling/`, `tests/unit/quality/`, `tests/unit/generation/statistical/`, `tests/sentry/profiling/`, the reason registry sentries, `tests/sentry/test_module_size.py`, `tests/sentry/layout/` |
| release | engine release with E2, then the CLI repin (engine repin checklist) | R1 | standard | E2 merged | release checks |
| C2 | 4.3, help, guide, troubleshooting, AT-C3 to AT-C5, roadmap row 24f, shipped log | R1 | 1 production file; about 105 lines in all | CLI #340 merged with the revert; the repin above on CLI main | AT-C3 to AT-C5, `tests/e2e/test_fit_command.py`, `tests/e2e/first_user/test_items_privacy.py` |

E2 changes the output of a frozen surface and adds a reason code. Both are full-suite triggers in
`testing.md`, so the E2 merge head gets the full engine suite against the saved main baseline.
Tests run on the Mac first, then through `~/bin/vm-run`, never on the devbox. C2 runs T1 only.

Row 24f stays PARTLY MERGED until C2 merges. Roadmap text for the row (CLI repo): "E2 (interior
bin floor and `numeric_bins` ceiling, plan `E:docs/plans/2026-11-20-24f-interior-bin-floor.md`),
then C2 (plain `--numeric-bins`)."

## 11. Stop lines for builders

1. A released numeric shape block gets one accompanying histogram bin. Without a released shape,
   the grid is one uniform level of the existing ladder and anchor. No per-bin merge, no edge
   chosen from counts, no new threshold constant, no change to `MIN_RELEASE_COUNT`.
2. Do not coarsen DP, raw or `include_values=True` histograms.
3. Do not fold empty bins.
4. No new module in `profiling/` or `quality/`; both are at the fan-out limit.
5. One limit constant, `MAX_NUMERIC_BINS`, and one `_check_int_param`. The CLI and `dp.py` import
   the constant and do not copy it.
6. No message, log or exception text carries a cell value. The plain check names the type only,
   as `check_contingency_top_k` does; the DP message keeps its existing `got <repr>` suffix for
   the request parameter.
7. A red test outside 7b is a stop. Weakening an assertion beyond the withdrawn "at least N bins"
   promise and the removed widening is a stop.
8. More than 8 production files or 400 changed lines in E2 is a stop.
9. Either 1M-row timing in 4.1 over 2 seconds per column is a stop and a report.

## 12. Owner questions (recommended option first)

- Q1. Ceiling. (a) Recommended: a fixed `MAX_NUMERIC_BINS = 1000`, the same figure as
  `MAX_CONTINGENCY_TOP_K`, together with the level search. Memory is bounded before any data is
  read. (b) Refuse N above rows/10. This needs the data first, does not bound memory on large
  files, and makes the same command pass or fail by file size. (c) A higher fixed cap such as
  10,000. Generation already gets fine detail from the `quantile_grid`, so there is no present
  consumer for it.
- Q2. Version bump. (a) Recommended: keep `distribution-snapshot/v2` and `flagged-redacted/v2`.
  The shape does not change, every reader already accepts these edges, v2 is in no released CLI
  build, and the project is pre-release (no product decision is locked). (b) Move the marker to
  `flagged-redacted/v3` so a reader can tell whether a file has the interior floor. That costs one
  more accepted-policy entry and test changes, for little value before GA.
- Q3. DP ceiling. (a) Recommended: apply the same 1000 maximum to `fit_dp_snapshot` with its
  existing code. It is the same out-of-memory fault on the other route, and the change is one
  condition. (b) Leave DP unbounded and record a follow-up.

## 13. Pre-mortem

- A user asks for 50 bins on a 200-row column and gets one because a shape block is released, or a
  small number after a no-shape grid coarsens. The help text and guide explain both rules.
  `--include-values` gives the raw histogram.
- One sparse region makes a no-shape column coarse. Generation is unaffected when `quantile_grid`
  or `exact_values` is released. The no-shape cost is accepted (5.1).
- A later change adds another histogram key to the plain numeric entry, or a second writer. The
  AT-24 property test reads every `bin_counts` and recounts it, and the parent's registry sentry
  fails on an unclassified key.
- Someone raises the cap later. That changes one constant, and the refusal test reads the
  constant, so the bounds stay pinned.

## 14. Sources

- [KS Handbook on Statistical Disclosure Control, 2nd ed. (2025)](https://ue.poznan.pl/wp-content/uploads/2025/12/KS-Handbook-on-Statistical-Disclosure-Control.pdf): threshold rule and table redesign for frequency tables.
- [tau-ARGUS manual, Producing safe tables](https://julienjamme.github.io/manual_tau_argus_to_quarto/02_Producing_Safe_tables.html): global recoding before suppression.
- [CBS CASC SDC FAQ](https://research.cbs.nl/casc/FAQ.htm): threshold semantics.
- [Navas-Palencia, Optimal binning: mathematical programming formulation](https://arxiv.org/pdf/2001.08025): minimum records per bin (the per-bin approach, rejected here).
- [OptimalBinningWoE `ob_numerical_mob`](https://www.rdocumentation.org/packages/OptimalBinningWoE/versions/1.0.8/topics/ob_numerical_mob): small bins merged with an adjacent bin (rejected here).
- R. C.-W. Wong, A. W.-C. Fu, K. Wang and J. Pei, "Minimality Attack in Privacy Preserving Data
  Publishing" (VLDB 2007): choosing the least generalized data-dependent release can itself reveal
  facts about the records; this is the documented V1 residual.
- Hundepool et al., Statistical Disclosure Control (Wiley 2012), section 3.4 and chapter 5; R sdcMicro `globalRecode`; ARX generalization hierarchies; P. Samarati, "Protecting respondents' identities in microdata release" (IEEE TKDE, 2001); F. Kohlmayer et al., "Flash: efficient, stable and optimal k-anonymity" (2012); LeFevre, DeWitt and Ramakrishnan, "Mondrian Multidimensional K-Anonymity" (ICDE 2006).

## 15. Revision map

### Revision 2 (Dennis r1: NO-GO, 1 HIGH, 3 MEDIUM, 5 LOW)

| # | Finding | Change |
|---|---|---|
| HIGH-1 | Greedy fold edges show sub-bin counts (an edge at 47.5 proves someone is 47) | Option (a): level-based global recoding on the same 1, 2, 5 ladder and anchor; the whole grid coarsens until every non-empty bin holds K; edges are a function of `a`, `b` and the level; empty bins stay. G9 restated; G2 now holds without exceptions (widening removed); G10 and the memory bound re-derived (2.2, 4.1); residual level disclosure stated; AT-27 integer ages |
| MEDIUM-1 | Counts not checked against the source | AT-20, AT-21, AT-24 and AT-27 recount every released bin with `np.histogram` over the released edges; edge off-by-one and "counts from another level" mutations added |
| MEDIUM-2 | AT-24 strategies too narrow | constant core, NaN and +-inf, cells at +-1e308, all-negative, exactly 20 and 21 cells; G9 and recount only on constant-core and fallback cases; AT-21b pins G2 on `a == b` |
| MEDIUM-3 | Two copies of the parameter check | one private `_check_int_param` used by `check_contingency_top_k` and `check_numeric_bins` |
| LOW-1 | Float-max fallback row and 7b expectation | the fallback releases one bin `[-1.5, 1.5]`; failure-mode row and 7b rewritten |
| LOW-2 | Messages hard-code 1000; DP message change unstated | messages read `MAX_NUMERIC_BINS`; the DP suffix change is stated (4.2) and asserted (AT-23) |
| LOW-3 | `np.int64` broke on the plain API | the check accepts non-bool `numbers.Integral` (AT-22) |
| LOW-4 | CLI and engine DP code parity | stated in 4.3; AT-C4 covers `--epsilon --numeric-bins 1` |
| LOW-5 | `__all__` and module size | `NUMERIC_BINS_INVALID` in `__all__` (4.2, AT-26); the trim-or-census route stays |

### Revision 3 (reviewer r2: NO-GO, 2 HIGH, 2 MEDIUM, 3 LOW)

| # | Finding | Change |
|---|---|---|
| HIGH-1 | `exact_values` counts subtracted from a multi-bin histogram locate the public `dropped_count` in a sub-K interval | G9 adds the one-bin rule whenever `exact_values` or `quantile_grid` is released; 4.1 branches before the level search; AT-28 pins the 0, 5, ..., 95 probe and proves there is no bin-local residual beyond the already public total |
| MEDIUM-1 | `quantile_grid` ranks minus cumulative edge counts can derive sub-K interval counts | Closed by the same shape-aware one-bin rule; G9, G10, 5.1, the failure table, AT-20, AT-24 and AT-25 cover the sampler and scorer effects |
| HIGH-2 | The finest passing level has a true minimality attack, including identification of the only failing coarse bin | G9 states the worst case and the 10@0, 10@100, 6@45, 6@55 example; Wong et al. 2007 is cited; AT-27 pins the residual; the owner-recorded V1 acceptance and a V2-LOG mitigation follow-up are explicit |
| MEDIUM-2 | The datetime year fold was cited as a safe precedent although its greedy edges have the same fault | Section 3 rejects it as a precedent; the follow-up list records a uniform year ladder remedy outside this slice |
| LOW-1 | AT-21's exact-K fixture used the raw histogram as its expected first level | AT-21 computes the first 1, 2, 5 step independently from `(b - a) / N` |
| LOW-2 | Repeated full-column histogram passes did not justify the time bound at large magnitude | 4.1 counts candidates with `searchsorted` over one sorted array and measures both a representative 1M-row column and one centered at `1e15` with small spread; stop line retained |
| LOW-3 | Module-size remedy gave a census entry equal standing with deleting duplicated docstrings | Section 8 makes docstring trimming the first choice and a census entry the last resort |
