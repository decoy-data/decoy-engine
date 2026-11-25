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

- G1. A pool-admitted Faker column produces the same bytes on the legacy path, the streamed path at any batch size, and a window read at any offset inside the column's defined range.
- G2. A column that is a key (a `reference` target or an `inherit` parent key) or `unique: true` never pools, on every admission site.
- G3. A `provider` or `lookup` column streams with bytes equal to the legacy path at every batch size, and a plan with only fast kinds reports `streamed`.
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
| Lookup draw | `lookup_values`, `lookup_column_values` | `generation/kinds/_lookup.py` |
| Null mask on streams | `NullMaskedStream` | `generation/_column_streams.py:249` |
| Reference targets | `_referenced_keys` | `generation/_streamed.py` (S1a) |
| Inherit edges | `iter_generate_input_refs` | `generation/relational/_inherit.py` |

## 5. Design

### 5.1 Choke point: one key-column set

New `generation/pool/_keys.py` (about 60 lines) has two functions:

- `pool_key_columns(configs) -> frozenset[tuple[str, str]]`: every `(reference_table, reference_column)` of a `type: reference` column, and every inherit parent key, read as `(edge.source_table, edge.source_key)` from each edge that `iter_generate_input_refs` yields (`config/_generate_relational/__init__.py:543`). An edge with an empty `source_key` is skipped. `source_key` is set for every input read through a foreign key, not only inherit (`config/_generate_relational/__init__.py:499-502`), so the set is slightly wider than reference and inherit targets; every member is a key another table reads, so a per-row draw for it is the safe side. Composite targets add each member column.
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

- Build order (`rows <= 10_000`): it builds `min(window_end, 10_000)` values. Build order is prefix-stable and does not depend on `rows`, so value `i` is the same for every table length, equal to the full run's value `i` for `i < rows`, and page 0 (count 100) of a 9,000-row table costs 100 Faker calls, not 9,000. A read with `window_end > 10_000` refuses with `CODE_WINDOW_INVALID` and a fixed message ("window passes the pool of a pooled column"). Reads past `row_count` and inside 10,000 are served, as for any Class A column.
- Selector (`rows > 10_000`): it builds the pool of `P` values and holds a `PooledSelector` with a cursor. A chunk at `offset == cursor` takes `size` and advances. A chunk at `offset > cursor` calls the new `PooledSelector.skip(n)`, which draws and discards indices in chunks of at most 1,048,576, so no large array is held. A chunk at `offset < cursor` reopens the selector from the seed and skips. Offsets past `row_count` are served.
- `_window_admission._class_b_reason` no longer returns `pooled_faker`. A pooled column runs `_check_faker` like a per-row column, so the cell cap still applies.
- `window._build_streams` (`generation/window.py:195-202`) uses `WindowPoolDraw` when `pool_eligible` admits the column and `PerRowFakerStream` otherwise. The decision is the same `pool_eligible(..., rows, opted_out=pool_opted_out(col, table=..., key_columns=...))` call as the full run, with `rows` the declared `row_count`. The window computes `key_columns` once per `generate_rows` call from the config it already holds.
- `WindowPoolDraw` is built lazily: `_build_streams` (`generation/window.py:322`) only records the column, and the pool is built on the first draw call, inside the chunk loop after its `deadline_s` check (`generation/window.py:353`). A call whose deadline has passed before the first chunk does not build. The build and a skip inside one chunk are not interrupted by the deadline; 14 states the cost.

The refusal past 10,000 is a contract change. The `window.py` docstring (`:283-284`) says "Offsets past the declared row_count are served: Class A values do not depend on the table length". That stays true for values. S1b adds one sentence: a pooled column on a table of at most 10,000 rows refuses a window that ends past 10,000. It records a `Breaking:` line. Callers:

- The V1 CLI does not call `generate_rows`; `decoy run --rows` scales `row_count`.
- The platform `generation_child.py` passes user offsets and maps `CODE_WINDOW_INVALID` to `window_invalid`. The platform is parked; the changelog line names this mapping.

A read past 10,000 on a table of at most 10,000 rows is a value the full run never produces, so the refusal is not a V1 function break.
- `PooledSelector.skip` is about 12 lines in `_faker_pool.py`.

### 5.5 Native shadow and draw sites

- `execution/physical/_shadow_generation.py:100` sets `SHADOW_ADMISSIBLE_FAKER_TYPES = POOL_ELIGIBLE_FAKER_TYPES`. It stays the legacy 10, so a column of a new type keeps the shadow decline it has today.
- The `gen.faker_pool_build` notes in `execution/native/_draw_sites_gen_pool.py` cite `n >= N_THRESHOLD`; they change to "pool size `min(rows, 10_000)`; build order at or below 10,000 rows". The selection site note changes from `partitionable=False` to say it is partitionable through `skip`; the flag value itself is a native contract and is not changed in S1b.
- `scripts/bench-generation-pool/bench_worker_gen.py:203` assigns `_faker_pool.N_THRESHOLD`, and its README cites it. After the deletion the assignment would do nothing. S1b removes the override argument from the script and the README line.

### 5.6 S2: provider streams

New `generation/stream/_provider.py` (about 160 lines). `make_column_stream` (`generation/_column_streams.py:330-358`) dispatches `provider` to `open_provider_stream(col, ctx, registry, ...)`, which reads `draw_path(caps)` (`generation/kinds/_provider.py:45`) once:

- `"pool"`: `PooledProviderStream` builds the pool once with the same `PoolBuilder(registry).build(size=DEFAULT_POOL_SIZE, job_seed=build_seed, locale=locale)` call (`generation/kinds/_provider.py:127-129`) and keeps one `np.random.default_rng(selection_seed)`. Each batch draws `integers(0, pool.size, size=batch)`, the call `PoolSampler.sample(..., REUSE)` makes for the whole table (`pool/_sampler.py:279-281`; AT-S2-1 proves the two agree). Provider pools keep `DEFAULT_POOL_SIZE` and do not take `pool_size_for`: S2 is a parity slice and changes no bytes. The Faker and provider rules differ on purpose until a later row decides otherwise.
- Provider pool memory: `_streamed._preflight` (`:241`) reserves only Faker pooled columns today. S2 adds provider pool columns to the same preflight, so routing sees the full cost and a tight budget refuses before the first write (AT-S2-7).
- `"keyed"`: `KeyedProviderStream` calls `adapter.generate(provider, spec=ProviderSpec(locale, deterministic=True, namespace=namespace, seed=value_seed), source_value=offset + i)` per row, the exact legacy call (`generation/kinds/_provider.py:146-151`). Stateless.
- `"batch"`: `BatchProviderStream` holds one seeded provider instance across batches. `generate_batch` (`providers_v2/_faker_adapter.py:197`) builds a fresh instance per call (`:230-234`), so calling it per batch would restart the sequence. S2 adds `open_batch_cursor(provider, spec) -> Callable[[int], list]` to the Faker adapter only, about 15 lines: it builds the seeded instance once and returns `k` values per call. `generate_batch` becomes `open_batch_cursor(...)(count)`, so legacy bytes do not change. `draw_path` (`kinds/_provider.py:45`) returns `"batch"` only for `backend_type == "faker"`, so the Mimesis adapter needs no cursor. An adapter without `open_batch_cursor` keeps that column declined (legacy path).
- `"computed"` (only if GNF S3a has merged): the stream dispatches to `ComputedDrawStream` from `generation/stream/_computed_draw.py`. If S3a has not merged, S2 does not add this branch.

New seed holders (the `WindowPoolDraw` selection seed kept for reopen, the `KeyedProviderStream` value seed, the `PooledProviderStream` selection seed, the batch-cursor seed) hold the seed in an `OpaqueBox` or a `repr=False` field and get rows in `secret_material_census.json`. The census test covers them (AT-S1b-13, AT-S2-8).

Every stream applies `_as_text` and the same error boundary as `provider_generate`: any failure raises `GenerationError(GENERATION_PROVIDER_FAILED)` with `from None` and a message with no value.

### 5.7 S2: lookup streams

`LookupStream` in the same module: one `random.Random(ctx.base_int("py"))` held across batches; each batch is `choices(values, weights, k=batch)`. The list comes from `legacy_kwargs["lookup_lists"][(table, name)]`, and the context is built with `content_digests=lookup_digests(...)` exactly as `lookup_column_values` does. The stream holds a reference to the resident list, not a copy. Today `make_column_stream` builds `ctx` without content digests (`generation/_column_streams.py:319`), and `GenDeriveContext.for_column` fingerprints at construction (`generators/derivation.py:300`), which refuses a file-backed lookup without digests (`kinds/_lookup.py:262-263`). So S2 adds a `lookup_lists` keyword to `make_column_stream` (passed by `_streamed` from its `legacy_kwargs`) and, for a lookup column, builds `ctx` with `content_digests=lookup_digests(col, lookup)` before dispatch. That one context feeds both `LookupStream` and the outer `NullMaskedStream(inner, ctx, null_prob)`, so the null seed matches the legacy `null_seed_digests(..., lookup_lists)` path. AT-S2-3 uses a file-backed lookup to prove it.

### 5.8 S2: admission

`ADMISSION_MATRIX` (`generation/_admission.py:57-60`) marks `provider` and `lookup` admitted. The per-column check declines a `provider` column whose adapter lacks `open_batch_cursor` on the `"batch"` path, and a `lookup` column whose list is missing from the legacy kwargs (it then fails on the legacy path with today's error).

### 5.9 Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_keys.py` | `generation/pool/` (16 modules; `generation/` already has 26 direct modules) | new CODEMAP row "pool key columns"; imports config only | `pool/_resident.py` |
| `_eligible.py` | `generation/pool/` | same | `pool/_resident.py` |
| `_window_pool.py` | `generation/stream/` | `generation/_column_streams.py` row (persistent per-column generators); `stream/` is S1a's sub-package for them | `stream/_batches.py` |
| `_provider.py` | `generation/stream/` | same | `stream/_batches.py` |
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
| Window read ending past 10,000 on a pooled table of at most 10,000 rows | `GenerationWindowError(CODE_WINDOW_INVALID)`, fixed message. |
| Window read on a pooled large table at offset 9M | Skip from the cursor; bytes equal the full run. |
| Pool build declined (custom override, locale unavailable) | `open_pooled_selector` returns `None` and the column runs per-row, as today. |
| Budget too small for the pool | The ledger refuses before the build, as S1a. |
| Provider raises in a streamed batch | `GenerationError(GENERATION_PROVIDER_FAILED)`, no cause, no value. |
| Lookup list missing | Declined at admission; the legacy path keeps today's error. |
| Budget too small for a provider pool | Preflight refuses before the first write. |
| Custom Faker provider | Per-row legacy, as today. |

## 7. Acceptance tests

Each test fails before its slice unless marked as a control. Master plan numbers in brackets.

S1b:

- AT-S1b-1 [A1]. `pool_eligible` admits the legacy 10 in `pt_BR`; it admits each certified Group A and B pair and refuses an uncertified pair; no clock-dependent type is admitted in any locale (checked against `_CLOCK_FAKER_EXACT`).
- AT-S1b-2 [A12]. For a plan where `users.email` is a `reference` target and `orders.addr` is an inherit parent key, a spy on `open_faker_pool_draw` sees no call for those columns on the legacy path, the streamed path, `generate_rows` and `execute_pinned`, and a spy on `pool_eligible` returns false for them on all four. A sibling ordinary `email` column calls `open_faker_pool_draw` on all four, at 9 rows and at 20,000 rows. A pinned 20,000-row `users.email` reference target has 20,000 distinct values.
- AT-S1b-3 [A15]. Tables of 0 and 1 rows generate on all routes with no pool error. A 9-row table with a Group B column reserves exactly `faker_pool_resident_bytes(9, payload)` and its values equal the first 9 provider calls of a fresh seeded instance.
- AT-S1b-4 [A4]. `faker_value_cap` returns a fixed cap for all 16 new types; preflight runs with a provider snapshot that raises on any call.
- AT-S1b-5. Window parity. A 9,000-row `email` table read at `offset=0, count=100` builds 100 values, counted by a spy. For `email` at 9 rows: `(0, 1)`, `(0, 9)` and `(7, 2)` equal the full run's slice (all inside the table, all inside 10,000). For `email` at 120,000 rows: `(0, 1)`, `(7, 13)`, `(4096, 5000)` and `(119_990, 10)` equal the full streamed run's slice. The 120,000-row case reads offsets out of order (4096, then 7) to cover the reopen path. Fails before: the 120,000-row table is Class B, and the 9-row values differ.
- AT-S1b-6. A 9-row pooled table read at `offset=9_995, count=10` refuses with `CODE_WINDOW_INVALID`; the message contains no generated value. A read at `offset=9, count=1` (past `row_count`, inside 10,000) returns the build-order value 9, and the docstring of `generate_rows` no longer says Class A values do not depend on the table length.
- AT-S1b-7. `PooledSelector.skip(n)` then `take(k)` equals `take(n + k)[n:]` for `n` in `{0, 1, 1_048_575, 1_048_577, 3_000_001}`, plus a Hypothesis property on `n` up to 4M.
- AT-S1b-8. `pool/_eligible.py` equals the output of `write_eligible.py` on the committed `certified_pairs.json` (drift guard).
- AT-S1b-9 [A10, perf, Dell vm-run]. Also: `bench_worker_gen.py` runs with no `N_THRESHOLD` reference (grep check). 10M rows of `email` stream in under 3 s; 10M `first_name` in under 1.0 s. Recorded in the PR.
- AT-S1b-10. The signature sentry of section 5.1 passes on the tree and fails when any function on the four chains gives `key_columns` a default.
- AT-S1b-11. The AST guard of section 5.1 passes on the tree and fails on a seeded scratch file that calls `pool_eligible(..., opted_out=False)`.
- AT-S1b-12. For one `email` column at 9 and 120,000 rows, legacy `try_pool`, streamed `_faker_stream` and `WindowPoolDraw` give equal bytes, and each calls `open_faker_pool_draw`. A Group B column with `faker_kwargs={"domain": "x.test"}` runs per-row on all three. `pool_opted_out` called without `table` raises `TypeError`.
- AT-S1b-13. The secret-material census test lists the `WindowPoolDraw` seed holder, and `repr(WindowPoolDraw(...))` shows no seed bytes.
- Controls [A2, A3]: S1a take parity and batch invariance pass at batches `{7, 4096}` for every new type.

S2:

- AT-S2-1 [A5]. For each draw path (`pool`, `keyed`, `batch`) and for `lookup` with and without weights, the streamed bytes at batch sizes `{1, 7, 4096}` equal the legacy bytes, and the run reports route `streamed`. The batch path runs with a Faker provider; a Mimesis provider is checked on the paths `draw_path` gives it.
- AT-S2-2 [A6]. A plan with `sequence`, `provider` and `lookup` columns reports `streamed`; before S2 it reports legacy.
- AT-S2-3. With `null_probability: 0.3`, provider and lookup streams equal legacy bytes (the mask positions match `_apply_null_probability`). The lookup cell uses a file-backed lookup, so the content digests enter the null seed.
- AT-S2-4. A provider that raises inside batch 3 gives `GENERATION_PROVIDER_FAILED`; `__cause__` and `__context__` are `None`; the message does not contain the raised text.
- AT-S2-5 (control). `generate_batch` output is byte-identical before and after the `open_batch_cursor` refactor for Faker at count 1 and 4096.
- AT-S2-6. An adapter without `open_batch_cursor` on the `"batch"` path keeps the plan on legacy, and the result equals today.
- AT-S2-7. A plan with a pooled provider column and a budget below its pool size refuses in preflight; a spy sink sees no write.
- AT-S2-8. The census test lists the provider stream seed holders, and their `repr` shows no seed bytes.

## 8. Named mutations

Each must turn the named test red on the final head.

- M-1. `pool_opted_out` ignores `key_columns`: AT-S1b-2 red.
- M-2. `execute_pinned` passes `frozenset()`, or `_generate_column` gives `key_columns` a default of `frozenset()`: AT-S1b-2 (pinned leg) and AT-S1b-10 red.
- M-2b. `window._build_streams` passes an empty key set: AT-S1b-2 (window leg) red.
- M-3. Pool size stays `DEFAULT_POOL_SIZE` for `rows < P`: AT-S1b-3 red.
- M-4. `skip` draws `n - 1` indices: AT-S1b-7 and AT-S1b-5 red.
- M-5. The reopen path (offset below cursor) continues from the cursor: AT-S1b-5 red.
- M-6. `_eligible.py` gains a hand-written pair: AT-S1b-8 red.
- M-6b. `pool_eligible` drops the `rows < 1` check: AT-S1b-3 red.
- M-6c. The streamed route computes its own build-order rule instead of `open_faker_pool_draw`: AT-S1b-12 red.
- M-6d. Group A and B pairs ignore `faker_kwargs`: AT-S1b-12 red.
- M-7. `PooledProviderStream` draws a fresh `default_rng(selection_seed)` per batch: AT-S2-1 red at batch 7.
- M-8. `BatchProviderStream` calls `generate_batch` per batch: AT-S2-1 red at batch 7.
- M-9. `LookupStream` builds `random.Random` per batch: AT-S2-1 red.
- M-10. The provider error boundary uses `raise ... from exc`: AT-S2-4 red.
- M-11. Preflight leaves provider pools out: AT-S2-7 red.
- M-12. `LookupStream` is null-masked with a context built without the lookup digests: AT-S2-3 red.

## 9. Frozen contracts and byte changes

- Generate output bytes change for: pool-eligible legacy-10 columns with fewer than 50,000 rows (now pooled); legacy-10 columns of 50,000 rows or more that are reference or inherit targets (now per-row under the key opt-out); and Group A and B columns in certified locales at every row count. The CLI `decoy run --rows N` preview (`decoy/src/decoy/cli/gen/_preview.py`) scales `row_count`. When the full table has at most 10,000 rows, preview and full run both use build order, so the preview is a prefix of the full run. When the full table has more than 10,000 rows (before S1b, 50,000 or more), the full run uses the selector and the preview is not a prefix; the changelog says so. One `Breaking:` line in `changelog.d/gen-stream-all-s1b.md` and an entry in `docs/compatibility-contract.md` section 1 as a pre-GA correction. Types and value sets do not change.
- `generate_rows` windows ending past 10,000 on a pooled table of at most 10,000 rows now refuse. Values do not depend on `row_count`. Same `Breaking:` line, which names the platform `window_invalid` mapping in `generation_child.py`.
- S2 changes no bytes (AT-S2-1 is parity).
- Golden files regenerated by the harness, by name (master plan section 10): `tests/native/test_determinism_goldens.py`, `tests/native/test_pooled_faker_draw_sites.py`, `tests/unit/test_v2_generation.py`, `tests/unit/generation/test_fr0_budget.py`, `tests/unit/test_r3_10_generation_key_contract.py`, `tests/unit/generation/test_fr0_preflight_lifetime.py`, `tests/unit/generation/test_generate_determinism_ratchets.py`, `tests/unit/generation/test_faker_pool_eligible.py`, `tests/unit/generation/unique/test_pool_opted_out.py`, `tests/parity/_f_audit_support.py`, `tests/parity/test_phase_f_f2_mixed_backend_witness.py`, `tests/parity/_f0_matrix.py`, `tests/parity/_f0_fixtures.py`, `tests/parity/test_phase_f_f0_invariants.py`, and the pinned goldens: `tests/unit/generation/test_pinned_*.py`, `tests/unit/generation/relational/test_routes.py` and `tests/unit/generation/_cf_routes_support.py` (the builder confirms exact paths at the anchor). Any other golden that moves is a stop: the builder reports it and does not regenerate it.
- No change to `GEN_FAMILIES`, the Faker pin, any reason code, or the mask side.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the one new refusal and the provider boundary have fixed messages; `from None`; seed holders boxed and in the census | AT-S1b-6, AT-S1b-13, AT-S2-4, AT-S2-8 | M-10 |
| 2 | Cleanup missing on an exit path | pool reservations release through the `ExitStack` callback and on the `selector is None` branch, as S1a; provider pools reserved in preflight | AT-S1b-3, AT-S2-7 | M-3, M-11 |
| 3 | State machine and concurrency | each stream owns its RNG or cursor; the window draw keeps a cursor and reopens below it | AT-S1b-5, AT-S1b-7 | M-4, M-5 |
| 4 | Route parity and silent fallback | one `pool_eligible`, one `open_faker_pool_draw` and one `pool_key_columns` on every route, required keywords with a signature sentry and an AST guard; the admission matrix is the only route switch | AT-S1b-2, AT-S1b-10, AT-S1b-11, AT-S1b-12, AT-S2-2 | M-1, M-2, M-6c |
| 5 | Referential integrity | key columns never pool on all four routes including pinned, so a parent key keeps distinct per-row values | AT-S1b-2 | M-1, M-2 |
| 6 | Untrusted producer | the config is the input; `requested_locale` declines a list locale; lookup lists come from pinned digests | AT-S1b-1 | M-6 |
| 7 | Check then use (TOCTOU) on a path | N/A no filesystem access is added; lookup files are read and digested before this code by the existing loader | none needed | N/A no path checks |
| 8 | Weak tests and overclaimed evidence | parity at batch sizes 1, 7 and 4096 with the route asserted; perf on the Dell; goldens listed by name | AT-S1b-9, AT-S2-1 | M-7, M-8, M-9 |
| 9 | Behavior-preserving refactor drift | `generate_batch` keeps its bytes through `open_batch_cursor` | AT-S2-5 | M-8 |
| 10 | Frozen contract drift | byte changes named in the changelog and the compatibility contract; the eligible set generated from certified data | AT-S1b-8, section 9 | M-6 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| No exception context in output | yes | AT-S2-4 asserts no cause or context |
| Normalized guard scanners | yes | the eligible set comes from `certified_pairs.json`; the AST guard walks every module under `generation/` |
| No reaching into private modules | yes | `stream/_provider.py` imports `kinds/_provider` and `generation.pool` names only |
| No hidden CI failures | yes | perf cells carry the `perf` marker and run on the Dell; recorded in the PR |
| Mutations on the final head | yes | section 8 on the final head |
| No raised caps | yes | `DEFAULT_POOL_SIZE` unchanged; two new caps are additions |

## 11. Enumerations

### 11.1 Exit paths

- Pool admitted and built: the stream or window draw serves values (`generation/_column_streams.py:347`, `generation/window.py:195`).
- Pool admitted, build declined: `open_pooled_selector` returns `None` and the column runs per-row (`generation/_faker_pool.py:491`).
- Budget refusal before the build: the ledger raises, as S1a.
- Window read past the pool of a small pooled column: `CODE_WINDOW_INVALID`.
- Table of 0 rows: `pool_eligible` returns False before any build.
- Preflight refusal for a provider pool: before the first write.
- Provider failure in a stream: `GENERATION_PROVIDER_FAILED`, no cause.

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
- `generate_rows` refusals: one new case of an existing code.
- Route label `streamed` for provider and lookup plans (S2); the run card is S4.

## 12. Slices

### S1b WIDEN-POOLS

Steps, in order (tests first, red before code):

1. Write AT-S1b-1 to AT-S1b-8 and AT-S1b-10 to AT-S1b-13 and confirm they fail.
2. Moves first, no behavior change: tier tables to `scripts/faker-determinism/_tiers.py`; `_referenced_keys` out of `_streamed.py`.
3. Add `TIER_3` to the harness, run it in the locked env, commit digests; add `write_eligible.py` and generate `pool/_eligible.py`.
4. Add `pool/_keys.py` and `PlanAdmission.key_columns`; make `table` and `key_columns` required on `pool_opted_out`; thread `key_columns` through all four routes with no defaults; add the signature sentry and the AST guard.
5. Delete `N_THRESHOLD`; add `pool_size_for`, `open_faker_pool_draw`, the `rows < 1` check and the kwargs decline; reservations pass `P`.
6. Add `PooledSelector.skip`, `stream/_window_pool.py`, the window admission change, the `_build_streams` branch and the docstring change.
7. Add the two caps; census rows; update the draw-site notes, the bench script and README, and the CODEMAP rows.
8. Regenerate the named goldens with the harness; stop on any other golden.
9. Run mutations M-1 to M-6d; run AT-S1b-9 on the Dell.

Files and budgets. The engine module cap is a goal of 600 and a hard max of 700 (`tests/sentry/test_module_size.py`); `scripts/` is held to the same limits. The planner cap of about 800 per slice diff applies to the change, not to a module.

| File | Now | After |
|---|---|---|
| `generation/_faker_pool.py` | 577 | at most 600 (skip +12, `pool_size_for` +6, `open_faker_pool_draw` +25, threshold and the in-place mode branch out); if it passes 600, the build-order draw moves to `pool/_build_order.py` |
| `generation/pool/_eligible.py` | new | about 90 (generated) |
| `generation/pool/_keys.py` | new | about 60 |
| `generation/stream/_window_pool.py` | new | about 90 |
| `generation/_window_admission.py` | 475 | about 485 |
| `generation/window.py` | 385 | about 395 |
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

1. Write AT-S2-1 to AT-S2-6 and confirm the parity and route tests fail.
2. Add `open_batch_cursor` to the Faker adapter; `generate_batch` calls it (AT-S2-5 stays green).
3. Add `stream/_provider.py` with the four streams and their census rows; wire `make_column_stream`.
4. Add provider pools to `_streamed._preflight`.
5. Admit `provider` and `lookup` in `ADMISSION_MATRIX`, with the two column-level declines.
6. If GNF S3a has merged, add the `"computed"` branch and add the provider stream dispatch to GNF's draw-site choke-point sentry; otherwise leave the branch out.
7. Run M-7 to M-12.

| File | Now | After |
|---|---|---|
| `generation/stream/_provider.py` | new | about 160 |
| `generation/_column_streams.py` | about 418 | about 440 (lookup ctx with digests) |
| `generation/_streamed.py` | about 585 | about 598 (provider preflight) |
| `generation/_admission.py` | about 310 | about 320 |
| `generation/kinds/_provider.py` | 159 | about 165 |
| `generation/kinds/_lookup.py` | 289 | about 292 |
| `providers_v2/_faker_adapter.py` | 282 | about 295 |

Public names added: `open_provider_stream`, `open_batch_cursor` (adapter method).

Test depth: T0 and T1 as above; T2 on the exact head with AT-S2-1 and the mutations. Full suite only if an escalation trigger is hit; none is expected (no golden moves, no frozen contract changes).

### Order and dependencies

1. #813 (S1a) merges first. S1b, S2 and GNF S3a all build on its `generation/stream/` package.
2. GSA S1b and GNF S3a (`origin/docs/plans-pap-gnf-1125:docs/plans/2026-11-25-gen-nonfaker-draws-s3.md`) can build in parallel. Both touch `_bounds.py` (`faker_payload_bound`), `_window_admission.py`, `window._build_streams` and `_column_streams._faker_stream`; the second to merge rebases (text conflicts only). S1b pools no type that S3a computes (`uuid4`, `random_int`, `random_element`), so admission does not overlap. Where both reach `_faker_stream` and `_build_streams`, the computed check runs first, then the pool check, then per-row. S1b making pooled columns Class A in windows removes the Class B block that GNF deferred `text` and `paragraph` on; GNF's plan should note this.
3. GNF S3a merges before GSA S2, so S2's provider stream dispatches the `"computed"` path to `ComputedDrawStream`. If S3a slips, S2 merges without that branch and S3a adds it (its F5 note already says the second to merge rebases `kinds/_provider.py`). Merge-order rule: GNF's choke-point sentry names four draw sites with no free-form allowlist, and the S2 provider stream dispatch is a fifth. Whichever of GNF S3a and GSA S2 merges second adds that site to the sentry in the same PR.
4. S2 before S3; S3 before S4. GEN-PER-COLUMN S1 starts only after S1a, S2 and S3 have landed (master plan cross-plan gate).

## 13. S3 and S4 outline

- S3 STATISTICAL-INHERIT. New `statistical/_stream.py` (about 120) and `relational/_inherit_stream.py` (about 100). Statistical columns stream with a fidelity accumulator (OWNER CALL master plan Q2, default: the accumulator, as recommended). The inherit parent map is reserved in the ledger before it is built. Tests A7, A8, A13. Depends on S2. `_streamed.py` is near its cap; S3 moves code out before it adds any.
- S4 ROUTE-CODES-CARD. `reasons/route/_generation.py` with `gen_legacy_*` codes, `quality_metrics["generation_route"]`, and the CLI `Generation` fact and `--json` block. Tests A9, A11. Depends on S3.

## 14. Pre-mortem

- The window pays the pool build on every `generate_rows` call (up to about 1.2 s for `email` at 10,000 values; a build-order page pays only up to its end). `WindowPoolDraw` is built per call, so every page of a large table also re-skips from offset 0. A preview that pages often pays both each page. `deadline_s` is checked only between chunks, so it does not interrupt a build or a skip inside one chunk. Accepted for V1: slower, not broken. Follow-up: a pool and cursor cache keyed by build seed (not in this row).
- A harness run on a different Faker version would certify the wrong digests. The builder runs it in the locked env, and AT-S1b-8 ties the eligible set to the committed digests.
- A new caller of `pool_opted_out` on a parallel branch fails because `key_columns` is required. That is the intended failure.
- `_streamed.py` grows past 600 on a rebase or in S2. The builder moves `_pooled_columns` into `_admission.py` before adding the provider preflight.
- A skip from offset 0 to 1e9 costs about 3 s, and per-call construction repeats it every page. The deadline is not checked inside it. Accepted for V1 with the cache follow-up above.
- A new route that reaches `pool_eligible` without a key set (as pinned did before this plan). The signature sentry and the AST guard make that a test failure, not a silent pool.
- The streamed sink on a mid-stream ledger refusal: S2's preflight closes the provider pool case before the first write. Whether the sink is transactional on other mid-stream refusals is unchanged by this plan.
