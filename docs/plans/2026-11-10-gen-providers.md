# GEN-PROVIDERS: generate columns from the masking provider registry, with coherent person and address records

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, code-review, testing,
architecture, feature-dev, cross-cutting-concerns, api-and-compatibility, exploration, reuse-first,
security, observability-and-resilience, documentation, verification, profiles/local-operations,
catalogs/recurring-defects

Revision 3 (2026-11-17). Re-anchored on engine `origin/main` at `8796ef69`. Revision 2 was the
Codex-fixed text that passed the 11-10 gate (Dennis round 2 GO, Codex GO); it was never committed,
so this revision starts from it. Changes since then: GEN-STRICT E2 (#465), GEN-TYPES (#467,
#501) and the one-seed-path fix (#582) are on main, so they are facts, not prerequisites; every
citation is refreshed; census item A9 (identifier locale scope, owner 2026-11-12) joins E1; the
instance-default locale check moves to the existing compile-side choke point
`check_faker_default_locale`; E1 moves the grouped dispatch out of `synthesize.py` to keep it under
600 lines; slices carry risk tiers, named mutations and a "Ratchets touched" line. Codex owes a
recheck of the deltas only (listed under "Revision 3 deltas").

Base inspected: engine `origin/main` at `8796ef69`. Roadmap row 24p (CLI repo `docs/ROADMAP.md:285`).
Requirements from the CLI record `docs/records/2026-11-08-generation-completeness-audit.md`. That
record has no numbered "Decisions" section. This plan reads "Decision 1" as its finding B1 (domain
identifiers are unreachable from generation) and "Decision 2" as B2 (coherent person and address
records). Census item A9 comes from `docs/records/2026-11-12-duplication-census/REMEDIATION.md:78`.
Engine only. CLI help picks up the new type and keys from `generate_option_catalog()`.

Risk: R2. The work adds a generate type, config keys and reason codes. It refactors how masking
builds composite generators, without changing behavior, and it changes the shared provider
registry. Required evidence is the reviewed plan, slice T0 and T1, independent T2 with the named
mutations, and the trigger-bound full suite per slice. The owner is the approver. Dennis and Codex
are the independent plan gates.

**Already on main (no longer prerequisites).**
- GEN-STRICT: the option registry `config/_generate_options.py` (`GENERATE_OPTIONS` at `:410`),
  `plan/checks/_generate_columns.py` with `check_generate_columns` (`:110`), its per-column
  `_check_column` (`:147`), the fixed-text `_refusal(code, table, column, key)` (`:77`), the faker
  view `_FakerView` (`:185`, unknown type refused at `:223`) and the run-time default-locale choke
  point `check_faker_default_locale` (`:516`), called by `generation/_streamed.py:361` and
  `generation/_window_admission.py:336` before any provider runs.
- GEN-TYPES: the `generation/kinds/` sub-package (`_constant`, `_lookup`, `_output_type`,
  `_parametric`), the `output_type` key gated by `OUTPUT_TYPE_KINDS`
  (`config/_generate_type_checks.py:120`), and the draw-site precedent of a generate kind mapped in
  `GEN_KIND_TO_SITE` (`execution/native/_determinism_protocol.py:102`).
- One seed path (#582): composite generators resolve seeds through
  `determinism.resolve_seed` and `seed_bytes_to_int(..., widths=COMPOSITE_SEED_WIDTHS)`
  (`determinism/_seeds.py:34`, `:58`), which accept 8- or 32-byte seeds. GEN-PROVIDERS passes
  32-byte family keys and so needs no seed converter of its own.
- The import-layer contract `.importlinter` exists (LAYOUT E3). `plan`, `generation` and
  `providers_v2` are siblings; `execution` is above them; `config` and `validators` are below.
- `generation/synthesize.py` is 593 lines. See Placement for how this plan stays under 600.
- Remote-owned GEN-INHERIT may also add a generate type; its proof-manifest increment is its own.

**A9: identifier locale scope (owner 2026-11-12, folded into this row).** All nine identifier
adapters declare `supported_locales=("en_US",)`. Four (`_ein.py:158`, `_ndc.py:94`, `_npi.py:89`,
`_ssn.py:110`) refuse another locale in `generate_random` with `provider.unsupported_locale`; five
(`_cusip.py:151`, `_iban.py:203`, `_icd10.py:88`, `_mrn.py:87`, `_pan.py:97`) ignore it. Generation
reads the declaration at compile, so a false declaration becomes a wrong refusal or a silent
acceptance. Resolution (E1 commit 1):
The owner chose the scope per provider on 2026-11-12 (go-recommended, recorded in CLI roadmap
#212): SSN, EIN, NPI and NDC `en_US` only; IBAN, PAN and ICD-10 locale-free; CUSIP `en_US` and
`en_CA`. MRN was not named; its kernel says it is locale-agnostic (`_mrn.py:95`), so it follows
the locale-free group.
- SSN, EIN, NPI and NDC keep `("en_US",)` and keep refusing.
- CUSIP declares `("en_CA", "en_US")` and refuses any other locale (it does not today).
- IBAN, PAN, ICD-10 and MRN, whose output does not depend on locale, declare every locale the
  engine accepts. That set already has one owner: Faker's `AVAILABLE_LOCALES`, which
  `_FakerView` validates against (`plan/checks/_generate_columns.py:230`). A new
  `providers_v2/identifiers/_locale.py` holds `ENGINE_LOCALES` (the sorted tuple of that set) and
  `require_locale(label, locale, supported)`. Each adapter's `capability_matrix` and its
  `generate_random` read the same module constant, so the declaration and the gate are one fact.
- No `CapabilityMatrix` field is added (the model is frozen, every field required, listed in
  `docs/frozen-surfaces.md:85`).
- Guard (AT-19): for every identifier in the live registry and two locales (`en_US`, `fr_FR`),
  `generate_random` either returns a value (locale declared) or raises `UNSUPPORTED_LOCALE`
  (locale not declared), never the other way round. For a declared non-`en_US` locale, the output
  with a fixed `rng` seed equals the `en_US` output, which proves the locale really has no effect.

**Guarantee.** A generate column can draw from any scalar provider that masking can use, by the
same name and through the same adapter and kernel code, plus the five fixed composites named
below. This covers the 9 `decoy_native` identifiers
(`synthetic_ssn`, `synthetic_ein`, `synthetic_npi`, `synthetic_ndc`, `synthetic_mrn`,
`synthetic_pan`, `synthetic_icd10`, `synthetic_iban`, `synthetic_cusip`) and the 19 Faker-bound
names. The composites `composite_person`, `composite_name_email`, `composite_city_state_zip`,
`composite_address` and `composite_provider` give coherent rows across several columns: the email
is built from the same row's first and last name, and the ZIP belongs to the same row's state.
`composite_person` can also emit `sex` (the first name is drawn from that sex's name list) and
`age` (whole years from the same row's date of birth). An unknown provider name fails at
`decoy validate` with a fixed-text code. Output is reproducible for a fixed config and seed unless
that column explicitly requests `determinism: fresh`.

**Non-goals:** a second provider table, list of names or copy of any kernel; `unique: true` on
provider columns (V2-LOG); per-provider options such as the MRN prefix or the email format
(V2-LOG); `composite_custom` in generation; the pinned route; streamed admission; locales beyond
each provider's declared `supported_locales`; any change to masking output bytes.

**Design notes.**
- One new generate type, `provider`, with keys `provider`, `locale`, `field` and `group`.
- Choke point: the shared registry `providers_v2.get_default_registry()`
  (`providers_v2/_registry.py:146`) is the only source of provider names, adapters and
  capabilities. The checks, the draw and the tests read it. Guard: AT-2 parametrizes over the live
  `known_providers()`, and AT-4 scans the new modules for kernel tokens and private imports.
  Mutation: replace the registry read with a fixed tuple, or construct `NpiAdapter()` directly.
- Open/closed: the draw path for each provider follows from its `CapabilityMatrix`
  (`backend_type`, `poolable`), never from a hand list. A new scalar masking provider with a known
  backend works in generation with no edit here. A new composite adds one descriptor because its
  output fields and factory are new facts.
- Parallel tables: the four lists of composite names (`_COMPOSITE_NAMES`,
  `_COMPOSITE_OUTPUT_COLUMNS`, the registry loop and the masking handler's if/elif chain) become
  one descriptor table that both masking and generation read. Guard: AT-13. Mutation: add a
  descriptor with no registry binding.
- Draw inventory: `provider` reuses the existing identifier, provider-pool and composite draw
  sites. `GEN_KIND_TO_SITE` points at the existing `gen.derive_context` substrate, the common
  generation entropy root for every branch. No second `DrawSite` or `DrawSiteProvider` describes
  the same underlying draws.
- Established pattern: GP2's generation pool bridge (`generation/_faker_pool.py`) and masking's
  `CompositeHandler`. Each new fact (provider names, slot names, seed labels) lives in one place.

Recurring-defect catalog check:
- "anchored validation": AT-2 applies provider format regexes with `re.fullmatch`, including a
  generated value plus a trailing newline as the refusal control.
- "strict wire and stored types": the option registry's existing `_str` check accepts only real
  strings for `provider`, `locale`, `field` and `group`; no coercion is added.
- "second registry": no provider list; the four composite name lists fold into one (AT-2, AT-13).
- "copied kernel": the generation modules call adapters and composite generators only (AT-4).
- "value in error text" and "no exception context": every refusal uses fixed text. Adapter errors
  are translated by a raise placed after the `except` block closes, so the new error has no
  `__cause__` or `__context__` (AT-5, AT-16).
- "route forgot the new branch": pinned refuses and streamed declines, both explicit (AT-9).
- "shared RNG stream": the null mask keeps its own `np` stream (AT-8).
- "option read outside the registry": `READER_FILES` gains the new modules (AT-17).
- "mutations on the final head": each slice reruns its named mutations after its last code change
  and records that head in T1 and T2 evidence.

## Why

The audit found that generation cannot produce a valid NPI, MRN, ICD-10 code, NDC, PAN, IBAN,
CUSIP, EIN or SSN, although masking ships kernels for all nine. A user who wants a synthetic
claims table has to pick "close enough" Faker methods with no check digits. It also found that
generated people are not coherent: `faker: first_name` and `faker: email` are drawn
independently, so `mary.smith@` sits beside "John Ortiz", and a ZIP has no link to its state.
Masking already solves both problems with the provider registry and the composite generators.
Generation should call that code, not grow its own.

## Behavior

### E1: scalar providers

Config shape:

```yaml
tables:
  - name: providers
    row_count: 1000
    generate_columns:
      - {name: npi, type: provider, provider: synthetic_npi}
      - {name: mrn, type: provider, provider: synthetic_mrn, null_probability: 0.05}
      - {name: phone, type: provider, provider: person_phone, locale: en_US}
```

1. **Type and keys.** `provider` joins the `GenerateColumnConfig.type` Literal and
   `GENERATE_TYPES` (`config/_tables.py:344`). Its `GENERATE_OPTIONS` entry
   (`config/_generate_options.py:410`) is `TypeOptions(keys={provider, locale, field, group},
   required={provider})`. All four are strings. In E1, a `field` or `group` refuses with
   `plan.generate_provider_field_unexpected`, because no E1 provider has slots. `COMMON_OPTIONS`
   (`:264`) apply unchanged. `unique` stays refused by `config/_generate_unique.py:56`, because
   `provider` is not in `UNIQUE_TYPES`.
2. **Validate and compile.** A new `plan/checks/_generate_providers.py` holds
   `check_provider_column(table, col)` and `check_provider_groups(table, columns)`. GEN-STRICT's
   `_check_column` calls the first. `check_generate_columns` calls the second once per table. In
   order:
   - `provider` not in `get_default_registry().known_providers()` refuses with
     `plan.generate_provider_unknown`. The name is not quoted.
   - `provider` is `composite_custom`, or its `backend_type` has no draw path (step 5), refuses
     with `plan.generate_provider_unsupported`.
   - A composite name without `field` refuses with `plan.generate_provider_field_required`. In
     E1 every composite refuses this way. E2 lifts it.
   - `locale` given and not in the provider's `CapabilityMatrix.supported_locales` refuses with
     `plan.generate_provider_locale_unsupported`.
   Each refusal is `_refusal(code, table, column, key)`, which carries the table, the column and
   the config key. It has no value text.
3. **Faker hint.** GEN-STRICT's `_FakerView.check` refuses an unknown `faker_type` with
   `plan.generate_faker_type_unknown`. When that unknown name is a registry name
   (`synthetic_npi`), E1 raises `plan.generate_faker_type_is_domain_provider` instead. Its fixed
   message says to use `type: provider`. The check is one membership test against
   `known_providers()` before the generic refusal.
4. **Seed.** The column root is `GenDeriveContext.for_column(derive_key, col, fallback_seed)`, as
   for every generate column. Its fingerprint is `strategy_config_fingerprint` over the config
   less `_EXCLUDED_FROM_FINGERPRINT`, and its identity is (table, column). The provider draw uses
   the column's `"faker"` family from `GEN_FAMILIES` (`generators/derivation.py:219`) as
   `K = gen_ctx.family_bytes("faker")` (32 bytes, `generators/derivation.py:330`). Why `faker`: a
   provider column is the registry-backed sibling of a faker column and draws from the same kind
   of value source. A column has one type, so no other draw on a provider column reads that
   family. The null mask keeps `base_int("np")` in `_apply_null_probability`
   (`generation/synthesize.py:539`) and does not share K. Pool paths take GP2's two existing
   labels, `family_bytes("faker_pool_build")[:8]` and `family_bytes("faker_pool_selection")[:8]`,
   exactly as `generation/_faker_pool.py:424` does. No new family label is added.
5. **Draw, by capability.** A new `generation/kinds/_provider.py` holds
   `provider_generate(col, n, gen_ctx, registry, locale)`. It reads
   `caps = registry.get_capabilities(p)` and picks one of three paths:
   - `backend_type` is `faker` or `mimesis` and `poolable`: masking's pool seam.
     `PoolBuilder(registry).build(p, size=DEFAULT_POOL_SIZE, job_seed=build_seed, locale=loc)`
     (`generation/pool/_builder.py:163`), then `PoolSampler().sample(pool, n, mode=REUSE,
     seed=selection_seed, deterministic=False)` (`generation/pool/_sampler.py:176`). This is
     GP2's pattern, through the registry instead of raw Faker reflection.
   - `backend_type` is `decoy_native` (the 9 identifiers, all `poolable=False`): per row
     `adapter.generate(p, spec=ProviderSpec(locale=loc, deterministic=True, namespace=ns, seed=K),
     source_value=i)`. The integer ordinal follows the shared length-prefixed integer
     canonicalization in `generation/pool/_canonicalize.py:45`. Inside the adapter this reaches the kernel's
     `derive_value(seed, namespace, canonical, domain=...)`, the same keyed draw masking uses (for
     example `providers_v2/identifiers/_npi.py:107`). The row ordinal is the source value, which
     is masking's positional pattern (`execution/_strategies/_faker_positional.py:52`). `ns` is
     the fixed string `gen-provider/<table>/<column>`. The unseeded `generate_batch`
     (`providers_v2/identifiers/_npi.py:141`) is never called, because it uses
     `np.random.default_rng()` with no seed.
   - `backend_type` is `faker` and not `poolable` (`uuid`, `lorem_text`, `random_int_range`,
     `random_choice`, `address_full`): `adapter.generate_batch(p,
     spec=ProviderSpec(locale=loc, deterministic=False, namespace=ns, seed=build_seed), count=n)`.
     The adapter ignores the namespace in this non-keyed path, but all three seed-envelope fields
     are explicit and no default can change the route. The seed creates a fresh Faker instance
     (`providers_v2/_faker_adapter.py:230`), so the batch is reproducible. It is sequential.
   Any other `backend_type` is refused at compile (step 2). That is the only closed branch.
6. **Locale.** The `locale` key, else the instance default locale passed to `_generate_column`,
   else `en_US`. Compile cannot see the instance default, so the existing run-time choke point
   `check_faker_default_locale` (`plan/checks/_generate_columns.py:516`) covers it: its column
   filter (`:539-545`) widens from `type == "faker"` to `faker` or `provider`, and a provider column
   with no `locale` is checked by the same `check_provider_column` in the effective locale. A
   miss refuses with `plan.generate_provider_locale_unsupported` before any provider runs, on both
   callers (`generation/_streamed.py:361`, `generation/_window_admission.py:336`). No second
   default-locale check is added.
7. **Run-time errors.** Before constructing an adapter, `provider_generate` rechecks the effective
   locale against the live capability matrix. This is the check-then-use guard for a registry
   override between the step-6 check and the draw, not the primary check. `ProviderError`, `CompositeError`, `IdentifierError` imported from the public
   `providers_v2.identifiers` package, `DeterminismError`, `PoolCapacityError` and the existing
   pool `GenerationError` raised inside the draw are caught at one site in `provider_generate`.
   The `except` block only records a flag. The new
   `GenerationError(code=runtime.generation_provider_failed)`, with fixed text naming the table and
   column, is raised after the block closes. `raise ... from None` is not enough: it clears
   `__cause__` but keeps `__context__`, and AT-5 and AT-16 require both to be `None`. Adapter
   messages can quote the provider name or a value, so they are never forwarded.
   Every provider-value draw path here is integer-only: HMAC-SHA256, integer modulo, Faker's integer-backed
   provider draws, numpy integer index draws, and date arithmetic for anchored dates and age.
   None uses libm or floating point, so the values and canonical Arrow bytes match across x86 and
   arm64. AT-3 commits a digest for every live scalar provider and every composite, rather than
   sampling one provider per backend, so a provider-specific float step turns the guard red.
   The shared null post-pass is not a provider-value draw. It keeps the existing PCG64
   `random(n) < null_probability` contract, which uses an exact IEEE conversion and no libm; AT-8
   pins its output on both T2 architectures.
8. **Dispatch.** `_generate_column` (`generation/synthesize.py:304`) gains one
   `elif kind == "provider":` branch (about 5 lines) that calls `provider_generate`. To pay for it,
   the same slice moves the grouped/windowed/group_key three-way dispatch (`:373-386`, a lazy import
   plus an inner if/elif) into one `grouped_windowed_values(kind, col, n, seed, generated, *,
   reference_date)` in `generation/_grouped_windowed_generators.py` (154 lines). That module
   already owns the three generators, so the dispatch joins its facts. The move saves about 10
   lines and changes no output; the existing grouped, windowed and group-key tests are the guard.
   `restore_declared` and `_apply_null_probability` then run on the result as for every type.
   `ProviderSpec` is always built with `deterministic` and `namespace` set explicitly on the
   keyed and composite paths, and with `seed` set on every path, so no adapter falls back to an
   unseeded draw.
   Memory: a table with a provider column runs on the legacy resident route (streamed declines,
   pinned refuses). Its memory grows with `n` and is bounded only by the run's row count and the
   existing generation budget, the same as `faker` today.
9. **Registries.**
   - `ADMISSION_MATRIX["provider"] = (False, ...)` (`generation/_admission.py:45`): streamed
     declines and the run falls back to resident.
   - `REJECTED_TYPES` (`generation/_pinned_compile.py:54`) gains `provider` with the new
     `plan.pinned_provider_unsupported`.
   - `READER_KEYS["provider"] = ()` (`generation/_numeric_typing.py:148`): it reads no column.
   - `compute_payload_bounds` (`generation/_bounds.py:181`): None (unbounded), as for `faker`.
     V2-LOG: per-provider width bounds.
   - `_reproducibility._direct_reason` (`generation/_reproducibility.py:70`): unchanged.
     `register_faker_provider_v2` overrides apply inside `FakerAdapter` the same way on every
     route, so there is no route-specific custom-provider reason to report.
10. **Draw sites.** `GEN_KIND_TO_SITE["provider"] = "gen.derive_context"`
    (`execution/native/_determinism_protocol.py:102`) uses the existing common generation root,
    whose entropy classification is `job_seed` rather than `mask_key`. The keyed scalar branch
    continues to consume `gen.identifier_deterministic`; the poolable branch uses `gen.pool_build_faker` plus
    `gen.pool_nondeterministic`; the non-poolable Faker branch uses `gen.pool_build_faker`; and the
    composite branch uses the existing composite sites. `PROVIDER_IDENTIFIER_SITES` (`:126`) and
    `tests/native/test_draw_site_providers_golden.py` are unchanged. The new generation modules
    contain no raw draw tokens, so the static draw scan in
    `tests/native/test_draw_site_inventory_coverage.py` needs no allowlist change. `_GEN_ONLY`
    (`execution/native/_capabilities.py:388`) gains a conservative python-only `provider` entry:
    not row-local, order-sensitive, global, needs global row identity, and output type not static.
    Its notes enumerate the mixed row-keyed and whole-column variants. This static row cannot
    accidentally admit a provider branch merely because one variant is partitionable. No new
    `DrawSite`, `DrawSiteProvider` or Rust kernel is added.
11. **Catalog and docs.** `generate_option_catalog()` (`config/_generate_option_catalog.py:103`) lists
    the new type, and the CLI's `decoy list generate-types` and `decoy explain generation` read it
    live (`src/decoy/cli/gen/_topic.py`), so the CLI needs no change. `docs/capability-matrix.md` and `docs/proof-manifest.json` are regenerated. The
    `surface["generate"] == 14` assertion (`tests/sentry/test_proof_manifest.py:69`) counts types,
    so it moves to 15. It is a count, not a ceiling. GEN-INHERIT (remote-owned) adds its own
    increment if it merges later.

### E2: composite groups

Config shape:

```yaml
tables:
  - name: people
    row_count: 1000
    generate_columns:
      - {name: first_name, type: provider, provider: composite_person, field: first_name}
      - {name: last_name,  type: provider, provider: composite_person, field: last_name}
      - {name: email,      type: provider, provider: composite_person, field: email}
      - {name: g_first,    type: provider, provider: composite_person, field: first_name, group: guardian}
      - {name: city,  type: provider, provider: composite_city_state_zip, field: city}
      - {name: state, type: provider, provider: composite_city_state_zip, field: state}
      - {name: zip,   type: provider, provider: composite_city_state_zip, field: zip}
```

1. **Factory table (behavior-preserving masking refactor).** The refactor is two commits.
   - Commit 1 adds `tests/unit/execution/test_composite_handler_digests.py` and nothing else. It
     runs each of the six masking composites through `CompositeHandler` on a fixed frame, in
     deterministic mode (a fixed `mask_key`) and in non-deterministic mode (a fixed `job_seed`, which the
     handler passes as `spec.seed` at `execution/_strategies/_composite.py:123`), converts the
     whole post-handler frame to Arrow, and records the existing F0 canonical fingerprint shape:
     ordered schema, row count, null-aware and type-tagged per-column values, and table digest
     (`tests/parity/_f0_canonical.py:78`). The digests are captured on the base commit and committed
     as constants. No byte golden for these composites exists today:
     `tests/integration/golden/test_execution_e2e.py` checks coherence, not bytes.
   - Commit 2 is the refactor. The digest test must pass unchanged.
   A new `generation/composite/_factory.py` holds `COMPOSITES: Mapping[str, CompositeDescriptor]`,
   exported from `generation/composite/__init__.py`. Callers import it from
   `decoy_engine.generation.composite`, never from `_factory`. Each descriptor has a factory, the
   canonical output columns and the optional output columns (empty until E3). Every factory has
   the one signature `(coherent_namespace, registry, provider_config) -> CompositeGenerator`.
   `CompositeDescriptor` also owns `variable_output: bool`, true only for `composite_custom`, so
   `_VARIABLE_OUTPUT_COMPOSITES` derives from the descriptor instead of preserving a second fact.
   Factories that do not need an argument ignore it (`composite_city_state_zip` takes no
   registry today). The `composite_custom` factory reads `provider_config["bundle"]`. The bundle
   shape check and its `ExecutionError(COMPOSITE_CUSTOM_BUNDLE_SHAPE)` stay in the handler
   (`execution/_strategies/_composite.py:85-111`), before the factory call, because `generation/`
   must not raise execution errors. These derive from the table:
   - `_COMPOSITE_NAMES` (`generation/composite/_generator.py:31`);
   - `_COMPOSITE_OUTPUT_COLUMNS` and `_VARIABLE_OUTPUT_COMPOSITES`
     (`generation/composite/_validate.py:47`, `:58`);
   - the registry's composite loop (`providers_v2/_registry.py:245`);
   - the `CompositeHandler` if/elif chain (`execution/_strategies/_composite.py:63`).
   - the masking-side name lists `execution/_column_access.py:270`, `validators/_leak_check.py:95`
     and the name constants in `validation/post/_checks/_composite_coherence.py:29`.
   The `.importlinter` layers contract decides the dependency split. `execution/_column_access.py`
   today imports the private `generation.composite._validate._COMPOSITE_OUTPUT_COLUMNS` inside
   `_fixed_outputs` (`:270`); it now reads `COMPOSITES` through the public
   `decoy_engine.generation.composite` API, because execution already imports that package in
   `execution/_strategies/_composite.py:21`. `validators/_leak_check.py` remains a leaf that imports
   only pyarrow and `validators._types`, so it keeps its literal composite set. AT-13 pins that
   literal to `set(COMPOSITES)`. The coherence check reads the public descriptors for names but
   keeps its per-composite checker functions, because each composite's rule differs. The guard
   asserts that every fixed `COMPOSITES` key other than `composite_custom` has a checker.
   The per-composite constructor arguments the handler passes today move into each descriptor's
   factory, so the generators masking builds are unchanged. The set guard asserts that the
   registry's composite names, the `COMPOSITES` keys and every list above are one set. The commit 1
   digest test stays byte-identical.
2. **Fields.** On a composite provider, `field` is required. It must be one of that descriptor's
   output columns, or else `plan.generate_provider_field_unknown`. On a scalar provider, `field`
   refuses with `plan.generate_provider_field_unexpected`. `group` defaults to the provider name.
3. **Groups.** Members are the provider columns of one table with the same (provider, group). In
   `check_provider_groups`:
   - locale declarations must be all omitted or the same explicit string. A mixture of omitted and
     explicit values refuses because compile cannot know the instance default. Any mismatch gives
     `plan.generate_provider_group_mismatch`;
   - all members must have the same effective `determinism` (`stable` by default), or else the same
     mismatch code;
   - each `field` appears at most once per group, or else
     `plan.generate_provider_field_duplicate`.
   A table can hold two people by giving two groups.
4. **Group seed.** The group root is `GenDeriveContext.for_column(derive_key, group_cfg,
   fallback_seed)`. `group_cfg` is `{name: "<provider-group:" + group + ">", type: provider,
   provider: p, locale: loc, determinism: det}` with the table set. `loc` is the group's common
   explicit locale, else the instance default, else `en_US`; `det` is the agreed effective
   determinism. Including `det` lets `GenDeriveContext.for_column` create an OS-entropy root for a
   `fresh` group, while stable groups keep their derived root. Members carry `field` and the group
   config does not, so its fingerprint differs from every member's. No real column can match its
   identity and fingerprint, because a composite column without `field` is refused. The bundle uses
   `K_g = group_ctx.family_bytes("faker")` and namespace `gen-provider/<table>/<group>`. Member
   order and member names do not reach the group seed, so reordering or renaming a member leaves
   the values the same.
5. **Draw.** `generation/kinds/_provider_group.py` calls `COMPOSITES[p].factory(...)` and then
   `generate_bundle(ProviderSpec(locale=loc, deterministic=True, namespace=ns_g, seed=K_g), n,
   source=pd.Series(range(n), dtype="int64"), deterministic=True)`. The row ordinal therefore uses
   the same integer canonicalization as the scalar identifier path. Masking's handler makes the
   same call shape with its real source. For `composite_person` that is one `derive` per row split into four index slots
   (`generation/composite/_person.py:203`), so combinations are near-unique, not capped at a
   10,000-tuple pool. The bundle is computed once per `(provider, group)` inside a table and held
   in a per-table `bundle_cache` dict keyed by that tuple. The table loop creates the cache and
   passes it to `_generate_column`. Including the provider prevents `composite_person` and
   `composite_address` groups that reuse the same group label from reading each other's bundle.
   The first member computes it. Each member takes its column from the bundle, then runs
   `restore_declared` and its own `_apply_null_probability`. So a member's nulls are independent
   of other members, as in masking.
6. **Run-time errors.** `CompositeError` follows E1 step 7. The `composite_custom` bundle-shape
   check is unreachable from generation, because generation refuses `composite_custom` at compile.
7. **Dispatch.** The `provider` branch passes `bundle_cache` when `field` is present (about 3
   more lines). The table loop in `_generate_tables_from_config` creates one dict per table (about
   2 lines). The pinned route never reaches here.

### E3: `sex` and `age` on `composite_person`

1. `CompositePerson` gains a constructor argument, `optional_fields: frozenset[str] =
   frozenset()`. Masking never passes it, so masking bytes and masking wiring
   (`composite_wiring_consistent`) do not change. The descriptor's optional columns for
   `composite_person` become `(age, sex)`. Generation passes the subset its group requests.
2. **sex.** When `sex` is requested, each row does a second derive on `coherent_namespace +
   "/ext"`. `generation/composite/_custom.py` has the same precedent for a fifth slot. The low bit
   of byte 0 picks `F` or `M`. The first name then comes from a female or male pool, indexed by the
   main latent's slot 0. The two pools come from two new registry entries,
   `person_first_name_female` and `person_first_name_male`. They map to Faker's
   `first_name_female` and `first_name_male` in `_FAKER_METHOD_MAP`
   (`providers_v2/_faker_adapter.py:43`, `person_first_name` at `:50`) and `_CATALOG`
   (`providers_v2/_real_registry.py:67`, `person_first_name` at `:74`).
   The registry grows from 34 to 36 names. The change is additive, and masking can use the new
   names too. The count pins that move in E3:
   - `tests/sentry/test_proof_manifest.py:70`;
   - `tests/unit/providers_v2/test_registry.py:44`;
   - `tests/unit/providers_v2/test_capability_matrix.py:19` (Faker-bound 19 to 21) and `:29`;
   - `tests/unit/providers_v2/mimesis/test_optional_dep.py:28` and `:92`;
   - the count docstrings in `providers_v2/_registry.py` and `faker_providers()`;
   - `docs/decisions/mimesis-adoption.md:51`.
   These are counts, not ceilings. The platform's provider picker reads `faker_providers()`, so it
   gains two entries. E3 adds both names to AT-2 and to AT-3's committed cross-architecture digest
   table. Faker 40.23.0 en_US has 13 names in both lists (for example Jordan, Taylor), so the name
   alone cannot fix the sex. Drawing sex first is the only coherent order.
3. **age.** When `age` is requested, it is computed per row from that row's `dob` to `DOB_ANCHOR`
   (`generation/_dob_anchor.py:28`), in whole years with the birthday rule. It is a pure function
   with no draw, and it never reads the wall clock. `dob` need not be emitted for `age` to work.
4. When neither field is requested, the person bundle is byte-identical to E2.

## Pre-mortem (failure modes)

| # | Failure | Where it would bite | Guard |
|---|---|---|---|
| P1 | A builder copies an identifier kernel or a Luhn helper into generation | two NPI implementations drift; masking fixes miss generation | AT-4 token and import scan on `generation/kinds/_provider*.py`; reuse inventory names the adapters |
| P2 | A hand list of "generatable" providers grows beside the registry | a new masking provider is silently missing from generation | AT-2 parametrizes over the live `known_providers()`; the branch choice reads the capability matrix |
| P3 | The identifier path calls the unseeded `generate_batch` | output changes every run | AT-3 two-run and two-process byte equality per identifier; mutant calls `generate_batch` |
| P4 | Unknown provider caught only at run | `decoy validate` passes a bad config | check in `check_generate_columns`, which validate calls; AT-5 runs `run_config_only_checks` |
| P5 | Adapter or pool error text, which can quote a value or the known list, reaches the user | provider or value text in a refusal | catch the typed errors, leave the `except` block, then raise the fixed-text `GenerationError`; AT-5 and AT-16 sentinel checks |
| P6 | The null mask draws from the provider stream, or the provider path advances `np` | null positions or values move when the other setting changes | K comes from `faker`, nulls from `np` base_int; AT-8 |
| P7 | Each composite member computes its own bundle, or two provider families collide on one group label | email does not match the name on the same row, or one family reads another family's bundle | one bundle per `(provider, group)` in the table-local `bundle_cache`; AT-10 and AT-11 mutants |
| P8 | The group seed depends on the first member's config or order | reordering columns changes people; mixed stable/fresh or omitted/explicit locale follows the first member | group root from the agreed provider, group, locale and determinism with no `field` or member name; AT-11 reorder and agreement cells |
| P9 | The factory refactor changes a masking constructor argument | masking output bytes change | commit 1 adds canonical Arrow fingerprints through `CompositeHandler`, captured on base for both modes; commit 2 refactors with them unchanged; AT-13 |
| P10 | `sex` is added to masking's canonical columns | masking wiring check refuses existing configs, or bytes change | optional columns are separate from canonical ones and masking never requests them; AT-14 masking golden cell |
| P11 | `age` reads `date.today()` | output changes daily | `DOB_ANCHOR` only; AT-15 mutant |
| P12 | Pinned or streamed silently half-supports `provider` | route divergence | explicit `REJECTED_TYPES` and `ADMISSION_MATRIX` entries; AT-9 |
| P13 | The new module reads a key not in the registry (for example `provider_options`) | silently ignored key | `READER_FILES` entry; AT-17 |
| P14 | `synthesize.py` (593 lines) crosses 600 | a module-size census entry would be needed | E1 moves the grouped dispatch out first (about -10), then adds the provider branch (about +5); E2 adds about 5; the module ends near 593; Placement rule |
| P15 | The identifier draw is too slow | large tables stall | floor of 20k rows/s per column at 100k rows, measured at T2; Dennis measured NPI 59k, IBAN 53k, MRN 70k and `composite_person` 26k rows/s per group on x86; a result below the floor is not a V1 blocker under the V1 bar; it opens the batch keyed path V2-LOG item and goes in the slice's gate notes |
| P17 | An identifier declares one locale scope and its `generate_random` enforces another (census A9) | generation refuses a valid IBAN column in a `fr_FR` table, or silently accepts a US-only identifier abroad | declaration and gate read one module constant through `require_locale`; AT-19 |
| P16 | A float or libm step enters any provider draw path | bytes differ between x86 and arm64 | integer-only paths stated in E1 step 7; AT-3 commits every live provider and composite digest and runs them on the Mac (arm64) and a Linux VM at T2 |

## Acceptance tests

| AT | What | Red on base / mutant |
|---|---|---|
| AT-1 | `provider` is in `GENERATE_TYPES`, the option catalog, `ADMISSION_MATRIX` (declined), `REJECTED_TYPES`, `READER_KEYS`, `GEN_KIND_TO_SITE`, `_GEN_ONLY`, the capability matrix and the proof manifest | red on base |
| AT-2 | For every name in the live `known_providers()` except composites, a 1,000-row column generates with no nulls. Each value passes that provider's `format_regex` via `re.fullmatch` and its `blocklist_validators` from the `CapabilityMatrix` (NPI and PAN Luhn, IBAN mod 97, CUSIP check digit, SSN blocklist). Appending a newline to a regex-checked value is refused | red on base; mutants: skip `decoy_native` in the branch choice; replace the registry read with a fixed tuple missing one name; use `re.match` |
| AT-3 | Determinism: the same config and seed in two runs, and in two subprocesses with different `PYTHONHASHSEED`, give identical canonical Arrow fingerprints for every live scalar registry provider and every supported composite. A different seed changes each draw-bearing output. Adding an unrelated column does not change it. Committed SHA-256 constants pin every provider, including all keyed identifiers, every Faker pool and seeded-batch method, and every composite. T2 runs the full digest table on the Mac (arm64) and on a Linux VM. This is the cross-arch guard for every provider-specific draw path, not one sample per backend | red on base; mutants: identifier path calls `generate_batch`; add a float step to one provider path; seed a Faker batch from a different family |
| AT-4 | AST-based reuse sentry: after normalizing import aliases and qualified calls, `generation/kinds/_provider.py` and `_provider_group.py` contain none of `derive`, `derive_value`, `default_rng`, `Faker` or `seed_instance`. They import no concrete identifier adapter and no private identifier or composite module. The only identifier-package import allowed is public `IdentifierError`; adapters come only from `get_default_registry()` and generators only from public `COMPOSITES`. The existing static draw scan stays green with an unchanged allowlist | mutants: alias and call `derive_value`; construct `NpiAdapter()` directly; import `providers_v2.identifiers._errors` |
| AT-5 | `provider: not_a_provider` refuses at `run_config_only_checks` and at `compile_plan` with `plan.generate_provider_unknown`, located by table, column and key. A sentinel provider name is absent from `str(exc)`, the log and the exception chain; `__cause__` and `__context__` are `None` | red on base; mutant: let the registry `ProviderError` propagate |
| AT-6 | `type: faker, faker_type: synthetic_npi` refuses with `plan.generate_faker_type_is_domain_provider`; `faker_type: not_real` still gives `plan.generate_faker_type_unknown` | red on base; mutant: drop the membership test |
| AT-7 | `locale: fr_FR` on a provider that declares only `en_US` (`synthetic_npi`) refuses with `plan.generate_provider_locale_unsupported`; `en_US` passes; `locale: fr_FR` on `synthetic_iban` passes (A9). `synthetic_cusip` passes at compile with `locale: en_CA` and with `locale: en_US`, and refuses `locale: fr_FR` with the same plan code. With no `locale` and an instance default of `fr_FR`, `run_generation` and the window admission both refuse through `check_faker_default_locale` with the same plan code before any draw; with an instance default of `en_CA`, a `synthetic_cusip` column passes that check | red on base; mutants: skip the locale check; leave the `check_faker_default_locale` filter at `faker` only; declare `_cusip.py` as `("en_US",)` (the `en_CA` cells go red) |
| AT-8 | With `null_probability: 0.3`, null positions are the ones `_apply_null_probability` picks from the column's `np` base seed, and the non-null values equal the same column's values at `null_probability: 0` with the same fingerprint inputs. Its committed digest runs on both T2 architectures | mutant: seed the null mask from `family_bytes("faker")` |
| AT-9 | Pinned compile refuses with `plan.pinned_provider_unsupported`. Streamed admission declines, and the fallback output equals the direct resident output. A `reference` child of a provider column draws only parent values | red on base; mutant: admit streamed |
| AT-10 | E2 coherence at 10,000 rows. `composite_person`: every email's local part is built from that row's first and last name under the default format. `composite_city_state_zip` and `composite_address`: every (city, state, zip) is a row of the locality table. `composite_provider`: every `npi` passes Luhn | red on base; mutant: compute a separate bundle per member |
| AT-11 | Two `composite_person` groups in one table give different people. Members of one group agree row for row. Reordering the members, renaming a member, or adding an unrelated column does not change any value. Two tables with the same group name do not share a bundle. In one table, a `composite_person` and a `composite_address` may use the same explicit group label and still receive distinct, correctly shaped bundles. A stable group repeats across runs; an all-fresh group is coherent within one run and changes across runs | mutants: derive the group root from the first member's config; create the cache once per run; key the table-local cache by group alone; omit `determinism` from `group_cfg` |
| AT-12 | E2 refusals, each with its code, location and no value text: composite without `field`; `field` on a scalar; unknown `field`; duplicate `field` in a group; conflicting explicit locales; mixed omitted and explicit locale; mixed stable and fresh determinism; `composite_custom` | red on base for the E2 codes |
| AT-13 | Commit 1's `CompositeHandler` canonical Arrow fingerprint test (six composites, deterministic and non-deterministic, constants captured on base) passes unchanged after commit 2. The `composite_custom` malformed-bundle cell still raises `ExecutionError(COMPOSITE_CUSTOM_BUNDLE_SHAPE)` from the handler. Set guard: the registry's composite names, `COMPOSITES` keys, `_COMPOSITE_NAMES`, `_COMPOSITE_OUTPUT_COLUMNS` keys, the direct `COMPOSITES` consumer in `execution/_column_access.py`, and the literal at `validators/_leak_check.py:95` are one set; `_VARIABLE_OUTPUT_COMPOSITES` derives from `descriptor.variable_output`; every fixed key except `composite_custom` has a coherence checker | mutants: change one constructor argument in the factory (digest red); add a descriptor without a registry binding (set guard red); alter the leak-check literal; move the bundle-shape check into the factory |
| AT-14 | E3 at 20,000 rows: every `F` row's first name is in Faker's `first_names_female`, every `M` row's in `first_names_male`. Each sex is between 45% and 55% of rows. With no optional field requested, masking and E2 person bundles are byte-identical | red on base; mutants: draw the first name from the unisex pool; put `sex` in the canonical columns |
| AT-15 | E3 `age` equals whole years from `dob` to `DOB_ANCHOR` on every row. Direct cells cover a birthday on the anchor day, the day after, and 29 February | red on base; mutants: use `date.today()`; drop the birthday rule |
| AT-16 | A monkeypatched adapter or pool that raises `ProviderError`, `CompositeError`, `IdentifierError`, `DeterminismError`, `PoolCapacityError` or the existing pool `GenerationError` with a sentinel message gives fixed-text `GenerationError` with `runtime.generation_provider_failed`. The sentinel is absent from `str(exc)` and the log, and the exception chain is empty. A registry override that removes a name, or replaces a capability with one that drops the locale, between the step-6 check and the draw gives the same code | red on base; mutants: `raise ... from exc`; `raise ... from None` inside the `except` block (keeps `__context__`); omit the pool errors; omit the runtime locale check |
| AT-17 | `tests/sentry/defects/test_generate_option_reads.py` `READER_FILES` lists the new modules and passes | mutant: read `provider_options` in `_provider.py`; the sentry goes red |
| AT-18 | `tests/native/test_draw_site_inventory_coverage.py` passes with `provider` mapped to existing `gen.derive_context`, so its static key source is generation rather than `mask_key`. The provider capability row stays conservative for the mixed branches. The providers golden and draw-site count are unchanged because no draw primitive was added | mutants: map to `gen.identifier_deterministic`; mark the capability row-local; add a duplicate provider draw site |
| AT-19 | A9 declarations. The locale cells are derived, not listed: for each identifier in the live registry, the cells are every locale in its `CapabilityMatrix.supported_locales` plus one undeclared probe (`fr_FR` when undeclared; for `ENGINE_LOCALES` providers, a well-formed name outside `AVAILABLE_LOCALES`, `xx_XX`). For every declared locale, `generate_random` returns a value, and the value from `default_rng(7)` equals the `en_US` value from `default_rng(7)`: every identifier kernel ignores locale inside its declared scope, CUSIP included (`_cusip.py:151` draws the body without reading `locale`), so equality is the right check for all nine. For the undeclared probe it raises `ProviderError(UNSUPPORTED_LOCALE)`. A fixed pin also checks the owner's scope: SSN, EIN, NPI and NDC declare exactly `("en_US",)`; CUSIP exactly `("en_CA", "en_US")`; IBAN, PAN, ICD-10 and MRN exactly `ENGINE_LOCALES` | red on base (five accept `fr_FR` while declaring only `en_US`; CUSIP does not declare `en_CA`); mutants: drop the `require_locale` call in `_ein.py`; declare `_mrn.py` as `("en_US",)`; hand-copy a shorter locale tuple into `_iban.py`; remove `en_CA` from `_cusip.py`'s declaration (the scope pin goes red); keep `en_CA` declared but have `_cusip.py`'s gate refuse it (the derived `en_CA` cell goes red) |

## Class table

| # | Class | Where it can bite here | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|---|
| 1 | Wrong value | Identifier with a bad check digit; email not matching the row's name; ZIP outside its state; age off by one; a locale declaration that disagrees with the adapter | Values come only from masking's adapters and composites; one bundle per group; age is a pure function of `dob`; one locale constant per identifier | AT-2, AT-10, AT-14, AT-15, AT-19 | per-member bundle; drop the birthday rule |
| 2 | Cleanup | Bundle cache kept across tables or runs | `bundle_cache` is created per table in the table loop and dropped with it; no files or handles | AT-11 two-table cell | create the cache once per run |
| 3 | State | Shared mutable state: the singleton registry, the person pool cache, the RNG streams | The registry is read-only here; each group builds a fresh generator; K and the null `np` stream are separate HMAC families | AT-3, AT-8 | seed nulls from K; reuse one generator across groups |
| 4 | Route divergence | Pinned or streamed half-supports the type; validate and compile check differently | Explicit pinned refusal and streamed decline; one check module that validate and compile both call | AT-5, AT-9 | admit streamed; check only at compile |
| 5 | Referential integrity | A `reference` to a provider column assumes unique parent values | `unique` stays refused on `provider`; a reference child draws from parent values as for any parent; GEN-REL's uniqueness rule still applies where it is required | AT-9 reference-child cell | allow `unique: true` without a unique draw |
| 6 | Untrusted input | Provider names and adapter messages reach refusal text or logs | Fixed-text `_refusal`; one translation site that raises after the `except` block | AT-5, AT-16 | forward the adapter message; `raise ... from None` inside the block |
| 7 | TOCTOU / check-then-use | Registry checked at compile, changed by `override` or a custom provider before the run | The run reads the same singleton; a missing name at run is caught and translated, not trusted from compile | AT-16 override cell | skip the run-time catch |
| 8 | Weak test | Coherence or format checked on a few rows | AT-2 runs every provider at 1,000 rows; AT-10 and AT-14 check every row at 10,000 and 20,000 | the mutation column | each listed mutation |
| 9 | Refactor drift | The composite factory refactor changes masking generators | E2 commit 1 captures the canonical composite digest table on the pre-refactor code; commit 2 must pass that exact test unchanged; guard test on the name sets | AT-13 | change one constructor argument in the factory |
| 10 | Frozen contract | Type Literal, option catalog, reason registry, provider registry names, draw-site catalogue | All additive: one type, four keys, new codes, two new registry names and one mapping to an existing draw site; masking bytes unchanged | AT-1, AT-13, AT-14, reason manifest sentry | rename a code; drop a manifest entry |

## Established solutions and reuse inventory

Search run: the engine tree (`git grep` on `origin/main` for provider, composite, pool and seed
code), the masking strategy handlers, GP2's pool bridge, and the GEN-STRICT, GEN-TYPES and
GEN-INHERIT plans. External patterns: Synthea's person module (one latent person record from
which name, sex, birth date and address are drawn together) and SDV's `FixedCombinations`
constraint (columns that must co-occur are drawn as one tuple). Both match the composite design
masking already ships. Check digits follow their issuing standards (Luhn for NPI and PAN, ISO 13616
mod 97 for IBAN, the CUSIP check digit), which the kernels already implement. No custom kernel is
needed. The only new code is wiring and one pure age function.

| Need | Reused | Source |
|---|---|---|
| provider names and capabilities | `get_default_registry()`, `known_providers`, `get_capabilities`, `get_adapter` | `providers_v2/_registry.py:146`, `:87` |
| identifier kernels | the 9 `decoy_native` adapters' `generate(deterministic=True)` | `providers_v2/identifiers/_npi.py:107` and siblings |
| Faker-bound values | `FakerAdapter` and `_FAKER_METHOD_MAP` | `providers_v2/_faker_adapter.py:87`, `:43` |
| pool build and sampling | `PoolBuilder.build`, `PoolSampler.sample`, `DEFAULT_POOL_SIZE` | `generation/pool/_builder.py:163`, `generation/pool/_sampler.py:176` |
| pool seed labels | GP2 `faker_pool_build` and `faker_pool_selection` | `generation/_faker_pool.py:424` |
| positional keying | row ordinal as the derive source | `execution/_strategies/_faker_positional.py:52` |
| composite generators | `generate_bundle(deterministic=True)` on each composite | `generation/composite/_person.py:223` and siblings |
| fifth-slot precedent | second derive on `coherent_namespace + "/ext"` | `generation/composite/_custom.py` docstring |
| column seed | `GenDeriveContext.for_column`, `family_bytes` | `generators/derivation.py:271`, `:330` |
| option registry and catalog | `GENERATE_OPTIONS`, `TypeOptions`, `generate_option_catalog` | `config/_generate_options.py:410`, `config/_generate_option_catalog.py:103` |
| check entry and fixed-text refusal | `check_generate_columns`, `_check_column`, `_refusal` | `plan/checks/_generate_columns.py:110`, `:147`, `:77` |
| run-time coded refusal | `GenerationError` and the runtime reason registry | `generation/pool/_errors.py`; `reasons/runtime/_part3.py` |
| date of birth anchor | `DOB_ANCHOR` | `generation/_dob_anchor.py:28` |
| established method | one latent per entity, columns drawn as one tuple | Synthea `Person` generation; SDV `FixedCombinations` |

## Enumerations

### Exit paths

- Config refusals from the option registry: a missing `provider` uses GEN-STRICT E1's required-key
  code; an unknown key or a wrong type uses its existing codes (`config/_generate_options.py:410`).
- `generate_unique_unsupported` for `unique: true` (`config/_generate_unique.py:56`).
- Plan refusals from `plan/checks/_generate_providers.py`, at validate and compile:
  `generate_provider_unknown`, `generate_provider_unsupported`, `generate_provider_field_required`,
  `generate_provider_field_unexpected`, `generate_provider_locale_unsupported`, the hint
  `generate_faker_type_is_domain_provider`, and in E2 `generate_provider_field_unknown`,
  `generate_provider_field_duplicate` and `generate_provider_group_mismatch`.
- Pinned compile refusal `plan.pinned_provider_unsupported` (`generation/_pinned_compile.py:54`).
- Streamed admission declines, so the run falls back to resident (`generation/_admission.py:45`).
- Run-time `runtime.generation_provider_failed` from the one translation site.

### Routes

- Resident: `_generate_column` (`generation/synthesize.py:304`), a new `provider` branch beside
  `faker` at `:340`.
- Pinned: refused at compile; never runs.
- Streamed: declined by `ADMISSION_MATRIX`; runs resident.
- Validate (`decoy validate`): `run_config_only_checks` through `check_generate_columns`.

### FK shapes

- A `reference` column whose parent column is `type: provider`: reads the generated values like
  any parent. Values can repeat, because `unique` is refused (V2-LOG).
- A provider column as an FK child: N/A because provider draws read no other table or column
  (`READER_KEYS["provider"] = ()`).

### Fields

- `provider` (required string, a registry name), `locale` (optional string), `field` (E2, a slot
  of the composite), `group` (E2, default the provider name).
- Common options: `null_probability`, `determinism`. `determinism` is excluded from the
  fingerprint but still acts: `determinism: fresh` gives the column an `os.urandom` root
  (`generators/derivation.py:292`), so that column is not reproducible, as for every type.
- Composite slots: `composite_person` `dob, email, first_name, last_name`, plus E3 `age, sex`;
  `composite_name_email` `email, first_name, last_name`; `composite_city_state_zip`
  `city, state, zip`; `composite_address` `city, state, street_address, zip`;
  `composite_provider` `npi, practice_address, provider_name`.

### Output surfaces

- Generated tables (CSV, Parquet, fixed width, `decoy.mask()` generate path): the provider values.
- Refusals: value-free `PlanCompileError` and `GenerationError` with the codes above.
- `generate_option_catalog()` and the JSON schema: the new type and keys.
- `docs/capability-matrix.md` and `docs/proof-manifest.json` (regenerated).
- Draw-site kind map: one mapping to existing `gen.derive_context`; the catalogue and
  providers golden do not change.
- The provider registry `known_providers()`: E3 adds two names, which masking can use too.

## Frozen contracts

| Contract | Change | Kind |
|---|---|---|
| `GenerateColumnConfig.type` Literal and `GENERATE_TYPES` | + `provider` | additive |
| Option registry and catalog | + `provider` entry with four keys | additive |
| Reason registry | E1: 7 plan codes and 1 runtime code; E2: 3 plan codes; E3: none. Next minor per slice at merge | additive |
| Provider registry names | E3: + `person_first_name_female`, `person_first_name_male` (34 to 36; the count pins listed in E3 step 2 move; the platform picker gains two entries) | additive |
| Draw-site kind map | + `provider` mapped to existing `gen.derive_context`; catalogue and `PROVIDER_IDENTIFIER_SITES` unchanged | additive mapping only |
| Masking composite output | unchanged bytes, pinned by the new digest test (AT-13, AT-14) | none |
| `composite_person` canonical columns and masking wiring | unchanged; `age` and `sex` are optional columns only | none |
| Identifier `CapabilityMatrix.supported_locales` values | E1: MRN, IBAN, ICD-10 and PAN widen from `("en_US",)` to `ENGINE_LOCALES`; CUSIP widens to `("en_CA", "en_US")` and starts refusing other locales in `generate_random`; SSN, EIN, NPI and NDC unchanged; no field added | additive, except CUSIP's new refusal of non-North-American locales (owner scope) |
| Root `decoy_engine/__init__.py` | no new export | none |

## Placement

Checked against `CODEMAP.md` "Where Things Go" rows: Config models, Plan compile and checks
(`plan/checks/`), Generation (by concern, sub-packages), Providers (`providers_v2/`, registry in
`_registry.py`), Native companion bridge (protocol modules in `execution/native/protocol/`),
Masking strategy handler, Reason codes, Sentry test, Unit tests, Plans, Changelog fragments.

| Change | File | CODEMAP row | Existing neighbor |
|---|---|---|---|
| type Literal | `config/_tables.py` | Config models | `GENERATE_TYPES` |
| `provider` options | `config/_generate_options.py` (548 lines; one `TypeOptions` entry) | Config models | `faker` entry |
| provider checks | new `plan/checks/_generate_providers.py` | Plan compile and checks | GEN-STRICT's `_generate_columns.py` |
| faker hint and default-locale filter | `plan/checks/_generate_columns.py` (545 lines) `_FakerView.check` (+ 3 lines) and `check_faker_default_locale` (+ about 4 lines) | Plan compile and checks | the unknown-type refusal |
| identifier locale scope | new `providers_v2/identifiers/_locale.py`; the nine identifier modules each read it (E1 commit 1) | Providers | `identifiers/_errors.py`, `_validate.py` |
| grouped dispatch move | `generation/_grouped_windowed_generators.py` (154 lines) gains `grouped_windowed_values` (E1) | Generation | the three generators it dispatches |
| scalar draw | new `generation/kinds/_provider.py` | Generation (kinds sub-package) | GEN-TYPES' `_constant.py`, `_parametric.py` |
| group draw and bundle cache | new `generation/kinds/_provider_group.py` (E2) | Generation (kinds sub-package) | `_provider.py` |
| dispatch | `generation/synthesize.py` (593 lines; net change about 0 after the move) | Generation | the `faker` branch |
| composite factory | new `generation/composite/_factory.py`, exported as `COMPOSITES` from `generation/composite/__init__.py` (E2) | Generation (composite sub-package) | `_generator.py`, `_validate.py` |
| composite digest test | new `tests/unit/execution/test_composite_handler_digests.py` (E2 commit 1) | Unit tests | `CompositeHandler` tests |
| optional person fields | `generation/composite/_person.py` (E3) | Generation (composite sub-package) | `_generate_deterministic` |
| two registry names | `providers_v2/_faker_adapter.py`, `providers_v2/_real_registry.py` (E3) | Providers | `person_first_name` |
| masking handler reads the factory | `execution/_strategies/_composite.py` (E2) | Masking strategy handler | the if/elif chain it replaces |
| registries | `_admission.py`, `_pinned_compile.py`, `_numeric_typing.py`, `_bounds.py` | Generation | one entry each |
| draw-site mapping and capability | `execution/native/_determinism_protocol.py`, `execution/native/_capabilities.py` | Native companion bridge | existing `gen.derive_context`; no new draw-site module or provider |
| reason codes | `reasons/plan/_part3.py` (227 lines), `reasons/runtime/_part3.py` (402 lines) | Reason codes | GEN-STRICT codes |
| sentries | `tests/sentry/defects/test_generate_option_reads.py` (`READER_FILES`), new `tests/sentry/defects/test_provider_reuse.py` (AT-4) | Sentry test | the option-read sentry |
| tests | `tests/unit/generation/kinds/test_provider.py`, `test_provider_group.py`, `tests/unit/generation/composite/test_factory.py`, `tests/unit/plan/test_generate_providers.py` | Unit tests | GEN-STRICT tests |

Module counts: `generation/` gains no direct module; the two new ones are in `generation/kinds/`
(four modules today). `plan/checks/` gains one module, `providers_v2/identifiers/` one. No root
export. `synthesize.py` stays under 600 through the E1 move; if a later merge pushes it near 600
before E2, the E2 bundle-cache creation moves into a helper in `kinds/_provider_group.py`, leaving
one call line. No census entry is added and no ceiling moves.

## Slices

| Slice | Tier | Branch | Size | Content | Gate |
|---|---|---|---|---|---|
| E1 | R2 (Dennis then Codex): new user-facing type, reason codes, value-free error boundary | `feat/gen-providers-e1` | M (about 360 lines plus tests) | commit 1: A9, `identifiers/_locale.py` and the nine adapters (AT-19); commit 2: type, option entry, `plan/checks/_generate_providers.py` scalar checks, faker hint, the widened `check_faker_default_locale` filter, `kinds/_provider.py` with the three backend paths and the error translation, the grouped-dispatch move, dispatch, registries, existing draw-site mapping, 8 reason codes, capability matrix and proof manifest regeneration; AT-1 to AT-9, AT-16 to AT-19 | full suite (reason manifest changes); T1 impact set and T2 on the exact head |
| E2 | R2 (Dennis then Codex): behavior-preserving refactor of masking's composite handler | `feat/gen-providers-e2` | M (about 320 lines plus tests) | commit 1: `CompositeHandler` canonical Arrow fingerprints captured on base; commit 2: composite factory refactor and the public `COMPOSITES` read in `execution/_column_access.py`; then `field` and `group`, group checks, `kinds/_provider_group.py`, tuple-keyed bundle cache, 3 reason codes and generation-composite digest constants; AT-3, AT-10 to AT-13 | full suite (reason manifest and masking handler); T1 and T2 on the exact head |
| E3 | R2 (Dennis then Codex): changes the shared provider registry that masking reads | `feat/gen-providers-e3` | S (about 150 lines plus tests) | `optional_fields` on `CompositePerson`, `sex` and `age`, two registry names and their digest constants, the count pins; AT-2, AT-3, AT-14, AT-15 | full suite (shared registry); T1 and T2 on the exact head |

Named mutations per slice (each run on the slice's final head and recorded with that head):
- E1: replace the registry read with a fixed tuple missing one name (AT-2); call `generate_batch`
  on the identifier path (AT-3); construct `NpiAdapter()` directly (AT-4); `raise ... from None`
  inside the `except` block (AT-16); leave the `check_faker_default_locale` filter at `faker` only
  (AT-7); drop the `require_locale` call in `_ein.py` (AT-19); remove or refuse CUSIP `en_CA`
  (AT-7, AT-19); map `provider` to
  `gen.identifier_deterministic` (AT-18).
- E2: change one constructor argument in a composite factory (AT-13 digest); key the bundle cache
  by group alone (AT-11); compute a bundle per member (AT-10); omit `determinism` from
  `group_cfg` (AT-11); add a descriptor with no registry binding (AT-13 set guard).
- E3: draw the first name from the unisex pool (AT-14); put `sex` in the canonical columns
  (AT-14); use `date.today()` for `age` (AT-15); drop the birthday rule (AT-15).

Ratchets touched: the reason-code manifest (additive, next minor per slice at merge); the proof
manifest generate count 14 to 15 (E1) and provider count 34 to 36 (E3), both counts, not
ceilings; `READER_FILES` in `tests/sentry/defects/test_generate_option_reads.py:33` gains the new
modules (a coverage list, it grows); the secret-material census
(`tests/sentry/secret_material_census.json`, derived by `scripts/secret_material_census.py`) gets
an entry for each new seed- or key-named binding in `kinds/_provider*.py`. The builder regenerates
with `--write` and picks a verdict that the sentry accepts, following the existing
`generation/_faker_pool.py` rows for pool seeds; `K` and `K_g` are 32-byte HMAC outputs of the
column root, never the mask key, so the expected verdict is `not-secret` with that reason, or
`unbound` if they are consumed inline; the module-size census
is not touched (`synthesize.py` stays under 600); the draw-site catalogue, providers golden and
the static draw-scan allowlist do not change; `.importlinter` does not change (the new imports
follow the existing layers, and `execution/_column_access.py` loses one private import).

Order: E1, then E2, then E3. Each slice takes the next registry minor at merge and adds
`changelog.d/gen-providers-e<N>.md` with the heading `### Added (GEN-PROVIDERS, E<N>, <date>)`,
checked by `scripts/dev/check_fragment.py`.

## Engineering calls made

- A new type `provider`, not new `faker_type` values. One key then names one registry, and the
  masking spelling (`provider: synthetic_npi`) carries over unchanged (Owner question 1).
- The branch choice comes from `CapabilityMatrix.backend_type` and `poolable`. `classify_provider`
  (`execution/native/_provider_class.py:68`) is not imported. It serves the native companion's
  routing and lives in the execution layer.
- The seed is the column's existing `faker` family plus GP2's two pool labels. No new family is
  added, so `GEN_FAMILIES` does not change.
- Composite members are separate generate columns tied by `field` and `group`. This matches how
  masking binds a composite with `coherent_with` and needs no nested config shape.
- Member nulls are independent per column, as in masking.
- `sex` values are `F` and `M`, the two lists Faker ships. Other labels are V2-LOG.
- `random_choice` and `random_int_range` generate with their registry defaults. The catalog text
  points users at `categorical` and `uniform` for real use.

## Owner questions

1. **Config shape.** Recommend `type: provider, provider: <name>`. Alternative: accept registry
   names in `faker_type`. That mixes two registries under one key and makes the unknown-name
   check ambiguous.
2. **`unique: true` on provider columns.** Recommend V2-LOG. Identifier output is near-unique
   but not guaranteed, and a true unique draw needs a retry family like GEN-UNIQUE's.
   Alternative: build it now on the `faker_unique` retry pattern (about 150 more lines).
3. **Per-provider options (MRN prefix and digits, composite `email_format`, `domain_pool`).**
   Recommend V2-LOG: defaults only in V1. Alternative: a `provider_options` mapping checked
   against each adapter's declared keys, which needs every adapter to declare its keys first.
4. **`composite_custom` in generation.** Recommend refusing it. Its coherence is identity
   stability over a source value, which means nothing when there is no source. Alternative:
   allow it as independent draws, which would mislead users.
5. **`sex` values.** Recommend `F` and `M` in V1. Alternative: a configurable label map (V2-LOG).

Questions 1 to 5 were taken on the recommended answers under standing approval (2026-11-10), as
roadmap row 24p records. Revision 3 adds no owner question. A9 was answered by the owner on 2026-11-12
(go-recommended): SSN, EIN, NPI and NDC `en_US` only; IBAN, PAN and ICD-10 locale-free; CUSIP
`en_US` and `en_CA`. MRN, not named there, follows its locale-agnostic kernel.

## V2-LOG / deferred

- `unique: true` on provider columns (Owner question 2).
- `provider_options` (Owner question 3).
- Pinned route support and streamed admission for `provider`.
- Per-provider payload width bounds in `_bounds.py`.
- A batch keyed path for identifiers and composites, if T2 shows any path below 20k rows/s.
- Locales beyond each provider's declared `supported_locales`.
- More optional person fields (for example `phone` tied to `state`) and other `sex` labels.

## Not verified

- Throughput of per-row identifier `generate` in generation. No tests were run for this plan. T2
  measures it.
- How `docs/capability-matrix.md` renders a long `supported_locales` tuple for the four
  locale-independent identifiers. If the render is unreadable, the generator prints the
  `ENGINE_LOCALES` name for that tuple; the builder checks at E1.
- Whether any platform or CLI code reads an identifier's `supported_locales`. A search of the
  engine found only the declarations and the mimesis adapter; the CLI and platform were not searched.
- The exact docstrings and count tests that pin the registry at 34 names. Dennis r1 listed them
  (E3 step 2); the builder confirms the list at E3 start.

## Review round 1 resolution

Dennis round 1 on `d782ffc4`: NO-GO, one blocker, three required edits, six fold-ins.

- B1 (no byte golden for the masking composites). Accepted. E2 step 1 now splits the refactor into
  two commits. Commit 1 adds a `CompositeHandler` digest test for all six composites, in
  deterministic and non-deterministic mode, captured on base. The factory signature is fixed at
  `(coherent_namespace, registry, provider_config)`. The `composite_custom` bundle-shape check
  and its `ExecutionError` stay in the handler. `COMPOSITES` is exported from
  `generation.composite`. AT-13 and P9 updated.
- M1 (cross-arch digests). Accepted and strengthened at the Codex gate. AT-3 commits digest
  constants for every live scalar provider and supported composite, then runs them on the Mac and
  a Linux VM at T2. E1 step 7 states that every draw path is integer-only. New P16.
- M2 (count pins). Accepted. E3 step 2 lists the pins that move from 34 to 36 and notes the
  platform picker's two new entries.
- M3 (`from None` keeps `__context__`). Accepted. The translation now raises after the `except`
  block closes. Design notes, E1 step 7, class 6 and the AT-16 mutant updated.
- Fold-ins: P15 now sets a 20k rows/s floor with Dennis's measurements. A miss opens the
  V2-LOG batch path rather than blocking, per the V1 bar. The catch set adds
  `IdentifierError` and `DeterminismError`. The Fields line now says `determinism: fresh` uses an
  `os.urandom` root. `ProviderSpec` sets `deterministic`, `namespace` and `seed` explicitly. The
  three extra composite name lists join the set guard. `execution/_column_access.py` reads
  `COMPOSITES`; leaf `validators/_leak_check.py` keeps its guarded literal. The legacy resident
  route and its memory bound are stated in E1 step 8.

## Codex plan gate

Checked against engine `origin/main` at `57d44a9a`, GEN-STRICT E2 at `3e954ce5`, and GEN-TYPES E1
at `86785412`. Dennis round 2 was GO. This gate applied his four requested corrections and then
closed the additional V1 and DESIGN findings found in the cross-model read.

- V1: Replaced both invalid illustrative config shapes with the engine's real `tables[]`,
  `row_count` and `generate_columns` shape.
- V1: Made the non-poolable Faker `ProviderSpec` pass `deterministic`, `namespace` and `seed`
  explicitly.
- V1: Expanded the fixed-text runtime translation boundary to the pool errors and added a live
  effective-locale check, so instance defaults and pool failures cannot escape with value-bearing
  messages or the wrong code.
- V1: Keyed the table-local composite bundle cache by `(provider, group)` and added the collision
  cell where two composite providers reuse one group label.
- V1: Made every composite group agree on determinism and on a compile-decidable locale
  declaration. The group seed now carries the agreed determinism, so `fresh` is not silently
  treated as stable and member order cannot choose an instance default.
- V1: Strengthened cross-platform determinism from one sample per backend to committed canonical
  Arrow fingerprints for every live scalar provider and every supported composite on arm64 and
  x86 Linux. The plan now states the integer-only path for every provider-value draw family and
  separately pins the existing null post-pass.
- V1: Pinned masking byte identity to E2 commit 1's pre-refactor canonical Arrow fingerprint test,
  including schema, row order, nulls and type-tagged values. Class-table row 9 points to that test.
- DESIGN: Removed the proposed duplicate `gen.provider_row_keyed` draw site and provider. The new
  kind maps to the existing `gen.derive_context` generation root and reuses the existing
  identifier, pool and composite sites. Its static capability row is conservative across those
  variants. No second randomness registry is created and no generation path is mislabeled as
  `mask_key`-rooted.
- DESIGN: Added `variable_output` to the composite descriptor so the variable-output set derives
  from the same table, and recorded the exact dependency split from Dennis round 2:
  `execution/_column_access.py` reads public `COMPOSITES`, while leaf `validators/_leak_check.py`
  keeps its literal under the AT-13 agreement guard. Origin/main has no `.importlinter` yet.
- V1: Replaced P5's `from None` wording with the required raise-after-`except` sequence and kept
  AT-16's explicit `__cause__` and `__context__` mutation.
- V2-LOG: Per-row provider throughput remains unmeasured until T2. A miss below 20k rows/s records
  the batch-path follow-up and does not change the V1 verdict.
- V2-LOG: Main advanced from the behavior baseline only through release and gate-selection work;
  the plan records the inspected current ref while retaining behavior citations to its ancestor.

Verdict: GO. No open V1 or change-created DESIGN finding remains in the plan.

## Revision 3 deltas

For the Codex recheck. Each item changed after the 11-10 GO; everything else is the GO text with
refreshed citations.

1. Base moved from `57d44a9a` to `8796ef69`. GEN-STRICT E2, GEN-TYPES and the one-seed-path fix are
   merged facts. Every line citation was re-read on `8796ef69`.
2. A9 joins E1 as commit 1, using the owner's per-provider scope from 2026-11-12 (CUSIP `en_US`
   and `en_CA`): `providers_v2/identifiers/_locale.py`, nine adapters read it, AT-19,
   P17, a frozen-contract row for the widened declarations.
3. The instance-default locale check moves from a run-time `runtime.generation_provider_failed`
   to the existing compile-side choke point `check_faker_default_locale`, giving
   `plan.generate_provider_locale_unsupported`. The in-draw recheck stays as the check-then-use
   guard (E1 steps 6 and 7, AT-7, AT-16).
4. E1 moves the grouped/windowed/group-key dispatch into `_grouped_windowed_generators.py` so
   `synthesize.py` (593 lines) stays under 600 with no census entry (E1 step 8, P14, Placement).
5. `execution/_column_access.py:270` drops its private `_validate` import for public `COMPOSITES`
   (E2 step 1). The `.importlinter` contract now exists and is unchanged.
6. The proof-manifest generate count moves 14 to 15, not 12 to 13.
7. Slices carry tiers (all R2), named mutations and a "Ratchets touched" line, including the
   secret-material census entries for new seed bindings.
8. Codex recheck on `dfec892a` (NO-GO, one V1): AT-19 tested only `en_US` and `fr_FR`, so
   CUSIP's declared `en_CA` was never exercised. AT-19 now derives its cells from each
   provider's declaration plus one undeclared probe, pins the owner's scope per provider, and
   adds two CUSIP `en_CA` mutants; AT-7 gains CUSIP `en_CA` compile and default-locale cells.
