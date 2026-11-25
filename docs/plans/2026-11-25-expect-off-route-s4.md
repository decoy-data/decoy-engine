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
  and the check skipped (engine `execution/_pipeline_finalize.py:361-376` on main), but it only
  lands in `quality_metrics["validation"]["warnings"]`. The run's `warnings` list, which the CLI
  counts and renders (CLI `src/decoy/cli/run/_execute.py:514`, `_render.py:112-115`), never sees
  it.
- `decoy validate` is silent when `expect leak_check` names a column the config keeps
  (`passthrough`), even though `plan_scope` (engine `validators/_scope.py:144`) can tell from the
  config alone.

## Guarantee

1. On single-pipeline runs, every configured validator appears on the card and in JSON with
   its entry index, name, status (`passed`, `failed` or `skipped`) and its value-free targets:
   checked, skipped and failed tables and columns.
   This holds on success, on a validator failure (exit 3), on a quarantine-covered failure that
   returns success, and in preview. For `run --all`, human output summarizes pipeline, exit and
   run folder. Child reports appear at `pipelines[i].validation` in aggregate JSON.
2. A failed entry names its own failed tables and columns, never another entry's, also when two
   entries share a validator name.
3. Each distinct explicitly named skip per entry produces a run warning, including a skip
   because the table was absent. A skip alone allows exit 0.
4. `decoy validate` and `decoy validate config` both warn, from the config alone, about each
   named column that `plan_scope` rules out. Exit 0, or 2 with `--fail-on-warning`.
5. Nothing new carries a data value: names, codes, counts, indices and statuses only.
6. When validators are configured and the engine returns no readable or complete block, the card
   and JSON say so with a fixed line. They never show a silent pass.
7. `decoy run --chunked` with validators is refused before any source read or output write, because that
   route returns no report (parent lines 77-81: checks judge published bytes and a failure
   publishes nothing). The target keeps its old bytes.

Non-goals:

- Existing validator verdicts and CI/pre-commit exits stand. The validate commands apply their
  existing warning policy to the new advisory. Explicit `--chunked` uses the pre-run refusal exit.
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
  `tests/unit/validators/test_validator_value_free.py:81-88`.
- CLI: the ordinary run keeps the engine result in `_execution` (`run/_execute.py:480`); the
  report flags alone fill `_report_quality_metrics` (`:510-511`), so S4 reads `_execution`.
  The card (`run/_render.py:161-188`); the JSON branch (`:116-153`); preview calls
  `run_pipeline` with validators kept (`cli/gen/_preview.py:38-56`, `run/_execute.py:525-537`);
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
2. Keep the public `unchecked_named_columns(config, report) -> tuple[SkippedColumn, ...]`
   contract, including order, repeated skips and omission of whole-table skips. Factor its
   explicit-scope selection in `validators/_scope.py:215-223` into one indexed traversal.
   Expose the indexed warning input through the validators package API. For the writer, expand
   each table-level skip in the traversal against that entry's explicit columns for that table.
   Keep the original table skip in the report. Default scope yields no warning candidates.
3. Change the existing `_unchecked_column_warnings` writer (#812
   `execution/_pipeline_finalize.py:361-387`) to consume the indexed input. Build one ordered
   list of QualityWarning records, keeping the first occurrence of each
   `(code, entry_index, table, column, reason)` before stamping. Preserve provider and code.
   Each record has `detail={"table": table, "reason": skip.code, "entry_index": entry_index}`.
   **OWNER CALL (recommended default chosen)**. Keep the accepted empty column name in the
   config. For that occurrence use `column=None` in the warning, including during whole-table
   expansion. This satisfies the QualityWarning constructor. Other named columns retain their
   exact spelling. The report keeps its original targets.
   Stamp the canonical list with the existing asdict writer. At the shared run_pipeline return
   (`execution/_pipeline.py:360-361`), `merge_validation_warnings` appends QualityWarning
   records reconstructed from those stamps to the frozen result via dataclasses.replace.
   Keep the existing warnings and their order. This merge runs once and neither enumerates
   skips nor defines another identity rule.
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
     a bool or numeric string where an int is needed, a negative count, a non-string table, or
     a column other than a string or null. Read target pairs and skip triples in the producer's
     tuple/list form and emit named JSON fields. Require an actual bool for `passed` and require
     it to equal `all(entry.status != "failed" for entry in results)` after exact entry coverage.
     Check status against the per-entry evidence: failed entries have failed targets, passed
     entries have checked targets and no failed targets, skipped entries have neither. A
     nonfailed entry has count zero. Null checked columns are valid for relationship checks.
     Ignore unknown extra fields and accept empty lists consistent with the entry status.
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
2a. Explicit `--chunked` with validators: extend the existing validated-config refusal shared by the early probe and execution at
   `run/_execute.py:247-270`, before any source read or output write, with a value-free message naming the
   flag and the `validators:` block. When `run_mask_chunked` returns a report this refusal goes.
3. Error path: `_errors.fail` adds the member to the existing context (`:312-349`) when the error
   is `ValidatorFailedError`. Pass the same projection to the human branch at
   `_result.py:437-438`. Print the Checks fact (including the failed count) and every entry on
   normal stderr before cleanup. A ValidatorFailedError carrying a coherent passing report also counts as malformed.
   A malformed failure report gets the fixed fallback on stderr
   and in JSON (`reported: false`), still exit 3. JSON emits one document. Quiet keeps the
   existing error and hint only.
4. **OWNER CALL (recommended default chosen)**. Make the skipped-column advisory command-local.
   Thread an explicit opt-in (default false) from only the two validate entry points through
   their gate calls to the config layer. Plan each leak_check scope once there. Convert a
   malformed scope (e.g. list-valued `params.exempt` or a generate table in entry-level
   `columns`) to one fixed config error, without interpolating the exception. This error
   applies to run as well. Only on opt-in, use the plan's explicit config skips to append
   advisory GateFindings before rendering and exit calculation. Deduplicate repeated names
   per entry. The passthrough message names the column and says the config keeps it.
   Errors keep precedence. Leave both CI adapters, pre-commit and run on the default path
   for advisories (`ci/adapters.py:119,138-151`, `ci/contracts.py:515`, `ci/runner.py:81-87`).
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
| Validate advisory | CLI `cli/validate.py` and existing gate entry points and config layer in `cli/gate/` | existing command and shared gate | |
| CLI tests | `tests/unit/test_run_checks.py`, `tests/unit/test_gate_leak_scope.py`; extend command, CI and project fan-out suites | CLI `CODEMAP.md:50-54` permits command units under `tests/unit/` and assigns gate units to `tests/unit/test_gate_*.py` | `tests/e2e/test_validate_gate.py`, `tests/e2e/project_layout/test_run_all.py` |
| Engine targets and warnings | engine `validators/_types.py`, `validators/_fold.py`, `validators/_scope.py`, `validators/__init__.py`, `execution/_pipeline_finalize.py`, `execution/_pipeline.py` | existing | |
| Engine tests | engine `tests/unit/validators/test_leak_check_skips.py` (extended), `test_validator_targets.py` (new) | `tests/unit/validators/` per engine `CODEMAP.md:286` | |

## Behavior and failure modes

| Case | Card | `--json` | Exit |
|---|---|---|---|
| Two passing checks, no report flags | `Checks  2 passed`, two entry lines | `validation.passed = true`, two results | 0 |
| One entry checks `email`, skips `phone` | one line with both | `checked` and `skipped` | 0 |
| Two leak checks, #1 fails on customers.email | stderr includes `Checks  1 failed` and both entries, only #1 names email as failed | error payload validation, failed target on #1 only | 3 |
| `fk_intact` with an orphan child | `#0 fk_intact failed orders` | target `{table: orders, column: null}` | 3 |
| Quarantine-covered failure | `Checks  1 failed` on a success card | `passed = false` | 0 |
| Passthrough column named in `columns:` | skip line, `Warnings 1` | `skipped`, warning `leak_check_column_not_checked` | 0 |
| Missing table with an explicit empty name and a nonempty name | table skip, two warnings | warning columns null and the nonempty name | 0 |
| Default scope, a passthrough column | skip recorded, no warning | skip in `results[].skipped` | 0 |
| No validators | no fact | no `validation` key | 0 |
| Validators configured, explicit `--chunked` | refusal before any source read or output write; target bytes unchanged | refusal payload | existing refusal exit |
| Malformed, partial or mismatched block | `checks: engine did not report validator results` | `validation.reported = false` | 0 |
| Two entries skip one column for different reasons | two warnings | two warnings, same in both channels | 0 |
| Preview, passing and failing | as the full run | as the full run | 0 / 3 |
| Forced out-of-core | as the default route | same | 0 |
| Both validate commands, named passthrough column | warning says the config keeps customers.email | finding in JSON | 0, or 2 with `--fail-on-warning` |
| Same plus a config error | the error wins | error | as today |
| List in params.exempt or generate table in entry-level columns | fixed config error finding | finding | as other config errors |
| CI validation (both modes) and pre-commit, otherwise clean kept-column fixture | existing success | no new advisory | 0 |
| Run --all with one passing and one validator-failed child | aggregate summary | reports under pipelines[i].validation | existing aggregate exit 3 |

## Acceptance tests (red first)

The post-S3b engine and repinned pre-S4c CLI heads are future dependencies. Red-before, pin
and mutation expectations below are source judgments. Record actual base SHAs and outcomes
when those heads exist. CLI main currently pins 0.28.3 (`pyproject.toml:153`).

1. **V10e (engine, red-before except the stated pins).** Run real pipelines on resident and forced out-of-core routes. Use two
   entries with identical passthrough skips, a repeated name within one entry, another named
   column and a scope with `columns: {absent_table: ["", email]}`. Include the empty-only form
   `columns: {absent_table: [""]}` as a separate run that produces exactly one null-column
   warning. For the mixed case assert a passing run,
   the table-level skip and separate warnings for null and email on the absent table.
   Assert exact ordered identities: repeats within an entry collapse, matching skips across
   entries survive. Compare serialized run warnings filtered by `leak_check_column_not_checked`
   with the stamped validation warnings. Independently assert a seeded unrelated warning retains
   its contents and order. Update the exact detail assertion at
   `test_leak_check_skips.py:179` to include integer `entry_index: 0`. Pin the public helper's
   original return shape and multiplicity, and absence of a default-scope warning.
2. **V10t (engine, red-before).** Two `leak_check` entries (one fails on `email`) and one
   `fk_intact` entry with an orphan child: each result's `failed_targets` holds only its own
   targets; `fk_intact` has `{orders, None}`.
3. **V11 card and JSON (CLI, red-before).** Each row of the table above, human and JSON, no report
   flags where applicable. A real failed run prints `Checks  1 failed` and the per-entry lines
   on normal stderr. JSON is one document, exit 3. Quiet shows only the error and hint.
   Assert the forced out-of-core route. Through both a #812 stamped mapping and a dataclass,
   exercise missing or invalid status, unknown code, bool and numeric-string (`"3"`) counts, bool index, int column,
   missing/duplicate index and a same-length wrong name with all indices present. Reject
   `passed=true` with a failed entry and `passed=false` with only passed/skipped entries.
   Each rejection yields the fixed fallback with no pass summary and JSON `reported: false`.
   On the error path also refuse an internally consistent passing report.
   Accept a real FK checked pair (child table, null), extra keys and consistent empty lists.
   No validators is a pin. For default scope the visible skip line and JSON skip are red-before,
   and absence of a warning is a pin. Exercise `run --all` with pass and failure children:
   assert each child's own `pipelines[i].validation` against its single-pipeline JSON, no
   aggregate validation member, existing human table and summary exit.
4. **V11x `--chunked` refusal (CLI, red-before).** A failing validator with an existing target:
   refusal exit, target bytes unchanged, no engine call.
5. **V11k cleanup (CLI, pin).** Drive a real validator failure in normal human mode and
   assert the pending layout was abandoned by the flow's finally. A sample refusal deletes
   sample scratch.
6. **V12 validate (CLI, red-before except the stated pins).** For each validate command assert the normal human warning names
   customers.email and says it is kept, the JSON finding carries that explanation, and exits
   are 0 by default and 2 with `--fail-on-warning`. Pin error precedence and default scope.
   On the same otherwise-green config pin both CI validation modes with their default
   fail-on-warning policy, pre-commit success and absence of the advisory from their findings.
   Pin run's gate acceptance. Exercise malformed `params.exempt: [email]` and entry-level
   `columns: {generated_table: [email]}` through validate, validate config and run; require
   a fixed config finding and the existing config-error exit, including on JSON paths.
7. **V13c value-free (CLI, marker absence is a pin).** Seed data columns with a marker. The engine test
   `test_validator_value_free.py:81-88` covers report representation and logs. Separately
   inject a ValidatorFailedError carrying a report with a marked finding.detail into the CLI
   run error path, through `_errors.py:340-349` and the real stderr/JSON emitters. Assert exit
   3, the expected structural check output and absence of the marker from the entire output,
   including warnings and error text.
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
| R12 | S4c | Skip the configured-name comparison | V11 same-length wrong name with valid index coverage |
| R13 | S4e | Drop entry_index from the identity | V10e identical skips in two entries, repeated name inside one |
| R14 | S4c | Remove layout abandon in `run/_flow.py:227-230` finally | V11k normal human failure (JSON abandons earlier) |
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
- Fan-out uses existing child exit precedence. Child validation adds no parent exit path.

### Routes

- Every `run_pipeline` route stamps one report after S3b. The CLI reads the block, not the
  route; V11 runs on the default route and on a forced out-of-core run.
- Preview retains validators and calls the engine at CLI `run/_execute.py:525-537`.
- Fan-out delegates from `run/_flow.py:131-132`; `cli/project/_run_all.py:125-129,170-174,221-236`
  retains child JSON at `pipelines[i]` and renders a human summary table.
- Explicit `--chunked` (`run_mask_chunked`, `run/_execute.py:420-437`): refused with validators.

### FK shapes

Relationship checks carry a child table with a null column in checked or failed targets. Render the table name alone.

### Fields

| Field | Source | Rule |
|---|---|---|
| `validation.passed` | `ValidationReport.passed` | bool |
| `validation.reported` | CLI | `false` only when configured and absent or malformed |
| `results[].validator` | `ValidatorResult.validator` | non-empty string |
| `results[].entry_index` | `ValidatorResult.entry_index` | int, not bool |
| `results[].status` | `result_status` | one of three |
| `results[].failing_row_count` | `ValidatorResult.failing_row_count` | int, not bool |
| `results[].checked[]` | `ValidatorResult.checked` | table, column or null |
| `results[].failed_targets[]` | `ValidatorResult.failed_targets` (new) | table, column or null |
| `results[].skipped[]` | `SkippedColumn` | table, column or null, registered code |

### Output surfaces

- Single-pipeline run card fact `Checks` and the lines under the card. Fan-out reports stay in child JSON records.
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
| 8 | Weak tests | Record observed reds and passing controls on the designated implementation bases | builder report | R3, skip lines dropped |
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
| 11 | No raised caps | Register the CLI reader in the package census. Edit the existing engine warning writer (527 lines on #812) within its existing cap |

## Reuse inventory

- Engine `ValidatorResult`, `result_status`, `plan_scope`, `unchecked_named_columns`,
  `stamp_validation`, `dataclasses.replace` on `ExecutionResult`.
- CLI `render_card`, `warning_records`, `render_warnings`, `post_scan_members` pattern, the error
  payload in `_errors.fail`, the shape snapshot.

## Frozen contracts

- Stamped validation warnings gain integer `detail.entry_index`. Document the additive detail key, the null warning column for an empty name, and the per-entry warning multiplicity.

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

Test depth: T0 per edit and T1 impact selection. Both PRs touch frozen surfaces. Run each
full suite **before the merge gate** and compare with its stored main baseline (CLI
`gates.sh --full --baseline-file`, `dev-rules/testing.md:84-88`).

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

## Round 4 resolution

1. **V1** — Only the two validate commands opt into advisories. V12 pins CI and pre-commit exits.
2. **DESIGN** — Indexed scope traversal feeds one deduplicating warning writer. V10e checks its exact detail and both channels.
3. **V1** — Empty explicit names project to null warning columns. V10e exercises an absent table through run_pipeline.
4. **V1** — Both report forms must agree with their entry verdicts. V11 covers both contradictions and a valid null FK column.
5. **V1** — V11 requires the failed count on stderr. V12 requires both commands to explain that the column is kept.
6. **V2-LOG** — R12 targets name matching, R13 targets index loss and R14 targets human-mode cleanup.
7. **V2-LOG** — V10e compares validation warnings separately. V11 distinguishes new default-scope output from the warning pin. Base and mutation outcomes await the implementation heads.
8. **V2-LOG** — Corrected writer, CODEMAP, fixture, emitter and preview references. Full suites precede the merge gate.
9. **V2-LOG** — The card guarantee covers single pipelines. V11 pins fan-out child JSON and the human summary.
