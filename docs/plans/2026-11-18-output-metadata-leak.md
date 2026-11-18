Status: plan (revision 3, 2026-11-18; Dennis round 1 and Codex plan gate GO-WITH-FIXES addressed)

# OUTPUT-METADATA-LEAK: source Parquet metadata reaches masked output (1.0 leak row)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

A masked output file must not carry text from the source file that masking never looked at. Today the out-of-core route copies the source schema's key/value metadata into the output schema. So a custom key (for example `table_comment` holding an email address) and the whole `b"pandas"` blob, including its `attributes` member (the source DataFrame's `attrs`), are written into the masked file's footer. The V1 bar blocks non-admin leaks, so this row blocks 1.0.

The owner decided on 2026-11-18 that F38 (dataset metadata preserve and redact) stays an opt-in 1.x feature (`C:docs/roadmap/post-1.0-plan.md`, F38 row: "preserving metadata is opt-in"). So the 1.0 default is: strip everything and keep only an allow-list. This plan makes that default true by construction and leaves an additive seam for F38.

Anchors: a path with no prefix is in decoy-engine (under `src/decoy_engine/` for source, the repo root for `tests/` and `docs/`); a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R2: privacy logic and an output-format change), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `bugfix.md` (fail-before proof, root cause), `security.md` (sensitive data out of artifacts, secure default), `cross-cutting-concerns.md` (one choke point plus a guard that walks the syntax tree, a seeded bypass, a shrink-only allowlist), `api-and-compatibility.md` (output bytes change, public additions, room for an opt-in later), `architecture.md` (placement against CODEMAP), `reuse-first.md`, `testing.md` (T0 to T2, mutations, strict xfail for known reds), `proportionality.md`, `scope-discipline.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Revision 2 changes (Dennis round 1: 0 blocker, 2 high, 7 medium, 5 low):

| Finding | Change | Where |
|---|---|---|
| H1 | Each CE cell names its publishing entry and reads the committed file; the helper checks that the engine wrote the file; "stream without a sink" moved to AT-E2 | 8.1, 8.3 |
| H2 | AT-S1 detects `COPY ... TO` in `execute()` SQL, resolving module constants and f-string parts; sites re-counted (7 COPY statements in 3 modules); baseline keyed by module and function; watch set copies the CLI set and adds `sink_parquet`, `write_metadata`, DuckDB relation `write_parquet`, each with a seeded cell | 5.3, 8.2 |
| M1 | Pandas blob closed: `creator` pinned to the running pyarrow, `pandas_version` PEP 440 public form, `pandas_type` a closed enum; forged-member cells | 4.2, AT-M4 |
| M2 | AT-S2 inverted: every schema-metadata argument is `None`, a literal or a direct `sanitized_schema_metadata(...)` call; 4.3 narrowed to the ten explicit copy sites | 4.3, 8.3 |
| M3 | CLI helper declared as a `[[mirror]]` in `C:ci/vendored.toml` | 8.4, 9 |
| M4 | Order section against `plan/freeze-batch` revision 2 (`24b1da552`); Breaking fragment class | 12.1, 6 |
| M5 | AT-M3 is a dtype matrix plus a file-level byte cell; mutation "from_arrays instead of cast" | 8.2 |
| M6 | Subset is a published `TARGET_OUTPUT` with its own baseline category, guarded by CE-9; 5.6 corrected | 5.3, 5.6 |
| M7 | Canaries for the range-index name, key names, forged `creator` and `pandas_version` | 8.1 |
| L1 to L5 | All 11 catalog classes named; physical-seam wording; cloud and DB delivery stated; light facade import; plain changelog text | 13, 3, 1.2, 10, 6 |

Revision 3 changes (Codex plan gate on revision 2: GO-WITH-FIXES; writer inventory and choke points confirmed):

| Finding | Change | Where |
|---|---|---|
| 1 (high) | The pandas blob copies no member because its shape looks valid. Every member is derived from the output Arrow type, the running library versions or a closed registry constant; `pandas_version` is the running pandas version; `num_categories` is dropped; AT-M4 gains forgeries that look valid | 4.2, AT-M4 |
| 2 (high) | The sanitizer takes the final output schema: `sanitized_schema_metadata(meta, *, for_schema)`, called only inside `safe_output`; E2 sites use `attach_output_metadata(schema, meta)`; AT-S2 allowed forms updated | 4.1, 4.3, AT-S2 |
| 3 (high) | One neutral Arrow-to-pandas descriptor registry `_pandas_descriptors.py`, used by native admission and by output sanitizing, each with its own policy; admission behaviour byte-identical (AT-R1) | 4.2, 8.2, 9 |
| 4 (medium) | AT-M1 covers every nested type the stripper supports, each with its own omission mutation; an unhandled nested type fails closed | 4.1, AT-M1 |
| 5 | One-repin order made explicit: no hard dependency; the fallback costs a second CLI repin, recorded | 12.1 |
| 6 | Standing guards (CE-10, CC-4, CC-5) are named outside the mutation claim | 8 |

Owner questions Q1 to Q6 were answered on 2026-11-18 with the recommended answers (section 15).

Risk: R2 overall (privacy logic on every output file; output bytes change for sources that carry metadata). E0 is R1 (tests and a record only). E1 is R2. E2 is R1 (in-memory schema hygiene behind the E1 guarantee). C1 is R2 (CLI output bytes). Approver: Cam (owner) for the plan and the owner questions. Plan gate: Dennis then Codex. Slice review: Codex for E0 and E2; Dennis then Codex for E1 and C1.

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. Every Parquet file that Decoy publishes as output (engine output stages and CLI targets, on every route) carries key/value metadata from a closed allow-list only. In 1.0 the allow-list is one schema-level key, `b"pandas"`, and only in its sanitized form (section 4.2). Any other schema-level key, from any source, is absent.
2. No output field, at any nesting depth, carries field-level key/value metadata. This includes `PARQUET:field_id` and unregistered `ARROW:extension:*` keys.
3. The `ARROW:schema` footer entry is the writer's serialization of the sanitized schema. A canary string placed in the source's schema metadata, field metadata, pandas `attrs` (both the `attributes` member of the pandas blob and the `PANDAS_ATTRS` key that pandas writes) or the pandas column-index name is found nowhere in an output file: not in the raw bytes, not in any decoded footer value, not in the base64-decoded `ARROW:schema`.
4. Masked values, row order, column names, Arrow types, nullability and row-group layout do not change. An output from a source with no custom metadata and no `attrs` is byte-identical to today's output on the resident route.
5. The rule has one choke point in the engine (`safe_output.output_schema`, applied inside the output writers of `fileaccess/adapters/arrow.py`) and one in the CLI (the writers of `C:src/decoy/cli/io/_targets.py`, which call the engine's public function). A sentry in each repo fails on a Parquet write that bypasses it.
6. Room for F38: the allow-list is one registry in one module, and the public functions can take a keyword-only policy argument later without breaking any caller. Nothing in 1.0 preserves source metadata.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- F38 itself (an opt-in preserve or redact policy). 1.x.
- A Decoy provenance key in output files (owner Q3, recommended no).
- Field-level metadata and `df.attrs` on in-memory results returned to a Python caller (`RunResult` tables, SDK DataFrames), including `attrs` that `Table.from_pandas` writes into the pandas blob of an in-memory table (Q5, decided). The caller already holds the source. E2 cleans the ten explicit copy sites in memory as hygiene; the guarantee is about files.
- Intermediate files that Decoy never publishes: scratch spill, the isolated child's source handoff, declared-cast staging, the out-of-core key stage, vault segments inside the encrypted vault. The sentry lists each by name with a reason (owner Q4).
- Registered Arrow extension types (for example `arrow.uuid`, `arrow.opaque`). Their parameters are type information and stay. An unregistered extension arrives as storage type plus `ARROW:extension:*` field metadata, which is stripped (canary cell CE-7).
- A stale pandas blob on masked columns (the source `pandas_type` on a column whose type masking changed). A correctness item for ROUTE-OUTPUT-CONTRACT, not a leak; recorded as a follow-up.
- Platform writers (parked with the platform).
- Cloud and database delivery. No CLI or engine route writes a Parquet target to object storage or a database today; `_targets.py` writes local files only. A later cloud or database writer must go through the `_targets.py` writers (CC-6 and G-ONE-TARGET-WRITE fail otherwise).
- CSV and fixed-width outputs: they have no key/value metadata (investigation at `ad36687a6`; cells CE-10 and CC-5 keep that true).

## 2. Established solutions

Search run on 2026-11-18: web search for stripping Parquet schema and field metadata with pyarrow, and for metadata-anonymization tools; in-codebase search for existing allow-lists of Parquet metadata. A local probe at pyarrow 24.0.0 and pandas 2.3.3 (the engine venv) confirmed three facts used below: `Table.from_pandas` writes `attributes` into the pandas blob; `DataFrame.to_parquet` also writes a separate `PANDAS_ATTRS` key; field metadata is absent from the raw file bytes and present only inside the base64 `ARROW:schema` value.

| Need | Established solution | What we take | What we do not take, and why |
|---|---|---|---|
| Remove metadata from an output file safely | MAT/mat2, the Metadata Anonymisation Toolkit (arXiv 1212.3648; mat2 man page): remove as much as possible, because a scan for known fields cannot find every field in a complex format | Rebuild the output schema from a closed allow-list | A deny-list of keys (`table_comment`, `PANDAS_ATTRS`): the next producer invents a new key |
| Where Arrow puts metadata in Parquet | Arrow docs, "Reading and Writing the Apache Parquet Format"; ARROW-8980 and ARROW-9009 (schema metadata is stored as Parquet key/value pairs and again inside the base64 `ARROW:schema` flatbuffer; `store_schema` controls the second) | Sanitize the Arrow schema before the writer is built, so both copies are clean; the canary decodes `ARROW:schema` with `pa.ipc.read_schema` | `store_schema=False`: it would lose time zones, large types and dictionary types on read |
| Writer schema vs batch schema | pyarrow `ParquetWriter`: the footer comes from the writer's schema; `write_table` compares schemas with `check_metadata=False` | Sanitize at writer construction; batch metadata cannot reach the footer (probe confirmed) | Sanitizing every batch (cost per batch, no benefit) |
| Closed allow-list for the pandas blob | The engine's own closed allow-list for pandas metadata in native admission (`execution/native/_faker_deterministic_admission.py:250-270`; `docs/compatibility-contract.md` lines 812-816) and the one strict JSON parser `strict_json_loads` (`tests/sentry/test_strict_json_single_parser.py`) | Same pattern: parse strictly, keep a closed member set with typed values, re-encode | Regenerating the blob through a pandas round trip of an empty table: pandas on the write path, plus an exception fallback for stale blobs |
| Input validation stance | OWASP Input Validation Cheat Sheet (allow-list over deny-list) | Unknown key, wrong type or malformed JSON is dropped, never raised | |

Remaining custom code: about 130 lines (the sanitizer and the pandas-blob filter). No library offers a Parquet output metadata allow-list; pyarrow gives the primitives (`pa.schema`, `Field.remove_metadata`, `Table.cast`).

## 3. Reuse inventory

- `decoy_engine.fileaccess.adapters.arrow` (`write_table`, `parquet_writer`, `_FileBacked`): the output writers call them; staging, `guarded` error mapping and file modes are unchanged.
- `execution._transactional_sink.StagedParquetWriter` and `publication._publish` (F22): the engine output writers; only the adapter call changes.
- `strict_json_loads` for the pandas blob.
- The file-access sentry resolver (`tests/sentry/fa/`, `tests/sentry/_call_resolution.py`) to resolve Parquet sink calls through aliases and re-exports.
- Test kit `tests/unit/execution/_transform_testkit.py` (`fk_config`, `fk_tables`, `single_table_config`) for the route cells.
- CLI G-ONE-TARGET-WRITE (`C:tests/sentry/io_policy/test_target_writes.py`, shared scanner `C:tests/sentry/io_policy/_calls.py`): it already pins every table write to `C:src/decoy/cli/io/_targets.py`; C1 extends it instead of adding a second walker.
- Physical-seam diff gate (`tests/sentry/test_physical_seam_disconnection.py`): every execution file E1 and E2 touch is already in its permitted set at `ad36687a6`. The builder confirms. If one is missing, it is added through the standard permitted-set process (one reasoned line, reviewed at the gate). That is the normal allowlist path for a changed file, not a cap or baseline raise.

## 4. Behaviour

### 4.1 One function, two callers

`safe_output/_file_metadata.py` (new) owns the rule:

- `output_schema(schema: pa.Schema) -> pa.Schema`: first builds a metadata-free schema with the same names, types and nullability. Every field is stripped recursively through struct, list, large_list, fixed_size_list, list_view, large_list_view, map (key and item fields), dense and sparse union, and the value type of a dictionary. A nested type outside this list raises `TypeError` (a code defect, fail closed; a test enumerates pyarrow's nested type predicates so a new pyarrow nested type turns that test red). Then it attaches `sanitized_schema_metadata(schema.metadata, for_schema=<the metadata-free schema>)`.
- `output_table(table: pa.Table) -> pa.Table`: `table.cast(output_schema(table.schema))` when the two schemas differ under `check_metadata=True`, else `table` itself. Types are equal, so the cast copies no buffers.
- `sanitized_schema_metadata(meta, *, for_schema: pa.Schema) -> dict[bytes, bytes] | None`: applies `_ALLOWED_SCHEMA_KEYS`, a mapping from key to its sanitizer. 1.0 holds one entry, `b"pandas": _sanitize_pandas_blob`. Any other key is dropped. `None` when nothing remains. `for_schema` is the final output schema; the pandas sanitizer reads field names and Arrow types from it, never from `meta`. Called only inside `safe_output`.
- `attach_output_metadata(schema: pa.Schema, meta) -> pa.Schema`: returns `schema` with its schema metadata replaced by `sanitized_schema_metadata(meta, for_schema=schema)` (or removed when that is `None`). Field metadata is left as it is (in memory, Q5). The in-memory entry for E2.
- Public: `decoy_engine.output_schema` and `decoy_engine.output_table` (root facade exports, for the CLI). F38 can add `*, policy=` to both later.

Callers:

- Engine output writers. `fileaccess/adapters/arrow.py` gains `write_output_table(table, txn, component)` and `output_parquet_writer(txn, component, schema)`. They call `output_table` or `output_schema`, then the existing `write_table` or `parquet_writer`. `StagedParquetWriter.write`, `StagedParquetWriter.write_batches` and `publication/_publish.py:448` switch to them. At `ad36687a6` these are every engine output Parquet site (section 5.3).
- CLI writers (C1). The two Parquet branches of `C:src/decoy/cli/io/_targets.py` (`_write_table` at lines 407-409, `write_chunked_output` at line 537) write `output_table(...)` or build the writer from `output_schema(...)`. A DataFrame is first converted with `pa.Table.from_pandas(df, preserve_index=False)`, so pandas never writes its own `PANDAS_ATTRS` key.

### 4.2 The sanitized pandas blob

Rule: no member is copied because its shape looks valid. Each written value is derived from (a) the output schema `for_schema`, (b) the running pyarrow and pandas versions, or (c) a constant of the descriptor registry. The source blob is used only to choose among registry constants that are all correct for the output Arrow type (for example `int64` or `Int64` for an Arrow int64), so it can tell the reader which pandas dtype to rebuild and cannot carry free text or a number.

The source blob is parsed with `strict_json_loads`. If it is not a JSON object, the output has no `b"pandas"` key (fail toward stripping; no error). The one string check left (an `index_columns` entry naming an output field) is an exact equality against `for_schema` names.

Descriptor registry: `src/decoy_engine/_pandas_descriptors.py` (new, a bottom leaf that imports only `pyarrow`). It holds, per Arrow type, the closed set of `(pandas_type, numpy_type)` pairs pyarrow writes for that type at the pinned version, the first pair being pyarrow's default; the column-index entry; and the per-type metadata builder (timezone from a timestamp type, `ordered` from a dictionary type, `precision` and `scale` from a decimal type). Native admission (`execution/native/_faker_deterministic_admission.py:117-145`) imports its `_PANDAS_TYPE_TABLE` pairs and `_COLUMN_INDEX_SHAPE` from it: admission's policy (exact match on the default pair, decline otherwise) and the output policy (choose a listed pair, or the default) stay in their own modules. There is one table.

| Member | Rule |
|---|---|
| `columns` | rebuilt, one entry per field of `for_schema` whose Arrow type is in the registry, in schema order. `name` and `field_name` are the output field name. `(pandas_type, numpy_type)` is the registry pair the source entry for that field names, if the source pair is equal to one of the listed pairs for the output Arrow type; else the registry default. `metadata` is built from the output Arrow type only: `timezone` from a timestamp type's tz, `ordered` from a dictionary type, `precision` and `scale` from a decimal type, `encoding: "UTF-8"` where pyarrow writes it; otherwise `null`. `num_categories` is never written (it is a count of source categories, and a writer built from a schema has no data). A field whose type is not in the registry gets no entry |
| `index_columns` | entries that are strings equal to a field name of `for_schema` are kept (the value written is the output field name); every range-index object is dropped (its `name` is user text and its `stop` is a source row count) |
| `column_indexes` | replaced with pyarrow's default single entry (`name` null, `field_name` null, `pandas_type` `"unicode"`, `numpy_type` `"object"`, `metadata` `{"encoding": "UTF-8"}`) |
| `creator` | always written as `{"library": "pyarrow", "version": pyarrow.__version__}` of the running process; the source's value is never copied |
| `pandas_version` | always the running pandas version (`importlib.metadata.version("pandas")`, read once at first use, so the facade import stays light); the source's value is never copied |
| `attributes` and any other member | dropped |

The JSON is encoded the way pyarrow writes it (`json.dumps` with default separators, members in pyarrow's order). A blob that pyarrow wrote in the same process for a frame with no `attrs`, no column-index name, no categorical column and `preserve_index=False` comes out byte-identical. AT-M3 pins that; for categorical columns it pins the dtype round trip instead (`num_categories` is gone).

### 4.3 Carriers in memory (E2)

Scope: the ten explicit copy sites of section 5.1, and no more (Q5). The six out-of-core builders copy `source_schema.metadata` or `batch.schema.metadata` into a new schema. `execution/_transforms_table.py:120` keeps every non-pandas source key. `execution/_faker_degenerate_pin.py:214` passes the rest of the source metadata through. E2 changes each to build the schema without metadata and then call `attach_output_metadata(schema, source_meta)`, so the blob is derived from the schema the site actually builds, and in-memory tables built by the engine carry no custom schema key and no `attributes`. Field metadata in memory stays as it is (passthrough columns are the source field by contract, `docs/compatibility-contract.md` line 852); the writers strip it.

### 4.4 Errors and logs

No new refusal and no new reason code. The sanitizer never raises on metadata content. No log line names a metadata key or value.

## 5. Enumerations

### 5.1 Carrier sites at `ad36687a6` (source metadata copied into an output schema)

| Site | Carries | Slice |
|---|---|---|
| `execution/out_of_core/_rewrite_pass.py:377` | `source_schema.metadata` | E2 |
| `execution/out_of_core/_stream_driver_support.py:83`, `:110`, `:131` | source and batch schema metadata; passthrough field metadata ("metadata included") | E2 |
| `execution/out_of_core/_mask.py:482` | `batch.schema.metadata` | E2 |
| `execution/out_of_core/_emit.py:257` | `template.metadata` | E2 |
| `execution/out_of_core/_batch_join.py:357` | `batch.schema.metadata` | E2 |
| `execution/out_of_core/_stream_join_cursors.py:431-434` | field metadata and `batch.schema.metadata` | E2 |
| `execution/_transforms_table.py:120` | every non-pandas source key (resident route with transforms) | E2 |
| `execution/_faker_degenerate_pin.py:214` | all source keys, pandas blob patched | E2 |
| `execution/_chunked_output_sink.py:398`, `:431`, `:591` | strips schema metadata (`replace_schema_metadata(None)`, `remove_metadata`); field metadata kept | none (the writer covers it) |
| `C:src/decoy/cli/io/_targets.py:537` | the first chunk's schema as is | C1 |

### 5.2 Exit paths

- Success: the file is written with the sanitized schema (every route).
- Pandas blob not a JSON object, not UTF-8, or failing a member rule: the blob (or the entry) is dropped; the write succeeds (AT-M4).
- A key that is not in `_ALLOWED_SCHEMA_KEYS`: dropped (AT-M2).
- `table.cast` to the sanitized schema does not fail for a valid table (same types). Any `ArrowInvalid` from the write propagates as the existing write failure through `guarded` and `capture_publication_failure` (`execution/_transactional_sink.py:222`), unchanged.
- `OSError` on the stage: unchanged (`fileaccess/adapters/arrow.py:97-110`).

### 5.3 Routes and write sites

Engine output writers (each goes through the choke point after E1):

- `StagedParquetWriter.write` (`execution/_transactional_sink.py:222`): resident results staged by the reference sink, and the isolated route's child writes (`execution/_isolated_common.py:476`).
- `StagedParquetWriter.write_batches` (`execution/_transactional_sink.py:271`): out-of-core (`execution/out_of_core/_emit.py:105`, `:127`), stream mode with a sink, the chunked output sink (`execution/_chunked_output_sink.py:597`), streamed generation (`generation/_streamed.py:525`).
- `publication/_publish.py:448` (F22 `publish_unit`).
- `subset/_materialize.py:69` (`polars_adapter.write_parquet`, which is `fileaccess/adapters/polars.py:36`): a published output (`FileRole.TARGET_OUTPUT`, `subset.output_dir`). A Polars frame read with `scan_parquet` carries no Arrow key/value metadata, so it is not routed through the Arrow output writers. It has its own baseline category, `published-polars` ("published; Polars writes no source metadata"), separate from the intermediate rows, and cell CE-9 guards it. A Polars pin bump re-runs CE-9 (it is in the pin bump's T1 set through `tests/security/`). If CE-9 is red on the base, E1 routes it through `write_output_table(frame.to_arrow(), ...)` and the category row is deleted.

Intermediate writers (baseline category `intermediate`, keyed by module and function, with a reason; not sanitized): `vault.py:363` (encrypted segment buffer), `execution/_isolated_commit.py:165` (source handoff to the isolated child), `execution/out_of_core/_stage.py` (masked-key stage), `declared_casting/_stream.py:168` and `:179` (typed source staging), `execution/native/_pool_quality.py` (scratch), `connectors/postgres_snapshot.py` `_export_relation` (source snapshot, `COPY` at line 332, called from `snapshot_tables_to_parquet` at line 375).

DuckDB `COPY ... TO` statements at `ad36687a6` (7 in 3 modules; all scratch or source, none published). The format comes from the module constant `PRIVATE_COPY = "FORMAT PARQUET, USE_TMP_FILE false"` (`execution/out_of_core/_duckdb.py:27`), imported as `_PRIVATE_COPY` and placed in f-strings:

| Module | Function | Lines |
|---|---|---|
| `execution/out_of_core/_relation.py` | `_build_relation` | 521, 525-530, 537-543 |
| `execution/out_of_core/_multi_parent.py` | `merge_parent_relations` | 154, 158-162, 168-174 |
| `connectors/postgres_snapshot.py` | `_export_relation` | 332-333 (format written inline) |

CLI writers: `C:src/decoy/cli/io/_targets.py` `_write_table` (DataFrame `to_parquet` at line 407, `pq.write_table` at line 409) and `write_chunked_output` (`ParquetWriter` at line 537); `write_private_table` (unmask, detokenize) shares `_write_table`. `C:src/decoy/api.py:268` writes the caller's own DataFrame into a private spool as a source: input side, not an output.

Route matrix for the canary (E0): full_frame, sequential, stream without a sink, stream with a sink, out_of_core FK, auto-chunk native dispatcher, resident with transforms, mixed generate and mask, subset, isolated, declared casting on, F22 `publish_unit`, and a zero-row source on out_of_core and chunked.

### 5.4 FK shapes

- Single-column parent and child (`fk_config`): the investigator's red repro; the FK child column is a carrier at `_stream_driver_support.py:131`.
- Multi-parent and composite FK on out-of-core (`_multi_parent.py`, `_batch_join.py:357`): one cell each in E0, so every out-of-core builder in 5.1 is reached by a test.
- The FK shape does not change the rule: the writer strips whatever schema the route built.

### 5.5 Fields

- Schema level: every key other than `b"pandas"` dropped; `b"pandas"` sanitized (4.2).
- Field level: all keys dropped at every depth, including `PARQUET:field_id`, `ARROW:extension:name` and `ARROW:extension:metadata` (unregistered extension), and custom keys.
- Pandas blob members: `columns`, `index_columns`, `column_indexes`, `creator`, `pandas_version` kept under rules; `attributes` and anything else dropped.
- `PANDAS_ATTRS` (written by `DataFrame.to_parquet` when `attrs` is set): dropped as a non-allowed key, and never produced by the CLI after C1.

### 5.6 Output surfaces

- Engine output Parquet files (all routes in 5.3).
- CLI target Parquet files (`decoy run`, `decoy run --chunked`, `decoy unmask`, `decoy detokenize`, subset outputs).
- Subset output Parquet files (`subset/_materialize.py:69`, published, Polars).
- In-memory tables returned by the engine (schema level, the ten copy sites only, E2).
- Not changed: CSV, fixed width, run results, `--json`, logs, progress events, reports, the vault file format.

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Output Parquet key/value metadata | route-dependent; out-of-core copies the source's | allow-list v1: `b"pandas"` sanitized, nothing else; no field metadata | new row in `docs/frozen-surfaces.md`; `docs/security/output-metadata.md` (new) |
| Output bytes | | change only for sources with custom metadata, `attrs`, field metadata, a column-index name or a range index; masked values unchanged | `Breaking:` changelog fragment and a shape-changelog entry (the freeze batch's class for output-byte changes, so `check_shape_changelog.py` passes at REL-GATE G3). Plain text: "Out-of-core output files written from pandas-made sources change bytes: the source's pandas metadata is replaced by a cleaned copy, and custom keys and field metadata are removed." |
| Route metadata difference in `docs/compatibility-contract.md` (lines 820-856) | full-frame carries pandas metadata, chunked none, passthrough field metadata kept | field metadata gone on every route; the schema metadata difference narrows to "sanitized pandas blob or none" | E1 updates those paragraphs |
| Public API | | adds `output_schema`, `output_table` (additive) | `src/decoy_engine/__init__.py`; public boundary sentry |
| CLI | | Parquet target bytes as above; no flag, exit code or `--json` change | `C:CHANGELOG.md` |
| F38 seam | | `output_schema(schema, *, policy=...)` may be added later with the strip default; additive | `docs/security/output-metadata.md` "Later" note |

Golden and determinism checks compare values, or hash outputs written from metadata-free fixtures. If a byte hash of an out-of-core output moves in E2 (the copied pandas blob becomes the sanitized one), the hash is re-pinned in the same slice with the reason "metadata only, values equal", and the value-level parity test stays as it is. No threshold, cap or baseline is raised.

## 7. Failure modes

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | Custom schema key in the source | absent from output on every route | CE cells, AT-M2 |
| FM-2 | `df.attrs` on the source (blob `attributes` and `PANDAS_ATTRS`) | absent | CE cells, AT-M3 |
| FM-3 | Field metadata on a passthrough, masked or FK column, or on a nested child | absent | CE-3, CE-6, AT-M1 |
| FM-4 | Malformed or oversized pandas blob | blob dropped, write succeeds | AT-M4 |
| FM-5 | Pandas blob names a column the output lacks, or a range index | entry dropped | AT-M5 |
| FM-6 | A new output writer added later that skips the choke point | engine sentry red | AT-S1 |
| FM-7 | A new carrier `metadata=<x>.metadata` added in `src/` | carrier sentry red | AT-S2 |
| FM-8 | Batches carry metadata the writer schema lacks | the footer has none (writer schema governs); `write_batch` accepts (`check_metadata=False`) | AT-M6 |
| FM-9 | Zero-row source on out-of-core or chunked | zero-row file with the sanitized schema | CE-8 |
| FM-10 | CLI DataFrame path | converted with `from_pandas(preserve_index=False)`; no `PANDAS_ATTRS` | CC-2 |
| FM-11 | Clean source | bytes identical to today on the resident route | AT-M3 |
| FM-12 | A canary visible only after base64 decoding (field metadata lives only inside `ARROW:schema`) | the canary helper decodes `ARROW:schema`; a raw-bytes grep alone is not accepted | AT-C0 |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the final slice head. Standing guards are outside that claim: CE-10, CC-4 and CC-5 are expected green on the base and have no mutation; they stop a later regression (a CSV header comment, a CLI route that bypasses the writers) and are listed as guards in the slice gate record.

### 8.1 E0: the canary across all routes (settles the unknowns)

Helper `tests/security/_metadata_canary.py`:

- `canary_sources(tmp_path)`: writes parent and child Parquet sources with one canary per carrier: `DCY-CANARY-SCHEMA` (schema key `table_comment`), `DCY-CANARY-ATTRS` (`df.attrs`, so both `attributes` and `PANDAS_ATTRS`), `DCY-CANARY-FIELD` (field metadata on every column, including the unconfigured passthrough `n`, the masked `note` and the FK `parent_id`), `DCY-CANARY-COLIDX` (`df.columns.name`), `DCY-CANARY-NESTED` (child-field metadata in a struct column, on routes that admit structs), `DCY-CANARY-EXT` (`ARROW:extension:name` on a storage column).
- More canaries (M7): `DCY-CANARY-RIDX` (a named RangeIndex, written with `preserve_index=None` so pyarrow stores it as a range-index object); `DCY-CANARY-SKEY` and `DCY-CANARY-FKEY` as the key names of a schema-metadata entry and of a field-metadata entry; `DCY-CANARY-CREATOR` and `DCY-CANARY-PDVER` as forged `creator.library`, `creator.version` and `pandas_version` members of the pandas blob.
- `canaries_in(path) -> set[str]`: the canaries found in (1) the raw file bytes, (2) every footer key and value, (3) the schema and every field (recursive), keys and values, of `pa.ipc.read_schema` over the base64-decoded `ARROW:schema`, (4) the parsed pandas blob.
- `assert_engine_wrote(path, run_start)`: the file is the committed output the entry under test reports (the `CommitReceipt` path, `TransactionalSink.committed_table_path`, the `publish_tables` result, or the subset `output_dir` listing), its mtime is after `run_start`, and the test never wrote to that path. A cell whose route publishes no file fails this check instead of passing on an empty set.

Each CE cell names its publishing entry and reads the file that entry committed:

| Entry | Used by |
|---|---|
| `run_pipeline(..., sink=TransactionalSink)` (`execution/_pipeline.py:115`), file from `committed_table_path` | CE-1 to CE-8 except the cells below |
| `publish_tables` (`publication/_publish.py:419`, write at `:448`) | the F22 cell of CE-6 |
| the isolated stage commit (`execution/_isolated_commit.py:112`, `TARGET_OUTPUT` `output_dir`) | the isolated cell of CE-6 |
| `materialize_subset` `output_dir` (`subset/_materialize.py:32`) | CE-9 |

| Id | Test | Red on base because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-C0 | `tests/security/test_metadata_canary_helper.py`: the helper finds each canary in a file written with it, including a field-metadata canary that is absent from the raw bytes | new helper | drop the `ARROW:schema` decode step (the field cell then misses the canary) | E0 |
| CE-1 | `tests/security/test_output_metadata_canary.py::test_route[out_of_core_fk]` (`fk_config`, `execution_mode="out_of_core"`): `canaries_in(output) == set()` for both tables | the investigator's repro: SCHEMA and ATTRS found | revert `output_parquet_writer` to the raw adapter | E0 (strict xfail), E1 flips |
| CE-2 | same test, `full_frame`, `sequential` (each through `run_pipeline(sink=TransactionalSink)`) | unknown, settled by E0 | as CE-1 for any cell red on the base | E0 |
| CE-3 | same test, `stream` with a `TransactionalSink` | unknown (field metadata through `_chunked_output_sink.py:386`) | as CE-1 | E0 |
| CE-4 | same test, auto-chunk native dispatcher (companion lane) | unknown (passthrough is "the source column exactly") | as CE-1 | E0 |
| CE-5 | same test, resident with a transform op | `_transforms_table.py:120` keeps custom keys | as CE-1 | E0 |
| CE-6 | same test, mixed generate and mask; isolated; declared casting on; F22 `publish_unit`; multi-parent and composite FK out-of-core | unknown | as CE-1 | E0 |
| CE-7 | unregistered-extension column on full_frame and out_of_core | unknown | as CE-1 | E0 |
| CE-8 | zero-row source on out_of_core and chunked | unknown | as CE-1 | E0 |
| CE-9 | subset output | expected green (Polars) | write the subset frame with the source schema attached | E0 |
| CE-10 | CSV target on out_of_core: no canary in the file | standing guard, expected green | none (standing guard) | E0 |

E0 rule: every cell red on the base is marked `pytest.mark.xfail(strict=True, reason="OUTPUT-METADATA-LEAK: <canary set>")`, so it stays visible and fails the suite the moment it turns green without the marker being removed. E0 also writes `docs/records/2026-11-<dd>-output-metadata-canary.md`: the full matrix (route by carrier, red or green) from one Linux VM run (`VMRUN_LINUX=1 ~/bin/vm-run engine <wt> 'pytest tests/security/test_output_metadata_canary.py -rxX'`) plus the companion-lane run for CE-4. If a cell needs a route the test kit cannot reach, the record says so and lists it as a follow-up; it is not dropped silently.

### 8.2 E1: the choke point

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-M1 | `tests/unit/safe_output/test_file_metadata.py::test_fields_stripped_recursively[type]`, one cell per supported nested type, each with metadata on the nested child and on `PARQUET:field_id`: struct, list, large_list, fixed_size_list, list_view, large_list_view, map key, map item, dense union, sparse union, dictionary value; plus `::test_nested_types_enumerated` (every pyarrow `pa.types.is_*` nested predicate at the pin maps to a handled case, and an unhandled nested type raises `TypeError`) | no function | strip top-level fields only; and one omission mutation per type (drop the large_list branch, drop the fixed_size_list branch, drop the map item branch, and so on), each turning only its own cell red | E1 |
| AT-M2 | `::test_only_allowed_schema_keys` (custom key, `PANDAS_ATTRS`, non-UTF-8 key bytes) | no function | add `b"PANDAS_ATTRS"` to `_ALLOWED_SCHEMA_KEYS` | E1 |
| AT-M3 | `::test_pandas_blob_sanitized` (`attributes` gone, column-index name gone) and `::test_clean_blob_identical[dtype]` over a dtype matrix: categorical, tz-aware datetime, decimal, nullable `Int64`, `string[pyarrow]`, non-ns datetime (`datetime64[ms]`), bool, and non-ASCII column names. For a frame with no `attrs`, `sanitized_schema_metadata(Table.from_pandas(df, preserve_index=False).schema.metadata)` equals the input bytes, and a round trip through `read_pandas` gives the same dtypes. File-level cell `::test_clean_file_identical`: `StagedParquetWriter.write` output bytes equal raw `pq.write_table` bytes for the same clean table | no function | keep `attributes`; re-encode with other separators (identity cells turn red); build the output table with `pa.Table.from_arrays(table.columns, schema=...)` instead of `cast` (keeps nested child field metadata; the nested cell of AT-M1 and the file-level cell turn red) | E1 |
| AT-M4 | `::test_forged_blob_not_copied`. Shape forgeries: not JSON, a JSON list, NaN, a 1 MiB string, wrong member types, a string ending in `"\n"`. Forgeries that look valid: `numpy_type: "DCY-CANARY"`, and a plausible but wrong `numpy_type` (`"int32"` on an Arrow int64); a numeric secret (`314159265`) in `precision`, `scale` and `num_categories`; `pandas_version: "9.9.9"` and `creator: {"library": "pyarrow", "version": "99.0.0"}`; `pandas_type: "decimal"` on an Arrow string; an `index_columns` string that names no output field. Each cell asserts the output blob equals the blob derived from the output schema alone (the canary or number is absent) | no function | keep any `numpy_type` that fullmatches the old pattern (the `DCY-CANARY` cell turns red); copy `precision` from the source (the numeric cell turns red); copy `pandas_version` (the version cell turns red); copy `creator` | E1 |
| AT-R1 | `tests/unit/execution/native/test_admission_descriptor_parity.py`: a fixed corpus of schemas (every row of the old `_PANDAS_TYPE_TABLE`, the column-index shape, unlisted types, forged pairs, extension and field-metadata cases) gives the same admission decision and reason code before and after the move; written and green on the E1 base first, then kept green. The registry's admission view equals the old 13 pairs | new test | change one admission pair in the registry (an int64 row) | E1 |
| AT-M5 | `::test_blob_entries_follow_output_schema` (unknown `field_name`, range index, `name` differing from `field_name`) | no function | keep range-index objects | E1 |
| AT-M6 | `tests/fileaccess/test_output_writers.py`: `output_parquet_writer` with a dirty schema and dirty batches writes a clean footer; `write_output_table` likewise; a clean table passes through without a copy (same buffer addresses) | no output writers | sanitize the batches but build the writer from the raw schema | E1 |
| AT-S1 | `tests/sentry/defects/test_output_metadata_choke_point.py`: walks `src/decoy_engine` with the file-access resolver. Watch set: the full CLI G-ONE-TARGET-WRITE Parquet set (`pyarrow.parquet.write_table`, `ParquetWriter`, `write_to_dataset`; `pyarrow.dataset.write_dataset`), plus `pyarrow.parquet.write_metadata`, `DataFrame.to_parquet`, Polars `DataFrame.write_parquet` and `LazyFrame.sink_parquet`, the Arrow and Polars adapter writers, DuckDB relation `.write_parquet`, and `execute()` / `sql()` calls whose SQL contains `COPY ... TO`. The SQL check joins string literals and f-string constant parts and resolves a `Name` or imported name bound to a module-level string constant (so `_PRIVATE_COPY` from `out_of_core/_duckdb.py:27` is seen). Every hit is inside an output writer of `fileaccess/adapters/arrow.py`, or matches a row of `tests/sentry/baselines/parquet-intermediate-writers.json` keyed by (module, function) with a category (`intermediate` or `published-polars`) and a reason, and a count per key. The baseline is shrink-only through `scripts/dev/ratchet_check.py`. At `ad36687a6` the COPY hits are the 7 statements in 3 functions of 5.3. Covered spellings, each with one seeded cell that fails: direct attribute call, `from pyarrow.parquet import write_table as w`, module alias, adapter call through `arrow_adapter`, `write_dataset`, `write_metadata`, `sink_parquet`, DuckDB `relation.write_parquet`, COPY in a plain literal, COPY with the format in an imported constant, COPY split across f-string parts. The output writers themselves must call `output_schema` or `output_table` (seeded cell removes the call) | no sentry | switch `StagedParquetWriter.write` back to `arrow_adapter.write_table` | E1 |
| AT-E1 | E0's CE cells for engine routes lose their xfail markers and pass | leak | revert `_publish.py:448` to the raw adapter (the F22 cell of CE-6 turns red) | E1 |
| AT-P1 | `tests/sentry/test_public_import_boundary.py` and `tests/sentry/test_ga_stub_exports.py` list `output_schema` and `output_table` | not exported | drop one export | E1 |

### 8.3 E2: carriers in memory

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-S2 | `tests/sentry/defects/test_metadata_carrier.py`: AST walk of `src/decoy_engine`. Every schema-metadata argument (the `metadata=` keyword or second positional of `pa.schema`, `pa.record_batch`, `pa.RecordBatch.from_arrays`, `pa.Table.from_arrays`, `pa.Table.from_batches` schema built inline, and the argument of `replace_schema_metadata` and `Schema.with_metadata`) must be `None` or a literal. Source metadata reaches a schema only through `attach_output_metadata(schema, meta)`. `sanitized_schema_metadata` may be called only inside `safe_output/` (a call elsewhere fails). A local name (`meta` at `_transforms_table.py:120-122`, the merged dict at `_faker_degenerate_pin.py:214`) fails. Field-level `metadata=` on `pa.field` is out of scope (Q5). Seeded cells: a direct `.metadata` read, a local variable, a dict merge | the ten sites in 5.1 | restore `metadata=source_schema.metadata` at `_rewrite_pass.py:377`; restore `meta` at `_transforms_table.py:122` | E2 |
| AT-E2 | `tests/security/test_output_metadata_canary.py::test_in_memory[out_of_core_fk, resident_transforms, stream_no_sink]`: the returned tables' schema metadata holds no schema-key, attrs-member or creator canary (stream without a sink publishes no file, so it is checked here) | carriers | restore the `_transforms_table.py:120` line | E2 |

### 8.4 CLI (C1)

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| CC-1 | `C:tests/e2e/cli_fmt/test_output_metadata_canary.py`: `decoy run` (plain) on canary sources; no canary in the Parquet targets (same decode as AT-C0; the helper is a `[[mirror]]` of the engine's `tests/security/_metadata_canary.py` in `C:ci/vendored.toml`, header naming the engine path and the differences: import paths only) | `pq.write_table(data)` keeps the table schema | drop `output_table` in `_write_table` | C1 |
| CC-2 | same file, DataFrame write path (`write_private_table` through `decoy unmask`): no `PANDAS_ATTRS`, no `attributes` | `to_parquet` writes `attrs` | restore `data.to_parquet` | C1 |
| CC-3 | same file, `decoy run --chunked`: no canary | the first chunk's schema is used as is | build `ParquetWriter` from `first.schema` | C1 |
| CC-4 | same file, out-of-core FK pipeline through the CLI | engine and CLI both | none extra (covered by E1 and CC-1) | C1 |
| CC-5 | same file, CSV target: no canary | expected green | none (guard) | C1 |
| CC-6 | `C:tests/sentry/io_policy/test_target_writes.py` new rule: inside `WRITERS`, each Parquet sink call takes a value produced in the same function by `output_table` or `output_schema`. Seeded cell (a writer that passes `data` straight to `pq.write_table`) fails | no rule | remove the call in `write_chunked_output` | C1 |

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/_pandas_descriptors.py` | new (E1, about 90 lines): the one Arrow-to-pandas descriptor registry; a bottom leaf importing only `pyarrow`, added to the leaf list in `.importlinter` | Shared bottom leaf modules (the top-level `Path | Purpose` table of `CODEMAP.md`, where `src/decoy_engine/_arrow_types.py` has its row; a new row is added beside it) | `src/decoy_engine/_arrow_types.py` |
| `src/decoy_engine/execution/native/_faker_deterministic_admission.py` | changed (E1, about -30 +3): imports the pairs and the column-index shape from the registry; policy unchanged; file stays in place, already in the physical-seam permitted set | Native companion bridge: `src/decoy_engine/execution/native/` | |
| `tests/unit/execution/native/test_admission_descriptor_parity.py` | new (E1) | Unit tests | existing admission tests |
| `src/decoy_engine/safe_output/_file_metadata.py` | new (E1, about 150 lines) | Safe output boundary: `src/decoy_engine/safe_output/_<output concern>.py` | `safe_output/_event.py` |
| `src/decoy_engine/safe_output/__init__.py` | changed (E1): re-exports | same | |
| `src/decoy_engine/fileaccess/adapters/arrow.py` | changed (E1, about +25): `write_output_table`, `output_parquet_writer` | Secret providers, file access | `write_table`, `parquet_writer` |
| `src/decoy_engine/execution/_transactional_sink.py`, `src/decoy_engine/publication/_publish.py` | changed (E1, two or three lines each) | Pipeline spine and routes; Publication | |
| `src/decoy_engine/__init__.py` | changed (E1): two exports | Public API | |
| six `execution/out_of_core/` modules, `execution/_transforms_table.py`, `execution/_faker_degenerate_pin.py` | changed (E2, one line each plus an import; no file moves) | Out-of-core FK; Pipeline spine and routes | |
| `tests/security/_metadata_canary.py`, `tests/security/test_metadata_canary_helper.py`, `tests/security/test_output_metadata_canary.py` | new (E0) | Safe output boundary tests: `tests/security/` | `tests/security/test_value_free_errors.py` |
| `tests/unit/safe_output/test_file_metadata.py` | new (E1) | Safe output boundary tests: `tests/unit/safe_output/` | `test_event_fields.py` |
| `tests/fileaccess/test_output_writers.py` | new (E1) | Unit tests (listed exception folder `tests/fileaccess/`) | `tests/fileaccess/test_x3_classification.py` |
| `tests/sentry/defects/test_output_metadata_choke_point.py`, `tests/sentry/defects/test_metadata_carrier.py`, `tests/sentry/baselines/parquet-intermediate-writers.json` | new (E1, E2) | Sentry test: recurring-defect class rules in `tests/sentry/defects/`; baselines in `tests/sentry/baselines/`, registered in `scripts/dev/sentry_registry.toml` and `tests/sentry/_baseline_sources.py` | `tests/sentry/defects/test_canonical_json_choke_point.py` |
| `docs/security/output-metadata.md` | new (E1) | Feature and contract docs | `docs/security/token-vault.md` |
| `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`, the output checklist in `docs/qa/` | changed (E1) | Feature and contract docs; QA checklists | |
| `docs/records/2026-11-<dd>-output-metadata-canary.md` | new (E0) | Plans, decisions, records | |
| `changelog.d/output-metadata-allow-list.md` | new (E1) | Changelog fragments | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `C:src/decoy/cli/io/_targets.py` | changed (about +15) | Source readers and target writers: `src/decoy/cli/io/` | |
| `C:tests/e2e/cli_fmt/test_output_metadata_canary.py`, `C:tests/e2e/cli_fmt/_metadata_canary.py` (a `[[mirror]]` entry: the CLI has no `tests/security/`, and a `[[vendored]]` entry needs the same path in both repos) | new | `tests/e2e/cli_fmt/` | the existing cli_fmt e2e tests |
| `C:tests/sentry/io_policy/test_target_writes.py` | changed | `tests/sentry/io_policy/` | |
| `C:CHANGELOG.md`, `C:ci/vendored.toml` | changed | | |

## 10. Design notes

- Choke points.
  - Engine files: `safe_output.output_schema` is the only place that decides output metadata, and the output writers in `fileaccess/adapters/arrow.py` are the only engine functions that write a published Parquet file. Guard: AT-S1. Mutation: `StagedParquetWriter.write` calls the raw adapter.
  - Engine memory: AT-S2. Mutation: one restored raw carrier.
  - CLI: the `WRITERS` of `_targets.py` (already the only table writers under G-ONE-TARGET-WRITE). Guard: CC-6. Mutation: a writer that skips `output_table`.
- Why at the output writer and not at every Parquet write (the investigator's first suggestion): intermediate files feed logic that reads metadata on purpose (stored pandas index fields in `execution/native/_chunk_schema.py:60`, native admission shape checks at `_faker_deterministic_admission.py:259`, the isolated child reading its sources). Stripping there changes routing and admission, which is not this row. Intermediates are never published. Owner Q4.
- Why also clean the in-memory carriers (E2) when the writer already guarantees files: in-memory tables cross into the CLI and the SDK, and a carrier left in place is how the next writer leaks. It is one line per site and gets its own sentry.
- Why keep a derived pandas blob (owner Q1): without it a pandas reader loses nullable integer and categorical dtypes on round trip, and every resident output's bytes change. A blob derived from the output schema plus a choice among registry pairs keeps those dtypes and keeps clean-source bytes identical (AT-M3), with nothing copied from the source.
- Why one descriptor registry: native admission already maps Arrow types to the exact pandas pair. A second table in `safe_output` would drift from it. The registry holds the facts; admission and output each keep their own policy.
- Why separate output writer functions and not a flag: house style (no flag arguments that switch behavior). `write_output_table` and `write_table` are two named entry points on one core (defect class 8).
- F38 seam: `_ALLOWED_SCHEMA_KEYS` is the one registry, and `output_schema` and `output_table` are the one entry. F38 adds `*, policy: MetadataPolicy = STRIP` and a preserve policy built from the run config, threaded to the output writers. Nothing is pre-built now.
- Logs: none added.
- Facade import (L4): `decoy_engine/__init__.py` and `safe_output/__init__.py` import only `pyarrow` and `strict_json_loads` for the new names; `_file_metadata.py` imports nothing from `execution`, `fileaccess` or `publication`. The import-linter contracts and `tests/sentry/test_public_import_boundary.py` catch a cycle; the builder runs `python -X importtime -c "import decoy_engine"` before and after and reports the delta.

## 11. Size

| Slice | Src lines | Test lines | Docs lines | Files touched |
|---|---|---|---|---|
| E0 | 0 | about +330 | about +60 (record) | 4 |
| E1 | about +250, -30 | about +520 | about +90 | src 8, tests 6, docs 4, baseline 1 |
| E2 | about +20, -10 | about +170 | about +5 | src 8, tests 2 |
| C1 | about +20 | about +260 | about +15 | src 1, tests 3, docs 2 |

New public names: `output_schema`, `output_table` (engine). No product file grows past its size ceiling; `fileaccess/adapters/arrow.py` goes from 143 to about 170 lines.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| E0 | engine | canary helper, route matrix with strict xfail on red cells, record of the matrix | R1 (tests only) | AT-C0, CE-1 to CE-10 | none | T0 on the new files; one Linux VM run plus the companion lane for CE-4; Codex review |
| E1 | engine | `safe_output/_file_metadata.py`, output writers, three call sites, public exports, choke-point sentry and baseline, flip of the engine CE cells, docs, fragment | R2 | AT-M1 to AT-M6, AT-R1, AT-S1, AT-E1, AT-P1 | E0 | T1 impact set (safe_output, fileaccess, publication, transactional sink, out_of_core, chunked, security, sentry) on the head, plus T2: each named mutation. Frozen-contract trigger: one saved-baseline full suite via `decoy-vm-t3` on the merge head. Dennis then Codex |
| E2 | engine | ten carrier sites through `attach_output_metadata`, carrier sentry, in-memory cells | R1 | AT-S2, AT-E2 | E1 | T1 (out_of_core, transforms, faker pin, parity suites unchanged) plus the physical-seam sentry; Codex |
| C1 | CLI | `_targets.py` through `output_table` and `output_schema`, CLI canary e2e, sentry rule, changelog | R2 | CC-1 to CC-6 | the engine release that carries E1, and the CLI repin to it | T1 (`tests/e2e/cli_fmt/`, io_policy sentries, unmask e2e) plus T2 on the head; Dennis then Codex |

Order: E0 now. E1 starts when E0's record exists (the record may add sites to 5.3; it cannot move the choke point). E2 after E1. C1 after the engine release that carries E1; target before the D-4 engine freeze ahead of 2026-12-04. The row closes only when C1 merges.

### 12.1 Order against the freeze batch

Against `plan/freeze-batch` revision 2 (`24b1da552`, `docs/plans/2026-11-18-freeze-batch.md`):

- E1 rebases after freeze X0 merges (X0 changes the frozen-surface map and contract section 1; E1 adds a row to the same map).
- E1 rides the same engine release as freeze O1 and O3, so the output-byte changes reach users in one release with one set of Breaking fragments.
- C1 lands after freeze O2, which changes the same two `_targets.py` write functions (`_write_table`, `write_chunked_output`), and rebases on it. C1 uses the single CLI repin to that engine release; it adds no second repin.
- No hard dependency. E1 is R2 and waits on E0's record, so it may not merge by the time the freeze release is cut, and the freeze batch must not wait for it. Decision: if E1 is merged when the freeze release is cut, it rides that release and C1 uses the single CLI repin. If not, the freeze release ships without E1, E1 takes the next daily release, and C1 needs a second CLI repin to that release. That second repin is the recorded cost of the fallback; it follows the standard repin checklist.

## 13. Recurring-defect class check

- Two copies of a central mechanism: one sanitizer, one registry, one engine writer pair, one CLI writer set; each has a sentry.
- A test weakened to pass: E0's strict xfail markers are removed only by the slice that fixes the cell; the gate diff-checks that no canary assertion changed.
- A grep counted as an enumeration: AT-S1 and AT-S2 walk the syntax tree with alias resolution and prove a seeded bypass per covered spelling.
- Anchored validation: 4.2 has no pattern check left; values are derived or are exact equality against output names and registry pairs; AT-M4 keeps a trailing-newline cell.
- Allowlisted helpers are still checked: the output writers are the allowed sites in AT-S1, and their own bodies must call `output_schema` or `output_table` (a seeded cell removes the call).
- Value exposure (F31 class): metadata text never enters an error or log line.

Catalog `catalogs/recurring-defects.md`, all 11 classes:

1. Anchored validation: no pattern checks in 4.2 (derived values and exact equality only); AT-M4 newline cell.
2. Strict wire and stored types: the pandas blob is parsed with `strict_json_loads` into a closed member set with typed values.
3. No exception context: the sanitizer raises nothing; no new exception.
4. Versioned read models: the pandas blob is read with its own closed rules; `creator` and `pandas_version` come from the running libraries; the descriptor registry is checked against the pinned pyarrow.
5. Normalized guard scanners: AT-S1 and AT-S2 resolve aliases, re-exports, module constants and f-string parts; one seeded cell per spelling.
6. No reaching into private modules: the CLI imports `decoy_engine.output_table` and `output_schema`, never `safe_output._file_metadata`.
7. No hidden CI failures: strict xfail on E0 red cells; the sentries fail, never skip.
8. One input, one trust class per entry point: two named output writers instead of a flag on `write_table`.
9. Mutations on the final head: every named mutation re-runs on the slice's last head.
10. Allowlisted helpers are still checked: the output writers must call the sanitizer (AT-S1 seeded cell).
11. No raised caps: the intermediate baseline is new and shrink-only; no cap, ratchet or allowlist grows.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure: source metadata text (comments, attrs, field notes) reaching an output file | allow-list rebuild of schema and field metadata at the output writer | CE cells, AT-M1 to AT-M3, CC-1 to CC-3 | keep `attributes` in the pandas blob | E1, C1 |
| 2 | Cleanup on every exit | no new resource: the output writers wrap the existing `_FileBacked` and staged-file cleanup, and the schema is built before the file is opened, so a sanitize step cannot fail with a file open | AT-M6 (writer built from the sanitized schema before the file opens) | sanitize after `parquet_writer` opens the file | E1 |
| 3 | State completeness: every metadata kind handled | the closed list in 5.5, one test cell per kind | AT-M1 to AT-M5 | drop the recursion into map value fields | E1 |
| 4 | Route coverage: a route that writes output without the rule | one output writer pair used by every engine route; CLI writers pinned | CE matrix over every route in 5.3, AT-S1, CC-6 | route the F22 publish through the raw adapter | E0, E1, C1 |
| 5 | Referential integrity | N/A: no key or FK value changes; FK shapes only reach the same writer (5.4) | none | none | none |
| 6 | Untrusted input: the source's metadata bytes and pandas JSON | strict JSON parser; every written value derived from the output schema, the running versions or a registry constant; the source only chooses among registry pairs | AT-M4, AT-M5 | accept a non-object JSON top level | E1 |
| 7 | TOCTOU / check-then-use: one schema checked, another written | the writer is constructed from the sanitized schema itself; nothing checks a schema and then writes a different one | AT-M6 (dirty batches into a clean writer) | build the writer from the batch schema | E1 |
| 8 | Weak proof: a canary check that cannot see field metadata | the helper decodes `ARROW:schema` and parses the pandas blob; its own test proves it sees a base64-only canary | AT-C0 | remove the decode step | E0 |
| 9 | Refactor drift | N/A: no refactor or move; every touched line is behaviour, and execution files stay in place (physical-seam gate) | none | none | none |
| 10 | Frozen contract drift: output bytes and the route metadata contract change without records | the frozen-surfaces row, the compatibility-contract paragraphs, the changelog fragment and the new doc move together in E1 | frozen-surface map sentry (`tests/sentry/release/`), AT-M3 identity cell | leave the old "passthrough field metadata kept" text in the contract | E1 |

## 14. Pre-mortem

- "The canary was green but the leak was real." Field metadata lives only inside base64 `ARROW:schema`; a raw-bytes grep misses it. Guard: AT-C0.
- "E1 changed every resident output's bytes and the golden gate went red." Guard: AT-M3 identity cell; clean-source bytes are unchanged by construction.
- "Stripping broke native admission or the stored-index guard." Guard: intermediates are outside the choke point (owner Q4); E2 leaves field metadata in memory; the native and chunked suites are in E1's T1 set.
- "A builder wrapped every Parquet write in the adapter and broke the isolated child." Guard: the plan names the intermediates, and the AT-S1 baseline lists them with reasons.
- "The CLI kept writing the engine's in-memory table as is." Guard: C1 and CC-6. Until C1 ships, E2 removes the schema-level carriers, so the CLI path can still leak field metadata. The row stays open until C1 merges.
- "F38 needs to break the API." The seam is a keyword-only argument with the strip default: additive.

## 15. Owner questions (decided 2026-11-18: owner took every recommended answer)

| Id | Question | Decided (recommended answer) |
|---|---|---|
| Q1 | Keep a sanitized `b"pandas"` blob (closed member set, `attributes` and column-index names dropped) instead of dropping the key entirely? | Yes. Pandas readers keep nullable-int and categorical dtypes, and clean-source resident output bytes do not change |
| Q2 | Strip all field-level metadata, including `PARQUET:field_id`? | Yes. Field ids and comments come from the source; F38 can preserve them on request |
| Q3 | Add a Decoy provenance key (for example "masked by Decoy, version") to outputs in 1.0? | No. It is a new frozen surface; leave it to F38 or a 1.x row |
| Q4 | Apply the rule to published output only, and list intermediate scratch writes by name with reasons, rather than strip every Parquet write? | Yes. Intermediates are never published, and some read metadata on purpose |
| Q5 | Leave field metadata and `df.attrs` on in-memory results returned to a Python caller out of 1.0 (E2 still removes schema-level carriers)? | Yes. The caller already holds the source; the guarantee is about files |
| Q6 | Drop range-index entries from the pandas blob (pandas readers get a default RangeIndex)? | Yes. Their `name` is user text and `stop` is the source row count; resident output already has none |

## 16. Unresolved

The E0 matrix settles the unknowns: field metadata on passthrough columns, the native chunked path, stream with a sink, `_chunked_output_sink.py:386`, the transforms carrier, and (through C1) the CLI chunked writer. The choke point covers each of them whatever the result, because it sits at the writer. E0 can add sites to 5.3; it cannot change the design. If E0 finds an output writer not listed in 5.3, E1 routes it through the output writers and AT-S1 must see it.
