Status: plan (revision 1, 2026-11-18; not yet reviewed)

# OUTPUT-METADATA-LEAK: source Parquet metadata reaches masked output (1.0 leak row)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

A masked output file must not carry text from the source file that masking never looked at. Today the out-of-core route copies the source schema's key/value metadata into the output schema. So a custom key (for example `table_comment` holding an email address) and the whole `b"pandas"` blob, including its `attributes` member (the source DataFrame's `attrs`), are written into the masked file's footer. The V1 bar blocks non-admin leaks, so this row blocks 1.0.

The owner decided on 2026-11-18 that F38 (dataset metadata preserve and redact) stays an opt-in 1.x feature (`C:docs/roadmap/post-1.0-plan.md`, F38 row: "preserving metadata is opt-in"). So the 1.0 default is: strip everything and keep only an allow-list. This plan makes that default true by construction and leaves an additive seam for F38.

Anchors: a path with no prefix is in decoy-engine (under `src/decoy_engine/` for source, the repo root for `tests/` and `docs/`); a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R2: privacy logic and an output-format change), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `bugfix.md` (fail-before proof, root cause), `security.md` (sensitive data out of artifacts, secure default), `cross-cutting-concerns.md` (one choke point plus a guard that walks the syntax tree, a seeded bypass, a shrink-only allowlist), `api-and-compatibility.md` (output bytes change, public additions, room for an opt-in later), `architecture.md` (placement against CODEMAP), `reuse-first.md`, `testing.md` (T0 to T2, mutations, strict xfail for known reds), `proportionality.md`, `scope-discipline.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

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
- Field-level metadata and `df.attrs` on in-memory results returned to a Python caller (`RunResult` tables, SDK DataFrames). The caller already holds the source. E2 removes schema-level carriers in memory as hygiene; the guarantee is about files.
- Intermediate files that Decoy never publishes: scratch spill, the isolated child's source handoff, declared-cast staging, the out-of-core key stage, vault segments inside the encrypted vault. The sentry lists each by name with a reason (owner Q4).
- Registered Arrow extension types (for example `arrow.uuid`, `arrow.opaque`). Their parameters are type information and stay. An unregistered extension arrives as storage type plus `ARROW:extension:*` field metadata, which is stripped (canary cell CE-7).
- A stale pandas blob on masked columns (the source `pandas_type` on a column whose type masking changed). A correctness item for ROUTE-OUTPUT-CONTRACT, not a leak; recorded as a follow-up.
- Platform writers (parked with the platform).
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
- Physical-seam diff gate (`tests/sentry/test_physical_seam_disconnection.py`): every execution file E1 and E2 touch is already in its permitted set at `ad36687a6`. The builder confirms; a missing one gets a reasoned line in the permitted set (an allowlist entry, not a cap).

## 4. Behaviour

### 4.1 One function, two callers

`safe_output/_file_metadata.py` (new) owns the rule:

- `output_schema(schema: pa.Schema) -> pa.Schema`: the same names, types and nullability; every field (recursively through struct, list, large_list, fixed_size_list, map and dictionary value types) has no metadata; schema metadata is `sanitized_schema_metadata(schema.metadata)`.
- `output_table(table: pa.Table) -> pa.Table`: `table.cast(output_schema(table.schema))` when the two schemas differ under `check_metadata=True`, else `table` itself. Types are equal, so the cast copies no buffers.
- `sanitized_schema_metadata(meta) -> dict[bytes, bytes] | None`: applies `_ALLOWED_SCHEMA_KEYS`, a mapping from key to its sanitizer. 1.0 holds one entry, `b"pandas": _sanitize_pandas_blob`. Any other key is dropped. `None` when nothing remains.
- Public: `decoy_engine.output_schema` and `decoy_engine.output_table` (root facade exports, for the CLI). F38 can add `*, policy=` to both later.

Callers:

- Engine output writers. `fileaccess/adapters/arrow.py` gains `write_output_table(table, txn, component)` and `output_parquet_writer(txn, component, schema)`. They call `output_table` or `output_schema`, then the existing `write_table` or `parquet_writer`. `StagedParquetWriter.write`, `StagedParquetWriter.write_batches` and `publication/_publish.py:448` switch to them. At `ad36687a6` these are every engine output Parquet site (section 5.3).
- CLI writers (C1). The two Parquet branches of `C:src/decoy/cli/io/_targets.py` (`_write_table` at lines 407-409, `write_chunked_output` at line 537) write `output_table(...)` or build the writer from `output_schema(...)`. A DataFrame is first converted with `pa.Table.from_pandas(df, preserve_index=False)`, so pandas never writes its own `PANDAS_ATTRS` key.

### 4.2 The sanitized pandas blob

Parsed with `strict_json_loads`. Anything that is not a JSON object, or fails a rule below, is dropped as a whole, and the output has no `b"pandas"` key (fail toward stripping; no error). String checks use `re.fullmatch` (defect class 1: `$` matches before a trailing newline).

| Member | Rule |
|---|---|
| `columns` | kept. Each entry keeps only `name`, `field_name`, `pandas_type`, `numpy_type`, `metadata`. `field_name` must name a field of the output schema, else the entry is dropped. `name` is set equal to `field_name`. `pandas_type` and `numpy_type` must be strings of at most 64 characters that fullmatch `[A-Za-z0-9_\[\], :/.()-]+`, else the entry is dropped. `metadata` keeps only `timezone` (string, must equal the Arrow field type's tz), `num_categories` (int, not bool), `ordered` (bool), `precision` and `scale` (int, not bool), `encoding` (`"UTF-8"`); otherwise `null` |
| `index_columns` | keeps string entries that name a field of the output schema; drops every range-index object (its `name` is user text and its `stop` is a source row count) |
| `column_indexes` | replaced with pyarrow's default single entry (`name` null, `field_name` null, `pandas_type` `"unicode"`, `numpy_type` `"object"`, `metadata` `{"encoding": "UTF-8"}`) |
| `creator` | kept only as `{"library": "pyarrow", "version": <version string>}` |
| `pandas_version` | kept if it fullmatches a version pattern, else dropped |
| `attributes` and any other member | dropped |

The JSON is re-encoded the way pyarrow writes it (`json.dumps` with default separators, members in pyarrow's order). A blob that pyarrow wrote for a frame with no `attrs`, no column-index name and `preserve_index=False` comes out byte-identical. AT-M3 pins that.

### 4.3 Carriers in memory (E2)

The six out-of-core builders copy `source_schema.metadata` or `batch.schema.metadata` into a new schema. `execution/_transforms_table.py:120` keeps every non-pandas source key. `execution/_faker_degenerate_pin.py:214` passes the rest of the source metadata through. E2 routes each through `sanitized_schema_metadata(...)`, so in-memory tables built by the engine carry no custom schema key and no `attributes`. Field metadata in memory stays as it is (passthrough columns are the source field by contract, `docs/compatibility-contract.md` line 852); the writers strip it.

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
- `subset/_materialize.py:69` (Polars `write_parquet`): a Polars frame read with `scan_parquet` carries no Arrow key/value metadata. Listed in the sentry baseline with that reason and proven by cell CE-9. If CE-9 is red on the base, E1 routes it through `write_output_table(frame.to_arrow(), ...)` instead.

Intermediate writers (listed in the sentry baseline with reasons, not sanitized): `vault.py:363` (encrypted segment buffer), `execution/_isolated_commit.py:165` (source handoff to the isolated child), `execution/out_of_core/_stage.py` (masked-key stage), `declared_casting/_stream.py:168` and `:179` (typed source staging), `execution/native/_pool_quality.py` (scratch), DuckDB `COPY ... (FORMAT PARQUET)` in `execution/out_of_core/_relation.py:521` and `execution/out_of_core/_multi_parent.py:154` (scratch), `connectors/postgres_snapshot.py:375` (source snapshot).

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
- In-memory tables returned by the engine (schema level, E2).
- Not changed: CSV, fixed width, run results, `--json`, logs, progress events, reports, the vault file format.

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Output Parquet key/value metadata | route-dependent; out-of-core copies the source's | allow-list v1: `b"pandas"` sanitized, nothing else; no field metadata | new row in `docs/frozen-surfaces.md`; `docs/security/output-metadata.md` (new) |
| Output bytes | | change only for sources with custom metadata, `attrs`, field metadata, a column-index name or a range index; masked values unchanged | changelog fragment (Changed, security) |
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

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the final slice head.

### 8.1 E0: the canary across all routes (settles the unknowns)

Helper `tests/security/_metadata_canary.py`:

- `canary_sources(tmp_path)`: writes parent and child Parquet sources with one canary per carrier: `DCY-CANARY-SCHEMA` (schema key `table_comment`), `DCY-CANARY-ATTRS` (`df.attrs`, so both `attributes` and `PANDAS_ATTRS`), `DCY-CANARY-FIELD` (field metadata on every column, including the unconfigured passthrough `n`, the masked `note` and the FK `parent_id`), `DCY-CANARY-COLIDX` (`df.columns.name`), `DCY-CANARY-NESTED` (child-field metadata in a struct column, on routes that admit structs), `DCY-CANARY-EXT` (`ARROW:extension:name` on a storage column).
- `canaries_in(path) -> set[str]`: the canaries found in (1) the raw file bytes, (2) every footer key/value value, (3) the schema and every field (recursive) of `pa.ipc.read_schema` over the base64-decoded `ARROW:schema`, (4) the parsed pandas blob.

| Id | Test | Red on base because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-C0 | `tests/security/test_metadata_canary_helper.py`: the helper finds each canary in a file written with it, including a field-metadata canary that is absent from the raw bytes | new helper | drop the `ARROW:schema` decode step (the field cell then misses the canary) | E0 |
| CE-1 | `tests/security/test_output_metadata_canary.py::test_route[out_of_core_fk]` (`fk_config`, `execution_mode="out_of_core"`): `canaries_in(output) == set()` for both tables | the investigator's repro: SCHEMA and ATTRS found | revert `output_parquet_writer` to the raw adapter | E0 (strict xfail), E1 flips |
| CE-2 | same test, `full_frame`, `sequential`, `stream` without a sink | unknown, settled by E0 | as CE-1 for any cell red on the base | E0 |
| CE-3 | same test, `stream` with a `TransactionalSink` | unknown (field metadata through `_chunked_output_sink.py:386`) | as CE-1 | E0 |
| CE-4 | same test, auto-chunk native dispatcher (companion lane) | unknown (passthrough is "the source column exactly") | as CE-1 | E0 |
| CE-5 | same test, resident with a transform op | `_transforms_table.py:120` keeps custom keys | as CE-1 | E0 |
| CE-6 | same test, mixed generate and mask; isolated; declared casting on; F22 `publish_unit`; multi-parent and composite FK out-of-core | unknown | as CE-1 | E0 |
| CE-7 | unregistered-extension column on full_frame and out_of_core | unknown | as CE-1 | E0 |
| CE-8 | zero-row source on out_of_core and chunked | unknown | as CE-1 | E0 |
| CE-9 | subset output | expected green (Polars) | write the subset frame with the source schema attached | E0 |
| CE-10 | CSV target on out_of_core: no canary in the file | expected green | none (a guard against a future CSV header comment) | E0 |

E0 rule: every cell red on the base is marked `pytest.mark.xfail(strict=True, reason="OUTPUT-METADATA-LEAK: <canary set>")`, so it stays visible and fails the suite the moment it turns green without the marker being removed. E0 also writes `docs/records/2026-11-<dd>-output-metadata-canary.md`: the full matrix (route by carrier, red or green) from one Linux VM run (`VMRUN_LINUX=1 ~/bin/vm-run engine <wt> 'pytest tests/security/test_output_metadata_canary.py -rxX'`) plus the companion-lane run for CE-4. If a cell needs a route the test kit cannot reach, the record says so and lists it as a follow-up; it is not dropped silently.

### 8.2 E1: the choke point

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-M1 | `tests/unit/safe_output/test_file_metadata.py::test_fields_stripped_recursively` (struct, list, map, dictionary value fields; `PARQUET:field_id`) | no function | strip top-level fields only | E1 |
| AT-M2 | `::test_only_allowed_schema_keys` (custom key, `PANDAS_ATTRS`, non-UTF-8 key bytes) | no function | add `b"PANDAS_ATTRS"` to `_ALLOWED_SCHEMA_KEYS` | E1 |
| AT-M3 | `::test_pandas_blob_sanitized` (`attributes` gone, column-index name gone) and `::test_clean_blob_identical`: for a frame with no `attrs`, `sanitized_schema_metadata(Table.from_pandas(df, preserve_index=False).schema.metadata)` equals the input bytes | no function | keep `attributes`; or re-encode with other separators (the identity cell turns red) | E1 |
| AT-M4 | `::test_bad_blob_dropped` (not JSON, a JSON list, NaN, a 1 MiB string, wrong member types, a bool where an int is required, a type string ending in `"\n"`) | no function | raise instead of dropping; or match with `re.match` (the newline cell turns red) | E1 |
| AT-M5 | `::test_blob_entries_follow_output_schema` (unknown `field_name`, range index, `name` differing from `field_name`) | no function | keep range-index objects | E1 |
| AT-M6 | `tests/fileaccess/test_output_writers.py`: `output_parquet_writer` with a dirty schema and dirty batches writes a clean footer; `write_output_table` likewise; a clean table passes through without a copy (same buffer addresses) | no output writers | sanitize the batches but build the writer from the raw schema | E1 |
| AT-S1 | `tests/sentry/defects/test_output_metadata_choke_point.py`: walks `src/decoy_engine` with the file-access resolver. Every Parquet sink (`pyarrow.parquet.write_table`, `ParquetWriter`, `write_to_dataset`, the adapter `write_table` and `parquet_writer`, Polars `write_parquet`, `DataFrame.to_parquet`, DuckDB `COPY` with `FORMAT PARQUET`) is inside an output writer of `fileaccess/adapters/arrow.py`, or is a row of `tests/sentry/baselines/parquet-intermediate-writers.json` (module, function, reason; shrink-only through `scripts/dev/ratchet_check.py`). Covered spellings: direct attribute call, `from pyarrow.parquet import write_table as w`, module alias, adapter call through `arrow_adapter`. Seeded cells for each spelling fail | no sentry | switch `StagedParquetWriter.write` back to `arrow_adapter.write_table` | E1 |
| AT-E1 | E0's CE cells for engine routes lose their xfail markers and pass | leak | revert `_publish.py:448` to the raw adapter (the F22 cell of CE-6 turns red) | E1 |
| AT-P1 | `tests/sentry/test_public_import_boundary.py` and `tests/sentry/test_ga_stub_exports.py` list `output_schema` and `output_table` | not exported | drop one export | E1 |

### 8.3 E2: carriers in memory

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-S2 | `tests/sentry/defects/test_metadata_carrier.py`: AST walk of `src/decoy_engine`. A `metadata=` keyword of `pa.schema`, `pa.record_batch` or `pa.Table.from_arrays`, or the argument of `replace_schema_metadata` or `with_metadata`, whose value reads a `.metadata` attribute must be wrapped in `sanitized_schema_metadata`. Seeded cell fails | the ten sites in 5.1 | restore `metadata=source_schema.metadata` at `_rewrite_pass.py:377` | E2 |
| AT-E2 | `tests/security/test_output_metadata_canary.py::test_in_memory[out_of_core_fk, resident_transforms]`: the returned tables' schema metadata holds no canary | carriers | restore the `_transforms_table.py:120` line | E2 |

### 8.4 CLI (C1)

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| CC-1 | `C:tests/e2e/cli_fmt/test_output_metadata_canary.py`: `decoy run` (plain) on canary sources; no canary in the Parquet targets (same decode as AT-C0; the helper is vendored and pinned in `C:ci/vendored.toml`) | `pq.write_table(data)` keeps the table schema | drop `output_table` in `_write_table` | C1 |
| CC-2 | same file, DataFrame write path (`write_private_table` through `decoy unmask`): no `PANDAS_ATTRS`, no `attributes` | `to_parquet` writes `attrs` | restore `data.to_parquet` | C1 |
| CC-3 | same file, `decoy run --chunked`: no canary | the first chunk's schema is used as is | build `ParquetWriter` from `first.schema` | C1 |
| CC-4 | same file, out-of-core FK pipeline through the CLI | engine and CLI both | none extra (covered by E1 and CC-1) | C1 |
| CC-5 | same file, CSV target: no canary | expected green | none (guard) | C1 |
| CC-6 | `C:tests/sentry/io_policy/test_target_writes.py` new rule: inside `WRITERS`, each Parquet sink call takes a value produced in the same function by `output_table` or `output_schema`. Seeded cell (a writer that passes `data` straight to `pq.write_table`) fails | no rule | remove the call in `write_chunked_output` | C1 |

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/safe_output/_file_metadata.py` | new (E1, about 130 lines) | Safe output boundary: `src/decoy_engine/safe_output/_<output concern>.py` | `safe_output/_event.py` |
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
| `C:tests/e2e/cli_fmt/test_output_metadata_canary.py`, `C:tests/e2e/cli_fmt/_metadata_canary.py` (vendored) | new | `tests/e2e/cli_fmt/` | the existing cli_fmt e2e tests |
| `C:tests/sentry/io_policy/test_target_writes.py` | changed | `tests/sentry/io_policy/` | |
| `C:CHANGELOG.md`, `C:ci/vendored.toml` | changed | | |

## 10. Design notes

- Choke points.
  - Engine files: `safe_output.output_schema` is the only place that decides output metadata, and the output writers in `fileaccess/adapters/arrow.py` are the only engine functions that write a published Parquet file. Guard: AT-S1. Mutation: `StagedParquetWriter.write` calls the raw adapter.
  - Engine memory: AT-S2. Mutation: one restored raw carrier.
  - CLI: the `WRITERS` of `_targets.py` (already the only table writers under G-ONE-TARGET-WRITE). Guard: CC-6. Mutation: a writer that skips `output_table`.
- Why at the output writer and not at every Parquet write (the investigator's first suggestion): intermediate files feed logic that reads metadata on purpose (stored pandas index fields in `execution/native/_chunk_schema.py:60`, native admission shape checks at `_faker_deterministic_admission.py:259`, the isolated child reading its sources). Stripping there changes routing and admission, which is not this row. Intermediates are never published. Owner Q4.
- Why also clean the in-memory carriers (E2) when the writer already guarantees files: in-memory tables cross into the CLI and the SDK, and a carrier left in place is how the next writer leaks. It is one line per site and gets its own sentry.
- Why keep a sanitized pandas blob (owner Q1): without it a pandas reader loses nullable integer and categorical dtypes on round trip, and every resident output's bytes change. With the closed filter, clean-source bytes stay identical (AT-M3).
- Why separate output writer functions and not a flag: house style (no flag arguments that switch behavior). `write_output_table` and `write_table` are two named entry points on one core (defect class 8).
- F38 seam: `_ALLOWED_SCHEMA_KEYS` is the one registry, and `output_schema` and `output_table` are the one entry. F38 adds `*, policy: MetadataPolicy = STRIP` and a preserve policy built from the run config, threaded to the output writers. Nothing is pre-built now.
- Logs: none added.

## 11. Size

| Slice | Src lines | Test lines | Docs lines | Files touched |
|---|---|---|---|---|
| E0 | 0 | about +330 | about +60 (record) | 4 |
| E1 | about +170 | about +420 | about +90 | src 6, tests 5, docs 4, baseline 1 |
| E2 | about +20, -10 | about +170 | about +5 | src 8, tests 2 |
| C1 | about +20 | about +260 | about +15 | src 1, tests 3, docs 2 |

New public names: `output_schema`, `output_table` (engine). No product file grows past its size ceiling; `fileaccess/adapters/arrow.py` goes from 143 to about 170 lines.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| E0 | engine | canary helper, route matrix with strict xfail on red cells, record of the matrix | R1 (tests only) | AT-C0, CE-1 to CE-10 | none | T0 on the new files; one Linux VM run plus the companion lane for CE-4; Codex review |
| E1 | engine | `safe_output/_file_metadata.py`, output writers, three call sites, public exports, choke-point sentry and baseline, flip of the engine CE cells, docs, fragment | R2 | AT-M1 to AT-M6, AT-S1, AT-E1, AT-P1 | E0 | T1 impact set (safe_output, fileaccess, publication, transactional sink, out_of_core, chunked, security, sentry) on the head, plus T2: each named mutation. Frozen-contract trigger: one saved-baseline full suite via `decoy-vm-t3` on the merge head. Dennis then Codex |
| E2 | engine | eight carrier sites through `sanitized_schema_metadata`, carrier sentry, in-memory cells | R1 | AT-S2, AT-E2 | E1 | T1 (out_of_core, transforms, faker pin, parity suites unchanged) plus the physical-seam sentry; Codex |
| C1 | CLI | `_targets.py` through `output_table` and `output_schema`, CLI canary e2e, sentry rule, changelog | R2 | CC-1 to CC-6 | the engine release that carries E1, and the CLI repin to it | T1 (`tests/e2e/cli_fmt/`, io_policy sentries, unmask e2e) plus T2 on the head; Dennis then Codex |

Order: E0 now. E1 starts when E0's record exists (the record may add sites to 5.3; it cannot move the choke point). E2 after E1. C1 after the next daily engine release that carries E1; target before the D-4 engine freeze ahead of 2026-12-04. The row closes only when C1 merges.

## 13. Recurring-defect class check

- Two copies of a central mechanism: one sanitizer, one registry, one engine writer pair, one CLI writer set; each has a sentry.
- A test weakened to pass: E0's strict xfail markers are removed only by the slice that fixes the cell; the gate diff-checks that no canary assertion changed.
- A grep counted as an enumeration: AT-S1 and AT-S2 walk the syntax tree with alias resolution and prove a seeded bypass per covered spelling.
- Anchored validation: every string check in 4.2 uses `re.fullmatch`; AT-M4 has a trailing-newline cell.
- Allowlisted helpers are still checked: the output writers are the allowed sites in AT-S1, and their own bodies must call `output_schema` or `output_table` (a seeded cell removes the call).
- Value exposure (F31 class): metadata text never enters an error or log line.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure: source metadata text (comments, attrs, field notes) reaching an output file | allow-list rebuild of schema and field metadata at the output writer | CE cells, AT-M1 to AT-M3, CC-1 to CC-3 | keep `attributes` in the pandas blob | E1, C1 |
| 2 | Cleanup on every exit | no new resource: the output writers wrap the existing `_FileBacked` and staged-file cleanup, and the schema is built before the file is opened, so a sanitize step cannot fail with a file open | AT-M6 (writer built from the sanitized schema before the file opens) | sanitize after `parquet_writer` opens the file | E1 |
| 3 | State completeness: every metadata kind handled | the closed list in 5.5, one test cell per kind | AT-M1 to AT-M5 | drop the recursion into map value fields | E1 |
| 4 | Route coverage: a route that writes output without the rule | one output writer pair used by every engine route; CLI writers pinned | CE matrix over every route in 5.3, AT-S1, CC-6 | route the F22 publish through the raw adapter | E0, E1, C1 |
| 5 | Referential integrity | N/A: no key or FK value changes; FK shapes only reach the same writer (5.4) | none | none | none |
| 6 | Untrusted input: the source's metadata bytes and pandas JSON | strict JSON parser, closed member set, length and fullmatch pattern limits, drop on any failure | AT-M4, AT-M5 | accept a non-object JSON top level | E1 |
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

## 15. Owner questions (taken on the recommended answer; owner to confirm)

| Id | Question | Recommended |
|---|---|---|
| Q1 | Keep a sanitized `b"pandas"` blob (closed member set, `attributes` and column-index names dropped) instead of dropping the key entirely? | Yes. Pandas readers keep nullable-int and categorical dtypes, and clean-source resident output bytes do not change |
| Q2 | Strip all field-level metadata, including `PARQUET:field_id`? | Yes. Field ids and comments come from the source; F38 can preserve them on request |
| Q3 | Add a Decoy provenance key (for example "masked by Decoy, version") to outputs in 1.0? | No. It is a new frozen surface; leave it to F38 or a 1.x row |
| Q4 | Apply the rule to published output only, and list intermediate scratch writes by name with reasons, rather than strip every Parquet write? | Yes. Intermediates are never published, and some read metadata on purpose |
| Q5 | Leave field metadata and `df.attrs` on in-memory results returned to a Python caller out of 1.0 (E2 still removes schema-level carriers)? | Yes. The caller already holds the source; the guarantee is about files |
| Q6 | Drop range-index entries from the pandas blob (pandas readers get a default RangeIndex)? | Yes. Their `name` is user text and `stop` is the source row count; resident output already has none |

## 16. Unresolved

The E0 matrix settles the unknowns: field metadata on passthrough columns, the native chunked path, stream with a sink, `_chunked_output_sink.py:386`, the transforms carrier, and (through C1) the CLI chunked writer. The choke point covers each of them whatever the result, because it sits at the writer. E0 can add sites to 5.3; it cannot change the design. If E0 finds an output writer not listed in 5.3, E1 routes it through the output writers and AT-S1 must see it.
