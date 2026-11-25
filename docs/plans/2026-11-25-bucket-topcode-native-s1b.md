# BUCKET-TOPCODE-NATIVE S1b: activate bucketize and top_code on chunked and unified

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), feature-dev, reuse-first, scope-discipline, testing (test depth), architecture,
cross-cutting-concerns, api-and-compatibility, workspace-and-vcs (commit messages),
catalogs/recurring-defects; engine `CLAUDE.md` and `CODEMAP.md`; owner notes on the V1 fast path
default, sentries over prose and plan-defines-acceptance-tests.

Row: BUCKET-TOPCODE-NATIVE, slice S1b. Parent plan: `docs/plans/2026-11-22-bucket-topcode-native.md`
rev 9 on branch `plan/bucket-topcode-native` (sections 4, 5 items 7 to 10a and 14, 6 P2 route
cases, P4, P4b, P5, P6, P7, P8, P9, P11, and the S1b row of section 7). This file is the build
brief for S1b only; the parent plan is the spec, and where the two differ the parent wins and
the builder reports the difference.

Risk: R2 (two strategies used by the HIPAA template move off pandas on two routes). Size: 1.25
builder-days. Code gate: Codex and Dennis. Depends on: S1g, S1d and S1r merged (and through them
#790, S1e, S1k, S1w). Anchor: engine main `2b8a47fbe`. None of the dependencies has merged on
that anchor, so every line number below is from main. S1d and S1r have separate predecessors,
so the base is the first main SHA that contains both. The builder records that SHA, re-anchors
on it and shows each red-before assertion there.

## Problem

After S1k and S1w the two Arrow operators exist and run when called directly, but no route uses
them:

- Neither strategy has a row in the operator registry (`execution/_operator_registry.py`, 312
  lines on main), so the native planner, the chunk iterator and unified admission all decline
  them as "no kernel".
- Unified sends every `top_code` node to the full-frame wrapper (`ADMITTED_GLOBAL_STRATEGIES`,
  `execution/physical/_shadow_full_frame.py:119`). The unified caller passes no relationship
  graph or adapter to `ShadowCoordinator.run` (`execution/_unified_slice.py:256`), so a plan that
  enters the wrapper from unified fails in `_require_full_frame_deps` (`_shadow_full_frame.py:220`).
- Three tests use `bucketize` as the stand-in for "declined, no kernel"
  (`tests/parity/native/test_phase2_gate.py:438`, `tests/native/test_native_plan_config_aware.py:405`
  and `:564`). They go wrong the moment bucketize is admitted.

## Guarantee and non-goals

Guarantee, on the S1b merge head:

1. An eligible row-local table with `bucketize` or `top_code` columns runs `native_bucketize` or
   `native_top_code` on backend `arrow_python` on the unified and chunked routes. Output, Arrow
   types and row errors equal a forced full-frame pandas run, except the named byte changes B2,
   B3 and B4 that S1a shipped. Warnings keep their existing scope: on chunked, each chunk's
   `top_code_generalized` warning equals the handler run on that same chunk (the job publishes
   the ordered union, `_pipeline_auto_chunk.py:460-462,579-580`); on unified, one warning per
   column with counts summed over batches equals the full-frame warning.
2. A column outside the numeric domain, a valid config the operator declines, a pandas-metadata
   identity miss or a failed resident round trip runs the oracle and publishes one coded decline
   record (parent section 4, "Published route evidence").
3. On unified, a `top_code` node on the admitted post-cast snapshot goes to the per-node runner,
   declared or not (parent item 10a). Raw snapshots keep every `top_code` node as a wrapper
   trigger, as on main.
4. Widths and thresholds come only from config literals or presets.

Non-goals: raw physical per-node top_code (S1p); sequential FK and out-of-core operators;
automatic chunk planner gates (both stay, parent section 12); job-level warning aggregation;
Rust kernels.

## What exists after the dependencies (reuse, do not rebuild)

- S1k: `bucketize_array`, `top_code_array`, `python_float_str` in `kernel/_bucket.py`; shared
  settings and the `top_code_generalized` warning builder in the strategy package interface.
- S1w: `BucketizeParams`, `TopCodeParams` (`native/_operator_params.py`); scalar entries in
  `native/_kernels_scalar.py`; typed step in `native/_operator_step.py`; physical bindings in
  `physical/_shadow_operators.py` and `_shadow_bindings.py`; the `chunk_degenerate_null` fact.
- S1d: raw NaN rendering, per-column warning accumulation, the attributed row-error map and the
  leaf `contracts/format_error_reasons.py`.
- S1e: decline transport from requirements and resident gates; `SOURCE_TYPE_NOT_NUMERIC`.
- S1g: shared F06 projection, shared top_code integer-column selection, the pandas-metadata
  identity predicate in `native/_real_type_admission.py`.
- S1r: the per-chunk routing function in `native/_real_type_admission.py`; the mixed-route
  evidence merge in `native/_chunked_evidence.py`, which keeps `decline_records` preflight-
  constant on every chunk and puts a chunk-local refusal in a separate chunk field, so the fold
  checks at `native/_chunked_evidence.py:221,261` and `_chunked_output_sink.py:241` do not
  raise.

## Design

S1b is wiring. It adds no operator code and no new module.

1. **Registry rows (parent item 8).** Add `native_bucketize` and `native_top_code` to
   `_operator_registry.py`: `shape="kernel"`, backend `arrow_python`, no required kernel, no
   compiled-kernel evidence, the numeric input domain (int8, int16, int32, int64, uint8, uint16,
   uint32, float64) as one immutable type set. The #807 kernels already check the same types
   (`kernel/_bucket.py:88-98,214,294`); both the registry rows and the kernel guard read that
   one set, defined in the kernel package so the registry keeps its import isolation
   (`tests/sentry/test_operator_registry_sentry.py:84-94`), `full_frame_assembly="null_on_empty"`, `chunk_degenerate_null=True`.
   Routed diagnostics: bucketize `reduce_row_error:format_error`; top_code that plus
   `reduce_warning:top_code_generalized`. Correct top_code's stale capability note in
   `native/_capabilities.py` (581 lines; stays at or below 600).
2. **Dispatch, bindings and config rejections.** Connect the S1w scalar entries and physical
   bindings to the new spec IDs. S1e ships only the transport, so S1b adds the two strategy
   config rejection functions in `native/_operator_config_rejections.py` (parent item 12:
   integer width out of operator range, declared integer output) and calls them from both
   `native/_plan.py:_config_rejection` (`:305-311`) and `native/_requirements.py:_config_gate_rejection`
   (`:622-625`). Without them a valid `2**53` width reaches a kernel that raises
   (`kernel/_bucket.py:217-219` on #807). Registry rows, dispatch, bindings, config rejections
   and the S1g and S1r gates start acting in one commit so no head has a row without its gate.
3. **Unified post-cast fact (parent item 10a).** `_unified_slice` passes an optional keyword to
   `ShadowCoordinator.run` that marks the snapshot as the admitted post-cast table. Default is
   raw; no other caller passes it. In `dispatch_full_frame_if_applicable`, a `top_code` node on
   a post-cast snapshot is not a trigger when its column type is in the registry domain (read
   from the spec, not a second list), its binding resolves to `native_top_code` and the S1g
   identity predicate admits the column. Shuffle, grouped_series and derived_aggregate stay
   triggers. `_require_admitted_global_strategies` keeps its current set.
4. **Unified decline publication (parent item 14).** Surface the attributed config refusal, the
   numeric type refusal, the identity refusal and the round-trip miss in unified admission, in
   that precedence. The round-trip gate returns before physical compilation
   (`_unified_slice_admission.py:386-400`, `_unified_slice.py:220`), and the full-frame fallback
   later assigns the whole `quality_metrics["execution"]` object (`_pipeline_full_frame.py:285-293`).
   So pass an invocation-local decline collector from `_unified_slice` to `_pipeline_full_frame`
   beside the existing optional result, and attach
   `quality_metrics["execution"]["unified_slice_decline"]` (reason plus serialized records)
   after that assignment.
5. **Negative controls.** In `test_phase2_gate.py:438` replace the bucketize stand-in with a
   column that still declines (a `float32` bucketize column). In both planning controls of
   `test_native_plan_config_aware.py` (`:405`, `:564`) use a strategy that still has no kernel;
   the old `INT_DECL` fixture at `:571-580` stays green either way because
   `declared_integer_output` already gives `python_only` (`plan/_seed_envelope.py:229-234`).
   Keep their route, kernel-call and parity assertions.
6. **Docs.** CODEMAP rows, the route contract, `docs/strategies.md` route lines for both
   strategies, and `changelog.d/bucket-topcode-native.md`.

Choke point: the registry row is the one admission fact. Native planner, chunk routing, unified
admission and the wrapper trigger all read the domain and backend from the spec. Guard: P7 exact
registry delta. Mutation: drop `uint32` from the spec domain; P7 and the P4 uint32 case go red.

Design notes: the post-cast fact is a keyword on the one call that needs it rather than a field
on the snapshot, so a raw snapshot built anywhere else cannot claim it. 10b (raw snapshots) is
a separate slice because it needs the F06 declaration check from the live plan's seed envelope.

### Placement

| New or changed | Path | CODEMAP rule | Sits beside |
|---|---|---|---|
| Registry rows | `src/decoy_engine/execution/_operator_registry.py` | existing | other operator specs |
| Wrapper trigger | `src/decoy_engine/execution/physical/_shadow_full_frame.py` (394; stays at or below 600) | existing | |
| Post-cast keyword | `src/decoy_engine/execution/_unified_slice.py` (473), `physical/_shadow_coordinator.py` | existing | |
| Unified declines | `src/decoy_engine/execution/_unified_slice_admission.py` (559; at most 599) | existing | |
| Cross-route tests | `tests/parity/native/test_bucket_topcode_native.py` | native parity package | `test_parity_matrix.py` |
| Fragment | `changelog.d/bucket-topcode-native.md` | release fragments | |

No new source module. The S1r budgets stand: `native/_chunked_entry.py` at or below 688,
`native/_dispatch.py` at or below its 688 ceiling, `native/_requirements.py` below 677. If a
budget cannot be met, stop and report; do not raise a ceiling.

## Behavior and failure modes

| Input | Route | Result |
|---|---|---|
| Null-free int64, int32, uint32, float64 | unified, chunked | `arrow_python`, output equal to forced full frame |
| Nullable int64 top_code, no floor | unified | protected integer dtype; `-(2**53 + 1)` renders `"-9007199254740993"` |
| Nullable int64 top_code | auto chunk | planner refusal, full frame (gates kept: `_planner.py:499-505`, `chunked/_source_dtype_gate.py:123-128`) |
| Float32 or uint64 bucketize column | both | oracle, `source_type_not_numeric` record |
| Valid NaN in a float64 chunk after normalization | chunked | NaN stays a present float label, not null (P2 literal) |
| Partly-null int64 bucketize | unified | round-trip decline, oracle output, `resident_round_trip_mismatch:{column}` |
| Float32 metadata on a double column | unified | table decline `pandas_metadata_not_identity:{column}` before the round trip |
| Float32 metadata on chunk two only | chunked | chunk one native, chunk two oracle, decline on chunk two and in the fold |
| Width `2**53` (valid, out of operator range) | both | oracle, `bucketize_integer_width_out_of_range:{column}` |
| Declared integer output | both | oracle, `bucketize_declared_integer_output:{column}` |
| Declared post-cast top_code | unified | per-node runner, no wrapper call |
| Declared raw strings `["45","92","oops"]` | raw physical snapshot (not unified) | wrapper, as on main |
| Admitted int64 top_code | raw physical snapshot | wrapper, as on main (10b is S1p) |
| Out-of-range bucketize cell, fail mode | unified, chunked | `RowErrorsFailedError`, rebased row index, nothing published |
| Over and under counts in two batches | unified | one warning with summed counts |

## Acceptance tests (red first)

Red-before means red on the S1r merge head, because the operators are not admitted there.

1. **P4 route parity (red-before).** Parent P4 table rows for S1b: executed `arrow_python`,
   operator ID in coordinator evidence, step spy invoked, no companion call; output and schema
   equal forced full frame at 2,000 resident rows and 120,000 chunked rows at chunk sizes
   1,000, 7,919 and 50,000. Chunked warnings are compared per chunk before aggregation. Unified
   warning aggregation uses two observed batches (inject a small batch size; 2,000 rows fit in
   one default 50,000-row batch, `physical/_shadow_context.py:75,138`) with counts (2,1) and
   (3,4), expecting one warning with (5,5). Params lifetime: width 10 then 7 on 19 gives `"10"`
   then `"14"`.
2. **P2 route cases (red-before).** Parent P2 on the activated routes: literal labels, validity
   bits and zero spurious row errors across int64 min/max, signed zeros, subnormals,
   infinities, `±2**53` and valid NaN after chunk normalization (a rebuilt chunk loses schema
   metadata, `native/_chunk_schema.py:140-156`); exact public declines for float32 and uint64.
   Plus #790's typed-date parity and decline regressions (parent section 7, overlap note).
3. **P4b public case (red-before).** Through `_route_chunked`: chunk one `Float64` metadata
   native, chunk two `Float32` metadata oracle, labels `"1"`, `"16777216"`, `"16777216"`, no
   warning. `decline_records` is the same preflight list on both chunks; chunk two's refusal is
   in its chunk-local field; both folds (retained and streamed) publish the ordered union, with
   the detail in `reroute_reason` and the four wire fields of the record
   (`native/_route_decline_codes.py:78-85`) intact.
4. **P11 unified per-node top_code (red-before).** Typed undeclared int64 and declared post-cast
   input: per-node runner, wrapper spy not called, no `UnifiedSliceInvariantError`,
   `unified_slice_activation` published, output equal to forced full frame.
5. **P11 controls (pin, plus new API coverage).** `tests/physical/test_shadow_full_frame.py:445`
   `test_top_code_warning_and_row_error_parity` unchanged, still on the wrapper. A raw,
   admitted int64 top_code snapshot with wrapper deps still takes the wrapper (assert
   `driver_invocation`), so a raw caller that wrongly defaults to post-cast goes red. The direct
   coordinator test (new keyword, so not red evidence): post-cast snapshot with `Float32`
   metadata and wrapper deps takes the wrapper and renders `"16777216"` with zero warnings. The
   public `Float32` unified control asserts the detail `pandas_metadata_not_identity:x` and zero
   coordinator calls, not only oracle output.
6. **P5 publication (red-before for the native legs).** Unified fail mode with the first bad row
   in a later batch: spy on the coordinator's returned output and records before
   `_unified_slice` finalizes or falls back (`_unified_slice.py:325-330,370-372`); assert the
   null cell and every ordered (table, column, row_index, trigger, reason) against literals;
   then check the public `RowErrorsFailedError` separately. Chunked: prove which backend made
   the failing chunk (native step spy or counting oracle delegate), inspect its result and
   `str(exc)` for the bad value; summary chunk_index 1, offset L, row 2; chunk two never
   yielded; nothing published through the transactional sink.
7. **P6 valid declines (red-before for route evidence).** Width `2**53` and declared integer
   output: exact detail in raw eligibility, compiled requirements, unified fallback leaf and
   chunk evidence; flag-off and second-run controls publish nothing stale.
8. **P7 registry delta (red-before).** Hand-written two-row delta on
   `tests/native/test_operator_tables_snapshot.py`; exact `chunk_degenerate_null` true set
   {bucket_perturb, bucketize, top_code}; the three replaced negative controls; a guard that
   the kernel's type check and the registry domain are the same set, checked against the
   hand-written P7 matrix.
9. **P8 other lanes (pin).** Sequential FK non-key pair unchanged except B2/B3 on handler
   routes. Out-of-core: bucketize keeps its specific refusal and top_code its generic refusal
   (`out_of_core/_compat.py:78-82,356-361`).
10. **P9 HIPAA preset (red-before).** `hipaa_age` top_code at 120,000 typed rows, unified and
   chunked, `arrow_python`, equal to forced full frame.

Mutations (run on the final head):

| ID | Mutation | Test that must fail |
|---|---|---|
| A1 | Drop the post-cast keyword from the unified call | P11 declared case |
| A2 | Remove the identity condition from item 10a | P11 direct coordinator control |
| A3 | Remove the unified identity check (item 14) | P11 `Float32` public control |
| A4 | Check only chunk one (rev 6 behavior) | P4b: chunk two emits `over` and a warning |
| A5 | Replace warning accumulation with assignment | P4 two-batch warning aggregation: reports (3,4) |
| A6 | Drop `uint32` from the spec domain | P7 and P4 uint32 case |
| A7 | Cache params by column name only | P4 params lifetime |
| A8 | Disable row-index rebasing | P5 unified pre-finalization record assertion |
| A9 | Set `chunk_degenerate_null` on text_mask | P7 exact true set |
| A10 | Yield the failing chunk before raising (`native/_chunked_entry.py:353-380`) | P5 chunked never-yielded assertion |
| A11 | Drop the width rejection from `_requirements.py` only | P6 compiled and route checks |
| A12 | Widen the kernel type set without the registry | P7 kernel-registry guard |

## Enumerations

### Exit paths

- Success on unified and chunked, `arrow_python` evidence per column.
- Declined table or chunk: oracle output plus one coded record; the job still succeeds.
- Row error in fail mode: `RowErrorsFailedError` before any output is published (chunk two
  never yielded, `native/_chunked_entry.py:344-380` path kept).
- Row error in quarantine mode: quarantine bypasses unified; full frame and sequential FK keep
  their handler records (P5).
- Unified invariant error: must not occur for a top_code plan on a post-cast snapshot (P11).

### Routes

- Unified: per-node runner for admitted nodes; wrapper only for shuffle, grouped_series,
  derived_aggregate and non-admitted top_code (`execution/physical/_shadow_full_frame.py:124`).
- Chunked (native iterator): per-chunk routing from S1r; native for admitted chunks.
- Auto chunk planner: gates unchanged (`execution/_planner.py:499-505,508-526`).
- Full frame and sequential FK: handler, unchanged (P8). Out-of-core: existing refusals.
- Raw physical snapshots (not unified): every top_code node stays a wrapper trigger until S1p.

### FK shapes

- FK key columns: the existing FK checks decline them; P8 adds a key-column fixture so the
  class 5 mutation has a test.
- Non-key child column on sequential FK: handler path, pinned in P8.

### Fields

| Field | Values |
|---|---|
| Executed backend | `arrow_python` or the oracle |
| Decline code | `source_type_not_numeric`, `fallback_policy_not_native` |
| Decline detail | `{strategy}_source_type_not_numeric:{column}:{type}`, `bucketize_integer_width_out_of_range:{column}`, `bucketize_declared_integer_output:{column}`, `pandas_metadata_not_identity:{column}`, `resident_round_trip_mismatch:{column}` |
| Warning | `top_code_generalized` with `over_count`, `under_count` |
| Row error | trigger `format_error`, reason `value is out of range under bucketize` |

### Output surfaces

- Masked output table and its Arrow schema (degenerate columns are Arrow null).
- Route evidence: per-chunk and aggregate `decline_records`, `reroute_reason`,
  `quality_metrics["execution"]["unified_slice_decline"]`.
- Run warnings and row-error records, quarantine JSONL.
- Docs: CODEMAP, route contract, `docs/strategies.md`, changelog fragment.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Decline details carry names and types only; row-error reason is the fixed leaf text | P5 full record compare | Put the cell value in a detail: P6 exact detail red |
| 2 | Cleanup on an exit path | Failing chunk never yielded; transactional sink publishes nothing | P5 chunked | A10, yield before raise |
| 3 | Shared state | Params built per column and invocation | P4 params lifetime | A7, name-keyed cache |
| 4 | Route parity and silent fallback | Every decline is coded and published; forced full frame is the reference | P4, P6 | A4, chunk one only |
| 5 | Referential integrity | FK key columns decline through existing checks | P8 sequential FK pair | Admit FK key column: P8 red |
| 6 | Untrusted producer | Pandas metadata checked by the identity predicate before values are read | P4b, P11 Float32 | A2, A3 identity off |
| 7 | Check-then-use (toctou) | Per-chunk decision on the raw chunk before normalization (S1r) | P4b | A4, chunk one only |
| 8 | Weak tests | Expected labels are literals, not computed from production specs | P7 hand-written delta | A9, text_mask degenerate |
| 9 | Refactor drift | Negative controls keep route, kernel-call and parity asserts | three replaced controls | Leave bucketize stand-in: control red |
| 10 | Frozen contract drift | Registry snapshot delta and fragment; no digest or seed change; one type set for kernel and registry | P7 snapshot test | A6, A12 |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | No new text grammar |
| 2 | Strict wire types | Decline records use the existing four-field serializer |
| 3 | No exception context | Admission turns resolver refusals into value-free declines, no cause kept |
| 4 | Versioned read models | No persisted plan version change; run-local decline stays out of plan digests |
| 5 | Normalized guard scanners | P10 from S1k still runs on the head |
| 6 | Private modules | Strategy package interface and `decoy_engine.kernel` exports only |
| 7 | No hidden CI failures | Read the exit status and failing IDs; no skip marks added |
| 8 | One input, one trust class | Raw chunk and resident frame both pass the same identity predicate |
| 9 | Mutations on the final head | A1 to A9 after the last edit |
| 10 | Allowlisted helpers still checked | Lossless-ingest and width caller sentries run unchanged |
| 11 | No raised caps | No ceiling, census, baseline or pin change |

## Reuse inventory

- Operators, settings and warning builder from S1k; params, steps and bindings from S1w.
- Diagnostics plumbing from S1d; decline transport and code from S1e.
- Identity predicate and integer-column selection from S1g; per-chunk routing from S1r.
- Existing unified coordinator row-error routing and `per_node_warnings`.

## Frozen contracts

- Operator registry snapshot: two new rows (hand-written delta).
- Route decline wire values: no new code in S1b (S1e added `source_type_not_numeric`).
- Output bytes on handler routes: unchanged beyond B2 to B4 (S1a).
- Seed protocol, plan digests and release pins: unchanged.

## Slices

One PR: `feat(execution): run bucketize and top_code natively on chunked and unified`.
Commits inside it may be split for review, but registry rows, dispatch, bindings and gates land
in one commit.

Test depth: T0 per edit; T1 impact selection per commit; T2 on the exact head with P2 route
cases, P4, P4b, P5, P6, P7, P8, P9, P11, #790's date regressions and A1 to A12. Escalation trigger: registry snapshot (frozen contract), so one
full suite on the merge head against the stored main baseline.

## Pre-mortem

- A dependency changes a name this plan uses (spec field, predicate, keyword). The builder
  re-anchors on the S1r head and reports each rename; the parent plan wins.
- The post-cast keyword leaks to a raw caller and admits declared raw text. A1 and the unchanged
  raw-text control catch it.
- Admission passes but the chunk iterator still runs the oracle because dispatch tables were not
  connected. P4 asserts the step spy, not only the evidence.
- `native/_dispatch.py` grows. Parent section 7 requires zero or negative net change there; the
  sentry ceilings are 689 for `_chunked_entry`, 688 for `_dispatch` and 677 for `_requirements`
  (`tests/sentry/test_module_size.py:113,116,124`). Run the size and import sentries on the
  combined base and on the head.
- A budget cannot be met in `_unified_slice_admission.py` (559 now, 599 limit). Put decline
  construction in `native/_operator_config_rejections.py`; if still over, stop and report.
- HIPAA preset run is slow on a laptop node. P9 runs on the Dell through `vm-run`.

## Builder brief items

- Do not start before S1g, S1d and S1r are merged; check merged PRs first.
- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; `~/bin/pytest-one`; native companion tests need the lock-faithful
  venv.
- Expected labels and registry facts are literals; never refresh a snapshot to pass.
- `ruff check`, `ruff format --check`, `mypy` before each commit; changelog fragment in the PR.
