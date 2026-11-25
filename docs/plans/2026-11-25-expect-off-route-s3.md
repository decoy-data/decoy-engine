Status: plan

# EXPECT-OFF-ROUTE S3: streamed routes judge validators, and validators stop picking a route

Rules consulted: `/home/cam/dev-rules/00-universal.md`, `/home/cam/dev-rules/risk-and-exceptions.md`, `/home/cam/dev-rules/development-loop.md`, `/home/cam/dev-rules/cross-cutting-concerns.md` (choke point, guard, mutation), `/home/cam/dev-rules/testing.md` (Test depth), `/home/cam/dev-rules/workspace-and-vcs.md` (Commit messages), the plan contract and defect catalog (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`), and the row's master plan rev 7 on the PR #812 branch (`docs/plans/2026-11-22-expect-off-route.md`: section 3a invariant, section 5 design notes, section 6 slices, sections 9 and 10).

Row: EXPECT-OFF-ROUTE (validators stop forcing pandas). Repo: decoy-engine. Risk: R2 (publication order, fail-open class, route contract, physical plan hash). Anchor: PR #812 (S2) at `99d868347` plus the fixes in flight in its worktree for three findings: standalone shadow runs skip validators, the verdict is not enforced on scope exit, and an ambient session judges the wrong config. S3 builds on the end state those fixes intend (section 1). Line numbers are from `99d868347` and move with the merge.

This file plans S3 in full. S4 is an outline (section 13).

## 1. Frame and the S2 end state S3 assumes

After S2, every resident route is judged by one session (`validators/_session.py`), and the section 3a invariant holds: every delivered table is judged exactly once. S3 relies on these S2 facts. If #812 merges without one of them, S3 re-plans that step before it builds.
- `bind_validation_session` (`validators/_session.py:54`) binds the ContextVar for every run. A run whose config has no validators binds `None`, so a nested run never sees an outer run's session (the "ambient session" fix). At `99d868347` the no-validator branch still yields `None` without setting the ContextVar (`validators/_session.py:63-65`); the fix in flight must set it, and S3 does not start until it has (section 12, Dependencies).
- Leaving the bind scope normally calls `close()` unless a caller already did (`validators/_session.py:73`).
- `close()` (`validators/_session.py:271`) is the one judge. It refuses a table that is complete or deferred but never fed (`validator_table_not_observed`), and it raises `ValidatorFailedError` for a finding on a table no judge settled.
- The standalone shadow coordinator judges its own result unless `ShadowContext.validation_owner` names an owner (`execution/physical/_shadow_generation.py:285`). The standalone coordinator reads `PhysicalPlan.validators`, which the S2 compiler copies from `PhysicalPlanInputs.validators` (`execution/physical/_compiler.py:439`).

What still forces a route: validators send every streamed and bounded route to resident. The reads are pinned in `S3_PENDING` (`tests/sentry/test_validators_do_not_route.py:32`). `S3_PENDING` pins 55 identities, 67 occurrences and 19 modules; the scan itself finds 60 identities, 72 occurrences and 22 modules, the extra five being lifecycle storage sites (5.6). Step 1 recounts both on the merged head. The out-of-core route keeps a second validator engine (`execution/out_of_core/_validate_batch.py`, 387 lines) that also protects a direct caller of the public `run_fk_out_of_core` (`execution/out_of_core/__init__.py:65`, `_validate_batch.py:326`) and records its verdict on the session with an owner token (`_validate_batch.py:387`).

## 2. Guarantee and non-goals

Guarantee:

- G1. A config with validators takes the same route, route reason and per-column backends as the same config without validators, on every route, with two exceptions that keep the run resident under a named route code:
  - `validators_need_transactional_sink`: the sink is a plain callable, so rows would leave before the verdict. A sink that is neither callable nor a full staged shape is refused before any read under the same code.
  - `validators_need_resident_rows`: the config enables quarantine. The bounded routes cannot remove rejected rows, so the resident quarantine path stays (it filters covered failures and succeeds).
- G2. No row reaches a committed sink, and no evidence is sealed, before the run's verdict. On a sink route a failing verdict raises `ValidatorFailedError` before `sink.commit()`, recorded as a validation failure, never as a COMMIT failure. On a no-sink route the verdict runs before `seal_evidence` and before the result is returned. This holds for every public entry that writes rows: `run_pipeline`, `run_fk_out_of_core`, `generate_tables_streamed` and `generate_tables_streamed_from_generation_plan`.
- G3. A streamed route's report equals whole-table validation of that route's delivered output (findings, counts, capped indices). On route-stable columns it equals the full-frame report. Where a route delivers different bytes for the same input, the report follows the delivered bytes: the documented case is a passed-through float NaN that survives out-of-core and becomes null on full frame (`tests/parity/SEMANTIC_DIFFERENCES.md:40`). AT-17 pins that exact report on both routes.
- G4. Validator memory on a streamed route stays bounded: per paired table, the source projections waiting for their output (bounded by the route's in-flight batches, or spilled on the two-phase driver), plus the fold state under the session's key-state ceiling.
- G5. No error, finding detail, quarantine reason or log text carries a cell value. S3 removes the one numeric leak it found: `reconciliation_holds` prints `worst_delta` in `finding.detail` (`validators/_relationship_checks.py:530`), which equals the parent cell when the child aggregate is zero.

Non-goals:

- No run-card fact, CLI JSON member or `leak_check_column_not_checked` warning (S4).
- No streaming for quarantine, post-validation, fidelity report or declared casting on the chunked lane: those keep their own resident reasons (`execution/_chunked_output_sink.py:110-122`).
- No change to any verdict rule inside a validator module. The `reconciliation_holds` detail text changes; its verdict does not.
- No hardening against a hostile in-process writer (V1 threat model: accidental leaks only). Engine-owned staging refuses a raw write once the proxy owns it (5.2); a user-supplied four-member sink relies on every engine route holding only the proxy (AT-13).

## 3. Established solutions

- Validate before publish, publish atomically: the two-phase write the engine already uses (`TransactionalSink` stage, then `commit`). S3 puts the verdict between them, as a database runs deferred constraints at COMMIT (PostgreSQL `SET CONSTRAINTS ... DEFERRED`).
- Observe writes through a proxy: the decorator pattern (GoF), as `io.BufferedWriter` wraps a raw stream. The proxy keeps the wrapped object's shape so protocol checks still see the real capabilities.
- Expected-set completeness at commit: a two-phase commit coordinator registers every participant before prepare and refuses to commit while one has not voted. S3 registers the tables a route will actually write before the first write.
- Exclusive writer: a capability handed to one holder (object-capability style). Engine-owned staging accepts writes only through the proxy once it is bound.
- Capture the pair where it is produced: the engine's vault already records the aligned source and masked batch at the mask step (`collect_batch_vault`, `out_of_core/_rewrite_pass.py:236`, `out_of_core/_stream_driver.py:373`) instead of re-reading the source. Paired checks use the same rule.
- Bounded producer and consumer handoff (a bounded queue) for interleaved routes, and a sealed spill for the two-phase driver, read only after the writer is closed, as `SpillPayloadStore` does (`out_of_core/_payload_store.py:77`) through `open_private` and `close_private` (`out_of_core/_scratch.py:25`, `:43`).
- Streaming checks with order-free folds: S1 and S2 already use mergeable aggregates (Apache Beam `CombineFn`).

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
| Staged replacement | `_replace_staged` | `execution/_transactional_sink.py:313` |
| Out-of-core table order | `_table_order` | `execution/out_of_core/_runner.py:240`, `:272` |
| Report stamp | `quality_metrics["validation"]` writer | `execution/out_of_core/_validate_batch.py:380` (moved, 5.1) |
| Private scratch files | `open_private`, `close_private`, `private_dir` | `execution/out_of_core/_scratch.py:25`, `:43`, `:69` |
| Sealed spill pattern | `SpillPayloadStore` | `execution/out_of_core/_payload_store.py:77` |
| Aligned pair sites | `collect_batch_vault` calls | `out_of_core/_rewrite_pass.py:236`, `out_of_core/_stream_driver.py:373` |
| Runtime codes | `VALIDATOR_TABLE_NOT_OBSERVED`, `VALIDATOR_SOURCE_PAIRING_MISMATCH`, `VALIDATOR_KEY_STATE_OVER_BUDGET` | `reasons/runtime/_part3.py:99-102` |
| Retired route codes | `reasons/route/_retired.py` | 20 lines today |
| Physical reason tokens | `ROUTE_VALIDATORS_PRESENT` | `execution/physical/_reasons.py:56`, `:101`, `:343` |
| Routing sentry | `S3_PENDING` and `_scan` | `tests/sentry/test_validators_do_not_route.py:32`, `:197` |
| Size and fan-out guards | `test_module_size.py`, `layout/test_package_fanout.py` | `tests/sentry/` |

## 5. Design

### 5.1 Who owns the session

New `judged_run(config, sink, *, tables, session=None, quality_metrics)` context manager in `execution/pipeline/_validated_sink.py`. It is the one way a run gets a session, a wrapped sink and a resident judge.

- Ownership is explicit, never inferred from config equality. Each public entry (`run_pipeline`, `run_fk_out_of_core`, the two streamed generation entries) calls `judged_run` with `session=None`, so every independent invocation binds a fresh session (or a fresh `None` for a validator-free config) on the ContextVar. A nested public call with the same config object therefore never closes or feeds the outer session.
- Internal delegation passes the owner. `execute_route` hands its session to the out-of-core runner through a new private `_run_fk_out_of_core_owned(..., session)`; the public `run_fk_out_of_core` is a thin wrapper that enters `judged_run(session=None)` and calls it. With `session` given, `judged_run` reuses it and does not bind.
- Before the first write it calls the new `session.expect_delivery(tables)` with the tables the route will actually write (5.3).
- It yields a `JudgedRun` with `.sink` (the proxy, or `None`) and `.judge_resident(outputs)`.
- On a clean exit it stamps `quality_metrics["validation"]` from the session's stored report, through the same writer the out-of-core collector used (`_validate_batch.py:380`, moved here), so a direct out-of-core call or a streamed generation call reports its checks on success, with and without a sink.

`execute_route`, `run_fk_out_of_core`, `generate_tables_streamed` and `generate_tables_streamed_from_generation_plan` (`generation/_plan_entry.py:315`, `:376`) enter `judged_run`. The generation entries pass `.sink` to `run_generation`, so the `OutputPublish` that `run_generation` opens (`generation/_streamed.py:525-529`) writes and commits through the proxy, and `observed_commit` judges before the commit. On the resident generation result they call `judge_resident(result.tables)` before returning. `generation/_streamed.py` is not edited; the proxy forwards the `bounded_write_batches` marker through `__getattr__`.

The runner's collector (`out_of_core/_runner.py:216`), its forward (`:322`), `finish_validation` (`:359`) and all of `_validate_batch.py` are deleted. The `_delivered` hooks (`_rewrite_pass.py:198-200`, `_stream_driver.py:431-433`) and the `validators` parameters (`_rewrite_pass.py:93`, `_stream_driver.py:154`) go with them. `record_external_verdict` and the `_external` set lose their only caller and are deleted.

A table reaches the session at one of two choke points:

- A table written to a sink is fed by the sink proxy (5.2), batch by batch, after the route's final reconciliation, in delivered order.
- A table returned resident is fed by `judge_resident`, after assembly, which `complete_resident_validation` also calls.

### 5.2 Sink shapes, the proxy and exclusive writes

One classifier for sink shape. `_has_transactional_write_contract` moves from `_sequential.py:207` to `execution/_transactional_sink.py`, next to the `TransactionalSink` protocol (`:75`), as public `sink_shape(sink) -> SinkShape`:

| Shape | Test | With validators |
|---|---|---|
| `ABSENT` | `sink is None` | route unchanged; resident judge |
| `TRANSACTIONAL` | callable `write`, `write_batches`, `commit`, `abort` | route unchanged; proxy |
| `STAGED` | callable `write`, `commit`, `abort`, no `write_batches` | route unchanged (never out-of-core or streamed, as today); proxy |
| `CALLABLE` | `callable(sink)` and not one of the above | resident, `validators_need_transactional_sink`; delivered after the verdict |
| `PARTIAL` | anything else | refused before any read, `validators_need_transactional_sink` |

`_sequential.py` imports it (its local function is deleted, so the file shrinks). Route admission, the proxy, sequential delivery and the direct out-of-core entry all read `sink_shape`. An out-of-core sink route requires `TRANSACTIONAL`, because the runner calls `write_batches`; this is today's `isinstance(sink, TransactionalSink)` rule, now named.

New `execution/pipeline/_validated_sink.py` (about 200 lines) holds `judged_run`, the proxy and `validation_needs_resident`. It sits in `execution/pipeline/` because `execution/` is pinned at 103 direct modules (`tests/sentry/layout/test_package_fanout.py:32`) and `pipeline/` already holds the run lifecycle (`_lifecycle.py`, `_post_scan.py`). `decoy_engine.validators` keeps only the session API. S1 listed `observe_sink` as a `decoy_engine.validators` name; S3 moves it and corrects the S1 public-name list.

`observe_sink(sink, session)` wraps `STAGED` and `TRANSACTIONAL` sinks only.

- `_ObservedStaged`: `write` feeds, then forwards. `commit` and `abort` forward only.
- `_ObservedTransactional`: `write` and `write_batches` feed, then forward. `write_batches` feeds each batch as the inner sink pulls it, so nothing is buffered. When no batch arrives (a zero-row table, written as `write_batches(table, iter(()), schema=...)` at `_chunked_output_sink.py:591`), it feeds `schema.empty_table()` once.
- A second write of a table the proxy has already fed refuses with the new runtime code `validator_table_rewritten` (fixed message, table name only), so the session never judges one version and delivers another. Step 1 confirms no route writes a table twice.

Each class carries a read-only `inner_sink`. `__getattr__` forwards an attribute only when the inner sink has it, so `staged_tables`, staged openers, publication evidence and the `bounded_write_batches` marker still work, and no protocol member is invented. `_ObservedStaged` has no `write_batches`, so `isinstance(proxy, TransactionalSink)` stays false for it.

Exclusive writes on engine-owned staging. `ParquetTransactionalSink` and `StagingSink` gain `bind_writer(token)`. Once bound, a `write` or `write_batches` that does not run inside the token's `guarded()` scope refuses with `validator_table_not_observed`, before `_replace_staged` (`_transactional_sink.py:313`) can replace a judged file. The proxy binds on wrap and wraps each forwarded call in `guarded()`; the guard is a per-sink thread-local flag, so a concurrent raw call on another thread is not let through by the proxy's own write. A user-supplied sink has no `bind_writer`, and the route-holds-only-the-proxy rule covers it (AT-13).

Installing the proxy. Most streamed writes use `ctx.publish.active_sink`, and `OutputPublish` (`_chunked_output_sink.py:128`) is an ordinary class built with the raw sink at `_pipeline_context.py:267` (writers at `_pipeline_generate_mask.py:251`, `:286`, `_pipeline_mixed_route.py:224`, `:241`, `_pipeline_full_frame.py:303`; commit at `_chunked_output_sink.py:161`). Before any executor runs and before the publish opens, `execute_route` builds `OutputPublish(proxy, stream=ctx.publish.stream, post_validation=ctx.publish.post_validation)` and replaces the context once with `dataclasses.replace(ctx, sink=proxy, publish=new_publish)`. On a no-sink route both stay `None`. Routing has already decided on the unwrapped sink.

While a session is bound, `observed_commit` refuses a sink that is not a proxy (it has no `inner_sink`) with `validator_table_not_observed`, before any commit.

`post_scan_sink_kind` (`config/_post_scan.py:211`) follows `inner_sink` (with a seen-set against cycles) before it returns the class token.

### 5.3 The verdict at commit, completeness, and the verdict before a seal

The expected set is the tables the route will actually write, computed from the same value the writer loops over:

- Out-of-core: `[t for t in _table_order(plan, relationship_graph, sources) if t in sources]`, the exact filter of the write loop (`_runner.py:272`). A plan-only table with no source is not expected; a source-only table is.
- Sequential: the plan and graph table set `run_sequential` loads (`_sequential.py:249`).
- Auto-chunk, split and mixed: the dispatched table set of the route.
- Streamed generation: the config's generated tables.

Step 1 confirms each against its write loop, and AT-6 has an asymmetric cell per route.

`observed_commit` (`execution/_publication_observer.py:132`), after `gate.before_commit(sink)` (`:141-142`) and before `evidence_of(sink)` (`:143`):

1. Refuses with `validator_table_not_observed` if `staged_tables()` (where the sink has it, `_transactional_sink.py:427`) names a table outside the expected set.
2. Marks every expected table complete.
3. Calls `close()` on the run's session.

A table in the expected set that the proxy never fed is refused by `close` with `validator_table_not_observed`. The expected set does not depend on the sink, so a four-member sink with no `staged_tables` is covered the same way as `ParquetTransactionalSink`. An empty table is observed by the proxy's empty feed, so it counts.

A `ValidatorFailedError` leaves before the commit `try`, so no COMMIT failure is captured, and the existing unwinds abort the sink: `OutputPublish.__exit__` (`_chunked_output_sink.py:165`), the sequential executor's failure path (`_sequential.py:658`), and the out-of-core runner's.

A table fed after the verdict is a wiring bug: `_feed` (`validators/_session.py:311`) raises `ValidatorStateError` with the new runtime code `validator_rows_after_verdict` and a fixed message naming the table, in place of today's bare `ValueError`.

The verdict before any seal. Every route that seals evidence judges first:

- With a sink, the verdict runs in `observed_commit`, after `seal_evidence`. The commit sits inside the cast owner's abort scope on both the sequential (`_sequential.py:608`, `:658`) and out-of-core routes, so a failure aborts the sink and discards the sealed quarantine evidence.
- Without a sink, the sequential runner (`_sequential.py:608`) and the out-of-core runner (`_runner.py:360`) call `judge_resident(outputs)` immediately before `seal_evidence`, inside the cast-owner scope. A failing verdict seals nothing, and the owner's abort removes temp output. `run_sequential` and the out-of-core runner take the judge as a keyword (`judge: Callable | None`); `execute_route` and `judged_run` pass it.
- After the executor returns, `complete_resident_validation` sees `close_attempted` and returns the stored report without a second judgement. If a resident output table was never fed, it refuses with `validator_table_not_observed`.

AT-16 checks the event order on both routes, with and without a sink, and that no sealed artifact remains on disk after a rejection.

### 5.4 Sources for paired checks

A paired check (for example `leak_check`) compares an output row with the source row that produced it. Re-reading `ctx.caller_sources` is wrong: a second read can be permuted, loader-only out-of-core tables exist only in `resolved_sources`, and declared casting masks typed copies. So S3 captures the source where masking consumes it, after any cast.

New `validators/_source_handoff.py` (about 150 lines), pyarrow only, two forms behind one `source_tap(table)` and one `SourceCursor`:

- `BoundedHandoff` for interleaved routes, where pulling one output batch drives masking of the matching source batch (auto-chunk, split, mixed mask, the out-of-core rewrite pass, sequential). The tap appends the paired-column projection to an in-memory FIFO; the proxy or resident feed takes rows from its head as output arrives, slicing at source-batch boundaries before each fold call. The FIFO is bounded by the route's in-flight batch count (step 1 names it per route; 2 on the rewrite pass). Overflow refuses with `validator_source_pairing_mismatch`, so a route that runs ahead fails closed instead of growing memory.
- `SealedSpill` for the two-phase out-of-core stream driver. The tap writes the projection, in source order, through `open_private` into a `private_dir` under the run's scratch arena, and charges the bytes to the measured arena (`temp_disk_budget_bytes`, `_runner.py:122`). The writer is closed with `close_private` before phase two, and only then does the cursor open it. The driver replays payload in insertion order and aligns joined rows to each payload offset (`_stream_driver.py:373`), so delivered order equals source order: the driver stays out-of-core with paired checks (AT-15).

The session owns both forms in its `ExitStack`: closed and deleted on `close`, on scope exit and on every exception. At `finish`, rows left in a handoff, or output with no source left, raise `validator_source_pairing_mismatch`. A paired table whose output reaches the fold with no tap raises the same code. The validators package imports no execution module: it receives the private-file opener and the directory as arguments.

Tap sites, all after cast and before masking:

- Sequential: directly after `cast_run.load_table` (`_sequential.py:408-410`), on every branch, so the `caller_sources`, lazy and loader paths all tap. The loader tee and `compose_tees` from the earlier draft are dropped.
- Auto-chunk, split and mixed mask: the shared chunk iterator in `_pipeline_auto_chunk._run_streamed` (`_pipeline_auto_chunk.py:342`), after `_declared_wrap` (`:238`). Mixed masking calls `run_auto_chunk` directly (`_pipeline_mixed_route.py`), so this one site covers it.
- Out-of-core rewrite pass: beside `collect_batch_vault` (`_rewrite_pass.py:236`), on the cast and compacted `raw_batch`. The proxy feeds after the final reconciliation.
- Out-of-core stream driver: phase one, on the aligned payload before the reorder (`_stream_driver.py:373`), into the sealed spill.

### 5.5 When validators need resident

New public `validation_needs_resident(config, sink) -> str | None` in `execution/pipeline/_validated_sink.py`:

- `validators_need_transactional_sink` when the config has validators and `sink_shape(sink)` is `CALLABLE`. For `PARTIAL` it returns the same code, and the caller refuses before any read instead of routing.
- `validators_need_resident_rows` when the config has validators and quarantine is enabled.

It is called once in `decide_execution_route` before the byte-estimate branch, so a decline is never replaced by `BYTE_ESTIMATE_FULL_FRAME_FITS`. The direct out-of-core entry calls it in `judged_run` before any read and refuses with the returned code (this replaces the direct entry's own validator and quarantine guard). Forced sequential or forced out-of-core with a declined job refuses with the existing forced-mode refusal naming the code. A job too large for resident refuses with the resident route's capacity refusal, and the routing record still names the validator code.

Plan hash. The sink shape now decides a route only when validators are present. `compute_plan_hash` (`execution/physical/_inputs.py:87-95`, `:324`) already hashes the whole config and the sink class token; S3 adds a `validator_sink_shape` token to the hash tuple only when the config has validators, so two instances of one class with different shapes hash differently, and every validator-free hash is unchanged. The physical snapshot records it for replay.

Callable delivery. The resident route leaves `OutputPublish.active_sink` `None`, so no resident callback exists today. S3 adds one delivery in `execute_route`: after `complete_resident_validation` and the post-scan settle, it calls the original callable once per judged table, in plan order. The callable is never wrapped, so delivery does not feed the session. A failing verdict raises before delivery, so the callable is called zero times.

### 5.6 Delete every routing read

Every entry in `S3_PENDING` is deleted at its source:

- Route choice: `decide_output_mode` loses `:114-115`; `_pipeline_routing.py` loses the `_sequential_eligible` decline (`:144`), `bounded_admission`'s validator parameter, `validators_ooc_ready` (`:338-349`) and the D3a lift in `decide_execution_route`; `_pipeline_routing_signals.resolve_execution_route` stops forwarding; `_pipeline_multi_table._job_gates_hold` loses `:151`.
- Mirrors of the decline: `_job_estimate._estimate`, `capacity.estimate_job_capacity`, `pipeline/_lazy_input._relationship_job_is_bounded`, `_transforms_admission.check_rejections_before_preparation`, `_transforms_prepare.prepare_transform_sources`, `_pipeline_context.build_run_context` and `decide_route`, `_unified_slice._execute_admitted`.
- Physical plan replay: `physical/_compiler.layer1_route` and `out_of_core_not_ready_reason` stop reading validators. `PhysicalPlanInputs.validators` stays, filled by a new lifecycle helper `physical_validator_spec(config)`; the compiler still copies it to `PhysicalPlan.validators` (`_compiler.py:439`) for the standalone coordinator.
- `ROUTE_VALIDATORS_PRESENT` leaves the physical reason-token catalog (`execution/physical/_reasons.py:56`, `:101`, `:343`).
- Out-of-core: 5.1.

`S3_PENDING` is then empty and is deleted. The sentry keeps two exact allowlists:

- Lifecycle callers, as `(module, function, public name)`: `judged_run` in `execute_route`, `run_fk_out_of_core` and the two generation entries; `observe_sink` in `judged_run`; `complete_resident_validation` in `execute_route`; `active_validation_session` in `observed_commit`; `validation_needs_resident` in `decide_execution_route` and `judged_run`; `physical_validator_spec` in the physical input builders; and the S2 callers that remain (`_pipeline_finalize.py:417`, `:421`, `:432`, `_pipeline_mixed_route.py:65`, `:294`, `physical/_shadow_generation.py:269`, `:276`, `:285`, `:292`).
- Storage and transfer sites, as `(module, qualified name, kind)`: the compiler's `validators` keyword and attribute copy (`physical/_compiler.py:439`), the `PhysicalPlan.validators` field, the coordinator's `plan.validators` read, the shadow enforcer's config read (`physical/_shadow_generation.py`), and `physical_validator_spec`'s own config read. These carry the spec; none chooses a route.

The scan gains caller tracking for public helpers. Any other read of the `validators` key or a `validators*` name under `execution/` fails. The stale comment at `_pipeline_mixed_route.py:294-296` is corrected.

### 5.7 Reason codes

- New route codes `validators_need_transactional_sink` and `validators_need_resident_rows` (`reasons/route/`).
- New runtime codes `validator_rows_after_verdict` and `validator_table_rewritten` (`reasons/runtime/_part3.py`).
- Retired: `route.validators_present` (`reasons/route/_part1.py:306`) moves to `reasons/route/_retired.py`. `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`) is retired the same way; if the runtime family has no retired module, S3 adds `reasons/runtime/_retired.py` on the route pattern.

### 5.8 Placement

| New or changed item | Directory | CODEMAP row | Why here |
|---|---|---|---|
| `_validated_sink.py` (`judged_run`, proxy, `validation_needs_resident`, report stamp) | `src/decoy_engine/execution/pipeline/` | run lifecycle row, beside `_lifecycle.py` | `execution/` is at its fan-out pin of 103; validators stays free of execution imports |
| `sink_shape`, `bind_writer` | `execution/_transactional_sink.py` | transactional sink row | next to the protocol and the staging it guards |
| `_source_handoff.py` | `src/decoy_engine/validators/` | "Job-level validator framework" (added in S1) | the session's own pairing state; pyarrow only |
| tests | `tests/unit/validators/`, `tests/unit/execution/judgement/`, `tests/sentry/` | per the S1 row | as S1 and S2 |

No module over 600 lines grows past its census ceiling: `_sequential.py` (680) loses the classifier (about 18 lines) and gains the tap and judge call (about 6); `_chunked_output_sink.py` (600), `_pipeline_routing_signals.py` (613) and `_pipeline_context.py` (599) only lose lines; `_pipeline_auto_chunk.py` (600) gains a one-line tap and moves `_slices` (`:174`, 5 lines) next to its only caller's helper so it stays at or under 600; `_transactional_sink.py` (598) gains `sink_shape` and `bind_writer` (about 45 lines) and takes a reviewed census entry with a ceiling of 650, under the 700 max. The module-size and fan-out sentries enforce all of this.

### 5.9 Design notes

- One owner per invocation (`judged_run`, ownership passed explicitly), one feed point per delivery shape (proxy or resident judge), one judge (`close`), one judgement time before every commit and every seal, one sink classifier (`sink_shape`), one capture point for paired sources (the tap after cast). Each has a guard test and a mutation (section 8).
- Routing knows nothing about validators, except the one public question `validation_needs_resident`.
- Dependency direction: `validators/` takes the private-file opener, directory and budget as arguments and imports no execution module.
- Pre-GA hard delete: the out-of-core collector, `record_external_verdict`, `observe_pair`, `S3_PENDING` and the retired codes go in this slice.

## 6. Behavior and failure modes

| Case | Behavior |
|---|---|
| Auto-chunk streamed with a `TransactionalSink`, validators pass | Route `streamed`, same reason as without validators; one commit. |
| Same, a validator fails | `ValidatorFailedError` before `sink.commit()`; abort runs; staging is empty; no COMMIT failure record. |
| `generate_tables_streamed` with a bounded sink, a validator fails | Zero commits, one abort, `ValidatorFailedError`. |
| `generate_tables_streamed`, resident result, a validator fails | Raises before the result is returned. |
| Sequential FK with a plain callable sink | Resident, `validators_need_transactional_sink`; callable called once per table after a pass, zero times after a fail. |
| Non-callable partial sink | Refused before any read, `validators_need_transactional_sink`. |
| No sink | `ABSENT`; route unchanged; judged before seal and return. |
| Three-member staged sink | Same route as without validators (never out-of-core); proxy. |
| Config with validators and quarantine | Resident, `validators_need_resident_rows`. |
| Sequential with no sink, a validator fails, declared casting | Verdict before `seal_evidence`; nothing sealed. |
| Out-of-core through the pipeline, with or without a sink | Out-of-core route; judged before commit or before seal. |
| Direct `run_fk_out_of_core` call | Fresh session; same verdicts; report stamped on success. |
| Nested public call with the same config object and other inputs | Fresh session; the outer session is untouched. |
| Paired check, interleaved route | Source tapped after cast into a bounded FIFO. |
| Paired check, two-phase stream driver | Sealed private spill; stays out-of-core. |
| Handoff FIFO overflows | `validator_source_pairing_mismatch`; nothing committed. |
| Source rows differ in count from delivered rows | `validator_source_pairing_mismatch`; nothing committed. |
| A table written twice through the proxy | `validator_table_rewritten`. |
| A raw write to engine-owned staging after the proxy bound it | `validator_table_not_observed`, before the staged file is replaced. |
| `staged_tables()` names a table outside the expected set | `validator_table_not_observed` at commit. |
| A write handle holds the raw user sink at commit | `observed_commit` refuses a non-proxy sink. |
| Rows fed after the verdict | `validator_rows_after_verdict`. |
| Zero-row table on a streamed route | The proxy feeds an empty table once; the table is judged. |
| `reconciliation_holds` fails | Finding detail names the check and table, no numeric delta. |
| Keyed state passes the ceiling | `validator_key_state_over_budget` before the next scoped write. |

## 7. Acceptance tests

Master plan numbers in brackets. A failure uses a reject-all `regex_match` (`pattern: "^$"`) unless stated, over a table with a seeded cell value `SECRET-CELL-7731`. Every assertion is marked "fails before S3" or "control". The PR records, per assertion, the observed result before S3 and the final-head mutation result.

- AT-1 [V4 streamed rows]. Routes: auto-chunk streamed with `ParquetTransactionalSink` (120k rows); sequential FK with a transactional sink and with no sink; out-of-core FK with and without a sink; multi-table split with a sink; mixed route generate and mask. Each route checks:
  - (a) route label, route reason and per-column backends equal the same config without validators. Fails before S3 on the auto-chunk, sequential, split and mixed cells; the out-of-core cells are controls (S2's D3a lift).
  - (b) a passing validator gives `passed` results. Control.
  - (c) a failing validator raises `ValidatorFailedError` with the exact finding count (7 rejected rows), the inner `commit` is never called, staging is empty, and the failure record does not say COMMIT. Out-of-core cells are controls for the verdict (D3a already rejects) and fail before S3 on a new assertion: the verdict event comes from `observed_commit` or `judge_resident`, recorded by the event trace.
  - (d) `SECRET-CELL-7731` is absent from `str(exc)`, the serialized report, the failure record and captured logs.
- AT-2 [V4 callable row]. Sequential FK with a plain callable and validators: resident with `validators_need_transactional_sink`; a failing validator calls the callable zero times; a passing one calls it once per table after `close`, with no session feed. Forced-sequential refuses with the forced-mode refusal naming the code. A low resident budget refuses with the resident capacity refusal. A table-driven cell runs `sink_shape` on `None`, a plain callable, a non-callable partial, a three-member sink and a four-member sink, through `run_pipeline` and through `run_fk_out_of_core`, and checks: `None` keeps the route; the three-member sink never reaches out-of-core; the partial refuses before the first source read (a counting loader reads zero tables).
- AT-3 [V4 readability rows]. `ParquetTransactionalSink` and an isolated `StagingSink`, each wrapped, with `post_scan.integrity`: no `POST_SCAN_INTEGRITY_SINK_UNREADABLE`; the integrity report shows the gate ran; the snapshot holds the inner sink kind and shape. The isolated row proves `StagingSink.commit()` and `.abort()` stay no-ops.
- AT-4 [V5]. A 120k-row table with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`. Source batches are 4,096 rows and sink batches 10,000. The check fails with the whole-table report of the delivered output on the streamed, sequential, out-of-core rewrite and out-of-core stream-driver routes, from a resident `pa.Table` source and from a lazy Parquet source. With `hash` it passes. Memory is measured from the tap's first call to `close`: `tracemalloc` peak plus `pyarrow.total_allocated_bytes()` delta stay under the FIFO bound (in-flight batches times one projected source batch) plus one output slice plus 64 KiB on the interleaved routes, and under one projected source batch plus one output slice plus 64 KiB on the stream driver, whose spill is checked on disk instead.
- AT-5 [V6, perf, Dell vm-run]. 2M rows streamed, `leak_check` and `regex_match`, every row failing: `retained_bytes()` under `2 * FINDING_INDEX_CAP * 8` plus 64 KiB plus the FIFO bound; peak RSS within 64 MiB of the same run without validators; on the stream driver, spill payload bytes (sum of projected `nbytes`) are reported apart from the IPC file size, which adds schema and framing; wall time recorded.
- AT-6 [V7]. Completeness and exclusive writes, each refusing before commit with nothing committed and no exception context:
  - Two tables, A through the proxy and B written straight to the inner sink: on `ParquetTransactionalSink` the raw write refuses at once (`bind_writer`); on a four-member user sink with no `staged_tables`, commit refuses for B.
  - Same-name replacement: A through the proxy (passing), then a rejecting A of the same row count through the raw handle of `ParquetTransactionalSink`: the raw write refuses and the staged file is the judged one. The same replacement through the proxy refuses with `validator_table_rewritten`.
  - Unexpected staged table: only A expected, B staged on `ParquetTransactionalSink` through a test seam that bypasses `bind_writer`: commit refuses. Deleting the `staged_tables()` check turns this red.
  - Out-of-core asymmetric sets: a source-only table (in `sources`, not in the plan) is expected and refused when written raw; a plan-only table with no source is not expected and the run passes.
  - A three-member sink wrapped stays non-`TransactionalSink`; a four-member one stays one.
  - Rows fed after `close` raise `validator_rows_after_verdict`.
- AT-7 [V8]. `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on sequential and out-of-core give the full-frame report for single, composite, nullable and two-parent FKs. Out-of-core with an orphan policy that nulls orphan keys gives a `no_orphan_children` finding. Named cells at the session boundary (fed directly, child batches before parent batches):
  - child-first with a non-null FK and a null child date, and with a non-null FK and a malformed non-null date: the report names those rows as the full-frame rule does.
  - duplicate pending children: two child rows at distinct indices reference one parent key outside its window; both indices appear.
  - self-reference on out-of-core: the route refuses as today (control).
  - A key-state budget forced to 1 KiB refuses before the first scoped write.
- AT-8 [V9]. The routing sentry passes with `S3_PENDING` deleted. It fails on each seeded spelling (`config.get("validators")`, `if validators:`, a `validators_ooc_ready` name) in a copy of `_pipeline_routing.py`, on a raw `validators` read added beside an allowlisted storage site, and on a call to `validation_needs_resident` from an unlisted function.
- AT-9 [V14]. `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as retired; `ROUTE_VALIDATORS_PRESENT` is gone from the physical catalog; nothing in `src/` emits them.
- AT-10. Nesting, each against an outer bound run: an inner run with no validators commits without closing or feeding the outer session; an inner `run_pipeline` call with the same config object and different records binds its own session and leaves the outer session's fed tables unchanged. Fails before S3 on the head named in section 1 (ContextVar not cleared) unless the S2 fix has landed.
- AT-11 [V15f]. Direct `run_fk_out_of_core`, with a sink and without: a failing validator raises with nothing committed or returned (control for the raise; fails before S3 on the event trace); a passing validator stamps `quality_metrics["validation"]` with the exact check names and counts (fails before S3 on the no-sink cell if the stamp moves). Through `run_pipeline` the out-of-core runner receives the pipeline's session object (identity checked) and binds none.
- AT-12. Plan hash: for a validator-free config the hash is equal before and after S3 (control). For a config with validators, two sinks of one class with different shapes (callable and four-member) hash differently (fails before S3). A config with validators records the same route decision as without them (fails before S3).
- AT-13. Every streamed writer reaches the proxy. On auto-chunk, split, mixed generate and mixed mask, spies on the inner sink's `write` and `write_batches` see only calls made from inside the proxy (the guard flag set), and the commit runs on the same proxy object built into the new `OutputPublish`. A seam that writes through the original `publish.active_sink` makes `observed_commit` refuse before commit.
- AT-14. Empty tables, on streamed, sequential and out-of-core: a zero-row table beside a passing non-empty sibling passes, and the session's fed set includes the empty table. With the empty feed deleted, the same run fails with `validator_table_not_observed`. A zero-row table beside a rejecting sibling raises with the sibling's exact finding and no finding on the empty table.
- AT-15 [V5 extension]. Pairing:
  - A source that returns the same rows rotated by one on each read gives the report of the read masking consumed, on the rewrite pass and the stream driver.
  - A loader-only out-of-core table is paired.
  - A declared cast that changes the verdict pairs against the cast value (sequential and auto-chunk).
  - Resident, lazy and loader-only sequential sources each pair.
  - A paired mixed-mask table pairs.
  - A source one row longer than the output refuses with `validator_source_pairing_mismatch`.
  - A route seam that runs the producer three batches ahead of a FIFO bound of two refuses with the same code.
  - The stream driver with a paired check stays out-of-core.
  - The sealed spill file has mode `0o600`, and it is gone after a pass, a fail and a refusal.
- AT-16. Declared casting with a failing validator, on sequential and out-of-core: with a sink the event trace is seal, verdict, abort, discard; without a sink it is verdict, abort, with no seal. No sealed quarantine artifact remains on disk in any cell.
- AT-17. NaN pass-through: a float column with NaN under `regex_match` rejecting `"nan"`. Out-of-core reports the NaN rows and full frame does not; the exact report is pinned for both routes (G3). Control (S2 behavior), kept as a G3 pin.
- AT-18. A standalone mask-plan run with a failing validator and no caller validation config raises `ValidatorFailedError`. Control (existing S2 test), kept so the `physical_validator_spec` move cannot break it.
- AT-19. Validators with quarantine: resident with `validators_need_resident_rows`; covered failures filtered and the run succeeds; no quarantine sidecar when an uncovered failure raises.
- AT-20. Streamed generation: `generate_tables_streamed` with a seven-row sequence, a reject-all validator and a bounded sink that consumes every batch: zero commits, one abort, `ValidatorFailedError`. The same through `generate_tables_streamed_from_generation_plan`. A passing run commits once and stamps the report. A resident-result run raises before return. Fails before S3 (commits once today).
- AT-21. Value-free numeric detail: `reconciliation_holds` with a parent value of `987654.321` and a child aggregate of zero fails; `987654.321` (and `987654`) is absent from the serialized finding, `str(exc)`, the failure record and, under quarantine, the quarantine reason column. Fails before S3.

## 8. Named mutations

Master plan numbers in brackets. Each must turn the named test red on the final head.

- M-1 [M3]. `observed_commit` commits before `close`: AT-1(c) and AT-20 red.
- M-2 [M4]. The cursor restarts from the head of the handoff for each output slice: AT-4 red.
- M-3 [M5]. `_ObservedTransactional.write_batches` forwards without feeding: AT-13 spy and AT-1(c) red.
- M-4 [M8]. The cursor reads the whole spill into memory on open: AT-4 stream-driver memory cell red.
- M-5 [M10]. `if validators: return False` back in `_sequential_eligible`: AT-8 and AT-1(a) sequential red.
- M-6 [M12]. Remove `complete_resident_validation` from `execute_route`: a dedicated cell where a sequential no-sink resident output is fed only by resident completion (judge not passed by a test seam) goes red with `validator_table_not_observed` missing.
- M-7 [M13]. Put `write_batches` on `_ObservedStaged`: AT-6 protocol cell red.
- M-8 [M14]. `post_scan_sink_kind` returns the proxy token: AT-3 red.
- M-9 [M15]. A second observer of a table adds to its folds: a dedicated cell that calls both the proxy feed and `judge_resident` for one table reports 14, not 7 (with the mutation off it refuses as a double feed).
- M-10 [M16]. Drop `raw_is_null` from pending `parent_window_respected` state: AT-7 null-date child-first cell red.
- M-11 [M9]. One pending child per parent key instead of a list: AT-7 duplicate cell red.
- M-12. `validation_needs_resident` returns `None` for a callable: AT-2 red.
- M-13. `_feed` after the verdict returns silently: AT-6 last cell red.
- M-14. `execute_route` replaces `ctx.sink` but keeps the old `OutputPublish`: AT-13 red.
- M-15. The proxy's `write_batches` feeds nothing for an empty iterator: AT-14 passing-sibling cell red.
- M-16. The handoff skips the leftover-rows check: AT-15 long-source cell red.
- M-17. The rewrite-pass tap is removed and the cursor re-reads `caller_sources`: AT-15 rotating cell red.
- M-18a. `judged_run` never binds when `session` is `None`: AT-11 direct-call cells red.
- M-18b. `judged_run` reuses any active session instead of binding fresh: AT-10 same-config nested cell red.
- M-19. `observed_commit` drops the expected-set marking and uses only `staged_tables()`: AT-6 four-member cell red.
- M-19b. `observed_commit` drops the unexpected-staged check: AT-6 unexpected-staged cell red.
- M-20. The no-sink verdict moves after `seal_evidence` on sequential: AT-16 sequential no-sink trace red.
- M-21. `validation_needs_resident` ignores quarantine: AT-19 red.
- M-22. `PhysicalPlanInputs.validators` left empty: AT-18 red.
- M-23. `bind_writer` is a no-op: AT-6 replacement cell red.
- M-24. The out-of-core expected set uses the plan tables, not the filtered order: AT-6 asymmetric cells red.
- M-25. The generation entries pass the raw sink: AT-20 red.
- M-26. `reconciliation_holds` keeps `worst_delta` in the detail: AT-21 red.
- M-27. The hash tuple omits `validator_sink_shape`: AT-12 shape cell red.

## 9. Frozen contracts

- Route contract: validators no longer change a route, except under the two new codes. A non-callable partial sink with validators now refuses before work. Breaking line in `changelog.d/expect-off-route-s3.md`; compatibility contract entry for the two retired codes, the two new route codes and the two new runtime codes.
- Physical plan hash: unchanged for validator-free configs (AT-12). For configs with validators it gains `validator_sink_shape`, and the recorded route decision changes; goldens that record either are regenerated by name after a fixed-snapshot comparison across the two revisions.
- Output bytes: unchanged; only the route that writes them changes.
- Finding detail text: `reconciliation_holds` no longer prints the numeric delta (G5).
- Engine-owned staging: `ParquetTransactionalSink` and `StagingSink` gain `bind_writer`; unbound behavior is unchanged.
- `ValidationSession` loses `record_external_verdict` and `observe_pair` (pre-GA hard delete) and gains `expect_delivery` and `source_tap`. New execution names: `judged_run`, `observe_sink`, `validation_needs_resident`, `sink_shape`, `SinkShape`, `physical_validator_spec`. `run_fk_out_of_core` keeps its signature.

## 10. Class tables

### 10.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | messages name tables and codes only; `reconciliation_holds` detail drops the delta; string and numeric sentinels asserted absent | AT-1(d), AT-21 | M-26 |
| 2 | Cleanup missing on an exit path | verdict before every commit and every seal, inside the cast-owner scope; handoff and spill owned by the session `ExitStack` | AT-16, AT-15 cleanup cell | M-1, M-20 |
| 3 | State machine and concurrency | one owner per invocation, passed explicitly; one judge; feeding after the verdict or twice refuses; per-thread write guard | AT-6, AT-10, AT-11 | M-13, M-18a, M-18b |
| 4 | Route parity and silent fallback | every routing read deleted; one `sink_shape` with explicit `ABSENT`; exact allowlists; declines recorded before the byte estimate | AT-1(a), AT-2, AT-8 | M-5, M-12 |
| 5 | Referential integrity | keyed folds give the full-frame report on sequential and out-of-core | AT-7 | M-10, M-11 |
| 6 | Untrusted producer | sinks classified by shape and wrapped; engine staging refuses raw writes; expected set from the write loop; unexpected staged tables refuse | AT-6, AT-13 | M-3, M-7, M-19, M-19b, M-23, M-24 |
| 7 | Check then use (TOCTOU) on a path | the source is captured after cast where masking consumes it, never re-read; the spill is a private file created with `O_NOFOLLOW` and `0o600`, read only after its writer is closed | AT-15 | M-17 |
| 8 | Weak tests and overclaimed evidence | per-assertion before and after recorded; controls marked; memory measured from tap to close, Python and Arrow | AT-1, AT-4, AT-5 | M-2, M-4, M-9 |
| 9 | Behavior-preserving refactor drift | deleting the out-of-core collector keeps the report and the stamp, including for a direct caller | AT-7, AT-11 | M-6, M-18a |
| 10 | Frozen contract drift | retired codes tombstoned; hash pinned for validator-free configs and widened only with validators; Breaking line | AT-9, AT-12, AT-18 | M-8, M-22, M-27 |

### 10.2 Recurring-defect catalog

| Class | Applies | How |
|---|---|---|
| Fail-open deferral (section 3a) | yes | no owner tokens remain; every public entry binds its own session; AT-11, AT-20 |
| No exception context in output | yes | AT-6 asserts no cause or context |
| Normalized guard scanners | yes | the sentry walks the AST of every module under `execution/` |
| No reaching into private modules | yes | execution imports only `decoy_engine.validators` public names; validators imports no execution module |
| No hidden CI failures | yes | AT-5 carries the `perf` marker; result in the PR |
| No raised caps | yes | one reviewed census ceiling (`_transactional_sink.py`, 650); fan-out pin unchanged |

## 11. Enumerations

### 11.1 Exit paths

- Pass with a sink: `close` at commit returns; `sink.commit()` runs (`execution/_publication_observer.py:145`).
- Fail with a sink: `ValidatorFailedError` from `close` at `execution/_publication_observer.py:142`; the route unwind aborts and the cast owner discards sealed evidence (`execution/_sequential.py:658`).
- Fail without a sink: `judge_resident` raises before `seal_evidence` (`execution/_sequential.py:608`, `execution/out_of_core/_runner.py:360`) or before the generation result returns (`generation/_plan_entry.py:315`).
- Refusal at a write: raw write to bound engine staging; a table written twice.
- Refusal at commit: a non-proxy sink; an expected table unfed; an unexpected staged table.
- Refusal before reads: a partial sink with validators; a direct out-of-core call that needs resident (`execution/out_of_core/_runner.py:111`).
- Runtime refusals: `validator_table_not_observed`, `validator_source_pairing_mismatch`, `validator_key_state_over_budget`, `validator_rows_after_verdict`, `validator_table_rewritten`.
- Exception inside the run: bind scope exits without `close`; the sink aborts; handoff and spill are released.

### 11.2 Routes and entries

- Auto-chunk streamed (`execution/_chunked_output_sink.py:161`), its shared chunk iterator (`execution/_pipeline_auto_chunk.py:342`).
- Sequential with transactional, staged, callable and no sink (`execution/_sequential.py:625`).
- Out-of-core rewrite pass and stream driver, with and without sink, through the pipeline and by direct call (`execution/out_of_core/_runner.py:111`, `:362`).
- Multi-table split with sink (`execution/_pipeline_multi_table.py:306`).
- Mixed generate and mixed mask (`execution/_pipeline_mixed_route.py:224`).
- Streamed generation entries (`generation/_plan_entry.py:315`, `:376`).
- Standalone physical mask plan (`execution/physical/_compiler.py:439`).
- Resident, unified and physical routes: S2, unchanged.

### 11.3 FK shapes

- Single and composite FK.
- Nullable FK and orphan policies that null keys.
- Two parents; self-reference (out-of-core refusal, control).
- Child-first order at the session boundary with null and malformed dates; duplicate pending children.

### 11.4 Fields

- `validators` entries and their `columns`, `min_rows`, `pattern` parameters.
- `quarantine.enabled`.
- Sink shape (`ABSENT`, `TRANSACTIONAL`, `STAGED`, `CALLABLE`, `PARTIAL`).
- Source kind (`pa.Table`, `LazySource`, loader, loader-only `resolved_sources`), and declared casts on paired columns.

### 11.5 Output surfaces

- `ValidatorFailedError`, its value-free report and finding details.
- `quality_metrics["validation"]`, stamped on every entry.
- The quarantine reason column.
- Route reason codes (two new, one retired), runtime codes (two new, one retired).
- The recorded route decision and the plan hash token for configs with validators.

## 12. Slices

### S3 STREAMED-ROUTES

Steps, in order (tests first, red before code):

1. On the merged #812 head, confirm:
   - the S2 end state of section 1, including the ContextVar fix;
   - the expected-set source per route against its write loop, and that no route writes one table twice;
   - the in-flight batch bound per interleaved route;
   - the generation entries' `OutputPublish` path and the `bounded_write_batches` marker through the proxy;
   - the `S3_PENDING` and scan counts.
2. Write AT-1 to AT-21 and record, per assertion, the result before S3.
3. Move `sink_shape` to `_transactional_sink.py` and add `bind_writer`; add `execution/pipeline/_validated_sink.py` and `validators/_source_handoff.py`; `post_scan_sink_kind` unwraps.
4. `judged_run` in the four public entries and `execute_route`; `_run_fk_out_of_core_owned`; the new `OutputPublish`; `expect_delivery`; `observed_commit` checks, marks and closes; `judge_resident` before each seal; `_feed` refusals; callable delivery; the report stamp.
5. Taps at each site (5.4); sealed spill on the stream driver.
6. Delete every routing read (5.6) and the out-of-core collector (5.1); `physical_validator_spec`; the hash token; delete `S3_PENDING` and set both allowlists.
7. `reconciliation_holds` detail; retire the codes; changelog and compatibility contract.
8. Run M-1 to M-27; run AT-5 on the Dell.

Files and budgets. Module cap: goal 600, hard max 700, enforced by `tests/sentry/test_module_size.py`; package fan-out by `tests/sentry/layout/test_package_fanout.py`. Changed-source budget for the slice: about 950 lines. Counts are at `99d868347`.

| File | Now | After |
|---|---|---|
| `execution/pipeline/_validated_sink.py` | new | about 200 |
| `validators/_source_handoff.py` | new | about 150 |
| `validators/_session.py` | 387 | about 400 (external verdict and `observe_pair` out; expected set, tap, rewrite guard in) |
| `validators/_relationship_checks.py` | as measured | 1 line changed |
| `execution/_transactional_sink.py` | 598 | about 643 (census ceiling 650) |
| `execution/_sequential.py` | 680 | about 668 (classifier out, tap and judge in) |
| `execution/_pipeline_auto_chunk.py` | 600 | at most 600 (one-line tap; `_slices` moved) |
| `execution/_pipeline_route_dispatch.py` | 278 | about 320 |
| `execution/_publication_observer.py` | 202 | about 218 |
| `config/_post_scan.py` | 249 | about 260 |
| `execution/_pipeline_routing.py` | 566 | about 540 |
| `execution/_pipeline_routing_signals.py` | 613 | about 605 |
| `execution/_chunked_output_sink.py` | 600 | 598 |
| `execution/_pipeline_multi_table.py` | 465 | 464 |
| `execution/_pipeline_context.py` | 599 | about 592 |
| `generation/_plan_entry.py` | as measured | about +12 |
| `execution/out_of_core/_validate_batch.py` | 387 | deleted |
| `execution/out_of_core/_rewrite_pass.py`, `_stream_driver.py`, `_runner.py` | 392, 583, 393 | about the same: hooks out, taps, judge and owned entry in |
| `execution/physical/_snapshot.py`, `_inputs.py`, `_live_inputs.py`, `_compiler.py`, `_reasons.py` | 285, 377, 179, 451, as measured | each a few lines either way |
| `capacity.py`, `_job_estimate.py`, `pipeline/_lazy_input.py`, `_transforms_admission.py`, `_transforms_prepare.py`, `_unified_slice.py` | as measured | each a few fewer |
| `reasons/route/_part1.py`, `_retired.py`; `reasons/runtime/_part2.py`, `_part3.py` | 323, 20, 576, 565 | moves of a few lines |
| `tests/sentry/test_validators_do_not_route.py` | 243 | about 180 |

About +550 and -650 of source.

Public names added: `judged_run`, `observe_sink`, `validation_needs_resident`, `sink_shape`, `SinkShape`, `physical_validator_spec` (execution); `ValidationSession.expect_delivery`, `source_tap`; `bind_writer` on the two engine staging sinks. Removed: `ValidationSession.record_external_verdict`, `ValidationSession.observe_pair`.

Test depth: T0 per edit; T1 impact selection per commit (validators, execution routing, out-of-core, physical, post-scan, declared casting, generation streamed entries, the sentries); T2 on the exact head with AT-1, AT-6, AT-8, AT-11, AT-15, AT-16, AT-20, AT-21 and the mutations. Full suite: yes, once on the final head, because S3 changes a frozen contract (route contract, plan hash token), moves and deletes tests (`tests/parity/test_phase_d_d3a_validators_ooc.py` and the collector's tests, whose NaN fixture moves to AT-17), and touches the physical plan record (`testing.md` escalation triggers). It diffs against the saved main baseline.

### Dependencies and order

1. PR #812 (S2) merges first, with its three fixes. The ContextVar fix (section 1) is a hard prerequisite: at `99d868347` it is still open.
2. S3 builds on the merged head. It edits `generation/_plan_entry.py` (the two streamed entries only) and taps `_pipeline_auto_chunk.py`. GEN-STREAM-ALL S1b and S2 and GEN-NONFAKER-DRAWS S3a edit `generation/_streamed.py`, `_column_streams.py`, `window.py` and `synthesize.py`, not `_plan_entry.py`'s streamed entries, so the slices do not collide. Whichever lands second rebases; AT-20 runs on whatever generation route main has.
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
