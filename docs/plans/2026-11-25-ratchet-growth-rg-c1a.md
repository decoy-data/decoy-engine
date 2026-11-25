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
  by the checker (`tests/sentry/test_baseline_registry.py:96-103`);
- the gate and CI skip the checker when the file is missing (`scripts/dev/gates.sh:269`) and run
  only the HEAD copy (`.github/workflows/ci.yml:283-285`).

## Guarantee

After this slice the CLI checker gives the same answers as the engine checker after RG-E3 for
every RG-E1 and RG-E3 case, with the CLI's own row schema (`kind`, `consumer`) and decision
grammar. The CLI gate and the PR CI job both run the base checker, and a missing checker fails
outside the baseline worktree.

Non-goals:

- No numeric bounds, floors or `sentry-limits` source (RG-C1b).
- No change to the CLI decision grammar (`src/decoy/distribution/release_identity.py:58`) or to
  the rule that every baseline names `created_in` (`tests/sentry/_ratchet.py:272-273`).
- No change to `--slice` (`scripts/dev/ratchet_check.py:35`).
- No signed approvals (V2).

## What exists (reuse, do not rebuild)

- Engine, after RG-E3: `tests/sentry/ratchet/_integrity.py` (BaseTree, Side, `kind_of`,
  `open_input`, `safe_path`, `closed_keys`, `decisions`, `fresh`, `new_decisions`,
  `sentry_file_findings`), `tests/sentry/ratchet/_base_run.py`, and the RG-E1 and RG-E3 tests.
- CLI: `tests/sentry/_ratchet.py:52-61` loads the decision check by path; `:175` `max_raised`;
  `:202` `move_findings`; `:248` `check`. `tests/sentry/_baseline_sources.py:31` `KINDS`.
  `tests/sentry/test_sentry_manifest.py` `SENTRIES` (the CLI also has a manifest, so the
  sentry-file walk ports as is).
- `ci/vendored.toml` with `[[vendored]]` (byte-identical, digest-pinned, fetched and compared by
  `tests/sentry/test_ci_lock_installs.py`) and `[[mirror]]` (adapted, header names the
  differences) rows; `tests/sentry/layout/test_vendored_files.py:27-30` `PINS`.

## Design

1. Helpers, in a new CLI group `tests/sentry/ratchet/`:
   - `_base_run.py`: vendored byte for byte from the engine, pinned in `ci/vendored.toml` and in
     a `PINS` table in a new `tests/sentry/ratchet/test_vendored_ratchet.py` (same shape as
     `layout/test_vendored_files.py`). The archive path list is a parameter of `extract`, so the
     same bytes serve both repos. If RG-E3 merges with the list hard-coded, a small engine
     follow-up makes it a parameter first; the CLI never forks the file.
   - `_integrity.py`: a `[[mirror]]` of the engine file. Its header lists each difference:
     the decision check is passed in (the CLI loads `is_dated_owner_decision`), the row schema
     is passed in, and `MANIFEST` is the CLI manifest path. No other difference.
2. `tests/sentry/_ratchet.py` (+25, to about 367): `_helper(name)` loads by path as in the
   engine. `check()` builds `BaseTree` once, reads both sides through `Side`, and calls
   `closed_keys` with the CLI row schema: `id`, `baseline`, `kind` required; `kind` in
   `_baseline_sources.KINDS`; `consumer` required when `kind == "json"` and refused otherwise;
   `approved_growth` optional. Replace the `startswith` path test with `safe_path`. Keep
   `max_raised`, `move_findings`, the `created_in` rule and `--slice` as they are.
3. `scripts/dev/sentry_registry.toml`: add empty `[retired]`, `[retired_files]` and
   `[checker_change]` tables with a header comment (+15).
4. `scripts/dev/ratchet_check.py` (+20): `--with-base`, the same order as the engine (resolve
   once, head check, base run). The CLI passes `scripts/dev`, `tests/sentry` and
   `src/decoy/distribution/release_identity.py` to `extract`, because the CLI `_ratchet.py`
   loads that file by path.
5. `scripts/dev/gates.sh:269` and `.github/workflows/ci.yml:285`: both run
   `ratchet_check.py --with-base --base <sha>`. The gate passes `label` into the `bash -c`
   string with the same four cases as RG-E3. `ci.yml` keeps its step-level
   `if: github.event_name == 'pull_request'` (the lane sentry refuses a job-level `if`).
6. `CODEMAP.md` "Where Things Go", row "Sentry test" (`CODEMAP.md:73`): add the
   `tests/sentry/ratchet/` group and the two shared helpers. CHANGELOG entry.

Choke point: `_ratchet.check()` is the one reader of the registry and baselines on both sides;
`closed_keys` is the one row-schema check. Guard: `test_cli_integrity_rejects_invalid_kind_or_consumer`
runs the checker, not the registry test. Mutation: drop the `kind` rule from the schema passed
to `closed_keys`; the guard fails while `test_baseline_registry.py` alone would still pass.

Design notes: no new abstraction. The established pattern is the repo's own vendoring ledger:
byte-identical where the logic is the same, a declared mirror where the CLI differs. Each fact
has one home: the row schema in CLI `_ratchet.py`, the kinds in `_baseline_sources.KINDS`, the
decision grammar in `release_identity.py`.

### Placement

| New or changed | Path | CODEMAP rule (`CODEMAP.md:73`) | Sits beside |
|---|---|---|---|
| Ratchet helpers | `tests/sentry/ratchet/_integrity.py`, `_base_run.py` | `tests/sentry/<group>/`, helper `_<name>.py`; vendored files pinned in `ci/vendored.toml` (map edit adds the group) | `tests/sentry/layout/_ratchet_cases.py` |
| Tests | `tests/sentry/ratchet/test_integrity.py`, `test_base_run.py`, `test_vendored_ratchet.py` | `tests/sentry/<group>/test_<rule>.py` | |
| Checker, gate, CI | `tests/sentry/_ratchet.py`, `scripts/dev/ratchet_check.py`, `scripts/dev/gates.sh`, `.github/workflows/ci.yml` | existing files (`CODEMAP.md:76`) | |

## Behavior and failure modes

| Change on a CLI branch | Expected | Test |
|---|---|---|
| Registry row and its baseline deleted, no `[retired]` row | Fail | `test_removed_registry_row_without_retirement_fails` (port) |
| A sentry file deleted, no `[retired_files]` row | Fail | `test_deleted_sentry_file_fails` (port) |
| Registry file deleted or emptied | Fail | `test_deleted_registry_file_fails`, `test_emptied_registry_file_fails` (port) |
| Unknown row key | Fail | `test_unknown_registry_key_fails` (port) |
| Row with no `kind`, an unknown `kind`, a JSON row with no `consumer`, a `consumer` on a recomputed row | Fail, each named | `test_cli_integrity_rejects_invalid_kind_or_consumer` |
| Baseline path with `..` or a backslash | Fail | `test_dotdot_and_backslash_below_baseline_dir_fail` (port) |
| Base has a directory at `scripts/dev/ratchet_check.py` | Fail | `test_checker_path_is_a_directory_in_base_fails` |
| Checker deleted on a branch | Fail, "ratchet checker missing" | `test_missing_checker_fails_outside_baseline_tree` (port) |
| Head checker edited to hide growth | Base copy fails | `test_base_checker_catches_growth_hidden_by_branch_checker_edit` (port) |
| Base run needs `release_identity.py` | Extracted and loaded | `test_base_run_loads_release_identity` |
| New baseline with no `created_in` | Fail, as today | `test_new_baseline_without_created_in_fails` (pin) |
| PR CI runs the base checker | Command has `--with-base`, step-level PR `if:` kept | `test_ci_runs_base_checker_on_pull_requests` |
| Live CLI registry | Pass | `test_live_cli_registry_kinds_and_consumers_pass` (pin) |

## Acceptance tests (red first)

Tags as in RG-E3: `red-before` fails on CLI main on its assertion (recorded by the builder);
`pin` passes on main and is never offered as red evidence.

Ported from the engine (RG-E1 and RG-E3), run on CLI temp repos with valid CLI rows (each fixture
row gets `kind = "from_scan"`, or `kind = "json"` plus a `consumer`): every red-before case in the
engine `tests/sentry/ratchet/test_integrity.py`, `test_malformed_registry.py` and
`test_base_run.py`. The builder lists each ported name in the report with its red result. The
case table is the vendored `layout/_ratchet_cases.py`, pinned byte for byte
(`tests/sentry/layout/test_vendored_files.py:44-48`).

CLI-only:

1. `test_cli_integrity_rejects_invalid_kind_or_consumer` (red-before): missing kind, unknown kind,
   JSON row with no consumer, consumer on a `from_scan` row.
2. `test_checker_path_is_a_directory_in_base_fails` (red-before).
3. `test_base_run_loads_release_identity` (red-before): the extracted checker loads its own
   `release_identity.py`; a head edit to that file cannot change the base decision check.
4. `test_ci_runs_base_checker_on_pull_requests` (red-before): parse `ci.yml`; the "Baselines only
   shrink" step runs `ratchet_check.py --with-base --base ${{ github.event.pull_request.base.sha }}`
   and keeps its step-level `if:`.
5. `test_vendored_ratchet_helpers_match_their_pins` (red-before): `_base_run.py` digest equals
   the pin and the ledger row.
6. `test_live_cli_registry_kinds_and_consumers_pass` (pin): the checker on the live registry,
   including JSON rows (`scripts/dev/sentry_registry.toml:13-17`) and recomputed rows
   (`scripts/dev/sentry_registry.toml:91-94`).
7. `test_new_baseline_without_created_in_fails` (pin, `tests/sentry/_ratchet.py:272-273`).

Fixture updates (not new tests): the row writers at `tests/sentry/test_ratchet_check.py:46-47,180,483,561`
emit a valid kind; `tests/sentry/cli_text/test_error_emitter_ratchet.py:22` gets
`kind = "from_scan"` for its pass cases; `tests/sentry/test_lint_debt.py:50` copies the
`tests/sentry/ratchet/` helpers into its scratch tree with `_ratchet.py`.

Mutations (run on the final head, results recorded):

| ID | Mutation | Test that must fail |
|---|---|---|
| C1 | Drop the `kind` rule from the CLI row schema | 1 |
| C2 | Restore `startswith` for baseline paths | ported path test |
| C3 | Leave `release_identity.py` out of the archive list | 3 |
| C4 | Remove `--with-base` from `ci.yml` | 4 |
| C5 | Restore the unconditional `[ -f ... ]` skip in `gates.sh` | ported missing-checker test |
| C6 | Edit one byte of `_base_run.py` | 5 |
| C7 | Treat a failed base listing as "absent" | ported listing test |

## Enumerations

### Exit paths

- `ratchet_check.py` (CLI): exit 2 with no merge base (`scripts/dev/ratchet_check.py:45-47`);
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
| 1 | Value-bearing output | Findings carry ids, paths, kinds and keys only | test 1 asserts the finding names the id and field | Print the row dict: the message assertion fails |
| 2 | Cleanup on an exit path | The vendored `_base_run.py` extracts into a `TemporaryDirectory` | ported `test_broken_base_checker_fails` | `mkdtemp` in place of the context: the ported test fails |
| 3 | Shared state | No module state; the child env is built fresh | ported `test_inherited_waiver_env_is_stripped` | Pass the parent env through: the ported test fails |
| 4 | Route parity and silent fallback | Gate and CI call the same `--with-base` line; no skip except proven absence | test 4, ported missing-checker test | C4, C5 |
| 5 | Referential integrity | `consumer` must name a real file read by `load_allowlist`; baseline paths must be safe | test 1, `test_baseline_registry.py:291-314` kept | C2, `startswith` restored |
| 6 | Untrusted producer | N/A for V1: repo files only (accidental-only threat model); tar unpacked with the `data` filter | ported broken-base test | Drop the filter: review finding |
| 7 | Check-then-use (toctou) on the base | One sha resolved once feeds listing, archive and base run | ported `test_unreachable_base_sha_fails_with_base` | Resolve the ref twice: review finding |
| 8 | Weak tests | Every ported red-before case is run red on CLI main and listed | builder report | C7, failed listing read as absent |
| 9 | Refactor drift | `check()` keeps `max_raised`, `move_findings` and `created_in` unchanged; their tests pass unchanged | `tests/sentry/test_ratchet_check.py` | N/A |
| 10 | Frozen contract drift | N/A: test and CI tooling; no CLI command, flag or JSON field changes | release-freeze sentries stay green | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decision rows use the shipped `is_dated_owner_decision`; `kind` compared by set membership |
| 2 | Strict wire types | `kind` and `consumer` must be strings; `approved_growth` stays a list of tables |
| 3 | No exception context | No re-raise; read errors become finding lines |
| 4 | Versioned read models | New tables are optional at base; the base checker runs with flags it knows |
| 5 | Normalized guard scanners | Registry and baselines parsed as TOML and JSON; `ci.yml` parsed as YAML in test 4 |
| 6 | Private modules | Helpers load by path; no private engine import |
| 7 | No hidden CI failures | The CI step keeps its PR condition and gains no `continue-on-error`; the only skip is proven absence |
| 8 | One input, one trust class | N/A: repo files only |
| 9 | Mutations on the final head | C1 to C7 rerun after the last code change |
| 10 | Allowlisted helpers still checked | `_base_run.py` is pinned by digest, so an edit fails, not passes |
| 11 | No raised caps | No ceiling raised; `_ratchet.py` stays near 367 of the CLI's 800-line cap; `test_ratchet_check.py` (565) takes no new tests |

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

Test depth: T0 the CLI ratchet tests per edit; T1 impact selection per commit. Triggers: CI
config and test tooling, so one full CLI suite at merge with `gates.sh --full`, diffed against
the stored main baseline.

## Pre-mortem

- An existing CLI registry row lacks a valid `kind` or `consumer` and the live check goes red.
  Test 6 runs on the live registry first; a bad row is fixed in the registry, not by loosening
  the schema.
- The engine `_base_run.py` has the archive paths hard-coded. Then the engine follow-up comes
  first; the CLI never forks the file.
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
- CHANGELOG entry before merge.
- Stop and report if the same defect class comes back after a fix.
