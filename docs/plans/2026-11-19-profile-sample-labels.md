Status: plan

# PROFILE-SAMPLE-LABELS: every profile number says what it was counted over (1.0 row PROFILE-SAMPLE-LABELS)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-19. Revision 2, answering Dennis round 1 (NO-GO: 1 BLOCKER, 3 HIGH, 4 MEDIUM, 6 LOW).

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `profiles/local-operations.md`, `bugfix.md`, `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation), `api-and-compatibility.md` (consumer inventory, explicit breaking changes), `proportionality.md`; also `architecture.md` (placement, fan-out), `testing.md` (T0 to T2), `reuse-first.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md` (checked by name in section 6.2); vault `30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`; engine `CODEMAP.md` ("Where Things Go"), `docs/compatibility-contract.md`, `docs/frozen-surfaces.md`; CLI `CODEMAP.md`, `docs/roadmap/groups/scan.md` (rows PROFILE-SAMPLE-LABELS, 24zm); the row 24zm plan (`origin/plan/profile-unflagged`, revision 5); the freeze-batch plan (`origin/plan/freeze-batch`, revision 3.2).

Anchors: a path with no prefix is in decoy-engine at `origin/main` `208478504`; a path with the prefix `C:` is in the CLI repository (decoy) at `origin/main` `ccc5540a`. Every cited engine line was reread at `208478504`; the two commits since revision 1's anchor `9e6547298` touch none of the cited files. The plan lives in the engine repo on branch `plan/profile-sample-labels` because the labels, the registry and the sentries are engine-owned.

Risk: R2 overall. E1 and C1 change the bytes of outputs that freeze at 1.0 (`scan-set/v1`, `profile_document`, `decoy scan --json`); `risk-and-exceptions.md` makes compatibility an R2 trigger. E0 changes what the cloud CSV readers fetch, so it is R2 (a reader contract other routes depend on). E2 is R1 unless a golden moves (then R2). Approver: Cam for the plan and the owner questions; Dennis then Codex for the plan gate. 1.0 bar: this row is a function break (a key claimed that is not a key, null counts shown as file-wide that are not) in an output that freezes; it is not a leak.

## Revision 2 change log

- BLOCKER 1 (a short read is not proof of end): new slice E0 makes "fewer than n rows only at end of source" the `ProfileSource.sample_frame` contract. The cloud CSV readers fetch more ranged windows until they hold n rows or the object ends. A conformance test covers every reader, and a sentry fails on a reader class that is not in the matrix (section 4.0). Owner Q5 now recommends (b): the head route asks for one row past the cap and stamps the proven basis with `dataclasses.replace`.
- HIGH 1: the `TableCore` write validator accepts `scanned_rows is None` as a legacy record (basis must then be `sample`), checks the relations only when it is set, and requires it when the basis is `whole`. "Always set" is a producer test on `_table_core`. New AT-17: `export_lines` on a pre-change record still exports and strips.
- HIGH 2: `FIELD_BASIS` is keyed `(root, type name, field)`. The sentry fails when one key reaches two classes (AT-11 seeded cell).
- HIGH 3: the scan core read model maps an unknown `basis` string to `sample` (fail closed) with a read-only `BeforeValidator` added by `_relaxed`; a non-string is still refused. A third basis value stays a minor change. Class 4 guard cells in AT-9.
- MEDIUM 1: E1 first freezes a pre-change `scan-set/v1` core and record into the compatibility corpus via `regenerate.py` at the pre-E1 head (AT-9, AT-17).
- MEDIUM 2: section 6.2 checks all 11 classes of `catalogs/recurring-defects.md` by name; class 2 cells added to AT-10 and AT-9.
- MEDIUM 3: the multi-table card sums `scanned_rows`; AT-C8.
- MEDIUM 4: AT-12 is now a property over `first_chunk_profile` and `profile_source` outputs on partial reads. It found a real case (a CSV whose row estimate undershoots the sample), fixed in E2 item 2.
- LOW 1 to 6: answered in sections 4.1 (Basis import, registry comments), 4.2 (field order), 4.4 (discriminator), 6.3 (`is_likely_unique`), and failure mode 1 (random route).

## 1. Frame

### 1.1 The row

"Sample numbers shown as whole-file numbers (found 2026-11-18): the default scan profiles the first 10,000 rows but prints the sample null and distinct counts beside the exact whole-file row count, and `key_candidates` can call a column a key from the sample alone. The chunked mask run profiles only its first chunk yet marks columns `sampled=False`, so the plan's `profile_hash` depends on chunk size. Fix before the freeze, because each changes output: label every sampled field (`basis`, `scanned_rows`), claim a key only from exact counts, and make the first-chunk profile say it is a sample (or keep its distribution fields out of the plan hash). Exact whole-file numbers stay a 1.x opt-in. V1 fix."

### 1.2 Evidence (probe on the Dell, `VMRUN_LINUX=1 ~/bin/vm-run engine`, engine `9e6547298`; no cited code changed since)

A 25,000-row CSV. Column `id` is `i % 12000` (unique in the first 10,000 rows, 12,000 distinct over the file). Column `n` has nulls only after row 10,000. Default `scan_sources` (head, cap 10,000):

```
core.row_count 28058 exact False strategy head cap 10000
key_candidates ['id']
field id null_count 0 null_rate 0.0 distinct 10000
field n null_count 0 null_rate 0.0 distinct 3
```

The core claims `id` is a key and reports 0 nulls for a column that has about 2,140, beside a source row count of 28,058. Nothing in the record says the field numbers cover 10,000 rows.

`first_chunk_profile` on two prefixes of one 4,000-row table (`id = i % 1500`):

```
chunk 1000 hash 21827d9f7369 [('id', 1000, 1000, False, True), ('v', 1000, 900, False, False)]
chunk 2000 hash 20e0d4b50d2c [('id', 2000, 1500, False, False), ('v', 2000, 900, False, False)]
```

Every column says `sampled=False`. With a 1,000-row chunk, `id` is flagged a candidate key, which the H6 invariant (`profile/_types.py:105`) exists to forbid for sampled data. `profile_hash` moves with the chunk size.

### 1.3 Root cause

There is no single rule that says what a profile number was counted over, no field-level record of it, and no reader guarantee that a short read means the end of the source.

1. `scan_set._read_and_profile` (`profiling/scan_set.py:274`) passes only `sample_strategy` and `sample_row_cap` to the core (`profiling/_scan_core.py:86`). The number of rows read is not in the core, and a cap of 10,000 does not say whether the file was shorter.
2. A short read does not prove the end. `S3CsvSource` and `GcsCsvSource` parse only a leading 1 MiB window (`profile/_cloud_readers.py:39`, `profile/_cloud_readers.py:254`, `profile/_cloud_readers.py:357`), so a large object with wide rows returns fewer rows than asked for while most of the object is unread. The `ProfileSource.sample_frame` docstring (`profile/_readers.py:94`) says only "up to `sample_rows` rows".
3. `_table_scan` (`profiling/scan_set.py:356`) claims a key when `null_count == 0 and distinct_count == scanned`, with no check that `scanned` is the whole source.
4. `first_chunk_profile` (`execution/_chunked_profile.py:53`) walks the chunk with `sample_rows=None` (`execution/_chunked_profile.py:36`), so the walk believes the chunk is the table; `arrow_column_profile` hard-codes `sampled=False` and computes the key flag from the chunk (`execution/_chunked_profile.py:198`).
5. The planner's `profile_source` decides "sampled" from `max(estimate, len(sample))` (`profile/_source.py:255`, `profile/_walk.py:119`). A CSV whose leading rows are wider than the rest gets a row estimate below the sample length, so a 10,000-row prefix of a 25,000-row file reads as the whole table and may flag a key.
6. Each surface added its own partial label (`sample_strategy`, `row_count_exact`, `sampled`, relationship `exact` and `bounded`), so a new field lands with whatever label its author remembered. That is a class, so the fix is a registry plus a sentry, not patches.

## 2. Guarantee and non-goals

- G0. `ProfileSource.sample_frame(n)` returns exactly `n` rows when the source holds at least `n`, and fewer only when it read to the end of the source. Every reader meets it; a reader not in the conformance matrix fails the build.
- G1. Every number in a profile output that was counted over the scanned rows sits in a record that states its basis (`whole` or `sample`) and how many rows were scanned. `whole` is written only when the read proved it reached the end of the source.
- G2. A key is claimed only on a `whole` basis. On a `sample` basis `key_candidates` is empty and every surface that shows it says the check was not run.
- G3. A first-chunk profile and a partial `profile_source` read say they are samples: every column `sampled=True`, no column a candidate key. No masked byte changes.
- G4. Every field reachable from the profile output types has exactly one basis class in one registry. A new field without one fails the build (owner's rule: a class finding gets a construction sentry).
- G5. Old records stay readable and exportable. A `scan-set/v1` core written before this change reads as `basis: sample` (fail closed), never as `whole`, and `export_lines` still strips and exports it. A basis value from a later minor reads as `sample`.

Non-goals:

- Exact whole-file aggregates over a sampled scan (a streaming pass for exact null and distinct counts). That is the 1.x opt-in the row names. `decoy scan --rows 0` (a full read) already gives exact numbers today.
- The planner's capacity arithmetic that mixes a source `row_count` with a sample `null_count` (`plan/_checks.py:161`). It never reaches output; section 16 logs it for its own row.
- A per-field `basis` key on every field record (owner Q2).
- Changing the hash rules of `profile_hash` (owner Q1).
- An Azure or SFTP profile reader. None exists at the anchor: `SourceDescriptor` is file, s3 or gcs (`config/_sources.py:343`), and `build_profile_source` refuses any other type (`profile/_readers.py:499`). The E0 sentry makes a later reader join the contract matrix before it can merge.

## 3. Established solutions

Searches run 2026-11-19 (web): DuckDB `SUMMARIZE` columns; Deequ `ApproxCountDistinct`, column profiler and constraint suggestion; Great Expectations `result_format` keys; ydata-profiling large-dataset guidance; S3 `GetObject` `Range` and GCS ranged download semantics. In-codebase: the value registry and its sentry (`profiling/_value_redaction.py:108`, `tests/sentry/profiling/test_profile_value_registry.py`), the existing labels (`row_count_exact`, `sampled`, relationship `exact`/`bounded`).

| Tool | How it labels a sample | What we take |
|---|---|---|
| ydata-profiling | Statistics cover the DataFrame it is given. Its "Profiling large datasets" page recommends `minimal=True` or sampling first (`df.sample(10000)`), and suggests the user add a disclaimer to the report stating the sample size. The report itself does not record the sample. | The negative case: a profile that does not carry its basis reads as whole-data, and the label is left to the user. That is our current behaviour; we put the label in the output. |
| Great Expectations | A result carries `element_count` and `unexpected_count`; a capped list is named `partial_unexpected_list` (20 items by default), so the name says the list is partial. | Say "partial" where a number is partial. We keep the counts' names and put the basis beside them. |
| Deequ | The analyzer name carries the basis: `ApproxCountDistinct` (HyperLogLog++) against `CountDistinct`. Constraint suggestion profiles the data and proposes constraints, which a `VerificationSuite` then checks. | A key found on partial data is a suggestion until an exact check confirms it. We do not ship it as a claim; on a sample the key check is "not run". |
| DuckDB `SUMMARIZE` | One query over the whole relation. Approximate columns say so (`approx_unique`); the docs state the quantiles are approximate. | The basis is visible where the number is shown: the CLI column header says "(sample)". |
| Python file and stream reads, S3/GCS ranged reads | `io.RawIOBase.read(n)` may return fewer bytes before EOF; only a zero-length read means EOF. A ranged GET returns the bytes of the range, not a count of what remains. | A short read is not an end-of-data signal unless the API promises it. We make the promise part of our reader contract (G0) and prove it per reader, instead of trusting a count. |

Synthesis: two patterns exist, basis in the name (Deequ, DuckDB) and basis in adjacent metadata or a "partial" marker (Great Expectations). Renaming `null_count` and `distinct_count` would break every reader of `scan-set/v1` and the profile document for no new information, so this plan uses adjacent metadata on the record that holds the numbers plus a display label, and takes Deequ's split between suggesting and verifying a key for G2. The only custom code is the basis rule, the reader contract and the registry, because the facts they need (cap, rows read, end reached) exist only inside our readers.

## 4. Design

### 4.0 E0: a short read proves the end of the source

Choice: the `sample_frame` contract (option A in the review), not an `exhausted` fact returned by each reader (option B). Reasons:

- The cloud CSV window is a reader bug in its own right. A 10,000-row request on wide rows returns a few thousand rows today, so the scan, the planner's `profile_source` (`profile/_source.py:249`) and the lifecycle estimate (`execution/pipeline/_lifecycle_inputs.py:83`) all profile a smaller sample than they asked for. Option B would label that sample truthfully and keep it small; option A fixes it at the source.
- Option B needs the same per-reader work (each reader must know whether it reached the end) plus a change to the `ProfileSource` protocol signature that eight readers and every fake in the tests implement. Option A keeps the signature and puts the guarantee in the docstring, the conformance test and the sentry.
- With the contract, end-of-source is one comparison in the caller (`len(frame) <= n` when it asked for `n + 1`), so the basis decision stays in one rule (`read_basis`).

Changes:

1. `ProfileSource.sample_frame` docstring (`profile/_readers.py:94`): "Exactly `sample_rows` rows when the source holds at least that many; fewer only when the read reached the end of the source."
2. `S3CsvSource.sample_frame` and `GcsCsvSource.sample_frame` (`profile/_cloud_readers.py:254`, `profile/_cloud_readers.py:357`) call one shared helper, `_csv_rows_from_ranges(size, fetch, n, lexeme)`, in the same module. It fetches the first window (1 MiB, `_CSV_SAMPLE_WINDOW_BYTES`), then ranged windows of doubling size appended to the buffer (never refetching bytes it holds), until either the parse of the buffer cut at its last newline yields `n + 1` data rows or the buffer covers the whole object. It returns the first `n` rows. Asking the parser for one row past `n` proves the `n`-th row was complete: a later row started after it, so a quoted field cut at the window edge cannot be counted. When the buffer covers the object it returns what parsed. Bytes fetched stay under about twice what `n + 1` rows occupy. GCS keeps one client for the whole loop (the `with` block in `_size_and_window`). The schema and row-count estimate paths keep their single window.
3. The other six readers already meet the contract (`CsvFileSource` reads with `nrows`, the Parquet readers stop on `head_frame_from_batches`, fixed width reads `max_records`, `ResidentTableSource` slices). E0 changes none of them; the conformance test proves it.
4. Conformance test `tests/unit/profile/test_sample_frame_contract.py`: for every reader class, a source of 3 rows asked for 5 returns 3; a source of 25,000 wide rows asked for 10,000 returns 10,000; asked for 10,001 returns 10,001. S3 runs on `moto[s3]` (a test dependency, `pyproject.toml:191`); GCS uses the fake client already in `tests/unit/profile/test_duplicate_header_readers.py`.
5. Sentry `tests/sentry/profiling/test_profile_source_contract_coverage.py`: imports every module under `decoy_engine.profile` and `decoy_engine.profiling`, collects each class that defines `sample_frame`, and fails when one is not in the conformance matrix. Seeded case: a new class with `sample_frame` defined in a test module registered for the scan fails it. A later Azure or SFTP reader therefore cannot merge without passing the contract.

`_cloud_readers.py` is 394 lines and ends near 425 (under 600).

### 4.1 One basis rule and one registry: `profiling/_basis.py` (new, about 120 lines)

- `Basis = Literal["whole", "sample"]`.
- `read_basis(strategy: str, cap: int | None, reached_end: bool) -> Basis`: `whole` when `strategy == "full"`, or `cap is None`, or `reached_end`; else `sample`. One rule, one fact. Each caller supplies `reached_end` from what it holds: `scan_set` from the reader contract (section 4.2 item 3), `profile_columns` on a caller's DataFrame from `len(df) < cap` (the caller's statement, failure mode 2).
- `claim_keys(profile) -> tuple[str, ...]`: the one key rule. Empty unless `profile.basis == "whole"`; otherwise the existing test (no nulls, distinct equals scanned rows).
- `BasisClass` enum:
  - `SCANNED`: counted over the scanned rows; its record's carrier applies (`null_count`, `distinct_count`, `null_rate`, `pii_score`, `top_values`, `reid_risk_score`, model hits, and heuristic hints such as `is_likely_unique`).
  - `SOURCE`: a fact of the whole source with its own label (`TableCore.row_count` with `row_count_exact`; relationship facts with `exact` and `bounded`).
  - `CHECKED`: a claim that needs exact counts; empty or `False` unless the basis is `whole` (`key_candidates`, planner `is_candidate_key_sampled`).
  - `LABEL`: identity, configuration or metadata (`name`, `engine_version`, `sample_strategy`, `basis`, `scanned_rows`).
- `FIELD_BASIS: Mapping[tuple[str, str, str], BasisClass]`, keyed `(root, type name, field name)`. Three roots:
  1. `"document"`: every type `profile_types()` reaches from `profiling.types.ColumnProfile` (`profiling/_value_redaction.py:419`);
  2. `"scan_core"`: `ScanSetCore` and every pydantic model it nests (`profiling/_scan_core.py`);
  3. `"planner"`: `Profile`, `TableProfile`, `ColumnProfile`, `Relationship` in `profile/_types.py`.
  The root is part of the key because two roots hold a class named `ColumnProfile` with a `row_count` of different meaning (`LABEL`, rows scanned, in the document; `SOURCE` in the planner). The key uses the root, not the module path, so the H-1 module splits do not rename registry keys. Within one root the sentry requires a type name to map to one class.
- `CARRIERS`: per root, the field that carries the basis (`("document", "ColumnProfile", "basis")`, `("scan_core", "TableCore", "basis")`, `("planner", "ColumnProfile", "sampled")`).
- Registry comment on the planner `TableProfile` entries: `row_count` and `row_count_exact` are `SOURCE`, except that a first-chunk profile sets `row_count` to the chunk length and leaves `row_count_exact=True` (`execution/capacity.py:481` reads it, stop line 7). On that profile they describe the chunk, not the source; no route serializes it (AT-14).

Import edges: `_basis.py` is a leaf. At run time it imports only `enum` and `typing`; it names `ColumnProfile` for `claim_keys` under `TYPE_CHECKING`, and names planner types by string, so `profiling` gains no edge into `profile`. `profiling/types.py` and `profiling/_scan_core.py` import `Basis` from it at run time. `TYPE_CHECKING` is not enough for `types.py`: `_walk` and `_conforms` call `get_type_hints` on the dataclass (`profiling/_value_redaction.py:401`, `profiling/_value_redaction.py:556`), which must resolve `Basis` at run time. There is no cycle, because `_basis.py` imports nothing from `types.py` at run time.

### 4.2 E1: the scan path and the profile document

1. `profiling.types.ColumnProfile` gains `basis: Basis = "sample"` as its last field, after `generated_at` (`profiling/types.py:196`), so positional construction and `to_dict` key order of existing fields do not move. The default fails closed for older constructors and loaded documents. `profile_columns` (`profiling/profiler.py:298`) sets it with `read_basis(sample_strategy, sample_row_cap, sample_row_cap is not None and len(df) < sample_row_cap)` at the one construction site (`profiling/profiler.py:454`). No new parameter on the frozen `profile_columns` signature.
2. `_value_redaction.py`: `("ColumnProfile", "basis")` joins `VALUE_FREE_FIELDS` (`profiling/_value_redaction.py:108`). `_checkable` and `_conforms` learn `Literal`: a value conforms when its type is exactly `str` and it is one of the literal's arguments. Without this the redactor drops the key from every plain document; with it a forged `basis` holding other text is dropped like any ill-typed value-free slot. About 5 lines; the module stays under 600.
3. `scan_set._read_and_profile` (`profiling/scan_set.py:295`) proves the end and stamps the basis:
   - head: `frame = reader.sample_frame(cap + 1)`; `reached_end = len(frame) <= cap`; when not, `frame = frame.iloc[:cap]`. On `reached_end` the source total is the frame length and exact (`total, exact = len(frame), True`); otherwise `total = max(count.value, cap + 1)` with `count.exact`, so a known-larger source never reports fewer rows than were seen.
   - random and full: `reader.to_frame()` reads everything, so `reached_end = len(full) <= cap` for random (no sampling happened) and `True` for full.
   - after `profile_columns`, `profile = dataclasses.replace(profile, basis=read_basis(strategy_label, row_cap, reached_end))`. `scan_set` holds the reader's proof, so it always overwrites the DataFrame-route value; both values come from `read_basis`. No new parameter on `profile_columns`.
   - the leading-zero read (`_text_frames`, `profiling/scan_set.py:331`) still reads `cap` rows on a head scan, the same rows profiled.
4. `TableCore` (`profiling/_scan_core.py:86`) gains `basis: Basis = "sample"` and `scanned_rows: int | None = None`. The defaults keep old records readable through `ScanSetCoreRead`, read as `sample` (G5). A model validator on the write model:
   - `scanned_rows is None` is a legacy record: allowed only with `basis == "sample"`, so a pre-change record still validates through `write_model` in `records/_export.py:127` (`_strip`) and `records/_codec.py:77` (`_payload_body`) and is not withheld from export;
   - when `scanned_rows` is set: `0 <= scanned_rows <= row_count`;
   - `basis == "whole"` requires `scanned_rows` set, `row_count_exact`, and `scanned_rows == row_count`.
   `_table_core` (`profiling/scan_set.py:432`) always fills both from `TableScan.profile`; a producer test pins that it never writes `None`. The tag stays `scan-set/v1`: both members are additive with read defaults, which contract section 3.1 allows within a major. Strict mode (`_Core`, `profiling/_scan_core.py:28`) already refuses a bool or a numeric string for `scanned_rows` on write and read.
5. Read-side token rule in `_relaxed` (`profiling/_scan_core.py:131`): `swap` replaces the `Basis` annotation with `Annotated[Basis, BeforeValidator(_unknown_basis_as_sample)]`. The validator turns a `str` that is not a known token into `"sample"` and passes every other input through, so a bool, an int or `None` is still refused by the strict `Literal`. Only the read model gets it; the write model refuses any unknown value. About 10 lines; `_scan_core.py` stays under 200.
6. `_table_scan` (`profiling/scan_set.py:356`) calls `claim_keys`. Nothing else computes a key.
7. `FieldCore` gains nothing (owner Q2): every `SCANNED` field in it takes its table's `basis`.
8. Corpus first: E1's first commit, made on the pre-E1 head before any production change, adds `write_scan_set_sample()` to `tests/integration/compat_corpus/regenerate.py` behind `python regenerate.py scan-set`, so the vault is not reminted. It scans a synthetic 40-row CSV, fixes `scanned_at` and the descriptor path (`/work/data/claims.csv`) through the write model, and writes `records/scan-set-v1-core.json` (the bare core) and `records/scan-set-v1.json` (a sealed `scan-set` record envelope built the way `tests/unit/records/_helpers.py` `make` builds one). The manifest gains the entries; the files are then frozen.

### 4.3 E2: the first-chunk profile and the planner's partial read

1. `first_chunk_profile` (`execution/_chunked_profile.py:53`) ends with one transform, `_as_chunk_sample(table_profile)`: every column `dataclasses.replace(c, sampled=True, is_candidate_key_sampled=False)`. It runs after the carried-column replacement, so columns built by `arrow_column_profile` are covered too. `walk_one_table` and `arrow_column_profile` stay unchanged, so their field-by-field parity test (test 20) still holds. `empty_input_profile` is unchanged: zero chunks means the source is empty, which is a whole read.
2. `profile_source` bounded path (`profile/_source.py:249`): ask `reader.sample_frame(n + 1)` under the E0 contract. When more than `n` rows come back, keep the first `n` and set `effective_total = max(row_count.value, n + 1)`, so the walker sees `total_row_count > frame_len` (`profile/_walk.py:119`), marks every column `sampled=True` and forces the key flag `False`. When `n` or fewer come back the read reached the end, and the code keeps today's arithmetic, so no hash of a fully read fixture moves (AT-15). About 6 lines.

`TableProfile.row_count_exact` is not flipped for the chunk, because `execution/capacity.py:481` reads it. The docstring of `first_chunk_profile` says the table `row_count` is the chunk length.

Hash: the rules of `_data_shape_bytes` (`profile/_serialize.py:51`) do not change (owner Q1). A first-chunk hash moves once (`sampled` and the key flag are hashed) and still depends on chunk size. No route writes it: `Plan.profile_hash` reaches disk only through `plan_to_yaml` and the full-frame unified slice evidence (`execution/_unified_slice.py:338`), and neither runs on a first-chunk profile. AT-14 pins that. A `profile_source` hash moves only for a source larger than `n` whose estimate undershot the sample, which today claims keys it should not.

### 4.4 C1: the CLI

1. `decoy scan` card (`C:src/decoy/cli/scanning/_multi.py:360`): "Rows scanned 10,000 of about 28,058 (sample, head)" on a sample; "Rows scanned 4,812 (whole file)" on a whole read. "Key candidates: not checked (sampled scan; --rows 0 reads every row)" on a sample (`C:src/decoy/cli/scanning/_multi.py:368`). The multi-table card sums `scanned_rows`, not `row_count`, for "Rows scanned" (`C:src/decoy/cli/scanning/_multi.py:384`), because after item 3 `row_count` is the source count. The multi-table table's "Rows scanned" cell shows `scanned_rows` with the same basis words (`C:src/decoy/cli/scanning/_multi.py:397`).
2. `--show-fields` table: "Null rate (sample)" and "Distinct (sample)" headers on a sample.
3. `--json` (`C:src/decoy/cli/scanning/_multi.py:252`): each table object gains `basis`, `scanned_rows` and `row_count_exact`, and `row_count` becomes the source row count, as in the core (owner Q3). The flat single-file payload the same.
4. `decoy scan show` (`C:src/decoy/cli/scan.py:794`): "Nulls 0 (in 10,000 scanned rows)" and "Distinct 10,000 (in 10,000 scanned rows)" on a sample; `--json` gains top-level `basis` and `scanned_rows` from the table. A saved scan written before E1 is told apart by `scanned_rows is None` (the read model fills `basis` with `sample`, so a missing `basis` cannot be seen after reading): it shows "basis not recorded (read as a sample)". A `basis` the CLI does not know reads as a sample, matching the engine read model. One label helper in `C:src/decoy/cli/scanning/_multi.py` builds every label; `scan.py` is a legacy module over the 800-line cap and may not grow.
5. Docs: the scan reference and `decoy scan --help` epilog say what `sample` means and that `--rows 0` gives whole-file numbers; roadmap row, shipped log, CHANGELOG `Breaking:` entry.

### 4.5 Design notes

- Principle: one place per fact (`architecture.md`). The basis rule, the key rule and the field classes each live once, in `_basis.py`; the end-of-source proof lives once, in the `sample_frame` contract; the CLI reads the engine's `basis` and never recomputes it. Change pain addressed: three surfaces each grew their own partial label, and a reader's short read was trusted as an end.
- Pattern followed: the existing value registry (`VALUE_FIELDS`, `VALUE_FREE_FIELDS`) and its both-ways sentry. `FIELD_BASIS` uses the same walk, with the root added to the key.
- No new abstraction beyond one enum, two functions, one mapping and one reader helper; no flag arguments; `read_basis` takes the three facts it needs.

## 5. Behaviour

| Input | Before | After |
|---|---|---|
| CSV, 25,000 rows, default scan | `row_count` 28,058 (estimate), field counts over 10,000 rows unlabeled, `key_candidates: ["id"]` | same counts; `basis: "sample"`, `scanned_rows: 10000`; `key_candidates: []`; card says not checked |
| CSV, 4,812 rows, default scan | `row_count` an estimate, `row_count_exact: false` | `row_count` 4,812, `row_count_exact: true`, `basis: "whole"`, keys claimed |
| Any file, `--rows 0` or `strategy="full"` | numbers exact, no label | `basis: "whole"`, `scanned_rows == row_count` |
| Exactly 10,000 rows, cap 10,000 | keys claimed | `basis: "whole"`, keys claimed (owner Q5 (b): one extra row read proves the end) |
| 10,001 rows, cap 10,000 | keys claimed from 10,000 rows | `basis: "sample"`, no keys |
| S3 or GCS CSV over 1 MiB with more than 10,000 wide rows | about 1 MiB of rows profiled, short read | 10,000 rows profiled, `basis: "sample"`, `row_count_exact: false` |
| `decoy.scan(df)` then `profile_document` | no basis key | `"basis": "whole"` or `"sample"` |
| Chunked mask run | first-chunk columns `sampled=False`, possible key flag | `sampled=True`, no key flag; masked bytes unchanged |
| Planner `profile_source`, CSV whose estimate undershoots | columns `sampled=False`, key flagged from a prefix | `sampled=True`, no key flag |
| Saved scan from an older engine | read as-is | reads with `basis: "sample"`, `scanned_rows: null`; exports and strips as before |

## 6. Failure modes

1. Owner Q5 (a) instead of (b): a head read of exactly the cap is labeled `sample`, and so is a random read of a source holding exactly the cap rows. Accepted under (a); the cost is one unclaimed key. Under (b), recommended, both read as `whole`.
2. A caller hands `profile_columns` a frame that is already a sample with `sample_strategy="full"`. The profile says `whole`. This is the caller's statement; the CLI and `scan_sources` never do it (`scan_sources` stamps from the reader). Documented in the docstring.
3. A forged profile document carries `basis: "whole"`. A label is not a cell value, and no trust decision rests on it; the redactor keeps only the two literal values (AT-8).
4. A hand-edited `scan-set/v1` core claims `basis: "whole"` with `scanned_rows < row_count`. The write model refuses it; the read model ignores validators by design (contract 3.1), so the CLI shows what is written. Readers never infer a key; they read `key_candidates`.
5. A golden or parity capture pins a first-chunk plan hash. E2 moves it; the owning tool regenerates it and the build record lists each move (stop line 4).
6. A new profile field is added without a basis class. The sentry fails (AT-11).
7. `Literal` support in `_conforms` keeps more than it should. It accepts only the literal's own strings; AT-8 feeds near-miss strings, a bool and an int.
8. The CLI pins an engine release without E1. Every scan would show "not recorded". Stop line 6 forbids merging C1 before the repin.
9. A cloud CSV row longer than the doubled windows can hold, or an object with no newline at all. The loop ends when the buffer covers the object, so it reads the object once at most; the result is what pandas parses, as `to_frame` would give. AT-0c covers a single 3 MiB row.
10. A reader added later (Azure, SFTP) returns a short frame before the end. The coverage sentry fails until it is in the conformance matrix, and the matrix fails it (AT-0b).
11. A pre-change record in a library is exported after the upgrade. The legacy branch of the validator keeps it exportable; without it `_strip` returns `None` and the record is withheld (AT-17).

### 6.1 Recurring-defect class table (vault plan-contract catalog)

| Class | Name | Where it could appear here | Closing structure | Sentry or test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new `basis` key in a plain profile document, and the CLI labels | `basis` is a closed `Literal`, kept by the one redactor only when it is one of its two strings; CLI labels are fixed text plus integers | AT-8; the existing `tests/sentry/profiling/test_profile_value_registry.py` forces the new field's classification | type the field as `str` (AT-8 red: a cell-like string survives) |
| 2 | Cleanup on an exit path | the cloud CSV loop holds a GCS client and S3 response streams across several ranged reads | GCS keeps the existing `with _clients.gcs_client()` block around the whole loop; S3 reads go through `_s3_range`, which already closes each stream | AT-0a runs both; existing `tests/unit/profile/test_cloud_reader_s3_errors.py` | open a GCS client per window outside the `with` (the fake client's close count fails AT-0a) |
| 3 | State machine and concurrency | N/A: profiles are frozen values built once per read; no shared state or lock is added | - | - | - |
| 4 | Route parity and silent fallback | head, random, full, DataFrame, first-chunk, `profile_source`, empty-input and every reader must agree on the end proof and the basis rule | one `sample_frame` contract, one `read_basis`, one `claim_keys`, one `_as_chunk_sample` | AT-0a, AT-0b, AT-1 to AT-6, AT-12, AT-13, AT-16 | derive basis from `strategy` alone (AT-5 red); return the first window only (AT-0a red) |
| 5 | Referential integrity | relationship facts keep their own `exact` and `bounded` labels; the first-chunk profile has no relationships | `RelationshipFactsCore` fields are `SOURCE` in `FIELD_BASIS`; no FK path changes | AT-11; existing relationship cases in `tests/unit/profiling/test_scan_set.py` | drop the relationship entries from the registry (AT-11 red) |
| 6 | Untrusted producer | a loaded profile document or saved core with a forged `basis`, an unknown `basis`, or missing members | strict `Literal` conformance in the redactor; read defaults and the unknown-token rule fail closed to `sample` | AT-8, AT-9, AT-C6 | default the read model to `whole` (AT-9 red) |
| 7 | Check then use on a path | N/A: no path is checked and later opened by this change; the cloud object size is read once per call and the loop stops at it | - | - | - |
| 8 | Weak tests and overclaimed evidence | a test that only checks a key exists, a probe on a file shorter than the cap, or a cloud test whose object fits in one window | hostile fixtures: unique in the sample, duplicated after it, nulls only after it; cloud objects over 1 MiB with more than 10,000 rows; probe output recorded in 1.2 | AT-0a, AT-2, AT-12, AT-18 | build the cloud fixture under 1 MiB (AT-18 then passes on `main`; the gate checks the size) |
| 9 | Behavior-preserving refactor drift | `claim_keys` and `_as_chunk_sample` move logic; masked output must not move | characterization: chunked output bytes and `PINNED_HASH` unchanged | AT-14, AT-15 | drop sampled columns' counts from the hash bytes (AT-15 red) |
| 10 | Frozen contract drift | `scan-set/v1`, `profile_document` and `decoy scan --json` gain members, and `key_candidates` changes meaning | additive members with read defaults; `Breaking:` entries; schema snapshots regenerated by their tools; a frozen pre-change sample in the corpus | AT-9, AT-10, AT-17, AT-C2, `tests/unit/profiling/test_scan_core_move.py` | remove the read default for `basis` (the corpus sample fails to read) |

### 6.2 dev-rules recurring-defect catalog, by name (`/home/cam/dev-rules/catalogs/recurring-defects.md`)

| # | Class | Applies here | Guard |
|---|---|---|---|
| 1 | Anchored validation | No: no regex validates a whole value in this change. `basis` is a `Literal`, compared exactly. | - |
| 2 | Strict wire and stored types | Yes: `TableCore.basis` and `TableCore.scanned_rows` are persisted. `_Core` is strict; the read model keeps `strict=True`. | AT-10 write cells and AT-9 read cells: `scanned_rows` as `True`, `"10000"` and `10000.0`, and `basis` as `True`, `1` and `["whole"]`, each refused on write and on read. |
| 3 | No exception context | Covered: the new validator raises inside pydantic, and `records/_codec.py` already raises its `RecordError` after the `except` block; the cloud loop reuses `_s3_range` and `_clients.gcs_download`, which wrap SDK errors. | Existing `tests/unit/profile/test_cloud_reader_s3_errors.py`; AT-10 asserts the `RecordError` from a refused payload has `__cause__` and `__context__` both `None`. |
| 4 | Versioned read models | Yes: the scan core read model gains an enum. The reader stays derived from the writer by `_relaxed`; the unknown-token rule makes a later-minor value read as `sample`, not as free text. | AT-9 cells: next major `scan-set/v2` refused, missing tag refused (existing), free text `"Jane Roe"` in `basis` reads as `sample` and is not echoed, the later-minor value `"exact"` reads as `sample`. |
| 5 | Normalized guard scanners | No text scanner is added. Both new sentries walk imported classes and type hints, not source text, so spelling normalization does not apply. | Seeded cases in AT-0b and AT-11. |
| 6 | No reaching into private modules | Covered: `scan_set` keeps its lazy `from decoy_engine import profile` import; `_basis.py` is in the `profiling` package it serves; the planner names stay strings. The CLI reads JSON members, not engine private modules. | Reviewers check for a new `from decoy_engine.<other>._x import` in production code. |
| 7 | No hidden CI failures | No CI configuration changes. | - |
| 8 | One input, one trust class per entry point | No new entry point; `profile_columns`, `scan_sources` and `first_chunk_profile` keep their signatures. | - |
| 9 | Mutations on the final head | Yes: every named mutation in section 9. | Stop line 8: rerun on the final head and record it. |
| 10 | Allowlisted helpers are still checked | No allowlist entry is added to any sentry. | - |
| 11 | No raised caps | Yes: `_value_redaction.py` near 600, `_cloud_readers.py`, `profiling/` fan-out at 24 of 25, `C:src/decoy/cli/scan.py` over its cap. | Stop line 5; section 10 sizes. |

### 6.3 Field basis class table

Every field that can come from a sample, and every other field, gets one class per root. `SCANNED` fields take their record's carrier.

| Root, surface and type | `SCANNED` | `CHECKED` | `SOURCE` | `LABEL` |
|---|---|---|---|---|
| document `ColumnProfile` | `reid_risk_columns`, `reid_risk_score`, `quasi_identifier_groups`, `k_anonymity` | - | - | `source_label`, `row_count` (rows scanned, `profiling/types.py:171`), `sample_strategy`, `sample_row_cap`, `basis` (new), `engine_version`, `generated_at`, `fields` |
| document `FieldStats` | every count, rate, range, length, class and pattern field (`null_count`, `null_rate`, `distinct_count`, `unique_rate`, `is_likely_unique`, `inferred_type`, `min_value` to `distribution`, `pii_score`, `detection_trail`, `domain`, `top_values`, `sentinels`, `detector_matches`) | - | - | `name`, `row_count` (scanned), `dtype_raw` |
| document `TopValue`, `Distribution`, `SentinelFlag`, `DetectorMatch`, `DetectionSignal` | every field | - | - | - |
| scan_core `TableCore` | `reid_risk_score`, `quasi_identifier_groups` | `key_candidates` | `row_count`, `row_count_exact` | `name`, `descriptor`, `sample_strategy`, `sample_row_cap`, `basis` (new), `scanned_rows` (new), `fields`, `warnings` |
| scan_core `FieldCore` | `dtype`, `null_count`, `null_rate`, `distinct_count`, `pii_score`, `pii_candidate`, `detector_hits`, `leading_zero_count`, `model_hits` | - | - | `name` |
| scan_core `ModelHitCore`, `ModelRefCore` | `band`, `rate_bucket` | - | - | `source`, `detector_id`, `model`, `id`, `version` |
| scan_core `RelationshipFactsCore`, `ChildFactsCore` | - | - | every count (own `exact`, `bounded` labels) | `parent`, `parent_columns`, `table`, `columns`, `status`, `exact`, `bounded`, `warnings` |
| scan_core `ScanSetCore`, detector run cores | - | - | - | `scan_schema`, `engine_version`, `scanned_at`, `tables`, `relationships`, `detectors`, `source`, `model` |
| planner `ColumnProfile` | `dtype`, `null_count`, `distinct_count`, `avg_length`, `max_length` (carrier `sampled`) | `is_candidate_key_sampled` | `row_count` | `name`, `sampled`, `declared_pk`, `is_fk`, `fk_target`, `pii_class` |
| planner `TableProfile`, `Profile`, `Relationship` | - | - | `row_count`, `row_count_exact` (chunk facts on a first-chunk profile, section 4.1) | every other field |

`dtype` and `inferred_type` are `SCANNED` because they are inferred from the scanned rows (a column empty in the first 10,000 rows reads as `object`).

`FieldStats.is_likely_unique` is `SCANNED`, not `CHECKED`. It is a heuristic (`unique_rate > 0.9`, `profiling/types.py:78`), not a key claim, and its name says "likely". Its readers use it as a hint: the file schema snapshot maps it to `is_primary_key` (`walks/cross_file.py:111`) and init inference suggests `hash` for a likely-unique integer (`C:src/decoy/cli/_init_inference.py:286`). Making it `CHECKED` would empty it on every default scan and change masking suggestions, a behaviour change outside this row. Its table's `basis` labels it; the `is_primary_key` mapping in `walks/cross_file.py` is logged in section 16.

The builder fills this table into `FIELD_BASIS`; the sentry, not this table, is the authority, and any field the table missed fails it.

## 7. Enumerations

### 7.1 Exit paths

- `decoy scan` success (exit 0): labels added; no new exit code and no new reason code.
- `scan_sources` refusals (`PipelineConfigError` for a bad `sample_rows`, `profiling/scan_set.py:176`; `ScanSourceError`): unchanged. A cloud read error inside the new loop is wrapped by `_scan_one` exactly as a first-window error is today.
- `ColumnProfile.__post_init__` (`profile/_types.py:105`): `_as_chunk_sample` sets `sampled=True` and the key flag `False` in one `replace`, so the H6 check never fires.
- `TableCore` write validator: a new `ValidationError` path, reachable only by an engine bug or a hand-built payload (AT-10).
- Records import and export of a pre-change core: no new refusal; the legacy branch validates it (AT-17).
- Chunked mask run: exit codes and reasons unchanged (AT-14).

### 7.2 Routes

- Scan head: `profiling/scan_set.py:295` (`reader.sample_frame(cap + 1)`), through each reader:
  - local CSV `CsvFileSource` (`profile/_readers_csv.py:98`), local Parquet (`profile/_readers.py:406`), fixed width (`profile/_readers.py:442`), resident table (`profile/_readers_resident.py:48`): meet the contract today;
  - S3 Parquet and GCS Parquet (`profile/_cloud_readers.py:217`, `profile/_cloud_readers.py:319`): meet it through `head_frame_from_batches`;
  - S3 CSV and GCS CSV (`profile/_cloud_readers.py:254`, `profile/_cloud_readers.py:357`): fixed by E0;
  - Azure and SFTP: no profile reader exists (`profile/_readers.py:499`); a later one is caught by the coverage sentry.
- Scan random and full: `profiling/scan_set.py:289` (`reader.to_frame()`; random samples after the read, and `reached_end` is known from the full length).
- `decoy.scan()` and `profile_columns` on a DataFrame: `C:src/decoy/api.py:727`, `profiling/profiler.py:298`.
- Planner `profile_source` bounded (default 10,000 rows): `profile/_source.py:249`, changed by E2 item 2; `residency="full"` reads `to_frame` and is unchanged.
- Lifecycle estimate: `execution/pipeline/_lifecycle_inputs.py:83` calls `sample_frame(SAMPLE_ROWS)`; under E0 a cloud CSV gives it the rows it asked for. It reads no basis.
- Chunked oracle lane: `execution/_chunked_oracle.py:240` and `execution/_chunked_oracle.py:250` (carried columns).
- Chunked legacy `auto_chunk` lane: `execution/_pipeline_auto_chunk.py:193`.
- Chunked native dispatcher: `execution/native/_dispatch.py:211` reads the same profile and no count from it.
- Empty chunked input: `execution/_chunked_profile.py:101` (`empty_input_profile`), unchanged.
- Fit snapshot: `profiling/_snapshot_values.py:584` profiles a head only to pick value-sensitive names; the snapshot covers the whole frame and is not changed.

### 7.3 FK shapes

- Declared relationships in a scan: `RelationshipFactsCore` already carries `exact` and `bounded` (`profiling/_scan_core.py:111`); classified `SOURCE`, not changed.
- Chunked runs: `first_chunk_profile` leaves `relationships` empty (`execution/native/_dispatch.py:211`), and FK tables reroute to the oracle; no FK path reads the changed flags.
- Planner `profile_source`: `declared_pk` and `fk_target` come from config, not from the sample, and E2 item 2 does not touch them.

### 7.4 Fields

- Section 6.3 classifies every field; the new ones are `profiling.ColumnProfile.basis` (last field, after `profiling/types.py:196`), `TableCore.basis` and `TableCore.scanned_rows` (`profiling/_scan_core.py:86`).
- `key_candidates` keeps its type and changes meaning on a sample (`profiling/scan_set.py:362`).

### 7.5 Output surfaces

- `scan-set/v1` core (`decoy scan --output`, `scan_set_to_dict(detail=False)`): two members and the key rule.
- `scan_set_to_dict(detail=True)` `detail` member: the nested profile dict gains `basis`.
- `profile_document` and `redact_profile_dict` (the demo `scan.json`, `decoy.scan()` saved through it): `basis`.
- Records library: a `scan-set` record carries the new members; `export_lines` strips and exports old and new records alike.
- `decoy scan` card, multi-table card and table, `--show-fields` table, `--json` flat and multi payloads (`C:src/decoy/cli/scanning/_multi.py:252`).
- `decoy scan show` card and `--json` (`C:src/decoy/cli/scan.py:794`).
- `decoy scan fields`: unchanged (PII scores and quasi-identifier membership only).
- Planner `profile_to_json` and `plan_to_yaml`: no new key; a first-chunk profile is never serialized by a route (AT-14).

## 8. Reuse inventory

| Need | Existing piece | Use |
|---|---|---|
| Walk every type a profile document reaches | `profile_types()` and `_walk` in `_value_redaction.py` | the sentry walks root `document` with it; no second walker |
| Registry-plus-sentry pattern | `VALUE_FIELDS`, `VALUE_FREE_FIELDS`, `tests/sentry/profiling/test_profile_value_registry.py` | `FIELD_BASIS` copies the both-ways coverage test and the seeded extra-field mutation, with the root added to the key |
| Strict key retention in a loaded document | `_shape_keep`, `_conforms` | extended with `Literal`; no second retention check |
| Old-record read defaults | `ScanSetCoreRead` from `_relaxed` | defaults carry over; `swap` gains the one token rule |
| Cloud ranged reads | `_s3_range`, `_clients.gcs_download`, `_csv_sample_from_window` | the loop reuses them; no new SDK call |
| Head of a batch stream | `head_frame_from_batches` (`profile/_readers.py:456`) | already meets the contract for every Parquet reader |
| Cloud reader fakes | moto S3; `_FakeGcsClient` in `tests/unit/profile/test_duplicate_header_readers.py` | conformance matrix; moved to a shared test helper if two files use it |
| H6 key invariant | `ColumnProfile.__post_init__` (`profile/_types.py:105`) | `_as_chunk_sample` and the walker satisfy it; no second check |
| Records corpus | `tests/integration/compat_corpus/regenerate.py`, `tests/unit/records/test_corpus.py` | one more writer and two frozen samples |
| Schema snapshot | `tests/unit/profiling/test_scan_core_move.py` with `tests/fixtures/f07/scan-set-core-schema.json` | regenerated, not hand-edited |
| CLI `--json` shape snapshot | `C:tests/e2e/release_freeze/write_shapes.py`, `C:tests/fixtures/release_freeze/json-shapes.json` | regenerated by its writer |

## 9. Acceptance tests (red first)

Each must fail on `origin/main`, except the characterization tests AT-14, AT-15, AT-16 and AT-17's corpus read, which pass before and after. The fixture `hostile_25k.csv` is built in the test: 25,000 rows, `id = i % 12000`, `n` null on every 7th row after row 10,000, `u` unique throughout. The fixture `wide_25k.csv` is 25,000 rows of about 300 bytes (about 7.5 MiB, well over the 1 MiB window), with `id` unique in the first 3,000 rows and repeated after.

| AT | What | Fails today because | Named mutation |
|---|---|---|---|
| AT-0a | Conformance, every reader: 3-row source asked for 5 gives 3; `wide_25k.csv` asked for 10,000 gives 10,000 and asked for 10,001 gives 10,001. S3 CSV and Parquet on moto, GCS CSV and Parquet on the fake client (which counts client closes), local CSV, Parquet, fixed width and resident on disk or memory | S3 and GCS CSV return about 3,500 rows | return the first window's parse only |
| AT-0b | Coverage sentry: the set of classes under `decoy_engine.profile` and `decoy_engine.profiling` that define `sample_frame` equals the conformance matrix; seeded: one extra reader class fails it | no sentry | skip modules whose name starts with `_cloud` |
| AT-0c | GCS and S3 CSV with one 3 MiB row then 5 short rows, asked for 4: returns 4 rows, fetches at most the object once | first window has no complete row | stop the loop at a fixed byte ceiling below the object size |
| AT-1 | Default head scan of `hostile_25k.csv`: table `basis == "sample"`, `scanned_rows == 10000`, `row_count >= 25000` | no members | hard-code `basis = "whole"` in `_table_core` |
| AT-2 | Same scan: `key_candidates == []`; with `sample_rows=None`: `key_candidates == ["u"]` (`id` is not a key over the file) | `["id", "u"]` today | delete the basis condition in `claim_keys` |
| AT-3 | Head scan of a 4,812-row CSV: `basis == "whole"`, `row_count == 4812`, `row_count_exact is True`, `scanned_rows == 4812` | estimate, not exact | keep `max(count.value, len(frame))` on the proven-end read |
| AT-4 | Head scan, cap 10,000: a CSV of exactly 10,000 rows gives `basis == "whole"` and claims `u`; a CSV of 10,001 rows gives `sample`, `scanned_rows == 10000`, no keys | 10,001 rows claims keys | ask `sample_frame(cap)` instead of `cap + 1` |
| AT-5 | Random strategy: 25,000 rows, cap 10,000 gives `sample`; 4,812 rows gives `whole`; exactly 10,000 rows gives `whole` | no members | derive basis from `strategy` alone |
| AT-6 | `strategy="full"`: `basis == "whole"`, `scanned_rows == row_count`, `sample_row_cap is None` | no members | treat `full` as a sample when a cap is passed |
| AT-7 | `profile_columns(df.head(100), sample_strategy="head", sample_row_cap=100)` on a 1,000-row frame gives `sample`; on a 50-row frame gives `whole`; `profile_document` keeps the key in both; `basis` is the last key of `to_dict()` | no key | default `basis` to `"whole"` |
| AT-8 | `redact_profile_dict` on a loaded document with `basis` set to `"Jane Roe"`, `True`, `1`, `"WHOLE"`: the key is dropped; `"whole"` and `"sample"` survive | key unknown, always dropped | accept any `str` for a `Literal` hint |
| AT-9 | Read model, `read_scan_set`: the frozen pre-change core `records/scan-set-v1-core.json` reads with `basis == "sample"` and `scanned_rows is None`; class 4 cells: `basis` `"exact"` and `"Jane Roe"` read as `"sample"` and the text appears nowhere in the parsed model; `scan_schema` `"scan-set/v2"` and a missing tag refused; class 2 read cells: `scanned_rows` `True`, `"10000"`, `10000.0` and `basis` `True`, `1`, `["whole"]` refused | members absent; unknown basis refused once the member exists | read default `"whole"`; drop the token rule from `_relaxed` (an `"exact"` record stops reading) |
| AT-10 | Write model: refuses `basis="whole"` with `scanned_rows < row_count`, `basis="whole"` with `row_count_exact=False`, `basis="whole"` with `scanned_rows=None`, `scanned_rows > row_count`, `scanned_rows=-1`, and `basis="exact"`; class 2 write cells as in AT-9; accepts `scanned_rows=None` with `basis="sample"` (legacy); a `RecordError` from `records` on a refused payload has `__cause__` and `__context__` `None`. Producer test: `_table_core` on every route of AT-1 to AT-6 writes a non-`None` `scanned_rows` | no validator | delete the model validator; make `_table_core` omit `scanned_rows` (producer test red) |
| AT-11 | Sentry `tests/sentry/profiling/test_field_basis_registry.py`: the `(root, type, field)` keys reached from the three roots equal the keys of `FIELD_BASIS`, both ways; within a root each type name maps to one class; every type holding a `SCANNED` or `CHECKED` field sits under its root's carrier. Seeded: `FieldStats`, `FieldCore` and planner `ColumnProfile` each rebuilt with one extra field fail it; a fake root reaching two different classes named `Row` fails the one-class cell; collapsing the key to `(type, field)` makes the two real `ColumnProfile` classes collide and fails it | no registry | remove one registry entry; make the walk skip pydantic models; drop the root from the key |
| AT-12 | Property, `tests/unit/profile/test_partial_read_keys.py`: over (a) `first_chunk_profile` of every prefix length in {1, 10, 999, 1,000} of a 4,000-row table with `id` unique in each prefix, carried and not carried, and (b) `profile_source` bounded at `sample_rows` in {10, 1,000, 10,000} on `hostile_25k.csv`, `wide_25k.csv` and `skewed_25k.csv` (first 1,000 rows 200 bytes wide, the rest 10 bytes, so the estimate is about 2,200 rows), every output column whose read did not cover the source has `sampled is True` and `is_candidate_key_sampled is False`. The test computes "did not cover" from the fixture length, never from the profile | first-chunk `id` flagged; `skewed_25k.csv` at 10,000 rows flags `id` | drop `_as_chunk_sample`; drop the `n + 1` read in `profile_source` |
| AT-13 | `first_chunk_profile` on a 1,000-row slice with `id` unique in the slice, with and without `carried={"id"}`: every column `sampled is True`, `is_candidate_key_sampled is False` | `sampled=False`, key `True` | apply `_as_chunk_sample` before the carried replacement |
| AT-14 | Characterization: a chunked mask run (oracle and native lanes) of one source at chunk sizes 1,000 and 2,000 gives byte-identical output and identical route evidence; neither result, nor any file it writes, holds `profile_hash` or `plan_hash` | passes today; guards Q1 | add `plan.profile_hash` to the chunked route evidence |
| AT-15 | Characterization: `tests/unit/profile/test_hash_regression.py` `PINNED_HASH` and the `profile_source` hashes of its fixtures are unchanged | passes today | drop sampled columns' counts from `_data_shape_bytes` |
| AT-16 | Characterization: `empty_input_profile` and its compile are unchanged | passes today | apply `_as_chunk_sample` to the empty profile |
| AT-17 | Records, `tests/unit/records/test_corpus.py`: the frozen pre-change `records/scan-set-v1.json` decodes; `export_lines` on it without `keep_paths` exports it (not in `withheld_records`) with the descriptor path reduced to `claims.csv`; re-importing the export reads it back | the legacy branch is new; with the revision 1 validator the record is withheld | require `scanned_rows` in the validator (record withheld, AT-17 red) |
| AT-18 | Scan of `wide_25k.csv` on moto S3 (`type: s3`) and on the fake GCS client, default cap: `basis == "sample"`, `row_count_exact is False`, `scanned_rows == 10000`, `key_candidates == []` | about 3,500 rows read, keys claimed from them | the E0 mutation of AT-0a |
| AT-C1 | `decoy scan hostile_25k.csv --has-header`: card shows "of about" and "(sample, head)" and Key candidates "not checked"; the 4,812-row file shows "(whole file)" and the key | no labels | render `key_candidates` without reading `basis` |
| AT-C2 | `--json` flat payload: `basis`, `scanned_rows`, `row_count_exact`, and `row_count` equal to the core's source count; `json-shapes.json` regenerated | `row_count` is scanned rows | take `row_count` from `scan.profile.row_count` |
| AT-C3 | Two-file scan `--json`: each table carries the same four members | missing | drop `basis` from `_table_summary` |
| AT-C4 | `decoy scan show scan.json id` on a sampled saved scan: "(in 10,000 scanned rows)" on Nulls and Distinct; `--json` top-level `basis` and `scanned_rows` | no labels | drop the label helper call |
| AT-C5 | `--show-fields` headers read "(sample)" on a sample and plain on a whole read | no labels | always print plain headers |
| AT-C6 | `decoy scan show` on a saved core with no `basis` and no `scanned_rows`: "basis not recorded (read as a sample)"; on a core with `basis: "exact"` and `scanned_rows` set: the sample labels | no label | treat a missing `basis` as whole; test `basis` instead of `scanned_rows is None` |
| AT-C7 | Sentry `C:tests/sentry/cli_text/test_scan_basis_labels.py`: in the regenerated `json-shapes.json`, every object holding `null_rate`, `null_count` or `distinct_count` has `basis` on itself or its nearest table object | no labels | remove `basis` from the multi payload |
| AT-C8 | Two-file scan of `hostile_25k.csv` and a 4,812-row CSV: card "Rows scanned" is 14,812 and each table row shows its `scanned_rows` | card sums source counts after Q3 | sum `row_count` in `_render_multi` |

## 10. Placement (against CODEMAP.md "Where Things Go")

| Path | New or changed | CODEMAP row | Sits beside, note |
|---|---|---|---|
| `src/decoy_engine/profile/_cloud_readers.py`, `profile/_readers.py` (docstring), `profile/_source.py` | changed | "profile" row: readers and `profile_source` | `_cloud_readers.py` 394 lines, ends near 425; no new module in `profile/` |
| `src/decoy_engine/profiling/_basis.py` | new | "Detectors, profiling": by profiling concern | beside `_value_redaction.py`; `profiling/` has 23 counted modules, this makes 24 (cap 25, no allowlist entry); CODEMAP profiling row gains one clause |
| `src/decoy_engine/profiling/types.py`, `profiler.py`, `scan_set.py`, `_scan_core.py`, `_value_redaction.py` | changed | same row | `_value_redaction.py` 580 lines, ends near 586 (goal 600) |
| `src/decoy_engine/execution/_chunked_profile.py` | changed | `execution/` row ("the Arrow-native column profile lives in `_chunked_profile.py`") | no new module in `execution/` (fan-out frozen at 103) |
| `tests/sentry/profiling/test_field_basis_registry.py`, `tests/sentry/profiling/test_profile_source_contract_coverage.py` | new | sentry tests | beside `test_profile_value_registry.py` |
| `tests/unit/profile/test_sample_frame_contract.py`, `tests/unit/profile/test_partial_read_keys.py`, `tests/unit/profiling/test_scan_basis.py`, `tests/unit/execution/test_chunked_profile_basis.py` | new | owning package tests | - |
| `tests/integration/compat_corpus/regenerate.py`, `manifest.json`, `records/scan-set-v1.json`, `records/scan-set-v1-core.json`; `tests/unit/records/test_corpus.py` | changed and new | compatibility corpus | samples written once by `regenerate.py scan-set` at the pre-E1 head, then frozen |
| `docs/compatibility-contract.md` (scan-set paragraph, section 1 pre-GA corrections), `CHANGELOG.d/` fragments, `docs/qa/03-pre-scan-profiling-detection.md`, `CODEMAP.md` | changed | docs | - |
| `C:src/decoy/cli/scanning/_multi.py` | changed | "`decoy scan` internals" | 512 lines, ends near 575 (cap 800) |
| `C:src/decoy/cli/scan.py` | changed | same row; `scan.py` keeps only the options | legacy over 800; net line change zero or negative |
| `C:tests/sentry/cli_text/test_scan_basis_labels.py` | new | "Sentry test" | registered in `C:tests/sentry/test_sentry_manifest.py` |
| `C:tests/fixtures/release_freeze/json-shapes.json` | regenerated | "Versioned schema artifacts" | by `write_shapes.py` only |
| `C:docs/` scan reference, `C:docs/roadmap/groups/scan.md`, `C:docs/RECENTLY-SHIPPED.md`, CLI CHANGELOG | changed | docs, roadmap | - |

Public names added: none. `ColumnProfile.basis` is a new attribute on a frozen class with a default.

## 11. Size budget

| Slice | Production lines | Test lines | Docs lines | Production files |
|---|---|---|---|---|
| E0 | about 45 (`_cloud_readers.py` 40, docstring 5) | about 260 | about 15 | 2 |
| E1 | about 205 (`_basis.py` 120, the rest under 20 each) | about 460 plus two corpus samples | about 40 | 6 |
| E2 | about 26 | about 200 | about 10 | 2 |
| C1 | about 75 | about 220 | about 60 | 2 |

Stop at 10 production files or 800 changed lines per slice. No module-size entry, fan-out entry or ceiling is added or raised in either repo.

## 12. Frozen contracts

- `scan-set/v1` (contract 3.1, `docs/frozen-surfaces.md:54`): two additive members with read defaults; `key_candidates` empty on a sample. Tag unchanged. Schema snapshot regenerated. `Breaking:` entry for the meaning of `key_candidates`.
- `profile_document`, `redact_profile_dict` and `ColumnProfile` (frozen names, `docs/frozen-surfaces.md:80`): one new key and one new dataclass field with a default, appended last; no signature change. `Breaking:` entry for the new key.
- `ProfileSource` protocol: signature unchanged; the docstring now promises "fewer only at end of source". Internal, not a frozen name; the stronger promise is additive for callers.
- `flagged-redacted/v2` marker: unchanged; row 24zm's floor rules are not touched.
- `profile_hash` and `plan_to_yaml`: no rule change (Q1). A first-chunk hash moves but is never written (AT-14). A `profile_source` hash moves only on a partial read that today flags a key it should not.
- CLI `decoy scan --json` and `decoy scan show --json` (frozen at 1.0 by the freeze batch): new members, and `row_count` changes meaning in the CLI payload (Q3). `Breaking:` entry in the CLI CHANGELOG.
- After 1.0, `basis`, `scanned_rows` and the values `sample` and `whole` are frozen. A third value later (for example for the 1.x exact-aggregate opt-in) is a minor change, and that is now enforced, not assumed: the engine read model maps an unknown `basis` string to `sample` (section 4.2 item 5, AT-9), the redactor drops an unknown value from a loaded document (AT-8), and the CLI reads an unknown value as a sample (AT-C6). The alternative, declaring a new value a major change, was rejected: contract 3.1 promises that an older reader accepts a newer record within a major, and a refused enum value would break that promise for an additive change. The contract paragraph states the rule.

## 13. Slices

| Slice | Content | Risk | Depends on | Tests at T1 | Gate |
|---|---|---|---|---|---|
| E0 | 4.0: `sample_frame` contract docstring, cloud CSV window loop, conformance test, coverage sentry | R2 (reader contract other routes use) | none | AT-0a to AT-0c, `tests/unit/profile/`, `tests/connectors/test_s3_error_text.py`, `tests/connectors/test_gcs_error_text.py`, `tests/acceptance/test_f06_csv_framing.py`, module size | T2 on the exact head; Dennis then Codex |
| E1 | 4.1, 4.2: corpus samples first, `_basis.py`, `basis` on the profile document, `TableCore` members, legacy-aware validator and read token rule, proven-end head read and stamp, `claim_keys`, `Literal` conformance, registry sentry, contract paragraph, CHANGELOG fragment, QA checklist line, CODEMAP | R2 | E0 merged; 24zm E1b merged (it is, engine #665) | AT-1 to AT-11, AT-17, AT-18, `tests/unit/profiling/`, `tests/sentry/profiling/`, `tests/unit/records/`, `tests/integration/compat_corpus/`, `tests/unit/test_public_api.py`, module size, fan-out | T2 on the exact head, plus the full engine suite against the saved main baseline (frozen-contract and serialization trigger); Dennis then Codex |
| E2 | 4.3: `_as_chunk_sample`, `profile_source` `n + 1` read, docstring, AT-12 to AT-16 | R1 (R2 if any golden moves) | E0 merged (AT-12's cloud-free fixtures do not need it, but the `n + 1` read relies on the contract) | AT-12 to AT-16, chunked profile tests in `tests/unit/execution/`, `tests/unit/profile/`, chunked cases in `tests/parity/` | T2; Codex (Dennis too if a golden moves) |
| C1 | 4.4: cards, fields table, `--json`, `scan show`, CLI sentry, docs, roadmap row, shipped log, CHANGELOG | R2 | E1 released and the CLI repinned (engine repin checklist) | AT-C1 to AT-C8, `C:tests/e2e/` scan tests, `C:tests/e2e/release_freeze/test_json_shapes.py`, `C:tests/sentry/` | T2; Dennis then Codex |

Engine first: E0, then E1 and E2 in parallel (separate worktrees), then the engine release and repin, then C1. Tests run on the Mac first, then `~/bin/vm-run`, never on the devbox.

### 13.1 Order against related work

- Row 24zm (PROFILE-UNFLAGGED-VALUES): E1a (#629) and E1b (#665) are merged. E1 here adds one `VALUE_FREE_FIELDS` entry and the `Literal` rule next to its registry and changes none of its floor rules. 24zm C1 (CLI docs and the demo `scan.json` test) is open; C1 here touches neighbouring CLI docs, so whichever merges second rebases. Both ride the same engine repin if E1 lands in time.
- Freeze batch (`origin/plan/freeze-batch`): E0, E1 and E2 should merge before the freeze engine release so its one CLI repin carries them, and C1 must merge before REL-GATE G0 (2026-12-04). If E1 misses that cut, it ships in the next daily engine release and C1 follows its repin. This plan adds no public name and no `"<name>/vN"` tag, so the freeze batch's stability registry (X0) and tag census (S7) need no row. If E2 moves a golden, whichever of E2, FREEZE-OUTPUT O1 and O3, and FAKER-MIGRATE S2 lands later reruns the owning tools named in freeze-batch section 5.6 and requires a clean `git status`.
- Row 24f (fit redaction): merged. The fit snapshot is a whole-frame document (`profiling/_snapshot_values.py:584` only picks names from a head), so it needs no basis label; its types are outside the three roots.

## 14. Stop lines for builders

1. One end proof (the `sample_frame` contract), one basis rule (`read_basis`), one key rule (`claim_keys`), one chunk transform (`_as_chunk_sample`), one registry (`FIELD_BASIS`). The CLI reads `basis` from the engine's output and never recomputes it.
2. Do not change `_data_shape_bytes`, `PINNED_HASH`, `VALUE_FIELDS`, `PROFILE_FLOOR_FIELDS`, `PROFILE_FLOOR_KEEP` or the `flagged-redacted/v2` marker.
3. Do not add a parameter to `profile_columns`, `scan_sources`, `first_chunk_profile`, `profile_source` or `ProfileSource.sample_frame`, and add no public name.
4. A golden, parity capture or schema snapshot that moves is regenerated by its owning tool and listed in the build record; none is edited by hand. A moved masked-output golden is a stop: E2 must not change masked bytes. The two corpus samples are written once, at the pre-E1 head, and never regenerated after the E1 production change.
5. `_value_redaction.py` stays at or under 600 lines and `C:src/decoy/cli/scan.py` must not grow; if either would, stop and report.
6. C1 does not merge before the CLI pins an engine release that holds E1.
7. Do not flip `TableProfile.row_count_exact` for the first chunk (`execution/capacity.py:481` reads it).
8. Write the acceptance tests first and show each red before the fix; attack your own diff with each named mutation and rerun them on the final head, recording it. Never widen a threshold, skip a test or weaken an assertion; a red test outside the ones named here is a stop. Commits: Conventional Commits subject at most 72 characters, final line `cam`, no other trailers.

## 15. Owner questions

Recommended answer first in each.

1. First-chunk hash. (a) Label the chunk as a sample and keep the hash rules (recommended). The row allows it; (b) moves every sampled `profile_source` plan hash and `PINNED_HASH`, and no route writes a first-chunk hash (AT-14 keeps it so). (b) Hash a sampled column without its `null_count` and `distinct_count`. Choose (b) only if plan hashes must not depend on how much was read, because after the freeze that is a 2.0 change.
2. Where the label sits. (a) One `basis` and `scanned_rows` per table record, and `basis` on the profile document, with the registry deciding which fields each governs (recommended). Every field of a table comes from one read, so a per-field key repeats one fact in every record. (b) A `basis` key on every field record.
3. CLI `--json` `row_count`. (a) Make it the source row count, as in the saved core, and add `scanned_rows`, `basis` and `row_count_exact` (recommended). Today the same key means scanned rows in `--json` and source rows in the saved core, and after 1.0 that split is frozen. (b) Keep `row_count` as scanned rows and add `source_row_count`.
4. Keys on a sample. (a) `key_candidates` empty, and the card says "not checked (sampled scan; --rows 0 reads every row)" (recommended, Deequ's suggest-then-verify split). (b) Also add a `sample_unique_columns` list labeled as a hint, which freezes one more member holding a weak claim.
5. A read that returns exactly the cap (changed in revision 2). (b) Read one row past the cap and call the read `whole` when that row is absent (recommended). Under the E0 contract this costs one row per table, needs no new parameter (`scan_sources` stamps the basis with `dataclasses.replace`), and also makes a random scan of a source of exactly the cap rows `whole`. (a) Call it a sample: no extra row, and the cost is one unclaimed key on a file of exactly 10,000 rows and the same on a random scan of exactly 10,000 rows. Revision 1 recommended (a) on the belief that (b) needed a new `profile_columns` parameter; it does not.

## 16. Unresolved and V2-LOG

- Found while planning, outside this row: the planner's unique-capacity check computes `row_count - null_count` from a source `row_count` and a sample `null_count` (`plan/_checks.py:161`), and the routing saturation guard reads sampled distincts (`execution/_pipeline_routing_signals.py:460`). Neither reaches output, and neither is a 1.0 break. Recommended: a new 1.x row; `FIELD_BASIS` gives that fix its input.
- `walks/cross_file.py:111` maps the sampled heuristic `is_likely_unique` to `is_primary_key` in a file schema snapshot. It is a hint path, not a key claim in a frozen output; recommended: fold into the same 1.x row, reading the profile's `basis`.
- The planner's `profile_source` on a fully read small CSV can still report an estimate above the frame length and mark columns `sampled=True`. That fails safe (no key claimed) and changing it would move fixture hashes; logged, not fixed.
- `TableCore.sample_strategy` is a `Literal` without the unknown-token rule, so a later strategy value would be refused by an older reader. Not this row; the token rule in `_relaxed` is the pattern if it is ever extended.
- The 1.x opt-in for exact whole-file aggregates over a sampled scan may add a basis value; section 12 says how it stays a minor change.
- Platform consumers of `ColumnProfile.to_dict()` (platform parked) read the new key with its default.

## 17. Pre-mortem

- Key claims disappear for every default scan of a large file and users read that as "no keys". Mitigation: the card says "not checked" and how to check; the docs say why.
- A reviewer finds a sample-derived field that section 6.3 missed. The sentry turns that into a build failure, not a review finding; the table is advice to the builder.
- `Literal` support in `_conforms` keeps a value it should drop. AT-8 feeds near-miss strings, a bool and an int.
- E2 moves a masked-output golden because some admitted strategy did read a profile count. AT-14 catches it; stop line 4 stops the slice and the finding goes back to the plan.
- C1 merges against an engine without E1 and every scan shows "not recorded". Stop line 6 and the repin checklist prevent it.
- The freeze release is cut without E0 and E1. C1 then waits for a daily release; the 2026-12-04 gate still holds if E1 merges by 2026-12-01.
- The cloud window loop fetches far more than before on a large object with very wide rows. Bytes stay under about twice what the asked rows occupy, and the loop never passes the object size; AT-0c pins the single-huge-row case. If a run shows a slow first scan on cloud CSV, that is the sample the user asked for, which the old reader silently cut.
- A pre-change record becomes un-exportable after the upgrade. AT-17 runs `export_lines` on a frozen pre-change record in the corpus.

## 18. Done when

- E0, E1, E2 and C1 merged; the engine release holding E0, E1 and E2 pinned by the CLI.
- The probe in 1.2, rerun on the merged engine, shows `basis: "sample"`, `scanned_rows: 10000`, `key_candidates: []`, and first-chunk columns with `sampled=True` and no key flag; the same scan from moto S3 shows 10,000 scanned rows.
- Roadmap row PROFILE-SAMPLE-LABELS closed in `C:docs/roadmap/groups/scan.md` and the shipped log updated in the same CLI PR.
