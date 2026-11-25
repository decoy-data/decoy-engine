# F31 AC0: engine release with the safe-output boundary, and the CLI repin

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), testing (test depth, escalation triggers), release-and-rollback,
api-and-compatibility, catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: `docs/plans/2026-11-24-f31-audit.md` (rev 3 on main; rev 2.2 sections "AE1 rev 2"
and "AE1 rev 2.1" on `plan/f31-audit`), slice AC0. Row: CLI `docs/roadmap/groups/health.md`,
F31-AUDIT.

Risk: three gated steps with separate gates.

- Engine release preparation: R2 (Codex and Dennis). The 0.28.4 release commit `19aabbfa9`
  touched 43 files, fragments included, so this is not a small step. The gate reviews the exact
  engine main SHA that the publication step then tags.
- Publication: R3, because a pushed tag is not withdrawn. Before the owner authorizes it, the PR
  body records the tested recovery: `cut-release.sh` run without `APPLY` on the gated SHA (a dry
  run that passes every check), and the recovery path for a bad `<V>` (a patch release `<V>+1`
  and a revert of the CLI repin commit). The dry run covers preflight only, and `:117` to `:120`
  tag locally, push, then read the tag back. So the publication step is also rehearsed with
  `APPLY=1` against a disposable bare remote for two outcomes: a failed push (the local tag is
  left and blocks a retry: delete it, then retry) and a failed readback after a good push
  (check the remote tag's peeled SHA with `git ls-remote <remote> refs/tags/v<V>^{}` before any
  retry). The PR body records both. Publication is
  `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`. The default invocation stops after
  the dry run and exits 0 (`cut-release.sh:111` to `:118`), so a run without `APPLY=1` is not a
  publication.
- CLI repin: R1 (Codex). It hits two full-suite triggers (dependency lock, shared test fixture),
  so the gate runs the full CLI suite on the repin head and on the CLI base SHA in the same
  environment.

Bases: engine main `2b8a47fbe` (0.28.4 released as `v0.28.4`, commit `19aabbfa9`). CLI main
`d6b9e4c7`, which pins `decoy-engine==0.28.3`. CLI PR #408 (pin 0.28.4) is open. AC0 starts
from whatever pin CLI main holds when it starts.

## Guarantee and non-goals

Guarantee:

1. One engine release `<V>` exists whose tag contains every engine slice the CLI F31 slices
   need: AE1a1, AE1a2, AE1b, AE1c1, AE1c2 (one stack), AE3, AE4, AE5, and the completed AE6
   translator fix (`63c63c950` on `feat/f31-ae6`, or its equivalent), where both native
   translators call `generation/pool/_errors.py:119` through the public API. The earlier
   `0ea90f559` still builds the admission error at `_crypto_ext.py:381` and `_index_ext.py:113`
   and is not enough. `<V>` is the next minor (expected
   0.29.0) because the release adds public names. AE5 is in the tag for the engine raise texts it
   rewrites, which AC1 renders against the installed engine, so there is one repin, not two. The
   AE6 fix is in the tag because `execution/native/_crypto_ext.py:379` and `_index_ext.py:111`
   copy Arrow type details into `GenerationError.message`, and those details can carry a
   metadata value even when the field name is clean. The amended parent (`plan/f31-audit`,
   "Effect on later slices") replaces the registry share table with the `SafeText` share, so AC0
   does not gate on `registry_share.py`; AE5 hands AC1 its `SafeText` share report instead.
2. The release exports one public strict-check entry: a context manager
   `decoy_engine.safe_output.strict_checks()` and a reader `strict_checks_enabled()`. The engine
   test fixture (`tests/conftest.py:117` on `feat/f31-ae1a1-safe-text`) uses them, so the
   lifecycle has one owner. If no AE slice adds them first, the engine release preparation adds
   them, with their own tests, and moves the engine fixture onto them. The engine fixture keeps
   its per-site warning reset (`_safe_text._warned.clear()`, `tests/conftest.py:122` on
   `feat/f31-ae1a1-safe-text`) when it delegates the switch to `strict_checks()`; without it,
   `tests/unit/test_safe_text.py:78` can consume the warning that `:89` expects.
   The release also exports two typed operations AC1 needs, added the same way if no AE slice
   adds them. Both live in `safe_output`, not in `reasons`: `reasons` sits below `safe_output`
   in the engine layer map (`.importlinter:24` to `:26`), and the amended AE1 plan keeps the
   mint inside the renderer. They reuse the renderer's existing typed paths
   (`safe_output/_render.py:221` to `:223` for coded text, `:248` to `:249` for labels) and the
   registry lookup:
   - `safe_output.safe_error_label(exc) -> SafeText`: the closed label that `safe_error_type`
     returns as a `SafeErrorType` enum (`safe_output/_exception.py:79` to `:89`);
   - `safe_output.safe_reason_summary(namespace, code) -> SafeText | None`: the registered
     summary of a reason code, or `None` for an unknown reason, which is the outcome AC1's local
     fallback keys on.
   Each has engine tests for a known and an unknown input.
3. The CLI pins `decoy-engine==<V>` in every place the 0.28.3 repin (#383) and the 0.28.4 repin
   (#408) moved, in one commit.
   The certified profile moves too: the DP fingerprint hash in `requirements-certified.txt:8`
   is restamped for the exact CLI version and closure.
4. The CLI test session runs with strict checks on, through one autouse fixture in
   `tests/conftest.py` that enters `strict_checks()`, so a failed literal check raises in CLI
   tests the same way it does in engine tests. The CLI imports no private engine name.
5. The public names the later AC slices use import from `decoy_engine.safe_output` at the pin.

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
| AE1a1 to AE1c2, AE3, AE4, AE5 and the AE6 translator fix are on engine main | `git merge-base --is-ancestor <merge> <release SHA>` for each merge commit; the AE1b to AE1c2 stack merged into main, not a non-main base |
| Each slice's behavior holds at the release SHA | run, at the release SHA, the behavior tests each slice owns: the AE3 handler filter test (removing `handler.addFilter(...)` at `internal/logging.py:29` must fail it), the AE4 copy ratchet (`636c1b3fb`, #794), the AE1c2 producer tests, the AE5 raise-copy test `tests/security/test_f31_raise_copies.py`, the AE5 loader-refusal tests the AE5 amendment names (its lines 480 to 482 and 815 to 818, which catch a loader echoing `corpus_source_version` list values into `str(exc)`), `tests/sentry/defects/test_config_refusal_text.py`, and `tests/unit/test_safe_text.py` run whole and in file order (the `:78` then `:89` pair proves the warning reset). An import check alone does not prove these |
| The native value leak is closed at the release SHA | with the native companion installed, run `tests/native/f31_canary/test_native_canary.py:359`, both compiled-wrapper cases at `:402` (on `feat/f31-ae6`) and both translator metadata cases. A skip counts as a failure: the gate reads the pytest summary and stops on any skip in these ids |
| No tag sits between AE1b and AE1c2 | `git tag --contains <AE1b merge>` lists no tag that lacks AE1c2 |
| `strict_checks()`, `strict_checks_enabled()`, `safe_error_label` and `safe_reason_summary` are public | each is in its package's `__all__`; else the release preparation adds them (guarantee 2) |
| `_CLI_REGISTRAR` names the module AC1 creates | open item 1 |

## Steps

1. Engine release preparation, following `reg-release.md` and the 0.28.4 release commit
   `19aabbfa9` (43 files): `release.py` version, CHANGELOG section and fragments, reason manifest
   and registry release fixtures, changelog breaking-ratchet fixture, `uv.lock`, and the strict
   entry of guarantee 2 if it is missing. Stamp the certified DP row for the exact CLI version
   and closure with `scripts/release/stamp_release.py:22` to `:26`. Gate this SHA at R2.
2. Dry run `scripts/release/cut-release.sh <gated-main-SHA>` and record its output with the
   recovery path (Risk). Then owner authorization, then
   `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`, which pushes tag `v<V>`.
3. CLI repin, one commit, every location in "Enumerations, Fields" below. Before editing,
   `git grep -n "0\.28\.[34]"` on CLI main lists every hit; each hit moves, or the PR body names
   it as history that stays (dated plans, `docs/roadmap/decisions.md`). The version grep misses
   the certified hash, so `requirements-certified.txt:8` and its header move from the stamp of
   step 1. Regenerate the SHA-pinned dev lock with `scripts/dev/lock.sh` and run its `--check`.
4. CLI `tests/conftest.py`: one autouse function-scoped fixture that enters
   `decoy_engine.safe_output.strict_checks()`. The engine owns save and restore.
5. CLI `docs/roadmap/groups/health.md`: the F31-AUDIT row still points at rev 9 (`2340a45b`)
   and says NOT STARTED. Point it at engine `docs/plans/2026-11-24-f31-audit.md` and list the AC
   slices.

`tests/sentry/test_engine_import_surface.py` needs no edit: it derives the CLI's engine names
from CLI source by AST, so it starts resolving the new names when AC1 and AC2 import them.

## Class table

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | N/A: AC0 changes no output; the engine boundary ships in the release and AC1 to AC4 use it | | | |
| 2 | cleanup on an exit path | N/A: no resource is opened | | | |
| 3 | state and concurrency | yes, narrow: the strict switch is process state | one engine-owned context manager saves and restores it; the CLI fixture only enters it | AT-3 runs a strict test through `pytest.main()` in an isolated interpreter and checks the switch after pytest returns | M2: drop the restore in `strict_checks()` |
| 4 | route parity and fallback | yes: three install routes (dev lock, certified pins, release smoke) | one pin value moved in every route in one commit; the certified hash restamped | AT-1, AT-2, `scripts/cert_smoke.py:59` to `:82`, the runtime-only fit at `.github/workflows/ci.yml:327` to `:328` | M1: leave `scripts/dev/lock_version.sh` at the old tag |
| 5 | referential integrity | N/A: no table data | | | |
| 6 | untrusted producer | N/A: no new input | | | |
| 7 | check then use on a path | N/A: no path checks | | | |
| 8 | weak tests and overclaimed evidence | yes: a repin can hide a new failing id, and an import check can pass without a slice's behavior | full suite on the repin head and the CLI base SHA in one environment; every new id resolved; slice behavior tests run at the release SHA | AT-4, preconditions | M3: remove the AE3 `addFilter` call at the release SHA; the AE3 filter test fails |
| 9 | refactor drift | N/A: no refactor | | | |
| 10 | frozen contract drift | yes: the engine pin is a frozen CLI contract | the pin moves only through the repin commit, and the CHANGELOG names it | `test_pyproject_metadata.py`, AT-1 | M1 |

## Enumerations

Read from CLI `d6b9e4c7`.

### Exit paths

- Release cut stops before the tag (a precondition fails, the R2 gate is not GO, or the owner
  does not authorize): no tag, no repin.
- Repin CI fails on a pin test (`tests/unit/release/test_launch_pin_check.py:21` names the tag)
  or on `scripts/cert_smoke.py` (hash or certified row mismatch).
- Repin full suite shows a new failing id against the CLI base SHA: the repin does not merge
  until the id is resolved (see AT-4).

### Routes

- Dev install: `scripts/dev/lock_version.sh:17`, `scripts/dev/bootstrap.sh:32`,
  `requirements-dev.lock`.
- Certified install: `requirements-certified.txt:5`, `:8` (DP fingerprint hash), `:25`, the CI
  leg at `.github/workflows/ci.yml:322`, and the runtime-only fit at `:327` to `:328`.
  `scripts/cert_smoke.py:59` to `:82` checks the hash and the engine's certified row; it is the
  certified-profile check.
- Release smoke: `.github/workflows/release-smoke.yml:79` to `:88` installs the wheel under the
  dev lock, or runs the weekly unconstrained install. `scripts/cert_smoke.py:8` names the pin.

### FK shapes

N/A: no table data.

### Fields

Pin locations on CLI `d6b9e4c7`:

- `pyproject.toml:148`, `:152`, `:153`; `requirements-certified.txt:8` and its header;
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
- `decoy-vm-t3` for the full suite on the repin head and on the CLI base SHA.
- The existing central pin guard `tests/sentry/test_ci_lock_installs.py:283` to `:289` (every
  engine URL equals `--engine-spec`, and the tag equals the pyproject pin).
- `scripts/release/stamp_release.py`, `scripts/release/cut-release.sh`, `scripts/dev/lock.sh`.

## Frozen contracts touched

The engine pin (additive move to a newer minor). No CLI JSON key, exit code or command changes.
`decoy-error-v1` keys are unchanged.

## Behavior

- CLI output is unchanged except where the engine release changes engine text (listed in the
  engine CHANGELOG under F31).
- A CLI test that triggers a failed engine SafeText literal check now fails with `TypeError`
  instead of passing with a withheld message. Outside the test session nothing changes: a
  production run stays non-strict and gets `WITHHELD`.
- If CLI main still pins 0.28.3 when AC0 starts, the repin also carries the 0.28.4 changes that
  #408 made: the import fix for `tests/unit/test_sources_dialect.py:10` (it imports the removed
  `VALIDATION_CODES`, which breaks collection), and the change at
  `tests/e2e/test_run_chunked.py:150` from `EXIT_USAGE` to a successful chunked run whose output
  matches the plain run byte for byte.

## Failure modes

| Failure | Detected by |
|---|---|
| A pin location left at the old version | the `git grep` list in the PR body; `test_ci_lock_installs.py:283`; `test_launch_pin_check`, `test_pyproject_metadata`; release-smoke workflow |
| The certified hash left at the old closure | `scripts/cert_smoke.py`; the runtime-only fit in CI |
| The release lacks one F31 slice, or a slice's behavior | ancestor check and slice behavior tests at the release SHA (preconditions); AT-1 for the installed names |
| A failed SafeText check inside a CLI flow | the strict fixture turns it into a CLI test failure (AT-3) |
| The strict switch leaks into a subprocess test | the engine switch is pid-bound; a subprocess runs non-strict, as in production |
| A divergence unrelated to F31 | the repin does not merge; the divergence goes back to the engine as a fix or is shown to be an intentional engine change with its own test (AT-4) |

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/sentry/release/test_engine_f31_surface.py` (new, CLI): import `SafeText`, `SafeName`, `SafePath`, `WITHHELD`, `render_failure`, `safe_text_of`, `register_mint_callers`, `SafeRecordFilter`, `strict_checks`, `strict_checks_enabled`, `safe_error_label` and `safe_reason_summary` from `decoy_engine.safe_output`. Public imports only; the installed version and commit are checked by `scripts/dev/bootstrap.sh --check` (AT-2), and slice behavior at the release SHA (preconditions) | red on CLI main (0.28.3 lacks the names) |
| AT-2 | `scripts/dev/bootstrap.sh --check` in the repin environment (it compares the installed distribution with the pyproject pin and its commit with the lock, `bootstrap.sh:35`, `:73` to `:94`), the central guard `tests/sentry/test_ci_lock_installs.py:283` to `:289`, `test_launch_pin_check.py`, `test_pyproject_metadata.py` and `scripts/dev/lock.sh --check` at `<V>`. The negative control in `test_launch_pin_check.py:55` to `:57` uses `v0.29.0` as the wrong tag; it changes to a tag derived as one patch above `<V>`, so it can never equal the pin | M1: leave `scripts/dev/lock_version.sh` at the old tag; the central guard fails |
| AT-3 | `tests/sentry/tooling/test_strict_fixture.py` (new, CLI): (a) under the autouse fixture, `SafeText.const` on a runtime-built string raises `TypeError`; (b) a subprocess runs `python -I -c` that calls `pytest.main()` on test (a) alone and asserts its return code is 0 with exactly one passed test (a pytest plugin object passed to `pytest.main` counts the reports), so a collection error or an early exit cannot pass. Only then, in that same interpreter after pytest returns, it calls `SafeText.const` on a runtime-built string and asserts it returns `WITHHELD` and `strict_checks_enabled()` is false | red-first: (a) fails before step 4. M2: drop the restore in `strict_checks()` in an engine checkout installed editable in a scratch venv; the child prints `decoy_engine.__file__` and the engine commit, the PR body records both, and (b) fails |
| AT-4 | full CLI suite on the repin head and on the CLI base SHA, on the same host, each in its own venv built from its own lock (`decoy-vm-t3` once per SHA, not the `gates.sh` baseline mode, which reuses the branch venv and lock at `gates.sh:286` and `:330`). The evidence records the installed engine version and commit for each run, so an engine regression cannot fail on both and look pre-existing. Each id that fails on the head and passes on the base is resolved before merge: a fix, or a text assertion updated to an engine change named in the engine CHANGELOG under F31 (or the 0.28.4 changes of #408) with the engine test that pins it. Collection must succeed on both SHAs with zero collection errors before ids are compared. Every test the repin adds must pass, though it has no base result. No id is merged as "listed for the owner" | gate evidence |

M1 and M2 run on the final repin head and M3 on the release SHA; the PR bodies record those
heads and, for M2, the mutated engine commit.

## Rollback

The repin is one CLI commit; revert it to return to the old pin. The engine release is a tag; it
is not withdrawn. A defect in `<V>` is fixed by a patch release and a second repin.

## Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_engine_f31_surface.py` | CLI `tests/sentry/release/` | `CODEMAP.md:73`: guards of a contract go under `tests/sentry/`; this one guards the release contract | `test_release_identity_sentry.py` |
| `test_strict_fixture.py` | CLI `tests/sentry/tooling/` | `CODEMAP.md:73`; it guards the pytest tooling (the strict fixture) | `test_pytest_timeout.py` |

Both are found by the sentry manifest's glob over `tests/sentry/` (`test_sentry_manifest.py:36`
to `:40`), so they run in the gate's sentry step with no registry entry.

## Size

Engine: the release preparation, about 43 files as in `19aabbfa9` (mostly fixtures and
fragments), plus about 100 lines for `strict_checks()`, `strict_checks_enabled()`, the two typed operations and their tests
if no AE slice added them. CLI: about 24 files, about 70 changed lines plus lock churn, and two
new test files of about 40 and 60 lines. No new public names in the CLI.

## Slices

Two gated units, in order:

1. Engine release preparation (engine, R2, about 43 files).
2. Publication (R3): dry run and recovery recorded, owner authorization, then
   `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`.
3. CLI repin PR (CLI, R1, about 24 files).

## Design notes

The strict lifecycle has one owner, the engine's `strict_checks()`. Both repos' fixtures only
enter it, so a change to the flag's storage cannot leave one repo's fixture restoring the wrong
thing.

## Recurring defect checks (dev-rules catalog)

| Id | Class | Applies | Check |
|---|---|---|---|
| D1 | anchored validation | no | no validator added |
| D2 | strict types | no | no model added |
| D3 | exception context | no | no error raised |
| D4 | versioned read models | indirectly | the reason manifest fixture moves with the release; the CLI reads reasons only through the public adapter |
| D5 | normalized scanners | no | no scanner added |
| D6 | private-module imports | yes | the CLI imports only `decoy_engine.safe_output` public names; no `_safe_text` import |
| D7 | hidden CI failures | yes | the moved workflow lines add no `continue-on-error` or narrowed install; release smoke keeps its two routes (`release-smoke.yml:79` to `:88`) and `scripts/cert_smoke.py` stays a required check |
| D8 | one trust class per entry | no | |
| D9 | mutations on final head | yes | M1 and M2 rerun on the final repin head; head recorded |
| D10 | allowlisted helpers | no | |
| D11 | no raised caps | yes | the repin moves no ratchet baseline; a baseline that must move because of the engine is listed for the owner |

## Pre-mortem

1. A pin location outside the #383 list (a new doc since): the `git grep` step lists it.
2. The strict fixture turns a CLI test red that hides a real engine F31 producer gap: that is a
   finding for the engine, recorded and routed to AE1c2 or AE5b, not silenced in the CLI.
3. The release misses AE3, or carries it with the filter call removed: the ancestor check and
   the AE3 filter test at the release SHA (M3).
4. A later repin forgets the fixture: it lives in `tests/conftest.py`, not in the pin list.
5. The certified hash is not restamped and only weekly smoke notices: `cert_smoke.py` runs on
   the repin PR.
6. The native canary skips because the companion is missing, and the native type-text leak
   ships: a skip in those ids fails the precondition.

## Open items

1. `_CLI_REGISTRAR` (AE1a2) is an engine constant that names one CLI module. AC1 proposes
   `decoy._safe_mints`. AE1a2 must use that name, or AC1 follows AE1a2's name. Check before the
   release is cut; a rename needs another release.
2. The names `safe_error_label` and `safe_reason_summary` are proposals from the AC1 plan. The
   engine owner confirms them, or AC1 follows the names an AE slice ships, before the release is
   cut.

## Unverified

- The release version `<V>`: 0.29.0 assumes no other engine release lands first.
- Whether an AE slice adds `strict_checks()` before the release preparation; if not, it adds
  them.
- The AE6 canary and translator test ids are cited from `feat/f31-ae6` (`0ea90f559`); the
  builder confirms them on the merged commit.
- The CLI lines cited from `.github/workflows/ci.yml`, `release-smoke.yml`,
  `requirements-certified.txt` and `scripts/cert_smoke.py` come from the round-1 review; the
  builder confirms them on the CLI head it starts from.
- Which CLI tests change with the release: known only after the full suite runs on the repin
  head.

## V2-LOG

None.
