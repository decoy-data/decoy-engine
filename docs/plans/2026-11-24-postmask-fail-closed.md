# Post-mask leak check fails closed (G8)

Status: plan

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN
phase), `profiles/local-operations.md`, `bugfix.md`, `testing.md` (test depth),
`cross-cutting-concerns.md`, `proportionality.md`.

Row: POSTMASK-FAIL-CLOSED (G8, owner 2026-11-24, blocks 1.0). Source: the F34 FRAME finding,
CLI `docs/roadmap/row-detail.md` section F34 (row 67).

Code references: engine `origin/main` at `9f7bb1f4a` unless marked `#784`, which means engine
PR #784 (branch `fix/postmask-fail-closed`) at `c2ca4f531`. Paths start at
`src/decoy_engine/verification/postmask/` unless they start with `src/` or `tests/`.

Revision 2, after Codex plan review round 1 (NO-GO). Round 1 found two V1 fail-open cases that
#784 does not cover: the text fallback in the resident runner can lose numeric equality (R1-V1a),
and the deferred gate converts tables outside any handler, so an Arrow error text can escape
with a cell in it (R1-V1b). This revision adds a source slice for both, separates reporting
checks from blocking checks in the inventory, closes C7 and N1 to N3 at their root, and
tightens the tests and mutations. The resolution of each finding is in "Review round 1".

Revision 3, after Dennis plan review (NO-GO on revision 2). A relationship parse failure is a
coded `PipelineConfigError`, so the revision 2 carrier for N2/N3 could never fire; the handlers
are now deleted and the coded error propagates. The deferred NER block moves into one helper in
`_blocked.py`, the NumPy key fix covers `float64`, and `_post_scan.py` has a checked line
budget. The resolution of each finding is in "Review round 2".

Revision 4 addresses the Codex review of plan `418f906b6` against `c2ca4f531`.

## Read this first: most of the fix is already in review

Part of this row is already built in open PR #784, which is slice PM-1a of
`docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md` on branch
`plan/pmfc-ratchet-growth`. #784 deletes `_source_identity`. The frame path then records a
failed comparison as `identity_error`, as the batch path already did, and reports it as an
`error` finding. It does this also when no detector hit the column, and also on a passthrough
that another writer may own. #784 takes `_source_identity` off the `post-scan-pass-through`
sentry baseline and has tests that force the comparison to raise on both paths. Codex round 1
confirmed that #784 closes S1 to S5 as named (184 targeted tests green on `c2ca4f531`).

This plan does not build that again. It does four things:

1. It states the G8 behavior as acceptance criteria, so the row can close against #784 and the
   two slices below.
2. It lists every swallow site and every failure carrier in the post-mask package and its gate
   caller, and says for each one whether its failure blocks or is only reported.
3. Slice G8-S1 (runtime, R2) fixes the two V1 cases from round 1, adds the missing
   `passes_through` guard to C7, and removes the three "no signal" handlers N1 to N3 at their
   root.
4. Slice G8-S2 (tests and sentry, R1) adds a sentry that stops a broad handler from turning a
   failure into "no signal", with an empty baseline, and the end-to-end pins.

The row closes when #784, G8-S1 and G8-S2 are all merged.

## Guarantee and non-goals

Guarantee: in the post-mask column suite and its gate caller, an exception that is not a coded
engine error never makes a column look clean, on any route (resident required, resident
deferred, streamed commit). It becomes an `error` row or a `pass_failed_with` entry that names
the exception class only. A required gate blocks on it. A deferred gate reports it, and blocks
on it when the run enforces the NER predicate (`ner_findings: fail`). A lossy conversion that
removes identity evidence or changes the source diversity used to grade a text column fails the
table. Both resident gates preserve exact Arrow integers on input and output. Under NER
enforcement, a blocking `check_error` withholds delivery even when NER itself completes cleanly.

Non-goals: new reason codes, a new finding type, a report schema version change, the PM-1b and
PM-1c slices of the existing PM plan, and making reporting-only checks block (distribution,
NER under `warn`, source-side key baselines). Those stay as they are; see the inventory and
the V2-LOG.

## Behavior

- B1. When the post-mask source comparison of a column raises, the residual-PII check reports
  one finding for that column with `severity: "error"`. It never reports the column as "not
  compared" with the base grade, and never omits it.
- B2. B1 holds on both entry paths: the frame check (`check_residual_pii`) and the facts check
  (`residual_pii_findings`, used by `run_post_mask` and `run_post_mask_tables`).
- B3. B1 holds when no detector hit the column, if the run may have written the column (#784
  `may_write`). A column that no writer touches and no detector hits has nothing to report.
- B4. "No signal" stays quiet only when there is no evidence to compare: no source table or
  column, unequal row counts (policy validation reports that), or zero comparable rows. These
  are not errors.
- B5. An exception that `passes_through` (a coded engine error) propagates as the same object.
  It does not become a finding. This holds in every broad handler of the package, policy
  validation (C7) included.
- B6. The finding, the report and every log line are value-free. They carry table, column,
  detector id, strategy and the exception class name only. No cell value, column value or
  exception text. Raises happen outside `except` blocks; no `raise ... from None` inside a
  handler.
- B7. An `error` residual finding makes the gate verdict `post_scan.check_error`. When the gate
  is required and not deferred, that raises `PostScanBlockedError`, the outputs are withheld,
  and the CLI exits 4 (CLI `src/decoy/cli/exit_codes.py:204,259`). On a deferred (report-only)
  run, the row is in the report and `error_count` counts it.
- B8. On aligned paired text columns, preserve the comparable denominator, all existing
  identity evidence and the original constant-or-varied source classification. Fail the table if the
  denominator or classification changes, or the keys count fewer identical rows. Extra identity
  matches are permitted only after both other checks pass.
- B9. Required and deferred resident suites use the same exact-integer conversion for every
  source and output column. A deferred suite or conversion exception produces a report with
  the safe class name in `pass_failed_with`. A completed suite keeps its own findings.
  Under `ner_findings: fail`, either `ner_blocked` or a blocking `check_error` withholds delivery.
  Under `warn`, the deferred gate records the verdict and allows delivery.
- B10 (new, N2/N3). An invalid declared relationship is a configuration error.
  `parse_relationship_config` (`src/decoy_engine/config/_parse.py:34-45`) raises
  `PipelineConfigError`, a coded, value-free `DecoyError` for which `passes_through` is True.
  The gate lets it propagate as the same object from `tee_reader`, `note_quarantined` and
  `run_resident`, so the run stops before any output is published. No handler in the gate
  catches it.

## The finding

No new type, field, severity or reason code. The finding is the existing `ResidualPIIFinding`
(`types.py`):

| Field | Value |
|---|---|
| `severity` | `"error"` (already in `Severity`, `types.py:25`) |
| `detector_id` | the top detector id, or `""` when no detector hit (B3) |
| `configured_strategy` | the configured strategy or `None` |
| `source_compared` | `False` |
| `source_identity_rate` | `None` |
| `message` | #784 `_compare_raised`: names the exception class and says a leak cannot be ruled out |

A table-level failure (B8, `runner.py` `_frame_tables`) uses the existing #784
`residual_pii_error(table, error_class)` row. A gate-level failure (B9) uses the existing
`pass_failed_with` report key.

The reason code is the existing `post_scan.check_error`
(`src/decoy_engine/reasons/post_scan/_part1.py:18`). `_blocked.py` picks it for any residual
`error` row and for `pass_failed_with`. The report counts residual rows in `error_count`
(`_blocked.severity_counts`). The run card shows the post-scan report as it does today.

Policy validation keeps its own per-column error (`policy_validation.py:134`, `_compare_failed`
at :157) for configured columns. A configured column whose comparison raises gets one policy
error and one residual error, because they are two checks. Tests that pin the residual verdict
alone use a column with no policy entry (AT-7).

## Inventory: failure carriers and swallow sites

Every broad handler and every "return no signal" branch in `verification/postmask/` and
`src/decoy_engine/execution/pipeline/_post_scan.py`, found by an AST scan of both heads plus a
read of the `continue` and exemption branches in `residual_pii_findings`. Codex ran the proposed
no-signal predicate on both heads in round 1 and found S1 and N1 to N3 on main, N1 to N3 on
#784, and nothing else.

"Blocks" says what the failure does on a required, non-deferred gate. "Blocking" means the
verdict gets `check_error` (or a stronger code). "Reporting" means the failure is in the report
but by design does not withhold the outputs. G8 is about the leak check, so every failure that
can hide a leak must be blocking. A reporting-only row is in scope only for B5 and B6.

### Sites that lost a failure (the G8 class)

| # | Site | What it did | Blocks after the fix | Status |
|---|---|---|---|---|
| S1 | main `residual_pii.py:255-274` `_source_identity` | `except Exception: return None`. A raised comparison looked like "no source". Frame path only. | Blocking (residual `error`) | Fixed in #784 |
| S2 | main `residual_pii.py:511` `if not fact.detectors: continue` | A column with `identity_error` and no detector hit gave no finding. Production path. | Blocking | Fixed in #784, for columns the run may write |
| S3 | main `residual_pii.py:518,552` passthrough exemption | Dropped `identity_error` on a passthrough column that another writer may own. | Blocking | Fixed in #784 (`may_write`) |
| S4 | main `residual_pii.py:541-543` failed source distinct count | Read as "varied", which could change the grade without saying so. | Blocking when the grade depends on it | Fixed in #784 |
| S5 | main `check_residual_pii` | No per-table isolation on the frame path. | Blocking (per table) | Fixed in #784 |
| S6 | #784 `runner.py:173-210` `_text` fallback in `_frame_table` | The fallback renders a NumPy `float32`, `float16` or `longdouble` cell in an object column as `12345.0` and an equal `int` as `12345`. A leaking column then counts zero identical rows and grades `info`. Pre-existing on main (`runner.py:178` `_key`). Round 1, R1-V1a. | Blocking | G8-S1 (B8) |
| S7 | #784 `_post_scan.py:266-287` `_report_only` | Converts the tables to pandas outside any handler. An Arrow error text can carry a cell, and `gate.report` stays `None`. Pre-existing on main. Round 1, R1-V1b. | Reporting on a deferred gate, blocking under `enforces_ner` | G8-S1 (B9) |

S1 has no production caller on main. S2, S3 and S6 are on the production path and are the real
fail-open cases today. S7 is a value-text exposure and a lost report.

### Carriers that already fail closed (pin, plus the fixes noted)

| # | Site | Carrier | Blocks | Change |
|---|---|---|---|---|
| C1 | `_column_facts.py:345` `column_facts` | `identity_error` by class name | Blocking (residual `error`) | none |
| C2 | `_column_facts.py:289-302` `_distinct_or_error` | `distinct_error` | Blocking when the grade depends on it (#784 S4) | none |
| C3 | `_column_facts.py:127` `_ValueTally.add` | `error` on the value facts | Reporting: the distribution check is warn-only today (`distribution.py:249`, "fail severity arrives with the blocking slice"). It is a utility check, not a leak check. | none; V2-LOG item 1 |
| C4 | `runner.py:235` `_frame_tables` | `failed[name]`, one residual `error` per table | Blocking | G8-S1 adds the B8 backstop here |
| C5 | `runner.py:420` `_suite_facts` | `failed[name]`, one residual `error` per table | Blocking | none |
| C6 | `runner.py:287,312,333` check wrappers | one `error` row per check | Blocking for residual, policy and FK rows; reporting for a distribution row | none |
| C7 | `policy_validation.py:134` `_check_one_column` | `_compare_failed`, a policy `error` | Blocking | G8-S1 adds the `passes_through` guard (B5) and deletes its `post-scan-pass-through` baseline entry |
| C8 | `_model_findings.py:200` model pass | one residual `error` row per model pass (`source` classifier or NER) | Reporting under `ner_findings: warn` (the default); blocking (`ner_blocked`) under `fail` for NER rows (`_blocked.py:207`). This follows the owner's model policy (SCAN-ML Q1). The regex residual check still runs and blocks on its own. | none; V2-LOG item 5 |
| C9 | `_keys.py:175` output side | key `status: error`, `check_error` | Blocking | none |
| C9b | `_keys.py:217,235` source side | `baseline: error` | Reporting: a source-side failure gives no baseline, so `check_error` there warns (`_blocked.py` `_key_refs`). The output-side counts (nulls, duplicates, orphans) still block on their own. Not a leak check. | none; V2-LOG item 2 |
| C10 | `_post_scan.py:200,208` `_decide` | `pass_failed_with`, then `check_error` | Blocking | none |

### Sites that returned "no signal", and their root fix

| # | Site (#784) | Why it looked safe | Root fix in G8-S1 |
|---|---|---|---|
| N1 | `runner.py:178-184` `_native`, `except Exception: return None` | `None` selects the text fallback, so the column is still checked. Round 1 showed the fallback itself can lose equality (S6). | Narrow the handler to the exceptions Arrow raises when it refuses a column: `pa.ArrowException`, `TypeError`, `ValueError`, `OverflowError`, still opening with the `passes_through` guard. Any other exception propagates to `_frame_tables` and fails the table (C4, blocking). The fallback then has the B8 backstop. |
| N2 | `_post_scan.py:222-232` `tee_reader`, `return None` | The comment says "an unreadable relationship is the check's to report". But the only error the parse raises is the coded `PipelineConfigError`, which the guard already re-raises, so the `return None` branch is dead code that hides intent. | Delete the `try`/`except`. The coded error propagates (B5, B10). |
| N3 | `_post_scan.py:292-306` `note_quarantined`, `return` | Same as N2. | Same as N2; the docstring sentence about leaving the relationship to the check goes too. |

After G8-S1 there is no broad handler in scope whose body is only `pass`, `continue`, `return`
or `return None`. So the G8-S2 sentry starts with an empty baseline. No baseline, census or
allowlist grows; `post-scan-pass-through` shrinks by one entry (C7).

## Design of the G8-S1 fixes

### S6: one equality rule through the text fallback (B8)

Root cause: two equality rules. The frame check uses pandas `==` through `identity_counts`
(`_column_facts.py:264`). The runner's text fallback uses the text key from
`cell_text._number_key` (#784 `src/decoy_engine/internal/cell_text.py:111`), which knows only
Python `bool`, `int`, `float` and `Decimal`. Most NumPy scalars in an object column are not a
Python `int` or `float`, so they fall to `str()`. `np.float64` is a `float` subclass, so it takes
the `float` branch, but that branch uses `repr()` for a non-whole value, and NumPy 2 gives
`'np.float64(1.5)'` there (checked: NumPy 2.2.6). Checked on the #784 venv:
`np.float32(12345.0)`, `np.float16` and `np.longdouble` render with `.0` against `int` `12345`,
`np.float64(1.5)` renders as `np.float64(1.5)` against `float` `1.5`, and `np.datetime64`
renders without the time part against an equal `pd.Timestamp`, while pandas `==` says equal in
every case.

Fix, in two parts:

1. Normalize temporal scalars first in `cell_text._number_key`. Render `np.timedelta64` via
   `pd.Timedelta` before the `np.integer` branch (`int(np.timedelta64(1, "D"))` raises).
   Render `np.datetime64` via `pd.Timestamp`. Give Python and NumPy booleans the integer
   comparison keys `"0"` and `"1"`. Convert other NumPy integers to Python integers and
   NumPy floats to Python floats before the existing numeric rendering rules. In particular,
   handle `np.float64` before the Python float branch. This affects fallback comparison keys
   in `key_text`; ordinary `cell_text` rendering retains its existing contract.
2. Check the actual arrays selected by the paired fallback once, inside the per-table failure
   boundary in `_frame_tables`. Use the source and output series with positional indexes and
   their actual emitted keys, with nulls intact. Skip identity checks on unequal lengths as
   the frame path does. Compare both results from `identity_counts` on the original and key
   pairs. A changed comparable count or a smaller identical count fails the table. When
   comparable rows exist, compare the non-null distinct count of the **entire source column**
   with that of its emitted keys using the grader's constant-source predicate. Fail the table
   if the constant/varied classification changes, even when every row matches. Distinct counts
   of three and two both mean varied and must still pass this check.
   Share the frame count currently at `residual_pii.py:172` as a function beside
   `canonical_cells` in `_column_facts.py` (`canonical_cells(series).nunique(dropna=True)`).
   This keeps container handling and null semantics identical. Give the constant-source
   predicate one owner beside `ColumnFacts`. Route its property (`_column_facts.py:198-199`),
   the residual grader (`residual_pii.py:281`), the policy grader (`policy_validation.py:239`)
   and this backstop through it.
   Check mismatches outside exception handlers with a fixed-text internal
   `ComparisonNotPreservedError`. The existing per-table handler records its class name and
   continues with the other tables. A failed count or comparison uses that same boundary
   and coded errors still pass through.

### S7: exact resident conversion and deferred enforcement (B9)

The duplicate conversions at `_post_scan.py:281-282` and `:433-434` widen nullable Arrow
integers to floats. For example, the SSN detector no longer sees nine digits after a decimal
suffix is added. The staged batch reader at `_column_facts.py:213-216` preserves the dtype.

Use a single resident frame builder for both callers and both sides. For each materialized
source or output table use `table_to_pandas_exact_ints(table, table.column_names)` from
`decoy_engine.internal.pandas_compat`. This includes unconfigured siblings and reuses the
batch reader's `exact_int_types_mapper`. Keep the required suite's keys, distribution input
and writer ownership, and the deferred suite's detectors and writer ownership. Keep the
existing early returns for no requested suite or no eligible deferred table.

In `_report_only`, build the frames and run the suite inside the failure boundary. Re-raise
coded errors first. On an ordinary exception build a report with `SCHEMA_VERSION` and
`safe_error_class(type(exc).__name__)` in `pass_failed_with`. Outside the handler, retain the
completed report or failure report, attach its verdict and set the gate state before ruling.
In `raise_if_ner_blocked` (`_blocked.py:334`), use the blocking reason refs in
`post_scan_verdict(report, ner_findings=ner_findings).codes`. Raise through the existing
`blocked_error` and `raise_bare` path for `_NER_BLOCKED`, or for `_CHECK_ERROR` under
`fail`. This includes a residual comparison error with `pass_failed_with is None`.
Other deferred finding codes alone keep their existing ruling. The gate calls this decision
after reporting, before settlement releases a held publish.


### C7: the policy handler passes coded errors through (B5)

Add the `passes_through` guard as the first statement of the handler in
`policy_validation._check_one_column`. Delete the
`policy_validation.py::_check_one_column::unguarded::0` entry from
`tests/sentry/baselines/post-scan-pass-through.json`. The reason for the guard is B5: every
broad handler in the package lets a coded engine error through as the same object, and this
handler is the one that does not. The baseline entry's reason ("no engine-coded error can arise
inside it") is a claim about the call graph that nothing checks; the guard removes the need for
it. (`UnreadableCellError` is not the reason: `passes_through` is False for it by design,
`profiling/scan_set.py:316`, so it still becomes a policy `error` row.)

### N2 and N3: delete the dead handlers (B10)

`_relationships()` builds the list with `parse_relationship_config`, whose only raise is the
coded `PipelineConfigError` (built outside the Pydantic handler, value-free text). Both handlers
open with `passes_through`, which is True for it, so the `return` branches can never run on a
parse failure. Delete the `try`/`except` in `tee_reader` and `note_quarantined` and call
`self._relationships()` directly. The coded error then propagates from both, as it already does
from `_decide`'s `_keys` call. No carrier, no new attribute.

### Design notes

Reuse existing modules, subject to the placement and line budget below. Internal names cover the backstop exception, shared count, conversion helper and sentry label.
`raise_if_ner_blocked` gets a wider rule, not a new name. Each new fact has one place: the
equality rule stays in `identity_counts`, the key rule stays in `cell_text`, the deferred NER
block rule stays in `_blocked.py`. The principle applied is "one rule, one place" (two equality
rules caused S6). No flag arguments: the deferred and required gates share the conversion
helper and differ only in what they do with its result.

## Enumerations

### Exit paths

The ways a column comparison can end, and what each one must give:

- Comparison succeeds: graded finding as today (`residual_pii.py:518`).
- Comparison raises a non-coded exception: one residual `error` row (S1 to S3).
- Comparison raises a coded `DecoyError`: propagates as the same object (B5).
- No evidence (no source, unequal rows, zero comparable rows): no `error` (B4).
- Text fallback loses identity evidence or changes the source diversity classification: one residual `error` row for the table (B8).
- Arrow refuses a column with an exception outside the narrowed set: one residual `error` row
  for the table (N1 fix).
- Whole table fails before the column loop: one `error` per table (`runner.py:235`, `:420`).
- The check wrapper itself raises: one `error` per check (`runner.py:287`).
- Gate conversion or suite raises: `pass_failed_with` on both the required and the deferred
  gate (C10, B9).
- Relationships cannot be parsed: the coded `PipelineConfigError` propagates as the same
  object and the outputs are withheld (B10).

### Routes

- Resident frame route: `check_residual_pii` (frame path, B2).
- Resident required gate: `PostScanGate.run_resident` -> `_decide` -> `run_post_mask`
  (`_post_scan.py:189`).
- Resident deferred gate: `PostScanGate.run_resident` -> `_report_only` -> `run_post_mask`
  (B9).
- Streamed commit route: `before_commit` -> `run_post_mask_tables` over staged row groups.

All four end in the same `_blocked.py` verdict. AT-2 covers both column paths, AT-7 the
required gate, AT-14 the deferred gate, and AT-12 the runner fallback that only the resident
routes use.

### FK shapes

N/A for shapes: this row changes no key handling. AT-8 pins that an invalid relationship stops
the run with the coded error from each of the three gate entry points (B10).

### Fields

- `ResidualPIIFinding.severity`: `"error"` on a raised or non-preserved comparison.
- `ResidualPIIFinding.source_compared`: `False`.
- `ResidualPIIFinding.source_identity_rate`: `None`.
- `ResidualPIIFinding.message`: class name only, no value.
- Report `pass_failed_with`: class name only (B9).
- Report `error_count`: counts residual `error` rows.

### Output surfaces

- The post-scan report dict and JSON (finding rows, `pass_failed_with`, `error_count`).
- The `PostScanBlockedError` verdict codes and the CLI exit code.
- Job log lines from the check (class name only, B6).
- The run card, which shows the report as it does today.

## Defect classes

| # | Class | Applies here | Closing structure | Proof |
|---|---|---|---|---|
| 1 | Value-bearing output | Yes: a finding, a report key, an exception or a log line could carry exception text or a cell (S7). | Class name only; deferred conversion inside the class-only handler; raise outside `except`; `raise_bare` for the NER block | AT-6, AT-7, AT-14 with seeded markers; M3, M13 |
| 2 | Cleanup on an exit path | N/A: no new resource. The deferred handler sets `report` before `ran`, so a failed check leaves no half state. | none | AT-14 |
| 3 | State machine and concurrency | N/A: no new gate state. The deferred handler sets `report` before `ran` (class 2). | none | AT-14 |
| 4 | Route parity and silent fallback | Yes: this is the G8 class (S6 is a silent lossy fallback). | One carrier (`identity_error`) on both paths; one equality rule (`identity_counts`) with a backstop; no-signal sentry | AT-2, AT-12, AT-13, AT-9; M1, M11, M12, M16 |
| 5 | Referential integrity | N/A for keys; the relationship parse failure is pinned | none | AT-8 |
| 6 | Untrusted producer | N/A: the exceptions come from in-process pandas or Arrow code, and only their class name is read. | none | AT-6, AT-14 |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is checked or opened. | none | none |
| 8 | Weak tests and overclaimed evidence | Yes: "exists" tests must be green on the slice head, red-before recorded, mutations recorded with the head SHA. | AT-10 red-before; mutation evidence table | M1 to M21 (no M17) on the slice heads |
| 9 | Behavior-preserving refactor drift | Yes, small: the shared conversion helper (S7) moves code, and the N2/N3 handler deletions change the shape of two methods. | The required-gate tests stay green unchanged | AT-11, AT-7, AT-8 |
| 10 | Frozen contract drift | N/A: no schema, reason code or exit code changes (see Frozen contracts). | none | none |

## Reuse inventory

- `ColumnFacts.identity_error` and `distinct_error`: the existing failure carrier.
- `identity_counts` (`_column_facts.py:264`): the one equality rule, reused by the B8 backstop.
- `cell_text._number_key` (#784): the one key rule, extended for NumPy scalars.
- `residual_pii_findings`, #784 `_compare_raised` and `residual_pii_error`: the existing error
  rows.
- `pass_failed_with`, `safe_error_class`, `raise_if_ner_blocked`, `blocked_error`,
  `raise_bare`: the existing gate failure path. `raise_if_ner_blocked` is extended, not copied.
- `parse_relationship_config` and `PipelineConfigError`: the existing coded config error (B10).
- `post_scan.check_error` and `_blocked.py`: the existing verdict.
- `tests/sentry/post_scan/_scan.py` (`sites`, `scan`, `_broad`, `_opens_with_pass_through`):
  the new label reuses these helpers.
- The ratchet baseline format, `tests/sentry/_baseline_sources.py` and
  `scripts/dev/sentry_registry.toml`.

## Frozen contracts

- `post-scan-integrity/v3` report schema: unchanged. `pass_failed_with` is an existing key.
- `ResidualPIIFinding` fields and the `Severity` literal: unchanged.
- Reason codes (`post_scan.check_error`): unchanged.
- CLI exit codes (exit 4 for a post-scan block): unchanged.
- `check_residual_pii` signature: #784 adds an optional keyword only. G8 changes no public
  signature.

## Pre-mortem

- #784 changes again before merge and moves a test that this plan names. Mitigation: step 1 of
  each slice checks the names on the base head and updates the AT table, not the criteria.
- The B8 backstop fails tables that passed before, because some cell type renders differently
  from its pandas equality. That is the intended fail-closed result. AT-12 covers the common
  NumPy types so the key rule handles them, and the backstop only catches the rest. A table
  that fails this way says so by class name.
- Narrowing N1 sends an unexpected Arrow-side exception to a table failure. It blocks, by class
  name, instead of falling back. The existing mixed-type pins (AT-11) show the common refusals
  are still in the narrowed set.
- The deferred gate now reports failures it used to raise as raw exceptions. A run that crashed
  with an Arrow error now completes report-only. That is the deferred contract. Under
  `enforces_ner` it still blocks.
- The no-signal label also flags handlers outside the G8 scope as the package grows. The
  baseline starts empty and is shrink-only, so a new site has to be fixed, not listed.
- `_post_scan.py` is at exactly 600 lines on #784 (the module-size GOAL) with no census entry.
  The B9 handler adds lines. The slice has a line budget that is a checked item (see "Slices
  and size"), so the file cannot grow a census entry unseen.
- AT-7 and AT-14 are slow because they run a gate. Use the smallest resident config already
  used in `test_gate_rulings.py`.

## Sentry: yes, one narrow rule (G8-S2)

Choke point. The choke point for "a comparison failed" is already in place.
`ColumnFacts.identity_error` and `distinct_error` (`_column_facts.py`) are the one carrier, and
`residual_pii_findings` (#784 `_compare_raised`) is the one place they become a finding. The gate
uses the verdict from `_blocked.py` for both row-level errors and `pass_failed_with`.

Gap. The existing `post-scan-pass-through` sentry (`tests/sentry/post_scan/_scan.py`
`pass_through_label`, baseline `tests/sentry/baselines/post-scan-pass-through.json`) checks
only that a broad handler opens with the `passes_through` guard. S1 on main shows the gap: a
guarded handler can still end in `return None` and lose the failure.

Guard. Add one label to the same scan, with the same scope (`verification/postmask` and
`execution/pipeline/_post_scan.py`):

- `no_signal_label` flags a broad handler (bare `except`, `except Exception`,
  `except BaseException`, or a tuple that holds one of them) whose body, after the optional
  `passes_through` guard, holds only `pass`, `continue`, `return` or `return None`. A handler
  that assigns, appends, calls, returns any other value or raises is clean.
- Baseline `tests/sentry/baselines/post-scan-no-signal.json`, `sentry_id`
  `post-scan-no-signal`, `created_in` `G8-S2`, with no entries (G8-S1 removes N1 to N3). Keys,
  if any are ever approved, use the existing `path::scope::label::ordinal` form.
- Register the baseline in both places, so the base-to-head ratchet checks growth
  (`tests/sentry/_ratchet.py`) and the registry test sees it
  (`tests/sentry/test_baseline_registry.py`): a `[[sentry]]` row in
  `scripts/dev/sentry_registry.toml` next to `post-scan-pass-through`, and an entry in
  `tests/sentry/_baseline_sources.py` next to the other post-scan baselines.
- Tests go in `tests/sentry/post_scan/test_post_scan_choke_points.py`, next to the pass-through
  tests: no site beyond the baseline, the baseline lists only live sites, and the fixture cases
  in AT-9.
- The mutation that must turn it red: M16 (widen N1 back to `except Exception: return None`).

The sentry does not prove that a recorded error reaches a finding. AT-1 to AT-4, AT-12 and AT-14
do that. The sentry stops the cheapest way back to the defect: a new `return None` in a handler.

It goes in `tests/sentry/post_scan/`, not `tests/sentry/defects/`, because the scope is the
post-scan package and it reuses `_scan.py`. The `tests/sentry/defects/test_exception_context.py`
ratchet already covers `raise ... from None` inside a handler, so G8 adds nothing for that.

## Established solutions

Search run: the codebase (the post-scan sentries in `_scan.py`, the defects ratchets) and the
usual linters. Ruff already has the generic rules: `S110` (try-except-pass), `S112`
(try-except-continue) and `BLE001` (blind except). The engine ignores `S110` and `S112`
globally until the lint-debt ratchet reaches the engine, and none of them catches `return None`
in a handler. So the plan follows the repo's existing pattern: an AST label in `_scan.py` with a
shrink-only JSON baseline. The custom part is one label function of about 20 lines.

For B8, the established rule is the one the frame check already uses (pandas `==` through
`identity_counts`), and NumPy's own `float()` and `int()` conversions for scalars (the same
conversions `.item()` performs). No new comparison library.

## Acceptance tests

"Exists" means the test is in #784; a slice only checks that it is there and green on its head.
"New" means the named slice adds it. "Red-before" means it must fail on the slice's base head
(#784 `c2ca4f531` for G8-S1) and pass on the slice head, and the PR body records both. Paths
under `tests/unit/detection_verification/` are shortened to start there.

Every seeded marker below is a synthetic string (for example `zz-g8-marker-7f3a@example.invalid`).
"Value-free" means: the marker and the forced exception's own text are not in any finding
field, not in `json.dumps(report)`, not in `str()` of any raised exception or its `__context__`
or `__cause__`, and not in any `caplog` record.

| # | Test | Kind | Slice | Where |
|---|---|---|---|---|
| AT-1 | Force the frame comparison to raise. One `error` finding for the column, `source_compared` False. | exists | #784 | `test_residual_pii_source_compare.py::TestIdentityComparisonRaises::test_frame_path_comparison_raise_is_error_finding` |
| AT-2 | The same cells through the frame path and the batch path give equal findings, including the case where equality raises. | exists | #784 | `test_residual_pii_source_compare.py::...::test_same_findings_on_both_paths` |
| AT-3 | A raised comparison on a column that no detector hits and the run writes is one `error`. | exists | #784 | `test_residual_pii_source_compare.py::...::test_failed_comparison_without_a_detector_hit_is_an_error` |
| AT-4 | A raised comparison on a passthrough column that another writer owns is one `error`, with or without a hit. A proven passthrough stays quiet. | exists | #784 | `postscan/test_writer_ownership_findings.py` (three tests, as named in #784) |
| AT-5 | A coded error raised inside the comparison propagates as the same object: `excinfo.value is raised`, on the frame path and on `run_post_mask`. | exists; extend with the identity assertion and the second path | G8-S2 | `test_residual_pii_source_compare.py::...::test_frame_path_passes_through_exception_propagates` |
| AT-6 | Value-free on the column paths: the forced exception's text holds a seeded marker. Value-free as defined above, on both paths, for AT-1 and AT-3 inputs. | new | G8-S2 | `test_residual_pii_source_compare.py` |
| AT-7 | Run the required gate through the real pipeline and a `ParquetTransactionalSink`, as in `test_m1_integrity_withholds_a_run_on_a_failing_column_finding`. Use Arrow-native synthetic emails only in unconfigured `contact`, and a configured sibling whose mask passes. Wrap `_column_facts._add_identity` at its batch-loop binding (:387). Identify the contact batch by its reserved synthetic email fixture, raise an ordinary marker-bearing exception only for it, and delegate every other call. Use one batch. Assert the injection ran, exactly one error across all sections, the residual `contact/email/error` row, no policy error or other blocking reason, `error_count == 1`, and `PostScanBlockedError` with sole code `check_error`. Assert the sink destination and configured target remain absent, and all surfaces are value-free. | new | G8-S2 | `tests/unit/execution/post_scan/test_gate_rulings.py` |
| AT-8 | Invalid relationship (an entry whose values hold a seeded marker). Patch `parse_relationship_config` to record the object it raises, or capture it on the first call. (a) `tee_reader()` raises `PipelineConfigError`, and `excinfo.value` is that same object. (b) `note_quarantined(...)` with a non-empty `removed` raises the same way. (c) `run_resident` on a required gate raises the same way, and no output is published (outputs withheld). All value-free: the marker is not in `str()` of the error, its `__context__` or its `__cause__`, or any `caplog` record. | new; red-before for (a) and (b) on #784 is not expected (the guard already re-raises), so this is a pin; M8 is its kill | G8-S1 | `tests/unit/execution/post_scan/test_gate_rulings.py` |
| AT-9 | Sentry fixtures. Flagged: `return None`, bare `return`, `pass` and `continue` after the guard, for bare `except`, for `except Exception`, for `except builtins.Exception`, for `except (Exception,)`, and for a tuple that holds `Exception` with another class. Clean: an assignment, an append, a returned finding, a re-raise, a narrow `except ValueError: return None`. The live scan finds zero sites. A seeded `except Exception: return None` in a scratch copy of `residual_pii.py` raises the count by one. | new | G8-S2 | `tests/sentry/post_scan/test_post_scan_choke_points.py` |
| AT-10 | Run the new label on main's `residual_pii.py` (flags `_source_identity`) and on `c2ca4f531` (flags N1 to N3). Record both in the PR body. | red-before evidence | G8-S2 | PR body |
| AT-11 | The closed carriers keep their tests: failed comparison, failed distinct counts, table isolation and the unconvertible table in `postscan/test_column_suite_on_facts.py`, including `test_a_zip_column_of_mixed_int_and_str_is_compared_as_on_the_frame_checks`; `postscan/test_runner_pass_through.py`; `postscan/test_value_free_check_errors.py`. | pin, exists | both | as named |
| AT-12 | B8 key parity. An object column holds, per case, one of: `np.float16`, `np.float32`, `np.float64`, `np.longdouble`, `np.int8` to `np.int64`, `np.uint8` to `np.uint64`, `np.bool_`, `Decimal`, Python `int`, Python `float`, `np.datetime64` vs `pd.Timestamp`. The output holds equal cells of another numeric type, plus a text sentinel arranged so Arrow refuses native conversion. Include object-series pairs of `np.timedelta64(1, "D")` and `pd.Timedelta(days=1)`, and `np.bool_(True/False)` and Python `1/0` respectively. Assert the text branch ran for the tested column and that each equal pair has equal keys and counts as identical. Every float type case includes non-whole values (`1.5`, `0.25`) as well as whole ones, against equal Python `float` cells. For each case, `run_post_mask` and `check_residual_pii` give the same reported identity rate and severity for detector hits (check raw counts with `identity_counts` for the scalar pairs), and the B8 backstop does not fire (no residual `error` row). The round 1 case (61 rows, `faker` strategy, 60 `np.float32` ZIP source cells, equal `int` output cells, one changed text cell) grades `fail` on both paths and `post_scan_verdict` blocks with `finding_blocked`. | new, red-before | G8-S1 | `postscan/test_column_suite_on_facts.py` |
| AT-13 | B8. (a) A test cell compares equal but renders differently on each side. Require one residual table error with the backstop class, value-free report and blocking `check_error`. Extra key matches are allowed in a control whose source diversity and comparable count stay unchanged. (b) Put 64 unchanged synthetic, Luhn-valid PAN cells alternating between the integer and its identical decimal string in an object column. Use an unconfigured sibling in a configured table and a clean masked column. Assert the frame check yields `pan/fail` with full identity. Confirm fallback has 64 comparable and identical rows on both representations, source distinct counts 2 and 1. Require one residual table error and blocking `check_error` from `run_post_mask`. Removing only the classification check must expose `pan/warning` and lose the block. (c) With mixed source cells `[1, "1", 2]` and distinct changed non-PII output, assert source diversity goes from three to two, both varied, with a clean verdict and no table error. | new, red-before | G8-S1 | `postscan/test_column_suite_on_facts.py` |
| AT-14 | Gate conversion, deferred ruling and publication. Run cases (a) through (d) below. | new, with required/staged controls | G8-S1 | `tests/unit/execution/post_scan/test_gate_rulings.py` |
| AT-15 | Call `check_policy_validation(source_frames, output_frames, config)` with an existing configured column and equal row counts. Patch `pd.Series.equals` for that pair to raise a preconstructed `FileAccessReadError`. Assert it was called and `excinfo.value is raised`. Removing the C7 guard must make this runtime assertion fail even without the sentry. Separately require the pass-through sentry green and the C7 baseline entry removed. | new, red-before | G8-S1 | `postscan/test_runner_pass_through.py` and the existing pass-through sentry |

**AT-14 gate cases**

- (a) Deferred, integrity on. Convert an Arrow string containing invalid UTF-8 and a synthetic
  marker. Under `warn`, require a completed gate, a value-free report, a bare class name
  (`re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)`) and blocking verdict code `check_error`.
  Under `fail`, require the same report and a chain-free, value-free `PostScanBlockedError`.
- (b) Repeat under both modes with valid Arrow cells, the selective batch fault from AT-7
  (define the fixture in G8-S1 for both slices), and an enabled deterministic clean NER
  pass. Assert the model ran, one residual comparison error, `pass_failed_with is None`,
  and sole blocking code `check_error`. Bind the gate and register an observable write
  through `publish_after_gate` before settlement. Under `fail` verify it was held, settlement
  raises the chain-free block and the destination remains empty. Under `warn` settlement
  returns with the error in the report and exactly one publication. Also exercise
  `raise_if_ner_blocked` with both report shapes in both modes and with a standalone
  `finding_blocked` control that remains report-only when deferred.
- (c) A required resident gate with the invalid conversion from (a) blocks with `check_error`.
- (d) Put 75 distinct synthetic nine-digit SSNs and one null in an unconfigured Arrow
  `int64` sibling, identical on source and output, beside a successfully masked column.
  Through the required resident gate and the staged gate's `before_commit` with a real `ParquetTransactionalSink`, assert the
  same `ssn/fail` residual row, full source identity, sole `finding_blocked` code and zero
  publications. Under deferred `warn`, require the same finding and recorded verdict.
  Assert both resident frame dtypes at the real suite boundary are nullable `Int64`
  (delegate to the real suite). This catches source-only widening even when floating-point
  equality still preserves all 75 matches. No fault injection or text fallback in this case.

## Mutations the tests must kill

Each mutation is run on the final slice head. The PR body records it in this form: mutation id,
slice head SHA, the test id that turned red, and the assertion line from the failure. A
mutation that no test kills blocks the slice. Until that table exists on that exact head, these are
proposed work, not results.

| # | Mutation | Slice | Killed by |
|---|---|---|---|
| M1 | Make the identity handler in `_frame_column_facts` return facts with no `identity_error`, or end in `return None`. | G8-S2 | AT-1, AT-2, AT-9 |
| M2 | Remove the `identity_error` branch in `residual_pii_findings`, so the base grade stands. | G8-S2 | AT-1, AT-2, AT-7 |
| M3 | Put `str(exc)` in the error message in place of the class name. | G8-S2 | AT-6, AT-7 |
| M4 | Put the passthrough exemption back before the `may_write` lookup. | G8-S2 | AT-4 |
| M5 | Put `if not fact.detectors: continue` back before the `identity_error` branch. | G8-S2 | AT-3 |
| M6 | In `_blocked.py`, stop mapping an `error` residual row to `check_error`. | G8-S2 | AT-7 (the only error row is residual, so the run passes and the test fails) |
| M7 | Drop `failed[name]` in `_suite_facts`. | G8-S2 | AT-11 (`test_a_table_whose_facts_fail_does_not_fail_the_other_table`) |
| M8 | Wrap the `_relationships()` call in `tee_reader` (and, as a second run, in `note_quarantined`) in an `except Exception: return` handler with no `passes_through` guard. | G8-S1 | AT-8 (a), AT-8 (b) |
| M9a | Remove `no_signal_label` from the scan. | G8-S2 | AT-9 |
| M9b | Add an entry to `post-scan-no-signal.json`. | G8-S2 | the "lists only live sites" test and the registry growth ratchet |
| M10 | Drop the `passes_through` guard from the identity handler. | G8-S2 | AT-5, the pass-through sentry |
| M11 | Remove the NumPy branch from `_number_key`. | G8-S1 | AT-12 |
| M12 | Remove the B8 backstop in `_frame_tables`. | G8-S1 | AT-13 |
| M13 | In `_report_only`, convert the tables before the handler (as on #784). | G8-S1 | AT-14 (a) |
| M14 | Restore the whole-suite-only predicate (`_NER_BLOCKED` or `fail` with `pass_failed_with`). | G8-S1 | AT-14(b), held output escapes despite the residual error |
| M15 | Drop the `passes_through` guard from the C7 handler. | G8-S1 | AT-15 |
| M16 | Widen the N1 handler back to `except Exception: return None`. | G8-S2 | AT-9 (live scan finds one site) |
| M18 | Move the NumPy branch in `_number_key` after the `float` check. | G8-S1 | AT-12 (the non-whole `np.float64` case) |
| M19 | Remove only the source diversity classification check, leaving the identity checks active. | G8-S1 | AT-13(b) |
| M20 | Restore plain conversion for the resident source alone, then for the output alone. | G8-S1 | AT-14(d) source dtype and output finding/dtype respectively |
| M21 | Handle NumPy integers before durations, then separately restore boolean string keys. | G8-S1 | AT-12 mixed duration and boolean pairs respectively |

M17 (revision 2, the relationship carrier) is withdrawn with the carrier.

## Compatibility

#784 carries the main behavior change, and its PR body, its `changelog.d/` entry and the PM-1a
entry in `docs/compatibility-contract.md` record it.

G8-S1 changes these observable behaviors:

- A resident run whose mixed-type column holds NumPy scalars now compares those cells as equal
  numbers. A leaking column that graded `info` now grades `fail` or `warning` as the frame
  check does. A run that passed can now block. That is the fix.
- A resident run whose text fallback cannot preserve equality, or whose Arrow conversion raises
  an exception outside the narrowed set, now gets one `error` row for the table and blocks.
- Resident suites preserve nullable integer cells for detector input on both sides, including unconfigured columns.
- A deferred gate enforcing NER withholds output on a residual comparison error even after a clean model pass.
- A deferred run whose suite or conversion fails now completes report-only with
  `pass_failed_with`, where it used to crash with a raw exception. Under `ner_findings: fail` it
  blocks with `check_error`.
- A coded error inside policy validation now propagates instead of becoming a policy `error`
  row. Both end the run; the coded error is the more precise one.

No report schema, reason code, exit code or public signature changes. G8-S1 adds a
`changelog.d/` entry and a line under the PM-1a entry in `docs/compatibility-contract.md`.
G8-S2 adds tests and a sentry only.

## Slices and size

| Slice | Repo | Risk | Size | Depends on |
|---|---|---|---|---|
| G8-S1 runtime: B8 key rule and backstop, B9 deferred handler and the `_blocked.py` rule, C7 guard, N1 narrowing, N2/N3 handler deletions | engine | R2 (changes grading and gate behavior) | 7 source files, about 140 changed source lines; 3 test files; 1 baseline shrink; internal helpers and the backstop exception, no new public API | #784 (stacks on `fix/postmask-fail-closed`, because `cell_text.py` is new in #784) |
| G8-S2 no-signal sentry and end-to-end pins | engine | R1 (tests and sentry only) | 1 new baseline file, 4 changed test and registry files, about 200 test lines; no `src/` change | G8-S1 (the empty baseline needs N1 to N3 gone) |

Placement, G8-S1 (existing files except for the conditional helper and changelog fragment):

| File | Change |
|---|---|
| `src/decoy_engine/verification/postmask/_column_facts.py` and `residual_pii.py` | Share the frame source count and constant-source predicate with B8 |
| `src/decoy_engine/internal/cell_text.py` | NumPy scalars in `_number_key` |
| `src/decoy_engine/verification/postmask/runner.py` | narrow `_native`; backstop in `_frame_tables` |
| `src/decoy_engine/verification/postmask/policy_validation.py` | Use the shared source classification and add the C7 guard |
| `src/decoy_engine/execution/pipeline/_post_scan.py` | shared conversion helper; `_report_only` handler; delete the N2/N3 `try`/`except` blocks |
| `src/decoy_engine/verification/postmask/_blocked.py` | `raise_if_ner_blocked` also raises on blocking `check_error` under NER enforcement |
| `tests/sentry/baselines/post-scan-pass-through.json` | delete the `policy_validation` entry |
| `tests/unit/detection_verification/postscan/test_column_suite_on_facts.py` | AT-12, AT-13 |
| `tests/unit/detection_verification/postscan/test_runner_pass_through.py` | AT-15 |
| `tests/unit/execution/post_scan/test_gate_rulings.py` | AT-8, AT-14 |
| `changelog.d/`, `docs/compatibility-contract.md` | Put the behavior note beside the PM-1a fragment and contract entry |
| `src/decoy_engine/execution/pipeline/_post_scan_suite.py` (conditional) | Resident frame builder beside `_post_scan.py` under the pipeline rule, #784 `CODEMAP.md:271` |

Line budget for `_post_scan.py` (checked item). The file is 600 lines on #784, the module-size
GOAL, with no census entry. G8-S1 must leave it at 600 lines or fewer, net change 0 or less.
Expected: the N2/N3 deletions remove about 10 lines, the shared conversion helper removes the
duplicated two-line conversion from `_column_suite` and `_report_only` (about 4 lines), and the
`_report_only` handler adds about 10. If the build still ends over 600, the conversion helper
moves to a new `src/decoy_engine/execution/pipeline/_post_scan_suite.py`, under the pipeline placement rule in #784 `CODEMAP.md:271`, beside
`_post_scan.py`, as `_post_scan_distribution.py` already does for the distribution check. No census entry is
added. Proof: `tests/sentry/test_module_size.py` green on the head (it fails a module over 600
with no entry), and the PR body records `wc -l` of the file on the base and the head.

Placement, G8-S2 (one new file under the sentry baseline rule in #784 `CODEMAP.md:295`):

| File | Change | Sits beside |
|---|---|---|
| `tests/sentry/post_scan/_scan.py` | add `no_signal_label`, `no_signal_sites()` | `pass_through_label`, `pass_through_sites()` |
| `tests/sentry/baselines/post-scan-no-signal.json` | new baseline, no entries | `post-scan-pass-through.json` |
| `scripts/dev/sentry_registry.toml` | `[[sentry]]` row `post-scan-no-signal` | the `post-scan-pass-through` row |
| `tests/sentry/_baseline_sources.py` | register the baseline | the other post-scan entries |
| `tests/sentry/post_scan/test_post_scan_choke_points.py` | AT-9, the AT-15 sentry half | the pass-through tests |
| `tests/unit/detection_verification/test_residual_pii_source_compare.py` | AT-5 extension, AT-6 | AT-1, AT-3 |
| `tests/unit/execution/post_scan/test_gate_rulings.py` | AT-7 | the gate ruling tests |

Steps, G8-S1:

1. Check whether #784 is merged. If it is open, branch from `fix/postmask-fail-closed` and
   retarget to `main` after it merges (check that the PR base is `main` before merge, so the
   stack does not strand work). Do not copy #784's changes.
2. Write AT-12, AT-13, AT-14, AT-15 and AT-8 first. Record each red on the base head (AT-8 is
   a pin and is green there).
3. Make the fixes. Record each test green. Check the line budget.
4. Run T0 per edit, then T1: `tests/unit/detection_verification/postscan`,
   `tests/unit/detection_verification/test_residual_pii_source_compare.py`,
   `tests/unit/execution/post_scan`, `tests/sentry/post_scan`,
   `tests/sentry/test_cell_text_choke_point.py`, `tests/sentry/test_module_size.py`, the
   ratchet and registry tests, and the `_blocked.py` unit tests. A baseline file shrinks, so
   run the sentry ratchet tests on the exact head.
5. Run M8, M11 to M15 and M18 to M21 and record them as stated above.

Steps, G8-S2:

1. Branch from the G8-S1 head (or `main` once it merges). Confirm AT-1 to AT-5 and AT-11 by
   test id on that head.
2. Add `no_signal_label`, `no_signal_sites()`, the empty baseline and both registrations. Add
   AT-9. Record AT-10.
3. Add the AT-5 extension, AT-6 and AT-7.
4. T0 and T1 as in G8-S1. No escalation trigger applies (tests plus one new empty baseline).
5. Run M1 to M7, M9a, M9b, M10 and M16 and record them.

Builder brief items (both slices): Conventional Commits subject, no body unless it says why,
last line `cam`, no other trailers. Test depth T0 per edit, T1 per commit. No data values or
exception text in any test log, assertion message or report. Raise outside `except` blocks;
never `raise ... from None` inside a handler. Do not raise any census, baseline or allowlist.
G8-S2 changes no file under `src/`. If a G8-S2 test fails on its base head, stop and report.

## Risk tier

G8-S1 is R2: it changes how the residual check grades a resident fallback column and how the
deferred gate ends. Review: Dennis, then Codex. G8-S2 is R1 (Codex only): tests and a sentry,
no runtime code. #784 has its own review track under the PM-1a plan.

## Failure modes this plan accepts

- The sentry is syntactic. A handler that assigns a dummy value and then returns no signal gets
  past it. AT-1 to AT-4 and AT-12 to AT-14 cover the real paths; the sentry covers the cheap
  regression.
- A column that no writer touches and no detector hits does not report a failed comparison
  (B3). Such a column has no masking and no PII signal, so the residual check has nothing to
  say. Policy validation does not see it either, because it is not configured.
- The B8 backstop fails the whole table, not one column, when a fallback column loses identity evidence or changes the source diversity classification.
  This is coarse but closed, and it needs no new per-column carrier in the runner. It is rare
  once the key rule knows NumPy scalars.
- A deferred gate without `enforces_ner` reports a failed suite and does not block. That is the
  deferred contract (the run result is stamped `post_scan_gate_deferred`).

## Review round 1 (Codex, NO-GO): resolutions

| Finding | Tier | Resolution |
|---|---|---|
| N1 fallback turns a leaking column into a pass (`np.float32` vs `int`) | V1 | S6, B8: NumPy scalars in the one key rule, plus a backstop that fails the table when the text keys count fewer identical rows than `identity_counts`. N1's handler is narrowed, so it is not baselined. AT-12 (pins the round 1 case), AT-13, M11, M12. G8-S1. |
| Deferred gate exposes a cell in `str(exc)`; `gate.report` is `None` | V1 | S7, B9: one conversion helper; `_report_only` runs it inside the class-only handler; `pass_failed_with`; blocks under `enforces_ner`. AT-14, M13, M14. G8-S1. |
| Sentry baseline not in `sentry_registry.toml` | should-fix | Registered in both the toml registry and `_baseline_sources.py`. The baseline starts empty, so it cannot grow without the ratchet failing (M9b). |
| AT-7 cannot isolate the residual verdict (policy error also present) | should-fix | AT-7 uses a writer-owned sibling with no policy entry and asserts the residual row is the only `error` row; M6 now dies on AT-7. |
| AT-5 lacks an object-identity assertion | should-fix | AT-5 extended: `excinfo.value is raised`, on two paths. |
| Mutations are proposals, not results | should-fix | Each mutation names its slice and must be recorded with the head SHA, the killing test id and the failing assertion. An unkilled mutation blocks the slice. |
| Inventory mixes reporting and blocking | should-fix | The inventory has a "Blocks" column. C3 (distribution), C8 under `warn` and C9b (source-side key baseline) are reporting by design; the rest block. |
| C7 lacks the B5 pass-through guard | should-fix | Guard added in G8-S1; its `post-scan-pass-through` baseline entry is deleted (the baseline shrinks). AT-15, M15. |
| N2/N3 relationship-read failure; AT-8 should require the FK row with the suite on; keys-only should block through `pass_failed_with` | should-fix | Revision 2 added a class-name carrier. Revision 3 replaces it (Dennis F1): the parse only raises the coded `PipelineConfigError`, which passes through, so it can never reach `pass_failed_with` or an FK row. The dead handlers are deleted and the coded error propagates and stops the run (B10). AT-8 pins that from all three entry points; M8 is its kill. |

## Review round 2 (Dennis, NO-GO on revision 2): resolutions

| Finding | Tier | Resolution |
|---|---|---|
| F1: the N2/N3 premise is false; the parse raises only the coded `PipelineConfigError`, which passes through | V1 | Carrier, its `_decide` read and M17 dropped. The `try`/`except` in `tee_reader` and `note_quarantined` is deleted and the coded error propagates (B10). AT-8 now asserts the same object (`is`) from `tee_reader`, `note_quarantined` and `run_resident`, outputs withheld, value-free. M8 is an unguarded handler around the parse, killed by AT-8. Round 1 row corrected. |
| F2: `raise_if_ner_blocked` raises only on `ner_blocked`, so `check_error` from `pass_failed_with` does not block | high | The rule goes in one place: `raise_if_ner_blocked` in `_blocked.py` also raises on blocking `check_error` under NER enforcement. The gate only calls it; no `secret_providers._errors` import in `_post_scan.py`. S7, B9, AT-14 (b) and M14 updated. |
| F3: `np.float64(1.5)` keys as `'np.float64(1.5)'` today | should-fix | The NumPy branch runs before the `float` check; the "except float64" wording is corrected. AT-12 adds non-whole values for every float type with the backstop not firing. M18 moves the branch after the `float` check. |
| F4: `_post_scan.py` is at 600 lines with no census entry | should-fix | Line budget: net change 0 or less, checked by `test_module_size.py` and `wc -l` in the PR body; named fallback `_post_scan_suite.py` for the helper; no census entry. |
| F5: AT-7 must name its mechanism | should-fix | AT-7 uses an unconfigured `contact` column with email-shaped synthetic values, expects `detector_id == "email"`, and forces only its batch comparison to raise as specified in AT-7. |
| F6: `1` vs `"1"` key collision | low | V2-LOG item 6. |
| F7: C7 rationale | low | Corrected: the guard is justified by B5; `passes_through` is False for `UnreadableCellError`. |
| F8: AT-9 fixtures | low | Added `except builtins.Exception` and `except (Exception,)`. |
| F9: #784 "stale reversions" | low | Reworded as a two-dot diff artifact; the update-from-main step stays. |
| CLI or run card shows `pass_failed_with` on a deferred run | low | V2-LOG item 7. The CLI does not read `pass_failed_with` today (no match in CLI `origin/main` `488d98b3`). |

## Impact on #784

#784 needs no code change for this plan. G8-S1 stacks on it and changes `cell_text.py`,
`runner.py` and `_post_scan.py`, which #784 also touches. Points for the #784 owner:

- S6 and S7 are pre-existing on main, not introduced by #784, so #784 can merge as it is.
- The `post-scan-pass-through` baseline entry for `policy_validation.py` keeps a reason that
  G8-S1 shows is not safe to rely on. G8-S1 deletes it; #784 need not.
- #784 is three commits behind `main`. A two-dot diff against `main` shows lines in
  `scripts/dev/sentry_registry.toml` that look like reversions; they are `main`'s newer commits,
  not changes in #784. Update #784 from `main` before its merge gate anyway, so G8-S1 and G8-S2
  stack on a current base.

## Owner questions

Both have a recommended default and are not high-risk, so the default applies unless the owner
says otherwise.

1. Fold G8-S1 into #784, or stack it? Default: stack. #784 is already under review, and G8-S1
   is R2 with its own red-before evidence.
2. A deferred run whose suite fails and that does not enforce NER: report-only, or block?
   Default: report-only, per the deferred contract. It still blocks under `ner_findings: fail`.

## V2-LOG

1. Distribution check blocking (C3). The distribution check is warn-only until its blocking
   slice. When that slice lands, a `_ValueTally` error must block in the same way as a residual
   `error` row. Not a leak check, so not in G8.
2. Source-side key baseline (C9b). A source-side read failure gives `baseline: error`, which
   warns. The output-side counts still block. Decide in the key-check backlog whether a missing
   baseline should block when the edge is declared `required`.
3. Per-column carrier in the runner fallback. The B8 backstop fails a whole table. A per-column
   `identity_error` from the runner would keep the other columns graded. Only needed if the
   backstop fires in practice.
4. A semantic no-signal check. The sentry is syntactic (see "Failure modes"). A data-flow check
   that every handler's recorded class name reaches a report row would close the dummy-value
   gap. Large for its value; revisit if the syntactic rule is bypassed.
5. NER under `warn` (C8). A model pass `error` is report-only under `warn`. That is the owner's
   SCAN-ML Q1 policy; revisit only if the default mode changes.
6. Key collision in the text fallback. `cell_text` gives `1` and `"1"` the same key, while
   pandas `==` says they differ, so the text keys can count more identical rows than
   `identity_counts`. With the source classification and the denominator preserved, B8 allows extra identity matches because they only increase identity evidence (a
   possible false `fail` on a constant-like column, never a missed leak). Revisit if it gives
   false blocks in practice.
7. Show `pass_failed_with` to the user. On a deferred run without NER enforcement, a failed
   suite is in the report but the CLI does not read `pass_failed_with` (no match in the CLI at
   `488d98b3`); the run card was not checked. Add a CLI line and, if missing, a run card line so the user sees "the post-mask check could not run" on a deferred run.
