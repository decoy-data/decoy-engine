# RG-C1a: CLI registry integrity and base run

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
reuse-first, catalogs/recurring-defects; owner notes on the V1 threat model and
plan-defines-acceptance-tests.

Row: RATCHET-GROWTH. Parent plan: engine `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`
(section "RG-C1a"), owner decisions Q1 to Q7 of 2026-11-24. The work lands in the CLI repo
(`decoy-data/decoy`); this plan lives in the engine repo beside its parent.

Risk: R2 (CI config and test tooling). Size: one day. Depends on RG-E1 (merged), RG-E2 (PR #801)
and RG-E3 (`2026-11-25-ratchet-growth-rg-e3.md`), all merged on engine main first, so the CLI
ports reviewed code. Anchor: CLI main `d6b9e4c7`. The builder re-anchors every line number on
CLI main and on the engine merge commit of RG-E3 before the first commit.

## Problem

The CLI checker (`tests/sentry/_ratchet.py`, 342 lines) is the pre-RG-E1 design:

- it reads HEAD with `Path.read_text` and the base with `git show`, so a missing base file and a
  failed read look the same (`tests/sentry/_ratchet.py:156-163`);
- it has no `[retired]`, `[retired_files]` or `[checker_change]` tables, so deleting a registry
  row together with its baseline, or deleting a sentry file, passes;
- registry rows have no closed key set, and `kind` and `consumer` are checked only by a test, not
  by the checker (`tests/sentry/test_baseline_registry.py:100,304-305`);
- the gate skips the checker when the file is missing (`scripts/dev/gates.sh:269`); both the
  gate and PR CI (`.github/workflows/ci.yml:283-285`, which calls Python with no skip) run only
  the HEAD copy.

## Guarantee

After this slice the CLI checker gives the same answers as the engine checker after RG-E3 for
every RG-E1 and RG-E3 case, with the CLI's own row schema (`kind`, `consumer`) and decision
grammar. The CLI gate and the PR CI job both run the base checker, and a missing checker fails
outside the baseline worktree.

Non-goals:

- No numeric bounds, floors or `sentry-limits` source (RG-C1b).
- No change to the CLI decision grammar (`src/decoy/distribution/release_identity.py:38-41,58-69`:
  optional colon, ten-character reasons) or to the rule that every baseline names `created_in`
  (`tests/sentry/_ratchet.py:274-275`). Engine cases that reject reasons the CLI accepts
  (engine `test_integrity.py:646-655`) are listed as CLI-specific pins with the CLI result.
- No change to `--slice` (`scripts/dev/ratchet_check.py:37`).
- No signed approvals (V2).

## What exists (reuse, do not rebuild)

- Engine, after RG-E3: `tests/sentry/ratchet/_integrity.py` (BaseTree, Side, `kind_of`,
  `open_input`, `safe_path`, `closed_keys`, `decisions`, `fresh`, `new_decisions`,
  `sentry_file_findings`, the manifest walk at `:437-453`), `tests/sentry/ratchet/_base_run.py`
  (pure rules, no I/O), the launcher in `scripts/dev/ratchet_check.py` with
  `BASE_ARCHIVE_PATHS`, and the RG-E1, RG-E3 tests, including `test_baseline_types.py:32-68` and
  `test_reader_guard.py:99-103` (the type and reader-guard suites come from RG-E1).
- CLI: `tests/sentry/_ratchet.py:52-61` loads the decision check by path; `:130-139` the lenient
  baseline parser (coerces ids, accepts missing `entries`); `:175` `max_raised`; `:202`
  `move_findings`; `:248` `check(root, base, slice_name)`; `:265-269` opens a path with no
  type check. `tests/sentry/_baseline_sources.py:31` `KINDS`.
  `tests/sentry/test_sentry_manifest.py:35-40` the manifest glob.
- CLI vendoring: `ci/vendored.toml` (`[[vendored]]` byte-identical and `[[mirror]]` rows);
  `tests/sentry/layout/test_vendored_files.py:26,36-45` `PINS` and its digest check;
  `tests/sentry/test_ci_lock_installs.py:475-480,501-508,514-519` (ledger digest check, the exact
  vendored-file set and the five-mirror count); `tests/sentry/layout/_ratchet_cases.py:10-17`
  (only `MAX_VALUE_CASES`), exported from `tests/sentry/layout/__init__.py:19-24`.
- CLI lint debt: `scripts/dev/lintdebt.py:34-48,98-107` rejects each new file and rule pair.
  The engine `test_reader_guard.py:63` scanner has complexity 13 (C901 limit 10), so a verbatim
  port is rejected. CLI `load_allowlist` (`tests/sentry/_ratchet.py:95-100`) opens files itself.
- CLI `max_raised` (`:175`) is the bound comparison; the engine inventory split calls
  `r.bound_loosened` (`_integrity.py:389-396`), which the CLI does not have.
- CLI vendoring census: `test_ci_lock_installs.py:507` counts rows (6 today);
  `test_vendored_files.py:36-45,48-67` keys pins on bare names.
- Pre-`kind` CLI base `91380fdf`: populated registry rows with no `kind` (registry `:5-15`).

## Design

1. Upstream first (engine, before this PR). Running the CLI lint-debt rules over #801
   `_integrity.py` gives `BLE001` at `:168,187,221` and `C901` at `:362`. The engine fixes these
   in RG-E3 (narrow the three `except` clauses to the named error types, split the function at
   `:362`) so the CLI copy is clean. RG-E3 also ships `BASE_ARCHIVE_PATHS` and drops paths the
   base listing lacks. This CLI PR starts only when both are on engine main.
2. Helpers, in a new CLI group `tests/sentry/ratchet/`:
   - `_base_run.py`: vendored byte for byte, pinned in `ci/vendored.toml`. The pin check uses
     the existing digest checker in `test_vendored_files.py` (add a `PINS` row), not a new one.
   - `_integrity.py`: a `[[mirror]]`. Header differences: the decision check is passed in (the
     CLI loads `is_dated_owner_decision`), the row schema is passed in, and the bound comparison
     is passed in: the CLI binds the inventory-split transfer check to `max_raised` and passes
     no per-site handler (the CLI has no `sites` bounds). Control:
     `test_ratchet_check.py:148-155` keeps passing. `MANIFEST` already matches
     (`_integrity.py:28`). No other difference.
   - `test_reader_guard.py`: ported with its scanner split into two functions so each is under
     C901 10; the ported file passes `lintdebt.py` with no new file and rule pair. CLI
     `load_allowlist` reads through the shared `open_input` reader, so the guard has no CLI
     exception.
   - `layout/_ratchet_cases.py`: re-vendored from the engine so it carries
     `REGISTRY_PATH_CASES`; update its digest and source commit; export the new table from
     `layout/__init__.py`.
   - `test_ci_lock_installs.py:501-508`: add the new vendored path; the row count at `:507`
     becomes 7 and the mirror count goes from 5 to 6.
   - `test_vendored_files.py:36-45,48-67`: the pin checker keys on repo-relative paths, checks
     that the ledger source commit equals the pin's, and its fixture creates parent directories.
   - Exports and fixtures: `tests/sentry/ratchet/__init__.py:3-5` and `ratchet/conftest.py:3-5`
     are added from the engine; the `test_gate_pins` import (line 630) and the glob guard
     (`607-613`, against `_ci_lanes.py:105-110`) are adapted to the new group.
3. `tests/sentry/_ratchet.py` (+30, to about 372): `_helper(name)` loads by path; `check()`
   builds `BaseTree` once, reads both sides through `Side` (regular-file check before open, so
   a FIFO is a finding, not a hang), and calls `closed_keys` with the CLI row schema: `id`,
   `baseline`, `kind` required; `kind` in `KINDS`; `consumer` required on `json` and refused
   otherwise; `approved_growth` optional. The strict read from the engine replaces the lenient
   parser on both sides: ids must be strings, `entries` must be present, `count` and `sites` are
   non-bool ints, and the `moved_from` map is kept. `safe_path` replaces `startswith`.
   Older base schema: a base registry whose rows have no `kind` key at all (CLI `91380fdf`) is
   read with the pre-`kind` schema; that is recognized only when no row on that side has `kind`.
   HEAD is always validated strictly.
   `max_raised`, `move_findings`, `created_in` and `--slice` stay. The new signature takes
   `slice_name` and `waiver_input` as keywords only, so a positional call cannot swap them.
4. One owner per check:
   - row schema: `closed_keys` in the checker; `test_baseline_registry.py:100,302-305` calls the
     same validator instead of its own kind and consumer checks. The consumer-to-loader check at
     `:309-314` stays, since it checks a different fact.
   - sentry file membership: `test_sentry_manifest.py:35-40` uses the `_integrity` manifest
     predicate.
   - vendored digests: the existing checkers only.
5. `scripts/dev/sentry_registry.toml`: empty `[retired]`, `[retired_files]` and `[checker_change]`
   tables with a header comment (+15).
6. `scripts/dev/ratchet_check.py` (+50): the RG-E3 launcher, ported as a mirror with
   `BASE_ARCHIVE_PATHS = ("scripts/dev", "tests/sentry", "src/decoy/distribution/release_identity.py")`.
   Paths absent from the base listing are dropped, so a base that predates
   `release_identity.py` (CLI `7860d26b`) still archives. The child-only `--schema-waiver-env`
   parser is added, and the head check passes `slice_name=` and `waiver_input=` by keyword.
   `--slice NAME` is forwarded to both the head check and the child.
7. `scripts/dev/gates.sh:269` and `.github/workflows/ci.yml:285`: both run
   `ratchet_check.py --with-base --base <sha>`. The gate passes `label` with the RG-E3 four
   cases, the RG-E3 failure marker, and replays decision and waiver lines from the step log to
   gate stderr on a pass (today `gates.sh:291-296` prints the tail only on failure). `ci.yml`
   keeps its step-level `if: github.event_name == 'pull_request'`.
8. `CODEMAP.md` row "Sentry test" (`CODEMAP.md:73`): add the `tests/sentry/ratchet/` group.
   CHANGELOG entry.

Choke point: `_ratchet.check()` is the one reader of the registry and baselines on both sides;
`closed_keys` is the one row-schema check, also used by the registry test. Guard:
`test_cli_integrity_rejects_invalid_kind_or_consumer` runs the checker. Mutation: drop the
`kind` rule from the schema; the guard and the registry test both fail.

Design notes: no new abstraction. The established pattern is the repo's own vendoring ledger.
Each fact has one home: the row schema in CLI `_ratchet.py`, the kinds in `KINDS`, the decision
grammar in `release_identity.py`, the archive list in `ratchet_check.BASE_ARCHIVE_PATHS`.

### Placement

| New or changed | Path | CODEMAP rule (`CODEMAP.md:73`) | Sits beside |
|---|---|---|---|
| Ratchet helpers | `tests/sentry/ratchet/_integrity.py`, `_base_run.py` | `tests/sentry/<group>/`, helper `_<name>.py`; pinned in `ci/vendored.toml` | `tests/sentry/layout/_ratchet_cases.py` |
| Tests | `tests/sentry/ratchet/test_integrity.py`, `test_malformed_registry.py`, `test_base_run.py`, `test_baseline_types.py`, `test_reader_guard.py` | `tests/sentry/<group>/test_<rule>.py`, each under 600 lines (parent lines 985-986) | |
| Checker, gate, CI | `tests/sentry/_ratchet.py`, `scripts/dev/ratchet_check.py`, `scripts/dev/gates.sh`, `.github/workflows/ci.yml` | existing files (`CODEMAP.md:76`) | |

## Behavior and failure modes

| Change on a CLI branch | Expected | Test |
|---|---|---|
| Registry row and its baseline deleted, no `[retired]` row | Fail | port |
| A sentry file deleted, no `[retired_files]` row | Fail | port |
| Registry file deleted or emptied | Fail | port |
| Unknown row key | Fail | port |
| Missing or unknown `kind`, JSON row with no `consumer`, `consumer` on a recomputed row | Fail, each named | 1 |
| Baseline path with `..` or a backslash | Fail | port |
| Base has a directory at `scripts/dev/ratchet_check.py` | Fail | 2 |
| Checker deleted on a branch | Fail, "ratchet checker missing" | port |
| Head checker edited to hide growth | Base copy fails | port |
| Head edit to `release_identity.py` | Base decision check unchanged | 3 |
| Base `7860d26b`, before `release_identity.py` | Archive succeeds, plain child, pass | 8 |
| Approved schema change with a `[checker_change]` row | Pass; waiver reaches the child as a keyword | 9 |
| Wrong first-inventory `--slice` with the head check disabled | Base copy fails with the slice finding; `--slice` forwarded to the child | 10 |
| Base `91380fdf`, pre-`kind` populated rows | Base read with the old schema; HEAD strict | 12 |
| Inventory split that raises a CLI `max` | Fail through `max_raised` | 13 |
| Baseline id not a string, `entries` missing (`test_malformed_registry.py:242`), bool in `count` or `sites` | Fail, head and base | port of `test_baseline_types.py` |
| Registry path is a FIFO | Fail within the test timeout | port, bounded |
| New baseline with no `created_in` | Fail, as today | 7 (pin) |
| PR CI runs the base checker | `--with-base`, step-level `if:` kept | 4 |
| Passing gate with a new decision row | Decision line on gate stderr | 11 |
| Live CLI registry | Pass | 6 (pin) |

## Acceptance tests (red first)

Tags: `red-before` fails on CLI main on its assertion; `pin` passes on main. The red run uses
the RG-E3 plain-command fallback, since main's parser refuses `--with-base`; an argparse error
is not red evidence. The FIFO probe opens with a 5-second test timeout.

Ported from the engine (RG-E1, RG-E2's type and reader-guard suites, RG-E3), on CLI temp repos
with valid CLI rows (`kind = "from_scan"`, or `kind = "json"` plus a `consumer`). Each ported test
is listed with its class on CLI main: red-before, pin, or CLI-specific pin (an engine case whose
CLI answer differs by the CLI decision grammar; the CLI answer is asserted). The case table is
the re-vendored `layout/_ratchet_cases.py`.

CLI-only:

1. `test_cli_integrity_rejects_invalid_kind_or_consumer` (red-before).
2. `test_checker_path_is_a_directory_in_base_fails` (red-before).
3. `test_base_run_loads_release_identity` (red-before): a head edit to `release_identity.py`
   that accepts any reason cannot change the base decision check. Asserts the base decision
   diagnostic text. The passing control uses a valid decision with the file unchanged.
4. `test_ci_runs_base_checker_on_pull_requests` (red-before): parse `ci.yml`.
5. `test_vendored_ratchet_helpers_match_their_pins` (red-before): asserts the file exists before
   hashing it, then the digest equals the pin and the ledger row.
6. `test_live_cli_registry_kinds_and_consumers_pass` (pin).
7. `test_new_baseline_without_created_in_fails` (pin, `_ratchet.py:274-275`).
8. `test_base_before_release_identity_runs` (red-before): base `7860d26b`; asserts the child ran
   (invocation record) and its exit.
9. `test_schema_waiver_reaches_the_child_by_keyword` (red-before): asserts the child ran and
   printed its exact waiver line.
10. `test_wrong_slice_caught_by_base_with_head_disabled` (red-before): asserts the slice
    diagnostic text from the child.
11. `test_decision_lines_shown_on_a_passing_cli_gate` (red-before, through the gate harness).
12. `test_pre_kind_base_registry_reads` (red-before): base `91380fdf`; HEAD with a missing
    `kind` still fails.
13. `test_shared_bound_uses_max_raised` (red-before): an inventory split that raises a CLI
    `max` is caught through `max_raised`.

Adapted existing tests: `test_integrity.py:376-379` and `test_baseline_types.py:35,51-57` assert
the CLI refusal text from `test_ratchet_check.py:217-220`. The engine `test_integrity.py` (686
lines) is split in the port into `test_integrity.py` and `test_integrity_base.py`, each under
600 lines.

Fixture updates (not new tests): the row writers at `tests/sentry/test_ratchet_check.py:46-47,180,483,561`
emit a valid kind; `tests/sentry/cli_text/test_error_emitter_ratchet.py:22` gets
`kind = "from_scan"`; `tests/sentry/test_lint_debt.py:50-52` copies `_ratchet.py`, the
`tests/sentry/ratchet/` group and `tests/sentry/_baseline_sources.py` (the `KINDS` source) into
its scratch tree, and the fixture's `--init` run reaches its success assertion.

Mutations (run on the final head, results recorded):

| ID | Mutation | Test that must fail |
|---|---|---|
| C1 | Drop the `kind` rule from the CLI row schema | negative case of 1 and the registry test |
| C2 | Restore `startswith` for baseline paths | ported path test |
| C3 | Leave `release_identity.py` out of the archive list | 3 (base decision diagnostic, control passes) |
| C4 | Remove `--with-base` from `ci.yml` | 4 |
| C5 | Restore the unconditional `[ -f ... ]` skip in `gates.sh` | ported missing-checker test |
| C6 | Edit one byte of `_base_run.py` | 5 |
| C7 | Treat a failed base listing as "absent" | ported listing test |
| C8 | Archive every path without checking the base listing | 8 |
| C9 | Pass the waiver positionally | 9 |
| C10 | Restore the lenient baseline parser | ported `test_baseline_types.py` cases |
| C11 | Drop the pass-time replay in `gates.sh` | 11 |
| C12 | Do not forward `--slice` to the child | 10 |
| C13 | Apply the pre-`kind` schema to HEAD too | 12 |
| C14 | Use a plain `>` in place of `max_raised` in the split check | 13 |
| C15 | Key vendored pins on bare file names | 5 |

## Enumerations

### Exit paths

- `ratchet_check.py` (CLI): exit 2 with no merge base (`scripts/dev/ratchet_check.py:46-48`);
  exit 1 on any finding (`scripts/dev/ratchet_check.py:53-55`); with `--with-base`, the RG-E3
  exit paths (base sha missing, listing failure, unreadable checker, archive failure, base run
  non-zero, proven absence skip).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:248`): findings plus report lines; after this
  slice a base read error becomes one named finding, as in the engine.
- Gate sentry step (`scripts/dev/gates.sh:269`): the four RG-E3 cases.
- CI step (`.github/workflows/ci.yml:283-285`): runs on pull requests only; a non-zero exit fails
  the job.

### Routes

| Route into the checker | Where | This slice |
|---|---|---|
| CLI local gate, branch label | `scripts/dev/gates.sh:269` | `--with-base` |
| CLI local gate, baseline label | same line | plain run or proven-absence skip |
| CLI PR CI "Baselines only shrink" | `.github/workflows/ci.yml:285` | `--with-base --base <PR base sha>` |
| Direct harness | `tests/sentry/test_ratchet_check.py` | unchanged entry, fixtures updated |
| Error-emitter ratchet harness | `tests/sentry/cli_text/test_error_emitter_ratchet.py:19` | fixture updated |

### FK shapes

N/A. Only repo files and git objects; no keyed data.

### Fields

| Field | Where | Rule after this slice |
|---|---|---|
| `id`, `baseline` | `[[sentry]]` rows | required, as today |
| `kind` | `[[sentry]]` rows | required, one of `KINDS` (`tests/sentry/_baseline_sources.py:31`) |
| `consumer` | `[[sentry]]` rows | required on `json`, refused on other kinds |
| `approved_growth` | `[[sentry]]` rows | optional on every kind |
| `[retired]`, `[retired_files]`, `[checker_change]` | registry | new tables, dated owner rows |
| `created_in` | baseline files | required on every baseline, as today |

### Output surfaces

- `ratchet_check.py` stdout and stderr: the existing `ratchet:` report and `FAIL` lines, plus the
  RG-E3 lines (`base has no checker, base run skipped`, `waived by checker_change`).
- Gate stderr: `ratchet checker missing`, copied decision and waiver lines.
- CI job log: the same lines. Ids, paths, keys and owner text only.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Findings carry ids, paths, kinds and keys only | test 1 seeds a unique marker in a row value and asserts it is absent from output | Print the row dict: the marker appears |
| 2 | Cleanup on an exit path | The launcher extracts into a `TemporaryDirectory` | ported `test_broken_base_checker_fails` with a controlled `TMPDIR` | Cleanup disabled: the ported test fails |
| 3 | Shared state | No module state; the child env is built fresh | ported `test_inherited_waiver_env_is_stripped` | Pass the parent env through: the ported test fails |
| 4 | Route parity and silent fallback | Gate and CI call the same `--with-base` line; no skip except proven absence | test 4, ported missing-checker test | C4, C5 |
| 5 | Referential integrity | `consumer` must name a real file read by `load_allowlist`; baseline paths must be safe | test 1, `test_baseline_registry.py:291-314` kept | C2, `startswith` restored |
| 6 | Untrusted producer | N/A for V1: repo files only (accidental-only threat model); tar unpacked with the `data` filter | ported broken-base test | Drop the filter: review finding |
| 7 | Check-then-use (toctou) on the base | One sha resolved once feeds listing, archive and base run | ported `test_unreachable_base_sha_fails_with_base` | Resolve the ref twice: review finding |
| 8 | Weak tests | Every ported red-before case is run red on CLI main and listed | builder report | C7, failed listing read as absent |
| 9 | Refactor drift | `check()` keeps `max_raised`, `move_findings` and `created_in`; their tests pass unchanged; the registry test calls the shared validator | `tests/sentry/test_ratchet_check.py`, `test_baseline_registry.py` | C1, drop the kind rule |
| 10 | Frozen contract drift | N/A: test and CI tooling; no CLI command, flag or JSON field changes | release-freeze sentries stay green | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decision rows use the shipped `is_dated_owner_decision`; `kind` compared by set membership |
| 2 | Strict wire types | `kind` and `consumer` strings; baseline ids strings and `entries` present (C10); bool refused in int fields |
| 3 | No exception context | No re-raise; read errors become finding lines |
| 4 | Versioned read models | New tables are optional at base; a pre-`kind` base reads with the old schema (C13); the base checker runs with flags it knows |
| 5 | Normalized guard scanners | Registry and baselines parsed as TOML and JSON; `ci.yml` parsed as YAML in test 4 |
| 6 | Private modules | Helpers load by path; no private engine import |
| 7 | No hidden CI failures | The CI step keeps its PR condition and gains no `continue-on-error`; the only skip is proven absence |
| 8 | One input, one trust class | N/A: repo files only |
| 9 | Mutations on the final head | C1 to C15 rerun after the last code change |
| 10 | Allowlisted helpers still checked | `_base_run.py` is pinned by digest, so an edit fails, not passes |
| 11 | No raised caps | No ceiling raised; `_ratchet.py` about 372; the CLI 800-line cap excludes tests (`layout/test_module_size.py:19-30`), so ported tests follow the parent's 600-line rule per file; `test_ratchet_check.py` (565) takes no new tests; `lintdebt` baseline not raised; CLI CHANGELOG (876 lines) net-zero |

## Reuse inventory

- Engine `_integrity.py` (mirror) and `_base_run.py` (vendored) and their tests.
- CLI `_ratchet.py` `max_raised`, `move_findings`, `parse_baseline`, `reason_findings`, the
  `created_in` rule and `--slice`.
- `_baseline_sources.KINDS`; `is_dated_owner_decision`.
- `ci/vendored.toml` and the vendored-file pin pattern.
- `layout/_ratchet_cases.py` (vendored case table).

## Frozen contracts

None. The CLI command surface, `--json` documents and release freeze files do not change.
`ci.yml` changes one command line in an existing step.

## Slices

One slice, one CLI PR: `feat(sentry): port registry integrity and base run to the CLI`. Next:
RG-C1b.

Test depth: T0 the CLI ratchet tests and `scripts/dev/lintdebt.py` per edit; T1 impact
selection per commit. Triggers: CI config and test tooling, so one full CLI suite at merge with
`gates.sh --full --baseline-file <stored main baseline>`.

## Pre-mortem

- An existing CLI registry row lacks a valid `kind` or `consumer` and the live check goes red.
  Test 6 runs on the live registry first; a bad row is fixed in the registry, not by loosening
  the schema.
- RG-E3 merges without the lint fixes (BLE001, C901, RUF100) or `BASE_ARCHIVE_PATHS`. Then a small engine follow-up
  lands first; the CLI never forks `_base_run.py`.
- `test_lint_debt.py` scratch tree misses a helper and fails for the wrong reason. The fixture
  update copies the whole `tests/sentry/ratchet/` group.
- The CI checkout lacks the PR base commit. `ci.yml` already fetches what `--base` needs today;
  the builder confirms `fetch-depth` on the job before review.
- A long-open CLI branch merges after this slice and fails the base run because of a new key.
  That is the intended result; the branch rebases.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, no body unless it says
  why, last line `cam`. No trailers, file lists or test counts.
- Test depth as in "Slices"; use `~/bin/pytest-one`.
- Never raise a module-size ceiling or the fan-out cap. New tests go in `tests/sentry/ratchet/`,
  not in `test_ratchet_check.py`.
- Builders never write owner decision rows; empty tables only.
- Run each red-before test on CLI main first and record the failure; pins are not red evidence.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG entry before merge, net-zero in length.
- Stop and report if the same defect class comes back after a fix.
