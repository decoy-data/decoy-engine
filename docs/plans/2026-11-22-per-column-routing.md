Status: plan (revision 1, 2026-11-22; not yet reviewed)

# PER-COLUMN-ROUTING: native and Python columns in one table, on the chunked lane and the unified slice

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: PER-COLUMN-ROUTING (CLI `docs/roadmap/groups/run.md:34`, moved from 1.1 into V1 by the owner on 2026-11-22). Three slices: two engine slices, then a small closing slice (CLI end-to-end tests, benchmark record, docs).

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Depends on: ROUTE-LABEL-TRUTH (`docs/plans/2026-11-22-route-label-truth.md`, branch `plan/route-label-truth`) slice 1, for `column_decline_code`, the kernel-less family codes, `RouteSummary.executed_backends` and the CLI `mixed` label row. Slice 1 here starts after that engine slice merges.

Sources: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md` ("A table takes one route"); `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 3 limit 2 and section 6; CLI `docs/roadmap/groups/run.md:34`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `feature-dev.md`, `refactoring.md`, `architecture.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `performance.md`, `api-and-compatibility.md`, `security.md` (value-free evidence), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R3. It changes which code masks which column on the default routes, and output bytes may change (owner direction below). Plan review: Dennis, then Codex. Code gate: Codex and Dennis (`/code-review high`: masking lane). Full suite (T3) at each merge head, and mutations on the core units at the final head.

Owner direction (2026-11-22): V1 must be fast and reproducible. Where a byte-changing design is faster or simpler than a byte-identical one, plan the faster one. Pre-V1 byte changes are allowed. Output must stay deterministic for a given seed or namespace, and each change is marked in section 10 and in the changelog `Breaking:` line. This plan uses that freedom: it does not promise byte parity with today's single-route output. It promises correct values per column, determinism, and chunk-size invariance.

## 1. Frame

Today a table takes one route. `native/_dispatch.py:232` (`_static_route_decision`) decides from every node, and its comment at `:286-291` says it: "never a per-column mix, since a non-admitted table runs 100% on the oracle". The unified slice does the same: `resident_contract_admission` (`execution/_unified_slice_admission.py:410`) declines the table if one node has no binding. So one `faker(address_full)` column puts nine `hash` columns on pandas. The audit lists this as the main reason the default faker, `shuffle`, `geo_generalize` and `formula` tables run slow.

After this change a table whose columns split into a native set and a Python set runs the native set on the kernels and the Python set on the pandas oracle, on the same batch, and splices the results. This is the established design for this problem (section 2).

## 2. Established solutions

Search run: per-operator or per-expression fallback in vectorized engines (Spark Python UDFs, Gluten/Velox, Polars, DataFusion, DuckDB).

- **Spark `ExtractPythonUDFs`.** The optimizer pulls Python UDFs out of a projection into an `ArrowEvalPython` (or `BatchEvalPython`) node. That node sends only the UDF input columns, as Arrow batches, to a Python worker and appends the result columns. The rest of the projection stays in the JVM. Two rules from it are used here: send the Python side only the columns it reads, and splice the results back into the batch.
- **Gluten/Velox.** Fallback is per plan node: the nodes Velox supports run native and the others run on vanilla Spark, with a transition between them. Gluten counts the transitions as a cost. Here a "transition" is one Arrow-to-pandas conversion of the Python columns per batch.
- **Polars.** Expressions in one `with_columns` call all read the input frame, never each other's output, so they can run in parallel. `map_batches` is the escape hatch for Python code. This plan takes the same "read the input" rule for the two halves: a native column and a Python column in one mixed table never read each other's output. A table where they would is not mixed (section 3, item 4).
- **DataFusion and DuckDB.** A scalar UDF gets the input batch's arrays and returns one array of the same length; the engine checks the length. Here the same length check is `require_same_rows` and HANDLER-ROW-COUNT.

No custom scheduler is added. The mixed route reuses the two executors the engine already has: the native chunk masker and the pandas adapter.

### Reuse inventory

- `execution/_pandas_adapter.py:164` `PandasExecutionAdapter.run`: the whole oracle, run on a smaller plan and a smaller table. No per-node extraction is needed.
- `execution/native/_chunk_masking.py:56` `_mask_chunk_native`: the native chunk masker, already column by column, already with `unconfigured` passthrough.
- `execution/physical/_shadow_coordinator.py` and `_shadow_batch_runner.py`: the unified slice's native executor; an unbound node is already skipped (`continue`).
- `execution/_runner.py:354` `column_dependency_edges` and `:380` `order_work`: the one source of "which node reads which masked column".
- `execution/_chunked_oracle.py:387` `_oracle_masked`: the per-chunk oracle loop, with its per-chunk guards and the DGRN row offset.
- `execution/native/_route_decline_codes.py`: decline records and (after ROUTE-LABEL-TRUTH) `column_decline_code`.
- `execution/native/_chunked_evidence.py:116` `executed_backend`: the per-column backend vocabulary.
- `execution/_gated_string_guard.require_same_rows` and `reasons.runtime.HANDLER_ROW_COUNT_CHANGED`.

## 3. Guarantee and non-goals

After this plan:

1. **Partition.** One function, `partition_columns(plan, table, native_ok) -> ColumnPartition | RouteDeclineRecord`, splits a table's mask nodes into a native set N (nodes the lane's existing per-column checks admit) and a Python set P (the rest). `native_ok` is the lane's own per-node verdict: `_static_route_decision` for the chunked lane, `execution_binding_for_slice_node` for the unified slice. The partition adds no new admission rule.
2. **When a table is mixed.** A table runs mixed when N and P are both non-empty and the table has no table-wide decline. If P is empty, the table runs today's native route. If N is empty, it runs today's route for P (the chunked oracle or the full-frame oracle). Table-wide declines (FK, validators, vault, quarantine and the others) still send the whole table to today's route.
3. **Execution of one batch** (a chunk on the chunked lane, the whole table on the unified slice):
   - N runs on the native executor over the batch, with every P target column passed as `unconfigured`.
   - P runs on `PandasExecutionAdapter.run` with `plan_for_nodes(plan, P)` (a plan holding only the P nodes and their edges) and a sub-table of the P target columns plus every column a P node reads. All of these come from the original batch.
   - The output table has the source schema's column order. Each column comes from N's output, P's output or the source (unconfigured passthrough). The splice checks that both halves returned `batch.num_rows` rows; a mismatch raises `HANDLER_ROW_COUNT_CHANGED` naming the half and the table. `require_same_rows` still guards each P node inside the adapter.
4. **No reads across halves.** If `column_dependency_edges` has an edge between an N node and a P node in either direction (a `when:` on a P column that reads an N column, a `formula` reading an N column, a `group_key` on an N column grouped by a P column), the table is not mixed. It records `per_column_cross_dependency` (a new registered code) naming the first such P column in work order, and runs today's route. SOURCE-read drivers (`joint_mask` `key_by`) have no edge and read the original value, which is what the sub-table holds. So `when:` order dependence cannot change any value: inside P the adapter keeps its own work order, inside N the native admission already refuses a gate that reads a masked column (`when_reads_masked_column`), and nothing reads across.
5. **Chunked lane.** P is allowed only when the chunked oracle would accept every P node per chunk today (the existing chunked compatibility preflight in `_chunked_oracle._oracle_preflight`). Whole-column families (`shuffle`, `geo_generalize`, `derived_aggregate`, `grouped_series` and an aggregate `formula`) are not row-local, so their table still does not chunk, as today.
6. **Unified slice (full frame).** P may hold any strategy, including whole-column families: the adapter runs them over the full column, exactly where they run today. So a full-frame table with `shuffle` on one column and `hash` on nine runs the nine through the kernels and `shuffle` through the oracle over the whole column.
7. **Values.** For every column, the mixed output value equals the value today's route for that column's half produces: an N column equals the native single-route output for that column, and a P column equals today's oracle output for that column. Values are compared after a cast to the output schema. Byte-level differences (Arrow type metadata, pandas schema metadata, warning order, row-group layout) are allowed and listed in section 10.
8. **Determinism.** The same config, seed and namespace give the same output bytes on rerun, for any `native_threads`, and the same values for any chunk size.
9. **Warnings.** The warnings of both halves are merged into one list, ordered stably by the canonical work-order index of the node that raised them (`_runner.in_work_order`). Projection warnings come last, as today.
10. **Evidence.** Each column's `executed_backend` is its half's backend: a P column records `pandas_oracle`, an N column its native backend. `chunked_route` and `unified_slice_activation` gain `mixed: true` for a mixed table. `RouteSummary.executed_backends` then shows both, and the CLI prints `mixed (native and Python columns)` (row already added by ROUTE-LABEL-TRUTH).

Non-goals: a single work-order loop that interleaves N and P nodes (it would allow cross-half reads, at the cost of a per-node conversion; 1.x if the cross-dependency decline shows up in real configs); native kernels for any kernel-less family; mixing on FK, sequential, out-of-core, multi-table split or mixed-route FK tables; parallel execution of the two halves (they run one after the other; Python holds the GIL anyway); any change to which columns the native checks admit.

## 4. Enumerations

### Exit paths

- Row-count mismatch at the splice: `HANDLER_ROW_COUNT_CHANGED` (existing code), message names the half (`native` or `python`) and the table, never a value. Exit 3.
- A P node failure inside the adapter: the same error the oracle raises today, for the same node.
- An N column failure: the same error the native lane raises today.
- Row errors: the adapter's row errors for P columns, the native `format_errors` for N columns. On the chunked lane both keep today's chunk-local positions (`_chunk_masking.py` docstring: not rebased); the plan does not change the row-error contract.
- The cross-dependency decline is not an error: the table runs today's route.

### Routes

- Chunked lane (auto-chunk single table, and each table of the multi-table split): mixed when item 2 holds and item 5 allows P. Decided in `native/_dispatch.py:232`, run in the chunk loop at `native/_chunked_entry.py:318`.
- Unified slice, full frame, one non-FK resident mask table: mixed when item 2 holds. Entered at `execution/_pipeline_full_frame.py:171`; partition in `execution/_unified_slice_admission.py:410`.
- Full-frame oracle, FK route, sequential route, out-of-core route: unchanged.
- `--chunked` CLI runs and `run_mask_pipeline_chunked`: unchanged (no native admission there).

### FK shapes

N/A: a table in any declared relationship is declined table-wide before partition (`_dispatch.py:255`, `fk_relationship`), on both lanes.

### Fields

- `quality_metrics["chunked_route"]["mixed"]` and `quality_metrics["unified_slice_activation"]["mixed"]` (new booleans).
- `executed_backend` per column now takes `pandas_oracle` for a P column inside an admitted table.
- New reason code `per_column_cross_dependency`.

### Output surfaces

- Masked output tables of a mixed table: values per column as item 7, bytes may change (section 10).
- `quality_metrics` route evidence and warnings list (order per item 9).
- `RouteSummary.executed_backends` and the CLI run card label (`CLI:src/decoy/_native_gate.py` `classify_route`, after ROUTE-LABEL-TRUTH).

## 5. Slices and size

### Slice 1: engine, partition, splice and the chunked lane

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/pipeline/_column_partition.py` (new) | 0 | `ColumnPartition`, `partition_columns`, `plan_for_nodes`, the cross-dependency check | about 150 |
| `execution/pipeline/_mixed_columns.py` (new) | 0 | `run_python_half` (sub-table and adapter call), `splice_halves` (schema order, row check, warning merge) | about 160 |
| `execution/native/chunked/_oracle_route.py` (new) | 0 | `_oracle_route` moved out of `_chunked_entry.py` unchanged, to make room (preparatory move, own commit) | about 70 |
| `execution/native/_chunked_entry.py` | 689 (ceiling 689) | minus `_oracle_route`; a mixed branch in the chunk loop that calls `_mask_chunk_native` for N and `_mixed_columns` for P; ceiling ratchets down | about 650 |
| `execution/native/_dispatch.py` | 679 (ceiling 688) | the "never a per-column mix" pass calls `partition_columns`; the decision carries the partition | at most 688 |
| `execution/native/_chunked_evidence.py` | 291 | `executed_backend` reads the column's half; `mixed` flag | about 305 |
| `reasons/route/_slice.py` (from ROUTE-LABEL-TRUTH) | about 130 | `per_column_cross_dependency` | +6 |

Also: `GUARDED_MODULES` in `tests/sentry/test_physical_seam_disconnection.py` gains both new `pipeline/` modules; the module-size census moves `_chunked_entry.py` down; a changelog fragment with the `Breaking:` lines.

Size target: about 450 source lines (70 of them moved), about 700 test lines.

### Slice 2: engine, the unified slice

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/_unified_slice_admission.py` | about 540 after ROUTE-LABEL-TRUTH | `resident_contract_admission` returns a physical table for N plus the partition, instead of declining on the first unbound node | about 570 |
| `execution/_unified_slice.py` | about 480 after ROUTE-LABEL-TRUTH | `_execute_admitted` runs the coordinator over N, then `run_python_half` over P, then `splice_halves` | about 515 |
| `execution/_unified_slice_evidence.py` | 246 | P nodes get node evidence with `executed_backend = pandas_oracle`; `mixed` flag | about 270 |
| `execution/physical/_shadow_batch_runner.py` | 350 | none: the unbound-node `continue` already skips P nodes; a test pins it | 350 |

Size target: about 120 source lines, about 500 test lines.

### Slice 3: closing (CLI test PR plus engine docs)

- `CLI:tests/e2e/test_run_native.py`: the `mixed` label end to end (no CLI source change).
- `docs/execution-backends.md`: a "Mixed tables" section (what mixes, what declines, the cross-dependency rule).
- `docs/records/2026-12-xx-per-column-routing-bench.md`: the benchmark record (P3).
- The CLI engine pin bump with the repin checklist, if not already done by a release train.

Size target: about 150 lines, docs and tests only.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_column_partition.py` | `src/decoy_engine/execution/pipeline/` | "Pipeline spine and routes": new route modules go in `execution/pipeline/` (`execution/` is frozen at 103 direct modules) | `_routing_facts.py`, `_route_summary.py` |
| `_mixed_columns.py` | `src/decoy_engine/execution/pipeline/` | same | same |
| `_oracle_route.py` | `src/decoy_engine/execution/native/chunked/` | "New native modules go in `execution/native/draw/` or `native/chunked/`" (`native/` is frozen at 55) | `_core.py` |
| `test_column_partition.py`, `test_mixed_columns.py` | `tests/unit/execution/pipeline/` | engine execution tests, existing subpackage | `test_native_fallback_notice.py` |
| `test_mixed_chunked.py`, `test_mixed_unified_slice.py` | `tests/unit/execution/native/` and `tests/physical/` | existing lane test homes | the auto-chunk and slice parity tests |
| `test_mixed_properties.py` | `tests/property/` | Hypothesis property tests | existing property suites |

Fan-out after both plans: `execution/pipeline/` 16 + 1 (ROUTE-LABEL-TRUTH) + 2 = 19 of 25; `execution/native/chunked/` 1 + 1 = 2. No package passes its cap. No new sub-package.

## 7. Design notes

- **Principles.** Single responsibility at the seam: the partition decides, the two existing executors execute, the splice assembles. No executor learns about the other. Open/closed: a strategy that gets a kernel later moves from P to N by the existing operator registry, with no change here.
- **Pattern.** Spark `ArrowEvalPython` (only the read columns go to Python; results are spliced) and the Polars "read the input" rule for independence (section 2).
- **One place per fact.** "Which node reads which masked column" comes only from `column_dependency_edges`. "Is this node native" comes only from the lane's existing check, passed in as `native_ok`. Column order comes only from the source schema. Warning order comes only from `in_work_order`.
- **Choke point.** `splice_halves` is the one place a mixed table's output is built, on both lanes. Guard: a sentry test that the chunked entry and the unified slice reach `splice_halves` for a mixed table (spy), and that no other module in `execution/` builds a table from both a native result and an adapter result (AST check for calls to both `_mask_chunk_native` or the coordinator, and `PandasExecutionAdapter.run`, in one function other than the two sanctioned callers). Mutation: inline a second splice in `_chunked_entry.py` (guard red).
- **House style.** `ColumnPartition` is a frozen dataclass (native nodes, python nodes, python read columns); no flag arguments; `run_python_half` takes the partition, not loose lists.
- **Why not one interleaved loop.** It would need the oracle split into a per-node session, a pandas conversion per Python node, and a native-to-pandas value hand-off. It is slower and adds a third executor. The two-half design reuses both executors whole and is the faster option the owner direction asks for. The price is the cross-dependency decline, which keeps today's route for those tables.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | splice errors, decline record, evidence | messages name half, table and column only; record is code and identifiers | P7 | add the row count's first differing value to the message (P7 red) |
| 2 | Cleanup missing on an exit path | chunked lane failure mid-stream | unchanged: the existing output sink owns publish and discard; the mixed branch raises before yield | P6 | n/a |
| 3 | State and concurrency | native threads | each half runs in turn; native threads apply to N only | P4 | n/a |
| 4 | Route parity and silent fallback | partition, cross-dependency, splice | values per column equal each half's route (property); cross-dependency declines with a code | P1, P2, P5 | drop the reverse-direction edge check (P2 red); swap two columns in the splice (P1 red) |
| 5 | Referential integrity | FK tables | declined table-wide before partition | P8 | remove the FK check order (P8 red) |
| 6 | Untrusted producer | adapter result for P | row count checked at the splice; column set checked against P targets | P6 | skip the row check (P6 red) |
| 7 | Check then use | partition decided once, executed per chunk | the decision object carries the partition; per-chunk schema gates (`_oracle_masked` guards) still run for P columns | P9 | n/a |
| 8 | Weak tests | value parity only on easy data | Hypothesis over nulls, empty chunks, all-null chunks, degenerate fpe and bucket_perturb types, `when:` gates | P1 | n/a |
| 9 | Refactor drift | `_oracle_route` moved | moved unchanged; existing auto-chunk tests are the control | P10 | n/a |
| 10 | Frozen contract drift | output bytes, warning order, evidence | listed in section 10 with `Breaking:` lines; frozen snapshots regenerated and reviewed | P11 | n/a |
| 11 | Determinism | seeds, chunk size, threads | per-column seeds unchanged; halves are pure per batch | P3, P4 | seed P with a per-chunk counter (P3 red) |

## 9. Acceptance tests

Each fails before the change unless marked control. "Mixed table" below means 9 native columns (`hash in ns` on strings, `categorical`, `date_shift`, `redact`) and at least one Python column.

- **P1 value property (Hypothesis).** Random mixed tables: column types from the admitted set, nulls, empty strings, the P column from `faker(address_full)`, `bucketize`, `top_code`, `code_set`, `formula` row-wise, `when:` on a P column reading another P column. For each column, the mixed output equals the reference after a cast to the output schema: N columns against a run with only the N columns configured on the native route, P columns against a run on the oracle route (`DECOY_ENGINE_NO_NATIVE` path). Column order equals the source schema. Fail-before: the table runs one route, so the N columns do not come from kernels (asserted by evidence) and the test's evidence check fails.
- **P2 cross-dependency.** `email: faker(person_email)` with `when: "status == 'active'"` and `status: hash in ns`: the table is not mixed, records `per_column_cross_dependency` naming `email`, and output equals today's route byte for byte. Same for the reverse direction (`group_key` on an N column grouped by a P column) and for `formula` reading an N column. Control for bytes, fail-before for the code.
- **P3 determinism.** One mixed table run twice gives identical output bytes and identical `quality_metrics` (minus timings). Chunk size 7,000 versus 40,000 on 120,000 rows gives equal values per column.
- **P4 threads.** `native_threads` 1 versus 4: identical output bytes.
- **P5 whole-column on full frame.** 2,000 rows: `shuffle` on one column and `hash in ns` on nine. The unified slice admits mixed; the nine `executed_backend` values are native, `shuffle` is `pandas_oracle`; the `shuffle` column equals today's oracle output byte for byte (same full column, same seed). On 120,000 rows the same table still does not chunk (route full frame) and is mixed there. Fail-before: full table on the oracle.
- **P6 row-count guard.** A P handler stub that drops a row: `HANDLER_ROW_COUNT_CHANGED` from the adapter's `require_same_rows`. A stubbed half that returns `n - 1` rows at the splice: `HANDLER_ROW_COUNT_CHANGED` naming the half. No partial output is published on the chunked lane (the sink discards).
- **P7 value-free.** P6 and P2 messages and evidence hold no seeded sentinel value.
- **P8 FK control.** A child table with an FK column and a P column: declined `fk_relationship`, today's route, output unchanged.
- **P9 degenerate chunks.** A 120,000-row mixed table whose last chunk is all-null for the `fpe` and `bucket_perturb` N columns and empty for a P column, and a zero-row chunk: values per column as P1, output types per the existing degenerate-type reconciliation.
- **P10 control: move.** The auto-chunk suites (`tests/unit/execution/test_auto_chunk_*`) pass unchanged after the `_oracle_route` move, before the mixed branch lands.
- **P11 frozen snapshots.** Any frozen-shape snapshot or golden output that changes is regenerated in the same PR and each change is listed in the PR body against section 10.
- **P12 warnings order.** A mixed table where a P column raises a projection warning and an N `fpe` column raises a residual warning: the merged list is in work order, projection last. Rerun gives the same list.
- **P13 label.** `RouteSummary.executed_backends` for a mixed run holds a native backend and `pandas_oracle`; the CLI card (slice 3) says `mixed (native and Python columns)`.

Performance (recorded, not a CI gate):

- **P-bench.** 1,000,000 rows, 9 native columns plus one `faker(address_full)` column, Dell node, native companion installed, three runs each. Record the wall time of today's route (whole table on the oracle) and the mixed route. Target: the mixed route at most 0.5 of today's time. A result over 0.8 stops slice 3 and goes back to the owner with the profile.

Test scope: T0 per edit; T1 impact selection plus the named tests and guard tests; T3 full suite at each merge head (R3, masking route), diffed against the saved main baseline. Mutations: `partition_columns`, the cross-dependency check, `splice_halves` (order, row check, warning merge) and the per-column backend evidence, rerun on the final head of each slice.

## 10. Frozen contracts and compatibility

All of these are pre-V1 byte or evidence changes under the owner direction of 2026-11-22. Each goes into the changelog fragment as a `Breaking:` line.

- **B1 output bytes of a mixed table.** Values per column are unchanged (P1). Bytes can change in type metadata, because N columns no longer pass through pandas: for example the pandas schema metadata on the output, and the Arrow type of an N column that the pandas round trip used to widen. `Breaking: a table with native and Python columns runs each column on its own backend; values are unchanged, but output type metadata can differ from the all-pandas run.`
- **B2 warning order.** Merged by work order across the halves. `Breaking: warnings of a mixed table are ordered by column work order.`
- **B3 route evidence.** `executed_backend` can be `pandas_oracle` inside an admitted table; new `mixed` keys; `native_admitted` is true for a mixed chunked table. `Breaking: chunked_route and unified_slice_activation report per-column backends for mixed tables.`
- **B4 route choice.** Tables that ran fully on pandas now run partly native. No new public name, no config key, no exit code change.
- Frozen: the output column order (source schema order), row order, the per-column seed derivation, the row-error contract, every exit code.
- `RouteSummary` shape: unchanged by this plan (members added by ROUTE-LABEL-TRUTH).

## 11. Pre-mortem

- **A P handler reads a column it does not declare.** Then the sub-table lacks it and the adapter fails with a missing column. The sub-table takes every column `_masked_driver_columns` and the SOURCE-read drivers name; P1 includes every P strategy that reads siblings. If a strategy reads undeclared columns, that is a declaration bug the oracle would have hidden. The fix is to declare the read in the strategy, not to widen the sub-table.
- **The adapter does whole-table work that a sub-table changes.** For example `apply_degenerate_faker_pin`, `untouched_columns`, `lossless_int_columns` or `enforce_output_projection` look at the full table. Each is run against the sub-plan; P1 compares values, and P11 catches a changed warning. The builder lists every whole-table step in `PandasExecutionAdapter.run` at DEVELOP and states for each why the sub-table gives the same value.
- **A strategy whose seed or behavior depends on the set of masked columns** (a key derived from the table's column list). P1 would show it. Per-column seeds come from `derive_key` by table and column, which does not change.
- **The chunked entry cannot fit.** `_chunked_entry.py` is at its ceiling. The `_oracle_route` move frees about 60 lines first; if the mixed branch still does not fit, more of the chunk loop moves to `native/chunked/`. The ceiling is never raised.
- **Cross-dependency is common in real configs** (many `when:` gates read a `hash` column). Then fewer tables mix. Slice 3's benchmark config set includes the prod-sim configs and records how many tables mixed, so the owner can judge the 1.x interleaved loop.
- **The two halves cost more than one oracle run on narrow tables** (one native column, one Python column, few rows). The unified slice only runs under the full-frame size limit, and the chunked lane converts only P columns per chunk, so the cost is lower than today's full conversion. P-bench records it.

## 12. Open questions for the owner

1. **Cross-dependency.** Recommended: in V1, a table where a native column and a Python column read each other's masked value is not mixed (coded `per_column_cross_dependency`, today's route). The interleaved loop that handles it is 1.x. Confirm.
2. **Benchmark target.** Recommended: the mixed route at most 0.5 of today's time on the P-bench table, recorded on the Dell, not a CI gate; over 0.8 stops for your call. Confirm the numbers.
