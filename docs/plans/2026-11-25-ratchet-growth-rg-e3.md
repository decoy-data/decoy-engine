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
  `ls-tree` listing, so "absent" is proven), `:125` `_probe`, `:147` `kind_of`, `:324` `fresh`,
  `:331` `new_decisions`, `:29` `DECISION_TABLES` with `checker_change`.
- `tests/sentry/_ratchet.py:324` `schema_waivers` (reads a JSON list of `[id, field]` pairs),
  `:344` `check(root, base_ref, waiver_input)`, `:404` the freshness rule for `checker_change`
  fields, and `:55` `_helper(name)`, which loads `tests/sentry/ratchet/<name>.py` by path
  relative to `_ratchet.py`. An extracted checker therefore loads its own helpers.
- `scripts/dev/ratchet_check.py:42-46` the `--schema-waiver-env` flag (RG-E1), read only when
  the flag is passed. The head run never passes it.
- `tests/sentry/test_ratchet_check.py:61-72` the subprocess harness and temp-repo fixtures.

## Design

Three parts. All new logic goes in one new helper so `_ratchet.py` (571 lines at #801) and
`_integrity.py` (517) do not grow.

1. `tests/sentry/ratchet/_base_run.py` (new, about 140 lines), loaded with `_ratchet._helper`:
   - `plan_base_run(tree) -> BasePlan | Skip | Fail`. Uses the `BaseTree` already built for the
     head check (one sha, one listing). If the listing omits `scripts/dev/ratchet_check.py`,
     return `Skip("ratchet: base has no checker, base run skipped")`. If it lists the path as
     anything other than a regular blob (mode `100644` or `100755`), return `Fail`.
   - `schema_waiver_pairs(root, tree, head_doc, base_doc) -> list[tuple[str, str]] | Fail`.
     Empty unless HEAD adds a fresh `[checker_change]` row. For each fresh field name F, all of
     these must hold, else `Fail` with a named reason:
     a. the diff from the base sha to the worktree edits `scripts/dev/ratchet_check.py`,
        `tests/sentry/_ratchet.py` or a file under `tests/sentry/ratchet/` whose name starts with
        `_` (a loaded helper);
     b. the same set of `[[sentry]]` ids in both registries;
     c. no file under `tests/sentry/baselines/` differs from the base sha;
     d. every changed `[[sentry]]` row differs from its base row only by the added key F.
     Output: the exact (id, F) pairs, sorted.
   - `extract(root, sha, dest)`: run `git -C root archive --format=tar <sha> scripts/dev
     tests/sentry` with stdout to a file in `dest`, check its exit code, then open the tar and
     extract with `filter="data"`. If `tarfile.data_filter` is missing (an old patch release),
     fail with "python lacks the tar data filter". Never read a partial stream.
   - `run_base(dest, root, sha, pairs) -> int`: build the child env from `os.environ` minus
     `RATCHET_SCHEMA_WAIVER`. When `pairs` is non-empty, set it to the JSON pairs and pass
     `--schema-waiver-env`. Run `[sys.executable, "-I", <dest>/scripts/dev/ratchet_check.py,
     "--root", root, "--base", sha, ...]`. Pass its stdout and stderr through. Return its exit
     code unchanged.
2. `scripts/dev/ratchet_check.py` (+25): add `--with-base`. Order: resolve the sha once with
   `resolve_commit` ("base commit not found: <ref>" and exit 1 on failure); run the head check
   with that sha (no waiver input; the head run never reads the env); then, only with
   `--with-base`, plan and run the base checker inside one `tempfile.TemporaryDirectory`. Exit
   1 when the head check fails, when the plan fails, or when the base run exits non-zero. Print
   each waiver use as `ratchet: waived by checker_change: <id> <field>`. The base run never
   turns a non-zero exit into success.
3. `scripts/dev/gates.sh` sentry step (`gates.sh:491`, +12): pass `$label` into the `bash -c`
   string as a positional argument. In the string:
   - checker present, label not `baseline`: run `ratchet_check.py --with-base`;
   - checker present, label `baseline`: run `ratchet_check.py` (older checkers accept only
     `--root` and `--base`, `scripts/dev/ratchet_check.py:40-41`);
   - checker missing, label `baseline`: skip only when `git ls-tree HEAD --
     scripts/dev/ratchet_check.py` succeeds and prints nothing; otherwise fail;
   - checker missing, any other label: print "ratchet checker missing" and exit 1.
   After the step, `grep` the step log for `ratchet: decision ` and `waived by checker_change`
   and copy those lines to gate stderr, also when the step passes.

Choke point: `ratchet_check.py --with-base` is the one place a base run starts. Guard test
`test_gate_sentry_step_calls_with_base` reads `gates.sh` and asserts the branch-label command
has `--with-base`. Mutation: drop the flag from `gates.sh`; the guard and
`test_base_checker_catches_growth_hidden_by_branch_checker_edit` both fail.

Design notes: one new helper module, no new abstraction that will grow. Established pattern:
`git archive` plus `tarfile` with the PEP 706 `data` filter, the same way CI tools pin a
reference copy of a linter. Each fact has one home: the base sha in `ratchet_check.py`, the
waiver rule in `_base_run.py`, the decision grammar in `_ratchet.DECISION`.

### Placement

| New or changed | Path | CODEMAP rule | Sits beside |
|---|---|---|---|
| Base-run helper | `tests/sentry/ratchet/_base_run.py` | ratchet helpers live in `tests/sentry/ratchet/_<concern>.py`, loaded by path | `_integrity.py` |
| Flag | `scripts/dev/ratchet_check.py` | gate tooling in `scripts/dev/` | `gates.sh` |
| Gate step | `scripts/dev/gates.sh` | same | |
| Tests | `tests/sentry/ratchet/test_base_run.py` | ratchet tests beside the helpers | `test_integrity.py` |

## Behavior and failure modes

| Change on the branch | Expected | Test |
|---|---|---|
| Deletes `ratchet_check.py` | Fail, "ratchet checker missing" | `test_missing_checker_fails_outside_baseline_tree` |
| Edits `_ratchet.py` so `check()` returns nothing, grows a baseline | Base copy fails the growth | `test_base_checker_catches_growth_hidden_by_branch_checker_edit` |
| Empties `integrity_findings` in the head helper, deletes a registry row | Base copy fails | `test_base_checker_ignores_tampered_head_helper` |
| Adds registry field F, edits the checker, adds fresh `[checker_change]` F | Pass, waiver line printed | `test_new_registry_key_with_checker_change_passes_base_run` |
| Same, no `[checker_change]` row | Fail | `test_new_registry_key_without_checker_change_fails_base_run` |
| `[checker_change]` row and a baseline edit | Fail | `test_checker_change_with_a_baseline_edit_fails` |
| `[checker_change]` F and another row edit | Fail | `test_schema_waiver_rejects_another_row_edit` |
| `[checker_change]` F and a sentry file deleted | Base copy still fails the deletion | `test_schema_waiver_cannot_hide_sentry_file_retirement` |
| Base listing fails | Fail, never skip | `test_failed_tree_listing_never_skips_base_checker` |
| Base lists the checker but the blob cannot be read | Fail | `test_listed_checker_read_error_never_skips` |
| `git archive` fails, or the base checker crashes, with a waiver present | Fail | `test_schema_waiver_cannot_hide_archive_failure_or_crash` |
| Base `_ratchet.py` has a syntax error | Fail, temp dir removed | `test_broken_base_checker_fails` |
| Base sha does not exist | Fail, "base commit not found" | `test_unreachable_base_sha_fails_with_base` |
| Base has no checker | Skip with one line | `test_base_checker_absent_skips_with_message` |
| Passing gate with a new decision row | Decision line on gate stderr | `test_decision_lines_shown_on_a_passing_gate` |
| Baseline-label run | No `--with-base` | `test_baseline_label_runs_without_with_base` |
| Baseline worktree with no checker | Skip, as today | `test_missing_checker_skips_in_baseline_tree` |
| An inherited `RATCHET_SCHEMA_WAIVER` in the gate env | Ignored by the head run and replaced for the base run | `test_inherited_waiver_env_is_stripped` |
| This slice's own head, judged by the #801 checker | Pass | `test_live_registry_passes_with_base` |

## Acceptance tests (red first)

File: `tests/sentry/ratchet/test_base_run.py` (new, about 220 lines). Each test builds a temp
repo with the fixtures in `test_ratchet_check.py:40-72` (imported, not copied), commits a base,
edits the worktree, then runs `ratchet_check.py --with-base --root <repo> --base <base sha>` or
the gate's sentry-step shell line. Tag in the docstring: `red-before` (fails on main, recorded by
the builder before the fix) or `pin` (passes on main, never offered as red evidence). An argparse
error for the unknown flag is not red-before proof: on main each red-before test must fail on its
assertion. The harness falls back to the plain command when `--with-base` is unknown, and the
test asserts the missed finding.

red-before:

1. `test_missing_checker_fails_outside_baseline_tree`
2. `test_base_checker_catches_growth_hidden_by_branch_checker_edit`
3. `test_base_checker_ignores_tampered_head_helper`
4. `test_new_registry_key_with_checker_change_passes_base_run`
5. `test_new_registry_key_without_checker_change_fails_base_run`
6. `test_checker_change_with_a_baseline_edit_fails`
7. `test_failed_tree_listing_never_skips_base_checker`
8. `test_listed_checker_read_error_never_skips`
9. `test_schema_waiver_cannot_hide_archive_failure_or_crash`
10. `test_schema_waiver_cannot_hide_sentry_file_retirement`: the branch adds field F validly and
    deletes an unrelated sentry file; the head retirement check is disabled in the branch, so
    only the extracted checker can reject the deletion.
11. `test_schema_waiver_rejects_another_row_edit`
12. `test_broken_base_checker_fails`: also asserts the temp directory no longer exists.
13. `test_unreachable_base_sha_fails_with_base`
14. `test_base_checker_absent_skips_with_message`
15. `test_decision_lines_shown_on_a_passing_gate`
16. `test_inherited_waiver_env_is_stripped`
17. `test_gate_sentry_step_calls_with_base`

pin:

18. `test_missing_checker_skips_in_baseline_tree`
19. `test_baseline_label_runs_without_with_base` (engine `gates.sh:474,491`)
20. `test_live_registry_passes_with_base`: the real repo against `origin/main`.

Mutations (the builder runs each on the final head and records the result):

| ID | Mutation | Test that must fail |
|---|---|---|
| M1 | `--with-base` returns the head result and never runs the base | 2, 3 |
| M2 | Restore the unconditional `[ -f ... ]` skip in `gates.sh` | 1 |
| M3 | Treat a failed `ls-tree` as "absent" | 7 |
| M4 | Return 0 when `git archive` exits non-zero | 9 |
| M5 | Replace `TemporaryDirectory` with `mkdtemp` | 12 |
| M6 | Skip check (c), the baseline-edit check | 6 |
| M7 | Skip check (d), the other-row-edit check | 11 |
| M8 | Pass the parent env through unchanged | 16 |
| M9 | Load base helpers from the head root | 3 |
| M10 | Do not copy decision lines on a pass | 15 |

## Enumerations

### Exit paths

- `ratchet_check.py --with-base`: head finding (exit 1); base sha missing (exit 1); listing
  fails (exit 1); checker listed but unreadable or not a regular blob (exit 1); archive or
  extraction fails (exit 1); base run non-zero (exit 1); checker absent on base (skip line, exit
  0 if the head passed); both pass (exit 0). No merge base and no `--base` keeps exit 2
  (`scripts/dev/ratchet_check.py:55-57`).
- `ratchet_check.py` without `--with-base`: unchanged (`scripts/dev/ratchet_check.py:59-68`).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:344`): findings plus report lines; base read
  errors become one named finding (`tests/sentry/_ratchet.py:353-356`).
- Sentry step (`scripts/dev/gates.sh:491`): the four cases in Design part 3.

### Routes

| Route into the checker | Where | This slice |
|---|---|---|
| Local gate, branch label | `scripts/dev/gates.sh:491` | `--with-base` |
| Local gate, baseline label | same line, `label=baseline` | plain run, or skip on proven absence |
| Self-hosted gate on branch pushes | `.github/workflows/gate-selfhosted.yml:84-85` | same as the local gate |
| CI tests job | `.github/workflows/ci.yml:147` (fetch-depth 0 for the merge base) | same as the local gate |
| Direct test harness | `tests/sentry/test_ratchet_check.py:61-72` | unchanged |

### FK shapes

N/A. This slice reads only repo files and git objects. No keyed data and no FK logic.

### Fields

| Field | Where | Change |
|---|---|---|
| `[checker_change]` key | `scripts/dev/sentry_registry.toml` | read; key = the added registry field name; value = dated owner decision |
| `RATCHET_SCHEMA_WAIVER` | child env only | JSON list of `[id, field]`; set only for the extracted run |
| `--with-base` | `ratchet_check.py` argv | new flag |
| Gate step label | `run_steps` local `label` (`scripts/dev/gates.sh:473`) | passed into the step string |

### Output surfaces

- `ratchet_check.py` stdout and stderr: `ratchet: base has no checker, base run skipped`,
  `ratchet: waived by checker_change: <id> <field>`, `ratchet: FAIL ...` lines from either run,
  `base commit not found: <ref>`. Only ids, paths, field names, shas and decision text the owner
  wrote. No file content.
- Gate stderr: `ratchet checker missing`; the copied `ratchet: decision ...` and waiver lines.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Findings carry ids, paths, field names and shas only; the base run's own output is passed through as is | `test_schema_waiver_rejects_another_row_edit` asserts the finding names the id and key, not the row text | Print the row dict in the finding: the message assertion fails |
| 2 | Cleanup on an exit path | Extraction happens inside one `TemporaryDirectory` context, removed on every exit | `test_broken_base_checker_fails` asserts the directory is gone | M5, `mkdtemp` in place of the context |
| 3 | Shared state | No module state; the env for the child is built fresh; the head run never reads the env | `test_inherited_waiver_env_is_stripped` | M8, pass the parent env through |
| 4 | Route parity and silent fallback | One `--with-base` path for the local gate, the self-hosted gate and CI; no skip except proven absence | tests 1, 7, 17 | M2, M3 |
| 5 | Referential integrity | (id, field) pairs must name ids in both registries and a field added on the diff | `test_schema_waiver_rejects_another_row_edit` | M7, skip check (d) |
| 6 | Untrusted producer | N/A for V1: inputs are the repo's own files and git objects (accidental-only threat model); the tar is still unpacked with the `data` filter | `test_broken_base_checker_fails` covers a bad base tree | Drop the filter: review finding |
| 7 | Check-then-use (toctou) on the base | The sha is resolved once and the same sha feeds the listing, the archive and the base run | test 13 plus code review | Resolve the ref twice: review finding |
| 8 | Weak tests | Red-before tests fail on their assertion on main, not on argparse; pins are marked | builder report lists each red result | M1, never run the base |
| 9 | Refactor drift | N/A: no function moves; new logic is a new helper | existing `test_ratchet_check.py` passes unchanged | N/A |
| 10 | Frozen contract drift | N/A: test and gate tooling only; no public name or reason code | census sentries stay green | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decision rows keep `DECISION` with `fullmatch`; field names compared exactly |
| 2 | Strict wire types | `schema_waivers` already refuses anything but a list of string pairs (`_ratchet.py:324-341`) |
| 3 | No exception context | No re-raise; failures become named finding lines |
| 4 | Versioned read models | The base checker runs with flags it knows; `--schema-waiver-env` only when pairs exist |
| 5 | Normalized guard scanners | Row comparison uses parsed TOML, not text |
| 6 | Private modules | Helpers load by path; no private engine import |
| 7 | No hidden CI failures | The only skip is proven checker absence, printed; every other failure exits 1 |
| 8 | One input, one trust class | N/A: one input class (repo files) |
| 9 | Mutations on the final head | M1 to M10 rerun after the last code change, head recorded |
| 10 | Allowlisted helpers still checked | N/A: no allowlist gains a helper |
| 11 | No raised caps | `_ratchet.py` and `_integrity.py` do not grow; `_baseline_sources.py` (653 at #801) is not touched |

## Reuse inventory

- `_integrity.resolve_commit`, `BaseTree`, `kind_of`, `fresh`, `new_decisions`, `decisions`.
- `_ratchet.schema_waivers`, `check`, `_helper`.
- `ratchet_check.py --root`, `--base`, `--schema-waiver-env`.
- `test_ratchet_check.py` temp-repo helpers, imported.
- `tarfile` with `filter="data"`, `tempfile.TemporaryDirectory`, `git archive`: stdlib and git,
  no hand-rolled tar code.

## Frozen contracts

None. Test and gate tooling only. The `gates.sh` step names and the `--steps` list stay the same.

## Slices

One slice, one PR: `feat(sentry): gate runs the base ratchet checker`. Next: RG-C1a (CLI), which
ports this helper.

Test depth: T0 `tests/sentry/ratchet/test_base_run.py` and `tests/sentry/test_bash32_compat.py`
per edit; T1 impact selection per commit; the gate runs `gates.sh --keep-going --steps
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
- Never raise a module-size ceiling; no touched file grows past 600 lines.
- Builders never write owner decision rows. Fixture rows inside `tmp_path` repos are fine.
- Run each red-before test on main first and record the failure; pins are not red evidence.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG fragment before merge.
- Stop and report if the same defect class comes back after a fix.
