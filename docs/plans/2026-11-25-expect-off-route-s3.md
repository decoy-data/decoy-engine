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
- The standalone shadow coordinator judges its own result unless `ShadowContext.validation_owner` names an owner (`execution/physical/_shadow_generation.py:285`).

What still forces a route: validators send every streamed and bounded route to resident. The reads are listed in `S3_PENDING` (`tests/sentry/test_validators_do_not_route.py:32-92`), 60 entries in 18 modules. The out-of-core route keeps a second validator engine (`execution/out_of_core/_validate_batch.py`, 387 lines) that records its verdict on the session with an owner token (`_validate_batch.py:387`).

## 2. Guarantee and non-goals

Guarantee:

- G1. A config with validators takes the same route, route reason and per-column backends as the same config without validators, on every route, with one exception: a plain callable sink on the sequential route goes resident with the new route code `validators_need_transactional_sink`.
- G2. On a streamed route, no row reaches a committed sink before the run's verdict. A failing verdict raises `ValidatorFailedError` before `sink.commit()`; the failure is recorded as a validation failure, never as a COMMIT failure.
- G3. The streamed report equals the full-frame report for the same data (findings, counts, capped indices).
- G4. Validator state on a streamed route stays bounded: at most one source batch per paired table plus the fold state, under the session's key-state ceiling.
- G5. No error or log text carries a cell value.

Non-goals:

- No run-card fact, CLI JSON member or `leak_check_column_not_checked` warning (S4).
- No streaming for quarantine, post-validation, fidelity report or declared casting: those keep their own resident reasons (`execution/_chunked_output_sink.py:110-122`).
- No change to any verdict rule inside a validator module.

## 3. Established solutions

- Validate before publish, publish atomically: the two-phase write the engine already uses (`TransactionalSink` stage, then `commit`). S3 puts the verdict between them, as a database runs deferred constraints at COMMIT (PostgreSQL `SET CONSTRAINTS ... DEFERRED`: checks run at commit time, and a failure rolls back).
- Observe writes through a proxy: the decorator pattern (GoF), as `io.BufferedWriter` wraps a raw stream. The proxy keeps the wrapped object's shape so protocol checks still see the real capabilities.
- Streaming checks with order-free folds: S1 and S2 already use mergeable aggregates (the "fold" in streaming systems such as Apache Beam `CombineFn`: `add_input`, `extract_output`).
- No new algorithm is introduced.

## 4. Reuse inventory

| Need | Reuse | Where |
|---|---|---|
| The judge | `ValidationSession.close` | `validators/_session.py:271` |
| Feed a written batch | `observe_published` | `validators/_session.py:172` |
| Feed a resident table against a lazy source | `observe_source_batches` | `validators/_session.py:195` |
| Resident completion choke | `complete_resident_validation` | `execution/_pipeline_route_dispatch.py:76` |
| Commit choke | `observed_commit` | `execution/_publication_observer.py:132` |
| Sink identity | `post_scan_sink_kind` | `config/_post_scan.py:211` |
| Loader tee | `tee_reader` (post-scan) | `execution/pipeline/_post_scan.py:537` |
| Runtime codes | `VALIDATOR_TABLE_NOT_OBSERVED`, `VALIDATOR_SOURCE_PAIRING_MISMATCH`, `VALIDATOR_KEY_STATE_OVER_BUDGET` | `reasons/runtime/_part3.py:99-102` |
| Retired route codes | `reasons/route/_retired.py` | 20 lines today |
| Routing sentry | `S3_PENDING` and `_scan` | `tests/sentry/test_validators_do_not_route.py:32`, `:197` |

## 5. Design

### 5.1 One feed point per route

S3 adds no route-specific feed. A table reaches the session at exactly one of two choke points:

- A table written to a sink is fed by the sink proxy (`validators/_sink.py`, section 5.2), batch by batch, in row order.
- A table returned resident is fed by `complete_resident_validation` (`execution/_pipeline_route_dispatch.py:76`), as in S2.

The out-of-core `_delivered` hooks (`execution/out_of_core/_rewrite_pass.py:198-200`, `execution/out_of_core/_stream_driver.py:431-433`) are deleted, with the `validators` parameters at `_rewrite_pass.py:93` and `_stream_driver.py:154`, the collector at `out_of_core/_runner.py:216`, the forward at `:322`, `finish_validation` at `:359`, and the whole of `_validate_batch.py`. With a sink, the proxy feeds the rendered batches the sink receives. Without a sink, the resident choke feeds the assembled tables. `record_external_verdict` and the `_external` set in the session lose their only caller and are deleted.

Deviation from the master plan: section 6 of the master plan names `observe_pair` at `_rewrite_pass.py:240` and `_stream_driver.py:374`. The stream driver's phase 3 has no source batch in scope ("no source read", `_stream_driver.py:430`), and the rewrite pass's raw batch precedes declared rendering (`_rewrite_pass.py:255`), so feeding there would judge bytes the sink does not receive. One feed at the sink or the resident choke judges the delivered bytes on every route. `observe_pair` is deleted if no caller remains.

### 5.2 Capability-preserving sink proxy

New `validators/_sink.py` (about 150 lines). `observe_sink(sink, session)` returns one of three classes, chosen by the inner sink's shape:

- `_ObservedCallable`: the sink is a plain `Callable[[str, pa.Table], None]`. `__call__` feeds, then forwards.
- `_ObservedStaged`: the sink has `write`, `commit` and `abort` but no `write_batches`. `write` feeds, then forwards. `commit` and `abort` forward only.
- `_ObservedTransactional`: the sink satisfies `TransactionalSink` (four members). `write` and `write_batches` feed, then forward; `write_batches` feeds each batch as the inner sink pulls it, so nothing is buffered.

Each class carries a read-only `inner_sink`. `__getattr__` forwards an attribute only when the inner sink has it, so helpers such as `staged_components`, staged openers and publication evidence still work, and no protocol member is invented. `_ObservedStaged` has no `write_batches`, so `isinstance(proxy, TransactionalSink)` stays false for it.

`execute_route` wraps the sink once, after the session binds and before any executor runs, only when a session is bound. Most streamed writes do not use `ctx.sink`: they use `ctx.publish.active_sink`, and `OutputPublish` is built with the raw sink at `execution/_pipeline_context.py:267` (writers at `_pipeline_generate_mask.py:251`, `:286`, `_pipeline_mixed_route.py:224`, `:241`, `_pipeline_full_frame.py:303`; commit at `_chunked_output_sink.py:161`). So `execute_route` rebuilds the context once with `dataclasses.replace(ctx, sink=proxy, publish=replace(ctx.publish, sink=proxy))`, and both handles point at the proxy. The sequential route's `_CallableSinkAdapter` (`_sequential.py:382-390`) wraps whatever sink it is given, so it wraps the proxy. The edit lives in `_pipeline_route_dispatch.py`; `_pipeline_context.py` (599) and `_chunked_output_sink.py` (600) do not grow. Routing has already decided on the unwrapped sink.

While a session is bound, `observed_commit` refuses a sink that is not a proxy (it has no `inner_sink`) with `validator_table_not_observed` and a fixed message, before any commit. A future write handle that bypasses the proxy therefore fails closed, whatever the sink type.

A table with no rows is written as `write_batches(table, iter(()), schema=...)` (`_chunked_output_sink.py:591`). When no batch arrives, `_ObservedTransactional.write_batches` feeds `schema.empty_table()` once, so the table is fed and complete.

`post_scan_sink_kind` (`config/_post_scan.py:211`) follows `inner_sink` (with a seen-set against cycles) before it returns the class token. Every consumer that names a sink kind already calls it: `post_scan_sink_refusal` (`config/_post_scan.py:237`), the two readability calls in `pipeline/_post_scan.py`, and `physical/_snapshot.py`.

### 5.3 The verdict at commit

`observed_commit` (`execution/_publication_observer.py:132`) calls `active_validation_session().close()` after `gate.before_commit(sink)` (`:141-142`) and before `evidence_of(sink)` (`:143`). A `ValidatorFailedError` therefore leaves before the commit `try`, so no COMMIT failure is captured, and the existing unwinds abort the sink: `OutputPublish.__exit__` (`execution/_chunked_output_sink.py:165`), the sequential executor's failure path, and the out-of-core runner's.

Before `close`, `observed_commit` marks each table in the sink's staged set complete (`staged_tables()`, the read-back `ParquetTransactionalSink` gives the post-scan gate, `execution/_transactional_sink.py:427`). A table written around the proxy is then complete but unfed, and `close` refuses it with `validator_table_not_observed`. A sink without `staged_tables` is judged on what the proxy saw, which is every write that passed through it.

A commit is the run's last action on every sink route (`execution/_chunked_output_sink.py:128-134`, and one `observed_commit` call per route: `_chunked_output_sink.py:161`, `_sequential.py:625`, `out_of_core/_runner.py:362`). Every written table has been fed by then, so closing at commit judges the whole run. A table fed after the verdict is a wiring bug: `_feed` (`validators/_session.py:311`) raises `ValidatorStateError` with the new runtime code `validator_rows_after_verdict` and a fixed message naming the table, in place of today's bare `ValueError`.

After the executor returns, `complete_resident_validation` sees `close_attempted`. It refuses with `validator_table_not_observed` if a resident output table was never fed, and otherwise returns the stored report without a second judgement.

### 5.4 Sources for paired checks on streamed routes

A paired check (for example `leak_check`) compares an output batch with the source rows at the same positions. On a streamed route the session gets those rows from one of two places:

- New `validators/_source_cursor.py` (about 100 lines): `SourceCursor(open_batches, columns)` where `open_batches` is a `Callable[[], Iterator[pa.RecordBatch]]`. `take(n)` returns the next `n` source rows, holding at most one source batch and its unread remainder. `exhausted()` reads ahead and reports whether any source row is left. The session calls `take` from `_source_rows` for every paired table on a streamed route. `execute_route` passes one opener per paired table in `ctx.caller_sources`: for a `LazySource` it is the source's `open_batches` (which runs the identity check against the routing snapshot at exhaustion, where the reader has one; Parquet `iter_batches` at `profile/_readers.py:233` has none), and for a resident `pa.Table` it is `table.select(columns).to_batches`. Today a resident source with a streamed output reaches `leak_check.add` with no source and raises a bare `ValueError` (`validators/_leak_check.py:141`); the cursor closes that gap. At `finish`, a cursor with rows left raises `validator_source_pairing_mismatch`, so a source longer than the output is caught as well as a shorter one. The cursor opens lazily on the first `take`, so an unpaired run never reads a source twice. The validators package does not import `LazySource`; it receives callables (dependency points inward).
- `ValidationSession.tee_reader()` returns a `Callable[[str, pa.Table], None]` for the sequential loader. It keeps a projection of the paired columns for a paired table and drops it when the published rows reach the source's row count. `execute_sequential_route` (`execution/_pipeline_route_dispatch.py:160`) composes it with the post-scan tee at `:167` through a small `compose_tees` helper in the same module. `_sequential.py` (680 lines) is not edited.

A count mismatch between source rows and published rows keeps today's refusal, `validator_source_pairing_mismatch` (`validators/_session.py:348`).

### 5.5 Callable sinks need resident

A plain callable sink delivers on every call and has no commit, so rows would leave before the verdict. New public helper `validation_needs_resident(config, sink) -> bool` in `validators/_sink.py`: true when the config has validators and the sink is callable without `commit`. Only `_sequential_eligible` (`execution/_pipeline_routing.py:97`) admits a non-transactional sink; there it replaces the validator decline at `:144` and declines with the new route code `validators_need_transactional_sink`. The chunked lane already sends any non-`TransactionalSink` resident (`execution/_chunked_output_sink.py:101`). The builder confirms in step 1 that the out-of-core runner accepts only `TransactionalSink`; if it accepts more, the same helper guards it.

S2 adds no callable delivery in `execute_route` (`_pipeline_route_dispatch.py:106-157`). Step 1 traces where the resident route calls a callable sink today. The rule S3 enforces: the callable is called only after `close` has returned. If the resident path calls it earlier, S3 moves that call after `complete_resident_validation` in `execute_route`. The out-of-core runner types its sink as `TransactionalSink | None` (`out_of_core/_runner.py:117`); an admission test pins that a callable sink never reaches it.

### 5.6 Delete every routing read

Every entry in `S3_PENDING` is deleted at its source:

- Route choice: `decide_output_mode` loses `:114-115`; `_pipeline_routing.py` loses the `_sequential_eligible` decline (`:144`), `bounded_admission`'s validator parameter, `validators_ooc_ready` (`:338-349`) and the D3a lift in `decide_execution_route`; `_pipeline_routing_signals.resolve_execution_route` stops forwarding; `_pipeline_multi_table._job_gates_hold` loses `:151`.
- Mirrors of the decline: `_job_estimate._estimate`, `capacity.estimate_job_capacity`, `pipeline/_lazy_input._relationship_job_is_bounded`, `_transforms_admission.check_rejections_before_preparation`, `_transforms_prepare.prepare_transform_sources`, `_pipeline_context.build_run_context` and `decide_route`, `_unified_slice._execute_admitted`.
- Physical plan replay: `physical/_compiler.layer1_route` and `out_of_core_not_ready_reason`, `physical/_inputs.PhysicalPlanInputs.validators`, `physical/_live_inputs.build_live_physical_plan_inputs`, and `physical/_snapshot.capture_physical_plan_inputs` (`:141-196`, `:272`). The validator list leaves the physical plan inputs, so the plan hash no longer covers it.
- Out-of-core: section 5.1.

`S3_PENDING` is then empty and is deleted. The sentry keeps an allowlist of exact `(module, function, public name)` identities for lifecycle wiring only: `bind_validation_session`, `observe_sink` and `complete_resident_validation` in `execute_route`; `active_validation_session` in `observed_commit` and `execute_sequential_route`; `validation_needs_resident` in `_sequential_eligible`; and the S2 callers that remain: `_pipeline_finalize.py:417`, `:421`, `:432`, `_pipeline_mixed_route.py:65`, `:294`, and `physical/_shadow_generation.py:269`, `:276`, `:285`, `:292`. S3 adds caller tracking for the public helpers to the scan, so this list is enforced, not decorative. The stale comment at `_pipeline_mixed_route.py:294-296` ("streamed output declines validators") is corrected. Any other read of the `validators` key or a `validators*` name under `execution/` fails.

### 5.7 Reason codes

- New route code `validators_need_transactional_sink` (`reasons/route/`).
- New runtime code `validator_rows_after_verdict` (`reasons/runtime/_part3.py`).
- Retired: `route.validators_present` (`reasons/route/_part1.py:306`) moves to `reasons/route/_retired.py`. `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`) is retired the same way; if the runtime family has no retired module, S3 adds `reasons/runtime/_retired.py` on the route pattern.

### 5.8 Placement

| New or changed item | Directory | CODEMAP row | Why here |
|---|---|---|---|
| `_sink.py` | `src/decoy_engine/validators/` | "Job-level validator framework" (added in S1) | the proxy observes for the session; execution only wraps |
| `_source_cursor.py` | `src/decoy_engine/validators/` | same | the session's source reads; takes callables, imports no execution module |
| `compose_tees` | `execution/_pipeline_route_dispatch.py` | route dispatch | the one place that builds the sequential loader |
| tests | `tests/unit/validators/`, `tests/unit/execution/judgement/`, `tests/sentry/` | per the S1 row | as S1 and S2 |

No module over 600 lines grows: `_sequential.py` (680), `_chunked_output_sink.py` (600), `_pipeline_routing_signals.py` (613) and `_pipeline_context.py` (599) only lose lines.

### 5.9 Design notes

- One feed point per delivery shape (sink proxy or resident choke), one judge (`close`), one judgement time for sink routes (commit). Each is a choke point with a guard test and a mutation (section 8).
- Routing knows nothing about validators, except the one public question `validation_needs_resident`.
- Dependency direction: `validators/` takes the sink, source openers and budget as arguments and imports no execution module.
- Pre-GA hard delete: the out-of-core collector, `record_external_verdict`, `S3_PENDING` and the retired codes go in this slice; nothing is kept for compatibility.

## 6. Behavior and failure modes

| Case | Behavior |
|---|---|
| Auto-chunk streamed with a `TransactionalSink`, validators pass | Route `streamed`, same reason as without validators; one commit. |
| Same, a validator fails | `ValidatorFailedError` before `sink.commit()`; abort runs; staging is empty; no COMMIT failure record. |
| Sequential FK with a plain callable sink | Resident, `validators_need_transactional_sink`; callable called once per table after a pass, zero times after a fail. |
| Sequential FK with a transactional sink | Sequential route; verdict at commit. |
| Out-of-core with a sink | Out-of-core route; proxy feeds rendered batches; verdict at commit. |
| Out-of-core without a sink | Out-of-core route; resident choke feeds the returned tables. |
| Paired check, lazy source | Source cursor reads the paired columns once, one batch at a time. |
| Source rows differ from published rows | `validator_source_pairing_mismatch`, nothing committed. |
| Rows fed after the verdict | `validator_rows_after_verdict`, fixed message. |
| A write handle holds the raw sink | `observed_commit` refuses a non-proxy sink while a session is bound. |
| Zero-row table on a streamed route | The proxy feeds an empty table once; the table is judged. |
| Resident `pa.Table` source, streamed output, paired check | The cursor reads the table's batches; same report as full frame. |
| Source longer than the output | `validator_source_pairing_mismatch` at `finish`. |
| A sink route writes through a seam that skips the proxy | `observed_commit` marks every table in the sink's staged set complete, so `close` refuses the unfed table with `validator_table_not_observed`. |
| Keyed state passes the ceiling | `validator_key_state_over_budget` before the next scoped write; nothing committed. |
| Nested run with no validators inside a bound run | The inner commit sees no session (S2 end state) and does not close the outer session. |

## 7. Acceptance tests

Master plan numbers in brackets. Each uses a reject-all `regex_match` (`pattern: "^$"`) where it needs a failure. Each fails before S3 unless marked as a control.

- AT-1 [V4 streamed rows]. For auto-chunk streamed with `ParquetTransactionalSink` (120k rows), sequential FK with a transactional sink and with no sink, out-of-core FK with and without a sink, multi-table split with a sink, and generation with a sink (the mixed route's streamed generate writes, `_pipeline_mixed_route.py:224`; `run_generation` is reached only from `generation/_plan_entry.py` and is out of scope): (a) the route label, route reason and per-column backends equal the same config without validators; (b) a passing validator gives `passed` results; (c) a failing validator raises `ValidatorFailedError`, the inner `commit` is never called, staging is empty, and the failure record does not say COMMIT. Fails before: (a) fails on every row.
- AT-2 [V4 callable row]. Sequential FK with a plain callable: the route is resident with `validators_need_transactional_sink`; a failure calls the callable zero times and raises; a pass calls it exactly once per table, after `close`. An admission cell pins that the out-of-core runner never receives a callable sink.
- AT-3 [V4 readability rows]. `ParquetTransactionalSink` and an isolated `StagingSink`, each wrapped, with `post_scan.integrity`: no `POST_SCAN_INTEGRITY_SINK_UNREADABLE`; the integrity report shows the gate ran; the physical snapshot holds the inner sink kind. The isolated row runs pass and fail and proves `StagingSink.commit()` and `.abort()` stay no-ops.
- AT-4 [V5]. 120k rows with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`: fails on the streamed route with the full-frame report, from a resident `pa.Table` source and from a lazy Parquet source; with `hash` it passes. An instrumented counter shows the cursor never holds more than one source batch per table. A sequential run with empty `caller_sources` and a counting `source_loader` loads each table once and gives the same report.
- AT-5 [V6, perf, Dell vm-run]. 2M rows streamed, `leak_check` and `regex_match`, every row failing: `retained_bytes()` under `2 * FINDING_INDEX_CAP * 8` plus 64 KiB plus one source batch projection; peak RSS within 64 MiB of the same run without validators; wall time recorded.
- AT-6 [V7]. A test route that writes to the inner sink around the proxy refuses before commit with `validator_table_not_observed`, nothing committed, no exception context. A three-member sink is wrapped and `isinstance(proxy, TransactionalSink)` is false; a four-member sink stays true. Rows fed after `close` raise `validator_rows_after_verdict`.
- AT-7 [V8]. `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on sequential and out-of-core give the full-frame report for single, composite, nullable, two-parent and self-reference FKs. Out-of-core with an orphan policy that nulls orphan keys gives a `no_orphan_children` finding, not an `fk_intact` break. A key-state budget forced to 1 KiB refuses before the first scoped write.
- AT-8 [V9]. The routing sentry passes on the tree with `S3_PENDING` deleted; it fails on each seeded spelling (`config.get("validators")`, `if validators:`, a `validators_ooc_ready` name) in a copy of `_pipeline_routing.py`, and on a call to `validation_needs_resident` from an unlisted function.
- AT-9 [V14]. `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as retired; nothing in `src/` emits them (registry sentry).
- AT-10. A run with no validators nested inside a bound run commits without closing or feeding the outer session. Control after the S2 fix.
- AT-11 [V15f]. Out-of-core through `run_pipeline` with a failing validator raises `ValidatorFailedError`; the session holds no external verdict (the attribute no longer exists); every delivered table was fed and judged.
- AT-12. The physical plan for a config with validators records the same route decision as the same config without them, and `PhysicalPlanInputs` has no `validators` field. The hash still differs, because `compute_plan_hash` hashes the whole config (`execution/physical/_inputs.py:87-95`, `:324`); that is intended.
- AT-13. Every streamed writer reaches the proxy: on the auto-chunk, split and mixed routes, a spy shows each batch fed, and a test seam that writes through the unwrapped `publish.active_sink` makes `observed_commit` refuse with `validator_table_not_observed` before commit.
- AT-14. A zero-row table passes and a zero-row table under a reject-all check on a non-empty sibling still fails, on the streamed, sequential and out-of-core routes.
- AT-15 [V5 extension]. A resident `pa.Table` source with streamed output and paired `leak_check` gives the full-frame report; a source one row longer than the output refuses with `validator_source_pairing_mismatch`.
- AT-16. Out-of-core with declared casting and a failing validator: the verdict now runs at commit, after `seal_evidence` (`out_of_core/_runner.py:360`); the run raises, nothing is published, and the sealed evidence is not reported as a publication.

## 8. Named mutations

Master plan numbers in brackets. Each must turn the named test red on the final head.

- M-1 [M3]. `observed_commit` commits before `close`: AT-1(c) red.
- M-2 [M4]. The source cursor restarts from row 0 for each `take`: AT-4 red.
- M-3 [M5]. `write_batches` forwards without feeding: AT-6 and AT-1 streamed rows red.
- M-4 [M8]. The cursor reads the whole lazy source on open: AT-4 counter red.
- M-5 [M10]. `if validators: return False` back in `_sequential_eligible`: AT-8 and AT-1 sequential row red.
- M-6 [M12]. Remove resident completion from `execute_route`: AT-1 no-sink rows and AT-11 red.
- M-7 [M13]. Put `write_batches` on `_ObservedStaged`: AT-6 protocol cell red.
- M-8 [M14]. `post_scan_sink_kind` returns the proxy token: AT-3 red.
- M-9 [M15]. A second observer of a table adds to its folds: AT-1 split row reports doubled counts.
- M-10 [M16]. Drop `raw_is_null` from pending `parent_window_respected` state: AT-7 child-first cell red.
- M-11 [M9]. One pending child per parent key instead of a list: AT-7 duplicate-key cell red.
- M-12. `validation_needs_resident` returns false for a callable: AT-2 red.
- M-13. `_feed` after the verdict returns silently: AT-6 red.
- M-14. `execute_route` replaces `ctx.sink` but not `ctx.publish`: AT-13 red.
- M-15. The proxy's `write_batches` feeds nothing for an empty iterator: AT-14 red.
- M-16. The cursor skips the exhaustion check: AT-15 long-source cell red.
- M-17. The opener for a resident `pa.Table` source is left out: AT-15 red.

## 9. Frozen contracts

- Route contract: validators no longer change a route. Breaking line in `changelog.d/expect-off-route-s3.md`; compatibility contract entry for the two retired codes and the new route code.
- Physical plan hash: the validator list leaves the inputs (AT-12). Any golden hash that moves is regenerated by name in the PR; this is an escalation trigger (frozen contract) for a full suite.
- Output bytes: unchanged; only the route that writes them changes.
- `ValidationSession` loses `record_external_verdict` and `observe_pair` (pre-GA hard delete); it gains `tee_reader`. `decoy_engine.validators` gains `observe_sink` (already planned in S1's list) and `validation_needs_resident`.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | new messages name tables and codes only; `ValidatorFailedError` keeps S1's value-free report text | AT-6, AT-1(c) | M-13 |
| 2 | Cleanup missing on an exit path | the verdict raises before the commit `try`, so each route's existing abort runs; the cursor closes its reader on finish and on unwind | AT-1(c), AT-3 isolated row | M-1 |
| 3 | State machine and concurrency | one judge (`close`), one time (commit or scope exit); feeding after the verdict refuses | AT-6, AT-11 | M-13, M-6 |
| 4 | Route parity and silent fallback | every routing read deleted; sentry with exact allowlist; same route with and without validators | AT-1(a), AT-8 | M-5 |
| 5 | Referential integrity | keyed folds give the full-frame report on sequential and out-of-core for every FK shape | AT-7 | M-10, M-11 |
| 6 | Untrusted producer | a user sink is wrapped by shape, never trusted to call back; a write around the proxy refuses | AT-6 | M-3, M-7 |
| 7 | Check then use (TOCTOU) on a path | N/A no filesystem path is checked then used; the cursor reads through the existing `LazySource` reader | none needed | N/A no path checks |
| 8 | Weak tests and overclaimed evidence | route asserted in every parity row; RSS on the Dell; counter on source reads | AT-4, AT-5 | M-2, M-4 |
| 9 | Behavior-preserving refactor drift | deleting the out-of-core collector keeps the full-frame report | AT-7, AT-11 | M-6 |
| 10 | Frozen contract drift | retired codes tombstoned; plan hash change stated; Breaking line | AT-9, AT-12 | M-8 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| Fail-open deferral (section 3a) | yes | no owner tokens remain for out-of-core; AT-11 |
| No exception context in output | yes | AT-6 asserts no cause or context |
| Normalized guard scanners | yes | the sentry walks the AST of every module under `execution/` |
| No reaching into private modules | yes | execution imports only `decoy_engine.validators` public names |
| No hidden CI failures | yes | AT-5 carries the `perf` marker; result in the PR |
| No raised caps | yes | no module over 600 grows (5.8) |

## 11. Enumerations

### 11.1 Exit paths

- Pass: `close` at commit returns; `sink.commit()` runs (`execution/_publication_observer.py:145`).
- Fail: `ValidatorFailedError` from `close` at `execution/_publication_observer.py:142`; route unwind aborts. On out-of-core this is now after `seal_evidence` (`out_of_core/_runner.py:360`) instead of before it (`finish_validation` at `:359` today); AT-16 covers it.
- Refusal at commit: a non-proxy sink while a session is bound.
- Refusal: `validator_table_not_observed`, `validator_source_pairing_mismatch`, `validator_key_state_over_budget`, `validator_rows_after_verdict`.
- No sink: resident choke `close` (`execution/_pipeline_route_dispatch.py:99`).
- Exception inside the run: bind scope exits without `close`; the sink aborts.

### 11.2 Routes

- Auto-chunk streamed (`execution/_chunked_output_sink.py:161`).
- Sequential with transactional sink, with callable sink, without sink (`execution/_sequential.py:625`).
- Out-of-core with and without sink (`execution/out_of_core/_runner.py:362`).
- Multi-table split with sink (`execution/_pipeline_multi_table.py:306`).
- Resident, unified, mixed and physical routes: S2, unchanged.

### 11.3 FK shapes

- Single and composite FK.
- Nullable FK and orphan policies that null keys.
- Two parents and self-reference.
- Child-first order (session unit test until GEN-PER-COLUMN S4).

### 11.4 Fields

- `validators` entries and their `columns`, `min_rows`, `pattern` parameters.
- Sink shape (callable, three-member, four-member).
- `caller_sources` entry kind (`pa.Table`, `LazySource`, absent with a loader).

### 11.5 Output surfaces

- `ValidatorFailedError` and its value-free report.
- `quality_metrics["validation"]` as stamped by S2.
- Route reason codes (one new, one retired) and one new runtime code.
- Physical plan hash.

## 12. Slices

### S3 STREAMED-ROUTES

Steps, in order (tests first, red before code):

1. Confirm the S2 end state of section 1 on the merged #812 head; confirm the out-of-core runner sink type and trace where the resident route calls a callable sink (5.5).
2. Write AT-1 to AT-16 and confirm the fail-before rows fail.
3. Add `validators/_sink.py` and `validators/_source_cursor.py`; `post_scan_sink_kind` unwraps; `execute_route` wraps and passes source openers.
4. `observed_commit` closes; `complete_resident_validation` honors `close_attempted`; `_feed` refuses after the verdict.
5. `tee_reader` on the session and `compose_tees` in `execute_sequential_route`.
6. Delete every routing read (5.6) and the out-of-core collector (5.1); add `validation_needs_resident` and the route code; delete `S3_PENDING` and set the allowlist.
7. Retire the two codes; changelog and compatibility contract.
8. Run M-1 to M-17; run AT-5 on the Dell.

Files and budgets (cap about 800 changed lines of source; current counts at `029f1b378`):

| File | Now | After |
|---|---|---|
| `validators/_sink.py` | new | about 150 |
| `validators/_source_cursor.py` | new | about 100 |
| `validators/_session.py` | 387 | about 380 (external verdict out; tee and cursor hook in) |
| `execution/_pipeline_route_dispatch.py` | 278 | about 320 |
| `execution/_publication_observer.py` | 202 | about 208 |
| `config/_post_scan.py` | 249 | about 260 |
| `execution/_pipeline_routing.py` | 566 | about 530 |
| `execution/_pipeline_routing_signals.py` | 613 | about 605 |
| `execution/_chunked_output_sink.py` | 600 | 598 |
| `execution/_pipeline_multi_table.py` | 465 | 464 |
| `execution/_pipeline_context.py` | 599 | about 592 |
| `execution/out_of_core/_validate_batch.py` | 387 | deleted |
| `execution/out_of_core/_rewrite_pass.py`, `_stream_driver.py`, `_runner.py` | 392, 583, 393 | each about 5 to 10 fewer |
| `execution/physical/_snapshot.py`, `_inputs.py`, `_live_inputs.py`, `_compiler.py` | 285, 377, 179, 451 | each a few fewer |
| `capacity.py`, `_job_estimate.py`, `pipeline/_lazy_input.py`, `_transforms_admission.py`, `_transforms_prepare.py`, `_unified_slice.py` | as measured | each a few fewer |
| `reasons/route/_part1.py`, `_retired.py`; `reasons/runtime/_part2.py`, `_part3.py` | 323, 20, 576, 565 | moves of a few lines |
| `tests/sentry/test_validators_do_not_route.py` | 243 | about 150 |

About +300 and -600 of source. A module-size test pins `_sequential.py`, `_chunked_output_sink.py`, `_pipeline_routing_signals.py` and `_pipeline_context.py` at or below their counts.

Public names added: `observe_sink`, `validation_needs_resident`, `ValidationSession.tee_reader`. Removed: `ValidationSession.record_external_verdict`, `ValidationSession.observe_pair` (if no caller remains).

Test depth: T0 per edit; T1 impact selection per commit (validators, execution routing, out-of-core, physical, post-scan, the sentries); T2 on the exact head with AT-1, AT-6, AT-8, AT-11 and the mutations. Full suite: yes, once on the final head, because S3 changes a frozen contract (route contract and physical plan hash), moves and deletes tests (`tests/parity/test_phase_d_d3a_validators_ooc.py` and the collector's tests), and touches serialization of the plan hash (`testing.md` escalation triggers). It diffs against the saved main baseline.

### Dependencies and order

1. PR #812 (S2) merges first, with its three fixes (section 1).
2. S3 builds on the merged head. It touches no generation file, so it does not interact with GEN-STREAM-ALL S1b or S2 or GEN-NONFAKER-DRAWS S3a. AT-1's generation-with-a-sink row uses whatever generation route main has.
3. S4 follows S3; its CLI half waits for an engine release with S1 to S3.

## 13. S4 outline

- Engine: `finish` emits the `leak_check_column_not_checked` `QualityWarning` for a skipped column that `columns:` names (about +15); rows in `docs/qa/14-casting-validators-quarantine.md` and `docs/qa/15-execution-routes-native.md`; the paragraph at `docs/strategies.md:2343`; the compatibility contract entry. Test V10.
- CLI, after the engine pin: a `Checks` fact on the run card and a `validation` member in `--json` on success and failure; `decoy validate` warns when `expect leak_check` names a `keep` column through `plan_scope`; JSON shape snapshot; the expect section of the language guide. Tests V11, V12.
- OWNER CALL (from the master plan, carried): the card wording `Checks  N passed` / `Checks  1 failed: <check> <table.column>`. Default: as written in the master plan.

## 14. Pre-mortem

- A sink route commits before every table is written (a future route). The feed after the verdict refuses with `validator_rows_after_verdict` instead of passing silently, and AT-6 pins it.
- The proxy hides an attribute a route reads by `hasattr`. `__getattr__` forwards anything the inner sink has; AT-3 runs the two real wrapped sinks end to end.
- A lazy source cannot project columns. The cursor still holds one batch; AT-4's counter bounds it.
- The plan-hash change moves physical goldens in tests outside the impact selection. The full suite on the final head catches them; each is regenerated by name.
- Removing the out-of-core collector loses a check it made that the session lacks. AT-7 and AT-11 compare the out-of-core report with full frame for every validator in the catalog; any gap is a stop.
- S2 merges without the ambient-session fix. Step 1 checks it; AT-10 fails until it lands, and S3 does not build on top of it.
