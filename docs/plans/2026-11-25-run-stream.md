Status: plan

# RUN-STREAM (row 63a): what is left, re-planned on current code

Rules consulted: 00-universal, risk-and-exceptions, development-loop, architecture, testing, cross-cutting-concerns, reuse-first, proportionality, documentation, profiles/local-operations, catalogs/recurring-defects; LOCAL-BUILDER-BRIEF; engine CLAUDE.md (established methodology, 600/700 module rule, pre-GA hard delete); CLI CODEMAP "Where Things Go" (`CODEMAP.md:44-85`).

Risk: R2 (runtime and out-of-core path; the publish step of `decoy run`). Release: CLI 1.0.0 (V1), with 1.0.0-rc.1 if it ships in mid-December; engine: the first daily engine train after slice E6 merges (the next number after 0.28.4; E6 is additive and does not wait for the 0.29.0 surface release). Engine half: one slice, E6 (section 14). E1a to E5b are merged and released. Author: architect worker, 2026-11-25. Bases: engine `origin/main` `393f0d47c` (engine version 0.28.4), CLI `origin/main` `3df9c13a`, CLI pin `decoy-engine==0.28.3`. Round 2 re-checked every cited line on both bases.

## Changes in round 2

Fix round 1 for the Senior review (5 HIGH, 8 MEDIUM, 6 LOW). Each item says whether it takes the reviewer's remediation (R) or a different root-cause fix (B).

- H1 (R, extended). `spill_parent` and `committed_table_path` never return None: 4.1 now names the rule per layout kind. New AT-S1l (absolute-target run with forced spill) and a unit sentry over every `RunLayout` constructor, plus a targetless-plus-quarantine unit cell. Failure-mode row "Hold-back must spill" restated.
- H2 (R). `runtime.streaming_unavailable` exits 1 through one code-keyed rule in `exit_code_for`, with a row in `tests/unit/test_exit_code_for.py`. Recorded in 5.1 and 13. This also keeps today's exit 1 for the `PlanCompileError` the engine now wraps.
- H3 (B: both halves). Engine slice E6 gives compressed CSV a lazy reader, so `.csv.gz` keeps streaming under `--chunked` (released on the first engine train after it merges). The CLI also loads `--chunked` sources lazy-only and refuses, before any read, a source with no lazy backend (`chunked_source_not_lazy`, exit 1). `_prepare.py` source loading is in S2 Placement. G3 restated.
- H4 (R). Only the `--explain-plan` part of `_ChunkedReportFlagError` is lifted; `--fidelity`, `--post-validate` and `--post-validate-enforce` keep a CLI refusal. Validators and declared casting under `--chunked` move from "runs" to the engine refusal; listed in 13, pinned by AT-S2g, owner question RS-Q9. Non-goal list, 4.3 and 13 restated: the round 1 text said two exception rows leave `exit_codes.py`; now one does.
- H5 (R). `sink_unused_reason` and `SINK_UNUSED_CODES` live in `run/_sink_policy.py`; `TargetSink` stays in `io/_sink.py` with plain arguments. The choke-point sentry also asserts that no `cli/io` module imports `decoy.cli.run`.
- M1 (R, set the marker). `TargetSink.bounded_write_batches = True`; route-parity cell AT-S1k for streamed generation. E6 documents the marker as an optional sink member.
- M2 (R). AT-S1i is now a unit test of `TargetSink` against `guard_quarantine_not_aliasing_committed_table`.
- M3 (R). G1 restated as the row-group cap (1,048,576 rows or 256 MiB, whichever comes first) plus one chunk. AT-S1b uses 8M rows.
- M4 (R). Both sentries allowlist by exact `(path, function)`; `execute_preview` is listed.
- M5 (R). The four DELIV plan amendments ship with S1 (section 10, text in 10.1).
- M6 (B). The pointer is `/result/route/sink`. The `Route` model is engine-owned (`run_result/_model.py:276-280`), so the optional field is added in E6, not by the CLI. `_result.py` is in Placement; the shape snapshot and CHANGELOG update in S1. Round 1 said "engine half: none", which this proves false; restated above.
- M7 (R, sequence). S2 waits on CLI #387 (merged or closed), and AT-S2a's config list is computed at the S2 head, so it includes #387's nested-passthrough fixtures.
- M8 (R). G4 declares the change: under S2, `--chunked` on an empty CSV source writes a header-only CSV, where base `--chunked` publishes nothing (`_targets.py:748-750`). AT-S2a pins it as a named exception.
- L1 to L4, L6 taken (rename to `sink_unused_reason`; sink errors carry no table name; class row 7 and 5.2 fixed; `_post_scan.py:197-222` cited; double-write refusal justified from the engine call sites in 4.1). L5 logged as V2-LOG in 16.
- Catalog notes from the review: class 3 (`__context__ is None` on every `TargetSink` error) is in the class table; class 5 shapes (`getattr` and module-attribute forms) are listed in 8.

This plan replaces sections 5.2, 5.6 and 14 of the revision 6.5 plan (`C:plan/run-stream-r6-5` `61826004`, `docs/plans/2026-11-08-run-stream.md`) for the slices that are not built. Everything that plan records as merged stays as it is and is not re-planned. Sections 1 (measurement method), 3 (established solutions) and 5.3 to 5.5 of revision 6.5 stay the reference for the engine contract; this file cites them instead of copying them.

## 0. What already shipped (evidence)

| Slice | Repo | State | Evidence |
|---|---|---|---|
| E2 CSV lazy source | engine | merged | #437 |
| E1a strict `execution_mode="stream"` | engine | merged, in 0.20.0 | #439 |
| E1b CPU probe, DuckDB thread cap, auto budget | engine | merged, in 0.20.0 | #442 |
| E3 `route_summary` | engine | merged, in 0.21.0 | #459 |
| E4 one lazy format table | engine | merged | #598 |
| E5 resident fallback for lazy input | engine | merged | #601 |
| E5a no-sink lazy input through the collector | engine | merged | #604 |
| E5b collector scratch on first spill | engine | merged | #605 |
| C3 `--max-memory`, `--threads`, settings, doctor | CLI | merged | #165 |
| C1l plain run hands sources lazily | CLI | merged | #372; `src/decoy/cli/run/_execute.py:469` passes `resident_fallback=True` |

Searches run on 2026-11-25: `gh pr list --state all --search RUN-STREAM` in both repos, `git log origin/main`, and the `plan/run-stream*` branches (`plan/run-stream`, `-r5`, `-r6-3`, `-r6-4`, `-r6-5`). No open or merged PR builds C1a, C1b, C2 or M1. Open draft CLI #387 (CHUNKED-STRUCT S2, `test(run): chunked runs keep nested passthrough columns`) adds `--chunked` nested-passthrough cases to `tests/e2e/test_run_chunked_parquet.py`; S2 waits on it and AT-S2a includes them (round 2, M7). No `src/decoy/cli/io/_sink.py` exists on CLI main. The roadmap row (`C:docs/roadmap/groups/run.md:21`) says "Left: C1a, C1b, C2 and M1".

Not duplicated: GEN-STREAM-ALL (engine #813) streams generate columns inside the engine and writes into whatever sink the caller passes (`generation/_streamed.py:527`); this plan builds that one CLI sink, it does not touch generation. NONFK-OOM S5 (engine #816) adds `scripts/bench-auto-chunk/bench_nonfk_fallthrough.py e2e`; M1 below reuses that verb instead of writing a second `decoy run` bench driver. F25 G7-1 (engine #789) is cloud reads; cloud sources and targets stay out of scope here (CLI-CLOUD, row 64).

What changed since revision 6.5 that forces the re-plan:

1. `--chunked` no longer uses the CLI pandas path. CLI #399 (2026-11-24) made it call the engine's `run_mask_chunked` per table (`src/decoy/cli/run/_execute.py:82-170`, `:196-235`), the same native chunked core the auto-chunk lane drives (`execution/physical/drivers/_chunked.py:33-34`). C2 is now "move `--chunked` onto `run_pipeline`", not "delete a pandas path".
2. CLI #397 made `write_chunked_output` the one Arrow chunked writer for CSV and Parquet (`src/decoy/cli/io/_targets.py:711-778`), with a deferred-publish `ExitStack` (`:696-708`).
3. DELIV C2a, which revision 6.5 made the base of C1a (`DeliverySink`), is not started. Its own order is E2b (#780, in rework), then REL, then C2p, then C2a (`E:plan/deliv` 0.3). C1b also waited on DELIV C2b and C2 on DELIV C5. Keeping that chain leaves row 63a open until most of DELIV is built.

## 1. FRAME

### Problem

A plain `decoy run` reads large sources lazily (C1l), but every output table still comes back resident in `result.outputs` and is written after the run (`_execute.py:496-498`), because the CLI passes no `sink`. The no-sink collector bounds input and hold-back, not output (`execution/_pipeline_auto_chunk.py:488-525`). So a 16M-row single table still needs its whole masked output in memory. `--chunked` streams output, but on its own call path with its own refusals and no `ExecutionResult`, so it has no route summary, no report flags and no quarantine.

### Pinned guarantee (V1)

- G1. A plain `decoy run` passes one CLI `TargetSink` to `run_pipeline` when `sink_unused_reason` returns None (4.2). Tables the engine streams reach their targets batch by batch. Peak output memory for an auto-chunk table is bounded by the engine's row-group buffer (`ROW_GROUP_ROWS` = 1,048,576 rows or `ROW_GROUP_BYTES` = 256 MiB, whichever comes first, `_chunked_output_sink.py:69-71`, `:433-442`) plus one chunk, not by table size. A table below about 1M rows sees little gain; the AT measures at 8M rows.
- G2. One staging seam. Streamed tables and resident tables of a sink run are staged through the one chunked writer, `write_chunked_output(..., defer=stack)`, onto one `ExitStack` that `execute` owns. Nothing is published until the run returned, `post_run_verify` passed and every resident table is staged. Any exception, `KeyboardInterrupt` included, unwinds the stack and publishes nothing.
- G3. `--chunked` is `run_pipeline(execution_mode="stream", chunk_size_rows=..., sink=TargetSink)` over sources loaded lazy-only. It must stream or it exits 1 before any source data row is read: the CLI refuses a source with no lazy backend (`chunked_source_not_lazy`, 4.3) before it opens one, and the engine refuses a config no streaming route takes with `runtime.streaming_unavailable` (E1a contract, revision 6.5 section 5.3), which `exit_code_for` maps to 1 (H2). After E6, every format base `--chunked` reads (CSV, compressed CSV, Parquet) has a lazy backend. `_run_chunked_mask` and its readers are deleted (pre-GA hard delete).
- G4. Output values and types do not change. A sink run writes the same CSV bytes and the same Parquet schema and values as the same config without a sink. `--chunked` keeps base `--chunked` bytes for the same chunk size (E1a keeps the row-group grouping under `stream_required`). An empty table follows the plain-run rule on both paths: a header-only CSV, a zero-row Parquet file with the schema. Declared change: base `--chunked` publishes nothing for an empty CSV source (`_targets.py:748-750`), so under S2 that one case changes from "no file" to "header-only CSV" (13; AT-S2a names it).
- G5. The run summary and `--json` (`/result/route/sink`) say whether the sink was used and, when not, the one registered reason code. The route label comes from `route_summary` as today.

### Non-goals (V1)

- A sink on a run where `post_scan_gate_applies(config)` is true (relationships or integrity). The engine post-scan gate cannot read a foreign sink (`config/_post_scan.py:197-222`, `_READABLE_SINK_KINDS`; revision 6.5 Q8). Those runs keep today's no-sink path. Exception: `--chunked` with relationships and no integrity, which runs today with the `chunked_key_check_not_run` warning (`_execute.py:308-321`) and keeps doing so (4.3).
- A sink with `--vault` (engine B0 refuses the pair, `execution/_pipeline_context.py:170-173`; V2 VAULT-STREAM).
- Streaming `fixed_width` and archive CSV targets (`_targets.py:742-743`). A run with one takes no sink.
- `--chunked` for generate tables, quarantine, subset and integrity: the current refusals stay (`_prepare.py:473-478`, `_execute.py:279-292`, `:297-302`, `:247-253`). Lifting any of them is a later row.
- `--chunked` with `--fidelity`, `--post-validate` or `--post-validate-enforce`: the CLI refusal stays (H4). The engine keeps output resident for both reports (`_chunked_output_sink.py:118-121`), so strict stream cannot take them.
- `--chunked` with `validators:` or declared casting: refused by the engine under strict stream (`_chunked_output_sink.py:110-115`, then `pipeline/_stream.py:188-189`). Base `--chunked` ran these configs (it never checked `validators:`, so they were silently skipped). This is a declared change (13, RS-Q9), not a kept behavior.
- DELIV's stage, pointer and delivery decision. DELIV C2a later moves the one staging seam named in G2 onto `DeliverySink` (owner question RS-Q1).
- Cloud sources and targets (row 64). Platform P1 (parked with Platform V1).

### Failure modes

| Failure | Behavior |
|---|---|
| Engine raises after streaming table 1 of 2 | engine calls `TargetSink.abort()` (state only, no I/O), re-raises; the `with ExitStack` in `execute` unwinds with the exception; every staged temp is removed (`_atomic.py:440-449`); no target file changes; exit as today |
| `post_run_verify` refuses after the engine committed | raises inside the stack; nothing published; "no output was written" stays true |
| `KeyboardInterrupt` after engine `commit()` (engine never aborts after commit) | the stack unwinds on `BaseException`; nothing published; `_flow.py:227-230` still calls `layout.abandon()` |
| Engine calls `write`/`write_batches` twice for one table, or after `commit()`/`abort()` | `TargetSink` raises `RuntimeError` with fixed text, no table name and no value, outside any `except` block; the run fails, nothing published |
| A table with no declared target | batches consumed and counted, never written (today's skip in `write_targets`, `_targets.py:650-667`) |
| Hold-back must spill | the engine makes a private `_hold` stage under `TargetSink.spill_parent` (`_chunked_output_sink.py:477-496`) and removes it at close; `spill_parent` is never None on any layout kind (4.1), so `hold_back_spill_unavailable` cannot fire for a CLI run |
| Quarantine path equals a target path | the CLI collision rule refuses first (`io/_placement.py:278-303`); behind it the engine alias guard reads `TargetSink.committed_table_path` (`quarantine.py:546-556`), which is never None, so a targetless table cannot reach `os.path.abspath(None)` |
| Publish fails on target 2 of 3 at stack exit | same as today's `--chunked`: the ledger records what published (`_targets.py:632-647`), exit 3; atomic multi-file publish is DELIV's |
| `--chunked` config no streaming route takes | engine `runtime.streaming_unavailable` before a data-row iterator opens; CLI exit 1 (code-keyed rule in `exit_code_for`, H2) with the reason code and blocking fact |
| `--chunked` source with no lazy backend | CLI `UsageRefusal` code `chunked_source_not_lazy`, exit 1, before any source is opened; names the table, no path or value |
| Empty streamed table | CSV: `TargetSink` stages `schema.empty_table()` as one chunk so the header is written; Parquet: the empty-schema path writes the zero-row file |
| Disk full while staging | `OSError` propagates, stack unwinds, exit 3 |

## 2. Established solutions

- Two-phase output commit: Hadoop/Spark `FileOutputCommitter` (task output staged privately, job commit publishes, abort deletes) and `atomicwrites.atomic_write`, which `staged_local_target` already follows (`_atomic.py:440-449`). The sink stages, the caller commits; the engine's `commit()` is only "producer finished".
- Push-to-file batch writers with a fixed schema: Arrow `ParquetWriter` and `pyarrow.csv.CSVWriter`, already the CLI's writers (`_targets.py:760-776`). No new writer.
- Strategy object at a library boundary (GoF Strategy; Python DB-API style protocols): the engine owns `TransactionalSink` (`execution/_transactional_sink.py:75-110`), the CLI supplies one implementation. Duck-typed optional members `spill_parent` and `committed_table_path` are documented in the engine compatibility contract (`docs/compatibility-contract.md:1208-1213`) and the quarantine guard.
- Streamed decompression for CSV (E6a): pandas `read_csv(compression=..., chunksize=...)` decompresses as it reads, with one chunk in memory; the compression is named explicitly because inference from a file object has no suffix to read. The engine already reads every CSV through this one reader (`profile/_csv_reader.py:514`); the reviewer's alternative, Arrow `pa.input_stream(path, compression="detect")` with `pyarrow.csv.open_csv`, would add a second CSV parse path that skips the dialect resolution and fail-closed rules `read_csv_source` applies. That sentry (`tests/sentry/test_csv_scan_single_copy.py`) states the one-reader rule but only walks stdlib `csv.reader` calls, so it would not catch the Arrow path; the plan keeps the one reader by choice, not because a guard forces it.
- Additive optional field in a versioned document (E6b): JSON Schema and protobuf practice (new optional fields within a major; readers ignore or default them), as the engine's own `/v1` rule states (`run_result/_model.py:8-11`).
- Benchmarks: M1 reuses `scripts/bench-auto-chunk/` (`bench_sink.py`, `bench_lazy.py`, `bench_nonfk_fallthrough.py e2e`) and records RSS by `/usr/bin/time -v` on Linux and `-l` on macOS, the method of revision 6.5 section 1.

## 3. Sameness questions

1. Does `TargetSink` do what another module already does? The engine has `ParquetTransactionalSink` (engine-owned stage and `publish_unit`) and the collector adapter. Neither writes CSV or places paths through `RunLayout`. The CLI side already has one chunked writer and one deferred stack. `TargetSink` adds no writer: it adapts the engine push calls onto `write_chunked_output`. A second writer, stage or publish path is a STOP.
2. Could it live in one central place? Yes: `src/decoy/cli/io/_sink.py` is the only CLI module that implements `TransactionalSink`, and `sink_unused_reason` in `src/decoy/cli/run/_sink_policy.py` is the only place a run decides to pass a sink. The policy reads `RunContext`, so it lives in `run/`; the sink takes plain arguments, so `io/` keeps importing nothing from `run/` (H5). DELIV C2a later swaps the stage under the sink in that one file.

## 4. Behavior

### 4.1 `TargetSink` (`src/decoy/cli/io/_sink.py`)

Constructed by `execute` with plain arguments `(config_dict, layout, stack, ledger)`: a dict, a `RunLayout`, an `ExitStack` and the publication ledger. It takes no `RunContext` and `io/_sink.py` imports nothing from `decoy.cli.run` (H5). States `open -> committed | aborted`. Class attribute `bounded_write_batches = True`: `write_chunked_output` pulls one batch at a time and never concatenates, so the engine's explicit capability marker (`generation/_streamed.py:101-104`) is true, and streamed generation takes the sink (M1).

- `write_batches(table, batches, *, schema)`: for a table with a file target, calls `write_chunked_output((pa.Table.from_batches([b], schema=schema) for b in batches), fmt, raw_path, layout, empty_schema=lambda: schema, ledger=ledger, name=table, defer=stack)`. When the iterator is empty and `fmt == "csv"`, it passes `[schema.empty_table()]` instead so the header is written (G4). Records the row count. A table without a target: consumes the iterator, counts rows.
- `write(table, data)`: `write_batches(table, data.to_batches(), schema=data.schema)`.
- `commit()`: `open -> committed`; publishes nothing; returns `None`.
- `abort()`: sets `aborted`; no I/O; never raises (protocol rule, `_transactional_sink.py:84-91`).
- `stage_resident(outputs)`: after `run_pipeline` returns, stages each output table the engine did not write, through the same `write` path. Refuses a table written twice.
- `rows_written() -> dict[str, int]`: per-table counts for `table_records`, evidence and notify, because a streamed table is absent from `result.outputs`.
- `spill_parent` (never None, H1). `layout.output_dir()` when it is not None (run folder 0700, or an existing `--out-dir`). A contained `--out-dir` that does not exist yet is created first with the same `RunLayout.out_dir(base, create=True)` call `place_target` makes (`_layout.py:577-578`). On a fixed layout (`build_layout` returns `RunLayout.fixed` when no output is placed, `_layout.py:783-784`, and `output_dir()` is then None, `:637-638`): the placed parent folder of the first declared file target, in config order, that exists as a directory; else `layout.base` (the YAML's folder, which exists). This follows the reference sink, whose `spill_parent` is the target's parent (engine `docs/compatibility-contract.md:1212-1213`).
- `committed_table_path(table)` (never None, H1): `layout.place_target(raw_path)` for a targeted table. For a targetless table, the same folder `spill_parent` returns: a directory, never a file destination, so it cannot alias a quarantine file, and the engine guard never calls `os.path.abspath(None)` (`quarantine.py:553`).
- Errors: every `TargetSink` error is raised after any `except` block closes, with fixed text, no table name and no value (catalog class 3; `__cause__` and `__context__` asserted None).
- Double write: the reference sink replaces a table written again (`_transactional_sink.py:188`, `:313`). `TargetSink` refuses instead, because a second `write_chunked_output(defer=stack)` for one target would put two publishes of one path on the stack. No engine route writes a table twice: each route calls the sink once per table (`_chunked_output_sink.py:591` or `:597`, an if/else; `_sequential.py:565`, one call per table in topological order; `out_of_core/_emit.py:106` or `:128`; `_pipeline_mixed_route.py:223` for generate outputs; `generation/_streamed.py:527`). `stage_resident` skips tables the engine already wrote. The unit state table pins the refusal (L6).

### 4.2 `sink_unused_reason(ctx) -> str | None` (`src/decoy/cli/run/_sink_policy.py`)

The one predicate, beside `SINK_UNUSED_CODES` in the same new module (H5, L1). `None` means pass the sink. Otherwise one code from `SINK_UNUSED_CODES`, checked in this order:

| Code | Condition |
|---|---|
| `run.sink_unused.vault` | `--vault` given |
| `run.sink_unused.post_scan` | `post_scan_gate_applies(config)` and not `--chunked` |
| `run.sink_unused.target_format` | any file target is `fixed_width` or archive CSV |
| `run.sink_unused.cloud` | never reached today (`_require_local_io_endpoints` refuses first); listed so the registry is complete once row 64 lifts the refusal |

It never refuses a run and is not a warning. `--sample` and `decoy run` both reach `execute` and use the same predicate; `tokenize` and `api.mask()` never call it (they do not call `execute`).

### 4.3 `--chunked` (S2)

`execute` has one branch. `ctx.chunked` adds `execution_mode="stream"` and `chunk_size_rows=ctx.chunk_size or DEFAULT_CHUNK_SIZE` to the same `run_pipeline` call, and always passes the sink, because strict stream needs streamed output. `sink_unused_reason` under `--chunked` can only return `vault` or `target_format`, and both are refused earlier (`_prepare.py:501-502`, `check_target_formats(chunked=True)`).

Source loading (H3). Today `_prepare.py:577-581` skips loading for `--chunked` and loads lazily otherwise. S2 loads `--chunked` sources through `_load_sources_from_config(..., lazy=True, lazy_only=True)` (`run/_execute.py:352-387`). With `lazy_only`, a materialized source that `lazy_sources` (`io/_lazy.py:18`) does not return is refused with `UsageRefusal(..., code="chunked_source_not_lazy")` before `read_source` is called for any table, so no source is read whole in the CLI. After E6 no format base `--chunked` reads hits this refusal; it guards G3 by construction for any later format. `UsageRefusal` is already in `usage_error_types()`, so exit 1.

On CLI main only the chunked factory calls `_value_free_failure` and `_value_free` (`run/_execute.py:216-238`). The plain `run_pipeline` call has no such wrapper. Under the ambient file policy a lazy reader can propagate the decoder's text. S2 keeps `run/_value_free.py::_value_free_failure(exc, reading=True)` at the source-read boundary used by the shared `run_pipeline` path, covering source setup, facts, resident fallback reads and batch iteration in both modes. Limit translation to read operations so sink and execution failures keep their classifications. Raise a replacement after leaving the handler, with no cause or context. Propagate capacity failures to exit 5. One CLI classifier preserves the existing refusal code and message across formats and modes.

Kept refusals: generate tables, `--vault`, quarantine, integrity, subset, `--fidelity`, `--post-validate`, `--post-validate-enforce`, and the engine compatibility check (now inside the engine's strict preflight). `_ChunkedReportFlagError` stays with its exit row; its condition drops `--explain-plan` and its message names only the three report flags and says they read the whole output, which `--chunked` does not keep (H4). Deleted: `_ChunkedFixedWidthError` (E4 and SE3b give fixed-width a lazy reader); its row leaves `exit_codes.py:310-346`. Lifted: `--explain-plan` (the run now returns an `ExecutionResult`). `--no-native --chunked` maps through `_native_gate.run_pipeline_kwargs` as on the plain path; AT-S2c proves no compiled backend ran.

Exit code (H2). `ExecutionError` is not in `usage_error_types()` and `streaming_unavailable` is not a capacity code, so today it would fall through to exit 3 (`exit_codes.py:249-286`). S2 adds one code-keyed rule in `exit_code_for`, beside the `VAULT_TAMPERED` rule (`:268-269`): `getattr(exc, "code", None) == reasons_runtime.STREAMING_UNAVAILABLE` returns `EXIT_USAGE`. The caller asked for a stream the config cannot give, which is a request error. This keeps today's exit 1 for a `PlanCompileError` from `check_chunked_compatibility`, which the engine now wraps in that refusal (`pipeline/_stream.py:73-86`). Row in `tests/unit/test_exit_code_for.py`.

Relationships without integrity under `--chunked`: the sink is passed, the engine defers the gate with `warning.post_scan_output_unreadable`, and the CLI keeps `chunked_key_check_not_run`. AT-S2b pins exit 0 and both warnings. This matches base `--chunked`.

### 4.4 Order in `execute` (plain and chunked)

1. `ctx._sink_unused = sink_unused_reason(ctx)`; `sink = TargetSink(...) if ctx._sink_unused is None else None`, inside `with ExitStack() as stack:`.
2. `run_pipeline(..., sink=sink)`.
3. `post_run_verify` (unchanged).
4. Vault commit (no-sink runs only; unchanged).
5. Sink run: `sink.stage_resident(result.outputs)`. No-sink run: `_write_mask_outputs` as today.
6. Leave the `with` block: the stack publishes every staged target.
7. Row counts from `sink.rows_written()` on a sink run, from `result.outputs` otherwise.

### 4.5 Engine slice E6 (engine repo, first engine train after merge)

Three additive changes, one PR.

- E6a lazy compressed CSV (H3). `_lazy_csv` stops returning None for a compressed CSV (`profile/_lazy_build.py:90-94`, `:137`). `read_csv_source` (`profile/_csv_reader.py:514`) takes an explicit `compression` that `CsvLazySource` infers once from the declared path name with pandas' own `infer_compression` (the rule `csv_is_compressed` already uses, `:581-589`). The inference is from the name because a rooted file policy hands pandas a descriptor path with no suffix (`:586-588`). Reads stay on the engine's one CSV reader, pandas `read_csv(chunksize=)`, which decompresses as a stream; no second reader is added. The facts pass and the batch read each decompress once, with one chunk in memory, as for a plain CSV today. Identity checks (`LazyFileIdentity`) apply to the compressed file unchanged. A decoder failure mid-stream keeps the value-free coded refusal that CLI AT-B3 pins (`tests/e2e/chunked_route/test_chunked_read_failures.py:90-100`). `_csv_reader.py` is 598 lines: the builder offsets the added lines inside the file or records a census entry under the 600/700 rule; no cap is raised.
- E6b `/result/route/sink` (M6). `Route` (`run_result/_model.py:276-280`) gains `sink: SafeRef | None = None`; `build_run_result` (`run_result/_build.py:203`) gains `sink: str | None = None` and passes it to `_route`. An optional field added under `/v1` is allowed by the model's own rule (`_model.py:1-15`, compatibility contract section 3.1); the derived read model reads a document without it. The CLI passes `"used"` or one `SINK_UNUSED_CODES` member; `SafeRef` refuses free text.
- E6c contract text. `docs/compatibility-contract.md` documents `spill_parent`, `committed_table_path` and `bounded_write_batches` as optional duck-typed sink members a caller's sink may provide (today only `ParquetTransactionalSink.spill_parent` is described, `:1212-1213`, and the marker is undocumented), plus the E6a and E6b additions. CHANGELOG entries.

## 5. Enumerations

### 5.1 Exit paths

- exit 0: run completes, stack publishes (`src/decoy/cli/run/_flow.py:256` commits `LATEST`).
- exit 1: `--chunked` refusal from `_prepare.py:473-514` (kept rows, including `_ChunkedReportFlagError` for the three report flags), `chunked_source_not_lazy`, or engine `runtime.streaming_unavailable` through the new code-keyed rule in `exit_code_for` (H2; without it this would be exit 3).
- exit 3: engine failure, sink misuse, disk error; stack unwinds, nothing published.
- exit 4: post-scan block, only on no-sink runs (the sink is never passed when the gate applies outside `--chunked`).
- exit 5: engine capacity refusals (NONFK-OOM) before the read; no stage opened.
- `KeyboardInterrupt`: stack unwinds; `_flow.py:227-230` `abandon()`.

### 5.2 Routes

- auto-chunk lane with sink: streamed output (`execution/_chunked_output_sink.py:564-597` `stream_table`).
- full-frame or sequential with sink: one `write` per table (`execution/_sequential.py:565`).
- mixed generate and mask with sink (`execution/_pipeline_mixed_route.py:223`); streamed generation (`generation/_streamed.py:527`), which streams only because `TargetSink.bounded_write_batches` is true (`:406`, `:415-420`; else `sink_not_bounded`).
- out-of-core on a plain run: never gets the sink in V1 (it needs relationships, so `sink_unused_reason` returns `post_scan`).
- no sink: today's collector or resident result (`_pipeline_auto_chunk.py:488-525`).
- strict stream (`--chunked`): lane only, or forced out-of-core when the FK gate allows (E1a, `pipeline/_stream.py:205-240`); refusal otherwise. This is the one route where out-of-core gets the sink: `--chunked` with relationships and no integrity (4.3).

### 5.3 FK shapes

- No relationships: sink applies.
- Relationships, plain run: no sink (`post_scan`), today's path, gate runs and blocks.
- Relationships under `--chunked`, no integrity: sink passed, each table on its own, key check deferred with a warning (4.3).
- `post_scan.integrity: true` under `--chunked`: refused before staging, as today (`src/decoy/cli/run/_execute.py:247-253`).

### 5.4 Fields

- `--json` `/result/route/sink`: `"used"` or one `SINK_UNUSED_CODES` member. Built by the one result builder: `src/decoy/cli/run/_result.py:193-210` passes `sink=ctx._sink_unused or "used"` to `build_run_result` (engine E6b); when no execution ran, the whole route object stays null as today (`_result.py:204`). Shape snapshot `tests/fixtures/release_freeze/json-shapes.json` gains `"/result/route/sink": "string"` beside `:478-482`; `scripts/release/check_shape_changelog.py` then requires the CHANGELOG line in the same PR.
- The `--json` envelope built in `_render.py:117-141` gains no top-level key; the sink fact is only at `/result/route/sink` (round 1 placed it beside `native_route` at `:136-141`, which would have made a second source).
- Human summary: a `Sink` fact beside the `Route` fact (`src/decoy/cli/run/_render.py:176-177`).
- Summary fact `Sink`: `used` or the code.
- `table_records` `rows`: from `rows_written()` on a sink run (`src/decoy/cli/io/_targets.py:781-793`).
- Evidence and notify row counts: same source.

### 5.5 Output surfaces

- Target files (CSV, compressed CSV, Parquet): same bytes and schema as without a sink.
- Engine hold-back spill under `spill_parent`: private, removed at close.
- Quarantine sidecar: unchanged placement (`src/decoy/cli/io/_layout.py:590-602`).
- Post-scan report: unchanged (no sink when the gate applies).
- `LATEST` and `current`: unchanged (`_layout.py:604-629`).
- stderr warnings: `chunked_key_check_not_run` kept; no new warning.

## 6. Class table

| # | Class | Closing structure | Guard test | Mutation |
|---|---|---|---|---|
| 1 | value-bearing output | sink errors use fixed text with no table name and no value; S2 moves the chunked factory’s read protection to the shared read path in 4.3 | `tests/unit/run_stream/test_target_sink.py::test_errors_carry_no_values` with a canary cell value and a canary table name, plus AT-S2i on both CLI routes | put the batch repr in the double-write error or bypass the read classifier for a late UTF-8 failure |
| 2 | cleanup on every exit path | one `ExitStack` owned by `execute`; `abort()` does no I/O; `spill_parent` never None, so a spill cannot fail for want of a folder | AT-S1c (engine fault after table 1), AT-S1d (`KeyboardInterrupt` after commit), AT-S1l (absolute targets, forced spill) | make `abort()` call `stack.close()` (publishes): AT-S1c goes red |
| 3 | state machine | `open -> committed or aborted`; writes refused after either; errors raised outside `except` (catalog class 3) | `test_target_sink.py::test_state_table` over every (state, call) pair, asserting `__cause__` and `__context__` are None | allow `write_batches` after `commit` |
| 4 | route parity and silent fallback | `sink_unused_reason` is the one predicate; reason code always recorded; `bounded_write_batches` set so generation streams | AT-S1a parity over routes in 5.2; AT-S1k (generation reason `eligible`); `tests/sentry/run/test_one_sink_choke_point.py` | return `None` for `--vault`: engine B0 refusal makes AT-S1f red; drop the marker: AT-S1k red |
| 5 | referential integrity | no sink when `post_scan_gate_applies`, so the orphan block is unchanged | AT-S1e (relationship run blocks with exit 4, nothing published) | drop the `post_scan` arm |
| 6 | untrusted input | table names from the engine are checked against declared targets; paths only through `layout.place_target` | `test_target_sink.py::test_unknown_table_is_counted_not_written` | write a file for an undeclared table name |
| 7 | toctou check-then-use | lazy source identity is checked by the engine (`lazy_source_changed`), compressed CSV included after E6a; the CLI adds no stat-then-open | engine AT-E2a (merged) and AT-E6a's identity cell for a `.csv.gz`; no CLI AT | none in CLI code: N/A because the check is engine-owned; E6 mutation: skip the identity window for compressed files |
| 8 | weak test | every AT names a mutation; parity tests compare bytes, not row counts; the alias guard is tested where it can fire (unit, AT-S1i) | mutation list in 7 | narrow AT-S1a to row counts: reviewer rejects |
| 9 | refactor drift | S2 deletes `_run_chunked_mask`, `_masked_chunks`, `iter_source_chunks`, `source_schema_and_chunks` and `_ChunkedFixedWidthError`, with no re-export | `tests/sentry/run/test_one_run_pipeline.py` (exact `(path, function)` allowlist, 8) | keep a call to `run_mask_chunked` |
| 10 | frozen contract | `--json` gains `/result/route/sink` (additive optional field, engine E6b); `--chunked` exit codes for kept refusals unchanged; `streaming_unavailable` exits 1; one exit row removed pre-GA; declared changes listed in 13 | `tests/sentry/release/test_frozen_surface_map.py`, the `--json` shape snapshot, `tests/unit/test_exit_code_for.py` | rename `/result/route/sink` without a snapshot update; drop the code-keyed exit rule |

## 7. Acceptance tests (red first)

All land before the code that turns them green. E6 rows in the engine repo; S1, S2 and M1 rows in the CLI repo.

| AT | Slice | Input | Expect | Mutation that turns it red |
|---|---|---|---|---|
| AT-E6a | E6 | `.csv.gz` and `.csv.bz2` sources (header, quoting, empty file) under the default and a rooted file policy | `build_lazy_source` returns a `CsvLazySource`; its batches equal the resident read; `num_rows` matches; replacing the file between facts and read raises `lazy_source_changed` | restore the `csv_is_compressed` early return |
| AT-E6b | E6 | gzip stream with a plaintext tail (the CLI AT-B3 shape) read lazily | the coded value-free refusal; no cell text in the message, `__context__` None | pass the decoder's own message through |
| AT-E6c | E6 | `build_run_result(sink="used")`, `sink="run.sink_unused.post_scan"`, `sink=None`, and free text; an older document without the field read by the read model | first three write and round-trip; free text refused by `SafeRef`; the older document reads with sink defaulting to None. Read the next-minor corpus fixture through `RunResultRead` and assert its route retains `sink="used"` | type `sink` as `str` |
| AT-S1a | S1 | the CLI format fixture set (CSV, `.csv.gz`, Parquet; nullable int, decimal, dictionary, empty source) run with and without the sink (sink forced off by a test seam on `sink_unused_reason`) | identical CSV bytes and Parquet schema plus values per target | write each batch through `write_table` (CSV gets a header per batch) |
| AT-S1b | S1 | 8M-row single Parquet table, chunk 100k, run in a subprocess under RSS sampling (Linux VM); 8M rows is eight row-group caps, so the bound in G1 is well below table size | peak RSS of the sink run below the same-host no-sink run by at least half the output table's Arrow size (bar set from the run measured at S1 FRAME, recorded in the S1 report); `/result/route/sink == "used"` | stage via `pa.concat_tables` in `write_batches` |
| AT-S1c | S1 | fault hook raising inside the engine after table 1 of 2 streamed | exit 3; neither target exists; no temp left beside targets | `abort()` closes the stack |
| AT-S1d | S1 | `KeyboardInterrupt` hook after engine `commit()`, before step 6 | no target exists; `LATEST` unchanged | publish in `commit()` |
| AT-S1e | S1 | relationship config with an orphan | exit 4, `/result/route/sink == "run.sink_unused.post_scan"`, nothing published | drop the `post_scan` arm |
| AT-S1f | S1 | one cell per `SINK_UNUSED_CODES` member that can fire, plus `used` | the code in summary and `--json` | swap two arms |
| AT-S1g | S1 | `--native` run on the lane with a companion (Dell) and without | with: exit 0 and a native label; without: refusal "no output was written", nothing published | publish before `post_run_verify` |
| AT-S1h | S1 | empty CSV source to CSV and Parquet targets, sink on | header-only CSV and a zero-row Parquet file equal to the no-sink run | drop the empty-CSV chunk |
| AT-S1i | S1 (unit, `test_target_sink.py`) | `TargetSink` with one targeted table and one targetless table, on each `RunLayout` constructor; call `decoy_engine.quarantine.guard_quarantine_not_aliasing_committed_table(sink, ["t", "untargeted"], output_path)` with `output_path` equal to the placed target, then with a distinct path | equal path: `ValueError`; distinct path: returns; the targetless table never raises `TypeError`. The CLI collision rule (`io/_placement.py:278-303`) refuses equal paths before execute, so an e2e run cannot reach this guard | return `None` from `committed_table_path` |
| AT-S1j | S1 | hold-back spill forced (row group cap lowered by monkeypatch, all-null first chunks), run-folder layout | run succeeds; no `_hold` entry left under the run folder | `spill_parent = None` gives `hold_back_spill_unavailable` |
| AT-S1k | S1 | plain run of a generate table and a mixed generate-and-mask config, with and without the sink | with sink: generation stream reason `eligible` in `quality_metrics`; target bytes equal the no-sink run | drop `bounded_write_batches`: reason `sink_not_bounded` |
| AT-S1l | S1 | every target an absolute path (`RunLayout.fixed`), hold-back spill forced as in AT-S1j | exit 0, same bytes as the no-sink run, no `_hold` left beside the target, no file in the YAML folder after the run | `spill_parent` returns `layout.output_dir()` unchanged (None here): `hold_back_spill_unavailable` |
| Unit sentry | S1 | `test_target_sink.py::test_paths_never_none`, parametrized over the `RunLayout` constructors (`open`, `out_dir` with the folder present and absent, `fixed` with targets whose parent exists and with no file target) | `spill_parent` and `committed_table_path(t)` for a targeted and a targetless table are never None | same mutation as AT-S1l |
| AT-S2a | S2 | every config under `tests/e2e` that base `--chunked` runs, computed at the S2 head (chunked fixture set, FK shapes of 5.3, nullable-int and decimal Parquet from CLI #399, CLI #387's nested-passthrough Parquet fixtures in `tests/e2e/test_run_chunked_parquet.py`, `.csv.gz` sources) | same exit code and same target bytes for the same chunk size as base, with two named exceptions: an empty CSV source now writes a header-only CSV (G4); configs with `validators:` or declared casting are refused (AT-S2g). The list of configs base runs and S2 refuses equals exactly the second exception's set | let the engine regroup row groups (plain `auto` caps) |
| AT-S2b | S2 | `--chunked` with relationships, no integrity | exit 0, `chunked_key_check_not_run` and `post_scan_output_unreadable` both reported | drop the CLI warning |
| AT-S2c | S2 | `--no-native --chunked` with a companion installed | route evidence shows no compiled backend executed | omit `_native_gate.run_pipeline_kwargs` on the chunked branch |
| AT-S2d | S2 | `--chunked` on a fixed-width source, and with `--explain-plan` | both run (refusals removed) and the report renders | keep the old refusal |
| AT-S2e | S2 | `--chunked` on a config with a strategy the lane declines and no FK route | exit 1 (code-keyed rule), reason `streaming_unavailable` and the blocking fact; no source data row read (reader spy) | catch the engine error and fall back to `auto`; or drop the `exit_code_for` rule (exit 3) |
| AT-S2f | S2 | `--chunked` with each of `--fidelity`, `--post-validate`, `--post-validate-enforce` | exit 1, `_ChunkedReportFlagError` naming the flag; no source opened | delete the class (generic `streaming_unavailable` instead) |
| AT-S2g | S2 | `--chunked` on a config with `validators:`, and on one with declared casting | exit 1, `streaming_unavailable` with fact `validators_present` or `declared_casting`; no source data row read | let the CLI skip `validators:` as base did |
| AT-S2h | S2 | `--chunked` with a test seam that makes `lazy_sources` omit one table | exit 1, `chunked_source_not_lazy`, `read_source` never called (spy) | fall back to `read_source` for the missing table |
| AT-S2i | S2 | Re-point `tests/e2e/chunked_route/test_chunked_read_failures.py` to the shared read path. Run every existing case with and without `--chunked`, including late invalid UTF-8, a gzip plaintext tail, corrupt Snappy row group and xz tail. Move the capacity injection from `run_mask_chunked` to actual reader creation and iterator advancement inside the unified run | The file must stay green with every existing assertion unchanged, including JSON and verbose output, exit 3 with the coded refusal, and exit 5 with capacity kind for all three memory exceptions at both stages | bypass the classifier on a late read, or translate a capacity exception into the read refusal |
| AT-M1 | M1 | section 1 sweep of revision 6.5 through 16M rows on the Mac (arm64) and one Linux VM; 10M-row end-to-end `decoy run`; SEQ against OOC for FK jobs at 10k, 100k and 1M | record with numbers, commands, host, engine and CLI versions; no gate threshold | evidence only |

Builder rules for every slice: write the generated tests first and show them red on an assertion; attack your own diff with the mutations above and record the head each ran on; compare against a baseline from the same environment and `uv.lock`; never widen a threshold, loosen a comparison or skip a test; stop and report if a catalogued class repeats.

## 8. Choke points, guard tests and mutations

| Rule | Choke point | Guard test | Seeded mutation |
|---|---|---|---|
| One CLI implementation of `TransactionalSink` and one place a run decides on a sink | `src/decoy/cli/io/_sink.py` (`TargetSink`); `src/decoy/cli/run/_sink_policy.py` (`sink_unused_reason`) | new `tests/sentry/run/test_one_sink_choke_point.py`: AST walk over `src/decoy/` finds every `run_pipeline(...)` call with a `sink=` keyword, every class defining `write_batches`, and every definition of `sink_unused_reason`. Exact `(path, name)` allowlist, size 3: (`src/decoy/cli/run/_execute.py`, `execute`), (`src/decoy/cli/io/_sink.py`, `TargetSink`), (`src/decoy/cli/run/_sink_policy.py`, `sink_unused_reason`) | a second `sink=` call in `run/_sample.py` |
| `io` never imports `run` (H5) | `src/decoy/cli/io/` | same sentry: no module under `src/decoy/cli/io/` imports `decoy.cli.run` in any shape (`import decoy.cli.run`, `import decoy.cli.run._x as y`, `from decoy.cli.run import x`, `from decoy.cli import run`, relative `from ..run import x`), including function-local imports | a function-local `from decoy.cli.run._context import RunContext` in `io/_sink.py` |
| One `run_pipeline` call per CLI run entry, no `run_mask_chunked` in the CLI | `run/_execute.py::execute` | `tests/sentry/run/test_one_run_pipeline.py` (new in S2): AST walk over `src/decoy/cli/run/`. `run_pipeline` calls allowed only at exact `(path, function)`: (`src/decoy/cli/run/_execute.py`, `execute`) and (`src/decoy/cli/run/_execute.py`, `execute_preview`) (`_execute.py:518-530`), ratchet size 2. `run_mask_chunked` banned everywhere under `src/decoy/`. Shapes: direct call, `from decoy_engine import run_mask_chunked as x`, `import decoy_engine as de; de.run_mask_chunked(...)`, `getattr(decoy_engine, "run_mask_chunked")` with a literal name | re-add `run_mask_chunked` under an alias; a third `run_pipeline` call in `execute` |
| Every chunked read-failure cell has a plain-run twin | AT-S2i uses the same parametrized test bodies for both invocations | `tests/sentry/run/test_one_run_pipeline.py::test_read_failure_cells_have_plain_twins` collects the read-failure module in full and groups collected cases by test and all non-route parameters. Require each group to have runnable plain and chunked cases. Fail on collection errors or an empty set | remove only the plain verbose xz case and keep its chunked case |
| One chunked writer | `write_chunked_output` | existing `tests/sentry/baselines/target-writes-allow.json` sentry (`_targets.py:1-12` note) | a `pq.ParquetWriter` in `_sink.py` |
| Sink-unused codes registered | `SINK_UNUSED_CODES` frozenset in `src/decoy/cli/run/_sink_policy.py`, the same module as the predicate | `test_one_sink_choke_point.py` checks every string `sink_unused_reason` returns is a member and every member is reached by AT-S1f | return a literal not in the set |
| `streaming_unavailable` exits 1 | `exit_code_for` (`src/decoy/cli/exit_codes.py:226-286`), the one exit map | new row in `tests/unit/test_exit_code_for.py` | delete the code-keyed rule: the row expects 1, gets 3 |

Scanner scope (catalog class 5): the shapes listed above are the covered ones. `eval`, `importlib.import_module` with a computed name, and a `getattr` with a non-literal name are deliberate evasion and V2-LOG.

## 9. Hostile corpus

- Engine calls `write` for a table whose target is `fixed_width`: cannot happen because `sink_unused_reason` returns `target_format`; the guard cell forces the call and expects a refusal.
- A table name containing a path separator: the engine validates names; `TargetSink` only looks names up in `targets`, never builds a path from them.
- Two tables targeting the same path: today's gate collision rule (`_placement.py`) refuses before execute.
- `--out-dir` on a path that does not exist yet: `place_target` makes it 0700 on first use (`_layout.py:566-588`), and `spill_parent` makes it the same way if a spill comes first (4.1).
- Every target an absolute path: the layout is fixed and `output_dir()` is None; `spill_parent` and `committed_table_path` fall back as 4.1 says (AT-S1l, unit sentry).
- A Parquet chunk whose schema drifts: `write_chunked_output` writes with the first schema and `ParquetWriter` raises; engine fixes one type per column first (CLI #399).

## 10. Owner and Tech lead questions

- RS-Q1 (Tech lead, cross-row order; default kind). Build the target sink on today's CLI staging seam now, or wait for DELIV C2a's `DeliverySink`? (a) Now, on `write_chunked_output(defer=)`; DELIV C2a then swaps the stage inside `_sink.py` and carries the `--chunked` relationship-only missing-report exception (4.3) into its missing-report decision. **Recommended:** row 63a closes without waiting on five DELIV slices, there is still one stage seam, and DELIV C2a gets one branch to move instead of two. (b) Keep revision 6.5's order (C1a after DELIV C2a, C1b after C2b, C2 after C5). Cost: row 63a stays open until DELIV is nearly done.
- RS-Q8 (owner, revision 6.5 Q8, never answered; default kind). Sink on relationship runs? (a) No sink when `post_scan_gate_applies`; output of those runs stays resident. **Recommended:** keeps the orphan block. (b) An engine slice teaches the post-scan gate to read a CLI sink. Applied by default under the 2026-11-23 rule when S1 starts if unanswered.
- RS-Q9 (owner, new in round 2; default kind). `--chunked` with `validators:` or declared casting: base `--chunked` ran these (validators silently skipped). Under strict stream the engine keeps that output resident and refuses (`_chunked_output_sink.py:110-115`). (a) Accept the refusal in V1 as a declared Breaking change: the operator runs without `--chunked`, which after S1 still reads lazily and runs the validators. **Recommended:** a coded refusal is safer than a run that skips validators without saying so, and lifting it needs an engine change to stream declared casting and validators, which is not established for this lane. (b) An engine slice streams declared casting before V1. Cost: new engine work on the F06 publish order; it would delay S2. Applied by default when S2 starts if unanswered.

All three are in `10_Projects/decoy/OWNER-QUESTIONS.md`.

### 10.1 DELIV plan amendments (ship with S1, M5)

RS-Q1 (a) makes four places in the DELIV plan stale (engine branch `plan/deliv` `800178c42`, `docs/plans/2026-11-12-deliv.md`). The S1 builder pushes these edits to `plan/deliv` before S1 merges, and the S1 gate checks that they are there:

1. Line 96, "RUN-STREAM C1a starts after C2a": replace with "RUN-STREAM S1 (target sink) is built before C2a on `write_chunked_output(defer=)`; C2a moves that one staging seam inside `cli/io/_sink.py`."
2. Lines 807-812, the C1a seam (`DeliverySink.stage_dir()`, `staged_path(table)`): replace with "RUN-STREAM `TargetSink` (`cli/io/_sink.py`) stages through `write_chunked_output(defer=stack)`. C2a swaps that call for the `DeliverySink` stage and keeps `TargetSink`'s members (`spill_parent`, `committed_table_path`, `bounded_write_batches`) and its never-None rule. No `stage_dir` or `staged_path` member is needed."
3. Section 6.3 Routes, lines 1043-1044: the plain route writes through `TargetSink` on a sink run and `_write_mask_outputs` otherwise; the chunked route is `execute` with `execution_mode="stream"` through `TargetSink`; `_run_chunked_mask` no longer exists.
4. G-ONE-DELIVERY-SINK (lines 1053-1060): add (`src/decoy/cli/io/_sink.py`, `TargetSink.write_batches`) to the exact `(path, name)` allowlist of `write_chunked_output` callers until C2a moves the call into `_delivery.py`, then remove it in C2a (the ratchet shrinks).

## 11. Reuse inventory

| Need | Reused | Where |
|---|---|---|
| batch writer, deferred publish, ledger | `write_chunked_output`, `_staged_chunked`, `_publication` | `src/decoy/cli/io/_targets.py:632-778` |
| atomic temp beside target | `staged_local_target` | `src/decoy/_atomic.py:440` |
| path placement | `RunLayout.place_target`, `output_dir` | `src/decoy/cli/io/_layout.py:566`, `:631` |
| sink protocol | `TransactionalSink` | engine `execution/_transactional_sink.py:75` |
| relationship decision | `post_scan_gate_applies` | engine `config/_post_scan.py:167` |
| native evidence check | `post_run_verify`, `classify_route` | `src/decoy/_native_gate.py:445-480` |
| strict stream preflight | E1a | engine `run_pipeline(execution_mode="stream")` |
| benchmarks | `bench_sink.py`, `bench_lazy.py`, `bench_nonfk_fallthrough.py e2e` | engine `scripts/bench-auto-chunk/` |
| lazy source loading | `lazy_sources`, `_load_sources_from_config(lazy=True)` | `src/decoy/cli/io/_lazy.py:18`, `src/decoy/cli/run/_execute.py:352-387` |
| one CSV reader and its compression rule | `read_csv_source`, `csv_is_compressed` (`infer_compression`) | engine `profile/_csv_reader.py:514`, `:581` |
| run result builder | `build_run_result`, `Route` | engine `run_result/_build.py:203`, `_model.py:276` |
| alias guard (unit test target) | `guard_quarantine_not_aliasing_committed_table` | engine `quarantine.py:504` |
| exit map | `exit_code_for` | `src/decoy/cli/exit_codes.py:195` |

## 12. Placement (CLI CODEMAP "Where Things Go"; engine CODEMAP rows 106, 128, 284)

| File | Kind | CODEMAP row | Slice | Expected lines |
|---|---|---|---|---|
| E `src/decoy_engine/profile/_lazy_build.py` | compressed CSV gets the lazy builder | engine `CODEMAP.md:128` | E6 | 144 to about 140 |
| E `src/decoy_engine/profile/_lazy_csv.py` | infer `compression` from the declared name, pass it on | engine `CODEMAP.md:128` | E6 | 229 to about 240 |
| E `src/decoy_engine/profile/_csv_reader.py` | `compression` argument on `read_csv_source` | engine `CODEMAP.md:128` (one CSV reader) | E6 | 598 to at most 600, or a census entry |
| E `src/decoy_engine/run_result/_model.py`, `_build.py` | `Route.sink`, `build_run_result(sink=)` | engine `CODEMAP.md:106` | E6 | 416 to about 418; 277 to about 281 |
| E `docs/compatibility-contract.md`, `CHANGELOG.md` | optional sink members, `Route.sink`, lazy compressed CSV | existing | E6 | small |
| E `tests/snapshots/frozen_schemas/run-result.schema.json` | regenerate the serialization schema with `python scripts/release/frozen_schemas.py --write` and review the optional field delta | existing frozen schema | E6 | generated |
| E `scripts/release/frozen_schemas.py`, `tests/snapshots/test_frozen_schemas.py` | use the existing generator and run its snapshot guard | existing release tooling and tests | E6 | unchanged |
| E `docs/frozen-surfaces.md` | record the optional route field in the run-result surface entry | existing inventory | E6 | small |
| E `tests/integration/compat_corpus/run_result/run-result-v1-next-minor.json` | add `route.sink="used"` to the existing next-minor cell, preserving its registry-version coverage. AT-E6c also reads the original v1 fixture without the field | existing run-result corpus | E6 | fixture edit |
| E `tests/unit/profile/test_lazy_csv_compressed.py`, `tests/unit/run_result/test_route_sink.py` | new: AT-E6a, b, c | engine `CODEMAP.md:284` | E6 | about 140, about 60 |
| `src/decoy/cli/io/_sink.py` | new: `TargetSink` (plain arguments, no `cli.run` import) | "Source readers and target writers" (`CODEMAP.md:55`) | S1 | about 200 |
| `src/decoy/cli/io/__init__.py` | export `TargetSink`; S2 drops two exports | same | S1, S2 | 323 to about 322 |
| `src/decoy/cli/run/_sink_policy.py` | new: `sink_unused_reason`, `SINK_UNUSED_CODES` | "`decoy run` internals" (`CODEMAP.md:52`) | S1 | about 60 |
| `src/decoy/cli/run/_execute.py` | sink in the plain branch (S1); one branch, chunked code deleted, `lazy_only` loading (S2) | "`decoy run` internals" (`CODEMAP.md:52`, 600-line cap) | S1, S2 | 540 to about 575 (S1), about 340 (S2) |
| `src/decoy/cli/run/_result.py` | pass `sink=` to `build_run_result` | same | S1 | 446 to about 449 |
| `src/decoy/cli/run/_render.py` | `Sink` fact beside `Route` | same | S1 | 239 to about 242 |
| `src/decoy/cli/run/_prepare.py` | fixed-width refusal deleted; report-flag refusal narrowed; `--chunked` loads sources lazy-only (`:577-581`) | same | S2 | 592 to about 575 |
| `src/decoy/cli/_sources.py` | `iter_source_chunks`, `source_schema_and_chunks` deleted | today's exception, moving under H-1 | S2 | 578 to about 500 |
| `src/decoy/cli/exit_codes.py` | `_ChunkedFixedWidthError` row removed; code-keyed `streaming_unavailable` rule added | existing | S2 | 374 to about 373 |
| `src/decoy/cli/io/_targets.py` | no change | | | 793 |
| `pyproject.toml`, `uv.lock` | pin `decoy-engine==` the E6 train version | existing | S1 | small |
| `tests/fixtures/release_freeze/json-shapes.json` | `/result/route/sink` | existing | S1 | plus 1 |
| `tests/unit/run_stream/test_target_sink.py` | new: state table, paths-never-None sentry, AT-S1i | `tests/unit/run_stream/` (`CODEMAP.md:55`) | S1 | about 300 |
| `tests/unit/test_exit_code_for.py` | one row | existing | S2 | plus about 8 |
| `tests/e2e/run_stream/test_sink_run.py` | new: AT-S1a, c to h, j to l | `tests/e2e/run_stream/` | S1 | about 380 |
| `tests/e2e/run_stream/test_sink_rss.py` | new: AT-S1b, Linux marker | same | S1 | about 90 |
| `tests/sentry/run/test_one_sink_choke_point.py` | new, includes the `io` never imports `run` rule | `tests/sentry/run/` (`CODEMAP.md:73`) | S1 | about 160 |
| `tests/e2e/run_stream/test_chunked_unified.py` | new: AT-S2a to h | `tests/e2e/run_stream/` | S2 | about 420 |
| `tests/e2e/chunked_route/test_chunked_read_failures.py` | AT-S2i, both route variants and re-pointed fault injection | existing read-failure suite | S2 | small |
| `tests/sentry/run/test_one_run_pipeline.py` | new, includes the AT-S2i twin guard | `tests/sentry/run/` | S2 | about 110 |
| `docs/records/2026-12-xx-run-stream-m1.md` | new: AT-M1 record | `docs/records/` (`CODEMAP.md:84`) | M1 | about 150 |
| `CHANGELOG.md`, `docs/cli-reference.md`, `decoy explain chunked` text | update | existing | S1, S2 | small |

E marks engine files. No new package. `src/decoy/cli/io/` holds 15 modules and `src/decoy/cli/run/` 14, both under the 25 fan-out cap after one new module each. `_execute.py` stays under the 600-line `run/` cap in S1 because the sink body is in `io/_sink.py` and the policy in `run/_sink_policy.py`. Existing tests that call `_run_chunked_mask` directly (CLI #399 deviation 1) move to the engine path or are deleted with the function in S2; each moved or deleted test is listed in the S2 report, which is a full-suite trigger. The S1 pin bump changes `uv.lock`, also a full-suite trigger.

## 13. Frozen contracts touched

- `--json`: additive optional `/result/route/sink` in the `decoy-run-result/v1` document (engine E6b); the shape snapshot and CHANGELOG update in S1. The envelope gets no new top-level key.
- `decoy run --chunked`, kept: same flags and exit codes for the kept refusals, including `_ChunkedReportFlagError` for `--fidelity`, `--post-validate` and `--post-validate-enforce` (its message drops `--explain-plan`). Route label now from `route_summary` like a plain run.
- `decoy run --chunked`, changed (pre-GA, CHANGELOG "Breaking" lines, each pinned by an AT):
  - fixed-width sources run (refusal removed; AT-S2d);
  - `--explain-plan` runs (AT-S2d);
  - `validators:` configs are refused with `streaming_unavailable` and fact `validators_present`; base `--chunked` ran them and skipped the validators (AT-S2g, RS-Q9);
  - declared-casting configs are refused with fact `declared_casting`; base `--chunked` ran those its compatibility check admitted (AT-S2g, RS-Q9);
  - a config no streaming route takes exits 1 with `streaming_unavailable` instead of a CLI refusal or a compatibility `PlanCompileError` (AT-S2e);
  - an empty CSV source writes a header-only CSV; base wrote no file (AT-S2a);
  - `chunked_source_not_lazy` is a new refusal code; no base-supported format reaches it after E6 (AT-S2h).
- Exit-code map: one exception row removed (`_ChunkedFixedWidthError`, `exit_codes.py:310-346`); one code-keyed rule added in `exit_code_for` so `runtime.streaming_unavailable` exits 1 (`tests/unit/test_exit_code_for.py`).
- Engine contract: E6 adds the optional field and documents `spill_parent`, `committed_table_path` and `bounded_write_batches` as optional sink members; `TransactionalSink` and `execution_mode="stream"` are read, not changed.

## 14. Slices

One PR per slice. Engine half: E6. CLI half: S1 and S2. Release: the first engine train after E6 merges, then CLI 1.0.0 (and 1.0.0-rc.1).

| Slice | Repo | Replaces | Contents | Files max | Lines max | Waits on | Gate |
|---|---|---|---|---:|---:|---|---|
| E6 LAZY-GZ-AND-ROUTE-SINK | engine | new (round 2) | 4.5: lazy compressed CSV, `Route.sink`, contract text; AT-E6a to c, frozen schema and corpus cell | 12 | 450 | none | Dennis, then Codex; full suite (serialization contract change) |
| S1 TARGET-SINK | CLI | old C1a and C1b | `io/_sink.py`, `run/_sink_policy.py`, sink in the plain branch, `_result.py` and summary, shape snapshot, pin bump, AT-S1a to l and the unit sentry, choke-point sentry, CHANGELOG; the DELIV plan amendments of 10.1 pushed to engine `plan/deliv` before S1 merges | 16 | 1100 | RS-Q1 (a) or its default; the engine train carrying E6 released | Dennis, then Codex; full suite (`uv.lock`, frozen `--json` shape) |
| S2 STRICT-CHUNKED | CLI | old C2 | `--chunked` onto `run_pipeline(execution_mode="stream", sink=...)` with lazy-only loading; delete the chunked path and the fixed-width refusal; narrow the report-flag refusal; exit rule; AT-S2a to i, including the existing read-failure suite and its plain-run twins; one-pipeline sentry; CHANGELOG Breaking lines; `explain chunked` and reference text | 14 | 1000 (net negative source) | S1 merged; CLI engine pin carrying E6a in place, including under the section 15 fallback; CLI #387 merged or closed; RS-Q9 answered or defaulted | Dennis, then Codex; full suite (moves and deletes tests) |
| M1 MEASURE | CLI evidence | old M1 | AT-M1 on the Mac and one Linux VM; 10M end-to-end `decoy run`; SEQ against OOC 10k to 1M; record in `docs/records/` | 2 | 200 | S2 merged on CLI main | Codex (record review) |

AT-C2d of revision 6.5 (the installed companion wheel sends `--threads` to native) belongs to the release gate with REL-PKG (row 90), not to S2; M1 runs it if the companion wheel exists by then and says so if not.

## 15. Pre-mortem

- The sink changes CSV bytes at batch boundaries (header per batch, quoting). Guard: AT-S1a compares bytes against the no-sink run over the CSV writer fixture set; `write_chunked_output` already writes one header per file.
- `abort()` publishes by closing the stack. Guard: AT-S1c, mutation 2.
- A relationship run loses its orphan block. Guard: AT-S1e.
- The `--chunked` move refuses a config base `--chunked` ran. Guard: AT-S2a's refusal list must equal exactly the declared set in 13 (validators, declared casting).
- `--chunked` reads a non-lazy source whole in the CLI before the engine refuses it. Guard: `lazy_only` loading and AT-S2h; E6a makes compressed CSV lazy (AT-E6a).
- A fixed-layout run fails on a hold-back spill that passes on main. Guard: AT-S1l and the paths-never-None unit sentry.
- `--chunked` refusals exit 3 instead of 1. Guard: the code-keyed rule and its `test_exit_code_for.py` row; AT-S2e.
- The engine E6 release slips. Effect: S1 and S2 wait. Fallback if no train carries E6 by 2026-12-08: S1 ships the summary fact without `/result/route/sink` and adds the key in S2; the Tech lead decides at that date.
- `--no-native --chunked` silently runs native kernels. Guard: AT-S2c.
- DELIV C2a later builds a second stage beside `_sink.py`. Guard: the choke-point sentry fails on a second `TransactionalSink` implementation; RS-Q1 records that C2a edits `_sink.py`.
- RSS test flakes on shared VMs. Guard: Linux-only marker, ratio against the same-host no-sink run, not an absolute number.

## 16. Follow-ups (not V1)

- `--chunked` for generate tables once GEN-STREAM-ALL lands (the sink already takes streamed generation).
- Sink on relationship runs (RS-Q8 (b)).
- Hold-back spill under the engine scratch root (`open_spill_scratch`) once it is a documented sink member.
- Atomic multi-file publish of a sink run: DELIV C2a.
- Streaming `validators:` and declared casting under `--chunked` (RS-Q9 (b)).
- V2-LOG (L5): `TargetSink` has no `publication_evidence`, so the engine records sink failures with publication state `unknown`. The CLI ledger still records what published. DELIV C2a's `DeliverySink` is the place to add it.
