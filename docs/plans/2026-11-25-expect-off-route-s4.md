# EXPECT-OFF-ROUTE S4: show every check on the run card and in JSON

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
reuse-first, catalogs/recurring-defects; owner notes on the value-free class (F31), the
express-all-capabilities rule, plan-defines-acceptance-tests and the engine repin checklist.

Row: EXPECT-OFF-ROUTE, slice S4 (holds the CLI row EXPECT-REPORT). Parent plan:
`docs/plans/2026-11-22-expect-off-route.md` rev 6 (sections 3, 4 "Output surfaces", 9 V10 to V12,
and the S4 entry in section 11).

Risk: R3 (frozen `--json` shape, error payload, engine warnings channel). Size: engine about +40
and docs; CLI about +120 and tests. Depends on: engine half after S3b (so every route stamps one
report); CLI half after an engine release that carries S1 to S3b and the engine half, and after
the CLI repins to it. Anchors: engine main `2b8a47fbe`, CLI main `d6b9e4c7`. The builder
re-anchors both first.

## Problem

- A passing check is not reported. Neither the run card nor `decoy run --json` reads
  `quality_metrics["validation"]` (CLI `src/decoy/cli/run/_render.py:106-216`).
- The engine builds a `leak_check_column_not_checked` warning for a column that `columns:` names
  and the check skipped (engine `execution/_pipeline_finalize.py:361-378` on main), but it only
  lands in `quality_metrics["validation"]["warnings"]`. The run's `warnings` list, which the CLI
  counts and renders (CLI `src/decoy/cli/run/_execute.py:514`, `_render.py:112-115`), never sees
  it.
- `decoy validate` is silent when `expect leak_check` names a column the config keeps
  (`passthrough`), even though `plan_scope` (engine `validators/_scope.py:144`) can tell from the
  config alone.

## Guarantee

1. Every configured `validators:` entry appears on the run card and in `decoy run --json` with
   its status (`passed`, `failed` or `skipped`), on success and on a validator failure (exit 3).
2. A column that `columns:` names and the check did not check produces one `QualityWarning` in
   the run's warnings. The run still exits 0.
3. `decoy validate` warns, from the config alone, about each named column that `plan_scope`
   rules out.
4. Nothing new carries a data value: names, codes, counts and statuses only.

Non-goals:

- No change to any verdict, route or exit code. A validator failure stays exit 3.
- No change to `--post-validate-enforce` or the `post_validation` check.
- No new `CheckId` in the engine `RunResult` document in this slice (open item below).

## What exists (reuse, do not rebuild)

- Engine: `ValidationReport.results` and `ValidatorResult` (`validators/_types.py:77-93`:
  `validator`, `entry_index`, `status`, `checked`, `skipped`, `failing_row_count`);
  `result_status` (`:96`), the one status rule; `SkippedColumn` (`:68`); `plan_scope` and
  `unchecked_named_columns` exported from `decoy_engine.validators` (`validators/__init__.py:71`);
  `_unchecked_column_warnings` (`_pipeline_finalize.py:361`); after S2, `stamp_validation`, the
  one writer of `quality_metrics["validation"]` (#812 `_pipeline_finalize.py:381`).
- CLI: the run card facts list and `render_card` (`_render.py:161-188`); the `--json` payload
  (`_render.py:116-150`); `warning_records` and `render_warnings`; the failure path
  `src/decoy/cli/run/_errors.py:172` `fail`; the shape snapshot
  `tests/fixtures/release_freeze/json-shapes.json` (`run` entry with `paths`, `optional_keys`,
  `opaque_values`); `src/decoy/cli/validate.py` `_emit_result` (`:175`).

## Design

### Engine half (one PR)

1. Warnings channel: `stamp_validation` also hands each `leak_check_column_not_checked`
   warning to the run's warning collector, the same path every other `QualityWarning` takes to
   `PipelineResult.warnings`. The builder finds that path first and names it in the PR. The
   copy in `quality_metrics["validation"]["warnings"]` stays (it is in the evidence manifest).
2. Docs: rows in `docs/qa/14-casting-validators-quarantine.md` and
   `docs/qa/15-execution-routes-native.md`; the `leak_check` paragraph at
   `docs/strategies.md:2338-2348` says which columns are skipped and that a named skip warns;
   compatibility contract entry for the new warning on `PipelineResult.warnings`.

### CLI half (one PR, after the repin)

1. New `src/decoy/cli/run/_checks.py` (about 90 lines): `validation_member(metrics)` reads
   `quality_metrics["validation"]["validators"]` with a strict reader and returns
   `{"passed": bool, "results": [{"validator", "entry_index", "status", "failing_row_count",
   "skipped": [{"table", "column", "code"}]}]}`, or `None` when no validators ran.
   `checks_fact(member)` returns the card fact (`Checks  2 passed`, `Checks  1 failed, 1 passed`)
   and `check_lines(member)` the lines under the card, one per failed or skipped entry
   (`leak_check customers.email failed`, `leak_check customers.phone skipped
   (leak_check_skip_passthrough)`). The strict reader refuses a bool or numeric-string
   `failing_row_count`, a `status` outside the three values and a non-string name, and ignores
   unknown extra fields.
2. `_render.py`: add `payload["validation"]` when the member is not `None`; add the fact after
   `Warnings`; print the lines after `render_warnings`. About +12.
3. `_errors.py` `fail`: when the engine error is `ValidatorFailedError`, put the same member,
   built from `exc.report`, in the error payload. About +8.
4. `validate.py`: for each `leak_check` entry, call `plan_scope(config, entry)` and print one
   warning per `config_skips()` row whose column the entry names in `columns:`. Exit code stays 0.
   About +15.
5. `json-shapes.json`: `run` gains optional `/validation` with typed paths; the error shape gains
   the same optional member.
6. Docs: the expect section of `docs/guides/decoy-language/05-checks-and-subsets.md` shows the
   `Checks` fact and the warning. CHANGELOG entry.

Choke point: `_checks.validation_member` is the one CLI reader of the validation block; the card,
`--json` and the error payload all call it. Guard: V11's reader cases. Mutation: read
`failing_row_count` with `int()` instead of the strict reader (V11 numeric-string case red).

Design notes: one new private module, because the reader, the fact and the lines are one concern
and `_render.py` (239 lines) should not take a parser. It follows the existing
`post_scan_members` pattern, a member builder beside the renderer.

### Placement

| New or changed | Path | CODEMAP rule | Sits beside |
|---|---|---|---|
| Validation reader and card lines | CLI `src/decoy/cli/run/_checks.py` | `decoy run` modules in `src/decoy/cli/run/` | `_render.py`, `_result.py` |
| Run card and JSON | CLI `src/decoy/cli/run/_render.py`, `_errors.py` | existing | |
| Validate warning | CLI `src/decoy/cli/validate.py` | existing | |
| CLI tests | CLI `tests/unit/cli/run/test_run_checks.py`, `tests/unit/cli/test_validate_leak_scope.py` | unit tests beside the command | |
| Engine warnings | engine `src/decoy_engine/execution/_pipeline_finalize.py` | existing | |
| Engine test | engine `tests/unit/validators/test_unchecked_column_warning.py` | `tests/unit/validators/` | |

## Behavior and failure modes

| Case | Card | `--json` | Exit |
|---|---|---|---|
| Two passing checks | `Checks  2 passed` | `validation.passed = true`, two results | 0 |
| One failing `leak_check` | `Checks  1 failed: leak_check customers.email` on the error card | error payload has `validation` | 3 |
| `email: passthrough`, `leak_check(columns: {customers: [email]})` | `Checks  1 skipped`, a skip line, `Warnings 1` | result `status = "skipped"`, warning `leak_check_column_not_checked` | 0 |
| Default scope, a passthrough column | skip recorded, no warning | skip in `results[].skipped` | 0 |
| No validators | no fact | no `validation` key | 0 |
| Malformed block (bool count, unknown status) | no fact; one internal-error warning line, no value | no `validation` key | 0 |
| `decoy validate` with `keep email` and `expect leak_check(customers.email)` | one warning naming `customers.email` and the reason | warning in the JSON result | 0 |

## Acceptance tests (red first)

From the parent plan: V10 engine half (warning reaches `result.warnings`), V11, V12.

1. **V10e (engine, red-before).** `email: passthrough` with `leak_check` naming
   `customers.email`: `PipelineResult.warnings` has one `leak_check_column_not_checked` with
   `column="email"` and the table in `detail`. Red on main: the warning exists only in
   `quality_metrics`.
2. **V11 card and JSON (CLI, red-before).** Pass, fail (exit 3) and skip runs as in the table;
   `--json` carries `validation` on success and on failure; the shape snapshot is updated. Reader
   cases: bool count, `"3"` count, status `"ok"`, extra field. Red on main: no fact, no member.
3. **V12 validate warning (CLI, red-before).** As in the table. Red on main: silent.
4. **V13c value-free (CLI, control).** A run with a marker value in every validated column and
   every check failing: the marker is in no card line, JSON member, warning or error payload.

Mutations:

| ID | Mutation | Test that must fail |
|---|---|---|
| R1 | `int()` in place of the strict count reader | V11 numeric-string case |
| R2 | Drop the member from the error payload | V11 failure case |
| R3 | Print only failed entries (skip lines dropped) | V11 skip case |
| R4 | Keep the warning in `quality_metrics` only | V10e |
| R5 | `validate.py` warns for default-scope skips too | V12 default-scope case |
| R6 | Put `finding.detail` text into a check line | V13c |

## Enumerations

### Exit paths

- Success: `_render.finish` (CLI `src/decoy/cli/run/_render.py:106`), exit 0, or 4 under
  `--post-validate-enforce` (unchanged).
- Validator failure: `ValidatorFailedError` to `_errors.fail` (CLI
  `src/decoy/cli/run/_errors.py:172`), exit 3, payload gains `validation`.
- Refusal before the run: `_errors.refused` (`:364`), no validation member.
- `decoy validate`: exit 0 with warnings; errors unchanged.

### Routes

- Every engine route stamps one report through the session after S3b. The CLI reads the block,
  not the route; V11 runs on the default route and on a forced out-of-core run.
- Preview mode (`finish_preview`, `_render.py:218`): no validation member (preview does not run
  validators).

### FK shapes

N/A. The keyed validators' results show like any other entry; keys are not printed.

### Fields

| Field | Source | Rule |
|---|---|---|
| `validation.passed` | `ValidationReport.passed` | bool |
| `results[].validator` | `ValidatorResult.validator` | registered name |
| `results[].entry_index` | `ValidatorResult.entry_index` | int, not bool |
| `results[].status` | `result_status` | one of three |
| `results[].failing_row_count` | `ValidatorResult.failing_row_count` | int, not bool |
| `results[].skipped[]` | `SkippedColumn` | table, column or null, registered code |

### Output surfaces

- Run card fact `Checks` and the lines under the card.
- `decoy run --json` member `validation` (success and error payloads).
- Run `warnings` (engine `PipelineResult.warnings`, CLI `warnings` array).
- `decoy validate` human and JSON output.
- Shape snapshot and the decoy-language guide.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Member and lines built from names, codes and counts; `detail` never read | V13c | R6, detail text in a line |
| 2 | Cleanup on an exit path | N/A: no resources opened; the error payload is built from the exception's report | V11 failure case | N/A |
| 3 | Shared state | N/A: pure functions of the metrics dict | V11 | N/A |
| 4 | Route parity and silent fallback | One reader for card, JSON and error payload; a malformed block shows an internal-error line, never a silent pass | V11 malformed case | R2, member dropped on failure |
| 5 | Referential integrity | Skip codes are registered warning codes; the reader checks them against the engine registry | V11 skip case | Accept any string code: V11 red |
| 6 | Untrusted producer | The engine block is parsed strictly (engine and CLI may run different pins) | V11 reader cases | R1, `int()` reader |
| 7 | Check-then-use (toctou) | N/A: the metrics dict is read once after the run returns | none needed | N/A |
| 8 | Weak tests | Each red-before shown red on main; V13c guards new fields | builder report | R3, skip lines dropped |
| 9 | Refactor drift | `_render.py` keeps its existing facts and order; snapshot diff shows only the new paths | shape snapshot test | N/A |
| 10 | Frozen contract drift | `json-shapes.json` updated with optional paths; compatibility contract names the warning | release-freeze shape test | Remove the snapshot update: shape test red |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Status compared to the exact three values; codes checked against the registry |
| 2 | Strict wire types | Bool and numeric strings refused for integer fields (R1) |
| 3 | No exception context | No new raise; the error payload reuses the existing fail path |
| 4 | Versioned read models | Unknown extra fields ignored, so a newer engine still reads |
| 5 | Normalized guard scanners | N/A: no scanner added |
| 6 | Private modules | `_checks.py` private; uses only public engine names (`plan_scope`, `ValidatorFailedError`) |
| 7 | No hidden CI failures | No skip marks; the CLI half lands only after the repin, so tests run on the real engine |
| 8 | One input, one trust class | The metrics block is engine output, treated as untrusted shape (cross-version) |
| 9 | Mutations on the final head | R1 to R6 after the last change |
| 10 | Allowlisted helpers still checked | N/A: no allowlist added |
| 11 | No raised caps | No ceiling raised; `_render.py` grows by about 12 lines |

## Reuse inventory

- Engine `ValidatorResult`, `result_status`, `plan_scope`, `unchecked_named_columns`,
  `stamp_validation`, the run warning collector.
- CLI `render_card`, `warning_records`, `render_warnings`, `post_scan_members` pattern, the error
  payload in `_errors.fail`, the shape snapshot.

## Frozen contracts

- CLI `decoy run --json`: new optional `validation` member (success and error). Additive.
- Engine `PipelineResult.warnings`: may now carry `leak_check_column_not_checked`. Additive,
  named in the compatibility contract.
- No change to exit codes or to the `RunResult` document.

## Slices

- **S4e (engine)** `feat(validators): report unchecked named columns as run warnings`. Test V10e.
  After S3b.
- **S4c (CLI)** `feat(run): show every validator result on the card and in JSON`. Tests V11, V12,
  V13c. After the engine release and the CLI repin (repin checklist: compat, fences, frozen
  files, docs, pin prefix, Dockerfile ARG, catalog).

Test depth: T0 per edit; T1 impact selection. Triggers: frozen contract (`--json` shape), so one
full CLI suite at the S4c merge (`gates.sh --full`), diffed against the stored main baseline.
S4e: T2 gate set; no trigger.

## Pre-mortem

- The engine warning path dedupes by code and drops the second named column. V10e uses two named
  columns.
- The CLI renders the `Checks` fact from a stale engine pin. S4c lands only after the repin.
- The error card cannot show lines because `fail` renders before the report is reachable. The
  builder reads `exc.report` first; `ValidatorFailedError` carries the report since S1.
- Open item for the owner: add a `validators` `CheckId` to the engine `RunResult` document so the
  saved result file also lists checks. Not in this slice; it changes a closed `Literal`
  (engine `run_result/_model.py:183`).

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; `~/bin/pytest-one`.
- Card and JSON text: names, codes, counts and statuses only; run V13c after each change.
- Do not edit the CLI half before the repin lands on CLI main.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entries in both repos.
