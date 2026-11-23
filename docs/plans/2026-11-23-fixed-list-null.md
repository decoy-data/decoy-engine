Status: plan

# FIXED-LIST-NULL: an in-memory source that Parquet cannot store no longer breaks the plain run

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 1. Roadmap row: FIXED-LIST-NULL (CLI `docs/roadmap/groups/run.md`, 1.0, function break). Anchors are in this repository (decoy-engine) at `origin/main` `26091c834` unless marked `#770:` (engine PR #770, UF-DOMAIN S1, head `3ad186c50`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (internal payload only, no external consumer), `catalogs/recurring-defects.md` (11 classes). Engine `CLAUDE.md` file-size rule.

Risk: R2. The change is small, but it changes the payload format of the isolated child (internal serialization) and what the routing probe can measure. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes (serialization trigger).

## 1. Frame

### 1.1 Symptom

`run_pipeline(config, sources={"t": table})` with an in-memory `pa.Table` whose only column is a passthrough `fixed_size_list` with a null cell in a middle row raises a raw `pyarrow.lib.ArrowNotImplementedError: Lists with non-zero length null components are not supported`. No coded reason, no output. The CLI cannot reach the case: it reads files, and a Parquet file cannot hold this cell (Dennis, review of engine #754). The Python API can.

### 1.2 What the probes showed

All probes ran on the Mac and the Dell through `vm-run` against `origin/main` `26091c834` and against #770 head `3ad186c50`. Both heads gave the same result for every case, so #770 does not change this path. Probe scripts stay in the author's scratch, not in the repo.

Probe A, shapes (fixed-size list of `int32[2]`, `int64[1]`, `string[2]`; null positions; `auto_chunk` on and off; the profile file is the same table with the null replaced, because the profiler reads the declared file):

| Shape | Null at row 1 of 3 | Null at row 0 | All null |
|---|---|---|---|
| only the list column, passthrough | FAIL, `ArrowNotImplementedError` | OK | OK |
| list column plus a passthrough string | OK | OK | OK |
| list column plus a redacted string | OK | OK | OK |

The failing trace, the same for every failing cell:

```
_pipeline_context.py:514 decide_route
_pipeline_routing_signals.py:560 resolve_execution_route
_transforms_admission.py:330 admission_signals
_pipeline_routing_signals.py:476 resolve_probe_recovery
_probe.py:415 probe_peak_bytes
_probe.py:283 _run_one_probe
_isolated_run.py:267 run_pipeline_isolated
_isolated_run.py:410 _write_payload
_isolated_commit.py:165 stage_sources
fileaccess/adapters/arrow.py:101 write_table  (pq.write_table)
```

Probe B, where the null sits. `pq.write_table` of `fixed_size_list<int32>[2]` with one null cell: null at row 0 writes, null at the last row writes, all nulls writes, null in a middle row raises. A head slice that ends before the middle null writes. The failure depends on the data, not only on the type.

Probe C, why the two-column shapes pass. A spy on `stage_sources` showed the stage write fails for them too. Two callers run the probe:

- `pipeline/_resident_fit.py:443-457` (`_run_probe`) catches every exception, logs `resident fit probe unavailable` and goes on without evidence. The failure is silent.
- `_transforms_admission.py:279` and `:330` (through `_pipeline_routing_signals.py:476`) do not catch. They raise. The only-list shape reaches this probe because its static estimate is not priceable (`fixed_size_list` has no resident-size model), so the probe is asked to recover it.

Probe D, the whole type catalogue (`tests/native/_rev9_type_catalogue.py`, each type with and without a null) as the only passthrough column of an in-memory source, plain `run_pipeline`:

| Result | Types |
|---|---|
| FAIL at `stage_sources` (Parquet cannot store the type or this cell) | `fixed_size_list` with a null, `fixed_shape_tensor` with a null, `dense_union`, `sparse_union`, `list_view`, `large_list_view`, `month_day_nano_interval`, `ree_string`, `ree_string_view`, `dictionary_string_view` |
| Staged, but Parquet changes the type the child reads | `date64` (to `date32`), `time32[s]` (to `time32[ms]`), `timestamp[s]` and `timestamp[s, tz]` (to `ms`), `dictionary<int64>` (to plain `int64`), `dictionary<large_string>` (to `dictionary<string, int32>`), `dictionary<float16>` (to `halffloat`) |
| Fails before staging, other causes (not this row) | `time64[ns]` (profile reader), `fixed_shape_tensor` without null (profile walk `TypeError`), `dictionary_float16` (pandas conversion) |
| Arrow IPC round trip | exact for every catalogue type, with and without a null |

Probe E, nested. A struct with a `fixed_size_list` field that has a null cell: `pq.write_table` does not raise, but reading the file back raises `ArrowInvalid: Expected all lists to be of size=2 but index 1 had size=0`. On the handoff this is a child that cannot read its input.

Probe F, a throwaway prototype (reverted): `stage_sources` writes Arrow IPC and the worker reads it. Every failing cell of probe A passed, with the exact source type and values. The probe child then failed when it staged its own output as Parquet, so the probe came back inconclusive (`outcome='crashed'`) and the parent run went on. `run_pipeline_isolated` on the same table returned an `IsolatedRunResult` with outcome `crashed`, reason `unexpected_error` at the output write, instead of raising in the parent.

### 1.3 Impact under the V1 bar

A function break on the Python API: a valid Arrow table fails a plain run with an uncoded pyarrow error. The class is wider than the row: ten catalogue types fail the same way (probe D), and the resident-fit probe loses its evidence for them without a word. Not a leak: the error text holds no cell value.

## 2. Root cause with evidence

The isolated child gets its sources as Parquet files. `stage_sources` (`src/decoy_engine/execution/_isolated_commit.py:158-167`) writes every caller table with `arrow_adapter.write_table` (`pq.write_table`, `src/decoy_engine/fileaccess/adapters/arrow.py:98-101`), and the worker wraps each path in a lazy Parquet handle (`src/decoy_engine/execution/_isolated_worker.py:76-113`, `LazySource(Path(path))` at `:109`). Parquet cannot hold every Arrow table: some types not at all, a fixed-size list not when a middle cell is null, and some types only with a changed type. The engine hands the child a format that is narrower than its input.

The routing probe is the caller that sends a caller's in-memory tables through this handoff (`_probe.py:250-300`, `run_isolated(...)` at `:283`, on head slices from `_probe_scale.py:215-236`). It runs during route choice, before any route executes. So a plain run of a table the in-process routes handle well fails in routing.

The two probe callers treat the failure differently (probe C). That asymmetry is a symptom, not the cause: with an exact handoff, neither caller sees this failure.

Not the cause:

- The nested rebuild (`_fk_keys.py:484-562`, engine #754) and `is_nested_type`: the failing trace never reaches them, and the two-column shapes go through the rebuild and come back exact.
- #770 moves the rebuild to `#770:src/decoy_engine/execution/pipeline/_source_types.py` and carries untouched columns from the source. It does not touch `_isolated_commit.py`, `_isolated_worker.py`, `_isolated_run.py` or `_probe*.py` (its diff stat), and probe A gave the same result on its head. This plan anchors on `origin/main`; it rebases over #770 with no overlap.

## 3. Established solutions considered

- Search run: Apache Arrow documentation on Parquet type support and on the IPC file format (Feather V2); pyarrow `ipc.new_file` and `ipc.open_file`; in-repo `git grep ipc_new_file`. Found: the Arrow IPC file format is the lossless on-disk form of an Arrow table and carries every Arrow type; Parquet has its own type system with documented gaps and conversions. Probe D confirms an exact IPC round trip for the whole catalogue on pyarrow 24.
- In this repository: the no-sink chunked collector already spills its hold-back as IPC through the file-access adapter (`src/decoy_engine/execution/_chunked_output_sink.py:472`, `arrow_adapter.ipc_new_file`), and the adapter has `ipc_new_file` and `ipc_read_file`. The fix reuses them. No new dependency.
- Rejected: catch the staging error in the probe and return inconclusive. It hides the class, keeps the child on drifted types (probe D, second row), and leaves `run_pipeline_isolated` raising.
- Rejected: stage every source as IPC. The child would lose the lazy Parquet handle for every isolated job. TB-1 and B6b made the child lazy on purpose (the memory double-count recorded in `_isolated_worker.py:79-97`), and `tests/unit/execution/test_isolated_worker_streaming.py` pins it.
- Rejected: try Parquet and fall back to IPC on error. Probe E shows Parquet can write a nested file it cannot read, so "the write succeeded" does not prove the handoff is exact.

The only custom code is the allowlist predicate, because no library answers "does Parquet round-trip this Arrow type exactly". It is a closed set pinned by a catalogue test.

## 4. Fix design

### 4.1 Guarantee

1. The isolated child receives each source table exactly: the table the child loads equals the caller's table in schema and values, for every type in the type catalogue and for a fixed-size list at any depth with null cells anywhere.
2. A table whose every type, at every depth, is in a closed Parquet-exact set is still handed over as Parquet and still loads lazily in the child (unchanged). Every other table is handed over as an Arrow IPC file and loads eagerly in the child.
3. A plain `run_pipeline` of an in-memory source with a passthrough fixed-size list with null cells completes and returns that column with the source type and values, with `auto_chunk` on or off and with `execution_mode="full_frame"`.
4. The routing probe never raises because of the source handoff. When the child cannot finish (for example, it cannot write a fixed-size list null cell to its Parquet output stage), the probe is inconclusive and routing goes on as it does with no probe evidence.
5. Output bytes do not change. No reason code is added or changed.

Non-goals (recorded, not blockers):

- G-1. Parquet output of a fixed-size list with a null cell: `TransactionalSink`, the isolated child's output stage, the out-of-core stage (`out_of_core/_stage.py:90`) and CLI Parquet targets still fail on that cell, because the target format cannot hold it. After this plan `run_pipeline_isolated` reports it as outcome `crashed`, reason `unexpected_error`, instead of raising in the parent. A coded "target format cannot hold this cell" reason is a follow-up row.
- G-2. A Parquet source file with a struct field of fixed-size list and a null cell (probe E): pyarrow writes it and cannot read it back, and the profiler raises a raw `ArrowInvalid`. A coded read error is a follow-up row.
- G-3. The probe D failures that happen before staging (`time64[ns]`, `fixed_shape_tensor` without null, `dictionary_float16`): known issues listed in `tests/integration/test_byte_estimate_arrow_types_e2e.py:305-321`; not this row.
- G-4. Whether the union, view, run-end-encoded and interval types then run end to end. This plan makes their handoff exact; the builder records their plain-run result in the report. A new failure past staging is a follow-up, not a blocker.
- G-5. The catch-all in `_resident_fit._run_probe` stays. It covers child start failures outside this scope.

### 4.2 Design

- `src/decoy_engine/execution/_isolated_commit.py`: one private predicate, `_parquet_stages_exactly(t: pa.DataType) -> bool`. True for a closed set of leaf types and for `list`, `large_list`, `struct` and `map` whose children are all true. The leaf set is the catalogue types that probe D found exact: `null`, `bool`, signed and unsigned integers, `float16`, `float32`, `float64`, the decimal types, `string`, `large_string`, `string_view`, `binary`, `large_binary`, `binary_view`, `fixed_size_binary`, `date32`, `time32[ms]`, `time64[us]`, `time64[ns]`, `timestamp` with unit `ms`, `us` or `ns` (any zone), `duration`, and `dictionary` whose value type is `string` or `binary` with `int32` indices. Everything else is false, including every `fixed_size_list` (the null limit depends on the data), every extension type, `date64`, `time32[s]` and `timestamp[s]`. A type the set does not name is false, so a new Arrow type goes to IPC until a test proves Parquet holds it. The builder confirms each leaf against AT-F3 and drops any leaf that does not round-trip.
- `stage_sources` writes a table as `s{index:04d}.parquet` with `arrow_adapter.write_table` when every field passes the predicate, else as `s{index:04d}.arrow` with `arrow_adapter.ipc_new_file`. The manifest value changes from a path string to `{"path": str, "format": "parquet" | "ipc"}`.
- `src/decoy_engine/execution/_isolated_worker.py`, `_load_sources`: a `parquet` entry loads as today (`LazySource` when `lazy`, else `pq.read_table`). An `ipc` entry loads eagerly through the file-access adapter (an IPC read by path, added to `fileaccess/adapters/arrow.py` beside `read_table` if no existing function fits). Any other format value, a missing `format` or a non-dict entry raises before any file is read (recurring-defects class 4: a checked token, not free text).
- Sentries: `tests/sentry/file_access_registry.toml` gets a row for the new IPC read in `_load_sources` (rule and reason as the Parquet row at `:136-143`). `tests/sentry/baselines/parquet-intermediate-writers.json` keeps `stage_sources` at `max: 1`. If an IPC writer registry exists, `stage_sources` gets a row with the same reason. No cap is raised (class 11).
- Known-issue list: `_REFUSED_WITH_ESTIMATE_OFF` (`tests/integration/test_byte_estimate_arrow_types_e2e.py:305-321`) loses each entry that now passes, so the list stays true. The builder reports which.
- Tests that call `_load_sources` with a bare string manifest (`tests/unit/execution/test_isolated_worker_streaming.py:107`, `:127`; `tests/unit/execution/test_b6b_modes.py:431-433`) move to the new entry shape.
- Size: about 45 source lines in `_isolated_commit.py` (307 lines) and `_isolated_worker.py` (233 lines), plus at most 10 in `fileaccess/adapters/arrow.py`. No new public name. No new reason code. No new file in `src/`.

### 4.3 Choke point

The source handoff to the isolated child has one writer, `stage_sources` (already held to one Parquet write by `parquet-intermediate-writers`), and one reader, `_load_sources` (`file_access_registry.toml`). The format rule lives only in `_parquet_stages_exactly`, called only by `stage_sources`. AT-F3 is the guard: it stages every catalogue type and the nested cases and checks what the worker loads. M-1 turns it red.

### 4.4 Placement

No new file in `src/`. Tests go into existing files:

| Test | File | Sits beside |
|---|---|---|
| AT-F1, AT-F1g, AT-F2 | `tests/native/test_unconfigured_passthrough_types.py` | the #754 resident nested cases |
| AT-F3, AT-F4, AT-F5 | `tests/unit/execution/test_isolated_worker_streaming.py` | the TB-1 `_load_sources` cases |
| AT-F6 | `tests/unit/execution/test_isolated_safe_error.py` | isolated outcome and value-free error cases |
| AT-F7 | `tests/unit/execution/` probe tests beside the existing `probe_peak_bytes` cases | |

Changelog: engine fragment `changelog.d/fixed-list-null.md`.

### 4.5 Design notes

None: no new structure. One private predicate and one field on an existing internal payload. The rule "what Parquet holds exactly" is in one place. The parent and the child are always the same engine version, so the payload change needs no compatibility reader (api-and-compatibility: no consumer outside the engine process pair); the worker still refuses an unknown token.

## 5. Behavior and failure modes

| Input | Before | After |
|---|---|---|
| In-memory table, only column a passthrough fixed-size list, null in a middle row | raw `ArrowNotImplementedError` in routing | runs; column exact; probe inconclusive (G-1) |
| Same, with other columns | runs; resident-fit probe silently skipped | runs; probe child gets the exact table; probe inconclusive when the child output stage cannot hold the cell |
| In-memory table with a union, view, run-end-encoded or interval column | raw `ArrowNotImplementedError` in routing | handoff exact; later stages as they are (G-4) |
| In-memory table with `date64`, `time32[s]`, `timestamp[s]` | probe child runs on a changed type | probe child runs on the exact type (IPC, eager) |
| In-memory table of Parquet-exact types only | Parquet handoff, lazy child | unchanged |
| `run_pipeline_isolated` with a fixed-size list null cell | raw `ArrowNotImplementedError` in the parent | `IsolatedRunResult`, outcome `crashed`, reason `unexpected_error` (G-1) |
| Manifest entry with an unknown or missing format | n/a | the child raises before reading; the parent classifies the child failure as today |
| Disk full or permission error while staging | raised from `stage_sources` | unchanged |

Memory: an IPC handoff loads eagerly in the child. It applies only to tables Parquet cannot hold exactly, which fail or drift today, so no working lazy path becomes eager. Route choice can change for in-memory tables with the drifting types, because the probe now measures the exact table. Outputs do not change bytes.

## 6. Acceptance tests (red-first)

Fixture L: `pa.table({"x": pa.array([[0, 0], None, [2, 2]], pa.list_(pa.int32(), 2))})`, passthrough, with a profile file that holds the same column with the null replaced by `[0, 0]` (the pattern of `tests/integration/test_byte_estimate_arrow_types_e2e.py:324-332`). Every run asserts the output column's type and values equal the source column's.

- AT-F1. Plain `run_pipeline`, fixture L, `auto_chunk` False and True; also `int64[1]` and `string[2]` value types; also a 5-row table with nulls at rows 1 and 3. Red on base: `ArrowNotImplementedError` from `stage_sources`.
- AT-F1g. Green on base on purpose (regression pins): null at row 0, null at the last row, all null; and fixture L's column beside a redacted string column.
- AT-F2. Fixture L with `execution_mode="full_frame"`. Red on base, same trace.
- AT-F3. Staging round trip: for every `CATALOGUE` type with and without a null, and for `struct<f: fixed_size_list<int64>[2]>`, `list<fixed_size_list<int64>[2]>` and `map<string, fixed_size_list<int64>[2]>` with a null fixed-size list cell in a middle row: `stage_sources` into a scratch root, then `_load_sources(manifest, lazy=True)`, materialize, assert schema and values equal the input. Red on base for the staging-failure set and the changed-type set of probe D (raise or schema mismatch) and for the nested cells. Green on base on purpose for every Parquet-exact type: those cells pin that their handoff did not change.
- AT-F4. Format choice: for each AT-F3 table the manifest says `parquet` exactly when the predicate passes; a `parquet` entry loads as a `LazySource` with `lazy=True` and an `ipc` entry loads as a `pa.Table`. Red on base (the manifest is a string).
- AT-F5. The worker refuses a manifest entry with format `"feather"`, with no format, and as a bare string, before it opens any file (a spy on the adapter reads sees no call). Red on base (a bare string is accepted).
- AT-F6. `run_pipeline_isolated(config, {"t": L})` returns an `IsolatedRunResult` and does not raise; the outcome is not `completed`; the error text holds no cell value. Red on base (raises in the parent). Pins G-1.
- AT-F7. `probe_peak_bytes` on fixture L returns an inconclusive result and does not raise. Red on base.

The builder report also lists, for G-4, the plain-run result of each probe D staging-failure type after the fix.

## 7. Mutations

Each alone on the final head; each must turn the named test red. Record the head (class 9).

| ID | Mutation | Red |
|---|---|---|
| M-1 | `_parquet_stages_exactly` returns True for every type | AT-F1, AT-F3, AT-F4 |
| M-2 | the predicate does not look into `struct`, `list` or `map` children | AT-F3 nested cells |
| M-3 | `fixed_size_list` added to the leaf set | AT-F1, AT-F3 |
| M-4 | `date64` added to the leaf set | AT-F3 `date64` cells |
| M-5 | the predicate returns False for every type | AT-F4 lazy half |
| M-6 | the worker loads an `ipc` entry as a `LazySource` | AT-F1, AT-F3 |
| M-7 | the worker treats an unknown format as `parquet` | AT-F5 |

## 8. Frozen contracts and byte changes

Frozen contracts touched: none. Output files and returned tables do not change bytes. No reason code, public name or `--json` field changes. `IsolatedRunResult` and `ProbeResult` keep their fields.

Internal change (not a contract): the isolated payload, a file between the parent and a same-version child, changes shape. The manifest value becomes `{"path", "format"}`, and some staged sources are `.arrow` files. AT-F3 and AT-F4 pin it. No golden is needed, because no output byte changes.

Breaking: none.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| Class | Applies | How |
|---|---|---|
| 1 Anchored validation | no | no regex added |
| 2 Strict wire and stored types | no | the manifest is a JSON dict read by the same-version child; `format` is checked as a token under class 4 |
| 3 No exception context | yes | no new raise carries a value; AT-F6 checks the text |
| 4 Versioned read models | yes | `format` is a checked token; unknown and missing are refused (AT-F5, M-7) |
| 5 Normalized guard scanners | no | no scanner added |
| 6 No reaching into private modules | no | all edits are inside `decoy_engine.execution` and its own `fileaccess` adapter |
| 7 No hidden CI failures | no | no CI step changes |
| 8 One input, one trust class per entry point | no | no user-chosen name; staged names are engine-made |
| 9 Mutations on the final head | yes | section 7; the builder records the head |
| 10 Allowlisted helpers are still checked | yes | the new IPC read row names `_load_sources` by exact path and function |
| 11 No raised caps | yes | `parquet-intermediate-writers` stays at 1; module-size ceilings move only by the lines added, listed in the report |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | N/A: no new log, message or error text; the existing child failure classification keeps the error value-free | AT-F6 checks the result text holds no cell value | N/A: no emitter added |
| 2 | Cleanup missing on an exit path | N/A: the work root stays owned by the `ExitStack` in `_isolated_run.py:364-398`; the `.arrow` file is written inside it and removed with it | AT-F6 runs the failing child exit; existing scratch tests | N/A: no new resource owner |
| 3 | State machine and concurrency | N/A: no shared state; staging is per call into a private work root | none needed | N/A: no transition added |
| 4 | Route parity and silent fallback | the handoff format is chosen from one closed type set, so every route that stages a source gets the same exact table; no fallback on error | AT-F1, AT-F2, AT-F3 across routes in section 10.2 | M-1, M-2, M-3 |
| 5 | Referential integrity | N/A: no FK path changes; relationship jobs stage the same tables, now exact | section 10.3 | N/A: no FK path changes |
| 6 | Untrusted producer | the child reads only `parquet` or `ipc` entries written by its parent; any other token is refused before a file opens | AT-F5 | M-7 |
| 7 | Check then use on a path (TOCTOU) | N/A: paths are engine-made inside a protected work root, as today; no new check-then-open | none needed | N/A: no new path consumer |
| 8 | Weak tests and overclaimed evidence | each AT records red on `26091c834`; AT-F1g and the Parquet-exact AT-F3 cells are marked green on base on purpose | builder report with base SHA and red output | each mutation names the AT it turns red |
| 9 | Behavior-preserving refactor drift | Parquet-exact tables keep the Parquet handoff and the lazy child | AT-F4 lazy half, `test_isolated_worker_streaming.py` TB-1 cases | M-5 |
| 10 | Frozen contract drift | N/A: no frozen contract touched (section 8) | existing output goldens unchanged | N/A: nothing frozen moves |

## 10. Enumerations

### 10.1 Exit paths

Of `run_pipeline_isolated` (`_isolated_run.py:364-398`), which owns the work root and the publication:

- Staging raises (base: the fixed-size list case; after: only disk or permission errors). The `finally` aborts the publication and closes the scratch stack. Unchanged.
- Child completes: `_spawn_and_classify` publishes or returns the staged output (`_isolated_run.py:484`, `:532`). Unchanged.
- Child fails, times out or is killed: classified, staging output removed (`_isolated_run.py:569`, `:575`). After the fix the fixed-size list case takes this exit (AT-F6).
- Worker refuses an unknown manifest token: a child failure, same exit as above (AT-F5).

### 10.2 Routes

Every path by which an in-memory source with such a column moves through the engine:

| Route | Touches the handoff | Base result | After |
|---|---|---|---|
| `run_pipeline` auto, admission probe (`_transforms_admission.py:330` via `_pipeline_routing_signals.py:476`) | yes | raises (probe A) | exact handoff (AT-F1) |
| `run_pipeline` auto, transform-bearing prepared tables (`_transforms_admission.py:279`) | yes | raises (same staging) | exact handoff (AT-F3 covers staging; AT-F1 the run) |
| `run_pipeline` auto, resident-fit probe (`pipeline/_resident_fit.py:443`) | yes | swallowed, evidence lost (probe C) | exact handoff (AT-F3) |
| `execution_mode="full_frame"` | yes (routing runs first) | raises | runs (AT-F2) |
| `execution_mode="sequential"` or `"out_of_core"` | yes for a relationship job | raises for the only-list shape | eligibility unchanged; handoff exact |
| `execution_mode="stream"` | no | refused without a sink | unchanged |
| auto-chunk lane in process | no | runs (probe A, two-column shapes) | unchanged (AT-F1 runs both `auto_chunk` values) |
| `run_mask_chunked`, `run_mask_pipeline_chunked` with in-memory chunks | no | runs | unchanged |
| `run_pipeline_isolated` (public) | yes | raises in the parent | result object (AT-F6) |
| `LazySource` sources | no (already a file) | Parquet cannot hold the cell | n/a |
| CLI | no | reads files only | n/a |


### 10.3 FK shapes

- Single, composite, self-referencing and cross-table relationships: the probe and the sequential child stage each table through the same `stage_sources`, so every FK shape gets the same exact handoff. No FK code changes.
- Children in another batch: N/A: the in-memory handoff is per call; batching is not touched.

### 10.4 Fields

- `IsolatedRunResult` (`_isolated_common.py:401`): no field added or changed. The fixed-size list case now fills `outcome` and the reason fields instead of raising.
- `ProbeResult` (`_probe.py:149`): no field added or changed. The case now returns `conclusive=False` with a `reason`.
- Manifest entry (internal): `path` (str), `format` (`"parquet"` or `"ipc"`).

### 10.5 Output surfaces

- Returned tables and written files: bytes unchanged; the fixed-size list column now comes back where it raised before.
- Errors: the raw `ArrowNotImplementedError` from routing goes away; no new message text.
- Logs: unchanged; `resident fit probe unavailable` (`pipeline/_resident_fit.py:455`) fires less often.
- stdout, stderr, `--json`, audit, evidence, progress, help: N/A: engine library change with no CLI surface.

## 11. Reuse inventory

- `arrow_adapter.ipc_new_file` (`fileaccess/adapters/arrow.py`), already used by `_chunked_output_sink.py:472`, for the IPC write.
- `arrow_adapter.write_table` and `LazySource` for the Parquet half, unchanged.
- `tests/native/_rev9_type_catalogue.py` `CATALOGUE` as the AT-F3 corpus.
- Sentries: `tests/sentry/file_access_registry.toml`, `tests/sentry/baselines/parquet-intermediate-writers.json`, `tests/sentry/test_module_size.py`.
- No new machinery. The predicate is the only new function.

## 12. Pre-mortem

- The allowlist names a type that Parquet does not round-trip exactly in some value range (for example a timestamp zone or a decimal width). AT-F3 covers each catalogue type with and without a null; the builder drops a leaf that fails, and an unlisted type goes to IPC.
- A large in-memory table with a moved type now loads eagerly in the child and uses more memory than the lazy path. Today these tables fail or drift, so no working run gets worse. If it shows in a probe, the follow-up is IPC memory mapping, not Parquet.
- A test or helper builds a bare-string manifest. AT-F5 makes it fail loudly; section 4.2 lists the known callers.
- #770 lands first and conflicts. It does not touch these files, so the rebase is textual only.

## 13. Slices and risk

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S1 | engine | predicate, two-format handoff, worker loader, sentry rows, known-issue list, AT-F1 to AT-F7, changelog fragment; about 55 source lines | nothing; rebases over #770 with no overlap | R2 | T1 plus the full engine suite (serialization trigger) |

One slice. No CLI slice: the CLI cannot reach the case.

## 14. Follow-ups (not in this row)

- G-1: coded reason when a Parquet target cannot hold a fixed-size list null cell.
- G-2: coded read error for a struct of fixed-size list null that pyarrow writes but cannot read.
- G-4: plain-run results of the union, view, run-end-encoded and interval types after the fix.
