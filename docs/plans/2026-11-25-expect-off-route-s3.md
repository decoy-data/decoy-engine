Status: plan

# EXPECT-OFF-ROUTE S3: streamed routes judge validators, and validators stop picking a route

Rules consulted: `/home/cam/dev-rules/00-universal.md`, `/home/cam/dev-rules/risk-and-exceptions.md`, `/home/cam/dev-rules/development-loop.md`, `/home/cam/dev-rules/cross-cutting-concerns.md` (choke point, guard, mutation), `/home/cam/dev-rules/testing.md` (Test depth), `/home/cam/dev-rules/workspace-and-vcs.md` (Commit messages), the plan contract and defect catalog (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`), and the row's master plan rev 7 on the PR #812 branch (`docs/plans/2026-11-22-expect-off-route.md`: section 3a invariant, section 5 design notes, section 6 slices, sections 9 and 10).

Row: EXPECT-OFF-ROUTE (validators stop forcing pandas). Repo: decoy-engine. Risk: R2 (publication order, fail-open class, route contract, physical plan hash). Anchor: PR #812 (S2) at `029f1b378` plus the fixes in flight in its worktree for three findings: standalone shadow runs skip validators, the verdict is not enforced on scope exit, and an ambient session judges the wrong config. S3 builds on the end state those fixes intend (section 1). Line numbers are from `029f1b378` and move with the merge.

This file plans S3 in full. S4 is an outline (section 13).

## 1. Frame and the S2 end state S3 assumes

After S2, every resident route is judged by one session (`validators/_session.py`), and the section 3a invariant holds: every delivered table is judged exactly once. S3 relies on these S2 facts. If #812 merges without one of them, S3 re-plans that step before it builds.
- `bind_validation_session` (`validators/_session.py:54`) binds the ContextVar for every run. A run whose config has no validators binds `None`, so a nested run never sees an outer run's session (the "ambient session" fix). At `029f1b378` the no-validator branch yields `None` without setting the ContextVar; the fix in flight sets it.
- Leaving the bind scope normally calls `close()` unless a caller already did (`validators/_session.py:73`).
- `close()` (`validators/_session.py:271`) is the one judge. It refuses a table that is complete or deferred but never fed (`validator_table_not_observed`), and it raises `ValidatorFailedError` for a finding on a table no judge settled.
- The standalone shadow coordinator judges its own result unless `ShadowContext.validation_owner` names an owner (`execution/physical/_shadow_generation.py:285`). The standalone coordinator reads `PhysicalPlan.validators`, which the S2 compiler copies from `PhysicalPlanInputs.validators` (`execution/physical/_compiler.py:439`).

What still forces a route: validators send every streamed and bounded route to resident. The reads are pinned in `S3_PENDING` (`tests/sentry/test_validators_do_not_route.py:32`). Codex counted 55 pinned identities, 67 occurrences and 19 modules on the in-flight S2 head; step 1 recounts on the merged head. The out-of-core route keeps a second validator engine (`execution/out_of_core/_validate_batch.py`, 387 lines) that also protects a direct caller of the public `run_fk_out_of_core` (`execution/out_of_core/__init__.py:65`, `_validate_batch.py:326`) and records its verdict on the session with an owner token (`_validate_batch.py:387`).

## 2. Guarantee and non-goals

Guarantee:

- G1. A config with validators takes the same route, route reason and per-column backends as the same config without validators, on every route, with two exceptions that keep the run resident under a named route code:
  - `validators_need_transactional_sink`: the sink is not transactional (a plain callable, or a partial shape), so rows would leave before the verdict.
  - `validators_need_resident_rows`: the config enables quarantine, or a paired check runs on a route that has no order-preserving source tap (5.4). The bounded routes cannot remove rejected rows or keep source and output aligned there, so the resident quarantine path stays (it filters covered failures and succeeds).
- G2. On a streamed route, no row reaches a committed sink before the run's verdict. A failing verdict raises `ValidatorFailedError` before `sink.commit()`; the failure is recorded as a validation failure, never as a COMMIT failure. On a no-sink bounded route, the verdict runs before the result is sealed or returned.
- G3. A streamed route's report equals whole-table validation of that route's delivered output (findings, counts, capped indices). On route-stable columns it equals the full-frame report. Where a route delivers different bytes for the same input, the report follows the delivered bytes: the documented case is a passed-through float NaN that survives out-of-core and becomes null on full frame (`tests/parity/SEMANTIC_DIFFERENCES.md:40`), so a `regex_match` that rejects `"nan"` finds it on out-of-core and not on full frame. AT-17 pins that exact report on both routes.
- G4. Validator memory on a streamed route stays bounded: per paired table, one captured source batch and the matching output slice, plus the fold state under the session's key-state ceiling. Captured source projections that wait for their output are spilled to disk (5.4), not held.
- G5. No error, failure record or log text carries a cell value.

Non-goals:

- No run-card fact, CLI JSON member or `leak_check_column_not_checked` warning (S4).
- No streaming for quarantine, post-validation, fidelity report or declared casting on the chunked lane: those keep their own resident reasons (`execution/_chunked_output_sink.py:110-122`).
- No change to any verdict rule inside a validator module.
- A direct caller of `run_fk_out_of_core` keeps validation; no other public runner is added.

## 3. Established solutions

- Validate before publish, publish atomically: the two-phase write the engine already uses (`TransactionalSink` stage, then `commit`). S3 puts the verdict between them, as a database runs deferred constraints at COMMIT (PostgreSQL `SET CONSTRAINTS ... DEFERRED`: checks run at commit time, and a failure rolls back).
- Observe writes through a proxy: the decorator pattern (GoF), as `io.BufferedWriter` wraps a raw stream. The proxy keeps the wrapped object's shape so protocol checks still see the real capabilities.
- Expected-set completeness at commit: a two-phase commit coordinator registers every participant before the prepare phase and refuses to commit while one has not voted. S3 registers the route's delivery set before the first write.
- Capture the pair where it is produced: the engine's vault already records the aligned source and masked batch at the mask step (`collect_batch_vault`, `out_of_core/_rewrite_pass.py:236`, `out_of_core/_stream_driver.py:373`) instead of re-reading the source, because a second read can be permuted. Paired checks use the same rule.
- Spill to disk for an unbounded wait: Arrow IPC streaming files, read back one batch at a time (`pyarrow.ipc.new_stream`, `open_stream`).
- Streaming checks with order-free folds: S1 and S2 already use mergeable aggregates (Apache Beam `CombineFn`: `add_input`, `extract_output`).

## 4. Reuse inventory

| Need | Reuse | Where |
|---|---|---|
| The judge | `ValidationSession.close` | `validators/_session.py:271` |
| Feed a written batch | `observe_published` | `validators/_session.py:172` |
| Feed a resident table against a lazy source | `observe_source_batches` | `validators/_session.py:195` |
| Paired tables | `paired_tables` | `validators/_session.py:231` |
| Resident completion choke | `complete_resident_validation` | `execution/_pipeline_route_dispatch.py:76` |
| Commit choke | `observed_commit` | `execution/_publication_observer.py:132` |
| Sink shape check | `_has_transactional_write_contract` (moved, 5.2) | `execution/_sequential.py:207` |
| Sink identity | `post_scan_sink_kind` | `config/_post_scan.py:211` |
| Loader tee | `tee_reader` (post-scan) | `execution/pipeline/_post_scan.py:537` |
| Aligned pair sites | `collect_batch_vault` calls | `out_of_core/_rewrite_pass.py:236`, `out_of_core/_stream_driver.py:373` |
| Runtime codes | `VALIDATOR_TABLE_NOT_OBSERVED`, `VALIDATOR_SOURCE_PAIRING_MISMATCH`, `VALIDATOR_KEY_STATE_OVER_BUDGET` | `reasons/runtime/_part3.py:99-102` |
| Retired route codes | `reasons/route/_retired.py` | 20 lines today |
| Physical reason tokens | `ROUTE_VALIDATORS_PRESENT` | `execution/physical/_reasons.py:56`, `:101`, `:343` |
| Routing sentry | `S3_PENDING` and `_scan` | `tests/sentry/test_validators_do_not_route.py:32`, `:197` |
| Module size guard | `test_module_size.py` | `tests/sentry/` |

## 5. Design

### 5.1 Who owns the session, and one feed point per delivery shape

New `judged_run(config, sink, *, key_state_budget)` context manager in `execution/_validated_sink.py`. It is the one way a route gets a session and a wrapped sink:

- If a session is bound for this config (the pipeline bound it in `execute_route`), it reuses that session and does not wrap twice (wrapping a proxy returns the proxy).
- If none is bound for this config (a direct call of `run_fk_out_of_core`), it binds one with `bind_validation_session`, wraps the sink, and owns the verdict. "For this config" is the bound session's config identity; step 1 confirms the pipeline passes the same object to the runner, and if it passes a copy the check uses the config hash.
- It registers the route's delivery set with the new `session.expect_delivery(tables)` before the first write (5.3).
- It yields the wrapped sink (or `None`) and a `judge_resident(tables)` callable for a no-sink route.

`execute_route` and `run_fk_out_of_core` both enter `judged_run`. The runner's collector (`out_of_core/_runner.py:216`), its forward (`:322`), `finish_validation` (`:359`) and all of `_validate_batch.py` are deleted. The `_delivered` hooks (`_rewrite_pass.py:198-200`, `_stream_driver.py:431-433`) and the `validators` parameters (`_rewrite_pass.py:93`, `_stream_driver.py:154`) go with them. `record_external_verdict` and the `_external` set lose their only caller and are deleted.

A table reaches the session at one of two choke points:

- A table written to a sink is fed by the sink proxy (5.2), batch by batch, in delivered order.
- A table returned resident is fed by `complete_resident_validation` (pipeline) or by `judge_resident` (direct out-of-core call), which calls the same session functions.

### 5.2 Sink shapes and the proxy

One classifier for sink shape. `_has_transactional_write_contract` moves from `_sequential.py:207` to `execution/_transactional_sink.py`, next to the `TransactionalSink` protocol (`:75`), as public `sink_shape(sink) -> SinkShape` with four values: `CALLABLE` (plain callable, no `commit`), `STAGED` (callable `write`, `commit` and `abort`, no `write_batches`), `TRANSACTIONAL` (all four), `PARTIAL` (anything else, for example `commit` without `abort`). `_sequential.py` imports it (its local function is deleted, so the file shrinks). Route admission, the proxy and sequential delivery all read `sink_shape`.

New `execution/_validated_sink.py` (about 180 lines) holds `judged_run`, the proxy, and `validation_needs_resident`. The proxy is placed in execution because it depends on the sink protocol; `decoy_engine.validators` keeps only the session API. S1 listed `observe_sink` as a `decoy_engine.validators` name; S3 moves it, and the S1 public-name list is corrected in the same PR.

`observe_sink(sink, session)` wraps only `STAGED` and `TRANSACTIONAL` sinks. `CALLABLE` and `PARTIAL` sinks never reach a streamed route with validators (5.5).

- `_ObservedStaged`: `write` feeds, then forwards. `commit` and `abort` forward only.
- `_ObservedTransactional`: `write` and `write_batches` feed, then forward. `write_batches` feeds each batch as the inner sink pulls it, so nothing is buffered. When no batch arrives (a zero-row table, written as `write_batches(table, iter(()), schema=...)` at `_chunked_output_sink.py:591`), it feeds `schema.empty_table()` once, so the table is observed.

Each class carries a read-only `inner_sink`. `__getattr__` forwards an attribute only when the inner sink has it, so `staged_tables`, staged openers and publication evidence still work, and no protocol member is invented. `_ObservedStaged` has no `write_batches`, so `isinstance(proxy, TransactionalSink)` stays false for it.

Installing the proxy. Most streamed writes use `ctx.publish.active_sink`, and `OutputPublish` (`_chunked_output_sink.py:128`) is an ordinary class built with the raw sink at `_pipeline_context.py:267` (writers at `_pipeline_generate_mask.py:251`, `:286`, `_pipeline_mixed_route.py:224`, `:241`, `_pipeline_full_frame.py:303`; commit at `_chunked_output_sink.py:161`). Before any executor runs and before the publish opens, `execute_route` builds a new `OutputPublish(proxy, stream=ctx.publish.stream, post_validation=ctx.publish.post_validation)` and replaces the context once with `dataclasses.replace(ctx, sink=proxy, publish=new_publish)`. On a no-sink route both stay `None`. The edit is in `_pipeline_route_dispatch.py`; `_pipeline_context.py` (599) and `_chunked_output_sink.py` (600) do not grow. Routing has already decided on the unwrapped sink.

While a session is bound, `observed_commit` refuses a sink that is not a proxy (it has no `inner_sink`) with `validator_table_not_observed` and a fixed message, before any commit.

`post_scan_sink_kind` (`config/_post_scan.py:211`) follows `inner_sink` (with a seen-set against cycles) before it returns the class token. Every consumer that names a sink kind already calls it: `post_scan_sink_refusal` (`config/_post_scan.py:237`), the two readability calls in `pipeline/_post_scan.py`, and `physical/_snapshot.py`.

### 5.3 The verdict at commit, and completeness

`judged_run` registers the delivery set before the first write: the output tables the route writes, from the frozen config (step 1 confirms the source per route: the split route's dispatched set, the out-of-core plan's tables, the sequential plan's tables). The session keeps it as `_expected`.

`observed_commit` (`execution/_publication_observer.py:132`), after `gate.before_commit(sink)` (`:141-142`) and before `evidence_of(sink)` (`:143`):

1. Marks complete every table in `_expected` and, where the sink has `staged_tables()` (`execution/_transactional_sink.py:427`), every staged table as well.
2. Calls `active_validation_session().close()`.

A table in either set that the proxy never fed (written around the proxy, or never written) is refused by `close` with `validator_table_not_observed`. The expected set does not depend on the sink, so a four-member sink with no `staged_tables` and no read-back is covered the same way as `ParquetTransactionalSink`. An empty table is observed by the proxy's empty feed, so it counts.

A `ValidatorFailedError` leaves before the commit `try`, so no COMMIT failure is captured, and the existing unwinds abort the sink: `OutputPublish.__exit__` (`_chunked_output_sink.py:165`), the sequential executor's failure path, and the out-of-core runner's.

A commit is the run's last action on every sink route (one `observed_commit` call per route: `_chunked_output_sink.py:161`, `_sequential.py:625`, `out_of_core/_runner.py:362`). A table fed after the verdict is a wiring bug: `_feed` (`validators/_session.py:311`) raises `ValidatorStateError` with the new runtime code `validator_rows_after_verdict` and a fixed message naming the table, in place of today's bare `ValueError`.

After the executor returns, `complete_resident_validation` sees `close_attempted`. It refuses with `validator_table_not_observed` if a resident output table was never fed, and otherwise returns the stored report without a second judgement.

Out-of-core order and cleanup. Today `finish_validation` runs at `_runner.py:359`, before `seal_evidence` (`:360`). After S3:

- With a sink, the verdict runs in `observed_commit`, after `seal_evidence`. The commit call already sits inside the declared-cast owner's abort scope, so a failure aborts the sink and discards the sealed quarantine evidence. AT-16 checks the event order (seal, verdict, abort, discard) and that no sealed artifact remains on disk.
- Without a sink, the runner calls `judge_resident(tables)` before `seal_evidence` and inside the same cast-owner scope, so a failing verdict seals nothing and the owner's abort removes its temp output. AT-16 checks this cell too.

### 5.4 Sources for paired checks

A paired check (for example `leak_check`) compares an output row with the source row that produced it. Re-reading `ctx.caller_sources` is wrong: a same-count permutation on a second read silently breaks alignment and can make `leak_check` pass unchanged output; loader-only out-of-core tables exist only in `resolved_sources`; and declared casting runs the masking step over typed copies (`declared_casting/_stream.py:265`). So S3 captures the source where the masking step consumes it.

- New `session.source_tap(table) -> Callable[[pa.RecordBatch], None] | None`. It returns `None` for an unpaired table. For a paired table it appends the projection of the paired columns of each batch to a session-owned spill (Arrow IPC stream file in the run's temp directory), in the order the rows will be delivered.
- New `validators/_source_cursor.py` (about 120 lines): `SourceCursor(spill_path)` reads the spill one record batch at a time. The proxy and the resident feed slice each output batch at source-batch boundaries before the fold, so one fold call holds one source batch and the matching output slice. At `finish`, a cursor with rows left raises `validator_source_pairing_mismatch`, and a cursor that runs out first raises the same code. The session closes the reader and deletes the spill on `close`, on scope exit and on every exception (its `ExitStack`).
- Where the spill is charged: the route's temp-disk budget where it has one (out-of-core `temp_disk_budget_bytes`, `_runner.py:122`), else the run's temp directory as other spills are.

Tap sites. A tap sits where row order equals delivered order:

- Sequential: `ValidationSession.tee_reader()` returns a loader tee that taps each loaded table. `execute_sequential_route` (`execution/_pipeline_route_dispatch.py:160`) composes it with the post-scan tee at `:167` through a small `compose_tees` helper in the same module. `_sequential.py` is not edited for this.
- Auto-chunk streamed and split: the batch iterator that feeds the mask step in `_pipeline_generate_mask.py` (step 1 names the line).
- Out-of-core rewrite pass: beside `collect_batch_vault` (`_rewrite_pass.py:236`), on `raw_batch`, which is aligned with `out`. Declared rendering (`_rewrite_pass.py:255`) keeps row count and order once quarantine is resident (G1), and the proxy checks per table that the delivered row count equals the tapped count.
- Out-of-core stream driver: the aligned pair is at `_stream_driver.py:373`, before the reorder and the type reconcile. Rows reach the sink in a different order. If the driver can apply its reorder permutation to the spill (step 1 checks), the tap records the permutation with the spill and the cursor reads in delivered order. If it cannot, `validation_needs_resident` sends a paired check on that driver resident with `validators_need_resident_rows`. Either way the run is never judged on misaligned rows.

A paired table whose output reaches the fold with no tap raises `validator_source_pairing_mismatch` (fail closed). The validators package imports no execution module; it receives the spill directory as an argument.

### 5.5 When validators need resident

New public `validation_needs_resident(config, sink, *, route) -> str | None` in `execution/_validated_sink.py`. It returns a route code or `None`:

- `validators_need_transactional_sink` when the config has validators and `sink_shape(sink)` is `CALLABLE` or `PARTIAL`.
- `validators_need_resident_rows` when the config has validators and quarantine is enabled, or when it has a paired check and `route` is a driver with no order-preserving tap (5.4).

It is called once in `decide_execution_route` before the byte-estimate branch, so a decline is never replaced by `BYTE_ESTIMATE_FULL_FRAME_FITS`, and the decline is the recorded reason. The physical snapshot records `sink_shape` so physical replay reaches the same decision. Forced sequential or forced out-of-core with a job it declines refuses with the existing forced-mode refusal, naming the same code. A job too large for resident refuses with the resident route's existing capacity refusal; the routing record still names the validator code.

Callable delivery. The resident route leaves `OutputPublish.active_sink` `None` and its commit inert, so no resident callback exists today. S3 adds one delivery in `execute_route`: after `complete_resident_validation` and the post-scan settle, it calls the original callable once per judged table, in plan order. The callable is never wrapped, so delivering it does not feed the session. A failing verdict raises before the delivery, so the callable is called zero times. The out-of-core runner types its sink as `TransactionalSink | None` (`out_of_core/_runner.py:117`); an admission test pins that a callable never reaches it.

### 5.6 Delete every routing read

Every entry in `S3_PENDING` is deleted at its source:

- Route choice: `decide_output_mode` loses `:114-115`; `_pipeline_routing.py` loses the `_sequential_eligible` decline (`:144`), `bounded_admission`'s validator parameter, `validators_ooc_ready` (`:338-349`) and the D3a lift in `decide_execution_route`; `_pipeline_routing_signals.resolve_execution_route` stops forwarding; `_pipeline_multi_table._job_gates_hold` loses `:151`.
- Mirrors of the decline: `_job_estimate._estimate`, `capacity.estimate_job_capacity`, `pipeline/_lazy_input._relationship_job_is_bounded`, `_transforms_admission.check_rejections_before_preparation`, `_transforms_prepare.prepare_transform_sources`, `_pipeline_context.build_run_context` and `decide_route`, `_unified_slice._execute_admitted`.
- Physical plan replay: `physical/_compiler.layer1_route` and `out_of_core_not_ready_reason` stop reading validators. `PhysicalPlanInputs.validators` stays: it is filled by a new lifecycle helper `physical_validator_spec(config)` (allowlisted), and the compiler still copies it to `PhysicalPlan.validators` (`_compiler.py:439`) for the standalone coordinator. AT-18 keeps a standalone mask-plan run with a failing validator and no caller validation config.
- `ROUTE_VALIDATORS_PRESENT` leaves the physical reason-token catalog (`execution/physical/_reasons.py:56`, `:101`, `:343`).
- Out-of-core: 5.1.

The plan hash does not move for a fixed config: `compute_plan_hash` hashes the whole config (`execution/physical/_inputs.py:87-95`, `:324`), and the validator field is not separately in the hash tuple. What moves is the recorded route decision for configs with validators. Before regenerating any golden, the builder compares a fixed snapshot across the two revisions.

`S3_PENDING` is then empty and is deleted. The sentry keeps an allowlist of exact `(module, function, public name)` identities for lifecycle wiring only:

- `judged_run`, `observe_sink` and `complete_resident_validation` in `execute_route`; `judged_run` in `run_fk_out_of_core`;
- `active_validation_session` in `observed_commit` and `execute_sequential_route`;
- `validation_needs_resident` in `decide_execution_route`; `physical_validator_spec` in the physical input builders;
- the S2 callers that remain: `_pipeline_finalize.py:417`, `:421`, `:432`, `_pipeline_mixed_route.py:65`, `:294`, and `physical/_shadow_generation.py:269`, `:276`, `:285`, `:292`.

S3 adds caller tracking for the public helpers to the scan, so this list is enforced. The stale comment at `_pipeline_mixed_route.py:294-296` ("streamed output declines validators") is corrected. Any other read of the `validators` key or a `validators*` name under `execution/` fails.

### 5.7 Reason codes

- New route codes `validators_need_transactional_sink` and `validators_need_resident_rows` (`reasons/route/`).
- New runtime code `validator_rows_after_verdict` (`reasons/runtime/_part3.py`).
- Retired: `route.validators_present` (`reasons/route/_part1.py:306`) moves to `reasons/route/_retired.py`. `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`) is retired the same way; if the runtime family has no retired module, S3 adds `reasons/runtime/_retired.py` on the route pattern.

### 5.8 Placement

| New or changed item | Directory | CODEMAP row | Why here |
|---|---|---|---|
| `_validated_sink.py` (`judged_run`, proxy, `validation_needs_resident`) | `src/decoy_engine/execution/` | execution publish rows, beside `_publication_observer.py` | depends on the sink protocol; validators stays free of execution imports |
| `sink_shape` | `execution/_transactional_sink.py` | transactional sink row | next to the protocol it classifies |
| `_source_cursor.py` | `src/decoy_engine/validators/` | "Job-level validator framework" (added in S1) | the session's own spill and cursor; pyarrow only |
| `compose_tees` | `execution/_pipeline_route_dispatch.py` | route dispatch | the one place that builds the sequential loader |
| tests | `tests/unit/validators/`, `tests/unit/execution/judgement/`, `tests/sentry/` | per the S1 row | as S1 and S2 |

No module over 600 lines grows: `_sequential.py` (680), `_chunked_output_sink.py` (600), `_pipeline_routing_signals.py` (613) and `_pipeline_context.py` (599) only lose lines. `_transactional_sink.py` (598) gains `sink_shape` (about 25 lines); if that passes 600 it takes a census entry with a ceiling, under the 700 max. The existing module-size sentry enforces all of this.

### 5.9 Design notes

- One owner of the session (`judged_run`), one feed point per delivery shape (sink proxy or resident judge), one judge (`close`), one judgement time for sink routes (commit), one sink classifier (`sink_shape`), one capture point for paired sources (the tap). Each has a guard test and a mutation (section 8).
- Routing knows nothing about validators, except the one public question `validation_needs_resident`.
- Dependency direction: `validators/` takes the spill directory and budget as arguments and imports no execution module.
- Pre-GA hard delete: the out-of-core collector, `record_external_verdict`, `S3_PENDING` and the retired codes go in this slice.

## 6. Behavior and failure modes

| Case | Behavior |
|---|---|
| Auto-chunk streamed with a `TransactionalSink`, validators pass | Route `streamed`, same reason as without validators; one commit. |
| Same, a validator fails | `ValidatorFailedError` before `sink.commit()`; abort runs; staging is empty; no COMMIT failure record. |
| Sequential FK with a plain callable sink | Resident, `validators_need_transactional_sink`; callable called once per table after a pass, zero times after a fail. |
| Partial sink shape (for example `commit` without `abort`) | Resident, `validators_need_transactional_sink`. |
| Config with validators and quarantine | Resident, `validators_need_resident_rows`; covered failures filtered as on full frame. |
| Sequential FK with a transactional sink | Sequential route; verdict at commit. |
| Out-of-core through the pipeline, with a sink | Out-of-core route; proxy feeds rendered batches; verdict at commit inside the cast-owner scope. |
| Out-of-core through the pipeline, no sink | Out-of-core route; resident judge before `seal_evidence`. |
| Direct `run_fk_out_of_core` call, with or without a sink | `judged_run` binds its own session; same verdicts as through the pipeline. |
| Paired check | Source tapped at the mask step, spilled, read back one batch at a time. |
| Stream driver, paired check, no reorder permutation available | Resident, `validators_need_resident_rows`. |
| Source rows differ in count from delivered rows | `validator_source_pairing_mismatch`, nothing committed. |
| Rows fed after the verdict | `validator_rows_after_verdict`, fixed message. |
| A write handle holds the raw sink | `observed_commit` refuses a non-proxy sink while a session is bound. |
| A table written around the proxy, any sink shape | In the expected set and unfed; `close` refuses with `validator_table_not_observed`. |
| Zero-row table on a streamed route | The proxy feeds an empty table once; the table is judged. |
| Forced sequential with a callable sink and validators | Forced-mode refusal naming `validators_need_transactional_sink`. |
| Too large for resident after a validator decline | Resident capacity refusal; routing record names the validator code. |
| Keyed state passes the ceiling | `validator_key_state_over_budget` before the next scoped write; nothing committed. |
| Nested run with no validators inside a bound run | The inner commit sees no session (S2 end state) and does not close the outer session. |

## 7. Acceptance tests

Master plan numbers in brackets. A failure uses a reject-all `regex_match` (`pattern: "^$"`) unless stated, over a table with a seeded cell value `SECRET-CELL-7731`. Each test fails before S3 unless marked as a control. The PR records, per cell, the observed failure before S3 and the final-head mutation result.

- AT-1 [V4 streamed rows]. Routes: auto-chunk streamed with `ParquetTransactionalSink` (120k rows); sequential FK with a transactional sink and with no sink; out-of-core FK with and without a sink; multi-table split with a sink; and the mixed route's streamed generate (`_pipeline_mixed_route.py:224`; `run_generation` is reached only from `generation/_plan_entry.py` and is out of scope). Each route checks:
  - (a) the route label, route reason and per-column backends equal the same config without validators. This fails before S3 on the auto-chunk, sequential, split and mixed cells. The out-of-core cells are controls, because S2's D3a lift already keeps them out-of-core.
  - (b) a passing validator gives `passed` results.
  - (c) a failing validator raises `ValidatorFailedError` with the exact finding count (7 rejected rows in the fixture, not 14). The inner `commit` is never called, staging is empty, and the failure record does not say COMMIT. `SECRET-CELL-7731` is absent from `str(exc)`, the failure record and the captured logs.
- AT-2 [V4 callable row]. Sequential FK with a plain callable and validators:
  - The route is resident with `validators_need_transactional_sink`.
  - A failing validator calls the callable zero times and raises.
  - A passing validator calls it exactly once per table, after `close`, and the session sees no feed from the delivery.
  - A forced-sequential cell refuses with the forced-mode refusal naming the code.
  - A capacity cell (resident budget forced low) refuses with the resident capacity refusal.
  - A table-driven cell runs `sink_shape` on a plain callable, a partial shape, a three-member sink and a four-member sink, and checks route admission, wrapping and sequential delivery against the same answer.
  - An admission cell pins that the out-of-core runner never receives a callable.
- AT-3 [V4 readability rows]. `ParquetTransactionalSink` and an isolated `StagingSink`, each wrapped, with `post_scan.integrity`: no `POST_SCAN_INTEGRITY_SINK_UNREADABLE`; the integrity report shows the gate ran; the physical snapshot holds the inner sink kind and the sink shape. The isolated row runs pass and fail and proves `StagingSink.commit()` and `.abort()` stay no-ops.
- AT-4 [V5]. A 120k-row table with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`. Source batches are 4,096 rows and sink batches 10,000, so boundaries never line up. The check fails with the whole-table report of the delivered output on the streamed, sequential and out-of-core rewrite routes, from a resident `pa.Table` source and from a lazy Parquet source. With `hash` it passes. `tracemalloc` during each fold `add` stays under one source batch projection plus the matching output slice plus 64 KiB. A sequential run with empty `caller_sources` and a counting `source_loader` loads each table once.
- AT-5 [V6, perf, Dell vm-run]. 2M rows streamed, `leak_check` and `regex_match`, every row failing: `retained_bytes()` under `2 * FINDING_INDEX_CAP * 8` plus 64 KiB plus one source batch projection; peak RSS within 64 MiB of the same run without validators; spill bytes equal the paired-column bytes; wall time recorded.
- AT-6 [V7]. Writes around the proxy refuse before commit with `validator_table_not_observed`, nothing committed, no exception context. Cells:
  - Two tables, A through the proxy and B written straight to the inner sink, commit through the proxy. Run once on `ParquetTransactionalSink` and once on a four-member sink with no `staged_tables`.
  - A three-member sink is wrapped and `isinstance(proxy, TransactionalSink)` is false; a four-member sink stays true.
  - Rows fed after `close` raise `validator_rows_after_verdict`.
- AT-7 [V8]. `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on sequential and out-of-core give the full-frame report for single, composite, nullable, two-parent and self-reference FKs. Out-of-core with an orphan policy that nulls orphan keys gives a `no_orphan_children` finding, not an `fk_intact` break. Named cells:
  - child-first: the child rows arrive before the parent, and one child's raw key is null; the report names that row as not judged by the window rule.
  - duplicate key: two child rows reference one parent key outside its window; both indices appear in the report.
  - A key-state budget forced to 1 KiB refuses before the first scoped write.
- AT-8 [V9]. The routing sentry passes on the tree with `S3_PENDING` deleted. It fails on each seeded spelling (`config.get("validators")`, `if validators:`, a `validators_ooc_ready` name) in a copy of `_pipeline_routing.py`, and on a call to `validation_needs_resident` from an unlisted function.
- AT-9 [V14]. `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as retired; `ROUTE_VALIDATORS_PRESENT` is gone from the physical catalog; nothing in `src/` emits them (registry sentry).
- AT-10. A run with no validators nested inside a bound run commits without closing or feeding the outer session. Control after the S2 fix.
- AT-11 [V15f]. Out-of-core with a failing validator raises `ValidatorFailedError` through `run_pipeline`, and through a direct `run_fk_out_of_core` call with a sink (nothing committed) and without a sink (nothing returned). The session has no external-verdict attribute, and every delivered table was fed and judged.
- AT-12. For a fixed config, the physical plan hash is the same before and after S3. A config with validators records the same route decision as the same config without them.
- AT-13. Every streamed writer reaches the proxy. On the auto-chunk, split and mixed routes, a spy on the real `OutputPublish` shows each batch fed through `write_batches` and the commit called on the same proxy object. A test seam that writes through the original `publish.active_sink` object makes `observed_commit` refuse with `validator_table_not_observed` before commit.
- AT-14. A zero-row table passes. A zero-row table under a reject-all check, beside a non-empty sibling, still fails. Both run on the streamed, sequential and out-of-core routes.
- AT-15 [V5 extension]. Pairing alignment:
  - A source that returns the same rows rotated by one on each read gives the report of the first read, on both out-of-core drivers.
  - A loader-only out-of-core table (present only in `resolved_sources`) is paired.
  - A declared cast that changes the paired rows' type pairs against the cast input.
  - A source one row longer than the output refuses with `validator_source_pairing_mismatch`.
  - On the stream driver, either the permutation cell passes, or the route is resident with `validators_need_resident_rows`. Step 1 records which.
- AT-16. Out-of-core with declared casting and a failing validator. With a sink, the event trace is seal, verdict, abort, discard, and no sealed quarantine artifact remains on disk. Without a sink, the trace is verdict, abort, with no seal, and the temp output is removed.
- AT-17. NaN pass-through: a float column with NaN under `regex_match` rejecting `"nan"`. Out-of-core reports the NaN rows and full frame does not, with the exact report pinned for both routes (G3).
- AT-18. A standalone mask-plan run with a failing validator and no caller validation config raises `ValidatorFailedError` (`PhysicalPlan.validators` still filled).
- AT-19. Config with validators and quarantine enabled: resident with `validators_need_resident_rows`; covered failures are filtered and the run succeeds, as on full frame today; no quarantine sidecar is written when an uncovered failure raises.

## 8. Named mutations

Master plan numbers in brackets. Each must turn the named test red on the final head.

- M-1 [M3]. `observed_commit` commits before `close`: AT-1(c) red.
- M-2 [M4]. The source cursor restarts from row 0 for each output slice: AT-4 red.
- M-3 [M5]. `_ObservedTransactional.write_batches` forwards without feeding: AT-13 spy red.
- M-4 [M8]. The cursor reads the whole spill into memory on open: AT-4 `tracemalloc` red.
- M-5 [M10]. `if validators: return False` back in `_sequential_eligible`: AT-8 and AT-1(a) sequential cell red.
- M-6 [M12]. Remove resident completion from `execute_route`: AT-1 no-sink cells and AT-11 red.
- M-7 [M13]. Put `write_batches` on `_ObservedStaged`: AT-6 protocol cell red.
- M-8 [M14]. `post_scan_sink_kind` returns the proxy token: AT-3 red.
- M-9 [M15]. A second observer of a table adds to its folds: AT-1(c) split cell reports 14, not 7.
- M-10 [M16]. Drop `raw_is_null` from pending `parent_window_respected` state: AT-7 child-first cell red.
- M-11 [M9]. One pending child per parent key instead of a list: AT-7 duplicate-key cell red.
- M-12. `validation_needs_resident` returns `None` for a callable: AT-2 red.
- M-13. `_feed` after the verdict returns silently: AT-6 red.
- M-14. `execute_route` replaces `ctx.sink` but keeps the old `OutputPublish`: AT-13 red.
- M-15. The proxy's `write_batches` feeds nothing for an empty iterator: AT-14 red.
- M-16. The cursor skips the leftover-rows check: AT-15 long-source cell red.
- M-17. The out-of-core rewrite tap is removed and the cursor re-reads `caller_sources`: AT-15 rotating cell red.
- M-18. `judged_run` reuses any bound session and never binds one: AT-11 direct-call cells red.
- M-19. `observed_commit` marks only `staged_tables()` complete: AT-6 four-member cell red.
- M-20. The no-sink out-of-core verdict moves after `seal_evidence`: AT-16 no-sink trace red.
- M-21. `validation_needs_resident` ignores quarantine: AT-19 red.
- M-22. `PhysicalPlanInputs.validators` left empty: AT-18 red.

## 9. Frozen contracts

- Route contract: validators no longer change a route, except under the two new codes. Breaking line in `changelog.d/expect-off-route-s3.md`; compatibility contract entry for the two retired codes and the two new route codes.
- Physical plan hash: unchanged for a fixed config (AT-12). The recorded route decision changes for configs with validators; goldens that record it are regenerated by name after the snapshot comparison.
- Output bytes: unchanged; only the route that writes them changes.
- `ValidationSession` loses `record_external_verdict` and `observe_pair` (pre-GA hard delete) and gains `expect_delivery`, `source_tap` and `tee_reader`. `decoy_engine.validators` does not gain `observe_sink`; it is an execution name (5.2). New execution names: `judged_run`, `observe_sink`, `validation_needs_resident`, `sink_shape`, `physical_validator_spec`.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | new messages name tables and codes only; seeded cell value asserted absent from error, record and logs | AT-1(c), AT-6 | M-13 |
| 2 | Cleanup missing on an exit path | verdict before the commit `try` and inside the cast-owner scope; spill deleted by the session `ExitStack` | AT-1(c), AT-16, AT-3 isolated row | M-1, M-20 |
| 3 | State machine and concurrency | one owner (`judged_run`), one judge (`close`), one time; feeding after the verdict refuses | AT-6, AT-11 | M-13, M-18 |
| 4 | Route parity and silent fallback | every routing read deleted; one `sink_shape`; sentry with exact allowlist; declines recorded before the byte estimate | AT-1(a), AT-2, AT-8 | M-5, M-12 |
| 5 | Referential integrity | keyed folds give the full-frame report on sequential and out-of-core for every FK shape | AT-7 | M-10, M-11 |
| 6 | Untrusted producer | a user sink is classified by shape and wrapped; an expected table written around the proxy refuses | AT-6, AT-13 | M-3, M-7, M-19 |
| 7 | Check then use (TOCTOU) on a path | the source is captured at the mask step, never re-read; the spill path is session-owned and created and read by the same session | AT-15 | M-17 |
| 8 | Weak tests and overclaimed evidence | exact counts and indices; per-cell before and after recorded; RSS and `tracemalloc` measured | AT-1, AT-4, AT-5 | M-2, M-4, M-9 |
| 9 | Behavior-preserving refactor drift | deleting the out-of-core collector keeps the report, including for a direct caller | AT-7, AT-11 | M-6, M-18 |
| 10 | Frozen contract drift | retired codes tombstoned; hash pinned unchanged; Breaking line | AT-9, AT-12, AT-18 | M-8, M-22 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| Fail-open deferral (section 3a) | yes | no owner tokens remain; the direct caller owns its own session; AT-11 |
| No exception context in output | yes | AT-6 asserts no cause or context |
| Normalized guard scanners | yes | the sentry walks the AST of every module under `execution/` |
| No reaching into private modules | yes | execution imports only `decoy_engine.validators` public names |
| No hidden CI failures | yes | AT-5 carries the `perf` marker; result in the PR |
| No raised caps | yes | no module over 600 grows (5.8); module-size sentry |

## 11. Enumerations

### 11.1 Exit paths

- Pass: `close` at commit returns; `sink.commit()` runs (`execution/_publication_observer.py:145`).
- Fail with a sink: `ValidatorFailedError` from `close` at `execution/_publication_observer.py:142`; route unwind aborts. On out-of-core this is after `seal_evidence` (`out_of_core/_runner.py:360`) and inside the cast-owner scope, which discards the seal.
- Fail without a sink: `judge_resident` or `complete_resident_validation` raises before a seal or a return (`execution/_pipeline_route_dispatch.py:99`).
- Refusal at commit: a non-proxy sink while a session is bound; an expected table unfed.
- Refusal: `validator_table_not_observed`, `validator_source_pairing_mismatch`, `validator_key_state_over_budget`, `validator_rows_after_verdict`.
- Exception inside the run: bind scope exits without `close`; the sink aborts; the spill is deleted.

### 11.2 Routes

- Auto-chunk streamed (`execution/_chunked_output_sink.py:161`).
- Sequential with transactional sink, with callable sink, without sink (`execution/_sequential.py:625`).
- Out-of-core with and without sink, through the pipeline and by direct call (`execution/out_of_core/_runner.py:111`, `:362`).
- Multi-table split with sink (`execution/_pipeline_multi_table.py:306`).
- Standalone physical mask plan (`execution/physical/_compiler.py:439`).
- Resident, unified, mixed and physical routes: S2, unchanged.

### 11.3 FK shapes

- Single and composite FK.
- Nullable FK and orphan policies that null keys.
- Two parents and self-reference.
- Child-first order and duplicate parent keys (AT-7 named cells).

### 11.4 Fields

- `validators` entries and their `columns`, `min_rows`, `pattern` parameters.
- `quarantine.enabled`.
- Sink shape (`sink_shape`: callable, partial, staged, transactional).
- `caller_sources` entry kind (`pa.Table`, `LazySource`, absent with a loader), and loader-only `resolved_sources`.

### 11.5 Output surfaces

- `ValidatorFailedError` and its value-free report.
- `quality_metrics["validation"]` as stamped by S2.
- Route reason codes (two new, one retired), one new runtime code, one retired runtime code.
- The recorded route decision in the physical plan; the plan hash (unchanged).

## 12. Slices

### S3 STREAMED-ROUTES

Steps, in order (tests first, red before code):

1. On the merged #812 head, confirm:
   - the S2 end state of section 1;
   - how the pipeline passes config to `run_fk_out_of_core` (identity or copy);
   - the delivery-set source per route;
   - the mask-step batch iterator line in `_pipeline_generate_mask.py`;
   - whether the stream driver can apply its reorder permutation to the spill;
   - the `S3_PENDING` count.
2. Write AT-1 to AT-19 and record which cells fail before S3.
3. Move `sink_shape` to `_transactional_sink.py`; add `execution/_validated_sink.py` (`judged_run`, proxy, `validation_needs_resident`) and `validators/_source_cursor.py`; `post_scan_sink_kind` unwraps.
4. `execute_route` and `run_fk_out_of_core` enter `judged_run`; the new `OutputPublish` with the proxy; `expect_delivery`; `observed_commit` marks and closes; `complete_resident_validation` honors `close_attempted`; `_feed` refuses after the verdict; the callable delivery.
5. Taps at each site (5.4), `tee_reader` and `compose_tees`; the out-of-core verdict order inside the cast-owner scope.
6. Delete every routing read (5.6) and the out-of-core collector (5.1); `physical_validator_spec`; delete `S3_PENDING` and set the allowlist.
7. Retire the codes; changelog and compatibility contract.
8. Run M-1 to M-22; run AT-5 on the Dell.

Files and budgets. Module cap: goal 600, hard max 700, enforced by `tests/sentry/test_module_size.py`. The changed-source budget for the slice is about 800 lines; counts are at `029f1b378`.

| File | Now | After |
|---|---|---|
| `execution/_validated_sink.py` | new | about 180 |
| `validators/_source_cursor.py` | new | about 120 |
| `validators/_session.py` | 387 | about 395 (external verdict out; expected set, tap and tee in) |
| `execution/_transactional_sink.py` | 598 | about 620 (census entry with ceiling) |
| `execution/_sequential.py` | 680 | about 662 (classifier out) |
| `execution/_pipeline_route_dispatch.py` | 278 | about 330 |
| `execution/_publication_observer.py` | 202 | about 212 |
| `config/_post_scan.py` | 249 | about 260 |
| `execution/_pipeline_routing.py` | 566 | about 540 |
| `execution/_pipeline_routing_signals.py` | 613 | about 605 |
| `execution/_pipeline_generate_mask.py` | 414 | about 420 (tap) |
| `execution/_chunked_output_sink.py` | 600 | 598 |
| `execution/_pipeline_multi_table.py` | 465 | 464 |
| `execution/_pipeline_context.py` | 599 | about 592 |
| `execution/out_of_core/_validate_batch.py` | 387 | deleted |
| `execution/out_of_core/_rewrite_pass.py`, `_stream_driver.py`, `_runner.py` | 392, 583, 393 | about the same: hooks out, taps and `judged_run` in |
| `execution/physical/_snapshot.py`, `_inputs.py`, `_live_inputs.py`, `_compiler.py`, `_reasons.py` | 285, 377, 179, 451, as measured | each a few lines either way |
| `capacity.py`, `_job_estimate.py`, `pipeline/_lazy_input.py`, `_transforms_admission.py`, `_transforms_prepare.py`, `_unified_slice.py` | as measured | each a few fewer |
| `reasons/route/_part1.py`, `_retired.py`; `reasons/runtime/_part2.py`, `_part3.py` | 323, 20, 576, 565 | moves of a few lines |
| `tests/sentry/test_validators_do_not_route.py` | 243 | about 160 |

About +450 and -650 of source.

Public names added: `judged_run`, `observe_sink`, `validation_needs_resident`, `sink_shape`, `physical_validator_spec` (execution); `ValidationSession.expect_delivery`, `source_tap`, `tee_reader`. Removed: `ValidationSession.record_external_verdict`, `ValidationSession.observe_pair`.

Test depth: T0 per edit; T1 impact selection per commit (validators, execution routing, out-of-core, physical, post-scan, declared casting, the sentries); T2 on the exact head with AT-1, AT-6, AT-8, AT-11, AT-15, AT-16 and the mutations. Full suite: yes, once on the final head, because S3 changes a frozen contract (route contract), moves and deletes tests (`tests/parity/test_phase_d_d3a_validators_ooc.py` and the collector's tests, whose NaN fixture moves to AT-17), and touches the physical plan record (`testing.md` escalation triggers). It diffs against the saved main baseline.

### Dependencies and order

1. PR #812 (S2) merges first, with its three fixes (section 1).
2. S3 builds on the merged head. It touches no generation file except the mask-step tap in `_pipeline_generate_mask.py`, which GEN-STREAM-ALL S1b and S2 and GEN-NONFAKER-DRAWS S3a do not edit. AT-1's mixed-route cell uses whatever generation route main has.
3. S4 follows S3; its CLI half waits for an engine release with S1 to S3.

## 13. S4 outline

- Engine: `finish` emits the `leak_check_column_not_checked` `QualityWarning` for a skipped column that `columns:` names (about +15); rows in `docs/qa/14-casting-validators-quarantine.md` and `docs/qa/15-execution-routes-native.md`; the paragraph at `docs/strategies.md:2343`; the compatibility contract entry. Test V10.
- CLI, after the engine pin: a `Checks` fact on the run card and a `validation` member in `--json` on success and failure; `decoy validate` warns when `expect leak_check` names a `keep` column through `plan_scope`; JSON shape snapshot; the expect section of the language guide. Tests V11, V12.
- OWNER CALL (from the master plan, carried): the card wording `Checks  N passed` / `Checks  1 failed: <check> <table.column>`. Default: as written in the master plan.

## 14. Pre-mortem

- A sink route commits before every table is written (a future route). The feed after the verdict refuses with `validator_rows_after_verdict` instead of passing silently, and AT-6 pins it.
- The proxy hides an attribute a route reads by `hasattr`. `__getattr__` forwards anything the inner sink has; AT-3 runs the two real wrapped sinks end to end.
- The stream driver cannot expose its reorder permutation. Paired checks on that driver then stay resident under `validators_need_resident_rows`; step 1 records it, and a follow-up row can add the permutation.
- The spill fills the temp disk on a very wide paired table. It holds only the paired columns and is charged to the route's temp-disk budget, so the run refuses through the existing disk budget instead of failing mid-write.
- A direct `run_fk_out_of_core` caller passes a config copy, so `judged_run` binds a second session inside a pipeline run. Step 1 checks; the config-hash comparison is the fallback, and AT-11 covers both entry points.
- The route-decision change moves physical goldens outside the impact selection. The full suite on the final head catches them; each is regenerated by name after the fixed-snapshot comparison.
- Removing the out-of-core collector loses a check it made that the session lacks. AT-7 and AT-11 compare the out-of-core report with full frame for every validator in the catalog; any gap is a stop.
- S2 merges without the ambient-session fix. Step 1 checks it; AT-10 fails until it lands, and S3 does not build on top of it.
