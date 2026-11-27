# F25 G7-3: materialization cap on the isolated route

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, profiles/local-operations,
feature-dev, testing, security, cross-cutting-concerns, proportionality, reuse-first,
catalogs/recurring-defects.

Risk: R2. Repo: engine. Row 58 (F25) 1.0 acceptance, finding G7 (CLI repo
`docs/roadmap/findings-register.md`, row G7: "The isolated-route materialization cap is still
open"). Owner 2026-11-27: harden existing engine code only, no new CLI surface. Model plan:
G7-1 (`feat/f25-g7-1-bounded-cloud`, `docs/plans/2026-11-25-f25-g7-1-bounded-cloud-reads.md`).
G7-1's shared pieces (`check_ranged_response`, `_exact`, `guarded`, `_memory_text`) solve bounded
network reads; none of them fits a local Parquet readback, so this plan reuses none of them and
copies none of them.

## Context: where the isolated route materializes

`run_pipeline_isolated` (`src/decoy_engine/execution/_isolated_run.py:145`) has a driver (the
caller's process, no memory limit) and a child (a fresh interpreter, optional `RLIMIT`, watched by
the governor). These are the places it holds table data:

| # | Where | What is held | Bounded today by |
|---|---|---|---|
| D1 | driver, `stage_sources` (`src/decoy_engine/execution/_isolated_commit.py:159`) | the caller's `sources`, written to the work root as Parquet or Arrow IPC (disk) | already in the caller's memory; disk is scratch under `scratch_root()` |
| C1 | child, source load (`src/decoy_engine/execution/_isolated_worker.py:95`) | IPC sources read whole; Parquet sources stay lazy (`:97`) | the child's `RLIMIT` (`apply_mem_cap`, `_isolated_worker.py:148`) and the governor |
| C2 | child, full-frame route | every resident table | the same `RLIMIT` and governor; the existing resident-fit checks |
| C3 | child, `StagingSink` (`src/decoy_engine/execution/_isolated_common.py:422`) | output Parquet in the stage (disk) | streamed routes write bounded batches |
| **D2** | **driver, `collect` (`_isolated_commit.py:205`) through `_read_staged` (`:231`)** | **every staged output table, read back whole to fill `IsolatedRunResult.outputs`** | **nothing** |

D2 is the gap. A child that streamed a large output to disk on the out-of-core route exits
cleanly. Then the driver reads the whole output into its own memory, before `publish_unit`
(`_isolated_commit.py:227`). The driver has no limit and no governor, so a large output gets the
caller killed by the kernel OOM killer: the `rc137` the governor exists to prevent
(`src/decoy_engine/execution/_governor.py:1-40`). The readback runs on every completed isolated
run, also when `output_dir` is given and the tables are already on disk, and also for the probe,
which uses only `peak_rss_mb` (`src/decoy_engine/execution/_probe.py:283-300`).

A second defect is on the same line. `collect` catches `(OSError, pa.ArrowException)`
(`_isolated_commit.py:218`). `pyarrow.ArrowMemoryError` subclasses both `MemoryError` and
`ArrowException` (`pyarrow/error.pxi`), so a driver memory failure in the readback is reported
today as `publication_failed`, and a bare `MemoryError` escapes `run_pipeline_isolated` as a raw
exception.

## Guarantee and non-goals

**Guarantee.** Before the driver decodes a staged output table, it checks a strict lower bound on
the bytes it would then hold against the host or cgroup kill ceiling. When the bound is over the
ceiling, the run ends with a coded, value-free refusal (`decoy.isolated_readback_capacity_exceeded`).
Nothing more is read, nothing is published, and the stage is removed. The bound tightens with
reality: tables already read count at their measured buffer bytes. A memory failure during the
readback is a coded memory result, never a publication failure and never a raw exception. A run
whose bound stays at or under the ceiling reads, publishes and returns exactly what `main` does.

Only a strict lower bound can refuse, and only above the kill ceiling, so no run that `main`
completes is refused. That is the rule row 58b sets for quotas (no default limit that refuses 1.0
runs that work) and the rule `_resident_fit` already applies (`RESIDENT_ADMISSION_FRACTION`,
`src/decoy_engine/execution/pipeline/_resident_fit.py:44-46`: it "can prove a fit, never a
refusal").

**The cap, in one line.** Size: the kill ceiling `H` from `out_of_core.detect_effective_memory_bytes`
(cgroup `memory.max`, else host RAM). Default: that detected value; there is no new knob. Relation
to row 58: the scratch manager owns disk bytes and this cap owns driver memory, so they share no
number. Relation to row 58b: 58b quotas are opt-in disk limits with no default; when 58b or
CHUNK-PARALLEL brings an explicit memory budget, this ceiling becomes `min(H, budget)` (V2-LOG).

**Non-goals.**

- Preventing every driver OOM. A table whose floor fits but whose decoded size does not (a
  string-heavy table: the floor counts offsets, not payload) still fails as on `main`. Where Arrow
  raises, it now fails as a coded memory result instead of a publication failure. Row-group
  granularity and a tighter string floor are V2-LOG.
- The child's materialization (C1, C2). It is bounded by its `RLIMIT` and the governor. A coded
  refusal there would be `crashed`, which ends the governor's reroute ladder
  (`_governor.py:381-404`), where `oom_killed` today reroutes to a bounded route.
- Disk bytes (D1, C3). Their registration with the protected scratch manager is row 58 G6; byte
  quotas are row 58b (1.x, opt-in, no default). This slice adds no disk limit.
- The result envelope read (`read_envelope`). It carries `row_errors` without a cap, as the
  in-process `ExecutionResult` does. V2-LOG.
- A caller-set cap, a new parameter or CLI surface (owner question Q3).
- Not reading outputs back when `output_dir` is given. That removes D2 instead of capping it, but
  changes the `IsolatedRunResult.outputs` contract (owner question Q2).

## Behaviour

1. `collect` admits the stage as today (`_names_ok`, `_admit`).
2. For each admitted table, in envelope order, it opens the file once through the file-access
   capability (as `_read_staged` does) and reads the footer row count and Arrow schema
   (`arrow_adapter.parquet_file(handle).metadata.num_rows`, `.schema_arrow`). Nothing is decoded yet.
3. Before each decode it calls the one comparison, new `check_readback` in `_resident_fit.py`:
   `bound = lower_bound_bytes(held + pending)`, all with `charge_pandas=False`. `held` is
   `resident_spec` of the caller's resident `sources` and of each output already read (measured
   buffer bytes, union of buffer ranges). `pending` is `lazy_spec(rows, schema)` of this table and
   every table not yet read (the footer floor). The verdict comes from `resident_fit_verdict`
   (`_resident_fit.py:104`) through `_lower_bound_verdict`, so the rule is the existing one:
   refused only when `bound > H`. `H` is `_kill_ceiling()` (`_resident_fit.py:219`), read once per
   `collect`.
4. On refusal: tables read so far are dropped, the publication transaction is aborted, and
   `collect` returns `ReadbackRefused(fit, receipt)`. `_result_from_envelope`
   (`_isolated_run.py:562`) maps it, through one builder in `_isolated_reason.py`, to
   `IsolatedRunResult(outcome="crashed", reason=ISOLATED_READBACK_CAPACITY_EXCEEDED,
   error=<fixed text with two integers>, outputs=None, publication_receipt=failed_receipt(request)
   when output_dir was given, else None)`, and removes the stage as the other failure paths do.
   Reason context: phase `FINALIZE`, publication `NOT_PUBLISHED`, cleanup confirmed by looking.
5. Otherwise the table is read with the unchanged `arrow_adapter.read_table(handle)`, so the frame,
   chunking and metadata are `main`'s, and step 3 repeats for the next table.
6. After the last table, `publish_unit` runs as today. A refusal can only happen before it.
7. A memory failure while reading (`is_memory_failure`, the predicate the worker already uses) is
   caught before the `(OSError, ArrowException)` arm. It becomes `outcome="crashed"`,
   `reason=decoy.process_out_of_memory`, fixed text, with the same abort and cleanup.
8. Every completed or refused readback records `extra["readback"] = {"kill_ceiling_bytes",
   "floor_bytes", "held_bytes", "tables_read", "tables_staged"}` (ints, or `None` for an unknown
   ceiling). This is how the estimate is checked against reality: `floor_bytes` is the footer floor
   of everything staged, `held_bytes` the measured bytes actually held, and A4 and A10 assert
   `floor_bytes <= held_bytes`.
9. When `H` cannot be detected (`_kill_ceiling()` returns `None`), no check runs and the readback is
   `main`'s.

`crashed` is the right outcome. Output size is the same on every route (the engine is seeded and
deterministic, `_governor.py:26-30`), so a reroute cannot help, and the governor stops on `crashed`
(`_governor.py:381-404`). The probe turns any non-completed run into an inconclusive probe
(`_probe.py:292-300`), which routing already handles.

**Refuse or fall back.** Falling back to the out-of-core route does not help: the child may
already be on it, and D2 is the driver reading the finished output. The only real fallback is to
not read the output back, which is Q2 (b). This plan recommends the refusal for 1.0.

### Design notes

No new module, abstraction or variant: the cap is one more caller of the existing resident-fit
comparison. One fact, one place: the bound formula stays in `_resident_bytes.py`, the ceiling in
`_kill_ceiling`, the comparison in `resident_fit_verdict`, the capacity text in `_errors.py`. The
refusal travels as a typed value (`ReadbackRefused`) instead of a flag argument.

## Failure modes

| Failure | Detected at | Reason code | Value-free | Test |
|---|---|---|---|---|
| Footer floor of outputs plus resident caller sources over `H` | `check_readback`, before the first decode | `decoy.isolated_readback_capacity_exceeded` | fixed summary, two integers | A1, A3 |
| Measured bytes of tables read plus floor of the rest over `H` | `check_readback`, before the next decode | `decoy.isolated_readback_capacity_exceeded` | same | A2 |
| Refusal with `output_dir` | `collect` aborts the transaction before `publish_unit` | same; receipt `failed` | receipt carries codes only | A8 |
| `ArrowMemoryError` or `MemoryError` during a read | `collect`, `is_memory_failure` arm | `decoy.process_out_of_memory` | fixed text, no exception text | A9 |
| Kill ceiling not detectable | `_kill_ceiling()` returns `None` | none; runs as `main` | n/a | A5 |
| Ceiling detection raises another `ExecutionError` | `_kill_ceiling()` re-raises (`_resident_fit.py:224-229`) | that error's code; stage aborted by `_run_isolated`'s `finally` (`_isolated_run.py:396-398`) | its own fixed text | A12 |
| Corrupt staged footer or body | `parquet_file` or `read_table`, unchanged `(OSError, ArrowException)` arm | `decoy.publication_failed` (unchanged) | receipt codes only | A12 |
| Floor formula above reality for some Arrow type (wrong refusal) | property test over the type corpus | n/a (test) | n/a | A10 |
| Governor reroutes a refused run | governor ladder | trip kind `crashed`, outcome `exhausted` after one rung | trip error is the fixed text | A7 |

## Acceptance tests, red first

All cases except A10 run the real `run_pipeline_isolated` with a real child on small tables, and
patch only the driver's kill ceiling (`_resident_fit._kill_ceiling`); the child is a fresh
interpreter and is untouched. A spy on `arrow_adapter.read_table`, as `_isolated_commit` sees it,
records each decode. A4 asserts one spy call per staged table, so the spy is proven wired. Each
case names the guard mutation that must turn it red.

- **A1 pre-read refusal.** Ceiling below the outputs' floor. Outcome `crashed`, reason
  `isolated_readback_capacity_exceeded`, `outputs is None`, zero decodes, stage and work root
  removed. G1: drop the `check_readback` call; the spy sees decodes and the run completes.
- **A2 measured bytes tighten the bound.** Two outputs: `t1` string-heavy (small floor, large
  measured), `t2` numeric. Ceiling with `floor(t1) + floor(t2) < H < measured(t1) + floor(t2)`.
  Refused after one decode; `t2` never decoded. G2: price held tables by their footer floor
  instead of `resident_spec`; both decode and the run completes.
- **A3 caller sources count.** Resident `sources` whose buffer bytes plus the outputs' floor exceed
  `H`, while the outputs' floor alone does not. Refused before the first decode. G3: leave the
  caller sources out of `held`.
- **A4 no refusal at or under the ceiling.** Ceiling equal to the final bound; also a ceiling with
  the bound between `0.85 * H` and `H`. The run completes; `outputs` equal `pq.read_table` of each
  staged file (schema, metadata and `assert_frame_equal` on `to_pandas()`). `extra["readback"]`
  has exact `int` values, `floor_bytes <= held_bytes`, `tables_read == tables_staged`. G4: compare
  against `admission_ceiling_bytes(H)` instead of `H`; the second variant is refused.
- **A5 ceiling unknown.** `_kill_ceiling` returns `None`: completes as `main`,
  `extra["readback"]["kill_ceiling_bytes"] is None`. G5: treat `None` as `0`; refused.
- **A6 value-free refusal.** Canary strings in cell values, column names and table names. On
  refusal, `error` fullmatches
  `^<summary> The figure checked is \d+ bytes and the memory ceiling is \d+ bytes\. <remedy>$`.
  No canary in `error`, `repr(result)`, `result.reason.to_payload()`, `extra`, the receipt, the
  governor trip (A7) or captured logs (`caplog`, all levels). The same check feeds `error + "\n"`
  to the pattern and expects no match. G6: add the table name to the text.
- **A7 governor stops.** `run_job_with_governor` with the patched ceiling: outcome `exhausted` after
  one rung, one trip of kind `crashed`, `reroute_to is None`. G7: return outcome `oom_killed`; the
  governor reroutes and the test sees two or more rungs.
- **A8 nothing published on refusal.** With `output_dir`: the target does not exist afterwards, no
  publication stage remains beside it (listing of the parent), receipt outcome `failed`. G8: move
  `publish_unit` before the readback loop; the target exists.
- **A9 memory failure classified.** The spy raises `pa.ArrowMemoryError` on the second decode; in a
  second run, a bare `MemoryError`. Outcome `crashed`, reason `process_out_of_memory` (not
  `publication_failed`), no exception text in `error`, nothing published, stage removed. G9:
  delete the memory arm; the first variant reports `publication_failed` and the second raises.
- **A10 floor is never above reality.** For a type corpus written through `StagedParquetWriter`
  (int8 to int64, uint, float16/32/64, bool, decimal128, date32, timestamp with and without tz,
  duration, string, large_string, binary, large_binary, fixed_size_binary, dictionary with int8,
  int16, int32 and int64 indexes, struct, list, large_list, map, fixed_size_list, null; each with
  and without nulls; empty tables; several row groups), assert
  `lower_bound_bytes([lazy_spec(pf.metadata.num_rows, pf.schema_arrow, charge_pandas=False)]) <=
  resident_spec(pq.read_table(path)).resident_input_bytes`. Non-vacuity: at least one case per type
  family has a floor above zero. G10: change the string offset width in `_lazy_column_bytes`
  (`src/decoy_engine/execution/pipeline/_resident_bytes.py:183`) from 4 to 16.
- **A11 reason registered.** The registry walk `tests/unit/reasons/test_capacity_reason_codes.py`
  passes with the new code in `CAPACITY_REASON_CODES` (`src/decoy_engine/errors.py:511`); the
  reasons doc and release-pin tests pass with `since=UNRELEASED` and a `changelog.d/` fragment.
  G11: drop the code from `CAPACITY_REASON_CODES`; the registry walk goes red.
- **A12 exit-path matrix.** {pre-read refusal, mid-read refusal, memory failure, corrupt footer,
  detection error} x {with `output_dir`, without}. After each: no stage, no work root, no open
  descriptor left by the readback (`/proc/self/fd` count before and after; Linux only, skipped
  elsewhere with that reason), and the result or raised error matches the failure-mode table.
  G12: skip `pub.txn.abort()` on the refusal path; a stage remains.
- **A13 safe-error producers.** `tests/unit/execution/test_isolated_safe_error.py` gains the refusal
  and the memory result as producers of `IsolatedRunResult.error`; both pass its existing
  no-exception-text checks, and the refusal error has `__cause__ is None and __context__ is None`
  where an error object exists. Mutation: build `error` from `str(exc)` in the memory arm.

Existing suites that must stay green unchanged: `tests/unit/execution/test_isolated_run.py`,
`test_isolated_oom_classification.py`, `tests/unit/execution/publication/` (route outcome matrix,
marker corpus), `tests/integration/test_f29_isolation.py`, `tests/unit/execution/test_resident_fit*.py`.

## Choke points

| Choke point | Where | Callers | Guard mutation |
|---|---|---|---|
| The one ceiling comparison | `resident_fit_verdict`, reached through new `check_readback(held, pending, *, kill_ceiling_bytes=None) -> ResidentFit` in `execution/pipeline/_resident_fit.py`, exported from `execution/pipeline/__init__.py` | `check_pre_read`, `check_pre_transform` (existing), `_isolated_commit.collect` (new) | G4 |
| The one bound formula | `lower_bound_bytes`, `lazy_spec`, `resident_spec` (`_resident_bytes.py:50`, `:133`, `:173`) | the same callers | G2, G10 |
| The one kill-ceiling source | `_kill_ceiling` (`_resident_fit.py:219`) over `detect_effective_memory_bytes` (`src/decoy_engine/execution/out_of_core/_budget.py:332`) | the same callers | G5 |
| The one isolated readback | `collect` and `_read_staged` (`_isolated_commit.py:205`, `:231`); every readback of a child's stage goes through it, for the probe, the governor and direct callers | `_result_from_envelope` (`_isolated_run.py:573`) | G1, G8 |
| The capacity message | new `capacity_message(code, *, needed_bytes, kill_ceiling_bytes)` in `execution/_errors.py`; `nonfk_full_frame_capacity_error` (`src/decoy_engine/execution/_errors.py:87`) is rewritten to use it, so both refusals share one text | both refusals | G6 |
| The refusal result | new `readback_refused(...)` in `_isolated_reason.py`, beside `envelope_failure` (`:68`) and `commit_reason` (`:101`) | `_result_from_envelope` | G7 |
| The memory predicate | `is_memory_failure` (already shared by the worker and `in_process_failure`) | `collect` (new) | G9 |
| Capacity code list | `CAPACITY_REASON_CODES` (`errors.py:511`); the CLI derives exit 5 from it | registry walk test | G11 |

## Established solutions

Searches run (online): Spark configuration docs and SPARK-3466 for `spark.driver.maxResultSize`;
the Databricks knowledge base article on the maxResultSize failure; Ray object spilling docs;
DuckDB memory management docs (already cited in `out_of_core/_budget.py:1-16`); PostgreSQL
`temp_file_limit` docs; Linux cgroup v2 `memory.max` docs; the Parquet format metadata spec
(`RowGroup.total_byte_size`); `pyarrow/error.pxi` for the `ArrowMemoryError` class tree.
Codebase: `detect_effective_memory_bytes`, `check_pre_read`, `lower_bound_bytes`,
`ArrowMemoryError`, consumers of `IsolatedRunResult.outputs` (probe, governor, platform), and the
F25 scratch plan (`docs/plans/2026-10-29-f25-protected-scratch-quotas-orphan.md`, rows T11, T12).

| Option | What it gives | Decision |
|---|---|---|
| Spark `spark.driver.maxResultSize` (default 1g; SPARK-3466, <https://issues.apache.org/jira/browse/SPARK-3466>; Databricks KB <https://kb.databricks.com/jobs/job-fails-maxresultsize-exception.html>). An action whose results exceed the limit is aborted, because `collect` can OOM the driver | the same problem (worker results collected into the driver) answered by a refusal | followed for the shape: refuse at the driver before the data arrives. Not followed for the fixed default: a 1 GiB default would refuse 1.0 runs that work, against row 58b |
| Spark guidance to write results to storage instead of `collect` (same KB article) | the result never enters driver memory | the answer behind Q2 option (b); changes the `outputs` contract; V2-LOG |
| Ray object spilling; DuckDB `memory_limit` with `temp_directory` | spill to disk instead of failing | not applicable to D2: the data is already on disk. Rerouting the child out of core does not change output size |
| PostgreSQL `temp_file_limit` | coded error when a query would pass a resource limit | same refusal pattern, for disk; disk stays with row 58b |
| cgroup v2 `memory.max`, host RAM as fallback | the number the kernel OOM-kills against | used, through the existing `detect_effective_memory_bytes` |
| Parquet `RowGroup.total_byte_size` as the estimate | a closer size for string columns | not used to refuse: it is not a floor on decoded Arrow bytes (dictionary columns read back as dictionaries can be smaller). V2-LOG as a tighter string floor |
| `pyarrow/error.pxi`: `class ArrowMemoryError(MemoryError, ArrowException)` | why the current `except` misfiles memory failures | the memory arm is ordered before the Arrow arm |
| In-repo `_resident_fit.check_pre_read` (engine #777): footer floor against the kill ceiling before a lazy source is read whole | the exact rule this slice needs, already reviewed | reused: same formula, same ceiling, same verdict ladder. No custom estimator is written |

## Enumerations

### Exit paths

- `_names_ok` refuses the envelope names: `failed_receipt`, transaction aborted (`src/decoy_engine/execution/_isolated_commit.py:216`).
- `_admit` refuses the stage or raises `OSError`: `failed_receipt` (`src/decoy_engine/execution/_isolated_commit.py:187`, `:218`).
- New: `check_readback` refuses before a decode: `ReadbackRefused`, tables dropped, transaction aborted.
- New: memory failure during a decode: process-out-of-memory result, transaction aborted.
- `parquet_file` or `read_table` raises an Arrow or OS error: `failed_receipt` (unchanged, `:218`).
- `publish_unit` does not commit: its receipt (`src/decoy_engine/execution/_isolated_commit.py:227`).
- `_result_from_envelope` removes the stage when there is no `output_dir` or on failure (`src/decoy_engine/execution/_isolated_run.py:575`).
- `_run_isolated` always aborts the transaction and closes the scratch work root (`src/decoy_engine/execution/_isolated_run.py:396-398`).

### Routes

- Isolated subprocess, child on any route (full frame, out of core, sequential, auto-chunk lane, multi-table split), resident or streamed outputs: the readback runs and the cap applies (`src/decoy_engine/execution/_isolated_worker.py:160`).
- Probe (`src/decoy_engine/execution/_probe.py:283`): forced full frame on a downscaled job; the cap applies; a refusal is an inconclusive probe.
- Governor (`src/decoy_engine/execution/_governor.py:381`): every rung; a refusal ends the ladder.
- In-process fallback, `isolate=False` and re-entry (`src/decoy_engine/execution/_isolated_run.py:314`): no readback; outputs are already in memory; unchanged.

### FK shapes

N/A: the readback reads each staged table on its own. FK jobs stage tables the same way, and no
relationship logic runs in the driver.

### Fields

`IsolatedRunResult` (`src/decoy_engine/execution/_isolated_common.py:346`) on a refusal:

- `outcome` `"crashed"`; `reason` the new code (memory arm: `process_out_of_memory`).
- `error` the fixed capacity text; `outputs` `None`; `quality_metrics` and `table_kinds` `{}`.
- `peak_rss_mb` the child's reported peak; `returncode` 0; `signal_number` `None`; `isolated` `True`.
- `committed_output_dir` `None`; `row_errors` `()`; `publication_receipt` `failed_receipt` with `output_dir`, else `None`.
- `extra["readback"]` the five numbers (`_isolated_common.py:407`), also on a completed run.

`ResidentFit` (`src/decoy_engine/execution/pipeline/_resident_fit.py:52`): verdict, code, table
count and byte figures, numbers and tokens only.

### Output surfaces

- `IsolatedRunResult.error`, `repr`, `reason.to_payload()`, `extra` (A6).
- Publication receipt (A6, A8).
- Governor trip error and diagnostic (A6, A7).
- Logs: the slice adds no log line; A6 captures all levels.
- CLI: none today; the CLI does not call the isolated route. A future caller gets exit 5 through `CAPACITY_REASON_CODES`.

## Class table (plan contract catalog)

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | `capacity_message` builds the text from a registered summary and two integers; no name or value | A6 canary corpus over every surface | G6: add the table name to the text |
| 2 | Cleanup missing on an exit path | refusal and memory arms abort the transaction and drop read tables; `_result_from_envelope` removes the stage; `_run_isolated` `finally` | A12 exit-path matrix with descriptor count | G12: skip the transaction abort |
| 3 | State machine and concurrency | N/A: the child has exited before `collect` runs; one thread reads; no shared state | n/a | n/a |
| 4 | Route parity and silent fallback | one readback for every isolated route; no fallback; the refusal has a registered reason | A1 to A4 on a streamed and a resident child; A7 | G1, G7 |
| 5 | Referential integrity | N/A: per-table readback; no FK data is joined in the driver | n/a | n/a |
| 6 | Untrusted producer (the child's staged files and footers) | admitted stage only; footer and body read through the capability and the guarded adapter; floor checked against measured bytes | A2, A10, A12 corrupt footer | G2, G10 |
| 7 | Check then use (TOCTOU) | footer and data read from one capability handle per table, after `_admit` made the stage 0700 and files 0600; the child has exited | A12 descriptor count | open a second handle by path for the decode: A12's descriptor and spy assertions go red |
| 8 | Weak tests and overclaimed evidence | real child in every route case; spy non-vacuity in A4; A10 non-vacuity per type family | A4, A10 | remove A4's spy-count assertion: a broken spy no longer fails |
| 9 | Behavior-preserving refactor drift | `read_table` call unchanged; `nonfk_full_frame_capacity_error` text unchanged through `capacity_message` | A4 parity; existing resident-fit text asserts | change one word of the shared text: those asserts go red |
| 10 | Frozen contract drift | reason registry additive (`since=UNRELEASED`); `IsolatedRunResult` fields and `IsolatedRunOutcome` unchanged | A11, release-pin tests | drop the changelog fragment: release-pin test red |

## Recurring defects (dev-rules catalog)

| Class | Status |
|---|---|
| 1 anchored validation | A6 uses `fullmatch` and the trailing-newline case |
| 2 strict wire and stored types | `extra["readback"]` asserted as exact `int` or `None` in A4, A5 |
| 3 no exception context | refusal built outside any `except`; memory result from fixed text; A13 asserts no cause or context |
| 4 versioned read models | n/a: no persisted format |
| 5 normalized guard scanners | n/a: no new scanner |
| 6 no private-module imports | `_isolated_commit` imports `check_readback`, `lazy_spec`, `resident_spec` from `decoy_engine.execution.pipeline` |
| 7 no hidden CI failures | A12 Linux skip states its reason; the gate records a Linux pass on the final head |
| 8 one trust class per entry point | n/a: one trust class (the child's stage) |
| 9 mutations on the final head | G1 to G12 rerun on the final head and recorded |
| 10 allowlisted helpers are still checked | no new file-access registry row; the readback stays on the capability path |
| 11 no raised caps | no module-size ceiling raised; `_isolated_run.py` stays at or under 600 |

## Reuse inventory

- `_resident_fit`: `resident_fit_verdict`, `_lower_bound_verdict`, `_kill_ceiling`, `ResidentFit`.
- `_resident_bytes`: `lower_bound_bytes`, `lazy_spec`, `resident_spec`.
- `out_of_core.detect_effective_memory_bytes`, through `_kill_ceiling`.
- `is_memory_failure`; the `envelope_failure` builder pattern; `publication.failed_receipt` (`publication/_publish.py:143`).
- `fileaccess.capture().open_read`, `arrow_adapter.parquet_file`, `arrow_adapter.read_table`.
- `nonfk_full_frame_capacity_error`'s text, moved into the shared `capacity_message`.
- Test support: `tests/unit/execution/test_isolated_run.py` helpers and `tests/unit/execution/publication/` support modules.

New names: `check_readback`, `ReadbackRefused`, `readback_refused`, `capacity_message`,
`ISOLATED_READBACK_CAPACITY_EXCEEDED`. Each has a production caller in this slice.

## Frozen contracts

- Reason registry: one additive identity `decoy.isolated_readback_capacity_exceeded`, retry
  `environment_repair`, `since=UNRELEASED`, with a `changelog.d/` fragment naming it.
  `REGISTRY_VERSION` and fixtures are not edited (docs/reasons.md).
- `CAPACITY_REASON_CODES`: additive. The CLI derives exit 5 and its rule-code census from the
  engine, so no CLI edit.
- `IsolatedRunResult`: no field added, removed or reordered; `extra` gains the `readback` key.
- `IsolatedRunOutcome`: unchanged (`crashed` is reused).
- `run_pipeline_isolated` and `run_job_with_governor` signatures: unchanged.
- `nonfk_full_frame_capacity_error` text: unchanged.

## Placement and sizes

| Path | Change | CODEMAP line | Beside | Lines now | Expected |
|---|---|---|---|---|---|
| `src/decoy_engine/execution/_isolated_commit.py` | footer read, check loop, memory arm, `ReadbackRefused`, `extra` numbers | `CODEMAP.md:271` | `_isolated_run.py` | 324 | about 385 |
| `src/decoy_engine/execution/_isolated_run.py` | `_result_from_envelope` maps `ReadbackRefused` | `CODEMAP.md:271` | `_isolated_commit.py` | 595 | at most 600; if more, `_result_from_envelope` moves to `_isolated_commit.py` with its two file-access registry rows, row count unchanged |
| `src/decoy_engine/execution/_isolated_reason.py` | `readback_refused`, memory result | `CODEMAP.md:271` | `_isolated_common.py` | 112 | about 150 |
| `src/decoy_engine/execution/_errors.py` | `capacity_message` | `CODEMAP.md:271` | `_isolated_reason.py` | 140 | about 150 |
| `src/decoy_engine/execution/pipeline/_resident_fit.py` | `check_readback` | `CODEMAP.md:271` | `_resident_bytes.py` | 470 | about 500 |
| `src/decoy_engine/execution/pipeline/__init__.py` | export `check_readback` | `CODEMAP.md:271` | `_resident_fit.py` | 51 | 53 |
| `src/decoy_engine/reasons/decoy/_core.py` | new identity | `CODEMAP.md:288` | `ISOLATED_WORKER_OUT_OF_MEMORY` | 288 | about 296 |
| `src/decoy_engine/errors.py` | `CAPACITY_REASON_CODES` entry | `CODEMAP.md:262` | the `ISOLATED_WORKER_OUT_OF_MEMORY` entry | 599 | 600 |
| `changelog.d/<fragment>` | names the new identity | release notes | other fragments | 0 | about 3 |
| `tests/unit/execution/test_isolated_readback_cap.py` (new) | A1 to A9, A12 | `CODEMAP.md:271` | `test_isolated_run.py` (877, not grown) | 0 | about 320 |
| `tests/unit/execution/test_resident_floor_reality.py` (new) | A10 | `CODEMAP.md:271` | `test_resident_fit.py` | 0 | about 120 |
| `tests/unit/execution/test_isolated_safe_error.py` | A13 producers | `CODEMAP.md:271` | `test_isolated_run.py` | 418 | about 440 |

No new source module and no new package: `execution/` is over its fan-out freeze (109 entries
against 104, `CODEMAP.md:271`), and every change fits an existing module under 600 lines.

## Slices

One slice, engine repo, branch `feat/f25-g7-3-readback-cap`: about +170 / -15 source lines and
+480 test lines. Order: A10 first (it decides whether the shared floor needs a fix before anything
relies on it), then red A1 to A9, A12, A13, then the code. Tests: T0 and T1 per commit, T2 at each
gate on the exact head. The reason registry is a frozen contract surface, which is a full-suite
escalation trigger; the slice rides the next merge train for its one full suite against the
stored baseline.

## Pre-mortem

- A10 finds a type whose floor is above reality. Suspect: Arrow reads Parquet dictionary indices
  back as int32, so a stored int64 index makes an 8-byte floor too high. The fix goes in
  `_lazy_column_bytes` (`_resident_bytes.py:183`), which also corrects `check_pre_read`, and lands
  in this slice before the cap.
- The spy patches the wrong name (a by-value import elsewhere): A4's per-table call count catches a
  spy that sees nothing.
- `_isolated_run.py` goes over 600 lines: the Placement row names the move in advance.
- A real child per case makes the file slow: tables stay under 1,000 rows, cases share one fixture
  config, and the governor case runs one rung.
- The ceiling patch leaks into the child: it cannot (fresh interpreter), and A4 shows the child
  completes normally under the patched driver.
- A reviewer asks for the cap to also catch string-heavy overruns: that is outside the guarantee
  (non-goal 1, Q1); record it, do not widen the slice.

## V2-LOG

- Read back only on request: with `output_dir`, leave `outputs` unread or return lazy handles;
  removes D2 (Q2 option (b) or (c)).
- Row-group granularity for the readback check, so one very large table is checked between row
  groups; needs a parity proof for chunk layout against `pq.read_table`.
- A tighter floor for string and binary payloads from footer statistics or `total_byte_size`.
- Bound the result-envelope read (`read_envelope`) and the `row_errors` it carries.
- The child's resident-fit checks read the `RLIMIT` as their kill ceiling, with the governor taught
  to reroute on that refusal.
- When row 58b or CHUNK-PARALLEL brings an explicit memory budget, the readback ceiling becomes
  `min(H, budget)`.
- A bounded footer read for child-staged files.
- The probe reads back outputs it never uses; skip the readback for the probe once Q2 (b) exists.

## Owner questions

**Q1. What may the cap refuse?**

- (a) Only what a strict floor proves cannot fit under the detected kill ceiling. Never refuses a
  run that `main` completes; misses string-heavy overruns. **Recommended** (matches row 58b's
  no-default-limit rule and `_resident_fit`'s rule).
- (b) An estimate (footer `total_byte_size`) against 85% of the ceiling. Catches more, but can
  refuse runs that complete today.
- (c) A fixed default cap in Spark's 1 GiB style. Simple, but refuses large runs that work.

**Q2. With `output_dir` given, what happens at the cap?**

- (a) Refuse the whole run and publish nothing; `outputs` keeps its contract (a dict on every
  completed run). Today that run dies with the driver, so nothing is lost. **Recommended for 1.0.**
- (b) Publish the staged unit, return `completed` with `outputs=None` and a reason. Better for big
  runs, but every caller of `IsolatedRunResult.outputs` must handle `None` on a completed run
  (contract change). V2-LOG.
- (c) Return lazy table handles instead of frames. Removes the readback entirely; the largest
  contract change. V2-LOG.

**Q3. Should callers be able to set the cap?**

- (a) No parameter in 1.0; the ceiling is detected. **Recommended** (hardening only, no new
  surface; 58b brings a configurable budget).
- (b) An engine keyword on `run_pipeline_isolated` (`max_readback_bytes`). Useful for platform
  tuning, but it is new public surface.
