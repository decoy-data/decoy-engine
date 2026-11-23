Status: plan

# PARQUET-CHUNKED-NULLABLE-INT: chunked runs and plain runs keep nullable integers exact

Owner: Cam. Author: Opus. Date: 2026-11-23. Roadmap row: PARQUET-CHUNKED-NULLABLE-INT (new V1 bug row). Anchors are in this repository (decoy-engine) at `origin/main` `104dfb442` unless marked `C:` (decoy CLI at `origin/main` `95362d16`, which pins `decoy-engine==0.28.3`) or `P:` (decoy-platform).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, design notes, choke point, placement, established solutions), `bugfix.md`, `reuse-first.md`, `testing.md` (test depth, full-suite triggers), `proportionality.md`, `api-and-compatibility.md` (output type change), `cross-cutting-concerns.md` (one choke point per rule), `catalogs/recurring-defects.md` (11 classes), `workspace-and-vcs.md` (commit messages). Engine `CLAUDE.md` file-size rule (600-line aim, 700 hard max). Engine `CODEMAP.md` "Where Things Go" (line 248).

Risk: R2 overall. S1 (engine) is R2: it changes the output type of an existing config on the plain route (frozen output) and touches the masking boundary. S2 (CLI) is R2: it changes which engine entry the `--chunked` path calls and the file bytes of chunked Parquet output. S3 is R1. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis, for S1 and S2. Full suite before merge: yes for S1 and S2 (frozen output contract trigger).

## 1. Frame

### 1.1 Symptom

`decoy run --chunked` with a Parquet source and a Parquet target exits 3 when a passthrough integer column holds a null in some chunks and none in others. The error text is pyarrow's `ValueError: Table schema does not match schema used to create file`, with `n: double` in the chunk against `n: int64` in the file. The same job fails with the CLI pinned to engine 0.28.3 and with the engine at `origin/main`.

### 1.2 What the probes showed

All probes ran through `vm-run` on the Mac and the Dell. They were not committed.

Engine probe on `104dfb442`. The table is `id int64, n int64, d date32, s string`; `n` and `d` are passthrough and `s` is hashed. Chunk 0 has no nulls, chunk 1 is mixed and chunk 2 is all null. `n` holds `2**53 + 1`.

| Entry | `n` type per chunk | `d` type per chunk | `s` type per chunk | `2**53 + 1` in chunk 1 | CLI-style `ParquetWriter` |
|---|---|---|---|---|---|
| `run_mask_pipeline_chunked` (the CLI `--chunked` entry) | int64, double, double | date32, date32, null | string, string, null | `9007199254740992.0` (lost) | fails |
| `run_mask_chunked`, default adapter | int64, int64, int64 | date32, date32, date32 | string, string, string | exact | ok |
| `run_mask_chunked`, subclass adapter (oracle leg) | int64, int64, int64 | date32, date32, date32 | string, string, string | exact | ok |

A narrower probe, where only `n` varied, gave the same split for every chunk order: null-free then mixed, mixed then null-free, null-free then all null, and all null then null-free. Hash tokens for the same integer were equal in a null-free chunk and in a null-bearing chunk on all three entries, so hash keying is not affected.

CLI probe on `C:95362d16`: `decoy run` on six rows, with `n` holding `2**53 + 1` and one null, `d` with two nulls, `email` hashed, and `--chunk-size 3`.

| Run | Parquet target | CSV target |
|---|---|---|
| plain | exit 0, `n: double`, values `[10.0, 20.0, 30.0, 9007199254740992.0, None, 60.0]` | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked` | exit 3, schema mismatch | exit 0, row 4 `n` is `9.007199254740992e+15` |
| `--chunked`, prototype where `_masked_chunks` calls `run_mask_chunked` | exit 0 | exit 0, row 4 `n` is `9007199254740993` |

With the prototype swap, the existing CLI suites `C:tests/e2e/test_run_chunked.py`, `C:tests/e2e/test_run_chunked_parquet.py` and `C:tests/e2e/test_run_chunked_post_scan.py` passed (24 tests). The prototype is not the S2 build: it skipped the sentries and the route label.

### 1.3 Impact under the V1 bar

- Function break: a `--chunked` run to a Parquet target fails when a passthrough integer column has nulls in some chunks only. The same happens with a date column or a masked string column that is all null in one chunk.
- Data loss: integers above `2**53` with a null in the same column are rounded on the plain run (both targets) and on `--chunked` to CSV. Large nullable IDs (64-bit keys, snowflake-style IDs) are a common case.
- No leak.

### 1.4 The Dennis R2 note on CLI #397

The note was "chunked parquet->csv csv_schema_drift on nullable int/date (main ok)". It has the same root cause. The oracle entry gives a nullable integer chunk as `double` and an all-null date chunk as `null` (1.2). The CSV-WRITE-FAST branch locked the CSV writer to the first chunk's types, so the type change became `csv_schema_drift`. Main's CSV writer accepts a type change between chunks on purpose (`C:src/decoy/cli/io/_targets.py:433-458`, docstring: "the engine's adapter makes a nullable int64 chunk float64 and reports an all-null chunk as `null`"), so main did not refuse. Main still rounds the value (1.2). Remediation A3 removed the type lock and the branch merged. That remediation changed the writer. This plan fixes the cause.

## 2. Root cause with evidence

### 2.1 Chunked runs

The CLI `--chunked` path calls the engine's reference oracle, `run_mask_pipeline_chunked` (`C:src/decoy/cli/run/_execute.py:157-182`, `_masked_chunks`). Each chunk goes through the pandas adapter, and its output is whatever pandas inference gives for that chunk alone. pandas widens an Arrow integer with a null to `float64`, which rounds above `2**53`, and infers `null` for an all-null column. The oracle applies no output rule across chunks. That is its documented contract: `docs/compatibility-contract.md:926-946` pins `run_mask_chunked` to "value equality with `run_mask_pipeline_chunked`" with one stated exception, "a value the oracle's round trip rounds or refuses, such as a nullable integer above 2^53, comes back exact". It gives the one-type-per-column rule to `run_mask_chunked` only.

The CLI writer then opens one `pq.ParquetWriter` with the first chunk's schema (`C:src/decoy/cli/io/_targets.py:740-750`) and fails on the first chunk whose types differ.

The engine already has the fix, and the CLI does not use it. `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:600`) builds a `CarryPlan` (`src/decoy_engine/execution/_chunked_carry.py`), so a passthrough column never goes through pandas. It also builds the schema rule (`build_schema_rule`, `src/decoy_engine/execution/native/_chunked_schema_rule.py:252`) and normalizes every chunk on both legs (`normalize_chunk`, same file, line 336, applied at `_chunked_entry.py:143` and `:386`). The public oracle never builds a `CarryPlan` (`_chunked_carry.py:16-17`), and `run_mask_pipeline_chunked` (`src/decoy_engine/execution/_chunked.py:380`) returns the raw adapter outputs. The auto-chunk lane and the stream route use the rule too (`src/decoy_engine/execution/_pipeline_auto_chunk.py:334`, `:366`).

### 2.2 Plain runs

The pandas adapter turns the masked frame back into Arrow in one place, `table_from_pandas_keeping_source_types` (`src/decoy_engine/execution/_fk_keys.py:521`). The full-frame adapter (`src/decoy_engine/execution/_pandas_adapter.py:322`) and the sequential route (`src/decoy_engine/execution/_sequential.py:526`) both call it. For untouched columns it gives nested types their source type back (`_rebuilds_with_source_type`, line 485, from engine #754), and it repairs two date cases (`_with_source_types`, line 497). It does nothing for integers. So an untouched integer column with a null leaves as `double`, and it keeps the rounding from the input conversion. The public oracle runs the same adapter per chunk, which is why its passthrough integers change type in 2.1.

A narrower fix for the same loss is already in the engine. `src/decoy_engine/execution/_exact_int_sources.py` keeps the original Arrow column of a widened integer column (`_widened_int_column`, line 29) so that deterministic Faker and hash key exactly. It does this only for those masked columns, never for the output of untouched columns.

### 2.3 Trace

`graphify query` on the engine graph (`~/.cache/graphify/decoy-engine/graphify-out/graph.json`, built 2026-11-21, before `104dfb442`) found `run_mask_pipeline_chunked`, `build_schema_rule` and `normalize_chunk`. `graphify path` from either chunked entry to `normalize_chunk` goes only through the shared `Table` type node, so the graph shows no call edge from the oracle to the rule. The call sites were then checked with grep on `104dfb442`: only `_chunked_entry.py` and `_pipeline_auto_chunk.py` call `normalize_chunk` and `build_schema_rule`, and the CLI calls only `run_mask_pipeline_chunked` (`C:src/decoy/cli/run/_execute.py:175`).

### 2.4 Overlap with other rows

- NONFK-OOM (`origin/plan/nonfk-oom:docs/plans/2026-11-19-nonfk-oom.md`) does not own this fix. Its section 2 records the same plain-route loss ("int64 with nulls, values above 2^53: full_frame `double`, values rounded", while `run_mask_chunked` gives `int64`, exact). It acts on routing (moving large tables to the chunked lane). It does not change the full-frame output or the CLI `--chunked` entry. Its AT-A8 assumes `--chunked` calls `run_mask_chunked`, which is false today and becomes true with S2. S1 removes the full-frame and chunked type difference for nullable integers, so NONFK-OOM's G1 byte change gets smaller. Its follow-up F2 (decimal precision on the full-frame route) stays with NONFK-OOM.
- CHUNKED-STRUCT (`C:origin/plan/chunked-struct`, engine #754 merged) does not own this fix. It restores nested types in the same output conversion (`_rebuilds_with_source_type`) and leaves scalars alone. S1 follows its pattern and keeps its behavior.
- FIXED-LIST-NULL (engine, not started) has no overlap. Its case is a fixed-size list with a null cell in an in-memory source.
- RUN-STREAM slice C2 (`C:origin/plan/run-stream-r6-5`, section 5.3) deletes `_run_chunked_mask` and sends `--chunked` through `run_pipeline(execution_mode="stream")`, which carries passthrough columns. That would also fix 2.1. C2 is not started and waits on DELIV C2a and C2b, an engine release and REL-PKG, so this plan does not wait for it. S2 changes one call and two sentries. C2 later deletes the same call site, and its AT-C2a parity gate (base `--chunked` against the new path) gets a stricter base from S2.

No row owns the fix, so this plan goes ahead.

## 3. Established solutions considered

Search run: a web search for pandas and Arrow nullable integer conversion and for the ParquetWriter schema rule, and an in-codebase search for each place the engine already keeps source types.

- Arrow pandas integration docs: `Table.to_pandas()` turns an integer column with nulls into `float64` by default. A `types_mapper` that maps Arrow integers to `pd.Int64Dtype()` and the other nullable widths keeps them exact ([Arrow docs, pandas integration](https://arrow.apache.org/docs/python/pandas.html), [Arrow 6.0 docs](https://arrow.apache.org/docs/6.0/python/pandas.html)). pandas `read_parquet` uses the same kind of mapper ([pandas PyArrow guide](https://pandas.pydata.org/docs/user_guide/pyarrow.html)). The engine uses it for FK keys only (`_exact_fk_types_mapper`, `_fk_keys.py:440-483`), and says on purpose that it is "not a blanket dtype policy change for every integer column the engine masks". Strategy code and `when:` predicates read the shared frame and behave differently on `pd.NA`.
- Arrow `ParquetWriter` takes one schema when it opens and refuses a table with another ([pyarrow ParquetWriter](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)). DuckDB `COPY ... TO` and Polars `sink_parquet` also bind the schema before the first byte (cited at `_chunked_output_sink.py:9-13`). So a column's output type must be fixed for the whole call. It cannot be inferred per chunk.
- In the codebase:
  - the B1 carry (`_chunked_carry.py`): a passthrough column never enters pandas, and the output takes the source column;
  - the schema rule (`_chunked_schema_rule.py`): one type per column per call;
  - `_exact_int_sources.py`: keep the widened column's Arrow values beside the frame;
  - the nested rebuild from engine #754: untouched columns get their source type in the one output conversion.

Choice:

- S2 (chunked): use the existing public entry that already applies the carry and the rule, `run_mask_chunked`. No new engine code.
- S1 (plain): extend the existing output conversion with the existing `_exact_int_sources` pattern. The Arrow values of an untouched widened integer column are kept at ingest and put back at output. The frame that strategies and predicates read does not change, so the FK-only `types_mapper` decision stands.

Rejected:

- A blanket `types_mapper` on input: it changes what every strategy and predicate reads.
- Casting the `float64` column back to the integer type at output: it cannot restore the lost low bits.
- A CLI writer that casts each chunk to the first schema: it cannot restore the lost bits, and it cannot type a first chunk that is all null.

No custom algorithm is needed.

## 4. Fix design

### 4.1 Guarantee

1. `decoy run --chunked` with a Parquet or CSV target gives one Arrow type per column for the whole run, and passthrough columns come back exactly as the source holds them. This covers nullable integers of every width, values above `2**53` and `2**63` (uint64), and date columns with all-null chunks. The rule is the one `run_mask_chunked` pins (`docs/compatibility-contract.md:926-946`).
2. On the pandas adapter routes (full frame and sequential), and so per chunk on `run_mask_pipeline_chunked`, an untouched integer column that pandas widened keeps its source Arrow type and exact values. This includes an all-null integer column.
3. Masked output values do not change on any route. Hash and deterministic Faker tokens stay byte-equal.
4. On S1's routes, an output with no widened untouched integer column is byte-identical to today, schema metadata included.

Non-goals (recorded, not blockers):

- Decimal precision and dictionary index width on the full-frame route (NONFK-OOM F2, owner question Q2).
- Masked numeric columns that the schema rule does not pin and that come back `null` for an all-null chunk. `run_mask_chunked` leaves them as the route produced them. Follow-up F1.
- The `--chunked` thread count. `run_mask_chunked` keeps `native_threads=1`; `--threads` reaches `--chunked` in RUN-STREAM C2.
- Putting back the CSV type lock that CSV-WRITE-FAST removed (follow-up F2).
- The unified-slice route. It already declines a table whose pandas round trip changes a column's type (`src/decoy_engine/execution/_unified_slice_admission.py:384-399`), so a widened integer column takes the adapter route that S1 fixes.

### 4.2 S1 engine design

- `_exact_int_sources.py` splits today's `_widened_int_column` test into a shared core, `_int_widened_by_pandas(source, frame, column)`: an Arrow integer source column with a non-integer frame dtype and at least one null. Two named predicates use the core. `_widened_int_column` keeps its current meaning for masked keying (it also excludes an all-null column). The new `_widened_output_int_column` includes the all-null case. No flag argument is added.
- A new function next to `exact_int_faker_sources`, `untouched_widened_int_sources(table, source, frame, untouched)`, returns `source.column(c)` for each column in `untouched` that `_widened_output_int_column` accepts.
- Both routes call it at ingest, next to the existing `register_exact_int_sources` call (`_sequential.py:426` and the matching site in the adapter), while the source table is still alive. The sequential route releases `src` at `_sequential.py:437-438`. The kept columns are only the widened untouched integer columns of that table, and they are released with the table (`release_table`, `_exact_int_sources.py:87`).
- `table_from_pandas_keeping_source_types` (`_fk_keys.py:521`) takes a new keyword, `exact_columns: Mapping[str, pa.ChunkedArray]`. It drops those columns from the frame before `pa.Table.from_pandas`, as the nested rebuild already does, and inserts each kept Arrow column at its frame position. Before inserting, it checks `len(array) == len(frame)` and raises `AssertionError` with a value-free message on a mismatch. This is an invariant, not a handled error: the frame is built from the same source in the same call, and `_exact_int_sources` already relies on that row alignment.
- Pandas schema metadata: as with the nested rebuild, the restored columns are not in the `from_pandas` metadata. `safe_output` rebuilds the `pandas` key from the output schema when a file is written (`src/decoy_engine/safe_output/_file_metadata.py:1-10`, `:305-314`), so written files describe the real type.
- Size: about 40 source lines over three files. No new module, no new public name, no new reason code. `_sequential.py` has 679 lines against the 700 hard maximum, so S1's net addition there must stay at 21 lines or fewer. If it does not fit, the ingest call moves into `register_exact_int_sources`, which both routes already call. The cap is not raised (catalog class 11).

### 4.3 S2 CLI design

- `_masked_chunks` (`C:src/decoy/cli/run/_execute.py:157`) calls `decoy_engine.run_mask_chunked` with the same config, chunks, table, engine version and key provider, plus a `route_evidence_sink` list. `run_mask_chunked` has no `source_schema` parameter. The CLI already runs `prepared_sources` before any reader exists (lines 113 and 170), and `run_mask_chunked` checks the config at entry and each chunk's columns, so the declared-read rule still holds. `source_schema_and_chunks` stays, because it gives the chunk iterator and the empty-Parquet schema.
- Route label: `classify_route` (`C:src/decoy/_native_gate.py:425-430`) returns the fixed label `pandas chunked stream`. With S2 the native route can run, so the label comes from the evidence: `chunked stream (native)` when every table's `NativeRouteEvidence.native_admitted` is true, `chunked stream (pandas)` when none is, and `chunked stream (mixed)` otherwise. The evidence goes back through the existing run context. No new flag is added.
- Sentries:
  - the declared-read sentry adds `run_mask_chunked` to `ENGINE_ENTRIES` (`C:tests/sentry/io_policy/test_declared_read_choke_point.py:94`);
  - the CSV writer guard names `run_mask_chunked` as the factory's engine call (`C:tests/sentry/io_policy/test_csv_writer_guards.py:26`);
  - a new rule in the same guard file refuses any call of `run_mask_pipeline_chunked` under `C:src/decoy/`, because the oracle is a reference entry, not a production one. One seeded case covers each import spelling the guard handles today: `from decoy_engine import run_mask_pipeline_chunked`, `decoy_engine.run_mask_pipeline_chunked(...)` and `from decoy_engine.execution import run_mask_pipeline_chunked`. Other spellings are V2-LOG under the owner's guard-scanner scope (catalog class 5).
- Docstrings that say `--chunked` calls the oracle are updated: `C:src/decoy/cli/run/__init__.py:7`, `C:src/decoy/api.py:511`, `_run_chunked_mask` and `classify_route`.
- Size: about 30 source lines in three files, plus tests. No new public name.

### 4.4 Choke points

- Pandas-to-Arrow output on the adapter routes: `table_from_pandas_keeping_source_types` is the one conversion, and both adapter routes call it. Guard: AT-E1 runs the full-frame route and AT-E2 the sequential route. Mutation M-E5 removes the sequential call's `exact_columns` and must turn AT-E2 red.
- Engine entry for CLI chunked masking: `_masked_chunks` is the one factory (existing guard). The new sentry refuses the oracle anywhere in CLI source. Mutation M-C3 must turn the seeded cases red.

### 4.5 Placement

No new files in `src/` in either repo. New tests go into existing files:

| Test | File | Sits beside |
|---|---|---|
| AT-E1, AT-E3, AT-E5, AT-E6, AT-E7, AT-E8 | `tests/unit/execution/test_c5c_a_nullable_int_faker.py` | the c5c-a exact-int cases |
| AT-E2 | `tests/unit/execution/test_de10_fk_lossless_typing.py` | the sequential FK typing cases |
| AT-E4 | `tests/native/test_chunked_entry_values_schema.py` | the oracle against `run_mask_chunked` schema cases |
| AT-C1 to AT-C4, AT-C8 | `C:tests/e2e/test_run_chunked_parquet.py` | the chunked Parquet e2e cases |
| AT-C6 | `C:tests/e2e/test_run_native.py` | the route label cases |
| AT-C7 | `C:tests/sentry/io_policy/test_csv_writer_guards.py`, `C:tests/sentry/io_policy/test_declared_read_choke_point.py` | the existing guards |
| AT-R1, AT-R2 | `C:tests/e2e/test_run_chunked_parquet.py` | as above |

Changelog: the fragment `changelog.d/parquet-chunked-nullable-int.md` (engine) and an entry in the CLI `CHANGELOG.md`.

### 4.6 Design notes

No new structure. S1 extends two existing helpers along their own established pattern: exact Arrow sources kept beside the frame, and untouched columns rebuilt with their source types. S2 changes one call to an existing public entry. One place per fact: the "pandas widened this integer" test stays in `_exact_int_sources.py`, and the "untouched" set stays in `untouched_columns`.

## 5. Slices

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S2 | CLI | `--chunked` calls `run_mask_chunked`; route label from evidence; sentries; docstrings; CHANGELOG | nothing; works on the current pin 0.28.3 | R2 | T1 plus the full CLI suite (output bytes trigger) |
| S1 | engine | exact untouched nullable integers on the adapter routes; contract text; changelog fragment | nothing | R2 | T1 plus the full engine suite (frozen output contract trigger) |
| S3 | CLI | plain-run and chunked-against-plain e2e cells after the repin to the engine release with S1 | S1 released, the repin | R1 | T1; folds into the repin PR if one is open |

Separate builders in separate worktrees can build S2 and S1 at the same time. S2 ships first: it fixes the reported exit 3 and the chunked CSV rounding with no engine release.

Slice count: 3.

## 6. Acceptance tests (red-first)

Fixture F, used unless a cell says otherwise, is a Parquet source with these columns:

- `id int64`, passthrough;
- `n int64`, passthrough, values `[10, 20, 30, 2**53 + 1, None, 60, None, None, None]`;
- `u uint64`, passthrough, values `[1, 2**63 + 5, 2**64 - 1, 7, None, 9, None, None, None]`;
- `d date32`, passthrough, with nulls in rows 5 to 9;
- `email string`, hashed, with rows 7 to 9 null.

At chunk size 3, chunk 0 has no nulls, chunk 1 is mixed, and chunk 2 is all null in `n`, `u`, `d` and `email`.

"Red on base" is the result on `C:95362d16` (S2, S3) or `104dfb442` (S1). The builder records it before writing the fix.

### S2 (CLI)

| AT | Behavior | Red on base |
|---|---|---|
| AT-C1 | `decoy run --chunked --chunk-size 3` on F with a Parquet target: exit 0. Output schema `n int64`, `u uint64`, `d date32`, `email string`. `n`, `u` and `d` equal the source exactly. `email` equals the plain run's tokens. | exit 3, schema mismatch |
| AT-C2 | The same with a CSV target: exit 0. Row 4 `n` is the text `9007199254740993` and row 2 `u` is `9223372036854775813`. Every other cell equals the plain run's CSV text. | `9.007199254740992e+15` |
| AT-C3 | Chunk sizes 1, 3, 7 and 100 on F: Parquet values and types are equal across sizes, and CSV bytes are equal across sizes. | exit 3 for the sizes that split nulls across chunks |
| AT-C4 | Chunk 0 is all null in `n` (F reversed): exit 0 and the same types as AT-C1. | exit 3 |
| AT-C5 (control) | `test_run_chunked.py`, `test_run_chunked_parquet.py` and `test_run_chunked_post_scan.py` pass unchanged. The post-scan refusal under `--chunked` keeps its exit code, reason code and text. | green on base |
| AT-C6 | Route label: a native-admissible config with the companion present gives `chunked stream (native)`. A config the native route declines (a `text_redact` column with `ner`) gives `chunked stream (pandas)`. A two-table run with one of each gives `chunked stream (mixed)`. The summary never says native unless the evidence says it ran. | `pandas chunked stream` in every case |
| AT-C7 | Sentries: each seeded oracle call in CLI source is refused, one case per covered spelling. A seeded `run_mask_chunked` call outside the gate is refused by the declared-read sentry. The real tree passes. | the oracle seeds are not refused; the real tree fails the new rule, because `_execute.py` calls the oracle |
| AT-C8 (control) | An empty Parquet source writes a zero-row file with the source schema. An empty CSV source publishes nothing. In a two-table run, a failing chunk publishes no target. | green on base |

### S1 (engine)

| AT | Behavior | Red on base |
|---|---|---|
| AT-E1 | `run_pipeline` on the full-frame route (asserted from `quality_metrics`), on a table with passthrough `int8`, `int16`, `int32`, `int64`, `uint8` and `uint64` columns that hold nulls, including each type's extremes, `2**53 + 1` and `2**64 - 1`: each output column has the source type and `equals` the source column. | `double`, rounded |
| AT-E2 | Sequential route, a parent and a child table with an FK edge. The child has a nullable `int64` passthrough column with `2**53 + 1`: exact type and values. | `double`, rounded |
| AT-E3 | Hash and deterministic Faker over a nullable `int64` column: tokens are byte-equal to base, and no output cell of the masked column equals its source cell. | green on base (control); red under M-E2 |
| AT-E4 | `run_mask_pipeline_chunked` on F's integer columns at chunk size 3: `int64` and `uint64` on every chunk, values exact, and `pa.Table.equals` to `run_mask_chunked` after `concat_tables`. | `double` on chunks 1 and 2 |
| AT-E5 | A table with no widened integer column (null-free integers, strings, dates): output bytes and schema metadata equal base on the full-frame and sequential routes. The unified-slice D9 parity tests pass. | green on base (control); red under M-E3 |
| AT-E6 | Unit: `table_from_pandas_keeping_source_types` with an `exact_columns` array one row longer than the frame raises `AssertionError`. The message holds no value, `__cause__ is None` and `__context__ is None` (catalog class 3). | the keyword does not exist (`TypeError`) |
| AT-E7 | A `when:` predicate on column `s` that reads the nullable integer passthrough column `n` (`n > 15`) selects the same rows as base, and `n` leaves exact. | `n` leaves as `double` |
| AT-E8 | An all-null `int64` passthrough column leaves as `int64` with all nulls. | `double` |

### S3 (CLI, after the repin)

| AT | Behavior | Red on 0.28.3 |
|---|---|---|
| AT-R1 | Plain `decoy run` on F: the Parquet target keeps `n int64` and `u uint64` exactly. In the CSV target, row 4 `n` is `9007199254740993`. | `double`, rounded |
| AT-R2 | On F, `--chunked` and the plain run give equal Parquet values and types, and equal CSV bytes. | types differ (`double` against `int64`) |

Existing tests that pin the old behavior change only where they assert the defect: the oracle's `double`, or the stated "oracle rounds" exception for integers. The builder lists each one in the report, with the line it changed and the reason. Any other assertion change is a stop-and-explain (owner rule: builders must not change tests so that a divergence passes).

## 7. Named mutations

Each mutation runs on the final head of its slice, and the report records that head (catalog class 9).

| Id | Slice | Mutation | Must turn red |
|---|---|---|---|
| M-C1 | S2 | `_masked_chunks` calls `run_mask_pipeline_chunked` again | AT-C1, AT-C2, AT-C4, AT-C7 (real tree) |
| M-C2 | S2 | remove `run_mask_chunked` from `ENGINE_ENTRIES` | AT-C7 declared-read seed |
| M-C3 | S2 | delete the new "no oracle in CLI source" rule | AT-C7 oracle seeds |
| M-C4 | S2 | `classify_route` returns the fixed chunked label again | AT-C6 |
| M-C5 | S2 | the label reads `native_admitted` of the first table only | AT-C6 mixed case |
| M-E1 | S1 | `table_from_pandas_keeping_source_types` ignores `exact_columns` | AT-E1, AT-E4, AT-E7, AT-E8 |
| M-E2 | S1 | `untouched_widened_int_sources` ignores `untouched`, so masked columns are restored too | AT-E3 (the source value comes back in the hashed column) |
| M-E3 | S1 | the core test drops the frame-dtype and null checks, so null-free integers are restored too | AT-E5 |
| M-E4 | S1 | the row-count check is removed | AT-E6 |
| M-E5 | S1 | the sequential route does not pass `exact_columns` | AT-E2 |
| M-E6 | S1 | the core test uses `pa.types.is_signed_integer` instead of `is_integer` | AT-E1 `uint8` and `uint64` cells, AT-E4 `u` |
| M-E7 | S1 | `_widened_output_int_column` excludes the all-null case | AT-E8 |

## 8. Frozen contracts and byte changes

No public signature changes in either repo. No new reason code, so the reason registry does not change.

Engine (S1), with a Breaking line in `changelog.d/parquet-chunked-nullable-int.md`:

- Plain runs (full-frame and sequential routes) write an untouched integer column that holds a null with its source Arrow type, not `double`. Values above `2**53` are exact. In Parquet files the type of those columns changes. In CSV the text changes only where the old text was rounded or in exponent form.
- `run_mask_pipeline_chunked` yields those columns with the source type on every chunk.
- `docs/compatibility-contract.md:926-946`: the stated exception narrows. Integer passthrough columns no longer differ between `run_mask_chunked` and the oracle. The exception stays for other types the round trip alters.
- The `pandas` schema-metadata entry of a restored column is not in the `ExecutionResult` outputs, as for nested columns. Written files carry the metadata rebuilt from the output schema.
- This changes the bytes of existing configs on the plain route, so it must merge before the 1.0 freeze. Under the FREEZE-OUTPUT rule, such a change after 1.0 waits for 2.0.

CLI (S2), with an entry in the CHANGELOG:

- `--chunked` Parquet output has one type per column per run. Before, a run could succeed with a schema-rule column (hash, truncate, string redact) that was `null`-typed on every chunk. That column is now `string`.
- `--chunked` Parquet files no longer carry the `pandas` schema-metadata key, because `run_mask_chunked` yields chunks without it (`_chunked_schema_rule.py`, last line of the module docstring). Values do not change. Bytes stay stable for a fixed chunk size and pyarrow version. The builder searches `C:tests/e2e` for sha256 pins of chunked Parquet output and lists each moved pin.
- `--chunked` CSV text for integers above `2**53` in a column with nulls is exact.
- The `--chunked` route label changes from `pandas chunked stream` to `chunked stream (native)`, `(pandas)` or `(mixed)`. This applies to the human summary, and to `--json` if the label is in it. The builder checks the JSON shape tests.
- `--chunked` can now run the native route (one thread). Values do not change, by the `run_mask_chunked` contract.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| # | Class | Applies | How this plan handles it |
|---|---|---|---|
| D1 | Anchored validation | no | no regex or value validation added |
| D2 | Strict wire and stored types | no | no persisted or wire model added |
| D3 | No exception context | yes (S1) | the row-count invariant raises with no context; AT-E6 asserts `__cause__` and `__context__` are `None` and the message holds no value |
| D4 | Versioned read models | no | no reader of a persisted format changes |
| D5 | Normalized guard scanners | yes (S2) | the new "no oracle in CLI source" rule covers the spellings listed in 4.3, each with a seeded case (AT-C7); deliberate evasion is V2-LOG |
| D6 | No reaching into private modules | yes (S2) | the CLI imports `run_mask_chunked` from `decoy_engine` (public, `docs/frozen-surfaces.md:103`); S1 stays inside the engine's own private modules |
| D7 | No hidden CI failures | no | no CI script changes |
| D8 | One input, one trust class per entry point | no | no user-named input path changes |
| D9 | Mutations on the final head | yes | section 7 runs on each slice's final head, and the head is recorded |
| D10 | Allowlisted helpers are still checked | yes (S2) | `run_mask_chunked` joins the declared-read sentry's entry set by exact name, so the same rule checks its callers (M-C2) |
| D11 | No raised caps | yes (S1) | `_sequential.py` has 679 of 700 lines; the cap is not raised, and 4.2 gives the fallback placement |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the row-count invariant message names no value and carries no context; no log line is added | AT-E6 checks the message, `__cause__` and `__context__` | M-E4 removes the check, and AT-E6 goes red |
| 2 | Cleanup missing on an exit path | N/A: no slice adds a resource owner. The CLI publish lease in `write_chunked_output` does not change, and AT-C8 keeps its failed-chunk exit as a control | AT-C8 (control) | N/A: no new exit path to mutate |
| 3 | State machine and concurrency | N/A: no new shared state. The kept integer columns live for one table in one call and go with `release_table` | none needed | N/A: no transition added |
| 4 | Route parity and silent fallback | one output rule per call (`run_mask_chunked`) on the chunked route; one output conversion (`table_from_pandas_keeping_source_types`) on both adapter routes; the route label comes from the evidence, never a fixed string | AT-E1 (full frame), AT-E2 (sequential), AT-E4 (oracle per chunk), AT-C6 (label) | M-E5, M-C4, M-C5 |
| 5 | Referential integrity | FK key columns are already exact through `_exact_fk_types_mapper`, so the S1 predicate never selects them; S1 changes untouched non-key columns only | AT-E2 runs a parent and child with an FK edge and checks the key and the nullable column | M-E3 restores null-free columns too and turns AT-E5 red; key columns fall in that set |
| 6 | Untrusted producer | N/A: no child process, extension or hostile object is added. The Arrow columns come from the engine's own source read | none needed | N/A: no boundary added |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is checked or opened by the new code. The CLI target path handling does not change | none needed | N/A: no path consumer added |
| 8 | Weak tests and overclaimed evidence | each AT records its red result on the named base before the fix; the controls (AT-C5, AT-C8, AT-E3, AT-E5) record green on base and red under a named mutation | the builder report holds the base SHA and the red output per AT | each mutation in section 7 names the AT it turns red |
| 9 | Behavior-preserving refactor drift | the `_widened_int_column` split keeps its current callers' meaning; AT-E3 pins the masked keying tokens byte for byte | AT-E3 and the existing c5c-a tests | M-E7 and M-E2 |
| 10 | Frozen contract drift | section 8 lists each frozen output that changes, with a Breaking changelog line and the contract text update; no public signature changes | AT-E5 (unchanged bytes where no widened integer exists); the existing `tests/sentry` frozen-surface snapshot | M-E3 turns AT-E5 red |

## 10. Enumerations

### 10.1 Exit paths

S1 owns no file or state. The CLI file owner on the S2 path is `write_chunked_output` (`C:src/decoy/cli/io/_targets.py:697`). Its exits do not change:

- success: the temp file is published after the last chunk (`C:src/decoy/cli/io/_targets.py:748` opens the writer);
- a chunk raises: no target is published (AT-C8);
- an empty source: Parquet writes a zero-row file with the source schema, CSV publishes nothing (AT-C8);
- the post-scan refusal under `--chunked` exits before any write (`C:tests/e2e/test_run_chunked_post_scan.py`, AT-C5).

### 10.2 Routes

- full frame, pandas adapter: `src/decoy_engine/execution/_pandas_adapter.py:322` (S1);
- sequential FK route: `src/decoy_engine/execution/_sequential.py:526` (S1);
- unified slice: declines widened integer tables at `src/decoy_engine/execution/_unified_slice_admission.py:386` (no change);
- `run_mask_chunked` native leg: `src/decoy_engine/execution/native/_chunked_entry.py:143` (no change, used by S2);
- `run_mask_chunked` oracle leg: `src/decoy_engine/execution/native/_chunked_entry.py:386` (no change, used by S2);
- auto-chunk lane: `src/decoy_engine/execution/_pipeline_auto_chunk.py:334` (no change);
- public oracle `run_mask_pipeline_chunked`: `src/decoy_engine/execution/_chunked.py:380` (gains exact integers through S1; the CLI stops calling it in S2).

### 10.3 FK shapes

- single-column FK: keys are read exact through `_exact_fk_types_mapper` (`src/decoy_engine/execution/_fk_keys.py:440`), so they are integer in the frame and S1 skips them; AT-E2 covers this shape;
- composite, self-referencing and cross-table FK: same key mapper, same skip; the nullable non-key columns of those tables take the S1 restore on the sequential route;
- `--chunked`: the CLI chunked path does not run the relationship key check and warns about it (`C:src/decoy/cli/run/_execute.py:258`); S2 does not change which configs `--chunked` accepts.

### 10.4 Fields

Public result types the slices read or change:

- `ExecutionResult.outputs` (`src/decoy_engine/execution/_adapter.py:68`): the table type changes for widened untouched integer columns (S1);
- `ExecutionResult.quality_metrics` (`src/decoy_engine/execution/_adapter.py:72`): no change; AT-E1 reads the route from it;
- `NativeRouteEvidence.native_admitted` (`src/decoy_engine/execution/native/_dispatch.py:142`): read by S2 for the route label; no change to the type;
- `NativeRouteEvidence.reroute_reason`: no change; not shown in the label.

### 10.5 Output surfaces

- Parquet target file: types and, for `--chunked`, the `pandas` metadata key change (section 8);
- CSV target file: text changes only for rounded or exponent-form integers;
- human summary route label: `C:src/decoy/_native_gate.py:429` (S2);
- `--json` summary: the label if it is serialized there (the builder checks);
- stderr on failure: the S1 invariant message is value-free; no other error text changes;
- logs, audit, evidence, progress, help: no change.

## 11. Reuse inventory

- `run_mask_chunked` with `CarryPlan`, `build_schema_rule` and `normalize_chunk`: the whole S2 fix.
- `_exact_int_sources.py` (`_widened_int_column`, `register_exact_int_sources`, `release_table`): the S1 capture and release.
- The nested rebuild in `table_from_pandas_keeping_source_types` (engine #754): the S1 drop-and-insert pattern.
- `untouched_columns` (`_chunked_carry.py:191`): the one definition of "untouched".
- `safe_output` metadata rebuild (`_file_metadata.py`): written files describe the restored type with no new code.
- CLI sentries `test_declared_read_choke_point.py` and `test_csv_writer_guards.py`: extended, not copied.
- Module-size sentry (`tests/sentry/test_module_size.py`): holds `_sequential.py` at 700.
- Reason registry: no new code needed.

No new machinery.

## 12. Pre-mortem

- S1 restores a masked column and leaks source values. Closed by passing only `untouched` columns, AT-E3 and M-E2.
- S1 changes null-free integer output and breaks D9 metadata parity or byte stability. Closed by the null and dtype predicate, AT-E5 and M-E3.
- A `when:` predicate or strategy sees a different frame. The frame does not change; AT-E7 checks.
- `_sequential.py` goes over 700 lines. Fallback placement in 4.2.
- S2 changes chunked Parquet bytes that some test pins by digest. The builder lists each moved pin (section 8).
- The native leg on `--chunked` gives different values from the oracle for some strategy. The `run_mask_chunked` contract pins value equality, and AT-C1, AT-C3 and the existing chunked suites compare values.
- S3 waits on an engine release that slips. S2 alone fixes the reported exit 3 and the chunked CSV loss; S3 only closes the plain route.

## 13. Follow-ups (not in this row)

- F1: on `--chunked` Parquet, a masked numeric column that the schema rule does not pin can still come back `null` for an all-null chunk. First measure which chunk-safe strategies can produce that (for example `bucketize` with a numeric output), then decide on a pin. V2-LOG unless a probe shows a common config failing.
- F2: once S2 is merged, the CLI CSV writer can lock types to the first chunk again, as CSV-WRITE-FAST wanted (`C:src/decoy/cli/io/_targets.py:740-760`). V2-LOG.
- F3: after S1 and S2 merge, NONFK-OOM's probe table (section 2) and the premise of its AT-A8 need a note. Hand this to that plan's owner.
- F4: the platform's rollback lever still calls `run_mask_pipeline_chunked` (`P:api/jobs/v2_runner.py:409`). The platform is parked, so this is recorded only.
