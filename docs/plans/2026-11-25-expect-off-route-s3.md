Status: plan

# EXPECT-OFF-ROUTE S3: streamed routes judge validators, and validators stop picking a route

Rules consulted: `/home/cam/dev-rules/00-universal.md`, `/home/cam/dev-rules/risk-and-exceptions.md`, `/home/cam/dev-rules/development-loop.md`, `/home/cam/dev-rules/cross-cutting-concerns.md` (choke point, guard, mutation), `/home/cam/dev-rules/testing.md` (Test depth), `/home/cam/dev-rules/workspace-and-vcs.md` (Commit messages), the plan contract and defect catalog (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`), and the row's master plan rev 7 on the PR #812 branch (`docs/plans/2026-11-22-expect-off-route.md`: section 3a invariant, section 5 design notes, section 6 slices, sections 9 and 10).

Row: EXPECT-OFF-ROUTE (validators stop forcing pandas). Repo: decoy-engine. Risk: R2 (publication order, fail-open class, route contract, physical plan hash). Anchor: PR #812 (S2) at `99d868347` plus the fixes in flight in its worktree for three findings: standalone shadow runs skip validators, the verdict is not enforced on scope exit, and an ambient session judges the wrong config. S3 builds on the end state those fixes intend (section 1). Line numbers are from `99d868347` and move with the merge.

This file plans S3 in full. Section 11 outlines S4.

## 1. Frame and the S2 end state S3 assumes

After S2, every resident route is judged by one session (`validators/_session.py`), and the section 3a invariant holds: every delivered table is judged exactly once. S3 relies on these S2 facts. If #812 merges without one of them, S3 re-plans that step before it builds.

- `bind_validation_session` (`validators/_session.py:54`) binds the ContextVar for every run. A run whose config has no validators binds `None`, so a nested run never sees an outer run's session (the "ambient session" fix). At `99d868347` the no-validator branch still yields `None` without setting the ContextVar (`validators/_session.py:63-65`); the fix in flight must set it, and S3 does not start until it has (Dependencies).
- Leaving the bind scope normally calls `close()` unless a caller already did (`validators/_session.py:73`).
- `close()` (`validators/_session.py:271`) is the one judge. It refuses a table that is complete or deferred but never fed (`validator_table_not_observed`), and it raises `ValidatorFailedError` for a finding on a table no judge settled.
- The standalone shadow coordinator judges its own result unless `ShadowContext.validation_owner` names an owner (`execution/physical/_shadow_generation.py:285`). The standalone coordinator reads `PhysicalPlan.validators`, which the S2 compiler copies from `PhysicalPlanInputs.validators` (`execution/physical/_compiler.py:439`).

S2 still routes validator-bearing jobs to resident outside its narrow D3a out-of-core admission. The reads are pinned in `S3_PENDING` (`tests/sentry/test_validators_do_not_route.py:32`). `S3_PENDING` pins 55 identities, 67 occurrences and 19 modules; the scan itself finds 60 identities, 72 occurrences and 22 modules, the extra five being lifecycle storage sites (Routing inventory). Step 1 recounts both on the merged head. The out-of-core route keeps a second validator engine (`execution/out_of_core/_validate_batch.py`, 387 lines) that also protects a direct caller of the public `run_fk_out_of_core` (`execution/out_of_core/__init__.py:65`, `_validate_batch.py:326`) and records its verdict on the session with an owner token (`_validate_batch.py:387`).

## 2. Guarantee and non-goals

Guarantee:

- G1. A config with validators takes the same route, route reason and per-column backends as the same config without validators, on every route, except for the two decisions below:
  - `validators_need_transactional_sink`: the sink is a plain callable, so rows would leave before the verdict. An unsupported partial shape is refused before reads under the same code. Generation accepts its existing marked batch-only sink.
  - `validators_need_resident_rows`: quarantine is enabled with the validation_fail trigger. The bounded routes cannot remove rejected rows, so the resident quarantine path stays (it filters covered failures and succeeds).
- G2. No row reaches a committed sink, and no evidence is sealed, before the run's verdict. On a sink route a failing verdict raises `ValidatorFailedError` before `sink.commit()`, recorded as a validation failure, never as a COMMIT failure. On a no-sink route the verdict runs before `seal_evidence` and before the result is returned. This holds for every public entry that writes rows: `run_pipeline`, `run_fk_out_of_core`, `generate_tables_streamed` and `generate_tables_streamed_from_generation_plan`.
- G3. A streamed route's report equals whole-table validation of that route's delivered output (findings, counts, capped indices). On route-stable columns it equals the full-frame report. Where a route delivers different bytes for the same input, the report follows the delivered bytes: the documented case is a passed-through float NaN that survives out-of-core and becomes null on full frame (`tests/parity/SEMANTIC_DIFFERENCES.md:40`). AT-17 pins that exact report on both routes.
- G4. Validator memory on a streamed route stays bounded: per paired table, the source projections waiting for their output (bounded in memory, with private spill for delayed output), plus the fold state under the session's key-state ceiling.
- G5. No error, finding detail, quarantine reason or log text carries a cell value. S3 removes the one numeric leak it found: `reconciliation_holds` prints `worst_delta` in `finding.detail` (`validators/_relationship_checks.py:530`), which equals the parent cell when the child aggregate is zero.

Non-goals:

- S4 owns the run-card and CLI. Preserve the existing skipped-column warning.
- No streaming for quarantine, post-validation, fidelity report or declared casting on the chunked lane: those keep their own resident reasons (`execution/_chunked_output_sink.py:110-122`).
- No change to any verdict rule inside a validator module. The `reconciliation_holds` detail text changes; its verdict does not.
- No hardening against a hostile in-process writer (V1 threat model: accidental leaks only). Engine-owned staging refuses a raw write once the proxy owns it; a user-supplied four-member sink relies on every engine route holding only the proxy (AT-13).

## 3. Behavior and failure modes

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
| Enabled quarantine with validators and the validation_fail trigger | Resident, `validators_need_resident_rows`. |
| Sequential with no sink, a validator fails, declared casting | Verdict before `seal_evidence`; nothing sealed. |
| Out-of-core through the pipeline, with or without a sink | Out-of-core route; judged before commit or before seal. |
| Direct `run_fk_out_of_core` call | Fresh session; same verdicts; report stamped on success. |
| Nested public call with the same config object and other inputs | Fresh session; the outer session is untouched. |
| Paired check, interleaved route | Source tapped after cast and aligned to surviving rows. |
| Paired check, two-phase stream driver | Sealed private spill; stays out-of-core. |
| Output delayed beyond the memory window | Spill privately and replay incrementally. Disk-budget failure aborts and removes scratch. |
| Source rows differ in count from delivered rows | `validator_source_pairing_mismatch`; nothing committed. |
| A table written twice through the proxy | `validator_table_rewritten`. |
| A raw write to engine-owned staging after the proxy bound it | `validator_table_not_observed`, before the staged file is replaced. |
| `staged_tables()` differs from the expected set | `validator_table_not_observed` before seal or commit. |
| A write handle holds the raw user sink at commit | `observed_commit` refuses a non-proxy sink. |
| Rows fed after the verdict | `validator_rows_after_verdict`. |
| Zero-row table on a streamed route | The proxy feeds an empty table once; the table is judged. |
| `reconciliation_holds` fails | Finding detail names the check and table, no numeric delta. |
| Keyed state passes the ceiling | `validator_key_state_over_budget` before the next scoped write. |
| Sink returns with an unread tail | Incomplete write, validator_table_not_observed. Zero seals and commits. |
| Isolated resident run | Worker stages the judged result once for the parent. |
| No-sink full frame or mixed | Inert OutputPublish, judged resident result. |
| Eligible out-of-core job with an unrelated quarantine trigger | Same bounded route and ordinary verdict. |
| Generation with a marked batch-only sink | Bounded streaming with the same verdict and report as a four-member sink. |

## 4. Acceptance tests

Master plan numbers in brackets. A failure uses a reject-all `regex_match` (`pattern: "(?!)"`) unless stated, over a table with a seeded cell value `SECRET-CELL-7731`. The baseline labels below are expectations. In the PR record each observed assertion as baseline failure, passing control or new guard, then record its implementation-head result.

- AT-1 [V4 streamed rows]. Routes: auto-chunk streamed with `ParquetTransactionalSink` (120k rows); sequential FK with a transactional sink and with no sink; out-of-core FK with and without a sink; multi-table split with a sink; mixed route generate and mask. Each route checks:
  - (a) route label, route reason and per-column backends equal the same config without validators. Fails before S3 on the auto-chunk, sequential, split and mixed cells; the out-of-core cells are controls (S2's D3a lift).
  - (b) a passing validator gives `passed` results. Control.
  - (c) a failing validator raises `ValidatorFailedError` with the exact finding count (7 rejected rows), the inner `commit` is never called, staging is empty, and the failure record does not say COMMIT. Out-of-core cells are controls for the verdict (D3a already rejects) and fail before S3 on a new assertion: the shared publication guard judges before seal or commit, recorded by the event trace.
  - (d) `SECRET-CELL-7731` is absent from `str(exc)`, the serialized report, the failure record and captured logs.
- AT-2 [V4 callable row]. Sequential FK with a plain callable and validators: resident with `validators_need_transactional_sink`; a failing validator calls the callable zero times; a passing one calls it once per table after judgement and successful post-scan settle, with no session feed. Forced-sequential refuses with the forced-mode refusal naming the code. A post-scan block after a passing validation calls the callable zero times. A low resident budget refuses with the resident capacity refusal. A table-driven cell runs `sink_shape` on `None`, a plain callable, a non-callable partial, a three-member sink and a four-member sink, through `run_pipeline` and through `run_fk_out_of_core`, and checks: `None` keeps the route; the three-member sink never reaches out-of-core; the partial refuses before the first source read (the counting loader and a lazy resident-fallback source see zero reads including materialization and iteration).
- AT-3 [V4 readability rows]. `ParquetTransactionalSink` and an isolated `StagingSink`, each wrapped, with `post_scan.integrity`: no `POST_SCAN_INTEGRITY_SINK_UNREADABLE`; the integrity report shows the gate ran; the snapshot holds the inner sink kind and shape. Use the actual isolated worker and parent. Force full frame with its original staging sink. The parent receives the exact judged table once on pass and no table on rejection. Also exercise streamed staging with its no-op commit and abort.
- AT-4 [V5]. A 120k-row table with a sink, `email: truncate(length: 100)` (a no-op) and `leak_check(min_rows: 50)`. Source batches are 4,096 rows and sink batches 10,000. The check fails with the whole-table report of the delivered output on the streamed, sequential, out-of-core rewrite and out-of-core stream-driver routes, from a resident `pa.Table` source and from a lazy Parquet source. With `hash` it passes. Measure validator-owned Python peak and peak live Arrow bytes during replay with an isolated Arrow pool and its high-water counter. Exclude existing source and output buffers. Use a spill many times the window. Allow the window plus one projected IPC batch, one output slice and 64 KiB of overhead.
- AT-5 [V6, perf, Dell vm-run]. 2M rows streamed, `leak_check` and `regex_match`, every row failing: `retained_bytes()` under `2 * FINDING_INDEX_CAP * 8` plus 64 KiB plus the projection window; peak RSS within 64 MiB of the same run without validators; on the stream driver, spill payload bytes (sum of projected `nbytes`) are reported apart from the IPC file size, which adds schema and framing; wall time recorded.
- AT-6 [V7]. Completeness and exclusive writes, each refusing before commit with nothing committed and no exception context:
  - Two tables, A through the proxy and B written straight to the inner sink: on `ParquetTransactionalSink` the raw write refuses at once (`bind_writer`); on a four-member user sink with no `staged_tables`, commit refuses for B.
  - Same-name replacement: A through the proxy (passing), then a rejecting A of the same row count through the raw handle of `ParquetTransactionalSink`: the raw write refuses and the staged file is the judged one. The same replacement through the proxy refuses with `validator_table_rewritten`.
  - Unexpected staged table: only A expected, B staged on `ParquetTransactionalSink` through a test seam that bypasses `bind_writer`: commit refuses. Deleting the `staged_tables()` check turns this red.
  - Out-of-core asymmetric sets: a source-only table (in `sources`, not in the plan) is expected and refused when written raw; a plan-only table with no source is not expected and the run passes.
  - A three-member sink wrapped stays non-`TransactionalSink`; a four-member one stays one.
  - Rows fed after `close` raise `validator_rows_after_verdict`.
- AT-7 [V8]. `fk_intact`, `no_orphan_children`, `parent_window_respected` and `reconciliation_holds` on sequential and out-of-core give the full-frame report for single, composite, nullable and two-parent FKs. Out-of-core with an orphan policy that nulls orphan keys gives a `no_orphan_children` finding. Named cells at the session boundary (fed directly, child batches before parent batches):
  - child-first with a non-null FK and a null child date, and with a non-null FK and a malformed non-null date: report the malformed non-null row and skip the null row. Pin indices and count.
  - duplicate pending children: two child rows at distinct indices reference one parent key outside its window; both indices appear.
  - self-reference on out-of-core: the route refuses as today (control).
  - A key-state budget forced to 1 KiB refuses before the first scoped write.
- AT-8 [V9]. The routing sentry passes with `S3_PENDING` deleted. It fails on each seeded spelling (`config.get("validators")`, `if validators:`, a `validators_ooc_ready` name) in a copy of `_pipeline_routing.py`, on a raw `validators` read added beside an allowlisted storage site, and on a call to `validation_needs_resident` from an unlisted function.
- AT-9 [V14]. `route.validators_present` and `runtime.out_of_core_validators_not_admitted` resolve as retired; `ROUTE_VALIDATORS_PRESENT` is gone from the physical catalog; nothing in `src/` emits them.
- AT-10. Nesting, each against an outer bound run: an inner run with no validators commits without closing or feeding the outer session; an inner `run_pipeline` call with the same config object and different records binds its own session and leaves the outer session's fed tables unchanged. Fails before S3 on the head named in section 1 (ContextVar not cleared) unless the S2 fix has landed.
- AT-11 [V15f]. Direct `run_fk_out_of_core`, with a sink and without: a failing validator raises with nothing committed or returned (control for the raise; fails before S3 on the event trace); a passing validator stamps `quality_metrics["validation"]` with the exact check names and counts (baseline report control). Through `run_pipeline` the out-of-core runner receives the pipeline's session object (identity checked) and binds none.
- AT-12. Plan hash: for a validator-free config the hash is equal before and after S3 (control). For a config with validators, two sinks of one class with different shapes (callable and four-member) hash differently (fails before S3). For each instance compare live and physical replay route AND reason. Replay has no live sink. Expect callable resident under the new code and transactional bounded under its validator-free reason.
- AT-13. Every streamed writer reaches the proxy. On auto-chunk, split, mixed generate and mixed mask, spies on the inner sink's `write` and `write_batches` see only calls made from inside the proxy (the guard flag set), and the commit runs on the same proxy object built into the new `OutputPublish`. Assert actual fold feed counts, table names and row totals for every batch. A seam that writes through the original `publish.active_sink` makes `observed_commit` refuse before commit.
- AT-14. Empty tables, on streamed, sequential and out-of-core: a zero-row table beside a passing non-empty sibling passes, and the session's fed set includes the empty table. With the empty feed deleted, the same run fails with `validator_table_not_observed`. A zero-row table beside a rejecting sibling raises with the sibling's exact finding and no finding on the empty table.
- AT-15 [V5 extension]. Pairing:
  - A source that returns the same rows rotated by one on each read gives the report of the read masking consumed, on the rewrite pass and the stream driver.
  - A loader-only out-of-core table is paired.
  - A declared cast that changes the verdict pairs against the cast value (sequential and a declared auto-chunk lane with resident input and resident output).
  - Resident, lazy and loader-only sequential sources each pair.
  - A paired mixed-mask table pairs.
  - A source one row longer than the output refuses with `validator_source_pairing_mismatch`.
  - Run a real multi-batch no-sink rewrite and real streamed auto-chunk with unresolved schema past a two-batch window. Each spills, succeeds and matches whole-table validation of final output.
  - The stream driver with a paired check stays out-of-core.
  - Every spill segment has mode 0600 and is removed after pass, rejection, disk-budget refusal or producer failure. Force the shared disk cap during schema hold-back and assert zero commits.
- AT-16. Declared casting with a failing validator, on sequential and out-of-core: with either delivery shape count actual seal calls and inner commits. Both counts are zero on rejection. Each open sink aborts once and temporary evidence is removed. On pass record verdict before seal and seal before any commit. Cover declared staged re-entry through pipeline and direct calls. Assert the same session and proxy, one bind and one verdict.
- AT-17. NaN pass-through: a float column with NaN under `regex_match` rejecting `"nan"`. Out-of-core reports the NaN rows and full frame does not; the exact report is pinned for both routes (G3). New admission. The S2 parity fixture explicitly excludes out-of-core at line 866.
- AT-18. A standalone mask-plan run with a failing validator and no caller validation config raises `ValidatorFailedError`. Control (existing S2 test), kept so the `physical_validator_spec` move cannot break it.
- AT-19. Validators with quarantine: resident with `validators_need_resident_rows`; covered failures filtered and the run succeeds; no quarantine sidecar when an uncovered failure raises. Enable validation_fail for this cell. With only an unrelated trigger, keep an otherwise eligible job above resident capacity out-of-core. Pin passing route and reason and ordinary rejection on a failing check.
- AT-20. Streamed generation: `generate_tables_streamed` with a seven-row sequence, a reject-all validator and a bounded sink that consumes every batch: zero commits, one abort, `ValidatorFailedError`. The same through `generate_tables_streamed_from_generation_plan`. Cross both public entries with streamed and resident results and passing and failing checks. Use the existing floor-test BoundedSink (marker True, write_batches/commit/abort, no write). Its proxy has no write. Passing streams commit once. Passing resident calls return judged tables, failing resident calls raise before return. Read the exact validation block, check names and counts from each successful result. Test the conditional warnings member on a masked table in AT-26. Old positional construction gets independent empty metrics. Fails before S3 (commits once today).
- AT-21. Value-free numeric detail: `reconciliation_holds` with a parent value of `987654.321` and a child aggregate of zero fails; `987654.321` (and `987654`) is absent from the serialized finding, `str(exc)`, the failure record and, under quarantine, the quarantine reason column. Fails before S3.

- AT-22. A bounded generation sink reads one passing batch and returns with a rejecting final batch unread. Expect incomplete-write refusal, one abort, zero commits. Fully consumed passing control commits.
- AT-23. A and B both exhaust, both are observed, and their writes succeed. The sink reports only A staged. Expect refusal before seal or commit. Reporting both passes.
- AT-24. Sequential declared rendering quarantines a middle row on a format error. Run leak_check on another column with distinct source values. Compare surviving pairs, indices and report with an oracle using the kept rows. Cover sink and no-sink delivery and a later row-error drop.
- AT-25. No-sink full frame enters its publish block. No-sink mixed examines stream. Both return judged outputs. For dispatch completion, exercise a passing resident result with independently registered expectations and no earlier observer. Removing completion raises validator_table_not_observed on normal scope exit.
- AT-26. Import-linter passes without new ignores. Count one validation metrics writer. In a passing pipeline fixture explicitly name a keep column of a masked table in leak_check. Pin the existing serialized warning in the validation block. Guard both write APIs of the shared parquet writer through both facades.

## 5. Named mutations

Master plan numbers in brackets. Each must turn the named test red on the final head.

- M-1 [M3]. `observed_commit` commits before `close`: AT-20 streamed rejection commits (generation has no earlier seal).
- M-2 [M4]. The cursor restarts from the head of the handoff for each output slice: AT-4 red.
- M-3 [M5]. `_ObservedTransactional.write_batches` forwards without feeding: AT-13 actual feed counts or missing-feed refusal red.
- M-4 [M8]. The cursor reads the whole spill into memory on open: AT-4 stream-driver memory cell red.
- M-5 [M10]. `if validators: return False` back in `_sequential_eligible`: AT-8 and AT-1(a) sequential red.
- M-6 [M12]. Remove `complete_resident_validation` from `execute_route`: AT-25 healthy resident success becomes validator_table_not_observed on scope exit.
- M-7 [M13]. Put `write_batches` on `_ObservedStaged`: AT-6 protocol cell red.
- M-8 [M14]. `post_scan_sink_kind` returns the proxy token: AT-3 red.
- M-9 [M15]. A second observer of a table adds to its folds: in AT-1(c) run the split completion path on a table the proxy already completed. The healthy path counts seven failures. A second fold doubles the count.
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
- M-19. `observed_commit` ignores registered expectations and uses only `staged_tables()`: AT-6 four-member cell red.
- M-19b. `observed_commit` drops the unexpected-staged check: AT-6 unexpected-staged cell red.
- M-20. The no-sink verdict moves after `seal_evidence` on sequential: AT-16 sequential no-sink trace red.
- M-21. `validation_needs_resident` ignores quarantine: AT-19 red.
- M-22. `PhysicalPlanInputs.validators` left empty: AT-18 red.
- M-23. `bind_writer` is a no-op: AT-6 replacement cell red.
- M-24. The out-of-core expected set uses the plan tables, not the filtered order: AT-6 asymmetric cells red.
- M-25. The generation entries pass the raw sink: AT-20 red.
- M-26. `reconciliation_holds` keeps `worst_delta` in the detail: AT-21 red.
- M-27. The hash tuple omits `validator_sink_shape`: AT-12 shape cell red.

- M-28. Complete a write on return alone. AT-22 sees a prefix commit.
- M-29. Accept a proper subset of expected staged names. AT-23 sees a commit.
- M-30. Restore overflow refusal on the third queued batch. Both delayed consumers fail AT-15.
- M-31. Discard the render keep map. AT-24 loses alignment.
- M-32. Judge sink output only at commit. AT-16 counts a seal on rejection.
- M-33. Re-enter the public runner from declared staging. AT-16 sees another owner.
- M-34. Bind when wrapping the worker sink. AT-3 loses resident handoff.
- M-35. Set no-sink publish to None. Both AT-25 route bodies fail.
- M-36. Drop result metrics. AT-20 loses the successful report. Separately require write on the marked batch-only sink. AT-20 loses bounded success.
- M-37. Classify partial sinks after context construction. AT-2 sees a lazy fallback read.
- M-38. Replay with absent sink shape. AT-12 loses the callable reason.
- M-39. Decline every enabled quarantine. AT-19 loses bounded success.
- M-40. Add a duplicate allowed spec read. AT-8 counts two.
- M-41. Drop warnings from the stamp. AT-26 loses its warning.

## 6. Delivery and publication

### Reuse inventory

| Need | Existing implementation at the anchor |
|---|---|
| Session feed, paired sources, completion and verdict | validators/_session.py:172,195,231,271 |
| Resident completion and commit gate | execution/_pipeline_route_dispatch.py:76 and execution/_publication_observer.py:132 |
| Sink classification and identity | execution/_sequential.py:207 and config/_post_scan.py:211 |
| Shared staged writer and replacement | execution/_transactional_sink.py:182,313 |
| Validation metrics and warnings | execution/_pipeline_finalize.py:363,381 |
| Private scratch and replay | execution/out_of_core/_scratch.py:25,43 and _payload_store.py:77 |
| Value-free reason codes and test guards | reasons/runtime/_part3.py:99, reasons/route/_retired.py, tests/sentry/test_validators_do_not_route.py:32 |

### One owner and one judge

Keep the S2 bind at pipeline dispatch. Replace it with the public validators API `judged_run`. Direct `run_fk_out_of_core` and the two public streamed generation entries open the same scope. Every independent invocation binds fresh, including binding None for a validator-free run. Internal delegates receive the owner explicitly, including an owner with no session. Never infer ownership from an ambient session or a config hash. Use the existing separate `resolve_budget` key-state ceiling. Do not charge folds to the generation ledger.

Pass the owner and its sink to a private owned out-of-core runner. Pipeline dispatch and the public runner both call it. At `_runner.py:197`, pass the owned continuation to `run_staged`. Forward only its declared arguments, including the owner, proxy, typed sources, arena and staged flag. No second bind, wrap, expectation reset or seal on return from this delegation.

Register expected table names before processing, independently of sink inventory and returned outputs. Use the writer's actual iteration domain: sequential's `table_topo_order(plan, graph)`, out-of-core's source-filtered `_table_order`, generation's selected generated tables, and the dispatched plus resident output names for mixed and split. Register each table's delivery mode when the route selects it. At normal exit even an unobserved registered resident table fails closed. Preserve S2's settled quarantine verdict on unfiltered resident rows. Complete remaining resident observations after assembly using `complete_resident_validation`. Never fold a table twice.

### One observed write per table

With validators bound, route all staged writes through the owner's proxy, including both `ctx.sink` and `ctx.publish.active_sink`. Replace the context publisher before it opens, preserving its stream and post-validation settings. With no sink keep `ctx.sink=None` and an inert `OutputPublish(None, ...)`. With a resident callable keep that publisher inert and retain the original callable for delivery once per table in plan order, after the verdict and successful settle. A block at either gate calls it zero times. Direct generation retains its documented resident-result semantics.

Use narrow proxy classes for whole-table, batch-only and full writers. Forward supported attributes including bounded marker, staged openers and evidence. Unwrap via the existing `post_scan_sink_kind` with cycle protection. Check owner/proxy identity at publication. A raw sink or a proxy belonging to another run refuses. For engine sinks bind the exclusive writer at the actual staging open, before input can be written: OutputPublish.open for publish routes, and the owned staging entry for sequential and direct out-of-core. Include sequential whole-table writes. Wrapping alone never binds. Resident isolated staging at `_isolated_worker.py:120` then writes the already judged outputs through its original sink. Enforce ownership once in `StagedParquetWriter` at both write methods, before any replacement. The facades delegate binding just as they delegate writes (`_transactional_sink.py:401`, `_isolated_common.py:449`). Scope a token to the forwarded write and current thread. Revoke it on transaction exit. Preserve ordinary unbound writes.

Claim each table once at write entry. A repeated write raises `validator_table_rewritten`. Whole-table write completes only after a successful feed and inner return. For batch writes feed exactly the batches the sink pulls after final reconciliation. The iterator records normal upstream exhaustion ONLY when the consumer asks for the next item and encounters end of stream. A never-started iterator, a prefix, generator close, producer exception or sink exception cannot complete a write. Do not probe or drain after sink return. On genuinely empty exhaustion feed the schema's empty table once. Only successful inner return plus exhaustion plus successful observation calls `table_complete`. Latch a failed or incomplete write so later commit cannot accept it. Raise `validator_table_not_observed` for incomplete writes.

### Guard before seal and again before commit

One guard compares the registered names with the independently completed deliveries. For staging, require the registered staged set to equal successful staged writes and, if supported, `set(sink.staged_tables())`. Check both missing and extra names even if both tables fed. Never complete a table from its name or planned row count. Verify source cursors are exhausted. Then `ValidationSession.close()` judges the folds. Cache the verdict, including refusal. Repeat the identity and set checks at commit without folding again. New feeds after verdict raise `validator_rows_after_verdict`.

Sequential and out-of-core call the guard inside the cast owner's cleanup scope immediately before `seal_evidence` (`_sequential.py:608`, `out_of_core/_runner.py:359`). For resident delivery feed assembled tables first. For streamed full-frame output bypass the resident validation call on its empty result mapping (_pipeline_full_frame.py:290). A mixed or split result with an earlier observer must never settle missing feeds through an empty resident finalize. The session owns the combined report. Apply the same ordering to full-frame's two `cast_run.finish()` paths and mixed's finish, retaining the existing resident finalize and post-scan gates. With no seal the guard still runs before publication or return. In `observed_commit` keep `gate.before_commit`, then the shared guard before commit evidence and the inner commit try. On rejection abort any open staging once, remove temporary evidence and scratch. A later seal or commit failure follows the existing cast-owner cleanup. A rejected validator never creates a sealed artifact or COMMIT failure record.

### Generation and reports

At `generation/_plan_entry.py:315,376` judge the prepared pinned config and pass the owner's proxy to `run_generation`. Preserve the two entries' different plan verification contracts. Keep the bounded-marker admission at `generation/_streamed.py:103`. A sink with the marker exactly True, callable write_batches, commit and abort, and no write remains supported for generation with validators. Its proxy exposes only those methods. A resident result is judged before return. Append `quality_metrics: dict[str, Any] = field(default_factory=dict)` after the last defaulted field of frozen GenerationResult. Use the per-result mapping or dataclasses.replace after judgement. Preserve existing positional arguments, receipt, row counts and resident tables.

Move the existing `stamp_validation` and warning construction from `execution/_pipeline_finalize.py:363,381` to the public validators report API. Pass the existing QualityWarning constructor from the caller so validators has no upward import of generation.pool. Execution and generation call the same writer with the stored report once. Keep both validators and conditional warnings in the metrics block. Delete the second writer at `out_of_core/_validate_batch.py:380`. Delete that collector, both pre-emit delivery hooks, `record_external_verdict` and the external table set. Keep S2's resident settlement and owned deferral. Remove unused `observe_pair` once all folds use the session cursor.

## 7. Paired sources and resource bounds

Tap only the columns the fold needs from the typed rows masking actually consumed. Never reopen caller_sources, even for a loader-only resolved source. Keep stream observation on the final output at the sink and resident observation on the assembled table. Align by row offset across differing batch boundaries. Missing source, premature end and leftover rows are pairing mismatches. Generated-only tables retain their normal source-free behavior.

Use one ordered spillable handoff per paired table. Start with a two-batch memory window of compact projections; split large input tables into bounded chunks before enqueue. Keep a bounded window of projected batches. When the consumer lags, write bounded private IPC segments in FIFO order. Close each segment before it can be replayed. Older segments always precede newer rows, including when the producer resumes during replay. Read one bounded batch at a time and release consumed segments. Keep segment metadata bounded too (monotonic read/write sequence numbers). Compact projected slices when needed so a small slice cannot retain a whole input allocation. Legitimate lag never triggers pairing mismatch. Use this handoff for schema hold-back in auto-chunk (`_chunked_output_sink.py:587`), full resident assembly in the no-sink rewrite (`_rewrite_pass.py:269`), and phase-one capture followed by phase-two replay in the stream driver. That driver aligns both joins to payload row_nr_start (`_stream_driver.py:436`).

- Auto-chunk, split and mixed mask capture the actual chunk after declared wrapping and before masking. Resident declared lanes use the cast renderer's surviving typed rows. The streamed declared lane keeps its existing refusal.
- Sequential retains the paired projection immediately after load_table. Share the keep map produced by post_mask with render_table's caller at `_boundary.py:378`; remap errors as today. Apply that exact selection to the typed projection. Then apply the existing row-error quarantine mask at `_sequential.py:553` to the same projection in rendered coordinates. Enqueue only survivors, sliced into bounded batches, before writing or storing the final output. Identity and all-dropped selections are valid. Use the existing resident table's projected view during masking.
- Out-of-core captures cast, compacted rows beside collect_batch_vault (`_rewrite_pass.py:236`, `_stream_driver.py:373`), including loader-only sources. Feed only after final reconciliation at emit or resident assembly. No validator tap on intermediate joined rows.

Provide scratch access and the budget from the route to the session. Reuse the existing private scratch arena and open_private/close_private behavior (0600 file, protected directory, no symlink following). For routes without a scratch root acquire a protected run arena lazily on first spill. Include actual segment bytes and IPC framing in the shared temp-disk budget, including declared staging in the same arena. Check on each segment, before further staging. Use fixed, value-free runtime failures on disk errors or budget refusal. Close writers, readers and remove segments on pass, rejection, refusal and producer exceptions through the run ExitStack. Account for a window, one replay batch and an output slice separately from keyed folds and existing resident route buffers.

## 8. Admission, replay and routing inventory

Classify the raw sink before any loader, profiling, context construction, lazy fallback, source preparation or provider work. Pipeline context can materialize a resident fallback at `_pipeline_context.py:354`. Apply the same preflight to direct public entries and physical capture. Use the same classifier before wrapping on every entry. Pass its immutable shape into the shared decision function; never pass the live sink into replay.

| Shape | Members | Validator policy |
|---|---|---|
| ABSENT | None | Existing route |
| TRANSACTIONAL | callable write, write_batches, commit, abort | Existing route and delivery capability |
| STAGED | callable write, commit, abort | Existing whole-table staging, ineligible for batch routes |
| BATCH_ONLY | marked bounded, callable write_batches, commit, abort, no write | Generation supports streaming. Pipeline and direct out-of-core refuse this incomplete protocol before reads. |
| CALLABLE | plain callable without staging members | Pipeline returns resident under validators_need_transactional_sink, then delivers after settle |
| PARTIAL | other incomplete or invalid staging shape | Refuse before reads under validators_need_transactional_sink |

Preserve unvalidated entry behavior. Use one pure decision on config, captured shape and entry contract. Return no restriction, resident with reason, or refuse with reason. Check invalid shapes first. For otherwise supported pipeline sinks use the callable reason first, then validators_need_resident_rows only for enabled quarantine with validation_fail among its triggers. Share the trigger predicate used for finding_index_cap (`validators/_fold.py:127`). Preserve all independent quarantine, casting, post-scan and capacity rules. A forced bounded mode or direct bounded entry refuses a resident-only decision before work. A resident capacity failure retains the decision reason. Direct generation returns its resident tables for a callable. OWNER CALL for direct generation with validation_fail: default to pre-provider refusal under validators_need_resident_rows since the producer has no quarantine-filtering stage. AT-19 also pins this direct-entry refusal; run_pipeline keeps the resident filtering path. Enforce the decision in both layer-1 routing and output-mode selection so fallback cannot stream a callable or skip row filtering. Keep forced-mode refusals and resident-fit checks ahead of resident execution.

Capture validator_sink_shape in PhysicalPlanInputs from the raw capabilities (ABSENT for the live no-sink unified builder). Live and physical layer1_route call the same pure decision with the same config, shape and pipeline contract. Carry its action and reason through transform preparation, bounded estimates and the shared router before the byte-estimate branch. No compiler needs a live sink. Include the shape token in the hash tuple only when the config has validators. Validator-free hashes stay byte-identical. Keep PhysicalPlan.validators for standalone execution. Preserve versioned stored reads wherever these inputs are serialized; derive absent only for known no-sink inputs, recapture legacy ambiguous shapes before replay.

Remove all blanket validator declines and D3a eligibility signals from _pipeline_routing, _pipeline_routing_signals, _chunked_output_sink, _pipeline_multi_table, _pipeline_context, _job_estimate, capacity, pipeline/_lazy_input, _transforms_admission, _transforms_prepare, _unified_slice, physical/_compiler and both out-of-core drivers. Retire route.validators_present and runtime.out_of_core_validators_not_admitted in the existing family registries and remove ROUTE_VALIDATORS_PRESENT from physical/_reasons. Register the two new route codes and both new runtime codes there. Use existing codes for missing observation, pairing mismatch and keyed-state budget. Messages may name structure. Never include cell values, numeric deltas, URL credentials or raw exception text in evidence, quarantine, errors or logs. Remove worst_delta from reconciliation_holds detail at _relationship_checks.py:530; quarantine.py:112 copies that detail directly.

### Counted sentry

Recount the starting 55 pinned identities / 67 occurrences / 19 modules and 60 scanned / 72 / 22 on the merged #812 head. Delete S3_PENDING. Use exact Counter equality with normalized module, qualified scope, AST operation and count. Pin each listed AST operation once in its scope, including both compiler operations. For each builder count one helper call and one validators keyword. No module-wide exemption.

| Module and scope | Allowed operation, once each |
|---|---|
| validators spec helper physical_validator_spec | config.get("validators"), return detached tuple |
| validators decision helper validation_needs_resident | call physical_validator_spec to test presence |
| physical/_snapshot.capture_physical_plan_inputs | validators keyword from physical_validator_spec(config) |
| physical/_live_inputs.build_live_physical_plan_inputs | same keyword and helper call; remove old validators parameter and _unified_slice keyword |
| physical/_inputs.PhysicalPlanInputs | validators field |
| physical/_compiler.compile_physical_plan | inputs.validators attribute and validators keyword |
| physical/_plan.PhysicalPlan | validators field |
| physical/_shadow_coordinator._validated | plan.validators attribute to enforcer |
| physical/_shadow_generation.enforce_validators | literal validators key in reconstructed config and config.get("validators") for ownership |

For conditional hashing use the captured optional token (None for a validator-free config) without another spec read. Derive presence at capture from the spec already retrieved. Capture and live builders call the helper once each. Keep lower-layer session/fold configuration outside the execution-routing scan. Extend it explicitly to the two new spec helpers and generation entry wiring. Pin resolved public lifecycle calls by caller and count separately: the four public run scopes (pipeline at execute_route), the proxy factory in judged_run, resident completion in dispatch, active session in observed_commit, and the S2 active/observe/settle calls in finalize, mixed and the standalone shadow enforcer. Only submission/capture preflight and shared route policy may consult the decision. Pin each concrete call edge at implementation review with its exact count, including direct admission, live, estimate and physical replay. A checked caller never gets a wildcard allowance for reads inside its helpers. AT-8 seeds alias spellings, another read of the same kind in an allowed function, and an unauthorized decision call. Missing and extra edges both fail.

## 9. Placement, compatibility and budgets

| Item | CODEMAP placement | Scope |
|---|---|---|
| validators/_validated_sink.py | Job-level validator framework | Public judged_run, proxy and shape classifier, immutable admission decision. Move _sequential.py:207 classifier here. Export via decoy_engine.validators. |
| validators/_source_handoff.py | Job-level validator framework | Session-owned ordered cursor, injected scratch access |
| validators/_session.py and validators public facade | Job-level validator framework | Expectations, verdict, shared report writer and its warning builder |
| execution/pipeline and existing route modules | Run lifecycle and dispatch | Route decisions, scratch injection, publisher installation, settle and callable delivery. No new direct execution module. |
| execution/_transactional_sink.py and _isolated_common.py | Transactional and isolated sinks | Shared StagedParquetWriter guard, two thin binding delegates |
| declared_casting/_boundary.py | Declared rendering | Expose kept indices from the same render for sequential |
| generation/_plan_entry.py and _streamed.py | Plan-only entries and bounded generation | Two entry wrappers and additive frozen result field |
| reasons/route and reasons/runtime | Code registries | Existing catalogs and retired catalogs; add runtime/_retired.py only if absent |
| tests/unit/validators, tests/unit/execution/judgement, tests/unit/generation, tests/parity, tests/physical, tests/sentry | Tests beside their owning concern | Route, worker, resource, report and architectural guards |

Generation and execution import the validators facade. Validators imports neither execution nor generation. Supply constructor and scratch dependencies at the caller. Export the existing scratch operations through their owning public API wherever they cross a package boundary. Keep existing public signatures, including run_fk_out_of_core. Share the writer and stamp at the sites above; AT-26 guards placement and reuse. Update CODEMAP, compatibility contract, semantic differences and changelog. Report route/reason and hash changes, retired codes, additive generation metrics and removal of value-bearing finding detail. Pin route-specific output differences such as NaN in AT-17. Preserve fixed-seed behavior per route.

Implementation projections in lines, based on 99d868347. Measure actual final counts with the size sentry. Goal 600, hard cap 700. A fresh dense entry uses min(700, actual + 20): 643 gives 663. Existing entries follow the sentry's growth rules. Avoid raising existing pins. Extract cohesive helpers into the named packages if needed.

| File or group | Baseline | Projected |
|---|---:|---:|
| validators/_validated_sink.py, _source_handoff.py | new | 230, 190 |
| validators/_session.py, _relationship_checks.py | 387, 567 | 445, detail-only edit |
| execution/_transactional_sink.py, _isolated_common.py | 598, 474 | up to 643, 480 |
| generation/_streamed.py, _plan_entry.py | 600, 386 | at most 600 by moving entry/result support if needed, 425 |
| declared_casting/_boundary.py | 524 | 535 |
| execution/_pipeline_finalize.py, _pipeline.py | 532, 361 | 505, 370 |
| execution/_sequential.py, _pipeline_auto_chunk.py | 680, 600 | 675, at most 600 by moving _slices beside its helper |
| execution/_pipeline_route_dispatch.py, _publication_observer.py | 278, 202 | 325, 218 |
| config/_post_scan.py, execution/_pipeline_routing.py, _pipeline_routing_signals.py | 249, 566, 613 | 260, 545, 605 |
| execution/_chunked_output_sink.py, _pipeline_multi_table.py, _pipeline_context.py | 600, 465, 599 | 600, 464, 598 |
| execution/out_of_core/_validate_batch.py | 387 | deleted |
| execution/out_of_core/_rewrite_pass.py, _stream_driver.py, _runner.py | 392, 583, 393 | about 395, 585, 405 |
| execution/physical/_snapshot.py, _inputs.py, _live_inputs.py, _compiler.py | 285, 377, 179, 451 | within 12 of baseline each |
| capacity, estimates, lazy input, transform gates, unified slice, physical reasons, reason catalogs | existing | small edits within current ceiling |
| execution/_pipeline_full_frame.py, _pipeline_mixed_route.py | 348, 333 | about 358, 340 |
| tests/sentry/test_validators_do_not_route.py | 243 | about 245 |

Allow about 1,250 changed source lines including the collector deletion. Reconcile measured line counts, churn, fan-out and fresh dense census on final head. Keep generation at 600 through a small cohesive move or reduction on the measured head. No flat package expansion beyond its cap.

### Defect classes, reuse and proof

| Class | Boundary and reused code | Proof | Mutation |
|---|---|---|---|
| Value-bearing output | Value-free finding shared by error and quarantine reason | AT-1(d), AT-21 | M-26 |
| Cleanup and publication | Cast owner and ExitStack, observed_abort on open sinks | AT-15, AT-16 | M-20, M-32 |
| State and concurrency | Explicit session and shared writer token. At AT-6 hold a forwarded write open with a barrier and reject a raw write from a second thread | AT-3, AT-6, AT-10 | M-18b, M-23, M-34 |
| Routing and silent fallback | Shared classifier, decision and replay token | AT-2, AT-8, AT-12, AT-19 | M-12, M-38, M-39 |
| Referential integrity | Existing keyed folds. Cover composite, nullable, self-reference, multiple parents and cross-batch children | AT-7 | M-10, M-11 |
| Incomplete or unobserved output | Registered deliveries, exhausted writes and exact staged inventory | AT-6, AT-22, AT-23 | M-19, M-28, M-29 |
| Source identity and path access | Captured typed projection, private segments under a held scratch arena | AT-4, AT-15, AT-24 | M-17, M-30, M-31 |
| Test validity | Count fold calls, peak allocations, actual seals and inner commits | AT-4, AT-13, AT-16 | M-3, M-4, M-32 |
| Refactor drift | One resident judge, shared report writer and isolated handoff | AT-3, AT-11, AT-25, AT-26 | M-6, M-34, M-41 |
| Public contract drift | GenerationResult field walk and physical snapshot parity | AT-12, AT-18, AT-20 | M-22, M-27, M-36 |

Walk GenerationResult fields in AT-20: mode, reason, row_counts, tables, peak_reserved_bytes, declines, publication_receipt and quality_metrics. Preserve defaults and old field positions. Enumerate externally visible outputs: returned tables, staged and committed files, caller callbacks, worker envelope, quarantine records and evidence, serialized report and warnings, error text, failure records and captured logs.

Apply the recurring-defect catalog on the implementation head. Keep whole-cell fullmatch semantics. Validate stored shape tokens as strict enum members; the bounded marker requires literal True. Preserve versioned reader compatibility at any persisted boundary. Raise sanitized refusals outside exception handlers and assert empty cause and context. Exercise separate verified-plan and pinned-generation entry contracts. Normalize aliases in guard scans, enforce public imports, check each allowlisted helper body, and record visible CI outcomes for the exact head. No raised existing limits or scanner pins.

## 10. Implementation order and evidence

1. Merge PR #812 with all three fixes from section 1. Verify fresh None binding, scope exit enforcement and standalone shadow validation on that actual head. Recount the routing scanner and trace each expected table set to the writer loop.
2. Write AT-1 through AT-26 first. Record baseline per assertion, including controls, new admissions and new guards whose evidence comes from mutation. Never infer a red result from an absent test.
3. Land the lower-layer API, result field, narrow proxies and writer guard. Connect ownership, pre-seal checks, commit guard and post-settle delivery. Preserve original report and warning shape. Then connect typed source handoffs, render selections, private spill and cleanup.
4. Feed the early immutable decision through live and captured inputs. Remove the collector and blanket routing reads. Land counted sentries, reason tombstones, compatibility docs and value-free reconciliation detail.
5. T0 per edit. T1 per commit covers validators, route and physical parity, out-of-core, casting, isolated worker, generation, post-scan and size, import and routing sentries. T2 on the exact implementation head runs all ATs, including AT-5 on the Dell, and M-1 through M-41 (including suffixed IDs). For every mutation record the assertion that changed from green to red. Restore it and rerun green. Run the full suite against the saved main baseline on the final head. Regenerate only named physical goldens after comparing fixed snapshots. Preserve the R2 independent implementation reviews.

Dependencies: S2 is first. GEN-STREAM-ALL S1b/S2 and GEN-NONFAKER-DRAWS S3a touch generation, including _streamed.py. Rebase the second change and repeat both public entry matrices on the resulting head. S4 follows S3. Its CLI half needs the engine release.

## 11. Handoff to S4

S3 supplies the validation report and its existing skipped-column warning. Section 17 outlines how S4 presents them after the engine release.

## 12. Frozen contracts

- Compare route, reason and column backends with the validator-free run. Section 8 defines the six sink shapes and the two permitted reasons. Existing capacity, forced-mode and route-specific gates still apply.
- Capture the raw sink shape for physical replay. Include its token in the hash only for validator-bearing configs. Keep validator-free hashes byte-identical. Compare live and replay decisions on a fixed snapshot before updating any named golden (AT-12).
- Preserve fixed-seed output on each route. Judge the rows that route delivers. AT-17 pins the different NaN reports on out-of-core and full frame.
- Judge before evidence seal, commit or resident return. Keep the post-scan gate ahead of commit. A resident pipeline callable runs once per table after both verdict and settle. Direct resident generation returns its tables.
- Bind the engine writer at staging open. Both sink facades delegate to the same writer. An isolated worker can still stage its judged resident result once for the parent (AT-3, AT-26).
- Export the run owner, shape classifier, decision, spec helper and report writer through `decoy_engine.validators`. The session owns expectations, paired source taps and resident settlement. Remove `record_external_verdict` and the unused `observe_pair`. Keep the public out-of-core signature and both generation entry contracts.
- Append `quality_metrics` after `publication_receipt` on frozen `GenerationResult`. Old positional calls get independent empty mappings. Successful judged calls use the shared validation stamp, including conditional warnings (AT-20, AT-26).
- Record both retired codes, the two new route codes and the two new runtime codes in the compatibility contract. Document the partial-sink refusal, hash change, additive result field and value-free reconciliation detail in the changelog.

## 13. Class tables

### 13.1 Plan contract catalog

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Remove the numeric delta where the finding is built, before errors and quarantine copy it. | AT-1(d), AT-21 | M-26 |
| 2 | Cleanup missing on an exit path | Guard inside cast cleanup before seal. Guard again at commit. Abort open staging once and release spill segments. | AT-15, AT-16, AT-20 | M-1, M-20, M-32 |
| 3 | State machine and concurrency | Each public run binds fresh. Internal staging keeps its owner. The shared writer checks a thread-scoped token. Close caches the verdict. | AT-3, AT-6, AT-10, AT-11, AT-16 | M-13, M-18a, M-18b, M-23, M-33, M-34 |
| 4 | Route parity and silent fallback | Decide from raw shape before reads. Replay the captured shape. Test the quarantine trigger and count allowed routing reads. | AT-1(a), AT-2, AT-8, AT-12, AT-19 | M-5, M-12, M-37 through M-40 |
| 5 | Referential integrity | Shared keyed folds retain child indices and distinguish null from malformed dates across batches. | AT-7 | M-10, M-11 |
| 6 | Untrusted producer | Claim each write once. Require exhaustion and successful return for batches. Match staged names exactly where inventory exists. | AT-6, AT-13, AT-14, AT-22, AT-23 | M-3, M-15, M-19, M-19b, M-24, M-28, M-29 |
| 7 | Check then use (TOCTOU) on a path | Capture typed survivors on the masking read. Close private spill segments before replay under the held arena. | AT-4, AT-15, AT-24 | M-4, M-17, M-30, M-31 |
| 8 | Weak tests and overclaimed evidence | Count real feeds, seals and inner commits. Measure live Python and Arrow allocations. Record baseline controls separately. | AT-1(c), AT-4, AT-5, AT-13, AT-16 | M-3, M-4, M-9, M-32 |
| 9 | Behavior-preserving refactor drift | Complete resident tables once. Keep the isolated handoff, sink readability and warning stamp when the collector goes. | AT-3, AT-11, AT-25, AT-26 | M-6, M-8, M-34, M-35, M-41 |
| 10 | Frozen contract drift | Keep code tombstones, standalone plan validators, conditional hash and positional generation result fields. Preserve the batch-only generation protocol. | AT-9, AT-12, AT-18, AT-20 | M-22, M-27, M-36, M-38 |

### 13.2 Recurring-defect catalog

| Class | Implementation check |
|---|---|
| Anchored validation | Keep whole-cell regex matching in `validators/_generic.py:54`. Check a trailing newline against a literal pattern. |
| Strict wire and stored types | Check stored shape tokens against the enum. Reject wrong types on write and read. Require literal True for the bounded marker. |
| No exception context | Raise sanitized refusals outside the handler. Check the message, cause and context (AT-6). |
| Versioned read models | At a persisted boundary derive the reader from the writer. Check missing and unknown versions under the existing compatibility rules. Recapture ambiguous legacy sink shapes. |
| Normalized guard scanners | Count normalized operations by module and scope. Seed aliases, duplicate reads and unauthorized calls (AT-8, M-40). |
| No private-module imports | Execution and generation use the validators facade. Inject scratch access and the warning constructor. Run import-linter (AT-26). |
| No hidden CI failures | Record each required check and exit status. Run the marked AT-5 on the Dell and record its measurements. |
| One trust class per entry point | Keep verified-plan preparation separate from trusted pinned-generation preparation. Exercise both through their public calls (AT-20). |
| Mutations on the final head | Record the exact implementation head and failing assertion for each section 5 mutation. Restore and rerun green. |
| Checked allowlisted helpers | Pin each helper definition and caller by qualified identity and count. Scan the helper body (AT-8). |
| No raised pins | Use section 9 and the existing size and fan-out sentries. For a fresh dense file at 643 lines the ceiling is 663. |
| Fail-open deferral | Register expected delivery independently and check normal scope exit. Pass the owner through declared staging (AT-11, AT-16, AT-25). |

## 14. Enumerations

### 14.1 Exit paths

- On pass, finish observations and source pairing before the verdict. Guard before any seal, including full-frame and mixed cast finish. At commit run the post-scan gate, recheck identity and sets, then enter the inner commit handler (`execution/_publication_observer.py:132`).
- On validation rejection, raise before seal, commit or return. Abort open staging once and remove temporary evidence. Record a validation failure. Preserve cast-owner cleanup for a later seal or commit failure (AT-16).
- On a resident pipeline pass, deliver to a callable only after post-scan settle. A validator or post-scan block yields zero calls. Resident generation returns judged tables (AT-2, AT-20).
- Refuse an incomplete or repeated write, raw access to bound staging, a foreign proxy, missing observation, or a staged inventory mismatch. Check a proper subset as well as extras (AT-6, AT-22, AT-23).
- On pairing mismatch, key or disk budget failure, or producer exception, unwind through the owner. Release readers, private segments and the staging token. A refused or partial write cannot later commit (AT-7, AT-15, AT-22).
- Refuse invalid shapes and direct bounded requests that require resident execution before reads or provider work. Preserve forced-mode and resident-capacity refusals (AT-2, AT-19).

### 14.2 Routes and entries

- Auto-chunk, split and mixed mask observe final batches through the installed publisher. Mixed generate and resident siblings use the same owner (AT-1, AT-13).
- Sequential covers staged output, no sink and resident callable fallback. Apply both render and later row-error selections before pairing (`declared_casting/_boundary.py:378`, `execution/_sequential.py:553`).
- Pipeline and direct out-of-core use the same owned runner for rewrite and stream-driver delivery. Declared staged re-entry retains the owner and proxy (`execution/out_of_core/_runner.py:197`).
- Full-frame and mixed no-sink runs retain an inert publisher. Isolated resident output reaches the original worker staging sink after judgement (`execution/_isolated_worker.py:120`).
- Both streamed generation entries cover streamed and resident outcomes. Preserve their separate preparation steps (`generation/_plan_entry.py:315`, `generation/_plan_entry.py:376`).
- Unified live routing and physical replay use the captured policy inputs. Standalone shadow execution still reads the compiled validator spec (AT-12, AT-18).

### 14.3 FK shapes

- AT-7 covers single, composite and nullable keys, two parents, and orphan policies that null keys.
- Keep the existing out-of-core self-reference refusal as a control.
- Feed children first. Pin duplicate child indices and distinguish null dates from malformed non-null dates at the session boundary.

### 14.4 Fields

- Validator inputs include columns, regex pattern and minimum row count. Read quarantine enablement together with membership of `validation_fail` in its triggers.
- Classify ABSENT, TRANSACTIONAL, STAGED, BATCH_ONLY, CALLABLE and PARTIAL. Section 8 defines admission per entry. Include the captured shape in the validator-bearing hash.
- Cover resident, lazy, loader-only and declared-cast inputs. Apply keep indices in the coordinate system of each filter. Generated-only tables need no source cursor.
- AT-20 walks every existing generation result field in section 9 and the appended metrics field. AT-26 checks the warning in the serialized validation block.

### 14.5 Output surfaces

- Returned tables and callbacks, staged and committed files, the worker envelope, receipts and sealed evidence.
- Validation findings, `str(exc)`, failure records, captured logs and the quarantine reason column. AT-1(d) and AT-21 check string and numeric sentinels.
- Successful result metrics with validator names, counts and conditional warnings. Reports follow the delivered rows, including the route-specific NaN case.
- Route reasons and runtime refusals in the family registries. The captured route, reason, backend choices and plan hash are replay surfaces.

## 15. Slices

### S3 STREAMED-ROUTES

1. Verify the three S2 prerequisites on the merged head. Recount pinned and scanned routing reads. Trace each expected set to its writer loop.
2. Write AT-1 through AT-26 first. Record the baseline by assertion, including passing controls and guards that need mutation evidence.
3. Place ownership and sink classification in `validators/_validated_sink.py`. Add the result field, narrow proxies and shared staged-writer guard. Wire explicit ownership through dispatch, direct entries and declared staging.
4. Install the publisher, register expectations and complete each delivery once. Guard before seal and again before commit. Deliver resident callables after settle. Move the report and warning stamp to validators.
5. Connect `validators/_source_handoff.py` to the actual typed inputs. Apply both sequential keep selections. Exercise delayed consumers, bounded replay and shared disk-budget cleanup.
6. Connect early admission, live routing and physical replay. Remove the duplicate out-of-core collector and old routing reads. Land the counted sentry, code tombstones, value-free detail and compatibility updates.
7. Use the placement and per-file budgets in section 9. Allow about 1,250 changed source lines including the 387-line deletion. Keep generation/_streamed.py at most 600 lines. Measure final size and fan-out with the existing sentries.
8. Run T0 per edit and T1 per commit. On the final implementation head run all 26 ATs, including AT-5 on the Dell. Run every section 5 mutation through M-41, including M-18a, M-18b and M-19b. Record each red assertion and restored green result. Compare the full suite with the saved main baseline. Apply the independent reviews in section 10.

### Dependencies and order

1. S2 must merge with normal scope-exit enforcement, fresh binding for validator-free runs and standalone shadow validation. Check all three on the merge head.
2. S3 and the GEN-STREAM-ALL and GEN-NONFAKER-DRAWS slices touch generation. Rebase whichever lands second. Repeat both public generation entry matrices on that head.
3. S4 follows S3. Its CLI work depends on an engine release containing S1 through S3.

## 16. Pre-mortem

- A sink returns after reading a passing prefix. Require observed exhaustion and successful inner return. AT-22 expects one abort and zero commits.
- A sink omits a staged table that was fully observed. Compare its inventory with registered staged names before seal and commit (AT-23).
- A worker binds on wrap and blocks its own resident handoff. Bind only at actual staging open. AT-3 exercises the real worker and parent.
- Declared staging re-enters a public runner, or a nested call borrows the ambient session. Pass the existing owner to the internal continuation. Bind each independent run fresh (AT-10, AT-11, AT-16).
- Deferred output exceeds the memory window. Replay closed private segments in FIFO order. Align stream-driver batches by payload row offset. Charge actual bytes to the shared disk budget and clean up on refusal (AT-4, AT-15).
- A middle row disappears during declared rendering. Apply its keep map before the later row-error mask. Compare with the surviving-row oracle (AT-24).
- A replay loses the callable reason, or an unrelated quarantine trigger forces resident execution. Compare live and captured decisions and run the bounded case above resident capacity (AT-12, AT-19).
- Collector removal loses a finding or warning. Compare exact reports on delivered rows, preserve the NaN case and check the shared warning stamp (AT-7, AT-11, AT-17, AT-26).
- A rejection seals evidence or creates a COMMIT failure record. Trace real seals and inner commits under both delivery shapes (AT-1(c), AT-16).

## 17. S4 outline

Carry the existing skipped-column warning to the QA rows, strategy guide and compatibility docs. CLI adds the Checks fact and validation member for success and failure, the keep-column diagnostic, JSON snapshot and language guide examples. Master tests V10 to V12. OWNER CALL: default card wording is “Checks  N passed” or “Checks  1 failed: <check> <table.column>”.
