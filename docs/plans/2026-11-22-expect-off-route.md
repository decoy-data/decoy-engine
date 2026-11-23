Status: plan (revision 2, 2026-11-22; Dennis round 1 applied)

# EXPECT-OFF-ROUTE: validators run on the route that was chosen, and the run card reports them

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap rows: EXPECT-OFF-ROUTE (engine, new) and EXPECT-REPORT (CLI, rank 7 in the V1 fast-path audit, folded in as slice S4). Source: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, section "Two earlier findings, checked", and the owner direction of 2026-11-22: every strategy runs its fastest path by default, each column runs its own path, faster and more robust wins even when output bytes change (every byte change is named here), output stays deterministic per seed, engine-gap deadline 2026-12-15. Four slices: three engine PRs and one engine-plus-CLI pair (S4).

Anchors: a path with no prefix is in this repository (decoy-engine); `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` `77da171f`. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, design notes, choke point, placement), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `performance.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `security.md`, `observability-and-resilience.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` (module size: aim 600, hard max 700), `CODEMAP.md` ("Where Things Go") and `.importlinter` (tier order). Related plans read: `plan/route-label-truth`, `plan/per-column-routing`, `plan/when-reads-source`, `plan/uf-domain`, `plan/gen-stream-all`, `plan/gen-per-column`, `plan/native-threads-default`, `plan/faker-default-pool` (engine), `plan/csv-write-fast` (CLI).

Risk: R2. The change moves a fail-closed privacy check (`leak_check`) and the other job-level validators onto every route. It changes the publish order on the streamed routes (validation must finish before commit), the evidence shape (`quality_metrics["validation"]`) and the CLI `--json` shape. No key material, no vault, no destructive operation. Plan review: Dennis, then Codex. Code gate: Codex and Dennis on every slice (fail-closed privacy path).

Revision 2 changes (Dennis round 1): every published batch now reaches the session through one sink proxy, so no route needs its own hook and no 600-line module grows (findings 1, 7); the out-of-core paired feed moves to `yield out` (1); plain callable sinks with validators stay resident as a named exception (2); keyed folds buffer child state for an unseen parent, so any table order works (3); `parent_window_respected` infers its date format once per table (4); the ninth site and every non-routing read are listed with a keep or delete decision (5); the key-state budget is injected by `run_pipeline` from the route's own budget (6); two more `leak_check` skip codes, `generate_tables_streamed` named out of scope, V13 marked as a control.

## 1. Frame

Evidence:

- Any `validators:` entry (the language's `expect` line) sends the table to pandas. The unified slice declines at `src/decoy_engine/execution/_unified_slice_admission.py:252-256` (`config.get("validators") or config.get("quarantine") or post_scan_model_setting(config) is not None`; this is the `:253` the audit cites).
- The same rule is copied at eight more sites. Each keeps a validator-bearing job off its fast or bounded route:
  1. `src/decoy_engine/execution/_chunked_output_sink.py:114-115`: `decide_output_mode` keeps an auto-chunk run resident (`VALIDATORS_PRESENT`).
  2. `src/decoy_engine/execution/_pipeline_routing.py:144-145`: `_sequential_eligible` refuses the bounded FK route.
  3. `src/decoy_engine/execution/_pipeline_routing.py:338-345`, with `src/decoy_engine/execution/_pipeline_routing_signals.py:547`, `:598` and `src/decoy_engine/execution/out_of_core/_validate_batch.py:73`, `:76`, `:144-177`: out-of-core admits only six per-cell validators, and only on `truncate`, `redact` and `passthrough` string columns (D3a).
  4. `src/decoy_engine/execution/_pipeline_multi_table.py:150`: the multi-table split.
  5. `src/decoy_engine/execution/_mixed_static.py:211-212`: the mixed route's static check (called from `src/decoy_engine/execution/_pipeline_mixed_route.py:302`).
  6. `src/decoy_engine/execution/physical/_shadow_full_frame.py:387-389`: the physical full-frame driver.
  7. `src/decoy_engine/execution/physical/_shadow_mixed.py:342-345`: the mixed generate-and-mask driver.
  8. `src/decoy_engine/execution/physical/_shadow_generation.py:414-417`: the generation driver.
- Validators run once, on the resident outputs, in `finalize_validators_and_quarantine` (`src/decoy_engine/execution/_pipeline_finalize.py:359-393`), which calls `validators._registry.validate` (`src/decoy_engine/validators/_registry.py:77-138`). The unified slice already calls the same finalize step on its resident output (`src/decoy_engine/execution/_unified_slice.py:316-322`). So the unified-slice decline guards nothing that the lane cannot do. The real gap is on the streamed and bounded routes, where no resident output exists.
- A per-batch validator collector already exists for out-of-core (`src/decoy_engine/execution/out_of_core/_validate_batch.py:194-270`, `ValidatorCollector`). It shifts batch-relative row indices to whole-table positions and keeps every failing position. Its docstring says that state is "O(failing rows) and unbounded in the worst case" (`:28-30`). Its hook sits before the FK join (`src/decoy_engine/execution/out_of_core/_rewrite_pass.py:233`, join at `:238`), so it never sees an orphan key the join nulls.
- Each validator reads whole columns with `to_pylist()` (for example `src/decoy_engine/validators/_catalog.py:66`, `src/decoy_engine/validators/_leak_check.py:281-282`, `src/decoy_engine/validators/_fk_validators.py:104`, `:134`). Each finding carries every failing row index (`src/decoy_engine/validators/_types.py:43`). A 10M-row `leak_check` that fails at the column tier stores 10M indices in `quality_metrics`.
- `parent_window_respected` parses dates with `pd.to_datetime(..., errors="coerce")` and no `format` (`src/decoy_engine/validators/_relationship_checks.py:142-143`, `:152`). pandas 2 infers the format from the first non-null value, so the same rows parse differently when split into chunks.
- Audit, checked on CLI main: a passing check is not reported. Neither the run card nor `decoy run --json` (`CLI:src/decoy/cli/run/_render.py:117-152`, `:159-176`) reads `quality_metrics["validation"]`.
- Audit: `keep email` plus `expect leak_check(customers.email)` exits 0 and never checks the column. `leak_check` skips the `passthrough` strategy (`src/decoy_engine/validators/_leak_check.py:79` `EXCLUDED`, applied at `:260-261`; the audit's `:87` names the same rule) and records nothing. It also skips silently below `min_rows` (`:283`) and for a table not in the outputs (`:226`).

What this costs the user: one `expect` line turns a native 2k-row hash job into a pandas job, and a 120k-row bounded streamed job into a resident one. The second is the NONFK-OOM risk that the auto-chunk lane exists to remove.

## 2. Established solutions

Search run (2026-11-22): Apache Beam `CombineFn`; Great Expectations validation results; AWS Deequ analyzers; dbt tests; Spark accumulators; streaming GROUP BY partial aggregation (DuckDB, Polars streaming); symmetric hash join; Spark `FileOutputCommitter`; the proxy pattern (Gamma et al., *Design Patterns*). In the codebase: `ValidatorCollector`, `OutputEvidenceAccumulator`, `_CallableSinkAdapter`.

- **Combine functions.** Beam's `CombineFn` (`create_accumulator`, `add_input`, `merge_accumulators`, `extract_output`) is the standard form for a check that sees elements one at a time and gives one result. Each validator becomes one fold of this form. The resident route calls it with one span; the streamed routes call it once per batch. Merge is not needed: every route delivers a table's rows in order, on one thread.
- **Exact count, capped sample.** Deequ computes checks from analyzer states that combine across partitions. Great Expectations reports `unexpected_count` (exact) beside `partial_unexpected_index_list` (a capped sample). This plan follows that split: the count is exact and the index list is a capped prefix.
- **Two-sided key checks in any order.** A symmetric hash join (Wilschut and Apers 1991) keeps state for both inputs and matches whichever side arrives second, so neither table must come first. The keyed folds follow it: parent keys go in a key map, child rows whose parent has not arrived go in a pending map, and each side probes the other. Both maps are reserved against one budget.
- **Validate before commit.** Spark's `FileOutputCommitter` and Decoy's `OutputPublish` (`src/decoy_engine/execution/_chunked_output_sink.py:120-171`) stage output and make it visible once, at the end. A check that finishes inside `commit()` and raises on failure gives "nothing published" by construction: `OutputPublish.__exit__` aborts the staged output when commit raises (`:168-171`).
- **Proxy at the publish boundary.** A proxy that forwards every call to the real sink and observes each batch on the way puts the check on the one path all published bytes take, with no edit at each route.

Custom code still needed: the fold form of each of the 11 validators, one session that owns them, and the sink proxy. No library computes Decoy's validator verdicts. The folds reuse the verdict code that exists today.

### Reuse inventory

- `src/decoy_engine/validators/_registry.py` `_REGISTRY` and `validate`: the one name-to-validator map and the public entry point. Both stay; `validate` becomes a one-span session.
- `src/decoy_engine/execution/out_of_core/_validate_batch.py` `ValidatorCollector` (`:194-270`): the offset shift and the configured-order re-emit move into the session; the module is deleted in S3.
- `src/decoy_engine/execution/_chunked_output_sink.py` `OutputPublish` (commit once, abort on exit) and `OutputEvidenceAccumulator` (fold per chunk, O(columns) state): the commit point and the state pattern.
- `src/decoy_engine/execution/_transactional_sink.py` `TransactionalSink` protocol (`:75-111`) and `_CallableSinkAdapter` (`:114-165`): the methods the proxy forwards, and the callable form it must keep.
- `src/decoy_engine/execution/_pipeline_finalize.py:359-470` `finalize_validators_and_quarantine`: the D8 quarantine and row-error logic stays, and reads the session's report.
- `src/decoy_engine/validators/_leak_check.py` `TRANSFORMATIVE`, `SHAPE_PRESERVING`, `EXCLUDED`, `_is_identical`, `_fk_child_columns`: classification unchanged; the skip reasons are recorded, none is added.
- `src/decoy_engine/reasons/route/_retired.py:14-19`: the tombstone pattern for `validators_present` (`reasons/route/_part1.py:286`) and `out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`).
- `src/decoy_engine/reasons/warning/_part1.py:45` `_d = _catalog.warning("QualityWarning")`: the registration form for the skip codes and warning.
- The route's own memory budget: `resolve_budget` (`src/decoy_engine/execution/out_of_core/_budget.py:363`, used by admission at `src/decoy_engine/execution/_transforms_admission.py:264`), the out-of-core carve for non-DuckDB state (`src/decoy_engine/execution/out_of_core/_runner.py:213-221`), and `GenerationBudgetLedger.reserve` (`src/decoy_engine/generation/_budget_ledger.py:107`). The session receives a figure from these; it computes none.
- `pandas.tseries.api.guess_datetime_format`: the same guess `to_datetime` makes from the first value, called once per table.
- CLI: `CLI:src/decoy/cli/run/_render.py` facts and `--json` payload; the shape snapshot `CLI:tests/fixtures/release_freeze/json-shapes.json`.

## 3. Guarantee and non-goals

After this row:

1. A `validators:` block never changes the route, with two named exceptions. A job with validators takes the route the same job takes without them: unified slice, auto-chunk (resident and streamed), full frame, mixed route, physical full-frame, mixed and generation drivers, sequential FK, out-of-core FK, multi-table split, and generation with a sink. The exceptions: (a) quarantine with the `validation_fail` trigger removes rows, so it stays resident (code `quarantine_enabled`, unchanged); (b) a plain callable sink (not a `TransactionalSink`) cannot take back a written table, so a job with validators and a callable sink takes a resident route, which validates before the first write (new route code `validators_need_transactional_sink`).
2. Every configured validator runs on the bytes the route publishes. It reads the output, the source, or both, as its shape says (section 4).
3. On the streamed and bounded routes, validator state is bounded: per finding at most `FINDING_INDEX_CAP` row indices plus counters; for `leak_check` at most one source batch per table in flight; for a keyed check one key map and one pending map, reserved against the route's budget, with a coded refusal when they would not fit.
4. A failing validator fails the job (`ValidatorFailedError`, CLI exit 3) and nothing is published. On a sink route the session finishes inside the sink's `commit()`, before the inner commit, and the failure aborts the staged output. On a resident route it finishes before any write.
5. `quality_metrics["validation"]` is the one result. One function (`ValidationSession.finish`) builds it, on every route; `run_pipeline` stores it. The report is a function of (config, published bytes): the same at any chunk size, in any table order, and on any route that publishes the same bytes.
6. The run card and `decoy run --json` show every configured check with its result (passed, failed or skipped), including passes (S4).
7. `leak_check` records each column and table it does not check, with a registered code. A column named in `columns:` that it skips raises a `QualityWarning` and shows on the run card (S4). The run still exits 0, as the audit asks.

Non-goals: quarantine on the streamed routes (row removal after a streamed write needs its own design); new validator kinds; any verdict rule change (thresholds, `TRANSFORMATIVE` classes); `post_validation` and `fidelity_report` routing (separate rows); `decoy validate` running validators on data; `generate_tables_streamed` (`src/decoy_engine/generation/_plan_entry.py:290`), the generation-only entry that takes no `validators:` block and does not go through `run_pipeline`.

## 4. Enumerations

### Validator shapes (one per registry entry)

| Shape | Reads | Validators | State on a bounded route |
|---|---|---|---|
| `cell` | published output, row by row | `luhn`, `npi`, `iban`, `vin`, `regex_match`, `column_in_set`, `no_orphan_children` | per finding: count plus first `FINDING_INDEX_CAP` indices |
| `paired` | published output plus the source, aligned by row | `leak_check` | per column: compared and identical counts, first `FINDING_INDEX_CAP` identical indices; at most one source batch per table in flight |
| `keyed` | two published tables, in either order | `fk_intact`, `parent_window_respected`, `reconciliation_holds` | a key map (parent key set; key to window; or key to parent row and value), a pending map for child rows whose parent has not arrived, and per-key child sums for `reconciliation_holds`; all reserved against the key-state budget |

`no_orphan_children` is `cell`: it flags null FK cells on child rows (`src/decoy_engine/validators/_fk_validators.py:244-249`) and reads no parent. A test fails if a name in `_REGISTRY` has no shape.

### FK shapes (for the `keyed` validators and `no_orphan_children`)

| FK shape | Today (resident) | Bounded route after S3 |
|---|---|---|
| Single-column FK | parent key set, child probe (`_fk_validators.py:72-113`) | key map from the parent's published batches; a child row probes it if the parent has arrived, else goes in the pending map, probed when the parent table finishes |
| Composite FK | key tuples in column order (`_fk_validators.py:79-81`) | same tuples; key width estimate sums the columns |
| Nullable FK (all FK columns null) | not a break for `fk_intact`; a finding for `no_orphan_children` | unchanged; null check is per cell |
| Orphan key the out-of-core join nulls | not seen (hook before the join, `_rewrite_pass.py:233`) | seen: the proxy observes the joined batch, so the nulled key is a `no_orphan_children` finding and not an `fk_intact` break, as on full frame |
| Several parents for one child | one edge per relationship entry | one key map and one pending map per parent edge, each reserved |
| Self-reference (parent table is the child table) | one table, both sides resident | same pending map: a child row before its parent row waits and is probed at table end |
| Parent written after its child (GEN-PER-COLUMN S4 deferred parents) | n/a (resident) | pending map holds the child's keys (`fk_intact`), keys and parsed dates (`parent_window_respected`) or per-key sums (`reconciliation_holds`, order-free already) until the parent table finishes |
| Cross-table FK cycle | auto full-frame fallback (cycles stay V2) | unchanged: the run is resident, so the fold gets one span per table |

### Fields

| Type | Field | Kind | Meaning |
|---|---|---|---|
| `ValidatorFinding` | `failing_row_count` | new, `int` | exact count of failing rows |
| `ValidatorFinding` | `failing_row_indices` | changed | first `FINDING_INDEX_CAP` failing positions in row order; all of them under quarantine `validation_fail` |
| `ValidationReport` | `results` | new, `tuple[ValidatorResult, ...]` | one per configured entry, in config order |
| `ValidationReport` | `elapsed_ms` | changed | summed fold time over the run |
| `ValidatorResult` | `validator`, `entry_index`, `status`, `checked`, `skipped`, `failing_row_count` | new type | `status` is `Literal["passed", "failed", "skipped"]`; `checked` is (table, column) pairs |
| `SkippedColumn` | `table`, `column`, `code` | new type | `code` is a registered skip code; `column` is `None` for a whole-table skip |
| `RowSpan` | `offset`, `output`, `source` | new, internal to the session API | one span of rows fed to a fold |

### Exit paths

1. All validators pass: the report is built; the run goes on to commit (sink) or returns (resident).
2. A validator fails and quarantine does not cover it: `finish` raises `ValidatorFailedError(report)`. On a sink route this happens inside the proxy's `commit()`, which calls the inner sink's `abort()` before raising, so nothing is published. CLI exit 3.
3. A validator fails and quarantine `validation_fail` is configured: resident route only (the D8 path, `_pipeline_finalize.py:410-470`, unchanged).
4. Parameter error (bad regex, missing `allowed_values`, unknown validator, `leak_check` naming a generate table): raised when the session opens, before any source read, as today (out-of-core does this at `_validate_batch.py:203-205`).
5. `leak_check` with no source for a table in scope: `ValueError` as today (`_leak_check.py:236-241`), raised at open.
6. New refusals. Each is a `ValidatorStateError` (a `DecoyError`) with a registered runtime code, raised after any `except` block closes:
   - `validator_key_state_over_budget`: the key map plus pending map estimate exceeds the key-state budget. Checked before the first scoped batch is written, and again as the maps grow.
   - `validator_source_pairing_mismatch`: the source rows read for a `paired` fold differ in count from the published rows of that table.
   - `validator_table_not_observed`: at commit, or before a resident route returns, a table in a validator's scope published rows the session did not observe (counts differ), or the session never finished. This is the construction guard for guarantee 2.

### Routes and what each one feeds the session

`run_pipeline` (`src/decoy_engine/execution/_pipeline.py:116`) opens the session and wraps the caller's sink once, before routing (`ValidatingSink`, section 5). Every sink route then publishes through the proxy, so the feed column below has two values only: `finalize` (resident) or `proxy`.

| Route | Today | After | Feed |
|---|---|---|---|
| Unified slice | declined (`_unified_slice_admission.py:253`) | admitted | finalize (`_unified_slice.py:316-322`) |
| Full frame (pandas oracle) | runs validators | same | finalize |
| Mixed route | declined (`_mixed_static.py:211-212`) | admitted | proxy when it streams to a sink, else finalize |
| Physical full-frame, mixed, generation drivers | declined (`_shadow_full_frame.py:387`, `_shadow_mixed.py:342`, `_shadow_generation.py:414`) | admitted | finalize |
| Auto-chunk, resident | runs validators on the joined output | same, through the session | finalize |
| Auto-chunk, streamed to a sink | declined (`_chunked_output_sink.py:114`) | admitted | proxy; `paired` source from the source reader |
| Multi-table split | declined (`_pipeline_multi_table.py:150`) | admitted | proxy per dispatched table |
| Sequential FK, transactional sink | declined (`_pipeline_routing.py:144-145`) | admitted | proxy |
| Sequential FK, no sink | declined | admitted | finalize on the returned outputs |
| Any route, plain callable sink | resident (validators decline) | resident (exception 1b, `validators_need_transactional_sink`) | finalize, then the proxy verifies counts |
| Out-of-core FK | six validators on three strategies (D3a) | all validators | proxy for `cell` and `keyed`; `paired` from `observe_pair(table, raw_batch, out)` at `yield out` (`_rewrite_pass.py:240`, the line moved from `:233`) |
| Generation with a sink | declined (`decide_output_mode`, called at `_pipeline_generate_mask.py:184`) | admitted | proxy (no source) |
| Quarantine `validation_fail` | resident | resident (exception 1a) | finalize |

On a resident route that also writes to a sink, finalize finishes the session first; the proxy then only counts rows and checks them against what finalize observed.

The source for a `paired` fold on a proxy route comes from a source reader `run_pipeline` builds from the caller's `sources`: a resident `pa.Table` is sliced at the published offset (no copy); a lazy source is read a second time, scoped columns only, one batch at a time. Out-of-core already holds `raw_batch` at `yield out`, so it feeds pairs itself. `leak_check` never checks FK child columns (`_leak_check.py:242-243`), the only columns the join rewrites, so `out` at `yield out` carries the published values of every column it checks.

### Codes

- New runtime codes (`reasons/runtime/_part3.py`, declarer `_catalog.runtime("ValidatorStateError")`): `validator_key_state_over_budget`, `validator_source_pairing_mismatch`, `validator_table_not_observed`.
- New route code (`reasons/route/_part1.py`, beside `quarantine_enabled`): `validators_need_transactional_sink`.
- New warning code (`reasons/warning/_part1.py`): `leak_check_column_not_checked`.
- Skip codes on a `leak_check` result, one per existing exclusion (same warning catalog): `leak_check_skip_passthrough`, `leak_check_skip_fk_child`, `leak_check_skip_when`, `leak_check_skip_exempt`, `leak_check_skip_missing_column`, `leak_check_skip_below_min_rows` (also zero compared, `_leak_check.py:283`), `leak_check_skip_table_not_produced` (`:226`).
- Tombstoned in `reasons/route/_retired.py` (`deprecated_in` = the release that carries S3, no `replaced_by`): `route.validators_present`. Tombstoned in a runtime `_retired.py` (created beside `_part3.py` if absent, as `plan/when-reads-source` does): `runtime.out_of_core_validators_not_admitted`. The alias `ROUTE_VALIDATORS_PRESENT` (`physical/_reasons.py:56`, `:101`, `:343`) is deleted.

### Every read of `validators` under `execution/`, with its decision

| Site | What it does | Decision |
|---|---|---|
| `_pipeline.py` `run_pipeline` (new) | opens the session | keep: the one allowlisted read |
| `_pipeline_routing.py` sequential eligibility (new call) | asks `session.needs_resident(sink)` for exception 1b | keep: the one allowlisted routing call |
| `_unified_slice_admission.py:253`, `_chunked_output_sink.py:114`, `_pipeline_routing.py:144`, `:338-349`, `:432`, `_pipeline_routing_signals.py:508`, `:547`, `:576`, `:598`, `_pipeline_multi_table.py:150`, `_mixed_static.py:105`, `:125`, `:195`, `:211-212`, `physical/_shadow_full_frame.py:387-389`, `physical/_shadow_mixed.py:342-345`, `physical/_shadow_generation.py:414-417` | route declines and their parameters | delete |
| `_pipeline_routing.py:101`, `:189`, `:206`, `:279`, `:300`, `:311`, `:330`; `capacity.py:375`, `:437`; `_job_estimate.py:172`; `_pipeline_context.py:409`, `:524`, `:592`; `_transforms_admission.py:72`, `:96`; `_transforms_prepare.py:51`, `:70`; `pipeline/_lazy_input.py:150`; `physical/_compiler.py:92`, `:175`; `physical/_live_inputs.py:59`, `:163` | forward the list to a decline | delete |
| `physical/_snapshot.py:144`, `:196`, `:272`; `physical/_inputs.py:211`, `:333`; `_unified_slice.py:202`; `physical/_shadow_context.py:180`, `:241` | carry the list into the plan snapshot, its hash and the shadow context | delete: validators no longer change the plan, so they leave its hash (a plan hash change, section 11) |
| `_pipeline_finalize.py:387-393` | runs validators on resident outputs | replace: finalize feeds the session (`observe` per table, then `finish`) |
| `out_of_core/_runner.py:208`, `:297`, `:334`; `out_of_core/_rewrite_pass.py:233`; `out_of_core/_stream_driver.py:154`, `:374`; `out_of_core/_validate_batch.py` | the out-of-core collector | replace: `observe_pair` at `_rewrite_pass.py:240` (FK pass, after the join) and in place at `_stream_driver.py:374` (no join on that path, so the masked batch is the published batch); the rest deleted with the module |

### Output surfaces (byte and shape changes; each on a changelog `Breaking:` line)

1. **Route.** A job with validators runs the route it runs without them, so its output bytes are that route's bytes. The differences between routes are the ones already listed in `tests/parity/SEMANTIC_DIFFERENCES.md` (for example `hash` and `categorical` Unicode normalization on the native kernels). A validator now judges the bytes that are published.
2. **`ValidatorFinding`** gains `failing_row_count: int` (exact). `failing_row_indices` holds the first `FINDING_INDEX_CAP` = 10,000 failing positions in row order. When quarantine with `validation_fail` is configured, the list is complete, because quarantine removes those rows. The cap depends on the config, never on the route.
3. **`ValidationReport`** gains `results: tuple[ValidatorResult, ...]`, one per configured entry, in order. `findings`, `passed` and `validators_run` keep their meaning.
4. **`elapsed_ms`** is the summed fold time across the run (it was the time of one call).
5. **`detail`** strings are built from the totals at `finish`. The out-of-core regex swap (`_validate_batch.py:242-255`) goes away. The wording does not change.
6. **`parent_window_respected`** parses with one format per table column (section 5). For a column whose values all match the first value's format, verdicts are unchanged. For a column with mixed formats, values that do not match the first value's format now parse as `NaT` on every route (they already did on full frame, where the first value set the format for the whole column), so a mixed-format column gives the full-frame verdict at any chunk size.
7. **Plan hash.** The physical plan hash no longer includes the validator count (`physical/_inputs.py:333`).
8. CLI: a `Checks` fact on the run card and a `validation` member in `decoy run --json` (S4).

## 5. Design notes

- **One fold per validator, one session per run.** Each validator module exports a fold class with `add(span: RowSpan)` and `finish() -> tuple[ValidatorFinding, ...]`. `RowSpan` is a frozen dataclass: row offset, output batch, source batch or `None`. The old function name stays as the registry entry point (open the fold, add one span, finish), so the registry signature and existing imports keep working. There is no second copy of any verdict rule.
- **The session is the only caller of folds.** `ValidationSession` (`validators/_session.py`, exported from `decoy_engine.validators`) is opened once in `run_pipeline` with the config, the source reader and the key-state budget, and stored on the run context. Entry points: `observe(table, output, source)` (finalize, one span per table), `observe_published(table, batch)` (the proxy), `observe_pair(table, source, output)` (out-of-core), `finish() -> ValidationReport`, and `needs_resident(sink) -> bool` (exception 1b). `validate()` is open, one `observe` per table, then `finish`.
- **Choke point for "every published byte is validated": the sink proxy.** `ValidatingSink` (`validators/_sink.py`) wraps the caller's sink once, in `run_pipeline`, before any routing reads the sink. It forwards every attribute to the inner sink (`__getattr__`), so `isinstance(sink, TransactionalSink)`, `bounded_write_batches` and the sink's own helpers answer as before. It overrides three calls: `write(table, data)` and `write_batches(table, batches, schema=...)` pass each batch to `observe_published` and forward it; `commit()` calls `session.finish()` (and the published-equals-observed check), calls the inner `abort()` and re-raises if that fails, and only then calls the inner `commit()`. A plain callable sink gets `ValidatingCallable`, a callable with the same check. The proxy imports only `pyarrow`, so it sits in the `validators` tier and the import contract holds. Guard test: V7. Mutation: route a sink write around the proxy (M5).
- **Choke point for "validators never pick a route".** Every routing read is deleted (section 4 table). A sentry (`tests/sentry/test_validators_do_not_route.py`) walks the AST of every module under `src/decoy_engine/execution/` and fails on: any subscript or `.get` of the `validators` key; any name, parameter or attribute spelled `validators`, `validators_requested`, `config_validators`, `validators_config` or `validators_ooc_*`, including truthiness tests (`if validators:`, `bool(validators)`, `not validators`, `len(validators)`); any import of `decoy_engine.validators` other than the public names. The allowlist holds exactly two `(path, function)` pairs: the `ValidationSession.open` call in `run_pipeline` and the `session.needs_resident` call in sequential eligibility. Mutation: re-add the check at `:253` (M6), or `if validators:` at `_pipeline_routing.py:144` (M10).
- **Keyed folds in any order.** Each keyed fold keeps a key map (filled from parent batches) and a pending map (child rows whose parent key is not yet in the key map: key to count and first indices for `fk_intact`; key to row and parsed date for `parent_window_respected`). When a parent table finishes, pending entries for that edge are probed and released. `reconciliation_holds` keeps per-key child sums and counts and compares them to the parent cells when both sides have finished, so it is order-free. There is no parent-first rule and no refusal for order.
- **One date format per table column.** `parent_window_respected` takes the first non-null value of each date column it reads (the parent start and end columns, the child column), calls `guess_datetime_format` once, and passes `format=` to `to_datetime` on every batch of that column; `format="mixed"` when the guess is `None`, which is what `to_datetime` does for a whole column in that case. The format is fold state, set by the first batch that has a non-null value.
- **Key-state budget, injected.** `run_pipeline` passes `key_state_budget: int | None` from the budget the route already holds: on the generation route a `GenerationBudgetLedger.reserve("validator_key_state", ...)` reservation; on out-of-core the same carve rule its faker pool uses (`out_of_core/_runner.py:213-221`); on the auto-chunk, multi-table and sequential routes the `resolve_budget` figure their admission used (`_transforms_admission.py:264`). Resident routes pass `None` (the maps are smaller than the tables already held). The session imports nothing from `execution` or `generation`, so `.importlinter` gains no ignore line. No new fraction is defined.
- **Where the new calls go (no 600-line module grows).** `run_pipeline` (`_pipeline.py`, 361 lines): session open, proxy wrap, source reader, budget, storing the report (about +30). `_pipeline_routing.py` (566): net negative. `out_of_core/_rewrite_pass.py` (387): one line moved. `_pipeline_finalize.py` (478): net about +2. No edit to `_pipeline_auto_chunk.py` (600), `generation/_streamed.py` (600) or `_sequential.py` (679 of 680). `_pipeline_context.py` (600) and `_chunked_output_sink.py` (600) only lose lines. `_transactional_sink.py` (598) is not edited: the proxy lives in `validators/_sink.py`. A test pins each of those five files at or below its count at `70881ad79`.
- **Principles.** Single responsibility: verdict rules stay in each validator module; bookkeeping, order and budget live in the session; publishing knows only that a proxy observes it; routing knows nothing about validators. The change pain removed: nine copies of one decline, a second validator engine for out-of-core, and a hook per route. Open/closed for routes: a new sink route needs no validator edit. Dependency inversion: the session receives its budget and source reader.
- **One place per fact.** Shape: the registry entry. Cap: `FINDING_INDEX_CAP` in `validators/_types.py`. `leak_check` skip reasons: `plan_scope` in `validators/_scope.py`, which the CLI also calls for `decoy validate`. Report: `ValidationSession.finish`. Date format: the fold's first non-null value.
- **House style.** Typed `RowSpan`, no loose argument lists. No flag arguments: `observe`, `observe_published` and `observe_pair` are named entry points over one core.

## 6. Slices and size

- **S1 FOLDS (engine; no route change; shape changes 2 to 6).** Folds in the existing modules: `_catalog.py` 196 to about 230, `_generic.py` 163 to about 190, `_leak_check.py` 317 to about 365 (seven skip codes), `_fk_validators.py` 303 to about 350 (pending maps), `_relationship_checks.py` 343 to about 400 (pending map, one-format parse). New `validators/_session.py` (about 240) and `validators/_scope.py` (about 80). `validators/_types.py` 104 to about 150 (`failing_row_count`, `ValidatorResult`, `SkippedColumn`, `RowSpan`, `FINDING_INDEX_CAP`). `_registry.py` 138 to about 120 (shape on each entry; `validate` over the session). `_pipeline_finalize.py` feeds the session (about +10, -8). `out_of_core/_validate_batch.py` collector replaced by session calls (317 to about 150; allowlists stay until S3). New public names, exported from `decoy_engine.validators`: `ValidationSession`, `ValidatorResult`, `SkippedColumn`, `plan_scope`, `FINDING_INDEX_CAP`. Tests V1, V2, V3, V10 (engine half), V13.
- **S2 RESIDENT-ROUTES (engine; route change 1 for resident routes).** `run_pipeline` opens the session and stores the report (about +15). Delete the declines at `_unified_slice_admission.py:253` (quarantine and post-scan stay), `_mixed_static.py:211-212`, `_shadow_full_frame.py:387-389`, `_shadow_mixed.py:342-345` and `_shadow_generation.py:414-417`, and every forward and snapshot read in section 4 that belongs to these routes. The plan hash drops the validator count. About -70, +30 across about 14 files. Tests V4 (resident rows), V9.
- **S3 STREAMED-ROUTES (engine; route change 1 for streamed routes; tombstones).** `validators/_sink.py` (new, about 110: `ValidatingSink`, `ValidatingCallable`). `run_pipeline` wraps the sink and builds the source reader and budget (about +15). `decide_output_mode` loses its validator line; `_pipeline_routing.py` loses the sequential and D3a lines and gains the `needs_resident` call; `_pipeline_multi_table.py:150` deleted; out-of-core: `validators_ooc_ready` and `validators_ooc_safe` deleted, `_validate_batch.py` deleted, `observe_pair` at `_rewrite_pass.py:240` and `_stream_driver.py:374`. The runtime codes, the route code, the tombstones, the sentry. About +150, -330. Tests V4 (streamed rows), V5, V6, V7, V8, V14.
- **S4 EXPECT-REPORT (engine-plus-CLI).** Engine: the `leak_check_column_not_checked` `QualityWarning` from `finish` for a skipped column that `columns:` names (about +15); rows in `docs/qa/14-casting-validators-quarantine.md` and `docs/qa/15-execution-routes-native.md`; the paragraph at `docs/strategies.md:2343`; the compatibility contract entry. CLI, after the engine pin: a `Checks` fact and a `validation` member in `--json` in `CLI:src/decoy/cli/run/_render.py` (about +30), with one line per failed or skipped check under the card; the failure path (`CLI:src/decoy/cli/run/_errors.py`) puts the same member in the error payload; `decoy validate` warns when `expect leak_check` names a `keep` column, through the engine's `plan_scope` (`CLI:src/decoy/cli/validate.py`, about +15); `CLI:tests/fixtures/release_freeze/json-shapes.json`; the expect section of `CLI:docs/guides/decoy-language/`. Tests V10 (CLI half), V11, V12.

Order: S1, S2, S3, S4. S4's CLI half waits for an engine release with S1 to S3. Every slice's consumer is named: the session (S1) is called by finalize in S1; `observe_published` and `observe_pair` (S1) are called in S3, before the row closes.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_session.py` | `src/decoy_engine/validators/` | "Job-level validator framework (validators: config block)": `src/decoy_engine/validators/` (8 modules, far under the fan-out cap) | `_registry.py` |
| `_scope.py` | `src/decoy_engine/validators/` | same | `_leak_check.py` |
| `_sink.py` | `src/decoy_engine/validators/` | same (imports only `pyarrow`; `validators` tier, below `execution`) | `_session.py` |
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
| 3 | No exception context | `ValidatorStateError`; `ValidatorFailedError` from `finish` and from the proxy's `commit()` | raised after the `except` block closes; V7 and V8 assert `__cause__ is None and __context__ is None` |
| 4 | Versioned read models | `quality_metrics["validation"]` read by the CLI | additive members under the existing key; the CLI reader is derived from one writer model; V11 has cells for an unknown extra field (tolerated) and a missing `status` (refused) |
| 5 | Normalized guard scanners | `test_validators_do_not_route.py` | covered shapes, each with a seeded failing case: `config.get("validators")`, `config["validators"]`, `ctx.config.get("validators")`, `cfg.get('validators', [])`, a key held in a module-level name and passed to `get`, `if validators:`, `bool(validators)`, `not validators`, `len(validators)`, a parameter named `validators`, `getattr(x, "validators_requested")`, attribute `.validators_requested`, an import of a private `decoy_engine.validators` module. Deliberate evasion is V2-LOG |
| 6 | No reaching into private modules | `execution/` and the CLI use the session, proxy and report types | both import the public names from `decoy_engine.validators`; the private import at `_pipeline_finalize.py:390` moves to the public name |
| 7 | No hidden CI failures | new sentry and route matrix | plain pytest; no `|| true`, no report-only flag |
| 8 | One input, one trust class per entry point | `observe`, `observe_published`, `observe_pair` | named entry points over one core, no flag; table and column names come from the validated config, not a new user boundary |
| 9 | Mutations on the final head | every slice | each slice record lists the head its mutations ran on |
| 10 | Allowlisted helpers are still checked | the sentry allows two call sites | the allowlist holds the exact `(path, function)` pairs of `ValidationSession.open` in `run_pipeline` and `needs_resident` in sequential eligibility; any other site fails |
| 11 | No raised caps | `execution/` fan-out (104), module size (700), the five 600-line files | no module added to `execution/`; one removed from `out_of_core/`; the five files at or below their main counts (section 5); no pin raised |

### Defect catalog classes (engine `DEFECT-CATALOG.md`, section 3)

| # | Class | Where it can enter | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | finding `detail`, skip records, warnings, `ValidatorStateError` messages | details built from counts and names at `finish`; skip codes are registry members; errors name table and column only | V13 | put the first failing cell in `detail` (V13 red) |
| 2 | Cleanup missing on an exit path | validator failure or session refusal on a sink route | the proxy's `commit()` aborts the inner sink before re-raising; `OutputPublish` aborts staging on exit | V4(c), V7 | M3 (V4(c) red) |
| 3 | State and concurrency | per-run fold state, pending maps, source reader | one session per run on the run context; no module-level state; the reader holds one batch | V2, V5 | M8 (V5 retained-batch assertion red) |
| 4 | Route parity and silent fallback | validators choosing a route; a write that skips the session | routing sentry; every sink write goes through the proxy; `validator_table_not_observed` | V4(a), V7, V9 | M5, M6, M10 |
| 5 | Referential integrity | `keyed` validators on bounded routes, any table order, orphans the join nulls | key map plus pending map; the proxy sees the joined batch | V8 | M9 (V8 red) |
| 6 | Untrusted producer | validator params (regex, `allowed_values`) | unchanged validation at session open, before any read | V1 (control) | N/A: no new parsing of user input; existing open-time checks move unchanged |
| 7 | Check then use | `leak_check` pairs source rows with published rows | the reader slices by the published offset; counts compared at commit, `validator_source_pairing_mismatch` | V5 | M4 (V5 red) |
| 8 | Weak tests | chunk sizes where folding and one call coincide | Hypothesis chunk sizes including 1, 7, 4096 and whole table; mixed date formats; 25,000 failures to pass the cap | V2, V3 | M1 (V2 red), M2 (V3 red), M11 (V2 red) |
| 9 | Refactor drift | moving every validator to the fold form | V1 parity against `70881ad79` findings for all 11 validators | V1 | change one fold's index shift (V1 and V2 red) |
| 10 | Frozen contract drift | `ValidationReport`, `ValidatorFinding`, `--json`, plan hash | `Breaking:` lines, compatibility contract entry, CLI shape snapshot | V11, V14 | drop `failing_row_count` from the writer (V11 red) |

## 9. Acceptance tests (each fails before its slice unless marked as a control)

S1:

- **V1 verdict parity (control, passes before and after).** For each of the 11 validators, one fixture that fails on fewer than 10,000 rows: `validate()` gives the same `findings` (validator, table, column, indices, detail) as at `70881ad79`, captured inside the test.
- **V2 chunk and order invariance (property test, Hypothesis, fixed seed).** The session fed at generated chunk sizes, including 1, 7, 4096 and the whole table, and with tables in generated orders (parent first, child first, interleaved), gives one report (ignoring `elapsed_ms`) for every validator, including `leak_check` with a source and the three keyed validators. Date columns for `parent_window_respected` include mixed-format strings (ISO dates, `MM/DD/YYYY`, ISO timestamps, blanks) where the first non-null value falls in the first chunk and in a later chunk; the report equals the whole-table call. Fail-before: `leak_check` and the keyed validators have no per-chunk form (out-of-core refuses them), and a mixed-format child column split at chunk 7 gives a different verdict.
- **V3 cap.** A `regex_match` with 25,000 failing rows: `failing_row_count == 25000` and `failing_row_indices` is the first 10,000 failures; the same config with quarantine `validation_fail` lists all 25,000. Fail-before: no count field.
- **V10 skip record (engine).** `email: passthrough` and `leak_check` with `columns: {customers: [email]}`: the result has `status == "skipped"` and `skipped == (("customers", "email", "leak_check_skip_passthrough"),)`; one `QualityWarning` `leak_check_column_not_checked`; the run passes. With the default scope (no `columns:`) the skip is recorded and no warning is raised. A 10-row table under `min_rows: 50` records `leak_check_skip_below_min_rows`; a scoped table the run does not produce records `leak_check_skip_table_not_produced` with `column=None`. Fail-before: nothing recorded, no warning.
- **V13 value-free (control: no current output carries a value, and the test guards the new fields).** A source with a marker value in every validated column, every validator failing: the marker is in no finding detail, result, skip record, warning, log line or exception message.

S2 and S3:

- **V4 route matrix.** For each route in section 4 (unified 2k rows `hash`; auto-chunk resident 120k; auto-chunk streamed with a `ParquetTransactionalSink` 120k; full frame forced by `post_validation`; mixed route; physical full-frame driver; sequential FK with a transactional sink and with no sink; out-of-core FK; multi-table split; generation with a sink): (a) route label, route reason and per-column backends equal those of the same config without validators; (b) with a passing validator, every result is `passed`; (c) with a failing validator, the run raises `ValidatorFailedError`, the inner sink's `commit` is never called, and the staging directory is empty. A callable-sink row: sequential FK with a plain `Callable[[str, pa.Table], None]` and a failing validator takes a resident route with reason `validators_need_transactional_sink`, the callable is never called, and the run raises `ValidatorFailedError`; with a passing validator every table reaches the callable once. Fail-before: (a) fails on every route except full frame; the callable row has no code.
- **V5 paired, streamed.** 120k rows with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`: fails on the auto-chunk streamed route with the full-frame report, from both a resident `pa.Table` source and a lazy Parquet source. With `hash` the check passes. The source reader never holds more than one batch per table (instrumented counter). Fail-before: the route is resident.
- **V6 bounded memory (performance gate, vm-run on the Dell node).** 2M rows streamed, `leak_check` and `regex_match`, every row failing: `ValidationSession.retained_bytes()` stays under `2 * FINDING_INDEX_CAP * 8` bytes plus 64 KiB plus one source batch projection; peak RSS is within 64 MiB of the same run without validators; wall time with a lazy source is recorded (the second read of the scoped columns). Recorded in the slice record. Fail-before: the run is resident.
- **V7 not-observed guard.** A test sink route that writes to the inner sink through a seam that skips the proxy refuses at commit with `validator_table_not_observed`, commits nothing, and the error has no exception context. A resident route whose finalize step is skipped through a seam refuses before returning outputs. Fail-before: n/a (new guard); its proof is mutation M5.
- **V8 keyed on bounded routes.** `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on the sequential and out-of-core routes give the full-frame report, for single, composite, nullable, two-parent and self-reference FKs. Out-of-core with `orphan_policy` that nulls orphan keys: a child row whose key has no parent is a `no_orphan_children` finding and not an `fk_intact` break, as on full frame. Child-first order (the generation route with a deferred parent, GEN-PER-COLUMN S4, simulated in a session unit test until that slice lands): each of the three keyed validators gives the parent-first report. A key-state budget forced to 1 KiB refuses with `validator_key_state_over_budget` before the first scoped write, nothing committed. Fail-before: both routes decline; the out-of-core hook sits before the join.
- **V9 routing sentry.** Passes on the tree; fails on each seeded spelling in class 5, including `if validators:` in a copy of `_pipeline_routing.py`.
- **V14 tombstones.** `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as deprecated; nothing in `src/` emits them (registry sentry).

S4:

- **V11 card and JSON.** CLI: a passing run with `expect luhn(...)` and `expect leak_check(...)` shows `Checks  2 passed`; a failing run (exit 3) shows `Checks  1 failed: leak_check customers.email`; `--json` carries `validation: {passed, results: [...]}` on success and on failure; the shape snapshot is updated; the reader refuses a bool or numeric-string `failing_row_count` and a free-text `status`, and tolerates an unknown extra field. Fail-before: no fact, no member.
- **V12 validate warning.** `keep email` plus `expect leak_check(customers.email)`: `decoy validate` exits 0 and prints one warning naming `customers.email` and the reason (the column is kept). Fail-before: silent.

## 10. Named mutations (each must turn the named test red on the final head)

- **M1** the session forgets the per-table offset (indices stay chunk-relative): V2 red at chunk 7.
- **M2** the cap also applies under quarantine `validation_fail`: V3 red.
- **M3** the proxy's `commit()` calls the inner commit before `finish`: V4(c) red (commit called).
- **M4** the source reader slices from offset 0 for every batch: V5 red.
- **M5** `write_batches` forwards without calling `observe_published`: V7 and the V4 streamed rows red.
- **M6** `config.get("validators")` re-added to `cheap_admission`: the V4 unified row and V9 red.
- **M7** `leak_check` skips a passthrough column without recording it: V10 red.
- **M8** the source reader reads the whole lazy source before the first batch: V5 counter red.
- **M9** pending child entries dropped when their parent arrives later: V8 child-first cell red.
- **M10** `if validators: return False` re-added to `_sequential_eligible`: V9 and the V4 sequential row red.
- **M11** `parent_window_respected` guesses the format per batch: V2 mixed-format cell red.

## 11. Frozen contracts and compatibility

- `ValidationReport` and `ValidatorFinding` are public (`decoy_engine.validators`) and serialized into evidence. The new fields are additive; the index cap changes a frozen field's behavior. Both go on the changelog `Breaking:` line, in `docs/compatibility-contract.md` (validators entry) and in `docs/strategies.md:2343`.
- `quality_metrics["validation"]` keeps its key and its `validators` member.
- Route changes for validator-bearing jobs (change 1): `Breaking:` line, pointing at `tests/parity/SEMANTIC_DIFFERENCES.md`.
- `parent_window_respected` on mixed-format columns (change 6) and the plan hash (change 7): `Breaking:` lines.
- CLI `--json` gains `validation`: additive; shape snapshot updated.
- Tests that assert a validator-bearing job's route, or `validators_present`, change in S2 and S3. The builder lists each in the PR body with "validators no longer route". Known groups: the out-of-core D3a admission tests (deleted with the allowlists), `tests/physical/` driver decline tests, plan-hash goldens that counted validators, and the decision rows of the chunked output sink tests.

## 12. Related plans

- `plan/per-column-routing` lists validators among the table-wide declines (its item 2). After this row validators are not a decline, so that list loses one word. Whichever merges second drops it.
- `plan/route-label-truth` registers decline codes in `reasons/route/`; this row tombstones `validators_present`. Both edit `reasons/route/__init__.py` and `_retired.py`: parallel ledger lines, keep both on merge. Its E1 test has a "validators" cheap-stage case and its CLI `native_config_outlook` keeps a validators decline. If RLT merges first, this plan's S2 deletes the E1 validators case and the outlook's validators decline in the same PR as the admission change. If this plan's S2 merges first, RLT drops both before it merges.
- `plan/gen-per-column` S4 writes a parent table after its children. The keyed folds here take tables in any order (pending maps, section 5), so no refusal fires and V8 covers child-first order. Its section 12 says the same.
- `plan/when-reads-source` creates a runtime `_retired.py` if absent; this plan uses the same file. Whichever lands first creates it.
- `plan/uf-domain` U7 runs "full frame with a validator" as its own case. After S2 that config takes the unified slice. U7's intent (same output schema with a validator on) holds, and it needs no edit.
- `plan/gen-stream-all` S1a moves the batch assembler. This plan does not edit `generation/`: the generation sink route is fed by the proxy.

## 13. Pre-mortem

- A route publishes through a path that does not use the caller's sink (for example a new internal collector that writes a file itself): `run_pipeline` refuses with `validator_table_not_observed`, because the session never observed or finished those rows. A loud failure, not a silent skip.
- A sink helper is reached through the proxy's `__getattr__` and writes a table itself (not through `write` or `write_batches`): the count check at commit refuses. A unit test lists the inner-sink methods that write and asserts the proxy overrides each.
- A user relies on the full index list for more than 10,000 failures: the count stays exact, and the changelog names quarantine as the way to get every row.
- A native route's output differs from pandas on a validated column (Unicode normalization on `hash`): the verdict follows the published bytes. The parity file already names the difference.
- `reconciliation_holds` on a very large parent, or a child-first order with a large pending map: the budget refuses before the first scoped write. The message names the table and says to set `execution_mode: full_frame` or give the run more memory.
- A lazy CSV source with `leak_check` on a streamed route is read twice (scoped columns only). V6 records the cost; a resident or Parquet source avoids most of it.
- Out-of-core starts rewriting a non-key column after the mask step: the paired fold reads `out` at `yield out`, after every rewrite, so it still reads published values.

## 14. Open questions for the owner

1. `FINDING_INDEX_CAP` = 10,000 per finding with an exact count (recommended), or every index on resident routes only (evidence would then depend on the route; not recommended).
2. `leak_check` naming a `keep` column: warning and exit 0 (recommended, as the audit says), or a config error.
3. A plain callable sink with validators runs resident (recommended: keeps "nothing published on failure"), or streams with a per-table verdict before each write (earlier tables that passed stay written when a later one fails, as the callable contract already allows for other errors).
