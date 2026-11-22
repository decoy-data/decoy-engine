Status: plan (revision 2, 2026-11-22)

# FAKER-NATIVE-WIDEN: every poolable string Faker provider runs native under the default pool

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FAKER-NATIVE-WIDEN (group mask; record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` item C1; V1 fast-path audit rank 2, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine only. The CLI gets it through its next engine pin bump.

No earlier plan file exists for this row: `git log --all -- 'docs/plans/*faker*widen*'` is empty and no plan branch names the row outside the 2026-11-19 record. This is revision 1.

Revision 2 (Dennis round 1, NO-GO): the out-of-core reservation is measured from the built pool, so widening cannot fail a job that reroutes and succeeds today (S0, W1); the out-of-core template proof uses a deterministic copy of the HIPAA set; the totality sentry walks every `pool_native` backend; the Mimesis gate record is spelled out; three missed text and test sites are named.

Anchors: a path with no prefix is under `src/decoy_engine/`. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head. The plan builds on `plan/faker-default-pool` (revision 3) and must stay consistent with `plan/faker-migrate` (revision 3.9), `plan/route-label-truth`, `plan/per-column-routing` and `plan/native-threads-default`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (route admission on the hot mask lanes for the providers every CLI template uses; a frozen-contract paragraph changes; marked byte changes on degenerate columns). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): every provider runs its fastest path by default; each column runs its own path; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

## 1. Frame

The native faker operator selects `pool.values[derive_index(...)]` from a pool that Python builds. The Rust kernel holds no Faker data and does not care which provider built the pool (`execution/_strategies/_faker.py:89-121` builds the pool through `resolve_faker_pool_identity`; the native routes take the same pool). The only thing that keeps other providers off the native route is one literal:

- `execution/_operator_registry.py:211-214`: `provider_allowlist=frozenset({"person_first_name", "person_last_name"})`, commented as "the frozen C1 recipe's providers".

Every admission site reads that one set:

| Site | Use |
|---|---|
| `execution/native/_faker_positional_admission.py:30`, `:62-68` | stage A of the position-keyed (non-deterministic) chunked route |
| `execution/native/_faker_deterministic_admission.py:43`, `:97-100` | deterministic chunked admission |
| `execution/native/_real_type_admission.py:55`, `:163` | first-chunk route decline `faker_provider_not_native` |
| `execution/physical/_shadow_bindings.py:76`, `:179` | unified-slice binding |
| `execution/_sequential_native_ops.py:62`, `:418` | sequential FK route |
| `execution/out_of_core/_compat.py:388`, `execution/out_of_core/_faker_native.py:86` | out-of-core route |
| `execution/_faker_degenerate_pin.py:39`, `:97`, `:125` | string type pin for deterministic faker on int/bool sources |

So the registry already gives one choke point. The work is to prove each added provider is safe on every route and to widen the set.

Measured (audit, 2026-11-22): `faker(person_name, email, phone, address_*, zip)` runs pandas full frame in any form unless it is deterministic with a namespace and `pool_size`, and then chunked pandas. 58 of the 109 engine disguise rules and all four CLI templates (`hipaa`, `pci`, `gdpr`, `minimal`) use these providers. FAKER-DEFAULT-POOL moves first and last name onto the native route; this row moves the rest.

Provider inventory (`providers_v2/_real_registry.py:68-90`, Faker method map `providers_v2/_faker_adapter.py:43-61`, Mimesis adoption `providers_v2/mimesis/_adoption_matrix.py:52-60`):

| Provider | Faker method | Pool value type | Mimesis-bound when installed | In this row |
|---|---|---|---|---|
| `person_first_name`, `person_last_name` | `first_name`, `last_name` | `str` | yes | already native |
| `person_name`, `person_full_name` | `name` | `str` | yes | S1 |
| `person_email` | `email` | `str` | yes | S1 |
| `person_phone` | `phone_number` | `str` | no | S1 |
| `address_street`, `address_city`, `address_state`, `address_zip` | `street_address`, `city`, `state`, `postcode` | `str` | no | S1 |
| `synthetic_account_number`, `synthetic_member_id`, `synthetic_plan_id` | `bban`, `numerify` | `str` | no | S2 |
| `person_dob` | `date_of_birth` | `datetime.date` | no | excluded: the operator takes a string pool |
| `address_full`, `lorem_text`, `uuid`, `random_int_range`, `random_choice` | | per-row draw | | not poolable (`python_only`) |
| ipv4 | `ipv4` | `str` | no | S3, owner-gated: no registry provider exists today |

The disguise rules name Faker methods (`faker_type: ipv4`, `first_name`, `zipcode`, ...). Every method except `ipv4` maps to a registry provider above. `ipv4` has none, so an ipv4 rule cannot reach any `faker` mask config today (the CLI scaffolder maps a scanned ipv4 column to `redact`, `C:src/decoy/cli/_init_inference.py:206`).

## 2. Established solutions

Search run: how pool- or dictionary-based fake-data tools decide which generators can be pre-built and index-selected (Faker's own `unique` and proxy docs, SDV/RDT `AnonymizedFaker`, Tonic and Gretel "consistent" fake replacement docs, Mimesis `Schema`), and the engine's own pool design.

- Tonic's consistency mode and RDT's `AnonymizedFaker(enforce_uniqueness=False)` both replace a value with an element of a pre-built or hashed finite domain. Neither restricts that to a named subset of generators; the rule is "a generator with a finite, value-typed output can be pooled". The engine's capability matrix already records exactly that per provider (`poolable`, `providers_v2/_real_registry.py:69-90`) and `classify_provider` turns it into `pool_native` (`execution/native/_provider_class.py:85-104`).
- The selection is the engine's own derive-index recipe (HMAC-keyed index into the pool, `derive_index`), the same on every route. It is provider-agnostic by construction.
- So no new mechanism is needed. The design follows the engine's existing pattern: one allowlist in the operator registry (`execution/_operator_registry.py`, module docstring lines 1-16) and the existing runtime string-output check (`execution/native/_chunked_pools.py:48-60`, `pool_values_are_strings`).

### Reuse inventory

- `OPERATORS["faker"].provider_allowlist`: the one set every site reads. This row edits only it.
- `classify_provider` and the live `ProviderRegistry`: the source the totality sentry walks.
- `pool_values_are_strings` and the codes `faker_provider_output_not_string`, `chunked_faker_nondeterministic_pool_not_string`: the runtime guard for a pool that is not all strings, for any provider and locale.
- `resolve_faker_pool_identity` and `effective_pool_size` (FAKER-DEFAULT-POOL): unchanged.
- The parity helpers in `tests/parity/_faker_seq_data.py`, `tests/parity/_ooc_faker_data.py` and `tests/native/_chunked_faker_support.py`: reused by the new proof tests.

## 3. Guarantee and non-goals

After S1 and S2:

1. For each provider in the allowlist (section 1 table, rows marked S1 and S2), a `faker` column with `cardinality_mode` absent or `reuse`, deterministic with a namespace or not, with or without `pool_size`, gets the same admission decision on every route as `person_first_name` gets today with the same shape.
2. On every route that admits it, its output equals the forced full-frame pandas output of the same config, row for row and type for type, except the marked degenerate-type changes in section 10.
3. The guarantee holds for both pool backends: Faker, and Mimesis when the optional `mimesis` extra is installed and the provider is in `ADOPTED_MIMESIS_PROVIDERS`.
4. One list: the allowlist stays one literal in `execution/_operator_registry.py`. A sentry proves it is total over the live registry: every `faker` or `mimesis` provider classified `pool_native` is either allowed or named in the sentry's exclusion table with a reason.
5. A pool that is not all strings (a custom provider registered under an allowed name, or a locale whose method returns something else) never reaches the kernel. It keeps today's route-specific outcome (FAKER-DEFAULT-POOL section 4, "Custom provider").

Non-goals: `person_dob` (a date pool needs a typed take; logged as a follow-up); non-poolable providers and composite bundles (per-row Python draws); `unique`, `match_source_cardinality` and `scale_source_cardinality` modes; faker on an FK key column (the chunked FK gate admits only `hash` as a self-masking key, unchanged); generation-side pools (`generation/_faker_pool.py`); the CLI route label (ROUTE-LABEL-TRUTH); the translation of disguise `faker_type` names into mask configs.

## 4. Enumerations

### Exit paths

- Admitted: native (`rust_pool_select`) under 100,000 rows; chunked native at 100,000 rows or more for a string source; chunked oracle leg for other source types, exactly as for `person_first_name`.
- Declined for another reason (open `when:`, a non-REUSE mode, a source type outside the domain): unchanged coded decline.
- Pool not all strings: unchanged route-specific outcome (FAKER-DEFAULT-POOL F5): chunked preflight `chunked_faker_nondeterministic_pool_not_string` before the first chunk; unified slice catches `FAKER_POOL_NON_STRING_OUTPUT` and reroutes to pandas; full frame succeeds.
- `person_dob` and non-poolable providers: `faker_provider_not_native:<column>:<provider>` (unchanged code).
- Out-of-core pool budget: `out_of_core_faker_pool_budget_exceeded` before scratch creation (the FAKER-DEFAULT-POOL F6b path), now reachable with more providers.

### Routes

| Route | Today, S1/S2 provider | After |
|---|---|---|
| Unified slice | declined, table on pandas | admitted |
| Chunked native (string source) | declined, full frame (or chunked oracle leg when deterministic with `pool_size`) | admitted |
| Chunked oracle leg (int/bool source, deterministic; numeric/bool source, positional) | deterministic only with explicit `pool_size` | admitted, as for first name |
| Sequential FK | `faker_provider_not_native` | admitted on non-key columns |
| Out-of-core, deterministic REUSE with a namespace | `out_of_core_faker_pool_unsupported`, reroute | admitted for an exact `string` source; pool reservation measured (S0) |
| Out-of-core, position-keyed (non-deterministic) | `out_of_core_faker_pool_unsupported`, reroute | unchanged: still declines and reroutes (`execution/out_of_core/_faker_native.py:86-91` admits only deterministic REUSE) |
| Full-frame pandas | runs | unchanged; the degenerate pin now covers the new providers (section 10) |

### FK shapes

- Faker on an FK key column (parent key, child key, composite part): never native; the chunked FK gate admits only `hash` as a self-masking key (`execution/_chunked_fk_vocab.py`). Unchanged, proved by P7.
- Faker on a non-key column of an FK child or parent table: native on the sequential route (`execution/_sequential_native_ops.py:418`) and the out-of-core route (`execution/out_of_core/_compat.py:388`), as for first name today. P4.
- Self-referencing and multi-edge tables: same rule per column; no shape-specific code.

### Fields

- `provider`: the only field whose accepted values grow.
- `deterministic`, `namespace`, `pool_size` (top level or `provider_config`), `locale`, `cardinality_mode`, `when`, `unique`: unchanged meaning and unchanged admission rules (`execution/native/_faker_positional_admission.py:62-68`, `execution/native/_faker_deterministic_admission.py:97-100`).

### Output surfaces

- The masked table (values and Arrow types): values unchanged, types per B1 and B2.
- Route evidence and `quality_metrics` (`native_executed`, per-column route): now names `rust_pool_select` for the new providers.
- Route decline records: `faker_provider_not_native` stops firing for the new providers.
- Warnings and row errors: none added or removed.

### Codes

No new reason code. `faker_provider_not_native` keeps firing for `person_dob`, non-poolable providers and unregistered names. Caller-visible text that changes:

- `execution/out_of_core/_compat.py:391-394`: "out-of-core faker admits only deterministic REUSE with a person-name provider" becomes "... with an allowlisted poolable provider".
- `execution/native/_faker_positional_admission.py:63-67`: the `chunked_strategy_conditions_unmet` condition text joins `sorted(_PROVIDER_ALLOWLIST)`, so the provider list it prints grows from two names to the full set. No code change there; named because callers see it.
- `execution/out_of_core/_faker_native.py:80` is a docstring, updated for accuracy only.

## 5. Design

One edit to the fact, proofs per provider, and a totality sentry.

1. `execution/_operator_registry.py:211-214`: the comment says the set is the string-pool providers proven by `tests/parity/test_faker_native_widen.py`; the set grows in two steps (S1, S2).
2. No admission site changes logic. The text in section 4 "Codes" changes.
2a. **Measured out-of-core reservation (S0).** `OocFakerPoolContext.get_pool` (`execution/out_of_core/_faker_pool.py:166-207`) reserves `pool_size * _RESERVE_BYTES_PER_VALUE` (4,096) before building, so a default pool reserves about 40 MiB against `min(run budget, 256 MiB)` (`execution/out_of_core/_runner.py:217-221`). Real pools of these providers measure under 1 MiB. Widening admits columns that decline and reroute today, so with the old reservation 7 distinct default pools (or 3 under a 100 MiB budget) would fail a job that succeeds today. The fix: on a cache miss, build the pool (the stock `PoolBuilder` returns exactly `pool_size` values, so the build is bounded by the pool size), measure it with the existing `estimate_pool_bytes` (`generation/pool/_value_pool.py:63`, the same function `PoolCache` budgets with), then reserve the measured bytes. Over budget still raises `out_of_core_faker_pool_budget_exceeded`, now only when the real pools do not fit, and the pool just built is dropped. The FAKER-DEFAULT-POOL preparation pass calls `get_pool` before `ScratchArena.fresh`, so the check stays pre-run. `_RESERVE_BYTES_PER_VALUE` and its comment block (`:40-56`) are deleted. One reservation rule, in one function.

   Row ownership: the reservation belongs to FAKER-DEFAULT-POOL, which already makes default first and last name pools reserve 40 MiB each and asserts in its F6b that three default pools under a 100 MiB budget fail before the run. That F6b outcome is the same function break on a smaller scale. Recommended: route S0 into FAKER-DEFAULT-POOL and change F6b to use a stub provider whose measured pool exceeds a small budget. If FAKER-DEFAULT-POOL merges without it, S0 lands here first, before S1.
3. The totality sentry `tests/sentry/defects/test_faker_native_allowlist_total.py` walks every provider id the live registry knows (`get_default_registry()`, plus the Mimesis-bound registry when importable) and, for each with `classify_provider(...) == "pool_native"` on any backend, requires it to be in `OPERATORS["faker"].provider_allowlist` or in the sentry's `EXCLUDED` map with a reason. `classify_provider` marks the whole `decoy_native` backend `pool_native` (`execution/native/_provider_class.py:57`, `:97`), so the map starts as: `person_dob`: "date pool; the operator takes string pools only"; `synthetic_ssn`, `synthetic_ein`, `synthetic_npi`, `synthetic_ndc`, `synthetic_mrn`: "decoy_native backend; its deterministic mode bypasses the Faker pool adapter, so the faker pool operator does not serve it". It also fails when the allowlist names a provider the registry does not classify `pool_native` (a stale entry). Mutation: delete `person_email` from the allowlist after S1 (red), or add `person_dob` to it (red on the stale/type check because its proof cell fails).
4. The proof suite is parametrized over `sorted(OPERATORS["faker"].provider_allowlist)`, so adding a provider to the set adds its proof cells with no second list.

Design notes: no new structure. The registry module is the single home of the fact (its docstring, lines 1-16). The sentry is the guard the cross-cutting rule asks for; the walk is over the live registry, not source text.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Depends on |
|---|---|---|---|---|
| S0 | Measured out-of-core reservation (section 5 item 2a), W1. Recommended to land inside FAKER-DEFAULT-POOL instead | `execution/out_of_core/_faker_pool.py`, tests | source about 15 net, tests about 80 | FAKER-DEFAULT-POOL preparation pass |
| S1 | Allow `person_name`, `person_full_name`, `person_email`, `person_phone`, `address_street`, `address_city`, `address_state`, `address_zip`. Totality sentry. Proof suite P1-P6. Two message texts. Contract paragraph, changelog fragment. Flip tests that used `person_email` as the "declines" example to `person_dob` | `_operator_registry.py`, `out_of_core/_faker_native.py`, `out_of_core/_compat.py`, `docs/compatibility-contract.md` (about lines 994-1012 and the deterministic paragraph), `changelog.d/faker-native-widen.md`, tests | source about 10, tests about 380 | FAKER-DEFAULT-POOL merged, and S0 merged (here or there) |
| S2 | Allow `synthetic_account_number`, `synthetic_member_id`, `synthetic_plan_id`. Proof cells come from the same parametrization; P7 adds the FK-key cell (these three declare `participates_in_fk_pk=True`) | `_operator_registry.py`, changelog, tests | source 3, tests about 80 | S1 |
| S3 (owner-gated, Q1) | Add registry provider `network_ipv4` (Faker `ipv4`, `poolable=True`) and allow it. Adds a Faker-backed provider, so it adds an `adapter` cell to the FAKER-MIGRATE output lock | `providers_v2/_real_registry.py`, `providers_v2/_faker_adapter.py` map, `_operator_registry.py`, the lock file and its generator run, `docs/compatibility-contract.md` provider list, tests | source about 8, tests about 40 | S2 and FAKER-MIGRATE S2 |

Existing tests whose assertion flips (behavior change, not weakening; each keeps its name and file, and the builder lists every flip in the report):

- `tests/native/test_operator_registry.py:55` (the allowlist value)
- `tests/native/test_operator_tables_snapshot.py:249` (asserts `C1_PROVIDER_ALLOWLIST` is the two-name set)
- `tests/parity/test_phase_d_faker_seq.py:178`, `:267` (`person_email` as the declining provider; switch to `person_dob`, which still declines)
- `tests/native/test_chunked_nondet_faker_admission.py`, `tests/physical/test_unified_slice_faker.py`, `tests/physical/test_shadow_bindings.py`, `tests/native/test_requirements.py`: any case that asserts a decline for an S1/S2 provider; find with `grep -rn "person_email\|person_name\|address_\|person_phone\|synthetic_member_id\|synthetic_plan_id\|synthetic_account_number" tests/native tests/physical tests/parity tests/unit/execution`
- `tests/unit/execution/_auto_chunk_strategies.py:227` if its provider is widened

Changed assertions in existing tests are a full-suite trigger (testing.md), so S1 runs T3 on the merge head. New public names: none.

### Order against FAKER-MIGRATE and FAKER-DEFAULT-POOL

1. FAKER-DEFAULT-POOL first. S1 edits the same admission modules and its value is in default configs (no `pool_size`), which only reach the native route after DEFAULT-POOL.
2. S1 and S2 do not depend on FAKER-MIGRATE. The native route only indexes into the Python-built pool, so it "moves exactly with the pool" (FAKER-MIGRATE 5.2, around its line 430). Every proof here compares two routes under the same installed Faker, and no test pins a Faker literal digest. Either merge order is safe. Recommended: S1 and S2 before FAKER-MIGRATE S2 (which starts on or after 2026-11-24), so the S2 full suite under Faker 40.54.0 also runs the widened native route. If MIGRATE S2 lands first, S1 rebases with no change.
3. S3 after FAKER-MIGRATE S2. It adds a Faker-backed provider, and FAKER-MIGRATE AT-L22 requires the output lock to name exactly the Faker-backed providers. Landing it after S2 captures its lock cell once, under 40.54.0, instead of twice.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_faker_native_widen.py` | `tests/parity/` | "Pipeline spine and routes": cross-route equality tests live in `tests/parity/` | `test_faker_default_pool.py`, `test_phase_d_faker_seq.py` |
| `test_faker_native_allowlist_total.py` | `tests/sentry/defects/` | "Sentry test" | `test_faker_pool_size_one_resolver.py` |
| `faker-native-widen.md` | `changelog.d/` | "Changelog fragments" | other fragments |

No new source module. The sentry gets a row in `scripts/dev/sentry_registry.toml`.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | no: no regex or whole-value validation added | n/a | n/a |
| 2 | Strict wire and stored types | no persisted model changes | n/a | n/a |
| 3 | No exception context | the two edited out-of-core messages stay value-free; no new raise | existing value-free sentries | n/a |
| 4 | Versioned read models | no reader changes | n/a | n/a |
| 5 | Normalized guard scanners | the totality sentry walks the live registry, not source text; shapes covered: Faker-bound, Mimesis-bound, stub-overridden registry | sentry seeded cases: a stub `pool_native` provider missing from both sets; an allowlist entry the registry does not know | remove the stub-registry case and add a missing provider (sentry must still go red through the live walk) |
| 6 | No reaching into private modules | tests import `OPERATORS` from `execution._operator_registry` as existing tests do; no new cross-package private import in source | review | n/a |
| 7 | No hidden CI failures | the Mimesis cells use `pytest.importorskip`; the gate runs them in a venv with the `mimesis` extra and checks they ran (`scripts/dev/junit_ran.py`), so a skip cannot pass as a run | gate evidence | run the gate without the extra: the ran-check fails |
| 8 | One input, one trust class per entry point | no new entry point | n/a | n/a |
| 9 | Mutations on the final head | named mutations below rerun after the last code change; head recorded | gate record | n/a |
| 10 | Allowlisted helpers still checked | the sentry's `EXCLUDED` map is an allowlist: each entry must name a live `pool_native` provider, and its stated reason must hold: `person_dob`'s built pool is not all strings; each `decoy_native` entry has `backend_type == "decoy_native"` | sentry asserts the reason per entry | add a Faker string provider such as `person_email` to `EXCLUDED` (red: neither reason holds) |
| 11 | No raised caps | no cap or allowlist of a guard grows in the same change as the guarded thing; the provider allowlist is the feature itself, not a guard allowlist; `EXCLUDED` starts at six entries and may not grow in this row | review | n/a |

### Harness defect classes (`docs/handoffs/DEFECT-CATALOG.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the two edited out-of-core messages | messages name the condition and the column, never a value or pool content | existing value-free message sentries | interpolate a pool value into the message (sentry red) |
| 2 | Cleanup missing on an exit path | out-of-core budget failure and the pool built before it | the measured check runs in the pre-scratch preparation pass; the pool built for the check is dropped on failure and never enters the cache | W1b | cache the pool before the budget check (W1b cache-size assertion red) |
| 3 | State and concurrency | the pool cache shared across chunks and columns | one identity from `resolve_faker_pool_identity` per column; different providers never share a cache key | P2 at 120k rows with two providers in one table | key the cache by namespace only (P2 two-provider cell red) |
| 4 | Route parity and silent fallback | six routes | one allowlist literal; parity proof per route | P2, P3, P4, totality sentry | drop a provider from the set (sentry and P2 red) |
| 5 | Referential integrity | synthetic ids are FK-capable | key columns stay off the native route | P7 | admit faker in the FK key gate (P7 red) |
| 6 | Untrusted producer | a custom provider under an allowed name returning non-strings | runtime `pool_values_are_strings` check, existing coded outcomes | P8 | disable the check (P8 red) |
| 7 | Check then use | N/A: admission reads the compiled plan and config, and the pool string check runs on the built pool that the kernel then uses | n/a | n/a | n/a |
| 8 | Weak tests | value equality alone misses a type change | P2 compares Arrow tables with schema plus the output hash | P2 | compare `to_pylist()` only (reviewer checks assertion form) |
| 9 | Refactor drift | tests that used `person_email` as the declining example | flip each to `person_dob`, keep names; builder lists every flip | flipped tests | n/a |
| 10 | Frozen contract drift | contract allowlist sentence; B1-B4 | contract text rewritten, Breaking fragment | docs review, P6, P9 | leave the old two-provider sentence (reviewer check) |

## 9. Acceptance tests (each fails before its slice unless marked)

All cells parametrize over `sorted(OPERATORS["faker"].provider_allowlist)` at test time.

- **P1 pool proof.** For each allowed provider: build the default pool (10,000, `en_US`) through `resolve_faker_pool_identity` and `PoolBuilder`; every value is a non-empty `str`; `pool_values_are_strings` is true. One extra cell per provider with locale `de_DE` (the runtime check is the guard for other locales; this cell proves a second locale end to end). Fail-before: none for the pool itself (unchanged-behavior control); the admission half is P2.
- **P2 route parity.** For each allowed provider, each of: deterministic with a namespace, and position-keyed; each of: no `pool_size`, `pool_size: 500`. Run 2,000 rows (unified slice) and 120,000 rows with a chunk size that forces three or more chunks (chunked native, string source). Assert the route evidence is `rust_pool_select` and the output equals the forced full-frame pandas run as an Arrow table (`equals`, schema included) and by output hash. Fail-before: the route is `pandas_oracle` full frame.
- **P3 typed sources.** For each allowed provider, deterministic on an `int64` source and position-keyed on a `float64` source at 120,000 rows: chunked oracle leg or native as today for first name, output equal to forced full frame. Fail-before: full frame.
- **P4 sequential and out-of-core.** A two-table FK job where the child has deterministic `faker(<provider>) in ns` on a string non-key column, one cell per provider: the sequential route reports the column native and the output equals forced full frame; the out-of-core route admits it with the same output. Fail-before: `faker_provider_not_native` and `out_of_core_faker_pool_unsupported`.
- **P5 Mimesis.** For the providers in `ADOPTED_MIMESIS_PROVIDERS ∩ allowlist`: (a) always-on cell with a stub adapter bound through `ProviderRegistry.override` under `backend_type="mimesis"`, `poolable=True`, returning strings: P2 at 2,000 and 120,000 rows; (b) real-Mimesis cell under `pytest.importorskip("mimesis")`: P1 and P2 with the real `MimesisAdapter`. Gate record for (b), exact commands: `~/bin/vm-run engine <worktree> 'uv venv /tmp/mim && . /tmp/mim/bin/activate && uv pip install -e ".[mimesis]" && python -m pytest tests/parity/test_faker_native_widen.py -k mimesis_real --junitxml=/tmp/mim-junit.xml; python scripts/dev/junit_ran.py /tmp/mim-junit.xml'`. The record pastes the install line's resolved `mimesis` version and the full `junit_ran.py` output, which must show the `mimesis_real` cells ran (not skipped). Fail-before: declined.
- **P6 degenerate types (marked byte change).** For one S1 provider: an empty table and an all-null string column with default `faker(...)`: the output column is Arrow `string` on unified slice and chunked. On full frame, a deterministic column over an all-null `int64` source is pinned to `string` (`execution/_faker_degenerate_pin.py:97`). Fail-before: `double` (empty), `null` (all-null).
- **P7 FK key (S2).** `synthetic_member_id` on an FK key column: declines exactly as `person_first_name` on a key column does today (the FK gate admits only `hash`). Unchanged-behavior control; must not fail before.
- **P8 non-string pool.** A custom provider registered under `person_email` that returns ints: the route-specific outcomes of FAKER-DEFAULT-POOL F5 hold (chunked preflight code, unified-slice reroute, full frame success). Fail-before: runs full frame and never reaches the preflight.
- **P9 templates.** (a) Each of the four CLI templates' faker column sets (read from `C:src/decoy/templates/*.yaml` copied as a fixture; these are position-keyed) at 120,000 rows on unified slice and chunked: every faker column reports `rust_pool_select`. On out-of-core the same columns still decline with `out_of_core_faker_pool_unsupported` and the job reroutes and succeeds. (b) A deterministic, namespaced copy of the HIPAA faker set (every faker column given `deterministic: true` and its own namespace, no `pool_size`) on the out-of-core route under the default budget: every column is admitted and the job succeeds. Fail-before: (a) pandas; (b) declines.
- **W1 measured reservation (S0).** (a) An out-of-core job with 12 deterministic default faker columns of distinct pool identities (the S1 providers plus first and last name in extra namespaces) under the default budget runs and succeeds, and the same job with 3 of them under a 100 MiB budget succeeds; `reserved_bytes` equals the sum of `estimate_pool_bytes` over the built pools. (b) A stub provider whose measured pool exceeds a 1 MiB budget fails with `out_of_core_faker_pool_budget_exceeded` before `ScratchArena.fresh`, the over-budget pool is not in the cache, and no scratch or output remains. Fail-before: (a) fails at the 7th pool (3rd under 100 MiB).
- **S1 sentry.** `test_faker_native_allowlist_total.py` passes and fails on its seeded cases.

Named mutations (record the head): remove `person_email` from the allowlist (sentry and P2 red); add `person_dob` to it (P1 red); return a non-string from the stub Mimesis adapter (P5a red at the string check); disable `pool_values_are_strings` in `_chunked_pools.py` (P8 red); drop the `EXCLUDED` reason check (class 10 seeded case red); restore the `pool_size * 4096` reservation (W1a red); walk only the faker and mimesis backends in the sentry (seeded `decoy_native` stub case red).

Performance evidence (performance.md): the audit probe for `gdpr` and `hipaa` template tables at 2,000 and 120,000 rows on the Dell node through `vm-run`, three runs each, before and after, wall time and peak RSS. Expected: 120,000-row tables move from full frame to chunked native. Numbers go in the PR body.

## 10. Frozen contracts and byte changes

Output values do not change on any route (P2). Named byte and behavior changes:

1. **B1.** A newly admitted column whose output is empty or all-null is typed Arrow `string` on unified slice and chunked (was `double` or `null` on pandas). Same ROUTE-OUTPUT-CONTRACT entry as first name.
2. **B2.** The full-frame deterministic pin (`_faker_degenerate_pin.py`) now pins the new providers over int/bool sources to `string` for an empty or all-null column.
3. **B3.** A custom non-string provider registered under a newly allowed name now fails on the chunked route with `chunked_faker_nondeterministic_pool_not_string` (it ran full frame before); unified slice still reroutes.
4. **B4.** The out-of-core pool reservation is the measured pool size, not `pool_size * 4096`. A job that fits today still fits; a job whose real pools exceed `min(run budget, 256 MiB)` fails before the run with `out_of_core_faker_pool_budget_exceeded` (W1b). Jobs that failed only because of the 4,096-byte reservation now run.

Fragment first line: `Breaking: person name, email, phone and address faker providers (and in S2 the synthetic account, member and plan ids) now run on the native and chunked routes; an empty or all-null output column is typed string, a non-string custom provider under one of these names fails on the chunked route, and the out-of-core pool budget counts measured pool bytes.`

Contract: rewrite the allowlist sentence at `docs/compatibility-contract.md:997-998` to name the set by reference to the operator registry, and keep the rest of the paragraph. `SEED_PROTOCOL_VERSION`, plan serialization and digests do not change.

## 11. Pre-mortem

- A provider's Faker method returns a non-`str` in some locale. The runtime check turns it into the existing coded outcome, never wrong output. P1's second-locale cell catches the common case.
- Building before reserving means a pathological provider allocates its pool before the check. The build is bounded by `pool_size` values (the stock `PoolBuilder` forces exactly that many) and `PoolCache` still refuses any single pool larger than the whole allowance. W1b covers the over-budget path.
- Mimesis is untested in default CI. P5a always runs; P5b runs at the gate with the extra installed and a ran-check.
- FAKER-MIGRATE S2 moves Faker output for some locale pairs. That moves pool contents on every route at once; P2 compares routes, so it stays green.

## 12. Owner questions

- **Q1 (S3).** Add a `network_ipv4` registry provider so the HIPAA, GDPR and CCPA ipv4 disguise rules can be expressed as a native `faker` column? It is a new catalog entry (a new provider name in the public provider list and in the Faker output lock). Recommendation: yes, after FAKER-MIGRATE S2, because it is the only disguise faker method with no provider.

## 13. Deferred (V2-LOG)

- **V2-LOG:** `person_dob` native: needs a typed (date32) pool take and a typed output contract.
- **V2-LOG:** a CI leg that installs the `mimesis` extra so P5b runs on every PR, not only at the gate.
