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
   its entry index, name, status (`passed`, `failed` or `skipped`) and its value-free targets.
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
6. When validators are configured and the engine returns no readable block, the card and JSON
   say so with a fixed line. They never show a silent pass.

Non-goals:

- No change to any verdict, route or exit code. A validator failure stays exit 3.
- No change to `--post-validate-enforce` or the `post_validation` check.
- No new `CheckId` in the engine `RunResult` document in this slice (open item below).

## What exists (reuse, do not rebuild)

- Engine: `ValidationReport.results` (`validators/_types.py:147`), `ValidatorResult`
  (`:77-91`: `validator`, `entry_index`, `status`, `checked`, `skipped`, `failing_row_count`),
  `result_status` (`:93`), `Finding` with no entry index (`:56-60`), `SkippedColumn` (a named
  tuple, `:68-73`); the fold that combines findings across entries (`validators/_fold.py:100-109`);
  `plan_scope` and `unchecked_named_columns` (`validators/__init__.py:71`); the table-level skip
  with `column=None` (`validators/_leak_check.py:187-192`), dropped for warnings at
  `validators/_scope.py:220-222`; the generate-table refusal (`_scope.py:161-170`);
  `_unchecked_column_warnings` (`_pipeline_finalize.py:361-387`); after S2, `stamp_validation`
  (#812 `_pipeline_finalize.py:381-384`, which uses `asdict`), the quarantine-covered success
  (#812 `:452-461,493-495`) and the route stamp (#812 `_pipeline_route_dispatch.py:101-106`).
  `run_pipeline` returns the frozen `ExecutionResult` with `warnings` as a tuple
  (`execution/_pipeline.py:165`, `execution/_adapter.py:49-72`). `ValidatorFailedError.report`
  is a dataclass and predates S1 (`v0.28.3 errors.py:396`).
- Engine tests: `tests/unit/validators/test_leak_check_skips.py:169-187`,
  `tests/unit/validators/test_validator_value_free.py:81-87`.
- CLI: the ordinary run keeps the engine result in `_execution` (`run/_execute.py:480`); the
  report flags alone fill `_report_quality_metrics` (`:510-511`), so S4 reads `_execution`.
  The card (`run/_render.py:161-188`); the JSON branch (`:116-153`); preview calls
  `run_pipeline` with validators kept (`cli/gen/_preview.py:38-56`, `run/_execute.py:525-540`);
  explicit `--chunked` calls `run_mask_chunked` and gets no report (`run/_execute.py:76-78,223,420-437`).
  The error path: `run/_errors.py:172` `fail`, the context at `:312-349`, rendered by
  `run/_result.py:419-440`; the unwind at `run/_flow.py:227-232`. Bare `validate` uses
  `_emit_gate` and `gate_exit_code` (`cli/validate.py:314-327`); `validate config` uses
  `_emit_result` (`:165-170`); gate findings are built at `cli/gate/_layers.py:245-248`.
- CLI freeze: `tests/e2e/release_freeze/write_shapes.py:107-108` (skips optional subtrees) and
  `:458-462` (exit 0 only); `tests/e2e/release_freeze/test_json_shapes.py:103,118`;
  `docs/schemas/decoy-error-v1.schema.json:33` (already allows command context). The package
  census `tests/sentry/layout/test_run_package_shape.py:35-49,165-176`.

## Design

### Engine half, S4e (one PR)

1. Per-entry targets. Add `failed_targets: tuple[Target, ...]` to `ValidatorResult` (default
   empty), where `Target` is a named tuple `(table, column)` with `column` optional. The fold
   (`_fold.py:100-109`) already walks each entry's findings before combining them; it records
   that entry's distinct `(table, column)` pairs there. No finding detail is copied.
2. Whole-table skips. `unchecked_named_columns` expands a `column=None` skip against the
   entry's explicit `columns:` list for that table, so each named column gets its warning. The
   table-level `SkippedColumn` stays in the report. Default scope adds no warning.
3. Warnings channel. One function, `merge_validation_warnings(result) -> ExecutionResult`, runs
   once at the end of `run_pipeline` (`execution/_pipeline.py:165`) after every route has
   returned and stamped. It reads the stamped block and returns
   `dataclasses.replace(result, warnings=existing + new)`, skipping any warning already present
   by `(code, table, column)`. The copy in `quality_metrics["validation"]["warnings"]` stays (it
   is in the evidence manifest).
4. Docs: rows in `docs/qa/14-casting-validators-quarantine.md` and
   `docs/qa/15-execution-routes-native.md`; the `leak_check` paragraph at
   `docs/strategies.md:2338-2348`; compatibility contract entries for the new warning on
   `ExecutionResult.warnings` and the new `failed_targets` field, each with a `Breaking:` line
   per parent line 179 (`Breaking: none, additive`).

### CLI half, S4c (one PR, after the repin)

1. New `src/decoy/cli/run/_checks.py` (about 120 lines), registered in
   `test_run_package_shape.py` before `_errors` and `_render`; engine imports inside functions.
   - `project(source) -> Checks | Absent | Malformed`. The one input normalizer. It accepts the
     two real producer forms, a `ValidationReport` (from `exc.report`) and the stamped mapping
     (from `_execution.quality_metrics["validation"]`), and turns both into one strict
     projection: `passed`, and per entry `entry_index`, `validator`, `status`,
     `failing_row_count`, `failed_targets`, `skipped` (`table`, `column` or null, `code`).
     `Absent` means no block. `Malformed` means a block that fails any rule: missing status, a
     status outside the three values, a non-string or empty name, a code not in the engine
     warning registry, a bool or numeric string where an int is needed, a non-null non-string
     column. Unknown extra keys are ignored.
   - `validation_member(result, configured: bool)`: `Checks` gives the member; `Absent` with no
     validators configured gives `None`; `Absent` with validators configured or `Malformed`
     gives `{"reported": false}` and the fixed warning line `checks: engine did not report
     validator results`.
   - `checks_fact(member)` and `check_lines(member)`: one line per entry, for example
     `#0 leak_check passed`, `#1 leak_check failed customers.email, customers.phone`,
     `#2 leak_check skipped customers.phone (leak_check_skip_passthrough)`,
     `#3 row_count failed orders`.
2. `_render.py` `finish`: read `_execution`, add `payload["validation"]`, the fact after
   `Warnings`, and the lines after `render_warnings` (about +12). `finish_preview` (`:218`) does
   the same. Explicit `--chunked`: the engine returns no block, so validators configured give
   the `reported: false` member and line, never a pass.
3. Error path: `_errors.fail` adds the member to the existing context (`:312-349`) when the error
   is `ValidatorFailedError`; `_result.py:419-440` prints the check lines on the human branch,
   inside the existing unwind so `_flow.py:227-232` still removes the layout and sample scratch.
   One JSON document on stdout, exit 3; `--quiet` prints only the error line.
4. Validate: one advisory `GateFinding` per named skipped column, built once in
   `cli/gate/_layers.py:245-248`, so `validate` (through `_emit_gate`) and `validate config`
   (through `_emit_result`) both show it and `gate_exit_code` applies `--fail-on-warning`.
   Errors keep precedence, including the generate-table refusal.
5. Freeze: `write_shapes.py` types optional subtrees for `validation` and adds an exit-3
   fixture; `json-shapes.json` and the optional-key list in `test_json_shapes.py` change in the
   same commit.
6. Docs: `docs/guides/decoy-language/05-checks-and-subsets.md` shows the `Checks` lines and the
   warning. CHANGELOG entry.

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
| Two `leak_check` entries, one fails on `customers.email` | error card names `#1 ... customers.email` only | error payload `validation`, targets on entry 1 only | 3 |
| Table-level failure (`row_count`) | `#0 row_count failed orders` | target `{table, column: null}` | 3 |
| Quarantine-covered failure | `Checks  1 failed` on a success card | `passed = false` | 0 |
| Passthrough column named in `columns:` | skip line, `Warnings 1` | `skipped`, warning `leak_check_column_not_checked` | 0 |
| Named column in a table the run did not produce | one warning per named column | same | 0 |
| Default scope, a passthrough column | skip recorded, no warning | skip in `results[].skipped` | 0 |
| No validators | no fact | no `validation` key | 0 |
| Validators configured, explicit `--chunked` | `checks: engine did not report validator results` | `validation.reported = false` | 0 |
| Malformed block | the same fixed line | `validation.reported = false` | 0 |
| Preview, passing and failing | as the full run | as the full run | 0 / 3 |
| Forced out-of-core | as the default route | same | 0 |
| `validate` and `validate config`, named passthrough column | advisory naming `customers.email` | finding in the JSON result | 0, or 2 with `--fail-on-warning` |
| Same plus a config error | the error wins | error | as today |

## Acceptance tests (red first)

1. **V10e (engine, red-before).** Two named passthrough columns plus one named column in an
   unproduced table: `ExecutionResult.warnings` has three `leak_check_column_not_checked`, the
   evidence block has the same three, nothing duplicated, on resident and forced out-of-core.
   Extends `test_leak_check_skips.py:169-187`. Default-scope control: none.
2. **V10t (engine, red-before).** Two `leak_check` entries and one table-level validator: each
   result's `failed_targets` holds only its own targets.
3. **V11 card and JSON (CLI, red-before).** Every row of the table above, human and JSON, with
   no report flags. Error case asserts human stderr, `--quiet`, one JSON document, exit 3 and
   scratch removed. The forced out-of-core case asserts the route in the result. Reader cases:
   missing status, status `"ok"`, empty name, unknown code, bool and `"3"` counts, bool index,
   int column, empty skips, extra key tolerated; each gives the fixed line.
4. **V12 validate (CLI, red-before).** Both commands, human and JSON, exit 0 and exit 2 with
   `--fail-on-warning`, error precedence, and the default-scope control (no advisory).
5. **V13c value-free (CLI, control).** A marker value in every validated column, plus a marker
   placed in a synthetic `finding.detail` and passed through the real emitter
   (`test_validator_value_free.py:81-87` shows real details already exclude data). The marker is
   in no card line, JSON member, warning or error payload.
6. **Shape freeze (CLI).** The regenerated snapshot types `/validation` on success and on the
   exit-3 fixture.

CLI red runs happen on the repinned pre-S4c base, not on CLI main (which pins 0.28.3,
`pyproject.toml:153`).

Mutations:

| ID | Mutation | Test that must fail |
|---|---|---|
| R1 | `int()` in place of the strict count reader | V11 numeric-string case |
| R2 | Drop the member from the error payload | V11 failure case |
| R3 | Print only failed entries | V11 pass and skip lines |
| R4 | Skip `merge_validation_warnings` | V10e |
| R5 | Advisory for default-scope skips too | V12 default-scope case |
| R6 | Put `finding.detail` into a check line | V13c synthetic detail marker |
| R7 | Accept any skip code | V11 unknown-code case |
| R8 | Attribute all findings to every entry with the same name | V10t |
| R9 | Drop the whole-table expansion | V10e unproduced-table case |
| R10 | Read `_report_quality_metrics` instead of `_execution` | V11 no-report-flag case |
| R11 | Treat `Absent` with validators configured as no member | V11 `--chunked` case |

## Enumerations

### Exit paths

- Success: `_render.finish` (CLI `src/decoy/cli/run/_render.py:106`), exit 0, or 4 under
  `--post-validate-enforce` (unchanged); also a quarantine-covered failure.
- Preview: `finish_preview` (`_render.py:218`), exit 0 or 3.
- Validator failure: `ValidatorFailedError` to `_errors.fail` (CLI
  `src/decoy/cli/run/_errors.py:172`), exit 3, payload and human card gain the checks.
- Refusals before or after the write (`_errors.refused`, `:364`), parameter errors (`:373`),
  other engine errors (`:396`) and interrupts (`:408`): no validation member.
- `decoy validate` and `decoy validate config`: exit 0 with the advisory, 2 with
  `--fail-on-warning`; errors unchanged.

### Routes

- Every `run_pipeline` route stamps one report after S3b. The CLI reads the block, not the
  route; V11 runs on the default route and on a forced out-of-core run.
- Preview runs validators (`cli/gen/_preview.py:38-56`): same member.
- Explicit `--chunked` (`run_mask_chunked`, `run/_execute.py:420-437`): no block; the
  `reported: false` member.

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
| 2 | Cleanup on an exit path | The error card renders inside the existing unwind, which removes layout and sample scratch | V11 failure case asserts scratch removed | Render after the unwind: scratch assertion red |
| 3 | Shared state | Pure functions of one result; per-entry targets built inside the fold per entry | V10t | R8, shared targets |
| 4 | Route parity and silent fallback | One reader for card, preview, JSON and error; absent or malformed with validators configured shows a fixed line, never a pass | V11 malformed and `--chunked` cases | R2, R11 |
| 5 | Referential integrity | Skip codes are registered warning codes; the reader checks them against the engine registry | V11 skip case | Accept any string code: V11 red |
| 6 | Untrusted producer | The engine block is parsed strictly (engine and CLI may run different pins) | V11 reader cases | R1, `int()` reader |
| 7 | Check-then-use (toctou) | N/A: the metrics dict is read once after the run returns | none needed | N/A |
| 8 | Weak tests | Each red-before shown red on main; V13c guards new fields | builder report | R3, skip lines dropped |
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
| 9 | Mutations on the final head | R1 to R6 after the last change |
| 10 | Allowlisted helpers still checked | N/A: no allowlist added |
| 11 | No raised caps | No ceiling raised; CLI `_render.py` 239 to about 251 (package cap 600); engine `_pipeline_finalize.py` untouched by S4e (527 on #812) |

## Reuse inventory

- Engine `ValidatorResult`, `result_status`, `plan_scope`, `unchecked_named_columns`,
  `stamp_validation`, `dataclasses.replace` on `ExecutionResult`.
- CLI `render_card`, `warning_records`, `render_warnings`, `post_scan_members` pattern, the error
  payload in `_errors.fail`, the shape snapshot.

## Frozen contracts

- CLI `decoy run --json`: new optional `validation` member (success and error). Additive.
- Engine `ExecutionResult.warnings`: may now carry `leak_check_column_not_checked`. Engine
  `ValidatorResult.failed_targets`: new field with an empty default. Both additive, named in the
  compatibility contract with `Breaking: none`.
- No change to exit codes or to the `RunResult` document.

## Slices

- **S4e (engine)** `feat(validators): report unchecked named columns as run warnings`. Test V10e.
  After S3b.
- **S4c (CLI)** `feat(run): show every validator result on the card and in JSON`. Tests V11, V12,
  V13c. After the engine release and the CLI repin (repin checklist: compat, fences, frozen
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
- Open item: explicit `--chunked` reports no checks until `run_mask_chunked` returns a report;
  S4 shows that plainly and does not change the route.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; `~/bin/pytest-one`.
- Card and JSON text: names, codes, counts and statuses only; run V13c after each change.
- Do not edit the CLI half before the repin lands on CLI main.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entries in both repos.
