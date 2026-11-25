Status: plan (revision 3, 2026-11-25, after Dennis round 1 and Codex round 1)

# BUCKET-TOPCODE-NATIVE S1b: activate the Arrow bucketize and top_code operators on chunked and unified

Owner: Cam. Author: Opus (plan author). Roadmap row: BUCKET-TOPCODE-NATIVE (group mask). Engine only. This is a slice plan under the parent plan `docs/plans/2026-11-22-bucket-topcode-native.md` (rev 9, branch `plan/bucket-topcode-native`, `2882e1d90`). The parent plan stays the authority for behaviour, the numeric domain, the byte changes B2 to B4 and the P-gates. This file pins what S1b consumes, what it changes, and how its gate is run, on the current code.

Source anchor: engine main `2b8a47fbe`; PR #807 (S1k) at `f2c5bd225`; PR #790 at `b6c7785d5` (open). Paths without a prefix start at `src/decoy_engine/`. Builders re-anchor line numbers on their merge head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `feature-dev.md`, `cross-cutting-concerns.md`, `architecture.md` (layout, size); engine `CODEMAP.md` ("Where things go").

Risk: R2 (two anonymisation strategies move off pandas on two routes; the HIPAA template uses top_code). Plan review: Dennis, then Codex. Code gate: Codex, then Dennis (parent plan header).

## 0. Status: not buildable yet

S1b is the activation slice. It starts after S1g, S1d and S1r (parent section 7), which in turn need S1e, S1w and PR #790. On 2026-11-25:

| Prerequisite | State | Blocks S1b because |
|---|---|---|
| S1a (oracle range errors, B4) | merged (#804) | none |
| S1k (kernels, settings) | PR #807 open, gate-ready, `f2c5bd225` | S1w builds on it |
| PR #790 (typed date32 date_shift) | open, `b6c7785d5`, earlier CI red | S1e and S1w branch after it merges (parent section 7, overlap list) |
| S1e (decline transport, `SOURCE_TYPE_NOT_NUMERIC`) | not built | S1b publishes declines through it |
| S1g (F06 projection, top_code integer selection, metadata identity predicate) | not built | S1b's admission and 10a read the predicate |
| S1w (params, step, scalar entries, bindings, degenerate fact) | not built | S1b turns these on |
| S1d (diagnostics, warning accumulation, row-error map) | not built | S1b's P5 and warning gates need it |
| S1r (per-chunk routing) | not built | S1b's public P4b case needs it |
| CODE-SET-NATIVE S2a (value-free source conversion, `docs/plans/2026-11-25-code-set-native-s2a-s2b.md`) | not built, can start now | a chunk that declines on metadata goes to the chunked oracle, whose conversion error re-raised at `execution/_chunked_oracle.py:471` carries the cell value (for example `99876543210`); S1b would route more chunks there |

Critical path from today: #790 merge, then S1e (1.0) then S1g (1.0) then S1r (1.5), in parallel with S1w (1.0) then S1d (1.0), then S1b (2.0). CS S2a (0.5) runs in parallel and lands before S1b. About 6 builder-days after #790 lands if both lanes run at once.

## 1. What S1b assumes from PR #807 (S1k)

S1b does not call the kernel directly; S1w's step does. S1b relies on these names at `f2c5bd225` staying as they are on merge. If #807 changes any of them before merge, S1w re-anchors and S1b follows S1w.

| Name | Module | Used by |
|---|---|---|
| `bucketize_array(values, width, fmt, *, exceptional=None) -> BucketizeResult(labels, exit_positions)` | `kernel/_bucket.py`, exported from `decoy_engine.kernel` | S1w step; S1b gates read `exit_positions` through S1d's row-error map |
| `top_code_array(values, cap, over_label, floor=None, under_label=None, *, exceptional=None) -> TopCodeResult(labels, over_count, under_count)` | same | S1w step; S1b's warning gate reads the counts through S1d |
| the numeric domain constant in `kernel/_bucket.py:88` | same | S1b step 3: the registry rows and `numeric_operator_admits` read this one immutable domain; no second list |
| `SparseLabels`, `python_float_str`, `integer_width_exit_mask`, `floor_multiple` | same | S1d raw NaN rendering; P3 already gated on #807 |
| `resolve_bucketize_settings`, `resolve_top_code_settings`, `BucketizeSettings`, `TopCodeSettings` | strategy package | S1w params; S1g config rejection |
| `render_exceptional_bucket_labels`, `render_exceptional_top_code`, `top_code_warning` | strategy package | S1d warning builder; S1b P4 warning rows |

## 2. What S1b assumes from the other slices

The builder checks each name on the S1b base before starting. A missing or renamed name stops the build and is reported; S1b does not add it.

| From | Interface S1b consumes |
|---|---|
| #790 | `ResidentTypeDomain.admits` (`_operator_registry.py`), `policy_decline` (`native/_real_type_admission.py`) |
| S1e | the optional attributed numeric-operator decline carried on node requirements and consumed in `native/_dispatch.py` before the generic policy refusal; `SOURCE_TYPE_NOT_NUMERIC` and `route/source_type_not_numeric`; `quality_metrics["execution"]["unified_slice_decline"]` publication |
| S1g | the shared F06 projection; the shared top_code integer-column selection used at both ingest points (`execution/_fk_keys.py:369`, `:406`); the pandas-metadata identity predicate in `native/_real_type_admission.py`, called by unified admission and the chunk preflight |
| S1w | `BucketizeParams`, `TopCodeParams` (`native/_operator_params.py`); scalar entries (`native/_kernels_scalar.py`); step dispatch with `StepResult` positions and counts (`native/_operator_step.py`); spec IDs `native_bucketize`, `native_top_code` with unkeyed params (`physical/_shadow_operators.py`); the namespace-safe binding change (`physical/_shadow_bindings.py`); the `chunk_degenerate_null` registry field, true on bucket_perturb only until S1b |
| S1d | per-column (operator ID, positions) in `_chunk_masking.py`; attributed drain in `_chunked_row_errors.py`; warning accumulation per column across unified batches; `per_node_warnings` at column scope |
| CS S2a | `source_pandas_conversion_failed` raised value-free by `table_to_pandas_exact_ints` (`internal/pandas_compat.py`) for every pandas route, including the chunked oracle |
| S1r | the per-chunk routing function in `native/_real_type_admission.py` and its use in the native chunk iterator; the mixed-route evidence merge in `native/_chunked_evidence.py` |

## 3. Established solutions

S1b adds no algorithm. It follows the activation pattern the engine already used for `native_bucket_perturb` and `native_text_mask` (registry rows at `_operator_registry.py:245` and `:175`): code paths land unreachable, and one registry row per operator turns them on, so membership has one source. Search run: `rg "operator_id=\"native_" src/decoy_engine/execution/_operator_registry.py` and the parent plan's section 2 (Arrow compute for the arithmetic, Python `str(float)` for labels).

### Reuse inventory

- Registry rows and `ResidentTypeDomain` (`execution/_operator_registry.py`, 312 lines on main): the single activation switch and the numeric domain.
- `ADMITTED_GLOBAL_STRATEGIES` and `dispatch_full_frame_if_applicable` (`execution/physical/_shadow_full_frame.py:119`, `:124`): the wrapper trigger set 10a narrows for top_code.
- `ShadowCoordinator.run` (`execution/physical/_shadow_coordinator.py:149`): gains the post-cast keyword.
- The unified call site (`execution/_unified_slice.py:254`): the only caller that passes it.
- `_require_admitted_global_strategies` (`execution/physical/_shadow_full_frame.py:288`, check at `:296`): keeps top_code in the executable set, unchanged.
- The parent plan's P-gate fixtures (P4 metadata rows, P9 HIPAA column) and the existing snapshot tests (`tests/native/test_operator_tables_snapshot.py`, `tests/native/test_obs2_decline_records.py`).

## 4. Guarantee and non-goals

After S1b, on the chunked route and the unified slice:

1. A bucketize or top_code column whose snapshot or chunk type is in the registry numeric domain, whose config passes the shared config rejection, and whose pandas metadata passes the identity predicate runs `native_bucketize` or `native_top_code` with executed backend `arrow_python`. Its output, Arrow type, warnings and row errors equal a forced full-frame run, apart from B2, B3 and B4 as the parent plan names them.
2. Every other column takes the oracle as on main, and the decline is published with its attributed reason.
3. A unified pure top_code plan runs on the per-node runner (10a), declared or not, and never calls `_require_full_frame_deps`. A raw physical snapshot keeps every top_code node as a wrapper trigger until S1p.
5. A raw physical CHUNKED plan never steps `native_bucketize` or `native_top_code` on a column the shared predicate does not admit: the coordinator checks each binding against the snapshot before stepping and sends a miss to the oracle binding.
4. No message or log line carries a data value.

Non-goals: raw physical snapshots skipping the wrapper (S1p); sequential native and out-of-core operators (parent V2-LOG, open item 2); float32, uint64, decimal and declared-integer-output bucketize (parent V2-LOG); any change to the kernels (S1k) or diagnostics plumbing (S1d).

## 5. Enumerations

### Exit paths (one bucketize or top_code column on an activated route)

| # | Condition | Result |
|---|---|---|
| X1 | config rejection (width or cap native-declined, for example width `2**53`) | oracle; decline `fallback_policy_not_native` with the config detail (S1e transport) |
| X2 | type outside the numeric domain | oracle; `source_type_not_numeric` |
| X3 | pandas-metadata identity miss (resident frame or a chunk) | oracle for that table (unified) or that chunk (chunked, S1r); `pandas_metadata_not_identity:<column>` |
| X4 | unified numeric round-trip miss | existing round-trip decline, now attributed (parent item 14) |
| X5 | admitted, a cell is out of range (B2/B3) | Arrow step, null cell, one `format_error` row error at the rebased row index |
| X6 | admitted, top_code values over or under the bounds | Arrow step, labels, one `top_code_generalized` warning per column with summed counts |
| X7 | admitted, empty or all-null column or chunk | Arrow null type through `chunk_degenerate_null`, then the schema reconciliation |
| X8 | empty input table on the chunked entry (`execution/native/_chunked_entry.py:458`, `empty_input`) | exits before any operator, unchanged; AT-2 keeps the case |
| X9 | a chunk declines on metadata and its oracle conversion fails | `source_pandas_conversion_failed` from CS S2a, value-free (AT-11) |
| X10 | raw physical CHUNKED binding whose column the predicate does not admit | oracle binding for that column, attributed decline (step 4b) |

### Routes

| Route | Before S1b | After S1b |
|---|---|---|
| chunked (`execution/native/_chunked_entry.py:284`, `_guard`, where S1r adds the per-chunk decision) | oracle for both strategies | Arrow per chunk where admitted; declined chunks on the oracle (S1r) |
| unified slice, bucketize | oracle (no kernel) | per-node Arrow step |
| unified slice, top_code | wrapper (`execution/physical/_shadow_full_frame.py:119`, called from `execution/_unified_slice.py:254`) | per-node Arrow step when unified admission admits the table (10a). The wrapper cannot run in unified: the unified `ShadowContext` has no relationship graph, namespace registry or full-frame adapter, so `_require_full_frame_deps` (`execution/physical/_shadow_full_frame.py:220`) raises and `_unified_slice.py:257` turns it into `UnifiedSliceInvariantError`, which fails the job. Invariant: unified admission admits a top_code column only if 10a admits it, enforced by one shared predicate (step 4) |
| mixed lane (`execution/_pipeline_mixed_route.py:228` calls `run_auto_chunk`; also reached from `execution/_pipeline_multi_table.py:385` and `execution/_pipeline_route_exec.py:574`) | bucketize on the oracle, including FK-coupled child tables | bucketize on Arrow where admitted, in the independent and FK-coupled topologies; B2/B3 row errors fail closed as on the chunked route; top_code still declines through `_mixed_admission.chunk_unstable_warning_column` |
| physical chunked driver (`execution/physical/drivers/_chunked.py:169`) | oracle | same per-chunk decision as the chunked route |
| raw physical CHUNKED plan through the coordinator (`execution/physical/_shadow_coordinator.py:183`, `execution/physical/_shadow_mixed.py:196`, `execution/physical/_shadow_batch_runner.py:205`) | binding picked by spec ID without a type or metadata check | each binding checked with `numeric_operator_admits` against the snapshot before stepping (step 4b) |
| per-table chunked routing (`execution/_pipeline_multi_table.py:455`, `chunked_route_by_table`) and `NativeOrOracleChunkedAdapter.run` | oracle | same per-chunk decision; AT-1 covers a multi-table job |
| native dispatch decline point (`execution/native/_dispatch.py:671`) | generic policy refusal | attributed decline from S1e, unchanged by S1b beyond the rows |
| physical raw snapshot | wrapper for top_code | unchanged (S1p) |
| sequential FK, out-of-core | handler; out-of-core refuses bucketize (`execution/out_of_core/_compat.py:78`) and has no top_code entry | unchanged (P8 controls) |
| full frame | handler (reference) | unchanged |

### FK shapes

- FK relationship tables on the plain chunked route: the chunk dispatcher declines them as on main; unified admission keeps its existing FK checks.
- FK-coupled child tables on the mixed lane: non-key columns already run native operators there (hash is the witness in `tests/parity/test_phase_f_f2_mixed_sweep.py`, topologies `coupled_int` and `coupled_str`). After S1b a bucketize non-key column on such a table runs Arrow too. Both operators are unkeyed and row-local, so a coupled table gains no cross-table dependency; AT-12 pins the output.
- Sequential FK non-key child column: the handler masks it, unchanged (P8 control).
- bucketize or top_code on a key column: compile refuses as on main; S1b adds no admission for key columns.
- Composite FK: a bucketize non-key column on a child of a composite key runs Arrow on the mixed lane like the single-key case; AT-12 adds a composite control.

### Fields

- Registry rows (parent P7 table): IDs `native_bucketize` and `native_top_code`, backend `arrow_python`, input types int8, int16, int32, int64, uint8, uint16, uint32, float64, diagnostics `reduce_row_error:format_error` (both) plus `reduce_warning:top_code_generalized` (top_code), `full_frame_assembly="null_on_empty"`, `chunk_degenerate_null=True`, no pool, companion, index, required kernel, positive compiled evidence or tokenizing.
- `ShadowCoordinator.run(..., post_cast: bool = False)`: invocation-local; only `_unified_slice` passes `True`; never serialized.
- `chunk_degenerate_null` true set: exactly bucket_perturb, bucketize, top_code.

### Output surfaces

| Surface | Change |
|---|---|
| per-column `executed_backend` in chunk, aggregate and coordinator evidence | `arrow_python` for admitted columns |
| `decline_records`, `reroute_reason`, `unified_slice_decline` | attributed declines for X1 to X4 |
| warnings | one `top_code_generalized` per column per scope with summed counts; scope is the column across all batches of one table run (unified) or all chunks (chunked), never across tables |
| row errors and quarantine | B2/B3 records at rebased indices (unchanged texts from S1a) |
| `unified_slice_activation` | published for pure top_code unified plans |
| docs | CODEMAP rows, route contract in `docs/execution-backends.md`, activation entry in `docs/compatibility-contract.md`, changelog fragment |

## 6. Acceptance tests

S1b's gate is the parent plan's gate set for this slice. They are referenced, not copied. AT-n below are the S1b-specific obligations on top.

| ID | Test | Parent gate | Fail-before |
|---|---|---|---|
| AT-1 | Route cases of P2 (executed route, published decline, chunk legs) through the public pipeline | P2 | oracle backend on main |
| AT-2 | P4 table, every row, unified and chunked, 2,000 resident and 120,000 chunked rows at chunk sizes 1,000, 7,919 and 50,000 | P4 | no `arrow_python` on main |
| AT-3 | Public P4b case through `_route_chunked`: chunk one `Float64` metadata on Arrow, chunk two `Float32` metadata on the oracle, no `over` and no warning in chunk two | P4b (S1b case) | M2 |
| AT-4 | P5 production-route assertions (moved to the activation head by the parent's deferred finding): unified rebased row index in a later batch, chunked failing chunk two never yielded, quarantine and fail policies. Two-chunk case: chunk two declines on metadata (int64 physical, `Int32` metadata, value `99876543210`) and its oracle conversion fails; the run raises `source_pandas_conversion_failed` | P5 | M4, M14 |
| AT-5 | P6 compile errors and valid declines, including the width `2**53` decline through requirements, unified fallback leaf and chunk evidence | P6 | M3 |
| AT-6 | P7 registry snapshot deltas as hand-written literals; `SOURCE_TYPE_NOT_NUMERIC` wire value; `chunk_degenerate_null` exact true set; the three negative controls (`tests/parity/native/test_phase2_gate.py:438`, `tests/native/test_native_plan_config_aware.py:405`, `:564`) rewritten to a column that still declines (`float32` bucketize) and a strategy that still has no kernel, keeping their route, kernel-call and parity assertions | P7 | snapshot red on activation without the delta |
| AT-7 | P8 other lanes: sequential FK non-key pair and out-of-core controls unchanged | P8 | none (control) |
| AT-8 | P9 HIPAA `hipaa_age` top_code at 120,000 typed rows, unified and chunked, `arrow_python` | P9 | oracle on main |
| AT-9 | P11 unified top_code on the per-node runner: typed undeclared int64 and declared post-cast input run `native_top_code` with no wrapper call and no `UnifiedSliceInvariantError`; raw declared-string control `test_top_code_warning_and_row_error_parity` unchanged on the wrapper; unified `Float32` control declines before the coordinator; direct coordinator test with a post-cast snapshot and `Float32` metadata takes the wrapper | P11 | `UnifiedSliceInvariantError` path on main once the operator exists; M1 |
| AT-10 | Atomic activation: with the registry rows present and any one of the config, type or metadata gates disconnected, at least one of AT-1, AT-2, AT-3 or AT-5 fails (shown once per gate in the builder report) | P2, P4, P6 | M2, M3, M5, M11 |
| AT-12 | Mixed lane: rewrite `tests/parity/test_phase_f_f2_mixed_sweep.py` (`test_mask_strategy_matches_the_oracle_in_every_topology`) with literal expectations. Keep `route == "mixed"`, assert `arrow_python` for the bucketize column in `independent`, `coupled_int` and `coupled_str`, and output equal to the oracle. Do not just flip the spec's `native` flag. Assert top_code still declines on this lane. Add a B2 case on the mixed lane that fails closed: capture the failure at the sink (`RowErrorsFailedError` is not an `ExecutionError`, so assert that type), plus route and backend evidence. Add a composite-key child control. These new cases go in `tests/parity/native/test_bucket_topcode_native.py`; the sweep rewrite stays in its file. Update the SIBLINGS comment that calls bucketize "no operator" | P4, P8 | the sweep's `pandas_oracle` assertion goes red on activation |
| AT-13 | Admission implies 10a, one way: for every P4 and P11 fixture, every top_code node that unified admission admits is skipped by 10a (no wrapper call). The reverse is not asserted, because unified admission also rejects tables for other reasons (for example the NaN round trip). A spy proves 10a calls the shared predicate | P11 | M12 |
| AT-14 | Phase D audit: `tests/parity/_d_audit_matrix.py` classifies the chunked cell from registry fields (`required_kernel`, planned backend) so bucketize and top_code get the Arrow class, not `COMPILED_RUST`. `text_mask` and `text_redact` keep their distinct existing classes; the test asserts each cell's class by literal. `tests/parity/test_phase_d_audit_no_legacy.py` (`test_native_chunked_compiled_cells_cite_their_real_kernel_suite`) stays green without listing them as compiled, and the new chunked suites are cited | P7 | the audit test goes red on activation |
| AT-15 | Unified with a native sibling: top_code plus a hash column in one table runs both per node, no wrapper, output equal to forced full frame. Unified failed-cast controls, by cast policy, on a declared top_code column with an unparseable cell: `fail` raises the coded cast error with zero coordinator calls; `null` and `quarantine` run the per-node step on the cast output with output equal to forced full frame | P11 | M1 |
| AT-16 | Companion-present and companion-absent legs for the route cases in AT-1 and AT-2, and the Dell perf record (wall time and RSS at 120,000 and 1,000,000 rows, three runs each, Arrow against forced full frame) | parent section 7 | none (evidence) |
| AT-11 | Message scan on AT-4 (including the two-chunk case), AT-9 and AT-17 fixtures with distinctive values: no value in `str(exc)`, `repr(exc)`, the exception chain, warnings, row-error reasons, decline details or logs | P5 | M6, M14 |
| AT-17 | Raw physical CHUNKED controls, direct coordinator tests for both operators: (a) a `float32` column and (b) a `double` column with `Float32` metadata, each with a `native_bucketize` and a `native_top_code` binding, take the oracle binding with an attributed decline and output equal to forced full frame; (c) an admitted int64 column steps Arrow. Through `_shadow_coordinator.py:183` and the mixed and batch-runner paths | P2, P4 | M13 |
| AT-18 | Domain guard: the registry rows' input types equal the `kernel/_bucket.py` domain constant; `float32` and `uint64` are outside it and decline on every route (unified, chunked, mixed, raw physical) | P2 | M11, M15 |
| AT-19 | Existing tests that change on purpose: `tests/unit/execution/_auto_chunk_strategies.py:223` and `tests/unit/execution/test_auto_chunk_output_contract.py:113` pin both strategies to `fallback_policy_not_native`; rewrite them to literal `arrow_python` for admitted types and keep a `float32` decline row. Listed in the PR | P7 | red on activation |

## 7. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | drop `post_cast=True` from the unified call | AT-9 declared case |
| M2 | check only chunk one's metadata (no per-chunk routing call) | AT-3 |
| M3 | skip the shared config rejection in `native/_requirements.py` | AT-5 (compiled and route checks) |
| M4 | disable row-index rebasing in the unified coordinator | AT-4 (before finalization) |
| M5 | remove the identity predicate from unified admission | AT-9 `Float32` control |
| M6 | add the cell value to the B2 reason | AT-11 |
| M7 | set `chunk_degenerate_null` true on text_mask | AT-6 exact set |
| M8 | replace warning accumulation with assignment | AT-2 warning row ((5,5) becomes (3,4)) |
| M9 | remove the identity condition from the shared predicate as 10a calls it (parent P11 10a mutation) | AT-9 direct coordinator test: the post-cast snapshot with `Float32` metadata on a physical `double` column gives `over` and a warning instead of `"16777216"` and none |
| M10 | disable only top_code's `chunk_degenerate_null` fact (parent P7 underreach) | AT-2 degenerate-shapes row: a string-typed all-null chunk reaches normalization |
| M11 | admit float32 in the type decision (parent P2) | AT-1 published float32 decline |
| M13 | step a raw physical CHUNKED binding without the predicate check | AT-17 (a), (b) |
| M14 | let the chunked oracle re-raise the pyarrow conversion error (revert CS S2a at the oracle path) | AT-4 two-chunk case, AT-11 |
| M15 | add `uint64` to the registry input types without the kernel domain | AT-18 |
| M12 | in 10a, rebuild the type and metadata check by hand instead of calling the shared predicate, with the metadata check left out | AT-13 |

Mutations run on the final S1b head; the gate records the head.

## 8. Defect classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | B2/B3 reasons, decline details, warnings, oracle conversion errors on declined chunks | reason leaf from S1a, details name column only, CS S2a boundary | AT-11 | M6, M14 |
| 2 | Cleanup missing on an exit path | failing chunk two | S1d fail-before-yield path, unchanged | AT-4 | M4 |
| 3 | State and concurrency | params per invocation, warning counts per column | immutable params per column and run (S1w); counts accumulated per node | AT-2 params-lifetime row and warning row | M8 |
| 4 | Route parity and silent fallback | unified, chunked, wrapper | registry rows as the one switch; declines published with reasons | AT-1, AT-2, AT-6 | M3 |
| 5 | Referential integrity | none new | bucketize and top_code are unkeyed and deterministic; no key column admitted | AT-7 controls | N/A, both strategies are unkeyed and key columns stay refused at compile |
| 6 | Untrusted producer | customer pandas metadata on chunks, resident frames and raw physical snapshots | identity predicate per chunk, per frame and per binding | AT-3, AT-9, AT-17 | M2, M5, M13 |
| 7 | Check then use (TOCTOU) | chunk one decision reused for later chunks | per-chunk routing on each raw chunk before normalization (S1r) | AT-3 | M2 |
| 8 | Weak tests | snapshot deltas computed from production specs | hand-written literal deltas; negative controls rewritten to still decline | AT-6 | M7 |
| 9 | Refactor drift | `ShadowCoordinator.run` keyword, trigger set | keyword with default; only one caller passes it; existing coordinator tests unchanged | T1 physical and unified selection | M1 |
| 10 | Frozen contract drift | plan digests, seed protocol, reason baseline | `post_cast` and decline causes stay run-local, out of plan serialization | existing digest and reason baseline tests unchanged | N/A, no serialized field is added |

## 9. Design

### Design notes

- One switch: the two registry rows are the activation. Code paths from S1w, S1d and S1r are reachable only through them. AT-10 shows the gates and the rows move together.
- One place per fact: the numeric domain is one immutable constant in `kernel/_bucket.py:88` (#807); the registry rows and `numeric_operator_admits` read it (AT-18). Admission, dispatch, 10a and the raw physical binding check all call the one predicate (M9, M13). The identity predicate is S1g's one function.
- No new module, class or registry.

### Placement

No new source files. Cross-route tests go in `tests/parity/native/test_bucket_topcode_native.py` as the parent places them (P2 route, P4, P4b public, P6, P9, AT-10). The 10a and raw physical binding tests go in a new subpackage `tests/physical/native_operators/` (`test_unified_top_code_per_node.py`, `test_raw_chunked_binding_gate.py`), because flat `tests/physical/` is at 62 modules and takes no new file (CODEMAP "Physical seam" row). No slice codes in file names; `tests/native/` is crowded and takes no new file.

### Steps

1. Registry (`execution/_operator_registry.py`): add the two rows per section 5 (Fields) and set `chunk_degenerate_null=True` on both. Correct top_code's stale capability note.
2. Dispatch and binding: confirm on the S1b base which ID-keyed entries S1w left unreachable; add only the remaining membership entries (for example the native scalar slice and kernel sets) so they derive from the rows. S1d owns replacing the bucket special column set in `native/_chunked_entry.py` with the direct map (parent item 9); S1b only asserts the map is present and does not edit that file unless a membership entry needs it. No line is added above the `_native_route` `key_box` line (260): the secret-material census is frozen (section 10). If a membership entry must go above it, the builder stops and reports.
3. Gates: read the registry rows' input types from the `kernel/_bucket.py` domain constant; connect the shared config rejection in `native/_plan.py` and `native/_requirements.py`, the type decision via `ResidentTypeDomain.admits`, and the identity predicate, in the same commit as step 1.
4. 10a: `ShadowCoordinator.run` gains `post_cast: bool = False`, passed through to `dispatch_full_frame_if_applicable`. `_unified_slice.py:256` passes `post_cast=True`. In `_shadow_full_frame.py`, a top_code node is not a trigger when `post_cast` is true, its binding resolves to `native_top_code`, and the shared predicate `numeric_operator_admits(spec, arrow_type, metadata)` in `native/_real_type_admission.py` admits its column. That predicate is the one function unified admission, the S1r chunk routing and 10a all call: it applies `ResidentTypeDomain.admits` and S1g's identity predicate. If S1g and S1r land the two checks as separate calls, S1b folds them into this one predicate (no new module). Shuffle, grouped_series and derived_aggregate always trigger. Without `post_cast` every top_code node stays a trigger.
4b. Raw physical binding gate: before the coordinator steps a `native_bucketize` or `native_top_code` binding (`_shadow_coordinator.py:183`; the mixed and batch-runner callers at `_shadow_mixed.py:196`, `_shadow_batch_runner.py:205` go through the same check), it calls `numeric_operator_admits` on the snapshot field and metadata; a miss rebinds that column to the oracle and records an attributed decline. One check function in `_shadow_coordinator.py`, not three copies.
5. Rewrite the three negative controls (AT-6) and the two auto-chunk pins (AT-19).
6. Docs: CODEMAP rows for the two operators, the route contract section in `docs/execution-backends.md`, the activation entry in `docs/compatibility-contract.md` (route evidence, controls, fallback and warning scope, beside the per-operator `executed_backend` entry), and the changelog fragment.

## 10. Size budgets

| File | Main | Budget on the S1b head |
|---|---|---|
| `execution/_operator_registry.py` | 312 | at most 400 |
| `execution/_unified_slice.py` | 473 | at most 480 |
| `execution/physical/_shadow_full_frame.py` | 394 | at most 440 |
| `execution/physical/_shadow_coordinator.py` | 289 | at most 330 |
| `execution/native/_dispatch.py` | 683 (686 on #790) | 688 or fewer |
| `execution/native/_chunked_entry.py` | 688 | 688 or fewer |
| `execution/native/_requirements.py` | 655 (672 on #790) | below 677 |
| `execution/_unified_slice_admission.py` | 559 (551 on #790) | at most 599 |

No census, allowlist, baseline, cap or pin change (parent section 7). If a budget cannot be met, stop and report; do not raise a ceiling.

## 11. Frozen contracts

- Plan digests and serialization: unchanged; `post_cast` and decline causes are run-local.
- Reason baseline: S1e owns the one new code; S1b adds none.
- Registry snapshot: changes only by the hand-written two-row delta (AT-6).
- Byte changes: only B2, B3 and B4 (S1a), now also on the Arrow routes.

## 12. Pre-mortem

- #790 keeps slipping. Every slice except S1k and S1b's own docs waits on it. If #790 is not merged by 2026-12-01, re-plan S1e and S1w against main and move #790's overlap into whichever lands second (owner call candidate, not assumed here).
- S1w lands the bindings already reachable (the spec IDs alone make the physical path pick them). Then S1w is an activation and the slice order breaks. The S1w gate must show the bindings are unreachable without the registry rows; S1b's AT-10 shows the inverse.
- `_chunked_entry.py` is at its ceiling. S1r and S1b both touch it. If S1r uses the reclaimed lines, S1b has none for step 2; the direct map must replace the special set line for line.
- A unified top_code plan with a declared column whose cast failed earlier: the snapshot is still marked post-cast, but the cast error has already sent the table to fallback, so the coordinator never runs. AT-9 covers the declared happy path; AT-15 makes the failed-cast control mandatory.
- A builder launders the mixed sweep or the Phase D audit by flipping a `native` flag or listing the new operators as compiled. AT-12 and AT-14 require literal expectations and registry-derived classification.
- The negative-control rewrite weakens a test. The reviewer diffs each rewritten test and checks its route, kernel-call and parity assertions are kept (parent P7).

## 13. Slices

| Slice | Content | Size | Risk | Starts after | Gate |
|---|---|---|---|---|---|
| S1b. Activate chunked and unified | steps 1 to 6 | 2.0 builder-days (mixed lane, audit, raw physical gate, test migrations) | R2 | S1g, S1d, S1r and CS S2a merged (so #790, S1e, S1w also merged) | AT-1 to AT-19; M1 to M15 on the final head |

Test depth: T0 per edit; T1 impact selection per commit, plus the native, physical, unified and chunked parity packages; T2 on the exact head with the mutations above. Full suite: yes, once at the gate head against the saved main baseline, because S1b edits the frozen registry snapshot tests and rewrites seven existing tests (three negative controls, the mixed sweep, the Phase D audit, two auto-chunk pins) (escalation triggers: frozen contract, changed tests).

## 14. Owner calls and open items

- Inherited, unchanged (parent section 12): keep the nullable-integer top_code auto-chunk gate and the bucketize null-count gate for V1. Defaults stand.
- Open item 1 (blocking): S1b cannot start until #790, five sibling slices and CS S2a merge (section 0).
- Follow-up (not this slice): `native/_kernels_scalar.__all__` and `_STRING_SOURCE_STRATEGIES` (`native/_real_type_admission.py:62`) are hand-written lists; the membership sets S1b relies on are already derived from the registry.
- Open item 2 (OWNER CALL). "Native fast path on every route": after S1b and S1p, bucketize and top_code are native on chunked, unified and physical, but sequential FK still runs the handler and out-of-core refuses bucketize (`execution/out_of_core/_compat.py:78`) and does not list top_code. Both need a row-error channel on those routes. Default: keep these as V2-LOG (parent section 13) and name the handler on the run card, as owner direction 2026-11-22 allows where no faster build exists.
