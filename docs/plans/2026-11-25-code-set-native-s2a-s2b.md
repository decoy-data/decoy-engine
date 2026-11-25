Status: plan (revision 3, 2026-11-25, after Dennis round 1 and Codex round 1)

# CODE-SET-NATIVE S2a and S2b: value-free source conversion, and out-of-core admits code_set only on proved text columns

Owner: Cam. Author: Opus (plan author). Roadmap row: CODE-SET-NATIVE (1.0 row). Engine only. This plan replaces the "S2: re-plan" entry in `docs/plans/2026-11-22-code-set-native.md` (rev 7, on branch `plan/code-set-native`, section 12). It reuses the rev 5 design of that plan (section 5.2) and closes the three Codex round 3 findings that rev 5 left open.

Source anchor: engine main `2b8a47fbe`. Paths without a prefix start at `src/decoy_engine/`. Builders re-anchor line numbers on their merge head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `feature-dev.md`, `cross-cutting-concerns.md`, `architecture.md` (layout, fan-out, size); engine `CODEMAP.md` ("Where things go").

Risk: R2 (route admission for a masking strategy; masked output on the out-of-core route; one shared ingestion boundary). Plan review: Dennis, then Codex. Code gate: Codex, plus Dennis on S2b.

Slice order changed in revision 3. S2a is now the value-free conversion boundary (small, no dependency on #808, also a prerequisite of BUCKET-TOPCODE-NATIVE S1b). S2b is the proof and every consumer. Reason: S2b sends more jobs to full frame and sequential, and those routes can raise a pyarrow error that carries a source value. The leak must be closed before the route change.

## 0. Dependency on PR #808 (S1)

S1 is PR #808 (`feat/code-set-native-s1`), head `68bcad3e8`, with Codex fixes in progress (mode check at the top of `apply_code_set`, URL credentials stripped from corpus diagnostics). S2a does not depend on #808. S2b branches from main after #808 merges and assumes these facts from it:

1. The full-frame handler `execution/_strategies/_code_set.py` masks with a bounded memo. A column that out-of-core declines goes to full frame or sequential and runs that handler. While the memo is under its caps, a repeated value costs no new corpus selection. After a cap is reached, an unseen value is computed per row again (#808 `execution/_strategies/_code_set.py:248`). S2b makes no claim beyond that.
2. `_PER_VALUE_CODE_SET_ERRORS` is still defined in `execution/_strategies/_code_set.py`, and `execution/out_of_core/_mask_group_c.py:92` still imports it.
3. `apply_code_set` refuses a mode other than `mask` or `gen` with a value-free message, and corpus diagnostics pass through `fileaccess.shown`. The S2b builder checks both on the merge head; if either is missing, it stops and reports.
4. #808 does not touch any file under `execution/out_of_core/`, the routing files, the estimators or `declared_casting/`. If its final head does, the S2b builder re-anchors and reports the overlap before starting.

## 1. Frame

The out-of-core route reads the physical Arrow value and masks `str(value)` (`kernel/_code_set.py:35`, `code_set_map`). Full frame, the reference, masks `str(value)` of the value pandas rebuilds from the same table after `to_pandas_fk_safe` (`execution/_fk_keys.py:430`) has applied schema metadata and the null-to-float widening (`execution/_strategies/_code_set.py:202`). When the two strings differ, the two routes pick different corpus codes for the same input:

- Witness 1: int64 `[1, null, 2]`. Out-of-core masks `"1"`, `"2"`; full frame masks `"1.0"`, `"2.0"`.
- Witness 2: a `string` column `["1", null]` whose pandas metadata says `double[pyarrow]`. Full frame masks `"1.0"`, out-of-core masks `"1"`.
- Witness 3 (Codex round 1): `list<int64>` `[1, 2]`. The empty-frame dtype is `object`, pandas prints `"[1 2]"`, Arrow prints `"[1, 2]"`.

The mask is still keyed and the value is still replaced, so nothing leaks. The defect is that the same job gives different output on two routes, and a run that changes route changes its codes. That breaks referential integrity across runs, so it is in the V1 bar.

A second defect sits on the reference routes. When a physical string carries numeric pandas metadata and a value does not parse, `table.to_pandas()` (`internal/pandas_compat.py:131`) raises `ArrowInvalid: Failed to parse string: '<value>'`, and sequential re-raises it (`execution/_sequential.py:420`, `:658`). The source value reaches `str(exc)`. That is a non-admin data leak, so it blocks V1 on its own.

Codex round 3 (on rev 5) named three gaps. Where each is closed:

| Codex r3 finding | Where it is closed |
|---|---|
| 1. Routing builds its type facts from caller sources only (`execution/_pipeline_routing_signals.py:268`), so a `source_loader` job gets an empty proof | S2b: proof from caller schemas for resident tables and loader schemas for tables the caller does not hold; the runner proves on the tables it masks |
| 2. Capacity (`execution/capacity.py:362`), job estimate (`execution/_job_estimate.py:164`) and transform admission (`execution/_transforms_admission.py:382`) call `out_of_core_admission` without a proof | S2b: a keyword every caller passes on purpose; a missing proof rejects code_set; both estimators use one rule; an AST sentry |
| 3. Declared casting changes the schema before pandas sees it (`execution/_pipeline_full_frame.py:164`, `declared_casting/_boundary.py:263`), and the runner stages before its preflight (`execution/out_of_core/_runner.py:194`) | S2b: prove the schema the runner will mask (post-cast only when a cast actually runs) and check before staging |

## 2. Established solutions

Search run: the engine's own admission gates (`rg "source_types|out_of_core_admission"`), the pandas `Table.to_pandas` type-mapping docs (pandas metadata wins over the Arrow type; `types_mapper` and `future.infer_string` change object to `StringDtype`), and the rev 5 design. Findings:

- Type-directed admission: decide from the schema, never from values. The faker B4 gate (`execution/out_of_core/_compat.py:368`) does this for faker.
- Fail closed on missing facts, as `reject_null_bearing_int_ooc` does (`execution/out_of_core/_null_int_guard.py`).
- Ask the converter, but only inside a narrow physical domain: Codex round 1 showed `object` alone is not a proof (witness 3). The proof requires a physical `string` or `large_string` field, and then asks pandas whether metadata changes it.
- Translate third-party errors at one boundary: the engine already maps unconvertible integer columns to a coded error through `on_unconvertible` (`internal/pandas_compat.py:116`). S2a extends the same boundary to the whole-table conversion.

### Reuse inventory

- `to_pandas_fk_safe` (`execution/_fk_keys.py:430`) and `table_to_pandas_exact_ints` (`internal/pandas_compat.py:116`): the converter every pandas route uses (`execution/_pandas_adapter.py:205`, `execution/_sequential.py:420`). S2a puts the value-free translation there, so full frame, sequential and the chunked oracle get it at once.
- `check_out_of_core_compatibility` and `_group_c_conditional_rejection` (`execution/out_of_core/_compat.py:174`, `:405`): the gate. The existing code `out_of_core_code_set_shape_unsupported` keeps its meaning; a new code `out_of_core_code_set_type_unproved` covers an unproved type.
- `arrow_type` and `DeclaredCastRun` (exported from `declared_casting/__init__.py:12`): the post-cast type. The post-cast schema operation moves into `declared_casting` as a public function (S2b item 2), so that package stays the one owner of what a cast does to a schema.
- `source_facts_of` (`contracts/column_shape.py:104`): used only for the column-shape facts it already serves; the proof does not take its merged schema map (Codex round 1: it gives loader metadata precedence over a resident caller table).
- The `ooc_route_uncertain` downgrade in `execution/capacity.py:527`.
- `run_preflight` (`execution/out_of_core/_preflight.py:44`).
- `arrow_columns` and `stored_index_fields` (`_pandas_meta/_columns.py:26`, `:32`): the one home for stored index fields. The proof cannot live in `_pandas_meta`, which imports only `pyarrow` by contract.
- Related mechanisms, and how the proof relates to each:
  - `execution/_chunked_code_set.py:88` (`_SAFE_CODE_SET_SOURCE_CHECKS`, `unsafe_code_set_source_columns`): the chunked code_set gate, Arrow type only. Unchanged. AT-7 asserts on the same effective schema that every column the proof admits, the chunked gate admits. Open item 2 covers whether the chunked gate itself diverges on witness 2.
  - `execution/native/_faker_deterministic_admission.py:214` (`metadata_shape_admits`): a different question (identity of every value). Not reused.
  - `_arrow_types.py:21` (`is_text`): the physical-type half of the proof uses it.

## 3. Guarantee and non-goals

After S2a:

1. No error raised while converting a source table to pandas carries a source value. The translated error names the table (when known) and the column, with a stable code.

After S2b:

2. For every mask-mode code_set column without `chapter_preserve`, the out-of-core route runs only if the proof admitted that column in the schema the runner masks: the post-cast schema when a declared cast runs, the source schema otherwise.
3. Every caller of `check_out_of_core_compatibility` and `out_of_core_admission` passes the proof or states that it has none. No proof means code_set is rejected. The estimators never report FIT on an out-of-core route that rests on an unproved code_set column.
4. The refusal comes before anything is written. Through `run_pipeline` forced, routing raises `ooc_ineligible` (`execution/_errors.py:117`, `OUT_OF_CORE_INELIGIBLE`) whose message carries the reject code, table and column. A direct `run_fk_out_of_core` call, or the physical out-of-core driver, raises `out_of_core_code_set_type_unproved` before it opens a scratch arena, stages a declared copy, writes a quarantine record, or writes to a sink.
5. When out-of-core runs, its code_set output equals forced full frame, byte for byte, under default pandas options and `future.infer_string=True`.

Non-goals (V2-LOG or later rows): admitting integer code columns out-of-core (CS-S2-Q1); a native code_set operator on unified or chunked (CS-Q5); falling back to another route after the runner refuses (CS-S2-Q2); reading Parquet footers in the estimators; any change to gen mode or `chapter_preserve` admission.

## 4. Enumerations

### Exit paths (the admission decision for one code_set node)

Earlier rejections keep precedence; the proof check runs last. On an FK-bearing table these fire first, as today: a `code_set` parent key (`execution/out_of_core/_compat.py:233`), a scalar composite child (`:255`), `when` (`:284`), self-edges, cycles and composite chains (`:504`, `:521`, `:551`). A single-column FK child key is owned by FK resolution, not by code_set.

| # | Condition | Result |
|---|---|---|
| X1 | mode is not `mask`, or `chapter_preserve` is set (`execution/out_of_core/_compat.py:417`) | rejected as today, same code and message |
| X2 | proof is `None` (caller has no schemas) | rejected, `out_of_core_code_set_type_unproved`, message names table and column |
| X3 | a target column is not in the proof | rejected, same as X2 |
| X4 | every target column is in the proof | admitted |
| X5 | the empty-table conversion raises | the table proves nothing; X3 applies; the exception stays inside the builder |
| X6 | the frame's labels are not exactly `arrow_columns(schema)` in order (renamed, swapped or reordered by metadata) | the table proves nothing; X3 applies |
| X7 | the field's physical type is not `string` or `large_string` | not proved (witness 3, integers, binary, dictionary, `string_view`) |
| X8 | routing admitted on declared loader schemas, but the resolved loader table's schema gives a different proof | the runner refuses before staging with `out_of_core_code_set_type_unproved`, message says the loaded table's column type differs from `source_loader_schemas`. Auto and forced alike (OWNER CALL CS-S2-Q2) |

### Conversion exit paths (S2a)

| # | Condition | Result |
|---|---|---|
| C1 | `table.to_pandas()` succeeds | unchanged |
| C2 | it raises `pa.ArrowInvalid`, `pa.ArrowNotImplementedError`, `ValueError`, `TypeError` or `OverflowError` | raise a coded, value-free engine error `source_pandas_conversion_failed`, `from None`, naming the column found by converting each column alone; if no single column fails, the table only |
| C3 | the existing per-integer-column path with `on_unconvertible` | unchanged |
| C4 | any other exception | propagates unchanged (not a data error) |

### Routes

| Route | Before | After |
|---|---|---|
| auto, routing signals (`execution/_pipeline_context.py:514` into `resolve_execution_route`, `execution/_pipeline_routing.py:216` from `execution/pipeline/_lazy_input.py:144`, `execution/physical/_snapshot.py:209`, `execution/physical/_live_inputs.py:128`, `execution/pipeline/_stream.py:216`) | code_set admitted on shape | admitted only with proof |
| forced `execution_mode="out_of_core"` through `run_pipeline` | admitted on shape | routing raises `OUT_OF_CORE_INELIGIBLE` with the structured rejection (code, table, column); X8 at the runner |
| direct `run_fk_out_of_core` | stages, then checks | checks, then stages |
| physical out-of-core driver (`execution/physical/_shadow_coordinator.py:248` to `execution/physical/drivers/_out_of_core.py:67`, no `cast_run`) | admitted on shape | proved on the raw schema, since no cast runs |
| full frame, sequential, chunked oracle | memoized handler (#808); conversion errors can carry a value | handler unchanged; conversion errors value-free (S2a) |
| capacity estimate | priced as admitted | priced as admitted, FIT downgraded to UNKNOWN when an unproved code_set column is present |
| job estimate | priced as admitted | same rule as capacity: priced as admitted, plus a note |

### FK shapes

- code_set on a non-key column of an FK-bearing table: the common case. A decline moves the whole job off out-of-core.
- code_set on an FK key: earlier rejections own it (Exit paths, first paragraph); the proof never runs.
- A job without relationships never reaches out-of-core (`execution/_pipeline_routing_signals.py:265`).

### Fields

- Proof type: `frozenset[tuple[str, str]]` of (table, column), or `None`.
- A column is proved when all hold: the physical field is `string` or `large_string`; the empty-table frame's labels equal `arrow_columns(schema)` in order; the column's dtype is numpy `object`, `pd.StringDtype` (any storage), or `pd.ArrowDtype` of `string` or `large_string`.
- Schema to prove, per table: the resident caller table's schema when the caller holds it; the loader schema only for a table the caller does not hold. When a declared cast will run for that table, `declared_casting.cast_schema(...)` of that schema.
- Conversion error: code `source_pandas_conversion_failed`, message "source table '<table>' column '<column>' could not be read with its pandas metadata". Table and column names only.

### Output surfaces

| Surface | Change |
|---|---|
| reasons and error registries | `out_of_core_code_set_type_unproved` (reason), `source_pandas_conversion_failed` (error code) |
| `quality_metrics["execution"]["out_of_core_declined"]` | records the structured rejection code; `RouteDecision` (`execution/_pipeline_context.py:150`) carries the code, table and column from `resolve_execution_route` |
| forced-run error | `OUT_OF_CORE_INELIGIBLE` with code, table and column in the message |
| public API | `check_out_of_core_compatibility` (re-exported at `execution/__init__.py:120`, `:165`) gains `code_set_text`, default `None` (rejects code_set). External caller: `decoy-platform` `api/jobs/v2_out_of_core.py:313` (parked; falls back safely). `declared_casting.cast_schema` is new public API |
| capacity verdict | UNKNOWN instead of FIT in the unproved case |
| job estimate | one note: "code_set route depends on source column types" |
| `docs/execution-backends.md`, `docs/compatibility-contract.md`, CHANGELOG | the route rule, the remedy (declare the column as text), the new keyword, the new error code |

## 5. Acceptance tests

Fixtures use a valid 32-byte mask root (`bytes([17]) * 32`, accepted at `keyprovider.py:244`); expected codes are regenerated from the reference route, not copied from older plans.

| ID | Slice | Test | Fail-before or kill |
|---|---|---|---|
| AT-1 | S2b | Unit, proof builder: (a) int64 with and without nulls, not proved; (b) `string` with `double[pyarrow]` metadata, not proved; (c) null-typed column, not proved; (d) metadata that renames one label, table proves nothing; (e) metadata that swaps two text labels, table proves nothing; (f) `list<int64>`, not proved; (g) metadata-free `string` and `large_string`, proved; (h) `string` with object and `string` metadata, proved; (i) corrupt pandas metadata JSON, table proves nothing, no exception escapes; (j) `string_view`, binary and dictionary `string`, not proved; (k) a named stored index field, skipped, the other text columns proved. Run under default options and `future.infer_string=True`. Two calls with different schemas give different proofs | new function; M2, M3 |
| AT-2 | S2b | Every consumer: (a) a job with a caller `LazySource` table and a loader-backed table (text code column) reaches `bounded_admission` through `resident_fallback_tables` and routes out-of-core on auto, forced succeeds; (b) the same with an int64 code column declines with `out_of_core_code_set_type_unproved` in `out_of_core_declined`, for a plain job and a transform job; (c) `check_out_of_core_compatibility` with no `code_set_text` rejects code_set and admits a plan without it; (d) capacity on a descriptor config with code_set gives UNKNOWN where it gave FIT, INSUFFICIENT stays; (e) job estimate prices the same route and carries the note; (f) caller and loader both name a table, caller has metadata-free `string`, loader schema has `double[pyarrow]` metadata: the proof uses the caller schema and the forced run succeeds | (a), (f) refuse on main once the proof exists; (d) FIT on main; M4, M9 |
| AT-3 | S2b | Public parity in `tests/parity/test_ooc_code_set_arrow.py`, shipped ICD-10, namespace `cs`, an FK pair so out-of-core is a candidate: (a) witness 1 across two batches; (b) witness 2; (c) witness 3; (d) null-typed code column. For each: auto declines before streaming, output equals forced full frame, forced `run_pipeline` raises `OUT_OF_CORE_INELIGIBLE` naming the code, table and column. (e) metadata-free `string` and `large_string`, (f) `string` with object or `string` metadata, (g) a declared-cast table whose code column is a raw `string` with `double[pyarrow]` metadata declared string: auto runs out-of-core, output equals forced full frame. Default options and `future.infer_string=True` | (a), (b) differ on main; M1, M7 |
| AT-4 | S2b | Direct `run_fk_out_of_core` with a declared-cast run: a sibling column is declared, the code column is an undeclared raw int64, so it is not proved. Spies on `ScratchArena.fresh`, `stage_declared_sources` and the quarantine writer, temp dir under `tmp_path`, a job sink. It raises `out_of_core_code_set_type_unproved`; no spy is called; the temp dir is empty; the sink received nothing. Second case: a faker conditional node on a binary column declared string, showing the pre-staging check passes post-cast `source_types`. Third case: the physical out-of-core driver with raw binary `b'A'` in a code_set column and no `cast_run` refuses (it is not proved on the raw schema) | staging runs first on main; M5, M8, M10 |
| AT-5 | S2b | Sentry `tests/sentry/test_ooc_code_set_proof_callers.py`: walks `src/decoy_engine/` (import-resolved names and aliases) for every call of `out_of_core_admission` and `check_out_of_core_compatibility` and asserts `code_set_text` is passed by keyword. A seeded call without it in a scratch copy turns it red (shown once in the builder report) | seeded omission |
| AT-6 | S2a | Conversion boundary: a physical `string` column with `double[pyarrow]` metadata holding `"ZZ-VALUE-1"`. Through full frame, sequential and the chunked oracle (two chunks, the bad value in the second), the run raises `source_pandas_conversion_failed`; `str(exc)`, `repr(exc)`, `__cause__`, `__context__`, warnings, `quality_metrics` and captured logs carry no `ZZ-VALUE-1`. The same column with `"1"`, `"2"` converts as before (parity unchanged). An int64 column with `Int32` metadata and value `99876543210` gives the same coded error | value in `str(exc)` on main; M6 |
| AT-7 | S2b | Proof against the chunked gate on the same effective schema: for every AT-1 fixture, each proved column is accepted by `unsafe_code_set_source_columns` (`execution/_chunked_code_set.py:133`) | guard |
| AT-8 | S2b | Loader drift (X8): the loader's declared schema has a metadata-free `string` code column; the returned table carries `double[pyarrow]` metadata. Auto and forced both raise `out_of_core_code_set_type_unproved` before staging; the loader is called once per table; no quarantine record is written | M9 |
| AT-9 | S2b | Int64 code column on a large table: auto declines with `out_of_core_code_set_type_unproved`, takes the route routing names (pinned), message names table and column only (CS-S2-Q1 pinned) | M1 |
| AT-10 | S2b | Cast schema guard: for each declared type, `declared_casting.cast_schema(schema, ...)` equals the schema of `cast_batch` applied to the empty table | M7 |
| AT-11 | S2b | Message scan on every S2b refusal (AT-2 (b), AT-3 (a) to (d), AT-4, AT-8) with `ZZ-VALUE-1` lexemes | M6 |

Existing tests that change on purpose (S2b): `tests/parity/test_out_of_core_group_c_parity.py:85` (pass a proof in positive fixtures) and `:711` (a float code column now declines; assert the decline); routing tests that call the changed signature (`tests/unit/execution/test_pipeline_routing_masktable_kills.py:451`, `tests/unit/execution/run_stream/test_lazy_input.py:1204` and the other callers mypy finds) pass schemas; a separate no-proof refusal test is kept. Each is listed in the PR as an intentional change.

## 6. Named mutations

| ID | Slice | Mutation | Must turn red |
|---|---|---|---|
| M6 | S2a | re-raise the original pyarrow error (or chain it with `from exc`) | AT-6 |
| M1 | S2b | admit code_set on shape only | AT-3 (a), (b), AT-9 |
| M2 | S2b | prove on the pandas dtype only (drop the physical `string` check) | AT-1 (f), AT-3 (c) |
| M3 | S2b | cache the proof at module scope by table name | AT-1 (two calls) |
| M4 | S2b | treat `None` or a missing column as proved | AT-2 (c) |
| M5 | S2b | run the pre-staging check after `run_staged` | AT-4 first case |
| M7 | S2b | prove on the raw schema when a cast runs (skip `cast_schema`) | AT-3 (g), AT-10 |
| M8 | S2b | pass raw `source_types` to the faker check | AT-4 second case |
| M9 | S2b | merge schemas with loader precedence for a resident table | AT-2 (f) |
| M10 | S2b | apply the post-cast view when no cast runs | AT-4 third case |

Each mutation runs on the final head of its own slice; the gate records the head.

## 7. Defect classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | pyarrow conversion errors on every pandas route; the new rejection message | one translation at the shared converter, `from None`; messages from names only; the proof reads empty tables | AT-6, AT-11 | M6 |
| 2 | Cleanup missing on an exit path | refusal on a declared-cast run | the check runs before `ScratchArena.fresh`, staging and quarantine | AT-4 | M5 |
| 3 | State and concurrency | proof per run | pure function of plan and schemas, built per call | AT-1 (two calls) | M3 |
| 4 | Route parity and silent fallback | five routing callers, two estimators, transform admission, two runner entries | fail-closed default, one proof builder, AST sentry, structured rejection carried in `RouteDecision` | AT-2, AT-3, AT-5 | M1, M4 |
| 5 | Referential integrity | one code value on two routes | admit only physical text that pandas keeps as text with identity labels | AT-3 | M1, M2 |
| 6 | Untrusted producer | customer pandas metadata JSON | physical-type gate first; label identity; conversion error proves nothing | AT-1 (d), (e), (i) | M2 |
| 7 | Check then use (TOCTOU) | routing proof against the runner's sources | the runner proves on the resolved tables it masks, loader called once | AT-4, AT-8 | M5, M9 |
| 8 | Weak tests | parity passes today for text | fail-before witnesses at the public boundary | AT-3 (a), (b) | M1 |
| 9 | Refactor drift | `out_of_core_routing_signals` and `bounded_admission` signatures | required keyword, no default, mypy fails on a missed caller | T1 routing selection, mypy | N/A, structural: the build fails on a missed caller |
| 10 | Frozen contract drift | full-frame output, reason codes, public gate | full-frame output unchanged; new codes registered; new keyword safe by default | AT-3, AT-2 (c) | M1, M4 |

Recurring-defect catalog: no new grammar, persisted type or scanner. The swallowed exception in X5 is inside a pure builder that only shrinks the proof.

## 8. Design

### Design notes

- Choke points: the shared converter for conversion errors; `check_out_of_core_compatibility` for admission, with a fail-closed keyword. Guards: AT-6, AT-5.
- One owner per fact: `declared_casting` owns what a cast does to a schema (`cast_schema`); the proof builder owns "this column reads as the same text on both routes".
- No new class, no new registry.

### Placement

| Item | File | CODEMAP line | Sits beside |
|---|---|---|---|
| conversion translation | `internal/pandas_compat.py` (`table_to_pandas_exact_ints`) | internal helpers | the existing `on_unconvertible` path |
| `source_pandas_conversion_failed` | the engine error registry beside the existing source/config codes | errors | existing codes |
| `cast_schema` | `declared_casting/_boundary.py`, exported from `declared_casting/__init__.py` | declared casting | `cast_batch` |
| `pandas_text_columns`, `code_set_proof_columns`, `code_set_proof_rejection` | `execution/out_of_core/_preflight.py` (no new module: the package is at its fan-out freeze of 44), names re-exported from `execution/out_of_core/__init__.py` for engine callers | "Out-of-core FK" | `run_preflight` |
| unit tests | `tests/unit/execution/test_ooc_code_set_proof.py`, `tests/unit/internal/test_pandas_conversion_errors.py` | tests | existing unit tests |
| sentry | `tests/sentry/test_ooc_code_set_proof_callers.py` | sentries | `tests/sentry/test_module_size.py` |

Import direction: `_compat.py` imports `code_set_proof_rejection` inside `_group_c_conditional_rejection` (lazy) because `_preflight.py` imports `_compat`; the rejection takes plain data. The import-linter contract runs.

### S2a: value-free source conversion

1. In `table_to_pandas_exact_ints` (`internal/pandas_compat.py:131`), wrap `table.to_pandas()`. On the C2 exceptions, find the failing column by converting each column alone (only on failure), then raise `source_pandas_conversion_failed` `from None`, naming the column. Callers that know the table name pass it through a new keyword `table: str | None = None` from `to_pandas_fk_safe`. Never format the original exception.
2. The chunked oracle re-raise (`execution/_chunked_oracle.py:471`) and `carry.diagnose_adapter` pass the coded error through unchanged; confirm with AT-6 that no other path re-wraps the pyarrow text.
3. CHANGELOG and error-code docs.

### S2b: one proof, every consumer, check before staging

1. `_preflight.py` gains (about 90 lines) `pandas_text_columns(plan, schemas)` per Fields, `code_set_proof_columns(plan)` and `code_set_proof_rejection(node, proof)`.
2. `declared_casting/_boundary.py` gains `cast_schema(schema, run_or_decls) -> pa.Schema` (declared types replaced, schema and field metadata dropped, as `cast_batch` at `:263` does), exported; guarded by AT-10.
3. `check_out_of_core_compatibility` and `out_of_core_admission` (`execution/_pipeline_routing_signals.py:57`) gain `code_set_text: frozenset[tuple[str, str]] | None = None`. `_group_c_conditional_rejection(node)` (`_compat.py:406`) gains the parameter; its call site at `:334` passes it; after the shape check at `:417` it calls `code_set_proof_rejection`. `_compat.py` grows at most 6 lines.
4. Schemas for routing: `RoutingFacts` (`execution/pipeline/_routing_facts.py:39`) gains `proof_schemas: Mapping[str, pa.Schema]`, built once in `build_routing_facts` (resident caller schema first, loader schema only for missing tables, `cast_schema` applied where the plan declares a cast). Consumers:
   - `bounded_admission` (`execution/_pipeline_routing.py:178`, call at `:216`) gains a required `proof_schemas` keyword; `execution/pipeline/_lazy_input.py:144` passes `facts.proof_schemas`.
   - `out_of_core_routing_signals` gains a required `proof_schemas` keyword. Its run-path caller is threaded from `execution/_pipeline_context.py:514` (the `resolve_execution_route` call), not from a context at `_pipeline_routing_signals.py:550`. `PipelineRunContext` (`execution/_pipeline_context.py:84`) gains the field, assigned from `facts.proof_schemas`; the file stays at 600 or fewer by moving the `facts_of` closure (`:340-352`) into `pipeline/_routing_facts.py`.
   - `execution/physical/_snapshot.py:209`, `execution/physical/_live_inputs.py:128`, `execution/pipeline/_stream.py:216`: the schemas they hold, same precedence rule.
5. `resolve_execution_route` returns the structured rejection (code, table, column) and `RouteDecision` (`execution/_pipeline_context.py:150`) carries it into `out_of_core_declined` for plain and transform jobs (`execution/_transforms_admission.py:376` stops discarding it) and into the forced `ooc_ineligible` message (`execution/_pipeline_routing.py:395`).
6. Estimators: capacity (`execution/capacity.py:362`) and job estimate (`execution/_job_estimate.py:164`) pass `code_set_proof_columns(plan)` and mark the route uncertain when it is not empty; capacity downgrades FIT to UNKNOWN at `:527`; the job estimate adds the note.
7. Runner: `run_fk_out_of_core` (`execution/out_of_core/_runner.py:194`) calls a new `refuse_incompatible(plan, sources, cast_run)` in `_preflight.py` before `_declared.run_staged`. It proves on the resolved source tables it will mask (`cast_schema` only when `cast_run` is present), passes `source_types` from the same view to the faker check, and raises X8. The physical driver path (`execution/physical/drivers/_out_of_core.py:67`) goes through the same call with no `cast_run`.
8. Parity matrix AT-3, migrated tests, docs, CHANGELOG, compatibility-contract note.

## 9. Size budgets and pinned surfaces

| File | Lines now | Budget | Slice |
|---|---|---|---|
| `internal/pandas_compat.py` | 218 | at most 270 | S2a |
| `execution/out_of_core/_preflight.py` | 94 | at most 240 | S2b |
| `execution/out_of_core/_compat.py` | 585 | at most 600, hard cap, no module-size entry | S2b |
| `execution/out_of_core/_runner.py` | 393 | at most 400 | S2b |
| `execution/_pipeline_routing_signals.py` | 613 | existing ceiling 633, not raised | S2b |
| `execution/_pipeline_context.py` | 600 | at most 600, hard cap (offset in item 4) | S2b |
| `execution/_pipeline_route_exec.py` | 597 | at most 600, expected unchanged | S2b |
| `execution/_pipeline_routing.py` | 566 | at most 600 | S2b |
| `execution/pipeline/_routing_facts.py`, `execution/pipeline/_lazy_input.py` | 117, existing | at most 600 each | S2b |
| `execution/capacity.py`, `execution/_job_estimate.py`, `execution/_transforms_admission.py` | 555, 321, 390 | at most 600 each | S2b |
| `declared_casting/_boundary.py` | 524 | at most 560 | S2b |
| `tests/parity/test_ooc_code_set_arrow.py` | 238 | at most 600 | S2b |

Pinned surfaces: reason and error registries (one new code each); `tests/sentry/baselines/gcs-call-kwargs.json:165` (an intentional change if the keyword shows there); `tests/unit/execution/test_out_of_core_public_api.py` green; the `test_f06_declared_casting.py` ROUTE_OWNERS and appliers sets do not move (the pre-staging check reads schemas and applies no cast); `declared_casting/__init__.py` public names gain `cast_schema`; secret-material census (`run_preflight`'s `mask_key` line moves only if lines are added above it, and only that census line is updated); import layers (run the import-linter contract). Any other delta: stop and report.

## 10. Frozen contracts

- Full-frame code_set output is the reference and does not change.
- Reason codes: `out_of_core_code_set_shape_unsupported` keeps its meaning. New: `out_of_core_code_set_type_unproved`, `source_pandas_conversion_failed`.
- Public API: `check_out_of_core_compatibility` gains a keyword with a safe default; `declared_casting.cast_schema` is added. CHANGELOG and compatibility-contract note.
- A source that converted before converts the same way after S2a; only the error text and type of a failing conversion change.

## 11. Pre-mortem

- An int64 code column that ran out-of-core now goes to full frame or sequential; a table too big for full frame then fails on the memory budget. Published under `out_of_core_declined`; docs name the remedy. CS-S2-Q1.
- A builder trusts the routing proof in the runner. X8 and AT-8 cover a loader whose real table differs.
- A builder proves on the pandas dtype alone. Witness 3 then diverges. AT-1 (f), AT-3 (c), M2.
- A builder chains the pyarrow error (`raise ... from exc`). The value reaches `__cause__`. AT-6 checks the chain, M6.
- A pandas upgrade maps `string` to a new dtype. The proof declines text columns: safe, slower; AT-1 (g) fails and names the dtype.
- `future.infer_string=True` turns object into `StringDtype`; both count. AT-1 and AT-3 run under both.
- A builder raises a size pin instead of moving `facts_of`. The gate fails it (a pin raised by growth in the same change is HIGH).

## 12. Slices

| Slice | Content | Size | Risk | Starts after | Gate |
|---|---|---|---|---|---|
| S2a. Value-free source conversion | S2a items 1 to 3 | 0.5 builder-days | R2 | nothing (branch from main now) | AT-6; M6 |
| S2b. One proof, every consumer, check before staging | S2b items 1 to 8 | 2 builder-days | R2 | S2a and #808 merged | AT-1 to AT-5, AT-7 to AT-11; M1 to M5, M7 to M10; existing out-of-core parity green |

Test depth: T0 the touched files' tests per edit; T1 impact selection per commit and slice head, plus the routing, estimator and out-of-core parity packages; T2 gate on the exact head with that slice's mutations. Full suite: S2a changes a shared ingestion helper used by every pandas route (shared fixture class), so it runs one full suite against the saved main baseline at its gate head. S2b adds a sentry, changes a public API and migrates existing tests, so it also runs one full suite at its gate head.

## 13. Owner questions and deferred items

- CS-S2-Q1 (OWNER CALL). Integer code columns are not proved text, so they run full frame or sequential. Default: accept for V1, document the remedy (declare the column as text), keep admission of null-free integer columns as V2-LOG.
- CS-S2-Q2 (OWNER CALL). When the resolved loader table's schema gives a different proof than the declared loader schema (X8). Default: refuse with `out_of_core_code_set_type_unproved` on auto and forced, before staging. The alternative, rerunning route selection with out-of-core excluded before the post-scan gate and route event, is V2-LOG: Codex round 1 showed a naive fallback to sequential is wrong for vault and validator jobs and can write quarantine records first.
- CS-Q5 (existing). Default (a): the native code_set operator moves to 1.x; V1 keeps the memoized handler.
- Open item 1. Faker's `source_types` (`execution/_pipeline_routing_signals.py:268`) is built from caller sources only, and the static check fails open when a source type is absent (`execution/out_of_core/_compat.py:397`). A loader-only faker job is therefore admitted without its type check. Not changed here; flagged for the orchestrator as a possible separate row.
- Open item 2. The chunked code_set gate decides on the Arrow type only; whether it diverges from full frame on witness 2 was not run. AT-7 keeps the proof within it.
- V2-LOG: estimator footer reads; `string_view` admission; fallback on X8.
