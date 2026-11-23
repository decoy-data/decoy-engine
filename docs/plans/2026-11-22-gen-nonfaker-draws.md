Status: plan (revision 3, 2026-11-23)

# GEN-NONFAKER-DRAWS: uuid, random_int_range and random_choice draw per batch from keyed kernels (mask) and numpy words (generate); lorem pools

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GEN-NONFAKER-DRAWS, new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 88: "Not poolable | `address_full`, `lorem_text`, `uuid`, `random_int_range`, `random_choice` | pandas | per-row draw, `native/_provider_class.py`"). No row exists yet in the CLI roadmap; the CLI roadmap owner adds it to `docs/roadmap/groups/generate.md` and `mask.md` when this plan is accepted. Engine only.

One plan for both sides. The mask side and the generate side share one fact: how a drawn index or 16 random bytes become a uuid string, an integer in a range, or one of a list of elements. That fact lives in one module (section 5.1). The random bits come from different sources on each side, because each side already has its own determinism contract: keyed per value or per row position on the mask side, the column's seeded stream on the generate side.

Not combined with GEN-VECTOR-STREAMS (`plan/gen-vector-streams`). That row changes no bytes and has no mask side. This row's generate slice depends on its S1 (the `next_array` stream method).

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` at the same date. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `bugfix.md` (the compile refusal below), `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md` (keyed derivation), `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Revision 2 answers Dennis round 1 (2 DESIGN, 3 MEDIUM, 4 V2-LOG). Owner decisions recorded 2026-11-23 (go with recommended): `lorem_text` becomes poolable; uuid is version 4 over keyed bits; `text` and `paragraph` join GEN-STREAM-ALL group A; the generate-side byte change is accepted; S1 is in the V1 closing set.

Revision 3 fixes Codex round 1: [V1] caller-specific generated dtypes and typed route scope, [DESIGN] one Faker draw-contract choke point, and [V2-LOG] the revision label.

Risk: R2 (keyed masking output, a new computed operator variant on the routes whose schema can carry it, a named generate-side byte change). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; faster and more robust wins even when bytes change, and every byte change is named (section 10); output stays deterministic per seed; mask-side values are deterministic per (seed, namespace, row) on every route that admits their computed output type and do not depend on chunk size.

## 1. Frame

### 1.1 Mask side: refused at compile, while scan and init recommend it

The audit lists the five non-poolable Faker providers as "pandas, per-row draw". The code is stricter than that. `plan/_checks.py:99` `check_non_poolable_provider_with_pool_backend`, called at `plan/_compile.py:197`, refuses any `strategy: faker` column whose provider has `poolable=False` (`providers_v2/_real_registry.py:86-90`: `address_full`, `lorem_text`, `uuid`, `random_int_range`, `random_choice`), with `reasons.plan.NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND`. The reason given there: `FakerStrategyHandler` always builds a pool (`execution/_strategies/_faker.py`), and `PoolBuilder.build` raises for these providers.

But the engine's own scan recommends this config. `profiling/recommendations.py:344-347` gives a detected UUID column the starter `strategy: faker, provider: uuid`. The CLI init does the same for UUID columns (`CLI:src/decoy/cli/_init_inference.py:201-205`). For IPv4 columns init writes `redact` (`:206-213`), and its review text tells the user to swap to `faker` with `provider: random_choice`, which compile refuses too. So the UUID config that `decoy scan` and `decoy init` write fails at compile, and so does the IPv4 swap their review text suggests. Under the V1 bar that is a function break.

### 1.2 Generate side: one Faker call per row, seeded per row

On the generate side these are Faker methods: `faker_type: uuid4`, `random_int`, `random_element`, `text`, `sentence`, `paragraph`, and the `provider` kind with `uuid`, `random_int_range`, `random_choice`, `lorem_text` (`providers_v2/_faker_adapter.py:60-66` maps them to `uuid4`, `random_int`, `random_element`, `text`). Unless pooled, they run in `PerRowFakerStream` (`generation/_column_streams.py:188-193`): `seed_instance(row_int("faker", i))`, then the provider, per row. `row_int` is one HMAC per row (`generators/derivation.py:354`). GEN-STREAM-ALL keeps `uuid4` in its never-pooled identifier class, so pooling does not fix uuid.

### 1.3 What the kernels already give

| Need | Existing kernel | Python reference |
|---|---|---|
| index in `[0, n)` keyed by value | `derive_index_batch` (`decoy-engine-native/src/arrow_ffi.rs:365`), the faker pool selection kernel | `determinism/_derive.py:318` `derive_index` |
| index keyed by global row position | the same kernel over `positional_key_array` (`execution/_positional_keys.py:53`), as `sample_faker_array_positional` does (`execution/native/_operator_step.py`) | `positional_pool_indices` (`execution/_strategies/_faker_positional.py`) |
| 128 keyed bits per value or position | `derive_batch` (`arrow_ffi.rs:281`), the native `hash` kernel, with `truncate=32` hex | `kernel.hash_array` (`kernel/_scalar.py:43-60`) |

Both are chunk-independent by construction: the key is the value or the global row number, never a chunk-local index. NATIVE-THREADS-DEFAULT (`plan/native-threads-default`) S2 moves positional index draws onto an AES positional PRF through its `POSITIONAL_SITES` table, and S3 moves source-keyed index draws onto AES-CMAC. Because this row calls the same index helpers the faker pool path calls, those changes reach it with no extra work. The uuid draw stays on keyed hash derivation (HMAC), which S3 does not change.

### 1.4 Measurements

Dell, 120,000 rows, from the probe run for this plan and the audit: per-row Faker on the generate side runs at about 8,600 rows/s for `email` (audit); per-row seeding costs one HMAC plus `seed_instance` per row. The keyed index kernel is the one the native faker pool route already uses at pool-select speed (12.6 ns/row for numpy indices plus `pc.take`, GEN-STREAM-ALL section 1). The probe's per-provider Faker timings were still running on the Dell when this plan was pushed; S1 records them in its gate report as the baseline for AT-9 and AT-10.

## 2. Established solutions

Search run: UUID layout for derived and random identifiers (RFC 9562 sections 5.4, 5.8 and 6.5); keyed pseudonym generation over a range (NIST SP 800-188 pseudonymization; format-preserving index maps); batch-invariant random streams (numpy `BitGenerator.random_raw`, counter-based generators); how fake-data tools draw these types (Faker `uuid4` uses `getrandbits(128)` then sets the version bits; Mimesis and SDV RDT `AnonymizedFaker` call per row).

- RFC 9562 defines version 4 as 122 random bits with the version nibble `0100` and the variant bits `10`. Faker's `uuid4` does exactly that from its seeded generator. Section 5.8 (version 8) is for custom layouts and 6.5 for name-based. This plan uses the version 4 layout over keyed pseudorandom bits, so the output reads as the same kind of value Faker gives today and passes common v4 validators.
- Keyed index over a fixed domain is the engine's existing DE-02 selection (`derive_index`), the NIST pattern. `random_int_range` is an index over `(max - min) // step + 1` values; `random_choice` is an index over the element list.
- For the generate side, one raw 64-bit word per draw (`BitGenerator.random_raw`) makes a draw a pure function of its position in the stream, so batching cannot change it. numpy's `Generator.integers` buffers 32-bit halves inside one call, so two calls do not equal one long call for small ranges; this plan does not use it.
- Lorem text has no identity to protect, so a pool of Faker paragraphs is enough. GEN-STREAM-ALL's certified pool set already holds `sentence` and `word`.

### Reuse inventory

- `derive_pool_indices` (the public promotion of `generation/pool/_sampler.py:147-195` `_derive_pool_indices`), native `derive_batch`, and `kernel.hash_array`: the existing mask-side derivation paths. No new Rust and no new production kernel chooser.
- `positional_key_array`, `positional_pool_indices`, `sample_faker_array_positional`'s null handling: positional mode.
- `classify_provider` (`execution/native/_provider_class.py:68`): gains one class (section 5.2).
- Registry capabilities `_faker_cap` (`providers_v2/_real_registry.py`): the one place that marks a provider.
- Draw-site registry (`execution/native/_draw_sites_mask.py`, `_draw_sites_gen.py`) and `execution/native/_determinism_protocol.py:93`: new draw sites registered there.
- GEN-VECTOR-STREAMS S1 `next_array`; GEN-STREAM-ALL `pool_take` and the eligible set.
- FAKER-DEFAULT-POOL (`plan/faker-default-pool`): a pooled `lorem_text` with no `pool_size` gets 10,000.

## 3. Guarantee and non-goals

After this row:

1. Mask side: `strategy: faker` with `provider: uuid`, `random_int_range` or `random_choice` compiles and runs on the pandas full-frame route as a computed draw. No pool is built. `uuid` emits string, `random_int_range` emits int64, and `random_choice` emits the one homogeneous Arrow type inferred and pinned from `elements`; a mixed or non-Arrow-representable mask choice is refused by E5. The native faker operator remains string-tokenizing. Therefore uuid, and a `random_choice` whose pinned output is exact string, may also run chunked native, sequential native, unified and out-of-core where their existing source and mode gates admit them. A computed result with any other output type is declined before that route starts with the codes in E11 and E13. Auto routing falls through to pandas full frame; a forced out-of-core request refuses at preflight. The every-route claim applies only to an admitted exact-string computed result, not to int64 or another scalar type.
2. Mask side: deterministic index draws go through public `generation.pool.derive_pool_indices`, promoted from `_derive_pool_indices` (`generation/pool/_sampler.py:147-195`). Positional draws go through `positional_pool_indices` (`execution/_strategies/_faker_positional.py:47`). `derive_pool_indices` owns pandas-to-Arrow conversion and the `native_type_not_admitted` fallback to the reference kernel. The pandas uuid leg calls `kernel.hash_array` (`kernel/_scalar.py:43-60`) over the same canonicalized source. Native routes use the crypto kernel that their route already binds with `load_compiled_crypto_kernel` (`execution/native/_kernels_keyed.py:62-69`). One `ComputedDrawSpec` carries the resolved output type and is read by full-frame execution, native admission, chunk assembly, sequential, unified, and `out_of_core/_mask.py::masked_output_type`. This row adds no production chooser for `derive_batch`. Route parity and frozen vectors prove equal values and schemas on admitted routes; decline tests prove the rest never execute under a false schema.
3. Mask side: `lorem_text` becomes poolable (owner decision) and runs on the existing faker pool path. The flip also moves generate-side `provider: lorem_text` onto the pool path through `draw_path` (`generation/kinds/_provider.py:47`); that byte change is named in section 10 and lands with its `Breaking:` line in S2, the slice that flips the flag. `address_full` stays refused at compile, as today.
4. Generate side: `faker_type: uuid4`, `random_int`, `random_element` and the `provider` kind with `uuid`, `random_int_range`, `random_choice` draw per batch from one raw-word stream per column. Caller contracts stay distinct. A `faker_type` column keeps the type selected by its existing Faker and numeric-typing path, including int64 for the admitted plain `random_int` case. A `provider` column still passes every non-null value through its existing text coercion and always emits string, including `provider: random_int_range` and mixed-scalar `provider: random_choice`. The output is deterministic per seed and independent of batch layout. Values change, but public dtypes do not (section 10).
5. Generate side: `text`, `sentence`, `paragraph` and `provider: lorem_text` pool through GEN-STREAM-ALL's eligible set (`text` and `paragraph` added to group A, owner decision).
6. One formatter module turns bits into values for both sides, while the compiled caller-specific descriptor performs the existing output coercion and pins the exact Arrow type (section 5.1).
7. The scan and init recommendations for UUID and IP columns compile and run (AT-1).

Non-goals: `address_full` (composite; FAKER-NATIVE-WIDEN and the composite rows own it); `unique`, `match_source_cardinality` and `scale_source_cardinality` modes for the computed providers (refused at compile with a registered code); Faker kwargs other than `min`, `max`, `step` and `elements`; new Rust.

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | mask, deterministic, non-null value | keyed draw on the value |
| E2 | mask, non-deterministic (`cardinality_mode` absent or `reuse`) | keyed draw on the global row number |
| E3 | null source | null out in place; in positional mode the row still uses its row number (as `sample_faker_array_positional` does) |
| E4 | `random_int_range` with `max < min`, `step < 1`, a count `(max - min) // step + 1` over 2**56, or a top value `min + (count - 1) * step` outside int64 | compile refusal, new code `computed_draw_range_invalid` |
| E5 | mask `random_choice` with empty or non-list/tuple `elements`, or elements that do not have one homogeneous Arrow type; generate caller shapes outside section 5.3 | mask compile refusal with new code `computed_draw_elements_invalid`; generate stays per row as E12 |
| E6 | `unique` or a cardinality mode other than `reuse` on a computed provider | compile refusal, new code `computed_draw_mode_unsupported` |
| E7 | companion absent | the shared helpers pick the Python reference; same bytes. Native routes decline with their existing companion-absent reason and the column runs on the pandas route |
| E8 | `address_full` | compile refusal, existing `NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND` (`plan/_checks.py:99`) |
| E9 | generate, any batch layout | same output (raw-word stream) |
| E10 | a user namespace containing `/computed:` | compile refusal, new code `computed_draw_namespace_reserved` |
| E11 | out-of-core, positional mode, a source that is not exact `string`, or a computed output type that is not exact `string` | auto route declines before execution with existing `faker_not_deterministic_reuse` or `string_source_type_rejection`, or new route reason `faker_computed_output_type_unsupported`; forced out-of-core refuses at preflight with new runtime code `out_of_core_faker_computed_output_type_unsupported` |
| E12 | generate, an argument shape section 5.3 does not admit | `faker_type` stays on `PerRowFakerStream`; `provider` stays on its existing adapter batch path; bytes and dtype stay unchanged and the computed path never creates a new runtime crash |
| E13 | chunked native, sequential native or unified sees a computed output type other than exact `string` | route decline `faker_computed_output_type_unsupported`; auto routing falls through to pandas full frame, and no native formatter or string assembly runs |

### Routes

| Route | Mask side | Generate side |
|---|---|---|
| pandas full frame | `FakerStrategyHandler` (`execution/_strategies/_faker.py:44`) dispatches all three computed providers to `computed_mask_draw`; the descriptor pins natural mask output type | - |
| chunked native, unified slice | `resolve_operator_variant` turns an exact-string computed descriptor into a computed operator variant that does not build a pool; other output types take E13 before the existing string-tokenizing pool operator or assembly runs | - |
| sequential | native admission reads the same descriptor and exact-string rule; other output types take E13 and the job falls through to the pandas full-frame route | - |
| out-of-core | existing `out_of_core/_faker_native.py` admission adds computed providers only for deterministic reuse, exact-`string` source and exact-`string` computed output; `out_of_core/_mask.py:253` `masked_output_type` reads the same descriptor; other shapes take E11 | - |
| streamed generation | - | `ComputedDrawStream.next_array` |
| whole-table generation (`synthesize.py`) | - | the same stream, drawn once for all rows |

### Codes

Four new plan codes (E4, E5, E6, E10), registered once in `reasons/plan`. One route code, `reasons.route.FAKER_COMPUTED_OUTPUT_TYPE_UNSUPPORTED`, is the shared E11/E13 decline. Two runtime codes are registered once: `reasons.runtime.COMPUTED_DRAW_POSITION_OUT_OF_DOMAIN` for positional keys, beside `FAKER_POSITION_OUT_OF_DOMAIN` (`execution/_strategies/_faker_positional.py:27`), and `reasons.runtime.OUT_OF_CORE_FAKER_COMPUTED_OUTPUT_TYPE_UNSUPPORTED` for a forced out-of-core request. Positional computed draws are their own positional site, `mask.faker_computed_position`: when NATIVE-THREADS-DEFAULT S2 adds `POSITIONAL_SITES` (not on main yet), this site gets its own row there, so its re-key is explicit and not inherited from the faker pool site. If ROUTE-LABEL-TRUTH has merged, its `kernel_less_per_row_faker` family loses `uuid`, `random_int_range` and `random_choice` (they now have a kernel) and its sentry sees the change; if it has not merged, nothing to do.

### FK shapes

- A computed-draw column that is an FK key in deterministic mode: the same value gives the same output on both sides of the key, because the draw is keyed on the value and namespace. Admitted where faker deterministic keys are admitted today.
- A computed-draw key in non-deterministic mode: positional draws break joins, so it is refused where positional faker keys are refused today (same check).
- A uuid key column with distinct inputs: collisions are possible at about n**2 / 2**123; recorded, not guarded.

### Fields

| Provider | Fields | Default |
|---|---|---|
| `uuid` | none | - |
| `random_int_range` | `min`, `max`, `step` (ints, not bools) | 0, 9999, 1 (the existing Faker/numeric-typing fact, moved to the shared contract in section 5.1) |
| `random_choice` | `elements` (list or tuple of scalars); mask route additionally requires one homogeneous Arrow type | `("a", "b", "c")` (the existing `_FAKER_DEFAULT_KWARGS` fact, moved to the shared contract in section 5.1) |
| `lorem_text` | Faker `text` kwargs | Faker defaults |
| all | `deterministic`, `namespace`, `cardinality_mode` | as for faker |

### Output surfaces

| Surface | Change |
|---|---|
| masked column | new values (the config was refused before) |
| generated column | changed values for the listed types (section 10) |
| route evidence | `rust_companion` when the kernel ran; `pandas_oracle` when the reference ran |
| draw-site registry and determinism protocol | new sites `mask.faker_computed_value`, `mask.faker_computed_position`, `gen.computed_draw` |
| `docs/` | provider pages for the four providers; route table |
| changelog | `Breaking:` line for the generate-side change |

## 5. Design notes

Principles that apply: one place per fact (Faker draw arguments and defaults; bit-to-value formatting; the provider class in the registry); dependency direction (provider contracts sit in `providers_v2`, formatting sits in `generation/`, and `execution/` consumes both through public APIs; generation never imports execution kernels). Established patterns: RFC 9562 version 4 layout; DE-02 keyed index; raw-word streams. The change pain is concrete: the adapter defaults, numeric typing and computed route would otherwise carry three independently edited argument/default tables, while the route layers would otherwise infer output type independently.

### 5.1 One draw-contract choke point and one formatter

`providers_v2/_faker_draw_contracts.py` is the one cross-cutting source for the three computed Faker methods. Its frozen `FakerDrawContract` rows name the provider alias and Faker type, accepted argument names and strict shapes, defaults, and the natural result family. The existing `_FAKER_DEFAULT_KWARGS` data moves here and becomes a derived read-only view of these rows. The `random_int` entry now owns the existing `min=0`, `max=9999` numeric defaults that `_INT_PROVIDERS` currently repeats in `generation/_numeric_typing.py:54`. Consumers reach `faker_draw_contract(...)` through `providers_v2`'s public API:

- `FakerAdapter` builds its default kwargs from the contract-derived `_FAKER_DEFAULT_KWARGS` view.
- `_numeric_typing.py` keeps its unrelated integer providers where they are, but derives the `random_int` keys and bounds from the same contract rather than restating them.
- `computed_draw_spec` validates and fills arguments from the contract. It contains no accepted-argument or default table of its own.

`tests/sentry/generation/test_faker_draw_contract_choke_point.py` walks the adapter, numeric typing and computed-spec consumers. It proves every computed name resolves to the same contract row, proves `_FAKER_DEFAULT_KWARGS` and the numeric view are derived from it, and fails if a consumer introduces a local default or accepted-argument literal for these names. The seeded bypass changes `random_int`'s adapter or numeric default locally to 1 without changing the contract; the guard must turn red. This is the DESIGN choke point and guard, not a second provider table.

`generation/pool/_computed_draw.py`:

- `uuid_from_bits(bits: np.ndarray[uint8, (n, 16)]) -> pa.Array`: set byte 6 high nibble to 4 and byte 8 top bits to `10`, then format `8-4-4-4-12` lowercase hex with numpy (no per-row `uuid.UUID`).
- `int_from_index(index, *, lo, step) -> pa.Array` (int64).
- `choice_from_index(index, elements) -> list[scalar]`: selects values without first constructing one Arrow array. The caller-specific materializer then applies its existing coercion and constructs an array with the descriptor's pinned type. This is what keeps mixed-scalar `provider: random_choice` on its existing string contract.
- `ComputedDrawSpec`: provider/Faker identity, caller kind (`mask`, `faker_type`, or `provider`), parsed fields, count, output policy and exact `pa.DataType`. It is built and validated once and then carried through admission and execution. Mask uses natural `string`, `int64`, or the homogeneous choice type. `faker_type` receives the type already selected by generation admission and `numeric_plan`. `provider` always pins `pa.string()` and applies the existing `_as_text` rule before Arrow construction.
- `computed_draw_spec(caller, name, kwargs, *, planned_output_type) -> ComputedDrawSpec | None`: the one parser and descriptor builder. It delegates all argument/default facts to `faker_draw_contract`. On the generate side `None` means E12. On the mask side the compile check turns a refusal into E4 or E5.

The formatter and compiled spec live in the existing `generation.pool` package. The package exports them through its public API. S1 imports the argument contract through the public `providers_v2` API and imports nothing from `generation.stream` or GEN-STREAM-ALL. Thus, the V1 mask fix has no dependency on GEN-STREAM-ALL. S3's `ComputedDrawStream` reuses these public names after GEN-STREAM-ALL creates `generation/stream/`.

### 5.2 Mask side

- Registry: `_faker_cap` gains `draw: Literal["pool", "computed"]`. `uuid`, `random_int_range`, `random_choice` become `computed`; `lorem_text` becomes poolable (owner decision); `address_full` stays not poolable. The capability flag selects the draw family only; argument/default facts stay in `faker_draw_contract`.
- `classify_provider` returns a new class `computed_native` for `draw="computed"`.
- `check_non_poolable_provider_with_pool_backend` keeps refusing `poolable=False` providers that are not computed (so `address_full`), and the new E4 to E6 checks run for computed ones.
- One function, `computed_mask_draw(source, *, spec, mode, key, namespace, row_offset, gate_positions)`, in the faker positional strategy module. It calls no kernel method directly for indices:
  - `random_int_range` and `random_choice`, deterministic: promote `_derive_pool_indices` to public `derive_pool_indices` in `generation.pool`. Then call `derive_pool_indices(nonnull_source, seed=key, namespace=ns, pool_size=spec.count)`. Do not call bare `derive_validated_indices` on `nonnull_values`. `derive_pool_indices` owns Arrow conversion and the fallback for dates, decimals, integers past int64 and mixed object columns.
  - The same two, positional: `positional_pool_indices(n, row_offset=..., job_seed=key, namespace=ns, pool_size=spec.count, gate_positions=..., domain_code=COMPUTED_DRAW_POSITION_OUT_OF_DOMAIN)`. `positional_pool_indices` gains the `domain_code` keyword, default unchanged.
  - uuid: the pandas leg calls `kernel.hash_array(..., truncate=32)` over the source values or `positional_key_array(...)`. This call uses the hash kernel's canonicalization. Native legs call `derive_batch(..., truncate=32)` on the compiled crypto kernel that their route already binds at `execution/native/_kernels_keyed.py:62-69`. They use the same canonicalized source, then convert hex to bytes and call `uuid_from_bits`. S1 first checks that the bound native kernel accepts the uint64 key array. If it does not, both legs cast the keys to string once. AT-3 freezes the form that ships.
  - Because index draws use the shared helpers, NATIVE-THREADS-DEFAULT S1 (thread budget in the helper) and S2/S3 (re-keys) reach them with no edit here. This row adds no `derive_batch` chooser: pandas uses `kernel.hash_array`, and each native route uses its existing bound crypto kernel.
- Namespaces: the selection namespace is the column namespace plus `/computed:<provider>`, so a computed draw never shares index material with a pool draw in the same namespace. A user namespace containing `/computed:` is refused (E10).
- Operator resolution: the static faker `OperatorSpec` remains the pool variant. A new `resolve_operator_variant(seed)` choke point in `_operator_registry.py` first classifies the provider. Pool providers return the existing spec unchanged. Computed providers obtain `ComputedDrawSpec` and return a `ResolvedOperatorSpec` with `shape="computed"`, the descriptor's `required_kernel` (`crypto` for uuid, `index` for integer/choice), its exact output type, and its assembly contract. No computed variant carries pool identity or pool-build parameters. Native admission, `_operator_step.py`, chunk schema assembly, `_sequential_native_ops.py`, and unified admission must accept only the resolved spec and may not read `OPERATORS["faker"]` directly for a computed provider. The realistic bypass mutation sends a computed provider through the pool spec; AT-2 must fail before any pool build.
- Typed native scope: membership in the faker `provider_allowlist` is not sufficient. `resolve_operator_variant` returns E13 unless `spec.output_type == pa.string()`, because the current native faker assembly contract is string-only. `random_int_range` therefore takes E13 on native resident routes and E11 out of core. A string `random_choice` and uuid can be admitted subject to existing source/mode gates. Chunk schema assembly, sequential and unified read `ResolvedOperatorSpec.output_type`; they do not infer the type from provider names. FAKER-NATIVE-WIDEN edits the same allowlist for poolable providers; whichever merges second rebases on the other's list.
- Out-of-core scope: `out_of_core/_faker_native.py` obtains the same computed descriptor and dispatches computed execution without `OocFakerPoolContext`; `out_of_core/_mask.py::masked_output_type` returns its output type. It admits only deterministic reuse, exact-string source and exact-string computed output. It does not restate provider-to-output-type rules.
- Out-of-core execution extends the existing `execution/out_of_core/_faker_native.py` and `_mask.py`; this plan does not cite or create a separate out-of-core computed module. Auto admission records the E11 route reason and reroutes. Forced out-of-core preflight raises the E11 runtime code before scratch allocation or sink writes.

### 5.3 Generate side

S3 creates `ComputedDrawStream` in `generation/stream/_computed_draw.py` after GEN-STREAM-ALL creates that package. `_faker_stream` (`generation/_column_streams.py:330`) and the `provider` kind builder create the stream before the pool check. Each builder passes its own caller kind and its existing planned output type. The stream imports the formatter and spec through the public `generation.pool` API:

- One `np.random.PCG64(ctx.base_int("draw"))` bit generator per column. Each value takes a fixed number of raw 64-bit words: uuid two, the others one. Index is `word % count` (bias at most `count / 2**64`).
- `next_array(offset, size, type)`, the GEN-VECTOR-STREAMS signature. It copies the column's start state and calls `PCG64.advance(offset * words)`, then reads `size * words` raw words. A value depends only on its row number, so no batch layout can change it, and out-of-order batches give the same column.
- Whole-table generation calls the same stream for all rows at once. It materializes using `spec.output_type`; it never asks Arrow to infer a shared type for provider values.
- Argument shapes S3 admits through `computed_draw_spec`; everything else takes E12:

| Caller and type | Admitted computed shape and preserved dtype | Existing path retained |
|---|---|---|
| `faker_type: uuid4` | no kwargs and `cast_to=str`; string, as today | `cast_to=None`, any other `cast_to`, or any other kwarg stays per row |
| `provider: uuid` | no provider args; string through existing provider text coercion | any extra arg stays on adapter batch |
| `faker_type: random_int` | strict int `min`, `max`, `step` from the shared contract; exact dtype supplied by existing numeric typing, with the plain admitted golden int64 | float or string bounds, bools, or unknown kwargs stay per row |
| `provider: random_int_range` | the same strict range contract; always string through existing provider text coercion | invalid or unknown args stay on adapter batch |
| `faker_type: random_element` | non-empty list or tuple of scalars with one stable Arrow type; keeps that existing natural/planned dtype | string, dict/weighted, empty, mixed-type, or unknown shapes stay per row |
| `provider: random_choice` | non-empty list or tuple of scalars, including mixed scalar types; every non-null result is coerced to string before `pa.array(..., type=pa.string())` | string, dict/weighted, empty, or unknown shapes stay on adapter batch |

A generate config whose bounds fail E4 stays per row too, so whatever Faker does today it still does; the generate side refuses nothing new.
- Shadow generation: `SHADOW_ADMISSIBLE_FAKER_TYPES` is `POOL_ELIGIBLE_FAKER_TYPES` (`execution/physical/_shadow_generation.py:100`). Adding `text` and `paragraph` to group A widens it. S3 adds both types to the shadow parity cells; if a cell fails, S3 pins the shadow set to its current members instead of widening it.

### 5.4 Lorem

Mask: `lorem_text` with `poolable=True` uses the existing pool path, so FAKER-DEFAULT-POOL and the native pool select (once FAKER-NATIVE-WIDEN admits it) apply. The same flag sends generate `provider: lorem_text` to pool through `draw_path`; S2 names it (section 10) and ships its `Breaking:` line. Generate: `text` and `paragraph` join GEN-STREAM-ALL group A as certified pairs (its harness checks they reproduce under a seed).

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| Faker draw argument/default contract | `providers_v2/_faker_draw_contracts.py` (new in S1, about 80 lines), exported by `providers_v2/__init__.py` | CODEMAP "Providers"; `providers_v2/` has 8 direct entries at the planning head, below the fan-out limit | `_faker_adapter.py` |
| formatter and `ComputedDraw` spec | `generation/pool/_computed_draw.py` (new in S1, about 100 lines) | CODEMAP "Generation": pools in `generation/pool/` | `generation/pool/_sampler.py` |
| public index helper promotion | `generation/pool/_sampler.py`, `generation/pool/__init__.py` | CODEMAP "Generation": pools in `generation/pool/` | `derive_validated_indices` |
| `ComputedDrawStream` | `generation/stream/_computed_draw.py` (new in S3, about 90 lines) | GEN-STREAM-ALL's row "Generation streamed batch assembly"; that dependency creates the package before S3 | `generation/stream/_batches.py` |
| `computed_mask_draw` | `execution/_strategies/_faker_positional.py` (grows about 60 lines; `_strategies/` is at its freeze of 28, so no new module) | "Masking strategy handler" | `_faker.py` |
| provider class | `execution/native/_provider_class.py` | "Native companion bridge" | - |
| resolved faker operator variant | `execution/_operator_registry.py` (`Shape` gains `computed`; no new file) | "Native companion bridge" | existing faker `OperatorSpec` |
| registry flag | `providers_v2/_real_registry.py`, capability type | "Providers" | - |
| compile checks E4 to E6 | `plan/checks/_computed_draw.py` (new) | "Plan compile and checks": new checks in `plan/checks/` | `plan/_checks.py:99` |
| codes | `reasons/plan` (four codes), `reasons/route` (one code), `reasons/runtime` (two codes) | reasons | - |
| `domain_code` keyword | `execution/_strategies/_faker_positional.py` `positional_pool_indices` | "Masking strategy handler" | - |
| draw sites | `execution/native/_draw_sites_mask.py`, `_draw_sites_gen.py` | "Native companion bridge" | existing sites |
| draw-contract guard | `tests/sentry/generation/test_faker_draw_contract_choke_point.py` | CODEMAP `tests/sentry/generation/`: generation choke-point sentries | existing generation sentries |
| tests | `tests/unit/generation/pool/test_computed_draw.py`, `tests/unit/generation/stream/test_computed_draw.py`, `tests/unit/execution/strategies/test_faker_computed.py`, `tests/unit/plan/checks/test_computed_draw.py` | "Unit tests" | - |

If `_faker_positional.py` would pass 600 lines, `computed_mask_draw` goes into a new `execution/_strategies/faker/` family package (CODEMAP: "next family in `execution/_strategies/<family>/` (target)") and S1 moves `_faker_positional.py` there with it.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | compile refusals E4 to E6 could echo `elements` or bounds | messages name the field, never its value | AT-7 | put `elements` into the E5 message (AT-7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no pool, no reservation for computed draws | n/a | n/a |
| 3 | State and concurrency | generate stream state across batches; kernel threads | one bit generator per column; kernels are thread-invariant (existing proof) | AT-4, AT-5 | create the bit generator per batch (AT-4 red) |
| 4 | Route parity, schema parity and silent fallback | computed mask routes | one typed descriptor feeds execution, admission, assembly, sequential, unified and out-of-core schema resolution; admitted routes compare values and schemas; unsupported output types decline before execution with registered reasons | AT-2 | M3 |
| 5 | Referential integrity | computed key columns | deterministic keys keyed on value; positional keys refused where today | AT-6 | M4 |
| 6 | Untrusted producer | compiled kernel output | existing `_checked_batch` length and null checks; hex length checked before decode | AT-3 | skip the hex length check (AT-3 short-output cell red) |
| 7 | Check then use | none | N/A: no file or path | n/a | n/a |
| 8 | Weak tests | value-only tests that miss route-dependent schemas or caller dtype drift | AT-2 compares admitted route values and schemas and checks declined-route decisions; AT-5 compares layouts; AT-11 pins a value and schema golden per caller kind | AT-2, AT-5, AT-11 | M1, M9 |
| 9 | Refactor drift | lorem pool flip and the compile check edit | existing non-poolable tests for `address_full` unchanged | AT-8 | drop `address_full` from the refusal (AT-8 red) |
| 10 | Frozen contract drift | generate-side output for six types | `Breaking:` line; compatibility contract note (pre-GA correction) | AT-10, docs review | omit a type from the changelog list (reviewer check against section 10) |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no regex validation added | - |
| 2 | Strict wire and stored types | yes: `min`, `max`, `step` must be ints, not bools or numeric strings | AT-7 cells for `True`, `"5"`, `5.0` refused |
| 3 | No exception context | yes: refusals raised after the parse block closes | AT-7 asserts cause and context None |
| 4 | Versioned read models | the draw-site registry has a provider version | new sites carry the current version; existing registry test |
| 5 | Normalized guard scanners | no | - |
| 6 | No reaching into private modules | `execution/` and `generation.stream` import formatter/spec/index names through public `generation.pool`; generation and execution import draw contracts through public `providers_v2` | import-linter |
| 7 | No hidden CI failures | companion-absent leg must run the reference path tests | CI review |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M10 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | the faker `provider_allowlist` | AT-2 walks every computed provider in the allowlist and proves a non-string descriptor cannot enter the string operator |
| 11 | No raised caps | `_strategies` freeze 28, `generation/` 25, module size | no new module in either; sizes listed |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Every `DetectorDescriptor` starter in `profiling/recommendations.py` goes through `compile_plan` and a run on a small frame; plus the IPv4 swap the init review text suggests (`faker`, `random_choice`) | the UUID starter fails with `NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND` today | S1 |
| AT-2 | Typed route matrix: pandas full frame runs all three providers in deterministic and positional modes over string, int, date and decimal sources with nulls, and asserts values plus exact Arrow schema. Exact-string uuid and string-choice cells compare values and schema across pandas (companion present and absent), unified, chunked at several sizes, sequential, and deterministic exact-string out-of-core. They also assert `shape == "computed"` and zero pool builds. `random_int_range` and non-string choice assert E13 on chunked native, sequential native and unified, E11 on out-of-core, and assert auto fallback produces the pandas values and schema. Forced out-of-core asserts the runtime code before writes. Date and decimal deterministic pandas cells prove `derive_pool_indices` takes its reference fallback. The matrix walks every computed provider in the native allowlist and fails if one enters the string pool operator or a non-string descriptor enters native assembly | refused today | S1 (pandas, chunked, unified), S2 (sequential, out-of-core) |
| AT-3 | Frozen vectors: fixed key, namespace and inputs give committed uuid, int and choice outputs; every uuid matches `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z`; every int is in `[min, max]` with `(v - min) % step == 0`; every choice is in `elements` | no draw today | S1 |
| AT-4 | Chunk and thread invariance (mask): admitted exact-string computed routes use chunk sizes 1, 7, 65,536 and `native_threads` 1 and 4 with `when:` gate positions; non-string cells compare the same layouts through their coded pandas fallback | refused today | S1 |
| AT-5 | Batch invariance (generate): layouts `[1]*7`, `[7, 4096, 3]`, one batch, and the whole-table path give equal columns | per-row Faker today has the property too; fail-before is AT-10 | S3 |
| AT-6 | FK: a deterministic `uuid` key column masks parent and child to equal values, with the child rows reordered and duplicated so row number and value differ; a positional key column is refused with the existing reason | refused today | S1 |
| AT-7 | Compile refusals E4 (including the int64 top-value cell), E5, E6, E10 with `True`, `"5"`, `5.0`, empty and non-list `elements`; messages value-free; cause and context None | no codes today | S1 |
| AT-8 | `address_full` is still refused; `lorem_text` now pools and runs on the mask side; generate `provider: lorem_text` takes `draw_path == "pool"` and its golden changes as named | `lorem_text` refused today | S2 |
| AT-9 | Speed, `perf`, Dell: masked `uuid` over 1,000,000 rows on the chunked native route at or under 200 ns per row | refused today | S1 |
| AT-10 | Generate speed and byte change: `uuid4` over 1,000,000 rows at or under 100 ns per row; a fixed seed has a committed golden output vector from `ComputedDrawStream`; the output differs from the per-row Faker golden (proves the new path ran) | per-row Faker today | S3 |
| AT-11 | Generate arguments and caller contracts: every row of the section 5.3 table. Each admitted caller kind has a committed value and Arrow-schema golden. In particular, plain `faker_type: random_int` is int64, `provider: random_int_range` is string, homogeneous integer `faker_type: random_element` keeps its natural/planned type, and mixed-scalar `provider: random_choice` yields only text without Arrow construction failure. E12 cells compare both bytes and schema with today's per-row or adapter-batch path | no computed stream today | S3 |
| AT-12 | Structure: an AST check requires the deterministic index branch of `computed_mask_draw` to call public `generation.pool.derive_pool_indices`, and forbids direct `derive_index_batch` or bare `derive_validated_indices` calls there | no function today | S1 |
| AT-13 | Draw-contract choke point: the sentry in section 5.1 derives the computed inventory, proves adapter defaults, numeric bounds and computed parsing resolve the same `FakerDrawContract`, and forbids local accepted-argument/default literals for those names. Seed a local `random_int` default of 1 in each consumer shape and prove the sentry fails | no shared contract today; the existing `_FAKER_DEFAULT_KWARGS` and `_INT_PROVIDERS` facts are separate | S1 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | uuid formatter leaves the version nibble unset | AT-3 |
| M2 | positional mode keys on the chunk-local index instead of the global row | AT-4 |
| M3 | the pandas uuid leg uses `random.Random` instead of `kernel.hash_array` | AT-2 |
| M4 | deterministic mode keys on the row number | AT-6 |
| M5 | `int_from_index` ignores `step` | AT-3 |
| M6 | generate stream uses `Generator.integers` per batch | AT-5 |
| M7 | `computed_mask_draw` calls `derive_validated_indices` directly instead of public `generation.pool.derive_pool_indices` | AT-12 |
| M8 | `computed_draw_spec` admits a string `elements` | AT-11 |
| M9 | the provider caller materializes `random_int_range` with the faker-type int64 output policy instead of text coercion | AT-11 |
| M10 | `resolve_operator_variant` returns the pool-shaped faker spec for uuid | AT-2 |

## 10. Frozen contracts and byte changes

Mask side: no byte change. These configs were refused, so there is no earlier output.

Generate side, byte change (pre-GA correction, one `Breaking:` line in the changelog and a note in `docs/compatibility-contract.md` section 1):

- `faker_type: uuid4` and `provider: uuid`: values change; still RFC 9562 version 4 strings.
- `faker_type: random_int` and `provider: random_int_range`: values change; same range and step. The former keeps its existing planned Faker dtype, with int64 pinned for the plain admitted case; the latter remains string.
- `faker_type: random_element` and `provider: random_choice`: values change; same element set. The former keeps its existing natural/planned dtype for admitted homogeneous elements; the latter remains string, including mixed scalar choices.
- `provider: lorem_text`: values change from per-row text to pool picks in S2, when the poolable flag flips (`draw_path`, `generation/kinds/_provider.py:47`). S2 carries its own `Breaking:` line.
- `faker_type: text` and `paragraph`: values change from per-row text to pool picks in S3 (GEN-STREAM-ALL group A).
- Generate configs with kwargs outside the section 5.3 table: no change.

Every other generate type keeps its bytes. FAKER-MIGRATE's output lock lists `uuid4`, `random_int` and `random_element` cells for the adapter; S3 regenerates those cells with this row's change named in the lock diff.

## 11. Pre-mortem

- NATIVE-THREADS-DEFAULT S2 or S3 merges first and changes the index helpers. This row calls the same helpers, so it follows; AT-3 vectors are regenerated once in the later of the two merges, and that merge names the change.
- A caller relies on the two integer-looking generate forms having different schemas. `faker_type: random_int` keeps the existing numeric-typing result, while `provider: random_int_range` remains string. AT-11 pins both values and schemas separately.
- A non-string computed mask is offered to a string-tokenizing route. The descriptor rejects it with E11 or E13 before execution; AT-2 mutates the type gate and observes schema parity fail.
- A uuid column feeds a database UUID type that rejects version 4 from non-random sources. No validator can tell; noted only.
- FAKER-NATIVE-WIDEN rewrites the allowlist shape. Section 5.2 names the rebase.
- The positional namespace suffix collides with a user namespace ending in `/computed:uuid`. Compile refuses namespaces containing `/computed:` with `computed_draw_namespace_reserved` (E10, S1).
- NATIVE-THREADS-DEFAULT S2 lands before S1 here. Then S1 adds the `mask.faker_computed_position` row to `POSITIONAL_SITES` itself; if S1 lands first, S2 of that row adds it.

## 12. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | shared Faker draw-contract registry and guard; registry flag and class; compile checks E4 to E6 and codes; typed formatter/spec; `computed_mask_draw`; pandas handler; exact-string unified and chunked native admission plus E13 declines; draw sites; AT-1 to AT-4, AT-6, AT-7, AT-9, AT-12, AT-13 | M: about 430 lines, 480 lines tests | Codex and Dennis; T2 on faker, plan and native selections |
| S2 | sequential and out-of-core exact-string admission; E11/E13 decline and forced preflight refusal; `masked_output_type` descriptor wiring; `lorem_text` poolable with its generate-side `Breaking:` line; AT-2 rest, AT-8 | S: about 150 lines, 200 lines tests | Codex |
| S3 | generate side: `ComputedDrawStream`, caller-specific typed descriptor wiring in `_faker_stream` and the provider kind (`draw_path` gains `computed`); GEN-STREAM-ALL group A gains `text`, `paragraph` with shadow parity cells; changelog `Breaking:`; FAKER-MIGRATE lock cells; AT-5, AT-10, AT-11 | M: about 230 lines, 300 lines tests | Codex and Dennis; depends on GEN-VECTOR-STREAMS S1 and GEN-STREAM-ALL S1b |

S1 is the V1 function fix and goes first. Its formatter and spec live in `generation.pool` and have no dependency on generation streams. Thus, S1 does not wait for GEN-STREAM-ALL, GEN-VECTOR-STREAMS or any generation row. All three fit before 2026-12-15 if GEN-STREAM-ALL S1b and GEN-VECTOR-STREAMS S1 merge by early December.

## 13. Owner decisions and follow-ups

Decided 2026-11-23 (go with recommended): `lorem_text` poolable; uuid version 4 over keyed bits; `text` and `paragraph` join group A; generate byte change accepted; S1 in the V1 closing set; generated `faker_type` and `provider` callers keep their distinct existing dtypes; native mask routes admit computed draws only when the shared descriptor proves their existing string operator and schema path can carry the result; argument schemas and defaults move to the one `FakerDrawContract` registry.

CLI follow-up row (CLI roadmap, `docs/roadmap/groups/mask.md`): after the engine release that carries S1, repin the engine in the CLI and add a CLI test that runs `decoy init` on a frame with a UUID column and then runs the written config. Optional in the same row: let init write `faker` with `random_choice` for IPv4 instead of `redact`, if the owner wants that default.

No open owner questions.
