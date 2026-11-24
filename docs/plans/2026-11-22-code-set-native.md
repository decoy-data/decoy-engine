Status: plan (revision 5, 2026-11-24; scope cut after Codex round 2, Opus rework)

# CODE-SET-NATIVE: code_set masks once per distinct value on the handler routes, and out-of-core admits only text it reproduces

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22, reworked 2026-11-24. Roadmap row: CODE-SET-NATIVE, from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 76). The row is a 1.0 row in the CLI roadmap `docs/roadmap/groups/mask.md`. Engine only.

Source anchor: engine main `9f7bb1f4a`. Every file this plan touches is unchanged between that commit and the plan branch. Paths without a prefix start at `src/decoy_engine/`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `security.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (masking output on every handler route; route admission). Plan review history: Dennis r1 GO-WITH-FIXES, Codex r1 NO-GO, codex-fix to rev 4, Codex r2 NO-GO, Opus rework to rev 5. Code gate per slice: Codex and Dennis.

## Changes in revision 5

Revisions 1 to 4 tried to build a new native operator, an Arrow front for the handler and a hoisted, boxed key in one row. Three review rounds kept finding the same class of defect: a native or Arrow route reads the physical Arrow value, while the oracle reads the value pandas reconstructs, and the two can differ in key text, output width and payload size. Revision 5 fixes this at the root by not creating a second interpretation. The handler routes keep the oracle's own loop and add a per-distinct memo. The one existing streaming route (out-of-core) admits a code_set column only when the full-frame pandas converter proves the column is plain text. Everything else moves to V2-LOG or to a separate candidate row.

| Codex r2 finding | Verified on main | Resolution in rev 5 |
|---|---|---|
| 1 BLOCKER: physical text does not establish the oracle's HMAC input (pandas metadata `double[pyarrow]` on a string column turns `"1"` into `1.0`) | Yes. Full-frame ingestion is `to_pandas_fk_safe` (`execution/_pandas_adapter.py:204-206`), which applies schema metadata. Out-of-core admission for code_set checks config shape only (`execution/out_of_core/_compat.py:406`); source types reach only the faker check | Native unified and native chunked routes cut to V2-LOG (section 13): no new route reads physical values. Handler routes run on the pandas objects the oracle reads, so no gap exists there. Out-of-core (an existing route) admits code_set only for columns that the full-frame converter itself turns into text, checked on the schema before streaming (section 5.2). Forced streaming refuses before any scratch or sink write. AT-3 carries the Codex reproduction, the int64 case and text controls |
| 2 HIGH: eager key derivation changes success and error precedence | Yes, for the rev 4 selector (`determinism/_derive.py:300` encodes the namespace strictly) | The selector and key hoist are cut (V2-LOG). The memo calls the unchanged `apply_code_set` in row order, once for each new string form. Missing cells and repeats make no call. Derivation, E4 and E5 order are the oracle's by construction. AT-2 requires zero calls for empty and all-missing input and pins a lone-surrogate namespace case |
| 3 HIGH: chunk widths differ from pandas string storage | Yes, for the rev 4 native chunk rule | Native chunked route cut. The handler keeps today's assignment code, so pandas inference is the oracle's under every pandas option. AT-1 runs under default options, `mode.string_storage="pyarrow"` and `future.infer_string=True` |
| 4 HIGH: one Arrow string array hits the 32-bit offset limit | Yes, for the rev 4 handler front | The handler builds no Arrow array. The memo is a Python dict over the strings the loop already makes. Out-of-core keeps its current per-batch `code_set_map`, which is bounded by `batch_rows` and unchanged by this row (V2-LOG notes the existing bound) |
| 5 HIGH: `verify_corpus` bypasses the safe projection | Yes, and it is existing main behavior (`transforms/_codeset_loader.py:623+`), not caused by code_set routing | Out of this plan. Filed as candidate row CODE-SET-CORPUS-TEXT-HYGIENE in vault `OWNER-QUESTIONS.md`, "V1 candidate rows", together with the rev 4 loader, E4/E5 message and provenance items |
| 6 HIGH: two customer-file stats to protect | Yes, existing main behavior (`transforms/_codeset_loader.py:220-228` catches only `FileNotFoundError` and `NotADirectoryError`; `:283-296` interpolates `{exc}`) | Same candidate row as finding 5 |
| DESIGN: evidence helper imports a private chunked module | n/a | Moot. No evidence helper. Handler and out-of-core evidence code is unchanged |
| V2-LOG: one resolution per run is unproved for gated and nested calls | Yes, existing behavior (`preflight` in `execution/_strategies/_code_set.py` resolves and discards) | Unchanged by this row. Kept in V2-LOG |
| V2-LOG: AT-7 expects the wrong failure for a later numeric chunk | n/a | Moot (native chunked cut) |
| V2-LOG: four tests require an empty chunked veto set | n/a | Moot (no veto) |
| V2-LOG: F29 producer growth from the fatal projection | n/a | Moot (no fatal projection). S1 keeps both `exc.code` reads and the reason f-string verbatim in `CodeSetHandler.run`. Expected F29 delta is zero. CS-Q4 withdrawn |
| V2-LOG LOW: fixture wording (zero-row corpus, out-of-core all-missing output type, public-job golden key) | Out-of-core all-missing output type: yes, existing | Zero-row corpus and key fixtures moot. Out-of-core all-missing output type kept in V2-LOG |
| V2-LOG LOW: proof claims (provider index, OpaqueBox, HMAC) | n/a | Moot (no selector, no box) |

Also removed with the native cut: the census rehome, the draw-catalogue re-pin, the operator snapshot, the `_requirements.py` and `_chunked_entry.py` size moves, evidence-route parity, assembly policy and the unified retry boundary. This row now changes no sentry baseline, census, catalogue digest or size ceiling.

## 1. Frame

`code_set` remaps a code (ICD-10, MCC) to another real code from a pinned corpus. In mask mode the output is a pure function of `str(value)`, the config, the mask key, the namespace and the pinned corpus record (`transforms/code_set.py:262`, `_pick_mask` at `:465`, chapter path `_apply_chapter_preserve`). `row_index` is read only in gen mode.

Today the handler (`execution/_strategies/_code_set.py`, loop at about `:202-239`) calls `apply_code_set(str(value), ...)` once for every non-missing row. Each call re-runs `derive` (HKDF plus HMAC) and the selection. Dell estimate from the earlier microbenchmark: 21 to 23 us per row on the shipped `icd10` corpus. The handler serves four routes: pandas full frame, the chunked oracle leg, nested `_nested_leaves` and sequential non-key columns.

Out-of-core (`execution/out_of_core/_mask_group_c.py`, about `:370-395`) already selects once per distinct value through `kernel/_code_set.py` `code_set_map`. It reads the physical Arrow value and stringifies it with Python `str()`. Admission checks mode and `chapter_preserve` only. So an int64 source with a null maps `1` to key `"1"`, while the full frame converts the column to float64 and hashes `"1.0"`. With shipped ICD-10, namespace `cs` and test key `bytes([17]) * 8`, the out-of-core output for int64 `[1, null, 2]` is `[R10.9, None, M17.11]` and the full-frame output is `[L89.90, None, I10]`. Codex r2 showed the same split for a string column carrying `double[pyarrow]` pandas metadata. This is an existing route-dependent output: the same input masks to different codes depending on table size. It breaks joins across runs, which meets the V1 bar (function break).

No native, unified-slice or chunked-native code_set route exists today, and this row adds none.

## 2. Established solutions

Search run: the earlier revisions surveyed Arrow compute, DuckDB, Polars and Parquet for per-distinct evaluation, and NIST SP 800-188 for keyed pseudonymization; the codebase was searched for existing route-admission proofs. Rev 5 adopts the simplest of those patterns.

- Compute a pure function once per distinct value and expand: Arrow `dictionary_encode`, Parquet dictionary pages, DuckDB dictionary vectors, Polars categorical `map`. In Python the standard form is memoization keyed by the function's exact input (`functools.lru_cache` semantics). The handler's exact input is `str(value)`, so the memo key is `str(value)`, not the raw object (`1`, `1.0` and `True` hash equal as Python objects but have different string forms).
- Keyed pseudonymization by HMAC over a fixed domain (NIST SP 800-188; DE-02). The selection formula does not change.
- Route admission by proving the input interpretation: the unified slice already declines a column whose pandas round trip differs from the resident Arrow column (`execution/_unified_slice_admission.py:374-400`). Out-of-core reuses the same idea, done on the schema with the full-frame converter.

Custom code left: one dict lookup in the handler loop and one schema check in out-of-core preflight. Neither has a library equivalent at this size.

### Reuse inventory

- `apply_code_set` and everything under it: unchanged, called by the memo.
- `CodeSetHandler.run`: same loop, record pin, row errors, evidence and assignment.
- `execution/_fk_keys.py:430` `to_pandas_fk_safe`: the full-frame converter, called on an empty table built from the source schema.
- `_arrow_types.is_text`: string and large_string.
- `_group_c_conditional_rejection` and its existing code `out_of_core_code_set_shape_unsupported`: the new refusal reuses this code, so no reason is added to the registry.
- `execution/out_of_core/_preflight.py` (source types at about `:69-77`) and `execution/_pipeline_routing_signals.py` (`_source_arrow_types` at `:219-236`): the two production callers of the compat check, and the only places that read source schemas for it.

## 3. Guarantee and non-goals

After this row:

1. In mask mode, every handler route calls `apply_code_set` at most once per distinct `str(value)` per handler call, in first-occurrence row order, and never for a missing cell. Output values, row errors (index, column, trigger, reason, order), failed original objects, the raised exception for fatal cases, evidence and the pandas dtype equal the base handler's.
2. Out-of-core admits a code_set column only when its source schema is known, the Arrow type is string or large_string, and the full-frame converter turns that column into a text dtype with an unchanged column label. Otherwise automatic routing declines before streaming and the full-frame oracle runs, and forced out-of-core refuses before any scratch or sink write.

Non-goals (V2-LOG, section 13): a native `code_set` operator on the unified slice or chunked step; a hoisted or boxed key; an Arrow front in the handler; a Rust kernel; gen mode (keeps its per-row loop, since `row_index` matters); out-of-core admission of numeric code columns; any change to loader, provenance or error text (candidate row CODE-SET-CORPUS-TEXT-HYGIENE).

## 4. Enumerations

### Exit paths (handler, mask mode)

| # | Condition | Result |
|---|---|---|
| E1 | `source.isna()` marks the cell | append `None`, no call, no memo entry (as today) |
| E2 | `str(value)` seen before with a success | append the memoized output, set `masked_any` |
| E3 | `str(value)` seen before with a per-value error | append this row's own original object, emit a `RowError` for this row with the memoized reason |
| E4 | first occurrence, `apply_code_set` returns | memoize, append, set `masked_any` |
| E5 | first occurrence, `PlanCompileError` with a code in `_PER_VALUE_CODE_SET_ERRORS` | memoize the reason string, append the original object, emit the `RowError` |
| E6 | first occurrence, any other exception (E4 single-row corpus, pin mismatch, lone-surrogate namespace, ...) | propagates unchanged, at the same row as today, because every earlier row had a non-fatal string form |
| E7 | zero rows, or every cell missing | zero calls; existing assignment branches |

### Routes

| Route | After |
|---|---|
| pandas full frame | memoized handler (S1) |
| chunked oracle leg | memoized handler per chunk; memo resets per call (S1) |
| nested `_nested_leaves` | memoized handler (S1) |
| sequential non-key column | memoized handler (S1) |
| out-of-core | unchanged mapping; admission requires proved text (S2) |
| unified slice, chunked native | not admitted today; unchanged (V2-LOG) |

### Codes

No new reason code. S2's refusal reuses `out_of_core_code_set_shape_unsupported` with a message that names the cause and the remedy (cast the column to text). The message carries table and column names only, no values.

### FK shapes and `when:`

Unchanged. Out-of-core FK candidates with a non-key code_set payload are the case AT-3 runs. Gated code_set columns keep today's `run_with_when_gate` path.

### Output surfaces

| Surface | Change |
|---|---|
| masked column, row_errors, raised errors, evidence | none on handler routes |
| out-of-core route choice | numeric, null-typed, unknown-schema and metadata-reinterpreted code_set payloads now take the full-frame route (automatic) or refuse (forced) |
| `docs/execution-backends.md` code_set rows | say "once per distinct value" for handler routes and name the out-of-core text requirement |
| CHANGELOG | one line for the routing change |

## 5. Design

Design notes: no new module, class, abstraction or route. Principles in play: one place per fact (the full-frame converter is the single definition of "what the oracle reads", and S2 asks it instead of restating its rules); single-purpose function (`pandas_text_columns`). Pattern: memoization of a pure function (section 2).

### 5.1 Handler memo (S1)

In `CodeSetHandler.run`, mask mode only, keep the loop `for i, value in enumerate(source)` and the `na_mask` check. Add two local dicts, `done: dict[str, str]` and `failed: dict[str, str]` (string form to output, string form to row-error reason). For a non-missing cell compute `key = str(value)`. On a hit in `done`, append the output and set `masked_any`. On a hit in `failed`, append `value` (this row's own object) and a `RowError` for row `i` with the stored reason. Otherwise run today's `try` block unchanged with `key` as the first argument, then record the result in `done` or the built reason string in `failed`.

Keep the two `exc.code` expressions and the reason f-string verbatim inside `run` (F29 inventory keys are file, function and expression; expected delta zero). Gen mode keeps the current loop untouched, since its output depends on `row_index`. The dicts are locals of one `run` call, so no state outlives the column. They hold string forms and output codes, never key material, so the secret-material census is unaffected.

Cost model after S1: `rows x (iteration + isna + str + dict lookup, about 0.3 us) + distinct x (today's 21 us)`.

### 5.2 Out-of-core admission (S2)

One helper, `pandas_text_columns(sources) -> frozenset[tuple[str, str]]`, in `execution/out_of_core/_preflight.py`. For each source with a schema: build `schema.empty_table()` and convert it with `to_pandas_fk_safe(empty, ())`, inside a `try` that treats any exception as "nothing proved for this table". If the frame's column labels differ from the schema names, prove nothing for that table. Otherwise include `(table, column)` when `is_text(field.type)` and the frame dtype is `object`, a pandas `StringDtype`, or an `ArrowDtype` over string or large_string. The empty conversion runs the same metadata reconstruction as full-frame ingestion (`execution/_pandas_adapter.py:204-206`), so a column whose metadata re-types it (the `double[pyarrow]` case) is not proved. It reads no rows.

`check_out_of_core_compatibility` (`execution/out_of_core/_compat.py:174`) and `out_of_core_admission` (`execution/_pipeline_routing_signals.py:57`) take a new keyword `pandas_text: frozenset[tuple[str, str]] | None = None`. `_group_c_conditional_rejection` receives it. For a mask-mode code_set node without `chapter_preserve`, it rejects with the existing code unless every node column is in `pandas_text`. `None` proves nothing, so it rejects too.

The compat check has exactly two production callers on main, and both pass the helper's result: the runner preflight (`_preflight.py:77`) and routing (`_pipeline_routing_signals.py:83`, fed from its source loop at `:267-269`). Choke point: `_group_c_conditional_rejection` is the only place code_set admission is decided, and its default (`None`) rejects, so a new caller that forgets the facts gets a refusal, not a silent admit. Guard: AT-3 `pandas_text=None` case. Mutation: M5. Forced out-of-core raises from preflight, which runs before the caller creates a temp root, so no scratch or sink write happens.

Size: `_compat.py` is 585 lines with a 600 ceiling. If the change would cross 600, move `_group_c_conditional_rejection` into `execution/out_of_core/_mask_group_c.py` (544 lines) beside `preflight_group_c`, after checking for an import cycle. Do not raise a ceiling. `_pipeline_routing_signals.py` is 613 with ceiling 633; the change there is about +3 lines.

## 6. Placement, size and pinned surfaces

No new file. Public names added: none. Private names added: `pandas_text_columns`, keyword `pandas_text`.

| File | Lines now | Ceiling | Slice and change |
|---|---|---|---|
| `execution/_strategies/_code_set.py` | 283 | 600 | S1: memo in the mask loop, about +20 |
| `execution/out_of_core/_preflight.py` | 94 | 600 | S2: `pandas_text_columns`, pass it to compat, about +30 |
| `execution/out_of_core/_compat.py` | 585 | 600 | S2: keyword and code_set check, about +12; move per 5.2 if needed |
| `execution/_pipeline_routing_signals.py` | 613 | 633 | S2: pass the facts, about +3 |
| `docs/execution-backends.md`, `CHANGELOG` | - | - | S1 and S2 wording |

Tests go in existing test files beside the current code_set strategy tests (AT-1, AT-2), `tests/parity/test_out_of_core_group_c_parity.py` and `tests/parity/test_ooc_code_set_arrow.py` (AT-3), and the `tests/perf/` throughput file (AT-4). Witnesses to recheck in S2: `tests/unit/execution/test_out_of_core_public_api.py` and any test that admits a code_set out-of-core node with a non-text or unknown source. Update only those that assert the old admission, and keep their value assertions.

Pinned surfaces: secret-material census, draw-site catalogue, F29 reason inventory, reason registry, module size, package fan-out and operator snapshot all have zero planned delta. A builder who sees a nonzero delta in any of them stops and reports. No baseline, census or allowlist refresh is part of this plan.

## 7. Defect classes

| # | Class | Where | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Route parity, two interpretations of one value | out-of-core vs full frame | admit only columns the full-frame converter proves are text | AT-3 | M4, M5 |
| 2 | Memo key wider than the function input | handler | key is `str(value)`, the exact first argument | AT-1 | M1 |
| 3 | Memo keeps row-specific data | failed rows | memo stores only the reason; the row's own object and index are used | AT-1 | M2 |
| 4 | State outliving its scope | memo dicts | locals of one `run` call | AT-1 | M3 |
| 5 | Error precedence change | fatal and per-value errors | first occurrence calls the unchanged scalar function in row order | AT-2 | M7 |
| 6 | Weak test (value parity passes before the change) | speed | call counts and the perf ratio carry fail-before | AT-2, AT-4 | M7 |
| 7 | Silent mid-run abort | forced out-of-core | refusal in preflight, before temp root | AT-3 | M5 |
| 8 | Gen-mode drift | gen loop | memo only in mask mode | AT-1 | M6 |

Recurring-defect catalog: no new validation grammar, persisted type, scanner or raised cap. No exception context is added (the memo stores strings). No value text is added to any log or message. Mutations run on the final head of each slice, head recorded.

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity against the base handler, captured on the S1 base head. One object column with `"1"`, `1`, `1.0`, `True`, `None`, `NaN`, `pd.NA`, a lone-surrogate string, and repeats of each; a float column; Int64 with NA; boolean extension; category; datetime64 with NaT; non-empty all-null; zero rows; shipped `icd10` plus one more shipped corpus; namespaces `cs`, another, and absent; `chapter_preserve` false and true, with an absent chapter and a sole-member bucket interleaved and repeated, plus a missing row and a success. Compare outputs, the full `RowError` list (index, column, trigger, reason, order), the original failed object per row, evidence in `ctx.code_set_corpora`, pandas dtype and `pa.Table.from_pandas` schema. Run under default pandas options, `mode.string_storage="pyarrow"` and `future.infer_string=True`. Run on the full-frame, chunked oracle (two chunks that split repeats), nested and sequential entries. Gen mode: same columns, output equal to base | memo bugs (M1, M2, M3, M6) | S1 |
| AT-2 | Spy on `apply_code_set` inside the handler. Mask mode: exactly one call per distinct `str(value)` of non-missing cells, in first-occurrence order; zero calls for zero rows and for all-missing input. A column whose first non-null value triggers E4 raises the same exception class, code and message as base at the same call. A column with E5 values before an E4 value records the same row errors as base before raising. A lone-surrogate namespace: all-missing input succeeds with zero calls (as base); non-missing input raises the same exception as base. Gen mode: one call per non-missing row (unchanged) | one call per row today | S1 |
| AT-3 | Out-of-core admission. Sources: (a) int64 batches `[1]` then `[null, 2]` (the section 1 witness); (b) Codex reproduction: string column `["1", null]` with pandas metadata `double[pyarrow]`; (c) null-typed column; (d) metadata that renames the column label; (e) metadata-free string and large_string; (f) string with pandas metadata for `object` and for `string`. For (a) to (d), in a real automatic out-of-core FK candidate job with a non-key code_set payload, assert the route declines before streaming (route evidence names `out_of_core_code_set_shape_unsupported`) and output equals the full-frame result at every position; with forced out-of-core assert the coded refusal and no temp root, scratch or sink file. For (e) and (f), assert out-of-core runs and output equals the full-frame result, under default options and `future.infer_string=True`. A direct `check_out_of_core_compatibility` call with `pandas_text=None` rejects code_set and still admits a plan without code_set | (a) and (b) stream today with different output | S2 |
| AT-4 | `perf` marker: 200,000 rows, 2,000 distinct codes, object column, `CodeSetHandler.run` end to end, mask mode, base loop and memo in the same process on the same sample. Require a ratio of at least 15x (ratio only, as the default gate runs `perf`). The PR records the measured ratio and the Dell numbers | about 1x today | S1 |

Existing code_set tests (pin, swap, mismatch, evidence, quarantine, `when:` preflight) stay green unchanged in S1.

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | key the memo by the raw object instead of `str(value)` | AT-1 (`1`, `1.0`, `True` collide) |
| M2 | memoize the first failed row's object and reuse it for later rows | AT-1 |
| M3 | lift the memo to module scope | AT-1 (namespace and corpus cases) |
| M4 | S2 helper checks only the Arrow type, not the converted dtype | AT-3 (b) |
| M5 | treat `pandas_text=None` or a missing column as proved | AT-3 (`None` case) |
| M6 | apply the memo in gen mode | AT-1 gen case |
| M7 | remove the memo hit path (call per row) | AT-2, AT-4 |

## 10. Frozen contracts

- The full-frame handler output is the reference and does not change. S1 is byte-identical by construction (section 5.1), and AT-1 checks it.
- S2 changes out-of-core route choice, not out-of-core mapping. Admitted out-of-core output is unchanged. Inputs that change route now get the full-frame output, which is the contract.
- Error text is unchanged in this row.

## 11. Pre-mortem

- A builder iterates with `source.tolist()` or `to_numpy()` for speed. String forms can differ from `Series.__iter__` (numpy scalar vs Python scalar boxing). Keep the existing iteration. AT-1's float, Int64, bool, category and datetime columns catch a change.
- A large table with an integer code column (MCC stored as int64) used to stream through out-of-core with the wrong keys. It now goes full frame, which may exceed the memory budget and fail with the router's existing budget error. That is the right trade: a clear error with a remedy (cast to text) instead of route-dependent output. The CHANGELOG line says so. V2-LOG holds the follow-up to admit null-free integer columns.
- The empty-table conversion could differ from the populated one for some metadata. Dtype reconstruction is where the conversion reinterprets values, and the empty conversion runs it. AT-3 (b) is the guard, and an unknown result declines.
- Chunked oracle chunks that carry their own metadata: the chunked oracle leg converts each chunk with pandas, as today. This row does not change it (V2-LOG).
- High-cardinality columns (distinct close to rows) gain little. The cost never exceeds today's loop plus one dict lookup per row.

## 12. Slices

| Slice | Content | Size | Risk | Gate |
|---|---|---|---|---|
| S1 | Handler memo (5.1), AT-1, AT-2, AT-4, M1 to M3, M6, M7. Docs line | half a builder-day plus gate | R2 | Codex and Dennis; T1 code_set tests plus F29 and census sentries (expected zero delta) |
| S2 | Out-of-core admission (5.2), AT-3, M4, M5, witness updates. Docs and CHANGELOG line | one builder-day plus gate | R2 | Codex and Dennis; out-of-core parity suites and routing tests |

S1 and S2 touch different files and can build in parallel in separate worktrees. Target: both merged by 2026-12-15.

## 13. Owner questions and deferred items

In vault `OWNER-QUESTIONS.md`:

- CS-Q1 (Arrow per distinct vs Rust kernel): superseded. Rev 5 keeps byte-identical output with a Python memo; no Rust kernel.
- CS-Q3 (gen mode per row in V1): unchanged, recommended yes.
- CS-Q4 (F29 keys): withdrawn; no F29 delta.
- CS-Q5 (new, kind default): the native code_set operator moves to 1.x, and code_set is a named exception on the run card. Recommended yes: S1 gives the handler routes a large speed-up on code columns, and the native route needs a pandas-interpretation proof, width policy and offset handling that three review rounds could not close cheaply.
- Candidate row CODE-SET-CORPUS-TEXT-HYGIENE under "V1 candidate rows" (Codex r2 findings 5 and 6, plus the rev 4 loader and message items).

V2-LOG:

- Native `code_set` operator on the unified slice and chunked step. Preconditions found in the rev 1 to 4 reviews: prove the pandas interpretation per column and per later manual chunk (metadata can change while the physical type stays string); match pandas string storage width (`large_string` under `mode.string_storage="pyarrow"` or `future.infer_string`); share distinct selections across bounded chunks and size the mapped output against the 32-bit offset limit; a typed fatal path past unified retry; F29 producer review for any rebuilt `PlanCompileError`; strategy-specific chunked veto tests.
- Hoisted, boxed key per handler call or batch (cuts about 15 us per distinct). Requires lazy derivation on the first draw, so empty, all-missing and rejected inputs derive nothing, plus a census rehome and draw-catalogue re-pin.
- Arrow front for Arrow-backed text Series in the handler.
- Out-of-core admission of null-free integer code columns (reuse the existing null-bearing integer scan).
- Out-of-core output type for an all-missing string payload is fixed `string`, while the full frame gives Arrow null (existing).
- Out-of-core `code_set_map` builds one `pa.string()` array per batch; payloads are bounded by `batch_rows` (existing).
- One corpus resolution per run for `when:`-gated and nested code_set: `preflight` resolves and discards, then `run` resolves again; an ungated nested column with no leaves returns before the child runs (existing).
- Chunked oracle leg: per-chunk pandas metadata is not checked against the first chunk (existing).
- A native code_set tenant on the sequential FK route.
- Merge the two `code_set_corpora` aggregators (`execution/_chunked_code_set.py`, `execution/_chunked_output_sink.py`).
