Status: plan (revision 1, 2026-11-18; not yet reviewed)

# FAKER-MIGRATE: move the launch engine off Faker 40.23.0 before the 1.0 freeze, and lock Faker output after it

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

Roadmap row FAKER-MIGRATE (`C:docs/roadmap/groups/mask.md`, 1.0 table, on `C:claude/focused-sagan-0arhsp` `da7ebc7f`): "Move the launch engine from Faker 40.23.0 to 40.31 before the freeze (owner 2026-11-18). Faker's name and data pools are not semver-stable, so the Faker release that ships in 1.0 fixes deterministic `faker` output for the life of 1.x. Re-pin, regenerate the determinism goldens as one reviewed act, and re-certify the DP stack row. Snapshotting the pools so Faker can be upgraded freely is non-breaking and is a Later candidate." It merges before row 93 (REL-GATE, D-4 launch engine freeze). Owner decision of the same day (`C:docs/roadmap/decisions.md`): "Faker moves to 40.31 before the freeze, not after R1."

Anchors: a path with no prefix is in decoy-engine; the prefix `C:` is the CLI repository (decoy). Engine `origin/main` `ad36687a6` (engine 0.27.0); CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R2: a dependency lock change that moves frozen output), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `profiles/local-operations.md` (pre-merge done-state), `api-and-compatibility.md` (consumer inventory, explicit and coordinated break), `config-secrets-and-supply-chain.md` (reproducible, attributable dependency inputs and lockfiles), `testing.md` (T0 to T4; a dependency lock and a version pin escalate to the full suite), `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation; copies kept equal by a guard), `reuse-first.md` (online search first; vendoring needs a recorded rationale), `proportionality.md` (size, deletion test, no pin that ordinary changes hand-edit), `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2. No engine logic changes, but the change moves deterministic output for some provider and locale pairs, changes a dependency lock and a version pin, and re-pins the DP certified rows. Approver: Cam (owner) for the target version and the post-1.0 rule; Dennis then Codex for the plan gate and the S2 code gate.

## 0. What the stale branch learned

`origin/fix/faker-40-31-migration` (`071b7d005`, 2026-09-25, no PR, about 994 commits behind main, base `0d69bffa5`) is read, not rebased. It holds two commits:

1. `a7b8d6691` bumped to 40.31.0 after finding that the 2026-07-23 claim ("40.31.0 drops five person providers and shifts the name pools") does not reproduce: `dir(Faker())` is identical between the two versions (305 names), the proof manifest was byte-identical, and every Faker-tagged test then on main passed unmodified.
2. `071b7d005` reverted the bump. The five-provider "drop" is real but has nothing to do with Faker: the optional `mimesis` extra rebinds `person_name`, `person_first_name`, `person_last_name`, `person_full_name` and `person_email` to `MimesisAdapter` (adoption matrix in `src/decoy_engine/providers_v2/_registry.py`), so they leave `faker_providers()` on either Faker version. The revert reason was the DP certified profile fingerprint: Faker is in the hashed distribution set, so the bump moved the row (`895b9a20...` to `234120d1...`) and failed `dp-certified-gate` and the CLI certified profile. Cam held the bump because re-certifying DP was a separate decision. That decision is now taken (row FAKER-MIGRATE).

What this plan keeps from it: the root cause (no registry fix is needed) and the three additive regression tests in `tests/unit/providers_v2/test_faker_adapter.py` (`TestPersonProvidersSurviveFakerVersion`), replayed by patch in S1. What it does not keep: the edit to `tests/unit/providers_v2/test_registry.py::test_known_faker_provider_present` (it makes an existing test conditional on `mimesis`; no CI job installs `mimesis`, so the test is green as it stands and the edit is out of scope), and the docstring note in `tests/sentry/test_proof_manifest.py` (recorded as follow-up F-1).

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. The engine pins one exact Faker version, `T` (owner Q1; recommended: the newest 40.x release that is at least 14 days old when S2 starts, 40.54.0 today; otherwise 40.31.0). `pyproject.toml`, `uv.lock`, `NOTICE`, the CLI `requirements-certified.txt` and `requirements-dev.lock`, and the Faker output lock all name `T`, and a sentry fails when any of them differs.
2. Before the pin moves, a Faker output lock is committed under 40.23.0. For every Faker locale (`faker.config.AVAILABLE_LOCALES`, the set `plan/checks/_generate_columns.py:230` admits) and every provider name the engine reflects for that locale (`get_faker_providers(make_faker(locale))`, denylist applied), the lock holds a digest of 8 seeded calls under a frozen clock. The S2 diff of that lock is the reviewed list of every changed, added and removed `(provider, locale)` pair.
3. Every golden that moves under `T` is rewritten by the tool that owns it (section 5.6), in S2. No golden file and no digest literal is edited by hand. No test assertion is weakened.
4. The DP certified rows are re-pinned with the existing tools: the engine dev/CI row through `scripts/release/dp_rows.py` (checked by `tests/sentry/test_dp_lock_row.py`) and the CLI pristine row through `C:scripts/cert_smoke.py`. Prior rows stay, so snapshots fitted on an older row still compile. `dp-certified-gate` runs and passes with no skips. The DP mechanism does not read Faker output (the proof-critical set is opendp, dp-accounting, numpy, scipy, pandas and pyarrow, `quality/dp_provenance.py`); Faker is in the row only because the row hashes the whole installed set. So the re-certification is a re-pin plus the gate run, not a new DP proof.
5. The output change is a pre-GA correction: one changelog fragment with a `Breaking:` line names the changed pairs, and `docs/compatibility-contract.md` section 1 records it as "Pre-GA corrections taken with the Faker repin".
6. After 1.0, compatibility contract section 3.3 says: a Faker bump may ship in a 1.x release only when the output lock diff has no changed digest and no removed provider or locale. Added providers and added locales are additive and allowed. Any other diff is a 2.0 change. The sentry makes every lock change visible (it fails on any diff); the release gate decides which diffs a 1.x release may carry.
7. No engine logic changes. Masking, generation, the native kernels, the derivation and `SEED_PROTOCOL_VERSION` are untouched.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- Snapshotting or vendoring Faker's providers so Faker can move freely (row text: Later, non-breaking). Section 2 says why it is not 1.0.
- Making the proof manifest independent of the `mimesis` extra (F-1, the stale branch's carry-forward).
- Widening `POOL_ELIGIBLE_FAKER_TYPES` or `POOL_ELIGIBLE_LOCALE_PAIRS`. S2 re-runs the determinism harness; a pair that newly certifies is not admitted here (F-3).
- The `test_registry.py` mimesis-awareness edit from the stale branch.
- Other dependency bumps. Dependabot PR E#583 bundles Faker 40.54.0 with five other packages and touches only `pyproject.toml` (the same shape as #47, which caused the 2026-07-23 confusion). S2 supersedes its Faker part (owner Q6).
- Provider kwargs. The lock calls each provider with no arguments (residual risk R-2).

## 2. Established solutions

Search run: Faker's documentation on seeding and versions; NumPy NEP 19 (random number generator policy) and the NumPy random compatibility policy; the CPython `random` reproducibility note; snapshot ("approval") testing in Python (pytest-regressions `data_regression`, syrupy); Dependabot grouping; a source diff of the Faker wheels 40.23.0, 40.31.0 and 40.54.0 taken from PyPI. In the codebase: the faker-determinism harness (`scripts/faker-determinism/`), the F0 parity oracle (`tests/parity/`), the runtime-lock probe (`support/_probe.py`), the DP row tooling (`scripts/release/dp_rows.py`), and the stale branch.

| Need | Established solution | What we take | What we do not take, and why |
|---|---|---|---|
| Know whether Faker output is stable across releases | Faker documentation ("Seeding the Generator"): "A Seed produces the same result when the same methods with the same version of faker are called"; "results are not guaranteed to be consistent across patch versions"; "If you hardcode results in your test, make sure you pinned the version of `Faker` down to the patch number" | Exact pin (already in place); every Faker release, patch included, is an output change until proven otherwise | Ranged pins |
| Freeze a random stream for users while the library improves | NumPy NEP 19: the legacy `RandomState` stream is frozen, with no more changes "not even to fix correctness bugs", while `Generator` may break stream compatibility "with caution"; CPython `random` keeps a backward-compatible seeder when seeding changes | The same split by version: the 1.x line freezes the Faker output it ships with; a better Faker stream is a 2.0 change | Two Faker backends side by side in one engine (the `RandomState` model): it doubles the provider surface for a rare case. Vendoring (below) is the later answer if a bump is needed inside 1.x |
| Detect an output change before it merges | Snapshot or approval testing (pytest-regressions `data_regression`, syrupy): a committed snapshot, a test that diffs against it, an explicit regenerate command whose diff is reviewed | The Faker output lock: one committed JSON snapshot, one sentry that diffs it, one writer whose diff is the review artifact | A new snapshot library. The engine has a versioned, type-tagged digest codec (`scripts/faker-determinism/digest_codec.py`, `CODEC_VERSION = 1`) and the same pattern in `check_determinism.py --write-golden`; a library adds a dependency for one file |
| Keep a bot from bumping a pinned dependency without review | Dependabot `groups` with `exclude-patterns` | Take Faker out of the `python-minor-patch` group so it gets its own PR, which the lock sentry judges alone | Ignoring Faker updates: the bot PR plus the sentry is the early warning that a Faker release changes nothing Decoy uses, which a 1.x security bump needs |
| Decouple Decoy from Faker's data churn | Vendoring the data (copy the provider tuples and formats, keep the MIT notice) | Recorded as the Later row the roadmap already names | Not in 1.0: Faker providers are code plus data across about 100 locales and 200 methods; a copy needs its own diff tool and owner. It is non-breaking to add after 1.0, because the copy starts as the frozen version and the lock is its acceptance test |

Source diff findings (wheels unpacked and diffed 2026-11-18; S0 repeats this for the exact `T`):

- 40.23.0 to 40.31.0: no change to `en_US`, `en_GB` or `fr_FR` provider data. Changed: `es_ES` `bban` and `iban` (computed CCC control digits), `de_DE` `vat_id` (ISO 7064 check digit), `nl_BE` bank codes, `pt_BR` `job` and `phone_number`, `ko_KR` region and country names, base `pyint`/`pyfloat` when both bounds collapse to one value (was infinite recursion), base `bank()` without a bank list raises `NotImplementedError` instead of `AttributeError`. Added: locale `mk_MK`, `pt_BR` `cin` and bank, `sr_BA` `ssn`, `es_MX` automotive.
- 40.31.0 to 40.54.0, in addition: base `uuid1` and `uuid7` draw their timestamp from the seeded generator instead of the wall clock (reproducible under a seed), base `currency` list follows current ISO 4217 codes, `en_GB` `vat_id` check digits, base `date_time` when start equals end, base `pyfloat` refuses `positive=True` with `max_value <= 0`, `file_path` gains an optional argument, and bank and ssn data in about ten more locales.
- The 2026-07-23 "Tomas to Tricia" name shift is in neither diff: `faker/providers/person/en_US` is unchanged across all three versions. This agrees with the stale branch.

Remaining custom code: one writer (about 120 lines) and two sentries (about 220 lines) over the existing reflection surface, codec and frozen clock.

## 3. Reuse inventory

- `decoy_engine.internal.faker_setup.make_faker` (`faker_setup.py:639`) and `get_faker_providers` (`faker_setup.py:465`): the call surface a `faker_type` column uses, with `_FAKER_DENYLIST` (`faker_setup.py:347`) applied. The lock reflects through them.
- `scripts/faker-determinism/digest_codec.py::_pool_digest`: type-tagged, length-framed encoding of a value list.
- `tests/parity/_f0_fixtures.py::frozen_faker_clock` (pins Faker's `date_time` clock to `ORACLE_CLOCK`).
- `scripts/faker-determinism/check_determinism.py --write-golden`: owner of `golden_digests.json` and `certified_pairs.json`.
- `scripts/gen_proof_manifest.py`, `scripts/gen_capability_matrix.py`, `tests/parity/_f0_capture.py`, `tests/parity/_fr0_refreeze.py`, `scripts/test_flight.py` write mode, `scripts/dev/licenses_write.sh`, `uv lock`, `scripts/release/dp_rows.py` and `scripts/release/stamp_release.py`, `C:scripts/cert_smoke.py`: the owning tools of section 5.6.
- `tests/sentry/dependencies/` (dependency rules folder) for the new sentries; `tests/physical/test_faker_determinism_driver.py` shows how a test loads a module from `scripts/faker-determinism/` by file path.
- The stale branch's three additive tests, replayed by patch.

## 4. Behaviour

### 4.1 The Faker output lock (S1)

File `scripts/faker-determinism/output_lock.json`, canonical JSON (sorted keys, separators `(",", ":")`, UTF-8, trailing newline):

```
{
  "lock_version": 1,
  "faker_version": "40.23.0",
  "codec_version": 1,
  "samples": 8,
  "clock": "2026-10-16T12:00:00",
  "locales": {
    "<locale>": {
      "<provider>": "<64 hex>" | "raises:<ExceptionClassName>" | "unstable"
    }
  }
}
```

Computation, one function `compute_lock()` in `scripts/faker-determinism/output_lock.py`:

1. For each `locale` in `sorted(faker.config.AVAILABLE_LOCALES)`: `providers = get_faker_providers(make_faker(locale))`.
2. For each `name` in `sorted(providers)`, on a fresh `make_faker(locale)`, inside `frozen_faker_clock()`: for `i` in `range(8)`, `fake.seed_instance(i)` and call the engine's reflected callable with no arguments. Encode the 8 values with `_pool_digest` and SHA-256 them.
3. A call that raises records `raises:<class name>`: the exception class only, never its message, so no value reaches the file.
4. The writer computes each pair twice on two fresh instances. A pair whose two digests differ is recorded as `unstable`. The sentry does not recompute an `unstable` pair but checks that the name is present and still recorded `unstable`, so the unstable set cannot change silently. Under 40.23.0 the expected unstable set is the clock-reading providers that do not go through `date_time` (for example `uuid1`).

Writer: `python scripts/faker-determinism/output_lock.py --write` rewrites the file; it exits 1 with a fixed message when the installed Faker is not the `pyproject.toml` pin. Sentry: `tests/sentry/dependencies/test_faker_output_lock.py` recomputes and diffs. Its failure message lists, per locale, the removed, added and changed names (names only, never values or digests), the installed Faker version and the lock's version, and ends: "Faker output moved. Before 1.0: regenerate with output_lock.py --write in the repin PR. After 1.0: a changed or removed pair is a 2.0 change (compatibility contract 3.3)."

Runtime budget: about 100 locales times about 200 providers times 8 calls. S1 measures the sentry on the Dell or the Mac and records the time in the PR. If it is over 30 seconds there, it gets the marker `faker_output_lock` and a required CI job `faker-output-lock` with no path filter (in `ci/required-jobs.toml`, so it cannot be skipped), and leaves the default loop. Otherwise it runs in the default loop. The rule is fixed here; the measurement only picks the branch.

### 4.2 The version-agreement sentry (S1)

`tests/sentry/dependencies/test_faker_pin_agrees.py`: the single `faker==` pin in `pyproject.toml`, the `faker` version in `uv.lock`, the `faker==` line in `NOTICE`, the lock's `faker_version`, and `tests/parity/_f0_fixtures.py::PINNED_FAKER_VERSION` are equal. The `pyproject.toml` pin is the one fact. `uv.lock` and `NOTICE` are generated from it; the lock version and `PINNED_FAKER_VERSION` record the version a capture was taken under, and a capture under a different version is stale. The CLI gets the same check in C1.

### 4.3 The repin (S2)

In this order, on one branch, each step by its owning tool:

1. `pyproject.toml`: `faker==T`. The comment above the pin is rewritten to the verified history: the 2026-07-23 claim was the `mimesis` rebinding; the pin moves only with the output lock and the DP rows; after 1.0 see compatibility contract 3.3.
2. `uv lock --upgrade-package faker==T`. The `uv.lock` diff may touch only the `faker` block and the `decoy-engine` requirement (AT-P2).
3. `scripts/dev/licenses_write.sh` (NOTICE).
4. `python scripts/faker-determinism/output_lock.py --write`. The lock diff, as names, goes into the PR body as the list of moved pairs.
5. Every golden that the S0 record marks "moved" in section 5.6, by its tool, in the table's order.
6. DP: the new dev/CI fingerprint, from `dp_rows` as release prep computes it, is added to `_CERTIFIED_STACKS` (`quality/dp_provenance.py:272`), newest first, prior rows kept. A fresh `uv sync --frozen --extra dev --extra lint --extra vault --extra cloud` on CPython 3.10.20 reproduces it (the check the row comment documents).
7. `support/_probe.py` `PROBE_GOLDEN[7]`: only if S0 shows the probe moved. Expected not: the probe pools `person_first_name` in `en_US`, unchanged in both diffs. If it moves, the value comes from `run_probe()` on the repinned venv and the fragment names it, as `_probe.py:49` requires.
8. Changelog fragment `changelog.d/faker-migrate.md`: a `Breaking:` line ("deterministic `faker` output changes for the listed provider and locale pairs; re-run masking to keep joins stable across the change"), then the moved pairs grouped by locale.
9. `docs/compatibility-contract.md`: section 1 gets "Pre-GA corrections taken with the Faker repin (FAKER-MIGRATE)"; section 3.3 gets the rule of 1.1 item 6; the section 5 decision table gets the row "Bump Faker so the output lock changes or loses a pair: Yes (major)". `docs/determinism.md`: one paragraph that points at the lock.
10. `.github/dependabot.yml`: `exclude-patterns: ["faker"]` on the `python-minor-patch` group.

### 4.4 CLI (C1)

After the engine release that carries S2 and its stamped DP rows: `C:requirements-certified.txt` gets `faker==T` and its row from `C:scripts/cert_smoke.py`; `C:requirements-dev.lock` is regenerated by its lock command; the engine repin follows the engine repin checklist; any CLI golden the S0 record lists is rewritten by its tool; `C:docs/roadmap/release-gates.md` D-4 text "Faker 40.23.0" becomes "Faker T"; `C:docs/roadmap/groups/mask.md` row state moves; CLI CHANGELOG entry. CLI sentry `C:tests/sentry/test_faker_pin_agrees.py`: both CLI files name the Faker version the installed engine requires.

## 5. Enumerations

### 5.1 Exit paths

The change adds no runtime refusal. The exits are those of the new tools and of existing provider calls whose behaviour moves:

- `output_lock.py --write`: exit 0 with the file written; exit 1 with a fixed message when Faker does not import or the installed version is not the pin at `pyproject.toml:74`.
- `test_faker_output_lock.py`: pass, or fail listing names per locale (AT-L1 to AT-L8).
- `test_faker_pin_agrees.py`: pass, or fail naming the file that disagrees (AT-P1).
- A `faker_type: bank` column in a locale with no bank list: today `AttributeError` from Faker, after S2 `NotImplementedError`. The engine has no `except AttributeError` around provider calls (the only one is the locale fallback at `faker_setup.py:660`), so both reach the same generic provider-failure path. AT-B1 pins that the reason code and exit do not change.
- `pyfloat` with `positive=True` and `max_value <= 0` (only if `T` is 40.54.0 or later): Faker raises `ValueError` where it used to return a value. Same generic path; listed in the fragment.
- DP fit on a `T` venv with no new row: `dp_stack_uncertified` (existing, `quality/dp_provenance.py:369`); after S2 it passes.
- Resume of a run started before the repin: the run fingerprint includes the Faker version (component list in `tests/unit/delivery/resume/test_fingerprint.py:18`), so resume is refused with the existing fingerprint-mismatch refusal, as for any engine bump.

### 5.2 Routes

Every route that turns Faker into output reads it through `make_faker` and the reflected or registry surface, so the lock and the goldens below cover them:

- Masking `faker` strategy: `execution/_strategies/_faker.py:89` builds the pool with `PoolBuilder` over the V2 registry, whose Faker backend seeds one instance per build (`providers_v2/_faker_adapter.py:230`). Native and chunked masking only derive indices into that Python-built pool (the Rust kernel holds no Faker data), so they move exactly with the pool.
- Generation per-row `faker` columns: `generation/synthesize.py:449` (`_faker`), one seeded call per row through `faker_setup`.
- Generation pooled `faker` columns: `generation/_faker_pool.py:359` (`make_faker(effective_locale)`), admitted pairs only.
- Composite person generation: `generation/composite/_person.py`, through the registry.
- Runtime-lock probe: `support/_probe.py:95` (`_pool_part`), Faker adapter pinned.
- Capability reporting: `providers_v2/_real_registry.py:27` records `faker.VERSION` as `backend_version`, which feeds `_providers_digest` (`support/_runtime_lock.py:280`) and `docs/capability-matrix.md`.

### 5.3 FK shapes

N/A: this change produces no FK keys and touches no FK machinery; an FK column with a `faker` strategy moves like any other column of that provider and locale.

### 5.4 Fields

- `output_lock.json`: `lock_version`, `faker_version`, `codec_version`, `samples`, `clock`, `locales` (closed set; the sentry refuses an unknown or missing key).
- Runtime lock `faker` field (`support/_runtime_lock.py:327`): the value moves from `40.23.0` to `T`; the field set does not change.
- Capability matrix `backend_version` for Faker-backed providers: `T`.
- DP certified rows: one new dev/CI fingerprint (S2), one new CLI fingerprint (C1); none removed.

### 5.5 Output surfaces

- Deterministic `faker` output for the pairs the lock diff lists (masked files, generated files, sample output).
- The runtime lock `faker` field and `providers_digest`; the probe only if S0 shows a move.
- `docs/proof-manifest.json`, `docs/capability-matrix.md`, `NOTICE`.
- No reason code, no log line, no CLI flag and no `--json` key changes.

### 5.6 Goldens and their owning tools

S0 runs every check below under `T` and marks each row "moved" or "unchanged". S2 regenerates only the moved rows, each by its tool. A red test that no row owns stops S2 (FM-4).

| Golden | Check that reads it | Owning tool | Expected under `T` |
|---|---|---|---|
| `scripts/faker-determinism/output_lock.json` | `tests/sentry/dependencies/test_faker_output_lock.py` | `output_lock.py --write` | moved (by design) |
| `scripts/faker-determinism/golden_digests.json`, `certified_pairs.json` | `check_determinism.py` (marker `determinism_harness`) | `check_determinism.py --write-golden` | likely unchanged: the 5 harness locales have changes only in bank and VAT types, which are not harness candidates |
| `tests/parity/_f0_expected.py` and `PINNED_FAKER_VERSION` (`tests/parity/_f0_fixtures.py:100`) | `tests/parity/test_phase_f_f0_oracle.py` | `python -m tests.parity._f0_capture` (its docstring command); the version literal moves with the capture | version literal moves; digests only if a fixture uses a moved pair |
| FR0 refreeze data | `tests/parity/test_phase_f_fr0_refreeze.py` | `tests/parity/_fr0_refreeze.py` | measured in S0 |
| `docs/proof-manifest.json` | `tests/sentry/test_proof_manifest.py` | `scripts/gen_proof_manifest.py` (no `mimesis`, as CI) | measured in S0 |
| `docs/capability-matrix.md` | `tests/sentry/test_capability_matrix.py` | `scripts/gen_capability_matrix.py` | moved if it prints `backend_version` |
| `testflight/golden_fingerprints.json` | `scripts/test_flight.py` (nightly) | `scripts/test_flight.py` write mode | measured in S0 |
| `support/_probe.py` `PROBE_GOLDEN` | `tests/unit/support/test_probe.py` | `run_probe()` value, named in the fragment | unchanged |
| `_CERTIFIED_STACKS` dev/CI row | `tests/sentry/test_dp_lock_row.py`, `dp-certified-gate` | `scripts/release/dp_rows.py` | moved (Faker is in the hashed set) |
| `NOTICE` | license sentries | `scripts/dev/licenses_write.sh` | moved |
| `tests/snapshots/*` baselines | their tests | each test's documented update path | measured in S0 |
| `tests/native/test_draw_site_providers_golden.py` | itself | none | unchanged (uses a stand-in `_FakeFaker`) |
| `tests/fixtures/golden/*` CSV inputs | V2 fixture tests | `scripts/build_golden_fixtures.py` | not regenerated: these are test inputs built with Faker, not outputs. Only if a reproducibility check reads them and fails does S2 rebuild them, and the downstream checks must then stay green on the new inputs |
| `tests/integration/compat_corpus/runtime-lock/*.json`, `tests/unit/delivery/resume/test_fingerprint.py` vectors | reader and fingerprint tests | none | unchanged: hand-written format samples whose `40.23.0` is data, not the installed version |
| CLI goldens | CLI e2e | each one's tool | measured in S0 (CLI part), rewritten in C1 |

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Faker pin | `faker==40.23.0` | `faker==T` | `pyproject.toml`, `uv.lock`, `NOTICE`, CLI requirement files, `output_lock.json` |
| Deterministic `faker` output | Faker 40.23.0 data | Faker `T` data for the pairs in the lock diff | changelog fragment `Breaking:`; compatibility contract section 1 pre-GA note |
| Faker output lock | none | `lock_version: 1` | `scripts/faker-determinism/README.md`; compatibility contract 3.3 |
| Post-1.0 Faker rule | the general 3.3 rule ("Faker seeding" in the section 5 table) | explicit: a changed or removed pair is a major; additive pairs are allowed | compatibility contract 3.3 and section 5 table |
| DP certified rows | rows up to engine 0.27.0 | plus one dev/CI row and one CLI row on `T` | `quality/dp_provenance.py`, `C:requirements-certified.txt` |
| D-4 launch engine | "Faker 40.23.0" | "Faker T" | `C:docs/roadmap/release-gates.md` |

## 7. Failure modes and partial failure

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | A Faker release changes data for a provider the engine admits | the lock sentry fails, naming the pairs | AT-L3 |
| FM-2 | A Faker release removes a reflected method or a locale | the sentry fails, naming the removed names | AT-L4 |
| FM-3 | A Faker release adds a method or a locale | the sentry fails too (the lock is exact) and marks the change additive; the bump PR rewrites the lock | AT-L5 |
| FM-4 | Under `T` a test goes red that no row of 5.6 owns | S2 stops and reports; the test is not edited. Either a plan revision adds its owner to 5.6, or it is a behaviour change taken to the owner | gate check G-1 |
| FM-5 | A builder edits a golden or digest by hand | the S2 gate re-runs every owning tool on the S2 head; any difference fails the gate | G-2 |
| FM-6 | `uv lock` moves other packages | the `uv.lock` diff check refuses it | AT-P2 |
| FM-7 | The DP row is added but a fresh venv does not reproduce it | `test_dp_lock_row.py` fails on every gate host (it never skips) | AT-DP1 |
| FM-8 | The CLI repins an engine on `T` but keeps `faker==40.23.0` | CLI sentry fails; `cert_smoke.py` fails with `dp_stack_uncertified` | CV-P1, CV-DP1 |
| FM-9 | A provider reads the wall clock outside `date_time` | recorded `unstable` by the writer; the sentry checks the unstable set exactly | AT-L6 |
| FM-10 | A provider call raises | recorded `raises:<class>`; a change of class shows as a changed pair (the `bank()` case) | AT-L7 |
| FM-11 | The sentry is slow | the 30-second rule of 4.1 moves it to a required CI job with no path filter | S1 measurement |
| FM-12 | A Dependabot group PR bumps Faker with other packages | the group excludes Faker; a Faker PR stands alone and the lock sentry judges it | AT-P3 |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the slice head.

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-L1 | `tests/sentry/dependencies/test_faker_output_lock.py::test_lock_matches_installed_faker` | no lock | change one stored digest in a temporary copy of the lock (the test takes the lock path as a fixture) | S1 |
| AT-L2 | `::test_lock_is_closed_and_canonical`: closed key set, canonical bytes, `codec_version == digest_codec.CODEC_VERSION`, `samples == 8` | no lock | accept an extra key in a copy | S1 |
| AT-L3 | `::test_changed_pair_is_named`: monkeypatch one reflected provider to return a different value; the failure names that provider and locale and holds no value | no sentry | drop the changed-name list from the message | S1 |
| AT-L4 | `::test_removed_pair_is_named`: remove one provider from the reflection in a cell | no sentry | compare only names present on both sides | S1 |
| AT-L5 | `::test_added_pair_is_named_additive`: add one provider in a cell; the message says "added" | no sentry | treat added names as equal | S1 |
| AT-L6 | `::test_unstable_set_is_exact`: in a lock copy, mark one stable provider `unstable`; the test fails | no sentry | skip `unstable` names entirely | S1 |
| AT-L7 | `::test_raise_is_recorded_by_class`: a provider that raises records `raises:<class>`, and the exception message never appears in the lock | no writer | record `str(exc)` | S1 |
| AT-L8 | `::test_lock_covers_engine_surface`: for `en_US` and `pt_BR`, the lock's names equal the keys of `get_faker_providers(make_faker(locale))`: a denylisted name is absent and every admitted name is present | no lock | reflect `dir(Faker())` instead of the engine surface | S1 |
| AT-P1 | `tests/sentry/dependencies/test_faker_pin_agrees.py::test_copies_agree`: the five copies of 4.2 agree; a seeded cell with one copy changed fails naming the file | no sentry | drop `NOTICE` from the checked set | S1 |
| AT-P2 | gate check on the S2 head: `git diff origin/main -- uv.lock` touches only the `faker` package block and the `decoy-engine` requirement | n/a (gate check) | an extra `--upgrade` in the lock command | S2 |
| AT-P3 | `test_faker_pin_agrees.py::test_dependabot_excludes_faker`: the pip group in `.github/dependabot.yml` has `exclude-patterns` containing `faker` | no exclusion | remove the pattern | S2 |
| AT-S1 | `tests/unit/providers_v2/test_faker_adapter.py::TestPersonProvidersSurviveFakerVersion` (three tests replayed from `071b7d005`) | not on main | drop `"email"` from the V1 reflection loop | S1 |
| AT-B1 | `tests/unit/generation/test_faker_provider_failure_code.py`: a generate config with `faker_type: bank` and a locale with no bank list fails with the same engine reason code and exit category on 40.23.0 and on `T` | the code is not pinned today | a new wrapper that catches only `AttributeError` (the `T` run then leaks a raw `NotImplementedError`) | S1 (green on 40.23.0), S2 (green on `T`) |
| AT-DP1 | `dp-certified-gate` on the S2 head: certified environment, the marked DP suites run, JUnit shows passed > 0 and no skip; `test_dp_lock_row.py` green | the 40.23.0 rows do not match a `T` venv | omit the new row from `_CERTIFIED_STACKS` | S2 |
| AT-R1 | every 5.6 check marked "moved" is red with the pin moved and the golden not yet regenerated, and green on the S2 head; every row marked "unchanged" is green throughout | n/a (the regeneration act) | revert one regenerated golden file | S2 |
| AT-F1 | the fragment passes `tests/unit/scripts/test_check_fragment.py` and carries a `Breaking:` line | no fragment | drop the `Breaking:` line | S2 |
| CV-P1 | `C:tests/sentry/test_faker_pin_agrees.py`: CLI `requirements-certified.txt`, `requirements-dev.lock` and the installed engine's `faker` requirement agree | no sentry | leave `40.23.0` in `requirements-dev.lock` | C1 |
| CV-DP1 | `C:scripts/cert_smoke.py` in a fresh 3.10.20 venv from `requirements-certified.txt` passes fit, `dps-marginal/v3` and generate | the CLI row is on 40.23.0 | omit the new CLI row | C1 |

Gate checks (run by the gate, not tests): G-1 every red test under `T` in S0 maps to a row of 5.6; G-2 on the S2 head, each owning tool in 5.6 runs again and `git status` stays clean.

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `scripts/faker-determinism/output_lock.py` | new (S1, about 120 lines): `compute_lock`, `--write` | Dev tooling: one-off tools in a topic folder, `scripts/faker-determinism/` | `check_determinism.py`, `digest_codec.py` |
| `scripts/faker-determinism/output_lock.json` | new (S1, generated) | same | `golden_digests.json` |
| `scripts/faker-determinism/README.md` | changed (S1): the lock, its writer and the post-1.0 rule | same | |
| `tests/sentry/dependencies/test_faker_output_lock.py` | new (S1, about 140 lines; loads `output_lock.py` by file path) | Sentry test: dependency rules in `tests/sentry/dependencies/` | `test_dependency_floors.py` |
| `tests/sentry/dependencies/test_faker_pin_agrees.py` | new (S1, about 80 lines; S2 adds the Dependabot cell) | same | same |
| `tests/unit/providers_v2/test_faker_adapter.py` | changed (S1, +64, replayed) | Unit tests | |
| `tests/unit/generation/test_faker_provider_failure_code.py` | new (S1, about 40 lines) | Unit tests mirroring `generation/` | other generation tests |
| `pyproject.toml`, `uv.lock`, `NOTICE` | changed (S2) | | |
| moved goldens of 5.6 | changed (S2, by tool) | their existing places | |
| `src/decoy_engine/quality/dp_provenance.py` | changed (S2, one row and its comment line) | Quality | the other rows |
| `src/decoy_engine/support/_probe.py` | changed only if S0 says so (S2) | Support bundles | |
| `changelog.d/faker-migrate.md` | new (S2) | Changelog fragments | |
| `docs/compatibility-contract.md`, `docs/determinism.md` | changed (S2) | Feature and contract docs | |
| `.github/dependabot.yml` | changed (S2) | Lightweight automatic PR checks | |
| `ci/required-jobs.toml`, `.github/workflows/ci.yml` | changed only if the 30-second rule moves the sentry (S1) | CI lane registries | |
| `docs/records/2026-11-<dd>-faker-repin-impact.md` | new (S0) | Plans, decisions, records | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"): `C:requirements-certified.txt` and `C:requirements-dev.lock` (changed); `C:tests/sentry/test_faker_pin_agrees.py` (new, sentry test, beside the other CLI sentries); `C:docs/roadmap/release-gates.md`, `C:docs/roadmap/groups/mask.md`, `C:CHANGELOG.md` (changed). No new source module in either repo.

## 10. Design notes

- Choke point for "Faker output may not move unseen": the output lock and its sentry. Every route in 5.2 reads Faker through `make_faker` and the reflected or registry surface, and the installed Faker can change only through `uv.lock`; the sentry recomputes over that surface. Guard: AT-L1 to AT-L8. Mutation: reflect `dir(Faker())` instead of the engine surface (AT-L8).
- Choke point for "one Faker version": the `pyproject.toml` pin. The other copies are generated or capture records, and AT-P1 and CV-P1 keep them equal (cross-cutting rule: copies kept equal by a guard, not by hand). Mutation: drop one copy from the checked set.
- Why lock under 40.23.0 first (S1 before S2): the S2 lock diff is then the complete, tool-made list of moved pairs. A lock written after the bump would hide what moved.
- Why 8 samples and no kwargs: 8 seeds reach the random branches of almost every provider at a cost the default loop can carry; kwargs are a config surface the other goldens cover (R-2).
- Why every Faker locale, not the five harness locales: `plan/checks/_generate_columns.py:230` admits any locale in `AVAILABLE_LOCALES`, so a `pt_BR` user's `job` column moves with this change (owner Q2).
- Why not vendor now: section 2. The lock is also what a later vendoring row needs: a vendored copy is correct when it reproduces the frozen lock.
- No new structure in `src/`. Logs and errors: the tools print provider names, locale names, file names and versions only; Faker exception messages are never stored (AT-L7).

## 11. Size

| Slice | Src lines | Test and tool lines | Generated | Docs lines | Files touched |
|---|---|---|---|---|---|
| S0 | 0 | 0 | 0 | about 120 (record) | 1 |
| S1 | 0 | about 450 (writer 120, sentries 220, replayed tests 64, AT-B1 40) | `output_lock.json` (size recorded in the PR) | about 40 | about 7 |
| S2 | about 15 (pin comment, DP row, probe only if moved) | about 10 (AT-P3 cell) | `uv.lock`, `NOTICE`, the moved goldens of 5.6 | about 90 | about 12 plus the moved goldens |
| C1 | 0 | about 60 | the two CLI requirement files | about 20 | about 6 |

New public names: none in the engine package. No file passes its size ceiling.

## 12. Slices

| Slice | Repo | Content | Risk | Line budget | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|---|
| S0 | engine (record); runs on the Dell or the Mac, never the devbox | Build a clean venv from `origin/main` with `faker==T` (scratch lock, not committed); run the full suite, `pytest -m determinism_harness`, `scripts/test_flight.py`, the proof-manifest and capability-matrix checks, and the CLI e2e suite against that engine; record each red test id, the 5.6 row that owns it, and moved or unchanged for every 5.6 row; repeat the wheel diff for the exact `T` | R0 (record only) | 150 docs | G-1 | owner Q1 | none (it is the measurement); Codex reads the record |
| S1 | engine | Lock writer, `output_lock.json` captured under 40.23.0, both sentries, the three replayed tests, AT-B1, README; the 30-second measurement and, if needed, the CI job | R1 (tests and tooling, no product change) | 500 test and tool, 40 docs | AT-L1 to AT-L8, AT-P1, AT-S1, AT-B1 | none | T1 impact set (sentry, providers_v2, generation) plus each named mutation; Codex review |
| S2 | engine | The repin of 4.3: pin, `uv.lock`, `NOTICE`, lock rewrite, moved goldens by tool, DP dev/CI row, probe if moved, fragment, contract and determinism docs, Dependabot | R2 (moves frozen output; dependency lock; version pin; DP row) | 30 src, 20 test, 100 docs; generated files exempt | AT-P2, AT-P3, AT-DP1, AT-R1, AT-F1, AT-B1, G-2 | S0 record read by the owner; S1 merged | Escalation triggers (dependency lock, version pin, frozen contract): T3 full suite on the Mac or Dell on the exact head, diffed against the saved main baseline; `determinism_harness`; `test_flight.py`; `dp-certified-gate`; each mutation; Dennis then Codex |
| E-REL | engine | The next daily engine release stamps the DP rows with the new engine version (`stamp_release.py`, existing release prep) | release train | n/a | `test_dp_lock_row.py` on the release head | S2 | release checks |
| C1 | CLI | `requirements-certified.txt` and its row via `cert_smoke.py`, `requirements-dev.lock`, engine repin per the checklist, CLI goldens by tool, D-4 text, roadmap row state, CHANGELOG, CLI pin sentry | R2 (certified profile, repin) | 60 test, 30 docs; generated exempt | CV-P1, CV-DP1 | E-REL | CLI T1 (e2e that touch generation and masking, sentries) plus T2 on the head; `cert_smoke.py`; Codex |

Order: S0 and S1 can start now, in parallel (S1 does not depend on `T`). S2 starts after the owner has read the S0 record and answered Q1. S2 and C1 merge before row 93 (REL-GATE). FREEZE-OUTPUT also recaptures goldens: whichever of the two merges second re-runs the owning tools on its own head; goldens are never merged by hand.

Open PRs that touch the same files (checked 2026-11-18): E#583 (Dependabot group: `pyproject.toml`, Faker 40.23.0 to 40.54.0 plus five packages; superseded for Faker by S2, owner Q6); E#661 (GEN-PROVIDERS E1: `generation/_faker_pool.py`, `testflight/golden_fingerprints.json`, Faker pool tests); E#333 (parked draft). Whichever of E#661 and S2 merges second re-runs `test_flight.py` write mode on its own head.

## 13. Recurring-defect class check

- A test weakened to pass: every red test under `T` is either owned by a 5.6 tool or stops the slice (FM-4). The one literal that moves in a test file is `PINNED_FAKER_VERSION`, the capture record the F0 test itself names, and it moves only with the F0 recapture.
- A golden refreshed as a reflex: G-2 re-runs every tool on the head.
- Copies of a fact: the Faker version has five engine copies and two CLI copies, all generated or capture records, kept equal by AT-P1 and CV-P1.
- Value exposure and exception context: the lock stores digests and exception class names only; no new error is raised from inside an `except` block.
- A dependency failure misread (the 2026-07-23 event): S0 reproduces every red in a clean venv on a test node from `origin/main`, never in a working venv.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a Faker value or exception text in the lock or a sentry message) | digests and class names only; messages carry names and versions | AT-L3, AT-L7 | record `str(exc)` in the lock | S1 |
| 2 | Cleanup on every exit | N/A: the writer and sentries open no resource beyond one file write; the frozen clock is a context manager that restores on every exit (`_f0_fixtures.py:79`) | existing F0 tests of the clock | none | none |
| 3 | State completeness (every lock entry kind handled: digest, raises, unstable, added, removed) | one diff function with one branch per kind | AT-L3 to AT-L7 | merge "added" into "changed" | S1 |
| 4 | Route coverage (a Faker route the lock does not see) | the lock reflects the surface every route in 5.2 uses; AT-L8 ties it to `get_faker_providers` | AT-L8 | reflect `dir(Faker())` | S1 |
| 5 | Referential integrity | N/A: no FK or cross-table state changes (5.3) | none | none | none |
| 6 | Untrusted input | N/A: the lock and the requirement files are repo files written by tools, not user input; the sentry still refuses an unknown lock key (AT-L2) | AT-L2 | accept unknown keys | S1 |
| 7 | TOCTOU (lock computed on one Faker, checked on another) | the lock records `faker_version`; the writer refuses when the installed Faker differs from the pin; AT-P1 ties the lock version to the pin | AT-P1 | skip the version check in the writer | S1 |
| 8 | Weak proof (a lock too coarse to see a change) | 8 seeded samples per pair and locale, exact name sets, exact unstable set | AT-L3, AT-L6 | digest only the first sample | S1 |
| 9 | Refactor drift | N/A: no source refactor; S2 changes a pin and data, and AT-P2 limits the `uv.lock` diff to Faker | AT-P2 | an unrelated upgrade | S2 |
| 10 | Frozen contract drift (output moves without its records) | pin, lock, goldens, DP rows, fragment, contract note and D-4 text move together in S2 and C1 | AT-R1, AT-F1, AT-DP1, CV-P1 | keep `faker==40.23.0` in the CLI dev lock | S2, C1 |

## 14. Pre-mortem

- "S2 refreshed a golden that hid a real regression." Guard: S0 maps every red to an owner before S2 starts (G-1); an unmapped red stops the slice (FM-4); Dennis reads the lock diff against the wheel diff of section 2.
- "The DP gate went green by skipping." Guard: `dp-certified-gate` fails on any skip (`scripts/dev/junit_ran.py`), and `test_dp_lock_row.py` never skips.
- "We misread a dependency failure again." Guard: S0 runs in a clean venv on a test node from `origin/main`; the pin comment names the `mimesis` root cause.
- "After 1.0 a Faker security fix cannot ship." Answer: it ships in 1.x when the lock is unchanged or only additive; otherwise the Later vendoring row is the path, or 2.0.
- "The lock sentry slows every test run." Guard: the 30-second rule of 4.1.
- "FREEZE-OUTPUT and S2 recapture the same goldens at once." Guard: the order rule in section 12.

## 15. Residual risks

- R-1: a Faker change that shows only past the first 8 seeds or on a rare branch (the `pyfloat` collapse case is one) is not in the lock. The harness and the other goldens see the admitted pool pairs; the per-row long tail relies on the lock.
- R-2: providers called with kwargs from a config are not in the lock.
- R-3: Faker import-time behaviour (locale fallback, a renamed locale) is seen only through `AVAILABLE_LOCALES` and the name sets.

## 16. Owner questions (taken on the recommended answer; owner to confirm)

| Id | Question | Recommended | Why |
|---|---|---|---|
| Q1 | Which Faker goes into 1.0: 40.31.0 (the 2026-11-18 decision) or the newest 40.x at least 14 days old when S2 starts (40.54.0, released 2026-11-10)? | The newest 40.x at least 14 days old at S2 start (40.54.0 if S2 starts on or after 2026-11-24) | The 1.0 Faker is frozen for all of 1.x, and the repin costs the same for either version. 40.54.0 adds seeded `uuid1`/`uuid7` (on 40.23.0 and 40.31.0 they read the wall clock, so a `uuid1` column is not reproducible), current ISO 4217 currency codes and `en_GB` VAT check digits. It also adds one new refusal (`pyfloat` with `positive=True` and `max_value <= 0`). 40.31.0 is the smaller diff: it changes no `en_US`, `en_GB` or `fr_FR` data. |
| Q2 | Lock every Faker locale, or only the five harness locales? | Every locale | The engine admits any locale in `AVAILABLE_LOCALES`; a `pt_BR` user gets moved `job` output from this change |
| Q3 | Post-1.0 rule: a Faker bump ships in 1.x only with an unchanged or purely additive lock diff; anything else is 2.0? | Yes | The NEP 19 split; the lock makes it checkable |
| Q4 | Vendoring or snapshotting the providers: Later (1.x), not 1.0? | Later | Non-breaking after 1.0; large surface; the lock is its acceptance test |
| Q5 | Delete `fix/faker-40-31-migration` after S1 has replayed its three tests? | Yes, after S1 merges (owner-gated branch deletion) | Its conclusion is on main and its tests move in S1 |
| Q6 | Close Dependabot E#583, or rebase it without Faker? | Rebase without Faker (or let Dependabot reopen after the group exclusion lands) | Faker moves only in S2 with its lock; the other five packages follow their own review |

## 17. Follow-ups (outside the guarantee)

- F-1: the proof manifest depends on whether `mimesis` is installed at generation time (stale branch note). Pin the generation profile in `gen_proof_manifest.py` or record it in the manifest. Maintenance row.
- F-2: the Later row "snapshot Faker providers" takes `output_lock.json` as its acceptance oracle.
- F-3: if S0 shows newly certifiable pool pairs under `T`, a widening row may admit them after 1.0 (additive).
