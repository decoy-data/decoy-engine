Status: plan

# PROFILE-UNFLAGGED-VALUES: a plain profile document keeps no rare or exact cell of any column (roadmap row 24zm)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `profiles/local-operations.md`, `bugfix.md`, `refactoring.md`,
`cross-cutting-concerns.md`, `api-and-compatibility.md`, `catalogs/recurring-defects.md`;
engine `CLAUDE.md`, `CODEMAP.md` ("Where Things Go"), `docs/frozen-surfaces.md`,
`docs/qa/03-pre-scan-profiling-detection.md`, `tests/sentry/layout/test_package_fanout.py`;
CLI `docs/ROADMAP.md` rows 24c, 24f and 24zm; the row 24f plan
(`origin/plan/fit-unflagged-values:docs/plans/2026-11-16-fit-unflagged-values.md`, revision 4).

Revision 5, after Dennis on revision 4 (`c2f08def6`, GO-WITH-FIXES, 0 blocker, 0 high). Every finding is taken.

| # | Finding | Change |
|---|---|---|
| M1 | `code_tails_at_k` over `(key, count)` was a second shape beside the fold's `(start, end, count)` | one function over the fold's own shape, `release_ranges_at_k`, codes the tails and then folds; `fold_year_bins` and `_floor_field` both call it; #649's `_kth_year` and inline clamp are deleted (4.3, 7a, 8, section 10 mutation, stop line 9) |
| M2 | no single statement of what an unflagged column may release | new umbrella guarantee P0; AT-11 asserts the date bounds against the K-th rows on random datetime frames; mutation "fold without coding" |
| M3 | AT-4 tail wording allowed a move that crosses the K-th row | "any of the 9 lowest rows to any earlier decade, or any of the 9 highest to any later decade"; the 200-row fixture puts its 9th and 10th lowest (and highest) rows in different decades |
| M4 | the 0.28.0 note had no owner | section 13: the orchestrator, as release owner, adds the line to the 0.28.0 notes before #647 merges |
| L1 | section 3 named the planned fold, not the shipped functions | shipped names; new tail-coding row (sdcMicro `topBotCoding`, Hundepool 3.4) |
| L2 | the Breaking fragment did not describe tail coding | it names the 10th earliest and 10th latest dated rows and the 19-row minimum |
| L3 | section 8 said 3 production files | 4, one line count that matches section 10 |
| L4 | no off-by-one mutation for the K-th row | "K-th row taken as (K-1)-th or (K+1)-th (AT-4, 19-row and 18-row cells)" |

Revision 4 (planner, 2026-11-17), a rebase onto what merged.

| # | What changed on main | Change to this plan |
|---|---|---|
| 1 | Row 24f E1 merged (engine #632, `f9cfef575`). It shipped the fold as `fold_ranges_under_k` and the word test as `labels_read_as_sentences` (with `FREETEXT_MIN_WORDS`), both named functions in `_snapshot_values.py`, plus `POLICY_REDACTED = "flagged-redacted/v2"` and `REDACTED_POLICIES` | the "extract if inline" branch is gone (4.3 shared helpers, stop line 9, section 13); E1b imports the two functions by name |
| 2 | E1a merged (engine #629): `_profile_document.py` holds the writer; the sentry reads it | E1a marked MERGED in section 10; no further E1a work |
| 3 | Row 24zp (engine #649, open at `385ad20bc`) bottom and top codes snapshot years at the K-th row from each end, because a folded outer range could still start at one row's year. This plan's P4 accepted exactly that ("an outer bucket edge can be the decade of one row") and AT-4 expected `1920s-2010s` from one 1921 row | V1 fix: P4, 4.3 steps 8 and 9, the section 5 `visit_date` row, AT-4, section 6 and the mutation list now code the decade tails at the K-th row. E1b extracts #649's tail coding into one named function and both writers call it (4.3). E1b depends on #649 merged |
| 4 | Engine 0.28.0 (#647, open) carries 24f E1 and so the v2 marker, but not E1b | Q4's window is now real: section 13 says what the CLI repin must do |
| 5 | Line counts moved: `_value_redaction.py` 486, `_profile_document.py` 76, `_snapshot_values.py` 552 (about 580 with #649) | section 8 sizes; stop line 4 adds the `_snapshot_values.py` limit; new "Ratchets touched" line in section 10 |

Round-cap fix (orchestrator, after Codex on `5a6d68570`): `is_table_sentinel` takes the flag's `count`, and an out-of-range `value` must equal `f"{count} value(s)"`; AT-14 gains the mismatch cell and the mutation list drops the count comparison.

Revision 3, after Codex on revision 2 (`bf8e1483f`, NO-GO). Every finding is taken.

| # | Finding | Change |
|---|---|---|
| 1 | V1: a null cell and a literal `(null)` cell both show as `(null)` (`profiler.py:94-105`), so the null count could prove a literal mode or label | the step 3 count map skips `(null)` as well as `[redacted]`; a `(null)` top-value entry proves no other slot (4.3 step 3); new AT-13: 999 nulls plus one literal `(null)` |
| 2 | V1 (orchestrator ruling): sentinels are kept only where `value` and `note` come from the fixed tables | verified against `sentinels.py` (section 1.1): every profiled `value` and `note` is table text or a count; new rule `SENTINEL_TABLE` keeps a sentinel only when `sentinels.py` matches it to its table, else the count floor (P6, 4.2, 4.3 step 10); new AT-14 and mutations |
| 3 | DESIGN: no `_placeholder_at` | `_apply` owns whole-slot and per-index decisions: a rules value may be `PlaceholderAt(indexes)` (4.2); the shared guard forbids any other placeholder write in both files (choke point) |

Revision 2, after Dennis round 1 on revision 1 (`334971cfb`). Every finding is taken.

| # | Finding | Change |
|---|---|---|
| 1 | HIGH: distribution bin counts are floats, so a strict int reader would fold nothing | one bin-count reading (finite float, `>= 0`, `is_integer()`), summed counts written back as floats (4.3 step 2, step 8); AT-11 adds the fixed-point property over random date frames |
| 2 | HIGH (design): `_floor_field` wrote null, `[redacted]` and `[]` itself, a second applier | `_floor_field` resolves each key to an `_apply` rule or a computed value and calls `_apply`; per-index replacement goes through `_apply` too (revision 3, finding 3); AT-10 points the forbidden-shape guard at `_profile_document.py`; mutation: an inline `field["mode_value"] = None` |
| 3 | MEDIUM: the free-text sample and count map could hold `[redacted]`, `(null)` and the aggregate; the fixed-point argument was loose | sample is the distinct kept labels without those three; the count map skips `[redacted]`; the argument is restated (4.3 step 5); AT-3 adds a heavily null column |
| 4 | MEDIUM: AT-1 fixture had 1,001 rows and relied on tie order; AT-2's 10-row and 9-row labels were not pinned in the top 5 | fixture counts fixed in sections 5 and 7 so the minimum has the largest count and both labels sit in the top 5 |
| 5 | MEDIUM: the AT-10 twin cannot build an unflagged `DetectorMatch` or pattern entry | those rows are covered by the flagged path; AT-10 asserts an entry with a `DetectorMatch` is flagged and tests the pattern and unknown-kind fallback on a loaded dict with empty `detector_matches` |
| 6 | V2-LOG: a mean plus released counts can reveal one outlier | recorded in section 15 |
| 7 | LOW: `Rule.KEEP` would reach `_apply`'s placeholder branch | `KEEP` is not a `Rule`; it is the frozenset `PROFILE_FLOOR_KEEP` (4.2); AT-10 checks the two tables are disjoint and cover `VALUE_FIELDS` |
| 8 | LOW: row 24f's 7b names `test_items_privacy.py` | section 13 and Q4 corrected; dependency note: no CLI release carries the 24f repin without 24zm C1 |
| 9 | LOW: a new `_count` duplicated the strict check | counts read through the existing `_conforms` (4.3 step 2) |
| 10 | LOW: a categorical share is `Distribution.data[i]`, not `TopValue.pct` | P2 and step 4 say so; a length mismatch between `data` and `labels` fails closed |
| 11 | LOW: AT-9 mutation wording | "apply steps 4 to 6 to bool columns" |

Bases: revision 3 read engine `902968682` and CLI `419572a`; revision 4 re-read the changed
parts at engine `origin/main` `8796ef691` and CLI `origin/main` `c558e2fb` (2026-11-17). Line
numbers in sections 1 and 6 are from the revision 3 base unless marked.

Owner decisions used: V1 bar (a leak of a non-admin value blocks V1); row 24zm is V1 and a fix to
an existing feature (owner 2026-11-16); "names may show in messages, data values never";
pre-release, so document output may change with a `Breaking:` line; the row 24f calls K = 10 and
the 3-word free-text rule (owner 2026-11-16), which this plan reuses and does not restate as new
decisions.

Risk: E1a is R1 (a private Move Function, no behaviour change). E1b is R2 (value-leak class,
changes the bytes of every plain profile document). C1 is R1 (CLI tests, docstring, help text,
docs). Full plan; plan review Dennis then Codex; E1b code gate Dennis and Codex; E1a and C1 Codex
only (`review-low`).

Dependency: row 24f's E0 (engine #609) and E1 (engine #632, `f9cfef575`) are merged. This row's
E1a is merged (engine #629). E1b waits for row 24zp (engine #649), which owns the year tail coding
that E1b shares (4.3).

## 1. Frame

### 1.1 Evidence

`profile_document` (`profiling/_value_redaction.py:473`) is `redact_profile_dict(profile.to_dict())`
(`:445-470`). That function redacts only the entries `_sensitive_entries` returns (`:306-319`),
which are the columns `is_value_sensitive` flags (`:290-303`: a detector hit, a PII score of 0.6
or more, or `is_likely_unique`). Every other column is the raw `to_dict()` entry. The value-bearing
slots of an unflagged column, all filled by `profiling/profiler.py` and `_distributions.py`:

| Slot | What it holds today | Source |
|---|---|---|
| `FieldStats.min_value`, `max_value` | the exact smallest and largest cell | `profiler.py:236-237` |
| `FieldStats.mean_value` | the mean, to 4 places | `profiler.py:238` |
| `FieldStats.date_min`, `date_max` | the exact earliest and latest timestamp | `profiler.py:242-243`, `_date_sniff.py:46-47` |
| `FieldStats.mode_value` | the most common value, even when 1 row holds it | `_classification.py:185-210` |
| `FieldStats.sample_invalid` | up to 3 raw cells that failed date parsing | `_date_sniff.py:49-50` |
| `TopValue.value` | the 5 most common values, a count of 1 included | `profiler.py:94-105` |
| `Distribution.labels` (categorical) | the 10 most common values as text | `_distributions.py:84-96` |
| `Distribution.labels` (numeric) | 10 equal-width bin edges from the exact min and max, so two edges give both extremes; a constant column's label is the cell | `_distributions.py:27-65` |
| `Distribution.labels` (date) | decades, a decade held by 1 row included | `_distributions.py:68-81` |
| `Distribution.min`, `max`, `mean` | exact numeric or date extremes and the mean | `_distributions.py:38-44`, `:78-79` |
| `SentinelFlag.value`, `note` | table text or a count, never the raw cell: date `value` is the table key's `isoformat()` and `note` the table text (`sentinels.py:196-202`); out-of-range `value` is `"<n> value(s)"` and `note` one of two fixed strings (`:206-216`); numeric `value` is the formatted table key and `note` the table text (`:233-239`); string `value` is the lowercased, stripped cell only when it is a member of `_STRING_SENTINELS`, so it equals the table member, and `note` is built from it (`:244-260`) | `sentinels.py:36-73`, `:196-260` |

The CLI writes this document in one place: `decoy demo` writes `scan.json` through
`profile_document` (CLI `src/decoy/cli/demo.py:163-167`). The `decoy.scan()` docstring tells
library users to save a profile the same way (CLI `src/decoy/api.py:684-688`). In the demo's
10-row sample, `gender` is unflagged with 5 rows per label, so `scan.json` stores `F` and `M` as
top values, mode and labels.

### 1.2 Root cause

The same as row 24f: the plain-document policy has one switch per column, flagged (withhold all)
or not flagged (keep all). Detection is a heuristic, so a column it misses keeps every cell. The
fix applies row 24f's floor (K = `MIN_RELEASE_COUNT`, `_value_redaction.py:58`) to every
unflagged column of the profile document, through one more table in the same registry.

One difference from row 24f decides the design: the snapshot writer has the frame, but a profile
document is built from `ColumnProfile` alone, and `redact_profile_dict` also takes a loaded
document. So every floor rule here reads only counts already in the document (top-value counts,
decade counts, rounded percentages, row and null counts). A slot whose safety needs the data (an
exact extreme with no count beside it) is withheld, not re-derived.

## 2. Guarantee

For a document written by `profile_document(profile)` or `redact_profile_dict(doc)` with
`include_values=False`, every column that `is_value_sensitive` does not flag ("unflagged") gets
the floor:

- P0. Every value-bearing slot an unflagged column releases is one of: a text proven by a count
  in the same document to be held by at least K rows; a date range whose buckets each hold at least
  K rows and whose outer edges are the decades of the K-th lowest and K-th highest dated rows; a
  sentinel kept by P6; or an aggregate over at least 2K non-null cells. Anything else is replaced.
  P1 to P7 are the cases of this rule.
- P1. Every text a document releases as a top value, a mode, a categorical label or a numeric
  bound is held by at least K source rows, as proven by a count in the same document. Text the
  document cannot prove is replaced (`[redacted]` in a list slot, `null` in a scalar slot). Bool
  columns (`inferred_type: boolean`) are exempt, as in row 24f G1.
- P2. A categorical label without an exact top-value count is kept only when the lower end of its
  rounded share, `(data[i] - 0.05) / 100 * row_count`, is at least K. `data[i]` is the
  `Distribution.data` entry at the label's own index (the builder writes the two lists in step,
  `_distributions.py:89-96`). When `data` and `labels` differ in length, every label is
  `[redacted]`. The trailing `other` aggregate label (`_distributions.py:93-95`) is kept.
- P3. Numeric distribution labels are `[redacted]` (bin counts stay), and the distribution `min`
  and `max` are `null`. `mean_value` and the numeric distribution `mean` are kept only when the
  column has at least 2K non-null cells, the row 24f rule for `mean`.
- P4. Date decade buckets are bottom and top coded, then folded, as row 24zp does for snapshot
  years. Every bucket below the one that holds the K-th lowest dated row is counted into that
  bucket, and likewise above the K-th highest, so no released edge is the decade of one of the K-1
  rows at either end. Then row 24f's contiguous fold merges buckets until each holds at least K
  rows. A merged label is `1990s-2010s`. `date_min` and `date_max` and the date distribution
  `min` and `max` become the first and last day of the outer buckets. A column whose decades total
  fewer than K rows, whose two K-th buckets cross (fewer than 2K-1 dated rows can do this), or that
  has no date distribution, has `[redacted]` labels and `null` bounds.
- P5. A column whose released labels read as sentences (row 24f's 3-word median test, applied to
  the labels P1 and P2 keep) releases no label, mode or bound text.
- P6. `sample_invalid` is empty. A sentinel's `value` and `note` are kept only when
  `sentinels.py` matches the pair to its fixed table for that `kind` (the table text, never the raw
  cell). Every profiled sentinel matches (section 1.1). A pair that does not match, which only a
  loaded document can hold, goes through the count floor: kept when the flag's own `count` is at
  least K, else both slots are replaced.
- P7. A key that no profile type declares, or a value-free key with the wrong type, is replaced
  inside an unflagged column, as it is today inside a flagged one (`_value_redaction.py:445-470`,
  the default-deny at `:461`).
- P8. `include_values=True` output is byte-identical to today. Flagged columns are handled as
  today. `redacted_columns` still lists the flagged names only. `value_policy` is the marker row
  24f E1 defines (`flagged-redacted/v2`).
- P9. `redact_profile_dict` stays a fixed point: a second pass changes nothing.

Non-goals (V1): a hand-edited or hostile loaded document (sentinel text, counts that lie; the V1
threat model covers accidental leaks only); `mean_value` arithmetic that isolates one outlier when
the other cells are known (an aggregate, as row 24f keeps it; V2-LOG, section 15); free-text length statistics; the
in-memory `ColumnProfile` that `decoy.scan()` returns (it holds values by design and its docstring
says so); the value-free `scan-set/v1` core that `decoy scan --output` writes (already value-free,
`scan_set.py:528`).

## 3. Established solutions

Search run: SDC handbook and sdcMicro (already cited in `_value_redaction.py:16-21`),
ydata-profiling sensitive mode, Google Cloud DLP inspect findings, CMS cell-size policy; in the
codebase, the value registry, row 24f's floor, the numeric shape release floor.

| Source | What it does | Used here |
|---|---|---|
| Hundepool et al., Statistical Disclosure Control (Wiley 2012), 4.2 threshold rule; 3.4 global recoding | A released cell needs a minimum frequency; recode to coarser intervals | K floor on every released label; decade fold |
| CMS cell-size suppression policy | Suppresses published cells under 11 | Supports K = 10 |
| ydata-profiling `sensitive=True` ([docs](https://docs.profiling.ydata.ai/latest/features/sensitive_data/)) | A shareable profile hides value counts, samples and extreme values for every column, not only detected ones | The scope of the fix: every column of a shared profile; extremes withheld when unprovable |
| Google Cloud DLP `include_quote` (cited at `_value_redaction.py:10-13`) | Findings omit the quote unless asked | Default-deny; `include_values=True` is the one opt-in |
| R sdcMicro `globalRecode` | Recode values into intervals | The decade fold |
| R sdcMicro `topBotCoding`; Hundepool et al. (2012) section 3.4 | Values beyond a threshold are recoded to the threshold | Tail coding at the K-th row from each end, as row 24zp does for snapshot years (`release_ranges_at_k`) |
| Row 24f E1 (engine #632) | `fold_ranges_under_k` contiguous fold; `labels_read_as_sentences` with `FREETEXT_MIN_WORDS` | Reused by name, not restated |

Rounded percentages as count bounds: a percentage rounded to 0.1 bounds the count to within
0.05 percent of the rows. No surveyed tool releases a label from a rounded share; the lower-bound
test in P2 is our own fail-closed reading of the existing field.

## 4. Design

Design notes: one more table joins the existing value registry, and the profile writer applies
it. The writer moves to its own module first (E1a, Fowler "Move Function") because
`_value_redaction.py` is 475 lines, row 24f E1 adds about 25, and the floor appliers would take it
past the 600-line aim; a census entry is not allowed. The registry module keeps the tables,
`Rule`, `_apply`, the type walk and the predicate. The writer module sits beside
`_snapshot_values.py`, which already is the snapshot writer over the same registry: one registry,
one writer module per document type. Same package, so no new cross-package private import (defect
class 6).

Choke point: `redact_profile_dict` is the one plain profile writer (`profile_document` calls it).
After E1b it calls `_floor_field` on every unflagged entry, and `_floor_field` changes a slot only
through `_apply` (a rule) or by assigning a value it computed from counts (a folded label list,
summed bin counts, a decade edge, as `_year_edge` does for the snapshot,
`_snapshot_values.py:109-116`). It never writes `null`, `[redacted]` or `[]` itself. Guards:
- the existing sentry `test_the_profile_redactor_uses_the_same_selection_stamp_and_applier`
  (`tests/sentry/profiling/test_snapshot_value_registry.py:378-385`) moves to the new path and
  also requires `_floor_field` in `redact_profile_dict`;
- the forbidden-shape guard `_guard_findings` (`test_snapshot_value_registry.py:245-277`) also
  scans `_profile_document.py`. The profile writer's placeholder is `REDACTED`, the `_apply`
  default, so the sentry splits the guard into the shared shape checks (both files) and the
  snapshot-only "`_apply` without `denied_value=None`" check. No check is dropped for the snapshot
  file;
- a registry sentry requires every `VALUE_FIELDS` pair (per distribution kind) to be in exactly
  one of `PROFILE_FLOOR_FIELDS` and `PROFILE_FLOOR_KEEP`.

Placeholder writes have one owner, `_apply`. The shared guard checks, run on `_profile_document.py`
and `_snapshot_values.py`, flag a subscript assignment of `None`, `REDACTED`, `{}` or `[]`, and any
use of the name `REDACTED` or the text `[redacted]` other than as an operand of a comparison or
membership test (so `[REDACTED] * n` and `labels[i] = REDACTED` are both caught). Neither file
holds such a write at the base.

Mutations that must turn them red: delete the `_floor_field` call; delete one
`PROFILE_FLOOR_FIELDS` row; write `field["mode_value"] = None` inline in `_floor_field`; replace
one label with `labels[i] = REDACTED` in `_floor_field`. The CLI
sentry `tests/sentry/io_policy/test_profile_document_route.py` already refuses a raw `to_dict()`
write.

### 4.1 E1a: move the profile writer

`redact_profile_dict`, `profile_document` and `_detached` move from `_value_redaction.py` to
`profiling/_profile_document.py`, unchanged. The new module imports `_apply`, `_shape_keep`,
`_shapes`, `_sensitive_entries`, `_redact_field` and `stamp_value_policy` from the registry.
`profiling/__init__.py` re-exports from the new module; `decoy_engine.profile_document` and
`decoy_engine.redact_profile_dict` keep their public paths. The registry module docstring, the
CODEMAP profiling row and the sentry path change with it. About 50 lines move.

### 4.2 E1b: registry

`_value_redaction.py` gains two tables, keyed like `VALUE_FIELDS`, with the distribution keyed
per kind (`Distribution.<kind>`):

- `PROFILE_FLOOR_FIELDS`, the rule for each value slot of an unflagged column. New `Rule`
  members join the one enum: `HELD_BY_K`, `UNDER_K_PLACEHOLDER`, `AGGREGATE_2K`, `FOLD_DECADES`,
  `DECADE_START`, `DECADE_END`, `SENTINEL_TABLE`. All seven join `DATA_RULES`: `_floor_field`
  resolves them to an existing `_apply` rule or a computed value, and `_apply` never receives them.
- `PROFILE_FLOOR_KEEP`, a frozenset of the value slots an unflagged column keeps unchanged. It is
  not a `Rule`, so nothing can route it to `_apply`'s placeholder branch.

| Type, field | Floor |
|---|---|
| `FieldStats` `min_value`, `max_value`, `mode_value` | `HELD_BY_K` |
| `FieldStats` `mean_value` | `AGGREGATE_2K` |
| `FieldStats` `date_min` / `date_max` | `DECADE_START` / `DECADE_END` |
| `FieldStats` `sample_invalid`, `DetectorMatch` `sample_misses` | `EMPTY_LIST` |
| `TopValue` `value` | `UNDER_K_PLACEHOLDER` |
| `Distribution.categorical` `labels` | `UNDER_K_PLACEHOLDER` |
| `Distribution.numeric` `labels` / `min`, `max` / `mean` | `PLACEHOLDER_EACH` / `NULL` / `AGGREGATE_2K` |
| `Distribution.date` `labels` / `min` / `max` | `FOLD_DECADES` / `DECADE_START` / `DECADE_END` |
| `Distribution.pattern` (any field) | the `VALUE_FIELDS` rule |
| `Distribution.freetext` `labels`, `min`, `max`, `mean` | `PROFILE_FLOOR_KEEP` (length buckets and length statistics) |
| `SentinelFlag` `value`, `note` | `SENTINEL_TABLE` (P6) |

A distribution `kind` outside the five gets the `VALUE_FIELDS` rules (fail closed). The
`DetectorMatch` and `Distribution.pattern` rows exist for completeness: a profiled column holds
either only when a detector fired, and a detector hit flags the column (`_value_redaction.py:290-303`),
so the flagged path covers them. They matter only for a loaded document.

`_apply` owns per-index decisions too. A value in its `rules` mapping may be a `Rule` or
`PlaceholderAt(indexes: frozenset[int])`, a frozen dataclass in `_value_redaction.py`. With
`PlaceholderAt`, `_apply` replaces the listed entries of a list slot and leaves the others; a
slot that is not a list is replaced whole (fail closed). Existing callers pass only `Rule`
values, so their behaviour is unchanged. There is no other placeholder writer.

`sentinels.py` gains `is_table_sentinel(kind, value, note, count) -> bool`, built from the same four
tables and the same formatting the scanners use. The string note and the numeric value text move
to one helper each (`_string_note`, `_numeric_text`), and the two out-of-range notes become named
constants, so the scanners and the check share one source (Fowler "Extract Function"). The
out-of-range `value` must equal `f"{count} value(s)"` for the flag's own `count` (a strict int at least 1, read through `_conforms`), so a loaded flag cannot carry a stored count text that its count does not produce.

### 4.3 E1b: rules (all in `_profile_document.py`)

`_floor_field(field)` runs on one unflagged entry. It reads a copy taken before any change, works
out a decision per slot, then applies all decisions through `_apply` or a
computed assignment. Every replacement goes through `_apply` (a `Rule` or a `PlaceholderAt`):

1. Default-deny keys (P7): reuse `_field_plan` containers with a keep test that admits the
   type's value-free shapes (`_shape_keep`) and its `VALUE_FIELDS` names.
2. Counts, through the existing strict predicate `_conforms` (`_value_redaction.py:214-236`), no
   new reader. A top-value count, `row_count` or `null_count` proves something only when
   `_conforms(x, int)` and `x >= 0` (a bool or string fails, defect class 2). A distribution bin
   count is written as a float (`_distributions.py:77`, `types.py:46`), so it proves something only
   when `_conforms(x, float)`, `x >= 0` and `x.is_integer()`. A share `data[i]` proves something
   only when `_conforms(x, float)` and `x >= 0`. A value that fails proves nothing. `n` is
   `row_count - null_count`.
3. Proven counts by text: from `top_values`, `{value: count}`, keeping the larger count if a text
   repeats. An entry whose text is `REDACTED` or the null marker `(null)` is skipped. The profiler
   writes a null cell and a literal `(null)` cell the same way (`profiler.py:94-105`), so the
   null count must never prove a mode, bound or label that reads `(null)`. A `(null)` top-value
   entry is still judged in step 4 by its own count, like any other entry.
4. `UNDER_K_PLACEHOLDER`: a top value is kept when its own count is at least K. A categorical
   label is kept when its proven count is at least K, or, with no proven count, when the P2 lower
   bound on `data[i]` is at least K. The bound uses `Decimal(repr(x))`, so float error cannot
   round it up. The label at index 10 of an 11-label list, when it reads `other`, is the
   aggregate and is kept. When `len(data) != len(labels)`, every label is replaced. The 0.05
   margin is one named constant beside the categorical builder's rounding in `_distributions.py`
   (the forbidden-shape guard bans a float literal from 0 to 1 in `_profile_document.py`).
   Label replacements are one `PlaceholderAt` per list.
5. Free text (P5). The sample is the distinct texts step 4 keeps, from top values and categorical
   labels, without `REDACTED`, the `(null)` marker (`profiler.py:100`) and the trailing aggregate.
   An empty sample is not free text. If row 24f's word-count test says the sample reads as
   sentences, every top value and categorical label is replaced (`PlaceholderAt` over all
   indexes) and `mode_value`, `min_value`, `max_value` resolve to `NULL`.
   Fixed point: on a second pass the counts are unchanged and step 3 skips placeholders, so step 4
   keeps exactly the texts the first pass kept. If the first pass found free text, nothing is kept,
   the sample is empty and every slot is already replaced. If it did not, the sample is the same
   set, so the verdict is the same.
6. `HELD_BY_K`: the scalar text is kept when step 3 proves at least K rows hold that exact text,
   else it resolves to `NULL`. The profiler writes both through `str()` of the same pandas scalar,
   so a numeric `min_value` held by K rows and present in the top 5 survives; any other bound is
   `null`.
7. `AGGREGATE_2K`: kept when `n >= 2 * K`, else `NULL`.
8. `FOLD_DECADES`: parse each label with `re.fullmatch(r"(\d{4})s(?:-(\d{4})s)?", label)`
   (defect class 1; the second form makes a second pass a no-op). Ranges must be ordered and
   non-overlapping, and `len(data) == len(labels)`. Then pass the parsed `(start, end, count)`
   ranges, with decade years (`end` is the end decade plus 9), to `release_ranges_at_k` (below).
   It counts every range before the one holding the K-th lowest row into that range, which keeps
   its own edges, and likewise after the K-th highest, then folds with `fold_ranges_under_k`. It
   returns `[]` when the total is under K or the two K-th ranges cross. On a second pass the
   outer ranges already hold K rows, so nothing changes. The computed
   `labels` and `data` are assigned; `data` holds the summed counts as floats, so `_conforms` still
   accepts them and a second pass reads the same numbers. If a label does not parse, a bin count
   fails step 2, or `release_ranges_at_k` returns `[]`, `labels` resolves to
   `PLACEHOLDER_EACH` and the date bounds to `NULL`.
9. `DECADE_START` / `DECADE_END`: computed from the coded and folded first and last range,
   `YYYY-01-01T00:00:00` and `YYYY-12-31T23:59:59.999999` for `FieldStats` (`YYYY` is the start
   decade, or the end decade plus 9), and `YYYY-01-01` / `YYYY-12-31` for the distribution. With
   no date distribution, or a fold that failed, `NULL`.
10. `SENTINEL_TABLE`: for each sentinel flag, `value` and `note` are kept when
    `is_table_sentinel(kind, value, note, count)` holds. Otherwise both are kept only when the flag's own
    `count` passes step 2 and is at least K; else both resolve to `PLACEHOLDER`. `kind` and
    `count` are value-free shapes and stay.
11. Bool columns skip steps 4 to 6 (P1).

Shared helpers, one owner each, all in `_snapshot_values.py`: `labels_read_as_sentences` (the
word test, row 24f E1), `fold_ranges_under_k` (the contiguous fold, row 24f E1) and the tail
coder. Row 24zp (#649) writes the tail coding inline in `fold_year_bins`, with a private
`_kth_year` and an inline clamp. E1b replaces both with one function over the fold's own shape,
`release_ranges_at_k(ranges: Sequence[tuple[int, int, int | float]]) -> list[tuple[int, int, int | float]]`:
it codes the tails at the K-th row from each end, then calls `fold_ranges_under_k`, and returns
`[]` when the total is under K or the K-th ranges cross (Fowler "Extract Function", no new file).
`fold_year_bins` passes `(y, y, c)` after its `MAX_SAMPLED_YEAR` clamp; `_floor_field` passes the
parsed decade ranges. `_kth_year` and the inline clamp are deleted, not left beside it, and
#649's tests stay green unchanged. The 3-word threshold and K are
never restated. `_profile_document.py` imports the three by name from the same package; the
package `__init__` already imports both modules, so no import cycle is added (E1b checks
`tests/unit/test_public_api.py` and import layers).

### 4.4 Marker

No new marker. Row 24f E1 changes the shared `POLICY_REDACTED` to `flagged-redacted/v2` ("every
other column is floored at K"). `stamp_value_policy` (`_value_redaction.py:331-340`) writes that
constant for profile documents too, so after 24f E1 merges a profile document carries v2 while its
unflagged columns are not yet floored. E1b makes the marker true. Q4 covers the window.

## 5. Behaviour

Fixture: the floor frame in AT-1 (1,000 rows); the demo sample (10 rows).

| Column | Today | After |
|---|---|---|
| `salary`: its minimum held by 59 rows, 47 other round values of 20 rows each, and one row 987,654 (1,000 rows) | `max_value: "987654"`; bin edges from 987,654 | `max_value: null`; `min_value` kept (its 59 rows, the largest count, show in the top values); labels `[redacted]`, counts kept; `mean_value` kept |
| `diagnosis`: labels of 400, 300, 280, 10 and 9 rows, and `ZXQ-RARE-LABEL` x1 | the label in `distribution.labels` | `[redacted]` in that slot; the 9-row label `[redacted]`, the 10-row label kept |
| `note`, 30 three-word strings, about 33 rows each | all 10 labels, 5 top values and the mode stored | every label and top value `[redacted]`, mode `null` |
| `tier` (A, B, C, each over 10 rows) | stored | stored |
| `region` (`New York`, `San Diego`, each over 10 rows) | stored | stored (2 words, not free text) |
| `comment`: 900 nulls and 10 three-word strings of 10 rows each | `(null)` and four strings in the top values; the strings in the labels | every string `[redacted]`, mode `null`; `(null)` does not count as a 1-word label |
| `is_active` bool with one `False` | stored | stored (bool exempt) |
| `visit_date`, one 1921 row, the rest 2015 to 2024 | `date_min` the exact 1921 timestamp; label `1920s` with count 1 | the 1920s row is counted into `2010s`; labels `2010s`, `2020s`; `date_min` `2010-01-01T00:00:00`; no `1920` anywhere in the column |
| demo `gender` (F and M, 5 rows each) | `F` and `M` in top values, mode and labels | `[redacted]`, mode `null`, counts kept |
| any column with `include_values=True` | raw | raw, byte-identical |
| any flagged column | redacted | redacted, unchanged |

Cost: a person reading `scan.json` loses labels under 10 rows, numeric ranges and exact dates.
Counts, null rates, types, detector results and re-identification facts do not change. The
in-memory `ColumnProfile` and every engine consumer of it (starter config, recommendations,
masking choosers) do not change: they never read the document.

## 6. Failure modes

| Case | Behaviour |
|---|---|
| A count that is a bool, string, float or negative | proves nothing; the text it would prove is replaced |
| `top_values` missing or not a list | no proven counts; mode and bounds `null`; labels fall to the P2 bound |
| `pct` NaN, infinite or not a number | proves nothing |
| Label exactly at K rows | kept (`>=`) |
| A real category named `other` inside the top 10 | judged like any label; only the 11th-of-11 `other` is the aggregate |
| Decade label off the grammar, out of order or overlapping | all date labels `[redacted]`, date bounds `null` |
| Date column with fewer than K dated rows | all date labels `[redacted]`, bounds `null` |
| Date column whose K-th lowest and K-th highest buckets cross (under 2K-1 dated rows) | all date labels `[redacted]`, bounds `null` |
| One far-out dated row (a 1921 visit among 2015 to 2024) | counted into the bucket of the K-th lowest row; its decade appears nowhere |
| String date column (sniffed, no date distribution) | `date_min`, `date_max` `null` |
| Constant numeric column | its one label `[redacted]`; `min_value` kept only when the top values prove K rows |
| Distribution `kind` unknown | flagged rules |
| Unknown key inside an unflagged column | `[redacted]` (P7) |
| `fields` not a list, or an entry not a mapping | unchanged: the entry is flagged by the fail-closed predicate (`_value_redaction.py:296-297`) |
| Second pass over a floored document | no change (P9) |
| Labels that read as sentences only after the floor | the test runs on the kept labels, so they are withheld in the first pass |

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | every unflagged slot of a plain profile document | `PROFILE_FLOOR_FIELDS` in the one registry, applied by `_floor_field` inside the one writer | AT-1 to AT-5, AT-10 | delete the `_floor_field` call |
| 2 | Cleanup missing on an exit path | none | N/A: pure functions over an in-memory dict; nothing opened, staged or leased | n/a | n/a |
| 3 | State machine and concurrency | none | N/A: no shared state, cache or lock is added | n/a | n/a |
| 4 | Route parity and silent fallback | `profile_document`, `redact_profile_dict`, `decoy demo`, the `decoy.scan()` save advice | one writer; `profile_document` calls `redact_profile_dict`; the CLI route sentry refuses a raw `to_dict()` | AT-7, AT-C1, AT-C2 | make `profile_document` build its own dict |
| 5 | Referential integrity | mode and bounds proven by top-value counts | proof by exact text match inside the same entry, read before any replacement | AT-1, AT-6 | read `top_values` after the placeholder step |
| 6 | Untrusted producer | a loaded document with ill-typed counts or keys | counts through `_conforms` (bin counts also `is_integer()`); default-deny keys; fixed label grammar with `fullmatch` | AT-6 | accept `isinstance(x, int)` (a bool passes) |
| 7 | Check then use (TOCTOU) | none | N/A: no file read; the caller owns the dict and the writer copies it first | n/a | n/a |
| 8 | Weak tests | a floor test that passes on a frame with no rare cell | each canary test first asserts the canary is in the raw `to_dict()` and the column is unflagged | AT-1 to AT-5 non-vacuity lines | build the AT-1 frame without the rare row |
| 9 | Refactor drift | E1a move; flagged columns; `include_values=True` | E1a moves code unchanged; flagged and raw paths untouched | existing `test_value_redaction.py`, AT-8 | change a flagged rule in E1a |
| 10 | Frozen contract drift | `profile_document` and `redact_profile_dict` output | `Breaking:` line; signature and public paths unchanged | AT-8, section 9 | change the public export path in E1a |

### 6.2 Enumerations

#### Exit paths

- No new exit or error. `redact_profile_dict` keeps its two `TypeError` refusals
  (`_value_redaction.py:445-458`); the floor never raises, it replaces.
- `decoy demo` keeps exit 0 and its counts-only output (CLI `src/decoy/cli/demo.py:172-210`).

#### Routes

- `profile_document`, `profiling/_value_redaction.py:473` (moves in E1a).
- `redact_profile_dict` on a loaded document, `profiling/_value_redaction.py:445`; no CLI caller
  today (CLI `git grep` at `419572a`).
- `decoy demo`, CLI `src/decoy/cli/demo.py:163-167`, the one CLI writer.
- `decoy.scan()`, CLI `src/decoy/api.py:653-727`: returns the in-memory profile; its docstring
  names `profile_document` as the way to save it.
- Not routes for this document: `decoy scan --output` (value-free `scan-set/v1` core,
  `profiling/scan_set.py:528`), `scan show` on a legacy file (CLI `src/decoy/cli/io/_scan_set.py`
  reads counts only), and `distribution_snapshot_document`, which reads only
  `value_sensitive_names` (`profiling/_snapshot_values.py:264`).

#### FK shapes

- N/A: the floor reads one column entry at a time and never a key relationship.

#### Fields

- Every `VALUE_FIELDS` pair (`_value_redaction.py:60-80`) gets a floor rule (4.2), the
  distribution per kind.
- `VALUE_FREE_FIELDS`, the type walk (`_value_redaction.py:243-283`) and the
  `ColumnProfile` shape do not change.

#### Output surfaces

- The `profile_document` / `redact_profile_dict` return value.
- `scan.json` from `decoy demo`.
- `decoy demo` stdout and `--json`: counts only (`pii_columns`, rows), unchanged.

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Floor constant | `MIN_RELEASE_COUNT` | no |
| Unflagged selection | `_sensitive_entries`, `is_value_sensitive` | no |
| Default-deny keys | `_field_plan`, `_containers`, `_shape_keep`, `_shapes` | no |
| Rule enum, flagged applier | `Rule`, `_apply` | seven members; `_apply` also accepts `PlaceholderAt` |
| Sentinel tables | `sentinels.py` tables and scanners | `is_table_sentinel` and two extracted formatters |
| Strict count test | `_conforms` | no |
| Forbidden-shape guard | `_guard_findings` | shared checks split from the snapshot-only one |
| Marker | `stamp_value_policy`, `POLICY_REDACTED` (v2 from row 24f E1) | no |
| Contiguous fold | `fold_ranges_under_k` (row 24f E1) | no |
| Free-text test | `labels_read_as_sentences` (row 24f E1) | no |
| Tail coding and fold | row 24zp's coding in `fold_year_bins` (#649) and `fold_ranges_under_k` | coding moved into `release_ranges_at_k`, which calls the fold; `_kth_year` and the inline clamp deleted (4.3) |
| Placeholder | `REDACTED` | no |

## 7. Acceptance tests, red first

Engine E1b, in `tests/unit/profiling/test_profile_floor.py` (new) unless named. The floor frame is
built in the test (1,000 rows, seed 31, the columns of section 5); every column it names is
asserted unflagged first.

| # | Test | Fail before |
|---|---|---|
| AT-1 | `salary` (counts in section 5; the minimum's 59 rows are the strictly largest count, so no tie decides its place in the top 5): the raw `to_dict()` has `max_value "987654"`; the document has `max_value` null, `min_value` equal to the raw text (held by 59 rows), numeric labels all `[redacted]` with `data` unchanged, distribution `min` and `max` null, `mean_value` kept; `987654` is not in the JSON text. A 15-row numeric column has `mean_value` null | exact max and edges stored |
| AT-2 | `diagnosis`: `ZXQ-RARE-LABEL` is in the raw labels and not in the document JSON; every kept top value and label is held by at least K rows of the frame; the 10-row and 9-row labels are first asserted to be in the raw top 5 (so each has an exact count), then the 10-row label is kept and the 9-row label is `[redacted]` | count-1 label stored |
| AT-3 | `note`: no note string in the JSON; mode null; every label `[redacted]`. `comment` (heavily null): no comment string in the JSON, mode null; the raw top values hold `(null)` first, so the test fails if `(null)` joins the sample. `region` keeps both 2-word labels | all strings stored |
| AT-4 | `visit_date`: labels `2010s` and `2020s`, every count at least K, the sum unchanged (the 1921 row counted in `2010s`); `date_min` `2010-01-01T00:00:00`, `date_max` `2029-12-31T23:59:59.999999`; neither `1921` nor `1920` is in the column's JSON. Tail property on a 200-row date column whose 9th and 10th lowest rows sit in different decades, and whose 9th and 10th highest rows do too: moving any of the 9 lowest rows to any earlier decade, or any of the 9 highest to any later decade, leaves labels and bounds unchanged. A loaded dict with decades `1950s: 9`, `1990s: 1`, `2000s: 9` (19 rows) is coded to one range; with `1950s: 9`, `2000s: 9` (18 rows, the K-th buckets cross) every label is `[redacted]` and the bounds null. A 5-row date column: labels `[redacted]`, bounds null. A string date column: bounds null | raw decades and exact timestamps stored; an outer edge at one row's decade |
| AT-5 | dict cells through `redact_profile_dict` (row_count 1,000): a label outside the top values whose share `data[i]` is `1.0` (bound 9.5) is `[redacted]`, `1.1` (bound 10.5) is kept; the label reads its own index of `data`, not a `TopValue.pct`; the 11th `other` is kept; a real `other` at index 3 with share `0.1` is `[redacted]`; a share NaN or `"5.0"` is `[redacted]` | labels kept regardless of share |
| AT-6 | fail closed: top-value counts as `True`, `"20"`, `20.0` or `-1` prove nothing; date bin counts as `True`, `20`, `2.5`, NaN or `-1.0` prove nothing; categorical `data` shorter than `labels` redacts every label; `top_values` missing; a decade label `1920s ` (trailing space), `1920s\n`, out of order or overlapping; an unknown distribution kind; an unknown key in an unflagged entry. Each yields the replacement in section 6 | ill-typed counts and keys pass through |
| AT-7 | `redact_profile_dict(redact_profile_dict(raw)) == redact_profile_dict(raw)` on the floor frame and on the case "two 1-word labels under K, one 3-word label over K"; the input dict is not mutated; `profile_document(p) == redact_profile_dict(p.to_dict())` | the free-text case flips on a second pass if the test reads all labels |
| AT-8 | `include_values=True` equals `to_dict()` plus the two keys on the floor frame (existing `test_include_values_is_to_dict_plus_the_two_keys` extended); flagged columns of the existing canary fixture are byte-identical to the pre-change document | not fail-before: pins what must not change |
| AT-9 | guards that stay green: `is_active` keeps its count-1 `False`; profiled sentinels of unflagged columns keep `value` and `note`; `test_a_column_that_is_not_value_sensitive_keeps_its_values` unchanged | not fail-before |
| AT-10 | sentry (`tests/sentry/profiling/test_profile_value_registry.py`): every `VALUE_FIELDS` pair, for each of the five kinds, is in exactly one of `PROFILE_FLOOR_FIELDS` and `PROFILE_FLOOR_KEEP`, and nothing else is; every `PROFILE_FLOOR_FIELDS` value is a `Rule`; `PROFILE_FLOOR_KEEP` is exactly the freetext slots of 4.2, and the sentinel slots map to `SENTINEL_TABLE`. `test_every_value_rule_is_applied` gains a twin that builds an unflagged canary entry (count 1, no detector) and asserts each floor rule removes it. The twin cannot build an unflagged `DetectorMatch` or `Distribution.pattern` entry, so it asserts instead that a profiled entry with a `DetectorMatch` is flagged, and tests the pattern rows and the unknown-kind fallback on a loaded dict with `detector_matches: []`. `test_snapshot_value_registry.py` runs the shared `_guard_findings` checks on `_profile_document.py` | unflagged canaries survive |
| AT-11 | property (hypothesis): random string, integer, datetime and bool frames; for every unflagged column of the document, each released top value, label, mode and numeric bound is held by at least K rows of the frame, and each date bucket count is at least K. On random datetime frames, `redact_profile_dict(redact_profile_dict(raw)) == redact_profile_dict(raw)` and the folded `data` entries are floats; with N dated rows, `date_min` and the distribution `min` are the first day of the decade of the K-th lowest row and `date_max` and `max` the last day of the decade of the K-th highest row, or all four are null when N < 2K-1 | fails on the first count-1 label; the fixed point fails if summed counts are written as ints; the bounds fail on a fold without coding |
| AT-12 | the demo's 10-row sample through `profile_document`: `gender` labels and top values `[redacted]`, mode null; `redacted_columns` unchanged; no exception | `F`, `M` stored |
| AT-13 | `nullish`: 999 null cells and one literal `(null)` cell (1,000 rows). Non-vacuity: the raw `to_dict()` has `mode_value "(null)"` and a top-value entry `(null)` with count 1. The document has `mode_value`, `min_value` and `max_value` null, no categorical label `(null)`, and the count-1 top-value entry `[redacted]`; the only `(null)` left in the column is the top-value entry with count 999, the null marker | the null count proves the literal mode |
| AT-14 | sentinels. Profiled: a frame where one row holds ` N/A ` and one row holds `-999`; the flags read `value "n/a"` and `"-999"` with their table notes and `is_table_sentinel` holds for each; the text ` N/A ` and `N/A` is not in the JSON. Loaded dict: a `string_sentinel` flag with `value "Jane Q Example"`, a free-form note and count 1 has both slots `[redacted]`; the same flag with count 12 keeps them; a table `value` with a changed note is floored Loaded out-of-range mismatch: a `date_out_of_range` flag with `count: 1`, a fixed note and `value: "12 value(s)"` is floored (both slots `[redacted]`), while `value: "1 value(s)"` with `count: 1` is kept. | a loaded raw sentinel text is stored |

Mutations that must turn a test red: delete the `_floor_field` call (AT-1 to AT-4); delete one
`PROFILE_FLOOR_FIELDS` row (AT-10); `>` instead of `>=` K (AT-2); read label counts from `pct`
only (AT-9, the existing status test); drop the `- 0.05` margin (AT-5); treat the 11th `other` as
a label (AT-5); skip the free-text step (AT-3); run it on all labels (AT-7); let `(null)` join the
free-text sample (AT-3 `comment`); apply steps 4 to 6 to bool columns (AT-9); leave a short final
decade unmerged (AT-4); skip the tail coder or code only the low tail (AT-4 tail property);
release ranges when the K-th buckets cross (AT-4, 18-row dict); fold without coding (AT-11 date
bounds); K-th row taken as (K-1)-th or (K+1)-th (AT-4, 19-row and 18-row cells); `isinstance` for counts (AT-6); read bin counts with the int test (AT-4,
AT-11); write summed bin counts as ints (AT-11); ignore a `data`/`labels` length mismatch (AT-6);
`match` for the decade grammar (AT-6); read `top_values` after replacement (AT-1 `min_value`);
write `field["mode_value"] = None` inline in `_floor_field` (AT-10 guard); let `(null)` into the
step 3 count map (AT-13); keep sentinel slots without `is_table_sentinel` (AT-14, loaded dict); drop the `count` comparison for out-of-range values (AT-14 mismatch cell);
write the string sentinel `value` from the raw cell instead of the normalized table member (AT-14,
profiled); floor flagged or raw
output (AT-8).

E1a: no new test. The existing suite and the moved sentry stay green; `git diff -M` shows the
three functions moved unchanged.

CLI C1, after the engine release that carries E1b:

| # | Test | Fail before |
|---|---|---|
| AT-C1 | `decoy demo`: in `scan.json`, `gender` is not in `redacted_columns`; its top values and labels are `[redacted]` and its mode is null; `value_policy` is `flagged-redacted/v2`; the existing redacted-column checks hold (`tests/e2e/first_user/test_items_privacy.py`) | `F` and `M` stored |
| AT-C2 | `decoy.scan(df)` on a frame with an unflagged label held by 1 row, then `decoy_engine.profile_document`: the label is absent from the JSON; the in-memory profile still holds it (the docstring's stated split) | label stored |

### 7b. Existing tests that change

Engine: `tests/sentry/profiling/test_snapshot_value_registry.py::test_the_profile_redactor_uses_the_same_selection_stamp_and_applier`
reads `_profile_document.py` (E1a) and also requires `_floor_field` (E1b). Any test importing
`redact_profile_dict` or `profile_document` from `_value_redaction` follows the move (none at the
base; they import from `decoy_engine.profiling`). `tests/unit/profiling/test_value_redaction.py`
gains the AT-8 and AT-9 cells; no assertion is weakened.

CLI: `test_c1_demo_scan_file_redacts_sensitive_values` in `tests/e2e/first_user/test_items_privacy.py`
asserts `flagged-redacted/v1`. Row 24f's C1 7b list names that file (24f plan, section 7b), so
the 24f C1 builder moves the marker to v2. C1 here adds the AT-C1 cells to the same file.

## 8. Placement

| Change | File and directory | CODEMAP placement | Existing neighbour or reason |
|---|---|---|---|
| profile writer (moved), `_floor_field` and its rules | `src/decoy_engine/profiling/_profile_document.py` (new) | "Detectors, profiling" row: by profiling concern | beside `_snapshot_values.py`, the snapshot writer over the same registry; `profiling/` holds 18 modules, under the fan-out limit of 25 |
| `PROFILE_FLOOR_FIELDS`, `PROFILE_FLOOR_KEEP`, seven `Rule` members, `DATA_RULES`, `PlaceholderAt` and its `_apply` branch | `src/decoy_engine/profiling/_value_redaction.py` | "Detectors, profiling" row | the one value registry; net smaller after E1a |
| re-export path | `src/decoy_engine/profiling/__init__.py` | existing | public names unchanged |
| `is_table_sentinel`, `_string_note`, `_numeric_text`, out-of-range note constants | `src/decoy_engine/profiling/sentinels.py` | "Detectors, profiling" row | the owner of the four tables; no new file |
| `release_ranges_at_k`, replacing row 24zp's `_kth_year` and inline clamp in `fold_year_bins` | `src/decoy_engine/profiling/_snapshot_values.py` | "Detectors, profiling" row | owner of `fold_ranges_under_k` and `labels_read_as_sentences`; no new file |
| floor tests | `tests/unit/profiling/test_profile_floor.py` (new) | "Unit tests" row: mirror `src/` under `tests/unit/<package>/` | beside `test_value_redaction.py` |
| sentry changes | `tests/sentry/profiling/test_profile_value_registry.py`, `test_snapshot_value_registry.py` | "Sentry test" row: existing rules | existing files |
| CODEMAP row text, QA checklist, fragment | `CODEMAP.md` profiling row, `docs/qa/03-pre-scan-profiling-detection.md`, `changelog.d/profile-unflagged-values.md` | "QA checklists" and "Changelog fragments" rows | existing owners |
| CLI docstring, help text, tests, docs | CLI `src/decoy/api.py`, `src/decoy/cli/explain.py`, `tests/e2e/first_user/test_items_privacy.py`, `docs/qa/cli-v1-checklist.md` (SCAN-04), roadmap, shipped log, `CHANGELOG.md` | existing files; no new module in the frozen flat `src/decoy/cli/` | C1 rides the engine repin PR |

Expected size. E1a: 2 production files plus the init, about 60 source lines moved (about 130
diff lines with the sentry path and CODEMAP text). E1b: 4 production files (`_value_redaction.py`,
`_profile_document.py`, `_snapshot_values.py`, `sentinels.py`); about 680 diff lines (about 255
source, 395 test and 30 doc), below 800.
`_profile_document.py` (76 lines at `8796ef691`) ends near 260 lines; `_value_redaction.py`
(486) near 545; `_snapshot_values.py` (552, about 580 with #649) near 590. New names: the
module, `PROFILE_FLOOR_FIELDS`, `PROFILE_FLOOR_KEEP`, seven `Rule` members, `PlaceholderAt`,
`is_table_sentinel`, `_string_note`, `_numeric_text` and
`_floor_field`; no new public export.
C1: no production logic; about 80 docstring, help, test and doc lines.

## 9. Frozen contracts touched

- `profile_document` and `redact_profile_dict` (frozen surfaces, `docs/frozen-surfaces.md:78`):
  signatures and public paths unchanged; plain output changes. Pre-GA break, engine fragment:
  "Breaking: a plain `profile_document` or `redact_profile_dict` document now redacts, in every
  column, any top value or label held by fewer than 10 rows, any label of a column whose labels
  read as sentences, every numeric bin label, any numeric or date extreme it cannot prove is held
  by 10 rows, and the invalid-date samples. Date decades are merged until each holds 10 rows, and
  the outer decades are those of the 10th earliest and 10th latest dated rows; a column with fewer
  than 19 dated rows releases no decade.
  `include_values=True` output is unchanged."
- CLI `CHANGELOG.md` line, under Changed: "The `scan.json` that `decoy demo` writes keeps no value
  of any column held by fewer than 10 rows, and no numeric range or exact date (roadmap row
  24zm)."
- `value_policy`: no change by this row; row 24f E1 makes it `flagged-redacted/v2`.
- `ColumnProfile.to_dict()`, `VALUE_FIELDS`, `VALUE_FREE_FIELDS`, the flagged rules: unchanged.
- Reason codes: none added. `REGISTRY_VERSION` and manifests untouched.

## 10. Slices

| Slice | Content | Risk | Size | Depends on | Tests at T1 |
|---|---|---|---|---|---|
| E1a | MERGED (engine #629). 4.1 move, sentry path, CODEMAP row text | R1 | 3 production files; about 130 diff lines | none | `tests/unit/profiling/test_value_redaction.py`, `tests/sentry/profiling/`, `tests/unit/test_public_api.py`, import layers, module size |
| E1b | 4.2 to 4.4 floor, the `release_ranges_at_k` extraction, tests, QA checklist, fragment | R2 | 4 production files (`_value_redaction.py`, `_profile_document.py`, `_snapshot_values.py`, `sentinels.py`); about 680 diff lines | E1a, row 24f E1 and row 24zp (#649) merged | AT-1 to AT-14, `tests/unit/profiling/`, `tests/sentry/profiling/`, `tests/sentry/test_module_size.py`, `tests/sentry/layout/test_package_fanout.py` |
| C1 | AT-C1, AT-C2, `decoy.scan()` docstring, `decoy explain security` line for the demo `scan.json`, SCAN-04 text, roadmap row, shipped log, changelog | R1 | about 80 lines | E1b released and pinned (repin checklist) | AT-C1, AT-C2, `tests/e2e/first_user/test_items_privacy.py`, `tests/sentry/io_policy/` |

Named mutations per slice. E1a (merged): change a flagged rule during the move (existing
`test_value_redaction.py`); change the public export path (`tests/unit/test_public_api.py`). E1b:
the list after section 7's table, plus make `fold_year_bins` call `fold_ranges_under_k` instead
of `release_ranges_at_k` (#649's `test_snapshot_floor.py` tail tests). C1: assert `F` and `M` are present in the demo
`scan.json` (AT-C1 goes red); save the `decoy.scan()` profile with `to_dict()` (the CLI sentry
`test_profile_document_route.py` goes red).

Ratchets touched: none. E1a added none. E1b adds no module-size census entry or ceiling
(`_value_redaction.py` ends near 545 lines and `_snapshot_values.py` near 590, both under the
600 goal; `_profile_document.py` near 260), no fan-out allowlist entry (no new file in
`profiling/`), no sentry baseline or allowlist row, no physical-seam entry and no pin. C1 changes
no pin itself: it rides the engine repin, whose checklist owns the pin move.

E1b changes the bytes of a frozen surface, an escalation trigger: its merge head gets the full
engine suite against the saved main baseline. E1a and C1 run T1 only. Tests run on the Mac first,
then `~/bin/vm-run`, never on the devbox.

## 11. Stop lines for builders

1. No second `Rule` enum, registry or applier; extend the existing ones.
2. Do not change `VALUE_FIELDS`, `VALUE_FREE_FIELDS`, the flagged path or `include_values=True`
   bytes. E1a changes no behaviour.
3. Do not change `MIN_RELEASE_COUNT`, restate 10 or 3, or copy row 24f's fold or word test.
4. No module-size census entry, ceiling, fan-out allowlist entry, sentry baseline or allowlist is
   added or raised. `_value_redaction.py` and `_snapshot_values.py` must not pass 600 lines;
   if either would, stop and report.
5. No new file under `src/decoy/cli/` or `src/decoy_engine/execution/`.
6. A red test outside 7b is a stop. Growing a fixture is allowed; weakening an assertion is not.
7. No new reason code and no new marker string.
8. A slice stops at 10 production files or 800 changed lines; split tests by the E1a/E1b line
   instead of raising the limit.
9. Use `fold_ranges_under_k` and `labels_read_as_sentences` as row 24f E1 shipped them. Put #649's
   tail coding into `release_ranges_at_k` and delete `_kth_year` and the inline clamp; no second
   tail coder. If #649 merges with coding that `release_ranges_at_k` cannot reproduce with its
   tests unchanged, stop and report. If #649 is not merged when E1b starts, stop and report.

## 12. Owner questions

Each is taken under standing approval ("go with recommended") on 2026-11-17.

1. Numeric and date extremes with no data to top-code: (a) withhold unless the document proves K
   rows hold the exact text; (b) a power-of-ten outward bound. Recommended and taken: (a). The
   document has no data for row 24f's top coding, (b) moves with one row, and the flagged profile
   rule already nulls these slots.
2. Date granularity: (a) fold the existing decade buckets; (b) add year buckets to the profiler.
   Recommended and taken: (a). It needs no change to `ColumnProfile` or the platform shape.
3. Categorical labels outside the top 5: (a) keep when the rounded-share lower bound reaches K;
   (b) redact every label without an exact count. Recommended and taken: (a). It keeps the 10-label
   chart useful and is never looser than K.
4. The marker window: row 24f E1 flips the shared marker to v2 before E1b floors profile
   documents. (a) Accept the window and ship E1b in the next engine release after 24f E1; (b) hold
   24f E1 until E1b is ready. Recommended and taken: (a). The leak exists today; the window only
   makes the marker describe the target state early. If an engine release is cut between them,
   its notes say profile documents are floored from the next release. No CLI release carries the
   24f repin without 24zm C1: the CLI pins the first engine release that holds both, or holds its
   release until it does. Row 24f's C1 already moves the `test_items_privacy.py` marker to v2.
5. Sentinels of unflagged columns: (a) keep only a `value` and `note` that match the fixed table
   for their `kind`, and floor any other at K; (b) redact. Recommended and taken: (a), as the
   orchestrator ruled on revision 2. Every profiled sentinel matches its table (section 1.1).

## 13. Unresolved

- Row 24zp (#649) is open. E1b's start date follows its merge.
- Engine 0.28.0 (#647) carries row 24f E1, so from 0.28.0 a profile document says
  `flagged-redacted/v2` while its unflagged columns are not floored. Q4 (a) stands: the CLI may
  repin 0.28.0 for row 24f C1, but no CLI release ships until it pins an engine release that holds
  E1b too. Owned action: before #647 merges, the release owner (the orchestrator) adds this line
  to the 0.28.0 notes: "`profile_document` and `redact_profile_dict` documents carry
  `flagged-redacted/v2` in this release but floor unflagged columns only from the next release
  (row 24zm)."
- The CLI release order (Q4): no CLI release ships the 24f repin without 24zm C1. The release
  owner checks this at the repin; the 24f C1 and 24zm C1 PRs may be stacked on one repin.

## 14. Pre-mortem

- A person reading the demo `scan.json` thinks redacted labels are a bug. Mitigation: the
  `decoy explain security` line and the QA checklist state the floor.
- A future value slot reaches the profile without a floor rule. Mitigation: AT-10 fails on any
  `VALUE_FIELDS` pair without a `PROFILE_FLOOR_FIELDS` row.
- A future profiler change writes `min_value` and top values through different `str()` forms, so
  `HELD_BY_K` never matches. Effect: over-redaction, never a leak. AT-1 pins the match.
- The percentage rounding in `_distributions.py` changes. Effect: P2's margin may be wrong.
  Mitigation: the margin is one constant beside the categorical builder's rounding (4.3 step 4),
  and AT-5 pins both.
- A builder routes around a hard case by widening `PROFILE_FLOOR_KEEP`. Mitigation: AT-10 lists
  its exact slots.
- A builder writes `null` or `[redacted]` inline in `_floor_field` instead of resolving a rule.
  Mitigation: the shared `_guard_findings` checks scan `_profile_document.py` (AT-10).

## 15. V2-LOG

- Mean dominance. A released `mean_value` (kept at `n >= 2K`) together with released top-value
  counts can isolate one outlier: when every other cell is known from the top values, the mean
  gives the last one. The SDC answer is a dominance or p% rule on the aggregate (Hundepool et al.,
  the sensitivity rules for magnitude tables). Row 24f keeps `mean` on the same `2K` rule, so both
  writers would change together. V1 threat model: an accidental leak needs a reader to do this
  arithmetic on purpose, so it is out of scope for V1 and logged for V2.
