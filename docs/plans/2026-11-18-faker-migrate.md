Status: plan (revision 2, 2026-11-18; Dennis round 1 NO-GO addressed: B1, H1 to H4, M1 to M8, L1 to L6; owner Q1 settled; not yet re-reviewed)

# FAKER-MIGRATE: move the launch engine from Faker 40.23.0 to 40.54.0 before the 1.0 freeze, and lock Faker output after it

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

Roadmap row FAKER-MIGRATE (`C:docs/roadmap/groups/mask.md`, 1.0 table, on `C:claude/focused-sagan-0arhsp` `da7ebc7f`): "Move the launch engine from Faker 40.23.0 to 40.31 before the freeze (owner 2026-11-18). Faker's name and data pools are not semver-stable, so the Faker release that ships in 1.0 fixes deterministic `faker` output for the life of 1.x. Re-pin, regenerate the determinism goldens as one reviewed act, and re-certify the DP stack row. Snapshotting the pools so Faker can be upgraded freely is non-breaking and is a Later candidate." It merges before row 93 (REL-GATE, D-4 launch engine freeze).

Target version (owner Q1, settled 2026-11-18): `T = 40.54.0`, released 2026-11-10, eligible under the 14-day rule on 2026-11-24. S0 measures on 40.54.0 now; S2 starts on or after 2026-11-24. The row text and `C:docs/roadmap/decisions.md` still say 40.31; C1 corrects both.

Anchors: a path with no prefix is in decoy-engine; the prefix `C:` is the CLI repository (decoy). Engine `origin/main` `ad36687a6` (engine 0.27.0); CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R2: a dependency lock change that moves frozen output), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `profiles/local-operations.md` (pre-merge done-state), `api-and-compatibility.md` (consumer inventory, explicit and coordinated break), `config-secrets-and-supply-chain.md` (reproducible, attributable dependency inputs and lockfiles), `testing.md` (T0 to T4; a dependency lock and a version pin escalate to the full suite), `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation; copies kept equal by a guard; prove the walk sees a seeded bypass), `reuse-first.md` (online search first; vendoring needs a recorded rationale), `proportionality.md` (size, deletion test, no pin that ordinary changes hand-edit), `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md` (anchored validation, strict types, no exception context).

Risk: R2. No engine logic changes, but the change moves deterministic output for some provider and locale pairs, changes the dependency lock twice (S1 adds a test-only tool, S2 moves Faker), and re-pins the DP certified rows. Approver: Cam (owner) for the post-1.0 rule and questions A to D; Dennis then Codex for the plan gate and the S1 and S2 code gates.

## 0. What the stale branch learned

`origin/fix/faker-40-31-migration` (`071b7d005`, 2026-09-25, no PR, about 994 commits behind main, base `0d69bffa5`) is read, not rebased. It holds two commits:

1. `a7b8d6691` bumped to 40.31.0 after finding that the 2026-07-23 claim ("40.31.0 drops five person providers and shifts the name pools") does not reproduce: `dir(Faker())` is identical between the two versions (305 names), the proof manifest was byte-identical, and every Faker-tagged test then on main passed unmodified.
2. `071b7d005` reverted the bump. The five-provider "drop" is real but has nothing to do with Faker: the optional `mimesis` extra rebinds `person_name`, `person_first_name`, `person_last_name`, `person_full_name` and `person_email` to `MimesisAdapter` (adoption matrix in `src/decoy_engine/providers_v2/_registry.py`), so they leave `faker_providers()` on either Faker version. The revert reason was the DP certified profile fingerprint: Faker is in the hashed distribution set, so the bump moved the row (`895b9a20...` to `234120d1...`) and failed `dp-certified-gate` and the CLI certified profile. Cam held the bump because re-certifying DP was a separate decision. That decision is now taken.

Kept: the root cause (no registry fix is needed) and the three additive regression tests in `tests/unit/providers_v2/test_faker_adapter.py` (`TestPersonProvidersSurviveFakerVersion`), replayed by patch in S1. Not kept: the edit to `tests/unit/providers_v2/test_registry.py::test_known_faker_provider_present` (it makes an existing test conditional on `mimesis`; no CI job installs `mimesis`, so the test is green as it stands) and the docstring note in `tests/sentry/test_proof_manifest.py` (follow-up F-1).

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. The engine pins `faker==40.54.0`. `pyproject.toml`, `uv.lock`, `NOTICE`, the output lock, `tests/parity/_f0_fixtures.py::PINNED_FAKER_VERSION`, and in the CLI `requirements-certified.txt` and `requirements-dev.lock` all name 40.54.0, and a sentry in each repo fails when a copy differs.
2. Before the pin moves, S1 commits a Faker output lock captured under 40.23.0. It covers both Faker call surfaces the engine has (4.1): the reflected surface used by `faker_type` columns, and the V2 adapter surface used by the masking `faker` strategy. For every Faker locale and every provider name on each surface, it records the provider's keyword-argument names, a per-seed digest, a sequential-draw digest, and whether the output depends on the calendar. It is computed in separate processes under a process-wide frozen clock. The S2 diff of the lock is the reviewed list of every changed, added, removed and newly reproducible pair.
3. Every golden that moves under 40.54.0 is rewritten by the tool that owns it (section 5.6). No golden file and no digest literal is edited by hand, no test assertion is weakened, and the S2 diff under `tests/` touches only the paths section 5.6 owns (G-3).
4. The DP certified rows are re-pinned with the existing tools: the engine dev/CI row through `scripts/release/dp_rows.py` (checked by `tests/sentry/test_dp_lock_row.py`), in S1 for the test-tool addition and in S2 for Faker, and the CLI pristine row through `C:scripts/cert_smoke.py` in C1. Prior rows stay, so snapshots fitted on an older row still compile. The DP mechanism does not read Faker output (the proof-critical set is opendp, dp-accounting, numpy, scipy, pandas and pyarrow, `quality/dp_provenance.py`); Faker is in the row only because the row hashes the whole installed set. Re-certification is therefore a re-pin plus a `dp-certified-gate` run with no skips, not a new DP proof.
5. The output change is a pre-GA correction: one changelog fragment with a `Breaking:` line for changed and removed pairs and a separate "now reproducible" line for pairs that move from unstable to a digest (`uuid1`, `uuid7`). `docs/compatibility-contract.md` section 1 records it as "Pre-GA corrections taken with the Faker repin" and states that the platform stays on Faker 40.23.0 while it is parked.
6. After 1.0, compatibility contract section 3.3 states (owner question C): a Faker bump may ship in a 1.x release only when the output lock diff has no changed digest, no removed provider, locale or keyword argument, and no pair that became unstable or calendar-dependent. Added providers, added locales and pairs that became reproducible are allowed. Any other diff is a 2.0 change. The freeze covers the default install on the platforms of owner question A; the `mimesis` extra is outside it (owner question B). The sentry makes every lock change visible; the release gate decides which diffs a 1.x release may carry.
7. No engine logic changes. Masking, generation, the native kernels, the derivation and `SEED_PROTOCOL_VERSION` are untouched.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- Snapshotting or vendoring Faker's providers (row text: Later, non-breaking). Section 2 says why not 1.0.
- Fixing providers whose production output changes with today's date (follow-up F-4, goes to the roadmap inbox). The lock freezes the calendar to make such pairs checkable; it does not change what users get.
- Making the proof manifest independent of the `mimesis` extra (F-1).
- Widening `POOL_ELIGIBLE_FAKER_TYPES` or `POOL_ELIGIBLE_LOCALE_PAIRS` (F-3).
- The `test_registry.py` mimesis edit from the stale branch.
- Other dependency bumps. Dependabot PR E#583 bundles Faker 40.54.0 with five other packages and touches only `pyproject.toml` (the same mix as #47, which caused the 2026-07-23 confusion). S2 supersedes its Faker part (owner Q6).
- Provider kwargs values. The lock records each provider's keyword-argument names, but calls the reflected surface with no arguments (residual risk R-2).

## 2. Established solutions

Search run: Faker's documentation on seeding and versions; NumPy NEP 19 (random number generator policy) and the NumPy random compatibility policy; the CPython `random` reproducibility note; snapshot ("approval") testing in Python (pytest-regressions `data_regression`, syrupy); clock freezing in Python tests (`time-machine`, `freezegun`); Dependabot grouping; a source diff of the Faker wheels 40.23.0, 40.31.0 and 40.54.0 taken from PyPI. In the codebase: the faker-determinism harness (`scripts/faker-determinism/`, subprocess workers with a pinned environment), the F0 parity oracle (`tests/parity/`), the runtime-lock probe (`support/_probe.py`), the DP row tooling (`scripts/release/dp_rows.py`), and the stale branch.

| Need | Established solution | What we take | What we do not take, and why |
|---|---|---|---|
| Know whether Faker output is stable across releases | Faker documentation ("Seeding the Generator"): "A Seed produces the same result when the same methods with the same version of faker are called"; "results are not guaranteed to be consistent across patch versions"; "If you hardcode results in your test, make sure you pinned the version of `Faker` down to the patch number" | Exact pin (already in place); every Faker release, patch included, is an output change until proven otherwise | Ranged pins |
| Freeze a random stream for users while the library improves | NumPy NEP 19: the legacy `RandomState` stream is frozen, with no more changes "not even to fix correctness bugs", while `Generator` may break stream compatibility "with caution"; CPython `random` keeps a backward-compatible seeder when seeding changes | The same split by version: 1.x freezes the Faker output it ships with; a better Faker stream is a 2.0 change | Two Faker backends side by side in one engine (the `RandomState` model): it doubles the provider surface for a rare case. Vendoring is the later answer if a bump is needed inside 1.x |
| Detect an output change before it merges | Snapshot or approval testing (pytest-regressions `data_regression`, syrupy): a committed snapshot, a test that diffs against it, an explicit regenerate command whose diff is reviewed | One committed JSON snapshot, one sentry that diffs it, one writer whose diff is the review artifact | A snapshot library: the engine already has a versioned digest codec (`scripts/faker-determinism/digest_codec.py`, `CODEC_VERSION = 1`) and the same pattern in `check_determinism.py --write-golden` |
| Make clock-reading code deterministic in a test | `time-machine` (maintained, C-level patch of `time.time`, `time.time_ns`, `datetime.now`, `date.today` and friends for the whole process); `freezegun` (pure-Python, patches by module scan) | `time-machine`, started before `faker` is imported in each worker process, so default arguments evaluated at import (for example `passport_dates(birthday=date.today())`) are frozen too | Patching `faker.providers.date_time` only (today's `frozen_faker_clock`): it misses `ssn` in `fi_FI`, `lv_LV`, `et_EE`, `zh_CN` (`date.today()`), `no_NO`, `sv_SE` (`datetime.now()`), `ru_RU` company (`now().year`) and the `en_US` passport default. `freezegun`: slower, and it misses already-imported references that `time-machine` covers |
| Determinism across processes and environments | The engine's own harness: `check_determinism.py` spawns fresh workers with `TZ=UTC`, `LC_ALL=C`, `LANG=C` and several `PYTHONHASHSEED` values | The same worker environment for the lock writer and sentry | A new harness |
| Keep a bot from bumping a pinned dependency without review | Dependabot `groups` with `exclude-patterns` | Faker leaves the `python-minor-patch` group, so it gets its own PR, which the lock sentry judges alone | Ignoring Faker updates: the bot PR plus the sentry is the early warning a 1.x security bump needs |
| Decouple Decoy from Faker's data churn | Vendoring the data (copy the provider tuples and formats, keep the MIT notice) | Recorded as the Later row the roadmap already names | Not in 1.0: about 100 locales and 200 methods of code plus data. Non-breaking to add after 1.0; the lock is its acceptance test |

Source diff findings (wheels unpacked and diffed 2026-11-18; S0 repeats this for 40.54.0 against 40.23.0 in one pass):

- 40.23.0 to 40.31.0: no change to `en_US`, `en_GB` or `fr_FR` provider data. Changed: `es_ES` `bban` and `iban` (computed CCC control digits), `de_DE` `vat_id` (ISO 7064 check digit), `nl_BE` bank codes, `pt_BR` `job` and `phone_number`, `ko_KR` region and country names, base `pyint`/`pyfloat` when both bounds collapse to one value (was infinite recursion), base `bank()` without a bank list raises `NotImplementedError` instead of `AttributeError`. Added: locale `mk_MK`, `pt_BR` `cin` and bank, `sr_BA` `ssn`, `es_MX` automotive.
- 40.31.0 to 40.54.0, in addition: base `uuid1` and `uuid7` draw their timestamp from the seeded generator instead of the wall clock (reproducible under a seed), base `currency` list follows current ISO 4217 codes, `en_GB` `vat_id` check digits, base `date_time` when start equals end, base `pyfloat` refuses `positive=True` with `max_value <= 0`, `file_path` gains the keyword argument `allowed_path_traversal_elements`, bank and ssn data in about ten more locales, and a new optional `image` extra (`pillow`) in the package metadata.
- The 2026-07-23 "Tomas to Tricia" name shift is in neither diff: `faker/providers/person/en_US` is unchanged across all three versions. This agrees with the stale branch.

Remaining custom code: one writer (about 220 lines including the worker entry) and two sentries (about 300 lines) over the existing reflection surface, adapter, codec and worker-environment pattern.

## 3. Reuse inventory

- `decoy_engine.internal.faker_setup.make_faker` (`faker_setup.py:639`) and `get_faker_providers(..., provider_snapshot=...)` (`faker_setup.py:465`): the reflected surface a `faker_type` column uses, `_FAKER_DENYLIST` (`faker_setup.py:347`) applied; `reflected_kwargs` (`faker_setup.py:416`) gives each provider's keyword-argument names.
- `decoy_engine.providers_v2.FakerAdapter.generate_batch` (`providers_v2/_faker_adapter.py:194`) with `_FAKER_METHOD_MAP` (`_faker_adapter.py:43`) and `_FAKER_DEFAULT_KWARGS` (`_faker_adapter.py:73`): the masking surface.
- `scripts/faker-determinism/digest_codec.py::_pool_digest`: type-tagged, length-framed encoding of a value list.
- `scripts/faker-determinism/check_determinism.py`: the worker environment (`TZ`, `LC_ALL`, `LANG`, `PYTHONHASHSEED`) and its `--write-golden` owner role for `golden_digests.json` and `certified_pairs.json`.
- `tests/parity/_f0_fixtures.py::ORACLE_CLOCK` (2026-10-16 12:00): the lock uses the same instant as a literal, so the writer does not import `tests/`.
- `scripts/gen_proof_manifest.py`, `scripts/gen_capability_matrix.py`, `tests/parity/_f0_capture.py`, `tests/parity/_fr0_refreeze.py`, `scripts/test_flight.py` write mode, `scripts/dev/licenses_write.sh`, `uv lock`, `scripts/release/dp_rows.py` and `scripts/release/stamp_release.py`, `C:scripts/cert_smoke.py`, `C:scripts/dev/lock.sh`: the owning tools of section 5.6 and C1.
- `tests/sentry/dependencies/` for the new sentries; `tests/physical/test_faker_determinism_driver.py` shows how a test loads a module from `scripts/faker-determinism/` by file path.
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
  "clocks": ["2026-10-16T12:00:00Z", "2027-11-20T12:00:00Z"],
  "locales": {
    "<locale>": {
      "resolved": "<locale>" | "fallback:en_US",
      "reflected": {
        "<provider>": {
          "kwargs": ["<name>", ...],
          "per_seed": "<64 hex>" | "raises:<ExceptionClassName>" | "unstable",
          "sequential": "<64 hex>" | "raises:<ExceptionClassName>" | "unstable",
          "calendar": false | true
        }
      },
      "adapter": {
        "<semantic name>": {
          "batch": "<64 hex>" | "raises:<ExceptionClassName>" | "unstable",
          "calendar": false | true
        }
      }
    }
  }
}
```

Worker (`python scripts/faker-determinism/output_lock.py --worker --clock <iso>`), one process:

1. Start `time_machine.travel(<clock>, tick=False)` before importing `faker` or `decoy_engine`, so module-level and default-argument clock reads are frozen as well as calls.
2. For each `locale` in `sorted(faker.config.AVAILABLE_LOCALES)`: `fake = make_faker(locale)`; `resolved` is the locale or `fallback:en_US` when `make_faker` fell back (L5). Reflected surface: `providers = get_faker_providers(fake, provider_snapshot={})` (M4: no custom provider can enter the lock).
3. For each reflected `name`: `kwargs` is the sorted keyword-argument names from `reflected_kwargs`. `per_seed`: on a fresh `make_faker(locale)`, for `i` in `range(8)`, `seed_instance(i)` and one call with no arguments (the per-row generation shape). `sequential`: on a fresh instance, `seed_instance(0)` then 8 calls in a row (the pool-build shape). Each list goes through `_pool_digest` and SHA-256.
4. Adapter surface: for each semantic name in `_FAKER_METHOD_MAP`, a fresh `FakerAdapter`, then `generate_batch(name, spec=ProviderSpec(locale=locale, seed=(0).to_bytes(8, "big"), deterministic=False), count=8)`. This goes through `Faker(locale)` at `_faker_adapter.py:229` and applies `_FAKER_DEFAULT_KWARGS`, which the reflected surface does not.
5. A call that raises records `raises:<class name>`: the class only, never the message.
6. The worker prints one JSON document on stdout.

Writer (`python scripts/faker-determinism/output_lock.py --write`):

1. Refuses with exit 1 and a fixed message when the installed Faker is not the `pyproject.toml` pin.
2. Runs the worker at clock A (`2026-10-16T12:00:00Z`, the F0 `ORACLE_CLOCK` instant) in three processes with `TZ=UTC`, `LC_ALL=C`, `LANG=C` and `PYTHONHASHSEED` 0, 1 and 2, and once at clock B (A plus 400 days).
3. A digest that differs between the three clock-A processes becomes `unstable`. A digest that is equal across processes at clock A but differs at clock B is kept (the clock-A value) with `calendar: true`. Everything else is a digest with `calendar: false`.
4. Writes the file.

Sentry (`tests/sentry/dependencies/test_faker_output_lock.py`): runs the worker at clock A in one subprocess (same pinned environment, `PYTHONHASHSEED=0`) and at clock B once, and diffs against the lock. It never compares a stored `unstable` value; it checks that the name is still present and still unstable. The diff has six kinds, each reported with names only: changed, removed (provider, locale or keyword argument), added, newly reproducible (unstable to digest), newly unstable (digest to unstable) and newly calendar-dependent. The message gives the installed and locked Faker versions and ends: "Faker output moved. Before 1.0: regenerate with output_lock.py --write in the repin PR. After 1.0: see compatibility contract 3.3 for which kinds a 1.x release may carry."

Reviewed lists in the sentry file (H3), each entry with a one-line reason, and each re-verified against the lock on every run:

- `EXPECTED_UNSTABLE`: the pairs recorded `unstable` (under 40.23.0, for example `uuid1` and `uuid7` in every locale: wall clock).
- `EXPECTED_RAISES`: the pairs recorded `raises:` (for example `bank` in locales with no bank list).
- `EXPECTED_CALENDAR`: the pairs recorded `calendar: true` (for example `ssn` in `fi_FI`, `lv_LV`, `et_EE`, `zh_CN`, `no_NO`, `sv_SE`; `company` in `ru_RU`; `passport_dates` and `passport_dob` in `en_US`; the `date_this_*` family).
- `ANCHORS`: pairs that must be digests on both surfaces where they exist: `first_name`, `email`, `address`, `currency_code` in `en_US`, `bban` in `es_ES`, `vat_id` in `en_GB`, and the adapter names `person_first_name` and `person_email` in `en_US`.
- `EN_US_DIGEST_FLOOR`: the minimum number of `en_US` reflected pairs that are digests, set in S1 to the captured count. Only a drop below it fails.

The three expected sets must equal the lock's sets exactly; a pair that leaves or joins one of them without an edit to the list fails, and the list edit shows in review.

Runtime budget: about 100 locales times about 200 providers times 16 calls, twice. S1 measures the sentry on the Dell or the Mac and records the time in the PR. If it is over 30 seconds there, it gets the marker `faker_output_lock` and a required CI job `faker-output-lock` with no path filter (in `ci/required-jobs.toml`), and leaves the default loop. Otherwise it runs in the default loop. Either way it also runs in the `import-smoke` job on CPython 3.11.9 and 3.12.7 (H2); that step installs the `dev` extra.

Platform scope (owner question A, recommended): Linux (CI) is blocking. S1 runs the sentry once on the Mac and records the result in the PR; a Mac difference is a finding for the owner. When WIN-RUNNER (row 6) lands, a Windows leg runs the sentry and becomes blocking; a Windows-only difference is fixed in the engine, not excluded from the lock.

### 4.2 The version-agreement sentry (S1)

`tests/sentry/dependencies/test_faker_pin_agrees.py`: the single `faker==` pin in `pyproject.toml`, the `faker` version in `uv.lock`, the `faker==` line in `NOTICE`, the lock's `faker_version`, and `tests/parity/_f0_fixtures.py::PINNED_FAKER_VERSION` are equal. The `pyproject.toml` pin is the one fact. `uv.lock` and `NOTICE` are generated from it; the lock version and `PINNED_FAKER_VERSION` record the version a capture was taken under, and a capture under a different version is stale. Versions are compared as full strings with `re.fullmatch` on `\d+\.\d+\.\d+` first (L3). In S2 it gains `test_dependabot_excludes_faker`, which parses `.github/dependabot.yml` with `yaml.safe_load` (L2).

### 4.3 The test-tool addition (S1)

`time-machine` joins the `dev` extra with an exact pin, as the other dev tools. `dev` is part of the certified DP profile (`dev+lint+vault+cloud`), so S1 also: regenerates `uv.lock` (only the `time-machine` block and the `dev` extra change), regenerates `NOTICE`, and adds the new dev/CI row to `_CERTIFIED_STACKS` through `dp_rows`, prior rows kept. The CLI pristine row is not affected (no `dev` tooling in it).

### 4.4 The repin (S2)

In this order, on one branch, each step by its owning tool:

1. `pyproject.toml`: `faker==40.54.0`. The comment above the pin is rewritten to the verified history: the 2026-07-23 claim was the `mimesis` rebinding; the pin moves only with the output lock and the DP rows; after 1.0 see compatibility contract 3.3.
2. `uv lock --upgrade-package faker==40.54.0`. The `uv.lock` diff may touch only the `faker` package block (including its new optional `image` extra on `pillow`, which no profile installs) and the `decoy-engine` requirement (AT-P2).
3. `scripts/dev/licenses_write.sh` (NOTICE).
4. `python scripts/faker-determinism/output_lock.py --write`. The lock diff, as names grouped by diff kind, goes into the PR body. The reviewed lists of 4.1 are updated in the same commit, each changed entry with its reason.
5. Every golden that the S0 record marks "moved" in section 5.6, by its tool, in the table's order.
6. DP: the new dev/CI fingerprint from `dp_rows` is added to `_CERTIFIED_STACKS` (`quality/dp_provenance.py:272`), newest first, prior rows kept. A fresh `uv sync --frozen --extra dev --extra lint --extra vault --extra cloud` on CPython 3.10.20 reproduces it.
7. `support/_probe.py` `PROBE_GOLDEN[7]`: only if S0 shows the probe moved. Expected not: the probe pools `person_first_name` in `en_US`, unchanged in both diffs. If it moves, the value comes from `run_probe()` on the repinned venv and the fragment names it, as `_probe.py:49` requires.
8. Changelog fragment `changelog.d/faker-migrate.md`: a `Breaking:` line ("deterministic `faker` output changes for the listed provider and locale pairs; re-run masking to keep joins stable across the change"); under it, the changed and removed pairs grouped by locale; a separate "Changed" bullet: "`uuid1` and `uuid7` are now reproducible under a seed"; and a bullet for the new `pyfloat` refusal.
9. `docs/compatibility-contract.md`: section 1 gets "Pre-GA corrections taken with the Faker repin (FAKER-MIGRATE)", including that the parked platform stays on Faker 40.23.0 until it repins; section 3.3 gets the rule of 1.1 item 6 with the platform scope (question A) and the `mimesis` exclusion (question B); the section 5 decision table gets the row "Bump Faker so the output lock changes, loses a provider, locale or keyword argument, or gains an unstable or calendar pair: Yes (major)". `docs/determinism.md`: one paragraph that points at the lock.
10. `.github/dependabot.yml`: `exclude-patterns: ["faker"]` on the `python-minor-patch` group.

### 4.5 CLI (C1)

After the engine release that carries S2 and its stamped DP rows (E-REL):

1. `C:requirements-certified.txt`: the `faker==` pin (line 64 on `920ea13c`) becomes `faker==40.54.0`; the header gets the new engine version, the new fingerprint from `C:scripts/cert_smoke.py`, and one more entry in its row history.
2. `C:requirements-dev.lock`: regenerated through `C:scripts/dev/lock.sh`, never by hand.
3. Engine repin per the engine repin checklist, including the CI install, the release smoke and the fresh-install smoke that read `requirements-certified.txt` (`C:.github/workflows/ci.yml`).
4. `C:docs/guides/shape-and-privacy/04-differential-privacy.md`: the install line, if it names versions.
5. `C:docs/release/frozen-surfaces.md`: the Faker version row.
6. `C:docs/roadmap/release-gates.md` D-4 text "Faker 40.23.0" becomes "Faker 40.54.0"; `C:docs/roadmap/groups/mask.md` row text "40.31" becomes "40.54.0" and the row state moves; `C:docs/roadmap/decisions.md` gets a dated line that the target moved from 40.31 to 40.54.0 (owner 2026-11-18).
7. CLI goldens the S0 record lists, each by its tool; CLI CHANGELOG entry.
8. CLI sentry `C:tests/sentry/test_faker_pin_agrees.py`: both CLI requirement files name the Faker version the installed engine requires.

## 5. Enumerations

### 5.1 Exit paths

The change adds no runtime refusal. The exits are those of the new tools and of existing provider calls whose behaviour moves:

- `output_lock.py --write`: exit 0 with the file written; exit 1 with a fixed message when Faker or `time_machine` does not import, a worker fails, or the installed Faker is not the pin at `pyproject.toml:74`.
- `test_faker_output_lock.py`: pass, or fail listing names per diff kind (AT-L1 to AT-L12).
- `test_faker_pin_agrees.py`: pass, or fail naming the file that disagrees (AT-P1).
- A `faker_type: bank` column in a locale with no bank list: today `AttributeError` from Faker, after S2 `NotImplementedError`. The engine has no `except AttributeError` around provider calls (the only one is the locale fallback at `faker_setup.py:660`), so both reach the same generic provider-failure path. AT-B1 pins that the reason code and exit do not change.
- `pyfloat` with `positive=True` and `max_value <= 0`: Faker 40.54.0 raises `ValueError` where 40.23.0 returned a value. Same generic path; AT-B1 pins its reason code; the fragment lists it.
- DP fit on a venv with no matching row: `dp_stack_uncertified` (existing, `quality/dp_provenance.py:369`); after S1 and S2 add their rows it passes.
- Resume of a run started before the repin: the run fingerprint includes the Faker version (component list in `tests/unit/delivery/resume/test_fingerprint.py:18`), so resume is refused with the existing fingerprint-mismatch refusal, as for any engine bump.

### 5.2 Routes

Every route that turns Faker into output uses one of two surfaces, and the lock covers both:

- Masking `faker` strategy: `execution/_strategies/_faker.py:89` builds the pool with `PoolBuilder` over the V2 registry. The Faker backend is `FakerAdapter.generate_batch`, which builds `Faker(locale)` directly (`providers_v2/_faker_adapter.py:229`), seeds it once and draws sequentially, with `_FAKER_DEFAULT_KWARGS` applied. Lock surface: `adapter`. Native and chunked masking only derive indices into that Python-built pool (the Rust kernel holds no Faker data), so they move exactly with the pool.
- Faker text spans: `transforms/_faker_span.py:32` reuses one default-locale `Faker()` per thread and seeds it before every draw. Default locale is `en_US`, so the `en_US` reflected `per_seed` digests cover it.
- Generation per-row `faker` columns: `generation/synthesize.py:449` (`_faker`), one seeded call per row through `faker_setup`. Lock surface: `reflected`, `per_seed`.
- Generation pooled `faker` columns: `generation/_faker_pool.py:359` (`make_faker(effective_locale)`), seeded once per pool. Lock surface: `reflected`, `sequential`.
- Composite person generation: `generation/composite/_person.py`, through the registry. Lock surface: `adapter`.
- Runtime-lock probe: `support/_probe.py:95` (`_pool_part`), Faker adapter pinned. Lock surface: `adapter`.
- Capability reporting: `providers_v2/_real_registry.py:27` records `faker.VERSION` as `backend_version`, which feeds `_providers_digest` (`support/_runtime_lock.py:280`) and `docs/capability-matrix.md`.
- If E#661 (GEN-PROVIDERS E1, the `provider` generate type) merges before S2, its route joins this list in a plan revision, and the lock gains the surface it calls, before S2 builds.

### 5.3 FK shapes

N/A: this change produces no FK keys and touches no FK machinery; an FK column with a `faker` strategy moves like any other column of that provider and locale.

### 5.4 Fields

- `output_lock.json`: top level `lock_version`, `faker_version`, `codec_version`, `samples`, `clocks`, `locales`; per locale `resolved`, `reflected`, `adapter`; per reflected pair `kwargs`, `per_seed`, `sequential`, `calendar`; per adapter pair `batch`, `calendar`. Closed sets; the sentry refuses an unknown or missing key and a value of the wrong type (`calendar` is a strict bool).
- Runtime lock `faker` field (`support/_runtime_lock.py:327`): the value moves from `40.23.0` to `40.54.0`; the field set does not change.
- Capability matrix `backend_version` for Faker-backed providers: `40.54.0`.
- DP certified rows: one new dev/CI row in S1 (time-machine), one in S2 (Faker), one new CLI row in C1; none removed.

### 5.5 Output surfaces

- Deterministic `faker` output for the pairs the lock diff lists (masked files, generated files, sample output).
- The runtime lock `faker` field and `providers_digest`; the probe only if S0 shows a move.
- `docs/proof-manifest.json`, `docs/capability-matrix.md`, `NOTICE`.
- No reason code, no log line, no CLI flag and no `--json` key changes.

### 5.6 Goldens and their owning tools

S0 runs every check below under 40.54.0 and marks each row "moved" or "unchanged". S2 regenerates only the moved rows, each by its tool. A red test that no row owns stops S2 (FM-4).

| Golden | Check that reads it | Owning tool | Expected under 40.54.0 |
|---|---|---|---|
| `scripts/faker-determinism/output_lock.json` and the reviewed lists in its sentry | `tests/sentry/dependencies/test_faker_output_lock.py` | `output_lock.py --write`; list entries edited with a reason | moved (by design) |
| `scripts/faker-determinism/golden_digests.json`, `certified_pairs.json` | `check_determinism.py` (marker `determinism_harness`) | `check_determinism.py --write-golden` | likely unchanged: the 5 harness locales change only in bank, VAT and currency types, which are not harness candidates |
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
| `tests/fixtures/golden/*` CSV inputs | V2 fixture tests | `scripts/build_golden_fixtures.py` | not regenerated: test inputs built with Faker, not outputs. Only if a reproducibility check reads them and fails does S2 rebuild them, and the downstream checks must then stay green on the new inputs |
| `tests/integration/compat_corpus/runtime-lock/*.json`, `tests/unit/delivery/resume/test_fingerprint.py` vectors | reader and fingerprint tests | none | unchanged: hand-written format samples whose `40.23.0` is data, not the installed version |
| CLI goldens | CLI e2e | each one's tool | measured in S0 (CLI part), rewritten in C1 |

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Faker pin | `faker==40.23.0` | `faker==40.54.0` | `pyproject.toml`, `uv.lock`, `NOTICE`, CLI requirement files, `output_lock.json` |
| Deterministic `faker` output | Faker 40.23.0 data | Faker 40.54.0 data for the pairs in the lock diff | changelog fragment `Breaking:`; compatibility contract section 1 pre-GA note |
| Faker output lock | none | `lock_version: 1` | `scripts/faker-determinism/README.md`; compatibility contract 3.3 |
| Post-1.0 Faker rule | the general 3.3 rule ("Faker seeding" in the section 5 table) | explicit diff-kind rule; default install only; platforms per question A | compatibility contract 3.3 and section 5 table |
| DP certified rows | rows up to engine 0.27.0 | plus two dev/CI rows (S1, S2) and one CLI row (C1) | `quality/dp_provenance.py`, `C:requirements-certified.txt` |
| D-4 launch engine | "Faker 40.23.0" | "Faker 40.54.0" | `C:docs/roadmap/release-gates.md`, `C:docs/release/frozen-surfaces.md` |
| Platform | Faker 40.23.0 | unchanged while parked | compatibility contract section 1 |

## 7. Failure modes and partial failure

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | A Faker release changes data for a provider the engine admits | the lock sentry fails, naming the pairs as "changed" | AT-L3 |
| FM-2 | A Faker release removes a reflected method, a locale or a keyword argument | the sentry fails, naming them as "removed" | AT-L4, AT-L9 |
| FM-3 | A Faker release adds a method or a locale | the sentry fails too (the lock is exact) and marks the change "added"; the bump PR rewrites the lock | AT-L5 |
| FM-4 | Under 40.54.0 a test goes red that no row of 5.6 owns | S2 stops and reports; the test is not edited. A plan revision adds its owner to 5.6, or it is a behaviour change taken to the owner | G-1 |
| FM-5 | A builder edits a golden or digest by hand | the S2 gate re-runs every owning tool on the S2 head; any difference fails the gate | G-2 |
| FM-6 | `uv lock` moves other packages | the `uv.lock` diff check refuses it | AT-P2 |
| FM-7 | A DP row is added but a fresh venv does not reproduce it | `test_dp_lock_row.py` fails on every gate host (it never skips) | AT-DP1 |
| FM-8 | The CLI repins an engine on 40.54.0 but keeps `faker==40.23.0` | CLI sentry fails; `cert_smoke.py` fails with `dp_stack_uncertified` | CV-P1, CV-DP1 |
| FM-9 | A provider reads the calendar through any clock API, at call time or at import | `time-machine` freezes it process-wide from before the import; the two-clock run marks it `calendar: true`; the sentry checks the calendar set exactly | AT-L6 |
| FM-10 | A provider reads something the frozen clock does not cover (wall-clock nanoseconds through a C call, OS entropy) | it differs across the writer's processes and is marked `unstable`; the unstable set is a reviewed list | AT-L7 |
| FM-11 | A provider call raises | recorded `raises:<class>`; a change of class shows as a changed pair (the `bank()` case) | AT-L8 |
| FM-12 | The writer degrades (for example marks every pair unstable) | the anchors and the `en_US` floor fail | AT-L10 |
| FM-13 | The masking surface drifts while the reflected surface is unchanged (an adapter default-kwarg change, or a Faker change only visible through `_FAKER_DEFAULT_KWARGS`) | the `adapter` digests change | AT-L11 |
| FM-14 | A difference only on another Python minor | the sentry runs in the 3.11 and 3.12 `import-smoke` legs | AT-L12 |
| FM-15 | The sentry is slow | the 30-second rule of 4.1 moves it to a required CI job with no path filter | S1 measurement |
| FM-16 | A Dependabot group PR bumps Faker with other packages | the group excludes Faker; a Faker PR stands alone and the lock sentry judges it | AT-P3 |
| FM-17 | E#661 and S2 both change Faker-fed goldens | whichever merges second re-runs every 5.6 tool and `output_lock.py --write` on its own head | G-2 on that head |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the slice head. All `test_faker_output_lock.py` cells that need a modified lock or modified reflection run the worker in a subprocess against a temporary lock path or with an injected stub module named on the worker command line; the committed lock is never edited by a test.

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-L1 | `tests/sentry/dependencies/test_faker_output_lock.py::test_lock_matches_installed_faker` | no lock | in the worker, `seed_instance(i + 1)` instead of `seed_instance(i)` | S1 |
| AT-L2 | `::test_lock_is_closed_and_strict`: closed key sets at every level, canonical bytes, `codec_version == digest_codec.CODEC_VERSION`, `samples == 8`, every digest matches `re.fullmatch(r"[0-9a-f]{64}")`, `calendar` is a strict bool | no lock | accept `"calendar": 1` | S1 |
| AT-L3 | `::test_changed_pair_is_named`: a stub makes one reflected provider return a different value; the failure names that provider and locale as "changed" and holds no value | no sentry | drop the changed-name list from the message | S1 |
| AT-L4 | `::test_removed_pair_is_named`: a stub removes one provider | no sentry | compare only names present on both sides | S1 |
| AT-L5 | `::test_added_pair_is_named_additive`: a stub adds one provider; the message says "added" | no sentry | treat added names as equal | S1 |
| AT-L6 | `::test_calendar_independent`: the computed calendar set equals `EXPECTED_CALENDAR`, and every pair outside it has the same digest at clock A and clock B | no sentry | drop `("ssn", "fi_FI")` from the frozen set (the clock freeze no longer applies to it, so the pair is not stable at clock A) | S1 |
| AT-L7 | `::test_unstable_set_is_reviewed`: the lock's unstable set equals `EXPECTED_UNSTABLE`; a lock copy that marks one stable pair unstable fails | no sentry | skip unstable names entirely | S1 |
| AT-L8 | `::test_raise_is_recorded_by_class`: a stub provider that raises records `raises:<class>`; the exception message never appears in the lock; the raises set equals `EXPECTED_RAISES` | no writer | record `str(exc)` | S1 |
| AT-L9 | `::test_removed_kwarg_is_removed`: a stub drops one keyword argument from a provider's signature; the failure names it as "removed" | no `kwargs` field | leave `kwargs` out of the comparison | S1 |
| AT-L10 | `::test_anchors_and_floor`: every `ANCHORS` pair is a digest; `en_US` reflected digests are at least `EN_US_DIGEST_FLOOR` | no sentry | the writer marks every pair unstable | S1 |
| AT-L11 | `::test_adapter_surface_covered`: the `adapter` names equal `_FAKER_METHOD_MAP` keys for `en_US` and `pt_BR`, and the `adapter` digests are compared | no adapter surface | `FakerAdapter` drops `_FAKER_DEFAULT_KWARGS` | S1 |
| AT-L12 | `.github/workflows/ci.yml` `import-smoke` runs the lock sentry on 3.11.9 and 3.12.7; `tests/sentry/tooling/test_ci_lanes.py` cell asserts the step exists | no step | remove the step | S1 |
| AT-L13 | `::test_lock_covers_engine_surface`: for `en_US` and `pt_BR`, the reflected names equal the keys of `get_faker_providers(make_faker(locale), provider_snapshot={})`: denylisted names absent, every admitted name present; a registered custom provider does not appear | no lock | pass the live provider snapshot instead of `{}` | S1 |
| AT-P1 | `tests/sentry/dependencies/test_faker_pin_agrees.py::test_copies_agree`: the five copies of 4.2 agree; a seeded cell with one copy changed fails naming the file | no sentry | drop `NOTICE` from the checked set | S1 |
| AT-P2 | gate check on the S2 head: `git diff origin/main -- uv.lock` touches only the `faker` package block (its new `image` extra included) and the `decoy-engine` requirement; S1's lock diff touches only `time-machine` and the `dev` extra | n/a (gate check) | an extra `--upgrade` in the lock command | S1, S2 |
| AT-P3 | `test_faker_pin_agrees.py::test_dependabot_excludes_faker`: `yaml.safe_load(".github/dependabot.yml")`, the pip group's `exclude-patterns` contains `faker` | no exclusion | remove the pattern | S2 |
| AT-S1 | `tests/unit/providers_v2/test_faker_adapter.py::TestPersonProvidersSurviveFakerVersion` (three tests replayed from `071b7d005`) | not on main | drop `"email"` from the V1 reflection loop | S1 |
| AT-B1 | `tests/unit/generation/test_faker_provider_failure_code.py`: (a) `faker_type: bank` in a locale with no bank list and (b) `faker_type: pyfloat` with `positive: true`, `max_value: 0` fail with a pinned engine reason code and exit category; (a) on 40.23.0 and 40.54.0, (b) on 40.54.0 (on 40.23.0 cell (b) is recorded as "returns a value") | the codes are not pinned today | a new wrapper that catches only `AttributeError` (the 40.54.0 run then leaks a raw `NotImplementedError`) | S1 (cell a), S2 (cell b on 40.54.0) |
| AT-DP1 | `dp-certified-gate` on the S1 and S2 heads: certified environment, the marked DP suites run, JUnit shows passed > 0 and no skip; `test_dp_lock_row.py` green | the old rows do not match the new lock | omit the new row from `_CERTIFIED_STACKS` | S1, S2 |
| AT-R1 | every 5.6 check marked "moved" is red with the pin moved and the golden not yet regenerated, and green on the S2 head; every row marked "unchanged" is green throughout | n/a (the regeneration act) | revert one regenerated golden file | S2 |
| AT-F1 | the fragment passes `tests/unit/scripts/test_check_fragment.py`, carries a `Breaking:` line, and lists `uuid1`/`uuid7` under "Changed", not under `Breaking:` | no fragment | move the `uuid1` line under `Breaking:` (the fragment check cell for diff kinds fails) | S2 |
| CV-P1 | `C:tests/sentry/test_faker_pin_agrees.py`: CLI `requirements-certified.txt`, `requirements-dev.lock` and the installed engine's `faker` requirement agree | no sentry | leave `40.23.0` in `requirements-dev.lock` | C1 |
| CV-DP1 | `C:scripts/cert_smoke.py` in a fresh 3.10.20 venv from `requirements-certified.txt` passes fit, `dps-marginal/v3` and generate | the CLI row is on 40.23.0 | omit the new CLI row | C1 |

Gate checks (run by the gate, not tests):

- G-1: every red test under 40.54.0 in S0 maps to a row of 5.6.
- G-2: on the S2 head (and on the head of whichever of E#661 and S2 merges second), each owning tool in 5.6 and `output_lock.py --write` run again and `git status` stays clean.
- G-3: the S2 diff under `tests/` touches only the paths 5.6 owns, the reviewed lists in `test_faker_output_lock.py`, the AT-B1 cell (b), the AT-P3 cell, and the `PINNED_FAKER_VERSION` line. Any other `tests/` path fails the gate.

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `scripts/faker-determinism/output_lock.py` | new (S1, about 220 lines): worker, writer, diff | Dev tooling: one-off tools in a topic folder, `scripts/faker-determinism/` | `check_determinism.py`, `digest_codec.py` |
| `scripts/faker-determinism/output_lock.json` | new (S1, generated) | same | `golden_digests.json` |
| `scripts/faker-determinism/README.md` | changed (S1): the lock, its writer, the reviewed lists and the post-1.0 rule | same | |
| `tests/sentry/dependencies/test_faker_output_lock.py` | new (S1, about 220 lines; loads `output_lock.py` by file path) | Sentry test: dependency rules in `tests/sentry/dependencies/` | `test_dependency_floors.py` |
| `tests/sentry/dependencies/test_faker_pin_agrees.py` | new (S1, about 80 lines; S2 adds the Dependabot cell) | same | same |
| `tests/unit/providers_v2/test_faker_adapter.py` | changed (S1, +64, replayed) | Unit tests | |
| `tests/unit/generation/test_faker_provider_failure_code.py` | new (S1, about 50 lines) | Unit tests mirroring `generation/` | other generation tests |
| `pyproject.toml`, `uv.lock`, `NOTICE` | changed (S1: `time-machine` in `dev`; S2: Faker) | | |
| `src/decoy_engine/quality/dp_provenance.py` | changed (S1 and S2, one row each with its comment line) | Quality | the other rows |
| `.github/workflows/ci.yml` | changed (S1: the `import-smoke` step) | Lightweight automatic PR checks | |
| `ci/required-jobs.toml` | changed only if the 30-second rule moves the sentry (S1) | CI lane registries | |
| moved goldens of 5.6 | changed (S2, by tool) | their existing places | |
| `src/decoy_engine/support/_probe.py` | changed only if S0 says so (S2) | Support bundles | |
| `changelog.d/faker-migrate.md` | new (S2) | Changelog fragments | |
| `docs/compatibility-contract.md`, `docs/determinism.md` | changed (S2) | Feature and contract docs | |
| `.github/dependabot.yml` | changed (S2) | Lightweight automatic PR checks | |
| `docs/records/2026-11-<dd>-faker-repin-impact.md` | new (S0) | Plans, decisions, records | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"): `C:requirements-certified.txt` and `C:requirements-dev.lock` (changed by their tools); `C:tests/sentry/test_faker_pin_agrees.py` (new, sentry test, beside the other CLI sentries); `C:docs/guides/shape-and-privacy/04-differential-privacy.md`, `C:docs/release/frozen-surfaces.md`, `C:docs/roadmap/release-gates.md`, `C:docs/roadmap/groups/mask.md`, `C:docs/roadmap/decisions.md`, `C:CHANGELOG.md` (changed). No new source module in either repo.

## 10. Design notes

- Choke point for "Faker output may not move unseen": the output lock and its sentry. Every route in 5.2 reads Faker through the reflected surface or the adapter surface, the lock walks both by reflection and by `_FAKER_METHOD_MAP`, and the installed Faker can change only through `uv.lock`. The walk is proved to see a seeded bypass (AT-L3, AT-L4, AT-L11, AT-L13). Mutation: pass the live provider snapshot (AT-L13) or drop the adapter default kwargs (AT-L11).
- Choke point for "one Faker version": the `pyproject.toml` pin. The other copies are generated or capture records, and AT-P1 and CV-P1 keep them equal.
- Why separate processes: `time-machine` must start before `faker` is imported, because some providers read the date in a default argument, which Python evaluates at import. The same processes give the cross-hash-seed check of the existing harness.
- Why two clocks: a frozen clock makes a calendar-reading pair stable but hides that it reads the calendar. Computing at two instants 400 days apart (past a year boundary and a leap day) separates "deterministic" from "deterministic only because the calendar is frozen", and the calendar set is then a reviewed list.
- Why lock under 40.23.0 first (S1 before S2): the S2 lock diff is then the complete, tool-made list of moved pairs.
- Why 8 samples and two draw shapes: `per_seed` is the per-row generation shape, `sequential` and `batch` are the pool shapes. 8 draws reach the random branches of almost every provider at a cost the default loop can carry.
- Why every Faker locale: `plan/checks/_generate_columns.py:230` admits any locale in `AVAILABLE_LOCALES`, and masking passes the configured locale straight to `Faker(locale)`.
- Why not vendor now: section 2. The lock is what a later vendoring row needs as its acceptance test.
- No new structure in `src/`. The tools print provider names, locale names, file names and versions only; Faker exception messages are never stored (AT-L8).

## 11. Size

| Slice | Src lines | Test and tool lines | Generated | Docs lines | Files touched |
|---|---|---|---|---|---|
| S0 | 0 | 0 | 0 | about 150 (record) | 1 |
| S1 | about 3 (DP row) | about 640 (writer and worker 220, lock sentry 220, pin sentry 80, replayed tests 64, AT-B1 50, CI step 6) | `output_lock.json` (size recorded in the PR), `uv.lock`, `NOTICE` | about 50 | about 12 |
| S2 | about 15 (pin comment, DP row, probe only if moved) | about 30 (AT-P3, AT-B1 cell b, reviewed-list entries) | `uv.lock`, `NOTICE`, the moved goldens of 5.6 | about 100 | about 12 plus the moved goldens |
| C1 | 0 | about 60 | the two CLI requirement files | about 40 | about 10 |

New public names: none in the engine package. No file passes its size ceiling.

## 12. Slices

| Slice | Repo | Content | Risk | Line budget | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|---|
| S0 | engine (record); runs on the Dell or the Mac, never the devbox | Build a clean venv from `origin/main` with `faker==40.54.0` (scratch lock, not committed). Run: the full default suite; `dp_certified` in the certified environment; `golden`; `ml` and `ner`; `determinism_harness`; `testflight`; the native companion suite; each marker set with the `scripts/dev/junit_ran.py` no-skip check; the proof-manifest and capability-matrix checks; the CLI e2e suite against that engine. Record each red test id, the 5.6 row that owns it, and moved or unchanged for every 5.6 row. Check by name: `date_time` with start equal to end, the new `file_path` keyword argument, the `pyfloat` refusal, `bank()` exception class. Repeat the wheel diff 40.23.0 to 40.54.0 | R0 (record only) | 150 docs | G-1 | none (Q1 settled) | none (it is the measurement); Codex reads the record |
| S1 | engine | `time-machine` in `dev` with its `uv.lock`, `NOTICE` and DP row; lock worker and writer; `output_lock.json` captured under 40.23.0; both sentries with the reviewed lists, anchors and floor; the `import-smoke` step; the three replayed tests; AT-B1 cell (a); README; the 30-second measurement and, if needed, the CI job; one Mac run recorded | R2 (dependency lock and DP row; no product change) | 650 test and tool, 5 src, 50 docs | AT-L1 to AT-L13, AT-P1, AT-P2, AT-S1, AT-B1 (a), AT-DP1 | none | Escalation triggers (dependency lock): T3 full suite on the Mac or Dell on the exact head against the saved main baseline; `dp-certified-gate`; each named mutation; Dennis then Codex |
| S2 | engine | The repin of 4.4: pin, `uv.lock`, `NOTICE`, lock rewrite and reviewed lists, moved goldens by tool, DP row, probe if moved, fragment, contract and determinism docs, Dependabot | R2 (moves frozen output; dependency lock; version pin; DP row) | 30 src, 40 test, 100 docs; generated files exempt | AT-P2, AT-P3, AT-DP1, AT-R1, AT-F1, AT-B1 (b), G-2, G-3 | S0 record read by the owner; S1 merged; on or after 2026-11-24 | T3 full suite on the Mac or Dell on the exact head against the saved main baseline; the S0 marker sets with the no-skip check; `dp-certified-gate`; each mutation; Dennis then Codex |
| E-REL | engine | The next daily engine release stamps the DP rows with the new engine version (`stamp_release.py`, existing release prep) | release train | n/a | `test_dp_lock_row.py` on the release head | S2 | release checks |
| C1 | CLI | The checklist of 4.5 | R2 (certified profile, repin) | 60 test, 40 docs; generated exempt | CV-P1, CV-DP1 | E-REL | CLI T1 (e2e that touch generation and masking, sentries) plus T2 on the head; `cert_smoke.py`; the CI release smoke and fresh-install smoke; Codex |

Order: S0 and S1 start now, in parallel (S1 does not depend on 40.54.0). S2 starts on or after 2026-11-24, after the owner has read the S0 record. S2 and C1 merge before row 93 (REL-GATE). Merge-order rule for goldens: whichever of S2, E#661 and FREEZE-OUTPUT merges later re-runs every tool in 5.6 and `output_lock.py --write` on its own head (G-2); goldens are never merged by hand. If E#661 merges before S2, a plan revision first extends 5.2 and the lock to the `provider` generate type.

Open PRs that touch the same files (checked 2026-11-18): E#583 (Dependabot group: `pyproject.toml`, Faker 40.23.0 to 40.54.0 plus five packages; superseded for Faker by S2, owner Q6); E#661 (GEN-PROVIDERS E1: `generation/_faker_pool.py`, `testflight/golden_fingerprints.json`, Faker pool tests); E#333 (parked draft).

## 13. Recurring-defect class check

- A test weakened to pass: every red test under 40.54.0 is either owned by a 5.6 tool or stops the slice (FM-4); G-3 limits the `tests/` diff to owned paths. The one literal that moves in a test file is `PINNED_FAKER_VERSION`, the capture record the F0 test names, and it moves only with the F0 recapture.
- A golden refreshed as a reflex: G-2 re-runs every tool on the head.
- Copies of a fact: the Faker version has five engine copies and two CLI copies, all generated or capture records, kept equal by AT-P1 and CV-P1.
- Anchored validation (catalog 1): digests and versions are checked with `re.fullmatch` (AT-L2, 4.2).
- Strict stored types (catalog 2): the lock refuses a non-bool `calendar` and unknown keys (AT-L2).
- Exception context (catalog 3): the tools store and print class names only and raise their fixed refusals outside `except` blocks.
- A dependency failure misread (the 2026-07-23 event): S0 reproduces every red in a clean venv on a test node from `origin/main`, never in a working venv.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a Faker value or exception text in the lock or a sentry message) | digests and class names only; messages carry names and versions | AT-L3, AT-L8 | record `str(exc)` in the lock | S1 |
| 2 | Cleanup on every exit | worker processes are run with a timeout and always reaped by `subprocess.run`; the clock freeze lives only in the worker process, so no test process keeps a frozen clock | AT-L1 (a hung or failing worker fails the sentry, never skips it) | leave `time_machine` travel running in the pytest process | S1 |
| 3 | State completeness (every lock entry kind and diff kind handled) | one diff function with one branch per kind: changed, removed, added, newly reproducible, newly unstable, newly calendar | AT-L3 to AT-L9 | merge "added" into "changed" | S1 |
| 4 | Route coverage (a Faker route the lock does not see) | two surfaces (reflected, adapter) and three draw shapes cover every route in 5.2 | AT-L11, AT-L13 | drop the adapter surface | S1 |
| 5 | Referential integrity | N/A: no FK or cross-table state changes (5.3) | none | none | none |
| 6 | Untrusted input | N/A: the lock, the requirement files and `dependabot.yml` are repo files written by tools or reviewers, not user input; the sentry still refuses unknown keys and wrong types (AT-L2) and parses YAML with `safe_load` | AT-L2, AT-P3 | accept unknown keys | S1, S2 |
| 7 | TOCTOU (lock computed on one Faker or clock, checked on another) | the lock records `faker_version` and `clocks`; the writer refuses when the installed Faker differs from the pin; AT-P1 ties the lock version to the pin; the clock is set before import | AT-P1, AT-L6 | start the clock after importing `faker` | S1 |
| 8 | Weak proof (a lock too coarse to see a change, or a degraded writer) | 8 draws in three shapes, two clocks, three processes, exact reviewed lists, anchors and an `en_US` floor | AT-L6, AT-L7, AT-L10 | the writer marks every pair unstable | S1 |
| 9 | Refactor drift | N/A: no source refactor; S2 changes a pin and data, and AT-P2 limits each `uv.lock` diff to its package | AT-P2 | an unrelated upgrade | S1, S2 |
| 10 | Frozen contract drift (output moves without its records) | pin, lock, goldens, DP rows, fragment, contract note and D-4 text move in S2 and C1 together | AT-R1, AT-F1, AT-DP1, CV-P1 | keep `faker==40.23.0` in the CLI dev lock | S2, C1 |

## 14. Pre-mortem

- "S2 refreshed a golden that hid a real regression." Guard: S0 maps every red to an owner before S2 starts (G-1); an unmapped red stops the slice (FM-4); G-3 limits the `tests/` diff; Dennis reads the lock diff against the wheel diff of section 2.
- "The lock passed because the calendar was frozen." Guard: two clocks and the reviewed calendar set (AT-L6).
- "The lock was green while masking moved." Guard: the adapter surface (AT-L11).
- "The DP gate went green by skipping." Guard: `dp-certified-gate` fails on any skip (`scripts/dev/junit_ran.py`), and `test_dp_lock_row.py` never skips.
- "We misread a dependency failure again." Guard: S0 runs in a clean venv on a test node from `origin/main`; the pin comment names the `mimesis` root cause.
- "After 1.0 a Faker security fix cannot ship." Answer: it ships in 1.x when the lock diff has only allowed kinds; otherwise the Later vendoring row is the path, or 2.0.
- "The lock sentry slows every test run." Guard: the 30-second rule of 4.1.
- "Two slices recapture the same goldens at once." Guard: the merge-order rule in section 12.

## 15. Residual risks

- R-1: a Faker change that shows only past the first 8 draws or on a rare branch (the `pyfloat` collapse case, `date_time` with start equal to end) is not in the lock. The harness and the other goldens see the admitted pool pairs; the per-row long tail relies on the lock.
- R-2: provider kwargs values from a config are not exercised. The lock records keyword-argument names (a removed name is caught), but a new keyword argument's effect, such as `file_path(allowed_path_traversal_elements=...)`, or a changed default inside an argument, is not. S0 checks the two named cases by hand.
- R-3: Faker import-time behaviour (locale fallback, a renamed locale) is seen only through `AVAILABLE_LOCALES`, `resolved` and the name sets. Multi-locale configs (a locale list, which `make_faker` accepts) are not in the lock; their output is a function of the single-locale providers it covers, but the proxy's locale choice is not checked.
- R-4: `make_faker` falls back to `en_US` for a locale Faker cannot build (`faker_setup.py:660`). The lock records `resolved` per locale, so a locale that starts falling back shows as a change, but configs that already fall back are locked as `en_US` output.
- R-5: platforms outside owner question A's blocking set (Mac before a Mac CI leg exists; Windows before WIN-RUNNER).

## 16. Owner questions (taken on the recommended answer; owner to confirm)

| Id | Question | Recommended | Why |
|---|---|---|---|
| Q1 | Target Faker version | Settled 2026-11-18: 40.54.0 | Carries seeded `uuid1`/`uuid7`, current ISO 4217 codes and `en_GB` VAT check digits into the frozen 1.x line |
| Q2 | Lock every Faker locale, or only the five harness locales? | Every locale | The engine admits any locale in `AVAILABLE_LOCALES`; a `pt_BR` user gets moved `job` output from this change |
| Q4 | Vendoring or snapshotting the providers: Later (1.x), not 1.0? | Later | Non-breaking after 1.0; large surface; the lock is its acceptance test |
| Q5 | Delete `fix/faker-40-31-migration` after S1 has replayed its three tests? | Yes, after S1 merges (owner-gated branch deletion) | Its conclusion is on main and its tests move in S1 |
| Q6 | Close Dependabot E#583, or rebase it without Faker? | Rebase without Faker (or let Dependabot reopen after the group exclusion lands) | Faker moves only in S2 with its lock |
| A | Platform scope of the freeze | Linux is blocking now; the Mac comparison is recorded in S1; the Windows leg becomes blocking when WIN-RUNNER (row 6) lands; a Windows-only difference is fixed in the engine, not excluded from the lock | The owner must demo on Windows, so Windows output must match Linux, not be carved out |
| B | Does the 1.x freeze cover the `mimesis` extra? | No: the freeze covers the default install; contract 3.3 says so | `mimesis` rebinds five providers and has its own data churn; the stale branch showed it changes the provider set |
| C | Which lock diff kinds may a 1.x release carry? | Added providers, added locales, and unstable to digest (newly reproducible). A changed digest, a removed provider, locale or keyword argument, and a pair that becomes unstable or calendar-dependent are 2.0 | A removed keyword argument breaks a config that passes it; becoming reproducible breaks nobody |
| D | How is the calendar handled in the lock? | `time-machine` under a pinned clock, computed at two instants; the production behaviour (fi_FI and sv_SE `ssn` output changes by day) goes to the roadmap inbox as F-4 | The lock must be deterministic to be a lock; fixing the product behaviour is a separate decision |

## 17. Follow-ups (outside the guarantee)

- F-1: the proof manifest depends on whether `mimesis` is installed at generation time (stale branch note). Pin the generation profile in `gen_proof_manifest.py` or record it in the manifest. Maintenance row.
- F-2: the Later row "snapshot Faker providers" takes `output_lock.json` as its acceptance oracle.
- F-3: if S0 shows newly certifiable pool pairs under 40.54.0, a widening row may admit them after 1.0 (additive).
- F-4 (roadmap inbox, not this plan): deterministic `ssn` output in `fi_FI` and `sv_SE` (and the other calendar pairs in `EXPECTED_CALENDAR`) changes with today's date in production, so the same config masked on two days can differ. Decide whether to pin the clock Faker sees during a run.
