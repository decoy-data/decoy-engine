# F25 G7-3: materialization cap on the isolated route

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, profiles/local-operations,
feature-dev, testing, security, cross-cutting-concerns, architecture, proportionality, reuse-first,
catalogs/recurring-defects, code-review, documentation, verification.

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

**Commit contract.** It holds on both routes of `run_pipeline_isolated`, through one boundary (section "Memory boundary"). On the isolated route, from readback setup through pre-call result preparation, a memory failure returns `crashed` with `decoy.process_out_of_memory` and NOT_PUBLISHED, and the stage is aborted. From immediately before the `publish_unit` call through final cleanup, a raised MemoryError returns the reserved memory result with UNKNOWN, no receipt and same-operation-id confirmation advice. This includes a matching replay. On the resident route (`isolate=False`) the same UNKNOWN result covers the span from immediately before `publish_resident` through the returned result, and NOT_PUBLISHED covers the completed result when there is no `output_dir`. CPython can raise between any two bytecodes, including after rename and before Python observes success. The guarantee is never a raw exception and never a false NOT_PUBLISHED once publishing may have started. A memory error caught inside the window is never turned into another verdict: inner handlers let it pass, and the one adapter that classifies it reports `process_out_of_memory`. A publishing run reports completion after it has a committed receipt and finishes result construction and cleanup. Before the window (staging, spawn, `run_pipeline` itself) memory errors behave as on `main`.

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
   when output_dir was given, else None)`, after cleanup. In `result_from_envelope`, start the scratch-stage cleanup try before target-string and row-error preparation, and include `collect`.
   In its `finally`, run the existing `shutil.rmtree(staging_output_dir, ignore_errors=True)`
   when `pub is None`. This also removes `staging_output/` when detection raises.
   Reason context: phase `FINALIZE`, publication `NOT_PUBLISHED`, cleanup confirmed by looking.
5. Otherwise reopen the admitted file through the capability and read it with the existing `arrow_adapter.read_table(handle)`, so the frame,
   chunking and metadata are `main`'s, and step 3 repeats for the next table.
6. After the last table, prepare the component names and publish under the boundary below. Build the completed result from the returned receipt. Scratch-only runs finish under the pre-call memory arm.
7. A memory failure while reading (`is_memory_failure`,
   `src/decoy_engine/fileaccess/_errors.py:160`, the predicate the worker already uses) is caught
   before the `(OSError, ArrowException)` arm. `collect` returns a typed
   `ReadbackMemoryFailure(receipt)` value, and `_result_from_envelope` maps it to
   `outcome="crashed"`, `reason=decoy.process_out_of_memory` (built with
   `ReasonRecord.for_reason`, never from the exception), fixed text, with the same abort and
   cleanup. A `MemoryError` instance (Arrow's included) is not caught there: it passes the
   handler through the `except MemoryError: raise` clause and `memory_boundary` returns the pre-call
   reserve, which has the same code, publication state, text, receipt and figures (its
   `cleanup_state` can differ, because the reserve is built before cleanup runs). **Behaviour change:** `is_memory_failure` also matches `OSError` with `errno.ENOMEM`
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

**Retry behavior checked on `abc5998fd`.** Neither the governor nor the probe retries on `process_out_of_memory` or UNKNOWN. The governor tests route ineligibility first. This reason does not qualify. Its `crashed` branch records one terminal trip with no reroute and returns `exhausted` (`_governor.py:160,372-405`). With the governor off, it runs once (lines 545 to 556). The probe returns inconclusive on any non-completed sample and exits its fraction loop immediately (`_probe.py:283-301,413-428`). Neither uses publication state to schedule another attempt.

For manual confirmation, rerun the same unit at the same destination with the original `PublicationRequest.operation_id`. Omitting the request generates a fresh id (`_isolated_commit.py:176-187`). Under the destination lock the publisher checks the stored result identity. A match verifies the vault and syncs before returning `already_committed`, without rebinding. Different content for that operation conflicts. An empty destination follows the ordinary first-bind path (`publication/_publish.py:255-256,291-309,339-366`).

**Refuse or fall back.** Falling back to the out-of-core route does not help: the child may
already be on it, and D2 is the driver reading the finished output. The only real fallback is to
not read the output back, as described in Q2. This plan recommends the refusal for 1.0.

### Memory boundary (section b, revised after Codex rounds 4 to 6)

Rounds 4, 5 and 6 each found the same class at a new site. A memory error raised after the
window opened was caught by a broad handler (`except Exception`, `except ArrowException`, `except
BaseException`) and turned into a data verdict: a refusal receipt, a malformed vault segment,
`unexpected_error`, or a raw escape on the route that had no reserve. The `c2b81ef1f` fix put
`fileaccess.reraise_memory(exc)` into three handlers. That is a per-site rule, so the next
unlisted handler fails the same way. This section replaces the per-site rule with one boundary
and one rule for inner handlers, both checked by construction.

**Survey at `c2b81ef1f`.** Broad handlers that the window runs through, found by an AST scan of
`publication/`, `vault/`, `fileaccess/`, `reasons/`, `reason_adapter.py`, `execution/_isolated_*.py`
and the modules they call:

| Site | Catches | What a memory error becomes today |
|---|---|---|
| `publication/_publish.py:276`, measurement | `(OSError, ArrowException)` | propagates (the `reraise_memory` call added in `c2b81ef1f`); a raw error on `isolate=False` (R6-2) |
| `vault/_format.py:276`, `_decode_rows` | `(ArrowException, KeyError, ValueError)` | propagates (`reraise_memory`); before that, a vault mismatch refusal (R5-1) |
| `execution/_isolated_commit.py:491`, `_typed_error` | `Exception` | propagates (`reraise_memory`); before that, NOT_PUBLISHED with the refusal receipt (R5-2) |
| `execution/_isolated_commit.py:299`, `collect` | `(OSError, ArrowException, MemoryError, KeyboardInterrupt)` | classified by `is_memory_failure` into `ReadbackMemoryFailure` |
| `reason_adapter.py:291`, `reason_from_exception` | `Exception` | `unexpected_error`, so NOT_PUBLISHED with the refusal receipt (R6-1) |
| `reason_adapter.py:330`, `:341`, `:483`, `:491` (`_identified_reason`, `_read_code`, `_lookup_captured`, `_remember`) | `Exception` | `unregistered_reason`, no code, not remembered: a wrong reason with no memory trace |
| `execution/_isolated_run.py:281`, the guard | `MemoryError` | the reserve, or a raw re-raise when `_pre_call` is unset (R6-3) |
| `execution/_isolated_run.py:332`, `_run_in_process` | `BaseException` | the run's own failure, `in_process_failure` (`oom_killed`); unchanged on purpose |
| `fileaccess/_errors.py:309`, `guarded_with_parser_errors` (and fileaccess `guarded` through it) | `Exception` | a typed `MemoryError` is re-raised as the same object (`passes_by_type`); a text-recognised memory failure is rebuilt scrubbed. In the window on 13 of 14 traced runs |
| `fileaccess/_errors.py:206`, `:216`, `:225` (`resurface_scrubbed`, `_errno_rebuild`, `_fixed_text_rebuild`) | `Exception` | a `MemoryError` while rebuilding becomes `None` (then `FileAccessReadError` at `:309`) or a second `OSError` |
| `fileaccess/_local_chain.py:60`, `:84`; `fileaccess/_output.py:260`, `:404`; `determinism/_derive.py:218`, `:313`, `:338`, `:428`; `determinism/_hkdf.py:58`, `:72`, `:90`; `internal/crypto.py:31`, `:47`; `_isolated_run.py:515`; `publication/_publish.py:471` | `BaseException` | cleanup, then a bare `raise`: already transparent |
| `fileaccess/_entry.py:266` (`__del__`); `internal/memory.py:53`, `:91`, `:115` | `Exception` | not in the window (A19 trace below) |

**A19 trace at `c2b81ef1f`** (prototype run 2026-11-27 on Python 3.10.20 and 3.12.13; the
handler lists are identical). Both routes, the six scenarios (scratch-only, publish, publish with
vault, matching replay with vault, occupied refusal, operation conflict) plus a `MemoryError` at
`publish_unit` entry. Recording starts at `Attempt.reserve` (isolated) or at `run_pipeline`'s
return (resident), takes the stack at that moment, and stops when `run_pipeline_isolated`
returns. Each scenario ran once untraced first. No thread started in any window. Sentinels
recorded: `_judge_and_bind`, `_check_vault`, `_decode_rows` (replay), `reason_from_exception`
(occupied, conflict). The window ran through 44 source files. Eleven of them hold a
memory-catching handler. The `SCOPE` patterns below cover those files plus `_isolated_reason.py` (the
boundary) and `_isolated_common.py`, kept from the earlier list. Non-compliant handlers found:
the six this design already names (`collect`, `_typed_error`, the old guard, `_judge_and_bind`,
`_decode_rows`, the adapter) and one more, `fileaccess/_errors.py:309`. Every
`contextlib.suppress` in the window names `OSError` only, and no `finally` in a `SCOPE` file holds
a `return`, `break` or `continue`. The fault scenario returned UNKNOWN on the isolated route and
escaped raw as `MemoryError` on the resident route: R6-2's class, which part 1 closes.

The expanded `trace3.py` records 26 runs and 45 source files. Its supplied 3.10 and 3.12
reports are identical. The additional cases exercise capacity refusal with and without a
destination, EIO and ENOMEM during measurement, and ENOMEM and marker text during readback.
They add no memory-catching handler to the scope. The readback-only injections are inactive
on the resident route. A19 checks the applicable cases below.

How the resident route reports errors today: `_run_in_process` (`_isolated_run.py:323`) catches
every failure of `run_pipeline` and returns `in_process_failure(exc)` (memory is `oom_killed`).
`publish_resident` then runs outside any handler. A non-committed receipt becomes
`failed_publication(..., isolated=False)`. Nothing owns a reserve, so any `MemoryError` in
publication or in building the result escapes `run_pipeline_isolated` raw. On `main` this
already happens for a bare `MemoryError`. An `ArrowMemoryError` in measurement used to become a
failed receipt only because the handler swallowed it.

**Options considered.**

- (a) The reason adapter as the one place that maps `MemoryError`, given the phase. Rejected as
  the whole answer. Two of the five reproduced faults never reach the adapter: the vault decoder
  returns a mismatch verdict and the publisher returns a failed receipt, both with no exception
  left to classify. And the adapter builds a `ReasonRecord`, while the contract needs a different
  `IsolatedRunResult` (no receipt, no outputs, the same-id text). The adapter keeps one job in
  the design below: it never hides a memory error behind another code.
- (b) A phase-aware outer boundary per public entry. Chosen, with two additions that make it
  hold by construction: inner handlers are memory-transparent in one exact syntactic shape that
  a sentry checks, and the boundary normalizes a memory-coded result by phase.
- (c) Observe every raised `MemoryError` at runtime (`sys.monitoring` `RAISE` and
  `EXCEPTION_HANDLED`, PEP 669) and let the boundary consult a latch. Rejected: Python 3.12 and
  later only, and the engine supports 3.10 to 3.12. `sys.settrace` on 3.10 and 3.11 would take
  over the slot that coverage and debuggers use. A10's corpus and the mutation runs need coverage.

**Design.** Three parts, one fact each.

1. **One boundary, both routes.** `memory_boundary(attempt, body)` in `_isolated_reason.py` is the only
   handler that turns a `MemoryError` into a result. `run_pipeline_isolated` calls it on both
   branches: `memory_boundary(attempt, lambda: _run_isolated(...))` and
   `memory_boundary(attempt, lambda: _run_in_process(...))`. The old `except MemoryError` in
   `run_pipeline_isolated` (`_isolated_run.py:281`) moves into it.

   ```python
   def memory_boundary(attempt: Attempt, body: Callable[[], IsolatedRunResult]) -> IsolatedRunResult:
       try:
           return attempt.settle(body())
       except MemoryError:
           reserved = attempt.memory_result()
           if reserved is None:  # Window.BEFORE: nothing has started that a result could describe
               raise
           return reserved
   ```

   The name is `memory_boundary`, not `guarded`, because `fileaccess._errors.guarded` already
   exists and is in the window. The `_isolated_reason.py` module docstring is rewritten to say
   the module owns the attempt windows, the reserves and the boundary for both routes.

   `Attempt` holds one `Window` value (replacing the `publishing` flag): `BEFORE`, `PRE_CALL`,
   `PUBLISHING`. It is built by `Attempt.isolated()` or `Attempt.resident()`. **Both reserves are
   built in the constructor**, before the route stages, spawns or runs anything, with
   `peak=None` and `pid=None`. Nothing inside a window builds a reserve. `memory_result()`
   returns `None` only in `BEFORE`, `_pre_call` in `PRE_CALL`, `_unknown` in `PUBLISHING`.
   Selecting a reserve allocates nothing beyond the method call.

   - `enter_readback(pid, peak)`: sets `PRE_CALL` first, then replaces `pid` and `peak` in both
     reserves. If that replacement fails, the earlier reserves (with `None` figures) stand.
   - `enter_publishing()`: sets `PUBLISHING`. It replaces `attempt.publishing = True` at the
     single isolated `publish_unit` call (`_isolated_commit.py:325`).
   - `failed_receipt_for(receipt)`: unchanged, but called in `_run_isolated` right after
     `begin_publication` (still `BEFORE`, before the spawn), not inside the readback.
   - `settle(result)`: in `PUBLISHING`, a non-completed result whose `reason.code` is
     `process_out_of_memory` is replaced by `_unknown`. Other publishing results are returned as built.
     In `PRE_CALL`, select the pre-call reserve for a memory-coded failure whose
     `reason.context.publication_state is None`. This is the context-free adapter fallback
     during classification of a failed admission or corrupt footer. Keep the already-contextual
     `ReadbackMemoryFailure` result, including its cleanup evidence and receipt. In `BEFORE`
     return the original result, including the resident run's own `oom_killed`. Inspect the
     existing fields without building a new result.

   Windows per route:

   | Route | `BEFORE` (raw, as on `main`) | `PRE_CALL` (NOT_PUBLISHED reserve) | `PUBLISHING` (UNKNOWN reserve) |
   |---|---|---|---|
   | isolated | staging, spawn, envelope read, a failed child's result | from the first statement of `result_from_envelope`'s completed branch (`enter_readback`, the statement that opens its cleanup `try`) to `publish_unit` | from immediately before `publish_unit` through `scratch.close()` |
   | resident (`isolate=False`) | `run_pipeline` and `in_process_failure` (its own classification, unchanged) | from `run_pipeline`'s return through the completed result when there is no `output_dir` | from immediately before `publish_resident` through the returned result |

   The resident reserves come from the same builder, renamed from `_readback_result` to
   `_reserved_result` because it now also builds resident `COMMIT` results, with `isolated=False`, `returncode=None`, operation `COMMIT`, and no receipt. With an
   `output_dir` the resident window goes to `PUBLISHING` before any publication code runs, so a
   pre-call receipt would never be used. The texts are the existing two: the summary plus the
   readback remedy, and the summary plus "Rerun with the same operation id to confirm."
   The isolated reserves keep their current fields. On the resident route put the window
   transition immediately after the run-only `try/except BaseException`, outside its protected
   body. A post-run allocation must never enter `in_process_failure`.

2. **Inner handlers are memory-transparent.** In every module the window runs through, a handler
   that can catch a `MemoryError` takes one of three shapes:

   - It is preceded, in the same `try`, by a handler of exactly `except MemoryError:` whose whole
     body is a bare `raise`. Python's own clause ordering then sends every `MemoryError`, Arrow's
     included, past the broad handler. No call can be skipped by a condition. `ArrowMemoryError`
     subclasses `MemoryError` (`pyarrow/error.pxi`), so one clause covers both.
   - Its last top-level statement is a bare `raise`, every `raise` in its body is bare, and its
     body holds no `return`, `break` or `continue` (nested `def` and `lambda` bodies excluded).
     Cleanup handlers such as `publish_tables`'s `except BaseException: txn.abort(); raise` pass.
     `except Exception: if cond: return None` followed by `raise` does not: it is a conditional
     swallow.
   - It is one of the three registered classifiers (the choke point, not a debt list):
     `_isolated_reason.memory_boundary` (the boundary), `reason_adapter.reason_from_exception` (the
     adapter, part 3) and `_isolated_run._run_in_process`'s run handler (the run's own failure,
     outside every window, unchanged from `main`).

   `fileaccess.reraise_memory` is **removed**, with its export and its three calls. The call
   becomes the clause at the same three sites: `publication/_publish.py:276`,
   `vault/_format.py:276` and `_isolated_commit._typed_error`. `collect` gets the clause ahead
   of its handler and drops `MemoryError` from that tuple. A real `MemoryError` in the readback
   now reaches the boundary and returns the pre-call reserve (same code, state, text, receipt
   and figures as `ReadbackMemoryFailure`). The handler keeps `is_memory_failure` for the shapes
   that are not `MemoryError`: `OSError(ENOMEM)`, marker-matched Arrow text, and a
   `KeyboardInterrupt` with a memory cause. The adapter's inner handlers at `:330`, `:341`,
   `:483` and `:491` get the clause. Their memory error then reaches the one classifier.

   Two more memory leaks out of a handler are findings: `contextlib.suppress(...)` naming
   `Exception`, `BaseException`, `MemoryError` or `ArrowMemoryError` (it is a handler without
   the `except` keyword), and a `return`, `break` or `continue` inside a `finally` (it discards
   the in-flight exception). The A19 trace found neither in the window today.

   **`fileaccess/_errors.py` joins the scope (found by the A19 trace).** Its four `except
   Exception` handlers get the clause:

   | Handler | Effect of the clause on a `MemoryError` | Non-memory verdicts |
   |---|---|---|
   | `:309` `guarded_with_parser_errors` (also `guarded` and strict iteration) | a typed `MemoryError` still passes by identity. A rebuild fault now propagates after the library handler closes | retain parser, denial, iterator and other by-type pass-throughs |
   | `:206` `resurface_scrubbed` | the text rebuild used to return `None`, leading to a read error or a false predicate. The rebuild now raises `MemoryError` | unchanged |
   | `:216` `_errno_rebuild` | serves both ENOMEM and resource errnos ENOSPC/EDQUOT. A constructor OOM used to trigger the plain `OSError` fallback. It now propagates | ordinary constructor rejection still uses the fallback |
   | `:225` `_fixed_text_rebuild` | the fixed-text constructor used to return `None` on OOM. It now propagates the fault | unchanged |
   | `fileaccess.keeps_class` (`_read.py:77–95`) | about 21 handlers use this predicate. Under a strict policy a text rebuild OOM in `resurface_scrubbed` now raises where the predicate returned `False` | ambient policy still returns `False` without a rebuild |
   | exported `fileaccess.classified_failure` (`_errors.py:244–259`) | strict boundaries use this policy-independent classifier. Errno rebuild OOM now raises where the caller received a fallback OS error in `fresh`. Fixed-text rebuild OOM now raises where it received a classification with `fresh=None` | unrecognised input still returns `None` |

   In `guarded_with_parser_errors`, keep the transparent clauses. In the translating handler
   save the exception in a separate local (`caught = exc`, since Python clears the handler
   target on exit). Call `_resurface(caught)` after that handler closes. If it returns the
   original, raise that object with its existing chain. Raise a fresh replacement or the
   ordinary read error as today. The rebuild's own `MemoryError` now has no library error as
   its context. A21(ii) checks the exception object and traceback rendering.

   The existing guarded contract, `vault/_reader.py:231` and the `ClassifiedFailure` docstring
   deliberately keep fresh failures free of the original chain. Rebuilding inside another
   caller's active handler can **introduce** that chain. A21 covers the remaining callers'
   changed verdicts. The residual traceback surfaces are recorded under V2-LOG. The other A19 additions (`_local_chain.py`, `_output.py`,
   `determinism/_derive.py`, `determinism/_hkdf.py`, `internal/crypto.py`) already pass shape 2
   and need no edit; `SCOPE` keeps them that way.

   **The publisher change stays**, in the clause shape. Without it a measurement `MemoryError` on
   a matching replay becomes a failed receipt that says NOT_PUBLISHED about a target that exists
   (Codex round 5, V2-LOG item 2). It no longer breaks `isolate=False`, because that route now
   runs under the same boundary (part 1). Its effect on the other `publish_unit` callers is
   stated and pinned in A20: `ParquetTransactionalSink.commit` and `DeliveryStage` raise the
   `ArrowMemoryError`, as they already raise a bare `MemoryError` on `main`, instead of returning
   a failed receipt. The vault decoder's clause has the same effect on vault readers: memory
   pressure is raised, never reported as a malformed segment.

   In resident `publish_tables` (`publication/_publish.py:458–474`), use the existing
   `with txn:` after a successful begin. It owns cleanup through the stage-path callback,
   table writes and the call into `publish_unit`. Keep the write-only OSError-to-receipt
   handler narrow. The txn context replaces the manual write-path aborts and closes the
   gap before the callee's own finalizer starts. Abort is idempotent after bind or abort.

3. **The adapter never hides a memory error.** `reason_from_exception` moves
   `_lookup_captured` and `known.with_context` inside its `try` and gets one clause ahead of
   `except Exception`:

   ```python
   except MemoryError:
       return _OUT_OF_MEMORY
   ```

   `_OUT_OF_MEMORY` is a module-level `ReasonRecord.for_reason(PROCESS_OUT_OF_MEMORY)` built at
   import, so the handler allocates nothing. It drops the caller's phase and context. The code is
   what a consumer acts on, and a memory failure while classifying is rare. Callers now get `process_out_of_memory` instead of
   `unexpected_error` or `unregistered_reason` when classification runs out of memory. On the
   isolated and resident routes that record reaches `settle`, which selects the UNKNOWN reserve
   once publishing has started. Before publication the same fallback selects the pre-call
   reserve as specified in part 1. The adapter needs no new public name.

   The adapter has a second change, the clauses at `:483` (`_lookup_captured`) and `:491`
   (`_remember`). These change behaviour outside the window. `capture_failure`,
   `amend_failure`, `FailureScope.capture` and `tag_exception` (12 call sites outside the
   adapter) call them. Today a `MemoryError` inside them is swallowed and the caller raises its
   original exception. After the change the caller raises `MemoryError` instead. Under memory
   pressure the memory error is the more accurate report, and every boundary that classifies the
   caller's exception also maps `MemoryError`, so this is accepted. A21 pins it.

   Residual, as on `main` (V2-LOG): a second memory error inside the `_record(UNEXPECTED_ERROR)`
   arm, after `except Exception` has caught a non-memory failure, escapes the adapter. Only the
   pre-built `_OUT_OF_MEMORY` path allocates nothing.

**Why each finding closes without a per-site edit.**

| Finding | Closed by |
|---|---|
| R6-1: `MemoryError` in `_classify` while building the refusal returns `unexpected_error`, NOT_PUBLISHED | Part 3 returns `process_out_of_memory` for any memory error inside classification. Part 1's `settle` turns any memory-coded result in `PUBLISHING` into the UNKNOWN reserve. A future memory error in any builder that goes through the adapter lands the same way, on either route. |
| R6-2: raw `ArrowMemoryError` on `isolate=False` | The resident route runs under `memory_boundary` with reserves built at entry and `PUBLISHING` set before `publish_resident`. A raw error from publication or result building has a reserve to select. |
| R6-3: a fault building the first reserve escapes raw after the child ran | Reserves are built in the `Attempt` constructor, before any stage, spawn or run. Inside a window nothing builds a reserve, so `memory_result()` cannot be `None` there. A fault in the constructor raises before any side effect, which is the same as the caller's own allocation failing before the call (A18). |
| R6 DESIGN: the guard accepts a conditional call and a tuple with `MemoryError`, and omits `reason_adapter.py` | The guard accepts only the exact clause, a final bare `raise`, or a registered classifier. Calls do not count, and a tuple that contains `MemoryError` is a finding. The scope is checked against a trace of the window on both routes (A19), so a module the window runs through cannot be left out. |
| R5-1: vault decoder turns `ArrowMemoryError` into a mismatch | The clause in `_decode_rows`, required by the guard because A19 traces it on a matching replay. |
| R5-2: `_typed_error` catches `MemoryError` from `raise_for_outcome` | The clause, required by the guard. Also covered by part 3 and `settle`: a returned `MemoryError` is classified `process_out_of_memory` and normalized to UNKNOWN. |
| R5-3: a pre-call fault leaves `staging_output/` in a caller `staging_dir` | Unchanged from `c2b81ef1f`. The scratch-stage `finally` opens at the same statement that enters `PRE_CALL`, so a window and its cleanup start together. |

**What the contract still does not cover** (non-goals, V2-LOG): a memory error in `BEFORE` on
either route (as on `main`); `OSError(ENOMEM)` and marker-text memory failures inside the shared
publisher, which stay ordinary failed receipts; a `KeyboardInterrupt` with a memory cause after
the flag; and the publication state the transactional sink records for a memory error during a
matching replay. CPython can still fail to allocate the frame for `memory_result()` itself; no
Python-level boundary can rule that out. Two narrower residuals: a frame-allocation failure on
the `enter_readback` call itself leaves the window at `BEFORE`, so that one error escapes raw as
on `main`; and an `OSError` from `pub.txn.abort()` in `_run_isolated`'s `finally` replaces an
in-flight `MemoryError`, so the caller sees the abort failure.

**Decisions (orchestrator, 2026-11-27, conservative option, both technical):**

- D-A20. The behaviour change A20 pins is accepted: `ParquetTransactionalSink.commit` and
  `DeliveryStage` raise a measurement `ArrowMemoryError` as `MemoryError`, as they already raise
  a bare `MemoryError` on `main`, instead of returning a failed receipt.
- D-BEFORE. A raw `MemoryError` before the window opens (`BEFORE` on either route) stays raw, as
  on `main`. No pre-window reserve is added.

### Design notes

The cap adds one caller to the existing resident-fit comparison. The memory boundary follows the Java split of `Error` from `Exception`: inner handlers are transparent to out-of-memory by construction, and one top-level handler per attempt turns it into a result (one place for the window, one for the reserves, one for the classification). One fact, one place: the bound formula stays in `_resident_bytes.py`, the ceiling in
`kill_ceiling`, the comparison in `resident_fit_verdict`, the capacity text in `_errors.py`. The
refusal travels as a typed value (`ReadbackRefused`) instead of a flag argument.

## Failure modes

| Failure | Detected at | Reason code | Value-free | Test |
|---|---|---|---|---|
| Footer floor of outputs plus resident caller sources over `H` | `check_readback`, before the first decode | `decoy.isolated_readback_capacity_exceeded` | fixed summary, two integers | A1, A3 |
| Measured bytes of tables read plus floor of the rest over `H` | `check_readback`, before the next decode | `decoy.isolated_readback_capacity_exceeded` | same | A2 |
| Refusal with `output_dir` | `collect` aborts the transaction before `publish_unit` | same; receipt `failed` | receipt carries codes only | A8 |
| `OSError(ENOMEM)` or a marker-matched memory message during a read (behaviour change: was `publication_failed`) | `collect`, `is_memory_failure` arm | `decoy.process_out_of_memory` | fixed text, no errno text | A9 |
| Memory failure from setup through pre-call result preparation or scratch-only completion, including `ArrowMemoryError` or `MemoryError` during a read (it passes `collect`'s clause) | `memory_boundary`, window `PRE_CALL` (both routes) | `decoy.process_out_of_memory`, NOT_PUBLISHED, stage aborted | Fixed text, no exception text | A9, A14, A18 |
| MemoryError raised inside `publish_unit` or `publish_resident`, including measurement and replay verification, or later in result building or cleanup | `memory_boundary`, window `PUBLISHING` (both routes) | `decoy.process_out_of_memory`, UNKNOWN whether the target exists or not, no receipt | Fixed same-id retry text | A14, A15, A17, G14 |
| MemoryError while the reason adapter classifies a refusal after the flag | adapter clause returns `process_out_of_memory`; `settle` selects UNKNOWN | same as the row above | Fixed same-id retry text | A16, G15, G20 |
| MemoryError while building the reserves | `Attempt` constructor, before any stage, spawn or run | none: raised before any side effect, as on `main` | n/a | A18, G17 |
| `ArrowMemoryError` in measurement through the transactional sink or `DeliveryStage` (behaviour change: was a failed receipt) | publisher clause | raised `MemoryError`; the sink captures `process_out_of_memory` | no text added | A20, G19 |
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
  `error`, nothing published, stage removed. The Arrow and bare variants take the
  `memory_boundary` pre-call reserve (they pass `collect`'s clause); the ENOMEM and marker
  variants take `collect`'s `is_memory_failure` arm. G9: delete the memory arm; the ENOMEM and
  marker variants fail the reason assertion. G14 (remove the outer boundary) kills the Arrow and
  bare variants.
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

- **A14 memory errors across the publication call.** Add the new cases in `tests/unit/execution/publication/test_isolated_commit_memory.py`. Use the public isolated entry point, a fake child, real staging and one injected fault per run. Assert that each fault fired.
  - Before the flag, inject at request and reader setup, initial `Readback` and `asdict`, `str(pub.target)`, `row_errors_of`, admission, decode, measurement, component creation and pre-call result preparation. Include refusal handling and the scratch-only result, mapping defaults and evidence. Patch the actual lookup or expression. Assert `crashed`, `process_out_of_memory`, NOT_PUBLISHED, fixed text, no outputs, stage removed and no new target. Repeat applicable cases without publication, including a fault before the reader exists.
  - Raise inside `publish_unit` before it binds anything. In a separate run, call the real publisher and raise before its receipt reaches the caller. Assert UNKNOWN in both cases. Check the first target is absent and read the descriptor and Parquet from the second. On a matching rerun with a vault, inject in `_check_vault`. Expect UNKNOWN and unchanged target and vault. A fault-free confirmation with the same request returns `already_committed`.
  - After a real committed receipt returns, fault the completed-result build, evidence replacement, transaction abort and scratch close in separate runs. For cleanup faults, wrap real cleanup and record both calls in order. Require the target to remain readable, and scratch close to run even when abort raises.
  - At every post-flag fault assert the reserved `crashed` result, `decoy.process_out_of_memory`, UNKNOWN, the exact fixed retry text, last complete readback figures, no receipt, no outputs and no exception text. Check normal success still has its outputs, row errors and receipt.
  - **G14.** Remove only the outer memory guard. Leave the flag, reserves and pre-call classification intact. A fault after the flag must now escape raw or report NOT_PUBLISHED. Require A14 to go red, restore the guard and rerun on the final head.

- **A15 round 5 cases (on the branch).** The `test_a15_*` cases in `test_isolated_commit_memory.py`
  stay as they are: replay measurement, vault segment decode, refusal error build, the caller
  `staging_dir` setup fault and `scratch.close()`. A15's vault-decode and refusal-build cases also
  run on `isolate=False` in the new file below (both routes, same assertions, `isolated is False`).

New cases go in `tests/unit/execution/publication/test_memory_boundary_routes.py`. Route cases use the public `run_pipeline_isolated`: `isolate=True` with the fake child, and
`isolate=False`, which runs `run_pipeline` in process on the same two-row job. Reuse `once`,
`memory` and `UNKNOWN_TEXT` from `test_isolated_commit_memory.py`. Each fault case asserts its fault
fired. A16 to A18 and A21 (i), (ii) must fail on `c2b81ef1f`, at least on the route their finding
names, before the change. On the pin, arm A16 at the actual publish call and fault
`_readback_result` from `Attempt.reserve` for A18(i). After refactoring, arm the corresponding
window and builder. Missing new symbols do not count as red evidence. Record fired injections,
observed verdicts and the red run's failing ids. A19, A20 and the guard are proven by
their mutations.

- **A16 memory error while classifying a refusal (R6-1).** Occupied destination: a different
  result already bound at the target. Inject a one-shot `MemoryError` into
  `decoy_engine.reason_adapter._classify`, armed only after `enter_publishing` runs (a spy on
  `enter_publishing` arms it), so an earlier classification cannot consume the shot. Expect `crashed`, `process_out_of_memory`, UNKNOWN,
  `publication_receipt is None`, `outputs is None`, `error == UNKNOWN_TEXT`, no canary, and the
  bound target unchanged (descriptor bytes equal). Red on `c2b81ef1f`: `unexpected_error`,
  NOT_PUBLISHED. Direct adapter cases in the same file: with `_classify`, `_read_code`,
  `_identified_reason` or `_lookup_captured` raising `MemoryError`, `reason_from_exception`
  returns `process_out_of_memory` and does not raise. Exercise the real inner handlers too:
  fault the property read inside `_identified_reason` and `_read_code` using their registered
  exception families. Fault `known.with_context` on a captured record with caller context. With `_classify` raising `RuntimeError` it
  still returns `unexpected_error`. Also force an ordinary corrupt-footer refusal on the
  isolated route, then fault classification of its failed receipt in PRE_CALL. Assert fixed
  pre-call memory text, NOT_PUBLISHED, failed receipt for a requested target (none for scratch),
  stage removed, and no outputs. Without the classification fault retain the ordinary receipt
  verdict. A9's ENOMEM result retains its measured cleanup evidence.
- **A17 measurement memory error (R6-2).** `ArrowMemoryError` from the publisher's `_measure`
  (patched at `decoy_engine.publication._publish._measure`), first on a fresh destination, then
  on a matching replay. Expect the UNKNOWN reserve on both routes and no raw exception. The fresh
  target is absent. The replay target is unchanged, and a fault-free rerun with the same request
  returns `already_committed`. Red on `c2b81ef1f` for `isolate=False`: the raw `ArrowMemoryError`
  escapes. Controls on both routes: `ArrowInvalid`, `OSError(EIO)` and `OSError(ENOMEM)`
  measurement faults still return `publication_failed` with a failed receipt and NOT_PUBLISHED.
  On the resident route also fault the stage-path callback lookup (`txn.local_stage_path()`)
  and the entry to `publication._publish.publish_unit` before its body runs. For each, require
  UNKNOWN, an absent fresh target and no pending publication stage. With no output directory,
  fault the resident completed-result build after the real run returns. Require the PRE_CALL
  result, `isolated=False`, no receipt and the fixed pre-call text.
  The measurement ENOMEM control pins the ordinary failed receipt through `settle`.
- **A18 reserve faults (R6-3).** (i) A `MemoryError` on the first call of the reserve builder
  (`_isolated_reason._reserved_result`). Expect `MemoryError` raised from `run_pipeline_isolated`.
  On the isolated route, `on_spawn` is never called, no `decoy-isolated-run-*` work root exists
  under the scratch root, and no publication stage or target exists beside `output_dir`. On the
  resident route, a spy on `run_pipeline` sees no call. Red on `c2b81ef1f`: the child has already
  run when the raw error appears. (ii) A `MemoryError` inside `enter_readback`'s reserve refresh,
  isolated only. Expect the pre-call reserve with `pid is None` and `peak_rss_mb is None`,
  NOT_PUBLISHED, and the stage removed. Compute both refreshed copies before assigning either.
  Fault each replacement in turn. Also retarget the existing A14 failed-receipt construction
  test (`test_isolated_commit_memory.py:108`) to its new pre-spawn lookup: per D-BEFORE it
  raises raw, skips spawn and cleans up the opened transaction. Keep A14's post-entry setup
  faults expecting NOT_PUBLISHED.
- **A19 the guard's scope is the window's.** Run the scenario matrix under `sys.setprofile`:
  scratch-only success; `output_dir` publish without and with a vault; matching replay with a
  vault; occupied refusal; operation conflict; and a `MemoryError` at `publish_unit` entry. Use
  both routes (14 runs). Add the expanded trace's measurement controls on both routes and
  the refusal and readback cases on the isolated route (eight additional runs). Require each
  injected fault or refusal condition to fire. The prototype is described under "A19 trace" in the Memory boundary
  section. Run this gate with PyNaCl installed (`nacl.bindings` importable) on each
  supported trace interpreter. A skipped vault case cannot establish the replay sentinel.
  Assert the expected result per scenario and route. Check the applicable sentinels within the
  corresponding route and scenario (for example, vault decode on each matching replay). The test follows the prototype:
  - Warm each scenario once untraced, so lazy imports run outside the trace, and ignore
    `<module>` code objects.
  - Bind the trace to the outer public invocation and its own `Attempt`. Start at that
    attempt's first window transition only. A resident `run_pipeline` can launch an isolated
    admission probe before it returns. Its reserve, sampler thread and return must neither
    start nor stop the resident trace. Assert exactly one start and stop for the selected
    attempt. Apply the same outer-attempt filter when arming route-specific OOM injections.
    At entry add every frame on the stack at that moment whose file is under `src/decoy_engine/` (the
    same filter as later events), then every later `call` event under `src/decoy_engine/`.
  - Stop on return from that same boundary frame. Restore the previous profiler and thread spy
    in teardown, including when the run raises.
  - Map each code object, including a lambda, comprehension or nested function, to the
    innermost enclosing `def` whose AST line span (first decorator line to `end_lineno`) holds
    its `co_firstlineno`. This works the same on 3.10 to 3.12.
  - Assert no thread starts inside a window (a spy on `threading.Thread.start`).
  - Assert the sentinels are recorded: `_judge_and_bind`, `_check_vault`, `_decode_rows` on the
    vault replay, and `reason_from_exception` on the occupied refusal. A trace that misses them
    is vacuous.
  - Every recorded function that contains a memory-catching handler or a memory-naming
    `contextlib.suppress`, or a forbidden finally exit, must be in a file in the guard's `SCOPE`. The failure message names
    the file and function.

  G18: remove `reason_adapter.py` from `SCOPE`; A19 goes red naming `reason_from_exception`.
- **A21 behaviour outside the window.** Direct cases in the same file.
  1. In `tag_exception` and standalone `capture_failure`, fault construction of `_Captured`
     **inside** the real `_remember` try. A `MemoryError` propagates. A `RuntimeError`
     retains the ordinary return (original exception or reason record respectively). For
     `_lookup_captured`, fault validation of a genuinely remembered record inside its try.
     Classification returns the reserved memory code, and direct `amend_failure` propagates OOM.
  2. (A21 ii) Construct the original error first, then arm its type's constructor to raise
     a fresh, fixed-text `MemoryError` only on rebuild. Assert the fault fired and the same
     fault reached the caller. Exercise the three real rebuild helpers. Through a strict
     `guarded_with_parser_errors`, fault a marker-text rebuild and a resource-errno rebuild.
     Assert `__context__ is None`, `__cause__ is None`, and no original data canary in the
     formatted traceback or exception text. Under a strict policy call exported `keeps_class`
     on the marker case. Call exported `classified_failure` on a marker-text error and on
     ENOMEM, ENOSPC and EDQUOT. Each fault must raise. Controls use an unarmed constructor
     and check normal classification, scrubbed text and preserved errno where applicable.
  3. A typed `ArrowMemoryError` through the strict guard retains identity, and an allowed
     parser error passes unchanged. Cases (i) and (ii) distinguish the old behavior on the pin.
- **A20 the raising `publish_unit` callers.** `ArrowMemoryError` in measurement through
  `ParquetTransactionalSink.commit` and through `DeliveryStage`'s bind. Each raises
  `MemoryError` (`isinstance`), binds nothing (target absent), and leaves no stage. For the sink,
  the captured reason is `process_out_of_memory`. This pins the stated behavior change. G19:
  remove the publisher clause; the sink raises `PublicationFailed` instead and A20 goes red.

**The guard.** `tests/sentry/defects/memory_boundary/test_memory_errors_reach_the_boundary.py`,
with its scanner in `tests/sentry/defects/memory_boundary/_memory_scan.py` and an empty
`__init__.py`. `tests/sentry/defects/` already holds 35 entries, so the rule gets its own
subpackage; `test_sentry_manifest` collects nested sentries. A19 imports `SCOPE` and the handler
predicate from the scanner, so there is one definition of both. `CODEMAP.md:298` places
recurring-defect class rules in `tests/sentry/defects/`. Delete
`tests/sentry/test_commit_path_memory_rule.py`.

- `SCOPE` (from the A19 trace): `publication/*.py`, `vault/*.py`, `reason_adapter.py`,
  `execution/_isolated_commit.py`, `execution/_isolated_reason.py`, `execution/_isolated_run.py`,
  `execution/_isolated_common.py`, `fileaccess/_errors.py`, `fileaccess/_local_chain.py`,
  `fileaccess/_output.py`, `determinism/_derive.py`, `determinism/_hkdf.py`,
  `internal/crypto.py`. The guard asserts each entry matches at least one file, so a rename
  cannot empty the scope silently.
- Reuse `ModuleIndex` from `tests/sentry/defects/_defect_scan.py:70` to resolve imported
  exception and suppress aliases. Seed `from pyarrow import ArrowException as AE`,
  `import contextlib as cl` and `from contextlib import suppress as ignore`. Use the same
  normalized predicate for A19 discovery, including forbidden finally exits in traced
  functions that contain no handler.
- A handler can catch `MemoryError` when its type is bare, or names (as a `Name` or the last
  `Attribute` part, inside a tuple or not) `Exception`, `BaseException`, `ArrowException`,
  `MemoryError` or `ArrowMemoryError`.
- It passes only in the three shapes of part 2. The memory clause must be exactly
  `except MemoryError:` (not a tuple, not `ArrowMemoryError`) with the body `[Raise(exc=None)]`,
  and it must come before the broad handler in the same `try`. A final bare `raise` must be the
  handler's last top-level statement, every `raise` in the body must be bare, and the body
  (nested `def` and `lambda` excluded) must hold no `return`, `break` or `continue`. A
  `contextlib.suppress` call naming a memory-catching type, and a `return`, `break` or
  `continue` inside a `finally`, are findings in any `SCOPE` file. Classifiers are matched by module and qualified function
  name, and only the registered handler may translate memory.
  In the adapter the exact `except MemoryError: return _OUT_OF_MEMORY` precedes its ordinary
  `except Exception` fallback in the same try. Count the converting arm once and check its
  sibling order explicitly. In the resident classifier only the `run_pipeline` call belongs
  in the protected body. Check any other handler in these functions by the ordinary rules.
  A classifier name that no longer
  exists fails the test, and so does a fourth one.
- `__del__` bodies are skipped: Python discards exceptions raised in a finalizer, so a clause
  there changes nothing.
- Seeded bypasses, each a finding: an `isinstance` check before `raise` inside
  `except Exception`; `except (Exception, MemoryError): return None`; `except MemoryError:
  return None` outside the classifiers; the clause after the broad handler; `except
  ArrowMemoryError: raise` ahead of `except Exception` (Arrow's subclass only); a
  `reraise_memory(exc)` call alone; `except BaseException: cleanup()` followed by
  `if flag: raise`; a bare `except:`; `except pa.lib.ArrowException`; the classifier shape copied
  into a function that is not registered; `except Exception: if cond: return None` then a final
  `raise`; `except Exception as exc: if cond: raise Other(...) from exc` then a final `raise`;
  `with contextlib.suppress(Exception):`; `with suppress(MemoryError):`; `return` inside a
  `finally`; a post-run result build moved inside the resident run handler; a second converting
  arm in a registered classifier; `break` inside a `finally` in a loop. Accepted seeds: the clause before `except Exception`;
  `except BaseException: cleanup(); raise`; `except (OSError, ValueError): pass`.
- Known limit, recorded and not chased (development-loop "guard tests prove the realistic case"):
  an exception class bound to another name (`Broad = Exception`) is not resolved.

**Mutations, run on the final head and recorded.** G14 as before. G15: delete the adapter's
memory clause; A16's direct cases and both routes go red. G16: on the resident route, drop
`enter_publishing()` before `publish_resident`; A17 resident goes red (NOT_PUBLISHED reserve).
G16b: call `_run_in_process` outside `memory_boundary`; A17 resident goes red (raw). G17: build the
reserves in `enter_readback` instead of the constructor; A18 (i) goes red. G18 and G19 as above.
G20: make `settle` return its argument unchanged; A16 goes red on both routes. G21: delete the
vault decoder's clause; the A15 vault case goes red, and so does the guard. G22: delete the
clause at `fileaccess/_errors.py:206`; A21 (ii) and the guard go red. Also run the context-only
mutation with all clauses intact: move `_resurface` back inside the guard handler. A21(ii)
must fail on the chain even though it still receives the correct exception type.

Existing suites that must stay green: `tests/unit/execution/test_isolated_run.py`,
`test_isolated_oom_classification.py`, `tests/unit/execution/publication/` (route outcome matrix,
marker corpus), `tests/integration/test_f29_isolation.py`, `tests/unit/execution/test_resident_fit*.py`,
`tests/unit/test_vault*.py`, the transactional-sink and delivery-stage publication tests, and the reason-adapter tests.

## Choke points

| Choke point | Where | Callers | Guard mutation |
|---|---|---|---|
| The one ceiling comparison | `resident_fit_verdict`, reached through new `check_readback(held, pending, *, kill_ceiling_bytes: int \| None) -> ResidentFit \| None` in `execution/pipeline/_resident_fit.py`, exported from `execution/pipeline/__init__.py` | `check_pre_read`, `check_pre_transform` (existing), `_isolated_commit.collect` (new) | G4 |
| The one bound formula | `lower_bound_bytes`, `lazy_spec`, `resident_spec` (`_resident_bytes.py:50`, `:133`, `:173`) | the same callers | G2, G10 |
| The one kill-ceiling source | Rename `_kill_ceiling` at `_resident_fit.py:219` to `kill_ceiling` and export it directly. It calls `out_of_core.detect_effective_memory_bytes` (`_budget.py:332`). | the same callers | G5 |
| The one isolated readback | `collect` and `_read_staged` (`_isolated_commit.py:205`, `:231`); every readback of a child's stage goes through it, for the probe, the governor and direct callers | `_result_from_envelope` (`_isolated_run.py:573`) | G1, G8 |
| Memory result through final cleanup | `memory_boundary(attempt, body)` in `_isolated_reason.py`, the only handler that turns a `MemoryError` into a result; `Attempt.settle` normalizes a memory-coded result by window | both branches of `run_pipeline_isolated` | G14, G16, G16b, G20 |
| Memory transparency of inner handlers | the exact `except MemoryError: raise` clause, checked by `tests/sentry/defects/memory_boundary/test_memory_errors_reach_the_boundary.py` over a scope A19 checks against a trace | every handler in the window | seeded bypasses, G18, G21 |
| Memory during classification | `reason_from_exception`'s one clause returns the pre-built `_OUT_OF_MEMORY` | every adapter caller | G15 |
| The capacity message | new `capacity_message(code, *, needed_bytes, kill_ceiling_bytes, remedy)` in `execution/_errors.py`. `nonfk_full_frame_capacity_error` (`src/decoy_engine/execution/_errors.py:87`) passes exactly "Run on a machine with more memory, or reduce the table's rows or columns." The formatter appends one space and the whole `remedy` sentence verbatim. Look up the summary in the supplied reason's namespace. The readback passes "Run on a machine with more memory, or write fewer or smaller output tables." | both refusals | G6 and class 9 |
| The refusal result | new `readback_refused(...)` in `_isolated_reason.py`, beside `envelope_failure` (`:68`) and `commit_reason` (`:101`) | `_result_from_envelope` | G7 |
| The memory predicate | `is_memory_failure` (already shared by the worker and `in_process_failure`) | `collect` (new) | G9 |
| Capacity code list | `CAPACITY_REASON_CODES` (`errors.py:511`); the CLI derives exit 5 from it | registry walk test | G11 |

## Established solutions

Searches run (online): Spark configuration docs and SPARK-3466 for `spark.driver.maxResultSize`;
the Databricks knowledge base article on the maxResultSize failure; Ray object spilling docs;
DuckDB memory management docs (already cited in `out_of_core/_budget.py:1-16`); PostgreSQL
`temp_file_limit` docs; Linux cgroup v2 `memory.max` docs; the Parquet format metadata spec
(`RowGroup.total_byte_size`); `pyarrow/error.pxi` for the `ArrowMemoryError` class tree.
Memory boundary search (2026-11-27): JLS and SEI CERT on `OutOfMemoryError`, Microsoft Learn on
corrupted-state exceptions and CA2153, PEP 669 and the `sys.monitoring` docs.
Codebase: `detect_effective_memory_bytes`, `check_pre_read`, `lower_bound_bytes`,
`ArrowMemoryError`, consumers of `IsolatedRunResult.outputs` (probe, governor, platform), and the
F25 scratch plan (`docs/plans/2026-10-29-f25-protected-scratch-quotas-orphan.md`, rows T11, T12).

| Option | What it gives | Decision |
|---|---|---|
| Spark `spark.driver.maxResultSize` (default 1g; SPARK-3466, <https://issues.apache.org/jira/browse/SPARK-3466>; Databricks KB <https://kb.databricks.com/jobs/job-fails-maxresultsize-exception.html>). An action whose results exceed the limit is aborted, because `collect` can OOM the driver | the same problem (worker results collected into the driver) answered by a refusal | followed for the shape: refuse at the driver before the data arrives. Not followed for the fixed default: a 1 GiB default would refuse 1.0 runs that work, against row 58b |
| Spark guidance to write results to storage instead of `collect` (same KB article) | the result never enters driver memory | the answer behind Q2; changes the `outputs` contract; V2-LOG |
| Ray object spilling; DuckDB `memory_limit` with `temp_directory` | spill to disk instead of failing | not applicable to D2: the data is already on disk. Rerouting the child out of core does not change output size |
| PostgreSQL `temp_file_limit` | coded error when a query would pass a resource limit | same refusal pattern, for disk; disk stays with row 58b |
| cgroup v2 `memory.max`, host RAM as fallback | the number the kernel OOM-kills against | used, through the existing `detect_effective_memory_bytes` |
| Parquet `RowGroup.total_byte_size` as the estimate | a closer size for string columns | not used to refuse: it is not a floor on decoded Arrow bytes (dictionary columns read back as dictionaries can be smaller). V2-LOG as a tighter string floor |
| `pyarrow/error.pxi`: `class ArrowMemoryError(MemoryError, ArrowException)` | why the current `except` misfiles memory failures | the memory arm is ordered before the Arrow arm |
| Java `OutOfMemoryError extends VirtualMachineError extends Error`, outside `Exception` (JLS 11.1.1; SEI CERT ERR08-J and ERR53-J) | `catch (Exception e)` never sees an out-of-memory condition; only a deliberate top-level handler does | followed: Python puts `MemoryError` under `Exception`, so the exact `except MemoryError: raise` clause gives each broad handler the Java hierarchy's effect, and `memory_boundary` is the one deliberate top-level handler |
| .NET 4+ corrupted-state exceptions are not delivered to `catch` blocks; analyzer CA2153 flags handlers that catch them (Microsoft Learn, `HandleProcessCorruptedStateExceptionsAttribute`, CA2153) | a runtime rule plus a static rule against swallowing process-state failures | followed for the static half: an AST sentry over the window's modules |
| PEP 669 `sys.monitoring` `RAISE` and `EXCEPTION_HANDLED` (Python 3.12+) | observe every raised or handled exception without touching handlers | rejected for runtime use: the engine supports 3.10 to 3.12, and `sys.settrace` on older versions takes the coverage slot. `sys.setprofile` is used only in A19 to measure the guard's scope |
| In-repo `_resident_fit.check_pre_read` (engine #777): footer floor against the kill ceiling before a lazy source is read whole | the exact rule this slice needs, already reviewed | reused: same formula, same ceiling, same verdict ladder. No custom estimator is written |

## Enumerations

### Exit paths

- `_names_ok` refuses the envelope names: `failed_receipt`, transaction aborted (`src/decoy_engine/execution/_isolated_commit.py:216`).
- `_admit` refuses the stage or raises `OSError`: `failed_receipt` (`src/decoy_engine/execution/_isolated_commit.py:187`, `:218`).
- New: `check_readback` refuses before a decode: `ReadbackRefused`, tables dropped, transaction aborted.
- New: memory failure during a decode (incl. ENOMEM and marker-matched text): `ReadbackMemoryFailure`, process-out-of-memory result, transaction aborted.
- `parquet_file` or `read_table` raises an Arrow or OS error: `failed_receipt` (unchanged, `:218`).
- Through result preparation before the flag (window `PRE_CALL`), a memory fault returns the NOT_PUBLISHED reserve through `memory_boundary`. Abort any open stage. Scratch-only runs take this path through return. A real `MemoryError` in the readback now takes this path too; `ReadbackMemoryFailure` remains for ENOMEM, marker text and a memory-caused interrupt.
- `enter_publishing()` immediately before calling `publish_unit`. A raised MemoryError there, including in measurement and replay verification, or later while building the result or unwinding, returns UNKNOWN. A memory-coded result built after it (the adapter's clause) is replaced by UNKNOWN in `settle`.
- A memory error while the `Attempt` constructor builds the reserves raises before staging or spawn.
- With an ordinary receipt, preserve existing handling. Build the completed result only after a committed receipt returns.
- Remove scratch-only output in the envelope finalizer. Inside the outer guard, attempt transaction abort and always close scratch in its nested finally.

### Routes

- Windows: ceiling detection fails (`src/decoy_engine/execution/out_of_core/_budget.py:195-215`), so the cap is inert on every route there (A5 path).
- Isolated subprocess, child on any route (full frame, out of core, sequential, auto-chunk lane, multi-table split), resident or streamed outputs: the readback runs and the cap applies (`src/decoy_engine/execution/_isolated_worker.py:160`).
- Probe (`src/decoy_engine/execution/_probe.py:283`): forced full frame on a downscaled job; the cap applies; a refusal is an inconclusive probe.
- Governor (`src/decoy_engine/execution/_governor.py:381`): every rung; a refusal ends the ladder.
- In-process fallback, `isolate=False` and re-entry (`src/decoy_engine/execution/_isolated_run.py:246`): no readback; outputs are already in memory. The route now runs under `memory_boundary` with its own reserves: `PRE_CALL` from `run_pipeline`'s return, `PUBLISHING` from immediately before `publish_resident` (A16, A17, A18).
- Other `publish_unit` callers (`ParquetTransactionalSink`, `DeliveryStage`): no boundary of their own; an `ArrowMemoryError` in measurement or vault decoding is raised as a bare `MemoryError` already is on `main` (A20).

### FK shapes

N/A: the readback reads each staged table on its own. FK jobs stage tables the same way, and no
relationship logic runs in the driver.

### Fields

`IsolatedRunResult` (`src/decoy_engine/execution/_isolated_common.py:346`) on a refusal:

- `outcome` `"crashed"`; `reason` the new code (memory arm: `process_out_of_memory`).
- `error` the fixed capacity text; `outputs` `None`; `quality_metrics` and `table_kinds` `{}`.
- `peak_rss_mb` the child's reported peak; `returncode` 0; `signal_number` `None`; `isolated` `True`.
- `committed_output_dir` `None`; `row_errors` `()`; `publication_receipt` `failed_receipt` with `output_dir`, else `None`.
- Both memory reserves retain the last complete `extra["readback"]` snapshot. UNKNOWN carries no receipt or committed path. The caller has no reliable visibility or durability report.

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
| 3 | State machine and concurrency | One `Window` per attempt on both routes (`BEFORE`, `PRE_CALL`, `PUBLISHING`); reserves exist before the first window opens; `memory_boundary` reads the window through cleanup | A14 to A18 on both routes, absent and visible targets | G14, G16, G17, G20 |
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
| 3 no exception context | refusal built outside any `except`; memory result from fixed text; A13 checks the refusal and A21(ii) checks the strict guard rebuild |
| 4 versioned read models | n/a: no persisted format |
| 5 normalized guard scanners | the memory sentry and A19 share normalized handler, suppress and finally checks with alias seeds |
| 6 no private-module imports | `_isolated_commit` imports `check_readback`, `lazy_spec`, `resident_spec` from `decoy_engine.execution.pipeline` |
| 7 no hidden CI failures | A12 Linux skip states its reason; the gate records a Linux pass on the final head |
| 8 one trust class per entry point | n/a: one trust class (the child's stage) |
| 9 mutations on the final head | G1 to G12, G14 to G22 (with G16b), the guard's seeded bypasses, the A21(ii) context-only mutation and the class 9 one-word mutation rerun on the final head and recorded |
| 10 allowlisted helpers are still checked | no new file-access registry row; the readback stays on the capability path |
| 11 no raised caps | no module-size ceiling raised and no baseline row added; every touched module stays at or under 600 lines (Placement) |

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
- CHANGELOG line: “On the isolated route, a memory error once publication may have started reports an unknown publication state. Rerun with the same operation id to confirm.”
- In `docs/publication.md`, explain UNKNOWN in the isolated result's reason context, the missing receipt on this path, and how to confirm with the same request and destination. Callers needing confirmation should supply and retain their operation id from the first attempt. Keep the existing publication exports, receipt outcomes and v1 descriptor.

## Placement and sizes

| Path | Change | CODEMAP line | Beside | Lines now | Expected |
|---|---|---|---|---|---|
| `src/decoy_engine/execution/_isolated_commit.py` | `enter_readback` and `enter_publishing` calls; the clause in `collect` and `_typed_error`; drop `reraise_memory` | `CODEMAP.md:271` | `_isolated_run.py` | 574 on c2b81ef1f | at most 580 |
| `src/decoy_engine/execution/_isolated_run.py` | both branches through `memory_boundary`; the old guard moves out; `failed_receipt_for` after `begin_publication`; resident window entries | `CODEMAP.md:271` | `_isolated_commit.py` | 575 on c2b81ef1f | at most 580 |
| `src/decoy_engine/execution/_isolated_reason.py` | `Window`, `Attempt.isolated()` and `.resident()`, `enter_readback`, `enter_publishing`, `settle`, `memory_boundary`; the builder, renamed `_reserved_result`, takes `isolated`, `returncode` and the operation; module docstring rewritten | `CODEMAP.md:271` | `_isolated_common.py` | 264 on c2b81ef1f | about 330 |
| `src/decoy_engine/reason_adapter.py` | `_OUT_OF_MEMORY`, the classifier clause, `_lookup_captured` and `known.with_context` inside the `try`, the transparent clause at four inner handlers | `CODEMAP.md` Foundation row | `reasons/` | 580 on c2b81ef1f | at most 600; shorten docstring prose if needed, no census row |
| `src/decoy_engine/publication/_publish.py` | `reraise_memory` call becomes the clause; scope the resident stage with its existing txn context; the module docstring's non-receipt exits (`:20-27`) add memory errors (A20) | `CODEMAP.md` Publication row | `_members.py` | 476 | about 478 |
| `src/decoy_engine/vault/_format.py` | `reraise_memory` call becomes the clause | `CODEMAP.md` Token vault row | `_writer.py` | 307 | 308 |
| `src/decoy_engine/fileaccess/_errors.py` | remove `reraise_memory` (added on this branch, never released, about -11); the clause at `:206`, `:216`, `:225`, `:309` (+8), move the guarded rebuild outside its handler, and document that `classified_failure` may raise `MemoryError` during rebuild | `CODEMAP.md` file access row | `is_memory_failure` | 342 | about 345 |
| `src/decoy_engine/fileaccess/_read.py` | update the `keeps_class` docstring: a strict text rebuild may raise `MemoryError` | `CODEMAP.md` file access row | `_errors.py` | 95 | about 96 |
| `src/decoy_engine/fileaccess/__init__.py` | remove the `reraise_memory` export | `CODEMAP.md` file access row | n/a | 244 | 242 |
| `fileaccess/_local_chain.py`, `fileaccess/_output.py`, `determinism/_derive.py`, `determinism/_hkdf.py`, `internal/crypto.py` | none: in `SCOPE` from the A19 trace, the existing memory-catching handlers already pass shape 2 | their own rows | n/a | 131, 489, 430, 92, 72 | unchanged |
| any further file a later A19 run adds | the clause at each traced handler | their own rows | n/a | n/a | at most 2 lines per handler. If a later run adds more than three source files, or a handler where the clause would change a non-memory verdict, stop and report |
| `src/decoy_engine/execution/_errors.py` | `capacity_message` | `CODEMAP.md:271` | `_isolated_reason.py` | 140 | about 150 |
| `src/decoy_engine/execution/pipeline/_resident_fit.py` | `check_readback`, public `kill_ceiling` | `CODEMAP.md:271` | `_resident_bytes.py` | 470 | about 505 |
| `src/decoy_engine/execution/pipeline/__init__.py` | export both | `CODEMAP.md:271` | `_resident_fit.py` | 51 | 55 |
| `src/decoy_engine/reasons/decoy/_core.py` | register the identity and add it to `__all__` | `CODEMAP.md:288` | `ISOLATED_WORKER_OUT_OF_MEMORY` | 288 | about 296 |
| `src/decoy_engine/errors.py` | `CAPACITY_REASON_CODES` entry | `CODEMAP.md:262` | the `ISOLATED_WORKER_OUT_OF_MEMORY` entry | 599 | 600 |
| `changelog.d/g7-3-readback-cap.md` | CHANGELOG line for the registered reason and isolated UNKNOWN behavior, via the unreleased fragment | release notes | other fragments | existing fragment | a few lines |
| `docs/publication.md` | add same-id confirmation advice beside isolated publication. Condense adjacent prose to fit | existing publication guide | receipt table | 601 on abc5998fd | at most 600 |
| `tests/unit/execution/publication/_isolated_support.py` | ordered table-spec plant mode | existing shared publication test support | `test_isolated_parent_measures.py` | 136 | about 150 |
| `tests/unit/execution/test_resident_fit_decision.py` | pin the full-frame refusal before the refactor | existing resident-fit tests | `test_resident_fit_transitions.py` | 525 | about 540 |
| `tests/unit/reasons/test_capacity_reason_codes.py` | update A11's expected membership | existing registry tests | registry walk | 80 | 81 |
| `tests/unit/execution/publication/test_isolated_readback_cap.py` | existing A1 to A9, A12. Shorten the A9 docstring to describe its actual check, no readback pricing after publish. Retain every assertion | `CODEMAP.md:172` | `_isolated_support.py` | 601 on abc5998fd | at most 600. All new cases go in the next file |
| `tests/unit/execution/publication/test_isolated_commit_memory.py` | A14, A15 (on the branch); A9-style exact `MemoryError` readback case now expects the reserve | `CODEMAP.md:172` | `test_isolated_readback_cap.py` | 364 on c2b81ef1f | at most 380 |
| `tests/unit/execution/publication/test_memory_boundary_routes.py` (new) | A16 to A21; route-specific and direct cases as specified above. A19 imports `SCOPE` and the predicate from the sentry-private `_memory_scan` (one definition; the only import of a sentry helper from a unit test) | `CODEMAP.md:172` | `test_isolated_commit_memory.py` | 0 | about 380 |
| `tests/sentry/defects/memory_boundary/__init__.py` (new) | empty; `tests/sentry/defects/` already has 35 entries | `CODEMAP.md:298` | n/a | 0 | 0 |
| `tests/sentry/defects/memory_boundary/_memory_scan.py` (new) | `SCOPE`, the handler predicate, the three shapes, the `suppress` and `finally` checks, `CLASSIFIERS` | `CODEMAP.md:298` (recurring-defect class rules in `tests/sentry/defects/`) | `../_defect_scan.py` | 0 | about 140 |
| `tests/sentry/defects/memory_boundary/test_memory_errors_reach_the_boundary.py` (new) | the guard, the scope-glob check and its seeded bypasses | `CODEMAP.md:298` | `../test_exception_context.py` | 0 | about 160 |
| `tests/sentry/test_commit_path_memory_rule.py` | deleted; replaced by the two files above | n/a | n/a | 106 | 0 |
| `changelog.d/g7-3-readback-cap.md` | add: `ArrowMemoryError` during publication measurement or vault decoding is raised like any `MemoryError`, not reported as a failed receipt or a malformed segment; `isolate=False` returns the same UNKNOWN memory result; the reason adapter reports `process_out_of_memory` when classification runs out of memory | release notes | other fragments | existing | a few lines |
| `tests/unit/execution/pipeline/test_resident_floor_reality.py` (new) | A10 | existing sub-package `tests/unit/execution/pipeline/` | `test_lifecycle_inputs.py` | 0 | about 120 |
| `tests/unit/execution/test_isolated_safe_error.py` | A13 producers | `CODEMAP.md:271` | `test_isolated_run.py` | 418 | about 440 |

Test placement: no new file goes in the flat `tests/unit/execution/` directory (`CODEMAP.md:171`).
The readback cases go in `tests/unit/execution/publication/` rather than a new `isolated/`
sub-package: the readback is the step that admits and publishes the child's stage, that
directory already holds the isolated publication tests (`test_isolated_parent_measures.py`,
`test_isolated_marker_corpus.py`), and it has `install_fake_worker`, so no new sub-package or
CODEMAP row is needed. A10 tests the shared floor formula of `execution/pipeline/`, so it goes in
`tests/unit/execution/pipeline/`.

No new production module or production package: `execution/` is over its fan-out freeze (109 entries
against 104, `CODEMAP.md:271`), and every change fits an existing module under 600 lines.

## Slices

The cap, the reserves and A14 and A15 are built on `feat/f25-g7-3-readback-cap` at `c2b81ef1f`. The remaining slice replaces the per-site `reraise_memory` rule with the memory boundary: write A16 to A18 and A21 and run them red on `c2b81ef1f`; then `Attempt` windows and `memory_boundary` on both routes; the clause at every non-compliant handler in `SCOPE` (the A19 trace found them all: `collect`, `_typed_error`, `_judge_and_bind`, `_decode_rows`, the adapter's four, and `fileaccess/_errors.py`'s four); the adapter clause; the guard in `tests/sentry/defects/memory_boundary/` and A19 over the 13-entry `SCOPE`; A20 and the changelog lines. Run the acceptance suite and the final-head mutations in the recurring-defects table, including the A21 context-only mutation. Use T0 and T1 per commit and T2 at each gate. The registry change rides the next merge train for one full suite against the stored baseline. Expected size: 9 source files edited (`_isolated_commit.py`, `_isolated_run.py`, `_isolated_reason.py`, `reason_adapter.py`, `_publish.py`, `vault/_format.py`, `fileaccess/_errors.py`, `fileaccess/_read.py`, `fileaccess/__init__.py`), about 3 test files changed, four test files added (one an empty `__init__.py`), one deleted; new names `Window`, `memory_boundary`, `Attempt.isolated`, `Attempt.resident`, `enter_readback`, `enter_publishing`, `settle`, `_OUT_OF_MEMORY`; renamed `_readback_result` to `_reserved_result`; one name removed, `fileaccess.reraise_memory`. No new public API.

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
- If execution modules approach 600 lines, keep result construction with the existing reason builders and remove stale commentary. Check physical line counts and all existing ceilings.
- A4 and A7 start real children. Keep those jobs below 1,000 rows. A7 stops after one rung.
- The ceiling patch leaks into the child: it cannot (fresh interpreter), and A4 shows the child
  completes normally under the patched driver.
- A reviewer asks for the cap to also catch string-heavy overruns: that is outside the guarantee
  (non-goal 1, Q1); record it, do not widen the slice.

## V2-LOG

- Defer splitting publisher preparation from bind, exporting preparation, fileaccess decision slots and moving the local bind branch. The isolated flag is enough for V1.
- Defer using `commit_uncertain` for memory faults. Today a bare `MemoryError` in `_sync_bound` escapes fileaccess because it is outside the `OSError` handler. The isolated guard catches it.
- `OSError(ENOMEM)` and marker-text memory failures inside the shared publisher stay failed receipts; only `MemoryError` instances pass its handlers.
- A memory boundary for `ParquetTransactionalSink` and `DeliveryStage`, and the publication state the sink records for a memory error during a matching replay.
- A `KeyboardInterrupt` with a memory cause after the flag; memory errors in `BEFORE` on either route.
- The guard does not resolve an exception class bound to another name.
- An `OSError` from `pub.txn.abort()` in `_run_isolated`'s `finally` replaces an in-flight `MemoryError` (Dennis r1 L6).
- A frame-allocation failure on the `enter_readback` call leaves the window at `BEFORE` (L7).
- A second memory error in the reason adapter's `_record(UNEXPECTED_ERROR)` arm escapes, as on `main` (L1).
- A rebuild OOM in `keeps_class` or `classified_failure` called inside an active handler can retain the original data-bearing error as context. CLI `--verbose`, the `decoy ci` unsafe debug log, and platform `logger.exception` at `api/jobs/iteration.py:633` can render the chain. The strict guarded rebuild runs after its handler closes. Public result text stays value-free.
- Codex R6: a retry that reuses a caller `staging_dir` with resident input tables finds the earlier `s0000.parquet` during input staging (`_isolated_commit.py:246`), before output admission. Input staging into a reused caller root is outside this slice.
- Defer guaranteed completed results for verified replay and pre-built completed results per receipt. The old A14 bind, rename, fsync and replay transition tests belong to that stronger guarantee.
- The CPython emergency-object reserve and PostgreSQL durable-commit comparison described the deferred completed-result design. Neither can establish that a Python caller observed a bind.
- Existing ceiling accessors include `execution/pipeline/_resident_fit.py:219`,
  `generation/__init__.py:59` and the third copy, `generation/_bounds.py:545`
  (`detected_memory_bytes()`). Cross-package consolidation is a follow-up.

- Read back only on request: with `output_dir`, leave `outputs` unread or return lazy handles;
  removes D2 (Q2).
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
- The probe reads back outputs it never uses; skip the readback for the probe once the optional readback in Q2 exists.

## Owner choices for 1.0

Q1. Use the strict floor and the documented swap assumption. An estimate or fixed default can refuse runs that fit.
Q2. Refuse before publishing when the floor exceeds the ceiling. Optional readback and lazy handles change the completed outputs contract and stay in V2-LOG.
Q3. Detect the ceiling. A caller-set budget belongs with row 58b.
D-A20 and D-BEFORE (orchestrator, 2026-11-27): see the Memory boundary section. A20's behaviour change is accepted, and a raw `MemoryError` before the window stays as on `main`.

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
| V1 setup and result preparation could raise raw memory errors | The pre-call arm and A14 include the first readback allocation, target string and row errors. |
| V1 false NOT_PUBLISHED or raw memory error during publication, replay or cleanup | The per-attempt flag selects UNKNOWN through final cleanup. A14 checks both target states. G14 removes the outer guard. |
| DESIGN unnecessary shared publication and fileaccess changes | The isolated caller owns the flag. The proposed shared mechanisms are in V2-LOG. |
| Codex R5-1 vault decoder turns `ArrowMemoryError` into a mismatch | Section "Memory boundary" part 2: the clause, required by the guard; A15 |
| Codex R5-2 `_typed_error` swallows a `MemoryError` | Part 2 clause; part 3 and `settle` cover it even without the clause; A15 |
| Codex R5-3 setup fault leaves `staging_output/` | Unchanged fix; the cleanup `try` opens with `enter_readback` |
| Codex R6-1 memory error in `_classify` gives `unexpected_error`, NOT_PUBLISHED | Part 3 adapter clause plus `settle`; A16, G15, G20 |
| Codex R6-2 raw `ArrowMemoryError` on `isolate=False` | Part 1: the resident route under `memory_boundary` with its own reserves; publisher clause kept; A17, G16, G16b, A20 |
| Codex R6-3 first reserve fault escapes raw | Part 1: reserves built in the `Attempt` constructor before any side effect; A18, G17 |
| Codex R6 DESIGN guard accepts conditional calls and tuples, omits `reason_adapter.py` | Exact clause shape, seeded bypasses, `tests/sentry/defects/`, scope checked by the A19 trace; G18 |
| Planner, per-site `reraise_memory` rule | Removed; replaced by the clause, one boundary and one classifier |
| Dennis r1 H1 shape 2 accepts a conditional swallow before the final `raise` | Part 2 and the guard: every `raise` bare, no `return`, `break` or `continue` in the handler; two new seeds |
| Dennis r1 H2 `SCOPE` incomplete | A19 prototype run on both routes, six scenarios and the `publish_unit` fault (3.10 and 3.12). `SCOPE` is the 13 traced files; `fileaccess/_errors.py` gets four clauses with a per-handler effect table; five files join with no edit; Placement line deltas |
| Dennis r1 M1 A19 soundness | A19 rewritten: stop at `memory_boundary` return, src filter on entry frames, warm runs, `<module>` ignored, AST-span mapping, thread check, fault scenario, sentinels |
| Dennis r1 M2 `suppress` and `finally` exits | Part 2 and the guard: both are findings, with seeds; each `SCOPE` entry must match a file |
| Dennis r1 M3 A9, G9 and the read row contradict the design | Failure-modes row moved into the `PRE_CALL` row; A9 says which arm each variant takes; G9 kills ENOMEM and marker, G14 kills Arrow and bare |
| Dennis r1 M4 adapter clauses change behaviour outside the window | Part 3 states it for the 12 external call sites; A21 (i); "only adapter change" wording removed |
| Dennis r1 M5 sentry placement | `tests/sentry/defects/memory_boundary/` subpackage |
| Dennis r1 L1 to L10 | L1 residual and `known.with_context` inside the `try`; L2 "publication state" and `cleanup_state`; L3 `memory_boundary`, docstring, `_reserved_result`; L4 ENOMEM control in A17; L5 A16 armed after `enter_publishing`; L6, L7 residuals and V2-LOG; L8 `_publish.py` docstring in Placement; L9 Codex R6 input-staging item in V2-LOG; L10 Placement note on the `_memory_scan` import |
| Orchestrator decisions 2026-11-27 | D-A20 and D-BEFORE written in the Memory boundary section |


### Dennis round 2 and final plan self-review against `c2b81ef1f`

| Finding | Fix and verification required of the build |
|---|---|
| DESIGN · Dennis R2 medium · strict callers missing from the effect table | Part 2 follows both rebuild paths through exported `keeps_class` and `classified_failure`. Placement includes both docstrings. A21(ii) faults the constructors through each public caller. |
| V1 · Dennis R2 low · strict rebuild can acquire the original library context | Part 2 moves reconstruction outside the handler. A21(ii) checks identity, both chain slots and rendered canary. The remaining diagnostic surfaces are in V2-LOG. |
| V2-LOG · Dennis R2 low · errno rebuild description | The table and A21(ii) include disk-full and quota errors as well as ENOMEM. |
| V2-LOG · Dennis R2 · vault dependency | A19 requires PyNaCl and a replay sentinel on each route. |
| V1 · self-review · adapter OOM during pre-call refusal classification | `_isolated_commit.py:449–451,512` can classify a failed receipt before publication. Part 1 and A16 give the context-free adapter result the pre-call reserve while preserving A9's detailed readback result. |
| V1 · self-review · resident stage ownership gap | Faulting the resident publisher at `publish_unit` entry on the pin left a pending stage on disk. Part 2 and A17 use the existing transaction context across the callback and handoff, with stage and target assertions. |
| DESIGN · self-review · classifier exception too broad and adapter arm count unsatisfiable | The guard checks the adapter's ordered pair and restricts the resident exemption to the run-only try. A17 also faults resident scratch completion. A19 shares the guard's discovery predicate, including finally exits and import aliases, and exercises the applicable expanded trace cases. |
| DESIGN · self-review · A19 could start on a nested probe | A local run of the original trace recorded 140 files and counted pre-window sampler threads. A19 now keys start and stop to the outer attempt and keeps the thread assertion. |
| V2-LOG · self-review · ineffective or stale fault injections | A16 and A21 inject inside the real inner handlers. A16/A18 specify executable seams on the pin. A18 checks both refresh allocations and aligns the earlier A14 receipt test with D-BEFORE. |

The existing commit-memory and file-access policy tests passed on the pinned source (83 tests,
Python 3.10.20). A static walk of all 25 source files matched by the 13 scope entries confirmed
the listed broad-handler sites. The resident handoff and pre-call adapter probes exercised the
pinned code directly, with the proposed adapter fallback supplied for the latter. An in-memory
probe of the revised strict guard preserved typed Arrow exception identity and kept the original
out of both chain slots for text, ENOMEM, ENOSPC and EDQUOT rebuild faults. Rerunning the
26-scenario prototype on 3.10 with route-specific entry and a public-return stop recovered the
same 45 files and handler sites as the supplied reports, all four sentinels and zero in-window
thread starts. The number of scenarios observing local abort differed (19 versus 21). A19
checks handler coverage and scenario outcomes independently of that incidental count.

**Plan verdict: GO.** The code and recorded Python 3.10/3.12 traces support the revised build
and acceptance instructions. Implementation, acceptance runs and final-head mutations remain
build gates. D-A20 and D-BEFORE stand. No size ceiling increase or baseline addition is required.
