Status: plan (revision 3.5, 2026-11-19; FAKER-REPRO R1 owns the CI run line and lane-coverage rule; FAKER-REPRO R1 outputs added; S1 review round 4 caller-argument and calendar findings addressed; Dennis round 2 GO-WITH-FIXES addressed; owner Q1 settled; owner Q11 and questions A to D decided 2026-11-18 (recommended); final Codex gate GO-WITH-FIXES addressed)

# FAKER-MIGRATE: move the launch engine from Faker 40.23.0 to 40.54.0 before the 1.0 freeze, and lock Faker output after it

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

Roadmap row FAKER-MIGRATE (`C:docs/roadmap/groups/mask.md`, 1.0 table, on `C:claude/focused-sagan-0arhsp` `da7ebc7f`): "Move the launch engine from Faker 40.23.0 to 40.31 before the freeze (owner 2026-11-18). Faker's name and data pools are not semver-stable, so the Faker release that ships in 1.0 fixes deterministic `faker` output for the life of 1.x. Re-pin, regenerate the determinism goldens as one reviewed act, and re-certify the DP stack row. Snapshotting the pools so Faker can be upgraded freely is non-breaking and is a Later candidate." It merges before row 93 (REL-GATE, D-4 launch engine freeze).

Target version (owner Q1, settled 2026-11-18): `T = 40.54.0`, released 2026-11-10, eligible under the 14-day rule on 2026-11-24. S0 measures on 40.54.0 now; S2 starts on or after 2026-11-24 and after the freeze-batch engine release. The row text and `C:docs/roadmap/decisions.md` still say 40.31; C1 corrects both.

Anchors: a path with no prefix is in decoy-engine; the prefix `C:` is the CLI repository (decoy). Engine `origin/main` `ad36687a6` (engine 0.27.0); CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R2: a dependency lock change that moves frozen output), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `profiles/local-operations.md` (pre-merge done-state), `workspace-and-vcs.md`, `reuse-first.md`, `exploration.md`, `scope-discipline.md`, `proportionality.md`, `verification.md`, `code-review.md`, `testing.md` (T0 to T4; a dependency lock and a version pin escalate to the full suite), `architecture.md` (placement, size and public boundaries), `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation; copies kept equal by a guard; prove the walk sees a seeded bypass), `api-and-compatibility.md` (consumer inventory, explicit and coordinated break), `config-secrets-and-supply-chain.md` (reproducible, attributable dependency inputs and lockfiles), `performance.md` (worker budget and observed timing), `documentation.md`, and `catalogs/recurring-defects.md`.

Risk: R2. No engine logic changes, but the change moves deterministic output for some provider and locale pairs, changes the dependency lock twice (S1 adds a test-only tool, S2 moves Faker), and re-pins the DP certified rows. Approver: Cam (owner) for the post-1.0 rule, Q11 and questions A to D; Dennis then Codex for the plan gate and the S1 and S2 code gates.

### Revision 3.5 changes

Dennis H1 resolved by owner choice: FAKER-REPRO R1 owns the CI run-line expansion and lane-coverage rule, so S1 keeps its correct single-file `faker_output_lock` lane.

### Revision 3.4 changes

Carried by FAKER-REPRO revision 2 (`docs/plans/2026-11-19-faker-reproducible.md` on `plan/faker-reproducible`), Dennis round 1 findings H1 and H3 there. Plan text only; no S1 code is named beyond the CI run line and its lane cell.

| Finding | Closed in |
|---|---|
| FAKER-REPRO R1 adds a route golden and a data-order audit that this plan did not own, so a red cell under 40.54.0 would stop S2 under FM-4 | 5.6 two rows (route golden with `python -m tests.integration.faker_repro._routes --write`; `_CANONICAL_ORDER` table); FM-4; FM-17; G-2; G-3; 12 S0 addendum and Order |
| The `faker-output-lock` job names one test file, but S1 splits the lock sentry into three modules and FAKER-REPRO adds marked files elsewhere; `addopts` and the regression gate deselect the marker, so those cells would run in no job | FAKER-REPRO R1 owns the CI run-line expansion and lane-coverage rule |

### Revision 3.3 changes

| Finding | Label | Closed in |
|---|---|---|
| Caller-supplied `faker_kwargs` and `ProviderSpec.extra` bypass the argument lock | V1 | 1.1 item 2; 4.1 derived caller-argument surface and grid; FM-20; AT-L16 to AT-L19; 10 design notes; 12 S1 |
| Both clocks are in the 2020s, so decade-relative output can be mislabeled | V1 | 4.1 clocks and calendar classification; AT-L1, AT-L6, AT-L20; 10 design notes |
| `test_faker_output_lock.py` is 914 lines | DESIGN | 8 acceptance-test ownership and AT-L21; 9 Placement; 11 Size; three cohesive test files, each below 600 lines |
| `argument_grid.py` is absent from Placement and the size claim is false | DESIGN | 9 Placement; 11 Size |
| AT-L17 is not alias-sound and discovery can silently lose a known family | V2-LOG | 4.1 derived runtime surface; AT-L17 and AT-L19 replace the source-call scanner and require the four known families exactly |
| The round-3 red assertion was narrowed to two reflected methods | V2-LOG | AT-L16 restores a full reflected-surface oracle for every argument-only mutation |

### Revision 3.2 changes

| Finding | Closed in |
|---|---|
| V1 argument-only Faker changes pass the lock | 1.1 item 2; 4.1 argument-forwarding inventory, fixed grid and construction guard; FM-20; AT-L16 to AT-L18; 9 Placement; 10 design notes; 11 Size; 12 S1 |
| V2-LOG stale two-seed text and S1 estimates | 4.1 writer and sentry; AT-L1; 9 Placement; 11 Size; 12 S1 |

### Revision 3.1 changes

| Finding | Closed in |
|---|---|
| V1 strict stored types | AT-L2 and 13 recurring-defect check require wrong-type cells for every stored primitive field and list element |
| DESIGN one tool-facing engine access seam | 3 reuse inventory; 4.1 worker; AT-L15; 9 Placement; 10 design notes; 13 recurring-defect checks |
| V2-LOG matrix fail-fast | 4.1 CI job and AT-L12 require `strategy.fail-fast: false` |
| V2-LOG exception context | AT-L8 and 13 recurring-defect check assert no cause or context on raised tool errors |
| V2-LOG S2 release order | 12 Slices and owner Q11 make S2 depend on the freeze-batch engine release; G-2 stays unchanged |

### Revision 3 changes

| Finding | Closed in |
|---|---|
| HIGH-1 | 4.1 worker lifetime, concurrent clocks, runtime budget, dedicated CI jobs; AT-L1, AT-L12; 9 Placement; 12 S1 |
| HIGH-2 | 1.1 items 5 and 6; 4.1 seven diff kinds; 4.4 fragment; AT-L6, AT-L7, AT-F1; owner question C |
| M1 | 4.1 sentry clock-A hash seeds 0 through 7; AT-L1 |
| M2 | 4.1 canonical adapter codec and `raises:<outer>/<cause>`; AT-L8; 13 recurring defects |
| M3 | 4.1 marker scope and sentry manifest; AT-L2, AT-L7, AT-L10, AT-L12; 9 Placement |
| M4 | AT-L6 and defect-catalog class 7 use the worker-ignores-`--clock` mutation |
| M5 | AT-L2 seeded negative cells |
| M6 | 3 reuse inventory; 4.1 shared worker environment; 9 Placement; AT-L14 |
| M7 | 4.1 and AT-L12 keep import-smoke unchanged and add a separate matrix job |
| L1 | 10 design notes describe the two clocks without a leap-day claim |
| L2 | 4.1 adapter `ProviderSpec` includes `namespace=None` |
| L3 | 4.3 distinguishes the `time-machine` floor from the exact `uv.lock` pin |
| L4 | 4.3, 5.6, 9, 11 and 12 require no S1 NOTICE diff |
| L5 | 4.5 adds the missing Faker row to CLI `frozen-surfaces.md` |
| L6 | 4.1 fixes the canonical writer interpreter at CPython 3.10.20 |
| L7 | 5.1 and AT-B1 record the observed failure behavior before deciding whether an engine assertion exists |
| L8 | AT-L13 registers a custom provider in the stub before proving exclusion |

## 0. What the stale branch learned

`origin/fix/faker-40-31-migration` (`071b7d005`, 2026-09-25, no PR, about 994 commits behind main, base `0d69bffa5`) is read, not rebased. It holds two commits:

1. `a7b8d6691` bumped to 40.31.0 after finding that the 2026-07-23 claim ("40.31.0 drops five person providers and shifts the name pools") does not reproduce: `dir(Faker())` is identical between the two versions (305 names), the proof manifest was byte-identical, and every Faker-tagged test then on main passed unmodified.
2. `071b7d005` reverted the bump. The five-provider "drop" is real but has nothing to do with Faker: the optional `mimesis` extra rebinds `person_name`, `person_first_name`, `person_last_name`, `person_full_name` and `person_email` to `MimesisAdapter` (adoption matrix in `src/decoy_engine/providers_v2/_registry.py`), so they leave `faker_providers()` on either Faker version. The revert reason was the DP certified profile fingerprint: Faker is in the hashed distribution set, so the bump moved the row (`895b9a20...` to `234120d1...`) and failed `dp-certified-gate` and the CLI certified profile. Cam held the bump because re-certifying DP was a separate decision. That decision is now taken.

Kept: the root cause (no registry fix is needed) and the three additive regression tests in `tests/unit/providers_v2/test_faker_adapter.py` (`TestPersonProvidersSurviveFakerVersion`), replayed by patch in S1. Not kept: the edit to `tests/unit/providers_v2/test_registry.py::test_known_faker_provider_present` (it makes an existing test conditional on `mimesis`; no CI job installs `mimesis`, so the test is green as it stands) and the docstring note in `tests/sentry/test_proof_manifest.py` (follow-up F-1).

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. The engine pins `faker==40.54.0`. `pyproject.toml`, `uv.lock`, `NOTICE`, the output lock, `tests/parity/_f0_fixtures.py::PINNED_FAKER_VERSION`, and in the CLI `requirements-certified.txt` and `requirements-dev.lock` all name 40.54.0, and a sentry in each repo fails when a copy differs.
2. Before the pin moves, S1 commits a Faker output lock captured under 40.23.0. It covers every Faker call surface in 4.1: no-argument reflected providers used by `faker_type` columns, the V2 adapter used by the masking `faker` strategy, raw engine call shapes, and a caller-argument grid derived from the complete current caller surface. That surface is the reflected `faker_kwargs` path including its `address` override, adapter `ProviderSpec.extra`, and formula helpers. For every Faker locale and every provider or derived argument case on each applicable surface, it records the provider's keyword-argument names or the exact typed argument descriptor, the applicable draw digests, and whether the output depends on the calendar. A sentry requires every discovered method and signature parameter to have a grid row and requires all four caller-argument families to remain present. It is computed in separate processes under a process-wide frozen clock. The S2 diff of the lock is the reviewed list of every changed, added, removed, newly reproducible, newly unstable, newly calendar-dependent and no-longer-calendar-dependent pair.
3. Every golden that moves under 40.54.0 is rewritten by the tool that owns it (section 5.6). No golden file and no digest literal is edited by hand, no test assertion is weakened, and the S2 diff under `tests/` touches only the paths section 5.6 owns (G-3).
4. The DP certified rows are re-pinned with the existing tools: the engine dev/CI row through `scripts/release/dp_rows.py` (checked by `tests/sentry/test_dp_lock_row.py`), in S1 for the test-tool addition and in S2 for Faker, and the CLI pristine row through `C:scripts/cert_smoke.py` in C1. Prior rows stay, so snapshots fitted on an older row still compile. The DP mechanism does not read Faker output (the proof-critical set is opendp, dp-accounting, numpy, scipy, pandas and pyarrow, `quality/dp_provenance.py`); Faker is in the row only because the row hashes the whole installed set. Re-certification is therefore a re-pin plus a `dp-certified-gate` run with no skips, not a new DP proof.
5. The output change is a pre-GA correction: one changelog fragment with a `Breaking:` line for changed and removed pairs. Its separate `Changed` line for `uuid1` and `uuid7` comes verbatim from the output-lock tool's rendered diff: their digest changes and stops depending on the calendar. They were calendar-dependent digests under 40.23.0 with `tick=False`, not unstable pairs. `docs/compatibility-contract.md` section 1 records the repin as a pre-GA correction and states that the platform stays on Faker 40.23.0 while it is parked.
6. After 1.0, compatibility contract section 3.3 records the recommended answer to owner question C (decided 2026-11-18, recommended): a Faker bump may ship in a 1.x release only when the output lock diff contains added providers or locales, newly reproducible pairs, or pairs that are no longer calendar-dependent. A changed digest is otherwise a 2.0 change, as is a removed provider, locale or keyword argument or a pair that becomes unstable or calendar-dependent. The `uuid1` and `uuid7` change is classified as a changed digest plus no longer calendar-dependent for the pre-GA repin. The freeze covers the default install on the platforms of still-open question A; the `mimesis` extra is outside it under the recommended answer to still-open question B. The sentry makes every lock change visible; the release gate applies the owner-confirmed answer.
7. No engine logic changes. Masking, generation, the native kernels, the derivation and `SEED_PROTOCOL_VERSION` are untouched.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- Snapshotting or vendoring Faker's providers (row text: Later, non-breaking). Section 2 says why not 1.0.
- Fixing providers whose production output changes with today's date (follow-up F-4, goes to the roadmap inbox). The lock freezes the calendar to make such pairs checkable; it does not change what users get.
- Making the proof manifest independent of the `mimesis` extra (F-1).
- Widening `POOL_ELIGIBLE_FAKER_TYPES` or `POOL_ELIGIBLE_LOCALE_PAIRS` (F-3).
- The `test_registry.py` mimesis edit from the stale branch.
- Other dependency bumps. Dependabot PR E#583 bundles Faker 40.54.0 with five other packages and touches only `pyproject.toml` (the same mix as #47, which caused the 2026-07-23 confusion). S2 supersedes its Faker part (owner Q6).
- Exhaustive combinations of multiple caller arguments beyond the derived single-parameter and named coupled-boundary shapes (residual risk R-2). Every current reachable method and every caller-settable signature parameter is covered by at least one derived row; the finite grid does not claim the Cartesian product of all legal values.

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

Remaining custom code: one writer below 700 lines, one argument-surface and grid module below 450 lines, one 45-line engine access module, one 30-line shared environment helper, and the split sentries in section 9 over the existing reflection surface, adapter and codec.

## 3. Reuse inventory

- `decoy_engine.internal.faker_setup.make_faker` (`faker_setup.py:639`) and `get_faker_providers(..., provider_snapshot=...)` (`faker_setup.py:465`): the reflected surface a `faker_type` column uses, `_FAKER_DENYLIST` (`faker_setup.py:347`) applied; `reflected_kwargs` (`faker_setup.py:416`) gives each provider's keyword-argument names. These are engine-internal names, not public exports.
- `decoy_engine.providers_v2.FakerAdapter.generate_batch` (`providers_v2/_faker_adapter.py:194`) with `_FAKER_METHOD_MAP` (`_faker_adapter.py:43`) and `_FAKER_DEFAULT_KWARGS` (`_faker_adapter.py:73`): the masking surface.
- `scripts/faker-determinism/digest_codec.py::_pool_digest`: type-tagged, length-framed encoding of a value list.
- `scripts/faker-determinism/_engine_access.py`: the one narrow, tool-facing access module for engine-internal names used by both determinism tools. It owns the existing harness access to `decoy_engine.generation._faker_pool` and `decoy_engine.internal.faker_setup` and the new output-lock access to `make_faker`, `get_faker_providers` and `reflected_kwargs`. `check_determinism.py`, `pool_determinism_worker.py` and `output_lock.py` import those names only from this sibling module. This is an accepted same-repo dev-tool exception, guarded by AT-L15; it is not an engine public API.
- `scripts/faker-determinism/check_determinism.py`: its `ThreadPoolExecutor` worker fan-out and its `--write-golden` owner role for `golden_digests.json` and `certified_pairs.json`. S1 moves lines 197 to 205, the shared worker-environment construction, into `scripts/faker-determinism/worker_env.py`; both determinism tools import that one standard-library-only helper.
- `tests/parity/_f0_fixtures.py::ORACLE_CLOCK` (2026-10-16 12:00): the lock uses the same instant as a literal, so the writer does not import `tests/`.
- `scripts/gen_proof_manifest.py`, `scripts/gen_capability_matrix.py`, `tests/parity/_f0_capture.py`, `tests/parity/_fr0_refreeze.py`, `scripts/test_flight.py` write mode, `scripts/dev/licenses_write.sh`, `uv lock`, `scripts/release/dp_rows.py` and `scripts/release/stamp_release.py`, `C:scripts/cert_smoke.py`, `C:scripts/dev/lock.sh`: the owning tools of section 5.6 and C1.
- `tests/sentry/dependencies/` for the new sentries; `tests/physical/test_faker_determinism_driver.py` shows how a test loads a module from `scripts/faker-determinism/` by file path.
- The stale branch's three additive tests, replayed by patch.

## 4. Behaviour

### 4.1 The Faker output lock (S1)

File `scripts/faker-determinism/output_lock.json`, canonical JSON (sorted keys, separators `(",", ":")`, UTF-8, trailing newline):

```
{
  "lock_version": 2,
  "faker_version": "40.23.0",
  "codec_version": 1,
  "samples": 8,
  "argument_samples": 2,
  "clocks": ["2026-10-16T12:00:00Z", "2030-01-16T12:00:00Z"],
  "argument_grid": {
    "<case id>": {
      "family": "reflected" | "address_override" | "adapter" | "formula",
      "target": "<public provider or helper name>",
      "method": "<bound Faker method name>",
      "locales": ["<applicable locale>", ...],
      "covers": ["<signature parameter>", ...],
      "arguments": {"args": [<typed descriptor>, ...], "kwargs": {"<name>": <typed descriptor>, ...}}
    }
  },
  "locales": {
    "<locale>": {
      "resolved": "<locale>" | "fallback:en_US",
      "reflected": {
        "<provider>": {
          "kwargs": ["<name>", ...],
          "per_seed": "<64 hex>" | "raises:<OuterClass>[/<CauseClass>]" | "unstable",
          "sequential": "<64 hex>" | "raises:<OuterClass>[/<CauseClass>]" | "unstable",
          "calendar": false | true
        }
      },
      "adapter": {
        "<semantic name>": {
          "batch": "<64 hex>" | "raises:<OuterClass>[/<CauseClass>]" | "unstable",
          "calendar": false | true
        }
      },
      "raw": {
        "<engine call shape>": {
          "draws": "<64 hex>" | "raises:<OuterClass>[/<CauseClass>]" | "unstable",
          "calendar": false | true
        }
      },
      "argumented": {
        "<case id>": {
          "draws": "<64 hex>" | "raises:<OuterClass>[/<CauseClass>]" | "unstable",
          "calendar": false | true
        }
      }
    }
  }
}
```

Worker (`python scripts/faker-determinism/output_lock.py --worker --clock <iso> [--locales en_US pt_BR]`), one process. Omitting `--locales` means every locale; only stub acceptance cells narrow it to `en_US` and `pt_BR`:

1. Start `time_machine.travel(<clock>, tick=False)` before importing `faker` or `decoy_engine`, so module-level and default-argument clock reads are frozen as well as calls.
2. For each locale, construct one fresh Faker instance for each draw shape, not one per provider: one `make_faker(locale)` for reflected `per_seed`, one for reflected `sequential`, one `Faker(locale)` for adapter `batch`, and one instance for each caller-argument family. Import the engine seams only from the sibling `_engine_access.py`, never from `decoy_engine.internal` in the worker. Discover reflected providers from the first instance with `get_faker_providers(fake, provider_snapshot={})`; record `resolved` as the locale or `fallback:en_US`. This is equivalent to a fresh instance because `seed_instance` resets the generator before every provider, as the existing `transforms/_faker_span.py:25-33` contract states.
3. For each reflected provider, reseed the shape's instance before that provider. `kwargs` is the sorted keyword-argument-name list from `reflected_kwargs`. For `per_seed`, call `seed_instance(i)` before each of 8 single draws. For `sequential`, call `seed_instance(0)` once, then draw 8 values. This preserves the production per-row and pool-build shapes while removing roughly 200 Faker constructions per locale.
4. Enumerate adapter semantic names through public `get_default_registry().faker_providers()`. During this draw shape only, `unittest.mock.patch.object(faker, "Faker", return_value=adapter_fake)` makes the real `FakerAdapter.generate_batch` constructor call return the one preconstructed locale instance. For each name, call `generate_batch(..., count=8)` with `ProviderSpec(locale=locale, deterministic=False, namespace=None, seed=(0).to_bytes(8, "big"))`; `generate_batch` itself reseeds the instance before that provider. This exercises the production seed conversion, `_FAKER_METHOD_MAP`, `_FAKER_DEFAULT_KWARGS`, anchored date-of-birth path and error wrapping without constructing a Faker per provider. Any engine-internal imports needed by this tool go through `_engine_access.py`; the tool does not copy adapter rules.
5. Ask `argument_grid.py` for the derived caller-argument surface and grid described below. Invoke every row through its production forwarding seam, not directly through the bound Faker method: the reflected wrapper receives `faker_kwargs`, the separate address target receives the same mapping through `_addr`, the adapter receives `ProviderSpec.extra`, and the callable returned by `_formula_scope` receives formula positional or keyword arguments. Each row reseeds to argument seeds 0 and 7 and digests the two results. The no-argument surfaces keep their eight draws. The top-level grid stores each descriptor once; locale entries store only digests and calendar classification.
6. `digest_codec.py` remains the one value codec. Extend its type-tagged, length-framed canonicalizer for adapter values using the same type dispatch and canonical forms as `generation/pool/_canonicalize.py::_canonicalize_source` where applicable: arbitrary-width integral scalars, bool before int, UTF-8 strings, raw bytes, `Decimal` canonical text, `date` ISO 8601, and `datetime` normalized to UTC when aware, with a separate tag for a naive datetime. Add the Faker scalar `time` form if S0 observes it. Unsupported types fail with a fixed error that names only the index and type class; remove the value `repr` now emitted at `digest_codec.py:93-96`.
7. A direct provider exception records `raises:<outer class>`. An adapter exception records `raises:<outer class>/<__cause__ class>`, for example `raises:AdapterError/NotImplementedError`, because `_faker_call` wraps all provider failures. A missing cause is the fixed token `none`. No exception message or generated value representation enters the lock, diff, error, stdout or changelog rendering.
8. The worker prints one JSON document on stdout.

Caller-argument source inventory, taken from `origin/feat/faker-migrate-s1` and re-run by the S1 builder before editing:

1. Formula scope: `generators/_formula.py:362-369` binds `date_between`, `date_this_decade`, `date_this_year`, `date_this_month`, `future_date` and `past_date` directly to Faker bound methods, and binds `date_of_birth` through `anchored_date_of_birth`. Both inline and referenced formulas call this scope, and callers can supply positional and keyword arguments.
2. Reflected generate path: `internal/faker_setup.py:431-445` filters and forwards the YAML `faker_kwargs` mapping to a bound Faker method; its `address` override at lines 507-509 forwards the same mapping. Production callers are `generators/columns.py:248-328`, `generation/synthesize.py:449-535`, `generation/_unique.py:54-95`, `generation/_column_streams.py:148-185`, and `generation/_faker_pool.py:329-368`. `resolve_pool_provider` returns the same reflected wrapper. The native protocol mirrors at `execution/native/protocol/providers_gen.py:223-250` and `execution/native/_draw_site_providers_gen_pool.py:30-64` forward the same kwargs through that wrapper, so they do not define an independent surface.
3. Adapter masking path: `providers_v2/_faker_adapter.py:131-157` merges caller-controlled `ProviderSpec.extra` over `_FAKER_DEFAULT_KWARGS` and forwards the result to the mapped Faker method or anchored DOB helper. `generation/pool/_builder.py:213-222` constructs that spec from masking `provider_config`, reached from `execution/_strategies/_faker.py:70-107`.

`argument_grid.py` is the single construction point for this surface. It obtains the current artifacts through `_engine_access.py` and returns typed `ArgumentTarget` records:

1. `reflected`: every callable returned by `get_faker_providers(fake, provider_snapshot={})` except `address`, paired with the exact bound Faker method or anchored DOB helper that its production wrapper calls. The names and takes-any-keyword flag from production `reflected_kwargs` are the accepted-parameter source. The signature supplies types, defaults and positional capability; the tool does not implement a second keyword filter.
2. `address_override`: the returned `address` wrapper as a required separate target, paired with `fake.address`'s signature. It cannot disappear into the general reflected family.
3. `adapter`: every semantic name returned by the public default registry, paired with its actual `_FAKER_METHOD_MAP` target, defaults and anchored DOB target from the one tool-facing access seam. Invocation still goes through `FakerAdapter.generate_batch` with `ProviderSpec.extra`.
4. `formula`: the actual callable table returned by `_formula_scope` on a controlled Faker-backed object. A callable bound to that object's Faker instance is a Faker target and provides its own signature; unrelated formula utilities are ignored. The anchored DOB forwarding callable receives the anchored helper's effective signature. Any other Faker-target wrapper with opaque `*args` or `**kwargs` and no effective signature fails discovery instead of being skipped.

The required family set is exactly `{"reflected", "address_override", "adapter", "formula"}`. Discovery returning no targets for a family, losing a current method, or losing a caller-settable parameter is a sentry failure. Because discovery consumes runtime callables and effective signatures, aliases such as `fn = fake.date_between; fn(**kw)` do not affect it. AT-L17 therefore replaces the round-3 source-call regex and AST scanner rather than trying to make that scanner enumerate every alias spelling. The native files in item 2 are mirrors of the reflected wrapper and do not create a fifth argument source.

V1 and V2 custom-provider registrations are outside the Faker-release grid: their production wrappers ignore `faker_kwargs` or `ProviderSpec.extra` and call repository or in-process custom code with only the Faker instance. The reflected discovery uses `provider_snapshot={}` for that reason, matching the no-argument lock's existing scope.

The grid is derived, not a method list. Discovery runs for every Faker locale. Identical target, signature and descriptor rows are coalesced once at the top level with their sorted applicable `locales`; locale-specific signatures remain separate rows. For every target, inspect its effective signature and include every parameter except the bound receiver. This includes positional, keyword, `*args` and `**kwargs` parameters. Each `(locale, family, target, parameter)` must appear in `covers` on at least one applicable row. `argument_grid.py` owns one `PARAMETER_SHAPES` registry:

| Parameter class | Derived rows |
|---|---|
| strict boolean | one `false` and one `true` row |
| integer or float | one non-default representative row; lower/upper pairs such as `min` and `max`, `start` and `end`, or their suffixed forms also get ordered and equal-boundary rows |
| string or enum-like | one non-default representative; date-bound names also get relative, absolute-string and typed-date rows, with absolute bounds chosen to remain valid at both clocks |
| sequence or mapping | one small closed synthetic container of the required type |
| nullable or unannotated | classify from its non-`None` default, then from the one reviewed `PARAMETER_KIND_BY_NAME` table; an unclassified name fails closed |
| `*args` or `**kwargs` | one typed positional item or one closed representative mapping from the same registry; Faker `dsv(**fmtparams)` therefore has a `fmtparams` row |

The reflected wrapper filters unknown keys, so a reflected method with no caller-settable parameters needs no argument row. The address override and adapter forward unknown `faker_kwargs` or `extra` without that filter, so each zero-parameter target gets one closed `unexpected_keyword` row; it normally captures the refusal class and turns red if the forwarding path starts dropping the mapping.

The descriptor codec accepts only strict JSON scalars and closed tagged forms for date, datetime, tuple and mapping. It accepts no import name, constructor or `eval`. Fixed synthetic descriptors are stored once in `argument_grid`; generated Faker values and caller data never enter it. The equal-boundary rule produces the required `random_int` row with `min=7,max=7`. Defaults from `_FAKER_DEFAULT_KWARGS` are part of the adapter target's starting arguments, and a row records only the caller override applied over them. Formula positional coverage is derived for positional-capable parameters, not maintained as a separate helper list.

Writer (`python scripts/faker-determinism/output_lock.py --write`):

1. Runs only under CPython 3.10.20. It refuses with exit 1 and a fixed message when the interpreter or installed Faker differs from the canonical writer versions.
2. Imports `worker_env.py`, the standard-library-only helper moved from `check_determinism.py:197-205`, to build `PATH`, `PYTHONPATH`, `PYTHONHASHSEED`, `TZ=UTC`, `LC_ALL=C`, `LANG=C` and `DECOY_ENGINE_COMMIT`. `check_determinism.py` imports the same helper. The helper receives the root, seed and already-resolved commit, so it imports no engine module.
3. With a `ThreadPoolExecutor` like `check_determinism.py`, concurrently runs clock A (`2026-10-16T12:00:00Z`, the F0 `ORACLE_CLOCK` instant) at all eight `PYTHONHASHSEED` values 0 through 7 and clock B (`2030-01-16T12:00:00Z`) at seed 0. The clocks have the same day and time but cross month, year and decade boundaries.
4. A digest that differs between the eight clock-A processes becomes `unstable`. A digest that is equal across processes at clock A but differs at clock B is kept (the clock-A value) with `calendar: true`. Everything else is a digest with `calendar: false`.
5. Writes the file and prints a names-only, seven-kind diff against the previous file, including the exact changelog `Changed` line for every changed digest that is also no longer calendar-dependent.

Sentries are split by concern as section 9 specifies. The marked runtime file runs the same eight clock-A hash seeds 0 through 7 and clock B seed 0 as the writer. To keep each cell below its explicit timeout, one marked worker cell gathers clock-A seeds 0 through 3 and another gathers seeds 4 through 7 plus clock B; the session-scoped `full_capture` joins all nine documents before classification. Every sentry run can therefore detect instability on any canonical hash seed, newly reproducible output and calendar movement. It never compares the digest of a stored `unstable` entry; it requires the eight clock-A workers to remain divergent for that entry. The diff has seven kinds, each reported with names only: changed, removed, added, newly reproducible, newly unstable, newly calendar-dependent and no longer calendar-dependent. A changed top-level grid descriptor is reported by family, target and case id. A pair can be in `changed` and `no longer calendar-dependent`; this is the classification for `uuid1` and `uuid7` in 40.54.0. The message gives the installed and locked Faker versions and ends: "Faker output moved. Before 1.0: regenerate with output_lock.py --write in the repin PR. After 1.0: see compatibility contract 3.3 for which kinds a 1.x release may carry."

Reviewed lists in `_faker_lock_lists.py` (H3), each entry with a one-line reason, and each re-verified against the lock on every run:

- `EXPECTED_UNSTABLE`: the pairs recorded `unstable`. It may be empty under 40.23.0 because `tick=False` makes `uuid1` and `uuid7` stable at one clock; those pairs belong to `EXPECTED_CALENDAR` when they change across the two clocks. AT-L7's seeded lock copy keeps the negative test meaningful even when the real set is empty.
- `EXPECTED_RAISES`: the pairs recorded `raises:` (for example `bank` in locales with no bank list).
- `EXPECTED_CALENDAR`: the pairs recorded `calendar: true` (for example `ssn` in `fi_FI`, `lv_LV`, `et_EE`, `zh_CN`, `no_NO`, `sv_SE`; `company` in `ru_RU`; `passport_dates` and `passport_dob` in `en_US`). Required argumented members include all four boolean shapes for `date_this_decade`, `date_this_year` and `date_this_month`: with both booleans false Faker returns the frozen current date. They also include relative `date_between` rows and every `future_date` or `past_date` row whose other boundary remains implicit `today`, even when the supplied endpoint is absolute. A `date_between` row with both absolute boundaries and other fully fixed-bound rows are expected not to be calendar-dependent unless the provider separately reads the clock. AT-L20 pins the 2026 versus 2030 `date_this_decade.both_sides` case.
- `ANCHORS`: pairs that must be digests on both surfaces where they exist: `first_name`, `email`, `address`, `currency_code` in `en_US`, `bban` in `es_ES`, `vat_id` in `en_GB`, and the adapter names `person_first_name` and `person_email` in `en_US`.
- `EN_US_DIGEST_FLOOR`: the minimum number of `en_US` reflected pairs that are digests, set in S1 to the captured count. Only a drop below it fails.

The three expected sets must equal the lock's sets exactly; a pair that leaves or joins one of them without an edit to the list fails, and the list edit shows in review.

Runtime and size budget: the old fresh-instance-per-provider prototype costs about 440 seconds per clock run. One fresh instance per locale per draw shape, reseeded before each provider, measured about 45 seconds before the argument grid. The derived grid has hard ceilings of 64,000 locale-case rows and 32 MiB of canonical lock JSON. Discovery fails before capture if either projected ceiling is exceeded. S1 records the actual target, parameter, row and byte counts, the full worker time, and both split sentry-cell times on the Dell or Mac. A worker must finish within its existing 150-second subprocess timeout and each pytest worker cell within the unchanged 180-second cell timeout. Approaching either time limit stops the build for a narrower worker split or a lower-cost invocation that preserves the same rows; no timeout or row cap is raised in S1.

Only cells that spawn a real or stub worker carry both `@pytest.mark.faker_output_lock` and an explicit `@pytest.mark.timeout(180)`. Static schema, list and surface-coverage cells are unmarked and remain in the ordinary sentry gate. S1 adds `faker_output_lock` to the pytest marker registry and to the default `addopts` deselection. It adds all three Faker output-lock sentry files to `SENTRIES` in `tests/sentry/test_sentry_manifest.py`, so the static cells cannot fall outside the gate.

The required, no-path-filter `faker-output-lock` CI matrix job sets `strategy.fail-fast: false` and runs the marked worker cells on CPython 3.10.20, 3.11.9 and 3.12.7 with the `dev` extra. It runs `pytest tests/sentry/dependencies/test_faker_output_lock.py -m faker_output_lock --tb=short`, the only file with marked worker cells on the S1 head. The 3.11 and 3.12 checks live only in this matrix job. The existing `import-smoke` job remains a no-extras install and keeps only its 10-minute Import and Probe checks. `ci/required-jobs.toml` makes the Faker job required on every change.

Platform scope (owner question A, recommended): Linux (CI) is blocking. S1 runs the sentry once on the Mac and records the result in the PR; a Mac difference is a finding for the owner. When WIN-RUNNER (row 6) lands, a Windows leg runs the sentry and becomes blocking; a Windows-only difference is fixed in the engine, not excluded from the lock.

### 4.2 The version-agreement sentry (S1)

`tests/sentry/dependencies/test_faker_pin_agrees.py`: the single `faker==` pin in `pyproject.toml`, the `faker` version in `uv.lock`, the `faker==` line in `NOTICE`, the lock's `faker_version`, and `tests/parity/_f0_fixtures.py::PINNED_FAKER_VERSION` are equal. The `pyproject.toml` pin is the one fact. `uv.lock` and `NOTICE` are generated from it; the lock version and `PINNED_FAKER_VERSION` record the version a capture was taken under, and a capture under a different version is stale. Versions are compared as full strings with `re.fullmatch` on `\d+\.\d+\.\d+` first (L3). In S2 it gains `test_dependabot_excludes_faker`, which parses `.github/dependabot.yml` with `yaml.safe_load` (L2).

### 4.3 The test-tool addition (S1)

`time-machine` joins the `dev` extra with a tested lower bound, written as `time-machine>=X.Y.Z` where S1 sets `X.Y.Z` to the minimum release it directly verifies against the required clock APIs. This matches the runtime test plugins in that extra; `uv.lock` resolves and pins one exact version. `dev` is part of the certified DP profile (`dev+lint+vault+cloud`), so S1 also regenerates `uv.lock` (only the `time-machine` package and `dev` extra edges change) and adds the new dev/CI row to `_CERTIFIED_STACKS` through `dp_rows`, prior rows kept. `NOTICE` covers shipped runtime distributions, so S1 runs its owner/check and requires no NOTICE diff. The CLI pristine row is not affected because it installs no dev tooling.

### 4.4 The repin (S2)

In this order, on one branch, each step by its owning tool:

1. `pyproject.toml`: `faker==40.54.0`. The comment above the pin is rewritten to the verified history: the 2026-07-23 claim was the `mimesis` rebinding; the pin moves only with the output lock and the DP rows; after 1.0 see compatibility contract 3.3.
2. `uv lock --upgrade-package faker==40.54.0`. The `uv.lock` diff may touch only the `faker` package block (including its new optional `image` extra on `pillow`, which no profile installs) and the `decoy-engine` requirement (AT-P2).
3. `scripts/dev/licenses_write.sh` (NOTICE).
4. `python scripts/faker-determinism/output_lock.py --write`. The lock diff, as names grouped by diff kind, goes into the PR body. The reviewed lists of 4.1 are updated in the same commit, each changed entry with its reason.
5. Every golden that the S0 record marks "moved" in section 5.6, by its tool, in the table's order.
6. DP: the new dev/CI fingerprint from `dp_rows` is added to `_CERTIFIED_STACKS` (`quality/dp_provenance.py:272`), newest first, prior rows kept. A fresh `uv sync --frozen --extra dev --extra lint --extra vault --extra cloud` on CPython 3.10.20 reproduces it.
7. `support/_probe.py` `PROBE_GOLDEN[7]`: only if S0 shows the probe moved. Expected not: the probe pools `person_first_name` in `en_US`, unchanged in both diffs. If it moves, the value comes from `run_probe()` on the repinned venv and the fragment names it, as `_probe.py:49` requires.
8. Changelog fragment `changelog.d/faker-migrate.md`: a `Breaking:` line ("deterministic `faker` output changes for the listed provider and locale pairs; re-run masking to keep joins stable across the change"); under it, the changed and removed pairs grouped by locale; the exact names-only `Changed` bullet rendered by `output_lock.py --write` for `uuid1` and `uuid7`, stating that each digest changed and is no longer calendar-dependent; and a bullet for the new `pyfloat` refusal. The gate compares the fragment line with fresh tool output instead of maintaining a second diff-kind table in the fragment checker.
9. `docs/compatibility-contract.md`: section 1 gets "Pre-GA corrections taken with the Faker repin (FAKER-MIGRATE)", including that the parked platform stays on Faker 40.23.0 until it repins; section 3.3 records the owner-confirmed answer to questions A to C, including the seventh `no longer calendar-dependent` kind; the section 5 decision table states that changed digests are major unless the only accompanying change is no longer calendar-dependent and owner question C confirms the recommended 1.x allowance. Removed provider, locale or keyword-argument entries and newly unstable or calendar-dependent pairs remain major. `docs/determinism.md` gets one paragraph that points at the lock.
10. `.github/dependabot.yml`: `exclude-patterns: ["faker"]` on the `python-minor-patch` group.

### 4.5 CLI (C1)

After the engine release that carries S2 and its stamped DP rows (E-REL):

1. `C:requirements-certified.txt`: the `faker==` pin (line 64 on `920ea13c`) becomes `faker==40.54.0`; the header gets the new engine version, the new fingerprint from `C:scripts/cert_smoke.py`, and one more entry in its row history.
2. `C:requirements-dev.lock`: regenerated through `C:scripts/dev/lock.sh`, never by hand.
3. Engine repin per the engine repin checklist, including the CI install, the release smoke and the fresh-install smoke that read `requirements-certified.txt` (`C:.github/workflows/ci.yml`).
4. `C:docs/guides/shape-and-privacy/04-differential-privacy.md`: the install line, if it names versions.
5. `C:docs/release/frozen-surfaces.md`: add the missing Faker row, with version 40.54.0 and the output-lock/compatibility-contract owner. The current file has no Faker row to edit.
6. `C:docs/roadmap/release-gates.md` D-4 text "Faker 40.23.0" becomes "Faker 40.54.0"; `C:docs/roadmap/groups/mask.md` row text "40.31" becomes "40.54.0" and the row state moves; `C:docs/roadmap/decisions.md` gets a dated line that the target moved from 40.31 to 40.54.0 (owner 2026-11-18).
7. CLI goldens the S0 record lists, each by its tool; CLI CHANGELOG entry.
8. CLI sentry `C:tests/sentry/test_faker_pin_agrees.py`: both CLI requirement files name the Faker version the installed engine requires.

## 5. Enumerations

### 5.1 Exit paths

The change adds no runtime refusal. The exits are those of the new tools and of existing provider calls whose behaviour moves:

- `output_lock.py --write`: exit 0 with the file written; exit 1 with a fixed message when Faker or `time_machine` does not import, a worker fails, or the installed Faker is not the pin at `pyproject.toml:74`.
- the three Faker output-lock sentries: pass, or fail listing names per diff kind or uncovered caller-surface provenance (AT-L1 to AT-L20).
- `test_faker_pin_agrees.py`: pass, or fail naming the file that disagrees (AT-P1).
- A `faker_type: bank` column in a locale with no bank list: today Faker raises `AttributeError`; after S2 it raises `NotImplementedError`. S1 first records the actual engine reason code and exit category under 40.23.0. If the engine supplies a coded failure, AT-B1 pins that observed code and category across both versions. If the exception is uncoded today, this dependency repin adds no engine wrapper or reason code; AT-B1 instead asserts that the observed uncoded exit behavior remains the same apart from the outer dependency exception class.
- `pyfloat` with `positive=True` and `max_value <= 0`: Faker 40.54.0 raises `ValueError` where 40.23.0 returns a value. S2 records the engine behavior first and applies the same rule: pin an existing reason code and exit category if one exists, otherwise assert the observed uncoded behavior without adding engine logic. The fragment lists the refusal.
- DP fit on a venv with no matching row: `dp_stack_uncertified` (existing, `quality/dp_provenance.py:369`); after S1 and S2 add their rows it passes.
- Resume of a run started before the repin: the run fingerprint includes the Faker version (component list in `tests/unit/delivery/resume/test_fingerprint.py:18`), so resume is refused with the existing fingerprint-mismatch refusal, as for any engine bump.

### 5.2 Routes

Every route that turns Faker into output uses the reflected, adapter or raw call surface; the argumented surface overlays every caller-settable parameter reachable through reflected `faker_kwargs`, its address override, adapter `ProviderSpec.extra`, and formulas:

- Masking `faker` strategy: `execution/_strategies/_faker.py:89` builds the pool with `PoolBuilder` over the V2 registry. The Faker backend is `FakerAdapter.generate_batch`, which builds `Faker(locale)` directly (`providers_v2/_faker_adapter.py:229`), seeds it once and draws sequentially, with `_FAKER_DEFAULT_KWARGS` applied. Lock surface: `adapter`. Native and chunked masking only derive indices into that Python-built pool (the Rust kernel holds no Faker data), so they move exactly with the pool.
- Faker text spans: `transforms/_faker_span.py:32` reuses one default-locale `Faker()` per thread and seeds it before every draw. Default locale is `en_US`; the `raw` `text_mask.<detector>` cells use the production `_mask_faker` seam and its 8 fixed 32-bit seeds.
- Generation per-row `faker` columns: `generation/synthesize.py:449` (`_faker`), one seeded call per row through `faker_setup`. Lock surface: `reflected`, `per_seed`.
- Generation pooled `faker` columns: `generation/_faker_pool.py:359` (`make_faker(effective_locale)`), seeded once per pool. Lock surface: `reflected`, `sequential`.
- Formula date helpers: `generators/_formula.py:362-369`, one seeded call per row with formula-supplied positional or keyword arguments. Lock surface: `argumented`; `date_of_birth` also retains its existing `raw` anchored cell.
- Composite person generation: `generation/composite/_person.py`, through the registry. Lock surface: `adapter`.
- Runtime-lock probe: `support/_probe.py:95` (`_pool_part`), Faker adapter pinned. Lock surface: `adapter`.
- Capability reporting: `providers_v2/_real_registry.py:27` records `faker.VERSION` as `backend_version`, which feeds `_providers_digest` (`support/_runtime_lock.py:280`) and `docs/capability-matrix.md`.
- If E#661 (GEN-PROVIDERS E1, the `provider` generate type) merges before S2, its route joins this list in a plan revision, and the lock gains the surface it calls, before S2 builds.

### 5.3 FK shapes

N/A: this change produces no FK keys and touches no FK machinery; an FK column with a `faker` strategy moves like any other column of that provider and locale.

### 5.4 Fields

- `output_lock.json`: top level `lock_version`, `faker_version`, `codec_version`, `samples`, `argument_samples`, `clocks`, `argument_grid`, `locales`; per grid row `family`, `target`, `method`, `locales`, `covers`, `arguments`; per locale `resolved`, `reflected`, `adapter`, `raw`, `argumented`; per reflected pair `kwargs`, `per_seed`, `sequential`, `calendar`; per adapter pair `batch`, `calendar`; per raw and argumented pair `draws`, `calendar`. `arguments` has exactly `args` and `kwargs` and accepts only the closed descriptors in 4.1. All sets are closed; the sentry refuses an unknown or missing key and a value of the wrong type (`calendar` is a strict bool).
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
| `scripts/faker-determinism/output_lock.json` and the reviewed lists in its sentry suite | the three `tests/sentry/dependencies/test_faker_output_lock*.py` modules | `output_lock.py --write`; list entries edited with a reason | moved (by design) |
| `scripts/faker-determinism/golden_digests.json`, `certified_pairs.json` | `check_determinism.py` (marker `determinism_harness`) | `check_determinism.py --write-golden` | likely unchanged: the 5 harness locales change only in bank, VAT and currency types, which are not harness candidates |
| `tests/parity/_f0_expected.py` and `PINNED_FAKER_VERSION` (`tests/parity/_f0_fixtures.py:100`) | `tests/parity/test_phase_f_f0_oracle.py` | `python -m tests.parity._f0_capture` (its docstring command); the version literal moves with the capture | version literal moves; digests only if a fixture uses a moved pair |
| FR0 refreeze data | `tests/parity/test_phase_f_fr0_refreeze.py` | `tests/parity/_fr0_refreeze.py` | measured in S0 |
| `docs/proof-manifest.json` | `tests/sentry/test_proof_manifest.py` | `scripts/gen_proof_manifest.py` (no `mimesis`, as CI) | measured in S0 |
| `docs/capability-matrix.md` | `tests/sentry/test_capability_matrix.py` | `scripts/gen_capability_matrix.py` | moved if it prints `backend_version` |
| `testflight/golden_fingerprints.json` | `scripts/test_flight.py` (nightly) | `scripts/test_flight.py` write mode | measured in S0 |
| `support/_probe.py` `PROBE_GOLDEN` | `tests/unit/support/test_probe.py` | `run_probe()` value, named in the fragment | unchanged |
| `_CERTIFIED_STACKS` dev/CI row | `tests/sentry/test_dp_lock_row.py`, `dp-certified-gate` | `scripts/release/dp_rows.py` | moved (Faker is in the hashed set) |
| `NOTICE` | license sentries | `scripts/dev/licenses_write.sh` | unchanged in S1 because the test-only dev dependency is not shipped; moved in S2 for the shipped Faker repin if the owner tool changes it |
| `tests/snapshots/*` baselines | their tests | each test's documented update path | measured in S0 |
| `tests/native/test_draw_site_providers_golden.py` | itself | none | unchanged (uses a stand-in `_FakeFaker`) |
| `tests/fixtures/golden/*` CSV inputs | V2 fixture tests | `scripts/build_golden_fixtures.py` | not regenerated: test inputs built with Faker, not outputs. Only if a reproducibility check reads them and fails does S2 rebuild them, and the downstream checks must then stay green on the new inputs |
| `tests/integration/compat_corpus/runtime-lock/*.json`, `tests/unit/delivery/resume/test_fingerprint.py` vectors | reader and fingerprint tests | none | unchanged: hand-written format samples whose `40.23.0` is data, not the installed version |
| CLI goldens | CLI e2e | each one's tool | measured in S0 (CLI part), rewritten in C1 |
| `tests/fixtures/golden/faker_repro_routes.json` (FAKER-REPRO R1; only once R1 has merged) | `tests/integration/faker_repro/test_routes.py` (marker `faker_output_lock`) | `python -m tests.integration.faker_repro._routes --write` | measured in the S0 addendum; expected unchanged (the R1 shim is version-independent and the it_IT and module-random sources are the same in 40.54.0) |
| `_CANONICAL_ORDER` in `src/decoy_engine/internal/faker_repro.py` (FAKER-REPRO R1; only once R1 has merged) | `tests/sentry/dependencies/test_faker_repro_audit.py` (data-order audit, marker `faker_output_lock`) | a reviewed table edit naming the attribute the audit reports; never a test edit | measured in the S0 addendum; expected unchanged |

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Faker pin | `faker==40.23.0` | `faker==40.54.0` | `pyproject.toml`, `uv.lock`, `NOTICE`, CLI requirement files, `output_lock.json` |
| Deterministic `faker` output | Faker 40.23.0 data | Faker 40.54.0 data for the pairs in the lock diff | changelog fragment `Breaking:`; compatibility contract section 1 pre-GA note |
| Faker output lock | none | `lock_version: 2` | `scripts/faker-determinism/README.md`; compatibility contract 3.3 |
| Post-1.0 Faker rule | the general 3.3 rule ("Faker seeding" in the section 5 table) | explicit diff-kind rule; default install only; platforms per question A | compatibility contract 3.3 and section 5 table |
| DP certified rows | rows up to engine 0.27.0 | plus two dev/CI rows (S1, S2) and one CLI row (C1) | `quality/dp_provenance.py`, `C:requirements-certified.txt` |
| D-4 launch engine | "Faker 40.23.0" | "Faker 40.54.0" | `C:docs/roadmap/release-gates.md`, `C:docs/release/frozen-surfaces.md` |
| Platform | Faker 40.23.0 | unchanged while parked | compatibility contract section 1 |

## 7. Failure modes and partial failure

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | A Faker release changes data for a provider the engine admits | the lock sentry fails, naming the pairs as "changed" | AT-L3 |
| FM-2 | A Faker release removes a reflected method, a locale, a keyword argument, a caller-settable parameter or an argument-grid case | the sentry fails, naming them as "removed" | AT-L4, AT-L9, AT-L17, AT-L18 |
| FM-3 | A Faker release adds a method or a locale | the sentry fails too (the lock is exact) and marks the change "added"; the bump PR rewrites the lock | AT-L5 |
| FM-4 | Under 40.54.0 a test goes red that no row of 5.6 owns | S2 stops and reports; the test is not edited. A plan revision adds its owner to 5.6, or it is a behaviour change taken to the owner. When FAKER-REPRO R1 has merged, a red route cell (`tests/integration/faker_repro/test_routes.py`) or data-order audit cell (`tests/sentry/dependencies/test_faker_repro_audit.py`) is owned by the two FAKER-REPRO rows of 5.6, not an FM-4 stop | G-1 |
| FM-5 | A builder edits a golden or digest by hand | the S2 gate re-runs every owning tool on the S2 head; any difference fails the gate | G-2 |
| FM-6 | `uv lock` moves other packages | the `uv.lock` diff check refuses it | AT-P2 |
| FM-7 | A DP row is added but a fresh venv does not reproduce it | `test_dp_lock_row.py` fails on every gate host (it never skips) | AT-DP1 |
| FM-8 | The CLI repins an engine on 40.54.0 but keeps `faker==40.23.0` | CLI sentry fails; `cert_smoke.py` fails with `dp_stack_uncertified` | CV-P1, CV-DP1 |
| FM-9 | A provider reads the calendar through any clock API, at call time or at import | `time-machine` freezes it process-wide from before the import; the two-clock run marks it `calendar: true`; the sentry checks the calendar set exactly | AT-L6 |
| FM-10 | A provider reads something the frozen clock does not cover (wall-clock nanoseconds through a C call, OS entropy) | it differs across the writer's processes and is marked `unstable`; the unstable set is a reviewed list | AT-L7 |
| FM-11 | A provider call raises | direct calls record `raises:<outer>` and adapter calls record `raises:<outer>/<cause>`; a class change shows as a changed pair without storing the message (the `bank()` case) | AT-L8 |
| FM-12 | The writer degrades (for example marks every pair unstable) | the anchors and the `en_US` floor fail | AT-L10 |
| FM-13 | The masking surface drifts while the reflected surface is unchanged (an adapter default-kwarg change, or a Faker change only visible through `_FAKER_DEFAULT_KWARGS`) | the `adapter` digests change | AT-L11 |
| FM-14 | A difference only on another Python minor | the required `faker-output-lock` matrix runs 3.10.20, 3.11.9 and 3.12.7 independently of import-smoke | AT-L12 |
| FM-15 | The sentry is slow | worker reuse and the split 4-worker and 5-worker cells keep each marked cell below its explicit 180-second timeout in the required, no-path-filter job | S1 measurement |
| FM-16 | A Dependabot group PR bumps Faker with other packages | the group excludes Faker; a Faker PR stands alone and the lock sentry judges it | AT-P3 |
| FM-17 | E#661, FAKER-REPRO R1 and S2 change Faker-fed goldens | whichever of them merges later re-runs every 5.6 tool (including the FAKER-REPRO route tool) and `output_lock.py --write` on its own head | G-2 on that head |
| FM-18 | The two determinism tools drift to different subprocess environments | both import `worker_env.py`; the physical guard fails on a restored inline copy or an engine import in the helper | AT-L14 |
| FM-19 | Another file in `scripts/faker-determinism/` imports `decoy_engine.internal` directly | the AST guard fails; `_engine_access.py` is the only accepted same-repo dev-tool exception | AT-L15 |
| FM-20 | Faker output changes only when a caller supplies arguments, or a caller-argument family, method or parameter has no lock case | the argumented digest changes, or derived-surface coverage fails before capture | AT-L16 to AT-L19 |
| FM-21 | A relative helper stays in the same decade under both capture clocks | clock B is in 2030 and the required decade cell is calendar-dependent | AT-L20 |
| FM-22 | Output-lock sentry tests grow back into one oversized file | the physical layout guard requires the three owned modules, each below 600 lines and present in the sentry manifest | AT-L21 |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the final slice head. Worker cells that need a modified lock or modified reflection run a subprocess against a temporary lock path or with an injected stub module named on the worker command line; the committed lock is never edited by a test. Runtime and diff tests live in `test_faker_output_lock.py`, closed-schema and reviewed-list tests in `test_faker_output_lock_schema.py`, and caller-surface, grid and argument-only mutations in `test_faker_output_lock_arguments.py`. Shared fixture and subprocess code lives in `_faker_output_lock_support.py`. Each test file stays below 600 hand-written lines.

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-L1 | `tests/sentry/dependencies/test_faker_output_lock.py::test_lock_matches_installed_faker`, marked `faker_output_lock` and `timeout(180)`: the two split worker cells collectively run clock A hash seeds 0 through 7 and clock B seed 0; `full_capture` joins all nine documents and matches the lock's classification | no lock | omit clock-A seed 7 from the joined capture | S1 |
| AT-L2 | `test_faker_output_lock_schema.py::test_lock_is_closed_and_strict`, unmarked: closed key sets at every level, canonical bytes, `lock_version == 2`, codec version, both sample counts, exact clocks, every digest checked with `re.fullmatch`, and strict stored types. Parametrized negative copies replace every primitive field and list element with wrong types. Descriptor cells cover every tagged form and refuse unknown keys, malformed dates, non-string mapping keys and non-JSON containers. Separate cells refuse an unknown key, short or newline-suffixed digests, and non-canonical bytes | no lock | accept `"calendar": 1` | S1 |
| AT-L3 | `::test_changed_pair_is_named`: a stub makes one reflected provider return a different value; the failure names that provider and locale as "changed" and holds no value | no sentry | drop the changed-name list from the message | S1 |
| AT-L4 | `::test_removed_pair_is_named`: a stub removes one provider | no sentry | compare only names present on both sides | S1 |
| AT-L5 | `::test_added_pair_is_named_additive`: a stub adds one provider; the message says "added" | no sentry | treat added names as equal | S1 |
| AT-L6 | marked `::test_calendar_independent`: the computed calendar set equals `EXPECTED_CALENDAR`, every pair outside it has the same digest at clock A and clock B, and the diff classifies a seeded calendar-to-noncalendar pair as `no longer calendar-dependent` | no sentry | make the worker ignore `--clock` | S1 |
| AT-L7 | split test: unmarked list-versus-lock cell asserts the lock's unstable set equals `EXPECTED_UNSTABLE` and a seeded lock copy that marks one stable pair unstable fails even if the real expected set is empty; marked `timeout(180)` worker cell proves a clock-A hash-seed disagreement is classified as unstable | no sentry | skip unstable names entirely | S1 |
| AT-L8 | marked `::test_raise_is_recorded_by_class`: a direct raising stub records `raises:<outer>`; an adapter stub records `raises:<outer>/<cause>`; messages and value representations never appear; the raises set equals `EXPECTED_RAISES`. Every raised tool error is caught and asserts `__cause__ is None` and `__context__ is None`. A separate unmarked codec cell covers dates and the other canonical scalar forms, asserts the unsupported-type error omits the value repr, and makes the same cause and context assertions | no writer | record `str(exc)` | S1 |
| AT-L9 | `::test_removed_kwarg_is_removed`: a stub drops one keyword argument from a provider's signature; the failure names it as "removed" | no `kwargs` field | leave `kwargs` out of the comparison | S1 |
| AT-L10 | unmarked `::test_anchors_and_floor`: every `ANCHORS` pair is a digest; `en_US` reflected digests are at least `EN_US_DIGEST_FLOOR` | no sentry | the writer marks every pair unstable | S1 |
| AT-L11 | marked `::test_adapter_surface_covered`: for `en_US` and `pt_BR`, the `adapter` names equal the public default registry's `faker_providers()` names, `generate_batch` is the exercised call, and adapter digests are compared | no adapter surface | `FakerAdapter` drops `_FAKER_DEFAULT_KWARGS` | S1 |
| AT-L12 | `tests/sentry/tooling/test_ci_lanes.py` asserts a required, no-path-filter `faker-output-lock` matrix job has `strategy.fail-fast: false` and runs `tests/sentry/dependencies/test_faker_output_lock.py` marked cells on 3.10.20, 3.11.9 and 3.12.7, while `import-smoke` still installs no extras and contains only Import and Probe | no job | remove the required Faker job | S1 |
| AT-L13 | marked stub `::test_lock_covers_engine_surface` runs only `en_US` and `pt_BR`; before capture the stub registers a custom provider, then proves reflected names equal `get_faker_providers(make_faker(locale), provider_snapshot={})`, denylisted and custom names are absent, and every admitted name is present | no lock | pass the live provider snapshot instead of `{}` | S1 |
| AT-L14 | `tests/physical/test_faker_determinism_driver.py` asserts `check_determinism.py` and `output_lock.py` import the same `worker_env.py`, its environment matches the prior contract, and the helper's import graph contains no `decoy_engine` edge | duplicated builder | restore the environment literal in either tool | S1 |
| AT-L15 | `tests/physical/test_faker_determinism_driver.py::test_engine_access_is_only_internal_import` parses every Python file under `scripts/faker-determinism/` with `ast`, recognizes both `import decoy_engine.internal...` and `from decoy_engine.internal... import ...` with aliases, and permits that edge only in `_engine_access.py`. It also asserts `check_determinism.py`, `pool_determinism_worker.py` and `output_lock.py` obtain their engine-internal names from `_engine_access.py`. A seeded direct import in a scratch file proves the walk fails | private imports are split between the existing harness and the new tool | add `from decoy_engine.internal.faker_setup import make_faker` to `output_lock.py` | S1 |
| AT-L16 | `test_faker_output_lock_arguments.py::test_argument_only_changes_are_locked`, marked and limited to `en_US`: parameterized stubs change output only when arguments are forwarded through (a) reflected `faker_kwargs`, including `random_int(min=7,max=7)`, (b) the `address` override's zero-parameter unexpected-key row, (c) adapter `ProviderSpec.extra`, including semantic `random_int_range` with `min=7,max=7`, and (d) formula positional and keyword date helpers. Every mutation must change a named argumented cell and make the lock red without exposing its returned value. The test independently compares every reflected cell before and after the stub, then requires the sentry's complete reflected diff to equal that oracle. It does not filter the assertion to `date_between`, `date_of_birth`, or any other named subset. The directly changed method's no-argument cell must remain unchanged; indirect reflected callers that use it with arguments must all be reported | the existing no-argument cells are blind to the directly changed argument shape | make `random_int` return a different result only when `min == max == 7` | S1 |
| AT-L17 | `test_faker_output_lock_arguments.py::test_every_discovered_parameter_has_a_grid_row`, unmarked: derive the four runtime families, targets and effective signatures for every locale, then assert exact coverage from every `(locale, family, target, parameter)` to at least one applicable grid row and no row that names absent provenance. Positional-capable formula parameters also require a positional row. A zero-parameter address or adapter target requires its unexpected-key forwarding row. This replaces AT-L17's non-alias-sound source scanner | generic config and adapter surfaces have no construction guard | add a new `random_int` parameter to a wrapped signature while suppressing its derived row | S1 |
| AT-L18 | `test_faker_output_lock_arguments.py::test_derived_argument_grid_is_closed_and_bounded`, unmarked: case ids are unique; every case is derived from the surface and `PARAMETER_SHAPES`; decoding and re-encoding is byte-identical; projected rows and canonical bytes are within the 64,000-row and 32-MiB caps. Wrong-type descriptors and an unknown descriptor kind are refused | no derived grid or argument schema | delete the equal-boundary derivation, accept `{"date":1}`, or lower the test cap below the observed row count | S1 |
| AT-L19 | `test_faker_output_lock_arguments.py::test_known_argument_families_are_exact`, unmarked: the discovered family set is exactly reflected, address override, adapter and formula; each is nonempty; discovered target identities equal the applicable targets in the committed lock, so discovery cannot silently lose a known method and there is no second target list. A formula callable rebound through a local alias still appears because the test consumes the runtime table, not source spelling | round-3 discovery can return a subset and stay green | make the access seam omit the adapter family, then omit one target that remains in the committed lock | S1 |
| AT-L20 | `test_faker_output_lock_arguments.py::test_decade_relative_case_crosses_clock_boundary`, marked: clock A is in 2026, clock B is in 2030, `formula.date_this_decade.both_sides` differs and is classified `calendar: true`; the year and month representatives are also in different periods | both prior clocks are in the 2020s | set clock B to `2027-11-20T12:00:00Z` | S1 |
| AT-L21 | `tests/physical/test_faker_determinism_driver.py::test_output_lock_sentries_are_split_and_bounded`, unmarked: the runtime, schema and argument sentry modules all exist, each has fewer than 600 physical lines, each is in `SENTRIES`, `_faker_lock_lists.py` is below 600, and the shared helper is below 250 with no `test_` function | the round-4 sentry is one 914-line file | append lines through the 600-line ceiling to the argument sentry, then remove the schema sentry from the manifest | S1 |
| AT-P1 | `tests/sentry/dependencies/test_faker_pin_agrees.py::test_copies_agree`: the five copies of 4.2 agree; a seeded cell with one copy changed fails naming the file | no sentry | drop `NOTICE` from the checked set | S1 |
| AT-P2 | gate check on the S2 head: `git diff origin/main -- uv.lock` touches only the `faker` package block (its new `image` extra included) and the `decoy-engine` requirement; S1's lock diff touches only `time-machine` and the `dev` extra | n/a (gate check) | an extra `--upgrade` in the lock command | S1, S2 |
| AT-P3 | `test_faker_pin_agrees.py::test_dependabot_excludes_faker`: `yaml.safe_load(".github/dependabot.yml")`, the pip group's `exclude-patterns` contains `faker` | no exclusion | remove the pattern | S2 |
| AT-S1 | `tests/unit/providers_v2/test_faker_adapter.py::TestPersonProvidersSurviveFakerVersion` (three tests replayed from `071b7d005`) | not on main | drop `"email"` from the V1 reflection loop | S1 |
| AT-B1 | `tests/unit/generation/test_faker_provider_failure_code.py`: S1 first records the observed reason code and exit category, if any, for `bank` with no bank list on 40.23.0. The test then pins that observed behavior on 40.23.0 and 40.54.0. S2 does the same for `pyfloat(positive=True, max_value=0)`, recording "returns a value" on 40.23.0 and the observed 40.54.0 failure. If no engine reason exists, add no engine code and assert the observed uncoded behavior | behavior is not recorded today | if an existing code is observed, catch only `AttributeError` so the 40.54.0 cell loses it; otherwise alter the observed exit category | S1 (bank observation and cell), S2 (pyfloat observation and cell) |
| AT-DP1 | `dp-certified-gate` on the S1 and S2 heads: certified environment, the marked DP suites run, JUnit shows passed > 0 and no skip; `test_dp_lock_row.py` green | the old rows do not match the new lock | omit the new row from `_CERTIFIED_STACKS` | S1, S2 |
| AT-R1 | every 5.6 check marked "moved" is red with the pin moved and the golden not yet regenerated, and green on the S2 head; every row marked "unchanged" is green throughout | n/a (the regeneration act) | revert one regenerated golden file | S2 |
| AT-F1 | the fragment passes the existing `tests/unit/scripts/test_check_fragment.py` grammar, carries a `Breaking:` line, and includes the output-lock tool's exact rendered `Changed` line for `uuid1` and `uuid7` as changed digests that are no longer calendar-dependent | no fragment | n/a: fragment wiring is acceptance-tested; diff-kind classification is mutated in AT-L6 | S2 |
| CV-P1 | `C:tests/sentry/test_faker_pin_agrees.py`: CLI `requirements-certified.txt`, `requirements-dev.lock` and the installed engine's `faker` requirement agree | no sentry | leave `40.23.0` in `requirements-dev.lock` | C1 |
| CV-DP1 | `C:scripts/cert_smoke.py` in a fresh 3.10.20 venv from `requirements-certified.txt` passes fit, `dps-marginal/v3` and generate | the CLI row is on 40.23.0 | omit the new CLI row | C1 |

Gate checks (run by the gate, not tests):

- G-1: every red test under 40.54.0 in S0 maps to a row of 5.6.
- G-2: on the S2 head (and on the head of whichever of E#661, FAKER-REPRO R1 and S2 merges later), each owning tool in 5.6, including `python -m tests.integration.faker_repro._routes --write` once FAKER-REPRO R1 has merged, and `output_lock.py --write` run again and `git status` stays clean.
- G-3: the S2 diff under `tests/` touches only the paths 5.6 owns (including `tests/fixtures/golden/faker_repro_routes.json` once FAKER-REPRO R1 has merged), `_faker_lock_lists.py`, the AT-B1 cell (b), the AT-P3 cell, and the `PINNED_FAKER_VERSION` line. Any other `tests/` path fails the gate.

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"):

The round-4 head has 12 direct files in `scripts/faker-determinism/` and 5 in `tests/sentry/dependencies/`; the revised layout has 12 and 8 respectively, below the roughly 25-module fan-out limit.

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `scripts/faker-determinism/output_lock.py` | new (S1, below 700 lines): worker, writer, capture and seven-kind diff | `CODEMAP.md:280`, Dev tooling: one-off tools in `scripts/faker-determinism/`, named by tool concern | `check_determinism.py`, `digest_codec.py` |
| `scripts/faker-determinism/argument_grid.py` | new (S1, below 450 lines): the one caller-argument surface discovery, parameter-shape registry, grid derivation and closed descriptor codec | same | `output_lock.py`, `digest_codec.py` |
| `scripts/faker-determinism/_engine_access.py` | new (S1, about 45 lines): the only tool-facing access to engine-internal names and runtime caller artifacts for both determinism tools; accepted same-repo dev-tool exception | same | `check_determinism.py`, `pool_determinism_worker.py` |
| `scripts/faker-determinism/worker_env.py` | new (S1, about 30 lines): standard-library-only worker environment builder moved from `check_determinism.py:197-205`, shared by both tools | same | `digest_codec.py` |
| `scripts/faker-determinism/check_determinism.py`, `pool_determinism_worker.py`, `digest_codec.py` | changed (S1): import the shared environment builder and engine access seam; add canonical date/datetime/Decimal scalar tags and remove value repr from codec failure | same | each other |
| `scripts/faker-determinism/output_lock.json` | new (S1, generated) | same | `golden_digests.json` |
| `scripts/faker-determinism/README.md` | changed (S1): the lock, its writer, the reviewed lists and the post-1.0 rule | same | |
| `tests/sentry/dependencies/test_faker_output_lock.py` | new (S1, below 500 lines): worker capture, classification, runtime diff and calendar tests | `CODEMAP.md:278`, Sentry test: dependency rules in `tests/sentry/dependencies/`, `test_<rule>.py` | `test_dependency_floors.py` |
| `tests/sentry/dependencies/test_faker_output_lock_schema.py` | new (S1, below 400 lines): strict schema, reviewed sets and names-only diff tests | same | `test_faker_output_lock.py` |
| `tests/sentry/dependencies/test_faker_output_lock_arguments.py` | new (S1, below 550 lines): derived caller-surface coverage, grid properties and argument-only mutations | same | `test_faker_output_lock.py` |
| `tests/sentry/dependencies/_faker_output_lock_support.py` | new (S1, below 250 lines): shared loader, subprocess fixtures and stub helpers for the three sentry modules; no tests | `CODEMAP.md:278`, Sentry helper `_<name>.py` beside its dependency sentries | `_faker_lock_lists.py` |
| `tests/sentry/dependencies/_faker_lock_lists.py` | new (S1, below 600 lines): reviewed unstable, raises, calendar and anchor lists with locale-set compression | same | the three output-lock sentries |
| `tests/sentry/dependencies/test_faker_pin_agrees.py` | new (S1, about 120 lines; S2 adds the Dependabot cell) | same | same |
| `tests/unit/providers_v2/test_faker_adapter.py` | changed (S1, +64, replayed) | Unit tests | |
| `tests/unit/generation/test_faker_provider_failure_code.py` | new (S1, about 50 lines) | Unit tests mirroring `generation/` | other generation tests |
| `pyproject.toml`, `uv.lock` | changed (S1: `time-machine` floor, exact lock resolution, marker registration/deselection; S2: Faker) | | |
| `NOTICE` | checked and unchanged in S1; changed by its owner in S2 only if the shipped Faker repin requires it | | |
| `src/decoy_engine/quality/dp_provenance.py` | changed (S1 and S2, one row each with its comment line) | Quality | the other rows |
| `.github/workflows/ci.yml` | changed (S1: new 3.10/3.11/3.12 `faker-output-lock` matrix job running `pytest tests/sentry/dependencies/test_faker_output_lock.py -m faker_output_lock --tb=short`; `import-smoke` unchanged) | Lightweight automatic PR checks | |
| `ci/required-jobs.toml` | changed (S1: required Faker job, no path filter) | CI lane registries | |
| `tests/sentry/test_sentry_manifest.py`, `tests/sentry/tooling/test_ci_lanes.py`, `tests/physical/test_faker_determinism_driver.py` | changed (S1): list all four new sentries including pin agreement, guard the job, shared environment builder and sole engine-internal access module | Test and CI sentries | existing manifest, lane and driver tests |
| moved goldens of 5.6 | changed (S2, by tool) | their existing places | |
| `src/decoy_engine/support/_probe.py` | changed only if S0 says so (S2) | Support bundles | |
| `changelog.d/faker-migrate.md` | new (S2) | Changelog fragments | |
| `docs/compatibility-contract.md`, `docs/determinism.md` | changed (S2) | Feature and contract docs | |
| `.github/dependabot.yml` | changed (S2) | Lightweight automatic PR checks | |
| `docs/records/2026-11-<dd>-faker-repin-impact.md` | new (S0) | Plans, decisions, records | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"): `C:requirements-certified.txt` and `C:requirements-dev.lock` (changed by their tools); `C:tests/sentry/test_faker_pin_agrees.py` (new, sentry test, beside the other CLI sentries); `C:docs/guides/shape-and-privacy/04-differential-privacy.md`, `C:docs/release/frozen-surfaces.md`, `C:docs/roadmap/release-gates.md`, `C:docs/roadmap/groups/mask.md`, `C:docs/roadmap/decisions.md`, `C:CHANGELOG.md` (changed). No new source module in either repo.

## 10. Design notes

- Choke point for "Faker output may not move unseen": the output lock and its split sentry suite. Every route in 5.2 reads Faker through the reflected, adapter or raw surface. `argument_grid.py` derives the argumented cells from the four production caller families and their effective signatures. The installed Faker can change only through `uv.lock`. The walk is proved to see a seeded bypass by AT-L3, AT-L4, AT-L11, AT-L13 and AT-L16 to AT-L20.
- Choke point for caller-argument coverage: `argument_grid.py` owns `ArgumentTarget`, the required family set, `PARAMETER_SHAPES`, `PARAMETER_KIND_BY_NAME`, descriptor encoding and grid derivation. No sentry repeats a method list or parameter list. `_formula_scope`, reflected providers and the public adapter registry remain the production roots. The reflected family reuses `reflected_kwargs` as its accepted-name source. `_engine_access.py` only exposes these artifacts to the tool. AT-L17 proves every discovered parameter has a row, AT-L18 proves the derived grid is closed and bounded, and AT-L19 fails if a known family or target disappears.
- Choke point for "one Faker version": the `pyproject.toml` pin. The other copies are generated or capture records, and AT-P1 and CV-P1 keep them equal.
- Choke point for engine-internal access from `scripts/faker-determinism/`: `_engine_access.py`. The existing pool harness and the new output-lock tool both need production-private seams, so this is an accepted same-repo dev-tool exception rather than a claim that those names are public. AT-L15 walks the folder's Python AST and fails on a second direct `decoy_engine.internal` import; its seeded mutation adds one to `output_lock.py`.
- Why separate processes: `time-machine` must start before `faker` is imported, because some providers read the date in a default argument, which Python evaluates at import. The same processes give the cross-hash-seed check of the existing harness. `worker_env.py` is the one environment builder for both tools, and AT-L14 guards against a second copy.
- Why concurrent workers: each clock worker is independent. The writer runs A/0 through A/7 and B/0 through the bounded executor. The sentry splits those same nine jobs into A/0 through A/3 and A/4 through A/7 plus B/0 so each marked test stays below 180 seconds, then joins every document before classification.
- Why two clocks: a frozen clock makes a calendar-reading pair stable but hides that it reads the calendar. Clock A is 2026-10-16 and clock B is 2030-01-16. They cross month, year and decade boundaries while holding day and time constant. AT-L20 requires the decade-, year- and month-relative representatives to move; the calendar set is then a reviewed list.
- Why lock under 40.23.0 first (S1 before S2): the S2 lock diff is then the complete, tool-made list of moved pairs.
- Why 8 no-argument samples and 2 argument samples: reflected `per_seed` is the per-row generation shape; reflected `sequential` and adapter `batch` are pool shapes; raw cells capture other engine calls. Argumented cells use seeds 0 and 7 so every current method and parameter fits the explicit row, byte and time budgets. Coverage comes from derived parameter rows, not a large draw count per row.
- Why every Faker locale: `plan/checks/_generate_columns.py:230` admits any locale in `AVAILABLE_LOCALES`, and masking passes the configured locale straight to `Faker(locale)`.
- Why not vendor now: section 2. The lock is what a later vendoring row needs as its acceptance test.
- No new structure in `src/`. The tools print provider names, locale names, file names and versions only; Faker exception messages are never stored (AT-L8).

## 11. Size

| Slice | Src lines | Test and tool lines | Generated | Docs lines | Files touched |
|---|---|---|---|---|---|
| S0 | 0 | 0 | 0 | about 150 (record) | 1 |
| S1 | about 3 (DP row) | about 3,900 (writer below 700, argument grid below 450, engine access 45, environment helper 30, codec 35, three lock sentries, reviewed lists and support about 2,250, pin sentry 120, replayed tests 64, AT-B1 50, CI and physical guards about 150) | `output_lock.json` at most 32 MiB with actual size recorded in the PR, `uv.lock`; `NOTICE` verified unchanged | about 60 | about 23 |
| S2 | about 15 (pin comment, DP row, probe only if moved) | about 30 (AT-P3, AT-B1 cell b, reviewed-list entries) | `uv.lock`, `NOTICE`, the moved goldens of 5.6 | about 100 | about 12 plus the moved goldens |
| C1 | 0 | about 60 | the two CLI requirement files | about 40 | about 10 |

New public names: none in the engine package. The round-4 head's `test_faker_output_lock.py` is 914 lines and fails the file-size rule. S1 replaces it with the three cohesive test files above, each below 600 lines. `output_lock.py` stays below 700 lines and `argument_grid.py` below 450; no planned hand-written file is at or above 800 lines.

## 12. Slices

| Slice | Repo | Content | Risk | Line budget | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|---|
| S0 | engine (record); runs on the Dell or the Mac, never the devbox | Build a clean venv from `origin/main` with `faker==40.54.0` (scratch lock, not committed). Run: the full default suite; `dp_certified` in the certified environment; `golden`; `ml` and `ner`; `determinism_harness`; `testflight`; the native companion suite; each marker set with the `scripts/dev/junit_ran.py` no-skip check; the proof-manifest and capability-matrix checks; the CLI e2e suite against that engine. Record each red test id, the 5.6 row that owns it, and moved or unchanged for every 5.6 row. Check by name: `date_time` with start equal to end, the new `file_path` keyword argument, the `pyfloat` refusal, `bank()` exception class. Repeat the wheel diff 40.23.0 to 40.54.0. Addendum (rev 3.4), when FAKER-REPRO R1 has merged before S2 starts: the data-order audit sentry and the route matrix under 40.54.0 (Order) | R0 (record only) | 150 docs | G-1 | none (Q1 settled) | none (it is the measurement); Codex reads the record |
| S1 | engine | `time-machine` floor in `dev` with its exact `uv.lock` resolution and DP row; NOTICE owner/check with no diff; one engine-internal access module; shared worker-environment helper; canonical scalar codec extension; lock worker and writer with reflected, adapter, raw and derived caller-argument surfaces; `output_lock.json` version 2 captured under 40.23.0 by CPython 3.10.20 at clocks in 2026 and 2030; one grid module; three cohesive output-lock sentries below 600 lines each with reviewed lists, anchors, floor, exact runtime-family coverage and parameter coverage; static/worker marker split; required 3.10/3.11/3.12 Faker matrix job while import-smoke stays unchanged; the three replayed tests; AT-B1 observation and bank cell; README; row, byte and split-worker timing measurements; one Mac run recorded | R2 (dependency lock and DP row; no product change) | 3,900 test and tool, 5 src, 60 docs | AT-L1 to AT-L21, AT-P1, AT-P2, AT-S1, AT-B1 (a), AT-DP1 | none | Escalation triggers (dependency lock): T3 full suite on the Mac or Dell on the exact head against the saved main baseline; `dp-certified-gate`; required `faker-output-lock`; each named mutation on the final head; Dennis then Codex |
| S2 | engine | The repin of 4.4: pin, `uv.lock`, `NOTICE`, lock rewrite and reviewed lists, moved goldens by tool, DP row, probe if moved, fragment, contract and determinism docs, Dependabot | R2 (moves frozen output; dependency lock; version pin; DP row) | 30 src, 40 test, 100 docs; generated files exempt | AT-P2, AT-P3, AT-DP1, AT-R1, AT-F1, AT-B1 (b), G-2, G-3 | S0 record read by the owner; S1 merged; freeze-batch engine release merged (owner Q11, decided 2026-11-18); on or after 2026-11-24 | T3 full suite on the Mac or Dell on the exact head against the saved main baseline; the S0 marker sets with the no-skip check; `dp-certified-gate`; each mutation; Dennis then Codex |
| E-REL | engine | The next daily engine release stamps the DP rows with the new engine version (`stamp_release.py`, existing release prep) | release train | n/a | `test_dp_lock_row.py` on the release head | S2 | release checks |
| C1 | CLI | The checklist of 4.5 | R2 (certified profile, repin) | 60 test, 40 docs; generated exempt | CV-P1, CV-DP1 | E-REL | CLI T1 (e2e that touch generation and masking, sentries) plus T2 on the head; `cert_smoke.py`; the CI release smoke and fresh-install smoke; Codex |

Order: S0 and S1 start now, in parallel (S1 does not depend on 40.54.0). S2 starts on or after 2026-11-24, after the owner has read the S0 record and after the freeze-batch engine release has merged (owner Q11, decided 2026-11-18: freeze release before Faker S2). S2 and C1 merge before row 93 (REL-GATE). Merge-order rule for goldens: whichever of S2, E#661 and FREEZE-OUTPUT merges later re-runs every tool in 5.6 and `output_lock.py --write` on its own head (G-2); goldens are never merged by hand. FAKER-REPRO R1 (`docs/plans/2026-11-19-faker-reproducible.md`) is planned after S1 and before S2: it moves only newly reproducible lock pairs, adds the route golden and the `_CANONICAL_ORDER` audit of 5.6, and joins the merge-order rule above. If R1 has merged when S2 starts, an S0 addendum on a clean 40.54.0 venv from `origin/main` runs `tests/sentry/dependencies/test_faker_repro_audit.py` and `tests/integration/faker_repro/` with `-m faker_output_lock`, and records moved or unchanged for both FAKER-REPRO rows of 5.6 before S2 regenerates anything. If E#661 merges before S2, a plan revision first extends 5.2 and the lock to the `provider` generate type.

Open PRs that touch the same files (checked 2026-11-18): E#583 (Dependabot group: `pyproject.toml`, Faker 40.23.0 to 40.54.0 plus five packages; superseded for Faker by S2, owner Q6); E#661 (GEN-PROVIDERS E1: `generation/_faker_pool.py`, `testflight/golden_fingerprints.json`, Faker pool tests); E#333 (parked draft).

## 13. Recurring-defect class check

- A test weakened to pass: every red test under 40.54.0 is either owned by a 5.6 tool or stops the slice (FM-4); G-3 limits the `tests/` diff to owned paths. The one literal that moves in a test file is `PINNED_FAKER_VERSION`, the capture record the F0 test names, and it moves only with the F0 recapture.
- A golden refreshed as a reflex: G-2 re-runs every tool on the head.
- Copies of a fact: the Faker version has five engine copies and two CLI copies, all generated or capture records, kept equal by AT-P1 and CV-P1.
- Anchored validation (catalog 1): digests and versions are checked with `re.fullmatch` (AT-L2, 4.2).
- Strict stored types (catalog 2): AT-L2 substitutes wrong types for every primitive field and every list element, including bool, float and string substitutions for integer fields, integer and bool substitutions for strings and string-list elements, and non-bool substitutions for booleans. AT-L18 does the same for argument descriptors. Every copy is refused. Unknown keys, malformed dates, short digests, extra newlines and non-canonical bytes are refused separately.
- Exception context (catalog 3): the stored adapter result deliberately names only the outer and explicit `__cause__` classes to distinguish Faker failures hidden by `AdapterError`; it never stores messages. The tools raise their own fixed refusals outside `except` blocks. AT-L8 catches every raised tool error and asserts `__cause__ is None` and `__context__ is None`. The codec's existing value repr is removed.
- Versioned read models (catalog 4): `lock_version`, closed key sets and strict canonical bytes are checked by AT-L2; an unknown major or missing version is refused.
- Normalized guard scanners (catalog 5): AT-L15 parses the Python AST rather than matching text and covers both import statement forms and aliases. AT-L17 no longer scans call syntax; it derives runtime caller families and effective signatures, so a local callable alias has the same identity and coverage as a direct attribute call. AT-L19 requires every known family and current target. The CI guard parses the workflow structure already owned by `test_ci_lanes.py`.
- No private-module imports (catalog 6): `_engine_access.py` is the one accepted same-repo dev-tool exception for both determinism tools; these are not public exports. AT-L15 fails if any other file under `scripts/faker-determinism/` imports `decoy_engine.internal` directly. The standard-library-only `worker_env.py` has no engine edge (AT-L14).
- No hidden CI failures (catalog 7): the required Faker job has no path filter or `continue-on-error`, sets `strategy.fail-fast: false`, and gives worker cells finite explicit timeouts (AT-L12).
- One trust class per entry point (catalog 8): the worker CLI takes only repository-controlled clocks/locales from the writer and tests; no user entry point changes.
- Mutations on final head, checked allowlisted helpers and no raised pins (catalog 9 to 11): every named mutation runs on the final slice head; no allowlist grows; the 150-second worker and 180-second cell timeouts are not raised.
- A dependency failure misread (the 2026-07-23 event): S0 reproduces every red in a clean venv on a test node from `origin/main`, never in a working venv.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (a Faker output value or exception text in the lock or a sentry message) | output is stored only as digests and exception class names; `arguments` stores only the fixed synthetic descriptors derived in 4.1; messages carry names and versions | AT-L3, AT-L8, AT-L16 | record `str(exc)` in the lock | S1 |
| 2 | Cleanup on every exit | worker processes are run with a timeout and always reaped by `subprocess.run`; the clock freeze lives only in the worker process, so no test process keeps a frozen clock | AT-L1 (a hung or failing worker fails the sentry, never skips it) | leave `time_machine` travel running in the pytest process | S1 |
| 3 | State completeness (every lock entry kind and diff kind handled) | one diff function with one branch per kind: changed, removed, added, newly reproducible, newly unstable, newly calendar-dependent, no longer calendar-dependent | AT-L3 to AT-L9 | merge "added" into "changed" | S1 |
| 4 | Route coverage (a Faker route the lock does not see) | reflected, adapter, raw and argumented surfaces cover every route in 5.2; caller families, methods and parameters are derived from runtime artifacts and effective signatures | AT-L11, AT-L13, AT-L16 to AT-L19 | omit the adapter family or one reflected parameter | S1 |
| 5 | Referential integrity | N/A: no FK or cross-table state changes (5.3) | none | none | none |
| 6 | Untrusted input | N/A: the lock, the requirement files and `dependabot.yml` are repo files written by tools or reviewers, not user input; the sentry still refuses unknown keys and wrong types (AT-L2) and parses YAML with `safe_load` | AT-L2, AT-P3 | accept unknown keys | S1, S2 |
| 7 | TOCTOU (lock computed on one Faker or clock, checked on another) | the lock records `faker_version` and `clocks`; the 3.10.20 writer refuses when its interpreter or installed Faker differs from the pin; AT-P1 ties the lock version to the pin; the clock is set before import | AT-P1, AT-L6 | make the worker ignore `--clock` | S1 |
| 8 | Weak proof (a lock too coarse to see a change, or a degraded writer) | 8 no-argument draws, 2 draws for every derived argument row, boundary-crossing clocks, eight clock-A hash seeds in both writer and sentry, exact caller provenance, reviewed lists, anchors and an `en_US` floor | AT-L6, AT-L7, AT-L10, AT-L16 to AT-L20 | change `random_int` only when `min == max == 7` | S1 |
| 9 | Refactor drift | N/A: no source refactor; S2 changes a pin and data, and AT-P2 limits each `uv.lock` diff to its package | AT-P2 | an unrelated upgrade | S1, S2 |
| 10 | Frozen contract drift (output moves without its records) | pin, lock, goldens, DP rows, fragment, contract note and D-4 text move in S2 and C1 together | AT-R1, AT-F1, AT-DP1, CV-P1 | keep `faker==40.23.0` in the CLI dev lock | S2, C1 |

## 14. Pre-mortem

- "S2 refreshed a golden that hid a real regression." Guard: S0 maps every red to an owner before S2 starts (G-1); an unmapped red stops the slice (FM-4); G-3 limits the `tests/` diff; Dennis reads the lock diff against the wheel diff of section 2.
- "The lock passed because the calendar was frozen." Guard: two clocks and the reviewed calendar set (AT-L6).
- "The lock was green while masking moved." Guard: the adapter surface (AT-L11).
- "The lock was green while caller-supplied arguments moved output." Guard: the derived grid covers all four caller families and every current signature parameter; the reflected and adapter `random_int(min=7,max=7)` mutations turn AT-L16 red, and AT-L17 to AT-L19 guard construction.
- "The DP gate went green by skipping." Guard: `dp-certified-gate` fails on any skip (`scripts/dev/junit_ran.py`), and `test_dp_lock_row.py` never skips.
- "We misread a dependency failure again." Guard: S0 runs in a clean venv on a test node from `origin/main`; the pin comment names the `mimesis` root cause.
- "After 1.0 a Faker security fix cannot ship." Answer: it ships in 1.x when the lock diff has only allowed kinds; otherwise the Later vendoring row is the path, or 2.0.
- "The lock sentry slows every test run." Guard: only static cells remain in the default sentry route; marked workers run concurrently in the required Faker job, with recorded split-worker timing and explicit 180-second cell timeouts that are not raised.
- "Two slices recapture the same goldens at once." Guard: the merge-order rule in section 12.

## 15. Residual risks

- R-1: a no-argument change that shows only past the first 8 draws, an argumented change that shows only past seeds 0 and 7, or a rare branch outside the derived shapes is not in the lock. The named equal-boundary shapes cover the `random_int` counterexample; S0 separately checks `pyfloat` collapse and `date_time` with equal bounds. The harness and the other goldens see the admitted pool pairs; the per-row long tail relies on the lock.
- R-2: the derived grid covers every current method and caller-settable parameter, including equal and ordered lower/upper boundaries, but it does not take the Cartesian product of all parameters or every legal value. AT-L17 fails if any parameter has no row; AT-L16 pins the collapsed `random_int` boundary counterexample. S0 still checks release-specific behavior such as `file_path(allowed_path_traversal_elements=...)` and the `pyfloat` refusal by name.
- R-3: Faker import-time behaviour (locale fallback, a renamed locale) is seen only through `AVAILABLE_LOCALES`, `resolved` and the name sets. Multi-locale configs (a locale list, which `make_faker` accepts) are not in the lock; their output is a function of the single-locale providers it covers, but the proxy's locale choice is not checked.
- R-4: `make_faker` falls back to `en_US` for a locale Faker cannot build (`faker_setup.py:660`). The lock records `resolved` per locale, so a locale that starts falling back shows as a change, but configs that already fall back are locked as `en_US` output.
- R-5: platforms outside owner question A's blocking set (Mac before a Mac CI leg exists; Windows before WIN-RUNNER).

## 16. Owner questions

Questions A to D were decided by the owner on 2026-11-18 with the recommended answers below.

| Id | Question | Recommended | Why |
|---|---|---|---|
| Q1 | Target Faker version | Settled 2026-11-18: 40.54.0 | Carries seeded `uuid1`/`uuid7`, current ISO 4217 codes and `en_GB` VAT check digits into the frozen 1.x line |
| Q2 | Lock every Faker locale, or only the five harness locales? | Every locale | The engine admits any locale in `AVAILABLE_LOCALES`; a `pt_BR` user gets moved `job` output from this change |
| Q4 | Vendoring or snapshotting the providers: Later (1.x), not 1.0? | Later | Non-breaking after 1.0; large surface; the lock is its acceptance test |
| Q5 | Delete `fix/faker-40-31-migration` after S1 has replayed its three tests? | Yes, after S1 merges (owner-gated branch deletion) | Its conclusion is on main and its tests move in S1 |
| Q6 | Close Dependabot E#583, or rebase it without Faker? | Rebase without Faker (or let Dependabot reopen after the group exclusion lands) | Faker moves only in S2 with its lock |
| Q11 | Does Faker S2 run before or after the freeze-batch engine release? | Decided 2026-11-18: freeze release before Faker S2 | S2 depends on the released freeze batch, then reruns every owning golden tool on its own head under G-2 |
| A | Platform scope of the freeze | Linux is blocking now; the Mac comparison is recorded in S1; the Windows leg becomes blocking when WIN-RUNNER (row 6) lands; a Windows-only difference is fixed in the engine, not excluded from the lock | The owner must demo on Windows, so Windows output must match Linux, not be carved out |
| B | Does the 1.x freeze cover the `mimesis` extra? | No: the freeze covers the default install; contract 3.3 says so | `mimesis` rebinds five providers and has its own data churn; the stale branch showed it changes the provider set |
| C | Which lock diff kinds may a 1.x release carry? | Added providers, added locales, unstable to digest (newly reproducible), and no longer calendar-dependent. A changed digest is otherwise 2.0, as is a removed provider, locale or keyword argument or a pair that becomes unstable or calendar-dependent | A removed keyword argument breaks a config that passes it. Newly reproducible and no-longer-calendar-dependent output remove external variability; allow the latter in 1.x, the same as newly reproducible |
| D | How is the calendar handled in the lock? | `time-machine` under a pinned clock, computed at two instants; the production behaviour (fi_FI and sv_SE `ssn` output changes by day) goes to the roadmap inbox as F-4 | The lock must be deterministic to be a lock; fixing the product behaviour is a separate decision |

## 17. Follow-ups (outside the guarantee)

- F-1: the proof manifest depends on whether `mimesis` is installed at generation time (stale branch note). Pin the generation profile in `gen_proof_manifest.py` or record it in the manifest. Maintenance row.
- F-2: the Later row "snapshot Faker providers" takes `output_lock.json` as its acceptance oracle.
- F-3: if S0 shows newly certifiable pool pairs under 40.54.0, a widening row may admit them after 1.0 (additive).
- F-4 (roadmap inbox, not this plan): deterministic `ssn` output in `fi_FI` and `sv_SE` (and the other calendar pairs in `EXPECTED_CALENDAR`) changes with today's date in production, so the same config masked on two days can differ. Decide whether to pin the clock Faker sees during a run.
