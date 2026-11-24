Status: plan (revision 4, 2026-11-24; Codex round 1 applied)

# CODE-SET-NATIVE: code_set masks once per distinct value over Arrow, on every route, and gets a native operator

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: CODE-SET-NATIVE, new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 76: "`code_set` | pandas | chunked pandas | no operator | none | Rust lookup over the pinned code list, 1 to 2 slices, 1.0.x"). The row is in the CLI roadmap `docs/roadmap/groups/mask.md` as a 1.0 row (owner 2026-11-22, V1 fast path). Engine only.

Source anchor: engine `3f0ae93c5`. Paths without a prefix start at `src/decoy_engine/`. Only the plan changed since `9f7bb1f4a`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `security.md` (keyed selection, secret material in frames), `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (keyed masking on every route; a new native operator; secret-derived key material). Plan review: Dennis (round 1 GO-WITH-FIXES, every V1 and design item applied in revision 3), then Codex (round 1 findings applied in revision 4). Code gate: Codex and Dennis.

Owner direction (2026-11-22): choose the fastest path by measurement and name every compatibility change. Start with Arrow per distinct value. The Dell timings estimate the component costs. AT-8 measures the full handler.

## 1. Frame

`code_set` remaps a code (for example, ICD-10 or MCC) to another real code from a pinned corpus. Mask mode (`transforms/code_set.py:465` `_pick_mask`, `:494` `_pick_from_seq`) is a pure function of the value: `idx = int(hmac_hex(derive(mask_key, namespace or "code_set", _KEYED_SALT), value)[:8], 16) % candidate_count`, then the "index with a hole" step (`transforms/_codeset_index.py:98`, `:111`) skips the input's own position. `hmac_hex` (`internal/crypto.py:44`) encodes the value with `errors="replace"`.

Where it runs today:

| Route | Code | Shape |
|---|---|---|
| pandas full frame | `execution/_strategies/_code_set.py:206` (loop in `CodeSetHandler.run`, `:142`) | one `apply_code_set` call per row; each call re-runs `derive` (HKDF plus HMAC) for the key |
| chunked | the same handler per chunk (admission: `execution/_chunked.py:224` calls `execution/_chunked_code_set.py:91` `code_set_conditional_failures`: mask mode, no `chapter_preserve`) | per row, per chunk |
| nested (`_nested_leaves`) | `NestedStrategyHandler` dispatches the same handler | per row |
| sequential (non-key column) | the same handler | per row |
| out-of-core | `execution/out_of_core/_mask_group_c.py:384` `code_set_map` (`kernel/_code_set.py`) | once per distinct value, then `pc.take`; but `to_pylist` and a Python `str()` pass over every row first, and the `_select` closure re-derives the key per distinct value |
| unified slice | not admitted: no `OperatorSpec` for `code_set` (`execution/_operator_registry.py`) | - |

Earlier Dell microbenchmark estimates, 120,000 rows over the shipped `icd10` corpus (65 rows), companion irrelevant:

| Path | Per row |
|---|---|
| `CodeSetHandler` per row (oracle) | 21 to 23 us |
| `code_set_map` (out-of-core today) | 1.05 to 1.16 us, almost all `to_pylist` and `str()` |
| Arrow front: `dictionary_encode` on the Arrow array, select per distinct, `pc.take` | 34 to 58 ns |
| one `select` per distinct value, as written (re-derives the key) | 14 to 24 us per distinct |
| the HMAC alone with the key hoisted | 2.7 to 4.6 us per distinct |

The text samples agreed. These numbers cover the Arrow front only, not the handler's object-to-Arrow conversion and pandas list assignment; S1 measures the handler end to end (AT-8). The cost model is `rows x (conversion + 50 ns) + distinct x (HMAC + lookup)`. A Rust HMAC kernel would cut the second term by about 10x, which matters only when distinct is close to rows. Code columns are bounded vocabularies (ICD-10-CM has about 74,000 codes), so Arrow wins on cost per line of new code.

No existing compiled kernel computes `HMAC(derive(K, ns, salt), value)`: `derive_hex_raw_batch` (`decoy-engine-native/src/arrow_ffi.rs:436`) computes `derive(K, ns, value)`, which frames the namespace into the message. Using it would change every code_set output. Section 10 records this as the rejected alternative.

The frozen reference is the full-frame pandas handler. On plain Arrow `int64 [1, null, 2]`, the old streaming map hashes `"1"` and `"2"`. The full frame hashes `"1.0"` and `"2.0"`. A null in a later batch can affect the first key. S1 corrects automatic routing and refuses an unsafe forced stream before it starts.

The 20x end-to-end gain is a target pending measurement. AT-8 retains it as a merge gate.

## 2. Established solutions

Search run: dictionary encoding as a compute pattern (Apache Arrow `dictionary_encode`, Parquet dictionary pages, DuckDB dictionary vectors, Polars categorical `map` on categories), and keyed pseudonymization over a lookup domain (NIST SP 800-188 de-identification, HMAC-based pseudonym tables).

- Arrow, Parquet, DuckDB and Polars all compute a pure function of a low-cardinality column once per dictionary entry, then expand by index. The engine already follows this in `kernel/_code_set.py` (B6). This row moves that one helper to an Arrow front and calls it on every route.
- Keyed pseudonymization with HMAC over a fixed domain is the standard (NIST SP 800-188 section on pseudonymization; the engine's DE-02 decision). The selection formula does not change.
- The HMAC call stays `hmac_hex`, not `hmac.digest`: it fixes the `errors="replace"` encoding, so bytes cannot drift on a lone surrogate, and it keeps the draw token the draw-site catalogue resolves (section 6.2). The per-distinct HMAC cost (a few us) is not the bottleneck.

### Reuse inventory

- `kernel/_code_set.py` `code_set_map`: the one per-distinct helper. Extended, not copied.
- `transforms/code_set.py` `resolve_corpus_record`, `_pick_mask`, `_apply_chapter_preserve`, `_pick_from_seq`, `hole_candidate_count`, `hole_resolve`, `describe_loaded_corpus`: the selection math and every raise site stay where they are. The new selector calls them.
- `_opaque.OpaqueBox`: holds the hoisted derived key between draws.
- `execution/_chunked_code_set.py`: `resolve_pinned_code_set_records` (`:265`), `code_set_conditional_failures` (`:91`, non-raising), `aggregate_chunk_code_set_corpora` (`:299`). The new evidence helper goes here too (section 5.5).
- `execution/native/_operator_config_rejections.py`: the one config-rejection choke point shared by the compiler (`_config_gate_rejection`, `execution/native/_requirements.py:496`) and `native_route_eligibility`.
- `execution/native/protocol/providers_mask.py:105` `CodeSetKeyedSelectProvider`: an independent reproduction of the selection formula. AT-1 uses it as a second oracle.
- `OperatorSpec` and the operator step (`execution/native/_operator_step.py`): reused for the new operator.

## 3. Guarantee and non-goals

After this row:

1. Freeze the full-frame oracle's keys, output values, pandas dtype and ordered row errors. Per frame, chunk, batch or native step, derive once and select once per distinct non-missing string key. E5 preserves the exact reason and original failed object at each position.
2. Encode Arrow string and large_string arrays directly. Materialize only dictionary entries before selection.
3. Native execution reports `arrow_python` for admitted mask-mode text. Section 5.4 gives the route gates. Section 5.5 defines evidence equality.
4. All routes use the exported kernel map and one selector. Bind the current config to its corpus record before the first draw, including empty inputs.
5. The selector stores an `OpaqueBox`. Open it inline with `.open()[0]`. Wipe tracked engine key parameters on exceptional exit. The box constructor and HMAC receive bytes during the call.
6. Keep data literals and secrets out of public error text. Publish only counts and safe provenance identifiers as corpus evidence.

Non-goals: a native tenant on the sequential FK route (it keeps the handler, which S1 already makes per distinct); gen mode (`_pick_gen`, keyed on row index; it keeps its per-row loop and is named on the run card as Python); a Rust kernel (section 10); `chapter_preserve` on native routes (per-value errors are not modeled there, as on the chunked route today); new corpora; merging the two existing `code_set_corpora` aggregators (section 13).

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | source mask marks a missing cell | exclude before stringification, append Python `None`, skip selection |
| E2 | value in corpus | candidate count `n - 1`, hole skip |
| E3 | value not in corpus | candidate count `n` |
| E4 | single-row corpus and the value equals its code | `CODE_SET_SINGLE_ROW_CORPUS`, job-fatal, raised in `_pick_mask` (`transforms/code_set.py:478-485`). S1 makes the message value-free |
| E5 | `chapter_preserve`, chapter absent or sole-member bucket | per-value `RowError` for every row with that value; original value kept (handler routes only; codes in `execution/_strategies/_code_set.py:93` `_PER_VALUE_CODE_SET_ERRORS`; raised at `transforms/code_set.py:408-417` and `:427-434`). S1 makes both messages value-free |
| E6 | any other `PlanCompileError` from the selector | job-fatal, as today |
| E7 | empty frame | assign `pd.array([], dtype="string")`. For a nonempty frame assign the completed list and let pandas infer the dtype |
| E8 | out-of-core sees a per-value code | `OUT_OF_CORE_CODE_SET_ROW_ERROR_UNREACHABLE`, as today (`execution/out_of_core/_mask_group_c.py:386-395`) |
| E9 | the object column cannot become an Arrow string array (a lone surrogate, only from the in-memory DataFrame API) | the handler falls back to the per-distinct dict path over the same `str()` forms (section 5.3); same bytes as today; no conversion exception is kept |
| E10 | admitted native selection raises | convert to a value-free fatal failure at the shared step. Propagate past unified retry. Abort chunked publication too (section 5.4) |

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

Keep registered reasons. Unified admission can silently decline and return the oracle outcome. Direct chunked preflight raises for an unsupported source, FK key or `when:`. Test each public entry point. E10 uses the registered reason for a known failure and fixed unexpected-error text otherwise. Update the `no_native_operator` family if ROUTE-LABEL-TRUTH has landed.

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
| masked column | full-frame keys and values. Empty output is Arrow string. Nonempty all-missing output is Arrow null. See section 5.4 for chunk boundaries |
| `row_errors` | same entries, same order, same value-free reasons |
| raised messages | fixed text for selection, version, stat and read failures. Keep registered reasons and safe structural paths |
| `quality_metrics["code_set_corpora"]` | safe evidence for each column with a successful mask. Compare by table and column across routes |
| route evidence and run card | `arrow_python` on the native operator |
| `docs/execution-backends.md` (`:77`, `:97`, `:203`, `:214-219`) | code_set rows name Arrow per distinct and the native operator; gen mode stays Python |

## 5. Design notes

Keep selection in `transforms/code_set.py` and mapping in `kernel/_code_set.py`. Export both map entry points and their result from `kernel/__init__.py`. The handler, out-of-core adapter and native step import the facade. Kernel takes callables and has no dependency on execution or transforms. The layer contract permits same-tier imports (`.importlinter:21`). Guard all three imports and run AT-2 on all callers.

### 5.1 The selector

Prepare `CodeSetSelector(config, *, corpus_record=None, mask_key: bytes, namespace=None)` once per build. Use one record-preparation operation in the transform. With no supplied record, resolve once under the caller's column file-access position. With a supplied record, check it against the current config with the existing version-pin validator. Return that exact object. Use this operation on both public scalar branches. In mask mode the selector owns preparation, so the scalar wrapper does not resolve or validate twice. Keep the scalar signature and mismatch checks (`transforms/code_set.py:312-332`).

Store the record and chapter policy. Inside a single outer wiping try, store `OpaqueBox(derive(mask_key, namespace or "code_set", _KEYED_SALT))` and delete the input key on normal exit. Delete it on exceptional exit before re-raising. Include preparation in that protection. The mask branches of `_pick_mask` and `_apply_chapter_preserve` pass the box to `_pick_from_seq`. Call `hmac_hex(hmac_key.open()[0], key_value)` there. Keep the prefix, modulus, hole position and UTF-8 replacement behavior. Keep `_pick_gen` and its row-index draw in place.

Give E4 and both E5 failures fixed advice. Keep the structural path and registered reason. Remove chapter and code literals. Apply the same rule in the loader. Pin mismatch omits both version strings. Stat and Parquet read errors omit raw exception text. Raise translated errors after leaving the handler. Preserve file-access policy, resource-error classification and handle cleanup. Use the policy-approved path display with URL credentials removed. Remove value interpolation from malformed version-pin and provenance-stamp diagnostics too. See `transforms/_codeset_loader.py:290-296`, `:337-349` and `:459-466`.

### 5.2 Mapping

`code_set_map(values, select, *, on_error=None)` returns a `CodeSetMapResult` with an Arrow string array `out` and an optional nullable string array `row_codes`. The callback returns the exact registered E5 code for a handled failure. A null return means re-raise. Without a callback all failures escape the map.

Combine a chunked array first, including the zero-chunk case. Dictionary-encode text directly. Use one selection loop over distinct keys in first-occurrence order. On success store the mapped value and a null reason. On handled failure store a null output and its code. Expand both with `pc.take` on the same indices. A source null yields two nulls. Keep exceptions out of the result. The E9 entry point `code_set_map_strings` builds indices with a Python dict and calls the same loop. Discard the conversion exception before selection. Only mapped values and reasons need to fit in Arrow there. If low-level callers pass a non-text Arrow array, keep the existing scalar coercion for that helper. Job routing must exclude that branch before streaming.

At out-of-core routing and direct preflight, require a known string or large_string source type for every code_set payload. Pass source types into the Group C compatibility check. Use the existing `is_text` predicate for the string/large_string domain in both the chunked and out-of-core checks. Reuse the existing out-of-core shape refusal. Unknown and non-text schemas decline before streaming. Automatic routing can then ingest the whole table through the oracle. Forced preflight refuses before scratch or sink writes. Both consult the same decision (`execution/out_of_core/_preflight.py:71-85`). Keep the low-level guard. Batch-local coercion cannot reproduce whole-frame ingestion.

Use the table's pinned record in each batch selector. A standalone call without a record resolves once at preparation. Return the map's output. For E8 raise the existing fixed error after leaving the handler. Preserve genuine corpus failures. Move the existing E5 set and its classifier to the public transform module. Return a code only for a PlanCompileError whose code belongs to that set. The handler and E8 guard share it. Keep the gen loop's existing reason text and use one handler builder for both gen and expanded mask row errors.

### 5.3 Handler

1. Pin under the existing context key, including `nested_outer_column`. Prepare the selector even for empty and all-missing input. Retain this record for evidence and repeat invocations.
2. Compute `source.isna()` first. For an Arrow-backed text Series with the same validity mask, pass its underlying Arrow array to the map. Otherwise iterate the original Series by position. Append a null key for each missing position. For every other cell use Python `str(value)`. Deduplicate those strings. This preserves pandas Timestamp and nullable-number spellings.
3. Try `pa.array(keys, type=pa.string())`. On Unicode or Arrow conversion failure, leave the exception handler before calling the E9 fallback. Catch only conversion failures here.
4. For chapter preservation supply the E5 classifier. Walk results in source order. Append Python `None` at missing positions. At failed positions append the original object, even if it is non-string. Emit one `RowError` with the original column, positional index, trigger and `code_set could not mask this value (<code>)`. Otherwise append the mapped string and set `masked_any`.
5. Assign the completed list directly for every nonempty result. For zero rows assign an explicit pandas string array. Keep the gen loop and quarantine behavior. See `execution/_strategies/_code_set.py:202-239` and `:272-282`.

### 5.4 Native operator

Register `native_code_set` as a kernel-shaped `arrow_python` operator. It needs no companion or positive compiled-kernel evidence. Declare string and large_string resident types, `string_on_empty` assembly and `reduce_row_error:mask_error`. Admission excludes both E5 conditions through the chapter gate. The diagnostic subset check is at `execution/_unified_slice_admission.py:479`.

**Admission.** Use one non-raising code_set predicate with a provider-config mapping as its only input. The native wrapper takes the column name to format the rejection. Keep the existing column-entry signature of `code_set_conditional_failures` as a thin adapter. Move its actual mode and chapter tests to the transform predicate, which accepts provider config. Native dispatch passes `cfg` to that predicate, and the chunked adapter passes `col_entry.get("provider_config") or {}`. Wire both `_requirements._config_gate_rejection` and `_plan._config_rejection` to it. Adapt the existing out-of-core mode and chapter checks to the same predicate. The owning transform exposes the config-shape check for route callers, so out-of-core has no dependency on native dispatch. Keep FK and predicate gates at their route boundaries. The chunked source-type list in `execution/native/_real_type_admission.py:59-67` is route-specific.

For a populated code_set target only, allow the cheap unified round trip from resident large_string to string when widening the reconstruction back proves identical values and nulls. Keep exact comparison on other columns and reject any changed value. Then apply the resident-type check (`execution/_unified_slice_admission.py:374-400`). S2a puts code_set in `CHUNKED_ROUTE_VETOED_STRATEGIES`. The dispatcher consults it before native binding (`execution/native/_dispatch.py:300-306`). Remove it only with the S2b wiring and tests.

**Binding and pinning.** Static `resolve_operator_params` at `execution/physical/_shadow_bindings.py:381-387` builds only a config descriptor with the effective namespace (`namespace or "code_set"`). Static compilation, explain and hashing perform no corpus I/O and serialize no rows. After resident admission succeeds, call `resolve_pinned_code_set_records` for the admitted table. It resolves each column under `fileaccess.at_position` (`execution/_chunked_code_set.py:283-296`). Pass this mapping on the runtime `ShadowContext`, keyed by (table, column). The batch runner passes the node identity to `run_operator`. Its `_bound_params` combines the descriptor with the exact record from this mapping before `run_kernel_step`. A missing runtime pin is fatal. Test identity at the executing step and evidence builder, including the synthesized empty batch. Use the same mapping for evidence. At the shared step prepare the selector from the bound config, record and existing mask-key parameter. Call the map without a recovery callback. Return `StepResult(out, None)` for Arrow Python work. Keep the physical plan immutable. The runner synthesizes one empty batch (`execution/physical/_shadow_batch_runner.py:98`). Pin before running it. Runtime coordinator callers executing this binding also prepare the pins before their first batch.

**Errors.** Use one typed fatal path for native code_set preparation and execution. In the shared step, protect the selector build and map, including empty inputs. In unified execution also protect post-admission resolution and runtime binding. Classify caught failures through the registered reason adapter. Create a fresh safe public error with the registered code and summary and a trusted structural path. Unknown exceptions get the fixed unexpected-error reason. Preserve the public corpus error class and code for ordinary domain failures, including E4 and bad pins. A runtime-only marker defined at the execution error boundary carries the sanitized error past the retry boundary. Raise after leaving the catch. Recognize the marker before the generic reroute in `execution/_unified_slice.py:362-377`. Raise its safe error outside the catch. The chunked entry delivers the same error and aborts. For already scrubbed file-policy and resource errors, preserve their required class and bypass retry as well. Propagate process interrupts normally. Never attach the caught exception or retry the oracle on this path.

**Assembly.** Both the physical assembler and final pandas overlay read the operator's assembly policy. In full-frame results a zero-row output gets pandas StringDtype before the final Arrow conversion. A nonempty all-missing output gets a list of Python None and becomes Arrow null. Compare final Arrow tables with `schema.equals(..., check_metadata=True)` as well as value equality (`execution/_unified_slice_evidence.py:203-225`).

**Chunked execution.** S2b gives `resolve_params_by_column` the existing preflight `state.code_set_records` and binds each column once before iteration. Use the same record for every chunk and evidence entry. In the native raw-chunk guard call `reject_unsafe_code_set_chunk_schema` on every chunk, including the first, before `cast_null_columns` or masking. The oracle already does this. A refusal cannot yield the offending chunk or commit staged output.

Keep code_set out of the fixed-string pin set. Define the Arrow empty/all-null transformation once beside the mapping operation and export it through the kernel facade. Apply it by registry policy in full-frame assembly and before per-chunk writeback. Keep the pandas StringDtype overlay at the pandas boundary. Apply the same degenerate-output policy to each completed native chunk before either yield path. A present zero-row chunk gives string, a nonempty all-null chunk gives null and a populated chunk gives string. The legacy iterator yields these types directly. The normalized iterator strips schema metadata and keeps these field types on both legs. The existing join or streamed resolver promotes a leading null field when later text arrives. A wholly null table stays null (`execution/_chunked.py:529-585`). An empty iterable yields no chunks after preflight. Reconcile a full frame only after combining all its native batch outputs.

Update the operator snapshot and list the derived tables that changed. Keep the S2a veto visible in chunked route evidence until S2b.

### 5.5 Evidence

One helper, `code_set_evidence_entry(code_cfg, record, *, table, column) -> dict`, in `execution/_chunked_code_set.py`: `{**describe_loaded_corpus(code_cfg, record=record), "table": table, "column": column}`. Callers:

- the handler, when `masked_any` (replaces its inline dict);
- the out-of-core stamp (`execution/out_of_core/_stream_driver_support.py:181`, replaces its inline dict);
- the unified slice: for each admitted code_set node whose source column has a non-null value, it adds the entry to `quality_metrics["code_set_corpora"]` (built at `execution/_unified_slice.py:309-350`). For the admitted shape every non-null value is masked, so "has a non-null value" is exactly the handler's `masked_any`;
- the chunked native step: per chunk, the same rule, written into the chunk `ExecutionResult.quality_metrics`, then folded by the existing aggregators (`aggregate_chunk_code_set_corpora`; `fold_corpora` at `execution/_chunked_output_sink.py:200`). No third aggregator.

Compare evidence by (table, column) across routes. Require one entry per key and exact field equality. Preserve each route's current order, including first observation in chunk aggregators. Omit the metrics key when no column masks.

Sanitize once at the public provenance projection used by `describe_loaded_corpus`. Use it for every exported evidence string derived from metadata, including free-form source, license and version. Have the metrics builder and provenance JSON exporter call this same projection. Keep their existing field sets. Keep safe identifiers and counts. Strip URL userinfo, signed query parameters and fragments, including URLs embedded in free text. Omit unsafe text when parsing is ambiguous. Keep the original version inside the record for pin validation. Guard the returned metrics and serialized evidence with credential canaries.

### 5.6 Public signatures

Keep the public scalar signature. Export the supported mapping interface from the kernel facade. Keep selection internals private. For an in-scope signature break the release sentry requires a `Breaking:` fragment naming the affected object and parameter (`tests/sentry/release/test_public_signatures.py:338-353`).

### 5.7 Sibling plans

FPE-CHECKSUM-NATIVE, BUCKET-TOPCODE-NATIVE and TEXT-REDACT-RUST-SPLICE share registry, step or snapshot edits. Recount on the merged head and rerun snapshots and mutations. At the anchor, 22 lines separate `_requirements.py` from its ceiling. Headroom after sibling merges is an estimate. This row adds no Rust or companion ABI change.


## 6. Placement

### 6.1 Files

No new production module. At the source anchor the direct module counts are 55 in `execution/native`, 28 in `execution/_strategies`, 103 in `execution` and 24 in `transforms`. Use existing test directories. New test placement follows the CODEMAP rows below.

| New test | CODEMAP row | Existing neighbor |
|---|---|---|
| `tests/unit/transforms/test_code_set_selector.py` | Transforms, line 278 | `test_code_set.py` |
| `tests/unit/kernel/test_code_set_map.py` | Arrow kernels, line 277 | `test_kernel_contracts.py` |
| `tests/unit/execution/native/test_native_code_set.py` | Native companion bridge, line 273 | `test_admission_descriptor_parity.py` |

| File | Lines now | Ceiling | Slice and change |
|---|---|---|---|
| `transforms/code_set.py` | 569 | 600 | S1: config-aware selector, shared preparation and fixed E4/E5 text. Consolidate existing code to fit. Keep gen helpers here |
| `kernel/__init__.py` | existing | 600 | S1: export map, fallback and result. S2a: export degenerate Arrow assembly beside them |
| `transforms/_codeset_loader.py`, `transforms/_codeset_config_checks.py`, `transforms/_codeset_provenance.py` | existing | current pins | S1: fixed loader and validation errors, safe provenance projection |
| `execution/out_of_core/_compat.py` | 585 | 600 | S1: schema-aware Group C decision shared by route choice and preflight |
| `execution/native/_plan.py` | 420 | 600 | S2a: eligibility uses the compiler's code_set predicate |
| `execution/_unified_slice_admission.py`, `execution/_unified_slice_evidence.py` | existing | current pins | S2a: prove text-width parity, reconstruct final dtype and evidence |
| `execution/physical/_shadow_bindings.py`, `_shadow_context.py`, `_shadow_batch_runner.py` in the same package | existing | current pins | S2a: static descriptor, runtime mapping, pass the table and column into binding |
| `execution/_errors.py` | existing | current pin | S2a: shared native fatal boundary and safe public error |
| `kernel/_code_set.py` | 44 | 600 | S1: Arrow front, reason array, fallback and shared selection loop. S2a: shared output assembly |
| `execution/_strategies/_code_set.py` | 283 | 600 | S1: handler body, shared classifier and row-error builder |
| `execution/out_of_core/_mask_group_c.py` | 544 | 600 | S1: selector in place of `_select` (net about -5) |
| `execution/out_of_core/_stream_driver_support.py` | 264 | 600 | S1: evidence helper call (net about 0) |
| `execution/_chunked_code_set.py` | 315 | 600 | S1: `code_set_evidence_entry` (about +12) |
| `execution/_operator_registry.py` | 312 | 600 | S2a: spec and `AssemblyShape` literal (about +14) |
| `execution/physical/_shadow_assembly.py` | 161 | 600 | S2a: `string_on_empty` branch (about +5) |
| `execution/native/_operator_config_rejections.py` | 324 | 600 | S2a: `code_set_config_rejection` (about +12) |
| `execution/native/_requirements.py` | 655 | 677 (dense entry) | S2a: config dispatch and explicit chunked veto. S2b removes the veto |
| `execution/native/_operator_params.py` | 358 | 600 | S2a: `CodeSetParams`, pinned-record parameter (about +25) |
| `execution/native/_operator_step.py` | 569 | 600 | S2a: one branch (about +11) |
| `execution/physical/_shadow_operators.py` | 437 | 600 | S2a: one `_bound_params` branch (about +6) |
| `execution/_unified_slice.py` | 473 | 600 | S2a: pin after admission, pass runtime context, stamp evidence, bypass retry for protected failures |
| `execution/native/_chunked_entry.py` | 688 | 689 | S2b: first move `_native_chunk_result` into `_chunked_evidence.py`. Then bind preflight records, check raw schemas and handle fatal errors during iteration |
| `execution/native/_chunked_evidence.py` | 292 | 600 | S2b: receives `_native_chunk_result`, merges `code_set_corpora` (about +50) |
| `execution/native/_chunk_masking.py` | 447 | 600 | S2b: pinned params for the chunked step, per-chunk evidence rule (about +15) |
| `execution/native/_chunked_schema_rule.py` | 363 | 600 | S2b: verify existing normalization and keep code_set outside the fixed-string set |
| `tests/native/test_operator_tables_snapshot.py` | - | - | S2a: snapshot literals |
| `docs/execution-backends.md` | - | - | S2a: route table rows |

### 6.2 Pinned surfaces: what moves and what does not

| Surface | Delta | How |
|---|---|---|
| Secret-material census | one rehome and two removals | Move `_pick_from_seq::mask_key` to `CodeSetSelector.__init__::mask_key`. Declare the full donor key in `moved_from`. The donor must be lost, uniquely claimed, have the same bound name and have no numeric max. Remove every binding and read of `mask_key` in the donor. An annotation change is insufficient. Drop `_pick_mask::mask_key` and `_code_set_array._select::job_seed`. Keep the outer batch, scalar, chapter, gen and step key sites. See `tests/sentry/ratchet/_rehome.py:60-114` |
| Census files | refresh each slice | Run `scripts/secret_material_census.py --write`. New identities start unreviewed. Inspect the wiping try and set the new row to `wiped` explicitly. Review live line changes, including `run_kernel_step::mask_key`, after S1, S2a and S2b. Adjust the ratchet only for the rehome and removals |
| Draw catalogue | metadata and two digests | Keep the `hmac_hex(` token in `_pick_from_seq` and the gen draw in its current file. Correct the operation, derivation and per-distinct mask notes in `execution/native/_draw_sites_mask.py:186-202`. Review and re-pin the entry and whole-catalogue digests. Output goldens keep their bytes |
| F29 reason inventory | inspect live identities separately from fixture keys | The ratchet reads the fixture by file, function and expression. Message edits do not change those keys. The builder scans live source. The unchanged gen loop retains `CodeSetHandler.run::exc.code`. Shared classification replaces the out-of-core direct read and adds the classifier read. Native error projection reads the registered reason. Review the live scan diff for each slice. F29 consumers have no rehome exemption. Refresh only the affected inventory entries after comparing live scans on both heads. Section 13 covers the required new consumer keys |
| Module size | shrink when required | Recount the first S2b move on that commit. Below 649 lines the 689 pin is stale. Lower the size entry and corresponding baseline under the existing headroom rule. Keep later wiring within the new ceiling |
| Package fan-out | no production growth | reuse existing modules |
| Operator snapshot and route witnesses | reviewed behavior changes | Update literals on the slice that changes them. Keep output bytes, mismatch and refusal assertions |

Retarget the provider golden to the boxed-key helper. Move out-of-core selection counts, injected-error and handler file-swap spies to the real selector. Retain the independent reference. Update Phase D's sequential and chunked matrix, backend classification, eligibility and auto-chunk expectations. S2a expects the temporary chunked veto. S2b expects Arrow Python work. Keep distinct-call counts and all current refusal cases. Update assertions that previously required a leaked version string to require its absence and the same error code.

Witness files include `tests/native/test_determinism_goldens.py`, `tests/parity/test_ooc_code_set_arrow.py`, `tests/unit/execution/test_code_set_strategy.py`, `tests/parity/test_phase_d_audit_no_legacy.py`, `tests/parity/_d_audit_matrix.py`, `tests/native/test_native_plan_config_aware.py` and `tests/unit/execution/_auto_chunk_strategies.py`.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | `RowError` reasons, E4 and E5 messages, conversion errors | reasons carry the code only; selection and loader messages use fixed advice, evidence strips credentials; the E9 fallback binds no exception | AT-5 | M7, M8 |
| 2 | Cleanup missing on an exit path | loader handles and key parameters | preserve close and wipe paths | AT-5 and census | remove the exceptional wipe |
| 3 | State and concurrency | the hoisted key and the pinned record are per selector build and per table | selector built once per handler call, batch or step; record pinned before the first chunk | AT-3, AT-9 | M5 |
| 4 | Route parity and silent fallback | seven routes | one `code_set_map` and one selector on all of them; route-specific refusal and activation witnesses | AT-1, AT-6, AT-7 | M2 |
| 5 | Referential integrity | code_set on an FK key | unified slice declines any table with relationships; chunked keeps its two-orientation refusal | AT-7 | drop the relationships decline for a code_set table (AT-7 red) |
| 6 | Untrusted producer | an override corpus file | existing schema and version checks; unchanged | existing corpus tests | n/a |
| 7 | Check then use | the corpus file | the record is read once and pinned; the selector never reopens the file | AT-3, AT-9 | M5 |
| 8 | Weak tests | value parity alone can pass before the change | AT-2 (no `to_pylist`, one derive per build) and AT-8 (speed) carry the fail-before | AT-2, AT-8 | M4 |
| 9 | Refactor drift | the key now travels boxed | golden outputs captured before S1, plus the protocol provider as a second oracle | AT-1 | M1 |
| 10 | Frozen contract drift | the compatibility contract freezes code_set output | freeze pandas output and correct unsafe stream selection | AT-1 | M1 |
| 11 | Silent route claim | `routed_diagnostics` on the native operator | the safe fatal marker bypasses unified retry | AT-7 | M9 |
| 12 | Evidence loss | native routes | one evidence helper, existing aggregators | AT-6 | M6 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no new anchored validation grammar | - |
| 2 | Strict wire and stored types | no new persisted model | - |
| 3 | No exception context | yes: selector errors, the kernel's `on_error` loop and the E9 fallback must not keep the key or value | AT-5 (d) |
| 4 | Versioned read models | the corpus `source_version` pin, unchanged | existing tests |
| 5 | Normalized guard scanners | no new scanner | - |
| 6 | No reaching into private modules | all three execution callers import the kernel facade and the public transform selector | review |
| 7 | No hidden CI failures | AT-8 is under the `perf` marker, which runs in the default gate (`pyproject.toml:435`), so it uses a ratio, not an absolute time | AT-8 |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M9 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | census rehome and draw-site resolution | section 6.2; census and draw-site sentries in T2 |
| 11 | No raised caps | module size, fan-out freezes | section 6.1: ratchet down stale pins |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity: outputs of today's per-row oracle, captured on the S1 base head before the change, for icd10 and one more shipped corpus: values in and out of corpus; `None`, `NaN` and `pd.NA` in one object column; `1`, `1.0`, `True` and `"1"` in one object column; a float column; an Int64 column with `pd.NA`; a boolean extension column; a category column; a datetime64 column (pins `str(Timestamp)`); a non-empty all-null object column (no evidence entry); a zero-row frame; a zero-chunk `ChunkedArray` on `code_set_map`; a lone-surrogate cell (in-memory DataFrame only); the nested `_nested_leaves` route; `chapter_preserve` true and false; two namespaces and the absent namespace. Include NaT and failed non-string objects. Check Python None at missing positions before assignment and observable scalars, identity where pandas preserves it, inferred dtype and returned Arrow schema after assignment. Choose a fixed seed and corpus with distinct goldens for 1, 1.0 and True. Every handler route gives the same values and pandas dtype. The selector also agrees with `CodeSetKeyedSelectProvider` on every string input in the golden suite. Check fatal and recoverable cases against the scalar oracle separately. Run a real automatic out-of-core FK candidate with a non-key ICD-10 payload in int64 batches [1] then [null, 2]. Assert fallback before streaming and exact equality with the whole-frame result at all three positions. Force direct streaming on the same source and assert pre-stream refusal. Include an admitted text control | numeric streaming disagrees today | S1 |
| AT-2 | Spy separately on derive and select for each handler call, out-of-core batch and native step. Require one derive per build and exactly one select per distinct non-null string, including repeats, all-null input and the E9 fallback. Spy on source materialization before encoding for both text widths. Dictionary and result reads after encoding are allowed | per-row derive today | S1, S2a, S2b |
| AT-3 | Keep scalar and out-of-core supplied-record mismatch tests. Bind a record from another release and assert the existing mismatch code before selection. With no supplied record count one resolution per column per run, or one per standalone batch call. Swap to a disjoint replacement corpus between handler draws and between chunked oracle chunks. Assert original outputs, record identity and evidence | existing pin and swap guards | S1 |
| AT-4 | Interleave an absent chapter and a sole-member bucket, repeat both, and include a missing row and a successful mask. Compare every RowError to the base handler, including exact index, column, trigger, reason and order. Check original failed objects, None normalization, pandas dtype, successful output and evidence. Repeat without a success and require no evidence | guards loss of reason or position | S1 |
| AT-5 | (a) E4 on a one-row customer corpus omits the planted corpus code and input from str(exc). (b) Both E5 reasons omit input and chapter. (c) Check RowError.reason and public diagnostics. (d) Assert empty cause and context on E4, E5, the E8 translation and translated reader errors. Use a surrogate plus a separate E4-triggering member so conversion fails first. Verify tracked key parameters are wiped on failure. (e) Plant version, reader and stat canaries. Assert the same registered codes, structural paths and fixed advice, with no canary in str(exc) or returned diagnostics. (f) Put credentials in URL-valued and free-form provenance. Inspect the returned result and serialized metrics. Safe identifiers and counts survive, credentials do not | selector and loader text and public evidence expose canaries today | S1 |
| AT-6 | Run flag-on and flag-off. Check actual unified activation or chunked native execution, arrow_python, AT-1 values and exact returned schemas. Include populated metadata-free large_string, a wholly null nonempty typed string table, a zero-row table and a leading all-null chunk followed by populated rows. Cover both normalized legs and the legacy iterator. Compare final full-frame pandas metadata and route-specific chunk types from section 5.4. With a valid zero-row corpus require unified activation. Assert one evidence entry per masked (table, column) with exact fields when B masks in the first chunk and A only later. Require absence of the key when neither masks | no operator today | S2a, S2b |
| AT-7 | Run the route and fatal cases below. Assert admission, oracle outcomes and publication at each public entry | no native guard today | S2a, S2b |
| AT-8 | Speed, `perf`: 200,000 rows, 5,000 distinct codes, object column, through `CodeSetHandler.run` end to end; at least 20x faster than the per-row oracle on the same sample in the same process. S1 records the measured ratio and the Dell per-row number in the PR | about 1x today | S1 |
| AT-9 | S2b repeats AT-3 during native streaming. Count one record resolution per configured column before iteration. Swap in a disjoint release between chunks. Check native activation, outputs and evidence from the original record. Keep supplied-record mismatch and empty-input failures | no native step today | S2b |

AT-1 has a reproducible scalar witness at the source anchor. Use shipped ICD-10, namespace `cs` and the test mask key `bytes([17]) * 8`. The old Arrow path returns `[R10.9, None, M17.11]`. The full-frame keys give `[L89.90, None, I10]`. With the same key, the distinct strings `"1"`, `"1.0"` and `"True"` select `R10.9`, `L89.90` and `S52.501A`. Inject the same resolved mask key at the route boundary or capture the full-frame golden for the route's own resolved key.

AT-7 cases:

- Compare the public eligibility query and compiler with defaults, gen alone, chapter preservation alone and both flags. Require the same config decision and explanation. For unified refusal on mode, chapter, source type (including pa.null()), `when:` or relationships, require no activation and the oracle outcome. Check both FK orientations.
- Direct chunked preflight must raise `chunked_code_set_when_not_supported`, `chunked_code_set_fk_key_unsupported` or `chunked_code_set_source_dtype_unsupported` for the corresponding case. For direct gen or chapter rejection, pin the existing config-compatibility failure. On S2b also try a good text chunk followed by a null-typed or numeric chunk. Check the same code before casting. A manual iterator can yield the earlier good chunk. Require no offending yield and no committed table or output file in a publishing job.
- On the same supported config S2a must activate unified execution and finish chunked execution through the oracle with the veto recorded. S2b must activate both routes. Static compile and plan inspection perform zero corpus opens. For good and bad zero-row corpora run the public job with activation on and off. Assert matching final schema or the oracle's exact error code. Prove the good unified step ran and the bad admitted job never retried.
- Inject a per-value PlanCompileError containing a data canary only inside native execution. Repeat with an unexpected exception containing a canary. Leave the oracle healthy and count oracle calls. For unified S2a and chunked S2b assert public job failure, zero retries, zero published outputs and no canary in str(exc), job-visible logs, evidence or notifications. Exercise failure after earlier staged work too.

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | `hole_resolve` uses `idx > position` instead of `idx < position` | AT-1 |
| M2 | deduplicate the S1 handler objects before stringification so 1, 1.0 and True collide | AT-1 |
| M3 | keep only the first failed position or use one E5 reason for both kinds | AT-4 |
| M4 | the handler calls `to_pylist` before encoding | AT-2 |
| M5 | resolve again after the disjoint file swap | AT-3, AT-9 |
| M6 | native routes drop the evidence helper call | AT-6 |
| M7 | put `{value!r}` back into the E4 message | AT-5 (a) |
| M8 | bind the E9 conversion exception and run the fallback inside the `except` block | AT-5 (d) |
| M9 | pass a handler callback that consumes the injected native E5, or let the unified catch retry the healthy oracle | AT-7, on the applicable native route |

## 10. Frozen contracts

- Freeze the full-frame pandas result. S1 corrects the older numeric out-of-core divergence through pre-stream admission. Preserve the per-route schema and evidence contracts in sections 5.4 and 5.5.
- Error message text is not frozen; only codes are. The E4 and E5 message change is a fix.
- Rejected alternative, recorded for the owner: route code_set through `derive_index_batch` (native, threaded, and moved to CMAC by NATIVE-THREADS-DEFAULT S3). It would change every code_set output and break joins with earlier runs, for a speed gain only at near-unique cardinality. Not proposed. If a measured customer column shows distinct close to rows, a follow-up row can add it with a `Breaking:` line.

## 11. Pre-mortem

- An object column holding both `"1"` and `1` dedupes to one entry. It must, because both print as `"1"` and today's loop gives both the same output. AT-1 covers it.
- The Arrow conversion treats one of `pd.NA`, `NaN` and `None` as non-null. The handler excludes missing positions before stringification and emits Python None during reconstruction. AT-1 has all three.
- A lone surrogate fails strict UTF-8 conversion. E9 falls back to the dict path; `hmac_hex` encodes with `errors="replace"`, so the bytes match today. Arrow-read sources are valid UTF-8, so out-of-core and native routes never see one.
- A builder "optimizes" the non-string branch with `astype(str)`. Datetime and float spellings change. AT-1's datetime64 and float cells catch it.
- The hoisted key outlives the column. The selector is a local of the handler call, batch or step and is dropped at return; the key sits in an `OpaqueBox`.
- `routed_diagnostics` is set and a later change admits `chapter_preserve` natively. AT-7's guard case and M9 catch a step that writes raw values.
- S2a lands before PER-COLUMN-ROUTING and a mixed table still runs one route. S2a's gain then shows only on all-native tables; S1 already removes the per-row cost everywhere.

## 12. Slices

| Slice | Content | Size | Risk | Gate |
|---|---|---|---|---|
| S1 | Config-aware selector, boxed key, reason arrays and public kernel facade. Repair pandas reconstruction, out-of-core admission, loader errors and evidence. Update census, draw catalogue and test seams. AT-1 to AT-5 and AT-8. M1 to M5, M7 and M8 | estimate: one builder-day plus gate | R2 | Codex and Dennis. Run selection, census and draw sentries |
| S2a | Register unified operator, shared config query, runtime pins, fatal boundary, final schema and evidence. Retain chunked veto. Update snapshots, witnesses and backend docs. AT-2, AT-6 and AT-7 on unified, plus chunked veto control. M6 and M9 | estimate: one builder-day plus gate | R2 | Codex and Dennis |
| S2b | First move the chunk-result builder and recount its size pin. Bind preflight records, validate every raw chunk, preserve both schema modes, collect evidence and propagate fatal errors. Remove veto with the working route. AT-2, AT-6, AT-7 and AT-9. Repeat M5, M6 and M9 | estimate: one builder-day plus gate | R2 | Codex and Dennis |

S2a depends on S1. S2b depends on S2a. The target date is 2026-12-15. Confirm the estimates after S1. S2a works with or without ROUTE-LABEL-TRUTH.

## 13. Owner questions and deferred items

Q1 and Q3 are in the vault `OWNER-QUESTIONS.md` (2026-11-24, kind: default; the recommended choice applies if unanswered when S1 starts). Q2 is settled: the row is already a 1.0 row in `mask.md`. Only required new sentry identities need an owner decision.

- Q1: Arrow per distinct (byte-identical) over a Rust kernel (byte change). Recommended: Arrow, per the measurement in section 1.
- Q3: gen-mode `code_set` stays per row and is named on the run card. Recommended: yes for V1; a later row can key it on the positional index kernel with a `Breaking:` line.

- Q4 (F29 consumer baseline): a live refresh needs keys for the shared classifier and safe fatal projection. Existing consumers use different file/function/expression identities. Options are to admit only the reviewed new keys and remove obsolete ones, or defer the inventory refresh pending a different approved design. Recommend the narrow update. Compare the generated delta with the base scan before updating the fixture or ratchet. No census or size-cap growth is requested.

V2-LOG:

- A native code_set tenant on the sequential FK route (a `_code_set_admit`/`_apply` pair in `execution/_sequential_native_ops.py`); S1 already removes the per-row cost there.
- Two existing `code_set_corpora` aggregators with the same rule (`aggregate_chunk_code_set_corpora`, `execution/_chunked_code_set.py:299`, and `fold_corpora`, `execution/_chunked_output_sink.py:200`). Merge them in a later cleanup; this row adds no third.
