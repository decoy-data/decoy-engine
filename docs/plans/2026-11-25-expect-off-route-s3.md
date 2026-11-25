# EXPECT-OFF-ROUTE S3: validators on the streamed and bounded routes

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
reuse-first, catalogs/recurring-defects; owner notes on the V1 threat model, the value-free class
(F31), plan-defines-acceptance-tests and the V1 fast path default.

Row: EXPECT-OFF-ROUTE. Parent plan: `docs/plans/2026-11-22-expect-off-route.md` rev 6 at
`6d92ab3d7` on branch `origin/plan/expect-off-route` (sections 4, 5, 9 and 10; slice S3
"STREAMED-ROUTES"). The parent path is not on #812. This file splits S3 into two PRs, S3a and S3b,
and adds the lessons from the S2 review rounds on PR #812.

Risk: R3 (route change, commit ordering, plan hash, tombstoned reason codes). Size: S3a about
+120, -260; S3b about +230, -200. Depends on S2 (PR #812) merged. Anchor: #812 head
`83f1fe077`; every line number below is from that head. The builder re-anchors on the S2 merge
commit first.

## Problem

After S2, validators run on the route chosen for the resident routes, but:

- the streamed and bounded routes still decline a validator-bearing job. About 60 reads remain,
  pinned in `S3_PENDING` (`tests/sentry/test_validators_do_not_route.py:32`), for example
  `_pipeline_routing.py:145` (`VALIDATORS_PRESENT`), `_chunked_output_sink.py:114`,
  `_pipeline_multi_table.py:151`, and the out-of-core allowlists
  (`out_of_core/_validate_batch.py:152`, `:188`);
- out-of-core keeps its own collector (`out_of_core/_validate_batch.py:201`) and raises from
  `finish_validation` (`:366`) after the drivers have written every batch, so the docs tell users
  to pick a `TransactionalSink` (S2 `docs/strategies.md` paragraph);
- validation does not finish inside `observed_commit` (`_publication_observer.py:132-150`), so
  there is no single point that makes a failed check a validation failure and never a COMMIT
  failure.

## Guarantee

After S3a: on the out-of-core route (with no sink or a `TransactionalSink`) the run's one
`ValidationSession` folds every delivered batch and the no-sink table, and the runner calls the
enforcing `verdict()` before it seals anything. `observed_commit` calls `verdict()` after
`gate.before_commit` and before `sink.commit()`. A validator failure commits and seals nothing.

After S3b: a validator-bearing job runs the same route, with the same route reason and per-column
backends, as the same job without validators, on every route in parent section 4, except the
plain-callable case of exception 1b. `S3_PENDING` is deleted and the sentry allowlist holds
exactly the entries in the S3a and S3b allowlist table.

Non-goals:

- No CLI change (S4). The `leak_check_column_not_checked` warning already exists in
  `quality_metrics` (`_pipeline_finalize.py:363-387`); S4 adds it to the run warnings.
- No change to any verdict rule. Parity V1 stays a control.
- No new validator, and no change to the quarantine route (exception 1a stays resident).

## What exists (reuse, do not rebuild)

- `validators/_session.py` (292 lines at #812): `observe`, `observe_published`, `observe_pair`,
  `observe_unobserved`, `observe_source_batches`, `table_complete`, `finish` (idempotent),
  `_check_pairing`; `bind_validation_session` and `active_validation_session` (`:48-54`).
- `_pipeline_route_dispatch.py`: `execute_route` (`:109`) binds the session; resident completion
  `complete_resident_validation` (`:76`).
- `_publication_observer.observed_commit` (`:132`) with the post-scan gate call at `:142`.
- `config/_post_scan.post_scan_sink_kind` (`:211`), the one sink-kind resolver.
- `_pipeline_sources.resolve_sequential_loader` with its `tee` (`:127-159`).
- The S2 sentry `tests/sentry/test_validators_do_not_route.py` (243 lines) and its exact
  `S3_PENDING` Counter.

## Lessons from the S2 review (PR #812, rounds 1 to 3), applied here

| S2 finding | Rule for S3 | Where it is tested |
|---|---|---|
| Validators judged bytes before the render | Folds observe the batch the sink receives, after declared formatting and `post_mask`. The proxy sits at the sink, so this holds by construction | V4 streamed rows with a format-sensitive `regex_match` |
| Sentry pinned modules, not sites | `S3_PENDING` only shrinks; S3a removes the out-of-core rows; S3b deletes the table. The allowlist is exact `(path, function, public name)` | V9 |
| A table was fed twice (out-of-core then resident) | The first complete observer owns the fold; later observers count-check only | V4 split row; spy on `observe_unobserved` |
| Lazy source read whole | Paired sources read one batch at a time; a length mismatch raises `validator_source_pairing_mismatch` | V5 counter |
| Callable delivery half-built | Callable delivery after validation lands in S3b with `validators_need_transactional_sink`, not before | V4 callable row |
| Shadow coordinator ignored failures | Every driver raises on a failing report before it returns | V4 physical rows (kept) |
| Error text carried values | Errors name the entry index, table, column and code only | V13 control extended to the new codes |

## Design

### Shared rules for both PRs

- One folding owner per table. The session gets `claim(table, owner)` before the first batch of
  that table. Only the owner's feed appends to the fold; any other observer calls
  `check_count(table, n, stage)`, which compares row counts and never appends
  (`validators/_session.py:149-158,240-247` append unconditionally today). `stage` names what
  was counted: the resident quarantine path validates unfiltered rows and returns filtered rows
  (`_pipeline_finalize.py:398-415`), so a later count-check of a quarantine-filtered table
  compares against the filtered count the finalizer records, not the validated count.
- Enforcing verdict. `finish()` keeps its contract: it builds and returns the report, pass or
  fail, because public `validate()` and resident quarantine use the failing report
  (`validators/_session.py:258-269`, `validators/_registry.py:257-261,284-287`). A new
  `session.verdict()` calls `finish()` and raises `ValidatorFailedError` when the report fails.
  Every route-side check point calls `verdict()`, never `finish()`.
- Run boundary. `bind_validation_session` binds `None` for a validator-free run and restores the
  previous token on exit (`_session.py:63-71` leaves the outer session visible today). Internal
  dispatch passes the owning session explicitly to the out-of-core runner and to its staged
  recursion (`out_of_core/_runner.py:194-202`); the runner never reads an ambient session. A
  public call to the runner opens and binds its own session.
- Expected tables. The session records each table the driver reports writing, with the row
  count from the driver's own write accounting. `verdict()` compares: a written table with no
  observation, or fewer observed rows than written, raises `validator_table_not_observed`. A
  zero-row table with a schema (`_chunked_output_sink.py:588-592`) is observed with zero rows.
  This lands in S3a, the first PR where a driver can write a table the session did not see.
- Sink shape has one owner. The classification at `_sequential.py:207-224`, the protocol check at
  `_chunked_output_sink.py:99-102` and the stream check at `pipeline/_stream.py:89-101` become one
  function, `sink_capability(sink)`, in the lowest layer that `.importlinter:21-25` lets all three
  callers import. It is not a new `execution/` module (that directory is frozen at 103 modules,
  `tests/sentry/layout/test_package_fanout.py:28-38,62-79`). The builder reads the layer
  contract first and names the module in the PR body. The proxy in `validators/` never imports
  it: `execute_route` computes the capability and passes it to `observe_sink(sink, session,
  capability)`.
- Whole-table validators. A registered whole-table validator receives every output table and may
  read any source, in one call at run finish (`validators/_registry.py:143-147,175-191`). On a
  route that writes in batches, the session spills each output table's batches, and the source
  columns the job declares, to Arrow IPC in protected scratch, then calls the function once after
  the last table, with complete mappings, and removes the scratch on every exit. Before it loads
  the spill it compares the spilled bytes with the resident budget and raises
  `validator_whole_table_over_budget` (new runtime code) when the call would not fit. This is a
  refusal at verdict time, not a route change. The memory of the call itself is the size of the
  tables, as it is on the resident route; the plan says so in the docs.

### S3a: out-of-core on the session

1. Eligibility. `_sequential_eligible` (`_pipeline_routing.py:140-145`) mixes structural rules
   with the `VALIDATORS_PRESENT` veto. The out-of-core selectors
   (`:368-375,390-394,432-439,471-474`) and the bounded-admission prepass (`:203-212`, which feeds
   `pipeline/_lazy_input.py:50-56,115-125,144-158` and is reached from CLI
   `cli/run/_execute.py:459-469`) move to `_structurally_sequential`, which reads no validator. In
   S3a the veto narrows: it still applies to the sequential route choice, and to out-of-core only
   when `sink_capability` is not a `TransactionalSink` and not "no sink" (a callable or
   three-method sink would fail at `_emit.py:106,128`). S3b deletes the veto. The
   `validation_fail` quarantine exclusion from `_validate_batch.py:166-169` becomes one shared
   guard, `quarantine_needs_resident(config)`, called by routing and by the runner before its
   first read.
2. Observation, sink exit. The final payload is observed in `_emit.py` before any rendering-side
   change the sink does not see: after `maybe_render` and after sink-schema reconciliation
   (`_emit.py:104-109,122-128`, after `_rewrite_pass.py:243-255`). The rewrite driver passes the
   scoped raw projection with each batch. The reorder driver consumes raw rows in phase one and
   emits in phase three (`_stream_driver.py:289-292,331-338,430-455`); it writes the scoped raw
   projection and row positions to its existing protected scratch in phase one and reads them
   back beside each emitted batch. Paired tables call `observe_pair`, others `observe_published`.
3. Observation, no-sink exit. With no sink, `_rewrite_pass.py:250-280` assembles the final table
   without `_emit`. The runner observes that assembled table, its aligned source projection and,
   for an empty table, the schema-bearing empty table, before the verdict.
4. Verdict point. The runner calls `session.verdict()` before `seal_evidence`
   (`out_of_core/_runner.py:359-374`), on the sink exit and the no-sink return. Nothing is sealed
   after a failure, the abort owner at `:374-376` is unchanged, and the quarantine cleanup order
   holds. `observed_commit` calls `session.verdict()` after `gate.before_commit` (`:142`) and
   before it reads evidence (`:98-101`) or enters `try: sink.commit()` (`:143`). On out-of-core
   that second call returns the cached result.
5. Delete `out_of_core/_validate_batch.py`. Remove the collector construction (`_runner.py:216`),
   the keyword-map entry (`:322`) and the finish call (`:359`), and the `validators` parameters at
   `_rewrite_pass.py:93` and `_stream_driver.py:154`. Lower the out-of-core fan-out pin from 44 to
   43 (`test_package_fanout.py:28-38,62-79`). Move the imports of the deleted module in
   `test_phase_d_d3a_validators_ooc.py:34`, `test_delivered_bytes_validation.py:22` and
   `test_fold_review_round2.py:185` to the session, keeping their behavior assertions.
6. Routing: `validators_ooc_safe` leaves `decide_execution_route` (`_pipeline_routing.py:300,432`)
   and its forwarding in `_pipeline_routing_signals.py:547,598`; the local `validators_ooc_ready`
   at `_pipeline_routing.py:339-340` goes.
7. Tombstone `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`) in a
   new runtime `_retired.py`, imported at `reasons/runtime/__init__.py:5-9`, with no `replaced_by`
   (parent line 165). Today a tombstone needs a live `replaced_by`
   (`tests/unit/test_reason_tombstones.py:8-21`, `scripts/release/reason_manifest_policy.py:42-43,363-373`)
   and the registry serializes two fields (`reasons/_registry.py:183-184`). S3a adds the
   `no_successor: str` field as the only other allowed form: the record, its serialization (an old
   manifest without the field reads as null), the release policy's pending-retirement check, the
   tombstone test and the manifest pin all change in this PR. The parent's route tombstone in S3b
   uses the same form.
8. Sentry. `S3_PENDING` drops the out-of-core and `validators_ooc_*` rows. The allowlist and its
   caller checks are exact per PR (below); a seeded aliased call from any other function fails.
   Docs keep the `TransactionalSink` guidance (`docs/strategies.md:2389-2391`). Changelog
   `Breaking:` line for the route change. V13 covers the two new codes.

Sentry allowlist, `(path, function, public name)`:

| PR | Entry |
|---|---|
| S3a | `execution/_pipeline_route_dispatch.py`, `execute_route`, `bind_validation_session` |
| S3a | `execution/_publication_observer.py`, `observed_commit`, `active_validation_session` |
| S3a | `execution/out_of_core/_runner.py`, the public runner entry, `bind_validation_session` |
| S3a | `execution/_pipeline_routing.py`, `_sequential_eligible`, `quarantine_needs_resident` |
| S3b | `execution/_pipeline_route_dispatch.py`, `execute_route`, `observe_sink` |
| S3b | `execution/_sequential.py`, `execute_sequential_route`, `ValidationSession.tee_reader` |
| S3b | `execution/_pipeline.py`, `run_pipeline`, `validators_need_resident` |

The builder confirms each function name on the re-anchored base and keeps this table exact.

### S3b: the write proxy and the remaining declines

1. Sink requirement before routing. `validators_need_resident(config, capability)` is a pure
   function, computed in `_pipeline.py` before the route is decided and emitted (`:358-360`) and
   before any route-specific early exit. A plain callable with validators on a route that would
   stream takes resident with `route.validators_need_transactional_sink`. After `settle`, a
   passing run calls the callable once per table. The value is part of the plan identity (item 6).
2. Proxy. `validators/_sink.py` (new, about 150): `observe_sink(sink, session, capability)` returns
   the shape the capability names. Only `write` and `write_batches` observe. `__getattr__`
   forwards only names the inner sink has. A read-only `inner_sink` marker;
   `post_scan_sink_kind` follows it with cycle protection.
3. Where the proxy goes. `_pipeline_context.py:267` captures the sink in `ctx.publish` before
   dispatch, and full-frame dispatch and output-mode selection use that publisher
   (`_pipeline_full_frame.py:194-195`, `_pipeline_generate_mask.py:183-196`). `execute_route`
   swaps the proxy into the publisher that writes, `ctx.publish.sink`, so there is no second
   reference to the raw sink. A unit test asserts every write on the auto-chunk route reaches the
   proxy.
4. Owners. Before the first batch, `execute_route` claims each table: the proxy on streamed
   routes, the driver on out-of-core. With a sink on out-of-core, the proxy only count-checks.
5. Sequential pairing. `_sequential.py:408-410,538-565` casts and filters rows after the loader
   tee. The tee keeps the retained row positions with the scoped raw projection, and the session
   pairs each output row with its typed source row by position, not by output offset. The
   sequential verdict runs before evidence is sealed and before the quarantine sidecar is
   published (`_sequential.py:608,639-654`, `pipeline/_post_scan.py:563-571`). The loader runs
   once per table.
6. Plan hash. The physical hash takes two config inputs (`physical/_inputs.py:315-324`): the
   plan's `pipeline_config_hash` (which includes validators, `plan/_compile.py:434,633-654`) and
   the canonical config. S3b computes a physical-only digest of each with `validators:` removed;
   the public semantic digest `pipeline_config_hash` is unchanged. The physical hash adds the
   value of `validators_need_resident`, because a callable sink with validators changes the route.
   The resident-fit identity (`:367-370`) stays.
7. Delete every remaining `S3_PENDING` site and the table. Refusals that do not involve
   validators keep the same reason with or without validators: mixed streamed and resident
   output (`_pipeline_multi_table.py:343-350`), streamed auto-chunk with declared formatting
   (`_chunked_output_sink.py:105-115`), out-of-core self-reference (`out_of_core/_compat.py:504-519`).
8. Tombstone `route.validators_present` (`reasons/route/_part1.py:306`) with `no_successor`, as
   parent line 165 says; delete `ROUTE_VALIDATORS_PRESENT` (`physical/_reasons.py:56,101,343`).
9. Docs, compatibility contract, changelog `Breaking:` lines (route, plan hash). V13 covers the
   new route code.

Generation: parent line 84 keeps `generate_tables_streamed` out of scope, and S3 does too. The
supported generation case is pipeline generation with a sink (`_pipeline_generate_mask.py:128-139`),
which is resident and stays covered by the S2 rows.

Choke points:

- Commit: `observed_commit` calls `verdict()`. Guard: V15 on the streamed route (S3b), where the
  first failing verdict is at the commit seam. Mutations M3, M18.
- Observation: one claimed owner per table; one publisher. Guard: V7, the split row, the
  publisher test. Mutations M5, M13, M15.
- No routing on validators: the sentry with exact caller checks. Guard: V9. Mutations M6, M10, M20.

Design notes: the proxy is the decorator shape the repo uses for publication evidence. Spilling
whole-table input to Arrow IPC is the established way to give a once-per-table function its
input without holding batches in memory during the run.

### Placement

| New or changed | Path | CODEMAP rule ("Job-level validator framework" row added by S1) | Sits beside |
|---|---|---|---|
| Write proxy | `src/decoy_engine/validators/_sink.py` | private modules in `src/decoy_engine/validators/` | `_session.py` |
| Sink capability | existing module in the lowest layer all callers may import (builder names it) | no new `execution/` module | `_sequential.py` |
| Commit verdict | `src/decoy_engine/execution/_publication_observer.py` | existing module | |
| Route and driver edits | `src/decoy_engine/execution/` files above | existing modules | |
| Tombstone form | `reasons/_registry.py`, `scripts/release/reason_manifest_policy.py` | existing | |
| Unit tests | `tests/unit/validators/test_sink_proxy.py`, `tests/unit/execution/test_streamed_validation_routes.py`, `test_out_of_core_session_validation.py` | route tests in `tests/unit/execution/` | `test_resident_validation_routes.py` |
| Sentry | `tests/sentry/test_validators_do_not_route.py` | `tests/sentry/` | |

Module sizes: `_chunked_output_sink.py` is at 600 and only shrinks; `_stream_driver.py` (583)
stays under 600 (budget +15, offset by the removed parameter); `_pipeline_routing.py` (566)
shrinks; `_pipeline_routing_signals.py` is 613 under a 633 ceiling (`test_module_size.py:98`)
and shrinks; if it reaches 600 its census entry goes (`:239-248`). `_session.py` gains `claim`,
`check_count`, `verdict`, expected tables and the spill (about +80, to about 372).

## Behavior and failure modes

| Case | Expected | Test |
|---|---|---|
| Out-of-core with a `TransactionalSink`, failing validator | Raise before seal and commit; staging empty; no COMMIT record | V4(c) |
| Out-of-core, no sink, pass and fail | Assembled table observed; fail raises before seal, no quarantine artifact | V4(c) no-sink rows |
| Out-of-core with a callable or three-method sink, validators (S3a) | Route as on #812 (veto still applies); no `AttributeError` | V22 |
| Lazy FK job over the resident budget, `resident_fallback=True` | Out-of-core, nothing loaded whole | V23 |
| Public runner called directly, failing validator | Own session; raise; no commit | V18 |
| Public runner with `validation_fail` quarantine | Refused before any read | V18 |
| Out-of-core by forced, row-threshold and byte-estimate selectors | Out-of-core, as without validators | V17 |
| Quarantine `validation_fail` with validators | Resident, as on #812 | V17 control |
| Nested validator-free job inside a sink callback | Outer session untouched and restored | V19 |
| Whole-table validator, two tables, several batches, undeclared source column read | One call with complete mappings; scratch removed; over budget raises | V20 |
| Streamed sink run, plain callable | Resident with `validators_need_transactional_sink`; 0 calls on fail, 1 per table on pass | V4 callable |
| Write bypasses the proxy; one batch skipped | `validator_table_not_observed` | V7 |
| Sequential, a middle row removed by the cast filter | Correct pairing by position | V5 sequential row |
| Sequential, no sink, later validator failure | Raise before seal and before the sidecar is published | V4 sequential no-sink row |
| Auto-chunk route writes | Every write reaches the proxy | publisher test |
| Mixed output, streamed auto-chunk with formatting, out-of-core self-reference | Same refusal with and without validators | refusal parity rows |
| Two configs differing only in validators, transactional sink | Same physical hash; different semantic digest | V21 |

## Acceptance tests (red first)

Each PR has its own list. Each row is marked red-before (a behavior assertion fails on the base),
pin (passes on the base and must keep passing) or new API (no red claim).

S3a:

| Test | Mark | Assertion |
|---|---|---|
| V4(c) sink rows | pin (`test_phase_d_d3a_validators_ooc.py:1215-1229`) | raise before seal, no commit |
| V4(c) no-sink rows | red-before for validators D3a refuses; pin otherwise | assembled table judged |
| V8 out-of-core rows (single, composite, nullable, two-parent, child-first, orphan policy) | red-before for `leak_check` and `parent_window_respected` | report equals full frame |
| V16 rendered bytes | pin (`test_delivered_bytes_validation.py:104-120`), extended to both drivers and asserting the observed Arrow schema | verdict on reconciled payload |
| V17 eligibility (three selectors) | red-before | route label equals the no-validator run |
| V18 direct runner | pin for enforcement (`_validate_batch.py:330-342`); new API for the own-session path | raise, no commit; quarantine refusal before read |
| V19 nested run | red-before | outer session object identical after the nested run |
| V20 whole-table validator | red-before (out-of-core declines today) | one call, complete mappings, scratch removed, over-budget raise |
| V22 sink shapes on S3a | pin | callable and three-method sinks behave as on #812 |
| V23 lazy prepass | red-before | no whole-table load (counter on `_lazy_input` materialize) |
| V7 expected tables | red-before for bypass and skipped batch; pin for zero-row | `validator_table_not_observed` |
| V13 | extended to `validator_table_not_observed`, `validator_whole_table_over_budget` | no value in any message |
| V14 runtime tombstone | new API | both tombstone forms load; old manifest without the field reads |
| V9 | red-before for caller checks | allowlist exact; seeded alias fails |

S3b:

| Test | Mark | Assertion |
|---|---|---|
| V4 streamed, sequential and callable rows | red-before (route declines) | route equals no-validator run; raise before commit |
| V4 resident unified and mixed rows | pin (`test_resident_validation_routes.py:108,171`) | unchanged |
| V4 readability rows | mutation control (parent line 273) | wrapped sinks readable |
| V15 commit seam | red-before on the streamed route | recording sink: `write`, `write`, `abort`, no `commit`, no COMMIT record |
| V5 pairing | red-before | loader once per table; middle-row removal pairs correctly; short and long sources raise |
| V6 performance | measured on the Dell node with `vm-run`, with `retained_bytes()` (parent line 275) | within the parent's budget |
| V6 keyed cell | new assertion: refusal before the first scoped write (the existing `test_fold_state.py:54-66` proves only refusal after some rows) | |
| V8 sequential rows, including self-reference | red-before | report equals full frame |
| V9 | `S3_PENDING` deleted; S3b entries exact | |
| V13 | extended to `route.validators_need_transactional_sink` | |
| V14 route tombstone | new API | |
| V21 plan hash | red-before | two independently compiled plans |
| Publisher test | red-before | every auto-chunk write passes the proxy |
| Split-owner test | new API | one fold per table |
| Refusal parity rows | pin | same reason with and without validators |

Mutations. M1 to M16 keep the meaning given in parent section 10; the ones this slice must kill
are listed with their PR. New IDs start at M18.

| ID | PR | Mutation | Test that must fail |
|---|---|---|---|
| M3 | S3b | `observed_commit` commits before `verdict()` | V15 |
| M4 | S3b | Source reader slices from offset 0 each batch (distinct data per batch) | V5 |
| M5 | S3b | `write_batches` forwards without observing | V7, V4 streamed rows |
| M6 | S3b | `config.get("validators")` re-added to `cheap_admission` | V4 unified row, V9 |
| M8 | S3b | Source reader reads the whole lazy source before the first batch | V5 counter |
| M9 | S3a | One pending child per parent key | V8 child-first duplicate-key cell |
| M10 | S3b | `if validators: return False` in `_sequential_eligible` | V9, V4 sequential row |
| M12 | S3b | Remove resident completion from `execute_route` | V4 sequential no-sink, V7 |
| M13 | S3b | `write_batches` on the three-member proxy | V7 protocol cell |
| M14 | S3b | `post_scan_sink_kind` returns the proxy class | V4 readability rows |
| M15 | S3b | A second observer adds to a table's folds | split V4 row |
| M16 | S3a | Drop `raw_is_null` from pending `parent_window_respected` | V8 null and malformed cell |
| M18 | S3b | `observed_commit` calls `finish()` instead of `verdict()` | V15 (commit runs on a failing report) |
| M19 | S3a | Observe before `maybe_render` in `_emit.py` | V16 |
| M20 | S3a | Allow an aliased caller of a lifecycle identity | V9 seeded call |
| M21 | S3a | Keep one stale out-of-core `S3_PENDING` row | V9 stale-pin check (`test_validators_do_not_route.py:201-203`) |
| M22a | S3a | Do not bind `None` for a validator-free run | V19 (nested run feeds the outer session) |
| M22b | S3a | Do not restore the outer token | V19 (outer session gone after the nested run) |
| M23 | S3a | Runner without a bound session skips validation | V18 |
| M24 | S3a | Count expected tables from the observer | V7 bypass case |
| M25 | S3b | Keep `validators:` in the physical digests | V21 |
| M26 | S3a | No-sink exit skips the assembled-table observation | V4(c) no-sink fail row |
| M27 | S3a | Prepass keeps the validator veto | V23 |
| M28 | S3b | Proxy not swapped into `ctx.publish` | publisher test |

## Enumerations

### Exit paths

- `observed_commit` (`_publication_observer.py:132`): gate refusal; `ValidatorFailedError` from
  `finish` (new); `validator_table_not_observed` (new); commit exception (recorded as COMMIT).
- Out-of-core runner (`out_of_core/_runner.py:359-374`): `session.verdict()` before seal, on
  the sink and no-sink exits.
- Sequential executor: verdict before seal and before the quarantine sidecar.
- Whole-table call: `validator_whole_table_over_budget` before loading the spill.
- `execute_route` (`_pipeline_route_dispatch.py:109`, resident completion at `:149`): raises
  for resident routes with no sink.
- Whole-table spill: scratch removed on success and failure.
- `observe_source_batches`: `validator_source_pairing_mismatch`. Fold append:
  `validator_key_state_over_budget`.

### Routes

From parent section 4. S3a touches only the out-of-core rows; S3b the rest.

- Unified slice, auto-chunk resident, full frame, mixed: resident, unchanged since S2.
- Physical full-frame, mixed and generation drivers: unchanged since S2.
- Auto-chunk streamed with a sink (`_chunked_output_sink.py:114`): S3b.
- Sequential FK with and without a sink (`_pipeline_routing.py:97`): S3b.
- Out-of-core FK with and without a sink, by the forced, row-threshold and byte-estimate
  selectors (`_pipeline_routing.py:339-340,368-375,390-394,432-439`): S3a.
- Public out-of-core runner called directly (`physical/drivers/_out_of_core.py:67-73`): S3a.
- Multi-table split (`_pipeline_multi_table.py:151`): S3b; the mixed-output refusal stays.
- Standalone `generate_tables_streamed`: out of scope (parent line 84).
- Plain callable sink on a streamed route: S3b, resident with `validators_need_transactional_sink`.
- Quarantine `validation_fail`: stays resident (exception 1a).

### FK shapes

As in V8, on the sequential and out-of-core routes (self-reference on sequential only; out-of-core
refuses it at `out_of_core/_compat.py:504-519`):

- Single-column FK.
- Composite FK.
- Nullable FK.
- Two parents on one child.
- Self-reference.
- Child-first order (deferred parent), pending maps.
- Out-of-core with an `orphan_policy` that nulls orphan keys: a `no_orphan_children` finding, not
  an `fk_intact` break.

### Fields

- `ValidatorFinding.failing_row_count`, `failing_row_indices` (cap 10,000), `ValidationReport.results`:
  unchanged from S1.
- `quality_metrics["validation"]`: now written by the session on every route; out-of-core no
  longer writes its own (`out_of_core/_validate_batch.py:379`).
- Physical plan hash: physical-only digests of the plan config hash and canonical config without
  `validators:`, plus `validators_need_resident` (`physical/_inputs.py:315-324`).
- Tombstone record: new `no_successor` field.

### Output surfaces

- Route label, route reason, per-column backends: equal to the no-validator run.
- Published bytes: the chosen route's bytes (parent section 4, surface 1).
- Error messages and reason codes: codes and names only; V13 extended to the three new code
  paths.
- Docs: `docs/strategies.md`, `docs/compatibility-contract.md`, changelog `Breaking:` lines.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Errors carry codes, table, column and entry index only (S2 round 3 rule) | V13 extended | Put the failing value into the not-observed message: V13 red |
| 2 | Cleanup on an exit path | Verdict before seal; abort owner unchanged; spill scratch removed | V4(c) no-sink row, V15, V20 | M18 |
| 3 | Shared state | One session per run; `None` bound for validator-free runs; one claimed owner per table | V19, split-owner test | M13, M22 |
| 4 | Route parity and silent fallback | Validators read nowhere in routing; sentry with exact allowlist | V4(a), V9 | M6, M10 |
| 5 | Referential integrity | Keyed folds use pending maps, any table order | V8 keyed rows | M9, one pending child per key kept |
| 6 | Untrusted producer | N/A: no new parsing; validator params checked at open as today (accidental-only threat model) | V1 control | N/A |
| 7 | Check-then-use (toctou) | Pairing by published offset; counts compared at finish | V5 paired rows | M4, slice from offset 0 each time |
| 8 | Weak tests | Per-row ledger; pins named; distinct data per batch | V15, V5, V9 | M21, stale pin row |
| 9 | Refactor drift | Deleting `_validate_batch.py` keeps the out-of-core verdicts; migrated tests keep their assertions | V8 out-of-core rows, V16 | M19 |
| 10 | Frozen contract drift | Plan hash and route changes on `Breaking:` lines; tombstones resolve in both forms | V14, V21 | M25 |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Proxy shape chosen by exact protocol members, not name matching |
| 2 | Strict wire types | `ValidationReport` fields unchanged; the CLI reader is S4 |
| 3 | No exception context | `ValidatorFailedError` raised with no context; V7 asserts no COMMIT record and no chained cause |
| 4 | Versioned read models | Plan hash change named; tombstoned codes stay resolvable |
| 5 | Normalized guard scanners | The sentry walks the AST, catches aliases and string paths (S2 round 1) |
| 6 | Private modules | `_sink.py` private; public names exported from `decoy_engine.validators` only |
| 7 | No hidden CI failures | V6 runs on the Dell node and its numbers go in the slice record; no skip marks |
| 8 | One input, one trust class | Source batches and output batches are both engine-produced; N/A for a new trust class |
| 9 | Mutations on the final head | Each PR's list reruns after its last code change |
| 10 | Allowlisted helpers still checked | The four lifecycle identities are exact; the sentry checks their callers |
| 11 | No raised caps | No ceiling raised; fan-out pin lowered to 43; `_stream_driver.py` stays under 600 |

## Reuse inventory

- `ValidationSession` and its feeds, `bind_validation_session`, `complete_resident_validation`.
- `observed_commit`, `evidence_of`, `OutputPublish` abort ownership.
- `post_scan_sink_kind`; `resolve_sequential_loader` tee.
- S2 sentry and its `S3_PENDING` Counter; S2 route-matrix harness in
  `tests/unit/execution/test_resident_validation_routes.py`.

## Frozen contracts

- Physical plan hash: validator list removed (named `Breaking:` line, compatibility contract).
- Reason codes: `route.validators_present` (S3b) and
  `runtime.out_of_core_validators_not_admitted` (S3a) tombstoned with `no_successor`;
  `runtime.validator_table_not_observed` and `runtime.validator_whole_table_over_budget` (S3a)
  and `route.validators_need_transactional_sink` (S3b) added.
- Tombstone record and reason manifest: the `no_successor` field (S3a), with the release policy,
  serialization, manifest pin and tombstone test changed together.
- `ValidationReport` and `ValidatorFinding`: no change in S3.

## Slices

- **S3a** `feat(validators): validate out-of-core batches in the run session`. Tests and
  mutations: the S3a lists above. Depends on #812.
- **S3b** `feat(validators): keep validators off the streamed route choice`. Tests and
  mutations: the S3b lists above, including sequential V8. Depends on S3a.

Test depth: T0 the touched files' tests; T1 impact selection. Triggers: serialization (plan
hash) and frozen contract (reason codes), so a full T3 at each merge head, diffed against the
saved main baseline. V6 runs with `vm-run` on the Dell node.

## Pre-mortem

- A test asserts a validator-bearing job's route or `validators_present`. Expected; the builder
  lists each in the PR body under "validators no longer route", as the parent plan says.
- A sink whose `write` is visible before commit (a plain file writer). Its bytes can be seen
  before the verdict; the `TransactionalSink` guidance stays in the docs for that reason.
- The whole-table spill fills the disk on a very wide table. It writes scoped columns only;
  the builder measures one 10M-row case on the Dell node and records it.
- The `no_successor` tombstone form is an owner call. If refused, S3a picks a replacement code
  and V14 changes with it.
- The proxy hides a helper such as `bounded_write_batches`. `__getattr__` forwards it; V4
  readability rows prove the integrity gate ran.
- GEN-PER-COLUMN S4 lands first and writes a parent after its children. Pending maps cover any
  order; V8 child-first row.
- `_session.py` grows past 600. Move `needs_resident` into `_sink.py` with the proxy.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; `~/bin/pytest-one` locally, `vm-run` for V6.
- Never weaken a route-matrix row to pass. A test that asserted the old route changes its
  expectation and is listed in the PR body.
- `S3_PENDING` rows are deleted, never added.
- Errors: codes and names only. Run V13 after each new error path.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entry before merge.
- Stop and report if the same defect class comes back after a fix.

## Round 3 review: open findings

Codex round 3 (the last review round) gave NO-GO. The findings below are quoted from that
review and are not yet folded into the plan above, except where a note says so. The builder
or the next planner resolves each one, checked against the cited lines on the re-anchored
base, before code starts.

1. P0 V1: Resident quarantine can publish its sidecar and then fail the job. Plan:91-95 requires every route checkpoint to raise on a failed report. A covered `validation_fail` deliberately retains that report, removes the rows, and can publish the sidecar immediately (`_pipeline_finalize.py:461,493-494,507-523`, `pipeline/_post_scan.py:563-571`). Dispatch currently raises only for newly judged tables (`_pipeline_route_dispatch.py:99-105`). Preserve the finalizer’s covered decision through completion and callable delivery. Test a covered failure returning filtered output and an uncovered failure publishing nothing.

2. P1 V1: Sequential writes still bypass the proxy. Plan:201-208 replaces `ctx.publish.sink`, but dispatch independently passes `ctx.sink` to sequential and out-of-core execution (`_pipeline_route_dispatch.py:194,249`). Sequential writes to that object at `_sequential.py:564-566`. Install the same wrapper in both references and assert that sequential folds each write while the out-of-core wrapper only checks counts.

3. P1 V1: Sequential no-sink validation has no observer before its verdict. Plan:207-214 assigns owners to the proxy and out-of-core driver. Sequential without a sink stores `out` at `_sequential.py:567-568` and seals at `:608`, before dispatch can observe returned tables. The proposed loader tee also misses ordinary `caller_sources` (`_pipeline_sources.py:155-167`). Feed the final output and aligned typed source inside the sequential loop before eviction. Exercise loader-only, resident and lazy inputs with a middle row removed.

4. P1 V1: Sink eligibility changes between slices and disagrees with the lazy prepass. Plan:126-136 removes the S3a capability veto in S3b, while plan:192-196 diverts only plain callables. A supported three-method sink can then reach `_emit.py:106,128`, which requires `write_batches` (`_sequential.py:207-225`). The prepass receives no sink at all (`_pipeline_context.py:355-370`, `pipeline/_lazy_input.py:144-158`). Carry the same capability through prepass and routing in S3a and S3b. Test three-method and callable sinks under auto, explicit out-of-core and required-stream modes, including their coded refusals.

5. P1 V1: Whole-table callbacks still lose undeclared source columns. Plan:114-122 promises complete mappings but spills only declared source columns. V20 at plan:277 expressly reads an undeclared column. `_WholeTableFold.finish` passes the source mapping to the callback without projecting it (`validators/_registry.py:143-147,181-191`). For this validator shape, preserve every source column and include it in the budget check. For ordinary folds on the no-sink exit, feed the assembled output in aligned batches to preserve the existing seven-row maximum (`test_phase_d_d3a_validators_ooc.py:1375-1395`, plan:144-146).

6. P1 V1: A nested public sequential adapter can finish the outer job. Plan:96-100 isolates `run_pipeline` and the direct out-of-core runner, but plan:147-152 puts ambient validation in every `observed_commit`. The public `SequentialAdapter` calls `run_sequential` directly and can commit inside an outer sink callback (`physical/drivers/_sequential.py:69-79`, `_sequential.py:625`). A subsequent outer feed then reaches an already-finished session (`validators/_session.py:240-245`). Pass the owning session or `None` explicitly to commit, or isolate this public entry too.

7. P1 V1: Readback can judge the wrong sink. Plan:197-200 follows an `inner_sink` attribute on any object. Exact producer identity determines readability at `config/_post_scan.py:197-216`, but `pipeline/_post_scan.py:480-486` calls `staged_tables()` on the outer object. An ordinary decorator with its own stage can therefore inherit another sink’s trusted status. Unwrap only engine-owned validation proxies and read from the same verified producer. Add a foreign-decorator control alongside V4.

8. P1 DESIGN: The physical plan has no shared source for the callable decision. Plan:186,192-196,215-220 authorizes `validators_need_resident` only in `run_pipeline`. Independent physical capture receives its own sink and config, and the compiler replays routing (`physical/_snapshot.py:50-59,268-272`, `physical/_compiler.py:89-96`). Compute the fact through one shared function, store it in `PhysicalPlanInputs`, and use it for routing and hashing. Extend V21 to compare a callable plan’s predicted route and reason with execution.

9. P1 DESIGN: The exact caller table rejects required calls. Plan:134-136 requires the runner to call `quarantine_needs_resident`, but plan:180-186 authorizes only `_sequential_eligible`. It also omits existing `active_validation_session` calls in `_pipeline_mixed_route.py:294` and `physical/_shadow_generation.py:267`. `execute_sequential_route` lives in `_pipeline_route_dispatch.py:163`, and the public runner is `out_of_core/_runner.py:111` (`run_fk_out_of_core`). Enumerate the retained callers or replace them with explicit session passing. Reuse the quarantine-trigger predicate already expressed in `validators/_fold.py:127-130`.

10. P2 V2-LOG: The size and baseline ledger is incomplete. Plan:155-156,258-262 lowers fan-out to 43 but omits `tests/sentry/baselines/package-fanout.json:21-23`. `test_baseline_registry.py:48-49` requires exact equality. `_sequential.py` is already 680/680 and `plan/_compile.py` is 673/673 (`test_module_size.py:109,131`). `scripts/release/reason_manifest_policy.py` is 600/600 without a census entry, and `_pipeline_context.py` is at 599. Record the companion baseline edit and a net line budget for each touched file. If routing signals falls to 600, remove its baseline key alongside its census entry (`_baseline_sources.py:195`).

11. P2 V2-LOG: Several acceptance rows do not distinguish the stated base or mutation. V19’s after-return identity already holds on `83f1fe077` (`plan:301,351-352`, `_session.py:63-71`). Assert `None` *inside* the nested run and outer identity afterward. V8 report equality alone can pass through resident fallback (`plan:297,321`, `_pipeline_routing.py:500-507`). Assert the bounded route was taken. Split V4’s callable exception from the route-equality assertion at plan:314. Use streamed mixed execution for V15/M3/M18 (`_pipeline_mixed_route.py:293-319`), since auto-chunk finalizes before commit (`_pipeline_full_frame.py:290,347`). Move M12 to a dispatch-only failing row. The sequential no-sink verdict at plan:212 already enforces failure before dispatch completion.

12. P2 V2-LOG: The split-owner mutation lacks a reachable route fixture. Plan:327,345 inherits a split that streams one table and returns another resident (parent:273). `_chunked_output_sink.py:105-109` keeps that split resident, and `_pipeline_multi_table.py:343-350` refuses it with a sink. Keep refusal parity. Kill M15 on an actual second observation, such as resident output subsequently delivered to a callable, and test split ownership separately at the session boundary.

13. P2 V2-LOG: Correct the remaining references and migration instructions. At plan:150-151, `_publication_observer.py:143` reads evidence, `:144` opens the `try`, and `:145` commits. Plan:300 cites admission at `_validate_batch.py:330-342` for enforcement, which is at `:379-383`. Plan:349 places `maybe_render` in `_emit.py`, but its call sites are `_rewrite_pass.py:255,270` and `_stream_driver.py:474`. Change “from `finish`” at plan:365 to `verdict`. Add the deleted-module import and spies in `test_pipeline_routing_route_kills.py:83,97,194-197,211-212` to plan:156-158. The cited V4 pin at plan:295 checks abort and publication, not sealing (`test_phase_d_d3a_validators_ooc.py:1223-1229`). Add a seal spy.
