Status: plan (revision 2, 2026-11-25, after Dennis round 1)

# CODE-SET-NATIVE S2a and S2b: out-of-core admits code_set only on columns pandas reads as text

Owner: Cam. Author: Opus (plan author). Roadmap row: CODE-SET-NATIVE (1.0 row). Engine only. This plan replaces the "S2: re-plan" entry in `docs/plans/2026-11-22-code-set-native.md` (rev 7, on branch `plan/code-set-native`, section 12). It reuses the rev 5 design of that plan (section 5.2) and closes the three Codex round 3 findings that rev 5 left open.

Source anchor: engine main `2b8a47fbe`. Paths without a prefix start at `src/decoy_engine/`. Builders re-anchor line numbers on their merge head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `feature-dev.md`, `cross-cutting-concerns.md`, `architecture.md` (layout, fan-out, size); engine `CODEMAP.md` ("Where things go").

Risk: R2 (route admission for a masking strategy; masked output on the out-of-core route). Plan review: Dennis, then Codex. Code gate: Codex, plus Dennis on S2a.

## 0. Dependency on PR #808 (S1)

S1 is PR #808 (`feat/code-set-native-s1`), head `68bcad3e8`, with Codex fixes in progress (mode check at the top of `apply_code_set`, URL credentials stripped from corpus diagnostics). S2a and S2b branch from main after #808 merges. They assume these facts from #808 and nothing else:

1. The full-frame handler `execution/_strategies/_code_set.py` masks with the bounded memo. A column that out-of-core declines goes to full frame or sequential and runs that handler, so a decline costs one corpus selection per distinct value, not one per row.
2. `_PER_VALUE_CODE_SET_ERRORS` is still defined in `execution/_strategies/_code_set.py`, and `execution/out_of_core/_mask_group_c.py:92` still imports it.
3. `apply_code_set` refuses a mode other than `mask` or `gen` with a value-free message, and corpus diagnostics pass through `fileaccess.shown`. S2 adds no message that carries a path or a value.
4. #808 does not touch any file under `execution/out_of_core/`, the routing files, the estimators or `declared_casting/`. If its final head does, the S2a builder re-anchors and reports the overlap before starting.

If #808 is still open when S2a is ready to build, S2a may branch from main without it: S2 does not call the memo. The only cost is that the AT-3 decline cases run the per-row handler and take longer.

## 1. Frame

The out-of-core route reads the physical Arrow value and masks `str(value)` (`kernel/_code_set.py`, `code_set_map`). Full frame, the reference, masks `str(value)` of the value pandas rebuilds from the same table after `to_pandas_fk_safe` (`execution/_fk_keys.py:430`) has applied schema metadata and the null-to-float widening. When the two strings differ, the two routes pick different corpus codes for the same input:

- Witness 1: int64 `[1, null, 2]`, shipped ICD-10, namespace `cs`, key `bytes([17]) * 8`. Out-of-core gives `[R10.9, None, M17.11]` (from `"1"`, `"2"`); full frame gives `[L89.90, None, I10]` (from `"1.0"`, `"2.0"`).
- Witness 2 (Codex): a `string` column `["1", null]` whose pandas metadata says `double[pyarrow]`. pandas rebuilds `1.0`, so full frame masks `"1.0"` and out-of-core masks `"1"`.

The mask is still keyed and the value is still replaced, so nothing leaks. The defect is that the same job gives different output on two routes, and a run that changes route (a bigger file, a new budget) changes its codes. That breaks referential integrity across runs, so it is in the V1 bar.

The fix: out-of-core admits a mask-mode code_set column only when converting that column's schema to pandas gives a text dtype. For a text dtype, `str(value)` of the pandas value is the Arrow string itself, so the two routes agree. Every other column goes to full frame (or sequential), where the memoized handler masks it.

Codex round 3 named three gaps in the rev 5 version of this fix. This plan closes each:

| Codex r3 finding | Where it is closed |
|---|---|
| 1. Routing builds its type facts from caller sources only (`execution/_pipeline_routing_signals.py:268`), so a `source_loader` job gets an empty proof and a forced run refuses text it should admit | S2a: one proof built from caller and loader schemas; the runner builds it from the sources it actually holds |
| 2. Capacity (`execution/capacity.py:362`), job estimate (`execution/_job_estimate.py:164`) and transform admission (`execution/_transforms_admission.py:382`) call `out_of_core_admission` without a proof | S2a: the proof is a keyword every caller passes on purpose; a missing proof rejects code_set (fail closed); each estimator states its choice; an AST sentry fails on a caller that omits it |
| 3. Declared casting changes the schema before pandas sees it (`execution/_pipeline_full_frame.py:164`, `declared_casting/_boundary.py:263`), and the out-of-core runner stages before its preflight (`execution/out_of_core/_runner.py:194`) | S2a proves on the post-cast schema; S2b moves the check in front of staging |

## 2. Established solutions

Search run: the engine's own admission gates (`rg "source_types|out_of_core_admission"`), the pandas `Table.to_pandas` type-mapping docs (pandas metadata wins over the Arrow type; `types_mapper` and `future.infer_string` change object to `StringDtype`), and the rev 5 design. Findings:

- Type-directed admission: decide from the schema, never from values, so the decision is cheap, stable across chunks and value-free. The faker B4 gate (`execution/out_of_core/_compat.py:368`) already does this for faker.
- Fail closed on missing facts: an admission check that lacks its input rejects, as `reject_null_bearing_int_ooc` streams a column instead of assuming no nulls (`execution/out_of_core/_null_int_guard.py`).
- Ask the converter, not a copy of its rules: pandas reconstruction from metadata has many cases (extension dtypes, `double[pyarrow]`, index labels). Converting an empty table with the same function full frame uses gets every case right with no copied rule table, and a pandas or pyarrow upgrade moves the proof with it.

The only custom code is the dtype test (three dtype kinds) and the post-cast schema view, which copies one known behaviour of `cast_batch`.

### Reuse inventory

- `to_pandas_fk_safe` (`execution/_fk_keys.py:430`): the converter full frame uses (`execution/_pandas_adapter.py:205`).
- `check_out_of_core_compatibility` and `_group_c_conditional_rejection` (`execution/out_of_core/_compat.py:174`, `:405`): the existing gate and the existing code `out_of_core_code_set_shape_unsupported` (shape failures). An unproved type gets its own code, `out_of_core_code_set_type_unproved`, added to the reasons registry, so telemetry separates the two causes.
- `contract_model` and `arrow_type` (`declared_casting/_boundary.py:76`): the post-cast Arrow type of a declared column. `declared_integer_columns` (`declared_casting/_boundary.py:151`) is the pattern for reading the plan's declared columns.
- `build_source_facts` / `source_facts_of` (`contracts/column_shape.py:85`, `:104`): the one builder that merges caller and loader schemas.
- The `ooc_route_uncertain` downgrade in `execution/capacity.py:527`: turns a FIT that rests on an assumption into UNKNOWN.
- `run_preflight` (`execution/out_of_core/_preflight.py:44`): the runner's pure, pre-write check.
- `arrow_columns` and `stored_index_fields` (`_pandas_meta/_columns.py:26`, `:32`): the one home for "which fields are stored index columns". The proof uses them to drop index fields per column instead of rejecting the table. The proof itself cannot live in `_pandas_meta`: that package imports only `pyarrow` by contract, and the proof needs pandas.
- Existing mechanisms that decide a related question, and how the proof relates to each:
  - `execution/_chunked_code_set.py:88` (`_SAFE_CODE_SET_SOURCE_CHECKS`, `unsafe_code_set_source_columns`, `reject_unsafe_code_set_chunk_schema`): the chunked route's code_set gate, on the Arrow type only. S2a does not change it. A guard test (AT-7) asserts that every column the proof admits, the chunked gate also admits, so the two cannot drift in the unsafe direction. Whether the chunked gate itself diverges on witness 2 is open item 2.
  - `execution/native/_faker_deterministic_admission.py:214` (`metadata_shape_admits`): a closed allow-list proof that pandas conversion is identity for faker. Different question (identity of every value, not text dtype); not reused, named so a reviewer sees both.
  - `_arrow_types.py:21` (`is_text`) and `execution/pipeline/_source_types.py`: Arrow-type and source-type readers. The proof does not restate them; it asks pandas.

## 3. Guarantee and non-goals

After S2a and S2b:

1. For every mask-mode code_set column without `chapter_preserve`, the out-of-core route runs only if `pandas_text_columns` proved that column. The proof is built from the schema full frame converts: the post-cast schema for a declared table, the source schema otherwise, for caller and loader tables alike.
2. Every caller of `check_out_of_core_compatibility` and `out_of_core_admission` passes the proof or states that it has none. No proof means code_set is rejected. The estimators never report FIT on an out-of-core route that rests on an unproved code_set column.
3. The proof refuses before anything is written. Through `run_pipeline` with `execution_mode="out_of_core"`, routing refuses first: `decide_execution_route` (`execution/_pipeline_routing.py:382-400`) raises `ooc_ineligible` (`execution/_errors.py:117`, `OUT_OF_CORE_INELIGIBLE`) with `out_of_core_code_set_type_unproved` in the message. A direct `run_fk_out_of_core` call raises `out_of_core_code_set_type_unproved` itself, before it opens a scratch arena, stages a declared copy, or writes to a sink (S2b).
4. When out-of-core runs, its code_set output equals forced full frame, byte for byte, under default pandas options and `future.infer_string=True`.
5. No message or log line names a value. Messages name table and column only.

Non-goals (V2-LOG or later rows): admitting integer code columns out-of-core (CS-S2-Q1); a native code_set operator on the unified slice or the chunked step (CS-Q5); closing the same loader-schema gap for faker's `source_types` (open item 1); reading Parquet footers in the estimators to prove text there; any change to gen mode or `chapter_preserve` admission.

## 4. Enumerations

### Exit paths (the admission decision for one code_set node)

| # | Condition | Result |
|---|---|---|
| X1 | mode is not `mask`, or `chapter_preserve` is set (`execution/out_of_core/_compat.py:417`) | rejected as today, same code and message |
| X2 | proof is `None` (caller has no schemas) | rejected, `out_of_core_code_set_type_unproved`, message names table and column and says the source type is not proved text |
| X3 | some target column is not in the proof | rejected, same code and message as X2 |
| X4 | every target column is in the proof | admitted (as today) |
| X5 | the proof builder fails for a table (pandas conversion raises) | that table contributes no columns, so X3 applies; the exception stays inside the builder and never reaches a message or log |
| X5b | a column's frame label is missing or renamed by metadata, or it is a stored index field | that column is not proved; other columns of the table are unaffected |
| X6 | routing proved on declared loader schemas, but the loader returns a table whose type or metadata differs (`profile/_declared_columns.py:484` `checked_loader` checks names only) | the runner re-proves and refuses. On an auto route this refusal is caught at the out-of-core dispatch in `execution/_pipeline_route_exec.py` (before `run_fk_out_of_core` at `:405` writes anything) and the job reruns on the route routing would have picked without out-of-core (sequential), recording `out_of_core_declined = out_of_core_code_set_type_unproved`. A forced run raises. OWNER CALL CS-S2-Q2, default: fall back on auto |

### Routes

| Route | Before | After |
|---|---|---|
| auto, routing signals (`execution/_pipeline_routing.py:216` and four other callers) | code_set admitted on shape | admitted only with proof from caller plus loader schemas, post-cast |
| forced `execution_mode="out_of_core"` through `run_pipeline` | admitted on shape | routing refuses with `OUT_OF_CORE_INELIGIBLE`, reject code in the message; if routing admitted and the loaded table differs, the runner refuses (X6, raises on a forced run) |
| public `run_fk_out_of_core` with a declared-cast run | stages, then checks | checks, then stages (S2b) |
| full frame, sequential, chunked oracle | memoized handler (#808) | unchanged; they receive the declined columns |
| capacity estimate | priced as admitted | priced as admitted, FIT downgraded to UNKNOWN when an unproved code_set column is present |
| job estimate | priced as admitted | priced as admitted, with a note that the route depends on source column types (same rule as capacity: unproved means uncertain, not declined) |

### FK shapes

- code_set on a non-key column of an FK-bearing table: the common case. A decline moves the whole job off out-of-core, as any other rejection does today.
- code_set on a key column: the gate is per node, so the same proof applies. `to_pandas_fk_safe` maps only integer key columns, and an integer column is never proved text, so the FK mapper never changes a proof.
- A job without relationships never reaches the out-of-core route (`execution/_pipeline_routing_signals.py:265`); nothing changes for it.

### Fields

- Proof type: `frozenset[tuple[str, str]]` of (table, column), or `None`.
- Text dtypes: numpy `object`, `pd.StringDtype` (any storage), and `pd.ArrowDtype` whose `pyarrow_dtype` is `string` or `large_string`. A `string_view` source is not proved (staying narrow costs only a route); the builder records its dtype in AT-1.
- Post-cast view: for a table the plan's declared-casting block names, each declared column's type becomes `arrow_type(contract)` and the schema and field metadata are dropped, matching `cast_batch`, which rebuilds the table with `pa.table({...})` (`declared_casting/_boundary.py:263`). Undeclared tables keep their schema and metadata. The view is idempotent: a staged copy's schema gives the same view as its raw source.

### Output surfaces

| Surface | Change |
|---|---|
| route decision, `quality_metrics["execution"]["out_of_core_declined"]` | a declined job records `out_of_core_code_set_type_unproved` |
| reasons registry | one new code, `out_of_core_code_set_type_unproved` |
| public API | `check_out_of_core_compatibility` (re-exported at `execution/__init__.py:120`, `:165`) gains the keyword `code_set_text`, default `None`, so a caller without it now gets code_set rejected. Known external caller: `decoy-platform` `api/jobs/v2_out_of_core.py:313` (platform is parked; its code_set jobs fall back to sequential, which is safe). CHANGELOG entry and a `docs/compatibility-contract.md` note |
| forced-run error | `OUT_OF_CORE_INELIGIBLE` through `run_pipeline`, `out_of_core_code_set_type_unproved` from a direct runner call; message names table and column |
| capacity verdict | UNKNOWN instead of FIT in the unproved case |
| job estimate | same route as before plus one note: "code_set route depends on source column types" |
| `docs/execution-backends.md`, CHANGELOG fragment | one paragraph: integer and metadata-typed code columns go full frame; declare the column as text to keep out-of-core |

## 5. Acceptance tests

| ID | Slice | Test | Fail-before or kill |
|---|---|---|---|
| AT-1 | S2a | Unit, `pandas_text_columns`: (a) int64 with and without nulls, not proved; (b) `string` with `double[pyarrow]` metadata, not proved; (c) null-typed column, not proved; (d) metadata that renames the column label, table proves nothing; (e) metadata-free `string` and `large_string`, proved; (f) `string` with object and `string` metadata, proved; (g) corrupt pandas metadata JSON, table proves nothing, no exception escapes; (h) a declared table whose raw column is `string` with `double[pyarrow]` pandas metadata, declared string, is proved (the cast drops the metadata), and a raw `binary` column declared string is proved, while a raw `string` column declared integer is not (an int64 raw column declared string is not buildable: `declared_casting/_boundary.py:473` refuses it); (i) a declared table's undeclared `string` column with `double[pyarrow]` metadata is proved (metadata dropped by the cast); (j) `string_view` recorded, not proved; (k) a dictionary `string` column, not proved (converts to `category`); (l) a schema with a named stored index field: the index is skipped and the other text columns are proved. Run (a) to (i) under default options and `future.infer_string=True`. Two calls with different schemas return different proofs | new function; M2, M3, M7 |
| AT-2 | S2a | Every consumer: (a) a `source_loader` job (`sources={}`, loader schemas with a text code column) routes out-of-core on auto, and the forced run succeeds; (b) the same job with an int64 code column declines on auto with `out_of_core_declined = out_of_core_code_set_type_unproved`; (c) `check_out_of_core_compatibility` with no `code_set_text` rejects a code_set plan and still admits a plan without code_set; (d) capacity on a descriptor config with a code_set column gives UNKNOWN where it gave FIT before, and still gives INSUFFICIENT for a too-small budget; (e) job estimate on the same config prices the same route as before and carries the note; (f) `out_of_core_declined` (transform admission) declines with the same proof the router used | (a) forced run refuses on main once the proof exists without loader schemas; (d) FIT on main; M4 |
| AT-3 | S2b | Public parity in `tests/parity/test_ooc_code_set_arrow.py`, shipped ICD-10, namespace `cs`, key `bytes([17]) * 8`, an FK pair so out-of-core is a candidate. Cases (a) witness 1, int64 `[1]`, `[null, 2]` across two batches; (b) witness 2; (c) null-typed code column; (d) label-renaming metadata. For (a) to (d): the auto run declines before streaming with `out_of_core_code_set_type_unproved` (or the shape code for (c) if the shape check fires first, recorded), output equals forced full frame, and a forced `run_pipeline` raises `OUT_OF_CORE_INELIGIBLE` with the reject code in the message. Cases (e) metadata-free `string` and `large_string`, (f) `string` with object or `string` metadata, (g) a declared-cast table whose code column is a raw `string` with `double[pyarrow]` metadata declared string: auto runs out-of-core and output equals forced full frame. Run under default options and `future.infer_string=True` | (a), (b) give different codes on main; M1 |
| AT-4 | S2b | Direct `run_fk_out_of_core` call (routing skipped), declared-cast run whose code column is a raw `string` with `double[pyarrow]` metadata declared as a numeric type, so it is not proved: spy on `ScratchArena.fresh` and `stage_declared_sources`, temp dir under `tmp_path`, and a job sink. It raises `out_of_core_code_set_type_unproved`, neither spy is called, the temp dir is empty and the sink received nothing. A second case: a binary column declared string under a faker conditional node, showing `refuse_incompatible` passes post-cast `source_types`. A third case through `run_pipeline` forced asserts `OUT_OF_CORE_INELIGIBLE` with the reject code in the message | staging runs first on main; M5, M8 |
| AT-5 | S2a | Choke-point sentry `tests/sentry/test_ooc_code_set_proof_callers.py`: walks the syntax tree of `src/decoy_engine/` (import-resolved names, aliases included) for every call of `out_of_core_admission` and `check_out_of_core_compatibility`, and asserts each passes `code_set_text` by keyword. A seeded call without it in a scratch copy turns the sentry red (shown once in the builder report) | M4 |
| AT-7 | S2a | Proof against the chunked gate: for every AT-1 fixture, each column `pandas_text_columns` proves is also accepted by `unsafe_code_set_source_columns` (`execution/_chunked_code_set.py:133`) | guard; M2 shows the direction |
| AT-8 | S2a | Loader drift (X6) and the lazy-input path: (a) a loader-only code_set job reaches `resident_fallback_tables` (`execution/pipeline/_lazy_input.py:144`) and `bounded_admission` sees the proof from `facts.source_schemas`; (b) a loader whose declared schema has a metadata-free `string` code column but whose returned table carries `double[pyarrow]` metadata: auto routing admits, the runner refuses, the job falls back to sequential with output equal to forced full frame and `out_of_core_declined = out_of_core_code_set_type_unproved`; forced raises | M9 |
| AT-9 | S2a | Int64 code column on a large table: the auto run declines out-of-core with `out_of_core_code_set_type_unproved`, takes the route routing names (pinned), and the message names table and column only (CS-S2-Q1 behaviour pinned) | M1 |
| AT-6 | S2a, S2b | Message scan: run AT-2 (b) and AT-3 (a), (b) with distinctive values (`"ZZ-VALUE-1"` style lexemes) and assert no value appears in the error, warnings, `quality_metrics` or captured logs | M6 |

Existing out-of-core code_set tests (`tests/parity/test_ooc_code_set_arrow.py`, `tests/parity/test_out_of_core_group_c_parity.py`) stay green: their fixtures are text columns.

## 6. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | admit code_set on shape only (skip the proof) | AT-3 (a), (b) |
| M2 | prove from the Arrow type only (`pa.types.is_string(field.type)`), ignoring pandas | AT-1 (b), AT-3 (b) |
| M3 | cache the proof at module scope by table name | AT-1 (two calls) |
| M4 | treat `None` or a missing column as proved | AT-2 (c) |
| M5 | move the S2b check back after `run_staged` | AT-4 direct-runner case |
| M8 | `refuse_incompatible` passes raw `source_types` instead of the post-cast view | AT-4 second case |
| M9 | on auto, let the runner refusal propagate instead of falling back | AT-8 (b) |
| M6 | put the column's first value in the rejection message | AT-6 |
| M7 | skip the post-cast view (prove on raw schemas) | AT-1 (h), (i), AT-3 (g) |

Mutations run on the final head of each slice; the gate records the head.

## 7. Defect classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new rejection message | message built from table and column names only; the proof reads an empty table, so no value exists to leak | AT-6 | M6 |
| 2 | Cleanup missing on an exit path | forced refusal on a declared-cast run | the check runs before `ScratchArena.fresh`, so there is nothing to clean | AT-4 (no temp root, no scratch, no sink) | M5 |
| 3 | State and concurrency | proof computed per run | a pure function of plan and schemas, built per call, never cached at module scope | AT-1 (two calls, different proofs) | M3 |
| 4 | Route parity and silent fallback | five routing callers, three estimators, the runner | required `source_schemas` keyword, fail-closed `None` default, one proof builder, AST sentry | AT-2, AT-3, AT-5 | M1, M4 |
| 5 | Referential integrity | the same code value masked on two routes | admit only when pandas text equals Arrow text | AT-3 | M1, M2 |
| 6 | Untrusted producer | customer schema metadata (pandas JSON) | the converter decides; a conversion error or a renamed label proves nothing | AT-1 (d), (g) | M2 |
| 7 | Check then use (TOCTOU) | routing proof against the runner's sources | the runner re-proves on the sources it masks; a routing proof is never passed into the runner | AT-4 (direct runner call, routing skipped) | M5 |
| 8 | Weak tests | parity passes today for text columns | fail-before witnesses 1 and 2 at the public boundary | AT-3 (a), (b) red on main | M1 |
| 9 | Refactor drift | `out_of_core_routing_signals` signature change | required keyword with no default, so mypy fails on a missed caller; existing routing tests green unchanged | T1 routing selection, mypy | N/A, structural: the build fails on a missed caller |
| 10 | Frozen contract drift | full-frame output (the reference) and reason codes | no change to either; out-of-core output moves to match full frame | AT-3 | M1 |

Recurring-defect catalog: no new grammar, persisted type or scanner. The swallowed exception in X5 is inside a pure builder that only shrinks the proof; it is never logged and its cause never reaches a message.

## 8. Design

### Design notes

- Choke point: `check_out_of_core_compatibility` is the one gate every out-of-core admission passes. The proof enters it as a keyword with a fail-closed default, so a forgetting caller rejects code_set instead of admitting it. Guard: AT-5. Mutation: M4.
- One place per fact: the proof builder is the only code that decides "pandas reads this column as text". The routing, transform-admission and runner paths call it; nobody restates the dtype list.
- No new structure beyond one function group; no new class, no new registry.

### Placement

| Item | File | CODEMAP line | Sits beside |
|---|---|---|---|
| `pandas_text_columns`, `pandas_view_schema`, `code_set_proof_columns` | `execution/out_of_core/_preflight.py` (no new module: the package is at its fan-out freeze of 44) | "Out-of-core FK", private by stage | `run_preflight` |
| `code_set_proof_rejection` | `execution/out_of_core/_preflight.py` | "Out-of-core FK" | `pandas_text_columns` |
| `declared_arrow_types` | `declared_casting/_boundary.py` | declared casting | `declared_integer_columns` |
| unit tests | `tests/unit/execution/test_ooc_code_set_proof.py` | out-of-core tests | `test_ooc_cross_row_decline_message.py` |
| sentry | `tests/sentry/test_ooc_code_set_proof_callers.py` | sentries | `tests/sentry/test_module_size.py` |

`_compat.py` imports `code_set_proof_rejection` from `_preflight.py`. `_preflight.py` already imports `_compat` for `run_preflight`, so the builder imports inside `_group_c_conditional_rejection` or moves the import direction (the rejection takes plain data and imports nothing from `_compat`); the import-linter contract is run either way. Routing, the estimators and transform admission reach the proof through a name re-exported from `execution/out_of_core/__init__.py` (`pandas_text_columns`, `code_set_proof_columns`), not through the private module.

### S2a: one proof, every consumer

1. `_preflight.py` gains (about 80 lines):
   - `pandas_view_schema(table, schema, declared)`: the post-cast view in section 4 (Fields). `declared` is `declared_arrow_types(plan)`.
   - `pandas_text_columns(plan, schemas) -> frozenset[tuple[str, str]]`: for each table, convert `pandas_view_schema(...).empty_table()` with `to_pandas_fk_safe(empty, ())` inside `try`/`except Exception`. On an exception the table proves nothing. Otherwise, for each name in `arrow_columns(view)` (stored index fields dropped), add the column when the frame has that label and its dtype is a text dtype. A column whose label is missing or renamed by metadata is not proved; the rest of the table still is. Values are never read: the table is empty.
   - `code_set_proof_columns(plan) -> frozenset[tuple[str, str]]`: the mask-mode code_set columns that need proof (used by the capacity estimate).
2. `declared_casting/_boundary.py` gains `declared_arrow_types(plan) -> dict[str, dict[str, pa.DataType]]` beside `declared_integer_columns` (about 12 lines).
3. `check_out_of_core_compatibility` and `out_of_core_admission` (`execution/_pipeline_routing_signals.py:57`) gain the keyword `code_set_text: frozenset[tuple[str, str]] | None = None`. `_group_c_conditional_rejection(node)` (`_compat.py:406`) gains a `code_set_text` parameter and its call site at `:334` passes it; after the shape check at `:417` it makes one short call to `code_set_proof_rejection(node, code_set_text)`, which lives in `_preflight.py` beside the proof (pure, no import of `_compat`). Default `None` rejects code_set only. `_compat.py` grows by at most 6 lines.
4. `out_of_core_routing_signals` gains a required keyword `source_schemas: Mapping[str, pa.Schema]` (no default) and passes `code_set_text=pandas_text_columns(plan, source_schemas)`. The five callers pass caller plus loader schemas, built with `source_facts_of(caller_sources, loader_schemas).schemas`:
   - One source for the run paths: `RoutingFacts` (`execution/pipeline/_routing_facts.py:39`) gains `source_schemas: Mapping[str, pa.Schema]`, set once in `build_routing_facts` from the same `source_facts_of(caller_sources, source_loader_schemas)` it already computes at `:106`.
   - `execution/_pipeline_routing.py:216` (`bounded_admission`, called only from `execution/pipeline/_lazy_input.py:144` `_relationship_job_is_bounded`, which holds `facts: RoutingFacts` and never builds a context): gains a `source_schemas` keyword; `_lazy_input.py` passes `facts.source_schemas`.
   - `execution/_pipeline_routing_signals.py:550`: reads `ctx.source_schemas`. `PipelineRunContext` (`execution/_pipeline_context.py:84`) gains that field, assigned from `facts.source_schemas` where the context is returned (about `:413`). The file stays at 600 or fewer: the two added lines are offset by moving the `facts_of` closure (`:340-352`) into `pipeline/_routing_facts.py` as a small builder bound to the run's arguments.
   - `execution/physical/_snapshot.py:209`: it already holds `source_loader_schemas` (`:73`) and builds facts at `:174`.
   - `execution/physical/_live_inputs.py:128` and `execution/pipeline/_stream.py:216`: the schemas their context holds; a caller with no loader passes caller schemas only.
   `source_types` for faker stays as it is (open item 1).
5. `out_of_core_declined` (`execution/_transforms_admission.py:369`) gains `code_set_text`, and the call at `execution/_pipeline_context.py:554` passes `pandas_text_columns(ctx.plan, ctx.source_schemas)` on the existing argument lines (no net growth).
6. Estimators, which compile with `NO_SOURCES` and hold no schemas:
   - Capacity (`execution/capacity.py:362`): pass `code_set_proof_columns(plan)` as the proof so pricing proceeds as if admitted, and set `ooc_route_uncertain = True` when that set is not empty. The existing downgrade at `:527` turns FIT into UNKNOWN and keeps INSUFFICIENT.
   - Job estimate (`execution/_job_estimate.py:164`): same rule as capacity. Pass `code_set_proof_columns(plan)` so it prices the admitted path, and add the note when that set is not empty. One rule for both estimators: no schemas means uncertain, never declined. The CLI already shows UNKNOWN as "not checked" (`decoy` `cli/preflight.py:500`).
7. Runner preflight: `run_preflight` builds the proof from the schemas of `sources` (resolved loader tables and, on a staged run, the typed copies) and passes it to the compat check.

### S2b: refuse before staging, prove it end to end

8. `run_fk_out_of_core` (`execution/out_of_core/_runner.py:194`): before `_declared.run_staged`, call a new `refuse_incompatible(plan, sources, ...)` in `_preflight.py` that runs only the compat check, with the proof from the raw sources' post-cast view. It also passes `source_types` built from the same post-cast view, so the faker conditional check (`_compat.py:367`, which fails open on `None`) sees the types the run will see. It reads schemas only and writes nothing. `run_preflight` keeps its full check for the unstaged path and for direct callers.
9. Add the public parity matrix (AT-3) in `tests/parity/test_ooc_code_set_arrow.py` (238 lines now), and the docs and CHANGELOG lines.

## 9. Size budgets and pinned surfaces

| File | Lines now | Budget | Slice |
|---|---|---|---|
| `execution/out_of_core/_preflight.py` | 94 | at most 220 | S2a, S2b |
| `execution/out_of_core/_compat.py` | 585 | at most 600, hard cap, no module-size entry | S2a |
| `execution/out_of_core/_runner.py` | 393 | at most 400 | S2b |
| `execution/_pipeline_routing_signals.py` | 613 | existing ceiling 633, not raised | S2a |
| `execution/_pipeline_context.py` | 600 | at most 600, hard cap, no module-size entry (offset in step 4) | S2a |
| `execution/pipeline/_routing_facts.py`, `execution/pipeline/_lazy_input.py` | 117, existing | at most 600 each | S2a |
| `execution/_pipeline_routing.py` | 566 | at most 600 | S2a |
| `execution/capacity.py`, `execution/_job_estimate.py`, `execution/_transforms_admission.py` | 555, 321, 390 | at most 600 each | S2a |
| `declared_casting/_boundary.py` | 524 | at most 540 | S2a |
| `tests/parity/test_ooc_code_set_arrow.py` | 238 | at most 600 | S2b |

Public names added: `pandas_text_columns` and `code_set_proof_columns` re-exported from the `execution.out_of_core` package for engine callers (not added to `execution/__init__.py`). Pinned surfaces: reason registry (one new code, `out_of_core_code_set_type_unproved`); `tests/sentry/baselines/gcs-call-kwargs.json:165` (if the new keyword changes that baseline, the change is listed in the PR as intentional); `tests/unit/execution/test_out_of_core_public_api.py` stays green; the `test_f06_declared_casting.py` ROUTE_OWNERS and appliers sets do not move for the S2b pre-staging call (it reads schemas, it applies no cast); secret-material census (`run_preflight`'s `mask_key` line number moves if lines are added above it, and only that census line is updated); module size (no new entries); import layers (`_preflight.py` imports `execution._fk_keys` and `declared_casting._boundary`; run the import-linter contract). Any other delta: stop and report.

## 10. Frozen contracts

- Full-frame code_set output is the reference and does not change.
- Reason codes: `out_of_core_code_set_shape_unsupported` keeps its meaning and message. One new code, `out_of_core_code_set_type_unproved`, for X2, X3 and X6.
- Public API: `check_out_of_core_compatibility` gains a keyword whose default is safe (reject code_set); CHANGELOG and compatibility-contract note.
- Out-of-core output changes only for columns that were wrong before (now declined); for proved columns it is unchanged.
- The `out_of_core_routing_signals` signature is internal (no public export); its change is checked by mypy.

## 11. Pre-mortem

- An int64 code column that ran out-of-core before now goes full frame. A table too big for full frame then fails on the memory budget. The decline is published under `out_of_core_declined`, and the docs name the remedy: declare the column as text. CS-S2-Q1 asks whether that is acceptable for V1.
- A builder computes the proof at routing time and passes it into the runner. A loader can return a table whose schema differs from what routing saw; the runner must prove on what it holds (class 7).
- A builder proves on the Arrow type because it is simpler. Witness 2 then still diverges. AT-3 (b) and M2 catch it.
- A pandas upgrade maps `string` to a new dtype. The proof then declines text columns and out-of-core stops being chosen for code_set jobs. Safe but slower; AT-1 (e) fails loudly and names the new dtype.
- `future.infer_string=True` turns object into `StringDtype`; both count as text. AT-1 and AT-3 run under both options.
- `_pipeline_context.py` is at the GOAL line. The `facts_of` move in step 4 pays for the new field; a builder who instead raises the pin fails the gate (owner rule: a pin raised by growth in the same change is HIGH).
- A builder proves on the declared loader schema and trusts it at run time. X6 and AT-8 cover a loader whose real table differs.
- Dictionary-encoded string columns convert to `category` and decline. Cost: route only. Recorded in AT-1.

## 12. Slices

| Slice | Content | Size | Risk | Starts after | Gate |
|---|---|---|---|---|---|
| S2a. One proof, every consumer | items 1 to 7 | 1.5 builder-days | R2 | #808 merged (or main, see section 0) | AT-1, AT-2, AT-5 to AT-9; M1 to M4, M6, M7, M9 |
| S2b. Refuse before staging, public parity | items 8 and 9, docs and CHANGELOG | 0.5 builder-days | R2 | S2a merged | AT-3, AT-4, AT-6; M5, M8; existing out-of-core parity green |

S2a is now 1.5 builder-days (lazy-input path, X6 fallback, new reason code). Test depth: T0 the touched files' tests per edit; T1 impact selection per commit and on each slice head, plus the routing, estimator and out-of-core parity packages; T2 gate on the exact head with the mutations above. Full suite: S2a adds a sentry, a reason code and a public keyword and may change the module-size allowlist and the secret census line, which are test configuration, so S2a runs one full suite against the saved main baseline at its gate head. S2b hits no escalation trigger (T1 plus T2 only).

## 13. Owner questions and deferred items

- CS-S2-Q1 (OWNER CALL). Integer code columns (for example CPT codes stored as `int64`) are not proved text, so they run full frame. Default: accept for V1, document the remedy (declare the column as text), and keep admission of null-free integer columns as V2-LOG. The null-free case is safe in principle (pandas `int64` prints like Arrow), but it needs the runtime null scan of `_null_int_guard.py` at routing time.
- CS-Q5 (existing, unanswered). Default (a): the native code_set operator moves to 1.x and V1 keeps the memoized handler, named on the run card. This plan follows that default.
- CS-S2-Q2 (OWNER CALL). Runner refusal after routing admitted (X6, loader drift). Default: fall back to sequential on auto, raise on forced. The alternative is to make `checked_loader` check types and metadata and fail the job with a clear code.
- Open item 2. The chunked code_set gate decides on the Arrow type only; whether it diverges from full frame on witness 2 (metadata-typed string) was not run. S2a adds AT-7 so the proof never admits more than chunked; a chunked fix, if needed, is a separate row.
- Open item 1. Faker's `source_types` (`execution/_pipeline_routing_signals.py:268`) has the same caller-only gap. A loader-backed faker job is rejected (safe, slower). Not changed here; a follow-up can pass the same `source_schemas` once S2a lands.
- V2-LOG: estimator footer reads to prove text without a run; `string_view` admission.
