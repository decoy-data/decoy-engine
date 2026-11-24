Status: plan

# FIXED-LIST-NULL: an in-memory source that Parquet cannot store no longer breaks the run, and Parquet output never holds an unreadable fixed-size list

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 3 (Dennis R1 and R2: GO-WITH-FIXES). Roadmap row: FIXED-LIST-NULL (CLI `docs/roadmap/groups/run.md`, 1.0, function break). Anchors are in this repository (decoy-engine) at `origin/main` `26091c834` unless marked `#770:` (engine PR #770, UF-DOMAIN S1, head `3ad186c50`).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `api-and-compatibility.md` (one appended reason code; internal payload), `catalogs/recurring-defects.md` (11 classes). Engine `CLAUDE.md` file-size rule; engine `CONTRIBUTING.md` reason rule (`since=UNRELEASED`).

Risk: R2. It changes the payload format of the isolated child (internal serialization), what the routing probe can measure, and adds a refusal to the one Parquet output adapter (data loss closed). Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full suite before merge: yes (serialization and reason-registry triggers).

## Rev 3 changes

| Finding (Dennis R2) | Change | Where |
|---|---|---|
| H1: the walk skips extension types; `fixed_shape_tensor` with a null at row 0 writes an unreadable file today | The shared type walk unwraps `pa.ExtensionType` to `storage_type`, and the array walk uses `ExtensionArray.storage`. Probe G added (re-run on the Mac). New AT-F9 cells: `fixed_shape_tensor` with a null at row 0, and a user extension type over `struct<f: fixed_size_list>`. New M-13. Pre-mortem corrected. G-6 now records, with probe evidence, that the dictionary, run-end-encoded, view and union forms raise loudly | 1.2, 4.2, 4.6 G-6, 6, 7, 12 |
| M1: `_FileBacked.write` is unguarded | `output_parquet_writer` returns `_CheckedParquetWriter`, a narrower type with only `write_batch`, `write_table`, `close` and the context methods; both write methods run the check. No `write`. New AT-F9 cell asserts `write` is absent | 4.2, 6 |
| L1: more nesting cells | AT-F9 cells for `fixed_size_list<fixed_size_list>` (inner null under a valid outer cell) and `large_list<fixed_size_list>` (null at row 0). M-2 extended to the `fixed_size_list` and `large_list` children | 6, 7 |
| L2: floor wording | "Proven on CI pyarrow; the remaining leaves are stable round-trips" | 4.2, 12 |

## Rev 2 changes

| Finding | Change | Where |
|---|---|---|
| H1 (data loss): a fixed-size list null at row 0, the last row or every row, and the same nested in a struct, list or map, writes to Parquet with no error and cannot be read back | Probe B rewritten from a re-run on the Mac. G-1 removed: the output refusal is now in this row (option a). One shared walk in the Arrow adapter; `write_output_table` and `output_parquet_writer` refuse any fixed-size list cell that is null or sits under a null parent, at any depth, with a coded reason. New AT-F8 (row-0 null to a `TransactionalSink` is refused, nothing published), AT-F9, M-8, M-9 | 1.2, 1.3, 2, 4.1, 4.2, 5, 6, 7, 8, 10 |
| M1: `struct<>` is not Parquet-exact | Re-probed: `pq.write_table` raises for `struct<>` and `struct<g: struct<>>`. The predicate is False for a struct with no fields; AT-F3 cells added | 1.2 probe E, 4.2, 6 |
| M2: leaves proven only on pyarrow 24 | `string_view`, `binary_view`, `decimal32`, `decimal64` and `float16` leave the allowlist and go by IPC. The floor is `pyarrow>=14` | 4.2, 12 |
| M3: IPC read | The worker reads with `pa.memory_map` plus `pa.ipc.open_file` (zero copy). Memory text and RLIMIT note rewritten; AT-F10 added | 4.2, 5, 6 |
| M4: predicate placement | The walk and the predicate move beside the Arrow file-access adapter (`fileaccess/adapters/arrow.py`), one shared walk with two callers: `stage_sources` and the output refusal | 4.2, 4.3, 4.5 |
| L1: child-name drift | AT-F3 compares `str(schema)` as well as `equals`. A Parquet-path type that fails the `str(schema)` check leaves the allowlist | 6 |
| L2: AT-F5 | Mixed manifest; no IPC or Parquet read before every entry is checked; a non-str path is refused | 6 |
| L3: changelog | The fragment says `run_pipeline_isolated` now returns a crashed result where it raised, and names the new reason | 4.4, 8 |

## 1. Frame

### 1.1 Symptom

`run_pipeline(config, sources={"t": table})` with an in-memory `pa.Table` whose only column is a passthrough `fixed_size_list` with a null cell in a middle row raises a raw `pyarrow.lib.ArrowNotImplementedError: Lists with non-zero length null components are not supported`. No coded reason, no output. The CLI cannot reach the case: it reads files, and a Parquet file cannot hold this cell (Dennis, review of engine #754). The Python API can.

The worse half (Dennis R1, H1): when the null sits in the first row, the last row or every row, Parquet writes the file with no error, and the file cannot be read back. A run that publishes such a table to Parquet reports success and leaves an unreadable output.

### 1.2 What the probes showed

All probes ran on the Mac and the Dell through `vm-run` against `origin/main` `26091c834` and against #770 head `3ad186c50`. Both heads gave the same result for every case, so #770 does not change this path. Probe scripts stay in the author's scratch, not in the repo.

Probe A, shapes (fixed-size list of `int32[2]`, `int64[1]`, `string[2]`; null positions; `auto_chunk` on and off; in-memory result, no output file; the profile file is the same table with the null replaced, because the profiler reads the declared file):

| Shape | Null at row 1 of 3 | Null at row 0 | All null |
|---|---|---|---|
| only the list column, passthrough | FAIL, `ArrowNotImplementedError` | returns | returns |
| list column plus a passthrough string | returns | returns | returns |
| list column plus a redacted string | returns | returns | returns |

"returns" means the in-memory result came back. It says nothing about a Parquet output of the same table: see probe B.

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

Probe B, write then read back, pyarrow 24.0.0 on the Mac (rev 2 re-run, confirming Dennis R1):

| `fixed_size_list<int32>[2]` column | `pq.write_table` | `pq.read_table` of that file |
|---|---|---|
| null at a middle row | raises `ArrowNotImplementedError` | n/a |
| null at row 0 | writes | raises `ArrowInvalid: Expected all lists to be of size=2 but index 1 had size=0` |
| null at the last row | writes | raises `ArrowInvalid` (index 3) |
| every row null | writes | raises `ArrowInvalid` |
| no null | writes | reads, `equals` True |
| `struct<f: fixed_size_list>` with `f` null at row 0 | writes | raises `ArrowInvalid` |
| `list<fixed_size_list>` with a null item at row 0 | writes | raises `ArrowInvalid` |
| `struct`, `list` or `map` holding a null fixed-size list in a middle row | raises `ArrowNotImplementedError` | n/a |
| `struct<f: fixed_size_list>` with the struct row null and `f` not null | raises `ArrowNotImplementedError` | n/a |

So a null fixed-size list cell is never safe in Parquet: it raises or writes a file that cannot be read. A null parent counts as a null cell (last row of the table).

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

Probe E, empty structs (rev 2). `pq.write_table` raises `ArrowNotImplementedError` for `struct<>` and for `struct<g: struct<>>`. The IPC round trip of `struct<>` is exact.

Probe G, more wrappers (rev 3, Dennis R2 `walk.py` re-run on the Mac, pyarrow 24.0.0), each with a null fixed-size list cell:

| Form | `pq.write_table` | read back |
|---|---|---|
| `fixed_shape_tensor` (extension over `fixed_size_list`), null at row 0 | writes | raises `ArrowInvalid` |
| `fixed_size_list<fixed_size_list>`, inner null under a valid outer cell | writes | raises `ArrowInvalid` |
| `large_list<fixed_size_list>`, null at row 0 | writes | raises `ArrowInvalid` |
| `dictionary<int32, fixed_size_list>`, null index at row 0 or a null dictionary value | raises `ArrowNotImplementedError` | n/a |
| run-end-encoded over `fixed_size_list`, null at row 0 | raises `ArrowNotImplementedError` | n/a |
| `list_view<fixed_size_list>`, null at row 0 | raises `ArrowNotImplementedError` | n/a |
| `dense_union` with a `fixed_size_list` child | raises `ArrowNotImplementedError` | n/a |

The first three are silent data loss and need the walk; the last four raise loudly at write.

Probe F, a throwaway prototype (reverted): `stage_sources` writes Arrow IPC and the worker reads it. Every failing cell of probe A passed, with the exact source type and values. The probe child then failed when it staged its own output as Parquet, so the probe came back inconclusive (`outcome='crashed'`) and the parent run went on. `run_pipeline_isolated` on the same table returned an `IsolatedRunResult` with outcome `crashed` instead of raising in the parent.

### 1.3 Impact under the V1 bar

- Function break on the Python API: a valid Arrow table fails a plain run with an uncoded pyarrow error. Ten catalogue types fail the same way (probe D), and the resident-fit probe loses its evidence for them without a word.
- Data loss: an in-memory table with a null fixed-size list cell in the first row, the last row or every row, published to Parquet (`TransactionalSink`, `publish`, subset materialize), reports success and leaves a file that cannot be read.
- Not a leak: no error text holds a cell value.

## 2. Root cause with evidence

Two faults, one cause: the engine writes Arrow tables to Parquet without checking that Parquet can hold them.

1. The isolated handoff. `stage_sources` (`src/decoy_engine/execution/_isolated_commit.py:158-167`) writes every caller table with `arrow_adapter.write_table` (`pq.write_table`, `src/decoy_engine/fileaccess/adapters/arrow.py:98-101`), and the worker wraps each path in a lazy Parquet handle (`src/decoy_engine/execution/_isolated_worker.py:76-113`, `LazySource(Path(path))` at `:109`). Parquet cannot hold every Arrow table: some types not at all, some only with a changed type, and a fixed-size list with a null cell never (probe B). The routing probe sends a caller's in-memory tables through this handoff (`_probe.py:250-300`, `run_isolated(...)` at `:283`, on head slices from `_probe_scale.py:215-236`) during route choice, so a plain run fails before any route executes.
2. The output adapter. Every published Parquet table goes through `write_output_table` or `output_parquet_writer` (`src/decoy_engine/fileaccess/adapters/arrow.py:114-123`; callers `execution/_transactional_sink.py:222`, `:271`, `publication/_publish.py:464`, `subset/_materialize.py:69`). Neither checks for a null fixed-size list cell, so pyarrow either raises a raw error or writes an unreadable file (probe B).

The two probe callers treat the handoff failure differently (probe C). That asymmetry is a symptom, not the cause.

Not the cause:

- The nested rebuild (`_fk_keys.py:484-562`, engine #754) and `is_nested_type`: the failing trace never reaches them.
- #770 moves the rebuild to `#770:src/decoy_engine/execution/pipeline/_source_types.py`. It does not touch `_isolated_commit.py`, `_isolated_worker.py`, `_isolated_run.py`, `_probe*.py` or `fileaccess/adapters/arrow.py` (its diff stat), and probe A gave the same result on its head. This plan anchors on `origin/main` and rebases over #770 with no overlap.

## 3. Established solutions considered

- Search run: Apache Arrow documentation on Parquet type support and on the IPC file format (Feather V2); pyarrow `ipc.new_file`, `ipc.open_file`, `memory_map`; the Arrow C++ Parquet writer's "non-zero length null components" limit (apache/arrow issue tracker); in-repo `git grep ipc_new_file`. Found: the Arrow IPC file format is the lossless on-disk form of an Arrow table and carries every Arrow type, and pyarrow documents memory-mapped IPC reads as zero copy. Parquet has its own type system with gaps and conversions, and the C++ writer does not support null fixed-size list cells. Probe D confirms an exact IPC round trip for the whole catalogue on pyarrow 24.
- In this repository: the no-sink chunked collector already spills as IPC through the adapter (`src/decoy_engine/execution/_chunked_output_sink.py:472`, `arrow_adapter.ipc_new_file`). `FixedWidthWriteError` (`src/decoy_engine/errors.py:467`) is the house pattern for "refuse a value the target format cannot hold, publish nothing". Reasons go in the F29 registry (`src/decoy_engine/reasons/`). The fix reuses all three.
- Rejected: catch the staging error in the probe and return inconclusive. It hides the class, keeps the child on drifted types, and leaves `run_pipeline_isolated` raising.
- Rejected: stage every source as IPC. The child would lose the lazy Parquet handle for every isolated job (TB-1 and B6b, `_isolated_worker.py:79-97`, pinned by `tests/unit/execution/test_isolated_worker_streaming.py`).
- Rejected: try Parquet and fall back on error, for staging or output. Probe B shows Parquet writes files it cannot read, so "the write succeeded" proves nothing.
- Rejected: read back every output file after writing. It doubles output cost for one rare type.
- Rejected for output: rewrite the null cell (for example as an empty-list sentinel). It changes data; a refusal is the house rule.

The only custom code is the type allowlist and the null walk, because no library answers "does Parquet round-trip this Arrow type exactly". The allowlist is a closed set pinned by a catalogue test.

## 4. Fix design

### 4.1 Guarantee

1. The isolated child receives each source table exactly: the table the child loads equals the caller's table in `str(schema)` and values, for every type in the type catalogue, for empty structs, and for a fixed-size list at any depth with null cells anywhere.
2. A table whose every type, at every depth, is in a closed Parquet-exact set is still handed over as Parquet and still loads lazily in the child (unchanged). Every other table is handed over as an Arrow IPC file and loads in the child from a memory map.
3. A plain `run_pipeline` of an in-memory source with a passthrough fixed-size list with null cells, with no Parquet output, completes and returns that column with the source type and values, with `auto_chunk` on or off and with `execution_mode="full_frame"`.
4. The engine never publishes a Parquet file holding a fixed-size list cell that is null or under a null parent, at any depth. `write_output_table` and `output_parquet_writer` refuse it before any byte of that table or batch is written, with the coded reason `runtime/parquet_fixed_list_null`; the sink publishes nothing for the run. The message names the column only.
5. The routing probe never raises because of the source handoff. When the child cannot finish (now: the coded output refusal in its own output stage), the probe is inconclusive and routing goes on as it does with no probe evidence.
6. Valid outputs do not change bytes.

Non-goals (recorded, not blockers):

- G-2. A Parquet source file written elsewhere with a null fixed-size list cell (probe B rows that write): the profiler and readers raise a raw `ArrowInvalid`. A coded read error is a follow-up row.
- G-3. The probe D failures that happen before staging (`time64[ns]`, `fixed_shape_tensor` without null, `dictionary_float16`): known issues in `tests/integration/test_byte_estimate_arrow_types_e2e.py:305-321`; not this row.
- G-4. Whether the union, view, run-end-encoded and interval types then run end to end. This plan makes their handoff exact; the builder records their plain-run result. A new failure past staging is a follow-up.
- G-5. The catch-all in `_resident_fit._run_probe` stays. It covers child start failures outside this scope.
- G-6. Other types Parquet cannot write at output keep raising pyarrow's own error at the output write: unions, views, run-end-encoded, and dictionary, run-end-encoded, `list_view` and union wrappers over a null fixed-size list (probe G rows 4 to 7). They raise; they do not write a bad file, so they are not data loss. A coded reason for them is a follow-up.
- G-7. Engine-internal Parquet scratch writers that never see a caller's fixed-size list (`vault/_format.py:260`, `native/_pool_quality.py:248`, `out_of_core/_stage.py:90` key stage, `declared_casting/_stream.py:168-183` typed CSV staging). Section 10.2 lists why each is out of reach.

### 4.2 Design

All in `src/decoy_engine/fileaccess/adapters/arrow.py` (156 lines today), beside the writers:

- One private recursive walk over a type's children (`list`, `large_list`, `fixed_size_list`, `struct`, `map`). An extension type is unwrapped to its `storage_type` first, at every depth. It is the only place that knows how to reach nested types. Two callers use it.
- `parquet_holds_type(t: pa.DataType) -> bool`, package-internal (no export from `decoy_engine`). True when `t` and every nested type pass. Leaf set, proven on CI pyarrow and pinned by AT-F3; the remaining leaves are stable round-trips across the `pyarrow>=14` range: `null`, `bool`, signed and unsigned integers, `float32`, `float64`, `decimal128`, `decimal256`, `string`, `large_string`, `binary`, `large_binary`, `fixed_size_binary`, `date32`, `time32[ms]`, `time64[us]`, `time64[ns]`, `timestamp` with unit `ms`, `us` or `ns` (any zone), `duration`, and `dictionary<int32, string | binary>`. Nested: `list`, `large_list`, `map`, and `struct` with at least one field. False for everything else, including every `fixed_size_list` (the null limit depends on the data), `struct<>`, every extension type (the predicate does not unwrap them: Parquet does not keep every extension type), `string_view`, `binary_view`, `decimal32`, `decimal64`, `float16`, `date64`, `time32[s]` and `timestamp[s]`. A type the set does not name is false, so a new Arrow type goes to IPC until a test proves Parquet holds it.
- `_refuse_fixed_list_null(data: pa.Table | pa.RecordBatch)`. For each column whose type contains a `fixed_size_list` (found by the walk), walk the array with parent validity merged (`ExtensionArray.storage`, `StructArray.flatten`, `ListArray.flatten` and `LargeListArray.flatten`, `FixedSizeListArray.flatten`, the map's keys and items) and raise `ParquetFixedListNullError` if any fixed-size list array on the path has `null_count > 0`. Columns with no fixed-size list cost one type check. The raise happens after the loop, outside any `except`, with only the column name (class 3).
- `write_output_table` calls the check before `write_table`. `output_parquet_writer` returns `_CheckedParquetWriter`, a narrower wrapper with only `write_batch`, `write_table`, `close`, `__enter__` and `__exit__`; both write methods run the check first. It has no `write`, so no raw byte path reaches the output file. Callers today use only `write_batch` and `close` (`_transactional_sink.py:271-283`). The check runs before any byte of that data reaches the file.
- `ParquetFixedListNullError(DecoyError)` in `src/decoy_engine/errors.py`, beside `FixedWidthWriteError`, with `code = reasons.runtime.PARQUET_FIXED_LIST_NULL` (`"parquet_fixed_list_null"`, appended with `since=UNRELEASED` per `CONTRIBUTING.md:57`). Exported from `decoy_engine.errors` like its siblings.
- IPC read: `ipc_read_path(path: Path) -> pa.Table` beside `read_table`: `pa.ipc.open_file(pa.memory_map(str(path), "r")).read_all()` inside `guarded`, so file errors stay coded as today.
- `src/decoy_engine/execution/_isolated_commit.py`, `stage_sources`: writes a table as `s{index:04d}.parquet` with `arrow_adapter.write_table` when every field passes `parquet_holds_type`, else as `s{index:04d}.arrow` with `arrow_adapter.ipc_new_file`. The manifest value changes from a path string to `{"path": str, "format": "parquet" | "ipc"}`.
- `src/decoy_engine/execution/_isolated_worker.py`, `_load_sources`: first checks every entry (a dict, `path` a `str`, `format` exactly `"parquet"` or `"ipc"`) and raises before any read if one fails (class 4). Then a `parquet` entry loads as today (`LazySource` when `lazy`, else `pq.read_table`) and an `ipc` entry loads through `ipc_read_path`.
- Sentries: `tests/sentry/file_access_registry.toml` gets a row for `ipc_read_path` in `_load_sources` (rule and reason as the Parquet row at `:136-143`). `tests/sentry/baselines/parquet-intermediate-writers.json` keeps `stage_sources` at `max: 1`. If an IPC writer registry exists, `stage_sources` gets a row with the same reason. No cap is raised (class 11).
- Known-issue list: `_REFUSED_WITH_ESTIMATE_OFF` (`tests/integration/test_byte_estimate_arrow_types_e2e.py:305-321`) loses each entry that now passes. The builder reports which.
- Tests that pass a bare string manifest (`tests/unit/execution/test_isolated_worker_streaming.py:107`, `:127`; `tests/unit/execution/test_b6b_modes.py:431-433`) move to the new entry shape.
- Size: about 85 source lines in `fileaccess/adapters/arrow.py` (156 to about 241), about 25 across `_isolated_commit.py` (307) and `_isolated_worker.py` (233), about 15 in `errors.py` and the reason module. New names: `ParquetFixedListNullError` (public), `reasons.runtime.PARQUET_FIXED_LIST_NULL` (public), `parquet_holds_type` and `ipc_read_path` (adapter-internal). No new file in `src/`.

Build differences from revision 3:

- PyArrow 24 renames the map entries field on a Parquet read. Maps use IPC. The private Parquet writer uses `use_compliant_nested_type=False` to preserve list and large-list child names.
- The IPC adapter takes an open file capability. The worker requests it after checking the manifest and the adapter maps its library path. The file-access scanner recognizes this adapter call for the named registry row.
- The runtime reason adapter recognizes the new public error so the child envelope carries its code. Test payload builders for B6a and the simulated noisy worker also consume the revised manifest. The existing adapter tests live in `tests/fileaccess/test_output_writers.py`.

### 4.3 Choke points

- Source handoff: one writer, `stage_sources` (held to one Parquet write by `parquet-intermediate-writers`), one reader, `_load_sources` (`file_access_registry.toml`). The format rule is `parquet_holds_type`. Guard: AT-F3. Mutation M-1.
- Published Parquet output: every engine output goes through `write_output_table` or `output_parquet_writer` (the "one engine entry for a whole published table", `arrow.py:114-116`; `tests/sentry/defects/test_output_metadata_choke_point.py` already holds every output writer to these two). The refusal is inside both, so a new output caller gets it by construction. Guard: AT-F8, AT-F9. Mutations M-8, M-9.
- Both rules reach nested types through the one walk, so "any depth" is written once (M-2 turns AT-F3 and AT-F9 red).

### 4.4 Placement

No new file in `src/`. Tests go into existing files:

| Test or change | File | Sits beside or falls under |
|---|---|---|
| AT-F1, AT-F1g, AT-F2 | `tests/native/test_unconfigured_passthrough_types.py` | the #754 resident nested cases |
| AT-F3, AT-F4, AT-F5, AT-F10 | `tests/unit/execution/test_isolated_worker_streaming.py` | the TB-1 `_load_sources` cases |
| AT-F6 | `tests/unit/execution/test_isolated_safe_error.py` | isolated outcome and value-free error cases |
| AT-F7 | `tests/unit/execution/` beside the existing `probe_peak_bytes` cases | |
| AT-F8, AT-F9 | the existing `TransactionalSink` unit tests in `tests/unit/execution/` and the adapter tests in `tests/unit/fileaccess/` | output write and abort cases |
| Parquet type rule, output check and IPC read | `src/decoy_engine/fileaccess/adapters/arrow.py` | CODEMAP "Where Things Go", "Secret providers, file access" |
| Behavior change | `changelog.d/fixed-list-null.md` | CODEMAP "Where Things Go", "Changelog fragments" |

Changelog: engine fragment `changelog.d/fixed-list-null.md`. It says: in-memory sources Parquet cannot hold are handed to the isolated child exactly; `run_pipeline_isolated` now returns a crashed result where it raised in the caller; Parquet output with a null fixed-size list cell is refused with `` `runtime/parquet_fixed_list_null` `` where it raised a raw error or wrote an unreadable file.

### 4.5 Design notes

- No new module. The Parquet type rule moves next to the Parquet writers it describes, so the adapter owns "what Parquet can hold" for both the handoff and the output (one place per fact).
- The output refusal follows `FixedWidthWriteError`: fail closed on a value the target cannot hold, value-free message, publish nothing.
- The parent and the child are always the same engine version, so the payload change needs no compatibility reader; the worker still refuses an unknown token.

## 5. Behavior and failure modes

| Input | Before | After |
|---|---|---|
| In-memory table, only column a passthrough fixed-size list, null in a middle row, in-memory result | raw `ArrowNotImplementedError` in routing | runs; column exact; probe inconclusive |
| Same, with other columns | runs; resident-fit probe silently skipped | runs; probe child gets the exact table; probe inconclusive (child output refused) |
| Any null fixed-size list cell (row 0, last, all, middle, nested, under a null parent) published to Parquet through a sink, `publish` or subset | raw `ArrowNotImplementedError`, or success with an unreadable file | `ParquetFixedListNullError`, `runtime/parquet_fixed_list_null`; nothing published |
| Fixed-size list with no null published to Parquet | writes | unchanged bytes |
| In-memory table with a union, view, run-end-encoded or interval column | raw error in routing | handoff exact; later stages as they are (G-4, G-6) |
| In-memory table with `date64`, `time32[s]`, `timestamp[s]`, an empty struct or a pyarrow-24-only leaf | probe child runs on a changed type, or staging raises | probe child runs on the exact type (IPC) |
| In-memory table of Parquet-exact types only | Parquet handoff, lazy child | unchanged |
| `run_pipeline_isolated` with a fixed-size list null cell | raw `ArrowNotImplementedError` in the parent | `IsolatedRunResult`, outcome `crashed` (the child's output refusal) |
| Manifest entry with an unknown or missing format, or a non-str path | n/a | the child raises before reading any entry; the parent classifies the child failure as today |
| Disk full or permission error while staging | raised from `stage_sources` | unchanged |

Memory. An IPC entry is read from a memory map with zero copy: the child's table buffers point into the mapped file, so there is no second heap copy. Pages count toward RSS when touched (the measured behavior noted at `execution/out_of_core/_external_sort_run.py:22-30`), so a probe still measures what the child really touches. Under `rlimit_kind="as"` the whole mapping counts toward the address-space cap, as an eager read would. Under `rlimit_kind="data"` a read-only file mapping is not counted in `VmData` (`_isolated_memwatch.py:8-9` names the kernel field), so the child can map an IPC file larger than its data cap; touched pages still show in RSS. AT-F10 pins the `as` case; the builder records the `data` case on Linux in the report. This applies only to tables Parquet cannot hold exactly, which fail or drift today, so no working lazy path changes.

Route choice can change for in-memory tables with the moved types, because the probe now measures the exact table.

## 6. Acceptance tests (red-first)

Fixture L: `pa.table({"x": pa.array([[0, 0], None, [2, 2]], pa.list_(pa.int32(), 2))})`, passthrough, with a profile file that holds the same column with the null replaced by `[0, 0]` (the pattern of `tests/integration/test_byte_estimate_arrow_types_e2e.py:324-332`). Fixture L0: the same with the null at row 0. Every in-memory run asserts the output column's `str(type)` and values equal the source column's.

- AT-F1. Plain `run_pipeline`, fixture L, in-memory result, `auto_chunk` False and True; also `int64[1]` and `string[2]` value types; also a 5-row table with nulls at rows 1 and 3. Red on base: `ArrowNotImplementedError` from `stage_sources`.
- AT-F1g. Green on base on purpose (regression pins), in-memory result only: null at row 0, null at the last row, all null; and fixture L's column beside a redacted string column.
- AT-F2. Fixture L with `execution_mode="full_frame"`, in-memory result. Red on base, same trace.
- AT-F3. Staging round trip: `stage_sources` into a scratch root, `_load_sources(manifest, lazy=True)`, materialize, assert `str(schema)` equal and `equals` True. Cells: every `CATALOGUE` type with and without a null; `string_view`, `binary_view`, `decimal32`, `decimal64`, `float16`; `struct<>` and `struct<g: struct<>>`; `struct<f: fixed_size_list<int64>[2]>`, `list<fixed_size_list<int64>[2]>` and `map<string, fixed_size_list<int64>[2]>` with a null fixed-size list cell at row 0 and at a middle row. Red on base for the staging-failure and changed-type sets of probe D, the empty structs and the nested cells. Green on base on purpose for every allowlisted leaf: those cells pin that their handoff did not change, and a cell that fails `str(schema)` there removes the type from the allowlist.
- AT-F4. Format choice: for each AT-F3 table the manifest says `parquet` exactly when `parquet_holds_type` passes for every field; a `parquet` entry loads as a `LazySource` with `lazy=True` and an `ipc` entry loads as a `pa.Table`. Red on base (the manifest is a string).
- AT-F5. A mixed manifest: entry 1 a valid `parquet`, entry 2 a valid `ipc`, entry 3 bad. Bad forms: format `"feather"`, no format, a bare string, a non-str path (`123`, `None`). Each raises, and a spy on `LazySource`, `pq.read_table` and `ipc_read_path` sees no call. Red on base (a bare string is accepted; entries are read one by one).
- AT-F6. `run_pipeline_isolated(config, {"t": L})` returns an `IsolatedRunResult` and does not raise; the outcome is not `completed`; the result text holds no cell value. Red on base (raises in the parent).
- AT-F7. `probe_peak_bytes` on fixture L returns an inconclusive result and does not raise. Red on base.
- AT-F8. Fixture L0 written through `TransactionalSink.write` and through `write_batches`, then committed: both raise `ParquetFixedListNullError` with code `parquet_fixed_list_null`; the target directory holds no file for the table; the message holds the column name and no cell value; `__cause__` and `__context__` are None. Red on base (`write` succeeds and the published file fails `pq.read_table`; `write_batches` the same).
- AT-F9. Adapter cells, `write_output_table` and `output_parquet_writer`: null at row 0, last row, all rows, middle row; the same inside `struct`, `list` and `map`; a null struct row over a non-null fixed-size list; a slice whose window holds no null of a column that has nulls outside it (written, read back equal); `fixed_shape_tensor` with a null at row 0; a user `pa.ExtensionType` over `struct<f: fixed_size_list>` with `f` null at row 0; `fixed_size_list<fixed_size_list>` with an inner null under a valid outer cell; `large_list<fixed_size_list>` with a null at row 0; and through `output_parquet_writer`, `hasattr(writer, "write")` is False. Every null cell refuses; the slice and the no-null cases write and read back equal. Red on base for each null cell (unreadable file or raw raise). Green on base on purpose for the no-null and slice cells.
- AT-F10. A child loads an `ipc` entry under `rlimit_kind="as"` with a cap of the baseline plus three times the file size and completes. Green on base is impossible (no `ipc` entry on base); this cell pins the memory note.

The builder report also lists, for G-4, the plain-run result of each probe D staging-failure type after the fix, and the `rlimit_kind="data"` observation.

## 7. Mutations

Each alone on the final head; each must turn the named test red. Record the head (class 9).

| ID | Mutation | Red |
|---|---|---|
| M-1 | `parquet_holds_type` returns True for every type | AT-F1, AT-F3, AT-F4 |
| M-2 | the shared walk does not enter `struct`, `list`, `large_list`, `fixed_size_list` or `map` children (one mutation per kind) | AT-F3 nested cells, AT-F9 nested cells, the `fixed_size_list<fixed_size_list>` and `large_list<fixed_size_list>` cells |
| M-3 | `fixed_size_list` added to the leaf set | AT-F1, AT-F3 |
| M-4 | `date64` added to the leaf set | AT-F3 `date64` cells |
| M-5 | `parquet_holds_type` returns False for every type | AT-F4 lazy half |
| M-6 | the worker loads an `ipc` entry as a `LazySource` | AT-F1, AT-F3 |
| M-7 | the worker treats an unknown format as `parquet` | AT-F5 |
| M-8 | `write_output_table` skips the refusal | AT-F8 (`write`), AT-F9 |
| M-9 | `output_parquet_writer` skips the refusal | AT-F8 (`write_batches`), AT-F9 |
| M-10 | the null walk reads child arrays without merging parent validity | AT-F9 null-parent cell |
| M-11 | `struct<>` treated as Parquet-exact | AT-F3 empty-struct cells |
| M-12 | the worker checks entries one by one as it reads | AT-F5 (the spy sees a read) |
| M-13 | the walk does not unwrap extension types (type and array) | AT-F9 `fixed_shape_tensor` and user-extension cells |
| M-14 | `_CheckedParquetWriter` gains a `write` that forwards unchecked | AT-F9 `write` cell |

## 8. Frozen contracts and byte changes

Frozen contracts touched:

- Reason registry (F29): one code appended, `runtime/parquet_fixed_list_null`, `since=UNRELEASED`. Additive. Release prep stamps the manifest and version (`CONTRIBUTING.md:57`); this slice does not edit them.
- Public errors: `ParquetFixedListNullError` added to `decoy_engine.errors`. Additive.
- `IsolatedRunResult` and `ProbeResult` keep their fields.

Byte changes: none to any output a reader can open. Valid Parquet outputs are byte-identical.

Breaking: a run that publishes a Parquet table holding a null fixed-size list cell now fails with `runtime/parquet_fixed_list_null` and publishes nothing. Before, it raised a raw `ArrowNotImplementedError` (middle-row null) or reported success with an unreadable file (row 0, last row, all rows, nested). `run_pipeline_isolated` with such a table returns a crashed result where it raised in the caller.

Internal change (not a contract): the isolated payload manifest value becomes `{"path", "format"}`, and some staged sources are `.arrow` files. AT-F3 and AT-F4 pin it.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| Class | Applies | How |
|---|---|---|
| 1 Anchored validation | no | no regex added |
| 2 Strict wire and stored types | yes | the manifest check requires a dict, a `str` path and an exact format token; `123` and `None` paths are refused (AT-F5) |
| 3 No exception context | yes | the output refusal is raised after the walk, outside any `except`, value-free; AT-F8 asserts `__cause__` and `__context__` are None |
| 4 Versioned read models | yes | `format` is a checked token; unknown and missing refused before any read (AT-F5, M-7, M-12) |
| 5 Normalized guard scanners | no | no scanner added |
| 6 No reaching into private modules | no | `execution` imports the adapter as it does today; the new error is public |
| 7 No hidden CI failures | no | no CI step changes |
| 8 One input, one trust class per entry point | no | no user-chosen name; staged names are engine-made |
| 9 Mutations on the final head | yes | section 7; the builder records the head |
| 10 Allowlisted helpers are still checked | yes | the new IPC read row names `_load_sources` by exact path and function |
| 11 No raised caps | yes | `parquet-intermediate-writers` stays at 1; module-size ceilings move only by the lines added, listed in the report |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the refusal names the column only and is raised with no exception context | AT-F8 seeded-marker check on the message and the chained exceptions; AT-F6 result text | M-8 (the raw pyarrow error returns) |
| 2 | Cleanup missing on an exit path | the refusal raises inside the sink's existing write path, so `capture_publication_failure` and abort run as for any write error (`_transactional_sink.py:221-225`, `:272-283`); the work root stays owned by the `ExitStack` in `_isolated_run.py:364-398` | AT-F8 (no file published), AT-F6 | M-8, M-9 |
| 3 | State machine and concurrency | N/A: no shared state; staging and the check run per call | none needed | N/A: no transition added |
| 4 | Route parity and silent fallback | one type rule for every route that stages a source; one output refusal inside the two adapter writers every output route uses | AT-F1, AT-F2, AT-F3, AT-F8, AT-F9 across section 10.2 | M-1, M-2, M-8, M-9 |
| 5 | Referential integrity | N/A: no FK path changes; relationship jobs stage the same tables, now exact | section 10.3 | N/A: no FK path changes |
| 6 | Untrusted producer | the child reads only checked `parquet` or `ipc` entries from its parent; every entry is checked before any read | AT-F5 | M-7, M-12 |
| 7 | Check then use on a path (TOCTOU) | N/A: paths are engine-made inside a protected work root, as today; the IPC read opens the path once | none needed | N/A: no new check-then-open |
| 8 | Weak tests and overclaimed evidence | each AT records red on `26091c834`; green-on-base cells are marked; rev 1 overclaimed probe B, and rev 2 re-ran it with a read-back | builder report with base SHA and red output | each mutation names the AT it turns red |
| 9 | Behavior-preserving refactor drift | Parquet-exact tables keep the Parquet handoff and the lazy child; valid outputs keep their bytes | AT-F4 lazy half, TB-1 cases, existing output goldens | M-5 |
| 10 | Frozen contract drift | section 8 names the appended reason and the new error; both additive | reason registry manifest tests; AT-F8 checks the code | M-8 |

## 10. Enumerations

### 10.1 Exit paths

Of `run_pipeline_isolated` (`_isolated_run.py:364-398`), which owns the work root and the publication:

- Staging raises (after the fix: only disk or permission errors). The `finally` aborts the publication and closes the scratch stack. Unchanged.
- Child completes: `_spawn_and_classify` publishes or returns the staged output (`_isolated_run.py:484`, `:532`). Unchanged.
- Child fails, times out or is killed: classified, staging output removed (`_isolated_run.py:569`, `:575`). The fixed-size list case now takes this exit (AT-F6).
- Worker refuses a bad manifest entry: a child failure, same exit (AT-F5).

Of `TransactionalSink` (`_transactional_sink.py:205-283`):

- `write` refused: `capture_publication_failure`, re-raise; nothing stored (AT-F8).
- `write_batches` refused on a batch: capture, best-effort close, re-raise; nothing stored (AT-F8).

### 10.2 Routes

In-memory source handoff:

| Route | Touches the handoff | Base result | After |
|---|---|---|---|
| `run_pipeline` auto, admission probe (`_transforms_admission.py:330` via `_pipeline_routing_signals.py:476`) | yes | raises (probe A) | exact handoff (AT-F1) |
| `run_pipeline` auto, transform-bearing prepared tables (`_transforms_admission.py:279`) | yes | raises (same staging) | exact handoff (AT-F3, AT-F1) |
| `run_pipeline` auto, resident-fit probe (`pipeline/_resident_fit.py:443`) | yes | swallowed, evidence lost (probe C) | exact handoff (AT-F3) |
| `execution_mode="full_frame"` | yes (routing runs first) | raises | runs (AT-F2) |
| `execution_mode="sequential"` or `"out_of_core"` | yes for a relationship job | raises for the only-list shape | eligibility unchanged; handoff exact |
| `execution_mode="stream"` | no | refused without a sink | unchanged |
| auto-chunk lane in process | no | runs | unchanged (AT-F1 runs both `auto_chunk` values) |
| `run_mask_chunked`, `run_mask_pipeline_chunked` with in-memory chunks | no | runs | unchanged |
| `run_pipeline_isolated` (public) | yes | raises in the parent | result object (AT-F6) |
| CLI | no | reads files only | n/a |

Parquet writers:

| Writer | Holds caller data | After |
|---|---|---|
| `write_output_table` (`arrow.py:114`): `_transactional_sink.py:222`, `publication/_publish.py:464`, `subset/_materialize.py:69` | yes | refuses (AT-F8, AT-F9) |
| `output_parquet_writer` (`arrow.py:120`): `_transactional_sink.py:271` | yes | refuses (AT-F8, AT-F9) |
| isolated child output stage (`StagedParquetWriter`, `_isolated_common.py:493`) | yes, through the two above | refuses inside the child; the parent sees `crashed` (AT-F6) |
| `stage_sources` (`_isolated_commit.py:165`) | yes | Parquet only for allowlisted tables (AT-F3) |
| `out_of_core/_stage.py:90` | masked key columns only; a key column is never a fixed-size list | N/A |
| `declared_casting/_stream.py:168-183` | typed CSV sources; CSV has no fixed-size list type | N/A |
| `vault/_format.py:260`, `native/_pool_quality.py:248` | engine-built string and binary tables | N/A |
| CLI `pq.write_table(output_table(...))` (`C:src/decoy/cli/io/_targets.py:584`) | CLI data comes from files, which cannot carry a readable null fixed-size list | N/A (G-2 covers the unreadable source) |

### 10.3 FK shapes

- Single, composite, self-referencing and cross-table relationships: the probe and the sequential child stage each table through the same `stage_sources`, so every FK shape gets the same exact handoff. No FK code changes.
- Children in another batch: N/A: the in-memory handoff is per call; batching is not touched.

### 10.4 Fields

- `IsolatedRunResult` (`_isolated_common.py:401`): no field added or changed. The fixed-size list case now fills `outcome` and the reason fields instead of raising.
- `ProbeResult` (`_probe.py:149`): no field added or changed. The case returns `conclusive=False` with a `reason`.
- `ParquetFixedListNullError`: `code` (the reason string) and a message naming the column.
- Manifest entry (internal): `path` (str), `format` (`"parquet"` or `"ipc"`).

### 10.5 Output surfaces

- Returned tables: the fixed-size list column comes back where it raised before.
- Parquet files: valid ones unchanged; unreadable ones are no longer published.
- Errors: the raw `ArrowNotImplementedError` from routing goes away; the output refusal is coded and value-free.
- Logs: unchanged; `resident fit probe unavailable` (`pipeline/_resident_fit.py:455`) fires less often.
- stdout, stderr, `--json`, audit, evidence, progress, help: N/A: engine library change; the CLI cannot reach it.

## 11. Reuse inventory

- `arrow_adapter.ipc_new_file` (already used by `_chunked_output_sink.py:472`) for the IPC write; `guarded` for the IPC read.
- `arrow_adapter.write_table`, `write_output_table`, `output_parquet_writer` and `LazySource`, extended in place.
- `FixedWidthWriteError` as the pattern for the new error; the F29 reason registry for its code.
- `capture_publication_failure` and the sink's abort path, unchanged.
- `tests/native/_rev9_type_catalogue.py` `CATALOGUE` as the AT-F3 corpus.
- Sentries: `tests/sentry/file_access_registry.toml`, `tests/sentry/baselines/parquet-intermediate-writers.json`, `tests/sentry/defects/test_output_metadata_choke_point.py`, `tests/sentry/test_module_size.py`.

## 12. Pre-mortem

- The allowlist names a type that Parquet does not round-trip exactly on some pyarrow version in range. The leaf set is proven on CI pyarrow by AT-F3; the remaining leaves are stable round-trips across the `pyarrow>=14` range; a leaf that fails on a later pin leaves the set.
- The null walk misses a wrapper. Rev 2 missed extension types, and `fixed_shape_tensor` with a null at row 0 would have written an unreadable file (probe G). Rev 3 unwraps extension types and covers `struct`, `list`, `large_list`, `fixed_size_list`, `map` and null parents in AT-F9. The wrappers it does not enter (dictionary, run-end-encoded, view, union) raise loudly at write (probe G, G-6), so they are not silent. A new Arrow wrapper type is the remaining risk; the follow-up is a catalogue cell per new type.
- The walk costs time on wide tables. Columns with no fixed-size list skip after one type check; `null_count` is cached by Arrow.
- A memory-mapped IPC table outlives its work root. The child process ends before the parent removes the work root, so the mapping is gone first.
- A test or helper builds a bare-string manifest. AT-F5 makes it fail loudly; section 4.2 lists the known callers.
- #770 lands first. It does not touch these files, so the rebase is textual only.

## 13. Slices and risk

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S1 | engine | adapter walk, `parquet_holds_type`, output refusal and error, reason code, IPC read, two-format handoff, worker check and loader, sentry rows, known-issue list, AT-F1 to AT-F10, changelog fragment; about 125 source lines | nothing; rebases over #770 with no overlap | R2 | T1 plus the full engine suite (serialization and reason-registry triggers) |

One slice. The handoff and the output refusal share the walk and the predicate, so splitting them would ship the walk twice. No CLI slice: the CLI cannot reach the case.

## 14. Follow-ups (not in this row)

- G-2: coded read error for a Parquet source with a null fixed-size list cell that pyarrow wrote but cannot read.
- G-4: plain-run results of the union, view, run-end-encoded and interval types after the fix.
- G-6: a coded reason for the other types Parquet cannot write at output.

### G-4 node observation

Run from the build worktree. The declared profile uses a string placeholder for the types that Parquet cannot store. The resident source carries the catalogue array. The report gives the type, null flag and outcome for each run.

```bash
VMRUN_LINUX=1 ~/bin/vm-run engine . '$PY - <<"PY"
from pathlib import Path
from tempfile import TemporaryDirectory
import pyarrow as pa
from decoy_engine.execution import run_pipeline
from tests.native._rev9_type_catalogue import CATALOGUE
from tests.unit.execution._auto_chunk_support import make_cfg, pass_col, write_source

names = ("fixed_size_list", "fixed_shape_tensor", "dense_union", "sparse_union",
         "list_view", "large_list_view", "month_day_nano_interval", "ree_string",
         "ree_string_view", "dictionary_string_view")
with TemporaryDirectory() as tmp:
    for name in names:
        if name not in CATALOGUE:
            print(name, "unavailable")
            continue
        for null in (False, True):
            array = CATALOGUE[name](null)
            table = pa.table({"x": array})
            profile = (CATALOGUE[name](False) if name == "fixed_size_list"
                       else pa.array(["profile"] * len(array)))
            path = write_source(pa.table({"x": profile}), Path(tmp) / "profile.parquet")
            cfg = make_cfg([pass_col("x")], path=path)
            try:
                output = run_pipeline(cfg, {"t": table}, engine_version="g4").outputs["t"]
            except Exception as exc:
                print(name, null, type(exc).__name__)
            else:
                print(name, null, "completed", "exact", output["x"].equals(table["x"]))
PY'
```
