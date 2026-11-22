Status: plan (revision 6, 2026-11-22; Codex R2 closed)

# PER-COLUMN-ROUTING: native and Python columns in one table, on the chunked lane and the unified slice

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: PER-COLUMN-ROUTING (CLI `docs/roadmap/groups/run.md:34`, moved from 1.1 into V1 by the owner on 2026-11-22). Four slices: S0 preparatory moves (no behavior change), S1 chunked lane, S2 unified slice with docs and benchmark record, S3 a CLI test-only PR.

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Depends on, before S1 starts:

- **ROUTE-LABEL-TRUTH slice 1** (`docs/plans/2026-11-22-route-label-truth.md`, branch `plan/route-label-truth`): `column_decline_code`, `PhysicalNode.decline_code`, the kernel-less family codes, `RouteSummary.executed_backends`, the CLI `mixed` label row, and the A5 carve-out (guarantee 8 there). The carve-out matters here: an oracle error raised by the Python half inside the unified slice is a `DecoyError` and must keep its own code and exit. Without the carve-out, `_unified_slice.py:358` would swallow it and rerun the table.
- **WHEN-READS-SOURCE** (`docs/plans/2026-11-22-when-reads-source.md`, branch `plan/when-reads-source`): every route evaluates a `when:` on the original values of the columns it names (its guarantee 1). With that contract, a `when:` on a Python column reads the same values from the sub-table as from the full oracle run, whatever the other half masked, so this plan needs no `when:` handling across halves. It also removes the native `when_reads_masked_column` decline, so more `when:` columns land in N.
- **UF-DOMAIN S1** (`origin/plan/uf-domain` at `cb4edf11d`, `docs/plans/2026-11-22-uf-domain.md` section 3 "After S1"): the one output assembler, `table_from_pandas_keeping_source_types` (`execution/_fk_keys.py:521`) widened to take the source table and `arrow_columns`; and `frame_columns(nodes, config, table)` (`execution/_unified_slice_resident_types.py`), the one definition of which columns a set of nodes reads. This plan adds one input to that assembler and calls `frame_columns` for the Python half. It adds no assembler of its own.
  - **Stated dependency on `frame_columns` (to be carried into UF-DOMAIN, not edited here).** UF-DOMAIN S1 at `cb4edf11d` defines a frame column as a non-passthrough target, a `group_key` `group_by` sibling or a `when:` read. The Python half needs the full read set, so `frame_columns` must be: "`frame_columns(nodes, config, table)` returns, in source order, the target columns of `nodes` plus every column in `column_access(entry).reads` for each node's config entry (`execution/_column_access.py:142-200`; `column_access` at `:362`). This covers `group_key` `group_by` siblings, `when:` reads (phase `source`, WHEN-READS-SOURCE guarantee 9), `joint_mask` `key_by`, `date_shift` `group_by` and `derived` expression references. If any node's access is `reads_unknown`, it returns every column of the batch." The unified slice's resident frame keeps its own narrower rule only if UF-DOMAIN chooses to; this plan needs only the full read set for the Python half. Until UF-DOMAIN carries this text, S1 does not start.

Sources: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md` ("A table takes one route"); `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 3 limit 2 and section 6; CLI `docs/roadmap/groups/run.md:34`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `feature-dev.md`, `refactoring.md`, `architecture.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `performance.md`, `api-and-compatibility.md`, `security.md` (value-free evidence), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R3. It changes which code masks which column on the default routes, and output bytes may change (owner direction below). Plan review: Dennis, then Codex. Code gate: Codex and Dennis (`/code-review high`: masking lane). Full suite (T3) at each merge head, and mutations on the core units at the final head of each behavior slice.

Owner direction (2026-11-22): V1 must be fast and reproducible. Where a byte-changing design is faster or simpler than a byte-identical one, plan the faster one. Pre-V1 byte changes are allowed. Output must stay deterministic for a given seed or namespace, and each change is marked in section 10 and in the changelog `Breaking:` line. This plan uses that freedom: it does not promise byte parity with today's single-route output. It promises exact values per column (section 3, item 7), determinism and chunk-size invariance.

## 1. Frame

Today a table takes one route. `native/_dispatch.py:232` (`_static_route_decision`) decides from every node, and its comment at `:286-291` says it: "never a per-column mix, since a non-admitted table runs 100% on the oracle". The unified slice does the same: `resident_contract_admission` (`execution/_unified_slice_admission.py:410`) declines the table if one node has no binding (`:470`). So one `faker(address_full)` column puts nine `hash` columns on pandas. The audit lists this as the main reason the default faker, `shuffle`, `geo_generalize` and `formula` tables run slow.

After this change a table whose columns split into a native set and a Python set runs the native set on the kernels and the Python set on the pandas oracle, on the same batch, and builds one output through the one assembler. This is the established design for this problem (section 2).

## 2. Established solutions

Search run: per-operator or per-expression fallback in vectorized engines (Spark Python UDFs, Gluten/Velox, Polars, DataFusion, DuckDB).

- **Spark `ExtractPythonUDFs`.** The optimizer pulls Python UDFs out of a projection into an `ArrowEvalPython` (or `BatchEvalPython`) node. That node sends only the UDF input columns, as Arrow batches, to a Python worker and appends the result columns. The rest of the projection stays in the JVM. Two rules from it are used here: send the Python side only the columns it reads, and put the results back into the batch.
- **Gluten/Velox.** Fallback is per plan node: the nodes Velox supports run native and the others run on vanilla Spark, with a transition between them. Gluten counts the transitions as a cost. Here a transition is one Arrow-to-pandas conversion of the Python half's columns per batch.
- **Polars.** Expressions in one `with_columns` call all read the input frame, never each other's output, so they can run in parallel. `map_batches` is the escape hatch for Python code. This plan applies that rule between the two halves: a native column and a Python column in one mixed table never read a value the other half masked. A table where one would is not mixed (section 3, item 4).
- **DataFusion and DuckDB.** A scalar UDF gets the input batch's arrays and returns one array of the same length; the engine checks the length. Here that check is `require_same_rows` inside the adapter and the assembler's row-count assert.

No custom scheduler is added. The mixed route reuses the two executors the engine already has (the native chunk masker and the pandas adapter), the per-chunk oracle step and the one output assembler.

### Reuse inventory

- `execution/_pandas_adapter.py:164` `PandasExecutionAdapter.run`: the whole oracle, run on a trimmed plan and a smaller table. No per-node extraction.
- `execution/_chunked_oracle.py:407-505`: the per-chunk body of `_oracle_masked` (guards, adapter call with `carry`, row-error fail-closed, DGRN offset). S0 factors it into one function that both the oracle loop and the mixed branch call.
- `execution/native/_chunk_masking.py:56` `_mask_chunk_native`: the native chunk masker, column by column, with `unconfigured` passthrough.
- `execution/physical/_shadow_coordinator.py` and `_shadow_batch_runner.py`: the unified slice's native executor. An unbound node is skipped (`_shadow_batch_runner.py:137-146`), but the runner then requires the produced columns to equal the full source set and raises `SCHEMA_DIFF` otherwise (`:247-265`). Guarantee 6 changes that boundary.
- `execution/_runner.py:354` `column_dependency_edges`: the created-column driver edges (from `scalar_creating_reads`) that decide which nodes must stay together.
- `execution/_runner.py:354` `column_dependency_edges` (`_masked_driver_columns`): masked driver reads of the creating strategies (`derived`, `derived_aggregate`, `grouped_series`, `windowed_date`, `group_key`) and `nested`.
- `execution/_fk_keys.py:521` `table_from_pandas_keeping_source_types`, as widened by UF-DOMAIN S1: the one output assembler.
- UF-DOMAIN `frame_columns`: the one definition of a node set's read columns.
- `execution/native/_route_decline_codes.py`: decline records and `column_decline_code` (ROUTE-LABEL-TRUTH).
- `execution/native/_chunked_evidence.py:116` `executed_backend`: the per-column backend vocabulary.

## 3. Guarantee and non-goals

After this plan:

1. **Partition.** One function, `partition_columns(plan, table, native_ok) -> ColumnPartition | RouteDeclineRecord`, splits a table's mask nodes into a native set N (nodes the lane's existing per-column checks admit) and a Python set P (the rest). `native_ok` is the lane's own per-node verdict: the per-node pass of `_static_route_decision` for the chunked lane, `PhysicalNode.execution is not None` for the unified slice. The partition adds no admission rule of its own.
2. **When a table is mixed.** A table runs mixed when N and P are both non-empty, the table has no table-wide decline, after item 4 has moved driver groups into P. If P is empty, the table runs today's native route. If N is empty, it runs today's route for P. Table-wide declines (FK, validators, vault, quarantine and the others) still send the whole table to today's route.
3. **Execution of one batch** (a chunk on the chunked lane, the whole table on the unified slice):
   - N runs on the native executor over the batch, with every P target column passed as `unconfigured`.
   - P runs on `PandasExecutionAdapter.run` with `plan_for_nodes(plan, P)` and the sub-table `batch.select(frame_columns(P, config, table))`: every P target plus every column a P entry's `column_access(entry).reads` names, or the whole batch when a P node has `reads_unknown` (the dependency above). `plan_for_nodes` keeps the full plan, including the full `seed_envelope`, and trims only the work nodes to P. `enforce_output_projection` (`execution/_output_projection.py:90-120`) checks output columns against `known_output_columns(plan, table)` (`:58-73`), which reads the seed envelope, so the sub-table's columns are all declared and no `undeclared_output_columns` is raised under either policy.
   - On the chunked lane the P call goes through the factored per-chunk oracle step (item 5), never a second copy of it.
   - The output is built by the one assembler: `table_from_pandas_keeping_source_types(frame=None, source=batch, untouched=..., arrow_columns=<N outputs>, python_half=<P output table>)`. `python_half` is the one input this plan adds. The assembler takes P target columns from it as stored, N target columns from `arrow_columns`, and every other column from `batch`. It asserts `python_half.num_rows == batch.num_rows` and each `arrow_columns` length, naming the half (`native` or `python`), and raises `HANDLER_ROW_COUNT_CHANGED` otherwise. Columns come out in source order (UF-DOMAIN assert). `require_same_rows` still guards each P node inside the adapter.
4. **Created columns stay with their drivers (one shared function).** A `when:` needs no rule here: under WHEN-READS-SOURCE it reads original values, which the sub-table holds. The only reads across columns that see a masked value are created-column drivers: a creating strategy (`derived`, `derived_aggregate`, `grouped_series`, `windowed_date`, `group_key`: the `OWN_TARGET_CREATES` declarations at `execution/_column_access.py:329-335`; `formula` is not one) reads the masked value of its drivers (`scalar_creating_reads`, `execution/_column_access.py:391`), ordered by `column_dependency_edges` (`execution/_runner.py:354`). `group_drivers_into_python(partition, work) -> ColumnPartition` is the one function, used by both lanes. It takes the connected components of the `column_dependency_edges` graph over the table's nodes, and moves every component that holds a P node wholly into P. So a P created column and every N node that writes one of its drivers (and, transitively, their drivers) run together on the oracle, in the oracle's work order, and the created column sees the masked driver value exactly as today. An N creating node whose driver is a P target moves too. The native strategies that create columns today (`group_key`) read only unmasked siblings (`group_key_sibling_*` admission), so their component is all-N. If the move empties N, the table runs today's route for P. No decline code is needed. SOURCE-read drivers (`joint_mask` `key_by`, `date_shift` `group_by`) have no edge and read the original value, which the sub-table holds.
5. **Chunked lane.** P is allowed only when the chunked oracle preflight (`_chunked_oracle._oracle_preflight`, `:91`) accepts the trimmed plan, the same check that runs today. Each chunk's P half runs through `oracle_chunk_step`, factored out of `_oracle_masked` (`_chunked_oracle.py:407-505`) in S0, so the one copy keeps: the per-chunk schema guards (FK passthrough, declared FK dtype, `text_mask`, `code_set`, `bucket_perturb`), the DGRN `row_offset` (`dgrn.validate_chunk_row_offset_range` and the global offset passed to the adapter), `carry` (`carry.adapter_input`, `diagnose_adapter`, `reattach`), and the `RowErrorsFailedError` fail-closed raise on any row error. The mixed loop advances `row_offset` once per chunk with `dgrn.advance_row_offset`. A row error in any chunk raises before that chunk is yielded, so the output sink publishes nothing. **Mixed branch inputs and schema.** The mixed branch passes `oracle_chunk_step` the sub-chunk `chunk.select(frame_columns(P, config, table))`, never the raw chunk. The table's `CarryPlan` (`execution/_chunked_carry.py:84-120`) is used unchanged: `adapter_input` and `reattach` act only on `carried` columns present in the table they get, and a carried column is one no entry reads or writes (`read_set`, `:64-81`), so it is never in `frame_columns(P)`. Both calls are therefore the identity on the sub-chunk, and `diagnose_adapter` still names a read passthrough column on a conversion failure. Carried columns reach the output from `batch` through the assembler. A test asserts `carry.carried ∩ frame_columns(P) == ∅` for every P1 table. The mixed branch passes `oracle_chunk_step` an `on_chunk` that returns the produced table unchanged, so the P half is not normalized on its own. After `assemble_mixed`, the branch calls `normalize_chunk(rule, assembled, chunk, table=table, chunk_index=i)` (`native/_chunked_schema_rule.py:321`) once, with the rule the native-admitted path builds today (`build_schema_rule`, `native/_chunked_entry.py:556`; the oracle-route `on_chunk` at `:149` and the native path at `:394` normalize the same way). So one call pins the schema of every assembled chunk, for both halves, against the source chunk. Whole-column families (`shuffle`, `geo_generalize`, `derived_aggregate`, `grouped_series` and an aggregate `formula`) are not row-local, so their table still does not chunk, as today.
6. **Unified slice (full frame).** P may hold any strategy, including whole-column families. The adapter runs them over the full column, where they run today. A full-frame table with `shuffle` on one column and `hash` on nine runs the nine through the kernels and `shuffle` through the oracle over the whole column. A `DecoyError` from the P half propagates with its own code and exit (ROUTE-LABEL-TRUTH A5 carve-out).
   - **Partial N result at the physical boundary.** Today `run_shadow_batches` raises `SCHEMA_DIFF` when the produced columns differ from the source columns (`physical/_shadow_batch_runner.py:247-265`), and the unified caller expects a complete table (`_unified_slice.py:289-295`). So without a change every mixed table would fail before `assemble_mixed`. `ShadowCoordinator.run` (`physical/_shadow_coordinator.py:149`) and `run_shadow_batches` (`:109`) gain one keyword, `deferred_columns: Mapping[str, frozenset[str]] | None = None`: per table, the P target columns the caller runs on the Python half. With `None` the check is today's, unchanged. With a set, the projected N schema is `source columns - deferred[table]`, and the runner raises `SCHEMA_DIFF` unless the produced columns equal it exactly: a missing N column (an unbound node whose target is not deferred), a produced deferred column, or a deferred name that is not a source column all fail closed. The validated partial table is built in source order over the projected schema. `ShadowRunResult` gains `deferred_columns` (empty by default), so the result says it is partial.
   - **Every path from the unified caller to the batch runner (traced at the head).** The unified slice has one call into the physical seam: `ShadowCoordinator(...).run(physical_plan, snapshot, when_masks=...)` at `_unified_slice.py:250-252`. `ShadowCoordinator.run` (`physical/_shadow_coordinator.py:149-198`) then branches, in order:
     1. no mask tables and a synthesis stage: `_dispatch_synthesis` (`:164-165`);
     2. mask tables and a synthesis stage: `_dispatch_mixed` (`:166-172`), which recurses into `run()` for the mask half (`physical/_shadow_mixed.py:196`) without `when_masks`;
     3. driver set `{OUT_OF_CORE}`: `_dispatch_out_of_core` (`:181-182`);
     4. driver set `{FULL_FRAME}`: `_shadow_full_frame.dispatch_full_frame_if_applicable` (`:183-188`), which captures the whole plan whenever any node's strategy is in `ADMITTED_GLOBAL_STRATEGIES` (`shuffle`, `top_code`, `grouped_series`, `derived_aggregate`; `physical/_shadow_full_frame.py:119-136`) and runs the whole table on the pandas adapter;
     5. `OUT_OF_CORE` mixed with another driver: `MIXED_DRIVER_UNSUPPORTED` (`:189-194`);
     6. otherwise `run_shadow_batches` (`:196-198`), the only place the projected-schema check runs.
     The unified slice compiles one mask-only, non-FK, full-frame table, so it reaches only branch 4 or 6. Branch 4 is the one that hid the fix: with `shuffle` in P, it captured the table before the runner saw `deferred_columns`.
   - **Coordinator rule for `deferred_columns`.** `ShadowCoordinator.run` gains the same `deferred_columns` keyword and passes it on. With `deferred_columns` set:
     - branches 1, 2, 3 and 5 refuse it with `ShadowDifference(SCHEMA_DIFF)` ("deferred columns on a non-full-frame plan"), before any work. A partial plan never reaches the synthesis, mixed-synthesis or out-of-core dispatch.
     - branch 4: `dispatch_full_frame_if_applicable(coordinator, plan, snapshot, *, deferred_columns=None)` counts as a candidate only a node whose target is not deferred. In the `shuffle` plus nine `hash` table the `shuffle` node is deferred, so there is no candidate, the function returns `None`, and the plan falls through to branch 6 with `deferred_columns`. If a candidate node remains while `deferred_columns` is set (a whole-column node left in N, which `partition_columns` never produces because such a node has no binding), the function raises `ShadowDifference(SCHEMA_DIFF)` instead of capturing the plan. It never runs a partial plan on the full-frame adapter.
     - branch 6: the projected-schema check above.
     With `deferred_columns=None` every branch is unchanged.
   - The mixed path of `_execute_admitted` passes `deferred_columns = {table: P targets}`, checks that the result's `deferred_columns` equals it, and hands the partial table to `assemble_mixed` as `native_out`. It never passes a partial table to the complete-table path at `_unified_slice.py:289-295`; a table that is not mixed passes `None` and keeps that path unchanged.
7. **Values.** Every column of a mixed output has exactly the values of its reference, null positions included, compared with `pa.Array.equals` after a cast to the reference's type:
   - an N column against a run of the same table with every P column set to `passthrough` (so that run takes today's native route);
   - a P column against a run of the same table on today's oracle route (`--no-native`).
   The only allowed differences are the type differences listed by type in section 10 B1. Any value difference fails.
8. **Determinism.** The same config, seed and namespace give the same output bytes on rerun, for any `native_threads`, and the same values for any chunk size.
9. **Warnings.** The warnings of both halves are merged into one list, ordered stably by the canonical work-order index of the node that raised them (`_runner.in_work_order`). Projection warnings come last, as today. The merge is one small function, `merge_half_warnings`.
10. **Evidence.** Each column's `executed_backend` is its half's backend: a P column records `pandas_oracle`, an N column its native backend. `chunked_route` and `unified_slice_activation` gain `mixed: true` for a mixed table. `RouteSummary.executed_backends` then shows both, and the CLI prints `mixed (native and Python columns)`.

Non-goals: a single work-order loop that interleaves N and P nodes (it would let a driver stay native while its created column runs on the oracle, at the cost of a per-node conversion); native kernels for any kernel-less family; mixing on FK, sequential, out-of-core or mixed-route FK tables; running the two halves in parallel; any change to which columns the native checks admit; any change to the output assembler beyond the `python_half` input.

## 4. Enumerations

### Exit paths

- Partial N result that does not match the projected N schema (a missing N column, a produced deferred column, an unknown deferred name): `SCHEMA_DIFF` from `run_shadow_batches` (existing code, `physical/_shadow_diff_codes.py:50`), names only. Nothing is written.
- Row-count mismatch at the assembler: `HANDLER_ROW_COUNT_CHANGED` (existing code), message names the half and the table, never a value. Exit 3. Nothing is written: the assert runs before any yield or publish.
- A P node failure: the same typed error the oracle raises today for that node, with its code and exit (A5 carve-out on the unified slice; no wrapper on the chunked lane).
- A P row error on the chunked lane: `RowErrorsFailedError` from `oracle_chunk_step`, before the chunk is yielded; the output sink discards (as `_chunked_oracle.py:490-503` today).
- An N column failure: the same error the native lane raises today.
- Moving a driver group into P is not an error and records no decline; the moved columns report `executed_backend = pandas_oracle`.

### Routes

- Chunked lane (auto-chunk single table, and each table of the multi-table split): mixed when item 2 holds and item 5 allows P. Decided in `native/_dispatch.py:232`, run in the chunk loop at `native/_chunked_entry.py:318`.
- Unified slice, full frame, one non-FK resident mask table: mixed when item 2 holds. Entered at `execution/_pipeline_full_frame.py:171`; partition in `execution/_unified_slice_admission.py:410`.
- Full-frame oracle, FK route, sequential route, out-of-core route: unchanged.
- `--chunked` CLI runs and `run_mask_pipeline_chunked`: unchanged, except that they now call `oracle_chunk_step` through the refactored `_oracle_masked` (S0, no behavior change).

### FK shapes

N/A: a table in any declared relationship is declined table-wide before partition (`_dispatch.py:255`, `fk_relationship`), on both lanes.

### Fields

- `quality_metrics["chunked_route"]["mixed"]` and `quality_metrics["unified_slice_activation"]["mixed"]` (new booleans).
- `executed_backend` per column can be `pandas_oracle` inside an admitted table.

### Output surfaces

- Masked output tables of a mixed table: values per item 7, bytes may change (section 10).
- `quality_metrics` route evidence and the warnings list (order per item 9).
- `RouteSummary.executed_backends` and the CLI run card label (`CLI:src/decoy/_native_gate.py` `classify_route`, after ROUTE-LABEL-TRUTH).

## 5. Slices and size

### Whole-table steps of the adapter

`PandasExecutionAdapter.run` (`execution/_pandas_adapter.py:164-330`) has these steps that look at more than one node. For each, the trimmed plan and the sub-table give the same per-column result as the full run:

| Step | Line | Why the P half gets the same result |
|---|---|---|
| `lossless_int_columns(plan, registry, graph)` then `to_pandas_fk_safe(tbl, lossless.for_table(t, tbl))` | `:200-202` | the set is computed from the full plan (envelope kept) and filtered to the sub-table's columns; each column's conversion depends only on that column |
| token vault writer | `:233` | not reached: a vault column or writer is a table-wide decline |
| `order_work(build_work_list(plan, registry), graph)` | `:238` | P nodes keep their relative order: the order is a topological sort with a fixed key, and no P node depends on an N node written earlier (item 4) |
| row-error drain per node | `:296-303` | per node; unchanged |
| `enforce_output_projection(..., plan, policy)` | `:311` | the envelope is kept, so every sub-table column is declared (item 3); tested with policy `error` |
| `apply_degenerate_faker_pin` | `:317` | applies per faker column of the outputs; the P half's faker columns are the same columns with the same seeds; `pin_degenerate_faker` is passed as the full-frame caller passes it |
| `table_from_pandas_keeping_source_types(..., untouched_columns(...))` | `:319-322` | the sub-table's read-only columns come back untouched; the mixed assembler takes only P targets from the P output |

The builder rechecks this table at DEVELOP against the head and adds any step it finds, with the same "why" column.

### Slice S0: preparatory moves (no behavior change)

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/chunked/_oracle_step.py` (new) | 0 | `oracle_chunk_step(state, chunk, *, plan, table, chunk_index, row_offset, on_chunk, chunk_result_sink)`: the body of `_chunked_oracle.py:407-505` moved unchanged, minus the offset advance and the vault add, which stay in the loop | about 120 |
| `execution/_chunked_oracle.py` | 600 | `_oracle_masked` loop calls `oracle_chunk_step` | about 505 |
| `execution/native/chunked/_oracle_route.py` (new) | 0 | `_oracle_route` (`_chunked_entry.py:119-180`) moved unchanged | about 70 |
| `execution/native/_chunked_entry.py` | 689 (ceiling 689) | minus `_oracle_route` | about 630; ceiling ratchets down to `ceiling_for(loc)` |
| `execution/native/chunked/_route_scan.py` (new) | 0 | the per-node pass of `_static_route_decision` (`_dispatch.py:283-389`, the loop that builds `reasons`, `declines` and `scalar_columns`) moved into `scan_table_nodes(...) -> NodeScan`, unchanged | about 120 |
| `execution/native/_dispatch.py` | 679 (ceiling 688) | `_static_route_decision` calls `scan_table_nodes` | about 590; leaves the census (under 600) |

Sentry baselines S0 updates for the moved paths (regenerated by each sentry's own script, then reviewed):

- `tests/sentry/baselines/lossless-int-columns.json:5`: the key `adapter_fk_safe_columns::execution/_chunked_oracle.py::_oracle_masked._masked` becomes the same call site under `execution/chunked/_oracle_step.py::oracle_chunk_step`. Same call, new path; the baseline does not grow.
- `tests/fixtures/f29/producer-inventory.json` and `tests/sentry/baselines/f29-producer-inventory.json`: no producer sits in the moved ranges today (the one `_chunked_entry.py` entry is `_validate_native_threads` at `:100`, above the move; `_dispatch.py` declines are enum members, recorded at `_route_decline_codes.py`). The builder reruns the inventory script and commits any change, which must be line or path only.
- `tests/sentry/baselines/module-size.json:50`, `:53`: `_chunked_entry.py` ratchets down; `_dispatch.py` leaves the census when it drops under 600.
- `tests/sentry/baselines/gcs-call-kwargs.json:62`, `:141` and `secret-material-census.json:55`, `:118`: entries in `_oracle_preflight_admitted` and `_native_route`, which do not move; unchanged.
- `GUARDED_MODULES` (`tests/sentry/test_physical_seam_disconnection.py:56-130`): confirmed at the head. It lists `execution/native/_dispatch.py` but neither `_chunked_entry.py` nor `_chunked_oracle.py`. S0 adds `execution/native/chunked/_route_scan.py` (it holds code moved out of a guarded module, so it must stay guarded) and `execution/native/chunked/_oracle_route.py` (a routing layer); S1 adds `execution/chunked/_oracle_step.py` and the two `pipeline/` modules. None imports `execution.physical`.

Control: the auto-chunk suites (`tests/unit/execution/test_auto_chunk_*`), the chunked-oracle suites and the B6a/B6b suites pass unchanged. Size: about 310 lines moved, about 20 changed.

### Slice S1: chunked lane mixing

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/pipeline/_column_partition.py` (new) | 0 | `ColumnPartition`, `partition_columns`, `plan_for_nodes`, `group_drivers_into_python` | about 150 |
| `execution/pipeline/_mixed_columns.py` (new) | 0 | `merge_half_warnings`, and `assemble_mixed(batch, partition, native_out, python_out)` which calls the one assembler | about 80 |
| `execution/_fk_keys.py` | 575 + UF-DOMAIN S1 | `python_half: pa.Table | None` input to `table_from_pandas_keeping_source_types` | +15 |
| `execution/native/chunked/_route_scan.py` | about 120 | `NodeScan` carries the per-node verdict that `partition_columns` reads | +10 |
| `execution/native/_dispatch.py` | about 590 | the decision carries the partition when mixed | about 605 |
| `execution/native/_chunked_entry.py` | about 630 | mixed branch in the chunk loop: `_mask_chunk_native` for N, `oracle_chunk_step` on the P sub-chunk, `assemble_mixed`, one `normalize_chunk` on the assembled chunk, one offset advance | about 655 |
| `execution/native/_chunked_evidence.py` | 291 | `executed_backend` reads the column's half; `mixed` flag | about 305 |

Also: `GUARDED_MODULES` gains both new `pipeline/` modules and `chunked/_oracle_step.py` (S0 added the two `native/chunked/` modules); UF-DOMAIN's assembler sentry (`test_output_assembly_one_path.py`) needs no allowlist entry (no new `from_pandas`); the changelog fragment carries the `Breaking:` lines. Size: about 300 source lines, about 750 test lines.

### Slice S2: unified slice mixing, docs and benchmark record

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/_unified_slice_admission.py` | about 555 after RLT and UF-DOMAIN | `resident_contract_admission` returns the physical table for N plus the partition, instead of declining on the first unbound node (`:470`) | about 580 |
| `execution/_unified_slice.py` | about 490 after RLT | `_execute_admitted` runs the coordinator over N with `deferred_columns`, `PandasExecutionAdapter.run` over P, then `assemble_mixed` on the partial N table | about 520 |
| `execution/_unified_slice_evidence.py` | 246 | P nodes get node evidence with `executed_backend = pandas_oracle`; `mixed` flag | about 270 |
| `execution/physical/_shadow_batch_runner.py` | 350 | `deferred_columns` keyword; the schema check compares against the projected N schema; partial output in source order | about 365 |
| `execution/physical/_shadow_coordinator.py` | 289 | `deferred_columns` keyword; refusal on branches 1, 2, 3, 5; pass to branches 4 and 6 | about 300 |
| `execution/physical/_shadow_full_frame.py` | 394 | `deferred_columns` narrows the candidate test; a remaining candidate with deferred columns raises `SCHEMA_DIFF` | about 405 |
| `execution/physical/_shadow_result.py` (`ShadowRunResult`, `:23`) | 46 | `deferred_columns` field, empty by default | about 48 |
| `docs/execution-backends.md` | n/a | "Mixed tables": what mixes, the driver-group rule, the type differences | +40 |
| `docs/records/2026-12-xx-per-column-routing-bench.md` | new | the P-bench record | new |

Size: about 150 source lines, about 620 test lines.

### Slice S3: CLI test-only PR

- `CLI:tests/e2e/test_run_native.py`: the `mixed` label end to end on a chunked and a full-frame mixed table. No CLI source change. Rides the engine pin bump of the release that holds S2 (repin checklist).

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_column_partition.py` | `src/decoy_engine/execution/pipeline/` | "Pipeline spine and routes": new route modules go in `execution/pipeline/` (`execution/` is frozen at 103 direct modules) | `_routing_facts.py`, `_route_summary.py` |
| `_mixed_columns.py` | `src/decoy_engine/execution/pipeline/` | same | same |
| `_oracle_step.py` | `src/decoy_engine/execution/chunked/` | "new route clusters go in `execution/chunked/`" | `_progress.py`, `_source_dtype_gate.py` |
| `_oracle_route.py`, `_route_scan.py` | `src/decoy_engine/execution/native/chunked/` | "New native modules go in `execution/native/draw/` or `native/chunked/`" (`native/` is frozen at 55) | `_core.py` |
| `test_column_partition.py`, `test_mixed_columns.py` | `tests/unit/execution/pipeline/` | engine execution tests, existing subpackage | `test_native_fallback_notice.py` |
| `test_mixed_chunked.py` | `tests/unit/execution/native/` | existing chunked lane tests | auto-chunk tests |
| `test_mixed_unified_slice.py` | `tests/physical/` | unified slice tests | `test_unified_slice_parity.py` |
| `test_mixed_properties.py` | `tests/property/` | Hypothesis property tests | existing property suites |

Fan-out after this plan and ROUTE-LABEL-TRUTH: `execution/pipeline/` 16 + 1 + 2 = 19 of 25; `execution/chunked/` 2 + 1 = 3; `execution/native/chunked/` 1 + 2 = 3. No package passes its cap. No new sub-package.

## 7. Design notes

- **Principles.** Single responsibility at the seam: the partition decides, the two existing executors execute, the one assembler builds the output. No executor learns about the other. Open/closed: a strategy that gets a kernel later moves from P to N through the operator registry, with no change here.
- **Pattern.** Spark `ArrowEvalPython` (only the read columns go to Python; results go back into the batch) and the Polars "read the input" rule between halves (section 2).
- **One place per fact.** Read columns: `frame_columns` (UF-DOMAIN). Driver groups: `group_drivers_into_python`, built on `column_dependency_edges`. The `when:` contract: WHEN-READS-SOURCE. Native verdict per node: the lane's own check, passed as `native_ok`. Output assembly: the one assembler. Per-chunk oracle work: `oracle_chunk_step`. Warning order: `in_work_order`.
- **Choke points.** (a) The one assembler: UF-DOMAIN's sentry already forbids a second `from_pandas` output path; this plan adds no allowlist entry. (b) `oracle_chunk_step`: a sentry test asserts that `adapter.run` is called in `execution/chunked/_oracle_step.py` and nowhere else on the chunked lane (AST scan of `_chunked_oracle.py`, `native/_chunked_entry.py` and `native/chunked/`). Mutation: call `state.adapter.run` directly in the mixed branch (sentry red). (c) `group_drivers_into_python`: both lanes call it (spy test); mutation: move only the P node and not its drivers (P2 red).
- **House style.** `ColumnPartition` and `NodeScan` are frozen dataclasses; no flag arguments; `assemble_mixed` takes the partition, not loose lists.
- **Why not one interleaved loop.** It would need the oracle split into a per-node session, a pandas conversion per Python node, and a native-to-pandas value hand-off. It is slower and adds a third executor. The two-half design reuses the executors whole and is the faster option the owner direction asks for. The price is that a driver of a Python created column runs on the oracle too.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | assembler errors, decline record, evidence | messages name half, table and column only; record is code and identifiers | P7 | add the first differing value to the message (P7 red) |
| 2 | Cleanup missing on an exit path | chunked failure mid-stream | the existing output sink owns publish and discard; the mixed branch raises before yield | P6, P14 | yield before the row-error check (P14 red) |
| 3 | State and concurrency | native threads | each half runs in turn; native threads apply to N only | P4 | n/a |
| 4 | Route parity and silent fallback | partition, driver groups, assembly | exact values per column (P1); a created column and its drivers run in one half | P1, P2, P5 | split a driver group across halves (P2 red); swap two columns at assembly (P1 red) |
| 5 | Referential integrity | FK tables | declined table-wide before partition | P8 | move the FK check after the partition (P8 red) |
| 6 | Untrusted producer | adapter result for P | row count asserted at the assembler; only P targets taken from it | P6 | skip the row assert (P6 red) |
| 7 | Check then use | partition decided once, executed per chunk | the decision carries the partition; per-chunk schema guards run in `oracle_chunk_step` | P9, P14 | skip the guards for P (P9 red) |
| 8 | Weak tests | value checks on easy data | Hypothesis over nulls, empty and all-null chunks, degenerate fpe and bucket_perturb types, `when:` gates, `windowed_date` | P1, P13 | n/a |
| 9 | Refactor drift | S0 moves | moved unchanged; existing chunked suites are the control | P10 | n/a |
| 10 | Frozen contract drift | output types, warning order, evidence | listed in section 10 with `Breaking:` lines; snapshots regenerated and reviewed | P11 | n/a |
| 11 | Determinism | seeds, chunk size, threads, DGRN offset | per-column seeds unchanged; one offset advance per chunk; global offset passed to the P half | P3, P4, P13 | pass `row_offset=0` to `oracle_chunk_step` (P13 red) |

## 9. Acceptance tests

Each fails before the change unless marked control. "Mixed table" below means 9 native columns (`hash in ns` on strings, deterministic `categorical`, `date_shift`, `redact`) and at least one Python column.

- **P1 exact values (Hypothesis).** Random mixed tables: column types from the admitted set, nulls, empty strings; P columns from `faker(address_full)`, `bucketize`, `top_code`, `code_set`, a row-wise `formula`, `windowed_date`, and a `when:` on a P column reading another P column. For every column, `mixed.column(c).equals(reference.column(c).cast(mixed_type))` with nulls in place, against the item 7 references (N columns: same table with every P column set to `passthrough`; P columns: `--no-native`). Column order equals the source schema. The cast is allowed only for the type pairs listed in section 10 B1; any other type difference fails. Fail-before: the evidence check (N columns ran on a kernel) fails because the table runs one route.
- **P2 created columns and `when:` (needs WHEN-READS-SOURCE).**
  - `aa_total: derived` (expression `amount * 2`) reading `amount: hash in ns`, plus 8 other `hash` columns: `amount` moves into P with `aa_total`, both report `pandas_oracle`, the other 8 run native, and `aa_total` equals the oracle output (it reads the masked `amount`, as today). Fail-before: whole table on the oracle.
  - A chain: `c: derived` reading `b: derived` reading `a: hash in ns`: all three in P.
  - A `derived` column that reads only unconfigured source columns: only it moves to P.
  - `zz_email: faker(person_email)` with `when: "status == 'active'"`, `status: hash in ns`: the table mixes (`status` in N, `zz_email` in P); the selected rows are the originally active ones, equal to the oracle under WHEN-READS-SOURCE; the `aa_email` rename gives identical output.
  - Mutation: move only the P node and leave its driver in N (the `aa_total` case red).
- **P3 determinism.** Each run first asserts the table ran mixed (`mixed: true` and both backends in `executed_backends`); that assertion is the fail-before. The determinism checks are controls. One mixed table run twice gives identical output bytes and identical `quality_metrics` (minus timings). Chunk size 7,000 versus 40,000 on 120,000 rows gives equal values per column.
- **P4 threads.** `native_threads` 1 versus 4 on a mixed table: identical output bytes. Same fail-before as P3 (the mixed assertion); the byte check is a control.
- **P5 whole-column on full frame.** 2,000 rows: `shuffle` on one column and `hash in ns` on nine. Run end to end through `run_pipeline`, so the call goes `_unified_slice.py:250-252` to `ShadowCoordinator.run` and not to the runner directly. The unified slice admits mixed; a spy shows `dispatch_full_frame_if_applicable` returned `None` and `run_shadow_batches` ran with `deferred_columns`; the nine `executed_backend` values are native and `shuffle` is `pandas_oracle`; the `shuffle` column equals today's oracle output exactly. Mutation: remove the deferred narrowing in `dispatch_full_frame_if_applicable` (the full-frame capture comes back): P5 red, because the nine `hash` columns report `pandas_oracle`. On 120,000 rows the same table still does not chunk and is mixed on full frame. Fail-before: whole table on the oracle.
- **P6 row-count guard.** A P handler stub that drops a row: `HANDLER_ROW_COUNT_CHANGED` from `require_same_rows`. A stubbed half returning `n - 1` rows at the assembler: `HANDLER_ROW_COUNT_CHANGED` naming the half. No output is published on either lane.
- **P7 value-free.** P6 and P14 messages and evidence hold no seeded sentinel value.
- **P8 FK control.** A child table with an FK column and a P column: declined `fk_relationship`, today's route, output unchanged.
- **P9 degenerate chunks and guards.** A 120,000-row mixed table whose last chunk is all-null for the `fpe` and `bucket_perturb` N columns and empty for a P column, plus a zero-row chunk: P1 values, degenerate types per the existing reconciliation. A `code_set` P column whose type drifts in chunk 3: the existing `code_set` schema guard raises, from `oracle_chunk_step`.
- **P10 control: S0 moves.** The auto-chunk, chunked-oracle, B6a and B6b suites pass unchanged on the S0 head. `_chunked_entry.py` and `_dispatch.py` ceilings move down.
- **P11 frozen snapshots.** The artifacts that can change, and how:
  - `tests/fileaccess/route_corpus_golden.json` and `tests/unit/execution/r3_within_route_baseline.json` (both hold `chunked_route` evidence): a table that now mixes gains `mixed: true`, `native_admitted: true` and per-column `executed_backend` values of its half (B3). No other key changes.
  - `tests/snapshots/golden/mask_*/<column>.sha256` (for example `mask_faker_seeded/address.sha256`): a digest changes only for an N column of a table that now mixes, and only through a B1 type pair; its values, compared with `pa.Array.equals` after the B1 cast, are equal.
  - `tests/snapshots/frozen_schemas/run-result.schema.json`: unchanged (it does not pin `quality_metrics` keys).
  Each changed entry is regenerated in the same PR and listed in the PR body against B1 or B3. Any other change blocks.
- **P18 partial N result accepted.** The 2,000-row `shuffle` plus nine `hash in ns` table, through `ShadowCoordinator.run` (not the runner directly): the coordinator with `deferred_columns={t: {shuffle column}}` returns the nine N columns plus passthrough columns, in source order, without the `shuffle` column, and `result.deferred_columns` equals the input. Control: the same call with `deferred_columns=None` on a fully bound table behaves as today. Fail-before: `SCHEMA_DIFF`.
- **P19 missing N column fails closed.** Same table with `deferred_columns` that leaves out one unbound P target: `SCHEMA_DIFF`, naming the table and column names only. Also `SCHEMA_DIFF` when a deferred column is produced (a bound node's target listed as deferred) and when a deferred name is not a source column. No output is published. Mutation: drop the projected N-schema check (accept any produced subset): P19 red.
- **P20 coordinator refusals.** Through `ShadowCoordinator.run` with `deferred_columns` set: a plan with a synthesis stage, a mixed synthesis-plus-mask plan and an `{OUT_OF_CORE}` plan each raise `ShadowDifference(SCHEMA_DIFF)` before any adapter runs (a spy on each dispatch shows no call). A `{FULL_FRAME}` plan with `deferred_columns` set and a `top_code` node not deferred raises `SCHEMA_DIFF` from `dispatch_full_frame_if_applicable`, not a full-frame run. Control: the same plans with `deferred_columns=None` behave as today. Mutation: drop the refusal in branch 2 (P20 red).
- **P12 warnings order.** A mixed table where a P column raises a projection warning and an N `fpe` column raises a residual warning: the merged list is in work order, projection last. Rerun gives the same list.
- **P13 DGRN offset.** `windowed_date` (a DGRN, position-keyed strategy) as the P column on 120,000 rows: chunk size 7,000 and 40,000 give equal output values, and both equal the `--no-native` chunked oracle output. Mutation: `row_offset=0` into `oracle_chunk_step` (red).
- **P14 row error fails closed.** A `date_shift` or `bucketize` P column with an unparseable value in chunk 2 (rows 7,000 to 13,999 at chunk size 7,000): `RowErrorsFailedError` is raised, its summary names chunk 2 and the column (no value), and the output sink publishes no file. Fail-before: today's route raises the same; the test fails before only for the mixed evidence assertion, so it is a guard on the new branch.
- **P15 projection policy error.** A mixed table run with `unconfigured_column_policy: error` and one unconfigured passthrough column: no `undeclared_output_columns` from the P half; the unconfigured column is handled as today. Mutation: build `plan_for_nodes` with a trimmed seed envelope (red).
- **P16 typed P error.** A P handler stub raising `ExecutionError(code=X)` on the unified slice: the run fails with code `X` and its exit, not `unified_slice_unexpected_error` (needs the RLT carve-out).
- **P17 label.** `RouteSummary.executed_backends` for a mixed run holds a native backend and `pandas_oracle`; the CLI card (S3) says `mixed (native and Python columns)`.

Performance (recorded, not a CI gate), on the Dell node with the native companion, three runs each, wall time of today's route against the mixed route:

- **P-bench chunked.** 1,000,000 rows, 9 native columns plus one `faker(address_full)` column (chunked lane). Target: mixed at most 0.5 of today's time.
- **P-bench full frame.** 90,000 rows, the same columns plus one `shuffle` column (full frame, unified slice). Target: mixed at most 0.5 of today's time.
- A result over 0.8 on either run stops S2 and goes to the owner with the profile. The record also counts how many tables in the prod-sim configs mixed and how many columns moved into P as created-column drivers.

Test scope: T0 per edit; T1 impact selection plus the named tests and guard tests; T3 full suite at each merge head (R3, masking route), diffed against the saved main baseline. Mutations: `partition_columns`, `group_drivers_into_python`, `assemble_mixed` (order, row assert), the projected N-schema check in `run_shadow_batches` (P19), the deferred narrowing in `dispatch_full_frame_if_applicable` (P5), the coordinator refusals (P20), `merge_half_warnings`, the `row_offset` passed to `oracle_chunk_step` and the per-column backend evidence, rerun on the final head of S1 and S2.

## 10. Frozen contracts and compatibility

All of these are pre-V1 output or evidence changes under the owner direction of 2026-11-22. Each goes into the changelog fragment as a `Breaking:` line.

- **B1 output types of a mixed table.** Values are unchanged (P1). An N column no longer passes through pandas, so it keeps its native output type where today's pandas route gave another. Allowed type pairs, by source type of an N target column (mixed type first, today's pandas-route type second):
  - `large_string` target: `large_string` from the kernel against `string` on the pandas route (UF-DOMAIN S3 narrows the pandas route; whichever lands first, P1 uses the pair that holds at its head).
  - `date32` or `timestamp` target of `date_shift`: the kernel's declared output type against the pandas route's `timestamp[ns]`, unless DATE-SHIFT-TYPED has landed.
  - nullable integer target of `categorical` or `bucket_perturb`: the kernel's integer type against `double` where the pandas route widened a null-bearing column.
  - The output's pandas schema metadata (`b"pandas"`) can be absent or differ.
  No other pair is allowed; P1 fails on any type pair outside this list. `Breaking: a table with native and Python columns runs each column on its own backend; values are unchanged, but some native columns keep their native Arrow type where the all-pandas run widened it.`
- **B2 warning order.** Merged by work order across halves. `Breaking: warnings of a mixed table are ordered by column work order.`
- **B3 route evidence.** `executed_backend` can be `pandas_oracle` inside an admitted table; new `mixed` keys; `native_admitted` is true for a mixed chunked table. `Breaking: chunked_route and unified_slice_activation report per-column backends for mixed tables.`
- **B4 route choice.** Tables that ran fully on pandas now run partly native. No new public name, no config key, no exit code change.
- Frozen and unchanged: output column order (source order), row order, the per-column seed derivation, the DGRN row offset, the row-error contract, every exit code.
- The assembler's new `python_half` input is internal.
- `RouteSummary` shape: unchanged by this plan.

## 11. Pre-mortem

- **A P handler reads a column it does not declare.** The sub-table lacks it and the adapter fails with a missing column. `frame_columns` is the one read set and P1 includes every P strategy that reads siblings. A strategy that reads an undeclared column is a declaration bug; the fix is to declare the read, not to widen the sub-table.
- **A whole-table step of the adapter behaves differently on the sub-table.** The section 5 table lists each step and why it gives the same result; P1, P12 and P15 check the result. The builder rechecks the table at the head.
- **A read channel that sees masked values is missed.** Under WHEN-READS-SOURCE only created-column drivers read masked values, and they all come from `scalar_creating_reads` through `column_dependency_edges`, the edges the oracle itself orders by. A new creating strategy declares its reads there or the oracle mis-orders it too. P2 covers `derived` and chains of created columns.
- **The S0 moves change behavior.** They are pure moves with the existing suites as control (P10), merged before any mixed code.
- **Many tables have a Python created column with native drivers.** Then those drivers lose the kernel. The benchmark record counts the moved columns for the 1.x interleaved-loop decision.
- **The two halves cost more than one oracle run on narrow tables.** The P half converts only `frame_columns(P)`, which is never more than the whole table. P-bench records both lanes.

## 12. Open questions for the owner

Both answered at plan gate R1 (2026-11-22):

1. **Reads across halves.** Agreed at R1, revised by the owner's WHEN-READS-SOURCE decision: `when:` needs no rule (it reads original values on every route); a Python created column runs together with its drivers in the Python half. The interleaved loop is 1.x.
2. **Benchmark target.** Agreed: mixed at most 0.5 of today's time, recorded on the Dell, not a CI gate, with a full-frame run at 90,000 rows added; over 0.8 stops for the owner's call.

No open questions remain.
