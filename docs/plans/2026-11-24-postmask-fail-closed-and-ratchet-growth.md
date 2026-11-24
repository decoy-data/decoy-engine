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
| RG-E2 bounds carry a max or min | engine | R2 | one day | RG-E1 |
| RG-E3 gate runs the base checker | engine | R2 (CI) | half a day | RG-E2 |
| RG-C1a CLI integrity and base run | CLI | R2 (CI) | one day | RG-E3 merged |
| RG-C1b CLI bounds | CLI | R2 | one day | RG-C1a |

PM-1 is independent and can run in parallel with RG-E1. The RG slices merge in table order.
Revised after plan review round 1 (2026-11-24); owner decisions are recorded at the end.

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
`policy_validation.py::_check_one_column::unguarded::0`). It is out of scope; owner decision Q6 makes it a separate R1 row. No change to
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
| `KeyboardInterrupt` or `SystemExit` in the comparison | Propagates (a `BaseException`, not caught) | Propagates, unchanged |
| `MemoryError` or another `Exception` that `passes_through` does not re-raise | Swallowed into None | `identity_error` finding, the same as the batch path |
| Table or column missing, row counts differ, nothing comparable | None | Unchanged |
| Strategy is `passthrough` and comparison raises | No finding | No error finding (operator chose no-op), unchanged rule |

## Acceptance tests (red before)

In the existing `tests/unit/detection_verification/test_residual_pii_source_compare.py` (216
lines).

- `test_frame_path_comparison_raise_is_error_finding` (red before): one object column whose output
  cells are e-mail strings, so the detector fires, and whose source cells are objects with an
  `__eq__` that raises `TypeError`. Do not monkeypatch `pd.Series.__eq__` globally. Call
  `check_residual_pii`. Assert exactly one finding for the column, severity `"error"`, message
  contains `"TypeError"`, and no source or output cell value appears in the message.
- `test_frame_path_passes_through_exception_propagates` (red before): raise a class that
  `passes_through` returns True for; assert it propagates.
- `test_frame_and_facts_paths_agree_on_identity_error` (red before): the same faulty input through
  `_frame_column_facts` and through `column_facts`; assert `ColumnFacts.identity_error` is equal,
  and that `residual_pii_findings` gives the same severity and message. The builder may instead add
  this case to the parity test at `test_column_suite_on_facts.py:136`.
- `test_not_comparable_still_quiet`: row counts differ; assert no `"error"` finding. It passes
  before and after, and pins that None keeps its meaning.
- The post-scan sentry passes with the shrunk baseline.

Test depth: T0 the touched test file and the post-scan sentry; T1 impact selection for
`verification/postmask`. No escalation trigger. Mutation run: the leak-check rule applies, so run
mutations on `_frame_column_facts` and `_source_identity`.

# Part 2. RATCHET-GROWTH

RG source refs verified with `git show`: engine `3426165fb`, CLI `00ed97b25`.

## Problem

A ratchet list may only shrink unless the owner signs off. The engine and CLI enforce part of this
today: `tests/sentry/_ratchet.py` and `scripts/dev/ratchet_check.py` compare each registered
baseline with the merge base. A grown entry set fails unless an exact-key `approved_growth` row
with a dated decision lists the key. A raised or dropped `max` fails with no approval path at all:
`check()` subtracts approvals from `grown` only, never from `raised` (`_ratchet.py:366-379`; the
CLI `_ratchet.py:303-317` does the same). A ceiling bump the owner signed off can never pass.

Routes that loosen a guard and pass today:

1. Remove a sentry's registry row together with its baseline JSON and its `_baseline_sources`
   row. Removing the row alone already fails ("baseline file is not registered",
   `_ratchet.py:319-321`), and `test_registry_has_no_source_less_sentry` catches a source left
   behind. Removing all three passes: nothing grows.
2. Delete or empty the registry file, with the baselines and sources. Every row reads as removed.
3. Delete a sentry test file. `tests/sentry/test_sentry_manifest.py` only reads the head tree,
   and the head's `OUTSIDE_SENTRIES` can drop the entry in the same diff.
4. Escape a path with `..`. `parse_registry` checks paths with `startswith` (`_ratchet.py:69`).
5. Raise a scalar limit or lower a floor. The scalar bounds are read in the sentries:
   `test_module_size.py:71-81,170`, `layout/test_package_fanout.py:25,69-70`,
   `test_outbound_clients.py:65,321` and `release/test_public_signatures.py:32,342`.
   Three numeric baselines (module-size, log-interpolation, locator-waivers) carry no `max`, so
   `max_raised` cannot see a rise. The module-size docstring (`test_module_size.py:38`) calls its rise rule
   "review-enforced, not machine-enforced".
6. Delete `scripts/dev/ratchet_check.py`. `gates.sh` runs it only `if [ -f ... ]` (a skip meant for
   the baseline worktree), so the gate is green. CI runs the branch's own copy, so a branch can
   edit the checker to pass itself.

Field typos already fail closed and need no new check: a misspelled `approved_growth` gives no
approval, so the growth fails; a misspelled `max` reads as a dropped max, which `max_raised`
fails; a misspelled `moved_from` gives no re-home.

The CLI has routes 1, 2, 3, 4 and 6, and the same raised-max gap. It already has the baseline-file
`created_in` rule, the first-inventory rule, `CEILING_FIELDS` and the moved-field check, and its
`module-size.json` already carries `max`. CI runs `ratchet_check.py --base <PR base sha>` on PRs
(`ci.yml:285`) with the branch's copy.

Source: platform X0a-h H1, H2 and H4 (`decoy-platform`
`docs/plans/2026-11-05-x0a-h-ratchet-hardening.md`, PR #181). Only the plan merged. There is no
platform code to vendor, so the engine builds the mechanism and the CLI ports it. Until RG-E1
merges, the orchestrator checks ratchet growth by hand at each gate.

## Guarantee

After these slices, the gate and CI fail when the diff against the merge base:

- removes an id without a fresh retirement decision or a transfer traceable to that id (RG-E1);
- deletes the registry file or leaves it with no rows;
- deletes a sentry test file (`tests/sentry/**/test_*.py` plus the base's `OUTSIDE_SENTRIES`),
  unless git reports a rename into the sentry set or the head registry adds a fresh `[retired_files]` entry with a dated
  owner decision;
- adds an unknown key to a registry row, or a value that is not a decision string to the
  `[retired]`, `[retired_files]` or `[checker_change]` tables (top-level table names are not a
  closed set);
- names a baseline outside `tests/sentry/baselines/` or a path that is absolute, has a backslash or has a `..` part;
- adds a baseline file with an empty or missing `created_in`;
- raises a `max` or lowers a `min` on any baseline entry, unless an exact-key `approved_growth`
  row new in this diff lists that key;
- drops a key from a `GUARD_KEYS` baseline (`sentry-limits`), on its own row or through a
  whole-id retirement, unless a fresh approval names the old id and exact key (RG-E2);
- names a base commit that does not exist in the repository;
- runs without the checker outside the baseline worktree;
- fails to list or read the base tree, extract its checker or complete its checks;
- fails a base check, except for an approved new registry field under RG-E3.

"New in this diff" has one meaning everywhere. An `approved_growth` row is new when its
(sentry id, key) pair is not among the base approvals; a `[retired]`, `[retired_files]` or
`[checker_change]` entry is new when its name is not in that base table. Rewording a decision that
is already on base does not make it new, so it cannot re-arm an approval.

Adding a key to a `GUARD_KEYS` baseline adds a guard, so it is not growth and needs no approval.

Each decision row new in the diff (`approved_growth`, `[retired_growth]`, `[retired]`, `[retired_files]`,
`[checker_change]`) is printed as a `ratchet: decision ...` line. The sentry step copies these
lines to gate stderr on a pass too (engine `scripts/dev/gates.sh:531,542`),
so the gate reviewer sees every sign-off.

Named limits (known issues, not blockers):

- L-A. A decision row is plain text that anyone with write access can type. V1 relies on the
  report line and gate review (owner decision Q1). The gate reviewer brief adds one step: grep
  the registry diff (`git diff <base> -- scripts/dev/sentry_registry.toml`) for new decision rows
  and check each against OWNER-QUESTIONS.md. SSH-signed approvals and a `merge_check.py` run
  from a main checkout (platform H1) are V2. The V1 threat model covers accidental loosening only.
- L-B. A sentry can be weakened in its test body without touching a baseline or limit (platform
  L3). Review catches this.
- L-C. A limit-like constant nobody lists in `sentry-limits` is not seen. Finding all of them is
  follow-up work.
- L-D. A branch can edit `gates.sh`, a workflow or the head `ratchet_check.py` that starts the base
  run and applies the `[checker_change]` waiver. The base run lowers the impact, every waiver is
  printed, and the `ci-write-scopes` sentry covers workflow writes. A waiver covers only the base schema finding for the named field.
  Branch protection on main remains an owner setting.
- L-E. Platform H4 process hygiene (process-group kill, `flock -o`, bash 3.2, exact workflow `if:`)
  is out of scope except the skip-if-missing fix (owner decision Q4).
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
  fields. Each repo supplies its row schema. A key-set check handles unknown fields without a `jsonschema` dependency.
- Path safety: `pathlib.PurePosixPath(...).parts`, rejecting `..`, absolute and backslash paths, is
  the standard library way. It replaces `startswith`.
- Running a trusted copy of the checker: `git archive <ref> <paths> | tar -x` extracts a tree at a
  commit without touching the work tree or `.git`, the same approach CI systems use to evaluate a
  base-branch config.
- `tests/sentry/layout/_ratchet_cases.py` is a case table vendored byte for byte into the CLI and
  pinned by `test_vendored_files.py`. RG-E1 adds integrity cases the same way.

Design follows the shrink-only baseline pattern already in place, extended with the platform
X0a-h H2 list (AT-RI1, RI3, RI5, RI6, RI7). Scalar limits reuse the baseline mechanism (one more
`_baseline_sources` source with `max` or `min`) instead of a second one. Custom code is needed
because no tool covers deletion of the registry, a sentry file or the checker, and the decision
format is house-specific (`owner YYYY-MM-DD reason`, regex `DECISION` in `_ratchet.py`).

## Design notes

- One mechanism for every bound. Scalar caps and floors become entries of a `sentry-limits`
  baseline, approved through `approved_growth` like any other baseline. No `[[limit]]` table, no
  `approved_limit`, no second mirror test.
- One place per fact. The registry TOML stays the one list of sentries and decisions. Limit values
  live in the test constants; `sentry-limits.json` records them and each repo extends its existing mirror test to compare the live bounds.
- `_ratchet.py` is 404 lines and `test_ratchet_check.py` is 652 (over 600), so new rules go in a
  helper module and new test files. `check()` in `_ratchet.py` calls the helper and stays the one
  entry point `ratchet_check.py` runs. No second checker.
- One function per integrity rule, each returning a list of finding strings, the shape
  `reason_findings` and `growth` already return.
- Helpers are loaded by path relative to `_ratchet.py`'s own `__file__`
  (`importlib.util.spec_from_file_location`), the way `ratchet_check.py` loads `_ratchet.py`. A
  base copy extracted to a temp dir therefore loads only the base helpers, never the head's.
- RG-E1 A1 puts both input sources behind one reader. Integrity rules stay in the existing pipeline.

Choke point: `_ratchet.check()`, run by `scripts/dev/ratchet_check.py` from the `sentry` gate step
and from CI. Guard tests in `tests/sentry/ratchet/` run `ratchet_check.py` on temporary git repos
with each bypass. Mutations: drop the call to `integrity_findings(...)` in `check()` (the shared-key transfer test goes red); drop `raised -= approved_new` (the raised-max approval test goes red); make
`bound_loosened` ignore `min` (the floor test goes red); make the base run return 0 on an
extraction error (the broken-base test goes red).

## Placement

`tests/sentry/` already has 100 direct `.py` files, so every new file goes in a new
`tests/sentry/ratchet/` sub-package. `_ratchet.py` stays where it is, because `ratchet_check.py`
loads it by that path and the CLI mirrors it.

| New file | Directory | CODEMAP line | Beside |
|---|---|---|---|
| `__init__.py` (empty) | `tests/sentry/ratchet/` | new row, below | `tests/sentry/layout/__init__.py` |
| `_integrity.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/_ratchet.py` (its caller) |
| `_limit_constants.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/_baseline_sources.py` (its caller) |
| `test_integrity.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_ratchet_check.py` |
| `test_bounds.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_ratchet_check.py` |
| `test_base_run.py` | `tests/sentry/ratchet/` | new row | `tests/sentry/test_bash32_compat.py` |
| `sentry-limits.json` | `tests/sentry/baselines/` | existing baselines | the other baselines |

Map change (engine `CODEMAP.md:292`, CLI `CODEMAP.md:73`): add one "Where Things Go" row, "Ratchet checker helpers and their tests |
`tests/sentry/ratchet/` | private `_<concern>.py` loaded by path from `tests/sentry/_ratchet.py`;
tests `test_*.py` | `scripts/dev/sentry_registry.toml`". No new file goes in `scripts/` (frozen at
26). The CLI mirrors the layout under its own `tests/sentry/ratchet/`.

## RG-E1. Registry integrity (engine, R2, one day)

Changes:

- New `tests/sentry/ratchet/_integrity.py` (about 170 lines, stdlib only):
  - `registry_present(base, head)`: the registry exists at head and has at least one `[[sentry]]`
    row when the base had rows.
  - Replace the union in engine `tests/sentry/_ratchet.py:340-349,380-403` and CLI
    `tests/sentry/_ratchet.py:282-289,318-341` with one transfer check. Use it for both growth
    and removal. With removals in the diff, match each new id's key to one removed id's key.
    Exclude ids with fresh retirement decisions from ordinary transfers. RG-E2 handles guard
    retirements. Require the same key and compare its bounds against that donor. Reject missing or ambiguous donors. Consume each pair (old id, key)
    once. A split can divide one inventory across new ids. It cannot spend one key twice.
    Every removed id must supply at least one matched key or have its own fresh retirement.
    An empty inventory has nothing to transfer. With no removals, keep first inventory.
    RG-E1 starts with an empty `GUARD_KEYS`. RG-E2 adds `sentry-limits`.
  - For both `[retired]` and `[retired_files]`, require the exact id or path to be absent from
    that base decision table. Validate the new decision with the repo's dated-decision and
    reason checks. Rewording an old row cannot retire a restored id or file again.
  - `removed_sentry_files(root, base_sha)`: sentry files in the checked base tree listing
    under `tests/sentry/**/test_*.py` plus the base's `OUTSIDE_SENTRIES`, minus those at
    head. `OUTSIDE_SENTRIES` is read with `git show <base>:tests/sentry/test_sentry_manifest.py`
    and parsed with `ast` (a module-level tuple of string literals). It is never imported, so the
    head copy and pytest are not involved. A base with no `test_sentry_manifest.py` gives an empty
    list. A path `git diff -M --name-status <base> HEAD` reports as renamed passes only when its
    destination is also in the sentry set (`tests/sentry/**/test_*.py` or the head
    `OUTSIDE_SENTRIES`). Others need a `[retired_files]` entry with a dated decision.
  - `closed_keys(head_registry, schema)` checks raw rows against the repo's schema.
    The engine allows `id`, `baseline` and `approved_growth`. RG-C1a supplies the CLI schema.
    Validate the decision strings in `retired`, `retired_files` and `checker_change`.
    Ignore unknown top-level tables for forward compatibility. Implement the field-specific
    input here in RG-E1 so the extracted RG-E2 checker supports the RG-E3 waiver.
  - In both repos, call `safe_path` from `parse_registry` before opening a baseline.
    Reject absolute paths, backslashes and any `..` component. Require the exact
    `PurePosixPath(BASELINE_DIR).parts` prefix and at least one component after it.
    The current directory checks are engine `_ratchet.py:69-70` and CLI `_ratchet.py:90-91`.
  - `new_baselines_dated(base, head)`: a baseline file new in the diff needs a non-empty
    `created_in` (the file-level field all 58 engine baselines and the CLI already carry). Owner
    decision Q7: required for new baselines only, no back-fill.
  - `new_decisions(base, head)`: every decision row at head and not at base, for the report.
- Load the helper relative to `_ratchet.py`. Resolve the commit once. Build one checked
  `git ls-tree -r -t -z --full-tree <sha>` inventory (`-t` lists directories, so a
  directory at the checker path is seen and fails as the wrong type rather than as absent). Treat an optional base path as absent only
  after a successful listing omits it. A listed path must have the expected type and read
  successfully. A registry row naming a missing baseline fails. Fail on listing, blob read,
  decoding or parse errors. Apply this to the registry, baselines, manifest and source lookups.
  Keep "base commit not found" for an invalid ref. Replace the empty-data fallbacks in engine `_ratchet.py:136-147,264,315-316` and CLI
  `_ratchet.py:156-167,197-199,255-256`. Report each new decision from `check()`.
- `scripts/dev/sentry_registry.toml`: add empty `[retired]`, `[retired_files]` and
  `[checker_change]` tables with a one-line comment on the decision format. Fix the stale comment at lines 6-7. Lines 10-11 register the F29 baseline.
- Integrity case table: extend the existing vendored table in
  `layout/_ratchet_cases.py` so RG-C1a parametrizes the same cases.
- CODEMAP row (see Placement). CHANGELOG entry.

Existing tests: no expectation in `test_ratchet_check.py` changes. Replacement and split tests
(`test_split_keeping_the_union_passes`, `test_renamed_baseline_with_extra_key_fails`,
`test_replaced_baseline_with_new_sentry_id_fails`, `test_split_whose_union_adds_a_key_fails`,
`test_a_rename_may_not_raise_a_numeric_max`) keep passing or failing for the same reason, because
each kept key in these fixtures has one donor. Its fixtures write `created_in = "S0"`, so the first
inventory test still passes. The builder runs the file unchanged and reports the result. The file
takes no new tests.

Failure modes:

| Bypass | Expected |
|---|---|
| Registry row, baseline JSON and source row deleted, no `[retired]` entry | Fail, names the id |
| Row renamed to a new id that keeps the keys | Pass (replacement path) |
| Row removed and an unrelated empty sentry added in the same diff | Fail, names the id |
| Sentry file renamed to a path outside the sentry set | Fail |
| `--base` names a commit that does not exist | Fail, "base commit not found" |
| `[retired]` entry with a placeholder reason | Fail, `reason_findings` rules |
| Registry file deleted or emptied | Fail |
| Sentry test file deleted | Fail, names the path |
| Outside sentry file and its `OUTSIDE_SENTRIES` entry both deleted | Fail (base list is read) |
| Sentry test file renamed with `git mv` | Pass |
| Unknown key on a registry row | Fail, names the id and key |
| Baseline path `tests/sentry/../../src/x.json` | Fail |
| New baseline with no `created_in` | Fail |
| Base has no `[retired]` table (first run) | Pass; the tables are optional at base |

Acceptance tests in `tests/sentry/ratchet/test_integrity.py`. Reuse the temporary-git-repo
helpers from `test_ratchet_check.py` by import; do not copy them. Each test is tagged. A
**red-before** test must fail on the base, and the builder records that run. A **pin** test passes
on the base and after; it guards against over-blocking, and the builder does not claim red
evidence for it.

- `test_removed_registry_row_without_retirement_fails` (AT-RI1, red-before): deletes the row and
  the baseline file. For single-id removals, leave a second registered inventory intact.
- `test_removed_row_with_unrelated_empty_new_sentry_fails` (red-before)
- `test_removed_registry_row_with_dated_retirement_passes` (pin)
- `test_row_replaced_by_new_id_keeping_keys_passes` (pin)
- `test_two_removed_ids_cannot_share_one_successor_key` (red-before)
- `test_split_cannot_copy_one_allowance_to_two_successors` (red-before)
- `test_restored_id_requires_fresh_retirement` (red-before)
- `test_restored_file_requires_fresh_retirement` (red-before)
  Keep the old sign-off on base with the restored id or path. Delete it again at head.
- `test_retirement_with_placeholder_reason_fails` (red-before)
- `test_deleted_registry_file_fails` (pin)
- `test_emptied_registry_file_fails` (pin). Both pins leave orphan JSON on disk
  (engine `_ratchet.py:319-321`, CLI `_ratchet.py:259-261`).
- `test_registry_required_after_last_baseline_removed` (red-before). Remove all JSON.
  Delete or empty the registry. Assert the missing-registry or empty-registry finding.
- `test_deleted_sentry_file_fails` (AT-RI3, red-before)
- `test_renamed_sentry_file_passes` (pin)
- `test_sentry_file_renamed_out_of_the_sentry_set_fails` (red-before)
- `test_deleted_outside_sentry_file_with_its_list_entry_fails` (red-before)
- `test_unknown_registry_key_fails` (red-before)
- `test_unknown_top_level_table_is_ignored` (pin)
- `test_dotdot_and_backslash_below_baseline_dir_fail` (AT-RI7, red-before). Put a readable
  file at each path and leave no orphan. Assert the path finding.
- `test_absolute_and_outside_baseline_paths_fail` (pin, both repos). Include a readable
  `docs/example.json`, an absolute path and a sibling directory named `baselines-old`.
- `test_listed_base_registry_read_failure_fails` (red-before). Make only its blob read fail.
- `test_listed_base_baseline_read_failure_fails` (red-before). Use an empty head inventory.
- `test_new_baseline_without_created_in_fails` (AT-RI6, red-before)
- `test_unreachable_base_sha_fails` (red-before)
- `test_new_decision_rows_are_reported` (red-before)
- `test_live_registry_passes_against_origin_main` (pin)

Size: about +170 helper, +15 `_ratchet.py`, +10 TOML, +250 tests, +1 CODEMAP row. No public names.

Test depth: T0 the ratchet test files; T1 impact selection for `tests/sentry`. Escalation trigger:
test tooling (the ratchet is gate tooling), so the merge runs one full suite diffed against the
stored main baseline.

### RG-E1 amendment A1 (after round 3)

**Decision.** Use option (b). Option (a) hardens the filesystem path but leaves BASE with
a separate inventory and mode policy. On `aba823f37`, compare `_ratchet.py:415,447` with
`ratchet/_integrity.py:96`. A1 replaces those paths. Both sides enumerate before comparing
inventories, then open and validate each input through the same functions.

**Placement and reader contract**

| Owner | Responsibility |
|---|---|
| `tests/sentry/ratchet/_integrity.py` | Extend the existing tree reader here. It owns the single `list_entries(side, dir)`, `open_input(side, path)` and their shared guarded stat. |
| `tests/sentry/_ratchet.py` | `load_side` calls the reader for BASE and HEAD. `parse_baseline` owns the JSON field checks. Remove the separate HEAD fetch and orphan scan. |
| `tests/sentry/ratchet/test_malformed_registry.py` | Add the CLI cases and AST guard here. Reuse the scratch-repo helpers. |

- BASE uses the resolved commit's checked, NUL-delimited `ls-tree` inventory and
  `cat-file blob`. HEAD uses the current checkout, including unstaged edits and untracked
  baselines. The working copy of a staged path supplies its current mode and bytes.
  Keep the existing committed membership and rename checks for sentry test files.
- Both operations validate plain relative paths and walk from the checkout or Git tree root.
  Check every ancestor before descent, including the baseline directory itself. Require
  directories for parents and regular files for reads (Git modes `100644` or `100755`).
  Refuse links at any depth, special files and wrong-kind components. HEAD uses no-follow
  stat and directory-relative, no-follow opens. BASE checks each component in its tree listing.
- Use the same walk to inventory baseline JSON under the baseline directory on each side.
  Validate nested directories before descent. Consume `os.scandir` under the guard, including
  iteration. Any listing, stat, open, Git or UTF-8 error yields a side and path finding, exit 1.
  Only proven absence yields “missing”. A file absent after it was listed is a read failure.
  A proven absent baseline directory contains no candidates. Compare the inventory with all
  original registry rows. Orphan JSON and missing named files fail, including during bootstrap.
- Reuse guarded stat for the tracked `OUTSIDE_SENTRIES` probe (`_integrity.py:359`).
  Only proven absence enters removal handling. Route rehome source reads and absence proofs
  (`_rehome.py:76,78`) through the reader with the same checkout containment.
- Apply one registry presence rule before parsing, waivers or comparisons. Present zero-byte
  and whitespace-only files fail on either side. HEAD requires a registry. Only a proven
  missing BASE registry permits bootstrap with a valid HEAD inventory. Preserve the existing
  row-count rule and the transfer rules for new IDs in an established registry.
- In `parse_baseline` (`_ratchet.py:179,185`), require a JSON object, a string `sentry_id`,
  and an `entries` object with string keys and object values. Each entry requires a string
  `reason`. Check optional `category` and `moved_from` as strings and `max` as an exact
  integer (exclude booleans). Apply the same integer check to `min` when RG-E2 adds it.
  If present, `created_in` must be a string, and a new baseline requires nonblank text.
  Reject duplicate JSON keys at every depth. Check all documented types before identity,
  reason, move or bound comparisons. No coercion or fallback for wrong types.

**DESIGN** Remove the site exception. Extract the existing test filename check from
`is_sentry_glob` in `ratchet/_integrity.py`. Use it for sentry membership and for gate-pins
file and recursive directory checks (`test_gate_pins.py:36`). Gate pins still accepts a
directory containing a test anywhere below it, including outside `tests/sentry`. Walk its
files and apply the shared predicate. Remove `GATE_PINS_CALL` and `_unexempt`
(`ratchet/test_integrity.py:608`). Assert the raw membership scan has no findings. Seed a
duplicate at the former exempt site and require a finding there. Pin a nested test file, an
empty directory and a directory named like a test with no test file inside. Keep the registry scanner
and mirror checks (`test_baseline_registry.py:39,78`). Never widen an allowlist or ceiling.

**V2-LOG** Keep `BROKEN_FILES`. Its tuples supply malformed test data.

**V1 acceptance tests.** Run each case as a separate scratch Git repo through
`scripts/dev/ratchet_check.py --root <repo> --base <sha>`. Capture exit status and the
specific finding. Each red-before assertion below expects exit 1 where the round-three
review observed 0 on `aba823f37`. Record the red runs before changing the reader.

| Case | Fixture and assertion | Mutation killed |
|---|---|---|
| V1 listing | Leave one registered file readable by name and add an unregistered sibling. Confirm the orphan finding, then chmod the directory to `0111`. Run as an unprivileged user, verify listing gets EACCES, and require a HEAD listing finding. Restore permissions in teardown. | Convert a failed iteration to an empty list. |
| V1 parent link | Move a valid baseline directory outside the checkout and symlink its old name to it. Keep every leaf regular and readable. Require a HEAD mode finding at the linked directory. | Check only the final component and follow the parent link. |
| V1 stored identity | Use registry ID `"1"` with JSON number `1`. Put the bad JSON on HEAD alone, then on BASE alone with HEAD repaired. Require a finding for the affected side. A string ID passes. | Restore `str(sentry_id)`. |
| V1 empty registry | Start with no BASE registry or JSON. Add an empty HEAD registry, then repeat with whitespace. Require the empty-file finding. Commit the same bytes and require BASE to fail too. A valid first inventory passes before and after commit. | Make the blank check BASE-only. |

**Reader guard and mutation pins.** Scan the AST of `tests/sentry/_ratchet.py` and every
`tests/sentry/ratchet/*.py`. Check all checker functions, including new helpers. Distinguish
pytest fixture and test-driver I/O from reader code by module role. Checker code cannot
delegate reads to test drivers. Resolve import aliases, bound calls and unbound method forms.
Forbid `Path.glob/rglob`, `os.path.isfile/exists` and their pathlib equivalents throughout
the reader. Permit raw `scandir/listdir/iterdir` only in the enumeration function, raw
file opens and byte/text reads only in the open function, and raw stat only in guarded stat.
Check the exact file and function for each primitive, including which functions may request Git tree and blob data through the existing Git runner.
Seed one violation for each spelling in a sibling function and in a second module. A valid
call to each guarded operation passes. The current glob, isfile and direct reads fail this guard.

Run each following mutation separately on the final build head and record its failing test.

- Skip BASE enumeration. A committed orphan with a repaired HEAD must fail on BASE.
- Admit a symlink leaf, a linked ancestor, or a non-regular leaf, one mutation per mode rule.
  Pin each side where representable, including a Git symlink in place of the registry parent.
- Treat a failed stat or open as absence, one mutation per operation. Pin an unreadable
  outside sentry parent with a fresh retirement and a listed but unreadable baseline.
- Accept a missing HEAD registry, or bootstrap after a failed BASE registry read. Pin both.
- Drop each JSON field check in turn. Supply a wrong type on each side, including null,
  a boolean bound and a quoted integer. Remove the required-`entries` check and duplicate-key
  hook separately. The existing missing-field and duplicate-key fixtures must catch each change.
- Bypass each guarded operation in a reader helper. Its seeded AST check must fail.
  Restore the gate-pins site filter. Its seeded duplicate must fail the guard test.

Aim for 600 lines per hand-written file, with 700 as the hard maximum. The reader owner
starts at 387 lines and the malformed-registry test file at 354. Keep
`ratchet/test_integrity.py` (698) flat or smaller. Apply the builder brief's size rule.

## RG-E2. Bounds carry a max or min (engine, R2, one day)

Merges after RG-E1 and before RG-E3, so the base checker that RG-E3 starts running already knows
the `max` fields this slice adds (H1 order).

Changes:

- `_ratchet.py` (about +20):
  - Raised-max approval: in `check()`, an exact-key `approved_growth` row new in the diff (its
    (sentry id, key) pair is absent from the base approvals) exempts that key from `raised` too,
    and prints "approved raise <key> (<decision>)". An approval already on main does not exempt a
    later raise, even if the branch rewords its decision text.
  - `bound_loosened(head, base)` replaces `max_raised`: a `CEILING_FIELDS = ("max",)` value rose
    or was dropped, or a `FLOOR_FIELDS = ("min",)` value fell or was dropped. Compare each matched transfer against its donor with the same predicate.
  - `GUARD_KEYS = {"sentry-limits"}` (the RG-E1 constant, now filled). For these sentries the
    direction flips, because a key is a guard, not a debt:
    - For a surviving guard id, require fresh `approved_growth` for each lost key.
      Reuse the accepted (id, key) pairs in the stale check at `_ratchet.py:335-338`.
      Exempt that pair on the deletion PR. On later PRs exempt a historical approval only
      if it was on base and the key is absent from both trees. Reject a fresh stray approval.
    - A new guard key tightens the check and needs no approval.
    - Retiring a guard id needs a fresh `[retired]` decision and fresh approvals for every
      old key without an attributable guard successor. Store the approvals under `[retired_growth]`,
      keyed by old id, as arrays of the same `{key, decision}` records as `approved_growth`.
      Use the same parser, freshness comparison and decision report for both locations.
      Compare (id, key) across both base locations so moving an approval cannot refresh it.
      Accept new rows there only for lost keys of a guard id retired in this diff.
      For a guard rename, count a key as retained only in a registered guard successor.
      Match it once by the same transfer and bound rules.
      These matches never excuse the id retirement and never excuse another missing key.
- New `tests/sentry/ratchet/_limit_constants.py` (about 50 lines):
  - `LIMITS`: a dict from `(test file, constant)` to `"max"` or `"min"`.
  - `read_int(file, constant)`: parses the file with `ast` and returns the module-level `NAME =
    <int>` or `NAME: int = <int>` value (`Assign` and `AnnAssign`). A `bool` or a non-int value
    is an error, because `isinstance(True, int)` is true.
- `tests/sentry/_baseline_sources.py` (562 lines, about +15, stays under 600):
  - Add an optional `mins` callable to `Source`, read by the mirror test the way `maxes` is.
  - A `sentry-limits` source over `LIMITS`, keys `<file>::<CONSTANT>`, with `maxes` and `mins`.
  - Add `maxes=` to `module-size` (`in_code("test_module_size.py", "ALLOWLIST").maxes`; values are
    ints), `log-interpolation` and `locator-waivers` (`count_at=0`). See
    `_baseline_sources.py:180,313-319`, `test_log_interpolation.py:71` and `test_locator_hygiene.py:127`.
  - There is no regenerate path (`_baseline_sources.py:535-542` refuses to overwrite). The builder adds `max`
    and `min` to the three baselines and writes `sentry-limits.json` by hand, with `created_in`.
    The mirror test (`test_baseline_registry.py:47-49`, extended to `min`) is the check that the
    hand-written values match the live constants. Register the new file in the TOML. Update the
    module-size docstring sentence that says the rule is review-enforced.
- `tests/sentry/test_baseline_registry.py`: compare each live bound map with the entries carrying that
  field. Require exact integer values. An entry with a floor must not acquire a ceiling.
  Apply the same rule to ceilings with an unexpected floor.
  This lets max and min entries share one baseline (`test_baseline_registry.py:44-50`).
  Replace the hand list in `test_every_numeric_source_declares_its_max` with a walk over every
  `InCode` source: one with any value that is an int, or a tuple holding an int, and not a `bool`,
  must declare `maxes`. The rule does not key off `count_at`, so `locator-waivers` tuple values
  (`_baseline_sources.py:313`, `test_locator_hygiene.py:127` `WAIVERS`) are caught. Add `LIMITS`
  to the `LIST_NAME` pattern (`test_baseline_registry.py:26-28`) so the unregistered-reader scan
  sees the limit list.

Initial `LIMITS` rows. The builder confirms each from the test body before adding it, and records
the line that compares against it:

| Key | Value | Kind | Why it is a bound |
|---|---|---|---|
| `test_module_size.py::GOAL` | 600 | max | entries at or under GOAL need no allowlist row |
| `test_module_size.py::MAX` | 700 | max | hard ceiling for new work |
| `test_module_size.py::MARGIN` | 20 | max | headroom added to a dense ceiling |
| `layout/test_package_fanout.py::LIMIT` | 25 | max | direct-module cap per package |
| `test_outbound_clients.py::WALK_FLOOR` | 146 | min | `>=` floor on files walked (`:321`) |
| `release/test_public_signatures.py::HEAD_FLOOR` | 350 | min | `>=` floor on public names (`:342`) |

`layout/test_scoped_changes.py` LIMIT is not a bound: `LIMIT = 1` at line 20 sits inside the `OLD`
string fixture. It is not listed. `test_date_shift_window_reader.py:47,108` uses the MAX_HITS dict; if no
baseline mirrors it, the builder adds `maxes` to the `date-shift-window-reader` source rather than
a `LIMITS` row.

Failure modes:

| Change | Expected |
|---|---|
| A module-size ALLOWLIST ceiling raised 632 to 650 | Fail via `bound_loosened` |
| The same raise with an exact-key `approved_growth` row new in the diff | Pass, printed |
| The same raise with an approval row already on main | Fail |
| GOAL raised 600 to 650 in the test and in `sentry-limits.json` | Fail unless approved |
| GOAL raised in the test only | Fail, mirror test |
| WALK_FLOOR lowered 146 to 140 | Fail unless approved |
| WALK_FLOOR raised 146 to 150 | Pass |
| `LIMITS` row and its baseline entry deleted | Fail unless approved (`GUARD_KEYS`) |
| The same removal, approved, after it merges to main | Next PR passes (approval is not stale) |
| A new `LIMITS` row added | Pass, not growth |
| `sentry-limits` renamed to `sentry-limits-v2` with GOAL dropped | Fail (no replacement exemption) |
| An approval already on base reworded, and the max raised again | Fail |
| GOAL rewritten as `GOAL: int = 600` | Pass, read via `AnnAssign` |
| GOAL rewritten as `GOAL = True` | Fail, `read_int` refuses a bool |

Acceptance tests in `tests/sentry/ratchet/test_bounds.py` unless noted, tagged as in RG-E1:

- `test_max_raise_with_approved_growth_passes` (H2, red-before)
- `test_max_raise_with_approval_already_on_base_fails` (pin)
- `test_reworded_base_approval_does_not_exempt_a_raise` (pin)
- `test_module_size_ceiling_raise_needs_approval` (red-before)
- `test_log_interpolation_count_raise_needs_approval` (red-before)
- `test_locator_waiver_count_raise_needs_approval` (red-before)
- `test_limit_raise_without_approval_fails` (AT-RI5, red-before)
- `test_floor_lowered_without_approval_fails` (red-before)
- `test_floor_raised_passes` (pin)
- `test_removed_limit_key_needs_approval` (red-before)
- `test_fresh_guard_deletion_passes_then_merged_approval_is_not_stale` (red-before).
  Run the checker on the deletion PR. Commit it as base, keep the row and check the next PR.
- `test_retired_guard_requires_every_lost_key_approval` (red-before). Keep another sentry.
  A fresh id retirement with one key approval missing fails. Add the missing approval and pass.
- `test_added_limit_key_is_not_growth` (red-before)
- `test_guard_sentry_renamed_with_a_dropped_key_fails` (red-before)
- `test_read_int_handles_annassign_and_refuses_bool` (red-before)
- `test_every_numeric_in_code_source_declares_max` (in `test_baseline_registry.py`, red-before)
- `test_limits_list_is_seen_by_the_reader_scan` (in `test_baseline_registry.py`, red-before)
- `test_live_limit_constants_match_recorded_bounds` (red-before). Use a standalone test
  that collects on main. Require the live source and compare its bounds through the mirror.
  After registration also run `test_source_matches_its_registered_baseline[sentry-limits]`.
  That node is post-change coverage only. Main collects from `bs.SOURCES`
  (`test_baseline_registry.py:38-49`). A missing node is no red-before result.

Size: about +20 `_ratchet.py`, +50 helper, +15 `_baseline_sources.py`, +8 TOML, three regenerated
baselines and one new one, +200 tests. No ceiling is raised.

Test depth: T0 the ratchet, baseline-registry and module-size tests; T1 impact selection. Same
test-tooling trigger as RG-E1; it can ride the same merge train.

## RG-E3. Gate runs the base checker (engine, R2 for CI, half a day)

Starts after RG-E2 merges.

Changes:

- Add `--with-base` to `scripts/dev/ratchet_check.py`. Resolve the base once before the
  head check. Pass the same sha and RG-E1 tree inventory through the run.
  - Fail an invalid commit or failed tree listing. Skip only the base run if the successful
    listing omits the exact checker path. Print "ratchet: base has no checker, base run skipped".
    A listed checker must be a readable regular blob. A failed probe never proves absence.
  - Extract `git archive <sha> scripts/dev tests/sentry` into a `TemporaryDirectory`.
    Check the archive command and unpack with the data filter. Run the extracted checker
    with `--root <head root> --base <sha>`. Load helpers relative to the extracted checker.
    Every read, extraction, import, launch or runtime failure fails, even with a waiver.
  - Require the unwaived head check to pass. Scope a fresh `[checker_change]` decision to one added registry field. Use the field
    name as its key. Require an edit to the checker entry point, `_ratchet.py` or a loaded
    ratchet helper. Require the same ids in both registries and
    no baseline edit. The only sentry-row edits allowed are additions of that field to
    existing ids. Check each (id, field) against the actual diff. Reject any other row edit.
  - In RG-E1 give the base checker one optional input for those exact (id, field) pairs
    through its child process environment. Set it only for the extracted run after validation.
    Strip inherited waiver input before the head check in both gate and CI. In `closed_keys`, omit only the corresponding
    unknown-field finding and report each use as "waived by checker_change".
    All other checks run on the real head, including sentry-file retirements. Never turn
    a nonzero process exit into success. Older checkers run with the existing flags and
    can pass a schema change only if they already accept it.
- `scripts/dev/gates.sh` sentry step (`gates.sh:491`): `label` is a local in `run_steps`, so pass it
  into the `bash -c` string as an argument (`env GATE_LABEL="$label"` or a positional). Skip a
  missing checker only when the label is `baseline` and a successful listing of that tree
  proves the checker path absent. A listed but missing worktree file fails. On any other tree, a missing
  `scripts/dev/ratchet_check.py` prints "ratchet checker missing" and fails. Call
  `ratchet_check.py --with-base` on the branch tree. On the `baseline` label call it without
  `--with-base`. Older checkers accept only `--root` and `--base`
  (engine `scripts/dev/ratchet_check.py:37-41`). One shell line; the CLI reuses the same invocation (L7).
- After the step, copy the `ratchet: decision ...` and "waived by checker_change" lines from the
  step log to gate stderr even when the step passes, so the gate reviewer sees them (L-A).
- `.github/workflows/gate-selfhosted.yml` already runs the `sentry` step, so no workflow edit is
  planned (`.github/workflows/gate-selfhosted.yml:84-85`). If one turns out to be needed, the `ci-write-scopes` sentry applies.

Failure modes:

| Change | Expected |
|---|---|
| Branch deletes `ratchet_check.py` | Fail |
| Branch edits `_ratchet.py` so `check()` returns nothing, and grows a baseline | Base copy fails the growth |
| Branch empties `integrity_findings` in the head helper and deletes a registry row | Base copy (its own helper) fails |
| Head adds a new registry-row key with a matching checker change and a `[checker_change]` row | Pass, waiver printed |
| The same without a `[checker_change]` row | Fail |
| This slice's head run by the RG-E2 base checker | Pass (the `[checker_change]` table is known since RG-E1) |
| Base has `ratchet_check.py` but it cannot be extracted or crashes | Fail |
| Base has no `ratchet_check.py` | Skip, one printed line |
| Base sha does not exist | Fail, "base commit not found" |
| `git archive` fails while `tarfile` reads a partial stream | Fail |
| Diff has a `[checker_change]` entry and also edits a baseline | Fail |
| Passing gate with a new decision row | Pass, decision line on gate stderr |
| Baseline-label run | Base checker runs without `--with-base` |
| Baseline worktree with no checker | Skip, as today |

Acceptance tests in `tests/sentry/ratchet/test_base_run.py`, tagged as in RG-E1. They run the
sentry step command or `ratchet_check.py --with-base` on a temporary repo, using the subprocess
harness in `test_ratchet_check.py:61-72`. For negative cases run the branch gate command and
assert the specific failure. An argparse error for an unknown flag is no red-before proof.

- `test_missing_checker_fails_outside_baseline_tree` (red-before)
- `test_missing_checker_skips_in_baseline_tree` (pin)
- `test_base_checker_catches_growth_hidden_by_branch_checker_edit` (red-before)
- `test_base_checker_ignores_tampered_head_helper` (H6, red-before)
- `test_new_registry_key_with_checker_change_passes_base_run` (H1, red-before)
- `test_new_registry_key_without_checker_change_fails_base_run` (red-before)
- `test_checker_change_with_a_baseline_edit_fails` (red-before)
- `test_failed_tree_listing_never_skips_base_checker` (red-before)
- `test_listed_checker_read_error_never_skips` (red-before)
- `test_schema_waiver_cannot_hide_archive_failure_or_crash` (red-before)
- `test_schema_waiver_cannot_hide_sentry_file_retirement` (red-before). Include the valid
  field addition and delete an unrelated sentry. Disable the head retirement check to
  prove the extracted checker still rejects the deletion.
- `test_schema_waiver_rejects_another_row_edit` (red-before)
- `test_broken_base_checker_fails` (M5, red-before): the base has `ratchet_check.py` but its
  `_ratchet.py` has a syntax error
- `test_unreachable_base_sha_fails_with_base` (red-before)
- `test_base_checker_absent_skips_with_message` (red-before)
- `test_decision_lines_shown_on_a_passing_gate` (red-before)
- `test_baseline_label_runs_without_with_base` (pin, engine `gates.sh:474,491`, CLI `gates.sh:269`)

Size: about +55 `ratchet_check.py`, +12 `gates.sh`, +180 tests.

Test depth: T0 the new test file and `test_bash32_compat.py`; T1 impact selection; the gate runs
`gates.sh --keep-going --steps env,ruff,format,mypy,sentry` on the exact head. Test-tooling
trigger: full suite once at merge.

## RG-C1a. CLI integrity and base run (CLI, R2 for CI, one day)

Starts after RG-E3 merges, so the CLI ports reviewed code.

- `tests/sentry/ratchet/_integrity.py`: port from the engine. Keep the CLI's decision grammar
  (`src/decoy/distribution/release_identity.py:58`) and its existing
  baseline-file `created_in` rule (`_ratchet.py:274-275`). Pass the CLI row schema into
  `closed_keys`. Add required `kind` from `_baseline_sources.py:31`. Require `consumer`
  on JSON rows and forbid it on other kinds. Keep `approved_growth` optional for all kinds.
  Use this one schema in both the checker and registry tests. Keep the consumer-to-loader
  check (`test_baseline_registry.py:96-103,291-314`). Update the CLI fixture row writers
  (`test_ratchet_check.py:46-47,180,483,561`) to emit a valid kind. Also update
  `tests/sentry/cli_text/test_error_emitter_ratchet.py:22`: its row needs `kind = "from_scan"` for
  the pass cases at `:68` and `:73`. `tests/sentry/test_lint_debt.py:50` copies the checker into a
  scratch tree; copy `_integrity.py` with it so the scratch checker can load `safe_path`.
  Test: a directory at `scripts/dev/ratchet_check.py` in the base tree fails the gate.
  Pin the shared case table byte for byte (`layout/test_vendored_files.py:44-48`).
- `tests/sentry/_ratchet.py` (342 lines): load the helper by path; call it from `check()`; replace
  `startswith`.
- `scripts/dev/sentry_registry.toml` (201 lines): `[retired]`, `[retired_files]`,
  `[checker_change]`.
- `scripts/dev/ratchet_check.py`: the same `--with-base` flag. The CLI base extraction adds
  `src/decoy/distribution/release_identity.py` to the `git archive` paths, because the CLI
  `_ratchet.py` loads it by path (`tests/sentry/_ratchet.py:52-60`).
- `scripts/dev/gates.sh:269` and `.github/workflows/ci.yml:285` ("Baselines only shrink"): both
  call the same `ratchet_check.py --with-base --base <sha>` line; no second inline copy of the
  shell. In `ci.yml` the step keeps its step-level `if: github.event_name == 'pull_request'`; the
  lane sentry refuses a job-level `if`. Pass `label` into the `gates.sh` `bash -c` string as in
  RG-E3.
- CHANGELOG entry.

Port the RG-E1 and RG-E3 behavior cases. Use valid CLI rows in the shared fixtures.

- `test_live_cli_registry_kinds_and_consumers_pass` (pin). Run the CLI checker on the live
  registry, including JSON rows (`scripts/dev/sentry_registry.toml:7-17`, kind definitions and a
  JSON row) and recomputed rows (`:91-94`).
- `test_cli_integrity_rejects_invalid_kind_or_consumer` (red-before). Run the checker
  on a missing or unknown kind, a missing JSON consumer and a consumer on a recomputed row.
- `test_new_baseline_without_created_in_fails` is a CLI pin (`_ratchet.py:274-275`).
- `test_ci_runs_base_checker_on_pull_requests` (red-before). Check the command and its
  step-level PR condition (`.github/workflows/ci.yml:283-285`).

Size: about +250 helpers and `ratchet_check.py`, +15 TOML, +25 `_ratchet.py`, +10 `gates.sh`,
+3 `ci.yml`, +250 tests.

## RG-C1b. CLI bounds (CLI, R2, one day)

Starts after RG-C1a merges.

- `tests/sentry/_ratchet.py`: the raised-max approval (an exact-key `approved_growth` row new in
  the diff), `FLOOR_FIELDS = ("min",)` beside the existing `CEILING_FIELDS`, and `GUARD_KEYS`.
- `tests/sentry/ratchet/_limit_constants.py`: port, with the same `AnnAssign` and bool rules.
- Register `sentry-limits` as a recomputed source with a CLI reader and a `created_in`
  entry (`test_baseline_registry.py:96-107,116-125`, `_baseline_sources.py:99-106`).
  Extend `test_recomputed_keys_match_the_registered_baseline` at its existing assertion.
  Keep key equality. For a numeric reader compare every live key's field and integer value
  to its recorded `max` or `min`. Reject a missing, extra, wrong-direction or non-integer
  bound, including bool. Read live values with the RG-E2 reader and its one `LIMITS` map.
- Audit other CLI numeric sources for missing recorded bounds. Start with the 800-line
  module size and 25-module fanout ceilings (`layout/test_module_size.py:19,42`,
  `layout/test_package_fanout.py:20,54-55`) and the release floors of 1400 and 7
  (`release/test_retired_name_residual.py:270,311`, `release/test_tag_census.py:16,22`).
  Keep the existing CLI ceiling fields and moved-field check (`_ratchet.py:48-49,175-194`).

Port the RG-E2 guard, approval and bound cases using CLI sources. Include both PRs of
the guard-deletion test and the whole-id case. Engine-only source tests stay in RG-E2.

- `test_cli_mirror_rejects_constant_only_loosening` (red-before). In a scratch tree
  install the numeric reader and a matching baseline. Seed a reader in the existing
  mirror fixture on main so the test collects and exercises its key comparison.
  Run that same mirror before and after raising only the module-size constant. Repeat
  with only the tag-census floor lowered. Keep the keys and JSON byte-identical.
  Assert the mirror names the mismatched key. Main's key-only mirror accepts both edits
  (`test_baseline_registry.py:121-125`).
- `test_module_size_ceiling_raise_needs_approval` is a CLI pin. The recorded max exists
  (`baselines/module-size.json:4-8`) and the checker rejects the raise (`_ratchet.py:312-317`).
- `test_reworded_base_approval_does_not_exempt_a_raise` stays a pin in both repos.
  Main already rejects that raise (engine `_ratchet.py:375-379`, CLI `_ratchet.py:312-317`).

Size: about +20 `_ratchet.py`, +50 helper, +15 sources, +8 TOML, one new baseline, +180 tests.

Test depth (C1a and C1b): T0 the CLI ratchet tests; T1 impact selection. Triggers: CI config and
test tooling, so one full CLI suite at each merge, diffed against the stored main baseline. Use
`gates.sh --full`.

# Defect classes

From the plan contract's class list (classes 1 to 10, checked by `~/bin/plan-lint`).

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | PM-1: `identity_error` holds `type(exc).__name__` only, the same field the batch path fills. RG: findings name ids, paths, keys and numbers from the repo's own registry, never file content | PM-1 AT asserts no cell value in the message | Put `str(exc)` in `identity_error`: the message check fails |
| 2 | Cleanup on an exit path | RG-E3 extracts the base checker into a `tempfile.TemporaryDirectory` context, removed on every exit; RG tests use pytest `tmp_path` repos; nothing is written to the shared `.git` (`git archive` reads only) | `test_broken_base_checker_fails` checks the temp dir is gone after a failing run | Replace the context with `mkdtemp`: the leftover-dir check fails |
| 3 | State and concurrency | The ratchet helpers keep no module state; each call reads base with `git show` and head from the tree. PM-1 adds no state | Tests run under xdist with separate `tmp_path` repos | N/A: no shared state to mutate |
| 4 | Route parity and silent fallback | PM-1: frame and batch paths fill `identity_error` the same way. RG: gates.sh and CI call the same `ratchet_check.py --with-base`; a missing checker fails outside the baseline tree; a broken base run fails instead of skipping | `test_frame_and_facts_paths_agree_on_identity_error`; `test_missing_checker_fails_outside_baseline_tree`; `test_broken_base_checker_fails` | Restore `return None` in `_source_identity`; restore the unconditional `-f` skip; return 0 on extraction error: each test fails |
| 5 | Referential integrity | RG: a registry row's `baseline` path must exist and be safe; a `sentry-limits` key must resolve to a live int constant (mirror test). PM-1: N/A, no FK handling | `test_dotdot_and_backslash_below_baseline_dir_fail`; `test_source_matches_its_registered_baseline[sentry-limits]` | Revert `safe_path` to `startswith`: the path test fails |
| 6 | Untrusted producer | N/A for V1: inputs are the repo's own registry, baselines and git history (V1 threat model, accidental only). Decision rows are parsed with the anchored `DECISION` regex using `fullmatch` | A decision row with a trailing newline is refused | Swap `fullmatch` for `match` with `$`: that case passes and the test fails |
| 7 | Check then use on a path | `check()` and `--with-base` verify `<base>^{commit}` exists; `ratchet_check.py --with-base` resolves the base sha once and passes the same sha to every `git show`, `git ls-tree`, `git archive` and the base run | Code review on `ratchet_check.py` | Resolve the merge base twice: review finding |
| 8 | Weak tests and overclaimed evidence | Every AT is tagged red-before or pin; each red-before AT is run red on the base first, and pins are never offered as red evidence; `test_removed_registry_row_without_retirement_fails` deletes the baseline file too so it is red before; `test_live_registry_passes_against_origin_main` keeps the real repo in the loop; the numeric-source walk replaces a hand list | Builder report lists each red-before result and each mutation | Return an empty list from `integrity_findings`: the shared-key transfer test fails |
| 9 | Refactor drift | PM-1 moves the catch from `_source_identity` to its one caller; `max_raised` becomes `bound_loosened` with every caller updated in the same slice | `postscan/test_column_facts.py` and `test_ratchet_check.py` pass unchanged | N/A |
| 10 | Frozen contract drift | N/A: no public name, finding schema or reason code changes | Existing census sentries stay green | N/A |

## Recurring defect catalog (11 classes)

Checked against `/home/cam/dev-rules/catalogs/recurring-defects.md`.

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | `DECISION` uses `fullmatch`; `safe_path` works on path parts |
| 2 | Strict wire and stored types | `read_int` refuses `bool` and non-int values; `_max_of` already checks `isinstance(..., int)`, and the builder makes it refuse `bool` too |
| 3 | No exception context | N/A: nothing is re-raised with a cause |
| 4 | Versioned read models | The base run calls the base checker with existing flags only; new registry tables are optional at base; a new registry key needs `[checker_change]` (H1) |
| 5 | Normalized guard scanners | `OUTSIDE_SENTRIES` and `LIMITS` constants are read with `ast` (`Assign` and `AnnAssign`), never by regex |
| 6 | Private modules | `passes_through` comes from the public `decoy_engine.profiling` |
| 7 | No hidden CI failures | The only skip is "base has no checker", proved by a successful tree listing; a missing base commit, an archive or extraction failure or a base run failure fails; the missing-checker skip is limited to the baseline label; decision lines reach gate stderr on a pass |
| 8 | One input, one trust class | N/A: one input class (repo files) |
| 9 | Mutations on the final head | The builder reruns the listed mutations after the last code change and records the head |
| 10 | Allowlisted helpers are still checked | N/A: no sentry allowlist gains a helper |
| 11 | No raised caps | No ceiling is raised; `_baseline_sources.py` stays under 600; `test_ratchet_check.py` takes no new tests |

# Enumerations

### Exit paths

- `_source_identity` (`residual_pii.py:240-274`): returns a tuple (compared); returns None when
  the table is missing, the column is missing, row counts differ or zero rows are comparable; or
  raises (comparison failed). PM-1 removes the last path, the `except Exception: return None`.
- `_frame_column_facts` call site (`residual_pii.py:183`): success, not comparable, a raise that
  `passes_through` keeps (propagates), any other raise (sets `identity_error`).
- `_ratchet.check()` (`tests/sentry/_ratchet.py:305`): returns findings and report lines;
  `ratchet_check.py` exits 1 on any finding and 2 when it has no merge base.
- `ratchet_check.py --with-base` skips the base run only on proven checker absence.
  It fails on any read error, extraction error, crash or remaining finding. A successful
  schema waiver prints the exact field and id. All independent checks must pass.
- Engine sentry step (`scripts/dev/gates.sh:491`): checker present (run, fail on non-zero); checker
  missing with label `baseline` (skip); checker missing with any other label (fail).

### Routes

| Route into the check | Where | Slice |
|---|---|---|
| Frame path `check_residual_pii` | `residual_pii.py:183` | PM-1 |
| Batch path `column_facts` (already fail-closed) | `_column_facts.py:380` | none |
| Engine local gate and `gate-selfhosted.yml` branch pushes | `scripts/dev/gates.sh:491` | RG-E1 to RG-E3 |
| CLI local gate | CLI `scripts/dev/gates.sh:269` | RG-C1a, RG-C1b |
| CLI PR CI "Baselines only shrink" | CLI `.github/workflows/ci.yml:285` | RG-C1a, RG-C1b |

### FK shapes

N/A. Neither row reads or writes keyed data. PM-1 compares one column by position and touches no
FK logic.

### Fields

| Field | Where | Change |
|---|---|---|
| `ColumnFacts.identity_error` | `_column_facts.py:179` | now set on the frame path too |
| `[[sentry]]` row keys (RG-E1 and RG-C1a) | `scripts/dev/sentry_registry.toml` | one closed schema per repo |
| `[retired]`, `[retired_files]`, `[checker_change]` | registry | new tables (all in RG-E1), `key = "owner YYYY-MM-DD reason"`; top-level table names stay open |
| `[retired_growth]` | registry | RG-E2 stores lost-key approvals by retired guard id |
| Baseline file `created_in` | `tests/sentry/baselines/*.json` | required on baseline files new in the diff |
| Baseline entry `max` | three baselines | added (RG-E2) |
| Baseline entry `min` | `sentry-limits.json` | new floor field (RG-E2) |

### Output surfaces

- Residual finding message (`residual_pii.py:552-558`): exception class name only.
- Ratchet findings and decision report lines on the stdout of `ratchet_check.py`: ids, paths, keys,
  numbers and the decision text the owner wrote. No file content.
- The base-run lines: "base has no checker", "waived by checker_change", and the base findings.
- The sentry step's "ratchet checker missing" line.

### Loosening forms the checker must see

| Form | Slice | Test |
|---|---|---|
| Registry row and baseline removed | RG-E1 | `test_removed_registry_row_without_retirement_fails` |
| Registry file deleted or emptied | RG-E1 | `test_deleted_registry_file_fails`, `test_emptied_registry_file_fails` |
| Sentry file deleted (inside `tests/sentry/` and the outside list) | RG-E1 | `test_deleted_sentry_file_fails`, `test_deleted_outside_sentry_file_with_its_list_entry_fails` |
| Unknown registry key | RG-E1 | `test_unknown_registry_key_fails` |
| Unsafe path (`_ratchet.py:69` uses `startswith` today) | RG-E1 | `test_dotdot_and_backslash_below_baseline_dir_fail` |
| Baseline count raised with no `max` | RG-E2 | the three `*_raise_needs_approval` tests |
| Scalar cap raised, floor lowered, limit key removed | RG-E2 | `test_limit_raise_without_approval_fails`, `test_floor_lowered_without_approval_fails`, `test_removed_limit_key_needs_approval` |
| Checker deleted, edited or its helper emptied | RG-E3 | `test_missing_checker_fails_outside_baseline_tree`, `test_base_checker_catches_growth_hidden_by_branch_checker_edit`, `test_base_checker_ignores_tampered_head_helper` |

# Reuse inventory

- `ColumnFacts.identity_error` and its `"error"` finding in `residual_pii_findings`: reused, not
  rebuilt.
- `passes_through` from `decoy_engine.profiling.scan_set`: reused for the re-raise guard.
- `_ratchet.py`: `DECISION`, `reason_findings`, `parse_registry`, `parse_approvals`, `max_raised`
  (generalized to `bound_loosened`), `moved_from`, the replacement and split call site, and the
  `check()` entry point: reused; new rules plug into `check()`.
- `approved_growth`: the one approval form for growth, raised maxes, lowered floors and removed
  limit keys. RG-E2 stores the same records under the old id when its sentry row is gone.
- `_baseline_sources.Source` with `maxes`, the regenerate path and
  `test_source_matches_its_registered_baseline`: reused for scalar limits through the
  `sentry-limits` source.
- `ratchet_check.py --root` and `--base`: reused; no `--repo`.
- `test_ratchet_check.py` temporary-repo helpers: imported by the new test files.
- `layout/_ratchet_cases.py` and `test_vendored_files.py`: the pattern for sharing case tables with
  the CLI.
- CLI `is_dated_owner_decision`, `created_in` rule and `CEILING_FIELDS`: kept as they are.

# Frozen contracts

None touched. PM-1 changes a private function and fills an existing field; the residual finding
schema, reason codes and `_blocked.py` verdict mapping do not change. The ratchet work is test and
gate tooling only.

# Pre-mortem

- A new registry key or checker fix deadlocks against the base checker. Closed: baseline entries
  have no closed schema, each repo supplies one row schema, RG-E2 merges before RG-E3, and a real
  checker change carries a `[checker_change]` owner row that the report prints.
- A new required key or table breaks every open branch at once. Closed: the new tables are
  optional at base, `created_in` is required only for baselines new in the diff, and RG-E3's own
  head must pass the RG-E2 base checker.
- An approved limit removal goes stale once merged and turns every later PR red. Closed: the
  stale check admits the fresh deletion and keeps the merged approval inert.
- Builders learn to paste decision rows to get green. Partly closed: every new row is printed for
  the gate reviewer (L-A), and builders never write decision rows (see Builder brief items). A
  signed approval is V2.
- The sentry-file walk flags normal moves. Closed by `git diff -M` rename detection. A split of one
  file into two shows as delete plus add: the builder raises it on OWNER-QUESTIONS.md, and the
  `[retired_files]` row is written only with the owner's dated answer.
- The base-checker run fails because the base tree imports something the extract lacks. Closed by
  extracting whole directories with `git archive`, not a file list; a failure then fails the step
  loudly (M5) rather than skipping. The builder runs it once on a real main sha before review.
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
- Builders never write an owner decision row (`approved_growth`, `[retired_growth]`, `[retired]`, `[retired_files]`,
  `[checker_change]`). When a change needs one, raise it on the vault `OWNER-QUESTIONS.md` with
  options and a recommendation, and write the row only with the owner's dated answer. Test
  fixtures inside `tmp_path` repos are not decision rows.
- Red before: run each acceptance test tagged red-before on the base first and record that it
  fails. Tests tagged pin pass on the base; do not report them as red evidence.
- No cell values, query text or exception message text in any finding or log line.
- Lint own edits: `ruff check`, `ruff format --check`, `mypy` before each commit.
- CHANGELOG updated before merge.

# Follow-ups (V2-LOG)

- L1 from plan review round 1: route `identity_error` on both the frame and batch paths through
  the central `safe_error_class` (`_progress_events.py:85`) at the message site
  (`residual_pii.py:558`). Class names are under the V1 bar.

# Owner decisions (2026-11-24)

The owner took the recommended answer on all seven questions.

- Q1. An owner sign-off in V1 is a dated text decision row plus a printed report line the gate
  reviewer checks. SSH-signed approvals checked from a main checkout (platform H1) are V2.
- Q2. Removing a sentry or deleting a sentry file needs an owner row (`[retired]` or
  `[retired_files]`). A removal covered by a replacement or split id needs none.
- Q3. Floors are covered, as `min` entries in the `sentry-limits` baseline (engine WALK_FLOOR and
  HEAD_FLOOR; CLI floors confirmed in RG-C1b).
- Q4. Platform H4 process hygiene stays out of this row. Only the skip-if-missing fix is in scope
  (RG-E3, RG-C1a). The rest is logged as a 1.x row.
- Q5. Keep the frame-path `check_residual_pii` and fix it in PM-1.
- Q6. `policy_validation.py::_check_one_column` gets the same fail-closed fix as a separate small
  R1 row.
- Q7. `created_in` is required for new baselines only, no back-fill. It is the baseline-file
  field the CLI already requires.
