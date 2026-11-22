Status: plan (revision 1, 2026-11-22)

# CODE-SET-NATIVE: code_set masks once per distinct value over Arrow, on every route, and gets a native operator

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: CODE-SET-NATIVE, new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 76: "`code_set` | pandas | chunked pandas | no operator | none | Rust lookup over the pinned code list, 1 to 2 slices, 1.0.x"). No row exists yet in the CLI roadmap; the CLI roadmap owner adds it to `docs/roadmap/groups/mask.md` (1.0.x) when this plan is accepted. Engine only.

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `security.md` (keyed selection, secret material in frames), `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (keyed masking on every route; a new native operator; secret-derived key material). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; each column runs its own path; faster wins even when bytes change, if each change is named. The brief asks to choose Rust or Arrow by measurement. The measurement (section 1) picks Arrow: the per-row cost is in the Python loop, not in the HMAC, and a per-distinct Arrow map with a hoisted key removes it with no byte change. A Rust kernel would only help when almost every row is a distinct code, which a code column is not.

## 1. Frame

`code_set` remaps a code (ICD-10, NPI, and the other shipped corpora) to another real code from a pinned corpus. Mask mode (`transforms/code_set.py:465` `_pick_mask`, `:494` `_pick_from_seq`) is a pure function of the value: `idx = int(HMAC-SHA256(derive(mask_key, namespace or "code_set", _KEYED_SALT), value).hex[:8], 16) % candidate_count`, then the "index with a hole" step (`transforms/_codeset_index.py:98`, `:111`) skips the input's own position.

Where it runs today:

| Route | Code | Shape |
|---|---|---|
| pandas full frame | `execution/_strategies/_code_set.py:206` `CodeSetHandler.run` | one `apply_code_set` call per row; each call re-runs `derive` (HKDF plus HMAC) for the key |
| chunked | the same handler per chunk (`execution/_chunked.py:198`, admission `execution/_chunked_code_set.py:91`: mask mode, no `chapter_preserve`) | per row, per chunk |
| out-of-core | `execution/out_of_core/_mask_group_c.py:385` `code_set_map` (`kernel/_code_set.py`) | once per distinct value, then `pc.take`; but `to_pylist` and a Python `str()` pass over every row first |
| unified slice | not admitted: no `OperatorSpec` for `code_set` (`execution/_operator_registry.py`); ROUTE-LABEL-TRUTH files it as `no_native_operator` | - |

Measured on the Dell, 120,000 rows over the shipped `icd10` corpus (65 rows), companion irrelevant:

| Path | Per row |
|---|---|
| `CodeSetHandler` per row (oracle) | 21 to 23 us |
| `code_set_map` (out-of-core today) | 1.05 to 1.16 us, almost all `to_pylist` and `str()` |
| Arrow front: `dictionary_encode` on the Arrow array, select per distinct, `pc.take` | 34 to 58 ns |
| one `select` per distinct value, as written (re-derives the key) | 14 to 24 us per distinct |
| the HMAC alone with the key hoisted | 2.7 to 4.6 us per distinct (devbox: `hmac.new` 3.4 us, `hmac.digest` 4.7 us) |

All three outputs were equal. So the cost model is `rows x 50 ns + distinct x (HMAC + lookup)`. A clinical code column at 10,000,000 rows with 70,000 distinct codes costs about 0.5 s + 0.2 s. A Rust HMAC kernel would cut the second term by about 10x, which matters only when distinct is close to rows. Code columns are bounded vocabularies (ICD-10-CM has about 74,000 codes), so Arrow wins on cost per line of new code.

No existing compiled kernel computes `HMAC(derive(K, ns, salt), value)`: `derive_hex_raw_batch` (`decoy-engine-native/src/arrow_ffi.rs:448`) computes `derive(K, ns, value)`, which frames the namespace into the message. Using it would change every code_set output. Section 10 records this as the rejected alternative.

## 2. Established solutions

Search run: dictionary encoding as a compute pattern (Apache Arrow `dictionary_encode`, Parquet dictionary pages, DuckDB dictionary vectors, Polars categorical `map` on categories), and keyed pseudonymization over a lookup domain (NIST SP 800-188 de-identification, HMAC-based pseudonym tables).

- Arrow, Parquet, DuckDB and Polars all compute a pure function of a low-cardinality column once per dictionary entry, then expand by index. The engine already follows this in `kernel/_code_set.py` (B6). This row moves that one helper to an Arrow front and calls it on every route.
- Keyed pseudonymization with HMAC over a fixed domain is the standard (NIST SP 800-188 section on pseudonymization; the engine's own DE-02 decision). The selection formula does not change.
- Python's `hmac.digest` is the one-shot C path for HMAC (stdlib docs, "faster than `hmac.new`" for one message); S1 measures it against `hmac.new` on the Dell and keeps the faster. Either gives the same bytes.

### Reuse inventory

- `kernel/_code_set.py` `code_set_map`: the one per-distinct helper. Extended, not copied.
- `transforms/code_set.py` `resolve_corpus_record`, `_pick_from_seq`, `hole_candidate_count`, `hole_resolve`, `describe_loaded_corpus`: the selection math stays in one place. The new selector calls these.
- `_opaque.OpaqueBox`: holds the hoisted derived key so no frame keeps it in a local.
- `execution/_chunked_code_set.py` `resolve_pinned_code_set_records`, `aggregate_chunk_code_set_corpora`, `reject_code_set_fk_keys`, `reject_code_set_when`: reused by the native operator for record pinning and evidence.
- `OperatorSpec` and the operator step (`execution/native/_operator_step.py`): reused for the new operator.

## 3. Guarantee and non-goals

After this row:

1. On every route, mask-mode `code_set` selects once per distinct non-null value per batch, chunk or frame, with the derived HMAC key computed once per column. The output is byte-identical to today's per-row oracle for every value, null and type. With `chapter_preserve`, per-value errors give the same `RowError` list, in the same row order, and keep the original value in place.
2. A string or large_string Arrow source is never turned into a Python list for the encode step.
3. `code_set` has a native operator (S2). On the unified slice and the chunked native step it runs as `arrow_python`. Admission: mask mode, no `chapter_preserve`, string source, not an FK key, and the existing `when:` rule. The `code_set_corpora` evidence is the same as today.
4. One mechanism: `CodeSetHandler.run`, the chunked path, the out-of-core path and the native operator all call `code_set_map` with one selector type.
5. The derived key is never a plain local in a frame (OpaqueBox pattern).

Non-goals: gen mode (`_pick_gen`, keyed on row index; it keeps its per-row loop and is named on the run card as Python); a Rust kernel (section 10); `chapter_preserve` on native routes (per-value errors are not modeled there, as on the chunked route today); new corpora.

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | null cell | null in place, no selection |
| E2 | value in corpus | candidate count `n - 1`, hole skip |
| E3 | value not in corpus | candidate count `n` |
| E4 | single-row corpus | `CODE_SET_SINGLE_ROW_CORPUS`, job-fatal, as today (`transforms/code_set.py:262` `apply_code_set` validates before selecting) |
| E5 | `chapter_preserve`, chapter absent or sole-member bucket | per-value `RowError` for every row with that value; original value kept (full-frame route only; codes in `execution/_strategies/_code_set.py:93` `_PER_VALUE_CODE_SET_ERRORS`) |
| E6 | any other `PlanCompileError` from the selector | job-fatal, as today |
| E7 | empty frame | `pd.array([], dtype="string")`, as today (`_strategies/_code_set.py`) |
| E8 | out-of-core sees a per-value code | `OUT_OF_CORE_CODE_SET_ROW_ERROR_UNREACHABLE`, as today (`execution/out_of_core/_mask_group_c.py:386-395`) |

### Routes

| Route | After |
|---|---|
| pandas full frame | `CodeSetHandler.run` (`execution/_strategies/_code_set.py:142`) calls `code_set_map` (S1) |
| chunked oracle leg | same handler (S1) |
| out-of-core | `code_set_map` with the Arrow front and hoisted key (S1) |
| unified slice | new `native_code_set` operator (S2) |
| chunked native step | same operator (S2) |
| sequential | same operator, if `_sequential_native_ops` admits the spec (S2; the builder confirms the sequential admission list reads `OPERATORS`) |

### Codes

No new failure codes. S2 removes `code_set` from the `no_native_operator` family in ROUTE-LABEL-TRUTH's `KERNEL_LESS_FAMILY` if that plan has merged; its sentry then sees the new `OperatorSpec`. Native declines for `chapter_preserve` and gen mode reuse the chunked admission texts (`_chunked_code_set.py:97-107`); if ROUTE-LABEL-TRUTH needs them as `RouteDeclineCode` members, S2 registers them once in `reasons/route`.

### FK shapes

- A code_set column that is an FK key on either side: refused on native routes by the reused `reject_code_set_fk_keys` (both orientations), as on the chunked route today.
- A code_set column that is not a key: no FK interaction.

### Fields

| Field | Values | Handling |
|---|---|---|
| `code_set` | a shipped corpus or an override path | `resolve_corpus_record`, pinned once per job |
| `mode` | `mask`, `gen` | mask: this row; gen: unchanged per-row loop |
| `chapter_preserve` | true, false | true: per-distinct selection with per-value errors (full frame); native refused |
| `namespace` | set or absent | absent uses `"code_set"`, as today |
| `corpus_source_version` | set or absent | pin check unchanged |

### Output surfaces

| Surface | Change |
|---|---|
| masked column | none (byte-identical, same pandas dtype) |
| `row_errors` | same entries, same order |
| `quality_metrics["code_set_corpora"]` | same |
| route evidence and run card | `arrow_python` on the native operator (S2) |
| `docs/` route table | code_set row names Arrow per distinct, and gen mode as Python |

## 5. Design notes

Principles that apply: one place per fact (the selection math stays in `transforms/code_set.py`; the dedupe stays in `kernel/_code_set.py`); dependency direction (`kernel/` takes the selector as a callable and does not import `transforms/`, as today). Established pattern: dictionary-encode and map (section 2).

### 5.1 The selector

`CodeSetSelector` in `transforms/code_set.py`, built once per column from `(config, record, mask_key, namespace)`:

- computes `derive(mask_key, namespace or "code_set", _KEYED_SALT)` once and keeps it in an `OpaqueBox`;
- `select(value: str) -> str` does what `_pick_from_seq` does today: the position from `record.selection.code_index`, the candidate count, the HMAC opened inside the call expression, `hole_resolve`, and the corpus code. With `chapter_preserve` it runs the chapter lookup and raises the same per-value codes.
- `_pick_from_seq` and `apply_code_set` call the selector, so there is one formula. AT-1 proves byte equality against a frozen copy of the old outputs.

### 5.2 `code_set_map` front

`code_set_map(values, select, *, on_error=None)`:

- `pa.string()` or `pa.large_string()` input: `values.dictionary_encode()` directly. No `to_pylist`.
- any other Arrow type: today's `str()` coercion (keeps the oracle's spelling of non-strings).
- `select` runs once per dictionary entry. If `on_error` is given, a per-value error code from the allowed set marks that dictionary index as failed instead of raising. The caller gets the failed indices back and builds `RowError`s in row order.
- Returns `pc.take(mapped, indices)` and, when asked, the failed-row mask.

### 5.3 Handler

`CodeSetHandler.run`, mask mode:

1. If `pd.api.types.infer_dtype(source, skipna=True) == "string"`, convert with `pa.array(source, type=pa.string(), from_pandas=True)`. Otherwise build the Arrow input with the same `str()` coercion the per-row loop used. Python equality must not be used for dedupe here, because `1`, `1.0` and `True` hash equal but print differently.
2. `code_set_map` with the selector and, for `chapter_preserve`, `on_error`.
3. Rebuild the column as today's object column: nulls `None`, failed rows keep their original object. `masked_any` and the evidence stamp are unchanged.

Gen mode keeps the existing loop.

### 5.4 Native operator (S2)

`OperatorSpec(strategy="code_set", operator_id="native_code_set", shape="kernel", planned_backend=ARROW_PYTHON, required_kernel=None, positive_kernel_evidence=False, unified_resident_types=string and large_string, full_frame_assembly=<the shape that matches the handler, proven by AT-6>)`. `CodeSetParams` carries the pinned record from `resolve_pinned_code_set_records`. The step calls `code_set_map`. The evidence for `code_set_corpora` rides on the step result and is merged with `aggregate_chunk_code_set_corpora`, the function the chunked route uses today.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `CodeSetSelector` | `transforms/code_set.py` (569 lines, about +40, then about -20 from `_pick_from_seq`) | "Transforms", fan-out limit 25 | no new module |
| Arrow front and `on_error` | `kernel/_code_set.py` | "Arrow kernels" | no new module |
| handler change | `execution/_strategies/_code_set.py` (283 lines, net smaller) | "Masking strategy handler", freeze 28 | no new module |
| `OperatorSpec`, params, step branch | `execution/_operator_registry.py`, `execution/native/_operator_params.py`, `execution/native/_operator_step.py` | "Pipeline spine", "Native companion bridge" | no new module; `execution/native/` stays at its freeze (55) |
| tests | `tests/unit/transforms/test_code_set_selector.py`, `tests/unit/kernel/test_code_set_map.py`, `tests/unit/execution/native/test_native_code_set.py` | "Unit tests" | existing code_set tests |
| docs | `docs/` route table row; changelog fragment | docs | - |

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | per-value `RowError` reasons and decline texts | reasons carry the code only, as today; no code value in any message | AT-5 | put the value into the `RowError` reason (AT-5 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no resource is acquired | n/a | n/a |
| 3 | State and concurrency | the hoisted key and the pinned record are per column per job | selector built once per column; the record is pinned before the first chunk, as today | AT-3 (a replaced corpus file mid-run does not change the record) | build the selector per chunk from a fresh `resolve_corpus_record` (AT-3 red) |
| 4 | Route parity and silent fallback | five routes | one `code_set_map` and one selector on all of them; native declines carry a registered reason | AT-1, AT-6 | M2 |
| 5 | Referential integrity | code_set on an FK key | refused on native routes in both orientations by the reused check | AT-7 | drop the reverse orientation (AT-7 red) |
| 6 | Untrusted producer | an override corpus file | existing schema and version checks; unchanged | existing corpus tests | n/a |
| 7 | Check then use | the corpus file | the record is read once and pinned (existing `_CorpusRecord`); the selector never reopens the file | AT-3 | M5 |
| 8 | Weak tests | AT-1 equality passes before the change | AT-2 (no `to_pylist`, one key derive) and AT-8 (speed) carry the fail-before | AT-2, AT-8 | M4 |
| 9 | Refactor drift | `_pick_from_seq` now calls the selector | frozen golden outputs captured before S1 | AT-1 | M1 |
| 10 | Frozen contract drift | compatibility contract freezes code_set output | no byte change | AT-1 | M1 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no new validation | - |
| 2 | Strict wire and stored types | no new persisted model | - |
| 3 | No exception context | yes: selector errors must not keep the key or value in `__context__` | AT-5 asserts cause and context are None on the per-value error |
| 4 | Versioned read models | the corpus `source_version` pin, unchanged | existing tests |
| 5 | Normalized guard scanners | no new scanner | - |
| 6 | No reaching into private modules | the native step imports the public selector name from `transforms.code_set` | review |
| 7 | No hidden CI failures | AT-8 under the `perf` marker, no `continue-on-error` | CI diff review |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M6 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | the physical-seam sentry allowlist; no new route file | sentry in T2 |
| 11 | No raised caps | `_strategies` freeze 28, `execution/native/` 55, module size | no new module; sizes listed in the report |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity: outputs of today's per-row oracle captured at `70881ad79` for icd10 and one more shipped corpus, values in and out of corpus, nulls, int and float and bool sources in an object column (`1`, `1.0`, `True`), `chapter_preserve` true and false, two namespaces and the absent namespace; every route gives the same values and pandas dtype | passes before (kept as guard); fail-before is AT-2 | S1 |
| AT-2 | Instrumented: for a string source, `to_pylist` is not called and `derive` is called once per column (spy) | per-row `derive` today | S1 |
| AT-3 | Pinning: replacing the override corpus file between chunks does not change the output or the evidence | passes today; guards the selector build site | S1 |
| AT-4 | `chapter_preserve` errors: the `RowError` list equals today's, same order, original values kept | passes today; guards `on_error` | S1 |
| AT-5 | Value-free errors: no corpus or source value in `RowError.reason` or any raised message; cause and context None | passes today for the reason; the context half is new | S1 |
| AT-6 | Native operator: unified slice and chunked native step admit mask-mode string code_set, outputs equal AT-1 goldens, executed backend `arrow_python`, `code_set_corpora` evidence equal to the full-frame run | no operator today | S2 |
| AT-7 | Native refusals: gen mode, `chapter_preserve`, non-string source, FK key in both orientations each decline with their registered reason and the column runs on the oracle path with AT-1 values | no operator today | S2 |
| AT-8 | Speed floor, `perf`, Dell: 1,000,000 rows, 5,000 distinct codes, under 150 ns per row on the full-frame route (21 us today) | 21 us today | S1 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | `hole_resolve` uses `idx > position` instead of `idx < position` | AT-1 |
| M2 | Native step dedupes on the raw Python value instead of the `str()` form | AT-1 (the `1` / `True` cell), AT-6 |
| M3 | `on_error` marks the first row only, not every row with that value | AT-4 |
| M4 | Handler calls `to_pylist` before encoding | AT-2 |
| M5 | Selector re-resolves the record per batch | AT-3 |
| M6 | Native operator drops the evidence merge | AT-6 |

## 10. Frozen contracts

- Masked code_set output is frozen by the compatibility contract. This row keeps it.
- Rejected alternative, recorded for the owner: route code_set through `derive_index_batch` (native, threaded, and moved to CMAC by NATIVE-THREADS-DEFAULT S3). It would change every code_set output and break joins with earlier runs, for a speed gain only at near-unique cardinality. Not proposed. If a measured customer column shows distinct close to rows, a follow-up row can add it with a `Breaking:` line.

## 11. Pre-mortem

- An object column holding both `"1"` and `1` dedupes to one entry. It must, because both print as `"1"` and today's loop gives both the same output. AT-1 covers it.
- The Arrow conversion of a pandas object column with `pd.NA`, `NaN` and `None` mixed treats one of them as non-null. The handler keeps today's `isna()` mask and applies it after the take. AT-1 has all three.
- The hoisted key outlives the column in a long-lived selector. The selector is a local of the handler call and is dropped at return; the key sits in an `OpaqueBox`.
- S2 lands before PER-COLUMN-ROUTING and a mixed table still runs one route. Then S2's gain shows only on all-native tables. S1 already removes the per-row cost everywhere.

## 12. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | `CodeSetSelector`; `code_set_map` Arrow front and `on_error`; handler and out-of-core on the one path; AT-1 to AT-5, AT-8 | S to M: about 150 lines, 250 lines tests | Codex and Dennis; T2 on the code_set selection |
| S2 | `OperatorSpec`, `CodeSetParams`, step branch, evidence merge, admission reuse; remove `code_set` from `no_native_operator`; docs route table; AT-6, AT-7 | M: about 200 lines, 250 lines tests | Codex and Dennis |

Both slices fit before 2026-12-15. S2 depends on ROUTE-LABEL-TRUTH S1 if that has merged (its sentry), and works without it.

## 13. Open questions for the owner

- Q1: Accept Arrow (byte-identical) over Rust (recommended), given the measurement in section 1?
- Q2: Add the CODE-SET-NATIVE row to the CLI roadmap `mask.md` at 1.0.x (S1) with S2 in the same row? Recommended: yes, one row.
- Q3: Gen-mode `code_set` stays per row and is named on the run card. Recommended: yes for V1; a later row can key it on the positional index kernel with a `Breaking:` line.
