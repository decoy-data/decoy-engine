Status: plan

# GEN-STREAM-ALL S1b and S2: Faker pools widen, and provider and lookup columns stream

Rules consulted: `/home/cam/dev-rules/00-universal.md`, `/home/cam/dev-rules/risk-and-exceptions.md`, `/home/cam/dev-rules/development-loop.md`, `/home/cam/dev-rules/cross-cutting-concerns.md`, `/home/cam/dev-rules/testing.md` (Test depth), `/home/cam/dev-rules/workspace-and-vcs.md` (Commit messages), the plan contract and defect catalog (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`), and the row's master plan `origin/plan/gen-stream-all:docs/plans/2026-11-22-gen-stream-all.md` (sections 5 to 10, owner decision 2026-11-23).

Row: GEN-STREAM-ALL (every fast generator kind streamed). Repo: decoy-engine. Risk: R2 (byte changes on a frozen output contract, determinism). Anchor: PR #813 (S1a) head `abbb6241d`, plus the uncommitted locale-helper fix in its worktree (`requested_locale` and `open_column_faker` in `faker_setup`). S1b and S2 re-anchor on the head that merges #813; every line number below is from that worktree (`abbb6241d` plus its uncommitted changes) and moves with the merge.

This file plans S1b and S2 in full. S3 and S4 are an outline (section 13) and get their own plan after S2 merges.

## 1. Frame

S1a (#813) gave the streamed core a `generation/stream/` package, resident pool sizing in `pool/_resident.py`, and one locale helper. Two gaps remain for the generator kinds the master plan calls fast:

- Faker pools are narrow. `pool_eligible` (`generation/_faker_pool.py:255`) admits the legacy 10 types in any locale and the certified locale pairs, and only from `N_THRESHOLD = 50_000` rows (`generation/_faker_pool.py:237`). The owner decision of 2026-11-23 widens pools to Group A (`word`, `sentence`, `date_of_birth`) and Group B (`email`, `safe_email`, `free_email`, `company_email`, `user_name`, `phone_number`, `url`, `domain_name`, `ipv4`, `street_address`, `address`, `postcode`, `zipcode`) on ordinary columns, with opt-out for `unique: true` and for `reference` / `inherit` key columns.
- `provider` and `lookup` columns are declined by `ADMISSION_MATRIX` (`generation/_admission.py:57-60`), so one such column sends the whole plan to the legacy resident path.

S1b closes the first gap. S2 closes the second.

## 2. Guarantee and non-goals

Guarantee:

- G1. A pool-admitted Faker column produces the same bytes on the legacy path, the streamed path at any batch size, and a window read at any offset inside the table. Two builds with the same seed give the same bytes, including for a locale list. A window read at any offset, inside or past `row_count`, is served, and its values do not depend on how the read is split into pages.
- G2. A column that is a key (a `reference` target or an `inherit` parent key) or `unique: true` never pools, on every admission site.
- G3. A `provider` or `lookup` column streams with bytes and Arrow schema equal to the legacy path at every batch size, and a plan with only fast kinds reports `streamed`. A lookup column whose legacy schema cannot be known before the first batch stays on the legacy path.
- G4. No new error or log text carries a generated or source value.

Non-goals:

- No `statistical` or `inherit` streaming (S3). No route codes or run-card fact (S4).
- No pooling of `uuid4`, `random_int`, `random_element`, `text` or `paragraph`: those belong to GEN-NONFAKER-DRAWS S3a (computed draws) or stay per-row.
- No change to the mask side or to custom Faker providers (they stay per-row and legacy).
- No native-shadow pooling of the new types.

## 3. Established solutions

Searches run: NumPy `Generator` documentation on sequential draws, the CPython `random.Random.choices` source (installed stdlib), the Faker `seed_instance` documentation, and the engine's own pool and harness code.

- Seeded pool plus a seeded index stream is the existing pattern (`PooledSelector`, `generation/_faker_pool.py:449`). NumPy `Generator.integers` is position-based: checked locally, `integers(size=7)` then `integers(size=993)` equals `integers(size=1000)` from the same seed. S1b's window skip follows the same rule.
- `random.Random.choices` draws one `random()` per element, with weights (`bisect(cum_weights, random() * total)`) or without (`floor(random() * n)`), so it is prefix-stable across `k`. `CategoricalStream` already relies on it.
- A seeded Faker instance is a sequential generator: checked locally, the first 9 `email` values of a build of 20 equal a build of 9 from the same seed. The determinism harness (`scripts/faker-determinism/`) certifies this per type and locale.
- No custom algorithm is added. The only new mechanics are a cursor and a discard loop over an existing generator.

## 4. Reuse inventory

| Need | Reuse | Where |
|---|---|---|
| Pool build | `build_pool_values` | `generation/_faker_pool.py:333` |
| Persistent selection | `PooledSelector.take` / `select` | `generation/_faker_pool.py:476` |
| Pool selector factory | `open_pooled_selector` | `generation/_faker_pool.py:491` |
| Resident pool sizing | `faker_pool_resident_bytes` | `generation/pool/_resident.py` (S1a) |
| Value caps | `FAKER_VALUE_CAPS`, `faker_value_cap` | `generation/_bounds.py:55`, `:125` |
| Per-type certification | `certified_pairs.json`, `check_determinism.py` | `scripts/faker-determinism/` |
| Locale handling | `requested_locale` | `internal/faker_setup.py:647` (S1a fix) |
| Provider draw paths | `draw_path`, `PoolBuilder`, `PoolSampler` | `generation/kinds/_provider.py:45`, `generation/pool/_builder.py:116` |
| Lookup draw | `lookup_values`, `lookup_column_values` | `generation/kinds/_lookup.py:246` |
| Weighted values draw | `CategoricalStream` batch draw | `generation/_column_streams.py:153` |
| Seed to int | `seed_bytes_to_int` | `generation/pool/_sampler.py:279` (import site) |
| Value width rule | `categorical_payload_bound` | `generation/_bounds.py:155` |
| Public provider API | `generation.kinds` exports | `generation/kinds/__init__.py:47` |
| Null mask on streams | `NullMaskedStream` | `generation/_column_streams.py:249` |
| Reference targets | `_referenced_keys` | `generation/_streamed.py` (S1a) |
| Inherit edges | `iter_generate_input_refs` | `generation/relational/_inherit.py` |

## 5. Design

### 5.1 Choke point: one key-column set

New `generation/pool/_keys.py` (about 60 lines) has two functions:

- `pool_key_columns(configs) -> frozenset[tuple[str, str]]`: every `(reference_table, reference_column)` of a `type: reference` column, and every inherit parent key, read as `(edge.source_table, edge.source_key)` from each edge that `iter_generate_input_refs` yields (`config/_generate_relational/__init__.py:543`). An edge with an empty `source_key` is skipped. `source_key` is set for every input read through a foreign key, not only inherit (`config/_generate_relational/__init__.py:499-502`), so the set is slightly wider than reference and inherit targets; every member is a key another table reads, so a per-row draw for it is the safe side. Composite targets add each member column. An inherit parent key must be a non-null `sequence` (`config/_generate_relational/__init__.py:207`), so today it is never a Faker column; it is in the set so that the rule stays true if that validation widens.
- `referenced_key_columns(configs)`: the reference targets only. `_streamed._referenced_keys` (`generation/_streamed.py:180-187`) is replaced by this one, because the same set drives KeyPool collection in `_preflight` (`:230`) and `_consume_table` (`:420`), and S1b does not change what KeyPool collects. S3 decides whether inherit keys join KeyPool.

`pool_opted_out(col, *, table, key_columns)` (`generation/_faker_pool.py:244`) gains one rule: `(table, col["name"])` is in `key_columns`. `table` is an explicit argument because the raw column dicts in `_streamed._pooled_columns` carry no `TABLE_KEY` (the window's dicts do, through `with_table` at `generation/window.py:192`); one explicit argument keeps every route the same. Both arguments are keyword-only with no default.

Every route that reaches `pool_eligible` passes the set, and every function on each chain takes `key_columns` as a required keyword with no default:

- Legacy resident: `synthesize._generate_tables_from_config` (`generation/synthesize.py:104`, entered from `generate_tables` at `generation/_plan_entry.py:215`) computes the set once, then `synthesize._generate_column` (call at `:186`), `synthesize._faker` (`:455`), `_faker_pool.try_pool` (`:292`).
- Pinned: `execute_pinned` (`generation/_pinned_execute.py:202`, public through `generation/pinned.py`) calls `_run`, which calls `synthesize._generate_column` directly (`:242`) and never enters `generate_tables` or `classify_plan`. `execute_pinned` computes the set from the pinned configs with `pool_key_columns` and passes it to `_run`. Without this, a 20,000-row pinned `users.email` that is a reference target would draw from 10,000 pool values with replacement and give duplicate parent keys.
- Streamed: `_streamed._pooled_columns` (`generation/_streamed.py:197`) and `make_column_stream` (`generation/_column_streams.py:300`) to `_column_streams._faker_stream` (`:360`, `pool_eligible` call at `:375`), reading the new `PlanAdmission.key_columns` that `classify_plan` fills.
- Window: `window._build_streams` (`generation/window.py:195-202`), where the pool or per-row choice is made once pooled Faker is Class A (5.4). `_window_admission.py:383` and `:437-440` call `pool_eligible` only to skip `_check_faker` and to return Class B; S1b removes both calls, so the window admission has no pool decision left.

Guards:

- AT-S1b-2 runs all four routes with a spy.
- AT-S1b-10 is a signature sentry: for each function on the four chains above, `inspect.signature` shows `key_columns` (and `table` on `pool_opted_out`) as keyword-only with no default. A seeded default makes it red, so M-2 is caught.
- AT-S1b-11 walks the AST of `src/decoy_engine/generation/` and fails on any call to `pool_eligible` whose `opted_out` argument is not a `pool_opted_out(..., table=..., key_columns=...)` call.

`_streamed.py` is at 592 lines against the 600 goal. Its edit replaces `_referenced_keys` with an import, so the file shrinks before S2 adds anything.

### 5.2 The eligible set and the pool size

- `N_THRESHOLD` is deleted. One function, `pool_size_for(rows) -> int` in `_faker_pool.py`, returns `P = min(rows, DEFAULT_POOL_SIZE)` with `DEFAULT_POOL_SIZE = 10_000`.
- `pool_eligible` returns False for `rows < 1`, so a 0-row table never reaches `check_pool_size` (`determinism/_derive.py:348-358`) or `integers(0, 0)`. A 1-row table pools a pool of 1 in build order.
- When `rows <= DEFAULT_POOL_SIZE`, the column is the pool in build order: value `i` is the `i`-th provider call after the seed. No selector runs. OWNER CALL (master plan Q1): build order for small tables. Default: build order, as recommended there.
- When `rows > DEFAULT_POOL_SIZE`, today's selector runs over a pool of `P` values.
- One shared draw decides between the two modes: `open_faker_pool_draw(col, rows, ...)` in `_faker_pool.py` returns either a build-order draw or a `PooledSelector`. Legacy `try_pool`, streamed `_faker_stream` and the window draw (5.4) all call it, so the rule is written once. AT-S1b-12 checks that the three routes agree.
- Locale lists. `build_pool_values` (`generation/_faker_pool.py:363`) resolves the provider callable on a fresh Faker before `seed_instance`. With a locale list, Faker's proxy picks the factory at attribute lookup from `factories[0].random` (Faker `proxy.py`, `_select_factory_choice`), which is not yet seeded, so two builds with one seed can use different locales (Codex probe: 14 builds of 9 `first_name` values with `["en_US", "ja_JP"]` gave two digests). S1b moves `seed_instance` before `resolve_pool_provider`, so the factory choice is drawn from the seeded generator. This changes bytes for a legacy-10 column with a locale list at 50,000 rows or more (section 9). A single-locale build is unchanged: a single-locale proxy draws nothing at lookup. AT-S1b-14 pins it.
- Group A and B pairs decline a column with non-empty `faker_kwargs`, because certification ran with `kwargs={}` (`scripts/faker-determinism/certified_pairs.json`). The legacy 10 keep today's behavior.
- Reservations pass `P`: `faker_pool_resident_bytes(P, payload)`.
- New generated module `generation/pool/_eligible.py` (about 90 lines) holds `POOL_ELIGIBLE_LOCALE_PAIRS`, written by `scripts/faker-determinism/write_eligible.py` (about 40 lines) from `certified_pairs.json`. `POOL_ELIGIBLE_FAKER_TYPES` (the legacy 10) stays in `_faker_pool.py`. `_bounds.py` imports the pairs from `_eligible.py`, so there is one root.
- Group A and B types are admitted only through certified `(type, locale)` pairs. A pair the harness has not certified stays per-row in that locale.
- `FAKER_VALUE_CAPS` gains `free_email: 320` and `domain_name: 256`. The other 14 new types already have caps or take the `_NAME_LIKE` default; AT-S1b-4 pins all 16.
- `_window_admission` reads the locale through `faker_setup.requested_locale` (`:649`) instead of `col.get("locale") or instance_default_locale`, so there is one locale reader.

### 5.3 Harness tier 3

`scripts/faker-determinism/check_determinism.py` (597 lines) first moves its tier tables into a new `scripts/faker-determinism/_tiers.py` (about 80 lines), then `_tiers.py` gains `TIER_3`: the 16 Group A and B types in en_US, en_GB, fr_FR, de_DE and es_ES. The builder runs the harness in the locked environment (`uv.lock`, Faker 40.23.0), commits the new digests to `certified_pairs.json` and `golden_digests.json`, then runs `write_eligible.py`. A pair whose pool digest is not stable across two processes is left out and stays per-row; the builder lists any left-out pair in the PR. `date_of_birth` is certified with the `_dob_anchor.py` anchor in place, because `_reproducibility.py` excludes it from `_CLOCK_FAKER_EXACT` only under that anchor.

### 5.4 Windows keep pooled Faker as Class A

Today a pooled column is Class B (`generation/_window_admission.py:440`, reason `pooled_faker`), and `generate_rows` (`generation/window.py:263`) refuses a Class B table. Before S1b this only touched tables of 50,000 rows or more. Dropping the threshold would make every small table with a Group A or B column Class B, and `generate_rows` would refuse tables it serves today. That is a function break, so S1b makes pooled Faker Class A.

New `generation/stream/_window_pool.py` (about 90 lines): `WindowPoolDraw`, one per column, built once per `generate_rows` call and reused for every chunk.

- Build order (`rows <= 10_000`): value `i` for `i < 10_000` is the `i`-th provider call after the seed. Build order is prefix-stable and does not depend on `rows`, so value `i` is the same for every table length and equals the full run's value `i` for `i < rows`. A window ending at `e <= 10_000` builds `e` values, so page 0 (count 100) of a 9,000-row table costs 100 Faker calls, not 9,000.
- Past the build-order prefix (`i >= 10_000`, only reachable by a read past `row_count`): the draw builds the full 10,000-value prefix once and serves value `i` as `pool[j]`, where `j` is position `i - 10_000` of the column's selector index stream (`PooledSelector` with the column's selection seed, reached through `skip`). This is a deterministic continuation: it does not depend on `rows` or on page boundaries, and no full run reads it, so it has no parity target. Reads past `row_count` stay served, as for any Class A column, and the `generate_rows` docstring (`generation/window.py:283-284`) stays true.
- Selector (`rows > 10_000`): it builds the pool of `P` values and holds a `PooledSelector` with a cursor. Inside one `generate_rows` call chunk offsets only increase (`generation/window.py:352`), so a chunk at `offset > cursor` calls the new `PooledSelector.skip(offset - cursor)`, which draws and discards indices in chunks of at most 1,048,576, so no large array is held. A chunk at `offset < cursor` has no caller, so `WindowPoolDraw` has no reopen path: it raises `RuntimeError` with a fixed message, and AT-S1b-7b pins it. Offsets past `row_count` are served.
- `_window_admission._class_b_reason` no longer returns `pooled_faker`. A pooled column runs `_check_faker` like a per-row column, so the cell cap still applies.
- `window._build_streams` (`generation/window.py:195-202`) uses `WindowPoolDraw` when `pool_eligible` admits the column and `PerRowFakerStream` otherwise. The decision is the same `pool_eligible(..., rows, opted_out=pool_opted_out(col, table=..., key_columns=...))` call as the full run, with `rows` the declared `row_count`. The window computes `key_columns` once per `generate_rows` call from the config it already holds.
- `WindowPoolDraw` is built lazily: `_build_streams` (`generation/window.py:322`) only records the column, and the pool is built on the first draw call, inside the chunk loop after its `deadline_s` check (`generation/window.py:353`). A call whose deadline has passed before the first chunk does not build. The build and a skip inside one chunk are not interrupted by the deadline; section 14 states the cost.

No window read that is served today refuses after S1b, so the window contract has no `Breaking:` line. The platform `generation_child.py` caller, which passes user offsets, keeps working.
- `PooledSelector.skip` is about 12 lines in `_faker_pool.py`.

### 5.5 Native shadow and draw sites

- `execution/physical/_shadow_generation.py:100` sets `SHADOW_ADMISSIBLE_FAKER_TYPES = POOL_ELIGIBLE_FAKER_TYPES`. It stays the legacy 10, so a column of a new type keeps the shadow decline it has today.
- The `gen.faker_pool_build` notes in `execution/native/_draw_sites_gen_pool.py` cite `n >= N_THRESHOLD`; they change to "pool size `min(rows, 10_000)`; build order at or below 10,000 rows". The selection site note changes from `partitionable=False` to say it is partitionable through `skip`; the flag value itself is a native contract and is not changed in S1b.
- `scripts/bench-generation-pool/bench_worker_gen.py:203` assigns `_faker_pool.N_THRESHOLD`, and its README cites it. After the deletion the assignment would do nothing. S1b removes the override argument from the script and the README line.

### 5.6 S2: provider streams

Provider draw logic stays in the package that owns it. New `generation/kinds/_provider_stream.py` (about 170 lines), exported from `generation.kinds` next to `draw_path` (`generation/kinds/__init__.py:47`). `make_column_stream` (`generation/_column_streams.py:330-358`) dispatches `provider` to the public `open_provider_stream(col, ctx, registry, ...)`; nothing outside `kinds/` imports a `kinds/_` module.

Order of dispatch inside `open_provider_stream`:

1. If GNF S3a has merged: its public `open_computed_stream(col, ctx, registry)` runs first, with S3a's live-registry, stock-binding and effective-locale checks. If it returns a stream, that is the column's stream. S3a never adds a `"computed"` value to `draw_path`, so S2 has no `"computed"` branch; S2 calls S3a's opener, never re-derives its rule. If S3a has not merged, this step does not exist and the second to merge adds it (section 12, order).
2. Otherwise `draw_path(caps)` (`generation/kinds/_provider.py:45`) is read once:

- `"pool"`: `PooledProviderStream` builds the pool once with the same `PoolBuilder(registry).build(size=DEFAULT_POOL_SIZE, job_seed=build_seed, locale=locale)` call (`generation/kinds/_provider.py:127-129`). Selection is not re-implemented. S2 adds `PoolSampler.open_reuse_cursor(pool, seed) -> Callable[[int], np.ndarray]` to `pool/_sampler.py` (about 12 lines): it builds `np.random.default_rng(seed_bytes_to_int(seed))` once (`pool/_sampler.py:279`) and returns `integers(0, pool.size, size=k)` per call. The whole-table REUSE branch (`pool/_sampler.py:279-281`) becomes `open_reuse_cursor(pool, seed)(n)`, so legacy bytes do not change (AT-S2-5b), and the stream calls the same cursor per batch. Provider pools keep `DEFAULT_POOL_SIZE` and do not take `pool_size_for`: S2 is a parity slice and changes no bytes. The Faker and provider rules differ on purpose until a later row decides otherwise.
- `"keyed"`: `KeyedProviderStream` calls `adapter.generate(provider, spec=ProviderSpec(locale, deterministic=True, namespace=namespace, seed=value_seed), source_value=offset + i)` per row, the exact legacy call (`generation/kinds/_provider.py:146-151`). Stateless.
- `"batch"`: `BatchProviderStream` holds one seeded provider instance across batches. `generate_batch` (`providers_v2/_faker_adapter.py:197`) builds a fresh instance per call (`:230-234`), so calling it per batch would restart the sequence. S2 adds `open_batch_cursor(provider, spec) -> Callable[[int], list]` to the Faker adapter only, about 15 lines: it builds the seeded instance once and returns `k` values per call. `generate_batch` becomes `open_batch_cursor(...)(count)`, so legacy bytes do not change. The column is admitted on the batch path only when the adapter's `generate_batch` and `open_batch_cursor` are both the stock Faker adapter's own functions (`type(adapter).generate_batch is FakerAdapter.generate_batch`, and the same for the cursor). A replacement adapter that subclasses the Faker adapter and overrides `generate_batch` inherits a cursor that would not match its own batch output, so it is declined (legacy path). `draw_path` returns `"batch"` only for `backend_type == "faker"`, so the Mimesis adapter needs no cursor.

Error boundary. Stream construction (pool build, cursor open, seed conversion), each draw and each `_as_text` conversion all run inside one boundary, the one `provider_generate` uses (`generation/kinds/_provider.py:79`): any failure raises `GenerationError(GENERATION_PROVIDER_FAILED)` with a fixed message. The raise is made after the `except` block closes (the existing pattern), so `__cause__` and `__context__` are both `None`, and no seed bytes or provider text reach `str(exc)`.

Schema. Legacy builds provider output as text (`text_columns`, `generation/_statistical_column.py:120-135`), so the provider stream's Arrow type is `pa.string()` on every path.

Payload bounds. Today `compute_payload_bounds` (`generation/_bounds.py:181`) returns `None` for `provider` and `lookup`, and `_run_admitted` refuses an unbounded column before `_preflight` (`generation/_streamed.py:374`). S2 adds:

- `provider_payload_bound(col, registry)`: the effective binding's value cap. A Faker-backed provider whose Faker type has a `faker_value_cap` takes that cap; any other binding returns `None` and keeps today's unbounded refusal (legacy path). Step 1 lists, for each stock provider, which one it gets.
- `lookup_payload_bound(values)`: `categorical_payload_bound`'s width rule applied to the decoded lookup list. `compute_payload_bounds` gains a keyword-only `lookup_lists` argument, passed by `_streamed` from its `legacy_kwargs`.

Provider pool memory. `_streamed._preflight` (`:241`) reserves only Faker pooled columns today. S2 reserves each live provider pool at preflight for the life of its stream, with `faker_pool_resident_bytes(DEFAULT_POOL_SIZE, provider_payload_bound)`, and releases it on the stream's `ExitStack` callback. A budget below the sum refuses with `GENERATION_BUDGET_EXCEEDED` before the first build or write (AT-S2-7).

New seed holders (the `WindowPoolDraw` selection seed, the `KeyedProviderStream` value seed, the `PooledProviderStream` selection seed, the batch-cursor seed) hold the seed in an `OpaqueBox` or a `repr=False` field and get rows in `secret_material_census.json`. The census test covers them (AT-S1b-13, AT-S2-8).

### 5.7 S2: lookup streams

`LookupStream` in `generation/kinds/_lookup.py` (exported from `generation.kinds`): one `random.Random(ctx.base_int("py"))` held across batches. The values-and-weights draw is written once: S2 extracts `weighted_draw(rng, values, weights, k)` (about 10 lines, `generation/kinds/_categorical.py`) from `CategoricalStream`'s batch draw (`generation/_column_streams.py:153`), and the legacy lookup draw (`generation/kinds/_lookup.py:246`), `CategoricalStream` and `LookupStream` all call it. Each batch is `weighted_draw(rng, values, weights, batch)`. The list comes from `legacy_kwargs["lookup_lists"][(table, name)]`, and the context is built with `content_digests=lookup_digests(...)` exactly as `lookup_column_values` does. The stream holds a reference to the resident list, not a copy. Today `make_column_stream` builds `ctx` without content digests (`generation/_column_streams.py:319`), and `GenDeriveContext.for_column` fingerprints at construction (`generators/derivation.py:300`), which refuses a file-backed lookup without digests (`kinds/_lookup.py:262-263`). So S2 adds a `lookup_lists` keyword to `make_column_stream` (passed by `_streamed` from its `legacy_kwargs`) and, for a lookup column, builds `ctx` with `content_digests=lookup_digests(col, lookup)` before dispatch. That one context feeds both `LookupStream` and the outer `NullMaskedStream(inner, ctx, null_prob)`, so the null seed matches the legacy `null_seed_digests(..., lookup_lists)` path. AT-S2-3 uses a file-backed lookup to prove it.

Lookup schema. The streamed assembler needs the Arrow type before the first batch (`generation/stream/_batches.py:114`); legacy infers it from the drawn column (`generation/_statistical_column.py:126`), and Parquet lookup lists may hold integers, floats and booleans as well as text (`generation/kinds/_lookup.py:171`). Admission sets the schema with new `lookup_stream_schema(values, col, rows, ctx) -> pa.DataType | None` in `kinds/_lookup.py`:

- A declared output type on the column: that type, as legacy (`declared[name].arrow_type`). Done.
- `rows == 0`: `None` (legacy gives a `null` column).
- The list holds a `None`, or its values infer to more than one Arrow type one by one (for example `[1, 2.5]`, where a drawn subset of only integers would infer `int64` but the whole list infers `double`): `None`.
- `null_probability > 0`: the null mask is replayed from the same context, batch by batch, until the first non-null position. If every row is null, `None` (legacy gives a `null` column). This costs one batch in practice and the whole table only when every row is null.
- Otherwise: the single inferred type of the list.

`None` declines the column, and the plan stays on the legacy path. AT-S2-9 covers each case and compares schema and values across batch sizes.

### 5.8 S2: admission

`ADMISSION_MATRIX` (`generation/_admission.py:57-60`) marks `provider` and `lookup` admitted. The per-column check declines: a `provider` column on the `"batch"` path whose adapter's `generate_batch` or `open_batch_cursor` is not the stock Faker adapter's own; a `provider` or `lookup` column with no payload bound; a `lookup` column whose list is missing from the legacy kwargs (it then fails on the legacy path with today's error); and a `lookup` column for which `lookup_stream_schema` returns `None`.

### 5.9 Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_keys.py` | `generation/pool/` (16 modules; `generation/` already has 26 direct modules) | new CODEMAP row "pool key columns"; imports config only | `pool/_resident.py` |
| `_eligible.py` | `generation/pool/` | same | `pool/_resident.py` |
| `_window_pool.py` | `generation/stream/` | `generation/_column_streams.py` row (persistent per-column generators); `stream/` is S1a's sub-package for them | `stream/_batches.py` |
| `_provider_stream.py` | `generation/kinds/` | `generation/kinds/` row (fast generator kinds); exported from `generation.kinds` | `kinds/_provider.py` |
| `write_eligible.py`, `_tiers.py` | `scripts/faker-determinism/` | harness scripts | `check_determinism.py` |

`generation/` itself takes no new module. The CODEMAP `_faker_pool.py` and `_column_streams.py` rows gain the new names in the same PR.

### 5.10 Design notes

- One place per fact: key columns (`pool/_keys.py`), certified pairs (`pool/_eligible.py`, generated), pool size and mode (`pool_size_for` and `open_faker_pool_draw` in `_faker_pool.py`). The window, legacy and streamed routes read these, never restate them.
- Open/closed: a new draw path adds one stream class and one `draw_path` branch; no other site changes.
- No flag arguments: build-order and selector modes are two classes chosen by `rows`, not a boolean parameter.

## 6. Behavior and failure modes

| Case | Behavior |
|---|---|
| Table with 0 rows | `pool_eligible` is False; no pool, no selector. |
| Table with 1 row | Pool of 1 in build order. |
| Group B column with non-empty `faker_kwargs` | Per-row. |
| Pinned run (`execute_pinned`), key column | Per-row (G2). |
| Group B column, 9 rows, en_US | Pool of 9 in build order; the ledger reserves `faker_pool_resident_bytes(9, payload)`. |
| Group B column, 2M rows | Pool of 10,000; selector; bytes equal on legacy, streamed and window. |
| Group B column in an uncertified locale | Per-row, as today. |
| Column that is a `reference` target or inherit parent key | Per-row on every site (G2). |
| `unique: true` | Per-row, as today. |
| Window read ending past 10,000 on a pooled table of at most 10,000 rows | Served: build order to 10,000, then the selector continuation. |
| Faker column with a locale list, pooled | Seeded before the factory is chosen; equal bytes across builds. |
| Window read on a pooled large table at offset 9M | Skip from the cursor; bytes equal the full run. |
| Pool build declined (custom override, locale unavailable) | `open_pooled_selector` returns `None` and the column runs per-row, as today. |
| Budget too small for the pool | The ledger refuses before the build, as S1a. |
| Provider raises in a streamed batch or while the stream is built | `GENERATION_PROVIDER_FAILED`, no cause, no context, no value. |
| Provider binding with no value cap | Unbounded, so declined; legacy path, as today. |
| Lookup with a mixed-type list, a `None` entry, 0 rows, or all rows null | Declined; legacy path. |
| Replacement adapter that overrides `generate_batch` | Declined on the batch path; legacy path. |
| Lookup list missing | Declined at admission; the legacy path keeps today's error. |
| Budget too small for a provider pool | `GENERATION_BUDGET_EXCEEDED` in preflight, before the first build or write. |
| Custom Faker provider | Per-row legacy, as today. |

## 7. Acceptance tests

Each test fails before its slice unless marked as a control. Master plan numbers in brackets.

S1b:

- AT-S1b-1 [A1]. `pool_eligible` admits the legacy 10 in `pt_BR`; it admits each certified Group A and B pair and refuses an uncertified pair; no clock-dependent type is admitted in any locale (checked against `_CLOCK_FAKER_EXACT`).
- AT-S1b-2 [A12]. A reference-only plan: `users.email` (Faker, 20,000 rows) is the target of `orders.user_email`, and `users.alt_email` is an ordinary sibling. On the legacy path, the streamed path, `generate_rows` and `execute_pinned`, each leg first asserts the route it ran on (route label, or the pinned entry), then: a spy on `open_faker_pool_draw` sees no call for `users.email` and one for `users.alt_email`; `users.email` equals a per-row oracle (the per-row draw of `synthesize.py:515` with the same seed) byte for byte. The same at 9 rows. Separately, `pool_key_columns` on a plan with a valid `sequence` inherit parent contains `(parent_table, parent_key)`.
- AT-S1b-3 [A15]. Tables of 0 and 1 rows generate on all routes with no pool error. A 9-row table with a Group B column reserves exactly `faker_pool_resident_bytes(9, payload)` and its values equal the first 9 provider calls of a fresh seeded instance.
- AT-S1b-4 [A4]. `faker_value_cap` returns a fixed cap for all 16 new types; preflight runs with a provider snapshot that raises on any call.
- AT-S1b-5. Window parity. A 9,000-row `email` table read at `offset=0, count=100` builds 100 values, counted by a spy. For `email` at 9 rows: `(0, 1)`, `(0, 9)` and `(7, 2)` equal the full run's slice. For `email` at 120,000 rows: `(0, 1)`, `(7, 13)`, `(4096, 5000)` and `(119_990, 10)` equal the full streamed run's slice, and a spy sees `open_faker_pool_draw` called (fails before: `email` is per-row Class A on S1a and the opener does not exist). For `first_name` at 120,000 rows the same reads are served (fails before: Class B refusal).
- AT-S1b-6. A 9-row pooled `email` table: `generate_rows(offset=9_995, count=10)` is served and equals `(9_995, 5)` followed by `(10_000, 5)`; `(9, 1)` returns build-order value 9; `(25_000, 3)` read twice gives equal values. A 9-row and a 9,000-row table give equal values at `(10_002, 4)` (no dependence on `rows`). Fails before for `email` values (per-row today).
- AT-S1b-7. `PooledSelector.skip(n)` then `take(k)` equals `take(n + k)[n:]` for `n` in `{0, 1, 1_048_575, 1_048_577, 3_000_001}`, plus a Hypothesis property on `n` up to 4M.
- AT-S1b-7b. On one `WindowPoolDraw`, a draw at offset 4,096 then at offset 7 raises `RuntimeError` with the fixed message; draws at 7 then 4,096 equal the full run's slices.
- AT-S1b-8. `pool/_eligible.py` equals the output of `write_eligible.py` on the committed `certified_pairs.json` (drift guard).
- AT-S1b-9 [A10, perf, Dell vm-run]. `bench_worker_gen.py` and `bench_compare_gen.py` run with no `N_THRESHOLD` reference and agree on one record format. The worker accepts the Group A and B types, times `generate_tables_streamed` into a bounded Parquet sink, and records two witnesses separately: a build-order run (no sampler hit expected) and a selector run (sampler hit required). 10M rows of `email` stream in under 3 s; 10M `first_name` in under 1.0 s. Recorded in the PR.
- AT-S1b-10. The signature sentry of section 5.1 passes on the tree and fails when any function on the four chains gives `key_columns` a default.
- AT-S1b-11. The AST guard of section 5.1 passes on the tree and fails on a seeded scratch file that calls `pool_eligible(..., opted_out=False)`.
- AT-S1b-12. For one `email` column at 9 and 120,000 rows, legacy `try_pool`, streamed `_faker_stream` and `WindowPoolDraw` give equal bytes, and each calls `open_faker_pool_draw`. A Group B column with `faker_kwargs={"domain": "x.test"}` runs per-row on legacy and streamed (spy: no opener call); the window refuses it with `CODE_UNBOUNDED` before any draw, as today (control). `pool_opted_out` called without `table` raises `TypeError`.
- AT-S1b-13. The secret-material census test lists the `WindowPoolDraw` seed holder, and `repr(WindowPoolDraw(...))` shows no seed bytes.
- AT-S1b-14. A `first_name` column with `locale: ["en_US", "ja_JP"]` at 9 rows and at 60,000 rows: 14 legacy runs in fresh processes give one digest, equal to the streamed run and to window reads `(0, 9)` and `(4096, 100)`. Fails before (Codex probe: two digests).
- AT-S1b-15 [master plan boundary cells]. A pool whose reservation is one byte over the remaining budget refuses in preflight with `GENERATION_BUDGET_EXCEEDED`; at exactly the reservation it passes. A pooled column whose built value would exceed `faker_value_cap` takes today's over-cap handling with a value-free message (control from S1a, kept for the new types).
- Controls [A2, A3]: S1a take parity and batch invariance pass at batches `{7, 4096}` for every new type.

S2:

- AT-S2-1 [A5]. For each draw path (`pool`, `keyed`, `batch`) and for `lookup` with and without weights, the streamed bytes and schema at batch sizes `{1, 7, 4096}` equal the legacy bytes and schema, and the run reports route `streamed`. The batch path runs with a Faker provider; a Mimesis provider is checked on the paths `draw_path` gives it.
- AT-S2-2 [A6]. A plan with `sequence`, `provider` and `lookup` columns reports `streamed`; before S2 it reports legacy.
- AT-S2-3. With `null_probability: 0.3`, provider and lookup streams equal a frozen legacy digest committed with the test (computed on the S1a head, independent of the streamed code), and each run asserts route `streamed`. The lookup cell uses a file-backed lookup, so the content digests enter the null seed.
- AT-S2-4. A provider that raises inside batch 3, and one whose pool build raises during stream construction, each give `GENERATION_PROVIDER_FAILED`; `__cause__` and `__context__` are `None`; the message contains neither the raised text nor the seed bytes.
- AT-S2-5 (control). `generate_batch` output is byte-identical before and after the `open_batch_cursor` refactor for Faker at count 1 and 4096.
- AT-S2-5b (control). `PoolSampler.sample(..., REUSE)` output is byte-identical before and after the `open_reuse_cursor` refactor at n 1 and 20,000.
- AT-S2-6. Control for bytes: an adapter without `open_batch_cursor` on the `"batch"` path, and a Faker-adapter subclass that overrides `generate_batch`, each keep the plan on legacy (route asserted) and give today's bytes. The new part is the decline reason: the admission result names the batch-cursor rule.
- AT-S2-6b. Merge order with GNF S3a, run on whichever head merges second: a stock `uuid` provider binding goes to `open_computed_stream`; a replacement binding for the same name and an unsupported locale go to `draw_path`; each equals the whole-table run.
- AT-S2-7. A plan with a pooled provider column: with a budget above the pool reservation it streams (route `streamed`); with a budget one byte below it refuses with `GENERATION_BUDGET_EXCEEDED` before the first pool build (spy on `PoolBuilder.build`) and before any write (spy sink). A provider binding with no value cap keeps the unbounded refusal (legacy).
- AT-S2-8. The census test lists the provider stream seed holders, and their `repr` shows no seed bytes.
- AT-S2-9. Lookup schema: typed Parquet lists of `int64`, `double` and `bool`, and a string list, each stream with schema and values equal to legacy at batches `{1, 7, 4096}`. A list `[1, 2.5]`, a list with `None`, a 0-row table, a column with `null_probability: 1.0`, and a 3-row table whose seeded mask nulls every row each stay legacy (route asserted). A declared output type `string` on an integer list streams with the declared type.
- AT-S2-10. `weighted_draw` guard: `CategoricalStream`, the legacy lookup draw and `LookupStream` give equal values for one seed, values and weights.

## 8. Named mutations

Each must turn the named test red on the final head.

- M-1. `pool_opted_out` ignores `key_columns`: AT-S1b-2 red.
- M-2a. `execute_pinned` passes `frozenset()`: AT-S1b-2 (pinned leg) red.
- M-2b. `_generate_column` gives `key_columns` a default of `frozenset()`: AT-S1b-10 red.
- M-2c. `window._build_streams` passes an empty key set: AT-S1b-2 (window leg) red.
- M-3. Pool size stays `DEFAULT_POOL_SIZE` for `0 < rows < DEFAULT_POOL_SIZE`: AT-S1b-3 red.
- M-4. `skip` draws `n - 1` indices: AT-S1b-7 and AT-S1b-5 red.
- M-5. `WindowPoolDraw` drops its offset-below-cursor check and continues from the cursor: AT-S1b-7b red.
- M-5b. The continuation past 10,000 uses build order instead of the selector, or depends on `rows`: AT-S1b-6 red.
- M-5c. `build_pool_values` seeds after `resolve_pool_provider`: AT-S1b-14 red.
- M-6. `_eligible.py` gains a hand-written pair: AT-S1b-8 red.
- M-6b. `pool_eligible` drops the `rows < 1` check: AT-S1b-3 red.
- M-6c. The streamed route computes its own build-order rule instead of `open_faker_pool_draw`: AT-S1b-12 red.
- M-6d. Group A and B pairs ignore `faker_kwargs`: AT-S1b-12 red.
- M-7. `PooledProviderStream` opens a fresh reuse cursor per batch: AT-S2-1 red at batch 7.
- M-8. `BatchProviderStream` calls `generate_batch` per batch: AT-S2-1 red at batch 7.
- M-9. `LookupStream` builds `random.Random` per batch: AT-S2-1 red.
- M-10. The provider error boundary uses `raise ... from exc`: AT-S2-4 red.
- M-11. Preflight leaves provider pools out: AT-S2-7 red.
- M-12. `LookupStream` is null-masked with a context built without the lookup digests: AT-S2-3 red.
- M-13. `lookup_stream_schema` skips the mixed-type check: AT-S2-9 `[1, 2.5]` cell red.
- M-14. `lookup_stream_schema` skips the all-null replay: AT-S2-9 3-row cell red.
- M-15. The batch-path admission accepts any adapter with an `open_batch_cursor` attribute: AT-S2-6 subclass cell red.
- M-16. Stream construction runs outside the error boundary: AT-S2-4 construction cell red.

## 9. Frozen contracts and byte changes

- Generate output bytes change for: pool-eligible legacy-10 columns with fewer than 50,000 rows (now pooled); columns of an already certified locale pair (for example `street_name/en_US`, `generation/_faker_pool.py:78`) with fewer than 50,000 rows (now pooled); legacy-10 columns of 50,000 rows or more that are reference targets (now per-row under the key opt-out); legacy-10 columns of 50,000 rows or more with a locale list (seed before the factory choice, 5.2); and Group A and B columns in certified locales at every row count. The compatibility entry and the golden checks name one pair of each kind, `street_name/en_US` included. The CLI `decoy run --rows N` preview (`decoy/src/decoy/cli/gen/_preview.py`) scales `row_count`. When the full table has at most 10,000 rows, preview and full run both use build order, so the preview is a prefix of the full run. When the full table has more than 10,000 rows (before S1b, 50,000 or more), the full run uses the selector and the preview is not a prefix; the changelog says so. One `Breaking:` line in `changelog.d/gen-stream-all-s1b.md` and an entry in `docs/compatibility-contract.md` section 1 as a pre-GA correction. Types and value sets do not change.
- `generate_rows`: no read that is served today refuses. Window values change only where the column's full-run bytes change (above), plus the continuation past 10,000 on small pooled tables, which no full run reads.
- S2 changes no bytes (AT-S2-1 is parity).
- Golden files regenerated by the harness, by name (master plan section 10): `tests/native/test_determinism_goldens.py`, `tests/native/test_pooled_faker_draw_sites.py`, `tests/unit/test_v2_generation.py`, `tests/unit/generation/test_fr0_budget.py`, `tests/unit/test_r3_10_generation_key_contract.py`, `tests/unit/generation/test_fr0_preflight_lifetime.py`, `tests/unit/generation/test_generate_determinism_ratchets.py`, `tests/unit/generation/test_faker_pool_eligible.py`, `tests/unit/generation/unique/test_pool_opted_out.py`, `tests/parity/_f_audit_support.py`, `tests/parity/test_phase_f_f2_mixed_backend_witness.py`, `tests/parity/_f0_matrix.py`, `tests/parity/_f0_fixtures.py`, `tests/parity/test_phase_f_f0_invariants.py`, and the pinned goldens: `tests/unit/generation/test_pinned_*.py`, `tests/unit/generation/relational/test_routes.py` and `tests/unit/generation/_cf_routes_support.py` (the builder confirms exact paths at the anchor). Any other golden that moves is a stop: the builder reports it and does not regenerate it.
- No change to `GEN_FAMILIES`, the Faker pin, any reason code, or the mask side.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the window rewind error and the provider boundary have fixed messages; the provider raise is made after the `except` closes; seed holders boxed and in the census | AT-S1b-13, AT-S2-4, AT-S2-8 | M-10, M-16 |
| 2 | Cleanup missing on an exit path | pool reservations release through the `ExitStack` callback and on the `selector is None` branch, as S1a; provider pools reserved in preflight | AT-S1b-3, AT-S2-7 | M-3, M-11 |
| 3 | State machine and concurrency | each stream owns its RNG or cursor; the window draw keeps a forward-only cursor and refuses a rewind; a pool build seeds before choosing a locale factory | AT-S1b-5, AT-S1b-7, AT-S1b-7b, AT-S1b-14 | M-4, M-5, M-5c |
| 4 | Route parity and silent fallback | one `pool_eligible`, one `open_faker_pool_draw` and one `pool_key_columns` on every route, required keywords with a signature sentry and an AST guard; the admission matrix is the only route switch; S3a's computed opener runs before `draw_path`; lookup schema decided at admission or declined | AT-S1b-2, AT-S1b-10, AT-S1b-11, AT-S1b-12, AT-S2-2, AT-S2-6b, AT-S2-9 | M-1, M-2a, M-2b, M-6c, M-13, M-14 |
| 5 | Referential integrity | key columns never pool on all four routes including pinned, so a parent key keeps distinct per-row values | AT-S1b-2 | M-1, M-2 |
| 6 | Untrusted producer | the config is the input; `requested_locale` declines a list locale; lookup lists come from pinned digests | AT-S1b-1 | M-6 |
| 7 | Check then use (TOCTOU) on a path | N/A no filesystem access is added; lookup files are read and digested before this code by the existing loader | none needed | N/A no path checks |
| 8 | Weak tests and overclaimed evidence | parity at batch sizes 1, 7 and 4096 with the route asserted; frozen legacy digests for the null cells; perf on the Dell with separate build-order and selector witnesses; goldens listed by name | AT-S1b-9, AT-S2-1, AT-S2-3 | M-7, M-8, M-9 |
| 9 | Behavior-preserving refactor drift | `generate_batch` keeps its bytes through `open_batch_cursor`; `PoolSampler` REUSE through `open_reuse_cursor`; one `weighted_draw` for categorical and lookup | AT-S2-5, AT-S2-5b, AT-S2-10 | M-8, M-15 |
| 10 | Frozen contract drift | byte changes named in the changelog and the compatibility contract; the eligible set generated from certified data | AT-S1b-8, section 9 | M-6 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| No exception context in output | yes | AT-S2-4 asserts no cause or context |
| Normalized guard scanners | yes | the eligible set comes from `certified_pairs.json`; the AST guard walks every module under `generation/` |
| No reaching into private modules | yes | provider and lookup streams live in `generation/kinds/` and are exported from `generation.kinds`; `_column_streams.py` imports only that public surface |
| No hidden CI failures | yes | perf cells carry the `perf` marker and run on the Dell; recorded in the PR |
| Mutations on the final head | yes | section 8 on the final head |
| No raised caps | yes | `DEFAULT_POOL_SIZE` unchanged; two new caps are additions |

## 11. Enumerations

### 11.1 Exit paths

- Pool admitted and built: the stream or window draw serves values (`generation/_column_streams.py:347`, `generation/window.py:195`).
- Pool admitted, build declined: `open_pooled_selector` returns `None` and the column runs per-row (`generation/_faker_pool.py:491`).
- Budget refusal before the build: the ledger raises, as S1a.
- Window draw asked to rewind below its cursor: `RuntimeError`, fixed message (no caller today) (`generation/window.py:352`).
- Table of 0 rows: `pool_eligible` returns False before any build.
- Preflight refusal for a provider pool: before the first write.
- Provider failure in a stream or while it is built: `GENERATION_PROVIDER_FAILED`, no cause (`generation/kinds/_provider.py:79`).
- Lookup or provider column declined at admission (no bound, no schema, non-stock batch adapter): plan on the legacy path (`generation/_admission.py:57`).

### 11.2 Routes

- Legacy resident (`synthesize._faker` via `try_pool`, `generation/_faker_pool.py:292`).
- Pinned (`execute_pinned`, `generation/_pinned_execute.py:201`, to `synthesize._generate_column` directly; no `classify_plan`).
- Streamed (`_run_admitted`, `generation/_streamed.py:352`).
- Window read (`generate_rows`, `generation/window.py:263`).
- Native shadow: unchanged; the admissible set stays the legacy 10 (`execution/physical/_shadow_generation.py:100`).

### 11.3 FK shapes

- `reference` column: its target `(reference_table, reference_column)` is a key column and never pools.
- `inherit` via an FK: the FK's parent key column is a key column and never pools.
- Composite and self-reference FKs: each member column of the target is in the set (the function walks every reference column).

### 11.4 Fields

- `faker_type`, `locale`, `pooled`, `unique`, `faker_kwargs` (non-empty declines Group A and B pooling), `null_probability` on Faker columns.
- `provider`, provider `kwargs`, `locale` on provider columns; `values`, `weights`, `file` on lookup columns.
- Table `row_count` (pool size and build-order mode).

### 11.5 Output surfaces

- Generated column bytes (section 9).
- `generate_rows`: no new refusal; reads past 10,000 on small pooled tables served by the continuation.
- Route label `streamed` for provider and lookup plans (S2); the run card is S4.
- Lookup column Arrow schema on the streamed route (S2).

## 12. Slices

### S1b WIDEN-POOLS

Steps, in order (tests first, red before code):

1. Write AT-S1b-1 to AT-S1b-8, AT-S1b-7b and AT-S1b-10 to AT-S1b-15 and confirm they fail (controls marked).
2. Moves first, no behavior change: tier tables to `scripts/faker-determinism/_tiers.py`; `_referenced_keys` out of `_streamed.py`.
3. Add `TIER_3` to the harness, run it in the locked env, commit digests; add `write_eligible.py` and generate `pool/_eligible.py`.
4. Add `pool/_keys.py` and `PlanAdmission.key_columns`; make `table` and `key_columns` required on `pool_opted_out`; thread `key_columns` through all four routes with no defaults; add the signature sentry and the AST guard.
5. Delete `N_THRESHOLD`; add `pool_size_for`, `open_faker_pool_draw`, the `rows < 1` check and the kwargs decline; reservations pass `P`; seed before `resolve_pool_provider` in `build_pool_values`.
6. Add `PooledSelector.skip`, `stream/_window_pool.py` (forward-only cursor, continuation past 10,000), the window admission change and the `_build_streams` branch.
7. Add the two caps; census rows; update the draw-site notes, both bench scripts (worker and comparison driver) and the README, and the CODEMAP rows.
8. Regenerate the named goldens with the harness; stop on any other golden.
9. Run mutations M-1 to M-6d (with M-2a to M-2c and M-5 to M-5c); run AT-S1b-9 on the Dell.

Files and budgets. The engine module cap is a goal of 600 and a hard max of 700 (`tests/sentry/test_module_size.py`); `scripts/` is held to the same limits. The planner cap of about 800 per slice diff applies to the change, not to a module.

| File | Now | After |
|---|---|---|
| `generation/_faker_pool.py` | 577 | at most 600 (skip +12, `pool_size_for` +6, `open_faker_pool_draw` +25, threshold and the in-place mode branch out); if it passes 600, the build-order draw moves to `pool/_build_order.py` |
| `generation/pool/_eligible.py` | new | about 90 (generated) |
| `generation/pool/_keys.py` | new | about 60 |
| `generation/stream/_window_pool.py` | new | about 90 |
| `generation/_window_admission.py` | 475 | about 485 |
| `generation/window.py` | 385 | about 395 |
| `generation/stream/_window_pool.py` continuation | (in the row above) | about 110 instead of 90 |
| `scripts/bench-generation-pool/bench_compare_gen.py` | measure at anchor | a few lines either way |
| `generation/_admission.py` | 301 | about 310 |
| `generation/_streamed.py` | 592 | about 585 (shrinks) |
| `generation/_pinned_execute.py` | measure at anchor | plus about 5 |
| `scripts/bench-generation-pool/bench_worker_gen.py` | measure at anchor | minus a few |
| `generation/_column_streams.py` | 413 | about 418 |
| `generation/_bounds.py` | 572 | about 575 |
| `generation/synthesize.py` | 587 | about 592 |
| `scripts/faker-determinism/write_eligible.py` | new | about 40 |
| `scripts/faker-determinism/check_determinism.py` | 597 | about 520 (tiers moved out) |
| `scripts/faker-determinism/_tiers.py` | new | about 100 with `TIER_3` |

Public names added: `pool_key_columns`, `referenced_key_columns`, `pool_size_for`, `open_faker_pool_draw`, `PlanAdmission.key_columns`, `PooledSelector.skip`, `WindowPoolDraw`.

Test depth: T0 per edit; T1 impact selection per commit (generation, parity, native draw-site tests, the harness cells for tier 3, the new guard); T2 on the exact head with the risk cells AT-S1b-2, AT-S1b-5, AT-S1b-7 and the harness. Full suite: yes, once on the final head, because S1b regenerates goldens and changes a frozen contract (escalation triggers in `testing.md`). It diffs against the saved main baseline.

### S2 STREAM-PROVIDER-LOOKUP

Steps:

1. On the merged head, confirm: which stock provider bindings get a value cap; the legacy lookup schema inference site; whether GNF S3a has merged (and so whether `open_computed_stream` exists).
2. Write AT-S2-1 to AT-S2-10 and confirm the parity and route tests fail (controls marked).
3. Refactors with no byte change: `open_batch_cursor` on the Faker adapter (AT-S2-5); `PoolSampler.open_reuse_cursor` (AT-S2-5b); `weighted_draw` (AT-S2-10).
4. Add `kinds/_provider_stream.py` and `LookupStream` with their census rows; export from `generation.kinds`; wire `make_column_stream`.
5. Add `provider_payload_bound`, `lookup_payload_bound` and the `lookup_lists` keyword on `compute_payload_bounds`; reserve provider pools in `_streamed._preflight`.
6. Admit `provider` and `lookup` in `ADMISSION_MATRIX`, with the column-level declines and `lookup_stream_schema`.
7. If GNF S3a has merged, call `open_computed_stream` first in `open_provider_stream`, run AT-S2-6b and add the provider stream dispatch to GNF's draw-site choke-point sentry; otherwise leave the step out.
8. Run M-7 to M-16.

| File | Now | After |
|---|---|---|
| `generation/kinds/_provider_stream.py` | new | about 170 |
| `generation/pool/_sampler.py` | measure at anchor | about +12 |
| `generation/kinds/_categorical.py` | measure at anchor | about +10 (`weighted_draw`) |
| `generation/kinds/__init__.py` | measure at anchor | about +4 |
| `generation/_column_streams.py` | about 418 | about 440 (lookup ctx with digests) |
| `generation/_streamed.py` | about 585 | about 598 before S3a; recount on the combined S2 and S3a head. If it passes 600, `_pooled_columns` moves to `_admission.py` first (section 14) |
| `generation/_bounds.py` | about 575 | about 595 (two bounds, the keyword) |
| `generation/_admission.py` | about 310 | about 320 |
| `generation/kinds/_provider.py` | 159 | about 165 |
| `generation/kinds/_lookup.py` | 289 | about 345 (`LookupStream`, `lookup_stream_schema`) |
| `providers_v2/_faker_adapter.py` | 282 | about 295 |

Public names added: `open_provider_stream`, `LookupStream`, `lookup_stream_schema`, `weighted_draw`, `provider_payload_bound`, `lookup_payload_bound`, `PoolSampler.open_reuse_cursor`, `open_batch_cursor` (adapter method).

Test depth: T0 and T1 as above; T2 on the exact head with AT-S2-1 and the mutations. Full suite only if an escalation trigger is hit; none is expected (no golden moves, no frozen contract changes).

### Order and dependencies

1. #813 (S1a) merges first. S1b, S2 and GNF S3a all build on its `generation/stream/` package.
2. GSA S1b and GNF S3a (`origin/docs/plans-pap-gnf-1125:docs/plans/2026-11-25-gen-nonfaker-draws-s3.md`) can build in parallel. Both touch `_bounds.py` (`faker_payload_bound`), `_window_admission.py`, `window._build_streams` and `_column_streams._faker_stream`; the second to merge rebases (text conflicts only). S1b pools no type that S3a computes (`uuid4`, `random_int`, `random_element`), so admission does not overlap. Where both reach `_faker_stream` and `_build_streams`, the computed check runs first, then the pool check, then per-row. S1b making pooled columns Class A in windows removes the Class B block that GNF deferred `text` and `paragraph` on; GNF's plan should note this.
3. GNF S3a merges before GSA S2, so `open_provider_stream` calls S3a's public `open_computed_stream` before `draw_path` (S3a adds no `"computed"` value to `draw_path`). If S3a slips, S2 merges without that call and S3a adds it to `open_provider_stream` (its F5 note already says the second to merge rebases `kinds/_provider.py`). Either way AT-S2-6b runs on the second head. Merge-order rule: GNF's choke-point sentry names four draw sites with no free-form allowlist, and the S2 provider stream dispatch is a fifth. Whichever of GNF S3a and GSA S2 merges second adds that site to the sentry in the same PR.
4. S2 before S3; S3 before S4. GEN-PER-COLUMN S1 starts only after S1a, S2 and S3 have landed (master plan cross-plan gate).

## 13. S3 and S4 outline

- S3 STATISTICAL-INHERIT. New `statistical/_stream.py` (about 120) and `relational/_inherit_stream.py` (about 100). Statistical columns stream with a fidelity accumulator (OWNER CALL master plan Q2, default: the accumulator, as recommended). The inherit parent map is reserved in the ledger before it is built. Tests A7, A8, A13. Depends on S2. `_streamed.py` is near its cap; S3 moves code out before it adds any.
- S4 ROUTE-CODES-CARD. `reasons/route/_generation.py` with `gen_legacy_*` codes, `quality_metrics["generation_route"]`, and the CLI `Generation` fact and `--json` block. Tests A9, A11. Depends on S3.

## 14. Pre-mortem

- A read past 10,000 on a small pooled table builds the full 10,000-value prefix and skips the selector, so a far page (offset 1e9) costs the build plus about 3 s of skip. Accepted for V1: slower, not broken, and no V1 CLI path reads it.
- A Faker update changes how a locale-list proxy picks its factory. AT-S1b-14 pins the digest, so the Faker pin bump fails loudly.
- The window pays the pool build on every `generate_rows` call (up to about 1.2 s for `email` at 10,000 values; a build-order page pays only up to its end). `WindowPoolDraw` is built per call, so every page of a large table also re-skips from offset 0 (one cursor per call, forward only). A preview that pages often pays both each page. `deadline_s` is checked only between chunks, so it does not interrupt a build or a skip inside one chunk. Accepted for V1: slower, not broken. Follow-up: a pool and cursor cache keyed by build seed (not in this row).
- A harness run on a different Faker version would certify the wrong digests. The builder runs it in the locked env, and AT-S1b-8 ties the eligible set to the committed digests.
- A new caller of `pool_opted_out` on a parallel branch fails because `key_columns` is required. That is the intended failure.
- `_streamed.py` grows past 600 on a rebase or in S2. The builder moves `_pooled_columns` into `_admission.py` before adding the provider preflight.
- A skip from offset 0 to 1e9 costs about 3 s, and per-call construction repeats it every page. The deadline is not checked inside it. Accepted for V1 with the cache follow-up above.
- A new route that reaches `pool_eligible` without a key set (as pinned did before this plan). The signature sentry and the AST guard make that a test failure, not a silent pool.
- The streamed sink on a mid-stream ledger refusal: S2's preflight closes the provider pool case before the first write. Whether the sink is transactional on other mid-stream refusals is unchanged by this plan.
