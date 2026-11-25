Status: plan

# GEN-STREAM-ALL S1b and S2: Faker pools widen, and provider and lookup columns stream

Rules consulted: `/home/cam/dev-rules/00-universal.md`, `/home/cam/dev-rules/risk-and-exceptions.md`, `/home/cam/dev-rules/development-loop.md`, `/home/cam/dev-rules/cross-cutting-concerns.md`, `/home/cam/dev-rules/testing.md` (Test depth), `/home/cam/dev-rules/workspace-and-vcs.md` (Commit messages), the plan contract and defect catalog (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`), and the row's master plan `origin/plan/gen-stream-all:docs/plans/2026-11-22-gen-stream-all.md` (sections 5 to 10, owner decision 2026-11-23).

Row: GEN-STREAM-ALL. Repo: decoy-engine. Risk: R2 (frozen bytes and determinism). Anchor: PR #813, `aa1c65631`, including `requested_locale` and `open_column_faker`. Recheck paths, budgets and mutations on the merged head. Source counts below use that object. The #813 worktree now points to its child `dca2db39a`. S1b requires that child's multi-locale replay fix on the merged dependency. It is the baseline for AT-S1b-14: at the older hash reflection still captures the initially selected method.

This file plans S1b and S2 in full. S3 and S4 are an outline (section 13) and get their own plan after S2 merges.

## 1. Frame

S1a (#813) gave the streamed core a `generation/stream/` package, resident pool sizing in `pool/_resident.py`, and one locale helper. Two gaps remain for the generator kinds the master plan calls fast:

- Faker pools are narrow. `pool_eligible` (`generation/_faker_pool.py:255`) admits the legacy 10 types in any locale and the certified locale pairs, and only from `N_THRESHOLD = 50_000` rows (`generation/_faker_pool.py:237`). The owner decision of 2026-11-23 widens pools to Group A (`word`, `sentence`, `date_of_birth`) and Group B (`email`, `safe_email`, `free_email`, `company_email`, `user_name`, `phone_number`, `url`, `domain_name`, `ipv4`, `street_address`, `address`, `postcode`, `zipcode`) on ordinary columns, with opt-out for `unique: true` and for `reference` / `inherit` key columns.
- `provider` and `lookup` columns are declined by `ADMISSION_MATRIX` (`generation/_admission.py:57-60`), so one such column sends the whole plan to the legacy resident path.

S1b widens ordinary Faker pools. S2 streams the parity-safe subset specified below.

## 2. Guarantee and non-goals

Guarantee:

- G1. Full-run Faker values agree at every batch size. Preserve each route's existing schema for empty and fully masked ordinary Faker columns without a declared cast (AT-S1b-3). Every previously served window stays accessible. In-table Class A reads match the full run. Beyond the table, each row is a direct per-row draw at its absolute position. Pages concatenate across either boundary. Section 8.4 defines the seek limit for historical Class B columns.
- G2. A column that is a key (a `reference` target or an `inherit` parent key) or `unique: true` never pools, on every admission site.
- G3. Newly admitted plans match forced legacy values, field order and Arrow types for every table. Unproven shapes keep the legacy decision. A bounded run requires a defensible width for every column before either route can start.
- G4. No new error or log text carries a generated or source value.

Non-goals:

- No `statistical` or `inherit` streaming (S3). No route codes or run-card fact (S4).
- No pooling of `uuid4`, `random_int`, `random_element`, `text` or `paragraph`: those belong to GEN-NONFAKER-DRAWS S3a (computed draws) or stay per-row.
- No change to the mask side or to custom Faker providers (they stay per-row and legacy).
- No native-shadow pooling of the new types.

## 3. Behavior and failure modes

| Case | Behavior |
|---|---|
| Table with 0 rows | `pool_eligible` is False; no pool, no selector. |
| Table with 1 row | Pool of 1 in build order. |
| Group B column with non-empty `faker_kwargs` | Per-row. |
| Pinned Faker | Compile and execution recheck both refuse with `pinned_faker_unsupported` before generation. |
| Group B column, 9 rows, en_US | Pool of 9 in build order; the ledger reserves `faker_pool_resident_bytes(9, payload)`. |
| Group B column, 2M rows | Pool of 10,000; selector; bytes equal on legacy, streamed and window. |
| Group B column in an uncertified locale | Per-row, as today. |
| Column that is a `reference` target or inherit parent key | Per-row on every site (G2). |
| `unique: true` | Per-row, as today. |
| Window crossing the table end | In-table values then direct absolute per-row draws. A huge out-of-table offset costs only the requested rows. |
| Multi-locale Faker | Resolve the pool provider, seed the instance, then draw. Keep the #813 replay fix's call-time factory lookup and absolute per-row seeds. |
| In-table selector seek | Bounded by one span on Class A. Poll deadline between discard blocks. Historical huge pooled tables retain Class B for in-table reads. |
| Pool build declined (custom override, locale unavailable) | `open_pooled_selector` returns `None` and the column runs per-row, as today. |
| Bounded Faker pool, including a legacy decline | S1b prices the actual pool size before fit and reservation. A shortfall refuses before generator or pool builder entry. |
| Provider raises in a streamed batch or while the stream is built | `GENERATION_PROVIDER_FAILED`, no cause, no context, no value. |
| Provider without a stock cap, including callback and Mimesis | Bounded refusal before either route. Unbounded legacy with the original binding. |
| Inconclusive lookup inference or unproven sibling schema in any table | Whole plan stays legacy. Speculative conversion errors do not escape. |
| Unsupported declared cast in a newly promoted plan | Decline to legacy; keep its cast result or existing failure. |
| Unsupported provider locale | Public default-locale validation raises `PlanCompileError(generate_provider_locale_unsupported)`. A capability change after validation fails inside dispatch with `GENERATION_PROVIDER_FAILED`. Both precede value draws. |
| Lookup list missing | Declined at admission; the legacy path keeps today's error. |
| Capacity with missing admission inputs | Return UNKNOWN for an unresolved S2 route. Use the prepared route's floor when available. Definite legacy declines keep their floor. |
| Budget too small for a provider pool | `GENERATION_BUDGET_EXCEEDED` before first build or write, on admitted and legacy routes. |
| Custom Faker provider | Per-row legacy, as today. |
| Stock pooled address | Same single-line normalization as the per-row provider. |

## 4. Acceptance tests

Use a bounded sink and assert `streamed` for positive stream cells. The independent oracle calls `_generate_tables_from_config` directly with the same prepared config, pinned inputs, locale, job seed and derive-key resolver. Spy on that call for public legacy declines and check the `legacy:` reason. `generate_tables` or a `resident` label alone cannot witness legacy. Compare complete tables in row order including every field type, subject to the two S1b schema controls in G1. Controls preserve anchor behavior; new assertions and bypass mutations provide the reds.

S1b:

- AT-S1b-1 [A1]. `pool_eligible` admits the legacy 10 in `pt_BR`; it admits each certified Group A and B pair and refuses an uncertified pair; no clock-dependent type is admitted in any locale (checked against `_CLOCK_FAKER_EXACT`).
- AT-S1b-2 [A12]. Run the reference-only plan with `orders.user_email` targeting Faker `users.email` and ordinary sibling `users.alt_email`, at 9 and 20,000 parent rows. Witness forced legacy, bounded-sink streaming and a parent-table window supplied the entire plan. On each, only the sibling opens a pool, and the key equals independent absolute per-row draws at matching positions. For the stream leg choose a ceiling that fits the real peak including the sibling and KeyPool but fails the stream fit if a second Faker pool is charged. Assert the route and the preflight pool charge. Check that a valid sequence inherit parent is in the key set. As separate controls, compile a Faker-only pinned config and execute a well-formed hand-built pinned Faker plan with matching runtime identity. Both raise `pinned_faker_unsupported`, with zero generator entries.
- AT-S1b-3 [A15]. Tables of 0 and 1 rows generate on forced legacy and admitted full-run routes with no pool error. A 9-row table with a Group B column reserves exactly `faker_pool_resident_bytes(9, payload)` and its values equal the first 9 provider calls of a fresh seeded instance. Assert `pool_eligible` directly returns False for an otherwise eligible zero-row column. Freeze empty and fully masked ordinary Faker schemas separately on an uncast, unreferenced first_name column: forced legacy infers Arrow `null`, the admitted stream declares `string`. Compare values and validity across routes and types within each route.
- AT-S1b-4 [A4]. `faker_payload_bound` returns a fixed cap for all 16 new types; preflight runs with a provider snapshot that raises on any call.
- AT-S1b-5. Window parity. A 9,000-row `email` table read at `offset=0, count=100` builds 100 values, counted by a spy. For `email` at 9 rows: `(0, 1)`, `(0, 9)` and `(7, 2)` equal the full run's slice. For `email` at 120,000 rows: `(0, 1)`, `(7, 13)`, `(4096, 5000)` and `(119_990, 10)` equal the full streamed run's slice, and a spy sees `open_faker_pool_draw` called (fails before: `email` is per-row Class A on S1a and the opener does not exist). For `first_name` at 120,000 rows the same reads are served (fails before: Class B refusal).
- AT-S1b-6. On 9 rows compare `(7,5)` to the full-run last two rows plus three independent frozen per-row values. Check split pages, and offsets 10_002, 25_000 and `2**62` with count one against that positional oracle. Assert zero pool builds and zero selector calls for wholly external reads. On 120,000 rows, compare an in-table page beyond 10,000 against an independent frozen pool gathered at indices from `default_rng(selection_seed_int).integers(...)`, not another stream. This catches an indefinite build-order draw.
- AT-S1b-7. `PooledSelector.skip(n)` then `take(k)` equals `take(n + k)[n:]` for `n` in `{0, 1, 1_048_575, 1_048_577, 3_000_001}`, plus a Hypothesis property on `n` up to 4M.
- AT-S1b-16. Request one row at `2**62` inside a newly eligible huge `email` table. Use a counting cursor that fails immediately on a second span or an oversized discard, so the mutant cannot hang the test. Compare to an independently initialized span RNG and assert fewer than one span of discarded indices. Cross a span boundary on all full-run draw implementations using a lowered test span. For a historical huge selector assert the unchanged whole-run RNG and the documented window class. On a multi-block in-table seek expire a fake clock after the first discard; expect the existing timeout and no second discard. Repeat wholly outside a nine-row table with count one; expect no discard, and an already expired deadline to do no work.
- AT-S1b-7b. On one `WindowPoolDraw`, a draw at offset 4,096 then at offset 7 raises `RuntimeError` with the fixed message. Draws at 7 then 4,096 on a fresh cursor equal the full run's slices.
- AT-S1b-8. `pool/_eligible.py` equals the output of `write_eligible.py` on the committed `certified_pairs.json` (drift guard). Run the worker via the driver in two fresh processes. Spy separately at the worker call boundary for delegation to the production opener. Preserve the 10,000-value pool and historical 2,000-pick digest with declared rows 60,000. For declared rows 2,000 compare its prefix to independent sequential provider calls. For a new Group B pair declare more than one real span and compare a slice crossing the span boundary with independent first-span and jumped-RNG picks. Bind pool and output digests to one observed build per probe, including resolution flags on decline.
- AT-S1b-9 [A10, perf, Dell vm-run]. Measure and record cold one-row window latency near the end of a seek span. Assert the discard bound separately from elapsed time. `bench_worker_gen.py` and `bench_compare_gen.py` run with no `N_THRESHOLD` reference and agree on one record format. The worker accepts the Group A and B types, times `generate_tables_streamed` into a bounded Parquet sink, and records two witnesses separately: a build-order run (no sampler hit expected) and a selector run (sampler hit required). 10M rows of `email` stream in under 3 s; 10M `first_name` in under 1.0 s. Recorded in the PR.
- AT-S1b-10. The signature sentry of section 8.1 fails when a receiving function gives `key_columns` a default.
- AT-S1b-11. The AST guard of section 8.1 passes on the tree and fails on a seeded scratch file that calls `pool_eligible(..., opted_out=False)`.
- AT-S1b-12. For one `email` column at 9 and 120,000 rows, legacy `try_pool`, streamed `_faker_stream` and `WindowPoolDraw` give equal bytes, and each calls `open_faker_pool_draw`. A Group B column with `faker_kwargs={"domain": "x.test"}` runs per-row on legacy and streamed (spy: no opener call); the window refuses it with `CODE_UNBOUNDED` before any draw, as today (control). `pool_opted_out` called without `table` raises `TypeError`.
- AT-S1b-13. The secret-material census test lists the window and segmented cursor seed holders, and `repr(WindowPoolDraw(...))` shows no seed bytes.
- AT-S1b-14. Freeze the full #813 replay-fixed A2 vector. Use only table `users`, 60,000 rows, with column dict `{name: name, type: faker, faker_type: first_name, locale: [en_US, ja_JP]}`, absent job seed, no derive-key resolver or other options. SHA-256 over all row-ordered UTF-8 values, each prefixed by its four-byte big-endian byte length, is `406726bbd1aa6bcdb50e748b869b6dc67f896d460a896684d758a9d926bed574` on `dca2db39a` with Faker 40.23.0. Require this digest on forced legacy and streamed runs and matching parent-window slices. Repeat in fresh processes with ambient Faker seeds 3 and 83. Separately test a nine-row build-order column and a 60,000-row reference target under those ambient states. Compare the key to an independent oracle that reseeds for each absolute ordinal before looking up the method. Assert the three reachable routes, pool mode and key opt-out.
- AT-S1b-17. For certified en_US `address`, independently build the reference prefix from the seeded provider with the legacy newline replacement. Witness raw multiline input. At 9 rows compare build order; at 120,000 compare independent selection-seed picks, including window slices. Assert no embedded newline and certification digest over the normalized values.
- AT-S1b-15 [A14,A15]. At the ledger unit boundary an exact reservation passes and one byte less refuses. Separately compute full plan streaming and resident needs including locale charge, buffers, sink, keys, layout and actual `P`. Exercise adjacent integer ceilings on either side of strict `need * (1 + 0.30) < remaining`; assert route or fallback using both peaks. Select a fixture where neither fits for the refusal leg. Spy on build, writes and live reservation amount. Keep the existing over-cap value-free failure control.
- AT-S1b-18. Use a one-row en_US `email` table with an earlier categorical parent and bounded conditional-categorical sibling. Witness the semantic decline. After the locale reservation, choose a ceiling that fits the old whole-table plus unique estimate but fails with `faker_pool_resident_bytes(1, email_cap)` and the strict fit margin. Expect `GENERATION_BUDGET_EXCEEDED`, zero entries to `_generate_tables_from_config` and `build_pool_values`, and zero sink writes. At the first passing ceiling assert the whole-table reservation includes that exact charge, legacy runs once, builds once at size one and returns oracle values.
- Controls [A2, A3]: S1a take parity and batch invariance pass at batches `{7, 4096}` for every new type.

S2:

- AT-S2-1 [A5]. Use each admitted stock pool, keyed and batch example from 8.6, and weighted and unweighted pinned lookups. At batches `{1,7,4096}` compare forced legacy with a witnessed streamed run, for bounded and unbounded budgets. Independently freeze nonnumeric provider pool values. An unpriced Mimesis pool keeps legacy with no ceiling and refuses before build under a ceiling; it is a negative control.
- AT-S2-2 [A6]. A nonempty plain unmasked sequence, certified provider and homogeneous lookup stream. Also run a four-row all-null sequence with the same ordinary provider in that table. Test an integer lookup parent with both an empty reference child and an all-null reference child. Add an unrelated table with an inferred nullable field. For each decline assert legacy dispatch, every field's type (including Arrow `null`), order and values against the anchor oracle at all three batch sizes.
- AT-S2-3. With `null_probability: 0.3`, provider and lookup streams equal a frozen legacy digest committed with the test (computed on the S1a head, independent of the streamed code), and each run asserts route `streamed`. The lookup cell uses a file-backed lookup, so the content digests enter the null seed. Choose a lookup seed with a surviving position in the probe prefix. Freeze after normalizing table chunks; retain validity and field types.
- AT-S2-4. Fault-inject below stock binding selection. Record selection of the streamed route and the streamed pool constructor or draw ordinals. Throw a sentinel in batch 3 at batch size 7 (absolute ordinal 14); require two successful batches then the intended failing draw. Separately throw during streamed pool construction before any batch. Both yield the existing `GENERATION_PROVIDER_FAILED` text for the structural table/column only, no sentinel or seed in errors/logs, `__cause__` and `__context__` both None.
- AT-S2-5 (control). `generate_batch` output is byte-identical before and after the `open_batch_cursor` refactor for Faker at count 1 and 4096.
- AT-S2-5b (control). For n=1 and 20,000, sample a pool of distinct nonnumeric strings. Compare the actual pandas Series, including type, index, dtype and values, to a frozen #813 oracle. Concatenated gathered cursor batches match that oracle. Include odd boundaries, object-only and Arrow-backed pools.
- AT-S2-6. Cover an adapter without a cursor, a same-class fresh adapter, an overriding subclass and a callback registered on the otherwise stock capped Faker name. Verify actual replacement bytes (including the registered callback) on unbounded forced legacy and public legacy. Under a finite ceiling expect `GENERATION_COLUMN_UNBOUNDED`, with no adapter or pool draw. Stock negative controls also cover unsupported caps/arguments. No diagnostic includes a callback result. Replacement dispatch and bounded refusal are passing #813 controls. M-15 and M-20 must break them after promotion.
- AT-S2-6b. On the combined head test all three S3a aliases against S3a's whole-table oracle. Assert computed dispatch, UTF-8 widths and table-wide row/byte layout caps, including unbounded ledger and caller partitions with zero and oversized pieces. Lower the limits to force splits; preserve row order, zeros and supplied-layout charge; price by largest effective piece. Replacements follow AT-S2-6. Assert Class B with reason `family_class_b:provider` for alias windows, and refusal through generate_rows. For the public locale fixture compile locale-less stock synthetic_npi and run with unsupported default fr_FR. Assert the exact `PlanCompileError` code `generate_provider_locale_unsupported` and zero value draws. In the existing default-locale tests at tests/unit/plan/test_generate_providers.py:209 replace the ledger-construction trap with a value-draw spy. Allow the public capability check's draw_path call. Separately validate a supported run and replace its live capability row at the dispatch seam to exclude that locale. Exercise legacy and stream dispatch. Require the fixed `GENERATION_PROVIDER_FAILED` with no cause, context or values, and zero dispatch-local draw_path calls, computed opens, pool builds or adapter value draws.
- AT-S2-7. Use a small earlier sequence table and a later stock pooled provider table. With sufficient total budget witness streaming, one reserve before build and release at stage exit. Choose a lower ceiling where the plan fits without the pool term but neither route fits with it. Assert `GENERATION_BUDGET_EXCEEDED`, no builder entry and zero sink writes including the earlier table. On a separate one-row table add a bounded conditional categorical sibling with its earlier parent; prove legacy decline. Choose a ceiling between output/unique/locale-only needs and the full legacy build requirement (including margin). Assert no generator or `PoolBuilder.build` entry. At the passing ceiling require legacy entry, one 10,000-value build and equal values. Include the measured build-peak control in 8.6.
- AT-S2-8. The census test lists the provider stream seed holders, and their `repr` shows no seed bytes.
- AT-S2-9. Through compiled public plans compare typed Parquet int64, float64, bool and string lookups at batches `{1,7,4096}`. Assert legacy on zero rows, all-null or mixed/None input including a three-row seeded all-null mask. Use a decoded-list unit fixture for heterogeneity Parquet cannot encode. Assert an actual schema decline for `[1, 2.5]`. A declared `int` over numeric text streams with the declared type. For weighted uint64 Parquet `[1, 2**63]`, weights `[1,0]`, assert the public run succeeds on legacy, only 1 is drawn, and Arrow type is int64. No exception text or source value is logged. Exercise a nondefault seed, real derive-key resolver and pinned digest through admission and drawing; replace the source file after compile to prove no reopen. Spy on the admission context: compare its fingerprint-derived mask positions to the forced legacy context, using a short seeded case whose admission changes with a dummy key. For the decoded (1, None) control use an unbounded ledger to witness legacy. A bounded run without a width must refuse before generator entry.
- AT-S2-10. Spy on the exported weighted helper in each of the four ordinary categorical/lookup callers, and on the common bounded-index cursor in Faker take/select/skip, scalar and bundle REUSE and provider streaming. Normalize aliases in the AST of these call sites; require delegation on the matching branch and forbid local copies of `choices` or bounded `integers`. Preserve separate conditional, unique and keyed contracts. Seed each bypass with a byte-identical local draw: the guard itself must go red. Run import-linter and check registry imports via `generation.pool`.
- AT-S2-11. Use a tiny pinned homogeneous Boolean Parquet list, no mask, and many output rows. With no sink or explicit ceiling, stub the detected host memory consistently for capacity and execution between the admitted Arrow floor (one data bit per row) and eight legacy list-slot bytes per row. Assert prepared admission, successful resident execution and Boolean output. Config-only estimate_job_capacity must give UNKNOWN. With the same prepared admission the generation-floor check passes here and refuses one byte below the Arrow floor. A definite legacy decline still refuses below its floor. Assert capacity does not reopen the lookup.

## 5. Named mutations

Each must turn the named test red on the final head.

- M-1. `pool_opted_out` ignores `key_columns`: AT-S1b-2 red.
- M-2a. Pass an empty key set only in `_pooled_columns`. AT-S1b-2 loses its tight-budget streamed route or charges the key.
- M-2b. `_generate_column` gives `key_columns` a default of `frozenset()`: AT-S1b-10 red.
- M-2c. `window._build_streams` passes an empty key set: AT-S1b-2 (window leg) red.
- M-3. Pool size stays `DEFAULT_POOL_SIZE` for `0 < rows < DEFAULT_POOL_SIZE`: AT-S1b-3 red.
- M-4. `skip` draws `n - 1` indices: AT-S1b-7 and AT-S1b-5 red.
- M-5. `WindowPoolDraw` drops its offset-below-cursor check and continues from the cursor: AT-S1b-7b red.
- M-5b. Continue build order indefinitely inside a selector table, or use it beyond the table instead of the absolute per-row draw: respective independent oracles in AT-S1b-6 fail.
- M-5c. Move build seeding before `resolve_pool_provider`. AT-S1b-14's frozen full-run digest changes. On the replay-fixed dependency this mutation gave 65fe929214c5d871e79f9ad681460e6243ee50d03b7febfa0b4521c50eee0854 in both fresh processes.
- M-6. `_eligible.py` gains a hand-written pair: AT-S1b-8 red.
- M-6b. `pool_eligible` drops the `rows < 1` check: AT-S1b-3 red.
- M-6c. The streamed route computes its own build-order rule instead of `open_faker_pool_draw`: AT-S1b-12 red.
- M-6d. Group A and B pairs ignore `faker_kwargs`: AT-S1b-12 red.
- M-5d. In the per-row draw skip the absolute ordinal reseed after the first row. AT-S1b-14's key differs from the independent positional oracle.
- M-5e. Replay preceding spans, skip a deadline check, or route a huge external offset through the selector: each separately fails AT-S1b-16's work counters or timeout assertion.
- M-6e. Return raw reflected `address` in the pool resolver: AT-S1b-17 red.
- M-6f. Omit only the legacy Faker build term. AT-S1b-18 enters generation at the refusing ceiling.
- M-6g. Restore the worker's always-sample path, pass prefix length as table size, or continue span zero in a new pair's second span. AT-S1b-8's delegation and independent vectors catch these separately.
- M-7. `PooledProviderStream` opens a fresh reuse cursor per batch: AT-S2-1 red at batch 7.
- M-8. `BatchProviderStream` calls `generate_batch` per batch: AT-S2-1 red at batch 7.
- M-9. `LookupStream` builds `random.Random` per batch: AT-S2-1 red.
- M-10. The provider error boundary uses `raise ... from exc`: AT-S2-4 red.
- M-11. Preflight leaves provider pools out: AT-S2-7 red.
- M-12. `LookupStream` is null-masked with a context built without the lookup digests: AT-S2-3 red.
- M-13. `lookup_stream_schema` skips the mixed-type check: AT-S2-9 `[1, 2.5]` cell red.
- M-14. `lookup_stream_schema` skips the all-null replay: AT-S2-9 3-row cell red.
- M-15. Replace the binding check that grants both batch admission and its stock cap with an `open_batch_cursor` attribute check: AT-S2-6 same-class and subclass cells red.
- M-16. Stream construction runs outside the error boundary: AT-S2-4 construction cell red.
- M-17. Return raw REUSE indices or a bare array from `sample`: AT-S2-5b red.
- M-18. Limit schema parity checks to the new column: AT-S2-2 sibling and child cells red.
- M-19. Omit the pool term only in `_run_legacy`: AT-S2-7 legacy cell red.
- M-20. Accept a registered callback's stock cap or reject the certified native binding: AT-S2-6 or AT-S2-1 red.
- M-21. Move locale validation after computed or adapter dispatch: AT-S2-6b call counts red. Omit provider aliases from supplied-partition subdivision: AT-S2-6b layout red. Map the public unsupported default to the generic draw error: AT-S2-6b's public error code fails.
- M-22. Propagate singleton `OverflowError`, or build admission's lookup context without the pinned digest/actual job key: AT-S2-9 public fixtures red (also AT-S2-3 for mask parity).
- M-23. Inline a byte-identical categorical draw or bounded-index draw in any named caller: AT-S2-10 red even when parity passes.
- M-24. Treat missing pinned inputs as definite legacy in the capacity floor. AT-S2-11 returns INSUFFICIENT instead of UNKNOWN. Reclassify from config despite prepared admission: the below-Arrow-floor control loses its definite refusal.

## 6. Established solutions

Searches run: NumPy `Generator` documentation on sequential draws, the CPython `random.Random.choices` source (installed stdlib), the Faker `seed_instance` documentation, and the engine's own pool and harness code.

- Seeded pool plus a seeded index stream is the existing pattern (`PooledSelector`, `generation/_faker_pool.py:449`). NumPy `Generator.integers` is position-based: checked locally, `integers(size=7)` then `integers(size=993)` equals `integers(size=1000)` from the same seed. S1b's window skip follows the same rule.
- `random.Random.choices` draws one `random()` per element, with weights (`bisect(cum_weights, random() * total)`) or without (`floor(random() * n)`), so it is prefix-stable across `k`. `CategoricalStream` already relies on it.
- A seeded Faker instance is a sequential generator: checked locally, the first 9 `email` values of a build of 20 equal a build of 9 from the same seed. The determinism harness (`scripts/faker-determinism/`) certifies this per type and locale.
- Bounded integers can consume a variable number of raw words. Advancing PCG64 by the row offset alone cannot reproduce a historical selector.

## 7. Reuse inventory

| Need | Reuse | Where |
|---|---|---|
| Pool build | `build_pool_values` | `generation/_faker_pool.py:333` |
| Persistent selection | `PooledSelector.take` / `select` | `generation/_faker_pool.py:476` |
| Pool selector factory | `open_pooled_selector` | `generation/_faker_pool.py:491` |
| Resident pool sizing | `faker_pool_resident_bytes` | `generation/pool/_resident.py` (S1a) |
| Value caps | `FAKER_VALUE_CAPS`, `faker_payload_bound` | `generation/_bounds.py:55`, `:125` |
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

## 8. Design

### 8.1 Choke point: one key-column set

New `generation/pool/_keys.py` (about 60 lines) has two functions:

- `pool_key_columns(configs) -> frozenset[tuple[str, str]]`: every `(reference_table, reference_column)` of a `type: reference` column, and every inherit parent key, read as `(edge.source_table, edge.source_key)` from each edge that `iter_generate_input_refs` yields (`config/_generate_relational/__init__.py:543`). An edge with an empty `source_key` is skipped. `source_key` is set for every input read through a foreign key, not only inherit (`config/_generate_relational/__init__.py:499-502`), so the set is slightly wider than reference and inherit targets; every member is a key another table reads, so a per-row draw for it is the safe side. Composite targets add each member column. An inherit parent key must be a non-null `sequence` (`config/_generate_relational/__init__.py:207`), so today it is never a Faker column; it is in the set so that the rule stays true if that validation widens.
- `referenced_key_columns(configs)`: the reference targets only. `_streamed._referenced_keys` (`generation/_streamed.py:180-187`) is replaced by this one, because the same set drives KeyPool collection in `_preflight` (`:230`) and `_consume_table` (`:420`), and S1b does not change what KeyPool collects. S3 decides whether inherit keys join KeyPool.

`pool_opted_out(col, *, table, key_columns)` (`generation/_faker_pool.py:244`) gains one rule: `(table, col["name"])` is in `key_columns`. `table` is an explicit argument because the raw column dicts in `_streamed._pooled_columns` carry no `TABLE_KEY` (the window's dicts do, through `with_table` at `generation/window.py:192`); one explicit argument keeps every route the same. Both arguments are keyword-only with no default. Export the shared helpers via the owning package.

Compute the set once at each route root. Every function that receives it takes a required keyword with no default. A public entry that computes its own set keeps its signature.

- Legacy resident: `synthesize._generate_tables_from_config` (`generation/synthesize.py:104`, entered from `generate_tables` at `generation/_plan_entry.py:215`) computes the set once, then `synthesize._generate_column` (call at `:186`), `synthesize._faker` (`:455`), `_faker_pool.try_pool` (`:292`).
- Pinned compile rejects Faker at `generation/_pinned_compile.py:67`. Execution repeats the check at `_pinned_execute.py:127` before _run, including deserialized plans. Supply the new required keyword to _generate_column for supported kinds after validation. Pass an empty immutable set only at that checked pinned call site. AT-S1b-2 keeps both refusal guards in place.
- Streamed: `_streamed._pooled_columns` (`generation/_streamed.py:197`) and `make_column_stream` (`generation/_column_streams.py:300`) to `_column_streams._faker_stream` (`:360`, `pool_eligible` call at `:375`), reading the new `PlanAdmission.key_columns` that `classify_plan` fills.
- Window: admission and `window._build_streams` use the same column decision, declared rows and required key set. Compute keys once from all configs, including children outside the requested table. Replace both old threshold checks (`_window_admission.py:383,437`) with the common decision. Keep the historical large-selector exception in section 8.4.

Guards:

- AT-S1b-2 exercises three reachable Faker routes, both pinned refusals and the streamed preflight charge.
- AT-S1b-10 is a signature sentry: for each function that receives the set from a caller, `inspect.signature` shows `key_columns` (and `table` on `pool_opted_out`) as keyword-only with no default. A seeded default makes it red, so M-2b is caught.
- AT-S1b-11 walks the AST of `src/decoy_engine/generation/` and fails on any call to `pool_eligible` whose `opted_out` argument is not a `pool_opted_out(..., table=..., key_columns=...)` call.

`_streamed.py` is at 592 lines against the 600 goal. Its edit replaces `_referenced_keys` with an import, making room for S1b legacy peak accounting.

### 8.2 The eligible set and the pool size

- `N_THRESHOLD` is deleted. One function, `pool_size_for(rows) -> int` in `_faker_pool.py`, returns `P = min(rows, DEFAULT_POOL_SIZE)` with `DEFAULT_POOL_SIZE = 10_000`.
- `pool_eligible` returns False for `rows < 1`, so a 0-row table never reaches `check_pool_size` (`determinism/_derive.py:348-358`) or `integers(0, 0)`. A 1-row table pools a pool of 1 in build order.
- When `rows <= DEFAULT_POOL_SIZE`, the column is the pool in build order: value `i` is the `i`-th provider call after the seed. No selector runs. OWNER CALL (master plan Q1): build order for small tables. Default: build order, as recommended there.
- When `rows > DEFAULT_POOL_SIZE`, use the selection seed and a pool of `P` values. Section 8.4 defines bounded seeks and protects historical full-run bytes.
- One shared draw decides between the two modes: `open_faker_pool_draw(col, rows, ...)` in `_faker_pool.py` returns either a build-order draw or a `PooledSelector`. Legacy reaches it through `try_pool`. Streamed and window draws use the same opener. AT-S1b-12 checks that the three routes agree.
- Keep #813 pool order: resolve the provider on the fresh instance, check the two flags, seed with the build seed, then call the provider. On the replay-fixed dependency multi-locale reflection discards the probe method and resolves again at draw time. Moving the seed ahead of that probe consumes a seeded choice. Keep open_column_faker, its pre-seed behavior and the absolute row reseed immediately before each effective lookup unchanged.
- Group A and B require empty `faker_kwargs`. Pass the actual kwargs into the common eligibility decision on every route. Keep prior certification rules for pre-existing pairs. Share the existing `address` newline replacement in `internal/faker_setup.py:511` with the pool resolver at `:609`. Preserve the per-row wrapper's call-time lookup on `fake`, kwargs, coercion and custom-provider precedence. Certify and price the normalized output, including separator bytes.
- S1b prices each eligible Faker column once with `faker_pool_resident_bytes(pool_size_for(rows), payload)`, including the fixed 80 KiB. Use the same decision and charge for admitted preflight, live stage reservation and bounded _run_legacy. Sum simultaneous admitted pools. Add the maximum sequential legacy Faker build to resident tables and uniqueness storage before _fits and the whole-table reservation. Keep the run-scope locale charge separate. Legacy uses the aggregate reservation, with no second charge in try_pool.
- Generate `generation/pool/_eligible.py` from the committed certification results. Export its registry through `generation.pool` for `_bounds.py`, `_faker_pool.py` and other cross-package readers. Preserve certification tier in that registry so the window can identify historically pooled types without a second list.
- Group A and B types are admitted only through certified `(type, locale)` pairs. A pair the harness has not certified stays per-row in that locale.
- `FAKER_VALUE_CAPS` gains `free_email: 320` and `domain_name: 256`. The other 14 new types already have caps or take the `_NAME_LIKE` default; AT-S1b-4 pins all 16.
- `_window_admission` reads the locale through `faker_setup.requested_locale` (`:649`) instead of `col.get("locale") or instance_default_locale`, so there is one locale reader.

### 8.3 Harness tier 3

`scripts/faker-determinism/check_determinism.py` (597 lines) first moves its tier tables into a new `scripts/faker-determinism/_tiers.py` (about 80 lines), then `_tiers.py` gains `TIER_3`: the 16 Group A and B types in en_US, en_GB, fr_FR, de_DE and es_ES. The builder runs the harness in the locked environment (`uv.lock`, Faker 40.23.0), commits the new digests to `certified_pairs.json` and `golden_digests.json`, then runs `write_eligible.py`. A pair whose pool digest is not stable across two processes is left out and stays per-row; the builder lists any left-out pair in the PR. `date_of_birth` is certified with the `_dob_anchor.py` anchor in place, because `_reproducibility.py` excludes it from `_CLOCK_FAKER_EXACT` only under that anchor.

The worker at pool_determinism_worker.py:137 currently selects through _build_and_sample_returning_pool (_faker_pool.py:440). Route it and legacy generation through the same production opener as the stream and window. Supply declared rows to the opener, and offset/count to its draw. Preserve the opener’s draw-or-decline contract for its generation callers. Inside the opener expose the one build result (ordered values and resolution flags) to the certification probe so even a decline can be distinguished from an unavailable name. The probe never constructs a second pool. Retire the independent sample branch and migrate existing seam spies. Keep initial selector goldens and add separate build-order and later-span probe records with declared rows, offset and count. Permit probes of candidate pairs before registry generation, using their candidate tier for the production span rule. Register only pairs that pass all applicable vectors across processes.

### 8.4 Window draws and bounded seeks

Today a pooled column is Class B (`generation/_window_admission.py:440`, reason `pooled_faker`), and `generate_rows` (`generation/window.py:263`) refuses a Class B table. Before S1b this only touched tables of 50,000 rows or more. Dropping the threshold would make every small table with a Group A or B column Class B, and `generate_rows` would refuse tables it serves today. S1b admits pooled windows with the seek contract below.

`WindowPoolDraw` lives in `generation/stream/_window_pool.py`. Create one per eligible column per window. Share the mode decision and segmented draw with full generation; only interval splitting and deadline plumbing belong to the window.

- Split each request at the declared `row_count`. For the in-table part at `rows <= 10_000`, build only the prefix through the requested end. Reuse it across chunks. For every position at or beyond `row_count`, use `PerRowFakerStream` at the absolute ordinal. A wholly out-of-table request does no pool build or selector seek, even at `2**62`.
- Use a seek span of 16,777,216 rows. Within the first span use the historical selection stream. For newly certified Group A/B pairs only, start each later span at `PCG64(seed_bytes_to_int(selection_seed)).jumped(span_number)` and use the same bounded-index cursor within it. Legacy, streamed and window draws split identically at span boundaries. No earlier span is visited. Include the span size and segment seed convention in the frozen S1b vectors. Provider REUSE never segments. Measure the worst one-row seek in AT-S1b-9.
- Historical types and pairs keep the original uninterrupted selector on full runs. For these formerly Class B columns only, tables larger than the seek span keep the existing `pooled_faker` Class B verdict for in-table reads. Out-of-table-only reads take the direct continuation. Pass the actual interval to window admission and construction; classification without an interval is conservative. Keys and other opt-outs stay per-row at every size. This bounds cold in-table replay to less than one span on every admitted window without changing an old selector byte. No checkpoint cache.
- Check widths for Class A pooled columns with `_check_faker`. `WindowPoolDraw` owns its forward cursor per call. A rewind raises the fixed `RuntimeError`. Split internally at a span end and at `row_count` even inside one chunk.
- `window._build_streams` (`generation/window.py:195-202`) uses `WindowPoolDraw` for a Class A, pool-eligible in-table range and `PerRowFakerStream` otherwise. The decision is the same `pool_eligible(..., rows, opted_out=pool_opted_out(col, table=..., key_columns=...))` call as the full run, with `rows` the declared `row_count`. The window computes `key_columns` once per `generate_rows` call from the complete config.
- Open draws lazily. Pass the existing monotonic deadline check into build and skip. Check before a build, between bounded groups of provider calls, before and after each discard block of at most 1,048,576 indices, and after the last chunk. Keep the existing timeout code and omit values from the message. No per-row clock call is needed.

Keep the accepted offset range and the existing timeout. Update the public window docstring and the S1b breaking entry: page splits within one plan agree, but a position inside one table and outside a shorter table can differ. Pass the existing direct positional draw into the window wrapper to avoid importing a private generation module from `stream/`.
- Implement `skip` using the shared bounded-index cursor introduced in S1b. Migrate Faker and scalar/bundle REUSE index generation in the same refactor. Keep the gather and return contracts, with anchor controls before the move. Discard blocks must preserve its buffered state at odd offsets.

### 8.5 Native shadow and draw sites

- `execution/physical/_shadow_generation.py:100` sets `SHADOW_ADMISSIBLE_FAKER_TYPES = POOL_ELIGIBLE_FAKER_TYPES`. It stays the legacy 10, so a column of a new type keeps the shadow decline it has today.
- The `gen.faker_pool_build` notes in `execution/native/_draw_sites_gen_pool.py` cite `n >= N_THRESHOLD`; they change to "pool size `min(rows, 10_000)`; build order at or below 10,000 rows". The selection site note changes from `partitionable=False` to say it is partitionable through `skip`; the flag value itself is a native contract and is not changed in S1b.
- `scripts/bench-generation-pool/bench_worker_gen.py:203` assigns `_faker_pool.N_THRESHOLD`, and its README cites it. After the deletion the assignment would do nothing. S1b removes the override argument from the script and the README line.

### 8.6 S2: provider streams

Provider draw logic stays in the package that owns it. New `generation/kinds/_provider_stream.py` (about 170 lines), exported from `generation.kinds` next to `draw_path` (`generation/kinds/__init__.py:47`). `make_column_stream` (`generation/_column_streams.py:330-358`) dispatches `provider` to the public `open_provider_stream(col, ctx, registry, ...)`; nothing outside `kinds/` imports a `kinds/_` module.

Keep public validation in plan/checks/_generate_providers.py:44-56, including the capability path check before the locale refusal. Inside the shared provider error boundary, resolve the effective locale and live capabilities once. Check membership in `supported_locales` before any computed opener, draw-path selection, pool construction, keyed draw or adapter call. Run the same metadata-only locale gate in admission before width refusal. An unsupported live locale must retain the provider failure even under a ceiling. Both resident and stream dispatch use this gate. Then dispatch in this order:

1. If GNF S3a has merged: its public `open_computed_stream(col, ctx, registry)` runs after the locale gate, with S3a's live-registry, stock-binding and effective-locale checks. If it returns a stream, that is the column's stream. S3a never adds a `"computed"` value to `draw_path`, so S2 has no `"computed"` branch; S2 calls S3a's opener, never re-derives its rule. If S3a has not merged, this step does not exist and the second to merge adds it (section 12, order).
2. Otherwise `draw_path(caps)` (`generation/kinds/_provider.py:45`) is read once:

- `pool`: build once through the same `PoolBuilder.build` arguments as `_provider.py:127`. Keep `DEFAULT_POOL_SIZE` even for one output row. `generation.pool` exports the persistent bounded-index cursor shared with `PooledSelector._indices` (`_faker_pool.py:473`). Seed it exactly as `_sampler.py:279` does. Its `take(k)` returns only indices. `PoolSampler.open_reuse_cursor(pool, seed)` returns a value cursor. It gathers `pool_pick(pool, indices)` on each call. `PoolSampler.sample` returns `pd.Series(gathered_values)` with today's dtype and index. The stream consumes the same gathered values before `_as_text`. Reuse the index operation for bundle REUSE (`_sampler.py:534`), keeping tuple-wise gather and UNIQUE/keyed algorithms intact.
- `"keyed"`: `KeyedProviderStream` calls `adapter.generate(provider, spec=ProviderSpec(locale, deterministic=True, namespace=namespace, seed=value_seed), source_value=offset + i)` per row, the exact legacy call (`generation/kinds/_provider.py:146-151`). Stateless.
- `batch`: extract the seeded instance and per-call loop from `FakerAdapter.generate_batch` into its `open_batch_cursor`. `generate_batch` consumes that same cursor once. Preserve deterministic-mode rejection, count, seed=None and callback behavior for existing callers. Only the stock binding in the admitted width table may stream. A replacement or callback cannot inherit its cap.

Error boundary. Stream construction (pool build, cursor open, seed conversion), each draw and each `_as_text` conversion all run inside one boundary, the one `provider_generate` uses (`generation/kinds/_provider.py:79`): any failure raises `GenerationError(GENERATION_PROVIDER_FAILED)` with a fixed message. The raise is made after the `except` block closes (the existing pattern), so `__cause__` and `__context__` are both `None`, and no seed bytes or provider text reach `str(exc)`.

Generated provider values use `pa.string()` on both routes, including an empty or all-null column. Legacy explicitly constructs text arrays in `_statistical_column.py:120-139`.

Semantic parity is independent of the ledger. Bounded pricing uses the same binding and pinned list as classification; `_reject_unbounded` (`_streamed.py:374`) precedes legacy dispatch.

- One binding decision, exported by the owning package, supplies the path and defensible UTF-8 width. Require the effective adapter to be the default adapter object for that name, matching stock capabilities, supported locale, backend and effective method/default arguments. Exclude V2 registered callbacks before granting any cap. Use `providers_v2.custom_provider_names()` for V2 callbacks. Share `providers_v2.is_stock_binding` with S3a and its out-of-core caller (`execution/out_of_core/_faker_pool.py:46,198`). An immutable registry override can reuse an adapter with different capabilities, so also compare the effective capability row. Use the same run binding for pricing and construction. With S3a, consult its `computed_spec_for` first after the locale gate and take `computed_value_width(spec)` for each admitted alias.
- S2's entire ordinary stock admission set is the following three bindings at `en_US`: Faker `synthetic_member_id` (`numerify('MBR########')`, 11 ASCII bytes, pool), native `synthetic_npi` (10 ASCII digits, keyed), Faker `lorem_text` (existing `text` cap 1024, batch). The provider package owns the stock path metadata. Reuse the adapter method/default mapping and the existing Faker cap, with no second alias table. Before S3a admit stock `uuid` at 36 via batch. Other bindings, including Mimesis, have no S2 cap. Check this before admitting them even without a ceiling. Keep their unbounded legacy output and bounded `GENERATION_COLUMN_UNBOUNDED` before dispatch. Never borrow a Faker cap for a different backend.

For lookups extract the scalar-width reduction from `_bounds.py:155` for both callers. Apply it to the pinned tuple without coercing or copying data; use the existing `output_payload_bound` post-pass for declared types. Reuse decoded lists; price pinned resident values/weights and the peak cumulative-weights scratch used by `choices` for both routes before drawing. Preserve the public entry's pinned-input decode order.

Pool memory has three callers and one size calculation in `generation.pool`. For fixed-size provider pools account for `PoolBuilder.build`'s adapter result, list copies, object array and distinct-count hash set including table capacity/resize peak (`pool/_builder.py:221` onward). `pool/_value_pool.py`'s per-value floor alone is insufficient. Reuse resident object and fixed-cost arithmetic. Verify the estimate against a cold build with distinct strings. Account separately for provider initialization and batch/sink buffers.

In `_preflight`, compute the maximum table stage across the whole plan, including all simultaneously live pools. Before building, reserve the same charge on the stage ledger and release it on every exit.

S2 extends S1b's legacy peak calculation with fixed-size provider builds at 10,000. Take the maximum over sequential Faker and provider builds. Keep the S1b fit, reservation and pre-entry refusal. After generation apply the existing value-free width tripwire to priced provider and lookup outputs on legacy as well as streamed batches. Budget and timeout exceptions stay outside provider-error translation.

New seed holders (the segmented cursor's selection seed and the window draw, the `KeyedProviderStream` value seed, the `PooledProviderStream` selection seed, the batch-cursor seed) hold the seed in an `OpaqueBox` or a `repr=False` field and get rows in `secret_material_census.json`. The census test covers them (AT-S1b-13, AT-S2-8).

### 8.7 S2: lookup streams

`generation.kinds` exports `weighted_draw(rng, values, weights, k)` from its existing `_categorical.py`. Ordinary resident categorical (`synthesize.py:445`), ordinary streamed categorical (`_column_streams.py:161`), legacy lookup (`kinds/_lookup.py:255`) and `LookupStream` all call it. Keep conditional cumulative weights and unique draws unchanged. A lookup stream holds its pinned `LookupList` and one `random.Random(ctx.base_int('py'))` across batches.

Admission runs before stream construction. Pass `_PreparedPlan.run_kwargs()`'s decoded list map including digests, the normalized config job seed, actual derive-key resolver, effective registry, default locale and provider snapshot from `run_generation` into `classify_plan`. Qualify the column with `with_table`. Use one lookup context builder for admission, legacy draw, streamed draw and null masking, with `lookup_digests(col, lookup)`. Do not reopen files, seed from a dummy job, consume execution RNGs or derive without the pinned digest. Pass those same inputs into `make_column_stream` and the outer null-mask wrapper. Missing run inputs leave an otherwise viable S2 candidate unresolved. Distinguish this state from a definite legacy decline in the admission result. Only prepared execution may promote it. For capacity pass the prepared admission when available into the existing generation floor calculation. With config alone, propagate unresolved through generation/__init__.py and execution/capacity.py as UNKNOWN with a fixed structural message. Preserve the existing definite-route floor and shortfall logic. Keep lifecycle estimates advisory. Never infer legacy impossibility from missing pinned inputs. Keep old plans' classification unchanged.

In `kinds/_lookup.py`, `lookup_stream_schema` returns an inferred Arrow type or a legacy decline. It never draws from the lookup list.

- A declared output type sets the emitted type via `output_types`. Keep the generated type separate; apply the existing cast post-pass. For numeric text to declared `int`, pass text through to the cast. Do not infer from the first batch. S2 admits declared casts only for proven numeric text to `int`: validate each possible non-null lexeme via the existing cast kernel, in bounded chunks. On failure decline and leave legacy to report the original cast error at its original position. Other declared casts in newly promoted plans stay legacy.
- An undeclared lookup with zero rows declines. Legacy infers Arrow `null`.
- A `None` entry or differing singleton Arrow types declines inference. Treat Arrow conversion failures, including Python `OverflowError` on a uint64 singleton, as a speculative decline. Return a fixed internal reason with no exception text or log. The legacy draw remains authoritative, including zero-weight entries that are never selected.
- For an undeclared lookup with a null probability between zero and one, use the existing null-mask rule and a fresh matching RNG to find a surviving row. Share the mask draw with `NullMaskedStream` (seed `ctx.base_int('np')`, masked where the draw is strictly less than the probability). Inspect at most `min(rows, 4096)` ordinals. Decline if inconclusive. Probability one declines immediately. This is a conservative decision, so a huge input cannot spend its run in admission.
- Otherwise: the single inferred type of the list.

`None` declines the column, and the plan stays on the legacy path. AT-S2-9 covers each case and compares schema and values across batch sizes.

### 8.8 S2: admission

`ADMISSION_MATRIX` allows provider and lookup candidates. Apply existing declines first. For plans containing either new kind, check every generated table before switching the whole plan. Admit only width-certified text providers without declared casts, schema-proven lookups, and nonempty plain sequences. Require those sequences to have no mask or declared cast and to resolve to int64 in the existing numeric plan. Any other sibling or relational edge keeps the plan on legacy. All other old kinds, all reference children, uncertain sequences, and changes to legacy sibling typing decline the entire new candidate. This deliberately narrow S2 does not alter previously eligible plans without the new kinds. Keep missing-list errors on legacy. A semantic decline runs legacy if widths and budget permit. Missing widths under a bounded ceiling refuse before legacy. Preserve the public plan-check error. A subsequent live locale mismatch uses the shared dispatch failure before any draw.

### 8.9 Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_keys.py` | `generation/pool/` (16 modules; `generation/` already has 26 direct modules) | new CODEMAP row "pool key columns"; imports config only | `pool/_resident.py` |
| `_eligible.py` | `generation/pool/` | same | `pool/_resident.py` |
| `_window_pool.py` | `generation/stream/` | `generation/_column_streams.py` row (persistent per-column generators); `stream/` is S1a's sub-package for them | `stream/_batches.py` |
| `_provider_stream.py` | `generation/kinds/` | CODEMAP §Where things go, generation row | `kinds/_provider.py`; export via `generation.kinds` |
| bounded-index cursor | existing `generation/pool/_sampler.py`, exported by `generation.pool` | pool sampling | scalar and bundle REUSE |
| `pool/_build_order.py` if needed | `generation/pool/` | generation pool draws | pool selector and size rule |
| new ATs and bypass guards | `tests/unit/generation/` and `tests/sentry/generation/` | generation unit and sentry tests | existing FR0 and computed-draw tests |
| `write_eligible.py`, `_tiers.py` | `scripts/faker-determinism/` | harness scripts | `check_determinism.py` |
| certification worker and capacity test | existing scripts/faker-determinism/pool_determinism_worker.py and tests/unit/execution/test_capacity_estimate_job.py | harness scripts and execution unit tests | existing driver and floor fixtures |
| certification data and contract entries | existing harness JSON, `docs/compatibility-contract.md`, `changelog.d/gen-stream-all-s1b.md` | harness, docs and changelog conventions | existing deterministic vectors and fragments |

`generation/` itself takes no new module. The CODEMAP `_faker_pool.py` and `_column_streams.py` rows gain the new names in the same PR.

### 8.10 Design notes

- One place per fact: key columns (`pool/_keys.py`), certified pairs (`pool/_eligible.py`, generated), pool size and mode (`pool_size_for` and `open_faker_pool_draw` in `_faker_pool.py`). The window, legacy and streamed routes read these, never restate them.
- Open/closed: a new draw path adds one stream class and one `draw_path` branch; no other site changes.
- No flag arguments: build-order and selector modes are two classes chosen by `rows`, not a boolean parameter.

## 9. Frozen contracts and byte changes

- Generate output bytes change for: pool-eligible legacy-10 columns with fewer than 50,000 rows (now pooled); columns of an already certified locale pair (for example `street_name/en_US`, `generation/_faker_pool.py:78`) with fewer than 50,000 rows (now pooled); formerly eligible legacy-10 or certified-pair columns of 50,000 rows or more that are reference targets (now per-row under the key opt-out); and newly pool-eligible ordinary Group A and B columns in certified locales at positive row counts. The compatibility entry and the golden checks name one pair of each kind, `street_name/en_US` included. The CLI `decoy run --rows N` preview (`decoy/src/decoy/cli/gen/_preview.py`) scales `row_count`. When the full table has at most 10,000 rows, preview and full run both use build order, so the preview is a prefix of the full run. When the preview has at most 10,000 rows and the full run has more, the modes differ and prefix parity is not guaranteed; the changelog says so. One `Breaking:` line in `changelog.d/gen-stream-all-s1b.md` and an entry in `docs/compatibility-contract.md` section 1 as a pre-GA correction. Types and value formats stay stable, including single-line addresses.
- `generate_rows` keeps direct per-row access past `row_count`. S1b widens Class A up to the historical seek limit and throughout newly certified tables. Name the span convention, the preserved ordinary multi-locale selector vector, and normalized address certification in the compatibility entry.
- S2 changes no bytes (AT-S2-1 is parity).
- Golden files regenerated by the harness, by name (master plan section 10): `tests/native/test_determinism_goldens.py`, `tests/native/test_pooled_faker_draw_sites.py`, `tests/unit/test_v2_generation.py`, `tests/unit/generation/test_fr0_budget.py`, `tests/unit/test_r3_10_generation_key_contract.py`, `tests/unit/generation/test_fr0_preflight_lifetime.py`, `tests/unit/generation/test_generate_determinism_ratchets.py`, `tests/unit/generation/test_faker_pool_eligible.py`, `tests/unit/generation/unique/test_pool_opted_out.py`, `tests/parity/_f_audit_support.py`, `tests/parity/test_phase_f_f2_mixed_backend_witness.py`, `tests/parity/_f0_matrix.py`, `tests/parity/_f0_fixtures.py`, `tests/parity/test_phase_f_f0_invariants.py`. Run these pinned/relational suites as unchanged controls: `tests/unit/generation/test_pinned_*.py`, `tests/unit/generation/relational/test_routes.py` and `tests/unit/generation/_cf_routes_support.py` (the builder confirms exact paths at the anchor). Any other golden that moves is a stop: the builder reports it and does not regenerate it.
- No change to `GEN_FAMILIES`, the Faker pin, any reason code, or the mask side.

OWNER CALL (window access). Default to the bounded historical Class B exception in 8.4. It preserves previously served reads and frozen historical selector bytes. New Group A/B selectors provide bounded seeks at every legal position.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the window rewind error and the provider boundary have fixed messages; the provider raise is made after the `except` closes; seed holders boxed and in the census | AT-S1b-13, AT-S2-4, AT-S2-8 | M-10, M-16 |
| 2 | Cleanup missing on an exit path | pool reservations release through the `ExitStack` callback and on the `selector is None` branch, as S1a; provider pools priced in both admitted preflight and legacy fit, reserved before construction | AT-S1b-3, AT-S1b-18, AT-S2-7 | M-3, M-6f, M-11 |
| 3 | State machine and concurrency | each stream owns its RNG or cursor; the window draw keeps a forward-only cursor and refuses a rewind; a pool build resolves before seeding, then draws | AT-S1b-5, AT-S1b-7, AT-S1b-7b, AT-S1b-14 | M-4, M-5, M-5c |
| 4 | Route parity and silent fallback | one `pool_eligible`, one `open_faker_pool_draw` and one `pool_key_columns` on reachable Faker routes, required keywords with a signature sentry and an AST guard; the admission matrix is the only route switch; effective locale checked before S3a opener and `draw_path`; lookup schema decided at admission or declined | AT-S1b-2, AT-S1b-10, AT-S1b-11, AT-S1b-12, AT-S2-2, AT-S2-6b, AT-S2-9 | M-1, M-2a, M-2b, M-6c, M-13, M-14 |
| 5 | Referential integrity | key columns stay per-row on all reachable Faker routes, so a parent key keeps its per-row draws | AT-S1b-2 | M-1, M-2a |
| 6 | Untrusted producer | snapshot-bound provider identity, callback exclusion and pinned lookup digest | AT-S2-6, AT-S2-9 | M-20, M-22 |
| 7 | Check then use (TOCTOU) on a path | N/A no filesystem access is added; lookup files are read and digested before this code by the existing loader | none needed | N/A no path checks |
| 8 | Weak tests and overclaimed evidence | parity at batch sizes 1, 7 and 4096 with the route asserted; frozen legacy digests for the null cells; perf on the Dell with separate build-order and selector witnesses; goldens listed by name | AT-S1b-9, AT-S2-1, AT-S2-3 | M-7, M-8, M-9 |
| 9 | Behavior-preserving refactor drift | `generate_batch` keeps its bytes through `open_batch_cursor`; `PoolSampler` REUSE through `open_reuse_cursor`; one `weighted_draw` for categorical and lookup | AT-S2-5, AT-S2-5b, AT-S2-10 | M-8, M-15 |
| 10 | Frozen contract drift | byte changes named in the changelog and the compatibility contract; the eligible set generated from certified data | AT-S1b-8, AT-S1b-14, section 9 | M-6, M-5c, M-6g |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| No exception context in output | yes | AT-S2-4 asserts no cause or context |
| Normalized guard scanners | yes | resolve import aliases and qualified names, scan named branch bodies, and run each guard against a byte-equivalent bypass |
| No reaching into private modules | yes | export lookup context, schema, draw and stream helpers from `generation.kinds`. Switch the touched private import at `synthesize.py:63` to that API. Export the shared index cursor, eligible registry and key helpers from `generation.pool`, and the window wrapper from `generation.stream` |
| No hidden CI failures | yes | perf cells carry the `perf` marker and run on the Dell; recorded in the PR |
| Mutations on the final head | yes | section 5 on the final head |
| No raised pins | yes | size sentry and compatibility vectors reviewed on final head; shrink oversize modules and ratchet pins down |
| Anchored regex, strict stored/wire types, versioned read models | no new grammar or persisted read model | reuse compiled config, pinned lookup and strict window validators |
| One trust class per entry, checked allowlisted helpers | yes | public compiled-plan entry supplies actual run inputs; only effective stock binding gets its cap; public helper guards in AT-S2-6/10 |

## 11. Enumerations

### 11.1 Exit paths

- Pool admitted and built: the stream or window draw serves values (`generation/_column_streams.py:347`, `generation/window.py:195`).
- Pool admitted, build declined: `open_pooled_selector` returns `None` and the column runs per-row (`generation/_faker_pool.py:491`).
- Budget refusal before the build: the ledger raises, as S1a.
- Window draw asked to rewind below its cursor: `RuntimeError`, fixed message (no caller today) (`generation/window.py:352`).
- Table of 0 rows: `pool_eligible` returns False before any build.
- Preflight refusal for a provider pool: before the first write.
- Provider failure in a stream or while it is built: `GENERATION_PROVIDER_FAILED`, no cause (`generation/kinds/_provider.py:79`).
- Semantic decline: legacy when all bounded checks fit or the run is unbounded. A missing width under a ceiling refuses before legacy.

### 11.2 Routes

- Legacy resident (`synthesize._faker` via `try_pool`, `generation/_faker_pool.py:292`).
- Pinned Faker refuses at compile and before _run on execute. Supported kinds only (`execute_pinned`, `generation/_pinned_execute.py:201`, to `synthesize._generate_column` directly; no `classify_plan`).
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
- `generate_rows`: direct per-row continuation at `row_count`, even for a huge offset.
- `streamed` only for admitted plans with a bounded sink and sufficient fit. Legacy refusal and route reasons retain their current codes.
- Lookup column Arrow schema on the streamed route (S2).

## 12. Slices

### S1b WIDEN-POOLS

Steps, in order (tests first, red before code):

1. Write all S1b ATs including 16 through 18. Establish the route, oracle and expected red for each mutation; record controls separately.
2. Moves first, no behavior change: tier tables to `scripts/faker-determinism/_tiers.py`; `_referenced_keys` out of `_streamed.py`.
3. Add tier 3 and its generator. Stage the probe inputs. Final certification needs the production opener and the span rule in step 6.
4. Add `pool/_keys.py` and `PlanAdmission.key_columns`; make `table` and `key_columns` required on `pool_opted_out`; thread `key_columns` through the receiving functions with no defaults; add the signature sentry and the AST guard.
5. Implement the size, build order, kwargs, actual-P legacy reservation and normalized address rules in 8.2. Wire the worker to the production opener and preserve the historical selector probe.
6. Implement bounded seeks, split spans and the direct out-of-table continuation in 8.4. Exercise existing Class B and per-row controls. Then run all three probe modes with the locked harness, record exclusions, commit the verified digests and generate the registry.
7. Add the two caps; census rows; update the draw-site notes, both bench scripts (worker and comparison driver) and the README, and the CODEMAP rows.
8. Regenerate the named goldens with the harness; stop on any other golden.
9. Run all S1b mutations on the final head, including M-5d/e and M-6e/f/g. Measure the worst cold one-row seek and run AT-S1b-9 on the Dell.

Files and budgets. The engine module size goal is 600 and the normal maximum is 700 (`tests/sentry/test_module_size.py`); `scripts/` follows the same limits except for existing legacy pins. The planner cap of about 800 per slice diff applies to the change, not to a module.

| File | Now | After |
|---|---|---|
| `generation/_faker_pool.py` | 577 | target 600; move the generated pair data out first. Put reusable mode/seek code in `generation/pool/` and export it. Keep window-specific work in `stream/` |
| `generation/pool/_eligible.py` | new | about 90 (generated) |
| `generation/pool/_keys.py` | new | about 60 |
| `generation/stream/_window_pool.py` | new | about 110, including interval splitting and deadline checks |
| `generation/pool/_sampler.py` | 543 | target 580 in S1b for the shared index cursor; at most 590 after S2 |
| `generation/_window_admission.py` | 475 | about 485 |
| `generation/window.py` | 385 | about 395 |
| `internal/faker_setup.py` | 699 at aa1c65631, 700 on its replay-fixed child | at most 700; consolidate the address wrapper in place and shorten its existing duplicated explanation |
| `scripts/bench-generation-pool/bench_compare_gen.py` | 908 | 908 or fewer; lower the exact pin if it shrinks, never raise it |
| `generation/_admission.py` | 301 | about 310 |
| `generation/_streamed.py` | 592 | target 600 including actual-P legacy accounting |
| `generation/_pinned_execute.py` | 264 | about +1 for required keyword |
| `scripts/bench-generation-pool/bench_worker_gen.py` | 266 | minus a few |
| `generation/_column_streams.py` | 413 | about 418 |
| `generation/_bounds.py` | 572 | about 575 |
| `generation/synthesize.py` | 587 | about 592 |
| `scripts/faker-determinism/pool_determinism_worker.py` | 180 | target 210, one opener and distinct probe records |
| `scripts/faker-determinism/write_eligible.py` | new | about 40 |
| `scripts/faker-determinism/check_determinism.py` | 597 | about 520 (tiers moved out) |
| `scripts/faker-determinism/_tiers.py` | new | about 100 with `TIER_3` |

Public names added: `pool_key_columns`, `referenced_key_columns`, `pool_size_for`, `open_faker_pool_draw`, `PlanAdmission.key_columns`, `PooledSelector.skip`, `WindowPoolDraw`.

Test depth: T0 per edit; T1 impact selection per commit (generation, parity, native draw-site tests, the harness cells for tier 3, the new guard); T2 on the exact head with the risk cells AT-S1b-2, AT-S1b-5, AT-S1b-7 and the harness. Full suite: yes, once on the final head, because S1b regenerates goldens and changes a frozen contract (escalation triggers in `testing.md`). It diffs against the saved main baseline. Include AT-S1b-14/16/17/18 and the timeout, seek and normalization mutations at T2.

### S2 STREAM-PROVIDER-LOOKUP

Steps:

1. Check the named stock bindings and public helper exports on the merged dependency head. Freeze reference outputs through the forced legacy generator before changing draws.
2. Write every S2 AT, including 5b and 6b, with bounded/unbounded controls and independent forced-route witnesses.
3. Refactors with no byte change: `open_batch_cursor` on the Faker adapter (AT-S2-5); `PoolSampler.open_reuse_cursor` (AT-S2-5b); `weighted_draw` (AT-S2-10).
4. Add `kinds/_provider_stream.py` and `LookupStream` with their census rows; export from `generation.kinds`; wire `make_column_stream`.
5. Thread prepared admission through the capacity floor and run inputs through bounds and construction. Propagate unresolved to config-only estimation. Use the same provider pool estimate in preflight, the live stage and legacy reservation.
6. Implement the whole-plan parity rule, safe lookup inference and fixed stock binding widths before changing the admission matrix.
7. On the combined head enforce locale first, then S3a's common computed spec, opener, width and layout rules, then ordinary dispatch. Update the S3a sentry.
8. Run all S2 mutations M-7 through M-24 against the exact final head.

| File | Now | After |
|---|---|---|
| `generation/__init__.py`, `execution/capacity.py` | 70 and 555 | about +10 each for the route-aware floor result |
| `generation/kinds/_provider_stream.py` | new | about 170; dispatch, cursors and provider error boundary reuse |
| `generation/pool/_sampler.py` | 543 at anchor | target 590 including shared cursor and bundle caller |
| `generation/kinds/_categorical.py` | measure at anchor | about +10 (`weighted_draw`) |
| `generation/kinds/__init__.py` | measure at anchor | about +4 |
| `generation/_column_streams.py` | about 418 | about 440 (lookup ctx with digests) |
| `generation/_streamed.py` | 592 on #813 | target 600 after preflight, legacy accounting and combined S3a layout/partition changes. Move cohesive planning code before adding more; recount on the combined head |
| `generation/_bounds.py` | about 575 | about 595 (two bounds, the keyword) |
| `generation/_admission.py` | about 310 | budget 390 including conservative whole-plan check and run inputs |
| `generation/pool/_resident.py`, `generation/pool/__init__.py` | existing | +35 and +5 for pool estimate and exports |
| `providers_v2/_registry.py`, `providers_v2/__init__.py` | existing | +20 and +3 for shared stock-binding decision if S3a has not landed |
| `generation/kinds/_provider.py` | 159 | budget 230 including shared provider boundary and stock metadata dispatch |
| `generation/kinds/_lookup.py` | 289 | about 345 (`LookupStream`, `lookup_stream_schema`) |
| `providers_v2/_faker_adapter.py` | 282 | about 295 |

Public names added: `open_provider_stream`, `LookupStream`, `lookup_stream_schema`, `weighted_draw`, `provider_payload_bound`, `lookup_payload_bound`, `PoolSampler.open_reuse_cursor`, `open_batch_cursor` (adapter method).

Test depth: T0 and T1 as above; T2 on the exact head with AT-S2-1 and the mutations. Full suite only if an escalation trigger is hit; none is expected (no golden moves, no frozen contract changes). Include AT-S2-11, the legacy-budget negative control, all-field schema fixtures and S3a layout cells. Enforce import-linter, size sentry and secret census on the combined head. Split into dependent, independently gated PRs if implementation plus tests exceeds the roughly 800-line slice budget; keep S2 admission closed until the whole gate passes.

### Order and dependencies

1. #813 (S1a) merges first. S1b, S2 and GNF S3a all build on its `generation/stream/` package.
2. GSA S1b and GNF S3a (`origin/docs/plans-pap-gnf-1125:docs/plans/2026-11-25-gen-nonfaker-draws-s3.md`) can build in parallel. Both touch `_bounds.py` (`faker_payload_bound`), `_window_admission.py`, `window._build_streams` and `_column_streams._faker_stream`; the second to merge rebases (recheck both paths after resolving conflicts). S1b pools no type that S3a computes (`uuid4`, `random_int`, `random_element`), so admission does not overlap. Where both reach `_faker_stream` and `_build_streams`, the computed check runs first, then the pool check, then per-row. S1b making pooled columns Class A in windows removes the Class B block that GNF deferred `text` and `paragraph` on; GNF's plan should note this.
3. Prefer S3a before S2. The second to merge owns AT-S2-6b, the fifth provider stream site in S3a's sentry, and the combined size recount. On the merged head update S3a’s sentry inventory: aliases stream on full runs and retain Class B for windows. Rebaseline AT-S3-5’s ordinary word control on merged S1b and assert it bypasses computed dispatch. The shared dispatch locale check runs before the computed opener. Use the computed spec for provider aliases in `_make_layout` and `_Layout.sizes` on both resident and sink routes. Respect S3a's 1,048,576-row and signed int32 payload limits, preserving zero pieces and bookkeeping for caller partitions. Build and price using the largest effective piece. Run both plans' parity and mutation gates on that head.
4. S2 before S3; S3 before S4. GEN-PER-COLUMN S1 starts only after S1a, S2 and S3 have landed (master plan cross-plan gate).

## 13. S3 and S4 outline

- S3 STATISTICAL-INHERIT. New `statistical/_stream.py` (about 120) and `relational/_inherit_stream.py` (about 100). Statistical columns stream with a fidelity accumulator (OWNER CALL master plan Q2, default: the accumulator, as recommended). The inherit parent map is reserved in the ledger before it is built. Tests A7, A8, A13. Depends on S2. `_streamed.py` is near its cap; S3 moves code out before it adds any.
- S4 ROUTE-CODES-CARD. `reasons/route/_generation.py` with `gen_legacy_*` codes, `quality_metrics["generation_route"]`, and the CLI `Generation` fact and `--json` block. Tests A9, A11. Depends on S3.

## 14. Pre-mortem

- A seek near a span boundary could restart the wrong RNG or overrun a deadline. AT-S1b-6/16 compare independent oracles and instrument discarded work. Huge external offsets never enter the selector.
- A Faker update or a seed-order edit changes how a locale-list proxy picks its factory. AT-S1b-14 pins the digest, so the Faker pin bump fails loudly.
- A cold page pays for one pool build per column per window. Bound it to 10,000 calls, check time between build groups and keep the draw lazy for wholly external reads.
- A harness run on a different Faker version would certify the wrong digests. The builder runs it in the locked env, and AT-S1b-8 ties the eligible set to the committed digests.
- A new caller of `pool_opted_out` on a parallel branch fails because `key_columns` is required. That is the intended failure.
- `_streamed.py` grows past 600 on a rebase or in S2. The builder moves `_pooled_columns` into `_admission.py` before adding the provider preflight.
- A stock-looking callback or an unproved schema could change bytes on route promotion. Keep that entire plan on the prior route and distinguish the bounded refusal in AT-S2-2/6.
- A new caller that reaches `pool_eligible` without a key set (for example in streamed preflight). The signature sentry and the AST guard make that a test failure, not a silent pool.
- The streamed sink on a mid-stream ledger refusal: S2's preflight closes the provider pool case before the first write. Whether the sink is transactional on other mid-stream refusals is unchanged by this plan.
