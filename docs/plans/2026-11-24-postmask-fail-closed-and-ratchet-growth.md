# Post-mask fail-closed and ratchet growth guard

Status: plan

Date: 2026-11-24. Rows: POSTMASK-FAIL-CLOSED (CLI `docs/roadmap/groups/trust.md`) and
RATCHET-GROWTH (CLI `docs/roadmap/groups/health.md`).

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`profiles/local-operations.md`, `bugfix.md`, `testing.md`, `workspace-and-vcs.md`,
`cross-cutting-concerns.md`, `architecture.md`, `reuse-first.md`, `proportionality.md`.

Code was read from engine `origin/main` (this worktree) and CLI `origin/main` with `git show`.
Line counts are from those trees on 2026-11-24.

## Slices

| Slice | Repo | Risk | Size | Depends on |
|---|---|---|---|---|
| PM-1 post-mask identity fails closed | engine | R1 | half a day | none |
| RG-E1 registry integrity | engine | R2 | one day | none |
| RG-E2 limits carry a max | engine | R2 | one day | RG-E1 |
| RG-E3 gate runs the base checker | engine | R2 (CI) | half a day | RG-E1 |
| RG-C1 CLI port | CLI | R2 (CI) | one day | RG-E1, RG-E2, RG-E3 merged |

PM-1 is independent and can run in parallel with RG-E1.

# Part 1. POSTMASK-FAIL-CLOSED

## Problem

`_source_identity` in `src/decoy_engine/verification/postmask/residual_pii.py` (lines 240-274)
wraps the whole comparison in `try: ... except Exception: return None`. None also means "not
comparable": the table or column is missing, row counts differ, or no row has both sides present.
So a comparison that raised looks the same as a column with nothing to compare. The caller builds
`ColumnFacts` with no `identity_error`, and no error finding is written. A leak check that crashed
reports as a clean check.

## What already exists (do not rebuild)

- `ColumnFacts.identity_error: str | None` in `postmask/_column_facts.py`.
- `residual_pii_findings` already emits a severity `"error"` finding when `fact.identity_error`
  is set and the configured strategy is not in `_NO_OP_BY_DESIGN`. Message: "column matched
  {det!r} but the source comparison raised {err} (see job log); a leak cannot be ruled out."
  `_blocked.py` maps a residual `"error"` row to `_CHECK_ERROR`, so the verdict blocks.
- The batch path (`_column_facts.column_facts`, which the production runner uses) already catches
  with the `passes_through(exc)` re-raise guard and sets `tallies[c].error = type(exc).__name__`.
  The production path is already fail-closed.
- `postscan/test_residual_pii_hint_gated.py::test_identity_error_is_still_an_error` covers the
  facts path.

The gap is the frame path only: `check_residual_pii` -> `_frame_column_facts` (line 183) ->
`_source_identity`. Only tests call it today, but it is the parity oracle for the batch path
(`postscan/test_column_facts.py:109` calls `_source_identity` directly). An oracle that hides a
raise can make a broken batch path look correct, and a future direct caller inherits the hole.

## Guarantee

- When the source comparison for a column raises, the frame path produces one residual finding
  with severity `"error"` for that column (unless its strategy is in `_NO_OP_BY_DESIGN`). It is
  the same finding the batch path produces for the same fault.
- The message names the exception class only. It holds no cell value and no exception message
  text.
- An exception for which `passes_through` returns True still propagates.
- The not-comparable cases still return None and produce no error finding.

Non-goals: `policy_validation.py::_check_one_column` has the same broad catch (baseline entry
`policy_validation.py::_check_one_column::unguarded::0`). It is out of scope; see Q6. No change to
the batch path, the verdict mapping or the finding schema.

## Design

1. Remove the `try`/`except` from `_source_identity`. Keep its explicit `return None` branches. A
   raise now leaves the function. Change the docstring: it raises when the comparison fails, and
   the caller turns that into `identity_error`. Drop "Must never raise".
2. In `_frame_column_facts`, wrap the one call:
   `except Exception as exc: if passes_through(exc): raise; identity_error = type(exc).__name__`.
   Pass `identity_error` into `ColumnFacts`. This matches the batch path in `_column_facts.py`.
3. Remove the entry
   `decoy_engine/verification/postmask/residual_pii.py::_source_identity::unguarded::0` from
   `tests/sentry/baselines/post-scan-pass-through.json`. The new handler is guarded, so the sentry
   does not list it. A shrink is allowed.
4. The parity test keeps working: on success `_source_identity` returns the same tuple.

Choke point: the post-scan pass-through sentry (`tests/sentry/post_scan/test_post_scan_choke_points.py`)
already fails any broad handler in post-scan code without the `passes_through` guard. Mutation:
delete `if passes_through(exc): raise` in `_frame_column_facts`; the sentry must go red.

Size: `residual_pii.py` is 574 lines; the change is about +6 and -3 lines. No new public names.
Files: `residual_pii.py`, `post-scan-pass-through.json`, one test file, CHANGELOG.

## Failure modes

| Failure | Today | After PM-1 |
|---|---|---|
| Comparison raises (a cell type whose `==` raises) | No finding, reads clean | One `"error"` finding, verdict blocks |
| Interrupt or fatal class raised in the comparison | Swallowed into None | Propagates |
| Table or column missing, row counts differ, nothing comparable | None | Unchanged |
| Strategy is `passthrough` and comparison raises | No finding | No error finding (operator chose no-op), unchanged rule |

## Acceptance tests (red before)

In `tests/unit/detection_verification/test_residual_pii_source_compare.py`, or a new
`test_residual_pii_identity_error.py` beside it if that file is near 600 lines.

- `test_frame_path_comparison_raise_is_error_finding` (red before): one PII column; make the
  comparison raise `TypeError` (an object cell whose `__eq__` raises, or monkeypatch
  `pd.Series.__eq__` for the call). Call `check_residual_pii`. Assert exactly one finding for the
  column, severity `"error"`, message contains `"TypeError"`, and no source or output cell value
  appears in the message.
- `test_frame_path_passes_through_exception_propagates` (red before): raise a class that
  `passes_through` returns True for; assert it propagates.
- `test_frame_and_facts_paths_agree_on_identity_error` (red before): the same faulty input through
  `check_residual_pii` and through `residual_pii_findings` over `column_facts`; assert equal
  severity and message.
- `test_not_comparable_still_quiet`: row counts differ; assert no `"error"` finding. It passes
  before and after, and pins that None keeps its meaning.
- The post-scan sentry passes with the shrunk baseline.

Test depth: T0 the touched test file and the post-scan sentry; T1 impact selection for
`verification/postmask`. No escalation trigger. Mutation run: the leak-check rule applies, so run
mutations on `_frame_column_facts` and `_source_identity`.

# Part 2. RATCHET-GROWTH

## Problem

A ratchet list may only shrink unless the owner signs off. The engine and CLI already enforce this
for baseline growth: `tests/sentry/_ratchet.py` and `scripts/dev/ratchet_check.py` compare each
registered baseline with the merge base, and fail a grown entry set or a raised `max` that lacks a
dated `approved_growth` decision. A change can still loosen a guard without growing a baseline:

1. Remove a sentry's row from `scripts/dev/sentry_registry.toml`. The head side is empty, nothing
   grows, the check passes.
2. Delete or empty the registry file. Every row reads as removed; the check passes.
3. Delete a sentry test file. `tests/sentry/test_sentry_manifest.py` only reads the head tree.
4. Misspell a field (`aproved_growth`, `maxx`). Unknown keys are ignored, so a typo turns a rule
   off. Registry rows and baseline entries have no closed schema.
5. Escape a path with `..`. `parse_registry` checks paths with `startswith`.
6. Raise a limit that is not a baseline `max`: `test_module_size.py` GOAL, MAX and MARGIN,
   `layout/test_package_fanout.py` LIMIT, `layout/test_scoped_changes.py` LIMIT; or lower a floor:
   `test_outbound_clients.py` WALK_FLOOR, `release/test_public_signatures.py` HEAD_FLOOR. Three
   numeric baselines (module-size, log-interpolation, locator-waivers) carry no `max`, so
   `max_raised` cannot see a rise. The module-size docstring says its rise rule is
   "review-enforced, not machine-enforced".
7. Delete `scripts/dev/ratchet_check.py`. `gates.sh` runs it only `if [ -f ... ]` (a skip meant
   for the baseline worktree), so the gate is green. CI runs the branch's own copy, so a branch can
   edit the checker to pass itself.

The CLI has holes 1, 2, 3, 4, 5 and 7. It already has `created_in`, the first-inventory rule,
`CEILING_FIELDS` and the moved-field check, and its `module-size.json` already carries `max`. CI
runs `ratchet_check.py --base <PR base sha>` on PRs (`ci.yml:285`) with the branch's copy.

Source: platform X0a-h H1, H2 and H4 (`decoy-platform`
`docs/plans/2026-11-05-x0a-h-ratchet-hardening.md`, PR #181). Only the plan merged. There is no
platform code to vendor, so the engine builds the mechanism and the CLI ports it. Until RG-E1
merges, the orchestrator checks ratchet growth by hand at each gate.

## Guarantee

After these slices, the gate and CI fail when the diff against the merge base:

- removes a registry row, unless the head registry has a `[retired]` entry for that id with a
  dated owner decision;
- deletes the registry file or leaves it with no rows;
- deletes a sentry test file (`tests/sentry/**/test_*.py` plus the manifest's outside list),
  unless git reports a rename or the head registry has a `[retired_files]` entry with a dated
  owner decision;
- adds an unknown field to a registry row, a `[[limit]]` row or a baseline entry;
- names a registry path that is absolute, has a backslash or has a `..` part;
- raises a registered `max` limit or lowers a registered `min` floor, unless the `[[limit]]` row
  carries a new `approved_limit` dated owner decision;
- removes a `[[limit]]` row without a `[retired]` entry;
- leaves a live limit constant different from its `[[limit]]` row;
- raises a module-size, log-interpolation or locator-waivers count without `approved_growth`;
- runs without the checker outside the baseline worktree; and the base commit's checker also runs
  against the head.

Each decision row new in the diff (`approved_growth`, `approved_limit`, `[retired]`,
`[retired_files]`) is printed on its own report line, so the gate reviewer sees every sign-off.

Named limits (known issues, not blockers):

- L-A. A decision row is plain text that anyone with write access can type. V1 relies on the
  report line and gate review. SSH-signed approvals and a `merge_check.py` run from a main
  checkout (platform H1) are V2. The V1 threat model covers accidental loosening only. See Q1.
- L-B. A sentry can be weakened in its test body without touching a baseline or limit (platform
  L3). Review catches this.
- L-C. A limit-like constant nobody registers is not seen. Finding all of them is follow-up work.
- L-D. A branch can edit `gates.sh` or a workflow. The base-checker run lowers the impact and the
  `ci-write-scopes` sentry covers workflow writes. Closing it fully needs branch protection on
  main, an owner setting.
- L-E. Platform H4 process hygiene (process-group kill, `flock -o`, bash 3.2, exact workflow `if:`)
  is out of scope except the skip-if-missing fix. See Q4.
- L-F. Runtime single-assignment of ratchet constants (platform AT-RI4) is not checked.

## Established solutions

Search run 2026-11-24: web search "code quality ratchet baseline tool only decrease betterer
phpstan baseline detekt baseline"; codebase search of engine, CLI and platform for ratchet code
(`_ratchet.py`, `ratchet_check.py`, `sentry_registry.toml`, `_baseline_sources.py`,
`layout/_ratchet_cases.py`, the platform X0a-h plan).

Found:

- PHPStan baseline (https://phpstan.org/user-guide/baseline): a snapshot of known errors that only
  shrinks; stale entries are reported so the file holds no dead rows. Pest ratchets (packagist
  `offset-smoker/pest-ratchets`) and Catraca (packagist `b7s/catraca`) apply the same rule to
  metrics. The engine `_ratchet.py` already follows this pattern.
- None of them guards against deleting the baseline, the rule or the checker. They treat config as
  reviewed code, and human sign-off comes from CODEOWNERS plus required review, a branch-protection
  setting rather than a checker feature.
- Closed schemas: JSON Schema `additionalProperties: false` is the standard way to fail unknown
  fields. The rows are flat with about six fields, so a key-set check does the same job without a
  `jsonschema` dependency.
- Path safety: `pathlib.PurePosixPath(...).parts`, rejecting `..`, absolute and backslash paths, is
  the standard library way. It replaces `startswith`.
- `tests/sentry/layout/_ratchet_cases.py` is a case table vendored byte for byte into the CLI and
  pinned by `test_vendored_files.py`. RG-E1 adds integrity cases the same way.

Design follows the shrink-only baseline pattern already in place, extended with the platform
X0a-h H2 list (AT-RI1, RI3, RI5, RI6, RI7). Custom code is needed because no tool covers deletion
of the registry, a sentry file or the checker, and the decision format is house-specific
(`owner YYYY-MM-DD reason`, regex `DECISION` in `_ratchet.py`).

## Design notes

- One place per fact. The registry TOML stays the one list of sentries, retirements and limits.
  Limit values live in the test constants; each `[[limit]]` row holds the reviewed value and a
  mirror test fails when they differ, the same rule `test_baseline_registry.py` uses for baselines.
- `_ratchet.py` is 404 lines and `test_ratchet_check.py` is 652 (over 600), so new rules go in two
  helper modules and two new test files. `check()` in `_ratchet.py` calls the helpers and stays the
  one entry point `ratchet_check.py` runs. No second checker.
- One function per integrity rule, each returning a list of finding strings, the shape
  `reason_findings` and `growth` already return.
- Principles: none beyond the existing structure. No new abstraction; new rule functions join an
  existing pipeline. Helpers are split by reason to change (integrity of the registry and files vs.
  numeric limits), not by size alone.

Choke point: `_ratchet.check()`, run by `scripts/dev/ratchet_check.py` from the `sentry` gate step
and from CI. Guard tests: `tests/sentry/test_ratchet_integrity.py` and `test_ratchet_limits.py`
run `check()` on temporary git repos with each bypass. Mutation: drop the call to
`integrity_findings(...)` in `check()`; every RG-E1 bypass test must go red. For RG-E2: drop the
call to `limit_findings(...)`.

## Placement

| New file | Directory | CODEMAP line | Beside |
|---|---|---|---|
| `_ratchet_integrity.py` | `tests/sentry/` | none: "Where Things Go" has rows for `src/` kinds only | `_ratchet.py` |
| `_ratchet_limits.py` | `tests/sentry/` | none, as above | `_ratchet.py` |
| `test_ratchet_integrity.py` | `tests/sentry/` | none, as above | `test_ratchet_check.py` |
| `test_ratchet_limits.py` | `tests/sentry/` | none, as above | `test_ratchet_check.py` |
| `test_ratchet_gate_step.py` | `tests/sentry/` | none, as above | `test_bash32_compat.py` |

Map change (RG-E1): add one "Where Things Go" row, "Ratchet checker and sentry helpers |
`tests/sentry/` | private `_<concern>.py` beside `_ratchet.py` | `tests/sentry/test_ratchet_*.py` |
`scripts/dev/sentry_registry.toml`". `tests/` is not under the package fan-out sentry (it walks
`src/` and `scripts/`), and no new file goes in `scripts/` (frozen at 26). The CLI mirrors the
layout under its own `tests/sentry/`.

## RG-E1. Registry integrity (engine, R2, one day)

Changes:

- New `tests/sentry/_ratchet_integrity.py` (about 180 lines):
  - `registry_present(base, head)`: the registry exists at head and has at least one `[[sentry]]`
    row when the base had rows.
  - `removed_rows(base_rows, head_rows, retired)`: an id at base and gone at head needs a
    `[retired]` entry `id = "owner YYYY-MM-DD reason"` matching `DECISION` and passing
    `reason_findings`. A retargeted row (same id, new `baseline` path) still needs `moved_from`,
    which exists today.
  - `removed_sentry_files(base_sha)`: sentry files at base (`git ls-tree -r --name-only`, filtered
    to `tests/sentry/**/test_*.py` plus the outside list exported from `test_sentry_manifest.py`)
    minus those at head. A path `git diff -M --name-status base..HEAD` reports as renamed passes.
    Others need a `[retired_files]` entry with a dated decision.
  - `closed_schema(...)`: allowed keys for `[[sentry]]` rows, `[[limit]]` rows and baseline
    entries. The builder derives each baseline type's key set from the live files. An unknown key
    fails with its file and id.
  - `safe_path(p)`: `PurePosixPath`; fails absolute, backslash or any `..` part. `parse_registry`
    uses it in place of `startswith`.
  - `new_decisions(base, head)`: every decision row at head and not at base, for the report.
- `_ratchet.py`: `check()` calls `integrity_findings(...)` and prints the decision lines. About +15
  lines.
- `scripts/dev/sentry_registry.toml`: add empty `[retired]` and `[retired_files]` tables with a
  one-line comment on the decision format. Fix the stale comment at lines 6-7: the F29 reason
  baseline is registered (platform AT-E8).
- `created_in` (platform AT-RI6, already in the CLI): optional for existing rows, required for a
  row new in the diff. No back-fill. See Q7.
- Integrity case table: add the bypass cases to a vendored table beside
  `layout/_ratchet_cases.py` (or extend that file) so RG-C1 parametrizes the same cases.
- CODEMAP row (see Placement). CHANGELOG entry.

Failure modes:

| Bypass | Expected |
|---|---|
| Registry row deleted, no `[retired]` entry | Fail, names the id |
| `[retired]` entry with a placeholder reason | Fail, `reason_findings` rules |
| Registry file deleted or emptied | Fail |
| Sentry test file deleted | Fail, names the path |
| Sentry test file renamed with `git mv` | Pass |
| `aproved_growth` typo on a row | Fail, unknown key |
| Baseline path `tests/sentry/../../src/x.json` | Fail |
| Base has no `[retired]` table (first run) | Pass; the tables are optional at base |

Acceptance tests, all red before, in `tests/sentry/test_ratchet_integrity.py`. Reuse the
temporary-git-repo helpers from `test_ratchet_check.py` by import; do not copy them.

- `test_removed_registry_row_without_retirement_fails` (AT-RI1)
- `test_removed_registry_row_with_dated_retirement_passes`
- `test_retirement_with_placeholder_reason_fails`
- `test_deleted_registry_file_fails`
- `test_emptied_registry_file_fails`
- `test_deleted_sentry_file_fails` (AT-RI3)
- `test_renamed_sentry_file_passes`
- `test_deleted_outside_sentry_file_fails`
- `test_unknown_registry_key_fails`
- `test_unknown_baseline_entry_key_fails`
- `test_dotdot_absolute_and_backslash_paths_fail` (AT-RI7)
- `test_new_row_without_created_in_fails` (AT-RI6)
- `test_new_decision_rows_are_reported`
- `test_live_registry_passes_against_origin_main` (passes before and after)

Size: about +180 helper, +15 `_ratchet.py`, +10 TOML, +260 tests, +1 CODEMAP row. No public names.

Test depth: T0 the ratchet test files; T1 impact selection for `tests/sentry`. Escalation trigger:
test tooling (the ratchet is gate tooling), so the merge runs one full suite diffed against the
stored main baseline.

## RG-E2. Limits carry a max (engine, R2, one day)

Changes:

- `tests/sentry/_baseline_sources.py` (562 lines, about +12): add `maxes=` to `module-size`
  (`in_code("test_module_size.py", "ALLOWLIST").maxes`; values are ints), `log-interpolation` and
  `locator-waivers` (`count_at=0`). Regenerate those three baselines so each entry carries `max`.
  Then `max_raised` catches a ceiling rise. Update the module-size docstring sentence that says the
  rule is review-enforced.
- `tests/sentry/test_baseline_registry.py`: replace the hand list in
  `test_every_numeric_source_declares_its_max` with a walk over every `InCode` source: one whose
  values are ints, or tuples with an int at `count_at`, must declare `maxes`.
- New `tests/sentry/_ratchet_limits.py` (about 120 lines) and a `[[limit]]` table in the registry
  with fields `id`, `file`, `constant`, `value`, `direction` (`"max"` or `"min"`), `created_in`,
  optional `approved_limit = "owner YYYY-MM-DD reason"`. Initial rows: `module-size-goal`
  (GOAL 600, max), `module-size-max` (MAX 700, max), `module-size-margin` (MARGIN 20, max),
  `package-fanout-limit` (LIMIT 25, max), `scoped-changes-limit` (LIMIT 1, max),
  `outbound-walk-floor` (WALK_FLOOR 146, min), `public-signatures-floor` (HEAD_FLOOR 350, min).
  The builder checks `test_date_shift_window_reader.py` MAX_HITS; if no baseline mirrors it, add a
  max row.
- `limit_findings(base, head)`, called from `check()`:
  - a `value` moved in the loosening direction (up for max, down for min) needs an
    `approved_limit` decision new in this diff;
  - a removed `[[limit]]` row needs a `[retired]` entry (RG-E1);
  - tightening always passes.
- Mirror test in `tests/sentry/test_ratchet_limits.py`: read each live constant with `ast` (a
  module-level `NAME = <int>`) and assert it equals the row's `value`.

Failure modes:

| Change | Expected |
|---|---|
| A module-size ALLOWLIST ceiling raised 632 to 650 | Fail via `max_raised` unless `approved_growth` |
| GOAL raised 600 to 650 in the test and the row | Fail unless `approved_limit` |
| GOAL raised in the test only | Fail, mirror test |
| WALK_FLOOR lowered 146 to 140 | Fail unless `approved_limit` |
| WALK_FLOOR raised 146 to 150 | Pass |
| `[[limit]]` row deleted | Fail unless `[retired]` |
| Constant renamed so the AST lookup misses it | Fail, mirror test names the row |

Acceptance tests, all red before:

- `test_module_size_ceiling_raise_needs_approval`
- `test_log_interpolation_count_raise_needs_approval`
- `test_locator_waiver_count_raise_needs_approval`
- `test_every_numeric_in_code_source_declares_max`
- `test_limit_raise_without_approval_fails` (AT-RI5)
- `test_limit_raise_with_new_approval_passes`
- `test_floor_lowered_without_approval_fails`
- `test_floor_raised_passes`
- `test_removed_limit_row_needs_retirement`
- `test_live_constant_matches_limit_row`

Size: about +12 `_baseline_sources.py` (stays under 600), +120 helper, +45 TOML, three regenerated
baselines, +200 tests, +5 `_ratchet.py`. No ceiling is raised.

Test depth: T0 the ratchet, baseline-registry and module-size tests; T1 impact selection. Same
test-tooling trigger as RG-E1; it can ride the same merge train.

## RG-E3. Gate runs the base checker (engine, R2 for CI, half a day)

Changes:

- `scripts/dev/gates.sh` sentry step: keep the skip-if-missing only for the baseline-label tree
  (`gates.sh:491`; use the existing `label` variable). On any other tree, a missing `scripts/dev/ratchet_check.py`
  prints "ratchet checker missing" and fails.
- After the branch checker passes, run the merge base's copy against the head: write
  `scripts/dev/ratchet_check.py`, `tests/sentry/_ratchet.py` and the helper modules from
  `git show <base>:<path>` to a temp directory and run them with the head tree as the repo. Add a
  `--repo` argument to `ratchet_check.py` if it has none. If the base has no checker, skip with one
  printed line.
- `.github/workflows/gate-selfhosted.yml` already runs the `sentry` step, so no workflow edit is
  planned. If one turns out to be needed, the `ci-write-scopes` sentry applies.

Failure modes:

| Change | Expected |
|---|---|
| Branch deletes `ratchet_check.py` | Fail |
| Branch edits `_ratchet.py` so `check()` returns nothing, and grows a baseline | Base copy fails the growth |
| This slice's head run by the older base checker | Pass (the older checker ignores the new tables) |
| Baseline worktree with no checker | Skip, as today |

Acceptance tests, all red before, in `tests/sentry/test_ratchet_gate_step.py`. They run the sentry
step command on a temporary repo, following the harness pattern in `test_bash32_compat.py`:

- `test_missing_checker_fails_outside_baseline_tree`
- `test_missing_checker_skips_in_baseline_tree`
- `test_base_checker_catches_growth_hidden_by_branch_checker_edit`
- `test_base_checker_absent_skips_with_message`

Size: about +20 `gates.sh`, +10 `ratchet_check.py`, +120 tests.

Test depth: T0 the new test file and `test_bash32_compat.py`; T1 impact selection; the gate runs
`gates.sh --keep-going --steps env,ruff,format,mypy,sentry` on the exact head. Test-tooling
trigger: full suite once at merge.

## RG-C1. CLI port (CLI, R2 for CI, one day)

Start after RG-E1, RG-E2 and RG-E3 merge, so the CLI ports reviewed code.

- `tests/sentry/_ratchet_integrity.py` and `_ratchet_limits.py`: port from the engine. Keep the
  CLI's decision grammar (`src/decoy/distribution/release_identity.py:is_dated_owner_decision`),
  its `created_in` rule and `CEILING_FIELDS`. Do not add a second grammar. Vendor the shared case
  table byte for byte, pinned by the CLI's vendored-files test.
- `tests/sentry/_ratchet.py` (342 lines): call the helpers from `check()`; replace `startswith`.
- `scripts/dev/sentry_registry.toml` (201 lines): `[retired]`, `[retired_files]` and `[[limit]]`.
  Initial limit rows: `layout/test_module_size.py` LIMIT 800 (max), `layout/test_package_fanout.py`
  LIMIT 25 (max), `release/test_retired_name_residual.py` MANIFEST_FLOOR 1400 (min),
  `release/test_tag_census.py` FLOOR 7 (min). The builder confirms from each test body that the
  constant is a cap or a floor before adding it.
- The builder lists CLI numeric baselines without `max` (`module-size.json` already has it) and
  adds `maxes` where missing.
- `scripts/dev/gates.sh:269`: the same skip-if-missing fix and base-checker run as RG-E3.
- `.github/workflows/ci.yml:285` ("Baselines only shrink"): add a step that runs the base commit's
  checker (`git show ${{ github.event.pull_request.base.sha }}:<path>` into a temp dir) against the
  head, with step-level `if: github.event_name == 'pull_request'` like the step above it. The lane
  sentry refuses a job-level `if`.
- CHANGELOG entry.

Acceptance tests: the RG-E1, RG-E2 and RG-E3 test names in the CLI `tests/sentry/`, all red
before, plus `test_ci_runs_base_checker_on_pull_requests` (reads `ci.yml`; asserts the step and
its step-level `if`).

Size: about +300 helpers, +60 TOML, +40 `_ratchet.py`, +20 `gates.sh`, +8 `ci.yml`, +450 tests.
If the builder sees this going well past a day, split at the first checkpoint into RG-C1a
(integrity and gate) and RG-C1b (limits).

Test depth: T0 the CLI ratchet tests; T1 impact selection. Triggers: CI config and test tooling, so
one full CLI suite at merge, diffed against the stored main baseline. Use `gates.sh --full`.

# Defect classes

From `catalogs/recurring-defects.md` and the plan contract's class list.

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | PM-1: `identity_error` holds `type(exc).__name__` only, the same field the batch path fills. RG: findings name ids, paths, keys and numbers from the repo's own registry, never file content | PM-1 AT asserts no cell value in the message | Put `str(exc)` in `identity_error`: the message check fails |
| 2 | Cleanup on an exit path | RG-E3 writes the base checker to a `mktemp -d` directory removed by a `trap`; RG tests use pytest `tmp_path` repos; nothing is written to the shared `.git` | `test_base_checker_catches_growth_hidden_by_branch_checker_edit` checks the temp dir is gone after a failing run | Drop the `trap`: the leftover-dir check fails |
| 3 | State and concurrency | The ratchet helpers keep no module state; each call reads base with `git show` and head from the tree. PM-1 adds no state | Tests run under xdist with separate `tmp_path` repos | N/A: no shared state to mutate |
| 4 | Route parity and silent fallback | PM-1: frame and batch paths fill `identity_error` the same way. RG: gates.sh and CI run the same `check()`; a missing checker fails outside the baseline tree instead of skipping | `test_frame_and_facts_paths_agree_on_identity_error`; `test_missing_checker_fails_outside_baseline_tree` | Restore `return None` in `_source_identity`; restore the unconditional `-f` skip: each test fails |
| 5 | Referential integrity | RG: a registry row's `baseline` path must exist and be safe; a `[[limit]]` row's file and constant must resolve (mirror test). PM-1: N/A, no FK handling | `test_dotdot_absolute_and_backslash_paths_fail`; `test_live_constant_matches_limit_row` | Revert `safe_path` to `startswith`: the path test fails |
| 6 | Untrusted producer | N/A for V1: inputs are the repo's own registry, baselines and git history (V1 threat model, accidental only). Decision rows are parsed with the anchored `DECISION` regex using `fullmatch` | A decision row with a trailing newline is refused | Swap `fullmatch` for `match` with `$`: that case passes and the test fails |
| 7 | Check then use on a path | RG reads the base once by sha (`--base`) and passes the same sha to every `git show` and `git ls-tree` call; RG-E3 resolves the merge base once | Code review on `check()` | Resolve the merge base twice: review finding |
| 8 | Weak tests and overclaimed evidence | Every named AT is run red on the base first; `test_live_registry_passes_against_origin_main` keeps the real repo in the loop; the numeric-source walk replaces a hand list so a new source cannot be skipped | Builder report lists each red-before result and each mutation | Return an empty list from `integrity_findings`: every RG-E1 bypass test fails |
| 9 | Refactor drift | PM-1 moves the catch from `_source_identity` to its one caller; the parity test keeps calling `_source_identity` unchanged | `postscan/test_column_facts.py` passes unchanged | N/A |
| 10 | Frozen contract drift | N/A: no public name, finding schema or reason code changes | Existing census sentries stay green | N/A |

# Enumerations

### Exit paths

- `_source_identity` (`residual_pii.py:240-274`): returns a tuple (compared); returns None when
  the table is missing, the column is missing, row counts differ or zero rows are comparable; or
  raises (comparison failed). PM-1 removes the last path, the `except Exception: return None`.
- `_frame_column_facts` call site (`residual_pii.py:183`): success, not comparable, a raise that
  `passes_through` keeps (propagates), any other raise (sets `identity_error`).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:305`): returns findings and report lines;
  `ratchet_check.py` exits 1 on any finding. RG adds no other exit.
- Engine sentry step (`scripts/dev/gates.sh:491`): checker present (run, fail on exit 1); checker
  missing in the baseline tree (skip); checker missing elsewhere (RG-E3: fail).

### Routes

| Route into the check | Where | Slice |
|---|---|---|
| Frame path `check_residual_pii` | `residual_pii.py:183` | PM-1 |
| Batch path `column_facts` (already fail-closed) | `_column_facts.py:380` | none |
| Engine local gate and `gate-selfhosted.yml` branch pushes | `scripts/dev/gates.sh:491` | RG-E1 to RG-E3 |
| CLI local gate | CLI `scripts/dev/gates.sh:269` | RG-C1 |
| CLI PR CI "Baselines only shrink" | CLI `.github/workflows/ci.yml:285` | RG-C1 |

### FK shapes

N/A. Neither row reads or writes keyed data. PM-1 compares one column by position and touches no
FK logic.

### Fields

| Field | Where | Change |
|---|---|---|
| `ColumnFacts.identity_error` | `_column_facts.py:179` | now set on the frame path too |
| `[[sentry]]` row keys | `scripts/dev/sentry_registry.toml` | closed set; `created_in` required on new rows |
| `[retired]`, `[retired_files]` | registry | new tables, `key = "owner YYYY-MM-DD reason"` |
| `[[limit]]` `id`, `file`, `constant`, `value`, `direction`, `created_in`, `approved_limit` | registry | new table (RG-E2) |
| Baseline entry keys (`reason`, `max`, `count`, `sites`, `created_in`, `moved_from`, per-type extras) | `tests/sentry/baselines/*.json` | closed set |

### Output surfaces

- Residual finding message (`residual_pii.py:552-558`): exception class name only.
- Ratchet findings and decision report lines on the stdout of `ratchet_check.py`: ids, paths, keys,
  numbers and the decision text the owner wrote. No file content.
- The sentry step's "ratchet checker missing" line.

### Loosening forms the checker must see

| Form | Slice | Test |
|---|---|---|
| Registry row removed | RG-E1 | `test_removed_registry_row_without_retirement_fails` |
| Registry file deleted or emptied | RG-E1 | `test_deleted_registry_file_fails`, `test_emptied_registry_file_fails` |
| Sentry file deleted (inside `tests/sentry/` and the outside list) | RG-E1 | `test_deleted_sentry_file_fails`, `test_deleted_outside_sentry_file_fails` |
| Unknown key (typo) | RG-E1 | `test_unknown_registry_key_fails`, `test_unknown_baseline_entry_key_fails` |
| Unsafe path (`_ratchet.py:69` uses `startswith` today) | RG-E1 | `test_dotdot_absolute_and_backslash_paths_fail` |
| Baseline count raised with no `max` | RG-E2 | the three `*_raise_needs_approval` tests |
| Scalar cap raised, floor lowered | RG-E2 | `test_limit_raise_without_approval_fails`, `test_floor_lowered_without_approval_fails` |
| Checker deleted or edited | RG-E3 | `test_missing_checker_fails_outside_baseline_tree`, `test_base_checker_catches_growth_hidden_by_branch_checker_edit` |

# Reuse inventory

- `ColumnFacts.identity_error` and its `"error"` finding in `residual_pii_findings`: reused, not
  rebuilt.
- `passes_through` from `decoy_engine.profiling.scan_set`: reused for the re-raise guard.
- `_ratchet.py`: `DECISION`, `reason_findings`, `parse_registry`, `max_raised`, `moved_from` and the
  `check()` entry point: reused; new rules plug into `check()`.
- `_baseline_sources.InCode(...).maxes`: reused for the three sources that lack `max`.
- `test_ratchet_check.py` temporary-repo helpers: imported by the new test files.
- `layout/_ratchet_cases.py` and `test_vendored_files.py`: the pattern for sharing case tables with
  the CLI.
- CLI `is_dated_owner_decision`, `created_in` rule and `CEILING_FIELDS`: kept as they are.

# Frozen contracts

None touched. PM-1 changes a private function and fills an existing field; the residual finding
schema, reason codes and `_blocked.py` verdict mapping do not change. The ratchet work is test and
gate tooling only.

# Pre-mortem

- A new required key or table breaks every open branch at once. Closed: the new tables are
  optional at base, `created_in` is required only for rows new in the diff, and RG-E3 checks that
  the older base checker passes on this slice's head.
- Builders learn to paste decision rows to get green. Partly closed: every new row is printed for
  the gate reviewer (L-A). A signed approval is V2.
- The sentry-file walk flags normal moves. Closed by `git diff -M` rename detection; a split of one
  file into two shows as delete plus add, and the builder records a `[retired_files]` row for it.
- The base-checker run fails because the base tree imports something the temp dir lacks. Closed by
  copying the full set of checker files and by the "base has no checker" skip; the builder runs
  it once on a real main sha before review.
- PM-1 turns a quiet test into a red one because some existing test input made the comparison
  raise. That is the bug showing. The builder lists any such test and fixes the input, never the
  assertion.

# Builder brief items (every slice)

- Commit messages: Conventional Commits subject, 72 characters or fewer, no body unless it says
  why, final line `cam`. No trailers, file lists, test counts or headings.
  Rule: `/home/cam/dev-rules/workspace-and-vcs.md`, "Commit messages".
- Test depth T0 to T4 per `/home/cam/dev-rules/testing.md`, "Test depth". Use `~/bin/pytest-one`.
  Put the "Test scope" block in the builder report.
- Never raise a module-size ceiling. Every touched file stays at or under 600 lines, or does not
  grow if it is already over (`test_ratchet_check.py` takes no new tests).
- Red before: run each named acceptance test on the base first and record that it fails.
- No cell values, query text or exception message text in any finding or log line.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG updated before merge.

# Owner questions

- Q1. What counts as an owner sign-off in V1?
  Options: (a) a dated text decision row plus a printed report line the gate reviewer checks;
  (b) decision rows must land on main before the loosening PR (two PRs);
  (c) SSH-signed approvals checked from a main checkout (platform H1).
  Recommended: (a). It fits the V1 threat model (accidental loosening). (c) moves to V2.
- Q2. Does removing a sentry, or deleting a sentry file, need an owner row, or is gate review
  enough?
  Recommended: an owner row (`[retired]` or `[retired_files]`). It costs one line and puts the
  removal in the report.
- Q3. Should floors (engine WALK_FLOOR and HEAD_FLOOR, CLI MANIFEST_FLOOR and FLOOR) be covered with
  direction `min`?
  Recommended: yes. Lowering a floor loosens a guard the same way raising a cap does.
- Q4. Should the platform H4 process hygiene (process-group kill, `flock -o`, exact workflow `if:`,
  bash 3.2) join this row?
  Recommended: no. Only the skip-if-missing fix is in scope (RG-E3, RG-C1). Log the rest as a 1.x
  row.
- Q5. Keep the frame-path `check_residual_pii`, or retire it since only tests call it?
  Recommended: keep it and fix it in PM-1. It is the batch path's parity oracle, and retiring it is
  a bigger change than the fix.
- Q6. Give `policy_validation.py::_check_one_column` the same fail-closed fix?
  Recommended: yes, as a separate small R1 row. It has the same unguarded broad catch, listed in
  `post-scan-pass-through.json`.
- Q7. Should `created_in` be required for new engine registry rows (RG-E1)?
  Recommended: yes for new rows only, no back-fill. The CLI already requires it.
