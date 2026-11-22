Status: plan (revision 1, 2026-11-22)

# GEN-NONFAKER-DRAWS: uuid, random_int_range and random_choice draw per batch from keyed kernels (mask) and numpy words (generate); lorem pools

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GEN-NONFAKER-DRAWS, new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 88: "Not poolable | `address_full`, `lorem_text`, `uuid`, `random_int_range`, `random_choice` | pandas | per-row draw, `native/_provider_class.py`"). No row exists yet in the CLI roadmap; the CLI roadmap owner adds it to `docs/roadmap/groups/generate.md` and `mask.md` when this plan is accepted. Engine only.

One plan for both sides. The mask side and the generate side share one fact: how a drawn index or 16 random bytes become a uuid string, an integer in a range, or one of a list of elements. That fact lives in one module (section 5.1). The random bits come from different sources on each side, because each side already has its own determinism contract: keyed per value or per row position on the mask side, the column's seeded stream on the generate side.

Not combined with GEN-VECTOR-STREAMS (`plan/gen-vector-streams`). That row changes no bytes and has no mask side. This row's generate slice depends on its S1 (the `next_array` stream method).

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` at the same date. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `bugfix.md` (the compile refusal below), `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md` (keyed derivation), `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (keyed masking output, a new provider class on every mask route, a named generate-side byte change). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; faster and more robust wins even when bytes change, and every byte change is named (section 10); output stays deterministic per seed; mask-side values are deterministic per (seed, namespace, row) on every route and do not depend on chunk size.

## 1. Frame

### 1.1 Mask side: refused at compile, while scan and init recommend it

The audit lists the five non-poolable Faker providers as "pandas, per-row draw". The code is stricter than that. `plan/_checks.py:99` `check_non_poolable_provider_with_pool_backend`, called at `plan/_compile.py:197`, refuses any `strategy: faker` column whose provider has `poolable=False` (`providers_v2/_real_registry.py:86-90`: `address_full`, `lorem_text`, `uuid`, `random_int_range`, `random_choice`), with `reasons.plan.NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND`. The reason given there: `FakerStrategyHandler` always builds a pool (`execution/_strategies/_faker.py`), and `PoolBuilder.build` raises for these providers.

But the engine's own scan recommends this config. `profiling/recommendations.py:344-347` gives a detected UUID column the starter `strategy: faker, provider: uuid`. The CLI init does the same (`CLI:src/decoy/cli/_init_inference.py:188-190`) and suggests `provider: random_choice` for IP addresses (`:198`). So a config that `decoy scan` and `decoy init` write fails at compile. Under the V1 bar that is a function break.

### 1.2 Generate side: one Faker call per row, seeded per row

On the generate side these are Faker methods: `faker_type: uuid4`, `random_int`, `random_element`, `text`, `sentence`, `paragraph`, and the `provider` kind with `uuid`, `random_int_range`, `random_choice`, `lorem_text` (`providers_v2/_faker_adapter.py:60-66` maps them to `uuid4`, `random_int`, `random_element`, `text`). Unless pooled, they run in `PerRowFakerStream` (`generation/_column_streams.py:188-193`): `seed_instance(row_int("faker", i))`, then the provider, per row. `row_int` is one HMAC per row (`generators/derivation.py:354`). GEN-STREAM-ALL keeps `uuid4` in its never-pooled identifier class, so pooling does not fix uuid.

### 1.3 What the kernels already give

| Need | Existing kernel | Python reference |
|---|---|---|
| index in `[0, n)` keyed by value | `derive_index_batch` (`decoy-engine-native/src/arrow_ffi.rs:365`), the faker pool selection kernel | `determinism/_derive.py:318` `derive_index` |
| index keyed by global row position | the same kernel over `positional_key_array` (`execution/_positional_keys.py:53`), as `sample_faker_array_positional` does (`execution/native/_operator_step.py`) | `positional_pool_indices` (`execution/_strategies/_faker_positional.py`) |
| 128 keyed bits per value or position | `derive_batch` (`arrow_ffi.rs:281`), the `hash` kernel, with `truncate=32` hex | `execution/native/_crypto_reference.py:57` |

Both are chunk-independent by construction: the key is the value or the global row number, never a chunk-local index. NATIVE-THREADS-DEFAULT (`plan/native-threads-default`) S2 moves positional index draws onto an AES positional PRF through its `POSITIONAL_SITES` table, and S3 moves source-keyed index draws onto AES-CMAC. Because this row calls the same index helpers the faker pool path calls, those changes reach it with no extra work. The uuid draw stays on `derive_batch` (HMAC), which S3 does not change.

### 1.4 Measurements

Dell, 120,000 rows, from the probe run for this plan and the audit: per-row Faker on the generate side runs at about 8,600 rows/s for `email` (audit); per-row seeding costs one HMAC plus `seed_instance` per row. The keyed index kernel is the one the native faker pool route already uses at pool-select speed (12.6 ns/row for numpy indices plus `pc.take`, GEN-STREAM-ALL section 1). The probe's per-provider Faker timings were still running on the Dell when this plan was pushed; S1 records them in its gate report as the baseline for AT-9 and AT-10.

## 2. Established solutions

Search run: UUID layout for derived and random identifiers (RFC 9562 sections 5.4, 5.8 and 6.5); keyed pseudonym generation over a range (NIST SP 800-188 pseudonymization; format-preserving index maps); batch-invariant random streams (numpy `BitGenerator.random_raw`, counter-based generators); how fake-data tools draw these types (Faker `uuid4` uses `getrandbits(128)` then sets the version bits; Mimesis and SDV RDT `AnonymizedFaker` call per row).

- RFC 9562 defines version 4 as 122 random bits with the version nibble `0100` and the variant bits `10`. Faker's `uuid4` does exactly that from its seeded generator. Section 5.8 (version 8) is for custom layouts and 6.5 for name-based. This plan uses the version 4 layout over keyed pseudorandom bits, so the output reads as the same kind of value Faker gives today and passes common v4 validators. Owner question Q2 offers version 8.
- Keyed index over a fixed domain is the engine's existing DE-02 selection (`derive_index`), the NIST pattern. `random_int_range` is an index over `(max - min) // step + 1` values; `random_choice` is an index over the element list.
- For the generate side, one raw 64-bit word per draw (`BitGenerator.random_raw`) makes a draw a pure function of its position in the stream, so batching cannot change it. numpy's `Generator.integers` buffers 32-bit halves inside one call, so two calls do not equal one long call for small ranges; this plan does not use it.
- Lorem text has no identity to protect, so a pool of Faker paragraphs is enough. GEN-STREAM-ALL's certified pool set already holds `sentence` and `word`.

### Reuse inventory

- `derive_index_batch`, `derive_batch` and their Python references: the bits on the mask side. No new Rust.
- `positional_key_array`, `positional_pool_indices`, `sample_faker_array_positional`'s null handling: positional mode.
- `classify_provider` (`execution/native/_provider_class.py:68`): gains one class (section 5.2).
- Registry capabilities `_faker_cap` (`providers_v2/_real_registry.py`): the one place that marks a provider.
- Draw-site registry (`execution/native/_draw_sites_mask.py`, `_draw_sites_gen.py`) and `execution/native/_determinism_protocol.py:93`: new draw sites registered there.
- GEN-VECTOR-STREAMS S1 `next_array`; GEN-STREAM-ALL `pool_take` and the eligible set.
- FAKER-DEFAULT-POOL (`plan/faker-default-pool`): a pooled `lorem_text` with no `pool_size` gets 10,000.

## 3. Guarantee and non-goals

After this row:

1. Mask side: `strategy: faker` with `provider: uuid`, `random_int_range` or `random_choice` compiles and runs on every mask route (pandas full frame, chunked, sequential, out-of-core, unified slice) as a computed draw. No pool is built. The value for a row is a pure function of (mask key or job seed, namespace, source value) in deterministic mode, and of (job seed, namespace, global row number) in non-deterministic mode. It does not depend on chunk size, batch size, thread count or route. Nulls stay null in place.
2. Mask side: with the companion, the draw runs in the compiled kernel; without it, the Python reference gives the same bytes on the pandas route.
3. Mask side: `lorem_text` becomes poolable (Q1) and runs on the existing faker pool path. `address_full` stays refused at compile, as today.
4. Generate side: `faker_type: uuid4`, `random_int`, `random_element` and the `provider` kind with `uuid`, `random_int_range`, `random_choice` draw per batch from one raw-word stream per column. The output is deterministic per seed and independent of batch layout. This changes their bytes (section 10).
5. Generate side: `text`, `sentence`, `paragraph` and `provider: lorem_text` pool through GEN-STREAM-ALL's eligible set (`text` and `paragraph` added to group A, Q3).
6. One formatter module turns bits into values for both sides (section 5.1).
7. The scan and init recommendations for UUID and IP columns compile and run (AT-1).

Non-goals: `address_full` (composite; FAKER-NATIVE-WIDEN and the composite rows own it); `unique`, `match_source_cardinality` and `scale_source_cardinality` modes for the computed providers (refused at compile with a registered code); Faker kwargs other than `min`, `max`, `step` and `elements`; new Rust.

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | mask, deterministic, non-null value | keyed draw on the value |
| E2 | mask, non-deterministic (`cardinality_mode` absent or `reuse`) | keyed draw on the global row number |
| E3 | null source | null out in place; in positional mode the row still uses its row number (as `sample_faker_array_positional` does) |
| E4 | `random_int_range` with `max < min`, `step < 1`, or a count over 2**56 | compile refusal, new code `computed_draw_range_invalid` |
| E5 | `random_choice` with an empty or non-list `elements` | compile refusal, new code `computed_draw_elements_invalid` |
| E6 | `unique` or a cardinality mode other than `reuse` on a computed provider | compile refusal, new code `computed_draw_mode_unsupported` |
| E7 | companion absent | Python reference on the pandas route; native routes decline with their existing companion-absent reason |
| E8 | `address_full` | compile refusal, existing `NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND` (`plan/_checks.py:99`) |
| E9 | generate, any batch layout | same output (raw-word stream) |

### Routes

| Route | Mask side | Generate side |
|---|---|---|
| pandas full frame | `FakerStrategyHandler` (`execution/_strategies/_faker.py`) dispatches computed providers to the computed draw with the reference kernels | - |
| chunked native, unified slice | faker `OperatorSpec` (`execution/_operator_registry.py:205-214`) admits the three providers; the step dispatches on provider class | - |
| sequential | `_sequential_native_ops.py` faker admission reads the same spec | - |
| out-of-core | `out_of_core/_faker_native.py` admission reads the same class | - |
| streamed generation | - | `ComputedDrawStream.next_array` |
| whole-table generation (`synthesize.py`) | - | the same stream, drawn once for all rows |

### Codes

Three new plan codes (E4, E5, E6), registered once in `reasons/plan`. If ROUTE-LABEL-TRUTH has merged, its `kernel_less_per_row_faker` family loses `uuid`, `random_int_range` and `random_choice` (they now have a kernel) and its sentry sees the change; if it has not merged, nothing to do. Any route decline code this row needs goes in `reasons/route` once.

### FK shapes

- A computed-draw column that is an FK key in deterministic mode: the same value gives the same output on both sides of the key, because the draw is keyed on the value and namespace. Admitted where faker deterministic keys are admitted today.
- A computed-draw key in non-deterministic mode: positional draws break joins, so it is refused where positional faker keys are refused today (same check).
- A uuid key column with distinct inputs: collisions are possible at about n**2 / 2**123; recorded, not guarded.

### Fields

| Provider | Fields | Default |
|---|---|---|
| `uuid` | none | - |
| `random_int_range` | `min`, `max`, `step` | `_FAKER_DEFAULT_KWARGS` today (`providers_v2/_faker_adapter.py`) |
| `random_choice` | `elements` (list of scalars) | `("a", "b", "c")` (`_faker_adapter.py:76`) |
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

Principles that apply: one place per fact (the bit-to-value formatting; the provider class in the registry); dependency direction (the formatter sits in `generation/`, which `execution/` may import; generation never imports the execution kernels). Established patterns: RFC 9562 version 4 layout; DE-02 keyed index; raw-word streams.

### 5.1 One formatter

`generation/stream/_computed_draw.py`:

- `uuid_from_bits(bits: np.ndarray[uint8, (n, 16)]) -> pa.Array`: set byte 6 high nibble to 4 and byte 8 top bits to `10`, then format `8-4-4-4-12` lowercase hex with numpy (no per-row `uuid.UUID`).
- `int_from_index(index, *, lo, step) -> pa.Array` (int64).
- `choice_from_index(index, elements) -> pa.Array` (`pool_take` over the elements as one Arrow array).
- `ComputedDraw` spec: provider, parsed fields, count. Built and validated once at compile (E4, E5), and read by both sides.

### 5.2 Mask side

- Registry: `_faker_cap` gains `draw: Literal["pool", "computed"]`. `uuid`, `random_int_range`, `random_choice` become `computed`; `lorem_text` becomes poolable (Q1); `address_full` stays not poolable.
- `classify_provider` returns a new class `computed_native` for `draw="computed"`.
- `check_non_poolable_provider_with_pool_backend` keeps refusing `poolable=False` providers that are not computed (so `address_full`), and the new E4 to E6 checks run for computed ones.
- One function, `computed_mask_draw(source, *, spec, mode, key, namespace, row_offset, gate_positions, index_kernel, hash_kernel)`, in the existing faker positional strategy module family. Deterministic mode passes the source column to the kernels; positional mode passes `positional_key_array(row_offset, n, gate_positions=...)`. uuid takes `hash_kernel.derive_batch(..., truncate=32)` and decodes hex to bytes; the other two take `index_kernel.derive_index_batch(..., pool_size=spec.count)`. The pandas handler passes the reference kernels; native steps pass the compiled ones. Same function, so the same bytes.
- Namespaces: the selection namespace is the column namespace plus `/computed:<provider>`, so a computed draw never shares index material with a pool draw in the same namespace.
- Native admission: the faker `OperatorSpec` keeps one `provider_allowlist`; the three providers join it with their class. FAKER-NATIVE-WIDEN edits the same allowlist for poolable providers; whichever merges second rebases on the other's list.

### 5.3 Generate side

`ComputedDrawStream` in `generation/stream/_computed_draw.py`, built by `_faker_stream` (`generation/_column_streams.py:330`) and by the `provider` kind's builder for the computed providers, before the pool check:

- One `np.random.PCG64(ctx.base_int("draw"))` bit generator per column. Each value takes a fixed number of raw 64-bit words: uuid two, the others one. Index is `word % count` (bias at most `count / 2**64`).
- `next_array(offset, size)` draws `size * words` raw words in order. A batch boundary cannot change a value.
- Whole-table generation calls the same stream for all rows at once.

### 5.4 Lorem

Mask: `lorem_text` with `poolable=True` uses the existing pool path, so FAKER-DEFAULT-POOL and the native pool select (once FAKER-NATIVE-WIDEN admits it) apply. Generate: `text` and `paragraph` join GEN-STREAM-ALL group A as certified pairs (its harness checks they reproduce under a seed).

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| formatter and `ComputedDrawStream` | `generation/stream/_computed_draw.py` (new, about 170 lines) | GEN-STREAM-ALL's row "Generation streamed batch assembly" | `generation/stream/_batches.py` |
| `computed_mask_draw` | `execution/_strategies/_faker_positional.py` (grows about 60 lines; `_strategies/` is at its freeze of 28, so no new module) | "Masking strategy handler" | `_faker.py` |
| provider class | `execution/native/_provider_class.py` | "Native companion bridge" | - |
| registry flag | `providers_v2/_real_registry.py`, capability type | "Providers" | - |
| compile checks E4 to E6 | `plan/checks/_computed_draw.py` (new) | "Plan compile and checks": new checks in `plan/checks/` | `plan/_checks.py:99` |
| codes | `reasons/plan` (three codes) | reasons | - |
| draw sites | `execution/native/_draw_sites_mask.py`, `_draw_sites_gen.py` | "Native companion bridge" | existing sites |
| tests | `tests/unit/generation/stream/test_computed_draw.py`, `tests/unit/execution/strategies/test_faker_computed.py`, `tests/unit/plan/checks/test_computed_draw.py` | "Unit tests" | - |

If `_faker_positional.py` would pass 600 lines, `computed_mask_draw` goes into a new `execution/_strategies/faker/` family package (CODEMAP: "next family in `execution/_strategies/<family>/` (target)") and S1 moves `_faker_positional.py` there with it.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | compile refusals E4 to E6 could echo `elements` or bounds | messages name the field, never its value | AT-7 | put `elements` into the E5 message (AT-7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no pool, no reservation for computed draws | n/a | n/a |
| 3 | State and concurrency | generate stream state across batches; kernel threads | one bit generator per column; kernels are thread-invariant (existing proof) | AT-4, AT-5 | create the bit generator per batch (AT-4 red) |
| 4 | Route parity and silent fallback | five mask routes | one `computed_mask_draw` with injected kernels; declines carry registered reasons | AT-2 | M3 |
| 5 | Referential integrity | computed key columns | deterministic keys keyed on value; positional keys refused where today | AT-6 | M4 |
| 6 | Untrusted producer | compiled kernel output | existing `_checked_batch` length and null checks; hex length checked before decode | AT-3 | skip the hex length check (AT-3 short-output cell red) |
| 7 | Check then use | none | N/A: no file or path | n/a | n/a |
| 8 | Weak tests | value tests that pass for any keyed draw | AT-2 compares routes to each other and to frozen vectors; AT-5 compares layouts | AT-2, AT-5 | M1 |
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
| 6 | No reaching into private modules | `execution/` imports the formatter through `generation.stream`'s public names | import-linter |
| 7 | No hidden CI failures | companion-absent leg must run the reference path tests | CI review |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M6 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | the faker `provider_allowlist` | AT-2 walks every provider in the allowlist |
| 11 | No raised caps | `_strategies` freeze 28, `generation/` 25, module size | no new module in either; sizes listed |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | The scan starter for a UUID column and the CLI init config for UUID and IPv4 columns compile and run end to end | `NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND` today | S1 |
| AT-2 | Route parity: the three providers, deterministic and positional, string and int sources with nulls, give equal output on pandas (reference kernels), unified slice, chunked (several chunk sizes), sequential and out-of-core | refused today | S1 (pandas, chunked, unified), S2 (sequential, out-of-core) |
| AT-3 | Frozen vectors: fixed key, namespace and inputs give committed uuid, int and choice outputs; uuid strings match `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z` | no draw today | S1 |
| AT-4 | Chunk and thread invariance (mask): chunk sizes 1, 7, 65,536; `native_threads` 1 and 4; `when:` gate positions | refused today | S1 |
| AT-5 | Batch invariance (generate): layouts `[1]*7`, `[7, 4096, 3]`, one batch, and the whole-table path give equal columns | per-row Faker today has the property too; fail-before is AT-10 | S3 |
| AT-6 | FK: a deterministic `uuid` key column masks parent and child to equal values; a positional key column is refused with the existing reason | refused today | S1 |
| AT-7 | Compile refusals E4, E5, E6 with `True`, `"5"`, `5.0`, empty and non-list `elements`; messages value-free; cause and context None | no codes today | S1 |
| AT-8 | `address_full` is still refused; `lorem_text` now pools and runs | `lorem_text` refused today | S2 |
| AT-9 | Speed, `perf`, Dell: masked `uuid` over 1,000,000 rows on the chunked native route at or under 200 ns per row | refused today | S1 |
| AT-10 | Generate speed and byte change: `uuid4` over 1,000,000 rows at or under 100 ns per row; the output differs from the per-row Faker golden (proves the new path ran) | per-row Faker today | S3 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | uuid formatter leaves the version nibble unset | AT-3 |
| M2 | positional mode keys on the chunk-local index instead of the global row | AT-4 |
| M3 | the pandas handler uses `random.Random` instead of the reference kernel | AT-2 |
| M4 | deterministic mode keys on the row number | AT-6 |
| M5 | `int_from_index` ignores `step` | AT-3 |
| M6 | generate stream uses `Generator.integers` per batch | AT-5 |

## 10. Frozen contracts and byte changes

Mask side: no byte change. These configs were refused, so there is no earlier output.

Generate side, byte change (pre-GA correction, one `Breaking:` line in the changelog and a note in `docs/compatibility-contract.md` section 1):

- `faker_type: uuid4` and `provider: uuid`: values change; still RFC 9562 version 4 strings.
- `faker_type: random_int` and `provider: random_int_range`: values change; same range and step.
- `faker_type: random_element` and `provider: random_choice`: values change; same element set.
- `faker_type: text`, `paragraph` and `provider: lorem_text`: values change from per-row text to pool picks (via GEN-STREAM-ALL).

Every other generate type keeps its bytes. FAKER-MIGRATE's output lock lists `uuid4`, `random_int` and `random_element` cells for the adapter; S3 regenerates those cells with this row's change named in the lock diff.

## 11. Pre-mortem

- NATIVE-THREADS-DEFAULT S2 or S3 merges first and changes the index helpers. This row calls the same helpers, so it follows; AT-3 vectors are regenerated once in the later of the two merges, and that merge names the change.
- A user relies on `random_int` returning a Python int on the pandas route. The output column is int64 on every route; AT-2 compares types.
- A uuid column feeds a database UUID type that rejects version 4 from non-random sources. No validator can tell; noted only.
- FAKER-NATIVE-WIDEN rewrites the allowlist shape. Section 5.2 names the rebase.
- The positional namespace suffix collides with a user namespace ending in `/computed:uuid`. The registry refuses namespaces containing `/computed:` (one check in S1).

## 12. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | registry flag and class; compile checks E4 to E6 and codes; formatter; `computed_mask_draw`; pandas handler, unified slice and chunked native admission; draw sites; AT-1 to AT-4, AT-6, AT-7, AT-9 | M: about 350 lines, 400 lines tests | Codex and Dennis; T2 on faker, plan and native selections |
| S2 | sequential and out-of-core admission; `lorem_text` poolable; AT-2 rest, AT-8 | S: about 100 lines, 150 lines tests | Codex |
| S3 | generate side: `ComputedDrawStream`, wiring in `_faker_stream` and the provider kind; GEN-STREAM-ALL group A gains `text`, `paragraph`; changelog `Breaking:`; FAKER-MIGRATE lock cells; AT-5, AT-10 | M: about 200 lines, 250 lines tests | Codex and Dennis; depends on GEN-VECTOR-STREAMS S1 and GEN-STREAM-ALL S1b |

S1 is the V1 function fix and should go first; it does not wait for the generation rows. All three fit before 2026-12-15 if GEN-STREAM-ALL S1b and GEN-VECTOR-STREAMS S1 merge by early December.

## 13. Open questions for the owner

- Q1: Mask-side `lorem_text`: make it poolable (recommended, uses the existing pool path) or keep refusing it?
- Q2: uuid layout: version 4 over keyed bits (recommended, matches today's Faker output kind) or RFC 9562 version 8?
- Q3: Add `text` and `paragraph` to GEN-STREAM-ALL group A (recommended) so generate-side lorem pools?
- Q4: The generate-side byte change for `uuid4`, `random_int`, `random_element` (section 10) is accepted under the 2026-11-22 direction? Recommended: yes.
- Q5: S1 is a V1 function fix (scan and init write a config that fails). Put S1 in the V1 closing set ahead of the rest of the row? Recommended: yes.
