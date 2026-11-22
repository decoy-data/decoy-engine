Status: plan (revision 1, 2026-11-22)

# GEN-UNIQUE-STREAM: `unique: true` columns on the streamed lane

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GEN-UNIQUE-STREAM (V1 engine, approved 2026-11-22), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 2). It comes after GEN-STREAM-ALL S1 (`origin/plan/gen-stream-all` `008acffed`, called GSA below) and stays consistent with GEN-PER-COLUMN (`origin/plan/gen-per-column`, called GPC below).

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head. Where GSA S1a moves code (`_table_batches` to `generation/stream/_batches.py`), this plan names the moved place.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN, choke point, placement), `profiles/local-operations.md`, `feature-dev.md`, `performance.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `testing.md`, `architecture.md`, `api-and-compatibility.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`; GSA and GPC plans in full.

Risk: R2. It changes admission for a whole column family, adds a budget reservation, and moves the unique retry loop. Output bytes do not change. Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

- Admission declines every `unique: true` column except `sequence` (`generation/_admission.py:249-251`). One unique column sends the whole plan to `_run_legacy` (`generation/_streamed.py:543-600`), which holds every table resident and reserves the whole-table bound plus `table_unique_peak` (`:563-579`).
- Unique types are `sequence`, `categorical`, `faker` and `reference` (`config/_generate_unique.py`, `UNIQUE_TYPES`). Three draw functions live in `generation/_unique.py`:
  - `unique_faker` (`:54-98`): per row, attempt 0 seeds `row_int("faker", i)`, and a repeat retries with `row_int("faker_unique", i * 1000 + k - 1)` up to `UNIQUE_FAKER_ATTEMPTS`. `None` is emitted and not tracked. An exhausted row refuses through `raise_uniqueness_impossible` with `needed=n`, `available=len(seen)` and `row=i`.
  - `unique_categorical` (`:101-113`): one `random.Random.sample(distinct, take)`, then `None` for the overflow rows.
  - `unique_reference` (`:116-129`): one `sample(ref_vals, n)`, or the first `n` keys for `sequential`.
- Callers: `synthesize.py:431-435` (categorical), `:527-537` (faker) and `_synthesize_derived.py:206-209` (reference, after `check_reference_pool`).
- Study evidence: row `i` depends only on its own seeds and on the values accepted before it. With global row order and one seen set for the run, the streamed output equals the whole-table draw for every batch size. This was measured for `first_name` (600 rows, 4,296 retries, batches 1, 7, 256, 600) and `email` (100,000 rows, 19,046 retries, batches 1, 7, 256, 10,000, 100,000). The seen set costs no measurable time. A Python `set` of `str` measured 114 bytes per value, under the existing price of `payload + 129` bytes (`generation/_bounds.py:269-284`).

## 2. Established solutions

- **Faker's unique proxy** (`faker/proxy.py`, `_UNIQUE_ATTEMPTS = 1000`): a seen set with bounded retries. The engine already copies it with per-attempt HMAC reseeding (`_unique.py` docstring). This plan keeps that kernel and only changes who holds its state.
- **Streaming distinct with a bounded state.** A run-wide hash set over a stream is the standard streaming `DISTINCT` operator (hash aggregation, Graefe 1993). The memory is reserved up front in the existing budget ledger, as GSA does for the inherit map.
- **Prefix-stable sampling.** `random.Random.sample(population, k)` picks its branch from `k` and the population size, so it is computed once at open with the full `k` and sliced per batch. Slicing a computed list is trivially prefix-stable.

### Reuse inventory

- `generation/_unique.py`: `unique_faker` (the retry kernel), `unique_categorical`, `unique_reference`, `_where`, `_key_or_none`. No second retry loop is written.
- `generation/pool/_errors.raise_uniqueness_impossible`, `generation/pool/_capacity.unique_capacity_ok`: the refusal and the size rule.
- `generation/_bounds.py:269-284` `unique_set_bytes`: the one price of a unique working set.
- `generation/_budget_ledger.py:107` `GenerationBudgetLedger.reserve`, which raises `GenerationBudgetExceeded` with `reasons.runtime.GENERATION_BUDGET_EXCEEDED`.
- `generation/_column_streams.py`: `make_column_stream` (`:271`), `PerRowFakerStream` (`:155-193`, provider and instance resolution), `ReferenceStream`'s `check_reference_pool` call (`:221`), `NullMaskedStream` (`:241`), `KeyPool`.
- `generation/_streamed.py`: `_preflight` and `_Plan` (`:205-247`), the stream-or-resident decision (`:406-414`).
- `generation/_faker_pool.py:243-251` `pool_opted_out`: a unique column already never pools.
- GSA S4 route codes in `reasons/route/_generation.py` and GPC's per-column codes: this plan removes one code from use and adds none.

## 3. Guarantee and non-goals

After this plan:

1. A `unique: true` column of type `faker`, `categorical` or `reference` that passes its kind's normal admission runs on the streamed lane. It no longer declines the plan.
2. Output is byte identical to `70881ad79`'s legacy output for every batch size and partition, resident or sink, with and without `null_probability`.
3. The retry seed order is the legacy order: global row order, attempt 0 `row_int("faker", i)`, attempt `k` `row_int("faker_unique", i * 1000 + k - 1)`. `None` is not tracked. A value nulled later by `null_probability` stays in the seen set.
4. Refusals are the same code, message and row as legacy (`uniqueness_impossible` with `needed` = the table rows and the global row index).
5. Each streamed unique column reserves `unique_set_bytes(rows, payload)` when it opens. The preflight counts the sum over a table's unique columns, so a plan that cannot hold them refuses with `generation_budget_exceeded` before any row is written.
6. `unique_together` pair members stay on the legacy path (decline `unique_pair`, unchanged).

Non-goals: streaming `unique_together`; hashing the seen set (the study measured little gain and a collision risk); a native seen set; threading attempt 0 (the two-phase shape in the study is a follow-up); any change to a kind's non-unique stream.

## 4. Enumerations

### Exit paths

- Streamed, resident and sink: unchanged shapes.
- Legacy: still reached by pair members and by any other declined column.
- `uniqueness_impossible` (`raise_uniqueness_impossible`): faker at the exhausted row; categorical and reference at stream open, before the first batch, as the legacy draw raises before it returns.
- `GenerationBudgetExceeded` (`generation_budget_exceeded`): at preflight (`generation/_streamed.py:406-414`, extended by the unique sum), and as a backstop at stream open through `ledger.reserve`.
- `check_reference_pool` refusals and warnings for a unique reference: same call, same order as legacy (`_synthesize_derived.py:203-209`).

### Routes and codes

- Admission: delete the `unique` decline (`generation/_admission.py:249-251`); a unique column then meets its kind's checks (`faker_custom_or_unresolved_provider`, `reference_*`, `family_declined:*`).
- Pair members: `unique_pair` decline unchanged (`:252-253`).
- Codes: GSA S4 registers `gen_legacy_unique`; GPC renames it `gen_whole_column_unique`. After this plan no column declines for being unique, so the code has no producer. Pre-GA rule (hard delete): this slice removes it from the decline table and tombstones it in `reasons/route/_retired.py` if GPC's tombstone file exists, or deletes the registry row if the code has never shipped in a release. The registry sentry proves no producer is left. No code is added.

### FK shapes

- A unique faker or categorical column that is a `reference` target: its batches feed the `KeyPool` collector as any streamed column does. GPC's held-parent-key case (V10) becomes a plain streamed parent.
- A unique `reference` child: `UniqueReferenceStream` reads the sealed parent `KeyPool` list (`key_pools[(table, column)]`) like `ReferenceStream`.
- `unique_together` (two `reference` members): legacy, unchanged.

### Fields

- No config field changes. `unique`, `null_probability`, `distribution`, `faker_type`, `faker_kwargs`, `locale` are read as today.
- `_Plan` gains `unique_peak: int`, counted in `streaming_peak()` and `resident_peak()`.

### Output surfaces

- Generated bytes: identical (guarantee 2).
- `GenerationResult.route` becomes `streamed` or `resident` instead of legacy for these plans, and `.declines` loses the `unique` entries. The run card's generation fact (GSA S4) changes with it.
- Draw-site catalogue entries for `unique_faker`, `unique_categorical`, `unique_reference` (`execution/native/_draw_sites_gen.py:333`, `:354`, `:370`): `call_site` text is updated only if a function moves (the plan keeps the names in `_unique.py`).
- `docs/qa/12-generation.md`: the unique row moves from "legacy" to "streamed".

## 5. Design notes

### One retry kernel, two callers

`generation/_unique.py` gains `UniqueFakerDraw`, which holds `inst`, `provider`, `kwargs`, `gen_ctx`, `needed` (the table rows), `table`, `column` and the seen set. `draw(offset, size) -> list[Any]` runs the existing loop body for rows `offset .. offset + size - 1`, moved verbatim. `unique_faker(...)` becomes `UniqueFakerDraw(...).draw(0, n)`, so the legacy path and the stream share one loop. The seen set lives on the instance and dies with it. Each run builds one per column, and nothing is module level.

### Streams (new module `generation/stream/_unique.py`, beside GSA's `_batches.py`)

- `UniqueFakerStream(col, ctx, seed, rows, instance_default_locale, provider_snapshot)`: resolves the instance and provider exactly as `PerRowFakerStream` does, so one resolver is shared. The builder lifts the resolution in `PerRowFakerStream.__init__` (`_column_streams.py:158-186`) into a function `resolve_faker(col, seed, instance_default_locale, provider_snapshot) -> (inst, provider, kwargs)`, and both streams call it. `next_batch(offset, size)` returns `self._draw.draw(offset, size)`. A check asserts `offset` equals the previous end, because the seen set needs global row order, and a skipped or repeated window raises `ValueError` (a programming error, not a user refusal).
- `UniqueSampleStream(values: list[Any], rows: int)`: holds the list computed at open and returns `values[offset:offset + size]`. Rows past the list are `None` (categorical overflow), so the stream never builds `rows` copies of `None`.
  - Categorical: `values` from `unique_categorical(col, rows, seed, derive_key)` with the overflow fill removed. The builder splits that function into `unique_categorical_sample(col, n, seed, derive_key) -> list[Any]` (the `take` list) and keeps `unique_categorical` as `sample + [None] * (n - take)` for legacy. One sample, two callers.
  - Reference: `check_reference_pool(...)` first (same order as `_synthesize_derived.py:203-205`), then `values = unique_reference(col, ref_vals, rows, seed, derive_key)`.
- `make_column_stream` (`_column_streams.py:271`) routes `col.get("unique") is True` for `faker`, `categorical` and `reference` to these streams. `sequence` keeps `SequenceStream`. `NullMaskedStream` still wraps when `null_probability > 0`, so the null mask runs after the unique draw, as legacy does.

### Budget

- `generation/_bounds.py` gains `table_unique_concurrent_bytes(table, payload_of) -> int`: the sum of `unique_set_bytes(rows, payload_of(col))` over the table's streamed unique columns. On the streamed lane every column of a table is open at once, so their sets coexist. `table_unique_peak` (the max, for the legacy loop where columns run one after another) stays for legacy and GPC.
- `_preflight` adds `unique_peak = max over tables of table_unique_concurrent_bytes(...)`. Tables run one after another and each table's stage closes its reservations. Both peaks include it, so the stream-or-resident decision and the resident refusal at `_streamed.py:406-414` see it before any provider runs.
- At stream open: `stage.callback(ledger.reserve(f"unique_set:{table}.{column}", unique_set_bytes(rows, payload)).release)`. The preflight already proved it fits, so this is the backstop and the ledger's record. It is released when the table's stage closes.
- Unbounded runs: `_refuse_if_over_memory` is unchanged. `generation_floor_shortfall` already adds `table_unique_peak` for resident floors (`_bounds.py:366`). The builder switches that line to the concurrent sum for tables the streamed lane will run. A test pins the figure (A6).

### Coordination with GSA and GPC

- Order: after GSA S1a (the batch assembler and `generation/stream/` exist). GSA S1b, S2, S3 and S4 are independent of this plan.
- GSA's routes table lists "any kind with `unique: true` -> legacy, `gen_legacy_unique`". This plan replaces that row with "`unique_together` member -> legacy, `unique_pair`", and the code is retired as section 4 says.
- GPC treats `unique` as `whole_column` (`gen_whole_column_unique`). If this plan merges first, GPC drops that row and its tests that use a unique faker as the whole-column example (GPC V1, V7, V10, V-speed) switch to `formula` or `unique_together`. If GPC merges first, this plan moves unique columns from `whole_column` to `streamed` and retires `gen_whole_column_unique`. Either order gives the same end state. The builder of the second slice owns the edit.

### Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_unique.py` | `src/decoy_engine/generation/stream/` (GSA S1a package) | GSA's "Generation streamed batch assembly" row | `_batches.py` |
| `test_unique_stream.py` | `tests/unit/generation/stream/` | GSA's test row | GSA's stream tests |

Sizes: `generation/_unique.py` 178 to about 200; `generation/stream/_unique.py` about 110; `_column_streams.py` +about 15 net (resolver lifted, dispatch added); `_bounds.py` 580 to about 595 (under 600; if it passes 600, `table_unique_concurrent_bytes` and `unique_set_bytes` move to `generation/_bounds_unique.py`, no ceiling raised); `_streamed.py` +about 8; `_admission.py` minus 3. Tests about 350 lines. Slice size 1.0.

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the uniqueness refusal | `raise_uniqueness_impossible` unchanged: counts, row, table, column, never a value | A4 | put the repeated value in the message (A4 red) |
| 2 | Cleanup missing on an exit path | the unique reservation on refusal | reservation released by the table `stage` `ExitStack` on every exit | A5 | release only on success (A5 red: ledger not back to zero) |
| 3 | State and concurrency | the run-wide seen set | one `UniqueFakerDraw` per column per run; order check on `offset` | A1, A7 | share the seen set across two columns (A3 red) |
| 4 | Route parity and silent fallback | streamed vs legacy unique | one kernel (`UniqueFakerDraw`, `unique_categorical_sample`, `unique_reference`) behind both | A1, A2 | fork the loop for the stream (structure check A8 red) |
| 5 | Referential integrity | unique parent keys feeding `KeyPool`; unique reference children | collector reads emitted batches; child reads the sealed pool | A2 | collect before the null mask (A2 red) |
| 6 | Untrusted producer | unkeyable faker values | `_key_or_none` refusal path kept | A4 | treat an unkeyable value as new (A4 red) |
| 7 | Check then use | preflight fits, then reserve at open | preflight and reserve use the same `unique_set_bytes` and payload bound | A5, A6 | preflight with the max instead of the sum (A6 red) |
| 8 | Weak tests | small columns with no retries | the study cases: `first_name` 600 rows (4,296 retries), `email` 100,000 rows; batches {1, 7, 256, rows}; irregular partitions | A1 | reseed attempt `k` with `i * 1000 + k` (A1 red) |
| 9 | Behavior-preserving refactor drift | moving the loop into `UniqueFakerDraw` | the legacy unit suite for `_unique.py` unchanged; A1 digests from `70881ad79` | A1, A3 | M1, M2 |
| 10 | Frozen contract drift | route code retired; draw-site text | registry retire rule; catalogue pin re-run | A9 | leave the code registered with no producer (registry sentry red) |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | none |
| 2 | Strict wire types | no | no new stored field |
| 3 | No exception context | yes | `GenerationBudgetExceeded` and `uniqueness_impossible` are raised outside any `except`; A4 and A5 assert `__cause__` and `__context__` are `None` |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | yes | A8 checks with an AST walk, not text, that `generation/` has one `faker_unique` reseed site |
| 6 | No private reaching | yes | `generation/stream/_unique.py` imports from the same `generation` package tree only |
| 7 | No hidden CI failures | yes | no skips; no `|| true` |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | run on the final head, head recorded |
| 10 | Allowlisted helpers checked | no | none |
| 11 | No raised caps | yes | `_bounds.py` split rather than a raised ceiling; `generation/` fan-out unchanged (new module in GSA's sub-package) |

## 7. Acceptance tests (each with its fail-before)

- **A1** Batch invariance and legacy parity: `first_name` unique, 600 rows; `email` unique, 100,000 rows; batches {1, 7, 256, 10,000, rows} and two irregular partitions; resident and sink. Every case gives the `70881ad79` legacy digest (captured from main in the test). Fail-before: the plan is declined, so no streamed run exists.
- **A2** With `null_probability: 0.2` and as a `reference` parent: the same digests as legacy; the child's picks match legacy.
- **A3** Two unique faker columns in one table, same `faker_type`: each equals its own legacy output (independent seen sets).
- **A4** Refusal: a unique categorical with 3 categories over 5 rows, and a unique faker over a type with 10 values for 20 rows: same code, message and row as legacy; no value in the message; no exception context.
- **A5** Ledger: after A4's refusal, `charged_bytes` is 0.
- **A6** Budget: a table with two unique `email` columns under a ceiling that fits one set but not two refuses at preflight with `generation_budget_exceeded`, before any batch is written (sink receives nothing). Fail-before: the legacy path refuses with the whole-table message, so the test asserts the stage name `unique_set` is in the ledger events of the passing case and the preflight figure equals the sum.
- **A7** Order guard: calling `UniqueFakerStream.next_batch` with a skipped offset raises `ValueError`.
- **A8** One kernel: an AST check finds exactly one `row_int("faker_unique", ...)` call under `src/decoy_engine/generation/`.
- **A9** Admission: a plan with `id: sequence`, `email: faker unique: true`, `tier: categorical unique: true` reports route `streamed` and no declines. A plan with `unique_together` still declines its members with `unique_pair`. The retired code has no producer (registry sentry).
- **A10** Speed and memory (Dell through `vm-run`, reported, no target on speed): 1M rows, five pooled faker columns plus one unique `email`. The run is streamed, and peak ledger bytes are below the legacy whole-table reservation for the same plan.

## 8. Named mutations

- M1: retry seed `i * 1000 + k` instead of `i * 1000 + k - 1` -> A1 red.
- M2: add `None` to the seen set -> A2 red (null rows), A4 unchanged.
- M3: reset the seen set per batch -> A1 red at batch 7.
- M4: sum replaced by max in the preflight -> A6 red.
- M5: release the reservation only on success -> A5 red.
- M6: draw the categorical sample per batch with `k = size` -> A1 red for categorical.

## 9. Slices

| Slice | Content | Size | Risk |
|---|---|---|---|
| S1 | `UniqueFakerDraw`, `unique_categorical_sample`, `resolve_faker`, `generation/stream/_unique.py`, `make_column_stream` dispatch, admission change, preflight and reservation, code retirement, docs row, A1 to A10 | 1.0 | R2 |

Depends on GSA S1a. Changelog fragment, not breaking: "`unique: true` columns now stream; output unchanged." Test depth: T0 per edit, T1 impact-selected per commit (generation parity suites, the route registry sentry and the draw-site catalogue pin are in the selection). Escalation trigger: retiring a reason code touches a frozen contract (the route registry), so the full suite runs once on the merge head.

## 10. Frozen contracts

- Route reason registry: one code retired (`gen_legacy_unique`, or `gen_whole_column_unique` if GPC landed first) by the registry's retire rule. No code is added.
- Generated bytes: unchanged. `SEED_PROTOCOL_VERSION`: unchanged.
- `GenerationResult.route` for unique plans: `streamed` or `resident` instead of legacy. This is a value of an existing field, and it is named in the changelog.

## 11. Pre-mortem

- **A legacy detail the stream misses**, for example the order of `check_reference_pool` and the sample, or the pre-seed of the default Faker instance. The shared resolver and the A1 and A2 digests against main catch it.
- **A partition feeds rows out of order.** The offset check (A7) stops it loudly. The streamed lane writes tables in order today, so this is a guard for a later parallel layout.
- **Many unique columns in one wide table** make the summed reservation large. That is correct: the sets coexist. The refusal names the stage, and the user can lower rows or drop `unique`.
- **GPC and this plan both edit `_admission.py` and the route codes.** Section 5 names the end state for either order.

## 12. Open questions

None for the owner. The code retirement follows the pre-GA hard-delete rule.

## 13. Follow-ups (not this plan)

- Two-phase draw (attempt 0 for a batch in parallel, then a sequential retry pass), measured byte identical in the study; useful when NATIVE-THREADS-DEFAULT reaches generation.
- `unique_together` on the streamed lane (a two-column hook).
