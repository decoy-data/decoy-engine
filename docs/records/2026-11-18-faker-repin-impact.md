Status: record

# FAKER-MIGRATE S0: what Faker 40.54.0 changes in the engine

Plan: `docs/plans/2026-11-18-faker-migrate.md`, slice S0 (measurement only, no code change). Base: engine `origin/main` `ad36687a6` (0.27.0). Date: 2026-11-18.

## How it was measured

- Node: the Dell (WSL2, CPython 3.10.20). A scratch copy of the lock-synced dev venv with `faker==40.54.0` installed over 40.23.0. Nothing about the pin or the lock is committed.
- The suites ran from a clean checkout of `origin/main`, not a working tree.
- The lock preview in section 3 came from the S1 tool (`output_lock.py`, PR #695) run under 40.54.0 against the S1 lock captured under 40.23.0. It is the diff S2 will render.
- Times: two of the runs shared the node with other jobs, so the durations are upper bounds.

## 1. Suite results under 40.54.0

| Run | Result |
|---|---|
| Full default suite (`-n 12`) | 48322 passed, 5438 skipped, 11 failed. 1 failure is the Faker version pin (section 2). The other 10 are `tests/sentry/layout/test_import_layers.py`, which fail the same way on clean `origin/main` on this node because no import-linter venv exists here; `lint-imports` itself reports the contract kept. |
| `dp_certified` | 92 skipped. The 40.54.0 environment is not a certified row, so `tests/_dp_cert.py` skips the suite. This is the expected move of the dev/CI row. S2 adds the row and must run this lane with no skips. |
| `golden` | 106 passed, 8 skipped |
| `ml` and `ner` | 100 passed, 76 skipped |
| `determinism_harness` | 3 passed, 8 skipped (16 min). `golden_digests.json` and `certified_pairs.json` are unchanged. |
| `tests/native` | 5387 passed, 1977 skipped, 1 failed: `TestGoldenGateCoverage::test_every_routed_vector_reproduced_and_count_is_locked`. It depends on collection order, so it fails when the directory is split across xdist workers. It passed in the full default run. Not Faker related. |
| Proof manifest and capability matrix sentries | 9 passed (both files unchanged) |
| `tests/parity` | 4577 passed, 1203 skipped, 37 xfailed, 1 failed: `test_phase_f_f0_oracle.py::test_dependency_pins` (section 2). The FR0 refreeze checks and every F0 digest check pass. |
| `scripts/test_flight.py` | 58 invariant checks passed, 6 of 6 fingerprints match the golden |
| CLI suite against this engine | 6622 passed, 1 failed (section 5) |

## 2. Every red test maps to an owner (G-1)

- `tests/parity/test_phase_f_f0_oracle.py::test_dependency_pins` asserts `faker.VERSION == PINNED_FAKER_VERSION`. Owner: the F0 recapture row of plan section 5.6. No F0 digest moved.
- The 10 `test_import_layers.py` tests and the one native ordering test are not caused by Faker.

No other test goes red, so no new row is needed in section 5.6.

## 3. Output lock diff, 40.23.0 to 40.54.0

Names only. Counts are cells (a pair has up to two reflected cells or one adapter cell).

| Kind | Count | Main content |
|---|---|---|
| changed | 1243 cells, 632 pairs, all 107 locales | `uuid1` and `uuid7` (all locales); `currency_symbol` (all), `currency_code` and `currency_name` (90 locales); `bank` (26); `bban` and `iban` (11); `vat_id` (`bg_BG`, `de`, `de_DE`, `en_GB`, `it_IT`); `swift`, `swift8`, `swift11` (`bn_BD`, `es_CO`, `pt_BR`); `ko_KR` and `vi_VN` address family; `pt_BR` `cnpj`, `cpf`, `company_id`, `cellphone_number`; `en_CA` and `pt_BR` `ssn`. Adapter cells: `synthetic_account_number` (11 locales), `vi_VN` address names (5), `pt_BR` `person_phone`. |
| removed | 0 | |
| added | 138 | locales `mk_MK`, `si_LK`, `sr_BA`; the `file_path` keyword argument `allowed_path_traversal_elements` in all 107 locales; new `vi_VN`, `es_MX`, `pt_BR` provider names; `use_alphanumeric` on `pt_BR` `cnpj` and `company_id` |
| newly reproducible, newly unstable, newly calendar-dependent | 0 | |
| no longer calendar-dependent | 214 | `uuid1` and `uuid7` in all 107 locales (they are also in `changed`) |

For the five harness locales: `en_US` changes only in `currency_code`, `currency_name`, `currency_symbol`, `uuid1` and `uuid7`. Name, address, email and phone providers are unchanged in `en_US`. The masking (adapter) surface is unchanged in `en_US`.

## 4. The 5.6 golden rows

| Golden | Under 40.54.0 |
|---|---|
| `output_lock.json` and its reviewed lists | moved (section 3) |
| `golden_digests.json`, `certified_pairs.json` | unchanged |
| `tests/parity/_f0_expected.py` digests | unchanged. Only the `PINNED_FAKER_VERSION` literal moves. The capture tool is broken, see section 6. |
| FR0 refreeze data | unchanged |
| `docs/proof-manifest.json` | unchanged |
| `docs/capability-matrix.md` | unchanged |
| `testflight/golden_fingerprints.json` | unchanged |
| `PROBE_GOLDEN` (`support/_probe.py`) | unchanged (the probe test is green in the default run) |
| `_CERTIFIED_STACKS` dev/CI row | moved (the DP lane skips) |
| `NOTICE` | the `faker==` line moves. The license sentries skip on a drifted venv, so S0 did not exercise them. |
| `tests/snapshots/*`, `tests/native/test_draw_site_providers_golden.py`, fixtures, compat corpus | unchanged (green) |
| CLI goldens | unchanged (section 5) |

## 5. CLI

The full CLI suite (CLI `origin/main` `f1da00f5`) ran against a copy of the CLI venv with 40.54.0 installed: 6622 passed, 25 skipped, 1 xfailed, 1 failed in 43 min. The failure is `tests/e2e/first_user/journey/test_cli_journey.py::test_nothing_is_written_outside_the_temp_root`. It lists files under the node's home directory and caught log files that other jobs on the shared node wrote during the run, so it is not a Faker effect. No CLI golden moved. C1 still has to change the requirement files, the sentry and the docs of plan section 4.5.

## 6. Checks by name

| Check | 40.23.0 | 40.54.0 |
|---|---|---|
| `date_time_between` with start equal to end | returns a datetime | returns a datetime |
| `pyint(min_value=5, max_value=5)` | returns an int | returns an int |
| `pyfloat(min_value=1.0, max_value=1.0)` | `ValueError` | `ValueError` |
| `pyfloat(positive=True, max_value=0)` | `RecursionError` | returns a float |
| `pyfloat(positive=True, max_value=-5)` | `ValueError` | `ValueError` |
| `file_path` keyword names | `absolute category depth extension file_system_rule` | adds `allowed_path_traversal_elements` |
| `bank()` in `cs_CZ` (no bank list) | `AttributeError` | `NotImplementedError` |
| `uuid1` twice from one seed | different | equal |

In the engine, `faker_type: bank` in a bank-less locale escapes `generate_tables` as the provider's own exception with no engine code, on both versions (pinned by AT-B1 in PR #695).

## 7. Wheel diff

31 changed and 21 added files between the two wheels. Added: locales `mk_MK`, `si_LK` (person), `sr_BA` (ssn), `es_CO` (bank, internet), `es_MX` automotive, `pt_BR` bank. Changed: bank data in 11 locales, `ssn` in 7, `currency`, `date_time`, `file`, `lorem`, `misc` (`uuid1`, `uuid7` draw their timestamp from the seeded generator), `python`, `pt_BR` `company` (`company_id` now draws with `random_choices`), `pt_BR` `job` and `phone_number`, `ko_KR` and `vi_VN` address. `providers/person/en_US` is unchanged, which agrees with the plan.

## 8. Where the plan was wrong or incomplete

- Plan section 5.1 says `pyfloat(positive=True, max_value<=0)` raises `ValueError` under 40.54.0 where 40.23.0 returns a value. Observed: `max_value=0` goes from `RecursionError` to returning a float, and a negative `max_value` raises `ValueError` on both versions. The S2 pyfloat cell of AT-B1 and the fragment bullet need the observed behavior.
- `python -m tests.parity._f0_capture`, named as the owner of the F0 digests, fails on `origin/main` under 40.23.0 as well. Fixture `rf` raises `generate_column_forward_reference` at plan compile. S2 cannot regenerate `_f0_expected.py` with it as it stands. Since no F0 digest moves, S2 needs only the `PINNED_FAKER_VERSION` literal, and the tool needs its own fix first.
- The plan says the S2 lock diff may hold `newly unstable`. It holds none. The writer finds 239 cells that already differ between processes at one frozen clock under 40.23.0 (for example `passport_full` and `passport_gender` in about 104 locales, and `nif`, `nie`, `cif`, `nuss` in the Spanish locales). They are hash-seed dependent. S1 records them in `EXPECTED_UNSTABLE` with a follow-up note.
