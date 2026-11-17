# WF-R engine and CLI part: tombstone the `WORKFLOW_*` reason codes

Status: plan

Rules consulted: 00-universal.md, risk-and-exceptions.md, development-loop.md,
api-and-compatibility.md, testing.md, catalogs/recurring-defects.md.

Roadmap row 17 (CLI repo `docs/ROADMAP.md`, section B). Planned from engine `origin/main`
`902968682`, CLI `origin/main` `419572a` and platform `origin/main` `fbaee2a9`. Risk R1 for both
slices: no runtime behavior changes, the identity set does not change, and one revert undoes the
change before the next engine release stamps it.

## Problem

The owner retired workflows: the pipeline is the only unit. The engine still declares three
live `platform` reasons for workflow runs:

- `platform/workflow_restart_interrupted` (`PlatformJobLog`, failure, execution),
  `src/decoy_engine/reasons/platform/_part1.py:239`
- `platform/workflow_step_not_run` (`PlatformJobLog`, control, cancelled),
  `src/decoy_engine/reasons/platform/_part1.py:244`
- `platform/workflow_step_failed` (`PlatformResponse`, failure, execution),
  `src/decoy_engine/reasons/platform/_part1.py:325`

All three shipped at `since` 1.5.0 and are in the release pin
(`tests/fixtures/f29/reason-registry-release.json`). Codes are append-only
(`docs/reasons.md:23`), so they become tombstones. They are never deleted.

The CLI pointer the row names (`src/decoy/cli/explain.py:170` when the row was written: the
`explain yaml` topic line "Full guide in the docs hub: decoy-platform/docs/guides/cli-yaml-workflows.md")
is already gone. CLI #146 (`cfdee4e`, 2026-11-09) removed it, and
`tests/e2e/first_user/test_items_text.py:91` bans `decoy-platform` in every explain topic. The CLI
slice only pins the row's exact pointer and the workflow codes in a test, and closes the row.

## Guarantee and non-goals

Guarantee:

1. After the engine slice, each of the three identities still resolves through `reasons.find`
   and its `reasons.platform.WORKFLOW_*` symbol. Each carries `deprecated_in=UNRELEASED` until
   release prep stamps it, and `replaced_by` names one live `platform` identity:
   - `workflow_restart_interrupted` to `platform/startup_failed`
   - `workflow_step_not_run` to `platform/job_cancelled`
   - `workflow_step_failed` to `platform/job_failed`
2. No other field of the three entries changes (summary, kind, rules, owner, symbol, since).
3. No other identity changes. The slice does not edit `REGISTRY_VERSION`, the release pin, the
   minor fixtures or `consumer-contract.json`. Release prep stamps the deprecation as a registry
   patch (`docs/reasons.md:27`).
4. After the CLI slice, a test proves that no `decoy explain` topic names the old guide or a
   workflow reason code.

Non-goals: deleting the codes (the row says never deleted); new wording for the tombstone
summaries (a tombstone keeps its shipped text, as in `route/_retired.py`); the platform backend
WF-R removal (separate platform row); any CLI repin.

## Behaviour and failure modes

Behaviour: on the branch, `reasons.get("platform", "workflow_step_failed").deprecated_in` is
`"unreleased"`; after release prep it is that release's registry version. `replaced_by` is
`("platform", "job_failed")`. A persisted record that names a workflow code still decodes as that
identity, not as `decoy/unknown_reason_from_future`. `decoy ci` keeps the codes in its SARIF
allowlist because it reads the registry with tombstones included (CLI
`src/decoy/ci/rule_codes.py:200`). That is correct and does not change.

Failure modes the plan closes:

- F1. A deprecation without `replaced_by` is not a waivable pending edit
  (`scripts/release/reason_manifest_policy.py:367`), so `reason_release_pin.py --check` reports
  drift. Closed: each tombstone names a replacement.
- F2. A replacement that is itself retired, or a typo, breaks the existing sentry
  `test_no_tombstone_without_a_live_replacement` (`tests/unit/test_shipped_reason_identities.py:157`;
  engine PR #610 moves it to `tests/unit/test_reason_tombstones.py`) and `check_integrity`
  (`src/decoy_engine/reasons/_registry.py:202`). Closed: the three replacements are live today.
- F3. The move changes an owner string, so `test_identity_set_is_exact`
  (`tests/unit/safe_output/test_platform_reasons.py:136`) and the pin fail. Closed: the new file
  uses the same `_catalog.platform("PlatformJobLog")` and `_catalog.platform("PlatformResponse")`
  declarers.
- F4. A numeric `deprecated_in` (for example `"1.29.0"`) typed by hand goes around the stamp and
  fails `reason_release_pin.py --check`. Closed: `UNRELEASED` only.
- F5. This slice and PR #610 both edit the tombstone sentence in `docs/reasons.md:27`. Closed:
  the slice that merges second rebases and states the count from main at that time.

## Platform consumer check

Platform `origin/main` `fbaee2a9` does not emit or read these codes. A search over every platform
ref for the three codes and their symbols finds one hit: the WF-R row of
`docs/product/v1-ux-map.md:365`, which already says "tombstoned, never deleted". The platform API
does not import these codes from `decoy_engine.reasons`. Its workflow runner writes prose to
`job.log` (`api/workflows/runner.py:90`, `api/workflows/restart_recovery.py:48`), not codes, so
no persisted platform record names them. The tombstones keep every identity resolvable, which is
all a later reader needs. The platform needs no change for this row.

## Reuse inventory

- Tombstone mechanism: the catalog arguments `deprecated_in` and `replaced_by`, the convention
  file `reasons/<namespace>/_retired.py` (`src/decoy_engine/reasons/route/_retired.py:1`), and
  the pending-deprecation path PS-12 used (engine #587, `2fa09874`: `deprecated_in=UNRELEASED`,
  stamped at 0.25.0 to registry 1.27.0). No second tombstone path.
- Release stamping: `scripts/release/stamp_release.py` rewrites every tracked file under
  `src/decoy_engine/reasons` (`scripts/release/stamp_release.py:401`), so a new `_retired.py`
  is stamped with no tool change.
- Gates: `scripts/release/reason_release_pin.py --check` and
  `scripts/dev/registry_renumber.py --check` (the branch keeps main's registry version and adds
  no numeric identity).
- Sentries already on main: `test_no_tombstone_without_a_live_replacement`,
  `test_identity_set_is_exact`, `check_integrity`.
- CLI: the explain-topic ban list `_REMOVED_FROM_TOPICS`
  (`tests/e2e/first_user/test_items_text.py:91`).

## Established solutions

Search run: in-codebase only (engine `reasons/`, the release scripts, PR #587, PR #610). The
registry has its own written deprecation procedure (`docs/reasons.md:23-27`), modelled on the
append-only identities of protobuf/gRPC status details and RFC 9457 problem types that the
identity module cites (`src/decoy_engine/reasons/_identity.py:5`). That procedure is the
established solution here. No external search: there is no new design to choose.

## Design notes

None: no new structure. One new catalog file copies the `route/_retired.py` pattern. The
replacement link is stored only on the catalog declaration.

## Enumerations

### Exit paths

- Engine: no code path emits these reasons. There is no producer in `src/`; the only references
  are the declarations at `src/decoy_engine/reasons/platform/_part1.py:72` to `:74` and `:239`,
  `:244`, `:325`. The slice adds and removes no exit path.
- CLI: `decoy explain yaml` (`src/decoy/cli/explain.py:140`, CLI repo) is the only path the row
  names. It exits 0, and AT-C1 pins its text.

### Routes

N/A: reason tombstones do not change routing. No route reason changes, and
`src/decoy_engine/reasons/route/_retired.py:1` is read only as the pattern.

### FK shapes

N/A: no data is read or written. The change is catalog metadata only.

### Fields

- `deprecated_in`: `None` to `UNRELEASED` on the three entries
  (`src/decoy_engine/reasons/_types.py:97`).
- `replaced_by`: `None` to a live `platform` identity on the three entries
  (`src/decoy_engine/reasons/_types.py:98`).
- Every other manifest field of the three entries stays the same. AT-E3 checks it.

### Output surfaces

- `reasons.manifest()` and `reasons.find` / `reasons.get` (engine public API): show the
  deprecation.
- The tombstone sentence at `docs/reasons.md:27` and one `changelog.d/` fragment
  (`### Deprecated`).
- CLI `decoy explain` topics: no change; guarded by AT-C1 and AT-C2.
- CLI `decoy ci` SARIF allowlist (`src/decoy/ci/rule_codes.py:200`, CLI repo): no change; it keeps
  tombstones by design.

## Defect classes

| # | Class | Applies | Closing structure | Guard and mutation |
|---|---|---|---|---|
| 1 | value-free text | N/A: the summaries are unchanged shipped text, already checked by `test_summaries_are_value_free` | - | - |
| 2 | cleanup on failure | N/A: no runtime path, so nothing to clean up | - | - |
| 3 | state transitions | N/A: no state machine changes; job states stay with the platform | - | - |
| 4 | route coverage | N/A: no route reason or route decision changes | - | - |
| 5 | referential integrity of `replaced_by` | yes | `check_integrity` and the live-replacement sentry | AT-E1, AT-E5; mutation M2b points one link at `platform/no_such_code` |
| 6 | untrusted input | N/A: no new input is parsed; `parse_payload` does not change | - | AT-E4 keeps the decode guarded |
| 7 | TOCTOU or check-then-use | N/A: no filesystem or concurrent access | - | - |
| 8 | weak test | yes | AT-E1 compares the exact `(deprecated_in, replaced_by)` per code, written as literals | mutations M1 and M2 must turn it red |
| 9 | refactor (move to `_retired.py`) | yes | owners and symbols kept; identity-set test and release pin | `test_identity_set_is_exact`, AT-E3; mutation M3 deletes one declaration |
| 10 | frozen contract (release pin) | yes | only the two waivable pending fields change | `reason_release_pin.py --check`; mutation M4 types `deprecated_in="1.29.0"` |

## Acceptance tests

Engine. All tests go in `tests/unit/safe_output/test_platform_reasons.py`, the owning test file;
AT-E6 and AT-E7 are gate commands.

| Id | Test | Fails on main because | Mutation that must turn it red |
|---|---|---|---|
| AT-E1 | `test_workflow_codes_are_tombstones`: for each of the three codes, `(spec.deprecated_in, spec.replaced_by)` equals `(UNRELEASED, ("platform", <replacement>))`, the replacement written as a literal; the replacement spec has `deprecated_in is None` | both fields are `None` | M1 drop `deprecated_in` from one; M2 swap `job_failed` and `job_cancelled` |
| AT-E2 | `test_workflow_tombstones_still_resolve`: `reasons.find` returns a spec and `reasons.platform.WORKFLOW_*` equals the code, for all three | passes on main (guard for "never deleted") | M3 delete the `WORKFLOW_STEP_FAILED` declaration |
| AT-E3 | `test_workflow_tombstones_change_only_the_deprecation`: the three manifest entries equal their main-time values (written as literals) except `deprecated_in` and `replaced_by` | the two fields differ on main | M5 edit one tombstone summary to drop "workflow" |
| AT-E4 | `test_a_record_naming_a_workflow_code_still_decodes`: a `ReasonRecord` payload naming `platform/workflow_step_failed` parses to that identity, not `decoy/unknown_reason_from_future` | passes on main (guard) | M3 |
| AT-E5 | existing `test_no_tombstone_without_a_live_replacement` stays green with three more tombstones | it passes on main with no platform tombstone | M2b link to `platform/no_such_code` |
| AT-E6 | gate: `python scripts/release/reason_release_pin.py --check` exits 0; `--release-ready` exits 1 and names the three `deprecated_in is still unreleased` lines | main has no pending deprecation, so `--release-ready` names none | M4 `deprecated_in="1.29.0"` makes `--check` exit 1 |
| AT-E7 | gate: `python scripts/dev/registry_renumber.py --check` exits 0 | gate only | an identity with `since="1.30.0"` makes it exit 1 |

CLI (`tests/e2e/first_user/test_items_text.py`):

| Id | Test | Fails on main because | Mutation that must turn it red |
|---|---|---|---|
| AT-C1 | add `"cli-yaml-workflows"` to `_REMOVED_FROM_TOPICS`, so every explain topic is checked for the exact row-17 pointer | passes on main (CLI #146 fixed it; this pins the row) | MC1 put the "Full guide in the docs hub" pointer back in the `yaml` topic |
| AT-C2 | `test_explain_topics_name_no_workflow_reason_code`: no topic summary or body contains `workflow_step` or `workflow_restart` (case-insensitive) | passes on main (guard for QA item EXIT-07) | MC2 add "see platform/workflow_step_failed" to any topic body |

AT-E1, AT-E3 and AT-E6 are red first on main. The builder records that run and each named
mutation on the final head (recurring defect 9).

## Placement

| New file | Directory | CODEMAP line that places it | Sits beside |
|---|---|---|---|
| `src/decoy_engine/reasons/platform/_retired.py` | `src/decoy_engine/reasons/platform/` | engine `CODEMAP.md:265`, "Reason codes: one catalog package per namespace" | `platform/_part1.py`; pattern `route/_retired.py` |
| `changelog.d/wf-r-workflow-reason-tombstones.md` | `changelog.d/` | `changelog.d/README.md` (one fragment per behavior PR) | other fragments |

The three declarations move from `_part1.py` (418 lines, about 18 fewer after) to `_retired.py`.
`platform/__init__.py` adds `from decoy_engine.reasons.platform._retired import *  # noqa: F403`.
The CLI slice adds no file.

## Frozen contracts

- Reason registry and release pin: append-only; the slice uses only the declared pending
  deprecation edit. It does not edit `REGISTRY_VERSION`, the minor fixtures,
  `consumer-contract.json` or `reason-registry-release.json`. No cap, pin, baseline or allowlist
  moves.
- `reasons.platform` public symbols: all three stay exported, from the `_retired.py` `__all__`.
- CLI explain topic text: no change.

## Slices

| Slice | Repo | Content | Size | Risk | After |
|---|---|---|---|---|---|
| WFR-E1 | engine | move the three declarations to `platform/_retired.py` with `deprecated_in=UNRELEASED` and `replaced_by`; remove them from the `_part1.py` `__all__`; import `_retired` in `platform/__init__.py`; AT-E1 to AT-E4; the tombstone sentence in `docs/reasons.md:27`; one `### Deprecated` fragment naming the three identities as `` `platform/<code>` `` | about 5 files, 90 lines; no new public names | R1 | none; registry order: merges alone in the registry queue and rebases over PR #610 if that lands first |
| WFR-C1 | CLI | AT-C1 and AT-C2; roadmap row 17 to DONE with both PR numbers | 2 files, about 20 lines; tests and docs only | R1 | WFR-E1 merged, only so the row can cite it; needs no engine release |

Engine release: WFR-E1 ships in the first engine release after it merges (expected `0.28.0` on
the daily train). Release prep stamps the three `deprecated_in` values and takes the next
registry patch (`1.29.1`), or the next minor if that release also adds identities. The CLI slice
needs no engine release: no CLI code reads these three codes, and the routine repin picks up the
tombstones.

Gates: one reviewer each (Codex), as R1 requires. T1 for WFR-E1: `tests/unit/safe_output/`,
`tests/unit/test_reason_registry.py`, `tests/unit/test_reason_release_pin.py`,
`tests/unit/test_shipped_reason_identities.py` (or `tests/unit/test_reason_tombstones.py` after
#610), `tests/sentry/test_reason_*`, plus AT-E6 and AT-E7. No full-suite trigger fires: no
serialization or frozen-contract code changes, and the registry edit is the declared pending
edit. T1 for WFR-C1: `tests/e2e/first_user/test_items_text.py`.

## Pre-mortem

- The pin check refuses the move because `owner` changed (F3). The builder compares
  `reasons.manifest()` before and after and expects exactly six field changes.
- PR #610 merges first and moves the sentry: AT-E5 then lives in
  `tests/unit/test_reason_tombstones.py`. This plan's code does not change.
- A reviewer asks for new summaries without "workflow": outside the guarantee (non-goal). A
  tombstone keeps shipped text, as in `route/_retired.py`.
- A reviewer asks to delete instead: row 17 says never deleted. The PR #610 deletion was a
  one-time owner exception for the STORM names only.
- `--release-ready` exits 1 on main after the merge: expected until release prep, as after PS-12.

## Owner questions (answered under standing approval, go-with-recommended)

- Q1. Which live identity does each tombstone point at? Recommended and taken: `startup_failed`,
  `job_cancelled`, `job_failed`. Each has the same kind and outcome; `job_failed` differs only in
  owner (`PlatformJobLog`, not `PlatformResponse`). Alternative for `workflow_step_failed`:
  `pipeline_error`.
- Q2. Move the declarations to `platform/_retired.py`, or mark them where they are? Recommended
  and taken: move, to match `route/_retired.py`, so every tombstone is in a `_retired.py` file.

## Unresolved

- Nothing blocks. The platform backend WF-R row removes the workflow runner prose and needs
  nothing from this row.
- QA item EXIT-07 (CLI `docs/qa/cli-v1-checklist.md:412`) is still run by QA after the CLI
  slice. This plan does not mark it.
