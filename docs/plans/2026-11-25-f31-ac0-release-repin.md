# F31 AC0: engine release with the safe-output boundary, and the CLI repin

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), testing (test depth, escalation triggers), release-and-rollback,
api-and-compatibility, code-review, verification, architecture, cross-cutting-concerns, catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: `docs/plans/2026-11-24-f31-audit.md` (rev 3 on main; rev 2.2 sections "AE1 rev 2"
and "AE1 rev 2.1" on `plan/f31-audit`), slice AC0. Row: CLI `docs/roadmap/groups/health.md`,
F31-AUDIT.

Risk: three gated steps with separate gates.

- Engine release preparation: R2 (Codex and Dennis). The 0.28.4 release commit `19aabbfa9`
  touched 43 files, fragments included, so this is not a small step. The gate reviews the exact
  engine main SHA that the publication step then tags.
- Publication: R3, because a pushed tag is not withdrawn. Before the owner authorizes it, the PR
  body records a successful dry run with `APPLY=0` on clean main and both disposable-remote
  rehearsals in Rollback. Obtain owner authorization for the full 40-hex gated main SHA
  immediately before `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`.
- CLI repin: R1 (Codex). It hits two full-suite triggers (dependency lock, shared test fixture),
  so AT-4 requires complete base and head results on the same host with each tree’s own lock.

Bases: engine main `2b8a47fbe` (0.28.4 released as `v0.28.4`, commit `19aabbfa9`). CLI main
`d6b9e4c7`, which pins `decoy-engine==0.28.3`. The plan also covers the 0.28.4 repin proposed in CLI PR #408. AC0 starts
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
   Route both public operations and the renderer through the same internal conversions.
   Keep exact-type classification in `safe_error_type` and pair lookup in public
   `reasons.find(namespace, code)` (`reasons/_registry.py:119`). Under strict checks assert
   the exact SafeText type and displayed text for a builtin exception and an unlisted subclass
   with a marker message (fixed fallback "Exception"). For a registered pair assert its exact
   registry summary without refs. For an unknown pair, including a known code under the wrong
   namespace, assert None. A mutation that mints the exception message or resolves by code
   alone must fail the corresponding case.
3. The CLI pins `decoy-engine==<V>` in every place the 0.28.3 repin (#383) and the 0.28.4 repin
   (#408) moved, in one commit.
   The certified profile moves too: the DP fingerprint hash in `requirements-certified.txt:8`
   is restamped for the exact CLI version and closure.
4. CLI tests run with strict checks on during the function-scoped fixture lifetime, through one autouse fixture in
   `tests/conftest.py` that enters `strict_checks()`, so a failed literal check raises in CLI
   tests the same way it does in engine tests. The CLI fixture imports only public engine names.
5. The public names the later AC slices use import from `decoy_engine.safe_output` at the pin.

Non-goals: no CLI source change that uses `SafeText`, `render_failure` or `SafeRecordFilter`
(AC1 and AC2). No CLI behavior change beyond what the engine release changes by itself. A CLI
test that fails because the engine changed its text is fixed in AC0 only when the change is the
engine's documented F31 behavior (a type label or a registry summary where copied exception text
was). Any other new failure holds the repin under AT-4, with the documented #408 carry-forward covered in Behavior.

## Established solutions

Search run: the engine release runbook (`docs/plans/reg-release.md`), the 0.28.4 release commit
`19aabbfa9`, CLI repin commits #383 (`0ca02653`) and #408, the engine repin checklist (vault
memory `engine-repin-checklist`), and the pytest documentation on autouse fixtures in a root
`conftest.py`. The design copies the existing repin pattern: one commit moves every pin
location, listed in the PR body. AC0 adds contract tests and any missing engine operations in guarantee 2.

## Preconditions (checked before the release is cut)

| Check | How |
|---|---|
| AE1a1 to AE1c2, AE3, AE4, AE5 and the AE6 translator fix are on engine main | `git merge-base --is-ancestor <merge> <release SHA>` for each landed main commit (use the main-side SHA for a squash merge); the AE1b to AE1c2 stack merged into main, not a non-main base |
| Each slice's behavior holds at the release SHA | run, at the release SHA, the behavior tests each slice owns: the AE3 handler filter test (removing `handler.addFilter(...)` at `internal/logging.py:29` must fail it), the AE4 copy tests (`tests/sentry/safe_output/test_exception_text_copy.py`), live equality in `tests/sentry/test_baseline_registry.py` and the merge-base ratchet, the AE1c2 producer tests, the AE5 raise-copy test `tests/security/test_f31_raise_copies.py`, the AE5 loader-refusal tests the AE5 amendment names (its lines 480 to 482 and 815 to 818, which catch a loader echoing `corpus_source_version` list values into `str(exc)`), `tests/sentry/defects/test_config_refusal_text.py`, and `tests/unit/test_safe_text.py` run whole, serially, in file order (the `:78` then `:89` pair proves the warning reset). An import check alone does not prove these |
| The native value leak is closed at the release SHA | with the native companion installed, run `tests/native/f31_canary/test_native_canary.py:359`, both compiled-wrapper cases at `:402` (on `feat/f31-ae6`) and both translator metadata cases. Use the lock-faithful native environment with the compiled companion built from the release tree. Record its revision, imported binary, ABI and landed node IDs. Require passing calls for each case, including both kernel routes with marker-bearing Arrow metadata on a cleanly named field, expected `GenerationError` and `reasons.runtime.NATIVE_TYPE_NOT_ADMITTED` for the admission cases, and marker absent from message and str(exc). Missing cases, skips, xfails and collection errors hold the cut |
| Producer and renderer contracts hold | Run the landed AE1a1/a2 literal and registration tests, AE1b renderer, AE1c1/c2 producer and AE6 engine canary cases on the release SHA. Map branch references to collected node IDs before running. Require the intended cases to execute and retain the documented AE3 gap separately. Record AE5's share report for AC1. |
| CLI certified profile admits a fit before publication | Run the candidate-wheel rehearsal in step 1 on the final engine SHA. |
| No engine release tag sits between AE1b and AE1c2 | In a full clone with the remote release tags fetched, inspect each version tag containing the landed AE1b SHA. Require the landed AE1c2 SHA to be its ancestor as well, using the peeled commit. An intervening published tag is reported to the owner and preserved |
| `strict_checks()`, `strict_checks_enabled()`, `safe_error_label` and `safe_reason_summary` are public | install the candidate engine wheel in isolation, run the AT-1 import list, check the four operations in `safe_output.__all__` and pass guarantee 2’s behavior tests before tagging |
| `_CLI_REGISTRAR` names the module AC1 creates | open item 1 |

## Steps

1. Engine release preparation, following `reg-release.md` and the 0.28.4 release commit
   `19aabbfa9` (43 files). Commit missing guarantee 2 operations, tests and their changelog
   fragment before stamping. Set engine `pyproject.toml` and `src/decoy_engine/release.py` to
   `<V>`, refresh `uv.lock` and generate `docs/proof-manifest.json` with `scripts/gen_proof_manifest.py`
   in the updated engine environment (version-agreement test).
   In a full clone run `scripts/release/stamp_release.py` with the release interpreter and
   `--version <V> --cli-pins-base <old-file> --cli-pins <candidate-file> --cli-version <CLI-version>`.
   Take the base certified file and CLI version from the intended CLI base SHA. Start with
   the same third-party pins for the candidate. The stamp owns the reason transition, released
   fixtures, CHANGELOG and DP rows. Record the exact candidate pins, CLI version and CLI-profile
   fingerprint from the stamped row.

   Before tagging, rehearse the certified-profile job at the final gated engine SHA. Build a
   scratch CLI wheel with the intended engine pin and CLI version. In a fresh unseeded Linux
   x86-64/glibc CPython 3.10.20 venv install that wheel and the candidate engine by SHA with
   `--no-deps`, then the candidate certified pins. Run `uv pip check` and the CLI's
   `scripts/cert_smoke.py` from a scratch CLI tree carrying the candidate pins and fingerprint
   header. Require hash equality, manifest admission and the successful real DP fit and generation from its snapshot. A changed
   CLI version or closure needs a matching stamped row and rehearsal. Gate the actual engine
   main result at R2, including the full engine suite for the changed lock/shared fixture.
2. Record the dry run and recovery rehearsals. After owner authorization run
   `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`. Record the remote annotated tag
   and peeled commit. Continue only when that commit equals the gated SHA.
3. Start from current CLI main and read its live engine pin. Use fixed-string
   `git grep -n -F` on the old version, tag, locked SHA and certified digest (including its
   displayed short prefix). Record each live match or historical disposition in the PR. Update present-tense consumers in Fields and Routes.
   Preserve dated history and historical assertions. If #408 already landed, retain its fixes.
   If the base advanced, recheck its CLI version and closure against the certified row. Put
   the rehearsed pins and digest in `requirements-certified.txt`, regenerate with
   `scripts/dev/lock.sh` and run its `--check`. Verify the generated engine SHA equals the
   peeled published tag.
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
| 1 | value-bearing output | yes, through the installed engine | closed labels and registry summaries; native translators use one admission error | guarantee 2, loader and native marker cases | restore raw detail in either translator, its metadata case fails |
| 2 | cleanup on an exit path | strict context and partial publication | restore prior state in finally; reconcile tag state in Rollback | AT-3 and disposable push/readback rehearsals | M2 and rejected push |
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
  dev lock, or runs the weekly unconstrained install. The PR runs the constrained wheel route in
  `ci.yml` (fresh-install-smoke). Require its smoke commands to pass on the candidate wheel.

### FK shapes

N/A: no table data.

### Fields

Pin inventory on CLI `d6b9e4c7`. Some matches describe history:

- `pyproject.toml:148`, `:152`, `:153`; `requirements-certified.txt:8` and its header;
- `packaging_tools/candidate.py:9`, `src/decoy/ci/rule_codes.py:214`;
- `LICENSING.md:6`, `README.md:218`, `docs/guides/shape-and-privacy/README.md:10`, `:13`,
  `docs/guides/shape-and-privacy/04-differential-privacy.md:88`,
  `docs/release/fresh-install-smoke.md:47`, `:87`, `:115`;
- `tests/unit/test_pyproject_metadata.py:174`, `:189`,
  preserve the historical manifest floor and its provenance in
  `tests/sentry/release/test_retired_name_residual.py:269` and the earlier engine wording
  described in `tests/e2e/test_report_vault_command.py:245` and `tests/e2e/test_unmask_command.py:396`;
- The route files above, including both workflow URLs, the lock, and
  `tests/unit/release/test_launch_pin_check.py` (positive and negative cases). Point stale
  present-tense version/hash examples in `scripts/cert_smoke.py` at the certified header.
- `CHANGELOG.md`, `docs/RECENTLY-SHIPPED.md` (new entries).

### Output surfaces

- Engine exceptions reach CLI error output. Exercise the loader and native translator refusals
  with marker values, and assert the expected code and nonempty safe text.
- Engine-owned console and file log handlers use the AE3 filter. Exercise both with the
  handler tests on the release SHA. AC1–AC4 own the later CLI rendering changes.

## Reuse inventory

- The repin file list of #383 and #408, and `docs/plans/reg-release.md`.
- The engine strict fixture shape (`tests/conftest.py:117` on `feat/f31-ae1a1-safe-text`).
- `tests/sentry/test_engine_import_surface.py` (unchanged; it derives names by AST).
- `decoy-vm-t3` for the full suite on the repin head and on the CLI base SHA.
- The existing central pin guard `tests/sentry/test_ci_lock_installs.py:283` to `:289` (every
  engine URL equals `--engine-spec`, and the tag equals the pyproject pin).
- `scripts/release/stamp_release.py`, `scripts/release/cut-release.sh`, `scripts/dev/lock.sh`.

## Frozen contracts touched

The engine pin moves to a newer minor. CLI command names, JSON keys and exit-code definitions stay stable. Skipping 0.28.4 also admits the previously refused chunked input in Behavior.
`decoy-error-v1` keys are unchanged.

## Behavior

- The F31 output changes come from the engine release. A CLI that skips 0.28.4 also picks up
  the chunked-run change below.
- A CLI test that triggers a failed engine SafeText literal check now fails with `TypeError`
  instead of passing with a withheld message. Outside the test session nothing changes: a
  production run stays non-strict and gets `WITHHELD`.
- If CLI main still pins 0.28.3 when AC0 starts, the repin also carries the 0.28.4 changes that
  #408 made: the import fix for `tests/unit/test_sources_dialect.py:10` (it imports the removed
  `VALIDATION_CODES`, which breaks collection; read the same symbols from public `decoy_engine.reasons.config`), and the change at
  `tests/e2e/test_run_chunked.py:150` for deterministic faker without explicit pool size.
  Run plain, save and remove its output, then require chunked exit 0 and a new byte-identical file.

## Failure modes

| Failure | Detected by |
|---|---|
| A pin location left at the old version | the `git grep` list in the PR body; `test_ci_lock_installs.py:283`; `test_launch_pin_check`, `test_pyproject_metadata`; release-smoke workflow |
| The certified hash left at the old closure | `scripts/cert_smoke.py`; the runtime-only fit in CI |
| The release lacks one F31 slice, or a slice's behavior | ancestor check and slice behavior tests at the release SHA (preconditions); AT-1 for the installed names |
| A failed SafeText check inside a CLI flow | the strict fixture turns it into a CLI test failure (AT-3) |
| Strict state leaks across a context or process boundary | engine tests assert the prior state after normal and exceptional exits and after a nested context. While strict is active, check that an exec child and, on POSIX, a fork child start non-strict while the parent stays strict |
| A divergence unrelated to F31 | the repin does not merge; the divergence goes back to the engine as a fix or is shown to be an intentional engine change with its own test (AT-4) |

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/sentry/release/test_engine_f31_surface.py` (new, CLI): import `SafeText`, `SafeName`, `SafePath`, `WITHHELD`, `render_failure`, `safe_text_of`, `register_mint_callers`, `SafeRecordFilter`, `strict_checks`, `strict_checks_enabled`, `safe_error_label` and `safe_reason_summary` from `decoy_engine.safe_output`. Public imports only; use the same public import list in the pre-tag check and on the CLI pin, with names resolved under Open items. AT-2 verifies installed identity. The preconditions exercise slice behavior at the release SHA | red on CLI main (0.28.3 lacks the names) |
| AT-2 | `scripts/dev/bootstrap.sh --check` in the repin environment (it compares the installed distribution with the pyproject pin and its commit with the lock, `bootstrap.sh:35`, `:73` to `:94`), the central guard `tests/sentry/test_ci_lock_installs.py:283` to `:289`, equality of the installed PEP 610 commit, generated lock commit and gated peeled tag, the runtime-only certified-profile job, `test_launch_pin_check.py`, `test_pyproject_metadata.py` and `scripts/dev/lock.sh --check` at `<V>`. Also run the real `scripts/release/launch_pin_check.py --engine-tag v<V>` with the locked CLI interpreter. The negative control in `test_launch_pin_check.py:55` to `:57` uses `v0.29.0` as the wrong tag; it changes to a tag derived as one patch above `<V>`, so it can never equal the pin | M1: leave `scripts/dev/lock_version.sh` at the old tag; the central guard fails |
| AT-3 | `tests/sentry/tooling/test_strict_fixture.py` (new, CLI): (a) under the autouse fixture assert the reader is true, a valid literal is accepted and `SafeText.const` on runtime-joined text raises `TypeError`; (b) launch `sys.executable -I -c` with CLI root as cwd and the absolute node ID. Clear inherited pytest selection and parallelism options, and run serially. The child first asserts strict is off, then calls `pytest.main()` on test (a) alone and asserts its return code is 0 with exactly one passed test (a pytest plugin object passed to `pytest.main` counts passing call-phase reports for the selected node ID), so a collection error or an early exit cannot pass. Only then, in that same interpreter after pytest returns, it calls `SafeText.const` on a runtime-built string and asserts it returns `WITHHELD` and `strict_checks_enabled()` is false | red-first: (a) fails before step 4. M2: drop the restore in `strict_checks()` in an engine checkout installed editable in a scratch venv; first pass (b) against an unmodified editable install of the gated engine in that same venv. Verify the child import resolves inside the scratch checkout, record its base SHA and mutation diff, and require (a) to pass and (b) to fail specifically on restoration |
| AT-4 | Compare complete CLI base and final-head outcomes on one host, each bootstrapped from its own lock. Record CLI SHA, lock digest, Python version, worker count, installed engine version/commit and completed reports for both. Require zero collection errors, no aborted run, all new tests passing, and every new failure or error resolved, including base-skipped IDs. Account for disappeared IDs and new skips/xfails that could hide a regression. For renamed cases show the replacement ran. Fix a regression or update an assertion only for documented F31 behavior or the verified #408 changes, preserving code, output and canary checks. | gate evidence |

Use matching stored base evidence when it contains the required provenance and outcomes.
Otherwise run the base with its own bootstrap and `scripts/dev/gates.sh --keep-going --write-baseline <scratch-base.json> tests`,
then the candidate with its own bootstrap and `scripts/dev/gates.sh --keep-going --baseline-file <scratch-base.json> tests` on the
same runner with matching worker counts. Preserve both reports. The VM helper's default
`stored` mode reads a saved baseline and its `legacy` mode shares the candidate venv. Keep
the canonical main baseline intact. Require the normal CLI CI interpreter matrix and the
separate layers step on the final pin. If hosted jobs are unavailable, run their actual
commands in the specified environments and retain the exits and reports.

M1 and M2 run on the final repin head and M3 on the release SHA; the PR bodies record those
heads and the one-line diffs. Run the guarantee 2 and native-detail mutations on scratch
copies of that final engine SHA. Restore each mutation before running the next.

## Rollback

In a disposable full clone with clean `main` and a bare remote holding the gated main SHA,
restrict `RELEASE_REMOTE` and the anchored `EXPECTED_REMOTE_RE` override to that disposable
destination. Use the bare-remote pattern in engine `tests/unit/test_cut_release_script.py:61`.
Reject a tag push with a receive hook. In a separate rehearsal allow the push and fail only
the final readback. Record each nonzero result, then independently run
`git ls-remote --tags <remote> "refs/tags/v<V>" "refs/tags/v<V>^{}"` and check its exit status.

- Both refs absent after a successful query: verify the local annotated tag peels to the gated
  SHA. Remove only that verified local rehearsal tag, clear the injected fault and repeat the
  cut. For a real retry reconcile the remote first and obtain owner authority for the next push.
- Remote tag exists and peels to the gated SHA: publication succeeded. Record readback and
  proceed once.
- Query failed, tag is lightweight or target differs: hold the repin for owner reconciliation.
  Preserve the refs. A failed push exit alone cannot establish remote absence.

Revert the one CLI repin commit to restore the old lock, fixture and certified header together.
Verify the old install and certified smoke. Keep the published tag immutable. For a defective
engine release, gate a corrected patch and repin in the same order.

## Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_engine_f31_surface.py` | CLI `tests/sentry/release/` | `CODEMAP.md:73`: guards of a contract go under `tests/sentry/`; this one guards the release contract | `test_release_identity_sentry.py` |
| `test_strict_fixture.py` | CLI `tests/sentry/tooling/` | `CODEMAP.md:73`; it guards the pytest tooling (the strict fixture) | `test_pytest_timeout.py` |
| `changelog.d/<slice-slug>.md` (if AC0 supplies public engine API) | engine `changelog.d/` | `CODEMAP.md:302`, Changelog fragments | the folder README; the stamp consumes the fragment |
| generated reason-manifest minor fixture (only for a registry minor) | engine `tests/fixtures/f29/` | existing F29 release fixture family, emitted by `stamp_release.py:439–447` | `reason-manifest-v1.34-release-0-28-4.json` |

Extend the landed engine renderer, strict-switch module and their tests in place. The two
new CLI files are found by the sentry manifest's glob over `tests/sentry/` (`test_sentry_manifest.py:36`
to `:40`), so they run in the gate's sentry step with no registry entry.

## Size

Engine: the release preparation, about 43 files as in `19aabbfa9` (mostly fixtures and
fragments), plus about 100 lines for `strict_checks()`, `strict_checks_enabled()`, the two typed operations and their tests
if no AE slice added them. CLI: about 24 files, about 70 changed lines plus lock churn, and two
new test files of about 40 and 60 lines. No new public names in the CLI.

## Slices

Three gated units, in order:

1. Engine release preparation (engine, R2, about 43 files).
2. Publication (R3): dry run and recovery recorded, owner authorization, then
   `APPLY=1 scripts/release/cut-release.sh <gated-main-SHA>`.
3. CLI repin PR (CLI, R1, about 24 files).

## Design notes

The strict lifecycle has one owner, the engine's `strict_checks()`. The CLI fixture enters the public context. The engine fixture keeps
its warning-site cleanup and delegates the switch to the same context. In the engine strict
owner, save the prior pid-bound value on entry and restore it in `finally`; the reader and the
literal check consult the same state. Preserve literal admission and mint caller identity when
sharing the renderer conversions. Run the existing mint/literal guards with the new operations
and assert that a direct application caller still cannot mint a runtime string.

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
| D10 | allowlisted helpers | yes, for the registrar handoff | exercise registration by the admitted module and refusal from a different module. Reuse existing checked mint paths. Any newly admitted forwarder requires the same caller check by exact module/function identity |
| D11 | no raised caps | yes | keep shrink-only baselines and caps. Resolve a newly exposed copy or regression at its source; report a required exception to the owner before merge |

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

1. **OWNER CALL (recommended default chosen)** Preserve the registrar module AE1a2 admits.
   Use AC1's proposed `decoy._safe_mints` if AE1a2 has yet to name it. Record the actual module
   in the AC1 handoff and run admitted-caller and rejected-caller cases before the cut.
2. **OWNER CALL (recommended default chosen)** Keep equivalent public operations an AE slice
   already shipped. Otherwise use the names and contracts in guarantee 2. Bind AT-1 and AC1
   to the same public spellings at the gated SHA.

## Unverified

- The release version `<V>`. **OWNER CALL (recommended default chosen)** Use the next additive minor, keeping existing public names. 0.29.0 assumes no other engine release lands first.
- Whether an AE slice adds `strict_checks()` before the release preparation; if needed, release preparation adds
  the missing public operations and tests.
- The AE1, AE3, AE5 and AE6 branch references describe implementation targets. Their future
  APIs, node IDs and results require verification on merged main. Round 4 inspected the two
  local `origin/main` snapshots in Bases.
- Which CLI tests change with the release: known only after the full suite runs on the repin
  head.

## V2-LOG

- **V2-LOG** Branch line numbers locate prior review targets. Execution uses landed test IDs
  and recorded main SHAs. Corrected the slice count.

## Round 4 resolution

- **V1** Added a pre-tag runtime-only DP fit and tied the installed CLI engine to the remote
  tag, generated lock and gated SHA.
- **V1** Replaced blind push retries with rehearsed recovery for absent, published and
  indeterminate remote tags.
- **V1** Required passing native, loader, strict-lifecycle and typed-renderer cases. The CLI
  comparison checks for collection loss and newly hidden failures on the final pin.
- **DESIGN** Kept classification, registry lookup, minting, release stamping and fixture state
  with their existing owners. Recorded compatibility defaults for the AC1 handoff.
