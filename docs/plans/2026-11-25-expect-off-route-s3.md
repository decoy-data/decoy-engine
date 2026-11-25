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

After S3a: on the out-of-core route the run's one `ValidationSession` folds every delivered batch,
and `observed_commit` finishes the session after `gate.before_commit` and before `sink.commit()`.
A validator failure commits nothing on any sink that has a commit step.

After S3b: a validator-bearing job runs the same route, with the same route reason and per-column
backends, as the same job without validators, on every route in parent section 4. `S3_PENDING` is
deleted and the sentry allowlist holds only the four lifecycle identities.

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
  `check_count(table, n)`, which compares row counts and never appends
  (`validators/_session.py:149-158,240-247` append unconditionally today).
- Nested runs. `bind_validation_session` binds `None` for a validator-free run and resets its
  token on exit (`_session.py:63-71` leaves the outer session visible today). A nested job
  never sees, feeds or finishes its caller's session.
- Expected tables. The session records the table list and the row count each driver reports it
  wrote, from the driver's own write accounting, not from the observer. `finish` compares them:
  a written table with no observation, or fewer observed rows than written, raises
  `validator_table_not_observed`. A zero-row table with a schema (`_chunked_output_sink.py:588-592`)
  counts as observed with zero rows.
- Sink shape has one owner: the existing classification at `_sequential.py:207-224` and the
  protocol check at `_chunked_output_sink.py:99-102` move into one `sink_capability(sink)` in
  `execution/_sink_capability.py`; the proxy and the routing check both call it.
- Whole-table validators. A registered whole-table validator (`validators/_registry.py:163-179,236-248`)
  cannot take a second span. On a streamed route the session spills that validator's scoped
  columns for the table to Arrow IPC in protected scratch, runs the function once at
  `table_complete`, and removes the scratch on every exit. Memory stays bounded; disk use is
  the scoped columns only.

### S3a: out-of-core on the session

1. Eligibility. `_sequential_eligible` (`_pipeline_routing.py:140-145`) mixes structural rules
   with the temporary `VALIDATORS_PRESENT` veto, and the out-of-core selectors use it
   (`:368-375,390-394,432-439,471-474`). Split it: `_structurally_sequential` (no validator
   read) feeds the out-of-core selectors; the veto stays only on the sequential route choice
   until S3b. The `validation_fail` quarantine exclusion from `_validate_batch.py:166-169` moves
   into the quarantine rule in routing, so it still forces resident.
2. Observation site. Both drivers observe the final payload at `_emit.py` after sink-schema
   reconciliation (`_emit.py:104-109,122-128`), which is after rendering
   (`_rewrite_pass.py:243-255`). The rewrite driver passes the scoped raw projection with the
   batch. The reorder driver consumes raw rows in phase one and emits in phase three
   (`_stream_driver.py:289-292,331-338,430-455`); it writes the scoped raw projection and row
   positions to its existing protected scratch in phase one and reads them back beside each
   emitted batch. Paired tables call `observe_pair`, others `observe_published`.
3. Verdict point. The runner keeps its verdict before `seal_evidence` (`out_of_core/_runner.py:359-374`)
   but asks the session (`session.verdict(tables)`, raising `ValidatorFailedError`) instead of
   its own collector. This covers the sink exit and the no-sink return, keeps the abort owner
   at `_runner.py:374-376`, and keeps the quarantine cleanup order: nothing is sealed after a
   failure. `observed_commit` also calls `finish()` (idempotent) after `gate.before_commit` at
   `:142` and before `evidence_of` (`:98-101`), so every commit has one check.
4. Direct callers. The public runner (`out_of_core/__init__.py:65`, called by
   `physical/drivers/_out_of_core.py:67-73`) opens and binds its own session from the job
   config when no session is bound, and finishes it at the verdict point. The guard the deleted
   module gave (`_validate_batch.py:330-342`) is kept this way.
5. Delete `out_of_core/_validate_batch.py`. Remove the collector construction (`_runner.py:216`),
   the keyword-map entry (`:322`) and the finish call (`:359`), and the `validators` parameters
   at `_rewrite_pass.py:93` and `_stream_driver.py:154`. Lower the out-of-core fan-out pin from
   44 to 43 (`tests/sentry/layout/test_package_fanout.py:28-38,62-79`). Move the imports of the
   deleted module in `test_phase_d_d3a_validators_ooc.py:34`, `test_delivered_bytes_validation.py:22`
   and `test_fold_review_round2.py:185` to the session, keeping their behavior assertions.
6. Routing: `validators_ooc_safe` and `validators_ooc_ready` leave `decide_execution_route`
   (`_pipeline_routing.py:300,339-340,432`) and `resolve_execution_route`.
7. Tombstone `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`).
   `tests/unit/test_reason_tombstones.py:8-21` requires a live `replaced_by`, and no code takes
   this one's place. S3a extends the tombstone record with `no_successor: str` (the reason the
   code has no successor) as the only other allowed form, updates that test to accept exactly
   these two forms, and imports the new runtime `_retired.py` in `reasons/runtime/__init__.py:5-9`.
8. Sentry. `S3_PENDING` drops the out-of-core and `validators_ooc_*` rows. V9 gains caller
   checks for the four lifecycle identities: each may be called only from its listed
   `(path, function)`, aliases included. Docs keep the `TransactionalSink` guidance
   (`docs/strategies.md:2389-2391`), since a plain sink's writes are visible before commit.
   Changelog `Breaking:` line for the route change.

### S3b: the write proxy and the remaining declines

1. Sink requirement before routing. `validators_need_resident(config, sink)` is a pure function
   of the config and `sink_capability`, computed in `_pipeline.py` before the route is decided
   and emitted (`:358-360`). It is carried into snapshot replay and the resident-fit check. It
   runs in `decide_execution_route` before any route-specific early exit, since flat and
   generate jobs leave `_sequential_eligible` at `:140-145`. A plain callable with validators on
   a route that would stream takes resident with `route.validators_need_transactional_sink`
   (new, beside `quarantine_enabled`). After `settle`, a passing run calls the callable once
   per table.
2. `validators/_sink.py` (new, about 150): `observe_sink(sink, session)` returns the shape
   `sink_capability` names (callable; write, commit and abort; or the four-member
   `TransactionalSink`). Only `write` and `write_batches` observe. `__getattr__` forwards only
   names the inner sink has. A read-only `inner_sink` marker. `post_scan_sink_kind` follows
   `inner_sink` with cycle protection.
3. Owners. Before the first batch, `execute_route` claims each table for one observer: the
   proxy on streamed routes, the out-of-core driver on out-of-core. On an out-of-core run with a
   sink, the proxy only count-checks.
4. Sources for the proxy. The bound session gets a `source_for(table)` from the route: the
   resident source, or a bounded projected lazy reader that reads the paired columns one batch
   at a time. `execute_sequential_route` composes the post-scan and validation tees so the
   loader runs once per table. Batch boundaries of source and output need not match.
5. Generation. The streamed generation entry is `generation/_plan_entry.py:290-319`, which calls
   `run_generation`; `generation/_streamed.py:522-530` writes and commits. `_plan_entry` binds a
   session from the job's `validators:` and wraps the sink, and the commit goes through
   `observed_commit`. Pipeline generation (`_pipeline_generate_mask.py:128-139`) stays resident.
6. Delete every remaining `S3_PENDING` site and the table. Refusals that do not involve
   validators stay as they are, with the same reason with or without validators: mixed
   streamed and resident output (`_pipeline_multi_table.py:343-350`), streamed auto-chunk with
   declared formatting (`_chunked_output_sink.py:105-115`) and out-of-core self-reference
   (`out_of_core/_compat.py:504-519`).
7. Plan hash. `physical/_inputs.py:315-324` hashes the plan config digest and the full canonical
   config; `inputs.validators` is already out of the tuple. The canonical config used for the
   hash drops the `validators:` key only. Two configs that differ only in validators give the
   same hash; every other config input and the resident-fit identity (`:367-370`) stay.
8. Tombstone `route.validators_present` (`reasons/route/_part1.py:306`) with `replaced_by`
   `route.validators_need_transactional_sink` (the one remaining validator-related route
   reason); delete the alias `ROUTE_VALIDATORS_PRESENT` (`physical/_reasons.py:56,101,343`).
9. New runtime code `validator_table_not_observed`. Docs, compatibility contract, changelog
   `Breaking:` lines (route, plan hash).

Choke points:

- Commit: `observed_commit`. Guard: V15. Mutation M18.
- Observation: one claimed owner per table. Guard: V7 and the split-owner unit test. Mutations
  M5, M13.
- No routing on validators: the sentry with caller checks. Guard: V9. Mutations M6, M10, M20.

Design notes: the proxy is the decorator shape the repo uses for publication evidence. Spilling
whole-table input to Arrow IPC is the established way to keep a once-per-table function bounded.

### Placement

| New or changed | Path | CODEMAP rule ("Job-level validator framework" row added by S1) | Sits beside |
|---|---|---|---|
| Write proxy | `src/decoy_engine/validators/_sink.py` | private modules in `src/decoy_engine/validators/` | `_session.py` |
| Sink capability | `src/decoy_engine/execution/_sink_capability.py` | execution helpers | `_sequential.py` |
| Commit finish | `src/decoy_engine/execution/_publication_observer.py` | existing module | |
| Route and driver edits | `src/decoy_engine/execution/` files above | existing modules | |
| Unit tests | `tests/unit/validators/test_sink_proxy.py`, `tests/unit/execution/test_streamed_validation_routes.py`, `test_out_of_core_session_validation.py` | route tests in `tests/unit/execution/` | `test_resident_validation_routes.py` |
| Sentry | `tests/sentry/test_validators_do_not_route.py` | `tests/sentry/` | |

Module sizes: `_chunked_output_sink.py` is at 600 and only shrinks; `_stream_driver.py` (583)
must stay under 600 after the scratch projection (budget +15, offset by the removed validator
parameter); `_pipeline_routing.py` (566) shrinks; `_pipeline_routing_signals.py` is 613 under a
633 ceiling (`test_module_size.py:98`); if it reaches 600 its census entry is removed
(`:239-248`). `_session.py` gains `claim`, `check_count`, `verdict`, expected tables and the
whole-table spill (about +70, to about 362).

## Behavior and failure modes

| Case | Expected | Test |
|---|---|---|
| Out-of-core with a `TransactionalSink`, failing validator | Raise before seal and commit; staging empty; no COMMIT record | V4(c) |
| Out-of-core, no sink, failing validator | Raise before seal; no sealed or staged quarantine artifact | V4(c) no-sink row |
| Direct call to the public runner, failing validator, recording sink | Raise; no commit | V18 |
| Out-of-core by forced, row-threshold and byte-estimate selectors, with validators | Out-of-core, as without | V17 |
| Forced out-of-core on an inadmissible job | Refused before any read | V17 |
| Quarantine `validation_fail` with validators | Resident, as on #812 | V17 control |
| Out-of-core, both drivers, declared formatting, several batches | Verdict on rendered, reconciled bytes; pairing correct | V16 |
| Nested validator-free job inside a sink callback | Outer session unaffected; outer job finishes | V19 |
| Streamed sink run, plain callable | Resident with `validators_need_transactional_sink`; 0 calls on fail, 1 per table on pass | V4 callable |
| Table written with no observation; one batch skipped; zero-row table; resident return without completion | `validator_table_not_observed` for the first two; zero-row passes; resident case raises | V7 |
| Registered whole-table validator, several batches | Runs once on the whole table; scratch removed | V20 |
| Paired lazy source shorter or longer than output, unequal batch sizes | `validator_source_pairing_mismatch` for short or long; correct verdict otherwise; loader once per table | V5 |
| Key state over budget | `validator_key_state_over_budget` before the first scoped write | V6 keyed cell |
| Out-of-core with a sink in S3b | One fold per table; proxy count-checks | split-owner unit test |
| Mixed output, streamed auto-chunk with formatting, out-of-core self-reference | Same refusal with and without validators | refusal parity rows |
| Two configs differing only in validators | Same plan hash on capture and replay | V21 |

## Acceptance tests (red first)

Each PR has its own list. The builder keeps a per-row ledger: red-before (fails on its assertion
on the base), pin (passes on the base), or new API (no red claim).

S3a:

- **V4(c) out-of-core rows.** Pins on #812 for admitted failure and abort
  (`test_phase_d_d3a_validators_ooc.py:1215-1229`); the no-sink quarantine-artifact row is
  red-before.
- **V8 out-of-core rows** (single, composite, nullable, two-parent, child-first, orphan policy),
  red-before for validators the D3a list refuses.
- **V15 finish inside the commit step (guard).** A recording sink: `write`, `write`, `abort`, no
  `commit`; no COMMIT record (`_publication_observer.py:144-150`). Already holds on #812; the
  raise location changes. Proof is M18.
- **V16 rendered bytes (red-before).** Out-of-core, both drivers, declared formatting, a
  format-sensitive `regex_match`, several batches, distinct data per batch.
- **V17 eligibility (red-before).** `leak_check` and `parent_window_respected`, which
  `admitted_validators` (`_validate_batch.py:81,173`) refuses, through the three selectors; the
  forced refusal and quarantine controls are pins.
- **V18 direct runner (red-before for the session path).**
- **V19 nested run (red-before).**
- **V14 runtime tombstone.** Both forms accepted by the updated tombstone test; the runtime
  identity resolves.
- **V9 S3a.** Out-of-core rows gone; caller checks for the four identities; a seeded aliased
  unauthorized call fails.

S3b:

- **V4 rest** (streamed, sequential, generation through `_plan_entry`, callable). Resident
  unified and mixed rows are pins (`test_resident_validation_routes.py:108,171`).
  Readability rows are a mutation control (parent line 273).
- **V5** paired sources (red-before on the streamed routes).
- **V6** performance on the Dell node with `vm-run`, including the `retained_bytes()`
  measurement (parent line 275). The keyed budget cell is a pin (`test_fold_state.py:54`).
- **V7** expected-table cases (red-before).
- **V8 sequential rows**, including self-reference (red-before).
- **V9** `S3_PENDING` deleted; caller checks stay.
- **V14 route tombstone.**
- **V20** whole-table validator (red-before).
- **V21** plan hash capture and replay (red-before).
- Split-owner unit test at a controlled seam; refusal parity rows (pins).

Mutations. Parent section 10 IDs keep their meaning (M3 to M16). New IDs start at M18.

| ID | PR | Mutation | Test that must fail |
|---|---|---|---|
| M3 | S3a | Commit before the verdict | V4(c) |
| M4 | S3b | Slice the source from offset 0 each batch (distinct data per batch) | V5 |
| M5 | S3b | Proxy `write` does not observe | V7 |
| M6 | S3b | Read validators in `_sequential_eligible` | V4 sequential, V9 |
| M9 | both | Keep one pending child per key | V8 keyed rows |
| M10 | S3b | Restore one `S3_PENDING` site | V9 |
| M12 | S3b | Streamed driver skips the failing-report raise | V4 streamed rows (not the physical rows, which `physical/_shadow_coordinator.py:221-227` enforce) |
| M13 | S3b | Two owners append for one table | split-owner unit test |
| M18 | S3a | `observed_commit` finishes after `evidence_of` and inside the `try` | V15 (COMMIT record present) |
| M19 | S3a | Observe before reconciliation in `_emit.py` | V16 |
| M20 | S3a | Allow an aliased caller of a lifecycle identity | V9 seeded call |
| M21 | S3a | Keep one stale out-of-core `S3_PENDING` row | V9 stale-pin check (`test_validators_do_not_route.py:201-203`) |
| M22 | S3a | Do not reset the binding for a validator-free run | V19 |
| M23 | S3a | Runner without a bound session skips validation | V18 |
| M24 | S3b | Count expected tables from the observer | V7 bypass case |
| M25 | S3b | Keep `validators:` in the hashed canonical config | V21 |

## Enumerations

### Exit paths

- `observed_commit` (`_publication_observer.py:132`): gate refusal; `ValidatorFailedError` from
  `finish` (new); `validator_table_not_observed` (new); commit exception (recorded as COMMIT).
- Out-of-core runner (`out_of_core/_runner.py:359-374`): the verdict before seal now asks the
  session; it raises on the sink and no-sink exits before anything is sealed.
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
- Streamed generation through `generation/_plan_entry.py:290-319`: S3b.
- Plain callable sink on a streamed route: S3b, resident with `validators_need_transactional_sink`.
- Quarantine `validation_fail`: stays resident (exception 1a).

### FK shapes

As in V8, on the sequential and out-of-core routes:

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
- Physical plan hash: the canonical config drops `validators:` (`physical/_inputs.py:315-324`).
- Tombstone record: new `no_successor` form.

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
- Reason codes: `route.validators_present` tombstoned with `replaced_by`
  `route.validators_need_transactional_sink`; `runtime.out_of_core_validators_not_admitted`
  tombstoned with `no_successor`; `runtime.validator_table_not_observed` added.
- Tombstone record: the `no_successor` form (S3a), with the tombstone test changed to accept
  exactly the two forms.
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
