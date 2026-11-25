# RG-E3: the gate runs the base checker (engine)

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
catalogs/recurring-defects; owner notes on the V1 threat model, plan-defines-acceptance-tests and
root-cause fixes.

Row: RATCHET-GROWTH. Parent plan: `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`
(section "RG-E3"), with owner decisions Q1 to Q7 of 2026-11-24. This file is the slice plan: it
re-reads the RG-E2 head and turns the row text into build steps.

Risk: R2 (CI and gate tooling). Size: half a day. Depends on RG-E2 (PR #801, open at
`f15adce3f`). Anchor: engine main `2b8a47fbe` plus the #801 head. The builder re-anchors every
line number below on main after #801 merges and before the first commit.

## Problem

`ratchet_check.py` runs the HEAD copy of the checker (`scripts/dev/ratchet_check.py:26-35` loads
`tests/sentry/_ratchet.py` from the checked tree). A branch that edits `_ratchet.py` or one of its
helpers can, by accident, stop a baseline growth from being seen, and the same edited code then
judges itself. The sentry step also skips the checker when the file is missing on any tree
(`scripts/dev/gates.sh:491`), so a branch that deletes the checker gets a green step.

## Guarantee

On every non-baseline gate run, the checker as it exists on the base commit also judges the
branch tree, and it uses its own helpers, not the branch's. A branch can pass only when both the
head checker and the base checker pass. The one allowed difference is a dated owner
`[checker_change]` row that adds one registry field, and that row is printed on the gate.

Non-goals:

- No signed approvals (V2, owner Q1).
- No defence against a hostile branch that rewrites `gates.sh` or `ratchet_check.py --with-base`
  on purpose (the V1 threat model covers accidental leaks and accidental loosening only).
- No CLI change (RG-C1a). No new baseline, no new bound (RG-E2 did those).
- No workflow edit: `gate-selfhosted.yml:84-85` and the CI tests job already run the sentry step.

## What exists (reuse, do not rebuild)

At the #801 head:

- `tests/sentry/ratchet/_integrity.py:50` `resolve_commit`, `:60` `BaseTree` (one checked
  `ls-tree` listing, so "absent" is proven), `:125` `_probe`, `:147` `kind_of`, `:285-291` the
  report line for each schema waiver the checker actually used, `:324` `fresh`, `:331`
  `new_decisions`, `:362` `transfer_findings`, `:29` `DECISION_TABLES` with `checker_change`.
- `tests/sentry/_ratchet.py:324` `schema_waivers` (reads a JSON list of `[id, field]` pairs),
  `:344-355` `check(root, base_ref, waiver_input)`, which resolves the ref and builds `BaseTree`
  itself, `:394-398,456-460` where the parsed registry rows are read and then dropped, `:404`
  the freshness rule for `checker_change` fields, and `:55-75` `_helper(name)`, which loads
  `tests/sentry/ratchet/<name>.py` by path relative to `_ratchet.py`. An extracted checker
  therefore loads its own helpers.
- `scripts/dev/ratchet_check.py:42-46,59-65` the `--schema-waiver-env` flag (RG-E1), read only
  when passed, and the print of the checker's report lines.
- `tests/sentry/ratchet/test_reader_guard.py:27-56,84-100`: forbids `open`, `run` and
  `tarfile.open` in ratchet helpers outside their named owners.
- `tests/sentry/test_ratchet_check.py:40-72` temp-repo fixtures; `tests/unit/scripts/_gates_harness.py:189`
  runs the real gate shell and returns its exit and stderr.
- Historical parser: `cb06f318e:scripts/dev/ratchet_check.py:39-41` accepts only `--root` and
  `--base`; its `_ratchet.py:55-64` already tolerates extra row fields.

## Design

Four parts. Process and archive I/O live in `ratchet_check.py`, which is gate tooling and is not
scanned by the reader guard. The new helper holds only comparison logic, so the reader guard
keeps passing.

1. `tests/sentry/_ratchet.py` (+15, 571 to about 586): split `check` into
   `check_tree(root, tree, waiver_input) -> CheckResult` (findings, report lines, the head and
   base registry rows already parsed at `:394-398,456-460`) and keep
   `check(root, base_ref, waiver_input)` as a thin wrapper with the same signature and output, so
   every caller keeps working. Add `CHECKER_HELPERS`, the tuple of names `_helper` may load; a
   guard test asserts every `_helper("...")` literal in `_ratchet.py` is in it.
2. `tests/sentry/ratchet/_base_run.py` (new, about 90 lines, no I/O), loaded with
   `_ratchet._helper`:
   - `plan_base_run(tree) -> BasePlan | Skip | Fail`. Uses the `BaseTree` from `check_tree`. If
     the listing omits `scripts/dev/ratchet_check.py`, `Skip("ratchet: base has no checker, base
     run skipped")`. A listed path that is not a regular blob (`100644` or `100755`) is `Fail`.
     A failed listing is `Fail` through the same handler `check_tree` uses, never `Skip`.
   - `schema_waiver_pairs(changed_paths, head_rows, base_rows, fresh_fields) -> pairs | Fail`.
     Empty unless HEAD adds a fresh `[checker_change]` row. For each fresh field F, all must
     hold, else `Fail` with a named reason:
     a. `changed_paths` includes `scripts/dev/ratchet_check.py`, `tests/sentry/_ratchet.py` or
        `tests/sentry/ratchet/<name>.py` for a name in base `CHECKER_HELPERS`. An edit only to
        `_limit_constants.py` (loaded by `_baseline_sources.py:82-91`, not by the checker) does
        not count;
     b. the same set of `[[sentry]]` ids in both registries;
     c. no file under `tests/sentry/baselines/` differs from the base sha;
     d. every changed row differs from its base row only by the added key F;
     e. at least one row adds F (a decision for a field no row adds is a finding).
     Output: the exact (id, F) pairs, sorted.
   - `accepts_waiver_flag(base_source: str) -> bool`: true when the base `ratchet_check.py`
     argparse source declares `--schema-waiver-env`.
3. `scripts/dev/ratchet_check.py` (+45, about 70 to about 115): add `--with-base`. Order:
   resolve the sha once (`base commit not found: <ref>`, exit 1); build the one `BaseTree`; run
   `check_tree` for the head with no waiver input; then, only with `--with-base`:
   - `plan_base_run`; on `Skip` print the line; on `Fail` exit 1.
   - compute changed paths with one `git diff --name-only <sha>` and the pairs.
   - extract: `git archive --format=tar <sha> scripts/dev tests/sentry` to a file inside one
     `tempfile.TemporaryDirectory`, check the exit code, then `tarfile` with `filter="data"`. A
     Python without `tarfile.data_filter` fails with "python lacks the tar data filter".
   - child: `[sys.executable, "-I", <dest>/scripts/dev/ratchet_check.py, "--root", root,
     "--base", sha]`, env from `os.environ` minus `RATCHET_SCHEMA_WAIVER`. When pairs exist and
     `accepts_waiver_flag(base source)` is true, set the env to the JSON pairs and add
     `--schema-waiver-env`. When pairs exist and the base checker lacks the flag, exit 1 ("base
     checker cannot take a schema waiver"): an older checker tolerates the extra field
     unaided, so the plain run is tried first and only its failure is reported. With no pairs
     the child gets the plain command.
   - the child's stdout and stderr pass through once. The waiver-use line is the one the
     checker itself prints at `_integrity.py:285-291`; the launcher prints no second format.
   - exit 1 when the head fails, the plan fails, extraction fails or the child exits non-zero.
   `--schema-waiver-env` without `--with-base` keeps working unchanged, so a later branch that
   extracts this file as its base can still pass waivers to it.
4. `scripts/dev/gates.sh` sentry step (`gates.sh:491`, about +15; the shell file is not in the
   Python module-size scan): pass `$label` (`gates.sh:474`) into the `bash -c` string:
   - checker present, label not `baseline`: `ratchet_check.py --with-base`;
   - checker present, label `baseline`: plain `ratchet_check.py`;
   - checker missing, label `baseline`: skip only when `git ls-tree HEAD --
     scripts/dev/ratchet_check.py` succeeds and prints nothing; a listed-but-missing file or a
     failed listing fails;
   - checker missing, other label: "ratchet checker missing", exit 1.
   A checker failure writes a marker file in the step dir. In `--baseline` mode
   (`gates.sh:531-539,666-672`) the final exit checks that marker after
   `_gates_report.py` (`:300-313`) and fails the gate even when every JUnit failure is classed
   as shared. After the step, copy `ratchet: decision ` and waiver lines from the step log to
   gate stderr, also on a pass.

Choke point: `ratchet_check.py --with-base` is the one place a base run starts. Guard test
`test_gate_sentry_step_calls_with_base` reads `gates.sh` and asserts the branch-label command
has `--with-base`. Mutation: drop the flag from `gates.sh`; the guard and test 15 (which runs
the real gate through `_gates_harness.py:189`) fail. Test 2 calls `ratchet_check.py` directly,
so it does not observe this mutation.

Design notes: one new helper, no new abstraction that will grow. Established pattern: `git
archive` plus `tarfile` with the PEP 706 `data` filter. Each fact has one home: the base sha and
all I/O in `ratchet_check.py`, the waiver rule in `_base_run.py`, the loaded-helper list in
`_ratchet.CHECKER_HELPERS`, the decision grammar in `_ratchet.DECISION`.

### Placement

| New or changed | Path | CODEMAP rule | Sits beside |
|---|---|---|---|
| Base-run rules | `tests/sentry/ratchet/_base_run.py` | ratchet helpers live in `tests/sentry/ratchet/_<concern>.py`, loaded by path, no I/O | `_integrity.py` |
| Split of `check` | `tests/sentry/_ratchet.py` | the checker | |
| Flag and I/O | `scripts/dev/ratchet_check.py` | gate tooling in `scripts/dev/` | `gates.sh` |
| Gate step | `scripts/dev/gates.sh` | same | |
| Tests | `tests/sentry/ratchet/test_base_run.py` | ratchet tests beside the helpers | `test_integrity.py` |

## Behavior and failure modes

| Change on the branch | Expected | Test |
|---|---|---|
| Deletes `ratchet_check.py` | Fail, "ratchet checker missing" | 1 |
| Edits `_ratchet.py` so `check()` returns nothing, grows a baseline | Base copy fails the growth | 2 |
| Head `_integrity.transfer_findings` returns nothing; one of two inventories and its baseline removed | Base copy names the removed id | 3 |
| Adds field F, edits the checker, fresh `[checker_change]` F | Pass, the checker's own waiver line once | 4 |
| Same, no `[checker_change]` row | Fail | 5 |
| `[checker_change]` and a whitespace-only baseline edit | Fail | 6 |
| Base listing fails | Fail, never skip | 7 (pin) |
| Listed checker blob unreadable | Fail | 8 |
| `git archive` fails, or the base checker crashes, with a waiver | Fail | 9 |
| `[checker_change]` F and an unrelated sentry file deleted, head retirement disabled | Base copy fails the deletion | 10 |
| `[checker_change]` F and an otherwise valid extra row edit | Fail | 11 |
| Base `_ratchet.py` syntax error | Fail, temp dir removed | 12 |
| Base sha missing | Fail, "base commit not found" | 13 (pin) |
| Base has no checker | Skip with one line | 14 |
| Passing gate with a new decision row | Decision line on gate stderr | 15 |
| Inherited `RATCHET_SCHEMA_WAIVER` | Child env recorded: no var with zero pairs, exact pairs otherwise | 16 |
| Gate step string | `--with-base` on branch label | 17 |
| Checker failure plus the same serial pytest failure on both trees in `--baseline` mode | Gate exits non-zero | 18 |
| Edit only to `_limit_constants.py` plus `[checker_change]` F | Fail, not a checker edit | 19 |
| `[checker_change]` F, no row adds F | Fail | 20 |
| Base checker accepts the field with no suppression | No waiver line | 21 |
| Base predates RG-E1 (`cb06f318e`), no pairs | Plain child command, pass | 22 |
| Standalone `--schema-waiver-env` without `--with-base` | Works as on #801 | 23 (pin) |
| Baseline label, checker listed but file missing | Fail | 24 |
| Baseline label, listing fails | Fail | 25 |
| Baseline label with checker | No `--with-base` | 26 (pin) |
| Baseline worktree with proven no checker | Skip, as today | 27 (pin) |
| Live repo | Pass with `--with-base` against the real merge base | 28 (pin) |

## Acceptance tests (red first)

File: `tests/sentry/ratchet/test_base_run.py` (new, about 300 lines; tests are outside the module
size scan). Each test builds a temp repo with the fixtures in `test_ratchet_check.py:40-72`
(imported), seeds and commits the checker (`scripts/dev/ratchet_check.py`, `tests/sentry/_ratchet.py`,
`tests/sentry/ratchet/_*.py`) into it, commits a base, edits the worktree, and launches the
scratch repo's own `ratchet_check.py`. Each test first proves the edited head passes on its own
(head check only), so the failure comes from the base run. Gate tests run the real gate through
`_gates_harness.py:189`.

Tags: `red-before` fails on its assertion on main; `pin` passes on main. For the red run only,
the harness falls back to the plain command when `--with-base` is unknown, and the test asserts
the missed finding. An argparse error is never red evidence.

red-before: 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25.

pin: 7 and 13 (main already rejects a bad sha and a failed listing at `_ratchet.py:349-355`;
test 13 matches `test_integrity.py:360-363`), 23, 26, 27, 28. Test 28 runs in CI and fails (does
not skip) if `--with-base` or the merge base is missing; the skip at `test_integrity.py:399-405`
stays for the plain test only. The #801 pin is checked separately from moving `origin/main`.

Mutations (the builder runs each on the final head and records the result):

| ID | Mutation | Test that must fail |
|---|---|---|
| M1 | `--with-base` returns the head result and never runs the base | 2, 3 |
| M2 | Restore the unconditional `[ -f ... ]` skip in `gates.sh` | 1 |
| M3 | The shared listing-failure handler returns "absent" | 7, 25 |
| M4 | Ignore the `git archive` exit code | 9 |
| M5 | Disable cleanup while keeping the child's syntax-error path; `TMPDIR` set to a test dir | 12 (directory not empty) |
| M6 | Skip check (c) | 6 |
| M7 | Skip check (d) | 11 |
| M8 | Pass the parent env through unchanged | 16 |
| M9 | Load base helpers from the head root | 3 |
| M10 | Do not copy decision lines on a pass | 15 (outer gate stderr) |
| M11 | Drop the marker check in `--baseline` mode | 18 |
| M12 | Treat any `_`-prefixed file as a checker edit | 19 |
| M13 | Skip check (e) | 20 |
| M14 | Launcher prints its own waiver line | 21 |
| M15 | Always pass `--schema-waiver-env` | 22 |

## Enumerations

### Exit paths

- `ratchet_check.py --with-base`: head finding (exit 1); base sha missing (exit 1); listing
  fails (exit 1); checker listed but unreadable or not a regular blob (exit 1); waiver rule
  fails (exit 1); base lacks the waiver flag while pairs exist (exit 1); archive or extraction
  fails (exit 1); base run non-zero (exit 1); checker absent on base (skip line, exit 0 if the
  head passed); both pass (exit 0). No merge base and no `--base` keeps exit 2
  (`scripts/dev/ratchet_check.py:55-57`).
- `ratchet_check.py` without `--with-base`: unchanged (`scripts/dev/ratchet_check.py:59-68`).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:344`): findings plus report lines; base read
  errors become one named finding (`tests/sentry/_ratchet.py:353-356`).
- Sentry step (`scripts/dev/gates.sh:491`): the four cases in Design part 4, plus the marker
  that keeps a checker failure red in `--baseline` mode (`gates.sh:531-539,666-672`).

### Routes

| Route into the checker | Where | This slice |
|---|---|---|
| Local gate, branch label | `scripts/dev/gates.sh:491` | `--with-base` |
| Local gate, baseline label | same line, `label=baseline` | plain run, or skip on proven absence |
| Self-hosted gate on branch pushes | `.github/workflows/gate-selfhosted.yml:84-85` | same as the local gate |
| CI tests job | `.github/workflows/ci.yml:150` (fetch-depth 0); pytest at `:194,203` | test 28 runs `--with-base` against the merge base and fails if it cannot |
| CI regression job | `.github/workflows/ci.yml:135` (skips PRs) | unchanged |
| Direct test harness | `tests/sentry/test_ratchet_check.py:61-72` | unchanged |

### FK shapes

N/A. This slice reads only repo files and git objects. No keyed data and no FK logic.

### Fields

| Field | Where | Change |
|---|---|---|
| `[checker_change]` key | `scripts/dev/sentry_registry.toml` | read; key = the added registry field name; value = dated owner decision |
| `RATCHET_SCHEMA_WAIVER` | child env only | JSON list of `[id, field]`; set only for the extracted run |
| `--with-base` | `ratchet_check.py` argv | new flag |
| Gate step label | `run_steps` local `label` (`scripts/dev/gates.sh:474`) | passed into the step string |
| `CHECKER_HELPERS` | `tests/sentry/_ratchet.py` | new tuple, guarded against `_helper` literals |

### Output surfaces

- `ratchet_check.py` stdout and stderr: `ratchet: base has no checker, base run skipped`,
  the checker's own waiver-use line (`_integrity.py:285-291`, printed once), `ratchet: FAIL ...`
  lines from either run,
  `base commit not found: <ref>`. Only ids, paths, field names, shas and decision text the owner
  wrote. No file content.
- Gate stderr: `ratchet checker missing`; the copied `ratchet: decision ...` and waiver lines.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Findings carry ids, paths, field names and shas only; the base run's own output is passed through as is | `test_schema_waiver_rejects_another_row_edit` asserts the finding names the id and key, not the row text | Print the row dict in the finding: the message assertion fails |
| 2 | Cleanup on an exit path | Extraction happens inside one `TemporaryDirectory` context, removed on every exit | test 12 asserts its controlled `TMPDIR` is empty | M5, cleanup disabled |
| 3 | Shared state | No module state; the env for the child is built fresh; the head run never reads the env | `test_inherited_waiver_env_is_stripped` | M8, pass the parent env through |
| 4 | Route parity and silent fallback | One `--with-base` path for the local gate, the self-hosted gate and CI; no skip except proven absence; a checker failure stays red in `--baseline` mode | tests 1, 7, 17, 18, 28 | M2, M3, M11 |
| 5 | Referential integrity | (id, field) pairs must name ids in both registries and a field added on the diff | `test_schema_waiver_rejects_another_row_edit` | M7, skip check (d) |
| 6 | Untrusted producer | N/A for V1: inputs are the repo's own files and git objects (accidental-only threat model); the tar is still unpacked with the `data` filter | `test_broken_base_checker_fails` covers a bad base tree | Drop the filter: review finding |
| 7 | Check-then-use (toctou) on the base | The sha is resolved once and the same sha feeds the listing, the archive and the base run | test 13 plus code review | Resolve the ref twice: review finding |
| 8 | Weak tests | Red-before tests fail on their assertion on main, not on argparse; pins are marked | builder report lists each red result | M1, never run the base |
| 9 | Refactor drift | `check` stays a wrapper over `check_tree` with the same output | existing `test_ratchet_check.py` and `test_integrity.py` pass unchanged | Drop the report lines from the wrapper: existing tests fail |
| 10 | Frozen contract drift | N/A: test and gate tooling only; no public name or reason code | census sentries stay green | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decision rows keep `DECISION` with `fullmatch`; field names compared exactly |
| 2 | Strict wire types | `schema_waivers` already refuses anything but a list of string pairs (`_ratchet.py:324-341`) |
| 3 | No exception context | No re-raise; failures become named finding lines |
| 4 | Versioned read models | The base checker runs with flags it knows: `accepts_waiver_flag` reads the base source; plain command otherwise (test 22, M15) |
| 5 | Normalized guard scanners | Row comparison uses parsed TOML, not text |
| 6 | Private modules | Helpers load by path; no private engine import |
| 7 | No hidden CI failures | The only skip is proven checker absence, printed; every other failure exits 1 |
| 8 | One input, one trust class | N/A: one input class (repo files) |
| 9 | Mutations on the final head | M1 to M10 rerun after the last code change, head recorded |
| 10 | Allowlisted helpers still checked | `_base_run.py` is scanned by the reader guard like every helper; the guard runs at T0 |
| 11 | No raised caps | `_ratchet.py` 571 to about 586, `ratchet_check.py` about 115, `_integrity.py` unchanged; `_baseline_sources.py` (653 at #801) not touched; `test_module_size.py:72-75,157-158` needs no change |

## Reuse inventory

- `_integrity.resolve_commit`, `BaseTree`, `kind_of`, `fresh`, `new_decisions`, `decisions`.
- `_ratchet.schema_waivers`, `check`, `_helper`; `_integrity.py:285-291` waiver report.
- `ratchet_check.py --root`, `--base`, `--schema-waiver-env`.
- `test_ratchet_check.py` temp-repo helpers, imported.
- `tarfile` with `filter="data"`, `tempfile.TemporaryDirectory`, `git archive`: stdlib and git,
  no hand-rolled tar code.

## Frozen contracts

None. Test and gate tooling only. The `gates.sh` step names and the `--steps` list stay the same.

## Slices

One slice, one engine PR after #801: `feat(sentry): gate runs the base ratchet checker`. CLI
work stays in RG-C1a (parent lines 656, 745-747). RG-C1a needs the archive path list to be a
parameter of the launcher, so `ratchet_check.py` takes the archive paths from one module
constant `BASE_ARCHIVE_PATHS` and drops any path the base listing does not contain. The same PR
narrows the `except` clauses at `_integrity.py:168,187,221` to named error types and splits the
function at `:362`, so the CLI copy passes CLI lint debt (`BLE001`, `C901`) unchanged.

Test depth: T0 `tests/sentry/ratchet/test_base_run.py`, `tests/sentry/ratchet/test_reader_guard.py`
and `tests/sentry/test_bash32_compat.py` per edit; T1 impact selection per commit; the gate runs `gates.sh --keep-going --steps
env,ruff,format,mypy,sentry` on the exact head. Test-tooling trigger: one full suite at merge,
diffed against the saved main baseline.

## Pre-mortem

- RG-E3's own head fails the #801 base checker. It adds no registry field, so it should pass;
  test 20 runs it before review.
- The base tree imports something outside `scripts/dev` and `tests/sentry`. The base run then
  fails loudly (exit 1), not silently. The builder runs `--with-base` against a real main sha
  before review. If it fails, widen the archive path list, never the skip rule.
- `-I` hides a package the checker needs. The checker uses only stdlib and the TOML reader from
  the gate venv, which `-I` keeps. The builder confirms on the gate venv.
- Bash 3.2: the step string uses only positional args and `[ ]` tests; `test_bash32_compat.py`
  runs.
- Gate time. The base run reads the same small set of files; expect under 5 seconds.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, no body unless it says
  why, last line `cam`. No trailers, file lists or test counts.
- Test depth T0 to T2 as in "Slices"; use `~/bin/pytest-one`.
- Never raise a module-size ceiling; no touched Python file grows past 600 lines (`gates.sh` is
  shell, 682 lines, outside the scan; keep its growth to the step).
- Builders never write owner decision rows. Fixture rows inside `tmp_path` repos are fine.
- Run each red-before test on main first and record the failure; pins are not red evidence.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG fragment before merge.
- Stop and report if the same defect class comes back after a fix.
