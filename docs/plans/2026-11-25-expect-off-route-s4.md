# EXPECT-OFF-ROUTE S4: show every check on the run card and in JSON

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
reuse-first, catalogs/recurring-defects; owner notes on the value-free class (F31), the
express-all-capabilities rule, plan-defines-acceptance-tests and the engine repin checklist.

Row: EXPECT-OFF-ROUTE, slice S4 (holds the CLI row EXPECT-REPORT). Parent plan:
`docs/plans/2026-11-22-expect-off-route.md` rev 6 on branch `origin/plan/expect-off-route`
(sections 3, 4 "Output surfaces", the S4 slice at section 6 line 212, V10 to V12 in section 9,
the frozen-contract entry at section 11 line 311, and the `Breaking:` rule at line 179).

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
   its entry index, name, status (`passed`, `failed` or `skipped`) and its value-free targets:
   checked, skipped and failed tables and columns.
   This holds on success, on a validator failure (exit 3), on a quarantine-covered failure that
   returns success, and in preview.
2. A failed entry names its own failed tables and columns, never another entry's, also when two
   entries share a validator name.
3. Each column that a `columns:` list names and the check did not check produces one
   `QualityWarning` in `ExecutionResult.warnings`, including when the whole table was not
   produced. The run still exits 0.
4. `decoy validate` and `decoy validate config` both warn, from the config alone, about each
   named column that `plan_scope` rules out. Exit 0, or 2 with `--fail-on-warning`.
5. Nothing new carries a data value: names, codes, counts, indices and statuses only.
6. When validators are configured and the engine returns no readable or complete block, the card
   and JSON say so with a fixed line. They never show a silent pass.
7. `decoy run --chunked` with validators is refused before the first read or write, because that
   route returns no report (parent lines 77-81: checks judge published bytes and a failure
   publishes nothing). The target keeps its old bytes.

Non-goals:

- No change to any verdict or route. A validator failure stays exit 3. The only new exit is the
  `--chunked` refusal, which uses the existing pre-run refusal path and its exit code.
- No change to `--post-validate-enforce` or the `post_validation` check.
- No new `CheckId` in the engine `RunResult` document in this slice (open item below).

## What exists (reuse, do not rebuild)

- Engine: `ValidationReport.results` (`validators/_types.py:147`), `ValidatorResult`
  (`:77-91`: `validator`, `entry_index`, `status`, `checked`, `skipped`, `failing_row_count`),
  `result_status` (`:93`), `ValidatorFinding` (`:35`) with no entry index (`:56-60`), `SkippedColumn` (a named
  tuple, `:68-73`); the fold that combines findings across entries (`validators/_fold.py:100-109`);
  `plan_scope` and `unchecked_named_columns` (`validators/__init__.py:71`); the table-level skip
  with `column=None` (`validators/_leak_check.py:187-192`), dropped for warnings at
  `validators/_scope.py:220-222`; the generate-table refusal (`_scope.py:161-170`);
  `_unchecked_column_warnings` (`_pipeline_finalize.py:361-376` on main); after S2,
  `stamp_validation` (#812 `_pipeline_finalize.py:381-387`, which writes
  `validation["validators"]` with `asdict` and stamps each warning with its reason in `detail`,
  `:370-387`), the quarantine-covered success
  (#812 `:452-461,493-495`) and the route stamp (#812 `_pipeline_route_dispatch.py:101-106`).
  `run_pipeline` returns the frozen `ExecutionResult` with `warnings` as a tuple
  (`execution/_pipeline.py:165`, shared return at `:360-361`, `execution/_adapter.py:49-72`).
  `fk_intact` reports an orphan child with `column=None` (`validators/_fk_validators.py:348-354`).
  `leak_check` keeps repeated column occurrences (`validators/_leak_check.py:104-108`).
  `validators:` `params` are free-form (`config/_validators.py:75-77`); `plan_scope` raises on a
  list `exempt` (`_scope.py:154-156`) and on a generate-table scope (`:165-169`). `ValidatorFailedError.report`
  is a dataclass and predates S1 (`v0.28.3 errors.py:396`).
- Engine tests: `tests/unit/validators/test_leak_check_skips.py:169-187`,
  `tests/unit/validators/test_validator_value_free.py:81-87`.
- CLI: the ordinary run keeps the engine result in `_execution` (`run/_execute.py:480`); the
  report flags alone fill `_report_quality_metrics` (`:510-511`), so S4 reads `_execution`.
  The card (`run/_render.py:161-188`); the JSON branch (`:116-153`); preview calls
  `run_pipeline` with validators kept (`cli/gen/_preview.py:38-56`, `run/_execute.py:525-540`);
  explicit `--chunked` calls `run_mask_chunked` and gets no report (`run/_execute.py:76-78,223,420-437`).
  The error path: `run/_errors.py:172` `fail`, the context at `:312-349`, the hint at
  `:293-296` (quiet mode still prints it, `ui/output.py:228-231,251-254`), rendered by
  `run/_result.py:419-440`; dispatch of other exceptions at `run/_flow.py:224-226` and cleanup
  in its `finally` (`:227-232`); the sample refusal before validators run (`run/_sample.py:127-149`);
  the existing pre-run refusals (`run/_execute.py:247-270`). Bare `validate` uses
  `_emit_gate` and `gate_exit_code` (`cli/validate.py:314-327`); `validate config` uses
  `_emit_result` (`:165-170`); both catch only `OSError` around the gate (`:164-170,313-325`);
  gate findings are built at `cli/gate/_layers.py:245-248`; the same gate serves `run`
  (`cli/gate/_run.py:160-169`).
- CLI freeze: `tests/e2e/release_freeze/write_shapes.py:107-108` (skips optional subtrees) and
  `:458-462` (exit 0 only); `tests/e2e/release_freeze/test_json_shapes.py:103,118`;
  `docs/schemas/decoy-error-v1.schema.json:33` (already allows command context); one top-level
  entry per command (`test_json_shapes.py:132-136`). The package census
  `tests/sentry/layout/test_run_package_shape.py:34-46,133-141`.

## Design

### Engine half, S4e (one PR)

1. Per-entry targets. Add `failed_targets: tuple[Target, ...]` to `ValidatorResult` (default
   empty; `checked` already exists), where `Target` is a named tuple `(table, column)` with `column` optional. The fold
   (`_fold.py:100-109`) already walks each entry's findings before combining them; it records
   that entry's distinct `(table, column)` pairs there. No finding detail is copied.
2. Whole-table skips. `unchecked_named_columns` expands a `column=None` skip against the
   entry's explicit `columns:` list for that table, so each named column gets its warning. The
   table-level `SkippedColumn` stays in the report. Default scope adds no warning.
3. Warnings channel. The warning identity is defined once, in the function that builds the
   validation warnings: `(code, entry_index, table, column, reason)`. Two entries that skip the
   same column for different reasons give two warnings. Both channels project from that one
   list: the stamped `quality_metrics["validation"]` copy (in the evidence manifest) and
   `ExecutionResult.warnings`. `merge_validation_warnings(result) -> ExecutionResult` runs once at
   the shared return of `run_pipeline` (`execution/_pipeline.py:360-361`) and returns
   `dataclasses.replace(result, warnings=existing + new)`, adding only identities not already in
   `existing` and keeping every unrelated warning.
4. Docs: rows in `docs/qa/14-casting-validators-quarantine.md` and
   `docs/qa/15-execution-routes-native.md`; the `leak_check` paragraph at
   `docs/strategies.md:2338-2348`; compatibility contract entries for the new warning on
   `ExecutionResult.warnings` and the new `failed_targets` field, each with a `Breaking:` line
   per parent lines 179 and 188 (`Breaking: none, additive`), and a CHANGELOG entry.

### CLI half, S4c (one PR, after the repin)

1. New `src/decoy/cli/run/_checks.py` (about 140 lines), registered in
   `test_run_package_shape.py` before `_result`, `_errors` and `_render` (all import it); engine
   imports inside functions.
   - `project(source, configured: tuple[str, ...]) -> Checks | Absent | Malformed`. The one input
     normalizer. `configured` is the ordered list of configured validator names. It accepts the
     two real producer forms, a `ValidationReport` dataclass (from `exc.report`) and the #812
     stamped mapping `quality_metrics["validation"]["validators"]`, and turns both into one
     strict projection: `passed`, and per entry `entry_index`, `validator`, `status`,
     `failing_row_count`, `checked`, `failed_targets`, `skipped` (`table`, `column` or null,
     `code`). `Absent` means no block. `Malformed` means a block that fails any rule: a missing,
     duplicate or extra `entry_index`, a name that does not match `configured` at that index, a
     missing status or one outside the three values, a code not in the engine warning registry,
     a bool or numeric string where an int is needed, a non-null non-string column. Accepted:
     unknown extra keys (parent line 237) and empty `skipped` or `checked` lists.
   - `validation_member(result, configured)`: `Checks` gives the member; `Absent` with nothing
     configured gives `None`; `Absent` with validators configured or `Malformed` gives
     `{"reported": false}` and the fixed warning line `checks: engine did not report validator
     results`.
   - `checks_fact(member)` and `check_lines(member)`: one line per entry, for example
     `#0 leak_check passed customers.email; skipped customers.phone (leak_check_skip_passthrough)`,
     `#1 leak_check failed customers.email`, `#2 fk_intact failed orders`.
2. `_render.py` `finish`: read `_execution`, add `payload["validation"]`, the fact after
   `Warnings`, and the lines after `render_warnings` (about +12). `finish_preview` (`:218`) does
   the same.
2a. Explicit `--chunked` with validators: a new pre-run refusal beside the existing ones at
   `run/_execute.py:247-270`, before any read or write, with a value-free message naming the
   flag and the `validators:` block. When `run_mask_chunked` returns a report this refusal goes.
3. Error path: `_errors.fail` adds the member to the existing context (`:312-349`) when the error
   is `ValidatorFailedError`; `_result.py:419-440` prints the check lines on the human branch,
   before the `finally` cleanup at `_flow.py:227-232` runs. One JSON document on stdout, exit 3;
   `--quiet` prints the existing error and hint lines and no check lines.
4. Validate: one advisory `GateFinding` per named skipped column, built once in
   `cli/gate/_layers.py:245-248`, so `validate` (through `_emit_gate`) and `validate config`
   (through `_emit_result`) both show it and `gate_exit_code` applies `--fail-on-warning`.
   Errors keep precedence, including the generate-table refusal. A `plan_scope` failure (a list
   `exempt`, a generate-table scope) becomes one value-free config error finding, never an
   uncaught exception; `run` gets the same finding through `cli/gate/_run.py:160-169`, with its
   exit code pinned.
5. Freeze: `write_shapes.py` types optional subtrees for `validation`; the success, exit-3 and
   `reported: false` variants nest under the one existing `run` entry (`test_json_shapes.py:132-136`);
   `json-shapes.json` and the optional-key list change in the same commit.
6. Docs: `docs/guides/decoy-language/05-checks-and-subsets.md` shows the `Checks` lines and the
   warning. CHANGELOG entry with a `Breaking:` line for the `--json` shape (additive) and the
   `--chunked` refusal.

Choke point: `_checks.project` is the one CLI reader of validation results; the card, JSON,
preview, error card and error JSON all call it. Guard: V11 reader cases. Mutation: read
`failing_row_count` with `int()` (V11 numeric-string case red).

Design notes: one new private module, because the reader, the fact and the lines are one
concern and `_render.py` (239 lines) should not take a parser. It follows the `post_scan_members`
pattern.

### Placement

| New or changed | Path | CODEMAP rule | Sits beside |
|---|---|---|---|
| Validation reader and card lines | CLI `src/decoy/cli/run/_checks.py` | `decoy run` modules in `src/decoy/cli/run/`; package census entry | `_render.py`, `_result.py` |
| Run card, JSON and error | CLI `run/_render.py`, `run/_errors.py`, `run/_result.py` | existing | |
| Validate advisory | CLI `cli/gate/_layers.py` | existing | |
| CLI tests | CLI `tests/unit/cli/run/test_run_checks.py`, `tests/unit/cli/test_validate_leak_scope.py` | new `tests/unit/cli/` tree per CLI `CODEMAP.md:50-52` | |
| Engine targets and warnings | engine `validators/_types.py`, `validators/_fold.py`, `validators/_scope.py`, `execution/_pipeline.py` | existing | |
| Engine tests | engine `tests/unit/validators/test_leak_check_skips.py` (extended), `test_validator_targets.py` (new) | `tests/unit/validators/` per engine `CODEMAP.md:286` | |

## Behavior and failure modes

| Case | Card | `--json` | Exit |
|---|---|---|---|
| Two passing checks, no report flags | `Checks  2 passed`, two entry lines | `validation.passed = true`, two results | 0 |
| One entry checks `email`, skips `phone` | one line with both | `checked` and `skipped` | 0 |
| Two `leak_check` entries, one fails on `customers.email` | error card names `#1 ... customers.email` only | error payload `validation`, targets on entry 1 only | 3 |
| `fk_intact` with an orphan child | `#0 fk_intact failed orders` | target `{table: orders, column: null}` | 3 |
| Quarantine-covered failure | `Checks  1 failed` on a success card | `passed = false` | 0 |
| Passthrough column named in `columns:` | skip line, `Warnings 1` | `skipped`, warning `leak_check_column_not_checked` | 0 |
| Named column in a table the run did not produce | one warning per named column | same | 0 |
| Default scope, a passthrough column | skip recorded, no warning | skip in `results[].skipped` | 0 |
| No validators | no fact | no `validation` key | 0 |
| Validators configured, explicit `--chunked` | refusal before any read or write; target bytes unchanged | refusal payload | existing refusal exit |
| Malformed, partial or mismatched block | `checks: engine did not report validator results` | `validation.reported = false` | 0 |
| Two entries skip one column for different reasons | two warnings | two warnings, same in both channels | 0 |
| Preview, passing and failing | as the full run | as the full run | 0 / 3 |
| Forced out-of-core | as the default route | same | 0 |
| `validate` and `validate config`, named passthrough column | advisory naming `customers.email` | finding in the JSON result | 0, or 2 with `--fail-on-warning` |
| Same plus a config error | the error wins | error | as today |
| List `exempt` or generate-table scope in `params` | config error finding | finding | as other config errors |

## Acceptance tests (red first)

Engine reds run on the post-S3b main head. CLI reds run on the repinned pre-S4c head, not on CLI
main (which pins 0.28.3, `pyproject.toml:153`). Each row is red-before or a pin.

1. **V10e (engine, red-before).** Two named passthrough columns, one named column in an
   unproduced table, and two entries skipping one column for different reasons: the warning
   list in `ExecutionResult.warnings` equals the stamped list, each identity once, unrelated
   warnings kept, on resident and forced out-of-core. Extends `test_leak_check_skips.py:169-187`.
   Default-scope control (pin): none added.
2. **V10t (engine, red-before).** Two `leak_check` entries (one fails on `email`) and one
   `fk_intact` entry with an orphan child: each result's `failed_targets` holds only its own
   targets; `fk_intact` has `{orders, None}`.
3. **V11 card and JSON (CLI, red-before).** Each row of the table above, human and JSON, no report
   flags. Error case: human stderr, one JSON document, exit 3; `--quiet` shows error and hint,
   no check lines. Forced out-of-core asserts the route. Reader cases through both real forms
   (the #812 `validation["validators"]` mapping and the dataclass), split: refused (fixed line)
   for missing status, status `"ok"`, unknown code, bool and `"3"` counts, bool index, int
   column, missing entry, duplicate index, name mismatch; accepted for an extra key and empty
   lists. Controls that pass on the base (no validators, default scope) are pins.
4. **V11x `--chunked` refusal (CLI, red-before).** A failing validator with an existing target:
   refusal exit, target bytes unchanged, no engine call.
5. **V11k cleanup (CLI, pin).** A real validator failure abandons the layout; a sample refusal
   deletes sample scratch.
6. **V12 validate (CLI, red-before).** Both commands, human and JSON, exit 0 and 2 with
   `--fail-on-warning`; a list `exempt` and a generate-table scope give a config finding on
   `validate`, `validate config` and `run`. Pins: error precedence, default-scope no advisory.
7. **V13c value-free (CLI, control).** A marker in every validated column and in a synthetic
   `finding.detail` passed through the real emitter (`test_validator_value_free.py:81-87`). The
   marker is in no card line, JSON member, warning or error payload.
8. **Shape freeze (CLI).** The snapshot types `/validation` under the `run` entry for the success,
   exit-3 and `reported: false` variants.

Mutations (all on the final head of their PR):

| ID | PR | Mutation | Test that must fail |
|---|---|---|---|
| R1 | S4c | `int()` in place of the strict count reader | V11 `"3"` case |
| R2 | S4c | Drop the member from the error payload | V11 failure case |
| R3 | S4c | Print only failed entries | V11 pass and skip lines |
| R4 | S4e | Skip `merge_validation_warnings` | V10e |
| R5 | S4c | Advisory for default-scope skips too | V12 default-scope pin |
| R6 | S4c | Put `finding.detail` into a check line | V13c synthetic marker |
| R7 | S4c | Accept any skip code | V11 unknown-code case |
| R8 | S4e | Attribute all findings to every entry with the same name | V10t |
| R9 | S4e | Drop the whole-table expansion | V10e unproduced-table case |
| R10 | S4c | Read `_report_quality_metrics` instead of `_execution` | V11 no-report-flag case |
| R11 | S4c | Drop the `--chunked` refusal | V11x |
| R12 | S4c | Skip the configured-names match | V11 missing-entry case |
| R13 | S4e | Warning identity without `reason` | V10e two-reasons case |
| R14 | S4c | Remove the layout abandon call in the failure path | V11k |
| R15 | S4c | Remove the sample scratch delete | V11k |
| R16 | S4c | Let a `plan_scope` exception escape | V12 `exempt` case |

## Enumerations

### Exit paths

- Success: `_render.finish` (CLI `src/decoy/cli/run/_render.py:106`), exit 0, or 4 under
  `--post-validate-enforce` (unchanged); also a quarantine-covered failure.
- Preview: `finish_preview` (`_render.py:218`), exit 0 or 3.
- Validator failure: `ValidatorFailedError` to `_errors.fail` (CLI
  `src/decoy/cli/run/_errors.py:172`), exit 3, payload and human card gain the checks.
- Pre-run refusals (`_errors.refused`, `:364`), including the new `--chunked` one; post-write
  refusals (`:373`); bad parameters (`:396`); interrupts (`:408`); other exceptions dispatched at
  `_flow.py:224-226`: no validation member.
- `decoy validate` and `decoy validate config`: exit 0 with the advisory, 2 with
  `--fail-on-warning`; errors unchanged.

### Routes

- Every `run_pipeline` route stamps one report after S3b. The CLI reads the block, not the
  route; V11 runs on the default route and on a forced out-of-core run.
- Preview runs validators (`cli/gen/_preview.py:38-56`): same member.
- Explicit `--chunked` (`run_mask_chunked`, `run/_execute.py:420-437`): refused with validators.

### FK shapes

N/A. The keyed validators' results show like any other entry; keys are not printed.

### Fields

| Field | Source | Rule |
|---|---|---|
| `validation.passed` | `ValidationReport.passed` | bool |
| `validation.reported` | CLI | `false` only when configured and absent or malformed |
| `results[].validator` | `ValidatorResult.validator` | non-empty string |
| `results[].entry_index` | `ValidatorResult.entry_index` | int, not bool |
| `results[].status` | `result_status` | one of three |
| `results[].failing_row_count` | `ValidatorResult.failing_row_count` | int, not bool |
| `results[].checked[]` | `ValidatorResult.checked` | table, column |
| `results[].failed_targets[]` | `ValidatorResult.failed_targets` (new) | table, column or null |
| `results[].skipped[]` | `SkippedColumn` | table, column or null, registered code |

### Output surfaces

- Run card fact `Checks` and the lines under the card.
- `decoy run --json` member `validation` (success and error payloads).
- Run `warnings` (engine `ExecutionResult.warnings`, CLI `warnings` array).
- Human error card on stderr.
- `decoy validate` and `decoy validate config` human and JSON output.
- Shape snapshot and the decoy-language guide.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Member and lines built from names, codes and counts; `detail` never read | V13c | R6, detail text in a line |
| 2 | Cleanup on an exit path | The `finally` cleanup is unchanged; the card renders before it | V11k | R14, R15 |
| 3 | Shared state | Pure functions of one result; per-entry targets built inside the fold per entry | V10t | R8, shared targets |
| 4 | Route parity and silent fallback | One reader for card, preview, JSON and error; incomplete blocks show a fixed line; `--chunked` refused | V11, V11x | R2, R11, R12 |
| 5 | Referential integrity | Skip codes are registered warning codes; the reader checks them against the engine registry | V11 skip case | Accept any string code: V11 red |
| 6 | Untrusted producer | The engine block is parsed strictly (engine and CLI may run different pins) | V11 reader cases | R1, `int()` reader |
| 7 | Check-then-use (toctou) | N/A: the metrics dict is read once after the run returns | none needed | N/A |
| 8 | Weak tests | Each row marked red-before or pin; reds shown on the stated heads | builder report | R3, skip lines dropped |
| 9 | Refactor drift | `_render.py` keeps its facts and order; snapshot diff shows only the new paths | shape snapshot test | R10, wrong source |
| 10 | Frozen contract drift | Generator, snapshot and optional-key list change together; contract names the warning and field with `Breaking:` lines | release-freeze shape test, typed on exit 0 and exit 3 | Remove the snapshot update: shape test red |

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
| 9 | Mutations on the final head | R1 to R16, each on its PR's final head |
| 10 | Allowlisted helpers still checked | N/A: no allowlist added |
| 11 | No raised caps | No ceiling raised; CLI `_render.py` 239 to about 251 (package cap 600); engine `_pipeline_finalize.py` untouched by S4e (527 on #812) |

## Reuse inventory

- Engine `ValidatorResult`, `result_status`, `plan_scope`, `unchecked_named_columns`,
  `stamp_validation`, `dataclasses.replace` on `ExecutionResult`.
- CLI `render_card`, `warning_records`, `render_warnings`, `post_scan_members` pattern, the error
  payload in `_errors.fail`, the shape snapshot.

## Frozen contracts

- CLI `decoy run --json`: new optional `validation` member (success and error). Additive.
- CLI `decoy run --chunked` with validators: now refused (it ran with no checks before).
- Engine `ExecutionResult.warnings`: may now carry `leak_check_column_not_checked`. Engine
  `ValidatorResult.failed_targets`: new field with an empty default. Both additive, named in the
  compatibility contract with `Breaking: none`.
- No new exit code and no change to the `RunResult` document.

## Slices

- **S4e (engine)** `feat(validators): report unchecked named columns as run warnings`. Tests
  V10e, V10t; mutations R4, R8, R9, R13. After S3b.
- **S4c (CLI)** `feat(run): show every validator result on the card and in JSON`. Tests V11,
  V11x, V11k, V12, V13c, shape freeze; the other R mutations. After the engine release and the CLI repin (repin checklist: compat, fences, frozen
  files, docs, pin prefix, Dockerfile ARG, catalog).

Test depth: T0 per edit; T1 impact selection. Both PRs touch a frozen surface (`dev-rules/testing.md:84-87`):
S4c the `--json` shape, S4e `ExecutionResult.warnings` and `ValidatorResult`. Each gets one full
suite at merge, diffed against the stored main baseline (CLI `gates.sh --full --baseline-file`).

## Pre-mortem

- The engine warning path dedupes by code and drops the second named column. V10e uses two named
  columns.
- The CLI renders the `Checks` fact from a stale engine pin. S4c lands only after the repin.
- The error card cannot show lines because `fail` renders before the report is reachable.
  `ValidatorFailedError.report` exists since v0.28.3 (`errors.py:396`).
- Open item for the owner: add a `validators` `CheckId` to the engine `RunResult` document so the
  saved result file also lists checks. Not in this slice; it changes a closed `Literal`
  (engine `run_result/_model.py:182`).
- Open item: explicit `--chunked` with validators is refused until `run_mask_chunked` returns a
  report. Owner may prefer a later slice that adds the report instead.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; `~/bin/pytest-one`.
- Card and JSON text: names, codes, counts and statuses only; run V13c after each change.
- Do not edit the CLI half before the repin lands on CLI main.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entries in both repos.
