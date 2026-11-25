# EXPECT-OFF-ROUTE S3: validators on the streamed and bounded routes

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), cross-cutting-concerns,
reuse-first, catalogs/recurring-defects; owner notes on the V1 threat model, the value-free class
(F31), plan-defines-acceptance-tests and the V1 fast path default.

Row: EXPECT-OFF-ROUTE. Parent plan: `docs/plans/2026-11-22-expect-off-route.md` rev 6 (sections
4, 5, 9 and 10; slice S3 "STREAMED-ROUTES"). This file splits S3 into two PRs, S3a and S3b,
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

- No CLI change (S4). No `leak_check_column_not_checked` warning (S4).
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

### S3a: out-of-core on the session, finish before commit

1. `out_of_core/_rewrite_pass.py` `_delivered` (`:198-200`) and `_stream_driver.py` `_delivered`
   (`:431-433`) call `session.observe_pair(table, raw_batch, out)` for a paired table and
   `session.observe_published(table, out)` otherwise. The FK pass pairs at `yield out` (`:243`).
2. Delete `out_of_core/_validate_batch.py` (387 lines): the collector, `admitted_validators`,
   `validators_ooc_safe`, `validate_delivered`, `finish_validation`. Remove the `validators`
   parameters at `_rewrite_pass.py:93`, `_stream_driver.py:154` and `_runner.py:216`, `:322`,
   `:359`. Out-of-core marks its tables complete through the session.
3. `_publication_observer.observed_commit`: after `gate.before_commit(sink)` (`:142`) and before
   `evidence_of(sink)`, call `active_validation_session().finish()` when a session is bound. A
   failure raises `ValidatorFailedError` before `try: sink.commit()`, so no COMMIT record. Abort
   stays with `OutputPublish` and the existing unwind.
4. Routing: `validators_ooc_safe` and `validators_ooc_ready` leave `decide_execution_route`
   (`_pipeline_routing.py:300`, `:339-340`, `:432`) and `resolve_execution_route`. Out-of-core
   then admits any validator. The other declines stay until S3b.
5. Tombstone `runtime.out_of_core_validators_not_admitted` (`reasons/runtime/_part2.py:214`) in a
   runtime `_retired.py`, `deprecated_in` the release that carries S3a, no `replaced_by`.
6. `S3_PENDING`: delete the 13 out-of-core and `validators_ooc_*` rows. Docs: drop the S2
   "use a `TransactionalSink`" sentence from `docs/strategies.md`; changelog `Breaking:` line.

### S3b: the write proxy and the remaining declines

1. `validators/_sink.py` (new, about 150): `observe_sink(sink, session)` returns one of three
   shapes: callable only; write, commit and abort; or the four-member `TransactionalSink`. Only
   `write` and `write_batches` observe. `__getattr__` forwards only names the inner sink has. A
   read-only `inner_sink` marker.
2. `config/_post_scan.post_scan_sink_kind` follows `inner_sink`, with cycle protection, and
   returns the real class token.
3. `_pipeline_route_dispatch.execute_route` wraps the sink in the bound session. A plain callable
   on a route that would stream takes the resident route with
   `route.validators_need_transactional_sink` (new, `reasons/route/_part1.py` beside
   `quarantine_enabled`), through `session.needs_resident(sink)` in `_sequential_eligible`
   (`_pipeline_routing.py:97`). After `settle`, a passing run calls the callable once per table.
4. `execute_sequential_route` composes the post-scan and validation tees for loader-only tables.
   The validation tee projects only the paired columns; the loader runs once per table.
5. Delete every remaining `S3_PENDING` site (routing, routing signals, multi-table, chunked
   output mode, capacity, job estimate, context, transforms admission and prepare, lazy input,
   physical compiler, live inputs, inputs, snapshot, unified slice) and the table itself. The
   physical plan hash drops the validator list; the resident-fit verdict stays in the hash.
6. Tombstone `route.validators_present` (`reasons/route/_part1.py:306`); delete the alias
   `ROUTE_VALIDATORS_PRESENT` (`physical/_reasons.py:56`, `:101`, `:343`).
7. New runtime code `validator_table_not_observed` (from `finish` when a written table had no
   observation). Docs, compatibility contract and changelog `Breaking:` lines (route, plan hash).

Choke points:

- Commit: `observed_commit` is the one place a commit starts (existing). Guard: V4(c). Mutation
  M3, commit before `finish`.
- Observation: the proxy is the one write path on streamed routes. Guard: V7. Mutations M5 and
  M13.
- No routing on validators: the sentry. Guard: V9. Mutations M6 and M10.

Design notes: no new pattern beyond the parent plan's section 5. The proxy is the established
decorator shape the repo already uses for publication evidence (`evidence_of`), and it keeps the
protocol members of the inner sink exactly.

### Placement

| New or changed | Path | CODEMAP rule ("Job-level validator framework" row added by S1) | Sits beside |
|---|---|---|---|
| Write proxy | `src/decoy_engine/validators/_sink.py` | private modules in `src/decoy_engine/validators/` | `_session.py` |
| Commit finish | `src/decoy_engine/execution/_publication_observer.py` | existing module | |
| Route and driver edits | `src/decoy_engine/execution/` files above | existing modules | |
| Unit tests | `tests/unit/validators/test_sink_proxy.py`, `tests/unit/execution/test_streamed_validation_routes.py`, `test_out_of_core_session_validation.py` | `tests/unit/validators/`, route tests in `tests/unit/execution/` | `test_resident_validation_routes.py` |
| Sentry | `tests/sentry/test_validators_do_not_route.py` | `tests/sentry/` | |

Module sizes: `_chunked_output_sink.py` is at 600 and only shrinks; `_stream_driver.py` (583)
shrinks; `_pipeline_routing.py` (566) shrinks; `_session.py` stays under 600 (it gains
`needs_resident` and the not-observed check, about +25).

## Behavior and failure modes

| Case | Expected | Test |
|---|---|---|
| Out-of-core FK with a `TransactionalSink`, failing validator | `ValidatorFailedError` before `commit`; staging empty; no COMMIT record | V4(c) out-of-core row |
| Out-of-core, write, commit and abort sink, failing validator | no `commit`; abort runs | V4(c) |
| Out-of-core, any validator (no D3a list) | admitted; report equals full frame | V8 |
| Auto-chunk streamed to a sink, failing validator | streams; raises before commit | V4 streamed row |
| Plain callable on a streamed route | resident with `validators_need_transactional_sink`; callable called 0 times on fail, once per table on pass | V4 callable row |
| Write bypasses the proxy | `validator_table_not_observed` at commit, nothing committed | V7 |
| Paired lazy source shorter than output | `validator_source_pairing_mismatch` | V5 (kept from S2) |
| Key state over budget | `validator_key_state_over_budget` before the first scoped write | V6 keyed cell |
| Wrapped `ParquetTransactionalSink` or `StagingSink` | post-scan sees the inner kind; gate runs | V4 readability rows |
| Split run, one streamed and one resident table | each table folded once | V4 split row |

## Acceptance tests (red first)

From the parent plan, section 9: V4 (streamed, out-of-core, sequential, generation, callable,
readability and split rows), V5 (streamed and loader-backed rows), V6 (performance gate on the
Dell node with `vm-run`), V7, V8, V9 (S3_PENDING deleted), V14. S3a carries V4 out-of-core rows,
V8 out-of-core rows, V14 for the runtime tombstone, V15 and V17; S3b carries the rest. Each V4,
V5 and V8 row is red before its PR because the route declines.

New in this plan:

- **V15 finish inside the commit step (S3a, new guard, proof by mutation M15).** A recording
  sink on out-of-core with a failing `regex_match`: the call order is `write`, `write`, `abort`,
  with no `commit`; the error is raised from `observed_commit` after `gate.before_commit` and
  carries no COMMIT record. On #812 the raise comes from `finish_validation` in the runner
  (`out_of_core/_runner.py:359`), so this is not red evidence; its proof is M15 and the
  deletion of the runner call.
- **V17 out-of-core admits every validator (S3a, red-before).** Two validators that
  `admitted_validators` (`out_of_core/_validate_batch.py:152`) refuses on #812 (the builder
  reads the list; `leak_check` and `parent_window_respected` are the expected picks), on an out-of-core FK job: the route
  label equals the run without validators and the report equals full frame. Red before: the
  route declines (`_pipeline_routing.py:339-340`).
- **V16 rendered bytes on streamed routes (S3b, red-before).** A format-sensitive `regex_match`
  on a column with declared formatting gives the full-frame verdict on the auto-chunk streamed
  route. Red before: the route declines (resident).

Mutations: M3, M4, M5, M6, M8, M9, M10, M12, M13, M14 from parent section 10, plus:

| ID | Mutation | Test that must fail |
|---|---|---|
| M15 | `observed_commit` finishes after `evidence_of` and inside the `try` | V15 (COMMIT record present) |
| M16 | `_delivered` observes before `maybe_render` | V16 |
| M17 | Keep one `S3_PENDING` row after its site is deleted | V9 (pin larger than scan) |

## Enumerations

### Exit paths

- `observed_commit` (`_publication_observer.py:132`): gate refusal; `ValidatorFailedError` from
  `finish` (new); `validator_table_not_observed` (new); commit exception (recorded as COMMIT).
- Out-of-core runner (`out_of_core/_runner.py:359`): the `finish_validation` raise is deleted;
  failure surfaces at commit or at resident completion for a no-sink run.
- `execute_route` (`_pipeline_route_dispatch.py:149`): resident completion raises for routes
  with no sink.
- `observe_source_batches`: `validator_source_pairing_mismatch`. Fold append:
  `validator_key_state_over_budget`.

### Routes

From parent section 4. S3a touches only the out-of-core rows; S3b the rest.

- Unified slice, auto-chunk resident, full frame, mixed: resident, unchanged since S2.
- Physical full-frame, mixed and generation drivers: unchanged since S2.
- Auto-chunk streamed with a sink (`_chunked_output_sink.py:114`): S3b.
- Sequential FK with and without a sink (`_pipeline_routing.py:97`): S3b.
- Out-of-core FK with and without a sink (`_pipeline_routing.py:339-340`): S3a.
- Multi-table split (`_pipeline_multi_table.py:151`): S3b.
- Generation with a sink: S3b.
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
  longer writes its own (`out_of_core/_validate_batch.py:378`).
- Physical plan hash inputs: the validator list leaves (`physical/_inputs.py`, `_snapshot.py`).

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
| 2 | Cleanup on an exit path | A failed `finish` leaves abort to `OutputPublish`; staging is empty after | V4(c), V15 | M15, finish inside the `try` |
| 3 | Shared state | One session per run in a `ContextVar`; first observer owns a table's fold | V4 split row | Feed a second observer: split row red |
| 4 | Route parity and silent fallback | Validators read nowhere in routing; sentry with exact allowlist | V4(a), V9 | M6, M10 |
| 5 | Referential integrity | Keyed folds use pending maps, any table order | V8 keyed rows | M9, one pending child per key kept |
| 6 | Untrusted producer | N/A: no new parsing; validator params checked at open as today (accidental-only threat model) | V1 control | N/A |
| 7 | Check-then-use (toctou) | Pairing by published offset; counts compared at finish | V5 paired rows | M4, slice from offset 0 each time |
| 8 | Weak tests | Order list in V15, counters in V5, exact pin table in V9 | V15, V5, V9 | M17, stale pin row |
| 9 | Refactor drift | Deleting `_validate_batch.py` keeps the out-of-core verdicts | V1, V8 out-of-core rows | M16, observe before render |
| 10 | Frozen contract drift | Plan hash and route changes on `Breaking:` lines; tombstones resolve | V14 | Drop a tombstone: V14 red |

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
| 9 | Mutations on the final head | M3 to M17 rerun after the last code change |
| 10 | Allowlisted helpers still checked | The four lifecycle identities are exact; the sentry checks their callers |
| 11 | No raised caps | No module-size ceiling raised; `_chunked_output_sink.py` and `_stream_driver.py` shrink |

## Reuse inventory

- `ValidationSession` and its feeds, `bind_validation_session`, `complete_resident_validation`.
- `observed_commit`, `evidence_of`, `OutputPublish` abort ownership.
- `post_scan_sink_kind`; `resolve_sequential_loader` tee.
- S2 sentry and its `S3_PENDING` Counter; S2 route-matrix harness in
  `tests/unit/execution/test_resident_validation_routes.py`.

## Frozen contracts

- Physical plan hash: validator list removed (named `Breaking:` line, compatibility contract).
- Reason codes: `route.validators_present` and `runtime.out_of_core_validators_not_admitted`
  tombstoned, never deleted; `route.validators_need_transactional_sink`,
  `runtime.validator_table_not_observed` added through the registry.
- `ValidationReport` and `ValidatorFinding`: no change in S3.

## Slices

- **S3a** `feat(validators): validate out-of-core batches in the run session`. Tests V4 and V8
  out-of-core rows, V14 (runtime), V15, V17. Depends on #812.
- **S3b** `feat(validators): keep validators off the streamed route choice`. Tests V4 rest, V5, V6,
  V7, V9, V14 (route), V16. Depends on S3a.

Test depth: T0 the touched files' tests; T1 impact selection. Triggers: serialization (plan
hash) and frozen contract (reason codes), so a full T3 at each merge head, diffed against the
saved main baseline. V6 runs with `vm-run` on the Dell node.

## Pre-mortem

- A test asserts a validator-bearing job's route or `validators_present`. Expected; the builder
  lists each in the PR body under "validators no longer route", as the parent plan says.
- A sink whose `write` is visible before commit (a plain file writer). S3a makes the commit
  wait; the written bytes are the sink's own staging. The compatibility contract says so.
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
