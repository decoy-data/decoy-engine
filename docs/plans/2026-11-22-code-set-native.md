Status: plan (revision 3, 2026-11-24; Dennis round 1 applied; anchored to engine main 9f7bb1f4a)

# CODE-SET-NATIVE: code_set masks once per distinct value over Arrow, on every route, and gets a native operator

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: CODE-SET-NATIVE, new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 76: "`code_set` | pandas | chunked pandas | no operator | none | Rust lookup over the pinned code list, 1 to 2 slices, 1.0.x"). The row is in the CLI roadmap `docs/roadmap/groups/mask.md` as a 1.0 row (owner 2026-11-22, V1 fast path). Engine only.

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. First read at engine `70881ad79` (0.28.3), re-anchored at `cb06f318e`, then at `origin/main` `9f7bb1f4a` (2026-11-24) for revision 3. Line numbers are at `9f7bb1f4a`. No code_set file changed between `cb06f318e` and `9f7bb1f4a`; the ratchet checker gained `tests/sentry/ratchet/_rehome.py`, which this plan uses. No merged PR does this work (searched `code_set` in merged engine PRs).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `security.md` (keyed selection, secret material in frames), `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (keyed masking on every route; a new native operator; secret-derived key material). Plan review: Dennis (round 1 GO-WITH-FIXES, every V1 and design item applied in revision 3), then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; each column runs its own path; faster wins even when bytes change, if each change is named. The brief asks to choose Rust or Arrow by measurement. The measurement (section 1) picks Arrow: the per-row cost is in the Python loop, not in the HMAC, and a per-distinct Arrow map with a hoisted key removes it with no byte change. A Rust kernel would only help when almost every row is a distinct code, which a code column is not.

## 1. Frame

`code_set` remaps a code (ICD-10, NPI, and the other shipped corpora) to another real code from a pinned corpus. Mask mode (`transforms/code_set.py:465` `_pick_mask`, `:494` `_pick_from_seq`) is a pure function of the value: `idx = int(hmac_hex(derive(mask_key, namespace or "code_set", _KEYED_SALT), value)[:8], 16) % candidate_count`, then the "index with a hole" step (`transforms/_codeset_index.py:98`, `:111`) skips the input's own position. `hmac_hex` (`internal/crypto.py:44`) encodes the value with `errors="replace"`.

Where it runs today:

| Route | Code | Shape |
|---|---|---|
| pandas full frame | `execution/_strategies/_code_set.py:206` (loop in `CodeSetHandler.run`, `:142`) | one `apply_code_set` call per row; each call re-runs `derive` (HKDF plus HMAC) for the key |
| chunked | the same handler per chunk (admission: `execution/_chunked.py:224` calls `execution/_chunked_code_set.py:91` `code_set_conditional_failures`: mask mode, no `chapter_preserve`) | per row, per chunk |
| nested (`_nested_leaves`) | `NestedStrategyHandler` dispatches the same handler | per row |
| sequential (non-key column) | the same handler | per row |
| out-of-core | `execution/out_of_core/_mask_group_c.py:384` `code_set_map` (`kernel/_code_set.py`) | once per distinct value, then `pc.take`; but `to_pylist` and a Python `str()` pass over every row first, and the `_select` closure re-derives the key per distinct value |
| unified slice | not admitted: no `OperatorSpec` for `code_set` (`execution/_operator_registry.py`) | - |

Measured on the Dell, 120,000 rows over the shipped `icd10` corpus (65 rows), companion irrelevant:

| Path | Per row |
|---|---|
| `CodeSetHandler` per row (oracle) | 21 to 23 us |
| `code_set_map` (out-of-core today) | 1.05 to 1.16 us, almost all `to_pylist` and `str()` |
| Arrow front: `dictionary_encode` on the Arrow array, select per distinct, `pc.take` | 34 to 58 ns |
| one `select` per distinct value, as written (re-derives the key) | 14 to 24 us per distinct |
| the HMAC alone with the key hoisted | 2.7 to 4.6 us per distinct |

All outputs were equal. These numbers cover the Arrow front only, not the handler's object-to-Arrow conversion and object-column rebuild; S1 measures the handler end to end (AT-8). The cost model is `rows x (conversion + 50 ns) + distinct x (HMAC + lookup)`. A Rust HMAC kernel would cut the second term by about 10x, which matters only when distinct is close to rows. Code columns are bounded vocabularies (ICD-10-CM has about 74,000 codes), so Arrow wins on cost per line of new code.

No existing compiled kernel computes `HMAC(derive(K, ns, salt), value)`: `derive_hex_raw_batch` (`decoy-engine-native/src/arrow_ffi.rs:436`) computes `derive(K, ns, value)`, which frames the namespace into the message. Using it would change every code_set output. Section 10 records this as the rejected alternative.

## 2. Established solutions

Search run: dictionary encoding as a compute pattern (Apache Arrow `dictionary_encode`, Parquet dictionary pages, DuckDB dictionary vectors, Polars categorical `map` on categories), and keyed pseudonymization over a lookup domain (NIST SP 800-188 de-identification, HMAC-based pseudonym tables).

- Arrow, Parquet, DuckDB and Polars all compute a pure function of a low-cardinality column once per dictionary entry, then expand by index. The engine already follows this in `kernel/_code_set.py` (B6). This row moves that one helper to an Arrow front and calls it on every route.
- Keyed pseudonymization with HMAC over a fixed domain is the standard (NIST SP 800-188 section on pseudonymization; the engine's DE-02 decision). The selection formula does not change.
- The HMAC call stays `hmac_hex`, not `hmac.digest`: it fixes the `errors="replace"` encoding, so bytes cannot drift on a lone surrogate, and it keeps the draw token the draw-site catalogue resolves (section 6.2). The per-distinct HMAC cost (a few us) is not the bottleneck.

### Reuse inventory

- `kernel/_code_set.py` `code_set_map`: the one per-distinct helper. Extended, not copied.
- `transforms/code_set.py` `resolve_corpus_record`, `_pick_mask`, `_apply_chapter_preserve`, `_pick_from_seq`, `hole_candidate_count`, `hole_resolve`, `describe_loaded_corpus`: the selection math and every raise site stay where they are. The new selector calls them.
- `_opaque.OpaqueBox`: holds the hoisted derived key, so no frame keeps it as raw bytes.
- `execution/_chunked_code_set.py`: `resolve_pinned_code_set_records` (`:265`), `code_set_conditional_failures` (`:91`, non-raising), `aggregate_chunk_code_set_corpora` (`:299`). The new evidence helper goes here too (section 5.5).
- `execution/native/_operator_config_rejections.py`: the one config-rejection choke point shared by the compiler (`_config_gate_rejection`, `execution/native/_requirements.py:496`) and `native_route_eligibility`.
- `execution/native/protocol/providers_mask.py:105` `CodeSetKeyedSelectProvider`: an independent reproduction of the selection formula. AT-1 uses it as a second oracle.
- `OperatorSpec` and the operator step (`execution/native/_operator_step.py`): reused for the new operator.

## 3. Guarantee and non-goals

After this row:

1. On every route, mask-mode `code_set` selects once per distinct non-null value per selector build. The derived HMAC key is computed once per selector build: once per handler call (a frame or a chunk), once per out-of-core batch, once per native step call. It is never computed per row or per distinct value. The output is byte-identical to today's per-row oracle for every value, null and type. With `chapter_preserve`, per-value errors give the same `RowError` list, in the same row order, and keep the original value in place.
2. A string or large_string Arrow source is never turned into a Python list for the encode step.
3. `code_set` has a native operator (S2a, S2b). On the unified slice and the chunked native step it runs as `arrow_python`. Admission: mask mode, no `chapter_preserve`, string source. FK keys and `when:` are already declined on those routes (section 4). The `code_set_corpora` evidence is the same as today.
4. One mechanism: the handler, the chunked oracle leg, the out-of-core path and the native operator all call `code_set_map` with one selector type. One evidence helper builds every `code_set_corpora` entry.
5. The derived key is never raw bytes in a frame. The secret-material census proves it: every census row this row adds or moves has the verdict `boxed` or `wiped` (section 6.2).
6. No error message on any code_set path carries a source value, a corpus code or a value-derived chapter (V1 fix; AT-5).

Non-goals: a native tenant on the sequential FK route (it keeps the handler, which S1 already makes per distinct); gen mode (`_pick_gen`, keyed on row index; it keeps its per-row loop and is named on the run card as Python); a Rust kernel (section 10); `chapter_preserve` on native routes (per-value errors are not modeled there, as on the chunked route today); new corpora; merging the two existing `code_set_corpora` aggregators (section 13).

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | null cell | null in place, no selection |
| E2 | value in corpus | candidate count `n - 1`, hole skip |
| E3 | value not in corpus | candidate count `n` |
| E4 | single-row corpus and the value equals its code | `CODE_SET_SINGLE_ROW_CORPUS`, job-fatal, raised in `_pick_mask` (`transforms/code_set.py:478-485`). S1 makes the message value-free |
| E5 | `chapter_preserve`, chapter absent or sole-member bucket | per-value `RowError` for every row with that value; original value kept (handler routes only; codes in `execution/_strategies/_code_set.py:93` `_PER_VALUE_CODE_SET_ERRORS`; raised at `transforms/code_set.py:408-417` and `:427-434`). S1 makes both messages value-free |
| E6 | any other `PlanCompileError` from the selector | job-fatal, as today |
| E7 | empty frame | `pd.array([], dtype="string")`, as today |
| E8 | out-of-core sees a per-value code | `OUT_OF_CORE_CODE_SET_ROW_ERROR_UNREACHABLE`, as today (`execution/out_of_core/_mask_group_c.py:386-395`) |
| E9 | the object column cannot become an Arrow string array (a lone surrogate, only from the in-memory DataFrame API) | the handler falls back to the per-distinct dict path over the same `str()` forms (section 5.3); same bytes as today; no conversion exception is kept |
| E10 | the native step sees a per-value code (unreachable: admission excludes `chapter_preserve`) | the step passes no `on_error`, so the value-free `PlanCompileError` propagates and the job fails; no raw value is written (section 5.4) |

### Routes

| Route | After |
|---|---|
| pandas full frame | `CodeSetHandler.run` calls `code_set_map` (S1) |
| chunked oracle leg | same handler (S1) |
| nested (`_nested_leaves`) | same handler (S1) |
| sequential (non-key column) | same handler (S1). Not a native tenant: `execution/_sequential_native_ops.py` admits strategies through its own hand-written `_<strategy>_admit`/`_apply` pairs, not `OPERATORS` (V2-LOG, section 13) |
| out-of-core | `code_set_map` with the Arrow front and one selector per batch (S1) |
| unified slice | new `native_code_set` operator (S2a) |
| chunked native step | same operator (S2b) |

### Codes

No new failure codes. Native declines reuse existing texts: `code_set_conditional_failures` gives the mode and `chapter_preserve` reasons; a non-string source declines on `unified_resident_types`. E10 reuses the per-value code itself: it is already job-fatal and value-free after S1, and a new wrapper code would add one producer row and one consumer row for a path that admission makes unreachable. Dennis round 1 asked for a guard "like `OUT_OF_CORE_CODE_SET_ROW_ERROR_UNREACHABLE`"; the guard here is the absent `on_error` plus AT-7 and M9, not a new code. S2a removes `code_set` from the `no_native_operator` family in ROUTE-LABEL-TRUTH's `KERNEL_LESS_FAMILY` if that plan has merged (not on main at `9f7bb1f4a`).

### FK shapes

- A code_set column on a table with any profile relationship: the unified slice declines the whole table (`execution/_unified_slice_admission.py:258`). The chunked route refuses a code_set FK key in both orientations (`reject_code_set_fk_keys`, `execution/_chunked_code_set.py:225`); that check stays where it is.
- A code_set column that is not a key: no FK interaction.

### `when:`

`code_set` is not in `ADMITTED_WHEN_STRATEGIES` (`execution/native/_when_admission.py:45`), so a gated code_set column declines natively and runs on the oracle. The chunked route keeps `reject_code_set_when` (`execution/_chunked_code_set.py:186`).

### Fields

| Field | Values | Handling |
|---|---|---|
| `code_set` | a shipped corpus or an override path | `resolve_corpus_record`, pinned once per table |
| `mode` | `mask`, `gen` | mask: this row; gen: unchanged per-row loop |
| `chapter_preserve` | true, false | true: per-distinct selection with per-value errors (handler routes); native declines |
| `namespace` | set or absent | absent uses `"code_set"`, as today |
| `corpus_source_version` | set or absent | pin check unchanged |

### Output surfaces

| Surface | Change |
|---|---|
| masked column | none: byte-identical, same pandas dtype; empty stays Arrow `string`, non-empty all-null stays Arrow `null` |
| `row_errors` | same entries, same order, same value-free reasons |
| raised messages | E4 and E5 lose the value and the value-derived chapter (V1 fix) |
| `quality_metrics["code_set_corpora"]` | same entries; also present on the unified slice and chunked native step |
| route evidence and run card | `arrow_python` on the native operator |
| `docs/execution-backends.md` (`:77`, `:97`, `:203`, `:214-219`) | code_set rows name Arrow per distinct and the native operator; gen mode stays Python |

## 5. Design notes

Principles that apply: one place per fact (the selection math and its raise sites stay in `transforms/code_set.py`; the dedupe stays in `kernel/_code_set.py`; config rejection stays in `_operator_config_rejections.py`; one evidence helper); dependency direction (`kernel/` takes the selector and the error predicate as callables and imports neither `transforms/` nor `execution/`; `.importlinter` keeps `execution : kernel` independent). Established pattern: dictionary-encode and map (section 2). House style: no flag argument switches behavior; `on_error` is a predicate the caller passes, not a mode flag.

### 5.1 The selector

`CodeSetSelector` in `transforms/code_set.py`, built once per selector build from `(record, mask_key, namespace, chapter_preserve)`:

- `__init__(self, record, *, mask_key: bytes, namespace, chapter_preserve)` computes `OpaqueBox(derive(mask_key, namespace or "code_set", _KEYED_SALT))` in one expression and stores only the box. Its body is a `try` whose `except BaseException:` deletes `mask_key` and re-raises, and it deletes `mask_key` on the normal exit too (census verdict `wiped`).
- `select(value: str) -> str`: without `chapter_preserve` it calls `_pick_mask(value, record, hmac_key=self._box)`; with it, `_apply_chapter_preserve(..., hmac_key=self._box)`. Both keep their raise sites and codes in place.
- `_pick_from_seq(key_value, seq, position, candidate_count, *, hmac_key: OpaqueBox)` opens the box inside the `hmac_hex(...)` call expression. No function derives a key per value any more.
- `_pick_mask` and the mask branch of `_apply_chapter_preserve` take `hmac_key: OpaqueBox` instead of raw key bytes. `_apply_chapter_preserve` keeps `job_seed` for its gen branch only.
- `apply_code_set` keeps its signature. In mask mode it builds a `CodeSetSelector` for the one value; gen mode is unchanged.
- The three raise messages (E4, chapter absent, sole-member bucket) become value-free: code, path and fixed advice only. No `value`, no `input_chapter` (derived from the value), no corpus code.

### 5.2 `code_set_map`

`code_set_map(values, select, *, on_error: Callable[[BaseException], bool] | None = None) -> CodeSetMapResult`, where `CodeSetMapResult` has `out: pa.Array` and `failed_rows: pa.BooleanArray | None`:

- A `pa.ChunkedArray` is combined first (`combine_chunks()`; a zero-chunk array gives an empty array of its type), because a dictionary-encoded ChunkedArray has no single `.dictionary`.
- `pa.string()` or `pa.large_string()` input: `dictionary_encode()` directly. No `to_pylist`.
- Any other Arrow type: today's `str()` coercion (keeps the oracle's spelling of non-strings).
- `select` runs once per dictionary entry. When `on_error` is given and returns true for a raised exception, that dictionary index is marked failed and its output is null. The kernel keeps only the failed index set; no exception object, traceback or `__context__` survives the loop. Any other exception propagates unchanged.
- `out = pc.take(mapped, indices)`; `failed_rows` is the take of the failed-index mask, or `None` when `on_error` is `None`.
- `code_set_map_strings(keys: list[str | None], select, *, on_error=None) -> CodeSetMapResult` runs the same dedupe over a list of `str()` forms with a dict, for the E9 fallback only. Both functions share one inner loop.

The out-of-core caller reads `.out` and keeps its own guard (`_mask_group_c.py:386-395`); its `_select` closure is replaced by `CodeSetSelector(...).select`.

### 5.3 Handler

`CodeSetHandler.run`, mask mode:

1. Build one `CodeSetSelector` per call.
2. Build the keys from the same `str()` forms today's loop uses, iterating the Series (a datetime64 cell gives `str(Timestamp)`, never `astype(str)`). Dedupe is on the string form, not Python equality, because `1`, `1.0` and `True` hash equal but print differently. Try `pa.array(keys, type=pa.string())`.
3. If the conversion raises (`UnicodeEncodeError` or `pa.ArrowException`), the `except` clause binds no name and only sets a flag. `code_set_map_strings` runs after the `except` block, so a later job-fatal raise has no `__context__` that holds part of the value (recurring class 3).
4. `on_error` is a module-level predicate in `execution/_strategies/_code_set.py`, `_is_per_value_code_set_error(exc)`: true only for a `PlanCompileError` whose code is in `_PER_VALUE_CODE_SET_ERRORS`. The handler passes it only when `chapter_preserve` is set.
5. Rebuild the column as today's object column: nulls stay as the source null (today's `isna()` mask), failed rows keep their original object and get one `RowError` each, in row order, with today's reason (`code_set could not mask this value (<code>)`). `masked_any` and the evidence follow section 5.5.

Gen mode keeps the existing loop.

### 5.4 Native operator

`OperatorSpec(strategy="code_set", operator_id="native_code_set", shape="kernel", planned_backend=ARROW_PYTHON, required_kernel=None, positive_kernel_evidence=False, unified_resident_types=frozenset({pa.string(), pa.large_string()}), full_frame_assembly="string_on_empty", routed_diagnostics=frozenset({"reduce_row_error:mask_error"}))`.

- Assembly: the handler gives Arrow `string` for an empty column (`pd.array([], dtype="string")`) and Arrow `null` for a non-empty all-null column (an object column of `None`); both were checked with `pa.Table.from_pandas`. No existing `AssemblyShape` (`execution/_operator_registry.py:56`) matches: `tokenizing` gives `float64` on empty, `null_on_empty` gives `null` on empty, and `type_preserving` keeps `string` on all-null. S2a adds the literal `"string_on_empty"` and one branch in `assemble_column` (`execution/physical/_shadow_assembly.py:54`): empty keeps `string`, all-null gives `null`. AT-6 pins both cases.
- Diagnostics: `code_set` declares `row_error_modes=("mask_error",)` (`execution/native/_capabilities.py:213-221`), which becomes the obligation `reduce_row_error:mask_error` (`execution/native/_requirements.py:404-408`). The unified slice admits a node only when its obligations are a subset of `routed_diagnostics` (`execution/_unified_slice_admission.py:141-153`). Routing it is honest for the admitted shape: `mask_error` comes only from the `chapter_preserve` codes, admission excludes `chapter_preserve`, and the step cannot write a raw value in place of a failed one (next point). The capability stays declared, so the oracle route keeps its quarantine.
- Fail-closed guard: the step calls `code_set_map` with no `on_error`. A per-value `PlanCompileError` therefore propagates job-fatal with its value-free message, and no row keeps its original value. This is the same outcome as the out-of-core guard. The step does not wrap the error or read `exc.code`, so no consumer site is added. AT-7 forces a per-value raise through the step and asserts a job failure with no raw value in any output.
- Admission: S2a adds `code_set_config_rejection(name, provider_config) -> str | None` to `execution/native/_operator_config_rejections.py`, built on the non-raising `code_set_conditional_failures`. It returns a decline string and never raises. One dispatch entry in `_config_gate_rejection` (`execution/native/_requirements.py:496`). The chunked raisers (`reject_code_set_fk_keys`, `reject_code_set_when`, `reject_unsafe_code_set_chunk_schema`) are not called from native admission: they raise chunked-route `PlanCompileError`s and would turn an oracle-runnable job into a failure.
- Params: `CodeSetParams(record, namespace)`. `resolve_operator_params` (`execution/native/_operator_params.py:198`) and `resolve_params_by_column` (`:327`) take the pinned record the way they take `prepared_categorical`. The unified slice pins with `resolve_pinned_code_set_records` before its empty-input return, so a zero-row table with a bad corpus fails with the oracle's code. `_bound_params` in `execution/physical/_shadow_operators.py:180` gets one `code_set` branch.
- Step: one branch in `run_kernel_step` (`execution/native/_operator_step.py:303`) that builds the selector from the `mask_key` the function already takes (an existing census row) and calls `code_set_map`. No new function takes key bytes. `_operator_step.py` goes from 569 to about 580 lines.

The registry-derived tables (unified-slice admission and evidence, `_shadow_bindings`, `_real_type_admission`, `_chunked_evidence`, `_requirements`) pick up the new spec. `tests/native/test_operator_tables_snapshot.py` holds a literal snapshot of those tables; S2a updates its literals and lists each changed table in the PR. That file is a behavior snapshot, not a ratchet or allowlist.

### 5.5 Evidence

One helper, `code_set_evidence_entry(code_cfg, record, *, table, column) -> dict`, in `execution/_chunked_code_set.py`: `{**describe_loaded_corpus(code_cfg, record=record), "table": table, "column": column}`. Callers:

- the handler, when `masked_any` (replaces its inline dict);
- the out-of-core stamp (`execution/out_of_core/_stream_driver_support.py:181`, replaces its inline dict);
- the unified slice: for each admitted code_set node whose source column has a non-null value, it adds the entry to `quality_metrics["code_set_corpora"]` (built at `execution/_unified_slice.py:309-350`). For the admitted shape every non-null value is masked, so "has a non-null value" is exactly the handler's `masked_any`;
- the chunked native step: per chunk, the same rule, written into the chunk `ExecutionResult.quality_metrics`, then folded by the existing aggregators (`aggregate_chunk_code_set_corpora`; `fold_corpora` at `execution/_chunked_output_sink.py:200`). No third aggregator.

### 5.6 Public signatures

Engine #763 sentry: `apply_code_set` keeps its signature; `CodeSetSelector` is a new name (additive); `code_set_map` and `code_set_map_strings` are in the private `kernel/_code_set.py`; `_pick_mask`, `_pick_from_seq` and `_apply_chapter_preserve` are private. If a builder changes a public signature, the changelog fragment needs a `Breaking:` line or the sentry fails.

### 5.7 Sibling plans

FPE-CHECKSUM-NATIVE (adds `checksum_schemes` with a default to `OperatorSpec`), BUCKET-TOPCODE-NATIVE (new specs) and TEXT-REDACT-RUST-SPLICE (registry and `_operator_step.py`) touch the same files. This row adds no Rust and no companion ABI change. Its registry, step, config-rejection and snapshot edits are separate entries, so merge order is free and a later slice only resolves an adjacent-line conflict. `_requirements.py` has 22 lines of headroom (655 of 677) shared by all four rows; this row uses about 3.

## 6. Placement

### 6.1 Files

No new module. Fan-out freezes (`tests/sentry/baselines/package-fanout.json`): `execution/native` at 55, `execution/_strategies` at 29, `execution` at 103; `transforms/` is at the 25-module cap. Tests go in existing directories: `tests/unit/transforms/test_code_set_selector.py`, `tests/unit/kernel/test_code_set_map.py`, `tests/unit/execution/native/test_native_code_set.py`.

| File | Lines now | Ceiling | Slice and change |
|---|---|---|---|
| `transforms/code_set.py` | 569 | 600 (GOAL) | S1: `CodeSetSelector` (about +35), key change in `_pick_from_seq`, `_pick_mask`, `_apply_chapter_preserve` (net about -5), messages (net 0). Must stay at or under 600; if not, S1 moves the gen-mode helpers to `transforms/_codeset_index.py` (122 lines) rather than add a size entry |
| `kernel/_code_set.py` | 44 | 600 | S1: Arrow front, `on_error`, result type, `code_set_map_strings` (about +60) |
| `execution/_strategies/_code_set.py` | 283 | 600 | S1: handler body, predicate (net about +10) |
| `execution/out_of_core/_mask_group_c.py` | 544 | 600 | S1: selector in place of `_select` (net about -5) |
| `execution/out_of_core/_stream_driver_support.py` | 264 | 600 | S1: evidence helper call (net about 0) |
| `execution/_chunked_code_set.py` | 315 | 600 | S1: `code_set_evidence_entry` (about +12) |
| `execution/_operator_registry.py` | 312 | 600 | S2a: spec and `AssemblyShape` literal (about +14) |
| `execution/physical/_shadow_assembly.py` | 161 | 600 | S2a: `string_on_empty` branch (about +5) |
| `execution/native/_operator_config_rejections.py` | 324 | 600 | S2a: `code_set_config_rejection` (about +12) |
| `execution/native/_requirements.py` | 655 | 677 (dense entry) | S2a: dispatch (about +3) |
| `execution/native/_operator_params.py` | 358 | 600 | S2a: `CodeSetParams`, pinned-record parameter (about +25) |
| `execution/native/_operator_step.py` | 569 | 600 | S2a: one branch (about +11) |
| `execution/physical/_shadow_operators.py` | 437 | 600 | S2a: one `_bound_params` branch (about +6) |
| `execution/_unified_slice.py` | 473 | 600 | S2a: pin before empty return, evidence (about +12) |
| `execution/native/_chunked_entry.py` | 688 | 689 (dense entry) | S2b: the first commit moves `_native_chunk_result` (`:179-221`) unchanged into `execution/native/_chunked_evidence.py`; later edits only pass `code_set_corpora` through. Net shrink; no ceiling change |
| `execution/native/_chunked_evidence.py` | 292 | 600 | S2b: receives `_native_chunk_result`, merges `code_set_corpora` (about +50) |
| `execution/native/_chunk_masking.py` | 447 | 600 | S2b: pinned params for the chunked step, per-chunk evidence rule (about +15) |
| `execution/native/_chunked_schema_rule.py` | 363 | 600 | S2b: code_set entry in the string-pin list (about +4) |
| `tests/native/test_operator_tables_snapshot.py` | - | - | S2a: snapshot literals |
| `docs/execution-backends.md` | - | - | S2a: route table rows |

### 6.2 Pinned surfaces: what moves and what does not

| Surface | Delta | How |
|---|---|---|
| secret-material census (live `tests/sentry/secret_material_census.json`; ratchet baseline `tests/sentry/baselines/secret-material-census.json`; registry `scripts/dev/sentry_registry.toml:28`) | 1 key moves, 2 keys go, 0 keys grow | `transforms/code_set.py::CodeSetSelector.__init__::mask_key` is new, with `moved_from: decoy_engine/transforms/code_set.py::_pick_from_seq::mask_key` (same bound name; the old site is gone because `_pick_from_seq` now takes an `OpaqueBox`, which the census does not track: `scripts/secret_material_census.py:267` tracks only parameters annotated bytes-like or not annotated). The census sentry is in `REHOME_BY_BINDING`, so `tests/sentry/ratchet/_rehome.py` accepts the move. `_pick_mask::mask_key` and `_code_set_array._select::job_seed` disappear (shrink). `apply_code_set::job_seed`, `_apply_chapter_preserve::job_seed`, `_pick_gen::job_seed`, `_code_set_array::job_seed` and `run_kernel_step::mask_key` stay. S1 runs `scripts/secret_material_census.py --write`, checks the new row's verdict is `wiped`, and edits the ratchet baseline only for the move and the two removals |
| draw-site catalogue (`execution/native/_draw_sites_mask.py:186-202`; digests in `tests/native/test_draw_sites_catalogue_pinned.py`) | none | `call_site` stays `transforms/code_set.py::_pick_from_seq`, which keeps its `hmac_hex(` draw token (`ENTRY_DRAW_TOKEN`, `tests/native/test_draw_site_inventory_coverage.py:359`). The `seed_derivation` text still describes the formula. No re-pin |
| f29 producer inventory (`tests/fixtures/f29/producer-inventory.json`; baseline `tests/sentry/baselines/f29-producer-inventory.json`) | none | every raise stays in `_pick_mask` and `_apply_chapter_preserve`; keys hold the code, not the message |
| f29 consumer inventory (baseline `tests/sentry/baselines/f29-consumer-inventory.json`) | none | the baseline is derived from a frozen fixture (`tests/sentry/_reason_baseline.py:1-7`), not from live source. The handler's `exc.code` read moves from `CodeSetHandler.run` into `_is_per_value_code_set_error` in the same module; the out-of-core read in `_code_set_array` stays. S1 does not edit the fixture or the baseline. The native step reads no `exc.code` |
| module size (`tests/sentry/test_module_size.py`) | none | section 6.1; `_chunked_entry.py` shrinks |
| package fan-out | none | no new module |
| operator-table snapshot | literals change | behavior snapshot, not a ratchet |

No sentry list, census or baseline grows, so no owner question is needed for growth. If a builder finds a delta not in this table, the slice stops and files a question in the vault `OWNER-QUESTIONS.md` with options and a recommended answer.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | `RowError` reasons, E4 and E5 messages, conversion errors | reasons carry the code only; the three messages lose the value and chapter; the E9 fallback binds no exception | AT-5 | M7, M8 |
| 2 | Cleanup missing on an exit path | none | N/A: no resource is acquired | n/a | n/a |
| 3 | State and concurrency | the hoisted key and the pinned record are per selector build and per table | selector built once per handler call, batch or step; record pinned before the first chunk, as today | AT-3, AT-9 | M5 |
| 4 | Route parity and silent fallback | seven routes | one `code_set_map` and one selector on all of them; native declines carry a registered reason | AT-1, AT-6, AT-7 | M2 |
| 5 | Referential integrity | code_set on an FK key | unified slice declines any table with relationships; chunked keeps its two-orientation refusal | AT-7 | drop the relationships decline for a code_set table (AT-7 red) |
| 6 | Untrusted producer | an override corpus file | existing schema and version checks; unchanged | existing corpus tests | n/a |
| 7 | Check then use | the corpus file | the record is read once and pinned; the selector never reopens the file | AT-3, AT-9 | M5 |
| 8 | Weak tests | AT-1 equality passes before the change | AT-2 (no `to_pylist`, one derive per build) and AT-8 (speed) carry the fail-before | AT-2, AT-8 | M4 |
| 9 | Refactor drift | the key now travels boxed | golden outputs captured before S1, plus the protocol provider as a second oracle | AT-1 | M1 |
| 10 | Frozen contract drift | the compatibility contract freezes code_set output | no byte change | AT-1 | M1 |
| 11 | Silent route claim | `routed_diagnostics` on the native operator | the step passes no `on_error`, so a per-value code fails the job | AT-7 | M9 |
| 12 | Evidence loss | native routes | one evidence helper, existing aggregators | AT-6 | M6 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no new validation | - |
| 2 | Strict wire and stored types | no new persisted model | - |
| 3 | No exception context | yes: selector errors, the kernel's `on_error` loop and the E9 fallback must not keep the key or value | AT-5 (d) |
| 4 | Versioned read models | the corpus `source_version` pin, unchanged | existing tests |
| 5 | Normalized guard scanners | no new scanner | - |
| 6 | No reaching into private modules | the native step imports the public `CodeSetSelector` from `transforms.code_set`; `_chunked_code_set` is a sibling module inside `execution` | review |
| 7 | No hidden CI failures | AT-8 is under the `perf` marker, which runs in the default gate (`pyproject.toml:401-402`), so it uses a ratio, not an absolute time | AT-8 |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M9 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | census rehome and draw-site resolution | section 6.2; census and draw-site sentries in T2 |
| 11 | No raised caps | module size, fan-out freezes | section 6.1: no ceiling or freeze changes |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity: outputs of today's per-row oracle, captured on the S1 base head before the change, for icd10 and one more shipped corpus: values in and out of corpus; `None`, `NaN` and `pd.NA` in one object column; `1`, `1.0`, `True` and `"1"` in one object column; a float column; an Int64 column with `pd.NA`; a boolean extension column; a category column; a datetime64 column (pins `str(Timestamp)`); a non-empty all-null object column (no evidence entry); a zero-row frame; a zero-chunk `ChunkedArray` on `code_set_map`; a lone-surrogate cell (in-memory DataFrame only); the nested `_nested_leaves` route; `chapter_preserve` true and false; two namespaces and the absent namespace. Every handler route gives the same values and pandas dtype. The selector also agrees with `CodeSetKeyedSelectProvider` on every string input | passes before (guard); the fail-before is AT-2 | S1 |
| AT-2 | Instrumented: for a string source, `to_pylist` is not called, and `derive` is called once per handler call (spy) and once per out-of-core batch | per-row `derive` today | S1 |
| AT-3 | Pinning on the handler and the chunked oracle leg: replacing the override corpus file between chunks changes neither the output nor the evidence | passes today; guards the selector build site | S1 |
| AT-4 | `chapter_preserve` errors: the `RowError` list equals today's, same order, original values kept, including a value repeated across rows | passes today; guards `on_error` | S1 |
| AT-5 | Value-free errors: (a) a one-row customer corpus and an input equal to its code raise E4 with neither the value nor the code in `str(exc)`; (b) chapter-absent and sole-member raises carry no value or chapter in `str(exc)`; (c) `RowError.reason` carries no value; (d) `__cause__` and `__context__` are None on E4 and per-value errors, including an E4 raised after the E9 fallback | (a) and (b) fail today (`transforms/code_set.py:412-413`, `:431-432`, `:482`) | S1 |
| AT-6 | Native operator: the unified slice (S2a) and the chunked native step (S2b) admit mask-mode string code_set; outputs equal the AT-1 goldens; executed backend `arrow_python`; `code_set_corpora` equals the full-frame run, including a non-empty all-null column (null column, no entry) and a zero-row table (string column, no entry) | no operator today | S2a, S2b |
| AT-7 | Native refusals and guard: gen mode, `chapter_preserve`, a non-string source, a `when:` gate and a table with relationships each decline with their registered reason, and the column runs on the oracle with AT-1 values; a zero-row unified-slice table with a bad corpus fails with the oracle's code; a per-value raise forced inside the native step (monkeypatched selector) fails the job and writes no raw value | no operator today | S2a |
| AT-8 | Speed, `perf`: 200,000 rows, 5,000 distinct codes, object column, through `CodeSetHandler.run` end to end; at least 20x faster than the per-row oracle on the same sample in the same process. S1 records the measured ratio and the Dell per-row number in the PR | about 1x today | S1 |
| AT-9 | Chunked native pinning: replacing the override corpus file between chunks of the chunked native step changes neither the output nor the evidence (params pinned once) | no operator today | S2b |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | `hole_resolve` uses `idx > position` instead of `idx < position` | AT-1 |
| M2 | the native step dedupes on the raw Python value instead of the `str()` form | AT-1, AT-6 |
| M3 | `on_error` marks the first row only, not every row with that value | AT-4 |
| M4 | the handler calls `to_pylist` before encoding | AT-2 |
| M5 | the selector re-resolves the record per batch or chunk | AT-3, AT-9 |
| M6 | native routes drop the evidence helper call | AT-6 |
| M7 | put `{value!r}` back into the E4 message | AT-5 (a) |
| M8 | bind the E9 conversion exception and run the fallback inside the `except` block | AT-5 (d) |
| M9 | the native step passes `on_error=lambda exc: True` | AT-7 (guard case) |

## 10. Frozen contracts

- Masked code_set output is frozen by the compatibility contract. This row keeps it.
- Error message text is not frozen; only codes are. The E4 and E5 message change is a fix.
- Rejected alternative, recorded for the owner: route code_set through `derive_index_batch` (native, threaded, and moved to CMAC by NATIVE-THREADS-DEFAULT S3). It would change every code_set output and break joins with earlier runs, for a speed gain only at near-unique cardinality. Not proposed. If a measured customer column shows distinct close to rows, a follow-up row can add it with a `Breaking:` line.

## 11. Pre-mortem

- An object column holding both `"1"` and `1` dedupes to one entry. It must, because both print as `"1"` and today's loop gives both the same output. AT-1 covers it.
- The Arrow conversion treats one of `pd.NA`, `NaN` and `None` as non-null. The handler keeps today's `isna()` mask and applies it after the take. AT-1 has all three.
- A lone surrogate fails strict UTF-8 conversion. E9 falls back to the dict path; `hmac_hex` encodes with `errors="replace"`, so the bytes match today. Arrow-read sources are valid UTF-8, so out-of-core and native routes never see one.
- A builder "optimizes" the non-string branch with `astype(str)`. Datetime and float spellings change. AT-1's datetime64 and float cells catch it.
- The hoisted key outlives the column. The selector is a local of the handler call, batch or step and is dropped at return; the key sits in an `OpaqueBox`.
- `routed_diagnostics` is set and a later change admits `chapter_preserve` natively. AT-7's guard case and M9 catch a step that writes raw values.
- S2a lands before PER-COLUMN-ROUTING and a mixed table still runs one route. S2a's gain then shows only on all-native tables; S1 already removes the per-row cost everywhere.

## 12. Slices

| Slice | Content | Size | Risk | Gate |
|---|---|---|---|---|
| S1 | `CodeSetSelector`; boxed key through `_pick_mask`, `_apply_chapter_preserve`, `_pick_from_seq`; value-free E4 and E5 messages; `code_set_map` Arrow front, `on_error`, `code_set_map_strings`; handler with E9 fallback; out-of-core selector; `code_set_evidence_entry` used by the handler and out-of-core; census rehome; AT-1 to AT-5, AT-8; M1, M3, M4, M5, M7, M8 | about 200 lines, 350 lines of tests; one builder-day | R2 | Codex and Dennis; T2 on code_set selection, census and draw-site sentries |
| S2a | `native_code_set` spec, `string_on_empty` assembly, `code_set_config_rejection` and dispatch, `CodeSetParams` and pinned-record parameter, `_bound_params` branch, step branch, unified-slice pinning and evidence, snapshot literals, `docs/execution-backends.md`; remove `code_set` from `no_native_operator` if present; AT-6 unified half, AT-7; M2, M6, M9 | about 150 lines, 250 lines of tests; one builder-day | R2 | Codex and Dennis |
| S2b | move `_native_chunk_result` to `_chunked_evidence.py` (pure move, first commit); chunked native step with pinned params, per-chunk evidence into the existing aggregators, schema-rule entry; AT-6 chunked half, AT-9; M5 on the native step | about 120 lines, 200 lines of tests; one builder-day | R2 | Codex and Dennis |

S2a depends on S1. S2b depends on S2a. All three fit before 2026-12-15. S2a works with or without ROUTE-LABEL-TRUTH.

## 13. Owner questions and deferred items

Q1 and Q3 are in the vault `OWNER-QUESTIONS.md` (2026-11-24, kind: default; the recommended choice applies if unanswered when S1 starts). Q2 is settled: the row is already a 1.0 row in `mask.md`. Revision 3 adds no question: section 6.2 shows no sentry list, census or baseline grows.

- Q1: Arrow per distinct (byte-identical) over a Rust kernel (byte change). Recommended: Arrow, per the measurement in section 1.
- Q3: gen-mode `code_set` stays per row and is named on the run card. Recommended: yes for V1; a later row can key it on the positional index kernel with a `Breaking:` line.

V2-LOG:

- A native code_set tenant on the sequential FK route (a `_code_set_admit`/`_apply` pair in `execution/_sequential_native_ops.py`); S1 already removes the per-row cost there.
- Two existing `code_set_corpora` aggregators with the same rule (`aggregate_chunk_code_set_corpora`, `execution/_chunked_code_set.py:299`, and `fold_corpora`, `execution/_chunked_output_sink.py:200`). Merge them in a later cleanup; this row adds no third.
