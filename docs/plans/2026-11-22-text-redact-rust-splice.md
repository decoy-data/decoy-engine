Status: plan (revision 9, 2026-11-24, after Codex round 4; anchored to cb06f318e, findings verified on 9f7bb1f4a)

# TEXT-REDACT-RUST-SPLICE: detect and splice text_redact spans in Rust over Arrow

## Changes in revision 9

| Codex round 4 finding | Fix in this revision |
|---|---|
| V1: an old core calls `text_redact_candidates` and `text_mask_detect_splice` directly. Both accept a cell through `is_eligible` and then narrow offsets to u32 (`crate/text_redact/detect.rs:35`). The Python guard in the new wrapper cannot protect that path. | New slice S0 fixes it at the root. The shared Rust predicate `is_eligible` also requires `text.len()` to fit the detector offset limit. Both legacy exports then return their existing decline sentinel (`None`) for an oversized cell, and every core already sends that cell to the Python oracle. The additive entry uses the same predicate for its decline bit. A coded error is not used on the legacy exports because an old core does not translate it, so the job would fail. New AT-11 runs the old core against a wheel built with a reduced test limit and requires exactly `<X>` for the oversized email (sections 5.2, 8, 10a, 11). The Python guard stays for old wheels. |
| V1: S1b enabled the Rust splice on job routes while the label still said `arrow_python`. | Moved the activation boundary. S1b adds and tests the new helper but no production route calls it. S1c switches every route call site to the helper in the same merge that consumes `ran`, updates the text_redact recorder at `_sequential_native.py:470`, carries the step and out-of-core evidence and sets the planned backend. The first job-enabled head therefore carries AT-5: the emitted mark plus `rust_companion` for a real splice and `arrow_python` for an admitted all-idle column, in both batch orders (sections 5.3, 8, 11). |
| V2-LOG: S1b and S2 oversized. | Split chunk-capable transport and out-of-core FK staging into preparatory slice S1t. It runs before S1b and needs no new companion capability. Split S2 into S2a (text_mask implementation) and S2b (both skew directions on the final head, final-head mutation replay and the Dell rerun). Each slice is now about one builder-day or less (section 11). |
| V2-LOG: stale `ExecutionError` citation. | Section 4.3 now cites the block by name, the `_d = _catalog.runtime("ExecutionError")` declaration block in `reasons/runtime/_part3.py` (line 449 on 9f7bb1f4a). |

Slice order: S0, S1a, S1t, S1b, S1c, S2a, S2b.

Owner: Cam. Roadmap group: mask, 1.0.x. Scope: decoy-engine. The CLI picks up the change with its next engine pin. Risk: R2. A missed span can expose a data value. The release contract freezes masked bytes.

Paths starting with `execution/`, `transforms/` or `reasons/` are under `src/decoy_engine/`. `crate/` means `decoy-engine-native/src/`. The review worktree is at `ac2f4abdb`. Only the source plan differs from `cb06f318e`. Section 1 records historical measurements. The new entry, its mutations, end-to-end parity and the Dell floor still need implementation evidence.

## 1. Frame

`execution/native/_kernels_scalar.py:149` owns `native_text_redact`. The unified and chunked routes call it through `_operator_step.py:343`. The sequential op calls it at `execution/_sequential_native_ops.py:474`. Out-of-core calls it at `execution/out_of_core/_text_redact_native.py:224`.

Today the helper converts the column to a Python list. It stringifies non-null values. It calls Rust for candidates in batches of 65,536 rows. Python merges the candidates, splices each cell and builds the Arrow output. Without the candidates kernel, Python also detects the spans. The backend evidence differs by route (section 5.4).

The earlier Dell run used WSL2, one thread, 120,000 mixed cells and the companion from `70881ad79`. These figures describe the old interfaces.

| Path | Time | Microseconds per row |
|---|---:|---:|
| Python detection and splice | 3.28 s | 27.3 |
| Current text_redact, literal token | 1.35 s | 11.2 |
| Current text_redact, detector labels | 1.40 s | 11.7 |
| Input list conversion alone | 0.13 s | 1.1 |
| Candidate call alone | 0.31 s | 2.5 |
| Legacy text_mask detect-splice, replace all spans and keep gaps | 0.27 s | 2.2 |

The historical run reported zero declines and zero differences from literal-token text_redact on that corpus.

For AT-9, pin a new zero-decline fixture in `scripts/bench_text_redact.py`. Use the anchor's `_representative` generator with one `random.Random(20261009)`. Draw in sequence. Keep the first 120,000 ASCII-safe strings. Build one Arrow string array. Use all detectors, literal `[REDACTED]`, label mode off and one native thread. This specifies the new gate independently of the historical corpus. The default benchmark uses 200,000 rows and adds non-ASCII text to about 5% of them.

AT-1 and AT-10 cover the broader contract. AT-1 parity already passes on Python. AT-1b and the per-route labels in AT-5 distinguish the new implementation.

### Overlap with RUST-DATE-TEXT (1.2)

That row owns full Unicode detection and parallel text kernels. This row releases the GIL around one Rust loop. The new entry accepts the existing thread budget and resolves it with `NativeThreadBudget::resolve_on_host` (`crate/arrow_ffi.rs:602`). It runs one thread.

## 2. Established solutions

The engine already separates detection, overlap resolution and replacement. `crate/text_mask.rs:102` detects candidates, sorts by start and decreasing length, and keeps non-overlapping spans. Request order breaks exact ties. Extend that sweep and its writer at lines 52 and 62. Both legacy exports use the same writer. Preserve the legacy resolved-span API's own eligibility rules.

### Reuse inventory

- Use `crate/text_redact/detect.rs:10` for eligibility. The live predicate excludes non-ASCII and ASCII controls 0x1c through 0x1f. Use the existing detector catalog and candidate generator.
- Expose `import_array`, `export_array_data` and `export_string_array` inside the crate (`crate/arrow_ffi.rs:54,98,110`). The string exporter takes a finished StringArray. Export BooleanArray data through the generic exporter.
- Extend `execution/native/_text_redact_kernel.py:143` for detector order. Reuse the token eligibility check in `execution/native/_text_mask_native_splice.py:99`. Make the candidates and legacy splice loaders consume the same bound compatibility result (section 10a).
- Use `detection.detectors.iter_spans` and `execution/_strategies/_text_redact.py:198` for the text_redact fallback. Use the existing text_mask callback for its declines, notices and fail-closed behavior.
- Reuse `execution/native/_chunked_evidence.py:120` for backend selection and its fold at line 130. Extend the error parser in place at `execution/native/_crypto_ext.py:369`.

## 3. Guarantee and non-goals

1. With the new capability, splice eligible text_redact cells over Arrow on all four native routes. Preserve oracle bytes for literal tokens, detector labels, duplicates and request order. Section 4 defines selection and literal eligibility.
2. Preserve nulls and the existing Python result for ineligible cells and configurations. Preserve the private wrapper's stringification of integer, float and Boolean input. Keep the public string-source admission gate.
3. Move text_mask's supported redact and passthrough configurations to the same core. Preserve gap policy, warnings, sub-floor counts and errors. Keep the existing path for other configurations, including hybrid FF1.
4. Eligible cells cross the new boundary in Arrow buffers. Inside the additive splice helper, Python materializes only declined cells for repair. Route reconstruction can materialize the returned column. Keep legacy behavior on capability skew as specified in section 10a.
5. For an admitted nonempty column, report Rust if it spliced at least one real input cell. Preserve each route's admission declines, reasons, empty-input behavior and branch counts.

NER admission, new detectors, parallel execution and the pandas handlers are outside this change.

## 4. Enumerations

### 4.1 Routes

| Route | Execution seam | Result transport |
|---|---|---|
| Unified | `physical/_shadow_operators.py:422`, shared operator step | Accumulate positive splice evidence across batches. |
| Chunked | Same step, `native/_chunk_masking.py:263` | Fold batch evidence. Count branch activation separately. |
| Sequential | `_sequential_native.py:469,487` | Keep values, call counts and text_mask notices. Accumulate splice evidence. |
| Out-of-core | `out_of_core/_text_redact_native.py:224`, `_text_mask_native.py:250` | Validate output, accumulate evidence and merge notice counts once. |
| Full-frame oracle | `TextRedactHandler.run`, `TextMaskHandler.run` | Reference bytes and diagnostics. |

### 4.2 Exit paths of the new call

| ID | Condition | Result |
|---|---|---|
| E1 | Companion absent, base agreement fails, or candidates check fails | Use full Python detection and splice. Keep the route's admission result. An admitted helper returns `ran=False`. |
| E1b | Base agreement and the candidates check pass. The additive entry is missing or fails its probe. | On a wheel with S0, both legacy detectors decline a row whose byte length exceeds the u32 offset limit. For older wheels, the Python wrapper also sets those rows aside before either legacy detector runs. Use Python detection and splice for those rows. For fitting rows, use the bound candidates and Python splice. Eligible text_mask can use a legacy splice only after its own check passes (section 10a). |
| E2 | Public text_redact selection is absent or `detectors: []` | Normalize to `None`, run all built-ins and mask a known email. Only a direct private call with resolved `()` means zero detectors. It returns stringified values and nulls with `ran=False`. |
| E3 | Null input | Null output in place. No decline or splice credit. |
| E4 | Cell fails Rust eligibility | Mark the row for Python repair. Also repair any large_string cell whose length cannot be represented by the detector's u32 offsets. A required token that cannot encode as UTF-8 selects today's path before calling Rust. |
| E5 | Eligible non-null row | Return its Rust splice, including unchanged text when no span matched. Count the row as executed. |
| E6 | Boundary call fails after a successful probe | Translate to a fixed registered error. No retry on the candidates or Python path inside the helper. Route handling is in section 5.3. |
| E7 | Malformed return, mask, validity or row coverage | Raise `text_splice_output_invalid`. Validate before scatter and verify null positions after scatter. |

### 4.3 Codes

Declare five reasons in the ExecutionError declaration block of `reasons/runtime/_part3.py` (the block that starts `_d = _catalog.runtime("ExecutionError")`, line 449 on 9f7bb1f4a). Give each a fixed summary and `since=UNRELEASED`. Export them with the other runtime symbols. Declare the engine reasons in S1b. Name each identity in its fragment as an exact code span.

- `runtime/text_splice_unsupported_type`
- `runtime/text_splice_catalog_mismatch`
- `runtime/text_splice_contract_mismatch`
- `runtime/text_splice_unknown_detector`
- `runtime/text_splice_output_invalid`

Use the last code for an unknown boundary failure. Release prep owns the registry version, manifest, consumer contract and release fixture (`CONTRIBUTING.md:57`). Run the release pin and registry renumber checks from CONTRIBUTING.md. No new route reason is needed.

### 4.4 FK shapes

Keep the existing FK admission and routing rules. This row changes the execution of an admitted text column.

### 4.5 Fields

| Field | Handling |
|---|---|
| `detectors` | The handler, step and out-of-core resolver all normalize an empty public selection to all detectors (`_strategies/_text_redact.py:109`, `native/_operator_params.py:231`, `out_of_core/_mask_group_b.py:234`). Sequential receives the handler's resolved selection. |
| `token` | Admission accepts a Python string. Share text_mask's UTF-8 check for literals the splice needs. If a required literal fails, preserve today's helper behavior, including success for a no-match cell. |
| `label_token` | In label mode send only the per-detector labels. Do not encode, check or pass the unused token. Otherwise use the literal token. |
| `ner` | Keep the config rejection in `native/_operator_config_rejections.py`. |

### 4.6 Output surfaces

Pin masked bytes, null positions, row order and schema against the oracle. Pin the run card and quality metrics against section 5.4. Public errors carry a registered code and fixed text. Keep values out of warnings, Job.log and output diagnostics. Update `docs/execution-backends.md` and the evidence statement in `docs/compatibility-contract.md:1047-1052`.

## 5. Design notes

### 5.1 One core with a replacement per detector

Use one outcome type: `SpanOut::Verbatim` or `SpanOut::Replace(literal)`. Pass `detect_splice_cell(text, indices, outs_by_catalog_index, gap_out)` to the existing sweep. Pass the resolved span outcomes and the independent gap outcome to its writer. Empty gaps emit nothing.

For text_redact, every requested span gets the token or its detector label. Extract the label formatter from `execution/_strategies/_text_redact.py:216`. Use it in both the oracle splice and the Python outcome builder through the strategies package export. AT-1 pins the literal `[REDACTED:email]` independently of both callers. The gap outcome is Verbatim. For text_mask, resolve the strategy for every requested built-in before filtering to Rust IDs. A Python-only detector must still participate in the legacy mixed-detector path. Resolve the unmatched policy independently. A redacted gap gets Replace(token) even if every span is Verbatim. If no span matches a nonempty cell, apply the gap outcome once. For example, email passthrough with redacted gaps turns `before a@b.com after` into `<X>a@b.com<X>` and `plain` into `<X>`.

### 5.2 Arrow boundary

Add `text_span_splice(values, *, detector_ids, outs, gap_out, catalog_version, splice_contract_version, native_threads=None)` and `text_span_splice_contract_version()` to the ABI 3 wheel. On the wire, use None for Verbatim and a string for Replace. An empty replacement string is valid. Pair each requested ID with one outcome. Accept repeated IDs with identical outcomes. Reject conflicting outcomes in either order. Reject malformed outcomes and unequal ID and outcome counts. Use a fixed text_splice_output_invalid error for these wire failures. Resolve names to catalog indices once per call. Reject unknown IDs. Keep both legacy exports and their signatures for the lifetime of ABI 3. Apply the new wire checks only at the new entry. The old detect wrapper resolves repeated IDs with its existing last-assignment rule before calling the shared core.

Inspect each original Python version object before numeric extraction. Require exact Python int type and equality to the expected value, including at probe time. Reject bool, int subclasses, strings and out-of-range integers. Map failure to the corresponding catalog or splice contract code. The catalog version is 2 at the anchor. The new splice contract version is 1.

Import each input Array once. Accept string and large_string. Reject other Arrow types with the registered unsupported-type code. The detector offset guard is in the shared predicate, not at each export (S0). `is_eligible` in `crate/text_redact/detect.rs:10` also returns false when `text.len()` exceeds `DETECTOR_OFFSET_LIMIT`. The production value is `u32::MAX as usize`, so every end offset that `candidates_for_cell` narrows at line 35 fits. All three callers use this predicate: `text_redact_candidates` (`pyboundary.rs:93`), `detect_splice_cell` under `text_mask_detect_splice` (`text_mask.rs:109`) and the additive entry. The two legacy exports return their existing `None` decline for an oversized cell. Every released core already routes `None` to the oracle path (`_kernels_scalar.py` candidates loop, `_text_mask_native_splice.py` fallback). The additive entry sets the decline bit. No export narrows an offset before this check. Route the narrowing at line 35 through one `narrow_offset` function. A crate feature `test-detector-offset-limit` lowers the limit to 64 bytes for test wheels only, and under that feature `narrow_offset` wraps at the reduced width, as `as u32` wraps at the real one. A test wheel therefore reproduces the production defect when the predicate check is missing. A Rust unit test without that feature asserts the production value. Extend `decoy-engine-native/scripts/parity_smoke.py`, which every release wheel runs, to require a non-None candidate list from `text_redact_candidates` for a 65-byte ASCII email. A release wheel built with the test feature then fails its smoke step. The crate enables Arrow FFI validation (`Cargo.toml:30-37`). Detach the loop only after importing the buffers and owning the options. Keep Python objects outside the detached loop.

In the common case return one pair of arrays in a one-piece sequence. Larger results use the same sequence format. Each pair holds a StringArray and a BooleanArray. Together the pieces cover the input slice once. Start a fresh piece before appending a row whose actual UTF-8 output would overflow the cumulative string offset. Use checked sizes for replacement expansion. Bound each input call by 65,536 rows as well. Flush both builders at the same row. Finish each string builder before export. Each mask element is true only for a non-null declined cell. Limit the initial buffer reservation to the checked piece size. An input slice can have a large backing buffer even when the output fits. Test the byte ceiling at a reduced value without changing the production limit. Obtain the byte ceiling from the existing Arrow offset policy for Python assembly. Exercise the Rust builder with the same ceiling via its internal test seam. A single row cannot be split. Preserve the old string builder's behavior for an individually unrepresentable value, with a fixed value-free failure if it exceeds the real offset domain. A cell larger than a test batching target but representable in production can occupy its own piece.

### 5.3 Python side

The new path takes public empty selections only after route normalization to None. Reserve the zero-detector shortcut for a direct text_redact call with a resolved empty tuple. A text_mask call with zero span detectors must still apply its gap policy.

Change `requested_rust_ids(None)` to expand `_SPAN_DETECTORS` in insertion order, filtered to `SUPPORTED_IDS`. Explicit lists keep first-seen order. Ignore unknown names as the oracle does. Keep catalog order for interpreting Rust candidate indices. The Python merge still replays the requested order (`_text_redact_kernel.py:186-197`). If a known Python detector lacks a Rust implementation, keep its existing candidate/merge path. S2a builds text_mask's per-ID outcomes in the order returned by the shared resolver.

1. Resolve E1, E1b, the private zero-detector case and literal eligibility. Before any legacy detection, apply the shared Python byte-length guard in section 10a. It protects wheels older than S0. An S0 wheel also declines those rows in Rust. Keep non-string wrapper inputs on the old null-aware stringification path. Preserve string output for large_string and private empty selections.
2. Walk chunks and offset slices in input order. Pass bounded Arrow slices to the new entry. Require a sequence of pairs. Reject empty pieces on nonempty input. Check complete row coverage. Apply the shared validator in step 3 to each pair. Match each piece to the corresponding source slice. A zero-row input yields a typed empty string array.
3. In one shared `_checked_splice_output`, first require a Boolean Array of exactly the corresponding input length, with zero null mask elements. Forbid a true bit on null input. Then require a string Array of that length, null exactly where input is null or the mask is true. A missing or extra row, wrong type or wrong validity takes E7 before repair.
4. Filter only true positions. Apply the existing strategy fallback once per declined cell. Scatter in order. Use wide offsets for the scatter intermediate if repaired rows expand. Reuse `split_narrow_text` in `src/decoy_engine/_arrow_types.py` to cut wide intermediates before narrowing. Check final null positions against the input, including after any predicate write-back. Preserve empty and all-null types at route assembly. Inside the additive helper, keep eligible input and output off Python lists. AT-9 ends at the helper return. Unified reconstruction can use its existing selected-row or whole-column list conversion at `_unified_slice_evidence.py:188,218`.
5. Keep a single Array when it fits. Otherwise retain the ordered string chunks. Never concatenate into one int32 domain unless the sum of the sliced payload bytes fits. The old `pa.array(list, type=pa.string())` can itself return a ChunkedArray on aggregate overflow. Sequential already consumes either with `.to_pylist()`. Return `(values, ran)` for text_redact and `(values, notices, ran)` for text_mask. OR actual splice evidence over all pieces.
6. At unified admission, compare the resident and round-trip ChunkedArrays directly (`_unified_slice_admission.py:390-399`). Keep the all-null resident exemption. Otherwise require equal types and logical values with `ChunkedArray.equals`. Compare across chunk boundaries without calling `combine_chunks()` on either side. Carry chunks through table consumers. Widen the result annotations on StepResult, NativeResult and their consumers. Keep the conditional path for other strategies intact. Update unified `physical/_shadow_assembly.py:69` to accept chunked text parts and preserve empty/all-null schema rules. For text_redact with a predicate, skip the unconditional source combine at `native/_operator_step.py:540`. Return the original chunks on zero selection. Otherwise scatter over aligned source, mask and replacement slices. Size the result for selected replacements plus retained rows. Keep original positions for unselected rows.
7. At a RecordBatch boundary, assemble already-masked columns into a Table and use aligned row slices (Table.to_batches) if the result needs several string chunks. Out-of-core currently insists on one Array per column at `_text_redact_native.py:230` and `_text_mask_native.py:264`. Validate the logical column type and length there. Feed one Array per aligned slice to batch assembly at `out_of_core/_mask.py`. Preserve an empty batch and its schema for zero-row input. Mask each original batch once. Count its decisions and notices once. Pair each masked piece with the raw slice at the same row offset and length. In the single-read driver, remove the pre-mask loop that calls `joiner.stage_batch(raw_batch)` at line 331. In the loop that appends each masked piece to the payload store, call `stage_batch(raw_slice)` once on every incoming joiner. Collect vault pairs before FK replacement. Validate the masked piece and preserve schema reconciliation before append. In phase 3, keep both cursor reads at the stored piece's row number and length. In the rewrite pass, collect the same vault pairs and call each joiner's `join_batch` with the immutable raw slice as `key_source`. Yield every piece. Preserve the single-batch result for existing callers when it fits.

**Boundary errors.** Extend `_translate_compiled_kernel_error` in `native/_crypto_ext.py:362`. Keep its sole `str(exc).partition(": ")` assignment in that function. Dispatch by caller family. FPE delegates there for its two determinism codes. Preserve crypto's extra type mapping and each legacy family's unknown-error behavior. For splice, match the prefix only against the registered splice reasons. Construct the mapped ExecutionError from the registry symbol and its fixed summary. Ignore all detail and map unexpected exception types or codes to `text_splice_output_invalid`. E7 uses the same fixed factory. Raw Rust errors from the new interface also have fixed messages. Raise the engine error after leaving the handler so cause and context are empty. Chunked, sequential and out-of-core propagate the fault. The unified coordinator's existing generic reroute uses the full-frame oracle. Test both the local exception and the route outcome.

Remove `audit::execution/native/_fpe_ext.py::_translate_compiled_fpe_error::str(exc)::assign` from `engine-exception-text-copies.json`. Keep the crypto key in place. Lower AUDIT_PARITY from 100 to 99 and total copies from 107 to 106. Remove the obsolete FPE producer site `execution/native/_fpe_ext.py::_translate_compiled_fpe_error::kw::code` from the F29 producer fixture and its baseline (1,382 to 1,381 rows and 1,212 to 1,211 distinct keys). In S1b remove the matching `("execution/native/_fpe_ext.py", "_translate_compiled_fpe_error")` entry from `ADAPTERS` in `tests/sentry/test_reason_registry.py:185`. This lowers the adapter total from 102 to 101. Run the unused-adapter guard at line 295. Use explicit registered symbols in new factories. Do not move the remaining crypto producer sites. Run the live census, baseline registry equality, F29 guards and `scripts/dev/ratchet_check.py` against the merge base. Keep all other inventory keys and maxima fixed.

**Recording.** The step carries `ran` and the existing notices on StepResult. For text_redact, record whether the `when:` predicate selected any row independently of `ran`. The zero-selection return at `_operator_step.py:542` did no strategy work. Selected rows masked on Python activate the branch even when every Rust cell declined. Keep the existing unmasked count, the absence of a never-activated strategy, and other strategies' counting rules (`_chunk_masking.py:268`, `_chunked_evidence.py:172`).

Add optional `ran` to NativeResult. Sequential records each call once and ORs `spliced` with the result. Replace the text_redact recorder at `execution/_sequential_native.py:470` in S1c and the text_mask recorder at line 487 in S2a. Keep both replacements at zero net lines. Preserve text_mask notice counts through the step, `execution/_sequential_native_text_mask.py:65` and the out-of-core accumulator. Keep the key and its cleanup in their current owners when moving the Arrow fast path ahead of list conversion. Emit the existing passthrough warning once per applicable nonempty cell, including on the new Arrow path. For legacy text_mask, count successful Rust splice results before Python fills declined rows. Candidates alone and hybrid FF1 with Python splice give no splice credit.

### 5.4 Route label

In the operator registry, change only the planned backend to RUST_COMPANION for the strategy in its slice. Keep required_kernel=None and positive_kernel_evidence=False. The latter would otherwise reject a legitimate idle unified run (`execution/_unified_slice_evidence.py:125`). Use the existing `executed_backend` selector when an admitted helper books rows. Supply its planned backend, native_admitted=True and kernel_idle equal to the absence of any actual splice. Call through a layer-safe public export. Do not duplicate this choice in the sequential entry at `_sequential_native_decisions.py:62` or the two out-of-core entries at `_text_redact_native.py:112` and `_text_mask_native.py:132`.

| Case | Unified and chunked | Sequential | Out-of-core |
|---|---|---|---|
| An admitted batch splices a real cell, including via a checked legacy text_mask entry | rust_companion | rust_companion | rust_companion |
| Admitted work books rows. Every batch is idle, including candidates with Python splice. | arrow_python | arrow_python | arrow_python |
| Companion absent or source/config declined. Route books a decline on nonempty input. | Keep route label and reason. Admitted Python work uses arrow_python. | python_scalar and existing reason | python_scalar and existing reason |
| Nonempty handler bypasses the sequential recorder | Follow route admission. | none, zero native calls and existing reason | Follow route admission. |
| No rows | Preserve route's empty behavior and idle label where emitted. | none and route-owned reason | none and route-owned reason |

The unified evidence flag and the chunked fold already retain a positive batch. Use a sticky flag on the other decisions. Route owners still determine zero-row and admission-decline records. `native_calls` counts helper calls, including a booked all-null call. A capability probe or its known-answer call never counts as job execution.

## 6. Placement

| Change | Location | CODEMAP placement and size constraint |
|---|---|---|
| Shared core, exports and Rust tests | `crate/text_mask.rs`, `crate/arrow_ffi.rs` | Native crate. Restrict the FFI edit to exposing existing functions. |
| Label formatter | `execution/_strategies/_text_redact.py` and the strategies package export | Keep the format with the oracle splice. Reuse it for the native wire literals in S1b. |
| Probe, order, UTF-8 guard and Arrow repair | `execution/native/_text_redact_kernel.py`, `_text_mask_native_splice.py`, `_kernels_scalar.py` | Native companion bridge (CODEMAP:273). Both strategies call the same boundary validator and byte-aware assembly. |
| Error mapping and reasons | `execution/native/_crypto_ext.py`, `_fpe_ext.py`, `reasons/runtime/_part3.py` | Extend the existing parser in place. Use the runtime registry for public messages. |
| Step, evidence and assembly | `execution/native/_operator_step.py`, `_chunk_masking.py`, `_chunked_evidence.py`, native package export, `execution/physical/_shadow_operators.py`, `_shadow_batch_runner.py`, `_shadow_assembly.py` | Existing step and evidence owners. Use the existing Arrow width helpers. |
| Admission comparison, evidence and result transport | `execution/_unified_slice_admission.py`, `execution/_operator_registry.py`, `_sequential_native_ops.py`, `_sequential_native_text_mask.py`, `_sequential_native.py`, `_sequential_native_decisions.py` | Pipeline spine and routes. Keep the 700-line sequential pin. Keep the ops file (593 lines) at or below 600 so it needs no dense-module entry. |
| Batch dispatch and streaming | `execution/out_of_core/_text_redact_native.py`, `_text_mask_native.py`, `_mask.py`, `_stream_driver.py`, `_rewrite_pass.py` | Existing route owners. Keep one common batch emitter for aligned output pieces. |
| Tests | New `tests/unit/execution/native/test_text_span_splice.py`. Extend existing native, parity and sentry tests. | Unit tests mirror the source package (CODEMAP:306). Put raw wire and helper tests in the new unit file. Put route assertions in their existing suites. Keep the unit file within the module-size budget. Keep edits to existing oversized suites size-neutral or smaller. |
| Detector offset guard | `crate/text_redact/detect.rs`, `Cargo.toml` feature, `decoy-engine-native/scripts/parity_smoke.py` | S0. Change the shared predicate only. No export signature changes. |
| Benchmark | `scripts/bench_text_redact.py` | Extend its worker and equivalence check in S1b. The worker calls the helper directly. Keep the existing matrix gates. |
| Docs | `docs/execution-backends.md`, `docs/compatibility-contract.md` | Describe each strategy's evidence change and both skew directions. |
| Release fragments | New files in `changelog.d/`: `text-detector-offset-guard.md` (S0), `text-span-splice-core.md` (S1a), `text-chunked-transport.md` (S1t), `text-redact-splice-reasons.md` (S1b), `text-redact-rust-splice.md` (S1c), `text-mask-arrow-splice.md` (S2a). S2b adds tests and evidence only and needs no fragment. | S0 describes the legacy detector decline for oversized cells. S1a describes the additive interface and ABI 3 compatibility. S1t describes chunk-carrying text results with no byte change. S1b names all five section 4.3 identities. S1c describes the text_redact Rust splice and its execution-label change together. S2a describes text_mask execution labels. |

No new production Python module. Keep the native package at its fan-out freeze of 55. Run import-linter and the module-size sentry. Keep new cross-package uses on the public API without introducing an eager import cycle. No census, allowlist or cap increases.

## 7. Defect classes

### 7.1 Plan-contract classes

| Class | Guard |
|---|---|
| Public values or secrets | Fixed raw and translated errors. Inject a sentinel through the live boundary in AT-7. |
| Cleanup and concurrency | Arrow owns the buffers until the detached loop returns. Extract options before releasing the GIL. No external writer or mutable job state in Rust. |
| Route drift and silent fallback | AT-5, AT-6 and AT-10 exercise actual route seams. |
| FK integrity | Existing admission and key handling stay in force. Exercise the sequential payload-next-to-key regression. |
| Untrusted output | AT-3 tests the complete mask and both validity checks. |
| File access and state | No file access in the splice. Out-of-core assembly forwards each masked row once. |
| Weak tests and frozen output | AT-1b counts actual rows. AT-4 checks both gap and span bytes. AT-9 measures the complete helper. |

### 7.2 Recurring-defect catalog

| Class | Check |
|---|---|
| Anchored regex | No new regex. Keep oracle detector and validator tests. |
| Strict wire and stored types | Exact integers for both versions, strict outcomes and a non-null Boolean mask. AT-3 and AT-6. |
| Exception context | AT-7 inspects the translated error after the handler exits. |
| Versioned reads | Probe the ABI, catalog and splice contract before using the new capability. |
| Normalized scanners | Use the live census and its merge-base ratchet. No new scanner. |
| Private imports | Check the public selector export and layer contracts. Other coded parsers at `execution/native/_group_key_ext.py:103` and `_index_ext.py:95` are existing follow-ups. |
| Hidden CI failures | Build the companion. Require the real-kernel tests to execute. Record skips. Run the Dell perf gate explicitly. |
| Trust class | The raw extension validates its wire input. The engine separately validates producer output. |
| Final-head mutations | In S2b rerun M1 to M11 on the final implementation head, including M2a and M6 after S2a. Record the SHA and the failing assertion. |
| Allowlisted helpers | Exercise route helpers through their callers and run the physical-seam sentry. |
| Raised pins | Run size, layout, census, release and merge-base guards. Apply the exact reductions in section 5.3. |

## 8. Acceptance tests

| ID | Test and decisive observation | Slice |
|---|---|---|
| AT-1 | Compare native text_redact to the handler. Cover every built-in, adjacent and overlapping spans, duplicates, unknown names, permutations, nulls, empty and long strings. Include both label modes, two literal tokens and the overlap cases on 12345-6789 and -2283038836. Direct private resolved () preserves a known email and reports false. The same input with None masks it. | S1b |
| AT-1b | Wrap the real entry after its probe. Use uniquely identifiable rows across at least two batches. Record each input slice and its returned mask. Mark each eligible output in a second instrumented run and require every mark at the same output position. This detects a discarded Rust result even when the oracle bytes would agree. Assert every eligible row occurs once in the Rust output and every ineligible non-null row occurs once in the Python repair. Include nulls, empty strings, 0x1c through 0x1f and non-ASCII. An aggregate ran flag cannot satisfy this test. | S1b |
| AT-2 | Compare bytes and validity at batch sizes 1, 7, 65,536 and whole input. Test thread budgets 1 and 4 at the new boundary. Both run the single-thread loop. | S1a raw entry, S1b wrapper |
| AT-3 | Exercise string, large_string, offset slices, uneven chunks, zero chunks, empty and all-null input. Raw int64 input gets ValueError with text_splice_unsupported_type. Wrapper integer, float and Boolean inputs retain Python stringification. With a required surrogate token a no-match cell returns plain text. With label mode the same token and a known email give the detector label on Rust. | S1a raw entry, S1b wrapper |
| AT-3 (raw capacity) | In Rust, lower the internal builder ceiling. Make replacement expansion split one input slice. Assert multiple aligned string and Boolean pieces, bounded offsets, complete ordered bytes and validity. Include a representable row larger than the test ceiling. | S1a |
| AT-3 (capacity) | S1t runs the consumer half with a stub helper that returns aligned multi-piece output, plus the current helper for byte parity. S1b runs the builder and scatter half on the helper. S1c and S2a run the full case through the routes with the real helper. Lower the batching byte ceiling. Use the same reduced ceiling at the builder, scatter and consumer assembly so the aggregate test cannot pass by concatenating. Expand many short matches with a long token within one input batch. Separately exceed the ceiling across individually fitting batches. Include an expanding declined row and a retained predicate row. Assert bytes, schema, row order, nulls and counts through chunk-capable consumers and single-Array batch sinks. Force one four-row child batch into two two-row payload pieces. Give the child an incoming FK with four distinct raw keys and known parent replacements. Force expansion on the text column. Vault a separate non-key string column with a hash strategy, a namespace and four distinct values. This fixture meets the existing vault gate in `out_of_core/_vault_collect.py:123`. Use the single-read spill path. Assert both stored boundaries, both resolved key arrays in row order and all four (namespace, expected hash, raw value) vault entries against the unsplit oracle. Check counts once for the original batch. Check the same output and pairs through the rewrite pass. Run the detector-offset cases below separately from this byte ceiling. | S1t consumers and FK staging, S1b helper, S1c redact routes, S2a mask routes |
| AT-3 (unified admission) | Start at unified admission with several fitting string chunks. Their combined input exceeds the reduced byte ceiling. Replace long emails with a short token so the whole masked result fits. Observe both logical columns during admission. Fail on a whole-column combine of either above the ceiling. Require unified execution and oracle output, including nulls and schema metadata. At the comparison seam, accept equal values with different chunk boundaries. Retain type and value mismatch declines and the all-null exemption. | S1t |
| AT-3 (detector offsets) | Lower only the detector limit (`test-detector-offset-limit` wheel or the Rust test seam). In S0 call `text_redact_candidates` and `text_mask_detect_splice` directly with the oversized email and a short email. Require `None` for the oversized cell and a valid result for its neighbour. Mutation M11 (drop the length check from `is_eligible`) must fail this case. Use a private large_string array with one long ASCII email whose end exceeds that limit. Include null and a short email. Expect one short token per email, in order. Test the additive decline bit and Python repair. Repeat on E1b with checked candidates and checked legacy detect-splice. Spy after probing. Neither legacy detector receives the oversized value. Verify one oracle repair for it and the expected job call for the short email. With only the oversized row, require false splice evidence. | S0 legacy exports, S1a raw additive, S1b redact wrapper and candidates, S2a mask candidates and legacy detect-splice |
| AT-3 (invalid output) | Inject wrong pair shape, missing/extra pieces, wrong output type/length, non-Boolean mask, wrong mask length, a null mask element beside a true bit, true on null input, unexpected null output and missing required nulls. Force a bad final null position after scatter. Each raises text_splice_output_invalid at the wrapper. | S1b redact, S2a mask |
| AT-4 | Pin text_mask email passthrough plus redacted gaps with token `<X>`. Input `before a@b.com after` gives exactly `<X>a@b.com<X>`. A nonempty no-match cell gives `<X>`. Empty input gives the empty string. Also cover redacted spans with verbatim gaps, adjacent spans, warning multiplicity and aggregate sub-floor notices. Compare the legacy and new entries and the handler. | S1a core, S2a routes |
| AT-5 | Run every applicable section 5.4 case on all four routes. Submit public text_redact `detectors: []`, token `<X>` and `mail a@b.com now`. Require `mail <X> now` and rust_companion on each current-wheel route. For text_mask set every built-in to redact and gaps to passthrough for the same assertion. Check absent companion, non-string admission decline, no rows, all-null and all-ineligible admitted columns. Verify bytes, schema, label, decline reason and helper counts. On sequential text_redact, test three separate invalid configs: `{"token": 5}`, `{"detectors": "email"}` and `{"detectors": 7}`. Require unchanged bytes, none, zero native calls and each existing config reason from `test_phase_d_text_redact_seq.py:179`. In S2a run active text_mask NER against its oracle. Assert the recorder bypass, none, zero calls and its existing reason. Contrast with a booked source decline. Run idle then spliced and spliced then idle across batches. S1c is the first head where any job route calls the new helper. On that head, mark the helper output after the probe and require the emitted mark together with rust_companion on each route. Require arrow_python for an admitted all-idle column. | S1c redact, S2a mask |
| AT-5 (predicate) | On chunked text_redact select a non-ASCII row containing an email. Assert its masked bytes, unchanged unselected bytes, arrow_python and one branch activation. Select no rows and assert original bytes, arrow_python and no strategy entry. Repeat with a selected no-match Python row so identical output and backend still yield different counts. Preserve the existing chunked text_mask predicate rejection. | S1c |
| AT-6 | At probe time vary callable presence, ABI, catalog version, ordered IDs, contract version and KAT output independently. Reject wrong exact types, including True for version 1. Use the section 10a decision for each bound companion. Include catalog version `"2"`, reordered IDs, an ABI mismatch and a noncallable candidates entry. For a base mismatch, make the rejected candidates stub return an empty candidate list. Also test matching metadata with a missing match, float offsets `(0, 0.0, 7.0)`, or a Boolean index `(False, 0, 7)`. Vary the outer list, cell list and triple container separately. Each malformed answer selects E1 with zero subsequent job calls to the rejected capability. For a compatible wheel, supply correct candidates. Run `mail a@b.com now` with token `<X>`. Assert oracle bytes `mail <X> now` and zero job calls to every rejected capability. Distinguish probes from job calls. Cover a missing additive entry and a failed additive KAT with both passing and failing legacy checks. Assert the selected job entry, bytes and splice credit for each strategy. After a successful probe, inject each version argument independently with bool, string, subclass and wrong integer. Also send an unknown ID past resolution. Assert the raw ValueError code, then the translated engine code. Verify no helper fallback and the route outcomes in section 5.3. Exercise both wheel/core skews in section 10a. | S1a probe and raw codes, S1b translation, S1c route outcomes, S2a mask fallback, S2b both skews on the final head |
| AT-7 | Interleave eligible rows, null, distinct Unicode rows and ASCII controls. Include tab, NUL, DEL and CRLF as eligible controls. Assert ordered bytes against the oracle. Inject known-code detail and an unknown exception containing a unique data sentinel after a successful probe. Require fixed public messages, absent sentinel on exposed error, warning and job-log surfaces, and no cause or context on the translated exception. | S1b redact helper error, S1c redact route surfaces, S2a mask |
| AT-8 | Rust unit tests cover label replacement, Verbatim and both gap outcomes. Use email and IPv4 on `10.0.0.1a@b.com` in both orders. The existing unequal-length test passes on the S1a base and head. The longer email wins. For an exact tie, use npi and us_phone on `2234567891`. Give each detector a distinct replacement literal. Reverse the requested detector order. Assert the winning detector's literal in each order through the real outcome lookup. | S1a |
| AT-8 (raw duplicate IDs) | Call the additive entry with email twice and verbatim gaps. Two identical replacements emit one token. Two Verbatim outcomes preserve the email. Reject a conflict in both orders, shorter and longer outcome lists, and non-string, non-None span or gap outcomes. Assert the fixed wire error. An empty replacement removes the email and yields a valid empty string. Call the legacy detect-splice export on the same email with token `<X>`. Flags `[False, True]` preserve `a@b.com`. Flags `[True, False]` emit `<X>`. | S1a |
| AT-9 | On the Dell under WSL2, use the section 1 fixture and a release wheel. Probe before timing. In a fresh worker, warm up once. Time ten complete helper calls with `perf_counter`. Require median elapsed seconds × 1,000,000 / 120,000 ≤ 3.0. Unpack `(values, ran)` and compare Arrow bytes and validity to full Python outside the timer. Verify the actual entry in an untimed pass and require splice credit. On an all-eligible helper call, forbid per-cell Python repair, input or output to_pylist, and list-backed pa.array construction. Apply the same conversion guard to text_mask in S2a. Unpack its notices separately. | S1b Dell and conversion guard on the helper, S2a mask conversion guard, S2b Dell rerun on the final head |
| AT-10 | Run one corpus end to end on unified, chunked, sequential and out-of-core with the companion built. Include nulls, declines, both label modes and tie strings. Compare bytes, validity and schema metadata with the corresponding oracle route. In S2a compare text_mask diagnostics. Run the section 8 mark-and-discard cases at the sequential output in their assigned slices. | S1c redact bytes and labels, S2a mask, S2b final head |
| AT-11 | Old core with new wheel. Install the engine Python package at the S0 merge base in its own venv with a wheel built from the slice head with `test-detector-offset-limit`. Run that core's own `native_text_redact` and its text_mask detect-splice path on [oversized email, null, short email] with token `<X>`. Require exactly `<X>`, null, `<X>` from each, a None decline from the export for the oversized cell and one oracle detection for it. Run the old core's existing text_redact and text_mask native suites against the same wheel. With M11 applied to the test wheel, the wrapped end offset leaves a suffix or the old core fails while building output, so the test fails. | S0, rerun S1a and S2b |

In S1b update the benchmark worker and equivalence helper to call the new helper directly. Add a distinct Arrow splice worker. Bind baseline8 and new11 to their respective candidates paths. Force full Python in the oracle worker. In each worker verify the expected job entry and excluded entries on an untimed call. Compare complete fixture outputs outside timing. Keep the existing matrix comparisons separate from AT-9. Record the Dell CPU, build SHA, wheel, fixture seed and ten samples.

**Existing regression suites.** S1b adds helper tests only. S1c updates return shapes, spies and byte assertions for text_redact. Update the direct helpers in `tests/native/test_c6c_i_text_redact_kernel.py` and `test_c6c_ii_text_redact_rust.py:72`. Update the resolver expectation at line 648. Keep the non-string case at line 331. Run candidates-only fixtures on an explicitly legacy wheel or stub. In `tests/parity/test_phase_d_audit_no_legacy.py:482`, retarget only the text_redact parameter. Mark an eligible additive result after the probe and check the emitted value. Discarding it must lose the mark. Update the sequential real and routing helpers and the out-of-core marking helpers. Keep consumed-output and mid-run failure tests. Run `test_ooc_text_redact_native_real.py`. These route edits belong to S1c, where the routes switch to the helper. S1b changes no route caller and no backend assertion.

S1c also updates the text_redact spec, planner and executed-backend assertions in the same merge. This includes the all-null expectation at `test_ooc_text_redact_native_routing.py:179` and the real splice at `test_c6c_i_text_redact_chunked.py:70`. Update sibling-column and idle expectations in the C6c chunked and unified suites. Run the existing sequential config-bypass cases at `test_phase_d_text_redact_seq.py:179` as already-green regression guards.

S2a keeps the candidate injection and discard controls for the default FPE/faker text_mask parameter in `test_phase_d_audit_no_legacy.py`. Check the candidate mark in the emitted value and expect arrow_python. Add an all-redact parameter with passthrough gaps. Mark the additive output after the probe. Require the emitted mark and rust_companion. Discarding the output must lose that mark. Exercise the active NER handler bypass in AT-5.

In S1c for text_redact and S2a for text_mask, update `tests/sentry/test_unified_backend_map.py:40` and `tests/native/test_operator_tables_snapshot.py:86,215`. Check both the per-strategy planned backend and the derived companion-strategy set. S2a updates the C6b chunked and unified assertions. Update tuple unpacking, marking fixtures and negative controls in the C6b detection, splice and FPE suites, sequential parity and `test_ooc_text_mask_native.py`. Preserve the per-cell warning at `test_c6b_ii_b_text_mask_splice.py:306` and notice counts on all three call seams. Run the real and marked route suites. Search all direct callers when changing return shapes.

## 9. Named mutations

| ID | Mutation | Witness that must fail |
|---|---|---|
| M1 | Sort same-start spans shortest first. | AT-8 unequal-length email/IPv4 case. |
| M2a | In Rust, use the other tied detector's replacement outcome. | S1a AT-8 expects distinct literals when request order reverses. |
| M2 | In Python, drop the detector ID from a label. | S1b AT-1 checks the exact oracle label. |
| M3 | Shift a declined replacement one position. | AT-7 interleaved values and final validity. |
| M4 | Catch a post-probe boundary failure and use Python. | AT-6 wrapper assertion. |
| M5 | Report the planned backend regardless of execution. | AT-5 all-idle admitted nonempty column. |
| M6 | Replace a Verbatim text_mask span with the token. | AT-4 literal passthrough email between redacted gaps, through the S2a route. |
| M7 | Rebuild eligible output with pa.array from a Python list. | AT-9 deterministic conversion guard. Also run the independent Dell floor. |
| M8 | Set positive_kernel_evidence=True. | AT-5 admitted idle unified column must complete. |
| M9 | Expand None in catalog order. | Python resolver unit test compares to filtered _SPAN_DETECTORS insertion order. |
| M10 | Process only the first input chunk. | AT-3 compares values and validity beyond that chunk. |
| M11 | Drop the length check from `is_eligible`. | S0 AT-3 detector offsets on both legacy exports and AT-11 on the test-limit wheel. |

Run each mutation separately against the unmutated passing tests. Restore it before the next run. S0 runs M11. S1a runs M1 and M2a against AT-8. S1t runs M10 against its consumer cases. S1b runs M2 to M4, M7, M9 and M10 on the helper. S1c runs M5 and M8. S2a runs M6. S2b records M1 to M11, including M2a, again on the final head with both strategies wired.

## 10. Byte changes

No masked-byte change is intended. The S1c and S2a fragments describe the execution-label change in both directions, including the idle case. AT-1, AT-4 and AT-10 gate the byte contract.

## 10a. Frozen contracts

Use the additive capability policy in `docs/native/supported-matrix.md:108`. Keep ABI 3. Bind one compatibility result to the imported companion instance. Share it across the candidates loader (`_text_redact_kernel.py:127`), the legacy loader (`_text_mask_native_splice.py:66`) and the additive probe. Cache success and rejection for that instance. Rebind if the companion changes. Require callable ABI and catalog helpers, the exact ABI string from `_EXPECTED_ABI_VERSION`, exact int catalog version 2, ordered IDs equal to `SUPPORTED_IDS` and a callable candidates entry. Check the base agreement before calling any data entry. Then run the bound candidates entry on [`a@b.com`, `café`, null] for email alone. Require a list of length three. Its first item must be a list containing one tuple of length three. Require `type(field) is int` for all three fields before comparing the tuple to `(0, 0, 7)`. Require each remaining item to be None. This pins the candidates wire shape at `crate/text_redact/pyboundary.rs:99`. Any missing or failing base or candidates check selects E1. No job path may reopen either loader to bypass that result.

After base agreement, require a callable additive entry and contract getter. Check exact int version 1. Run the additive known-answer test (KAT) on [`a@b.com`, `café`, null] with email, Replace(`<X>`) and verbatim gaps. Require one pair of Arrow arrays with string values [`<X>`, null, null] and Boolean mask [false, true, false]. Check lengths, types and validity. Missing capability, version failure or a bad answer selects E1b. A compatible candidates-only wheel can still detect for Python splice.

Before granting legacy splice access, check both bound legacy callables. Exercise each on the synthetic KAT cells with the legacy list signature. For resolved spans pass `[(0, 7, False)]` on the email and empty spans on the other rows. For detect-splice pass email with verbatim false. Use token `<X>` and passthrough gaps for both. Require the list [`<X>`, None, None] from each. On failure, disable legacy splice and use checked candidates with Python splice. Run these checks once per bound instance, outside job counts. Use only synthetic data.

An old core must load both `text_mask_detect_splice` and `text_mask_splice_spans` from the S2a wheel and get its old list shapes, bytes and decline sentinels. Keep the old positional parameters, gap policy and exported semantics. Run the old core against the built S2a wheel in S2b. Spy on both legacy lookups and the actual legacy splice call. Compare its results and warnings to the old oracle. In the reverse direction test the new core against an ABI-3 wheel with candidates and the two legacy symbols. The root guard for this direction is the S0 predicate: both legacy detector exports decline an oversized cell with their existing `None` sentinel, so an old core takes its oracle path (AT-11). At the new Python wrapper, also partition legacy batches before dispatch to candidates or detect-splice. That wrapper guard covers wheels older than S0. Use one guard for both strategies, including hybrid candidates on a current wheel. Measure each non-null row in UTF-8 bytes. For Arrow strings, use the sliced offsets. Send only fitting rows to a legacy detector. Detect and splice each oversized row once with the strategy oracle. Restore positions, validity, warnings and notices. Only rows actually spliced in Rust earn credit. E1b uses candidates and Python splice for text_redact. For eligible text_mask, E1b uses the working legacy Rust splice and reports rust_companion only if that splice produced a non-null cell result. Missing legacy capability keeps the existing Python splice. Never send job data to a wheel with an incompatible ABI via candidates or either splice interface. Keep existing route admission gates distinct from the new capability probe.

## 10b. Pre-mortem

- An overlap can preserve output length while leaking part of a span. AT-8 checks literal bytes for unequal lengths and the winning label for an exact tie.
- A decline mask can silently erase an input row. AT-3 injects that fault before and after repair.
- A row-count bound can miss replacement expansion. AT-3 exercises both a single expanding call and aggregate overflow at actual consumers.
- A detector scan or KAT can look like job execution. AT-1b and AT-5 require job-row evidence.
- A legacy client can silently lose acceleration after a wheel upgrade. AT-6 exercises both directions.
- An old core can call a legacy detector export directly and bypass every Python guard. S0 puts the offset check in the shared Rust predicate, and AT-11 runs the old core itself.
- A merged head can run Rust on jobs while its run card says Python. No route calls the helper before S1c, and S1c carries AT-5.

## 11. Slices

Estimates include changes to existing tests and route assembly. Every slice is R2. Build the companion and run the targeted T2 suites with the real extension. Record test scope, skips, mutations and perf evidence. Code reviewers: Codex and Dennis.

In each slice, write its named acceptance tests first. Run them on the slice base and record the expected failures. Record the passing legacy guards separately. These include AT-4 parity, AT-8 longest-first and last assignment, and the three AT-5 sequential config bypass cases. Implement the slice, rerun its tests and then run its mutations.

Each slice merges separately, in the order S0, S1a, S1t, S1b, S1c, S2a, S2b. Each starts from the merged previous slice. Each slice adds its own section 6 fragment relative to its merge base, except S2b. Run the fragment guard on each head. Bind both existing loaders to base agreement in S1a. Require the bound legacy checks before any job uses legacy splice. This includes S1a to S1c, while text_mask still calls its old loader.

**Activation boundary.** S1b adds the new helper `splice_text_redact(array, *, detectors, token, label_token) -> (values, ran)` in `execution/native/_kernels_scalar.py` (384 lines on 9f7bb1f4a). No production route calls it in S1b. Tests and the benchmark call it directly. `native_text_redact` and every route stay unchanged, so every S1b job runs today's path under today's label. S1c points all four route call sites at the helper, consumes `ran`, replaces the recorder at `_sequential_native.py:470`, sets the planned backend and deletes the old list-based body, all in one merge. The module stays under 600 lines at every head. Job use of the additive entry therefore starts in S1c, the same head that first requires correct attribution in AT-5.

| Slice | Content | Size estimate | Risk and gate |
|---|---|---|---|
| S0 | Detector offset guard. Add the length check to the shared `is_eligible`, the `DETECTOR_OFFSET_LIMIT` constant, `narrow_offset` and the `test-detector-offset-limit` feature. Extend `parity_smoke.py`. Build the old-core venv harness used again in S1a and S2b. Add the S0 fragment. | S, about half a builder-day: about 20-40 implementation lines and 120-180 test and harness lines. | R2. AT-3 detector offsets on both legacy exports, AT-11. Run M11. |
| S1a | Shared Rust outcomes and gap writer. Add the Arrow entry, contract getter, bounded builders and mask export. The entry uses the S0 predicate. Keep both legacy wrappers. Bind the Python probe and existing loaders to one compatibility result. Add the core fragment. | M, about one builder-day: about 300-400 implementation lines and 250-350 test lines. This is the upper edge. If it runs over, merge the Rust half first and the Python binding second. | R2. AT-2 and AT-3 raw boundary, AT-3 raw capacity and detector offsets on the additive entry, AT-4 core, AT-6 bound probe and raw codes, AT-8 core and raw duplicate IDs, AT-11 rerun on the S1a wheel. Run M1 and M2a. |
| S1t | Chunk-capable transport and out-of-core FK staging (section 5.3 steps 5 to 7, consumer side). Widen StepResult, NativeResult and consumer annotations to carry chunks. Make unified admission compare chunked columns without a whole-column combine. Accept chunked text parts in `_shadow_assembly.py`. Scatter predicate results over aligned chunks without the combine at `_operator_step.py:540`. Stage raw slices per stored piece in the single-read driver and pass the immutable raw slice in the rewrite pass. Uses today's helper output, so bytes and labels do not change. Add the S1t fragment. | M, about one builder-day: about 150-250 implementation lines and 200-300 test lines. | R2. AT-3 capacity consumer half and FK staging with a stub multi-piece helper, AT-3 unified admission, existing route parity suites unchanged. Run M10 on the consumer cases. |
| S1b | text_redact helper, not yet on any route. Add `splice_text_redact` (section 5.3 steps 1 to 5): legacy detector Python guard, Arrow walk, `_checked_splice_output`, decline repair and scatter. Add the five registry declarations, error translation, census and adapter deletions, the resolver order fix, the benchmark workers and the S1b fragment. | M, about one builder-day: about 200-280 implementation lines and 250-350 test lines. | R2. AT-1, AT-1b, AT-2 wrapper, AT-3 wrapper, capacity helper half, detector offsets and invalid output, AT-6 redact fallback and translation, AT-7 helper error, AT-9 Dell on the helper. Run M2 to M4, M7, M9 and M10. Run live census and merge-base guards. |
| S1c | Switch text_redact routes and labels together. Point the four route call sites at the helper and delete the old body. Carry `ran` through StepResult and NativeResult. Record predicate branches and update the sequential recorder at `_sequential_native.py:470`. Retain positive out-of-core evidence. Use the shared selector and set `planned_backend=RUST_COMPANION`. Update the existing regression suites, snapshots, `docs/execution-backends.md`, evidence docs and the S1c fragment. | M, about one builder-day: about 150-220 implementation lines and 250-350 test lines. | R2. AT-3 capacity through the redact routes, AT-5 redact including the recorder-bypass cases and the mark-plus-label check, AT-5 (predicate), AT-6 route outcomes, AT-7 route surfaces, AT-10 redact bytes and labels. Run M5 and M8. |
| S2a | Wire text_mask and its three call seams. Preserve legacy evidence, gap behavior, warnings and notices. Update the recorder at `_sequential_native.py:487`, snapshots, docs and text_mask fragment. | M, about one builder-day: about 120-220 implementation lines and 200-300 test lines. | R2. AT-3 mask capacity, legacy detector offsets and validation, AT-4 routes, AT-5 mask including NER bypass, AT-6 mask fallback, AT-7 mask errors, AT-9 mask conversion guard and AT-10 mask, including hybrid candidate and all-redact splice marks. Run M6. |
| S2b | Final-head verification. Add the two skew runs in section 10a as CI tests: old core against the S2a wheel and new core against an ABI-3 wheel with only candidates and the legacy symbols. Replay M1 to M11, including M2a, on the S2a head and record the SHA and each failing assertion. Rerun AT-9 on the Dell for both strategies and AT-10 end to end. No production code. | S, about half to one builder-day: about 80-150 test and harness lines plus the Dell run. | R2. AT-6 both skews, AT-9 rerun, AT-10 final head, AT-11 rerun. If a skew or mutation fails, the fix goes in a new slice with its own gate, not in S2b. |

## 12. Open questions for the owner

The plan assigns text_mask evidence to S2a so the label changes with the implementation. The open scheduling choice is whether to defer that evidence change to ROUTE-LABEL-TRUTH. S2a and S2b assume it ships here.
