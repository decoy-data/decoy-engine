Status: plan

# GEN-NONFAKER-DRAWS S3: computed draws on the generate side (uuid, integer range, element choice)

Owner: Cam. Author: Opus. Date: 2026-11-25. Revision 3 (Dennis R1 and Codex R1 folded). Row: GEN-NONFAKER-DRAWS. Parent plan: revision 4 on branch `plan/gen-nonfaker-draws` ("rev 4" below), sections 5.3, 8, 10 and 12. S1a is merged (#775). S2 is PR #797, open at `2b98183ba`, in gate. S1b (mask-side admission on the remaining native routes, if the closing set keeps it) is not built and is not a dependency of S3.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md` (named byte change), `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` "Where Things Go".

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine at `origin/main` `2b8a47fbe`. `GSA` is the GEN-STREAM-ALL plan (`plan/gen-stream-all`); its S1a is PR #813, open at `abbb6241d`. `GVS` is the GEN-VECTOR-STREAMS plan (`plan/gen-vector-streams`); its S1 is not built.

Risk: R2. A named byte change on the generate side, a new draw path on three generation call sites, and a widening of window admission for two Faker types. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis.

## 1. Frame

On the generate side, `faker_type: uuid4`, `faker_type: random_int`, `faker_type: random_element` and the provider aliases `uuid`, `random_int_range` and `random_choice` still call Faker once per row, after `seed_instance(row_int("faker", i))`. S1a moved the argument contract to `providers_v2/_faker_draw_contracts.py` and the formatters and `ComputedDrawSpec` to `generation/pool/_computed_draw.py`. Nothing on the generate side calls them yet.

Re-reading main for this plan found three facts rev 4 does not state:

1. There are three Faker generation call sites, not two. `generation/synthesize.py:455` `_faker` (whole table), `generation/_column_streams.py:331` `_faker_stream` (streamed batches, called at `:298`), and `generation/window.py:200-201`, where `generate_rows` builds `PerRowFakerStream` directly inside `_positional`. The window contract is that `generate_rows` gives the same bytes as a full run for its Class A columns. If S3 changes only the first two sites, a window over a uuid column returns per-row Faker values while the full run returns computed values. That is a function break.
2. The provider kind is whole-table only. `generation/synthesize.py:388` calls `provider_column_values` (`generation/kinds/_provider.py:56`). The streamed and window paths do not admit `kind: provider`.
3. Generate provider options are only `provider`, `locale`, `field` and `group` (`config/_generate_options.py:405-407`). A generate `provider:` column cannot pass draw arguments, so a provider computed draw always uses the contract defaults (`random_int_range` 0 to 9999 step 1, `random_choice` the contract's default elements). The rev 4 row "any extra arg stays on adapter batch" cannot happen and is dropped.

Also corrected from rev 4:

- `faker_type: uuid4` is admitted with no `faker_kwargs` at all. Rev 4 named a `cast_to=str` form, but no `cast_to` handling exists in `src/`, and `parse_computed_draw` (`generation/pool/_computed_draw.py:142`) already refuses any argument for the uuid family.
- The Faker output lock (`scripts/faker-determinism/output_lock.json`) digests Faker method output, not engine generate output. S3 does not call Faker for these cells, so no lock diff is expected. If one appears, the builder stops and reports it.
- `text` and `paragraph` become pool picks through the harness-certified locale-pair set `POOL_ELIGIBLE_LOCALE_PAIRS` (`generation/_faker_pool.py:79`, embedded from `scripts/faker-determinism` `certified_pairs.json`), which the GSA group A work in GSA S1b extends. A pair is never added by inference: it needs its own harness certification. Codex R1 P1-3 found that certifying a pair makes the column `pooled_faker` (`generation/_window_admission.py:434-440`), which is Class B, so `generate_rows` would refuse a table whose `text` or `paragraph` window works today (both have width caps, `generation/_bounds.py:86-88`). That turns a working public route into a refusal. They are therefore deferred out of this plan (section 12 OWNER CALL).
- Window and streamed admission price Faker columns through `faker_payload_bound` (`generation/_bounds.py:107`). It returns `None` for any `faker_kwargs` (only `pyint` reads kwargs, `:118-125`) and has a cap only for `uuid4` among the three methods (`:81`). `_check_faker` (`generation/_window_admission.py:271-287`) refuses on `None` with `CODE_UNBOUNDED`. So without a width rule, `random_int` and `random_element` can never reach the window, and guarantee 1 would fail on real entry points (Dennis R1 P1-3). S3a adds the width rule.

V1 bar: this row is in the 1.0 set for speed (rev 4 section 1.4: per-row Faker is the slowest generate path for these types). S3a must not break the window contract or any caller's output type. Those two would be function breaks.

## 2. Guarantee and non-goals

S3a guarantees:

1. Each admitted generate column (section 5.2 table) takes the computed path on every call site that can reach it: whole table, streamed batches and window for `faker_type`; whole table for `provider`. No admitted column calls `Faker.seed_instance` or the adapter's batch call.
2. For a stable root (any `determinism` mode other than `fresh`, which draws a new root per invocation, `generators/derivation.py:297-300`), a value depends only on (job root, column identity, row number). Any batch layout, the whole-table path and any `generate_rows` window that is admitted today or by S3a give the same value at the same row. A column with positive `null_probability` stays Class B for windows (`generation/_window_admission.py:430-431`), as today.
3. Output types do not move: `faker_type: random_int` keeps the type numeric typing plans today (int64 when nothing else is planned); `faker_type: random_element` emits text before any declared output cast; every `provider:` column stays string, mixed scalar choices included.
4. Columns outside the admitted shapes keep today's bytes: other kwargs, `unique: true`, a custom provider in the provider snapshot that overrides the Faker method, and every other Faker type.
5. Admitted columns change bytes. This is a named pre-GA change with one `Breaking:` line and a note in `docs/compatibility-contract.md` section 1.

S3b (`text` and `paragraph` pool picks) is deferred: it would turn working windows into refusals (section 1). This plan makes no claim for those types; they keep today's bytes and routes.

Non-goals: the mask side (S1a, S2, S1b); `lorem_text` (S2); formula expressions that call `faker.uuid4()` and the like (they run through `ColumnGenerator._eval_formula_inline`, reached from `generation/_synthesize_derived.py:95`, and keep their per-row bytes); the V1 mirror `generators/columns.py::ColumnGenerator._generate_faker_column`, which no generate Faker column reaches (Dennis R1 checked every caller; section 5.3); weighted or dict `random_element`; `unique: true` columns; a provider-argument option for generate configs; removing the per-row V1 mirror in `generators/columns.py`; Lemire unbiased bounded integers (section 3).

Size:

- S3a: one new module `generation/stream/_computed_draw.py` (about 100 lines), about 70 changed lines over `synthesize.py`, `_column_streams.py`, `window.py`, `_window_admission.py`, `_bounds.py`, `kinds/_provider.py`, `generators/derivation.py` and `execution/native/_determinism_protocol.py`, one draw-site row (about 20 lines), one sentry (about 120 lines), and about 300 lines of tests. New public names: `ComputedDrawStream` and `open_computed_stream` in `generation.stream`; `COMPUTED_DRAW_FAMILY` in `generators.derivation`.
- S3b: deferred, no size.

## 3. Established solutions

Search run on 2026-11-25:

- Online: NumPy random docs for `PCG64`, `PCG64.advance` and `BitGenerator.random_raw`; the PCG paper (O'Neill 2014) on jump-ahead; RFC 9562 section 5.4 (UUID version 4 layout); Lemire, "Fast random integer generation in an interval" (2019); the JAX and NumPy guidance on counter-based and seekable streams.
- Codebase: `generation/pool/_computed_draw.py` (S1a formatters), `generators/derivation.py:219-222` and `:335-354` (seeding families), the GVS plan (`next_array`), the GSA plan (`pool_take`, group A), `generation/window.py` (the window contract), `execution/native/_draw_sites_gen.py` (draw site registry).

Findings and the source each part follows:

- Seekable stream: `PCG64.advance(delta)` jumps the state forward in O(log delta). With a fixed number of raw words per value, value i is a pure function of (seed, i). This is the counter-based pattern the GVS plan already picked for `next_array`. S3a follows it.
- Words to uuid: RFC 9562 section 5.4. `uuid_from_bits` (S1a) sets the version and variant bits. S3a feeds it 16 bytes per value: two raw uint64 words, little-endian, `words.astype("<u8").view(np.uint8).reshape(n, 16)`. The byte order is stated so a big-endian host gives the same strings.
- Words to an index: `word % count`. Bias is at most `count / 2**64`; with the S1a cap `_COUNT_MAX = 2**56` it is at most 1/256 for the largest range, and below 1e-15 for ranges up to 10,000. Lemire's method removes the bias but needs rejection, which breaks the fixed words-per-value rule and so breaks seekability. The bias is recorded as a known issue, not fixed.
- Family separation: `GenDeriveContext.family_bytes(label)` already gives independent keys per label (`POOL_BUILD_FAMILY`, `POOL_SELECTION_FAMILY`). S3a adds one label beside them.

The only custom code is the wiring of a stream into the three sites. Everything else reuses S1a names, NumPy and GVS's stream method.

## 4. Reuse inventory

- `generation.pool`: `computed_draw_spec` (`_computed_draw.py:182`), `uuid_from_bits` (`:194`), `int_from_index` (`:234`), `choice_from_index` (`:247`).
- `providers_v2.faker_draw_contract` (`providers_v2/_faker_draw_contracts.py:93`): accepts the alias or the Faker method name, so one lookup serves `faker_type` and `provider` columns.
- `generators/derivation.py`: `GenDeriveContext.family_bytes` (`:335`), the family constants (`:219-222`).
- `generation/kinds/_provider.py`: `draw_path` (`:45`), `_draw` (`:102`) with its live capability and locale check, `provider_generate` (`:63`) with `_as_text` (`:97`) and its value-free error boundary.
- `internal/faker_setup.py` `_coerce_to_str` (`:438-445`): the text conversion per-row Faker applies to every value today.
- `execution/native/protocol/providers_gen.py`: the generation-side draw-site provider classes, where the new `gen.faker_computed` provider class goes (Codex R2: `_draw_site_providers.py:43` says generation providers live there). `execution/native/_draw_site_providers.py` builds the one-provider-per-site registry, registers the new class and keeps the import-time totality check (`:282-290`).
- `providers_v2/_registry.py`: the new `is_stock_binding` predicate, beside `override`, since the registry owns which adapter is bound.
- `generation/_numeric_typing.py`: the planned type for `faker_type: random_int`, applied by the existing post-pass.
- `ColumnStream.next_batch(offset, size)` (the protocol `window.py:147-153` and `_column_streams.py` already use) and the existing typing post-pass (`restore_declared`, `generation/_numeric_typing.py:391-405`; `window.py:333-336`).
- `generation/_bounds.py` `faker_payload_bound` (`:107`), extended, not copied.
- GSA S1a (#813): the `generation/stream/` package and the Arrow batch assembler.
- `execution/native/_draw_sites_gen.py` and its sentry `tests/native/test_draw_sites_assembly.py`.

## 5. Design

### 5.1 Choke point

The rule: "a generate column whose Faker type or provider is a computed draw contract, in an admitted shape, takes the computed path". It has four sites: `synthesize._faker`, `_column_streams._faker_stream`, the window builder in `window.py`, and the provider kind inside `kinds/_provider._draw`, reached from both `provider_column_values` and the exported `provider_generate` (`generation/kinds/__init__.py:81`).

All four sites call `open_computed_stream` in `generation.stream`. It constructs a stream only when `computed_spec_for` returns a spec. Bounds and layout planning call that same pure admission function. For a `faker_type` column, pass the run's provider snapshot, use the existing `has_custom_faker_override` lookup (including live lookup when the snapshot is absent), and require the exact contract method name. The S1a parser also recognizes aliases, but `faker_type: uuid` and `random_choice` take the existing fallback. Pass `planned_output_type=None` and leave final typing to the post-pass.

For a provider column, pass the effective `ProviderRegistry` from `_draw` through the stream opener to admission. Require the contract's provider name, live `caps.draw == "computed"` and the public `providers_v2.is_stock_binding(registry, provider)`. Define that predicate once beside `ProviderRegistry.override` (`providers_v2/_registry.py:122`), and export it from the package. A name absent from the default catalog is non-stock. For a default name, compare its effective adapter with the default adapter by object identity and exclude names in `providers_v2.custom_provider_names()`. A fresh adapter of the same class is a replacement. The out-of-core pool retains its string allowlist and replaces its class comparison with this predicate (`execution/out_of_core/_faker_pool.py:46-56,198`). Its measured-size check still runs after construction.

In `kinds/_provider._draw`, check the effective locale first, then try the computed stream. If admission returns no stream, continue through the existing `draw_path(caps)` pool, keyed or batch branches. The three stock computed catalog rows are non-poolable Faker providers, so a callback with unchanged capabilities reaches the seeded adapter batch. Compile-time support checking continues to use `draw_path` (`plan/checks/_generate_providers.py:44`). Both generation entry points retain `provider_generate`'s text conversion and value-free error boundary.

The guard is `tests/sentry/generation/test_computed_generate_choke_point.py`. It derives its inventory from `FAKER_DRAW_CONTRACTS` and runs every contract row through every site that can reach it (whole table, streamed, window for `faker_type`; whole table for `provider`). For each run it patches `Faker.seed_instance`, `PerRowFakerStream.__init__` and the adapter batch call to raise, and asserts the run completes and that the outputs of all sites are equal. A second part walks the AST of the named site functions (`synthesize._faker`, `_column_streams._faker_stream`, the window builder in `window.py` that constructs `PerRowFakerStream`, and `kinds/_provider._draw`) and fails if one constructs `PerRowFakerStream`, calls `seed_instance` or calls the adapter batch without first calling `open_computed_stream`. It also fails if any other function in those modules, except `PerRowFakerStream`'s own methods (`_column_streams.py:186,191`), constructs `PerRowFakerStream`, so a new site is caught. The rule names its scope; there is no free-form allowlist.

Mutations that must turn the guard red:

- M-1: `window.py` builds `PerRowFakerStream` for a uuid column (the realistic bypass: a new site copies the old line).
- M-2: the provider admission function declines a stock computed capability.
- M-3: `synthesize._faker` skips `open_computed_stream`.

### 5.2 Admitted shapes

| Caller and type | Admitted | Output type | Stays on today's path |
|---|---|---|---|
| `faker_type: uuid4` | no `faker_kwargs` | string | any kwarg |
| `provider: uuid` | stock binding (`is_stock_binding`) | string | an override or a registered callback |
| `faker_type: random_int` | strict int `min`, `max`, `step` per the contract, or none | the type numeric typing plans (int64 when none) | float, bool or string bounds, unknown kwargs, a shape S1a refuses |
| `provider: random_int_range` | stock binding, with contract defaults | string via `_as_text` | an override or a registered callback |
| `faker_type: random_element` | non-empty list or tuple of scalars with one Arrow type | string before any declared output cast | string, dict or weighted, empty, mixed-type, unknown kwargs |
| `provider: random_choice` | stock binding, with the contract's default elements | string via `_as_text` | an override or a registered callback |

For every caller: `unique: true` stays on today's path (the unique retry loop is not partitionable, `_draw_sites_gen.py` `gen.faker_unique`), and so does a column whose provider snapshot overrides the Faker method (a custom provider named `uuid4`, `random_int` or `random_element`). Locale does not matter for these three methods, so a column's locale does not change admission.

### 5.3 The stream

`ComputedDrawStream` (in `generation/stream/_computed_draw.py`) implements the existing `ColumnStream` protocol, `next_batch(offset, size) -> list` (Dennis R1 P1-4), which the window path (`window.py:147-153`) and `_faker` consume. It also implements the optional `next_array(offset, size)` that #813 adds (`#813:generation/stream/_batches.py`, used when the stream supports it), so the streamed route keeps the values as an Arrow string array. Both methods share one draw function; `next_batch` does not go through one combined array (see internal chunking below). `ComputedDrawStream.supports_array` is `True`, because #813's assembler takes the array route only when that property is `True` (`#813:generation/_column_streams.py:289`, `generation/stream/_batches.py:65`, `:97`); implementing `next_array` alone would leave production on the list path (Codex R2 P1-5). No GVS work is needed.

- One bit generator per column: `np.random.PCG64(int.from_bytes(ctx.family_bytes(COMPUTED_DRAW_FAMILY), "big"))`. `COMPUTED_DRAW_FAMILY = "faker_computed_draw"` sits beside `POOL_SELECTION_FAMILY` (`generators/derivation.py:222`). It is a `family_bytes` label like the pool labels, not a new `GEN_FAMILIES` entry, so the null-mask and per-row families do not change.
- Words per value: uuid 2, integer and choice 1.
- The draw: copy the start state, `advance(offset * words)`, `random_raw(size * words)`, format with the S1a function for the spec's family, and return an Arrow string array. uuid: the pure helper `_words_to_uuid_bytes(words)` does `words.astype("<u8").view(np.uint8).reshape(n, 16)`, then `uuid_from_bits`. Integer: `int_from_index`. Choice: `choice_from_index`. Every value is text, for both callers. Per-row Faker returns text today for all three methods (`_coerce_to_str`, `internal/faker_setup.py:438-445`): `random_element(elements=[1, 2])` gives `['2', '2']` and plans Arrow `string` (`generation/_admission.py:270-275`), and #813 builds the streamed array with that planned type (`#813:generation/stream/_batches.py:108-115`). So integers and choices are formatted with `str()` exactly as `_coerce_to_str` does, and provider values pass through `_as_text` in `provider_generate`.
- Internal chunking uses one row-limit calculation for list draws and table layouts. Cap each computed array at 1,048,576 rows and at the Arrow string payload ceiling (signed int32 maximum). Divide the byte ceiling by `max(1, computed_value_width(spec))` and take the smaller row cap. This accounts for variable-width choices as well as 36-byte uuids. Use lowerable limits for tests. `next_batch` extends its list from individual chunks at absolute offsets. Each `next_array` call receives one bounded span and returns one plain `pa.Array`. #813 passes it to `RecordBatch.from_arrays`, which rejects a `ChunkedArray` (`generation/stream/_batches.py:97-120` on #813).
- For each eligible table, use the smallest cap among its admitted computed columns, including when the ledger is unbounded. Apply it in #813's existing `_make_layout` and `_Layout.sizes` (`generation/_streamed.py:129-157`). Lazily subdivide each requested size for all columns together, preserving total rows, order, zero sizes in supplied partitions, and the bookkeeping charge for the original sequence. Use the largest effective piece for preflight and reservations. Tables without computed columns keep their requested layout. The assembler consumes the same layout for streamed and resident execution.
- Typing has one owner, the existing post-pass. The stream returns the same value kind (text) per-row Faker returns today, so `restore_declared` (`generation/_numeric_typing.py:391-406`, `window.py:333-336`) and the `output_type` cast behave exactly as now, including when numeric typing is suppressed. The stream never builds an int, decimal or other planned type. `int_from_index` returns int64 (`generation/pool/_computed_draw.py:234-244`); the stream converts it to text, so it does not take `planned_output_type`.
- Width: `computed_value_width(spec) -> int` beside the stream, in UTF-8 bytes of the text form, which is what #813 measures (`#813:generation/stream/_batches.py:40-47`): uuid 36, integer the larger of `len(str(v).encode())` for `lo` and the top value, choice the largest `len(str(e).encode())` over the elements (Codex R1 P1-4: counting characters prices `"😀"` at 1 byte, not 4). `faker_payload_bound` (`generation/_bounds.py:107`) calls `computed_spec_for` first and returns this width for admitted shapes, before its kwargs rule. Window and streamed pricing then admit `random_int` and `random_element` like `uuid4`.
- No per-row state, so out-of-order batches and windows give the same values.
- Null handling is unchanged: `null_probability` is a separate post-pass on the `np` family.

Window: `_window_admission.py:439` returns `"pooled_faker"` (Class B) for pooled columns. A computed column is Class A, because its value is a pure function of (seed, i). `window.py` calls `open_computed_stream` before the `PerRowFakerStream` branch and wraps the result in `_positional` like the other Class A streams.

Draw sites: S3a adds a `gen.faker_computed` row to `execution/native/_draw_sites_gen.py` (family `numpy_pcg64`, identity `row_index`, partitionable true) and, in the same commit, a dedicated provider class in `execution/native/protocol/providers_gen.py`, registered in `execution/native/_draw_site_providers.py`, whose draw calls the production `ComputedDrawStream` draw function (no copy). The module raises at import when a catalogued site has no provider (`:282-290`), so the two land together. The family count in the assembly sentry moves with them, and edits the `gen.faker_per_row` note to say the per-row site no longer serves the six admitted shapes. `GEN_KIND_TO_SITE` is `dict[str, str]` (`execution/native/_determinism_protocol.py:116`), so its `"faker"` value stays `"gen.faker_per_row"` and gets a trailing comment `# + gen.faker_computed`, the same form as the mask line at `:99`.

V1 mirror, settled: no generate Faker column reaches `generators/columns.py::ColumnGenerator._generate_faker_column`. Formula paths (`generation/_referenced_formula.py:80`, `generation/_synthesize_derived.py:95` and `:246`) reach only `_eval_formula_inline`. The mirror note keeps naming that function for the per-row site, and S3a does not edit it.

### 5.4 Placement

| New file | Directory | CODEMAP "Where Things Go" row | Beside |
|---|---|---|---|
| `_computed_draw.py` | `src/decoy_engine/generation/stream/` | "Generation": `src/decoy_engine/generation/`, by generation concern; the `stream/` sub-package is created by GSA S1a | `generation/stream/_batches.py` (GSA S1a) |
| `test_computed_generate_choke_point.py` | `tests/sentry/generation/` | "Sentry test": `tests/sentry/`; CODEMAP lists `tests/sentry/generation/` for generation choke points | `test_faker_draw_contract_choke_point.py` |
| `test_computed_draw_stream.py` | `tests/unit/generation/stream/` | "Generation": tests in `tests/unit/generation/` | GSA S1a stream tests |
| `gen-nonfaker-draws-s3.md` | `changelog.d/` | "Changelog fragments" (`CODEMAP.md:302`): `changelog.d/<slice-slug>.md` | `changelog.d/gen-nonfaker-draws-s1.md` |

The module and its consumer land in the same slice (S3a), so no consumer gap exists for `proportionality.md`.

### 5.5 Design notes

- One place per fact: the argument contract stays in `providers_v2`, the formatting in `generation.pool`, the stream and the admission in one module. No site restates admission.
- Established pattern: a seekable counter-style stream (PCG64 advance), RFC 9562 layout (section 3).
- Dependency direction: `generation.stream` imports `generation.pool` and `providers_v2` through their public names. It imports nothing from `execution`.
- House style: `open_computed_stream` takes the column, the context and a keyword caller kind; no flag argument switches its behavior.

## 6. Behavior and failure modes

| Case | Before | After |
|---|---|---|
| `faker_type: uuid4`, no kwargs, any route | per-row Faker uuid | computed uuid v4; same on every route and window |
| `faker_type: random_int`, `min: 1, max: 6` | per-row Faker text, then the post-pass type | computed text of an int in [1, 6], then the same post-pass type |
| `faker_type: random_element`, `elements: [1, 2, 3]` | per-row Faker pick as text (`'1'`, `'2'`, `'3'`), then the post-pass type | computed pick as the same text, then the same post-pass type |
| `faker_type: random_element`, mixed `[1, "a"]` | per row | per row, unchanged bytes |
| `provider: random_choice` | adapter batch, string | computed string for the stock binding, adapter output as text for a replacement or callback |
| `faker_type: uuid4`, `unique: true` | per-row unique path | unchanged |
| custom provider overriding `uuid4` | custom function per row | unchanged |
| `generate_rows(start, stop)` over a uuid column | per-row values, equal to the full run | computed values, equal to the full run |
| a pre-S3 golden for these types | committed | regenerated with the change named |

Failure modes the plan checks for:

- F1: window and full run disagree (fact 1 in section 1). AT-S3-2 compares every window cut with the full run.
- F2: a planned output type is lost, for example `random_int` with a decimal(2) plan becomes int64. AT-S3-4 pins both cells from `tests/unit/generation/kinds/test_gen_types_e2_output.py:109-110`.
- F3: the computed stream shares bits with another family. It uses its own `family_bytes` label; AT-S3-11 checks the null mask of an admitted nullable column is unchanged.
- F4: parity tests with goldens for these types fail. Expected for admitted shapes. The builder regenerates each one and lists it in the PR body. A golden for a non-admitted shape (for example `tests/parity/test_phase_f_f2_mixed_sweep.py:364`, `uuid4` with `unique: true`) must not change; if it does, S3a stops.
- F5: GSA S2 (provider and lookup streams) edits `kinds/_provider.py` at the same time. Whichever merges second rebases; section 11.

## 7. Acceptance tests

Fail-before is recorded on the parent commit.

| ID | Slice | Test | Fail-before |
|---|---|---|---|
| AT-S3-1 | S3a | At a stable root, compare each partition with one batch over the same rows: seven single-row batches and an irregular [7,4096,3] layout on their respective fixtures, for each reachable route. Repeat an absolute offset out of order on the computed stream. With the row cap lowered to 1,000 and payload ceiling to 40,000 bytes, compare one 4,500-row uuid list draw and five bounded `next_array` calls (four of 1,000, then 500) against the unsplit reference values. Assert each call returns a plain string array within the byte ceiling. | AT-S3-3 distinguishes computed bytes from per-row Faker |
| AT-S3-2 | S3a | window parity: for each admitted `faker_type` shape (including `random_int` with `min`/`max` and `random_element` with a list), window admission passes (no `CODE_UNBOUNDED`), `_window_admission` reports Class A, and `generate_rows(offset=a, count=b-a)` for cuts (0, 1), (5, 4100), (n-3, n) equals the full run's rows (non-nullable columns, stable root) | `random_int` with kwargs is refused `CODE_UNBOUNDED` today; a computed full run against a per-row window differs (M-1) |
| AT-S3-3 | S3a | rev 4 AT-10: a fixed seed gives a committed golden from `ComputedDrawStream`, which differs from the per-row golden (no timing in this cell). Speed is a separate gate measurement, not a CI test: `uuid4` over 1,000,000 rows through `next_array` on the streamed route, at or under 100 ns per row on the Dell, recorded in the PR with the command. A miss fails the gate. The whole-table list route is measured and reported, not gated | per-row Faker today |
| AT-S3-4 | S3a | rev 4 AT-11: one value and Arrow-schema golden per row of section 5.2, including plain `random_int` int64, `random_int` with a decimal(2) plan (`tests/unit/generation/kinds/test_gen_types_e2_output.py:109-110`), homogeneous int `random_element` (values and Arrow type `string`, as today), a `random_int` read by a text-dependent consumer, and `provider: random_choice` as string; each `faker_type` cell asserts the same Arrow schema on the whole-table, streamed and window sites | no computed path today |
| AT-S3-5 | S3a | non-admitted shapes keep their outcome: mixed `random_element`, `unique: true` uuid4, a custom provider override, and `word` compare bytes with the parent commit; `random_int` with float bounds compares the parent's outcome, values or exception, on each supported interpreter | guards F2, F4 |
| AT-S3-6 | S3a | choke point sentry (section 5.1) passes and M-1 to M-3 each turn it red | no computed path today |
| AT-S3-7 | S3a | `tests/native/test_draw_sites_assembly.py` passes with the new `gen.faker_computed` row | row missing |
| AT-S3-8 | S3a | uuid strings match `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z`; every emitted value is text; for `random_int`, `int(v)` is in `[min, max]` with `(int(v) - min) % step == 0`; for `random_element`, `v` is in `[str(e) for e in elements]` | no computed path today |
| AT-S3-9 | S3a | provider entry points: `provider_column_values` and `provider_generate` give equal values for each computed provider; an unsupported locale still raises before any draw; a draw that raises with a sentinel value in its message surfaces only `GENERATION_PROVIDER_FAILED` with no sentinel | no computed provider branch today |
| AT-S3-11 | S3a | an admitted column with `null_probability: 0.3` has the same null bitmap on the whole-table and streamed routes and on the parent commit. A second cell pins a value golden derived independently in the test from `family_bytes("faker_computed_draw")` with PCG64 and the S1a formatter; seeding values from the `np` family turns that golden red, since the null mask alone cannot see it | null mask unchanged by design |
| AT-S3-12 | S3a | a `random_element` with a multibyte element (`"😀"`) is priced at 4 bytes and admitted under a budget that fits 4 bytes | char counting prices 1 byte |
| AT-S3-13 | S3a | `provider_for("gen.faker_computed")` reproduces a production golden; deleting the catalogue row or the provider class fails at import or in `tests/native/test_draw_sites_assembly.py` | site missing |
| AT-S3-14 | S3a | For each provider alias in the contracts, test a registered V2 callback, a different-class adapter and a distinct same-class adapter independently. Keep the original capabilities and use distinguishable results. Assert the exact replacement output as text through `provider_generate` and whole-table generation (inject the effective registry at the lookup in `synthesize.py:388`). Restore each registration between cases. The default binding still takes the computed route in AT-S3-6. | a computed branch selected on capability alone replaces the configured output |
| AT-S3-15 | S3a | Through #813's actual assembler, stream a 4,500-row table with uuid and a positional sibling. First run with an unbounded ledger. Use AT-S3-1's limits, patch computed `next_batch` to raise for this array-eligible table, and record each `next_array` result before assembly. Require plain arrays, row counts [1000,1000,1000,1000,500] for `batch_rows=4500` and [17,1000,1000,1000,1000,483] for supplied [17,4483]. Compare both columns and schema with the full run. Repeat with a 100-byte singleton choice in the table: every piece has at most 400 rows. On a bounded sink, choose a budget between the split and unsplit streaming peaks and require streamed success. | missing array support invokes the patched list path, an unsplit layout violates the expected spans, and a chunked return fails assembly |
| AT-S3-16 | S3a | Extend `tests/unit/execution/test_ooc_faker_pool_context.py:303`. For an allowlisted name, set the allowance between the type-free and string construction floors. Assert stock refuses before build, while an isolated callback and an independently rebound same-class adapter returning distinct small ints each build and fit. Keep the off-allowlist control. In the sentry, force the public predicate false for an otherwise stock binding at each consumer's lookup and observe adapter dispatch and the type-free construction floor respectively. | the existing class comparison misclassifies the callback and same-class replacement |
| AT-S3-10 | S3a | through the public route, a compiled config with `faker_type: uuid` or `faker_type: random_choice` (alias names) is refused as today (`plan/checks/_generate_columns.py:245`); at the lower-level `synthesize` entry, the same columns keep today's `word` fallback bytes | guards the alias check in section 5.1 |

## 8. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M-1 | `window.py` builds `PerRowFakerStream` for an admitted column | AT-S3-2, AT-S3-6 |
| M-2 | the provider admission function declines a stock computed capability | AT-S3-6, AT-S3-4 provider cells |
| M-3 | `synthesize._faker` skips `open_computed_stream` | AT-S3-6 |
| M-4 | `next_batch` draws with `Generator.integers` per batch instead of fixed raw words (rev 4 M6) | AT-S3-1 |
| M-5 | `_words_to_uuid_bytes` uses native byte order (`.view(np.uint8)` without `astype("<u8")`) | a unit cell feeds a big-endian (`>u8`) word array and asserts the little-endian byte layout; native order is equivalent on little-endian hosts, so only this explicit cell can catch it |
| M-6 | the provider caller builds the int array as int64 instead of text (rev 4 M9) | a cell asserts `next_array` returns `pa.string()` before `_as_text` runs; AT-S3-4 alone cannot catch it, because `_as_text` turns the int back into text (`generation/kinds/_provider.py:82`, `:97`) |
| M-14 | Provider admission ignores `is_stock_binding` | AT-S3-14, AT-S3-16 dispatch cell |
| M-15 | Independently return a `ChunkedArray` for a bounded array call, skip splitting a supplied partition, or drop the payload-width cap | AT-S3-15 |
| M-16 | Restore the out-of-core class comparison at `_faker_pool.py:56` | AT-S3-16 floor cells |
| M-7 | `open_computed_stream` admits `unique: true` | AT-S3-5 |
| M-8 | the stream seeds from `ctx.base_int("faker")` | AT-S3-3 golden |
| M-11 | the stream returns ints for `random_element` instead of text | AT-S3-4 (streamed `pa.array(..., type=string)` raises) |
| M-12 | the width counts characters, not UTF-8 bytes | AT-S3-12 |
| M-13 | the computed provider branch moves into `provider_column_values` | AT-S3-9 (`provider_generate` misses it), AT-S3-6 |
| M-9 | `faker_payload_bound` skips `computed_spec_for` | AT-S3-2 (`random_int` window refused) |
| M-10 | `open_computed_stream` drops the `contract.faker_type` check | AT-S3-10 |

## 9. Frozen contracts and byte changes

- Generate output bytes change for the six admitted shapes (rev 4 section 10, as narrowed by section 1 here). One `Breaking:` line in `changelog.d/gen-nonfaker-draws-s3.md` and one entry in `docs/compatibility-contract.md` section 1 as a pre-GA correction. Types and value sets do not change.
- No change for `text` and `paragraph` (S3b deferred).
- No change to: other Faker types, non-admitted shapes, mask output bytes, the null mask, any seed family in `GEN_FAMILIES`, any reason code, the Faker output lock.
- The draw site registry gains one row; the determinism protocol map (`execution/native/_determinism_protocol.py:116`) keeps `"faker": "gen.faker_per_row"` and gains the trailing comment `# + gen.faker_computed` (section 5.3).
- Window admission widens: `random_int` with strict int kwargs and `random_element` with a homogeneous list become Class A instead of `CODE_UNBOUNDED`. A refusal becomes a success, which is not breaking.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | no new message or log; `computed_draw_spec` refusals are already value-free (S1a) and generate refuses nothing new | AT-S3-5 | M-7 |
| 2 | Cleanup missing on an exit path | N/A no new resource; the stream holds only a bit generator and no ledger reservation | none needed | N/A no handle to leak |
| 3 | State machine and concurrency | the stream has no per-row state; each `next_batch` copies the start state, so concurrent or out-of-order batches are safe | AT-S3-1, AT-S3-2 | M-4 |
| 4 | Route parity and silent fallback | one admission function for all sites; the sentry runs every contract row on every reachable site with the old paths patched to raise | AT-S3-6 | M-1, M-2, M-3 |
| 5 | Referential integrity | N/A generate references draw from parent rows, not from these streams; a uuid key column used as a parent is read from its output like any column | existing relational tests in T1 | N/A no FK code changes |
| 6 | Untrusted producer | the config is the input; argument parsing is the S1a strict parser, and anything outside it stays on today's path | AT-S3-5 | M-7 |
| 7 | Check then use (TOCTOU) on a path | N/A no filesystem access | none needed | N/A no path checks |
| 8 | Weak tests and overclaimed evidence | goldens are value and schema; regenerated parity goldens are listed by name; the perf cell runs on the Dell | AT-S3-3, AT-S3-4 | M-5, M-6 |
| 9 | Behavior-preserving refactor drift | non-admitted shapes compared byte for byte with the parent commit | AT-S3-5 | M-7 |
| 10 | Frozen contract drift | the byte change is named in the changelog and the compatibility contract; types pinned | AT-S3-4, section 9 | M-6 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| Anchored validation | yes | the uuid regex in AT-S3-8 is anchored with `\Z` |
| Strict wire and stored types | yes | computed draws emit text and the existing typing post-pass owns the output schema (AT-S3-4) |
| No exception context in output | no | no new error |
| Versioned read models | no | no read model |
| Normalized guard scanners | yes | the sentry's inventory comes from `FAKER_DRAW_CONTRACTS`, not a literal list |
| No reaching into private modules | yes | the stream imports `generation.pool` and `providers_v2` public names only |
| No hidden CI failures | yes | the perf cell has a `perf` marker and runs on the Dell; recorded in the PR |
| One input, one trust class | no | no new entry point |
| Mutations on the final head | yes | section 8 on the final head |
| Allowlisted helpers still checked | yes | the AST walk has no allowlist; every site module is walked |
| No raised caps | yes | `_COUNT_MAX` is unchanged |

## 11. Enumerations

### 11.1 Exit paths

- Admitted column: `open_computed_stream` returns a stream; the site uses it (`generation/synthesize.py:455`, `generation/_column_streams.py:331`, `generation/window.py:200`).
- Not admitted: it returns `None`; the site takes today's path (pool check, then per-row Faker or adapter batch).
- Provider kind: after locale validation, `_draw` tries the computed stream with the effective registry, then uses existing capability routing for a declined binding.
- Generate refuses nothing new; no new exception or reason code.

### 11.2 Routes

| Route | Site | After S3a |
|---|---|---|
| whole table | `synthesize._faker` | computed for admitted shapes |
| streamed batches | `_column_streams._faker_stream` | computed, through `next_array` on #813's array-eligible path, otherwise through its existing list or type-conversion path |
| window | `window.generate_rows` | computed, Class A |
| provider kind (whole table only) | `kinds/_provider._draw`, from `provider_column_values` and the exported `provider_generate` | computed for admitted stock bindings, otherwise the adapter path |
| V1 mirror | `generators/columns.py::ColumnGenerator._generate_faker_column` | unchanged and unreachable from generate Faker columns (section 5.3); formula `faker.*` calls keep per-row bytes (non-goal) |

### 11.3 FK shapes

- N/A: S3 adds no relationship handling. A generated uuid used as a parent key is a normal output column, and child references read it after generation, so the existing relational tests in T1 cover it.
- N/A: `inherit` and per-parent repair read output values, not streams.

### 11.4 Fields

- Config `faker_type`, `faker_kwargs`, `unique`, `null_probability` on a generate column; `provider` on a provider column (`config/_generate_options.py:405`).
- `ComputedDrawSpec.output_type`, `.count`, `.lo`, `.step`, `.elements` (`generation/pool/_computed_draw.py:62`).
- `COMPUTED_DRAW_FAMILY` (new, `generators/derivation.py`).

### 11.5 Output surfaces

- Generated column values and Arrow types in every output format.
- Generation evidence: the draw site registry row (`execution/native/_draw_sites_gen.py`).
- Logs and error messages: N/A, no new site.
- Changelog and `docs/compatibility-contract.md` section 1.

## 12. Slices

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S3a | engine | `ComputedDrawStream`, `open_computed_stream`, `computed_spec_for` and `computed_value_width`; wiring in the three Faker sites, provider dispatch, table layouts and `faker_payload_bound`; shared stock predicate in generation and the out-of-core construction floor; window Class A; `COMPUTED_DRAW_FAMILY`; draw site row and protocol comment; sentry; changelog and contract note; AT-S3-1 to AT-S3-16 | GSA S1a (#813) merged (it creates `generation/stream/`) | R2 | T1 plus the generation, parity and native draw-site selections; full suite (golden regeneration touches shared parity fixtures); gate Codex then Dennis |
| S3b | engine | deferred (OWNER CALL below) | - | - | - |

OWNER CALL (recommended non-breaking option taken): S3a does not wait for GVS S1 (plan revision 1, not built). `ComputedDrawStream` implements the existing `next_batch` protocol and the optional `next_array` that #813 already adds. This removes the schedule risk to a 1.0 row and adds no parallel interface (Dennis R1 P2-9).

OWNER CALL (recommended non-breaking option taken): S3b (`text` and `paragraph` pool picks, rev 4 section 10) is deferred. A certified pair makes the column Class B, and `generate_rows` would refuse tables whose window works today (Codex R1 P1-3). It comes back as its own row only with a pool window contract (a positional pool pick that is Class A) or an explicit owner decision to accept the refusal.

OWNER CALL (recommended non-breaking option taken): the modulo bias of at most `count / 2**64` is accepted and recorded as a known issue. An unbiased method breaks seekability.

## 13. Pre-mortem

- GSA S1a (#813) changes the stream package layout in gate. S3a only places one module beside `_batches.py`; it re-anchors after #813 merges.
- #813 changes the `next_array` signature in gate. S3a follows what merges.
- The uuid4 measurement misses 100 ns/row on the Dell. The gate fails and the builder profiles the formatter; the budget is not loosened in S3a.
- GSA S2 (provider and lookup streams) edits `kinds/_provider.py`. Whichever merges second rebases. If GSA S2 makes `kind: provider` streamable, the provider row joins the streamed and window cells of the sentry, which already derive from the contract rows.
- NATIVE-THREADS-DEFAULT changes the index helpers. S3a uses no index helper (raw words only), so it is not affected.
- A user relies on per-row `uuid4` values across releases. Pre-GA byte changes are allowed when named; section 9 names it.
- The Faker lock shows a diff. Not expected (section 1). The builder stops and reports instead of regenerating.
- A formula path reaches the V1 mirror with an admitted column. Section 5.3 makes the builder check and route it.

Review status: Codex R4 checked the R3 folds against the provider registry, out-of-core pool and #813 assembler. Sections 5, 7 and 8 specify the effective layout, adapter fallback and guards for both stock-binding consumers. Implementation tests and mutations run on the final S3a code head.

## 14. Follow-ups (not in this row)

- S3b: `text` and `paragraph` pool picks, once a positional (Class A) pool pick exists or the owner accepts the window refusal.
- Provider arguments for generate `provider:` columns, if a user asks. Today the config cannot carry them.
- Retire the per-row V1 mirror once nothing reaches it (H-1 structure review).
- Unbiased bounded integers if a range near `_COUNT_MAX` is ever admitted.
