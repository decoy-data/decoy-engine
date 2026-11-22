Status: plan (revision 1, 2026-11-22)

# EXPECT-OFF-ROUTE: validators run on the route that was chosen, and the run card reports them

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap rows: EXPECT-OFF-ROUTE (engine, new) and EXPECT-REPORT (CLI, rank 7 in the V1 fast-path audit, folded in as slice S4). Source: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, section "Two earlier findings, checked", and the owner direction of 2026-11-22: every strategy runs its fastest path by default, each column runs its own path, faster and more robust wins even when output bytes change (every byte change is named here), output stays deterministic per seed, engine-gap deadline 2026-12-15. Four slices: three engine PRs and one engine-plus-CLI pair (S4).

Anchors: a path with no prefix is in this repository (decoy-engine); `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` `77da171f`. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, design notes, choke point, placement), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `performance.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `security.md`, `observability-and-resilience.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` (module size: aim 600, hard max 700) and `CODEMAP.md` ("Where Things Go"). Related plans read: `plan/route-label-truth`, `plan/per-column-routing`, `plan/when-reads-source`, `plan/uf-domain`, `plan/gen-stream-all`, `plan/native-threads-default`, `plan/faker-default-pool` (engine), `plan/csv-write-fast` (CLI).

Risk: R2. The change moves a fail-closed privacy check (`leak_check`) and the other job-level validators onto every route. It changes the publish order on the streamed routes (validation must finish before commit), the evidence shape (`quality_metrics["validation"]`) and the CLI `--json` shape. No key material, no vault, no destructive operation. Plan review: Dennis, then Codex. Code gate: Codex and Dennis on every slice (fail-closed privacy path).

## 1. Frame

Evidence:

- Any `validators:` entry (the language's `expect` line) sends the table to pandas. The unified slice declines at `src/decoy_engine/execution/_unified_slice_admission.py:252-256` (`config.get("validators") or config.get("quarantine") or post_scan_model_setting(config) is not None`; this is the `:253` the audit cites).
- The same rule is copied at seven more sites. Each keeps a validator-bearing job off its fast or bounded route:
  1. `src/decoy_engine/execution/_chunked_output_sink.py:114-115`: `decide_output_mode` keeps an auto-chunk run resident (`VALIDATORS_PRESENT`).
  2. `src/decoy_engine/execution/_pipeline_routing.py:144-145`: `_sequential_eligible` refuses the bounded FK route.
  3. `src/decoy_engine/execution/_pipeline_routing.py:338-345`, with `src/decoy_engine/execution/_pipeline_routing_signals.py:547`, `:598` and `src/decoy_engine/execution/out_of_core/_validate_batch.py:73`, `:76`, `:144-177`: out-of-core admits only six per-cell validators, and only on `truncate`, `redact` and `passthrough` string columns (D3a).
  4. `src/decoy_engine/execution/_pipeline_multi_table.py:150`: the multi-table split.
  5. `src/decoy_engine/execution/physical/_shadow_full_frame.py:387-389`: the physical full-frame driver.
  6. `src/decoy_engine/execution/physical/_shadow_mixed.py:342-345`: the mixed generate-and-mask driver.
  7. `src/decoy_engine/execution/physical/_shadow_generation.py:414-417`: the generation driver.
- Validators run once, on the resident outputs, in `finalize_validators_and_quarantine` (`src/decoy_engine/execution/_pipeline_finalize.py:359-393`), which calls `validators._registry.validate` (`src/decoy_engine/validators/_registry.py:77-138`). The unified slice already calls the same finalize step on its resident output (`src/decoy_engine/execution/_unified_slice.py:316-322`). So the unified-slice decline guards nothing that the lane cannot do. The real gap is on the streamed and bounded routes, where no resident output exists.
- A per-batch validator collector already exists for out-of-core (`src/decoy_engine/execution/out_of_core/_validate_batch.py:194-270`, `ValidatorCollector`). It shifts batch-relative row indices to whole-table positions and keeps every failing position. Its docstring says that state is "O(failing rows) and unbounded in the worst case" (`:28-30`).
- Each validator reads whole columns with `to_pylist()` (for example `src/decoy_engine/validators/_catalog.py:66`, `src/decoy_engine/validators/_leak_check.py:281-282`, `src/decoy_engine/validators/_fk_validators.py:104`, `:134`). Each finding carries every failing row index (`src/decoy_engine/validators/_types.py:43`). A 10M-row `leak_check` that fails at the column tier stores 10M indices in `quality_metrics`.
- Audit, checked on CLI main: a passing check is not reported. Neither the run card nor `decoy run --json` (`CLI:src/decoy/cli/run/_render.py:117-152`, `:159-176`) reads `quality_metrics["validation"]`.
- Audit: `keep email` plus `expect leak_check(customers.email)` exits 0 and never checks the column. `leak_check` skips the `passthrough` strategy (`src/decoy_engine/validators/_leak_check.py:79` `EXCLUDED`, applied at `:260-261`; the audit's `:87` names the same rule) and records nothing.

What this costs the user: one `expect` line turns a native 2k-row hash job into a pandas job, and a 120k-row bounded streamed job into a resident one. The second is the NONFK-OOM risk that the auto-chunk lane exists to remove.

## 2. Established solutions

Search run (2026-11-22): Apache Beam `CombineFn`; Great Expectations validation results; AWS Deequ analyzers; dbt tests; Spark accumulators; streaming GROUP BY partial aggregation (DuckDB, Polars streaming); Spark `FileOutputCommitter`. In the codebase: `ValidatorCollector` and `OutputEvidenceAccumulator`.

- **Combine functions.** Beam's `CombineFn` (`create_accumulator`, `add_input`, `merge_accumulators`, `extract_output`) is the standard form for a check that sees elements one at a time and gives one result. Each validator becomes one fold of this form. The resident route calls it with one span; the streamed routes call it once per chunk. Merge is not needed: every route delivers a table's rows in order, on one thread.
- **Exact count, capped sample.** Deequ computes checks from analyzer states that combine across partitions. Great Expectations reports `unexpected_count` (exact) beside `partial_unexpected_index_list` (a capped sample). This plan follows that split: the count is exact and the index list is a capped prefix.
- **Two-sided key checks.** A referential check over a stream builds the parent key set first, then probes the child per batch: the build/probe hash join (Graefe 1993, "Query evaluation techniques for large databases"). The engine already follows the parent-first order (SDV HMA1 method, cited at `src/decoy_engine/validators/_fk_validators.py:160`).
- **Validate before commit.** Spark's `FileOutputCommitter` and Decoy's `OutputPublish` (`src/decoy_engine/execution/_chunked_output_sink.py:120-160`) stage output and make it visible once, at the end. A check that finishes before `commit()` and raises on failure gives "nothing published" by construction. Out-of-core already does this (`src/decoy_engine/execution/out_of_core/_validate_batch.py:304-317`, "Runs before the sink publish").

Custom code still needed: the fold form of each of the 11 validators, and one session that owns them. No library computes Decoy's validator verdicts. The folds reuse the verdict code that exists today.

### Reuse inventory

- `src/decoy_engine/validators/_registry.py` `_REGISTRY` and `validate`: the one name-to-validator map and the public entry point. Both stay; `validate` becomes a one-span session.
- `src/decoy_engine/execution/out_of_core/_validate_batch.py` `ValidatorCollector` (`:194-270`): the offset shift and the configured-order re-emit move into the session. The module then loses the collector (S1) and the allowlists (S3).
- `src/decoy_engine/execution/_chunked_output_sink.py` `OutputPublish` (commit once, abort on exit) and `OutputEvidenceAccumulator` (fold per chunk, O(columns) state): the commit point and the state pattern.
- `src/decoy_engine/execution/_pipeline_finalize.py:359-470` `finalize_validators_and_quarantine`: the D8 quarantine and row-error logic stays, and reads the session's report.
- `src/decoy_engine/validators/_leak_check.py` `TRANSFORMATIVE`, `SHAPE_PRESERVING`, `EXCLUDED`, `_is_identical`, `_fk_child_columns`: classification unchanged; the skip reasons are recorded, none is added.
- `src/decoy_engine/reasons/route/_retired.py:14-19`: the tombstone pattern for `validators_present` (`reasons/route/_part1.py:286`) and `out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`).
- `src/decoy_engine/reasons/warning/_part1.py:45` `_d = _catalog.warning("QualityWarning")`: the registration form for the skip codes and warning.
- `detected_memory_bytes` (used by `generation/_streamed.py` `_refuse_if_over_memory`): the memory figure the key-state budget reads.
- CLI: `CLI:src/decoy/cli/run/_render.py` facts and `--json` payload; the shape snapshot `CLI:tests/fixtures/release_freeze/json-shapes.json`.

## 3. Guarantee and non-goals

After this row:

1. A `validators:` block never changes the route. A job with validators takes the route the same job takes without them: unified slice, auto-chunk (resident and streamed), full frame, physical full-frame and mixed drivers, sequential FK, out-of-core FK, multi-table split, and generation with a sink. The one exception is quarantine with the `validation_fail` trigger. It removes rows, so it stays resident (named in section 4, code `quarantine_enabled`, unchanged).
2. Every configured validator runs on the bytes the route publishes. It reads the output, the source, or both, as its shape says (section 4).
3. On the streamed and bounded routes, validator state is bounded: per finding at most `FINDING_INDEX_CAP` row indices plus counters; for `leak_check` at most two source chunks in flight; for a key check one parent key map, sized against a budget, with a coded refusal when it would not fit.
4. A failing validator fails the job (`ValidatorFailedError`, CLI exit 3) and nothing is published. On a streamed route the session finishes before `OutputPublish.commit()`, and the failure aborts the staged output.
5. `quality_metrics["validation"]` is the one result. One function (`ValidationSession.finish`) writes it, on every route. The report is a function of (config, published bytes): the same at any chunk size and on any route that publishes the same bytes.
6. The run card and `decoy run --json` show every configured check with its result (passed, failed or skipped), including passes (S4).
7. `leak_check` records each column it does not check, with a registered code. A column named in `columns:` that it skips raises a `QualityWarning` and shows on the run card (S4). The run still exits 0, as the audit asks.

Non-goals: quarantine on the streamed routes (row removal after a streamed write needs its own design); new validator kinds; any verdict rule change (thresholds, `TRANSFORMATIVE` classes); `post_validation` and `fidelity_report` routing (separate rows); `decoy validate` running validators on data.

## 4. Enumerations

### Validator shapes (one per registry entry)

| Shape | Reads | Validators | State on a bounded route |
|---|---|---|---|
| `cell` | published output, row by row | `luhn`, `npi`, `iban`, `vin`, `regex_match`, `column_in_set`, `no_orphan_children` | per finding: count plus first `FINDING_INDEX_CAP` indices |
| `paired` | published output plus the source, aligned by row | `leak_check` | per column: compared and identical counts, first `FINDING_INDEX_CAP` identical indices; at most 2 source chunks in flight |
| `keyed` | two published tables, parent first | `fk_intact`, `parent_window_respected`, `reconciliation_holds` | one parent map (key set; key to window; or key to parent row and value) plus per-key child sums for `reconciliation_holds`; reserved against the key-state budget |

`no_orphan_children` is `cell`: it flags null FK cells on child rows (`src/decoy_engine/validators/_fk_validators.py:244-249`) and reads no parent. A test fails if a name in `_REGISTRY` has no shape.

### FK shapes (for the `keyed` validators and `no_orphan_children`)

| FK shape | Today (resident) | Bounded route after S3 |
|---|---|---|
| Single-column FK | parent key set, child probe (`_fk_validators.py:72-113`) | same fold: parent keys built from the parent's published batches, child probed per batch |
| Composite FK | key tuples in column order (`_fk_validators.py:79-81`) | same tuples; key width estimate sums the columns |
| Nullable FK (all FK columns null) | not a break for `fk_intact`; a finding for `no_orphan_children` | unchanged; null check is per cell |
| Several parents for one child | one edge per relationship entry | one key map per parent edge, each reserved against the budget |
| Self-reference (parent table is the child table) | one table, both sides resident | a child row whose key has not yet been seen goes in a pending map (key to first indices, capped) and is probed at table end; the pending map is reserved against the same budget |
| Cross-table FK cycle | auto full-frame fallback (cycles stay V2) | unchanged: the run is resident, so the fold gets one span per table |

### Fields

| Type | Field | Kind | Meaning |
|---|---|---|---|
| `ValidatorFinding` | `failing_row_count` | new, `int` | exact count of failing rows |
| `ValidatorFinding` | `failing_row_indices` | changed | first `FINDING_INDEX_CAP` failing positions in row order; all of them under quarantine `validation_fail` |
| `ValidationReport` | `results` | new, `tuple[ValidatorResult, ...]` | one per configured entry, in config order |
| `ValidationReport` | `elapsed_ms` | changed | summed fold time over the run |
| `ValidatorResult` | `validator`, `entry_index`, `status`, `checked`, `skipped`, `failing_row_count` | new type | `status` is `Literal["passed", "failed", "skipped"]`; `checked` is (table, column) pairs |
| `SkippedColumn` | `table`, `column`, `code` | new type | `code` is a registered skip code |
| `RowSpan` | `offset`, `output`, `source` | new, internal to the session API | one span of rows fed to a fold |

### Exit paths

1. All validators pass: `quality_metrics["validation"]` written; the run goes on to commit.
2. A validator fails and quarantine does not cover it: `finish` raises `ValidatorFailedError(report)` before commit; staged output is aborted; CLI exit 3.
3. A validator fails and quarantine `validation_fail` is configured: resident route only (the D8 path, `_pipeline_finalize.py:410-470`, unchanged).
4. Parameter error (bad regex, missing `allowed_values`, unknown validator, `leak_check` naming a generate table): raised when the session opens, before any source read, as today (out-of-core does this at `_validate_batch.py:203-205`).
5. `leak_check` with no source for a table in scope: `ValueError` as today (`_leak_check.py:236-241`), raised at open.
6. New refusals. Each is a `ValidatorStateError` (a `DecoyError`) with a registered runtime code, raised after any `except` block closes:
   - `validator_key_state_over_budget`: the parent map estimate (parent rows times key bytes) exceeds the key-state budget. Checked before the parent's first batch is written, and again as the map grows.
   - `validator_parent_not_observed`: a child batch reaches a `keyed` fold before its parent table finished. No route does this today (all deliver parents first). The refusal makes the order a checked rule.
   - `validator_chunk_pairing_mismatch`: a source chunk and its masked chunk differ in row count, or more than two source chunks wait.
   - `validator_table_not_observed`: at `finish`, a table in a validator's scope published rows the session did not observe (counts differ). This is the construction guard for guarantee 2.

### Routes and what each one feeds the session

| Route | Today | After | Feed |
|---|---|---|---|
| Unified slice | declined (`_unified_slice_admission.py:253`) | admitted | `observe(table, output, source=resident source)` in the existing finalize call |
| Full frame (pandas oracle) | runs validators | same | `observe` per resident output table, in finalize |
| Physical full-frame driver | declined (`_shadow_full_frame.py:387`) | admitted | finalize |
| Physical mixed driver | declined (`_shadow_mixed.py:342`) | admitted | finalize |
| Physical generation driver | declined (`_shadow_generation.py:414`) | admitted | finalize (no source) |
| Auto-chunk, resident | runs validators on the joined output | same, through the session | finalize |
| Auto-chunk, streamed to a sink | declined (`_chunked_output_sink.py:114`) | admitted | `tap(table, masked_chunks, source_chunks)` around `_core.mask_chunked` (`_pipeline_auto_chunk.py:384-408`) |
| Multi-table split | declined (`_pipeline_multi_table.py:150`) | admitted | `tap` per dispatched table |
| Sequential FK | declined (`_pipeline_routing.py:145`) | admitted | `observe(table, output, source)` per table, before the table is written and evicted |
| Out-of-core FK | six validators on three strategies (D3a) | all validators | `observe_masked` at `_stream_driver.py:374` (paired folds, with the source batch); `observe_published` at `_rewrite_pass.py:233` and, for tables with no incoming FK, at the mask step (cell and keyed folds) |
| Generation with a sink | declined (`decide_output_mode`, called at `_pipeline_generate_mask.py:184`) | admitted | `observe` on each batch in the `generate` callback before `sink.write_batches` (`generation/_streamed.py:525-527`) |
| Quarantine `validation_fail` | resident | resident (named exception) | finalize |

On every route except out-of-core, the masked rows are the published rows, so one `observe` call feeds all three shapes. Out-of-core rewrites incoming FK child key columns after the mask step. `leak_check` never checks FK child columns (`_leak_check.py:251-252`), so its paired fold reads the mask-step batch, and the other shapes read the published batch. The session checks that both feeds saw every row.

### Codes

- New runtime codes (`reasons/runtime/_part3.py`, declarer `_catalog.runtime("ValidatorStateError")`): `validator_key_state_over_budget`, `validator_parent_not_observed`, `validator_chunk_pairing_mismatch`, `validator_table_not_observed`.
- New warning code (`reasons/warning/_part1.py`): `leak_check_column_not_checked`.
- Skip codes on a `leak_check` result, one per existing exclusion (same warning catalog): `leak_check_skip_passthrough`, `leak_check_skip_fk_child`, `leak_check_skip_when`, `leak_check_skip_exempt`, `leak_check_skip_missing_column`.
- Tombstoned in `reasons/route/_retired.py` (`deprecated_in` = the release that carries S3, no `replaced_by`): `route.validators_present`. Tombstoned in a runtime `_retired.py` (created beside `_part3.py` if absent, as `plan/when-reads-source` does): `runtime.out_of_core_validators_not_admitted`. The alias `ROUTE_VALIDATORS_PRESENT` (`physical/_reasons.py:56`, `:101`, `:343`) is deleted.

### Output surfaces (byte and shape changes; each on a changelog `Breaking:` line)

1. **Route.** A job with validators runs the route it runs without them, so its output bytes are that route's bytes. The differences between routes are the ones already listed in `tests/parity/SEMANTIC_DIFFERENCES.md` (for example `hash` and `categorical` Unicode normalization on the native kernels). A validator now judges the bytes that are published.
2. **`ValidatorFinding`** gains `failing_row_count: int` (exact). `failing_row_indices` holds the first `FINDING_INDEX_CAP` = 10,000 failing positions in row order. When quarantine with `validation_fail` is configured, the list is complete, because quarantine removes those rows. The cap depends on the config, never on the route.
3. **`ValidationReport`** gains `results: tuple[ValidatorResult, ...]`, one per configured entry, in order: `validator`, `entry_index`, `status` (`Literal["passed", "failed", "skipped"]`), `checked` (table and column pairs), `skipped` (table, column, code), `failing_row_count`. `findings`, `passed` and `validators_run` keep their meaning.
4. **`elapsed_ms`** is the summed fold time across the run (it was the time of one call).
5. **`detail`** strings are built from the totals at `finish`. The out-of-core regex swap (`_validate_batch.py:242-255`) goes away. The wording does not change.
6. CLI: a `Checks` fact on the run card and a `validation` member in `decoy run --json` (S4).

## 5. Design notes

- **One fold per validator, one session per run.** Each validator module exports a fold class with `add(span: RowSpan)` and `finish() -> tuple[ValidatorFinding, ...]`. `RowSpan` is a frozen dataclass: row offset, output batch, source batch or `None`. The old function name stays as the registry entry point (open the fold, add one span, finish), so the registry signature and existing imports keep working. There is no second copy of any verdict rule.
- **The session is the only caller of folds.** `ValidationSession` (`validators/_session.py`, exported from `decoy_engine.validators`) is opened once in `run_pipeline` from the config and stored on the pipeline context. Routes receive it and call `observe`, `tap`, `observe_masked` or `observe_published`. `finish(quality_metrics, published_rows=...)` writes the one result and raises. `validate()` is open, one `observe` per table, then finish without the publish check.
- **Choke point for "every route validates".** `finish` compares the rows each scoped table published (from `StreamStats`, the sink receipt or the resident table) with the rows the session observed. A route that never calls the session fails closed with `validator_table_not_observed`. Guard test: V7. Mutation that must turn it red: delete the `tap` in the auto-chunk streamed path (M5).
- **Choke point for "validators never pick a route".** Every routing read of `validators` is deleted. A sentry (`tests/sentry/test_validators_do_not_route.py`) parses every module under `src/decoy_engine/execution/` and fails on any read of the `validators` config key or a `validators_requested` attribute, outside the one `ValidationSession.open` call in `run_pipeline`. The covered spellings are in section 8, class 5. Mutation: re-add the check at `:253` (M6).
- **Source alignment for `leak_check`.** `tap` wraps the source chunk iterator (before `_core.mask_chunked` reads it) and the masked chunk iterator (before `stream_table`). Each source chunk is projected to the `leak_check` columns and queued; each masked chunk pops one. `mask_chunked` yields one output per input chunk, in order, so the queue depth stays at 1. Depth over 2, or a row-count mismatch, is refused. The tap sits before `stream_table` because the sink re-cuts chunks into row groups of up to `ROW_GROUP_ROWS` (`_chunked_output_sink.py:68`); a tap after it would hold a whole row group of source.
- **Key-state budget.** 25% of `detected_memory_bytes()`, the planning fraction generation uses. An undetectable host skips the check, as `_refuse_if_over_memory` does. The estimate before the parent's first batch: parent row count (known for file sources and generated tables) times the key's fixed width, or its Parquet byte statistics for strings. The backstop measures the live map each batch.
- **Principles.** Single responsibility: verdict rules stay in each validator module; bookkeeping, order and budget live in the session; routing knows nothing about validators. The change pain removed: eight copies of one decline, and a second validator engine for out-of-core. Open/closed for validators: a new validator adds a fold and a shape, no route edit.
- **One place per fact.** Shape: the registry entry. Cap: `FINDING_INDEX_CAP` in `validators/_types.py`. `leak_check` skip reasons: `plan_scope` in `validators/_scope.py`, which the CLI also calls for `decoy validate`. Report: `ValidationSession.finish`.
- **House style.** Typed `RowSpan`, no loose argument lists. No flag arguments: `observe_masked` and `observe_published` are two named entry points over one core.

## 6. Slices and size

- **S1 FOLDS (engine; no route change; shape changes 2 to 5).** Folds in the existing modules: `_catalog.py` 196 to about 230, `_generic.py` 163 to about 190, `_leak_check.py` 317 to about 360, `_fk_validators.py` 303 to about 330, `_relationship_checks.py` 343 to about 380. New `validators/_session.py` (about 220) and `validators/_scope.py` (about 80). `validators/_types.py` 104 to about 150 (`failing_row_count`, `ValidatorResult`, `SkippedColumn`, `RowSpan`, `FINDING_INDEX_CAP`). `_registry.py` 138 to about 120 (shape on each entry; `validate` over the session). `_pipeline_finalize.py` reads the session report (about +10, -8). `out_of_core/_validate_batch.py` 317 to about 150 (collector replaced by the session; allowlists stay until S3). New public names, exported from `decoy_engine.validators`: `ValidationSession`, `ValidatorResult`, `SkippedColumn`, `plan_scope`, `FINDING_INDEX_CAP`. Tests V1, V2, V3, V10 (engine half), V13.
- **S2 RESIDENT-ROUTES (engine; route change 1 for resident routes).** Delete the decline at `_unified_slice_admission.py:253` (quarantine and post-scan stay), at `_shadow_full_frame.py:387-389`, `_shadow_mixed.py:342-345`, `_shadow_generation.py:414-417` and `_pipeline_routing.py:144-145`, and the `validators` parameter of `_sequential_eligible`. The sequential route feeds the session per table. The session opens in `run_pipeline` (`_pipeline_context.py`, about +12). The builder checks each remaining `validators=` forward (`_pipeline_context.py:409`, `:524`, `:592`, `_job_estimate.py:172`, `capacity.py:375`, `:437`, `pipeline/_lazy_input.py:150`, `physical/_snapshot.py:144`, `physical/_compiler.py:92`, `:175`, `_unified_slice.py:202`) and deletes each one whose only reader was a decline. About -60, +50 across about 12 files. Tests V4 (resident rows), V8 (sequential), V9.
- **S3 STREAMED-ROUTES (engine; route change 1 for streamed routes; tombstones).** `decide_output_mode` loses its validator line (`_chunked_output_sink.py:114-115`). `tap` in `_pipeline_auto_chunk.py` (about +15) and in the multi-table split (`_pipeline_multi_table.py:150` deleted, tap per table, about +10). Out-of-core: `validators_ooc_ready` and `validators_ooc_safe` deleted (`_pipeline_routing.py:338-345`, `_pipeline_routing_signals.py:547`, `:598`); `_validate_batch.py` deleted, and its three hook sites call the session. Generation sink: `observe` in the `generate` callback and `finish` before `publish.commit()` (`generation/_streamed.py:525-527`, about +6). Key-state budget, the four runtime codes, the tombstones. About +120, -260. Tests V4 (streamed rows), V5, V6, V7, V8 (out-of-core), V14.
- **S4 EXPECT-REPORT (engine-plus-CLI).** Engine: the `leak_check_column_not_checked` `QualityWarning` from `finish` for a skipped column that `columns:` names (about +15); rows in `docs/qa/14-casting-validators-quarantine.md` and `docs/qa/15-execution-routes-native.md`; the paragraph at `docs/strategies.md:2343`; the compatibility contract entry. CLI, after the engine pin: a `Checks` fact and a `validation` member in `--json` in `CLI:src/decoy/cli/run/_render.py` (about +30), with one line per failed or skipped check under the card; the failure path (`CLI:src/decoy/cli/run/_errors.py`) puts the same member in the error payload; `decoy validate` warns when `expect leak_check` names a `keep` column, through the engine's `plan_scope` (`CLI:src/decoy/cli/validate.py`, about +15); `CLI:tests/fixtures/release_freeze/json-shapes.json`; the expect section of `CLI:docs/guides/decoy-language/`. Tests V10 (CLI half), V11, V12.

Order: S1; then S2; then S3 (it needs S2's session wiring); then S4. S4's CLI half waits for an engine release with S1 to S3. Every slice's consumer is named: the session (S1) is called by finalize in S1 itself; `tap` and `observe_masked` (S1) are called in S3, before the row closes.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_session.py` | `src/decoy_engine/validators/` | "Job-level validator framework (validators: config block)": `src/decoy_engine/validators/` (8 modules, far under the fan-out cap) | `_registry.py` |
| `_scope.py` | `src/decoy_engine/validators/` | same | `_leak_check.py` |
| `_retired.py` (only if absent) | `src/decoy_engine/reasons/runtime/` | "Reason codes" | `_part3.py` |
| `test_validators_do_not_route.py` | `tests/sentry/` | sentry tests | the route sentries |
| engine tests | `tests/unit/validators/`, `tests/unit/execution/` (route matrix), `tests/physical/` (driver rows) | engine test layout | `test_catalog.py`, `test_leak_check.py` |
| CLI tests | `CLI:tests/unit/cli/run/` | CLI test layout | the render tests |

`execution/` (frozen at 104) gets no module; `out_of_core/` loses one (`_validate_batch.py`).

## 8. Recurring defect classes (`catalogs/recurring-defects.md`)

| # | Class | Applies | How this plan closes it |
|---|---|---|---|
| 1 | Anchored validation | no new validation of a string | N/A: `regex_match` keeps the user's pattern semantics; nothing new is matched |
| 2 | Strict wire and stored types | `ValidatorResult.status`, skip `code`, `failing_row_count`; the CLI `--json` reader | `status` is a `Literal`, `code` a registry member, the count a strict int; V11 feeds a bool count, a numeric-string count and a free-text status, all refused by the CLI reader |
| 3 | No exception context | `ValidatorStateError`; `ValidatorFailedError` from `finish` | raised after the `except` block closes; V7 and V8 assert `__cause__ is None and __context__ is None` |
| 4 | Versioned read models | `quality_metrics["validation"]` read by the CLI | additive members under the existing key; the CLI reader is derived from one writer model; V11 has cells for an unknown extra field (tolerated) and a missing `status` (refused) |
| 5 | Normalized guard scanners | `test_validators_do_not_route.py` | covered shapes, each with a seeded failing case: `config.get("validators")`, `config["validators"]`, `ctx.config.get("validators")`, `cfg.get('validators', [])`, a key held in a module-level name and passed to `get`, `getattr(x, "validators_requested")`, attribute `.validators_requested`. Deliberate evasion is V2-LOG |
| 6 | No reaching into private modules | `execution/` and the CLI use the session and report types | both import the public names from `decoy_engine.validators`; the existing private import at `_pipeline_finalize.py:390` moves to the public name |
| 7 | No hidden CI failures | new sentry and route matrix | plain pytest; no `|| true`, no report-only flag |
| 8 | One input, one trust class per entry point | `observe_masked`, `observe_published` | two named entry points over one core, no flag; table and column names come from the validated config, not a new user boundary |
| 9 | Mutations on the final head | every slice | each slice record lists the head its mutations ran on |
| 10 | Allowlisted helpers are still checked | the sentry allows one call site | the allowlist holds the exact `(path, function)` of the `ValidationSession.open` call; any second site fails |
| 11 | No raised caps | `execution/` fan-out (104), module size (700) | no module added to `execution/`; one removed from `out_of_core/`; every touched module stays under 600 lines; no pin raised |

### Defect catalog classes (engine `DEFECT-CATALOG.md`, section 3)

| # | Class | Where it can enter | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | finding `detail`, skip records, warnings, `ValidatorStateError` messages | details built from counts and names at `finish`; skip codes are registry members; errors name table and column only | V13 | put the first failing cell in `detail` (V13 red) |
| 2 | Cleanup missing on an exit path | validator failure or session refusal on a streamed route | `finish` raises before `commit()`; `OutputPublish` aborts staging on exit | V4(c), V7 | M3 (V4(c) red) |
| 3 | State and concurrency | per-run fold state, tap queue | one session per run on the pipeline context; no module-level state; tap queue depth checked | V2, V5 | M8 (V5 depth red) |
| 4 | Route parity and silent fallback | validators choosing a route; a route that skips the session | routing sentry; `finish` refuses `validator_table_not_observed` | V4(a), V7, V9 | M5, M6 |
| 5 | Referential integrity | `keyed` validators on bounded routes | parent-first order checked by the session; key map built from the parent's published rows | V8 | M9 (V8 red) |
| 6 | Untrusted producer | validator params (regex, `allowed_values`) | unchanged validation at session open, before any read | V1 (control) | N/A: no new parsing of user input; existing open-time checks move unchanged |
| 7 | Check then use | `leak_check` pairs a source chunk with its masked chunk | pairing and row count checked on each pop, refusal `validator_chunk_pairing_mismatch` | V5 | M4 (V5 red) |
| 8 | Weak tests | chunk sizes where folding and one call coincide | Hypothesis chunk sizes including 1, 7, 4096 and whole table; 25,000 failures to pass the cap | V2, V3 | M1 (V2 red), M2 (V3 red) |
| 9 | Refactor drift | moving every validator to the fold form | V1 parity against `70881ad79` findings for all 11 validators | V1 | change one fold's index shift (V1 and V2 red) |
| 10 | Frozen contract drift | `ValidationReport`, `ValidatorFinding`, `--json` | `Breaking:` lines, compatibility contract entry, CLI shape snapshot | V11, V14 | drop `failing_row_count` from the writer (V11 red) |

## 9. Acceptance tests (each fails before its slice unless marked as a control)

S1:

- **V1 verdict parity (control, passes before and after).** For each of the 11 validators, one fixture that fails on fewer than 10,000 rows: `validate()` gives the same `findings` (validator, table, column, indices, detail) as at `70881ad79`, captured inside the test.
- **V2 chunk invariance (property test, Hypothesis, fixed seed).** The session fed at generated chunk sizes, including 1, 7, 4096 and the whole table, gives one report (ignoring `elapsed_ms`) for every validator, including `leak_check` with a source and the three `keyed` validators parent first. Fail-before: `leak_check` and the keyed validators have no per-chunk form (out-of-core refuses them).
- **V3 cap.** A `regex_match` with 25,000 failing rows: `failing_row_count == 25000` and `failing_row_indices` is the first 10,000 failures; the same config with quarantine `validation_fail` lists all 25,000. Fail-before: no count field.
- **V10 skip record (engine).** `email: passthrough` and `leak_check` with `columns: {customers: [email]}`: the result has `status == "skipped"` and `skipped == (("customers", "email", "leak_check_skip_passthrough"),)`; one `QualityWarning` `leak_check_column_not_checked`; the run passes. With the default scope (no `columns:`) the skip is recorded and no warning is raised. Fail-before: nothing recorded, no warning.
- **V13 value-free.** A source with a marker value in every validated column, every validator failing: the marker is in no finding detail, result, warning, log line or exception message.

S2 and S3:

- **V4 route matrix.** For each route in section 4 (unified 2k rows `hash`; auto-chunk resident 120k; auto-chunk streamed with a `ParquetTransactionalSink` 120k; full frame forced by `post_validation`; physical full-frame driver; sequential FK; out-of-core FK; multi-table split; generation with a sink): (a) route label, route reason and per-column backends equal those of the same config without validators; (b) with a passing validator, `quality_metrics["validation"]` has every result `passed`; (c) with a failing validator, the run raises `ValidatorFailedError`, `sink.commit` is never called, and the staging directory is empty. Fail-before: (a) fails on every route except full frame.
- **V5 paired, streamed.** 120k rows with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`: fails on the auto-chunk streamed route with the full-frame report. With `hash` the check passes. The tap's queue depth never exceeds 1 (instrumented counter). Fail-before: the route is resident.
- **V6 bounded memory (performance gate, vm-run on the Dell node).** 2M rows streamed, `leak_check` and `regex_match`, every row failing: `ValidationSession.retained_bytes()` stays under `2 * FINDING_INDEX_CAP * 8` bytes plus 64 KiB plus one source chunk projection; peak RSS is within 64 MiB of the same run without validators. Recorded in the slice record. Fail-before: the run is resident.
- **V7 not-observed guard.** With the auto-chunk tap removed through a test seam, the streamed run refuses with `validator_table_not_observed`, commits nothing, and the error has no exception context. Fail-before: n/a (new guard); its proof is mutation M5.
- **V8 keyed on bounded routes.** `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on the sequential and out-of-core routes give the full-frame report, for single, composite, nullable, two-parent and self-reference FKs (a self-reference child row before its parent row is a pass, an orphan is a finding). A child-first feed (unit test on the session) refuses with `validator_parent_not_observed`. A key-state budget forced to 1 KiB refuses with `validator_key_state_over_budget` before the parent's first write, nothing committed. Fail-before: both routes decline.
- **V9 routing sentry.** Passes on the tree; fails on each seeded spelling in class 5.
- **V14 tombstones.** `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as deprecated; nothing in `src/` emits them (registry sentry).

S4:

- **V11 card and JSON.** CLI: a passing run with `expect luhn(...)` and `expect leak_check(...)` shows `Checks  2 passed`; a failing run (exit 3) shows `Checks  1 failed: leak_check customers.email`; `--json` carries `validation: {passed, results: [...]}` on success and on failure; the shape snapshot is updated; the reader refuses a bool or numeric-string `failing_row_count` and a free-text `status`, and tolerates an unknown extra field. Fail-before: no fact, no member.
- **V12 validate warning.** `keep email` plus `expect leak_check(customers.email)`: `decoy validate` exits 0 and prints one warning naming `customers.email` and the reason (the column is kept). Fail-before: silent.

## 10. Named mutations (each must turn the named test red on the final head)

- **M1** the session forgets the per-table offset (indices stay chunk-relative): V2 red at chunk 7.
- **M2** the cap also applies under quarantine `validation_fail`: V3 red.
- **M3** `finish` moved after `publish.commit()` on the streamed route: V4(c) red (commit called).
- **M4** `tap` pairs each masked chunk with itself instead of the source: V5 red (the `hash` column reads as unchanged).
- **M5** the auto-chunk `tap` deleted: V7 and the V4 streamed row red.
- **M6** `config.get("validators")` re-added to `cheap_admission`: the V4 unified row and V9 red.
- **M7** `leak_check` skips a passthrough column without recording it: V10 red.
- **M8** tap queue unbounded (no depth check): V5 depth assertion red.
- **M9** keyed fold accepts a child before its parent: V8 order cell red.

## 11. Frozen contracts and compatibility

- `ValidationReport` and `ValidatorFinding` are public (`decoy_engine.validators`) and serialized into evidence. The new fields are additive; the index cap changes a frozen field's behavior. Both go on the changelog `Breaking:` line, in `docs/compatibility-contract.md` (validators entry) and in `docs/strategies.md:2343`.
- `quality_metrics["validation"]` keeps its key and its `validators` member.
- Route changes for validator-bearing jobs (change 1): `Breaking:` line, pointing at `tests/parity/SEMANTIC_DIFFERENCES.md`.
- CLI `--json` gains `validation`: additive; shape snapshot updated.
- Tests that assert a validator-bearing job's route, or `validators_present`, change in S2 and S3. The builder lists each in the PR body with "validators no longer route". Known groups: the out-of-core D3a admission tests (deleted with the allowlists), `tests/physical/` driver decline tests, and the decision rows of the chunked output sink tests.

## 12. Related plans

- `plan/per-column-routing` lists validators among the table-wide declines (its item 2). After this row validators are not a decline, so that list loses one word. Whichever merges second drops it.
- `plan/route-label-truth` registers decline codes in `reasons/route/`; this row tombstones `validators_present`. Both edit `reasons/route/__init__.py` and `_retired.py`: parallel ledger lines, keep both on merge.
- `plan/when-reads-source` creates a runtime `_retired.py` if absent; this plan uses the same file. Whichever lands first creates it.
- `plan/uf-domain` U7 runs "full frame with a validator" as its own case. After S2 that config takes the unified slice. U7's intent (same output schema with a validator on) holds, and it needs no edit.
- `plan/gen-stream-all` S1a moves the batch assembler to `generation/stream/_batches.py`. The S3 generation hook is in the `generate` callback in `_streamed.py`, outside the assembler, so the two do not touch the same lines.

## 13. Pre-mortem

- A route publishes through a path this plan did not list (for example a new sink adapter): `finish` refuses with `validator_table_not_observed`. A loud failure, not a silent skip.
- A user relies on the full index list for more than 10,000 failures: the count stays exact, and the changelog names quarantine as the way to get every row.
- A native route's output differs from pandas on a validated column (Unicode normalization on `hash`): the verdict follows the published bytes. The parity file already names the difference.
- `reconciliation_holds` on a very large parent: the budget refuses before any write. The message names the table and says to set `execution_mode: full_frame` or give the run more memory.
- Out-of-core starts rewriting a non-key column after the mask step: the paired fold would read stale values and the row-count guard would not notice. A unit test pins the rewrite pass's column list to incoming FK child columns only.

## 14. Open questions for the owner

1. `FINDING_INDEX_CAP` = 10,000 per finding with an exact count (recommended), or every index on resident routes only (evidence would then depend on the route; not recommended).
2. `leak_check` naming a `keep` column: warning and exit 0 (recommended, as the audit says), or a config error.
3. Key-state budget at 25% of detected memory (recommended, the generation figure), or all detected memory.
