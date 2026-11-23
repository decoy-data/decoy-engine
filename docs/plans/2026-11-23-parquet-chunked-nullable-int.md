Status: plan

# PARQUET-CHUNKED-NULLABLE-INT: `--chunked` keeps source types and values exact

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 2 (after Dennis R1). Roadmap row: PARQUET-CHUNKED-NULLABLE-INT (new V1 bug row). Anchors are in this repository (decoy-engine) at `origin/main` `104dfb442` unless marked `C:` (decoy CLI at `origin/main` `95362d16`, which pins `decoy-engine==0.28.3`), `#770:` (engine PR #770, UF-DOMAIN S1, head `3ad186c50`) or `P:` (decoy-platform).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `reuse-first.md`, `testing.md` (test depth, full-suite triggers), `proportionality.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `catalogs/recurring-defects.md` (11 classes), `workspace-and-vcs.md` (commit messages); vault `Decoy-Plan-Contract-and-Defect-Catalog.md` (10 classes). Engine `CLAUDE.md` file-size rule. Engine `CODEMAP.md` "Where Things Go".

Risk: R2 overall. S2 (CLI) is R2: it changes the engine entry of `--chunked`, the bytes of chunked Parquet output, the route label and the `--no-native` path. S1 (engine) is R2: frozen contract text and one error-message change; the rest is tests. S3 is R1. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis, for S1 and S2. Full suite before merge: yes for S2 (serialization and output bytes trigger) and S1 (frozen contract trigger).

## Changes from revision 1

- S1 no longer changes the plain-route output. Engine #770 already writes every untouched column from the source on the full-frame, sequential and unified routes. S1 is now test cells that run after #770, the contract text, and one value-free error fix.
- S2 now states how `--no-native` reaches `run_mask_chunked`, and keeps the `--native --chunked` refusal with corrected text.
- Section 8 names every byte and type change of `--chunked` from a new type probe, with a golden schema snapshot and a per-type matrix. `decimal256` to a CSV target is allowed.
- The route label comes from executed evidence (`compiled_kernel_executed`, `pool_select_executed`).
- Section 10.5 lists the engine codes S2 makes reachable and whether each is value-free.
- Section 5 names the interim window between S2 and the repin.

## 1. Frame

### 1.1 Symptom

`decoy run --chunked` with a Parquet source and a Parquet target exits 3 when a passthrough integer column holds a null in some chunks and none in others. The error is pyarrow's `ValueError: Table schema does not match schema used to create file` (`n: double` in the chunk, `n: int64` in the file). It fails with the CLI pinned to engine 0.28.3 and with the engine at `origin/main`.

### 1.2 What the probes showed

All probes ran through `vm-run` on the Mac, the Dell and test-6. They were not committed.

Probe 1, engine `104dfb442`. Table `id int64, n int64, d date32, s string`; `n` and `d` passthrough, `s` hashed. Chunk 0 has no nulls, chunk 1 is mixed, chunk 2 is all null. `n` holds `2**53 + 1`.

| Entry | `n` per chunk | `d` per chunk | `s` per chunk | `2**53 + 1` | CLI-style `ParquetWriter` |
|---|---|---|---|---|---|
| `run_mask_pipeline_chunked` (the CLI `--chunked` entry) | int64, double, double | date32, date32, null | string, string, null | `9007199254740992.0` (lost) | fails |
| `run_mask_chunked`, default adapter | int64, int64, int64 | date32, date32, date32 | string, string, string | exact | ok |
| `run_mask_chunked`, adapter subclass (oracle leg) | int64, int64, int64 | date32, date32, date32 | string, string, string | exact | ok |

Probe 2, engine `104dfb442`, one type per column. A Parquet file with `email` (hashed) and passthrough `int8`, `uint16`, `uint64` (holds `2**64 - 1`), `decimal128(12, 2)`, `decimal256(40, 2)`, `dictionary<int32, string>`, `date64`, `timestamp[us, UTC]`, a REQUIRED `int64`, and `float64` with NaN. Each field has `PARQUET:field_id`. Two chunks of 3 rows; chunk 1 is all null in the nullable columns.

| Column | Source as read | Oracle chunk 0 | Oracle chunk 1 | `run_mask_chunked` (both legs, both chunks) |
|---|---|---|---|---|
| `int8`, `uint16` | int8, uint16 | double | double | source type |
| `uint64` | uint64 | double | double | uint64 |
| `decimal128(12, 2)` | same | decimal128(12, 2) (only because a value needs 12 digits) | null | decimal128(12, 2) |
| `decimal256(40, 2)` | same | decimal128(3, 2) | null | decimal256(40, 2) |
| `dictionary` | int32 indices | int8 indices | int8 indices | int32 indices |
| `date64` | date32 (Parquet stores DATE as int32, so pyarrow reads date32) | date32 | null | date32 |
| `timestamp[us, UTC]` | same | same | same | same |
| REQUIRED `int64` | `not null` | nullable | nullable | `not null` |
| field metadata (`PARQUET:field_id`) | on every field | dropped | dropped | kept on passthrough fields, dropped on masked ones |
| schema key `pandas` | none | present | present | none |

The oracle then raised `ArrowInvalid: Float value 18446744073709551616.000000 was truncated converting to uint64` while it concatenated chunks. The text quotes a value. `run_mask_chunked` returned every passthrough column equal to the source on both legs.

CLI probe, `C:95362d16`. Six rows, `n` with `2**53 + 1` and one null, `d` with two nulls, `email` hashed, `--chunk-size 3`.

| Run | Parquet target | CSV target |
|---|---|---|
| plain | exit 0, `n: double`, `[10.0, 20.0, 30.0, 9007199254740992.0, None, 60.0]` | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked` | exit 3, schema mismatch | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked`, prototype calling `run_mask_chunked` | exit 0 | exit 0, row 4 `n` is `9007199254740993` |

With the prototype, `C:tests/e2e/test_run_chunked.py`, `C:tests/e2e/test_run_chunked_parquet.py` and `C:tests/e2e/test_run_chunked_post_scan.py` passed (24 tests). The prototype is not the S2 build.

### 1.3 Impact under the V1 bar

- Function break: a `--chunked` run to a Parquet target fails when a typed column is null in some chunks only, or when a decimal's inferred precision differs between chunks. A `uint64` column above `2**53` with a null fails on any target.
- Data loss: integers above `2**53` in a column with nulls are rounded on `--chunked` to CSV and on the plain run (the plain run is fixed by #770).
- Value text in an error: the `uint64` failure above quotes a value. The operator owns the data, so this is not a non-admin leak, but F31 forbids it.

### 1.4 The Dennis R2 note on CLI #397

The note was "chunked parquet->csv csv_schema_drift on nullable int/date (main ok)". Same root cause. The oracle gives a nullable integer chunk as `double` and an all-null date chunk as `null`. The CSV-WRITE-FAST branch locked the CSV writer to the first chunk's types, so the change became `csv_schema_drift`. Main's CSV writer accepts a type change between chunks on purpose (`C:src/decoy/cli/io/_targets.py:433-458`), so main did not refuse, but it still rounds. Remediation A3 removed the lock. That changed the writer. This plan fixes the cause.

## 2. Root cause with evidence

### 2.1 Chunked runs

The CLI `--chunked` path calls the engine's reference oracle, `run_mask_pipeline_chunked` (`C:src/decoy/cli/run/_execute.py:157-182`, `_masked_chunks`). Each chunk goes through the pandas adapter alone, and its output is whatever pandas inference gives for that chunk: a nullable integer becomes `float64`, an all-null column becomes `null`, a decimal gets the precision of that chunk's values, a dictionary gets the narrowest index type. The oracle applies no rule across chunks. That is its documented contract: `docs/compatibility-contract.md:926-946` gives the one-type-per-column rule to `run_mask_chunked` only.

The CLI writer opens one `pq.ParquetWriter` with the first chunk's schema (`C:src/decoy/cli/io/_targets.py:740-750`) and fails on the first chunk whose types differ.

The engine already has the fix, and the CLI does not use it. `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:600`) carries passthrough columns past pandas (`CarryPlan`, `src/decoy_engine/execution/_chunked_carry.py`) and normalizes every chunk to one schema (`build_schema_rule` and `normalize_chunk`, `src/decoy_engine/execution/native/_chunked_schema_rule.py:252` and `:336`, applied at `_chunked_entry.py:143` and `:386`). The public oracle `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:380`) returns the raw adapter outputs.

### 2.2 Plain runs (owned by #770)

The pandas adapter's output conversion `table_from_pandas_keeping_source_types` (`src/decoy_engine/execution/_fk_keys.py:521`) did not restore integer types, so the plain route also rounded. Engine #770 moves it to `#770:src/decoy_engine/execution/pipeline/_source_types.py` and writes every untouched column from the source Arrow column on the full-frame, sequential and unified routes. Its U1 cells hold `2**53 + 1` int64 and `2**64 - 1` uint64 with nulls (`#770:tests/parity/test_untouched_columns_keep_source_type.py`). The oracle runs the same adapter per chunk, so after #770 its untouched columns also keep their source type. This plan does not change that code.

### 2.3 Trace

`graphify query` on the engine graph (built 2026-11-21) found `run_mask_pipeline_chunked`, `build_schema_rule` and `normalize_chunk`. `graphify path` between them goes only through the shared `Table` type node. Grep on `104dfb442` confirmed the call sites: only `_chunked_entry.py` and `_pipeline_auto_chunk.py` call the schema rule, and the CLI calls only the oracle (`C:src/decoy/cli/run/_execute.py:175`).

### 2.4 Overlap with other rows

- UF-DOMAIN S1 (engine #770, Codex GO, full suite running) owns the plain-route fix. S1 of this plan runs after it and adds only the cells #770 does not have.
- NONFK-OOM (`origin/plan/nonfk-oom`) acts on routing. Its AT-A8 assumes `--chunked` calls `run_mask_chunked`, which becomes true with S2 (follow-up F3).
- CHUNKED-STRUCT (engine #754 merged) covers nested types only.
- FIXED-LIST-NULL has no overlap.
- RUN-STREAM C2 later deletes `_run_chunked_mask` and sends `--chunked` through `run_pipeline(execution_mode="stream")`. It is not started and waits on DELIV C2a and C2b and REL-PKG. Its parity gate gets a stricter base from S2.

No row owns the `--chunked` fix, so this plan goes ahead.

## 3. Established solutions considered

Search run: a web search for pandas and Arrow nullable integer conversion and for the ParquetWriter schema rule, and an in-codebase search for each place the engine keeps source types.

- `Table.to_pandas()` turns an integer column with nulls into `float64` by default; a `types_mapper` to `pd.Int64Dtype()` keeps it exact ([Arrow docs, pandas integration](https://arrow.apache.org/docs/python/pandas.html); [pandas PyArrow guide](https://pandas.pydata.org/docs/user_guide/pyarrow.html)). The engine uses that mapper for FK keys only (`_fk_keys.py:440-483`), on purpose, because strategies and `when:` predicates behave differently on `pd.NA`.
- `ParquetWriter` binds one schema when it opens and refuses another ([pyarrow ParquetWriter](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)). DuckDB `COPY ... TO` and Polars `sink_parquet` do the same (cited at `_chunked_output_sink.py:9-13`). So a column's type must be fixed for the whole call.
- In the codebase: the B1 carry, the schema rule, and the #770 assembler. Each keeps the source column instead of a pandas round trip.

Choice: S2 uses the existing public entry that already applies the carry and the rule, `run_mask_chunked`. No new engine machinery.

Rejected:

- A CLI writer that casts each chunk to the first schema: it cannot restore lost bits, and it cannot type a first chunk that is all null.
- Changing the public oracle further: it is the parity reference, and #770 already fixes its untouched columns.

## 4. Fix design

### 4.1 Guarantee

1. `decoy run --chunked` gives one Arrow type per column for the whole run, and each passthrough column is written as the source holds it (section 8 lists the exact changes).
2. `--no-native --chunked` runs no compiled kernel. `--native --chunked` stays refused, with true text.
3. The route label of a chunked run says what executed, from the engine's runtime evidence.
4. Masked values do not change. Hash and Faker tokens stay byte-equal.
5. After the repin to an engine release with #770, `--chunked` and the plain run give equal values and types for a Parquet source.

Non-goals (recorded, not blockers):

- Masked numeric columns that the schema rule does not pin and that come back `null` for an all-null chunk (F1).
- The `--chunked` thread count: `run_mask_chunked` keeps `native_threads=1`; `--threads` reaches `--chunked` in RUN-STREAM C2.
- Putting back the CSV type lock (F2).

### 4.2 S2 CLI design

- `_masked_chunks` (`C:src/decoy/cli/run/_execute.py:157`) calls `decoy_engine.run_mask_chunked` with the same config, chunks, table, engine version and key provider, plus `route_evidence_sink=evidence` and, under `--no-native`, `adapter=_PandasOnlyAdapter()`. `run_mask_chunked` takes no `source_schema`. The declared-read rule still holds: `prepared_sources` runs before any reader exists (lines 113 and 170).
- Disable intent. `run_mask_chunked` runs the oracle leg whenever `adapter` is neither `None` nor exactly `PandasExecutionAdapter` (`src/decoy_engine/execution/native/_chunked_entry.py:624-628`, the same text in 0.28.3), and records `reroute_reason="adapter_requested"`. The CLI defines `_PandasOnlyAdapter(PandasExecutionAdapter)` with no body, beside `_masked_chunks`, and passes it when the pre-execution gate resolved `unified_slice_enabled=False` (the value `run_pipeline_kwargs` already reads, `C:src/decoy/_native_gate.py:488-499`). `PandasExecutionAdapter` is public and frozen (`docs/frozen-surfaces.md:103`). Probe 1 shows that leg gives the same types and exact values as the native leg. Follow-up F5 replaces the subclass with an explicit engine keyword if the owner wants one.
- `--native --chunked` stays refused before the run with code `native_require_not_a_candidate`. The text changes for the chunked case only: "--native is not supported with --chunked: the chunked route does not verify compiled-kernel evidence before it publishes. Drop --native; the route label shows whether a compiled kernel ran." The text at `C:src/decoy/_native_gate.py:321-325` ("never routes through the unified slice, so it could never show compiled-kernel evidence") is false after S2. The generate-table case keeps its own text.
- Route label. `_run_chunked_mask` takes an `evidence: list` argument that `execute` owns, and passes it to each `_masked_chunks` call. The engine appends one `NativeRouteEvidence` per table at call time and sets `compiled_kernel_executed` and `pool_select_executed` on that same object as chunks run (`src/decoy_engine/execution/native/_chunk_masking.py:264-267`). After `_run_chunked_mask` returns, every stream is exhausted, so `classify_route(chunked=True, ..., chunked_evidence=evidence)` reads final values. A table ran natively when `compiled_kernel_executed or pool_select_executed`. Label: `chunked stream (native)` when every table ran natively, `chunked stream (pandas)` when none did (an empty source records `empty_input` and counts as none), `chunked stream (mixed)` otherwise. `applicable` stays `False` and `state` stays `None`, so the `--json` `native_route` shape keeps its fields and only the label text changes. The CLI reads attributes only and imports nothing from `decoy_engine.execution.native`.
- CSV allowlist: `_csv_type_allowed` (`C:src/decoy/cli/io/_targets.py:405-430`) admits `decimal256` with the same text form as `decimal128` (Arrow's decimal-to-string cast). Without it, S2 turns a `decimal256` Parquet to CSV run into a new refusal, and the plain run hits the same refusal after the #770 repin. Allowing it keeps both working.
- Sentries:
  - the declared-read sentry adds `run_mask_chunked` to `ENGINE_ENTRIES` (`C:tests/sentry/io_policy/test_declared_read_choke_point.py:94`);
  - the CSV writer guard replaces `run_mask_pipeline_chunked` with `run_mask_chunked` in `FACTORY_CALLS` (`C:tests/sentry/io_policy/test_csv_writer_guards.py:22-27`); its `_run_chunked_mask` checks (one build per table, no `next()`) do not change;
  - a new rule in the same guard file refuses any call of `run_mask_pipeline_chunked` under `C:src/decoy/`, with one seeded case per spelling: `from decoy_engine import run_mask_pipeline_chunked`, `decoy_engine.run_mask_pipeline_chunked(...)`, `from decoy_engine.execution import run_mask_pipeline_chunked`. Other spellings are V2-LOG (catalog class 5).
- Docstrings: `C:src/decoy/cli/run/__init__.py:7` and `:72`, `C:src/decoy/api.py:511`, `_run_chunked_mask` (`C:src/decoy/cli/run/_execute.py:89-104`, including the parity claim at 93-95, see 5.1), `classify_route` (`C:src/decoy/_native_gate.py:421-424`), and the `--chunked` help text "pandas chunked path".
- Size: about 60 source lines in four files (`_execute.py`, `_native_gate.py`, `_targets.py`, `run/__init__.py`), plus tests. No new public name.

### 4.3 S1 engine design (after #770)

- Test cells #770 does not have (section 6, AT-E4, AT-E7, AT-E8, AT-E10).
- `docs/compatibility-contract.md:926-946`: the "one stated exception" goes. After #770 the oracle writes untouched columns from the source, so `run_mask_chunked` and the oracle agree on values with no exception; they differ only in that the oracle types each chunk alone (an all-null masked chunk can be `null`). The builder writes the text from the AT-E4 result.
- `_safe_cast` (`src/decoy_engine/execution/native/_chunked_schema_rule.py:315-326`) puts pyarrow's message into its own (`({exc})`), and pyarrow's message quotes the value (probe 2). The fix drops `({exc})` and raises after the `except` block, so `__cause__` and `__context__` are both `None`. The message keeps the table, chunk index, column name and both type names.
- Size: about 8 source lines in one file, plus tests and contract text. No new public name, no new reason code.

### 4.4 Choke points

- Engine entry for CLI chunked masking: `_masked_chunks` is the one factory (existing guard). The new sentry refuses the oracle anywhere in CLI source. Mutation M-C3 turns the seeded cases red.
- Native intent on the chunked route: `_masked_chunks` is the one place the adapter is chosen. AT-C12 is the guard; M-C6 drops the adapter and must turn it red.
- Output assembly on the pandas routes: #770's assembler (its own sentry, `#770:tests/sentry/defects/test_output_assembly_one_path.py`). This plan adds no site.

### 4.5 Placement

No new files in `src/` in either repo.

| Test | File | Sits beside |
|---|---|---|
| AT-E4 | `tests/native/test_chunked_entry_values_schema.py` | oracle against `run_mask_chunked` schema cases |
| AT-E7, AT-E8, AT-E10 | `#770:tests/parity/test_untouched_columns_keep_source_type.py` | the U1 cells |
| AT-E9 | `tests/native/test_chunked_entry_values_schema.py` | the schema rule cases |
| AT-C1 to AT-C4, AT-C8, AT-C9 | `C:tests/e2e/test_run_chunked_parquet.py` | chunked Parquet e2e |
| AT-C6, AT-C11, AT-C12 | `C:tests/e2e/test_run_native.py` | route label and native intent cases |
| AT-C7 | `C:tests/sentry/io_policy/test_csv_writer_guards.py`, `C:tests/sentry/io_policy/test_declared_read_choke_point.py` | existing guards |
| AT-C10 | `C:tests/e2e/test_run_chunked_parquet.py` | as above |
| AT-C13 | `C:tests/unit/cli_fmt/test_csv_type_gate.py` | the allowlist rows |
| golden schema | `C:tests/e2e/fixtures/chunked_type_matrix.schema.txt` (data file next to the existing e2e fixtures) | read by AT-C9 |
| AT-R1, AT-R2 | `C:tests/e2e/test_run_chunked_parquet.py` | as above |

Changelog: engine fragment `changelog.d/parquet-chunked-nullable-int.md` (S1) and the CLI `CHANGELOG.md` (S2).

### 4.6 Design notes

No new structure. S2 changes one call to an existing public entry, chooses the leg through that entry's documented adapter rule, and reads evidence the engine already records. S1 changes one message. The label rule lives in `classify_route` only.

## 5. Slices

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S2 | CLI | `--chunked` calls `run_mask_chunked`; `--no-native` adapter; `--native` text; label from executed evidence; `decimal256` CSV; sentries; golden; docstrings; CHANGELOG | nothing; works on pin 0.28.3 | R2 | T1 plus the full CLI suite |
| S1 | engine | test cells after #770; contract text; value-free `_safe_cast` | #770 merged | R2 | T1 plus the full engine suite |
| S3 | CLI | plain against chunked parity e2e after the repin | an engine release with #770 (and S1 for AT-R3) | R1 | T1; folds into the repin PR if one is open |

S2 and S1 can be built at the same time by separate builders in separate worktrees. S2 ships first.

Slice count: 3.

### 5.1 Interim window (S2 merged, CLI still on an engine without #770)

- `--chunked` writes Parquet sources exactly (types and values). The plain run still widens nullable integers (rounded above `2**53`), infers decimal precision and narrows dictionary indexes.
- So for a Parquet source with those columns, `--chunked` and the plain run differ in types, and in CSV text above `2**53`. For a CSV source both read every column as `string`, so parity holds.
- A `when:` predicate that reads a `uint64` passthrough above `2**53` with nulls can raise `chunked_schema_mismatch` with pyarrow's value text until the CLI pins an engine with S1 (today's oracle raises a raw `ArrowInvalid` with the same text, so this is not worse).
- The window closes with S3.
- The `_run_chunked_mask` docstring (`C:src/decoy/cli/run/_execute.py:93-95`) says a chunked run "is guaranteed byte-identical to a plain run of the same config for CSV targets". S2 rewrites it: byte-identical for CSV sources; for Parquet sources, value- and type-equal once the CLI pins an engine with #770.
- Parity tests the builder checks, each with its source format recorded in the report: `C:tests/e2e/test_run_chunked.py:78` and `:111` (CSV sources, hold), `C:tests/e2e/dup_defects/test_dup_defects_e2e.py:203` (holds if its source is CSV; else it moves to S3), `C:tests/e2e/test_atomic_output.py:292` (base pin of success outputs; moves only if a chunked Parquet output with a typed column is in it).

## 6. Acceptance tests (red-first)

Fixture F is a Parquet source with:

- `id int64`, passthrough;
- `n int64`, passthrough, `[10, 20, 30, 2**53 + 1, None, 60, None, None, None]`;
- `u uint64`, passthrough, `[1, 2**63 + 5, 2**64 - 1, 7, None, 9, None, None, None]`;
- `d date32`, passthrough, nulls in rows 5 to 9;
- `email string`, hashed, rows 7 to 9 null.

At chunk size 3, chunk 0 has no nulls, chunk 1 is mixed, chunk 2 is all null in `n`, `u`, `d` and `email`.

Fixture M (the type matrix) is probe 2's file: passthrough `int8`, `uint16`, `uint64`, `decimal128(12, 2)`, `decimal256(40, 2)`, `dictionary<int32, string>`, `timestamp[us, UTC]`, REQUIRED `int64`, `float64` with NaN, each with `PARQUET:field_id`, plus a hashed `email`.

"Red on base" is the result on `C:95362d16` (S2, S3) or `104dfb442` (S1, the pre-#770 base). The builder records it before writing the fix.

Companion cells (AT-C6 native and mixed, AT-C12) need a real `decoy_engine_native`. They run with `VMRUN_LINUX=1` on the Dell in a CLI venv built like `/home/louis/decoy/venv-native-lock` (`uv sync --frozen`, then install `decoy-engine-native`). The report shows `python -c "import decoy_engine_native"` from that venv and a PASSED line for each cell. A SKIPPED line is not a pass, and the gate refuses it.

### S2 (CLI)

| AT | Behavior | Red on base |
|---|---|---|
| AT-C1 | `--chunked --chunk-size 3` on F, Parquet target: exit 0; `n int64`, `u uint64`, `d date32`, `email string`; `n`, `u`, `d` equal the source; `email` equals the plain run's tokens | exit 3 |
| AT-C2 | the same, CSV target: exit 0; row 4 `n` is `9007199254740993`, row 2 `u` is `9223372036854775813`, row 3 `u` is `18446744073709551615` | exit non-zero on `u` (raw `ArrowInvalid`), or e-notation for `n` |
| AT-C3 | chunk sizes 1, 3, 7 and 100 on F: Parquet values and types equal across sizes; CSV bytes equal across sizes | exit 3 or exit non-zero |
| AT-C4 | chunk 0 all null in `n` (F reversed): exit 0, types as AT-C1 | exit 3 |
| AT-C5 (control) | `test_run_chunked.py`, `test_run_chunked_parquet.py`, `test_run_chunked_post_scan.py` pass; the post-scan refusal keeps its exit code, reason code and text | green on base |
| AT-C6 | label: a native-admissible config with the companion gives `chunked stream (native)`; a config the native route declines (`text_redact` with `ner`) gives `chunked stream (pandas)`; two tables, one of each, give `chunked stream (mixed)`; a unit cell of `classify_route` with hand-built evidence that is admitted but has both executed flags false gives `chunked stream (pandas)`; `--json` `native_route` has `applicable: false`, `state: null` and that label | `pandas chunked stream` in every case |
| AT-C7 | sentries: each seeded oracle spelling in CLI source is refused; a seeded `run_mask_chunked` call outside the gate is refused by the declared-read sentry; the real tree passes | seeds pass; the real tree fails the new rule |
| AT-C8 (control and new cells) | an empty Parquet source writes a zero-row file with the source schema; a zero-row Parquet source with a REQUIRED column keeps `not null`; an empty CSV source publishes nothing; a failing chunk in a two-table run publishes no target; a Parquet source with a column the config does not declare is refused by the declared-read gate before any read, with its current exit code and reason | green on base, except the REQUIRED cell, which is red (oracle writes it nullable) if the zero-row file is built from the first chunk; the builder records which |
| AT-C9 | type matrix on M, Parquet target: the published file's `schema.to_string(show_schema_metadata=True)` equals the golden `chunked_type_matrix.schema.txt`; every passthrough column equals the source; no `pandas` key; no field metadata (the metadata canary stays green) | exit 3 (decimal and dictionary chunks differ) |
| AT-C10 | type matrix on M, CSV target: exit 0; text of every cell equals the golden CSV (written once from the source with the CLI CSV writer); `decimal256` cells read `1.25` and `3.50` | exit non-zero (`uint64`) |
| AT-C11 | `--native --chunked` exits with `native_require_not_a_candidate` and the new chunked text; nothing is written; the text does not say the chunked route can never run a kernel | the old text (red on the text check) |
| AT-C12 | `--no-native --chunked` with the companion on a native-admissible config: exit 0; the evidence for each table has `native_admitted` false, `reroute_reason` `adapter_requested`, and both executed flags false; the label is `chunked stream (pandas)`; output bytes equal the default run's | label is `pandas chunked stream`; the cell is red because `reroute_reason` is absent (the oracle records no evidence) |
| AT-C13 | the CSV allowlist admits `decimal256` and its text form equals `decimal128`'s for the same values; `float16` and other unlisted types stay refused | `decimal256` refused (pin at `C:tests/unit/cli_fmt/test_csv_type_gate.py:26` moves) |
| AT-C14 | a seeded marker value in a passthrough column that a `when:` reads, built to raise `chunked_passthrough_value_unrepresentable`: the marker is not in stdout, stderr or `--json` | the oracle raises raw; the marker appears (red) |

### S1 (engine, after #770)

| AT | Behavior | Red on `104dfb442` |
|---|---|---|
| AT-E4 | `run_mask_pipeline_chunked` on F's integer columns at chunk size 3: `int64` and `uint64` on every chunk, values exact, and `pa.Table.equals` to `run_mask_chunked` after `concat_tables` | `double` on chunks 1 and 2 |
| AT-E7 | full-frame `run_pipeline`: a `when:` predicate on `s` that reads nullable `n` (`n > 15`) selects the same rows as base, and `n` leaves exact | `n` leaves as `double` |
| AT-E8 | an all-null `int64` passthrough column leaves as `int64` on the full-frame and sequential routes | `double` |
| AT-E9 | `_safe_cast` on a narrowing that pyarrow refuses, with a seeded marker value: `ExecutionError` code `chunked_schema_mismatch`; the marker is not in `str(exc)`; `__cause__` and `__context__` are `None` | the marker is in the message |
| AT-E10 | `uint8` and `int8` passthrough columns with nulls, at each type's extremes, keep their type and values on the full-frame and sequential routes | `double` |

### S3 (CLI, after the repin)

| AT | Behavior | Red on 0.28.3 |
|---|---|---|
| AT-R1 | plain `decoy run` on F: Parquet keeps `n int64` and `u uint64` exactly; CSV row 4 `n` is `9007199254740993` | `double`, rounded |
| AT-R2 | on F and M, `--chunked` and the plain run give equal Parquet values and types, and equal CSV bytes | types differ |
| AT-R3 | with S1 in the pinned engine, AT-C14's pattern for `chunked_schema_mismatch`: the marker is absent | marker present |

Existing tests that pin the old behavior change only where they assert the defect. The builder lists each one with the line and the reason:

- the label pins at `C:tests/unit/test_native_gate.py:402-406`, `C:tests/e2e/test_run_native.py:505` and `C:tests/e2e/dup_defects/test_dup_defects_e2e.py:201`;
- the oracle spies at `C:tests/e2e/test_run_chunked.py:178`, `C:tests/e2e/test_run_missing_extras.py:140`, `C:tests/e2e/test_run_validate_always.py:93`, `C:tests/e2e/test_run_native.py:444` and `C:tests/e2e/test_atomic_output.py:109-120`, which move to `run_mask_chunked`;
- the `decimal256` refusal row at `C:tests/unit/cli_fmt/test_csv_type_gate.py:26`.

Any other assertion change is a stop-and-explain.

## 7. Named mutations

Each runs on the final head of its slice, and the report records that head.

| Id | Slice | Mutation | Must turn red |
|---|---|---|---|
| M-C1 | S2 | `_masked_chunks` calls `run_mask_pipeline_chunked` again | AT-C1, AT-C4, AT-C9, AT-C7 (real tree) |
| M-C2 | S2 | remove `run_mask_chunked` from `ENGINE_ENTRIES` | AT-C7 declared-read seed |
| M-C3 | S2 | delete the "no oracle in CLI source" rule | AT-C7 oracle seeds |
| M-C4 | S2 | `classify_route` returns a fixed chunked label | AT-C6 |
| M-C5 | S2 | the label reads `native_admitted` instead of the executed flags | AT-C6 unit cell (admitted, nothing executed) |
| M-C6 | S2 | `_masked_chunks` ignores `--no-native` (no adapter) | AT-C12 |
| M-C7 | S2 | the `--native --chunked` refusal is removed | AT-C11 |
| M-C8 | S2 | `decimal256` dropped from the allowlist | AT-C10, AT-C13 |
| M-C9 | S2 | the label reads only the first table's evidence | AT-C6 mixed cell |
| M-E1 | S1 | in #770's assembler, `untouched` is treated as empty | AT-E4, AT-E7, AT-E8, AT-E10 |
| M-E2 | S1 | the oracle passes `source=None` to the assembler | AT-E4 |
| M-E3 | S1 | `_safe_cast` puts `({exc})` back | AT-E9 |
| M-E4 | S1 | `_safe_cast` raises inside the `except` block | AT-E9 (`__context__`) |

## 8. Frozen contracts and byte changes

No public signature changes in either repo. No new reason code.

### 8.1 `--chunked` after S2 (CLI CHANGELOG, frozen by AT-C9 and AT-C10 goldens)

Parquet sources (from probe 2):

- Integer columns of every width, signed and unsigned, keep their source type. Before: `double` in any chunk with a null, which failed the run or rounded above `2**53`.
- Decimal columns keep their source precision and scale, `decimal256` included. Before: each chunk inferred its own precision (`decimal256(40, 2)` became `decimal128(3, 2)`), and an all-null chunk became `null`, which failed the run.
- Dictionary columns keep their source index type (`int32` stays `int32`). Before: `int8`.
- `date64`: no change reachable. pyarrow reads a Parquet DATE column as `date32`, and CSV sources are read as `string`.
- REQUIRED fields stay `not null` in the file. Before: nullable.
- Field metadata, `PARQUET:field_id` included: no change in the file. Passthrough chunks now carry it, but the CLI writes through `output_schema`, which drops all field metadata (`src/decoy_engine/safe_output/_file_metadata.py:305-307`). The metadata canary (`C:tests/e2e/cli_fmt/test_output_metadata_canary.py`) stays green.
- The `pandas` schema key is gone, because `run_mask_chunked` yields chunks without it.
- Columns the config does not declare: unreachable from the CLI. The declared-read gate refuses them before any read, so the engine's `warn` carry never applies (AT-C8).
- An all-null chunk of a typed column keeps the column type. Before: `null`, which failed the run.
- Timestamps and floats: no change.
- Byte stability for a fixed chunk size and pyarrow version still holds. The builder searches `C:tests/e2e` for sha256 pins of chunked Parquet output and lists each moved pin.

CSV targets:

- Integers above `2**53` in a column with nulls are written exactly. `uint64` above `2**53` with nulls no longer fails.
- `decimal256` columns are written (AT-C13).
- Other text does not change.

Route and intent:

- The label changes from `pandas chunked stream` to `chunked stream (native)`, `(pandas)` or `(mixed)`, in the summary and in `--json`. `applicable` and `state` keep their values.
- `--chunked` can run compiled kernels (one thread) by default. `--no-native --chunked` cannot. Values do not change.
- `--native --chunked` keeps its exit code and reason code; its text changes.

### 8.2 Engine (S1)

- `docs/compatibility-contract.md:926-946`: the "one stated exception" is removed or narrowed to match AT-E4. A Changed line in `changelog.d/parquet-chunked-nullable-int.md`.
- The `chunked_schema_mismatch` message from `_safe_cast` no longer includes pyarrow's text. Callers that match on the code are not affected.
- This lands before the 1.0 freeze.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| # | Class | Applies | How this plan handles it |
|---|---|---|---|
| D1 | Anchored validation | no | no regex or value validation added |
| D2 | Strict wire and stored types | yes (S2) | the `--json` `native_route` object keeps its fields and value types; only the label string changes (AT-C6) |
| D3 | No exception context | yes (S1) | `_safe_cast` raises outside the `except` block; AT-E9 asserts `__cause__` and `__context__` are `None` (M-E4) |
| D4 | Versioned read models | no | no persisted format changes |
| D5 | Normalized guard scanners | yes (S2) | the oracle rule covers the listed spellings with seeds (AT-C7); evasion is V2-LOG |
| D6 | No reaching into private modules | yes (S2) | the CLI imports `run_mask_chunked` and `PandasExecutionAdapter` from public `decoy_engine`; it reads evidence attributes and imports no private type |
| D7 | No hidden CI failures | yes | companion cells must show PASSED in the named venv; a skip is not a pass |
| D8 | One trust class per entry point | no | no user-named input path changes |
| D9 | Mutations on the final head | yes | section 7, head recorded |
| D10 | Allowlisted helpers are still checked | yes (S2) | `run_mask_chunked` joins `ENGINE_ENTRIES` by exact name (M-C2) |
| D11 | No raised caps | no | S1 adds about 8 lines to a 363-line module; S2 stays inside existing modules' ceilings; the builder confirms with the module-size sentries |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | `_safe_cast` message names column and types only; CLI output for reachable engine codes carries no cell value | AT-E9, AT-C14, AT-R3 with seeded markers | M-E3, M-E4 |
| 2 | Cleanup missing on an exit path | N/A: no resource owner added; the CLI publish lease in `write_chunked_output` is unchanged, and AT-C8 checks its failed-chunk exit | AT-C8 (control) | N/A: no new exit path |
| 3 | State machine and concurrency | evidence is read only after every stream is exhausted, so the executed flags are final when the label is computed | AT-C6, AT-C12 | M-C5 |
| 4 | Route parity and silent fallback | one schema rule per call (`run_mask_chunked`); the label comes from executed evidence; `--no-native` forces the oracle leg with a recorded reason | AT-C6, AT-C9, AT-C12, AT-E4 | M-C4, M-C6, M-C9 |
| 5 | Referential integrity | N/A: `--chunked` runs no relationship key check and warns about it (`C:src/decoy/cli/run/_execute.py:258`); S2 does not change which configs it accepts | AT-C5 (control) | N/A: no FK path changes |
| 6 | Untrusted producer | N/A: no child process, extension or hostile object added; the engine is the producer, and its errors pass through the existing CLI handler | AT-C14 checks that handler's output | N/A: no boundary added |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is checked or opened by new code | none needed | N/A: no path consumer added |
| 8 | Weak tests and overclaimed evidence | each AT records red on its named base; companion cells must show PASSED in the named venv | builder report with base SHA, red output and the import line | each mutation names the AT it turns red |
| 9 | Behavior-preserving refactor drift | hash and Faker tokens unchanged; CSV-source parity unchanged | AT-C1 (`email` tokens), AT-C5 | M-C1 |
| 10 | Frozen contract drift | section 8 names every change; goldens freeze the chunked schema and CSV text | AT-C9, AT-C10 goldens; `--json` shape tests | M-C8, M-C1 |

## 10. Enumerations

### 10.1 Exit paths

The S2 file owner is `write_chunked_output` (`C:src/decoy/cli/io/_targets.py:697`). Its exits do not change:

- success: published after the last chunk (`C:src/decoy/cli/io/_targets.py:748` opens the writer);
- a chunk raises: nothing published (AT-C8);
- empty source: zero-row Parquet file with the source schema, nothing for CSV (AT-C8);
- `--native --chunked` and the post-scan refusal exit before any write (AT-C11, AT-C5).

### 10.2 Routes

- `run_mask_chunked` native leg: `src/decoy_engine/execution/native/_chunked_entry.py:143` (S2 default with a companion);
- `run_mask_chunked` oracle leg: `src/decoy_engine/execution/native/_chunked_entry.py:386` (S2 without a companion, a declined config, or `--no-native`);
- public oracle `run_mask_pipeline_chunked`: `src/decoy_engine/execution/_chunked.py:380` (the CLI stops calling it; AT-E4 tests it);
- full frame, sequential, unified slice: #770's assembler (AT-E7, AT-E8, AT-E10; no change here);
- auto-chunk lane: `src/decoy_engine/execution/_pipeline_auto_chunk.py:334` (no change).

### 10.3 FK shapes

- `--chunked`: no relationship key check (`C:src/decoy/cli/run/_execute.py:258`); single-table streams only; S2 accepts the same configs.
- Plain runs: FK key handling is #770's; AT-E8 runs the sequential route with a single-column FK edge.
- Composite, self-referencing and cross-table FK: N/A for this plan: no FK code changes, and #770 covers them (`#770:tests/parity/test_untouched_columns_keep_source_type.py`).

### 10.4 Fields

- `NativeRouteEvidence.compiled_kernel_executed` and `.pool_select_executed` (`src/decoy_engine/execution/native/_dispatch.py:145` and `:156`): read by S2 for the label;
- `NativeRouteEvidence.native_admitted` and `.reroute_reason` (`src/decoy_engine/execution/native/_dispatch.py:142-143`): read by AT-C12 only;
- `RouteClassification.applicable`, `.state`, `.label` (`C:src/decoy/_native_gate.py:125`): values of the first two unchanged for chunked runs; the label changes.

### 10.5 Output surfaces

- Parquet and CSV target files: section 8.1.
- Human summary and `--json` `native_route.label`: section 8.1.
- stderr and `--json` error output: S2 makes these engine codes reachable from `--chunked`:

| Code | Reachable from CLI input | Message | Proof |
|---|---|---|---|
| `chunked_schema_mismatch` | yes: a `when:` that reads a `uint64` passthrough above `2**53` with nulls goes through pandas and fails the narrowing cast | table, chunk, column, type names, plus pyarrow's text, which quotes the value (`_chunked_schema_rule.py:321-325`) | not value-free until S1; AT-E9 and AT-R3 after S1; interim named in 5.1 |
| `chunked_passthrough_value_unrepresentable` | yes: a `when:` that reads a passthrough holding a value pandas refuses | names the column only (`src/decoy_engine/execution/_chunked_carry.py:153-161`); the cell is in `__cause__` | AT-C14 shows the CLI output holds no marker |
| `chunked_leading_null_type` | no: Parquet chunks come from one file schema, and CSV columns are read as `string` | names and types only | none needed |
| `native_chunk_schema_drift` | no: same reason | names and types only (`src/decoy_engine/execution/native/_chunk_schema.py:130-137`) | none needed |
| `chunked_route_evidence_inconsistent` | no: raised only by `aggregate_chunked_route_evidence` and the output sink, which the CLI does not call | n/a | none needed |

- Logs, audit, evidence files, progress, help: no change, apart from the `--chunked` help text "pandas chunked path".

## 11. Reuse inventory

- `run_mask_chunked` with `CarryPlan`, `build_schema_rule` and `normalize_chunk`: the S2 fix.
- Its documented adapter rule: the `--no-native` leg choice.
- `NativeRouteEvidence` runtime flags: the label.
- #770's assembler: the plain-route fix and the oracle's per-chunk fix.
- `output_schema` (`_file_metadata.py`): strips field metadata at write, so `PARQUET:field_id` does not reach files.
- CLI sentries `test_declared_read_choke_point.py` and `test_csv_writer_guards.py`: extended.
- `run_pipeline_kwargs` and the pre-execution gate: the one source of native intent.
- Reason registry: no new code.

No new machinery.

## 12. Pre-mortem

- `--no-native` still runs kernels because the adapter rule changes in a later engine. AT-C12 runs in the companion venv on every gate, and M-C6 proves it bites.
- The label says native when nothing ran. It reads executed flags after exhaustion (M-C5).
- A companion cell skips and the gate counts it. The report must show PASSED from the named venv.
- A chunked Parquet digest pin moves silently. The builder lists every moved pin, and the golden is the new reference.
- `decimal256` CSV text differs from `decimal128` for the same value. AT-C13 compares them.
- #770 changes shape before merge. S1 re-anchors on the merged head and reruns red-first on `104dfb442`.
- The interim window lasts longer than expected. It only affects Parquet sources and is named in the CHANGELOG.

## 13. Follow-ups (not in this row)

- F1: masked numeric columns that the schema rule does not pin can come back `null` for an all-null chunk. Measure which strategies can do that, then decide. V2-LOG unless a common config fails.
- F2: with S2 merged, the CLI CSV writer can lock types to the first chunk again. V2-LOG.
- F3: NONFK-OOM's probe table and the premise of its AT-A8 need a note after S2. Hand to that plan's owner.
- F4: the platform's rollback lever still calls `run_mask_pipeline_chunked` (`P:api/jobs/v2_runner.py:409`). The platform is parked.
- F5: an explicit engine keyword to force the oracle leg, to replace the CLI adapter subclass, if the owner wants it.
