# Post-mask leak check fails closed (G8)

Status: plan

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN
phase), `bugfix.md`, `testing.md` (test depth), `cross-cutting-concerns.md`,
`proportionality.md`.

Row: POSTMASK-FAIL-CLOSED (G8, owner 2026-11-24, blocks 1.0). Source: the F34 FRAME finding,
CLI `docs/roadmap/row-detail.md` section F34 (row 67).

Code references: engine `origin/main` at `9f7bb1f4a` unless marked `#784`, which means engine
PR #784 (branch `fix/postmask-fail-closed`) at `c2ca4f531`. Paths start at
`src/decoy_engine/verification/postmask/` unless they start with `src/` or `tests/`.

## Read this first: most of the fix is already in review

The core of this row is already built in open PR #784, which is slice PM-1a of
`docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md` on branch
`plan/pmfc-ratchet-growth`. #784 deletes `_source_identity`. The frame path then records a
failed comparison as `identity_error`, as the batch path already did, and reports it as an
`error` finding. It does this also when no detector hit the column, and also on a passthrough
that another writer may own. #784 takes `_source_identity` off the `post-scan-pass-through`
sentry baseline and has tests that force the comparison to raise on both paths.

This plan does not build that again. It does three things:

1. It states the G8 behavior as acceptance criteria, so the row can close against #784.
2. It lists every swallow site on main and gives each one a status on #784.
3. It adds one small slice, G8-S1, for the part #784 does not cover: a sentry that stops a
   broad handler from turning a failure into "no signal", and two end-to-end pins.

The row closes when #784 and G8-S1 are both merged.

## Guarantee and non-goals

Guarantee: in the post-mask column suite and its gate caller, an exception that is not a coded
engine error never makes a column look clean. It becomes an `error` row that names the
exception class only, and a required gate blocks on it.

Non-goals: new reason codes, a new finding type, a schema version change, changes to the FK,
distribution or model checks beyond the pins below, and the PM-1b and PM-1c slices of the
existing PM plan.

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
- B5. An exception that `passes_through` (a coded engine error) propagates unchanged. It does
  not become a finding.
- B6. The finding and every log line are value-free. They carry table, column, detector id,
  strategy and the exception class name only. No cell value, column value or exception text.
  Raises happen outside `except` blocks; no `raise ... from None` inside a handler.
- B7. An `error` residual finding makes the gate verdict `post_scan.check_error`. When the gate
  is required and not deferred, that raises `PostScanBlockedError`, the outputs are withheld,
  and the CLI exits 4 (CLI `src/decoy/cli/exit_codes.py:204,259`). On a deferred (report-only)
  run, the row is in the report and `error_count` counts it.

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

The reason code is the existing `post_scan.check_error`
(`src/decoy_engine/reasons/post_scan/_part1.py:18`). `_blocked.py` picks it for any residual
`error` row. The report counts the row in `error_count` (`_blocked.severity_counts`). The run
card shows the post-scan report as it does today; no new field is needed.

Policy validation keeps its own per-column error (`policy_validation.py:134`, `_compare_failed`
at :157) for configured columns. So a configured column whose comparison raises gets one policy
error and one residual error. That is intended, because they are two checks.

## Swallow sites

These are every broad handler and every "return no signal" branch in the post-mask package and
its gate caller. They were found by an AST scan of `verification/postmask/` and
`src/decoy_engine/execution/pipeline/_post_scan.py` on both heads, plus a read of the
`continue` and exemption branches in `residual_pii_findings`.

### Sites that lose a failure (the G8 class)

| # | Site (main) | What it does on main | Status |
|---|---|---|---|
| S1 | `residual_pii.py:255-274` `_source_identity` | `except Exception: return None`. A raised comparison looks like "no source". Frame path only. | Fixed in #784: `_frame_column_facts` records `identity_error`. |
| S2 | `residual_pii.py:511` `if not fact.detectors: continue` | A column with `identity_error` and no detector hit gives no finding. Production path. | Fixed in #784, for columns the run may write. |
| S3 | `residual_pii.py:518,552` passthrough exemption | `configured not in _NO_OP_BY_DESIGN` drops `identity_error` on a passthrough column, also one that a joint mask or FK cascade writes. Production path. | Fixed in #784: exempt only when `may_write` proves no other writer. |
| S4 | `residual_pii.py:541-543` failed source distinct count | Read as "varied" (`max(..., 2)`), which can change the grade without saying so. | Fixed in #784: the grade stays when both answers agree, else `error`. |
| S5 | `residual_pii.py` `check_residual_pii` | No per-table isolation, so one bad table raises out of the whole frame check. Not a swallow, but the two paths disagree. | Fixed in #784. |

S1 has no production caller on main. The engine and the CLI call only the facts path, which
already records `identity_error` (`_column_facts.py:345`). S1 is still a public function, so it
counts. S2 and S3 are on the production path and are the real fail-open cases today.

### Sites that already fail closed (pin, no change)

| # | Site (main) | Why it is closed |
|---|---|---|
| C1 | `_column_facts.py:345` `column_facts` | records `identity_error` by class name |
| C2 | `_column_facts.py:289-302` `_distinct_or_error` | returns the class name; `distinct_error` is set |
| C3 | `_column_facts.py:127` `_ValueTally.add` | records `error`; the distribution check reports it |
| C4 | `runner.py:235` `_frame_tables` | `failed[name]`, one `error` per table |
| C5 | `runner.py:420` `_suite_facts` | `failed[name]`, one `error` per table |
| C6 | `runner.py:287,312,333` check wrappers | one `error` row per check, class name only |
| C7 | `policy_validation.py:134` `_check_one_column` | `_compare_failed` error finding |
| C8 | `_model_findings.py:200` | one `error` row per model pass |
| C9 | `_keys.py:175,217,235` | key status `error` |
| C10 | `src/decoy_engine/execution/pipeline/_post_scan.py:200,208` `_decide` | `pass_failed_with`, then `check_error` |

### Sites that return "no signal" on purpose

| # | Site (main) | Why it is not a lost failure |
|---|---|---|
| N1 | `runner.py:167-173` `_native` returns `None` | Not a check result. `None` selects the text conversion, which always succeeds, so the column is still checked. |
| N2 | `_post_scan.py:222-232` `tee_reader` returns `None` | An unreadable relationship turns off the key tee only. The FK check reads the relationships again and reports the failure (C6). |
| N3 | `_post_scan.py:292-306` `note_quarantined` returns | Same as N2: the FK check reports the failure. |

N1 to N3 are the baseline of the G8-S1 sentry. Each gets a pin test that shows the failure is
reported somewhere else (AT-8).

## Enumerations

### Exit paths

The ways a column comparison can end, and what each one must give:

- Comparison succeeds: graded finding as today (`residual_pii.py:518`).
- Comparison raises a non-coded exception: one `error` row (S1 to S3 above).
- Comparison raises a coded `DecoyError`: propagates unchanged (`passes_through`, B5).
- No evidence (no source, unequal rows, zero comparable rows): no `error` (B4).
- Whole table fails before the column loop: one `error` per table (`runner.py:235`,
  `runner.py:420`).
- The check wrapper itself raises: one `error` per check (`runner.py:287`).

### Routes

- Resident frame route: `check_residual_pii` (frame path, B2).
- Resident gate route: `PostScanGate.run_resident` -> `run_post_mask`
  (`src/decoy_engine/execution/pipeline/_post_scan.py:189`).
- Streamed commit route: `before_commit` -> `run_post_mask_tables` over staged row groups.

All three end in the same `_blocked.py` verdict, so AT-7 on the resident gate and AT-2 on both
column paths cover them.

### FK shapes

N/A: this row changes no key handling. The FK check is touched only by the N2 and N3 pins (AT-8),
which assert that a relationship read failure still reaches an `fk_preservation` `error` row.

### Fields

- `ResidualPIIFinding.severity`: `"error"` on a raised comparison.
- `ResidualPIIFinding.source_compared`: `False`.
- `ResidualPIIFinding.source_identity_rate`: `None`.
- `ResidualPIIFinding.message`: class name only, no value.
- Report `error_count`: counts the row.

### Output surfaces

- The post-scan report dict and JSON (the finding row and `error_count`).
- The `PostScanBlockedError` verdict codes and the CLI exit code.
- Job log lines from the check (class name only, B6).
- The run card, which shows the report as it does today.

## Defect classes

| # | Class | Applies here | Closing structure | Proof |
|---|---|---|---|---|
| 1 | Value-bearing output | Yes: a finding or log line could carry the exception text or a cell. | Class name only in `_compare_raised`; raise outside `except` | AT-6, AT-7 with a seeded value; mutation M3 |
| 2 | Cleanup on an exit path | N/A: the slice adds no resource, file or staging step. | none | none |
| 3 | State machine and concurrency | N/A: the column suite is single-threaded per table and keeps no state across calls. | none | none |
| 4 | Route parity and silent fallback | Yes: this is the G8 class (a failure turned into "no signal"). | One carrier (`identity_error`) on both paths; no-signal sentry | AT-2 parity, AT-9 sentry; mutations M1, M9 |
| 5 | Referential integrity | N/A: no key handling changes; N2 and N3 are pinned only. | none | AT-8 |
| 6 | Untrusted producer | N/A: the exception comes from in-process pandas or Arrow code, and only its class name is read. | none | AT-6 |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is checked or opened. | none | none |
| 8 | Weak tests and overclaimed evidence | Yes: "exists" tests must be shown green on the merge head, and red-before recorded. | AT-10 red-before; mutation table with heads | Mutations M1 to M10 on the final head |
| 9 | Behavior-preserving refactor drift | N/A: no refactor; the slice adds tests and a sentry label only. | none | none |
| 10 | Frozen contract drift | N/A: no schema, reason code or exit code changes in G8-S1 (see Frozen contracts). | none | none |

## Reuse inventory

- `ColumnFacts.identity_error` and `distinct_error`: the existing failure carrier.
- `residual_pii_findings` and #784 `_compare_raised`: the existing error finding.
- `post_scan.check_error` and `_blocked.py`: the existing verdict.
- `tests/sentry/post_scan/_scan.py` (`sites`, `scan`, `_broad`, `_opens_with_pass_through`):
  the new label reuses these helpers.
- The ratchet baseline format and loader in `tests/sentry/_baseline_sources.py`.

Nothing new is built where one of these fits.

## Frozen contracts

- `post-scan-integrity/v3` report schema: unchanged.
- `ResidualPIIFinding` fields and the `Severity` literal: unchanged.
- Reason codes (`post_scan.check_error`): unchanged.
- CLI exit codes (exit 4 for a post-scan block): unchanged.
- `check_residual_pii` signature: #784 adds an optional keyword only.

## Pre-mortem

- #784 changes again before merge and moves a test that this plan names. Mitigation: step 1
  checks the names on the merge head and updates the AT table, not the criteria.
- The no-signal label also flags handlers outside the G8 scope as the package grows, and people
  add baseline entries to get past it. Mitigation: the baseline is shrink-only, and each entry
  needs a reason and a pin test like AT-8.
- AT-7 is slow because it runs a full gated pipeline. Mitigation: use the smallest resident
  config already used in `test_gate_rulings.py`.

## Sentry: yes, one narrow rule

Choke point. The choke point for "a comparison failed" is already in place.
`ColumnFacts.identity_error` and `distinct_error` (`_column_facts.py`) are the one carrier, and
`residual_pii_findings` (#784 `_compare_raised`) is the one place they become a finding.

Gap. The existing `post-scan-pass-through` sentry (`tests/sentry/post_scan/_scan.py`
`pass_through_label`, baseline `tests/sentry/baselines/post-scan-pass-through.json`) checks
only that a broad handler opens with the `passes_through` guard. S1 on main shows the gap: a
guarded handler, or a baselined unguarded one, can still end in `return None` and lose the
failure.

Guard. Add one label to the same scan, with the same scope (`verification/postmask` and
`execution/pipeline/_post_scan.py`), and a shrink-only baseline in the same format:

- `no_signal_label` flags a broad handler (bare `except`, `except Exception`,
  `except BaseException`, or a tuple that holds one of them) whose body, after the optional
  `passes_through` guard, holds only `pass`, `continue`, `return` or `return None`. A handler
  that assigns, appends, calls, returns any other value or raises is clean.
- Baseline `tests/sentry/baselines/post-scan-no-signal.json`, `sentry_id`
  `post-scan-no-signal`, with entries N1, N2 and N3 and a reason for each. Keys use the
  existing `path::scope::label::ordinal` form. Register it where `tests/sentry/_baseline_sources.py`
  registers the other post-scan baselines.
- Tests go in `tests/sentry/post_scan/test_post_scan_choke_points.py`, next to the pass-through
  tests: no site beyond the baseline, the baseline lists only live sites, and the fixture cases
  in AT-9.

Mutation that must turn the guard red: put `except Exception: return None` back into the
identity comparison in `residual_pii.py` (M1).

The sentry does not prove that a recorded error reaches a finding. AT-1 to AT-4 do that. The
sentry stops the cheapest way back to the defect: a new `return None` in a handler.

Where it sits. It goes in `tests/sentry/post_scan/`, not `tests/sentry/defects/`, because the
scope is the post-scan package and it reuses `_scan.py`. The
`tests/sentry/defects/test_exception_context.py` ratchet already covers `raise ... from None`
inside a handler, so G8-S1 adds nothing for that.

## Established solutions

Search run: the codebase (the four post-scan sentries in `_scan.py`, the defects ratchets) and
the usual linters. Ruff already has the generic rules: `S110` (try-except-pass), `S112`
(try-except-continue) and `BLE001` (blind except). The engine ignores `S110` and `S112`
globally until the lint-debt ratchet reaches the engine (development loop, "Agent pre-checks"),
and none of them catches `return None` in a handler. So the plan follows the repo's existing
pattern: an AST label in `_scan.py` with a shrink-only JSON baseline, which is the shape of the
four post-scan sentries. The custom part is one label function of about 20 lines.

## Acceptance tests

"Exists" means the test is in #784; G8-S1 only checks that it is there and green on the merge
head. "New" means G8-S1 adds it. Paths under `tests/unit/detection_verification/` are shortened
to start there.

| # | Test | Kind | Where |
|---|---|---|---|
| AT-1 | Force the frame comparison to raise. One `error` finding for the column, `source_compared` False. | red-before on main, exists | `test_residual_pii_source_compare.py::...::test_frame_path_comparison_raise_is_error_finding` |
| AT-2 | The same cells through the frame path and the batch path give equal findings, including the case where equality raises. | red-before, exists | `test_residual_pii_source_compare.py::...::test_same_findings_on_both_paths[equality raises]` |
| AT-3 | A raised comparison on a column that no detector hits and the run writes is one `error`. | red-before, exists | `test_residual_pii_source_compare.py::...::test_failed_comparison_without_a_detector_hit_is_an_error` |
| AT-4 | A raised comparison on a passthrough column that another writer owns is one `error`, with or without a hit. A proven passthrough stays quiet. | red-before, exists | `postscan/test_writer_ownership_findings.py::test_an_owned_passthrough_reports_a_failed_comparison_without_a_hit`, `..._with_a_hit`, `test_a_proven_passthrough_in_a_sibling_table_stays_quiet` |
| AT-5 | A coded error raised inside the comparison propagates as the same object. | pin, exists | `test_residual_pii_source_compare.py::...::test_frame_path_passes_through_exception_propagates` |
| AT-6 | Value-free: the forced exception's message holds a seeded email. Assert that the seeded value and the exception text are in no finding field, not in the report dict and not in any captured log record. | new (extend AT-1 and AT-3) | `test_residual_pii_source_compare.py` |
| AT-7 | End to end: a gated resident run whose column comparison raises ends with `PostScanBlockedError`, first code `post_scan.check_error`, outputs withheld, `error_count` 1, no seeded value in the report. A deferred run with the same input completes and keeps the row. | new | `tests/unit/execution/post_scan/test_gate_rulings.py` |
| AT-8 | N2 and N3: make the gate's relationship read raise. The tee is off, and the report still holds an `fk_preservation` `error` row with `check_error` in the verdict. N1: a column Arrow refuses is still compared. | new for N2 and N3; N1 pin exists (`postscan/test_column_suite_on_facts.py::test_a_zip_column_of_mixed_int_and_str_is_compared_as_on_the_frame_checks`) | `tests/unit/execution/post_scan/test_gate_rulings.py` |
| AT-9 | Sentry fixtures. Flagged: `return None`, bare `return`, `pass` and `continue` after the guard, for bare `except` and for a tuple that holds `Exception`. Clean: an assignment, an append, a returned finding, a re-raise. A seeded `except Exception: return None` in a scratch copy of `residual_pii.py` raises the count by one. | new | `tests/sentry/post_scan/test_post_scan_choke_points.py` |
| AT-10 | Run the new label on main's `residual_pii.py`; it flags `_source_identity`. Record this red-before in the PR body. | red-before evidence | PR body |
| AT-11 | The closed sites C1 to C10 keep their tests: failed comparison, failed distinct counts, table isolation and the unconvertible table in `postscan/test_column_suite_on_facts.py`; `postscan/test_runner_pass_through.py`; `postscan/test_value_free_check_errors.py`. | pin, exists | as named |

## Mutations the tests must kill

Run each on the G8-S1 head and record the test that turns red.

| # | Mutation | Killed by |
|---|---|---|
| M1 | Make the identity handler in `_frame_column_facts` return facts with no `identity_error` (S1 again), or end in `return None`. | AT-1, AT-2, AT-9 |
| M2 | Remove the `identity_error` branch in `residual_pii_findings`, so the base grade stands. | AT-1, AT-2, AT-7 |
| M3 | Put `str(exc)` in the error message in place of the class name. | AT-6, AT-7 |
| M4 | Put the passthrough exemption back before the `may_write` lookup. | AT-4 |
| M5 | Put `if not fact.detectors: continue` back before the `identity_error` branch. | AT-3 |
| M6 | In `_blocked.py`, stop mapping an `error` residual row to `check_error`. | AT-7 |
| M7 | Drop `failed[name]` in `_suite_facts`. | AT-11 (`test_a_table_whose_facts_fail_does_not_fail_the_other_table`) |
| M8 | Make the FK check swallow a relationship read failure. | AT-8 |
| M9 | Remove `no_signal_label` from the scan, or delete one baseline entry. | AT-9, the baseline tests |
| M10 | Drop the `passes_through` guard from the identity handler. | AT-5, the pass-through sentry |

## Compatibility

G8-S1 adds tests, one sentry label and one baseline file. It changes no output bytes, no report
schema (`post-scan-integrity/v3` stays), no reason code and no exit code.

The behavior change is in #784. Its PR body, its `changelog.d/` entry and the PM-1a entry in
`docs/compatibility-contract.md` already record it. A run whose source comparison raises on a
column the run may write now gets an `error` finding. On a required gate that run now blocks
with `check_error` (CLI exit 4), where main passed it. That is the fix, not a regression.
Configs whose comparison does not raise see no change in output bytes, findings or exit code.
`ResidualPIIFinding` gets no new field. `check_residual_pii` keeps its signature; #784 adds
only an optional `writes=` argument.

## Slices

One slice.

| Slice | Repo | Risk | Size | Depends on |
|---|---|---|---|---|
| G8-S1 no-signal sentry and G8 end-to-end pins | engine | R1 | About half a day. No new public names. | #784 merged |

Placement (no new source files):

| File | Change | Sits beside |
|---|---|---|
| `tests/sentry/post_scan/_scan.py` | add `no_signal_label`, `no_signal_sites()` | `pass_through_label`, `pass_through_sites()` |
| `tests/sentry/baselines/post-scan-no-signal.json` | new baseline, 3 entries | `post-scan-pass-through.json` |
| `tests/sentry/_baseline_sources.py` | register the baseline | the other post-scan entries |
| `tests/sentry/post_scan/test_post_scan_choke_points.py` | AT-9 | the pass-through tests |
| `tests/unit/detection_verification/test_residual_pii_source_compare.py` | AT-6 | AT-1, AT-3 |
| `tests/unit/execution/post_scan/test_gate_rulings.py` | AT-7, AT-8 | the gate ruling tests |

Steps:

1. Check that #784 is merged and that AT-1 to AT-5 and AT-11 are green on main. If #784 is
   still open, stack on `fix/postmask-fail-closed` and retarget after it merges. Do not copy
   its source changes.
2. Add `no_signal_label`, `no_signal_sites()` and the baseline (N1, N2, N3). Add AT-9. Record
   AT-10.
3. Add AT-6, AT-7 and AT-8.
4. Run T0 on the touched files, then T1: the post-scan unit tests, `tests/sentry/post_scan`,
   `tests/unit/execution/post_scan` and the repo guard tests. No escalation trigger applies
   (tests plus one sentry baseline), so there is no full suite at the slice.
5. Run M1 to M10 and list the test that killed each in the PR body.

Builder brief items: Conventional Commits subject, no body unless it says why, last line `cam`,
no other trailers. Test depth T0 per edit, T1 per commit. No data values or exception text in
any test log or message. Raise outside `except` blocks; never `raise ... from None` inside a
handler. No source code changes. If a new test fails on main after #784, stop and report; do
not change `src/` in this slice.

## Risk tier

R1 (Codex only) for G8-S1. It adds tests and a sentry and changes no runtime code. The risky
part of G8 (the grading change, writer ownership, the effect on the verdict) is #784, which has
its own review track under the PM-1a plan.

## Failure modes this plan accepts

- The sentry is syntactic. A handler that assigns a dummy value and then returns no signal gets
  past it. AT-1 to AT-4 cover the real path; the sentry covers the cheap regression.
- A column that no writer touches and no detector hits does not report a failed comparison
  (B3). Such a column has no masking and no PII signal, so the residual check has nothing to
  say. Policy validation does not see it either, because it is not configured.
