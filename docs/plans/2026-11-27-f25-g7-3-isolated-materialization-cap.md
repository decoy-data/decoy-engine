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
readback is a coded memory result, never a publication failure and never a raw exception. On an ordinary success, the caller gets the same outputs and publication receipt as on `main`.

**Commit contract.** For a completed child's readback, the public result follows the publication decision.
Before commit, any raised memory failure in readback or finalization yields `crashed` with
`decoy.process_out_of_memory`. This attempt publishes nothing. Once the target binds, any
`MemoryError` through the return from `run_pipeline_isolated` yields an already built
`completed` result. It identifies the target and retains the decoded outputs and quarantine records.
Optional figures without a complete measurement stay absent. A retry that the publisher verifies as
`already_committed` has the same protection. CPython can raise even while returning or unwinding,
so moving constructors alone cannot establish this contract.

Only a strict lower bound can refuse, and only above the kill ceiling, so compatibility depends on the swap assumption below. That is the rule row 58b sets for quotas (no default limit that refuses 1.0
runs that work) and the rule `_resident_fit` already applies (`RESIDENT_ADMISSION_FRACTION`,
`src/decoy_engine/execution/pipeline/_resident_fit.py:44-46`: it "can prove a fit, never a
refusal").

**Assumption: swap is not counted.** `H` leaves swap out on purpose
(`src/decoy_engine/execution/out_of_core/_budget.py:154-160`), so it can be lower than the point
where the kernel really kills. Where swap is on, a run whose floor is over `H` but under RAM plus
swap completes on `main` by swapping, and this cap refuses it. The guarantee above holds only on
hosts where swap or compression cannot extend the binding limit. This is the same assumption
engine #777 (`check_pre_read`) already makes, and it is kept here on purpose: a run that needs
swap to hold its own output is already degraded. Known cases:

- Linux with swap on: a run that fits only with swap is refused.
- macOS: `H` is host RAM, and the memory compressor plus dynamic swap let runs well past RAM
  complete. This is the worst case for wrong refusals.
- Windows: no `os.sysconf` page counts and no `/proc/meminfo`, so detection fails
  (`_budget.py:195-215`), `H` is unknown, and the cap does nothing (the A5 path).

A swap-aware refusal ceiling is V2-LOG.

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

1. Pass the resident source mapping from `_run_isolated` through `_spawn_and_classify` and
   `_result_from_envelope` to `collect`. Absent sources count as empty. Keep these facts in the driver.
   `collect` admits the stage as today (`_names_ok`, `_admit`).
2. Before the first decode, gather footer specs for all admitted tables in envelope order. Open each through the file-access
   capability (as `_read_staged` does) and read the footer row count and Arrow schema
   inside `with arrow_adapter.parquet_file(handle) as pf:` (`pf.metadata.num_rows`,
   `pf.schema_arrow`), so the footer file is closed before the decode, as
   `src/decoy_engine/profile/_readers.py:339` does. Nothing is decoded yet.
3. Before each decode it calls the one comparison, new
   `check_readback(held, pending, *, kill_ceiling_bytes: int | None) -> ResidentFit | None` in
   `_resident_fit.py`. It returns `None` when `kill_ceiling_bytes` is `None` (ceiling unknown,
   no check), and never re-detects the ceiling itself:
   `bound = lower_bound_bytes(held + pending)`, all with `charge_pandas=False`. `held` is
   `resident_spec` of the caller's resident `sources` and of each output already read (measured
   buffer bytes, union of buffer ranges). Price a metadata-free view with
   `table.replace_schema_metadata(None)` when taking resident specs for readback. This shares
   the buffers and avoids parsing optional pandas metadata for an Arrow-only measurement.
   Retain the original table and metadata in `outputs`. `pending` is `lazy_spec(rows, schema)` of this table and
   every table not yet read (the footer floor). The verdict comes from `resident_fit_verdict`
   (`_resident_fit.py:104`) through `_lower_bound_verdict`, so the rule is the existing one:
   refused only when `bound > H`. `H` comes from `kill_ceiling()`. Rename `_kill_ceiling` at `_resident_fit.py:219`, update its
   three internal callers and export the same function from `decoy_engine.execution.pipeline`.
   Call it once per admitted readback. Only an insufficient verdict refuses. Both unknown and fit proceed to decode.
4. On refusal: tables read so far are dropped, the publication transaction is aborted, and
   `collect` returns `ReadbackRefused(fit, receipt, readback)`. `_result_from_envelope`
   (`_isolated_run.py:562`) maps it, through one builder in `_isolated_reason.py`, to
   `IsolatedRunResult(outcome="crashed", reason=ISOLATED_READBACK_CAPACITY_EXCEEDED,
   error=<fixed text with two integers and the readback remedy>, outputs=None, publication_receipt=failed_receipt(request)
   when output_dir was given, else None)`, after cleanup. In `_result_from_envelope`, put `collect` in a `try` block.
   In its `finally`, run the existing `shutil.rmtree(staging_output_dir, ignore_errors=True)`
   when `pub is None`. This also removes `staging_output/` when detection raises.
   Reason context: phase `FINALIZE`, publication `NOT_PUBLISHED`, cleanup confirmed by looking.
5. Otherwise reopen the admitted file through the capability and read it with the existing `arrow_adapter.read_table(handle)`, so the frame,
   chunking and metadata are `main`'s, and step 3 repeats for the next table.
6. After the last table, prepare both completed results and then publish under the boundary below.
   Scratch-only runs finish under the pre-commit memory arm.
7. A memory failure while reading (`is_memory_failure`,
   `src/decoy_engine/fileaccess/_errors.py:160`, the predicate the worker already uses) is caught
   before the `(OSError, ArrowException)` arm. `collect` returns a typed
   `ReadbackMemoryFailure(receipt)` value, and `_result_from_envelope` maps it to
   `outcome="crashed"`, `reason=decoy.process_out_of_memory` (built with
   `ReasonRecord.for_reason`, never from the exception), fixed text, with the same abort and
   cleanup. **Behaviour change:** `is_memory_failure` also matches `OSError` with `errno.ENOMEM`
   (`fileaccess/_errors.py:107-111`) and messages that carry a known memory marker or pattern
   (`:170-173`). These reach `publication_failed` with the errno today; after this slice they are
   `process_out_of_memory`. A9 pins the ENOMEM case.
8. Return the six figures with the completed collection or refusal so its result builder sets `extra["readback"] = {"kill_ceiling_bytes",
   "sources_bytes", "floor_bytes", "held_bytes", "tables_read", "tables_staged"}` (ints, or `None`
   for an unknown ceiling). `sources_bytes` is the measured bytes of the caller's resident sources.
   `floor_bytes` is the footer floor of the staged outputs only. `held_bytes` is the measured bytes
   of the outputs read only. This is how the estimate is checked against reality: on a completed
   run A4 asserts `floor_bytes <= held_bytes` over the same outputs, and A10 asserts the same per
   type.
9. When `H` cannot be detected (`kill_ceiling()` returns `None`), no check runs and the readback is
   `main`'s.

`crashed` is the right outcome. Output size is the same on every route (the engine is seeded and
deterministic, `_governor.py:26-30`), so a reroute cannot help, and the governor stops on `crashed`
(`_governor.py:381-404`). The probe turns any non-completed run into an inconclusive probe
(`_probe.py:292-300`), which routing already handles.

**Refuse or fall back.** Falling back to the out-of-core route does not help: the child may
already be on it, and D2 is the driver reading the finished output. The only real fallback is to
not read the output back, which is Q2 (b). This plan recommends the refusal for 1.0.

### Commit boundary on `abc5998fd`

`_isolated_run._run_isolated` owns the one decision about a memory failure after commit. It
owns the transaction and scratch cleanup and is the last call on the public isolated route.
Keep its memory guard around the whole readback, the publisher, and all enclosing cleanup,
including `txn.abort()` and `scratch.close()` at lines 394 to 397. Nest cleanup so both run
even if one raises. Callers return the selected object directly.

- Reserve the per-attempt coded memory result when setting up the attempt, before entering readback.
  Use the existing memory reason builder, fixed text and failed receipt when publishing. Leave
  unknown figures absent and cleanup evidence conservative. On exhaustion, release the partial
  tables and abort the stage. Returning the reserve needs no second constructor or exception text.
- Start the existing pre-commit memory arm before the first readback allocation. Include request and
  reader setup, the initial `extra` at `_isolated_commit.py:350`, `str(pub.target)` at line 426
  and `row_errors_of` at line 427. Include admission, reads, measurement, component names, refusal
  handling, receipt preparation, and both completed results. Classify memory before broad Arrow
  and OS handlers, including the measurement handler in `publication/_publish.py:275`.
- Make `collect` finish readback before publication. Build `Collected` if still needed, both empty
  mapping defaults, and the normal and emergency `IsolatedRunResult` before calling the bind.
  Share the decoded output mapping, target string, row errors and actual quality and kind mappings
  within this attempt. Prepare sampling evidence here, with the current abnormal flag for child
  crashes. Remove the completed route's later `evidence_of` and `replace` at `_isolated_run.py:522`.
  The emergency result can omit the entire optional `readback` entry. Zero is a measured value.
- The frozen results need real receipts. Split the existing publisher's locked preparation from
  its bind so that preparation supplies the measured receipt candidates **before** the isolated
  caller invokes `publish_unit` to commit. Keep one lock from the existing judge through bind.
  Only the lock owner can consume a prepared bind, once, for its original transaction and destination.
  Both the ordinary publication API and this prepared call use the same judge, descriptor,
  receipt builder and bind. Expose preparation through the publication package API. Execution
  never measures the descriptor again or predicts the outcome. Prepare completed results with
  the corresponding receipts for a fresh bind or a verified replay, as selected under that lock.
- Record the decision in pre-existing per-attempt slots shared with the outer guard. At the
  successful rename, store the visible state before handle close or fsync can allocate
  (`fileaccess/_local_chain.py:104`). For a memory fault during this interval, reserve a
  completed result with a visible, non-durable `commit_uncertain` receipt for the measured unit.
  On successful chain sync, select the prepared durable receipt and its results before releasing
  the lock. For replay, select success only after the existing identity, vault and sync checks.
  The binding primitive records each transition by a direct store, with no helper call or allocation
  between the successful operation and the store. A prior target's existence proves nothing.
  Preserve ordinary conflict, refusal, I/O and uncertain receipts, including failed fsync.
- On the normal path, return the prepared full result. On `MemoryError`, the outer guard returns
  the prepared fallback for the recorded decision, even when the publisher raised before returning
  a receipt. Before any bind or verified replay it returns the coded memory result. There is no
  post-commit retry, failure builder, telemetry update or logging call.

### Design notes

The cap adds one caller to the existing resident-fit comparison. One fact, one place: the bound formula stays in `_resident_bytes.py`, the ceiling in
`kill_ceiling`, the comparison in `resident_fit_verdict`, the capacity text in `_errors.py`. The
refusal travels as a typed value (`ReadbackRefused`) instead of a flag argument.

## Failure modes

| Failure | Detected at | Reason code | Value-free | Test |
|---|---|---|---|---|
| Footer floor of outputs plus resident caller sources over `H` | `check_readback`, before the first decode | `decoy.isolated_readback_capacity_exceeded` | fixed summary, two integers | A1, A3 |
| Measured bytes of tables read plus floor of the rest over `H` | `check_readback`, before the next decode | `decoy.isolated_readback_capacity_exceeded` | same | A2 |
| Refusal with `output_dir` | `collect` aborts the transaction before `publish_unit` | same; receipt `failed` | receipt carries codes only | A8 |
| `ArrowMemoryError` or `MemoryError` during a read | `collect`, `is_memory_failure` arm | `decoy.process_out_of_memory` | fixed text, no exception text | A9 |
| `OSError(ENOMEM)` or a marker-matched memory message during a read (behaviour change: was `publication_failed`) | `collect`, `is_memory_failure` arm | `decoy.process_out_of_memory` | fixed text, no errno text | A9 |
| Memory failure in setup or any preparation before bind | Pre-commit memory arm in the isolated finalization path | `decoy.process_out_of_memory`, nothing newly published | Fixed text | A9, A14 |
| MemoryError after bind or verified replay, including publisher and caller unwind | `_run_isolated` reads the recorded decision | `completed`, visible target, receipt reflects confirmed durability | Missing figures omitted | A14, G14 |
| Swap on (Linux, macOS): floor over `H` but under RAM plus swap | `check_readback` | `decoy.isolated_readback_capacity_exceeded` (a refusal `main` would not make; accepted assumption) | fixed text | none (documented, V2-LOG) |
| Windows: ceiling detection fails | `kill_ceiling()` returns `None` | none; cap inert, runs as `main` | n/a | A5 |
| Kill ceiling not detectable | `kill_ceiling()` returns `None` | none; runs as `main` | n/a | A5 |
| Ceiling detection raises another `ExecutionError` | `kill_ceiling()` re-raises (`_resident_fit.py:224-229`) | that error's code; the collect `finally` removes the scratch output stage. With publication the outer `finally` aborts the transaction (`_isolated_run.py:396-398`) | its own fixed text | A12 |
| Corrupt staged footer or body | `parquet_file` or `read_table`, unchanged `(OSError, ArrowException)` arm | `decoy.publication_failed` (unchanged) | receipt codes only | A12 |
| Floor formula above reality for some Arrow type (wrong refusal) | property test over the type corpus | n/a (test) | n/a | A10 |
| Governor reroutes a refused run | governor ladder | trip kind `crashed`, outcome `exhausted` after one rung | trip error is the fixed text | A7 |

## Acceptance tests, red first

Before the refactor, add the class 9 characterization test to
`tests/unit/execution/test_resident_fit_decision.py`. Use a literal independent of the registry
and the formatter. Pin the message and its public exception text.

```python
exc = nonfk_full_frame_capacity_error(needed_bytes=1, kill_ceiling_bytes=2)
expected = (
    "A job with no foreign keys would hold more memory than this machine can give it. "
    "The figure checked is 1 bytes and the memory ceiling is 2 bytes. "
    "Run on a machine with more memory, or reduce the table's rows or columns."
)
assert re.fullmatch(re.escape(expected), exc.message)
assert str(exc) == f"[nonfk_full_frame_capacity_exceeded] {expected}"
```

Run this test against the unmodified main implementation first. After the refactor, change one
word in the formatter and require the same test to fail. Restore the word and rerun the test.

Most route cases use `run_pipeline_isolated` with `install_fake_worker`. Add a plant mode
that reads an ordered JSON table spec from the test environment. Write one Parquet file per
entry and report exactly those names in `staged_tables`. Preserve the default two-row
`t.parquet` and existing plant modes. Use the new mode for A2, A6 and the two-decode
cases in A9 and A12. A2 uses file-backed inputs with no resident caller tables.
A4 uses a real child with streamed out-of-core output. A7 starts its real child on full-frame. Give A7 a second eligible rung so a reroute is observable.
Patch the renamed `kill_ceiling` at the driver's lookup site. Tests of its internal callers
patch `_resident_fit.kill_ceiling`. Spy on `arrow_adapter.read_table` as the driver sees it.
A4 requires one decode per staged table. A10, A11, A13 and class 9 are direct tests.

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
  published Parquet file under `output_dir` (schema, metadata and `assert_frame_equal` on `to_pandas()`). `extra["readback"]`
  has exact `int` values; `floor_bytes` and `held_bytes` both cover the outputs only (the run has
  non-empty caller sources, so a `held_bytes` that wrongly includes them shows as a mismatch with
  the sum of `resident_spec` over `outputs`); `held_bytes` equals that sum;
  `floor_bytes <= held_bytes`; `tables_read == tables_staged`. G4: compare
  against `admission_ceiling_bytes(H)` instead of `H`; the second variant is refused.
  Check Arrow schema metadata before converting any ordinary fixture to pandas. Also compare
  a table with opaque pandas metadata directly in a resident-pricing unit case. Pricing must succeed without a pandas conversion.
- **A5 ceiling unknown.** `kill_ceiling` returns `None`: completes as `main`,
  `extra["readback"]["kill_ceiling_bytes"] is None`. G5: treat `None` as `0`; refused.
- **A6 value-free refusal.** Canary strings in cell values, column names and table names. On
  refusal, `error` fullmatches
  the escaped summary, the exact wording around two ASCII integers, and the escaped whole remedy.
  No canary in `error`, `repr(result)`, `result.reason.to_payload()`, `extra`, the receipt, the
  governor trip (A7) or captured logs (`caplog`, all levels). The same check feeds `error + "\n"`
  to the pattern and expects no match. G6: add the table name to the text.
- **A7 governor stops.** `run_job_with_governor` with the patched ceiling: outcome `exhausted` after
  one rung, one trip of kind `crashed`, `reroute_to is None`. G7: return outcome `oom_killed`; the
  governor reroutes and the test sees two or more rungs.
- **A8 nothing published on refusal.** With `output_dir`: the target does not exist afterwards, no
  publication stage remains beside it (listing of the parent), receipt outcome `failed`. G8: move
  `publish_unit` before the readback loop; the target exists.
- **A9 memory failure classified.** The spy raises, on the second decode, `pa.ArrowMemoryError`;
  then in further runs a bare `MemoryError`, `OSError(errno.ENOMEM, "x")` and an Arrow error containing a known memory marker. Outcome `crashed`,
  reason `process_out_of_memory` (not `publication_failed`), no exception or errno text in
  `error`, nothing published, stage removed. G9: delete the memory arm; the Arrow and ENOMEM
  variants must fail the reason assertion even if the outer guard still catches a bare `MemoryError`.
- **A10 floor is never above reality.** For a type corpus written through `StagedParquetWriter`
  (int8 to int64, uint, float16/32/64, bool, decimal128, date32, timestamp with and without tz,
  duration, string, large_string, binary, large_binary, fixed_size_binary, dictionary with int8,
  int16, int32 and int64 indexes, struct, list, large_list, map, fixed_size_list, null; each with
  and without nulls; empty tables; several row groups), assert
  `lower_bound_bytes([lazy_spec(pf.metadata.num_rows, pf.schema_arrow, charge_pandas=False)]) <=
  resident_spec(pq.read_table(path)).resident_input_bytes`. Non-vacuity: require a positive floor for each family with a positive pricing rule. For null and fixed-size list, assert the documented zero floor on nonempty input. Include short strings on several rows to kill G10. G10: change the string offset width in `_lazy_column_bytes`
  (`src/decoy_engine/execution/pipeline/_resident_bytes.py:183`) from 4 to 16.
- **A11 reason registered.** The registry walk `tests/unit/reasons/test_capacity_reason_codes.py`
  adds the new code to its explicit `EXPECTED` set and passes with the code in `CAPACITY_REASON_CODES` (`src/decoy_engine/errors.py:511`); the
  reasons doc and release-pin tests pass with `since=UNRELEASED` and a `changelog.d/` fragment.
  G11: drop the code from `CAPACITY_REASON_CODES`; the registry walk goes red.
- **A12 exit-path matrix.** {pre-read refusal, mid-read refusal, memory failure, corrupt footer,
  detection error} x {with `output_dir`, without} x {engine-made work root, caller `staging_dir`}.
  After each: no publication stage; an engine-made work root is removed; a caller-named
  `staging_dir` still exists, as designed (`_isolated_run.py:364-368`), with no `staging_output/`.
  Its payload and `result.json` stay by design. On Linux compare `/proc/self/fd` counts
  before and after, including footer handles. Skip only that check elsewhere. Check that the
  result or raised error matches the failure-mode table.
  G12: move no-publication cleanup after `collect`. The detection-error case with a caller root leaves `staging_output/`.
- **A13 safe-error producers.** `tests/unit/execution/test_isolated_safe_error.py` gains the refusal
  and the memory result as producers of `IsolatedRunResult.error`; both pass its existing
  no-exception-text checks, and the refusal error has `__cause__ is None and __context__ is None`
  where an error object exists. Mutation: build `error` from `str(exc)` in the memory arm.

- **A14 result agrees with the target under allocation failure.** Run through
  `run_pipeline_isolated` with the fake worker and a real destination. Use one fault per run.
  - Before bind, inject once at each preparation site, starting with reader construction,
    initial `Readback` and `asdict`, target string conversion and `row_errors_of`. Cover
    every later allocating step in the boundary, including component creation, publisher
    measurement and receipt construction, both result constructors, mapping defaults and evidence.
    Patch the actual lookup or inject at the expression for literals. Assert the fault fired,
    `crashed`, `process_out_of_memory`, fixed text, no outputs, no new target and stage cleanup.
    Repeat applicable cases without publication. Include a failure that occurs before the reader exists.
  - Arm constructor traps at bind for `Collected`, `IsolatedRunResult`, receipt construction,
    mapping defaults, `replace` and evidence. Exercise empty and populated metadata. Assert
    prebuilt identity and zero late constructions on normal success. Separately inject a real
    `MemoryError` at each remaining post-bind operation, including before the publisher returns,
    after its real return, at result handoff, and on lock, transaction and scratch cleanup.
    Wrap real cleanup so it runs. For return-only sites use a one-shot trace fault inside the guard.
    Assert each scheduled fault fired. A constructor trap that nobody calls cannot test the guard.
  - Read the published Parquet and descriptor. Assert `completed`, the correct path, outputs,
    quarantine records, receipt identity and visibility. Check confirmed durability after sync
    and its absence for a fault between rename and sync. Optional figures must match the normal
    result or be absent. Repeat after a verified replay. Seed a different existing target as a
    negative control and require its conflict or refusal and unchanged contents. Exercise a
    genuine fsync error separately to pin the existing uncertain outcome.
  - **G14.** Remove only the post-commit branch of the memory guard. With all preparation intact,
    the injected fault after real publication must now escape or yield the wrong outcome while
    the target remains readable. Restore the guard and rerun A14 on the same final head.

Existing suites that must stay green: `tests/unit/execution/test_isolated_run.py`,
`test_isolated_oom_classification.py`, `tests/unit/execution/publication/` (route outcome matrix,
marker corpus), `tests/integration/test_f29_isolation.py`, `tests/unit/execution/test_resident_fit*.py`.

## Choke points

| Choke point | Where | Callers | Guard mutation |
|---|---|---|---|
| The one ceiling comparison | `resident_fit_verdict`, reached through new `check_readback(held, pending, *, kill_ceiling_bytes: int \| None) -> ResidentFit \| None` in `execution/pipeline/_resident_fit.py`, exported from `execution/pipeline/__init__.py` | `check_pre_read`, `check_pre_transform` (existing), `_isolated_commit.collect` (new) | G4 |
| The one bound formula | `lower_bound_bytes`, `lazy_spec`, `resident_spec` (`_resident_bytes.py:50`, `:133`, `:173`) | the same callers | G2, G10 |
| The one kill-ceiling source | Rename `_kill_ceiling` at `_resident_fit.py:219` to `kill_ceiling` and export it directly. It calls `out_of_core.detect_effective_memory_bytes` (`_budget.py:332`). | the same callers | G5 |
| The one isolated readback | `collect` and `_read_staged` (`_isolated_commit.py:205`, `:231`); every readback of a child's stage goes through it, for the probe, the governor and direct callers | `_result_from_envelope` (`_isolated_run.py:573`) | G1, G8 |
| Outcome after irreversible publication | `_isolated_run._run_isolated` uses the decision recorded by the publisher through final cleanup | `run_pipeline_isolated` | G14 |
| The capacity message | new `capacity_message(code, *, needed_bytes, kill_ceiling_bytes, remedy)` in `execution/_errors.py`. `nonfk_full_frame_capacity_error` (`src/decoy_engine/execution/_errors.py:87`) passes exactly "Run on a machine with more memory, or reduce the table's rows or columns." The formatter appends one space and the whole `remedy` sentence verbatim. Look up the summary in the supplied reason's namespace. The readback passes "Run on a machine with more memory, or write fewer or smaller output tables." | both refusals | G6 and class 9 |
| The refusal result | new `readback_refused(...)` in `_isolated_reason.py`, beside `envelope_failure` (`:68`) and `commit_reason` (`:101`) | `_result_from_envelope` | G7 |
| The memory predicate | `is_memory_failure` (already shared by the worker and `in_process_failure`) | `collect` (new) | G9 |
| Capacity code list | `CAPACITY_REASON_CODES` (`errors.py:511`); the CLI derives exit 5 from it | registry walk test | G11 |

## Established solutions

CPython reserves emergency objects and can return its last-resort memory error without a fresh
allocation. Use that reserve pattern for the completed result. PostgreSQL reports a successful
commit once the changes are durable and visible. A reporting fault cannot reverse that decision.
[CPython memory error implementation](https://github.com/python/cpython/blob/3.13/Objects/exceptions.c#L3197-L3202)
and [PostgreSQL COMMIT](https://www.postgresql.org/docs/current/sql-commit.html).

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
- New: memory failure during a decode (incl. ENOMEM and marker-matched text): `ReadbackMemoryFailure`, process-out-of-memory result, transaction aborted.
- `parquet_file` or `read_table` raises an Arrow or OS error: `failed_receipt` (unchanged, `:218`).
- Any memory failure before bind or verified replay, including result setup, returns the coded memory result after cleanup.
- After bind or verified replay, the outer guard returns the prepared completed result on a memory fault through final cleanup. A14 checks the target and receipt.
- `publish_unit` does not commit: its receipt (`src/decoy_engine/execution/_isolated_commit.py:227`).
- `_result_from_envelope` removes the stage when there is no `output_dir` or on failure (`src/decoy_engine/execution/_isolated_run.py:575`).
- `_run_isolated` always aborts the transaction and closes the scratch work root (`src/decoy_engine/execution/_isolated_run.py:396-398`).

### Routes

- Windows: ceiling detection fails (`src/decoy_engine/execution/out_of_core/_budget.py:195-215`), so the cap is inert on every route there (A5 path).
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
- `extra["readback"]` the six numbers (`_isolated_common.py:407`), also on an ordinary completed run. The emergency result omits unavailable figures.

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
| 2 | Cleanup missing on an exit path | refusal and memory arms abort the transaction and drop read tables; `_result_from_envelope` removes the stage; `_run_isolated` `finally` | A12 exit-path matrix with descriptor count | G12: move cleanup after collect |
| 3 | State machine and concurrency | One publication decision under the destination lock determines which prepared result the driver returns | A14 fresh bind, verified replay and conflict | G14 |
| 4 | Route parity and silent fallback | one readback for every isolated route; no fallback; the refusal has a registered reason | A1 to A3 use the fake worker. A4 and A7 cover both routes with real children | G1, G7 |
| 5 | Referential integrity | N/A: per-table readback; no FK data is joined in the driver | n/a | n/a |
| 6 | Untrusted producer (the child's staged files and footers) | admitted stage only; footer and body read through the capability and the guarded adapter; floor checked against measured bytes | A2, A10, A12 corrupt footer | G2, G10 |
| 7 | Check then use (TOCTOU) | N/A: this slice adds no new check-then-use window. pyarrow reopens the path for the footer and for the body (`src/decoy_engine/fileaccess/adapters/arrow.py:61`, `:65`), as the readback does today; both opens follow the unchanged `_admit` step and happen after the child exited. That sequence is covered by the existing `test_isolated_marker_corpus.py` | n/a | n/a |
| 8 | Weak tests and overclaimed evidence | fake worker for most cases. Real children in A4 and A7. A4 counts decodes and A10 checks each type family | A4, A10 | remove A4's spy-count assertion: a broken spy no longer fails |
| 9 | Behavior-preserving refactor drift | `read_table` call unchanged; `nonfk_full_frame_capacity_error` text unchanged through `capacity_message` | A4 parity and the new pre-refactor fullmatch. Existing tests do not pin the message | change one word in the shared text. The new characterization test fails |
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
| 9 mutations on the final head | G1 to G12, G14 and the class 9 one-word mutation rerun on the final head and recorded |
| 10 allowlisted helpers are still checked | no new file-access registry row; the readback stays on the capability path |
| 11 no raised caps | no module-size ceiling raised; `_isolated_run.py` stays at or under 600 |

## Reuse inventory

- `_resident_fit`: `resident_fit_verdict`, `_lower_bound_verdict`, `kill_ceiling`, `ResidentFit`.
- `_resident_bytes`: `lower_bound_bytes`, `lazy_spec`, `resident_spec`.
- `out_of_core.detect_effective_memory_bytes`, through `kill_ceiling`.
- `is_memory_failure`; the `envelope_failure` builder pattern; `publication.failed_receipt` (`publication/_publish.py:143`).
- `fileaccess.capture().open_read`, `arrow_adapter.parquet_file`, `arrow_adapter.read_table`.
- `nonfk_full_frame_capacity_error`'s text, moved into the shared `capacity_message`.
- Test support: `tests/unit/execution/test_isolated_run.py` helpers and `tests/unit/execution/publication/` support modules.

New names: `check_readback`, `kill_ceiling`, `ReadbackRefused`, `ReadbackMemoryFailure`,
`readback_refused`, `capacity_message`, `ISOLATED_READBACK_CAPACITY_EXCEEDED`. Each has a production caller in this slice.

## Frozen contracts

- Reason registry: one additive identity `decoy.isolated_readback_capacity_exceeded`, retry
  `environment_repair`, `since=UNRELEASED`, with a `changelog.d/` fragment naming it.
  `REGISTRY_VERSION` and fixtures are not edited (docs/reasons.md).
- `CAPACITY_REASON_CODES`: additive. The CLI derives exit 5 and its rule-code census from the
  engine, so no CLI edit.
- `IsolatedRunResult`: no field added, removed or reordered; `extra` gains the `readback` key.
- `decoy_engine.execution.pipeline` exports: additive (`check_readback`, `kill_ceiling`).
- `IsolatedRunOutcome`: unchanged (`crashed` is reused).
- `run_pipeline_isolated` and `run_job_with_governor` signatures: unchanged.
- `nonfk_full_frame_capacity_error` text: byte-identical (its remedy is passed in).
- Memory classification in the readback: changed on purpose for ENOMEM and marker-matched text
  (Behaviour step 7); release notes say so in the same `changelog.d/` fragment.

## Placement and sizes

| Path | Change | CODEMAP line | Beside | Lines now | Expected |
|---|---|---|---|---|---|
| `src/decoy_engine/execution/_isolated_commit.py` | guarded readback and preparation of completed results | `CODEMAP.md:271` | `_isolated_run.py` | 559 on abc5998fd | at most 600. If it would cross 600, move result construction to existing `_isolated_reason.py` beside the readback builders |
| `src/decoy_engine/execution/_isolated_run.py` | own the outer memory guard and cleanup, pass sampling evidence into preparation | `CODEMAP.md:271` | `_isolated_commit.py` | 559 on abc5998fd | at most 600 |
| `src/decoy_engine/publication/_publish.py`, `publication/__init__.py` | expose locked preparation, reuse existing receipt construction and bind | `CODEMAP.md:105` | `_types.py` | 474 in publisher | under 600 |
| `src/decoy_engine/fileaccess/_local_chain.py`, `_local.py` | record bind and sync state at the ambient directory transaction used by isolation | `CODEMAP.md:35` | existing durable directory helpers | 600 in `_local.py` | keep orchestration at 600 by moving the existing durable-directory branch into `_local_chain.py` |
| `src/decoy_engine/execution/_isolated_reason.py` | `readback_refused`, memory result | `CODEMAP.md:271` | `_isolated_common.py` | 112 | about 150 |
| `src/decoy_engine/execution/_errors.py` | `capacity_message` | `CODEMAP.md:271` | `_isolated_reason.py` | 140 | about 150 |
| `src/decoy_engine/execution/pipeline/_resident_fit.py` | `check_readback`, public `kill_ceiling` | `CODEMAP.md:271` | `_resident_bytes.py` | 470 | about 505 |
| `src/decoy_engine/execution/pipeline/__init__.py` | export both | `CODEMAP.md:271` | `_resident_fit.py` | 51 | 55 |
| `src/decoy_engine/reasons/decoy/_core.py` | register the identity and add it to `__all__` | `CODEMAP.md:288` | `ISOLATED_WORKER_OUT_OF_MEMORY` | 288 | about 296 |
| `src/decoy_engine/errors.py` | `CAPACITY_REASON_CODES` entry | `CODEMAP.md:262` | the `ISOLATED_WORKER_OUT_OF_MEMORY` entry | 599 | 600 |
| `changelog.d/<fragment>` | names the new identity | release notes | other fragments | 0 | about 3 |
| `tests/unit/execution/publication/_isolated_support.py` | ordered table-spec plant mode | existing shared publication test support | `test_isolated_parent_measures.py` | 136 | about 150 |
| `tests/unit/execution/test_resident_fit_decision.py` | pin the full-frame refusal before the refactor | existing resident-fit tests | `test_resident_fit_transitions.py` | 525 | about 540 |
| `tests/unit/reasons/test_capacity_reason_codes.py` | update A11's expected membership | existing registry tests | registry walk | 80 | 81 |
| `tests/unit/execution/publication/test_isolated_readback_cap.py` (new) | A1 to A9, A12 | `CODEMAP.md:172` | `test_isolated_parent_measures.py`, `_isolated_support.py` | 0 | about 320 |
| `tests/unit/execution/publication/test_isolated_commit_memory.py` (new) | A14 and G14 | `CODEMAP.md:172` | `test_isolated_readback_cap.py` | 0 | about 150 |
| `tests/unit/execution/pipeline/test_resident_floor_reality.py` (new) | A10 | existing sub-package `tests/unit/execution/pipeline/` | `test_lifecycle_inputs.py` | 0 | about 120 |
| `tests/unit/execution/test_isolated_safe_error.py` | A13 producers | `CODEMAP.md:271` | `test_isolated_run.py` | 418 | about 440 |

Test placement: no new file goes in the flat `tests/unit/execution/` directory (`CODEMAP.md:171`).
The readback cases go in `tests/unit/execution/publication/` rather than a new `isolated/`
sub-package: the readback is the step that admits and publishes the child's stage, that
directory already holds the isolated publication tests (`test_isolated_parent_measures.py`,
`test_isolated_marker_corpus.py`), and it has `install_fake_worker`, so no new sub-package or
CODEMAP row is needed. A10 tests the shared floor formula of `execution/pipeline/`, so it goes in
`tests/unit/execution/pipeline/`.

No new source module and no new package: `execution/` is over its fan-out freeze (109 entries
against 104, `CODEMAP.md:271`), and every change fits an existing module under 600 lines.

## Slices

One slice, engine repo, branch `feat/f25-g7-3-readback-cap`: about +170 / -15 source lines and
+480 test lines. First run the class 9 characterization against main. Run A10 next and fix any floor violation before using the floor. Add A1 to A9 and A11 to A14, then implement the cap. Tests: T0 and T1 per commit, T2 at each
gate on the exact head. The reason registry is a frozen contract surface, which is a full-suite
escalation trigger; the slice rides the next merge train for its one full suite against the
stored baseline.

## Pre-mortem

- A10 finds a type whose floor is above reality. Plan review ran the floor against
  `resident_spec(pq.read_table(...))` on pyarrow 24 for the riskiest types (dictionary int8 and
  int64 indexes, duration, float16, decimal128, date64, time32, struct of list) with no violation,
  so this is unlikely; A10 still pins it. If it goes red, the fix goes in `_lazy_column_bytes`
  (`_resident_bytes.py:183`), which also corrects `check_pre_read`, and lands before the cap.
- Swap makes the cap refuse a run that `main` completes. On Linux with swap on and on macOS
  (compressor and dynamic swap, `H` is host RAM), a run whose output fits only with swap is
  refused. This is the accepted #777 assumption (Guarantee). If a real run reports it, the
  swap-aware ceiling in V2-LOG is the fix, not a lower floor.
- On Windows the cap does nothing because ceiling detection fails; a large readback can still
  kill the driver as on `main`. Accepted; V2-LOG.
- The spy patches the wrong name (a by-value import elsewhere): A4's per-table call count catches a
  spy that sees nothing.
- `_isolated_run.py` goes over 600 lines: the Placement row names the move in advance.
- A4 and A7 start real children. Keep those jobs below 1,000 rows. A7 stops after one rung.
- The ceiling patch leaks into the child: it cannot (fresh interpreter), and A4 shows the child
  completes normally under the patched driver.
- A reviewer asks for the cap to also catch string-heavy overruns: that is outside the guarantee
  (non-goal 1, Q1); record it, do not widen the slice.

## V2-LOG

- Existing ceiling accessors include `execution/pipeline/_resident_fit.py:219`,
  `generation/__init__.py:59` and the third copy, `generation/_bounds.py:545`
  (`detected_memory_bytes()`). Cross-package consolidation is a follow-up.

- Read back only on request: with `output_dir`, leave `outputs` unread or return lazy handles;
  removes D2 (Q2 option (b) or (c)).
- Row-group granularity for the readback check, so one very large table is checked between row
  groups; needs a parity proof for chunk layout against `pq.read_table`.
- A tighter floor for string and binary payloads from footer statistics or `total_byte_size`.
- Bound the result-envelope read (`read_envelope`) and the `row_errors` it carries.
- Bound the child's stdout and stderr: `proc.communicate()` (`src/decoy_engine/execution/_isolated_run.py:477`) holds both in driver memory without a cap.
- A swap-aware refusal ceiling: add `SwapTotal` (host) or `memory.swap.max` / `memory.memsw.limit_in_bytes` (cgroup) to `H` for refusals only, leaving the admission and budget ceilings unchanged.
- Ceiling detection on Windows (for example `GlobalMemoryStatusEx` through `ctypes`), so the cap is not inert there.
- The child's resident-fit checks read the `RLIMIT` as their kill ceiling, with the governor taught
  to reroute on that refusal.
- When row 58b or CHUNK-PARALLEL brings an explicit memory budget, the readback ceiling becomes
  `min(H, budget)`.
- A bounded footer read for child-staged files.
- The probe reads back outputs it never uses; skip the readback for the probe once Q2 (b) exists.

## Owner questions

**Q1. What may the cap refuse?**

- (a) Only what a strict floor proves cannot fit under the detected kill ceiling. This accepts the documented swap exception and can miss string-heavy overruns. **Recommended** (matches row 58b's
  no-default-limit rule and `_resident_fit`'s rule).
- (b) An estimate (footer `total_byte_size`) against 85% of the ceiling. Catches more, but can
  refuse runs that complete today.
- (c) A fixed default cap in Spark's 1 GiB style. Simple, but refuses large runs that work.

**Q2. With `output_dir` given, what happens at the cap?**

- (a) Refuse the whole run and publish nothing; `outputs` keeps its contract (a dict on every
  completed run). **Recommended for 1.0.**
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

## Finding map (plan review rounds 1 and 2, and self-review)

| Finding | Where addressed |
|---|---|
| V1 test placement in flat `tests/unit/execution/` | Placement and sizes: A1 to A9, A12 in `publication/`; A10 in `pipeline/`; reason stated |
| DESIGN swap overclaim | Guarantee "Assumption: swap is not counted"; failure-modes rows; Pre-mortem; V2-LOG swap-aware ceiling |
| V2-LOG `check_readback` return and ceiling accessor | Behaviour step 3; Choke points; `ResidentFit \| None`, public `kill_ceiling()` |
| V2-LOG ENOMEM and text-matched reclassification; memory value; reason builder | Behaviour step 7 (`ReadbackMemoryFailure`, `ReasonRecord.for_reason`); failure-modes row; A9 ENOMEM variant; Frozen contracts |
| V2-LOG Class 7 one-handle claim; footer `ParquetFile` left open | Class table row 7 now N/A with reason; Behaviour step 2 `with` block; A12 descriptor check includes the footer |
| V2-LOG A4 floor vs held vacuous | Behaviour step 8 and A4: both over outputs only, `sources_bytes` separate |
| V2-LOG A12 work-root claim with caller `staging_dir` | A12 matrix adds the caller `staging_dir` axis |
| V2-LOG `capacity_message` remedy | Choke points: `remedy` argument; full-frame text byte-identical; readback remedy |
| V2-LOG Windows detection inert | Guarantee assumption; Routes; failure-modes row; Pre-mortem; V2-LOG |
| V2-LOG `proc.communicate()` unbounded | V2-LOG |
| V2-LOG Fake worker for speed | Acceptance preamble: `install_fake_worker` for most cases, real child per route in A4 and A7 |
| V1 round 2, full-frame refusal text | Acceptance pins the complete main message before extraction. Choke points defines both whole remedies. Class 9 requires a one-word mutation to fail. |
| V2-LOG round 2, cleanup on detection error | Behaviour step 4 and A12 put scratch output cleanup in `finally` and check only `staging_output/` inside a caller root. |
| V2-LOG round 2, fixed fake-worker output | Acceptance and Placement specify the shared helper's ordered table-spec mode for two tables and canaries. |
| DESIGN round 2, duplicate ceiling accessor | Behaviour step 3 renames and exports the existing function directly. V2-LOG records the generation copies. |
| V2-LOG round 2, route evidence and QA | Class rows 4 and 8 match the fake-worker cases and the A4 and A7 real-child pair. A7 checks one trip. |
| V1 self-review, caller sources missing from collect | Behaviour steps 1 to 3 carry resident source facts to the comparison. A3 isolates their contribution. |
| V2-LOG self-review, test evidence | A4 reads published files. A10 covers intentional zero floors. A11 updates expected membership. G12 catches the cleanup regression even with the outer abort. |
| V1 self-review, Arrow-only pricing | Behaviour step 3 prices shared buffers without interpreting pandas metadata. A4 checks the original schema and metadata. |
| V1 repeated review, memory failure after irreversible publication | Guarantee, Commit boundary, Failure modes and Exit paths tie the public outcome to the actual bind. A14 and G14 exercise the guard. |
| V1 unguarded preparation | Commit boundary and A14 cover initial figures, target string, row errors and all later result construction before commit. |
| V1 self-review, receipt construction and caller unwind | Commit boundary and A14 cover the publisher before receipt return, verified replay, evidence replacement and outer cleanup. |
