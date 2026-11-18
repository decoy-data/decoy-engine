Status: proposal

# Grouping proposal for `src/decoy_engine/execution/`

Owner: Cam. Date: 2026-11-18. Scope: engine only. Read-only study: no code, test or file move
is part of this document. Measured on `origin/main` at `2c869dce6` (2026-11-18). Every count
below comes from a command in Appendix A.

The handoff names `handoffs/phase1/RULES-REMOTE-2026-11-17.md` as required reading. That file
is in the vault, not in any of the four repositories this session can reach, so this proposal
follows the rules stated in the handoff itself and the engine `CLAUDE.md`.

## 1. Summary

- `execution/` holds 104 flat `.py` files: `__init__.py` and 103 modules, 30,932 lines in the
  103 modules. The layout sentry freezes this at 103 against a cap of 25
  (`tests/sentry/layout/test_package_fanout.py:25,32`); the owner rule is about 20.
- Proposal: 10 sub-packages that take 102 of the 103 flat modules plus 2 modules from the
  existing `pipeline/`. Sizes run from 5 to 18. The largest is `spine/` with 18.
- `capacity.py` stays where it is. It is the one flat module with a public name, and the CLI
  tests import it as a module and replace an attribute on it (section 6).
- After the move, `execution/` has 2 flat files (`__init__.py`, `capacity.py`), `chunked/` has
  11 direct modules and `pipeline/` has 10.
- The package graph has 13 direct two-package cycles and one three-package loop (section 4).
  9 of the 13 exist today between the flat modules and the existing sub-packages, or between
  two existing sub-packages. 4 become visible because the flat modules are split. Only one of
  those 4 is a cycle at module load: `frame` and `sequential`.
- 108 files outside the documentation pin a flat module by path or by dotted name in a string
  (section 5), plus 17 places that scan `execution/` as a directory.
- The move is 11 waves, each one pure-move PR, the largest an estimated 416 changed non-test
  lines before registry edits (section 7).

## 2. Proposed sub-packages

Names follow the layout map where it already names a target: `CODEMAP.md` "Where Things Go",
row "Pipeline spine and routes", lists `execution/chunked/`, `execution/pipeline/`,
`execution/sequential/` (target) and `execution/isolated/` (target).

| # | Sub-package | Modules | Purpose | Why these belong together |
|---|---|---|---|---|
| 1 | `contract/` | 12 | The types every route shares: adapter protocol, errors, row-error channel, sink protocol, operator registry. | No member imports another proposed sub-package at module load. Everything else imports it: 337 non-test import lines from 186 files. |
| 2 | `frame/` | 16 | Work on one resident table: the pandas adapter, its work list and guards, FK match keys, per-table transforms, source materialization. | Shared data: one in-memory frame and its `WorkNode` list. Shared callers: `_strategies`, `native`, `out_of_core` and every route. |
| 3 | `sizing/` | 5 | Price a job from its schema: peak-memory estimate and throughput calibration. | Pure functions over schema. A leaf: imports no other part of `execution/`. Read by `routing`, `spine`, `pipeline` and `out_of_core`. |
| 4 | `chunked/` (existing, 2 today) | 9 added, 11 total | The chunked mask lane: entry, oracle masker, batch input, output sink, carried columns, profile. | One stage of the pipeline, one data shape (a batch). `chunked/_progress.py` is already here. |
| 5 | `chunked/gates/` | 13 | Admission gates for the chunked lane, one per strategy, plus the six-module FK gate. | Called together by `_chunked.py` and `_chunked_oracle.py` (14 import lines). No gate imports the lane back. |
| 6 | `sequential/` | 8 | The sequential load, mask, evict route and its native operators. | One route. All 8 share the `_sequential` prefix today. |
| 7 | `unified_slice/` | 5 | The unified-slice lane: admission, evidence, resident-type gates, `when:` support. | One lane. These are the modules allowed to reach `execution/physical/` (4 of the 5 are the whole of `physical-seam-connected.json`). |
| 8 | `routing/` | 8 | Decide the route: job classification, route decisions, size signals, transform admission. | One stage: runs after resolve and before any executor. Reads `sizing`, writes the route that `spine` executes. |
| 9 | `spine/` | 18 (16 flat + 2 from `pipeline/`) | `run_pipeline` and its phases: context, route dispatch, route executors, finalize, the mixed route, the job estimate. | One call chain from the `run_pipeline` entry. `pipeline/_subset_stage.py` and `pipeline/_stream.py` import the spine back today and move with it. |
| 10 | `isolated/` | 10 | Run a job in a child process: isolated run, worker, commit, memory watch, governor, micro-probe. | Shared mechanism (a capped child that runs `run_pipeline`) and shared result contract (`_isolated_common`). |

Members:

- `contract/`: `_adapter`, `_errors`, `_events`, `_operator_registry`, `_output_projection`, `_publication_observer`, `_row_error_summary`, `_row_errors`, `_stitch`, `_technique_class`, `_transactional_sink`, `_transforms_gate`
- `frame/`: `_column_access`, `_exact_int_sources`, `_faker_degenerate_pin`, `_fk_key_compat`, `_fk_keys`, `_fk_resolve`, `_gated_string_guard`, `_guards`, `_pandas_adapter`, `_pipeline_sources`, `_positional_keys`, `_runner`, `_substrate`, `_transforms`, `_transforms_table`, `_when_gate`
- `sizing/`: `_mem_estimate`, `_mem_estimate_arrow`, `_mem_estimate_dtypes`, `_mem_estimate_schema`, `_throughput_calibration`
- `chunked/`: `_chunked`, `_chunked_adapter_gate`, `_chunked_aggregate`, `_chunked_carry`, `_chunked_input`, `_chunked_oracle`, `_chunked_output_sink`, `_chunked_preresolved`, `_chunked_profile`
- `chunked/gates/`: `_chunked_bucket_perturb`, `_chunked_categorical`, `_chunked_code_set`, `_chunked_dgrn`, `_chunked_fk`, `_chunked_fk_dtype`, `_chunked_fk_dtype_safety`, `_chunked_fk_edge_checks`, `_chunked_fk_runtime`, `_chunked_fk_vocab`, `_chunked_group_key`, `_chunked_text_mask`, `_chunked_when_guard`
- `sequential/`: `_sequential`, `_sequential_composite_chain`, `_sequential_native`, `_sequential_native_decisions`, `_sequential_native_group_key`, `_sequential_native_ops`, `_sequential_native_text_mask`, `_sequential_order`
- `unified_slice/`: `_unified_slice`, `_unified_slice_admission`, `_unified_slice_evidence`, `_unified_slice_resident_types`, `_unified_slice_when`
- `routing/`: `_pipeline_chunk_route`, `_pipeline_routing`, `_pipeline_routing_fk_dtype`, `_pipeline_routing_samples`, `_pipeline_routing_signals`, `_planner`, `_planner_columns`, `_transforms_admission`
- `spine/`: `_job_estimate`, `_mixed_admission`, `_mixed_fk_bridge`, `_mixed_static`, `_pipeline`, `_pipeline_auto_chunk`, `_pipeline_context`, `_pipeline_finalize`, `_pipeline_full_frame`, `_pipeline_generate_mask`, `_pipeline_mixed_route`, `_pipeline_multi_table`, `_pipeline_route_dispatch`, `_pipeline_route_exec`, `_residency_warning`, `_transforms_prepare`, `pipeline/_stream`, `pipeline/_subset_stage`
- `isolated/`: `_governor`, `_governor_monitor`, `_isolated_commit`, `_isolated_common`, `_isolated_memwatch`, `_isolated_reason`, `_isolated_run`, `_isolated_worker`, `_probe`, `_probe_scale`
- Stays flat: `__init__.py`, `capacity.py`

Placement choices that are not obvious from the file name:

- `_transforms_gate` goes to `contract/`: it is config-only, imports nothing from `execution/`,
  and 13 flat modules import it. `_transforms` and `_transforms_table` go to `frame/` (they run
  on a resident table and `_guards` imports `_transforms`). `_transforms_admission` goes to
  `routing/` (its docstring: "Routing-signal rules"). `_transforms_prepare` goes to `spine/`.
  A separate `transforms/` package was measured first and gave three more cycles.
- `_pipeline_sources` goes to `frame/`, not `spine/`. `pipeline/_lazy_input.py:25` and
  `pipeline/_post_scan.py:40` import it at module load; in `spine/` that is a cycle with
  `pipeline/`.
- `_probe` and `_probe_scale` go to `isolated/`: `_probe.py:55-56` imports `_isolated_common`
  and `_isolated_run` at module load, and the probe is a consumer of the isolated run.
- `_substrate` goes to `frame/`: it selects the adapter and imports `_pandas_adapter`.
- `_job_estimate` goes to `spine/`: it calls the resolve and route phases
  (`_pipeline_context`, `_pipeline_routing`).
- `_pipeline_full_frame` stays with `spine/`: it imports four spine modules at module load.

## 3. Every flat module

Columns: lines are newline counts. "Importers" are counts of files that import the module, by
where the file lives. "flat" means another flat module of `execution/`.

| Module | Lines | What it does | Importers inside `execution/` (files) | Importers outside (files) | Proposed |
|---|---|---|---|---|---|
| `_adapter` | 523 | ExecutionAdapter protocol + ExecutionResult + strategy-handler contract (S9) | flat 27, _strategies 30, native 5, out_of_core 13, physical 8, pipeline 2 | scripts 1, tests 56 | `contract/` |
| `_chunked` | 589 | Chunked mask execution (capability-gaps WS4, 2026-06-12) | flat 4, native 1, physical 1, pipeline 1 | __init__ 1, scripts 2, tests 44 | `chunked/` |
| `_chunked_adapter_gate` | 29 | Adapter-aware gating for the chunked passthrough-FK guard (DE-10 reland) | flat 1 | tests 1 | `chunked/` |
| `_chunked_aggregate` | 61 | Roll per-chunk results of the chunked mask route up into one full-frame-shaped result | flat 1 | - | `chunked/` |
| `_chunked_bucket_perturb` | 310 | bucket_perturb (explicit date_format) admission gates for chunked execution (Phase 4 slice 5) | flat 3, native 1 | tests 1 | `chunked/gates/` |
| `_chunked_carry` | 248 | Carried passthrough columns for `run_mask_chunked` (B1 revision 9) | flat 2, native 2 | tests 5 | `chunked/` |
| `_chunked_categorical` | 131 | Categorical admission gates for chunked execution (slice C1) | flat 1 | tests 2 | `chunked/gates/` |
| `_chunked_code_set` | 315 | code_set admission + corpus-pinning gates for chunked execution (Phase 4 slice 4) | flat 4 | tests 5 | `chunked/gates/` |
| `_chunked_dgrn` | 155 | DGRN admission + domain guard for chunked execution (Phase 4 slice 1) | flat 2, native 1 | tests 3 | `chunked/gates/` |
| `_chunked_fk` | 255 | FK self-masking gate for chunked execution (Option 1) | flat 3 | tests 10 | `chunked/gates/` |
| `_chunked_fk_dtype` | 246 | Runtime FK-key declared-vs-real dtype guard for chunked execution (DE-10 residual, LOW) | flat 1 | tests 1 | `chunked/gates/` |
| `_chunked_fk_dtype_safety` | 187 | Predicate 12's EXACT cross-route-safe FK-key dtype set (chunked-FK cascade-safety fix, 2026-09-02 plan) | flat 2 | tests 1 | `chunked/gates/` |
| `_chunked_fk_edge_checks` | 542 | The ordered admission checks `gate_fk_child_edges` runs on each FK edge | flat 1 | tests 1 | `chunked/gates/` |
| `_chunked_fk_runtime` | 191 | Per-chunk runtime half of the chunked FK gate: the FK column sets each chunk is checked against, and the lossy-passthrough guard | flat 1 | - | `chunked/gates/` |
| `_chunked_fk_vocab` | 163 | Shared vocabulary of the chunked FK self-masking gate | flat 2, pipeline 1 | tests 2 | `chunked/gates/` |
| `_chunked_group_key` | 365 | group_key admission + gates for chunked execution (Phase 4 slice 2) | flat 3, native 1 | tests 1 | `chunked/gates/` |
| `_chunked_input` | 504 | Batch input for the auto-chunk lane (Rust engine program slice B6b) | flat 8, native 2, physical 1, pipeline 3 | tests 11 | `chunked/` |
| `_chunked_oracle` | 594 | The pandas-oracle chunked masker, split into a preflight and a masking loop | flat 2, native 1 | tests 17 | `chunked/` |
| `_chunked_output_sink` | 600 | Incremental output sink for the auto-chunk lane (Rust engine program slice B6a) | flat 5, pipeline 1 | generation 1, tests 16 | `chunked/` |
| `_chunked_preresolved` | 116 | A pre-resolved column carried through the chunked mask lane | flat 2 | tests 1 | `chunked/` |
| `_chunked_profile` | 284 | Profile construction for `_chunked.run_mask_pipeline_chunked` | flat 3 | tests 32 | `chunked/` |
| `_chunked_text_mask` | 163 | text_mask `when` gate for chunked execution (Phase 4 slice 3) | flat 3, native 1 | tests 1 | `chunked/gates/` |
| `_chunked_when_guard` | 132 | Per-chunk type guard for a positional draw under `when:` on the chunked route (C8-iii-d-2) | flat 2, native 1 | tests 1 | `chunked/gates/` |
| `_column_access` | 530 | Which columns each pandas dispatch surface reads or writes besides its own | flat 7, native 3 | tests 7 | `frame/` |
| `_errors` | 106 | Exception hierarchy for the execution adapter (engine-v2 S9) | flat 37, _strategies 19, native 11, out_of_core 31, pipeline 5 | declared_casting 4, plan 1, unmask 1, scripts 1, tests 167 | `contract/` |
| `_events` | 19 | ExecutionEvent: a structured observation surfaced during a run (engine-v2 S9) | flat 1 | - | `contract/` |
| `_exact_int_sources` | 175 | Exact integer keys for deterministic Faker and hash over integer columns that hold nulls | flat 3, _strategies 2 | tests 2 | `frame/` |
| `_faker_degenerate_pin` | 216 | C5c-ii: pin an admitted deterministic-Faker column's degenerate output to Arrow `string` | flat 4, native 2 | tests 2 | `frame/` |
| `_fk_key_compat` | 23 | Compatibility wrapper for `_pandas_adapter.py`'s FK key normalization | flat 1 | tests 1 | `frame/` |
| `_fk_keys` | 380 | Canonical FK match keys, and the lossless FK-integer-typing contract | flat 8, native 3, out_of_core 4 | scripts 1, tests 24 | `frame/` |
| `_fk_resolve` | 215 | Parent-level FK orphan-policy resolution helpers (Task 4.6 slice 5b-ii) | flat 2, _strategies 1, out_of_core 4 | tests 2 | `frame/` |
| `_gated_string_guard` | 99 | Execution guard: a `when:`-gated write that would mix strings into a numeric column | flat 1 | tests 1 | `frame/` |
| `_governor` | 600 | Sprint B4: the RUNTIME GOVERNOR -- the last-line safety net that kills a job approaching OOM and reroutes it, so an estimator/probe miss (B1a/B2) … | flat 1 | scripts 2, tests 9 | `isolated/` |
| `_governor_monitor` | 184 | Sprint B4 runtime governor: the supervisor-side `/proc` poller | flat 1 | tests 2 | `isolated/` |
| `_guards` | 294 | Execution-time ingest guards (engine-v2 S13) | flat 11, _strategies 1, native 2, out_of_core 1, physical 1, pipeline 1 | profiling 1, tests 6 | `frame/` |
| `_isolated_commit` | 307 | Parent-side publication and result-envelope IO for the isolated-run primitive | flat 1 | tests 3 | `isolated/` |
| `_isolated_common` | 510 | Shared constants, classification, and the result contract for isolated runs | flat 7 | fileaccess 1, scripts 1, tests 17 | `isolated/` |
| `_isolated_memwatch` | 382 | Driver-side memory evidence for a capped isolated run | flat 2 | tests 2 | `isolated/` |
| `_isolated_reason` | 112 | Structured reasons for the isolated-run primitive (F29) | flat 2 | tests 1 | `isolated/` |
| `_isolated_run` | 591 | `run_pipeline_isolated`: a fresh-process wrapper around `run_pipeline` | flat 3 | scripts 1, tests 16 | `isolated/` |
| `_isolated_worker` | 233 | Worker entrypoint for an isolated `run_pipeline` invocation | - | scripts 2, tests 5 | `isolated/` |
| `_job_estimate` | 288 | Advisory job estimate: route + peak memory + runtime band (job-time-estimator Slice 2) | flat 1 | - | `spine/` |
| `_mem_estimate` | 598 | Pure, schema-derived peak-memory estimator (OOM-avoidance routing redesign, Sprint B1a -- docs/plans/2026-07-10-oom-avoidance-routing-redesign.md … | flat 4, out_of_core 1, pipeline 2 | generation 1, scripts 3, tests 17 | `sizing/` |
| `_mem_estimate_arrow` | 313 | Price a column by its Arrow type for the byte-estimate router | flat 4, pipeline 1 | tests 2 | `sizing/` |
| `_mem_estimate_dtypes` | 122 | Dtype byte-cost tables for the pure peak-memory estimator | flat 1 | - | `sizing/` |
| `_mem_estimate_schema` | 286 | Adapters: build a `TableSizeSpec` (`_mem_estimate.py`) from the engine's real schema representations -- `profile/_types.py` for mask tables, … | flat 2, pipeline 1 | tests 5 | `sizing/` |
| `_mixed_admission` | 323 | Semantic admission core for a MIXED (generate + mask) job | flat 2, physical 1 | tests 2 | `spine/` |
| `_mixed_fk_bridge` | 272 | Whole-table FK key resolution for a mask child whose parent is a GENERATE table (the one edge a coupled mixed job admits) | flat 1, physical 1 | tests 1 | `spine/` |
| `_mixed_static` | 315 | STATIC (pre-generation) admission of the production mixed route | flat 2 | tests 2 | `spine/` |
| `_operator_registry` | 294 | One frozen descriptor per native masking operator: the single home of shared per-operator facts | flat 8, native 9, out_of_core 7, physical 3, pipeline 1 | scripts 2, tests 23 | `contract/` |
| `_output_projection` | 146 | DE-03: fail-closed output projection | flat 8, native 1, out_of_core 3, physical 4 | tests 3 | `contract/` |
| `_pandas_adapter` | 694 | PandasExecutionAdapter: the first concrete ExecutionAdapter (engine-v2 S9) | flat 6, native 1, physical 1 | scripts 1, tests 40 | `frame/` |
| `_pipeline` | 360 | FC-1 (2026-06-02) unified pipeline entry: mixed mask + generate | flat 5, physical 2 | examples 2, scripts 5, testflight 1, tests 44 | `spine/` |
| `_pipeline_auto_chunk` | 568 | Auto-chunk lane executor for `run_pipeline` (Rust engine program slice B2) | flat 6 | tests 13 | `spine/` |
| `_pipeline_chunk_route` | 152 | S3 (engine-efficiencies P3) auto-chunk routing: `decide_chunk_route` + `auto_chunk_stamp`, split out of `_pipeline_routing.py` to hold the 600-LOC … | flat 1 | - | `routing/` |
| `_pipeline_context` | 582 | The resolve and route phases of `run_pipeline`, as a typed carrier | flat 6, pipeline 2 | profile 1, tests 7 | `spine/` |
| `_pipeline_finalize` | 478 | Post-mask finalize helpers for `run_pipeline`, split out to hold the 600-LOC orchestration cap (CLAUDE.md "Engineering best practices") | flat 5, physical 1 | tests 8 | `spine/` |
| `_pipeline_full_frame` | 333 | The full_frame layer-1 route executor, peer to the sequential and out-of-core executors | flat 2 | tests 2 | `spine/` |
| `_pipeline_generate_mask` | 436 | The generate + mask execution steps of `run_pipeline`, split out to hold the 645-LOC orchestration cap (CLAUDE.md "Engineering best practices", … | flat 1 | tests 2 | `spine/` |
| `_pipeline_mixed_route` | 316 | The production mixed (generate + mask) route executor | flat 1 | tests 2 | `spine/` |
| `_pipeline_multi_table` | 453 | Independent multi-table dispatch for `run_pipeline` (Rust engine program slice B7) | flat 4, pipeline 1 | tests 6 | `spine/` |
| `_pipeline_route_dispatch` | 221 | Context-driven entry points for the two bounded layer-1 routes | flat 1 | tests 3 | `spine/` |
| `_pipeline_route_exec` | 616 | Route EXECUTORS for `run_pipeline`'s routing decisions, split out from `_pipeline_routing` to hold the 600-LOC orchestration cap (CLAUDE.md … | flat 5, physical 1, pipeline 1 | scripts 1, tests 14 | `spine/` |
| `_pipeline_routing` | 566 | `run_pipeline`'s execution-route DECISIONS, split out to hold the 600-LOC orchestration cap (CLAUDE.md section "Engineering best practices") | flat 6, physical 1, pipeline 2 | tests 25 | `routing/` |
| `_pipeline_routing_fk_dtype` | 141 | Schema-aware retention signal for `decide_execution_route` | flat 2, physical 1, pipeline 1 | tests 5 | `routing/` |
| `_pipeline_routing_samples` | 56 | Per-table size specs and resident column samples for the routing estimates | flat 1 | - | `routing/` |
| `_pipeline_routing_signals` | 613 | Size + out-of-core-admission SIGNALS that feed `run_pipeline`'s route DECISIONS, split out of `_pipeline_routing` to hold the 600-LOC … | flat 4, physical 2 | tests 18 | `routing/` |
| `_pipeline_sources` | 200 | TB-1 source materialization: resolve a caller-supplied source AT THE POINT OF USE | flat 4, pipeline 2 | declared_casting 1, tests 6 | `frame/` |
| `_planner` | 589 | Execution-mode planner: classify a job; the chunked mode also routes | flat 11, physical 3 | tests 14 | `routing/` |
| `_planner_columns` | 40 | Config column lookups the auto-chunk planner reads (split out of `_planner` for its size bar) | flat 1 | - | `routing/` |
| `_positional_keys` | 64 | The dense uint64 key column for a position-keyed draw | _strategies 3, native 2 | - | `frame/` |
| `_probe` | 498 | Sprint B2: the two-point micro-probe (OOM-avoidance routing redesign, `docs/plans/2026-07-10-oom-avoidance-routing-redesign.md` §3.3, corrected … | flat 3 | scripts 1, tests 8 | `isolated/` |
| `_probe_scale` | 182 | Config/sources down-scaling helper for the B2 micro-probe (OOM-avoidance routing redesign, … | flat 1 | tests 3 | `isolated/` |
| `_publication_observer` | 202 | Publication evidence: what the engine can truthfully say about an output at each boundary | flat 3, out_of_core 1 | tests 2 | `contract/` |
| `_residency_warning` | 94 | Caller-managed residency signalling for the out-of-core route (P4-A, Option A) | flat 1 | tests 1 | `spine/` |
| `_row_error_summary` | 215 | Bounded, value-free summary of per-row masking errors (OBS-2c) | flat 2, native 1 | errors 1, tests 2 | `contract/` |
| `_row_errors` | 90 | The per-row error channel (Sprint 2 honesty pack, S5 / D7) | flat 10, _strategies 6, native 2, physical 3 | quarantine 1, tests 14 | `contract/` |
| `_runner` | 488 | Work-list construction + execution ordering for the pandas adapter (S9) | flat 14, _strategies 2, native 3, out_of_core 3, physical 4 | tests 26 | `frame/` |
| `_sequential` | 676 | Option 2 (FK-RI memory-scaling): sequential load+mask+evict execution | flat 3, physical 1 | tests 12 | `sequential/` |
| `_sequential_composite_chain` | 91 | Clean decline for REMAP through a composite foreign-key chain on the sequential (SEQ) route | flat 1 | tests 1 | `sequential/` |
| `_sequential_native` | 697 | Native routing for payload masks on the sequential (SEQ) FK route | flat 3 | tests 36 | `sequential/` |
| `_sequential_native_decisions` | 112 | Decision and evidence value types for the SEQ-native seam | flat 2 | tests 2 | `sequential/` |
| `_sequential_native_group_key` | 206 | Native group_key payload on the sequential (SEQ) FK route (B7) | flat 1, _strategies 1 | tests 1 | `sequential/` |
| `_sequential_native_ops` | 594 | The per-strategy native operators the sequential (SEQ) route can hand a column to | flat 4, _strategies 1 | tests 18 | `sequential/` |
| `_sequential_native_text_mask` | 95 | The sequential (SEQ) native operator for `text_mask` | flat 1 | tests 2 | `sequential/` |
| `_sequential_order` | 64 | FK-topological table order for the sequential route (split out of `_sequential`) | flat 1 | - | `sequential/` |
| `_stitch` | 41 | Task 4.6 slice 5b-i: the single shared owner of the generate+mask output stitch precedence -- `run_pipeline`'s former inline Step 3 … | flat 2, physical 1 | tests 2 | `contract/` |
| `_substrate` | 79 | Execution-adapter selection | flat 7, physical 1 | tests 3 | `frame/` |
| `_technique_class` | 182 | MG-1 S1 (2026-06-01): GDPR technique classification | _strategies 1 | plan 1, scripts 1, tests 3 | `contract/` |
| `_throughput_calibration` | 117 | Throughput calibration for the job-time estimator (job-time-estimator Slice 1) | flat 1 | tests 1 | `sizing/` |
| `_transactional_sink` | 598 | Transactional sink protocol and reference file-based implementation | flat 13, out_of_core 5, physical 4, pipeline 1 | scripts 2, tests 40 | `contract/` |
| `_transforms` | 399 | Per-op execution for the V2 narrow transform surface | flat 4, native 3 | profile 1, tests 14 | `frame/` |
| `_transforms_admission` | 394 | Routing-signal rules for jobs that declare per-table transforms | flat 6, physical 1 | tests 1 | `routing/` |
| `_transforms_gate` | 83 | Config-only checks for per-table transforms | flat 13, native 1, physical 2, pipeline 2 | tests 1 | `contract/` |
| `_transforms_prepare` | 97 | Prepare resident transform-bearing tables before routing | flat 2, physical 1 | - | `spine/` |
| `_transforms_table` | 178 | Arrow-table front end for per-table transforms: `apply_table_transforms` | flat 2 | __init__ 1, tests 5 | `frame/` |
| `_unified_slice` | 460 | Task 4.5: the unified-slice production lane -- the DEFAULT-ON (activated 2026-09-20; `unified_slice_enabled=True`) per-run-flag route that runs … | flat 3 | tests 27 | `unified_slice/` |
| `_unified_slice_admission` | 571 | Task 4.5 D3 (hardened, post-Codex-determination): the unified-slice admission predicate, split out of `_unified_slice.py` to hold the ~600-LOC … | flat 2 | tests 17 | `unified_slice/` |
| `_unified_slice_evidence` | 246 | Completed-execution evidence for the unified-slice lane (D7), assembled purely | flat 1 | tests 5 | `unified_slice/` |
| `_unified_slice_resident_types` | 112 | Per-strategy resident-type gates for the unified-slice admission predicate, split out of `_unified_slice_admission.py` (pure move) to hold its … | flat 1 | tests 2 | `unified_slice/` |
| `_unified_slice_when` | 98 | `when:` support for the unified full-frame route: admission and the row masks | flat 2 | tests 3 | `unified_slice/` |
| `_when_gate` | 309 | MG-3 / M3 (2026-05-31): pre-strategy `when:` predicate gate | flat 2, native 1 | tests 11 | `frame/` |
| `capacity` | 550 | `estimate_job_capacity`: the estimate-only entrypoint for the out-of-core-FK memory capacity gate (v1 CLI capacity checker, `decoy validate … | flat 2 | tests 7 | stays (public path) |

## 4. Import graph between the proposed sub-packages

Numbers are import lines (distinct file and line). The second column lists only targets that
have no module-load import; the third only targets with neither.

| From | Imports at module load (import lines) | Imports only inside functions | Type-checking only |
|---|---|---|---|
| contract | - | pipeline (existing, 10 left) (1) | sequential (1) |
| frame | contract (18), sequential (1), native (existing) (1), _strategies (existing) (4) | - | - |
| sizing | - | - | - |
| chunked | contract (11), frame (7), chunked/gates (14), native (existing) (2) | chunked/_progress (existing) (1) | spine (2) |
| chunked/gates | contract (6), _strategies (existing) (1) | frame (6), native (existing) (7) | - |
| sequential | contract (18), frame (4), pipeline (existing, 10 left) (1), native (existing) (24), out_of_core (existing) (7), _strategies (existing) (2) | - | - |
| unified_slice | contract (5), frame (4), native (existing) (4) | spine (1), physical (existing) (8) | routing (1) |
| routing | contract (5), sizing (3), chunked (1) | frame (2), chunked/gates (4), spine (1), isolated (2), native (existing) (1), out_of_core (existing) (12) | - |
| spine | contract (22), frame (13), sizing (1), chunked (11), sequential (1), unified_slice (1), routing (7), pipeline (existing, 10 left) (7), out_of_core (existing) (3) | chunked/gates (1), capacity.py (stays) (1), native (existing) (7), _strategies (existing) (1) | - |
| isolated | contract (5), frame (2), spine (2) | - | - |
| capacity.py (stays) | contract (2), routing (2), spine (2), out_of_core (existing) (2) | frame (1) | - |
| __init__.py | contract (5), frame (4), chunked (1), routing (1), spine (2), isolated (4), capacity.py (stays) (1), native (existing) (1), out_of_core (existing) (4) | - | - |
| chunked/_progress (existing) | - | - | - |
| pipeline (existing, 10 left) | contract (5), frame (3), sizing (4), chunked (1), chunked/gates (1), out_of_core (existing) (1), _strategies (existing) (1) | routing (1) | spine (3) |
| native (existing) | contract (29), frame (15), chunked (2), chunked/gates (3), chunked/_progress (existing) (1), out_of_core (existing) (1), _strategies (existing) (6) | - | - |
| out_of_core (existing) | contract (57), frame (11), sizing (1), pipeline (existing, 10 left) (2), native (existing) (22), _strategies (existing) (8) | - | - |
| physical (existing) | contract (9), frame (1), sequential (1), routing (1), spine (5), native (existing) (21), out_of_core (existing) (1) | chunked (2) | - |
| _strategies (existing) | contract (55), frame (8) | sequential (2), native (existing) (1) | - |

### 4.1 Cycles

A cycle is counted when two packages import each other. "Load" means both directions are
imports at module load. "Function" means at least one direction is only inside a function.
One strongly connected component holds 8 packages at module load: `frame`, `sequential`,
`chunked`, `chunked/gates`, `_strategies`, `native`, `out_of_core`, `pipeline`.

Cycles that the split makes visible (4):

| # | Cycle | Kind | Evidence | Fix or reason |
|---|---|---|---|---|
| 1 | `frame` and `sequential` | Load | `_pandas_adapter.py:75` imports `run_sequential`; `_sequential.py:146-159` imports `_exact_int_sources`, `_fk_keys`, `_guards`, `_runner`; `_sequential.py:193` imports `PandasExecutionAdapter` inside a function. | Fix, as a separate change before wave 4: import `run_sequential` inside the one adapter method that delegates to it. Not a pure move. Merging the two packages gives 24 modules, over the rule. |
| 2 | `capacity.py` and `spine` | Function | `capacity.py:82-83` imports `_pipeline`, `_pipeline_route_exec`; `_job_estimate.py:128` imports `capacity._resolved_config_copy` inside a function. | Fix: move `_resolved_config_copy` into a spine module. Not a pure move. |
| 3 | `routing` and `spine` | Function | 7 load imports from `spine` to `routing`; `_planner.py:217` imports `_pipeline.classify_table_kinds` inside a function. | Fix: `_planner` reads `config.classify_table_kinds`, which the `CODEMAP.md` layout map names as the one table-kind classifier. Not a pure move. |
| 4 | `spine` and `unified_slice` | Function | `_pipeline_full_frame.py:24` imports `_unified_slice`; `_unified_slice.py:168` imports `_pipeline_finalize`, `_pipeline_route_exec` inside a function. | Reason: the lane is called by the spine and stamps its result with the spine's finalize helpers. Stays lazy until the finalize helpers move below both. |

Three-package loop (1): `routing` to `isolated` to `spine` to `routing`.
`_pipeline_routing_signals.py:439` and `_transforms_admission.py:255` import `_probe` inside a
function; `_isolated_run.py:107` and `_isolated_worker.py:41` import `_pipeline`. Reason: the
probe runs a scaled-down copy of the job in a child process, so routing calls the pipeline by
design. The import stays inside a function.

Cycles that exist today and the move does not change (9):

| # | Cycle | Kind | Evidence |
|---|---|---|---|
| 5 | `frame` and `_strategies` | Load | `_pandas_adapter.py:76-79`; 8 lines back, for example `_strategies/_composite.py:20` imports `_runner`. |
| 6 | `frame` and `native` | Load | `_faker_degenerate_pin.py:31`; 15 lines back, for example `native/_chunk_masking.py:24` imports `_runner`. |
| 7 | `chunked` and `native` | Load | `_chunked.py:193`, `_chunked_output_sink.py:43`; `native/_chunked_entry.py:35,40`. |
| 8 | `native` and `out_of_core` | Load | `native/_pool_quality.py:41`; 22 lines back, for example `out_of_core/_compat.py:18-19`. |
| 9 | `out_of_core` and `pipeline` | Load | `out_of_core/_budget.py:127`, `out_of_core/_duckdb.py:15`; `pipeline/_post_scan.py:42`. |
| 10 | `contract` and `pipeline` | Function | `_publication_observer.py:139` imports `pipeline._post_scan` inside a function; 5 lines back. |
| 11 | `sequential` and `_strategies` | Function | `_sequential_native.py:100-101`; `_strategies/_fpe.py:185`, `_strategies/_group_key.py:78` inside functions. |
| 12 | `chunked/gates` and `native` | Function | `native/_chunked_entry.py:36-38`; 7 lines back inside functions. |
| 13 | `_strategies` and `native` | Function | 6 load lines from `native`; `_strategies/_fpe.py:186` inside a function. |

One cycle that exists today is removed by the proposal: `pipeline` and the spine modules
(`pipeline/_subset_stage.py:25` imports `_pipeline_route_exec`; `_pipeline.py:89` imports
`pipeline._subset_stage`). Moving `_subset_stage` and `_stream` into `spine/` and
`_pipeline_sources` into `frame/` leaves only type-checking imports from `pipeline` to `spine`.

## 5. Path-pinned checks a move would touch

108 files outside `docs/` name a flat module by path (`execution/_x.py`) or by dotted name
inside a string. Import statements are not in this list; section 7 counts those. "Lines" is the
number of lines in the file with at least one such reference. Long line lists are cut after
eight ranges and give the count and span; Appendix A regenerates the full list.

The ones the handoff names:

- Module-size census: `tests/sentry/baselines/module-size.json:38,41,44,47,50` (5 flat modules)
  and `tests/sentry/test_module_size.py:95,99,122,130,133`.
- Physical-seam allowlist: `tests/sentry/baselines/physical-seam-connected.json:5,8,11,14` and
  129 lines of `tests/sentry/test_physical_seam_disconnection.py` (67 to 1009).
- File-access registry: 17 lines of `tests/sentry/file_access_registry.toml` (39 to 1764),
  `tests/sentry/file_access_modules.toml:42,44-45,53`, `tests/sentry/fa/rules.py:360-362,381`.
- Import-linter: `.importlinter:26-30,33-34,36-37,43,46-48,52` (14 ignore lines; each must name
  a leaf module, so each changes), `tests/sentry/baselines/import-layers.json` (14 keys),
  `tests/sentry/layout/test_import_layers.py:192,221`. There are no import-linter contracts in
  `pyproject.toml`; it holds the `layers` extra only (`pyproject.toml:207`).
- `pyproject.toml:758-762,781-791`: 16 mypy override module names. A moved module silently
  drops out of its stricter override unless the name changes with it. `pyproject.toml:89` is a
  comment.
- `CODEMAP.md`: 40 lines (24 to 287), including the "Where Things Go" row and its
  "fan-out freeze at 104" cell. `tests/sentry/test_package_map_paths.py` fails if a row names a
  path that does not exist.
- Fan-out freeze: `tests/sentry/layout/test_package_fanout.py:32` and
  `tests/sentry/baselines/package-fanout.json:9-12`. The entry is deleted when the flat count
  falls to 25 or lower.


**Contracts and maps** (3 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `.importlinter` | 14 | 26-30, 33-34, 36-37, 43, 46-48, 52 | chunked, contract, frame, isolated, sizing, spine |
| `CODEMAP.md` | 40 | 24, 29, 32-34, 36-39, 41-48, 50-52, 79, 101-104, 107, 110, 112-113, 123, 208-211, 214-218, 287 | chunked, chunked_gates, contract, frame, routing, sequential, spine, unified_slice |
| `pyproject.toml` | 17 | 89, 758-762, 781-791 | contract, frame, isolated, routing, sizing |

**Sentry baselines and registries** (14 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `tests/sentry/baselines/exception-context.json` | 2 | 53, 56 | isolated, sequential |
| `tests/sentry/baselines/f29-consumer-inventory.json` | 10 | 8, 11, 14, 17, 20, 23, 26, 29, 41, 44 | capacity, chunked_gates, isolated, routing, sequential, spine, unified_slice |
| `tests/sentry/baselines/f29-producer-inventory.json` | 157 | 116, 119, 122, 125, 128, 131, 134, 137, … 157 lines in 116..791 | capacity, chunked, chunked_gates, contract, frame, isolated, routing, sequential, spine, unified_slice |
| `tests/sentry/baselines/gcs-call-kwargs.json` | 28 | 50, 53, 56, 59, 62, 65, 68, 71, … 28 lines in 50..138 | chunked, chunked_gates, contract, frame, isolated, routing, sequential, spine |
| `tests/sentry/baselines/import-layers.json` | 14 | 8, 11, 14, 17, 20, 29, 32, 38, 41, 59, 68, 71, 74, 86 | chunked, contract, frame, isolated, sizing, spine |
| `tests/sentry/baselines/module-size.json` | 5 | 38, 41, 44, 47, 50 | frame, routing, sequential, spine |
| `tests/sentry/baselines/physical-seam-connected.json` | 4 | 5, 8, 11, 14 | unified_slice |
| `tests/sentry/baselines/post-scan-commit.json` | 1 | 5 | sequential |
| `tests/sentry/baselines/post-scan-route-exempt.json` | 8 | 5, 8, 11, 14, 17, 20, 23, 26 | chunked, frame, isolated, routing, spine |
| `tests/sentry/baselines/secret-material-census.json` | 14 | 49, 52, 55, 58, 61, 64, 67, 70, 73, 76, 79, 82, 85, 88 | chunked, contract, sequential |
| `tests/sentry/baselines/table-kind-truth-tests.json` | 4 | 17, 21, 25, 29 | chunked, contract, frame, isolated |
| `tests/sentry/file_access_modules.toml` | 4 | 42, 44-45, 53 | isolated |
| `tests/sentry/file_access_registry.toml` | 17 | 39, 48, 58, 68, 77, 87, 96, 106, 116, 126, 136, 145, 155, 164, 1359, 1754, 1764 | chunked_gates, contract, isolated, spine |
| `tests/sentry/secret_material_census.json` | 14 | 140, 149, 158, 167, 176, 185, 194, 203, 212, 221, 230, 239, 248, 257 | chunked, contract, sequential |

**Sentry tests and helpers** (22 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `tests/sentry/_reason_baseline.py` | 1 | 119 | sequential |
| `tests/sentry/defects/test_anchored_regex.py` | 4 | 132, 134, 139, 143 | chunked_gates |
| `tests/sentry/defects/test_environment_reads.py` | 1 | 33 | isolated |
| `tests/sentry/defects/test_validation_sites.py` | 1 | 50 | frame |
| `tests/sentry/fa/rules.py` | 4 | 360-362, 381 | isolated |
| `tests/sentry/layout/test_import_layers.py` | 2 | 192, 221 | contract, spine |
| `tests/sentry/layout/test_package_fanout.py` | 3 | 193, 199-200 | contract |
| `tests/sentry/post_scan/_scan.py` | 3 | 264-265, 331 | contract, spine |
| `tests/sentry/post_scan/test_post_scan_choke_points.py` | 7 | 201, 242, 249, 252, 299-301 | isolated, sequential, spine |
| `tests/sentry/protected_dir/test_protected_dir.py` | 1 | 133 | isolated |
| `tests/sentry/source_config/test_declaration_gate.py` | 7 | 53, 57, 75, 226, 264, 323, 405 | chunked, frame, isolated |
| `tests/sentry/test_exception_hierarchy.py` | 4 | 30-33 | contract, frame, isolated |
| `tests/sentry/test_f06_declared_casting.py` | 22 | 23-32, 40-41, 48, 53, 58, 62, 64, 76-79, 86 | chunked, routing, sequential, spine, unified_slice |
| `tests/sentry/test_file_access_boundary.py` | 1 | 376 | isolated |
| `tests/sentry/test_module_size.py` | 5 | 95, 99, 122, 130, 133 | frame, routing, sequential, spine |
| `tests/sentry/test_operator_registry_sentry.py` | 1 | 96 | unified_slice |
| `tests/sentry/test_pandas_eval_sites.py` | 8 | 25, 27, 91-92, 94, 96, 100, 124 | frame |
| `tests/sentry/test_physical_seam_disconnection.py` | 129 | 67, 71-74, 77-79, 83-87, 90, 93, 106, 109-115, … 129 lines in 67..1009 | capacity, chunked, chunked_gates, contract, frame, isolated, routing, sequential, sizing, spine, unified_slice |
| `tests/sentry/test_post_scan_route_guard.py` | 10 | 42, 44, 49, 52-58 | chunked, frame, isolated, routing, sequential, spine |
| `tests/sentry/test_reason_registry.py` | 17 | 55-56, 89-91, 122, 133, 138-140, 154, 178, 215-217, 707, 853 | chunked_gates, contract, frame, spine |
| `tests/sentry/test_table_kind_classifier.py` | 4 | 30-33 | chunked, contract, frame, isolated, spine |
| `tests/sentry/test_vault_writer_routes.py` | 5 | 29, 45, 203, 206, 214 | chunked, contract, spine |

**Frozen fixtures** (5 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `tests/fixtures/f29/producer-inventory.json` | 193 | 46-185, 257-294, 1394-1402, 1407-1412 | capacity, chunked, chunked_gates, contract, frame, isolated, routing, sequential, spine, unified_slice |
| `tests/fixtures/f29/reason-baseline.json` | 134 | 130, 133, 154-187, 224, 292, 310, 336, 446-447, … 134 lines in 130..844 | capacity, chunked, chunked_gates, contract, frame, isolated, routing, sequential, spine, unified_slice |
| `tests/fixtures/f29/reason-manifest-v1.27-release-0-25-0.json` | 1 | 149 | routing |
| `tests/fixtures/f29/reason-manifest-v1.4-f06.json` | 1 | 295 | chunked |
| `tests/fixtures/f29/reason-manifest-v1.json` | 31 | 246, 332, 472-473, 481, 507, 509-510, 513-514, 519-520, 529, 536-539, 542, 545-551, 554-555, 557, 614, 660, 819 | chunked, frame, isolated, routing, sequential, spine |

**Other tests (string and path references)** (47 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `tests/fileaccess/test_policy_strace.py` | 1 | 21 | contract |
| `tests/integration/test_f29_failure_contract.py` | 1 | 126 | contract |
| `tests/integration/test_f29_publication_state.py` | 2 | 81, 129 | contract, sequential |
| `tests/native/test_c1b_i_metadata_inventory.py` | 1 | 257 | spine |
| `tests/native/test_c5b_i_metadata_inventory.py` | 1 | 209 | chunked |
| `tests/native/test_draw_site_inventory_coverage.py` | 4 | 239-242 | chunked, chunked_gates, spine |
| `tests/native/test_unconfigured_passthrough.py` | 1 | 172 | contract |
| `tests/parity/SEMANTIC_DIFFERENCES.md` | 1 | 51 | frame |
| `tests/parity/native/_fixtures.py` | 1 | 111 | chunked |
| `tests/physical/test_compiler_preflight_equivalence.py` | 3 | 72, 76, 80 | spine |
| `tests/physical/test_lossless_forwarding.py` | 1 | 120 | chunked |
| `tests/physical/test_shadow_mixed_fk.py` | 2 | 695-696 | contract, frame |
| `tests/physical/test_unified_slice_exception_boundary.py` | 1 | 33 | unified_slice |
| `tests/physical/test_unified_slice_faker.py` | 1 | 724 | unified_slice |
| `tests/unit/execution/_auto_chunk_support.py` | 1 | 312 | spine |
| `tests/unit/execution/_b6a_support.py` | 1 | 28 | chunked |
| `tests/unit/execution/_b6b_support.py` | 1 | 31 | chunked |
| `tests/unit/execution/_multi_table_support.py` | 1 | 36 | spine |
| `tests/unit/execution/_r3_scenarios.py` | 2 | 852, 872 | spine |
| `tests/unit/execution/post_scan/test_integrity_refusals.py` | 1 | 84 | contract |
| `tests/unit/execution/post_scan/test_isolated_blocked.py` | 4 | 44, 65, 163, 186 | isolated |
| `tests/unit/execution/post_scan/test_staged_gate.py` | 1 | 40 | contract |
| `tests/unit/execution/publication/_isolated_support.py` | 1 | 96 | isolated |
| `tests/unit/execution/publication/test_sink_transition_cells.py` | 2 | 315, 329 | contract |
| `tests/unit/execution/r3_failure_trace_baseline.json` | 39 | 80, 92, 98, 104, 110, 116, 122, 128, … 39 lines in 80..445 | contract, unified_slice |
| `tests/unit/execution/test_auto_chunk_bookkeeping.py` | 6 | 27, 30, 33, 37, 85, 88 | spine |
| `tests/unit/execution/test_b6a_bookkeeping.py` | 2 | 25, 28 | spine |
| `tests/unit/execution/test_b6b_bookkeeping.py` | 2 | 30, 33 | spine |
| `tests/unit/execution/test_draw_identity.py` | 1 | 26 | contract |
| `tests/unit/execution/test_engine_transforms_admission.py` | 3 | 618, 639, 796 | sizing |
| `tests/unit/execution/test_expression_log_redaction.py` | 2 | 36, 51 | frame |
| `tests/unit/execution/test_group_key_chunked.py` | 3 | 493, 571, 624 | chunked |
| `tests/unit/execution/test_isolated_memwatch_run.py` | 4 | 38, 188, 312, 413 | isolated |
| `tests/unit/execution/test_isolated_run.py` | 3 | 63, 95, 835 | isolated, spine |
| `tests/unit/execution/test_isolated_run_env_flag.py` | 3 | 32, 44, 73 | isolated |
| `tests/unit/execution/test_isolated_safe_error.py` | 2 | 171, 203 | contract |
| `tests/unit/execution/test_mem_estimate_arrow_types.py` | 1 | 56 | sizing |
| `tests/unit/execution/test_multi_table_run.py` | 2 | 553, 558 | spine |
| `tests/unit/execution/test_probe_routing.py` | 15 | 225, 242, 259, 274, 292, 319, 340, 366, 411, 429, 555, 586, 606, 627, 666 | isolated |
| `tests/unit/execution/test_scanml_m5_route_guard.py` | 2 | 134-135 | chunked |
| `tests/unit/execution/test_subset_run_entry_policy.py` | 1 | 41 | chunked |
| `tests/unit/profile/test_declaration_gate.py` | 1 | 569 | chunked |
| `tests/unit/profile/test_lazy_csv.py` | 1 | 334 | contract |
| `tests/unit/quality/test_carriers.py` | 1 | 1219 | contract |
| `tests/unit/quality/test_tq_mutate_gates.py` | 1 | 58 | sequential |
| `tests/unit/test_fk_memory_probe_classifier.py` | 1 | 104 | contract |
| `tests/unit/test_v2_transforms.py` | 2 | 515, 526 | frame |

**Scripts** (4 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `scripts/audit/stage2b_phase1_streaming.py` | 1 | 147 | chunked |
| `scripts/bench-unified-slice/README.md` | 1 | 142 | unified_slice |
| `scripts/dev/ooc_fk_seam_mutants.py` | 2 | 35-36 | frame, routing |
| `scripts/fk-scale/bench_worker_mixed.py` | 1 | 91 | spine |

**Runtime strings in src** (13 files)

| File | Lines | Line numbers | Sub-packages named |
|---|---|---|---|
| `src/decoy_engine/_execution_error.py` | 1 | 25 | contract |
| `src/decoy_engine/config/_post_scan.py` | 2 | 177-178 | contract, isolated |
| `src/decoy_engine/execution/_isolated_run.py` | 1 | 118 | isolated |
| `src/decoy_engine/execution/_isolated_worker.py` | 1 | 206 | isolated |
| `src/decoy_engine/fileaccess/__init__.py` | 8 | 77-84 | capacity, chunked, frame, isolated, sequential, spine |
| `src/decoy_engine/reason_adapter.py` | 8 | 53-55, 64, 67, 78-79, 119 | contract, frame, isolated, spine, unified_slice |
| `src/decoy_engine/reasons/plan/_part3.py` | 1 | 85 | frame |
| `src/decoy_engine/reasons/route/_added.py` | 1 | 20 | routing |
| `src/decoy_engine/reasons/route/_f06.py` | 1 | 50 | chunked |
| `src/decoy_engine/reasons/route/_part1.py` | 4 | 147, 152, 156, 168 | chunked, sequential, spine |
| `src/decoy_engine/reasons/route/_retired.py` | 1 | 14 | routing |
| `src/decoy_engine/reasons/route/_sink.py` | 1 | 20 | chunked |
| `src/decoy_engine/reasons/runtime/_part3.py` | 2 | 317, 342 | frame, isolated |

Places that read `execution/` as a directory (17). A recursive scan keeps working. The rest
build a path from a flat file name or count direct children:

| File and line | How it reads | Effect of a move |
|---|---|---|
| `tests/sentry/layout/test_package_fanout.py:32` | counts direct modules | entry shrinks, then goes |
| `tests/sentry/baselines/package-fanout.json:9` | same count | same |
| `tests/sentry/test_post_scan_route_guard.py:197-198` | `EXECUTION.glob("_pipeline*.py")`, not recursive | finds nothing after wave 8 |
| `tests/sentry/test_post_scan_route_guard.py:83` | `rglob` | none |
| `tests/sentry/test_operator_registry_sentry.py:14` | `EXEC_ROOT / "_operator_registry.py"` | path changes |
| `tests/sentry/test_operator_registry_sentry.py:61` | `rglob` | none |
| `tests/native/test_r1b_resolver_single_source.py:16,59` | `ENGINE / module` | path changes |
| `tests/unit/execution/test_auto_chunk_bookkeeping.py:21,31-38,102,115` | `EXEC / "<flat name>"` | paths change |
| `tests/unit/execution/test_b6a_bookkeeping.py:18,29-36,83-85` | same | same |
| `tests/unit/execution/test_b6b_bookkeeping.py:20,25-39,101-103` | same | same |
| `tests/sentry/test_physical_seam_disconnection.py:325` | `git diff -- src/decoy_engine/execution` | none |
| `tests/sentry/test_cdf_threshold_ratchet.py:22,73` | `rglob`, reports paths relative to `execution/` | reported paths change |
| `tests/sentry/source_config/test_declaration_gate.py:350` | `rglob` | none |
| `tests/sentry/test_f06_declared_casting.py:132` | `rglob` | none |
| `tests/native/test_c1b_i_metadata_inventory.py:143,167` | `rglob` | none |
| `tests/native/test_c5b_i_metadata_inventory.py:136,158` | `rglob` | none |
| `tests/unit/run_result/test_build.py:381` | `rglob` | none |

`.github/` and `ci/` name no flat module. `.semgrep/f13-secret-providers.yml:69` names the
directory `/src/decoy_engine/execution/` as a whole and keeps working.

Four references need a decision, not an edit (section 8):

- `src/decoy_engine/_execution_error.py:25` sets
  `ExecutionError.__module__ = "decoy_engine.execution._errors"`.
- `src/decoy_engine/execution/_isolated_run.py:118` holds the worker module name passed to
  `python -m`; `_isolated_worker.py:206` prints it in the usage line.
- The reason catalogs name owning modules as strings (`reasons/route/_part1.py:147,152,156,168`
  and 7 more lines in `reasons/`), and three frozen manifests under `tests/fixtures/f29/` carry
  them as `"owner"` (31 lines in `reason-manifest-v1.json`, 1 each in v1.4 and v1.27).
- `tests/fixtures/f29/producer-inventory.json` (193 lines) and `reason-baseline.json`
  (134 lines) record `"file": "execution/_x.py"` per producer.

## 6. Public import surface

Names imported from `decoy_engine.execution` or below, outside the engine's own `src/`. The
sub-packages that do not move (`_strategies`, `out_of_core`, `native`, `physical`) are left out.

| Import path | Name | Used by | After the move |
|---|---|---|---|
| `decoy_engine.execution` | `ExecutionError` | CLI `src/decoy/cli/run/_errors.py:147`, `tokenize.py:235`, `unmask.py:186`, and 9 places in CLI tests | re-exported by `execution/__init__.py`; no change |
| `decoy_engine.execution` | `check_chunked_compatibility` | CLI `src/decoy/cli/run/_execute.py:214` | same |
| `decoy_engine.execution` | `estimate_job_capacity` (read as an attribute of the package, and replaced with `setattr` or `patch.object` at 14 places in CLI tests) | CLI `src/decoy/cli/preflight.py:380,421`; CLI `tests/e2e/` | same; the name must stay bound on the package |
| `decoy_engine.execution.capacity` | the module, and its attribute `decide_execution_route`, which two CLI tests replace | CLI `tests/e2e/test_preflight_capacity.py:142-151`, `test_run_preflight_capacity_parity.py:136-151` | `capacity.py` does not move. A re-export shim would not work: the test replaces the name in the module that `estimate_job_capacity` reads it from. |
| `decoy_engine.execution._isolated_commit` | `CommitError` | CLI `tests/e2e/test_run_reason_envelope.py:71` | private path; the CLI test changes with wave 5, or `CommitError` gains a public export first |
| `decoy_engine.execution._pipeline` | `run_pipeline` | engine `examples/ner_redaction_demo.py:28`, `examples/runnable_demo.py:20`, `testflight/_runner.py:213` | switch to `from decoy_engine.execution import run_pipeline` in wave 8 |
| `decoy_engine.execution._adapter` | `StrategyContext` | engine `tests/unit/test_public_api.py:435,532` | `StrategyContext` is already in `execution.__all__`; switch the test in wave 11 |
| `decoy_engine.execution._row_errors.RowErrorRecord` | string | engine `docs/conf.py:298` (Sphinx nitpick entry) | string changes in wave 10 |

The 51 names in `execution.__all__` stay. The 18 import statements that bring them in from
flat modules (`execution/__init__.py:68-113`, one of them from `capacity`) are rewritten wave
by wave. The engine root
facade imports two flat modules directly (`src/decoy_engine/__init__.py:127,129`:
`_chunked.run_mask_pipeline_chunked`, `_transforms_table.apply_table_transforms`); those are
rewritten in waves 7 and 9. The CLI's `execution._strategies.SCALAR_HANDLERS` imports are
untouched.

Engine docs outside `docs/plans`, `docs/records`, `docs/archive` and `docs/quality` contain no
`decoy_engine.execution._x` import in an example.

## 7. Move order

Pre-GA is hard delete, so no shim modules are left behind: every importer is rewritten in the
same PR and the public names keep working through `execution/__init__.py`. Each wave is one
`scripts/check_pure_move.py` manifest. "Non-test lines" is twice the number of non-test import
lines that name a moved module (one removed, one added), which is the bulk of the non-test
diff; renames with unchanged content add none. Config and registry lines come on top; section 5
gives the line count per file.

Order is by blast radius: fewest importers and pins first, the two packages everything imports
last.

| Sub-package | Modules | LOC | Import sites, non-test (files) | Import sites, tests (files) | Other files naming a member (config, baselines, registries) |
|---|---|---|---|---|---|
| `contract/` | 12 | 2499 | 337 (186) | 360 (272) | 13 |
| `frame/` | 16 | 4343 | 144 (88) | 177 (120) | 13 |
| `sizing/` | 5 | 1436 | 25 (13) | 37 (18) | 3 |
| `chunked/` | 9 | 3025 | 52 (26) | 155 (95) | 13 |
| `chunked/gates/` | 13 | 3155 | 34 (12) | 34 (24) | 7 |
| `sequential/` | 8 | 2535 | 20 (12) | 86 (49) | 12 |
| `unified_slice/` | 5 | 1487 | 9 (5) | 62 (33) | 8 |
| `routing/` | 8 | 2551 | 51 (26) | 83 (47) | 11 |
| `spine/` | 18 | 6285 | 77 (40) | 129 (92) | 12 |
| `isolated/` | 10 | 3599 | 29 (16) | 80 (44) | 14 |

| Wave | Moves | Modules | Non-test import lines | Estimated non-test changed lines | Notes |
|---|---|---|---|---|---|
| 1 | `sizing/` | 5 | 25 | 50 | Leaf. 2 mypy override names, 1 import-linter ignore. |
| 2 | `unified_slice/` | 5 | 9 | 18 | Whole physical-seam baseline changes (4 keys) plus the sentry's path table. |
| 3 | `chunked/gates/` | 13 | 34 | 68 | New nested package under the existing `chunked/`. |
| 4 | `sequential/` | 8 | 20 | 40 | Needs cycle 1 fixed first. 2 module-size census keys. |
| 5 | `isolated/` | 10 | 29 | 58 | Worker module string, 8 mypy override names, 1 import-linter ignore, CLI test import of `CommitError`. |
| 6 | `routing/` | 8 | 51 | 102 | 1 module-size key, 1 mypy override name. |
| 7 | `chunked/` | 9 | 52 | 104 | 155 test import lines. Root facade import. 1 import-linter ignore. |
| 8 | `spine/` | 18 | 77 | 154 | Includes the 2 `pipeline/` modules. `test_post_scan_route_guard.py:197` glob. Examples and testflight. 1 module-size key, 1 import-linter ignore. |
| 9 | `frame/` | 16 | 144 | 288 | 1 module-size key, 2 mypy override names, 3 import-linter ignores. |
| 10 | `contract/` without `_errors`, `_adapter` | 10 | 129 | 258 | `docs/conf.py:298`. 1 mypy override name, 2 import-linter ignores. |
| 11 | `_errors`, `_adapter` into `contract/` | 2 | 208 at most | 416 at most | 199 + 60 test import lines. `ExecutionError.__module__`. 2 mypy override names, 5 import-linter ignores. |

All 11 estimates are under 800. The waves are independent pure moves, so the order is by risk
only. Each wave also rewrites import lines inside
the modules moved by earlier waves, so a wave is rebased on `main` just before it opens.

Not attempted here: `tests/unit/execution/` holds 267 test files (231 directly in the folder).
The layout map says unit tests mirror `src/`; mirroring is a separate set of test-only moves.

## 8. Open questions for the owner

1. Do module names inside strings count as frozen? `ExecutionError.__module__` is pinned to
   `decoy_engine.execution._errors`, reason catalogs carry owner module names, and three frozen
   reason manifests record them. Either these strings stay as stable identifiers that no longer
   match a real module, or they change and the frozen manifests need a new version.
2. Top level or nested? This proposal puts `spine/` and `routing/` directly under
   `execution/`. The layout map points new route clusters at `execution/pipeline/`. Nesting
   them there keeps the map as written but puts 36 modules under `pipeline/` in three folders
   and hides the `pipeline` and spine cycle instead of removing it. Related: may the move take
   `_subset_stage.py` and `_stream.py` out of `pipeline/`?
3. Cycle 1 (`frame` and `sequential`) needs one import moved inside a function, which is a code
   change and cannot ride in a pure-move PR. Approve it as its own small PR before wave 4, or
   accept the cycle with the reason on record?
4. Which cap applies, 20 (owner rule) or 25 (`test_package_fanout.py` `LIMIT`)? At 25 `frame/`
   and `sequential/` could merge and cycle 1 disappears.
5. `capacity.py` stays flat because CLI tests patch it by module path. Is that acceptable, or
   should the CLI tests patch through a public seam so it can join `spine/`?
6. `CommitError` is imported by a CLI test from a private module. Export it from
   `decoy_engine.execution`, or let the CLI test follow the move?
7. The existing sub-packages are over the rule too (`native` 63, `out_of_core` 45,
   `_strategies` 32, `physical` 31, counted with their nested folders) and hold 5 of the 13
   cycles. Same review, or a later one?
8. Should `tests/unit/execution/` (267 files) be regrouped to mirror the new folders in the
   same waves, or after?

## Appendix A. Commands

All run from the engine repository root against `origin/main` (`2c869dce6`).

Counts:

```bash
git ls-tree --name-only origin/main src/decoy_engine/execution/ | grep -c '\.py$'   # 104
for d in _strategies chunked native out_of_core physical pipeline; do
  git ls-tree -r --name-only origin/main src/decoy_engine/execution/$d/ | grep -c '\.py$'
done                                                                                # 32 2 63 45 31 12
git ls-tree --name-only origin/main src/decoy_engine/execution/pipeline/ | grep -c '\.py$'  # 12
git ls-tree -r --name-only origin/main tests/unit/execution | grep -c 'test_.*\.py$'  # 267
git ls-tree --name-only origin/main tests/unit/execution/ | grep -c 'test_.*\.py$'    # 231
```

Directory scans (section 5):

```bash
git grep -n -E '(/ ?"execution"|"execution" ?/|decoy_engine/execution"|execution"\)?\.(glob|rglob|iterdir))' \
  origin/main -- tests scripts .github .semgrep ci
```

CLI surface patch targets (section 6), run in the CLI repository:

```bash
git grep -n -E '(setattr|patch\.object)\((engine_exec|engine_execution|capacity_mod),' origin/main
```

Import graph (sections 3, 4, 7). `graph.py` parses every `.py` file on `origin/main` with
`ast`, resolves relative imports, marks an import as "in function" when it sits inside a
`def`, and as type-checking when it sits under `if TYPE_CHECKING:`. It records line counts
(`text.count("\n")`) and the first docstring paragraph per flat module.

```python
"""Import graph for decoy_engine.execution flat modules. Run from the engine repo root."""
import ast, json, subprocess, sys
from collections import defaultdict
from pathlib import Path

REV = "origin/main"
PKG = "decoy_engine.execution"
def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
files = [f for f in git("ls-tree", "-r", "--name-only", REV).splitlines() if f.endswith(".py")]
def modname(p):
    p = p.removeprefix("src/").removesuffix(".py")
    if p.endswith("/__init__"): p = p[: -len("/__init__")]
    return p.replace("/", ".")
src = {}
for f in files:
    if f.startswith(("src/", "tests/", "scripts/", "examples/", "testflight/", "ci/", "docs/", "custom_providers/")):
        src[f] = git("show", f"{REV}:{f}")
known = {modname(f) for f in src if f.startswith("src/")}
flat = sorted(f for f in src if f.startswith("src/decoy_engine/execution/") and f.count("/") == 3)
flatmods = {modname(f): f for f in flat}

def targets(path, tree):
    """Yield (absolute module, imported name or None, lineno, lazy?, type_checking?)."""
    is_pkg = path.endswith("__init__.py")
    parts = modname(path).split(".")
    base = parts if is_pkg else parts[:-1]
    def walk(node, lazy, tc):
        for ch in ast.iter_child_nodes(node):
            l2, t2 = lazy, tc
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)): l2 = True
            if isinstance(ch, ast.If) and "TYPE_CHECKING" in ast.dump(ch.test): 
                for b in ch.body: yield from walk_stmt(b, l2, True)
                for b in ch.orelse: yield from walk_stmt(b, l2, t2)
                continue
            yield from walk_stmt(ch, l2, t2)
    def walk_stmt(ch, lazy, tc):
        if isinstance(ch, ast.Import):
            for a in ch.names: yield (a.name, None, ch.lineno, lazy, tc)
        elif isinstance(ch, ast.ImportFrom):
            if ch.level:
                b = base[: len(base) - ch.level + 1]
                m = ".".join([*b, *( [ch.module] if ch.module else [])])
            else: m = ch.module or ""
            for a in ch.names: yield (m, a.name, ch.lineno, lazy, tc)
        else:
            yield from walk(ch, lazy or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)), tc)
    yield from walk(tree, False, False)

edges = []  # (importer path, target module, name, lineno, lazy, tc)
for path, text in src.items():
    try: tree = ast.parse(text)
    except SyntaxError as e: print("SYNTAX", path, e, file=sys.stderr); continue
    for m, n, ln, lazy, tc in targets(path, tree):
        if not m.startswith(PKG): 
            if not (path.startswith("src/decoy_engine/execution/")): continue
        # resolve "from pkg import submodule"
        full = f"{m}.{n}" if n and f"{m}.{n}" in known else m
        edges.append((path, full, n if full == m else None, ln, lazy, tc))
info = {}
for mod, f in flatmods.items():
    text = src[f]; tree = ast.parse(text)
    doc = (ast.get_docstring(tree) or "").strip().split("\n\n")[0].replace("\n", " ")
    info[mod] = {"path": f, "lines": text.count("\n"), "doc": doc}
json.dump({"edges": edges, "info": info, "known": sorted(known)}, open(sys.argv[1], "w"))
print(len(flat), "flat files;", len(edges), "edges")
```

`grp.py` takes the grouping (Appendix B) and prints the package edges, the strongly connected
components (Tarjan) and the two-package cycles:

```python
import json, sys
from collections import defaultdict
d = json.load(open("graph.json")); info = d["info"]; P = "decoy_engine.execution"
G = json.load(open(sys.argv[1])); verbose = len(sys.argv) > 2
g_of = {}
for g, ms in G.items():
    for m in ms:
        assert f"{P}.{m}" in info or "." in m, m
        assert m not in g_of, m
        g_of[m] = g
missing = [m.split(".")[-1] for m in info if m != P and m.split(".")[-1] not in g_of]
print("unassigned:", missing); print({g: len(v) for g, v in G.items()}, sum(len(v) for v in G.values()))
def node(path=None, mod=None):
    if path:
        if not path.startswith("src/decoy_engine/execution/"): return None
        rest = path[len("src/decoy_engine/execution/"):-3]
        if rest.replace("/", ".") in g_of: return g_of[rest.replace("/", ".")]
        if "/" in rest: return "[" + rest.split("/")[0] + "]"
        return "[init]" if rest == "__init__" else g_of.get(rest, "[" + rest + "]")
    if not mod.startswith(P): return None
    rest = mod[len(P)+1:]
    if not rest: return "[init]"
    if rest in g_of: return g_of[rest]
    head = rest.split(".")[0]
    return g_of.get(head, "[" + head + "]")
E = defaultdict(lambda: defaultdict(list))   # kind -> (a,b) -> [(path, tgt, ln)]
for path, tgt, name, ln, lazy, tc in d["edges"]:
    a, b = node(path=path), node(mod=tgt)
    if not a or not b or a == b: continue
    kind = "tc" if tc else ("lazy" if lazy else "eager")
    E[kind][(a, b)].append((path.split("/execution/")[1], tgt[len(P)+1:], ln))
def scc(edges):
    nodes = sorted({x for e in edges for x in e}); adj = defaultdict(set)
    for a, b in edges: adj[a].add(b)
    idx, low, st, on, out, c = {}, {}, [], set(), [], [0]
    sys.setrecursionlimit(10000)
    def v(n):
        idx[n] = low[n] = c[0]; c[0] += 1; st.append(n); on.add(n)
        for m in adj[n]:
            if m not in idx: v(m); low[n] = min(low[n], low[m])
            elif m in on: low[n] = min(low[n], idx[m])
        if low[n] == idx[n]:
            comp = []
            while True:
                m = st.pop(); on.discard(m); comp.append(m)
                if m == n: break
            if len(comp) > 1: out.append(sorted(comp))
    for n in nodes:
        if n not in idx: v(n)
    return out
eager = set(E["eager"]); rt = eager | set(E["lazy"])
print("\nEAGER edges:")
for (a, b), v in sorted(E["eager"].items()): print(f"  {a:14} -> {b:14} {len(v)}")
print("LAZY-only edges:")
for (a, b), v in sorted(E["lazy"].items()):
    if (a, b) not in eager: print(f"  {a:14} -> {b:14} {len(v)}")
print("TC-only edges:", sorted(k for k in E["tc"] if k not in rt))
print("\nSCC eager:", scc(eager)); print("SCC eager+lazy:", scc(rt))
print("mutual pairs (eager):", sorted({tuple(sorted(e)) for e in eager if (e[1], e[0]) in eager}))
print("mutual pairs (eager+lazy):", sorted({tuple(sorted(e)) for e in rt if (e[1], e[0]) in rt}))
if verbose:
    for want in sys.argv[2:]:
        a, b = want.split(">")
        for k in ("eager", "lazy", "tc"):
            for x in E[k].get((a, b), []): print(f"  {k:5} {a}>{b}: {x[0]}:{x[2]} imports {x[1]}")
```

Path and string references (section 5). `pins.py` matches `execution/<flat module>` and
`[decoy_engine.]execution.<flat module>` in every tracked file; in `.py` files it reads string
constants through `ast` and separates docstrings and comments, which section 5 leaves out:

```python
"""Every non-import reference to a FLAT execution module, by file and line. Run from engine root."""
import ast, json, re, subprocess, sys
from collections import defaultdict
REV = "origin/main"
def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
flat = [f.split("/")[-1][:-3] for f in git("ls-tree", "--name-only", REV, "src/decoy_engine/execution/").splitlines() if f.endswith(".py")]
flat = sorted((f for f in flat if f != "__init__"), key=len, reverse=True)
alt = "|".join(map(re.escape, flat))
PATH = re.compile(rf"execution/({alt})(?:\.py)?(?![\w/])")
DOT = re.compile(rf"(?<![\w.])(?:decoy_engine\.)?execution\.({alt})(?![\w])")
out = defaultdict(lambda: defaultdict(set))   # file -> kind -> lines
mods = defaultdict(set)
for f in git("ls-tree", "-r", "--name-only", REV).splitlines():
    try: text = git("show", f"{REV}:{f}")
    except Exception: continue
    if f.endswith(".py"):
        try: tree = ast.parse(text)
        except SyntaxError: continue
        docs = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                docs.add(id(n.body[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                hits = [(m.group(1), "path") for m in PATH.finditer(n.value)] + [(m.group(1), "dotted") for m in DOT.finditer(n.value)]
                for name, kind in hits:
                    k = ("doc-" if id(n) in docs else "str-") + kind
                    # multi-line constants: attribute to the constant's first line
                    out[f][k].add(n.lineno); mods[f].add(name)
        # comments
        for i, line in enumerate(text.splitlines(), 1):
            if "#" in line:
                c = line[line.index("#"):]
                if PATH.search(c) or DOT.search(c): out[f]["comment"].add(i)
    else:
        for i, line in enumerate(text.splitlines(), 1):
            hp, hd = PATH.findall(line), DOT.findall(line)
            if hp: out[f]["path"].add(i)
            if hd: out[f]["dotted"].add(i)
            for n in hp + hd: mods[f].add(n)
json.dump({f: {k: sorted(v) for k, v in d.items()} for f, d in out.items()}, open(sys.argv[1], "w"), indent=0)
json.dump({f: sorted(v) for f, v in mods.items()}, open(sys.argv[1] + ".mods", "w"))
```

Public surface (section 6). `surface.py <repo> origin/main <path prefixes>` lists imports,
attribute reads on module aliases and dotted strings:

```python
"""Public surface: names reached through decoy_engine.execution[.*] outside the engine's src. args: repo-root rev prefixes..."""
import ast, re, subprocess, sys
from collections import defaultdict
root, rev, prefixes = sys.argv[1], sys.argv[2], tuple(sys.argv[3:])
def git(*a): return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True).stdout
P = "decoy_engine.execution"
STR = re.compile(r"decoy_engine\.execution(?:\.\w+)*")
use = defaultdict(set)  # (module, name) -> {file:line}
for f in git("ls-tree", "-r", "--name-only", rev).splitlines():
    if not f.endswith(".py") or not f.startswith(prefixes): continue
    text = git("show", f"{rev}:{f}")
    try: tree = ast.parse(text)
    except SyntaxError: continue
    alias = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(P) and not n.level:
            for a in n.names: use[(n.module, a.name)].add(f"{f}:{n.lineno}")
        elif isinstance(n, ast.ImportFrom) and n.module == "decoy_engine" and not n.level:
            for a in n.names:
                if a.name == "execution": alias[a.asname or a.name] = P; use[(P, "<module>")].add(f"{f}:{n.lineno}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith(P):
                    use[(a.name, "<module>")].add(f"{f}:{n.lineno}")
                    if a.asname: alias[a.asname] = a.name
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias:
            use[(alias[n.value.id], "attr:" + n.attr)].add(f"{f}:{n.lineno}")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 300:
            for m in STR.findall(n.value): use[(m, "<string>")].add(f"{f}:{n.lineno}")
for (m, name), sites in sorted(use.items()):
    s = sorted(sites)
    print(f"{m} | {name} | {len(s)} | {'; '.join(s[:4])}{' …' if len(s) > 4 else ''}")
```

Run as:

```bash
python3 graph.py graph.json
python3 grp.py groups_final.json
python3 grp.py groups_final.json 'frame>sequential' 'sequential>frame'   # evidence lines for one edge
python3 pins.py pins.json
python3 surface.py ../decoy origin/main src/ tests/ docs/ scripts/ examples/
python3 surface.py . origin/main docs/ examples/ testflight/ custom_providers/ tests/unit/test_public_api.py
```

The tables in sections 3, 4, 5 and 7 are these outputs formatted as Markdown with no further
arithmetic except: wave "estimated non-test changed lines" is twice the import-line count, and
the wave 11 figure is the sum of the two modules' lines (114 + 94), an upper bound because one
line can import both.

## Appendix B. The grouping as data

```json
{
 "contract": [
  "_adapter",
  "_errors",
  "_events",
  "_operator_registry",
  "_output_projection",
  "_publication_observer",
  "_row_error_summary",
  "_row_errors",
  "_stitch",
  "_technique_class",
  "_transactional_sink",
  "_transforms_gate"
 ],
 "frame": [
  "_column_access",
  "_exact_int_sources",
  "_faker_degenerate_pin",
  "_fk_key_compat",
  "_fk_keys",
  "_fk_resolve",
  "_gated_string_guard",
  "_guards",
  "_pandas_adapter",
  "_pipeline_sources",
  "_positional_keys",
  "_runner",
  "_substrate",
  "_transforms",
  "_transforms_table",
  "_when_gate"
 ],
 "sizing": [
  "_mem_estimate",
  "_mem_estimate_arrow",
  "_mem_estimate_dtypes",
  "_mem_estimate_schema",
  "_throughput_calibration"
 ],
 "chunked": [
  "_chunked",
  "_chunked_adapter_gate",
  "_chunked_aggregate",
  "_chunked_carry",
  "_chunked_input",
  "_chunked_oracle",
  "_chunked_output_sink",
  "_chunked_preresolved",
  "_chunked_profile"
 ],
 "chunked_gates": [
  "_chunked_bucket_perturb",
  "_chunked_categorical",
  "_chunked_code_set",
  "_chunked_dgrn",
  "_chunked_fk",
  "_chunked_fk_dtype",
  "_chunked_fk_dtype_safety",
  "_chunked_fk_edge_checks",
  "_chunked_fk_runtime",
  "_chunked_fk_vocab",
  "_chunked_group_key",
  "_chunked_text_mask",
  "_chunked_when_guard"
 ],
 "sequential": [
  "_sequential",
  "_sequential_composite_chain",
  "_sequential_native",
  "_sequential_native_decisions",
  "_sequential_native_group_key",
  "_sequential_native_ops",
  "_sequential_native_text_mask",
  "_sequential_order"
 ],
 "unified_slice": [
  "_unified_slice",
  "_unified_slice_admission",
  "_unified_slice_evidence",
  "_unified_slice_resident_types",
  "_unified_slice_when"
 ],
 "routing": [
  "_pipeline_chunk_route",
  "_pipeline_routing",
  "_pipeline_routing_fk_dtype",
  "_pipeline_routing_samples",
  "_pipeline_routing_signals",
  "_planner",
  "_planner_columns",
  "_transforms_admission"
 ],
 "spine": [
  "_job_estimate",
  "_mixed_admission",
  "_mixed_fk_bridge",
  "_mixed_static",
  "_pipeline",
  "_pipeline_auto_chunk",
  "_pipeline_context",
  "_pipeline_finalize",
  "_pipeline_full_frame",
  "_pipeline_generate_mask",
  "_pipeline_mixed_route",
  "_pipeline_multi_table",
  "_pipeline_route_dispatch",
  "_pipeline_route_exec",
  "_residency_warning",
  "_transforms_prepare",
  "pipeline._stream",
  "pipeline._subset_stage"
 ],
 "isolated": [
  "_governor",
  "_governor_monitor",
  "_isolated_commit",
  "_isolated_common",
  "_isolated_memwatch",
  "_isolated_reason",
  "_isolated_run",
  "_isolated_worker",
  "_probe",
  "_probe_scale"
 ]
}
```
