# F31 AC0: engine release with the safe-output boundary, and the CLI repin

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), testing (test depth, escalation triggers), release-and-rollback,
api-and-compatibility, catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: `docs/plans/2026-11-24-f31-audit.md` (rev 3 on main; rev 2.2 sections "AE1 rev 2"
and "AE1 rev 2.1" on `plan/f31-audit`), slice AC0. Row: CLI `docs/roadmap/groups/health.md`,
F31-AUDIT.

Risk: R1. The slice adds no logic. It cuts an engine release from slices that already passed
their own gates, and moves the CLI pin. The CLI repin hits two full-suite triggers (dependency
lock, shared test fixture), so the gate runs the full CLI suite against the saved main baseline.
One reviewer (Codex).

Bases: engine main `2b8a47fbe` (0.28.4 released as `v0.28.4`, commit `19aabbfa9`). CLI main
`d6b9e4c7`, which pins `decoy-engine==0.28.3`. CLI PR #408 (pin 0.28.4) is open. AC0 starts
from whatever pin CLI main holds when it starts.

## Guarantee and non-goals

Guarantee:

1. One engine release `<V>` exists whose tag contains every engine slice the CLI F31 slices
   need: AE1a1, AE1a2, AE1b, AE1c1, AE1c2 (one stack), AE3 and AE4. `<V>` is the next minor
   (expected 0.29.0) because the release adds public names.
2. The CLI pins `decoy-engine==<V>` in every place the 0.28.3 repin (#383) and the 0.28.4 repin
   (#408) moved, in one commit.
3. The CLI test session runs with the engine's SafeText strict switch on, through one autouse
   fixture in `tests/conftest.py`, so a failed literal check raises in CLI tests the same way it
   does in engine tests.
4. The public names the later AC slices use import from `decoy_engine.safe_output` at the pin.

Non-goals: no CLI source change that uses `SafeText`, `render_failure` or `SafeRecordFilter`
(AC1 and AC2). No CLI behavior change beyond what the engine release changes by itself. A CLI
test that fails because the engine changed its text is fixed in AC0 only when the change is the
engine's documented F31 behavior (a type label or a registry summary where copied exception text
was). Any other divergence is recorded for the owner, as #408 did.

## Established solutions

Search run: the engine release runbook (`docs/plans/reg-release.md`), the 0.28.4 release commit
`19aabbfa9`, CLI repin commits #383 (`0ca02653`) and #408, the engine repin checklist (vault
memory `engine-repin-checklist`), and the pytest documentation on autouse fixtures in a root
`conftest.py`. The design copies the existing repin pattern: one commit moves every pin
location, listed in the PR body. Nothing new is built.

## Preconditions (checked before the release is cut)

| Check | How |
|---|---|
| AE1a1 to AE1c2, AE3 and AE4 are on engine main | `git log origin/main` shows each merge; the AE1b to AE1c2 stack merged into main, not a non-main base |
| No tag sits between AE1b and AE1c2 | `git tag --contains <AE1b merge>` lists no tag that lacks AE1c2 |
| AE5 status recorded | Recommended: wait for AE5 when it is within one day of merge, so AC1 needs no second repin. If AE5 is later, AC1 needs a second release and repin; the AC0 PR says so |
| The strict switch has a public test entry | open item 1 |
| `_CLI_REGISTRAR` names the module AC1 creates | open item 2 |

## Steps

1. Engine release `<V>`, following `reg-release.md` and the 0.28.4 release commit:
   `release.py` version, CHANGELOG section, reason manifest and registry release fixtures,
   changelog breaking-ratchet fixture, `uv.lock`. Tag `v<V>`.
2. CLI repin, one commit, every location in "Enumerations, Fields" below. Before editing,
   `git grep -n "0\.28\.[34]"` on CLI main lists every hit; each hit moves, or the PR body names
   it as history that stays (dated plans, `docs/roadmap/decisions.md`).
3. CLI `tests/conftest.py`: one autouse function-scoped fixture that turns the strict switch on
   and restores the earlier value, the same shape as the engine fixture
   (`tests/conftest.py:117` on `feat/f31-ae1a1-safe-text`).
4. CLI `docs/roadmap/groups/health.md`: the F31-AUDIT row still points at rev 9 (`2340a45b`)
   and says NOT STARTED. Point it at engine `docs/plans/2026-11-24-f31-audit.md` and list the AC
   slices.

`tests/sentry/test_engine_import_surface.py` needs no edit: it derives the CLI's engine names
from CLI source by AST, so it starts resolving the new names when AC1 and AC2 import them.

## Class table

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | N/A: AC0 changes no output; the engine boundary ships in the release and AC1 to AC4 use it | | | |
| 2 | cleanup on an exit path | N/A: no resource is opened | | | |
| 3 | state and concurrency | yes, narrow: the strict switch is process state | the fixture restores the earlier value; the engine flag is pid-bound, so a forked or spawned child runs non-strict | AT-3, and a second test in the same module that sees the switch off after the fixture exits | M2: drop the restore |
| 4 | route parity and fallback | yes: three install routes (dev lock, certified pins, release smoke) | one pin value moved in every route in one commit | AT-1, `test_launch_pin_check.py`, release-smoke workflow | M1: leave `scripts/dev/lock_version.sh` at the old tag |
| 5 | referential integrity | N/A: no table data | | | |
| 6 | untrusted producer | N/A: no new input | | | |
| 7 | check then use on a path | N/A: no path checks | | | |
| 8 | weak tests and overclaimed evidence | yes: a repin can hide a new failing id | full suite diffed against the saved main baseline; every new id listed | AT-4 | |
| 9 | refactor drift | N/A: no refactor | | | |
| 10 | frozen contract drift | yes: the engine pin is a frozen CLI contract | the pin moves only through the repin commit, and the CHANGELOG names it | `test_pyproject_metadata.py`, AT-1 | M1 |

## Enumerations

Read from CLI `d6b9e4c7`.

### Exit paths

- Release cut stops before the tag (a precondition fails): no tag, no repin.
- Repin CI fails on a pin test (`tests/unit/release/test_launch_pin_check.py:21` names the tag).
- Repin full suite shows a new failing id: fixed as a documented F31 change, or listed for the
  owner.

### Routes

- Dev install: `scripts/dev/lock_version.sh:17`, `scripts/dev/bootstrap.sh:32`,
  `requirements-dev.lock`.
- Certified install: `requirements-certified.txt:5`, `:25`, and the CI leg at
  `.github/workflows/ci.yml:322`.
- Release smoke: `.github/workflows/release-smoke.yml:88`, `scripts/cert_smoke.py:8`.

### FK shapes

N/A: no table data.

### Fields

Pin locations on CLI `d6b9e4c7`:

- `pyproject.toml:148`, `:152`, `:153`;
- `packaging_tools/candidate.py:9`, `src/decoy/ci/rule_codes.py:214`;
- `LICENSING.md:6`, `README.md:218`, `docs/guides/shape-and-privacy/README.md:10`, `:13`,
  `docs/guides/shape-and-privacy/04-differential-privacy.md:88`,
  `docs/release/fresh-install-smoke.md:47`, `:87`, `:115`;
- `tests/unit/test_pyproject_metadata.py:174`, `:189`,
  `tests/sentry/release/test_retired_name_residual.py:269`,
  `tests/e2e/test_report_vault_command.py:245`, `tests/e2e/test_unmask_command.py:396`;
- `CHANGELOG.md`, `docs/RECENTLY-SHIPPED.md` (new entries).

### Output surfaces

N/A: AC0 changes no CLI output by its own code. Engine text changes reach CLI output through the
pin and are listed in the engine CHANGELOG.

## Reuse inventory

- The repin file list of #383 and #408, and `docs/plans/reg-release.md`.
- The engine strict fixture shape (`tests/conftest.py:117` on `feat/f31-ae1a1-safe-text`).
- `tests/sentry/test_engine_import_surface.py` (unchanged; it derives names by AST).
- `decoy-vm-t3` default mode for the full suite against the saved main baseline.

## Frozen contracts touched

The engine pin (additive move to a newer minor). No CLI JSON key, exit code or command changes.
`decoy-error-v1` keys are unchanged.

## Behavior

- CLI output is unchanged except where the engine release changes engine text (listed in the
  engine CHANGELOG under F31).
- A CLI test that triggers a failed engine SafeText literal check now fails with `TypeError`
  instead of passing with a withheld message.

## Failure modes

| Failure | Detected by |
|---|---|
| A pin location left at the old version | the `git grep` list in the PR body; `test_launch_pin_check`, `test_pyproject_metadata`; release-smoke workflow |
| The release lacks one F31 slice | AT-1 |
| A failed SafeText check inside a CLI flow | the strict fixture turns it into a CLI test failure (AT-3) |
| The strict switch leaks into a subprocess test | the engine switch is pid-bound; a subprocess runs non-strict, as in production |
| A divergence unrelated to F31 | recorded in the PR body for the owner, not fixed in AC0 |

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/unit/release/test_engine_f31_surface.py` (new, CLI): import `SafeText`, `SafeName`, `SafePath`, `render_failure`, `safe_text_of`, `register_mint_callers` and `SafeRecordFilter` from `decoy_engine.safe_output`; assert the installed engine version equals the `pyproject.toml` pin | red on CLI main (0.28.3 lacks the names) |
| AT-2 | `test_launch_pin_check.py` and `test_pyproject_metadata.py` at `<V>` | M1: leave one route at the old tag; the release-smoke or pin test fails |
| AT-3 | `tests/unit/test_strict_fixture.py` (new, CLI): `SafeText.const(name)` with a non-literal `name` raises `TypeError`; a second test checks the switch is off outside the fixture by calling the engine's public read of the switch, if AE1 ships one, else by a subprocess | red-first: fails before step 3. M2: drop the restore line |
| AT-4 | full CLI suite on the repin head against the saved main baseline (`decoy-vm-t3` default mode); every new failing id is fixed as a documented engine F31 change or listed for the owner | gate evidence |

Mutations M1 and M2 run on the final repin head; the PR body records that head.

## Rollback

The repin is one CLI commit; revert it to return to the old pin. The engine release is a tag; it
is not withdrawn. A defect in `<V>` is fixed by a patch release and a second repin.

## Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_engine_f31_surface.py` | CLI `tests/unit/release/` | "Release scripts" row: release tests in `tests/unit/release/` | `test_launch_pin_check.py` |
| `test_strict_fixture.py` | CLI `tests/unit/` | flat unit tests of a shared root fixture | `test_env_flags.py` |

## Size

Engine: the release commit only (about 10 files, mostly fixtures). CLI: about 22 files, about
60 changed lines plus lock churn, and two new test files of about 40 lines each. No new public
names in the CLI.

## Slices

One slice in two repos, in order: the engine release commit and tag (engine, R1, about 10
files), then the CLI repin PR (CLI, R1, about 22 files). The CLI PR is the gated unit.

## Design notes

None: no new structure. The fixture copies the engine fixture's shape.

## Recurring defect checks (dev-rules catalog)

| Id | Class | Applies | Check |
|---|---|---|---|
| D1 | anchored validation | no | no validator added |
| D2 | strict types | no | no model added |
| D3 | exception context | no | no error raised |
| D4 | versioned read models | indirectly | the reason manifest fixture moves with the release; the CLI reads reasons only through the public adapter |
| D5 | normalized scanners | no | no scanner added |
| D6 | private-module imports | yes | the strict switch import (open item 1) |
| D7 | hidden CI failures | yes | the moved workflow lines add no `continue-on-error` or narrowed install; release-smoke keeps `--all-extras` |
| D8 | one trust class per entry | no | |
| D9 | mutations on final head | yes | M1 and M2 rerun on the final repin head; head recorded |
| D10 | allowlisted helpers | no | |
| D11 | no raised caps | yes | the repin moves no ratchet baseline; a baseline that must move because of the engine is listed for the owner |

## Pre-mortem

1. A pin location outside the #383 list (a new doc since): the `git grep` step lists it.
2. The strict fixture turns a CLI test red that hides a real engine F31 producer gap: that is a
   finding for the engine, recorded and routed to AE1c2 or AE5b, not silenced in the CLI.
3. The release misses AE3 because it merged after the tag: AT-1 imports `SafeRecordFilter`.
4. A later repin forgets the fixture: it lives in `tests/conftest.py`, not in the pin list.

## Open items

1. The strict switch is a private flag (`decoy_engine._safe_text._set_strict`). A CLI conftest
   import of it breaks recurring defect D6. Recommended: AE1a2 or AE1b exports a public test
   entry, for example a context manager `decoy_engine.safe_output.strict_checks()`, and the CLI
   fixture uses it. If the release has no public entry, the CLI fixture imports the private
   flag in `tests/conftest.py` only, and the AC0 PR records an owner exception with a removal
   note.
2. `_CLI_REGISTRAR` (AE1a2) is an engine constant that names one CLI module. AC1 proposes
   `decoy._safe_mints`. AE1a2 must use that name, or AC1 follows AE1a2's name. Check before the
   release is cut; a rename needs another release.

## Unverified

- The release version `<V>`: 0.29.0 assumes no other engine release lands first.
- Which CLI tests change with the release: known only after the full suite runs on the repin
  head.

## V2-LOG

None.
