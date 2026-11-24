Status: plan (revision 3, 2026-11-24, after Dennis round 1; anchored to cb06f318e)

# TEXT-REDACT-RUST-SPLICE: text_redact detects and splices spans in Rust, over Arrow, on every native route

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: TEXT-REDACT-RUST-SPLICE (CLI `docs/roadmap/groups/mask.md:32`, group mask, 1.0.x, not started): "reusing detect and splice in text_mask.rs ... Output bytes do not change." V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 68 and rank 10). Engine only. The CLI gets the change through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. `crate/` is the Rust crate `decoy-engine-native/src/`. Read at engine `origin/main` `70881ad79` (0.28.3) for revision 1; revision 2 re-checked every citation at `cb06f318e`. Line numbers are at `cb06f318e`. The crate and the text_redact Python modules did not change between the two heads; only `_chunked_evidence.py` line numbers moved. Revision 3 applies Dennis round 1 (F1, D1 to D3, M1 to M3, L1 to L6); every new citation was read at `cb06f318e`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `api-and-compatibility.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (a masking hot path moves to a new compiled entry point; a wrong span is a leak; output must stay byte-identical). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; each column runs its own path; faster wins even when bytes change, if each change is named. This row needs no byte change. The measured Rust path matches the oracle exactly (section 1), so the roadmap text "Output bytes do not change" holds.

## 1. Frame

`text_redact` is admitted on the native routes as an Arrow-Python operator (`execution/_operator_registry.py:162-172`: `planned_backend=ARROW_PYTHON`, `required_kernel=None`). Every native route calls one function, `native_text_redact` (`execution/native/_kernels_scalar.py:149`):

- unified slice and chunked native step: `execution/native/_operator_step.py:343`;
- sequential route: the op `execution/_sequential_native_ops.py:474`, called from `execution/_sequential_native.py:469-470`;
- out-of-core route: `execution/out_of_core/_text_redact_native.py:224`.

The function already calls Rust, but only to find candidate spans. It starts with `to_pylist`. Per 65,536-cell batch it calls `kernel.text_redact_candidates` (`_kernels_scalar.py:196`). Then, for each cell, it runs the Python merge (`execution/native/_text_redact_kernel.py:167` `merge_text_redact_spans`) and the Python splice (`execution/_strategies/_text_redact.py:198` `_splice`). It builds the output with `pa.array(list)`.

`text_mask` already has the full Rust path. `crate/text_mask.rs:102` `detect_splice_cell` does detection, the oracle merge (stable sort by start then longest first, then a leftmost-longest sweep) and the splice for one ASCII-safe cell. Its PyO3 entry `text_mask_detect_splice` (`crate/text_mask.rs:198`) takes a Python list and returns a Python list. Each span has one of two outcomes: replaced with the one `token`, or kept verbatim.

Measured on the Dell (WSL2) with the companion built from `70881ad79`, 120,000 mixed free-text cells, one thread:

| Path | Time | Per row |
|---|---|---|
| pure Python oracle (`iter_spans` and `_splice`) | 3.28 s | 27.3 us |
| today's `native_text_redact`, `label_token=False` | 1.35 s | 11.2 us |
| today's `native_text_redact`, `label_token=True` | 1.40 s | 11.7 us |
| part of it: `to_pylist` | 0.13 s | 1.1 us |
| part of it: `text_redact_candidates` (Rust) | 0.31 s | 2.5 us |
| `text_mask_detect_splice`, every detector replaced, gaps kept (the text_redact shape) | 0.27 s | 2.2 us |

Parity of the last row against `native_text_redact(label_token=False)`: 0 mismatches and 0 declined cells. So text_redact is the text_mask detect-splice with every span replaced and every gap kept. Three things are missing:

- (a) the `label_token` form, where each span becomes `[REDACTED:<detector_id>]`;
- (b) an Arrow boundary, so the 1.1 us `to_pylist` and the list rebuild go away;
- (c) a route label that says Rust ran. `executed_backend` (`execution/native/_chunked_evidence.py:120`) reports `arrow_python` for text_redact and text_mask, because their step returns `ran=None` (`_operator_step.py:343` returns `StepResult(out, None)`; the text_mask comment at `:352` says the same). After this row, Rust does all the work for eligible cells, so `arrow_python` would understate the route on the unified slice and the chunked route. The sequential and out-of-core routes already report `rust_companion` whenever the companion is bound (`_sequential_native_decisions.py:63-64` uses `rows > 0` for text_redact; `out_of_core/_text_redact_native.py:112-119` uses `native_calls`), so there the label overstates the route for an all-null or all-non-ASCII column.

### Overlap with RUST-DATE-TEXT (1.2)

RUST-DATE-TEXT (`mask.md:34`) owns full-Unicode text paths and multi-thread text kernels through `native_threads` (its R10 and R11). Today a non-ASCII cell declines to Python (`_text_redact_kernel.py:74` `is_ascii_safe`), and it still does after this row. This row releases the GIL around a single-threaded loop, because the input is Arrow and no Python object is touched. Splitting a batch across threads stays with RUST-DATE-TEXT. The new entry point takes `native_threads` now and resolves it with the crate's `NativeThreadBudget::resolve_on_host` (the function behind `resolve_native_threads`, `crate/arrow_ffi.rs:602`), then runs one thread. RUST-DATE-TEXT changes the body, not the signature.

## 2. Established solutions

Search run: span redaction engines (Microsoft Presidio anonymizer operators and conflict resolution; Google DLP `ReplaceWithInfoTypeConfig`); Rust Arrow string building (arrow-rs `StringBuilder`); the engine's own text_mask path.

- Presidio applies one model: detectors give `(start, end, entity)` spans, a conflict step keeps non-overlapping spans, and an operator per entity replaces each span ("replace" with a fixed value, or the default `<ENTITY_TYPE>` label). Google DLP's `ReplaceWithInfoTypeConfig` is the same label form. So `token` and `label_token` are one splice loop with a replacement string per entity, not two code paths. Source: Presidio anonymizer docs (microsoft.github.io/presidio/anonymizer).
- arrow-rs `StringBuilder::with_capacity` builds a string column in one pass. The engine already uses it in `crate/arrow_ffi.rs:110` `export_string_array` and imports arrays with `import_array` (`crate/arrow_ffi.rs:54`).
- The engine's `detect_splice_cell` already reproduces the oracle merge and has text_mask parity tests. This row extends it. It does not write a second sweep.

### Reuse inventory

- `crate/text_mask.rs:102` `detect_splice_cell`, `:62` `splice_cell`, `:52` `push_gap`: changed in place (section 5.1), not copied.
- `crate/text_redact/` (`candidates_for_cell`, `is_eligible`, `CATALOG_LEN`, `SUPPORTED_IDS`, catalog version 2): unchanged.
- `crate/arrow_ffi.rs` `import_array`, `export_string_array`: reused for the Arrow boundary. Both are private `fn`s today (`:54`, `:110`); S1 makes them `pub(crate)`. `arrow_ffi.rs` is 615 lines, so the new pyfunction goes in `text_mask.rs`, not there.
- `execution/native/_text_redact_kernel.py`: `load_text_redact_kernel` (returns None when the companion is absent or skewed), `requested_rust_ids` (becomes the one detector-order resolver, section 5.3), `is_ascii_safe`, `CATALOG_VERSION`: reused. `load_text_redact_kernel` itself does not change (section 10a). `merge_text_redact_spans` stays for cells that decline.
- `execution/_strategies/_text_redact.py:198` `_splice` and `detection.detectors.iter_spans`: stay as the oracle and as the per-cell fallback.
- `StepResult.ran` (`execution/native/_operator_step.py:256`) and `executed_backend`: reused for the label on the unified slice and the chunked route. The sequential and out-of-core routes need a small rule change (section 5.4).
- The coded-`ValueError` translation pattern (`_crypto_ext.py:362`, `_group_key_ext.py:103`, `_index_ext.py:95`, `_fpe_ext.py:50`): one shared helper is extracted from it (section 5.3); no fifth copy.

## 3. Guarantee and non-goals

After this row:

1. On every native route (unified slice, chunked native, sequential, out-of-core), a `text_redact` cell that is a non-null ASCII-safe string, in a column that requests only Rust-supported detectors, is detected, merged and spliced by one Rust call per batch. Its output is byte-identical to the pandas oracle (`TextRedactHandler.run`) for `label_token` true and false, any `token`, and any detector list and order, including duplicates.
2. Every other cell (null, not ASCII-safe) takes today's Python path inside the same function. Its bytes do not change. A detector id that is not a built-in is dropped by the resolver, as the oracle skips it (`detection/detectors.py:867-869`); custom and NER spans are not parameters of the native function (NER is refused at admission).
3. `text_mask` keeps its bytes. Its Rust entry moves onto the same core and the same Arrow boundary.
4. On the Rust path, input and output cross the boundary as Arrow arrays: no `to_pylist`, no `pa.array(list)`.
5. The executed backend is `rust_companion` for a text_redact or text_mask column when Rust spliced at least one cell of it (a non-null cell that did not decline), and `arrow_python` when the column had rows but Rust spliced none. A table with no rows keeps today's per-route label. The full table is in section 5.4. The run card and `docs/execution-backends.md` name both cases.
6. With the companion absent or skewed, output is unchanged and the route is native Arrow-Python, as today.

Non-goals: full-Unicode cells and multi-thread splitting (RUST-DATE-TEXT, 1.2); NER (stays refused natively, `execution/native/_operator_config_rejections.py:291` `text_redact_ner_not_native`); new detectors; the pandas oracle handler's own loop (it stays the reference); text_mask strategies other than redact and passthrough (they keep their Python path).

## 4. Enumerations

### 4.1 Routes

| Route | Entry | After this row |
|---|---|---|
| unified slice | `_operator_step.py:343` `native_text_redact` | same call, new body; `StepResult(out, ran)` |
| chunked native | same step | same |
| sequential | op `_sequential_native_ops.py:474`, counted at `_sequential_native.py:470` | op returns `NativeResult(..., ran=ran)`; the count line becomes a call that records `ran` (zero net lines) |
| out-of-core | `out_of_core/_text_redact_native.py:224` | unpacks `(array, ran)` |
| pandas full frame (native declined) | `TextRedactHandler.run` | unchanged (oracle) |

One function body changes, so the four native routes move together. There are three call sites: the step (unified slice and chunked), the sequential op and the out-of-core caller. Each one unpacks the new `(array, ran)` return (section 5.3). Input shape: every route admits only a `string` source (`native/_real_type_admission.py:93-101`), but the step passes `pa.Array | pa.ChunkedArray` (`_operator_step.py:305`), so the function handles both (section 5.3).

### 4.2 Exit paths of the new call

| # | Condition | Result |
|---|---|---|
| E1 | companion absent or catalog skew (`load_text_redact_kernel` returns None) | whole column on the Python path, `ran=False` |
| E1b | companion present but older, without `text_span_splice` or with another splice contract version (the probe in section 10a returns None) | today's candidates path, unchanged, `ran=False` |
| E2 | `detectors: []` | the input array is returned as is (the oracle passes every cell through), no Rust call, `ran=False` |
| E3 | null cell | null out, in place |
| E4 | non-null cell that is not ASCII-safe | Rust marks it declined; the Python path runs for that cell only |
| E5 | eligible cell | Rust output |
| E6 | Rust boundary error: `text_splice_unsupported_type`, `text_splice_catalog_mismatch`, `text_splice_contract_mismatch`, `text_splice_unknown_detector` | mapped to `ExecutionError` with the matching `reasons.runtime` code by the shared translator (section 5.3); never a fallback inside the function. Route outcome: section 5.3 |
| E7 | Rust output length, type or null positions differ from the input slice | `ExecutionError` `text_splice_output_invalid`, raised by a named check `_checked_splice_output` in `_kernels_scalar.py` |

### 4.3 Codes

No new reason codes in `reasons/route`. Five new runtime codes in `reasons/runtime/_part3.py`, in its `ExecutionError` block (`:438`): `TEXT_SPLICE_UNSUPPORTED_TYPE`, `TEXT_SPLICE_CATALOG_MISMATCH`, `TEXT_SPLICE_CONTRACT_MISMATCH`, `TEXT_SPLICE_UNKNOWN_DETECTOR` (defensive: the resolver drops unknown ids first) and `TEXT_SPLICE_OUTPUT_INVALID`. `_part3.py` is 542 lines and stays under 600. The labels are the existing `rust_companion` and `arrow_python`. If ROUTE-LABEL-TRUTH (`plan/route-label-truth`) merges first, its per-column decline record carries E1, E1b and E2.

### 4.4 FK shapes

N/A: text_redact is not an FK key strategy and this row changes no admission, so a text_redact column on an FK key is refused or routed exactly as today.

### 4.5 Fields

| Field | Values | Handling |
|---|---|---|
| `detectors` | absent (all built-ins), a list, an empty list | absent and lists map through `requested_rust_ids`, which gives the oracle tie order (section 5.3); unknown ids are dropped as the oracle skips them; an empty list is E2 |
| `token` | any string | `Replace(token)` |
| `label_token` | true, false | `Replace("[REDACTED:<id>]")` per index, or `Replace(token)` |
| `ner` | set | refused natively (unchanged) |

### 4.6 Output surfaces

| Surface | Change |
|---|---|
| masked output column | none (byte-identical) |
| `quality_metrics` route evidence and the run card | executed backend `rust_companion` when Rust ran |
| `docs/execution-backends.md` (`:22-24`, `:74`) | text_redact and text_mask rows say Rust detection and splice for ASCII-safe cells, Python per cell otherwise |
| `docs/compatibility-contract.md:1047-1052` | the sentence "Evidence reports `arrow_python`, never a compiled kernel" is replaced with the section 5.4 rule; the bytes clause is unchanged |
| warnings, errors, logs | no cell text (AT-7) |

## 5. Design notes

Principles that apply: one place per fact (one sweep and one splice in the crate); open/closed on the span outcome (a new outcome is one enum arm, not a new function). Established pattern: Presidio's per-entity operator table (section 2).

### 5.1 One core with a replacement per detector

Today `detect_splice_cell` takes `verbatim: &[bool; CATALOG_LEN]` and one `token`. It changes to a table of span outcomes:

```
pub enum SpanOut<'a> { Verbatim, Replace(&'a str) }
pub fn detect_splice_cell(text, indices, outs: &[SpanOut; CATALOG_LEN], passthrough_unmatched) -> Option<String>
```

- text_mask builds `outs[i]` as `Verbatim` or `Replace(token)` from its `verbatim` list, so its bytes cannot move. Guard: AT-4.
- text_redact builds `Replace(token)` for every index, or with `label_token` `Replace(label_i)`, where `label_i = "[REDACTED:" + SUPPORTED_IDS[i] + "]"` is built once per call. The oracle passes the Python detector id to `_splice`. S1 asserts that the Rust `SUPPORTED_IDS` spellings equal `_text_redact_kernel.SUPPORTED_IDS`.
- text_redact passes `passthrough_unmatched=True` (gaps are kept as they are).
- `splice_cell` takes the resolved replacement for each span instead of `verbatim` and `token`.

### 5.2 Arrow boundary

A new pyfunction in `crate/text_mask.rs`: `text_span_splice(values, *, detector_ids, outs, passthrough_unmatched, catalog_version, splice_contract_version, native_threads=None)`, plus `text_span_splice_contract_version() -> int` (value 1). It returns a pair: the spliced `pa.string()` array, and a `declined` boolean array (true where a non-null cell is not ASCII-safe; the string array holds null there).

- `values` comes in through `import_array` (made `pub(crate)`). `string` is the type every route sends. `large_string` is also accepted, because the cost is one match arm; no route sends it today (`_real_type_admission.py:93-101`). Any other type raises `text_splice_unsupported_type`. Arrow validates UTF-8 on import (`Cargo.toml` `force_validate`), so taking `&str` cells is safe.
- `catalog_version` and `splice_contract_version` are checked first; a mismatch raises the matching coded error. A bool for either is refused by the PyO3 type.
- The output uses `StringBuilder::with_capacity(len, input_bytes + slack)` and `export_string_array` (made `pub(crate)`).
- The loop runs inside `py.detach` (pyo3 0.29, as at `crate/arrow_ffi.rs:232`). `native_threads` goes through `NativeThreadBudget::resolve_on_host` and the loop runs on one thread.
- `text_mask_detect_splice` stays as a thin list wrapper over the same core until S2 moves text_mask, then S2 deletes it.

### 5.3 Python side

One detector-order resolver. `requested_rust_ids` (`_text_redact_kernel.py:143`) today returns catalog order for `None` (`:156-157`). The oracle breaks equal `(start, length)` ties by `_SPAN_DETECTORS` insertion order (`detection/detectors.py:841-853`), and `detect_splice_cell` breaks them by the order of the indices it gets (`crate/text_mask.rs:113-114`). text_mask already resolves `None` to `list(_SPAN_DETECTORS)` (`_text_mask_native_splice.py:108`). S1 changes the `None` branch of `requested_rust_ids` to `_SPAN_DETECTORS` order filtered to `SUPPORTED_IDS`, and S2 makes `_text_mask_native_splice.py:108-109` call it. The candidates path does not depend on this order (the Python merge groups candidates by detector index and walks `detector_ids` itself, `_text_redact_kernel.py:186-197`), so its output does not change. Known natural ties: `ssn`/`us_zip` on "12345-6789" and `npi`/`us_phone` on "-2283038836" (Dennis round 1 fuzz). Both keep the same relative order in both orderings, so today's bytes are right; the fix stops a future catalog change from putting the wrong `[REDACTED:<id>]` label in.

`native_text_redact` becomes:

1. E1: today's Python code, `ran=False`. E2: return the input, `ran=False`. E1b (the splice probe returns None): today's candidates code, `ran=False`.
2. Otherwise walk the input chunk by chunk: `array.chunks` for a `pa.ChunkedArray`, `[array]` for a `pa.Array`, nothing for a zero-chunk ChunkedArray. Inside each chunk, call `text_span_splice` on each 65,536-cell `chunk.slice(base, n)` (zero copy; a non-zero offset crosses the C interface as is). No `combine_chunks`: on a large text column it can overflow int32 string offsets.
3. Check each result with `_checked_splice_output` (E7): `pa.string()`, the same length as the input slice, and null exactly where the input is null or `declined` is true.
4. If `declined` has any true value: take the declined cells with `pc.filter`, run today's per-cell Python fallback on them only (the `iter_spans` plus `_splice` code at `_kernels_scalar.py:177-183`), and put them back with `pc.replace_with_mask`.
5. Assemble with `pa.concat_arrays(pieces)` (an empty input gives `pa.array([], pa.string())`) and return `(out, ran)`, where `ran` is true when any slice had a non-null cell that did not decline. The assembled column has the same int32 offset limit as today's `pa.array(list)`, so this is no worse; a larger column is RUST-DATE-TEXT or a later `large_string` row.

Boundary errors (E6). A shared helper `translate_coded_error(exc, table)` is extracted into `_crypto_ext.py` next to `_translate_compiled_kernel_error` (`:362`); it splits `code: detail` once and looks the code up in a table of factories. `_fpe_ext._translate_compiled_fpe_error` (`:50`) is rewritten to call it, so the helper has two callers from the start; the other three translators move later only if touched. `native_text_redact` catches `ValueError` from `text_span_splice`, computes the mapped `ExecutionError` inside the `except`, and raises it after the block closes, so `__cause__` and `__context__` are None (AT-7). Route outcome of a boundary error: chunked, sequential and out-of-core fail the job with that `ExecutionError`; the unified slice's generic exception boundary reroutes the node to the full-frame oracle (comment at `physical/_shadow_operators.py:414-417`), which is existing behavior and the same for every operator. AT-6 asserts each.

`native_text_redact` returns a `(array, ran)` pair. Each caller unpacks it:

- Step (`_operator_step.py:343`): `return StepResult(out, ran)` in place of `StepResult(out, None)`. The unified slice then sets `evidence.compiled_kernel_executed` when `ran` is true (`physical/_shadow_operators.py:422`). The chunked path does the same at `native/_chunk_masking.py:263-273`; on `ran=False` it marks the column `kernel_idle`. On that branch `counted` stays true for text_redact unless a `when:` mask is set, so `kernel_calls` changes only for a `when:` column that Rust did not touch. AT-5 pins the companion-absent count.
- Sequential: `NativeResult` (`_sequential_native_ops.py:130-137`) gains `ran: bool | None = None` (other kernels leave it None). The text_redact op (`:470-476`) and, in S2, the text_mask op pass `ran`. In `_sequential_native.py:470` (700 lines, census pin 700 at `tests/sentry/test_module_size.py:129`) the line `decision.native_calls += 1` becomes `decision.record_call(result)`: zero net lines, and the pin does not move. `record_call` lives in `_sequential_native_decisions.py` (112 lines): it adds one to `native_calls`, as today, and sets `spliced = True` when `result.ran`. `native_calls` keeps its meaning (one per call, so an all-null column still counts one, `:77-80`).
- Out-of-core (`out_of_core/_text_redact_native.py:224`): unpack before the existing `isinstance(out, pa.Array)`, type and length check, which stays. `native_calls` keeps counting calls; a new `spliced` flag on the decision is set when `ran` is true. The module docstring "no fallback and no catch" stays true: the per-cell decline is inside `native_text_redact`.

`native_text_mask` takes the same shape in S2, where `plan_native_splice` (`execution/native/_text_mask_native_splice.py`) already decides that a config is the redact and passthrough shape.

### 5.4 Route label

`OperatorSpec` for `text_redact` and `text_mask` (`_operator_registry.py:162`, `:173`): `planned_backend=RUST_COMPANION`, `required_kernel=None` (the operator still runs without the companion), and `positive_kernel_evidence` stays `False`.

Revision 1 set `positive_kernel_evidence=True`. That is wrong: on the unified slice that flag raises `UnifiedSliceInvariantError` when no compiled kernel ran (`execution/_unified_slice_evidence.py:50-53`, `:125-133`). A companion-absent run (E1), an old companion (E1b), `detectors: []` (E2) and an all-non-ASCII column would then fail instead of running on the Python path, which breaks guarantees 5 and 6. The value-dependent kernels `bucket_perturb`, `date_shift` and `group_key` already use `planned_backend=RUST_COMPANION` with the flag `False`; text_redact and text_mask follow them. M8 guards it.

One definition of "ran": Rust spliced at least one cell. Result per case and route:

| Case | Unified slice and chunked | Sequential | Out-of-core |
|---|---|---|---|
| eligible cells, companion current | `rust_companion` | `rust_companion` | `rust_companion` |
| rows, but all null, all declined, E1b or E2 | `arrow_python` (today: `arrow_python`) | `arrow_python` (today: `rust_companion`) | `arrow_python` (today: `rust_companion`) |
| companion absent (E1) | `arrow_python`, as today | not admitted, Python handler, as today | not admitted, as today |
| no rows | as today (`arrow_python`) | `none` with the no-rows reason, as today | `none` with the no-calls reason, as today |

How each route gets there:

- Unified slice: `kernel_idle` is `planned != ARROW_PYTHON and not evidence.compiled_kernel_executed` (`_unified_slice_evidence.py:136`), so `executed_backend` (`_chunked_evidence.py:120`) gives `rust_companion` when any batch spliced a cell and `arrow_python` otherwise.
- Chunked: `kernel_idle` comes from `StepResult.ran` being false (`_chunk_masking.py:263-273`). The fold `merge_executed_backend` (`_chunked_evidence.py:130`) keeps `rust_companion` if any chunk spliced a cell.
- Sequential: a rule change in `entry()` (`_sequential_native_decisions.py:63-75`): for TEXT_REDACT and TEXT_MASK with `rows > 0`, `executed_backend` is `self.backend` when `spliced`, else `arrow_python`. The `native_calls` field in the entry is unchanged.
- Out-of-core: the same rule in `TextRedactColumnDecision.entry()` (`out_of_core/_text_redact_native.py:112-119`) and, in S2, the text_mask twin (`out_of_core/_text_mask_native.py:132`).

`_COMPANION_STRATEGIES` (`_chunked_evidence.py:59`) is derived from the registry, so it picks up both strategies with no edit. `tests/sentry/test_unified_backend_map.py:40-41` pins `ARROW_PYTHON` for `native_text_redact` and `native_text_mask`; S1 and S2 change those pins to `RUST_COMPANION`. That is the intended edit, not a raised cap.

Consistency with ROUTE-LABEL-TRUTH: that plan reads the executed backend per column from these same fields and adds the decline record. This row changes only the spec values and the `ran` evidence.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `SpanOut` core and `text_span_splice` | `decoy-engine-native/src/text_mask.rs` (341 lines, about +90) | native crate, by kernel | `text_redact/` |
| bridge protocol for `text_span_splice` | `execution/native/_text_mask_native_splice.py` (`SpliceKernel`) | "Native companion bridge", fan-out freeze at 55 | no new module |
| `native_text_redact` body, `_checked_splice_output` | `execution/native/_kernels_scalar.py` (384 lines, about +50) | same | - |
| splice probe, resolver order fix | `execution/native/_text_redact_kernel.py` (244 lines, about +25) | same | - |
| shared `translate_coded_error`; fpe translator calls it | `execution/native/_crypto_ext.py` (536 lines, about +15), `execution/native/_fpe_ext.py` (282 lines, about -3) | same | existing translators |
| runtime codes | `reasons/runtime/_part3.py` (542 lines, +5 codes) | reasons | `ExecutionError` block `:438` |
| spec values | `execution/_operator_registry.py` (312 lines) | "Pipeline spine and routes" | one field edit per spec |
| caller unpacking | `execution/native/_operator_step.py` (569 lines), `execution/_sequential_native_ops.py` (593 lines; `NativeResult.ran` and the op), `execution/out_of_core/_text_redact_native.py` (251 lines) | same | a few lines each; all stay under the 600-line limit. `_sequential_native_ops.py` is the tightest: S1 keeps it at 600 or under, or moves the op body, and never raises a cap |
| sequential count | `execution/_sequential_native.py` (700 lines, census pin 700) | same | zero net lines (`record_call`) |
| sequential label rule | `execution/_sequential_native_decisions.py` (112 lines, about +12) | same | `record_call`, `spliced` |
| backend map pin | `tests/sentry/test_unified_backend_map.py:40-41` | sentry | intended pin edit |
| tests | `tests/unit/execution/native/test_text_span_splice.py`; Rust tests in `text_mask.rs` | "Unit tests" | `tests/unit/execution/native/` |
| docs | `docs/execution-backends.md` rows; `docs/compatibility-contract.md:1047-1052` evidence sentence; changelog fragment `changelog.d/text-redact-rust-splice.md` | docs | no `Breaking:` line: `native_text_redact` is private, so the signature sentry (#763, `tests/sentry/release/test_public_signatures.py`) does not see its new return; the new pyfunction is additive |

No new Python module. `execution/native/` stays at its freeze.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | boundary errors and the decline path could echo cell text | errors carry a registered code and counts only; the mapped Python error is raised after the `except` closes | AT-7 | put the cell into the `unsupported_type` message (AT-7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no resource is acquired; arrays are owned by Arrow | n/a | n/a |
| 3 | State and concurrency | GIL released around the loop | the loop reads only the imported Arrow buffers and owned Rust values; no Python object is touched while released | AT-2 (batch sizes) | read a Python list inside `py.detach` (does not compile; reviewer check) |
| 4 | Route parity and silent fallback | four native routes and the pandas oracle; fallback to Python on decline | one function body for all native routes; decline is per cell and counted; boundary errors never fall back | AT-1, AT-5, AT-6 | M4 |
| 5 | Referential integrity | none | N/A: text_redact is not an FK key strategy | n/a | n/a |
| 6 | Untrusted producer | the compiled extension is a producer | output length, type and null mask checked (E7); catalog version handshake | AT-3, AT-6 | drop the length check (AT-3 truncated-output cell red) |
| 7 | Check then use | none | N/A: no path or file is touched | n/a | n/a |
| 8 | Weak tests | AT-1 passes before the change | AT-1b and AT-5 carry the fail-before; AT-9 measures | AT-1b, AT-9 | M7 |
| 9 | Refactor drift | text_mask moves onto the changed core | text_mask parity tests unchanged and run on the new core | AT-4 | M6 |
| 10 | Frozen contract drift | compatibility contract lists text_redact output as frozen | no byte change; route label is evidence, not frozen output | AT-1 | M1 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no: no new pattern validation; the detectors are unchanged | - |
| 2 | Strict wire and stored types | yes, at the boundary: `outs`, `detector_ids` and `catalog_version` are typed in PyO3; a bool or a string for `catalog_version` is refused | AT-6 cells |
| 3 | No exception context | yes: the boundary error must carry a code, not cell text, and no `__context__` with a value | AT-7 asserts `__cause__` and `__context__` are None on the mapped error |
| 4 | Versioned read models | yes, narrowly: the catalog version handshake | AT-6 (mismatch refused) |
| 5 | Normalized guard scanners | no new scanner | - |
| 6 | No reaching into private modules | yes: callers outside `execution/native/` use the existing public bridge names | review; import-linter unchanged |
| 7 | No hidden CI failures | yes: the companion build leg must fail the job, and AT-9 runs under the existing `perf` marker with no `continue-on-error` | CI diff review |
| 8 | One input, one trust class | no: one caller class (the engine) | - |
| 9 | Mutations on the final head | yes | M1 to M7 rerun on the final head, head recorded in the gate ledger |
| 10 | Allowlisted helpers are still checked | yes: the physical-seam sentry allowlists `execution/` routes; no new allowlist entry is needed because no route file is added | sentry run in T2 |
| 11 | No raised caps | yes: `execution/native/` fan-out 55, module size limit | no new module; line counts listed in the report |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Oracle parity: a generated corpus (each supported detector, overlaps, adjacent spans, duplicate detector ids, unknown ids, all orders of a three-detector subset, the tie strings "12345-6789" and "-2283038836" with `detectors=None` and with explicit reversed lists, empty strings, long cells, nulls) through `native_text_redact` and through `TextRedactHandler.run`, `label_token` true and false, two tokens; outputs equal | passes today (both run Python), kept as the guard; the fail-before is AT-1b | S1 |
| AT-1b | Same corpus: the Rust entry handled every eligible cell (`ran` true, decline count 0 on ASCII input) | `ran` is None today | S1 |
| AT-2 | Batch invariance: one column at batch sizes 1, 7, 65,536 and whole; outputs equal. The `native_threads` 1 and 4 cells are a regression guard for RUST-DATE-TEXT only: while the loop runs one thread they prove nothing | no `text_span_splice` today | S1 |
| AT-3 | Arrow boundary: `string` and `large_string` in; nulls stay null in place; empty and all-null arrays; a ChunkedArray of several chunks whose boundaries do not line up with the batch size; an input with a non-zero offset (`arr.slice(3)`); a zero-chunk ChunkedArray; output type `pa.string()`; an `int64` array raises `text_splice_unsupported_type`; a forced bad output length raises `text_splice_output_invalid` | no entry today | S1 |
| AT-4 | text_mask bytes unchanged on the new core: existing text_mask native-splice tests plus a redact and passthrough corpus through `text_span_splice` | no entry today | S1 (core), S2 (wired) |
| AT-5 | Executed backend, every row of the section 5.4 table on all four routes: eligible cells give `rust_companion`; all-null, all-non-ASCII, old companion and `detectors: []` give `arrow_python` with no `UnifiedSliceInvariantError`; no rows and companion absent keep today's label; sequential `native_calls` is unchanged; `kernel_calls` for a companion-absent chunked column equals today's value | unified and chunked: always `arrow_python` today. Sequential and out-of-core: the all-null and all-non-ASCII cells report `rust_companion` today | S1 (text_redact), S2 (text_mask) |
| AT-6 | A forced catalog-version mismatch, a forced splice-contract mismatch, a bool `catalog_version` and an unknown detector id sent past the resolver each raise their coded `ExecutionError` from `native_text_redact`, with no Python fallback. Per route: chunked, sequential and out-of-core fail the job with that code; the unified slice reroutes to the full-frame oracle. A companion without `text_span_splice` takes E1b | no entry today | S1 |
| AT-7 | Non-ASCII decline: output equals the oracle; no cell text appears in any warning, error or log record; the mapped error has no cause or context | no entry today | S1 |
| AT-8 | Rust unit tests: `label_token` replacement per index; `SpanOut::Verbatim` keeps the span; ties on (start, length) keep requested order, including a constructed tie checked under two index orders with `label_token` | no `SpanOut` today | S1 |
| AT-10 | Route parity: one corpus (nulls, non-ASCII, `label_token` true and false, the two tie strings) run end to end on the unified, chunked, sequential and out-of-core routes with the companion built; each output equals the oracle. Also required in T2: the existing route parity tests `tests/parity/test_phase_d_text_redact_seq.py`, `test_phase_d_text_redact_seq_real.py`, `test_ooc_text_redact_native_routing.py`, `test_ooc_text_redact_native_real.py` and, for S2, `test_ooc_text_mask_native.py` | passes today on the Python path; the fail-before is AT-1b and AT-5 | S1 |
| AT-9 | Speed floor, marked `perf`, Dell: 120,000 mixed cells through `native_text_redact` at or under 3.0 us per row (expected about 1.5 us; 11.2 us today) | 11.2 us today | S1 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | Sort ties longest-last instead of longest-first | AT-1, AT-8 |
| M2 | `label_token` emits `[REDACTED]` without the id | AT-1, AT-8 |
| M3 | Scatter declined cells to position i+1 | AT-7, AT-1 |
| M4 | Catch the boundary `ValueError` and fall back to Python | AT-6 |
| M5 | `executed_backend` reads `planned_backend` and ignores `ran` | AT-5 (companion-absent case) |
| M6 | text_mask builds `Replace(token)` for a verbatim detector | AT-4 |
| M7 | Build the output with `pa.array` from a Python list | AT-9 |
| M8 | Set `positive_kernel_evidence=True` on the text_redact spec | AT-5 (companion-absent unified slice) |
| M9 | `requested_rust_ids(None)` returns catalog order again | a resolver test that asserts `requested_rust_ids(None)` equals `_SPAN_DETECTORS` order filtered to `SUPPORTED_IDS`, and the AT-8 constructed-tie Rust test |
| M10 | Process only the first chunk of a ChunkedArray | AT-3 (multi-chunk cell) |

## 10. Byte changes

None. AT-1 is the proof. The changelog fragment says the text_redact and text_mask route label changes from `arrow_python` to `rust_companion` when the companion runs them. That is a label change, not an output change.

## 10a. Frozen contracts

- `docs/compatibility-contract.md` freezes masked output bytes for shipped strategies. This row keeps them (AT-1).
- Companion ABI: revision 1 bumped the ABI string. Revision 3 does not, matching how `text_mask_detect_splice` and `text_redact_candidates` were added (`crate/lib.rs:54-57`). A new probe `load_text_span_splice()` in `_text_redact_kernel.py` looks up `text_span_splice` and `text_span_splice_contract_version` with `getattr` and checks the version equals `SPLICE_CONTRACT_VERSION = 1`. If either is missing or the version differs, it returns None and `native_text_redact` keeps today's candidates path (E1b), so an older companion is as fast as today, not slower. `load_text_redact_kernel` does not change, so text_mask, the sequential gate (`_sequential_native_ops.py:456-459`), the out-of-core gate and `out_of_core/_hash_run.py:321-329` see no change. Rust also checks `splice_contract_version` on every call (E6), so a future build with the same signature but different splice rules is refused, not silently used. RUST-DATE-TEXT bumps the contract version when it changes the splice. This avoids the ABI collision with FPE-CHECKSUM-NATIVE, which takes `decoy-native-abi-4` (`origin/plan/fpe-checksum-native`); CODE-SET-NATIVE (`origin/plan/code-set-native`) names no ABI change. If a reviewer finds a rule that any new pyfunction needs a bump, S1 takes the next free number on main at merge time (abi-4 if FPE-CHECKSUM-NATIVE has not merged, else abi-5) and runs the engine repin checklist.
- The backend vocabulary (`rust_companion`, `arrow_python`) is unchanged; only which value text_redact and text_mask report changes. Additive for consumers that read the label.
- `docs/compatibility-contract.md:1047-1052` states text_redact evidence is always `arrow_python`. S1 replaces that sentence with the section 5.4 rule; the bytes guarantee in the same paragraph stays. The changelog fragment names the label change.

## 10b. Pre-mortem

- A tie in the merge orders differently in Rust for a detector list with duplicates. AT-1 includes duplicates and all orders of a three-detector subset; M1 proves the test sees ordering.
- A cell that Python treats as ASCII-safe but Rust does not (or the reverse) splices differently. Both sides use the same `is_eligible` rule today; AT-7 runs a corpus of edge characters (tab, DEL, NUL, CRLF) through both.
- A route hands the function a ChunkedArray or an offset slice. Section 5.3 walks chunks and slices; AT-3 covers multi-chunk, offset and zero-chunk inputs.
- A future catalog change adds a tie between two detectors whose order differs between catalog order and `_SPAN_DETECTORS` order. The one resolver (section 5.3) and M9 close it.
- The decline scatter costs more than it saves on a mostly non-ASCII column. That column was slow before too; AT-9 is for ASCII text. RUST-DATE-TEXT removes the decline.
- The text_mask label change confuses a reader of old run cards. The changelog fragment names it.

## 11. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | Rust `SpanOut` core, `text_span_splice` with the contract version, Rust tests; `native_text_redact` on the new entry with chunk walk, decline scatter and `_checked_splice_output`; shared `translate_coded_error` and five runtime codes; resolver order fix; `(array, ran)` in the step, sequential and out-of-core callers with the section 5.4 label rule; text_redact spec `planned_backend` (flag stays `False`) and backend-map pin; contract and backends docs; AT-1 to AT-3, AT-5 to AT-10, M1 to M5, M7 to M10; splice probe, no ABI bump (section 10a) | M: about 380 lines Rust and Python, 420 lines tests, about one and a half builder-days. If it runs over, split S1a (Rust core, `text_span_splice`, AT-8, the Rust side of AT-3 and AT-6) from S1b (Python wiring, labels, docs) | Risk R2 (native boundary plus route evidence). Codex and Dennis; T2 on the native and text_redact selection with the companion built |
| S2 | `native_text_mask` redact and passthrough configs on `text_span_splice`; `_text_mask_native_splice.py:108-109` calls the shared resolver; delete the `text_mask_detect_splice` list wrapper; text_mask spec label, backend-map pin and the out-of-core text_mask label rule; AT-4, AT-5 and AT-10 for text_mask | S: about 80 lines, 120 lines tests, under one builder-day | Risk R2 (frozen text_mask bytes). Codex |

Both slices fit before the 2026-12-15 engine-gap deadline.

## 12. Open questions for the owner

- Q1: The text_mask label change rides in S2 of this row (recommended, because the spec fields move with the kernel), or waits for ROUTE-LABEL-TRUTH? Recommended: here.

No other owner decision: no byte change and no new feature.
