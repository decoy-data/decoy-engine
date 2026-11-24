Status: plan (revision 5, 2026-11-24, S1 split into S1a and S1b; anchored to cb06f318e)

# TEXT-REDACT-RUST-SPLICE: detect and splice text_redact spans in Rust over Arrow

Owner: Cam. Roadmap group: mask, 1.0.x. Scope: decoy-engine. The CLI picks up the change with its next engine pin. Risk: R2. A missed span can expose a data value. The release contract freezes masked bytes.

Paths starting with `execution/`, `transforms/` or `reasons/` are under `src/decoy_engine/`. `crate/` means `decoy-engine-native/src/`. The review worktree is at `0acdf0f8b`. Its only diff from `cb06f318e` is the original plan. Section 1 records historical measurements. The new entry, its mutations, end-to-end parity and the Dell floor still need implementation evidence.

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

The last run reported zero declines and zero differences from literal-token text_redact on that corpus. AT-1 and AT-10 cover the broader contract. AT-1 parity already passes on Python. AT-1b and the per-route labels in AT-5 distinguish the new implementation.

### Overlap with RUST-DATE-TEXT (1.2)

That row owns full Unicode detection and parallel text kernels. This row releases the GIL around one Rust loop. The new entry accepts the existing thread budget and resolves it with `NativeThreadBudget::resolve_on_host` (`crate/arrow_ffi.rs:602`). It runs one thread.

## 2. Established solutions

The engine already separates detection, overlap resolution and replacement. `crate/text_mask.rs:102` detects candidates, sorts by start and decreasing length, and keeps non-overlapping spans. Request order breaks exact ties. Extend that sweep and its writer at lines 52 and 62. Both legacy exports use the same writer. Preserve the legacy resolved-span API's own eligibility rules.

### Reuse inventory

- Use `crate/text_redact/detect.rs:10` for eligibility. The live predicate excludes non-ASCII and ASCII controls 0x1c through 0x1f. Use the existing detector catalog and candidate generator.
- Expose `import_array`, `export_array_data` and `export_string_array` inside the crate (`crate/arrow_ffi.rs:54,98,110`). The string exporter takes a finished StringArray. Export BooleanArray data through the generic exporter.
- Extend `execution/native/_text_redact_kernel.py:143` for detector order. Reuse the token eligibility check in `execution/native/_text_mask_native_splice.py:99`. Keep the existing candidates loader for legacy paths.
- Use `detection.detectors.iter_spans` and `execution/_strategies/_text_redact.py:198` for the text_redact fallback. Use the existing text_mask callback for its declines, notices and fail-closed behavior.
- Reuse `execution/native/_chunked_evidence.py:120` for backend selection and its fold at line 130. Extend the error parser in place at `execution/native/_crypto_ext.py:369`.

## 3. Guarantee and non-goals

1. With the new capability, splice eligible text_redact cells over Arrow on all four native routes. Preserve oracle bytes for literal tokens, detector labels, duplicates and request order. Section 4 defines selection and literal eligibility.
2. Preserve nulls and the existing Python result for ineligible cells and configurations. Preserve the private wrapper's stringification of integer, float and Boolean input. Keep the public string-source admission gate.
3. Move text_mask's supported redact and passthrough configurations to the same core. Preserve gap policy, warnings, sub-floor counts and errors. Keep the existing path for other configurations, including hybrid FF1.
4. Eligible cells cross the new boundary in Arrow buffers. Python materializes only declined cells for repair. Keep legacy behavior on capability skew as specified in section 10a.
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
| E1 | No usable candidates companion | Keep current admission and Python behavior. An admitted helper returns `ran=False`. |
| E1b | Candidates available. New splice capability fails its probe. | text_redact keeps candidates plus Python splice. For text_mask use a working compatible legacy splice when available. See section 10a. |
| E2 | Public text_redact selection is absent or `detectors: []` | Normalize to `None`, run all built-ins and mask a known email. Only a direct private call with resolved `()` means zero detectors. It returns stringified values and nulls with `ran=False`. |
| E3 | Null input | Null output in place. No decline or splice credit. |
| E4 | Cell fails Rust eligibility | Mark the row for Python repair. Also repair any large_string cell whose length cannot be represented by the detector's u32 offsets. A required token that cannot encode as UTF-8 selects today's path before calling Rust. |
| E5 | Eligible non-null row | Return its Rust splice, including unchanged text when no span matched. Count the row as executed. |
| E6 | Boundary call fails after a successful probe | Translate to a fixed registered error. No retry on the candidates or Python path inside the helper. Route handling is in section 5.3. |
| E7 | Malformed return, mask, validity or row coverage | Raise `text_splice_output_invalid`. Validate before scatter and verify null positions after scatter. |

### 4.3 Codes

Declare five reasons in the ExecutionError block at `reasons/runtime/_part3.py:438`. Give each a fixed summary and `since=UNRELEASED`. Export them with the other runtime symbols. Name each in the changelog fragment:

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

For text_redact, every requested span gets the token or its detector label. The gap outcome is Verbatim. For text_mask, resolve the strategy for every requested built-in before filtering to Rust IDs. A Python-only detector must still participate in the legacy mixed-detector path. Resolve the unmatched policy independently. A redacted gap gets Replace(token) even if every span is Verbatim. If no span matches a nonempty cell, apply the gap outcome once. For example, email passthrough with redacted gaps turns `before a@b.com after` into `<X>a@b.com<X>` and `plain` into `<X>`.

### 5.2 Arrow boundary

Add `text_span_splice(values, *, detector_ids, outs, gap_out, catalog_version, splice_contract_version, native_threads=None)` and `text_span_splice_contract_version()` to the ABI 3 wheel. On the wire, use None for Verbatim and a string for Replace. An empty replacement string is valid. Pair each requested ID with one outcome. Reject malformed types, lengths or conflicting duplicate outcomes with fixed messages. Resolve names to catalog indices once per call. Reject unknown IDs. Keep both legacy exports and their signatures for the lifetime of ABI 3. Apply the new wire checks only at the new entry. The old detect wrapper resolves repeated IDs with its existing last-assignment rule before calling the shared core.

Inspect each original Python version object before numeric extraction. Require exact Python int type and equality to the expected value, including at probe time. Reject bool, int subclasses, strings and out-of-range integers. Map failure to the corresponding catalog or splice contract code. The catalog version is 2 at the anchor. The new splice contract version is 1.

Import each input Array once. Accept string and large_string. Reject other Arrow types with the registered unsupported-type code. Before scanning a large_string row, check that its byte length fits the u32 span offsets in `crate/text_redact/detect.rs:35`. Mark a wider row for oracle detection and splice without narrowing its offsets. The crate enables Arrow FFI validation (`Cargo.toml:30-37`). Detach the loop only after importing the buffers and owning the options. Keep Python objects outside the detached loop.

In the common case return one pair of arrays in a one-piece sequence. Larger results use the same sequence format. Each pair holds a StringArray and a BooleanArray. Together the pieces cover the input slice once. Start a fresh piece before appending a row whose actual UTF-8 output would overflow the cumulative string offset. Use checked sizes for replacement expansion. Bound each input call by 65,536 rows as well. Flush both builders at the same row. Finish each string builder before export. Each mask element is true only for a non-null declined cell. Limit the initial buffer reservation to the checked piece size. An input slice can have a large backing buffer even when the output fits. Test the byte ceiling at a reduced value without changing the production limit. Obtain the byte ceiling from the existing Arrow offset policy for Python assembly. Exercise the Rust builder with the same ceiling via its internal test seam. A single row cannot be split. Preserve the old string builder's behavior for an individually unrepresentable value, with a fixed value-free failure if it exceeds the real offset domain. A cell larger than a test batching target but representable in production can occupy its own piece.

### 5.3 Python side

The new path takes public empty selections only after route normalization to None. Reserve the zero-detector shortcut for a direct text_redact call with a resolved empty tuple. A text_mask call with zero span detectors must still apply its gap policy.

Change `requested_rust_ids(None)` to expand `_SPAN_DETECTORS` in insertion order, filtered to `SUPPORTED_IDS`. Explicit lists keep first-seen order. Ignore unknown names as the oracle does. Keep catalog order for interpreting Rust candidate indices. The Python merge still replays the requested order (`_text_redact_kernel.py:186-197`). If a known Python detector lacks a Rust implementation, keep its existing candidate/merge path. S2 builds text_mask's per-ID outcomes in the order returned by the shared resolver.

1. Resolve E1, E1b, the private zero-detector case and literal eligibility. Keep non-string wrapper inputs on the old null-aware stringification path. Preserve string output for large_string and private empty selections.
2. Walk chunks and offset slices in input order. Pass bounded Arrow slices to the new entry. Check pair structure, concrete Arrow types, equal piece lengths, forward progress and exact coverage. Match each piece to the corresponding source slice. A zero-row input yields a typed empty string array.
3. In one shared `_checked_splice_output`, first require a Boolean Array of exactly the corresponding input length, with zero null mask elements. Forbid a true bit on null input. Then require a string Array of that length, null exactly where input is null or the mask is true. A missing or extra row, wrong type or wrong validity takes E7 before repair.
4. Filter only true positions. Apply the existing strategy fallback once per declined cell. Scatter in order. Use wide offsets for the scatter intermediate if repaired rows expand. Reuse `split_narrow_text` in `src/decoy_engine/_arrow_types.py` to cut wide intermediates before narrowing. Check the final null bitmap against the input, including after any predicate write-back. Preserve empty and all-null types at route assembly. Keep eligible input and output off Python lists.
5. Keep a single Array when it fits. Otherwise retain the ordered string chunks. Never concatenate into one int32 domain unless the sum of the sliced payload bytes fits. The old `pa.array(list, type=pa.string())` can itself return a ChunkedArray on aggregate overflow. Sequential already consumes either with `.to_pylist()`. Return `(values, ran)` for text_redact and `(values, notices, ran)` for text_mask. OR actual splice evidence over all pieces.
6. Carry chunks through table consumers. Widen the result annotations on StepResult, NativeResult and their consumers. Keep the conditional path for other strategies intact. Update unified `physical/_shadow_assembly.py:69` to accept chunked text parts and preserve empty/all-null schema rules. For masked steps at `native/_operator_step.py:540-562`, scatter over aligned source, mask and replacement slices. Size the result for selected replacements plus retained rows. Keep original positions for unselected rows.
7. At a RecordBatch boundary, assemble already-masked columns into a Table and use aligned row slices (Table.to_batches) if the result needs several string chunks. Out-of-core currently insists on one Array per column at `_text_redact_native.py:230` and `_text_mask_native.py:264`. Validate the logical column type and length there. Feed one Array per aligned slice to batch assembly at `out_of_core/_mask.py`. Preserve an empty batch and its schema for zero-row input. Pair every masked piece with the identical row slice of the raw batch. Use that pair for vault collection and the original key source for FK joins. Stream every resulting batch through both `_stream_driver.py:360` and `_rewrite_pass.py:219`. Keep the one-batch API for existing callers whose result fits. Share the masking pass. Never rerun a sibling strategy, warning or decision to split output. Keep row accounting per original call.

**Boundary errors.** Extend `_translate_compiled_kernel_error` in `native/_crypto_ext.py:362`. Keep its sole `str(exc).partition(": ")` assignment in that function. Dispatch by caller family. FPE delegates there for its two determinism codes. Preserve crypto's extra type mapping and each legacy family's unknown-error behavior. For splice, match the prefix only against the registered splice reasons. Construct the mapped ExecutionError from the registry symbol and its fixed summary. Ignore all detail and map unexpected exception types or codes to `text_splice_output_invalid`. E7 uses the same fixed factory. Raw Rust errors from the new interface also have fixed messages. Raise the engine error after leaving the handler so cause and context are empty. Chunked, sequential and out-of-core propagate the fault. The unified coordinator's existing generic reroute uses the full-frame oracle. Test both the local exception and the route outcome.

Remove `audit::execution/native/_fpe_ext.py::_translate_compiled_fpe_error::str(exc)::assign` from `engine-exception-text-copies.json`. Keep the crypto key in place. Lower AUDIT_PARITY from 100 to 99 and total copies from 107 to 106. Remove the obsolete FPE producer site `execution/native/_fpe_ext.py::_translate_compiled_fpe_error::kw::code` from the F29 producer fixture and its baseline (1,382 to 1,381 rows and 1,212 to 1,211 distinct keys). Use explicit registered symbols in new factories. Do not move the remaining crypto producer sites. Run the live census, baseline registry equality, F29 guards and `scripts/dev/ratchet_check.py` against the merge base. No new key or higher maximum is permitted.

**Recording.** The step carries `ran` and the existing notices on StepResult. For text_redact, record whether the `when:` predicate selected any row independently of `ran`. The zero-selection return at `_operator_step.py:542` did no strategy work. Selected rows masked on Python activate the branch even when every Rust cell declined. Keep the existing unmasked count, the absence of a never-activated strategy, and other strategies' counting rules (`_chunk_masking.py:268`, `_chunked_evidence.py:172`).

Add optional `ran` to NativeResult. Sequential records each call once and ORs `spliced` with the result. Replace the recorder at `execution/_sequential_native.py:470` in S1b and the separate recorder at line 487 in S2. Keep both replacements at zero net lines. Preserve text_mask notice counts through the step, `execution/_sequential_native_text_mask.py:65` and the out-of-core accumulator. Keep the key and its cleanup in their current owners when moving the Arrow fast path ahead of list conversion. Emit the existing passthrough warning once per applicable nonempty cell, including on the new Arrow path. For legacy text_mask, count successful Rust splice results before Python fills declined rows. Candidates alone and hybrid FF1 with Python splice give no splice credit.

### 5.4 Route label

In the operator registry, change only the planned backend to RUST_COMPANION for the strategy in its slice. Keep required_kernel=None and positive_kernel_evidence=False. The latter would otherwise reject a legitimate idle unified run (`execution/_unified_slice_evidence.py:125`). Use the existing `executed_backend` selector for every **admitted, nonempty** decision. Supply its planned backend, native_admitted=True and kernel_idle equal to the absence of any actual splice. Call through a layer-safe public export. Do not duplicate this choice in the sequential entry at `_sequential_native_decisions.py:62` or the two out-of-core entries at `_text_redact_native.py:112` and `_text_mask_native.py:132`.

| Case | Unified and chunked | Sequential and out-of-core |
|---|---|---|
| Any admitted batch splices, including a public empty selection that masks an email | rust_companion | rust_companion |
| All admitted batches idle, including candidates plus Python splice | arrow_python | arrow_python |
| Compatible old wheel splices text_mask via legacy export | rust_companion | rust_companion |
| Companion absent, otherwise eligible text | arrow_python when admitted | python_scalar and the existing decline reason for nonempty input |
| Source or config declined | Keep route's oracle label and reason. | Keep python_scalar and its reason for nonempty input. |
| No rows | Preserve route's empty behavior and idle label where evidence is emitted. | Keep none and the route-owned reason. |

The unified evidence flag and the chunked fold already retain a positive batch. Use a sticky flag on the other decisions. Route owners still determine zero-row and admission-decline records. `native_calls` counts helper calls, including an all-null call. A capability probe or its known-answer call never counts as job execution.

## 6. Placement

| Change | Location | CODEMAP placement and size constraint |
|---|---|---|
| Shared core, exports and Rust tests | `crate/text_mask.rs`, `crate/arrow_ffi.rs` | Native crate. Restrict the FFI edit to exposing existing functions. |
| Probe, order, UTF-8 guard and Arrow repair | `execution/native/_text_redact_kernel.py`, `_text_mask_native_splice.py`, `_kernels_scalar.py` | Native companion bridge (CODEMAP:273). Both strategies call the same boundary validator and byte-aware assembly. |
| Error mapping and reasons | `execution/native/_crypto_ext.py`, `_fpe_ext.py`, `reasons/runtime/_part3.py` | Extend the existing parser in place. Use the runtime registry for public messages. |
| Step, evidence and assembly | `execution/native/_operator_step.py`, `_chunk_masking.py`, `_chunked_evidence.py`, native package export, `execution/physical/_shadow_operators.py`, `_shadow_batch_runner.py`, `_shadow_assembly.py` | Existing step and evidence owners. Use the existing Arrow width helpers. |
| Admission evidence and result transport | `execution/_operator_registry.py`, `_sequential_native_ops.py`, `_sequential_native_text_mask.py`, `_sequential_native.py`, `_sequential_native_decisions.py` | Pipeline spine and routes. Keep the 700-line sequential pin. Keep the ops file (593 lines) at or below 600 so it needs no dense-module entry. |
| Batch dispatch and streaming | `execution/out_of_core/_text_redact_native.py`, `_text_mask_native.py`, `_mask.py`, `_stream_driver.py`, `_rewrite_pass.py` | Existing route owners. Keep one common batch emitter for aligned output pieces. |
| Tests | New `tests/unit/execution/native/test_text_span_splice.py`. Extend existing native, parity and sentry tests. | Unit tests mirror the source package (CODEMAP:306). Put new coverage in the new unit file. Keep edits to existing oversized suites size-neutral or smaller. |
| Docs and release | `docs/execution-backends.md`, `docs/compatibility-contract.md`, new `changelog.d/text-redact-rust-splice.md` | Describe the evidence change, both skew directions and all five section 4.3 codes. |

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
| Final-head mutations | Rerun M1 to M10 on the applicable final implementation head, including M6 after S2. Record the SHA and the failing assertion. |
| Allowlisted helpers | Exercise route helpers through their callers and run the physical-seam sentry. |
| Raised pins | Run size, layout, census, release and merge-base guards. Apply the exact reductions in section 5.3. |

## 8. Acceptance tests

| ID | Test and decisive observation | Slice |
|---|---|---|
| AT-1 | Compare native text_redact to the handler. Cover every built-in, adjacent and overlapping spans, duplicates, unknown names, permutations, nulls, empty and long strings. Include both label modes, two literal tokens and the existing ties on 12345-6789 and -2283038836. Direct private resolved () preserves a known email and reports false. The same input with None masks it. | S1b |
| AT-1b | Wrap the real entry after its probe. Use uniquely identifiable rows across at least two batches. Record each input slice and its returned mask. Mark each eligible output in a second instrumented run and require every mark at the same output position. This detects a discarded Rust result even when the oracle bytes would agree. Assert every eligible row occurs once in the Rust output and every ineligible non-null row occurs once in the Python repair. Include nulls, empty strings, 0x1c through 0x1f and non-ASCII. An aggregate ran flag cannot satisfy this test. | S1b |
| AT-2 | Compare bytes and validity at batch sizes 1, 7, 65,536 and whole input. Test thread budgets 1 and 4 at the new boundary. Both run the single-thread loop. | S1a raw entry, S1b wrapper |
| AT-3 | Exercise string, large_string, offset slices, uneven chunks, zero chunks, empty and all-null input. Raw int64 input gets ValueError with text_splice_unsupported_type. Wrapper integer, float and Boolean inputs retain Python stringification. With a required surrogate token a no-match cell returns plain text. With label mode the same token and a known email give the detector label on Rust. | S1a raw entry, S1b wrapper |
| AT-3 (capacity) | Lower the batching byte ceiling. Use the same reduced ceiling at the builder, scatter and consumer assembly so the aggregate test cannot pass by concatenating. Expand many short matches with a long token within one input batch. Separately exceed the ceiling across individually fitting batches. Include an expanding declined row and a retained predicate row. Assert bytes, schema, row order, nulls and counts through chunk-capable consumers and single-Array batch sinks. Include a sibling key column. Verify the raw-to-masked vault pairs, FK results and every emitted batch in both out-of-core passes. Exercise the large-cell offset guard with a reduced detector-offset limit and a match beyond that limit. | S1b, S2 |
| AT-3 (invalid output) | Inject wrong pair shape, missing/extra pieces, wrong output type/length, non-Boolean mask, wrong mask length, a null mask element beside a true bit, true on null input, unexpected null output and missing required nulls. Force a bad final null position after scatter. Each raises text_splice_output_invalid at the wrapper. | S1b |
| AT-4 | Pin text_mask email passthrough plus redacted gaps with token `<X>`. Input `before a@b.com after` gives exactly `<X>a@b.com<X>`. A nonempty no-match cell gives `<X>`. Empty input gives the empty string. Also cover redacted spans with verbatim gaps, adjacent spans, warning multiplicity and aggregate sub-floor notices. Compare the legacy and new entries and the handler. | S1a core, S2 routes |
| AT-5 | Run every applicable section 5.4 case on all four routes. Submit public text_redact `detectors: []`, token `<X>` and `mail a@b.com now`. Require `mail <X> now` and rust_companion on each current-wheel route. For text_mask set every built-in to redact and gaps to passthrough for the same assertion. Check absent companion, non-string admission decline, no rows, all-null and all-ineligible admitted columns. Verify bytes, schema, label, decline reason and helper counts. Run idle then spliced and spliced then idle across batches. | S1b redact, S2 mask |
| AT-5 (predicate) | On chunked text_redact select a non-ASCII row containing an email. Assert its masked bytes, unchanged unselected bytes, arrow_python and one branch activation. Select no rows and assert original bytes, arrow_python and no strategy entry. Repeat with a selected no-match Python row so identical output and backend still yield different counts. Preserve the existing chunked text_mask predicate rejection. | S1b |
| AT-6 | At probe time vary callable presence, ABI, catalog version, ordered IDs, contract version and KAT output independently. Reject wrong exact types, including True for version 1. A failed new-capability probe takes E1b if candidates are usable. After a successful probe, inject each version argument independently with bool, string, subclass and wrong integer. Also send an unknown ID past resolution. Assert the raw ValueError code, then the translated engine code. Verify no helper fallback and the route outcomes in section 5.3. Exercise both wheel/core skews in section 10a. | S1a probe and raw codes, S1b translation and route outcomes, S2 skew |
| AT-7 | Interleave eligible rows, null, distinct Unicode rows and ASCII controls. Include tab, NUL, DEL and CRLF as eligible controls. Assert ordered bytes against the oracle. Inject known-code detail and an unknown exception containing a unique data sentinel after a successful probe. Require fixed public messages, absent sentinel on exposed error, warning and job-log surfaces, and no cause or context on the translated exception. | S1b |
| AT-8 | Rust unit tests cover label replacement, Verbatim and both gap outcomes. Use email and IPv4 on `10.0.0.1a@b.com` in both orders. The longer email wins. A constructed exact tie under two requested orders must select the first label. | S1a |
| AT-9 | On the Dell run the section 1 workload through the complete helper. Require at most 3.0 microseconds per row. Independently instrument the all-eligible path after probing: forbid per-cell Python fallback, input to_pylist and list-backed pa.array construction. Check the real returned Arrow bytes outside instrumentation. | S1b, S2 conversion guard |
| AT-10 | Run one corpus end to end on unified, chunked, sequential and out-of-core with the companion built. Include nulls, declines, both label modes and tie strings. Compare bytes, validity, schema and text_mask diagnostics with the corresponding oracle route. | S1b, S2 |

**Existing regression suites.** In S1b update direct-return helpers and the spec check in `tests/native/test_c6c_i_text_redact_kernel.py`. Update the helper at `test_c6c_ii_text_redact_rust.py:72` and the resolver expectation at line 648. Keep its non-string regression at line 331. Retain candidates-only tests on an explicitly legacy wheel or stub. For live splice assertions, retarget the spies and discard-output mutations to the new entry, including `tests/parity/test_phase_d_audit_no_legacy.py:482`. Update the sequential real and routing fixtures (`test_phase_d_text_redact_seq.py` and `test_phase_d_text_redact_seq_real.py`). Run `test_ooc_text_redact_native_real.py`. Update the out-of-core marking helpers and all-null backend expectation (`test_ooc_text_redact_native_routing.py:175`). Retain consumed-output and mid-run failure assertions.

In each strategy's slice update its planned-backend entry in `tests/sentry/test_unified_backend_map.py:40` and `tests/native/test_operator_tables_snapshot.py:86`. Update the latter's exact derived companion-strategy set at line 215. These are behavior snapshots. Update the C6c text_redact and C6b text_mask `tests/native/*_chunked.py` and `tests/physical/*_unified.py` suites in S1 and S2 respectively. Their planner, executed-backend, sibling-column and idle assertions must distinguish admitted Python work from a real splice. In S2 update tuple unpacking, marking fixtures, spliced-cell spies and negative controls across the C6b detection, splice and FPE suites, sequential parity and `test_ooc_text_mask_native.py`. Preserve the per-cell warning assertion at `test_c6b_ii_b_text_mask_splice.py:306` and notice-count assertions on all three call seams. Run both real and marked route suites. Search all direct helper callers when changing the return shapes.

## 9. Named mutations

| ID | Mutation | Witness that must fail |
|---|---|---|
| M1 | Sort same-start spans shortest first. | AT-8 unequal-length email/IPv4 case. |
| M2 | Drop the detector ID from a label. | AT-1 and AT-8 literal label. |
| M3 | Shift a declined replacement one position. | AT-7 interleaved values and final validity. |
| M4 | Catch a post-probe boundary failure and use Python. | AT-6 wrapper assertion. |
| M5 | Report the planned backend regardless of execution. | AT-5 all-idle admitted nonempty column. |
| M6 | Replace a Verbatim text_mask span with the token. | AT-4 literal passthrough email between redacted gaps, through the S2 route. |
| M7 | Rebuild eligible output with pa.array from a Python list. | AT-9 deterministic conversion guard. Also run the independent Dell floor. |
| M8 | Set positive_kernel_evidence=True. | AT-5 admitted idle unified column must complete. |
| M9 | Expand None in catalog order. | Python resolver unit test compares to filtered _SPAN_DETECTORS insertion order. |
| M10 | Process only the first input chunk. | AT-3 compares values and validity beyond that chunk. |

Run each mutation separately against the unmutated passing tests. Restore it before the next run. S1a runs M1 and the Rust half of M2 against AT-8. S1b runs M2 to M5 and M7 to M10. S2 runs M6. Record all ten results again on the final head with both strategies wired.

## 10. Byte changes

No masked-byte change is intended. The changelog describes the execution-label change in both directions, including the idle case. AT-1, AT-4 and AT-10 gate the byte contract.

## 10a. Frozen contracts

Use the additive capability policy in `docs/native/supported-matrix.md:108`. Keep ABI 3. Probe callability of the new entry and agreement helpers, exact ABI tag, exact integer catalog version, ordered supported IDs and exact integer splice contract version. Use the core's existing ABI constant. Run a known-answer splice on [`a@b.com`, `café`, null] with the email detector, Replace(`<X>`) and verbatim gaps. Require [`<X>`, null, null] and mask [false, true, false], with exact Arrow types and lengths. Bind the verified callable to that companion instance. Cache a successful probe outside the row loop. No customer data enters the probe.

An old core must load both `text_mask_detect_splice` and `text_mask_splice_spans` from the S2 wheel and get its old list shapes, bytes and decline sentinels. Keep the old positional parameters, gap policy and exported semantics. Run the old core against the built S2 wheel. Spy on both legacy lookups and the actual legacy splice call. Compare its results and warnings to the old oracle. In the reverse direction test the new core against an ABI-3 wheel with candidates and the two legacy symbols. It uses candidates and Python splice for text_redact. It uses the working legacy Rust splice for eligible text_mask and reports rust_companion only if that splice produced a non-null cell result. Missing legacy capability keeps the existing Python splice. Never send job data to a wheel with an incompatible ABI via the new or legacy splice. Keep existing route admission gates distinct from the new capability probe.

## 10b. Pre-mortem

- An overlap can preserve output length while leaking part of a span. AT-8 checks literal bytes for unequal lengths and the winning label for an exact tie.
- A decline mask can silently erase an input row. AT-3 injects that fault before and after repair.
- A row-count bound can miss replacement expansion. AT-3 exercises both a single expanding call and aggregate overflow at actual consumers.
- A detector scan or KAT can look like job execution. AT-1b and AT-5 require job-row evidence.
- A legacy client can silently lose acceleration after a wheel upgrade. AT-6 exercises both directions.

## 11. Slices

Estimates include changes to existing tests and route assembly. Every slice is R2. Build the companion and run the targeted T2 suites with the real extension. Record test scope, skips, mutations and perf evidence. Code reviewers: Codex and Dennis.

Test-first order in every slice: write the slice's acceptance tests first, run them on the slice base and record that each fails for the stated reason (or, for a guard such as the AT-4 legacy comparison, passes before and after). Then implement until they pass. Then run the slice's mutations.

Each slice merges on its own. S1a adds the Rust entry, the ABI 3 wrappers and the probe, but no Python route calls the new entry yet, so masked bytes and labels do not change except through the legacy text_mask wrappers, which AT-4 pins. S1b starts from merged S1a. S2 starts from merged S1b.

| Slice | Content | Size estimate | Risk and gate |
|---|---|---|---|
| S1a | Rust core: shared span outcomes, independent gap outcome, `text_span_splice` and `text_span_splice_contract_version`, Arrow pieces with byte-safe piece splitting and the Boolean mask export (exporters made `pub(crate)`). The legacy `text_mask_detect_splice` and `text_mask_splice_spans` stay as permanent ABI 3 wrappers over the shared core. The Python capability probe `load_text_span_splice` with exact-int version checks and the known-answer splice (section 10a), unit tested but not yet called by a route. | M, about one builder-day: about 250-350 implementation lines and 200-300 test lines. | R2 (the live text_mask wrappers move onto the new core). Acceptance: AT-8; AT-4 core (legacy wrappers and the new entry against the handler); AT-2 and AT-3 at the raw entry (types, offsets, chunks, int64 raw code); AT-6 probe-time cases and raw ValueError codes. Mutations M1 and the Rust half of M2. |
| S1b | text_redact wiring: `native_text_redact` on the new entry with chunk walk, byte-safe assembly, mask validation, decline scatter; error mapping in the existing parser with the census reductions; resolver order fix; shared backend selector, branch count and the first sequential recorder; out-of-core caller; spec `planned_backend`, snapshots, spies, docs and the release fragment. | M, about one builder-day: about 250-400 implementation lines and 300-400 test lines. | R2. Acceptance: AT-1, AT-1b, AT-2 and AT-3 at the wrapper, AT-3 (capacity) and AT-3 (invalid output), AT-5 and AT-5 (predicate) for text_redact, AT-6 translation and route outcomes, AT-7, AT-9, AT-10 for text_redact. Mutations M2 to M5 and M7 to M10. Dell floor, live census and merge-base ratchet. |
| S2 | Wire text_mask to the shared core with explicit gap outcome. Keep legacy splice evidence, warnings and notices. Update all three callers, the second sequential recorder, snapshots, spies, skew tests and docs. | M, about 120-220 implementation lines and 180-300 test lines. | R2. AT-3 to AT-7 as applicable, AT-9 conversion guard and AT-10. Run old core with S2 wheel and the reverse. Rerun M1-M10 on the final head, including M6. |

## 12. Open questions for the owner

The plan assigns text_mask evidence to S2 so the label changes with the implementation. The open scheduling choice is whether to defer that evidence change to ROUTE-LABEL-TRUTH. S2 and its gates assume it ships here.
