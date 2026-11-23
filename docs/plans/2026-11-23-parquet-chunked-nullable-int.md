Status: plan

# PARQUET-CHUNKED-NULLABLE-INT: `--chunked` keeps source types and values exact

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 3.1 (after Codex on revision 3). Roadmap row: PARQUET-CHUNKED-NULLABLE-INT (new V1 bug row). Anchors are in this repository (decoy-engine) at `origin/main` `104dfb442` unless marked `C:` (decoy CLI at `origin/main` `95362d16`, which pins `decoy-engine==0.28.3`), `#770:` (engine PR #770, UF-DOMAIN S1, head `3ad186c50`) or `P:` (decoy-platform).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `reuse-first.md`, `testing.md` (test depth, full-suite triggers), `proportionality.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `catalogs/recurring-defects.md` (11 classes), `workspace-and-vcs.md` (commit messages); vault `Decoy-Plan-Contract-and-Defect-Catalog.md` (10 classes). Engine `CLAUDE.md` file-size rule. Engine `CODEMAP.md` "Where Things Go".

Risk: R2 overall. S2 (CLI) is R2: it changes the engine entry of `--chunked`, the bytes of chunked Parquet output, the route label, native intent on the chunked route, and user-facing text. S1 (engine) is R2: frozen contract text and one error-message change; the rest is tests. S3 is R1. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis, for S1 and S2. Full suite before merge: yes for S2 (serialization and output bytes trigger) and S1 (frozen contract trigger).

## Changes from revision 3

- The companion check scope is not widened. `static_native_eligibility` cannot see source schemas or runtime admission, so widening it could refuse a chunked job that would never touch the companion. On `--chunked`, a broken companion falls back to pandas and the label says `pandas`. 4.1, 4.2, 8.1, 10.5 and the explain text say so. AT-C16 and M-C11 now pin that difference. A fail-closed chunked check is follow-up F7.
- New AT-C17 pins, in a golden, the type of an all-null chunk under hash, truncate, string redact and deterministic categorical.
- AT-C9 and AT-C1 now pin a Parquet-bytes digest golden for fixtures M and F.
- Section 6 no longer says every AT is red first. Each control and characterization cell is marked, with the mutation that makes it meaningful (new M-C13 to M-C15 and M-E6).

## Changes from revision 2

- `--no-native --chunked` also turns off the carry, so the two legs are not equivalent. Sections 4.1, 4.2, 8.1 and 10.5 now say so. AT-C12 gains a cell with a value pandas refuses. S1 narrows the contract's stated exception instead of removing it, and pins the adapter rule with an engine test (AT-E11).
- A probe shows the `_safe_cast` path is not reached from any input tried. It is now defense in depth: AT-E9 stays, AT-R3 is dropped, and 5.1 and 10.5 are corrected.
- Section 4.2 lists all user-facing text that becomes false, with an explain-text AT (AT-C15).
- A broken companion on a native-eligible `--chunked` run now fails closed, as on the plain run (AT-C16). Withdrawn in revision 3.1.
- Section 6 lists every oracle spy and stub site. A new sentry rule refuses a test that patches the oracle, so an old stub cannot become a silent no-op.
- AT-E4 gains one cell per exception class in the contract text.
- The LOW items are folded in: L1 in 8.1, L2 in 4.2, L3 in 4.2, L4 in 4.2, L5 in AT-E10, L6 in AT-C9, AT-C10 and AT-C14, and L7 in 4.5.

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

Probe 3, on `104dfb442` and on `#770` `3ad186c50`. Two chunks of 2 rows. Each case is one passthrough column `c` beside a hashed `email`, run on three legs: the oracle, `run_mask_chunked` with the default adapter ("default"), and `run_mask_chunked` with an adapter subclass ("subclass"). "Read" means a `when:` on `email` reads `c`.

| Column `c` | Oracle on `104dfb442` | Oracle on `#770` | Default, carried | Default, read | Subclass, carried or read |
|---|---|---|---|---|---|
| `time64[ns]` with non-zero nanoseconds | raises raw `ArrowInvalid: Value 1 has non-zero nanoseconds` | same | exact | `chunked_passthrough_value_unrepresentable`, message names the column only | raises raw `ArrowInvalid`, quotes the value |
| `date32` outside pandas' range | raises raw `ValueError: year -768 is out of range` | same | exact | `chunked_passthrough_value_unrepresentable` | raises raw `ValueError`, quotes the value |
| `timestamp[ns]` holding `-2**63` | becomes null (lost) | exact | exact | not tried (closed `when:` grammar) | exact |
| `timestamp[us]` at `±2**62` | exact | exact | exact | not tried | exact |
| `list<int64>` with `2**53 + 1` | exact | exact | exact | not tried | exact |
| `uint64` at `2**64 - 1` | `double` in chunk 0, concat fails | exact | exact | not tried | exact |

Probe 3 also ran `hash`, `truncate` and `redact` over `binary` with invalid UTF-8, nullable `int64` and `large_string`, the inputs most likely to make a pinned string column fail its cast. No leg raised `chunked_schema_mismatch`. `truncate` over a nullable integer is refused earlier with `null_bearing_int_unsupported` on every leg.

CLI probe, `C:95362d16`. Six rows, `n` with `2**53 + 1` and one null, `d` with two nulls, `email` hashed, `--chunk-size 3`.

| Run | Parquet target | CSV target |
|---|---|---|
| plain | exit 0, `n: double`, `[10.0, 20.0, 30.0, 9007199254740992.0, None, 60.0]` | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked` | exit 3, schema mismatch | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked`, prototype calling `run_mask_chunked` | exit 0 | exit 0, row 4 `n` is `9007199254740993` |

With the prototype, `C:tests/e2e/test_run_chunked.py`, `C:tests/e2e/test_run_chunked_parquet.py` and `C:tests/e2e/test_run_chunked_post_scan.py` passed (24 tests). The prototype is not the S2 build.

### 1.3 Impact under the V1 bar

- Function break: a `--chunked` run to a Parquet target fails when a typed column is null in some chunks only, or when a decimal's inferred precision differs between chunks. A `uint64` column above `2**53` with a null fails on any target. A `time64[ns]` column with nanoseconds, or a date outside pandas' range, fails every `--chunked` run today.
- Data loss: integers above `2**53` in a column with nulls are rounded on `--chunked` to CSV and on the plain run (the plain run is fixed by #770). A `timestamp[ns]` of `-2**63` becomes null on the oracle before #770.
- Value text in an error: the raw pyarrow and pandas errors above quote values. The operator owns the data, so this is not a non-admin leak, but F31 forbids it.

### 1.4 The Dennis R2 note on CLI #397

The note was "chunked parquet->csv csv_schema_drift on nullable int/date (main ok)". Same root cause. The oracle gives a nullable integer chunk as `double` and an all-null date chunk as `null`. The CSV-WRITE-FAST branch locked the CSV writer to the first chunk's types, so the change became `csv_schema_drift`. Main's CSV writer accepts a type change between chunks on purpose (`C:src/decoy/cli/io/_targets.py:433-458`), so main did not refuse, but it still rounds. Remediation A3 removed the lock. That changed the writer. This plan fixes the cause.

## 2. Root cause with evidence

### 2.1 Chunked runs

The CLI `--chunked` path calls the engine's reference oracle, `run_mask_pipeline_chunked` (`C:src/decoy/cli/run/_execute.py:157-182`, `_masked_chunks`). Each chunk goes through the pandas adapter alone, and its output is whatever pandas inference gives for that chunk: a nullable integer becomes `float64`, an all-null column becomes `null`, a decimal gets the precision of that chunk's values, a dictionary gets the narrowest index type. The oracle applies no rule across chunks. That is its documented contract: `docs/compatibility-contract.md:926-946` gives the one-type-per-column rule to `run_mask_chunked` only.

The CLI writer opens one `pq.ParquetWriter` with the first chunk's schema (`C:src/decoy/cli/io/_targets.py:740-750`) and fails on the first chunk whose types differ.

The engine already has the fix, and the CLI does not use it. `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:600`) carries passthrough columns past pandas (`CarryPlan`, `src/decoy_engine/execution/_chunked_carry.py`) and normalizes every chunk to one schema (`build_schema_rule` and `normalize_chunk`, `src/decoy_engine/execution/native/_chunked_schema_rule.py:252` and `:336`, applied at `_chunked_entry.py:143` and `:386`). `normalize_chunk` takes each passthrough column from the source chunk on both legs (`_chunked_schema_rule.py:345-355`), which is why probe 1's subclass leg is exact. The public oracle `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:380`) returns the raw adapter outputs.

### 2.2 Plain runs (owned by #770)

The pandas adapter's output conversion `table_from_pandas_keeping_source_types` (`src/decoy_engine/execution/_fk_keys.py:521`) did not restore integer types, so the plain route also rounded. Engine #770 moves it to `#770:src/decoy_engine/execution/pipeline/_source_types.py` and writes every untouched column from the source Arrow column on the full-frame, sequential and unified routes. Its U1 cells hold `2**53 + 1` int64 and `2**64 - 1` uint64 with nulls (`#770:tests/parity/test_untouched_columns_keep_source_type.py`). The oracle runs the same adapter per chunk, so after #770 its untouched columns also keep their source type (probe 3). #770 fixes output only: a value pandas refuses on input still raises on the oracle (probe 3, `time64[ns]` and far dates). This plan does not change #770's code.

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

1. With default native intent, `decoy run --chunked` gives one Arrow type per column for the whole run, and each passthrough column is written as the source holds it (section 8.1 lists the exact changes). A passthrough column that a `when:` predicate or a sibling-reading strategy reads still goes through pandas; a value pandas refuses there fails with `chunked_passthrough_value_unrepresentable`, whose message names the column only.
2. `--no-native --chunked` runs no compiled kernel and carries nothing: every passthrough column goes through pandas. Types and values still match guarantee 1 for every value pandas converts, because `normalize_chunk` takes passthrough columns from the source. A value pandas refuses (probe 3: `time64[ns]` with nanoseconds, dates outside pandas' range) fails the run with a raw, uncoded pyarrow or pandas error that can quote the value. This is the behavior of every `--chunked` run today. `--no-native` is the rollback lever, so this plan records it (F6) and does not change it.
3. `--native --chunked` stays refused, with true text.
4. A present but broken companion does not refuse a `--chunked` run. The engine downgrades each table whose kernel fails to load to the oracle leg, and the label says `pandas`. This differs from the plain run, which fails closed. The difference is named in 8.1 and in `decoy explain native` (F7).
5. The route label of a chunked run says what executed, from the engine's runtime evidence.
6. Masked values do not change. Hash and Faker tokens stay byte-equal.
7. After the repin to an engine release with #770, `--chunked` and the plain run give equal values and types for a Parquet source.

Non-goals (recorded, not blockers):

- Masked numeric columns that the schema rule does not pin and that come back `null` for an all-null chunk (F1).
- The `--chunked` thread count: `run_mask_chunked` keeps `native_threads=1`; `--threads` reaches `--chunked` in RUN-STREAM C2.
- Putting back the CSV type lock (F2).
- Coded, value-free errors on the oracle leg for values pandas refuses (F6).

### 4.2 S2 CLI design

- Entry. `_masked_chunks` (`C:src/decoy/cli/run/_execute.py:157`) calls `decoy_engine.run_mask_chunked` with the same config, chunks, table, engine version and key provider, plus `route_evidence_sink=evidence` and, under `--no-native`, `adapter=_PandasOnlyAdapter()`. It still calls `source_schema_and_chunks` for the chunk iterator and the empty-Parquet schema, so `source_schema_and_chunks` stays in the guard's `FACTORY_CALLS`. `run_mask_chunked` takes no `source_schema`. The declared-read rule still holds: `prepared_sources` runs before any reader exists (lines 113 and 170).
- Disable intent. The native route downgrades to the oracle leg with `reroute_reason="adapter_requested"` when `type(adapter) is not PandasExecutionAdapter` (`src/decoy_engine/execution/native/_dispatch.py:453-463`). The same exact-type test turns the carry off (`is_stock_adapter`, `src/decoy_engine/execution/_chunked_carry.py:52-57`), so on that leg every passthrough column goes through pandas, and the coded diagnosis returns early (`_chunked_carry.py:113` and `:134`). The CLI defines `_PandasOnlyAdapter(PandasExecutionAdapter)` with no body, beside `_masked_chunks`, and passes it when the pre-execution gate resolved `unified_slice_enabled=False` (the value `run_pipeline_kwargs` reads, `C:src/decoy/_native_gate.py:488-499`). `PandasExecutionAdapter` is public and frozen (`docs/frozen-surfaces.md:103`). S1 pins this rule in the contract with an engine test (AT-E11), so the CLI does not rely on unpinned behavior. Follow-up F5 offers an explicit engine keyword in its place.
- `--native --chunked` stays refused before the run with code `native_require_not_a_candidate`. The text changes for the chunked case only: "--native is not supported with --chunked: the chunked route does not verify compiled-kernel evidence before it publishes. Drop --native; the route label shows whether a compiled kernel ran." The text at `C:src/decoy/_native_gate.py:321-325` ("never routes through the unified slice, so it could never show compiled-kernel evidence") is false after S2. The generate-table case keeps its own text.
- Broken companion. With default intent, `pre_execution_gate` classifies the companion only for a unified-slice candidate (`C:src/decoy/_native_gate.py:363-364`), and a chunked run is never one. S2 keeps that scope. After S2 a chunked run can use compiled kernels, and the engine downgrades a table to the oracle leg when a kernel fails to load (`src/decoy_engine/execution/native/_dispatch.py:563-600`), so the label says `pandas`. A fail-closed check here would need runtime admission evidence: `static_native_eligibility` reads the config only (`C:src/decoy/_native_gate.py:203`), and chunked admission can still decline columns it does not cover, so a config-shape scope could refuse a chunked job that would never touch the companion. That is a function break under the V1 bar. The difference is named in 8.1 and in the explain text, pinned by AT-C16, and recorded as F7.
- Route label. `_run_chunked_mask` takes an `evidence: list` argument that `execute` owns, and passes it to each `_masked_chunks` call. The engine appends one `NativeRouteEvidence` per table at call time and sets `compiled_kernel_executed` and `pool_select_executed` on that same object as chunks run (`src/decoy_engine/execution/native/_chunk_masking.py:264-267`). After `_run_chunked_mask` returns, every stream is exhausted, so `classify_route(chunked=True, ..., chunked_evidence=evidence)` reads final values. A table ran natively when `compiled_kernel_executed or pool_select_executed`. Tables whose evidence says `reroute_reason == "empty_input"` are left out. Label: `chunked stream (native)` when every remaining table ran natively, `chunked stream (pandas)` when none did or none remain, `chunked stream (mixed)` otherwise. So one empty table and one native table give `native`. `applicable` stays `False` and `state` stays `None`, so the `--json` `native_route` shape keeps its fields and only the label text changes. The CLI reads attributes only and imports nothing from `decoy_engine.execution.native`.
- Why raw evidence and not `route_summary`: `route_summary` reads an `ExecutionResult.quality_metrics`, and a chunked run has one per chunk only through `chunk_result_sink`, which keeps every chunk's result in a list. That grows with the stream and breaks the bounded-memory promise of `--chunked`. `route_evidence_sink` holds one small object per table.
- CSV allowlist: `_csv_type_allowed` (`C:src/decoy/cli/io/_targets.py:405-430`) admits `decimal256` with the same text form as `decimal128` (Arrow's decimal-to-string cast). Without it, S2 turns a `decimal256` Parquet to CSV run into a new refusal, and the plain run hits the same refusal after the #770 repin.
- Sentries:
  - the declared-read sentry adds `run_mask_chunked` to `ENGINE_ENTRIES` (`C:tests/sentry/io_policy/test_declared_read_choke_point.py:94`);
  - the same file gets a new rule: no call of `run_mask_pipeline_chunked` under `C:src/decoy/`, one seeded case per spelling (`from decoy_engine import run_mask_pipeline_chunked`, `decoy_engine.run_mask_pipeline_chunked(...)`, `from decoy_engine.execution import run_mask_pipeline_chunked`); other spellings are V2-LOG (catalog class 5);
  - the same rule refuses a test under `C:tests/` that names `run_mask_pipeline_chunked` in a `monkeypatch.setattr` or assigns it, so a stub the CLI never calls cannot pass silently; the engine's own oracle is not under `C:tests/`;
  - the CSV writer guard replaces `run_mask_pipeline_chunked` with `run_mask_chunked` in `FACTORY_CALLS` (`C:tests/sentry/io_policy/test_csv_writer_guards.py:22-27`) and moves its seed at `:113`; its `_run_chunked_mask` checks (one build per table, no `next()`) do not change.
- User-facing text that becomes false, each rewritten by S2 and checked by AT-C15:
  - `decoy explain chunked`, `C:src/decoy/cli/explain.py:302`: "Chunked output is byte-identical to a plain run for CSV targets." New text: identical for CSV sources; for Parquet sources, value- and type-equal once the CLI pins an engine with #770.
  - `decoy explain native`, `C:src/decoy/cli/explain.py:335`: "Refuses up front on --chunked" stays true; `:343-344` "--no-native Force the legacy pandas adapter" is now true for `--chunked` too; `:346-350` "A present-but-broken companion ... refuses closed" gets a sentence that on `--chunked` a broken companion falls back to pandas and the route label says `pandas`.
  - `decoy explain substrate`, `C:src/decoy/cli/explain.py:362-377`: "pandas is the only masking substrate ... for both plain and --chunked runs" and the summary line become false. New text names the native chunked route.
  - `decoy run --help` and `docs/cli-reference.md:161`: "(pandas chunked path)" and "(Masking uses the pandas substrate. See: decoy explain substrate.)" (`C:src/decoy/cli/run/__init__.py:72-73`).
  - Docstrings: `C:src/decoy/cli/run/__init__.py:7`, `C:src/decoy/api.py:511`, `_ChunkedQuarantineError` (`C:src/decoy/cli/run/_execute.py:56`, names the oracle), `_ChunkedReportFlagError` (`:76`, "returns no `ExecutionResult`" stays true, and the entry name is updated), `_run_chunked_mask` (`:89-104`, including the parity claim at 93-95, see 5.1), and `classify_route` (`C:src/decoy/_native_gate.py:421-424`).
- Size: about 80 source lines in five files (`_execute.py`, `_native_gate.py`, `_targets.py`, `run/__init__.py`, `explain.py`), plus `docs/cli-reference.md` and tests. No new public name.

### 4.3 S1 engine design (after #770)

- Test cells #770 does not have (section 6: AT-E4, AT-E7, AT-E8, AT-E10, AT-E11).
- `docs/compatibility-contract.md:926-946`: the stated exception is narrowed, not removed. After #770 the oracle writes untouched columns from the source, so values the oracle used to round (nullable integers above `2**53`, a `timestamp[ns]` of `-2**63`) now agree. The text keeps:
  - values pandas refuses to convert (probe 3: `time64[ns]` with nanoseconds, dates outside pandas' range) raise on the oracle and come back exact on the stock-adapter path;
  - a read passthrough column that pandas refuses raises `chunked_passthrough_value_unrepresentable`;
  - an adapter that is not exactly `PandasExecutionAdapter` runs the oracle leg with `reroute_reason="adapter_requested"` and carries nothing (new sentence, pinned by AT-E11);
  - the oracle types each chunk alone, so an all-null masked chunk can be `null` there.
  The builder writes the final text from the AT-E4 results.
- `_safe_cast` (`src/decoy_engine/execution/native/_chunked_schema_rule.py:315-326`) puts pyarrow's message into its own (`({exc})`). It is called only for pinned string columns (`:356-359`), and probe 3 found no input that reaches it. The fix is defense in depth: drop `({exc})` and raise after the `except` block, so `__cause__` and `__context__` are both `None`. The message keeps the table, chunk index, column name and both type names.
- Size: about 8 source lines in one 363-line module, plus tests and contract text. No new public name, no new reason code.

### 4.4 Choke points

- Engine entry for CLI chunked masking: `_masked_chunks` is the one factory (existing guard). The new rule refuses the oracle anywhere in CLI source and in CLI test patches. M-C3 turns the seeded cases red.
- Native intent on the chunked route: `_masked_chunks` is the one place the adapter is chosen; `pre_execution_gate` is the one place the companion is classified. AT-C12 is the guard for the adapter (M-C6). AT-C16 pins that the companion check does not reach chunked runs (M-C11).
- Output assembly on the pandas routes: #770's assembler (its own sentry, `#770:tests/sentry/defects/test_output_assembly_one_path.py`). This plan adds no site.

### 4.5 Placement

No new files in `src/` in either repo.

| Test | File | Sits beside |
|---|---|---|
| AT-E4, AT-E9, AT-E11 | `tests/native/test_chunked_entry_values_schema.py` | oracle against `run_mask_chunked` schema cases |
| AT-E7, AT-E8, AT-E10 | `#770:tests/parity/test_untouched_columns_keep_source_type.py` | the U1 cells |
| AT-C1 to AT-C4, AT-C8, AT-C9, AT-C10, AT-C14, AT-C17 | `C:tests/e2e/test_run_chunked_parquet.py` | chunked Parquet e2e |
| AT-C6 e2e cells, AT-C11, AT-C12, AT-C16 e2e cell | `C:tests/e2e/test_run_native.py` | route label and native intent cases |
| AT-C6 `classify_route` unit cells, AT-C16 unit cell | `C:tests/unit/test_native_gate.py` | the existing `classify_route` and `pre_execution_gate` cases |
| AT-C7 | `C:tests/sentry/io_policy/test_declared_read_choke_point.py` (engine-entry rules), `C:tests/sentry/io_policy/test_csv_writer_guards.py` (factory) | existing guards |
| AT-C13 | `C:tests/unit/cli_fmt/test_csv_type_gate.py` | the allowlist rows |
| AT-C15 | the existing explain-topic tests (`git grep -l "explain" C:tests/e2e`; the builder names the file) | topic text cases |
| goldens | `C:tests/e2e/fixtures/chunked_type_matrix.schema.txt`, `chunked_all_null_masked.schema.txt`, `chunked_parquet_digests.txt` (data files next to the existing e2e fixtures) | read by AT-C1, AT-C9, AT-C17 |
| AT-R1, AT-R2 | `C:tests/e2e/test_run_chunked_parquet.py` | as above |

Changelog: engine fragment `changelog.d/parquet-chunked-nullable-int.md` (S1) and the CLI `CHANGELOG.md` (S2).

### 4.6 Design notes

No new structure. S2 changes one call to an existing public entry, chooses the leg through that entry's adapter rule (pinned by S1), and reads evidence the engine already records. S1 changes one message. The label rule lives in `classify_route` only.

## 5. Slices

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S2 | CLI | `--chunked` calls `run_mask_chunked`; `--no-native` adapter; `--native` text; label from executed evidence; `decimal256` CSV; sentries; goldens; user-facing text; CHANGELOG | nothing; works on pin 0.28.3 | R2 | T1 plus the full CLI suite |
| S1 | engine | test cells after #770; narrowed contract text with the adapter rule; value-free `_safe_cast` | #770 merged | R2 | T1 plus the full engine suite |
| S3 | CLI | plain against chunked parity e2e after the repin | an engine release with #770 | R1 | T1; folds into the repin PR if one is open |

S2 and S1 can be built at the same time by separate builders in separate worktrees. S2 ships first.

Slice count: 3.

### 5.1 Interim window (S2 merged, CLI still on an engine without #770)

- `--chunked` writes Parquet sources exactly (types and values). The plain run still widens nullable integers (rounded above `2**53`), infers decimal precision, narrows dictionary indexes and turns a `timestamp[ns]` of `-2**63` into null.
- So for a Parquet source with those columns, `--chunked` and the plain run differ in types, and in CSV text above `2**53`. For a CSV source both read every column as `string`, so parity holds.
- Values pandas refuses (probe 3) are exact on the engine's default `--chunked` leg and fail on the plain run and on `--no-native --chunked`, in the window and after it, until F6. Through `decoy run` the preflight capacity estimate profiles a 10,000-row pandas sample and ends the run with exit 1 ("source not parsed") on every leg when that sample holds such a value. A bad value after the sample reaches the engine: a default `--chunked` run publishes it exactly, a run whose `when:` reads the column exits 3 with `chunked_passthrough_value_unrepresentable`, and `--no-native` exits 3 with the same code. The CLI replaces the engine's cell-quoting errors with a fresh value-free error with no cause (a coded error chains the pandas error, which `--verbose` printed). Row PREFLIGHT-ARROW-PROFILE tracks that. S2 pins the CLI refusal and exercises the engine half through `_run_chunked_mask` (amended after the S2 build, PR #399).
- The window closes with S3.
- The `_run_chunked_mask` docstring (`C:src/decoy/cli/run/_execute.py:93-95`) says a chunked run "is guaranteed byte-identical to a plain run of the same config for CSV targets". S2 rewrites it as in `decoy explain chunked` (4.2).
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

Fixture R is a Parquet source with a hashed `email` and a passthrough `time64[ns]` column holding a value with non-zero nanoseconds, plus a second file with a passthrough `date32` column holding a date outside pandas' range.

"Red on base" is the result on `C:95362d16` (S2, S3) or `104dfb442` (S1, the pre-#770 base). The builder records it before writing the fix. Not every cell is red on base. A cell marked control or characterization is green on base on purpose: it pins behavior the fix must keep. Each one names the mutation in section 7 that turns it red, and that mutation result is its evidence. A cell with no such mutation is reported as a characterization only and does not count as evidence for the fix.

Companion cells (AT-C6 native and mixed, AT-C12 companion cell) need a real `decoy_engine_native`. They run with `VMRUN_LINUX=1` on the Dell in a CLI venv built like `/home/louis/decoy/venv-native-lock` (`uv sync --frozen`, then install `decoy-engine-native`). The report shows `python -c "import decoy_engine_native"` from that venv and a PASSED line for each cell. A SKIPPED line is not a pass, and the gate refuses it.

### S2 (CLI)

| AT | Behavior | Red on base |
|---|---|---|
| AT-C1 | `--chunked --chunk-size 3` on F, Parquet target: exit 0; `n int64`, `u uint64`, `d date32`, `email string`; `n`, `u`, `d` equal the source; `email` equals the plain run's tokens; the sha256 of the published file equals the F entry in `chunked_parquet_digests.txt`, which also records the pyarrow version | exit 3 |
| AT-C2 | the same, CSV target: exit 0; row 4 `n` is `9007199254740993`, row 2 `u` is `9223372036854775813`, row 3 `u` is `18446744073709551615` | exit non-zero on `u` (raw `ArrowInvalid`), or e-notation for `n` |
| AT-C3 | chunk sizes 1, 3, 7 and 100 on F: Parquet values and types equal across sizes; CSV bytes equal across sizes | exit 3 or exit non-zero |
| AT-C4 | chunk 0 all null in `n` (F reversed): exit 0, types as AT-C1 | exit 3 |
| AT-C5 (control) | `test_run_chunked.py`, `test_run_chunked_parquet.py`, `test_run_chunked_post_scan.py` pass; the post-scan refusal keeps its exit code, reason code and text | green on base |
| AT-C6 | label, e2e: a native-admissible config with the companion gives `chunked stream (native)`; a config the native route declines (`text_redact` with `ner`) gives `chunked stream (pandas)`; two tables, one of each, give `chunked stream (mixed)`; `--json` `native_route` has `applicable: false`, `state: null` and that label. Unit, `classify_route` with hand-built evidence: admitted but both executed flags false gives `pandas`; one `empty_input` table and one native table give `native`; only `empty_input` tables give `pandas` | `pandas chunked stream` in every case |
| AT-C7 | sentries: each seeded oracle spelling in CLI source is refused; a seeded `monkeypatch.setattr(decoy_engine, "run_mask_pipeline_chunked", ...)` in a test is refused; a seeded `run_mask_chunked` call outside the gate is refused; the real trees pass | seeds pass; the real trees fail the new rule |
| AT-C8 (controls and one new cell) | an empty Parquet source writes a zero-row file with the source schema; a zero-row Parquet source with a REQUIRED column keeps `not null`; a header-only CSV source publishes a header-only file (base behavior, found at build; a stream that yields no table publishes nothing, covered by `test_atomic_output.py`); a failing chunk in a two-table run publishes no target; a Parquet source with a column the config does not declare is refused by the declared-read gate before any read, with its current exit code and reason | control, green on base: empty Parquet (M-C13), empty CSV (M-C13), failing chunk (M-C14), undeclared column (M-C15). The REQUIRED cell is red if the zero-row file is built from an oracle chunk, else control under M-C13; the builder records which |
| AT-C9 | type matrix on M, Parquet target: the published file's `schema.to_string(show_schema_metadata=True)` equals the golden `chunked_type_matrix.schema.txt`; the file's sha256 equals the M entry in `chunked_parquet_digests.txt`; every passthrough column equals the source; no `pandas` key; no field metadata (the metadata canary stays green). At the gate the reviewer also checks the golden against `output_schema(source schema)` with `email` as `string`, so the golden cannot freeze a wrong type | exit 3 (decimal and dictionary chunks differ) |
| AT-C10 | type matrix on M, CSV target: exit 0. Every passthrough cell's text equals the golden CSV written once from the source with the CLI CSV writer. The hashed `email` column equals the plain run's `email` column text (tokens, not source values). `decimal256` cells read `1.25` and `3.50` | exit non-zero (`uint64`) |
| AT-C11 | `--native --chunked` exits with `native_require_not_a_candidate` and the new chunked text; nothing is written; the text does not say the chunked route can never run a kernel | the old text (red on the text check) |
| AT-C12 | `--no-native --chunked`. Companion cell, native-admissible config: exit 0; each table's evidence has `native_admitted` false, `reroute_reason` `adapter_requested` and both executed flags false; the label is `chunked stream (pandas)`; output bytes equal the default run's. Refused-value cell, fixture R: the default run exits 0 with the column exact; the `--no-native` run exits non-zero, and the report records its exit code and error class (F6 tracks the uncoded error) | companion cell: label is `pandas chunked stream` and no evidence exists; refused-value cell: both runs fail on base, so the default-leg half is red |
| AT-C13 | the CSV allowlist admits `decimal256` and its text form equals `decimal128`'s for the same values; `float16` and other unlisted types stay refused | `decimal256` refused (pin at `C:tests/unit/cli_fmt/test_csv_type_gate.py:26` moves) |
| AT-C14 (amended after the S2 build: the CLI preflight refuses fixture R first, so the coded error is checked through `_run_chunked_mask`, and the CLI refusal is pinned separately) | fixture R with a `when:` on `email` that reads the refused column, carrying a seeded marker in that column: exit non-zero with `chunked_passthrough_value_unrepresentable`; the marker is not in stdout, stderr or `--json`, at default verbosity and with `--verbose` | the oracle raises raw; the marker appears (red) |
| AT-C15 | `decoy explain chunked`, `native` and `substrate`, and `decoy run --help`: no sentence says pandas is the only substrate for `--chunked`, no "pandas chunked path", no unqualified "byte-identical to a plain run"; each says `--chunked` can use compiled kernels and names the label | the old text (red) |
| AT-C16 | broken companion on `--chunked`: with `_probe_status` returning present but not ok, `pre_execution_gate` does not raise for a chunked config (unit cell); e2e cell with a companion stub whose kernel load fails: exit 0, the label is `chunked stream (pandas)`, output equals the `--no-native` run; `decoy explain native` text names this fallback | control for the gate cell, green on base (M-C11); the label and text halves are red (old label, old text) |
| AT-C17 | all-null masked chunks: a Parquet source whose chunk 1 is all null in columns masked by hash, truncate, string redact and deterministic categorical; Parquet target: exit 0; the published schema equals the golden `chunked_all_null_masked.schema.txt` (each column `string`) | exit 3 (`null` chunk) |

### S1 (engine, after #770)

| AT | Behavior | Red on `104dfb442` |
|---|---|---|
| AT-E4 | `run_mask_pipeline_chunked` against `run_mask_chunked` at chunk size 2, one cell per contract exception class: (a) F's `n` and `u`: oracle `int64` and `uint64` on every chunk, values exact, `pa.Table.equals` after `concat_tables`; (b) `timestamp[ns]` holding `-2**63`: equal; (c) `list<int64>` with `2**53 + 1`: equal; (d) `time64[ns]` with nanoseconds: oracle raises, `run_mask_chunked` exact; (e) `date32` outside pandas' range: oracle raises, `run_mask_chunked` exact | (a) red: `double`; (b) red: null; (c) characterization, green on base, no mutation, kept only to back the contract text; (d) and (e) control, green on base and after #770, made meaningful by M-E6 |
| AT-E7 | full-frame `run_pipeline`: a `when:` predicate on `s` that reads nullable `n` (`n > 15`) selects the same rows as base, and `n` leaves exact | `n` leaves as `double` |
| AT-E8 | an all-null `int64` passthrough column leaves as `int64` on the full-frame and sequential routes | `double` |
| AT-E9 | `_safe_cast` called directly on a narrowing that pyarrow refuses, with a seeded marker value: `ExecutionError` code `chunked_schema_mismatch`; the marker is not in `str(exc)`; `__cause__` and `__context__` are `None` | the marker is in the message |
| AT-E10 | a `uint8` passthrough column with nulls, at `0` and `255`, keeps its type and values on the full-frame and sequential routes (#770's U1 already covers `int8`) | `double` |
| AT-E11 | `run_mask_chunked` with a subclass of `PandasExecutionAdapter` and a native-admissible config: evidence has `native_admitted` false and `reroute_reason` `adapter_requested`; `quality_metrics["chunked_route"]["pandas_read_passthrough"]` lists nothing carried (the carry is off) | green on base (pins existing behavior); red under M-E5 |

### S3 (CLI, after the repin)

| AT | Behavior | Red on 0.28.3 |
|---|---|---|
| AT-R1 | plain `decoy run` on F: Parquet keeps `n int64` and `u uint64` exactly; CSV row 4 `n` is `9007199254740993` | `double`, rounded |
| AT-R2 | on F and M, `--chunked` and the plain run give equal Parquet values and types, and equal CSV bytes | types differ |

Existing tests that pin the old behavior change only where they assert the defect. Every oracle spy and stub moves to `run_mask_chunked` with its assertion unchanged; an `iter(())` stub left on the oracle would become a silent no-op, and AT-C7's test-patch rule refuses it. The builder lists each one with the line:

- spies and stubs: `C:tests/e2e/test_run_chunked.py:178`; `C:tests/e2e/test_atomic_output.py:109-120` and `:211`; `C:tests/e2e/test_source_csv_dialect.py:215-218`; `C:tests/e2e/run_progress/test_run_progress_events.py:5`, `:179-193`; `C:tests/e2e/first_user/test_items_run.py:124`; `C:tests/e2e/test_run_validate_always.py:93`; `C:tests/e2e/test_run_native.py:444-446`; `C:tests/e2e/cli_fmt/test_csv_run_wide_preflight.py:121-137` and `:208-215`; `C:tests/e2e/test_run_missing_extras.py:123` and `:140`; `C:tests/e2e/project_layout/test_run_placement.py:272`;
- sentry entries and seeds: `C:tests/sentry/io_policy/test_csv_writer_guards.py:26` and `:113`, `C:tests/sentry/io_policy/test_declared_read_choke_point.py:94`;
- label pins: `C:tests/unit/test_native_gate.py:402-406`, `C:tests/e2e/test_run_native.py:505`, `C:tests/e2e/dup_defects/test_dup_defects_e2e.py:201`;
- the `decimal256` refusal row at `C:tests/unit/cli_fmt/test_csv_type_gate.py:26`.

A `git grep run_mask_pipeline_chunked` over `C:src` and `C:tests` on the S2 head returns only the sentry's own rule and seeds. Any other assertion change is a stop-and-explain.

## 7. Named mutations

Each runs on the final head of its slice, and the report records that head.

| Id | Slice | Mutation | Must turn red |
|---|---|---|---|
| M-C1 | S2 | `_masked_chunks` calls `run_mask_pipeline_chunked` again | AT-C1, AT-C4, AT-C9, AT-C7 (real tree) |
| M-C2 | S2 | remove `run_mask_chunked` from `ENGINE_ENTRIES` | AT-C7 declared-read seed |
| M-C3 | S2 | delete the "no oracle in CLI source or test patches" rule | AT-C7 oracle seeds |
| M-C4 | S2 | `classify_route` returns a fixed chunked label | AT-C6 |
| M-C5 | S2 | the label reads `native_admitted` instead of the executed flags | AT-C6 unit cell (admitted, nothing executed) |
| M-C6 | S2 | `_masked_chunks` ignores `--no-native` (no adapter) | AT-C12 companion cell |
| M-C7 | S2 | the `--native --chunked` refusal is removed | AT-C11 |
| M-C8 | S2 | `decimal256` dropped from the allowlist | AT-C10, AT-C13 |
| M-C9 | S2 | the label reads only the first table's evidence | AT-C6 mixed cell |
| M-C10 | S2 | the old `substrate` topic text is restored | AT-C15 |
| M-C11 | S2 | the companion check scope adds `or chunked` | AT-C16 gate cell |
| M-C13 | S2 | `write_chunked_output` writes nothing for an empty source | AT-C8 empty cells |
| M-C14 | S2 | the publish lease commits when a chunk raises | AT-C8 failing-chunk cell |
| M-C15 | S2 | `_masked_chunks` skips `prepared_sources` | the ordering sentry `test_every_reader_is_gated_first` only: `_run_chunked_mask` gates first too, so the AT-C8 undeclared-column cell stays green (found at build) |
| M-C12 | S2 | `empty_input` tables are counted as pandas | AT-C6 unit cell (one empty, one native) |
| M-E1 | S1 | in #770's assembler, `untouched` is treated as empty | AT-E4 (a), AT-E7, AT-E8, AT-E10 |
| M-E2 | S1 | the oracle passes `source=None` to the assembler | AT-E4 (a) and (b) |
| M-E3 | S1 | `_safe_cast` puts `({exc})` back | AT-E9 |
| M-E4 | S1 | `_safe_cast` raises inside the `except` block | AT-E9 (`__context__`) |
| M-E5 | S1 | `_dispatch.py:461` uses `isinstance` instead of the exact type test | AT-E11 |
| M-E6 | S1 | `is_stock_adapter` returns `False` for the stock adapter (carry off) | AT-E4 (d) and (e) |

## 8. Frozen contracts and byte changes

No public signature changes in either repo. No new reason code.

### 8.1 `--chunked` after S2 (CLI CHANGELOG, frozen by AT-C9 and AT-C10 goldens)

Parquet sources, default native intent (from probes 2 and 3):

- Integer columns of every width, signed and unsigned, keep their source type. Before: `double` in any chunk with a null, which failed the run or rounded above `2**53`.
- Decimal columns keep their source precision and scale, `decimal256` included. Before: each chunk inferred its own precision (`decimal256(40, 2)` became `decimal128(3, 2)`), and an all-null chunk became `null`, which failed the run.
- Dictionary columns keep their source index type (`int32` stays `int32`). Before: `int8`.
- `date64`: no change reachable. pyarrow reads a Parquet DATE column as `date32`, and CSV sources are read as `string`.
- REQUIRED fields stay `not null` in the file. Before: nullable.
- Field metadata, `PARQUET:field_id` included: no change in the file. Passthrough chunks now carry it, but the CLI writes through `output_schema`, which drops all field metadata (`src/decoy_engine/safe_output/_file_metadata.py:305-307`). The metadata canary (`C:tests/e2e/cli_fmt/test_output_metadata_canary.py`) stays green.
- The `pandas` schema key is gone, because `run_mask_chunked` yields chunks without it.
- Columns the config does not declare: unreachable from the CLI. The declared-read gate refuses them before any read, so the engine's `warn` carry never applies (AT-C8).
- An all-null chunk of a typed passthrough column keeps the column type. Before: `null`, which failed the run.
- Masked columns pinned to `string` (hash, truncate, string redact, native-admissible deterministic categorical) leave as `string` on every chunk, an empty or all-null chunk included. Before: `null` for such a chunk, which failed a Parquet run. Pinned by the AT-C17 golden.
- Values pandas refuses (`time64[ns]` with nanoseconds, dates outside pandas' range) are exact on the engine route when nothing reads the column. `decoy run` still refuses such a source at preflight (row PREFLIGHT-ARROW-PROFILE), so a user sees no change until that row lands. Before: every run failed with a raw error.
- Timestamps and floats: no change.
- Byte stability for a fixed chunk size and pyarrow version still holds. It is pinned by a new digest golden, `chunked_parquet_digests.txt`, with the sha256 of the published file for fixtures F and M at chunk size 3 and the pyarrow version (AT-C1, AT-C9). A pyarrow bump that moves a digest updates the golden in the same PR, with the reason. The builder also lists any existing chunked Parquet sha256 pin that moves.

`--no-native --chunked`: the same types and values for every value pandas converts. A value pandas refuses fails the run with a raw, uncoded error that can quote the value, as every `--chunked` run does today (guarantee 2, F6).

CSV targets:

- Integers above `2**53` in a column with nulls are written exactly. `uint64` above `2**53` with nulls no longer fails.
- `decimal256` columns are written (AT-C13).
- Other text does not change.

Route and intent:

- The label changes from `pandas chunked stream` to `chunked stream (native)`, `(pandas)` or `(mixed)`, in the summary and in `--json`. `applicable` and `state` keep their values.
- `--chunked` can run compiled kernels (one thread) by default. `--no-native --chunked` cannot. Values do not change.
- `--native --chunked` keeps its exit code and reason code; its text changes.
- A present but broken companion does not refuse a `--chunked` run. Each table whose kernel fails to load runs on the oracle leg, and the label says `pandas`. The plain run fails closed in the same case. `decoy explain native` names the difference (AT-C16, F7).

### 8.2 Engine (S1)

- `docs/compatibility-contract.md:926-946`: the stated exception is narrowed as in 4.3, and the adapter rule is pinned. A Changed line in `changelog.d/parquet-chunked-nullable-int.md`.
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
| D5 | Normalized guard scanners | yes (S2) | the oracle rule covers the listed spellings and test patches with seeds (AT-C7); evasion is V2-LOG |
| D6 | No reaching into private modules | yes (S2) | the CLI imports `run_mask_chunked` and `PandasExecutionAdapter` from public `decoy_engine`; it reads evidence attributes and imports no private type |
| D7 | No hidden CI failures | yes | companion cells must show PASSED in the named venv; a skip is not a pass |
| D8 | One trust class per entry point | no | no user-named input path changes |
| D9 | Mutations on the final head | yes | section 7, head recorded |
| D10 | Allowlisted helpers are still checked | yes (S2) | `run_mask_chunked` joins `ENGINE_ENTRIES` by exact name (M-C2) |
| D11 | No raised caps | no | S1 adds about 8 lines to a 363-line module; S2 stays inside existing modules' ceilings; the builder confirms with the module-size sentries |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | `_safe_cast` message names column and types only; CLI output for the reachable coded error carries no cell value; the uncoded `--no-native` path is recorded as F6 | AT-E9, AT-C14 with seeded markers; AT-C12 records the `--no-native` error class | M-E3, M-E4 |
| 2 | Cleanup missing on an exit path | N/A: no resource owner added; the CLI publish lease in `write_chunked_output` is unchanged, and AT-C8 checks its failed-chunk exit | AT-C8 (control) | N/A: no new exit path |
| 3 | State machine and concurrency | evidence is read only after every stream is exhausted, so the executed flags are final when the label is computed | AT-C6, AT-C12 | M-C5 |
| 4 | Route parity and silent fallback | one schema rule per call (`run_mask_chunked`); the label comes from executed evidence; `--no-native` forces the oracle leg with a recorded reason; a broken companion on `--chunked` falls back with a `pandas` label, named in text | AT-C6, AT-C9, AT-C12, AT-C16, AT-E4, AT-E11 | M-C4, M-C6, M-C9, M-C11, M-E5, M-E6 |
| 5 | Referential integrity | N/A: `--chunked` runs no relationship key check and warns about it (`C:src/decoy/cli/run/_execute.py:258`); S2 does not change which configs it accepts | AT-C5 (control) | N/A: no FK path changes |
| 6 | Untrusted producer | N/A: no child process, extension or hostile object added; the engine is the producer, and its errors pass through the existing CLI handler | AT-C14 checks that handler's output | N/A: no boundary added |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is checked or opened by new code | none needed | N/A: no path consumer added |
| 8 | Weak tests and overclaimed evidence | each AT records red on its named base; companion cells must show PASSED in the named venv; oracle stubs cannot go silent | builder report with base SHA, red output and the import line; AT-C7 test-patch rule | each mutation names the AT it turns red |
| 9 | Behavior-preserving refactor drift | hash and Faker tokens unchanged; CSV-source parity unchanged | AT-C1 (`email` tokens), AT-C5 | M-C1 |
| 10 | Frozen contract drift | section 8 names every change; goldens freeze the chunked schema and CSV text; the contract keeps its exception, narrowed | AT-C9, AT-C10 goldens; AT-E4; `--json` shape tests | M-C8, M-C1, M-E2 |

## 10. Enumerations

### 10.1 Exit paths

The S2 file owner is `write_chunked_output` (`C:src/decoy/cli/io/_targets.py:697`). Its exits do not change:

- success: published after the last chunk (`C:src/decoy/cli/io/_targets.py:748` opens the writer);
- a chunk raises: nothing published (AT-C8);
- empty source: zero-row Parquet file with the source schema, nothing for CSV (AT-C8);
- `--native --chunked` and the post-scan refusal exit before any write (AT-C11, AT-C5). A broken companion is not an exit on `--chunked` (AT-C16).

### 10.2 Routes

- `run_mask_chunked` native leg: `src/decoy_engine/execution/native/_chunked_entry.py:143` (S2 default with a companion);
- `run_mask_chunked` oracle leg with the carry: `src/decoy_engine/execution/native/_chunked_entry.py:386` (S2 without a companion, or a declined config);
- `run_mask_chunked` oracle leg without the carry: the same site with a non-stock adapter (`src/decoy_engine/execution/_chunked_carry.py:52-57`; S2 `--no-native`);
- public oracle `run_mask_pipeline_chunked`: `src/decoy_engine/execution/_chunked.py:380` (the CLI stops calling it; AT-E4 tests it);
- full frame, sequential, unified slice: #770's assembler (AT-E7, AT-E8, AT-E10; no change here);
- auto-chunk lane: `src/decoy_engine/execution/_pipeline_auto_chunk.py:334` (no change).

### 10.3 FK shapes

- `--chunked`: no relationship key check (`C:src/decoy/cli/run/_execute.py:258`); single-table streams only; S2 accepts the same configs.
- Plain runs: FK key handling is #770's; AT-E8 runs the sequential route with a single-column FK edge.
- Composite, self-referencing and cross-table FK: N/A for this plan: no FK code changes, and #770 covers them (`#770:tests/parity/test_untouched_columns_keep_source_type.py`).

### 10.4 Fields

- `NativeRouteEvidence.compiled_kernel_executed` and `.pool_select_executed` (`src/decoy_engine/execution/native/_dispatch.py:145` and `:156`): read by S2 for the label;
- `NativeRouteEvidence.native_admitted` and `.reroute_reason` (`src/decoy_engine/execution/native/_dispatch.py:142-143`): `reroute_reason` read by S2 for `empty_input`; both read by AT-C12 and AT-E11;
- `RouteClassification.applicable`, `.state`, `.label` (`C:src/decoy/_native_gate.py:125`): values of the first two unchanged for chunked runs; the label changes.

### 10.5 Output surfaces

- Parquet and CSV target files: section 8.1.
- Human summary and `--json` `native_route.label`: section 8.1.
- `decoy explain` topics, `decoy run --help`, `docs/cli-reference.md`: rewritten (4.2, AT-C15).
- stderr and `--json` error output. S2 makes these engine codes reachable from `--chunked`:

| Code | Reachable from CLI input | Message | Proof |
|---|---|---|---|
| `chunked_schema_mismatch` | not reached: `_safe_cast` runs only for pinned string columns (`src/decoy_engine/execution/native/_chunked_schema_rule.py:356-359`), and probe 3 found no input that fails that cast; passthrough columns are taken from the source and never cast there | table, chunk, column, type names, plus pyarrow's text | defense in depth: S1 makes it value-free (AT-E9) |
| `chunked_passthrough_value_unrepresentable` | not from `decoy run`: the preflight capacity estimate refuses such a source (exit 1, "source not parsed") before the engine runs; reachable only through the engine entry or `_run_chunked_mask` (row PREFLIGHT-ARROW-PROFILE) | names the column only (`src/decoy_engine/execution/_chunked_carry.py:153-161`); the cell is in `__cause__` | AT-C14 checks the coded error through `_run_chunked_mask`; the CLI refusal text holds no value |
| raw pyarrow or pandas errors (no code) | yes, under `--no-native` only: a passthrough value pandas refuses (probe 3) | can quote the value | recorded by AT-C12; F6 |
| `chunked_leading_null_type` | no: Parquet chunks come from one file schema, and CSV columns are read as `string` | names and types only | none needed |
| `native_chunk_schema_drift` | no: same reason | names and types only (`src/decoy_engine/execution/native/_chunk_schema.py:130-137`) | none needed |
| `chunked_route_evidence_inconsistent` | no: raised only by `aggregate_chunked_route_evidence` and the output sink, which the CLI does not call | n/a | none needed |
| `native_companion_<reason>` | no on `--chunked`: the gate scope is unchanged, and a broken companion falls back to pandas with a `pandas` label | n/a | AT-C16 pins the fallback |

- Logs, audit, evidence files, progress: no change.

## 11. Reuse inventory

- `run_mask_chunked` with `CarryPlan`, `build_schema_rule` and `normalize_chunk`: the S2 fix.
- Its exact-type adapter rule (`_dispatch.py:453-463`, `_chunked_carry.py:52-57`): the `--no-native` leg choice, pinned by S1.
- `NativeRouteEvidence` runtime flags: the label.
- `pre_execution_gate`: the broken-companion check, unchanged in scope (AT-C16).
- #770's assembler: the plain-route fix and the oracle's per-chunk fix.
- `output_schema` (`_file_metadata.py`): strips field metadata at write, so `PARQUET:field_id` does not reach files.
- CLI sentries `test_declared_read_choke_point.py` and `test_csv_writer_guards.py`: extended.
- Reason registry: no new code.

No new machinery.

## 12. Pre-mortem

- `--no-native` still runs kernels because the adapter rule changes in a later engine. S1 pins the rule in the contract (AT-E11, M-E5), and AT-C12 runs in the companion venv on every gate (M-C6).
- `--no-native` fails on a value the default leg handles. Accepted for a rollback lever, recorded in 8.1, measured by AT-C12, tracked as F6.
- The label says native when nothing ran. It reads executed flags after exhaustion (M-C5).
- A companion cell skips and the gate counts it. The report must show PASSED from the named venv.
- An oracle stub keeps a test green after the CLI stops calling the oracle. AT-C7's test-patch rule refuses it.
- A chunked Parquet digest pin moves silently. The builder lists every moved pin, and the golden is the new reference.
- `decimal256` CSV text differs from `decimal128` for the same value. AT-C13 compares them.
- A broken companion on `--chunked` goes unnoticed. The label says `pandas` and the explain text names the fallback (AT-C16); F7 tracks a fail-closed check with runtime admission evidence.
- #770 changes shape before merge. S1 re-anchors on the merged head and reruns red-first on `104dfb442`.
- The interim window lasts longer than expected. It only affects Parquet sources and is named in the CHANGELOG.

## 13. Follow-ups (not in this row)

- F1: masked numeric columns that the schema rule does not pin can come back `null` for an all-null chunk. Measure which strategies can do that, then decide. V2-LOG unless a common config fails.
- F2: with S2 merged, the CLI CSV writer can lock types to the first chunk again. V2-LOG.
- F3: NONFK-OOM's probe table and the premise of its AT-A8 need a note after S2. Hand to that plan's owner.
- F4: the platform's rollback lever still calls `run_mask_pipeline_chunked` (`P:api/jobs/v2_runner.py:409`). The platform is parked.
- F5: an explicit engine keyword to force the oracle leg, to replace the CLI adapter subclass, if the owner wants it.
- F6: coded, value-free errors on the oracle leg (and on the plain run) for values pandas refuses on input (`time64[ns]` with nanoseconds, dates outside pandas' range). Engine row; it also covers the plain run, which fails the same way after #770.
- F7: fail a `--chunked` run closed on a broken companion, as on the plain run. It needs runtime admission evidence (which tables the chunked native route admitted and which kernel failed to load), not the config-shape `static_native_eligibility`. Engine plus CLI row.
