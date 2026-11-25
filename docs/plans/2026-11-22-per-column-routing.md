Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `feature-dev.md`, `refactoring.md`, `architecture.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `performance.md`, `api-and-compatibility.md`, `security.md` (value-free evidence), `documentation.md`, `workspace-and-vcs.md`, `profiles/local-operations.md` (extract refresh, 2026-11-25); engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Status: plan (revision 7, 2026-11-25; Dennis fix round 1, section 13)

# PER-COLUMN-ROUTING: native and Python columns in one table, on the chunked lane and the unified slice

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: PER-COLUMN-ROUTING (CLI `docs/roadmap/groups/run.md:28`, moved from 1.1 into V1 by the owner on 2026-11-22). Four slices: S0 preparatory moves (no behavior change), S1 chunked lane, S2 unified slice with docs and benchmark record, S3 a CLI test-only PR.

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3); anchors refreshed to `origin/main` `393f0d47c` (0.28.4) on 2026-11-25. Line numbers are at `393f0d47c` unless marked (see "Changes in this extract").

## Changes in this extract

Extract of engine branch `plan/per-column-routing` (`a17633567`, revision 6), refreshed 2026-11-25 for the loop's install. Wording, guarantees, slices and tests are unchanged. Only anchors, line counts, the UF-DOMAIN dependency line (now partly merged) and the notes in this section changed. The "Rules consulted" line moved to the top of the file.

### Merged-state check (2026-11-25)

- Engine: no PER-COLUMN-ROUTING slice is merged or open (`gh pr list --state all`, `git log origin/main`). The only related merge is engine PR 351 (2026-10-31), the ungated concept doc this plan replaces. Main is `393f0d47c` (0.28.4). Nothing this plan adds (`partition_columns`, `oracle_chunk_step`, `deferred_columns`, `python_half`, `mixed` evidence) exists on main.
- CLI: no PER-COLUMN-ROUTING slice is merged or open. The roadmap row is `docs/roadmap/groups/run.md:28` (was `:34`), status IN REVIEW, depends on WHEN-READS-SOURCE and ROUTE-LABEL-TRUTH. `CLI:src/decoy/_native_gate.py` has no `mixed (native and Python columns)` label yet; ROUTE-LABEL-TRUTH slice 2 adds it.
- WHEN-READS-SOURCE: S1 merged (engine PR 769). S2 is engine PR 783, open, head `2764361b4`, which already contains main.
- ROUTE-LABEL-TRUTH: plan in review (`plan/route-label-truth`, revision 3.3). Its slice 1 is now three engine PRs: 1a (A1, A6), 1b (decline codes, `column_decline_code`, `RouteSummary.executed_backends`), 1c (the A5 carve-out). Slice 2 is the CLI PR that pins engine 0.28.5 and adds the `mixed` label row.
- UF-DOMAIN: S1 merged (engine PR 770, `3426165fb`, 2026-11-24). The assembler moved out of `execution/_fk_keys.py` into `execution/pipeline/_source_types.py:90` (UF-DOMAIN amendment A2.1). `frame_columns` is UF-DOMAIN S2 work (its section 5 table), not on main, and S2 has no PR. The frame-columns text this plan asked UF-DOMAIN to carry is in its guarantee 3 since `d621db2f1`. The CLI roadmap `mask.md:18` still says "S1 building"; that row is stale.

### Review history already passed

Dennis round 1 and round 3 items closed (`75349f9c3`, `92732daed`), rebased on WHEN-READS-SOURCE (`33f6b93a7`), Codex R1 HIGH and Codex R2 closed (`8b74b74d9`, `a17633567`), all 2026-11-22. This extract adds no design change, so it needs no new design round; the gate only checks the refreshed anchors and the start order below. Dennis R1 on this extract (2026-11-25) gave GO-WITH-FIXES; revision 7 closes it in place (section 13). Those fixes change the guard input of `oracle_chunk_step`, the assembler's column rule, the `frame_columns` placement and the S1 module split.

Risk tier: the brief names R2; the plan itself says R3 (it changes which code masks which column on the default routes, and output bytes can change). Recommended: keep the R3 gates as written (T3 at each merge head, mutations on the final head of S1 and S2). Recorded as an owner question in [[OWNER-QUESTIONS]].

### WHEN-READS-SOURCE: what this plan still carries for it

No code. The roadmap note "the `when:` order dependence goes away with WHEN-READS-SOURCE" holds: guarantee 4 has no `when:` rule, the plan records no `when_reads_masked_column` decline, and `frame_columns` already reads `when:` columns at phase `source`. What remains are acceptance tests that only pass on a main holding PR 783: P1 (a `when:` on a P column reading another P column) and P2 case 4 (`zz_email` gated on an N column). So S1 waits for PR 783 to merge. PR 783 also edits `pipeline/_source_types.py` (+13), `_column_access.py`, `_runner.py`, `_pandas_adapter.py` and `_chunked_carry.py` (`untouched_columns` now reads `work_order.resolve_operations`). On PR 783's head `column_dependency_edges` is at `_runner.py:433`, `column_access` at `_column_access.py:388` and `scalar_creating_reads` at `:424`; `column_dependency_edges` keeps its meaning (masked-driver edges only). S1 rereads these anchors at its branch base.

### Start order against the dependencies

| Slice | May start (branch, write tests) | Must not merge before | Why |
|---|---|---|---|
| S0 moves | now | ROUTE-LABEL-TRUTH 1b | 1b edits the `_dispatch.py` node loop (`:335-336`, `:345-346`) that S0 moves into `native/chunked/_route_scan.py`; the RLT plan asks for this order. S0 needs nothing from WHEN-READS-SOURCE or UF-DOMAIN. |
| S1 chunked lane | after S0 merges | WHEN-READS-SOURCE S2 (PR 783), RLT 1b; UF-DOMAIN S2 only while it still owns `frame_columns` | PR 783: the `when:` contract and the assembler edit; RLT 1b: `column_decline_code`, `executed_backends`. `frame_columns`: if UF-DOMAIN S2 has merged it in `execution/_column_access.py` when S1 reaches DEVELOP, S1 reuses it; otherwise S1 builds it there (fallback in "Depends on") and the UF-DOMAIN S2 dependency drops. RLT 1c is not needed on the chunked lane (no wrapper there). |
| S2 unified slice | after S1 merges | RLT 1c, EXPECT-OFF-ROUTE S2 (PR 812) | 1c: the A5 carve-out P16 needs; PR 812 edits `_unified_slice.py`, `_unified_slice_admission.py`, `_shadow_coordinator.py` and `_shadow_full_frame.py`. Recommended: PR 812 merges first and S2 rebases on it. |
| S3 CLI test | after RLT slice 2 merges | the engine release that holds S2 | the `mixed` label row comes from RLT slice 2; the test rides the repin. |

Release: engine S0, S1 and S2 each ship on the first engine train after they merge (after 0.28.5, which RLT 1c takes). S2 carries the `Breaking:` lines of section 10. CLI S3 ships in CLI 1.0.0 (V1), or 1.0.0-rc.1 if it lands before mid-December.

### Overlap with other rows (do not edit the same files at once)

- **ROUTE-LABEL-TRUTH** (`plan/route-label-truth`): shares `native/_dispatch.py`, `native/_route_decline_codes.py`, `native/_chunked_evidence.py`, `_unified_slice.py`, `_unified_slice_admission.py`, `pipeline/_route_summary.py`. Order: RLT 1a, 1b before S0; 1c before S2.
- **GEN-PER-COLUMN** (`plan/gen-per-column`): generation lane only (`generation/stream/`, `reasons/route/_generation.py`). It cites `_pipeline_full_frame.py`, which this plan cites but does not edit. No shared file; can run at the same time.
- **NONFK-OOM S5** (engine PR 816): edits `docs/execution-backends.md` and `docs/compatibility-contract.md`. S2 adds a "Mixed tables" section to `docs/execution-backends.md`. PR 816 is open now and S2 is far behind, so S2 rebases on it; no code overlap.
- **RUN-STREAM E6** (building): `profile/_lazy_build.py`, `profile/_csv_reader.py`, `run_result/_model.py`, `run_result/_build.py`, `docs/compatibility-contract.md`. No shared file. CLI side: RUN-STREAM S1/S2 touch `CLI:src/decoy/cli/run/`; S3 here is test-only in `CLI:tests/e2e/test_run_native.py`.
- **EXPECT-OFF-ROUTE S2** (engine PR 812, open): shares `_unified_slice.py`, `_unified_slice_admission.py`, `physical/_shadow_coordinator.py`, `physical/_shadow_full_frame.py` and `_pipeline_full_frame.py` with S2. No overlap with S0 or S1.
- **WHEN-READS-SOURCE S2** (engine PR 783): shares `pipeline/_source_types.py`, `_column_access.py`, `_runner.py`, `_pandas_adapter.py`, `_chunked_carry.py`, `native/_chunked_schema_rule.py` with S1 (read or one-input edit). S1 waits for it.

### Anchors that moved (old at `70881ad79`, new at `393f0d47c`)

| Anchor | Old | New |
|---|---|---|
| CLI roadmap row | `run.md:34` | `run.md:28` |
| `_static_route_decision` | `native/_dispatch.py:232` | `:233` |
| "never a per-column mix" comment | `:286-291` | `:283-288` (old cite was two lines off) |
| node loop S0 moves | `:283-389` | `:283-346` (old range ran into `NativePreflight`; the loop ends before `native_admitted` on `:348`) |
| FK table-wide decline | `:255` | `:262-267` |
| catch-all swallow | `_unified_slice.py:358` | `:369-371` |
| coordinator call | `_unified_slice.py:250-252` | `:254-256` |
| complete-table path | `_unified_slice.py:289-295` | `:294-304` |
| output assembler | `_fk_keys.py:521` | `pipeline/_source_types.py:90` (moved by UF-DOMAIN S1) |
| `column_access` reads section | `_column_access.py:142-200`, `:362` | `:144-211`, `:373` |
| `OWN_TARGET_CREATES` declarations | `:329-335` | `:340-346` |
| `scalar_creating_reads` | `:391` | `:402` |
| `PandasExecutionAdapter.run` | `_pandas_adapter.py:164`, `:164-330` | `:167`, `:167-350` |
| adapter steps | `:200-202`, `:233`, `:238`, `:296-303`, `:311`, `:317`, `:319-322` | `:203-205`, `:236`, `:241`, `:299-306`, `:314`, `:320`, `:322-335` |
| oracle per-chunk body | `_chunked_oracle.py:407-505`, `:490-503` | `:406-504`, `:489-502` |
| `_oracle_route` | `_chunked_entry.py:119-180` | `:113-176` |
| chunk loop native call | `_chunked_entry.py:318` | `:310` |
| `build_schema_rule`, oracle `on_chunk`, native normalize | `:556`, `:149`, `:394` | `:554`, `:143`, `:386` |
| `_validate_native_threads` | `:100` | def `:98`; its `code=` still at `:100` (the f29 fixture line) |
| `executed_backend` | `_chunked_evidence.py:116` | `:120` (old cite was three lines off) |
| `normalize_chunk` | `_chunked_schema_rule.py:321` | `:336` (old cite pointed into the previous function) |
| module-size baseline | `module-size.json:50`, `:53` | `:47`, `:50`; ceilings `test_module_size.py:113` (689), `:116` (688) |
| secret census | `secret-material-census.json:118` | `:121` |
| line counts | `_chunked_entry.py` 689, `_dispatch.py` 679, `_chunked_evidence.py` 291, `_unified_slice_evidence.py` 246, `_fk_keys.py` 575 | 688, 683, 292, 226; assembler file `pipeline/_source_types.py` 182 |
| `execution/pipeline/` fan-out | 16 | 18 (`_resident_bytes.py`, `_source_types.py` added); after RLT and this plan 21 of 25 |

Unchanged at `393f0d47c`: `_unified_slice_admission.py` (`:410`, `:470`), `_pipeline_full_frame.py:171`, `_runner.py:354`, `_output_projection.py`, `_chunked_carry.py` (`:64-81`, `:84-120`), `native/_chunk_masking.py:56`, `native/_route_decline_codes.py`, every `physical/` file cited (`_shadow_batch_runner.py`, `_shadow_coordinator.py`, `_shadow_full_frame.py`, `_shadow_result.py`, `_shadow_mixed.py`, `_shadow_diff_codes.py`), `tests/sentry/test_physical_seam_disconnection.py`, `lossless-int-columns.json:5`, `gcs-call-kwargs.json:62`, `:141`. Engine `_chunked_oracle.py` is still 600 lines.

Depends on, before S1 starts:

- **ROUTE-LABEL-TRUTH slice 1** (`docs/plans/2026-11-22-route-label-truth.md`, branch `plan/route-label-truth`): `column_decline_code`, `PhysicalNode.decline_code`, the kernel-less family codes, `RouteSummary.executed_backends`, the CLI `mixed` label row, and the A5 carve-out (guarantee 8 there). The carve-out matters here: an oracle error raised by the Python half inside the unified slice is a `DecoyError` and must keep its own code and exit. Without the carve-out, `_unified_slice.py:369-371` would swallow it and rerun the table.
- **WHEN-READS-SOURCE** (`docs/plans/2026-11-22-when-reads-source.md`, branch `plan/when-reads-source`): every route evaluates a `when:` on the original values of the columns it names (its guarantee 1). With that contract, a `when:` on a Python column reads the same values from the sub-table as from the full oracle run, whatever the other half masked, so this plan needs no `when:` handling across halves. It also removes the native `when_reads_masked_column` decline, so more `when:` columns land in N.
- **UF-DOMAIN S1 and S2** (`origin/plan/uf-domain` at `e90eeed05`, `docs/plans/2026-11-22-uf-domain.md` section 5): the one output assembler, `table_from_pandas_keeping_source_types` (S1, merged as engine PR 770; now `execution/pipeline/_source_types.py:90` per UF-DOMAIN amendment A2.1) widened to take the source table and `arrow_columns`; and `frame_columns(nodes, config, table)` (S2, not on main), the one definition of which columns a set of nodes reads. This plan adds one input to that assembler and calls `frame_columns` for the Python half. It adds no assembler of its own.
  - **Stated dependency on `frame_columns` (to be carried into UF-DOMAIN, not edited here).** UF-DOMAIN S1 at `cb4edf11d` defines a frame column as a non-passthrough target, a `group_key` `group_by` sibling or a `when:` read. The Python half needs the full read set, so `frame_columns` must be: "`frame_columns(nodes, config, table)` returns, in source order, the target columns of `nodes` plus every column in `column_access(entry).reads` for each node's config entry (`execution/_column_access.py:144-211`; `column_access` at `:373`). This covers `group_key` `group_by` siblings, `when:` reads (phase `source`, WHEN-READS-SOURCE guarantee 9), `joint_mask` `key_by`, `date_shift` `group_by` and `derived` expression references. If any node's access is `reads_unknown`, it returns every column of the batch." The unified slice's resident frame keeps its own narrower rule only if UF-DOMAIN chooses to; this plan needs only the full read set for the Python half. (Since `d621db2f1` UF-DOMAIN guarantee 3 carries this text word for word.)
  - **Where `frame_columns` lives, and the fallback (fix round 1, M1).** `frame_columns` goes in `execution/_column_access.py`, next to `column_access` (`:373`), not in `execution/_unified_slice_resident_types.py` (UF-DOMAIN plan line 123). That module is in `DELIBERATELY_CONNECTED_MODULES` (`tests/sentry/test_physical_seam_disconnection.py:148`), so the chunked lane's `pipeline/` modules would gain a sideways dependency on a module allowed to import the physical seam. Request to UF-DOMAIN (carried in its plan by its author, not edited here): place `frame_columns` in `_column_access.py`. `_column_access.py` is 544 lines; `frame_columns` adds about 25, so it stays under 600. Start rule (matches the start-order table): S1 may branch and write tests once S0 merges. Fallback: if UF-DOMAIN S2 has not merged `frame_columns` when S1 reaches DEVELOP, S1 builds it in `_column_access.py` with the guarantee 3 text above and its own unit test (`tests/unit/execution/test_column_access.py`, the read-set cases: `group_key` siblings, `when:` reads, `joint_mask` `key_by`, `date_shift` `group_by`, `derived` references, `reads_unknown` gives the whole batch), and UF-DOMAIN S2 reuses it. Either way it exists once.

Sources: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md` ("A table takes one route"); `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 3 limit 2 and section 6; CLI `docs/roadmap/groups/run.md:28`.

Risk: R3. It changes which code masks which column on the default routes, and output bytes may change (owner direction below). Plan review: Dennis, then Codex. Code gate: Codex and Dennis (`/code-review high`: masking lane). Full suite (T3) at each merge head, and mutations on the core units at the final head of each behavior slice.

Owner direction (2026-11-22): V1 must be fast and reproducible. Where a byte-changing design is faster or simpler than a byte-identical one, plan the faster one. Pre-V1 byte changes are allowed. Output must stay deterministic for a given seed or namespace, and each change is marked in section 10 and in the changelog `Breaking:` line. This plan uses that freedom: it does not promise byte parity with today's single-route output. It promises exact values per column (section 3, item 7), determinism and chunk-size invariance.

## 1. Frame

Today a table takes one route. `native/_dispatch.py:233` (`_static_route_decision`) decides from every node, and its comment at `:283-288` says it: "never a per-column mix, since a non-admitted table runs 100% on the oracle". The unified slice does the same: `resident_contract_admission` (`execution/_unified_slice_admission.py:410`) declines the table if one node has no binding (`:470`). So one `faker(address_full)` column puts nine `hash` columns on pandas. The audit lists this as the main reason the default faker, `shuffle`, `geo_generalize` and `formula` tables run slow.

After this change a table whose columns split into a native set and a Python set runs the native set on the kernels and the Python set on the pandas oracle, on the same batch, and builds one output through the one assembler. This is the established design for this problem (section 2).

## 2. Established solutions

Search run: per-operator or per-expression fallback in vectorized engines (Spark Python UDFs, Gluten/Velox, Polars, DataFusion, DuckDB).

- **Spark `ExtractPythonUDFs`.** The optimizer pulls Python UDFs out of a projection into an `ArrowEvalPython` (or `BatchEvalPython`) node. That node sends only the UDF input columns, as Arrow batches, to a Python worker and appends the result columns. The rest of the projection stays in the JVM. Two rules from it are used here: send the Python side only the columns it reads, and put the results back into the batch.
- **Gluten/Velox.** Fallback is per plan node: the nodes Velox supports run native and the others run on vanilla Spark, with a transition between them. Gluten counts the transitions as a cost. Here a transition is one Arrow-to-pandas conversion of the Python half's columns per batch.
- **Polars.** Expressions in one `with_columns` call all read the input frame, never each other's output, so they can run in parallel. `map_batches` is the escape hatch for Python code. This plan applies that rule between the two halves: a native column and a Python column in one mixed table never read a value the other half masked. A table where one would is not mixed (section 3, item 4).
- **DataFusion and DuckDB.** A scalar UDF gets the input batch's arrays and returns one array of the same length; the engine checks the length. Here that check is `require_same_rows` inside the adapter and the assembler's row-count assert.

No custom scheduler is added. The mixed route reuses the two executors the engine already has (the native chunk masker and the pandas adapter), the per-chunk oracle step and the one output assembler.

### Reuse inventory

- `execution/_pandas_adapter.py:167` `PandasExecutionAdapter.run`: the whole oracle, run on a trimmed plan and a smaller table. No per-node extraction.
- `execution/_chunked_oracle.py:406-504`: the per-chunk body of `_oracle_masked` (guards, adapter call with `carry`, row-error fail-closed, DGRN offset). S0 factors it into one function that both the oracle loop and the mixed branch call.
- `execution/native/_chunk_masking.py:56` `_mask_chunk_native`: the native chunk masker, column by column, with `unconfigured` passthrough.
- `execution/physical/_shadow_coordinator.py` and `_shadow_batch_runner.py`: the unified slice's native executor. An unbound node is skipped (`_shadow_batch_runner.py:137-146`), but the runner then requires the produced columns to equal the full source set and raises `SCHEMA_DIFF` otherwise (`:247-265`). Guarantee 6 changes that boundary.
- `execution/_runner.py:354` `column_dependency_edges` (`_masked_driver_columns`): the created-column driver edges (from `scalar_creating_reads`: masked driver reads of `derived`, `derived_aggregate`, `grouped_series`, `windowed_date`, `group_key`, and `nested`) that decide which nodes must stay together.
- `execution/pipeline/_source_types.py:90` `table_from_pandas_keeping_source_types`, as widened by UF-DOMAIN S1: the one output assembler.
- `frame_columns` in `execution/_column_access.py` (UF-DOMAIN S2, or S1 under the fallback in "Depends on"): the one definition of a node set's read columns.
- `execution/_chunked_carry.py:205` `untouched_columns`: the one definition of the columns no work node changes. The mixed assembler takes a column from the batch only when it is in this set (item 3).
- `execution/native/_route_decline_codes.py`: decline records and `column_decline_code` (ROUTE-LABEL-TRUTH).
- `execution/native/_chunked_evidence.py:120` `executed_backend`: the per-column backend vocabulary.

## 3. Guarantee and non-goals

After this plan:

1. **Partition.** One function, `partition_columns(plan, table, native_ok) -> ColumnPartition | RouteDeclineRecord`, splits a table's mask nodes into a native set N (nodes the lane's existing per-column checks admit) and a Python set P (the rest). `native_ok` is the lane's own per-node verdict: the per-node pass of `_static_route_decision` for the chunked lane, `PhysicalNode.execution is not None` for the unified slice. These verdicts seed N and P. Before deriving targets, `partition_columns` checks the table's entries with the existing `handler_written_columns` registry query (`execution/_column_access.py:520-531`). If it returns `None`, any one node's `writes_unknown` forces a table-wide decline to today's all-oracle route. An empty `untouched_columns` result alone cannot distinguish unknown writes from known writes to every source column (`execution/_chunked_carry.py:247-248`). For known writes, a node's targets are all of `node.columns` (never `columns[0]` alone) plus any column its handler writes beyond them (a composite's canonical outputs): exactly the columns that `untouched_columns` (`execution/_chunked_carry.py:205`) does not report as untouched for that node. A table-scope decline the per-node pass records, such as `NON_SCALAR_NODE` (`native/_dispatch.py:294-296`), stays table-wide: `partition_columns` returns it as a `RouteDeclineRecord` and the whole table takes today's route.
2. **When a table is mixed.** A table runs mixed when N and P are both non-empty, the table has no table-wide decline, after item 4 has resolved driver groups and overlapping writes, subject to the chunked entry contract in item 5. If P is empty, the table runs today's native route. If N is empty, it runs today's route for P. Table-wide declines (FK, validators, vault, quarantine and the others) still send the whole table to today's route.
3. **Execution of one batch** (a chunk on the chunked lane, the whole table on the unified slice):
   - N runs on the native executor over the batch, with every P target column passed as `unconfigured`.
   - P runs on `PandasExecutionAdapter.run` with `plan_for_nodes(plan, P)` and the sub-table `batch.select(frame_columns(P, config, table))`: every P target plus every column a P entry's `column_access(entry).reads` names, or the whole batch when a P node has `reads_unknown` (the dependency above). `plan_for_nodes` keeps the full plan, including the full `seed_envelope`, and trims only the work nodes to P. `enforce_output_projection` (`execution/_output_projection.py:97`) checks output columns against `known_output_columns(plan, table)` (`:58-73`), which reads the seed envelope, so the sub-table's columns are all declared and no `undeclared_output_columns` is raised under either policy.
   - On the chunked lane the P call goes through the factored per-chunk oracle step (item 5), never a second copy of it.
   - The output is built by the one assembler, and it stays fail-closed (fix round 1, H2). `assemble_mixed` calls `table_from_pandas_keeping_source_types(frame=empty_frame_for(batch), source=batch, untouched=untouched_columns(<all nodes of the table>, ...), arrow_columns=<N targets only>, python_half=<P targets and P-created columns only>)`. `python_half` is the one input this plan adds. `empty_frame_for(source)` is a small helper in the same module that returns a zero-column frame on the source's expected row index (`_expected_index`), so the existing frame checks run unchanged and no `frame=None` mode is added. The column rule, for each source column:
     - from `arrow_columns` when given there (today's rule); `assemble_mixed` passes only N targets, never the `unconfigured` P target copies the native output holds;
     - else from `batch` as stored when it is in `untouched` (the one definition, `untouched_columns`; the same set the adapter uses at `_pandas_adapter.py:322-335`);
     - else from `python_half`;
     - else `_columns_mismatch` (`OUTPUT_ASSEMBLY_COLUMNS_MISMATCH`). A column named in both `arrow_columns` and `python_half` also raises `_columns_mismatch`. So a column the partition fails to list as an N or P target never leaves as the raw source value.
   - Created columns (a `python_half` column the source does not hold, such as `aa_total` in P2) go where today's oracle output puts them: after every source column, in `python_half` order, which is the oracle's work order (fix round 1, M3). P2 asserts the output column list equals the `--no-native` output's list.
   - The assembler asserts `python_half.num_rows == batch.num_rows` and each `arrow_columns` length, naming the half (`native` or `python`), and raises `HANDLER_ROW_COUNT_CHANGED` otherwise. Source columns come out in source order (UF-DOMAIN assert). `require_same_rows` still guards each P node inside the adapter.
4. **Created columns stay with their drivers (one shared function).** A `when:` needs no rule here: under WHEN-READS-SOURCE it reads original values, which the sub-table holds. The only reads across columns that see a masked value are created-column drivers: a creating strategy (`derived`, `derived_aggregate`, `grouped_series`, `windowed_date`, `group_key`: the `OWN_TARGET_CREATES` declarations at `execution/_column_access.py:340-346`; `formula` is not one) reads the masked value of its drivers (`scalar_creating_reads`, `execution/_column_access.py:402`), ordered by `column_dependency_edges` (`execution/_runner.py:354`). `group_drivers_into_python(partition, work) -> ColumnPartition` is the one function, used by both lanes. For known writes, `partition_columns` uses this grouping step to resolve ownership before returning. Form components over the table's nodes using both `column_dependency_edges` and shared written targets from item 1, including `coherent_with` outputs. Move each component containing a P node wholly into P, preserving oracle work order. This also resolves overlaps exposed by a moved driver or writer. The final N targets and P written sets are disjoint. So a P created column and every N node that writes one of its drivers (and, transitively, their drivers) run together on the oracle, in the oracle's work order, and the created column sees the masked driver value exactly as today. An N creating node whose driver is a P target moves too. The native strategies that create columns today (`group_key`) read only unmasked siblings (`group_key_sibling_*` admission), so those sibling reads alone do not move them into P. If the move empties N, the table runs today's route for P. No decline code is needed. SOURCE-read drivers (`joint_mask` `key_by`, `date_shift` `group_by`) have no edge and read the original value, which the sub-table holds.
5. **Chunked lane.** The legacy `run_native_or_oracle_chunked` entry sets `enforce_schema_rule=False`: each route yields its own output with no normalization (`native/_chunked_entry.py:433-435`). At route choice, enable mixing only when `enforce_schema_rule` is true. The legacy call retains today's whole-table decision and evidence, before any mixed decision is recorded, and keeps `rule=None`. There is one preflight. `_run_chunked` already calls `_chunked_oracle._oracle_preflight` (`:91`) on the full config at `native/_chunked_entry.py:441`, before the route choice. The mixed branch reuses that `state` and passes `plan=plan_for_nodes(state.plan, P)` to each P call; it runs no second preflight. P is allowed only when that preflight succeeded for the table (fix round 1, H1). Each chunk's P half runs through `oracle_chunk_step`, factored out of `_oracle_masked` (`_chunked_oracle.py:406-504`) in S0, so the one copy keeps: the per-chunk schema guards (FK passthrough, declared FK dtype, `text_mask`, `code_set`, `bucket_perturb`), the DGRN `row_offset` (`dgrn.validate_chunk_row_offset_range` and the global offset passed to the adapter), `carry` (`carry.adapter_input`, `diagnose_adapter`, `reattach`), and the `RowErrorsFailedError` fail-closed raise on any row error. The mixed loop advances `row_offset` once per chunk with `dgrn.advance_row_offset`. A row error in any chunk raises before that chunk is yielded, so the output sink publishes nothing. **Guards on the full chunk, adapter on the sub-chunk.** The guard column lists in `state` (`guard_passthrough_fk_columns`, `declared_fk_dtypes`, `hash_fk_key_columns`, `text_mask_cols`, `code_set_cols`, `bucket_perturb_cols`; `_chunked_oracle.py:415-444`) come from the full config, and each guard treats a missing column as unsafe (`_chunked_bucket_perturb.py:139-146`). So `oracle_chunk_step` takes two tables: `source_chunk` (the full chunk) for every guard, and `adapter_chunk` for the adapter call. The oracle loop passes the same chunk as both. The mixed branch passes the full chunk as `source_chunk` and the sub-chunk `chunk.select(frame_columns(P, config, table))` as `adapter_chunk`, never the raw chunk to the adapter. So an N column's guard (for example a native `bucket_perturb` column) still runs on every chunk of a mixed table, and a guard never sees a sub-chunk that lacks its column (P9).
   **Mixed branch inputs and schema.** The table's `CarryPlan` (`execution/_chunked_carry.py:84-120`) is used unchanged: `adapter_input` and `reattach` act only on `carried` columns present in the table they get, and a carried column is one no entry reads or writes (`read_set`, `:64-81`), so it is never in `frame_columns(P)`. Both calls are therefore the identity on the sub-chunk, and `diagnose_adapter` still names a read passthrough column on a conversion failure. Carried columns reach the output from `batch` through the assembler. A test asserts `carry.carried ∩ frame_columns(P) == ∅` for every P1 table. The mixed branch passes `oracle_chunk_step` (through its step context) an `on_chunk` that returns the produced table unchanged, so the P half is not normalized on its own. After `assemble_mixed`, the branch calls `normalize_chunk(rule, assembled, chunk, table=table, chunk_index=i)` (`native/_chunked_schema_rule.py:336`) once, with the rule the native-admitted path builds today (`build_schema_rule`, `native/_chunked_entry.py:554`; the oracle-route `on_chunk` at `:143` and the native path at `:386` normalize the same way). So one call pins the schema of every assembled chunk, for both halves, against the source chunk. Whole-column families (`shuffle`, `geo_generalize`, `derived_aggregate`, `grouped_series` and an aggregate `formula`) are not row-local, so their table still does not chunk, as today.
6. **Unified slice (full frame).** P may hold any strategy, including whole-column families. The adapter runs them over the full column, where they run today. A full-frame table with `shuffle` on one column and `hash` on nine runs the nine through the kernels and `shuffle` through the oracle over the whole column. A `DecoyError` from the P half propagates with its own code and exit (ROUTE-LABEL-TRUTH A5 carve-out).
   - **Partial N result at the physical boundary.** Today `run_shadow_batches` raises `SCHEMA_DIFF` when the produced columns differ from the source columns (`physical/_shadow_batch_runner.py:247-265`), and the unified caller expects a complete table (`_unified_slice.py:294-304`). So without a change every mixed table would fail before `assemble_mixed`. `ShadowCoordinator.run` (`physical/_shadow_coordinator.py:149`) and `run_shadow_batches` (`:109`) gain one keyword, `deferred_columns: Mapping[str, frozenset[str]] | None = None`: per table, the P target columns the caller runs on the Python half. With `None` the check is today's, unchanged. With a set, the projected N schema is `source columns - deferred[table]`, and the runner raises `SCHEMA_DIFF` unless the produced columns equal it exactly: a missing N column (an unbound node whose target is not deferred), a produced deferred column, or a deferred name that is not a source column all fail closed. The validated partial table is built in source order over the projected schema. `ShadowRunResult` gains `deferred_columns` (empty by default), so the result says it is partial.
   - **Every path from the unified caller to the batch runner (traced at the head).** The unified slice has one call into the physical seam: `ShadowCoordinator(...).run(physical_plan, snapshot, when_masks=...)` at `_unified_slice.py:254-256`. `ShadowCoordinator.run` (`physical/_shadow_coordinator.py:149-198`) then branches, in order:
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
   - The mixed path of `_execute_admitted` passes `deferred_columns = {table: P targets}`, checks that the result's `deferred_columns` equals it, and hands the partial table to `assemble_mixed` as `native_out`. It never passes a partial table to the complete-table path at `_unified_slice.py:294-304`; a table that is not mixed passes `None` and keeps that path unchanged.
7. **Values.** Every column of a mixed output has exactly the values of its reference, null positions included, compared with `pa.Array.equals` after a cast to the reference's type:
   - an N column against a run of the same table with every P column set to `passthrough` (so that run takes today's native route);
   - a P column against a run of the same table on today's oracle route (`--no-native`).
   The only allowed differences are the type differences listed by type in section 10 B1. Any value difference fails.
8. **Determinism.** The same config, seed and namespace give the same output bytes on rerun, for any `native_threads`, and the same values for any chunk size.
9. **Warnings.** The warnings of both halves are merged into one list, ordered stably by the canonical work-order index of the node that raised them (`_runner.in_work_order`). Projection warnings come last, as today. The merge is one small function, `merge_half_warnings`.
10. **Evidence.** Each column's `executed_backend` is its half's backend: a P column records `pandas_oracle`, an N column its native backend. `chunked_route` and `unified_slice_activation` gain `mixed: true` for a mixed table. `RouteSummary.executed_backends` then shows both, and the CLI prints `mixed (native and Python columns)`.

Non-goals: a single work-order loop that interleaves N and P nodes (it would let a driver stay native while its created column runs on the oracle, at the cost of a per-node conversion); native kernels for any kernel-less family; mixing on FK, sequential, out-of-core or mixed-route FK tables; running the two halves in parallel; any change to which columns the native checks admit; any change to the output assembler beyond the `python_half` input and the `empty_frame_for` helper (the column rule stays fail-closed, item 3).

## 4. Enumerations

### Exit paths

- Partial N result that does not match the projected N schema (a missing N column, a produced deferred column, an unknown deferred name): `SCHEMA_DIFF` from `run_shadow_batches` (existing code, `physical/_shadow_diff_codes.py:50`), names only. Nothing is written.
- A source column with no source at the assembler (not in `untouched`, not in `arrow_columns`, not in `python_half`), or a column in both halves: `OUTPUT_ASSEMBLY_COLUMNS_MISMATCH` from `_columns_mismatch` (existing code, `pipeline/_source_types.py`), counts only. Nothing is written: it raises before any yield or publish (P21).
- Row-count mismatch at the assembler: `HANDLER_ROW_COUNT_CHANGED` (existing code), message names the half and the table, never a value. Exit 3. Nothing is written: the assert runs before any yield or publish.
- A P node failure: the same typed error the oracle raises today for that node, with its code and exit (A5 carve-out on the unified slice; no wrapper on the chunked lane).
- A P row error on the chunked lane: `RowErrorsFailedError` from `oracle_chunk_step`, before the chunk is yielded; the output sink discards (as `_chunked_oracle.py:489-502` today).
- An N column failure: the same error the native lane raises today.
- Moving a driver group into P is not an error and records no decline; the moved columns report `executed_backend = pandas_oracle`.

### Routes

- Chunked lane (auto-chunk single table, and each table of the multi-table split): mixed when item 2 holds and item 5 allows P. Decided in `native/_dispatch.py:233`, run in the chunk loop at `native/_chunked_entry.py:310`.
- Unified slice, full frame, one non-FK resident mask table: mixed when item 2 holds. Entered at `execution/_pipeline_full_frame.py:171`; partition in `execution/_unified_slice_admission.py:410`.
- Full-frame oracle, FK route, sequential route, out-of-core route: unchanged.
- `--chunked` CLI runs and `run_mask_pipeline_chunked`: unchanged, except that they now call `oracle_chunk_step` through the refactored `_oracle_masked` (S0, no behavior change).

### FK shapes

N/A: a table in any declared relationship is declined table-wide before partition (`_dispatch.py:262-267`, `fk_relationship`), on both lanes.

### Fields

- `quality_metrics["chunked_route"]["mixed"]` and `quality_metrics["unified_slice_activation"]["mixed"]` (new booleans).
- `executed_backend` per column can be `pandas_oracle` inside an admitted table.

### Output surfaces

- Masked output tables of a mixed table: values per item 7, bytes may change (section 10).
- `quality_metrics` route evidence and the warnings list (order per item 9).
- `RouteSummary.executed_backends` and the CLI run card label (`CLI:src/decoy/_native_gate.py` `classify_route`, after ROUTE-LABEL-TRUTH).

## 5. Slices and size

### Slices summary (engine and CLI halves, release named)

| Slice | Repo | Code | Acceptance tests | Sentries | Docs | Changelog fragment | Release |
|---|---|---|---|---|---|---|---|
| S0 moves | engine | `execution/chunked/_oracle_step.py`, `native/chunked/_oracle_route.py`, `native/chunked/_route_scan.py` (new); `_chunked_oracle.py`, `native/_chunked_entry.py`, `native/_dispatch.py` call them | P10 (control) | `test_module_size.py` ceilings ratchet down; `lossless-int-columns.json`, f29 inventory path-only; `GUARDED_MODULES` gains `_route_scan.py` and `_oracle_route.py`; fan-out unchanged | `CODEMAP.md` rows for the three new modules | none: `refactor` commits only, which `check_fragment.py` exempts | first engine train after merge; no behavior change |
| S1 chunked lane | engine | `pipeline/_column_partition.py`, `pipeline/_mixed_columns.py`, `native/chunked/_mixed_loop.py` (new); `python_half` and `empty_frame_for` in `pipeline/_source_types.py`; `frame_columns` in `_column_access.py` under the M1 fallback; the partition carried in `_route_scan.py`; a one-call dispatch in `native/_chunked_entry.py`; `_dispatch.py`, `_chunked_evidence.py` | P1, P2, P3, P4, P6, P7, P8, P9, P11 (`chunked_route`), P12, P13, P14, P15, P17 engine half, P21 | new AST sentry: exactly one `adapter.run` call, in `chunked/_oracle_step.py` (choke point b, widened per M4); guard sentry (P9: full-chunk guards); partition disjointness property sentry and assembler fail-closed mutation (P21); spy test that both lanes call `group_drivers_into_python`; `GUARDED_MODULES` gains `chunked/_oracle_step.py`, `native/chunked/_mixed_loop.py` and both `pipeline/` modules; `test_output_assembly_one_path.py` with no new allowlist row; no module-size ceiling raised | `CODEMAP.md` rows for the two `pipeline/` modules and `_mixed_loop.py` | `changelog.d/per-column-routing-s1.md`: `Breaking:` lines B1, B2 and B3 (`chunked_route`), `### Changed` B4 | first engine train after merge (after 0.28.5) |
| S2 unified slice | engine | `_unified_slice_admission.py`, `_unified_slice.py`, `_unified_slice_evidence.py`, `physical/_shadow_batch_runner.py`, `_shadow_coordinator.py`, `_shadow_full_frame.py`, `_shadow_result.py` | P5, P16, P18, P19, P20, P1 and P3 on the full-frame table, P11 (`unified_slice_activation`), P-bench record | `test_physical_seam_disconnection.py` (no `execution.physical` import from the new modules); mutations of P5, P19, P20 | `docs/execution-backends.md` "Mixed tables"; `docs/records/2026-12-xx-per-column-routing-bench.md` | `changelog.d/per-column-routing-s2.md`: `Breaking:` line B3 (`unified_slice_activation`), `### Changed` | first engine train after merge; CLI repins to it |
| S3 CLI test | CLI | none (test only) | P17 CLI half: `mixed (native and Python columns)` on a chunked and a full-frame mixed table in `CLI:tests/e2e/test_run_native.py` | none new | none | none (test-only PR) | CLI 1.0.0 (V1), with the engine pin bump that holds S2 |

### Whole-table steps of the adapter

`PandasExecutionAdapter.run` (`execution/_pandas_adapter.py:167-350`) has these steps that look at more than one node. For each, the trimmed plan and the sub-table give the same per-column result as the full run:

| Step | Line | Why the P half gets the same result |
|---|---|---|
| `lossless_int_columns(plan, registry, graph)` then `to_pandas_fk_safe(tbl, lossless.for_table(t, tbl))` | `:203-205` | the set is computed from the full plan (envelope kept) and filtered to the sub-table's columns; each column's conversion depends only on that column |
| token vault writer | `:236` | not reached: a vault column or writer is a table-wide decline |
| `order_work(build_work_list(plan, registry), graph)` | `:241` | P nodes keep their relative order: the order is a topological sort with a fixed key, and no P node depends on an N node written earlier (item 4) |
| row-error drain per node | `:299-306` | per node; unchanged |
| `enforce_output_projection(..., plan, policy)` | `:314` | the envelope is kept, so every sub-table column is declared (item 3); tested with policy `error` |
| `apply_degenerate_faker_pin` | `:320` | applies per faker column of the outputs; the P half's faker columns are the same columns with the same seeds; `pin_degenerate_faker` is passed as the full-frame caller passes it |
| `table_from_pandas_keeping_source_types(..., untouched_columns(...))` | `:322-335` | the sub-table's read-only columns come back untouched; the mixed assembler takes only P targets from the P output |

The builder rechecks this table at DEVELOP against the head and adds any step it finds, with the same "why" column.

### Slice S0: preparatory moves (no behavior change)

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/chunked/_oracle_step.py` (new) | 0 | `OracleChunkStep` (frozen dataclass: `plan`, `table`, `on_chunk`, `chunk_result_sink`) and `oracle_chunk_step(state, step, *, source_chunk, adapter_chunk, chunk_index, row_offset)`: the body of `_chunked_oracle.py:406-504` moved, minus the offset advance and the vault add, which stay in the loop. Guards and `on_chunk(result, source_chunk)` read `source_chunk`. The adapter (including `carry.adapter_input`), `diagnose_adapter`, `reattach` and the row-error summary (column names) read `adapter_chunk` (H1, N3). The S0 oracle loop passes the same chunk for both parameters. Exported from `execution/chunked/__init__.py` | about 135 |
| `execution/_chunked_oracle.py` | 600 | `_oracle_masked` loop calls `oracle_chunk_step` | about 510 |
| `execution/native/chunked/_oracle_route.py` (new) | 0 | `_oracle_route` (`_chunked_entry.py:113-176`) moved unchanged | about 70 |
| `execution/native/_chunked_entry.py` | 688 (ceiling 689) | minus `_oracle_route` (64 lines, `:113-176`), plus the import | about 627; the dense-ceiling rule (loc at most 40 under the ceiling) forces the ratchet to `ceiling_for(627)` = 647 |
| `execution/native/chunked/_route_scan.py` (new) | 0 | the per-node pass of `_static_route_decision` (`_dispatch.py:283-346`, the loop that builds `reasons`, `declines` and `scalar_columns`) moved into `scan_table_nodes(...) -> NodeScan`, unchanged | about 120 |
| `execution/native/_dispatch.py` | 683 (ceiling 688) | `_static_route_decision` calls `scan_table_nodes` (moves out `:283-346`, 64 lines) | about 623; stays in the census; ceiling ratchets to `ceiling_for(623)` = 643 |

Sentry baselines S0 updates for the moved paths (regenerated by each sentry's own script, then reviewed):

- `tests/sentry/baselines/lossless-int-columns.json:5`: the key `adapter_fk_safe_columns::execution/_chunked_oracle.py::_oracle_masked._masked` becomes the same call site under `execution/chunked/_oracle_step.py::oracle_chunk_step`. Same call, new path; the baseline does not grow.
- `tests/fixtures/f29/producer-inventory.json` and `tests/sentry/baselines/f29-producer-inventory.json`: no producer sits in the moved ranges today (the one `_chunked_entry.py` entry is `_validate_native_threads`, its `code=` at `:100` (def at `:98`), above the move; `_dispatch.py` declines are enum members, recorded at `_route_decline_codes.py`). The builder reruns the inventory script and commits any change, which must be line or path only.
- `tests/sentry/baselines/module-size.json:47`, `:50` (ceilings at `tests/sentry/test_module_size.py:113`, `:116`): both ratchet down to `ceiling_for(loc)` at the S0 head (about 647 and 643). Neither leaves the census.
- `tests/sentry/baselines/gcs-call-kwargs.json:62`, `:141` and `secret-material-census.json:55`, `:121`: entries in `_oracle_preflight_admitted` and `_native_route`, which do not move; unchanged.
- `GUARDED_MODULES` (`tests/sentry/test_physical_seam_disconnection.py:56-130`): confirmed at the head. It lists `execution/native/_dispatch.py` but neither `_chunked_entry.py` nor `_chunked_oracle.py`. S0 adds `execution/native/chunked/_route_scan.py` (it holds code moved out of a guarded module, so it must stay guarded) and `execution/native/chunked/_oracle_route.py` (a routing layer); S1 adds `execution/chunked/_oracle_step.py` and the two `pipeline/` modules. None imports `execution.physical`.

Control: the auto-chunk suites (`tests/unit/execution/test_auto_chunk_*`), the chunked-oracle suites and the B6a/B6b suites pass unchanged. Size: about 310 lines moved, about 20 changed.

### Slice S1: chunked lane mixing

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/pipeline/_column_partition.py` (new) | 0 | `ColumnPartition`, `partition_columns`, `plan_for_nodes`, `group_drivers_into_python` | about 150 |
| `execution/pipeline/_mixed_columns.py` (new) | 0 | `merge_half_warnings`, and `assemble_mixed(batch, partition, native_out, python_out)`, which narrows each half to its targets and calls the one assembler | about 90 |
| `execution/pipeline/_source_types.py` | 182 (UF-DOMAIN S1, merged; about 195 after PR 783) | `python_half: pa.Table | None` input with the fail-closed column rule and created-column placement (item 3); `empty_frame_for` helper | about 225 |
| `execution/pipeline/__init__.py` | 51 | exports `ColumnPartition`, `partition_columns`, `plan_for_nodes`, `group_drivers_into_python`, `assemble_mixed`, `merge_half_warnings` (L5) | +12 |
| `execution/_column_access.py` | 544 (plus PR 783's edit) | `frame_columns`, only under the M1 fallback | about 575 |
| `execution/native/chunked/_route_scan.py` | about 120 | `NodeScan` carries the per-node verdict, and the scan result carries the partition when mixed (the "decision carries the partition" change, kept out of `_dispatch.py`) | about 145 |
| `execution/native/chunked/_mixed_loop.py` (new) | 0 | `run_mixed_chunks(...)`: the mixed chunk loop. Per chunk: `_mask_chunk_native` for N; `oracle_chunk_step` with the full chunk as `source_chunk` and the P sub-chunk as `adapter_chunk`; `assemble_mixed`; one `normalize_chunk` on the assembled chunk; one offset advance | about 110 |
| `execution/native/_dispatch.py` | about 623 (ceiling 643) | passes the scan's partition through on the decision | about 627 |
| `execution/native/_chunked_entry.py` | about 627 (ceiling 647) | one branch: a schema-enforcing mixed decision calls `run_mixed_chunks` (legacy keeps the whole-table decision, item 5) | about 637 |
| `execution/native/_chunked_evidence.py` | 292 | `executed_backend` reads the column's half; `mixed` flag | about 305 |

No module-size ceiling is raised in S1 (fix round 1, M2): `_dispatch.py` and `_chunked_entry.py` stay under the ceilings S0 sets, and the mixed loop and the partition carry go into `native/chunked/` modules under 600. Callers outside `pipeline/` and `chunked/` import the new names from `decoy_engine.execution.pipeline` and `decoy_engine.execution.chunked`, never from the private modules (L5).

Also: `GUARDED_MODULES` gains both new `pipeline/` modules, `chunked/_oracle_step.py` and `native/chunked/_mixed_loop.py` (S0 added the other two `native/chunked/` modules); UF-DOMAIN's assembler sentry (`test_output_assembly_one_path.py`) needs no allowlist entry (no new `from_pandas`); the changelog fragment carries the `Breaking:` lines. Size: about 370 source lines, about 820 test lines.

### Slice S2: unified slice mixing, docs and benchmark record

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/_unified_slice_admission.py` | about 555 after RLT and UF-DOMAIN | `resident_contract_admission` returns the physical table for N plus the partition, instead of declining on the first unbound node (`:470`) | about 580 |
| `execution/_unified_slice.py` | about 490 after RLT | `_execute_admitted` runs the coordinator over N with `deferred_columns`, `PandasExecutionAdapter.run` over P, then `assemble_mixed` on the partial N table | about 520 |
| `execution/_unified_slice_evidence.py` | 226 | P nodes get node evidence with `executed_backend = pandas_oracle`; `mixed` flag | about 270 |
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
| `_column_partition.py` | `src/decoy_engine/execution/pipeline/` | "Pipeline spine and routes": new route modules go in `execution/pipeline/` (`execution/` is frozen at 104 direct modules, `CODEMAP.md:271`) | `_routing_facts.py`, `_route_summary.py` |
| `_mixed_columns.py` | `src/decoy_engine/execution/pipeline/` | same | same |
| `_oracle_step.py` | `src/decoy_engine/execution/chunked/` | "new route clusters go in `execution/chunked/`" | `_progress.py`, `_source_dtype_gate.py` |
| `_oracle_route.py`, `_route_scan.py` (S0), `_mixed_loop.py` (S1) | `src/decoy_engine/execution/native/chunked/` | "New native modules go in `execution/native/draw/` or `native/chunked/`" (`native/` is frozen at 55) | `_core.py` |
| `test_column_partition.py`, `test_mixed_columns.py` | `tests/unit/execution/pipeline/` | engine execution tests, existing subpackage | `test_native_fallback_notice.py` |
| `test_mixed_chunked.py` | `tests/unit/execution/native/` | existing chunked lane tests | auto-chunk tests |
| `test_mixed_unified_slice.py` | `tests/physical/` | unified slice tests | `test_unified_slice_parity.py` |
| `test_mixed_properties.py` | `tests/property/` | Hypothesis property tests | existing property suites |

Fan-out after this plan and ROUTE-LABEL-TRUTH: `execution/pipeline/` 18 + 1 + 2 = 21 of 25; `execution/chunked/` 2 + 1 = 3; `execution/native/chunked/` 1 + 3 = 4. `frame_columns` adds no module (it goes in `_column_access.py`). No package passes its cap. No new sub-package.

## 7. Design notes

- **Principles.** Single responsibility at the seam: the partition decides, the two existing executors execute, the one assembler builds the output. No executor learns about the other. Open/closed: a strategy that gets a kernel later moves from P to N through the operator registry, with no change here.
- **Pattern.** Spark `ArrowEvalPython` (only the read columns go to Python; results go back into the batch) and the Polars "read the input" rule between halves (section 2).
- **One place per fact.** Read columns: `frame_columns` in `execution/_column_access.py`. Untouched columns: `untouched_columns`. Driver groups: `group_drivers_into_python`, built on `column_dependency_edges`. The `when:` contract: WHEN-READS-SOURCE. Native verdict per node: the lane's own check, passed as `native_ok`. Output assembly: the one assembler. Per-chunk oracle work: `oracle_chunk_step`. Warning order: `in_work_order`.
- **Choke points.** (a) The one assembler: UF-DOMAIN's sentry already forbids a second `from_pandas` output path; this plan adds no allowlist entry. (b) `oracle_chunk_step`: a new sentry, `tests/sentry/test_oracle_step_choke_point.py`, scans with `ast` every module of the chunked lane: `execution/_chunked_oracle.py`, `execution/chunked/*.py`, `execution/native/_chunked_entry.py`, `execution/native/_dispatch.py`, `execution/native/chunked/*.py` (including `_mixed_loop.py`), `execution/pipeline/_mixed_columns.py` and `execution/pipeline/_column_partition.py`. It counts as a call site: a `.run(...)` call whose receiver chain names `adapter` (`state.adapter.run(...)`, `adapter.run(...)`, `self._adapter.run(...)`); a name bound to such a receiver or to its bound `run` (`run = state.adapter.run`, `a = state.adapter`) and later called or `.run`-called; and `getattr(<receiver naming adapter>, "run")`. It asserts the scanned file list is non-empty and holds each named file (so a rename cannot empty the scan), and that exactly one call site exists, inside `chunked/_oracle_step.py::oracle_chunk_step`. On main today the one call is `_chunked_oracle.py:448`; S0 moves it, and the sentry lands in S1, when every scanned file exists. Mutations, each red: a direct `state.adapter.run(...)` in `_mixed_loop.py`; `run = state.adapter.run` then `run(...)`; `getattr(state.adapter, "run")(...)`; deleting the call in `_oracle_step.py` (zero sites). (c) `group_drivers_into_python`: both lanes call it (spy test); mutation: move only the P node and not its drivers (P2 red). (d) `partition_columns` owns target disjointness on both lanes. P21 checks its returned partition against the declared writes (class table, row 4).
- **House style.** `ColumnPartition` and `NodeScan` are frozen dataclasses; no flag arguments; `assemble_mixed` takes the partition, not loose lists.
- **Why not one interleaved loop.** It would need the oracle split into a per-node session, a pandas conversion per Python node, and a native-to-pandas value hand-off. It is slower and adds a third executor. The two-half design reuses the executors whole and is the faster option the owner direction asks for. The price is that a driver of a Python created column runs on the oracle too.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | assembler errors, decline record, evidence | messages name half, table and column only; record is code and identifiers | P7 | add the first differing value to the message (P7 red) |
| 2 | Cleanup missing on an exit path | chunked failure mid-stream | the existing output sink owns publish and discard; the mixed branch raises before yield | P6, P14 | yield before the row-error check (P14 red) |
| 3 | State and concurrency | native threads | each half runs in turn; native threads apply to N only | P4 | n/a |
| 4 | Route parity and silent fallback | partition, driver groups, assembly | `partition_columns` declines unknown writes and groups known overlapping writers. P21 property sentry checks final N targets against P writes. Exact values per column (P1); a created column and its drivers run in one half; the assembler takes a column from the batch only when it is in `untouched_columns`, else from a half, else raises | P1, P2, P5, P21 | split a driver group across halves (P2 red); swap two columns at assembly (P1 red); drop one P target from the partition (P21 red) |
| 5 | Referential integrity | FK tables | declined table-wide before partition | P8 | move the FK check after the partition (P8 red) |
| 6 | Untrusted producer | adapter result for P | row count asserted at the assembler; only P targets taken from it | P6 | skip the row assert (P6 red) |
| 7 | Check then use | partition decided once, executed per chunk; one preflight | the decision carries the partition; per-chunk schema guards run in `oracle_chunk_step` on the full source chunk; the mixed branch reuses the preflight state | P9, P14 | skip the guards for P (P9 red); run the guards on the sub-chunk (P9 guard sentry red) |
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
  - Created-column position (M3): in every case above the output column list equals the `--no-native` output's column list, so `aa_total` sits where today's oracle puts it (after the source columns). Mutation: place created columns after their last read column instead (red).
  - Mutation: move only the P node and leave its driver in N (the `aa_total` case red).
- **P3 determinism.** Each run first asserts the table ran mixed (`mixed: true` and both backends in `executed_backends`); that assertion is the fail-before. The determinism checks are controls. One mixed table run twice gives identical output bytes and identical `quality_metrics` (minus timings). Chunk size 7,000 versus 40,000 on 120,000 rows gives equal values per column.
- **P4 threads.** `native_threads` 1 versus 4 on a mixed table: identical output bytes. Same fail-before as P3 (the mixed assertion); the byte check is a control.
- **P5 whole-column on full frame.** 2,000 rows: `shuffle` on one column and `hash in ns` on nine. Run end to end through `run_pipeline`, so the call goes `_unified_slice.py:254-256` to `ShadowCoordinator.run` and not to the runner directly. The unified slice admits mixed; a spy shows `dispatch_full_frame_if_applicable` returned `None` and `run_shadow_batches` ran with `deferred_columns`; the nine `executed_backend` values are native and `shuffle` is `pandas_oracle`; the `shuffle` column equals today's oracle output exactly. Mutation: remove the deferred narrowing in `dispatch_full_frame_if_applicable` (the full-frame capture comes back): P5 red, because the nine `hash` columns report `pandas_oracle`. On 120,000 rows the same table still does not chunk and is mixed on full frame. Fail-before: whole table on the oracle.
- **P6 row-count guard.** A P handler stub that drops a row: `HANDLER_ROW_COUNT_CHANGED` from `require_same_rows`. A stubbed half returning `n - 1` rows at the assembler: `HANDLER_ROW_COUNT_CHANGED` naming the half. No output is published on either lane.
- **P7 value-free.** P6 and P14 messages and evidence hold no seeded sentinel value.
- **P8 FK control.** A child table with an FK column and a P column: declined `fk_relationship`, today's route, output unchanged.
- **P9 degenerate chunks and guards.** A 120,000-row mixed table whose last chunk is all-null for the `fpe` and `bucket_perturb` N columns and empty for a P column, plus a zero-row chunk: P1 values, degenerate types per the existing reconciliation. A `code_set` P column whose type drifts in chunk 3: the existing `code_set` schema guard raises, from `oracle_chunk_step`. Guards on the full chunk (H1):
  - A native (N) `bucket_perturb` column whose type drifts to a non-string type in chunk 3 of a mixed table: `chunked_bucket_perturb_source_dtype_unsupported` is raised from the full-chunk guard in `oracle_chunk_step`, and no output is published.
  - Guard sentry: the same mixed table with no drift (the N `bucket_perturb`, `code_set` and `text_mask` columns are guard columns of the full config and absent from the P sub-chunk) runs every chunk and raises nothing. Mutation: pass the sub-chunk to the guards (red on chunk 0).
  - One preflight: a spy on `_oracle_preflight` counts one call per mixed table, and every P adapter call gets `plan_for_nodes(state.plan, P)`.
  - Legacy entry control (S1): run an otherwise mixable table through `run_native_or_oracle_chunked` and compare each chunk's values and exact Arrow types to the unnormalized whole-table oracle. Assert oracle-only route evidence and zero calls to `normalize_chunk`. Run the same input through the schema-enforcing entry and assert it mixes, with one normalization per assembled chunk. Allowing the legacy entry to mix must fail the control.
- **P10 control: S0 moves.** The auto-chunk, chunked-oracle, B6a and B6b suites pass unchanged on the S0 head. `_chunked_entry.py` and `_dispatch.py` ceilings move down.
- **P11 frozen snapshots.** The artifacts that can change, and how:
  - `tests/fileaccess/route_corpus_golden.json` and `tests/unit/execution/r3_within_route_baseline.json` (both hold `chunked_route` evidence): a table that now mixes gains `mixed: true`, `native_admitted: true` and per-column `executed_backend` values of its half (B3). No other key changes.
  - `tests/snapshots/golden/mask_*/<column>.sha256` (for example `mask_faker_seeded/address.sha256`): a digest changes only for an N column of a table that now mixes, and only through a B1 type pair; its values, compared with `pa.Array.equals` after the B1 cast, are equal.
  - `tests/snapshots/frozen_schemas/run-result.schema.json`: unchanged (it does not pin `quality_metrics` keys).
  Each changed entry is regenerated in the same PR and listed in the PR body against B1 or B3. Any other change blocks.
- **P18 partial N result accepted.** The 2,000-row `shuffle` plus nine `hash in ns` table, through `ShadowCoordinator.run` (not the runner directly): the coordinator with `deferred_columns={t: {shuffle column}}` returns the nine N columns plus passthrough columns, in source order, without the `shuffle` column, and `result.deferred_columns` equals the input. Control: the same call with `deferred_columns=None` on a fully bound table behaves as today. Fail-before: `SCHEMA_DIFF`.
- **P19 missing N column fails closed.** Same table with `deferred_columns` that leaves out one unbound P target: `SCHEMA_DIFF`, naming the table and column names only. Also `SCHEMA_DIFF` when a deferred column is produced (a bound node's target listed as deferred) and when a deferred name is not a source column. No output is published. Mutation: drop the projected N-schema check (accept any produced subset): P19 red.
- **P20 coordinator refusals.** Through `ShadowCoordinator.run` with `deferred_columns` set: a plan with a synthesis stage, a mixed synthesis-plus-mask plan and an `{OUT_OF_CORE}` plan each raise `ShadowDifference(SCHEMA_DIFF)` before any adapter runs (a spy on each dispatch shows no call). A `{FULL_FRAME}` plan with `deferred_columns` set and a `top_code` node not deferred raises `SCHEMA_DIFF` from `dispatch_full_frame_if_applicable`, not a full-frame run. Control: the same plans with `deferred_columns=None` behave as today. Mutation: drop the refusal in branch 2 (P20 red).
- **P21 assembler fails closed (H2).** Mixed table, chunked lane and full frame: mutate the partition so one P target is in neither half (dropped from P, not added to N). The assembler raises `OUTPUT_ASSEMBLY_COLUMNS_MISMATCH` and the output sink publishes no file; the raw source value never reaches the output. Also: a column passed in both `arrow_columns` and `python_half` raises the same code. A multi-column P node (two `node.columns`): both columns come from the P half (targets are all of `node.columns`). A table with a non-scalar node: declined `NON_SCALAR_NODE`, today's route, not mixed. Mutation: let a column with no half fall back to `batch` (red).
  - Unknown writes: an otherwise mixable table has nine native hashes and one working custom handler whose access declaration yields `writes_unknown`. Assert the partition returns a table-wide decline, execution uses only the oracle, and the complete output equals the oracle reference. Bypass the `handler_written_columns(...) is None` decline: the partition assertion must fail.
  - Known overlap: seed P with a composite provider whose `coherent_with` writes a target also owned by a native-admitted node. Use a scalar provider node so the non-scalar decline cannot mask the test. Include an independent native hash. Assert both writers run in P in oracle work order, the shared column matches the all-oracle result, and the independent hash stays native. Remove shared-write edges while keeping driver edges: the ownership assertion must fail on a pair with no driver edge.
  - Partition property sentry (both lanes): generate valid work nodes with known writes, varying native verdicts, multi-target writes, shared outputs and driver chains. For each returned partition, derive N targets and P written columns independently from the original node columns and registry declarations and assert their intersection is empty. Include the known-overlap example with a required mixed result so a blanket decline cannot pass. Omitting the shared-write edge must turn this sentry red.
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

Test scope: T0 per edit; T1 impact selection plus the named tests and guard tests; T3 full suite at each merge head (R3, masking route), diffed against the saved main baseline. Mutations: `partition_columns` (P21 unknown-write decline), `group_drivers_into_python` (P2 driver groups and P21 shared-write edges), `assemble_mixed` (order, row assert, the fail-closed column rule of P21, created-column placement of P2), the full-chunk guard input of `oracle_chunk_step` (P9), the `adapter.run` choke-point sentry (choke point b), the projected N-schema check in `run_shadow_batches` (P19), the deferred narrowing in `dispatch_full_frame_if_applicable` (P5), the coordinator refusals (P20), `merge_half_warnings`, the `row_offset` passed to `oracle_chunk_step` and the per-column backend evidence, rerun on the final head of S1 and S2.

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

## 13. Fix round 1 (Dennis R1, 2026-11-25)

Review: GO-WITH-FIXES, 2 HIGH, 4 MEDIUM, 6 LOW, against engine `origin/main` `393f0d47c`. Each finding and where the plan now answers it:

| Finding | Where answered | Test or sentry |
|---|---|---|
| H1 guards fail on the P sub-chunk | section 3 item 5 (one preflight from `_chunked_entry.py:441`, `plan_for_nodes(state.plan, P)`; guards on `source_chunk`, adapter on `adapter_chunk`); S0 table row for `_oracle_step.py` | P9 N `bucket_perturb` drift in chunk 3 raises; guard sentry (no false raise, mutation: guards on the sub-chunk); preflight spy |
| H2 assembler stops failing closed | section 3 item 1 (targets are all of `node.columns`; `NON_SCALAR_NODE` stays table-wide) and item 3 (column rule: `arrow_columns`, else `batch` only when in `untouched_columns`, else `python_half`, else `_columns_mismatch`; no `frame=None`); exit paths; non-goals; class table row 4 | P21 (drop one P target: raises, nothing written; both halves raises; multi-column node; `NON_SCALAR_NODE`) |
| M1 `frame_columns` placement and start rule | "Depends on" (UF-DOMAIN bullet and fallback), start-order table S1 row, reuse inventory, design notes | `test_column_access.py` read-set cases under the fallback |
| M2 sizes lead to a raised cap | S0 and S1 size tables; `_mixed_loop.py` new; partition carry in `_route_scan.py`; "No module-size ceiling is raised in S1" | `test_module_size.py` ratchets in S0, no bump in S1 |
| M3 created-column position | section 3 item 3 (after the source columns, in work order, as today's oracle) | P2 column-list assertion and its mutation |
| M4 narrow `adapter.run` sentry | section 7 choke point (b): wider scan, alias and `getattr` forms, exactly one site, non-empty scan | `test_oracle_step_choke_point.py` and four mutations |
| L1 `enforce_output_projection` anchor | section 3 item 3: `_output_projection.py:97` | n/a |
| L2 P5 anchor | P5: `_unified_slice.py:254-256` | n/a |
| L3 `_runner.py:354` listed twice | reuse inventory: one line | n/a |
| L4 `execution/` freeze | placement table: 104 (`CODEMAP.md:271`) | n/a |
| L5 private-module imports | S1 table: `pipeline/__init__.py` and `chunked/__init__.py` exports; callers import from the package | code gate |
| L6 eight keyword parameters | S0 table: `OracleChunkStep` step context; `oracle_chunk_step(state, step, *, source_chunk, adapter_chunk, chunk_index, row_offset)` | n/a |

Not verified in this round (carried from the review): ROUTE-LABEL-TRUTH revision 3.3 line by line, the anchors on PR 783's head, and the P-bench targets. The builder rereads them at the S1 branch base.
