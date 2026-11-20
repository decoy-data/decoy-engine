Status: plan

# 24f interior bin floor: no plain-fit numeric bin holds 1 to 9 rows, and `numeric_bins` has a ceiling (roadmap row 24f, amendment)

Owner: Cam. Author: Opus plan agent. Date of decision: 2026-11-20. Revision 2, after Dennis plan
review round 1 (NO-GO). The change map is in section 15.

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

- G9. The released histogram has one bin width `s`, a step of the Heckbert 1, 2, 5 times 10^k
  ladder. Its edges are `lo + i * s` for `i = 0..m`, with `lo = floor(a / s) * s` and `m =
  max(1, ceil((b - lo) / s))`. So the edges are a function of `a`, `b` and `s` only. Every bin holds
  0 rows or at least `MIN_RELEASE_COUNT` (K = 10) rows. No bin holds 1 to K-1 rows. No released
  edge lies inside another released bin, so no count finer than width `s` can be derived from the
  document. `s` is the finest ladder step, starting from the step `numeric_bins` asks for, at which
  every non-empty bin holds K rows and the edges can be written. The float-max fallback releases
  one bin `[-1.5, 1.5]` that holds every finite cell.
- G2 (parent, now without exceptions). Replacing any of the K-1 smallest cells by another value
  below `a`, or any of the K-1 largest by another value above `b`, changes no `min`, `max`,
  `bin_edges` or `bin_counts`. This now holds for `a == b` and for spans below the grid floor too,
  because the widened grid is gone (4.1).
- G10. `bin_edges[0] <= a` and `bin_edges[-1] >= b`, so every `quantile_grid` point and every
  `exact_values` value (each held by K rows, so inside `[a, b]`) lies inside the released edges.
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

Residual disclosure, accepted: the chosen level `s` says that the next finer ladder step failed,
which means some finer bin held 1 to K-1 rows or the finer edges could not be written. It does not
say which bin or what count. Every global recoding search that picks the least coarse level that
passes has this property (section 3). It is inside the V1 threat model (accidental leaks only).

Unchanged: `include_values=True` output for any N up to the ceiling (parent G6); DP histograms
(noised, and the carrier check needs exactly `numeric_bins` bins); datetime ranges (parent G3);
`quantile_grid` and `exact_values` (already K-floored); `mean` and `std`; flagged and G5 numeric
columns (one coarse bin).

Non-goals (recorded follow-ups, not blockers):

- Freetext `length_bin_counts`. A length is not a cell value, and the parent plan excludes length
  statistics. G11 bounds their memory. V2-LOG item: "freetext length bins under K".
- Folding empty bins into a neighbour. Empty bins stay as zero bins, because a fold would make an
  edge depend on the data again. A count of 0 names no value.
- A user-visible note when the histogram coarsens. The help text and the guide state the rule.
- Reconstruction across several snapshots of the same source with different N (parent non-goal).
- Scan and profile documents (row 24zm).

## 3. Established solutions

Search run (2026-11-20): the SDC handbook (Hundepool et al., 2012, and the 2025 second edition)
on frequency tables; the tau-ARGUS manual "Producing safe tables"; sdcMicro `globalRecode`; ARX
interval generalization hierarchies and its lattice search; Samarati (2001) minimal
generalization; Mondrian (LeFevre, DeWitt, Ramakrishnan, ICDE 2006); OptBinning (Navas-Palencia,
arXiv 2001.08025) and R OptimalBinningWoE minimum-bin-size merging; the CBS SDC FAQ on threshold
semantics. In the codebase: `_top_coded_stats`, `_nice_steps` and `_writable`
(`_snapshot_values.py:299-355`), `check_contingency_top_k` (`quality/snapshot.py:127`) and
`_FALLBACK_DOMAIN`.

| Source | What it does | Used here |
|---|---|---|
| sdcMicro `globalRecode` (breaks or a fixed interval width for the whole variable) | Recodes every value of a variable into intervals on one set of breaks | The release is one uniform interval width for the whole column |
| ARX generalization hierarchies; Samarati 2001; Kohlmayer et al., "Flash" (2012) | A variable is generalized to one level of a fixed hierarchy; the search picks the lowest level at which every group holds k | The ladder is the hierarchy; we pick the finest level at which every non-empty bin holds K |
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), chapter 5: threshold rule and table redesign | A cell under the threshold is unsafe; table redesign collapses categories until no cell is unsafe | The rule (G9) |
| tau-ARGUS manual, "Producing safe tables" | Global recoding of the spanning variable first, then suppression | Recoding only; a one-way histogram with uniform bins has no margin that recomputes a part |
| CBS SDC FAQ | The threshold comparison is stated exactly | `count >= K` is safe, as `_held_by_k` and the year fold. K = 10 is the owner-set floor |
| OptBinning; OptimalBinningWoE; greedy adjacent fold (revision 1) | Merge a small bin with a neighbour, bin by bin | Rejected: edges chosen bin by bin show where the rows are (1.2) |
| Mondrian in one dimension | Median cut points while each part keeps k | Rejected: a median cut can equal a real cell |

Reuse: the ladder `_nice_steps`, the anchor `floor(a / step) * step`, the writability check
`_writable` and the clamped `numeric_stats(bins, domain)` all exist. The change replaces the
widening rule and the stop condition of the existing loop in `_top_coded_stats`. No new merge code.

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
the AT-24 property test over every plain `bin_counts`. Mutation: stop on writability alone.

### 4.1 Level search (E2, `profiling/_snapshot_values.py`, `_top_coded_stats`)

Inputs as today: `a` = K-th smallest finite cell, `b` = K-th largest, and the start width
`(b - a) / numeric_bins` when `a < b`, else `_grid_step(a, b)`.

```
for step in islice(_nice_steps(width), _MAX_STEP_TRIES):
    start = floor(a / step) * step                     # Decimal, as today
    bins = max(1, ceil((b - start) / step))            # no max(numeric_bins, ...) widening
    domain = (float(start), float(start + step * bins))
    stop to the fallback if a domain end is not finite or numeric_stats overflows (as today)
    stats = numeric_stats(non_null, bins=bins, domain=domain)
    if _writable(stats, bins) and every count is 0 or >= MIN_RELEASE_COUNT:
        return stats, False
return numeric_stats(non_null, bins=1, domain=_FALLBACK_DOMAIN), True
```

Changes from 0.28.1, and why:

- The stop test adds "every count is 0 or at least K". The loop climbs the ladder from the
  requested resolution until the whole column passes. The result is the finest passing level.
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
bin. So every level's counts, and with them the chosen level, do not change under the swap.

Memory and time: the first level has at most `(b - a) / s0 + 1` bins with `s0 > width / 2.5`, so
at most about `2.5 * numeric_bins + 1` (2,501 for N = 1000). Later levels have fewer. Each level is
one `numeric_stats` pass, O(n), so a column costs at most about 14 passes. On 1M rows that is well
under a second per column. The builder measures it in the PR (one 1M-row column, N = 1000); a
result over 2 seconds is a stop and a report, not a silent optimization.

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
  fit widens the bins until every non-empty bin holds at least 10 rows." The fit guide and the
  troubleshooting page say the same.

## 5. Behaviour

| Case | Today (0.28.1 with the PR #340 CLI) | After E2 and C2 |
|---|---|---|
| Probe, `--numeric-bins 100000` | 173,000 bins, 23 with one row; `[112000, 112001)` names a value | exit 2, `quality.numeric_bins_invalid`, before the CSV is read |
| Probe, `--numeric-bins 1000` | about 2,500 narrow bins, many with 1 to 3 rows | one uniform width, coarse enough that every non-empty bin holds 10 or more rows |
| Ages 18 to 90, `--numeric-bins 100`, age 47 held by 3 rows | step 0.5; the 47 bin holds 3 | step 2 (0.5 and 1 fail at 47); `[46, 48)` holds 33; no edge at 47 or 47.5 |
| Default 10 bins, one interior bin of 3 rows | released | the whole histogram moves to the next ladder step until it passes |
| `--numeric-bins 100000000` | histogram allocation, out of memory | exit 2 before any allocation |
| `--numeric-bins 0` or `-3` | passed through; numpy `ValueError` | exit 2, registered code |
| `--epsilon 1 --numeric-bins 1` | DP refusal | DP refusal, `dp_numeric_bins_invalid`, exit 2 |
| `include_values=True`, N up to 1000 | raw | raw, byte-identical |
| `include_values=True`, N over 1000 | allocates | refused, registered code |
| DP fit, N over 1000 | allocates N-1 edges per column | refused, `dp_numeric_bins_invalid` |
| Flagged or G5 numeric | one coarse bin | unchanged |
| 100 or more finite cells | sampler draws from `quantile_grid` | draws unchanged; only the released histogram is coarser |

### 5.1 Fidelity cost

- Generation: the sampler reads the histogram only when a column has no `quantile_grid` or
  `exact_values`, which means under 100 finite cells (`MIN_GRID_ROWS`,
  `generation/statistical/_numeric_shape.py:52`). With 20 to 99 cells, at most 9 non-empty bins
  can pass, and one sparse region coarsens the whole column. Draws stay inside `[lo, hi]`.
- Uniform coarsening is coarser than a per-bin merge. That is the price of edges that show
  nothing about where rows sit (1.2).
- Scorers: `ks_complement_binned` (`quality/_distribution_gof.py:108`) evaluates the union of both
  edge lists, so a different bin count compares correctly. The `shape_fidelity` numeric method
  (sorted `bin_counts` TVD) gets a shorter source vector when a caller scores against a plain
  document. The E2 builder lists every caller that passes a plain `distribution_snapshot_document`
  into a scorer. If there is one, the parent's AT-9 must stay green on it. If there is none, the
  PR says "no scorer reads a plain document's histogram".
- Docs: `docs/distribution-integrity/snapshot-and-fidelity.md:65` says "equal-width over min to
  max". Plain v2 bins become "equal width on a 1, 2, 5 grid, widened until every non-empty bin
  holds 10 rows". Raw and DP keep their current text.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| Mass only in the end bins | passes at the first writable level (interior bins are 0) |
| `a == b` (constant core, spread tails) | one bin `[lo, lo + s]` holding every finite cell; tails clamp into it; G2 holds |
| `0 < b - a` below the grid floor | first writable step at or above the floor; `a` in bin 0, `b` in the last bin; climbs until it passes |
| Grid arithmetic overflows near float max | fallback: one bin `[-1.5, 1.5]` holding every finite cell; shape blocks popped |
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
| 1 | Value-bearing output | every unflagged numeric histogram of a plain document | the level search in `_top_coded_stats`, the one writer | AT-20, AT-21, AT-24, AT-27 | stop the search on writability alone |
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
| Level ladder and anchor | `_nice_steps`, the `floor(a / step) * step` anchor in `_top_coded_stats` | stop condition and widening only |
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
| AT-20 | Probe frame. Non-vacuity: with `include_values=True` and `numeric_bins=1000`, some bin holds 1 to 9 rows. Then, for each N in (1, 10, 17, 100, 999, 1000), the plain `salary` histogram: every count is 0 or `>= 10`; `recount == bin_counts`; the sum is 501; all widths are equal (to 12 places) and the width is a 1, 2, 5 times 10^k step; `bin_edges[0] <= a < bin_edges[1]` and `bin_edges[-2] <= b <= bin_edges[-1]`, with `a` and `b` read from the sorted source cells | at N = 1000 many bins hold one row |
| AT-21 | Interior canary at the default N: 60 cells, 25 near 0, 25 near 100 and 10 spread so that one interior bin holds 3 rows. The raw document has the 3-row bin; the plain document has none from 1 to 9 and `recount == bin_counts`. A second fixture whose first level has a bin of exactly 10 rows and no bin from 1 to 9 is released at that first level (same width as the raw grid would choose) | the 3-row bin is released |
| AT-21b | `a == b`: 30 cells equal to 50.0 with 5 spread cells on each side. One bin; it holds 40; the parent tail swap leaves every key unchanged | under 0.28.1 the widened grid spreads the tails |
| AT-22 | For `numeric_bins` in (0, -1, 1001, 100_000, 10**8, True, 10.0, "10", None): `distribution_snapshot_document` and `compute_distribution_snapshot` raise `DistributionSnapshotError` with code `quality.numeric_bins_invalid`. Spies on `quality.snapshot.numeric_stats` and on `profile_columns` record no call. The message contains `str(MAX_NUMERIC_BINS)` and neither `100000` nor `987654`. `1`, `1000` and `np.int64(17)` are accepted. `check_contingency_top_k` still refuses its existing bad values with its existing code | no refusal; 10**8 allocates |
| AT-23 | `fit_dp_snapshot(numeric_bins=1001)` raises `DpError` with `dp_numeric_bins_invalid` and the message ends `from 2 to 1000; got 1001.`; 1000 passes the validator; 1 is still refused (validator level, no OpenDP run needed) | 1001 accepted |
| AT-24 | Property (hypothesis, as the parent's AT-8), N from 1 to 1000. Strategies: ordinary finite floats and ints; a constant core (`a == b`) with spread tails; NaN and +-inf mixed into finite cells; at least K cells at +-1e308 (fallback domain); all-negative values; finite counts of exactly 20 and 21. Every case: each count is 0 or `>= K`, or the column is one bin; `recount == bin_counts`; counts sum to the finite count. Ordinary, all-negative and 20/21 cases also: equal widths, and the parent tail swap leaves `min`, `max`, `bin_edges` and `bin_counts` unchanged. Constant-core and fallback cases assert G9 and the recount only | first count under K |
| AT-25 | Guards that stay green: `include_values=True` equals the raw snapshot plus two keys for N 10 and 1000; DP output for N 10 is byte-identical to the base; a flagged numeric still has one coarse bin; `quantile_grid` and `exact_values` lie inside the released outer edges; the probe round trip (fit, then generate 2,000 rows) decodes and generates | not fail-before: they pin what must not change |
| AT-26 | `quality.numeric_bins_invalid` is registered with `since` unreleased and listed in `__all__`; the existing reason registry sentries pass | code not registered |
| AT-27 | Integer ages, Dennis's case: ages 18 to 90, each held by 30 rows except 47, held by 3 rows; `numeric_bins=100`. Non-vacuity: the raw grid at step 0.5 has a bin holding 3. Plain: width 2; edges equal `lo + i * 2` recomputed in the test from `a`, `b` and the width alone; neither 47.0 nor 47.5 is an edge; every count is 0 or `>= 10`; `recount == bin_counts`; no released edge lies strictly inside another released bin. Control: with the 3 rows moved to age 46 (47 empty), the release is width 0.5 (the half-integer bins and the 47 bin are empty) and every count is 0 or `>= 10` | revision 1's greedy fold puts an edge at 47.5 |

Mutations that must turn a test red:

- Stop the search on writability alone (AT-20, AT-21, AT-24, AT-27).
- Restore the `max(numeric_bins, ...)` widening (AT-21b, AT-24 tail swap).
- Edge off-by-one: `bins = ceil(...) - 1` or `start = floor(a / step) * step + step` (AT-20 `a` and
  `b` placement, AT-24 tail swap).
- Write counts from a different level than the edges (AT-20, AT-24 recount).
- Use `>` for `>=` against K (AT-21 exact-10 fixture).
- Treat 0 as failing (AT-27 control: a gap forces a needless coarser level; the test pins width 0.5).
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
| level search (stop test, no widening, one-bin fallback) | `src/decoy_engine/profiling/_snapshot_values.py` | "Detectors, profiling" row | inside `_top_coded_stats` |
| `MAX_NUMERIC_BINS`, `_check_int_param`, `check_numeric_bins` and the call | `src/decoy_engine/quality/snapshot.py` | the existing quality snapshot owner | beside `MAX_CONTINGENCY_TOP_K` and `check_contingency_top_k` |
| lazy exports | `src/decoy_engine/quality/__init__.py` | existing re-export map | same map as `MAX_CONTINGENCY_TOP_K` |
| DP maximum and message | `src/decoy_engine/quality/dp.py` | existing DP fit owner | `_validate_fit_params` |
| reason code and `__all__` entry | `src/decoy_engine/reasons/quality/_part1.py` | existing reason catalog | the `DistributionSnapshotError` group |
| acceptance tests | `tests/unit/profiling/test_snapshot_bin_floor.py` | "Unit tests" row | beside `test_snapshot_floor.py` |
| DP bound test | the existing DP validator test file under `tests/unit/quality/` | "Unit tests" row | beside the existing `dp_numeric_bins_invalid` cases |
| docs and fragment | `docs/strategies.md` (the plain-snapshot section, `:1696-1715`), `docs/distribution-integrity/snapshot-and-fidelity.md:65`, `docs/compatibility-contract.md` (the v2 paragraph), `docs/reasons.md` if the registry generates it, `changelog.d/24f-interior-bin-floor.md` | "Feature and contract docs" and "Changelog fragments" rows | existing owners |
| CLI | `src/decoy/cli/fit.py`, the C2 tests, the fit guide and troubleshooting pages, roadmap row 24f, the shipped log | CLI CODEMAP command and "First-user QA item tests" rows | no new CLI module |

Module size. `_snapshot_values.py` has 589 lines and `quality/snapshot.py` has 595. The goal is
600 (`tests/sentry/test_module_size.py:71`). E2 adds about 3 lines to the first (the loop changes
shape, the widening goes) and about 10 to the second. The builder keeps each file at or under 600
by trimming duplicated prose in the same file's module docstring (`_snapshot_values.py:1-24` gives
the SDC citations twice; `quality/snapshot.py:1-60` carries a long D1a history). If a trim would
lose meaning, the builder adds a census entry at the measured count (at most 620) and says so in
the PR. That is V2-LOG, not a stop.

Expected size: E2 is about 30 production lines across 5 files, about 280 test lines and about 40
doc lines. New public names: `MAX_NUMERIC_BINS`, `check_numeric_bins` and
`reasons.quality.NUMERIC_BINS_INVALID`. C2 is 1 production file, about 15 production lines and
about 90 test and doc lines.

## 9. Frozen contracts touched (compatibility contract impact)

- Plain snapshot bytes change (`distribution_snapshot_document`, a frozen surface listed in
  `docs/frozen-surfaces.md:101`). A plain document whose numeric grid had a bin of 1 to 9 rows now
  has a coarser uniform grid. This includes default-N fits of small or skewed columns, narrow or
  constant spans (no widening) and the float-max fallback (one bin). Pre-GA, so the fragment
  carries a `Breaking:` line:
  "Breaking: a plain `decoy fit` snapshot widens each numeric histogram to the finest 1, 2, 5 step
  at which every non-empty bin holds 10 rows, so it can have fewer bins than `numeric_bins`;
  `numeric_bins` outside 1 to 1000 is refused with `quality.numeric_bins_invalid` by every snapshot
  writer, and above 1000 by the DP fit."
- `compute_distribution_snapshot`: the signature does not change. It gains a refusal for values
  that crashed before (0 or less) or could exhaust memory (over 1000). Bytes are unchanged for
  valid N. `contingency_top_k` and `numeric_bins` accept `np.int64` (a loosening).
- Schema and marker stay `distribution-snapshot/v2` and `flagged-redacted/v2` (Q2). Every reader
  already accepts any strictly increasing finite edges, so no reader changes. The compat-contract
  v2 paragraph gains one sentence: "A plain v2 numeric histogram has equal-width bins on a 1, 2, 5
  grid, and every non-empty bin is held by at least 10 rows."
- Reason codes: one new code, `quality.numeric_bins_invalid`, with `since` unreleased. Release
  prep stamps the version. The DP message text changes; the DP code does not.
- Generated output (contract 3.3): changes only for statistical numeric columns with under 100
  finite cells fitted from a new plain snapshot. Old snapshots generate as before.
- DP: bytes are unchanged for N up to 1000.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E2 | 4.1 and 4.2, docs, compat note, fragment | R2 | 5 production files; about 30 source, 280 test and 40 doc lines | none (E1 is merged) | AT-20 to AT-27, the 7b edits, `tests/unit/profiling/`, `tests/unit/quality/`, `tests/unit/generation/statistical/`, `tests/sentry/profiling/`, the reason registry sentries, `tests/sentry/test_module_size.py`, `tests/sentry/layout/` |
| release | engine release with E2, then the CLI repin (engine repin checklist) | R1 | standard | E2 merged | release checks |
| C2 | 4.3, help, guide, troubleshooting, AT-C3 to AT-C5, roadmap row 24f, shipped log | R1 | 1 production file; about 105 lines in all | CLI #340 merged with the revert; the repin above on CLI main | AT-C3 to AT-C5, `tests/e2e/test_fit_command.py`, `tests/e2e/first_user/test_items_privacy.py` |

E2 changes the output of a frozen surface and adds a reason code. Both are full-suite triggers in
`testing.md`, so the E2 merge head gets the full engine suite against the saved main baseline.
Tests run on the Mac first, then through `~/bin/vm-run`, never on the devbox. C2 runs T1 only.

Row 24f stays PARTLY MERGED until C2 merges. Roadmap text for the row (CLI repo): "E2 (interior
bin floor and `numeric_bins` ceiling, plan `E:docs/plans/2026-11-20-24f-interior-bin-floor.md`),
then C2 (plain `--numeric-bins`)."

## 11. Stop lines for builders

1. The released grid is one uniform level of the existing ladder and anchor. No per-bin merge, no
   edge chosen from counts, no new threshold constant, no change to `MIN_RELEASE_COUNT`.
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
9. The 1M-row timing in 4.1 over 2 seconds per column is a stop and a report.

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

- A user asks for 50 bins on a 200-row column and gets 5. The help text and the guide say that
  bins widen until every non-empty bin holds 10 rows. `--include-values` gives the raw histogram.
- One sparse region makes a whole column coarse. Generation is unaffected at 100 or more cells
  (`quantile_grid`). Under 100 cells the cost is accepted (5.1).
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
